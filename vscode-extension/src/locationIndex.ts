/**
 * Code -> diagram lookup (UX_DESIGN §13). At graph load we build a per-file interval array
 * `[startLine, endLine, nodeId, span]`; the cursor lookup picks the NARROWEST interval
 * containing the line, so `forward` wins over its enclosing class. With no containing
 * interval, the nearest node in the same file is returned and the caller says so.
 */

import type { GraphNode, Loc, MLGraph } from './graph';

export interface Interval {
  startLine: number;
  endLine: number;
  nodeId: string;
  label: string;
  /** endLine - startLine; smaller is narrower and therefore wins. */
  span: number;
  /** op (2) beats unit (1) beats stage (0) when spans tie. */
  levelRank: number;
}

export interface IndexedNodeInfo {
  id: string;
  label: string;
  file: string;
  line: number;
  level: string;
  ghost: boolean;
  /** Dotted qualname — the `unit:` scope selector target (CONTRACTS.md §11.1). */
  qualname: string;
  /** Containment parent, or null for a lane root. The climb in `findEnclosingUnit` walks it. */
  parent: string | null;
}

export interface LocationIndex {
  byFile: Map<string, Interval[]>;
  nodes: Map<string, IndexedNodeInfo>;
}

export interface LookupHit {
  nodeId: string;
  label: string;
  /** False when the cursor was not inside any node and the nearest one was chosen. */
  exact: boolean;
  line: number;
}

const LEVEL_RANK: Record<string, number> = { stage: 0, unit: 1, op: 2 };

export function normalizeFile(file: string): string {
  return file.replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase();
}

function pushInterval(target: Interval[], node: GraphNode, loc: Loc): void {
  const startLine = Math.max(1, Math.trunc(loc.line));
  const endLine = Math.max(startLine, Math.trunc(loc.endLine));
  target.push({
    startLine,
    endLine,
    nodeId: node.id,
    label: node.label,
    span: endLine - startLine,
    levelRank: LEVEL_RANK[String(node.level)] ?? 1
  });
}

export function buildLocationIndex(graph: MLGraph): LocationIndex {
  const byFile = new Map<string, Interval[]>();
  const nodes = new Map<string, IndexedNodeInfo>();
  for (const node of graph.nodes) {
    if (!node.loc || typeof node.loc.file !== 'string') {
      continue;
    }
    nodes.set(node.id, {
      id: node.id,
      label: node.label,
      file: node.loc.file,
      line: node.loc.line,
      level: String(node.level),
      ghost: node.ghost === true,
      qualname: typeof node.qualname === 'string' ? node.qualname : '',
      parent: typeof node.parent === 'string' ? node.parent : null
    });
    // Ghost nodes borrow their parent's loc, so they would shadow the real node at the same
    // range; they are reachable through the issue rail instead.
    if (node.ghost === true) {
      continue;
    }
    const key = normalizeFile(node.loc.file);
    const list = byFile.get(key) ?? [];
    pushInterval(list, node, node.loc);
    if (node.defLoc && normalizeFile(node.defLoc.file) === key) {
      pushInterval(list, node, node.defLoc);
    }
    byFile.set(key, list);
  }
  for (const list of byFile.values()) {
    list.sort((a, b) => a.startLine - b.startLine || a.span - b.span);
  }
  return { byFile, nodes };
}

/** Narrowest containing interval, then deepest level, then earliest start. */
export function findNodeAtLine(
  index: LocationIndex,
  file: string,
  line: number
): LookupHit | null {
  const list = index.byFile.get(normalizeFile(file));
  if (!list || list.length === 0) {
    return null;
  }
  let best: Interval | undefined;
  for (const interval of list) {
    if (line < interval.startLine || line > interval.endLine) {
      continue;
    }
    if (
      !best ||
      interval.span < best.span ||
      (interval.span === best.span && interval.levelRank > best.levelRank)
    ) {
      best = interval;
    }
  }
  if (best) {
    return { nodeId: best.nodeId, label: best.label, exact: true, line: best.startLine };
  }
  let nearest: Interval | undefined;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const interval of list) {
    const distance =
      line < interval.startLine ? interval.startLine - line : line - interval.endLine;
    if (distance < nearestDistance || (distance === nearestDistance && nearest && interval.span < nearest.span)) {
      nearest = interval;
      nearestDistance = distance;
    }
  }
  return nearest
    ? { nodeId: nearest.nodeId, label: nearest.label, exact: false, line: nearest.startLine }
    : null;
}

/** Unit-level, non-ghost nodes in one file — the CodeLens anchors. */
export function unitAnchors(
  graph: MLGraph,
  file: string
): { nodeId: string; label: string; line: number }[] {
  const key = normalizeFile(file);
  const anchors: { nodeId: string; label: string; line: number }[] = [];
  const seen = new Set<number>();
  for (const node of graph.nodes) {
    if (node.ghost === true || String(node.level) !== 'unit') {
      continue;
    }
    const loc = node.defLoc ?? node.loc;
    if (!loc || normalizeFile(loc.file) !== key) {
      continue;
    }
    const line = Math.max(1, Math.trunc(loc.line));
    if (seen.has(line)) {
      continue;
    }
    seen.add(line);
    anchors.push({ nodeId: node.id, label: node.label, line });
  }
  return anchors.sort((a, b) => a.line - b.line);
}

/** What `findEnclosingUnit` resolved the cursor to. */
export interface EnclosingUnit {
  /** The unit (or stage-level lane root) that encloses the cursor. */
  nodeId: string;
  qualname: string;
  label: string;
  level: string;
  /** What `findNodeAtLine` returned — usually an op or a loop inside the unit. */
  fromNodeId: string;
  fromLabel: string;
}

/** The two levels a `unit:` scope selector may name (CONTRACTS.md §11.1, §11.11). */
const UNIT_LEVELS: ReadonlySet<string> = new Set(['unit', 'stage']);

/**
 * The cursor -> `unit:` scope selector resolution (CONTRACTS.md §11.11).
 *
 * `findNodeAtLine` picks the NARROWEST node containing the line, which on
 * `samples/vision_pipeline/train.py:44` is the batch loop rather than the `validate()` it lives
 * in. So: run that lookup, then climb `parent` to the narrowest ancestor whose level is `unit`
 * or `stage`. A lane root has no such ancestor and is already a unit, so it stands for itself.
 *
 * Returns null when the cursor is not inside any node — `findNodeAtLine`'s nearest-node
 * fallback is deliberately NOT used, because a scope must never be guessed.
 */
export function findEnclosingUnit(
  index: LocationIndex,
  file: string,
  line: number
): EnclosingUnit | null {
  const hit = findNodeAtLine(index, file, line);
  if (!hit || !hit.exact) {
    return null;
  }
  const start = index.nodes.get(hit.nodeId);
  if (!start) {
    return null;
  }
  const seen = new Set<string>([start.id]);
  let current = start.parent ? index.nodes.get(start.parent) : undefined;
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    if (UNIT_LEVELS.has(current.level) && current.qualname) {
      return unitOf(current, start);
    }
    current = current.parent ? index.nodes.get(current.parent) : undefined;
  }
  return UNIT_LEVELS.has(start.level) && start.qualname ? unitOf(start, start) : null;
}

function unitOf(unit: IndexedNodeInfo, from: IndexedNodeInfo): EnclosingUnit {
  return {
    nodeId: unit.id,
    qualname: unit.qualname,
    label: unit.label,
    level: unit.level,
    fromNodeId: from.id,
    fromLabel: from.label
  };
}
