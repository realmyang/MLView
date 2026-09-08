"""The two honesty notes every MLView MCP payload carries.

Both answer the same question: *is an empty result good news?* `diagnostics_summary`
carries the document's diagnostics through `mlview.api.digest`, which drops them
wholesale, and `corpus_note` is the sentence that stops "0 issues" from a directory
with no Python — or one whose every file failed to parse — reading as a clean bill
of health, which is exactly what `commands/mlview-issues.md` tells the model to say.

Split out of `mlview_payloads` to keep that module inside the repo's ~600-line file
budget. Pure: no filesystem, no MCP SDK, no analyzer import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def diagnostics_summary(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`[{kind, count}]` for the document's diagnostics, worst-first by count.

    ``mlview.api.digest`` drops ``graph["diagnostics"]`` wholesale, so without this
    a `parse_error` never reaches the model through any tool and "0 issues" cannot
    be told apart from "every file failed to parse". It costs ~30 bytes per kind.
    """
    tally: Dict[str, int] = {}
    for entry in graph.get("diagnostics") or []:
        kind = entry.get("kind") or "unknown"
        tally[kind] = tally.get(kind, 0) + max(1, int(entry.get("count") or 1))
    return [
        {"kind": kind, "count": count}
        for kind, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def corpus_note(
    files_analyzed: int, files_failed: int, diagnostics: Sequence[Dict[str, Any]] = ()
) -> Optional[str]:
    """The sentence that stops "0 issues" from being read as "clean".

    A directory with no Python, and a directory whose every file failed to parse,
    otherwise produce byte-identical payloads to a genuinely clean workspace — and
    `commands/mlview-issues.md` tells the model to answer the latter with a
    positive clean bill of health.
    """
    parts: List[str] = []
    if not files_analyzed:
        parts.append(
            "no analyzable Python was found at this path, so an empty result is "
            "NOT a clean bill of health"
        )
    if files_failed:
        parts.append(
            "%d file(s) failed to parse; any issues they contain are missing from "
            "this result" % files_failed
        )
    if not parts:
        return None
    kinds = ", ".join(
        "%s x%d" % (d.get("kind"), d.get("count", 0)) for d in diagnostics
    )
    note = "; ".join(parts)
    return note + ((" (diagnostics: %s)" % kinds) if kinds else "")


__all__ = ["diagnostics_summary", "corpus_note"]
