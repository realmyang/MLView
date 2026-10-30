// A far connection in the review walk, one whose two end cards cannot both be shown.
// The walk keeps its source card, its lit line ends in a cap where it runs out of sight, and one
// line in the walk bar names the other card (src/far.ts, canvas/far.ts, app/far.ts).
//
// The document is SYNTHETIC (written here: three phases, sixteen steps, one of them a group of
// eight). The shipped stylesheet is read as text, because jsdom lays nothing out and resolves no
// custom property: the canvas is a stubbed 541 x 337 px box, the size the walk leaves of a 541 px
// panel, and what a rule paints is read with the cascade of test/helpers.mjs. A flow's passes end
// when the browser fires `animationend`; here the test dispatches it. The viewer is the built
// bundle, mounted in jsdom.
//
// Later tests hold one rule on every inferred and unresolved connection of two documents the
// repository holds (the test document d06-refinement and the skill's example), of the generated
// documents of helpers.mjs (its two shapes, and the stress fixture of the geometry golden) and of
// the document above: the cap is drawn with its line's own dash, and the reader is shown the
// line, not the cap in its place. The rules themselves, as pure functions, are in far.test.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cascadeWinner, loadBundle, recordingBridge, rendererRegressionWorkflow, REPO_ROOT, shapedWorkflow, SHAPE_79_CLAIMS, WEBVIEW_ROOT, SHAPE_176_CLAIMS } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');

/**
 * Setup (five steps in a row), Train (the group "Epoch loop": seven steps in a row and an eighth
 * under the first) and Save (two steps). In a 541 x 337 px canvas at reading size:
 *
 * - `c-val-sched` runs from the group's last step in the row back to the step under the first: far;
 * - `c-opts-ckpt` runs from phase 1 to phase 3 and carries a finding: far, drawn in its severity;
 * - `c-model-export` and `c-model-export-2` are two connections between the same two steps, the
 *   first observed, the second inferred: one line, drawn dashed; its two cards fit at 45% or more;
 * - `c-optim-ckpt` and `c-optim-ckpt-2` are such a pair too, observed and unresolved: one line,
 *   drawn dotted; its two cards fit only under the 45% a frame stops at: far;
 * - `c-loop-ckpt` starts at the open group, which is wider than the canvas: far;
 * - `c-opts-seed` joins two neighbours: both cards in view.
 */
function farDoc(revision = 'far-1') {
  const step = (id, label, phase, extra = {}) => ({ id, label, phase, basis: 'observed', evidence: ['e1'], ...extra });
  const link = (id, source, target, extra = {}) => ({ id, source, target, label: id, basis: 'observed', evidence: ['e1'], ...extra });
  return {
    workflowVersion: '1.0', title: 'Far connections', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: revision },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'setup', label: 'Setup' }, { id: 'train', label: 'Train' }, { id: 'save', label: 'Save' }],
    nodes: [
      step('opts', 'Options', 'setup'), step('seed', 'Seed', 'setup'), step('data', 'Dataset', 'setup'), step('model', 'Model', 'setup'), step('optim', 'Optimizer', 'setup'),
      step('loop', 'Epoch loop', 'train', { kind: 'group', evidence: [] }),
      step('batch', 'Next batch', 'train', { parent: 'loop' }), step('fwd', 'Forward', 'train', { parent: 'loop' }), step('loss', 'Loss', 'train', { parent: 'loop' }),
      step('back', 'Backward', 'train', { parent: 'loop' }), step('upd', 'Update', 'train', { parent: 'loop' }), step('log', 'Log', 'train', { parent: 'loop' }),
      step('val', 'Validate', 'train', { parent: 'loop' }), step('sched', 'Scheduler', 'train', { parent: 'loop' }),
      step('ckpt', 'Checkpoint', 'save'), step('export', 'Export', 'save'),
    ],
    edges: [
      link('c-opts-seed', 'opts', 'seed'), link('c-seed-data', 'seed', 'data'), link('c-data-model', 'data', 'model'), link('c-model-optim', 'model', 'optim'),
      link('c-batch-fwd', 'batch', 'fwd'), link('c-fwd-loss', 'fwd', 'loss'), link('c-loss-back', 'loss', 'back'), link('c-back-upd', 'back', 'upd'),
      link('c-upd-log', 'upd', 'log'), link('c-log-val', 'log', 'val'), link('c-val-sched', 'val', 'sched'),
      link('c-opts-ckpt', 'opts', 'ckpt'),
      link('c-model-export', 'model', 'export'), link('c-model-export-2', 'model', 'export', { basis: 'inferred', label: 'weights' }),
      link('c-optim-ckpt', 'optim', 'ckpt'), link('c-optim-ckpt-2', 'optim', 'ckpt', { basis: 'unresolved', label: 'state' }),
      link('c-loop-ckpt', 'loop', 'ckpt'),
      link('c-ckpt-export', 'ckpt', 'export'),
    ],
    findings: [{ id: 'f-save', title: 'No resume', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c-opts-ckpt'], basis: 'observed', evidence: ['e1'] }],
    evidence: [{ id: 'e1', file: 'train.py', line: 3, endLine: 4, quote: 'x()' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

/** The canvas the walk leaves of a 541 x 798 px panel, as measured by capture.mjs (`canvasBox`). */
const CANVAS = { w: 541, h: 337 };

async function mount(document = farDoc(), opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  if (opts.bodyClass) ctx.document.body.classList.add(opts.bodyClass);
  // The canvas has its size before the viewer mounts, as on a page that has been laid out.
  const size = { ...(opts.canvas || CANVAS) };
  const native = ctx.window.HTMLElement.prototype.getBoundingClientRect;
  ctx.window.HTMLElement.prototype.getBoundingClientRect = function () {
    return this.classList.contains('mlv-canvas') ? { x: 0, y: 0, top: 0, left: 0, width: size.w, height: size.h, right: size.w, bottom: size.h } : native.call(this);
  };
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 541;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: 798, right: width, bottom: 798 });
  // `state`: what the page saved, for a page loaded again in its panel to mount from (a remount).
  const bridge = recordingBridge(ctx.window, 'vscode', opts.state ? { state: opts.state } : {});
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.focus();
  /** The canvas takes another size, as when the panel or the bar under it does. */
  const resize = (w, h) => {
    size.w = w;
    size.h = h;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  /** The panel takes another width. */
  const panel = (w) => {
    width = w;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  return { ...ctx, root, bridge, app, canvas, resize, panel };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const live = (ctx) => $(ctx, '.mlv-root > [aria-live]').textContent;
const plain = (value) => JSON.parse(JSON.stringify(value));
const viewport = (ctx) => plain(ctx.app.getState().viewport);

/** Start the All claims walk at its first claim (`r`, the filter, `k`) and press `j` until it is on claim `id`. */
function walkTo(ctx, id) {
  if (!ctx.app.walk.active) {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 60 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
  }
  for (let i = 0; i < 60 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
  assert.equal(ctx.app.walk.current().id, id, 'the walk reached ' + id);
}

/** Press `k` until the walk is on claim `id` again, which it has passed. */
function walkBackTo(ctx, id) {
  for (let i = 0; i < 60 && ctx.app.walk.current().id !== id; i++) press(ctx, 'k', {}, ctx.canvas);
  assert.equal(ctx.app.walk.current().id, id, 'the walk went back to ' + id);
}

/** The drawn line of connection `id` (the line of the route that carries it). */
function lineOf(ctx, id) {
  const route = ctx.app.view.routes.find((r) => r.ids.includes(id));
  return route ? $(ctx, '.mlv-canvas [data-edge-id="' + route.id + '"]') : null;
}

/** The far line when it is on show, and the caps on the canvas. */
const farLine = (ctx) => {
  const line = $(ctx, '.mlv-walkbar__far');
  return line && !line.hidden ? line : null;
};
const caps = (ctx) => $$(ctx, '.mlv-farcaps .mlv-farcap');
const barGlyph = (ctx) => $(ctx, '.mlv-walkbar__farglyph');
/** The value the stylesheet gives the cap's colour on `element`. */
const capColour = (element) => cascadeWinner(CSS, element, '--mlv-cap').value;

/** The browser's `animationend` on the lit line's charge: its passes are done. */
function endCharge(ctx, line) {
  const charge = line.querySelector('.mlv-edge__charge');
  assert.ok(charge, 'precondition: a charge runs along the line');
  charge.dispatchEvent(new ctx.window.Event('animationend'));
}

/* ── the cap's colour is the colour its line is drawn in ─────────────── */

test("the cap and its copy in the walk bar are the accent while the line's charge runs, and the line's own colour once it has settled", async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-val-sched');
    const line = lineOf(ctx, 'c-val-sched');
    assert.ok(farLine(ctx), 'precondition: the connection is far');
    assert.equal(caps(ctx).length, 1);
    const cap = caps(ctx)[0];
    // Full motion: the selected line is the accent (edge.css) for the two passes of its charge.
    assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
    assert.ok(line.classList.contains('is-flowing--pulse') && !line.classList.contains('is-flow-settled'));
    assert.equal(cap.classList.contains('is-lit'), false, 'the cap does not take the tone before its line does');
    assert.equal(barGlyph(ctx).classList.contains('is-lit'), false);
    assert.equal(capColour(cap), 'var(--mlv-accent)');
    assert.equal(capColour(barGlyph(ctx)), 'var(--mlv-accent)');
    // The passes are done: the line is lit in its phase tone (flow.css), and so is its cap.
    endCharge(ctx, line);
    assert.ok(line.classList.contains('is-flow-settled'));
    assert.equal(cap.classList.contains('is-lit'), true);
    assert.equal(barGlyph(ctx).classList.contains('is-lit'), true);
    assert.equal(cap.getAttribute('data-phase-tone'), line.getAttribute('data-phase-tone'));
    assert.equal(capColour(cap), 'var(--mlv-stage, var(--mlv-accent))');
    assert.equal(capColour(barGlyph(ctx)), 'var(--mlv-stage, var(--mlv-accent))');
    // Shift+A plays the flow again from its first pass: the line is the accent again.
    press(ctx, 'A', { shiftKey: true }, ctx.canvas);
    assert.equal(lineOf(ctx, 'c-val-sched').classList.contains('is-flow-settled'), false);
    assert.equal(caps(ctx)[0].classList.contains('is-lit'), false);
    assert.equal(barGlyph(ctx).classList.contains('is-lit'), false);
    endCharge(ctx, lineOf(ctx, 'c-val-sched'));
    assert.equal(caps(ctx)[0].classList.contains('is-lit'), true);
    // The charge of another line takes this line's away (a hover): it is the accent until its own returns.
    ctx.app.view.flow.pulse(ctx.app.view.routes.find((r) => r.id === 'c-opts-seed'));
    assert.equal(lineOf(ctx, 'c-val-sched').classList.contains('is-flowing--pulse'), false);
    assert.equal(caps(ctx)[0].classList.contains('is-lit'), false);
    ctx.app.view.flow.stop();
    endCharge(ctx, lineOf(ctx, 'c-val-sched'));
    assert.equal(caps(ctx)[0].classList.contains('is-lit'), true);
    // With the flow layer off a selected line stays the accent.
    press(ctx, 'a', {}, ctx.canvas);
    assert.equal(ctx.canvas.getAttribute('data-flow'), 'off');
    assert.equal(caps(ctx)[0].classList.contains('is-lit'), false);
    assert.equal(barGlyph(ctx).classList.contains('is-lit'), false);
  } finally {
    ctx.app.destroy();
  }
});

test('where nothing moves the line is lit in its own colour at once, and so is its cap; in high contrast that colour is ink', async () => {
  const ctx = await mount(farDoc(), { bodyClass: 'vscode-reduce-motion' });
  try {
    walkTo(ctx, 'c-val-sched');
    assert.equal(ctx.canvas.getAttribute('data-flow'), 'static');
    const cap = caps(ctx)[0];
    assert.equal(cap.classList.contains('is-lit'), true);
    assert.equal(barGlyph(ctx).classList.contains('is-lit'), true);
    assert.equal(capColour(cap), 'var(--mlv-stage, var(--mlv-accent))');
    // High contrast: the lit line is ink (flow.css); a selected line not yet lit is the accent there too.
    ctx.document.body.classList.add('vscode-high-contrast');
    assert.equal(capColour(cap), 'var(--mlv-text)');
    cap.classList.remove('is-lit');
    assert.equal(capColour(cap), 'var(--mlv-accent)');
  } finally {
    ctx.app.destroy();
  }
});

test("a finding's line is drawn in its severity before and after its charge, and so is its cap", async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const line = lineOf(ctx, 'c-opts-ckpt');
    assert.ok(line.classList.contains('has-issue'));
    const cap = caps(ctx)[0];
    assert.equal(cap.getAttribute('data-sev'), 'medium');
    assert.equal(cap.classList.contains('is-lit'), false);
    assert.equal(capColour(cap), 'var(--mlv-sev)');
    assert.equal(capColour(barGlyph(ctx)), 'var(--mlv-sev)');
    endCharge(ctx, line);
    assert.equal(cap.classList.contains('is-lit'), true);
    assert.equal(capColour(cap), 'var(--mlv-sev)');
  } finally {
    ctx.app.destroy();
  }
});

/* ── a line drawn dashed or dotted, whichever of its connections the walk is on ── */

test('a line that carries an observed and an unresolved connection is drawn dotted, and for either connection its cap and the copy in the bar are dotted and the picture is the same; the words say what each connection is', async () => {
  const ctx = await mount(farDoc(), { bodyClass: 'vscode-reduce-motion' });
  try {
    // Two connections between the same two steps are one line, drawn with the less certain basis.
    const route = ctx.app.view.routes.find((r) => r.ids.includes('c-optim-ckpt'));
    assert.deepEqual(Array.from(route.ids), ['c-optim-ckpt', 'c-optim-ckpt-2']);
    assert.equal(lineOf(ctx, 'c-optim-ckpt').getAttribute('data-basis'), 'unresolved');

    // The observed one: its line is dotted, so its cap is. Nothing calls the connection unresolved.
    walkTo(ctx, 'c-optim-ckpt');
    assert.equal(ctx.app.index.edgeById.get('c-optim-ckpt').basis, 'observed');
    assert.ok(farLine(ctx), 'precondition: the connection is far');
    assert.equal(caps(ctx).length, 1);
    assert.equal(caps(ctx)[0].getAttribute('data-basis'), 'unresolved', 'a solid cap on a dotted line is another basis than its line');
    assert.equal(cascadeWinner(CSS, caps(ctx)[0], 'border-style').value, 'dotted');
    assert.equal(barGlyph(ctx).getAttribute('data-basis'), 'unresolved');
    assert.equal(farLine(ctx).querySelector('.mlv-walkbar__fartag'), null, 'no basis tag: the connection is observed');
    assert.doesNotMatch(farLine(ctx).getAttribute('aria-label'), /unresolved/);
    assert.doesNotMatch(live(ctx), /unresolved/);
    const observed = { viewport: viewport(ctx), cap: [caps(ctx)[0].style.left, caps(ctx)[0].style.top] };

    // The unresolved one, on the same line: the same picture, and said to be unresolved.
    walkTo(ctx, 'c-optim-ckpt-2');
    assert.ok(farLine(ctx));
    assert.equal(caps(ctx)[0].getAttribute('data-basis'), 'unresolved');
    assert.equal(barGlyph(ctx).getAttribute('data-basis'), 'unresolved');
    assert.equal(farLine(ctx).querySelector('.mlv-walkbar__fartag').textContent, '? unresolved');
    assert.match(farLine(ctx).getAttribute('aria-label'), /^\? unresolved connection\. /);
    assert.deepEqual({ viewport: viewport(ctx), cap: [caps(ctx)[0].style.left, caps(ctx)[0].style.top] }, observed, 'the line gets the same room for both');

    // A line of its own that is observed keeps a solid cap.
    walkTo(ctx, 'c-val-sched');
    assert.equal(caps(ctx)[0].hasAttribute('data-basis'), false);
    assert.equal(barGlyph(ctx).hasAttribute('data-basis'), false);
    assert.equal(cascadeWinner(CSS, caps(ctx)[0], 'border-style'), null, 'the solid border of the cap as it is declared');
  } finally {
    ctx.app.destroy();
  }
});

test('a dashed line whose two cards fit at 45% or more is framed whole for either of its connections, with no cap', async () => {
  const ctx = await mount();
  try {
    assert.equal(lineOf(ctx, 'c-model-export').getAttribute('data-basis'), 'inferred');
    for (const id of ['c-model-export', 'c-model-export-2']) {
      walkTo(ctx, id);
      const ends = ctx.app.view.far.ends(id);
      assert.equal(ends.source.inView && ends.target.inView, true, id + ': both cards are on the canvas');
      assert.equal(farLine(ctx), null, id);
      assert.equal(caps(ctx).length, 0, id);
      assert.equal($(ctx, '.mlv-walkbar__faridle').textContent, 'Both ends in view');
      const zoom = viewport(ctx).zoom;
      assert.ok(zoom >= 0.45 && zoom < 0.62, id + ': framed at ' + zoom);
    }
  } finally {
    ctx.app.destroy();
  }
});

/* ── a source that is an open group too large for the canvas ─────────── */

/** A world rectangle in canvas pixels. */
function drawn(ctx, box) {
  const vp = viewport(ctx);
  return { x: box.x * vp.zoom + vp.x, y: box.y * vp.zoom + vp.y, w: box.w * vp.zoom, h: box.h * vp.zoom };
}
/** Whether a rectangle in canvas pixels is whole on a canvas of `size`. */
const whole = (r, size) => r.x >= -0.5 && r.y >= -0.5 && r.x + r.w <= size.w + 0.5 && r.y + r.h <= size.h + 0.5;

/** Each cap on the canvas as a rectangle in canvas pixels: 22 x 14 px along its line. */
function capBoxes(ctx) {
  return caps(ctx).map((cap) => {
    const upright = cap.classList.contains('mlv-farcap--v');
    return { x: parseFloat(cap.style.left), y: parseFloat(cap.style.top), w: upright ? 14 : 22, h: upright ? 22 : 14 };
  });
}

/** The cards drawn over the lines, in canvas pixels: every step and every folded group. */
function cardBoxes(ctx) {
  const cards = [];
  for (const box of ctx.app.view.frame.boxes.values()) if (!ctx.app.index.isGroup(box.id) || ctx.app.view.collapsed.has(box.id)) cards.push(drawn(ctx, box));
  return cards;
}

/** The open group's box, the start of its header (as wide as a card) and the point its line leaves it. */
function groupParts(ctx, id, group) {
  const box = ctx.app.view.frame.boxes.get(group);
  const card = ctx.app.view.frame.boxes.get('opts');
  const start = ctx.app.view.routes.find((r) => r.ids.includes(id)).points[0];
  return {
    box: drawn(ctx, box),
    header: drawn(ctx, { x: box.x, y: box.y, w: card.w, h: box.headerH }),
    start: drawn(ctx, { x: start.x, y: start.y, w: 0, h: 0 }),
  };
}

test("of a source that is an open group too large for the canvas the walk shows the place its line leaves it, and the start of the group's header with it when the canvas has room for both", async () => {
  // 1000 x 337 px: the group is wider than the canvas, and its header's start and the place its
  // line leaves it fit side by side.
  const wide = { w: 1000, h: 337 };
  let ctx = await mount(farDoc(), { canvas: wide, width: 1000 });
  try {
    walkTo(ctx, 'c-loop-ckpt');
    let parts = groupParts(ctx, 'c-loop-ckpt', 'loop');
    assert.ok(parts.box.w > wide.w, 'precondition: the group is wider than the canvas');
    assert.equal(whole(parts.start, wide), true, 'the place the line leaves the group is on the canvas');
    assert.equal(whole(parts.header, wide), true, "and the start of the group's header, which names it");
    const ends = ctx.app.view.far.ends('c-loop-ckpt');
    assert.deepEqual([ends.source.port, ends.source.inView, ends.keep], [true, true, 'source']);
    assert.match(lineOf(ctx, 'c-loop-ckpt').getAttribute('class'), /is-selected/);

    // A taller canvas keeps both; a canvas with no room for both keeps the place the line leaves.
    ctx.resize(1000, 500);
    parts = groupParts(ctx, 'c-loop-ckpt', 'loop');
    assert.equal(whole(parts.start, { w: 1000, h: 500 }) && whole(parts.header, { w: 1000, h: 500 }), true, 'both after the canvas grew');
    ctx.resize(541, 337);
    parts = groupParts(ctx, 'c-loop-ckpt', 'loop');
    assert.equal(whole(parts.start, CANVAS), true, 'the place the line leaves the group after the canvas shrank');
    assert.equal(ctx.app.view.far.ends('c-loop-ckpt').source.inView, true);
  } finally {
    ctx.app.destroy();
  }

  // 541 x 337 px: no room for both, so only the place the line leaves the group.
  ctx = await mount();
  try {
    walkTo(ctx, 'c-loop-ckpt');
    const parts = groupParts(ctx, 'c-loop-ckpt', 'loop');
    assert.equal(whole(parts.start, CANVAS), true);
    assert.equal(whole(parts.header, CANVAS), false, 'the header is 889 px from that place');
    assert.equal(ctx.app.view.far.ends('c-loop-ckpt').source.inView, true);
    assert.ok(farLine(ctx), 'the connection is far');
    assert.equal(caps(ctx).length, 1);
  } finally {
    ctx.app.destroy();
  }
});

/* ── a look at the far end ends with the walk, the document or the filter it belonged to ── */

/** What the walk shows of connection `id`: the bar's place and line, the caps, and the end the view holds. */
function farState(ctx, id) {
  const ends = ctx.app.view.far.ends(id);
  const line = farLine(ctx);
  return {
    walking: ctx.app.walk.active,
    claim: ctx.app.walk.active ? ctx.app.walk.current().id : null,
    place: $(ctx, '.mlv-walkbar__postext').textContent,
    line: line ? $(ctx, '.mlv-walkbar__farverb').textContent + ' ' + $(ctx, '.mlv-walkbar__fartitle').textContent : null,
    caps: caps(ctx).map((cap) => cap.getAttribute('data-far-end')),
    keep: ends ? ends.keep : null,
    source: !!ends && ends.source.inView,
    target: !!ends && ends.target.inView,
  };
}

/** Walk onto the far connection `id` and look at its far end (key o). Returns the picture left at its source. */
function lookAtFarEnd(ctx, id) {
  walkTo(ctx, id);
  const left = viewport(ctx);
  press(ctx, 'o', {}, ctx.canvas);
  const state = farState(ctx, id);
  assert.deepEqual([state.keep, state.source, state.target], ['target', false, true], 'precondition: the view is at the far end of ' + id);
  assert.match(state.place, / · far end$/);
  assert.match(state.line, /^Back to /);
  assert.deepEqual(state.caps, ['source']);
  return left;
}

/**
 * The walk is on `id` as a step onto it leaves it: its source card kept, the line to the far card,
 * no "far end", and (unless `capped` is false) the cap where its lit line goes out of sight.
 */
function atSource(ctx, id, title, capped = true) {
  const state = farState(ctx, id);
  assert.deepEqual([state.claim, state.keep, state.source, state.target], [id, 'source', true, false], id + ' is shown from its source');
  assert.equal(state.line, 'Go to ' + title);
  assert.doesNotMatch(state.place, /far end/);
  if (capped) assert.deepEqual(state.caps, ['target']);
}

/** Nothing of a far connection is on show: no line in the bar, no cap, no end held. */
function nothingFar(ctx, id) {
  const state = farState(ctx, id);
  assert.deepEqual([state.line, state.caps, state.keep], [null, [], null]);
  assert.doesNotMatch(state.place, /far end/);
}

const filterButton = (ctx, filter) => $(ctx, '.mlv-walkbar__filter[data-walk-filter="' + filter + '"]');

/** The far-connection document as its next revision, with one more step in Setup and a connection to it. */
function nextRevision() {
  const next = farDoc('far-2');
  next.nodes.splice(5, 0, { id: 'amp', label: 'AMP scaler', phase: 'setup', basis: 'observed', evidence: ['e1'] });
  next.edges.push({ id: 'c-optim-amp', source: 'optim', target: 'amp', label: 'scaler', basis: 'observed', evidence: ['e1'] });
  return next;
}

test('another revision ends the walk and the look at the far end with it; the walk of the new revision is the one a fresh panel gives, and its far line counts the steps of that revision', async () => {
  const ctx = await mount();
  const fresh = await mount(nextRevision());
  const distance = (panel) => $(panel, '.mlv-walkbar__fardistance').textContent;
  try {
    walkTo(ctx, 'c-opts-ckpt');
    assert.equal(distance(ctx), '13 steps later');
    lookAtFarEnd(ctx, 'c-val-sched');
    ctx.app.setWorkflow(nextRevision());
    assert.equal(ctx.app.walk.active, false);
    assert.equal($(ctx, '.mlv-walkbar').hidden, true);
    nothingFar(ctx, 'c-val-sched');

    // The walk of the new revision, in this panel and in one that never showed the old one. The
    // new revision has a step more between the two cards of this connection.
    for (const panel of [ctx, fresh]) {
      walkTo(panel, 'c-opts-ckpt');
      assert.equal(distance(panel), '14 steps later');
      assert.match(farLine(panel).getAttribute('aria-label'), /^Go to the far end: Checkpoint, 14 steps later, /);
      walkTo(panel, 'c-val-sched');
      atSource(panel, 'c-val-sched', 'Scheduler');
    }
    assert.deepEqual(viewport(ctx), viewport(fresh));
    for (const panel of [ctx, fresh]) press(panel, 'j', {}, panel.canvas);
    assert.deepEqual([farState(ctx, 'c-val-sched'), viewport(ctx)], [farState(fresh, 'c-val-sched'), viewport(fresh)], 'and the step after it');
  } finally {
    ctx.app.destroy();
    fresh.app.destroy();
  }
});

test('the same revision again keeps the reader at the far end, and key o still goes back to the source', async () => {
  const ctx = await mount();
  try {
    lookAtFarEnd(ctx, 'c-val-sched');
    const far = viewport(ctx);
    ctx.app.setWorkflow(farDoc());
    assert.equal(ctx.app.walk.active, true, 'a refresh is not another revision');
    assert.deepEqual(viewport(ctx), far, 'and not another picture');
    const state = farState(ctx, 'c-val-sched');
    assert.deepEqual([state.claim, state.keep, state.target], ['c-val-sched', 'target', true]);
    assert.match(state.place, / · far end$/);
    assert.match(state.line, /^Back to Validate/);
    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-val-sched', 'Scheduler');
  } finally {
    ctx.app.destroy();
  }
});

test('a page rebuilt while the reader looked at the far end resumes the walk at the source of its connection', async () => {
  const first = await mount();
  let saved;
  try {
    lookAtFarEnd(first, 'c-val-sched');
    saved = plain(first.app.getState());
    assert.deepEqual(Object.keys(saved).filter((key) => /far|look|held/i.test(key)), [], 'the look is not part of the saved state');
    assert.deepEqual(saved.walk, { filter: 'all', claim: { kind: 'edge', id: 'c-val-sched' }, active: true });
  } finally {
    first.app.destroy();
  }
  const again = await mount(farDoc(), { state: saved });
  try {
    assert.equal(again.app.walk.active, true);
    atSource(again, 'c-val-sched', 'Scheduler');
  } finally {
    again.app.destroy();
  }
});

test('ending the walk at the far end leaves the picture and forgets the look; r shows the connection from its source again', async () => {
  const ctx = await mount();
  try {
    lookAtFarEnd(ctx, 'c-val-sched');
    const far = viewport(ctx);
    press(ctx, 'Escape', {}, ctx.canvas);
    assert.equal(ctx.app.walk.active, false);
    assert.equal($(ctx, '.mlv-walkbar').hidden, true);
    assert.deepEqual(viewport(ctx), far, 'ending the walk moves nothing');
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c-val-sched' });
    nothingFar(ctx, 'c-val-sched');
    // Key o is the walk's: without a walk it does nothing to the picture.
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), far);

    press(ctx, 'r', {}, ctx.canvas);
    atSource(ctx, 'c-val-sched', 'Scheduler');
    // A look and back again is whole: the way back is to the picture this walk left, not the old one.
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
  } finally {
    ctx.app.destroy();
  }
});

