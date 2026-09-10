/**
 * VIEW-04 — one trunk per lane pair, as geometry.
 *
 * `routeEdges` stamps every cross-lane route with a `TrunkRef`: the corridor its
 * (source lane, target lane) pair shares, and the two indices at which this
 * route's own polyline joins and leaves it. This module turns those routes into
 * the bundles the renderer draws — one trunk, one splayed spur per member at
 * each end, and a member-count badge — and it does so WITHOUT reading or writing
 * `points` beyond those indices and WITHOUT touching `d`. That is the item's
 * hard constraint: the flow charge rides each edge's own `d` through an
 * `<mpath>` and the SVG export emits the same string, so a bundle has to be a
 * second drawing of unchanged routes, never a replacement for them.
 *
 * The trunk is the members' COMMON run, not just the channel column:
 *
 *   a skipping hop      ┌──────────────  ← entry spurs splay off here
 *                    ───┤                  (each member's own approach)
 *                       │  the shared vertical in the left channel
 *                    ───┤
 *                       └──────────────  ← exit spurs splay off here
 *
 * so the long horizontal into the channel — which every member of a pair drew
 * for itself, fanned over 140 px by the old `n * 7` stagger — is drawn once.
 *
 * A group is bundled only when it has two or more members and a common run long
 * enough to read as one. Anything else stays exactly as it was drawn before,
 * which is also what the reader sees the moment they hover a bundle.
 */

import { BUNDLE_MIN_TRUNK, CORNER_R } from './constants.js';
import { orthPath } from './orth.js';
import type { Point } from './orth.js';
import type { RoutedEdge, TrunkRef } from './routing.js';

export interface BundleSpur {
  /** The route this spur belongs to. */
  id: string;
  /** `in` leads into the trunk's head, `out` leaves its tail. */
  side: 'in' | 'out';
  points: Point[];
  d: string;
}

export interface EdgeBundle {
  /** `bundle:<source lane>><target lane>` — stable across re-renders. */
  id: string;
  sourceLane: string;
  targetLane: string;
  /** Route ids, in the barycentre order the channel plan chose. */
  memberIds: string[];
  /** Routes in the group. */
  count: number;
  /** Document edges those routes carry — routes merge parallel connections. */
  edgeCount: number;
  /** `y` for a channel trunk, `x` for a gutter trunk. */
  axis: 'x' | 'y';
  /** The shared run, in travel order. */
  trunk: Point[];
  /** The trunk's own rounded path. */
  d: string;
  /** Entry spurs first, then exit spurs, both in member order. */
  spurs: BundleSpur[];
  /** Where the count badge sits — the middle of the longest trunk segment. */
  badge: Point;
  /** The distinct edge kinds inside the bundle, in first-seen order. */
  kinds: string[];
}

/**
 * Group `routes` into drawable bundles. Pure, order-preserving and total: a
 * route with no trunk, a group of one, or a common run under `BUNDLE_MIN_TRUNK`
 * px simply yields no bundle, and its strokes are drawn as they always were.
 */
export function buildBundles(routes: RoutedEdge[]): EdgeBundle[] {
  const groups = new Map<string, RoutedEdge[]>();
  const order: string[] = [];
  for (const route of routes) {
    if (!usable(route)) continue;
    const key = route.trunk!.key;
    const list = groups.get(key);
    if (list) list.push(route);
    else {
      groups.set(key, [route]);
      order.push(key);
    }
  }

  const out: EdgeBundle[] = [];
  for (const key of order) {
    const members = groups.get(key)!;
    if (members.length < 2) continue;
    // Barycentre order is the plan's; re-assert it here so a bundle drawn from a
    // filtered or re-ordered route list still splays its spurs in the same order.
    members.sort((a, b) => a.trunk!.index - b.trunk!.index || compare(a.id, b.id));
    const bundle = members[0].trunk!.axis === 'y' ? channelBundle(key, members) : gutterBundle(key, members);
    if (bundle) out.push(bundle);
  }
  return out;
}

/** A route can only join a trunk if both of its shoulders survived `dedupe`. */
function usable(route: RoutedEdge): boolean {
  const ref = route.trunk;
  if (!ref) return false;
  if (ref.joinFrom < 1 || ref.joinTo <= ref.joinFrom) return false;
  return ref.joinTo + 1 <= route.points.length - 1;
}

/**
 * A hop that skips a lane: the trunk is the shoulder into the channel, the
 * vertical column, and the shoulder back out. The shoulders stop at the member
 * whose approach is SHORTEST, so no trunk is ever drawn across ground that only
 * one cable covers.
 */
