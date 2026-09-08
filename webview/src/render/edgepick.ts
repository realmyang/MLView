/**
 * Which cable is the pointer on?
 *
 * `.mlv-edge__hit` is a 12 px transparent stroke laid over `route.d`, and the
 * router deliberately packs edges that share a gutter on top of one another. DOM
 * hit-testing therefore hands the whole shared run to whichever `<g>` happens to
 * be LAST in document order, and every other cable in that gutter becomes
 * unhoverable: on the shipped sample five connections owned none of their own
 * pixels and thirteen more owned under a third of them (MLV-R1-FLOW-006).
 *
 * That was survivable while a hover only opened a tooltip. It is not survivable
 * now that hovering is the gesture Feature 1 hangs off: instead of nothing
 * happening, the WRONG connection lights end to end, which is an active lie
 * about the pipeline.
 *
 * So the pointer's owner is resolved GEOMETRICALLY, from the same
 * `RoutedEdge.points` polylines the flow layer measures — no `elementFromPoint`,
 * no DOM measurement, and therefore identical in jsdom and in Chromium. The
 * caller raises the winner to the top of the edge layer, which also fixes the
 * plain document-order case for as long as the pointer tracks along it.
 */

import type { Point, RoutedEdge } from '../layout/routing.js';

/** Squared distance from `p` to the segment `a`-`b`. Squared: no sqrt in the loop. */
export function pointSegmentDist2(p: Point, a: Point, b: Point): number {
  const vx = b.x - a.x;
  const vy = b.y - a.y;
  const wx = p.x - a.x;
  const wy = p.y - a.y;
  const len2 = vx * vx + vy * vy;
  let t = len2 > 0 ? (wx * vx + wy * vy) / len2 : 0;
  if (t < 0) t = 0;
  else if (t > 1) t = 1;
  const dx = wx - t * vx;
  const dy = wy - t * vy;
  return dx * dx + dy * dy;
}

/** The closest approach of the route's own polyline to `p`, in world units. */
export function routeDistance(route: RoutedEdge, p: Point): number {
  const points = route.points || [];
  if (points.length === 0) return Infinity;
  if (points.length === 1) {
    const dx = p.x - points[0].x;
    const dy = p.y - points[0].y;
    return Math.sqrt(dx * dx + dy * dy);
  }
  let best = Infinity;
  for (let i = 1; i < points.length; i++) {
    const d2 = pointSegmentDist2(p, points[i - 1], points[i]);
    if (d2 < best) best = d2;
  }
  return Math.sqrt(best);
}

/**
 * The route whose polyline passes closest to `p`, or null when the nearest one
 * is further away than `maxDistance` (world units — the caller divides its
 * screen-space tolerance by the zoom). Ties keep the earlier route, so the
 * answer is stable for a stationary pointer.
 */
export function nearestRoute(routes: RoutedEdge[], p: Point, maxDistance: number): RoutedEdge | null {
  let best: RoutedEdge | null = null;
  let bestDist = maxDistance;
  for (const route of routes) {
    const d = routeDistance(route, p);
    if (d < bestDist) {
      bestDist = d;
      best = route;
    }
  }
  return best;
}
