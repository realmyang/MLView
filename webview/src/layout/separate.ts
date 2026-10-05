/**
 * Stage 0a (requirement R7) — an inferred or unresolved cable runs on a track of its own.
 *
 * Viewer M2 drew those cables' dashes and dots above the trunks, but a dash
 * pattern drawn on, or a few pixels from, a solid stroke reads as that stroke.
 * The relayout research of 2026-10-04 measured 9 of the 16 such cables on three
 * real documents with half or more of their length within 4 px of another stroke
 * drawn at rest, 7 of them inside a trunk, and the two sets differ: a cable also
 * leaves its card on the card's centre x, and crosses a gutter on the y every
 * other cable of that gutter uses, trunk or not. Keeping these cables out of the
 * trunks (`channel.ts`, `routing.ts`, `bundles.ts`) is one half of the fix; this
 * pass is the other.
 *
 * It runs after every observed cable is routed and moves nothing else: observed
 * cables, trunks and spurs are obstacles here, so the observed picture is the one
 * `routeEdges` drew. A cable moves one run at a time. A run of an orthogonal
 * polyline can slide sideways without the polyline changing shape, because its
 * two neighbours just get longer or shorter; a first or last run slides its port
 * along the card face it leaves, `PORT_MARGIN` px clear of the corners, and no
 * run gets shorter than `MIN_RUN` px (or than it was), so a cable still meets a
 * card head on and never doubles back over itself. Each run
 * tries offsets of up to `EXCEPTION_MAX_SHIFT` px from where it was routed, in
 * `STEP` px steps, and keeps the cheapest. The cost is the changed runs' length
 * within `EXCEPTION_HIDDEN` px of a parallel stroke (heavily), closer than
 * `EXCEPTION_CLEAR` px (lightly), the strokes they cross, their length, and the
 * distance moved. An offset
 * is refused when the changed runs would pass through more cards, lie along more
 * lane or group headers or more of a card, group or lane border than they did, or
 * leave the frame.
 *
 * Two sweeps over the runs and two rounds over the cables, the second round
 * seeing where the others ended up. Every collection is walked in route order, so
 * the result is deterministic, and a cable that is already clear stays put.
 *
 * Lying on another stroke is a cost, not a refusal: where every offset within
 * reach is refused or shares a line, the cheapest allowed one wins, so in a full
 * gutter a run can still lie on another stroke (26 of 133 uncertain cables over
 * the repo-held, public development and three shakedown documents for more than
 * 8 px, 18 of them on the renderer-regression fixture; `drawnOn` in
 * `tools/layout-metrics.mjs`).
 */

import { EXCEPTION_CLEAR, EXCEPTION_HIDDEN, EXCEPTION_MAX_SHIFT } from './constants.js';
import type { LayoutBox } from './layout.js';
import type { Point } from './orth.js';

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SeparateEnv {
  boxes: Map<string, LayoutBox>;
  /** Cards `points` passes through that are neither end nor around one: the router's own test. */
  hits(points: Point[], s: string, t: string): number;
  /** Strips a horizontal run must not newly lie along: the lane and group headers. */
  headers: Rect[];
  /**
   * Card, group and lane outlines. They are strokes too: a dash pattern drawn on a
   * border reads as the border (an inferred card or group is drawn dashed itself),
   * so a run never lies within `EXCEPTION_HIDDEN` px along one for longer than it
   * already did, and keeps off them as it keeps off cables. A cable crosses them
   * wherever it enters a band or a group, so crossing one costs nothing.
   */
  outlines: Rect[];
  width: number;
  height: number;
}

export interface ExceptionRoute {
  points: Point[];
  source: string;
  target: string;
}

/** A pixel within `EXCEPTION_HIDDEN` px of another stroke costs as much as moving 18 px. */
const HIDDEN_W = 8;
const CLEAR_W = 1;
const LENGTH_W = 0.1;
const MOVE_W = 0.5;
/** A crossing costs as much as moving 24 px, so a run takes the side of a shared run it turns to. */
const CROSS_W = 12;
const STEP = 2;
const PORT_MARGIN = 12;
const MIN_RUN = 8;
const SWEEPS = 2;
const ROUNDS = 2;

/** One axis-aligned run: horizontal at y = `c` over x in [a, b], or vertical at x = `c` over y in [a, b]. */
interface Run {
  h: boolean;
  c: number;
  a: number;
  b: number;
  /** A side of a card, group or lane: kept off, never counted as crossed. */
  outline?: boolean;
}

