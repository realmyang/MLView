"""Grouped issue views for ``mlview_issues`` (ROADMAP RAIL-GROUP, host half).

Two audits measured the same failure on two corpora: **113 rows from 12 distinct
codes**, and **111 rows that are 11 codes x 10 identical repeats**. Over MCP that
is worse than in a rail, because the 4 KB budget then sheds rows until the answer
is both long and incomplete: the model reads ten copies of MLV702 and never learns
there are only twelve distinct problems.

``group_by`` folds the rows before the budget does. One row per rule (or per file,
or per severity) with an occurrence count, the worst severity and confidence in the
group, and up to three example sites — so "what is wrong with this repo" costs
twelve lines instead of a hundred and eleven, and the sites are still citable.

Pure: no filesystem, no MCP SDK, no analyzer import. ``tests/test_issue_groups.py``
asserts it directly on a synthetic graph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: The accepted values of the `groupBy` tool argument and the `--group-by` CLI flag.
GROUP_BY_MODES = ("rule", "file", "severity")

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
#: Worst (most certain) first, so a group's bucket is the strongest claim inside it.
BUCKET_RANK = {"speculative": 0, "possible": 1, "likely": 2, "certain": 3}

#: How many `file:line` examples ride along on each group row.
MAX_SITES = 3


def _file_of(row: Dict[str, Any]) -> Optional[str]:
    """The row's file.

    ``group_issues`` folds the FLAT payload rows `issues_payload` already built
    (`{code, severity, file, line, ...}`), not the raw graph issues — grouping the
    rows is what keeps the group counts and the listed rows describing the same
    filtered set. The ``loc`` fallback is there so a raw issue also groups sanely.
    """
    if row.get("file"):
        return str(row["file"])
    loc = row.get("loc") or {}
    return str(loc["file"]) if loc.get("file") else None


def _line_of(row: Dict[str, Any]) -> Any:
    if row.get("line") is not None:
        return row["line"]
    return (row.get("loc") or {}).get("line")


def _site(row: Dict[str, Any]) -> Optional[str]:
    path = _file_of(row)
    if not path:
        return None
    line = _line_of(row)
    return "%s:%s" % (path, line) if line else path


def _key_for(row: Dict[str, Any], mode: str) -> Optional[str]:
    if mode == "rule":
        return row.get("code")
    if mode == "severity":
        return row.get("severity")
    return _file_of(row)


def group_issues(issues: Sequence[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    """Fold ``issues`` into one row per ``mode`` key, worst and biggest first.

    ``issues`` is the already-filtered, already-unsuppressed list the payload
    builder produced; grouping never widens or narrows a filter, so the counts
    on the rows always add up to the rows that were folded.
    """
    if mode not in GROUP_BY_MODES:
        raise ValueError(
            "groupBy=%r is not valid; accepted values are %s"
            % (mode, ", ".join(repr(m) for m in GROUP_BY_MODES))
        )

    order: List[str] = []
    groups: Dict[str, Dict[str, Any]] = {}
    for issue in issues:
        key = _key_for(issue, mode)
        if not key:
            continue
        row = groups.get(key)
        if row is None:
            order.append(key)
            row = groups[key] = {
                "key": key,
                "title": issue.get("title") or "",
                "count": 0,
                "files": [],
                "codes": [],
                "maxSeverity": "low",
                "worstBucket": None,
                "sites": [],
            }
        row["count"] += 1
        severity = issue.get("severity") or "low"
        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(row["maxSeverity"], 0):
            row["maxSeverity"] = severity
        bucket = issue.get("confidenceBucket")
        if bucket and (
            row["worstBucket"] is None
            or BUCKET_RANK.get(bucket, 0) > BUCKET_RANK.get(row["worstBucket"], 0)
        ):
            row["worstBucket"] = bucket
        code = issue.get("code")
        if code and code not in row["codes"]:
            row["codes"].append(code)
        issue_file = _file_of(issue)
        if issue_file and issue_file not in row["files"]:
            row["files"].append(issue_file)
        site = _site(issue)
        if site and len(row["sites"]) < MAX_SITES:
            row["sites"].append(site)

    rows = [_finish(groups[key], mode) for key in order]
    rows.sort(
        key=lambda r: (-SEVERITY_RANK.get(r["maxSeverity"], 0), -r["count"], r["key"])
    )
    return rows


def _finish(row: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Shape one row: `files` becomes a COUNT, and the redundant key is dropped.

    A rule group whose key already is the code does not repeat it in `codes`, and a
    file group does not repeat the filename in `files` — the payload is 4 KB and a
    field that restates the key is a field that costs rows.
    """
    out: Dict[str, Any] = {
        "key": row["key"],
        "count": row["count"],
        "maxSeverity": row["maxSeverity"],
        "sites": row["sites"],
    }
    if row["worstBucket"]:
        out["worstBucket"] = row["worstBucket"]
    if mode == "rule":
        out["title"] = row["title"]
        out["files"] = len(row["files"])
    elif mode == "file":
        out["codes"] = row["codes"]
    else:  # severity
        out["codes"] = row["codes"]
        out["files"] = len(row["files"])
    return out


def group_note(mode: str, groups: Sequence[Dict[str, Any]], total: int) -> str:
    """The sentence that stops a grouped answer reading as a shorter finding list."""
    return (
        "grouped by %s: %d group(s) covering %d finding(s) — the rows are folded, "
        "not filtered; omit groupBy for the individual findings"
        % (mode, len(groups), total)
    )


__all__ = ["GROUP_BY_MODES", "MAX_SITES", "group_issues", "group_note"]
