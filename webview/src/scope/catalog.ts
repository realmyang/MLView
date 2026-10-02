/**
 * The scopable-unit catalogue: what the scope picker lists.
 *
 * A "unit" is a node worth scoping TO: anything with children, or any
 * top-level step (`level: 'unit'`). Counts are computed the way `project()`
 * computes core, so the number beside a row is the number of cards the user
 * will actually get.
 */

import { parseScope } from './selector.js';
import { projectedNodeCount } from './project.js';
import type { IssueCounts, Loc, MLGraph, MLNode, Severity } from '../types.js';

const SEVERITIES: Severity[] = ['high', 'medium', 'low'];

export interface ScopeUnit {
  /** The selector to hand to `setScope`: the node's stable id (VIEWUI-7). */
  spec: string;
  nodeId: string;
  label: string;
  qualname: string;
  file: string;
  line: number;
  /** The node's own location, so a row can name an authored notebook cell (VIEWUI-8). */
  loc: Loc;
  /** Cards this scope would draw at depth 0: the unit plus its descendants. */
  nodeCount: number;
  maxSeverity: Severity | null;
}

export interface ScopeGroup {
  /** A stage: a whole region, drawn at depth 0. */
  spec: string;
  label: string;
  nodes: number;
  issues: IssueCounts;
  /** False renders the row disabled as "not detected in this project" — itself a finding. */
  present: boolean;
}

function childrenOf(graph: MLGraph): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const node of graph.nodes || []) {
    if (!node.parent) continue;
    const list = map.get(node.parent);
    if (list) list.push(node.id);
    else map.set(node.parent, [node.id]);
  }
  return map;
}

function subtreeSize(children: Map<string, string[]>, id: string): number {
  let n = 1;
  const stack = [id];
  const seen = new Set<string>([id]);
  let guard = 0;
  while (stack.length) {
    if (++guard > 100000) break;
    const cur = stack.pop() as string;
    for (const child of children.get(cur) || []) {
      if (seen.has(child)) continue;
      seen.add(child);
      n++;
      stack.push(child);
    }
  }
  return n;
}

function severityOf(graph: MLGraph, ids: Set<string>): Severity | null {
  const counts: IssueCounts = { low: 0, medium: 0, high: 0 };
  for (const issue of graph.issues || []) {
    if (!issue.nodeIds.some((n) => ids.has(n))) continue;
    const sev = issue.severity as Severity;
    if (counts[sev] !== undefined) counts[sev]++;
  }
  return SEVERITIES.filter((s) => counts[s] > 0)[0] || null;
}

function subtreeIds(children: Map<string, string[]>, id: string): Set<string> {
  const out = new Set<string>([id]);
  const stack = [id];
  let guard = 0;
  while (stack.length) {
    if (++guard > 100000) break;
    const cur = stack.pop() as string;
    for (const child of children.get(cur) || []) {
      if (out.has(child)) continue;
      out.add(child);
      stack.push(child);
    }
  }
  return out;
}

export function isScopableUnit(node: MLNode, children: Map<string, string[]>): boolean {
  return (children.get(node.id) || []).length > 0 || node.level === 'unit';
}

/** Sorted `(-nodeCount, file, line, qualname)` — the biggest handles first. */
export function scopeCatalog(graph: MLGraph, limit = 40): ScopeUnit[] {
  const children = childrenOf(graph);
  const rows: ScopeUnit[] = [];
  for (const node of graph.nodes || []) {
    if (!isScopableUnit(node, children)) continue;
    rows.push({
      // VIEWUI-7: by id, so two steps with one label stay apart.
      spec: 'unit:' + node.id,
      nodeId: node.id,
      label: node.label || node.qualname,
      qualname: node.qualname,
      file: node.loc.file,
      line: node.loc.line,
      loc: node.loc,
      nodeCount: subtreeSize(children, node.id),
      maxSeverity: severityOf(graph, subtreeIds(children, node.id)),
    });
  }
  rows.sort(
    (a, b) =>
      b.nodeCount - a.nodeCount ||
      cmp(a.file, b.file) ||
      a.line - b.line ||
      cmp(a.qualname, b.qualname),
  );
  return rows.slice(0, limit);
}

/**
 * HOSTS-UX-ROWCOUNT. The number of cards a row's own click draws, for ANY
 * selector.
 *
 * `ScopeUnit.nodeCount` and `ScopeGroup.nodes` are relation facts: the subtree,
 * or the nodes carrying that stage. The CLICK runs `project()`, which applies
 * the kind's default depth and keeps the `context` ancestors that hold the
 * containment tree together (11.2), so the two numbers differ (a unit that
 * matched 1 node could draw 5). Both numbers are correct
 * about different things; only the one a MENU PROMISES has to be the one the
 * click delivers, so the relation counts are left alone and the picker asks
 * here instead.
 *
 * It runs the same `project()` the click runs rather than re-deriving the
 * projection's rules: a second copy of the rules is a second set of numbers to
 * keep in step.
 *
 * Memoised per `(document identity, spec)` because the picker re-renders on
 * every keystroke in its search box and lists up to 200 units. A selector this
 * document cannot resolve returns `null` and the caller keeps the relation's
 * number: a picker must never be the thing that takes the report down.
 */
let cachedSpecGraph: MLGraph | null = null;
let cachedSpecCounts: Map<string, number> | null = null;

export function viewCountOf(graph: MLGraph, spec: string): number | null {
  if (cachedSpecGraph !== graph || !cachedSpecCounts) {
    cachedSpecGraph = graph;
    cachedSpecCounts = new Map<string, number>();
  }
  const hit = cachedSpecCounts.get(spec);
  if (hit !== undefined) return hit;
  let count: number;
  try {
    // The count, not the document: `projectedNodeCount` runs the click's own
    // steps 3-7 and stops before step 8 copies every kept node and edge, which
    // is what keeps a 222-row menu over a 400-node repository inside a frame.
    count = projectedNodeCount(graph, parseScope(spec));
  } catch (_e) {
    return null;
  }
  cachedSpecCounts.set(spec, count);
  return count;
}

/** One row per stage the document declares; absent stages are shown disabled. */
export function stageRows(graph: MLGraph): ScopeGroup[] {
  return (graph.stages || []).map((stage) => {
    let nodes = 0;
    for (const node of graph.nodes || []) {
      if (node.stage === stage.id) nodes++;
    }
    return {
      spec: 'stage:' + stage.id,
      label: stage.label || stage.id,
      nodes,
      issues: { ...stage.issueCounts },
      present: nodes > 0,
    };
  });
}

function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
