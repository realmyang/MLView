/**
 * Graph index — hierarchy, adjacency and issue aggregation.
 *
 * Everything here is derived deterministically from the document's own ordering
 * (CONTRACTS section 0, "Ordering"), so two runs over the same bytes produce the
 * same structures in the same order.
 */

import type { IssueCounts, Issue, MLEdge, MLGraph, MLNode, Severity, Stage } from '../types.js';
import { emptyCounts, normalizeSeverity } from '../markers.js';

export interface IssuePredicate {
  (issue: Issue): boolean;
}

/**
 * Viewer M2: how many phase colours there are (`--mlv-phase-0` … `--mlv-phase-7` in
 * styles/tokens.css). Phase i (document order) takes tone i mod PHASE_TONES, so every authored
 * phase gets a colour whatever its id; past eight phases the colours repeat and the lane label
 * tells them apart.
 */
export const PHASE_TONES = 8;

export function phaseTone(phaseIndex: number): number {
  return ((phaseIndex % PHASE_TONES) + PHASE_TONES) % PHASE_TONES;
}

export class GraphIndex {
  readonly graph: MLGraph;
  readonly nodeById = new Map<string, MLNode>();
  readonly edgeById = new Map<string, MLEdge>();
  readonly issueById = new Map<string, Issue>();
  /** Each finding's position in the document, so a union of lists keeps document order. */
  private readonly issueRank = new Map<string, number>();
  /** Hierarchy children as the DOCUMENT declares them, in document order. */
  readonly childrenOf = new Map<string, string[]>();
  /** The document's own `parent` field, cycle-guarded. Rarely what you want. */
  readonly lexicalParentOf = new Map<string, string | null>();
  /** Children that share the parent's stage — the ones drawn inside the group box. */
  readonly laneChildrenOf = new Map<string, string[]>();
  /**
   * The DRAWN parent: the lexical parent when it shares this node's stage, else
   * null. A child whose parent sits in another lane is promoted to a root of its
   * own lane (see `rootsByLane`), so no box contains it and nothing about it may
   * be derived from the lexical chain — collapsing the lexical parent must not
   * hide it, and the parent's collapsed badge must not count it.
   */
  readonly parentOf = new Map<string, string | null>();
  readonly rootsByLane = new Map<string, string[]>();
  readonly outEdges = new Map<string, MLEdge[]>();
  readonly inEdges = new Map<string, MLEdge[]>();
  readonly lanes: Stage[] = [];
  readonly absentStages: Stage[] = [];
  /**
   * Stages the FULL analysis has but this PROJECTION does not draw. Only ever
   * populated while `graph.view` is present; `ui/chrome.ts` renders them as a
   * "not in this scope" chip row beside the existing "not detected" one, so the
   * information is not lost — it is correctly labelled (CONTRACTS 11.4 F3).
   */
  readonly outOfScopeStages: Stage[] = [];
  /**
   * Viewer M2: each phase's position in the document (0-based), the key of its colour. Taken
   * from the declared phases in authored order, so it does not shift when a scope hides a lane;
   * a stage id that only appears on nodes comes after them.
   */
  private readonly phaseOrder = new Map<string, number>();

  constructor(graph: MLGraph) {
    this.graph = graph;
    for (const n of graph.nodes || []) this.nodeById.set(n.id, n);
    for (const e of graph.edges || []) this.edgeById.set(e.id, e);
    for (const i of graph.issues || []) {
      this.issueById.set(i.id, i);
      if (!this.issueRank.has(i.id)) this.issueRank.set(i.id, this.issueRank.size);
    }

    for (const n of graph.nodes || []) {
      const parent = n.parent && this.nodeById.has(n.parent) ? n.parent : null;
      this.lexicalParentOf.set(n.id, parent);
      if (parent) push(this.childrenOf, parent, n.id);
    }
    // Guard against a malformed document: a parent cycle must not hang the render.
    for (const n of graph.nodes || []) {
      if (this.hasCycle(n.id)) this.lexicalParentOf.set(n.id, null);
    }

    for (const n of graph.nodes || []) {
      const parent = this.lexicalParentOf.get(n.id) || null;
      const parentNode = parent ? this.nodeById.get(parent) : undefined;
      const sameLane = !!parentNode && parentNode.stage === n.stage;
      this.parentOf.set(n.id, sameLane ? parent : null);
      if (sameLane) push(this.laneChildrenOf, parent!, n.id);
      else push(this.rootsByLane, n.stage, n.id);
    }

    for (const e of graph.edges || []) {
      if (!this.nodeById.has(e.source) || !this.nodeById.has(e.target)) continue;
      push(this.outEdges, e.source, e);
      push(this.inEdges, e.target, e);
    }

    const declared = new Map<string, Stage>();
    for (const s of graph.stages || []) declared.set(s.id, s);
    const ordered = (graph.stages || []).slice().sort((a, b) => a.order - b.order || cmp(a.id, b.id));
    // `stage.present` is PROJECT-LEVEL truth and a projection carries it through
    // verbatim, so under a scope it no longer implies "this lane has content":
    // a narrow scope leaves other phases present at nodeCount 0, and admitting
    // them here drew empty swimlane bands. While a view is present a lane is
    // admitted ONLY when it has drawn roots (CONTRACTS 11.4 F3).
    const projected = !!graph.view;
    for (const s of ordered) {
      const drawn = (this.rootsByLane.get(s.id) || []).length > 0;
      if (drawn || (!projected && s.present)) this.lanes.push(s);
      else if (projected && s.present) this.outOfScopeStages.push(s);
      else this.absentStages.push(s);
    }
    // Forward compatibility: a stage id that only appears on nodes still gets a lane.
    const seen = new Set(this.lanes.map((l) => l.id));
    const unknownStages: string[] = [];
    for (const n of graph.nodes || []) {
      if (!declared.has(n.stage) && !seen.has(n.stage)) {
        seen.add(n.stage);
        unknownStages.push(n.stage);
      }
    }
    unknownStages.sort();
    for (const s of ordered) if (!this.phaseOrder.has(s.id)) this.phaseOrder.set(s.id, this.phaseOrder.size);
    for (const id of unknownStages) this.phaseOrder.set(id, this.phaseOrder.size);
    let order = this.lanes.length ? this.lanes[this.lanes.length - 1].order + 1 : 0;
    for (const id of unknownStages) {
      this.lanes.push({
        id,
        label: id,
        order: order++,
        present: true,
        nodeCount: (this.rootsByLane.get(id) || []).length,
        issueCounts: emptyCounts(),
        maxSeverity: null,
      });
    }
  }