test('a filter chosen at the far end shows the claim from its source again, and reaches another claim as if the reader had not looked', async () => {
  // The new filter holds the claim: the picture the reader left at its source, exactly.
  let ctx = await mount();
  try {
    const left = lookAtFarEnd(ctx, 'c-optim-ckpt-2');
    filterButton(ctx, 'notObserved').click();
    assert.equal(ctx.app.walk.filter, 'notObserved');
    atSource(ctx, 'c-optim-ckpt-2', 'Checkpoint');
    assert.deepEqual(viewport(ctx), left);
  } finally {
    ctx.app.destroy();
  }
  // The new filter does not hold it: the claim the walk moves to is shown as from the source.
  ctx = await mount();
  const plainWalk = await mount();
  try {
    lookAtFarEnd(ctx, 'c-val-sched');
    walkTo(plainWalk, 'c-val-sched');
    for (const panel of [ctx, plainWalk]) filterButton(panel, 'notObserved').click();
    assert.notEqual(ctx.app.walk.current().id, 'c-val-sched', 'precondition: Not observed does not hold the claim');
    const id = ctx.app.walk.current().id;
    assert.deepEqual([farState(ctx, id), viewport(ctx)], [farState(plainWalk, id), viewport(plainWalk)]);
    assert.equal(ctx.app.view.far.ends('c-val-sched').keep, null, 'no end of the claim it left is held');
  } finally {
    ctx.app.destroy();
    plainWalk.app.destroy();
  }
});

test('a claim the reader selects at the far end takes the walk with it and the look is forgotten', async () => {
  const ctx = await mount();
  try {
    lookAtFarEnd(ctx, 'c-val-sched');
    const far = viewport(ctx);
    // Another far connection, so the walk is on a connection again at once.
    ctx.app.select({ kind: 'edge', id: 'c-opts-ckpt' });
    assert.equal(ctx.app.walk.current().id, 'c-opts-ckpt', 'the walk follows the selection');
    assert.deepEqual(viewport(ctx), far, 'a selection moves nothing');
    // Nothing of the look is left: no end is held and the place does not say "far end". The line
    // and the caps on show are the new connection's own; both its cards are out of view here.
    const state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.line, state.caps, state.keep, state.source, state.target], ['Back to Options', ['source', 'target'], null, false, false]);
    assert.doesNotMatch(state.place, /far end/);
    assert.equal(ctx.app.view.far.ends('c-val-sched').keep, null);
    // The next step starts from this picture, not from the one left at the first connection's source.
    const control = await mount();
    try {
      walkTo(control, 'c-val-sched');
      control.app.view.viewport.set(far);
      control.app.select({ kind: 'edge', id: 'c-opts-ckpt' });
      for (const panel of [ctx, control]) press(panel, 'j', {}, panel.canvas);
      assert.deepEqual([ctx.app.walk.current().id, viewport(ctx)], [control.app.walk.current().id, viewport(control)]);
    } finally {
      control.app.destroy();
    }
  } finally {
    ctx.app.destroy();
  }
});

/* ── the line is on show for as long as an end is out of view ────────── */

test('the far line and the cap come back when an end of the walk\'s connection leaves the view again, and ← and → do not take the walk off it meanwhile', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    const step = viewport(ctx);
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection)], ['c-opts-ckpt', { kind: 'edge', id: 'c-opts-ckpt' }], what);
    const bothInView = (what) => {
      assert.equal(farLine(ctx), null, what);
      assert.equal(caps(ctx).length, 0, what);
      assert.deepEqual([$(ctx, '.mlv-walkbar__faridle').hidden, $(ctx, '.mlv-walkbar__faridle').textContent], [false, 'Both ends in view'], what);
    };

    // The reader zooms out until both cards are on the canvas, and back to the picture of the step.
    ctx.app.view.fitWhole();
    bothInView('zoomed out');
    ctx.app.view.viewport.set(step);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    assert.equal($(ctx, '.mlv-walkbar__faridle').hidden, true);
    // ← is towards the source, which is in view: said, and the walk stays (the card is not selected).
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    still('after ←');
    assert.deepEqual(viewport(ctx), step);

    // The canvas grows until both cards show, and shrinks back: no pan, no zoom, no click.
    ctx.resize(541, 900);
    bothInView('on the taller canvas');
    ctx.resize(541, 337);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    still('after ← again');

    // A connection the step showed with both cards: once the reader pans one of them out of view
    // the bar's line names it and the lit line ends in a cap; back in view, the bar says so again.
    walkTo(ctx, 'c-seed-data');
    bothInView('c-seed-data at its step');
    const near = viewport(ctx);
    const data = drawn(ctx, ctx.app.view.frame.boxes.get('data'));
    ctx.app.view.viewport.panBy(CANVAS.w - data.x + 30, 0);
    let state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line, state.caps], [true, false, 'Go to Dataset', ['target']]);
    ctx.app.view.viewport.set(near);
    bothInView('c-seed-data back in view');
  } finally {
    ctx.app.destroy();
  }
});

test('a connection the step shows with both cards is not a far one, however the reader pans it: a card moved out of view is named with "Go to", key o shows the two cards together again, the place never says "far end", and ← and → select a card that is in view', async () => {
  const ctx = await mount();
  try {
    const card = (id) => drawn(ctx, ctx.app.view.frame.boxes.get(id));
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection)], ['c-seed-data', { kind: 'edge', id: 'c-seed-data' }], what);
    // Seed to Dataset, two neighbours: the step shows both cards, and they fit the canvas together.
    walkTo(ctx, 'c-seed-data');
    let state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line, state.keep, ctx.app.view.far.ends('c-seed-data').fits], [true, true, null, null, true]);

    // The far card panned out of view: ← is towards the source card, which is in view, and selects
    // it, and the walk goes with it to that step's claim.
    ctx.app.view.viewport.panBy(CANVAS.w - card('data').x + 30, 0);
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line, state.caps, state.place], [true, false, 'Go to Dataset', ['target'], '5/35']);
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: 'seed' }, 'seed']);

    // The reader drags the diagram to the left until 4 px of the source card are cut off. Both
    // cards are still on the canvas: this is not the far end, and the source is no way back.
    walkTo(ctx, 'c-seed-data');
    pressBackground(ctx, [[100 - card('seed').x - 4, 100]]);
    assert.equal(Math.round(card('seed').x), -4, 'precondition');
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.claim, state.source, state.target, state.keep], ['c-seed-data', false, true, null]);
    assert.deepEqual([state.place, state.line, state.caps], ['5/35', 'Go to Seed', []]);
    assert.equal($(ctx, '.mlv-walkbar__posspoken').textContent, 'Claim 5 of 35, All claims');
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the source: Seed, previous step, partly in view to the left');
    assert.equal(farLine(ctx).title, 'Seed. Click, Enter or key o goes there. The walk stays on this claim.');
    assert.equal($(ctx, '.mlv-walkbar__faridle').hidden, true, 'nothing says both ends are in view');
    // → is towards the far card, which is in view: it selects the card, as on any connection.
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: 'data' }, 'data']);
    assert.equal(live(ctx), 'Selected step Dataset, Setup phase, train.py line 3.');

    // Dragged on until the source card has left the canvas: the same words, and a cap where the
    // line leaves. Key o shows the source card again, and with it both cards: it says that both
    // ends are in view, as it does when the far card was the one out of view. The view was never
    // at a far end, so there is no source to be back at.
    walkBackTo(ctx, 'c-seed-data');
    pressBackground(ctx, [[100 - card('seed').x - card('seed').w - 5, 100]]);
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.place, state.line, state.caps], [false, true, '5/35', 'Go to Seed', ['source']]);
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.keep, state.source, state.target, state.line, state.place], [null, true, true, null, '5/35']);
    assert.equal($(ctx, '.mlv-walkbar__faridle').textContent, 'Both ends in view');
    still('after key o');

    // Key o towards the far card shows it beside the source card, where it fits: this is no far
    // end and there is no way back from it, so neither the tooltip nor the announcement names one.
    ctx.app.view.viewport.panBy(CANVAS.w - card('data').x + 30, 0);
    assert.equal(farState(ctx, 'c-seed-data').line, 'Go to Dataset');
    assert.equal(farLine(ctx).title, 'Dataset. About 0.7 screens right. Click, Enter or key o goes there. The walk stays on this claim.');
    press(ctx, 'o', {}, ctx.canvas);
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.keep, state.source, state.target, state.place, state.line], [null, true, true, '5/35', null]);
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    still('after key o towards the far card');
  } finally {
    ctx.app.destroy();
  }
});

/** The share of the line of connection `id` that lies on a canvas of `size`, by length. */
function shareOnCanvas(ctx, id, size) {
  const vp = viewport(ctx);
  const points = ctx.app.view.routes.find((r) => r.ids.includes(id)).points.map((p) => ({ x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y }));
  let on = 0;
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const n = Math.max(1, Math.ceil(length));
    for (let k = 0; k < n; k++) {
      const p = { x: a.x + ((b.x - a.x) * (k + 0.5)) / n, y: a.y + ((b.y - a.y) * (k + 0.5)) / n };
      total += length / n;
      if (p.x >= 0 && p.x <= size.w && p.y >= 0 && p.y <= size.h) on += length / n;
    }
  }
  return total ? Math.round((on / total) * 100) / 100 : 0;
}

/** Whether both cards of connection `id` are whole on the canvas and clear of the phase index, each by its own box. */
function bothWhole(ctx, id) {
  const edge = ctx.app.index.edgeById.get(id);
  const boxes = ctx.app.view.frame.boxes;
  return ctx.app.view.far.inView(boxes.get(edge.source)) && ctx.app.view.far.inView(boxes.get(edge.target));
}

test('on a connection whose two cards fit the canvas together, key o, the bar\'s line, a cap and the arrow towards the card out of view show both cards again by a pan: after a drag that cut the far card by 4 px, after one that cut both, and on a dashed line framed under reading size; the view then holds no end', async () => {
  const ctx = await mount();
  try {
    const card = (id) => drawn(ctx, ctx.app.view.frame.boxes.get(id));
    const both = (id, zoom, what) => {
      const state = farState(ctx, id);
      assert.equal(bothWhole(ctx, id), true, what + ': both cards are whole on the canvas');
      assert.deepEqual([state.claim, state.keep, state.line, state.caps, state.place.includes('far end'), viewport(ctx).zoom], [id, null, null, [], false, zoom], what);
      assert.deepEqual([$(ctx, '.mlv-walkbar__faridle').hidden, $(ctx, '.mlv-walkbar__faridle').textContent], [false, 'Both ends in view'], what);
      assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id }, what);
    };
    walkTo(ctx, 'c-seed-data');
    const step = viewport(ctx);
    both('c-seed-data', step.zoom, 'at the step');
    /** The far card cut by 4 px at the canvas's right edge, as a drag of a few pixels leaves it. */
    const cutFar = () => {
      ctx.app.view.viewport.set(step);
      pressBackground(ctx, [[100 + CANVAS.w - card('data').x - card('data').w + 4, 100]]);
      const state = farState(ctx, 'c-seed-data');
      assert.deepEqual([Math.round(card('data').x + card('data').w - CANVAS.w), state.source, state.target, state.line], [4, true, false, 'Go to Dataset'], 'precondition');
    };

    // Key o: the far card is not centred with the source card cut off beside it.
    cutFar();
    press(ctx, 'o', {}, ctx.canvas);
    both('c-seed-data', step.zoom, 'after key o');
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    // Key o again has nowhere to go: it says so and moves nothing.
    const shown = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), shown);
    assert.equal(live(ctx), 'Both ends of this connection are in view.');

    // A click on the bar's line, and → towards the far card, do the same.
    cutFar();
    farLine(ctx).click();
    both('c-seed-data', step.zoom, 'after a click on the line');
    cutFar();
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    both('c-seed-data', step.zoom, 'after →');
    // The far card moved off the canvas: its line ends in a cap, and a click on the cap shows both.
    ctx.app.view.viewport.set(step);
    ctx.app.view.viewport.panBy(CANVAS.w - card('data').x + 30, 0);
    assert.deepEqual(farState(ctx, 'c-seed-data').caps, ['target'], 'precondition');
    caps(ctx)[0].dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
    both('c-seed-data', step.zoom, 'after a click on the cap');

    // A drag down until 24 px of both cards are under the canvas's foot: the line names the far
    // card, and one press shows both.
    ctx.app.view.viewport.set(step);
    pressBackground(ctx, [[100, 100 + CANVAS.h - card('seed').y - card('seed').h + 24]]);
    let state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line], [false, false, 'Go to Dataset'], 'precondition');
    press(ctx, 'o', {}, ctx.canvas);
    both('c-seed-data', step.zoom, 'after a drag that cut both cards');
    // The view holds no end of it, so with the far card out of view again ← selects the source card.
    ctx.app.view.viewport.panBy(CANVAS.w - card('data').x + 30, 0);
    assert.equal(farState(ctx, 'c-seed-data').line, 'Go to Dataset');
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: 'seed' }, 'seed']);

    // A dashed line the step frames with both cards under reading size: the cards come back at
    // that zoom, with as much of the line between them, not at reading size with one of them.
    for (const id of ['c-model-export', 'c-model-export-2']) {
      walkTo(ctx, id);
      const framed = viewport(ctx);
      const share = shareOnCanvas(ctx, id, CANVAS);
      assert.ok(framed.zoom < 0.62, id + ': precondition: framed at ' + framed.zoom);
      pressBackground(ctx, [[100, 100 - card('model').y - 4]]);
      state = farState(ctx, id);
      assert.deepEqual([Math.round(card('model').y), state.source, state.target, state.line], [-4, false, true, 'Go to Model'], id + ': precondition');
      press(ctx, 'o', {}, ctx.canvas);
      both(id, framed.zoom, id + ' after key o');
      assert.ok(shareOnCanvas(ctx, id, CANVAS) >= share, id + ': as much of the dashed line is on the canvas as at the step, ' + share);
    }
  } finally {
    ctx.app.destroy();
  }
});

test('a card that a notch of zoom or a short pan cut off at the canvas\'s edge has not gone anywhere: on two cards zoomed in until they no longer fit the canvas together the place says "far end", and → that this is it, only once the source card has left the canvas', async () => {
  const ctx = await mount();
  try {
    const card = (id) => drawn(ctx, ctx.app.view.frame.boxes.get(id));
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection)], ['c-seed-data', { kind: 'edge', id: 'c-seed-data' }], what);
    walkTo(ctx, 'c-seed-data');
    // Three notches of the wheel in, at the canvas's middle: 90% to 122%.
    for (let i = 0; i < 3; i++) ctx.canvas.dispatchEvent(new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 0, deltaY: -100, deltaMode: 0, clientX: CANVAS.w / 2, clientY: CANVAS.h / 2 }));
    const span = card('data').x + card('data').w - card('seed').x;
    assert.ok(viewport(ctx).zoom > 1.2 && span > CANVAS.w, 'precondition: at ' + viewport(ctx).zoom + ' the two cards span ' + Math.round(span) + ' px');
    assert.deepEqual([ctx.app.view.far.ends('c-seed-data').fits, ctx.app.view.far.ends('c-seed-data').keep], [false, null]);
    /** Drag the diagram sideways until the far card's right edge is `px` from the canvas's. */
    const farAt = (px) => pressBackground(ctx, [[100 + CANVAS.w - px - card('data').x - card('data').w, 100]]);

    // The far card whole, 2 px inside the canvas: its edge cuts the source card, most of which
    // still shows. Not the far end, and the source no way back.
    farAt(2);
    let state = farState(ctx, 'c-seed-data');
    assert.ok(card('seed').x < -4 && card('seed').x + card('seed').w > card('seed').w / 2, 'precondition: the source card is cut off at ' + Math.round(card('seed').x) + ', ' + Math.round(card('seed').w) + ' px wide');
    assert.deepEqual([state.source, state.target, state.keep, state.place, state.line], [false, true, null, '5/35', 'Go to Seed']);
    assert.match(farLine(ctx).title, /key o goes there\. The walk stays on this claim\.$/);

    // Dragged on until the source card has left the canvas: the far card in view is the far end.
    farAt(CANVAS.w - card('data').w - 20);
    assert.ok(card('seed').x + card('seed').w < 0, 'precondition: the source card is off the canvas');
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.keep, state.place, state.line], [false, true, null, '5/35 · far end', 'Back to Seed']);
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    still('after → at the far end');

    // Back to the first picture: → towards the far card selects it, as on any connection.
    farAt(2);
    assert.deepEqual([farState(ctx, 'c-seed-data').place, farState(ctx, 'c-seed-data').line], ['5/35', 'Go to Seed']);
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: 'data' }, 'data']);
  } finally {
    ctx.app.destroy();
  }
});

test('a connection whose step reads "Line in view end to end" is not a far one after a pan either: with the source card cut off, or gone from the canvas, the place does not say "far end", the line is no way back, and the arrow towards the group in view selects it', async () => {
  // The 176-claim shape: from a step to the open group next to it, which is larger than the
  // canvas and so in view by the place the line meets it.
  for (const [width, canvas, id] of [[541, CANVAS, 'c105'], [1440, { w: 1080, h: 767 }, 'c72']]) {
    const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS), { width, canvas });
    try {
      press(ctx, 'r', {}, ctx.canvas);
      if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
      for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
      for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
      const where = id + ' at ' + width + ' px';
      const step = viewport(ctx);
      let ends = ctx.app.view.far.ends(id);
      const source = () => drawn(ctx, ctx.app.view.frame.boxes.get(ends.source.drawnId));
      assert.deepEqual([$(ctx, '.mlv-walkbar__faridle').textContent, ends.target.byLine, farLine(ctx)], ['Line in view end to end', true, null], where + ': precondition');
      assert.equal(ends.fits, true, where + ': the source card and the place the line meets the group fit the canvas together');
      const place = $(ctx, '.mlv-walkbar__postext').textContent;
      // Down until 24 px of the source card are under the canvas's foot, then until it has left.
      for (const [under, what] of [[24, 'cut off'], [source().h + 10, 'gone']]) {
        ctx.app.view.viewport.set(step);
        pressBackground(ctx, [[100, 100 + canvas.h - source().y - source().h + under]]);
        ends = ctx.app.view.far.ends(id);
        const state = farState(ctx, id);
        assert.deepEqual([ends.source.inView, ends.source.onCanvas, ends.target.inView], [false, what === 'cut off', true], where + ', the source card ' + what + ': precondition');
        assert.deepEqual([state.claim, state.place, state.line.split(' ').slice(0, 2).join(' ')], [id, place, 'Go to'], where + ', the source card ' + what);
        assert.match(farLine(ctx).getAttribute('aria-label'), /^Go to the source: /, where);
      }
      const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends.target.drawnId);
      assert.ok(key, where + ': precondition: an arrow points at the group');
      press(ctx, key, {}, ctx.canvas);
      assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: ends.target.drawnId }, where);
    } finally {
      ctx.app.destroy();
    }
  }
});

test('with both ends of a connection in view ← and → select a card as on any connection, also where the view holds the source card: on a step that reads "Line in view end to end" the arrow towards the source card selects it and the walk goes with it', async () => {
  // The 176-claim shape again: from a step to the open group next to it. The group is larger
  // than the canvas, so the step keeps the source card as a far step does, and the group is in
  // view by the place the line meets it: no end is out of view, and the bar has no far line.
  for (const [width, canvas, id] of [[541, CANVAS, 'c105'], [1440, { w: 1080, h: 767 }, 'c72']]) {
    const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS), { width, canvas });
    try {
      press(ctx, 'r', {}, ctx.canvas);
      if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
      for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
      for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
      const where = id + ' at ' + width + ' px';
      const ends = ctx.app.view.far.ends(id);
      assert.deepEqual([$(ctx, '.mlv-walkbar__faridle').textContent, farLine(ctx), ends.keep, ends.source.inView, ends.target.inView], ['Line in view end to end', null, 'source', true, true], where + ': precondition');
      const place = ctx.app.walk.position;
      const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends.source.drawnId);
      assert.ok(key, where + ': precondition: an arrow points at the source card');
      press(ctx, key, {}, ctx.canvas);
      assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: ends.source.drawnId }, where + ': the source card is selected');
      assert.equal(ctx.app.walk.current().id, ends.source.drawnId, where + ': the walk is on the card\'s claim');
      assert.notEqual(ctx.app.walk.position, place, where);
      assert.match(live(ctx), /^Selected /, where);
    } finally {
      ctx.app.destroy();
    }
  }
});

test('the bar\'s arrow to a card that is partly on the canvas points from the connection\'s other card: a far card beside the source that a 20 px drag put under the phase index lies to the right, not down, and the line says "partly in view"', async () => {
  const ctx = await mount();
  try {
    const card = (id) => drawn(ctx, ctx.app.view.frame.boxes.get(id));
    const arrow = () => $(ctx, '.mlv-walkbar__fararrow').style.transform;
    // Checkpoint to Export, side by side in the last phase: the step shows both.
    walkTo(ctx, 'c-ckpt-export');
    nothingFar(ctx, 'c-ckpt-export');
    const step = viewport(ctx);
    assert.equal(Math.round(card('ckpt').y), Math.round(card('export').y), 'precondition: the two cards stand at one height');

    // The reader drags the diagram 20 px down. Both cards are still whole on the canvas, to the
    // left and right of each other, with their feet under the phase index.
    pressBackground(ctx, [[100, 120]]);
    const covered = ctx.app.view.viewport.covered();
    for (const id of ['ckpt', 'export']) {
      assert.equal(whole(card(id), CANVAS), true, id + ' is whole on the canvas');
      assert.ok(card(id).y + card(id).h > covered.y && card(id).x + card(id).w > covered.x, id + ' stands under the phase index');
    }
    // From the canvas's middle the far card lies below; from the source card, to the right.
    assert.ok(card('export').y + card('export').h / 2 > CANVAS.h / 2 && card('export').x > card('ckpt').x + card('ckpt').w, 'precondition');
    let state = farState(ctx, 'c-ckpt-export');
    assert.deepEqual([state.source, state.target, state.line], [false, false, 'Go to Export']);
    assert.equal(arrow(), 'rotate(0deg)');
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Export, next step, partly in view to the right');
    assert.equal(farLine(ctx).title, 'Export. Click, Enter or key o goes there. The walk stays on this claim.');
    // Key o shows the two clear of the index again.
    press(ctx, 'o', {}, ctx.canvas);
    nothingFar(ctx, 'c-ckpt-export');
    assert.equal(bothWhole(ctx, 'c-ckpt-export'), true);

    // Dragged 4 px over the canvas's left edge instead, the source card lies to the left of the far card.
    ctx.app.view.viewport.set(step);
    pressBackground(ctx, [[100 - card('ckpt').x - 4, 100]]);
    state = farState(ctx, 'c-ckpt-export');
    assert.deepEqual([Math.round(card('ckpt').x), state.source, state.target, state.line], [-4, false, true, 'Go to Checkpoint']);
    assert.equal(arrow(), 'rotate(180deg)');
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the source: Checkpoint, previous step, partly in view to the left');

    // A card that has left the canvas is off screen, and its way is counted from the canvas's middle.
    walkBackTo(ctx, 'c-opts-ckpt');
    assert.equal(arrow(), 'rotate(90deg)');
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
  } finally {
    ctx.app.destroy();
  }
});

