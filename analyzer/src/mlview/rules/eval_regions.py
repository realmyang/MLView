"""Where is this project *evaluating*? The region, and the evidence for it.

MLV301 and MLV302 are both "inside an evaluation region, the model is in the
wrong state", so the region is the subject and finding it is most of the work.
An `EvalRegion` is a loop or a function that independent evidence says is an
evaluation: a metric call, a framework hook that is one by declaration, a
`no_grad` decorator, an eval-shaped name - never the name alone.

The test-suite exclusions are here for the same reason: a `pytest` case that
forwards a model is not an evaluation loop, and saying so once keeps both rules
from firing on every test file in the workspace.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Sequence

from .. import knowledge as K
from ..core.graph import Node
from ..ir.model import (CallSite, ClassIR, FunctionIR, Loc, LoopIR, ScopeIR,
                        ValueRef)
from .helpers import calls_in_loop, with_role


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
        if _in_a_pytest_case(ctx, loop.function):
            continue                     # PUB2-03: a unit test, not evaluation
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
        # PUB-05. Unlike the loop branch above, this one never asked for
        # positive evidence: the name regex alone created the region, and the
        # regex matches `test`, so every pytest case that builds a module and
        # runs one forward pass was reported at high / 0.85 - on vit-pytorch's
        # and stable-baselines3's own test suites among others. Iron law 2 says
        # a name regex reinforces a dataflow signal and never creates one; this
        # is that law applied where it was missing.
        positive = _function_evaluation_evidence(ctx, func, calls)
        if not positive:
            continue
        node = ctx.builder.scope_unit.get(func.scope.qualname)
        if node is None:
            continue
        why = "%s() runs a forward pass, never calls backward() or " \
              "optimizer.step(), and %s" % (func.name, positive)
        regions.append(EvalRegion(node, func.loc, func.scope, forwards[0], calls,
                                  func=func, why=why))
    regions.sort(key=lambda r: (r.loc.file, r.loc.line, r.loc.col))
    return regions


#: Roles that only appear when a model is being *measured*, not trained.
_MEASURE_ROLES = ("METRIC", "SCORE_METRIC", "PREDICT", "ARGMAX", "TO_NUMPY", "CV")
_LOSS_ROLES = ("LOSS_CLS", "LOSS_FN")


#: PUB-09. Frameworks whose models have neither `.eval()` nor `torch.no_grad()`.
#: MLV301/MLV302 declare `frameworks=["torch"]`, and that declaration was
#: enforced at the workspace, never at the receiver - so a keras-io example
#: whose `def infer(...)` calls a `keras.Model` was told to call
#: `zero_dce_model.eval()`, a method that does not exist in Keras.
_NON_TORCH_FRAMEWORKS = frozenset({"keras", "tf"})


def _is_torch_model(call: CallSite) -> bool:
    """Is the receiver of this forward pass a torch module?

    Silence is the answer whenever the receiver resolves to a framework whose
    models are not `nn.Module`s. A receiver that resolved to nothing is left
    alone: that is MLV301's documented unresolved-architecture case, which
    de-rates rather than disappears.
    """
    ref = call.receiver
    producer = ref.producer if ref is not None else None
    candidates: List[str] = []
    if producer is not None:
        candidates.extend(producer.canonical_fqns or ())
        if producer.fqn:
            candidates.append(producer.fqn)
    if ref is not None:
        candidates.extend(getattr(ref, "via_fqns", ()) or ())
    entry, _which = K.best_entry(candidates)
    if entry is not None and entry["framework"] in _NON_TORCH_FRAMEWORKS:
        return False
    cls = ref.class_ir if ref is not None else None
    cls = cls or call.class_ir
    if cls is not None and not cls.is_model_module and cls.resolved_bases:
        return False
    return True


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
        if not _is_torch_model(call):
            continue                     # PUB-09: not a torch model at all
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
        # IP-01: this ValueRef comes off the loop, not off `ctx.binding_of`, so
        # it declares its own hop; a region recognised only because a tag
        # crossed an object boundary must pay for the crossing.
        ctx.note_hops(iterates, loop.scope)
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


def _function_evaluation_evidence(ctx, func: FunctionIR,
                                  calls: Sequence[CallSite]) -> str:
    """Why this *function* looks like evaluation, beyond being named like one.

    The same three positive signals the loop branch demands (PUB-05): it runs
    with gradients off, it measures something, or it iterates a held-out
    loader. The eval-shaped name is what selected the function; it is not also
    allowed to be the evidence.
    """
    if func.inside_no_grad or any(d in _NO_GRAD_DECORATORS for d in func.decorators or ()):
        return "it runs with gradients disabled"
    if any(c.inside_no_grad for c in calls):
        return "its forward pass runs inside a no-grad context"
    measured = with_role(calls, *_MEASURE_ROLES)
    if measured:
        call = measured[0]
        return "it computes %s at line %d" % (call.fqn or call.short_name,
                                              call.loc.line)
    for call in calls:
        if K.role_of(call.fqn) == "EVAL_MODE":
            return "it calls %s at line %d" % (call.short_name, call.loc.line)
    return ""


#: PUB-05. A pytest case is not an evaluation, whatever it is called. `test_*`
#: is in `_EVAL_NAME_RE` for `test_loop` / `test_step`, and a file under a
#: `tests/` directory (or named `test_*.py` / `*_test.py`) is where the
#: collision lives.
#: PUB2-03. Round 1 closed this with ONE filename pattern - `test_*.py` or
#: `*_test.py` - plus a directory arm that drops the filename before looking,
#: so a module literally called `tests.py` matched neither and MLV302 went on
#: telling readers to wrap a pytest case in `torch.no_grad()`. Measured on
#: rasbt/LLMs-from-scratch: four findings across two `ch*/.../tests.py` files,
#: at 0.85 and 0.68, both above the Problems-panel floor. `model_tests.py` and
#: `conftest.py` fall through the same hole and are equally ordinary pytest
#: module names.
_TEST_FILE_RE = re.compile(
    r"(?i)(^|/)(test_[^/]*\.py|[^/]*_tests?\.py|tests?\.py|conftest\.py)$")
#: The second, un-spoofable signal: the module imports a test framework, or the
#: function carries a `@pytest.*` decorator. A project that puts its cases in
#: `checks.py` is covered by this and by nothing else.
_TEST_IMPORTS = ("pytest", "unittest", "nose", "hypothesis")


def _is_test_module(relpath: str) -> bool:
    path = (relpath or "").replace("\\", "/")
    if _TEST_FILE_RE.search(path):
        return True
    return any(part in ("test", "tests") for part in path.split("/")[:-1])


def _imports_a_test_framework(module) -> bool:
    symbols = getattr(module, "symbols", None)
    aliases = getattr(symbols, "aliases", None) or {}
    for fqn in aliases.values():
        head = (fqn or "").split(".")[0]
        if head in _TEST_IMPORTS:
            return True
    for name in getattr(module, "imports", ()) or ():
        if str(name).split(".")[0] in _TEST_IMPORTS:
            return True
    return False


def _is_test_function(func: FunctionIR) -> bool:
    if func.name.lower().startswith("test"):
        return True
    return any((d or "").split(".")[0] == "pytest" for d in func.decorators or ())


def _eval_named_functions(ctx) -> List[FunctionIR]:
    out: List[FunctionIR] = []
    for relpath in sorted(ctx.modules):
        module = ctx.modules[relpath]
        in_tests = _is_test_module(relpath) or _imports_a_test_framework(module)
        for qualname in sorted(module.functions):
            func = module.functions[qualname]
            if not _EVAL_NAME_RE.match(func.name):
                continue
            if in_tests and _is_test_function(func):
                continue                 # a pytest case, not an evaluation loop
            out.append(func)
    return out


def _in_a_pytest_case(ctx, func: Optional[FunctionIR]) -> bool:
    """Is this function a pytest case (PUB2-03)?

    The same two signals `_eval_named_functions` uses, applied to a loop-based
    region: a test module (by path or by what it imports) plus a test-shaped
    function name or a `@pytest.*` decorator.
    """
    while func is not None:
        module = getattr(func, "module", None)
        relpath = getattr(module, "relpath", "") if module is not None else ""
        if (_is_test_module(relpath)
                or (module is not None and _imports_a_test_framework(module))):
            if _is_test_function(func):
                return True
        func = func.parent_function
    return False


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
