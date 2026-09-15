/**
 * Where the two features MEET (CONTRACTS 11.14, FEATURES section 4).
 *
 * Four rules, and every one of them is a lie the product would otherwise tell:
 *
 *  C1 a scope change clears every flow element and every `--mlv-flow-*` property;
 *  C2 a lineage stream requires BOTH endpoints to be `core` — a charge animating
 *     into a boundary stub would claim a value goes somewhere the picture does
 *     not show;
 *  C3 a DIRECT hover, focus or selection still pulses any drawn edge, boundary
 *     or not: the user pointed at that edge, not at a lineage;
 *  C4 `e` / `Shift+E` iterate only routes present in the CURRENT projection.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const HOVER_OPEN_MS = 400;

const TRAIN = 'n:5500cc66dd77';
const BATCH_LOOP = 'n:9c8d7e6f5a4b';
/** train.train -> batch_loop: both `core` under unit:train.train. */
const CORE_EDGE = 'e:bd4e7f9a5b68';
/** train.train -> build_loaders: crosses out to a boundary stub. */
const CROSSING_EDGE = 'e:8a1b4c6d2e35';

async function app() {
  const ctx = await loadBundle();
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState() {},
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, sample, bridge);
  return { ...ctx, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const enter = (ctx, el) => el.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const key = (ctx, el, k, opts = {}) =>
  el.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));
const edgeEl = (ctx, id) => ctx.document.querySelector('[data-edge-id="' + id + '"]');
const hoverTarget = (ctx, id) => {
  const el = ctx.document.querySelector('[data-node-id="' + id + '"]');
  return el.querySelector('.mlv-group__header') || el;
};

test('C3: an edge INSIDE a scope pulses on a direct hover', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  const g = edgeEl(ctx, CORE_EDGE);
  assert.ok(g, 'the edge survived the projection and the relayout');
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_OPEN_MS + 100);
  assert.ok(g.classList.contains('is-flowing--pulse'));
  assert.equal(g.querySelectorAll('.mlv-edge__flow').length, 1, 'the charge renders after a re-projection + relayout');
  assert.equal(g.querySelectorAll('.mlv-edge__port').length, 2);
});

test('C3: a BOUNDARY-touching edge still pulses when the user points at it', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  const g = edgeEl(ctx, CROSSING_EDGE);
  const target = ctx.document.querySelector('[data-node-id="n:1100aa22bb33"]');
  assert.equal(target.getAttribute('data-view-role'), 'boundary', 'this edge really does cross the boundary');
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_OPEN_MS + 100);
  assert.ok(g.classList.contains('is-flowing--pulse'), 'that edge is fully drawn and fully real');
  assert.equal(g.querySelectorAll('.mlv-edge__flow').length, 1);
});

test('C2: a lineage stream stops at the scope boundary but still lights it', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 120);

  const core = edgeEl(ctx, CORE_EDGE);
  assert.ok(core.classList.contains('is-lit'));
  assert.ok(core.classList.contains('is-flowing'), 'core -> core streams');
  assert.equal(core.querySelectorAll('.mlv-edge__flow').length, 1);

  const crossing = edgeEl(ctx, CROSSING_EDGE);
  assert.ok(crossing.classList.contains('is-lit'), 'a boundary-touching edge is real, and it is drawn');
  assert.equal(crossing.classList.contains('is-flowing'), false, 'but a charge into a stub would be a lie');
  assert.equal(crossing.querySelectorAll('.mlv-edge__flow').length, 0);

  // Every streaming edge in a projection has two core endpoints, by construction.
  for (const g of ctx.document.querySelectorAll('.mlv-edge.is-flowing')) {
    const ids = g.getAttribute('data-edge-ids').split(' ');
    assert.ok(ids.length >= 1);
    assert.ok(g.classList.contains('is-lit'), 'and it is lit');
  }
});

test('C2: with NO projection, every non-config lit edge may stream', async () => {
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 120);
  const crossing = edgeEl(ctx, CROSSING_EDGE);
  assert.ok(crossing.classList.contains('is-flowing'), 'the same edge streams when nothing is scoped');
});

test('C1: a scope change clears every flow element and every --mlv-flow-* property', async () => {
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 120);
  assert.ok(ctx.document.querySelectorAll('.mlv-edge__flow').length > 0, 'something is flowing first');

  ctx.app.setScope('unit:train.train', { depth: 1 });
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'the re-projection cleared the charges');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__port').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0);
  assert.equal(ctx.document.querySelectorAll('.is-flow-source, .is-flow-target').length, 0, 'and the endpoint ids were reset');
  for (const g of ctx.document.querySelectorAll('.mlv-edge')) {
    assert.equal((g.getAttribute('style') || '').indexOf('--mlv-flow'), -1, 'no --mlv-flow-* survived');
  }

  ctx.app.setScope(null);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'and clearing the scope leaves none either');
  for (const g of ctx.document.querySelectorAll('.mlv-edge')) {
    assert.equal((g.getAttribute('style') || '').indexOf('--mlv-flow'), -1);
  }
});