test('a far card that lies wholly under the phase index is not "partly in view": the line says "off screen" and gives the screens, and the arrow points to it from the canvas\'s middle; with some of it clear of the index it is partly in view, beside the source card', async () => {
  // 1080 x 767 px, the canvas of a 1440 px panel: the phase index is an open list there, 360 x 106 px
  // for this document's three phases, and a card fits under it.
  const canvas = { w: 1080, h: 767 };
  const ctx = await mount(farDoc(), { width: 1440, canvas });
  try {
    const card = (id) => drawn(ctx, ctx.app.view.frame.boxes.get(id));
    const arrow = () => $(ctx, '.mlv-walkbar__fararrow').style.transform;
    // Seed to Dataset, side by side: the step shows both.
    walkTo(ctx, 'c-seed-data');
    nothingFar(ctx, 'c-seed-data');
    const covered = ctx.app.view.viewport.covered();
    assert.deepEqual([covered.w, covered.h], [360, 106], 'precondition: the phase index is a list');

    // The reader drags the diagram until the far card lies under the list, 20 px inside its left and
    // top edges. The source card stands to its left, whole and clear of the list.
    pressBackground(ctx, [[100 + covered.x + 20 - card('data').x, 100 + covered.y + 20 - card('data').y]]);
    assert.deepEqual([Math.round(card('data').x - covered.x), Math.round(card('data').y - covered.y), whole(card('data'), canvas)], [20, 20, true], 'precondition');
    assert.ok(card('data').x + card('data').w < covered.x + covered.w && card('data').y + card('data').h < covered.y + covered.h, 'precondition: the list covers the whole card');
    let state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line], [true, false, 'Go to Dataset']);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Dataset, next step, off screen below');
    assert.equal(farLine(ctx).title, 'Dataset. About 0.4 screens down. Click, Enter or key o goes there. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(90deg)');

    // Dragged 30 px up, 10 px of the card show above the list: partly in view, to the right of the
    // source card.
    pressBackground(ctx, [[100, 70]]);
    assert.equal(Math.round(covered.y - card('data').y), 10, 'precondition');
    state = farState(ctx, 'c-seed-data');
    assert.deepEqual([state.source, state.target, state.line], [true, false, 'Go to Dataset']);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Dataset, next step, partly in view to the right');
    assert.equal(farLine(ctx).title, 'Dataset. Click, Enter or key o goes there. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(0deg)');
  } finally {
    ctx.app.destroy();
  }
});

test('two cards the step frames together under reading size fit the canvas at that zoom, with no margin: once a drag has taken the source card off the canvas it is still a card to go to, and the arrow towards the far card in view selects it', async () => {
  for (const id of ['c-model-export', 'c-model-export-2']) {
    const ctx = await mount();
    try {
      const card = (node) => drawn(ctx, ctx.app.view.frame.boxes.get(node));
      walkTo(ctx, id);
      const zoom = viewport(ctx).zoom;
      assert.ok(zoom < 0.62, id + ': precondition: framed under reading size, at ' + zoom);
      // The zoom at which the rectangle around the two cards fits the canvas with `margin` px to
      // spare: under reading size, and for the inferred connection's frame under the zoom on
      // screen once a frame's 48 px are asked for.
      const boxes = [ctx.app.view.frame.boxes.get('model'), ctx.app.view.frame.boxes.get('export')];
      const span = { w: Math.max(boxes[0].x + boxes[0].w, boxes[1].x + boxes[1].w) - Math.min(boxes[0].x, boxes[1].x), h: Math.max(boxes[0].y + boxes[0].h, boxes[1].y + boxes[1].h) - Math.min(boxes[0].y, boxes[1].y) };
      const fit = (margin) => Math.min((CANVAS.w - margin) / span.w, (CANVAS.h - margin) / span.h);
      assert.ok(fit(0) >= zoom && fit(0) < 0.9, id + ': precondition: the two cards fit at ' + fit(0));
      if (id === 'c-model-export-2') assert.ok(fit(48) < zoom, id + ': precondition: with 48 px to spare they fit at ' + fit(48) + ', the zoom is ' + zoom);
      // The reader drags the diagram up until the source card has left the canvas by 4 px.
      pressBackground(ctx, [[100, 100 - card('model').y - card('model').h - 4]]);
      const ends = ctx.app.view.far.ends(id);
      assert.deepEqual([Math.round(card('model').y + card('model').h), ends.source.onCanvas, ends.target.inView, ends.fits], [-4, false, true, true], id + ': precondition');
      const state = farState(ctx, id);
      assert.deepEqual([state.line, state.place.includes('far end')], ['Go to Model', false], id);
      assert.match(farLine(ctx).getAttribute('aria-label'), /Go to the source: Model, /, id);
      const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === 'export');
      press(ctx, key, {}, ctx.canvas);
      assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: 'export' }, id);
    } finally {
      ctx.app.destroy();
    }
  }
});

test('a far step whose two cards fit the canvas but not clear of the phase index: the arrow towards the source card the view holds says so and the walk stays, key o goes to the far end and back, and after a drag to the far card the arrow towards it selects it', async () => {
  // The 176-claim shape at 900 x 318 px, c48: the two cards fit the canvas together, but no pan
  // shows both clear of the phase index. The step keeps the source card.
  const canvas = { w: 900, h: 318 };
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS), { width: 900, canvas });
  try {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'c48'; i++) press(ctx, 'j', {}, ctx.canvas);
    let ends = ctx.app.view.far.ends('c48');
    const far = () => drawn(ctx, ctx.app.view.frame.boxes.get(ends.target.drawnId));
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection)], ['c48', { kind: 'edge', id: 'c48' }], what);
    const towards = (end) => ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends[end].drawnId);
    assert.deepEqual([ends.keep, ends.fits, ends.together, ends.source.inView, ends.target.inView, whole(far(), canvas)], ['source', true, false, true, false, true], 'precondition: the far card is whole on the canvas, under the phase index');
    const step = viewport(ctx);

    // The arrow towards the source card: this is where the connection starts. Nothing is selected.
    press(ctx, towards('source'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), step);
    still('after the arrow towards the source');

    // Key o goes to the far card, which is then the far end, and back to the step's picture.
    press(ctx, 'o', {}, ctx.canvas);
    let state = farState(ctx, 'c48');
    assert.deepEqual([state.keep, state.source, state.target, state.line.split(' ').slice(0, 2).join(' ')], ['target', false, true, 'Back to']);
    assert.match(state.place, /, far end /);
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    still('after the arrow towards the far end');
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), step);

    // The reader drags the diagram 40 px up: the far card is clear of the index, the source card
    // cut off at the canvas's top. The view was not taken there by a look, and the two cards fit
    // the canvas: the far card is a card like any other, and the arrow selects it.
    pressBackground(ctx, [[100, 60]]);
    ends = ctx.app.view.far.ends('c48');
    state = farState(ctx, 'c48');
    assert.deepEqual([ends.keep, ends.source.inView, ends.source.onCanvas, ends.target.inView], ['source', false, true, true], 'precondition');
    assert.deepEqual([state.line.split(' ').slice(0, 2).join(' '), state.place.includes('far end')], ['Go to', false]);
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: ends.target.drawnId });
  } finally {
    ctx.app.destroy();
  }
});

/** A two-finger scroll that moves the diagram by `dx`, `dy` px: wheel events of 20 px or less each, which pan. */
function scroll(ctx, dx, dy) {
  const n = Math.max(1, Math.ceil(Math.max(Math.abs(dx), Math.abs(dy)) / 20));
  for (let i = 0; i < n; i++) ctx.canvas.dispatchEvent(new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: -dx / n, deltaY: -dy / n, deltaMode: 0 }));
}

test('on a far step whose two cards do not fit the canvas, the arrow towards a card in view says which end it is and the walk stays, however much of the other card is still on the canvas: towards the far card after a scroll that brought it whole into view and cut the source card off, and towards the source card after key o and a scroll back', async () => {
  // The 176-claim shape at 541 x 337 px, c112: two cards in one row that do not fit the canvas
  // together at the step's zoom. With either card whole on the canvas, 60 px of the other one are
  // on it too.
  const id = 'c112';
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS));
  try {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
    let ends = ctx.app.view.far.ends(id);
    const card = (end) => drawn(ctx, ctx.app.view.frame.boxes.get(ends[end].drawnId));
    const towards = (end) => ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends[end].drawnId);
    const place = ctx.app.walk.position;
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection)], [id, place, { kind: 'edge', id }], what);
    /** The least scroll that brings the card at `end` whole onto the canvas, 2 px inside its edge. */
    const scrollTo = (end) => {
      const least = (start, size, extent) => (start < 2 ? 2 - start : start + size > extent - 2 ? extent - 2 - (start + size) : 0);
      scroll(ctx, least(card(end).x, card(end).w, CANVAS.w), least(card(end).y, card(end).h, CANVAS.h));
      ends = ctx.app.view.far.ends(id);
    };
    assert.deepEqual([ends.keep, ends.fits, ends.source.inView, ends.target.inView], ['source', false, true, false], 'precondition: a far step, which keeps its source card');
    const step = viewport(ctx);

    // The reader scrolls until the far card is whole on the canvas, whose edge now cuts the source
    // card, which the bar names as a card to go to; the place does not say "far end".
    scrollTo('target');
    assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, Math.round(card('source').x + card('source').w)], ['source', false, true, false, 60], 'precondition: the far card whole, the source card cut off');
    let state = farState(ctx, id);
    assert.deepEqual([state.place, state.line], [place + 1 + '/176', 'Go to Step 47']);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the source: Step 47, next step, partly in view to the left');
    // The arrow towards the far card says that this is it. The card is not selected: the walk
    // would go with it to another claim.
    let at = viewport(ctx);
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    assert.deepEqual(viewport(ctx), at);
    still('after the arrow towards the far card');

    // From the step's picture again: key o goes to the far end, and the reader scrolls back until
    // the source card is whole, with the far card cut off. The arrow towards the source card says
    // that the connection starts there.
    ctx.app.view.viewport.set(step);
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, id).place, / · far end$/);
    scrollTo('source');
    assert.deepEqual([ends.keep, ends.fits, ends.source.inView, ends.target.inView, Math.round(CANVAS.w - card('target').x)], ['target', false, true, false, 60], 'precondition: the source card whole, the far card cut off');
    state = farState(ctx, id);
    assert.deepEqual([state.place, state.line], [place + 1 + '/176', 'Go to Step 46']);
    at = viewport(ctx);
    press(ctx, towards('source'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), at);
    still('after the arrow towards the source card');
  } finally {
    ctx.app.destroy();
  }
});

test('once key o has shown the two cards of a connection together the view holds neither end, also on a far step that kept its source card until the reader zoomed out: after a pan that takes the far card out of view again, the arrow towards the source card selects it', async () => {
  const id = 'c-opts-ckpt';
  const ctx = await mount();
  try {
    walkTo(ctx, id);
    const step = viewport(ctx);
    assert.deepEqual([ctx.app.view.far.ends(id).keep, farState(ctx, id).line], ['source', 'Go to Checkpoint'], 'precondition: a far step, which keeps its source card');
    // The reader zooms out to 50%: the two cards now fit the canvas clear of the phase index, and
    // the far card is still under the canvas's foot.
    ctx.app.view.viewport.zoomAt(0.5 / step.zoom, CANVAS.w / 2, CANVAS.h / 2);
    let ends = ctx.app.view.far.ends(id);
    assert.deepEqual([ends.keep, ends.together, ends.source.inView, ends.target.onCanvas], ['source', true, true, false], 'precondition');
    press(ctx, 'o', {}, ctx.canvas);
    ends = ctx.app.view.far.ends(id);
    assert.deepEqual([ends.keep, ends.source.inView, ends.target.inView, farState(ctx, id).line], [null, true, true, null]);
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    assert.ok(Math.abs(viewport(ctx).zoom - 0.5) < 0.001, 'the zoom is the reader\'s: ' + viewport(ctx).zoom);
    // A drag of 60 px down takes the far card under the canvas's foot again. It is a card to go to,
    // and the source card is a card like any other: the arrow towards it selects it.
    pressBackground(ctx, [[100, 160]]);
    ends = ctx.app.view.far.ends(id);
    const state = farState(ctx, id);
    assert.deepEqual([ends.keep, ends.source.inView, ends.target.onCanvas, state.line, state.place.includes('far end')], [null, true, false, 'Go to Checkpoint', false], 'precondition');
    const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === 'opts');
    press(ctx, key, {}, ctx.canvas);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: 'opts' });
  } finally {
    ctx.app.destroy();
  }
});

test('a far connection the walk comes onto by a click on its line, by Reveal in Diagram or by a selection made again has its line in the bar and its cap, as one it stepped onto', async () => {
  const ctx = await mount();
  try {
    // From a step claim: a click on the line of a far connection. The walk follows; nothing moves.
    walkTo(ctx, 'seed');
    const before = viewport(ctx);
    ctx.app.select({ kind: 'edge', id: 'c-opts-ckpt' }, { showClaim: true });
    assert.equal(ctx.app.walk.current().id, 'c-opts-ckpt');
    assert.deepEqual(viewport(ctx), before);
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.target, state.line, state.caps, state.keep], [true, false, 'Go to Checkpoint', ['target'], null]);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
    // Key o goes there and comes back to this picture.
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, 'c-opts-ckpt').place, / · far end$/);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), before);

    // The selection is cleared (a click on the background) and the connection is clicked again.
    ctx.app.clearSelection();
    assert.equal(farLine(ctx), null);
    assert.equal(caps(ctx).length, 0);
    ctx.app.select({ kind: 'edge', id: 'c-opts-ckpt' }, { showClaim: true });
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.line, state.caps], ['Go to Checkpoint', ['target']]);

    // Reveal in Diagram from the host, from a step claim: an unresolved connection too far apart to frame.
    walkTo(ctx, 'seed');
    ctx.bridge.send({ v: 1, type: 'reveal', kind: 'edge', id: 'c-optim-ckpt-2' });
    assert.equal(ctx.app.walk.current().id, 'c-optim-ckpt-2');
    state = farState(ctx, 'c-optim-ckpt-2');
    assert.equal(state.source && state.target, false, 'precondition: the reveal cannot show both cards');
    assert.match(state.line, /^(Go to Checkpoint|Back to Optimizer)$/);
    assert.ok(state.caps.length >= 1);
    assert.equal(farLine(ctx).querySelector('.mlv-walkbar__fartag').textContent, '? unresolved');
    assert.equal(caps(ctx)[0].getAttribute('data-basis'), 'unresolved');
    // The same connection revealed again while the walk is on it keeps them.
    ctx.bridge.send({ v: 1, type: 'reveal', kind: 'edge', id: 'c-optim-ckpt-2' });
    assert.ok(farLine(ctx));
    assert.ok(caps(ctx).length >= 1);
  } finally {
    ctx.app.destroy();
  }
});

test('after a click on a far connection\'s line the view holds neither end, and the arrow towards the card in view says which end of the connection that card is: the walk\'s place, its claim and the selection do not change and nothing moves, from the step\'s own picture and after a scroll to the far card', async () => {
  // The 176-claim shape at 541 x 337 px, c112, as above: two cards in one row that do not fit the
  // canvas. With either card whole on it, some of the other one is on it too. A click on a line
  // selects the connection and moves nothing, so the view holds neither end afterwards
  // (`FarEnds.keep`). The picture and the bar's words are those of a far step, and for the arrows
  // it is a far connection too (`WalkFar.arrow`): selecting the card would take the walk with it
  // to another claim.
  const id = 'c112';
  for (const whole of ['source', 'target']) {
    const other = whole === 'source' ? 'target' : 'source';
    const where = 'towards the ' + (whole === 'source' ? 'source' : 'far') + ' card';
    const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS));
    try {
      press(ctx, 'r', {}, ctx.canvas);
      if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
      for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
      for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
      let ends = ctx.app.view.far.ends(id);
      const place = ctx.app.walk.position;
      assert.deepEqual([ctx.app.walk.current().id, ends.keep, ends.fits, ends.source.inView, ends.target.inView, ends.target.onCanvas], [id, 'source', false, true, false, true], where + ': precondition: a far step, which keeps its source card; the canvas\'s edge cuts the far card');
      if (whole === 'target') {
        // The least scroll that brings the far card whole onto the canvas, 2 px inside its edge.
        const card = drawn(ctx, ctx.app.view.frame.boxes.get(ends.target.drawnId));
        const least = (start, size, extent) => (start < 2 ? 2 - start : start + size > extent - 2 ? extent - 2 - (start + size) : 0);
        scroll(ctx, least(card.x, card.w, CANVAS.w), least(card.y, card.h, CANVAS.h));
      }
      const picture = viewport(ctx);

      // The reader clicks the background, which clears the selection, and then the connection's
      // line. Nothing moves, and the bar reads as before the two clicks.
      pressBackground(ctx, []);
      assert.deepEqual([ctx.app.selection, ctx.app.walk.position], [null, place], where + ': precondition: the click on the background cleared the selection, and the walk kept its place');
      lineOf(ctx, id).querySelector('.mlv-edge__hit').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
      assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection)], [id, place, { kind: 'edge', id }], where + ': precondition: the walk is on the connection again');
      assert.deepEqual(viewport(ctx), picture, where);
      ends = ctx.app.view.far.ends(id);
      assert.deepEqual([ends.keep, ends.fits, ends[whole].inView, ends[other].inView, ends[other].onCanvas], [null, false, true, false, true], where + ': precondition: the view holds neither end; one card whole, the other cut off');
      assert.deepEqual([farState(ctx, id).place, farState(ctx, id).line], [place + 1 + '/176', whole === 'source' ? 'Go to Step 46' : 'Go to Step 47'], where);

      // The arrow towards the card that is whole says which end of the connection it is. The card
      // is not selected, the walk stays on the connection and the picture is the same.
      const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends[whole].drawnId);
      assert.ok(key, where + ': precondition: an arrow points at the card');
      press(ctx, key, {}, ctx.canvas);
      assert.equal(live(ctx), whole === 'source' ? 'This is where the connection starts.' : 'This is the far end of the connection.', where);
      assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection)], [id, place, { kind: 'edge', id }], where + ': the walk\'s claim, its place and the selection are those before the arrow');
      assert.deepEqual(viewport(ctx), picture, where);
      assert.deepEqual([farState(ctx, id).place, farState(ctx, id).line], [place + 1 + '/176', whole === 'source' ? 'Go to Step 46' : 'Go to Step 47'], where + ': the bar reads as before the arrow');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('a far connection the walk comes onto by a click on its line is a far one for ← and → although the view holds neither end: the arrow towards the card in view says which end it is, and the walk\'s place, claim and selection stay; a connection it stepped onto, or clicked while its two cards fitted the canvas, still gives a card to the arrow where the view holds neither end and the reader has zoomed in until the two do not fit', async () => {
  // The 176-claim shape at 541 x 337 px, c112, as above: two cards in one row that do not fit the
  // canvas. With either card whole on it, some of the other one is on it too.
  const id = 'c112';
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS));
  try {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
    let ends = ctx.app.view.far.ends(id);
    const card = (end) => drawn(ctx, ctx.app.view.frame.boxes.get(ends[end].drawnId));
    const towards = (end) => ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === ends[end].drawnId);
    const place = ctx.app.walk.position;
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection)], [id, place, { kind: 'edge', id }], what);
    /** The least scroll that brings the card at `end` whole onto the canvas, 2 px inside its edge. */
    const scrollTo = (end) => {
      const least = (start, size, extent) => (start < 2 ? 2 - start : start + size > extent - 2 ? extent - 2 - (start + size) : 0);
      scroll(ctx, least(card(end).x, card(end).w, CANVAS.w), least(card(end).y, card(end).h, CANVAS.h));
      ends = ctx.app.view.far.ends(id);
    };
    /** A click on the connection's line, as the pointer makes it. */
    const clickLine = () => {
      lineOf(ctx, id).querySelector('.mlv-edge__hit').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
      ends = ctx.app.view.far.ends(id);
    };
    /** Three notches of the wheel at the canvas's middle: out to 67%, where the two cards fit, or back in to 90%. */
    const notches = (deltaY) => {
      for (let i = 0; i < 3; i++) ctx.canvas.dispatchEvent(new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 0, deltaY, deltaMode: 0, clientX: CANVAS.w / 2, clientY: CANVAS.h / 2 }));
      ends = ctx.app.view.far.ends(id);
    };
    const step = viewport(ctx);
    assert.deepEqual([ends.keep, ends.fits, ends.source.inView, ends.target.inView, ends.target.onCanvas], ['source', false, true, false, true], 'precondition: a far step, which keeps its source card; the canvas\'s edge cuts the far card');

    // The reader clicks the background, which clears the selection, and then the connection's
    // line. Nothing moves and the bar reads as at the step, but the view now holds neither end.
    pressBackground(ctx, []);
    assert.deepEqual([ctx.app.selection, ctx.app.walk.position], [null, place], 'precondition: the click on the background cleared the selection, and the walk kept its place');
    clickLine();
    still('after the click on the line');
    assert.deepEqual(viewport(ctx), step);
    assert.deepEqual([ends.keep, ends.fits, ends.source.inView, ends.target.inView, ends.target.onCanvas], [null, false, true, false, true], 'precondition: the view holds neither end');
    assert.deepEqual([farState(ctx, id).place, farState(ctx, id).line], [place + 1 + '/176', 'Go to Step 46']);
    // The arrow towards the source card says that the connection starts there. The card is not
    // selected: the walk would go with it to another claim.
    press(ctx, towards('source'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), step);
    still('after the arrow towards the source card');

    // The reader scrolls until the far card is whole on the canvas, where its edge cuts the source
    // card: the arrow towards the far card says that this is it.
    scrollTo('target');
    assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, ends.source.onCanvas], [null, false, true, false, true], 'precondition: the far card whole, the source card cut off');
    assert.equal(farState(ctx, id).line, 'Go to Step 47');
    const scrolled = viewport(ctx);
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    assert.deepEqual(viewport(ctx), scrolled);
    still('after the arrow towards the far card');

    // From another claim: the walk steps on, the reader has this picture again and clicks the
    // line. The walk follows the click onto the connection, and the arrow answers as above.
    press(ctx, 'j', {}, ctx.canvas);
    assert.equal(ctx.app.walk.position, place + 1, 'precondition: the walk stepped on');
    ctx.app.view.viewport.set(scrolled);
    clickLine();
    still('the walk followed the click on the line');
    assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, ends.source.onCanvas], [null, false, true, false, true], 'precondition: the far card whole, the source card cut off, neither held');
    assert.notEqual(live(ctx), 'This is the far end of the connection.', 'precondition: the click said what it selected');
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    still('after the arrow towards the far card, the walk having followed a click');

    // A step onto the connection is no such click. The walk steps on and back, and the step keeps
    // the source card. The reader zooms out until the two cards fit, key o shows them together,
    // and the view holds neither end; zoomed in again until they do not fit and scrolled to the
    // far card, that card is one like any other: the arrow selects it and the walk goes with it.
    press(ctx, 'j', {}, ctx.canvas);
    press(ctx, 'k', {}, ctx.canvas);
    ends = ctx.app.view.far.ends(id);
    still('the walk stepped back onto the connection');
    assert.deepEqual([ends.keep, ends.fits], ['source', false], 'precondition: a far step again');
    notches(100);
    assert.deepEqual([ends.keep, ends.together], ['source', true], 'precondition: at ' + viewport(ctx).zoom + ' the two cards can be shown together');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    notches(-100);
    scrollTo('target');
    assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, ends.source.onCanvas], [null, false, true, false, true], 'precondition: the far card whole, the source card cut off, neither held, at ' + viewport(ctx).zoom);
    press(ctx, towards('target'), {}, ctx.canvas);
    assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: ends.target.drawnId }, ends.target.drawnId]);
  } finally {
    ctx.app.destroy();
  }

  // A click on the line of a connection whose two cards fit the canvas is a click on any line:
  // Seed to Dataset in the document above. Zoomed in afterwards until the two do not fit, with
  // the far card whole and the source card cut off, the arrow selects the far card.
  const near = await mount();
  try {
    const card = (node) => drawn(near, near.app.view.frame.boxes.get(node));
    walkTo(near, 'seed');
    lineOf(near, 'c-seed-data').querySelector('.mlv-edge__hit').dispatchEvent(new near.window.MouseEvent('click', { bubbles: true, cancelable: true }));
    assert.deepEqual([near.app.walk.current().id, near.app.view.far.ends('c-seed-data').fits], ['c-seed-data', true], 'precondition: the walk followed the click, and the two cards fit');
    for (let i = 0; i < 3; i++) near.canvas.dispatchEvent(new near.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 0, deltaY: -100, deltaMode: 0, clientX: CANVAS.w / 2, clientY: CANVAS.h / 2 }));
    pressBackground(near, [[100 + CANVAS.w - 2 - card('data').x - card('data').w, 100]]);
    const ends = near.app.view.far.ends('c-seed-data');
    assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, ends.source.onCanvas], [null, false, true, false, true], 'precondition: zoomed in to ' + viewport(near).zoom + ', the far card whole, the source card cut off');
    press(near, 'ArrowRight', {}, near.canvas);
    assert.deepEqual([plain(near.app.selection), near.app.walk.current().id], [{ kind: 'node', id: 'data' }, 'data']);
  } finally {
    near.app.destroy();
  }
});

