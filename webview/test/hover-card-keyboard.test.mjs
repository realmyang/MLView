// A keyboard move or a walk step hides the hover card, and a card or a connection that the diagram
// moves under the resting pointer gets none until the pointer moves; a press of the pointer ends
// that hold too.
//
// The document is SYNTHETIC, a small one written here. The shipped
// stylesheet is injected into the jsdom page. jsdom lays nothing out: the panel and canvas boxes
// are stubbed `getBoundingClientRect`s. The host is the test's recording bridge. The viewer is the
// built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

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

test('a keyboard move or a walk step hides the hover card, and what passes under the resting pointer gets none until the pointer moves', async () => {
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
    // The diagram panned another card under the resting pointer: it gets pointerenter and a move
    // to the same place. No hover card.
    enter(card('aug'));
    move(card('aug'), 100, 100);
    await sleep(450);
    assert.equal(tooltip.hidden, true, 'no hover card for the card the diagram moved under the resting pointer');
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
    // A walk step does the same, from the keyboard (r) or from the bar's Next button.
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
