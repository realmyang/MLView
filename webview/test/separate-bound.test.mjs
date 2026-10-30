// The separation pass (`layout/separate.ts`) is a refinement with a bound: on a drawing beyond
// what it takes on, every connection keeps the route the router drew.
//
// The pass's index holds one entry for every 64 px cell a run passes through, so it grows with the
// size of the drawing, which the contract's 2,000 steps and 4,000 connections do not limit: a nest
// of 60 groups with two steps beside each inner group unfolds to a drawing more than ten million
// px tall, and with no bound the index of such a drawing, a Map with an entry for each cell, can
// hold more entries than a Map allows or take more memory than the process has. The pass's time
// grows with the cables it may move, with their length, with the strokes near them and with what
// it reads to find those: the entries of its own tables, found or not, and the boxes its card test
// reads, which under groups nested one inside the next are every one of those groups for every
// segment. `beyondPass` bounds all six: the index entries, those of them that belong to the cables
// that may move, and the number of such cables, counted before an index is built; and, counted in
// each round as it goes, the strokes found within reach, the entries read and the boxes read.
//
// Checked here:
//   - the predicate at its six limits, as a pure function, and the limits themselves;
//   - the pass on hand-made runs whose counts are exactly at a limit (it moves a cable) and one
//     past it (every cable comes back as given, the same array);
//   - documents: the nest above is routed without an error inside a 256 MB heap, and its routes
//     are exactly those of a build of the same sources with the pass taken out, while on smaller
//     documents that build draws differently (so the comparison can fail); and a small core that
//     the pass does move under 5 groups is left as routed under 100.
//
// The scenes are SYNTHETIC and the counts are of this code's own bookkeeping. A bound that fails
// shows as a thrown error, a worker out of memory or a route that differs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { Worker } from 'node:worker_threads';
import { build } from 'esbuild';
import { WEBVIEW_ROOT, rendererRegressionWorkflow } from './helpers.mjs';

const ENTRY = [
  "export { separateExceptions, beyondPass, MAX_INDEX_ENTRIES, MAX_MOVING_ENTRIES, MAX_MOVING_CABLES, MAX_NEAR_STROKES, MAX_ROUND_READS, MAX_CARD_READS } from './layout/separate.ts';",
  "export { normalizeWorkflow } from './workflow.ts';",
  "export { GraphIndex } from './layout/model.ts';",
  "export { layoutGraph } from './layout/layout.ts';",
  "export { routeEdges } from './layout/routing.ts';",
].join('\n');

/** The pass taken out: every uncertain cable keeps the points the router gave it. */
const PASS_OFF = {
  name: 'pass-off',
  setup(b) {
    b.onLoad({ filter: /[\\/]layout[\\/]separate\.ts$/ }, () => ({
      loader: 'ts',
      contents: [
        'export const MAX_INDEX_ENTRIES = 0;',
        'export const MAX_MOVING_ENTRIES = 0;',
        'export const MAX_MOVING_CABLES = 0;',
        'export const MAX_NEAR_STROKES = 0;',
        'export const MAX_ROUND_READS = 0;',
        'export const MAX_CARD_READS = 0;',
        'export const beyondPass = () => true;',
        'export function separateExceptions(_env: unknown, _fixed: unknown, moving: Array<{ points: unknown }>) { return moving.map((route) => route.points); }',
      ].join('\n'),
    }));
  },
};

/** The layout sources as one ES module's text (nothing touches the DOM on import). */
async function bundle(plugins = []) {
  const result = await build({
    stdin: { contents: ENTRY, resolveDir: join(WEBVIEW_ROOT, 'src'), loader: 'ts', sourcefile: 'separate-bound-entry.ts' },
    bundle: true, format: 'esm', platform: 'neutral', write: false, logLevel: 'silent', plugins,
  });
  return result.outputFiles[0].text;
}
const asModule = (code) => import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

const realCode = await bundle();
const real = await asModule(realCode);
const passOff = await asModule(await bundle([PASS_OFF]));
const { separateExceptions, beyondPass, MAX_INDEX_ENTRIES, MAX_MOVING_ENTRIES, MAX_MOVING_CABLES, MAX_NEAR_STROKES, MAX_ROUND_READS, MAX_CARD_READS } = real;

/* ── the predicate ────────────────────────────────────────────────────────────────────────── */

test('the six limits of the pass are the values written out here', () => {
  // The limits of `layout/separate.ts`, written out again, so that changing one, which changes
  // what the viewer draws on large documents, takes a change to this test as well.
  assert.equal(MAX_INDEX_ENTRIES, 2000000);
  assert.equal(MAX_MOVING_ENTRIES, 200000);
  assert.equal(MAX_MOVING_CABLES, 2000);
  assert.equal(MAX_NEAR_STROKES, 2500000);
  assert.equal(MAX_ROUND_READS, 100000000);
  assert.equal(MAX_CARD_READS, 10000000);
});

const COUNTS = ['entries', 'moving', 'cables', 'strokes', 'reads', 'cards'];
const NOTHING = { entries: 0, moving: 0, cables: 0, strokes: 0, reads: 0, cards: 0 };

