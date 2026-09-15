"""Loop kind: which `for`/`while` is an epoch, a batch, a fold, a sweep.

`classify_loops` is the second pass over the loops `ir/scopes_walk.py`
recorded, run once the bindings exist because the answer needs them: what the
loop iterates (a DataLoader, a splitter, a `range`), what its body does to a
model (a backward, an optimiser step, a `fit`), and what its target is called,
in that order - the name is the last and weakest signal, never the first.
"""
from __future__ import annotations

import ast
from typing import Dict, List

from .model import CallSite, LoopIR, ModuleIR
from .symbols import dotted_text

__all__ = ["classify_loops"]


_LOADER_NAME_RE = ("loader", "_dl", "dl_", "batches", "dataloader")
_EPOCH_NAMES = ("epoch", "epochs", "n_epochs", "num_epochs", "max_epochs")


# ---------------------------------------------------------------------------
# loop classification (runs after bindings exist)
# ---------------------------------------------------------------------------

def _unwrap_iter(node: ast.expr) -> ast.expr:
    """Strip enumerate()/zip()/tqdm() wrappers around the iterated value."""
    seen = 0
    while isinstance(node, ast.Call) and seen < 4:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        if name in ("enumerate", "tqdm", "zip", "iter", "list", "reversed", "trange"):
            if not node.args:
                return node
            node = node.args[0]
            seen += 1
            continue
        break
    return node


#: `_classify`'s evidence phrase for the literal-range branch, so the second
#: pass can find exactly the loops that arm alone claimed (PUB2-07).
_LITERAL_RANGE = "range() over a literal count"

#: Method names that mean a loop body updates a model, whatever resolved.
#: Same set and same argument as `core/views._TRAINING_CALL_NAMES`: none of the
#: four has a non-training meaning, so a loop carrying one really does train.
_UPDATE_NAMES = ("backward", "apply_gradients", "minimize")
_STEP_NAMES = ("step", "zero_grad", "apply_gradients", "minimize")
#: Roles that say the same thing, when the call resolved.
_BACKWARD_ROLES = ("BACKWARD", "TAPE_GRADIENT")
_STEP_ROLES = ("OPT_STEP", "ZERO_GRAD", "TF_OPT_STEP")
#: Roles that mean a loop body does ML work at all (PUB2-07's evidence test).
_ML_ROLES = frozenset({
    "BACKWARD", "OPT_STEP", "ZERO_GRAD", "SCALE", "SCALER_UPDATE", "UNSCALE",
    "TAPE_GRADIENT", "TF_OPT_STEP", "FORWARD", "PREDICT", "FIT", "KERAS_FIT",
    "KERAS_EVAL", "HF_TRAIN", "HF_EVAL", "METRIC", "SCORE_METRIC", "ARGMAX",
    "GBM_TRAIN", "SCHED_STEP", "SCHED_STEP_BATCH", "EVAL_MODE", "TRAIN_MODE",
    "CLIP_GRAD", "LIGHTNING_FIT", "FASTAI_FIT", "IGNITE_RUN", "EMA_UPDATE",
})


def _own_body(loop: LoopIR):
    """Statements of this loop's body, not descending into a nested loop.

    A nested loop is its own loop and answers for itself; without this, an
    epoch loop would inherit every piece of evidence its batch loop carries.
    """
    stack = list(getattr(loop.node, "body", []) or []) + list(
        getattr(loop.node, "orelse", []) or [])
    while stack:
        stmt = stack.pop()
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield stmt
        for field_name in ("body", "orelse", "finalbody"):
            stack.extend(getattr(stmt, field_name, []) or [])
        for handler in getattr(stmt, "handlers", []) or []:
            stack.extend(handler.body or [])
        for case in getattr(stmt, "cases", []) or []:
            stack.extend(case.body or [])


def _own_calls(loop: LoopIR, module: ModuleIR) -> List[CallSite]:
    """Resolved call sites whose innermost loop is exactly this one."""
    return [c for c in module.calls if c.loop is loop]


def _method_names(loop: LoopIR) -> set:
    """Attribute-call names written directly in this loop's own body."""
    out = set()
    for stmt in _own_body(loop):
        for child in ast.walk(stmt):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                out.add(child.func.attr)
    return out


def _updates_a_model(loop: LoopIR, module: ModuleIR, role_of) -> bool:
    """Does this loop body run a training step? (PUB2-06 / DGRG2-02)

    `_classify` only ever produced `batch` for a `for` over something that
    resolved as a loader, so two whole shapes of training loop were not loops
    at all as far as the graph and MLV201-205 were concerned:

    * `while True:` / `while step < max_steps:` with `next(data_iter)` inside -
      minGPT's `Trainer.run` and nanoGPT's `train.py`, and a large fraction of
      RL and LLM-pretraining code. nanoGPT's train lane had no loop node at
      all, so README requirement 1's "the training loop drawn **as a loop**"
      did not happen on the flagship repository;
    * `for start in range(0, n, MINIBATCH):` - the PPO / SAC minibatch loop,
      whose range is not literal so it was kinded `other`.

    The evidence is the training step itself: something back-propagates and
    something steps or zeroes an optimizer, in this loop's own body. Resolved
    roles answer first; the syntactic names are the fallback for the case the
    receiver did not type, which is exactly minGPT's.
    """
    calls = _own_calls(loop, module)
    roles = {role_of(c.fqn) for c in calls}
    if roles & set(_BACKWARD_ROLES) and roles & set(_STEP_ROLES):
        return True
    names = _method_names(loop)
    if names & set(_UPDATE_NAMES) and names & set(_STEP_NAMES):
        return True
    return False


