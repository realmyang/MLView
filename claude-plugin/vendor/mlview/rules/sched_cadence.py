"""MLV207: at what cadence does this scheduler want to be stepped?

The rule is one comparison - the cadence the scheduler's own class declares
against the loop its `.step()` is written in - and everything hard is on the
two sides of it. This module holds both: the cadence tables (which schedulers
are per-epoch, which are per-batch, and which are per-batch only when their
step size was computed from `len(loader)`), and the walk that finds *which*
scheduler a `.step()` belongs to - through a name, a parameter, a returned
value or a factory - and *which* loop it effectively runs in.
"""

from __future__ import annotations

import ast
from typing import List, Optional

from .. import knowledge as K
from ..ir.model import CallSite, LoopIR
from ..ir.symbols import dotted_text
from .helpers import within_loop
from .mechanics_sites import _producer, _tail


#: Schedulers whose `step()` belongs in the **epoch** loop.
#:
#: VIS2-04. `LambdaLR` and `PolynomialLR` were in this set in the code and NOT
#: in the set docs/ISSUE_RULES.md section 4 documents, and neither belongs:
#:
#: * `LambdaLR` has **no intrinsic cadence at all**. The lambda receives
#:   whatever counter its owner steps, and `transformers`'
#:   `get_linear_schedule_with_warmup` - which is in `_BATCH_CADENCE` three
#:   lines below - literally *returns a LambdaLR*. timm, DETR, MoCo, SimCLR and
#:   the FixMatch reference all build one over `epochs * len(loader)` steps and
#:   step it per batch, which the rule was calling a defect at medium / 0.80 /
#:   likely with the evidence row "LambdaLR is in the epoch-cadence set of
#:   torch.optim.lr_scheduler" - a property LambdaLR does not have.
#: * `PolynomialLR` is mmsegmentation's `poly` policy, which is per-iteration
#:   in every published segmentation recipe.
#:
#: A constructor that cannot be judged from its class is not judged. That is
#: the rule's own stated discipline ("a scheduler whose constructor MLView
#: could not resolve is not judged at all"), applied to two classes whose class
#: does not answer the question.
_EPOCH_CADENCE = ("StepLR", "MultiStepLR", "ExponentialLR", "CosineAnnealingLR",
                  "ReduceLROnPlateau")
#: Schedulers whose `step()` belongs in the **batch** loop.
#: NLP2-08 adds the rest of the `transformers.optimization.get_*` family; they
#: all return a `LambdaLR` built over `num_training_steps`, so their cadence is
#: per step by construction.
_BATCH_CADENCE = ("OneCycleLR", "CyclicLR", "get_linear_schedule_with_warmup",
                  "get_cosine_schedule_with_warmup",
                  "get_cosine_with_hard_restarts_schedule_with_warmup",
                  "get_polynomial_decay_schedule_with_warmup",
                  "get_constant_schedule_with_warmup",
                  "get_inverse_sqrt_schedule",
                  "get_wsd_schedule")


# ---------------------------------------------------------------------------
# MLV207
# ---------------------------------------------------------------------------
def _scheduler_name(call: CallSite) -> Optional[str]:
    """The constructor class name behind a `<sched>.step()` receiver."""
    producer = _producer(call.receiver)
    if producer is None:
        return None
    name = _tail(producer.fqn)
    return name or None


def _scheduler_producer(ctx, call: CallSite) -> Optional[CallSite]:
    """The scheduler constructor, following one hop when it is not local.

    vision-14. MLV207 decides cadence from the receiver's constructor, and a
    scheduler that arrives as a function parameter (`train_one_epoch(...,
    scheduler, ...)`) or out of a `build_scheduler(...)` factory has no local
    constructor at all - so both of the real-world wrong-cadence shapes were
    invisible: a `OneCycleLR` stepped once per epoch finishes its whole cycle
    in the first few epochs and then trains at the floor LR, and a `MultiStepLR`
    with milestones at 20 and 35 stepped per batch blows through both in the
    first epoch. Neither raises, so the schedule is the only thing that says
    so. Both hops are taken only when unambiguous.
    """
    producer = _producer(call.receiver)
    if producer is not None and K.role_of(producer.fqn) != "SCHEDULER":
        # `scheduler = build_scheduler(optimizer, ...)` - one hop into the
        # callee's single returned constructor.
        producer = _returned_scheduler(ctx, producer) or producer
    if producer is not None:
        return producer
    return _parameter_scheduler(ctx, call)


def _returned_scheduler(ctx, call: CallSite) -> Optional[CallSite]:
    func = call.target_function
    if func is None or len(func.returns) != 1:
        return None
    expr = func.returns[0]
    index = {id(c.node): c for c in func.module.calls}
    inner = index.get(id(expr))
    if inner is None:
        name = dotted_text(expr)
        ref = ctx.binding_of(name, func.scope) if name else None
        inner = ref.producer if ref is not None else None
    if inner is None or K.role_of(inner.fqn) != "SCHEDULER":
        return None
    return inner


