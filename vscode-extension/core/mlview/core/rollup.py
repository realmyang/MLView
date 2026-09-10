"""PERF-04: `--max-nodes` is a hierarchical ROLLUP, not a deletion.

CONTRACTS 11.46. The cap is a **graph** cap on the finished document (section 3),
applied after the rules and BEFORE projection (11.2.2, unchanged). What changed
is what "over budget" does.

The old cap kept the highest-priority `N` nodes and deleted the rest, then kept
only the edges whose **both** endpoints happened to survive - so edges died far
faster than nodes and a 400-node view of a 500-file repo was a third
disconnected. This module folds instead:

1. an op-level child folds into its parent unit,
2. then a whole file folds into one synthesized summary node,
3. then a whole directory folds into one, climbing to the workspace root (a
   stated deviation from the ROADMAP entry - see `_fold_dirs`),
4. and only then, when the budget is smaller than the number of top-level
   directories, the old deletion runs.

Edges are re-pointed at the surviving ancestor, parallels are merged into one
carrying a `weight`, and an edge whose two endpoints landed on the same survivor
is **absorbed** (it became internal to a rolled-up node) rather than dropped.
Nothing here can change an uncapped document: `apply_node_budget` returns before
touching anything when the graph is within budget.

Pure with respect to the filesystem and the clock. Deterministic: every ordering
is a total order over document-order keys, never set-iteration order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..ir.model import Loc
from .graph import STAGE_ORDER, Diagnostic, Edge, MLGraph, Node
from .ids import digest12, edge_id

__all__ = ["apply_node_budget", "RollupReport", "FILE_ROLLUP_KIND",
           "DIR_ROLLUP_KIND"]

#: The `kind` slot of the §0 id recipe for a synthesized file summary node. It
#: is deliberately NOT a `NodeKind`, so a summary id can never collide with an
#: analyzed node's id and is stable across budgets.
FILE_ROLLUP_KIND = "file-rollup"
#: The same, one level up, for a directory summary.
DIR_ROLLUP_KIND = "dir-rollup"

_MAX_CHAIN = 64
_MAX_GHOST_ROUNDS = 8


@dataclass
class RollupReport:
    """What the cap did, in the words the diagnostic uses (11.46 D)."""

    budget: int
    folded: int = 0              # nodes that folded into a survivor
    units_absorbing: int = 0     # units that absorbed their op children
    files_summarised: int = 0    # files that became one summary node
    dirs_summarised: int = 0     # directories that became one summary node
    dropped: int = 0             # nodes deleted by phase 3
    kept: int = 0
    lost_issues: int = 0
    edges_merged: int = 0        # parallel members removed by the merge
    edges_absorbed: int = 0      # both endpoints landed on one survivor
    edges_lost: int = 0          # an endpoint was dropped outright

    @property
    def rolled_up(self) -> bool:
        return self.folded > 0

    def message(self) -> str:
        """The `truncated` diagnostic. Must keep the two phrases 11.46 D pins:
        the word `budget`, and `<n> node(s) kept` for the document actually
        emitted."""
        if self.rolled_up:
            head = ("Graph cap (--max-nodes budget) %d reached: %d node(s) rolled up "
                    "into their surviving ancestor (%d unit(s) absorbed their "
                    "operations, %d file(s) and %d director(ies) summarised), "
                    "%d node(s) dropped, %d node(s) kept."
                    % (self.budget, self.folded, self.units_absorbing,
                       self.files_summarised, self.dirs_summarised, self.dropped,
                       self.kept))
        else:
            head = ("Graph cap (--max-nodes budget) %d reached: nothing could be "
                    "rolled up, %d node(s) dropped, %d node(s) kept."
                    % (self.budget, self.dropped, self.kept))
        edges = ("%d parallel edge(s) merged into one carrying a weight, %d absorbed "
                 "into a rolled-up node, %d lost an endpoint."
                 % (self.edges_merged, self.edges_absorbed, self.edges_lost))
        tail = ("Raise --max-nodes, or narrow the analyzed path, to see the rest.")
        issues = ("%d finding(s) had no surviving node and went with them. "
                  % self.lost_issues) if self.lost_issues else ""
        return " ".join([head, edges, issues + tail])


# --------------------------------------------------------------- entry point
def apply_node_budget(graph: MLGraph, max_nodes: int) -> Optional[RollupReport]:
    """Bring `graph` within `max_nodes` by rolling up, then dropping.

    Returns `None` - having mutated nothing - when the document is already
    within budget, which is what makes 11.46's "it cannot change any uncapped
    document" true by construction rather than by test.
    """
    if max_nodes <= 0 or len(graph.nodes) <= max_nodes:
        return None

    nodes = list(graph.nodes)
    by_id: Dict[str, Node] = {n.id: n for n in nodes}
    children: Dict[str, List[str]] = {}
    for node in nodes:
        if node.parent and node.parent in by_id:
            children.setdefault(node.parent, []).append(node.id)
    anchored: Dict[str, Set[str]] = {}
    for issue in graph.issues:
        for node_id in issue.nodeIds:
            if node_id in by_id:
                anchored.setdefault(node_id, set()).add(issue.id)

    report = RollupReport(budget=max_nodes)
    merged: Dict[str, str] = {}                 # folded node -> its fold target
    summaries: List[Node] = []
    alive = len(nodes)

    alive = _fold_ops(nodes, by_id, children, anchored, merged, alive,
                      max_nodes, report)
    if alive > max_nodes:
        alive = _fold_files(graph, nodes, by_id, anchored, merged, summaries,
                            alive, max_nodes, report)
    if alive > max_nodes:
        alive = _fold_dirs(graph, nodes, by_id, anchored, merged, summaries,
                           alive, max_nodes, report)

    # A file summary the directory phase then folded is NOT a survivor: it is
    # merged like any other node, and only the summaries still standing count.
    survivors = ([n for n in nodes if n.id not in merged]
                 + [s for s in summaries if s.id not in merged])
    keep_ids = _choose_survivors(graph, survivors, by_id, merged, anchored,
                                 max_nodes)
    report.dropped = len(survivors) - len(keep_ids)

    _rewrite(graph, nodes, by_id, merged, summaries, keep_ids, report)
    graph.truncated = True
    graph.diagnostics.append(Diagnostic(
        kind="truncated", message=report.message(),
        count=len(nodes) - len(graph.nodes) + len(summaries)))
    return report


# ------------------------------------------------------------ phase 1: ops
def _fold_ops(nodes: Sequence[Node], by_id: Dict[str, Node],
              children: Dict[str, List[str]], anchored: Dict[str, Set[str]],
              merged: Dict[str, str], alive: int, max_nodes: int,
              report: RollupReport) -> int:
    """Fold each unit's non-ghost `op` children into the unit (11.46 A1).

    A ghost is never folded (11.46 A5): it exists to draw a call the code should
    have made and does not, and that is the most legible finding MLView draws.
    """
    groups: List[Tuple[int, int, tuple, str, List[str]]] = []
    for node in nodes:
        kids = [c for c in children.get(node.id, ())
                if by_id[c].level == "op" and not by_id[c].ghost]
        if not kids:
            continue
        issues: Set[str] = set()
        for kid in kids:
            issues |= anchored.get(kid, set())
        groups.append((len(issues), -len(kids), tuple(node.sort_key), node.id, kids))
    groups.sort(key=lambda g: g[:3])

    for _issues, _size, _key, parent_id, kids in groups:
        if alive <= max_nodes:
            break
        for kid in kids:
            merged[kid] = parent_id
        alive -= len(kids)
        report.folded += len(kids)
        report.units_absorbing += 1
    return alive


# ---------------------------------------------------------- phase 2: files
def _fold_files(graph: MLGraph, nodes: Sequence[Node], by_id: Dict[str, Node],
                anchored: Dict[str, Set[str]], merged: Dict[str, str],
                summaries: List[Node], alive: int, max_nodes: int,
                report: RollupReport) -> int:
    """Fold a whole file's survivors into one summary node (11.46 A2/A3)."""
    per_file: Dict[str, List[str]] = {}
    for node in nodes:
        if node.id in merged or node.ghost:
            continue
        per_file.setdefault(node.loc.file, []).append(node.id)

    rows: List[Tuple[int, int, str, List[str]]] = []
    for path, ids in per_file.items():
        if len(ids) < 2:                       # folding one node into one saves 0
            continue
        issues: Set[str] = set()
        for node_id in ids:
            issues |= anchored.get(node_id, set())
        rows.append((len(issues), -len(ids), path, ids))
    rows.sort(key=lambda r: r[:3])

    used: Set[str] = set(by_id)
    for _issues, _size, path, ids in rows:
        if alive <= max_nodes:
            break
        summary = _file_summary(graph.root, path, [by_id[i] for i in ids], used)
        used.add(summary.id)
        summaries.append(summary)
        for node_id in ids:
            merged[node_id] = summary.id
        alive -= len(ids) - 1
        report.folded += len(ids)
        report.files_summarised += 1
    return alive