/**
 * An orthogonal polyline as one coordinate per run (the y of a horizontal run,
 * the x of a vertical one). Consecutive runs alternate, so run i's ends sit at
 * the coordinates of runs i - 1 and i + 1, and the first and last points sit at
 * `start` and `end` along their runs, on the card faces.
 */
interface Shape {
  h: boolean[];
  c: number[];
  origin: number[];
  start: number;
  end: number;
  /** The range a run's coordinate may take: a port's face for the first and last run. */
  range: Array<[number, number] | null>;
  /** The length below which a run may not shrink: `MIN_RUN`, or its routed length if shorter. */
  minLength: number[];
  source: string;
  target: string;
}

/**
 * Move each of `moving` off the strokes in `fixed` and off one another. Returns
 * one polyline per moving cable, the same array when it did not move.
 */
export function separateExceptions(env: SeparateEnv, fixed: Point[][], moving: ExceptionRoute[]): Point[][] {
  const index = new RunIndex();
  for (const points of fixed) for (const run of runsOfPoints(points)) index.add(run, -1);
  for (const rect of env.outlines) for (const run of outlineRuns(rect)) index.add(run, -1);
  const sides = new RunIndex();
  for (const rect of env.outlines) for (const run of outlineRuns(rect)) sides.add(run, -1);
  const shapes = moving.map((route) => shapeOf(route, env.boxes));
  moving.forEach((route, k) => {
    const shape = shapes[k];
    for (const run of shape ? runsOfShape(shape) : runsOfPoints(route.points)) index.add(run, k);
  });

  for (let round = 0; round < ROUNDS; round++) {
    for (let k = 0; k < shapes.length; k++) {
      const shape = shapes[k];
      if (!shape) continue;
      // Only this cable moves while it settles, so what each of its runs can meet
      // is read from the index once per round.
      const near = shape.c.map((_, j) => index.query(reachOf(shape, j), k));
      for (let sweep = 0; sweep < SWEEPS; sweep++) {
        for (let i = 0; i < shape.c.length; i++) settle(env, sides, shape, i, near, round === 0 ? isNear : isHiding);
      }
      index.remove(k);
      for (const run of runsOfShape(shape)) index.add(run, k);
    }
  }

  return shapes.map((shape, k) => {
    if (!shape || shape.c.every((c, i) => Math.abs(c - shape.origin[i]) < 0.01)) return moving[k].points;
    return dedupe(build(shape, shape.c));
  });
}

/**
 * A parallel stroke closer than `EXCEPTION_CLEAR` px is near; one at most
 * `EXCEPTION_HIDDEN` px away hides the run. A run exactly `EXCEPTION_CLEAR` px
 * from its neighbours, as a channel track is from the next, is clear.
 */
const isNear = (d: number): boolean => d < EXCEPTION_CLEAR;
const isHiding = (d: number): boolean => d <= EXCEPTION_HIDDEN;

/**
 * Pick the cheapest allowed coordinate for run `i` of cable `k`, the others held
 * where they are. A run with no parallel stroke `within` reach stays put.
 */
