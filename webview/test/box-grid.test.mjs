// The box grid (`layout/boxgrid.ts`) against the scan it stands in for.
//
// The router asks of every segment it proposes which cards it passes through, and the separation
// pass (`layout/separate.ts`) asks it for every offset it tries. Both read one grid of the layout's
// boxes. A box the grid misses is a card a connection is routed through, and a box it names twice
// is a card counted twice, so on seeded random boxes and segments `hitBy` must name exactly the
// boxes `segHitsBox` accepts, each once.
//
// The boxes are SYNTHETIC rectangles, not layouts: card-sized ones in a frame, ones with faces on
// the grid's cell lines, ones far apart (the grid doubles its cell size until it fits), zero-sized
// ones, and ones that are no rectangle at all (a negative size, a coordinate that is not finite),
// which the grid keeps aside and reads for every segment. The generator is a small PRNG seeded per
// scene, so a failure names its scene and repeats. The routes the router and the pass build on it
// are held by the digests of `geometry-golden.test.mjs`.
import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { build } from 'esbuild';
import { WEBVIEW_ROOT } from './helpers.mjs';

/** The grid as one ES module, compiled from the sources (nothing touches the DOM on import). */
const { BoxGrid, segHitsBox } = await build({
  stdin: {
    contents: "export { BoxGrid, segHitsBox } from './layout/boxgrid.ts';",
    resolveDir: join(WEBVIEW_ROOT, 'src'),
    loader: 'ts',
    sourcefile: 'box-grid-entry.ts',
  },
  bundle: true,
  format: 'esm',
  platform: 'neutral',
  write: false,
  logLevel: 'silent',
}).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));

/** mulberry32: a 32-bit seed in, a stream of numbers in [0, 1) out. */
function prng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The router's rule, written out apart from `segHitsBox`: a segment against a box interior, 1 px inset. */
function passesThrough(x0, x1, y0, y1, box) {
  return x1 > box.x + 1 && x0 < box.x + box.w - 1 && y1 > box.y + 1 && y0 < box.y + box.h - 1;
}

const CELL = 128;

/** One scene: its boxes, and the coordinates worth aiming a segment at. */
function scene(kind, seed) {
  const rand = prng(seed);
  const int = (n) => Math.floor(rand() * n);
  const pick = (list) => list[int(list.length)];
  const cents = (v) => Math.round(v * 100) / 100;
  const boxes = [];
  const count = pick([0, 1, 2, 5, 12, 40, 120, 300]);
  for (let i = 0; i < count; i++) {
    if (kind === 'cards') {
      // Cards and groups as a layout places them: hundredths of a pixel, a group around the card before it.
      const around = boxes.length && rand() < 0.15 ? boxes[int(boxes.length)] : null;
      if (around) boxes.push({ x: around.x - 14, y: around.y - 36, w: around.w + 28 + int(300), h: around.h + 50 + int(200) });
      else boxes.push({ x: cents(rand() * 2400), y: cents(rand() * 9000), w: 120 + int(240), h: 44 + int(160) });
    } else if (kind === 'cell lines') {
      // Faces on, and a pixel or two either side of, the lines between cells.
      const edge = () => CELL * (int(12) - 2) + pick([0, 0, 1, -1, 2, -2, 0.5, -0.5, 64]);
      const x = edge();
      const y = edge();
      boxes.push({ x, y, w: Math.max(0, edge() - x), h: Math.max(0, edge() - y) });
    } else if (kind === 'far apart') {
      // A drawing far too large for 128 px cells, with boxes left of and above the origin.
      const far = pick([1e3, 1e5, 4e6, 3e8]);
      boxes.push({ x: (rand() - 0.5) * far, y: (rand() - 0.5) * far, w: rand() * pick([10, 300, 4000]), h: rand() * pick([10, 300, 4000]) });
    } else {
      // Zero-sized boxes, slivers under the 2 px the inset takes, and boxes that are no rectangle.
      const box = { x: cents(rand() * 600 - 100), y: cents(rand() * 600 - 100), w: pick([0, 0.5, 1, 2, 2.01, 3, 150]), h: pick([0, 0.5, 1, 2, 2.01, 3, 90]) };
      const odd = int(12);
      if (odd === 0) box.w = -box.w - 40;
      if (odd === 1) box.h = -200;
      if (odd === 2) box[pick(['x', 'y', 'w', 'h'])] = NaN;
      if (odd === 3) box[pick(['w', 'h'])] = Infinity;
      if (odd === 4) box[pick(['x', 'y'])] = -Infinity;
      boxes.push(box);
    }
  }
  // Where to aim: every face, its 1 px inset and just either side of both, the cell lines, and anywhere.
  const xs = [];
  const ys = [];
  for (const box of boxes) {
    for (const d of [-1.01, -1, 0, 0.99, 1, 1.01, 2]) {
      xs.push(box.x + d, box.x + box.w - d);
      ys.push(box.y + d, box.y + box.h - d);
    }
  }
  const span = kind === 'far apart' ? 4e8 : kind === 'cards' ? 10000 : 1600;
  const aim = (list) => {
    const roll = rand();
    if (roll < 0.5 && list.length) return pick(list);
    if (roll < 0.6) return CELL * (int(40) - 8) + pick([0, -0.01, 0.01]);
    if (roll < 0.62) return pick([Infinity, -Infinity, NaN]);
    return (rand() - 0.3) * span;
  };
  const segment = () => {
    const a = { x: aim(xs), y: aim(ys) };
    const b = { x: aim(xs), y: aim(ys) };
    const shape = int(10);
    // Mostly what a router draws, a horizontal or a vertical run; also a point, and any pair of points.
    if (shape < 4) b.y = a.y;
    else if (shape < 8) b.x = a.x;
    else if (shape === 8) Object.assign(b, a);
    return [Math.min(a.x, b.x), Math.max(a.x, b.x), Math.min(a.y, b.y), Math.max(a.y, b.y)];
  };
  return { boxes, segment };
}

