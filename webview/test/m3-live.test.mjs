// Viewer M3 live fixes: what the live check in an isolated Extension Development Host (VS Code
// 1.139, macOS, the vit-cc shakedown artifact) found wrong on the webview side, each pinned here:
// W1 the Selection pane kept its scroll between claims, W2 a restored file kept its "not opened"
// text, W3 hover cards over a diagram the keyboard panned, W4 the phase overview's header scrolled
// away, W5 an arrow key from a connection went to the diagram's first card; and the walk bar at the
// 320 px floor.
//
// The documents are SYNTHETIC (small hand-made ones and the vit-cc shape from helpers.mjs); no
// third-party text is used. The shipped stylesheet is injected into the jsdom page. jsdom lays
// nothing out: the panel and canvas boxes are stubbed `getBoundingClientRect`s, the Selection pane
// has a stand-in layout (helpers.mjs, stubPaneLayout), and the phase overview's block offsets are
// read from its own layout. The host is the test's recording bridge, which answers the walk's opens
// by hand. None of this is a live VS Code check, a usability result or a semantic review.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cascadeWinner, inPane, loadBundle, recordingBridge, shapedWorkflow, stubPaneLayout, VIT_SHAPE, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const eq = (actual, expected, message) => (message === undefined ? assert.deepEqual(plain(actual), plain(expected)) : assert.deepEqual(plain(actual), plain(expected), message));

/** A small document: two phases, a group, connections with one and two quotes, four findings. */
function smallDoc() {
  const ev = (id, file = 'train.py', line = 1) => ({ id, file, line, endLine: line + 1, quote: 'x()' });
  return {
    workflowVersion: '1.0', title: 'Live fixes', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'o1' },
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
const opens = (ctx) => ctx.bridge.posted.filter((m) => m.type === 'openLocation');
const answer = (ctx, frame, outcome, extra = {}) =>
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: frame.requestId, action: 'openLocation', outcome, seq: frame.seq, ...extra });
const pane = (ctx) => $(ctx, '.mlv-rail [role="tabpanel"][data-tab="inspector"]');
function walkTo(ctx, id, key) {
  for (let i = 0; i < 20 && (!ctx.app.walk.current() || ctx.app.walk.current().id !== id); i++) press(ctx, key);
  assert.equal(ctx.app.walk.current() && ctx.app.walk.current().id, id, 'the walk reached ' + id);
}

/* ── W1: the Selection pane's scroll between claims ─────────────────── */

test('W1: a new selection starts the Selection pane at its top; the same claim built again keeps the reader\'s place', async () => {
  const ctx = await mount(smallDoc());
  try {
    click(ctx, $(ctx, '.mlv-node[data-node-id="load"]'));
    eq(ctx.app.selection, { kind: 'node', id: 'load' });
    // The reader scrolled the pane down; a freshness change builds the same claim again.
    pane(ctx).scrollTop = 200;
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'train.py', reason: 'changed' }] });
    assert.equal(pane(ctx).scrollTop, 200, 'the same claim keeps its place');
    // A click on another card shows that claim from its top (live: the title sat at -163 px).
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

test('W1: each step of the walk starts the pane at its top and brings the walked quote into view, the title with it when both fit, at once', async () => {
  const ctx = await mount(smallDoc());
  try {
    // A 315 px pane (as live at 540x798); the title 30 px into it, the first quote's walk line at 274-292.
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
    assert.equal(pane(ctx).scrollTop, 0, 'live, the pane kept 194 px from the claim before');
    assert.ok(inPane(title()) && inPane(walkLine()));
    // A claim whose quote is far below (a long finding): the quote is brought up the least distance
    // that shows its file line and the walk's line; the title does not fit with it, so it goes.
    stubPaneLayout(ctx.window, { quoteY: 600 });
    press(ctx, 'k');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.equal(pane(ctx).scrollTop, 600 + 24 + 18 + 8 - 315, 'scrolled at once, the walk line 8 px above the foot');
    assert.ok(inPane(walkLine()) && inPane($(ctx, '.mlv-quote.is-walk .mlv-quote__head')));
    assert.equal(inPane(title()), false);
    // [ and ] keep bringing the quote into view.
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
    // The scroll is set, not animated: the shipped CSS asks for no smooth scrolling anywhere, so
    // VS Code's Reduce Motion and the OS setting have nothing to stop.
    assert.doesNotMatch(CSS, /scroll-behavior\s*:\s*smooth/);
  } finally {
    ctx.app.destroy();
  }
});

