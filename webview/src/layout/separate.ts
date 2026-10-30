/**
 * An inferred or unresolved cable runs on a track of its own.
 *
 * A dash pattern drawn on, or a few pixels from, a solid stroke reads as that
 * stroke. Inside a trunk such a cable would lie on the observed ones, and outside
 * one it can too: a cable leaves its card on the card's centre x, and crosses a
 * gutter on the y every other cable of that gutter uses, trunk or not. Keeping
 * these cables out of the trunks (`channel.ts`, `routing.ts`, `bundles.ts`) is
 * one half of keeping them legible; this pass is the other.
 *
 * It runs after every observed cable is routed and moves nothing else: observed
 * cables, trunks and spurs are obstacles here, so the observed picture is the one
 * `routeEdges` drew. A cable moves one run at a time. A run of an orthogonal
 * polyline can slide sideways while its two neighbours just get longer or
 * shorter; a first or last run slides its port along the card face it leaves,
 * `PORT_MARGIN` px clear of the corners, and no run gets shorter than `MIN_RUN`
 * px (or than it was), so a cable still meets a card head on. The polyline keeps
 * its runs, not always its shape: a run that slides past the far end of a
 * neighbour turns that neighbour round, so a jog can end up on its other side.
 * Each run tries offsets of up to `EXCEPTION_MAX_SHIFT` px from where it was
 * routed, in `STEP` px steps, and keeps the cheapest. The cost is the changed
 * runs' length within `EXCEPTION_HIDDEN` px of a parallel stroke (heavily),
 * closer than `EXCEPTION_CLEAR` px (lightly), the strokes they cross, their
 * length, and the distance moved.
 *
 * An offset is refused when the changed runs would pass through more cards, lie
 * along more lane or group headers, lie within `EXCEPTION_HIDDEN` px along more
 * of a header's lower edge or of a card, group or lane border than they did,
 * cross, touch or lie on another run of their own cable more often than they
 * did, or leave the frame. It is also refused when a vertical run would change
 * sides of the bands' left edge, or one routed in the channel would end closer
 * to the bands than `EXCEPTION_PAD` px (than it was routed, if that was closer
 * still): a channel track stays out of the lanes it skips, and no other run
 * takes a track's place.
 *
 * Two sweeps over the runs and two rounds over the cables, the second round
 * seeing where the others ended up. Every collection is walked in route order, so
 * the result is deterministic, and a cable that is already clear stays put.
 *
 * Lying on another stroke is a cost, not a refusal: where every offset within
 * reach is refused or shares a line, the cheapest allowed one wins, so in a full
 * gutter a run can still lie on another stroke (`drawnOn` in
 * `webview/tools/layout-metrics.mjs` counts the uncertain cables that do so for
 * more than 8 px). Two more things are not refused: a moved run may enter the
 * band of a lane that holds neither end of its cable, and a vertical run may
 * pass through a lane or group header strip, as routed cables do.
 *
 * The pass is a refinement, and it has a bound (`beyondPass`). Its index holds
 * one entry for every 64 px cell a run passes through, so its memory grows with
 * the size of the drawing, which the contract's 2,000 steps and 4,000
 * connections do not limit: groups nested one inside the next can unfold to a
 * drawing millions of px tall. Its time grows with the cables it may move, with
 * their length, with the strokes it finds near them, and with what it reads to
 * find those and to test a move, found or not: the entries of its own tables,
 * and the boxes of the card test, which under groups nested one inside the next
 * are every one of those groups for every segment. A drawing with more of any
 * of the six than the pass takes on is left alone: every cable keeps the route
 * `routeEdges` drew, so an uncertain run can then lie on another stroke. All
 * six are counted, on the drawing alone and never on a clock or on free memory,
 * so the same document is drawn the same everywhere.
 */

import { EXCEPTION_CLEAR, EXCEPTION_HIDDEN, EXCEPTION_MAX_SHIFT, EXCEPTION_PAD } from './constants.js';
import type { LayoutBox } from './layout.js';
import type { Point } from './orth.js';

