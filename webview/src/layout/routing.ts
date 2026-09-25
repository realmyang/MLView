/**
 * Edge routing. Orthogonal elbows with rounded corners; cross-lane edges pass
 * through the gutters between bands; control back-edges are drawn as loops that
 * stay OUTSIDE the box of the construct they return to (R1.5).
 *
 * Every route is obstacle-aware (UX_DESIGN §4.5: "edges never cross a node").
 * Each router first proposes its natural elbow; if that elbow would be drawn
 * through the interior of a card that is neither endpoint nor an ancestor or
 * descendant of one, the route is re-planned through free corridors — the
 * vertical gaps the dagre pass already leaves between box columns, plus the
 * horizontal band reserved at the bottom of every lane (MLV-R1-003).
 *
 * Routing is pure geometry over the LayoutFrame, so it is as deterministic as
 * the layout it consumes.
 */

import type { MLEdge } from '../types.js';
import { GraphIndex } from './model.js';
import { LayoutBox, LayoutFrame, isBackEdge } from './layout.js';
import { CORNER_R, ROUTE_CLEARANCE } from './constants.js';
import { CrossBucket, LanePair, memberSplay, planChannel } from './channel.js';
import { midpointOf, orthPath } from './orth.js';
import type { Point } from './orth.js';

/**
 * The polyline primitives live in `layout/orth.ts` now, because VIEW-04's
 * bundle layer draws trunks and spurs with the same pen. Re-exported here so
 * every existing import site still names one module for "a routed shape".
 */
export type { Point } from './orth.js';
export { midpointOf, orthPath } from './orth.js';

/**
 * VIEW-04 — this route's share of a cross-lane trunk.
 *
 * Stamped on every route that leaves its lane. `head` and `tail` are the SAME
 * two points for every member of a pair — they are the trunk's ends — and
 * `joinFrom` / `joinTo` index this route's own `points` at the two places it
 * meets that trunk. `layout/bundles.ts` needs nothing else to draw one trunk
 * with N splayed spurs, and it does so WITHOUT touching `points` or `d`: the
 * flow charge and the SVG export read those, so a bundle is a second drawing of
 * an unchanged route, never a replacement for it.
 */
export interface TrunkRef {
  /** `<source lane>><target lane>`. */
  key: string;
  sourceLane: string;
  targetLane: string;
  /** Index inside the pair, in barycentre order, and the pair's size. */
  index: number;
  size: number;
  /** The axis the trunk runs along: `y` in the channel, `x` in a gutter. */
  axis: 'x' | 'y';
  /** The shared vertical run's x. Meaningless for a gutter trunk. */
  channelX: number;
  /** The gutter this pair enters the corridor in, and the one it leaves by. */
  entryY: number;
  exitY: number;
  joinFrom: number;
  joinTo: number;
}

export interface RoutedEdge {
  /** The representative edge id (the first in document order for this route). */
  id: string;
  /** Every document edge merged into this route. */
  ids: string[];
  kind: string;
  subkind?: string;
  source: string;
  target: string;
  label: string;
  points: Point[];
  d: string;
  mid: Point;
  midAngle: number;
  crossLane: boolean;
  back: boolean;
  count: number;
  /** VIEW-04: the trunk this route shares with the rest of its lane pair. */
  trunk?: TrunkRef;
}

/* ── obstacle environment ────────────────────────────────────────────── */

interface RouteEnv {
  index: GraphIndex;
  frame: LayoutFrame;
  /** Every drawn box, at every depth, bucketed by lane. */
  laneBoxes: Map<string, LayoutBox[]>;
  /** id -> { itself } ∪ its ancestors, so containment tests are O(1). */
  ancestry: Map<string, Set<string>>;
  /** Per lane: the y of the free horizontal band reserved under the content. */
  band: Map<string, number>;
  /** Flat obstacle list — small enough to scan per segment. */
  all: LayoutBox[];
}

