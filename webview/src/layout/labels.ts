/**
 * Lane-seam-aware edge-label placement (VIEW-03).
 *
 * `render/edges.ts` used to draw every label at `{x: r.mid.x, y: r.mid.y - 8}`
 * with no collision logic and no lane awareness. Since ~70 % of edges cross a
 * lane, the geometric midpoint of a route IS the lane seam: the flagship demo
 * printed `X_train_pca` twice on the preprocess / model boundary, struck
 * `logits` through with the lane rule, stacked `X_scaled` / `X_test` /
 * `X_train` in the 20 px gutter, and put six labels on top of node cards.
 *
 * The fix is three passes over pure geometry, in this order:
 *
 *   1. ANCHOR. Every axis-aligned run of the route is clipped to each lane's
 *      SAFE BAND — the band inset by `LANE_PAD` from both of that lane's
 *      boundaries — and the longest surviving run wins (horizontal preferred,
 *      because horizontal text reads along a horizontal cable). A cross-lane
 *      route has no horizontal run inside a lane at all: its horizontal leg is
 *      the gutter leg, which is exactly the seam, so it anchors to the vertical
 *      leg inside the source or target band instead. When nothing survives, the
 *      OUTLET-ADJACENT segment (the first leg, leaving the source card) is used
 *      and the placement is marked `fallback`.
 *   2. DECLUTTER. One greedy pass in DOCUMENT ORDER over the labels that are
 *      visible without hovering. Each label takes the first of at most
 *      `MAX_DECLUTTER_TRIES` candidate positions — pushed along its own run,
 *      then flipped across the stroke — that sits inside a lane band, clears
 *      every node card and clears every label already placed. If the cap is
 *      reached the label is HIDDEN rather than drawn over something.
 *   3. NUDGE. The severity marker is walked along the polyline until its disc
 *      clears the label box, so the two stop being centred on the same point.
 *
 * Everything here is a pure function of (frame, routes): no DOM, no text
 * measurement, no randomness, and every collection is walked in the order the
 * document produced it. That is what keeps the parity and golden-render gates
 * from going flaky — the one hard requirement VIEW-03 names.
 */

import { CORNER_R, LANE_PAD } from './constants.js';
import type { LayoutFrame, LayoutLane } from './layout.js';
import type { Point, RoutedEdge } from './routing.js';

/** Advance width of one character of the 10 px monospace label face. */
export const LABEL_CHAR_W = 6.02;
/**
 * The height of the box a label really occupies, MEASURED in Chromium.
 *
 * A 10 px `--mlv-font-mono` label with the `paint-order: stroke` halo reports a
 * 13.68 px client rect, not the 12 px a naive font-size model assumes; and
 * `dominant-baseline: middle` puts that box about 1.05 px ABOVE the declared
 * `y`. Modelling the box 2 px short put two labels 2 px over a lane boundary on
 * the flagship report while every in-process assertion passed — the model has to
 * be at least as big as the ink, or the LANE_PAD rule is enforced against a box
 * nobody draws.
 */
export const LABEL_H = 14;
/** How far above the declared `y` the rendered box sits (measured, Chromium). */
export const LABEL_RISE = 1;
/** The halo `paint-order: stroke` paints around the glyphs, per side. */
export const LABEL_PAD_X = 4;
/** Distance from the stroke to the label's centre line. */
export const LABEL_GAP = 8;
/** Slack added to every collision test, so two boxes never merely kiss. */
export const LABEL_CLEAR = 2;
/**
 * Positions tried before a colliding label is hidden instead of overlapped.
 *
 * Ten per run — on the spot, pushed two thirds of the way to each end, pushed
 * all the way to each end, and each of those five flipped across the stroke —
 * over the longest in-band runs of the route in turn. The far ends matter: a
 * back-edge's loop label only clears the cards it runs beside at the very
 * bottom of its drop. It is a CONSTANT, not a budget that grows with the crowd:
 * a cap that moves is a cap a document can make non-deterministic.
 */
export const MAX_DECLUTTER_TRIES = 20;
/** Positions offered on any ONE run, before the pass moves to the next one. */
export const TRIES_PER_RUN = 10;
/** How many of the route's own runs the pass will consider, longest first. */
export const RUNS_PER_LABEL = 3;
/** A run shorter than this cannot carry a label legibly. */
export const MIN_RUN = 14;
/** Horizontal text on a vertical cable is legible but second choice. */
export const VERTICAL_BIAS = 0.7;
/** Half the severity disc drawn at the route midpoint (`edgeMarker(_, 14)`). */
export const MARKER_R = 7;
/** Bucket size for the collision grid — a few label widths. */
export const GRID = 96;

