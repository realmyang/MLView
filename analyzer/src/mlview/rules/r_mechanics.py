"""Training-mechanics rules (ANA-8): schedulers, AMP, clipping, device, saving.

MLV207 a scheduler stepped at the wrong granularity - MLV208 a `GradScaler`
protocol used inconsistently - MLV209 gradient clipping in the wrong position -
MLV502 a hard-coded CUDA device with no availability check - MLV803 a whole
model pickled, or `torch.load` with neither `map_location=` nor `weights_only=`.

**The constraint these rules honour.** The IR is documented flow-insensitive,
so every ordering predicate here is evaluated over **one confirmed loop body**
and, for the strictly-ordered checks, over **one block of it** (`block_id` plus
`stmt_index`). Calls that span two functions, or two branches of an `if`, are
never compared: there is no single iteration path through them, and a rule that
pretended otherwise would fire on the correct gradient-accumulation protocol -
which is precisely what `analyzer/tests/clean/amp_accumulation.py` writes.

**What these rules cannot analyze.** A `GradScaler(enabled=cfg.train.amp)` is
not a literal, and the corpus's real code is exactly that shape: it **de-rates**
the finding (evidence weight 0.6), it never suppresses it, and it never
escalates it either. A scheduler whose constructor MLView could not resolve is
not judged at all. MLV502 reads the device string **written at the call site**;
a device that arrives through a module constant or a config object is left
alone, because that is a configuration decision this analyzer cannot see the
default of.
"""

from __future__ import annotations

import ast
from typing import Iterable, List, Optional, Sequence, Tuple

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, LoopIR, ModuleIR, ValueRef
from ..ir.symbols import dotted_text
from .helpers import calls_in_loop, literal_of, loop_chain, with_role, within_loop
from .registry import rule

__all__ = ["scheduler_wrong_granularity", "amp_scaler_protocol",
           "clipping_out_of_position", "hardcoded_cuda_device",
           "unsafe_checkpoint_serialization"]

#: Schedulers whose `step()` belongs in the **epoch** loop.
_EPOCH_CADENCE = ("StepLR", "MultiStepLR", "ExponentialLR", "CosineAnnealingLR",
                  "ReduceLROnPlateau", "LambdaLR", "PolynomialLR")
#: Schedulers whose `step()` belongs in the **batch** loop.
_BATCH_CADENCE = ("OneCycleLR", "CyclicLR", "get_linear_schedule_with_warmup",
                  "get_cosine_schedule_with_warmup",
                  "get_polynomial_decay_schedule_with_warmup")
_CUDA_LITERALS = ("cuda", "cuda:0", "cuda:1", "cuda:2", "cuda:3")


def _short(call: CallSite) -> str:
    if call.receiver_name:
        return "%s.%s()" % (call.receiver_name, call.method or call.short_name)
    return "%s()" % call.short_name


def _anchor(ctx, call: CallSite):
    return ctx.node_for_call(call) or ctx.unit_for_call(call)


def _tail(fqn: Optional[str]) -> str:
    return (fqn or "").rsplit(".", 1)[-1]


def _producer(ref: Optional[ValueRef]) -> Optional[CallSite]:
    return ref.producer if ref is not None else None


def _static(scope) -> List[Tuple[str, str, float]]:
    if scope is None or scope.is_dynamic:
        return []
    return [("scope_static", "no dynamic constructs in %s" % scope.qualname, 1.0)]


def _in_block(calls: Iterable[CallSite], block_id: str) -> List[CallSite]:
    return [c for c in calls if c.block_id == block_id]


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


def _stepsize_uses_len(ctx, producer: CallSite) -> bool:
    """`StepLR(step_size=len(loader) * k)` really is a per-batch schedule."""
    for node in list(producer.args) + list(producer.kwarg_nodes.values()):
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and dotted_text(child.func) == "len":
                return True
    return False


def _encloses_batch_loop(ctx, loop: LoopIR) -> bool:
    return any(within_loop(batch, loop) and batch is not loop
               for batch in ctx.loops("batch"))


@rule(code="MLV207", severity="medium", base_prior=0.80, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="Learning-rate scheduler stepped at the wrong granularity",
      why="The schedule runs at the wrong speed - an epoch schedule stepped per batch "
          "decays to its floor within the first epoch, and a one-cycle schedule stepped "
          "per epoch never reaches its peak - so the learning-rate curve you designed "
          "is not the one that trains the model.",
      fix_hint="Call scheduler.step() once per epoch for StepLR / CosineAnnealingLR, "
               "and once per batch for OneCycleLR / CyclicLR.")