function buildEnv(index: GraphIndex, frame: LayoutFrame): RouteEnv {
  const laneBoxes = new Map<string, LayoutBox[]>();
  const all: LayoutBox[] = [];
  const ancestry = new Map<string, Set<string>>();
  for (const box of frame.boxes.values()) {
    all.push(box);
    const list = laneBoxes.get(box.laneId);
    if (list) list.push(box);
    else laneBoxes.set(box.laneId, [box]);
    const own = new Set<string>([box.id]);
    for (const a of index.ancestors(box.id)) own.add(a);
    ancestry.set(box.id, own);
  }
  for (const list of laneBoxes.values()) list.sort((a, b) => a.x - b.x || compareId(a.id, b.id));

  const band = new Map<string, number>();
  for (const lane of frame.lanes) {
    let bottom = lane.y + lane.headerH;
    for (const box of laneBoxes.get(lane.id) || []) bottom = Math.max(bottom, box.y + box.h);
    band.set(lane.id, round(Math.min(bottom + 9, lane.y + lane.h - 5)));
  }
  return { index, frame, laneBoxes, ancestry, band, all };
}

/**
 * True when `box` must be avoided by an edge running between `s` and `t`.
 * An endpoint, anything inside an endpoint, and any group containing an
 * endpoint are all legitimately overlapped — everything else is an obstacle.
 */
function blocks(env: RouteEnv, box: LayoutBox, s: string, t: string): boolean {
  const own = env.ancestry.get(box.id);
  if (!own) return false;
  if (own.has(s) || own.has(t)) return false;
  const sa = env.ancestry.get(s);
  if (sa && sa.has(box.id)) return false;
  const ta = env.ancestry.get(t);
  if (ta && ta.has(box.id)) return false;
  return true;
}

/** The bounding box of one axis-aligned segment. */
interface SegBounds { x0: number; x1: number; y0: number; y1: number }

function segBounds(a: Point, b: Point): SegBounds {
  return { x0: Math.min(a.x, b.x), x1: Math.max(a.x, b.x), y0: Math.min(a.y, b.y), y1: Math.max(a.y, b.y) };
}

/** Axis-aligned segment against a box interior (1 px inset, so faces are free). */
function segHitsBox(seg: SegBounds, box: LayoutBox): boolean {
  const m = 1;
  return seg.x1 > box.x + m && seg.x0 < box.x + box.w - m && seg.y1 > box.y + m && seg.y0 < box.y + box.h - m;
}

// RENDER-2. Both predicates are pure and ANDed, so the cheap geometric test
// runs first and the Map/Set lookups in `blocks` run only for a box the
// segment actually hits. The geometry golden (test/geometry-golden.test.mjs)
// pins that the output is unchanged.
function pathCrosses(env: RouteEnv, points: Point[], s: string, t: string): boolean {
  for (let i = 1; i < points.length; i++) {
    const seg = segBounds(points[i - 1], points[i]);
    for (const box of env.all) {
      if (!segHitsBox(seg, box)) continue;
      if (blocks(env, box, s, t)) return true;
    }
  }
  return false;
}

/**
 * Free vertical corridors in a lane over the y-range a run needs, as x-intervals.
 * The dagre pass leaves `ranksep`/`nodesep` gaps between box columns; this turns
 * them into the list of x values a vertical run may legally use.
 */
function freeCorridors(env: RouteEnv, laneId: string, y0: number, y1: number, s: string, t: string): { a: number; b: number }[] {
  const laneIdx = env.frame.laneIndex.get(laneId);
  const lane = laneIdx === undefined ? null : env.frame.lanes[laneIdx];
  const lo = Math.min(y0, y1);
  const hi = Math.max(y0, y1);
  const spans: { a: number; b: number }[] = [];
  for (const box of env.laneBoxes.get(laneId) || []) {
    if (box.y + box.h <= lo || box.y >= hi) continue;
    if (!blocks(env, box, s, t)) continue;
    spans.push({ a: box.x - ROUTE_CLEARANCE, b: box.x + box.w + ROUTE_CLEARANCE });
  }
  spans.sort((p1, p2) => p1.a - p2.a);
  const left = lane ? lane.x + 4 : 0;
  const right = lane ? lane.x + lane.w - 4 : left;
  const out: { a: number; b: number }[] = [];
  let cursor = left;
  for (const span of spans) {
    if (span.b <= cursor) continue;
    if (span.a > cursor) out.push({ a: cursor, b: Math.min(span.a, right) });
    cursor = Math.max(cursor, span.b);
    if (cursor >= right) break;
  }
  if (cursor < right) out.push({ a: cursor, b: right });
  return out.filter((iv) => iv.b - iv.a >= 10 && iv.b > left && iv.a < right);
}

