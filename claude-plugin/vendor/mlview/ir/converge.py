"""Fixed-point detection for the IR rounds (PERF-02).

`build_workspace` used to run a literal `range(4)` over five whole-workspace
passes, with a comment conceding *"four rounds reach the fixed point on every
fixture"* - a guess in both directions: on `samples/vision_pipeline` the fourth
round is pure waste, and `analyzer/tests/clean` needs a **fifth** it never got.

`state_digest` fingerprints everything those passes write, so the loop can stop
the round after nothing changed and report honestly when it stopped on the cap
instead. Two properties make it correct:

* it is **content-addressed, never identity-addressed** - `bind_module` clears
  and rebuilds every `ValueRef` on every round, so an `id()`-based digest would
  never repeat and the loop would never converge;
* it is only ever compared **within one process** (round N against round N-1),
  which is what lets it be a plain `hash()` of a tuple - no encoding, no
  hashlib, ~4x cheaper than formatting the same state into strings.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

__all__ = ["MAX_ROUNDS", "state_digest", "summary_key"]

#: The round cap. Four was the old fixed count; the shipped clean corpus needs
#: five, and the cap exists only to stop a pathological oscillation.
MAX_ROUNDS = 8


def _slot_key(slot) -> Any:
    """One `ir.returns.ReturnSlot`, by content (its `class_ir` by qualname)."""
    if slot is None:
        return None
    cls = getattr(slot, "class_ir", None)
    return (slot.fqns, slot.tags, cls.qualname if cls is not None else None,
            getattr(slot, "opaque", None),
            # REC-04: the container slots a `return` carries are state too, so a
            # round that first resolves one must not look like a fixed point.
            tuple(sorted(k for k, _v in getattr(slot, "entries", ()) or ())),
            len(getattr(slot, "elements", ()) or ()))


def summary_key(summary) -> Any:
    """One `ir.returns.ReturnSummary`, by content.

    Public because `ir.summaries` runs the RETURN pass to its own fixed point
    (DATAFLOW-IP) and must fingerprint the same state this module does; two
    digests of the same thing are two chances to disagree.
    """
    if summary is None:
        return None
    return (_slot_key(summary.scalar),
            tuple(_slot_key(s) for s in summary.positions))


_summary_key = summary_key


def _ref_key(name: str, ref) -> Tuple:
    """One `ValueRef`, by content.

    The producer is keyed by its **location**, which survives the rebuild
    `bind_module` does every round; `id(ref.producer)` would not.
    """
    producer = ref.producer
    cls = ref.class_ir
    return (name, ref.name, ref.tags, ref.literal, ref.index, ref.is_config,
            ref.via_fqns, ref.sources,
            # DATAFLOW-IP: the interprocedural chain is part of the state the
            # rounds write, so a round that only moved a chain still counts as
            # movement and the loop does not stop one round early.
            tuple(getattr(ref, "provenance", ()) or ()),
            (producer.loc.file, producer.loc.line, producer.loc.col)
            if producer is not None else None,
            cls.qualname if cls is not None else None)


def _call_key(call) -> Tuple:
    """One `CallSite`, restricted to the fields the IR rounds resolve."""
    receiver = call.receiver
    target = call.target_function
    cls = call.class_ir
    return (call.fqn, call.canonical_fqns, call.import_fqn, call.receiver_name,
            call.method, call.var,
            (receiver.scope.qualname, receiver.name) if receiver is not None else None,
            target.qualname if target is not None else None,
            cls.qualname if cls is not None else None)


def state_digest(workspace) -> int:
    """A hash of everything the binding / resolution / return passes write.

    Two consecutive rounds with the same digest means the round changed
    nothing, and - the passes being deterministic functions of this state -
    every further round would change nothing either. That is the fixed point.
    """
    parts: List[Any] = []
    append = parts.append
    for relpath in sorted(workspace.modules):
        module = workspace.modules[relpath]
        append(relpath)
        for scope in module.scopes:
            append((scope.qualname, scope.dynamic, tuple(scope.reasons)))
            for name in sorted(scope.bindings):
                append(_ref_key(name, scope.bindings[name]))
        for call in module.calls:
            append(_call_key(call))
        for qualname in sorted(module.functions):
            append((qualname, _summary_key(module.functions[qualname].return_summary)))
    return hash(tuple(parts))