def scheduler_wrong_granularity(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in ctx.calls_with_role("SCHED_STEP"):
        loop = call.loop
        name = _scheduler_name(call)
        producer = _producer(call.receiver)
        if loop is None or name is None or producer is None:
            continue
        variant = None
        if name in _EPOCH_CADENCE and loop.kind == "batch":
            if _stepsize_uses_len(ctx, producer):
                continue                # step_size=len(loader)*k is per-batch on purpose
            variant = ("%s is an epoch schedule but step() runs inside the batch loop "
                       "at line %d" % (name, loop.loc.line))
        elif name in _BATCH_CADENCE and loop.kind == "epoch" \
                and _encloses_batch_loop(ctx, loop):
            variant = ("%s is a per-batch schedule but step() runs in the epoch loop "
                       "at line %d, outside the batch loop it should follow"
                       % (name, loop.loc.line))
        elif name == "ReduceLROnPlateau" and not call.args and not call.kwarg_nodes:
            variant = ("ReduceLROnPlateau.step() was called with no metric, so it "
                       "compares nothing and never reduces")
        if variant is None:
            continue
        node = _anchor(ctx, call)
        evidence = [
            ("fqn_resolved", "the receiver resolves to %s" % (producer.fqn or name), 1.0),
            ("context_confirmed",
             "the step is inside a confirmed %s loop (line %d)" % (loop.kind,
                                                                   loop.loc.line), 1.0),
            ("knowledge_table",
             "%s is in the %s-cadence set of torch.optim.lr_scheduler"
             % (name, "epoch" if name in _EPOCH_CADENCE else "batch"), 1.0),
        ] + _static(call.scope)
        issues.append(ctx.issue(
            message="%s at %s:%d - %s." % (_short(call), call.loc.file, call.loc.line,
                                           variant),
            loc=call.loc, node_ids=[node] if node is not None else (),
            related=[("step_site", call.loc, "the scheduler is stepped here"),
                     ("construction", producer.loc, "%s is built here" % name)],
            evidence=evidence, stage="train", dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV208
# ---------------------------------------------------------------------------
def _scaler_for(ctx, loop: LoopIR,
                body: Sequence[CallSite] = ()) -> Optional[CallSite]:
    """The `GradScaler(...)` construction that governs this loop, if any.

    Proximity first - the construction in the loop's own function - and then,
    REC-04, **identity**: a `scaler.step(optimizer)` in this very loop whose
    receiver resolves to a `GradScaler(...)` written somewhere else is that
    scaler, whatever function built it. That is the shape a `make_state()` /
    `build()` factory writes, and it is the one the dataflow can now follow all
    the way through a parameter dict. Identity is strictly better evidence than
    proximity: the first arm guesses from position, the second one *knows*.
    """
    best = None
    for call in ctx.calls_with_role("GRAD_SCALER"):
        if call.module is not loop.module:
            continue
        if call.function is not None and loop.function is not None \
                and call.function is not loop.function:
            continue
        if best is None or call.loc.line < best.loc.line:
            best = call
    if best is not None:
        return best
    for call in body:
        receiver = call.receiver
        producer = receiver.producer if receiver is not None else None
        if producer is not None and K.role_of(producer.fqn) == "GRAD_SCALER":
            return producer
    return None


def _scaler_enabled(ctx, scaler: CallSite) -> Tuple[bool, float, str]:
    """`(judgeable, evidence weight, detail)` for `GradScaler(enabled=...)`."""
    node = scaler.kwarg_nodes.get("enabled")
    if node is None:
        return True, 1.0, "the scaler is unconditionally enabled"
    literal = literal_of(ctx, node, scaler.scope, scaler.module)
    if literal == "False":
        return False, 0.0, "GradScaler(enabled=False) is a no-op"
    if literal == "True":
        return True, 1.0, "GradScaler(enabled=True)"
    return True, 0.6, ("GradScaler(enabled=%s) is not a literal, so this finding is "
                       "de-rated rather than suppressed"
                       % (dotted_text(node) or "an expression"))


def _is_scaled(module: ModuleIR, call: CallSite) -> bool:
    """`scaler.scale(loss).backward()` - the receiver is the scale() call."""
    func = getattr(call.node, "func", None)
    inner = getattr(func, "value", None) if isinstance(func, ast.Attribute) else None
    if not isinstance(inner, ast.Call):
        return False
    for other in module.calls:
        if other.node is inner:
            return K.role_of(other.fqn) == "SCALE"
    text = dotted_text(inner.func)
    # An inner call the IR never recorded is not evidence of a *missing*
    # scale(): unreadable counts as scaled, which is the quiet direction.
    return text is None or text.rsplit(".", 1)[-1] == "scale"


@rule(code="MLV208", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="AMP GradScaler protocol is used inconsistently",
      why="Half-precision gradients underflow to zero without the scaler, so the run "
          "looks healthy while whole layers stop learning - and an unscaled clip "
          "clips the scaled values, which silently changes the clip threshold.",
      fix_hint="Use the full protocol: scaler.scale(loss).backward(); "
               "scaler.unscale_(optimizer) before any clip; scaler.step(optimizer); "
               "scaler.update().")
def amp_scaler_protocol(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loop in ctx.loops("batch"):
        body = calls_in_loop(ctx, loop, follow=False)
        scaler = _scaler_for(ctx, loop, body)
        if scaler is None:
            continue
        judgeable, weight, detail = _scaler_enabled(ctx, scaler)
        if not judgeable:
            continue
        found = _protocol_fault(ctx, loop, body)
        if found is None:
            continue
        call, variant, message = found
        node = _anchor(ctx, call)
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (scaler.fqn or "torch.amp.GradScaler"), 1.0),
            ("context_confirmed",
             "the batch loop at line %d runs under the GradScaler built at line %d"
             % (loop.loc.line, scaler.loc.line), 1.0),
            ("knowledge_table", detail, weight),
        ] + _static(loop.scope)
        issues.append(ctx.issue(
            message=message, loc=call.loc,
            node_ids=[node] if node is not None else (),
            related=[("construction", scaler.loc, "the GradScaler is built here"),
                     ("step_site", call.loc, "the protocol breaks here")],
            evidence=evidence, tags=("correctness", "train-loop", variant),
            stage="train", dynamic=loop.scope.is_dynamic))
    return issues


def _protocol_fault(ctx, loop: LoopIR, body: Sequence[CallSite]):
    """The first broken link of the AMP protocol in this loop body."""
    module = loop.module
    for call in with_role(body, "BACKWARD"):
        if not _is_scaled(module, call):
            return call, "unscaled_backward", (
                "%s at %s:%d runs under a GradScaler but is not wrapped in "
                "scaler.scale(...), so the half-precision gradients underflow."
                % (_short(call), call.loc.file, call.loc.line))
    for call in with_role(body, "OPT_STEP"):
        if call.fqn == "torch.optim.Optimizer.step":
            return call, "unscaled_step", (
                "%s at %s:%d steps the optimizer directly while a GradScaler is in "
                "use; the scaled gradients are applied without ever being unscaled."
                % (_short(call), call.loc.file, call.loc.line))
    steps = [c for c in body if c.fqn == "torch.amp.GradScaler.step"]
    if steps and not with_role(body, "SCALER_UPDATE"):
        searched = list(body)
        for outer in loop_chain(loop)[1:]:
            searched.extend(calls_in_loop(ctx, outer, follow=False))
        if not with_role(searched, "SCALER_UPDATE"):
            call = steps[0]
            return call, "missing_update", (
                "%s at %s:%d is never followed by scaler.update(), so the scale factor "
                "never adapts and the first overflow is never recovered from."
                % (_short(call), call.loc.file, call.loc.line))
    for call in with_role(body, "CLIP_GRAD"):
        unscales = [c for c in _in_block(body, call.block_id)
                    if K.role_of(c.fqn) == "UNSCALE" and c.stmt_index < call.stmt_index]
        if unscales:
            continue
        if with_role(body, "UNSCALE"):
            continue                    # unscaled somewhere else in the loop: not judged
        return call, "clip_without_unscale", (
            "%s at %s:%d clips gradients that are still multiplied by the GradScaler's "
            "scale factor, so the clip threshold is not the one you wrote."
            % (_short(call), call.loc.file, call.loc.line))
    return None


# ---------------------------------------------------------------------------
# MLV209
# ---------------------------------------------------------------------------
@rule(code="MLV209", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["correctness", "train-loop"],
      title="Gradient clipping in the wrong position",
      why="Clipping before the backward pass clips the previous batch's gradients and "
          "clipping after the optimizer step clips gradients that have already been "
          "applied, so in both cases the exploding update you meant to prevent still "
          "lands on the weights.",
      fix_hint="Order the step as loss.backward() -> clip_grad_norm_(...) -> "
               "optimizer.step().")
def clipping_out_of_position(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for loop in ctx.loops("batch"):
        body = [c for c in loop.module.calls if within_loop(c.loop, loop)]
        for clip in with_role(body, "CLIP_GRAD"):
            peers = _in_block(body, clip.block_id)
            backwards = with_role(peers, "BACKWARD")
            steps = with_role(peers, "OPT_STEP")
            partner = variant = None
            for backward in backwards:
                if clip.stmt_index < backward.stmt_index:
                    partner, variant = backward, "before_backward"
                    break
            if partner is None:
                for step in steps:
                    if clip.stmt_index > step.stmt_index:
                        partner, variant = step, "after_step"
                        break
            if partner is None:
                continue
            node = _anchor(ctx, clip)
            where = ("before %s at line %d, so it clips the previous iteration's "
                     "gradients" if variant == "before_backward"
                     else "after %s at line %d, so the update has already been applied")
            evidence = [
                ("fqn_resolved", "%s resolved to %s"
                 % (clip.short_name, clip.fqn or "a clipping call"), 1.0),
                ("context_confirmed",
                 "both calls sit in the same block of the batch loop at line %d"
                 % loop.loc.line, 1.0),
                ("dataflow_direct",
                 "statement index %d against %d in block %s"
                 % (clip.stmt_index, partner.stmt_index, clip.block_id or "-"), 1.0),
            ] + _static(loop.scope)
            issues.append(ctx.issue(
                message="%s at %s:%d runs %s."
                        % (_short(clip), clip.loc.file, clip.loc.line,
                           where % (_short(partner), partner.loc.line)),
                loc=clip.loc, node_ids=[node] if node is not None else (),
                related=[("backward_site" if variant == "before_backward" else "step_site",
                          partner.loc, "the gradients are %s here"
                          % ("computed" if variant == "before_backward" else "applied")),
                         ("call_site", clip.loc, "the clip happens here")],
                evidence=evidence, tags=("correctness", "train-loop", variant),
                stage="train", dynamic=loop.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV502
# ---------------------------------------------------------------------------
def _availability_checked(ctx) -> Optional[str]:
    """Any device-availability probe anywhere in the workspace."""
    for call in ctx.calls_with_role("DEVICE_CHECK"):
        return call.fqn or "torch.cuda.is_available"
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            text = dotted_text(call.node.func) or ""
            if text.endswith("is_available") or text.endswith("device_count"):
                return text
    return None


def _cuda_sites(ctx, module: ModuleIR) -> List[Tuple[CallSite, str]]:
    """`(call, what)` for every hard-coded CUDA device written in a module."""
    out: List[Tuple[CallSite, str]] = []
    for call in module.calls:
        if call.fqn == "torch.device" and call.args:
            node = call.args[0]
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.lower() in _CUDA_LITERALS:
                out.append((call, "torch.device(\"%s\")" % node.value))
        elif (call.method or "") == "cuda" and K.role_of(call.fqn) == "TO_DEVICE":
            out.append((call, "%s.cuda()" % (call.receiver_name or "a value")))
    out.sort(key=lambda pair: (pair[0].loc.line, pair[0].loc.col))
    return out


@rule(code="MLV502", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["portability", "device"],
      title="Hard-coded CUDA device with no availability check",
      why="On any machine without a GPU - a laptop, a CI runner, a colleague's box - "
          "the very first tensor move raises, so the script is not runnable anywhere "
          "except the machine it was written on.",
      fix_hint="Use device = torch.device(\"cuda\" if torch.cuda.is_available() else "
               "\"cpu\") and move the model and batches to that device.")
def hardcoded_cuda_device(ctx) -> Iterable[Issue]:
    """One finding per module, never one per `.to(device)`: the root cause is the
    single decision to name a device, and repeating it four times is noise."""
    if _availability_checked(ctx) is not None:
        return []
    issues: List[Issue] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        sites = _cuda_sites(ctx, module)
        if not sites:
            continue
        call, what = sites[0]
        node = _anchor(ctx, call)
        related = [("call_site", call.loc, "%s is written here" % what)]
        for other, other_what in sites[1:4]:
            related.append(("call_site", other.loc, "and again as %s" % other_what))
        evidence = [
            ("fqn_resolved", "%s resolved through the import table"
             % (call.fqn or "torch.device"), 1.0),
            ("negation_absent",
             "no torch.cuda.is_available() anywhere in the %d analyzed module(s)"
             % len(ctx.modules), 1.0),
            ("context_confirmed",
             "%d hard-coded CUDA site(s) in %s" % (len(sites), relpath), 1.0),
        ] + _static(call.scope)
        issues.append(ctx.issue(
            message="%s at %s:%d names a CUDA device outright and nothing in this "
                    "workspace calls torch.cuda.is_available(), so the program cannot "
                    "run on a CPU-only machine."
                    % (what, call.loc.file, call.loc.line),
            loc=call.loc, node_ids=[node] if node is not None else (),
            related=related, evidence=evidence, stage="config",
            dynamic=call.scope.is_dynamic))
    return issues


# ---------------------------------------------------------------------------
# MLV803
# ---------------------------------------------------------------------------
def _mentions_state_dict(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and (dotted_text(child.func) or "").endswith(
                "state_dict"):
            return True
        if isinstance(child, ast.Constant) and child.value == "state_dict":
            return True
    return False


@rule(code="MLV803", severity="low", base_prior=0.95, frameworks=["torch"],
      rule_version=1, tags=["deliver", "portability"],
      title="Whole model pickled, or torch.load left unrestricted",
      why="A pickled module stores the class path rather than the weights, so the "
          "checkpoint stops loading the day the file is renamed - and an unrestricted "
          "torch.load executes whatever the pickle tells it to.",
      fix_hint="Save torch.save(model.state_dict(), path) and load it back with "
               "torch.load(path, map_location=\"cpu\", weights_only=True).")
def unsafe_checkpoint_serialization(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for call in ctx.calls_of("torch.save"):
        if not call.args:
            continue
        node = call.args[0]
        if _mentions_state_dict(node):
            continue
        name = dotted_text(node)
        ref = ctx.binding_of(name, call.scope) if name else None
        is_model = bool(ref is not None and (ref.has("MODEL")
                                             or (ref.class_ir is not None
                                                 and ref.class_ir.is_model_module)))
        if not is_model:
            if name is not None and ref is None:
                ctx.untraced(call, name, "the saved value carries no MODEL tag, so "
                                         "MLV803 could not tell a module from a "
                                         "state_dict")
            continue
        anchor = _anchor(ctx, call)
        evidence = [
            ("fqn_resolved", "torch.save resolved through the import table", 1.0),
            ("dataflow_direct", "%s carries the MODEL tag" % name, 1.0),
            ("negation_absent",
             "the saved expression contains no .state_dict() call", 1.0),
        ] + _static(call.scope)
        issues.append(ctx.issue(
            message="torch.save at %s:%d pickles the module %s itself rather than "
                    "%s.state_dict(), so the checkpoint carries the class path and "
                    "breaks when the code moves."
                    % (call.loc.file, call.loc.line, name, name),
            loc=call.loc, node_ids=[anchor] if anchor is not None else (),
            related=[("call_site", call.loc, "the whole module is pickled here")],
            evidence=evidence, tags=("deliver", "portability", "whole_model"),
            stage="deliver", dynamic=call.scope.is_dynamic))
    for call in ctx.calls_of("torch.load"):
        if "map_location" in call.kwarg_nodes or "weights_only" in call.kwarg_nodes:
            continue
        anchor = _anchor(ctx, call)
        evidence = [
            ("fqn_resolved", "torch.load resolved through the import table", 1.0),
            ("negation_absent",
             "neither map_location= nor weights_only= is passed", 1.0),
        ] + _static(call.scope)
        issues.append(ctx.issue(
            message="torch.load at %s:%d passes neither map_location= nor "
                    "weights_only=, so it unpickles arbitrary objects and fails on a "
                    "machine without the device the checkpoint was saved from."
                    % (call.loc.file, call.loc.line),
            loc=call.loc, node_ids=[anchor] if anchor is not None else (),
            related=[("call_site", call.loc, "the checkpoint is loaded here")],
            evidence=evidence, tags=("deliver", "portability", "unsafe_load"),
            stage="deliver", dynamic=call.scope.is_dynamic))
    return issues
