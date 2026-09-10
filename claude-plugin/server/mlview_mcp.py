#!/usr/bin/env python
"""MLView MCP server — static ML-workflow analysis for Claude Code.

Transport is stdio, driven by the official `mcp` Python SDK v2 (CONTRACTS A1).
stdout carries protocol frames only; every log line goes to stderr.

The five tools mirror `CONTRACTS.md` section 5 exactly:

    mlview_analyze       structure + issue digest, and the on-disk graph path
    mlview_issues        the ranked issue list, filterable
    mlview_graph         a compact diagram (mermaid by default) of the whole
                         graph, the stage lanes, one lane, or one neighbourhood
    mlview_explain       one node in full, or one rule code's documentation
    mlview_open_diagram  write and open the self-contained HTML report

Every result is a plain dict of at most 4096 bytes in the encoding the SDK hands
the model (its indented ``content[0].text``, which is larger than the compact
``structuredContent``); the complete document always stays available on disk
behind ``graphPath``.

This module is the bootstrap plus the five tool definitions. The rest lives in
three pure siblings, none of which imports the MCP SDK:

    mlview_workspace.py  path resolution, the write-containment guard, the
                         analysis cache, and rule-doc lookup
    mlview_payloads.py   the per-tool result builders
    mlview_scope.py      the scope selector grammar at the tool boundary, over
                         the analyzer's one projection (`mlview.core.project`)
    mlview_views.py      filtered views of a graph and the shapes they render into
    mlview_budget.py     the 4 KB budget: measuring it and shrinking into it

Run it directly (`python mlview_mcp.py`) or through `.mcp.json`, which puts
``${CLAUDE_PLUGIN_ROOT}/vendor`` on PYTHONPATH so no pip install is needed.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
import webbrowser
from typing import Any, List, Optional

#: The floor `pyproject.toml` declares and the vendored core is written against.
MIN_PYTHON = (3, 10)


def python_version_problem(version, executable):
    """The actionable stderr lines for an interpreter too old to run this server.

    CLEANUP 7: `.mcp.json` has to spell ONE default command, and the only spelling
    that works out of the box on Windows is `python` — which on most macOS and Linux
    boxes is either absent or a Python 2. The failure mode without this check is a
    SyntaxError from deep inside the vendored analyzer, or "MCP server mlview
    failed" with nothing to act on. So the check is here, before the first `mlview`
    import, and the message names BOTH fixes: the `MLVIEW_PYTHON` environment
    variable the config honours (`"command": "${MLVIEW_PYTHON:-python}"`, which is
    the fix for a plugin installed read-only), and the one-field edit.

    Returns an EMPTY list when the interpreter is fine. Pure, so
    `tests/test_server_bootstrap.py` asserts the message without a subprocess.
    """
    if tuple(version[:2]) >= MIN_PYTHON:
        return []
    return [
        "mlview-mcp: this server needs Python %d.%d or newer; %s is %d.%d."
        % (MIN_PYTHON[0], MIN_PYTHON[1], executable or "the interpreter",
           version[0], version[1]),
        "mlview-mcp: set MLVIEW_PYTHON to a Python %d.%d+ interpreter (e.g. "
        'MLVIEW_PYTHON=python3, or an absolute path) and restart Claude Code; '
        '.mcp.json reads "command": "${MLVIEW_PYTHON:-python}". Editing that '
        'field to "python3" works too.' % MIN_PYTHON,
    ]


_VERSION_PROBLEM = python_version_problem(sys.version_info, sys.executable)
if _VERSION_PROBLEM:  # pragma: no cover - needs a <3.10 interpreter to reach
    for _line in _VERSION_PROBLEM:
        print(_line, file=sys.stderr)
    raise SystemExit(1)

# Running the core out of `vendor/` must not litter the *distributed* plugin with
# __pycache__ trees: `claude plugin install` copies the directory verbatim, so a
# stale .pyc compiled from a different revision would ship beside the .py files.
# Set before the first `mlview` import, which is the first thing that would write.
sys.dont_write_bytecode = True

# --------------------------------------------------------------------- bootstrap
# CONTRACTS A1: `<plugin_root>/vendor` is prepended to sys.path and, **as a dev
# fallback when that has no `mlview` package**, `<repo>/analyzer/src`. Exactly one
# of them is added, before `mlview` is imported for the first time.
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_SERVER_DIR)
_REPO_ROOT = os.path.dirname(_PLUGIN_ROOT)


def _prepend_sys_path(candidate: str) -> None:
    """Make ``candidate`` the FIRST entry on ``sys.path``.

    An existing (possibly differently-spelled) copy of the same directory is
    removed first: `pip install -e analyzer` drops `analyzer/src` onto sys.path
    through a .pth file, and a plain "insert if absent" would leave that editable
    checkout ahead of whatever we chose here — which is how the vendored core came
    to be silently shadowed while the banner still claimed "core from vendor".
    """
    real = os.path.normcase(os.path.realpath(candidate))

    def _same(entry: str) -> bool:
        if not entry:  # '' means "the current directory" - never a core we chose
            return False
        try:
            return os.path.normcase(os.path.realpath(entry)) == real
        except OSError:  # pragma: no cover - an unresolvable entry is not a match
            return False

    sys.path[:] = [p for p in sys.path if not _same(p)]
    sys.path.insert(0, candidate)


def _bootstrap_sys_path() -> str:
    """Put exactly one core on the front of ``sys.path``; return which one.

    First match wins and the function returns immediately: adding both would put
    the dev tree ahead of the vendored copy (the last ``insert(0, ...)`` wins),
    which makes the vendor-completeness test and parity gate 1 vacuous — a gutted
    or mutated `vendor/` would still ship green.
    """
    vendor = os.path.join(_PLUGIN_ROOT, "vendor")
    dev = os.path.join(_REPO_ROOT, "analyzer", "src")
    for candidate, name in ((vendor, "vendor"), (dev, "analyzer/src")):
        if os.path.isdir(os.path.join(candidate, "mlview")):
            _prepend_sys_path(candidate)
            return name
    return "installed"


_CORE_SOURCE = _bootstrap_sys_path()

if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

import mlview_diff as diffs  # noqa: E402  (VIEW-08: the scope='diff' projection)
import mlview_payloads as payloads  # noqa: E402  (needs the sys.path bootstrap)
import mlview_scope as scopes  # noqa: E402  (the section 11.1 selector grammar)
from mlview_workspace import (  # noqa: E402  (imports the core, so bootstrap first)
    RULE_DOC_ROOTS as _RULE_DOC_ROOTS,
    data_dir,
    load_attributed,
    load_graph,
    load_graph_or_file,
    project_dir,
    read_source as _read_source,
    resolve_out,
    resolve_path,
    rule_doc as _rule_doc,
    rule_spec as _rule_spec,
)

from mlview.api import (  # noqa: E402
    digest,
    render_html,
    render_mermaid,
    render_text,
)
from mlview.core.diff import diff_documents  # noqa: E402  (VIEW-08, section 11.38)
from mlview.emit.diff_out import render_summary as render_diff_summary  # noqa: E402
from mlview.version import __version__ as CORE_VERSION  # noqa: E402

logging.basicConfig(
    stream=sys.stderr,
    level=os.environ.get("MLVIEW_LOG_LEVEL", "INFO"),
    format="mlview-mcp: %(levelname)s %(message)s",
)
log = logging.getLogger("mlview.mcp")

INSTRUCTIONS = (
    "Static ML-workflow analysis for Python (PyTorch / scikit-learn). Nothing is "
    "imported or executed. Call mlview_analyze FIRST to recover the pipeline "
    "structure before reading source files; then mlview_issues for the findings, "
    "mlview_graph for a diagram you can reason about in the terminal, "
    "mlview_explain for one node or one rule code, and mlview_open_diagram when "
    "the user wants to look at it."
)


# ------------------------------------------------------------------------ server
try:
    from mcp.server.mcpserver import MCPServer  # mcp >= 2
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - mcp 1.x fallback
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore
    try:
        from mcp.server.fastmcp.exceptions import ToolError  # type: ignore
    except ImportError:
        ToolError = ValueError  # type: ignore

server = MCPServer("mlview", instructions=INSTRUCTIONS, version=CORE_VERSION)


def visible_errors(func):
    """Re-raise a caller mistake as ``ToolError`` so its text reaches the model.

    The SDK deliberately swallows the text of an unexpected exception (a crash
    must not leak server internals), so a plain ``ValueError`` — which is what the
    pure payload builders raise for "no such node", "no such path" — would reach
    Claude as the useless "Error executing tool mlview_analyze". Anything the
    caller can fix by retrying differently is re-raised as ``ToolError``, whose
    message is preserved verbatim in the ``isError`` result.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ToolError:
            raise
        except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