const KINDS = ['cards', 'cell lines', 'far apart', 'degenerate'];
const SCENES = 60;
const SEGMENTS = 250;

for (const kind of KINDS) {
  test('the box grid names the boxes a scan of every box names, each once: ' + kind, () => {
    let found = 0;
    for (let n = 0; n < SCENES; n++) {
      const seed = 1000 * (KINDS.indexOf(kind) + 1) + n;
      const { boxes, segment } = scene(kind, seed);
      const grid = new BoxGrid(boxes);
      for (let q = 0; q < SEGMENTS; q++) {
        const [x0, x1, y0, y1] = segment();
        const where = () => kind + ' scene ' + seed + ' (' + boxes.length + ' boxes), segment ' + q + ' [' + [x0, x1, y0, y1].join(', ') + ']';
        const expected = [];
        for (let at = 0; at < boxes.length; at++) {
          const hit = passesThrough(x0, x1, y0, y1, boxes[at]);
          if (segHitsBox(x0, x1, y0, y1, boxes[at]) !== hit) assert.fail(where() + ': segHitsBox disagrees on box ' + at);
          if (hit) expected.push(at);
        }
        const count = grid.hitBy(x0, x1, y0, y1);
        const actual = Array.from(grid.found.subarray(0, count)).sort((a, b) => a - b);
        if (actual.length !== expected.length || actual.some((at, k) => at !== expected[k])) assert.deepEqual(actual, expected, where());
        found += count;
      }
    }
    // Not vacuous: the segments do pass through boxes.
    assert.ok(found > 500, kind + ': only ' + found + ' boxes were found over every scene');
  });
}