test('a walk step that opens a group the reader had folded is a step like any other: where the view then holds neither end of its connection and the reader has zoomed in until the two cards do not fit, the arrow selects the card in view', async () => {
  // The 176-claim shape at 541 x 337 px, c76 (a far step) and the 79-claim shape, c35: an end of
  // each lies inside a group. Each is walked twice: with the group open, and with the group folded
  // by the reader on the claim before, so that the step opens it again.
  for (const [shape, id] of [[SHAPE_176_CLAIMS, 'c76'], [SHAPE_79_CLAIMS, 'c35']]) {
    for (const folded of [false, true]) {
      const ctx = await mount(shapedWorkflow(shape));
      try {
        const where = id + (folded ? ', the group folded before the step' : ', the group open');
        const view = ctx.app.view;
        press(ctx, 'r', {}, ctx.canvas);
        if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
        for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
        for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
        press(ctx, 'k', {}, ctx.canvas);
        const edge = ctx.app.index.edgeById.get(id);
        const groups = [...new Set([...ctx.app.index.ancestors(edge.source), ...ctx.app.index.ancestors(edge.target)])];
        assert.ok(groups.length > 0, where + ': precondition: an end lies inside a group');
        if (folded) for (const group of groups) view.toggleCollapse(group);
        assert.equal(groups.every((group) => view.collapsedSet.has(group)), folded, where + ': precondition');
        press(ctx, 'j', {}, ctx.canvas);
        let ends = view.far.ends(id);
        assert.deepEqual([ctx.app.walk.current().id, groups.some((group) => view.collapsedSet.has(group)), ends.keep, ends.fits], [id, false, 'source', false], where + ': precondition: a far step, with the group open');
        // The reader zooms out until the two cards can be shown together, key o shows both, and
        // the view holds neither end; then the same notches in, and a scroll to the far card.
        const notch = (deltaY) => ctx.canvas.dispatchEvent(new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 0, deltaY, deltaMode: 0, clientX: CANVAS.w / 2, clientY: CANVAS.h / 2 }));
        let notches = 0;
        while (!view.far.ends(id).together && notches < 12) { notch(100); notches++; }
        assert.equal(view.far.ends(id).together, true, where + ': precondition: the two cards can be shown together at ' + viewport(ctx).zoom);
        press(ctx, 'o', {}, ctx.canvas);
        assert.equal(live(ctx), 'Both ends of this connection are in view.', where);
        for (let i = 0; i < notches; i++) notch(-100);
        ends = view.far.ends(id);
        const far = drawn(ctx, view.frame.boxes.get(ends.target.drawnId));
        const least = (start, size, extent) => (start < 2 ? 2 - start : start + size > extent - 2 ? extent - 2 - (start + size) : 0);
        scroll(ctx, least(far.x, far.w, CANVAS.w), least(far.y, far.h, CANVAS.h));
        ends = view.far.ends(id);
        assert.deepEqual([ends.keep, ends.fits, ends.target.inView, ends.source.inView, ends.source.onCanvas], [null, false, true, false, true], where + ': precondition: the far card whole, the source card cut off, neither held, at ' + viewport(ctx).zoom);
        const key = ['ArrowLeft', 'ArrowRight'].find((k) => (view.nextSelection(ctx.app.selection, k) || {}).id === ends.target.drawnId);
        assert.ok(key, where + ': precondition: an arrow points at the far card');
        press(ctx, key, {}, ctx.canvas);
        assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: ends.target.drawnId }, ends.target.drawnId], where);
      } finally {
        ctx.app.destroy();
      }
    }
  }
});

test('two limits, not the rule for a far connection: ← or → still selects the card in view, and the walk goes with it to another claim, on a far connection whose line was clicked while the reader had zoomed out until its two cards fit, after a zoom in; and on one the walk stepped onto, after key o showed both cards at a smaller zoom and a zoom in', async () => {
  // The 176-claim shape at 541 x 337 px, c112, as above; at 67% its two cards fit the canvas.
  // In both states the view holds neither end, and the walk did not come onto the connection by a
  // click while its two cards did not fit (`WalkFar.arrow`), so the card in view is a card like
  // any other for the arrows. The picture and the bar's words are those of a far connection all
  // the same. This holds what the viewer does there, so that a change to it shows; it is not
  // what a far connection should do.
  const id = 'c112';
  for (const state of ['its line clicked at 67%', 'stepped onto, key o at 67%']) {
    const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS));
    try {
      press(ctx, 'r', {}, ctx.canvas);
      if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
      for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
      for (let i = 0; i < 400 && ctx.app.walk.current().id !== id; i++) press(ctx, 'j', {}, ctx.canvas);
      const place = ctx.app.walk.position;
      const ends = () => ctx.app.view.far.ends(id);
      /** Three notches of the wheel at the canvas's middle: out to 67%, where the two cards fit, or back in to 90%. */
      const notches = (deltaY) => {
        for (let i = 0; i < 3; i++) ctx.canvas.dispatchEvent(new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 0, deltaY, deltaMode: 0, clientX: CANVAS.w / 2, clientY: CANVAS.h / 2 }));
      };
      assert.deepEqual([ctx.app.walk.current().id, ends().keep, ends().fits], [id, 'source', false], state + ': precondition: a far step, which keeps its source card');
      if (state === 'its line clicked at 67%') {
        // A click on the background clears the selection; the reader zooms out and clicks the line.
        pressBackground(ctx, []);
        notches(100);
        assert.deepEqual([ctx.app.selection, ends().fits], [null, true], state + ': precondition: nothing selected, and at ' + viewport(ctx).zoom + ' the two cards fit');
        lineOf(ctx, id).querySelector('.mlv-edge__hit').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
      } else {
        // The reader zooms out and key o shows the two cards together.
        notches(100);
        assert.equal(ends().together, true, state + ': precondition: at ' + viewport(ctx).zoom + ' the two cards can be shown together');
        press(ctx, 'o', {}, ctx.canvas);
        assert.equal(live(ctx), 'Both ends of this connection are in view.', state);
      }
      assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection), ends().keep], [id, place, { kind: 'edge', id }, null], state + ': precondition: the walk is on the connection, and the view holds neither end');
      // Zoomed in again until the two do not fit, and scrolled the least distance that brings the
      // far card whole onto the canvas, 2 px inside its edge.
      notches(-100);
      const card = drawn(ctx, ctx.app.view.frame.boxes.get(ends().target.drawnId));
      const least = (start, size, extent) => (start < 2 ? 2 - start : start + size > extent - 2 ? extent - 2 - (start + size) : 0);
      scroll(ctx, least(card.x, card.w, CANVAS.w), least(card.y, card.h, CANVAS.h));
      const now = ends();
      assert.deepEqual([now.keep, now.fits, now.target.inView, now.source.inView, now.source.onCanvas], [null, false, true, false, true], state + ': precondition: the far card whole, the source card cut off, neither held, at ' + viewport(ctx).zoom);
      assert.deepEqual([farState(ctx, id).place, farState(ctx, id).line], [place + 1 + '/176', 'Go to Step 47'], state + ': the bar reads as on a far connection, and names the source card');

      // The arrow towards the far card selects it, and the walk follows the selection.
      const key = ['ArrowLeft', 'ArrowRight'].find((k) => (ctx.app.view.nextSelection(ctx.app.selection, k) || {}).id === now.target.drawnId);
      assert.ok(key, state + ': precondition: an arrow points at the far card');
      press(ctx, key, {}, ctx.canvas);
      assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'node', id: now.target.drawnId }, now.target.drawnId], state + ': the card is selected, and the walk is on its claim');
      assert.notEqual(ctx.app.walk.position, place, state);
      assert.match(live(ctx), /^Selected /, state);
    } finally {
      ctx.app.destroy();
    }
  }
});

/* ── a drag that pans the diagram keeps the far connection ─────────── */

/**
 * One press on the canvas's background at (100, 100), moved through `path` and released, with
 * the click the browser sends after every press and release, also after a drag.
 */
function pressBackground(ctx, path) {
  const send = (type, x, y) => ctx.canvas.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  send('pointerdown', 100, 100);
  let at = [100, 100];
  for (const next of path) {
    at = next;
    send('pointermove', at[0], at[1]);
  }
  send('pointerup', at[0], at[1]);
  send('click', at[0], at[1]);
}

test('a drag on the background keeps the far connection selected, lit, capped and named in the bar; a click there clears the selection and the walk goes on', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-val-sched');
    atSource(ctx, 'c-val-sched', 'Scheduler');
    const before = viewport(ctx);
    const place = ctx.app.walk.position;
    pressBackground(ctx, [[80, 90], [60, 70]]);
    const after = viewport(ctx);
    assert.deepEqual([Math.round(after.x - before.x), Math.round(after.y - before.y), after.zoom], [-40, -30, before.zoom], 'the diagram moved with the pointer');
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c-val-sched' }, 'the drag kept the selection');
    assert.match(lineOf(ctx, 'c-val-sched').getAttribute('class'), /is-selected/);
    atSource(ctx, 'c-val-sched', 'Scheduler');
    assert.equal(ctx.app.walk.position, place);

    // A press and release in one place is a click on the background: it clears the selection.
    pressBackground(ctx, []);
    assert.equal(ctx.app.selection, null);
    assert.equal(farLine(ctx), null);
    assert.equal(caps(ctx).length, 0);
    assert.deepEqual([ctx.app.walk.active, ctx.app.walk.position], [true, place], 'the walk keeps its place');
    press(ctx, 'j', {}, ctx.canvas);
    assert.equal(ctx.app.walk.position, place + 1, 'and steps on from it');
  } finally {
    ctx.app.destroy();
  }
});

/* ── a canvas that changes size ──────────────────────────────────────── */

test('a canvas that gets shorter keeps the card the reader has on it: the end the walk holds while that was in view, the other card once they have dragged to it', async () => {
  const boxOf = (ctx, id, end) => ctx.app.view.frame.boxes.get(ctx.app.index.edgeById.get(id)[end]);
  const inView = (ctx, id, end) => ctx.app.view.far.inView(boxOf(ctx, id, end));
  for (const id of ['c-opts-ckpt', 'c-optim-ckpt', 'c-val-sched']) {
    const ctx = await mount();
    try {
      walkTo(ctx, id);
      // The walk holds the source card: a shorter canvas keeps it.
      ctx.resize(541, 200);
      assert.equal(inView(ctx, id, 'source'), true, id + ': the source card after the canvas shrank');
      ctx.resize(541, 337);

      // The reader drags until the far card is in the canvas's lower left, 52 px above its foot
      // and clear of the phase index; the source card is out of view.
      const vp = viewport(ctx);
      const box = boxOf(ctx, id, 'target');
      ctx.app.view.viewport.panBy(12 - box.x * vp.zoom - vp.x, 337 - 52 - (box.y + box.h) * vp.zoom - vp.y);
      assert.deepEqual([inView(ctx, id, 'source'), inView(ctx, id, 'target')], [false, true], id + ': precondition');
      assert.equal(ctx.app.view.far.ends(id).keep, 'source', id + ': precondition: the walk still holds the source');
      ctx.resize(541, 200);
      assert.equal(inView(ctx, id, 'target'), true, id + ': the far card is still whole on the shorter canvas');
      assert.equal(farState(ctx, id).line.startsWith('Back to '), true, id);
    } finally {
      ctx.app.destroy();
    }
  }
});

test('a canvas that shrinks keeps the start of the far line with the source card, and the same after a look at the far end and back', async () => {
  const seen = {};
  for (const looked of [false, true]) {
    const ctx = await mount();
    try {
      walkTo(ctx, 'c-opts-ckpt');
      if (looked) {
        press(ctx, 'o', {}, ctx.canvas);
        press(ctx, 'o', {}, ctx.canvas);
      }
      const rows = [];
      for (const [w, h] of [[541, 337], [541, 240], [541, 200], [400, 200], [320, 200], [541, 337]]) {
        ctx.resize(w, h);
        rows.push({ w, h, viewport: viewport(ctx), card: ctx.app.view.far.inView(ctx.app.view.frame.boxes.get('opts')), line: Math.round(lineInSight(ctx, 'c-opts-ckpt', { w, h }).seen) });
      }
      for (const row of rows) {
        assert.equal(row.card, true, row.w + ' x ' + row.h + ': the source card is whole');
        assert.ok(row.line >= 80, row.w + ' x ' + row.h + ': ' + row.line + ' px of the line in sight');
      }
      seen[looked] = rows;
    } finally {
      ctx.app.destroy();
    }
  }
  assert.deepEqual(seen[true], seen[false], 'a look and back changes nothing of what a resize keeps');
});

test('a canvas too small to show a card that grows shows the card the view holds: the bar does not go on saying the reader is at an end that is cut off', async () => {
  const boxOf = (ctx, end) => ctx.app.view.frame.boxes.get(ctx.app.index.edgeById.get('c-opts-ckpt')[end]);
  const inView = (ctx, end) => ctx.app.view.far.inView(boxOf(ctx, end));
  // 270 x 60 px: a card is 65 px high. The step leaves the source card cut off on two sides.
  const small = { w: 270, h: 60 };
  let ctx = await mount(farDoc(), { canvas: small, width: 270 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    assert.equal(inView(ctx, 'source'), false, 'precondition: the canvas cannot show the source card');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
    ctx.panel(541);
    ctx.resize(541, 337);
    assert.equal(inView(ctx, 'source'), true, 'the source card is whole on the larger canvas');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    // The way there and back is from this picture.
    const here = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), here);
  } finally {
    ctx.app.destroy();
  }
  // The same at the far end, and the way back is kept.
  ctx = await mount(farDoc(), { canvas: small, width: 270 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(inView(ctx, 'target'), false, 'precondition: the canvas cannot show the far card');
    assert.match(farState(ctx, 'c-opts-ckpt').place, / · far end$/);
    ctx.panel(541);
    ctx.resize(541, 337);
    assert.equal(inView(ctx, 'target'), true);
    const state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.line, state.caps], ['target', 'Back to Options', ['source']]);
    assert.match(state.place, / · far end$/);
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(inView(ctx, 'source'), true);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
  } finally {
    ctx.app.destroy();
  }
  // A canvas that gets smaller still keeps the end where the walk left it.
  ctx = await mount(farDoc(), { canvas: { w: 270, h: 74 }, width: 270 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const left = viewport(ctx);
    ctx.resize(270, 70);
    assert.deepEqual(viewport(ctx), left);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
  } finally {
    ctx.app.destroy();
  }
});

test('a short canvas that grows shows the source the walk holds again, at the zoom the larger canvas allows; that zoom is the viewer\'s, so the next step returns to reading size from it', async () => {
  // c-loop-ckpt starts at the open group, wider than the canvas: the walk shows the place its line
  // leaves the group, which a canvas 50 px high cannot show by the rule.
  const ctx = await mount(farDoc(), { canvas: { w: 541, h: 50 } });
  try {
    walkTo(ctx, 'loop');
    // The reader zooms out below full detail (three steps of the zoom control), and steps on.
    for (let i = 0; i < 3; i++) ctx.app.view.zoomStep(-1);
    const chosen = viewport(ctx).zoom;
    assert.ok(chosen < 0.62, 'precondition: below full detail, at ' + chosen);
    press(ctx, 'j', {}, ctx.canvas);
    atSource(ctx, 'c-loop-ckpt', 'Checkpoint', false);
    assert.deepEqual([viewport(ctx).zoom, ctx.app.getState().framedZoom], [chosen, undefined], 'precondition: this canvas has no room for a larger zoom, so the zoom is still the reader\'s');
    // The canvas grows to 120 px: the place is shown again, zoomed in as far as it fits there.
    ctx.resize(541, 120);
    const grown = viewport(ctx).zoom;
    assert.ok(grown >= 0.62 && grown < 0.75, 'precondition: at full detail and under reading size, at ' + grown);
    atSource(ctx, 'c-loop-ckpt', 'Checkpoint', false);
    assert.equal(ctx.app.getState().framedZoom, grown, 'the viewer\'s zoom, not one the reader chose');
    // On the usual canvas the next step is at reading size again; a zoom the reader chose would stay.
    ctx.resize(541, 337);
    assert.equal(viewport(ctx).zoom, grown);
    press(ctx, 'j', {}, ctx.canvas);
    assert.deepEqual([ctx.app.walk.current().id, viewport(ctx).zoom], ['batch', 0.9]);
  } finally {
    ctx.app.destroy();
  }
});

test('a drag that cuts the source card off by a few pixels leaves the line on the far card, and key o still goes there; once the source card has left the canvas the line is the way back', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    const source = () => drawn(ctx, ctx.app.view.frame.boxes.get('opts'));
    // The reader drags the picture up until 24 px of the source card are above the canvas.
    pressBackground(ctx, [[100, 60], [100, 100 - source().y - 24]]);
    assert.equal(Math.round(source().y), -24, 'precondition');
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.claim, state.source, state.target, state.keep], ['c-opts-ckpt', false, false, 'source']);
    assert.equal(state.line, 'Go to Checkpoint', 'the line still names the far card');
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
    assert.doesNotMatch(state.place, /far end/);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c-opts-ckpt' });
    // Key o goes to the far card, not back to the source.
    press(ctx, 'o', {}, ctx.canvas);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.target, state.line], ['target', true, 'Back to Options']);
    assert.match(state.place, / · far end$/);
    assert.equal(live(ctx), 'Far end of this connection: Checkpoint. o goes back to Options.');
    // And back: the source card whole again.
    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');

    // Dragged on until the source card has left the canvas: both cards are out of view, and the
    // line is the way back, with a cap towards each end.
    pressBackground(ctx, [[100, 60], [100, 100 - source().y - source().h - 10]]);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.target, state.line, state.caps], [false, false, 'Back to Options', ['source', 'target']]);
    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
  } finally {
    ctx.app.destroy();
  }
});

/* ── the bar in a narrow panel ───────────────────────────────────────── */

const flexOf = (element) => cascadeWinner(CSS, element, 'flex').value;
const ruleOf = (element, property) => {
  const winner = cascadeWinner(CSS, element, property);
  return winner ? winner.value : null;
};

test('under 400 px the bar stacks its rows: the far line on a row to itself, then Previous and Next, the place and Exit, the filters under them; from 400 px the place and the line share a row', async () => {
  // jsdom lays nothing out, so no height of the bar is read here, only the rules that lay it out:
  // under 400 px a row for the line, a row for Previous and Next, the place and Exit, and rows for
  // the filters; from 400 px one row for the place and the line, with the controls under it.
  for (const width of [270, 320, 399, 400, 541]) {
    const ctx = await mount(farDoc(), { width });
    try {
      walkTo(ctx, 'c-opts-ckpt');
      const bar = $(ctx, '.mlv-walkbar');
      const slot = $(ctx, '.mlv-walkbar__farslot');
      const tools = $(ctx, '.mlv-walkbar__tools');
      const filters = $(ctx, '.mlv-walkbar__filters');
      const stacked = width < 400;
      assert.equal(bar.getAttribute('data-layout'), 'narrow', width + ' px');
      assert.equal(bar.getAttribute('data-rows'), stacked ? 'stacked' : null, width + ' px');
      // The same document order at every width: the place, the line's slot, the controls.
      assert.deepEqual(Array.from($(ctx, '.mlv-walkbar__row').children).map((c) => c.className), ['mlv-walkbar__pos', 'mlv-walkbar__farslot', 'mlv-walkbar__tools']);
      assert.equal(ruleOf(slot, 'height'), '22px', 'the row for the line is there on every claim');
      if (stacked) {
        // The line first, on the whole row; then what the controls' box gives to the row, with
        // the place: Previous and Next, the place, Exit at the row's end; then the filters on the
        // rows under them. Previous and Next come before the place, so a place that grows ("9/16"
        // to "10/16", or by " · far end") does not move them under the pointer.
        assert.deepEqual([flexOf(slot), ruleOf(slot, 'order')], ['1 1 100%', '-2']);
        assert.deepEqual([ruleOf($(ctx, '.mlv-walkbar__steps'), 'order'), ruleOf($(ctx, '.mlv-walkbar__pos'), 'order'), ruleOf($(ctx, '.mlv-walkbar__exit'), 'order')], ['-1', null, null]);
        assert.equal(ruleOf(tools, 'display'), 'contents');
        assert.deepEqual([flexOf(filters), ruleOf(filters, 'order'), ruleOf(filters, 'flex-wrap')], ['1 1 100%', '1', 'wrap']);
        assert.equal(ruleOf($(ctx, '.mlv-walkbar__exit'), 'margin-left'), 'auto');
      } else {
        // The slot never asks for a row of its own: the place may grow ("100/176 · far end") and the bar stays.
        assert.deepEqual([flexOf(slot), ruleOf(slot, 'order')], ['1 1 0', null]);
        assert.deepEqual([ruleOf(tools, 'display'), flexOf(tools)], ['flex', '1 1 100%']);
        assert.equal(ruleOf($(ctx, '.mlv-walkbar__steps'), 'order'), null);
      }
      // The toolbar and the order of its buttons are the same either way.
      assert.equal(tools.getAttribute('role'), 'toolbar');
      const order = Array.from(tools.querySelectorAll('button:not([hidden])')).map((b) => b.getAttribute('data-walk-step') || b.getAttribute('data-walk-filter') || 'exit');
      assert.deepEqual(order, ['prev', 'next', 'notObserved', 'findings', 'all', 'exit']);
    } finally {
      ctx.app.destroy();
    }
  }

  // The panel is dragged across 400 px while the walk runs: the bar follows.
  const ctx = await mount(farDoc(), { width: 541 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const bar = $(ctx, '.mlv-walkbar');
    assert.equal(bar.hasAttribute('data-rows'), false);
    ctx.panel(399);
    assert.equal(bar.getAttribute('data-rows'), 'stacked');
    ctx.panel(320);
    assert.equal(bar.getAttribute('data-rows'), 'stacked');
    ctx.panel(400);
    assert.equal(bar.hasAttribute('data-rows'), false);
    assert.ok(farLine(ctx), 'the far line is still on show');
  } finally {
    ctx.app.destroy();
  }
});

test("the far line folds its words to the room it has: three one-line boxes that wrap, so the verb goes first, then the phase, then the distance, and the line's name keeps them all", async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const far = farLine(ctx);
    const kids = (element) => Array.from(element.children).map((c) => c.className.split(' ').pop());
    assert.deepEqual(kids(far), ['mlv-farglyph', 'mlv-walkbar__farway', 'mlv-walkbar__farbody', 'mlv-walkbar__farkey']);
    const body = $(ctx, '.mlv-walkbar__farbody');
    const lead = $(ctx, '.mlv-walkbar__farlead');
    const words = $(ctx, '.mlv-walkbar__farwords');
    assert.deepEqual([kids(body), kids(lead), kids(words)], [['mlv-walkbar__farlead', 'mlv-walkbar__farmore'], ['mlv-walkbar__farwords', 'mlv-walkbar__fardistance'], ['mlv-walkbar__farverb', 'mlv-walkbar__fartitle']]);
    assert.deepEqual(kids($(ctx, '.mlv-walkbar__farmore')), ['mlv-walkbar__fardot', 'mlv-walkbar__farphase']);
    // Each box is one line high and hides what wraps to a second line.
    for (const box of [body, lead, words]) {
      assert.deepEqual([ruleOf(box, 'display'), ruleOf(box, 'height'), ruleOf(box, 'overflow'), ruleOf(box, 'min-width')], ['flex', '20px', 'hidden', '0'], box.className);
    }
    assert.deepEqual([ruleOf(body, 'flex-wrap'), ruleOf(lead, 'flex-wrap')], ['wrap', 'wrap']);
    // The phase is the body's last child: it wraps when the lead would be under 188 px.
    assert.deepEqual([flexOf(body), flexOf(lead), flexOf($(ctx, '.mlv-walkbar__farmore'))], ['1 1 0', '1 1 188px', 'none']);
    // The distance is the lead's last child: it wraps when the words would be under 4em.
    assert.deepEqual([flexOf(words), flexOf($(ctx, '.mlv-walkbar__fardistance'))], ['1 1 4em', 'none']);
    // The words wrap upwards and keep their last line, so the verb, the first child, is what goes
    // when the title would be under 72 px; the title takes the room and is cut with an ellipsis.
    assert.deepEqual([ruleOf(words, 'flex-wrap'), ruleOf(words, 'align-content')], ['wrap-reverse', 'flex-end']);
    const title = $(ctx, '.mlv-walkbar__fartitle');
    assert.deepEqual([flexOf($(ctx, '.mlv-walkbar__farverb')), flexOf(title), ruleOf(title, 'min-width'), ruleOf(title, 'text-overflow')], ['none', '1 1 72px', '0', 'ellipsis']);
    for (const word of [$(ctx, '.mlv-walkbar__farverb'), title, $(ctx, '.mlv-walkbar__fardistance')]) assert.equal(ruleOf(word, 'height'), '20px', word.className);

    // Whatever is folded away on screen is in the name; the tooltip has the title and the phase.
    assert.equal(far.getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
    assert.match(far.title, /^Checkpoint\. Phase 3, Save\. /);
    assert.deepEqual([$(ctx, '.mlv-walkbar__farverb').textContent, title.textContent, $(ctx, '.mlv-walkbar__fardistance').textContent, $(ctx, '.mlv-walkbar__farphase').textContent], ['Go to', 'Checkpoint', '13 steps later', 'phase 3']);
    // A connection inside one phase has no phase to print; one that is not observed has its tag before the words.
    walkTo(ctx, 'c-optim-ckpt-2');
    assert.deepEqual(kids(farLine(ctx)), ['mlv-farglyph', 'mlv-walkbar__farway', 'mlv-walkbar__fartag', 'mlv-walkbar__farbody', 'mlv-walkbar__farkey']);
    walkTo(ctx, 'c-val-sched');
    assert.equal($(ctx, '.mlv-walkbar__farmore').hidden, true);
  } finally {
    ctx.app.destroy();
  }
});

/* ── short canvases, and a line in view end to end ───────────────────── */

test('on a canvas too short to show a card clear of the phase index, a step still names the far card, key o goes there and back to the same picture, and a card is not called a group', async () => {
  // 270 x 74 px: too short for a card clear of the phase index, which lies over its lower half.
  const small = { w: 270, h: 74 };
  const ctx = await mount(farDoc(), { canvas: small, width: 270 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const boxes = ctx.app.view.frame.boxes;
    assert.equal(ctx.app.view.far.inView(boxes.get('opts')), false, 'precondition: by the rule the source card is not in view, and cannot be');
    // What is in sight of its line, at this end and at the other, is a few pixels between a card
    // and the phase index, where a cap would lie on the card. After key o, at the far end, no cap
    // is drawn.
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
    assert.match(live(ctx), /Its far end is out of view, 13 steps later/);
    const left = viewport(ctx);

    press(ctx, 'o', {}, ctx.canvas);
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.source, state.target, state.line], ['target', false, true, 'Back to Options']);
    assert.match(state.place, / · far end$/);
    assert.deepEqual(state.caps, []);
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Back to the source: Options, 13 steps earlier, off screen above, in phase 1, Setup');
    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
    assert.deepEqual(viewport(ctx), left, 'the picture the reader left');

    // A canvas that changes size keeps the end it holds.
    ctx.resize(270, 80);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
    // Once the reader moves the view the rule applies again: the source is out of view. While some
    // of its card is on the canvas the line still names the far card; once it has left, o brings it back.
    ctx.app.view.viewport.panBy(-60, 0);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.line], [false, 'Go to Checkpoint']);
    ctx.app.view.viewport.panBy(-240, 0);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.line], [false, 'Back to Options']);
    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint', false);
    // The walk steps on.
    const place = ctx.app.walk.position;
    press(ctx, 'j', {}, ctx.canvas);
    assert.equal(ctx.app.walk.position, place + 1);
  } finally {
    ctx.app.destroy();
  }
});

