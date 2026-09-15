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
           "notebook_dropped_note", "ADOPT_NOTE_KINDS", "NOTEBOOK_MODULE_DIR"]

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
    include_notebooks: bool = False,
) -> Tuple[Dict[str, Any], List[str]]:
    """Analyze the WHOLE project, then attribute. Returns `(document, notes)`.

    Whole-project first is not an implementation detail: a per-file or per-diff
    analysis loses the cross-file rules (COVERAGE measured 3 findings where the
    directory yields 7), so CI-ADOPT analyses everything and narrows afterwards.

    `include_notebooks` is part of "the whole project" — HOST-5. It used to stop at
    this boundary: `mlview_issues` accepted `includeNotebooks` and then dropped it
    whenever `changedSince` or `baseline` was also passed, so a caller asking "what
    did this PR introduce, notebooks included" got an answer from a run that had not
    opened one notebook, and nothing in the payload said so. Attribution never
    required that — the CLI takes `--include-notebooks --changed-since` together —
    so the flag is threaded here and a notebook is analyzed, then attributed, like
    any other file.

    `changed_only` is always True here because that is what the parameter MEANS at
    this boundary — an agent that wanted every finding simply omits `changedSince`.
    Findings that merely sit in a changed file, or whose related location is inside
    an added hunk, are kept and marked `touched`; only `existing` is dropped, and
    the count that was dropped comes back in the notes.
    """
    from mlview.api import AnalyzeOptions, analyze  # noqa: PLC0415
    from mlview_workspace import normalize_framework  # noqa: PLC0415 - sibling

    # The same guard `load_graph` applies, at the second (and only other) place in
    # this server that builds `AnalyzeOptions`. It is not defence in depth for its
    # own sake: `rules.registry._applies` silently drops every rule that declares a
    # framework when the filter names none of them, so an unvalidated string here
    # would answer "what did this PR introduce" with a stripped rule set and no
    # note. Both constructions going through one vocabulary is what
    # `test_argument_bounds.py` asserts statically, over every module in this
    # directory that builds `AnalyzeOptions`.
    graph = analyze(
        AnalyzeOptions(
            paths=(resolved,),
            framework=normalize_framework(framework),
            max_nodes=int(max_nodes),
            include_notebooks=bool(include_notebooks),
        )
    )
    cli_glue = _adopt()
    notes: List[str] = []
    if cli_glue is None:
        return graph.to_dict(), [unsupported_note(changed_since, baseline)]

    before = set(id(d) for d in graph.diagnostics)
    notebook_issues = _notebook_issue_ids(graph)
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
    dropped = notebook_dropped_note(graph, notebook_issues)
    if dropped:
        notes.append(dropped)
    return doc, notes


# ------------------------------------------------------- notebooks under attribution
#: The one directory a notebook's generated module can live in, used only to name
#: it in the note. The *set* of modules is read off the graph, never guessed.
NOTEBOOK_MODULE_DIR = ".mlview/notebooks/"


def _notebook_modules(graph) -> Dict[str, str]:
    """`{generated module path: source .ipynb}` for every notebook in the graph.

    Read off `Node.attrs` because CONTRACTS 11.29 N6 is what puts the mapping
    there; the `.mlview/notebooks/` path shape is a consequence, not the evidence.
    """
    modules: Dict[str, str] = {}
    for node in getattr(graph, "nodes", ()) or ():
        notebook = (getattr(node, "attrs", None) or {}).get("notebook")
        loc = getattr(node, "loc", None)
        module = getattr(loc, "file", "") or ""
        if notebook and module:
            modules.setdefault(module, str(notebook))
    return modules


def _notebook_issue_ids(graph) -> Dict[str, str]:
    """`{issue id: source .ipynb}` for the findings anchored inside a notebook."""
    modules = _notebook_modules(graph)
    if not modules:
        return {}
    found: Dict[str, str] = {}
    for issue in getattr(graph, "issues", ()) or ():
        module = getattr(getattr(issue, "loc", None), "file", "") or ""
        if module in modules:
            found[getattr(issue, "id", "")] = modules[module]
    return found


def notebook_dropped_note(graph, notebook_issues: Dict[str, str]) -> Optional[str]:
    """Say out loud that attribution dropped every finding inside a notebook.

    HOST-5, the half that threading the flag does not fix. `includeNotebooks` now
    reaches the analysis under `changedSince`, so the notebooks really are read —
    but a notebook finding is anchored in the **generated module**
    (`.mlview/notebooks/<name>.py`), and git has never heard of that path. So
    `mlview.adopt` classifies it `existing` no matter how new the `.ipynb` is, and
    `--changed-only` (always on at this boundary) drops it. Measured, not assumed:
    a freshly `git add`ed `leak.ipynb` yields 3 findings with `--changed-since HEAD`
    and **0** with `--changed-only`, in the CLI as much as here.

    Reporting nothing would recreate the exact defect HOST-5 names — a short list
    from a run that read the notebooks and then silently discarded everything they
    said. So the drop is counted (before vs after attribution, by issue id) and
    stated with the numbers and the way out.
    """
    if not notebook_issues:
        return None
    survived = {getattr(i, "id", "") for i in getattr(graph, "issues", ()) or ()}
    dropped = [nb for issue_id, nb in notebook_issues.items() if issue_id not in survived]
    if not dropped:
        return None
    notebooks = sorted(set(dropped))
    return (
        "includeNotebooks was honoured, but attribution dropped %d of the %d "
        "finding(s) inside %d notebook(s) (%s). A notebook finding is anchored in the generated "
        "module `%s<name>.py`, which git does not track, so no diff can ever place "
        "it inside a changed hunk and the changed-only filter cannot keep it — "
        "this is NOT a statement that the notebooks are clean. Call mlview_issues "
        "again without changedSince (or with baseline instead, which does not filter "
        "by hunk) to see them."
        % (len(dropped), len(notebook_issues), len(notebooks),
           ", ".join(notebooks[:3]) + (", …" if len(notebooks) > 3 else ""),
           NOTEBOOK_MODULE_DIR)
    )


def adoption_notes(doc: Dict[str, Any]) -> List[str]:
    """The adoption diagnostics already inside a document, for a cached read."""
    return [
        str(d.get("message", ""))
        for d in (doc.get("diagnostics") or [])
        if d.get("kind") in ADOPT_NOTE_KINDS
    ]