export const LABEL_METRICS = {
  LABEL_CHAR_W,
  LABEL_H,
  LABEL_RISE,
  LABEL_PAD_X,
  LABEL_GAP,
  LABEL_CLEAR,
  MAX_DECLUTTER_TRIES,
  TRIES_PER_RUN,
  RUNS_PER_LABEL,
  MIN_RUN,
  MARKER_R,
  LANE_PAD,
};

export interface LabelRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LabelPlacement {
  /** The route this label belongs to. */
  id: string;
  /** Exactly the string the renderer draws, back-edge glyph included. */
  text: string;
  /** Anchor point for a `text-anchor: middle; dominant-baseline: middle` node. */
  x: number;
  y: number;
  rect: LabelRect;
  /** True when no legal position existed: the label is not drawn at all. */
  hidden: boolean;
  /** True when the label sits on the other side of its stroke. */
  flipped: boolean;
  axis: 'h' | 'v';
  /** The lane band the label was placed inside, or null when hidden. */
  laneId: string | null;
  /** True when no run survived the lane clip and the outlet leg was used. */
  fallback: boolean;
  /** How far the declutter pass pushed it along its own run, in px. */
  shifted: number;
  /** Where the severity marker goes once nudged off the label box. */
  marker: Point;
  /** True when this label is drawn without hovering at LOD `full`. */
  always: boolean;
}

export interface LabelStats {
  /** Routes carrying a label at all. */
  labels: number;
  /** Of those, the ones drawn without hovering. */
  always: number;
  placed: number;
  hidden: number;
  flipped: number;
  shifted: number;
  fallback: number;
  /** Severity markers moved off a label box. */
  nudged: number;
}

export interface LabelPlan {
  placements: Map<string, LabelPlacement>;
  stats: LabelStats;
}

/** Exactly what `buildEdge` writes into the <text> node. */
export function labelTextOf(route: { label: string; back: boolean }): string {
  if (!route.label) return '';
  return route.back ? '\u21bb ' + route.label : route.label;
}

export function labelWidth(text: string): number {
  return round(text.length * LABEL_CHAR_W + 2 * LABEL_PAD_X);
}

/**
 * Whether this label is on screen without a pointer on it.
 *
 * It mirrors `styles/edge.css` exactly: back-edges and merged routes carry
 * `has-label` / `--merged` at every zoom, and data and control labels are simply
 * on at LOD `full` (>= 0.62). Only these participate in the declutter pass and
 * only these can be hidden by it — a call or config label appears one at a time
 * under the pointer, where it cannot collide with a sibling that is not drawn.
 */
export function alwaysVisible(route: { kind: string; back: boolean; count: number }): boolean {
  return route.back || route.count > 1 || route.kind === 'data' || route.kind === 'control';
}

/* ── rectangles ─────────────────────────────────────────────────────────── */

function overlaps(a: LabelRect, b: LabelRect, pad: number): boolean {
  return (
    a.x - pad < b.x + b.w &&
    a.x + a.w + pad > b.x &&
    a.y - pad < b.y + b.h &&
    a.y + a.h + pad > b.y
  );
}

/** A coarse uniform grid, so a label tests a handful of rects instead of all. */
class RectGrid {
  private cells = new Map<string, LabelRect[]>();

  add(rect: LabelRect): void {
    const x0 = Math.floor(rect.x / GRID);
    const x1 = Math.floor((rect.x + rect.w) / GRID);
    const y0 = Math.floor(rect.y / GRID);
    const y1 = Math.floor((rect.y + rect.h) / GRID);
    for (let gx = x0; gx <= x1; gx++) {
      for (let gy = y0; gy <= y1; gy++) {
        const key = gx + ':' + gy;
        const bucket = this.cells.get(key);
        if (bucket) bucket.push(rect);
        else this.cells.set(key, [rect]);
      }
    }
  }

  hits(rect: LabelRect, pad: number): boolean {
    const x0 = Math.floor((rect.x - pad) / GRID);
    const x1 = Math.floor((rect.x + rect.w + pad) / GRID);
    const y0 = Math.floor((rect.y - pad) / GRID);
    const y1 = Math.floor((rect.y + rect.h + pad) / GRID);
    for (let gx = x0; gx <= x1; gx++) {
      for (let gy = y0; gy <= y1; gy++) {
        const bucket = this.cells.get(gx + ':' + gy);
        if (!bucket) continue;
        for (const other of bucket) {
          if (overlaps(rect, other, pad)) return true;
        }
      }
    }
    return false;
  }
}

