"""MLV-P12: weakly-connected pipelines seeded from `workspace.entrypoints`.

CONTRACTS 11.47. A research repo with ten training scripts is ten pipelines, not
one 320-node graph, and `workspace.entrypoints` already knows their names. This
module turns that into a **relation over the finished document** - pure, and
readable by both ports from the document alone:

* `seeds(E)`  = the nodes whose `loc.file` is the entrypoint `E`;
* adjacency   = `data` and `call` edges, both directions, **plus containment**
  (`parent` up and down). `config` and `control` edges are deliberately cut: a
  shared `config.py` is precisely the module that would merge ten independent
  training scripts into one component;
* `reach(E)`  = the closure of `seeds(E)`, which **includes but does not expand
  through** a node belonging to another entrypoint's file. Without that one
  clause an undirected closure is the whole connected component whichever seed
  it starts from, ten training scripts that share one `utils.py` are one
  pipeline, and the feature answers nothing;
* a node in `reach(E)` that another entrypoint also reaches is **shared** for
  `E` - unless it is one of `E`'s own seeds, which are always `E`'s. A node in
  no reach at all is **unreached** and belongs to no pipeline.

Nothing here reads the emitted `pipelines[]` block: `project()` recomputes it,
so a hand-edited or stale block can never move a projection. Everything is
materialised in **document order**, never set-iteration order, because both
ports must agree byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .selectors import ascii_lower

__all__ = ["PipelineIndex", "build_index", "pipelines_block", "pipeline_catalog",
           "resolve_entrypoint", "PIPELINE_EDGE_KINDS"]

#: The only edge kinds that join a pipeline (11.47 A2).
PIPELINE_EDGE_KINDS = ("data", "call")

_ZERO_COUNTS = {"low": 0, "medium": 0, "high": 0}
_SEVERITIES = ("high", "medium", "low")


def _max_severity(counts: Dict[str, int]) -> Optional[str]:
    return next((s for s in _SEVERITIES if counts.get(s)), None)


@dataclass(frozen=True)
class PipelineIndex:
    """Every pipeline of one document, computed once (11.47 A)."""

    entrypoints: Tuple[str, ...] = ()
    #: entrypoint -> its reachable node ids, in document order.
    reach: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    #: node ids reached by two or more entrypoints.
    shared: frozenset = frozenset()
    #: node id -> the entrypoint whose file it lives in, for the seeds only.
    owner: Dict[str, str] = field(default_factory=dict)
    #: node ids reachable from none.
    unreached: Tuple[str, ...] = ()

    def _shared_for(self, entrypoint: str, node_id: str) -> bool:
        """A node another entrypoint also reaches - unless it is one of THIS
        entrypoint's own seeds, which are never taken away from it."""
        return (node_id in self.shared
                and self.owner.get(node_id) != entrypoint)

    def core_of(self, entrypoint: str) -> Tuple[str, ...]:
        """The nodes this pipeline does **not** share with another (11.47 C)."""
        return tuple(n for n in self.reach.get(entrypoint, ())
                     if not self._shared_for(entrypoint, n))

    def context_of(self, entrypoint: str) -> Tuple[str, ...]:
        """The shared nodes of this pipeline - forced to `viewRole: context`."""
        return tuple(n for n in self.reach.get(entrypoint, ())
                     if self._shared_for(entrypoint, n))

    @property
    def non_empty(self) -> Tuple[str, ...]:
        return tuple(e for e in self.entrypoints if self.reach.get(e))