// A call through these reads a constant of the module. `Math.abs(...)` looks
// `Math` up on the global object each time, and the loops below make such calls
// for every offset and stroke they test, in a page and in jsdom, which runs the
// bundle in a `vm` context.
const { abs, floor, max, min } = Math;
const mathRound = Math.round;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SeparateEnv {
  boxes: Map<string, LayoutBox>;
  /**
   * Cards `points` passes through that are neither end nor around one: the
   * router's own test. With `limit`, any count above it may be returned for one
   * that is above it.
   */
  hits(points: Point[], s: string, t: string, limit?: number): number;
  /**
   * How many boxes have been read for `hits`, all its calls so far together: a
   * box counts each time it is read, whether the segment hits it or not. The
   * pass takes differences only, so what was read before it began may be in it.
   */
  cardsRead(): number;
  /**
   * Strips a horizontal run must not newly lie along: the lane and group headers.
   * A lane header's lower edge is drawn as a line under the heading, so a run does
   * not lie within `EXCEPTION_HIDDEN` px along it for longer than it did either. A
   * group heading has no such line; its lower edge is kept clear by the same rule.
   * The upper edge is the lane's or the group's own border, one of the `outlines`.
   */
  headers: Rect[];
  /**
   * Card, group and lane outlines. They are strokes too: a dash pattern drawn on a
   * border reads as the border (an inferred card or group is drawn dashed itself),
   * so a run never lies within `EXCEPTION_HIDDEN` px along one for longer than it
   * already did, and keeps off them as it keeps off cables. A cable crosses them
   * wherever it enters a band or a group, so crossing one costs nothing.
   */
  outlines: Rect[];
  /**
   * The bands' left edge, the least lane x: the channel lies left of it. A
   * vertical run keeps the side it was routed on, and one routed in the channel
   * is not moved closer to the bands than `EXCEPTION_PAD` px (than it was
   * routed, if that was closer still).
   */
  bandsLeft: number;
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

/**
 * What the pass has taken on. Three counts are known before anything is built:
 * `entries`, the entries its two indexes will hold (`RunIndex`: one for each
 * 64 px cell a run passes through; a card, group or lane side twice, as it is in
 * both); `moving`, those of them that belong to the cables that may move; and
 * `cables`, how many such cables there are. The other three are counted as the
 * pass goes, each from nothing in each round: `strokes`, the strokes found
 * within reach (`reachOf`) of the runs whose turn has come; `reads`, what the
 * pass has read of its own tables, found or not (every entry of every cell an
 * index walks for a query or searches to take a run out, and every header a
 * run is read against); and `cards`, the boxes read for the card test
 * (`SeparateEnv.cardsRead`). A cell that holds nothing is looked up and adds
 * nothing to `reads`; such look-ups grow with the cells under the moving runs,
 * which `moving` limits.
 */
export interface PassLoad {
  entries: number;
  moving: number;
  cables: number;
  strokes: number;
  reads: number;
  cards: number;
}

/**
 * The most the pass takes on, one limit for each count of `PassLoad`:
 *
 *   MAX_INDEX_ENTRIES   entries in both indexes: the memory of the pass
 *   MAX_MOVING_ENTRIES  entries of the cables that may move, each read, taken
 *                       out and put back every round
 *   MAX_MOVING_CABLES   cables that may move, each run of which may try its
 *                       offsets twice a round whatever is near it
 *   MAX_NEAR_STROKES    strokes found within reach in one round
 *   MAX_ROUND_READS     entries of its own tables read in one round, found or
 *                       not: a stroke just out of a cable's reach is read by
 *                       every query and never found
 *   MAX_CARD_READS      boxes the card test reads in one round, found or not:
 *                       every group around a cable's ends is read for each of
 *                       its segments
 *
 * The first limit bounds the memory, the other five the time. The first three
 * counts are compared before the indexes are built, the last three before each
 * cable settles, so a round can pass a limit by what one cable reads while it
 * settles. Past any of them `settled` gives up and drops every move it has made,
 * and `separateExceptions` returns the routes as `routeEdges` drew them.
 */
export const MAX_INDEX_ENTRIES = 2e6;
export const MAX_MOVING_ENTRIES = 2e5;
export const MAX_MOVING_CABLES = 2000;
export const MAX_NEAR_STROKES = 2.5e6;
export const MAX_ROUND_READS = 1e8;
export const MAX_CARD_READS = 1e7;

/**
 * True when a drawing is beyond what the pass takes on. A count that is not a
 * number (a coordinate that is not finite) is beyond it too.
 */
export function beyondPass(load: PassLoad): boolean {
  return !(
    load.entries <= MAX_INDEX_ENTRIES &&
    load.moving <= MAX_MOVING_ENTRIES &&
    load.cables <= MAX_MOVING_CABLES &&
    load.strokes <= MAX_NEAR_STROKES &&
    load.reads <= MAX_ROUND_READS &&
    load.cards <= MAX_CARD_READS
  );
}

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
  /**
   * The lane and group headers a horizontal run of the cable can lie in or
   * under wherever the pass puts it (`headersNear`), in the order of
   * `SeparateEnv.headers`. Filled once, before the first round.
   */
  headers: Rect[];
  source: string;
  target: string;
}