/**
 * Every rectangle a label must stay off: node cards, collapsed groups and the
 * TITLE STRIP of an expanded group. An expanded group's interior is not an
 * obstacle — it is background that its own children are drawn on, and the
 * children are in this list.
 */
function cardRects(frame: LayoutFrame): LabelRect[] {
  const out: LabelRect[] = [];
  for (const box of frame.boxes.values()) {
    if (!box.isGroup || box.collapsed) {
      out.push({ x: box.x, y: box.y, w: box.w, h: box.h });
      continue;
    }
    out.push({ x: box.x, y: box.y, w: box.w, h: Math.max(box.headerH, 1) });
  }
  return out;
}

/* ── lane bands ─────────────────────────────────────────────────────────── */

interface Band {
  id: string;
  top: number;
  bottom: number;
}

/**
 * A lane's safe band: its box inset by `LANE_PAD` at the top and the bottom.
 *
 * `layout.ts` builds a lane as `LANE_HEADER_H + contentH + LANE_PAD`, so this is
 * exactly the content rectangle — a label inside it is provably not on a seam,
 * and one outside it is either on the header, in the bottom padding or in the
 * `LANE_GUTTER` between two bands, which is where every one of the measured
 * failures sat.
 */
function bandsOf(lanes: LayoutLane[]): Band[] {
  const out: Band[] = [];
  for (const lane of lanes) {
    const top = lane.y + LANE_PAD;
    const bottom = lane.y + lane.h - LANE_PAD;
    if (bottom - top < LABEL_H) continue;
    out.push({ id: lane.id, top, bottom });
  }
  return out;
}

/** The band that fully contains this rect, or null — the LANE_PAD rule itself. */
function bandFor(bands: Band[], rect: LabelRect): Band | null {
  for (const band of bands) {
    if (rect.y >= band.top && rect.y + rect.h <= band.bottom) return band;
  }
  return null;
}

/* ── runs ───────────────────────────────────────────────────────────────── */

interface Run {
  axis: 'h' | 'v';
  /** The run's fixed coordinate: y for a horizontal run, x for a vertical one. */
  at: number;
  /** The run's extent along its own axis, ascending. */
  a: number;
  b: number;
  laneId: string;
  score: number;
  order: number;
}

/**
 * Every axis-aligned run of the route, clipped to the lane bands it passes
 * through. The ends adjacent to an interior corner are trimmed by `CORNER_R`,
 * because `orthPath` rounds those corners and the straight stroke stops there.
 */
function runsOf(points: Point[], bands: Band[]): Run[] {
  const out: Run[] = [];
  for (let i = 1; i < points.length; i++) {
    const p0 = points[i - 1];
    const p1 = points[i];
    const startInset = i - 1 > 0 ? CORNER_R : 0;
    const endInset = i < points.length - 1 ? CORNER_R : 0;
    const dx = Math.abs(p1.x - p0.x);
    const dy = Math.abs(p1.y - p0.y);
    if (dy < 0.51 && dx > 0.51) {
      const forward = p1.x > p0.x;
      const a = Math.min(p0.x, p1.x) + (forward ? startInset : endInset);
      const b = Math.max(p0.x, p1.x) - (forward ? endInset : startInset);
      if (b - a < MIN_RUN) continue;
      const at = (p0.y + p1.y) / 2;
      for (const band of bands) {
        if (at < band.top || at > band.bottom) continue;
        out.push({ axis: 'h', at, a, b, laneId: band.id, score: b - a, order: i });
      }
    } else if (dx < 0.51 && dy > 0.51) {
      const forward = p1.y > p0.y;
      const a = Math.min(p0.y, p1.y) + (forward ? startInset : endInset);
      const b = Math.max(p0.y, p1.y) - (forward ? endInset : startInset);
      if (b - a < MIN_RUN) continue;
      const at = (p0.x + p1.x) / 2;
      for (const band of bands) {
        const lo = Math.max(a, band.top);
        const hi = Math.min(b, band.bottom);
        if (hi - lo < MIN_RUN) continue;
        out.push({ axis: 'v', at, a: lo, b: hi, laneId: band.id, score: (hi - lo) * VERTICAL_BIAS, order: i });
      }
    }
  }
  return out;
}

/** Longest first, ties broken by document order of the segment. */
function byLength(a: Run, b: Run): number {
  if (Math.abs(a.score - b.score) > 0.001) return b.score - a.score;
  return a.order - b.order;
}

