// Viewer M3, roadmap step 13: the phase overview (Shift+0) and the labelled phase index that
// replaced the minimap.
//
// The overview's geometry (render/phaseoverview.ts), the move to a phase (phasePlan) and the
// index's in-view rule (phasesInView) are pure, so their cases run against the sources compiled
// here with the esbuild the build already uses. The integration cases run on the built bundle.
//
// The fixtures are SYNTHETIC: generated documents with the shapes of the two public shakedown
// artifacts the design was measured on (helpers.mjs: VIT_SHAPE, 6 phases and 31 steps; YOLO_SHAPE,
// 4 phases and 59 steps), plus small hand-made documents for the order and link rules. No
// third-party text is used. The three panel sizes the roadmap names (1440x900, 900x800, 541x798)
// give these canvases: beside the docked rail 1080x842; above the collapsed bottom sheet 900x710
// and 541x708 (the header is 58 px, the collapsed sheet 32 px). jsdom lays nothing out, so the
// panel and canvas boxes are stubbed `getBoundingClientRect`s, as in m2-live.test.mjs. None of
// this is a live VS Code check, a usability check or a semantic review.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { build } from 'esbuild';
import { loadBundle, recordingBridge, routedGeometry, shapedWorkflow, VIT_SHAPE, WEBVIEW_ROOT, YOLO_SHAPE } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const eq = (actual, expected, message) => (message === undefined ? assert.deepEqual(plain(actual), plain(expected)) : assert.deepEqual(plain(actual), plain(expected), message));

let sourcePromise = null;
/** The pure parts as one ES module (nothing touches the DOM on import). */
function source() {
  if (!sourcePromise) {
    sourcePromise = build({
      stdin: {
        contents: [
          "export { normalizeWorkflow } from './workflow.ts';",
          "export { GraphIndex } from './layout/model.ts';",
          "export * from './render/phaseoverview.ts';",
          "export { phasesInView, INDEX_W, INDEX_MARGIN, PILL_H, PILL_MAX_W } from './render/phaseindex.ts';",
          "export { phasePlan, clearOf, rectsOverlap, VIEW_ANIMATION_MS, READABLE_ZOOM } from './render/canvas.ts';",
          "export { blockName } from './ui/overview.ts';",
        ].join('\n'),
        resolveDir: join(WEBVIEW_ROOT, 'src'),
        loader: 'ts',
        sourcefile: 'phase-overview-entry.ts',
      },
      bundle: true,
      format: 'esm',
      platform: 'neutral',
      write: false,
      logLevel: 'silent',
    }).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));
  }
  return sourcePromise;
}

async function inputFor(document, keep = () => true) {
  const m = await source();
  return m.overviewInput(new m.GraphIndex(m.normalizeWorkflow(document)), keep);
}

/** The canvases of the three panel sizes, and the raw panel sizes (a canvas can be that big too). */
const CANVASES = [
  ['1440x900 (docked rail)', 1080, 842],
  ['900x800 (sheet collapsed)', 900, 710],
  ['541x798 (sheet collapsed)', 541, 708],
];
const RAW = [['1440x900', 1440, 900], ['900x800', 900, 800], ['541x798', 541, 798]];

/* ── small hand-made documents ───────────────────────────────────────── */

const ev = (id, file = 'train.py', line = 1) => ({ id, file, line, endLine: line + 1, quote: 'x()' });
const base = (title, rest) => ({
  workflowVersion: '1.0', title, producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: title.replace(/\W+/g, '-') },
  request: { question: 'q', scope: 's' },
  coverage: { status: 'scoped', summary: 's', inspectedFiles: ['data.py', 'train.py'], limitations: [] },
  ...rest,
});

