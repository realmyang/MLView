"""Evaluation rules: MLV301 (no `model.eval()`), MLV302 (no `torch.no_grad()`).

Both start from the same **eval region** analysis, so the two findings always
agree about what counts as evaluation: a loop over a loader (or a function
named like an evaluation entrypoint) that runs a forward pass and neither
backpropagates nor steps an optimizer.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional, Sequence

from .. import knowledge as K
from ..core.graph import Issue, Node
from ..ir.model import CallSite, ClassIR, FunctionIR, Loc, LoopIR, ScopeIR, ValueRef
from .fixes import eval_mode_fix, no_grad_fix
from .helpers import calls_in_loop, with_role
from .registry import rule

__all__ = ["EvalRegion", "eval_regions", "eval_loop_without_eval_mode",
           "eval_loop_without_no_grad"]

_EVAL_NAME_RE = re.compile(r"(?i)^(validate|validation|evaluate|evaluation|val|test|"
                           r"testing|predict|prediction|inference|infer|score)(_|$)")
#: Layers whose behaviour differs between `train()` and `eval()`.
_SENSITIVE_ROLES = frozenset({"DROPOUT", "NORM_TRAIN_SENSITIVE"})
_TRAINING_ROLES = ("BACKWARD", "OPT_STEP", "ZERO_GRAD")
_NO_GRAD_DECORATORS = ("no_grad", "inference_mode")


class EvalRegion:
    """One place where a model is run for evaluation."""

    def __init__(self, node: Node, loc: Loc, scope: ScopeIR, forward: CallSite,
                 calls: Sequence[CallSite], func: Optional[FunctionIR] = None,
                 loop: Optional[LoopIR] = None, why: str = ""):
        self.node = node
        self.loc = loc
        self.scope = scope
        self.forward = forward
        self.calls = list(calls)
        self.func = func
        self.loop = loop
        self.why = why

    @property
    def model_ref(self) -> Optional[ValueRef]:
        return self.forward.receiver

    @property
    def model_name(self) -> str:
        return self.forward.receiver_name or self.forward.short_name

    @property
    def model_class(self) -> Optional[ClassIR]:
        ref = self.model_ref
        if ref is not None and ref.class_ir is not None:
            return ref.class_ir
        return self.forward.class_ir

    @property
    def inside_no_grad(self) -> bool:
        if self.loop is not None and self.loop.inside_no_grad:
            return True
        return bool(self.forward.inside_no_grad)


# ---------------------------------------------------------------------------
# region discovery
# ---------------------------------------------------------------------------
def eval_regions(ctx) -> List[EvalRegion]:
    """Every loop / function that runs a model without training it.

    The absence of `backward()` is not enough on its own: a loop that only
    accumulates a loss for one backward pass per epoch has the same shape.
    A region therefore also needs **positive** evidence of evaluation - a
    no-grad context, an evaluation-shaped function name, a metric/prediction
    call, or a loader over the held-out split.
    """
    regions: List[EvalRegion] = []
    claimed = set()
    for loop in ctx.loops("batch"):
        if framework_hook(loop.function):
            continue
        calls = calls_in_loop(ctx, loop)
        forwards = _model_forwards(calls)
        if not forwards or with_role(calls, *_TRAINING_ROLES):
            continue
        positive = _evaluation_evidence(ctx, loop, calls)
        if not positive:
            continue
        node = ctx.node_for_loop(loop)
        if node is None:
            continue
        why = "the loop at line %d over %s runs a forward pass, never calls backward() " \
              "or optimizer.step(), and %s" % (loop.loc.line,
                                               loop.iter_text or "a loader", positive)
        regions.append(EvalRegion(node, loop.loc, loop.scope, forwards[0], calls,
                                  func=loop.function, loop=loop, why=why))
        for call in forwards:
            claimed.add(id(call))
    for func in _eval_named_functions(ctx):
        if framework_hook(func):
            continue
        calls = list(func.calls)
        forwards = [c for c in _model_forwards(calls) if id(c) not in claimed]
        if not forwards or with_role(calls, *_TRAINING_ROLES):
            continue
        node = ctx.builder.scope_unit.get(func.scope.qualname)
        if node is None:
            continue
        why = "%s() runs a forward pass and never calls backward() or " \
              "optimizer.step()" % func.name
        regions.append(EvalRegion(node, func.loc, func.scope, forwards[0], calls,
                                  func=func, why=why))
    regions.sort(key=lambda r: (r.loc.file, r.loc.line, r.loc.col))
    return regions


#: Roles that only appear when a model is being *measured*, not trained.
_MEASURE_ROLES = ("METRIC", "SCORE_METRIC", "PREDICT", "ARGMAX", "TO_NUMPY", "CV")
_LOSS_ROLES = ("LOSS_CLS", "LOSS_FN")


def _model_forwards(calls: Sequence[CallSite]) -> List[CallSite]:
    """FORWARD calls that are a *model* forward - `criterion(...)` is not one.

    A loss module is an `nn.Module` too, so its `__call__` also resolves to
    `torch.nn.Module.__call__`; matching it would make the rule talk about the
    wrong object.
    """
    out: List[CallSite] = []
    for call in with_role(calls, "FORWARD"):
        ref = call.receiver
        if ref is not None and ref.has("LOSS"):
            continue
        if any(K.role_of(f.rsplit(".__call__", 1)[0]) in _LOSS_ROLES
               for f in call.canonical_fqns or ()):
            continue
        out.append(call)
    return out


def _evaluation_evidence(ctx, loop: LoopIR, calls: Sequence[CallSite]) -> str:
    """Why this loop looks like evaluation rather than an accumulation step."""
    if loop.inside_no_grad:
        return "it runs inside a no-grad context"
    func = loop.function
    while func is not None:
        if _EVAL_NAME_RE.match(func.name):
            return "it sits in %s()" % func.name
        func = func.parent_function
    measured = with_role(calls, *_MEASURE_ROLES)
    if measured:
        call = measured[0]
        return "its body computes %s at line %d" % (
            call.fqn or call.short_name, call.loc.line)
    iterates = loop.iterates
    if iterates is not None and iterates.has("VAL_SPLIT", "TEST_SPLIT"):
        return "it iterates %s, which carries the held-out split" % iterates.name
    return ""


def framework_hook(func: Optional[FunctionIR]) -> Optional[str]:
    """The framework hook a function *is*, walking out through nested defs.

    FW-RECOG makes `validation_step` a real eval region: `self(features)` now
    resolves to a forward pass, where before it resolved to nothing. That is
    the recognition working - and it re-arms MLV301 / MLV302 on **correct**
    Lightning code, because there is no `model.eval()` in a `validation_step`
    and there must not be: Lightning calls it for you before it calls the hook.

    Iron law 4's `WRAPPER_FACTOR` de-rate is the right answer for a
    hand-written loop in a file that happens to import a wrapper. It is the
    wrong answer here, because the region **is** the wrapper's own hook: the
    finding is not weak evidence, it is a statement about code the user does
    not own. So a hook body is not an eval region at all.
    """
    while func is not None:
        cls = getattr(func, "class_ir", None)
        if (cls is not None and cls.is_hook_owner
                and K.hook_stage(func.name) is not None):
            return func.name
        func = func.parent_function
    return None


def _eval_named_functions(ctx) -> List[FunctionIR]:
    out: List[FunctionIR] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            if _EVAL_NAME_RE.match(func.name):
                out.append(func)
    return out


def _needs_gradients(region: EvalRegion) -> bool:
    """Saliency / adversarial evaluation genuinely needs the graph."""
    for call in region.calls:
        name = (call.method or call.short_name or "")
        if name in ("requires_grad_", "grad") or (call.fqn or "").startswith(
                "torch.autograd."):
            return True
    node = region.loop.node if region.loop is not None else (
        region.func.node if region.func is not None else None)
    if node is None:
        return False
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in ("requires_grad",
                                                               "requires_grad_"):
            return True
    return False


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
    calls = _eval_mode_calls(ctx, region.forward.module)
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