/**
 * The x of the nearest free corridor beside `box` that can be reached by a
 * straight horizontal run out of the box's own face. Null when there is none.
 */
function escapeX(
  env: RouteEnv,
  box: LayoutBox,
  toRight: boolean,
  y0: number,
  y1: number,
  s: string,
  t: string,
): number | null {
  const free = freeCorridors(env, box.laneId, y0, y1, s, t);
  const candidates: number[] = [];
  // `box` is an endpoint, so it is not itself an obstacle and a free interval can
  // straddle it. Clip each interval to the requested side before measuring it.
  for (const iv of free) {
    if (toRight) {
      const a = Math.max(iv.a, box.x + box.w + 4);
      if (iv.b - a >= 10) candidates.push(round((a + Math.min(iv.b, a + 40)) / 2));
    } else {
      const b = Math.min(iv.b, box.x - 4);
      if (b - iv.a >= 10) candidates.push(round((Math.max(iv.a, b - 40) + b) / 2));
    }
  }
  candidates.sort((a, b) => (toRight ? a - b : b - a));
  const y = cy(box);
  const face = toRight ? box.x + box.w : box.x;
  for (const x of candidates) {
    if (!pathCrosses(env, [p(face, y), p(x, y)], s, t)) return x;
  }
  return null;
}

/** Escape on the side facing `towardX` first, then the other side. */
function escapeToward(
  env: RouteEnv,
  box: LayoutBox,
  towardX: number,
  y0: number,
  y1: number,
  s: string,
  t: string,
): number | null {
  const right = towardX >= cx(box);
  const first = escapeX(env, box, right, y0, y1, s, t);
  if (first !== null) return first;
  return escapeX(env, box, !right, y0, y1, s, t);
}

/* ── the router ──────────────────────────────────────────────────────── */

export function routeEdges(index: GraphIndex, frame: LayoutFrame, collapsed: Set<string>): RoutedEdge[] {
  const env = buildEnv(index, frame);
  const groups = new Map<string, { edges: MLEdge[]; s: string; t: string }>();
  const order: string[] = [];

  for (const e of index.graph.edges || []) {
    const s = index.visibleRepresentative(e.source, collapsed);
    const t = index.visibleRepresentative(e.target, collapsed);
    if (s === t) continue;
    if (!frame.boxes.has(s) || !frame.boxes.has(t)) continue;
    const key = s + ' ' + t + ' ' + e.kind + ' ' + (e.subkind || '');
    let bucket = groups.get(key);
    if (!bucket) {
      bucket = { edges: [], s, t };
      groups.set(key, bucket);
      order.push(key);
    }
    bucket.edges.push(e);
  }

  // VIEW-04: the cross-lane buckets are collected FIRST, because a trunk is a
  // decision about a whole lane pair — which slot it takes in the channel and in
  // what order its members leave it — and none of that can be known one edge at
  // a time. Document order in, deterministic plan out.
  const crossBuckets: CrossBucket[] = [];
  for (const key of order) {
    const bucket = groups.get(key)!;
    if (isBackEdge(bucket.edges[0])) continue;
    const sBox = frame.boxes.get(bucket.s)!;
    const tBox = frame.boxes.get(bucket.t)!;
    if (sBox.laneId === tBox.laneId) continue;
    if (index.ancestors(bucket.s).indexOf(bucket.t) >= 0) continue;
    if (index.ancestors(bucket.t).indexOf(bucket.s) >= 0) continue;
    crossBuckets.push({ key, sBox, tBox });
  }
  const channel = planChannel(frame, crossBuckets);

  const backCounters = new Map<string, number>();
  const gutterCounters = new Map<string, number>();
  const out: RoutedEdge[] = [];

  for (const key of order) {
    const bucket = groups.get(key)!;
    const first = bucket.edges[0];
    const sBox = frame.boxes.get(bucket.s)!;
    const tBox = frame.boxes.get(bucket.t)!;
    const back = isBackEdge(first);
    const crossLane = sBox.laneId !== tBox.laneId;

    const sInsideT = index.ancestors(bucket.s).indexOf(bucket.t) >= 0;
    const tInsideS = index.ancestors(bucket.t).indexOf(bucket.s) >= 0;

    let points: Point[];
    let trunk: TrunkRef | undefined;
    if (back) {
      const n = bump(backCounters, sBox.laneId);
      points = routeBack(env, index, frame, sBox, tBox, n);
    } else if (tInsideS || sInsideT) {
      points = routeContainment(env, sBox, tBox, tInsideS);
    } else if (crossLane) {
      const pair = channel.pairOf.get(key)!;
      const idx = channel.indexOf.get(key) || 0;
      const routed = routeCrossLane(env, sBox, tBox, pair, idx);
      points = routed.points;
      if (routed.joinFrom >= 0 && routed.joinTo > routed.joinFrom) {
        trunk = {
          key: pair.key,
          sourceLane: pair.sourceLane,
          targetLane: pair.targetLane,
          index: idx,
          size: pair.members.length,
          axis: pair.adjacent ? 'x' : 'y',
          channelX: pair.trunkX,
          entryY: pair.entryY,
          exitY: pair.adjacent ? pair.entryY : pair.exitY,
          joinFrom: routed.joinFrom,
          joinTo: routed.joinTo,
        };
      }
    } else {
      const n = bump(gutterCounters, 'in:' + sBox.laneId);
      points = routeWithinLane(env, frame, sBox, tBox, n);
    }

    const label = bucket.edges.length > 1 ? '×' + bucket.edges.length : first.label || '';
    const midInfo = midpointOf(points);
    out.push({
      id: first.id,
      ids: bucket.edges.map((e) => e.id),
      kind: first.kind,
      subkind: first.subkind,
      source: bucket.s,
      target: bucket.t,
      label,
      points,
      d: orthPath(points, CORNER_R),
      mid: midInfo.point,
      midAngle: midInfo.angle,
      crossLane,
      back,
      count: bucket.edges.length,
      trunk,
    });
  }
  return out;
}

