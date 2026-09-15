"""The analysis pipeline: discover -> parse -> IR -> graph -> rules -> emit.

`api.analyze()` is a thin wrapper over `run()`. Everything here is pure with
respect to the filesystem apart from reading the analyzed source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple

from ..ingest.discover import discover, normalize_path
from ..ingest import notebook as notebook_mod
from ..ingest.parse import parse_all, parse_bytes, parse_file, read_bytes
from ..ir.build_ir import DEFAULT_DATAFLOW, build_workspace
from ..rules import Suppressor, cross_file_codes, load_config, run_all
from ..rules import confidence as confidence_mod
from ..rules.context import GraphContext
from . import cache as cache_mod
from . import config as config_mod
from . import relevance as relevance_mod
from .build import GraphBuilder
from .coverage import (note_unconfirmed_train_loops, note_untraced_sites,
                       single_file_diagnostic)
from .unresolved import unresolved_callee_diagnostics
from .graph import Diagnostic, MLGraph, SEVERITY_RANK
from .rollup import apply_node_budget
from .progress import safe_call

__all__ = ["AnalyzeOptions", "run", "AnalysisResult", "drop_orphan_ghosts",
           "DEFAULT_RELEVANCE", "annotate_notebook_nodes"]

#: PERF-03. The shipped default for `--relevance`, and since the Sprint-5
#: re-baseline (CONTRACTS 11.39) it is `ml`: the IR is built only for files
#: within `relevance_hops` import hops of a framework import, and the count of
#: what was set aside is stated on the document.
#:
#: ROADMAP's condition for the flip was that `tools/accuracy.py` be identical
#: in both modes. It **is** - byte-identical over the whole ANA-12 corpus - and
#: `tools/perf_equiv.py --expect-same` is byte-identical on all three corpora
#: with the new default in force. 11.28 A11 held the default at `all` for a
#: second, measured reason: on workspaces too small for the filter to save
#: anything it still moves four analyzer gates, because a handful of files with
#: one non-framework module is exactly the shape where "set aside" becomes
#: visible. 11.39 moves those four deliberately and records what each of them
#: now says. `--relevance all` and `MLVIEW_NO_CACHE=1` restore the old paths
#: exactly; `all` still derives no facts and consults no cache.
DEFAULT_RELEVANCE = "ml"


@dataclass(frozen=True)
class AnalyzeOptions:
    """FROZEN surface (CONTRACTS section 3)."""

    paths: Tuple[str, ...]
    include: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()
    max_files: int = 500
    max_nodes: int = 400
    framework: str = "auto"
    min_severity: str = "low"
    min_confidence: float = 0.0
    config_path: Optional[str] = None
    strict: bool = False
    #: CONTRACTS 11.6 - appended last, both defaulted, so positional
    #: construction, `frozen=True` and hashability are unchanged. `run()`
    #: ignores them: a scope is a **document-level projection** applied by
    #: `api.analyze_to_dict()`, never a smaller analysis.
    scope: Optional[str] = None
    depth: Optional[int] = None
    #: H3 - an optional `(done, total, relpath)` sink called once per analyzed
    #: file. Appended last and defaulted to `None`, so the frozen surface is
    #: unchanged and `analyze()` still performs no I/O of its own: the CLI
    #: passes `core.progress.ProgressWriter()` for `--progress-json`, an
    #: in-process host passes its own callable, and nobody else pays anything.
    progress: Optional[Callable[[int, int, str], None]] = None
    #: PERF-03 / CACHE (CONTRACTS 11.28) - three more appended last, all
    #: defaulted, so positional construction, `frozen=True` and hashability are
    #: unchanged. `relevance="all"` is the identity; `cache=None` means "ask
    #: the environment", which is on unless `MLVIEW_NO_CACHE=1`, and neither
    #: can change what the analysis concludes - only how much of the workspace
    #: it looks at, and how fast it gets there.
    relevance: str = DEFAULT_RELEVANCE
    relevance_hops: int = relevance_mod.DEFAULT_HOPS
    cache: Optional[bool] = None
    #: NB (CONTRACTS 11.29) - appended last and False by default, so positional
    #: construction, `frozen=True` and hashability are unchanged and a run that
    #: does not set it emits byte-identical bytes. True (or `[paths] notebooks
    #: = true`) turns `.ipynb` files from a counted skip into analyzed,
    #: generated Python modules under `<root>/.mlview/notebooks/`.
    include_notebooks: bool = False
    #: DATAFLOW-IP (CONTRACTS 11.36) - appended last, so positional
    #: construction, `frozen=True` and hashability are unchanged. `ip` runs the
    #: interprocedural summary pass (`ir.summaries`): constructor arguments,
    #: return values and method arguments carry value tags across the object
    #: boundary, every hop is de-rated by an explicit evidence weight, and no
    #: cross-object finding may reach `certain`.
    #:
    #: R1 makes `ip` the default, and this field reads `DEFAULT_DATAFLOW`
    #: rather than naming a mode, so the constant in `ir.build_ir` stays the
    #: one place the product default is written down. A host that wants the
    #: narrower analysis passes `dataflow="local"` explicitly.
    dataflow: str = DEFAULT_DATAFLOW


@dataclass
class AnalysisResult:
    """The graph plus the internals the CLI and tests want."""

    graph: MLGraph
    workspace: object = None
    builder: object = None
    context: object = None
    empty: bool = False
    #: CACHE / PERF-03: what the parse cache and the prefilter did on this run.
    #: `stats` is schema-frozen and may not carry either, so they ride here and
    #: on the log line; `api.digest(..., cached=...)` is how a host publishes
    #: the first of them to a model.
    cache: Optional[object] = None
    relevance: Optional[object] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(options: AnalyzeOptions) -> AnalysisResult:
    """Analyze `options.paths` and return the complete graph."""
    started = time.perf_counter()
    # CFG-ONE (11.37): resolve the file **before** discovery, against the root
    # discovery is itself going to report, so `[paths] include/exclude` narrow
    # the first walk rather than a second one and `[analysis]` is in force for
    # the whole run. `apply` leaves every option the caller set alone.
    config = load_config(options.config_path, config_mod.probe_root(options.paths))
    options = config_mod.apply(options, config)
    excludes = tuple(options.exclude) + tuple(config.excludes)
    want_notebooks = bool(options.include_notebooks or config.notebooks)
    found = discover(options.paths, include=options.include, exclude=excludes,
                     max_files=options.max_files, notebooks=want_notebooks)
    # a config file inside the discovered root takes effect too. `probe_root`
    # is `discover`'s own root function, so this second read finds a file only
    # when the two disagree - which they do not for any path shape shipped.
    if config.path is None:
        # CFG-CONFIG-WARNING-DROPPED (11.37 A3/C4): the first read decided
        # nothing, but it may still have had something to *say* - the measured
        # case is `--config pyproject.toml` on a file with no [tool.mlview]
        # table, which `load_config` reports as a warning with `path=None`.
        # Rebinding `config` here used to throw that warning away, so an
        # explicit --config that applied nothing also said nothing: exactly the
        # silent-fallback failure CFG-ONE exists to end.
        first_warnings = list(config.warnings)
        config = load_config(None, found.root)
        options = config_mod.apply(options, config)
        carried = [w for w in first_warnings if w not in config.warnings]
        if carried:
            config.warnings = carried + list(config.warnings)
        # NB: `[paths] notebooks` lives in that same file, so the second read
        # can turn notebooks on as well as add excludes.
        reread = bool(options.include_notebooks or config.notebooks)
        if config.excludes or reread != want_notebooks:
            want_notebooks = reread
            found = discover(options.paths, include=options.include,
                             exclude=excludes + tuple(config.excludes),
                             max_files=options.max_files,
                             notebooks=want_notebooks)

    diagnostics: List[Diagnostic] = []
    parsed_files, parse_failures, relevance, cache_report = _ingest(
        found, options, _explicit_files(options.paths, found.root))
    failures = len(parse_failures)
    for bad in parse_failures:
        diagnostics.append(Diagnostic(kind="parse_error", message=bad.message,
                                      file=bad.relpath, line=bad.line))

    # NB: notebooks are ingested here, after the Python files and before the
    # "nothing parsed" exit, so a workspace that is *only* notebooks is a real
    # analysis rather than an empty graph.
    notebook_maps, notebooks_skipped = _ingest_notebooks(
        found, want_notebooks, parsed_files, diagnostics)
    if found.file_cap_hit:
        diagnostics.append(Diagnostic(
            kind="truncated",
            message="Discovery capped at %d files (%d found); raise --max-files to widen."
                    % (options.max_files, found.total_found),
            count=found.total_found - len(found.files)))
    for missing in found.missing:
        diagnostics.append(Diagnostic(kind="config_warning",
                                      message="path does not exist: %s" % missing))
    for warning in config.warnings:
        diagnostics.append(Diagnostic(kind="config_warning", message=warning))
    narrowing = relevance_mod.relevance_diagnostic(relevance)
    if narrowing is not None:
        diagnostics.append(narrowing)

    if not parsed_files:
        graph = MLGraph(root=found.root)
        graph.diagnostics = diagnostics
        graph.filesFailed = failures
        graph.notebooksSkipped = notebooks_skipped
        graph.configPath = config.path
        graph.generatedAt = _now_iso()
        graph.durationMs = int((time.perf_counter() - started) * 1000)
        graph.finalize()
        return AnalysisResult(graph=graph, empty=True, cache=cache_report,
                              relevance=relevance)

    workspace = build_workspace(found.root, parsed_files,
                                dataflow=getattr(options, "dataflow",
                                                 DEFAULT_DATAFLOW))
    # NB: the offset tables ride on the workspace so `GraphContext` can reach
    # them without the rules ever importing `ingest`.
    workspace.notebooks = notebook_maps
    builder = GraphBuilder(workspace, max_nodes=options.max_nodes)
    graph = builder.build()
    graph.diagnostics = diagnostics + list(graph.diagnostics)
    graph.filesAnalyzed = len(parsed_files)
    graph.filesFailed = failures
    graph.notebooksSkipped = notebooks_skipped
    graph.configPath = config.path

    for scope in workspace.dynamic_scopes:
        module = workspace.modules.get(scope.module)
        diagnostics_line = scope.loc.line if scope.loc else 1
        graph.diagnostics.append(Diagnostic(
            kind="dynamic_scope",
            message="%s: %s" % (scope.qualname, "; ".join(scope.reasons) or "dynamic scope"),
            file=scope.module, line=diagnostics_line, scope=scope.qualname))

    if not getattr(workspace, "ir_converged", True):
        # PERF-02: the IR rounds stopped on the cap, not on a fixed point, so
        # some cross-module resolution is incomplete. Silence here means the
        # graph just comes back smaller with nothing to point at.
        graph.diagnostics.append(Diagnostic(
            kind="truncated",
            message="Cross-module resolution stopped after %d rounds without "
                    "reaching a fixed point; some imported symbols may be "
                    "unresolved. Narrow the analyzed path, or file the workspace "
                    "shape as a bug." % getattr(workspace, "ir_rounds", 0),
            count=getattr(workspace, "ir_rounds", 0)))

    # ANA-5a: a call whose callee the analyzer could not resolve is drawn as an
    # `unknown` op and said out loud, one row per (file, scope). Before this an
    # odd-syntax file lost its whole training step with `dynamic: 0` on every
    # node it kept, which is indistinguishable from a clean read.
    graph.diagnostics.extend(unresolved_callee_diagnostics(workspace))

    # DATAFLOW-IP: every interprocedural chain the hop cap - or a set of call
    # sites the pass refused to merge - stopped. Reported rather than dropped:
    # a truncated chain that says nothing looks exactly like a value that never
    # carried a tag, which is the one confusion this project refuses to ship.
    for relpath, line, message in getattr(workspace, "ip_notes", ()) or ():
        graph.diagnostics.append(Diagnostic(
            kind="truncated", message=message, file=relpath, line=line))

    for relpath, line, message in workspace.unresolved_imports:
        graph.diagnostics.append(Diagnostic(
            kind="dynamic_scope", message=message, file=relpath, line=line,
            scope=workspace.modules[relpath].dotted or relpath))

    # COVERAGE: one file of a package answers a smaller question than the
    # reader thinks it does - 3 findings where the directory yields 7, measured
    # on samples/vision_pipeline/train.py.
    narrow = single_file_diagnostic(found, workspace, cross_file_codes(),
                                    include=options.include, exclude=excludes)
    if narrow is not None:
        graph.diagnostics.append(narrow)

    suppressor = Suppressor(config)
    for relpath in sorted(workspace.modules):
        suppressor.index_module(relpath, workspace.modules[relpath].lines)
    # CLEANUP 3: an ignore comment naming a code that does not exist suppresses
    # nothing; saying nothing about it is how a typo'd suppression hides.
    for warning in suppressor.warnings:
        graph.diagnostics.append(Diagnostic(kind="config_warning", message=warning))

    context = GraphContext(graph, workspace, builder, suppressor, options,
                           graph.diagnostics)
    # `[rules] disable` is a *suppression*, not a skip: the schema requires the
    # issue to be emitted with `suppressed: true` so a UI can offer "show
    # suppressed". `Suppressor` applies it; only `enabled=False` skips a rule.
    run_all(context, strict=options.strict, framework=options.framework)
    # COVERAGE / TB-10: one sweep over the call index, after the rules, so an
    # untraced FIT / SPLIT / LOADER site is declared whether or not a rule that
    # happens to gate on it ran. Emits diagnostics only - never an issue.
    note_untraced_sites(context)
    note_unconfirmed_train_loops(context)

    _filter_issues(graph, options)
    drop_orphan_ghosts(graph)
    # PERF-04 (CONTRACTS 11.46): the cap is a hierarchical rollup now, and it
    # still runs here - after the rules, before projection (11.2.2).
    apply_node_budget(graph, options.max_nodes)
    # NB: last, so a ghost minted by an absence rule and a node re-parented by
    # the cap both carry the cell they came from.
    annotate_notebook_nodes(graph, notebook_maps)
    graph.generatedAt = _now_iso()
    graph.durationMs = int((time.perf_counter() - started) * 1000)
    graph.finalize()
    return AnalysisResult(graph=graph, workspace=workspace, builder=builder,
                          context=context, cache=cache_report,
                          relevance=relevance)


def _ingest(found, options: AnalyzeOptions, pinned: Tuple[str, ...]):
    """Read, parse and prefilter. Returns `(parsed, failures, relevance, cache)`.

    Two phases, because PERF-03 and CACHE only pay together:

    * **Phase 1** reads every discovered file once and establishes its
      *facts* - is it a seed, what does it import. A file whose content digest
      is already in the sidecar contributes its facts without being parsed at
      all; every other file is parsed here, since the bytes are in hand.
    * **Phase 2** parses whatever the prefilter kept and phase 1 did not
      already have. Only the kept set reaches `build_workspace`, and therefore
      the IR fixed point and the rules.

    Under `--relevance all` there is nothing to decide, so neither the facts
    nor the cache are consulted and this collapses to exactly the single
    `parse_all` pass the analyzer has always made - the same bytes, in the same
    order, at the same cost.
    """
    if options.relevance != "ml":
        parsed, failures, _sink = parse_all(found, progress=options.progress)
        # `select` in "all" mode reads only the keys - no facts are derived,
        # which is what makes this path cost exactly what it always cost.
        relevance = relevance_mod.select(dict.fromkeys(p.relpath for p in parsed),
                                         mode="all", hops=options.relevance_hops)
        return parsed, failures, relevance, None

    cache = cache_mod.open_cache(found.root, options.cache)
    total = len(found.files)
    sink = options.progress
    failures: List = []
    parsed_by_rel = {}
    facts = {}
    for index, relpath in enumerate(found.files, start=1):
        abspath = found.abspath(relpath)
        raw, bad = read_bytes(abspath, relpath)
        if raw is not None:
            stored = cache.get(relpath, cache.content_key(raw)) if cache else None
            if stored is not None:
                facts[relpath] = stored
            else:
                ok, bad = parse_bytes(raw, relpath, abspath)
                if ok is not None:
                    parsed_by_rel[relpath] = ok
                    fresh = relevance_mod.facts_of_parsed(ok)
                    facts[relpath] = fresh
                    if cache is not None:
                        cache.put(relpath, cache.content_key(raw), fresh)
        # H3: one frame per discovered file, in order, whether or not the
        # prefilter will keep it - `done` counts files dealt with.
        sink = safe_call(sink, index, total, relpath)
        if bad is not None:
            failures.append(bad)

    cache_report = None
    if cache is not None:
        cache.flush()
        cache_report = cache.report()
        cache_mod.announce(cache_report)

    relevance = relevance_mod.select(facts, mode="ml", hops=options.relevance_hops,
                                     pinned=pinned)
    parsed = []
    for relpath in relevance.kept:
        ok = parsed_by_rel.get(relpath)
        if ok is None:                      # facts came off disk; parse it now
            ok, bad = parse_file(found.abspath(relpath), relpath)
            if ok is None:
                if bad is not None:
                    failures.append(bad)
                continue
        parsed.append(ok)
    failures.sort(key=lambda f: f.relpath)
    return parsed, failures, relevance, cache_report


def _ingest_notebooks(found, want: bool, parsed_files: List,
                      diagnostics: List[Diagnostic]):
    """NB. Convert the discovered `.ipynb` files. Returns `(maps, skipped)`.

    Three honesty rules, and they are the reason this is not four lines inside
    `run()`:

    1. **`notebooksSkipped` never becomes zero because the flag was on.** It is
       `found.notebooks` (every notebook discovered) minus the ones that really
       did reach the rules - so a notebook the include filter excluded, one
       whose JSON is broken and one whose generated module does not parse are
       all still counted, exactly as they were before this feature existed.
    2. **Every skip says why.** A notebook that failed gets its own
       `parse_error` naming the notebook, not the generated module: the reader
       has to be able to find the file the tool choked on.
    3. **Every success says what it did.** One `notebook_analyzed` per
       notebook, carrying the generated module, the cell count, the magic
       count and the execution-order verdict. A notebook that was analyzed and
       says nothing is exactly the "clean bill of health from a blind tool"
       this contract refuses everywhere else.
    """
    if not want:
        if found.notebooks:
            diagnostics.append(Diagnostic(
                kind="notebook_skipped",
                message="%d notebook(s) detected but not analyzed in this version."
                        % found.notebooks,
                count=found.notebooks))
        return {}, found.notebooks

    ingest = notebook_mod.ingest_notebooks(found.root, found.notebook_files)
    parsed_files.extend(ingest.parsed)
    for relpath, why in ingest.failures:
        diagnostics.append(Diagnostic(kind="parse_error", message=why, file=relpath))
    skipped = max(0, found.notebooks - len(ingest.parsed))
    if skipped:
        tail = (" " + notebook_mod.failure_summary(ingest.failures)
                ) if ingest.failures else ""
        diagnostics.append(Diagnostic(
            kind="notebook_skipped",
            message="%d of %d notebook(s) could not be analyzed.%s"
                    % (skipped, found.notebooks, tail),
            count=skipped))
    for shadow in sorted(ingest.maps, key=lambda k: ingest.maps[k].notebook):
        nbmap = ingest.maps[shadow]
        diagnostic = Diagnostic(kind="notebook_analyzed", message=nbmap.summary(),
                                file=nbmap.notebook, count=nbmap.codeCells)
        if not nbmap.orderOk:
            diagnostic.codes = list(confidence_mod.ORDER_SENSITIVE_CODES)
        diagnostics.append(diagnostic)
    return dict(ingest.maps), skipped


def annotate_notebook_nodes(graph: MLGraph, maps) -> None:
    """NB. Put the cell mapping beside every node that came from a notebook.

    `Loc` is frozen (CONTRACTS section 2) and cannot carry a cell index, so the
    mapping rides in `Node.attrs` - `notebook`, `cell`, `cellLine`, all
    strings, which is what `attrs` already is. Provenance wins over a literal
    keyword argument of the same name: a location that names the wrong cell is
    worse than a lost `cell=` kwarg, and the collision is stated in 11.29
    rather than discovered.

    Public because a host that rebuilds a graph (a projection, a cap) may
    re-run it; it is idempotent.
    """
    if not maps:
        return
    for node in graph.nodes:
        nbmap = maps.get(node.loc.file)
        if nbmap is None:
            continue
        node.attrs["notebook"] = nbmap.notebook
        where = nbmap.locate(node.loc.line)
        if where is not None:
            node.attrs["cell"] = str(where[0])
            node.attrs["cellLine"] = str(where[1])


def _explicit_files(paths: Sequence[str], root: str) -> Tuple[str, ...]:
    """Workspace-relative paths the caller named as **files**, not directories.

    PERF-03 pins them as seeds. `mlview issues train_utils.py` asks about that
    file; a prefilter that decides the file is not interesting has answered a
    different question, and "no findings" would be indistinguishable from "not
    looked at". Directories are not pinned - naming a directory is exactly the
    case the filter exists for.
    """
    import os

    out = []
    for path in paths or ():
        try:
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(normalize_path(path), root).replace("\\", "/")
        except (OSError, ValueError):
            continue
        if rel and not rel.startswith(".."):
            out.append(rel)
    return tuple(sorted(set(out)))


def _filter_issues(graph: MLGraph, options: AnalyzeOptions) -> None:
    floor = SEVERITY_RANK.get(options.min_severity, 0)
    kept = []
    for issue in graph.issues:
        if SEVERITY_RANK.get(issue.severity, 0) < floor:
            continue
        if issue.confidence < options.min_confidence:
            continue
        kept.append(issue)
    graph.issues = kept


def drop_orphan_ghosts(graph: MLGraph) -> None:
    """Invariant 1.1.8: a ghost node always carries at least one issue.

    Public because CI-ADOPT drops issues **after** the pipeline has finished
    (`--changed-only`), and a ghost whose only finding just went would violate
    1.1.8 on the way out. Re-run this, then `finalize()`, after any late edit
    to `graph.issues`.
    """
    live = {issue.id for issue in graph.issues}
    keep = []
    dropped = set()
    for node in graph.nodes:
        if node.ghost and not any(i in live for i in node.issueIds):
            dropped.add(node.id)
            continue
        keep.append(node)
    if dropped:
        graph.nodes = keep
        graph.edges = [e for e in graph.edges
                       if e.source not in dropped and e.target not in dropped]
