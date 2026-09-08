/**
 * The scopable-unit catalogue: what the scope picker lists and what
 * `mlview_graph {scope:"units"}` returns on the analyzer side.
 *
 * A "unit" is a node worth scoping TO: anything with children, or anything the
 * analyzer already calls a definition (`level` in {stage, unit}). Counts are
 * computed the way `project()` computes core, so the number beside a row is the
 * number of cards the user will actually get.
 */

import { CONCERNS, CONCERN_LABELS, CONCERN_NAMES } from './selector.js';
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