test('beyondPass: at every limit the pass still runs, one past any of them it does not', () => {
  const at = { entries: MAX_INDEX_ENTRIES, moving: MAX_MOVING_ENTRIES, cables: MAX_MOVING_CABLES, strokes: MAX_NEAR_STROKES, reads: MAX_ROUND_READS, cards: MAX_CARD_READS };
  assert.equal(beyondPass(NOTHING), false);
  assert.equal(beyondPass({ entries: MAX_INDEX_ENTRIES - 1, moving: MAX_MOVING_ENTRIES - 1, cables: MAX_MOVING_CABLES - 1, strokes: MAX_NEAR_STROKES - 1, reads: MAX_ROUND_READS - 1, cards: MAX_CARD_READS - 1 }), false);
  assert.equal(beyondPass(at), false);
  for (const key of COUNTS) {
    assert.equal(beyondPass({ ...NOTHING, [key]: at[key] }), false, key + ' at its limit');
    assert.equal(beyondPass({ ...NOTHING, [key]: at[key] + 1 }), true, key + ' one past its limit');
    assert.equal(beyondPass({ ...at, [key]: at[key] + 1 }), true, key + ' one past its limit, the others at theirs');
    assert.equal(beyondPass({ ...at, [key]: 0 }), false, key + ' at nothing, the others at their limits');
  }
  assert.equal(beyondPass({ ...NOTHING, entries: 133306728 * 44 }), true);
});

test('beyondPass: a count that is not a number is beyond the pass', () => {
  // A coordinate that is not finite makes the count of entries NaN or Infinity.
  for (const key of COUNTS) {
    assert.equal(beyondPass({ ...NOTHING, [key]: NaN }), true, key + ' NaN');
    assert.equal(beyondPass({ ...NOTHING, [key]: Infinity }), true, key + ' Infinity');
    assert.equal(beyondPass({ ...NOTHING, [key]: undefined }), true, key + ' missing');
  }
  assert.equal(beyondPass({ ...NOTHING, entries: -Infinity }), false);
});

/* ── the pass on hand-made runs ───────────────────────────────────────────────────────────── */

const CELL = 64;
const pt = (x, y) => ({ x, y });
/** The entries a polyline takes in the index, written out again: one per cell each run passes through. */
const entriesOf = (points) => {
  let n = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const lo = a.y === b.y ? Math.min(a.x, b.x) : Math.min(a.y, b.y);
    const hi = a.y === b.y ? Math.max(a.x, b.x) : Math.max(a.y, b.y);
    n += Math.floor(hi / CELL) - Math.floor(lo / CELL) + 1;
  }
  return n;
};
const env = (extra = {}) => ({ boxes: new Map(), hits: () => 0, cardsRead: () => 0, headers: [], outlines: [], bandsLeft: 0, width: 1e7, height: 1e7, ...extra });

/**
 * Two uncertain cables drawn on one another, far from everything else: a step right, 200 px down,
 * a step right. Their ends are on no card, so only the middle run can move, and where the pass
 * runs it moves one of them off the other.
 */
const witness = () => ['a', 'b'].map((id) => ({ source: id + '-from', target: id + '-to', points: [pt(1000, 500), pt(1200, 500), pt(1200, 700), pt(1400, 700)] }));
const sameArrays = (out, moving) => out.length === moving.length && out.every((points, k) => points === moving[k].points);

test('the witness: where the pass runs, a cable drawn on another moves off it', () => {
  const moving = witness();
  const out = separateExceptions(env(), [], moving);
  assert.equal(sameArrays(out, moving), false, 'neither cable moved');
  const xs = out.map((points) => points[1].x);
  assert.ok(Math.abs(xs[0] - xs[1]) >= 8, 'the middle runs are 8 px apart or more: ' + xs.join(' and '));
  for (const points of out) assert.deepEqual([points[0], points[points.length - 1]], [pt(1000, 500), pt(1400, 700)], 'the ends stay');
  // Drawn the other way, last point first, its runs go right to left and upwards: it moves too.
  const back = witness().map((route) => ({ ...route, points: route.points.slice().reverse() }));
  assert.equal(sameArrays(separateExceptions(env(), [], back), back), false, 'drawn backwards, neither cable moved');
});

test('index entries: exactly at the limit the pass runs, one entry more and every cable is as routed', () => {
  // The entries are made of strokes far from the witness, all on one line, so that two million of
  // them share a thousand cells and cost little: 1,000 cells each, and one last stroke for the rest.
  // One more is 10 px long and lies across a cell border: it takes two entries, because an entry
  // is a cell a stroke passes through, however little of the stroke lies in it.
  const strokes = (cells) => {
    const out = [[pt(60, 900000), pt(70, 900000)]];
    for (let left = cells - 2; left > 0; left -= 1000) out.push([pt(0, 900000), pt(CELL * (Math.min(left, 1000) - 1) + 1, 900000)]);
    return out;
  };
  const moving = witness();
  const own = moving.reduce((n, route) => n + entriesOf(route.points), 0);
  assert.equal(own, 24, 'the witness takes 12 entries a cable');

  const at = strokes(MAX_INDEX_ENTRIES - own);
  assert.equal(at.reduce((n, points) => n + entriesOf(points), 0) + own, MAX_INDEX_ENTRIES);
  assert.equal(sameArrays(separateExceptions(env(), at, moving), moving), false, 'at the limit the pass moved no cable');

  const past = strokes(MAX_INDEX_ENTRIES - own + 1);
  assert.equal(past.reduce((n, points) => n + entriesOf(points), 0) + own, MAX_INDEX_ENTRIES + 1);
  assert.equal(sameArrays(separateExceptions(env(), past, moving), moving), true, 'one entry past the limit a cable was moved');
});