def _majority(values: Sequence[str], tiebreak) -> str:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts, key=lambda v: (-counts[v], tiebreak(v)))[0]


def _file_summary(root: str, path: str, members: Sequence[Node],
                  used: Set[str]) -> Node:
    """One synthesized summary node for the file `path` (11.46 A3)."""
    return _summary(root, path, "file", FILE_ROLLUP_KIND, path,
                    path.rsplit("/", 1)[-1], members, used,
                    Loc(file=path, absFile="%s/%s" % (root, path), line=1, col=0,
                        endLine=1, endCol=0))


def _dir_summary(root: str, folder: str, members: Sequence[Node],
                 used: Set[str]) -> Node:
    """One synthesized summary node for the directory `folder` (11.46 A3b).

    Its `loc` is the **first member's own location**, not the directory: a
    directory is not a place an editor can open, and click-to-code must land
    somewhere real (CONTRACTS section 0 / R2.1).
    """
    label = ("%s/" % folder) if folder else "./"
    node = _summary(root, folder, "dir", DIR_ROLLUP_KIND, label, label,
                    members, used, members[0].loc)
    node.attrs["rollupPath"] = folder
    return node


def _summary(root: str, path: str, rollup: str, id_kind: str, qualname: str,
             label: str, members: Sequence[Node], used: Set[str],
             loc: Loc) -> Node:
    """The shared shape of a rollup summary node (11.46 A3).

    `level` is `stage` because it may end up parenting a `unit` or an `op` from
    any file and CONTRACTS 1.1.2 requires a parent to sit at a strictly lower
    level. It carries no parent of its own, which is what every `stage`-level
    node does and what keeps the forest a forest.
    """
    node_id = "n:" + digest12("%s|%s|%s" % (path, path, id_kind))
    salt = ""
    while node_id in used:                     # defensive; a 48-bit collision
        salt += "!"
        node_id = "n:" + digest12("%s|%s|%s%s" % (path, path, id_kind, salt))
    return Node(
        id=node_id,
        kind=_majority([m.kind for m in members], lambda v: v),
        level="stage",
        stage=_majority([m.stage for m in members],
                        lambda v: STAGE_ORDER.get(v, 99)),
        label=label,
        qualname=qualname,
        loc=loc,
        sublabel="%d nodes rolled up" % len(members),
        parent=None,
        attrs={"rollup": rollup},
        ghost=False,
        dynamic=any(m.dynamic for m in members),
        confidence=max(m.confidence for m in members),
        collapsedByDefault=True,
    )