test('C1: clearFlow is idempotent', async () => {
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 120);
  for (let i = 0; i < 3; i++) {
    ctx.app.setScope(i % 2 === 0 ? 'stage:train' : null);
    assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'pass ' + i);
  }
});

test('C4: e / Shift+E iterate only routes in the CURRENT projection', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 0 });
  const drawn = new Set(Array.from(ctx.document.querySelectorAll('[data-edge-id]')).map((e) => e.getAttribute('data-edge-id')));
  assert.ok(drawn.size >= 2 && drawn.size < sample.edges.length, drawn.size + ' routes are drawn at depth 0');

  // batch_loop draws as a GROUP under this scope (it contains the ghost), and a
  // group's gesture lives on its header — go through the public selection API.
  ctx.app.focusNode(BATCH_LOOP);
  const seen = new Set();
  for (let i = 0; i < 6; i++) {
    key(ctx, ctx.canvas, 'e');
    const selected = ctx.document.querySelector('.mlv-edge.is-selected');
    assert.ok(selected, 'iteration ' + i + ' selected a route');
    const id = selected.getAttribute('data-edge-id');
    assert.ok(drawn.has(id), id + ' is a route that exists in this projection');
    seen.add(id);
  }
  assert.ok(seen.size >= 2, 'and it really cycles: ' + Array.from(seen).join(', '));
});

test('the Escape cascade is one order: sheet -> focus mode -> scope -> selection -> blur', async () => {
  const ctx = await app();
  ctx.app.setScope('stage:train');
  // batch_loop draws as a GROUP under this scope (it contains the ghost), and a
  // group's gesture lives on its header — go through the public selection API.
  ctx.app.focusNode(BATCH_LOOP);
  key(ctx, ctx.canvas, 'f'); // focus mode, latched stream
  assert.ok(ctx.canvas.classList.contains('is-focusing'));

  key(ctx, ctx.canvas, '?');
  key(ctx, ctx.canvas, 'Escape');
  assert.ok(ctx.canvas.classList.contains('is-focusing'), '1: the sheet went first');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.canvas.classList.contains('is-focusing'), false, '2: then focus mode');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0, 'and the rung stopped the flow it owned');
  assert.equal(ctx.app.getScope().spec, 'stage:train', 'the scope is still standing');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.app.getScope().spec, null, '3: then the scope');
  // batch_loop draws as a group box unscoped, so match on the id, not the class.
  assert.ok(ctx.document.querySelector('[data-node-id].is-selected'), 'the selection is still standing');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.document.querySelector('[data-node-id].is-selected'), null, '4: then the selection');
});

test('the legend is a rung of that cascade: sheet -> legend -> focus mode -> scope', async () => {
  const ctx = await app();
  const legend = () => ctx.document.querySelector('[data-legend]');
  ctx.app.setScope('stage:train');
  ctx.app.focusNode(BATCH_LOOP);
  key(ctx, ctx.canvas, 'f');
  key(ctx, ctx.canvas, 'l');
  key(ctx, ctx.canvas, '?');
  assert.equal(legend().hidden, false, 'the legend is open under the sheet');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.document.querySelector('.mlv-sheet').hidden, true, '1: the sheet went first');
  assert.equal(legend().hidden, false, 'the legend outlived it');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(legend().hidden, true, '2: then the legend');
  assert.ok(ctx.canvas.classList.contains('is-focusing'), 'focus mode is still standing');
  assert.equal(ctx.app.getScope().spec, 'stage:train', 'and so is the scope');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.canvas.classList.contains('is-focusing'), false, '3: then focus mode');
  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.app.getScope().spec, null, '4: then the scope');
  assert.ok(ctx.document.querySelector('[data-node-id].is-selected'), 'the selection is still standing');
});

test('focus mode latches a stream inside a scope, and clearing it stops it', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  // batch_loop draws as a GROUP under this scope (it contains the ghost), and a
  // group's gesture lives on its header — go through the public selection API.
  ctx.app.focusNode(BATCH_LOOP);
  key(ctx, ctx.canvas, 'f');
  await sleep(50);
  const flowing = ctx.document.querySelectorAll('.mlv-edge.is-flowing');
  assert.ok(flowing.length > 0, 'the stream latched with no pointer anywhere');
  for (const g of flowing) assert.ok(g.classList.contains('is-lit'));

  key(ctx, ctx.canvas, 'f');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});
