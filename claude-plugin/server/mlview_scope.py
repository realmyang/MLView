"""The scope selector grammar at the MCP boundary (CONTRACTS 11.1 / 11.10).

One place decides three things, so the tool docstrings, the error text and the
projection can never disagree:

* **what a `scope` argument may say** — the two catalogue values (`"stages"`,
  `"units"`) that are project-level statements, plus the full section 11.1
  selector grammar (`all`, `unit:`, `stage:`, `file:`, `concern:`, `node:`,
  `symbol:`);
* **what an unusable selector says back** — a ``ValueError`` naming the offending
  spec, the grammar code, and every accepted value, because
  ``mlview_mcp.mlview_graph``'s docstring promises exactly that and a promise the
  server does not keep is a lie the model acts on;
* **how the unit catalogue is spelled** in the three `mlview_graph` formats.

The projection itself is NOT reimplemented here: ``mlview.core.project`` is the
one algorithm (CONTRACTS 11.16, "one projection"), reached through
``mlview.api``.  This module is the adapter, and everything in it is pure — no
filesystem, no network, no MCP SDK.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mlview.api import (
    CONCERNS,
    ScopeError,
    parse_scope as _parse_scope,
    project as _project,
    scope_catalog as _scope_catalog,
)
from mlview.core.project import MAX_DEPTH

#: The eight canonical pipeline stages (CONTRACTS section 1, ``StageId``). Used
#: to tell "scope=stage:nosuch" (a caller mistake, worth an error) apart from
#: "scope=stage:eval on a project with no eval lane" (a real, reportable answer).
STAGE_IDS: Tuple[str, ...] = (
    "config", "data", "preprocess", "model", "objective",
    "train", "eval", "deliver",
)

#: Values that are NOT selectors: they summarise the whole project rather than
#: projecting it, so they never carry the filtered-view note.
CATALOG_SCOPES: Tuple[str, ...] = ("stages", "units")

#: Rows of the ``scope="units"`` catalogue, in the contracted order.
CATALOG_ROW_KEYS: Tuple[str, ...] = (
    "nodeId", "label", "qualname", "file", "line", "nodeCount", "maxSeverity",
)

__all__ = [
    "STAGE_IDS", "CATALOG_SCOPES", "CATALOG_ROW_KEYS", "MAX_DEPTH",
    "accepted_values", "scope_value_error", "clamp_depth", "parse", "project",
    "apply_scope",
    "catalog_rows", "catalog_json", "catalog_text", "catalog_mermaid",
    "catalog_content", "catalog_clipped_note",
    "filtered_view_note",
]


# ------------------------------------------------------------------ the vocabulary
def accepted_values() -> str:
    """Every value `scope` accepts, spelled the way a caller must type it.

    ``mlview_graph``'s docstring contracts an error that "names the accepted
    values", and section 11.10 requires the docstring and the grammar to be
    extended in the same edit — so both read this one function's vocabulary.
    """
    return (
        "'stages' (one row per stage lane — the only project-wide lane summary), "
        "'units' (the catalogue of scopable units: classes, functions and loops), "
        "'all' (the whole graph), "
        "'stage:<id>' (%s), "
        "'unit:<qualname|ClassName|function>', "
        "'file:<path.py>', "
        "'concern:<%s>', "
        "'node:<nodeId>'"
        % (
            ", ".join("stage:%s" % s for s in STAGE_IDS),
            "|".join(sorted(CONCERNS)),
        )
    )


def scope_value_error(spec: str, exc: ScopeError) -> ValueError:
    """Turn a grammar ``ScopeError`` into the sentence the model should read.

    Only ``code``, ``term`` and ``candidates`` are contractual (section 11.1);
    the prose is free, and it is spent on telling the caller what to type next.
    """
    hint = ""
    if exc.code == "unknown_node":
        hint = (
            " — call mlview_analyze first for current node ids, or scope='units' "
            "to list the scopable units"
        )
    elif exc.code == "unknown_file":
        hint = " — the path is workspace-relative with forward slashes"
    elif exc.code == "bad_depth":
        hint = " — depth is 0, 1 or 2"
    candidates = ""
    if exc.candidates:
        candidates = "; candidates: %s" % ", ".join(exc.candidates)
    return ValueError(
        "scope=%r is not valid (%s: %r%s). Accepted values are %s, or omit it "
        "for the whole graph.%s"
        % (spec, exc.code, exc.term, candidates, accepted_values(), hint)
    )


def clamp_depth(depth: Optional[Any]) -> Tuple[Optional[int], Optional[str]]:
    """``(depth, note)`` — depth held inside 0..2, saying so when it moved.

    Section 11.10 bounds `depth` to 0..2. A value outside is reported rather than
    applied silently: the note travels into the payload, so a caller that asked
    for three hops can see it got two instead of believing it got three.
    """
    if depth is None or depth == "":
        return None, None
    try:
        value = int(depth)
    except (TypeError, ValueError):
        return None, "depth=%r is not an integer; the per-kind default was used" % (depth,)
    if value < 0:
        return 0, "depth=%d is below 0; 0 was used" % value
    if value > MAX_DEPTH:
        return MAX_DEPTH, "depth=%d is above the maximum %d; %d was used" % (
            value, MAX_DEPTH, MAX_DEPTH,
        )
    return value, None


# -------------------------------------------------------------------- the grammar
def parse(spec: str, depth: Optional[int] = None):
    """``mlview.api.parse_scope`` with the boundary's error text."""
    try:
        return _parse_scope(spec, depth)
    except ScopeError as exc:
        raise scope_value_error(spec, exc) from exc


