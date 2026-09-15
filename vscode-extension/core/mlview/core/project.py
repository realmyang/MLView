"""Scoped views: parse a selector, resolve it, project the document.

CONTRACTS section 11.1 (grammar) and 11.2 (resolution + projection). A scope
is a **pure projection of a finished whole-workspace document** - never a
smaller set of files handed to the parser, and never a smaller audit.

Pure: no filesystem, no IR, no clock, no randomness, no set-iteration-order
leak. Every step only *removes* elements from arrays that are already
canonically sorted (CONTRACTS section 0), so `nodes`, `edges` and `issues` in
the output are **subsequences** of the input arrays in the same relative
order. The single non-filter operation in the whole algorithm is the stable
rotation in step 6 (section 11.2.1). A port that sorts anything is wrong.

Named `project.py`, not `scope.py`: `mlview/ir/scopes.py` already owns the
word "scope" for lexical scopes. Nothing here imports `build.py` or
`pipeline.py` - a projection must stay callable on a graph loaded from disk.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .pipelines import build_index, pipeline_catalog, resolve_entrypoint
from .selectors import (CONCERN_ALIASES, CONCERN_LABELS, CONCERNS, DEFAULT_DEPTH,
                        MAX_DEPTH, SCOPE_KINDS, SCOPE_SPELLINGS, Scope, ScopeError,
                        ascii_lower, parse_scope)

#: Re-exported from `selectors.py` so the whole scoped-view surface keeps the
#: single import path CONTRACTS 11.6 names.
__all__ = [
    "CONCERNS", "CONCERN_ALIASES", "CONCERN_LABELS", "SCOPE_KINDS", "SCOPE_SPELLINGS",
    "DEFAULT_DEPTH", "MAX_DEPTH", "ScopeError", "Scope", "ScopeResolution",
    "parse_scope", "resolve_scope", "project", "scope_catalog", "view_label",
    "pipeline_catalog",
]

_SEVERITIES = ("high", "medium", "low")
_ZERO_COUNTS = {"low": 0, "medium": 0, "high": 0}
_MAX_PRUNE_ROUNDS = 8


# ------------------------------------------------------------ resolution
@dataclass(frozen=True)
class ScopeResolution:
    """Anchors and core for a scope - no projection (CONTRACTS 11.6)."""

    scope: Scope
    anchors: Tuple[str, ...]
    core: Tuple[str, ...]
    ambiguous: bool = False
    warnings: Tuple[str, ...] = ()
    #: MLV-P12 (CONTRACTS 11.47 C). Nodes the scope must keep but must NOT call
    #: its own - today only a `pipeline:` scope's shared nodes, the ones another
    #: entrypoint reaches too. Appended last and defaulted to `()`, so every
    #: other kind builds exactly the resolution it built before.
    context: Tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.anchors


def _last_segment(qualname: str) -> str:
    return qualname.rsplit(".", 1)[-1] if "." in qualname else qualname


def _unit_tiers(nodes: Sequence[Dict[str, Any]], target: str, fold: bool
                ) -> List[List[Dict[str, Any]]]:
    """The five `unit:` tiers, in order, over `nodes` in document order."""
    def fold_fn(value: str) -> str:
        return ascii_lower(value) if fold else value

    want = fold_fn(target)
    want_call = fold_fn(target + "()")

    def eq(value: Optional[str], expected: str) -> bool:
        return bool(value) and fold_fn(value) == expected

    definition = ("stage", "unit")
    return [
        [n for n in nodes if eq(n.get("qualname"), want)],
        [n for n in nodes if eq(n.get("fqn"), want)],
        [n for n in nodes if eq(_last_segment(n.get("qualname", "")), want)
         and n.get("level") in definition],
        [n for n in nodes if eq(_last_segment(n.get("qualname", "")), want)],
        [n for n in nodes if eq(n.get("label"), want) or eq(n.get("label"), want_call)],
    ]


def _resolve_unit(nodes: Sequence[Dict[str, Any]], target: str
                  ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Tiered `unit:` resolution: the first non-empty tier wins (11.2 step 1)."""
    warnings: List[str] = []
    text = target[:-2] if target.endswith("()") else target
    if text.startswith("n:"):
        exact = [n for n in nodes if n.get("id") == text]
        if exact:
            return exact, warnings
    for tier in _unit_tiers(nodes, text, False):
        if tier:
            return tier, warnings
    for tier in _unit_tiers(nodes, text, True):
        if tier:
            spellings = sorted({n.get("qualname", "") for n in tier})[:5]
            warnings.append(
                "scope unit:%s matched case-insensitively; the canonical spelling is %s"
                % (text, ", ".join(spellings)))
            return tier, warnings
    return [], warnings