/**
 * Move each of `moving` off the strokes in `fixed` and off one another. Returns
 * one polyline per moving cable, the same array when it did not move. On a
 * drawing beyond the pass (`beyondPass`) no cable moves.
 */
export function separateExceptions(env: SeparateEnv, fixed: Point[][], moving: ExceptionRoute[]): Point[][] {
  return settled(env, fixed, moving) || moving.map((route) => route.points);
}

/** The pass itself: one polyline per moving cable, or null once the drawing proves beyond it. */
function settled(env: SeparateEnv, fixed: Point[][], moving: ExceptionRoute[]): Point[][] | null {
  const fixedRuns: Run[] = [];
  for (const points of fixed) for (const run of runsOfPoints(points)) fixedRuns.push(run);
  const sideRuns: Run[] = [];
  for (const rect of env.outlines) for (const run of outlineRuns(rect)) sideRuns.push(run);
  const shapes = moving.map((route) => shapeOf(route, env.boxes));
  const ownRuns = moving.map((route, k) => {
    const shape = shapes[k];
    return shape ? runsOfShape(shape) : runsOfPoints(route.points);
  });

  // Counted first: a long run costs nothing to count and a cell for every 64 px to index.
  const load: PassLoad = { entries: cellsOf(fixedRuns) + 2 * cellsOf(sideRuns), moving: 0, cables: moving.length, strokes: 0, reads: 0, cards: 0 };
  for (const runs of ownRuns) load.moving += cellsOf(runs);
  load.entries += load.moving;
  if (beyondPass(load)) return null;

  // A horizontal run is read against the headers for every offset it or a
  // neighbour tries. The few its cable can reach are picked out once, so a run
  // is not read against every header of the drawing each time.
  for (const shape of shapes) if (shape) shape.headers = headersNear(shape, env.headers);

  const index = new RunIndex();
  for (const run of fixedRuns) index.add(run, -1);
  for (const run of sideRuns) index.add(run, -1);
  const sides = new RunIndex();
  for (const run of sideRuns) sides.add(run, -1);
  ownRuns.forEach((runs, k) => {
    for (const run of runs) index.add(run, k);
  });

  for (let round = 0; round < ROUNDS; round++) {
    // What a round reads is counted from nothing. The card test's count runs on
    // from before the pass, so a round's share is what it has grown by.
    load.strokes = 0;
    load.reads = 0;
    const cardsBefore = env.cardsRead();
    for (let k = 0; k < shapes.length; k++) {
      const shape = shapes[k];
      if (!shape) continue;
      // Only this cable moves while it settles, so what each of its runs can meet
      // is read from the index once per round.
      const near = shape.c.map((_, j) => {
        const found = index.query(reachOf(shape, j), k, load);
        load.strokes += found.length;
        return nearOf(found, shape.h[j]);
      });
      load.cards = env.cardsRead() - cardsBefore;
      // Settling costs time for every stroke read here, and the cables before
      // this one have read what they read. Past the bound the pass gives up, and
      // with it the moves it has made. This is the one place a round's counts
      // are compared, so a round can pass a limit by what one cable reads while
      // it settles, its last cable included.
      if (beyondPass(load)) return null;
      // Until the cable is put back in the index, a run settles by the cable's own
      // coordinates alone: one that stayed put would stay put again, and is not
      // asked again before a run of the cable has moved.
      let moves = 0;
      const stayedAt = shape.c.map(() => -1);
      for (let sweep = 0; sweep < SWEEPS; sweep++) {
        for (let i = 0; i < shape.c.length; i++) {
          if (stayedAt[i] === moves) continue;
          if (settle(env, sides, shape, i, near, round === 0 ? isNear : isHiding, load)) moves++;
          else stayedAt[i] = moves;
        }
      }
      index.remove(k, load);
      for (const run of runsOfShape(shape)) index.add(run, k);
    }
  }

  return shapes.map((shape, k) => {
    if (!shape || shape.c.every((c, i) => abs(c - shape.origin[i]) < 0.01)) return moving[k].points;
    return dedupe(build(shape, shape.c));
  });
}