test('W1 under reduced motion: when the step opens the bottom panel, the quote is brought into view again once the pane has its height', async () => {
  const ctx = await mount(smallDoc(), { width: 541, bodyH: 740 });
  try {
    ctx.document.body.classList.add('vscode-reduce-motion');
    // Headless Chrome, reduced motion: the stylesheet's 0.01 ms transition left the pane 16 px tall
    // when the step measured it, and the quote was scrolled to the pane's top with the title gone.
    const observers = [];
    ctx.window.ResizeObserver = class {
      constructor(callback) { this.callback = callback; this.live = true; observers.push(this); }
      observe() {}
      disconnect() { this.live = false; }
    };
    let height = 16;
    stubPaneLayout(ctx.window, { paneH: () => height, quoteY: 250 });
    press(ctx, 'r');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    assert.ok(pane(ctx).scrollTop > 0, 'precondition: measured at 16 px, the first reveal scrolls');
    height = 315;
    for (const observer of observers.filter((o) => o.live)) observer.callback([]);
    assert.equal(pane(ctx).scrollTop, 0, 'measured again at 315 px, from where the pane was');
    assert.ok(inPane($(ctx, '.mlv-sel .mlv-insp__title')) && inPane($(ctx, '.mlv-quote.is-walk .mlv-quote__walk')));
    assert.equal(observers.filter((o) => o.live).length, 0, 'the observer is let go');
  } finally {
    ctx.app.destroy();
  }
});

test('W1: a click on a claim the walk holds starts the pane at its top and shows that claim\'s quote', async () => {
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

/* ── W2: a restored file ─────────────────────────────────────────────── */

test('W2: once the host no longer lists the changed file, the bar and the quote stop saying "not opened" and nothing is opened by itself', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'load', 'k');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'changed', message: 'data.py changed after revision o1 was published; not opened.' });
    const text = () => $(ctx, '.mlv-walkbar__editortext').textContent;
    const mark = () => $(ctx, '.mlv-quote.is-walk');
    assert.equal(text(), 'data.py changed after revision o1 was published; not opened.');
    assert.equal(mark().getAttribute('data-walk-status'), 'blocked');
    assert.equal($(ctx, '.mlv-walkbar__editoricon').hidden, false);
    const before = opens(ctx).length;
    // The file is restored: the host's stale list is empty again.
    ctx.bridge.send({ v: 1, type: 'stale', files: [] });
    eq(ctx.app.walk.current(), { kind: 'node', id: 'load' });
    assert.equal(text(), 'Enter shows data.py · lines 3–4 in the editor beside.');
    assert.equal($(ctx, '.mlv-walkbar__editoricon').hidden, true, 'no warning mark');
    assert.equal(mark().getAttribute('data-walk-status'), 'idle');
    assert.equal(mark().querySelector('.mlv-quote__walk').textContent, 'Enter shows these lines in the editor beside.');
    assert.equal(mark().querySelector('.mlv-quote__walk svg'), null, 'no warning icon under the quote');
    assert.equal(opens(ctx).length, before, 'nothing is opened by itself');
    assert.equal(ctx.app.walk.pendingOpen, false);
    // Enter opens it.
    press(ctx, 'Enter');
    assert.equal(opens(ctx).length, before + 1);
    assert.equal(opens(ctx).at(-1).evidenceId, 'e1');
  } finally {
    ctx.app.destroy();
  }
});

test('W2: a file that goes from changed to missing says so; a block for unsaved edits stays when another file changes', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'load', 'k');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'changed', message: 'data.py changed after revision o1 was published; not opened.' });
    const text = () => $(ctx, '.mlv-walkbar__editortext').textContent;
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'missing' }] });
    assert.equal(text(), 'data.py: file missing; not opened.');
    // Unsaved edits in train.py lost the cited lines; then data.py is restored. The train.py block stays.
    walkTo(ctx, 'step', 'j');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'unsaved', message: 'train.py has unsaved edits that no longer contain the cited lines; not opened.' });
    ctx.bridge.send({ v: 1, type: 'stale', files: [] });
    eq(ctx.app.walk.current(), { kind: 'node', id: 'step' });
    assert.equal(text(), 'Quote 1 of 2: train.py has unsaved edits that no longer contain the cited lines; not opened.');
  } finally {
    ctx.app.destroy();
  }
});

