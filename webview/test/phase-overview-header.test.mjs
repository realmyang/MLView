// The phase overview's header, with Back, the counts and the key, sticks while its blocks scroll,
// and a block brought into view sits below it. A header taller than half the overlay scrolls with
// the blocks. Home shows the header whole when the first block fits below it, else the first
// block's top.
//
// The documents are SYNTHETIC: a small one written here and the 79-claim shape from helpers.mjs.
// The shipped stylesheet is injected into the jsdom page. jsdom lays
// nothing out: the panel and canvas boxes are stubbed `getBoundingClientRect`s, and the phase
// overview's block offsets are read from its own layout. The host is the test's recording bridge.
// The viewer is the built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cascadeWinner, loadBundle, recordingBridge, shapedWorkflow, SHAPE_79_CLAIMS, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');

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
  test(`${name}: the overview's header with Back, the counts and the key sticks while it scrolls; a block brought into view sits below it; Home goes back to the top`, async () => {
    const ctx = await mount(shapedWorkflow(SHAPE_79_CLAIMS), { width, bodyH });
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
      assert.equal(overview.scrollTop, 0, 'Home scrolls to the very top and shows the header whole');
    } finally {
      ctx.app.destroy();
    }
  });
}

for (const [name, doc, width, bodyH, fits] of [
  ['79-claim shape at 541 px, first block too tall to fit below the header', () => shapedWorkflow(SHAPE_79_CLAIMS), 541, 230, false],
  ['a short first block at 320 px that fits below the header', () => smallDoc(), 320, 300, true],
]) {
  test(`${name}: a header taller than half the overlay scrolls with the blocks; Home shows it whole when the first block fits below it, else the first block's top`, async () => {
    const ctx = await mount(doc(), { width, bodyH });
    try {
      stubOverviewLayout(ctx);
      press(ctx, ')', { shiftKey: true, code: 'Digit0' });
      const layout = ctx.app.view.overviewLayout();
      const header = $(ctx, '.mlv-overview__header');
      const overview = $(ctx, '.mlv-overview');
      const view = ctx.box().h;
      assert.ok((layout.header.y + layout.header.h) * 2 > view, 'precondition: a short overlay');
      assert.equal(header.getAttribute('data-sticky'), 'false');
      assert.equal(cascadeWinner(CSS, header, 'position').value, 'relative');
      const first = layout.blocks[0];
      assert.equal(first.y + first.h + 12 <= view, fits, 'precondition: whether the first block fits below the header');
      press(ctx, 'End');
      const block = layout.blocks[layout.blocks.length - 1];
      assert.ok(overview.scrollTop > 0 && block.y - overview.scrollTop >= 0, 'the last block\'s top shows');
      press(ctx, 'Home');
      // The header (with Back) shows whole only when the first block fits.
      assert.equal(overview.scrollTop, fits ? 0 : first.y - 12);
    } finally {
      ctx.app.destroy();
    }
  });
}
