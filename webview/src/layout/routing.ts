/**
 * Edge routing. Orthogonal elbows with rounded corners; cross-lane edges pass
 * through the gutters between bands; control back-edges are drawn as loops that
 * stay OUTSIDE the box of the construct they return to.
 *
 * Every route but a self-edge's small loop (`routeSelf`) is obstacle-aware.
 * Each of those routers first proposes its natural elbow; if that elbow would be drawn
 * through the interior of a card that is neither endpoint nor an ancestor or
 * descendant of one, the route is re-planned through free corridors — the
 * vertical gaps the dagre pass already leaves between box columns, plus the
 * horizontal band reserved at the bottom of every lane. When the corridors give
 * no route clear of such cards, the natural elbow stays.
 *
 * Routing is pure geometry over the LayoutFrame, so it is as deterministic as
 * the layout it consumes.
 */

import type { MLEdge } from '../types.js';
import { GraphIndex } from './model.js';
import { LayoutBox, LayoutFrame, isBackEdge, isNotObserved } from './layout.js';
import { CORNER_R, ROUTE_CLEARANCE } from './constants.js';
import { BoxGrid } from './boxgrid.js';
import { CrossBucket, LanePair, memberSplay, planChannel } from './channel.js';
import { buildBundles } from './bundles.js';
import { midpointOf, orthPath } from './orth.js';
import type { Point } from './orth.js';
import { Rect, separateExceptions } from './separate.js';

// Module constants, not lookups of `Math` on the global object (`layout/separate.ts`).
const { abs, max, min } = Math;
const mathRound = Math.round;

/**
 * The polyline primitives live in `layout/orth.ts`, because the bundle layer
 * (`layout/bundles.ts`) draws trunks and spurs with the same pen. Re-exported
 * here so every import site can name one module for "a routed shape".
 */
export type { Point } from './orth.js';
export { midpointOf, orthPath } from './orth.js';

/**
 * This route's share of a cross-lane trunk.
 *
 * Stamped on an observed route that leaves its lane (an inferred or
 * unresolved one never joins a trunk). The corridor fields (`axis`,
 * `channelX`, `entryY`, `exitY`) are the SAME for every member of a pair, and
 * `joinFrom` / `joinTo` index this route's own `points` at the two places it
 * meets that trunk. `layout/bundles.ts` draws each trunk of a pair (a gutter
 * hop's pair can have several) and its splayed spurs from these and the route's
 * own `points`, WITHOUT writing `points` (spurs copy them) or touching `d`: the
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
  /** The trunk this route shares with the rest of its lane pair. */
  trunk?: TrunkRef;
  /**
   * True when a connection the route carries is inferred or unresolved, so it is
   * drawn dashed or dotted (the least certain basis, `routeBasis`). Such a route
   * has no trunk and runs on a track of its own (`layout/separate.ts`).
   */
  notObserved?: boolean;
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
  /** Flat obstacle list, in the frame's order. */
  all: LayoutBox[];
  /** `all` on a grid: a segment reads the boxes of the cells it covers. */
  grid: BoxGrid;
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
    for (const box of laneBoxes.get(lane.id) || []) bottom = max(bottom, box.y + box.h);
    band.set(lane.id, round(min(bottom + 9, lane.y + lane.h - 5)));
  }
  return { index, frame, laneBoxes, ancestry, band, all, grid: new BoxGrid(all) };
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

// Both predicates are pure and ANDed, so the geometric test runs first, over
// the grid, and the Map/Set lookups in `blocks` run only for a box the segment
// actually hits; the order changes no route. `test/geometry-golden.test.mjs`
// compares the routed geometry of its fixture with a recorded digest.
function pathCrosses(env: RouteEnv, points: Point[], s: string, t: string): boolean {
  const grid = env.grid;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const found = grid.hitBy(min(a.x, b.x), max(a.x, b.x), min(a.y, b.y), max(a.y, b.y));
    for (let k = 0; k < found; k++) if (blocks(env, env.all[grid.found[k]], s, t)) return true;
  }
  return false;
}

/**
 * How many times a polyline passes through a card it must avoid, the
 * router's own test (`segHitsBox`, `blocks`), a card counted once for each
 * segment through it. `layout/separate.ts` asks it for the count where a run lies,
 * then, for each offset that passes its cheaper tests, only whether the count is
 * above that one: with `limit`, the count stops once it has passed it.
 */