/** The walk's order document: groups, a cross-phase parent, a finding on two phases. */
function orderDoc() {
  return base('Order rules', {
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', basis: 'inferred', evidence: ['e3'] },
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'observed', evidence: ['e2'] },
      { id: 'sched', label: 'LR schedule', phase: 'data', parent: 'loop', basis: 'unresolved', evidence: [] },
      { id: 'zero', label: 'Zero grads', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e5'] },
    ],
    edges: [
      { id: 'c-step-zero', source: 'step', target: 'zero', label: 'then', basis: 'observed', evidence: ['e3'] },
      { id: 'c-load-aug', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c-aug-step', source: 'aug', target: 'step', label: 'batches', basis: 'inferred', evidence: ['e2'] },
      { id: 'c-load-step', source: 'load', target: 'step', label: 'labels', basis: 'observed', evidence: ['e1'] },
    ],
    findings: [
      { id: 'f-whole', title: 'No seed', message: 'm', severity: 'low', nodeIds: [], basis: 'observed', evidence: ['e1'] },
      { id: 'f-two', title: 'Order risk', message: 'm', severity: 'high', nodeIds: ['zero', 'aug'], basis: 'inferred', evidence: ['e5'] },
      { id: 'f-edge', title: 'Cast on batches', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c-aug-step'], basis: 'unresolved', evidence: ['e2'] },
      { id: 'f-step', title: 'Clip missing', message: 'm', severity: 'medium', nodeIds: ['step'], basis: 'observed', evidence: ['e3'] },
    ],
    evidence: [ev('e1', 'data.py', 3), ev('e2', 'data.py', 9), ev('e3', 'train.py', 4), ev('e5', 'train.py', 12)],
  });
}

/**
 * Four phases, one step each but the first: every kind of link. p0→p1 twice (the next phase),
 * p1→p0 (an ADJACENT backward link: a bracket, not an arrow), p3→p2 (adjacent backward again, on
 * phases the first one does not span, so it shares its slot), p0→p2 (skips p1), p2→p3 (next),
 * and one connection inside p0.
 */
function linkDoc() {
  const node = (id, phase) => ({ id, label: 'Step ' + id, phase, basis: 'observed', evidence: ['e1'] });
  const edge = (id, source, target) => ({ id, source, target, label: id, basis: 'observed', evidence: ['e1'] });
  return base('Link rules', {
    phases: [0, 1, 2, 3].map((i) => ({ id: 'p' + i, label: 'Phase ' + i })),
    nodes: [node('a', 'p0'), node('a2', 'p0'), node('b', 'p1'), node('c', 'p2'), node('d', 'p3')],
    edges: [edge('x1', 'a', 'b'), edge('x2', 'a2', 'b'), edge('back1', 'b', 'a'), edge('back2', 'd', 'c'), edge('skip', 'a', 'c'), edge('next', 'c', 'd'), edge('in', 'a', 'a2')],
    findings: [],
    evidence: [ev('e1')],
  });
}

/* ── the geometry, pure ──────────────────────────────────────────────── */

/** Every invariant a layout keeps whatever the document and the size. */
async function checkLayout(input, L, label) {
  const m = await source();
  const pad = L.narrow ? m.PAD_NARROW : m.PAD;
  // Every step is listed or counted, per block and in all.
  let sum = 0;
  for (const b of L.blocks) {
    const phase = input.phases[b.phase];
    const total = phase.steps.length;
    assert.equal(b.listed + b.more, total, `${label}: block ${b.phase} lists ${b.listed} and counts ${b.more} of ${total}`);
    sum += b.listed + b.more;
    const titles = b.items.filter((it) => it.step >= 0);
    eq(titles.map((it) => it.step), Array.from({ length: b.listed }, (_, k) => k), `${label}: block ${b.phase} lists its FIRST steps, in reading order`);
    const more = b.items.filter((it) => it.step < 0);
    assert.equal(more.length, b.more ? 1 : 0, `${label}: one "… N more steps" row exactly when trimmed`);
    if (b.more) {
      assert.equal(more[0].more, b.more, `${label}: the row's N is the steps not listed`);
      assert.equal(b.items[b.items.length - 1].step, -1, `${label}: the count is the last slot`);
      assert.ok(b.listed >= Math.min(total, m.MIN_SLOTS) - 1, `${label}: never fewer than ${m.MIN_SLOTS - 1} titles`);
    }
    assert.ok(b.items.length <= b.rows * b.cols, `${label}: the items fit the block's slots`);
    assert.equal(new Set(b.items.map((it) => it.col + ':' + it.row)).size, b.items.length, `${label}: one item per slot`);
    // Items inside their block, below its head.
    for (const it of b.items) {
      assert.ok(it.x >= b.x + m.BLOCK_PAD_X - 0.05 && it.x + it.w <= b.x + b.w - m.BLOCK_PAD_X + 0.05, `${label}: item ${it.step} of block ${b.phase} inside it across`);
      assert.ok(it.y >= b.y + b.headH - 0.05 && it.y + m.ROW_H <= b.y + b.h - m.BLOCK_PAD_B + 0.05, `${label}: item ${it.step} of block ${b.phase} inside it down`);
    }
    assert.ok(b.w <= m.BLOCK_MAX_W);
    assert.equal(b.x, pad);
  }
  assert.equal(sum + input.unplacedSteps, input.totalSteps, `${label}: the blocks sum to the document's steps`);
  // The connections are a partition: inside + arrows + brackets = all.
  const part = m.connectionPartition(input);
  assert.equal(part.inside + part.next + part.jumps + part.unplaced, input.totalConnections, `${label}: the partition sums to the connections`);
  assert.equal(L.arrows.reduce((s, a) => s + a.count, 0), part.next, `${label}: the arrows carry the links to the next phase`);
  assert.equal(L.brackets.reduce((s, b) => s + b.count, 0), part.jumps, `${label}: the brackets carry the rest`);
  for (const a of L.arrows) assert.equal(a.to, a.from + 1);
  for (const b of L.brackets) {
    assert.notEqual(b.to, b.from + 1, 'a bracket never joins a phase to the next one');
    assert.equal(b.back, b.to < b.from);
    assert.ok(b.x > b.x0, `${label}: a bracket runs right of the blocks`);
    assert.ok(b.x + m.BRACKET_TAIL <= L.viewW - pad + 1, `${label}: and its count stays on the canvas (${b.x} + tail, canvas ${L.viewW})`);
  }
  // Blocks in phase order, under the header, never overlapping.
  let bottom = L.header.y + L.header.h;
  for (const [i, b] of L.blocks.entries()) {
    assert.equal(b.phase, i);
    assert.ok(b.y >= bottom, `${label}: block ${i} starts under what is above it`);
    bottom = b.y + b.h;
  }
  assert.ok(bottom <= L.height, `${label}: the content holds the last block`);
  assert.ok(L.width <= L.viewW, `${label}: never wider than the canvas (no sideways scroll)`);
  // It scrolls only when every block is down to its minimum.
  if (L.scrolls) {
    for (const b of L.blocks) assert.equal(b.rows, Math.ceil(Math.min(input.phases[b.phase].steps.length, m.MIN_SLOTS) / b.cols), `${label}: scrolls only with block ${b.phase} at its minimum`);
  } else assert.ok(L.height <= L.viewH, `${label}: fits the canvas`);
  // The block with the most rows gives first: a trimmed block is at most one row under the tallest.
  const tallest = Math.max(...L.blocks.map((b) => b.rows));
  for (const b of L.blocks) if (b.more) assert.ok(b.rows >= tallest - 1 || b.rows === Math.ceil(Math.min(input.phases[b.phase].steps.length, m.MIN_SLOTS) / b.cols), `${label}: block ${b.phase} was not trimmed before a taller one`);
}

for (const [name, shape, phases, steps] of [['vit-cc', VIT_SHAPE, 6, 31], ['yolov5-cc2', YOLO_SHAPE, 4, 59]]) {
  test(`overview geometry, the ${name} shape: every step listed or counted, the connections a partition, blocks inside the canvas, at the three sizes`, async () => {
    const m = await source();
    const input = await inputFor(shapedWorkflow(shape));
    assert.equal(input.phases.length, phases);
    assert.equal(input.totalSteps, steps);
    for (const [label, w, h] of [...CANVASES, ...RAW]) {
      const L = m.phaseOverviewLayout(input, w, h);
      await checkLayout(input, L, `${name} ${label}`);
    }
  });

  test(`overview geometry, the ${name} shape: two title columns from 900 px, one at 541 px; titles at least 200 px wide; the counts head the overview`, async () => {
    const m = await source();
    const input = await inputFor(shapedWorkflow(shape));
    for (const [label, w, h] of CANVASES) {
      const L = m.phaseOverviewLayout(input, w, h);
      const narrow = w < 620;
      assert.equal(L.narrow, narrow, label);
      for (const b of L.blocks) {
        assert.equal(b.cols, narrow ? 1 : 2, `${label}: ${narrow ? 'one column' : 'two columns'} of titles`);
        assert.equal(b.twoLineHead, narrow, `${label}: the counts go on a second line only when narrow`);
        for (const it of b.items) assert.ok(it.w + it.depth * m.INDENT >= 200, `${label}: a title column is ${it.w + it.depth * m.INDENT} px`);
      }
      assert.equal(L.header.summary, m.overviewSummary(input));
      assert.match(L.header.summary, new RegExp(`^${phases} phases · ${steps} steps · \\d+ connections: \\d+ inside a phase, \\d+ to the next phase, \\d+ (skip ahead or go back|skips ahead or goes back)\\.$`));
      assert.equal(L.header.key === null, narrow, `${label}: the key is shown when there is room`);
    }
  });
}

test('overview geometry: six phases fit without scrolling at 1440 and 900 and scroll a little at 541; four phases fit at all three sizes', async () => {
  const m = await source();
  const vit = await inputFor(shapedWorkflow(VIT_SHAPE));
  const yolo = await inputFor(shapedWorkflow(YOLO_SHAPE));
  const scrolls = (input) => CANVASES.map(([, w, h]) => m.phaseOverviewLayout(input, w, h).scrolls);
  eq(scrolls(vit), [false, false, true]);
  eq(scrolls(yolo), [false, false, false]);
  // At 541 px the six blocks keep two titles and the count each, rather than names only.
  const narrow = m.phaseOverviewLayout(vit, 541, 708);
  for (const b of narrow.blocks) assert.ok(b.listed >= 2, 'two titles per block at 541 px');
  // A short canvas (the sheet open at 541 px) only scrolls further; nothing goes below the minimum.
  const short = m.phaseOverviewLayout(vit, 541, 392);
  assert.equal(short.scrolls, true);
  await checkLayout(vit, short, 'vit 541x392');
});

test('overview geometry: an adjacent backward link is a dashed bracket, not an arrow; brackets on disjoint phases share a slot', async () => {
  const m = await source();
  const input = await inputFor(linkDoc());
  eq(input.links, [{ from: 0, to: 1, count: 2 }, { from: 0, to: 2, count: 1 }, { from: 1, to: 0, count: 1 }, { from: 2, to: 3, count: 1 }, { from: 3, to: 2, count: 1 }]);
  eq(m.connectionPartition(input), { inside: 1, next: 3, jumps: 3, unplaced: 0 });
  assert.equal(m.overviewSummary(input), '4 phases · 5 steps · 7 connections: 1 inside a phase, 3 to the next phase, 3 skip ahead or go back.');
  const L = m.phaseOverviewLayout(input, 1080, 842);
  await checkLayout(input, L, 'link rules');
  eq(L.arrows.map((a) => [a.from, a.to, a.count]), [[0, 1, 2], [2, 3, 1]]);
  const brackets = L.brackets.map((b) => [b.from, b.to, b.count, b.back, b.slot]);
  // p1→p0 spans phases 0-1 and p3→p2 spans 2-3: the same slot. p0→p2 spans 0-2: the next one.
  eq(brackets.sort(), [[0, 2, 1, false, 1], [1, 0, 1, true, 0], [3, 2, 1, true, 0]].sort());
  // Each bracket leaves its block and enters the other, on their right edges.
  for (const b of L.brackets) {
    const from = L.blocks[b.from];
    const to = L.blocks[b.to];
    assert.ok(b.y1 > from.y && b.y1 < from.y + from.h, 'it leaves the block it comes from');
    assert.ok(b.y2 > to.y && b.y2 < to.y + to.h, 'and enters the block it goes to');
    assert.equal(b.x0, from.x + from.w);
  }
  // A block's name says where its connections go, each count with its unit.
  assert.equal(m.blockName(input, 0), 'Phase 1 of 4: Phase 0. 2 steps. 2 connections to phase 2; 1 connection ahead to phase 3. Enter goes to this phase.');
  assert.equal(m.blockName(input, 1), 'Phase 2 of 4: Phase 1. 1 step. 1 connection back to phase 1. Enter goes to this phase.');
  assert.equal(m.blockName(input, 3), 'Phase 4 of 4: Phase 3. 1 step. 1 connection back to phase 3. Enter goes to this phase.');
});

test('overview input: steps in reading order (a group before its steps), basis marks, F labels the toggles keep, findings counted per phase (PR #14)', async () => {
  const m = await source();
  const input = await inputFor(orderDoc());
  eq(input.phases.map((p) => p.label), ['Data', 'Fit']);
  // The walk's and the Outline's order: Data's roots, sched last (its parent is in Fit); then the
  // Fit group before its steps, one level in.
  eq(input.phases.map((p) => p.steps.map((s) => [s.id, s.depth, s.basis])), [
    [['load', 0, 'observed'], ['aug', 0, 'observed'], ['sched', 0, 'unresolved']],
    [['loop', 0, 'observed'], ['step', 1, 'inferred'], ['zero', 1, 'observed']],
  ]);
  eq(input.phases.map((p) => m.blockStepsText(p)), ['3 steps (1 unresolved)', '3 steps (1 inferred)']);
  const tags = (inp) => Object.fromEntries(inp.phases.flatMap((p) => p.steps.map((s) => [s.id, s.tags.map((t) => t.short + ':' + t.severity)])));
  eq(tags(input), { load: [], aug: ['F2:high'], sched: [], loop: [], step: ['F4:medium'], zero: ['F2:high'] });
  // f-two cites a step in each phase: it counts in both (the PR #14 rule), so the counts are not summed.
  assert.equal(input.phases[0].findings.high, 1);
  assert.equal(input.phases[1].findings.high, 1);
  // The connection-only finding counts in the phase its connection leaves.
  assert.equal(input.phases[0].findings.medium, 1);
  assert.equal(input.phases[1].findings.medium, 1);
  // With high findings hidden by the toggles, their labels and counts go.
  const kept = await inputFor(orderDoc(), (issue) => issue.severity !== 'high');
  eq(tags(kept), { load: [], aug: [], sched: [], loop: [], step: ['F4:medium'], zero: [] });
  assert.equal(kept.phases[0].findings.high, 0);
  assert.equal(m.overviewSummary(input), '2 phases · 6 steps · 4 connections: 2 inside a phase, 2 to the next phase, 0 skip ahead or go back.');
});

test('overview geometry: titles run down the first column and on into the second; group steps are indented, at most two levels', async () => {
  const m = await source();
  const input = await inputFor(shapedWorkflow(YOLO_SHAPE));
  const L = m.phaseOverviewLayout(input, 1080, 842);
  for (const b of L.blocks) {
    b.items.forEach((it, k) => {
      assert.equal(it.col, Math.floor(k / b.rows), 'column-major');
      assert.equal(it.row, k % b.rows);
      if (it.step >= 0) assert.equal(it.depth, Math.min(2, input.phases[b.phase].steps[it.step].depth));
    });
  }
  assert.ok(L.blocks.some((b) => b.items.some((it) => it.depth > 0)), 'the shape has group steps');
});

test('overview geometry is pure: the same input and size give the same picture, and the input is not changed', async () => {
  const m = await source();
  const input = await inputFor(shapedWorkflow(VIT_SHAPE));
  const before = JSON.stringify(input);
  const a = m.phaseOverviewLayout(input, 900, 710);
  const b = m.phaseOverviewLayout(input, 900, 710);
  eq(a, b);
  assert.equal(JSON.stringify(input), before);
});

test('phasePlan: a phase at reading size, its lane and left channel fitted when they fit at 0.75 or more, never above 0.9', async () => {
  const { phasePlan, READABLE_ZOOM } = await source();
  const frame = { width: 1200, height: 2000, channelW: 40, lanes: [0, 1, 2].map((i) => ({ x: 72, y: 32 + i * 640, w: 1000, h: 600 })) };
  const plan = phasePlan(frame, 1, 1080, 842);
  // Fitting lane 1 (1040 px with the channel, 600 px tall) needs (1080-48)/1040 = 0.99, so 0.9.
  assert.equal(plan.zoom, READABLE_ZOOM);
  assert.equal(plan.mode, 'phase-fit');
  assert.ok(Math.abs(plan.y - (24 - 672 * READABLE_ZOOM)) < 1e-9, 'the lane top 24 px under the canvas top');
  // The last lane: the end of the document stays at the foot of the canvas.
  const last = phasePlan(frame, 2, 1080, 842);
  assert.ok(Math.abs(last.y - (842 - 24 - 2000 * last.zoom)) < 1e-9);
  // A lane too big for 0.75 is anchored at 0.9.
  const narrow = phasePlan(frame, 0, 541, 708);
  assert.equal(narrow.mode, 'phase-anchor');
  assert.equal(narrow.zoom, READABLE_ZOOM);
  assert.equal(phasePlan(frame, 3, 1080, 842), null);
});

test('clearOf: the least pan that moves a card off the phase index while keeping it on the canvas', async () => {
  const { clearOf, rectsOverlap } = await source();
  const index = { x: 780, y: 650, w: 288, h: 180 };
  assert.equal(clearOf({ x: 100, y: 100, w: 200, h: 80 }, index, 1080, 842), null, 'already clear');
  // Low and to the right: up is shorter than left.
  const shift = clearOf({ x: 800, y: 700, w: 200, h: 60 }, index, 1080, 842);
  eq(shift, { dx: 0, dy: 650 - 8 - 760 });
  assert.equal(rectsOverlap({ x: 800, y: 700 + shift.dy, w: 200, h: 60 }, index), false);
  // A card that only clears to the left.
  eq(clearOf({ x: 700, y: 640, w: 120, h: 200 }, index, 1080, 842), { dx: 780 - 8 - 820, dy: 0 });
});

test('phasesInView: every lane on the canvas is in view; the current one is the lane the reader moved to, not the tall one beside it', async () => {
  const { phasesInView } = await source();
  const row = (id, y, h) => ({ id, label: id, index: 0, steps: 1, counts: {}, rect: { x: 0, y, w: 1000, h } });
  const rows = [row('a', 0, 300), row('b', 320, 260), row('c', 600, 3000)];
  // The view starts just above lane b: a sliver of a, all of b, and the top of the tall lane c under it
  // (c fills more of the canvas than b does; b is the lane the reader is on).
  const view = phasesInView(rows, { x: 0, y: -280, zoom: 1 }, 1080, 842);
  eq(view, { ids: ['a', 'b', 'c'], current: 'b' });
  eq(phasesInView(rows, { x: 0, y: -5000, zoom: 1 }, 1080, 842), { ids: [], current: null });
});

/* ── the overview and the phase index in the viewer ──────────────────── */

const RAIL_W = 360;
const SHEET_SHARE = 0.47;

/** Mount `document` in a panel `width` px wide whose body (between header and status bar) is `bodyH` px. */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  if (opts.reduce) ctx.document.body.classList.add('vscode-reduce-motion');
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 1440;
  const bodyH = opts.bodyH || 842;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: bodyH + 58, right: width, bottom: bodyH + 58 });
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const rail = ctx.document.querySelector('.mlv-rail');
  const box = () => {
    const docked = rail.getAttribute('data-mode') !== 'sheet';
    const w = docked ? width - (rail.hidden ? 0 : RAIL_W) : width;
    const sheet = docked ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * SHEET_SHARE) : 32;
    return { w, h: bodyH - sheet };
  };
  canvas.getBoundingClientRect = () => {
    const { w, h } = box();
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  const resize = (next) => {
    width = next;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  // The canvas box exists now: let the viewer measure it, and start from the readable first view.
  resize(width);
  app.view.fit();
  canvas.focus();
  return { ...ctx, root, bridge, app, canvas, rail, box, resize };
}

/** The panel sizes the roadmap names, as mount options. */
const PANELS = [
  ['1440x900', { width: 1440, bodyH: 842 }],
  ['900x800', { width: 900, bodyH: 742 }],
  ['541x798', { width: 541, bodyH: 740 }],
];

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const event = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
};
const shiftZero = (ctx, target) => press(ctx, ')', { shiftKey: true, code: 'Digit0' }, target);
const live = (ctx) => $(ctx, '.mlv-root > [aria-live]').textContent;
const vpOf = (ctx) => plain(ctx.app.getState().viewport);
const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;
const sameVp = (a, b) => near(a.x, b.x) && near(a.y, b.y) && near(a.zoom, b.zoom);

