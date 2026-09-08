"""DataLoader rules: MLV110 (no shuffle), MLV111 (shuffled eval), MLV112 (spawn).

All three read one `torch.utils.data.DataLoader(...)` construction and the
context around it; none of them needs torch installed.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, LoopIR
from ..ir.symbols import dotted_text
from .helpers import calls_in_loop, literal_of, with_role
from .registry import rule

__all__ = ["train_loader_not_shuffled", "eval_loader_shuffled", "workers_without_guard"]

LOADER_FQN = "torch.utils.data.DataLoader"
_TRAIN_LOADER_RE = re.compile(r"(?i)^(train_?(loader|dl|data|batches)?|(loader|dl)_?train)$")
_EVAL_LOADER_RE = re.compile(r"(?i)^(val|valid|validation|test|eval|holdout)_?"
                             r"(loader|dl|data|batches)?$")
_SEQUENCE_HINT_RE = re.compile(r"(?i)(sequence|sequential|timeseries|time_series|curriculum"
                               r"|series|forecast|temporal)")
_SAMPLER_KEYS = ("sampler", "batch_sampler")


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------
def loader_calls(ctx) -> List[CallSite]:
    return ctx.calls_of(LOADER_FQN)


def dataset_arg(ctx, call: CallSite):
    """`(name, ValueRef)` for the loader's `dataset` argument."""
    node = call.args[0] if call.args else call.kwarg_nodes.get("dataset")
    if node is None:
        return None, None
    name = dotted_text(node)
    if not name:
        return None, None
    return name, ctx.binding_of(name, call.scope)


def loader_name(call: CallSite) -> str:
    return (call.var or "").split(".")[-1]


def iterating_loops(ctx, call: CallSite) -> List[LoopIR]:
    """Every loop that iterates the value this loader was bound to."""
    out: List[LoopIR] = []
    if not call.var:
        return out
    for loop in ctx.loops():
        if loop.module is not call.module:
            continue
        if loop.iterates is not None and loop.iterates.producer is call:
            out.append(loop)
        elif loop.iter_text and loop.iter_text.split(".")[-1] == call.var.split(".")[-1]:
            out.append(loop)
    return out


def _loop_has_role(ctx, loop: LoopIR, *roles: str) -> bool:
    return bool(with_role(calls_in_loop(ctx, loop), *roles))


def _is_iterable_dataset(ctx, ref) -> bool:
    """`IterableDataset` cannot shuffle, so MLV110 must skip it."""
    if ref is None:
        return False
    cls = ref.class_ir
    if cls is not None and any("IterableDataset" in b for b in cls.resolved_bases):
        return True
    producer = ref.producer
    fqn = producer.fqn if producer is not None else None
    return bool(fqn and fqn.endswith("IterableDataset"))


def _has_sampler(call: CallSite) -> Optional[str]:
    for key in _SAMPLER_KEYS:
        node = call.kwarg_nodes.get(key)
        if node is None:
            continue
        if isinstance(node, ast.Constant) and node.value is None:
            continue
        return key
    return None


def _int_kwarg(ctx, call: CallSite, key: str) -> Optional[int]:
    """A kwarg resolving to an int literal, directly or via a constant binding."""
    literal = call.kwargs.get(key)
    if literal is None:
        node = call.kwarg_nodes.get(key)
        if node is None:
            return None
        literal = literal_of(ctx, node, call.scope, call.module)
    if literal is None:
        return None
    try:
        return int(float(literal))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# MLV110
# ---------------------------------------------------------------------------
@rule(code="MLV110", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["data", "correctness"],
      title="Training DataLoader does not shuffle",
      why="Batches arrive in dataset order, so gradients are correlated with however "
          "the files were sorted and the model can learn the ordering instead of the task.",
      fix_hint="Pass shuffle=True to the training DataLoader, or give it a shuffling "
               "sampler such as RandomSampler / DistributedSampler.")
def train_loader_not_shuffled(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in loader_calls(ctx):
        shuffle = call.kwargs.get("shuffle")
        if shuffle == "True":
            continue
        sampler = _has_sampler(call)
        if sampler:
            continue
        name, ref = dataset_arg(ctx, call)
        if _is_iterable_dataset(ctx, ref):
            continue
        training, evidence, tagged = _training_loader(ctx, call, ref)
        if not training:
            continue
        node = ctx.node_for_call(call)
        if node is None:
            continue
        if not tagged:
            evidence.append(("name_regex",
                             "%s only matches the training-loader naming convention"
                             % loader_name(call), 0.8))
        if _sequence_hint(ctx, call, name):
            evidence.append(("context_confirmed",
                             "the dataset name hints at sequence modelling, where "
                             "ordered batches can be deliberate", 0.6))
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The training DataLoader at %s:%d is built with shuffle=%s and no "
                    "sampler=, so %s is consumed in dataset order every epoch."
                    % (call.loc.file, call.loc.line, shuffle or "unset (defaults to False)",
                       name or "the dataset"),
            loc=call.loc, node_ids=[node],
            related=[("construction", call.loc, "DataLoader built here")],
            evidence=evidence, dynamic=call.scope.is_dynamic))
    return issues


