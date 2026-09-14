"""MLV501 - the model moved to a device but the batches left behind (or vice versa).

Two symmetric halves of one check, reported with a `variant` tag so the UI can
tell them apart: `batch_not_moved` (the common case) and `model_not_moved`.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Sequence, Set

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ClassIR, FunctionIR, LoopIR, ValueRef
from ..ir.symbols import dotted_text
from .helpers import calls_in_loop, with_role
from .registry import rule

__all__ = ["batch_not_moved_to_device"]

_CPU_LITERALS = ("cpu", "'cpu'", '"cpu"')
_MOVE_METHODS = ("to", "cuda", "npu", "xpu", "mps")
#: Knowledge roles whose `__call__` is a *loss*, not a network forward.
_LOSS_ROLES = ("LOSS_CLS", "LOSS_FN")


@rule(code="MLV501", severity="medium", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "device"], cross_file=True,
      title="Model and batches are on different devices",
      why="The forward pass raises \"Expected all tensors to be on the same device\" on "
          "the first batch - and when it does not, the whole run silently falls back to "
          "the CPU and takes an order of magnitude longer.",
      fix_hint="Move each batch inside the loop: "
               "x, y = x.to(device, non_blocking=True), y.to(device).")
def batch_not_moved_to_device(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    #: `id(model_move) -> the Issue that reported it`, so a second offending
    #: loop can be appended to the first finding's related locations (DGRG-11).
    reported: dict = {}
    for loop in ctx.loops("batch"):
        calls = calls_in_loop(ctx, loop)
        forward = _model_forward(with_role(calls, "FORWARD"))
        if forward is None:
            continue
        model_move = _model_move(ctx, forward)
        batch_names = _batch_names(loop, forward)
        if not batch_names:
            continue
        moved = _moved_names(ctx, loop, calls, batch_names)
        if model_move is None:
            issue = _model_left_behind(ctx, loop, forward, moved, batch_names)
            if issue is not None:
                issues.append(issue)
            continue
        if _cpu_device(ctx, model_move):
            continue
        if moved:
            continue
        if _dataset_moves(ctx, loop) or _collate_moves(ctx, loop):
            continue
        if id(model_move) in reported:
            # DGRG-11: still one finding per placement - the fix is the same
            # line for every loop - but the other loops are named, so a reader
            # who fixes the reported one does not still crash on the next.
            _note_sibling_loop(reported[id(model_move)], loop, forward)
            continue
        node = ctx.node_for_loop(loop)
        if node is None:
            continue
        names = ", ".join(sorted(batch_names))
        evidence = [
            ("fqn_resolved", "%s resolves to %s"
             % (_label(model_move), model_move.fqn or "torch.nn.Module.to"), 1.0),
            ("dataflow_direct",
             "%s feed %s at line %d without a .to()/.cuda() on any path"
             % (names, _label(forward), forward.loc.line), 1.0),
            ("negation_absent",
             "no .to()/.cuda() on the batch, in the Dataset.__getitem__, or in a "
             "collate_fn", 1.0),
        ]
        if not loop.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % loop.scope.qualname, 1.0))
        issue = ctx.issue(
            message="The model is moved to a device at %s:%d, but the batch value(s) %s "
                    "in the loop at line %d are never moved before %s."
                    % (model_move.loc.file, model_move.loc.line, names, loop.loc.line,
                       _label(forward)),
            loc=loop.loc, node_ids=[node],
            related=[("construction", model_move.loc, "the model is moved here"),
                     ("call_site", forward.loc, "the forward pass runs here")],
            evidence=evidence, tags=("correctness", "device", "batch_not_moved"),
            dynamic=loop.scope.is_dynamic,
            wrapper_gated=_wrapper_handles_placement(ctx, loop))
        reported[id(model_move)] = issue
        issues.append(issue)
    return issues


def _note_sibling_loop(issue, loop: LoopIR, forward: CallSite) -> None:
    """Name another loop with the same unmoved-batch defect (DGRG-11).

    `adv_audio_bad` moves the model at line 88 and never moves a batch: the
    training loop at 102 and the validation loop at 64 both raise on their
    first batch, and only one of them was reported. One finding is right - the
    fix is one line - but a reader who fixes the reported loop and stops still
    crashes.
    """
    related = loop.loc.related_dict(
        "eval_loop", "and %s at line %d has the same unmoved batch"
        % (_label(forward), loop.loc.line))
    if related not in issue.relatedLocs:
        issue.relatedLocs.append(related)


def _is_loss_call(call: CallSite) -> bool:
    """`criterion(logits, y)` - an `nn.Module.__call__` that is not a forward pass."""
    ref = call.receiver
    if ref is not None and ref.has("LOSS"):
        return True
    return any(K.role_of(f.rsplit(".__call__", 1)[0]) in _LOSS_ROLES
               for f in call.canonical_fqns or ())


def _is_model_call(call: CallSite) -> bool:
    """A forward whose receiver is provably a network, not merely `nn.Module`-ish."""
    ref = call.receiver
    if ref is not None and ref.has("MODEL"):
        return True
    cls = ref.class_ir if ref is not None else call.class_ir
    return cls is not None and cls.is_nn_module


def _model_forward(forwards: Sequence[CallSite]) -> Optional[CallSite]:
    """The forward pass through the *model*, not through the loss.

    `criterion(model(x), y)` is an `nn.Module.__call__` too, and the outer call
    is recorded before its own argument - so taking `forwards[0]` names the
    loss where the finding means the network ("the model behind crit()").

    Loss receivers are **dropped**, never fallen back to: when the real network
    comes from a factory the knowledge tables do not know (timm, open_clip, an
    unresolved in-workspace import) the only surviving FORWARD candidate is the
    criterion, and reporting it produced a self-contradictory finding on correct
    code. No model resolved means no finding.
    """
    candidates = [c for c in forwards if not _is_loss_call(c)]
    for call in candidates:
        ref = call.receiver
        if ref is not None and ref.has("MODEL"):
            return call
    for call in candidates:
        ref = call.receiver
        cls = ref.class_ir if ref is not None else call.class_ir
        if cls is not None and cls.is_nn_module:
            return call
    return candidates[0] if candidates else None


def _model_left_behind(ctx, loop: LoopIR, forward: CallSite, moved: Set[str],
                       batch_names: Set[str]):
    """`variant: "model_not_moved"` - the batches move, the network does not.

    Deliberately strict: it needs a batch that is explicitly moved *and* no
    `.to()` / `.cuda()` on any MODEL-tagged value anywhere in the workspace, so
    a model moved in a different file can never be mistaken for a missing move.
    """
    if not moved:
        return None
    if not _is_model_call(forward):
        # "the model was never moved" is unprovable when no model was resolved
        return None
    # INFRA-02. The module scope is what made the claim false: `engine/
    # trainer.py` does `model = model.to(device)` and calls
    # `evaluate(model, loader, device)` in `engine/evaluator.py`, and this rule
    # then asserted "the model model is never moved" about a workspace whose
    # own IR carries the move. The docstring above states the opposite intent
    # ("a model moved in a different file can never be mistaken for a missing
    # move"); the implementation guaranteed exactly that mistake. A negative
    # claim needs the whole workspace.
    if _any_model_move(ctx, None):
        return None
    node = ctx.node_for_loop(loop)
    if node is None:
        return None
    mover = _first_move(ctx, loop, moved)
    if mover is None:
        return None
    if _cpu_device(ctx, mover):
        return None                  # FP-note (d): the device is the literal 'cpu'
    model_name = _model_name(forward)
    names = ", ".join(sorted(moved))
    evidence = [
        ("dataflow_direct", "%s is moved to a device at line %d"
         % (names, mover.loc.line), 1.0),
        ("negation_absent",
         "no .to(device) / .cuda() on any nn.Module in the workspace", 1.0),
    ]
    if not loop.scope.is_dynamic:
        evidence.append(("scope_static",
                         "no dynamic constructs in %s" % loop.scope.qualname, 1.0))
    return ctx.issue(
        message="The batch value(s) %s are moved to a device at %s:%d, but %s is never "
                "moved, so the forward pass mixes devices."
                % (names, mover.loc.file, mover.loc.line, model_name),
        loc=loop.loc, node_ids=[node],
        related=[("construction", mover.loc, "the batch is moved here"),
                 ("call_site", forward.loc, "the forward pass runs here")],
        evidence=evidence, tags=("correctness", "device", "model_not_moved"),
        dynamic=loop.scope.is_dynamic,
        wrapper_gated=_wrapper_handles_placement(ctx, loop))


def _any_model_move(ctx, module=None) -> bool:
    """Is any model moved to a device anywhere the search was asked to look?

    `module=None` searches the whole workspace, which is what an absence claim
    about "the model" requires (INFRA-02). Passing a module narrows it, and
    that narrowing is only ever safe for a *positive* claim.
    """
    for call in ctx.calls_with_role("TO_DEVICE"):
        if module is not None and call.module is not module:
            continue
        if any(f.startswith("torch.nn.Module") for f in call.canonical_fqns or ()):
            return True
        receiver = call.receiver
        if receiver is not None and receiver.has("MODEL"):
            return True
    return False


def _model_name(forward: CallSite) -> str:
    """How to name the network in the message: its binding, or its class."""
    ref = forward.receiver
    if forward.receiver_name:
        return "the model %s" % forward.receiver_name
    if ref is not None and ref.name and ref.name != "<call>":
        return "the model %s" % ref.name
    cls = ref.class_ir if ref is not None else forward.class_ir
    if cls is not None:
        return "the model %s" % cls.name
    return "the model"


def _first_move(ctx, loop: LoopIR, moved: Set[str]) -> Optional[CallSite]:
    """The `.to(device)` on a batch value **inside the anchor's own function**.

    A move in a sibling function is a different batch: citing it as the
    finding's `construction` related-location navigates the reader to code that
    has nothing to do with the loop the issue is anchored on.
    """
    scoped = _moves_in(loop, moved, same_function=True)
    return scoped or _moves_in(loop, moved, same_function=False)


def _moves_in(loop: LoopIR, moved: Set[str], same_function: bool) -> Optional[CallSite]:
    for call in loop.module.calls:
        if same_function and call.function is not loop.function:
            continue
        if (call.method or call.short_name) not in _MOVE_METHODS:
            continue
        for child in ast.walk(call.node):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text in moved:
                return call
    return None


def _wrapper_handles_placement(ctx, loop: LoopIR) -> bool:
    """Lightning / accelerate / HF Trainer move the batch for you.

    Iron law 4 says such a finding is **de-rated to speculative** with a chip
    explaining why, not deleted: a hard `return []` dropped MLV501 out of the
    document entirely, and it did so workspace-wide, so an unrelated Trainer
    script silenced a hand-written loop in another file.
    """
    return bool(ctx.wrappers_for(loop.loc.file))


def _label(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _model_move(ctx, forward: CallSite) -> Optional[CallSite]:
    """The `.to(device)` / `.cuda()` applied to the model behind this forward."""
    ref = forward.receiver
    names = {forward.receiver_name} if forward.receiver_name else set()
    if ref is not None:
        names.add(ref.name)
    fallback = None
    for call in ctx.calls_with_role("TO_DEVICE"):
        if call.module is not forward.module:
            continue                     # a `model` in another file is another model
        if not any(f.startswith("torch.nn.Module") for f in call.canonical_fqns or ()):
            continue
        receiver = call.receiver
        if call.receiver_name in names or (receiver is not None and receiver.name in names):
            return call
        if receiver is not None and receiver.has("MODEL") and fallback is None:
            fallback = call
    return fallback


def _cpu_device(ctx, move: CallSite) -> bool:
    """`model.to('cpu')` moves nothing anywhere interesting."""
    for arg in list(move.args) + [move.kwarg_nodes[k] for k in sorted(move.kwarg_nodes)]:
        if isinstance(arg, ast.Constant) and str(arg.value).lower() == "cpu":
            return True
        name = dotted_text(arg)
        ref = ctx.binding_of(name, move.scope) if name else None
        if ref is not None and ref.literal and ref.literal.strip("'\"").lower() == "cpu":
            return True
        if ref is not None and ref.producer is not None:
            producer = ref.producer
            for inner in producer.args:
                if isinstance(inner, ast.Constant) and str(inner.value).lower() == "cpu":
                    return True
    return False


def _batch_names(loop: LoopIR, forward: CallSite) -> Set[str]:
    """Loop targets (including tuple-unpacked ones) that feed the forward pass."""
    targets = set(loop.targets)
    if not targets:
        return set()
    used: Set[str] = set()
    for arg in list(forward.args) + [forward.kwarg_nodes[k]
                                     for k in sorted(forward.kwarg_nodes)]:
        for child in ast.walk(arg):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text and text in targets:
                used.add(text)
    return used


def _moved_names(ctx, loop: LoopIR, calls: Sequence[CallSite],
                 batch_names: Set[str]) -> Set[str]:
    """Batch values that do get a `.to()` / `.cuda()` somewhere in the loop."""
    moved: Set[str] = set()
    for call in calls:
        method = call.method or call.short_name
        if method not in _MOVE_METHODS:
            continue
        receiver = call.receiver_name or ""
        if receiver in batch_names:
            moved.add(receiver)
        for child in ast.walk(call.node):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text in batch_names:
                moved.add(text)
    for child in ast.walk(loop.node):
        # `x, y = x.to(device), y.to(device)` rebinds the same names
        if isinstance(child, ast.Attribute) and child.attr in _MOVE_METHODS:
            text = dotted_text(child.value)
            if text in batch_names:
                moved.add(text)
    return moved


def _dataset_moves(ctx, loop: LoopIR) -> bool:
    """A `Dataset.__getitem__` that already returns device tensors."""
    ref = loop.iterates
    dataset_cls = _dataset_class(ctx, ref)
    if dataset_cls is None:
        return False
    getitem = dataset_cls.methods.get("__getitem__")
    if getitem is None:
        return False
    return _has_move(getitem)


def _dataset_class(ctx, ref: Optional[ValueRef]) -> Optional[ClassIR]:
    seen = 0
    while ref is not None and seen < 4:
        seen += 1
        if ref.class_ir is not None and any(b.startswith("torch.utils.data.")
                                            for b in ref.class_ir.resolved_bases):
            return ref.class_ir
        producer = ref.producer
        if producer is None:
            return None
        if producer.class_ir is not None:
            return producer.class_ir
        if producer.args:
            name = dotted_text(producer.args[0])
            ref = ctx.binding_of(name, producer.scope) if name else None
            continue
        return None
    return None


def _collate_moves(ctx, loop: LoopIR) -> bool:
    """A custom `collate_fn` that moves the batch."""
    ref = loop.iterates
    producer = ref.producer if ref is not None else None
    if producer is None:
        return False
    node = producer.kwarg_nodes.get("collate_fn")
    if node is None:
        return False
    name = dotted_text(node)
    if not name:
        return False
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            if func.name == name.split(".")[-1] and _has_move(func):
                return True
    return False


def _has_move(func: FunctionIR) -> bool:
    for child in ast.walk(func.node):
        if isinstance(child, ast.Attribute) and child.attr in _MOVE_METHODS:
            return True
    return False