test('index entries: a card, group or lane side counts twice, and a run that is not finite is beyond the pass', () => {
  // A frame 64 px wide: its two long sides take `cells` entries each and its two short sides 2
  // each, in the index and again in the index of the sides, so 4 * (cells + 2) in all. The frames
  // lie on one another, far from the witness, so that they share their cells.
  const frame = (cells) => ({ x: 0, y: 900000, w: CELL, h: CELL * (cells - 1) });
  const frames = (quarter) => {
    const out = [];
    for (let left = quarter; left > 0; left -= 1000) out.push(frame(Math.min(left, 1000) - 2));
    return out;
  };
  const moving = witness();
  const quarter = (MAX_INDEX_ENTRIES - 24) / 4;
  assert.ok(Number.isInteger(quarter) && quarter % 1000 > 2, 'the frames can be made to land on the limit');
  assert.equal(sameArrays(separateExceptions(env({ outlines: frames(quarter) }), [], moving), moving), false, 'at the limit the pass moved no cable');
  assert.equal(sameArrays(separateExceptions(env({ outlines: frames(quarter + 1) }), [], moving), moving), true, 'four entries past the limit a cable was moved');

  // A coordinate that is not finite: an index of such a run would never be finished.
  for (const bad of [Infinity, -Infinity]) {
    const out = separateExceptions(env(), [[pt(0, 900000), pt(bad, 900000)]], moving);
    assert.equal(sameArrays(out, moving), true, 'a stroke to x = ' + bad + ' did not stop the pass');
  }
  for (const bad of [Infinity, NaN]) {
    const out = separateExceptions(env({ outlines: [{ x: 0, y: 900000, w: CELL, h: bad }] }), [], moving);
    assert.equal(sameArrays(out, moving), true, 'a frame of height ' + bad + ' did not stop the pass');
  }
});

test('entries of the cables that may move: exactly at the limit the pass runs, one more and every cable is as routed', () => {
  // Uncertain cables far from the witness and 1,000 px from one another, so that none finds a
  // stroke: straight lines of 1,000 cells each, and one last line for the rest.
  const lines = (cells) => {
    const out = [];
    for (let left = cells, row = 0; left > 0; left -= 1000, row++) out.push([pt(0, 900000 + 1000 * row), pt(CELL * (Math.min(left, 1000) - 1) + 1, 900000 + 1000 * row)]);
    return out;
  };
  const cables = (cells) => witness().concat(lines(cells).map((points, i) => ({ source: 'ls' + i, target: 'lt' + i, points })));
  const count = (moving) => moving.reduce((n, route) => n + entriesOf(route.points), 0);

  const at = cables(MAX_MOVING_ENTRIES - 24);
  assert.equal(count(at), MAX_MOVING_ENTRIES);
  const out = separateExceptions(env(), [], at);
  assert.equal(sameArrays(out.slice(0, 2), at.slice(0, 2)), false, 'at the limit the pass moved no cable');
  assert.equal(sameArrays(out.slice(2), at.slice(2)), true, 'a straight line moved');

  const past = cables(MAX_MOVING_ENTRIES - 24 + 1);
  assert.equal(count(past), MAX_MOVING_ENTRIES + 1);
  assert.equal(sameArrays(separateExceptions(env(), [], past), past), true, 'one entry past the limit a cable was moved');

  // A cable the pass cannot move is counted like the others. One that ends on a slant has no
  // shape the pass can slide, and the 100 cells under its straight run are entries all the same:
  // with 100 fewer under the lines the count is exactly the limit, and with one cell more under
  // that run it is one past it.
  const stuck = (cells) => ({ source: 'stuck-from', target: 'stuck-to', points: [pt(0, 700000), pt(CELL * (cells - 1) + 1, 700000), pt(CELL * (cells - 1) + 31, 700030)] });
  const held = cables(MAX_MOVING_ENTRIES - 24 - 100).concat([stuck(100)]);
  assert.equal(count(held.slice(0, -1)) + entriesOf(stuck(100).points.slice(0, 2)), MAX_MOVING_ENTRIES);
  const heldOut = separateExceptions(env(), [], held);
  assert.equal(sameArrays(heldOut.slice(0, 2), held.slice(0, 2)), false, 'at the limit, a cable that cannot move among them, the pass moved no cable');
  assert.equal(sameArrays(heldOut.slice(2), held.slice(2)), true, 'a straight line moved, or the cable that cannot');
  const heldPast = cables(MAX_MOVING_ENTRIES - 24 - 100).concat([stuck(101)]);
  assert.equal(sameArrays(separateExceptions(env(), [], heldPast), heldPast), true, 'the entries of a cable that cannot move were not counted');

  // The same lines as strokes that stay, nine times over: only what may move counts here.
  const still = witness();
  const fixed = lines(MAX_MOVING_ENTRIES - 24 + 1);
  for (let n = 1; n < 9; n++) for (const points of lines(MAX_MOVING_ENTRIES)) fixed.push(points);
  assert.ok(fixed.reduce((n, points) => n + entriesOf(points), 0) + 24 < MAX_INDEX_ENTRIES);
  assert.equal(sameArrays(separateExceptions(env(), fixed, still), still), false, 'strokes that stay were counted as cables that may move');
});

test('cables that may move: exactly at the limit the pass runs, one more and every cable is as routed', () => {
  // Short uncertain lines far from the witness and 1,000 px from one another, so that none finds a
  // stroke and each takes one entry.
  const cables = (n) => {
    const out = witness();
    for (let i = 0; out.length < n; i++) out.push({ source: 'cs' + i, target: 'ct' + i, points: [pt(4, 900000 + 1000 * i), pt(40, 900000 + 1000 * i)] });
    return out;
  };
  const at = cables(MAX_MOVING_CABLES);
  assert.equal(at.length, MAX_MOVING_CABLES);
  const out = separateExceptions(env(), [], at);
  assert.equal(sameArrays(out.slice(0, 2), at.slice(0, 2)), false, 'at the limit the pass moved no cable');
  assert.equal(sameArrays(out.slice(2), at.slice(2)), true, 'a line with nothing near it moved');

  const past = cables(MAX_MOVING_CABLES + 1);
  assert.equal(sameArrays(separateExceptions(env(), [], past), past), true, 'one cable past the limit a cable was moved');
  // A cable the pass cannot move, here one that is not orthogonal, is a cable all the same.
  const slanted = cables(MAX_MOVING_CABLES).concat([{ source: 'slant-from', target: 'slant-to', points: [pt(4, 800000), pt(40, 800030)] }]);
  assert.equal(sameArrays(separateExceptions(env(), [], slanted), slanted), true, 'a cable that cannot move was not counted');

  // Strokes that stay are not cables that may move, however many there are.
  const still = witness();
  const fixed = cables(3 * MAX_MOVING_CABLES).slice(2).map((route) => route.points);
  assert.equal(sameArrays(separateExceptions(env(), fixed, still), still), false, 'strokes that stay were counted as cables that may move');
});

