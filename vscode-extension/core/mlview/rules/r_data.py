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
from .fixes import shuffle_false_fix
from .helpers import (KWARG_ABSENT, KWARG_RESOLVED, UNRESOLVED_KWARG_WEIGHT,
                      calls_in_loop, kwarg_literal, literal_of,
                      note_unresolved_kwarg, with_role)
from .registry import rule

__all__ = ["train_loader_not_shuffled", "eval_loader_shuffled", "workers_without_guard"]

LOADER_FQN = "torch.utils.data.DataLoader"
_TRAIN_LOADER_RE = re.compile(r"(?i)^(train_?(loader|dl|data|batches)?|(loader|dl)_?train)$")
#: DGRG2-11 / VIS2-18. `dev` is the canonical held-out name in LibriSpeech
#: (`dev-clean`), GLUE and CoNLL; `query` and `gallery` are the canonical names
#: in retrieval and re-identification. Both were missing, so
#: `dev_loader` and `query_loader` could not be evaluation loaders at all.
#: Reinforcing-only under iron law 2 - the regex cannot create a tag, only let
#: a finding that already has dataflow or structural evidence be seen - so
#: widening it costs no precision.
_EVAL_LOADER_RE = re.compile(r"(?i)^(val|valid|validation|dev|devel|test|eval|holdout|"
                             r"query|gallery)_?"
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


def dataset_split_key(call: CallSite) -> Optional[str]:
    """The literal split key of a subscripted dataset argument (NLP-14).

    `DataLoader(split["test"], shuffle=True)` names the held-out split right
    there in the constructor, and MLV111 stayed silent because the subscript
    carries no dataflow tag (NLP-03) and the variable was called `loader`
    rather than `test_loader`, so nothing reinforced. Iron law 2 is satisfied:
    this is evidence of exactly the kind a variable name already provides -
    reinforcing, never creating - and it is charged the same x0.8 factor.
    """
    node = call.args[0] if call.args else call.kwarg_nodes.get("dataset")
    while isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
        node = node.value
    return None


def loader_name(call: CallSite) -> str:
    return (call.var or "").split(".")[-1]


def iterating_loops(ctx, call: CallSite) -> List[LoopIR]:
    """Every loop that iterates the value this loader was bound to.

    vision-12: `call.var` is the name the construction was assigned to, and a
    `def build_loader(): return DataLoader(...)` factory assigns it to nothing
    - so the documented MLV110 clause "a loader also counts as a training
    loader if the `for` loop iterating it contains a `.backward()` call" could
    never apply to the layout every project bigger than one file uses. The
    caller's binding is the loader's name; one hop finds it.
    """
    out: List[LoopIR] = []
    names, cross_module = _loader_binding_names(ctx, call)
    if not names:
        return out
    for loop in ctx.loops():
        if loop.iterates is not None and loop.iterates.producer is call:
            out.append(loop)          # value identity: always correct
            continue
        if not loop.iter_text:
            continue
        tail = loop.iter_text.split(".")[-1]
        if tail not in names:
            continue
        # PUB2-02. The guard here read
        #     `if tail in names and (loop.module is call.module or tail in names)`
        # and `A and (B or A)` is `A`, so the module check never applied: EVERY
        # loop in the workspace whose iterable ended in the same bare
        # identifier was attributed to this construction. Measured on
        # pytorch/tutorials, a correctly built `test_loader` in
        # knowledge_distillation_tutorial.py was reported as "the **training**
        # DataLoader ... consumed in dataset order every epoch", with the
        # decisive evidence "the loop at line 272 over this loader calls
        # backward()" - line 272 of that file is prose inside a comment block,
        # and the loop lives in fgsm_tutorial.py, a different module with a
        # different `test_loader` over a different dataset.
        #
        # A bare identifier match is only allowed where the name really did
        # travel: the same module, or one of the modules that call the factory
        # this loader is returned from.
        if loop.module is call.module or id(loop.module) in cross_module:
            out.append(loop)
    return out


def _loader_binding_names(ctx, call: CallSite):
    """`(names, modules)` this DataLoader construction is bound to.

    `modules` is the set of modules that actually call the factory the loader
    is returned from - the only places a cross-module name match is evidence of
    anything.
    """
    names: set = set()
    modules: set = set()
    if call.var:
        names.add(call.var.split(".")[-1])
        return names, modules
    func = call.function
    if func is None or len(func.returns) != 1:
        return names, modules
    expr = func.returns[0]
    if expr is not call.node:
        text = dotted_text(expr)
        if not text or text.split(".")[-1] != (call.var or "").split(".")[-1]:
            local = ctx.binding_of(text, func.scope) if text else None
            if local is None or local.producer is not call:
                return names, modules
    for relpath in sorted(ctx.modules):
        for site in ctx.modules[relpath].calls:
            if site.target_function is func and site.var:
                names.add(site.var.split(".")[-1])
                modules.add(id(site.module))
    return names, modules


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
        # ANA-03: read the *expression*, not just the folded constant, and then
        # keep the three states apart. `call.kwargs` alone answered None both
        # for `DataLoader(ds)` and for `DataLoader(ds, shuffle=config.shuffle)`
        # where the analyzer already held the literal `True` - so this rule
        # published "built with shuffle=unset (defaults to False)" above a
        # snippet reading `shuffle=config.shuffle`, contradicting its own
        # evidence on screen, and fired on correct code.
        state, shuffle = kwarg_literal(ctx, call, "shuffle")
        if state == KWARG_RESOLVED and shuffle == "True":
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
        where = "%s:%d" % (call.loc.file, call.loc.line)
        subject = name or "the dataset"
        if state == KWARG_ABSENT:
            message = ("The training DataLoader at %s is built with shuffle= unset "
                       "(it defaults to False) and no sampler=, so %s is consumed "
                       "in dataset order every epoch." % (where, subject))
        elif state == KWARG_RESOLVED:
            evidence.append(("context_confirmed",
                             "shuffle= resolves to %s at %s" % (shuffle, where), 1.0))
            message = ("The training DataLoader at %s is built with shuffle=%s and "
                       "no sampler=, so %s is consumed in dataset order every epoch."
                       % (where, shuffle, subject))
        else:
            evidence.append(("context_confirmed",
                             "shuffle= is passed at line %d but its value could "
                             "not be resolved statically" % call.loc.line,
                             UNRESOLVED_KWARG_WEIGHT))
            note_unresolved_kwarg(ctx, call, "shuffle",
                                  "a training loader that does shuffle is correct")
            message = ("The training DataLoader at %s passes shuffle= an expression "
                       "MLView could not resolve, and has no sampler=. If that "
                       "expression is not True, %s is consumed in dataset order "
                       "every epoch - MLView could not tell which."
                       % (where, subject))
        issues.append(ctx.issue(
            message=message,
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
            # PUB2-02: the file as well as the line. A cross-module attribution
            # that is legitimate stays readable, and one that is not is obvious
            # on sight instead of sending the reader to a line number the file
            # it points at does not have.
            evidence.append(("context_confirmed",
                             "the loop at %s:%d over this loader calls backward()"
                             % (loop.loc.file, loop.loc.line), 1.0))
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
        # ANA-03: the same two-step read. This direction only ever *loses*
        # findings when the expression is unresolved, so there is no third
        # branch to write - `shuffle=` must be provably True to be a defect.
        state, shuffle = kwarg_literal(ctx, call, "shuffle")
        if state != KWARG_RESOLVED or shuffle != "True":
            continue
        name, ref = dataset_arg(ctx, call)
        tagged = ref is not None and ref.has("VAL_SPLIT", "TEST_SPLIT")
        named = bool(_EVAL_LOADER_RE.match(loader_name(call)))
        key = dataset_split_key(call)
        keyed = bool(key and _EVAL_LOADER_RE.match(key))
        if not tagged and not named and not keyed:
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
        elif named:
            evidence.append(("name_regex",
                             "%s only matches the evaluation-loader naming convention"
                             % loader_name(call), 0.8))
        else:
            evidence.append(("name_regex",
                             "the dataset argument is the literal `%s` split of a "
                             "split container, which names the held-out half but "
                             "carries no dataflow tag" % key, 0.8))
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The evaluation DataLoader at %s:%d passes shuffle=True over %s, so "
                    "predictions come back in a different order each run."
                    % (call.loc.file, call.loc.line, name or "the held-out dataset"),
            loc=call.loc, node_ids=[node],
            related=[("construction", call.loc, "DataLoader built here")],
            evidence=evidence, dynamic=call.scope.is_dynamic,
            # H5: one literal replaced by one literal - the narrowest edit in
            # the product, and the only reason this rule is in the first five.
            fix=shuffle_false_fix(ctx, call)))
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
    if call.function is None and call.enclosing_class is None:
        if guard is not None and _inside(guard, call.node):
            return None
        if guard is not None:
            return "the loader is constructed at module scope, outside the guard"
        return ("the loader is constructed at module scope and the module has no "
                "if __name__ == \"__main__\" guard")
    func = call.function
    if func is None:
        return None
    return _import_time_chain(module, func, guard)


#: How many call hops the import-time reachability walk follows.
_IMPORT_CHAIN_DEPTH = 6


def _import_time_chain(module, func, guard) -> Optional[str]:
    """The module-scope call chain that reaches `func`, as a sentence.

    The walk used to be **one** hop - a helper called directly at module scope
    - and the real shape is deeper: a bare `main()` call at the foot of the
    file (often wrapped in a print), `main()` calling `fit()`, `fit()` calling
    `build_loaders()`. Three hops, and
    the loader is built at import time just as surely as if it were written at
    module scope. `tabular_seq_lstm_bad` (two loaders), `nlp_mlm_pretrain_bad`
    and `nlp_reranker_bad` all have exactly that chain, and MLV112 - a rule
    whose base prior is 0.98 because the question is purely syntactic - saw
    none of them.

    The chain is reported in full, so the reader can see which call at module
    scope is the one to move behind a guard.
    """
    callers = {}
    for caller in module.calls:
        target = caller.target_function
        if target is not None:
            callers.setdefault(id(target), []).append(caller)
    frontier = [(func, [])]
    seen = {id(func)}
    depth = 0
    while frontier and depth <= _IMPORT_CHAIN_DEPTH:
        nxt = []
        for current, path in frontier:
            for caller in callers.get(id(current), ()):
                if caller.function is None and caller.enclosing_class is None:
                    if guard is not None and _inside(guard, caller.node):
                        continue
                    chain = " <- ".join(["%s()" % current.name]
                                        + ["%s()" % f.name for f in path])
                    return ("%s is called at module scope (line %d), so the loader "
                            "is built while the module is imported"
                            % (chain, caller.loc.line))
                owner = caller.function
                if owner is None or id(owner) in seen:
                    continue
                seen.add(id(owner))
                nxt.append((owner, path + [current]))
        frontier = nxt
        depth += 1
    return None


def _inside(container: Optional[ast.AST], target: ast.AST) -> bool:
    if container is None:
        return False
    for child in ast.walk(container):
        if child is target:
            return True
    return False