function channelBundle(key: string, members: RoutedEdge[]): EdgeBundle | null {
  const ref = members[0].trunk!;
  const chX = ref.channelX;
  let headX = Infinity;
  let tailX = Infinity;
  for (const route of members) {
    headX = Math.min(headX, route.points[route.trunk!.joinFrom - 1].x);
    tailX = Math.min(tailX, route.points[route.trunk!.joinTo + 1].x);
  }
  const column = Math.abs(ref.exitY - ref.entryY);
  if (column < BUNDLE_MIN_TRUNK) return null;
  const trunk = dedupe([p(headX, ref.entryY), p(chX, ref.entryY), p(chX, ref.exitY), p(tailX, ref.exitY)]);

  const spurs: BundleSpur[] = [];
  for (const route of members) {
    const j = route.trunk!.joinFrom;
    const y = route.points[j].y;
    const lead = dedupe(route.points.slice(0, j).concat([p(headX, y), p(headX, ref.entryY)]));
    spurs.push({ id: route.id, side: 'in', points: lead, d: orthPath(lead, CORNER_R) });
  }
  for (const route of members) {
    const j = route.trunk!.joinTo;
    const y = route.points[j].y;
    const tail = dedupe([p(tailX, ref.exitY), p(tailX, y)].concat(route.points.slice(j + 1)));
    spurs.push({ id: route.id, side: 'out', points: tail, d: orthPath(tail, CORNER_R) });
  }

  return assemble(key, members, ref, trunk, spurs, p(chX, (ref.entryY + ref.exitY) / 2));
}

/**
 * A hop between neighbouring bands: the trunk is the stretch of gutter every
 * member crosses. When they do not all cross the same stretch there is nothing
 * to bundle, and the group is drawn as it always was.
 */
function gutterBundle(key: string, members: RoutedEdge[]): EdgeBundle | null {
  const ref = members[0].trunk!;
  let lo = -Infinity;
  let hi = Infinity;
  for (const route of members) {
    const a = route.points[route.trunk!.joinFrom].x;
    const b = route.points[route.trunk!.joinTo].x;
    lo = Math.max(lo, Math.min(a, b));
    hi = Math.min(hi, Math.max(a, b));
  }
  if (!(hi - lo >= BUNDLE_MIN_TRUNK)) return null;
  const trunk = [p(lo, ref.entryY), p(hi, ref.entryY)];

  const spurs: BundleSpur[] = [];
  for (const route of members) {
    const j = route.trunk!.joinFrom;
    const rightward = route.points[j].x <= route.points[route.trunk!.joinTo].x;
    const end = rightward ? lo : hi;
    const lead = dedupe(route.points.slice(0, j + 1).concat([p(end, route.points[j].y), p(end, ref.entryY)]));
    spurs.push({ id: route.id, side: 'in', points: lead, d: orthPath(lead, CORNER_R) });
  }
  for (const route of members) {
    const j = route.trunk!.joinTo;
    const rightward = route.points[route.trunk!.joinFrom].x <= route.points[j].x;
    const end = rightward ? hi : lo;
    const tail = dedupe([p(end, ref.entryY), p(end, route.points[j].y)].concat(route.points.slice(j)));
    spurs.push({ id: route.id, side: 'out', points: tail, d: orthPath(tail, CORNER_R) });
  }

  return assemble(key, members, ref, trunk, spurs, p((lo + hi) / 2, ref.entryY));
}

function assemble(
  key: string,
  members: RoutedEdge[],
  ref: TrunkRef,
  trunk: Point[],
  spurs: BundleSpur[],
  badge: Point,
): EdgeBundle {
  const kinds: string[] = [];
  let edgeCount = 0;
  for (const route of members) {
    edgeCount += route.ids.length;
    if (kinds.indexOf(route.kind) < 0) kinds.push(route.kind);
  }
  return {
    id: 'bundle:' + key,
    sourceLane: ref.sourceLane,
    targetLane: ref.targetLane,
    memberIds: members.map((r) => r.id),
    count: members.length,
    edgeCount,
    axis: ref.axis,
    trunk,
    d: orthPath(trunk, CORNER_R),
    spurs: spurs.filter((s) => s.points.length > 1),
    badge,
    kinds,
  };
}

function dedupe(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const pt of points) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - pt.x) < 0.01 && Math.abs(prev.y - pt.y) < 0.01) continue;
    out.push(pt);
  }
  return out;
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function p(x: number, y: number): Point {
  return { x: round(x), y: round(y) };
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
