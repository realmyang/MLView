"""The confidence model and the absence-rule severity cap.

    confidence = clamp(base_prior x PI(evidence weights)
                       x 0.7  when the enclosing scope is dynamic
                       x 0.4  when an absence rule sees a framework wrapper,
                       0.05, 0.99)

Buckets: `certain >= 0.9`, `likely >= 0.7`, `possible >= 0.5`, else
`speculative` (CONTRACTS section 0 / `contracts/validate_sample.py`).

Absence-rule severity cap: `high` becomes `medium` unless the enclosing scope
resolved statically **and** no framework wrapper was detected.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

from ..core.graph import Evidence, bucket_for, clamp_confidence

__all__ = ["compute_confidence", "cap_severity", "bucket_for", "DYNAMIC_FACTOR",
           "WRAPPER_FACTOR", "normalize_evidence"]

DYNAMIC_FACTOR = 0.7
WRAPPER_FACTOR = 0.4


def normalize_evidence(evidence: Iterable) -> Tuple[Evidence, ...]:
    """Accept `Evidence` objects or `(kind, detail, weight)` tuples."""
    out = []
    for item in evidence or ():
        if isinstance(item, Evidence):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Evidence(item["kind"], item.get("detail", ""),
                                float(item.get("weight", 1.0))))
        elif isinstance(item, (tuple, list)):
            kind = item[0]
            detail = item[1] if len(item) > 1 else ""
            weight = float(item[2]) if len(item) > 2 else 1.0
            out.append(Evidence(kind, detail, weight))
    return tuple(out)


def compute_confidence(base_prior: float, evidence: Sequence[Evidence],
                       dynamic: bool = False, wrapper_gate: bool = False) -> float:
    """The six-factor product, clamped and rounded.

    `evidence` may be `Evidence` objects or the `(kind, detail, weight)`
    tuples rules write.
    """
    value = float(base_prior)
    for item in normalize_evidence(evidence):
        weight = float(item.weight)
        if weight <= 0:
            weight = 0.05
        value *= min(1.0, weight)
    if dynamic:
        value *= DYNAMIC_FACTOR
    if wrapper_gate:
        value *= WRAPPER_FACTOR
    return clamp_confidence(value)


def cap_severity(severity: str, absence: bool, static_scope: bool,
                 wrapper_present: bool) -> str:
    """Absence rules may only reach `high` when fully resolved and unwrapped."""
    if not absence or severity != "high":
        return severity
    if static_scope and not wrapper_present:
        return "high"
    return "medium"