/** A box in world coordinates on screen, at the current viewport. */
function onScreen(ctx, b) {
  const vp = ctx.app.getState().viewport;
  return { x: b.x * vp.zoom + vp.x, y: b.y * vp.zoom + vp.y, w: b.w * vp.zoom, h: b.h * vp.zoom };
}
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** The plan a move to lane `k` lands on, for the canvas the viewer has now. */
async function planFor(ctx, k) {
  const { phasePlan } = await source();
  const { w, h } = ctx.box();
  return phasePlan(ctx.app.view.frameData, k, w, h);
}

test('Shift+0 opens the phase overview over the canvas, outside the world layer, on the phase in view; the diagram under it does not move', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    const geometry = routedGeometry(ctx.document);
    const before = vpOf(ctx);
    const overview = $(ctx, '.mlv-overview');
    assert.equal(overview.hidden, true, 'closed at first');
    assert.equal(overview.parentElement, ctx.canvas, 'a child of the canvas, beside the world layer');
    assert.equal($(ctx, '.mlv-world').contains(overview), false, 'never inside the layer that pans and zooms');
    const index = $(ctx, '.mlv-phaseindex');
    assert.equal(index.hidden, false, 'the phase index is shown');
    const event = shiftZero(ctx);
    assert.equal(event.defaultPrevented, true);
    assert.equal(ctx.app.view.overviewOpen, true);
    assert.equal(overview.hidden, false);
    assert.equal(index.hidden, true, 'the overview covers the canvas, so the index steps aside');
    assert.equal($$(ctx, '.mlv-ovblock').length, 6);
    const current = ctx.app.view.phasesInView()[0];
    const focused = ctx.document.activeElement;
    assert.ok(focused.classList.contains('mlv-ovblock'), 'a block has the focus');
    assert.equal(focused.getAttribute('data-phase-id'), ctx.app.view.phaseIndexElement.querySelector('[data-in-view]') ? focused.getAttribute('data-phase-id') : current);
    assert.equal(focused.tabIndex, 0, 'the focused block is the roving Tab stop');
    assert.equal($$(ctx, '.mlv-ovblock[tabindex="0"]').length, 1);
    assert.match(live(ctx), /^Phase overview: 6 phases, 31 steps\. Arrow keys move between phases, Enter goes to one, Escape goes back\.$/);
    // The routed picture and the viewport are untouched by the overlay.
    eq(routedGeometry(ctx.document), geometry, 'the routed geometry is unchanged with the overview open');
    eq(vpOf(ctx), before);
    // The ⋯ menu item says what it does now.
    $(ctx, '.mlv-btn--more').click();
    const item = $(ctx, '[data-more-item="overview"]');
    assert.match(item.textContent, /Close the phase overview/);
    $(ctx, '.mlv-btn--more').click();
    // Shift+0 again (on the block, as '0' with Shift on another layout) goes back.
    press(ctx, '0', { shiftKey: true }, $(ctx, '.mlv-ovblock[tabindex="0"]'));
    assert.equal(ctx.app.view.overviewOpen, false);
    eq(vpOf(ctx), before, 'back to exactly where the reader was');
    eq(routedGeometry(ctx.document), geometry);
    assert.equal(index.hidden, false, 'the index is back');
  } finally {
    ctx.app.destroy();
  }
});

