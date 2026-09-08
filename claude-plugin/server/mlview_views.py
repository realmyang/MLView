"""Filtered views of a graph document, and the text shapes they render into.

Split out of ``mlview_payloads`` so each module stays readable: this one is only
about *which part of the graph* a `mlview_graph` call is talking about, and how a
stage summary or a node/edge index is spelled.  ``mlview_payloads`` keeps the
per-tool result assembly and the budget.

Pure — no filesystem, no network and no MCP SDK.  Since the scoped-view feature
landed it *does* import the analyzer core: ``stage_scope_ids`` and
``neighbourhood_ids`` are now thin delegating wrappers over
``mlview.core.project`` (CONTRACTS 11.10), so this server can never acquire a
second, drifting copy of the projection algorithm.

The one rule worth stating twice, because it produced a confirmed defect: a
FILTERED view never restates project-level truth.  ``subgraph`` recounts
``nodeCount`` for the selection but carries ``stage.present`` through untouched,
because both renderers print a "not detected" line from ``present`` — and a scoped
view that recomputed it told the model that seven stages the project actually has
were missing, which ``commands/mlview.md`` instructs it to report as a finding.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Set, Tuple

from mlview.api import ScopeError, parse_scope, project, resolve_scope

__all__ = [
    "stage_summary_text", "stage_summary_mermaid", "subgraph",
    "stage_scope_ids", "neighbourhood_ids", "json_index",
]


def stage_summary_text(graph: Dict[str, Any]) -> str:
    lines = ["stage          nodes  max severity"]
    for stage in graph.get("stages", []):
        if not stage.get("present"):
            continue
        lines.append(
            "%-13s %6d  %s"
            % (stage.get("id", "?"), stage.get("nodeCount", 0), stage.get("maxSeverity") or "-")
        )
    absent = [s.get("id") for s in graph.get("stages", []) if not s.get("present")]
    if absent:
        lines.append("not detected: " + ", ".join(a for a in absent if a))
    return "\n".join(lines)


def stage_summary_mermaid(graph: Dict[str, Any]) -> str:
    lines = ["flowchart TB"]
    present = [s for s in graph.get("stages", []) if s.get("present")]
    for stage in present:
        sid = stage.get("id", "unknown")
        label = "%s<br/>%d nodes%s" % (
            stage.get("label", sid),
            stage.get("nodeCount", 0),
            "" if not stage.get("maxSeverity") else " · max %s" % stage["maxSeverity"],
        )
        lines.append('  stage_%s["%s"]' % (sid, label))
    for a, b in zip(present, present[1:]):
        lines.append("  stage_%s --> stage_%s" % (a.get("id"), b.get("id")))
    absent = [s.get("id") for s in graph.get("stages", []) if not s.get("present")]
    if absent:
        lines.append("  %% not detected: " + ", ".join(a for a in absent if a))
    return "\n".join(lines)


def subgraph(graph: Dict[str, Any], node_ids: Set[str]) -> Dict[str, Any]:
    """A schema-shaped graph restricted to ``node_ids``.

    Parents that fall outside the selection are re-pointed to ``None`` so the
    result is still a forest, edges are kept only when both endpoints survive,
    and the stage rows are recounted so a renderer sees a consistent document.
    """
    nodes = [dict(n) for n in graph.get("nodes", []) if n.get("id") in node_ids]
    for node in nodes:
        if node.get("parent") not in node_ids:
            node["parent"] = None
    edges = [
        e
        for e in graph.get("edges", [])
        if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    kept_issue_ids = {i for n in nodes for i in (n.get("issueIds") or [])}
    issues = [i for i in graph.get("issues", []) if i.get("id") in kept_issue_ids]

    stages = []
    for stage in graph.get("stages", []):
        row = dict(stage)
        members = [n for n in nodes if n.get("stage") == stage.get("id")]
        counts = {"low": 0, "medium": 0, "high": 0}
        for issue in issues:
            if issue.get("stage") == stage.get("id") and issue.get("severity") in counts:
                counts[issue["severity"]] += 1
        row["nodeCount"] = len(members)
        # `present` stays the PROJECT-level truth. Recomputing it from the members
        # of a filtered view made `scope="stage:train"` report all eight stages as
        # "not detected" — a false statement that `commands/mlview.md` then tells
        # the model to report as a finding. Renderers already skip a lane with no
        # nodes in it, so nothing draws an empty band because of this.
        row["present"] = bool(stage.get("present"))
        row["issueCounts"] = counts
        row["maxSeverity"] = next(
            (s for s in ("high", "medium", "low") if counts[s]), None
        )
        stages.append(row)

    out = dict(graph)
    out["nodes"] = nodes
    out["edges"] = edges
    out["issues"] = issues
    out["stages"] = stages
    stats = dict(graph.get("stats", {}))
    stats["nodes"] = len(nodes)
    stats["edges"] = len(edges)
    out["stats"] = stats
    return out


def stage_scope_ids(graph: Dict[str, Any], stage_id: str) -> Set[str]:
    """The nodes of one stage lane — the `core` of `stage:<id>` (CONTRACTS 11.2).

    A thin delegating wrapper over ``mlview.core.project``: the selection rule
    lives in the analyzer, not here, so the plugin and the CLI can never disagree
    about what "the train lane" means. A stage id outside the eight canonical ones
    selects nothing, exactly as this returned an empty set before; callers that
    want that spelled as an error validate the id themselves (`graph_payload`
    does, and says so in the message the model reads).
    """
    try:
        scope = parse_scope("stage:%s" % stage_id, 0)
    except ScopeError:
        return set()
    return set(resolve_scope(graph, scope).core)


def neighbourhood_ids(graph: Dict[str, Any], node_id: str, depth: int = 1) -> Set[str]:
    """``node_id`` plus its projection at ``depth`` hops — `node:<id>` (11.2).

    A thin delegating wrapper over ``mlview.core.project``. The kept set is
    `core ∪ boundary ∪ context`: the node itself, `depth` rings of edge
    neighbours in **both** directions, and the `parent` ancestors that keep the
    result a forest. That last part is what the hand-rolled BFS this replaced got
    wrong — it climbed one parent per ring from the frontier only, so a boundary
    node could be drawn with no frame around it.
    """
    scope = parse_scope("node:%s" % node_id, depth)
    return {n["id"] for n in project(graph, scope).get("nodes", [])}


def json_index(view: Dict[str, Any], budget: int) -> Tuple[str, bool]:
    """A node/edge index as a JSON string, shedding rows until it fits ``budget``.

    A one-line JSON blob cannot be clipped by line without becoming unparseable,
    so this drops whole rows instead — edges first, since a node with its file and
    line is the more useful half for an agent that wants to go and read something.
    """
    nodes = [
        {
            "id": n.get("id"), "kind": n.get("kind"), "stage": n.get("stage"),
            "label": n.get("label"), "file": (n.get("loc") or {}).get("file"),
            "line": (n.get("loc") or {}).get("line"),
        }
        for n in view.get("nodes", [])
    ]
    edges = [
        {"source": e.get("source"), "target": e.get("target"),
         "kind": e.get("kind"), "label": e.get("label")}
        for e in view.get("edges", [])
    ]
    total_nodes, total_edges = len(nodes), len(edges)

    def encode() -> str:
        payload: Dict[str, Any] = {"nodes": nodes, "edges": edges}
        if len(nodes) < total_nodes or len(edges) < total_edges:
            payload["truncated"] = {
                "nodes": "%d of %d" % (len(nodes), total_nodes),
                "edges": "%d of %d" % (len(edges), total_edges),
            }
        return json.dumps(payload, ensure_ascii=False)

    def halve(rows: List[Dict[str, Any]]) -> None:
        # Halving converges in log(n) encodes; popping one row at a time on a
        # 500-node graph would re-serialize hundreds of times.
        if len(rows) > 8:
            del rows[len(rows) // 2:]
        else:
            rows.pop()

    text = encode()
    while len(text.encode("utf-8")) > budget and (edges or nodes):
        # Shed from whichever side is currently larger, so an index never comes
        # back as 25 nodes and zero edges — the connections are half the answer.
        if edges and (len(edges) >= len(nodes) or not nodes):
            halve(edges)
        else:
            halve(nodes)
        text = encode()
    return text, (len(nodes) < total_nodes or len(edges) < total_edges)


