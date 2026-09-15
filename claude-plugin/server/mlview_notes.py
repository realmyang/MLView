"""The honesty notes every MLView MCP payload carries.

They all answer the same question: *is an empty result good news?*

* ``diagnostics_summary`` carries the document's diagnostics through
  ``mlview.api.digest``, which drops them wholesale, as a ``{kind, count}`` tally.
* ``corpus_note`` is the sentence that stops "0 issues" from a directory with no
  Python - or one whose every file failed to parse - reading as a clean bill of
  health, which is exactly what ``commands/mlview-issues.md`` tells the model to say.
* ``coverage_notes`` / ``coverage_note`` (ROADMAP COVERAGE) are the *blind spot*
  half: the coverage diagnostics name the rules that could not run,
  and a ``{kind, count}`` tally drops precisely that. ``commands/mlview.md`` tells
  the model to "name the rules that could not run before you report the count", so
  the codes and the producer's own sentence have to be IN the payload; without them
  that instruction can only be met by inventing rule codes, and the bare ``count``
  - sibling modules for ``single_file_analysis`` - reads as a tally of rules.
  This is the plugin's mirror of ``vscode-extension/src/coverage.ts``.

Split out of ``mlview_payloads`` to keep that module inside the repo's ~600-line
file budget. Pure: no filesystem, no MCP SDK, no analyzer import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: The ``Diagnostic.kind`` values this host reads as coverage caveats. Closed, and
#: in the order a payload renders them: the three the ANALYZER emits lead, because
#: they say what the run could not see; the one this HOST derives follows, because
#: it says what the caller asked not to run.
#:
#: CONTRACTS §2.6 C9 as restated by §17 E40 is a SUBSET rule, not an equality: no
#: coverage kind the core emits may be dropped by a host, and each extra kind a
#: host lists is named in the contract. ``framework_filter`` is the core's — it
#: arrived with C8 and dropping it would have let a run the MODEL ITSELF narrowed
#: come back as a clean bill of health. ``framework_suppressed`` is the extra one,
#: and only HALF of that kind belongs here — see :func:`is_framework_filter_note`.
#:
#: The two say the SAME cost when both are present, and BOTH are written: on every
#: non-auto run :func:`mlview_workspace.note_framework_suppression` appends the
#: host's note to ``graph["diagnostics"]`` - and so to the ``graph.json`` on disk -
#: beside the analyzer's ``framework_filter``. That is deliberate: §11.4 B3 has the
#: ``{kind, count}`` tally carry each producer's own statement, and 11.57 B1's gates
#: read the host's there. It is §11.4 C3 that forbids adding the two counts
#: together, and that is an obligation on the READER; the way this module makes it
#: impossible to trip over is :func:`coverage_notes`, which renders exactly ONE of
#: them - the analyzer's whenever it spoke, the host's only where it was silent, as
#: in a ``graph.json`` cached by a build older than C8.
COVERAGE_KINDS = (
    "single_file_analysis",
    "untagged_dataflow",
    "framework_filter",
    "framework_suppressed",
)

#: Every message :func:`mlview_workspace.framework_suppression` writes begins with
#: this, and no other producer of the kind does.
FRAMEWORK_FILTER_PREFIX = "--framework "


def is_framework_filter_note(entry: Any) -> bool:
    """True for the ``framework_suppressed`` note a ``--framework`` filter owes.

    ONE kind, TWO statements, and only one of them is a coverage caveat:

    * the analyzer's R3.8 absence gate — "Training loop handled by Keras - 1
      rule(s) de-rated to speculative" (`mlview/rules/context.py:_note_gate`).
      Those rules RAN; their severity was capped. Rendering that as "MLV601 could
      not run" beside "the finding count is a floor, not a clean bill of health"
      would be a coverage claim MLView never made, on every Lightning, HF and
      Keras workspace — a misrepresentation in the opposite direction to the one
      this module exists to prevent.
    * this host's ``--framework`` filter, where the named rules really did not
      run at all.

    The analyzer's Diagnostic carries no field that separates them (the schema's
    ``kind`` is closed and neither producer is tagged), so the discriminator is
    the message this server writes itself. It is checked, never assumed: an entry
    that does not start with the prefix is left in the ``diagnostics`` tally
    exactly where it has always been.
    """
    return (
        isinstance(entry, dict)
        and entry.get("kind") == "framework_suppressed"
        and str(entry.get("message") or "").startswith(FRAMEWORK_FILTER_PREFIX)
    )


#: How many rule codes one caveat carries before the list is elided. There are only
#: a handful of cross-file / leakage rules, so this is a safety valve rather than a
#: routine clip - but it is what makes the block's size bounded, which is what lets
#: ``mlview_budget.PROTECTED_KEYS`` protect it from the budget walk.
MAX_CODES = 6

#: How much of the analyzer's own sentence survives into the payload. The longest
#: real message today is ~360 bytes; 400 keeps every one of them whole while capping
#: the block at ~1 KB of the 4 KB budget even with both kinds present.
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

    This is a TALLY, not an explanation: for the two coverage kinds the count is
    sibling modules / untraced sites, never rules, and ``coverage_notes`` below is
    what carries the wording and the rule codes.
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


#: One sentence per coverage kind, used when the diagnostic arrived without a
#: message of its own. Keyed rather than branched so adding a kind to
#: ``COVERAGE_KINDS`` cannot silently borrow another kind's wording — which is
#: what a trailing ``return`` did: every kind but ``single_file_analysis`` got the
#: dataflow sentence, so the next kind added would have described itself as a
#: leakage gap. (``framework_suppressed`` needs no entry: a filter note is
#: RECOGNIZED by its message, so one without a message is not a filter note.)
_DEFAULT_MESSAGES = {
    "single_file_analysis": (
        "Only part of the project was analyzed, so the rules that need "
        "cross-file evidence could not run."
    ),
    "untagged_dataflow": (
        "A key argument carried no dataflow tag, so the leakage rules could not "
        "check it - a gap in coverage, not a clean result."
    ),
    "framework_filter": (
        "A --framework filter narrowed the rule set, so rules the detected "
        "frameworks would have run did not - a filtered answer, not a clean one."
    ),
}

#: For a kind with no sentence of its own: says the run was incomplete and nothing
#: more, rather than borrowing a neighbour's explanation.
_GENERIC_DEFAULT = (
    "Part of this analysis could not run, so the finding count is a floor rather "
    "than a clean result."
)


def _default_message(kind: str) -> str:
    """The wording used when the analyzer sent a kind with no message of its own."""
    return _DEFAULT_MESSAGES.get(kind, _GENERIC_DEFAULT)


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
    diagnostics = (graph or {}).get("diagnostics") or []
    # C8 gave the ANALYZER the same statement this host has derived since 11.57:
    # `framework_filter` names the codes a `--framework` filter dropped, from the
    # same registry, and the host's `framework_suppressed` filter note names them
    # again. CONTRACTS §11.4 C3 forbids a reader adding the two counts together;
    # rendering both here is what would invite it, and the note built from this
    # block read "MLV121, MLV705, MLV709 could not run" twice in one sentence.
    # The analyzer's is the one kept - it is the producer that ran the rules - and
    # the host's survives in `diagnostics` (where 11.57 B1's gates read it) and
    # renders whenever the analyzer was silent: a `graph.json` cached by a build
    # older than C8, which `analyzer_identity()` still serves.
    analyzer_said_it = any(
        isinstance(e, dict) and e.get("kind") == "framework_filter"
        for e in diagnostics
    )
    by_kind: Dict[str, Dict[str, Any]] = {}
    for entry in diagnostics:
        kind = entry.get("kind")
        if kind not in COVERAGE_KINDS:
            continue
        if kind == "framework_suppressed":
            if not is_framework_filter_note(entry):
                # The analyzer's absence gate, not a filter: those rules ran.
                continue
            if analyzer_said_it:
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
    "FRAMEWORK_FILTER_PREFIX",
    "is_framework_filter_note",
    "MAX_CODES",
    "MAX_MESSAGE",
    "diagnostics_summary",
    "corpus_note",
    "coverage_notes",
    "coverage_note",
]
