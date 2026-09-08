"""Shared shape for every knowledge-table row.

A knowledge entry maps a **canonical FQN** to what MLView knows about it:

* ``kind``      - the ``NodeKind`` a call to it produces
* ``stage``     - the ``StageId`` it votes for
* ``framework`` - the ``Framework`` enum value
* ``role``      - the analyzer-internal role (``FIT``, ``OPT_STEP``, ...)
* ``tags``      - ``ValueTag``s carried by the value it produces
* ``family``    - receiver family for method resolution (``optimizer``,
  ``module``, ``tensor``, ``estimator``, ``scheduler``, ``loader``)
* ``weight``    - stage-vote weight (1.0 unless the mapping is weak)

Everything here is plain data: adding a framework is data, not code.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

Entry = Dict[str, Any]


def E(
    kind: str,
    stage: str,
    framework: str,
    role: str | None = None,
    tags: Iterable[str] = (),
    family: str | None = None,
    weight: float = 1.0,
) -> Entry:
    """Build one knowledge row."""
    return {
        "kind": kind,
        "stage": stage,
        "framework": framework,
        "role": role,
        "tags": tuple(tags),
        "family": family,
        "weight": weight,
    }


def expand(prefix: str, names: Iterable[str], entry: Entry) -> Dict[str, Entry]:
    """``expand("torch.optim", ["Adam", "SGD"], E(...))`` -> one row per name."""
    return {"%s.%s" % (prefix, n): dict(entry) for n in names}


EMPTY: Tuple[str, ...] = ()