def _adjacency(nodes: Sequence[Dict[str, Any]],
               edges: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    """`data` + `call` edges, both directions, plus containment (11.47 A2)."""
    known = {n.get("id") for n in nodes}
    adj: Dict[str, List[str]] = {}

    def link(a: Optional[str], b: Optional[str]) -> None:
        if not a or not b or a == b or a not in known or b not in known:
            return
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    for edge in edges:
        if edge.get("kind") in PIPELINE_EDGE_KINDS:
            link(edge.get("source"), edge.get("target"))
    for node in nodes:
        link(node.get("id"), node.get("parent"))
    return adj


def build_index(graph: Dict[str, Any]) -> PipelineIndex:
    """Compute every pipeline of `graph`. Pure; O(entrypoints x (V + E))."""
    nodes: List[Dict[str, Any]] = list(graph.get("nodes") or [])
    edges: List[Dict[str, Any]] = list(graph.get("edges") or [])
    workspace = graph.get("workspace") or {}
    entrypoints: Tuple[str, ...] = tuple(
        str(e) for e in (workspace.get("entrypoints") or []))
    if not entrypoints or not nodes:
        return PipelineIndex(entrypoints=entrypoints,
                             unreached=tuple(n["id"] for n in nodes))

    adj = _adjacency(nodes, edges)
    order = {n["id"]: i for i, n in enumerate(nodes)}
    by_file: Dict[str, List[str]] = {}
    for node in nodes:
        by_file.setdefault((node.get("loc") or {}).get("file") or "", []).append(
            node["id"])

    owner: Dict[str, str] = {}
    for entrypoint in entrypoints:
        for node_id in by_file.get(entrypoint, ()):
            owner.setdefault(node_id, entrypoint)

    reach: Dict[str, Tuple[str, ...]] = {}
    hits: Dict[str, int] = {}
    for entrypoint in entrypoints:
        seen: Set[str] = set()
        stack = list(by_file.get(entrypoint, ()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            held = owner.get(current)
            if held is not None and held != entrypoint:
                continue            # another entrypoint's own node: keep, stop
            stack.extend(adj.get(current, ()))
        if not seen:
            reach[entrypoint] = ()
            continue
        reach[entrypoint] = tuple(sorted(seen, key=lambda n: order.get(n, 0)))
        for node_id in seen:
            hits[node_id] = hits.get(node_id, 0) + 1

    shared = frozenset(n for n, count in hits.items() if count > 1)
    unreached = tuple(n["id"] for n in nodes if n["id"] not in hits)
    return PipelineIndex(entrypoints=entrypoints, reach=reach, shared=shared,
                         owner=owner, unreached=unreached)


def pipelines_block(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The optional root `pipelines[]` rows, in `workspace.entrypoints` order.

    One row per **non-empty** pipeline. The caller decides whether to emit the
    block at all: 11.47 D emits it only at two or more rows, because the block
    exists to drive a chooser and a single-pipeline workspace has nothing to
    choose.

    `issueCounts` counts non-suppressed issues with at least one anchor inside
    the pipeline, so an issue spanning two pipelines is counted in **both**: the
    block is a menu, not a partition, and the rows are deliberately not required
    to sum to `stats.issues`.
    """
    index = build_index(graph)
    issues = [i for i in graph.get("issues") or [] if not i.get("suppressed")]
    rows: List[Dict[str, Any]] = []
    for entrypoint in index.entrypoints:
        members = index.reach.get(entrypoint) or ()
        if not members:
            continue
        inside = set(members)
        counts = dict(_ZERO_COUNTS)
        for issue in issues:
            if any(n in inside for n in issue.get("nodeIds") or []):
                severity = issue.get("severity")
                if severity in counts:
                    counts[severity] += 1
        shared = len(index.context_of(entrypoint))
        rows.append({
            "entrypoint": entrypoint,
            "label": entrypoint,
            "nodeCount": len(members),
            "exclusiveCount": len(members) - shared,
            "sharedCount": shared,
            "issueCounts": counts,
        })
    return rows


def resolve_entrypoint(graph: Dict[str, Any], target: str
                       ) -> Tuple[Optional[str], List[str]]:
    """Match `target` against `workspace.entrypoints` (11.47 B).

    Exact path, then bare basename when the target carries no `/`, then the same
    two ASCII-case-folded - the `file:` ladder, for the same reason. Returns
    `(canonical entrypoint or None, warnings)`.
    """
    entrypoints = [str(e) for e in
                   ((graph.get("workspace") or {}).get("entrypoints") or [])]
    text = (target or "").replace("\\", "/")
    if text in entrypoints:
        return text, []
    if "/" not in text and text:
        hits = [e for e in entrypoints if e.rsplit("/", 1)[-1] == text]
        if hits:
            return hits[0], []
    want = ascii_lower(text)
    folded = [e for e in entrypoints if ascii_lower(e) == want]
    if not folded and "/" not in text and text:
        folded = [e for e in entrypoints
                  if ascii_lower(e.rsplit("/", 1)[-1]) == want]
    if folded:
        return folded[0], [
            "scope pipeline:%s matched case-insensitively; the canonical "
            "spelling is %s" % (text, folded[0])]
    return None, []


def pipeline_catalog(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One `pipeline:` row per pipeline, in `workspace.entrypoints` order.

    Returned **only when the workspace has two or more non-empty pipelines**,
    for the same reason 11.47 D emits the document block only then: a single
    pipeline is not a choice. Rows carry exactly the ten keys `scope_catalog`
    rows carry, so `--list-scopes` renders both lists through one formatter.

    `nodeCount` keeps the column's documented meaning - *what `--scope <spec>
    --depth 0` draws as `core`* - which for a pipeline is its **exclusive**
    reach, not `reach(E)`; the shared remainder is drawn as context and is
    reported in the document's `pipelines[]` block as `sharedCount`. Deliberately
    NOT merged into `scope_catalog`: the MCP `mlview_graph {scope:"units"}`
    catalogue prefixes every row with `unit:` from its `qualname`
    (`claude-plugin/server/mlview_scope.py`), so a pipeline row there would
    render as a selector that does not resolve.
    """
    index = build_index(graph)
    if len(index.non_empty) < 2:
        return []
    nodes = list(graph.get("nodes") or [])
    issues = [i for i in graph.get("issues") or [] if not i.get("suppressed")]
    rows: List[Dict[str, Any]] = []
    for entrypoint in index.non_empty:
        core = index.core_of(entrypoint)
        inside = set(core)
        counts = dict(_ZERO_COUNTS)
        for issue in issues:
            if any(n in inside for n in issue.get("nodeIds") or []):
                severity = issue.get("severity")
                if severity in counts:
                    counts[severity] += 1
        seeds = [n["id"] for n in nodes
                 if (n.get("loc") or {}).get("file") == entrypoint]
        rows.append({
            "spec": "pipeline:%s" % entrypoint,
            "kind": "pipeline",
            "nodeId": seeds[0] if seeds else "",
            "label": entrypoint.rsplit("/", 1)[-1],
            "qualname": entrypoint,
            "file": entrypoint,
            "line": 1,
            "nodeCount": len(core),
            "issueCounts": counts,
            "maxSeverity": _max_severity(counts),
        })
    return rows