test('on a canvas shorter than a card, a connection whose line is in view from end to end says that, and does not say both ends are in view while both cards are cut off', async () => {
  // 420 x 60 px: a card is 65 px high, so no card is ever whole. An end is then in view by the
  // place its line meets it.
  const size = { w: 420, h: 60 };
  const ctx = await mount(farDoc(), { canvas: size, width: 420 });
  try {
    walkTo(ctx, 'c-opts-seed');
    // The reader puts the short line between the two neighbours across the top of the canvas.
    const points = ctx.app.view.routes.find((r) => r.ids.includes('c-opts-seed')).points;
    const zoom = viewport(ctx).zoom;
    const first = points[0];
    const last = points[points.length - 1];
    ctx.app.view.viewport.set({ x: size.w / 2 - ((first.x + last.x) / 2) * zoom, y: 10 - Math.min(first.y, last.y) * zoom, zoom });
    const boxes = ctx.app.view.frame.boxes;
    assert.deepEqual([whole(drawn(ctx, boxes.get('opts')), size), whole(drawn(ctx, boxes.get('seed')), size)], [false, false], 'precondition: both cards are cut off by the canvas');
    const ends = ctx.app.view.far.ends('c-opts-seed');
    assert.deepEqual([ends.source.inView, ends.target.inView], [true, true], 'precondition: the line is on the canvas from end to end');
    assert.equal(farLine(ctx), null);
    assert.equal(caps(ctx).length, 0);
    assert.deepEqual([$(ctx, '.mlv-walkbar__faridle').hidden, $(ctx, '.mlv-walkbar__faridle').textContent], [false, 'Line in view end to end']);
    const here = viewport(ctx);
    assert.equal(press(ctx, 'o', {}, ctx.canvas).defaultPrevented, true);
    assert.equal(live(ctx), 'The line of this connection is in view end to end.');
    assert.deepEqual(viewport(ctx), here);
  } finally {
    ctx.app.destroy();
  }
});

test('a connection whose two ends are in view by its line reads "Line in view end to end" only while the whole line is: with a stretch of it under the phase index the bar reads "Both ends of the line in view", and key o says the same', async () => {
  // The 176-claim shape at 1080 x 767 px, c91: from a step to the open group above it, which is
  // larger than the canvas and so in view by the place the line meets it.
  const canvas = { w: 1080, h: 767 };
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS), { width: 1440, canvas });
  try {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'c91'; i++) press(ctx, 'j', {}, ctx.canvas);
    const idle = () => ($(ctx, '.mlv-walkbar__faridle').hidden ? null : $(ctx, '.mlv-walkbar__faridle').textContent);
    const inView = () => [ctx.app.view.far.ends('c91').source.inView, ctx.app.view.far.ends('c91').target.inView];
    /** How much of the line is on the canvas and not under the phase index (the cards hide none of it here), of its length. */
    const clear = () => {
      const vp = viewport(ctx);
      const covered = ctx.app.view.viewport.covered();
      const points = ctx.app.view.routes.find((r) => r.ids.includes('c91')).points.map((p) => ({ x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y }));
      let seen = 0;
      let total = 0;
      for (let i = 1; i < points.length; i++) {
        const length = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
        const n = Math.max(1, Math.ceil(length));
        for (let k = 0; k < n; k++) {
          const p = { x: points[i - 1].x + ((points[i].x - points[i - 1].x) * (k + 0.5)) / n, y: points[i - 1].y + ((points[i].y - points[i - 1].y) * (k + 0.5)) / n };
          total += length / n;
          if (p.x >= 0 && p.x <= canvas.w && p.y >= 0 && p.y <= canvas.h && !(p.x > covered.x && p.x < covered.x + covered.w && p.y > covered.y && p.y < covered.y + covered.h)) seen += length / n;
        }
      }
      return [Math.round(seen), Math.round(total)];
    };
    assert.equal(ctx.app.view.far.ends('c91').target.byLine, true, 'precondition: the far group is larger than the canvas');
    assert.deepEqual([inView(), idle(), farLine(ctx), clear()], [[true, true], 'Line in view end to end', null, [445, 445]]);

    // The reader moves the diagram 360 px down. Both ends are still in view; the line's bend now
    // runs under the phase index for 100 of its 445 px.
    ctx.app.view.viewport.panBy(0, 360);
    assert.deepEqual([inView(), clear()], [[true, true], [345, 445]], 'precondition');
    assert.deepEqual([idle(), farLine(ctx), caps(ctx).length], ['Both ends of the line in view', null, 0]);
    const moved = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(live(ctx), 'Both ends of the line of this connection are in view.');
    assert.deepEqual(viewport(ctx), moved, 'key o moves nothing');

    // 60 px back up the whole line is clear of the index again.
    ctx.app.view.viewport.panBy(0, -60);
    assert.deepEqual([inView(), clear(), idle()], [[true, true], [445, 445], 'Line in view end to end']);
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(live(ctx), 'The line of this connection is in view end to end.');
  } finally {
    ctx.app.destroy();
  }
});

test('on a canvas 150 px high, where the phase index leaves a card no room for a stretch of line beside it, the card itself is shown whole and clear of the index: the source of a connection the walk comes back to with k, and the far card of a dashed line after key o', async () => {
  // 541 x 150 px: the phase index lies over the canvas from 110 px down. Above it a card fits
  // whole, but not with a stretch of its line beside it.
  const short = { w: 541, h: 150 };
  const ctx = await mount(farDoc(), { canvas: short, width: 541 });
  try {
    const boxes = ctx.app.view.frame.boxes;
    const covered = ctx.app.view.viewport.covered();
    assert.deepEqual([covered.y, covered.h], [110, 28], 'precondition: where the phase index lies');
    /** The card by its own box: whole on the canvas and above the phase index. */
    const shown = (id) => {
      const r = drawn(ctx, boxes.get(id));
      return whole(r, short) && r.y + r.h <= covered.y + 0.5 && ctx.app.view.far.inView(boxes.get(id));
    };

    // Back with k from the step after it: the view stands at the far card, Scheduler, and the
    // source card, Validate, is two canvases and more to the right.
    walkTo(ctx, 'sched');
    assert.equal(drawn(ctx, boxes.get('val')).x > 2 * short.w, true, 'precondition: the source card is off the canvas');
    press(ctx, 'k', {}, ctx.canvas);
    atSource(ctx, 'c-val-sched', 'Scheduler');
    assert.equal(shown('val'), true, 'the source card is whole on the canvas, above the phase index');

    // The far card of a dashed line: the view moves to show the end of the line with it, which
    // here puts the card's foot under the index, and then the least that clears the card.
    walkBackTo(ctx, 'c-model-export-2');
    atSource(ctx, 'c-model-export-2', 'Export');
    assert.equal(shown('model'), true);
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    const state = farState(ctx, 'c-model-export-2');
    assert.deepEqual([state.keep, state.target, state.line], ['target', true, 'Back to Model']);
    assert.equal(shown('export'), true, 'the far card is whole on the canvas, above the phase index');
    // The card comes before the line on a canvas with room for one of them: 37 px or more of the
    // dashed line stay in sight with it here.
    const seen = lineInSight(ctx, 'c-model-export-2', short).seen;
    assert.ok(seen >= 37, Math.round(seen) + ' px of the line in sight');
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left, 'the picture the reader left');
  } finally {
    ctx.app.destroy();
  }
});

/* ── key o: the far end and back ─────────────────────────────────────── */

/**
 * Where the caps are drawn, by the left and top render/farcap.ts sets: "target 2px 255px",
 * upright with a "v".
 */
const capPlaces = (ctx) => caps(ctx).map((cap) => [cap.getAttribute('data-far-end'), cap.style.left, cap.style.top].join(' ') + (cap.classList.contains('mlv-farcap--v') ? ' v' : ''));

test('key o shows the far card of the walk\'s connection, centred, and pressed again puts back the picture it left; the claim, the selection and the keyboard stay', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    // The step's announcement names both ends, as on any connection, then says where the far one is.
    assert.equal(live(ctx), 'Claim 3 of 35: Connection c-opts-ckpt, from Options to Checkpoint. Its far end is out of view, 13 steps later, in phase 3, Save, about 1.4 screens down. o goes there and back.');
    assert.equal(farLine(ctx).title, 'Checkpoint. Phase 3, Save. About 1.4 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.');
    // The tooltip is for the pointer. What assistive technology is given as the line's description
    // adds only what its name lacks: the title and the phase are not said twice.
    const note = () => ctx.document.getElementById(farLine(ctx).getAttribute('aria-describedby'));
    assert.equal(farLine(ctx).getAttribute('aria-label'), 'Go to the far end: Checkpoint, 13 steps later, off screen below, in phase 3, Save');
    assert.deepEqual([note().hidden, note().textContent], [true, 'About 1.4 screens down. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.']);
    assert.doesNotMatch(note().textContent, /Checkpoint|Save/);
    // The boxed arrow before the distance points the way the far card lies: down.
    const arrow = () => $(ctx, '.mlv-walkbar__fararrow').style.transform;
    assert.equal(arrow(), 'rotate(90deg)');
    const left = { viewport: viewport(ctx), caps: capPlaces(ctx) };
    // The lit line leaves the canvas through its left edge: the cap lies along it, 2 px inside.
    assert.deepEqual(left.caps, ['target 2px 255px']);
    assert.equal(caps(ctx)[0].title, 'This connection continues to Checkpoint, 1.4 screens down. Click, or key o, to go there.');
    const place = ctx.app.walk.position;

    assert.equal(press(ctx, 'o', {}, ctx.canvas).defaultPrevented, true);
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.claim, state.keep, state.source, state.target, state.line], ['c-opts-ckpt', 'target', false, true, 'Back to Options']);
    // The far card is in the middle of the canvas, at the zoom the reader was at.
    const card = drawn(ctx, ctx.app.view.frame.boxes.get('ckpt'));
    assert.deepEqual([Math.round(card.x + card.w / 2), Math.round(card.y + card.h / 2), viewport(ctx).zoom], [271, 169, left.viewport.zoom]);
    // The line now ends in a cap towards the source, where it leaves through the top.
    assert.deepEqual(capPlaces(ctx), ['source 118px 2px v']);
    assert.equal(caps(ctx)[0].title, 'This connection continues to Options, 1.4 screens up. Click, or key o, to go there.');
    assert.equal(live(ctx), 'Far end of this connection: Checkpoint. o goes back to Options.');
    assert.equal(note().textContent, 'About 1.4 screens up. Click, Enter or key o goes back. The walk stays on this claim.');
    // The tooltip and the arrow are those of the end the line goes to now: the source, above.
    assert.equal(farLine(ctx).title, 'Options. Phase 1, Setup. About 1.4 screens up. Click, Enter or key o goes back. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(270deg)');
    // Only the view moved.
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c-opts-ckpt' });
    assert.match(lineOf(ctx, 'c-opts-ckpt').getAttribute('class'), /is-selected/);
    assert.equal(ctx.app.walk.position, place);
    assert.equal(ctx.document.activeElement, ctx.canvas);

    press(ctx, 'o', {}, ctx.canvas);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    assert.deepEqual({ viewport: viewport(ctx), caps: capPlaces(ctx) }, left, 'the picture the reader left, and the cap where it was');
    assert.equal(live(ctx), 'Back at the source of this connection: Options.');
    // There and back again; O does what o does.
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(capPlaces(ctx), ['source 118px 2px v']);
    press(ctx, 'O', {}, ctx.canvas);
    assert.deepEqual({ viewport: viewport(ctx), caps: capPlaces(ctx) }, left);
    // The host hears nothing of a look: no message follows the step's request for its cited lines.
    const pause = () => new Promise((resolve) => setTimeout(resolve, 250));
    await pause();
    const posted = ctx.bridge.posted.map((message) => message.type);
    assert.deepEqual(posted.slice(-1), ['openLocation'], 'the step asked for its cited lines');
    press(ctx, 'o', {}, ctx.canvas);
    await pause();
    press(ctx, 'o', {}, ctx.canvas);
    await pause();
    assert.deepEqual(ctx.bridge.posted.map((message) => message.type), posted, 'a look posts nothing to the host');
    // With Ctrl or Cmd the walk leaves the key unconsumed.
    for (const init of [{ ctrlKey: true }, { metaKey: true }]) assert.equal(press(ctx, 'o', init, ctx.canvas).defaultPrevented, false);
    assert.deepEqual(viewport(ctx), left.viewport);

    // An unresolved connection is called that at its far end, and its cap there is dotted too.
    walkTo(ctx, 'c-optim-ckpt-2');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(live(ctx), 'Far end of this unresolved connection: Checkpoint. o goes back to Optimizer.');
    assert.equal(farLine(ctx).getAttribute('aria-label'), '? unresolved connection. Back to the source: Optimizer, 9 steps earlier, off screen above and to the right, in phase 1, Setup');
    assert.deepEqual(caps(ctx).map((cap) => [cap.getAttribute('data-far-end'), cap.getAttribute('data-basis')]), [['source', 'unresolved']]);
    assert.equal(farLine(ctx).title, 'Unresolved connection. Optimizer. Phase 1, Setup. About 1.9 screens up and to the right. Click, Enter or key o goes back. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(315deg)');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(arrow(), 'rotate(135deg)');

    // A connection inside one phase, whose far card lies to the left: the tooltip names no phase.
    walkTo(ctx, 'c-val-sched');
    assert.equal(farLine(ctx).title, 'Scheduler. About 2.6 screens left. Click, Enter or key o goes there; the same again comes back. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(180deg)');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(farLine(ctx).title, 'Validate. About 2.9 screens right. Click, Enter or key o goes back. The walk stays on this claim.');
    assert.equal(arrow(), 'rotate(0deg)');
  } finally {
    ctx.app.destroy();
  }
});

test('key o leaves the far card of an observed connection in the middle of the canvas also where the 80 px of line next to it are not all in sight there: only a dashed or dotted line moves its far card', async () => {
  // The 79-claim shape at 541 x 337 px, c4, c21 and c9, chosen so that with the far card centred
  // the line next to it runs under the phase index or off the canvas.
  const ctx = await mount(shapedWorkflow(SHAPE_79_CLAIMS), { width: 541, canvas: CANVAS });
  try {
    press(ctx, 'r', {}, ctx.canvas);
    if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
    for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
    const seen = [];
    for (let i = 0; i < ctx.app.walk.list.length; i++) {
      if (i) press(ctx, 'j', {}, ctx.canvas);
      const claim = ctx.app.walk.current();
      if (claim.kind !== 'edge' || !['c4', 'c21', 'c9'].includes(claim.id)) continue;
      assert.equal(lineOf(ctx, claim.id).getAttribute('data-basis'), 'observed', claim.id + ': precondition: an observed line');
      press(ctx, 'o', {}, ctx.canvas);
      assert.match(farState(ctx, claim.id).place, / · far end$/, claim.id);
      const card = drawn(ctx, ctx.app.view.frame.boxes.get(ctx.app.view.far.ends(claim.id).target.drawnId));
      seen.push(claim.id);
      assert.deepEqual([Math.round(card.x + card.w / 2 - CANVAS.w / 2), Math.round(card.y + card.h / 2 - CANVAS.h / 2)], [0, 0], claim.id + ': the far card is centred');
      press(ctx, 'o', {}, ctx.canvas);
    }
    assert.deepEqual(seen.sort(), ['c21', 'c4', 'c9']);
  } finally {
    ctx.app.destroy();
  }
});

test('key o goes back to the picture the reader left last: after they moved the view at the source themselves, to that picture and not to the one the step made', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const step = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    // The reader drags back to the source by hand, to a picture of their own.
    const own = { x: step.x + 30, y: step.y + 20, zoom: step.zoom };
    ctx.app.view.viewport.set(own);
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.target, state.line, state.place], [true, false, 'Go to Checkpoint', '3/35'], 'precondition: the source is in view again');
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, 'c-opts-ckpt').place, / · far end$/);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), own, 'the picture they left, not the step\'s');
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');

    // From the far end they pan until neither card is in view: o still knows the way back.
    press(ctx, 'o', {}, ctx.canvas);
    ctx.app.view.viewport.panBy(0, 150);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.source, state.target, state.line], [false, false, 'Back to Options']);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), own);
  } finally {
    ctx.app.destroy();
  }
});

test('key o at the far end goes back to the picture left at the source also after the reader zoomed out there until the two cards could be shown together: that picture at its own zoom, not both cards at the reader\'s', async () => {
  const id = 'c-opts-ckpt';
  const ctx = await mount();
  try {
    const left = lookAtFarEnd(ctx, id);
    // At the far end the reader zooms out to 50% and scrolls the diagram 120 px up. The far card is
    // still in view, and at this zoom some pan would show the source card with it.
    ctx.app.view.viewport.zoomAt(0.5 / left.zoom, CANVAS.w / 2, CANVAS.h / 2);
    scroll(ctx, 0, -120);
    const ends = ctx.app.view.far.ends(id);
    assert.deepEqual([ends.keep, ends.together, ends.source.inView, ends.target.inView], ['target', true, false, true], 'precondition');
    const state = farState(ctx, id);
    assert.deepEqual([state.place, state.line], ['3/35 · far end', 'Back to Options']);
    assert.match(farLine(ctx).title, /key o goes back\. The walk stays on this claim\.$/);
    // Key o is the way back it was: the picture the reader left at the source, at reading size.
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
    assert.equal(live(ctx), 'Back at the source of this connection: Options.');
    atSource(ctx, id, 'Checkpoint');
  } finally {
    ctx.app.destroy();
  }
});

test('key o from a picture that cuts the source card off comes back to that picture, moved only as far as shows the card whole; a step from the far end starts from it too', async () => {
  for (const id of ['c-optim-ckpt-2', 'c-val-sched']) {
    const ctx = await mount();
    const control = await mount();
    try {
      const source = (panel) => drawn(panel, panel.app.view.frame.boxes.get(panel.app.index.edgeById.get(id).source));
      for (const panel of [ctx, control]) {
        walkTo(panel, id);
        // The reader drags the diagram 30 px to the left and up until 24 px of the source card are
        // above the canvas. The line still names the far card.
        pressBackground(panel, [[100, 60], [70, 100 - source(panel).y - 24]]);
      }
      const dragged = { viewport: viewport(ctx), card: source(ctx) };
      assert.deepEqual(viewport(control), dragged.viewport);
      assert.deepEqual([Math.round(dragged.card.y), farState(ctx, id).source, farState(ctx, id).line.startsWith('Go to ')], [-24, false, true], id + ': precondition');
      press(ctx, 'o', {}, ctx.canvas);
      assert.match(farState(ctx, id).place, / · far end$/, id);
      // Back: the picture they left, 40 px lower, so that the card is whole with the 16 px a step
      // leaves above it. Nothing has moved sideways, as it would in a picture made from the far end.
      press(ctx, 'o', {}, ctx.canvas);
      assert.deepEqual(viewport(ctx), { x: dragged.viewport.x, y: dragged.viewport.y + 40, zoom: dragged.viewport.zoom }, id);
      assert.deepEqual([Math.round(source(ctx).x), Math.round(source(ctx).y)], [Math.round(dragged.card.x), 16], id);
      const state = farState(ctx, id);
      assert.deepEqual([state.keep, state.source, state.target, state.line.startsWith('Go to ')], ['source', true, false, true], id);
      // There and back again from this picture is exact.
      const here = viewport(ctx);
      press(ctx, 'o', {}, ctx.canvas);
      press(ctx, 'o', {}, ctx.canvas);
      assert.deepEqual(viewport(ctx), here, id);

      // From the far end of a look that started at such a picture, the next step is the one a
      // reader gets who dragged the same way and never looked.
      ctx.app.view.viewport.set(dragged.viewport);
      press(ctx, 'o', {}, ctx.canvas);
      for (const panel of [ctx, control]) press(panel, 'j', {}, panel.canvas);
      assert.deepEqual([ctx.app.walk.current().id, viewport(ctx)], [control.app.walk.current().id, viewport(control)], id + ': the step after');
    } finally {
      ctx.app.destroy();
      control.app.destroy();
    }
  }

  // A picture left at the source with the card whole is kept over a later one that cuts it off.
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    // From the far end the reader drags back until 24 px of the source card are above the canvas,
    // and goes to the far end again by the cap towards it.
    ctx.app.view.viewport.set(left);
    ctx.app.view.viewport.panBy(0, -drawn(ctx, ctx.app.view.frame.boxes.get('opts')).y - 24);
    const state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.source, state.target, state.line, state.caps], ['target', false, false, 'Back to Options', ['target']], 'precondition');
    caps(ctx)[0].dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
    assert.match(farState(ctx, 'c-opts-ckpt').place, / · far end$/);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
  } finally {
    ctx.app.destroy();
  }
});

test('key o back from a picture that cut the source card of a dotted line off at the canvas\'s foot shows the card with 80 px or more of that line, and from a picture the reader had zoomed out it comes back at reading size', async () => {
  const id = 'c-optim-ckpt-2';
  const ctx = await mount();
  try {
    walkTo(ctx, id);
    const box = ctx.app.view.frame.boxes.get('optim');
    const step = viewport(ctx);
    /** The reader drags the diagram down until 24 px of the source card are under the canvas's foot. */
    const cutAtFoot = () => {
      ctx.app.view.viewport.panBy(0, CANVAS.h - (drawn(ctx, box).y + drawn(ctx, box).h) + 24);
      assert.deepEqual([farState(ctx, id).source, farState(ctx, id).line], [false, 'Go to Checkpoint'], 'precondition');
    };
    cutAtFoot();
    assert.ok(lineInSight(ctx, id, CANVAS).seen < MIN_IN_SIGHT, 'precondition: the picture left shows ' + Math.round(lineInSight(ctx, id, CANVAS).seen) + ' px of the line');
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, id).place, / · far end$/);
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(ctx.app.view.far.inView(box), true, 'the source card is whole');
    let seen = lineInSight(ctx, id, CANVAS).seen;
    assert.ok(seen >= MIN_IN_SIGHT, Math.round(seen) + ' px of the dotted line in sight');
    assert.equal(viewport(ctx).zoom, step.zoom);

    // The same from a picture the reader had zoomed out to 52%: back at reading size, as a step
    // onto the card would be, with the line.
    ctx.app.view.viewport.set(step);
    ctx.app.view.viewport.zoomAt(0.52 / step.zoom, CANVAS.w / 2, CANVAS.h / 2);
    cutAtFoot();
    assert.ok(Math.abs(viewport(ctx).zoom - 0.52) < 0.001, 'precondition');
    press(ctx, 'o', {}, ctx.canvas);
    press(ctx, 'o', {}, ctx.canvas);
    seen = lineInSight(ctx, id, CANVAS).seen;
    assert.deepEqual([viewport(ctx).zoom, ctx.app.view.far.inView(box), seen >= MIN_IN_SIGHT], [0.9, true, true], Math.round(seen) + ' px of the dotted line in sight');
  } finally {
    ctx.app.destroy();
  }
});

test('a look at the far end and back leaves nothing behind: a later look from a picture that cuts the source card off comes back as in a panel where the reader had not looked before', async () => {
  const looked = await mount();
  const never = await mount();
  try {
    for (const ctx of [looked, never]) walkTo(ctx, 'c-opts-ckpt');
    // In one panel the reader looks at the far end and comes back.
    press(looked, 'o', {}, looked.canvas);
    press(looked, 'o', {}, looked.canvas);
    assert.deepEqual(viewport(looked), viewport(never));
    for (const ctx of [looked, never]) {
      // They drag until 24 px of the source card are above the canvas, and look from there: the
      // way back is that picture with the card brought into view.
      const source = drawn(ctx, ctx.app.view.frame.boxes.get('opts'));
      pressBackground(ctx, [[100, 60], [100, 100 - source.y - 24]]);
      press(ctx, 'o', {}, ctx.canvas);
      assert.match(farState(ctx, 'c-opts-ckpt').place, / · far end$/);
      press(ctx, 'o', {}, ctx.canvas);
      atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    }
    // The same picture in both panels: the one of the first look, which was put back once, is
    // not put back again.
    assert.deepEqual(viewport(looked), viewport(never));
  } finally {
    looked.app.destroy();
    never.app.destroy();
  }
});

test('key o back on a canvas that changed while the reader looked at the far end shows the source card whole: the picture left on the other canvas is put back only where it still shows the card', async () => {
  const sourceBox = (ctx, id) => ctx.app.view.frame.boxes.get(ctx.app.index.edgeById.get(id).source);
  const sourceWhole = (ctx, id) => ctx.app.view.far.inView(sourceBox(ctx, id));
  // The canvas gets shorter, or narrower and shorter (the sheet under it opens, the panel is dragged).
  for (const [id, title, size] of [['c-opts-ckpt', 'Checkpoint', { w: 541, h: 180 }], ['c-optim-ckpt-2', 'Checkpoint', { w: 400, h: 200 }]]) {
    const ctx = await mount();
    try {
      walkTo(ctx, id);
      const left = viewport(ctx);
      press(ctx, 'o', {}, ctx.canvas);
      ctx.resize(size.w, size.h);
      assert.match(farState(ctx, id).place, / · far end$/, id + ': the resize keeps the far card');
      press(ctx, 'o', {}, ctx.canvas);
      // Put back as it was, the picture would cut the card off at the canvas's new foot.
      const box = sourceBox(ctx, id);
      const card = { x: box.x * left.zoom + left.x, y: box.y * left.zoom + left.y, w: box.w * left.zoom, h: box.h * left.zoom };
      assert.equal(whole(card, size), false, id + ': precondition: the picture left does not show the card on this canvas');
      assert.equal(sourceWhole(ctx, id), true, id + ': the source card is whole on the canvas and clear of the phase index');
      atSource(ctx, id, title);
      assert.equal(live(ctx), 'Back at the source of this ' + (id === 'c-optim-ckpt-2' ? 'unresolved ' : '') + 'connection: ' + (id === 'c-opts-ckpt' ? 'Options' : 'Optimizer') + '.');
      // And there and back again from this picture is exact.
      const here = viewport(ctx);
      press(ctx, 'o', {}, ctx.canvas);
      press(ctx, 'o', {}, ctx.canvas);
      assert.deepEqual(viewport(ctx), here);
    } finally {
      ctx.app.destroy();
    }
  }

  // The list of phases is opened at the far end, over the place the source card had.
  let ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    $(ctx, '.mlv-phaseindex__pill').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
    press(ctx, 'o', {}, ctx.canvas);
    assert.notDeepEqual(viewport(ctx), left, 'precondition: the picture left has the card under the open list');
    assert.equal(sourceWhole(ctx, 'c-opts-ckpt'), true);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
  } finally {
    ctx.app.destroy();
  }

  // A canvas that changed and still shows the card in the picture left: that picture, exactly.
  ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    ctx.resize(300, 337);
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
  } finally {
    ctx.app.destroy();
  }
});