def _parameter_scheduler(ctx, call: CallSite) -> Optional[CallSite]:
    """The constructor every resolved call site passes for this parameter."""
    func = call.function
    name = call.receiver_name
    if func is None or not name or name not in (func.params or ()):
        return None
    index = list(func.params).index(name)
    found: List[CallSite] = []
    for relpath in sorted(ctx.modules):
        for site in ctx.modules[relpath].calls:
            if site.target_function is not func:
                continue
            node = site.args[index] if index < len(site.args) \
                else site.kwarg_nodes.get(name)
            if node is None:
                return None
            text = dotted_text(node)
            ref = ctx.binding_of(text, site.scope) if text else None
            inner = ref.producer if ref is not None else None
            if inner is not None and K.role_of(inner.fqn) != "SCHEDULER":
                inner = _returned_scheduler(ctx, inner) or inner
            if inner is None or K.role_of(inner.fqn) != "SCHEDULER":
                return None
            found.append(inner)
    if not found:
        return None
    first = found[0]
    for other in found[1:]:
        if _tail(other.fqn) != _tail(first.fqn):
            return None                  # the call sites disagree: judge none
    return first


def _stepsize_uses_len(ctx, producer: CallSite) -> bool:
    """`StepLR(step_size=len(loader) * k)` really is a per-batch schedule."""
    for node in list(producer.args) + list(producer.kwarg_nodes.values()):
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and dotted_text(child.func) == "len":
                return True
    return False


def _via_scheduler_name(call: CallSite) -> Optional[str]:
    """The scheduler class a factory's return summary already established."""
    ref = call.receiver
    for fqn in getattr(ref, "via_fqns", ()) or ():
        tail = _tail(fqn)
        if tail in _EPOCH_CADENCE or tail in _BATCH_CADENCE:
            return tail
    return None


def _sched_step_calls(ctx) -> List[CallSite]:
    """Every `<scheduler>.step()`, including the ones whose receiver is a parameter.

    vision-14. `ctx.calls_with_role("SCHED_STEP")` needs the receiver's family
    to resolve, and `def train_one_epoch(..., scheduler, ...)` - the shape
    torchvision's own reference, timm, detectron2 and mmdet all use - never
    does, so the rule could not see the call at all. The `.step` name only
    SELECTS a candidate here; the claim still rests entirely on resolving the
    constructor through the resolved call sites (`_parameter_scheduler`), and a
    candidate whose constructor does not resolve is dropped without a word.
    That is iron law 1 honoured: the match is on the canonical FQN, and the
    name is how the candidate list is kept cheap.
    """
    out: List[CallSite] = []
    seen = set()
    for call in ctx.calls_with_role("SCHED_STEP"):
        seen.add(id(call))
        out.append(call)
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            if id(call) in seen or (call.method or "") != "step":
                continue
            if K.role_of(call.fqn) is not None:
                continue
            func = call.function
            name = call.receiver_name
            if func is None or not name or name not in (func.params or ()):
                continue
            out.append(call)
    out.sort(key=lambda c: (c.loc.file, c.loc.line, c.loc.col))
    return out


def _encloses_batch_loop(ctx, loop: LoopIR) -> Optional[str]:
    """Does a batch loop run once per iteration of this one? (VIS2-03)

    Returns the phrase naming where it is, or None.

    The lexical half was the whole test, and `for epoch in range(N):
    train_one_epoch(...); scheduler.step()` - the decomposition torchvision's
    own references, timm, detectron2 and essentially every repository above one
    file uses - has the batch loop in the callee. A `OneCycleLR` that completes
    its entire cycle inside the first few epochs was therefore never reported
    in any project with a `train_one_epoch()`. One hop into the callees
    `ir/resolve` already resolved is the same hop MLV201/MLV202 take, and the
    evidence names the callee so the claim stays checkable.
    """
    for batch in ctx.loops("batch"):
        if batch is not loop and within_loop(batch, loop):
            return "the batch loop at line %d" % batch.loc.line
    seen = set()
    for call in loop.module.calls:
        if not within_loop(call.loop, loop):
            continue
        callee = call.target_function
        if callee is None or id(callee) in seen:
            continue
        seen.add(id(callee))
        for batch in ctx.loops("batch"):
            if batch.function is callee:
                return "the batch loop is in %s() at %s:%d" % (
                    callee.name, batch.loc.file, batch.loc.line)
    return None


def _effective_loop(ctx, call: CallSite) -> Optional[LoopIR]:
    """The loop this `.step()` really runs once per (NLP2-08).

    `call.loop` is None for a step written in a `train_one_epoch(...)` helper
    **after** its batch loop - the dominant torchvision / HuggingFace shape -
    so the rule dropped the call and never considered it. The helper is called
    once per iteration of an epoch loop, so the step runs at epoch cadence,
    and that is exactly the question. The claim only stands when the call sites
    agree: one caller inside an epoch loop, and the helper containing a
    confirmed batch loop that this step is written outside of.
    """
    if call.loop is not None:
        return call.loop
    func = call.function
    if func is None:
        return None
    if not any(loop.function is func and loop.kind == "batch"
               for loop in ctx.loops("batch")):
        return None
    found: Optional[LoopIR] = None
    for relpath in sorted(ctx.modules):
        for site in ctx.modules[relpath].calls:
            if site.target_function is not func:
                continue
            outer = site.loop
            while outer is not None and outer.kind != "epoch":
                outer = outer.parent_loop
            if outer is None:
                return None          # a caller that is not in an epoch loop
            if found is not None and found is not outer:
                return None          # the call sites disagree: judge none
            found = outer
    return found
