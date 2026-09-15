"""The scope selector grammar (CONTRACTS 11.1).

One string with exactly one `kind` and one `target`, split on the **first**
colon only - a node id contains one (`node:n:55662bceebd0`). `depth` always
travels as its own parameter, never packed into the spec.

Split out of `project.py` so each module carries one section of the contract:
this file is 11.1 (parse and normalize), `project.py` is 11.2 (resolve and
project). `project.py` re-exports every name here, so
`from mlview.core.project import parse_scope` - the spelling CONTRACTS 11.6
names - keeps working, and so does `mlview.api`.

Named `selectors.py`, not `scope.py`: `mlview/ir/scopes.py` already owns the
word "scope" for lexical scopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from ..knowledge import STAGE_IDS

__all__ = [
    "CONCERNS", "CONCERN_ALIASES", "CONCERN_LABELS", "SCOPE_KINDS",
    "SCOPE_SPELLINGS", "DEFAULT_DEPTH", "MAX_DEPTH", "ScopeError", "Scope",
    "parse_scope", "ascii_lower",
]

#: The four concern presets. They **partition** all eight stages: no stage is
#: unreachable and no stage is claimed by two concerns (CONTRACTS 11.1).
CONCERNS: Dict[str, Tuple[str, ...]] = {
    "config": ("config",),
    "data": ("data", "preprocess"),
    "optimization": ("model", "objective", "train"),
    "evaluation": ("eval", "deliver"),
}

#: Alias -> canonical concern. Resolved **before** validation, so
#: `concern:inference` and `concern:evaluation` are byte-identical documents.
CONCERN_ALIASES: Dict[str, str] = {
    "setup": "config",
    "preprocessing": "data",
    "dataset": "data",
    "training": "optimization",
    "inference": "evaluation",
    "eval": "evaluation",
}

#: Frozen breadcrumb names for the four concerns (`view.label`).
CONCERN_LABELS: Dict[str, str] = {
    "config": "Configuration",
    "data": "Data & preprocessing",
    "optimization": "Model & optimization",
    "evaluation": "Evaluation & inference",
}

#: MLV-P12 (CONTRACTS 11.47 B2) appends `pipeline`. Additive: every
#: previously legal selector still parses to exactly what it did, and the
#: only visible change is one more entry in the `bad_selector` candidates.
SCOPE_KINDS: Tuple[str, ...] = ("unit", "stage", "file", "concern", "node",
                               "pipeline")
#: Everything a user may type in the kind slot (`symbol` normalizes to `unit`).
SCOPE_SPELLINGS: Tuple[str, ...] = tuple(sorted(SCOPE_KINDS + ("symbol", "all")))

#: Per-kind default boundary depth. A unit or a node is a *point* and its
#: interface is most of what you came to see; a stage, file or concern is
#: already a region, and a ring around a whole lane is mostly noise.
DEFAULT_DEPTH: Dict[str, int] = {
    "unit": 1, "node": 1, "stage": 0, "file": 0, "concern": 0, "all": 0,
    # A pipeline is already a whole region, and 11.47 A2 puts containment in
    # the relation, so a ring around it is mostly noise.
    "pipeline": 0,
}
MAX_DEPTH = 2

_SEVERITIES = ("high", "medium", "low")
_ZERO_COUNTS = {"low": 0, "medium": 0, "high": 0}
_MAX_CANDIDATES = 10
_MAX_PRUNE_ROUNDS = 8


# --------------------------------------------------------------- errors
class ScopeError(ValueError):
    """A selector the grammar rejects (CONTRACTS 11.1).

    Only `code`, `term` and `candidates` are contractual; the message prose is
    free and may differ between Python and TypeScript.
    """

    def __init__(self, code: str, term: str, candidates: Iterable[str] = (),
                 message: Optional[str] = None):
        self.code = code
        self.term = term
        self.candidates: Tuple[str, ...] = tuple(
            sorted({str(c) for c in candidates}))[:_MAX_CANDIDATES]
        super().__init__(message or _default_message(code, term, self.candidates))


def _near_miss(term: str, candidates: Sequence[str]) -> Optional[str]:
    """The candidate that differs from `term` only in ASCII case, if any.

    `stage:` and `concern:` targets are matched exactly (CONTRACTS 11.1
    lowercases the *kind* only), while `unit:` and `file:` fold case during
    resolution - so `stage:TRAIN` is a hard error where `unit:TRAIN` is not.
    Folding the target here would change the *grammar*, which is a two-port
    change (11.16, `webview/src/scope/selector.ts`); naming the canonical
    spelling in the message is free, because only the code, the term and the
    candidate list are contractual - the prose is not.
    """
    want = ascii_lower(term)
    for candidate in candidates:
        if candidate != term and ascii_lower(candidate) == want:
            return candidate
    return None


def _default_message(code: str, term: str, candidates: Sequence[str]) -> str:
    prose = {
        "bad_selector": "not a scope selector: %r" % term,
        "unknown_stage": "unknown stage %r" % term,
        "unknown_concern": "unknown concern %r" % term,
        "unknown_node": "no node %r in this graph" % term,
        "unknown_file": "no analyzed file matches %r" % term,
        "unknown_pipeline": "no entrypoint %r in this workspace" % term,
        "bad_depth": "depth must be an integer 0..2, got %r" % term,
    }.get(code, "%s: %r" % (code, term))
    kind = {"unknown_stage": "stage", "unknown_concern": "concern"}.get(code)
    near = _near_miss(term, candidates) if kind else None
    if near is None and code == "unknown_concern":
        # `concern:Inference` folds to an *alias*, which is not in the
        # candidate list (only the four canonical names are contractual).
        folded = ascii_lower(term)
        folded = CONCERN_ALIASES.get(folded, folded)
        near = folded if folded in CONCERNS and folded != term else None
    if near:
        prose += (" - did you mean %s:%s? (%s targets are matched exactly, "
                  "unlike unit: and file:)" % (kind, near, kind))
    if candidates:
        prose += " (try: %s)" % ", ".join(candidates)
    return prose


# --------------------------------------------------------------- grammar
@dataclass(frozen=True)
class Scope:
    """One parsed selector. `spec` is the normalized `<kind>:<target>`."""

    kind: str
    target: str
    depth: int
    spec: str
    #: ROB-13. The selector exactly as the user wrote it, before `symbol:` was
    #: folded into `unit:`. Messages that exist to help somebody find the right
    #: selector must quote the one they typed; `spec` stays normalized, because
    #: that is what hosts read back out of `view.scope`.
    spelling: str = field(default="", compare=False, repr=False)

    @property
    def is_all(self) -> bool:
        return self.kind == "all"

    @property
    def as_typed(self) -> str:
        return self.spelling or self.spec


def ascii_lower(text: str) -> str:
    """ASCII-only case folding - `str.lower()` and `toLowerCase()` disagree
    outside ASCII, and the two ports must not."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


