// What the walk bar and the walked quote say of a cited file while the host's list of stale files
// changes. Once the host stops listing a file as changed, the bar and the quote stop saying "not
// opened" and nothing is opened by itself; a file that goes from changed to missing says so; a
// block the host gave for unsaved edits stays when a file leaves the list.
//
// The document is SYNTHETIC, a small one written here. The shipped
// stylesheet is injected into the jsdom page. jsdom lays nothing out: the panel and canvas boxes
// are stubbed `getBoundingClientRect`s. The host is the test's recording bridge, which answers the
// walk's opens by hand. The viewer is the built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

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
const opens = (ctx) => ctx.bridge.posted.filter((m) => m.type === 'openLocation');
const answer = (ctx, frame, outcome, extra = {}) =>
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: frame.requestId, action: 'openLocation', outcome, seq: frame.seq, ...extra });
function walkTo(ctx, id, key) {
  for (let i = 0; i < 20 && (!ctx.app.walk.current() || ctx.app.walk.current().id !== id); i++) press(ctx, key);
  assert.equal(ctx.app.walk.current() && ctx.app.walk.current().id, id, 'the walk reached ' + id);
}

test('once the host no longer lists the changed file, the bar and the quote stop saying "not opened" and nothing is opened by itself', async () => {
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

test('a file that goes from changed to missing says so; a block for unsaved edits stays when another file changes', async () => {
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

test('a block the host gave for unsaved edits stays when the same file then leaves the stale list', async () => {
  const ctx = await mount(smallDoc());
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'load', 'k');
    ctx.app.walk.flushOpen();
    // The host checked the editor's unsaved text, not the file on disk: its reason is not a stale one.
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'unsaved', message: 'data.py has unsaved edits that no longer contain the cited lines; not opened.' });
    const text = () => $(ctx, '.mlv-walkbar__editortext').textContent;
    const before = opens(ctx).length;
    ctx.bridge.send({ v: 1, type: 'stale', files: [] });
    eq(ctx.app.walk.current(), { kind: 'node', id: 'load' });
    assert.equal(text(), 'data.py has unsaved edits that no longer contain the cited lines; not opened.');
    assert.equal($(ctx, '.mlv-quote.is-walk').getAttribute('data-walk-status'), 'blocked');
    assert.equal(opens(ctx).length, before, 'nothing opened by itself');
  } finally {
    ctx.app.destroy();
  }
});