def _bucket(node: Node) -> str:
    """The directory a node folds into. A directory summary folds into its
    PARENT directory, which is what lets the phase climb the tree."""
    if node.attrs.get("rollup") == "dir":
        folder = node.attrs.get("rollupPath", "")
        return folder.rsplit("/", 1)[0] if "/" in folder else ""
    path = node.loc.file
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _fold_dirs(graph: MLGraph, nodes: Sequence[Node], by_id: Dict[str, Node],
               anchored: Dict[str, Set[str]], merged: Dict[str, str],
               summaries: List[Node], alive: int, max_nodes: int,
               report: RollupReport) -> int:
    """Fold a directory's survivors into one summary node (11.46 A3b).

    Normative in CONTRACTS 11.46 A3b. **Deviation, stated.** The ROADMAP entry
    names two fold tiers - operations into their unit, then a file - and then
    deletion. Two tiers bottom out at
    *one node per file*, so on the 525-file synthetic at `--max-nodes 400` the
    budget is structurally unreachable by folding and 147 file summaries had to
    be deleted, taking 1023 edges with them (measured: 5.6% edge retention,
    79.8% isolated). A directory tier is the same fold one level up, it keeps
    the graph connected at **any** budget, and it is strictly better than the
    deletion it replaces - a folded node still carries its findings, a deleted
    one does not. Deletion remains, for the case where even one node per
    top-level directory does not fit.

    Rounds are recomputed each time, so a directory summary folds into its
    parent on the next round and the phase climbs to the workspace root.
    """
    while alive > max_nodes:
        living = [n for n in nodes if n.id not in merged and not n.ghost]
        living += [s for s in summaries if s.id not in merged]
        groups: Dict[str, List[Node]] = {}
        for node in living:
            groups.setdefault(_bucket(node), []).append(node)
        rows: List[Tuple[int, int, str, List[Node]]] = []
        for folder, members in groups.items():
            if len(members) < 2:
                continue
            issues: Set[str] = set()
            for member in members:
                issues |= anchored.get(member.id, set())
            rows.append((len(issues), -len(members), folder, members))
        if not rows:
            return alive
        rows.sort(key=lambda r: r[:3])
        _issues, _size, folder, members = rows[0]
        used = set(by_id) | {s.id for s in summaries}
        summary = _dir_summary(graph.root, folder, members, used)
        summaries.append(summary)
        for member in members:
            merged[member.id] = summary.id
        alive -= len(members) - 1
        report.folded += len(members)
        report.dirs_summarised += 1
    return alive