def _training_loader(ctx, call: CallSite, ref) -> Tuple[bool, List, bool]:
    """Is this a *training* loader, and how do we know?"""
    evidence: List = [("fqn_resolved", "DataLoader resolved through the import table", 1.0)]
    if ref is not None and ref.has("TRAIN_SPLIT"):
        evidence.append(("dataflow_direct",
                         "%s carries TRAIN_SPLIT from the split" % ref.name, 1.0))
        return True, evidence, True
    for loop in iterating_loops(ctx, call):
        if _loop_has_role(ctx, loop, "BACKWARD"):
            evidence.append(("context_confirmed",
                             "the loop at line %d over this loader calls backward()"
                             % loop.loc.line, 1.0))
            return True, evidence, True
    if _TRAIN_LOADER_RE.match(loader_name(call)):
        return True, evidence, False
    return False, evidence, False


def _sequence_hint(ctx, call: CallSite, dataset_name: Optional[str]) -> bool:
    text = " ".join(filter(None, [dataset_name, call.loc.file, loader_name(call)]))
    return bool(_SEQUENCE_HINT_RE.search(text))


# ---------------------------------------------------------------------------
# MLV111
# ---------------------------------------------------------------------------
@rule(code="MLV111", severity="low", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["data", "reproducibility"],
      title="Evaluation DataLoader shuffles",
      why="Predictions no longer line up with the dataset order, so per-sample "
          "inspection and confusion matrices differ from run to run.",
      fix_hint="Use shuffle=False on validation and test DataLoaders so predictions "
               "stay aligned with the dataset order.")
def eval_loader_shuffled(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in loader_calls(ctx):
        if call.kwargs.get("shuffle") != "True":
            continue
        name, ref = dataset_arg(ctx, call)
        tagged = ref is not None and ref.has("VAL_SPLIT", "TEST_SPLIT")
        named = bool(_EVAL_LOADER_RE.match(loader_name(call)))
        if not tagged and not named:
            continue
        node = ctx.node_for_call(call)
        if node is None:
            continue
        evidence = [("fqn_resolved", "DataLoader resolved through the import table", 1.0)]
        if tagged:
            evidence.append(("dataflow_direct",
                             "%s carries %s from the split"
                             % (ref.name, "/".join(t for t in ref.tags
                                                   if t in ("VAL_SPLIT", "TEST_SPLIT"))), 1.0))
        else:
            evidence.append(("name_regex",
                             "%s only matches the evaluation-loader naming convention"
                             % loader_name(call), 0.8))
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The evaluation DataLoader at %s:%d passes shuffle=True over %s, so "
                    "predictions come back in a different order each run."
                    % (call.loc.file, call.loc.line, name or "the held-out dataset"),
            loc=call.loc, node_ids=[node],
            related=[("construction", call.loc, "DataLoader built here")],
            evidence=evidence, dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV112
# ---------------------------------------------------------------------------
@rule(code="MLV112", severity="medium", base_prior=0.98, frameworks=["torch"],
      rule_version=1, tags=["portability", "data"],
      title="DataLoader worker processes without a __main__ guard",
      why="Windows and macOS start workers with spawn, so each worker re-imports the "
          "module; without a guard the module-level training code runs again in every "
          "worker and the program hangs or recurses.",
      fix_hint="Move the entrypoint into a function and call it from "
               "if __name__ == \"__main__\": main().")
def workers_without_guard(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in loader_calls(ctx):
        workers = _int_kwarg(ctx, call, "num_workers")
        if not workers or workers <= 0:
            continue
        module = call.module
        reason = _runs_at_import(call)
        if reason is None:
            continue
        node = ctx.node_for_call(call)
        if node is None:
            continue
        evidence = [
            ("fqn_resolved", "DataLoader resolved through the import table", 1.0),
            ("negation_absent", reason, 1.0),
        ]
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="DataLoader(num_workers=%d) at %s:%d, but %s - on Windows and macOS "
                    "every worker re-imports %s."
                    % (workers, call.loc.file, call.loc.line, reason, module.relpath),
            loc=call.loc, node_ids=[node],
            related=[("construction", call.loc, "worker processes requested here")],
            evidence=evidence, dynamic=call.scope.is_dynamic))
    return issues


def _runs_at_import(call: CallSite) -> Optional[str]:
    """Why this loader is built while the module is being imported, or None.

    Spawn re-imports the module inside every worker, so the footgun is a
    loader that is *constructed at import time*: at module scope outside the
    guard, or in a helper that module scope calls. A loader built inside a
    function that only the entrypoint calls is import-safe, guard or no guard -
    firing on that would accuse most library modules in the world.
    """
    module = call.module
    guard = module.main_guard
    if call.function is None and call.class_ir is None:
        if guard is not None and _inside(guard, call.node):
            return None
        if guard is not None:
            return "the loader is constructed at module scope, outside the guard"
        return ("the loader is constructed at module scope and the module has no "
                "if __name__ == \"__main__\" guard")
    func = call.function
    if func is None:
        return None
    for caller in module.calls:
        if caller.target_function is not func:
            continue
        if caller.function is not None or caller.class_ir is not None:
            continue
        if guard is not None and _inside(guard, caller.node):
            continue
        return ("%s() is called at module scope (line %d), so the loader is built while "
                "the module is imported" % (func.name, caller.loc.line))
    return None


def _inside(container: Optional[ast.AST], target: ast.AST) -> bool:
    if container is None:
        return False
    for child in ast.walk(container):
        if child is target:
            return True
    return False
