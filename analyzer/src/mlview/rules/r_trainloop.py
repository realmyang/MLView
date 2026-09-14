"""Training-step rules.

MLV201 missing `optimizer.zero_grad()` · MLV202 gradients computed but never
applied · MLV203 `step()` before `backward()` · MLV204 `backward()` under
`no_grad` · MLV205 loss accumulated with its autograd graph attached.

All five read the same object: the **batch loop** - the innermost `for` over a
`LOADER`-tagged value - and the calls inside it, following one level of
module-local helper calls.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Sequence, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, LoopIR, ValueRef
from ..ir.symbols import dotted_text
from .fixes import zero_grad_fix
from .helpers import calls_in_loop, first_with_role, loop_chain, with_role
from .registry import rule

__all__ = ["missing_zero_grad", "gradients_never_applied", "step_before_backward",
           "backward_under_no_grad", "loss_accumulated_with_graph"]


@rule(code="MLV201", severity="high", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"], absence=True,
      title="Gradients are never zeroed",
      why="Accumulated gradients make each update the sum of all previous batches, "
          "so training diverges or converges to the wrong place - silently.",
      fix_hint="Call optimizer.zero_grad(set_to_none=True) as the first statement of "
               "the training step, before the forward pass.")
def missing_zero_grad(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loop in ctx.loops("batch"):
        body = calls_in_loop(ctx, loop)
        backward = first_with_role(body, "BACKWARD")
        step = first_with_role(body, "OPT_STEP")
        if backward is None or step is None:
            continue
        # zero_grad may live in this loop, any enclosing loop, or a followed callee
        searched = list(body)
        for outer in loop_chain(loop)[1:]:
            searched.extend(calls_in_loop(ctx, outer))
        if loop.function is not None:
            searched.extend(loop.function.calls)
        if with_role(searched, "ZERO_GRAD"):
            continue
        if _unresolved_method(searched, ("zero_grad",)) is not None:
            continue                 # an unresolved receiver is not an absence
        if _lbfgs(ctx, step):
            continue
        node = ctx.node_for_loop(loop)
        if node is None:
            continue
        ghost = ctx.ghost("optimizer", node, "zero_grad()",
                          fqn="torch.optim.Optimizer.zero_grad")
        optimizer = _optimizer_site(ctx, step)
        related = []
        if optimizer is not None:
            related.append(("optimizer_site", optimizer.loc, "optimizer created here"))
        related.append(("backward_site", backward.loc, "backward here"))
        evidence = [
            ("fqn_resolved", "%s resolved through the import table" % (step.fqn or "step"), 1.0),
            ("context_confirmed",
             "batch loop over %s contains backward() and an optimizer step"
             % (loop.iter_text or "a loader"), 1.0),
            ("negation_absent",
             "framework wrapper detected: %s" % ", ".join(ctx.wrappers) if ctx.wrappers
             else "no Lightning / HF Trainer / accelerate detected in the workspace", 1.0),
        ]
        # The dynamic de-rating is the engine's job (x0.7); claiming
        # `scope_static` for a scope that is not static would be a lie.
        if not loop.scope.is_dynamic:
            evidence.insert(2, ("scope_static",
                                "no dynamic constructs in %s" % loop.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The batch loop at %s:%d calls %s (line %d) and %s (line %d) but never "
                    "zero_grad(). Gradients accumulate across batches."
                    % (loop.loc.file, loop.loc.line,
                       _short(backward), backward.loc.line, _short(step), step.loc.line),
            loc=node.loc, node_ids=[ghost, node], related=related, evidence=evidence,
            dynamic=loop.scope.is_dynamic,
            # H5: the ghost node already says *where* the missing call belongs;
            # the fix is that same slot expressed as an edit. `needs-review`,
            # always - gradient accumulation has this exact shape.
            fix=zero_grad_fix(ctx, loop, step)))
    return issues


def _short(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _optimizer_site(ctx, call: CallSite) -> Optional[CallSite]:
    """Where the optimizer this finding is about was constructed.

    MLV202 hands us the `.backward()` call, whose receiver is the *loss* - so
    the receiver short-circuit only applies when the receiver really is an
    optimizer, otherwise the finding would cite the loss construction as
    "optimizer created here" (a related-location that navigates nowhere useful).
    """
    ref = call.receiver
    if ref is not None and ref.producer is not None and _is_optimizer(ref):
        return ref.producer
    for value in ctx.values_tagged("OPTIMIZER"):
        if value.producer is not None:
            return value.producer
    return None


def _is_optimizer(ref: ValueRef) -> bool:
    if ref.has("OPTIMIZER"):
        return True
    producer = ref.producer
    return bool(producer is not None and K.role_of(producer.fqn) == "OPTIMIZER")


def _unresolved_method(calls: Iterable[CallSite], methods: Sequence[str]
                       ) -> Optional[CallSite]:
    """An `x.step()` / `x.zero_grad()` whose receiver never resolved.

    An absence rule may only assert `negation_absent` about calls it can see.
    When the receiver is a value the IR could not type, the honest answer is
    "unknown", not "missing" - claiming the latter is what put a dashed ghost
    node in the middle of a perfectly correct training step.
    """
    wanted = set(methods)
    for call in calls:
        if (call.method or "") not in wanted:
            continue
        if K.lookup(call.fqn) is None:
            return call
    return None


def _lbfgs(ctx, step: CallSite) -> bool:
    ref = step.receiver
    producer = ref.producer if ref is not None else None
    return bool(producer is not None and (producer.fqn or "").endswith("LBFGS"))


# ---------------------------------------------------------------------------
# shared batch-loop plumbing
# ---------------------------------------------------------------------------
#: Wrappers that detach the value before it is accumulated.
_ACCUM_SAFE = ("item", "detach", "float", "cpu", "numpy", "tolist")
_GRAD_INPUT_METHODS = ("requires_grad_", "retain_grad")


def _within(loop: Optional[LoopIR], outer: Optional[LoopIR]) -> bool:
    """True when `loop` is `outer` or nested inside it."""
    if outer is None:
        return False
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False


def _searched_calls(ctx, loop: LoopIR) -> List[CallSite]:
    """The loop body, every enclosing loop body, and the enclosing function."""
    out = list(calls_in_loop(ctx, loop))
    for outer in loop_chain(loop)[1:]:
        out.extend(calls_in_loop(ctx, outer))
    if loop.function is not None:
        out.extend(loop.function.calls)
    return out


def _optimizes_the_input(ctx, loop: LoopIR, calls: Sequence[CallSite]) -> bool:
    """Adversarial-example code backprops into the batch, not the parameters."""
    for call in calls:
        if (call.method or call.short_name) in _GRAD_INPUT_METHODS:
            return True
    for child in ast.walk(loop.node):
        if isinstance(child, ast.Attribute) and child.attr in ("requires_grad",
                                                               "requires_grad_"):
            return True
    return False


def _distinct_receivers(calls: Iterable[CallSite]) -> List[str]:
    out: List[str] = []
    for call in calls:
        name = call.receiver_name or call.short_name
        if name and name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# MLV202
# ---------------------------------------------------------------------------
@rule(code="MLV202", severity="high", base_prior=0.90, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"], absence=True,
      title="Gradients are computed but never applied",
      why="Every batch computes a gradient that is thrown away, so the weights never "
          "move and the loss curve stays flat for reasons that look like a bad learning "
          "rate rather than a missing call.",
      fix_hint="Call optimizer.step() after loss.backward() - or scaler.step(optimizer); "
               "scaler.update() under AMP - stepping every N batches if you accumulate.")
def gradients_never_applied(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loop in ctx.loops("batch"):
        body = calls_in_loop(ctx, loop)
        backward = first_with_role(body, "BACKWARD")
        if backward is None:
            continue
        searched = _searched_calls(ctx, loop)
        if with_role(searched, "OPT_STEP"):
            continue
        if _unresolved_method(searched, ("step",)) is not None:
            continue                 # an unresolved receiver is not an absence
        if _optimizes_the_input(ctx, loop, searched):
            continue
        node = ctx.node_for_loop(loop)
        if node is None:
            continue
        ghost = ctx.ghost("optimizer", node, "optimizer.step()",
                          fqn="torch.optim.Optimizer.step")
        optimizer = _optimizer_site(ctx, backward)
        related = [("backward_site", backward.loc, "gradients computed here")]
        if optimizer is not None:
            related.append(("optimizer_site", optimizer.loc,
                            "optimizer created here but never stepped"))
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (backward.fqn or "backward"), 1.0),
            ("context_confirmed",
             "batch loop over %s calls backward() at line %d"
             % (loop.iter_text or "a loader", backward.loc.line), 1.0),
            ("negation_absent",
             "no optimizer.step() / scaler.step() in the loop, the enclosing loop, or a "
             "followed helper", 1.0),
        ]
        if not loop.scope.is_dynamic:
            evidence.insert(2, ("scope_static",
                                "no dynamic constructs in %s" % loop.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The batch loop at %s:%d calls %s (line %d) but no optimizer step "
                    "follows it, so the gradients are discarded at the next iteration."
                    % (loop.loc.file, loop.loc.line, _short(backward), backward.loc.line),
            loc=node.loc, node_ids=[ghost, node], related=related, evidence=evidence,
            dynamic=loop.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV203
# ---------------------------------------------------------------------------
@rule(code="MLV203", severity="high", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="optimizer.step() runs before loss.backward()",
      why="The step applies whatever gradients the previous iteration left behind, so "
          "every update is one batch stale and the first one is pure noise.",
      fix_hint="Order the training step as zero_grad() -> forward -> loss.backward() -> "
               "(clip) -> optimizer.step().")
def step_before_backward(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loop in ctx.loops("batch"):
        body = [c for c in loop.module.calls if _within(c.loop, loop)]
        steps = with_role(body, "OPT_STEP")
        backwards = with_role(body, "BACKWARD")
        if not steps or not backwards:
            continue
        if len(_distinct_receivers(steps)) > 1 or len(_distinct_receivers(backwards)) > 1:
            continue                # multi-optimizer GAN loop: the order is legitimate
        variant = "step() before backward()"
        pair = _out_of_order(steps, backwards)
        if pair is None:
            pair = _wiped_by_zero_grad(body, steps, backwards)
            variant = "zero_grad() between backward() and step()"
        if pair is None:
            continue
        step, backward = pair
        node = ctx.node_for_call(step) or ctx.node_for_loop(loop)
        if node is None:
            continue
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (step.fqn or "step"), 1.0),
            ("context_confirmed",
             "both calls sit in the same block of the batch loop at line %d"
             % loop.loc.line, 1.0),
            ("dataflow_direct",
             "one optimizer (%s) and one loss (%s) in this loop, so they are linked"
             % (step.receiver_name or "optimizer", backward.receiver_name or "loss"), 1.0),
        ]
        if not loop.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % loop.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s runs at line %d, before %s at line %d (%s), so each update uses "
                    "the previous iteration's gradients."
                    % (_short(step), step.loc.line, _short(backward),
                       backward.loc.line, variant),
            loc=step.loc, node_ids=[node],
            related=[("step_site", step.loc, "step happens here"),
                     ("backward_site", backward.loc, "gradients are computed here")],
            evidence=evidence, dynamic=loop.scope.is_dynamic))
    return issues


def _out_of_order(steps, backwards) -> Optional[Tuple[CallSite, CallSite]]:
    for step in steps:
        for backward in backwards:
            if step.block_id == backward.block_id and step.stmt_index < backward.stmt_index:
                return step, backward
    return None


def _wiped_by_zero_grad(body, steps, backwards) -> Optional[Tuple[CallSite, CallSite]]:
    """`backward() -> zero_grad() -> step()` throws the fresh gradients away too."""
    zeros = with_role(body, "ZERO_GRAD")
    for step in steps:
        for backward in backwards:
            if step.block_id != backward.block_id:
                continue
            if backward.stmt_index >= step.stmt_index:
                continue
            for zero in zeros:
                if zero.block_id != step.block_id:
                    continue
                if backward.stmt_index < zero.stmt_index < step.stmt_index:
                    return step, backward
    return None


# ---------------------------------------------------------------------------
# MLV204
# ---------------------------------------------------------------------------
@rule(code="MLV204", severity="high", base_prior=0.97, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="backward() inside torch.no_grad()",
      why="No graph was recorded, so the call raises \"element 0 of tensors does not "
          "require grad\" at runtime and the training run dies on its first batch.",
      fix_hint="Move the backward pass outside the torch.no_grad() block, or wrap only "
               "the parts that genuinely need no gradients.")
def backward_under_no_grad(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in ctx.calls_with_role("BACKWARD"):
        if not call.inside_no_grad:
            continue
        node = ctx.node_for_call(call) or ctx.unit_for_call(call)
        if node is None:
            continue
        guard = _enclosing_no_grad(call)
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (call.fqn or "backward"), 1.0),
            ("context_confirmed",
             "line %d is marked insideNoGrad and no torch.enable_grad() re-enables "
             "gradients around it" % call.loc.line, 1.0),
        ]
        if not call.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % call.scope.qualname, 1.0))
        related = []
        if guard is not None:
            related.append(("construction", guard.loc,
                            "%s opened here" % (guard.fqn or "no_grad")))
        issues.append(ctx.issue(
            message="%s at %s:%d runs with autograd disabled%s, so there is no graph to "
                    "back-propagate through."
                    % (_short(call), call.loc.file, call.loc.line,
                       (" (opened at line %d)" % guard.loc.line) if guard is not None
                       else ""),
            loc=call.loc, node_ids=[node], related=related, evidence=evidence,
            dynamic=call.scope.is_dynamic))
    return issues


def _enclosing_no_grad(call: CallSite) -> Optional[CallSite]:
    best = None
    for other in call.module.calls:
        if K.role_of(other.fqn) != "NO_GRAD" or other.loc.line > call.loc.line:
            continue
        if best is None or other.loc.line > best.loc.line:
            best = other
    return best


# ---------------------------------------------------------------------------
# MLV205
# ---------------------------------------------------------------------------
@rule(code="MLV205", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["performance", "train-loop"],
      title="Loss accumulated without .item()",
      why="Adding the loss tensor keeps its whole autograd graph alive, so memory grows "
          "with every batch and a long epoch ends in an out-of-memory error.",
      fix_hint="Accumulate scalars: running_loss += loss.item() (or loss.detach()).")
def loss_accumulated_with_graph(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for name, loop, loc, scope, loss_ref, how in _accumulations(ctx, module):
            if _backwarded(module, name):
                continue                # deliberate multi-step accumulation
            outer = _defined_outside(module, name, loop, loc)
            if outer is None:
                continue
            node = (ctx.node_for_loop(loop) if loop is not None else None) \
                or ctx.node_for(loc)
            if node is None:
                continue
            evidence = [
                ("dataflow_direct",
                 "%s carries the LOSS tag from %s"
                 % (loss_ref.name,
                    loss_ref.producer.fqn if loss_ref.producer is not None
                    else "the loss computation"), 1.0),
                ("context_confirmed",
                 "%s is created at line %d, outside the %s loop at line %d"
                 % (name, outer.loc.line, loop.kind, loop.loc.line), 1.0),
                ("negation_absent",
                 "the accumulated value is not wrapped in .item(), .detach() or float()",
                 1.0),
            ]
            if not scope.is_dynamic:
                evidence.append(("scope_static",
                                 "no dynamic constructs in %s" % scope.qualname, 1.0))
            related = [("construction", outer.loc,
                        "%s is created here, outside the loop" % name)]
            if loss_ref.producer is not None:
                related.append(("call_site", loss_ref.producer.loc,
                                "the loss is produced here"))
            issues.append(ctx.issue(
                message="%s %s the tensor %s at %s:%d, so every iteration of the loop at "
                        "line %d keeps its autograd graph alive."
                        % (name, how, loss_ref.name, loc.file, loc.line, loop.loc.line),
                loc=loc, node_ids=[node], related=related, evidence=evidence,
                dynamic=scope.is_dynamic))
    return issues


def _accumulations(ctx, module):
    """`total += loss`, `total = total + loss` and `losses.append(loss)` in a loop."""
    out = []
    for record in module.assignments:
        if record.loop is None or record.value is None:
            continue
        name = None
        if record.kind == "aug":
            name = dotted_text(record.targets[0]) if record.targets else None
        elif record.kind == "assign" and isinstance(record.value, ast.BinOp):
            for target in record.targets:
                text = dotted_text(target)
                if text and text in _names_of(record.value):
                    name = text
                    break
        if name is None or _guarded(record.value):
            continue
        loss_ref = _loss_operand(ctx, record.value, record.scope, name)
        if loss_ref is not None:
            out.append((name, record.loop, record.loc, record.scope, loss_ref,
                        "accumulates"))
    for call in module.calls:
        if (call.method or "") != "append" or call.loop is None or not call.args:
            continue
        name = call.receiver_name
        container = ctx.binding_of(name, call.scope) if name else None
        if container is None or container.literal not in ("[]", "()"):
            continue
        if _guarded(call.args[0]):
            continue
        loss_ref = _loss_operand(ctx, call.args[0], call.scope, name)
        if loss_ref is not None:
            out.append((name, call.loop, call.loc, call.scope, loss_ref, "collects"))
    return out


def _names_of(value: ast.expr) -> List[str]:
    out: List[str] = []
    for child in ast.walk(value):
        text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) else None
        if text and text not in out:
            out.append(text)
    return out


def _guarded(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Attribute) and func.attr in _ACCUM_SAFE:
            return True
        if isinstance(func, ast.Name) and func.id in ("float", "int", "len", "sum"):
            return True
    return False


def _loss_operand(ctx, value: ast.expr, scope, accumulator: str) -> Optional[ValueRef]:
    for text in _names_of(value):
        if text == accumulator:
            continue
        ref = ctx.binding_of(text, scope)
        if ref is not None and ref.has("LOSS"):
            return ref
    return None


def _defined_outside(module, name: str, loop: Optional[LoopIR], loc):
    """The statement that created the accumulator outside the loop, if any."""
    best = None
    for other in module.assignments:
        if other.loc.line >= loc.line:
            continue
        if _within(loop, other.loop):
            continue                    # created inside the same loop: reset each pass
        if any(dotted_text(t) == name for t in other.targets):
            best = other
    return best


def _backwarded(module, name: str) -> bool:
    """`total_loss.backward()` (or `torch.stack(losses).backward()`) is deliberate."""
    short = name.split(".")[-1]
    stacked = set()
    for call in module.calls:
        if (call.fqn or "").endswith(("torch.stack", "torch.cat")) and call.var:
            for arg in call.args:
                if (dotted_text(arg) or "").split(".")[-1] == short:
                    stacked.add(call.var.split(".")[-1])
    wanted = {short} | stacked
    for call in module.calls:
        if K.role_of(call.fqn) != "BACKWARD":
            continue
        receiver = (call.receiver_name or "").split(".")[-1]
        if receiver in wanted:
            return True
        for child in ast.walk(call.node):
            text = dotted_text(child) if isinstance(child, (ast.Name, ast.Attribute)) \
                else None
            if text and text.split(".")[-1] in wanted:
                return True
    return False
