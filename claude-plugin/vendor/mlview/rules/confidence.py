"""The confidence model and the absence-rule severity cap.

    confidence = clamp(base_prior x PI(evidence weights)
                       x 0.7  when the enclosing scope is dynamic
                       x 0.4  when an absence rule sees a framework wrapper,
                       0.05, 0.99)

NB (CONTRACTS 11.29) adds no fifth term: an order-sensitive rule inside a
notebook that was last run out of order is de-rated through the **evidence**
product, by `NOTEBOOK_ORDER_FACTOR`, so the caveat is one visible factor rather
than an invisible multiplier.

Buckets: `certain >= 0.9`, `likely >= 0.7`, `possible >= 0.5`, else
`speculative` (CONTRACTS section 0 / `contracts/validate_sample.py`).

Absence-rule severity cap: `high` becomes `medium` unless the enclosing scope
resolved statically **and** no framework wrapper was detected.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

from ..core.graph import Evidence, bucket_for, clamp_confidence
from ..ir.provenance import IP_HOP_WEIGHT, chain_text, hop_weight, hops_of

__all__ = ["compute_confidence", "cap_severity", "bucket_for", "DYNAMIC_FACTOR",
           "WRAPPER_FACTOR", "normalize_evidence", "NOTEBOOK_ORDER_FACTOR",
           "ORDER_SENSITIVE_CODES", "notebook_evidence", "IP_HOP_WEIGHT",
           "interprocedural_evidence", "hops_of"]

DYNAMIC_FACTOR = 0.7
WRAPPER_FACTOR = 0.4

#: DATAFLOW-IP re-exports the hop weight and the hop count here so a rule reaches
#: them through the confidence model like every other factor. The constants
#: themselves live with the pass that creates the hops (`ir/provenance.py`).

#: NB. A notebook whose recorded `execution_count` is not monotonic was last
#: run out of order, so *document order is not run order* and every rule that
#: concludes something from "A comes before B" is reading an assumption. The
#: honest response is to de-rate those rules, not to silence them and not to
#: pretend: the code really does contain the pattern, and the reader is the one
#: who knows whether the cells were re-run.
NOTEBOOK_ORDER_FACTOR = 0.75

#: The rules whose whole argument is an ordering. MLV101 (fit before split),
#: MLV203 (`step()` before `backward()`) and MLV209 (clipping in the wrong
#: position) each compare two positions and conclude from the comparison; no
#: other registered rule does.
ORDER_SENSITIVE_CODES = ("MLV101", "MLV203", "MLV209")


def notebook_evidence(nbmap, line: int, code: str):
    """The one evidence factor every finding inside a notebook carries.

    It does two jobs, and it does them in one place so they cannot disagree:

    * **provenance** - `Loc` is frozen and cannot hold a cell index, so the
      `(cell, cellLine)` mapping rides here, in words a host renders as-is.
    * **the execution-order de-rating** - weight `NOTEBOOK_ORDER_FACTOR` for an
      order-sensitive rule in an out-of-order notebook, and weight 1.0 (an
      exact no-op in the confidence product) otherwise, so the same code in a
      `.py` file and in an in-order notebook score identically.

    `nbmap` is duck-typed (`ingest.notebook.NotebookMap`) so the confidence
    model keeps importing nothing from `ingest`.
    """
    where = nbmap.locate(line)
    if where is None:
        place = ("%s (generated module line %d, outside any cell)"
                 % (nbmap.notebook, line))
    else:
        place = "%s cell %d, line %d" % (nbmap.notebook, where[0], where[1])
    derate = (not nbmap.orderOk) and code in ORDER_SENSITIVE_CODES
    weight = NOTEBOOK_ORDER_FACTOR if derate else 1.0
    detail = "%s; %s" % (place, nbmap.order_text())
    if derate:
        detail += ("; %s reads an ordering, so this finding is de-rated x%s"
                   % (code, NOTEBOOK_ORDER_FACTOR))
    return (Evidence(kind="context_confirmed", detail=detail, weight=weight),)


def interprocedural_evidence(ref) -> Tuple[Evidence, ...]:
    """The one evidence factor a cross-object finding carries (DATAFLOW-IP).

    It does the same two jobs `notebook_evidence` does, in one place so they
    cannot disagree:

    * **provenance** - the hop chain, in words, so a reader can audit the claim
      line by line instead of taking *"`self.features` is FEATURES"* on faith;
    * **the de-rating** - `IP_HOP_WEIGHT` once per hop. It is a factor in the
      ordinary confidence product, not a special case, which is what makes
      "never `certain`" arithmetic rather than a promise: MLV101's 0.95 prior
      lands at 0.76 after one hop and 0.61 after two.

    Returns an empty tuple for a value dataflow established locally, so a
    `--dataflow local` run - and every local finding inside an `ip` run - is
    numerically untouched.
    """
    chain = tuple(getattr(ref, "provenance", ()) or ())
    if not chain:
        return ()
    return (Evidence(
        kind="cross_file",
        detail=("the tag arrived interprocedurally: %s; %d hop(s), each de-rated "
                "x%s" % (chain_text(chain), len(chain), IP_HOP_WEIGHT)),
        weight=hop_weight(len(chain))),)


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
