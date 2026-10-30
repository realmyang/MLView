/**
 * Stage-swimlane layout.
 *
 * Ordered phase bands stacked top to bottom; each band laid out independently
 * with dagre `rankdir: LR`. Groups (units with children) are laid out
 * CHILDREN-FIRST and inserted into the parent's dagre pass as a single sized
 * meta-node — dagre compound / setParent is never used. Control back-edges are
 * removed before the dagre pass and drawn afterwards by routing.ts.
 *
 * Fully deterministic: every collection is walked in document order, so the
 * same document always gets the same layout.
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
  BACK_EDGE_DROP,
  LANE_ROUTE_BAND,
  CHANNEL_MAX_W,
  CHANNEL_MIN_STEP,
  CHANNEL_PAD_L,
  CHANNEL_PAD_R,
  CHANNEL_PAIR_STEP,
  EXCEPTION_PAD,
  EXCEPTION_TRACK_STEP,
  edgeWeight,
} from './constants.js';
import { cardSize } from './cardmetrics.js';
import { exceptionTracks, gutterSpan } from './channel.js';
import { wrapTallRanks, wrapWideRows } from './wrap.js';

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
  /** x of the OUTERMOST trunk in the left channel (slot 0). */
  channelX: number;
  hasChannel: boolean;
  /** Distinct (source lane, target lane) pairs that skip a lane. */
  channelPairs: number;
  /** How many of those pairs got a slot of their own; the rest share. */
  channelSlots: number;
  /** Distance between two neighbouring trunks. Shrinks before the world grows. */
  channelStep: number;
  /** Total width reserved to the left of the first lane. */
  channelW: number;
  /**
   * x of the first channel track of the inferred and unresolved cables
   * that skip a lane, inside the innermost observed trunk, and how many tracks
   * there are, `exceptionStep` apart.
   */
  exceptionX: number;
  exceptionTracks: number;
  exceptionStep: number;
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

  // A cross-lane edge that skips a lane needs the left routing channel, which is
  // reserved by the number of distinct lane PAIRS, because every observed edge
  // of a pair shares one trunk. Back-edges are excluded: `routeEdges` draws
  // them as loops inside their own lane and they never reach the channel.
  //
  // The edges are split by basis, as `routeEdges` will: a cable (the
  // connections with the same ends, kind and subkind) is observed only when every
  // connection it carries is. Observed cables keep their pair's trunk; each
  // inferred or unresolved one needs a channel track of its own. Counted over the
  // document's own ends, so a fold, which only merges cables, never needs more.
  const channelPairKeys = new Set<string>();
  const observedPairKeys = new Set<string>();
  const exceptionSpans: Array<[number, number]> = [];
  {
    const order = new Map<string, number>();
    index.lanes.forEach((l, i) => order.set(l.id, i));
    const cables = new Map<string, { pair: string; a: number; b: number; observed: boolean }>();
    for (const e of index.graph.edges || []) {
      if (isBackEdge(e)) continue;
      const s = index.nodeById.get(e.source);
      const t = index.nodeById.get(e.target);
      if (!s || !t) continue;
      const a = order.get(s.stage);
      const b = order.get(t.stage);
      if (a === undefined || b === undefined) continue;
      if (Math.abs(a - b) <= 1) continue;
      channelPairKeys.add(s.stage + '>' + t.stage);
      const key = e.source + '\u0000' + e.target + '\u0000' + e.kind + '\u0000' + (e.subkind || '');
      const cable = cables.get(key);
      const observed = !isNotObserved(e);
      if (cable) cable.observed = cable.observed && observed;
      else cables.set(key, { pair: s.stage + '>' + t.stage, a, b, observed });
    }
    for (const cable of cables.values()) {
      if (cable.observed) observedPairKeys.add(cable.pair);
      else exceptionSpans.push(gutterSpan(cable.a, cable.b));
    }
  }

  const channelPairs = channelPairKeys.size;
  const needChannel = channelPairs > 0;
  const wanted = CHANNEL_PAD_L + channelPairs * CHANNEL_PAIR_STEP + CHANNEL_PAD_R;
  const channelW = needChannel ? Math.min(wanted, CHANNEL_MAX_W) : 0;
  const room = Math.max(0, channelW - CHANNEL_PAD_L - CHANNEL_PAD_R);
  // Rounded DOWN to the hundredth: `pairs * step` must never exceed the room, or
  // the last pair loses its slot to a floating-point hair and shares the
  // INNERMOST one with the pair before it (`planChannel`).
  const channelStep = needChannel
    ? Math.max(CHANNEL_MIN_STEP, Math.min(CHANNEL_PAIR_STEP, floor2(room / Math.max(1, channelPairs))))
    : 0;
  const channelSlots = needChannel ? Math.max(1, Math.min(channelPairs, Math.floor(room / channelStep + 1e-6))) : 0;
  // The exception tracks go inside the innermost observed trunk, in the
  // room the reservation above already leaves before the bands (one step and the
  // right padding: two tracks at the full step); the channel grows only past that.
  const channelX = CANVAS_MARGIN + CHANNEL_PAD_L;
  const observedSlots = Math.min(observedPairKeys.size, channelSlots);
  const exceptionX = observedSlots > 0 ? channelX + (observedSlots - 1) * channelStep + EXCEPTION_TRACK_STEP : channelX;
  let tracks = 0;
  for (const track of exceptionTracks(exceptionSpans)) tracks = Math.max(tracks, track + 1);
  const reserved = tracks > 0 ? Math.max(channelW, exceptionX + (tracks - 1) * EXCEPTION_TRACK_STEP + EXCEPTION_PAD - CANVAS_MARGIN) : channelW;
  const laneX = CANVAS_MARGIN + reserved;
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

  // Lane boxes are NOT normalised to the widest lane: a lane ends where its own
  // content ends, so a band with little in it is not drawn as a mostly empty
  // box. The world is as wide as the widest lane, which is what the band
  // striping measures itself against.
  const width = laneX + maxContentW + CANVAS_MARGIN;
  const height = Math.max(cursorY - LANE_GUTTER + CANVAS_MARGIN, CANVAS_MARGIN * 2);

  return {
    lanes,
    laneIndex,
    boxes,
    width,
    height,
    channelX,
    hasChannel: needChannel,
    channelPairs,
    channelSlots,
    channelStep,
    channelW: reserved,
    exceptionX,
    exceptionTracks: tracks,
    exceptionStep: EXCEPTION_TRACK_STEP,
  };
}

/** True for a connection drawn dashed (inferred) or dotted (unresolved): never in a trunk. */
export function isNotObserved(e: MLEdge): boolean {
  return e.basis === 'inferred' || e.basis === 'unresolved';
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
      size.set(id, cardSize(node, true));
    } else {
      size.set(id, cardSize(node, false));
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
  wrapWideRows(g, ids);

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

function floor2(v: number): number {
  return Math.floor(v * 100) / 100;
}