def project(graph: Dict[str, Any], scope) -> Dict[str, Any]:
    """``mlview.api.project`` with the boundary's error text.

    ``project`` raises for a selector that only the *document* can refute — an
    unknown node id, an unknown file — which parsing cannot catch.
    """
    try:
        return _project(graph, scope)
    except ScopeError as exc:
        raise scope_value_error(scope.spec, exc) from exc


def apply_scope(
    graph: Dict[str, Any], spec: Optional[str], depth: Optional[Any] = None
) -> Tuple[Optional[str], Dict[str, Any], List[str], Optional[int]]:
    """``(normalized spec | None, view, notes, depth)`` for one tool call.

    The single place `mlview_analyze`, `mlview_issues` and `mlview_open_diagram`
    turn their two optional arguments into a projection. ``None`` comes back as
    the spec for both "no scope" and ``"all"`` — the grammar's identity — so the
    payload gains neither a `scope` key nor a filtered-view note, and its bytes
    are what they were before this feature existed.

    The **full** graph is what goes in; the caller keeps it for `graphPath`,
    `render_html` and the diagnostics summary, so the analysis cache is never
    keyed on a scope (CONTRACTS 11.10) and a model can always widen for free.
    """
    text = (spec or "").strip()
    depth, note = clamp_depth(depth)
    notes: List[str] = [note] if note else []
    if not text:
        return None, graph, notes, depth
    scope = parse(text, depth)
    if scope.is_all:
        return None, graph, notes, depth
    view = project(graph, scope)
    if (view.get("view") or {}).get("empty"):
        notes.append(
            "%s matched no nodes; the whole graph has %d — widen the selector, or "
            "call mlview_graph with scope='units' to see what is scopable"
            % (scope.spec, len(graph.get("nodes") or []))
        )
    return scope.spec, view, notes, scope.depth


def filtered_view_note(spec: str) -> str:
    """The sentence every projected result carries (CONTRACTS 11.10)."""
    return (
        "this is a filtered view of %s; counts describe the scope, not the whole "
        "project — call scope='stages' for the project-wide lanes" % spec
    )


