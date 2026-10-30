// How the canvas brings cards forward in the mounted viewer. A finding that cites a step and a
// connection elsewhere frames the step and both ends of the connection. A hover dims no card and
// rings the lit ones; focus mode dims the rest and makes it inert.
//
// The shipped stylesheet is injected into the jsdom page, and a rule that depends on specificity
// is resolved with `cascadeWinner` (helpers.mjs). The document is a small one written here,
// mounted in the built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { cascadeWinner, loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Fine-tune a classifier on CIFAR-10 with mixed precision',
    producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r7' },
    request: { question: 'How is the classifier trained?', scope: 'train.py' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'], detail: 'Reads CIFAR-10 with batch size 64.' },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'inferred', evidence: ['e1'] },
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', kind: 'optimizer', basis: 'observed', evidence: ['e2'] },
      { id: 'sched', label: 'LR schedule', phase: 'fit', parent: 'loop', kind: 'scheduler', basis: 'observed', evidence: ['e2'] },
    ],
    edges: [
      { id: 'c1', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c2', source: 'aug', target: 'step', label: 'batches', basis: 'unresolved', evidence: [] },
      { id: 'c3', source: 'step', target: 'sched', label: 'optimizer handle', basis: 'observed', evidence: ['e2'] },
    ],
    findings: [
      { id: 'f-amp', title: 'Loss scaling skipped', message: 'The scaler is never used.', severity: 'high', nodeIds: ['step'], basis: 'inferred', evidence: ['e2'] },
      { id: 'f-shuffle', title: 'Validation shuffled', message: 'm', severity: 'medium', nodeIds: ['load'], basis: 'observed', evidence: ['e1'] },
    ],
    evidence: [
      { id: 'e1', file: 'data.py', line: 3, endLine: 4, quote: 'loader = DataLoader(ds)' },
      { id: 'e2', file: 'train.py', line: 9, endLine: 9, quote: 'opt.step()' },
    ],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py', 'data.py'], limitations: ['Launcher not read.', 'Config not read.'] },
    ...overrides,
  };
}

async function mount(document = doc(), opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  if (opts.bodyClass) ctx.document.body.classList.add(opts.bodyClass);
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 0;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: 798, right: width, bottom: 798 });
  const bridge = recordingBridge(ctx.window, 'vscode', opts.state ? { state: opts.state } : {});
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const resize = (next) => {
    width = next;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  return { ...ctx, root, bridge, app, resize, width: () => width };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);

const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);

/* ── A finding frames the ends of the connections it cites too ─────────────────────── */

test('a finding that cites a step and a connection elsewhere frames both ends of the connection as well', async () => {
  const d = doc();
  d.findings = [{ id: 'f-mixed', title: 'Mixed citation', message: 'm', severity: 'medium', nodeIds: ['load'], edgeIds: ['c3'], basis: 'observed', evidence: ['e1'] }];
  const ctx = await mount(d, { width: 1440 });
  try {
    const canvas = $(ctx, '.mlv-canvas');
    canvas.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: 1080, height: 742, right: 1080, bottom: 742 });
    ctx.app.view.viewport.set({ x: -4000, y: -4000, zoom: 1.6 });
    ctx.app.focusIssue('f-mixed');
    const vp = ctx.app.getState().viewport;
    for (const id of ['load', 'step', 'sched']) {
      const box = ctx.app.view.frameData.boxes.get(id);
      const left = box.x * vp.zoom + vp.x;
      const top = box.y * vp.zoom + vp.y;
      const right = (box.x + box.w) * vp.zoom + vp.x;
      const bottom = (box.y + box.h) * vp.zoom + vp.y;
      assert.ok(left >= 0 && top >= 0 && right <= 1080 && bottom <= 742, `${id} is framed (${left.toFixed(0)}-${right.toFixed(0)}, ${top.toFixed(0)}-${bottom.toFixed(0)} at ${vp.zoom.toFixed(2)})`);
    }
  } finally {
    ctx.app.destroy();
  }
});

test('a hover dims no card; it rings the lit ones. Focus mode still dims and makes the rest inert', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const canvas = $(ctx, '.mlv-canvas');
    const lit = card(ctx, 'load');
    const other = card(ctx, 'step');
    canvas.classList.add('is-tracing');
    lit.classList.add('is-lit');
    for (const prop of ['opacity', 'filter', 'pointer-events']) {
      const won = cascadeWinner(CSS, other, prop);
      assert.ok(!won || !/is-tracing/.test(won.selector), prop + ' is not set by the hover: ' + (won && won.selector));
    }
    assert.match(cascadeWinner(CSS, lit, 'box-shadow').value, /var\(--mlv-text-2\)/);
    canvas.classList.remove('is-tracing');
    canvas.classList.add('is-focusing');
    assert.equal(cascadeWinner(CSS, other, 'opacity').value, '.22');
    assert.equal(cascadeWinner(CSS, other, 'pointer-events').value, 'none');
  } finally {
    ctx.app.destroy();
  }
});