/** The far-connection document with every step in one phase: the viewer then shows no phase index. */
function onePhaseDoc() {
  const doc = farDoc();
  doc.phases = [{ id: 'setup', label: 'Setup' }];
  for (const node of doc.nodes) node.phase = 'setup';
  return doc;
}

test('in a document of one phase, which has no phase index, key o back on a canvas that got shorter shows the source card whole: the canvas\'s height alone tells that the picture left no longer shows it', async () => {
  for (const id of ['c-opts-ckpt', 'c-optim-ckpt-2']) {
    const ctx = await mount(onePhaseDoc());
    try {
      walkTo(ctx, id);
      assert.equal(ctx.app.view.viewport.covered(), null, 'precondition: no phase index');
      const box = ctx.app.view.frame.boxes.get(ctx.app.index.edgeById.get(id).source);
      // The reader drags the diagram down until the source card stands 6 px above the canvas's foot.
      ctx.app.view.viewport.panBy(0, CANVAS.h - 6 - (drawn(ctx, box).y + drawn(ctx, box).h));
      assert.equal(ctx.app.view.far.inView(box), true, 'precondition');
      press(ctx, 'o', {}, ctx.canvas);
      assert.match(farState(ctx, id).place, / · far end$/);
      ctx.resize(541, 302);
      press(ctx, 'o', {}, ctx.canvas);
      assert.equal(ctx.app.view.far.inView(box), true, id + ': the source card is whole on the shorter canvas');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('key o back on a canvas that got shorter, to a picture the reader had zoomed out: the source is shown at the zoom that canvas allows; that zoom is the viewer\'s, so the next step returns to reading size from it', async () => {
  // c-loop-ckpt starts at the open group, wider than the canvas: the walk shows the place its line
  // leaves the group.
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-loop-ckpt');
    // The reader zooms out below full detail (three steps of the zoom control) and looks at the far end.
    for (let i = 0; i < 3; i++) ctx.app.view.zoomStep(-1);
    const left = viewport(ctx);
    assert.ok(left.zoom < 0.62 && ctx.app.getState().framedZoom === undefined, 'precondition: the reader\'s zoom, below full detail, at ' + left.zoom);
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, 'c-loop-ckpt').place, / · far end$/);
    // The canvas gets shorter (the sheet under it opens). Back: the picture left does not show the
    // place on this canvas, so the walk shows it as a step would, zoomed in as far as it fits.
    ctx.resize(541, 120);
    press(ctx, 'o', {}, ctx.canvas);
    const back = viewport(ctx).zoom;
    assert.ok(back >= 0.62 && back < 0.75, 'precondition: at full detail and under reading size, at ' + back);
    atSource(ctx, 'c-loop-ckpt', 'Checkpoint', false);
    assert.equal(ctx.app.getState().framedZoom, back, 'the viewer\'s zoom, not one the reader chose');
    // On the usual canvas again the next step is at reading size; a zoom the reader chose would stay.
    ctx.resize(541, 337);
    assert.equal(viewport(ctx).zoom, back);
    press(ctx, 'j', {}, ctx.canvas);
    assert.deepEqual([ctx.app.walk.current().id, viewport(ctx).zoom], ['batch', 0.9]);
  } finally {
    ctx.app.destroy();
  }
});

test('a group folded while the reader looks at the far end moves the source card: key o shows the card where it is now, not the place it was', async () => {
  // The far-connection document with a connection that runs back up, from Checkpoint (phase 3) to
  // Options (phase 1): folding the group between them moves its source card up.
  const doc = farDoc();
  doc.edges.push({ id: 'c-ckpt-opts', source: 'ckpt', target: 'opts', label: 'resume', basis: 'observed', evidence: ['e1'] });
  const ctx = await mount(doc);
  try {
    walkTo(ctx, 'c-ckpt-opts');
    assert.ok(farLine(ctx), 'precondition: the connection is far');
    // The reader moves the diagram until the source card is 4 px under the canvas's top: still whole.
    ctx.app.view.viewport.panBy(0, 4 - drawn(ctx, ctx.app.view.frame.boxes.get('ckpt')).y);
    assert.equal(ctx.app.view.far.inView(ctx.app.view.frame.boxes.get('ckpt')), true, 'precondition: the source card is whole');
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    assert.match($(ctx, '.mlv-walkbar__postext').textContent, / · far end$/);
    ctx.app.view.toggleCollapse('loop');
    const now = ctx.app.view.frame.boxes.get('ckpt');
    const stale = { x: now.x * left.zoom + left.x, y: now.y * left.zoom + left.y, w: now.w * left.zoom, h: now.h * left.zoom };
    assert.equal(whole(stale, CANVAS), false, 'precondition: the picture left no longer holds the card (it would be at y ' + Math.round(stale.y) + ')');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(ctx.app.view.far.inView(ctx.app.view.frame.boxes.get('ckpt')), true, 'the source card is whole on the canvas');
    assert.doesNotMatch($(ctx, '.mlv-walkbar__postext').textContent, /far end/);
  } finally {
    ctx.app.destroy();
  }
});

test('key o on a connection with both cards in view says so and moves nothing; on a step or a finding, and without a walk, the key is not the viewer\'s', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-seed-data');
    const near = viewport(ctx);
    assert.equal(farLine(ctx), null);
    assert.equal($(ctx, '.mlv-walkbar__faridle').textContent, 'Both ends in view');
    assert.equal(press(ctx, 'o', {}, ctx.canvas).defaultPrevented, true, 'the walk is on a connection: the key is answered');
    assert.equal(live(ctx), 'Both ends of this connection are in view.');
    assert.deepEqual(viewport(ctx), near);
    assert.doesNotMatch($(ctx, '.mlv-walkbar__postext').textContent, /far end/);
    assert.equal(caps(ctx).length, 0);
    assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection)], ['c-seed-data', { kind: 'edge', id: 'c-seed-data' }]);

    // On a step and on a finding the walk has no other end to go to.
    for (const id of ['model', 'f-save']) {
      walkTo(ctx, id);
      const said = live(ctx);
      const before = viewport(ctx);
      assert.equal(press(ctx, 'o', {}, ctx.canvas).defaultPrevented, false, id);
      assert.deepEqual([live(ctx), viewport(ctx)], [said, before], id);
    }
    // Without a walk, on a selected far connection: nothing.
    press(ctx, 'Escape', {}, ctx.canvas);
    ctx.app.select({ kind: 'edge', id: 'c-opts-ckpt' });
    const before = viewport(ctx);
    assert.equal(press(ctx, 'o', {}, ctx.canvas).defaultPrevented, false);
    assert.deepEqual(viewport(ctx), before);
    assert.equal(caps(ctx).length, 0, 'no cap outside the walk');
  } finally {
    ctx.app.destroy();
  }
});

test('the shortcut sheet lists key o, and says what ← and → do on a connection whose other end is out of view', async () => {
  const ctx = await mount();
  try {
    press(ctx, '?', {}, ctx.canvas);
    assert.equal(ctx.app.sheet.open, true);
    // The sheet prints the key table itself; the walk answers o, so the table must list it.
    const rows = $$(ctx, '.mlv-sheet__keys').map((keys) => [Array.from(keys.querySelectorAll('kbd')).map((key) => key.textContent), keys.nextElementSibling.textContent]);
    assert.deepEqual(rows.find(([keys]) => keys.includes('o')), [['o'], 'In the review walk, on a connection whose other end is out of view: show both ends if they fit the diagram together; if not, go to that end, and o again comes back (the walk stays on the connection)']);
    const arrows = rows.find(([keys]) => keys.includes('ArrowLeft'));
    assert.deepEqual(arrows[0], ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight']);
    assert.match(arrows[1], /^Move the selection \(from a connection, to its end that lies that way; /);
    assert.match(arrows[1], /from the connection the walk is on, ← and → show the end that lies that way if it is out of view, while the walk stays on the connection; if that end is in view, the selection moves to it or stays\)$/);
    // No other row gives o another meaning.
    assert.equal(rows.filter(([keys]) => keys.some((key) => key.toLowerCase() === 'o')).length, 1);
  } finally {
    ctx.app.destroy();
  }
});

test('at the far end the walk\'s place says so: "3/35 · far end" in a narrow panel, "Claim 30 of 35, far end" in a wide one, and in the words a screen reader is given', async () => {
  let ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const text = () => $(ctx, '.mlv-walkbar__postext').textContent;
    assert.equal(text(), '3/35');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(text(), '3/35 · far end');
    // Narrow, the short form is for the eye; the sentence beside it is what is read out.
    assert.equal($(ctx, '.mlv-walkbar__postext').getAttribute('aria-hidden'), 'true');
    assert.equal($(ctx, '.mlv-walkbar__posspoken').textContent, 'Claim 3 of 35, far end, All claims');
    assert.match($(ctx, '.mlv-walkbar__pos').title, /^Claim 3 of 35, far end · All claims\. /);
    // The reader pans until the far card is cut by the canvas's edge: this is not the far end.
    ctx.app.view.viewport.panBy(0, 150);
    assert.equal(text(), '3/35');
    assert.ok(farLine(ctx), 'the line stays while an end is out of view');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(text(), '3/35');
    // A step from the far end drops it with the claim.
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(text(), '3/35 · far end');
    press(ctx, 'j', {}, ctx.canvas);
    assert.equal(text(), '4/35');
    assert.equal($(ctx, '.mlv-walkbar__posspoken').textContent, 'Claim 4 of 35, All claims');
  } finally {
    ctx.app.destroy();
  }
  // Wide (the canvas of a 1440 x 900 px panel).
  ctx = await mount(farDoc(), { width: 1440, canvas: { w: 1080, h: 767 } });
  try {
    walkTo(ctx, 'c-val-sched');
    const text = () => $(ctx, '.mlv-walkbar__postext').textContent;
    assert.equal(text(), 'Claim 30 of 35 · All claims');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(text(), 'Claim 30 of 35, far end · All claims');
    assert.equal($(ctx, '.mlv-walkbar__pos').title, 'Claim 30 of 35, far end · All claims');
    press(ctx, 'o', {}, ctx.canvas);
    assert.equal(text(), 'Claim 30 of 35 · All claims');
  } finally {
    ctx.app.destroy();
  }
});

/* ── the arrow keys, and j and k ─────────────────────────────────────── */

test('on a far connection ← and → look at the end that lies that way, or say the reader is at it, and the walk stays on the claim; with both cards in view they select the card as on any connection', async () => {
  const ctx = await mount();
  try {
    // Validate to Scheduler: the far card lies to the left.
    walkTo(ctx, 'c-val-sched');
    const left = viewport(ctx);
    const still = () => assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position, plain(ctx.app.selection)], ['c-val-sched', 29, { kind: 'edge', id: 'c-val-sched' }]);
    assert.equal(press(ctx, 'ArrowLeft', {}, ctx.canvas).defaultPrevented, true);
    let state = farState(ctx, 'c-val-sched');
    assert.deepEqual([state.keep, state.target, state.place, state.line], ['target', true, '30/35 · far end', 'Back to Validate']);
    assert.equal(live(ctx), 'Far end of this connection: Scheduler. o goes back to Validate.');
    still();
    const far = viewport(ctx);
    // Again the same way: the reader is there already. Nothing moves and nothing else is selected.
    assert.equal(press(ctx, 'ArrowLeft', {}, ctx.canvas).defaultPrevented, true);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    assert.deepEqual(viewport(ctx), far);
    still();
    // The other way: back to the picture left at the source.
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
    assert.equal(live(ctx), 'Back at the source of this connection: Validate.');
    atSource(ctx, 'c-val-sched', 'Scheduler');
    // And again: at the source already. No card is selected, and the walk stays on its claim.
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), left);
    still();

    // Options to Checkpoint, one above the other: → is towards the target, ← towards the source.
    walkBackTo(ctx, 'c-opts-ckpt');
    const top = viewport(ctx);
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), top);
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.claim, state.keep, state.place], ['c-opts-ckpt', 'target', '3/35 · far end']);
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), top);
    // ↓ and ↑ step through the claims on a far connection as on any other.
    press(ctx, 'ArrowDown', {}, ctx.canvas);
    assert.equal(ctx.app.walk.current().id, 'seed');
    press(ctx, 'ArrowUp', {}, ctx.canvas);
    assert.equal(ctx.app.walk.current().id, 'c-opts-ckpt');

    // Seed to Dataset, both cards on the canvas: the arrow selects the card, and the walk follows.
    walkTo(ctx, 'c-seed-data');
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: 'data' });
    assert.equal(ctx.app.walk.current().id, 'data');
    assert.equal(live(ctx), 'Selected step Dataset, Setup phase, train.py line 3.');
    press(ctx, 'k', {}, ctx.canvas);
    assert.equal(ctx.app.walk.current().id, 'c-seed-data');
    press(ctx, 'ArrowLeft', {}, ctx.canvas);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: 'seed' });
  } finally {
    ctx.app.destroy();
  }
});

test('j and k from the far end go to the next and the previous claim and show it as a walk that never looked does', async () => {
  const ctx = await mount();
  const control = await mount();
  try {
    const same = (id, what) => assert.deepEqual([farState(ctx, id), viewport(ctx), capPlaces(ctx)], [farState(control, id), viewport(control), capPlaces(control)], what);
    for (const panel of [ctx, control]) walkTo(panel, 'c-val-sched');
    press(ctx, 'o', {}, ctx.canvas);
    assert.match(farState(ctx, 'c-val-sched').place, / · far end$/);
    // j: claim 31, the step Scheduler, from the picture left at the source, not from the far end.
    for (const panel of [ctx, control]) press(panel, 'j', {}, panel.canvas);
    assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position], ['sched', 30]);
    nothingFar(ctx, 'c-val-sched');
    same('c-val-sched', 'after j');
    // k back onto the connection: shown from its source again.
    for (const panel of [ctx, control]) press(panel, 'k', {}, panel.canvas);
    atSource(ctx, 'c-val-sched', 'Scheduler');
    same('c-val-sched', 'after k');
    // k from the far end: claim 29, the step Validate.
    press(ctx, 'o', {}, ctx.canvas);
    for (const panel of [ctx, control]) press(panel, 'k', {}, panel.canvas);
    assert.deepEqual([ctx.app.walk.current().id, ctx.app.walk.position], ['val', 28]);
    nothingFar(ctx, 'c-val-sched');
    same('c-val-sched', 'after k from the far end');
  } finally {
    ctx.app.destroy();
    control.app.destroy();
  }
});

test('j never stops at the far end of an inferred or unresolved connection: the Not observed walk of the 176-claim shape is 15 presses for 16 claims, 7 of them far connections', async () => {
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS));
  try {
    press(ctx, 'r', {}, ctx.canvas);
    assert.deepEqual([ctx.app.walk.filter, ctx.app.walk.list.length], ['notObserved', 16]);
    let far = 0;
    const seen = [];
    for (let presses = 0; presses < 16; presses++) {
      const claim = ctx.app.walk.current();
      assert.equal(ctx.app.walk.position, presses, 'one claim a press');
      seen.push(claim.kind + ':' + claim.id);
      assert.doesNotMatch($(ctx, '.mlv-walkbar__postext').textContent, /far end/, claim.id);
      if (claim.kind === 'edge' && farLine(ctx)) {
        // Shown from its source, with its far end named in the bar: the step did not go there.
        const ends = ctx.app.view.far.ends(claim.id);
        assert.deepEqual([ends.keep, ends.source.inView, ends.target.inView], ['source', true, false], claim.id);
        assert.match(farLine(ctx).getAttribute('aria-label'), /^(inferred|\? unresolved) connection\. Go to the far end: /, claim.id);
        far++;
      }
      press(ctx, 'j', {}, ctx.canvas);
    }
    assert.equal(new Set(seen).size, 16);
    assert.equal(far, 7);
    assert.equal(live(ctx), 'Claim 16 of 16 is the last one.', 'the sixteenth press found nothing after the last claim');
  } finally {
    ctx.app.destroy();
  }
  // And in a walk over every claim: from an unresolved far connection j goes to the claim after it.
  const all = await mount();
  try {
    walkTo(all, 'c-optim-ckpt-2');
    assert.ok(farLine(all));
    press(all, 'j', {}, all.canvas);
    assert.deepEqual([all.app.walk.current().id, $(all, '.mlv-walkbar__postext').textContent], ['loop', '15/35']);
  } finally {
    all.app.destroy();
  }
});

/* ── the line in the bar: Tab, Enter, Space, a click; the cap: a click ── */

/**
 * The elements Tab stops at, in order. The viewer uses no positive tabindex, so the order is the
 * document's: whatever can take the focus, is not disabled and is not inside something hidden.
 */
function tabStops(ctx) {
  const shown = (element) => {
    for (let node = element; node && node.nodeType === 1; node = node.parentElement) if (node.hidden) return false;
    return true;
  };
  const index = (element) => (element.hasAttribute('tabindex') ? Number(element.getAttribute('tabindex')) : /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(element.tagName) ? 0 : -1);
  return $$(ctx, 'a[href], button, input, select, textarea, [tabindex]').filter((element) => index(element) >= 0 && !element.disabled && shown(element));
}

test('the far line is the Tab stop after the diagram and before the walk\'s controls; it is a button, so Enter and Space press it, and the focus stays on it there and back', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const line = farLine(ctx);
    let stops = tabStops(ctx);
    let at = stops.indexOf(ctx.canvas);
    assert.equal(stops[at + 1], line, 'Tab from the diagram lands on the line');
    assert.ok(stops[at + 2].closest('.mlv-walkbar__tools'), 'Tab again goes to the walk\'s controls');
    assert.equal(stops.filter((stop) => stop.closest('.mlv-walkbar')).length, 2, 'the bar is two stops: the line, and its toolbar');
    // The cap on the canvas is a picture and a pointer's shortcut: no Tab stop, nothing for a screen reader.
    assert.equal(stops.some((stop) => stop.closest('.mlv-farcaps')), false);
    assert.equal($(ctx, '.mlv-farcaps').getAttribute('aria-hidden'), 'true');
    assert.deepEqual([line.tagName, line.type, line.getAttribute('aria-keyshortcuts'), line.hasAttribute('tabindex')], ['BUTTON', 'button', 'o', false]);

    // Enter and Space reach the button unanswered by the walk's keys. jsdom does not press a
    // button for a key, so the click below stands for the one a browser sends.
    line.focus();
    assert.equal(ctx.document.activeElement, line);
    const left = viewport(ctx);
    for (const key of ['Enter', ' ']) {
      assert.equal(press(ctx, key, {}, line).defaultPrevented, false, JSON.stringify(key) + ' is left to the button');
      assert.deepEqual(viewport(ctx), left);
    }
    line.click();
    assert.match($(ctx, '.mlv-walkbar__postext').textContent, / · far end$/);
    assert.equal(ctx.document.activeElement, farLine(ctx), 'the focus stays on the line');
    assert.equal(farLine(ctx), line, 'the same button, now "Back to"');
    assert.equal($(ctx, '.mlv-walkbar__farverb').textContent, 'Back to');
    line.click();
    assert.deepEqual(viewport(ctx), left);
    assert.equal(ctx.document.activeElement, line);
    // The walk's keys work from the line too: o is the same press, j steps on.
    assert.equal(press(ctx, 'o', {}, line).defaultPrevented, true);
    assert.match($(ctx, '.mlv-walkbar__postext').textContent, / · far end$/);
    assert.equal(ctx.document.activeElement, line);
    press(ctx, 'o', {}, line);
    assert.deepEqual(viewport(ctx), left);
    press(ctx, 'j', {}, line);
    assert.equal(ctx.app.walk.current().id, 'seed');
    // The line went with the claim: the diagram has the keyboard, not a hidden button.
    assert.equal(farLine(ctx), null);
    assert.equal(ctx.document.activeElement, ctx.canvas);
    // Without a line the diagram's next stop is the toolbar.
    stops = tabStops(ctx);
    at = stops.indexOf(ctx.canvas);
    assert.ok(stops[at + 1].closest('.mlv-walkbar__tools'));

    // Escape on the line at the far end ends the walk, and the diagram has the keyboard.
    press(ctx, 'k', {}, ctx.canvas);
    press(ctx, 'o', {}, ctx.canvas);
    farLine(ctx).focus();
    press(ctx, 'Escape', {}, farLine(ctx));
    assert.equal(ctx.app.walk.active, false);
    assert.equal(ctx.document.activeElement, ctx.canvas);
  } finally {
    ctx.app.destroy();
  }
});

test('← and → on the far line do what they do from the diagram: with the focus left on the line by a click, the arrow towards the far card goes there, the same again says the reader is at it, and the other comes back; the focus stays on the line', async () => {
  const ctx = await mount();
  try {
    // Validate to Scheduler: the far card lies to the left.
    walkTo(ctx, 'c-val-sched');
    const left = viewport(ctx);
    const line = farLine(ctx);
    const still = (what) => assert.deepEqual([ctx.app.walk.current().id, plain(ctx.app.selection), ctx.document.activeElement], ['c-val-sched', { kind: 'edge', id: 'c-val-sched' }, line], what);
    // A click on the line goes to the far end and back; focus() stands for the focus a click
    // leaves on the button.
    line.focus();
    line.click();
    line.click();
    assert.deepEqual(viewport(ctx), left);
    still('after two clicks');

    assert.equal(press(ctx, 'ArrowLeft', {}, line).defaultPrevented, true);
    let state = farState(ctx, 'c-val-sched');
    assert.deepEqual([state.keep, state.target, state.place, state.line], ['target', true, '30/35 · far end', 'Back to Validate']);
    assert.equal(live(ctx), 'Far end of this connection: Scheduler. o goes back to Validate.');
    still('after ←');
    const far = viewport(ctx);
    assert.equal(press(ctx, 'ArrowLeft', {}, line).defaultPrevented, true);
    assert.equal(live(ctx), 'This is the far end of the connection.');
    assert.deepEqual(viewport(ctx), far);
    still('after ← again');
    press(ctx, 'ArrowRight', {}, line);
    assert.deepEqual(viewport(ctx), left);
    assert.equal(live(ctx), 'Back at the source of this connection: Validate.');
    press(ctx, 'ArrowRight', {}, line);
    assert.equal(live(ctx), 'This is where the connection starts.');
    assert.deepEqual(viewport(ctx), left);
    still('after → twice');

    // With Ctrl or Cmd the line leaves the arrow unconsumed, and ↑ and ↓ are not the line's.
    for (const [key, init] of [['ArrowLeft', { ctrlKey: true }], ['ArrowLeft', { metaKey: true }], ['ArrowUp', {}], ['ArrowDown', {}]]) {
      assert.equal(press(ctx, key, init, line).defaultPrevented, false, key + ' ' + JSON.stringify(init));
      assert.deepEqual(viewport(ctx), left);
    }
    still('after keys that are not the line\'s');
    // On the walk's other controls ← and → keep the focus in the toolbar and start no look.
    const next = $(ctx, '.mlv-walkbar__step--next');
    next.focus();
    press(ctx, 'ArrowLeft', {}, next);
    assert.deepEqual([viewport(ctx), farState(ctx, 'c-val-sched').keep], [left, 'source']);
    assert.ok(ctx.document.activeElement.closest('.mlv-walkbar__tools'));
  } finally {
    ctx.app.destroy();
  }
});

test('a click on the far line or on the cap does what key o does and keeps the selection; the cap answers the pointer on the line, and the line the pointer on the cap', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const left = viewport(ctx);
    const click = (element) => element.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
    const selected = () => assert.deepEqual([plain(ctx.app.selection), ctx.app.walk.current().id], [{ kind: 'edge', id: 'c-opts-ckpt' }, 'c-opts-ckpt']);

    click(farLine(ctx));
    let state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.target, state.caps], ['target', true, ['source']]);
    assert.equal(live(ctx), 'Far end of this connection: Checkpoint. o goes back to Options.');
    selected();
    click(farLine(ctx));
    assert.deepEqual(viewport(ctx), left);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');

    // The cap lies on the canvas, where a click on the background clears the selection: not on a cap.
    click(caps(ctx)[0]);
    state = farState(ctx, 'c-opts-ckpt');
    assert.deepEqual([state.keep, state.target, state.caps], ['target', true, ['source']]);
    selected();
    // At the far end the cap points back: a click on it is the way back.
    click(caps(ctx)[0]);
    assert.deepEqual(viewport(ctx), left);
    atSource(ctx, 'c-opts-ckpt', 'Checkpoint');
    selected();
    // A press on a cap is not the start of a drag of the diagram.
    const cap = caps(ctx)[0];
    cap.dispatchEvent(new ctx.window.MouseEvent('pointerdown', { bubbles: true, cancelable: true, clientX: 10, clientY: 260 }));
    ctx.canvas.dispatchEvent(new ctx.window.MouseEvent('pointermove', { bubbles: true, cancelable: true, clientX: 60, clientY: 300 }));
    ctx.canvas.dispatchEvent(new ctx.window.MouseEvent('pointerup', { bubbles: true, cancelable: true, clientX: 60, clientY: 300 }));
    assert.deepEqual(viewport(ctx), left);

    // The pointer or the keyboard on the line fills the cap; the pointer on the cap marks the line.
    const hover = (element, type) => element.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: false }));
    hover(farLine(ctx), 'pointerenter');
    assert.equal(caps(ctx)[0].classList.contains('is-cued'), true);
    hover(farLine(ctx), 'pointerleave');
    assert.equal(caps(ctx)[0].classList.contains('is-cued'), false);
    farLine(ctx).focus();
    assert.equal(caps(ctx)[0].classList.contains('is-cued'), true);
    hover(farLine(ctx), 'pointerleave');
    assert.equal(caps(ctx)[0].classList.contains('is-cued'), true, 'the keyboard is still on the line');
    ctx.canvas.focus();
    assert.equal(caps(ctx)[0].classList.contains('is-cued'), false);
    hover(caps(ctx)[0], 'pointerenter');
    assert.equal(farLine(ctx).classList.contains('is-cued'), true);
    hover(caps(ctx)[0], 'pointerleave');
    assert.equal(farLine(ctx).classList.contains('is-cued'), false);
    // The fill is the cap's own colour (here the cap on the canvas).
    caps(ctx)[0].classList.add('is-cued');
    assert.equal(cascadeWinner(CSS, caps(ctx)[0], 'background').value, 'var(--mlv-cap)');
  } finally {
    ctx.app.destroy();
  }
});