# ------------------------------------------------------------------ the catalogue
def catalog_rows(graph: Dict[str, Any], limit: int = 0) -> List[Dict[str, Any]]:
    """The ``scope="units"`` rows, in the contracted key order and sort order.

    ``mlview.api.scope_catalog`` already sorts by ``(-nodeCount, file, line,
    qualname)`` and returns a superset of these keys; this keeps only the seven
    section 11.10 names so the rows are small enough for a 4 KB payload.
    """
    rows = _scope_catalog(graph, limit=limit)
    return [{key: row.get(key) for key in CATALOG_ROW_KEYS} for row in rows]


def catalog_json(rows: Sequence[Dict[str, Any]]) -> str:
    return json.dumps(list(rows), ensure_ascii=False)


def _spec_of(row: Dict[str, Any]) -> str:
    return "unit:%s" % (row.get("qualname") or row.get("nodeId") or "?")


def catalog_text(rows: Sequence[Dict[str, Any]]) -> str:
    lines = ["%5s  %-6s %-44s %s" % ("NODES", "MAX", "SCOPE", "LOCATION")]
    for row in rows:
        lines.append(
            "%5d  %-6s %-44s %s:%s"
            % (
                int(row.get("nodeCount") or 0),
                row.get("maxSeverity") or "-",
                _spec_of(row),
                row.get("file") or "?",
                row.get("line") or "?",
            )
        )
    if not rows:
        lines.append("(no scopable units — the graph has no classes, functions or loops)")
    return "\n".join(lines)


def catalog_mermaid(rows: Sequence[Dict[str, Any]]) -> str:
    """One box per scopable unit. Deliberately edge-free: this is a menu, not a
    picture of the pipeline — the picture is what `scope:"unit:<name>"` returns."""
    lines = ["flowchart TB", "  %% scopable units — pass one as scope"]
    for index, row in enumerate(rows):
        lines.append(
            '  unit_%d["%s<br/>%d nodes%s"]'
            % (
                index,
                _spec_of(row),
                int(row.get("nodeCount") or 0),
                "" if not row.get("maxSeverity") else " · max %s" % row["maxSeverity"],
            )
        )
    if not rows:
        lines.append('  none["no scopable units"]')
    return "\n".join(lines)


def catalog_content(
    rows: Sequence[Dict[str, Any]], fmt: str, budget: int
) -> Tuple[str, int, int]:
    """``(text, kept, total)`` — the catalogue rendered in ``fmt`` within ``budget``.

    Rows arrive sorted `(-nodeCount, file, line, qualname)`, so shedding from the
    end drops the smallest units first and the menu stays useful. Both counts come
    back because the shed rows are exactly the leaf classes and short functions a
    user is most likely to name: `catalog_clipped_note` turns them into the
    sentence that keeps a clipped menu from reading as a complete one.
    """
    render = {"json": catalog_json, "text": catalog_text, "mermaid": catalog_mermaid}[fmt]
    kept = list(rows)
    text = render(kept)
    while kept and len(text.encode("utf-8")) > budget:
        kept.pop()
        text = render(kept)
    return text, len(kept), len(rows)


def catalog_clipped_note(kept: int, total: int) -> str:
    """What a CLIPPED catalogue must say about itself.

    `truncated: true` alone is not enough here: this is the documented discovery
    surface ("call scope='units' first and pick the row"), so a model that reads a
    shed row as an absent unit reports "no such unit" for a name `unit:<x>`
    resolves perfectly. It names both counts and points at `--list-scopes`, which
    has no byte budget — not at `graphPath`, which holds the graph, not the menu.
    """
    return (
        "this menu is INCOMPLETE: showing %d of %d scopable units (the smallest "
        "were dropped to fit) — run `python -m mlview analyze <path> "
        "--list-scopes` for the whole catalogue, and treat a name you cannot see "
        "here as untested, not as absent" % (kept, total)
    )
