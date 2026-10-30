/**
 * A FAR CONNECTION in the review walk: one whose two end cards cannot both be shown on the
 * canvas.
 *
 * The walk keeps such a connection's source card in view, with the start of its lit line. Where
 * the line runs out of sight on its way to the other card it ends in a cap: three dots in a
 * lozenge, in the line's own colour and with its dashed or dotted outline when the line is drawn
 * so, for an inferred or unresolved connection (`render/farcap.ts`). One line in the walk bar
 * (`ui/walkbar.ts`) names the other card with its direction, its distance and the key that goes
 * there and back.
 *
 * This module is the rules, as pure functions of boxes, polylines, a viewport and the document's
 * index: what counts as in view, how much of the line the walk shows with the card it keeps, where
 * the cap sits, which way and how far the other card lies, and every sentence said about it. It
 * reads no DOM and moves nothing. `canvas/far.ts` moves the view and draws the caps; `app/far.ts`
 * ties the walk, the bar and the canvas together.
 */

import { READABLE_ZOOM } from './render/canvas.js';
import type { Rect } from './render/canvas.js';
import type { GraphIndex } from './layout/model.js';
import type { Viewport } from './types.js';

/** One end of a connection. */
export type End = 'source' | 'target';

export interface XY {
  x: number;
  y: number;
}

export interface Area {
  w: number;
  h: number;
}

/** An inferred or unresolved connection: drawn dashed or dotted, so the reader sees it is uncertain. */
export function isUncertain(basis: string | null | undefined): boolean {
  return !!basis && basis !== 'observed';
}

/* ── what is in view ─────────────────────────────────────────────────────────────────────── */

const inRect = (p: XY, r: Rect): boolean => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
const grow = (r: Rect, dx: number, dy: number): Rect => ({ x: r.x - dx, y: r.y - dy, w: r.w + 2 * dx, h: r.h + 2 * dy });

/** The rectangle around two boxes: a connection's two end cards. */
export function unionOf(a: Rect, b: Rect): Rect {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
}

/** Whether a box fits a canvas at `zoom` with `margin` px to spare (`ViewportController.fitsAt`). */
export function fitsCanvas(box: { w: number; h: number }, area: Area, zoom: number, margin = 48): boolean {
  return Math.min((area.w - margin) / Math.max(1, box.w), (area.h - margin) / Math.max(1, box.h)) >= zoom;
}

/**
 * A world rectangle is whole on the canvas and clear of the phase index (`covered`, in canvas
 * pixels), half a pixel of rounding allowed. `ViewportController.isVisible` allows none, and calls
 * a card that sits exactly on the canvas's edge, where a least pan leaves it, out of view.
 */
export function inView(box: Rect, vp: Viewport, area: Area, covered: Rect | null): boolean {
  const z = vp.zoom;
  const r = { x: box.x * z + vp.x, y: box.y * z + vp.y, w: box.w * z, h: box.h * z };
  const eps = 0.5;
  if (!(r.x >= -eps && r.y >= -eps && r.x + r.w <= area.w + eps && r.y + r.h <= area.h + eps)) return false;
  return !covered || !(r.x < covered.x + covered.w && covered.x < r.x + r.w && r.y < covered.y + covered.h && covered.y < r.y + r.h);
}

/** Whether the segment from `a` to `b` passes through the inside of `r`; touching its edge does not count. */
function crosses(a: XY, b: XY, r: Rect): boolean {
  let t0 = 0;
  let t1 = 1;
  // Liang and Barsky: what each of the rectangle's four sides in turn leaves of the segment.
  const clip = (p: number, q: number): boolean => {
    if (p === 0) return q > 0;
    const t = q / p;
    if (p < 0) {
      if (t > t1) return false;
      if (t > t0) t0 = t;
    } else {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    }
    return true;
  };
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  return clip(-dx, a.x - r.x) && clip(dx, r.x + r.w - a.x) && clip(-dy, a.y - r.y) && clip(dy, r.y + r.h - a.y) && t0 < t1;
}

/**
 * A line (world coordinates) is on the canvas from end to end and clear of the phase index
 * (`covered`, in canvas pixels), half a pixel of rounding allowed. False when it is not drawn.
 */
export function lineInView(points: readonly XY[] | null, vp: Viewport, area: Area, covered: Rect | null): boolean {
  if (!points || points.length < 2) return false;
  const eps = 0.5;
  const pts = points.map((p) => ({ x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y }));
  if (!pts.every((p) => p.x >= -eps && p.y >= -eps && p.x <= area.w + eps && p.y <= area.h + eps)) return false;
  if (!covered) return true;
  for (let i = 1; i < pts.length; i++) if (crosses(pts[i - 1], pts[i], covered)) return false;
  return true;
}

/* ── the start of the line ───────────────────────────────────────────────────────────────── */

/**
 * How much of a far connection's line the walk shows beside the card it keeps, in screen pixels
 * along the line from that card (`leadBox`). An inferred or unresolved connection gets three times
 * as much, or two thirds of the canvas's shorter side when that is less: its dashed or dotted
 * stroke is what tells the reader it is uncertain, so the stroke gets the room.
 */