test('strokes within reach: exactly at the limit the pass runs, one stroke more and it gives up what it moved', () => {
  // 1,000 uncertain cables, straight lines 10 px apart: each is within reach (48 px) of the four
  // above and the four below it, but not near them (8 px), so none has anything to move off. Every
  // one is crossed by `columns` fixed strokes, 1 px apart. Their ends are on no card, so none can move.
  const CABLES = 1000;
  const Y0 = 20000;
  const scene = (columns, more, watchers = []) => {
    const fixed = [];
    for (let v = 0; v < columns; v++) fixed.push([pt(100 + v, Y0 - 100), pt(100 + v, Y0 + 10 * (CABLES - 1) + 100)]);
    // One more stroke, crossing the reach of the first `more` cables and of no other.
    if (more > 0) fixed.push([pt(50, Y0 - 100), pt(50, Y0 + 10 * (more - 1) - 43)]);
    const moving = watchers.concat(witness());
    for (let i = 0; i < CABLES; i++) moving.push({ source: 's' + i, target: 't' + i, points: [pt(0, Y0 + 10 * i), pt(columns + 200, Y0 + 10 * i)] });
    return { fixed, moving };
  };
  // A round finds: 7 strokes for each cable of the witness (the other's three runs, from each of
  // its own three: 2 + 3 + 2); the 8 neighbours of each line, less the 20 the first and last four
  // lack; and every column once from every line.
  const others = 14 + 8 * CABLES - 20;
  const columns = Math.floor((MAX_NEAR_STROKES - others) / CABLES);
  const more = MAX_NEAR_STROKES - others - columns * CABLES;
  assert.ok(columns > 100 && more >= 0 && more < CABLES, columns + ' columns and ' + more + ' more');

  const at = scene(columns, more);
  const out = separateExceptions(env(), at.fixed, at.moving);
  assert.equal(sameArrays(out.slice(0, 2), at.moving.slice(0, 2)), false, 'at the limit the pass moved no cable');
  assert.equal(sameArrays(out.slice(2), at.moving.slice(2)), true, 'a straight line moved');

  // The witness comes first, so the pass has moved it before the count passes the limit.
  const past = scene(columns, more + 1);
  assert.equal(sameArrays(separateExceptions(env(), past.fixed, past.moving), past.moving), true, 'one stroke past the limit a cable was moved');

  // A side of a card, group or lane found within reach is a stroke found, like any other. A frame
  // of no width stands 60 px from the lines' left ends, from 20 to 10 px above the first line:
  // its upper side is within reach of the first three lines, its lower side and each of its two
  // upright sides of the first four. A round finds those 15 on top of the limit, so no cable moves.
  const SIDES = 3 + 4 + 4 + 4;
  const framed = () => env({ outlines: [{ x: 60, y: Y0 - 20, w: 0, h: 10 }] });
  assert.equal(sameArrays(separateExceptions(framed(), at.fixed, at.moving), at.moving), true, 'the sides of a frame within reach were not counted and a cable was moved');
  // With 15 strokes fewer the sides bring the count to the limit exactly, and the pass runs: one
  // column less, which is 1,000 fewer, and the one more stroke across the reach of 985 more lines.
  assert.ok(more < SIDES);
  const sided = scene(columns - 1, more + CABLES - SIDES);
  assert.equal(sameArrays(separateExceptions(framed(), sided.fixed, sided.moving).slice(0, 2), sided.moving.slice(0, 2)), false, 'exactly at the limit, 15 sides of a frame among the strokes, the pass moved no cable');
  const sidedPast = scene(columns - 1, more + CABLES - SIDES + 1);
  assert.equal(sameArrays(separateExceptions(framed(), sidedPast.fixed, sidedPast.moving), sidedPast.moving), true, 'one stroke past the limit, 15 sides of a frame among them, a cable was moved');

  // Each round is counted. Two short uncertain lines stand 54 px either side of the witness's
  // middle runs: out of reach of them as routed, within reach of one that has moved 6 px or more
  // towards it. Their turn comes before the witness's, so the first round finds what it found
  // above, exactly the limit, and the second finds the moved run as well.
  const watchers = [1146, 1254].map((x) => ({ source: 'w' + x, target: 'v' + x, points: [pt(x, 590), pt(x, 640)] }));
  const twice = scene(columns, more, watchers);
  assert.equal(sameArrays(separateExceptions(env(), twice.fixed, twice.moving), twice.moving), true, 'the second round went past the limit and a cable was moved');
  // With two strokes fewer the second round stays within the limit, and the pass runs.
  assert.ok(more >= 2);
  const within = scene(columns, more - 2, watchers);
  const kept = separateExceptions(env(), within.fixed, within.moving);
  assert.equal(sameArrays(kept.slice(2, 4), within.moving.slice(2, 4)), false, 'two strokes under the limit the pass moved no cable');

  // And the first round is counted, not only the last. One short uncertain line stands 46 px left
  // of the witness's middle runs: within reach of both as routed, and of one only once the other
  // has moved away. With three strokes fewer, the first round finds one stroke more than the
  // limit and the second exactly the limit, so a pass that looked at the end only would run.
  const leaver = [{ source: 'w1154', target: 'v1154', points: [pt(1154, 590), pt(1154, 640)] }];
  assert.ok(more >= 4);
  const first = scene(columns, more - 3, leaver);
  assert.equal(sameArrays(separateExceptions(env(), first.fixed, first.moving), first.moving), true, 'the first round went one stroke past the limit, the second did not, and a cable was moved');
  // One stroke fewer still and both rounds are within the limit.
  const neither = scene(columns, more - 4, leaver);
  assert.equal(sameArrays(separateExceptions(env(), neither.fixed, neither.moving), neither.moving), false, 'with both rounds within the limit the pass moved no cable');
});

