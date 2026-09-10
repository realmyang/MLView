"""The `--format summary` / `--format text` renderer.

**This is the only module in the core allowed to write to stdout**
(`test_stdout_purity.py` greps every other module for a bare `print(`).
Everything else - logs, warnings, progress - goes to stderr.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Sequence

from ..core.coverage import COVERAGE_KINDS
from ..core.unresolved import UNRESOLVED_KIND, unresolved_note
from .answers import render_block as render_answers_block
from .group_out import render_grouped

__all__ = ["render_text", "render_summary", "render_issue_table", "issue_lines",
           "diagnostic_block", "fix_block",
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
    # CI-ADOPT: `stats.issues` is the document's project-level truth and counts
    # every unsuppressed finding, baselined or not. The printed line is what a
    # reader is being asked to act on, so it nets the baselined ones out and
    # says how many they were - never one number silently standing for two.
    counts, baselined = _visible_counts(doc, counts)
    lines.append("%s nodes · %s edges · %s high / %s medium / %s low%s"
                 % (_fmt_int(stats.get("nodes")), _fmt_int(stats.get("edges")),
                    _fmt_int(counts.get("high")), _fmt_int(counts.get("medium")),
                    _fmt_int(counts.get("low")),
                    (" · %d baselined" % baselined) if baselined else ""))
    scoped = scope_line(doc)
    if scoped:
        lines.append(scoped)
    if stats.get("truncated"):
        lines.append("! graph truncated (--max-nodes reached)")
    lines.append("")

    # MLV-P1: the four questions, answered in words, as the first block - a CI
    # log and a terminal both put the answer above the evidence. Absent on a
    # document that carries no `answers` key (the hand-authored golden), and
    # then the block simply is not there.
    answers = render_answers_block(doc.get("answers"))
    if answers:
        lines.extend(answers)
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
        # ANA-5a: "not detected" is a claim about the program. It may only be
        # made without qualification when the analyzer resolved everything it
        # saw; where it did not, the sentence says so on the same line rather
        # than in a note the reader has to find.
        lines.append("  not detected: %s%s"
                     % (", ".join(absent), _unresolved_suffix(doc)))
    lines.append("")

    issues = [i for i in doc.get("issues", [])
              if show_suppressed or not (i.get("suppressed") or i.get("baselined"))]
    set_aside = [i for i in issues if i.get("suppressed") or i.get("baselined")]
    heading = "Issues (%d)" % len(issues)
    if set_aside:
        # Name the denominator the way `mlview issues` already does, so one
        # command's header and its own table cannot state two numbers.
        baselined = sum(1 for i in set_aside
                        if i.get("baselined") and not i.get("suppressed"))
        suppressed = sum(1 for i in set_aside if i.get("suppressed"))
        parts = ["%d" % (len(issues) - len(set_aside))]
        if baselined:
            parts.append("%d baselined" % baselined)
        if suppressed:
            parts.append("%d suppressed" % suppressed)
        heading = "Issues (%s)" % " · ".join(parts)
    lines.append(heading)
    lines.extend(issue_lines(issues, group_by) if issues else ["  none found"])

    lines.extend(fix_block(doc))
    lines.extend(diagnostic_block(doc))
    return "\n".join(lines) + "\n"


def fix_block(doc: Dict[str, Any]) -> List[str]:
    """H5's `Fixes (N)` block as lines, empty when nothing carries an edit.

    Two things belong here and the second is the one that matters. The first is
    the list itself: which findings come with a computed edit, how safe it is,
    and where it lands. The second is the **denominator** - when a rule
    produced an edit somewhere in this run and not somewhere else, the block
    says so out loud. `samples/vision_pipeline` is exactly that case: one
    MLV602 gets `random_state=42` and the other gets nothing, because
    `data.py` never binds the name `torch` to spell a generator with. Printing
    only the fixes that exist would let a reader conclude the second split was
    fine.
    """
    issues = [i for i in doc.get("issues", [])
              if not (i.get("suppressed") or i.get("baselined"))]
    fixed = [i for i in issues if isinstance(i.get("fix"), dict)]
    if not fixed:
        return []
    fixed.sort(key=lambda i: (_SEV_ORDER.get(i.get("severity"), 3),
                              i.get("loc", {}).get("file", ""),
                              i.get("loc", {}).get("line", 0), i.get("code", "")))
    lines = ["", "Fixes (%d)" % len(fixed)]
    for issue in fixed:
        fix = issue["fix"]
        edits = fix.get("edits") or [{}]
        where = "%s:%s" % (edits[0].get("file", "?"), edits[0].get("line", "?"))
        lines.append("  %-12s %-7s %-24s %s"
                     % (fix.get("safety", ""), issue.get("code", ""), where,
                        fix.get("title", "")))
    codes = {i.get("code") for i in fixed}
    missing = sorted({i.get("code") for i in issues
                      if i.get("code") in codes and not i.get("fix")})
    if missing:
        lines.append("  no edit was computed for %d other finding(s) of %s - "
                     "see docs/rules/<CODE>.md for when one is withheld"
                     % (sum(1 for i in issues
                            if i.get("code") in missing and not i.get("fix")),
                        ", ".join(missing)))
    lines.append("  nothing here is applied automatically.")
    return lines


def diagnostic_block(doc: Dict[str, Any], limit: int = 10) -> List[str]:
    """The `Coverage` and `Notes` blocks as lines, empty when there are none.

    Factored out of `render_summary` for `mlview issues`, which built its own
    body and rendered no diagnostics at all: under `--changed-only` it printed
    `0 issue(s) - none found` while `analyze` said on the same argv that 15
    findings had been set aside. `issues` is the surface CI-ADOPT names as the
    one "for agent loops and PR descriptions", so it is the last place that may
    leave a reader unable to tell "I checked and it is fine" from "I could not
    check".
    """
    diagnostics = doc.get("diagnostics") or []
    # COVERAGE: what the analyzer could *not* check gets its own block, above
    # the notes and outside the ten-note clip. Burying "I was blind here" among
    # the housekeeping is the failure this block exists to end.
    coverage = [d for d in diagnostics if d.get("kind") in COVERAGE_KINDS]
    other = [d for d in diagnostics if d.get("kind") not in COVERAGE_KINDS]
    lines: List[str] = []
    if coverage:
        lines.append("")
        lines.append("Coverage (%d)" % len(coverage))
        lines.extend(_diagnostic_lines(coverage))
    if other:
        lines.append("")
        lines.append("Notes (%d)" % len(other))
        lines.extend(_diagnostic_lines(other[:limit]))
    return lines


def _unresolved_suffix(doc: Dict[str, Any]) -> str:
    """The ANA-5a qualifier for the "not detected" line, or ""."""
    count = sum(int(d.get("count") or 1) for d in (doc.get("diagnostics") or [])
                if isinstance(d, dict) and d.get("kind") == UNRESOLVED_KIND)
    return unresolved_note(count) or ""


def _visible_counts(doc: Dict[str, Any],
                    counts: Dict[str, Any]) -> tuple:
    """`(counts minus the baselined findings, how many those were)`."""
    baselined = [i for i in doc.get("issues", [])
                 if i.get("baselined") and not i.get("suppressed")]
    if not baselined:
        return counts, 0
    adjusted = {sev: int(counts.get(sev, 0) or 0) for sev in ("low", "medium", "high")}
    for issue in baselined:
        severity = issue.get("severity", "low")
        adjusted[severity] = max(0, adjusted.get(severity, 0) - 1)
    return adjusted, len(baselined)


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
        elif issue.get("baselined"):
            # VW-11: a suppressed row was marked and a baselined one was not,
            # so `--show-suppressed` printed a header netting six findings out
            # over a table that listed them indistinguishably from the rest.
            title += "  (baselined)"
        # H5: the row says an edit exists; `Fixes (N)` below says what it is.
        # Marked on the row too because a reader scanning the table for
        # something to act on should not have to hold two blocks in their head.
        if isinstance(issue.get("fix"), dict):
            title += "  (fix)"
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
    issues = [i for i in doc.get("issues", [])
              if not (i.get("suppressed") or i.get("baselined"))]
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
        fix = issue.get("fix")
        if isinstance(fix, dict):
            edits = fix.get("edits") or [{}]
            parts.append("      edit: %s [%s] -> %s:%s (not applied)"
                         % (fix.get("title", ""), fix.get("safety", ""),
                            edits[0].get("file", "?"), edits[0].get("line", "?")))
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