function settle(env: SeparateEnv, sides: RunIndex, shape: Shape, i: number, near: Indexed[][], within: (d: number) => boolean): void {
  const current = shape.c[i];
  const here = runOf(shape, shape.c, i);
  if (!near[i].some((other) => other.h === here.h && within(Math.abs(other.c - here.c)) && Math.min(here.b, other.b) - Math.max(here.a, other.a) > 0.01)) return;

  const range = shape.range[i];
  const values: number[] = [];
  const steps = Math.floor(EXCEPTION_MAX_SHIFT / STEP);
  for (let n = 0; n <= steps; n++) {
    for (const sign of n === 0 ? [1] : [-1, 1]) {
      const v = round(shape.origin[i] + sign * n * STEP);
      if (range && (v < range[0] - 0.01 || v > range[1] + 0.01) && Math.abs(v - shape.origin[i]) > 0.01) continue;
      values.push(v);
    }
  }

  // The runs that change are this one and its two neighbours. Read the strokes
  // near where each can be once, then price every offset against those alone.
  const lo = Math.max(0, i - 1);
  const hi = Math.min(shape.c.length - 1, i + 1);
  const vmin = Math.min(...values);
  const vmax = Math.max(...values);
  const prepared: Prepared[] = [];
  for (let j = lo; j <= hi; j++) prepared.push(prepare(shape, i, j, vmin, vmax, near[j]));

  const trial = shape.c.slice();
  const price = (v: number): number => {
    trial[i] = v;
    let cost = MOVE_W * Math.abs(v - shape.origin[i]);
    for (let j = lo; j <= hi; j++) cost += runCost(runOf(shape, trial, j), prepared[j - lo], j === i);
    return cost;
  };
  // Every term is at least 0 and the two neighbours shorten by at most the
  // offset each, so an offset d costs at least `floor + (MOVE_W - 2 LENGTH_W) d`.
  // Once that passes what staying put costs, no further offset can win.
  const stay = price(current);
  trial[i] = shape.origin[i];
  let floor = 0;
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, trial, j);
    floor += LENGTH_W * (run.b - run.a);
  }
  const scored: Array<[number, number]> = [[stay, current]];
  for (const v of values) {
    const d = Math.abs(v - shape.origin[i]);
    if (floor + (MOVE_W - 2 * LENGTH_W) * d > stay) break;
    if (Math.abs(v - current) < 0.01) continue;
    scored.push([price(v), v]);
  }
  scored.sort((a, b) => a[0] - b[0] || Math.abs(a[1] - shape.origin[i]) - Math.abs(b[1] - shape.origin[i]) || a[1] - b[1]);

  trial[i] = current;
  const was = trouble(env, sides, shape, trial, lo, hi);
  for (const [, v] of scored) {
    if (Math.abs(v - current) < 0.01) return;
    trial[i] = v;
    if (allowed(env, sides, shape, trial, lo, hi, was)) {
      shape.c[i] = v;
      return;
    }
  }
}

/** Cards passed through, end cards entered, headers and borders lain along by runs lo..hi. */
interface Trouble {
  hits: number;
  ends: number;
  headers: number;
  sides: number;
}

function trouble(env: SeparateEnv, sides: RunIndex, shape: Shape, c: number[], lo: number, hi: number): Trouble {
  const points = build(shape, c).slice(lo, hi + 2);
  const out: Trouble = { hits: env.hits(points, shape.source, shape.target), ends: 0, headers: 0, sides: 0 };
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    for (const side of sides.query(boxOf(run, EXCEPTION_HIDDEN), NOBODY)) {
      if (side.h === run.h && Math.abs(side.c - run.c) <= EXCEPTION_HIDDEN) out.sides += Math.max(0, Math.min(run.b, side.b) - Math.max(run.a, side.a));
    }
    for (const id of shape.source === shape.target ? [shape.source] : [shape.source, shape.target]) {
      const box = env.boxes.get(id);
      if (box && runInside(run, box)) out.ends++;
    }
    if (!run.h) continue;
    for (const header of env.headers) {
      if (run.c > header.y && run.c < header.y + header.h && run.b > header.x && run.a < header.x + header.w) out.headers++;
    }
  }
  return out;
}

function allowed(env: SeparateEnv, sides: RunIndex, shape: Shape, c: number[], lo: number, hi: number, was: Trouble): boolean {
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    const across = run.h ? env.height : env.width;
    const along = run.h ? env.width : env.height;
    if (run.c < 0 || run.c > across || run.a < 0 || run.b > along) return false;
    if (run.b - run.a < shape.minLength[j] - 0.01) return false;
  }
  const now = trouble(env, sides, shape, c, lo, hi);
  return now.hits <= was.hits && now.ends <= was.ends && now.headers <= was.headers && now.sides <= was.sides + 0.01;
}

/** True when the run passes through the box's interior (1 px inset, so its faces are free). */
function runInside(run: Run, box: LayoutBox): boolean {
  const m = 1;
  if (run.h) return run.c > box.y + m && run.c < box.y + box.h - m && run.b > box.x + m && run.a < box.x + box.w - m;
  return run.c > box.x + m && run.c < box.x + box.w - m && run.b > box.y + m && run.a < box.y + box.h - m;
}

/**
 * Everywhere run `j` can be while any run of its cable slides: its own line over
 * `EXCEPTION_MAX_SHIFT` px either side of where it was routed, and its ends over
 * the same range of its neighbours, padded by `EXCEPTION_CLEAR` px.
 */
