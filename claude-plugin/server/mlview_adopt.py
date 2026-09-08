"""CI-ADOPT at the MCP boundary: `changedSince` and `baseline` for `mlview_issues`.

The agent loop is the surface CI-ADOPT was built for — `/mlview-issues` advertises
itself as being "for agent loops and PR descriptions", and on a repo that already
has 111 findings a PR description listing all of them is noise. `changedSince` turns
that into "what did THIS diff introduce"; `baseline` turns it into "what is new since
we froze the ratchet".

**This module implements nothing.** Attribution, the baseline match and the
degradation contract all live in `mlview.adopt` (the analyzer), and the whole job
here is to call the analyzer's own `cli_glue.apply_to_graph` with the same argument
shape the CLI passes it, so the MCP answer and `mlview issues --changed-since` cannot
diverge. That is the same rule `tools/verify.py`'s parity gate enforces for the
unattributed document.

**A core that predates CI-ADOPT degrades, it does not fail.** The plugin can be
installed against an older `mlview` (CONTRACTS A1 allows an installed core to shadow
the vendored one), and the answer then is every finding plus a note saying attribution
was unavailable and why — never an error, and never an empty list.
"""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("mlview.mcp")

__all__ = ["supported", "unsupported_note", "analyze_attributed", "adoption_notes",
           "ADOPT_NOTE_KINDS"]

#: The diagnostics `mlview.adopt` appends are all `config_warning`s; they are the
#: sentences that say what was attributed, what was dropped and what could not be
#: read, and they are exactly what the model must be told.
ADOPT_NOTE_KINDS = ("config_warning",)


def _adopt():
    """`mlview.adopt.cli_glue`, or None on a core that predates CI-ADOPT."""
    try:
        from mlview.adopt import cli_glue  # noqa: PLC0415 - optional, probed once per call
    except ImportError:
        return None
    if not hasattr(cli_glue, "apply_to_graph"):
        return None
    return cli_glue


def supported() -> bool:
    return _adopt() is not None


def unsupported_note(changed_since: Optional[str], baseline: Optional[str]) -> str:
    """What to tell the model when the installed core cannot attribute."""
    asked = []
    if changed_since:
        asked.append("changedSince=%s" % changed_since)
    if baseline:
        asked.append("baseline=%s" % baseline)
    return (
        "attribution unavailable: this MLView core has no `mlview.adopt`, so %s "
        "was ignored and EVERY finding is listed. This is not a statement that the "
        "change introduced them. Upgrade the core (`pip install --upgrade mlview`) "
        "or run `mlview issues --changed-since <rev>` with a newer CLI."
        % " and ".join(asked)
    )


def analyze_attributed(
    resolved: str,
    framework: str = "auto",
    max_nodes: int = 400,
    changed_since: Optional[str] = None,
    baseline: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Analyze the WHOLE project, then attribute. Returns `(document, notes)`.

    Whole-project first is not an implementation detail: a per-file or per-diff
    analysis loses the cross-file rules (COVERAGE measured 3 findings where the
    directory yields 7), so CI-ADOPT analyses everything and narrows afterwards.

    `changed_only` is always True here because that is what the parameter MEANS at
    this boundary — an agent that wanted every finding simply omits `changedSince`.
    Findings that merely sit in a changed file, or whose related location is inside
    an added hunk, are kept and marked `touched`; only `existing` is dropped, and
    the count that was dropped comes back in the notes.
    """
    from mlview.api import AnalyzeOptions, analyze  # noqa: PLC0415

    graph = analyze(
        AnalyzeOptions(
            paths=(resolved,),
            framework=framework or "auto",
            max_nodes=int(max_nodes),
        )
    )
    cli_glue = _adopt()
    notes: List[str] = []
    if cli_glue is None:
        return graph.to_dict(), [unsupported_note(changed_since, baseline)]

    before = set(id(d) for d in graph.diagnostics)
    args = SimpleNamespace(
        changed_since=changed_since or None,
        changed_paths=None,
        changed_only=bool(changed_since),
        baseline_path=os.path.abspath(baseline) if baseline else None,
    )
    problem = cli_glue.validate_args(args)
    if problem:
        # Cannot happen through this entry point (the two sources are exclusive by
        # construction), but a silent divergence from the CLI's own validation is
        # exactly the class of bug this delegation exists to prevent.
        return graph.to_dict(), [problem]
    try:
        cli_glue.apply_to_graph(graph, args)
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the tool
        log.warning("attribution failed (%s); reporting every finding", exc)
        return graph.to_dict(), [
            "attribution failed (%s), so every finding is listed. This is not a "
            "statement that the change introduced them." % exc
        ]
    doc = graph.to_dict()
    for diagnostic in graph.diagnostics:
        if id(diagnostic) not in before and getattr(diagnostic, "kind", "") in ADOPT_NOTE_KINDS:
            notes.append(str(getattr(diagnostic, "message", "")))
    return doc, notes


def adoption_notes(doc: Dict[str, Any]) -> List[str]:
    """The adoption diagnostics already inside a document, for a cached read."""
    return [
        str(d.get("message", ""))
        for d in (doc.get("diagnostics") or [])
        if d.get("kind") in ADOPT_NOTE_KINDS
    ]