test('the second click of a double-click on a cap is swallowed: it is not a click on the background or the card the look put under the pointer', async () => {
  const ctx = await mount();
  try {
    // `detail` is the browser's count of the clicks of one sequence, whatever each lands on.
    const click = (element, detail) => {
      const ev = new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail });
      element.dispatchEvent(ev);
      return ev;
    };
    const atFarEnd = (what) => {
      const state = farState(ctx, 'c-opts-ckpt');
      assert.deepEqual([state.claim, state.keep, state.target, plain(ctx.app.selection)], ['c-opts-ckpt', 'target', true, { kind: 'edge', id: 'c-opts-ckpt' }], what);
      assert.match(state.place, / · far end$/, what);
    };
    walkTo(ctx, 'c-opts-ckpt');
    const posted = ctx.bridge.posted.length;

    // The cap is under the pointer for the first click only; then the background is.
    click(caps(ctx)[0], 1);
    atFarEnd('the first click travelled');
    assert.equal(click(ctx.canvas, 2).defaultPrevented, true);
    atFarEnd('the second click, on the background, cleared nothing');
    const dbl = new ctx.window.MouseEvent('dblclick', { bubbles: true, cancelable: true, detail: 2 });
    ctx.canvas.dispatchEvent(dbl);
    assert.equal(dbl.defaultPrevented, true);

    // Or the far card is: it is not selected, and the walk does not follow to its claim.
    press(ctx, 'o', {}, ctx.canvas);
    click(caps(ctx)[0], 1);
    atFarEnd('the first click travelled again');
    click($(ctx, '.mlv-node[data-node-id="ckpt"]'), 2);
    atFarEnd('the second click, on the far card, selected nothing');
    click($(ctx, '.mlv-node[data-node-id="ckpt"]'), 3);
    atFarEnd('nor a third');
    assert.equal(ctx.bridge.posted.length, posted, 'and nothing was opened');

    // A click of its own afterwards is a click again.
    click(ctx.canvas, 1);
    assert.equal(ctx.app.selection, null);
  } finally {
    ctx.app.destroy();
  }
});

test('the bar\'s line stops answering a cap that is taken away under the pointer, and a cap drawn while the line has the keyboard answers it', async () => {
  const ctx = await mount();
  try {
    const hover = (element, type) => element.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: false }));
    const lineCued = () => $(ctx, '.mlv-walkbar__far').classList.contains('is-cued');
    // The pointer rests on a cap; a step takes that cap away, and no pointerleave is sent for it.
    walkTo(ctx, 'c-val-sched');
    for (const [key, back] of [['j', 'k'], ['k', 'j'], ['Escape', 'r']]) {
      hover(caps(ctx)[0], 'pointerenter');
      assert.equal(lineCued(), true, 'precondition: the line answers the pointer on the cap');
      press(ctx, key, {}, ctx.canvas);
      assert.equal(lineCued(), false, 'after ' + key);
      // Back on the connection, its line is not lit by the cap that went.
      press(ctx, back, {}, ctx.canvas);
      assert.equal(ctx.app.walk.current().id, 'c-val-sched');
      assert.ok(farLine(ctx));
      assert.equal(lineCued(), false, 'back after ' + key);
    }
    // A pointer that leaves a cap the ordinary way still ends the cue.
    hover(caps(ctx)[0], 'pointerenter');
    hover(caps(ctx)[0], 'pointerleave');
    assert.equal(lineCued(), false);

    // The keyboard is on the line; the reader pans to the middle of the connection, where each
    // end is out of view: the second cap is drawn answering as the first does.
    farLine(ctx).focus();
    assert.deepEqual(caps(ctx).map((cap) => cap.classList.contains('is-cued')), [true]);
    press(ctx, 'o', {}, farLine(ctx));
    const far = viewport(ctx);
    press(ctx, 'o', {}, farLine(ctx));
    const near = viewport(ctx);
    ctx.app.view.viewport.set({ x: (near.x + far.x) / 2, y: (near.y + far.y) / 2, zoom: near.zoom });
    assert.equal(ctx.document.activeElement, farLine(ctx));
    assert.deepEqual(caps(ctx).map((cap) => [cap.getAttribute('data-far-end'), cap.classList.contains('is-cued')]), [['source', true], ['target', true]]);
    ctx.canvas.focus();
    assert.deepEqual(caps(ctx).map((cap) => cap.classList.contains('is-cued')), [false, false]);
  } finally {
    ctx.app.destroy();
  }
});

test('a cap on a dashed or dotted line keeps its outline when it answers the pointer or the keyboard: a ring around it, not a fill in the outline\'s own colour; a solid cap fills', async () => {
  // jsdom matches no :hover and no :focus-visible: a class of the same weight stands for each.
  const STATES = CSS.replace(/:hover/g, '.t-hover').replace(/:focus-visible/g, '.t-focus');
  const paint = (mark) => ['background', 'color', 'border-style', 'box-shadow'].map((property) => {
    const winner = cascadeWinner(STATES, mark, property);
    return winner ? winner.value : null;
  });
  // Every way the cap on the canvas and its copy in the bar are made to answer.
  const states = (ctx) => [
    [caps(ctx)[0], 't-hover', caps(ctx)[0], 'the pointer on the cap'],
    [caps(ctx)[0], 'is-cued', caps(ctx)[0], 'the pointer or the keyboard on the bar\'s line'],
    [farLine(ctx), 't-hover', barGlyph(ctx), 'the pointer on the bar\'s line'],
    [farLine(ctx), 't-focus', barGlyph(ctx), 'the keyboard on the bar\'s line'],
    [farLine(ctx), 'is-cued', barGlyph(ctx), 'the pointer on the cap'],
  ];
  // The dashed pair is framed whole on the usual canvas; on one 300 px wide it is far.
  for (const [id, border, canvas] of [['c-optim-ckpt-2', 'dotted', CANVAS], ['c-model-export-2', 'dashed', { w: 300, h: 337 }]]) {
    const ctx = await mount(farDoc(), { bodyClass: 'vscode-reduce-motion', canvas });
    try {
      walkTo(ctx, id);
      assert.equal(caps(ctx).length, 1, id);
      assert.deepEqual(paint(caps(ctx)[0]), ['var(--mlv-bg)', 'var(--mlv-cap)', border, null], id + ', at rest');
      for (const [element, state, mark, what] of states(ctx)) {
        element.classList.add(state);
        const [background, colour, style, ring] = paint(mark);
        assert.deepEqual([background, colour, style], ['var(--mlv-bg)', 'var(--mlv-cap)', border], id + ', ' + what + ': the ' + border + ' outline on its ground');
        assert.match(String(ring), /^0 0 0 2px var\(--mlv-bg\), ?0 0 0 3\.5px var\(--mlv-cap\)$/, id + ', ' + what + ': a ring says the cap answers');
        element.classList.remove(state);
      }
      if (border !== 'dotted') continue;
      // A line drawn solid: its cap fills.
      walkTo(ctx, 'c-val-sched');
      assert.equal(caps(ctx)[0].hasAttribute('data-basis'), false);
      for (const [element, state, mark, what] of states(ctx)) {
        element.classList.add(state);
        assert.deepEqual(paint(mark).slice(0, 3), ['var(--mlv-cap)', 'var(--mlv-bg)', null], what);
        element.classList.remove(state);
      }
    } finally {
      ctx.app.destroy();
    }
  }
});

test('the pointer on a cap is the cap\'s: the line it sits on is not hovered there, and its hover card does not open over the cap', async () => {
  const ctx = await mount();
  try {
    walkTo(ctx, 'c-opts-ckpt');
    const cap = caps(ctx)[0];
    const line = lineOf(ctx, 'c-opts-ckpt');
    // The middle of the cap, in canvas pixels: a point of the line it sits on.
    const at = { x: parseFloat(cap.style.left) + 11, y: parseFloat(cap.style.top) + 7 };
    const move = (target, dx) => target.dispatchEvent(new ctx.window.MouseEvent('pointermove', { bubbles: true, cancelable: true, clientX: at.x + dx, clientY: at.y }));
    // A walk step holds the hover back until the pointer has moved: the second move is the reader's.
    move(ctx.canvas, 2);
    move(ctx.canvas, 0);
    assert.equal(line.classList.contains('is-hover'), true, 'precondition: on the canvas that place is the line\'s');
    move(cap, 1);
    assert.equal(line.classList.contains('is-hover'), false, 'on the cap it is not');
    await new Promise((resolve) => setTimeout(resolve, 450));
    assert.equal($(ctx, '.mlv-tooltip').hidden, true, 'no hover card over the cap');
  } finally {
    ctx.app.destroy();
  }
});

/* ── one bar height for the whole walk ───────────────────────────────── */

/**
 * What decides the bar's height, as far as jsdom can say: the elements of the bar in order, each
 * with whether it is shown, not entering the far line's slot, a button or a hidden element. What
 * is inside the slot comes and goes with the claim; the slot's own box does not depend on it (the
 * rules below).
 */
function barShape(ctx) {
  const slot = $(ctx, '.mlv-walkbar__farslot');
  const out = [];
  const visit = (element, depth) => {
    for (const child of element.children) {
      out.push('  '.repeat(depth) + child.className + (child.hidden ? ' [hidden]' : ''));
      if (!child.hidden && child !== slot && child.tagName !== 'BUTTON') visit(child, depth + 1);
    }
  };
  visit($(ctx, '.mlv-walkbar'), 0);
  return out.join('\n');
}

test('the bar is built the same on every claim of a walk and at both ends of a far connection, at 541, 900 and 1440 px: the line and its words come and go inside a slot of one height', async () => {
  // The bar must be one height on every claim of a walk, so that the canvas, the phase index and
  // the Next button do not move between two claims. jsdom lays nothing out, so this holds what
  // that height follows from: the same elements on every claim, and a slot of one height for the
  // line and its words.
  for (const [width, canvas, layout] of [[541, CANVAS, 'narrow'], [900, { w: 900, h: 318 }, 'wide'], [1440, { w: 1080, h: 767 }, 'wide']]) {
    const ctx = await mount(farDoc(), { width, canvas });
    try {
      walkTo(ctx, 'opts');
      const bar = $(ctx, '.mlv-walkbar');
      const slot = $(ctx, '.mlv-walkbar__farslot');
      assert.deepEqual([bar.getAttribute('data-layout'), bar.getAttribute('data-rows')], [layout, null], width + ' px');
      const first = barShape(ctx);
      const kinds = new Set();
      const look = (what) => {
        const where = width + ' px, claim ' + (ctx.app.walk.position + 1) + ' ' + ctx.app.walk.current().id + ', ' + what;
        assert.equal(barShape(ctx), first, where);
        // In the slot: the line, or the words that say why there is none, or nothing; never two.
        const line = $(ctx, '.mlv-walkbar__far');
        const idle = $(ctx, '.mlv-walkbar__faridle');
        assert.deepEqual(Array.from(slot.children), [idle, line], where);
        assert.equal(line.hidden || idle.hidden, true, where);
        assert.deepEqual([slot.hidden, slot.getAttribute('style'), bar.getAttribute('data-layout'), bar.getAttribute('data-rows')], [false, null, layout, null], where);
        kinds.add(!line.hidden ? (/far end/.test($(ctx, '.mlv-walkbar__postext').textContent) ? 'far end' : 'far') : !idle.hidden ? idle.textContent : ctx.app.walk.current().kind);
      };
      for (let i = 0; i < ctx.app.walk.list.length; i++) {
        if (i) press(ctx, 'j', {}, ctx.canvas);
        look('at the step');
        if (!farLine(ctx)) continue;
        press(ctx, 'o', {}, ctx.canvas);
        look('at the far end');
        press(ctx, 'o', {}, ctx.canvas);
        look('back');
      }
      // Every kind of claim was among them: a far connection from both ends, a near one, a step, a
      // finding and, on the largest canvas, a connection in view by its line (from the open group).
      assert.deepEqual(Array.from(kinds).sort(), ['Both ends in view', ...(width === 1440 ? ['Line in view end to end'] : []), 'far', 'far end', 'issue', 'node'], width + ' px');

      // The rules: the place does not wrap or shrink, the slot takes what it leaves and is 22 px
      // high whatever it holds, and the controls ask for the whole row under them.
      const pos = $(ctx, '.mlv-walkbar__pos');
      assert.deepEqual([ruleOf(pos, 'flex'), ruleOf(pos, 'white-space')], ['none', 'nowrap']);
      assert.deepEqual([ruleOf(slot, 'display'), ruleOf(slot, 'flex'), ruleOf(slot, 'min-width'), ruleOf(slot, 'height')], ['flex', '1 1 0', '0', '22px']);
      walkBackTo(ctx, 'c-val-sched');
      const line = farLine(ctx);
      assert.deepEqual([ruleOf(line, 'height'), ruleOf(line, 'min-width')], ['22px', '0']);
      const idle = $(ctx, '.mlv-walkbar__faridle');
      assert.deepEqual([ruleOf(idle, 'white-space'), ruleOf(idle, 'overflow'), ruleOf(idle, 'min-width')], ['nowrap', 'hidden', '0']);
      assert.equal(ruleOf($(ctx, '.mlv-walkbar__tools'), 'flex'), '1 1 100%');
    } finally {
      ctx.app.destroy();
    }
  }
});

/* ── the caps and the phase index ────────────────────────────────────── */

test('the caps are placed again when the phase index opens, closes or changes form: never left under it', async () => {
  const underIndex = (ctx) => {
    const covered = ctx.app.view.viewport.covered();
    return caps(ctx).filter((cap) => {
      const upright = cap.classList.contains('mlv-farcap--v');
      const box = { x: parseFloat(cap.style.left), y: parseFloat(cap.style.top), w: upright ? 14 : 22, h: upright ? 22 : 14 };
      return box.x < covered.x + covered.w && covered.x < box.x + box.w && box.y < covered.y + covered.h && covered.y < box.y + box.h;
    }).length;
  };
  const click = (ctx, element) => element.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));

  // 541 px: the index is a pill; a click on it opens the list of phases above it.
  let ctx = await mount();
  try {
    walkTo(ctx, 'c-val-sched');
    press(ctx, 'o', {}, ctx.canvas);
    // At the far end the line runs right along y 246 and leaves through the right edge, above the pill.
    assert.deepEqual(capPlaces(ctx), ['source 516px 239px']);
    const pill = plain(ctx.app.view.viewport.covered());
    const view = viewport(ctx);
    click(ctx, $(ctx, '.mlv-phaseindex__pill'));
    const open = plain(ctx.app.view.viewport.covered());
    assert.ok(open.y < 239 && open.h > pill.h, 'precondition: the open list covers the place the cap was');
    assert.deepEqual(viewport(ctx), view, 'precondition: the view did not move');
    // All of that line on the canvas is now behind the list: no cap, and no copy of one in the bar.
    assert.deepEqual(capPlaces(ctx), []);
    assert.equal($(ctx, '.mlv-walkbar__farglyph').hidden, true);
    assert.ok(farLine(ctx), 'the line in the bar stays');
    press(ctx, 'Escape', {}, ctx.canvas);
    assert.deepEqual(plain(ctx.app.view.viewport.covered()), pill, 'Escape closed the list');
    assert.equal(ctx.app.walk.active, true);
    assert.deepEqual(capPlaces(ctx), ['source 516px 239px'], 'and the cap is back');
    assert.equal($(ctx, '.mlv-walkbar__farglyph').hidden, false);

    // The reader pans 200 px left: the line comes in from the left of where the list opens.
    ctx.app.view.viewport.panBy(-200, 0);
    assert.deepEqual(capPlaces(ctx), ['source 516px 239px']);
    click(ctx, $(ctx, '.mlv-phaseindex__pill'));
    // The cap moves to where the line goes behind the list: 6 px left of it.
    assert.deepEqual(capPlaces(ctx), ['source 140px 239px']);
    assert.equal(140 + 22 + 6, open.x - 1);
    assert.equal(underIndex(ctx), 0);
    press(ctx, 'Escape', {}, ctx.canvas);
    assert.deepEqual(capPlaces(ctx), ['source 516px 239px']);
  } finally {
    ctx.app.destroy();
  }

  // 1440 px: the index is a panel of rows; folded, or in a panel under 1000 px, it is the pill.
  ctx = await mount(farDoc(), { width: 1440, canvas: { w: 1080, h: 767 } });
  try {
    walkTo(ctx, 'c-val-sched');
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(capPlaces(ctx), ['source 1056px 441px'], 'through the right edge, above the index');
    const form = () => $(ctx, '.mlv-phaseindex').getAttribute('data-form');
    // Panned 220 px down, the line runs behind the panel of rows: the cap is before it.
    ctx.app.view.viewport.panBy(0, 220);
    const rows = plain(ctx.app.view.viewport.covered());
    assert.deepEqual([form(), capPlaces(ctx)], ['list', ['source 680px 661px']]);
    assert.equal(680 + 22 + 6, rows.x);
    assert.equal(underIndex(ctx), 0);
    // Folded to its pill, the index does not reach the line: the cap is at the edge again.
    click(ctx, $(ctx, '.mlv-phaseindex__fold'));
    assert.ok(ctx.app.view.viewport.covered().y > 661 + 14, 'precondition: the pill is below the line');
    assert.deepEqual([form(), capPlaces(ctx)], ['pill', ['source 1056px 661px']]);
    click(ctx, $(ctx, '.mlv-phaseindex__pill'));
    assert.deepEqual([form(), capPlaces(ctx)], ['list', ['source 680px 661px']], 'unfolded');
    // The panel narrows under 1000 px and widens again: the pill, then the rows.
    ctx.panel(900);
    assert.deepEqual([form(), capPlaces(ctx)], ['pill', ['source 1056px 661px']]);
    ctx.panel(1440);
    assert.deepEqual([form(), capPlaces(ctx)], ['list', ['source 680px 661px']]);
    assert.equal(underIndex(ctx), 0);
  } finally {
    ctx.app.destroy();
  }
});

/* ── the dash of an uncertain line: on its cap, and in sight ─────────── */

/** The documents whose inferred and unresolved connections the rule is held on. */
const RULE_DOCUMENTS = [
  ['the test document d06-refinement (contracts/conformance/documents/workspace/d06-refinement.mlview.json)', () => JSON.parse(readFileSync(join(REPO_ROOT, 'contracts', 'conformance', 'documents', 'workspace', 'd06-refinement.mlview.json'), 'utf8'))],
  ['the skill\'s example (skills/mlview/references/workflow-example.json)', () => JSON.parse(readFileSync(join(REPO_ROOT, 'skills', 'mlview', 'references', 'workflow-example.json'), 'utf8'))],
  ['the 79-claim shape', () => shapedWorkflow(SHAPE_79_CLAIMS)],
  ['the 176-claim shape', () => shapedWorkflow(SHAPE_176_CLAIMS)],
  ['the far-connection document', () => farDoc()],
  // Eight groups of five steps (48 nodes), every second connection inferred: no real
  // document's shape.
  ['the stress fixture', () => rendererRegressionWorkflow(48)],
];
/**
 * The walk's canvas in panels of 541 x 798, 900 x 800 and 1440 x 900 px, as measured by
 * capture.mjs (`canvasBox`).
 */
const RULE_PANELS = [[541, CANVAS], [900, { w: 900, h: 318 }], [1440, { w: 1080, h: 767 }]];

/**
 * How much of the line of connection `id` the reader sees, in px on screen: the part on the
 * canvas, not under the phase index and not behind a card (the connections are drawn under the
 * cards; an open group hides nothing), nor under one of `over` (the caps, which are drawn on the
 * line). `total` is the line's whole length on screen.
 */
function lineInSight(ctx, id, size, over = []) {
  const vp = viewport(ctx);
  const points = ctx.app.view.routes.find((r) => r.ids.includes(id)).points.map((p) => ({ x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y }));
  const hides = [...over, ...cardBoxes(ctx)];
  const covered = ctx.app.view.viewport.covered();
  if (covered) hides.push(covered);
  const inside = (p, r) => p.x > r.x && p.x < r.x + r.w && p.y > r.y && p.y < r.y + r.h;
  let seen = 0;
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const n = Math.max(1, Math.ceil(length));
    for (let k = 0; k < n; k++) {
      const p = { x: a.x + ((b.x - a.x) * (k + 0.5)) / n, y: a.y + ((b.y - a.y) * (k + 0.5)) / n };
      total += length / n;
      if (p.x >= 0 && p.x <= size.w && p.y >= 0 && p.y <= size.h && !hides.some((r) => inside(p, r))) seen += length / n;
    }
  }
  return { seen, total };
}

/**
 * The `end` card of connection `id` (its source, or its target) is an open group that fits the
 * canvas at reading size, and so is kept whole like a card, and the canvas has no room for that
 * group together with the `px` screen pixels of the connection's line next to it and the 32 px the
 * walk keeps around what it reveals. (A group larger than the canvas is another case: the walk
 * shows the place its line leaves it.)
 */
function groupLeavesNoRoom(ctx, id, px, size, end = 'source') {
  const zoom = viewport(ctx).zoom;
  const edge = ctx.app.index.edgeById.get(id);
  const card = ctx.app.view.frame.boxes.get(ctx.app.index.visibleRepresentative(edge[end], ctx.app.view.collapsed));
  if (!ctx.app.index.isGroup(card.id) || ctx.app.view.collapsed.has(card.id)) return false;
  if (card.w * 0.9 > size.w || card.h * 0.9 > size.h) return false;
  const route = ctx.app.view.routes.find((r) => r.ids.includes(id)).points;
  const points = end === 'source' ? route : route.slice().reverse();
  let x0 = card.x;
  let y0 = card.y;
  let x1 = card.x + card.w;
  let y1 = card.y + card.h;
  let left = px / zoom;
  for (let i = 1; i < points.length && left > 0; i++) {
    const a = points[i - 1];
    const b = points[i];
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    const t = length > left ? left / length : 1;
    const p = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
    x0 = Math.min(x0, p.x);
    y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x);
    y1 = Math.max(y1, p.y);
    left -= length;
  }
  return (x1 - x0) * zoom > size.w - 32 || (y1 - y0) * zoom > size.h - 32;
}

/**
 * Walk every claim of `filter` and call `visit` on each connection whose line is drawn dashed or
 * dotted: it is inferred or unresolved, or shares its line with a connection that is.
 */
function eachUncertain(ctx, filter, visit) {
  press(ctx, 'r', {}, ctx.canvas);
  if (ctx.app.walk.filter !== filter) ctx.app.walk.setFilter(filter);
  for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
  for (let i = 0; i < ctx.app.walk.list.length; i++) {
    if (i) press(ctx, 'j', {}, ctx.canvas);
    const claim = ctx.app.walk.current();
    if (claim.kind !== 'edge') continue;
    const basis = lineOf(ctx, claim.id).getAttribute('data-basis');
    if (basis === 'inferred' || basis === 'unresolved') visit(claim.id, basis);
  }
}