function bump(map: Map<string, number>, key: string): number {
  const n = (map.get(key) || 0) + 1;
  map.set(key, n);
  return n - 1;
}

function cx(b: LayoutBox): number {
  return b.x + b.w / 2;
}

function cy(b: LayoutBox): number {
  return b.y + b.h / 2;
}

/**
 * One endpoint contains the other (a control/enter edge into a loop body, say).
 * Drop through the container's left padding — which is free of children by
 * construction — and enter the child's left face.
 */
function routeContainment(env: RouteEnv, s: LayoutBox, t: LayoutBox, targetInsideSource: boolean): Point[] {
  const outer = targetInsideSource ? s : t;
  const inner = targetInsideSource ? t : s;
  const gutter = round(outer.x + 12);
  const headerY = outer.y + Math.min(28, outer.h / 2);
  const simple = targetInsideSource
    ? [p(gutter, headerY), p(gutter, cy(inner)), p(inner.x, cy(inner))]
    : [p(inner.x, cy(inner)), p(gutter, cy(inner)), p(gutter, headerY)];
  if (!pathCrosses(env, simple, s.id, t.id)) return simple;

  // A sibling sits between the container's left padding and the child: come in
  // through the free corridor immediately beside the child instead.
  const lift = escapeX(env, inner, false, cy(inner), cy(inner), s.id, t.id);
  const x = lift === null ? gutter : lift;
  const face = lift === null || lift <= inner.x ? inner.x : inner.x + inner.w;
  const detour = targetInsideSource
    ? [p(gutter, headerY), p(gutter, cy(inner)), p(x, cy(inner)), p(face, cy(inner))]
    : [p(face, cy(inner)), p(x, cy(inner)), p(gutter, cy(inner)), p(gutter, headerY)];
  return pathCrosses(env, detour, s.id, t.id) ? simple : dedupe(detour);
}