/**
 * A parallel stroke closer than `EXCEPTION_CLEAR` px is near; one at most
 * `EXCEPTION_HIDDEN` px away hides the run. A run exactly `EXCEPTION_CLEAR` px
 * from its neighbours, as a channel track is from the next, is clear: both are
 * compared with the 0.01 px the coordinates are rounded to, because two tracks
 * planned 8 px apart on a fractional trunk step differ by 7.999999999999986 in
 * doubles.
 */
const isNear = (d: number): boolean => d < EXCEPTION_CLEAR - 0.01;
const isHiding = (d: number): boolean => d <= EXCEPTION_HIDDEN + 0.01;

/**
 * Pick the cheapest allowed coordinate for run `i` of cable `k`, the others held
 * where they are, and say whether the run moved. A run with no parallel stroke
 * `within` reach stays put. What it picks depends on `shape.c`, `near` and
 * `within` and on nothing else that changes during the pass.
 */
function settle(env: SeparateEnv, sides: RunIndex, shape: Shape, i: number, near: Near[], within: (d: number) => boolean, load: PassLoad): boolean {
  const current = shape.c[i];
  const here = runOf(shape, shape.c, i);
  if (!near[i].parallel.some((other) => within(abs(other.c - here.c)) && min(here.b, other.b) - max(here.a, other.a) > 0.01)) return false;

  const range = shape.range[i];
  const values: number[] = [];
  const steps = floor(EXCEPTION_MAX_SHIFT / STEP);
  for (let n = 0; n <= steps; n++) {
    for (const sign of n === 0 ? [1] : [-1, 1]) {
      const v = round(shape.origin[i] + sign * n * STEP);
      if (range && (v < range[0] - 0.01 || v > range[1] + 0.01) && abs(v - shape.origin[i]) > 0.01) continue;
      values.push(v);
    }
  }

  // The runs that change are this one and its two neighbours. Read the strokes
  // near where each can be once, then price every offset against those alone.
  const lo = max(0, i - 1);
  const hi = min(shape.c.length - 1, i + 1);
  const vmin = min(...values);
  const vmax = max(...values);
  const prepared: Prepared[] = [];
  for (let j = lo; j <= hi; j++) prepared.push(prepare(shape, i, j, vmin, vmax, near[j]));

  const trial = shape.c.slice();
  // Every term is at least 0 and the two neighbours shorten by at most the
  // offset each, so an offset d costs at least `base + (MOVE_W - 2 LENGTH_W) d`.
  // Once that passes what staying put costs, no further offset can win.
  const stay = price(shape, trial, prepared, i, lo, hi, current);
  trial[i] = shape.origin[i];
  let base = 0;
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, trial, j);
    base += LENGTH_W * (run.b - run.a);
  }
  const scored: Array<[number, number]> = [[stay, current]];
  for (const v of values) {
    const d = abs(v - shape.origin[i]);
    if (base + (MOVE_W - 2 * LENGTH_W) * d > stay) break;
    if (abs(v - current) < 0.01) continue;
    scored.push([price(shape, trial, prepared, i, lo, hi, v), v]);
  }
  // Cheapest first, then nearest to where the run was routed, then the lower
  // coordinate. No two offsets are the same coordinate, so the order is strict and
  // an insertion sort of this short list gives what any sort would.
  const origin = shape.origin[i];
  for (let n = 1; n < scored.length; n++) {
    const item = scored[n];
    let m = n;
    while (m > 0 && (scored[m - 1][0] - item[0] || abs(scored[m - 1][1] - origin) - abs(item[1] - origin) || scored[m - 1][1] - item[1]) > 0) {
      scored[m] = scored[m - 1];
      m--;
    }
    scored[m] = item;
  }

  trial[i] = current;
  const was = trouble(env, sides, shape, trial, lo, hi, load);
  for (const [, v] of scored) {
    if (abs(v - current) < 0.01) return false;
    trial[i] = v;
    if (allowed(env, sides, shape, trial, lo, hi, was, load)) {
      shape.c[i] = v;
      return true;
    }
  }
  return false;
}

/**
 * Cards passed through, end cards entered, headers and borders lain along by runs
 * lo..hi, and how often those runs meet another run of their own cable.
 */
interface Trouble {
  hits: number;
  ends: number;
  headers: number;
  /** Length lain within `EXCEPTION_HIDDEN` px along the lower edge of a header (a lane's is a drawn line). */
  underlines: number;
  sides: number;
  self: number;
}

