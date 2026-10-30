// A drag on the diagram's background pans it; a click there clears the selection. The browser
// sends a click after every press and release on the canvas, also after a drag. If that click
// cleared the selection, a reader who dragged the diagram to follow a selected connection would
// lose its lit line. This pins the rule in `wireCanvasGestures` (ui/shell.ts): a press that
// travelled more than 4 px (x plus y) is a drag, and its click keeps the selection.
//
// The document is SYNTHETIC (three steps, two connections, written here). jsdom lays nothing out
// and has no pointer capture; the events are dispatched by hand in the order a browser sends them
// (pointerdown, pointermove, pointerup, click). The viewer is the built bundle, mounted in jsdom.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

function doc() {
  const ev = (id, line) => ({ id, file: 'train.py', line, endLine: line + 1, quote: 'x()' });
  return {
    workflowVersion: '1.0', title: 'Pan and click', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'p1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'observed', evidence: ['e2'] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', basis: 'observed', evidence: ['e3'] },
    ],
    edges: [
      { id: 'c-load-aug', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c-aug-step', source: 'aug', target: 'step', label: 'batches', basis: 'inferred', evidence: ['e2'] },
    ],
    findings: [],
    evidence: [ev('e1', 3), ev('e2', 9), ev('e3', 14)],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

async function mount() {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: 1440, height: 900, right: 1440, bottom: 900 });
  const app = ctx.MLView.mountWorkflow(root, doc(), recordingBridge(ctx.window, 'vscode'));
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: 1080, height: 842, right: 1080, bottom: 842 });
  ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  app.view.fit();
  return { ...ctx, app, canvas };
}

/** One press on the canvas's background at (100, 100), moved through `path`, released, and the click the browser then sends. */
function press(ctx, path) {
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

const selection = (ctx) => (ctx.app.selection ? { kind: ctx.app.selection.kind, id: ctx.app.selection.id } : null);

test('a drag on the background pans the diagram and keeps the selection; the next click there clears it', async () => {
  const ctx = await mount();
  try {
    ctx.app.select({ kind: 'edge', id: 'c-aug-step' });
    const before = { ...ctx.app.view.viewport.vp };
    press(ctx, [[130, 120], [160, 140]]);
    const after = ctx.app.view.viewport.vp;
    assert.deepEqual([after.x - before.x, after.y - before.y, after.zoom], [60, 40, before.zoom], 'the diagram moved with the pointer');
    assert.deepEqual(selection(ctx), { kind: 'edge', id: 'c-aug-step' }, 'the click that ends a drag is not a click on the background');
    // A press and release in one place is a click on the background and clears the selection.
    press(ctx, []);
    assert.equal(selection(ctx), null);
  } finally {
    ctx.app.destroy();
  }
});

test('a press that travels 4 px or less is still a click; a drag with no click after it does not swallow the next click', async () => {
  const ctx = await mount();
  try {
    ctx.app.select({ kind: 'node', id: 'aug' });
    press(ctx, [[102, 102]]);
    assert.equal(selection(ctx), null, 'a hand that moved 4 px while clicking clicked');
    // A drag whose release the canvas never saw (it ended outside the window): no click follows.
    ctx.app.select({ kind: 'node', id: 'aug' });
    const send = (type, x, y) => ctx.canvas.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y }));
    send('pointerdown', 100, 100);
    send('pointermove', 180, 100);
    send('pointercancel', 180, 100);
    assert.deepEqual(selection(ctx), { kind: 'node', id: 'aug' });
    press(ctx, []);
    assert.equal(selection(ctx), null, 'the next click on the background clears the selection');
  } finally {
    ctx.app.destroy();
  }
});

test('a drag that arrives in many small moves, as a hand makes one, keeps the selection: the distance is counted from the press, not from the last move', async () => {
  const ctx = await mount();
  try {
    ctx.app.select({ kind: 'edge', id: 'c-aug-step' });
    const before = { ...ctx.app.view.viewport.vp };
    // 30 moves of 2 px left and 1 px up each: no move is over 4 px, the drag is 90.
    press(ctx, Array.from({ length: 30 }, (_, i) => [100 - 2 * (i + 1), 100 - (i + 1)]));
    const after = ctx.app.view.viewport.vp;
    assert.deepEqual([after.x - before.x, after.y - before.y], [-60, -30], 'the diagram moved with the pointer');
    assert.deepEqual(selection(ctx), { kind: 'edge', id: 'c-aug-step' });
  } finally {
    ctx.app.destroy();
  }
});

test('a drag straight down, straight up, straight left or straight right keeps the selection', async () => {
  const ctx = await mount();
  try {
    ctx.app.select({ kind: 'edge', id: 'c-aug-step' });
    for (const [way, path] of [['down', [[100, 130], [100, 160]]], ['up', [[100, 70], [100, 40]]], ['left', [[70, 100], [40, 100]]], ['right', [[130, 100], [160, 100]]]]) {
      press(ctx, path);
      assert.deepEqual(selection(ctx), { kind: 'edge', id: 'c-aug-step' }, way);
    }
  } finally {
    ctx.app.destroy();
  }
});

test('5 px is the first distance that is a drag, along one axis or as 3 px and 2 px; 4 px, as 2 px and 2 px or along one axis, is a click', async () => {
  const ctx = await mount();
  try {
    for (const [what, to, drag] of [['3 + 2 px', [103, 102], true], ['5 px down', [100, 105], true], ['5 px left', [95, 100], true], ['2 + 2 px', [102, 102], false], ['4 px down', [100, 104], false], ['4 px right', [104, 100], false]]) {
      ctx.app.select({ kind: 'edge', id: 'c-aug-step' });
      press(ctx, [to]);
      assert.deepEqual(selection(ctx), drag ? { kind: 'edge', id: 'c-aug-step' } : null, what);
    }
  } finally {
    ctx.app.destroy();
  }
});