/** The outlet-adjacent segment: the leg leaving the source card. */
function outletRun(points: Point[]): Run | null {
  if (points.length < 2) return null;
  const p0 = points[0];
  const p1 = points[1];
  const dx = Math.abs(p1.x - p0.x);
  const dy = Math.abs(p1.y - p0.y);
  if (dy < 0.51 && dx > 0.51) {
    return { axis: 'h', at: (p0.y + p1.y) / 2, a: Math.min(p0.x, p1.x), b: Math.max(p0.x, p1.x), laneId: '', score: dx, order: 1 };
  }
  if (dx < 0.51 && dy > 0.51) {
    return { axis: 'v', at: (p0.x + p1.x) / 2, a: Math.min(p0.y, p1.y), b: Math.max(p0.y, p1.y), laneId: '', score: dy, order: 1 };
  }
  return null;
}

/* ── candidate positions ────────────────────────────────────────────────── */

interface Position {
  x: number;
  y: number;
  rect: LabelRect;
  flipped: boolean;
  shift: number;
}

/**
 * At most `TRIES_PER_RUN` positions on one run, in the order the greedy pass
 * tries them: on the spot, flipped, then pushed along the run to either end,
 * each of those flipped in turn.
 */
function positionsFor(run: Run, width: number): Position[] {
  const half = width / 2;
  const alongHalf = run.axis === 'h' ? half : LABEL_H / 2;
  const mid = (run.a + run.b) / 2;
  const lo = run.a + alongHalf;
  const hi = run.b - alongHalf;
  const base = hi > lo ? clamp(mid, lo, hi) : mid;
  const span = hi > lo ? (hi - lo) / 2 : 0;
  const steps = [0, span * 0.6, -span * 0.6, span, -span];
  const out: Position[] = [];
  for (const step of steps) {
    if (out.length >= TRIES_PER_RUN) break;
    if (step !== 0 && Math.abs(step) < 1) continue;
    const along = base + step;
    for (const flipped of [false, true]) {
      if (out.length >= TRIES_PER_RUN) break;
      let x: number;
      let y: number;
      if (run.axis === 'h') {
        x = along;
        y = flipped ? run.at + LABEL_GAP : run.at - LABEL_GAP;
      } else {
        x = flipped ? run.at - LABEL_GAP - half : run.at + LABEL_GAP + half;
        y = along;
      }
      out.push({
        x: round(x),
        y: round(y),
        rect: { x: round(x - half), y: round(y - LABEL_RISE - LABEL_H / 2), w: width, h: LABEL_H },
        flipped,
        shift: Math.abs(round(step)),
      });
    }
  }
  return out;
}

/* ── the marker nudge ───────────────────────────────────────────────────── */

function markerRect(p: Point): LabelRect {
  return { x: p.x - MARKER_R, y: p.y - MARKER_R, w: MARKER_R * 2, h: MARKER_R * 2 };
}

function polyLength(points: Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  return total;
}

function pointAtLength(points: Point[], target: number): Point {
  let walked = 0;
  for (let i = 1; i < points.length; i++) {
    const seg = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    if (walked + seg >= target || i === points.length - 1) {
      const f = seg === 0 ? 0 : clamp((target - walked) / seg, 0, 1);
      return {
        x: round(points[i - 1].x + (points[i].x - points[i - 1].x) * f),
        y: round(points[i - 1].y + (points[i].y - points[i - 1].y) * f),
      };
    }
    walked += seg;
  }
  return points[points.length - 1];
}

/**
 * Walk the severity disc along the cable until it clears the label box. The
 * label keeps the anchor it earned; the marker is the thing that moves, because
 * a glyph anywhere on its own stroke still reads as belonging to that edge.
 */
function nudgeMarker(points: Point[], mid: Point, rect: LabelRect | null): { point: Point; moved: boolean } {
  if (!rect || !overlaps(markerRect(mid), rect, 1)) return { point: mid, moved: false };
  const total = polyLength(points);
  const half = total / 2;
  for (const delta of [18, -18, 30, -30, 44, -44]) {
    const at = clamp(half + delta, Math.min(8, total), Math.max(total - 8, 0));
    const candidate = pointAtLength(points, at);
    if (!overlaps(markerRect(candidate), rect, 1)) return { point: candidate, moved: true };
  }
  return { point: mid, moved: false };
}

/* ── the pass ───────────────────────────────────────────────────────────── */