function trouble(env: SeparateEnv, sides: RunIndex, shape: Shape, c: number[], lo: number, hi: number, load: PassLoad): Trouble {
  const strips = stripsOf(shape, c, lo, hi, load);
  return {
    hits: hitsOf(env, shape, c, lo, hi),
    ends: endsOf(env, shape, c, lo, hi),
    headers: strips.headers,
    underlines: strips.underlines,
    sides: sidesOf(sides, shape, c, lo, hi, load),
    self: selfMeets(shape, c, lo, hi),
  };
}

function hitsOf(env: SeparateEnv, shape: Shape, c: number[], lo: number, hi: number, limit?: number): number {
  return env.hits(build(shape, c).slice(lo, hi + 2), shape.source, shape.target, limit);
}

function endsOf(env: SeparateEnv, shape: Shape, c: number[], lo: number, hi: number): number {
  let ends = 0;
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    for (const id of shape.source === shape.target ? [shape.source] : [shape.source, shape.target]) {
      const box = env.boxes.get(id);
      if (box && runInside(run, box)) ends++;
    }
  }
  return ends;
}

function stripsOf(shape: Shape, c: number[], lo: number, hi: number, load: PassLoad): { headers: number; underlines: number } {
  const out = { headers: 0, underlines: 0 };
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    if (!run.h) continue;
    load.reads += shape.headers.length;
    // Read apart, so a run by a header's lower edge cannot trade that for a place in the strip.
    for (const header of shape.headers) {
      const along = min(run.b, header.x + header.w) - max(run.a, header.x);
      if (along <= 0) continue;
      if (run.c > header.y && run.c < header.y + header.h) out.headers++;
      if (abs(run.c - header.y - header.h) <= EXCEPTION_HIDDEN) out.underlines += along;
    }
  }
  return out;
}

/**
 * The headers `stripsOf` can count for a run of `shape`, in the order given
 * (the order it adds in). It counts a header for a horizontal run inside the
 * strip or within `EXCEPTION_HIDDEN` px of its lower edge, and a run stays
 * within `EXCEPTION_MAX_SHIFT` px of where it was routed, so a header further
 * than both from every horizontal run of the cable is never counted. The test
 * is on y alone and a pixel wide of the mark: what it lets through, `stripsOf`
 * still reads in full.
 */
function headersNear(shape: Shape, headers: Rect[]): Rect[] {
  const span = EXCEPTION_MAX_SHIFT + EXCEPTION_HIDDEN + 1;
  const out: Rect[] = [];
  for (const header of headers) {
    const top = min(header.y, header.y + header.h) - span;
    const bottom = max(header.y, header.y + header.h) + span;
    for (let j = 0; j < shape.origin.length; j++) {
      if (shape.h[j] && shape.origin[j] >= top && shape.origin[j] <= bottom) {
        out.push(header);
        break;
      }
    }
  }
  return out;
}

function sidesOf(sides: RunIndex, shape: Shape, c: number[], lo: number, hi: number, load: PassLoad): number {
  let length = 0;
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    for (const side of sides.query(boxOf(run, EXCEPTION_HIDDEN), NOBODY, load)) {
      if (side.h === run.h && abs(side.c - run.c) <= EXCEPTION_HIDDEN) length += max(0, min(run.b, side.b) - max(run.a, side.a));
    }
  }
  return length;
}

function allowed(env: SeparateEnv, sides: RunIndex, shape: Shape, c: number[], lo: number, hi: number, was: Trouble, load: PassLoad): boolean {
  for (let j = lo; j <= hi; j++) {
    const run = runOf(shape, c, j);
    const across = run.h ? env.height : env.width;
    const along = run.h ? env.width : env.height;
    if (run.c < 0 || run.c > across || run.a < 0 || run.b > along) return false;
    if (run.b - run.a < shape.minLength[j] - 0.01) return false;
    // A vertical run keeps its side of the bands' left edge, and a channel run its pad.
    if (!run.h) {
      const o = shape.origin[j];
      if (o < env.bandsLeft ? run.c > max(o, env.bandsLeft - EXCEPTION_PAD) + 0.01 : run.c < env.bandsLeft) return false;
    }
  }
  // No measure of `trouble` may be worse than it was. Each is read on its own,
  // the cheap ones first, and the first that is worse ends the test: most
  // offsets are refused before the border sum, the dearest, is taken.
  if (!(endsOf(env, shape, c, lo, hi) <= was.ends)) return false;
  if (!(selfMeets(shape, c, lo, hi) <= was.self)) return false;
  const strips = stripsOf(shape, c, lo, hi, load);
  if (!(strips.headers <= was.headers && strips.underlines <= was.underlines + 0.01)) return false;
  if (!(hitsOf(env, shape, c, lo, hi, was.hits) <= was.hits)) return false;
  return sidesOf(sides, shape, c, lo, hi, load) <= was.sides + 0.01;
}