# ----------------------------------------------------------- phase 3: drop
def _choose_survivors(graph: MLGraph, survivors: Sequence[Node],
                      by_id: Dict[str, Node], merged: Dict[str, str],
                      anchored: Dict[str, Set[str]], max_nodes: int) -> Set[str]:
    """The pre-PERF-04 deletion order, over whatever the folds left (11.46 A4).

    Unchanged in substance: ghosts and each issue's FIRST anchor outrank every
    issue's later anchors, then ancestors, then units, then ops. The one
    difference is that an anchor is resolved **through the fold** first, so an
    issue that now lives on a file summary protects that summary.
    """
    if len(survivors) <= max_nodes:
        return {n.id for n in survivors}

    live = {n.id for n in survivors}

    def resolved(node_id: str) -> str:
        return _resolve(node_id, merged)

    primary = {n.id for n in survivors if n.ghost}
    anchors = set(primary)
    for issue in graph.issues:
        ids = [resolved(n) for n in issue.nodeIds]
        ids = [i for i in ids if i in live]
        if ids:
            primary.add(ids[0])
        anchors.update(ids)

    def chain(node_id: str) -> List[str]:
        out: List[str] = []
        node = by_id.get(node_id)
        parent = by_id.get(node.parent or "") if node is not None else None
        while parent is not None and len(out) < 32:
            out.append(resolved(parent.id))
            parent = by_id.get(parent.parent or "")
        return out

    ancestors: Set[str] = set()
    for node_id in anchors:
        ancestors.update(p for p in chain(node_id) if p in live)
    ancestors -= anchors

    def tier(node: Node) -> int:
        if node.id in primary:
            return 0
        if node.id in anchors:
            return 1
        if node.id in ancestors:
            return 2
        return 3 if node.level != "op" else 4

    ordered = sorted(survivors,
                     key=lambda n: (tier(n), len(chain(n.id))) + tuple(n.sort_key))
    return {n.id for n in ordered[:max_nodes]}


# --------------------------------------------------------------- rewriting
def _resolve(node_id: str, merged: Dict[str, str]) -> str:
    seen = 0
    while node_id in merged and seen < _MAX_CHAIN:
        node_id = merged[node_id]
        seen += 1
    return node_id


def _rewrite(graph: MLGraph, nodes: Sequence[Node], by_id: Dict[str, Node],
             merged: Dict[str, str], summaries: Sequence[Node],
             keep_ids: Set[str], report: RollupReport) -> None:
    """Apply the plan: nodes, parents, edges, issues, then the ghost sweep."""

    def survivor(node_id: Optional[str]) -> Optional[str]:
        """The node that stands for `node_id` in the emitted document."""
        if not node_id:
            return None
        target = _resolve(node_id, merged)
        if target in keep_ids:
            return target
        current = by_id.get(target)
        guard = 0
        while current is not None and guard < _MAX_CHAIN:
            parent = current.parent
            if not parent:
                return None
            candidate = _resolve(parent, merged)
            if candidate in keep_ids:
                return candidate
            current = by_id.get(parent)
            guard += 1
        return None

    kept_nodes = [n for n in nodes if n.id in keep_ids]
    kept_nodes += [s for s in summaries if s.id in keep_ids]
    kept_index = {n.id: n for n in kept_nodes}

    # `rolledUp` counts folds only: a node the drop phase deleted was not
    # summarised by anybody, and the diagnostic counts it separately.
    for node in list(nodes):
        if node.id in keep_ids:
            continue
        target = _resolve(node.id, merged)
        if target in kept_index and node.id in merged:
            kept_index[target].rolledUp += 1
    for summary in summaries:
        if summary.id in kept_index:
            summary.sublabel = "%d nodes rolled up" % summary.rolledUp

    for node in kept_nodes:
        parent = survivor(node.parent) if node.parent else None
        node.parent = parent if parent != node.id else None

    graph.nodes = kept_nodes
    edge_map = _rewrite_edges(graph, survivor, report)
    _rewrite_issues(graph, survivor, edge_map, report)
    _sweep_ghosts(graph)
    _relink(graph)
    report.kept = len(graph.nodes)