function hitCounter(env: RouteEnv): (points: Point[], s: string, t: string, limit?: number) => number {
  const grid = env.grid;
  return (points, s, t, limit = Infinity) => {
    let n = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1];
      const b = points[i];
      const found = grid.hitBy(min(a.x, b.x), max(a.x, b.x), min(a.y, b.y), max(a.y, b.y));
      for (let k = 0; k < found; k++) if (blocks(env, env.all[grid.found[k]], s, t) && ++n > limit) return n;
    }
    return n;
  };
}

/**
 * Free vertical corridors in a lane over the y-range a run needs, as x-intervals.
 * The dagre pass leaves `ranksep`/`nodesep` gaps between box columns; this turns
 * them into the list of x values a vertical run may legally use.
 */
function freeCorridors(env: RouteEnv, laneId: string, y0: number, y1: number, s: string, t: string): { a: number; b: number }[] {
  const laneIdx = env.frame.laneIndex.get(laneId);
  const lane = laneIdx === undefined ? null : env.frame.lanes[laneIdx];
  const lo = min(y0, y1);
  const hi = max(y0, y1);
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
    if (span.a > cursor) out.push({ a: cursor, b: min(span.a, right) });
    cursor = max(cursor, span.b);
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
      const a = max(iv.a, box.x + box.w + 4);
      if (iv.b - a >= 10) candidates.push(round((a + min(iv.b, a + 40)) / 2));
    } else {
      const b = min(iv.b, box.x - 4);
      if (b - iv.a >= 10) candidates.push(round((max(iv.a, b - 40) + b) / 2));
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
    // Two ends folded into one collapsed group are hidden inside it. A document self-edge on a
    // drawn node is different: the authored contract allows it, and it is drawn as a loop on the
    // card rather than dropped.
    if (s === t && !(e.source === e.target && s === e.source)) continue;
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

  // The cross-lane buckets are collected FIRST, because a trunk is a
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
    crossBuckets.push({ key, sBox, tBox, own: bucket.edges.some(isNotObserved) });
  }
  const channel = planChannel(frame, crossBuckets);

  const backCounters = new Map<string, number>();
  const gutterCounters = new Map<string, number>();
  const selfCounters = new Map<string, number>();
  const out: RoutedEdge[] = [];

  for (const key of order) {
    const bucket = groups.get(key)!;
    const first = bucket.edges[0];
    const sBox = frame.boxes.get(bucket.s)!;
    const tBox = frame.boxes.get(bucket.t)!;
    const back = isBackEdge(first);
    const crossLane = sBox.laneId !== tBox.laneId;
    // The least certain basis decides, as it decides the dashes (`routeBasis`).
    const notObserved = bucket.edges.some(isNotObserved);

    const sInsideT = index.ancestors(bucket.s).indexOf(bucket.t) >= 0;
    const tInsideS = index.ancestors(bucket.t).indexOf(bucket.s) >= 0;

    let points: Point[];
    let trunk: TrunkRef | undefined;
    if (bucket.s === bucket.t) {
      points = routeSelf(sBox, bump(selfCounters, bucket.s));
    } else if (back) {
      const n = bump(backCounters, sBox.laneId);
      points = routeBack(env, index, frame, sBox, tBox, n);
    } else if (tInsideS || sInsideT) {
      points = routeContainment(env, sBox, tBox, tInsideS);
    } else if (crossLane) {
      const pair = channel.pairOf.get(key)!;
      const idx = channel.indexOf.get(key) || 0;
      const routed = routeCrossLane(env, sBox, tBox, pair, idx);
      points = routed.points;
      if (!notObserved && routed.joinFrom >= 0 && routed.joinTo > routed.joinFrom) {
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
      ...(notObserved ? { notObserved: true } : {}),
    });
  }
  separate(env, out);
  return out;
}

/**
 * Move the inferred and unresolved routes off the strokes every other
 * route, trunk and spur draws (`layout/separate.ts`). Observed routes are not
 * touched, so the trunks built from them here are the ones the scene plan builds.
 */