test('entries read in a round: exactly at the limit the pass runs, one more and every cable is as routed', () => {
  // A query reads every entry of every cell under the reach of a run, and taking a cable out of
  // the index searches every cell it lies in, whether or not anything there is within reach. The
  // strokes found do not count that: 1,000 uncertain lines 2 px long, drawn on one another in one
  // cell, with tens of thousands of strokes in that cell that stand 9 px past their reach. The
  // lines' ends are on no card, so none can move; each finds the 999 others and nothing else.
  const LINES = 1000;
  const ROW = 900000; // 32 px into its cell: a line's reach takes in the cells above and below, which are empty
  const lines = Array.from({ length: LINES }, (_, i) => ({ source: 'rs' + i, target: 'rt' + i, points: [pt(1, ROW), pt(3, ROW)] }));
  const beside = (n) => Array.from({ length: n }, () => [pt(20, ROW), pt(60, ROW)]);
  // One more such line far from the others, 8 px into its cell, so that its reach takes in the
  // cell above it: a stroke there, past its reach, is read once a round, by that line's query.
  const LONE = 800008;
  const lone = { source: 'lone-from', target: 'lone-to', points: [pt(1, LONE), pt(3, LONE)] };
  const above = (n) => Array.from({ length: n }, () => [pt(20, LONE - 40), pt(60, LONE - 40)]);
  // Strokes that no query reaches and no cable lies on are not read at all.
  const elsewhere = Array.from({ length: 1000 }, (_, i) => [pt(5000, ROW + 1000 + i), pt(5040, ROW + 1000 + i)]);
  // A cable reads while it settles too: the sides of cards, groups and lanes in the cells under
  // the runs a move changes, and the headers its horizontal runs can reach, once for where the
  // runs stand and once for each place tried. The witness is given both to read, and neither is
  // in its way. Three flat frames lie in the cell below its last run, 60 px under the run and out
  // of every reach: four sides each, so 12 entries of that cell in the index and 12 in the index
  // of the sides, which a look-up 4 px around the second or the third run reads. And one header
  // has its strip end 40 px above the last run, within the 45 px a header is kept for.
  const frames = Array.from({ length: 3 }, () => ({ x: 1160, y: 760, w: 40, h: 0 }));
  const over = { x: 1250, y: 630, w: 100, h: 30 };
  const scene = (inCell, aboveLone, headers = []) => ({
    env: env({ outlines: frames, headers: [over].concat(headers) }),
    fixed: beside(inCell - LINES).concat(above(aboveLone), elsewhere),
    moving: witness().concat([lone], lines),
  });
  // What a round has read when its last cable's turn comes, the most that is compared. The
  // witness reads more in the first round than in the second, so the first is the one at the
  // limit:
  //   the witness looked up and taken out, 180: each of its two cables reads 60 entries for its
  //     three runs (36 in the cells under their reach, which hold both cables' runs, and the
  //     frames' 12 for the second run and for the third) and searches 30 to be taken out;
  //   the witness settling, 141. A run with the other cable on it is read where it stands, with
  //     the neighbours a move of it changes: 12 sides for the second run and 12 for the third,
  //     and the header for the first run and for the third. That is 13 for the first run (it
  //     and the second), 26 for the second (all three) and 25 for the third. The first cable
  //     reads the three, the second run again at the place it moves to and, a run having moved,
  //     the first once more: 13 + 26 + 26 + 25 + 13. The second cable's second run is clear of
  //     the first's by then, so it reads its first and its third: 13 + 25;
  //   the lone line: its own entry, the strokes above it, and its own entry again to be taken out;
  //   each line: its cell for its query and again to be taken out, less the last line's taking out.
  // In the second round the two second runs stand 8 px apart, neither is read, and each cable
  // reads 13 + 25: 65 fewer.
  const WITNESS = 2 * (60 + 30) + (13 + 26 + 26 + 25 + 13) + (13 + 25);
  assert.equal(WITNESS, 321);
  const perEntry = 2 * LINES - 1;
  const inCell = Math.floor((MAX_ROUND_READS - WITNESS - 2) / perEntry);
  const aboveLone = MAX_ROUND_READS - WITNESS - 2 - perEntry * inCell;
  assert.ok(inCell > 10 * LINES && aboveLone >= 0 && aboveLone < perEntry, inCell + ' entries in the cell and ' + aboveLone + ' above the lone line');
  assert.equal(WITNESS + (aboveLone + 2) + perEntry * inCell, MAX_ROUND_READS);
  // Far fewer strokes are found than read: the lines find one another, and the witness itself.
  assert.ok(LINES * (LINES - 1) + 14 < MAX_NEAR_STROKES / 2);

  const moved = (s) => {
    const out = separateExceptions(s.env, s.fixed, s.moving);
    if (sameArrays(out, s.moving)) return 'none';
    return sameArrays(out.slice(2), s.moving.slice(2)) ? 'the witness' : 'more than the witness';
  };
  assert.equal(moved(scene(inCell, aboveLone)), 'the witness', 'exactly at the limit');
  assert.equal(moved(scene(inCell, aboveLone + 1)), 'none', 'one entry read past the limit');

  // A header a run is read against is an entry read too. Headers level with the lines, far to
  // their right: every line is read against each of them once a round, when its turn comes.
  // `perEntry` headers cost the lines before the last one what LINES - 1 entries in the cell cost.
  const headers = (n) => Array.from({ length: n }, () => ({ x: 5000, y: ROW - 10, w: 100, h: 20 }));
  assert.equal(moved(scene(inCell - (LINES - 1), aboveLone, headers(perEntry))), 'the witness', 'exactly at the limit, with headers');
  assert.equal(moved(scene(inCell - (LINES - 1), aboveLone, headers(perEntry + 1))), 'none', 'one header past the limit');

  // The second round is counted too, from nothing, with all it reads. In the scenes above the
  // first round reads the most, so nothing there looks at the second; here the second alone
  // passes the limit, and a pass that left its count out, or part of it, would move the witness.
  //
  // The witness stands 44 px further left, its middle runs at x = 1156, 4 px inside a column of
  // cells. The first cable's moves 40 px left, as far as it may, into the next column, and one
  // of the four cells it lies in there holds NEXT short strokes, 22 px left of it and out of
  // every reach. That cell is under the reach of a middle run wherever the first cable stands,
  // so the look-ups read it in both rounds; taking a cable out searches the cells the cable
  // lies in, so only the second round searches it, when the first cable is taken out from
  // where it moved to. And the witness reads while it settles, in both rounds: it has the header
  // and the three frames of the scenes above, the header 44 px further left as the cables are,
  // so that its strip ends 40 px above their last run, and the frames where they were, in the
  // cell below that run and in the column the middle runs are routed in. What the witness reads:
  //   a cable's three look-ups, 62 + NEXT in either round: 38 for the two cables' own entries
  //     in the cells under its reaches (14 + 14 + 10 before the first cable has moved,
  //     13 + 14 + 11 after), the frames' 12 for the second run and for the third, and the
  //     strokes once, for its middle run;
  //   in the first round the first cable taken out from where it was routed, 32 (12 + 11 + 9
  //     for its three runs, every one of their cells holding both cables), and the second,
  //     which by then does not share every cell with the first, 25 (11 + 6 + 8);
  //   in the second round the first cable taken out from where it moved to, 25 + NEXT
  //     (9, 6 + NEXT and 10), and the second, 25 again;
  //   while it settles, a run is read with the neighbours a move of it changes: the header once
  //     for each horizontal run among them, and the frames' 12 sides for a last run and for a
  //     middle run at x = 1156, none for a middle run at x = 1116, in the next column. So a
  //     first, a second and a third run read 13, 26 and 25 while their cable's middle run is
  //     where it was routed, and 1, 14 and 13 once it has moved;
  //   settling in the first round, 105. The first cable reads its three runs, the second one
  //     where it stands and again at the place it moves to, and, a run having moved, the first
  //     once more: 13 + 26 + 14 + 13 + 1. The second cable's middle run is clear of the first's
  //     by then, so it reads its first and its third: 13 + 25;
  //   settling in the second round, 52. The middle runs stand 40 px apart and neither is read:
  //     the first cable reads 1 + 13 and the second 13 + 25.
  // So the second round reads NEXT - 60 more than the first.
  //
  // The lines read while they settle too, once a round each: LEVEL headers level with them,
  // and the sides in their cell, where three flat frames lie beside them like the strokes
  // (four sides each, which are entries of the cell in the index as well and are counted among
  // its `inCell`).
  const NEXT = 200;
  const LEVEL = 10;
  const left = () => ['a', 'b'].map((id) => ({ source: id + '-from', target: id + '-to', points: [pt(956, 500), pt(1156, 500), pt(1156, 700), pt(1356, 700)] }));
  const nextColumn = Array.from({ length: NEXT }, () => [pt(1092, 600), pt(1094, 600)]);
  const byLines = Array.from({ length: 3 }, () => ({ x: 20, y: ROW, w: 40, h: 0 }));
  const overLeft = { x: 1206, y: 630, w: 100, h: 30 };
  const second = (inCell, aboveLone) => ({
    env: env({ outlines: byLines.concat(frames), headers: headers(LEVEL).concat([overLeft]) }),
    fixed: beside(inCell - LINES - 4 * byLines.length).concat(above(aboveLone), nextColumn, elsewhere),
    moving: left().concat([lone], lines),
  });
  const LOOKUPS = 38 + 12 + 12 + NEXT;
  const FIRST = 2 * LOOKUPS + 32 + 25 + (13 + 26 + 14 + 13 + 1) + (13 + 25);
  const SECOND = 2 * LOOKUPS + (25 + NEXT) + 25 + (1 + 13) + (13 + 25);
  assert.deepEqual([FIRST, SECOND], [686, 826]);
  // A line before the last reads its cell twice and, settling, the headers and the frames' sides.
  const perLine = LEVEL + 4 * byLines.length;
  const rest = MAX_ROUND_READS - SECOND - 2 - (LINES - 1) * perLine;
  const inCell2 = Math.floor(rest / perEntry);
  const aboveLone2 = rest - perEntry * inCell2;
  assert.ok(inCell2 > 10 * LINES && aboveLone2 >= 0 && aboveLone2 < perEntry, inCell2 + ' entries in the cell and ' + aboveLone2 + ' above the lone line');
  assert.equal(SECOND + (aboveLone2 + 2) + perEntry * inCell2 + (LINES - 1) * perLine, MAX_ROUND_READS);
  // One stroke more above the lone line puts the second round one past the limit and leaves the
  // first NEXT - 61 under it.
  assert.ok(SECOND - FIRST === NEXT - 60 && NEXT - 61 > 0);

  // Where the count rests on the witness: the first cable's middle run ends in the next column
  // (x under 1152) and the second's stays. A scene with little in the lines' cell shows it.
  const few = second(2 * LINES, 0);
  assert.deepEqual(separateExceptions(few.env, few.fixed, few.moving).slice(0, 2).map((points) => points[1].x), [1116, 1156]);
  assert.equal(moved(second(inCell2, aboveLone2)), 'the witness', 'the second round exactly at the limit');
  assert.equal(moved(second(inCell2, aboveLone2 + 1)), 'none', 'the second round one entry read past the limit, the first within it');
});