  /** Viewer M2: the phase's document position (0-based), or 0 for an id this index never saw. */
  phaseIndexOf(stageId: string): number {
    return this.phaseOrder.get(stageId) ?? 0;
  }

  private hasCycle(start: string): boolean {
    let cur = this.lexicalParentOf.get(start) || null;
    let hops = 0;
    while (cur) {
      if (cur === start) return true;
      if (++hops > 4096) return true;
      cur = this.lexicalParentOf.get(cur) || null;
    }
    return false;
  }

  children(id: string): string[] {
    return this.childrenOf.get(id) || [];
  }

  laneChildren(id: string): string[] {
    return this.laneChildrenOf.get(id) || [];
  }

  roots(laneId: string): string[] {
    return this.rootsByLane.get(laneId) || [];
  }

  /** The chain of boxes that visually CONTAIN `id`, innermost first. */
  ancestors(id: string): string[] {
    const out: string[] = [];
    let cur = this.parentOf.get(id) || null;
    while (cur) {
      out.push(cur);
      cur = this.parentOf.get(cur) || null;
    }
    return out;
  }

  isGroup(id: string): boolean {
    return this.laneChildren(id).length > 0;
  }

  /** Own issues of a node, filtered. */
  issuesOf(id: string, keep: IssuePredicate): Issue[] {
    const node = this.nodeById.get(id);
    if (!node) return [];
    const out: Issue[] = [];
    for (const iid of node.issueIds) {
      const issue = this.issueById.get(iid);
      if (issue && keep(issue)) out.push(issue);
    }
    return out;
  }

  issuesOfEdge(id: string, keep: IssuePredicate): Issue[] {
    const edge = this.edgeById.get(id);
    if (!edge) return [];
    const out: Issue[] = [];
    for (const iid of edge.issueIds) {
      const issue = this.issueById.get(iid);
      if (issue && keep(issue)) out.push(issue);
    }
    return out;
  }

  /**
   * The findings of several edges — a merged route's members — each listed
   * ONCE, in document order. Members of one route often share a finding, and
   * listing it per member repeated it on the hover card.
   */
  issuesOfEdges(ids: string[], keep: IssuePredicate): Issue[] {
    if (ids.length === 1) return this.issuesOfEdge(ids[0], keep);
    const seen = new Set<string>();
    const out: Issue[] = [];
    for (const id of ids) addDistinct(out, seen, this.issuesOfEdge(id, keep));
    return this.inDocumentOrder(out);
  }

  private inDocumentOrder(issues: Issue[]): Issue[] {
    return issues.sort((a, b) => (this.issueRank.get(a.id) ?? 0) - (this.issueRank.get(b.id) ?? 0));
  }

  countsFor(issues: Issue[]): IssueCounts {
    const c = emptyCounts();
    for (const i of issues) c[normalizeSeverity(i.severity) as Severity]++;
    return c;
  }

  /** Own counts for a node. */
  ownCounts(id: string, keep: IssuePredicate): IssueCounts {
    return this.countsFor(this.issuesOf(id, keep));
  }

