// From 400 px the walk bar keeps a slot for the far line beside the place on every claim of a
// walk, and puts its controls on the row under it.
//
// The document is SYNTHETIC, a small one written here. The shipped
// stylesheet is injected into the jsdom page. jsdom lays nothing out: the panel and canvas boxes
// are stubbed `getBoundingClientRect`s. The host is the test's recording bridge. The viewer is the
// built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cascadeWinner, loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

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

test('from 400 px the walk bar keeps a 22 px slot for the far line beside the place on every claim and puts its controls on the row under it, narrow and wide', async () => {
  // The far line names the other card of a connection whose two cards cannot both be shown. The
  // bar keeps a slot for it beside the place for as long as the walk runs, whether or not the
  // claim has such a line, and the controls take the whole row under it at every width from
  // 400 px. A line that came and went would change the bar's height between two claims, and with
  // it the canvas's. With the slot the bar has one height on every claim of a walk, and the canvas,
  // the phase index and the Previous and Next buttons do not move between two claims. The price is
  // canvas height on every claim of a walk. Under 400 px the bar stacks its rows
  // instead (far-walk.test.mjs). jsdom lays nothing out, so the checks below read the rules that
  // do it.
  for (const [width, layout] of [[400, 'narrow'], [541, 'narrow'], [900, 'wide']]) {
    const ctx = await mount(smallDoc(), { width, bodyH: 740 });
    try {
      press(ctx, 'r');
      const bar = $(ctx, '.mlv-walkbar');
      assert.equal(bar.getAttribute('data-layout'), layout, width + ' px');
      // One row holds the place, the far line's slot and the controls, in that order.
      eq(Array.from($(ctx, '.mlv-walkbar__row').children).map((c) => c.className), ['mlv-walkbar__pos', 'mlv-walkbar__farslot', 'mlv-walkbar__tools']);
      // The controls ask for the whole row, so they wrap to the row under the place and the slot.
      assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__tools'), 'flex').value, '1 1 100%');
      // The slot takes the room the place leaves and is 22 px high, as high as the line in it.
      const slot = $(ctx, '.mlv-walkbar__farslot');
      assert.equal(cascadeWinner(CSS, slot, 'flex').value, '1 1 0');
      assert.equal(cascadeWinner(CSS, slot, 'height').value, '22px');
      assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__far'), 'height').value, '22px');
      // The slot is there on every claim of the walk: a step, a connection and a finding.
      ctx.app.walk.setFilter('all');
      const kinds = new Set();
      for (let i = 0; i < ctx.app.walk.list.length; i++) {
        if (i) press(ctx, 'j', {}, ctx.canvas);
        kinds.add(ctx.app.walk.current().kind);
        assert.equal(slot.isConnected && !slot.hidden && slot.parentNode === $(ctx, '.mlv-walkbar__row'), true, 'claim ' + (i + 1));
      }
      eq(Array.from(kinds).sort(), ['edge', 'issue', 'node']);
      if (layout === 'narrow') {
        // Narrow, the filters take the room between Next and Exit and wrap inside it.
        assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__filters'), 'flex').value, '1 1 0');
        assert.equal(cascadeWinner(CSS, $(ctx, '.mlv-walkbar__filters'), 'min-width').value, '0');
      }
      // The order for the eye is the order for Tab and the toolbar's arrows: Previous, Next, the filters, Exit.
      const order = Array.from(bar.querySelectorAll('.mlv-walkbar__tools button:not([hidden])')).map((b) => b.getAttribute('data-walk-step') || b.getAttribute('data-walk-filter') || 'exit');
      eq(order, ['prev', 'next', 'notObserved', 'findings', 'all', 'exit']);
    } finally {
      ctx.app.destroy();
    }
  }
});
