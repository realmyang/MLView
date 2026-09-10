"""VIEW-08 in the Claude Code plugin: ``mlview_graph(scope="diff", base=...)``.

The comparison is defined ONCE, in the analyzer (``mlview.core.diff``, CONTRACTS
section 11.38), so the report, the editor and this server all answer the reviewer's
question the same way.  This module is the tool boundary around it and nothing more:
it resolves the base path, refuses what is not a graph, calls ``diff_documents`` and
renders the summary ``emit/diff_out`` already writes.

Three decisions worth stating, because each is a place a comparison could quietly
mislead a reader:

1. **It is a SCOPE, not a sixth tool.**  ``mlview_graph`` already means "render this
   workflow in a way I can read in the terminal", and a diff is another projection of
   the same graph -- the same argument section 11.1 makes for ``stage:`` and
   ``unit:``.  A sixth tool would be a sixth thing for a model to choose between.

2. **``notes[]`` is never shed.**  ``note`` is a PROTECTED key in the budget walk, so
   the 4 KB clip can drop diff rows but can never drop the sentence explaining that a
   ``removed`` node may mean "not analysed" rather than "deleted".  Section 11.38 C is
   the honesty half of VIEW-08 and it does not survive being optional.

3. **A base that is not a graph is an ERROR, never an empty diff.**  Comparing a
   report against an overlay, or against a file that is not JSON, must come back as a
   message the model can act on -- ``visible_errors`` re-raises it as ``ToolError`` --
   because "0 changes" is the most dangerous wrong answer this feature can give.

**What it cannot do.**  A diff joins on the section 0 stable id, so a renamed file is
every node removed plus every node added; no rename detection is attempted here or in
the analyzer.  It compares two DOCUMENTS, so a base produced by a different analyzer
version or a different ``--max-nodes`` is compared anyway and the ``notes`` say so.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

from mlview_budget import LIMIT_BYTES, clip_text_lines, fit, payload_size

__all__ = ["DIFF_SCOPE", "load_base_document", "diff_payload"]

#: The selector that asks ``mlview_graph`` for a comparison instead of a diagram.
DIFF_SCOPE = "diff"


def load_base_document(base: Optional[str], resolve: Callable[[Optional[str]], str]) -> Dict[str, Any]:
    """Read the base graph named by ``base``, or raise ``ValueError`` saying why not.

    ``resolve`` is ``mlview_workspace.resolve_path``, so the base is constrained to the
    project directory exactly like every other path a tool argument carries.
    """
    if not base or not str(base).strip():
        raise ValueError(
            "scope='diff' needs base=<path to an earlier `mlview analyze --json` "
            "document>; there is nothing to compare against without one"
        )
    resolved = resolve(str(base).strip())
    if not os.path.isfile(resolved):
        raise ValueError("base is not a file: %s" % resolved)
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError("base is not readable JSON (%s): %s" % (resolved, exc)) from exc
    if not isinstance(document, dict):
        raise ValueError("base is not an MLView graph document: %s" % resolved)
    if document.get("kind") == "mlview-diff":
        raise ValueError(
            "base is a diff overlay, not a graph: %s -- pass the analyze document "
            "the overlay was computed FROM" % resolved
        )
    if "nodes" not in document or "schemaVersion" not in document:
        raise ValueError("base is not an MLView graph document: %s" % resolved)
    document["__path"] = resolved
    return document


def _counts(summary: Dict[str, Any], key: str) -> Dict[str, int]:
    row = summary.get(key) or {}
    return {name: int(value) for name, value in row.items() if isinstance(value, int)}


def diff_payload(
    head: Dict[str, Any],
    base: Dict[str, Any],
    *,
    diff_documents: Callable[[Any, Any], Dict[str, Any]],
    render_summary: Callable[[Dict[str, Any]], str],
    graph_path: Optional[str] = None,
    limit_bytes: int = LIMIT_BYTES,
) -> Dict[str, Any]:
    """The ``scope="diff"`` result: ``{format, scope, content, summary, note, ...}``.

    ``content`` is ``emit/diff_out.render_summary`` -- the same text ``mlview diff``
    prints -- clipped to the budget with the row counts named in the clip note.  The
    machine-readable counts travel beside it in ``summary`` so a model never has to
    parse the prose to answer "did this PR add a finding".
    """
    base_path = base.pop("__path", None)
    overlay = diff_documents(base, head)
    summary = overlay.get("summary") or {}
    notes = [
        "%s%s: %s"
        % (
            row.get("kind", "note"),
            " (%s)" % row.get("side") if row.get("side") else "",
            row.get("message", ""),
        )
        for row in overlay.get("notes") or []
        if isinstance(row, dict)
    ]
    if not notes:
        notes = [
            "both analyses read their whole workspace, so a removed node is a "
            "removed node"
        ]
    # A diff joins on ids and says nothing about WHY an id is missing; 11.38 C is the
    # complete list of reasons it knows, and it rides in the protected `note` key.
    notes.append(
        "a renamed file or qualname is reported as every node removed plus every "
        "node added: the stable id embeds the path, and no rename detection is done"
    )

    raw = render_summary(overlay)
    clip_note = "... truncated - the full comparison is `mlview diff BASE HEAD`"

    def assemble(content: str, clipped: bool) -> Dict[str, Any]:
        built: Dict[str, Any] = {
            "format": "text",
            "scope": DIFF_SCOPE,
            "content": content,
            "truncated": clipped,
            "summary": {
                "headline": summary.get("headline", ""),
                "nodes": _counts(summary, "nodes"),
                "edges": _counts(summary, "edges"),
                "issues": _counts(summary, "issues"),
            },
            "note": "; ".join(notes),
        }
        if base_path:
            built["basePath"] = base_path
        if graph_path:
            built["graphPath"] = graph_path
        return built

    budget = limit_bytes - 256
    out = assemble(raw, False)
    for _ in range(16):
        content, clipped = clip_text_lines(raw, budget, clip_note)
        out = assemble(content, clipped)
        if payload_size(out) <= limit_bytes:
            return out
        budget = int(budget * 0.75)
    return fit(out, limit_bytes)