@server.tool(structured_output=True)
@visible_errors
def mlview_analyze(
    path: Optional[str] = None,
    framework: str = "auto",
    maxNodes: int = 400,
    includeHtml: bool = False,
    scope: Optional[str] = None,
    depth: Optional[int] = None,
    includeNotebooks: bool = False,
) -> dict[str, Any]:
    """Statically analyze the Python ML code under `path` and return the pipeline structure.

    CALL THIS FIRST, before reading source files, whenever the user asks what a
    training script does, how the pipeline is wired, or what is wrong with it:
    the digest tells you which stages exist, which frameworks are in play and
    which issues fired, so subsequent reads are targeted instead of linear.

    Nothing is imported or executed and neither torch nor scikit-learn needs to
    be installed — the analysis is pure `ast` work on source text.

    PREFER A DIRECTORY OVER A SINGLE FILE. Four rules — MLV301, MLV302, MLV401 and
    MLV501 — need a sibling module to fire at all, so analyzing `train.py` alone
    reports fewer findings than analyzing the directory that contains it (measured:
    3 against 7). When the caller names one file, the result carries a `coverage`
    row of kind `single_file_analysis` whose `codes` name the rules that could not
    run; quote those codes to the user rather than reporting the shorter list as a
    clean file. The same applies to `untagged_dataflow`, which says a key argument
    could not be traced, so the leakage rules could not check it. Analyze the
    directory and pass
    `scope="file:<name>.py"` when the question really is about one file: that
    recovers the cross-file rules and still answers about the file.

    Args:
        path: file or directory, absolute or relative to the project. Defaults to
            the whole project directory. A DIRECTORY is the honest default — see
            the single-file caveat above.
        framework: "auto" (default), or one of torch, sklearn, keras, hf, lightning
            to restrict the extractors.
        maxNodes: graph cap; the result sets truncated=true when it is exceeded.
        includeHtml: also write the self-contained HTML report and return
            reportPath (it is NOT opened; use mlview_open_diagram for that).
        scope: optional — narrow the DIGEST to one part of the pipeline, e.g.
            "concern:evaluation", "unit:SmallCNN", "stage:train", "file:data.py",
            "node:<nodeId>", or "all" for everything. Call mlview_graph with
            scope="units" first if you need to discover the names. The counts
            then describe the scope, not the project, and the payload says so —
            omit it when the question is about the project as a whole.
        depth: optional — 0, 1 or 2 boundary hops around the scope. Defaults per
            kind (1 for unit/node, 0 for stage/file/concern).
        includeNotebooks: also analyze `.ipynb` files (default false, which is
            byte-identical to the behaviour before notebooks existed). Set it
            whenever the question is about a notebook, or whenever the result
            reports `notebooksSkipped > 0` and the user has not said to ignore
            them — a green answer for a project whose code lives in notebooks is
            a clean bill of health from a run that read none of it. Each notebook
            is converted to one generated module under `.mlview/notebooks/`, so
            locations name THAT file; the `notebook_analyzed` note names the
            notebook and the cell mapping, and cell execution order is not
            recoverable from the file, so order-sensitive findings (MLV101,
            MLV203, MLV209) in an out-of-order notebook are de-rated and say so.

    Returns a <=4 KB digest: schemaVersion, root, filesAnalyzed, filesFailed,
    notebooksSkipped, frameworks, stats{nodes,edges,issues}, lanes (one row per
    detected stage), topIssues (<=10), graphPath, and reportPath when requested;
    with a scope, also scope{spec,kind,target,depth,nodesInScope,nodesTotal}.
    The COMPLETE graph document is written to graphPath — read that file when you
    need detail the digest omits. graphPath always points at the FULL document
    even for a scoped call, so widening back costs nothing.
    """
    loaded = load_graph(path, framework=framework, max_nodes=maxNodes,
                        include_notebooks=bool(includeNotebooks))
    graph = loaded["graph"]
    # The cache is never keyed on the scope: the FULL document is analyzed and
    # stored, then projected (CONTRACTS 11.10).
    spec, view, notes, hops = scopes.apply_scope(graph, scope, depth)
    report_path = None
    if includeHtml:
        # Through the same containment helper as mlview_open_diagram, so there is
        # exactly one place that decides where this server is allowed to write.
        report_path = render_html(graph, resolve_out(None), scope=spec, depth=hops)
    return payloads.analyze_payload(
        digest(view, limit_bytes=3200), loaded["graphPath"], report_path,
        graph=graph, scope=spec, extra_notes=notes,
    )