test('boxes nested one inside the next: the grid keeps to 65,536 entries and still names what a scan names', () => {
  // A group lies in every cell its frame covers, so groups nested one inside the next are each
  // written to nearly every cell: 65,536 cells do not bound such a grid, its entries do. The
  // scenes are frames nested 16 px in from the sides, 34 px from the top and 16 px from the
  // bottom, as `layoutGraph` nests groups, around a core up to 3 million px tall, and a card in
  // each tenth frame. `entriesAt` is the grid's own count written out again: the cells a box
  // lies in, summed, at a cell size.
  const MAX = 65536;
  const entriesAt = (boxes, size) => boxes.reduce((n, b) => n + (Math.floor((b.x + b.w) / size) - Math.floor(b.x / size) + 1) * (Math.floor((b.y + b.h) / size) - Math.floor(b.y / size) + 1), 0);
  const cellsAt = (boxes, size) => {
    const lo = (key) => Math.min(...boxes.map((b) => Math.floor(b[key] / size)));
    const hi = (key, span) => Math.max(...boxes.map((b) => Math.floor((b[key] + b[span]) / size)));
    return (hi('x', 'w') - lo('x') + 1) * (hi('y', 'h') - lo('y') + 1);
  };
  let bounded = 0;
  let found = 0;
  for (const [depth, coreW, coreH] of [[40, 900, 3000], [300, 2000, 40000], [300, 600, 3e6], [1200, 1500, 9e5], [1200, 300, 300]]) {
    const seed = 5000 + depth + coreH;
    const rand = prng(seed);
    const boxes = [];
    for (let i = 0; i < depth; i++) {
      const inset = depth - i;
      boxes.push({ x: 100 + 16 * i, y: 100 + 34 * i, w: coreW + 32 * inset, h: coreH + 50 * inset });
      if (i % 10 === 9) boxes.push({ x: 100 + 16 * i + 20, y: 100 + 34 * i + 40, w: 176, h: 60 });
    }
    const grid = new BoxGrid(boxes);
    // What the grid ends with: at most MAX cells, and MAX entries or four entries a box, whichever
    // is more.
    assert.ok(grid.cols * grid.rows <= MAX, 'scene ' + seed + ': ' + grid.cols * grid.rows + ' cells');
    assert.equal(grid.items.length, entriesAt(boxes, grid.size), 'scene ' + seed + ': the entries are the cells the boxes lie in');
    assert.ok(grid.items.length <= Math.max(MAX, 4 * boxes.length), 'scene ' + seed + ': ' + grid.items.length + ' entries at ' + grid.size + ' px');
    // The cell size is the first doubling of 128 px that keeps both limits, no larger.
    let size = CELL;
    while (cellsAt(boxes, size) > MAX) size *= 2;
    if (entriesAt(boxes, size) > MAX) bounded++;
    while (entriesAt(boxes, size) > Math.max(MAX, 4 * boxes.length)) size *= 2;
    assert.equal(grid.size, size, 'scene ' + seed + ': the cell size');

    const right = 100 + coreW + 32 * depth + 16 * depth;
    const bottom = 100 + coreH + 50 * depth + 34 * depth;
    for (let q = 0; q < 300; q++) {
      const a = { x: rand() * (right + 200) - 50, y: rand() * (bottom + 200) - 50 };
      const b = { x: rand() * (right + 200) - 50, y: rand() * (bottom + 200) - 50 };
      if (q % 3 === 0) b.y = a.y;
      else if (q % 3 === 1) b.x = a.x;
      // A third of them from a frame's own face or its inset.
      if (q % 3 === 2) Object.assign(a, { x: boxes[q % boxes.length].x + (q % 2), y: boxes[q % boxes.length].y + 1 + (q % 2) });
      const [x0, x1, y0, y1] = [Math.min(a.x, b.x), Math.max(a.x, b.x), Math.min(a.y, b.y), Math.max(a.y, b.y)];
      const expected = [];
      for (let at = 0; at < boxes.length; at++) if (passesThrough(x0, x1, y0, y1, boxes[at])) expected.push(at);
      const count = grid.hitBy(x0, x1, y0, y1);
      const actual = Array.from(grid.found.subarray(0, count)).sort((m, n) => m - n);
      if (actual.length !== expected.length || actual.some((at, k) => at !== expected[k])) assert.deepEqual(actual, expected, 'scene ' + seed + ', segment ' + q + ' [' + [x0, x1, y0, y1].join(', ') + ']');
      found += count;
    }
  }
  // Not vacuous: in most scenes 65,536 cells alone would have held more entries than that, and the segments pass through boxes.
  assert.ok(bounded >= 3, 'only ' + bounded + ' scenes needed the limit on entries');
  assert.ok(found > 5000, 'only ' + found + ' boxes were found');
});