/* ── W3: hover cards over a diagram the keyboard moves ───────────────── */

test('W3: a keyboard move or a walk step hides the hover card, and what passes under the resting pointer gets none until the pointer moves', async () => {
  const ctx = await mount(smallDoc());
  try {
    const tooltip = $(ctx, '.mlv-tooltip');
    const card = (id) => $(ctx, `.mlv-node[data-node-id="${id}"]`);
    const move = (element, x, y) => element.dispatchEvent(new ctx.window.MouseEvent('pointermove', { bubbles: true, clientX: x, clientY: y }));
    const enter = (element) => element.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
    const title = () => tooltip.querySelector('.mlv-tooltip__title').textContent;
    // The pointer rests on a card: its hover card opens after the usual 400 ms.
    move(card('load'), 100, 100);
    enter(card('load'));
    await sleep(450);
    assert.equal(tooltip.hidden, false);
    assert.equal(title(), 'Load batches');
    // An arrow key: the card goes at once, with the hover's trace.
    ctx.canvas.focus();
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    assert.equal(tooltip.hidden, true);
    assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
    assert.equal(ctx.app.view.hoverIsHeld, true);
    // The diagram panned another card under the resting pointer: the browser sends pointerenter
    // and a move to the same place. No hover card.
    enter(card('aug'));
    move(card('aug'), 100, 100);
    await sleep(450);
    assert.equal(tooltip.hidden, true, 'live, this card covered part of the diagram');
    // A cable that passes under it does not take the hover either.
    const cable = $(ctx, '.mlv-edge[data-edge-id="c-load-aug"]');
    enter(cable.querySelector('.mlv-edge__hit'));
    assert.equal(cable.classList.contains('is-hover'), false);
    // The reader moves the pointer: the card under it gets its hover again.
    move(card('aug'), 104, 101);
    assert.equal(ctx.app.view.hoverIsHeld, false);
    await sleep(450);
    assert.equal(tooltip.hidden, false);
    assert.equal(title(), 'Augment');
    // A walk step does the same, from the keyboard (r, j) or from the bar's Next button.
    press(ctx, 'r', {}, ctx.canvas);
    assert.equal(tooltip.hidden, true);
    enter(card('zero'));
    move(card('zero'), 104, 101);
    await sleep(450);
    assert.equal(tooltip.hidden, true);
    move(card('zero'), 120, 110);
    await sleep(450);
    assert.equal(title(), 'Zero grads');
    $(ctx, '.mlv-walkbar__step--next').click();
    assert.equal(tooltip.hidden, true);
    assert.equal(ctx.app.view.hoverIsHeld, true);
    // A press of the pointer ends the hold too.
    ctx.canvas.dispatchEvent(new ctx.window.MouseEvent('pointerdown', { bubbles: true, clientX: 120, clientY: 110 }));
    assert.equal(ctx.app.view.hoverIsHeld, false);
  } finally {
    ctx.app.destroy();
  }
});

/* ── W4: the phase overview's header ─────────────────────────────────── */

/** The overview's own block geometry stands in for the layout jsdom does not do. */
function stubOverviewLayout(ctx) {
  const proto = ctx.window.HTMLElement.prototype;
  Object.defineProperty(proto, 'clientHeight', {
    configurable: true,
    get() { return this.classList.contains('mlv-overview') ? ctx.box().h : 0; },
  });
  Object.defineProperty(proto, 'offsetTop', { configurable: true, get() { return this.classList.contains('mlv-ovblock') ? parseFloat(this.style.top) : 0; } });
  Object.defineProperty(proto, 'offsetHeight', { configurable: true, get() { return this.classList.contains('mlv-ovblock') ? parseFloat(this.style.height) : 0; } });
}