/** Same-lane forward flow: right edge of source into left edge of target. */
function routeWithinLane(env: RouteEnv, frame: LayoutFrame, s: LayoutBox, t: LayoutBox, n: number): Point[] {
  const sx = s.x + s.w;
  const sy = anchorY(s, n);
  const tx = t.x;
  const ty = anchorY(t, n);
  let simple: Point[];
  if (tx >= sx + 16) {
    const mx = round((sx + tx) / 2);
    simple =
      Math.abs(sy - ty) < 0.5 ? [p(sx, sy), p(tx, ty)] : [p(sx, sy), p(mx, sy), p(mx, ty), p(tx, ty)];
  } else {
    // Target sits left of, or overlaps, the source: detour under both boxes.
    const lane = frame.lanes[frame.laneIndex.get(s.laneId) ?? 0];
    const drop = Math.max(s.y + s.h, t.y + t.h) + 14 + n * 6;
    const limit = lane ? lane.y + lane.h - 6 : drop;
    const y = round(Math.min(drop, limit));
    simple = [p(cx(s), s.y + s.h), p(cx(s), y), p(cx(t), y), p(cx(t), t.y + t.h)];
  }
  if (!pathCrosses(env, simple, s.id, t.id)) return simple;
  const detour = laneDetour(env, s, t, n);
  return detour && !pathCrosses(env, detour, s.id, t.id) ? detour : simple;
}

/**
 * Leave the source sideways into a free corridor, run along the lane's reserved
 * bottom band, and rise into the target's near face. Every leg is provably free:
 * the corridors are gaps between box columns and the band is below all content.
 */
function laneDetour(env: RouteEnv, s: LayoutBox, t: LayoutBox, n: number): Point[] | null {
  const y = round((env.band.get(s.laneId) ?? Math.max(s.y + s.h, t.y + t.h) + 12) + n * 5);
  const sx = escapeToward(env, s, cx(t), cy(s), y, s.id, t.id);
  const tx = escapeToward(env, t, cx(s), y, cy(t), s.id, t.id);
  if (sx === null || tx === null) return null;
  const sFace = sx >= cx(s) ? s.x + s.w : s.x;
  const tFace = tx >= cx(t) ? t.x + t.w : t.x;
  return dedupe([p(sFace, cy(s)), p(sx, cy(s)), p(sx, y), p(tx, y), p(tx, cy(t)), p(tFace, cy(t))]);
}

/** Where a routed cross-lane polyline meets the trunk its lane pair shares. */
interface CrossRoute {
  points: Point[];
  /** Index of the point where this route joins the trunk; -1 when it never does. */
  joinFrom: number;
  joinTo: number;
}

/**
 * Vertical elbows through the gutter between bands; long hops use the left
 * channel (VIEW-04).
 *
 * The two shoulders — where the run enters the corridor and where it leaves —
 * come from the lane pair's plan, so every member of a pair converges on ONE
 * trunk and splays off it by at most `BUNDLE_MEMBER_SPREAD`. The old `n * 7`
 * fan is gone: it was unbounded, so the seventh member of a pair was routed
 * through the lane boxes the channel was reserved to avoid.
 */
function routeCrossLane(env: RouteEnv, s: LayoutBox, t: LayoutBox, pair: LanePair, index: number): CrossRoute {
  const down = pair.down;
  const off = memberSplay(index, pair.members.length);

  const sy = down ? s.y + s.h : s.y;
  const ty = down ? t.y : t.y + t.h;
  const gy = round(pair.entryY + off);
  const gy1 = gy;
  const gy2 = round(pair.exitY + off);
  const channel = pair.trunkX;

  const simple = pair.adjacent
    ? [p(cx(s), sy), p(cx(s), gy), p(cx(t), gy), p(cx(t), ty)]
    : [p(cx(s), sy), p(cx(s), gy1), p(channel, gy1), p(channel, gy2), p(cx(t), gy2), p(cx(t), ty)];
  const simpleJoin: [Point, Point] = pair.adjacent ? [simple[1], simple[2]] : [simple[2], simple[3]];
  if (!pathCrosses(env, simple, s.id, t.id)) return joined(simple, simpleJoin);

  // Escape sideways into a free corridor, then use the gutter, which is empty by
  // construction, for the whole horizontal run.
  const exitY = pair.adjacent ? gy : gy1;
  const enterY = pair.adjacent ? gy : gy2;
  const sx = escapeToward(env, s, cx(t), cy(s), exitY, s.id, t.id);
  const tx = escapeToward(env, t, cx(s), enterY, cy(t), s.id, t.id);
  if (sx === null || tx === null) return joined(simple, simpleJoin);
  const sFace = sx >= cx(s) ? s.x + s.w : s.x;
  const tFace = tx >= cx(t) ? t.x + t.w : t.x;
  const detour = pair.adjacent
    ? [p(sFace, cy(s)), p(sx, cy(s)), p(sx, gy), p(tx, gy), p(tx, cy(t)), p(tFace, cy(t))]
    : [
        p(sFace, cy(s)),
        p(sx, cy(s)),
        p(sx, gy1),
        p(channel, gy1),
        p(channel, gy2),
        p(tx, gy2),
        p(tx, cy(t)),
        p(tFace, cy(t)),
      ];
  const detourJoin: [Point, Point] = pair.adjacent ? [detour[2], detour[3]] : [detour[3], detour[4]];
  if (pathCrosses(env, detour, s.id, t.id)) return joined(simple, simpleJoin);
  return joined(dedupe(detour), detourJoin);
}