  /**
   * The DISTINCT findings of a box and every CONTAINED descendant, in document
   * order — what a collapsed group stands for. A finding that names the group
   * and a child, or two children, is one finding. Walks the lane hierarchy: a
   * child drawn in another lane carries its own badge there, so counting it
   * here too would double-count it.
   *
   * A connection with both ends inside is hidden when the box is collapsed
   * (`routeEdges`), so its findings are the box's too, or they vanished from
   * the canvas. The box's own self-loop stays drawn on the card, as a step's
   * does, and is left to its own marker.
   */
  subtreeIssues(id: string, keep: IssuePredicate): Issue[] {
    const inside: string[] = [];
    const walk = (at: string) => {
      inside.push(at);
      for (const child of this.laneChildren(at)) walk(child);
    };
    walk(id);
    const members = new Set(inside);
    const seen = new Set<string>();
    const out: Issue[] = [];
    for (const at of inside) {
      addDistinct(out, seen, this.issuesOf(at, keep));
      for (const e of this.outEdges.get(at) || []) {
        if (!members.has(e.target) || (at === id && e.target === id)) continue;
        addDistinct(out, seen, this.issuesOfEdge(e.id, keep));
      }
    }
    return this.inDocumentOrder(out);
  }

  /** What a group's badge counts: `subtreeIssues`, each finding once. */
  subtreeCounts(id: string, keep: IssuePredicate): IssueCounts {
    return this.countsFor(this.subtreeIssues(id, keep));
  }

  /** How many boxes this one contains — i.e. how many collapsing it hides. */
  descendantCount(id: string): number {
    let n = 0;
    for (const child of this.laneChildren(id)) n += 1 + this.descendantCount(child);
    return n;
  }

  /**
   * The DISTINCT findings attached to a node of the lane or to an edge the lane
   * owns (an edge belongs to its source node's lane). Summing per-node and
   * per-edge counts drew 5 on a lane header for one finding that named three
   * steps and two connections, while the toolbar said 1. A finding that touches
   * two lanes is still counted in both: each header says what concerns it.
   */
  laneCounts(laneId: string, keep: IssuePredicate): IssueCounts {
    const seen = new Set<string>();
    const out: Issue[] = [];
    for (const n of this.graph.nodes || []) {
      if (n.stage !== laneId) continue;
      addDistinct(out, seen, this.issuesOf(n.id, keep));
    }
    for (const e of this.graph.edges || []) {
      const src = this.nodeById.get(e.source);
      if (!src || src.stage !== laneId) continue;
      addDistinct(out, seen, this.issuesOfEdge(e.id, keep));
    }
    return this.countsFor(out);
  }

  /** True when a collapsed box CONTAINS `id`, so it is not drawn. */
  isHidden(id: string, collapsed: Set<string>): boolean {
    let cur = this.parentOf.get(id) || null;
    while (cur) {
      if (collapsed.has(cur)) return true;
      cur = this.parentOf.get(cur) || null;
    }
    return false;
  }

  /** The node actually drawn for `id`: itself, or its outermost collapsed ancestor. */
  visibleRepresentative(id: string, collapsed: Set<string>): string {
    const chain = this.ancestors(id);
    for (let i = chain.length - 1; i >= 0; i--) {
      if (collapsed.has(chain[i])) return chain[i];
    }
    return id;
  }

  /**
   * Groups that start collapsed: large subtrees.
   *
   * Campaign 3, issue 6: a group that holds the target of a finding (a node it
   * names, or an end of a connection it names) is never folded by this size
   * rule. The rule folded away the training loop in four of twelve Claude Code
   * shakedown artifacts, and with it every finding placed on the loop, while
   * peripheral groups stayed open. The reader can still fold it.
   */
  defaultCollapsed(): string[] {
    const out: string[] = [];
    const big = (this.graph.nodes || []).length > 120;
    const holdsTarget = this.findingTargetAncestors();
    for (const n of this.graph.nodes || []) {
      if (!this.isGroup(n.id)) continue;
      if (holdsTarget.has(n.id)) continue;
      const kids = this.descendantCount(n.id);
      if (kids > 12 || (big && kids > 4)) out.push(n.id);
    }
    return out.sort();
  }

  /** Every group that contains a node or connection end some finding names. */
  private findingTargetAncestors(): Set<string> {
    const targets = new Set<string>();
    for (const issue of this.graph.issues || []) {
      for (const id of issue.nodeIds || []) targets.add(id);
      for (const id of issue.edgeIds || []) {
        const edge = this.edgeById.get(id);
        if (edge) {
          targets.add(edge.source);
          targets.add(edge.target);
        }
      }
    }
    const out = new Set<string>();
    for (const id of targets) for (const ancestor of this.ancestors(id)) out.add(ancestor);
    return out;
  }
}

/** Append each finding in `issues` that `seen` has not met yet. */
function addDistinct(into: Issue[], seen: Set<string>, issues: Issue[]): void {
  for (const issue of issues) {
    if (seen.has(issue.id)) continue;
    seen.add(issue.id);
    into.push(issue);
  }
}

function push<K, V>(map: Map<K, V[]>, key: K, value: V): void {
  const arr = map.get(key);
  if (arr) arr.push(value);
  else map.set(key, [value]);
}

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
