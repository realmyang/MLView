// From a connection an arrow key selects the end that lies that way, and from a finding it moves
// as from its first cited step or its connection. In the review walk the walk follows such a move
// when it holds that step.
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

const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
function walkTo(ctx, id, key) {
  for (let i = 0; i < 20 && (!ctx.app.walk.current() || ctx.app.walk.current().id !== id); i++) press(ctx, key);
  assert.equal(ctx.app.walk.current() && ctx.app.walk.current().id, id, 'the walk reached ' + id);
}

test('from a connection an arrow key selects the end that lies that way; from a finding it moves as from its first cited step', async () => {
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
    // A finding that cites neither, and no selection: the first card.
    eq(fromSelection({ kind: 'issue', id: 'f-whole' }, 'ArrowRight'), { kind: 'node', id: first });
    ctx.app.clearSelection();
    press(ctx, 'ArrowRight', {}, ctx.canvas);
    eq(ctx.app.selection, { kind: 'node', id: first });
    // A selected step inside a folded group counts from the group, which is the card drawn for it,
    // and not from the first card.
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

test('in the review walk, ← and → on a connection go to its nearer end in that direction, and the walk follows when it holds that step', async () => {
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