test('overview keys: arrows, Home and End move between blocks and never move the selection; Escape gives the focus back to the card the reader was on', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    const first = ctx.app.index.roots(ctx.app.index.lanes[0].id).find((id) => !ctx.app.index.isGroup(id));
    ctx.app.select({ kind: 'node', id: first });
    const card = ctx.app.view.nodeElement(first);
    card.focus();
    assert.equal(ctx.document.activeElement, card, 'precondition: the keyboard is on a card');
    const before = vpOf(ctx);
    shiftZero(ctx, card);
    const active = () => Number(ctx.document.activeElement.getAttribute('data-block'));
    press(ctx, 'Home');
    assert.equal(active(), 0);
    press(ctx, 'ArrowDown');
    press(ctx, 'ArrowRight');
    assert.equal(active(), 2);
    press(ctx, 'ArrowUp');
    assert.equal(active(), 1);
    press(ctx, 'End');
    assert.equal(active(), 5);
    assert.equal(press(ctx, 'ArrowDown').defaultPrevented, true);
    assert.equal(active(), 5, 'End stays at the last block');
    press(ctx, 'ArrowLeft');
    assert.equal(active(), 4);
    eq(ctx.app.getState().selection, { kind: 'node', id: first }, 'the arrows moved the blocks, not the selection');
    assert.equal($$(ctx, '.mlv-ovblock[tabindex="0"]').length, 1);
    assert.equal(press(ctx, 'Escape').defaultPrevented, true);
    assert.equal(ctx.app.view.overviewOpen, false);
    assert.equal(ctx.document.activeElement, card, 'Escape gives the focus back to the card');
    eq(vpOf(ctx), before, 'and the diagram as it was');
    eq(ctx.app.getState().selection, { kind: 'node', id: first }, 'with the selection');
    assert.match(live(ctx), /Back to the diagram\./);
    // The Back button does the same.
    shiftZero(ctx, card);
    $(ctx, '.mlv-overview__back').click();
    assert.equal(ctx.app.view.overviewOpen, false);
  } finally {
    ctx.app.destroy();
  }
});