export function planLabels(frame: LayoutFrame, routes: RoutedEdge[]): LabelPlan {
  const placements = new Map<string, LabelPlacement>();
  const stats: LabelStats = {
    labels: 0,
    always: 0,
    placed: 0,
    hidden: 0,
    flipped: 0,
    shifted: 0,
    fallback: 0,
    nudged: 0,
  };
  const bands = bandsOf(frame.lanes);
  const cards = new RectGrid();
  for (const rect of cardRects(frame)) cards.add(rect);
  const taken = new RectGrid();

  // Two ordered passes, both in DOCUMENT ORDER. The labels that are always on
  // screen claim their positions first and are the only ones that can be
  // hidden; a hover-only label then takes the best position left, and is drawn
  // whatever happens, because hiding a label that only exists under the pointer
  // would delete information rather than declutter anything.
  const tiers: RoutedEdge[][] = [[], []];
  for (const route of routes) {
    if (!route.label) continue;
    stats.labels++;
    const always = alwaysVisible(route);
    if (always) stats.always++;
    tiers[always ? 0 : 1].push(route);
  }

  for (let tier = 0; tier < tiers.length; tier++) {
    const always = tier === 0;
    for (const route of tiers[tier]) {
      const text = labelTextOf(route);
      const width = labelWidth(text);
      // The route's own runs, longest first, then the outlet-adjacent leg as the
      // documented fallback. Trying the SECOND-longest run before giving up is
      // still "along its own segment": a crowded document has many routes whose
      // best run is taken and whose next one is empty.
      const runs = runsOf(route.points, bands).sort(byLength).slice(0, RUNS_PER_LABEL);
      const outlet = outletRun(route.points);
      const attempts: { run: Run; fallback: boolean }[] = runs.map((run) => ({ run, fallback: false }));
      if (outlet) attempts.push({ run: outlet, fallback: true });

      let chosen: Position | null = null;
      let chosenRun: Run | null = null;
      let fallback = false;
      let band: Band | null = null;
      let firstInBand: Position | null = null;
      let firstInBandRun: Run | null = null;
      let firstInBandLane: Band | null = null;
      let tries = 0;
      for (const attempt of attempts) {
        if (chosen || tries >= MAX_DECLUTTER_TRIES) break;
        for (const position of positionsFor(attempt.run, width)) {
          if (tries >= MAX_DECLUTTER_TRIES) break;
          tries++;
          const inBand = bandFor(bands, position.rect);
          if (!inBand) continue;
          if (!firstInBand) {
            firstInBand = position;
            firstInBandRun = attempt.run;
            firstInBandLane = inBand;
          }
          if (cards.hits(position.rect, LABEL_CLEAR)) continue;
          if (taken.hits(position.rect, LABEL_CLEAR)) continue;
          chosen = position;
          chosenRun = attempt.run;
          fallback = attempt.fallback;
          band = inBand;
          break;
        }
      }
      // A hover-only label is never dropped: if every position collides it takes
      // the first one that is at least inside a lane band, which is the rule
      // that stops labels living on the seam.
      if (!chosen && !always && firstInBand) {
        chosen = firstInBand;
        chosenRun = firstInBandRun;
        band = firstInBandLane;
      }

      if (!chosen) {
        stats.hidden++;
        placements.set(route.id, {
          id: route.id,
          text,
          x: route.mid.x,
          y: route.mid.y,
          rect: { x: route.mid.x, y: route.mid.y, w: 0, h: 0 },
          hidden: true,
          flipped: false,
          axis: attempts.length ? attempts[0].run.axis : 'h',
          laneId: null,
          fallback,
          shifted: 0,
          marker: route.mid,
          always,
        });
        continue;
      }

      const nudge = nudgeMarker(route.points, route.mid, chosen.rect);
      if (nudge.moved) stats.nudged++;
      stats.placed++;
      if (chosen.flipped) stats.flipped++;
      if (chosen.shift > 0) stats.shifted++;
      if (fallback) stats.fallback++;
      // Every placed label claims its box, hover-only ones included: two labels
      // that only appear under the pointer still must not be planned onto the
      // same spot, and a tier-1 rect can never affect tier 0, which is already
      // placed.
      taken.add(chosen.rect);
      placements.set(route.id, {
        id: route.id,
        text,
        x: chosen.x,
        y: chosen.y,
        rect: chosen.rect,
        hidden: false,
        flipped: chosen.flipped,
        axis: chosenRun ? chosenRun.axis : 'h',
        laneId: band ? band.id : null,
        fallback,
        shifted: chosen.shift,
        marker: nudge.point,
        always,
      });
    }
  }

  return { placements, stats };
}

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