test('the grid counts what it reads: a box once for each cell it is read from, hit or not', () => {
  // The separation pass bounds what its card test reads by this count (`layout/separate.ts`, `cards`).
  // A group over four cells with a card inside it over the same four, and a card over two cells elsewhere.
  const boxes = [{ x: 40, y: 40, w: 200, h: 180 }, { x: 60, y: 90, w: 120, h: 60 }, { x: 600, y: 40, w: 120, h: 60 }];
  const grid = new BoxGrid(boxes);
  assert.equal(grid.read, 0);
  // Along the first row of cells from x = 0 to 400: the group and its card in each of two cells, nothing in the next two.
  assert.equal(grid.hitBy(0, 400, 120, 120), 2);
  assert.equal(grid.read, 4);
  // Into the lone card's first cell and short of the card: read, not hit.
  assert.equal(grid.hitBy(590, 599, 50, 50), 0);
  assert.equal(grid.read, 5);
  // Outside the grid there is nothing to read.
  assert.equal(grid.hitBy(5000, 5100, 5000, 5000), 0);
  assert.equal(grid.read, 5);
  // A box that is no rectangle lies in no cell and is read for every segment.
  const odd = new BoxGrid(boxes.concat([{ x: 0, y: 0, w: -5, h: 10 }]));
  odd.hitBy(5000, 5100, 5000, 5000);
  assert.equal(odd.read, 1);
  odd.hitBy(0, 400, 120, 120);
  assert.equal(odd.read, 6);

  // Under frames nested one inside the next a segment reads every frame around it, so the count
  // grows with the nesting. On seeded segments it is the entries of the cells under the segment,
  // written out again: for each box, the cells it shares with the segment's.
  for (const [depth, coreW, coreH] of [[40, 900, 3000], [300, 2000, 40000], [1200, 300, 300]]) {
    const rand = prng(7000 + depth);
    const nest = [];
    for (let i = 0; i < depth; i++) nest.push({ x: 100 + 16 * i, y: 100 + 34 * i, w: coreW + 32 * (depth - i), h: coreH + 50 * (depth - i) });
    const deep = new BoxGrid(nest);
    const size = deep.size;
    const shared = (lo, hi, from, to) => Math.max(0, Math.min(Math.floor(hi / size), Math.floor(to / size)) - Math.max(Math.floor(lo / size), Math.floor(from / size)) + 1);
    const right = 100 + coreW + 48 * depth;
    const bottom = 100 + coreH + 84 * depth;
    for (let q = 0; q < 200; q++) {
      const a = { x: rand() * (right + 200) - 50, y: rand() * (bottom + 200) - 50 };
      const b = q % 2 ? { x: a.x, y: rand() * (bottom + 200) - 50 } : { x: rand() * (right + 200) - 50, y: a.y };
      const [x0, x1, y0, y1] = [Math.min(a.x, b.x), Math.max(a.x, b.x), Math.min(a.y, b.y), Math.max(a.y, b.y)];
      const expected = nest.reduce((n, box) => n + shared(x0, x1, box.x, box.x + box.w) * shared(y0, y1, box.y, box.y + box.h), 0);
      const before = deep.read;
      deep.hitBy(x0, x1, y0, y1);
      assert.equal(deep.read - before, expected, depth + ' frames, segment ' + q + ' [' + [x0, x1, y0, y1].join(', ') + ']');
    }
    // A point inside the innermost frame is under all of them.
    const before = deep.read;
    assert.equal(deep.hitBy(100 + 16 * depth, 100 + 16 * depth, 100 + 34 * depth, 100 + 34 * depth), depth);
    assert.equal(deep.read - before, depth);
  }
});

test('a grid of no boxes finds nothing, and a grid asked twice answers the same', () => {
  const empty = new BoxGrid([]);
  assert.equal(empty.hitBy(-1e6, 1e6, -1e6, 1e6), 0);
  // A group over four cells with a card inside it, and a card elsewhere.
  const grid = new BoxGrid([{ x: 40, y: 40, w: 200, h: 180 }, { x: 60, y: 90, w: 120, h: 60 }, { x: 600, y: 40, w: 120, h: 60 }]);
  const first = Array.from(grid.found.subarray(0, grid.hitBy(0, 400, 120, 120))).sort();
  const second = Array.from(grid.found.subarray(0, grid.hitBy(0, 400, 120, 120))).sort();
  assert.deepEqual(first, [0, 1]);
  assert.deepEqual(second, first);
});
