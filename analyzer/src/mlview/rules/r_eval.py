"""Evaluation rules: MLV301 (no `model.eval()`), MLV302 (no `torch.no_grad()`).

Both start from the same **eval region** analysis, so the two findings always
agree about what counts as evaluation: a loop over a loader (or a function
named like an evaluation entrypoint) that runs a forward pass and neither
backpropagates nor steps an optimizer.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .. import knowledge as K
from ..core.graph import Issue
from ..ir.model import CallSite, ClassIR, FunctionIR
from .eval_regions import (EvalRegion, _NO_GRAD_DECORATORS, _SENSITIVE_ROLES,
                           _needs_gradients, eval_regions)
from .fixes import eval_mode_fix, no_grad_fix
from .registry import rule

__all__ = ["EvalRegion", "eval_regions", "eval_loop_without_eval_mode",
           "eval_loop_without_no_grad"]


# ---------------------------------------------------------------------------
# MLV301
# ---------------------------------------------------------------------------
@rule(code="MLV301", severity="high", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["correctness", "eval"], absence=True, cross_file=True,
      title="Evaluation runs without model.eval()",
      why="Dropout keeps dropping activations and BatchNorm keeps updating its running "
          "statistics, so the reported validation score is noisy and the model you "
          "ship is not the model you measured.",
      fix_hint="Call model.eval() before the validation loop and model.train() when "
               "returning to training.")
def eval_loop_without_eval_mode(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    for region in eval_regions(ctx):
        witness = _eval_mode_call(ctx, region)
        if witness is not None:
            continue
        cls = region.model_class
        sensitive = _sensitive_layers(ctx, cls)
        ghost = ctx.ghost("model", region.node, "model.eval()",
                          fqn="torch.nn.Module.eval")
        evidence = [
            ("fqn_resolved", "%s resolves to %s"
             % (region.model_name, region.forward.fqn or "an nn.Module forward"), 1.0),
            ("context_confirmed", region.why, 1.0),
            ("negation_absent",
             "no torch.nn.Module.eval() dominates this region", 1.0),
        ]
        severity = None
        sequential = _sequential_layers(ctx, region) if cls is None else None
        if cls is None and sequential is not None:
            # a bare `nn.Sequential(...)` has no ClassDef, but its element FQNs
            # are resolved already - reading them off is a real classification
            if sequential:
                evidence.append(("class_base",
                                 "the nn.Sequential contains %s, which behave "
                                 "differently in train mode"
                                 % ", ".join(sequential), 1.0))
            else:
                severity = "medium"
                evidence.append(("class_base",
                                 "the nn.Sequential declares no Dropout / BatchNorm, "
                                 "so eval() only matters for submodules", 0.6))
        elif cls is None:
            severity = "medium"
            evidence.append(("class_base",
                             "the model architecture could not be resolved, so the "
                             "train/eval-sensitive layers are unknown", 0.7))
        elif sensitive:
            evidence.append(("class_base",
                             "%s contains %s, which behave differently in train mode"
                             % (cls.name, ", ".join(sensitive)), 1.0))
        else:
            severity = "medium"
            evidence.append(("class_base",
                             "%s declares no Dropout / BatchNorm, so eval() only "
                             "matters for submodules" % cls.name, 0.6))
        if not region.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % region.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="%s is run at %s:%d without a preceding %s.eval(); %s."
                    % (region.model_name, region.forward.loc.file,
                       region.forward.loc.line, region.model_name, region.why),
            loc=region.loc, node_ids=[ghost, region.node],
            related=_related_for(region, cls), evidence=evidence,
            dynamic=region.scope.is_dynamic, severity=severity,
            # H5. Note the interaction with `severity` above: an unresolved
            # architecture drops this to medium, never below `likely`, so the
            # edit follows the finding rather than being gated separately.
            fix=eval_mode_fix(ctx, region)))
    return issues


def _related_for(region: EvalRegion, cls: Optional[ClassIR]):
    related = [("eval_loop", region.loc, region.why),
               ("call_site", region.forward.loc, "forward pass here")]
    if cls is not None:
        related.append(("definition", cls.loc, "model class %s" % cls.name))
    return related


def _wrapper_owns_the_loop(ctx, region: EvalRegion) -> bool:
    """Lightning / HF Trainer / accelerate call eval() for you (iron law 4).

    The gate **de-rates**, it does not delete: iron law 4 multiplies the
    confidence by 0.4 (dropping the finding to `speculative`, off the Problems
    panel and behind the canvas toggle) and shows a chip explaining why. A hard
    `return []` made three genuine findings disappear with no user-visible
    trace, and it applied workspace-wide - so one unrelated HuggingFace script
    silenced the hand-written loop in the file next to it.
    """
    return bool(ctx.wrappers_for(region.loc.file))


def _eval_mode_call(ctx, region: EvalRegion) -> Optional[CallSite]:
    """A `model.eval()` that dominates this region, one level of call following.

    Deliberately generous: any `eval()` in the enclosing function counts, even
    on a differently-named binding, because a false accusation here is far
    worse than a missed one.
    """
    # VIS2-13. The search used to read **one** module - the one the forward
    # pass is written in - and ask only whether the call sat in
    # `region.func`. When the region is a loop in one function and the forward
    # happens in a callee in another file (`tta_accuracy` -> `tta_logits`,
    # `robust_accuracy` -> `fgsm`: the shape of every TTA / adversarial
    # evaluation), those two are never the same module, so an `model.eval()`
    # written immediately above the loop was invisible and the finding's own
    # evidence row asserted "no torch.nn.Module.eval() dominates this region"
    # about a workspace with nine of them. The region's own module and the
    # function that contains the forward are both part of the region.
    modules = []
    for module in (_module_of(region.func), region.forward.module,
                   _module_of(region.forward.function)):
        if module is not None and all(module is not m for m in modules):
            modules.append(module)
    calls: List[CallSite] = []
    for module in modules:
        calls.extend(_eval_mode_calls(ctx, module))
    name = region.model_name
    # The bound is the *forward pass*, not the region header: a function region
    # is anchored on its `def` line, so `model.eval()` on the first line of the
    # body is always below it and would never be seen.
    limit = max(region.loc.line, region.forward.loc.line)
    same = [c for c in calls if not c.receiver_name or not name
            or c.receiver_name == name]
    for group in (same, calls):
        for call in group:
            if call.function is region.func and call.loc.line <= limit:
                return call
        # The callee that runs the forward may guard itself - `def tta_logits(
        # model, x): model.eval(); return model(x)` - and that dominates the
        # forward just as surely as a switch in the caller does.
        for call in group:
            owner = region.forward.function
            if owner is not None and call.function is owner \
                    and call.loc.line <= region.forward.loc.line:
                return call
    for call in calls:
        if call.function is None:                # module-level setup: model.eval()
            return call
    if region.func is None:
        return None
    for caller in _callers_of(ctx, region.func):
        for call in _eval_mode_calls(ctx, caller.module):
            if call.function is caller.function and call.loc.line <= caller.loc.line:
                return call
    return None


def _module_of(func: Optional[FunctionIR]):
    return getattr(func, "module", None) if func is not None else None


def _eval_mode_calls(ctx, module) -> List[CallSite]:
    return [c for c in module.calls if K.role_of(c.fqn) == "EVAL_MODE"]


def _callers_of(ctx, func: FunctionIR) -> List[CallSite]:
    out: List[CallSite] = []
    for relpath in sorted(ctx.modules):
        for call in ctx.modules[relpath].calls:
            if call.target_function is func:
                out.append(call)
    return out


def _sequential_layers(ctx, region: EvalRegion) -> Optional[List[str]]:
    """Train/eval-sensitive elements of a model built as a bare `nn.Sequential`.

    Returns `None` when the model is not a fully-literal `nn.Sequential` (so the
    architecture really is unresolved), and the - possibly empty - list of
    sensitive layer names when it is.
    """
    ref = region.model_ref
    producer = ref.producer if ref is not None else None
    if producer is None:
        return None
    if "torch.nn.Sequential" not in (producer.canonical_fqns or ()):
        return None
    by_node = getattr(producer.module, "_calls_by_node", {})
    found: List[str] = []
    for arg in producer.args:
        inner = by_node.get(id(arg))
        fqn = inner.fqn if inner is not None else None
        if not fqn:
            return None              # `nn.Sequential(*layers)` - not readable
        if K.role_of(fqn) in _SENSITIVE_ROLES:
            short = fqn.split(".")[-1]
            if short not in found:
                found.append(short)
    return found


def _sensitive_layers(ctx, cls: Optional[ClassIR], depth: int = 0) -> List[str]:
    """Dropout / BatchNorm declared by the model (LayerNorm is exempt)."""
    if cls is None or depth > 2:
        return []
    found: List[str] = []
    for call in cls.calls:
        role = K.role_of(call.fqn)
        if role in _SENSITIVE_ROLES:
            short = (call.fqn or call.short_name).split(".")[-1]
            if short not in found:
                found.append(short)
        elif call.class_ir is not None and call.class_ir is not cls \
                and call.class_ir.is_nn_module:
            for name in _sensitive_layers(ctx, call.class_ir, depth + 1):
                if name not in found:
                    found.append(name)
    return found


# ---------------------------------------------------------------------------
# MLV302
# ---------------------------------------------------------------------------
@rule(code="MLV302", severity="medium", base_prior=0.85, frameworks=["torch"],
      rule_version=1, tags=["performance", "eval"], cross_file=True,
      title="Evaluation loop not wrapped in torch.no_grad()",
      why="Autograd keeps every intermediate activation alive for a backward pass that "
          "never happens, so evaluation uses several times the memory it needs and can "
          "run out of GPU memory on a larger batch.",
      fix_hint="Wrap the evaluation loop in with torch.no_grad(): (or "
               "torch.inference_mode()), or decorate the function with @torch.no_grad().")
def eval_loop_without_no_grad(ctx) -> Iterable[Issue]:
    issues: List[Issue] = []
    seen = set()
    for region in eval_regions(ctx):
        if region.inside_no_grad or _decorated_no_grad(region.func):
            continue
        if _needs_gradients(region):
            continue                     # saliency / adversarial evaluation
        key = (region.loc.file, region.loc.line)
        if key in seen:
            continue
        seen.add(key)
        evidence = [
            ("fqn_resolved", "%s resolves to %s"
             % (region.model_name, region.forward.fqn or "an nn.Module forward"), 1.0),
            ("context_confirmed", region.why, 1.0),
            ("negation_absent",
             "no enclosing torch.no_grad() / torch.inference_mode() block and no "
             "@torch.no_grad() decorator", 1.0),
        ]
        if not region.scope.is_dynamic:
            evidence.append(("scope_static",
                             "no dynamic constructs in %s" % region.scope.qualname, 1.0))
        issues.append(ctx.issue(
            message="The evaluation region at %s:%d builds an autograd graph it never "
                    "uses: %s."
                    % (region.loc.file, region.loc.line, region.why),
            loc=region.loc, node_ids=[region.node],
            related=[("eval_loop", region.loc, region.why),
                     ("call_site", region.forward.loc, "forward pass here")],
            evidence=evidence, dynamic=region.scope.is_dynamic,
            wrapper_gated=_wrapper_owns_the_loop(ctx, region),
            # H5: the decorator form only, and only for a function that
            # provably never trains - see `fixes.no_grad_fix` for why the
            # `with` wrap the fix hint names is not built.
            fix=no_grad_fix(ctx, region)))
    return issues


def _decorated_no_grad(func: Optional[FunctionIR]) -> bool:
    while func is not None:
        for dec in func.decorators:
            if dec.split(".")[-1] in _NO_GRAD_DECORATORS:
                return True
        if func.inside_no_grad:
            return True
        func = func.parent_function
    return False
