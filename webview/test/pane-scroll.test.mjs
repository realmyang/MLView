// A new selection starts the Selection pane at its top, and a step of the walk brings the walked
// quote into view.
//
// The document is SYNTHETIC, a small one written here. The shipped
// stylesheet is injected into the jsdom page. jsdom lays nothing out: the panel and canvas boxes
// are stubbed `getBoundingClientRect`s, and the Selection pane has a stand-in layout (helpers.mjs,
// stubPaneLayout). The host is the test's recording bridge. The viewer is the built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { inPane, loadBundle, recordingBridge, stubPaneLayout, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const eq = (actual, expected, message) => (message === undefined ? assert.deepEqual(plain(actual), plain(expected)) : assert.deepEqual(plain(actual), plain(expected), message));

/** A small document: two phases, a group, connections with one and two quotes, three findings. */
function smallDoc() {
  const ev = (id, file = 'train.py', line = 1) => ({ id, file, line, endLine: line + 1, quote: 'x()' });
  return {
    workflowVersion: '1.0', title: 'Small training workflow', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'o1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', basis: 'inferred', evidence: ['e3', 'e4'] },
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'observed', evidence: ['e2'] },
      { id: 'zero', label: 'Zero grads', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e5'] },
    ],
    edges: [
      { id: 'c-step-zero', source: 'step', target: 'zero', label: 'then', basis: 'observed', evidence: ['e4'] },
      { id: 'c-load-aug', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c-aug-step', source: 'aug', target: 'step', label: 'batches', basis: 'inferred', evidence: ['e2', 'e3'] },
    ],
    findings: [
      { id: 'f-whole', title: 'No seed', message: 'm', severity: 'low', nodeIds: [], basis: 'observed', evidence: ['e1'] },
      { id: 'f-edge', title: 'Cast on batches', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c-aug-step'], basis: 'unresolved', evidence: ['e2'] },
      { id: 'f-step', title: 'Clip missing', message: 'm', severity: 'medium', nodeIds: ['step'], basis: 'observed', evidence: ['e3'] },
    ],
    evidence: [ev('e1', 'data.py', 3), ev('e2', 'data.py', 9), ev('e3', 'train.py', 4), ev('e4', 'train.py', 8), ev('e5', 'train.py', 12)],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['data.py', 'train.py'], limitations: [] },
  };
}

/** Mount in a panel `width` px wide whose body (between header and status bar) is `bodyH` px. */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
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
    const w = docked ? width - (rail.hidden ? 0 : 360) : width;
    const sheet = docked ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * 0.47) : 32;
    return { w, h: bodyH - sheet };
  };
  canvas.getBoundingClientRect = () => {
    const { w, h } = box();
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  app.view.fit();
  canvas.focus();
  return { ...ctx, root, bridge, app, canvas, rail, box };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const click = (ctx, element) => element.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
const pane = (ctx) => $(ctx, '.mlv-rail [role="tabpanel"][data-tab="inspector"]');

/* ── the Selection pane's scroll between claims ─────────────────────── */

test('a new selection starts the Selection pane at its top; the same claim built again keeps the reader\'s place', async () => {
  const ctx = await mount(smallDoc());
  try {
    click(ctx, $(ctx, '.mlv-node[data-node-id="load"]'));
    eq(ctx.app.selection, { kind: 'node', id: 'load' });
    // The reader scrolled the pane down; a freshness change builds the same claim again.
    pane(ctx).scrollTop = 200;
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'train.py', reason: 'changed' }] });
    assert.equal(pane(ctx).scrollTop, 200, 'the same claim keeps its place');
    // A click on another card shows that claim from its top.
    click(ctx, $(ctx, '.mlv-node[data-node-id="aug"]'));
    eq(ctx.app.selection, { kind: 'node', id: 'aug' });
    assert.equal(pane(ctx).scrollTop, 0, 'another claim starts at the top');
    // A connection chosen from the pane's links does the same.
    pane(ctx).scrollTop = 150;
    ctx.app.select({ kind: 'edge', id: 'c-load-aug' }, { tab: 'inspector' });
    assert.equal(pane(ctx).scrollTop, 0);
  } finally {
    ctx.app.destroy();
  }
});

