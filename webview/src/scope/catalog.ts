/**
 * The scopable-unit catalogue: what the scope picker lists and what
 * `mlview_graph {scope:"units"}` returns on the analyzer side.
 *
 * A "unit" is a node worth scoping TO: anything with children, or anything the
 * analyzer already calls a definition (`level` in {stage, unit}). Counts are
 * computed the way `project()` computes core, so the number beside a row is the
 * number of cards the user will actually get.
 */

import { CONCERNS, CONCERN_LABELS, CONCERN_NAMES, parseScope } from './selector.js';
import { PipelineIndex } from './pipelines.js';
import { project } from './project.js';
import type { PipelineRow } from './pipelines.js';
import type { IssueCounts, MLGraph, MLNode, Severity } from '../types.js';

const SEVERITIES: Severity[] = ['high', 'medium', 'low'];

export interface ScopeUnit {
  /** The selector to hand to `setScope` — a qualname, so it survives an edit. */
  spec: string;
  nodeId: string;
  label: string;
  qualname: string;
  file: string;
  line: number;
  /** Cards this scope would draw at depth 0: the unit plus its descendants. */
  nodeCount: number;
  maxSeverity: Severity | null;
}

export interface ScopeGroup {
  /** A concern preset or a stage: a whole region, drawn at depth 0. */
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
    if (issue.suppressed) continue;
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
  return (children.get(node.id) || []).length > 0 || node.level === 'stage' || node.level === 'unit';
}

/** Sorted `(-nodeCount, file, line, qualname)` — the biggest handles first. */
export function scopeCatalog(graph: MLGraph, limit = 40): ScopeUnit[] {
  const children = childrenOf(graph);
  const rows: ScopeUnit[] = [];
  for (const node of graph.nodes || []) {
    if (!isScopableUnit(node, children)) continue;
    rows.push({
      spec: 'unit:' + node.qualname,
      nodeId: node.id,
      label: node.label || node.qualname,
      qualname: node.qualname,
      file: node.loc.file,
      line: node.loc.line,
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

/** The four presets with LIVE counts, so a concern that matches nothing says so. */
export function concernRows(graph: MLGraph): ScopeGroup[] {
  return CONCERN_NAMES.map((name) => {
    const stages = CONCERNS[name] || [];
    const ids = new Set<string>();
    for (const node of graph.nodes || []) {
      if (stages.indexOf(node.stage) >= 0) ids.add(node.id);
    }
    const counts: IssueCounts = { low: 0, medium: 0, high: 0 };
    for (const issue of graph.issues || []) {
      if (issue.suppressed) continue;
      if (!issue.nodeIds.some((n) => ids.has(n))) continue;
      const sev = issue.severity as Severity;
      if (counts[sev] !== undefined) counts[sev]++;
    }
    // The FROZEN name, not the slug: the breadcrumb, the toolbar button and the
    // accessible name all read CONCERN_LABELS, so a picker row saying
    // 'optimization' renamed itself 'Model & optimization' one click later
    // (MLV-R3-005).
    const label = CONCERN_LABELS[name] || name;
    return { spec: 'concern:' + name, label, nodes: ids.size, issues: counts, present: ids.size > 0 };
  });
}

/**
 * MLV-P12. The pipelines of one document, computed ONCE per document object.
 *
 * The picker re-renders on every keystroke in its search box and the chooser
 * asks for the same rows a moment later, so a relation that is O(entrypoints ×
 * (V + E)) is memoised against the document's identity rather than recomputed.
 * A new document is a new object, so the cache can never be stale; it holds one
 * entry, because there is only ever one document on screen.
 *
 * Nothing here reads the emitted `pipelines[]` block — 11.47 A is explicit that
 * both ports compute the relation and neither trusts the block, so a stale or
 * hand-edited block can never change what the picker offers or what is drawn.
 */
let cachedGraph: MLGraph | null = null;
let cachedIndex: PipelineIndex | null = null;

export function pipelineIndexOf(graph: MLGraph): PipelineIndex {
  if (cachedGraph === graph && cachedIndex) return cachedIndex;
  cachedGraph = graph;
  cachedIndex = new PipelineIndex(graph);
  return cachedIndex;
}

/**
 * The picker's and the chooser's rows, in the analyzer's ranked order.
 *
 * HOSTS-UX-PIPELINECOUNT. Each row also carries `viewCount`: the number of
 * cards the click actually draws, obtained by running the SAME `project()` the
 * click runs rather than by re-deriving the projection's rules here. `nodeCount`
 * is left alone — it is 11.47 A's relation, `exclusiveCount + sharedCount`, and
 * what the emitted block reports — so the two numbers stay separate facts and
 * only the one a row PROMISES changes.
 *
 * Memoised beside the relation, against the document's identity, because the
 * picker re-renders on every keystroke in its search box and a projection per
 * entrypoint per keystroke is not free. A projection that throws — a document
 * whose `workspace.entrypoints` no longer resolves — leaves `viewCount` unset
 * and the row falls back to `nodeCount`: a picker must never be the thing that
 * takes the report down.
 */
export function pipelineRows(graph: MLGraph | null): PipelineRow[] {
  if (!graph) return [];
  const rows = pipelineIndexOf(graph).rows();
  const drawn = viewCountsOf(graph, rows);
  return rows.map((row) => {
    const count = drawn.get(row.entrypoint);
    return count === undefined ? row : { ...row, viewCount: count };
  });
}

let cachedCountGraph: MLGraph | null = null;
let cachedCounts: Map<string, number> | null = null;

function viewCountsOf(graph: MLGraph, rows: PipelineRow[]): Map<string, number> {
  if (cachedCountGraph === graph && cachedCounts) return cachedCounts;
  const out = new Map<string, number>();
  for (const row of rows) {
    try {
      out.set(row.entrypoint, project(graph, parseScope('pipeline:' + row.entrypoint)).nodes.length);
    } catch (_e) {
      /* an entrypoint this document can no longer resolve keeps its own count */
    }
  }
  cachedCountGraph = graph;
  cachedCounts = out;
  return out;
}

/**
 * HOSTS-UX-ROWCOUNT. The number of cards a row's own click draws, for ANY
 * selector — the generalisation of `pipelineRows`' `viewCount` above.
 *
 * `ScopeUnit.nodeCount` and `ScopeGroup.nodes` are relation facts: the subtree,
 * or the nodes carrying that stage. The CLICK runs `project()`, which applies
 * the kind's default depth and keeps the `context` ancestors that hold the
 * containment tree together (11.2), so the two numbers differ — on the frozen
 * golden `unit:model.SmallNet` matched 1 and drew 5. Both numbers are correct
 * about different things; only the one a MENU PROMISES has to be the one the
 * click delivers, so the relation counts are left alone and the picker asks
 * here instead.
 *
 * It runs the same `project()` the click runs rather than re-deriving the
 * projection's rules, for the reason round 1 gave about the pipeline rows: a
 * second copy of the rules is a second set of numbers to keep in step.
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
    count = project(graph, parseScope(spec)).nodes.length;
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