def _parse_depth(depth: Any, kind: str) -> int:
    if depth is None or (isinstance(depth, str) and not depth.strip()):
        return DEFAULT_DEPTH.get(kind, 0)   # not given: the per-kind default
    value = depth
    if isinstance(value, bool):
        raise ScopeError("bad_depth", str(depth), ("0", "1", "2"))
    if isinstance(value, str):
        text = value.strip()
        try:
            value = int(text, 10)
        except ValueError:
            raise ScopeError("bad_depth", text, ("0", "1", "2"))
    if not isinstance(value, int):
        raise ScopeError("bad_depth", str(depth), ("0", "1", "2"))
    if value < 0 or value > MAX_DEPTH:
        raise ScopeError("bad_depth", str(value), ("0", "1", "2"))
    return value


def parse_scope(spec: Optional[str], depth: Optional[Any] = None) -> Scope:
    """Parse one selector string (CONTRACTS 11.1). Raises `ScopeError`.

    Split on the **first** colon only - a node id contains one
    (`node:n:55662bceebd0`). An empty or missing spec means `all`.

    `bad_selector` is spent on exactly what 11.1 says it is: no `:`, or an
    unknown `kind`. A **known** kind with an empty target keeps its own error
    code, because the user has already told us the kind and only forgot the
    target: `stage:` and `concern:` answer here with their own candidate list,
    `node:` and `file:` are handed to the resolver (only it knows this graph's
    node ids and analyzed files), and `unit:` - the one kind whose
    unresolvable target is an empty *scope* rather than an error - is rejected
    with `term: ""`.
    """
    text = (spec or "").strip()
    if not text or ascii_lower(text) == "all":
        return Scope("all", "", _parse_depth(depth, "all"), "all", text or "all")
    if ":" not in text:
        raise ScopeError("bad_selector", text, SCOPE_SPELLINGS)
    raw_kind, target = text.split(":", 1)
    kind = ascii_lower(raw_kind.strip())
    target = target.strip()
    if kind == "symbol":                      # one line, because "symbol" is
        kind = "unit"                         # the word everyone reaches for
    if kind not in SCOPE_KINDS:
        raise ScopeError("bad_selector", raw_kind.strip(), SCOPE_SPELLINGS)
    if not target and kind == "unit":
        # CONTRACTS 11.1 spends `bad_selector` on "no `:`, or an unknown
        # `kind`", and every other kind has a code of its own for a target it
        # cannot resolve. `unit:` is the one kind whose unresolvable target is
        # an *empty scope* rather than an error - which would turn a typo into
        # a silent zero-node document - so the empty target is rejected here,
        # with `term: ""` so the message points at the missing half.
        raise ScopeError(
            "bad_selector", "", SCOPE_SPELLINGS,
            "%s: needs a target - a qualname, an FQN, a bare name or a node id"
            % raw_kind.strip())
    if kind in ("file", "pipeline"):
        target = target.replace("\\", "/")
    if kind == "concern":
        target = CONCERN_ALIASES.get(target, target)
        if target not in CONCERNS:
            raise ScopeError("unknown_concern", target, CONCERNS)
    if kind == "stage" and target not in STAGE_IDS:
        raise ScopeError("unknown_stage", target, STAGE_IDS)
    # `node:`, `file:` and `pipeline:` with an empty target fall through to the
    # resolver on purpose: only it can name the candidates CONTRACTS 11.1
    # requires (the graph's node ids, the analyzed `loc.file` values, this
    # workspace's entrypoints), so it raises `unknown_node` / `unknown_file` /
    # `unknown_pipeline` with `term: ""` and a real candidate list.
    return Scope(kind, target, _parse_depth(depth, kind), "%s:%s" % (kind, target),
                 text)