for (const [name, width, bodyH] of [['541x798 (sheet collapsed)', 541, 740], ['541 px beside an open sheet', 541, 470], ['901 px beside an open sheet', 901, 470]]) {
  test(`W4, ${name}: the overview's header with Back, the counts and the key sticks while it scrolls; a block brought into view sits below it; Home goes back to the top`, async () => {
    const ctx = await mount(shapedWorkflow(VIT_SHAPE), { width, bodyH });
    try {
      stubOverviewLayout(ctx);
      press(ctx, ')', { shiftKey: true, code: 'Digit0' });
      assert.equal(ctx.app.view.overviewOpen, true);
      const overview = $(ctx, '.mlv-overview');
      const layout = ctx.app.view.overviewLayout();
      const view = ctx.box().h;
      assert.equal(layout.scrolls, true, 'precondition: this overview scrolls');
      const header = $(ctx, '.mlv-overview__header');
      assert.ok(header.contains($(ctx, '.mlv-overview__back')) && header.contains($(ctx, '.mlv-overview__summary')) && header.contains($(ctx, '.mlv-overview__key')));
      assert.equal(header.getAttribute('data-sticky'), 'true');
      assert.equal(cascadeWinner(CSS, header, 'position').value, 'sticky');
      assert.equal(cascadeWinner(CSS, header, 'top').value, '0');
      const covered = layout.header.y + layout.header.h;
      assert.equal(header.style.height, covered + 'px', 'the header is the space above the first block, so nothing below it moves');
      assert.ok(covered * 2 <= view);
      const check = (label) => {
        const at = Number(ctx.document.activeElement.getAttribute('data-block'));
        const block = layout.blocks[at];
        const top = block.y - overview.scrollTop;
        assert.ok(top >= covered, `${label}: block ${at} starts ${top} px down, below the header's ${covered} px`);
        if (block.h + 24 <= view - covered) assert.ok(top + block.h <= view, `${label}: block ${at} ends inside the overlay`);
      };
      press(ctx, 'End');
      assert.ok(overview.scrollTop > 0, 'End scrolls');
      check('End');
      for (let i = 0; i < layout.blocks.length - 1; i++) {
        press(ctx, 'ArrowUp');
        check('ArrowUp ' + (i + 1));
      }
      press(ctx, 'End');
      press(ctx, 'Home');
      assert.equal(overview.scrollTop, 0, 'Home shows the header whole (it used to stop 12 px above the first block)');
    } finally {
      ctx.app.destroy();
    }
  });
}

test('W4: a header taller than half the overlay scrolls with the blocks, and Home still shows it whole when the first block fits', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { width: 541, bodyH: 230 });
  try {
    stubOverviewLayout(ctx);
    press(ctx, ')', { shiftKey: true, code: 'Digit0' });
    const layout = ctx.app.view.overviewLayout();
    const header = $(ctx, '.mlv-overview__header');
    assert.ok((layout.header.y + layout.header.h) * 2 > ctx.box().h, 'precondition: a short overlay');
    assert.equal(header.getAttribute('data-sticky'), 'false');
    assert.equal(cascadeWinner(CSS, header, 'position').value, 'relative');
    press(ctx, 'End');
    const block = layout.blocks[layout.blocks.length - 1];
    assert.ok(block.y - $(ctx, '.mlv-overview').scrollTop >= 0, 'the last block\'s top shows');
  } finally {
    ctx.app.destroy();
  }
});

/* ── W5: arrow keys from a connection or a finding ───────────────────── */