def _has_ml_content(loop: LoopIR, module: ModuleIR, role_of) -> bool:
    """PUB2-07: is there anything in this loop that is machine learning?

    `for i in range(<literal>)` used to be classified an **epoch loop** on that
    shape alone - no backward, no forward, no metric, no nested batch loop -
    and `core/build.py` then drew it as a `train_loop`, declared the `train`
    stage present, and let the absence rules treat the workspace as having a
    confirmed training loop. Measured over the 37-repo public corpus, 739 of
    4898 train/eval loop nodes (15.1%) were matplotlib subplot loops, timing
    benchmarks and lookup-table builders; on tensorflow/models the ONLY node in
    the entire train lane of a 398-node diagram was a loop that appends 100
    float thresholds to a protobuf config.

    "The count is a literal" is not evidence of anything. The two other epoch
    signals - an epoch-shaped argument, an epoch-shaped target - are real and
    stay unconditional.
    """
    if any(role_of(c.fqn) in _ML_ROLES for c in _own_calls(loop, module)):
        return True
    if _method_names(loop) & (set(_UPDATE_NAMES) | set(_STEP_NAMES) | {"fit"}):
        return True
    for inner in module.loops:
        parent = inner.parent_loop
        while parent is not None:
            if parent is loop:
                if inner.kind in ("batch", "fold"):
                    return True
                break
            parent = parent.parent_loop
    return False


def classify_loops(module: ModuleIR, binding_lookup) -> None:
    """Assign `kind`, `iterates` and a stable qualname to every loop."""
    from ..knowledge import role_of

    counters: Dict[str, int] = {}
    for loop in module.loops:
        kind, evidence, value = _classify(loop, binding_lookup)
        loop.kind = kind
        loop.evidence = evidence
        loop.iterates = value
    # PUB2-06 / DGRG2-02: a loop whose own body runs a training step is a batch
    # loop whatever it iterates - a `while`, a minibatch `range`, an index scan.
    for loop in module.loops:
        if loop.kind != "other":
            continue
        if _updates_a_model(loop, module, role_of):
            loop.kind = "batch"
            loop.evidence = ("its body back-propagates and steps an optimizer",)
    # PUB2-07: the literal-range arm needs ML content before it may claim an
    # epoch loop. Runs last, so a nested loop this pass promoted to `batch`
    # counts as evidence for the loop that encloses it.
    for loop in module.loops:
        if loop.kind != "epoch" or loop.evidence != (_LITERAL_RANGE,):
            continue
        if not _has_ml_content(loop, module, role_of):
            loop.kind = "other"
            loop.evidence = ()
    for loop in module.loops:
        base = "%s.%s_loop" % (loop.scope.qualname, loop.kind)
        counters[base] = counters.get(base, 0) + 1
        loop.qualname = base if counters[base] == 1 else "%s%d" % (base, counters[base])


def _classify(loop: LoopIR, binding_lookup):
    node = loop.node
    if not isinstance(node, (ast.For, ast.AsyncFor)):
        return "other", (), None
    iter_node = _unwrap_iter(node.iter)
    targets = loop.targets
    value = None
    name = dotted_text(iter_node)
    if name:
        value = binding_lookup(name, loop.scope)

    # fold: iterating a splitter's .split()
    if isinstance(iter_node, ast.Call):
        callee = iter_node.func
        if isinstance(callee, ast.Attribute) and callee.attr == "split":
            base = dotted_text(callee.value)
            base_ref = binding_lookup(base, loop.scope) if base else None
            if base_ref is not None and base_ref.producer is not None:
                from ..knowledge import role_of
                if role_of(base_ref.producer.fqn) in ("SPLITTER", "SPLIT"):
                    return "fold", ("iterates a cross-validation splitter",), base_ref
            if base and any(k in base.lower() for k in ("kfold", "splitter", "cv", "skf")):
                return "fold", ("iterates a splitter-named value",), base_ref
        func_fqn = None
        if isinstance(callee, ast.Name):
            func_fqn = callee.id
        if func_fqn == "range":
            arg_names = [dotted_text(a) or "" for a in iter_node.args]
            if any(any(e in (a or "").lower() for e in _EPOCH_NAMES) for a in arg_names):
                return "epoch", ("range() over an epoch count",), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("range() with an epoch target",), None
            # A *fully* literal range - `range(10)`, `range(0, 100, 5)`. One
            # literal bound is not enough: `range(1, len(parts))` is ordinary
            # index arithmetic, not an epoch count.
            if iter_node.args and all(isinstance(a, ast.Constant) for a in iter_node.args):
                return "epoch", (_LITERAL_RANGE,), None
            if any("epoch" in t.lower() for t in targets):
                return "epoch", ("epoch loop target",), None
            return "other", (), None

    if any("epoch" in t.lower() for t in targets):
        return "epoch", ("loop target named epoch",), None

    if value is not None and value.has("LOADER"):
        return "batch", ("iterates a LOADER-tagged value",), value
    lowered = (name or "").lower()
    if lowered and any(k in lowered for k in _LOADER_NAME_RE):
        return "batch", ("iterates a loader-named value",), value
    if value is not None and value.has("TRAIN_SPLIT", "VAL_SPLIT", "TEST_SPLIT", "BATCH"):
        return "batch", ("iterates a split value",), value
    return "other", (), value