function reachOf(shape: Shape, j: number): Box {
  const span = EXCEPTION_MAX_SHIFT + EXCEPTION_CLEAR;
  const n = shape.c.length;
  const ends = [j === 0 ? shape.start : shape.origin[j - 1], j === n - 1 ? shape.end : shape.origin[j + 1]];
  const along0 = Math.min(ends[0] - (j === 0 ? 0 : span), ends[1] - (j === n - 1 ? 0 : span)) - EXCEPTION_CLEAR;
  const along1 = Math.max(ends[0] + (j === 0 ? 0 : span), ends[1] + (j === n - 1 ? 0 : span)) + EXCEPTION_CLEAR;
  const c = shape.origin[j];
  return shape.h[j]
    ? { x0: along0, y0: c - span, x1: along1, y1: c + span }
    : { x0: c - span, y0: along0, x1: c + span, y1: along1 };
}

function touches(run: Run, box: Box): boolean {
  return run.h
    ? run.c >= box.y0 && run.c <= box.y1 && run.a <= box.x1 && run.b >= box.x0
    : run.c >= box.x0 && run.c <= box.x1 && run.a <= box.y1 && run.b >= box.y0;
}

/**
 * What one changed run can meet while run `i` slides over [vmin, vmax]: the
 * parallel strokes near it, sorted by coordinate, and the strokes across it as
 * sorted bounds, so pricing an offset reads a few of them, not all.
 */
interface Prepared {
  /** Sorted by where they start along the run. */
  parallel: Indexed[];
  /** Run i: a stroke across it at [start, end] along it is crossed when start < v < end. */
  starts: number[];
  ends: number[];
  /** A neighbour: where the strokes across its line sit, crossed when inside its extent. */
  across: number[];
}

function prepare(shape: Shape, i: number, j: number, vmin: number, vmax: number, near: Indexed[]): Prepared {
  const trial = shape.c.slice();
  const here = runOf(shape, trial, j);
  trial[i] = vmin;
  const low = runOf(shape, trial, j);
  trial[i] = vmax;
  const high = runOf(shape, trial, j);
  // The run's reach over every offset: its own line moves when j is i, its ends otherwise.
  const reach: Run = { h: here.h, c: here.c, a: Math.min(here.a, low.a, high.a), b: Math.max(here.b, low.b, high.b) };
  const box = boxOf(reach, EXCEPTION_CLEAR);
  if (j === i) {
    if (here.h) {
      box.y0 = vmin - EXCEPTION_CLEAR;
      box.y1 = vmax + EXCEPTION_CLEAR;
    } else {
      box.x0 = vmin - EXCEPTION_CLEAR;
      box.x1 = vmax + EXCEPTION_CLEAR;
    }
  }
  const out: Prepared = { parallel: [], starts: [], ends: [], across: [] };
  for (const other of near) {
    if (!touches(other, box)) continue;
    if (other.h === here.h) {
      if (j === i || Math.abs(other.c - here.c) <= EXCEPTION_CLEAR) out.parallel.push(other);
    } else if (other.outline) continue;
    else if (j === i) {
      if (other.c > here.a + 0.5 && other.c < here.b - 0.5) {
        out.starts.push(other.a + 0.5);
        out.ends.push(other.b - 0.5);
      }
    } else if (here.c > other.a + 0.5 && here.c < other.b - 0.5) out.across.push(other.c);
  }
  out.parallel.sort((a, b) => a.a - b.a || a.c - b.c);
  out.starts.sort((a, b) => a - b);
  out.ends.sort((a, b) => a - b);
  out.across.sort((a, b) => a - b);
  return out;
}

function runCost(run: Run, p: Prepared, moving: boolean): number {
  // One sweep along the run, in the order the parallel strokes start: the union of
  // the stretches within EXCEPTION_HIDDEN px and of those closer than EXCEPTION_CLEAR px.
  let hidden = 0;
  let hiddenFrom = -1e9;
  let hiddenTo = -1e9;
  let near = 0;
  let nearFrom = -1e9;
  let nearTo = -1e9;
  for (const other of p.parallel) {
    const d = Math.abs(other.c - run.c);
    if (!isNear(d)) continue;
    const lo = Math.max(run.a, other.a);
    const hi = Math.min(run.b, other.b);
    if (hi - lo <= 0.01) continue;
    if (lo > nearTo) {
      near += nearTo - nearFrom;
      nearFrom = lo;
      nearTo = hi;
    } else if (hi > nearTo) nearTo = hi;
    if (!isHiding(d)) continue;
    if (lo > hiddenTo) {
      hidden += hiddenTo - hiddenFrom;
      hiddenFrom = lo;
      hiddenTo = hi;
    } else if (hi > hiddenTo) hiddenTo = hi;
  }
  hidden += hiddenTo - hiddenFrom;
  near += nearTo - nearFrom;
  const crossings = moving
    ? countBelow(p.starts, run.c, false) - countBelow(p.ends, run.c, true)
    : countBelow(p.across, run.b - 0.5, false) - countBelow(p.across, run.a + 0.5, true);
  return HIDDEN_W * hidden + CLEAR_W * near + CROSS_W * crossings + LENGTH_W * (run.b - run.a);
}

