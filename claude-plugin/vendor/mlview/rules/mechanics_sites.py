"""Six one-liners every `rules/r_mechanics.py` rule spells the same way.

Where to anchor an issue, how to name the call in a message, what the evidence
tuple says, whether a call is inside a block. They are here rather than in
`rules/helpers.py` because each one is this file's *answer*, not a shared
convention - `_static` says what MLV207/208/209/502/803 agree counts as static
evidence, and nothing outside `r_mechanics` should inherit that.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from ..ir.model import CallSite, ValueRef


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