test('every cap on a dashed or dotted line is dashed or dotted like it, on the canvas and in the bar, at the source and at the far end; a line the walk frames whole has no cap', async () => {
  const count = { connections: 0, far: 0, caps: 0, dashed: 0, dotted: 0, whole: 0 };
  for (const [name, load] of RULE_DOCUMENTS) {
    for (const [width, canvas] of RULE_PANELS) {
      const ctx = await mount(load(), { width, canvas });
      try {
        eachUncertain(ctx, name === 'the far-connection document' ? 'all' : 'notObserved', (id, basis) => {
          const where = name + ', ' + width + ' px, ' + id;
          const border = basis === 'inferred' ? 'dashed' : 'dotted';
          // The line itself is drawn so (edge.css).
          assert.match(ruleOf(lineOf(ctx, id).querySelector('.mlv-edge__path'), 'stroke-dasharray'), basis === 'inferred' ? /^calc\(6px / : /^calc\(1\.5px /, where);
          count.connections++;
          const check = (at) => {
            for (const cap of caps(ctx)) {
              assert.equal(cap.getAttribute('data-basis'), basis, where + ', ' + at + ': the cap has another basis than its line');
              assert.equal(ruleOf(cap, 'border-style'), border, where + ', ' + at);
              count.caps++;
              count[border]++;
            }
            const glyph = barGlyph(ctx);
            if (farLine(ctx) && !glyph.hidden) {
              assert.equal(glyph.getAttribute('data-basis'), basis, where + ', ' + at + ': the copy in the bar');
              assert.equal(ruleOf(glyph, 'border-style'), border, where + ', ' + at);
            }
          };
          if (!farLine(ctx)) {
            // Both cards on the canvas: nothing stands at the end of this line but its arrowhead.
            const ends = ctx.app.view.far.ends(id);
            assert.deepEqual([ends.source.inView, ends.target.inView, caps(ctx).length], [true, true, 0], where);
            count.whole++;
            return;
          }
          count.far++;
          check('at the source');
          press(ctx, 'o', {}, ctx.canvas);
          check('at the far end');
          press(ctx, 'o', {}, ctx.canvas);
        });
      } finally {
        ctx.app.destroy();
      }
    }
  }
  // Not vacuous: caps of both kinds were drawn, and lines of both fates were met.
  assert.ok(count.connections >= 140 && count.far >= 100 && count.whole >= 20, JSON.stringify(count));
  assert.ok(count.dashed >= 150 && count.dotted >= 10, JSON.stringify(count));
});

/**
 * What the rule asks the walk to keep in sight of a far connection's line beside its card, in px
 * on screen (FAR_LEAD_PX): eight dashes of a dashed line, sixteen dots of a dotted one.
 */
const MIN_IN_SIGHT = 80;
/** A cap is drawn on the line and is 22 px long: what it leaves of those 80 px. */
const MIN_CLEAR_OF_CAP = MIN_IN_SIGHT - 22;

/**
 * Walk the dashed and dotted lines of RULE_DOCUMENTS on each canvas of `panels`, twice: in the
 * walk key r starts (Not observed) and in the walk over every claim, which arrives from another
 * picture. A connection framed with both its cards is checked here. Of a far one, a row for each
 * end: `seen`, how much of its line is in sight with the card the view keeps (at the source as
 * the step leaves it, at the far end after key o), `clear`, how much of that is not under the
 * cap, and `noRoom`, whether that card is an open group that leaves no room for 80 px of line
 * (`groupLeavesNoRoom`). The card itself is looked at by its own box, not by what the view says
 * of it: `whole` on the canvas and clear of the phase index; `larger` than the canvas at reading
 * size, so that the walk shows the place its line meets it; `noClear`, too tall to stand above
 * the phase index and too wide to stand beside it (whether it fits the canvas is `larger`). The
 * tests say which cards may be less than whole. The layout measures no text, so the boxes and the
 * lines are the browser's; the canvas and the phase index are jsdom stand-ins.
 */
async function uncertainRows(panels) {
  const rows = [];
  for (const [name, load] of RULE_DOCUMENTS) {
    for (const [width, canvas] of panels) {
      for (const filter of ['notObserved', 'all']) {
        const ctx = await mount(load(), { width, canvas });
        try {
          eachUncertain(ctx, filter, (id) => {
            const where = name + ', ' + width + ' x ' + canvas.h + ' px, ' + filter + ', ' + id;
            const ends = ctx.app.view.far.ends(id);
            if (ends.source.inView && ends.target.inView) {
              // Framed with both its cards: no less of the line than a far one shows, or all of a short one.
              const { seen, total } = lineInSight(ctx, id, canvas);
              assert.ok(seen >= Math.min(MIN_IN_SIGHT, total - 1), where + ': ' + Math.round(seen) + ' of ' + Math.round(total) + ' px in sight with both cards in view');
              assert.ok(viewport(ctx).zoom >= 0.45, where + ': framed at ' + viewport(ctx).zoom);
              return;
            }
            const row = (end) => {
              const card = ctx.app.view.frame.boxes.get(ctx.app.view.far.ends(id)[end].drawnId);
              const box = drawn(ctx, card);
              const covered = ctx.app.view.viewport.covered();
              return {
                name, where: where + ', at the ' + (end === 'source' ? 'source' : 'far end'), end,
                seen: lineInSight(ctx, id, canvas).seen, clear: lineInSight(ctx, id, canvas, capBoxes(ctx)).seen, noRoom: groupLeavesNoRoom(ctx, id, MIN_IN_SIGHT, canvas, end),
                whole: ctx.app.view.far.inView(card), larger: card.w * 0.9 > canvas.w || card.h * 0.9 > canvas.h, noClear: !!covered && box.h > covered.y && box.w > covered.x,
              };
            };
            // The view holds the source card: the stretch in sight is the start of the line.
            assert.deepEqual([ends.keep, ends.source.inView], ['source', true], where);
            rows.push(row('source'));
            // The connection's own basis is in the bar in words, before the title, and in the line's name.
            const basis = ctx.app.index.edgeById.get(id).basis;
            const tag = farLine(ctx).querySelector('.mlv-walkbar__fartag');
            if (basis === 'observed') assert.equal(tag, null, where + ': an observed connection on a shared line');
            else {
              assert.equal(tag.textContent, basis === 'inferred' ? 'inferred' : '? unresolved', where);
              assert.equal(tag.nextElementSibling, $(ctx, '.mlv-walkbar__farbody'), where);
              assert.match(farLine(ctx).getAttribute('aria-label'), basis === 'inferred' ? /^inferred connection\. / : /^\? unresolved connection\. /, where);
            }
            // The far end: the view holds its card, and the stretch in sight is the end of the line.
            press(ctx, 'o', {}, ctx.canvas);
            const there = ctx.app.view.far.ends(id);
            assert.deepEqual([there.keep, there.target.inView], ['target', true], where + ', at the far end');
            rows.push(row('target'));
            press(ctx, 'o', {}, ctx.canvas);
          });
        } finally {
          ctx.app.destroy();
        }
      }
    }
  }
  return rows;
}

test('the far end of a dashed line that ends at an open group with no room beside it: the view shows the place the line meets the group, and counts as at the far end', async () => {
  // The stress fixture at 541 x 337 px: the group this inferred connection ends at fits the canvas
  // at reading size, but not together with 80 px of the dashed line beside it (the precondition).
  // The line meets the group's foot, far from its header: the canvas has no room for both, so
  // the header is not shown (where it has, the header's start comes with that place, as at a
  // source that is a group larger than the canvas).
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 541, canvas: CANVAS });
  try {
    // Key r starts the Not observed walk, which holds this connection.
    press(ctx, 'r', {}, ctx.canvas);
    for (let i = 0; i < 100 && ctx.app.walk.current().id !== 'edge-37'; i++) press(ctx, 'j', {}, ctx.canvas);
    assert.equal(ctx.app.walk.current().id, 'edge-37', 'precondition: the walk is on the connection');
    const edge = ctx.app.index.edgeById.get('edge-37');
    const group = ctx.app.view.frame.boxes.get(ctx.app.index.visibleRepresentative(edge.target, ctx.app.view.collapsed));
    assert.equal(ctx.app.index.isGroup(group.id) && !ctx.app.view.collapsed.has(group.id), true, 'precondition: the far card is an open group');
    assert.equal(groupLeavesNoRoom(ctx, 'edge-37', MIN_IN_SIGHT, CANVAS, 'target'), true, 'precondition: it fits the canvas and leaves no room for 80 px of line');
    const left = viewport(ctx);
    press(ctx, 'o', {}, ctx.canvas);
    // The end of the line, and 80 px of it or more.
    const end = ctx.app.view.routes.find((r) => r.ids.includes('edge-37')).points.slice(-1)[0];
    assert.equal(whole(drawn(ctx, { x: end.x, y: end.y, w: 0, h: 0 }), CANVAS), true, 'the place the line meets the group is on the canvas');
    const seen = lineInSight(ctx, 'edge-37', CANVAS, capBoxes(ctx)).seen;
    assert.ok(seen >= MIN_IN_SIGHT, Math.round(seen) + ' px of the line in sight and clear of the cap');
    // The group is not whole on the canvas, and the view is at the far end all the same.
    assert.equal(ctx.app.view.far.inView(group), false);
    const state = farState(ctx, 'edge-37');
    assert.deepEqual([state.keep, state.target, state.caps], ['target', true, ['source']]);
    assert.match(state.line, /^Back to /);
    assert.match(state.place, / · far end$/);
    // No cap on the group's header: the one cap is where the line leaves the canvas.
    const header = drawn(ctx, { x: group.x, y: group.y, w: group.w, h: group.headerH });
    const cap = capBoxes(ctx)[0];
    assert.equal(cap.x < header.x + header.w && header.x < cap.x + cap.w && cap.y < header.y + header.h && header.y < cap.y + cap.h, false, 'the cap is not on the header');
    // A canvas that gets shorter and comes back keeps that place: the line is not given up for
    // the whole group.
    const there = viewport(ctx);
    ctx.resize(541, 300);
    ctx.resize(541, 337);
    assert.deepEqual(viewport(ctx), there);
    assert.match(farState(ctx, 'edge-37').place, / · far end$/);
    // And back to the picture left.
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(viewport(ctx), left);
  } finally {
    ctx.app.destroy();
  }
});

const brief = (rows) => rows.map((row) => row.where + ': ' + Math.round(row.seen) + ' px in sight, ' + Math.round(row.clear) + ' px clear of the cap').join('\n');
const leastOf = (rows, key) => rows.reduce((min, row) => Math.min(min, row[key]), Infinity);

/**
 * Hold `rows` of one end to the rule: 80 px of line in sight and 58 px of it clear of the cap,
 * but for `known`, rows this canvas is known to show less of. Returns the rows held.
 */
function holdRule(rows, known = () => false) {
  const room = rows.filter((row) => !known(row));
  for (const row of room) {
    assert.ok(row.seen >= MIN_IN_SIGHT, row.where + ': only ' + row.seen.toFixed(1) + ' px of its line in sight');
    assert.ok(row.clear >= MIN_CLEAR_OF_CAP, row.where + ': only ' + row.clear.toFixed(1) + ' px of its line in sight and clear of the cap');
  }
  return room;
}

test('the cap never stands in for a dashed or dotted line: where such a connection is far the walk shows 80 px or more of its line in sight, at the source and at the far end, and the bar says inferred or unresolved in words', async () => {
  // The rule, on canvases of 541 x 337, 900 x 318 and 1080 x 767 px: `MIN_IN_SIGHT` px of the line
  // in sight and `MIN_CLEAR_OF_CAP` px of it clear of the cap, at the source and at the far end.
  //
  // One case shows less, and is counted here so that it cannot spread unnoticed: a SOURCE that is
  // an open group which fits the canvas, and so is kept whole like a card, but leaves no room for
  // 80 px of line beside it. The stress fixture has such groups on the canvases 337 and 318 px
  // high, each the source of two inferred connections. There the word "inferred"
  // in the bar, and the dashed cap where one is drawn, are what says the connection is uncertain.
  // No other document here has the case. At the far end such a group is shown at the place its
  // line meets it, so the far end has no exception.
  const rows = await uncertainRows(RULE_PANELS);
  const source = rows.filter((row) => row.end === 'source');
  const target = rows.filter((row) => row.end === 'target');
  // Far connections of each document, so that the stress fixture's cannot stand in for the others'.
  const far = (name) => source.filter((row) => row.name === name).length;
  const perDocument = { shape79: far('the 79-claim shape'), shape176: far('the 176-claim shape'), own: far('the far-connection document'), stress: far('the stress fixture') };
  assert.ok(perDocument.shape79 >= 4 && perDocument.shape176 >= 30 && perDocument.own >= 3 && perDocument.stress >= 100, JSON.stringify(perDocument));
  const atSource = holdRule(source, (row) => row.noRoom);
  const atFarEnd = holdRule(target);
  assert.equal(atFarEnd.length, target.length);
  assert.ok(leastOf(atSource, 'seen') >= MIN_IN_SIGHT && leastOf(atFarEnd, 'seen') >= MIN_IN_SIGHT, 'the least in sight is ' + leastOf(atSource, 'seen').toFixed(1) + ' px at the source and ' + leastOf(atFarEnd, 'seen').toFixed(1) + ' px at the far end');
  // The case above: at most 16 far steps in all, and only on the stress fixture at 541 x 337 and
  // 900 x 318 px.
  const noRoom = source.filter((row) => row.noRoom);
  assert.ok(noRoom.length <= 16, brief(noRoom));
  assert.ok(noRoom.every((row) => /^the stress fixture, (541 x 337|900 x 318) px, /.test(row.where)), brief(noRoom));
  // The card the view holds, by its own box. Every source card is whole on the canvas and clear of
  // the phase index, but for one open group larger than any of the canvases (c13 of the 176-claim
  // shape), of which the walk shows the place its line leaves it.
  const cutSource = source.filter((row) => !row.whole);
  assert.ok(cutSource.length <= 6, brief(cutSource));
  assert.ok(cutSource.every((row) => row.larger && /^the 176-claim shape, .+, c13, at the source$/.test(row.where)), brief(cutSource));
  // So is every far card after key o, but for the one group of the stress fixture that leaves no
  // room for the line it ends (edge-37, on the two short canvases, in each walk): the walk shows
  // the place the line meets it.
  const cutTarget = target.filter((row) => !row.whole);
  assert.ok(cutTarget.length <= 4, brief(cutTarget));
  assert.ok(cutTarget.every((row) => row.noRoom && !row.larger && /^the stress fixture, (541 x 337|900 x 318) px, (notObserved|all), edge-37, at the far end$/.test(row.where)), brief(cutTarget));
});

test('on the canvas a 541 px panel leaves under a changed-file notice or a taller bar, 311 and 302 px high, a far dashed or dotted line still has 80 px in sight at either end, but at a source group that fits the canvas with no room beside it, and for one line that reaches its far card behind a row of cards', async () => {
  // 311 px: the canvas a 541 px panel leaves under a bar that is a row taller; 302 px: under the
  // notice that a cited file changed. At 302 px one connection of the 176-claim shape (c90) shows
  // less than 80 px at its far end: its line comes to the far card behind a row of cards close
  // together, and the canvas has no room for the cards it would take to show 80 px of it between
  // them.
  //
  // The source group with no room beside it shows less here as well, and is counted so that it
  // cannot spread unnoticed. In the stress fixture (helpers.mjs) a group that is the source of an
  // inferred connection is the source of two, with one target. At most 20 far steps (two canvases,
  // two walks) show less than 80 px of the dashed line at such a source with no room beside it; the
  // other sources are held to the rule.
  const rows = await uncertainRows([[541, { w: 541, h: 311 }], [541, { w: 541, h: 302 }]]);
  const source = rows.filter((row) => row.end === 'source');
  const target = rows.filter((row) => row.end === 'target');
  const noRoomShort = (row) => row.noRoom && row.seen < MIN_IN_SIGHT;
  const atSource = holdRule(source, noRoomShort);
  const behindCards = (row) => /^the 176-claim shape, 541 x 302 px, (notObserved|all), c90, at the far end$/.test(row.where);
  const atFarEnd = holdRule(target, behindCards);
  assert.ok(atSource.length >= 140 && atFarEnd.length >= 140, atSource.length + ' and ' + atFarEnd.length + ' far connections with room');
  // That line has 34 px in sight or more.
  for (const row of rows.filter(behindCards)) assert.ok(row.seen >= 34, brief([row]));
  // Those 20 steps are held as well: no more of them, nowhere else, and none with under 1.9 px.
  const short = source.filter(noRoomShort);
  assert.ok(short.length <= 20, brief(short));
  assert.ok(short.every((row) => /^the stress fixture, 541 x (311|302) px, /.test(row.where) && row.seen >= 1.9), brief(short));

  // The card the view holds, by its own box. Those groups fit these canvases, but they are
  // too tall to stand above the phase index (a pill 360 px wide here, 12 px above the canvas's
  // foot) and too wide to stand beside it. Such a group is less than whole as a source on at most
  // 28 far steps and as a far card on at most 18, edge-37's far end among them: the walk shows it
  // with its foot under the index or, at that far end, which leaves no room for its line, the
  // place the line meets the group. Every other card is whole and clear of the index, but for the
  // source group larger than the canvas (c13 of the 176-claim shape).
  const underIndex = (row) => row.noClear && !row.larger && /^the stress fixture, 541 x (311|302) px, /.test(row.where);
  const cutSource = source.filter((row) => !row.whole && !row.larger);
  assert.ok(cutSource.length <= 28 && cutSource.every(underIndex), brief(cutSource));
  const largerSource = source.filter((row) => row.larger);
  assert.ok(largerSource.length <= 4 && largerSource.every((row) => /^the 176-claim shape, .+, c13, at the source$/.test(row.where)), brief(largerSource));
  const cutTarget = target.filter((row) => !row.whole);
  assert.ok(cutTarget.length <= 18 && cutTarget.every(underIndex), brief(cutTarget));
});

/* ── every connection of a walk ──────────────────────────────────────── */

test('on every connection of a walk over every claim, at three canvas sizes: a far step keeps its source card whole, key o twice puts back the picture it left, and no cap lies over a card, under the phase index or outside the canvas', async () => {
  const documents = [['the far-connection document', () => farDoc()], ['the 79-claim shape', () => shapedWorkflow(SHAPE_79_CLAIMS)], ['the 176-claim shape', () => shapedWorkflow(SHAPE_176_CLAIMS)], ['the stress fixture', () => rendererRegressionWorkflow(48)]];
  // More than half a pixel in both directions: a cap may touch a card's border.
  const over = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.5 && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0.5;
  const count = { connections: 0, far: 0, caps: 0 };
  const faults = { silent: [], sourceCut: [], notBack: [], overCard: [], underIndex: [], outside: [] };
  // Sources larger than the canvas at reading size: the walk shows the place the line leaves them.
  const larger = [];
  for (const [name, load] of documents) {
    for (const [width, canvas] of RULE_PANELS) {
      const ctx = await mount(load(), { width, canvas });
      try {
        const checkCaps = (where) => {
          const covered = ctx.app.view.viewport.covered();
          const cards = cardBoxes(ctx);
          for (const box of capBoxes(ctx)) {
            count.caps++;
            if (box.x < 0 || box.y < 0 || box.x + box.w > canvas.w || box.y + box.h > canvas.h) faults.outside.push(where);
            if (covered && over(box, covered)) faults.underIndex.push(where);
            if (cards.some((card) => over(box, card))) faults.overCard.push(where);
          }
        };
        press(ctx, 'r', {}, ctx.canvas);
        if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
        for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
        for (let i = 0; i < ctx.app.walk.list.length; i++) {
          if (i) press(ctx, 'j', {}, ctx.canvas);
          const claim = ctx.app.walk.current();
          if (claim.kind !== 'edge') continue;
          count.connections++;
          const where = name + ', ' + width + ' px, ' + claim.id;
          const ends = ctx.app.view.far.ends(claim.id);
          if (!farLine(ctx)) {
            // Nothing in the bar: both ends are in view.
            if (!(ends.source.inView && ends.target.inView)) faults.silent.push(where);
            continue;
          }
          count.far++;
          // The source card by its own box: whole on the canvas and clear of the phase index.
          const source = ctx.app.view.frame.boxes.get(ends.source.drawnId);
          const tooLarge = source.w * 0.9 > canvas.w || source.h * 0.9 > canvas.h;
          if (tooLarge) larger.push(where);
          if (!(ends.keep === 'source' && (tooLarge ? ends.source.inView : ctx.app.view.far.inView(source)))) faults.sourceCut.push(where);
          checkCaps(where + ' at the source');
          const left = viewport(ctx);
          press(ctx, 'o', {}, ctx.canvas);
          checkCaps(where + ' at the far end');
          press(ctx, 'o', {}, ctx.canvas);
          if (JSON.stringify(viewport(ctx)) !== JSON.stringify(left)) faults.notBack.push(where);
        }
      } finally {
        ctx.app.destroy();
      }
    }
  }
  // Not vacuous: hundreds of far connections, and about two caps for each (one at each end).
  assert.ok(count.connections >= 600 && count.far >= 400 && count.caps >= 800, JSON.stringify(count));
  for (const [what, list] of Object.entries(faults)) assert.deepEqual(list, [], what + ' (' + list.length + ')');
  // Three open groups larger than the canvas at reading size, the sources of these connections.
  assert.deepEqual(larger, [
    'the far-connection document, 541 px, c-loop-ckpt', 'the far-connection document, 900 px, c-loop-ckpt',
    'the 176-claim shape, 541 px, c13', 'the 176-claim shape, 541 px, c88', 'the 176-claim shape, 900 px, c13', 'the 176-claim shape, 900 px, c88', 'the 176-claim shape, 1440 px, c13',
  ]);
});

/* ── key o after a pan; the stylesheet rules of the line and the caps ── */

/**
 * The picture the least pan gives from the one on screen: the rectangle around the two cards of
 * connection `id` back on a canvas of `size`, 16 px inside the edge it was moved over (less on a
 * canvas barely larger than the rectangle), as a walk step brings a connection into view.
 */
function leastPanBack(ctx, id, size) {
  const edge = ctx.app.index.edgeById.get(id);
  const vp = viewport(ctx);
  const a = drawn(ctx, ctx.app.view.frame.boxes.get(edge.source));
  const b = drawn(ctx, ctx.app.view.frame.boxes.get(edge.target));
  const shift = (start, end, extent) => {
    const pad = Math.max(0, Math.min(16, (extent - (end - start)) / 2));
    return start < 0 ? pad - start : end > extent ? extent - pad - end : 0;
  };
  return {
    x: vp.x + shift(Math.min(a.x, b.x), Math.max(a.x + a.w, b.x + b.w), size.w),
    y: vp.y + shift(Math.min(a.y, b.y), Math.max(a.y + a.h, b.y + b.h), size.h),
    zoom: vp.zoom,
  };
}
/** Two pictures are one: the same zoom, and a pan apart by less than a millionth of a pixel. */
const samePicture = (a, b) => a.zoom === b.zoom && Math.abs(a.x - b.x) < 1e-6 && Math.abs(a.y - b.y) < 1e-6;

test('after a pan of 20 or 200 px on any connection the step showed with both cards, key o shows both cards again at the same zoom, and gives back the step\'s own picture where that is the least pan that shows the two with 16 px to spare: every such connection of the far document, of the test document d06-refinement, of the skill\'s example and of the generated ones, at three canvas sizes', async () => {
  const pans = [[20, 0], [-20, 0], [0, 20], [0, -20], [200, 0], [-200, 0], [0, 200], [0, -200]];
  const faults = [];
  let pressed = 0;
  let stepsPicture = 0;
  for (const [name, load] of RULE_DOCUMENTS) {
    for (const [width, canvas] of RULE_PANELS) {
      const ctx = await mount(load(), { width, canvas });
      try {
        press(ctx, 'r', {}, ctx.canvas);
        if (ctx.app.walk.filter !== 'all') ctx.app.walk.setFilter('all');
        for (let i = 0; i < 400 && ctx.app.walk.position > 0; i++) press(ctx, 'k', {}, ctx.canvas);
        for (let i = 0; i < ctx.app.walk.list.length; i++) {
          if (i) press(ctx, 'j', {}, ctx.canvas);
          const claim = ctx.app.walk.current();
          if (claim.kind !== 'edge' || farLine(ctx) || !bothWhole(ctx, claim.id)) continue;
          const step = viewport(ctx);
          for (const [dx, dy] of pans) {
            ctx.app.view.viewport.set(step);
            ctx.app.view.viewport.panBy(dx, dy);
            if (!farLine(ctx)) continue;
            // Where the pan moved the two cards over an edge the step had put them 16 px from, the
            // least pan back is the step's own picture.
            const back = samePicture(leastPanBack(ctx, claim.id, canvas), step);
            press(ctx, 'o', {}, ctx.canvas);
            pressed++;
            const state = farState(ctx, claim.id);
            if (!(bothWhole(ctx, claim.id) && state.line === null && state.keep === null && !state.place.includes('far end') && viewport(ctx).zoom === step.zoom)) {
              faults.push(name + ' ' + width + ' ' + claim.id + ' after a pan of ' + dx + ',' + dy + ': place "' + state.place + '", line ' + JSON.stringify(state.line) + ', zoom ' + viewport(ctx).zoom);
            }
            if (back) {
              stepsPicture++;
              if (!samePicture(viewport(ctx), step)) faults.push(name + ' ' + width + ' ' + claim.id + ' after a pan of ' + dx + ',' + dy + ': not the step\'s picture, ' + JSON.stringify(viewport(ctx)) + ' for ' + JSON.stringify(step));
            }
          }
          ctx.app.view.viewport.set(step);
        }
      } finally {
        ctx.app.destroy();
      }
    }
  }
  assert.deepEqual(faults, []);
  assert.ok(pressed >= 300 && stepsPicture >= 300, 'the sweep pressed o ' + pressed + ' times, ' + stepsPicture + ' of them where the least pan back is the step\'s picture');
});

test("the stylesheet: a hidden far line and a hidden copy of the cap are not displayed, the caps' layer lets the pointer through to the diagram and a cap takes it, an upright cap is 14 x 22 px, and the bar's row wraps", async () => {
  let ctx = await mount();
  try {
    walkTo(ctx, 'opts');
    const line = $(ctx, '.mlv-walkbar__far');
    // On a step the line is hidden. It is a flex box: without its own rule for the hidden attribute
    // it would stay on show with the words of the last connection.
    assert.equal(line.hidden, true, 'precondition: no far line on a step');
    assert.equal(ruleOf(line, 'display'), 'none');
    // The place and the line's slot share a row, and the controls wrap onto the row under it.
    assert.equal(ruleOf($(ctx, '.mlv-walkbar__row'), 'flex-wrap'), 'wrap');
    // The caps' layer lies over the whole canvas, in the walk and out of it: it takes no pointer
    // event, or no click, drag or hover would reach the diagram. A cap takes its own.
    const layer = $(ctx, '.mlv-farcaps');
    assert.deepEqual([ruleOf(layer, 'position'), ruleOf(layer, 'inset'), ruleOf(layer, 'pointer-events')], ['absolute', '0', 'none']);
    walkTo(ctx, 'c-opts-ckpt');
    assert.equal(ruleOf(line, 'display'), 'flex');
    assert.equal(ruleOf(caps(ctx)[0], 'pointer-events'), 'auto');
    // A cap lies along its line: 22 x 14 px on a horizontal stretch, upright on a vertical one.
    const size = (cap) => [cap.classList.contains('mlv-farcap--v'), ruleOf(cap, 'width'), ruleOf(cap, 'height')];
    assert.deepEqual(size(caps(ctx)[0]), [false, '22px', '14px']);
    assert.notEqual(ruleOf(barGlyph(ctx), 'display'), 'none', 'the copy of the cap is in the bar while a cap is on the canvas');
    press(ctx, 'o', {}, ctx.canvas);
    assert.deepEqual(size(caps(ctx)[0]), [true, '14px', '22px']);
  } finally {
    ctx.app.destroy();
  }

  // 270 x 74 px: the line of this connection has no room for a cap, so the bar has no copy of one.
  ctx = await mount(farDoc(), { canvas: { w: 270, h: 74 }, width: 270 });
  try {
    walkTo(ctx, 'c-opts-ckpt');
    assert.ok(farLine(ctx), 'precondition: the far line is on show');
    assert.deepEqual([caps(ctx).length, barGlyph(ctx).hidden], [0, true], 'precondition: no cap, so no copy');
    assert.equal(ruleOf(barGlyph(ctx), 'display'), 'none');
  } finally {
    ctx.app.destroy();
  }
});