/** How many of the sorted `values` are below `v` (or at most `v`, with `inclusive`). */
function countBelow(values: number[], v: number, inclusive: boolean): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < v || (inclusive && values[mid] === v)) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** An axis-aligned rectangle by its edges. */
interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function boxOf(run: Run, pad: number): Box {
  return run.h
    ? { x0: run.a - pad, y0: run.c - pad, x1: run.b + pad, y1: run.c + pad }
    : { x0: run.c - pad, y0: run.a - pad, x1: run.c + pad, y1: run.b + pad };
}

/** A run in the index: whose it is (-1 for a fixed stroke, else the moving cable's position). */
interface Indexed extends Run {
  owner: number;
  seen: number;
}

/** Grid cell size of the index, in px. */
const CELL = 64;
/** The `skip` of a query that skips no run (fixed strokes are owned by -1). */
const NOBODY = -2;

/**
 * Every run, fixed and moving, bucketed on a uniform grid, so a query reads the
 * runs near it and not the whole drawing. A moving cable's runs are replaced as
 * it settles.
 */
class RunIndex {
  private cells = new Map<number, Indexed[]>();
  private byOwner = new Map<number, Indexed[]>();
  private stamp = 0;

  add(run: Run, owner: number): void {
    const item: Indexed = { ...run, owner, seen: 0 };
    forCells(boxOf(run, 0), (key) => {
      const list = this.cells.get(key);
      if (list) list.push(item);
      else this.cells.set(key, [item]);
    });
    if (owner < 0) return;
    const own = this.byOwner.get(owner);
    if (own) own.push(item);
    else this.byOwner.set(owner, [item]);
  }

  remove(owner: number): void {
    const own = this.byOwner.get(owner);
    if (!own) return;
    this.byOwner.delete(owner);
    for (const item of own) {
      forCells(boxOf(item, 0), (key) => {
        const list = this.cells.get(key);
        const at = list ? list.indexOf(item) : -1;
        if (list && at >= 0) list.splice(at, 1);
      });
    }
  }

  /** Every run touching `box` that `skip` does not own, each once. */
  query(box: Box, skip: number): Indexed[] {
    const stamp = ++this.stamp;
    const out: Indexed[] = [];
    forCells(box, (key) => {
      for (const item of this.cells.get(key) || []) {
        if (item.seen === stamp || item.owner === skip) continue;
        item.seen = stamp;
        if (touches(item, box)) out.push(item);
      }
    });
    return out;
  }
}

function forCells(box: Box, visit: (key: number) => void): void {
  const x1 = Math.floor(box.x1 / CELL);
  const y1 = Math.floor(box.y1 / CELL);
  for (let gx = Math.floor(box.x0 / CELL); gx <= x1; gx++) {
    for (let gy = Math.floor(box.y0 / CELL); gy <= y1; gy++) visit(gx * 1048576 + gy);
  }
}

/** The four sides of a card, group or lane. */
function outlineRuns(r: Rect): Run[] {
  return [
    { h: true, c: r.y, a: r.x, b: r.x + r.w, outline: true },
    { h: true, c: r.y + r.h, a: r.x, b: r.x + r.w, outline: true },
    { h: false, c: r.x, a: r.y, b: r.y + r.h, outline: true },
    { h: false, c: r.x + r.w, a: r.y, b: r.y + r.h, outline: true },
  ];
}

function runsOfPoints(points: Point[]): Run[] {
  const out: Run[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    if (Math.abs(a.y - b.y) < 0.01 && Math.abs(a.x - b.x) >= 0.01) out.push({ h: true, c: a.y, a: Math.min(a.x, b.x), b: Math.max(a.x, b.x) });
    else if (Math.abs(a.x - b.x) < 0.01 && Math.abs(a.y - b.y) >= 0.01) out.push({ h: false, c: a.x, a: Math.min(a.y, b.y), b: Math.max(a.y, b.y) });
  }
  return out;
}

