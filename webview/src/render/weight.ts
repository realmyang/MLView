/**
 * The weight of a drawn cable: how many authored connections one routed path
 * stands for. `layout/routing.ts` merges connections whose endpoints share the
 * same two boxes (most often once a group is collapsed), and the merged cable is
 * drawn thicker with a `×N` pill.
 *
 * Both renderers import this module, so the DOM and the SVG export draw the same
 * stroke and put the pill in the same place.
 *
 * Pure: no DOM, no clock, no `this`.
 */

/** A weight of 1 is an ordinary connection; the pill and the wider stroke start at 2. */
export const WEIGHT_MIN = 2;

/** Stroke width in px at weight 1, and the widest a cable is ever drawn. */
const STROKE_BASE = 1.5;
const STROKE_MAX = 5;

/** The weight of a drawn route: the number of connections it merges (at least 1). */
export function routeWeight(ids: string[]): number {
  return ids.length || 1;
}

/** Stroke width for a weight, growing with its log so 200 is not 200 px wide. */
export function weightStroke(weight: number): number {
  if (weight < WEIGHT_MIN) return STROKE_BASE;
  const grown = STROKE_BASE + Math.log2(weight) * 0.75;
  return Math.round(Math.min(STROKE_MAX, grown) * 100) / 100;
}

/** The `×7` a weighted cable carries. */
export function weightBadgeText(weight: number): string {
  return '×' + weight;
}

/** How far off the stroke the badge is pushed when the midpoint is taken. */
const WEIGHT_NUDGE = 13;

/**
 * Where the `×7` pill goes: the route's midpoint, pushed along the route's own
 * normal when a severity glyph or a loop chevron already owns that point.
 */
export function weightBadgeAt(
  mark: { x: number; y: number },
  angle: number,
  occupied: boolean,
): { x: number; y: number } {
  if (!occupied) return { x: mark.x, y: mark.y };
  const a = typeof angle === 'number' && isFinite(angle) ? angle : 0;
  return {
    x: mark.x + Math.cos(a + Math.PI / 2) * WEIGHT_NUDGE,
    y: mark.y + Math.sin(a + Math.PI / 2) * WEIGHT_NUDGE,
  };
}

/** Pill width for a weight, so both renderers size the same rectangle. */
export function weightBadgeWidth(weight: number): number {
  return Math.round(weightBadgeText(weight).length * 5.6 + 10);
}

/** Pill height, shared for the same reason. */
export const WEIGHT_BADGE_H = 13;
