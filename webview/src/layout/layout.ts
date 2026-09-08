/**
 * Stage-swimlane layout (CONTRACTS amendment A11, UX_DESIGN section 2.2).
 *
 * Eight ordered bands stacked top to bottom; each band laid out independently
 * with dagre `rankdir: LR`. Groups (units with children) are laid out
 * CHILDREN-FIRST and inserted into the parent's dagre pass as a single sized
 * meta-node — dagre compound / setParent is never used. Control back-edges are
 * removed before the dagre pass and drawn afterwards by routing.ts.
 *
 * Fully deterministic: every collection is walked in document order, which the
 * analyzer guarantees is canonically sorted.
 */

import dagre from '@dagrejs/dagre';
import type { MLEdge } from '../types.js';
import { GraphIndex } from './model.js';
import {
  CANVAS_MARGIN,
  DAGRE_OPTS,
  GROUP_HEADER_H,
  GROUP_MIN_H,
  GROUP_MIN_W,
  GROUP_PAD,
  LANE_GUTTER,
  LANE_HEADER_H,
  LANE_MIN_H,
  LANE_MIN_W,
  LANE_PAD,
  NODE_H,
  NODE_W_LG,
  BACK_EDGE_DROP,
  LANE_ROUTE_BAND,
  MAX_RANK_H,
  RANK_COL_GAP,
  RANK_ROW_GAP,
  edgeWeight,
  nodeSize,
} from './constants.js';

export interface LayoutBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  laneId: string;
  depth: number;
  isGroup: boolean;
  collapsed: boolean;
  headerH: number;
}

export interface LayoutLane {
  id: string;
  label: string;
  order: number;
  index: number;
  x: number;
  y: number;
  w: number;
  h: number;
  headerH: number;
  nodeCount: number;
}

export interface LayoutFrame {
  lanes: LayoutLane[];
  laneIndex: Map<string, number>;
  boxes: Map<string, LayoutBox>;
  width: number;
  height: number;
  channelX: number;
  hasChannel: boolean;
}

interface Placer {
  w: number;
  h: number;
  place(ox: number, oy: number): void;
}

export function isBackEdge(e: MLEdge): boolean {
  return e.kind === 'control' && e.subkind === 'back';
}

/**
 * Lay the whole document out. Depends only on (graph, collapsed) so the result
 * is stable across re-renders — filters and selection never relayout.
 */
export function layoutGraph(index: GraphIndex, collapsed: Set<string>): LayoutFrame {
  const boxes = new Map<string, LayoutBox>();
  const lanes: LayoutLane[] = [];
  const laneIndex = new Map<string, number>();

  const laneIdOf = new Map<string, string>();
  for (const n of index.graph.nodes || []) laneIdOf.set(n.id, n.stage);

  // Edges available to dagre: every non-back edge, in document order.
  const rankEdges = (index.graph.edges || []).filter((e) => !isBackEdge(e));

  const hasBackEdgeInLane = new Set<string>();
  for (const e of index.graph.edges || []) {
    if (!isBackEdge(e)) continue;
    const src = index.nodeById.get(e.source);
    if (src) hasBackEdgeInLane.add(src.stage);
    const tgt = index.nodeById.get(e.target);
    if (tgt) hasBackEdgeInLane.add(tgt.stage);
  }

  let needChannel = false;
  {
    // A cross-lane edge that skips a lane needs the left routing channel.
    const order = new Map<string, number>();
    index.lanes.forEach((l, i) => order.set(l.id, i));
    for (const e of index.graph.edges || []) {
      const s = index.nodeById.get(e.source);
      const t = index.nodeById.get(e.target);
      if (!s || !t) continue;
      const a = order.get(s.stage);
      const b = order.get(t.stage);
      if (a === undefined || b === undefined) continue;
      if (Math.abs(a - b) > 1) needChannel = true;
    }
  }

  const channelW = needChannel ? 56 : 0;
  const laneX = CANVAS_MARGIN + channelW;
  let cursorY = CANVAS_MARGIN;
  let maxContentW = LANE_MIN_W;

  index.lanes.forEach((stage, i) => {
    laneIndex.set(stage.id, i);
    const roots = index.roots(stage.id).filter((id) => !index.isHidden(id, collapsed));
    const placer = layoutContainer(index, collapsed, roots, 0, stage.id, rankEdges, boxes);
    const contentW = Math.max(placer.w, LANE_MIN_W - 2 * LANE_PAD);
    const reserve = (hasBackEdgeInLane.has(stage.id) ? BACK_EDGE_DROP : 0) + LANE_ROUTE_BAND;
    const contentH = Math.max(placer.h, LANE_MIN_H - LANE_HEADER_H - LANE_PAD) + reserve;
    const laneH = LANE_HEADER_H + contentH + LANE_PAD;
    placer.place(laneX + LANE_PAD, cursorY + LANE_HEADER_H);
    lanes.push({
      id: stage.id,
      label: stage.label || stage.id,
      order: stage.order,
      index: i,
      x: laneX,
      y: cursorY,
      w: contentW + 2 * LANE_PAD,
      h: laneH,
      headerH: LANE_HEADER_H,
      nodeCount: countNodesInLane(index, stage.id),
    });
    maxContentW = Math.max(maxContentW, contentW + 2 * LANE_PAD);
    cursorY += laneH + LANE_GUTTER;
  });

  for (const lane of lanes) lane.w = maxContentW;

  const width = laneX + maxContentW + CANVAS_MARGIN;
  const height = Math.max(cursorY - LANE_GUTTER + CANVAS_MARGIN, CANVAS_MARGIN * 2);

  return {
    lanes,
    laneIndex,
    boxes,
    width,
    height,
    channelX: CANVAS_MARGIN + 16,
    hasChannel: needChannel,
  };
}