test('boxes read for the card test: exactly at the limit the pass runs, one more and every cable is as routed', () => {
  // The pass asks its caller how many boxes the card test has read so far (`cardsRead`) as each
  // round starts and before each cable settles: six times for the two cables of the witness.
  // Here the answers are given, so the count is exact; that the router's count is of the boxes
  // its grid reads is checked on a document below and in `box-grid.test.mjs`.
  const M = MAX_CARD_READS;
  const run = (answers) => {
    let asked = 0;
    const moving = witness();
    const out = separateExceptions(env({ cardsRead: () => answers[Math.min(asked++, answers.length - 1)] }), [], moving);
    return { asRouted: sameArrays(out, moving), asked };
  };
  assert.deepEqual(run([0, 0, M, M, M, M]), { asRouted: false, asked: 6 }, 'exactly at the limit before the second cable settles');
  // The first cable has moved by then, and is given up.
  assert.deepEqual(run([0, 0, M + 1]), { asRouted: true, asked: 3 }, 'one box past the limit');
  assert.deepEqual(run([0, M + 1]), { asRouted: true, asked: 2 }, 'past the limit before the first cable settles');
  // What was read before the pass began is not the pass's.
  const B = 7e9;
  assert.equal(run([B, B, B + M, B + M, B + M, B + M]).asRouted, false, 'boxes read before the pass were counted');
  assert.equal(run([B, B, B + M + 1]).asRouted, true);
  // Each round is counted from nothing.
  assert.deepEqual(run([0, 0, M, M, M, 2 * M]), { asRouted: false, asked: 6 }, 'the second round, at the limit, was counted on from the first');
  assert.deepEqual(run([0, 0, M, M, M, 2 * M + 1]), { asRouted: true, asked: 6 }, 'the second round went one box past the limit and a cable was moved');
});