def _resolve_file(nodes: Sequence[Dict[str, Any]], target: str
                  ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Exact path, then bare basename, then the same two case-insensitively."""
    def file_of(node: Dict[str, Any]) -> str:
        return (node.get("loc") or {}).get("file") or ""

    def base(path: str) -> str:
        return path.rsplit("/", 1)[-1]

    bare = "/" not in target
    exact = [n for n in nodes if file_of(n) == target]
    if exact:
        return exact, []
    if bare:
        by_base = [n for n in nodes if base(file_of(n)) == target]
        if by_base:
            return by_base, []
    want = ascii_lower(target)
    folded = [n for n in nodes if ascii_lower(file_of(n)) == want]
    if not folded and bare:
        folded = [n for n in nodes if ascii_lower(base(file_of(n))) == want]
    if folded:
        spellings = sorted({file_of(n) for n in folded})[:5]
        return folded, ["scope file:%s matched case-insensitively; the canonical "
                        "spelling is %s" % (target, ", ".join(spellings))]
    raise ScopeError("unknown_file", target,
                     sorted({file_of(n) for n in nodes if file_of(n)}))


def _resolve_pipeline(graph: Dict[str, Any], nodes: Sequence[Dict[str, Any]],
                      scope: Scope) -> ScopeResolution:
    """`pipeline:<entrypoint>` (CONTRACTS 11.47 B/C).

    Anchors are the **seeds**: the nodes of the entrypoint file itself, which is
    what the user named. `core` is the pipeline's *exclusive* reach - everything
    it reaches that no other entrypoint does - and the shared remainder becomes
    forced `context`, so a node two pipelines both use is never claimed by one
    of them. A target that is not an entrypoint is `unknown_pipeline`; an
    entrypoint whose file contributed no node is an EMPTY scope, not an error,
    for the same reason `unit:` is (11.2 step 9).
    """
    canonical, warnings = resolve_entrypoint(graph, scope.target)
    if canonical is None:
        raise ScopeError(
            "unknown_pipeline", scope.target,
            [str(e) for e in
             ((graph.get("workspace") or {}).get("entrypoints") or [])])
    index = build_index(graph)
    anchors = tuple(n["id"] for n in nodes
                    if (n.get("loc") or {}).get("file") == canonical)
    core = index.core_of(canonical)
    context = index.context_of(canonical)
    if anchors:
        warnings = list(warnings) + [
            "scope pipeline:%s draws %d node(s) of %d: %d are shared with "
            "another entrypoint and are shown as context, and %d node(s) of "
            "this graph belong to no pipeline at all."
            % (canonical, len(core) + len(context), len(nodes), len(context),
               len(index.unreached))]
    return ScopeResolution(scope, anchors, core, False, tuple(warnings), context)


def resolve_scope(graph: Dict[str, Any], scope: Scope) -> ScopeResolution:
    """Anchors + core for `scope`, in document order. No projection."""
    nodes: List[Dict[str, Any]] = list(graph.get("nodes") or [])
    warnings: List[str] = []
    if scope.kind == "all":
        return ScopeResolution(scope, tuple(n["id"] for n in nodes),
                               tuple(n["id"] for n in nodes))
    if scope.kind == "stage":
        anchors = [n for n in nodes if n.get("stage") == scope.target]
    elif scope.kind == "concern":
        wanted = set(CONCERNS[scope.target])
        anchors = [n for n in nodes if n.get("stage") in wanted]
    elif scope.kind == "file":
        anchors, extra = _resolve_file(nodes, scope.target)
        warnings.extend(extra)
    elif scope.kind == "node":
        anchors = [n for n in nodes if n.get("id") == scope.target]
        if not anchors:
            raise ScopeError("unknown_node", scope.target,
                             [n["id"] for n in nodes])
    elif scope.kind == "pipeline":
        return _resolve_pipeline(graph, nodes, scope)
    else:                                                   # unit
        anchors, extra = _resolve_unit(nodes, scope.target)
        warnings.extend(extra)

    anchor_ids = tuple(n["id"] for n in anchors)
    ambiguous = scope.kind == "unit" and len(anchor_ids) > 1
    if ambiguous:
        warnings.append(
            "scope unit:%s is ambiguous: %d nodes match. Use one of: %s"
            % (scope.target, len(anchor_ids),
               ", ".join(sorted(n.get("qualname", n["id"]) for n in anchors))))
    core = anchor_ids
    if scope.kind == "unit" and anchor_ids:
        core = _with_descendants(nodes, anchor_ids)
    return ScopeResolution(scope, anchor_ids, core, ambiguous, tuple(warnings))


def _with_descendants(nodes: Sequence[Dict[str, Any]],
                      seeds: Sequence[str]) -> Tuple[str, ...]:
    """Seeds plus their transitive `parent` descendants, in document order."""
    children: Dict[str, List[str]] = {}
    for node in nodes:
        parent = node.get("parent")
        if parent:
            children.setdefault(parent, []).append(node["id"])
    keep: Set[str] = set()
    stack = list(seeds)
    while stack:                                            # cycle-guarded
        current = stack.pop()
        if current in keep:
            continue
        keep.add(current)
        stack.extend(children.get(current, ()))
    return tuple(n["id"] for n in nodes if n["id"] in keep)


# ------------------------------------------------------------ projection
def project(graph: Dict[str, Any], scope: Scope) -> Dict[str, Any]:
    """Project `graph` through `scope` (CONTRACTS 11.2). Pure dict -> dict."""
    if scope.kind == "all":
        out = copy.deepcopy(graph)
        out.pop("view", None)
        for node in out.get("nodes") or []:
            node.pop("viewRole", None)
        return out

    nodes: List[Dict[str, Any]] = list(graph.get("nodes") or [])
    edges: List[Dict[str, Any]] = list(graph.get("edges") or [])
    issues: List[Dict[str, Any]] = list(graph.get("issues") or [])
    by_id = {n["id"]: n for n in nodes}

    resolution = resolve_scope(graph, scope)
    core: Set[str] = set(resolution.core)

    # steps 3-4: boundary rings, then the ancestor closure. `forced` is
    # MLV-P12's addition (11.47 C): nodes the scope keeps but never calls its
    # own. It is empty for every kind but `pipeline`, so nothing else moves.
    forced: Set[str] = set(resolution.context) - core
    boundary = _boundary(edges, core, scope.depth) - forced - core
    context = (_ancestors(by_id, core | boundary | forced) | forced) - core - boundary
    kept: Set[str] = core | boundary | context

    kept_edges = [e for e in edges if e["source"] in kept and e["target"] in kept]
    kept_edge_ids = {e["id"] for e in kept_edges}
    core_edge_ids = {e["id"] for e in kept_edges
                     if e["source"] in core and e["target"] in core}

    retained, promoted = _retain_issues(issues, core, kept, kept_edge_ids,
                                        core_edge_ids,
                                        {e["id"]: e for e in kept_edges})
    retained, kept, kept_edges = _prune_ghosts(retained, kept, kept_edges, by_id)

    node_ids = kept
    live_issue_ids = {i["id"] for i in retained}
    out_nodes: List[Dict[str, Any]] = []
    for node in nodes:
        if node["id"] not in node_ids:
            continue
        copied = copy.deepcopy(node)
        issue_ids = [i for i in node.get("issueIds") or [] if i in live_issue_ids]
        for issue_id in promoted.get(node["id"], ()):   # keep the link two-way
            if issue_id in live_issue_ids and issue_id not in issue_ids:
                issue_ids.append(issue_id)
        copied["issueIds"] = issue_ids
        copied.pop("viewRole", None)
        copied["viewRole"] = ("core" if node["id"] in core
                              else "boundary" if node["id"] in boundary else "context")
        out_nodes.append(copied)
    out_edges: List[Dict[str, Any]] = []
    for edge in kept_edges:
        copied = copy.deepcopy(edge)
        copied["issueIds"] = [i for i in edge.get("issueIds") or []
                              if i in live_issue_ids]
        out_edges.append(copied)

    counts = {"core": 0, "boundary": 0, "context": 0}
    for node in out_nodes:
        counts[node["viewRole"]] += 1
    return _assemble(graph, scope, resolution, out_nodes, out_edges, retained,
                     counts, kept)


def _boundary(edges: Sequence[Dict[str, Any]], core: Set[str], depth: int) -> Set[str]:
    """`depth` BFS rings over `edges[]` in both directions. Containment is not a hop."""
    if depth <= 0 or not core:
        return set()
    adjacency: Dict[str, Set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        adjacency.setdefault(edge["target"], set()).add(edge["source"])
    seen = set(core)
    frontier = set(core)
    boundary: Set[str] = set()
    for _ in range(depth):
        nxt: Set[str] = set()
        for node_id in frontier:
            nxt |= adjacency.get(node_id, set())
        nxt -= seen
        if not nxt:
            break
        boundary |= nxt
        seen |= nxt
        frontier = nxt
    return boundary


def _ancestors(by_id: Dict[str, Dict[str, Any]], seeds: Set[str]) -> Set[str]:
    """The transitive `parent` chain of `seeds`, minus anything already kept."""
    context: Set[str] = set()
    for node_id in seeds:
        current = by_id.get(node_id, {}).get("parent")
        guard = 0
        while current and guard < 64:
            if current in seeds or current in context:
                break
            context.add(current)
            current = by_id.get(current, {}).get("parent")
            guard += 1
    return context


def _retain_issues(issues: Sequence[Dict[str, Any]], core: Set[str], kept: Set[str],
                   kept_edge_ids: Set[str], core_edge_ids: Set[str],
                   edges_by_id: Dict[str, Dict[str, Any]]
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    """Step 6: retention through `core` only, then filter + stable rotation.

    The one case step 6 does not spell out: an issue retained **through the
    edge rule** whose every `nodeIds` entry fell outside `kept` would end with
    `nodeIds: []`, which breaks graph invariant 1.1.3 (`issue.nodeIds[0]`
    always names a node in `nodes[]`) and leaves the renderer with nowhere to
    put the badge - the schema cannot catch it, since `Issue.nodeIds` carries
    no `minItems`. No shipped rule can reach it today (every rule that cites an
    edge also cites its two endpoints), but the projection is contracted as
    total over any schema-valid document. So: promote the retaining edge's
    `source` - a `core` node by construction, and therefore a legal
    `nodeIds[0]` that needs no rotation - and drop the issue outright if it was
    not retained through an edge after all. The promotion is the one place a
    projection *adds* an id, so the reverse link is added with it (the node
    gets the issue in its `issueIds`): a one-way link would break the
    node <-> issue link check in `contracts/validate_sample.py` in place of
    invariant 1.1.3. Returns the retained issues and the promotions,
    `{nodeId: [issueId, ...]}`.
    """
    out: List[Dict[str, Any]] = []
    promoted: Dict[str, List[str]] = {}
    for issue in issues:
        node_ids = list(issue.get("nodeIds") or [])
        edge_ids = list(issue.get("edgeIds") or [])
        through_node = any(n in core for n in node_ids)
        through_edge = any(e in core_edge_ids for e in edge_ids)
        if not (through_node or through_edge):
            continue
        copied = copy.deepcopy(issue)
        live_nodes = [n for n in node_ids if n in kept]
        live_edges = [e for e in edge_ids if e in kept_edge_ids]
        if not live_nodes:
            retaining = next((e for e in live_edges if e in core_edge_ids), None)
            if retaining is None:                    # not reachable via step 6
                continue
            live_nodes = [edges_by_id[retaining]["source"]]
            promoted.setdefault(live_nodes[0], []).append(issue["id"])
        copied["nodeIds"] = _rotate_to_core(live_nodes, core)
        copied["edgeIds"] = live_edges
        out.append(copied)
    return out, promoted


def _rotate_to_core(node_ids: List[str], core: Set[str]) -> List[str]:
    """Put a core node first without re-sorting: `ids[k:] + ids[:k]` (11.2 step 6)."""
    if not node_ids or node_ids[0] in core:
        return node_ids
    for index, node_id in enumerate(node_ids):
        if node_id in core:
            return node_ids[index:] + node_ids[:index]
    return node_ids


def _prune_ghosts(retained: List[Dict[str, Any]], kept: Set[str],
                  kept_edges: List[Dict[str, Any]], by_id: Dict[str, Dict[str, Any]]):
    """Step 7: a kept ghost with no retained issue is dropped, and so is an
    issue whose `nodeIds` emptied out. Two rounds converge; the loop is
    bounded so a malformed document cannot spin."""
    for _ in range(_MAX_PRUNE_ROUNDS):
        live = {i["id"] for i in retained}
        doomed = {nid for nid in kept
                  if by_id.get(nid, {}).get("ghost")
                  and not any(i in live for i in by_id[nid].get("issueIds") or [])}
        if not doomed:
            break
        kept = kept - doomed
        kept_edges = [e for e in kept_edges
                      if e["source"] in kept and e["target"] in kept]
        edge_ids = {e["id"] for e in kept_edges}
        survivors: List[Dict[str, Any]] = []
        for issue in retained:
            issue["nodeIds"] = [n for n in issue["nodeIds"] if n in kept]
            issue["edgeIds"] = [e for e in issue["edgeIds"] if e in edge_ids]
            if issue["nodeIds"]:
                survivors.append(issue)
        retained = survivors
    return retained, kept, kept_edges


def _issue_counts(issues: Iterable[Dict[str, Any]], stage: Optional[str] = None
                  ) -> Dict[str, int]:
    counts = dict(_ZERO_COUNTS)
    for issue in issues:
        if issue.get("suppressed"):
            continue
        if stage is not None and issue.get("stage") != stage:
            continue
        severity = issue.get("severity")
        if severity in counts:
            counts[severity] += 1
    return counts


def _max_severity(counts: Dict[str, int]) -> Optional[str]:
    return next((s for s in _SEVERITIES if counts.get(s)), None)


def view_label(graph: Dict[str, Any], scope: Scope,
               anchors: Sequence[Dict[str, Any]]) -> str:
    """The frozen breadcrumb name for `view.label` (both ports must agree)."""
    if scope.kind == "stage":
        row = next((s for s in graph.get("stages") or []
                    if s.get("id") == scope.target), None)
        return (row or {}).get("label") or scope.target
    if scope.kind == "concern":
        return CONCERN_LABELS.get(scope.target, scope.target)
    if scope.kind in ("file", "pipeline"):
        return scope.target
    if len(anchors) == 1:
        return anchors[0].get("label") or scope.target
    if len(anchors) > 1:
        return "%s (%d matches)" % (scope.target, len(anchors))
    return scope.target


def _assemble(graph: Dict[str, Any], scope: Scope, resolution: ScopeResolution,
              out_nodes: List[Dict[str, Any]], out_edges: List[Dict[str, Any]],
              retained: List[Dict[str, Any]], counts: Dict[str, int],
              kept: Set[str]) -> Dict[str, Any]:
    """Steps 9-11: aggregates, carried-verbatim fields, then `view` last."""
    by_stage: Dict[str, int] = {}
    for node in out_nodes:
        by_stage[node.get("stage", "")] = by_stage.get(node.get("stage", ""), 0) + 1
    stages: List[Dict[str, Any]] = []
    for row in graph.get("stages") or []:
        copied = copy.deepcopy(row)
        stage_counts = _issue_counts(retained, row.get("id"))
        copied["nodeCount"] = by_stage.get(row.get("id"), 0)
        copied["issueCounts"] = stage_counts
        copied["maxSeverity"] = _max_severity(stage_counts)
        copied["present"] = row.get("present")            # project-level truth
        stages.append(copied)

    stats = copy.deepcopy(graph.get("stats") or {})
    stats["nodes"] = len(out_nodes)
    stats["edges"] = len(out_edges)
    stats["issues"] = _issue_counts(retained)
    stats["suppressed"] = sum(1 for i in retained if i.get("suppressed"))

    all_nodes = graph.get("nodes") or []
    all_edges = graph.get("edges") or []
    anchors = [n for n in all_nodes if n["id"] in set(resolution.anchors)]
    inbound = sum(1 for e in all_edges
                  if e["target"] in kept and e["source"] not in kept)
    outbound = sum(1 for e in all_edges
                   if e["source"] in kept and e["target"] not in kept)
    of_issues = graph.get("stats", {}).get("issues")
    if not isinstance(of_issues, dict):
        of_issues = _issue_counts(graph.get("issues") or [])
    view: Dict[str, Any] = {
        "scope": scope.spec,
        "label": view_label(graph, scope, anchors),
        "depth": scope.depth,
        "counts": {"core": counts["core"], "boundary": counts["boundary"],
                   "context": counts["context"]},
        "of": {"nodes": len(all_nodes), "edges": len(all_edges),
               "issues": {"low": of_issues.get("low", 0),
                          "medium": of_issues.get("medium", 0),
                          "high": of_issues.get("high", 0)}},
        "hidden": {"nodes": len(all_nodes) - len(out_nodes),
                   "edges": len(all_edges) - len(out_edges),
                   "inboundEdges": inbound, "outboundEdges": outbound},
        "resolvedTo": [{"id": n["id"], "qualname": n.get("qualname", ""),
                        "label": n.get("label", ""),
                        "file": (n.get("loc") or {}).get("file", ""),
                        "line": (n.get("loc") or {}).get("line", 1)}
                       for n in anchors],
        "ambiguous": bool(resolution.ambiguous),
        "empty": bool(resolution.empty),
    }

    diagnostics = [copy.deepcopy(d) for d in graph.get("diagnostics") or []]
    for message in resolution.warnings:
        diagnostics.append({"kind": "config_warning", "message": message})
    if resolution.empty:
        diagnostics.append({
            "kind": "config_warning",
            "message": "scope %s matched no nodes; the whole graph has %d node(s). "
                       "This is a finding, not an error."
                       % (scope.as_typed, len(all_nodes))})
    if (graph.get("stats") or {}).get("truncated"):
        diagnostics.append({
            "kind": "truncated",
            "message": "the graph was capped by --max-nodes BEFORE this scope was "
                       "applied; view.of reports the pre-projection totals."})
    diagnostics.sort(key=lambda d: (d.get("kind", ""), d.get("file") or "",
                                    d.get("line") or 0, d.get("message", "")))

    out: Dict[str, Any] = {}
    for key, value in graph.items():
        if key == "stages":
            out[key] = stages
        elif key == "nodes":
            out[key] = out_nodes
        elif key == "edges":
            out[key] = out_edges
        elif key == "issues":
            out[key] = retained
        elif key == "diagnostics":
            out[key] = diagnostics
        elif key == "stats":
            out[key] = stats
        elif key == "view":
            continue
        else:
            out[key] = copy.deepcopy(value)
    out.setdefault("stages", stages)
    out.setdefault("nodes", out_nodes)
    out.setdefault("edges", out_edges)
    out.setdefault("issues", retained)
    out.setdefault("diagnostics", diagnostics)
    out.setdefault("stats", stats)
    out["view"] = view                                   # always the LAST key
    return out


# -------------------------------------------------------------- catalogue
#: `pipeline_catalog` lives in `pipelines.py` beside the relation it reads and
#: is re-exported here, so `--list-scopes` and CONTRACTS 11.6 keep one import
#: path for the whole scoped-view surface.
def scope_catalog(graph: Dict[str, Any], limit: int = 40) -> List[Dict[str, Any]]:
    """One row per scopable unit - a node with children, or `level` in
    {stage, unit} - sorted `(-nodeCount, file, line, qualname)`.

    Backs `analyze --list-scopes` and the MCP `mlview_graph {scope:"units"}`
    catalogue (CONTRACTS 11.5 / 11.10).

    `nodeCount` is the row's **subtree at depth 0**: the unit plus its
    transitive `parent` descendants - the same set `project()` calls `core`,
    and exactly what `--scope <spec> --depth 0` draws. It is *not* a
    prediction of the drawn card count, because a `unit:` scope defaults to
    **depth 1** (CONTRACTS 11.1), which adds a boundary ring. Surfaces that
    print it must not label it "nodes you will see": the CLI column is named
    `SUBTREE` (`emit/scope_out.py`) and `webview/src/scope/catalog.ts` carries
    the same definition on `ScopeUnit.nodeCount`. Computing it at the per-kind
    default depth instead would be a two-port change (11.16).
    """
    nodes = list(graph.get("nodes") or [])
    parents = {n.get("parent") for n in nodes if n.get("parent")}
    issues = [i for i in graph.get("issues") or [] if not i.get("suppressed")]
    rows: List[Dict[str, Any]] = []
    for node in nodes:
        if node.get("level") not in ("stage", "unit") and node["id"] not in parents:
            continue
        subtree = set(_with_descendants(nodes, (node["id"],)))
        counts = dict(_ZERO_COUNTS)
        for issue in issues:
            if any(n in subtree for n in issue.get("nodeIds") or []):
                severity = issue.get("severity")
                if severity in counts:
                    counts[severity] += 1
        loc = node.get("loc") or {}
        rows.append({
            "spec": "unit:%s" % node.get("qualname", node["id"]),
            "kind": "unit",
            "nodeId": node["id"],
            "label": node.get("label", ""),
            "qualname": node.get("qualname", ""),
            "file": loc.get("file", ""),
            "line": loc.get("line", 1),
            "nodeCount": len(subtree),
            "issueCounts": counts,
            "maxSeverity": _max_severity(counts),
        })
    rows.sort(key=lambda r: (-r["nodeCount"], r["file"], r["line"], r["qualname"]))
    return rows[:limit] if limit and limit > 0 else rows