@server.tool(structured_output=True)
@visible_errors
def mlview_issues(
    path: Optional[str] = None,
    minSeverity: str = "low",
    minConfidence: float = 0.0,
    code: Optional[List[str]] = None,
    limit: int = 20,
    scope: Optional[str] = None,
    depth: Optional[int] = None,
    groupBy: Optional[str] = None,
    changedSince: Optional[str] = None,
    baseline: Optional[str] = None,
    includeNotebooks: bool = False,
) -> dict[str, Any]:
    """List the ML correctness and hygiene issues detected under `path`.

    Use this when asked what is wrong with the training code, whether there is
    data leakage, or before proposing a fix — every row carries a rule code, a
    severity, a concrete message, a one-line fix hint, and file:line you can cite
    or open. Related locations (the split site, the backward site, ...) come back
    as `related` so a multi-site finding can be followed end to end.

    Suppressed issues (`# mlview: ignore[MLV201]`, `.mlview.toml`) are never
    listed; `suppressedCount` reports how many were withheld.

    Args:
        path: file or directory; defaults to the whole project directory.
        minSeverity: "low" (default), "medium" or "high". Any other value is
            rejected with an error rather than quietly treated as "low".
        minConfidence: 0.0-1.0 floor on the rule's confidence.
        code: restrict to specific rule codes, e.g. ["MLV201", "MLV301"].
        limit: maximum rows to return (default 20).
        scope: optional — list only the findings inside one part of the pipeline,
            e.g. "concern:evaluation", "unit:train.train", "stage:train",
            "file:model.py", "node:<nodeId>", or "all". A finding is kept when it
            is anchored INSIDE the scope, so a scoped count is never a statement
            about the project — omit it when asked "what is wrong with this code".
        depth: optional — 0, 1 or 2 boundary hops around the scope; it widens the
            picture, never the findings (only core anchors retain an issue).
        groupBy: optional — "rule", "file" or "severity". Folds the findings into
            one row per key with an occurrence count, the worst severity and
            confidence in the group and up to three example `file:line` sites, and
            returns `groups` INSTEAD of `issues`. Use it on any workspace that
            answers with more than about twenty findings: a legacy repo is
            typically eleven distinct rules repeated ten times each, and the flat
            list spends the whole 4 KB budget on the repeats. Grouping folds the
            rows, it never filters them — the counts still describe every finding
            that passed minSeverity / minConfidence / code / scope.

        changedSince: optional — a git revision (`HEAD`, `origin/main`, a SHA).
            The WHOLE project is analyzed either way; the findings are then
            attributed against `git diff -M --unified=0 <rev>` and only the ones
            that touch the change are listed, each row carrying `change`: `new`
            (inside an added hunk) or `touched` (a changed file, or a related
            location such as the split site inside one). This is the answer to
            "what did this PR introduce" on a repo that already has findings —
            never use it to answer "is this project clean". When git is absent,
            the directory is not a repo, or the revision does not exist, every
            finding is listed and the `note` says so.
        baseline: optional — path to a `mlview baseline write` file. Findings it
            already records are marked and excluded from the counts (they come
            back as `baselinedCount`), so only what is NEW since the baseline is
            listed. Entries that no longer match any finding are reported in the
            `note` rather than silently forgiven.
        includeNotebooks: also analyze `.ipynb` files (default false). Pass the
            SAME value you passed to mlview_analyze: with it off, no finding
            inside a notebook is listed at all, and a short list from a run that
            read none of the notebooks is not a clean project. It is honoured with
            changedSince and baseline too — the notebooks are read and attributed
            like any other file. One limit, and the `note` says it whenever it
            bites: a notebook finding is anchored in the generated module
            `.mlview/notebooks/<name>.py`, which git does not track, so
            `changedSince` cannot place it inside a diff hunk and the changed-only
            filter drops it. Use `baseline`, or omit `changedSince`, to see
            notebook findings.

    Returns countBySeverity, suppressedCount and issues[] (or groups[] under
    groupBy); the payload is capped at 4 KB, so a large workspace comes back
    truncated with the full list in the graph document that mlview_analyze wrote.
    """
    if changedSince or baseline:
        loaded = load_attributed(path, changedSince, baseline,
                                 include_notebooks=bool(includeNotebooks))
    else:
        loaded = load_graph(path, include_notebooks=bool(includeNotebooks))
    spec, view, notes, _hops = scopes.apply_scope(loaded["graph"], scope, depth)
    return payloads.issues_payload(
        view,
        min_severity=minSeverity,
        min_confidence=float(minConfidence or 0.0),
        codes=code,
        limit=int(limit),
        graph_path=loaded["graphPath"],
        scope=spec,
        extra_notes=list(loaded.get("notes") or ()) + list(notes),
        group_by=groupBy,
    )