function separate(env: RouteEnv, routes: RoutedEdge[]): void {
  const moving = routes.filter((r) => r.notObserved);
  if (moving.length === 0) return;
  const fixed: Point[][] = [];
  for (const route of routes) if (!route.notObserved) fixed.push(route.points);
  for (const bundle of buildBundles(routes)) {
    fixed.push(bundle.trunk);
    for (const spur of bundle.spurs) fixed.push(spur.points);
  }
  const headers: Rect[] = env.frame.lanes.map((lane) => ({ x: lane.x, y: lane.y, w: lane.w, h: lane.headerH }));
  for (const box of env.all) if (box.headerH > 0) headers.push({ x: box.x, y: box.y, w: box.w, h: box.headerH });
  const outlines: Rect[] = env.frame.lanes.map((lane) => ({ x: lane.x, y: lane.y, w: lane.w, h: lane.h }));
  for (const box of env.all) outlines.push({ x: box.x, y: box.y, w: box.w, h: box.h });
  const moved = separateExceptions(
    {
      boxes: env.frame.boxes,
      hits: hitCounter(env),
      cardsRead: () => env.grid.read,
      headers,
      outlines,
      bandsLeft: min(...env.frame.lanes.map((lane) => lane.x)),
      width: env.frame.width,
      height: env.frame.height,
    },
    fixed,
    moving,
  );
  moving.forEach((route, i) => {
    if (moved[i] === route.points) return;
    route.points = moved[i];
    route.d = orthPath(route.points, CORNER_R);
    const midInfo = midpointOf(route.points);
    route.mid = midInfo.point;
    route.midAngle = midInfo.angle;
  });
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
  const headerY = outer.y + min(28, outer.h / 2);
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
      abs(sy - ty) < 0.5 ? [p(sx, sy), p(tx, ty)] : [p(sx, sy), p(mx, sy), p(mx, ty), p(tx, ty)];
  } else {
    // Target sits left of, or overlaps, the source: detour under both boxes.
    const lane = frame.lanes[frame.laneIndex.get(s.laneId) ?? 0];
    const drop = max(s.y + s.h, t.y + t.h) + 14 + n * 6;
    const limit = lane ? lane.y + lane.h - 6 : drop;
    const y = round(min(drop, limit));
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
  const y = round((env.band.get(s.laneId) ?? max(s.y + s.h, t.y + t.h) + 12) + n * 5);
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
 * channel.
 *
 * The two shoulders — where the run enters the corridor and where it leaves —
 * come from the lane pair's plan, so every member of a pair converges on ONE
 * trunk and splays off it by at most `BUNDLE_MEMBER_SPREAD`. The splay is
 * bounded: a fan that grew with each member would route the later members of a
 * large pair through the lane boxes the channel is reserved to avoid.
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
  let bottom = max(s.y + s.h, t.y + t.h);
  const sAnc = new Set(index.ancestors(s.id));
  const tAnc = new Set(index.ancestors(t.id));
  for (const box of frame.boxes.values()) {
    if (box.laneId !== s.laneId) continue;
    if (box.id !== s.id && box.id !== t.id && (sAnc.has(box.id) || tAnc.has(box.id))) continue;
    const spanA = min(cx(s), cx(t));
    const spanB = max(cx(s), cx(t));
    if (box.x + box.w < spanA || box.x > spanB) continue;
    bottom = max(bottom, box.y + box.h);
  }
  const y = round(min(bottom + 12 + n * 7, lane ? lane.y + lane.h - 6 : bottom + 12));
  const tx = tAnc.has(s.id) || sAnc.has(t.id) ? round(t.x + min(28, t.w / 3)) : cx(t);
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

/**
 * A self-edge: a small loop off the card's lower-right corner that leaves the right face and
 * returns up into the bottom face, the way a back-edge rises into its target. The first loop
 * stays inside a parent group's padding (GROUP_PAD) and the gaps dagre leaves between cards;
 * further self-edges on the same card (other kinds) nest outward, 6 px apart.
 */
function routeSelf(b: LayoutBox, n: number): Point[] {
  const out = 14 + n * 6;
  const right = b.x + b.w;
  const bottom = b.y + b.h;
  const exitY = bottom - min(14 + n * 6, b.h / 2);
  const entryX = right - min(28 + n * 6, b.w / 2);
  return [p(right, exitY), p(right + out, exitY), p(right + out, bottom + out), p(entryX, bottom + out), p(entryX, bottom)];
}

/** Spread parallel connections across the vertical face of a card. */
function anchorY(b: LayoutBox, n: number): number {
  if (n === 0) return round(cy(b));
  const span = min(b.h - 16, 40);
  const step = span / 4;
  const k = ((n + 1) >> 1) * (n % 2 === 1 ? 1 : -1);
  return round(cy(b) + max(-span / 2, min(span / 2, k * step)));
}

/** Drop zero-length steps so the corner rounding never degenerates. */
function dedupe(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const pt of points) {
    const prev = out[out.length - 1];
    if (prev && abs(prev.x - pt.x) < 0.01 && abs(prev.y - pt.y) < 0.01) continue;
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
  return mathRound(v * 100) / 100;
}