test('W5: from a connection an arrow key selects the end that lies that way; from a finding it moves as from its first cited step', async () => {
  const ctx = await mount(smallDoc());
  try {
    const boxes = ctx.app.view.frame.boxes;
    const centre = (id) => { const b = boxes.get(id); return { x: b.x + b.w / 2, y: b.y + b.h / 2 }; };
    const first = Array.from(boxes.values()).sort((a, b) => a.y - b.y || a.x - b.x)[0].id;
    const fromSelection = (sel, key) => {
      ctx.app.select(sel);
      ctx.canvas.focus();
      press(ctx, key, {}, ctx.canvas);
      return plain(ctx.app.selection);
    };
    // Optimizer step -> Zero grads, both inside the group, neither the diagram's first card.
    const [s, t] = [centre('step'), centre('zero')];
    const towards = (key) => {
      const d = key === 'ArrowRight' || key === 'ArrowLeft' ? t.x - s.x : t.y - s.y;
      const forward = key === 'ArrowRight' || key === 'ArrowDown';
      return d === 0 ? (forward ? 'zero' : 'step') : (d > 0) === forward ? 'zero' : 'step';
    };
    for (const key of ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp']) {
      eq(fromSelection({ kind: 'edge', id: 'c-step-zero' }, key), { kind: 'node', id: towards(key) }, key + ' from the connection');
    }
    assert.notEqual(first, 'step');
    assert.notEqual(first, 'zero');
    // The two ends are on different sides one way or the other, so the arrows reach both.
    assert.equal(new Set(['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'].map(towards)).size, 2);
    // A finding moves as its first cited step, which the diagram marks for it.
    const fromStep = fromSelection({ kind: 'node', id: 'step' }, 'ArrowRight');
    eq(fromSelection({ kind: 'issue', id: 'f-step' }, 'ArrowRight'), fromStep);
    // A finding on a connection only: as from that connection.
    const [a, b] = [centre('aug'), centre('step')];
    eq(fromSelection({ kind: 'issue', id: 'f-edge' }, 'ArrowDown'), { kind: 'node', id: b.y - a.y >= 0 ? 'step' : 'aug' });
    // A finding that cites neither, and no selection: the first card, as before.
    eq(fromSelection({ kind: 'issue', id: 'f-whole' }, 'ArrowRight'), { kind: 'node', id: first });
    ctx.app.clearSelection();
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    eq(ctx.app.selection, { kind: 'node', id: first });
    // A selected step inside a folded group counts from the group, which is the card drawn for it
    // (it went to the first card too).
    ctx.app.select({ kind: 'node', id: 'step' });
    ctx.app.view.toggleCollapse('loop');
    assert.equal(ctx.app.view.frame.boxes.has('step'), false, 'precondition: the step is folded away');
    ctx.canvas.focus();
    press(ctx, 'ArrowUp', {}, ctx.canvas);
    const fromFolded = plain(ctx.app.selection);
    eq(fromSelection({ kind: 'node', id: 'loop' }, 'ArrowUp'), fromFolded);
    assert.notEqual(fromFolded.id, first);
  } finally {
    ctx.app.destroy();
  }
});

test('W5: in the review walk, ← and → on a connection go to its nearer end in that direction, and the walk follows when it holds that step', async () => {
  const ctx = await mount(smallDoc());
  try {
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'c-step-zero', 'j');
    const boxes = ctx.app.view.frame.boxes;
    const cx = (id) => boxes.get(id).x + boxes.get(id).w / 2;
    const right = cx('zero') >= cx('step') ? 'zero' : 'step';
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    eq(ctx.app.selection, { kind: 'node', id: right });
    eq(ctx.app.walk.current(), { kind: 'node', id: right }, 'the walk moved there (All claims holds every step)');
  } finally {
    ctx.app.destroy();
  }
});

/* ── the walk bar at the 320 px floor ────────────────────────────────── */

test('the narrow walk bar puts its controls beside the place and wraps the filters between Next and Exit (two rows at 320 px, measured in Chrome)', async () => {
  const ctx = await mount(smallDoc(), { width: 320, bodyH: 740 });
  try {
    press(ctx, 'r');
    const bar = $(ctx, '.mlv-walkbar');
    assert.equal(bar.getAttribute('data-layout'), 'narrow');
    // Headless Chrome (simulated host) at 320x798: four rows and 102 px before, two rows and 55 px
    // after. jsdom lays nothing out, so this pins the rules that do it.
    assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__tools'), 'flex').value, '1 1 0');
    assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__filters'), 'flex').value, '1 1 0');
    assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__filters'), 'min-width').value, '0');
    // The order for the eye is the order for Tab and the toolbar's arrows: Previous, Next, the filters, Exit.
    const order = Array.from(bar.querySelectorAll('.mlv-walkbar__tools button:not([hidden])')).map((b) => b.getAttribute('data-walk-step') || b.getAttribute('data-walk-filter') || 'exit');
    eq(order, ['prev', 'next', 'notObserved', 'findings', 'all', 'exit']);
  } finally {
    ctx.app.destroy();
  }
});