/* ── a document ───────────────────────────────────────────────────────────────────────────── */

/**
 * `levels` groups nested one inside the next in the first phase, each holding two steps beside the
 * next group, the first step feeding that group and the second step; ten steps in a second phase;
 * and connections between the two phases and between levels, every third one inferred or unresolved.
 */
function nest(levels) {
  const nodes = [];
  const edges = [];
  const step = (phase, extra) => {
    nodes.push({ id: 'n' + nodes.length, label: 'Step ' + nodes.length, phase, ...extra, basis: 'observed', evidence: ['ev'] });
    return nodes[nodes.length - 1].id;
  };
  const link = (source, target, kind) => {
    const basis = edges.length % 3 ? 'observed' : edges.length % 2 ? 'inferred' : 'unresolved';
    edges.push({ id: 'c' + edges.length, source, target, label: kind + ' ' + edges.length, kind, basis, evidence: ['ev'] });
  };
  const groups = [];
  const leaves = [];
  for (let level = 0; level < levels; level++) {
    groups.push(step('p0', { kind: 'group', ...(level ? { parent: groups[level - 1] } : {}) }));
    leaves.push([step('p0', { parent: groups[level] }), step('p0', { parent: groups[level] })]);
  }
  const side = Array.from({ length: 10 }, () => step('p1', {}));
  for (let level = 0; level + 1 < levels; level++) link(leaves[level][0], groups[level + 1], 'call');
  for (let level = 0; level < levels; level++) link(leaves[level][0], leaves[level][1], 'data');
  for (let i = 1; i < side.length; i++) link(side[i - 1], side[i], 'call');
  for (let j = 0; j < 20; j++) link(leaves[(7 * j) % (levels - 12)][j % 2], leaves[((7 * j) % (levels - 12)) + 1 + (j % 11)][(j + 1) % 2], 'data');
  for (let j = 0; j < 10; j++) link(side[j], leaves[(11 * j + 3) % levels][j % 2], 'config');
  for (let j = 0; j < 5; j++) link(leaves[(13 * j + 5) % levels][j % 2], side[(3 * j) % side.length], 'control');
  return {
    workflowVersion: '1.0', title: 'A nest of ' + levels + ' groups',
    producer: { kind: 'host-llm', host: 'unknown', model: 'fixture' }, revision: { id: 'nest-' + levels },
    request: { question: 'Is a drawing beyond the pass still routed?', scope: 'synthetic' },
    phases: [{ id: 'p0', label: 'Nested groups' }, { id: 'p1', label: 'Beside them' }],
    nodes, edges, findings: [],
    evidence: [{ id: 'ev', file: 'src/steps.py', line: 1, endLine: 1, quote: 'step()' }],
    coverage: { status: 'partial', summary: 'Synthetic shape only.', inspectedFiles: [], limitations: [] },
  };
}

/** Lay `doc` out with every group unfolded and route it: the frame's height and every route. */
function routed(mod, doc) {
  const index = new mod.GraphIndex(mod.normalizeWorkflow(JSON.parse(JSON.stringify(doc))));
  const frame = mod.layoutGraph(index, new Set());
  const routes = mod.routeEdges(index, frame, new Set());
  return {
    height: frame.height,
    uncertain: routes.filter((r) => r.notObserved).length,
    routes: routes.map((r) => [r.id, r.points.map((p) => p.x + ',' + p.y).join(' '), r.d, r.mid.x + ',' + r.mid.y, r.midAngle, r.trunk ? r.trunk.key + '#' + r.trunk.index : '']),
  };
}

