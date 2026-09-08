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


def loop_is_eval(loop: LoopIR) -> bool:
    if loop.inside_no_grad:
        return True
    func = loop.function
    if func is not None and name_stage(func.name) == "eval":
        return True
    return False


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