function countNodesInLane(index: GraphIndex, laneId: string): number {
  let n = 0;
  for (const node of index.graph.nodes || []) if (node.stage === laneId) n++;
  return n;
}

function layoutContainer(
  index: GraphIndex,
  collapsed: Set<string>,
  ids: string[],
  depth: number,
  laneId: string,
  rankEdges: MLEdge[],
  boxes: Map<string, LayoutBox>,
): Placer {
  if (ids.length === 0) return { w: 0, h: 0, place: () => undefined };

  const member = new Set(ids);
  const inner = new Map<string, Placer>();
  const size = new Map<string, { w: number; h: number }>();

  const g = new dagre.graphlib.Graph();
  g.setGraph({ ...DAGRE_OPTS });
  g.setDefaultEdgeLabel(() => ({}));

  for (const id of ids) {
    const node = index.nodeById.get(id);
    if (!node) continue;
    const group = index.isGroup(id);
    const isCollapsed = collapsed.has(id);
    if (group && !isCollapsed) {
      const kids = index.laneChildren(id);
      const child = layoutContainer(index, collapsed, kids, depth + 1, laneId, rankEdges, boxes);
      inner.set(id, child);
      const w = Math.max(GROUP_MIN_W, child.w + 2 * GROUP_PAD);
      const h = Math.max(GROUP_MIN_H, GROUP_HEADER_H + child.h + GROUP_PAD);
      size.set(id, { w, h });
    } else if (group && isCollapsed) {
      size.set(id, { w: NODE_W_LG, h: NODE_H });
    } else {
      size.set(id, nodeSize(node.kind, node.level, node.ghost));
    }
    const s = size.get(id)!;
    g.setNode(id, { width: s.w, height: s.h });
  }

  // Lift each edge to this container's sibling level; drop the ones that leave it.
  const seen = new Map<string, number>();
  for (const e of rankEdges) {
    const s = liftTo(index, e.source, member);
    const t = liftTo(index, e.target, member);
    if (!s || !t || s === t) continue;
    const key = s + '\u0000' + t;
    const prev = seen.get(key) || 0;
    const weight = prev + edgeWeight(e.kind);
    seen.set(key, weight);
    g.setEdge(s, t, { weight, minlen: 1 });
  }

  dagre.layout(g);
  wrapTallRanks(g, ids);

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const local = new Map<string, { x: number; y: number; w: number; h: number }>();
  for (const id of ids) {
    const dn: any = g.node(id);
    if (!dn) continue;
    const w = dn.width;
    const h = dn.height;
    const x = dn.x - w / 2;
    const y = dn.y - h / 2;
    local.set(id, { x, y, w, h });
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x + w);
    maxY = Math.max(maxY, y + h);
  }
  if (!isFinite(minX)) {
    minX = 0;
    minY = 0;
    maxX = 0;
    maxY = 0;
  }

  const width = Math.max(0, maxX - minX);
  const height = Math.max(0, maxY - minY);

  return {
    w: width,
    h: height,
    place(ox: number, oy: number) {
      for (const id of ids) {
        const l = local.get(id);
        if (!l) continue;
        const x = round(ox + (l.x - minX));
        const y = round(oy + (l.y - minY));
        const group = index.isGroup(id);
        const isCollapsed = collapsed.has(id);
        boxes.set(id, {
          id,
          x,
          y,
          w: l.w,
          h: l.h,
          laneId,
          depth,
          isGroup: group,
          collapsed: group && isCollapsed,
          headerH: group && !isCollapsed ? GROUP_HEADER_H : 0,
        });
        const child = inner.get(id);
        if (child) {
          const innerX = x + Math.max(GROUP_PAD, (l.w - child.w) / 2);
          child.place(round(innerX), round(y + GROUP_HEADER_H));
        }
      }
    },
  };
}

