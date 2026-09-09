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
from ..ingest.parse import parse_all, parse_bytes, parse_file, read_bytes
from ..ir.build_ir import build_workspace
from ..rules import Suppressor, cross_file_codes, load_config, run_all
from ..rules.context import GraphContext
from . import cache as cache_mod
from . import relevance as relevance_mod
from .build import GraphBuilder
from .coverage import note_untraced_sites, single_file_diagnostic
from .unresolved import unresolved_callee_diagnostics
from .graph import Diagnostic, MLGraph, SEVERITY_RANK
from .progress import safe_call

__all__ = ["AnalyzeOptions", "run", "AnalysisResult", "drop_orphan_ghosts",
           "DEFAULT_RELEVANCE"]

#: PERF-03. The shipped default for `--relevance`, and it is `all` - the
#: identity mode, in which every discovered file reaches the IR and the rules
#: exactly as before the prefilter existed.
#:
#: ROADMAP's condition for defaulting to `ml` was that `tools/accuracy.py` be
#: identical in both modes. It **is** - byte-identical over the whole ANA-12
#: corpus - and `tools/perf_equiv.py` is byte-identical on all three corpora
#: too. The default stays `all` for a different, measured reason: on workspaces
#: small enough that the filter saves nothing, it still changes four analyzer
#: gates, because a two-file fixture with one non-framework module is exactly
#: the shape where "set aside" and "not analyzed" become visible
#: (`filesAnalyzed`, `single_file_analysis`'s count, and an unresolved-import
#: note that moves from the module to the set-aside list). Flipping the default
#: is a re-baseline, not an optimisation, and CONTRACTS 11.28 records precisely
#: what it costs so it can be done deliberately.
DEFAULT_RELEVANCE = "all"


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
    config = load_config(options.config_path, None)
    excludes = tuple(options.exclude) + tuple(config.excludes)
    found = discover(options.paths, include=options.include, exclude=excludes,
                     max_files=options.max_files)
    # a config file inside the discovered root takes effect too
    if config.path is None:
        config = load_config(None, found.root)
        if config.excludes:
            found = discover(options.paths, include=options.include,
                             exclude=excludes + tuple(config.excludes),
                             max_files=options.max_files)

    diagnostics: List[Diagnostic] = []
    parsed_files, parse_failures, relevance, cache_report = _ingest(
        found, options, _explicit_files(options.paths, found.root))
    failures = len(parse_failures)
    for bad in parse_failures:
        diagnostics.append(Diagnostic(kind="parse_error", message=bad.message,
                                      file=bad.relpath, line=bad.line))

    if found.notebooks:
        diagnostics.append(Diagnostic(
            kind="notebook_skipped",
            message="%d notebook(s) detected but not analyzed in this version."
                    % found.notebooks,
            count=found.notebooks))
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
        graph.notebooksSkipped = found.notebooks
        graph.configPath = config.path
        graph.generatedAt = _now_iso()
        graph.durationMs = int((time.perf_counter() - started) * 1000)
        graph.finalize()
        return AnalysisResult(graph=graph, empty=True, cache=cache_report,
                              relevance=relevance)

    workspace = build_workspace(found.root, parsed_files)
    builder = GraphBuilder(workspace, max_nodes=options.max_nodes)
    graph = builder.build()
    graph.diagnostics = diagnostics + list(graph.diagnostics)
    graph.filesAnalyzed = len(parsed_files)
    graph.filesFailed = failures
    graph.notebooksSkipped = found.notebooks
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

    _filter_issues(graph, options)
    drop_orphan_ghosts(graph)
    _apply_node_cap(graph, options.max_nodes)
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


def _apply_node_cap(graph: MLGraph, max_nodes: int) -> None:
    """`--max-nodes` is a **graph** cap on the finished document (CONTRACTS §3).

    It runs after the rules, not during construction, for two reasons: the
    older op-only version was not a cap at all (a workspace with more units
    than the budget came back at full size with `truncated: true` and nothing
    the caller could act on), and capping first would have hidden findings from
    the rules themselves.

    Priority order: ghosts and the nodes an issue is anchored on, then their
    ancestors, then the remaining units, then ops. Survivors whose parent went
    are re-parented to their nearest kept ancestor, and an issue whose anchors
    all went is re-anchored the same way - so invariants 1.1.2 and "every issue
    names at least one node" both hold at any budget.
    """
    if max_nodes <= 0 or len(graph.nodes) <= max_nodes:
        return
    by_id = {n.id: n for n in graph.nodes}

    def chain(node):
        out = []
        parent = by_id.get(node.parent or "")
        while parent is not None and len(out) < 32:
            out.append(parent)
            parent = by_id.get(parent.parent or "")
        return out

    # An issue's *first* anchor outranks its later ones. Anchor sets grow (a
    # finding may name the loss node, the model unit and the offending op), and
    # a budget smaller than the total anchor count used to be spent on second
    # and third anchors while some other issue lost every one of its own and
    # was dropped: "lowering the cap must not silence a finding" held only
    # while every anchor fitted. Measured on `analyzer/tests`: 56 anchors, and
    # a 50-node budget silenced MLV203 and MLV204 outright.
    primary = {n.id for n in graph.nodes if n.ghost}
    anchors = set(primary)
    for issue in graph.issues:
        if issue.nodeIds:
            primary.add(issue.nodeIds[0])
        anchors.update(issue.nodeIds)
    ancestors = set()
    for node in graph.nodes:
        if node.id in anchors:
            ancestors.update(p.id for p in chain(node))
    ancestors -= anchors

    def tier(node) -> int:
        if node.id in primary:
            return 0
        if node.id in anchors:
            return 1
        if node.id in ancestors:
            return 2
        return 3 if node.level != "op" else 4

    ordered = sorted(graph.nodes, key=lambda n: (tier(n), len(chain(n))) + tuple(n.sort_key))
    kept = ordered[:max_nodes]
    keep_ids = {n.id for n in kept}
    dropped = [n for n in graph.nodes if n.id not in keep_ids]
    dropped_ops = sum(1 for n in dropped if n.level == "op")

    def surviving(node_id):
        node = by_id.get(node_id)
        if node is None:
            return None
        if node.id in keep_ids:
            return node.id
        for parent in chain(node):
            if parent.id in keep_ids:
                return parent.id
        return None

    for node in kept:
        node.parent = surviving(node.parent) if node.parent else None
    lost_issues = []
    for issue in graph.issues:
        rehomed = []
        for nid in issue.nodeIds:
            survivor = surviving(nid)
            if survivor and survivor not in rehomed:
                rehomed.append(survivor)
        if rehomed:
            issue.nodeIds = rehomed
        else:
            lost_issues.append(issue)
    if lost_issues:
        lost = {id(i) for i in lost_issues}
        graph.issues = [i for i in graph.issues if id(i) not in lost]
    graph.nodes = [n for n in graph.nodes if n.id in keep_ids]
    graph.edges = [e for e in graph.edges
                   if e.source in keep_ids and e.target in keep_ids]
    graph.truncated = True
    extra = ("; %d issue(s) went with them" % len(lost_issues)) if lost_issues else ""
    graph.diagnostics.append(Diagnostic(
        kind="truncated",
        message="Graph cap (--max-nodes budget) %d reached: %d operation node(s) and "
                "%d unit node(s) dropped, %d node(s) kept%s. Raise --max-nodes, or "
                "narrow the analyzed path, to see the rest."
                % (max_nodes, dropped_ops, len(dropped) - dropped_ops,
                   len(graph.nodes), extra),
        count=len(dropped)))


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