@server.tool(structured_output=True)
@visible_errors
def mlview_graph(
    path: Optional[str] = None,
    format: str = "mermaid",
    scope: Optional[str] = None,
    depth: Optional[int] = None,
    base: Optional[str] = None,
) -> dict[str, Any]:
    """Render the workflow graph as a compact diagram you can read in the terminal.

    Mermaid is the default because it is the cheapest faithful picture of the
    pipeline: stage lanes as subgraphs, units nested inside them, typed edges
    between them. Use `scope` to keep the payload small and the answer focused
    rather than pulling the entire graph.

    Args:
        path: file or directory; defaults to the whole project directory.
        format: "mermaid" (default), "text" (an ASCII lane view) or "json" (an
            id/label/file/line index of nodes and edges).
        scope: omit for the whole graph, or pass one of --
            "stages"          one row per stage lane with node counts and worst
                              severity. The ONLY project-wide lane statement.
            "units"           the catalogue of CONTAINER units (classes, functions,
                              loops) as {nodeId, label, qualname, file, line,
                              nodeCount, maxSeverity}, biggest first. Call this to
                              DISCOVER what can be scoped to; it costs no analysis.
                              It is a menu, not the set of legal targets: an op
                              (a call site such as "train_test_split") resolves
                              under unit: but is never listed, and rows are shed
                              to fit 4 KB -- when that happens the `note` says
                              "showing N of M" and points at --list-scopes. Treat
                              a name you cannot see here as untested, not absent.
            "all"             the whole graph, spelled explicitly.
            "stage:<id>"      one lane: config, data, preprocess, model, objective,
                              train, eval or deliver.
            "unit:<name>"     one class, function or loop -- a qualname
                              ("train.train"), a bare name ("SmallCNN") or a node
                              id. Resolves to every match, and says when it is
                              ambiguous.
            "file:<path.py>"  everything the analyzer found in one file
                              (workspace-relative, forward slashes, or a basename).
            "concern:<name>"  config | data | optimization | evaluation -- the four
                              presets that partition the eight stages (aliases:
                              setup, preprocessing, dataset, training, inference).
            "node:<nodeId>"   one node and its neighbourhood.
            "pipeline:<entry>" MLV-P12 -- everything one workspace entrypoint
                              reaches over data and call edges plus containment:
                              "pipeline:exp03/train.py", or its bare basename.
                              This is the unit a practitioner thinks in on a repo
                              with several training scripts. A node reachable
                              from two entrypoints is SHARED and comes back as
                              viewRole "context", never as this pipeline's own,
                              and a finding anchored only on a shared node is
                              reported as outside the view. Call scope="stages"
                              or read `pipelines` in the graph document for the
                              entrypoints; a target that is not one of them is an
                              unknown_pipeline error listing the real ones.
            "symbol:<name>"   an alias for "unit:<name>".
            "diff"            VIEW-08 -- NOT a diagram: compare this analysis
                              against an earlier one and report what changed.
                              REQUIRES `base`; `format` and `depth` are ignored.
                              Returns the `mlview diff` summary in `content`
                              plus machine-readable `summary` {headline, nodes,
                              edges, issues}. `issues.new` is the number a PR
                              comment needs; `fixed` and `persisting` are the
                              rest of that sentence.
        base: the earlier `mlview analyze --json` document -- for scope="diff",
            and meaningless without it. Anything that is not an MLView graph,
            a diff overlay included, is an error naming the file rather than an
            empty comparison, because "0 changes" is the most dangerous wrong
            answer here. ALWAYS read the returned `note` before quoting the
            counts: a `removed` node can also mean not-analyzed, truncated,
            projected away, a different workspace root or a different analyzer
            version, and a rename is every node removed plus every node added.
        depth: 0, 1 or 2 boundary hops around the scope. Omit it for the per-kind
            default: 1 for unit/node (a point, so its interface is the answer), 0
            for stage/file/concern (already a region). Ignored by "stages",
            "units" and "all".

    An unrecognized `format`, or a `scope` outside the grammar above (including a
    stage id outside the eight canonical stages, a concern that is not one of the
    four, or a node id this graph does not contain), comes back as an error naming
    the accepted values -- never as a silently substituted default. A stage that
    exists in the contract but was not detected in this project returns an empty
    diagram plus a `note` saying so; that absence is a finding.

    Every projected result carries a `note` saying it is a filtered view: its
    counts describe the scope, not the project. Call scope="stages" when the
    question is about the project as a whole.

    Returns {format, scope, content, graphPath}. Content is clipped to fit the
    4 KB budget; narrow the scope, or read graphPath, if it comes back truncated.
    """
    loaded = load_graph(path)
    if (scope or "").strip() == diffs.DIFF_SCOPE:
        # VIEW-08: a comparison is another projection of the same graph, so it is a
        # scope rather than a sixth tool. The diff itself is the ANALYZER's
        # (mlview.core.diff, section 11.38) - this server never computes one.
        return diffs.diff_payload(
            loaded["graph"],
            diffs.load_base_document(base, resolve_path),
            diff_documents=diff_documents,
            render_summary=render_diff_summary,
            graph_path=loaded["graphPath"],
        )
    return payloads.graph_payload(
        loaded["graph"],
        fmt=format,
        scope=scope,
        depth=depth,
        renderers={"mermaid": render_mermaid, "text": render_text},
        graph_path=loaded["graphPath"],
    )


