"""Source views and label helpers used by the graph builder.

`ParsedView` is the minimal `ParsedFile`-compatible wrapper `ir.locs.loc_of`
needs to turn an AST node into a `Loc` (it owns the byte-column -> character-
column conversion, which only matters on a non-ASCII line). The rest are the
small pure functions that decide a loop's stage and a node's sublabel.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .. import knowledge as K
from ..ir.model import CallSite, ClassIR, LoopIR, ModuleIR
from .graph import Evidence
from .stages import name_stage, vote_stage

__all__ = ["ParsedView", "parsed_view", "within_loop", "loop_is_eval", "loop_stage",
           "loop_backward",
           "clip_literal", "class_sublabel", "op_sublabel",
           "KWARG_ABBREV", "MAX_SUBLABEL_KWARGS"]

KWARG_ABBREV = {"batch_size": "bs", "num_workers": "workers", "learning_rate": "lr",
                "weight_decay": "wd", "random_state": "seed", "n_estimators": "trees"}
MAX_SUBLABEL_KWARGS = 3


class ParsedView:
    """Minimal ParsedFile-compatible view over a ModuleIR (for loc building)."""

    def __init__(self, module: ModuleIR):
        self.relpath = module.relpath
        self.abspath = module.abspath
        self.lines = module.lines
        self._ascii: Dict[int, bool] = {}

    def line_text(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1]
        return ""

    def char_col(self, line: int, col: int) -> int:
        text = self.line_text(line)
        if not text or col <= 0:
            return max(0, col)
        if text.isascii():
            return col
        raw = text.encode("utf-8", "replace")
        return len(raw[:col].decode("utf-8", "ignore"))

    def snippet(self, line: int) -> Optional[str]:
        text = self.line_text(line).rstrip()
        if not text or len(text) > 200:
            return None
        return text


def parsed_view(module: ModuleIR) -> ParsedView:
    view = getattr(module, "_view", None)
    if view is None:
        view = ParsedView(module)
        setattr(module, "_view", view)
    return view


def within_loop(loop: Optional[LoopIR], outer: LoopIR) -> bool:
    while loop is not None:
        if loop is outer:
            return True
        loop = loop.parent_loop
    return False


#: Roles whose presence in a batch loop means the model is being *run*.
_FORWARD_ROLES = ("FORWARD", "PREDICT", "KERAS_EVAL", "HF_EVAL")
#: Roles whose presence means the model is being *measured*.
_MEASURE_ROLES = ("METRIC", "SCORE_METRIC", "ARGMAX", "TO_NUMPY", "CV")
#: Roles that make a loop a training loop whatever else it contains.
_TRAINING_ROLES = ("BACKWARD", "OPT_STEP", "ZERO_GRAD", "SCALE")


def loop_is_eval(loop: LoopIR) -> bool:
    """Is this batch loop an evaluation region?

    NLP-01. This used to be exactly two signals - `inside_no_grad`, or the
    enclosing function's name mapping to the eval stage - and it never asked
    the question MLV301's own detection sketch asks, even though
    `loop_backward` sits a few lines below in this same file. The measured
    consequence on `nlp_token_classification`: `for batch in eval_loader` inside
    `token_accuracy()` was emitted as a `train_loop` in the `train` lane, the
    `eval` stage came back `present: false, nodeCount: 0`, MLV301 and MLV302
    stayed silent in both dataflow modes, and the answer card printed two
    statements the source disproves - "no backward() call" about a file whose
    line 41 is `loss.backward()`, and "No evaluation stage was detected" about
    a function that runs the model and computes a metric. Renaming the function
    `evaluate` flipped all of it, which is a lane recovered from a name rather
    than from the loop's contents.

    The third signal is structural: a batch loop that runs a forward pass, and
    neither back-propagates nor steps an optimizer, is evaluation. It is
    guarded on the forward pass so an empty data loop is never reclassified.
    """
    if loop.inside_no_grad:
        return True
    func = loop.function
    if func is not None and name_stage(func.name) == "eval":
        return True
    return _runs_without_training(loop)


def _runs_without_training(loop: LoopIR) -> bool:
    """A batch loop that runs the model and never updates it."""
    if loop.kind != "batch":
        return False
    runs = False
    for call in loop.module.calls:
        if not within_loop(call.loop, loop):
            continue
        role = K.role_of(call.fqn)
        if role in _TRAINING_ROLES:
            return False
        if role in _FORWARD_ROLES or role in _MEASURE_ROLES:
            runs = True
    if not runs:
        runs = _runs_an_unresolved_model(loop)
    if not runs:
        return False
    # The backward may live one call level down - `train_one_epoch(...)` - and
    # `loop_backward` is the search that already knows how to find it.
    return loop_backward(loop) is None


#: Methods that only ever appear where a prediction is being turned into a
#: number: the measurement half of the fallback below.
_MEASURE_METHODS = ("argmax", "item", "numpy", "topk", "tolist", "softmax",
                    "sigmoid", "detach", "cpu")
#: Methods that mean the loop trains, whatever resolved.
_TRAINING_METHODS = ("backward", "step", "zero_grad", "update", "scale")


def _runs_an_unresolved_model(loop: LoopIR) -> bool:
    """`for batch in eval_loader: logits = model(...)` where `model` is a parameter.

    NLP-01's real shape: the model and the loader both arrive as parameters, so
    neither the FORWARD role nor the loader tag resolves and the role scan
    above finds nothing at all. Two things are still true of the source and are
    checked here, both structural rather than name-based: something that came
    in from outside the function is **called** inside the loop, and its result
    is turned into a number. A loop that merely iterates data does neither.

    Purely syntactic and deliberately narrow: any `.backward()` / `.step()` /
    `.zero_grad()` in the body disqualifies it outright, so a training loop
    whose calls did not resolve is never reclassified as evaluation.
    """
    import ast

    func = loop.function
    if func is None or not func.params:
        return False
    params = set(func.params)
    called = False
    measured = False
    for child in ast.walk(loop.node):
        if not isinstance(child, ast.Call):
            continue
        func_node = child.func
        if isinstance(func_node, ast.Attribute):
            if func_node.attr in _TRAINING_METHODS:
                return False
            if func_node.attr in _MEASURE_METHODS:
                measured = True
            base = func_node.value
            if isinstance(base, ast.Name) and base.id in params:
                called = True
        elif isinstance(func_node, ast.Name) and func_node.id in params:
            called = True
    return called and measured


def loop_backward(loop: LoopIR) -> Optional[str]:
    """`backward()` in the loop body, or in a module-local callee one level down.

    The per-batch work usually lives in a helper (`train_one_epoch(...)`), so
    an epoch loop that only calls it has no direct `backward()` of its own.
    """
    for call in loop.module.calls:
        if not within_loop(call.loop, loop):
            continue
        if K.role_of(call.fqn) == "BACKWARD":
            return "loop body calls backward()"
        callee = call.target_function
        if callee is None:
            continue
        for inner in callee.calls:
            if K.role_of(inner.fqn) == "BACKWARD":
                return "loop body calls %s(), which calls backward()" % callee.name
    return None


def loop_stage(loop: LoopIR, votes: Dict[str, float]):
    evidence = [Evidence("context_confirmed",
                         "%s loop over %s" % (loop.kind, loop.iter_text or "an iterable"),
                         1.0)]
    if loop.evidence:
        evidence.append(Evidence("context_confirmed", loop.evidence[0], 0.9))
    backward = loop_backward(loop)
    if backward:
        evidence.append(Evidence("context_confirmed", backward, 1.0))
        return "train", evidence
    if loop.inside_no_grad or loop_is_eval(loop):
        evidence.append(Evidence("context_confirmed", "loop runs under no_grad / eval", 1.0))
        return "eval", evidence
    winner = vote_stage(votes)
    if loop.kind in ("epoch", "batch"):
        # A confirmed epoch / batch loop *is* training structure. The ops in its
        # body say what happens each iteration - a checkpoint save, a metric -
        # not what the loop is, so they must not outvote its own kind and drag
        # a `train_loop` node into the Save / Deploy lane.
        if winner == "eval":
            return "eval", evidence
        evidence.append(Evidence("context_confirmed",
                                 "a confirmed %s loop is training structure" % loop.kind,
                                 1.0))
        return "train", evidence
    if winner:
        return winner, evidence
    return "data", evidence


def clip_literal(text: Optional[str], width: int = 48) -> Optional[str]:
    if not text:
        return None
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width - 1] + "…"


def class_sublabel(cls: ClassIR) -> Optional[str]:
    if not cls.bases:
        return None
    short = [b.split(".")[-1] for b in cls.bases[:2]]
    return "class · %s" % ", ".join(short)


def op_sublabel(call: CallSite, entry) -> Optional[str]:
    parts: List[str] = []
    if call.var:
        parts.append(call.short_name)
    kwargs = call.kwargs
    for key in sorted(kwargs)[:MAX_SUBLABEL_KWARGS]:
        value = kwargs[key]
        if len(value) > 20:
            value = value[:19] + "…"
        parts.append("%s=%s" % (KWARG_ABBREV.get(key, key), value))
    return " · ".join(parts) if parts else None