export const FAR_LEAD_PX = 80;
export const FAR_LEAD_UNCERTAIN_PX = 240;

/** The room around the place a line leaves an open group (`portBox`), in screen pixels. */
const PORT_PAD_PX = 24;

/**
 * An end card of a connection together with the start of its line from that card: what the walk
 * shows of a far connection, so the reader sees which way the lit line sets off before it reaches
 * its cap. The card alone when the line is not drawn.
 *
 * `points` is the line in world coordinates, source first; `px` is how much of it, in screen
 * pixels at `zoom`. With `behind` (the other cards, in world coordinates), how much of it IN
 * SIGHT: a stretch that runs behind another card (the connections are drawn under the cards) is
 * taken into the box and not counted, so a line that leaves its card straight into a neighbour is
 * followed until it comes out again, and the reader sees that it passes behind that card and does
 * not end there. Without `withCard` the box is the stretch alone.
 */
export function leadBox(points: readonly XY[] | null, end: End, card: Rect, px: number, zoom: number, opts: { withCard?: boolean; behind?: readonly Rect[] } = {}): Rect {
  if (!points || points.length < 2 || !(px > 0)) return card;
  const pts = end === 'source' ? points : points.slice().reverse();
  const withCard = opts.withCard !== false;
  const z = Math.max(0.01, zoom);
  let left = px / z;
  let x0 = withCard ? card.x : pts[0].x;
  let y0 = withCard ? card.y : pts[0].y;
  let x1 = withCard ? card.x + card.w : pts[0].x;
  let y1 = withCard ? card.y + card.h : pts[0].y;
  const take = (p: XY) => {
    x0 = Math.min(x0, p.x);
    y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x);
    y1 = Math.max(y1, p.y);
  };
  const behind = opts.behind || [];
  const hidden = (p: XY) => behind.some((c) => p.x > c.x && p.x < c.x + c.w && p.y > c.y && p.y < c.y + c.h);
  take(pts[0]);
  for (let i = 1; i < pts.length && left > 0; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const length = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    if (!behind.length) {
      const t = length > left ? left / length : 1;
      take({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
      left -= length;
      continue;
    }
    // Two screen pixels at a time: what lies behind a card is taken and not counted.
    const n = Math.max(1, Math.min(4000, Math.ceil((length * z) / 2)));
    for (let k = 1; k <= n && left > 0; k++) {
      const p = { x: a.x + ((b.x - a.x) * k) / n, y: a.y + ((b.y - a.y) * k) / n };
      take(p);
      if (!hidden(p)) left -= length / n;
    }
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

/**
 * The leads the walk tries for the card it keeps, longest first; the first that fits the canvas
 * with the card is used. `inSight`: counted as `leadBox` counts with `behind`, so a stretch behind
 * a neighbouring card does not use the lead up; else as the line runs.
 */
export function leadChoices(uncertain: boolean, area: Area): Array<{ px: number; inSight: boolean }> {
  const short = [{ px: FAR_LEAD_PX, inSight: true }, { px: FAR_LEAD_PX, inSight: false }];
  if (!uncertain) return short;
  const long = Math.min(FAR_LEAD_UNCERTAIN_PX, Math.round(Math.min(area.w, area.h) * 0.66));
  return [{ px: long, inSight: true }, ...short];
}

/**
 * For an end card that does not fit the canvas at reading size (an open group, drawn around the
 * steps inside it; any card on a canvas shorter than one): the stretch of line that leaves it,
 * FAR_LEAD_PX long. That is what "in view" means for such an end, and, with a little room around
 * it (`portBox`), what the walk keeps in view of it; its corner, where a plain reveal would put
 * the canvas, can lie screens from its line. Null for a card that fits, and when the line is not
 * drawn.
 */
export function portStretch(points: readonly XY[] | null, end: End, card: Rect, zoom: number, area: Area): Rect | null {
  if (fitsCanvas(card, area, READABLE_ZOOM, 0)) return null;
  if (!points || points.length < 2) return null;
  return leadBox(points, end, card, FAR_LEAD_PX, zoom, { withCard: false });
}

/** `portStretch` with PORT_PAD_PX of room around it: what the walk reveals of such an end. */
export function portBox(points: readonly XY[] | null, end: End, card: Rect, zoom: number, area: Area): Rect | null {
  return portStretch(points, end, card, zoom, area) ? meetBox(points, end, card, zoom) : null;
}

/**
 * The place a connection's line meets one of its end cards: the FAR_LEAD_PX of the line next to
 * the card, with PORT_PAD_PX of room around it. What the walk shows of an end that it cannot show
 * whole together with its line. Null when the line is not drawn.
 */
export function meetBox(points: readonly XY[] | null, end: End, card: Rect, zoom: number): Rect | null {
  if (!points || points.length < 2) return null;
  const pad = PORT_PAD_PX / Math.max(0.01, zoom);
  return grow(leadBox(points, end, card, FAR_LEAD_PX, zoom, { withCard: false }), pad, pad);
}

/* ── the two ends as the canvas shows them ───────────────────────────────────────────────── */

/** The eight ways the walk bar's arrow points, clockwise from "right"; the index times 45 degrees. */
export type Compass = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;

export interface FarWay {
  /**
   * Which way the card lies: from the middle of the canvas, or, for a card that is partly in
   * sight, from the connection's other card (`FarView.ends`).
   */
  compass: Compass;
  /** "down", "up and to the right"…: the same in words. */
  words: string;
  /**
   * How far: the pan that would centre the card, in canvas heights (up or down) or widths (left
   * or right), whichever is more. A screen is what the reader sees now, at this zoom, so the unit
   * means the same on a narrow panel and a wide one, and inside one phase or across several.
   */
  screens: number;
}

const WAY_WORDS = ['right', 'down and to the right', 'down', 'down and to the left', 'left', 'up and to the left', 'up', 'up and to the right'];
/** The same eight ways as a place: "off screen below", "partly in view to the right". */
const SIDE_WORDS = ['to the right', 'below and to the right', 'below', 'below and to the left', 'to the left', 'above and to the left', 'above', 'above and to the right'];

/**
 * Which way, and how many screens away, a card (a world rectangle) lies from the canvas's middle.
 * With `from` (another world rectangle: the connection's other card) the way is taken from that
 * card's middle instead. A card beside it that the canvas's edge cuts by a few pixels, or that
 * stands with a corner under the phase index, lies to its side, wherever the canvas's middle is:
 * taken from the middle, the way to a card at the top right of the canvas can come out as "up".
 * The screens are counted from the canvas's middle either way.
 */
export function farWay(box: Rect, vp: Viewport, area: Area, from?: Rect): FarWay {
  const cx = (box.x + box.w / 2) * vp.zoom + vp.x;
  const cy = (box.y + box.h / 2) * vp.zoom + vp.y;
  const sx = (cx - area.w / 2) / Math.max(1, area.w);
  const sy = (cy - area.h / 2) / Math.max(1, area.h);
  const wx = from ? (cx - ((from.x + from.w / 2) * vp.zoom + vp.x)) / Math.max(1, area.w) : sx;
  const wy = from ? (cy - ((from.y + from.h / 2) * vp.zoom + vp.y)) / Math.max(1, area.h) : sy;
  const ax = Math.abs(wx);
  const ay = Math.abs(wy);
  const major = Math.max(ax, ay);
  const minor = Math.min(ax, ay);
  // A diagonal only when the card is also well off on the other axis, not a little to one side.
  const diagonal = minor >= 0.5 && minor >= major * 0.4;
  let compass: Compass;
  if (diagonal) compass = wy >= 0 ? (wx >= 0 ? 1 : 3) : wx >= 0 ? 7 : 5;
  else if (ay >= ax) compass = wy >= 0 ? 2 : 6;
  else compass = wx >= 0 ? 0 : 4;
  return { compass, words: WAY_WORDS[compass], screens: Math.max(Math.abs(sx), Math.abs(sy)) };
}

/** One end of a connection, as the canvas shows it at the current viewport. */
export interface FarEnd {
  /** The authored step, and the card drawn for it (a folded group stands for the steps inside it). */
  id: string;
  drawnId: string;
  /**
   * The card is whole on the canvas and clear of the phase index. For a card too large for the
   * canvas at reading size (`portStretch`): the place the connection's line meets it is.
   */
  inView: boolean;
  /** Some of the card is on the canvas, whole or cut by its edge. */
  onCanvas: boolean;
  /**
   * Some of the card is in sight: it is on the canvas and does not lie wholly under the phase
   * index, which hides what it covers.
   */
  seen: boolean;
  /**
   * Which way and how far it (for a card too large for the canvas, that place) lies from the
   * middle of the canvas. The way of a card that is partly in sight is taken from the other card
   * when that one is on the canvas too (`FarView.ends`).
   */
  way: FarWay;
  /**
   * The card is too large for the canvas at reading size, so `inView` is the place the line meets
   * it and not the card: the walk bar then speaks of the line being in view, not of the card.
   */
  byLine: boolean;
  /** The card is an open group too large for the canvas: the walk bar speaks of the line's end at it. */
  port: boolean;
}

/** Both ends of a connection, and which one the walk is keeping in view (null: neither). */
export interface FarEnds {
  source: FarEnd;
  target: FarEnd;
  keep: End | null;
  /**
   * The two cards fit the canvas together at the zoom on screen (`fitsCanvas`, no margin), as do
   * those of every connection a walk step shows with both cards. Such a connection is not a far
   * one: an end of it that is out of view is a card the reader moved off the canvas, or one the
   * step could not clear of the phase index (`FarView.afterReveal`). A card too large for the
   * canvas counts by the place the line meets it (`portStretch`), as it does for `inView`.
   */
  fits: boolean;
  /**
   * Some pan shows both cards whole and clear of the phase index at the zoom on screen. A look at
   * either end then shows the two together, and the view holds neither (`FarView.look`). Never so
   * while an end is too large for the canvas.
   */
  together: boolean;
  /**
   * A stretch of the connection's line is off the canvas or under the phase index (`lineInView`).
   * Where both ends are in view by the place the line meets them, the bar then speaks of the
   * line's two ends and not of the line from end to end (`farIdleText`).
   */
  lineCut: boolean;
}

/**
 * One end of a connection: `id` the authored step, `card` the box drawn for it, `points` the
 * connection's line in world coordinates (source first), or null when it is not drawn.
 */
export function farEnd(end: End, id: string, card: Rect & { id: string; headerH?: number }, points: readonly XY[] | null, vp: Viewport, area: Area, covered: Rect | null): FarEnd {
  const stretch = portStretch(points, end, card, vp.zoom, area);
  const x = card.x * vp.zoom + vp.x;
  const y = card.y * vp.zoom + vp.y;
  const right = x + card.w * vp.zoom;
  const foot = y + card.h * vp.zoom;
  const onCanvas = x < area.w && right > 0 && y < area.h && foot > 0;
  // The whole card lies under the phase index, half a pixel of rounding allowed.
  const eps = 0.5;
  const under = !!covered && x >= covered.x - eps && y >= covered.y - eps && right <= covered.x + covered.w + eps && foot <= covered.y + covered.h + eps;
  return {
    id,
    drawnId: card.id,
    inView: inView(stretch || card, vp, area, covered),
    onCanvas,
    seen: onCanvas && !under,
    way: farWay(portBox(points, end, card, vp.zoom, area) || card, vp, area),
    byLine: !!stretch,
    // On a canvas shorter than a card a step's card is too large as well: it is no group.
    port: !!stretch && !!card.headerH,
  };
}

/** One end of the connection, or both, is out of view (`FarEnd.inView`). */
export function isFar(ends: FarEnds): boolean {
  return !(ends.source.inView && ends.target.inView);
}

/**
 * The end the walk bar's line and key o go to: the one out of view; null when both are in view.
 * With both out of view it is the source, unless the walk has not been to the far end and some of
 * the source card is still on the canvas: a reader who dragged the picture a little, or began to
 * follow the line, still goes to the far card. Whether the source is then the way back ("Back to")
 * or a card to go to is `FarLine.back`.
 */
export function farGoal(ends: FarEnds): End | null {
  if (ends.source.inView) return ends.target.inView ? null : 'target';
  if (ends.target.inView) return 'source';
  return ends.keep !== 'target' && ends.source.onCanvas ? 'target' : 'source';
}

/**
 * The reader is at end `end` of a far connection, with the other end somewhere else: the view
 * holds that end (a step kept the source, a look went to the far end), or the two cards do not
 * fit the canvas together and the other card has left it. Two cards that fit are not far apart,
 * and a card that a few pixels of pan or a notch of zoom cut off at the canvas's edge has not
 * gone anywhere: there the reader is at an end only while the view holds it.
 */
export function atEnd(ends: FarEnds, end: End): boolean {
  const other = ends[end === 'source' ? 'target' : 'source'];
  return ends.keep === end || (!ends.fits && !other.onCanvas);
}

/* ── where the cap sits ──────────────────────────────────────────────────────────────────── */

/**
 * The cap's drawn size along and across its line (it lies along the line, so 22 x 14 px on a
 * horizontal stretch and 14 x 22 px on a vertical one), and the room it keeps from the canvas's
 * edge, the phase index and a card.
 */
export const CAP_LONG = 22;
export const CAP_SHORT = 14;
export const CAP_EDGE = 2;
export const CAP_GAP = 6;
export const CAP_CARD_GAP = 1;

/** A place on a line: a point in canvas pixels, and whether the line runs up or down there. */
export interface CapAt extends XY {
  vertical: boolean;
}

/** The stretches of a line in sight on the way to one end, in order, sampled a pixel apart. */
interface Sight {
  runs: CapAt[][];
  /** The phase index's corner of the canvas, or null. */
  corner: Rect | null;
}

/**
 * `points` is the line in world coordinates, source first; `toward` names the end the walk runs
 * to. A stretch is IN SIGHT when it is on the canvas, not behind a card (`cards`, in canvas pixels:
 * the connections are drawn under the cards) and not in the phase index's corner: `covered`, the
 * index, together with the strips between it and the canvas's right and bottom edges, where a line
 * runs on for a few pixels beside the index and says nothing. Null when that end of the line is
 * itself in sight.
 */
function sight(points: readonly XY[], vp: Viewport, area: Area, covered: Rect | null, toward: End, cards: readonly Rect[]): Sight | null {
  if (points.length < 2) return null;
  const pts = (toward === 'target' ? points : points.slice().reverse()).map((p) => ({ x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y }));
  const canvas: Rect = { x: 0, y: 0, w: area.w, h: area.h };
  const corner: Rect | null = covered ? { x: covered.x, y: covered.y, w: Math.max(covered.w, area.w - covered.x), h: Math.max(covered.h, area.h - covered.y) } : null;
  // A port lies on its card's border: a pixel inside the border still counts as in sight.
  const under = cards.map((c) => grow(c, -1.5, -1.5));
  const inSight = (p: XY): boolean => inRect(p, canvas) && !(corner && inRect(p, corner)) && !under.some((c) => inRect(p, c));
  if (inSight(pts[pts.length - 1])) return null;
  const runs: CapAt[][] = [];
  let run: CapAt[] = [];
  const close = () => {
    if (run.length) runs.push(run);
    run = [];
  };
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    // A segment wholly beyond one side of the canvas holds nothing to find.
    if ((a.x < 0 && b.x < 0) || (a.x > area.w && b.x > area.w) || (a.y < 0 && b.y < 0) || (a.y > area.h && b.y > area.h)) {
      close();
      continue;
    }
    const vertical = Math.abs(b.y - a.y) > Math.abs(b.x - a.x);
    const length = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    const steps = Math.max(1, Math.min(8000, Math.ceil(length)));
    for (let k = 0; k <= steps; k++) {
      const p = { x: a.x + ((b.x - a.x) * k) / steps, y: a.y + ((b.y - a.y) * k) / steps, vertical };
      if (inSight(p)) run.push(p);
      else close();
    }
  }
  close();
  return { runs, corner };
}

/**
 * Where a line goes out of sight for good on its way to one of its ends, in canvas pixels: the
 * end of its last stretch in sight (see `sight` for what is in sight). Null when that end of the
 * line is in sight, or none of the line is.
 */
export function lineExit(points: readonly XY[], vp: Viewport, area: Area, covered: Rect | null, toward: End, cards: readonly Rect[] = []): CapAt | null {
  const seen = sight(points, vp, area, covered, toward, cards);
  if (!seen || !seen.runs.length) return null;
  const last = seen.runs[seen.runs.length - 1];
  return last[last.length - 1];
}

/**
 * Where the cap of a line sits, in canvas pixels (its centre), or null when that end of the line
 * is in sight or none of the line is.
 *
 * The cap marks the end of the LAST stretch in sight on the way to that end (`lineExit`): the
 * place nearest that stretch's end where a whole cap fits, inside the canvas by CAP_EDGE, off the
 * phase index's corner by CAP_GAP and off every card. So:
 *
 * - a line that leaves through a canvas edge is capped just inside that edge;
 * - one that runs behind the phase index, or along the canvas's foot under it, is capped before it;
 * - one that passes behind a neighbouring card on its way out is capped before that card;
 * - one that leaves, comes back and leaves again is capped where it leaves for good.
 *
 * Where no whole cap fits near that stretch's end (a line that runs out along the canvas's very
 * edge) the cap goes at the end, moved the least distance inside the canvas. When that would put
 * it on a card (a stub of line between a card and the canvas's edge), it goes further back: on
 * that stretch, else on the stretch in sight before it; last, at the stretch's middle. A cap is
 * never drawn over a card: where the only room for one is on a card (a few pixels of line in the
 * gap between two cards, or between a card and the phase index) the line has no cap.
 */
export function capPoint(points: readonly XY[], vp: Viewport, area: Area, covered: Rect | null, toward: End, cards: readonly Rect[] = []): CapAt | null {
  const seen = sight(points, vp, area, covered, toward, cards);
  if (!seen || !seen.runs.length) return null;
  const { runs, corner } = seen;
  // The half sizes of a cap lying along a horizontal or a vertical stretch.
  const half = (vertical: boolean) => (vertical ? { x: CAP_SHORT / 2, y: CAP_LONG / 2 } : { x: CAP_LONG / 2, y: CAP_SHORT / 2 });
  const room = (h: XY): Rect => ({ x: h.x + CAP_EDGE, y: h.y + CAP_EDGE, w: area.w - 2 * (h.x + CAP_EDGE), h: area.h - 2 * (h.y + CAP_EDGE) });
  const clear = (p: CapAt): boolean => {
    const h = half(p.vertical);
    return inRect(p, room(h)) && !(corner && inRect(p, grow(corner, h.x + CAP_GAP, h.y + CAP_GAP)));
  };
  const offCards = (p: CapAt, gap: number): boolean => {
    const h = half(p.vertical);
    return !cards.some((c) => inRect(p, grow(c, h.x + gap, h.y + gap)));
  };
  const fits = (p: CapAt): boolean => clear(p) && offCards(p, CAP_CARD_GAP);
  const last = runs[runs.length - 1];
  // Within NEAR pixels of the last stretch's end, a place on the line itself.
  const NEAR = 48;
  const from = Math.max(0, last.length - 1 - NEAR);
  for (let k = last.length - 1; k >= from; k--) if (fits(last[k])) return last[k];
  // Else the end itself, moved the least distance inside the canvas and off the index's corner.
  const into = (p: CapAt): CapAt => {
    const h = half(p.vertical);
    const r = room(h);
    const q = { x: Math.min(Math.max(p.x, r.x), r.x + r.w), y: Math.min(Math.max(p.y, r.y), r.y + r.h), vertical: p.vertical };
    const blocked = corner ? grow(corner, h.x + CAP_GAP, h.y + CAP_GAP) : null;
    if (blocked && inRect(q, blocked)) {
      // To the corner's left along a line that runs under it, else above it.
      if (blocked.x - 1 >= r.x && Math.abs(q.x - blocked.x) <= Math.abs(q.y - blocked.y)) q.x = blocked.x - 1;
      else if (blocked.y - 1 >= r.y) q.y = blocked.y - 1;
      else if (blocked.x - 1 >= r.x) q.x = blocked.x - 1;
    }
    return q;
  };
  const end = into(last[last.length - 1]);
  if (clear(end) && offCards(end, -0.5)) return end;
  // Else further back: on this stretch, then on the stretches before it.
  for (let k = from - 1; k >= 0; k--) if (fits(last[k])) return last[k];
  for (let r = runs.length - 2; r >= 0; r--) for (let k = runs[r].length - 1; k >= 0; k--) if (fits(runs[r][k])) return runs[r][k];
  const mid = into(last[Math.floor(last.length / 2)]);
  return clear(mid) && offCards(mid, -0.5) ? mid : null;
}

/* ── how far, in steps and in screens ────────────────────────────────────────────────────── */

/**
 * Each drawn card's place in reading order, counted in STEPS (the same visit as `claimOrder` in
 * `walk.ts`: the lanes in phase order, a group before what it contains, depth first). A group
 * holds no place of its own: it has the place of the first step inside it. The walk bar's line
 * says how far a connection's other end is as the difference of two places ("12 steps later"),
 * which does not change as the reader pans or zooms. It is not the number of `j` presses: the
 * walk also stops on connections and findings.
 */
export function stepRanks(index: GraphIndex): Map<string, number> {
  const ranks = new Map<string, number>();
  let n = 0;
  const visit = (id: string): void => {
    if (ranks.has(id) || !index.nodeById.has(id)) return;
    ranks.set(id, index.isGroup(id) ? n : n++);
    for (const child of index.laneChildren(id)) visit(child);
  };
  for (const lane of index.lanes) for (const root of index.roots(lane.id)) visit(root);
  for (const node of index.graph.nodes || []) visit(node.id);
  return ranks;
}

/** "12 steps later", "next step", "3 steps earlier"; '' for no difference. */
export function stepsText(delta: number): string {
  if (!delta) return '';
  if (delta === 1) return 'next step';
  if (delta === -1) return 'previous step';
  return Math.abs(delta) + ' steps ' + (delta > 0 ? 'later' : 'earlier');
}

/** "0.6 screens", "1 screen", "3.3 screens", "11 screens". */
export function screensText(screens: number): string {
  const n = screens >= 9.95 ? Math.round(screens) : Math.round(screens * 10) / 10;
  return (n >= 9.95 ? String(n) : n.toFixed(1).replace(/\.0$/, '')) + (n === 1 ? ' screen' : ' screens');
}

/* ── what the walk bar's line says ───────────────────────────────────────────────────────── */

/** What the walk bar's line says of a far connection. Everything is authored text or geometry; nothing is a verdict. */
export interface FarLine {
  /** The end the line goes to: the far card, or the source (back to it, while the reader looks at the far end). */
  end: End;
  /**
   * The line is the way back to the source: the reader is at the far end (`atEnd`). That is after
   * a look has taken the view there, and on two cards that do not fit the canvas together also
   * once the source card has left the canvas. Until then a source that is out of view is a card
   * the reader moved or zoomed off the canvas's edge, and the line goes to it as it goes to any
   * card ("Go to").
   */
  back: boolean;
  /**
   * Pressing the line shows this card together with the other one (`FarEnds.together`): there is
   * then no way back to speak of.
   */
  together?: boolean;
  /**
   * Some of this card is in sight (`FarEnd.seen`: the canvas's edge cuts the card, or the phase
   * index covers part of it): the line says "partly in view" on that side, not "off screen", and
   * gives no distance in screens to a card that is on the screen. A card wholly under the phase
   * index is off screen.
   */
  partly?: boolean;
  /** That card's authored title. */
  title: string;
  /**
   * The folded group drawn in its place, when its own card is not drawn (the reader folded it
   * after the step; a step opens the groups around both ends). The line then names the card the
   * reader will find, "Go to folded group <group>", and says which step it holds.
   */
  folded?: string;
  /**
   * That end is an open group too large for the canvas: the line goes to the place the
   * connection's line meets the group's border, and says so ("Go to its end at …"), since the
   * group's title may well be on the canvas already.
   */
  port?: boolean;
  /** Which way it lies (`FarEnd.way`), as a compass point and in words, and how far in screens. */
  compass: Compass;
  way: string;
  screens: string;
  /** How far in reading order (`stepsText`), the distance the line prints; '' when unknown (the line then prints the screens). */
  steps: string;
  /**
   * The view is at the far end (the far card in view, the source not, and the line the way back):
   * the walk's place says so.
   */
  atFar: boolean;
  /** Its phase, when that is another phase than the one of the end in view. */
  phase?: { n: number; label: string };
  /** The connection's basis when it is not observed. */
  basis?: string;
  /**
   * The basis its line is drawn with when that is not observed, for the line's own copy of the
   * cap. It is `basis`, except on a line that also carries a less certain connection (`DrawnLine`).
   */
  drawnBasis?: string;
  /** The lit line's phase tone and severity, and whether it is drawn in them now, for that copy. */
  tone?: string | null;
  severity?: string | null;
  lit?: boolean;
}

/**
 * How a connection's line is drawn, which its cap copies. The colour: the source card's phase
 * tone, or its finding's severity, once the line is `lit` in them; until then a selected line is
 * the accent, and a finding's its severity. The `basis`: dashed for inferred, dotted for
 * unresolved. One line can carry several connections between the same two cards and is then drawn
 * with the least certain basis among them (`routeBasis`), so an observed connection can run on a
 * dashed line.
 */
export interface DrawnLine {
  tone: string | null;
  severity: string | null;
  lit: boolean;
  basis: string | null;
}

/** A step's authored title. */
export function stepTitle(index: GraphIndex, id: string): string {
  const node = index.nodeById.get(id);
  return node ? node.label || node.id : id;
}

/**
 * The walk bar's line for connection `edgeId` whose ends the canvas shows as `ends`, or null when
 * both are in view. `ranks` is `stepRanks(index)`; `drawn` is how the connection's line is drawn.
 */
export function farLine(index: GraphIndex, edgeId: string, ends: FarEnds, ranks: ReadonlyMap<string, number>, drawn: DrawnLine): FarLine | null {
  const end = farGoal(ends);
  if (!end) return null;
  const far = ends[end];
  const near = ends[end === 'source' ? 'target' : 'source'];
  const phaseOf = (id: string): { n: number; label: string } | null => {
    const node = index.nodeById.get(id);
    const lane = node ? index.lanes.find((l) => l.id === node.stage) : undefined;
    return node && lane ? { n: index.phaseIndexOf(node.stage) + 1, label: lane.label || lane.id } : null;
  };
  const farPhase = phaseOf(far.id);
  const nearPhase = phaseOf(near.id);
  const edge = index.edgeById.get(edgeId);
  const a = ranks.get(near.id);
  const b = ranks.get(far.id);
  const back = end === 'source' && atEnd(ends, 'target');
  const line: FarLine = {
    end,
    back,
    title: stepTitle(index, far.id),
    compass: far.way.compass,
    way: far.way.words,
    screens: screensText(far.way.screens),
    steps: a === undefined || b === undefined ? '' : stepsText(b - a),
    atFar: back && ends.target.inView,
    tone: drawn.tone,
    severity: drawn.severity,
    lit: drawn.lit,
  };
  if (far.drawnId !== far.id) line.folded = stepTitle(index, far.drawnId);
  if (far.port) line.port = true;
  else if (far.seen) line.partly = true;
  if (ends.together) line.together = true;
  if (farPhase && (!nearPhase || nearPhase.n !== farPhase.n)) line.phase = farPhase;
  if (edge && isUncertain(edge.basis)) line.basis = edge.basis;
  if (isUncertain(drawn.basis)) line.drawnBasis = drawn.basis as string;
  return line;
}

/** The words the line prints, left to right; an empty part is not drawn. */
export interface FarLineText {
  /** The basis tag of a connection that is not observed, as a card's tag prints it. */
  tag: string;
  verb: string;
  title: string;
  distance: string;
  phase: string;
}

export function farLineText(line: FarLine): FarLineText {
  const going = line.end === 'target';
  const verb = line.port ? (going ? 'Go to its end at' : line.back ? 'Back to its start at' : 'Go to its start at') : line.back ? 'Back to' : 'Go to';
  return {
    tag: line.basis === 'unresolved' ? '? unresolved' : isUncertain(line.basis) ? 'inferred' : '',
    verb: line.folded ? verb + ' folded group' : verb,
    title: line.folded || line.title,
    distance: line.steps || line.screens,
    phase: line.phase ? 'phase ' + line.phase.n : '',
  };
}

/**
 * The line's accessible name: what it prints, in order, with what the picture says beside it put
 * in words (which end, which side of the screen, the phase's name). A card that is partly in sight
 * (`FarLine.partly`) is "partly in view" on that side, not "off screen". The number of screens,
 * which changes with every pan, is not in the name.
 */
export function farLineName(line: FarLine): string {
  const going = line.end === 'target';
  const text = farLineText(line);
  const what = line.folded
    ? text.verb + ' ' + text.title + (going ? ', which holds the far end, ' : ', which holds the source, ') + line.title
    : text.verb + (line.port ? ' the group ' : going ? ' the far end: ' : ' the source: ') + text.title;
  return (text.tag ? text.tag + ' connection. ' : '') + what + ', ' + text.distance + (line.partly ? ', partly in view ' : ', off screen ') + SIDE_WORDS[line.compass] +
    (line.phase ? ', in ' + text.phase + ', ' + line.phase.label : '');
}

/**
 * The line's accessible description: only what its name leaves out, the distance in screens (of a
 * card that is off the screen) and how the line is used. The card's title and its phase are in
 * the name already.
 */
export function farLineDescription(line: FarLine): string {
  return (line.partly ? '' : 'About ' + line.screens + ' ' + line.way + '. ') + (line.end === 'target' && !line.together
    ? 'Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.'
    : line.back
      ? 'Click, Enter or key o goes back. The walk stays on this claim.'
      : 'Click, Enter or key o goes there. The walk stays on this claim.');
}

/** The line's tooltip: what the line cuts or leaves out (the whole title, the phase's name, the screens), and how it is used. */
export function farLineTitle(line: FarLine): string {
  const what = (isUncertain(line.basis) ? (line.basis === 'unresolved' ? 'Unresolved' : 'Inferred') + ' connection. ' : '') +
    line.title + (line.folded ? ' (inside the folded group ' + line.folded + ', which stays folded)' : '') + '.' +
    (line.phase ? ' Phase ' + line.phase.n + ', ' + line.phase.label + '.' : '');
  return what + ' ' + farLineDescription(line);
}

/** A cap's tooltip: `title` is the card the line continues to, `way` where that card lies. */
export function capTitle(title: string, way: FarWay): string {
  return 'This connection continues to ' + title + ', ' + screensText(way.screens) + ' ' + way.words + '. Click, or key o, to go there.';
}

/**
 * What the line's place in the bar says on a connection with no far line: both cards are on the
 * canvas. An end too large for the canvas (an open group; any card on a canvas shorter than one)
 * is in view by the place the line meets it, so the bar then speaks of the line and not of the
 * cards, which may both be cut off: of the line from end to end while all of it is on the canvas,
 * of its two ends once a stretch between them is not (`FarEnds.lineCut`). '' while an end is out
 * of view.
 */
export function farIdleText(ends: FarEnds): string {
  if (isFar(ends)) return '';
  if (!(ends.source.byLine || ends.target.byLine)) return 'Both ends in view';
  return ends.lineCut ? 'Both ends of the line in view' : 'Line in view end to end';
}

/* ── what the live region says ───────────────────────────────────────────────────────────── */

/**
 * What the walk's announcement adds on a far connection. The walk's sentence has just named both
 * ends, so this says only where the far one is, and the key. Of a card that is partly in sight
 * it says so, and on which side.
 */
export function farAnnouncement(line: FarLine): string {
  const where = (line.steps ? line.steps + ', ' : '') + (line.phase ? 'in phase ' + line.phase.n + ', ' + line.phase.label + ', ' : '') +
    (line.partly ? SIDE_WORDS[line.compass] : 'about ' + line.screens + ' ' + line.way);
  const folded = line.folded ? ', inside ' + line.folded + ', which is folded' : '';
  const seen = line.partly ? ' is partly in view, ' : ' is out of view, ';
  return line.end === 'target'
    ? 'Its far end' + seen + where + folded + (line.together ? '. o goes there.' : '. o goes there and back.')
    : 'Its source' + seen + where + folded + (line.back ? '. o goes back.' : '. o goes there.');
}

/**
 * Said after the view went to end `to` of connection `edgeId`. An inferred or unresolved
 * connection is called that at its far end too, and a group the reader folded stays folded: the
 * card they arrive at is the group's.
 */
export function lookAnnouncement(index: GraphIndex, edgeId: string, ends: FarEnds, to: End): string {
  const here = stepTitle(index, ends[to].id);
  const other = stepTitle(index, ends[to === 'target' ? 'source' : 'target'].id);
  const edge = index.edgeById.get(edgeId);
  const basis = edge && isUncertain(edge.basis) ? edge.basis + ' ' : '';
  const inside = ends[to].drawnId !== ends[to].id ? ', inside the folded group ' + stepTitle(index, ends[to].drawnId) : '';
  return to === 'target'
    ? 'Far end of this ' + basis + 'connection: ' + here + inside + '. o goes back to ' + other + '.'
    : 'Back at the source of this ' + basis + 'connection: ' + here + inside + '.';
}

/** Key o on a connection whose two ends are in view: of the cards, or of the line (`farIdleText`). */
export const BOTH_ENDS_IN_VIEW = 'Both ends of this connection are in view.';
export const LINE_IN_VIEW = 'The line of this connection is in view end to end.';
export const LINE_ENDS_IN_VIEW = 'Both ends of the line of this connection are in view.';
export function inViewAnnouncement(ends: FarEnds): string {
  if (!(ends.source.byLine || ends.target.byLine)) return BOTH_ENDS_IN_VIEW;
  return ends.lineCut ? LINE_ENDS_IN_VIEW : LINE_IN_VIEW;
}

/**
 * What an arrow towards an end in view says when it moves nothing (`WalkFar.arrow`): which end
 * that card is.
 */
export function atEndAnnouncement(end: End): string {
  return end === 'source' ? 'This is where the connection starts.' : 'This is the far end of the connection.';
}