test('Enter on a block animates to that phase at reading size in about 240 ms, focus on the canvas; the next arrow starts at its first step', async () => {
  const { VIEW_ANIMATION_MS } = await source();
  const ctx = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    const before = vpOf(ctx);
    shiftZero(ctx);
    press(ctx, 'Home');
    press(ctx, 'ArrowDown');
    press(ctx, 'ArrowDown');
    press(ctx, 'ArrowDown');
    const lane = ctx.app.view.frameData.lanes[3];
    const plan = await planFor(ctx, 3);
    assert.equal(press(ctx, 'Enter').defaultPrevented, true);
    assert.equal(ctx.app.view.overviewOpen, false);
    assert.equal(ctx.document.activeElement, ctx.canvas, 'the keyboard is on the canvas');
    assert.equal(ctx.app.view.viewport.animating, true, 'it is moving');
    eq(vpOf(ctx), before, 'and has not jumped');
    assert.match(live(ctx), new RegExp(`^Phase 4: ${lane.label}, ${lane.nodeCount} steps\\.$`));
    await sleep(VIEW_ANIMATION_MS + 260);
    assert.equal(ctx.app.view.viewport.animating, false, 'landed');
    const after = vpOf(ctx);
    assert.ok(sameVp(after, plan), `landed on the phase plan: ${JSON.stringify(after)} vs ${JSON.stringify(plan)}`);
    assert.ok(ctx.app.view.phasesInView().includes(lane.id), 'the phase is marked in view in the index');
    assert.equal(ctx.app.getState().selection, null, 'a move to a phase selects nothing');
    press(ctx, 'ArrowDown');
    eq(ctx.app.getState().selection, { kind: 'node', id: ctx.app.index.roots(lane.id)[0] }, 'the first arrow selects the phase\'s first step');
  } finally {
    ctx.app.destroy();
  }
});

