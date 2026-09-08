"""The analysis pipeline: discover -> parse -> IR -> graph -> rules -> emit.

`api.analyze()` is a thin wrapper over `run()`. Everything here is pure with
respect to the filesystem apart from reading the analyzed source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from ..ingest.discover import discover
from ..ingest.parse import parse_file
from ..ir.build_ir import build_workspace
from ..rules import Suppressor, load_config, run_all
from ..rules.context import GraphContext
from .build import GraphBuilder
from .graph import Diagnostic, MLGraph, SEVERITY_RANK

__all__ = ["AnalyzeOptions", "run", "AnalysisResult"]


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


@dataclass
class AnalysisResult:
    """The graph plus the internals the CLI and tests want."""

    graph: MLGraph
    workspace: object = None
    builder: object = None
    context: object = None
    empty: bool = False


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
    parsed_files = []
    failures = 0
    for relpath in found.files:
        ok, bad = parse_file(found.abspath(relpath), relpath)
        if ok is not None:
            parsed_files.append(ok)
        else:
            failures += 1
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

    if not parsed_files:
        graph = MLGraph(root=found.root)
        graph.diagnostics = diagnostics
        graph.filesFailed = failures
        graph.notebooksSkipped = found.notebooks
        graph.configPath = config.path
        graph.generatedAt = _now_iso()
        graph.durationMs = int((time.perf_counter() - started) * 1000)
        graph.finalize()
        return AnalysisResult(graph=graph, empty=True)

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

    for relpath, line, message in workspace.unresolved_imports:
        graph.diagnostics.append(Diagnostic(
            kind="dynamic_scope", message=message, file=relpath, line=line,
            scope=workspace.modules[relpath].dotted or relpath))

    suppressor = Suppressor(config)
    for relpath in sorted(workspace.modules):
        suppressor.index_module(relpath, workspace.modules[relpath].lines)

    context = GraphContext(graph, workspace, builder, suppressor, options,
                           graph.diagnostics)
    # `[rules] disable` is a *suppression*, not a skip: the schema requires the
    # issue to be emitted with `suppressed: true` so a UI can offer "show
    # suppressed". `Suppressor` applies it; only `enabled=False` skips a rule.
    run_all(context, strict=options.strict, framework=options.framework)

    _filter_issues(graph, options)
    _drop_orphan_ghosts(graph)
    _apply_node_cap(graph, options.max_nodes)
    graph.generatedAt = _now_iso()
    graph.durationMs = int((time.perf_counter() - started) * 1000)
    graph.finalize()
    return AnalysisResult(graph=graph, workspace=workspace, builder=builder,
                          context=context)


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

    anchors = {n.id for n in graph.nodes if n.ghost}
    for issue in graph.issues:
        anchors.update(issue.nodeIds)
    ancestors = set()
    for node in graph.nodes:
        if node.id in anchors:
            ancestors.update(p.id for p in chain(node))
    ancestors -= anchors

    def tier(node) -> int:
        if node.id in anchors:
            return 0
        if node.id in ancestors:
            return 1
        return 2 if node.level != "op" else 3

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


def _drop_orphan_ghosts(graph: MLGraph) -> None:
    """Invariant 1.1.8: a ghost node always carries at least one issue."""
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