@server.tool(structured_output=True)
@visible_errors
def mlview_explain(
    nodeId: Optional[str] = None,
    code: Optional[str] = None,
    path: Optional[str] = None,
    graphPath: Optional[str] = None,
) -> dict[str, Any]:
    """Explain one graph node in full, or one rule code.

    With `nodeId` (an "n:..." id from mlview_analyze, mlview_issues or
    mlview_graph): the node record, its incoming and outgoing edges with the
    variable names on them, the issues attached to it, the stage evidence that
    says WHY it landed in that lane, and up to 60 lines of the actual source.
    That is usually enough to answer a question without a separate Read.

    With `code` (e.g. "MLV201"): the offline rule documentation — what it detects,
    why it matters, the known false-positive traps, and the fix.

    Args:
        nodeId: the node to explain. Exactly one of nodeId or code is required.
        code: the rule code to document, e.g. "MLV201".
        path: file or directory to analyze when no graphPath is given.
        graphPath: reuse the graph document mlview_analyze already wrote — faster
            and guaranteed to match the ids you were handed.
    """
    if not nodeId and not code:
        raise ValueError("mlview_explain needs either nodeId (an 'n:...' id) or code (e.g. 'MLV201')")
    if code and not nodeId:
        normalized = str(code).strip().upper()
        doc = _rule_doc(normalized)
        return payloads.explain_rule_payload(
            normalized, doc["text"], _rule_spec(normalized), doc["path"]
        )

    loaded = load_graph_or_file(path, graphPath)
    graph = loaded["graph"]
    node = next((n for n in graph.get("nodes", []) if n.get("id") == nodeId), None)
    source = _read_source((node or {}).get("loc", {}).get("absFile")) if node else None
    return payloads.explain_node_payload(
        graph, str(nodeId), source_lines=source, graph_path=loaded["graphPath"]
    )