test('the move to a phase: the canvas-centre point travels straight while the zoom eases on a log scale; any other move stops it', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    const vp = ctx.app.view.viewport;
    const { w, h } = ctx.box();
    const from = vpOf(ctx);
    const to = { x: from.x - 600, y: from.y - 900, zoom: from.zoom * 0.5 };
    const centre = (v) => ({ x: (w / 2 - v.x) / v.zoom, y: (h / 2 - v.y) / v.zoom });
    const c0 = centre(from);
    const c1 = centre(to);
    vp.animateTo(to, 1200);
    await sleep(300);
    const mid = vpOf(ctx);
    const c = centre(mid);
    const t = (c.x - c0.x) / (c1.x - c0.x);
    assert.ok(t > 0 && t < 1, `mid-flight (${t.toFixed(2)})`);
    assert.ok(Math.abs((c.y - c0.y) / (c1.y - c0.y) - t) < 1e-6, 'on the straight line between the two centres');
    const e = Math.log(mid.zoom / from.zoom) / Math.log(to.zoom / from.zoom);
    assert.ok(Math.abs(e - t) < 1e-6, 'the zoom at the same eased step, on a log scale');
    // A pan stops it where it is.
    vp.panBy(5, 0);
    assert.equal(vp.animating, false);
    const stopped = vpOf(ctx);
    await sleep(150);
    eq(vpOf(ctx), stopped, 'nothing moves after the pan');
  } finally {
    ctx.app.destroy();
  }
});

test('reduced motion: the move to a phase is instant under VS Code\'s Reduce Motion and under the OS setting', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { reduce: true });
  try {
    shiftZero(ctx);
    press(ctx, 'End');
    const plan = await planFor(ctx, 5);
    press(ctx, 'Enter');
    assert.equal(ctx.app.view.viewport.animating, false);
    assert.ok(sameVp(vpOf(ctx), plan), 'landed at once (body.vscode-reduce-motion)');
  } finally {
    ctx.app.destroy();
  }
  const os = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    os.window.matchMedia = (query) => ({ matches: query === '(prefers-reduced-motion: reduce)', media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
    shiftZero(os);
    press(os, 'Home');
    press(os, 'ArrowDown');
    const plan = await planFor(os, 1);
    press(os, ' ');
    assert.equal(os.app.view.viewport.animating, false);
    assert.ok(sameVp(vpOf(os), plan), 'landed at once (prefers-reduced-motion)');
  } finally {
    os.app.destroy();
  }
});

test('a click on a block goes to its phase; a key the canvas acts on closes the overview first and then acts', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { reduce: true });
  try {
    shiftZero(ctx);
    const block = $(ctx, '.mlv-ovblock[data-block="2"]');
    block.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
    assert.equal(ctx.app.view.overviewOpen, false);
    assert.ok(sameVp(vpOf(ctx), await planFor(ctx, 2)));
    // r starts the review walk: the overview closes without moving the diagram, then the walk starts.
    shiftZero(ctx);
    press(ctx, 'r');
    assert.equal(ctx.app.view.overviewOpen, false);
    assert.equal(ctx.app.walk.active, true);
    press(ctx, 'r');
    // ? opens the shortcut sheet over the overview and leaves it open.
    shiftZero(ctx);
    press(ctx, '?');
    assert.equal(ctx.app.view.overviewOpen, true, 'the shortcut sheet keeps the overview');
  } finally {
    ctx.app.destroy();
  }
});

