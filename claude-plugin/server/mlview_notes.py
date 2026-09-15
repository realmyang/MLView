"""The honesty notes every MLView MCP payload carries.

They all answer the same question: *is an empty result good news?*

* ``diagnostics_summary`` carries the document's diagnostics through
  ``mlview.api.digest``, which drops them wholesale, as a ``{kind, count}`` tally.
* ``corpus_note`` is the sentence that stops "0 issues" from a directory with no
  Python - or one whose every file failed to parse - reading as a clean bill of
  health, which is exactly what ``commands/mlview-issues.md`` tells the model to say.
* ``coverage_notes`` / ``coverage_note`` (ROADMAP COVERAGE) are the *blind spot*
  half: the analyzer's coverage diagnostics name the rules that could not run,
  and a ``{kind, count}`` tally drops precisely that. ``commands/mlview.md`` tells
  the model to "name the rules that could not run before you report the count", so
  the codes and the analyzer's own sentence have to be IN the payload; without them
  that instruction can only be met by inventing rule codes, and the bare ``count``
  - sibling modules for ``single_file_analysis`` - reads as a tally of rules.
  This is the plugin's mirror of ``vscode-extension/src/coverage.ts``.

Split out of ``mlview_payloads`` to keep that module inside the repo's ~600-line
file budget. Pure: no filesystem, no MCP SDK, no analyzer import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: The ``Diagnostic.kind`` values this host reads as coverage caveats. Closed, and
#: in the order a payload renders them; the same SET as `mlview.core.coverage`
#: emits and as `coverage.ts` reads, which
#: ``tests/test_payload_truth.py::test_this_host_reads_every_coverage_kind_the_core_emits``
#: gates - a kind that lands in the core and in neither host is a caveat the model
#: never sees. ``framework_filter`` is third because ``mlview_analyze`` lets the
#: MODEL set ``framework``: narrowing it drops rules the detected frameworks would
#: have run, and without this entry the shorter finding list arrived with no
#: explanation at all - exactly the false clean bill of health this module exists
#: to prevent. Render order is each host's own; only the membership is shared.
COVERAGE_KINDS = ("single_file_analysis", "untagged_dataflow", "framework_filter")

#: How many rule codes one caveat carries before the list is elided. There are only
#: a handful of cross-file / leakage rules, so this is a safety valve rather than a
#: routine clip - but it is what makes the block's size bounded, which is what lets
#: ``mlview_budget.PROTECTED_KEYS`` protect it from the budget walk.
MAX_CODES = 6

#: How much of the analyzer's own sentence survives into the payload. The longest
#: real message today is ~360 bytes; 400 keeps every one of them whole while capping
#: the block at ~1.4 KB of the 4 KB budget even with all three kinds present.
MAX_MESSAGE = 400


def _occurrences(entry: Dict[str, Any]) -> int:
    """``entry["count"]`` as a positive int, tolerating junk from an older core."""
    try:
        value = int(entry.get("count") or 1)
    except (TypeError, ValueError):
        return 1
    return value if value > 0 else 1


def diagnostics_summary(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`[{kind, count}]` for the document's diagnostics, worst-first by count.

    ``mlview.api.digest`` drops ``graph["diagnostics"]`` wholesale, so without this
    a `parse_error` never reaches the model through any tool and "0 issues" cannot
    be told apart from "every file failed to parse". It costs ~30 bytes per kind.

    This is a TALLY, not an explanation: the count means something different for
    every kind - sibling modules for ``single_file_analysis``, untraced sites for
    ``untagged_dataflow``, suppressed rule codes for ``framework_filter`` - and
    ``coverage_notes`` below is what carries the wording that says which.
    """
    tally: Dict[str, int] = {}
    for entry in graph.get("diagnostics") or []:
        kind = entry.get("kind") or "unknown"
        tally[kind] = tally.get(kind, 0) + _occurrences(entry)
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


# --------------------------------------------------------------------- COVERAGE
def _clip(text: str, limit: int = MAX_MESSAGE) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _default_message(kind: str) -> str:
    """The wording used when the analyzer sent a kind with no message of its own."""
    if kind == "single_file_analysis":
        return (
            "Only part of the project was analyzed, so the rules that need "
            "cross-file evidence could not run."
        )
    if kind == "framework_filter":
        return (
            "A framework filter narrowed the rule set, so rules the detected "
            "frameworks would have run did not - a clean result here is a clean "
            "result for that framework alone."
        )
    return (
        "A key argument carried no dataflow tag, so the leakage rules could not "
        "check it - a gap in coverage, not a clean result."
    )


def coverage_notes(graph: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`[{kind, count, codes, message}]` for the coverage diagnostics in ``graph``.

    One entry per kind — a workspace with forty untagged sites is one caveat with
    ``count: 40``, not forty rows — carrying the union of the rule codes the
    analyzer named and its own sentence for the first occurrence, clipped. Entries
    come back in ``COVERAGE_KINDS`` order, so two runs never reorder the block.

    A kind this host does not know is left alone: it still reaches the model in the
    ``diagnostics`` tally, and nothing here invents a caveat the analyzer did not
    emit.
    """
    by_kind: Dict[str, Dict[str, Any]] = {}
    for entry in (graph or {}).get("diagnostics") or []:
        kind = entry.get("kind")
        if kind not in COVERAGE_KINDS:
            continue
        codes = [c for c in (entry.get("codes") or []) if isinstance(c, str)]
        note = by_kind.get(kind)
        if note is None:
            message = entry.get("message")
            by_kind[kind] = {
                "kind": kind,
                "count": _occurrences(entry),
                "codes": codes[:MAX_CODES],
                "message": _clip(
                    (message if isinstance(message, str) else "").strip()
                    or _default_message(kind)
                ),
            }
            continue
        note["count"] += _occurrences(entry)
        for code in codes:
            if code not in note["codes"] and len(note["codes"]) < MAX_CODES:
                note["codes"].append(code)
    return [by_kind[kind] for kind in COVERAGE_KINDS if kind in by_kind]


def coverage_note(notes: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The imperative sentence that goes with a ``coverage`` block, or ``None``.

    ``commands/mlview.md`` asks the model to name the rules that could not run
    *before* it reports the finding count. This is the payload half of that
    instruction: the codes are quoted from the analyzer, and the wording says the
    count beside them is a floor rather than a verdict.
    """
    parts: List[str] = []
    for note in notes:
        codes = [c for c in (note.get("codes") or []) if isinstance(c, str)]
        parts.append(
            "%s - %s could not run"
            % (note.get("kind"), ", ".join(codes) if codes else "some rules")
        )
    if not parts:
        return None
    return (
        "COVERAGE: this analysis was incomplete, so the finding count is a floor, "
        "not a clean bill of health (%s); name those rule codes before you report "
        "the count" % "; ".join(parts)
    )


__all__ = [
    "COVERAGE_KINDS",
    "MAX_CODES",
    "MAX_MESSAGE",
    "diagnostics_summary",
    "corpus_note",
    "coverage_notes",
    "coverage_note",
]
