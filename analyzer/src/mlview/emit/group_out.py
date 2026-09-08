"""`--group-by rule|file|none`: the CLI half of RAIL-GROUP.

Two audits measured the same failure on two corpora: **113 rows in an 830 px
panel from 12 distinct codes**, and **111 rows that are 11 codes x 10 identical
repeats**. The CLI has the same shape - `mlview issues` on a 50-file workspace
prints 111 lines to say five things.

Grouping is a **rendering** choice, never a filter: every occurrence is still
counted, and `none` (the default) prints exactly what it printed before this
module existed, so every snapshot and `--json` consumer is untouched.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

__all__ = ["GROUP_BY", "render_grouped", "group_rows"]

#: Accepted `--group-by` values. `none` is the default everywhere.
GROUP_BY = ("none", "rule", "file")

_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
_BUCKET_ORDER = ("certain", "likely", "possible", "speculative")


def _plural(count: int, word: str) -> str:
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _worst_severity(issues: Sequence[Dict[str, Any]]) -> str:
    return min((i.get("severity", "low") for i in issues),
               key=lambda s: _SEV_ORDER.get(s, 3), default="low")


def _worst_bucket(issues: Sequence[Dict[str, Any]]) -> str:
    buckets = [i.get("confidenceBucket", "") for i in issues]
    for name in _BUCKET_ORDER:
        if name in buckets:
            return name
    return ""


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def group_rows(issues: Sequence[Dict[str, Any]], by: str) -> List[Dict[str, Any]]:
    """One row per group, worst severity first then key.

    Each row carries `key`, `severity`, `bucket`, `count`, `files`, `codes`
    and `title`, so a caller that is not the text emitter (a host, a test) can
    render the same grouping without re-deriving it.
    """
    if by not in ("rule", "file"):
        return []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for issue in issues:
        key = (issue.get("code", "?") if by == "rule"
               else (issue.get("loc", {}) or {}).get("file", "?"))
        buckets.setdefault(key, []).append(issue)
    rows: List[Dict[str, Any]] = []
    for key in sorted(buckets):
        members = buckets[key]
        files = sorted({(i.get("loc", {}) or {}).get("file", "?") for i in members})
        codes = sorted({i.get("code", "?") for i in members})
        rows.append({
            "key": key,
            "severity": _worst_severity(members),
            "bucket": _worst_bucket(members),
            "count": len(members),
            "files": files,
            "codes": codes,
            "title": members[0].get("title", "") if by == "rule" else "",
            "lines": sorted((i.get("loc", {}) or {}).get("line", 0) for i in members),
        })
    rows.sort(key=lambda r: (_SEV_ORDER.get(r["severity"], 3), r["key"]))
    return rows


def render_grouped(issues: Sequence[Dict[str, Any]], by: str,
                   severity_mark: Optional[Dict[str, str]] = None) -> str:
    """The grouped issue table: one line per rule (or per file)."""
    marks = severity_mark or {"high": "[!!]", "medium": "[!]", "low": "[i]"}
    rows = group_rows(issues, by)
    lines: List[str] = []
    if by == "rule":
        header = "  %-4s %-7s %-11s %-28s %s" % ("SEV", "CODE", "CONFIDENCE",
                                                 "OCCURRENCES", "TITLE")
    else:
        header = "  %-4s %-28s %-11s %-28s %s" % ("SEV", "FILE", "WORST",
                                                  "OCCURRENCES", "RULES")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for row in rows:
        mark = marks.get(row["severity"], "[i]")
        if by == "rule":
            where = "%s in %s" % (_plural(row["count"], "occurrence"),
                                  _plural(len(row["files"]), "file"))
            lines.append("  %-4s %-7s %-11s %-28s %s"
                         % (mark, row["key"], row["bucket"], _clip(where, 28),
                            row["title"]))
        else:
            where = "%s · %s" % (_plural(row["count"], "occurrence"),
                                      _plural(len(row["codes"]), "rule"))
            lines.append("  %-4s %-28s %-11s %-28s %s"
                         % (mark, _clip(row["key"], 28), row["bucket"],
                            _clip(where, 28), ", ".join(row["codes"])))
    return "\n".join(lines)