@server.tool(structured_output=True)
@visible_errors
def mlview_open_diagram(
    path: Optional[str] = None,
    graphPath: Optional[str] = None,
    out: Optional[str] = None,
    scope: Optional[str] = None,
    depth: Optional[int] = None,
) -> dict[str, Any]:
    """Write the self-contained HTML diagram report and open it in the browser.

    This is the visual surface in a terminal host: one offline file with the
    interactive diagram, the stage lanes and every issue marker. Call it when the
    user asks to SEE the pipeline, wants a picture, or after an analysis they
    want to look at rather than read.

    Args:
        path: file or directory to analyze; defaults to the project directory.
        graphPath: reuse an existing graph document instead of re-analyzing.
        out: where to write the HTML; defaults to <project>/.mlview/report.html.
        scope: optional -- open the report AT one part of the pipeline, e.g.
            "unit:train_test_split", "concern:optimization", "stage:train". Same
            grammar as mlview_graph. The file still embeds the WHOLE graph, so the
            reader can widen or clear the scope in the report's own toolbar.
        depth: optional -- 0, 1 or 2 boundary hops (per-kind default when omitted).

    Returns {reportPath, reportUrl, opened, exportHint}. `opened` is false when
    MLVIEW_NO_OPEN=1 is set or no browser could be launched — the file is still
    written, so tell the user the path.

    SVG and PNG export is a VIEWER feature, not an MCP one (VIEW-07). This server
    writes HTML and nothing else: it cannot rasterize or serialize a diagram,
    because the picture's geometry only exists once the viewer has laid the graph
    out. So when the user asks for an SVG, a PNG or "an image for the PR", hand
    them `reportPath` and say where the picture comes from — the report's own
    export menu, or `MLView: Export Diagram as SVG` / `... as PNG` in VS Code.
    `exportHint` carries that sentence. Never claim a file this tool did not write.
    """
    loaded = load_graph_or_file(path, graphPath)
    target = resolve_out(out)
    # Validated BEFORE ~270 KB is written and handed to the browser: a mistyped
    # selector must be a refusal, not a report that quietly shows everything.
    spec, _view, notes, hops = scopes.apply_scope(loaded["graph"], scope, depth)
    report_path = render_html(loaded["graph"], target, scope=spec, depth=hops)
    report_url = "file:///" + report_path.replace("\\", "/").lstrip("/")

    if os.environ.get("MLVIEW_NO_OPEN") == "1":
        return payloads.open_diagram_payload(
            report_path, report_url, False,
            note="; ".join(
                notes + ["MLVIEW_NO_OPEN=1 — the report was written but not launched."]
            ),
            scope=spec,
        )

    opened, note = True, None
    try:
        starter = getattr(os, "startfile", None)
        if starter is not None:
            starter(report_path)  # Windows
        else:
            opened = bool(webbrowser.open(report_url))
            if not opened:
                note = "No browser could be launched; open the file manually."
    except OSError as exc:
        opened, note = False, "Could not open the report automatically: %s" % exc
        log.warning("open failed: %s", exc)
    combined = "; ".join(notes + ([note] if note else [])) or None
    return payloads.open_diagram_payload(
        report_path, report_url, opened, combined, scope=spec
    )


TOOL_NAMES = (
    "mlview_analyze", "mlview_issues", "mlview_graph", "mlview_explain",
    "mlview_open_diagram",
)


def main() -> None:
    log.info(
        "MLView MCP server %s starting (core from %s, project=%s)",
        CORE_VERSION, _CORE_SOURCE, project_dir(),
    )
    server.run("stdio")


if __name__ == "__main__":
    main()
