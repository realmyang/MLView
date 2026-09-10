"""VIEW-08 — rendering a diff overlay (CONTRACTS 11.38).

`core/diff.py` decides *what changed*; this module decides *what a person is
shown first*. The order is deliberate and is the whole design of the surface:

1. **The two documents, named.** A diff of the wrong pair is the easiest
   mistake to make and the hardest to notice, so both roots, both file counts
   and both totals are printed before any verdict.
2. **The headline.** `+26 nodes · −16 nodes · 0 new findings · 15 fixed` — the
   same sentence the viewer's banner shows, produced once, in the analyzer.
3. **Findings before structure.** New findings first, then fixed: a reviewer
   cares whether the change introduced a defect long before they care that it
   added eleven nodes. Structure follows underneath.
4. **Notes last and never omitted.** If either analysis could not see the whole
   workspace, the counts above are not a statement about the code, and this is
   the block that says so. Everything else is capped at ten rows; the notes
   are not capped, because a truncated caveat is a broken caveat.

The renderer writes nothing itself: it returns text, and the CLI is the only
thing that touches a stream.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from ..core.graph import SEVERITY_RANK

__all__ = ["render_summary", "headline", "ROW_LIMIT"]

#: How many rows of any one list the summary prints before eliding. The elision
#: always names the number it did not print - a list that quietly stops is the
#: same failure as an analyzer that quietly stops.
ROW_LIMIT = 10


def headline(overlay: Mapping[str, Any]) -> str:
    return str((overlay.get("summary") or {}).get("headline") or "")


def _short(root: Any) -> str:
    text = str(root or "?").replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1] or text


def _side_line(label: str, side: Mapping[str, Any]) -> str:
    parts = []
    if side.get("filesAnalyzed") is not None:
        parts.append("%s file(s)" % side["filesAnalyzed"])
    parts.append("%d nodes" % int(side.get("nodes") or 0))
    parts.append("%d edges" % int(side.get("edges") or 0))
    parts.append("%d issues" % int(side.get("issues") or 0))
    if side.get("truncated"):
        parts.append("TRUNCATED")
    if side.get("view"):
        parts.append("view %s" % side["view"])
    return "  %-5s %-34s %s" % (label, _short(side.get("root")), " · ".join(parts))


def _loc_text(row: Mapping[str, Any]) -> str:
    loc = row.get("loc") or {}
    if not loc.get("file"):
        return ""
    line = loc.get("line")
    return "%s:%s" % (loc["file"], line) if line else str(loc["file"])


def _issue_rows(overlay: Mapping[str, Any], status: str) -> List[Dict[str, Any]]:
    rows = [r for r in overlay.get("issues") or () if r.get("status") == status]
    rows.sort(key=lambda r: (-SEVERITY_RANK.get(str(r.get("severity")), 0),
                             str(r.get("code")), _loc_text(r)))
    return rows


def _node_rows(overlay: Mapping[str, Any], status: str) -> List[Dict[str, Any]]:
    rows = [r for r in overlay.get("nodes") or () if r.get("status") == status]
    rows.sort(key=lambda r: (str(r.get("stage")), _loc_text(r), str(r.get("label"))))
    return rows


def _elide(lines: List[str], rows: Sequence[Any], limit: int, what: str) -> None:
    if len(rows) > limit:
        lines.append("    … and %d more %s (use --json to see them all)"
                     % (len(rows) - limit, what))


def _issue_block(lines: List[str], title: str, rows: Sequence[Mapping[str, Any]],
                 empty: str) -> None:
    lines.append("")
    lines.append("%s (%d)" % (title, len(rows)))
    if not rows:
        lines.append("    %s" % empty)
        return
    for row in rows[:ROW_LIMIT]:
        marker = {"new": "+", "fixed": "-", "persisting": "="}.get(
            str(row.get("status")), " ")
        lines.append("  %s %-6s %-7s %-46s %s"
                     % (marker, row.get("severity", ""), row.get("code", ""),
                        _clip(str(row.get("title") or ""), 46), _loc_text(row)))
    _elide(lines, rows, ROW_LIMIT, "finding(s)")


def _node_block(lines: List[str], title: str, marker: str,
                rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    lines.append("")
    lines.append("%s (%d)" % (title, len(rows)))
    for row in rows[:ROW_LIMIT]:
        detail = ""
        if row.get("changed"):
            detail = "  [%s]" % ", ".join(row["changed"])
        lines.append("  %s %-9s %-40s %s%s"
                     % (marker, row.get("stage", ""),
                        _clip(str(row.get("label") or ""), 40), _loc_text(row), detail))
    _elide(lines, rows, ROW_LIMIT, "node(s)")


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def render_summary(overlay: Mapping[str, Any]) -> str:
    """The `--format summary` rendering of an overlay document."""
    summary = overlay.get("summary") or {}
    nodes = summary.get("nodes") or {}
    edges = summary.get("edges") or {}
    issues = summary.get("issues") or {}
    lines: List[str] = ["mlview diff",
                        _side_line("base", overlay.get("base") or {}),
                        _side_line("head", overlay.get("head") or {}),
                        "",
                        headline(overlay),
                        "",
                        "  nodes     +%d added · -%d removed · %d changed · %d unchanged"
                        % (nodes.get("added", 0), nodes.get("removed", 0),
                           nodes.get("changed", 0), nodes.get("unchanged", 0)),
                        "  edges     +%d added · -%d removed · %d changed · %d unchanged"
                        % (edges.get("added", 0), edges.get("removed", 0),
                           edges.get("changed", 0), edges.get("unchanged", 0)),
                        "  findings  %d new · %d fixed · %d persisting"
                        % (issues.get("new", 0), issues.get("fixed", 0),
                           issues.get("persisting", 0))]
    _issue_block(lines, "new findings", _issue_rows(overlay, "new"),
                 "none - this change introduced no finding MLView can see")
    _issue_block(lines, "fixed findings", _issue_rows(overlay, "fixed"), "none")
    persisting = _issue_rows(overlay, "persisting")
    if persisting:
        _issue_block(lines, "still present", persisting, "none")
    _node_block(lines, "added nodes", "+", _node_rows(overlay, "added"))
    _node_block(lines, "removed nodes", "-", _node_rows(overlay, "removed"))
    _node_block(lines, "changed nodes", "~", _node_rows(overlay, "changed"))

    notes = list(overlay.get("notes") or ())
    lines.append("")
    lines.append("Notes (%d)" % len(notes))
    if not notes:
        lines.append("  both analyses read their whole workspace, so a removed "
                     "node is a removed node.")
    for note in notes:
        lines.append("  - %s" % note.get("message", ""))
    return "\n".join(lines) + "\n"
