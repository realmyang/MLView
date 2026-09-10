"""Where an interprocedural tag came from (DATAFLOW-IP).

`local` dataflow answers *"what is this value?"* inside one scope and stops at
the first `def`. `ip` dataflow carries a tag across the object boundary, and
the moment it does, the analyzer owes the reader two things it never owed
before:

* **the chain** - a finding that says *"`self.features` is FEATURES"* is
  useless if the reader cannot see that the tag entered through
  `SeriesExperiment(features, labels)` at `run.py:19`. Every hop is recorded on
  the `ValueRef` and rendered into one `cross_file` evidence entry and one
  `RelatedLoc` per hop, so the argument is auditable line by line;
* **the doubt** - each hop is a place the analysis could be wrong (a subclass
  overrides `setup`, a second construction site was never seen, a decorator
  rewrote the call). `IP_HOP_WEIGHT` is that doubt, stated as a number and
  multiplied into the confidence product once per hop, which is what keeps a
  cross-object finding at `likely` or `possible` and never at `certain`.

The cap is `DEFAULT_MAX_HOPS`. A chain that outruns it is **not** propagated
and **is** reported (`ir.summaries` collects the notes, the pipeline emits them
as `truncated` diagnostics): "I stopped following this" is a fact the reader
needs, and the failure mode the whole product is trying not to have is silence
that looks like a clean read.

This module imports nothing from `mlview` at all - `ir.model` imports *it*, so
the dependency runs one way and `Hop` can hold a `Loc` without a cycle. Two
places build hops: `ir.summaries` (the three summaries) and
`rules.helpers._projection` (the one-step subscript read); everything else only
reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

__all__ = ["Hop", "DEFAULT_MAX_HOPS", "IP_HOP_WEIGHT", "HOP_KINDS", "HOP_ROLES",
           "extend", "chain_text", "hops_of", "merge_chains", "hop_weight"]

#: How many interprocedural hops a tag may take. The roadmap's condition of
#: approval names a cap and this is it; three is deep enough for
#: `caller -> ctor -> attribute -> sibling method` and shallow enough that the
#: confidence product still lands above `speculative` for a two-hop chain.
DEFAULT_MAX_HOPS = 3

#: The interprocedural evidence weight, applied **once per hop**. Stated as a
#: constant rather than buried in a rule so that "how much does one hop cost"
#: has exactly one answer:
#:
#:     MLV101 base 0.95   0 hops -> 0.950 certain
#:                        1 hop  -> 0.760 likely
#:                        2 hops -> 0.608 possible
#:                        3 hops -> 0.486 speculative
IP_HOP_WEIGHT = 0.8

#: The four shapes a hop can have. `constructor`, `return` and `method-arg` are
#: the three summaries the roadmap names; `projection` is the one-step read of
#: a tracked value through a subscript (`frame[FEATURES]`), which is how the
#: tag reaches a fit site written the way a DataModule writes it.
HOP_KINDS = ("constructor", "return", "method-arg", "projection")


#: The `RelatedRole` (a FROZEN schema enum, CONTRACTS 11.1) each hop kind is
#: rendered under, so a reader can jump to the line the tag came through. No
#: new role is invented: `construction` and `call_site` already mean exactly
#: this, and a frozen enum is frozen.
HOP_ROLES = {
    "constructor": "construction",
    "method-arg": "call_site",
    "return": "call_site",
    "projection": "definition",
}


@dataclass(frozen=True)
class Hop:
    """One step a tag took to arrive where a rule found it.

    `loc` is an `ir.model.Loc` and is deliberately untyped here: `model`
    imports this module, so this module imports nothing back. It carries the
    whole location rather than a file/line pair because a hop becomes a
    `RelatedLoc`, and half a location cannot.
    """

    kind: str
    detail: str            # "SeriesExperiment(features, labels)"
    loc: object = None     # ir.model.Loc

    @property
    def file(self) -> str:
        return getattr(self.loc, "file", "") or ""

    @property
    def line(self) -> int:
        return int(getattr(self.loc, "line", 0) or 0)

    @property
    def role(self) -> str:
        return HOP_ROLES.get(self.kind, "call_site")

    def text(self) -> str:
        return "%s through %s at %s:%d" % (self.kind, self.detail, self.file, self.line)


def hops_of(ref) -> int:
    """How many interprocedural hops this value's tags took (0 = local)."""
    return len(getattr(ref, "provenance", ()) or ())


def hop_weight(count: int) -> float:
    """`IP_HOP_WEIGHT` compounded over `count` hops (1.0 for a local value)."""
    weight = 1.0
    for _ in range(max(0, int(count))):
        weight *= IP_HOP_WEIGHT
    return weight


def extend(chain: Sequence[Hop], hop: Hop,
           max_hops: int = DEFAULT_MAX_HOPS) -> Optional[Tuple[Hop, ...]]:
    """`chain + hop`, or **None** when that would outrun the cap.

    None is the caller's signal to stop propagating *and* to record a note: a
    silently truncated chain is indistinguishable from a value that never had
    a tag, which is the exact confusion this project refuses to ship.
    """
    if len(chain) + 1 > max_hops:
        return None
    return tuple(chain) + (hop,)


def merge_chains(chains: Iterable[Sequence[Hop]], fallback: Hop
                 ) -> Tuple[Hop, ...]:
    """The chain to record when several call sites agreed on a tag set.

    One site: its own chain, which is the useful case and the one a reader can
    follow. Several: a single `fallback` hop, because *"it arrived through one
    of these four call sites"* is not a chain and pretending otherwise would
    put a line number on a claim the analysis did not make.
    """
    kept = [tuple(c) for c in chains]
    if len(kept) == 1:
        return kept[0]
    return (fallback,)


def chain_text(chain: Sequence[Hop]) -> str:
    """The hop chain as one sentence, oldest hop first."""
    if not chain:
        return "no interprocedural hop"
    return " -> ".join(hop.text() for hop in chain)