/**
 * Locate the two shoulder points AFTER `dedupe` has had its say — a degenerate
 * zero-length step can drop one, and an index into a polyline that lost a point
 * would hand `layout/bundles.ts` the wrong corner.
 */
function joined(points: Point[], join: [Point, Point]): CrossRoute {
  return { points, joinFrom: points.indexOf(join[0]), joinTo: points.indexOf(join[1]) };
}

/**
 * Back-edge loop. Drops below both endpoint boxes — and below the construct the
 * edge returns to — then rises into the target's bottom edge, so the path never
 * enters the loop container it belongs to.
 */
function routeBack(
  env: RouteEnv,
  index: GraphIndex,
  frame: LayoutFrame,
  s: LayoutBox,
  t: LayoutBox,
  n: number,
): Point[] {
  const lane = frame.lanes[frame.laneIndex.get(s.laneId) ?? 0];
  let bottom = Math.max(s.y + s.h, t.y + t.h);
  const sAnc = new Set(index.ancestors(s.id));
  const tAnc = new Set(index.ancestors(t.id));
  for (const box of frame.boxes.values()) {
    if (box.laneId !== s.laneId) continue;
    if (box.id !== s.id && box.id !== t.id && (sAnc.has(box.id) || tAnc.has(box.id))) continue;
    const spanA = Math.min(cx(s), cx(t));
    const spanB = Math.max(cx(s), cx(t));
    if (box.x + box.w < spanA || box.x > spanB) continue;
    bottom = Math.max(bottom, box.y + box.h);
  }
  const y = round(Math.min(bottom + 12 + n * 7, lane ? lane.y + lane.h - 6 : bottom + 12));
  const tx = tAnc.has(s.id) || sAnc.has(t.id) ? round(t.x + Math.min(28, t.w / 3)) : cx(t);
  const simple = [p(cx(s), s.y + s.h), p(cx(s), y), p(tx, y), p(tx, t.y + t.h)];
  if (!pathCrosses(env, simple, s.id, t.id)) return simple;

  // The drop out of the source, or the rise into the target, would pass through
  // a card stacked under it: leave sideways through a free corridor instead.
  const sx = escapeToward(env, s, cx(t), cy(s), y, s.id, t.id);
  const ux = escapeToward(env, t, cx(s), y, cy(t), s.id, t.id);
  if (sx === null || ux === null) return simple;
  const sFace = sx >= cx(s) ? s.x + s.w : s.x;
  const tFace = ux >= cx(t) ? t.x + t.w : t.x;
  const detour = dedupe([p(sFace, cy(s)), p(sx, cy(s)), p(sx, y), p(ux, y), p(ux, cy(t)), p(tFace, cy(t))]);
  return pathCrosses(env, detour, s.id, t.id) ? simple : detour;
}

/** Spread parallel connections across the vertical face of a card. */
function anchorY(b: LayoutBox, n: number): number {
  if (n === 0) return round(cy(b));
  const span = Math.min(b.h - 16, 40);
  const step = span / 4;
  const k = ((n + 1) >> 1) * (n % 2 === 1 ? 1 : -1);
  return round(cy(b) + Math.max(-span / 2, Math.min(span / 2, k * step)));
}

/** Drop zero-length steps so the corner rounding never degenerates. */
function dedupe(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const pt of points) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - pt.x) < 0.01 && Math.abs(prev.y - pt.y) < 0.01) continue;
    out.push(pt);
  }
  return out.length >= 2 ? out : points;
}

function compareId(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function p(x: number, y: number): Point {
  return { x: round(x), y: round(y) };
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