/**
 * Wrap over-tall ranks into sub-columns (MLV-R1-002).
 *
 * Under `rankdir: 'LR'` a dagre rank is a column, and every sibling with no
 * incident edge lands in rank 0 — so a lane of fifteen unconnected calls becomes
 * one 1400 px column, the document turns into a 4:1 ribbon and `fit()` picks the
 * zoom floor. Any rank whose stacked height exceeds MAX_RANK_H is re-flowed into
 * ceil(H / MAX_RANK_H) sub-columns and every later rank is shifted right by the
 * width that added, so the lane grows across the axis the canvas has room in.
 *
 * Runs on dagre's OUTPUT coordinates only: edge points are recomputed from the
 * boxes by routing.ts, so nothing downstream depends on dagre's own routing.
 */
function wrapTallRanks(g: any, ids: string[]): void {
  const placed: { id: string; n: any }[] = [];
  for (const id of ids) {
    const n = g.node(id);
    if (n && isFinite(n.x) && isFinite(n.y)) placed.push({ id, n });
  }
  if (placed.length < 2) return;

  // Same rank => same centre x, so the rounded centre is the rank key.
  const columns = new Map<number, { id: string; n: any }[]>();
  for (const entry of placed) {
    const key = Math.round(entry.n.x * 100) / 100;
    const bucket = columns.get(key);
    if (bucket) bucket.push(entry);
    else columns.set(key, [entry]);
  }

  const keys = Array.from(columns.keys()).sort((a, b) => a - b);
  let shift = 0;
  for (const key of keys) {
    const members = columns.get(key)!;
    for (const m of members) m.n.x += shift;
    if (members.length < 2) continue;

    members.sort((a, b) => a.n.y - b.n.y || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    let stacked = 0;
    let colW = 0;
    for (const m of members) {
      stacked += m.n.height;
      colW = Math.max(colW, m.n.width);
    }
    stacked += (members.length - 1) * RANK_ROW_GAP;
    if (stacked <= MAX_RANK_H) continue;

    const subColumns = Math.ceil(stacked / MAX_RANK_H);
    const rows = Math.max(1, Math.ceil(members.length / subColumns));
    const top = Math.min.apply(null, members.map((m) => m.n.y - m.n.height / 2));
    let column = 0;
    let cursor = top;
    for (let i = 0; i < members.length; i++) {
      if (i > 0 && i % rows === 0) {
        column++;
        cursor = top;
      }
      const m = members[i];
      m.n.x = key + shift + column * (colW + RANK_COL_GAP);
      m.n.y = cursor + m.n.height / 2;
      cursor += m.n.height + RANK_ROW_GAP;
    }
    shift += column * (colW + RANK_COL_GAP);
  }
}

function liftTo(index: GraphIndex, id: string, member: Set<string>): string | null {
  if (member.has(id)) return id;
  let cur = index.parentOf.get(id) || null;
  let hops = 0;
  while (cur) {
    if (member.has(cur)) return cur;
    if (++hops > 4096) return null;
    cur = index.parentOf.get(cur) || null;
  }
  return null;
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