/** `routed` with the real build in a worker whose heap is capped, so that a pass with no bound fails here and not the machine. */
function routedInWorker(doc, heapMb) {
  const source = [
    "const { parentPort, workerData } = require('node:worker_threads');",
    "import('data:text/javascript;base64,' + Buffer.from(workerData.code).toString('base64')).then((mod) => {",
    '  const routed = ' + routed.toString() + ';',
    '  parentPort.postMessage(routed(mod, workerData.doc));',
    '}).catch((err) => { throw err; });',
  ].join('\n');
  return new Promise((resolve, reject) => {
    const worker = new Worker(source, { eval: true, workerData: { code: realCode, doc }, resourceLimits: { maxOldGenerationSizeMb: heapMb } });
    worker.once('message', resolve);
    worker.once('error', reject);
    worker.once('exit', (code) => reject(new Error('the worker left with code ' + code + ' and no routes')));
  });
}

test('a nest of 60 groups and 190 steps, unfolded, is routed without an error and as the router drew it', async () => {
  const doc = nest(60);
  assert.equal(doc.nodes.length, 190);
  const expected = routed(passOff, doc);
  // What makes this drawing one the pass cannot take on. If the layout stops making such nests
  // this tall, this test needs another drawing beyond the pass.
  assert.ok(expected.height > 1e7, 'the unfolded nest is only ' + expected.height + ' px tall');
  assert.ok(expected.uncertain >= 20, 'only ' + expected.uncertain + ' uncertain cables');
  const actual = await routedInWorker(doc, 256);
  assert.equal(actual.height, expected.height);
  assert.deepEqual(actual.routes, expected.routes);
});

test('the build with the pass taken out draws a small document and a nest of 14 groups differently', () => {
  // So that the comparison above can fail: within the bound the pass does move cables.
  const small = rendererRegressionWorkflow();
  const a = routed(real, small);
  const b = routed(passOff, small);
  assert.equal(a.routes.length, b.routes.length);
  assert.notDeepEqual(a.routes, b.routes);
  // And a nest of 14 groups (under 20,000 px tall) is within it: the pass runs there too.
  const shallow = nest(14);
  const c = routed(real, shallow);
  assert.ok(c.height < 20000, 'a nest of 14 groups is ' + c.height + ' px tall');
  assert.notDeepEqual(c.routes, routed(passOff, shallow).routes);
});

/**
 * A core under `wrappers` groups that each hold nothing but the next: two rows of 24 steps, narrow
 * cards over wide ones, each row an observed chain, and for 20 of the 23 gaps between columns 90
 * inferred or unresolved connections, each of a kind of its own, from the narrow card of one
 * column to the wide card of the next: 1,800 in all, within the 2,000 the pass takes on. The
 * drawing stays small: every group adds 32 px of width and 50 px of height.
 */
function squeezed(wrappers) {
  const nodes = [];
  const edges = [];
  const step = (extra) => {
    nodes.push({ id: 'n' + nodes.length, label: 'Step ' + nodes.length, phase: 'p0', ...extra, basis: 'observed', evidence: ['ev'] });
    return nodes[nodes.length - 1].id;
  };
  const link = (source, target, kind, basis) => {
    edges.push({ id: 'c' + edges.length, source, target, label: kind + ' ' + edges.length, kind, basis, evidence: ['ev'] });
  };
  let parent = null;
  for (let i = 0; i < wrappers; i++) parent = step({ kind: 'group', ...(parent ? { parent } : {}) });
  const inside = parent ? { parent } : {};
  const narrow = Array.from({ length: 24 }, () => step({ kind: 'layer', ...inside }));
  const wide = Array.from({ length: 24 }, () => step({ kind: 'model', ...inside }));
  for (const row of [narrow, wide]) for (let i = 1; i < row.length; i++) link(row[i - 1], row[i], 'call', 'observed');
  for (let c = 0; c + 1 < 24; c++) {
    // Six columns fit a row of the drawing: none across the wrap to the next row.
    if (c % 6 === 5) continue;
    for (let j = 0; j < 90; j++) link(narrow[c], wide[c + 1], 'kind-' + j, j % 2 ? 'inferred' : 'unresolved');
  }
  return {
    workflowVersion: '1.0', title: 'A core under ' + wrappers + ' groups',
    producer: { kind: 'host-llm', host: 'unknown', model: 'fixture' }, revision: { id: 'squeezed-' + wrappers },
    request: { question: 'Is a drawing whose card test is beyond the pass still routed?', scope: 'synthetic' },
    phases: [{ id: 'p0', label: 'Wrapped core' }],
    nodes, edges, findings: [],
    evidence: [{ id: 'ev', file: 'src/steps.py', line: 1, endLine: 1, quote: 'step()' }],
    coverage: { status: 'partial', summary: 'Synthetic shape only.', inspectedFiles: [], limitations: [] },
  };
}

test('a core under 100 groups is left as the router drew it, and the same core under 5 groups is not', () => {
  // Every group around a cable's ends is one more box the card test reads for every segment it is
  // asked about, so what the pass reads there grows with the nesting and with nothing else: the
  // cables, the strokes near them and the entries read are the same under 5 groups and under 100,
  // and the drawing is a few thousand px either way. With no bound on the boxes read, the time of
  // the pass would grow with every group.
  const deep = squeezed(100);
  assert.equal(deep.nodes.length, 148);
  const expected = routed(passOff, deep);
  assert.equal(expected.uncertain, 1800);
  assert.ok(expected.height < 8000, 'the drawing is ' + expected.height + ' px tall');
  assert.deepEqual(routed(real, deep).routes, expected.routes);
  // So that the comparison can fail: under 5 groups the pass runs, on the same cables.
  const shallow = squeezed(5);
  const off = routed(passOff, shallow);
  assert.equal(off.uncertain, 1800);
  assert.notDeepEqual(routed(real, shallow).routes, off.routes);
});