test('each step of the walk starts the pane at its top and brings the walked quote into view when it fits with the title; [ and ] bring the quote, at once', async () => {
  const ctx = await mount(smallDoc());
  try {
    // A 315 px pane; the title 30 px into it, the first quote's walk line at 274-292.
    stubPaneLayout(ctx.window, { quoteY: 250 });
    const title = () => $(ctx, '.mlv-sel .mlv-insp__title');
    const walkLine = () => $(ctx, '.mlv-quote.is-walk .mlv-quote__walk');
    press(ctx, 'r');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.equal(pane(ctx).scrollTop, 0);
    assert.ok(inPane(title()) && inPane(walkLine()), 'the title and the walked quote both show');
    // The reader scrolls the pane, then steps: the next claim starts at its top again.
    pane(ctx).scrollTop = 200;
    press(ctx, 'j');
    assert.notEqual(ctx.app.walk.current().id, 'c-aug-step');
    assert.equal(pane(ctx).scrollTop, 0, 'the next claim starts the pane at its top, not at the scroll left on the claim before');
    assert.ok(inPane(title()) && inPane(walkLine()));
    // A quote just below the fold that fits with the title: the least scroll that shows both.
    stubPaneLayout(ctx.window, { quoteY: 280 });
    press(ctx, 'k');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.equal(pane(ctx).scrollTop, 280 + 24 + 18 + 8 - 315, 'scrolled at once, the walk line 8 px above the foot');
    assert.ok(inPane(title()) && inPane(walkLine()));
    // A claim whose quote is far below (a long finding): the title does not fit with it, so the
    // step keeps the claim's title in view; the editor beside shows the quoted lines highlighted.
    stubPaneLayout(ctx.window, { quoteY: 600 });
    press(ctx, 'j');
    press(ctx, 'k');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.equal(pane(ctx).scrollTop, 0, 'the step keeps the title');
    assert.ok(inPane(title()));
    assert.equal(inPane(walkLine()), false);
    // ] and [ ask for the quote: it wins when both do not fit.
    press(ctx, ']');
    assert.equal(pane(ctx).scrollTop, 840 + 24 + 18 + 8 - 315);
    assert.ok(inPane(walkLine()));
    press(ctx, '[');
    assert.equal(pane(ctx).scrollTop, 840 + 24 + 18 + 8 - 315, 'the first quote\'s lines still show: no move');
    assert.ok(inPane(walkLine()));
    pane(ctx).scrollTop = 700;
    press(ctx, ']');
    press(ctx, '[');
    assert.equal(pane(ctx).scrollTop, 600 - 8, 'from below, back up the least distance: the quote 8 px under the top edge');
    assert.ok(inPane(walkLine()));
    // The scroll is set, not animated: no rule of the shipped CSS asks for smooth scrolling, so
    // there is no scroll animation for a reduced-motion setting to stop.
    assert.doesNotMatch(CSS, /scroll-behavior\s*:\s*smooth/);
  } finally {
    ctx.app.destroy();
  }
});

test('under reduced motion: when a walk step opens the bottom panel, the quote is brought into view again once the pane has its height', async () => {
  const ctx = await mount(smallDoc(), { width: 541, bodyH: 740 });
  try {
    ctx.document.body.classList.add('vscode-reduce-motion');
    // Under reduced motion the stylesheet still gives the opening panel a 0.01 ms transition, so
    // the step can measure the pane before it has its height (16 px here). It measures again,
    // through a ResizeObserver, once the pane has grown.
    const observers = [];
    ctx.window.ResizeObserver = class {
      constructor(callback) { this.callback = callback; this.live = true; observers.push(this); }
      observe() {}
      disconnect() { this.live = false; }
    };
    let height = 16;
    stubPaneLayout(ctx.window, { paneH: () => height, quoteY: 280 });
    press(ctx, 'r');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.equal(pane(ctx).scrollTop, 0, 'precondition: measured at 16 px, nothing fits with the title, so the title stays');
    height = 315;
    for (const observer of observers.filter((o) => o.live)) observer.callback([]);
    assert.equal(pane(ctx).scrollTop, 280 + 24 + 18 + 8 - 315, 'measured again at 315 px: the quote fits with the title and is brought into view');
    assert.ok(inPane($(ctx, '.mlv-sel .mlv-insp__title')) && inPane($(ctx, '.mlv-quote.is-walk .mlv-quote__walk')));
    assert.equal(observers.filter((o) => o.live).length, 0, 'the observer is let go');
  } finally {
    ctx.app.destroy();
  }
});

test('a click on a claim the walk holds starts the pane at its top and shows that claim\'s quote', async () => {
  const ctx = await mount(smallDoc());
  try {
    stubPaneLayout(ctx.window, { quoteY: 250 });
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    pane(ctx).scrollTop = 220;
    click(ctx, $(ctx, '.mlv-node[data-node-id="step"]'));
    eq(ctx.app.walk.current(), { kind: 'node', id: 'step' });
    assert.equal(pane(ctx).scrollTop, 0);
    assert.ok(inPane($(ctx, '.mlv-sel .mlv-insp__title')) && inPane($(ctx, '.mlv-quote.is-walk .mlv-quote__walk')));
  } finally {
    ctx.app.destroy();
  }
});
