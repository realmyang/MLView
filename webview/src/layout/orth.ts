/**
 * Orthogonal polyline primitives: the point, the rounded path and the midpoint.
 *
 * Split out of `routing.ts` when VIEW-04 gave the cross-lane edges a second
 * drawing — `layout/bundles.ts` builds trunks and spurs out of the same corners
 * the router builds cables out of, and the two should share the pen rather than
 * one importing the other's internals. Pure arithmetic: no frame, no obstacles,
 * no DOM, and nothing measured through the DOM at all (F1-A3: jsdom implements
 * none of the SVG path-length API, so a length taken from the document would
 * make the tested path a different path from the shipped one).
 */

export interface Point {
  x: number;
  y: number;
}

/** Rounded orthogonal polyline. */
export function orthPath(points: Point[], r: number): string {
  if (points.length < 2) return '';
  const parts: string[] = ['M ' + points[0].x + ' ' + points[0].y];
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const next = points[i + 1];
    const inLen = dist(prev, cur);
    const outLen = dist(cur, next);
    const rad = Math.max(0, Math.min(r, inLen / 2, outLen / 2));
    if (rad < 0.75) {
      parts.push('L ' + cur.x + ' ' + cur.y);
      continue;
    }
    const a = lerp(cur, prev, rad / (inLen || 1));
    const b = lerp(cur, next, rad / (outLen || 1));
    parts.push('L ' + round(a.x) + ' ' + round(a.y));
    parts.push('Q ' + cur.x + ' ' + cur.y + ' ' + round(b.x) + ' ' + round(b.y));
  }
  const last = points[points.length - 1];
  parts.push('L ' + last.x + ' ' + last.y);
  return parts.join(' ');
}

/** Point and direction at half the polyline's length — where markers and labels go. */
export function midpointOf(points: Point[]): { point: Point; angle: number } {
  if (points.length === 0) return { point: { x: 0, y: 0 }, angle: 0 };
  if (points.length === 1) return { point: points[0], angle: 0 };
  let total = 0;
  for (let i = 1; i < points.length; i++) total += dist(points[i - 1], points[i]);
  let walked = 0;
  const half = total / 2;
  for (let i = 1; i < points.length; i++) {
    const seg = dist(points[i - 1], points[i]);
    if (walked + seg >= half || i === points.length - 1) {
      const f = seg === 0 ? 0 : (half - walked) / seg;
      const pt = lerp(points[i - 1], points[i], Math.max(0, Math.min(1, f)));
      const angle = (Math.atan2(points[i].y - points[i - 1].y, points[i].x - points[i - 1].x) * 180) / Math.PI;
      return { point: { x: round(pt.x), y: round(pt.y) }, angle };
    }
    walked += seg;
  }
  return { point: points[points.length - 1], angle: 0 };
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}

function dist(a: Point, b: Point): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

function lerp(from: Point, to: Point, f: number): Point {
  return { x: from.x + (to.x - from.x) * f, y: from.y + (to.y - from.y) * f };
}
