"""The `--format summary` / `--format text` renderer.

**This is the only module in the core allowed to write to stdout**
(`test_stdout_purity.py` greps every other module for a bare `print(`).
Everything else - logs, warnings, progress - goes to stderr.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Sequence

from ..core.coverage import COVERAGE_KINDS
from .group_out import render_grouped

__all__ = ["render_text", "render_summary", "render_issue_table", "issue_lines",
           "render_findings", "scope_line", "write_stdout", "write_stdout_bytes",
           "write_stderr", "SEVERITY_MARK"]

SEVERITY_MARK = {"high": "[!!]", "medium": "[!]", "low": "[i]"}
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------- plumbing
def write_stdout(text: str) -> None:
    """Write payload text to stdout as UTF-8, with no newline translation."""
    data = text.encode("utf-8", "replace")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # pragma: no cover - exotic stdout replacements
        sys.stdout.write(text)
        sys.stdout.flush()
        return
    buffer.write(data)
    buffer.flush()


def write_stdout_bytes(data: bytes) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:  # pragma: no cover
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()
        return
    buffer.write(data)
    buffer.flush()


def write_stderr(text: str) -> None:
    sys.stderr.write(text if text.endswith("\n") else text + "\n")
    try:
        sys.stderr.flush()
    except Exception:  # pragma: no cover - closed stderr
        pass


# ------------------------------------------------------------------ render
def _fmt_int(value: Any) -> str:
    return str(value if isinstance(value, int) else 0)


def scope_line(doc: Dict[str, Any]) -> Optional[str]:
    """The one line a PROJECTION adds to a text payload (CONTRACTS 11.5).

    `None` for an unprojected document, which is what keeps an unscoped run
    byte-identical to what it printed before this feature existed.
    """
    view = doc.get("view")
    if not isinstance(view, dict):
        return None
    return ("scope: %s · depth %s · %s of %s nodes"
            % (view.get("scope", "all"), _fmt_int(view.get("depth")),
               _fmt_int(doc.get("stats", {}).get("nodes")),
               _fmt_int(view.get("of", {}).get("nodes"))))


def render_summary(doc: Dict[str, Any], show_suppressed: bool = False,
                   group_by: str = "none") -> str:
    """Header + per-stage counts + the issue table.

    `group_by` is RAIL-GROUP's CLI half. It defaults to `none`, which prints
    exactly what this function printed before the flag existed, so every
    snapshot and every host that parses this text is untouched.
    """
    ws = doc.get("workspace", {})
    gen = doc.get("generator", {})
    stats = doc.get("stats", {})
    counts = stats.get("issues", {"low": 0, "medium": 0, "high": 0})
    lines: List[str] = []
    lines.append("MLView %s  ·  %s" % (gen.get("version", "?"), ws.get("root", "")))
    frameworks = ", ".join(ws.get("frameworks") or []) or "none detected"
    lines.append("%s files analyzed · %s failed · %s notebooks skipped · frameworks: %s"
                 % (_fmt_int(ws.get("filesAnalyzed")), _fmt_int(ws.get("filesFailed")),
                    _fmt_int(ws.get("notebooksSkipped")), frameworks))
    entrypoints = ws.get("entrypoints") or []
    if entrypoints:
        lines.append("entrypoints: %s" % ", ".join(entrypoints[:5]))
    lines.append("%s nodes · %s edges · %s high / %s medium / %s low"
                 % (_fmt_int(stats.get("nodes")), _fmt_int(stats.get("edges")),
                    _fmt_int(counts.get("high")), _fmt_int(counts.get("medium")),
                    _fmt_int(counts.get("low"))))
    scoped = scope_line(doc)
    if scoped:
        lines.append(scoped)
    if stats.get("truncated"):
        lines.append("! graph truncated (--max-nodes reached)")
    lines.append("")

    lines.append("Stages")
    # Under a scope, a present stage with nothing kept means "not in THIS
    # view" - a different statement from "this project has no such stage", and
    # `present` deliberately still carries the project-level truth
    # (CONTRACTS 11.2 step 9 / 11.4). The viewer splits the two into separate
    # chip rows (11.4 F3); the text emitters make the same split, so a scoped
    # CI log cannot be read as a claim about what the project contains.
    scoped = isinstance(doc.get("view"), dict)
    absent: List[str] = []
    out_of_view: List[str] = []
    for stage in doc.get("stages", []):
        stage_counts = stage.get("issueCounts", {}) or {}
        if not stage.get("present"):
            absent.append(stage["id"])
            continue
        if scoped and not stage.get("nodeCount") and not any(stage_counts.values()):
            out_of_view.append(stage["id"])
            continue
        marks = " ".join("%s%d" % (SEVERITY_MARK[sev], stage_counts.get(sev, 0))
                         for sev in ("high", "medium", "low") if stage_counts.get(sev))
        lines.append("  %-11s %3d nodes%s" % (stage["id"], stage.get("nodeCount", 0),
                                              ("   " + marks) if marks else ""))
    if out_of_view:
        lines.append("  not in this scope: %s" % ", ".join(out_of_view))
    if absent:
        lines.append("  not detected: %s" % ", ".join(absent))
    lines.append("")

    issues = [i for i in doc.get("issues", []) if show_suppressed or not i.get("suppressed")]
    lines.append("Issues (%d)" % len(issues))
    lines.extend(issue_lines(issues, group_by) if issues else ["  none found"])

    diagnostics = doc.get("diagnostics") or []
    # COVERAGE: what the analyzer could *not* check gets its own block, above
    # the notes and outside the ten-note clip. Burying "I was blind here" among
    # the housekeeping is the failure this block exists to end.
    coverage = [d for d in diagnostics if d.get("kind") in COVERAGE_KINDS]
    other = [d for d in diagnostics if d.get("kind") not in COVERAGE_KINDS]
    if coverage:
        lines.append("")
        lines.append("Coverage (%d)" % len(coverage))
        lines.extend(_diagnostic_lines(coverage))
    if other:
        lines.append("")
        lines.append("Notes (%d)" % len(other))
        lines.extend(_diagnostic_lines(other[:10]))
    return "\n".join(lines) + "\n"


def _diagnostic_lines(diagnostics: Sequence[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for diagnostic in diagnostics:
        where = diagnostic.get("file")
        out.append("  %s: %s%s" % (diagnostic.get("kind", "note"),
                                   diagnostic.get("message", ""),
                                   (" (%s)" % where) if where else ""))
    return out


def issue_lines(issues: Sequence[Dict[str, Any]], group_by: str = "none") -> List[str]:
    """The issue table as lines - flat (`none`) or grouped by rule / file."""
    if group_by in ("rule", "file", "severity"):
        return render_grouped(issues, group_by, SEVERITY_MARK).splitlines()
    return render_issue_table(issues).splitlines()


def render_issue_table(issues: Sequence[Dict[str, Any]]) -> str:
    """The issue table: severity, code, confidence bucket, file:line, title."""
    rows = sorted(issues, key=lambda i: (_SEV_ORDER.get(i.get("severity"), 3),
                                         i.get("loc", {}).get("file", ""),
                                         i.get("loc", {}).get("line", 0),
                                         i.get("code", "")))
    lines: List[str] = []
    header = "  %-4s %-7s %-11s %-28s %s" % ("SEV", "CODE", "CONFIDENCE", "LOCATION", "TITLE")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for issue in rows:
        loc = issue.get("loc", {})
        where = "%s:%s" % (loc.get("file", "?"), loc.get("line", "?"))
        if len(where) > 28:
            where = "…" + where[-27:]
        mark = SEVERITY_MARK.get(issue.get("severity", "low"), "[i]")
        title = issue.get("title", "")
        if issue.get("suppressed"):
            title += "  (suppressed)"
        lines.append("  %-4s %-7s %-11s %-28s %s"
                     % (mark, issue.get("code", ""), issue.get("confidenceBucket", ""),
                        where, title))
    return "\n".join(lines)


def render_text(doc: Dict[str, Any]) -> str:
    """A longer plain-text view: the summary plus node lanes and fix hints.

    Deliberately takes no `group_by`: `api.render_text`'s one-argument
    signature is pinned by `tests/core/test_api.py::test_render_signatures`,
    and `--format text` is the *per-issue* form - its `Findings` block is one
    entry per issue by definition, so collapsing the table above it would only
    disagree with the block below.
    """
    parts = [render_summary(doc)]
    parts.append("Nodes")
    by_stage: Dict[str, List[Dict[str, Any]]] = {}
    for node in doc.get("nodes", []):
        by_stage.setdefault(node["stage"], []).append(node)
    for stage in doc.get("stages", []):
        nodes = by_stage.get(stage["id"]) or []
        if not nodes:
            continue
        parts.append("  %s (%d)" % (stage["label"], len(nodes)))
        for node in nodes:
            marks = "".join(SEVERITY_MARK.get(_severity_of(doc, iid), "")
                            for iid in node.get("issueIds", []))
            ghost = " · missing" if node.get("ghost") else ""
            parts.append("    %-6s %-22s %-30s %s:%d%s"
                         % (node["level"], node["kind"], _clip(node["label"], 30),
                            node["loc"]["file"], node["loc"]["line"], ghost + (" " + marks if marks else "")))
    issues = [i for i in doc.get("issues", []) if not i.get("suppressed")]
    if issues:
        parts.append("")
        parts.append("Findings")
        parts.extend(render_findings(issues).splitlines())
    return "\n".join(parts) + "\n"


def render_findings(issues: Sequence[Dict[str, Any]]) -> str:
    """The rich per-issue block: title, message, why, fix, related locations.

    Extracted so `mlview issues --text` reaches it too. CLEANUP 1: `--text`
    was declared on `issues` and read by nobody, so the obvious command for
    "show me the issues" was the one that hid the fix hints.
    """
    parts: List[str] = []
    for issue in issues:
        loc = issue.get("loc", {})
        parts.append("  %s %s  %s:%s" % (SEVERITY_MARK.get(issue.get("severity"), "[i]"),
                                         issue.get("code", ""), loc.get("file"),
                                         loc.get("line")))
        parts.append("      %s" % issue.get("title", ""))
        parts.append("      %s" % issue.get("message", ""))
        parts.append("      why: %s" % issue.get("why", ""))
        parts.append("      fix: %s" % issue.get("fixHint", ""))
        for related in issue.get("relatedLocs", []) or []:
            parts.append("      %s -> %s:%s" % (related.get("role"), related.get("file"),
                                                related.get("line")))
    return "\n".join(parts)


def _severity_of(doc: Dict[str, Any], issue_id: str) -> str:
    for issue in doc.get("issues", []):
        if issue["id"] == issue_id:
            return issue["severity"]
    return ""


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"