function runsOfShape(shape: Shape): Run[] {
  return shape.c.map((_, i) => runOf(shape, shape.c, i));
}

/** Run `i` of `shape` with its coordinates taken from `c`. */
function runOf(shape: Shape, c: number[], i: number): Run {
  const from = i === 0 ? shape.start : c[i - 1];
  const to = i === c.length - 1 ? shape.end : c[i + 1];
  return { h: shape.h[i], c: c[i], a: Math.min(from, to), b: Math.max(from, to) };
}

function build(shape: Shape, c: number[]): Point[] {
  const n = c.length;
  const out: Point[] = [shape.h[0] ? p(shape.start, c[0]) : p(c[0], shape.start)];
  for (let i = 1; i < n; i++) out.push(shape.h[i - 1] ? p(c[i], c[i - 1]) : p(c[i - 1], c[i]));
  out.push(shape.h[n - 1] ? p(shape.end, c[n - 1]) : p(c[n - 1], shape.end));
  return out;
}

/** The shape of a route, or null for one this pass cannot move (not orthogonal, or turning back on itself). */
function shapeOf(route: ExceptionRoute, boxes: Map<string, LayoutBox>): Shape | null {
  const pts = simplify(route.points);
  if (pts.length < 2) return null;
  const h: boolean[] = [];
  const c: number[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const horizontal = Math.abs(a.y - b.y) < 0.01;
    if (!horizontal && Math.abs(a.x - b.x) >= 0.01) return null;
    if (h.length && h[h.length - 1] === horizontal) return null;
    h.push(horizontal);
    c.push(horizontal ? a.y : a.x);
  }
  const n = c.length;
  const first = pts[0];
  const last = pts[pts.length - 1];
  const range: Array<[number, number] | null> = c.map(() => null);
  const startFace = faceRange(boxes.get(route.source), first, h[0]);
  const endFace = faceRange(boxes.get(route.target), last, h[n - 1]);
  range[0] = startFace;
  range[n - 1] = n === 1 ? [Math.max(startFace[0], endFace[0]), Math.min(startFace[1], endFace[1])] : endFace;
  const shape = {
    h,
    c,
    origin: c.slice(),
    start: h[0] ? first.x : first.y,
    end: h[n - 1] ? last.x : last.y,
    range,
    minLength: [] as number[],
    source: route.source,
    target: route.target,
  };
  shape.minLength = c.map((_, i) => {
    const run = runOf(shape, c, i);
    return Math.min(MIN_RUN, run.b - run.a);
  });
  return shape;
}

/**
 * Where a port may slide: along the face of `box` the end point sits on, clear of
 * the corners. A point on no face (a containment cable starts inside its group)
 * stays where it is.
 */
function faceRange(box: LayoutBox | undefined, pt: Point, horizontal: boolean): [number, number] {
  const fixedAt: [number, number] = [horizontal ? pt.y : pt.x, horizontal ? pt.y : pt.x];
  if (!box) return fixedAt;
  if (horizontal) {
    if (Math.abs(pt.x - box.x) > 0.5 && Math.abs(pt.x - box.x - box.w) > 0.5) return fixedAt;
    const m = Math.min(PORT_MARGIN, box.h / 4);
    return [box.y + m, box.y + box.h - m];
  }
  if (Math.abs(pt.y - box.y) > 0.5 && Math.abs(pt.y - box.y - box.h) > 0.5) return fixedAt;
  const m = Math.min(PORT_MARGIN, box.w / 4);
  return [box.x + m, box.x + box.w - m];
}

/** Drop repeated points and merge straight runs, so every interior point is a turn. */
function simplify(points: Point[]): Point[] {
  const out = dedupe(points);
  for (let i = out.length - 2; i >= 1; i--) {
    const a = out[i - 1];
    const b = out[i];
    const c = out[i + 1];
    const straightX = Math.abs(a.x - b.x) < 0.01 && Math.abs(b.x - c.x) < 0.01 && (b.y - a.y) * (c.y - b.y) > 0;
    const straightY = Math.abs(a.y - b.y) < 0.01 && Math.abs(b.y - c.y) < 0.01 && (b.x - a.x) * (c.x - b.x) > 0;
    if (straightX || straightY) out.splice(i, 1);
  }
  return out;
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

function p(x: number, y: number): Point {
  return { x: round(x), y: round(y) };
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
