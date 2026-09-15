"""Scope payloads for the CLI: the `--list-scopes` catalogue and the stderr
rendering of a `ScopeError` (CONTRACTS 11.5).

Lives beside the other emitters so `cli.py` stays a thin dispatcher. Only the
error **code**, the offending **term** and the sorted, <=10-entry candidate
list are contractual; the prose here is free.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["render_catalog_text", "render_catalog_json", "error_text",
           "empty_note", "fail_on_suffix", "issues_scope_suffix"]

_MARK = {"high": "[!!]", "medium": "[!]", "low": "[i]"}


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def render_catalog_text(rows: Sequence[Dict[str, Any]]) -> str:
    """The human form of `--list-scopes`.

    The count column is the row's **subtree** - the unit plus its `parent`
    descendants, i.e. what `--scope <SPEC> --depth 0` draws. A `unit:` scope
    defaults to depth 1 (CONTRACTS 11.1), so the view a user gets by
    activating a row is usually *larger* than this number. The column is named
    `SUBTREE`, not `NODES`, so it cannot be read as a prediction of the drawn
    card count, and the footer says so in words.
    """
    pipelines = [r for r in rows if r.get("kind") == "pipeline"]
    head = "%d scopable unit(s)" % (len(rows) - len(pipelines))
    if pipelines:
        head = "%d pipeline(s) + %s" % (len(pipelines), head)
    lines: List[str] = [head]
    header = "  %-38s %-18s %7s  %-15s %s" % ("SCOPE", "LABEL", "SUBTREE", "ISSUES",
                                              "LOCATION")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for row in rows:
        counts = row.get("issueCounts") or {}
        marks = " ".join("%s%d" % (_MARK[sev], counts.get(sev, 0))
                         for sev in ("high", "medium", "low") if counts.get(sev))
        lines.append("  %-38s %-18s %7d  %-15s %s:%s"
                     % (_clip(row.get("spec", ""), 38), _clip(row.get("label", ""), 18),
                        row.get("nodeCount", 0), marks or "-",
                        row.get("file", "?"), row.get("line", "?")))
    if not rows:
        lines.append("  none found")
    lines.append("")
    lines.append("SUBTREE = the unit plus its descendants (what --depth 0 draws); "
                 "a unit: scope defaults to --depth 1, so the view is usually larger.")
    lines.append("This is a menu, not the whole vocabulary: a call site such as "
                 "unit:train_test_split resolves too but is never listed, because "
                 "the catalogue holds only units and their parents.")
    lines.append("Also legal: unit:<qualname|name|node id>, stage:<one of the eight>, "
                 "file:<path.py>, concern:<config|data|optimization|evaluation>, "
                 "node:<n:id>, pipeline:<entrypoint>, all.")
    if pipelines:
        lines.append("A pipeline: row counts only the nodes NO other entrypoint "
                     "reaches; nodes two pipelines share are drawn as context.")
    lines.append("Use one with:  python -m mlview analyze <path> --scope <SCOPE>")
    return "\n".join(lines) + "\n"


def render_catalog_json(rows: Sequence[Dict[str, Any]]) -> str:
    return json.dumps(list(rows), indent=2, ensure_ascii=False) + "\n"


def error_text(exc) -> str:
    """The stderr block for a `ScopeError`: code, term, candidates."""
    lines = ["mlview: %s: %s" % (exc.code, exc)]
    lines.append("mlview:   term: %s" % exc.term)
    if exc.candidates:
        lines.append("mlview:   candidates: %s" % ", ".join(exc.candidates))
    return "\n".join(lines)


def empty_note(doc: Dict[str, Any], scope: Any = None) -> Optional[str]:
    """The stderr note for a valid selector that matched nothing (exit 0).

    ROB-13: `view.scope` is the **normalized** selector, because that is what
    hosts read back; `core/selectors.parse_scope` folds `symbol:` into `unit:`
    on purpose. Quoting the normalized form here told the user about a flag
    value they never wrote, on the one code path whose whole job is to help
    them find the right one - so when the caller still has the parsed `Scope`,
    its `as_typed` spelling wins.
    """
    view = doc.get("view")
    if not isinstance(view, dict) or not view.get("empty"):
        return None
    spelling = getattr(scope, "as_typed", None) or view.get("scope", "?")
    return ("mlview: scope %s matched no nodes; the whole graph has %d node(s). "
            "Nothing to draw is a finding, not an error."
            % (spelling, view.get("of", {}).get("nodes", 0)))


def issues_scope_suffix(doc: Dict[str, Any]) -> str:
    """The parenthetical `mlview issues` appends when a scope is active.

    Every other narrowing surface in this feature carries a denominator - the
    analyze summary line prints "<inScope> of <total> nodes", the viewer rail
    prints "3 of 15 findings shown - 12 outside this scope", `fail_on_suffix`
    prints "8 of 45 nodes". `issues` is the CI-facing command, so it says how
    many findings the scope is hiding instead of leaving its count to be read
    as a project total. Everything needed is already in `view.of.issues`.
    """
    view = doc.get("view")
    if not isinstance(view, dict):
        return ""
    in_scope = _issue_total(doc.get("stats", {}).get("issues"))
    total = _issue_total(view.get("of", {}).get("issues"))
    return (" (scope: %s · %d of %d, %d outside this scope)"
            % (view.get("scope", "?"), in_scope, total, max(total - in_scope, 0)))


def _issue_total(counts: Any) -> int:
    """The non-suppressed issue total behind an `IssueCounts` block."""
    if not isinstance(counts, dict):
        return 0
    return sum(int(counts.get(sev, 0) or 0) for sev in ("high", "medium", "low"))


def fail_on_suffix(doc: Dict[str, Any]) -> str:
    """`--fail-on`'s stderr line names the active scope, so a narrowed CI gate
    is visible in the log."""
    view = doc.get("view")
    if not isinstance(view, dict):
        return ""
    return (" (scope: %s · %d of %d nodes)"
            % (view.get("scope", "?"), doc.get("stats", {}).get("nodes", 0),
               view.get("of", {}).get("nodes", 0)))