/**
 * How often runs lo..hi cross, touch or lie on a run of their own cable that is
 * not a neighbour. The index never holds a cable's own runs against it, so this
 * is the one place a cable is read against itself: a run that slides past its
 * neighbour's far end turns that neighbour round, and the run beyond it can then
 * cross the cable or lie on it.
 */
function selfMeets(shape: Shape, c: number[], lo: number, hi: number): number {
  let n = 0;
  for (let j = lo; j <= hi; j++) {
    const a = runOf(shape, c, j);
    for (let k = 0; k < c.length; k++) {
      // Each pair once: a run of lo..hi before `j` has already been read against it.
      if (abs(k - j) < 2 || (k >= lo && k < j)) continue;
      const b = runOf(shape, c, k);
      if (a.h === b.h) {
        if (abs(a.c - b.c) < 0.01 && min(a.b, b.b) - max(a.a, b.a) > 0.01) n++;
      } else if (b.c > a.a - 0.01 && b.c < a.b + 0.01 && a.c > b.a - 0.01 && a.c < b.b + 0.01) n++;
    }
  }
  return n;
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
  const along0 = min(ends[0] - (j === 0 ? 0 : span), ends[1] - (j === n - 1 ? 0 : span)) - EXCEPTION_CLEAR;
  const along1 = max(ends[0] + (j === 0 ? 0 : span), ends[1] + (j === n - 1 ? 0 : span)) + EXCEPTION_CLEAR;
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

/**
 * The strokes one run of a cable can meet while the cable settles, as the index
 * returned them: those parallel to it, in the order `runCost` sweeps them, and
 * those across it that count when crossed (a border does not).
 */
interface Near {
  parallel: Indexed[];
  across: Indexed[];
}

function nearOf(found: Indexed[], horizontal: boolean): Near {
  const out: Near = { parallel: [], across: [] };
  for (const other of found) {
    if (other.h === horizontal) out.parallel.push(other);
    else if (!other.outline) out.across.push(other);
  }
  // By where they start along the run. The sort is stable, so the strokes kept
  // of this list for one offset range are in the order sorting them alone gives.
  out.parallel.sort((a, b) => a.a - b.a || a.c - b.c);
  return out;
}

function prepare(shape: Shape, i: number, j: number, vmin: number, vmax: number, near: Near): Prepared {
  const trial = shape.c.slice();
  const here = runOf(shape, trial, j);
  trial[i] = vmin;
  const low = runOf(shape, trial, j);
  trial[i] = vmax;
  const high = runOf(shape, trial, j);
  // The run's reach over every offset: its own line moves when j is i, its ends otherwise.
  // Built as a literal, unlike `runOf`, whose comment says why V8 may recompile a
  // function that stores fractions into such a literal.
  const reach: Run = { h: here.h, c: here.c, a: min(here.a, low.a, high.a), b: max(here.b, low.b, high.b) };
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
  for (const other of near.parallel) {
    if (touches(other, box) && (j === i || abs(other.c - here.c) <= EXCEPTION_CLEAR)) out.parallel.push(other);
  }
  for (const other of near.across) {
    if (!touches(other, box)) continue;
    if (j === i) {
      if (other.c > here.a + 0.5 && other.c < here.b - 0.5) {
        out.starts.push(other.a + 0.5);
        out.ends.push(other.b - 0.5);
      }
    } else if (here.c > other.a + 0.5 && here.c < other.b - 0.5) out.across.push(other.c);
  }
  ascending(out.starts);
  ascending(out.ends);
  ascending(out.across);
  return out;
}

/** The longest list `ascending` sorts by insertion. */
const INSERTION_MAX = 24;

/**
 * Sort numbers ascending in place. Most of the lists are a few numbers long, and
 * for those an insertion sort costs less than the calls `sort` makes to compare.
 */
function ascending(values: number[]): void {
  if (values.length > INSERTION_MAX) {
    values.sort((a, b) => a - b);
    return;
  }
  for (let n = 1; n < values.length; n++) {
    const v = values[n];
    let m = n;
    while (m > 0 && values[m - 1] > v) {
      values[m] = values[m - 1];
      m--;
    }
    values[m] = v;
  }
}

/**
 * What runs lo..hi of `trial` cost with run `i` at `v` (which it writes to
 * `trial`), each read against its own `prepared`: the move, then the runs in order.
 */
function price(shape: Shape, trial: number[], prepared: Prepared[], i: number, lo: number, hi: number, v: number): number {
  trial[i] = v;
  let cost = MOVE_W * abs(v - shape.origin[i]);
  for (let j = lo; j <= hi; j++) {
    // Run j as `runOf` gives it, without making the object.
    const from = j === 0 ? shape.start : trial[j - 1];
    const to = j === trial.length - 1 ? shape.end : trial[j + 1];
    cost += runCost(trial[j], min(from, to), max(from, to), prepared[j - lo], j === i);
  }
  return cost;
}

/** The cost of a run at coordinate `c` over [a, b], read against `p`. */
function runCost(c: number, a: number, b: number, p: Prepared, moving: boolean): number {
  // One sweep along the run, in the order the parallel strokes start: the union of
  // the stretches within EXCEPTION_HIDDEN px and of those closer than EXCEPTION_CLEAR px.
  let hidden = 0;
  let hiddenFrom = -1e9;
  let hiddenTo = -1e9;
  let near = 0;
  let nearFrom = -1e9;
  let nearTo = -1e9;
  const parallel = p.parallel;
  for (let n = 0; n < parallel.length; n++) {
    const other = parallel[n];
    const d = abs(other.c - c);
    if (!isNear(d)) continue;
    const lo = max(a, other.a);
    const hi = min(b, other.b);
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
    ? countBelow(p.starts, c, false) - countBelow(p.ends, c, true)
    : countBelow(p.across, b - 0.5, false) - countBelow(p.across, a + 0.5, true);
  return HIDDEN_W * hidden + CLEAR_W * near + CROSS_W * crossings + LENGTH_W * (b - a);
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
    // Written out, not `{ ...run, owner, seen: 0 }`, so that every run in the
    // index has one shape. In V8 the copies a spread makes can each end up with
    // a hidden class of their own, and each read of `c`, `a` or `b` in the loops
    // of this file is then a lookup.
    const item: Indexed = { h: run.h, c: run.c, a: run.a, b: run.b, outline: run.outline === true, owner, seen: 0 };
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

  /** Take the runs of `owner` out. Every cell they lie in is searched for them: `load.reads` grows by its entries. */
  remove(owner: number, load: PassLoad): void {
    const own = this.byOwner.get(owner);
    if (!own) return;
    this.byOwner.delete(owner);
    for (const item of own) {
      forCells(boxOf(item, 0), (key) => {
        const list = this.cells.get(key);
        if (!list) return;
        load.reads += list.length;
        const at = list.indexOf(item);
        if (at >= 0) list.splice(at, 1);
      });
    }
  }

  /**
   * Every run touching `box` that `skip` does not own, each once. Every entry
   * of every cell under `box` is read for it, touching or not: `load.reads`
   * grows by their number.
   */
  query(box: Box, skip: number, load: PassLoad): Indexed[] {
    const stamp = ++this.stamp;
    const out: Indexed[] = [];
    const cells = this.cells;
    // The cells in the order of `forCells`, each list in the order it was filled.
    const x1 = floor(box.x1 / CELL);
    const y0 = floor(box.y0 / CELL);
    const y1 = floor(box.y1 / CELL);
    for (let gx = floor(box.x0 / CELL); gx <= x1; gx++) {
      for (let gy = y0; gy <= y1; gy++) {
        const list = cells.get(gx * 1048576 + gy);
        if (!list) continue;
        load.reads += list.length;
        for (let n = 0; n < list.length; n++) {
          const item = list[n];
          if (item.seen === stamp || item.owner === skip) continue;
          item.seen = stamp;
          if (touches(item, box)) out.push(item);
        }
      }
    }
    return out;
  }
}

function forCells(box: Box, visit: (key: number) => void): void {
  const x1 = floor(box.x1 / CELL);
  const y1 = floor(box.y1 / CELL);
  for (let gx = floor(box.x0 / CELL); gx <= x1; gx++) {
    for (let gy = floor(box.y0 / CELL); gy <= y1; gy++) visit(gx * 1048576 + gy);
  }
}

/**
 * The entries `runs` take in an index: the cells `forCells` visits for each,
 * counted and not visited. Infinite or not a number when a coordinate is not
 * finite, which `beyondPass` takes for beyond the pass.
 */
function cellsOf(runs: Run[]): number {
  let n = 0;
  for (const run of runs) {
    const box = boxOf(run, 0);
    n += (floor(box.x1 / CELL) - floor(box.x0 / CELL) + 1) * (floor(box.y1 / CELL) - floor(box.y0 / CELL) + 1);
  }
  return n;
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
    if (abs(a.y - b.y) < 0.01 && abs(a.x - b.x) >= 0.01) out.push({ h: true, c: a.y, a: min(a.x, b.x), b: max(a.x, b.x) });
    else if (abs(a.x - b.x) < 0.01 && abs(a.y - b.y) >= 0.01) out.push({ h: false, c: a.x, a: min(a.y, b.y), b: max(a.y, b.y) });
  }
  return out;
}

function runsOfShape(shape: Shape): Run[] {
  return shape.c.map((_, i) => runOf(shape, shape.c, i));
}

/**
 * Run `i` of `shape` with its coordinates taken from `c`.
 *
 * The object is made with fractions in its number fields and then filled in.
 * Written as one literal, `{ h: shape.h[i], c: c[i], a: min(from, to), b:
 * max(from, to) }`, V8 can compile the stores for small integers and throw its
 * code for this function away when a coordinate is a fraction, again and
 * again, and with it the code of a function that has this one inlined
 * (`prepare`, `settle`). Some drawings whose coordinates are nearly all whole
 * numbers are slower in this form.
 */
function runOf(shape: Shape, c: number[], i: number): Run {
  const from = i === 0 ? shape.start : c[i - 1];
  const to = i === c.length - 1 ? shape.end : c[i + 1];
  const run: Run = { h: false, c: 0.5, a: 0.5, b: 0.5 };
  run.h = shape.h[i];
  run.c = c[i];
  run.a = min(from, to);
  run.b = max(from, to);
  return run;
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
    const horizontal = abs(a.y - b.y) < 0.01;
    if (!horizontal && abs(a.x - b.x) >= 0.01) return null;
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
  range[n - 1] = n === 1 ? [max(startFace[0], endFace[0]), min(startFace[1], endFace[1])] : endFace;
  const shape = {
    h,
    c,
    origin: c.slice(),
    start: h[0] ? first.x : first.y,
    end: h[n - 1] ? last.x : last.y,
    range,
    minLength: [] as number[],
    headers: [] as Rect[],
    source: route.source,
    target: route.target,
  };
  shape.minLength = c.map((_, i) => {
    const run = runOf(shape, c, i);
    return min(MIN_RUN, run.b - run.a);
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
    if (abs(pt.x - box.x) > 0.5 && abs(pt.x - box.x - box.w) > 0.5) return fixedAt;
    const m = min(PORT_MARGIN, box.h / 4);
    return [box.y + m, box.y + box.h - m];
  }
  if (abs(pt.y - box.y) > 0.5 && abs(pt.y - box.y - box.h) > 0.5) return fixedAt;
  const m = min(PORT_MARGIN, box.w / 4);
  return [box.x + m, box.x + box.w - m];
}

/** Drop repeated points and merge straight runs, so every interior point is a turn. */
function simplify(points: Point[]): Point[] {
  const out = dedupe(points);
  for (let i = out.length - 2; i >= 1; i--) {
    const a = out[i - 1];
    const b = out[i];
    const c = out[i + 1];
    const straightX = abs(a.x - b.x) < 0.01 && abs(b.x - c.x) < 0.01 && (b.y - a.y) * (c.y - b.y) > 0;
    const straightY = abs(a.y - b.y) < 0.01 && abs(b.y - c.y) < 0.01 && (b.x - a.x) * (c.x - b.x) > 0;
    if (straightX || straightY) out.splice(i, 1);
  }
  return out;
}

function dedupe(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const pt of points) {
    const prev = out[out.length - 1];
    if (prev && abs(prev.x - pt.x) < 0.01 && abs(prev.y - pt.y) < 0.01) continue;
    out.push(pt);
  }
  return out;
}

function p(x: number, y: number): Point {
  return { x: round(x), y: round(y) };
}

function round(v: number): number {
  return mathRound(v * 100) / 100;
}