test('overview names: each block is a button named by its phase, counts and connections, described by its titles ending "… N more steps"', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { width: 541, bodyH: 740 });
  try {
    shiftZero(ctx);
    const overview = $(ctx, '.mlv-overview');
    assert.equal(overview.getAttribute('data-layout'), 'narrow');
    assert.equal(overview.getAttribute('data-scrolls'), 'true', 'six phases scroll a little beside the code');
    assert.equal($(ctx, '#' + overview.getAttribute('aria-labelledby')).textContent, 'Phase overview');
    assert.match($(ctx, '#' + overview.getAttribute('aria-describedby')).textContent, /^6 phases · 31 steps · 41 connections: /);
    let listed = 0;
    let counted = 0;
    for (const block of $$(ctx, '.mlv-ovblock')) {
      assert.equal(block.getAttribute('role'), 'button');
      assert.match(block.getAttribute('aria-label'), /^Phase \d of 6: Phase \d\. \d+ steps?( \([^)]*\))?\.( \d+ findings? touch(es)? this phase\.)?( .*)? Enter goes to this phase\.$/);
      const list = $(ctx, '#' + block.getAttribute('aria-describedby'));
      assert.ok(block.contains(list));
      const rows = Array.from(list.children);
      listed += rows.filter((li) => li.hasAttribute('data-node-ref')).length;
      const more = rows.find((li) => li.classList.contains('mlv-ovitem--more'));
      if (more) {
        assert.equal(rows[rows.length - 1], more, 'the count is the last row');
        counted += Number(/^… (\d+) more steps?$/.exec(more.textContent)[1]);
      }
      for (const li of rows) assert.ok(parseFloat(li.style.width) >= 200, 'a title row is at least 200 px wide at 541 px');
    }
    assert.equal(listed + counted, 31, 'the listed titles and the counts sum to the steps');
  } finally {
    ctx.app.destroy();
  }
});

test('overview marks: ◌ (a drawn dotted ring) for inferred, ? for unresolved, nothing for observed; the key draws the same ring', async () => {
  // A tall canvas, so every title of the yolov5-cc2 shape (2 inferred and 2 unresolved steps) is listed.
  const ctx = await mount(shapedWorkflow(YOLO_SHAPE), { width: 1440, bodyH: 2400 });
  try {
    shiftZero(ctx);
    assert.equal(ctx.app.view.overviewLayout().trimmed, false);
    const rows = $$(ctx, '.mlv-ovitem[data-node-ref]');
    assert.equal(rows.length, 59);
    const of = (basis) => rows.filter((li) => (li.getAttribute('data-basis') || 'observed') === basis);
    assert.equal(of('inferred').length, 2);
    assert.equal(of('unresolved').length, 2);
    for (const li of of('inferred')) {
      assert.ok(li.querySelector('.mlv-ovitem__mark .mlv-ovmark'), 'the ring');
      assert.equal(li.querySelector('.mlv-sr').textContent, 'inferred: ');
    }
    for (const li of of('unresolved')) {
      assert.equal(li.querySelector('.mlv-ovitem__mark').textContent, '?');
      assert.equal(li.querySelector('.mlv-sr').textContent, 'unresolved: ');
    }
    for (const li of of('observed')) {
      assert.equal(li.querySelector('.mlv-ovitem__mark').textContent, '');
      assert.equal(li.querySelector('.mlv-ovmark'), null, 'an observed step has no mark (the calm canvas)');
    }
    const key = $(ctx, '.mlv-overview__key');
    assert.ok(key.querySelector('.mlv-ovmark'));
    assert.equal(key.textContent, 'Arrows join a phase to the next; brackets on the right skip ahead (solid) or go back (dashed).  inferred, ? unresolved.');
    assert.match(CSS, /\.mlv-ovmark\{[^}]*border:1\.5px dotted currentColor/);
  } finally {
    ctx.app.destroy();
  }
});

test('the overview follows the severity toggles: hiding a severity removes its F labels from the titles', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE));
  try {
    shiftZero(ctx);
    const tagsOf = (sev) => $$(ctx, `.mlv-ovitem__tag[data-sev="${sev}"]`).length;
    const sev = ['high', 'medium', 'low'].find((s) => tagsOf(s) > 0);
    assert.ok(sev, 'some title carries a finding label');
    ctx.app.setFilters({ severities: ctx.app.filters.value.severities.filter((s) => s !== sev) });
    assert.equal(ctx.app.view.overviewOpen, true, 'a toggle leaves the overview open');
    assert.equal(tagsOf(sev), 0, 'the labels of a hidden severity go');
  } finally {
    ctx.app.destroy();
  }
});