def _rewrite_edges(graph: MLGraph, survivor, report: RollupReport) -> Dict[str, str]:
    """Re-point, absorb self-loops, merge parallels into one `weight` (11.46 B2)."""
    groups: Dict[Tuple[str, str, str], List[Edge]] = {}
    order: List[Tuple[str, str, str]] = []
    remap: Dict[str, Tuple[str, str, str]] = {}
    for edge in graph.edges:
        source = survivor(edge.source)
        target = survivor(edge.target)
        if source is None or target is None:
            report.edges_lost += 1
            continue
        if source == target:
            report.edges_absorbed += 1
            continue
        key = (source, edge.kind, target)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(edge)
        remap[edge.id] = key

    out: List[Edge] = []
    new_id: Dict[Tuple[str, str, str], str] = {}
    for key in order:
        members = groups[key]
        first = members[0]
        labels = {e.label for e in members}
        label = first.label if len(labels) == 1 else None
        source, kind, target = key
        merged_id = edge_id(source, kind, target, label or "")
        new_id[key] = merged_id
        issue_ids: Set[str] = set()
        for member in members:
            issue_ids.update(member.issueIds)
        out.append(Edge(
            id=merged_id, kind=kind, source=source, target=target,
            loc=first.loc, subkind=first.subkind, label=label, tags=first.tags,
            confidence=max(e.confidence for e in members),
            issueIds=sorted(issue_ids),
            weight=len(members),
        ))
        report.edges_merged += len(members) - 1
    graph.edges = out
    return {old: new_id[key] for old, key in remap.items()}


def _rewrite_issues(graph: MLGraph, survivor, edge_map: Dict[str, str],
                    report: RollupReport) -> None:
    """Re-anchor every issue through the fold (11.46 B4). A fold never drops
    one; only the deletion phase can, and it is counted."""
    kept: List = []
    for issue in graph.issues:
        node_ids: List[str] = []
        for node_id in issue.nodeIds:
            mapped = survivor(node_id)
            if mapped and mapped not in node_ids:
                node_ids.append(mapped)
        edge_ids: List[str] = []
        for edge_id_ in issue.edgeIds:
            mapped_edge = edge_map.get(edge_id_)
            if mapped_edge and mapped_edge not in edge_ids:
                edge_ids.append(mapped_edge)
        if not node_ids:
            report.lost_issues += 1
            continue
        issue.nodeIds = node_ids
        issue.edgeIds = edge_ids
        kept.append(issue)
    graph.issues = kept


def _sweep_ghosts(graph: MLGraph) -> None:
    """Invariant 1.1.8 on the way out: a surviving ghost whose only finding was
    lost by the deletion phase is removed, then edges and anchors re-filtered."""
    for _ in range(_MAX_GHOST_ROUNDS):
        live = {i.id for i in graph.issues}
        doomed = {n.id for n in graph.nodes
                  if n.ghost and not any(i in live for i in n.issueIds)}
        if not doomed:
            return
        graph.nodes = [n for n in graph.nodes if n.id not in doomed]
        graph.edges = [e for e in graph.edges
                       if e.source not in doomed and e.target not in doomed]
        edge_ids = {e.id for e in graph.edges}
        survivors = []
        for issue in graph.issues:
            issue.nodeIds = [n for n in issue.nodeIds if n not in doomed]
            issue.edgeIds = [e for e in issue.edgeIds if e in edge_ids]
            if issue.nodeIds:
                survivors.append(issue)
        graph.issues = survivors


def _relink(graph: MLGraph) -> None:
    """Rebuild the reverse links so both directions of the node <-> issue and
    edge <-> issue checks in `contracts/validate_sample.py` hold, and drop a
    parent that the deletion phase removed."""
    node_ids = {n.id for n in graph.nodes}
    by_node: Dict[str, Set[str]] = {}
    by_edge: Dict[str, Set[str]] = {}
    for issue in graph.issues:
        for node_id in issue.nodeIds:
            by_node.setdefault(node_id, set()).add(issue.id)
        for edge in issue.edgeIds:
            by_edge.setdefault(edge, set()).add(issue.id)
    for node in graph.nodes:
        node.issueIds = sorted(by_node.get(node.id, ()))
        if node.parent and node.parent not in node_ids:
            node.parent = None
    for edge in graph.edges:
        edge.issueIds = sorted(by_edge.get(edge.id, ()))