for (const [name, opts] of PANELS) {
  test(`the phase index at ${name}: rows or pill inside the canvas (above the sheet), counts by the PR #14 rule, steps that sum`, async () => {
    const document = shapedWorkflow(VIT_SHAPE);
    const ctx = await mount(document, { ...opts, reduce: true });
    try {
      const root = ctx.app.view.phaseIndexElement;
      assert.ok(ctx.canvas.contains(root), 'inside the canvas');
      assert.equal(ctx.rail.contains(root), false, 'never on the rail or the bottom sheet');
      assert.equal($(ctx, '.mlv-world').contains(root), false, 'outside the world layer');
      const wide = opts.width >= 1000;
      assert.equal(root.getAttribute('data-form'), wide ? 'list' : 'pill');
      const rows = $$(ctx, '.mlv-phaseindex__row');
      assert.equal(rows.length, 6);
      const lanes = ctx.app.view.frameData.lanes;
      let steps = 0;
      rows.forEach((row, i) => {
        const lane = lanes[i];
        assert.equal(row.getAttribute('data-phase-id'), lane.id);
        assert.equal(row.querySelector('.mlv-phaseindex__num').textContent, String(i + 1));
        assert.equal(row.querySelector('.mlv-phaseindex__label').textContent, lane.label);
        assert.equal(row.querySelector('.mlv-phaseindex__steps').textContent, `${lane.nodeCount} ${lane.nodeCount === 1 ? 'step' : 'steps'}`);
        steps += lane.nodeCount;
        const counts = ctx.app.index.laneCounts(lane.id, ctx.app.filters.keep);
        for (const [sev, n] of Object.entries(counts)) {
          const cell = row.querySelector(`.mlv-cluster__item--${sev} .mlv-cluster__count`);
          if (n > 0) assert.equal(cell && cell.textContent, String(n), `${lane.id} ${sev}`);
          else assert.equal(cell, null);
        }
        assert.match(row.getAttribute('aria-label'), new RegExp(`^Phase ${i + 1} of 6: ${lane.label}, ${lane.nodeCount} steps`));
      });
      assert.equal(steps, 31);
      assert.equal($(ctx, '.mlv-phaseindex__total').textContent, '31 steps');
      // The phases in view are marked, and named so.
      const inView = ctx.app.view.phasesInView();
      assert.ok(inView.length >= 1);
      for (const row of rows) {
        const on = inView.includes(row.getAttribute('data-phase-id'));
        assert.equal(row.getAttribute('data-in-view') === 'true', on);
        assert.equal(/, in view$/.test(row.getAttribute('aria-label')), on);
      }
      if (!wide) {
        // The pill names the phase most in view, "k/6 label"; after a move it names the new one.
        ctx.app.view.goToPhase(lanes[3].id);
        assert.equal($(ctx, '.mlv-phaseindex__pillnum').textContent, '4/6');
        assert.equal($(ctx, '.mlv-phaseindex__pilllabel').textContent, lanes[3].label);
        assert.match($(ctx, '.mlv-phaseindex__pill').getAttribute('aria-label'), new RegExp(`^Phase 4 of 6 in view: ${lanes[3].label}\\. Show every phase\\.$`));
        // It covers the canvas's lower right corner, inside the canvas above the sheet.
        const covered = ctx.app.view.viewport.covered();
        const area = ctx.box();
        assert.ok(covered.y + covered.h <= area.h && covered.x + covered.w <= area.w, 'inside the canvas');
        assert.ok(covered.x >= 0 && covered.y > area.h / 2, 'in its lower part');
        // The pill opens the rows above itself; Escape closes them and keeps the selection.
        ctx.app.select({ kind: 'node', id: ctx.app.index.roots(lanes[3].id)[0] });
        $(ctx, '.mlv-phaseindex__pill').click();
        assert.equal(root.getAttribute('data-open'), 'true');
        assert.equal($(ctx, '.mlv-phaseindex__panel').hidden, false);
        press(ctx, 'Escape', {}, ctx.canvas);
        assert.equal(root.hasAttribute('data-open'), false);
        assert.ok(ctx.app.getState().selection, 'Escape closed the list first, not the selection');
      } else {
        // A row goes to its phase.
        rows[4].click();
        assert.ok(sameVp(vpOf(ctx), await planFor(ctx, 4)));
        assert.ok(ctx.app.view.phasesInView().includes(lanes[4].id));
      }
    } finally {
      ctx.app.destroy();
    }
  });
}

/**
 * Every path that brings a card into view, at one panel size: the card the keyboard or the reader
 * is on is wholly on the canvas and never under the phase index (`viewport.covered()`, the panel
 * or the pill).
 */
async function checkNeverCovered(document, name, opts) {
  const ctx = await mount(document, { ...opts, reduce: true });
  const failures = [];
  try {
    const view = ctx.app.view;
    const area = () => ctx.box();
    const check = (path, id) => {
      const covered = view.viewport.covered();
      assert.ok(covered, `${name} ${path}: the index is shown`);
      const shown = ctx.app.index.visibleRepresentative(id, view.collapsed);
      const b = view.frameData.boxes.get(shown);
      if (!b || ctx.app.index.isGroup(shown)) return;
      const s = onScreen(ctx, b);
      const { w, h } = area();
      const inside = s.x >= -0.5 && s.y >= -0.5 && s.x + s.w <= w + 0.5 && s.y + s.h <= h + 0.5;
      if (!inside || overlaps(s, covered)) failures.push(`${path} ${id}: card ${s.x.toFixed(0)},${s.y.toFixed(0)} ${s.w.toFixed(0)}x${s.h.toFixed(0)} canvas ${w}x${h} index ${covered.x.toFixed(0)},${covered.y.toFixed(0)} ${covered.w.toFixed(0)}x${covered.h.toFixed(0)}`);
    };
    // Step cards (a group's box is a frame around its steps, often larger than the canvas).
    const cards = Array.from(view.frameData.boxes.keys()).filter((id) => ctx.app.view.nodeElement(id) && !ctx.app.index.isGroup(id));
    // Arrow keys, from the first step through the diagram.
    ctx.app.select({ kind: 'node', id: cards[0] });
    view.nodeElement(cards[0]).focus();
    for (let i = 0; i < 40; i++) {
      press(ctx, i % 3 === 2 ? 'ArrowRight' : 'ArrowDown');
      const sel = ctx.app.getState().selection;
      if (sel && sel.kind === 'node') check('arrow', sel.id);
    }
    // The Outline (select with reveal), a search result, the host's reveal, for every card.
    for (const id of cards) {
      ctx.app.select({ kind: 'node', id }, { center: true, reveal: true, fromList: 'outline' });
      check('outline', id);
      ctx.app.activateHit({ kind: 'node', id });
      check('search', id);
      ctx.bridge.send({ v: 1, type: 'revealNode', nodeId: id, center: true });
      check('host reveal', id);
    }
    // A finding: its first cited card (the frame's anchor) is never under the index.
    for (const issue of ctx.app.graph.issues) {
      if (!issue.nodeIds.length) continue;
      ctx.app.focusIssue(issue.id);
      check('finding ' + issue.id, issue.nodeIds[0]);
    }
    // The review walk on every step it visits ("All" claims).
    assert.equal(ctx.app.walk.start('all'), true);
    for (let i = 0; i < 120 && ctx.app.walk.active; i++) {
      const claim = ctx.app.walk.current();
      if (claim && claim.kind === 'node') check('walk', claim.id);
      press(ctx, 'j', {}, ctx.canvas);
    }
  } finally {
    ctx.app.destroy();
  }
  return failures;
}

for (const [name, opts] of PANELS) {
  for (const [shapeName, shape] of [['vit-cc', VIT_SHAPE], ['yolov5-cc2', YOLO_SHAPE]]) {
    test(`the focused card is never under the phase index at ${name}, the ${shapeName} shape: arrows, Outline, search, host reveal, findings, the walk`, async () => {
      const failures = await checkNeverCovered(shapedWorkflow(shape), `${shapeName} ${name}`, opts);
      assert.deepEqual(failures, [], failures.slice(0, 8).join('\n'));
    });
  }
}
