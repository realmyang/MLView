// What a selection shows in the mounted viewer. A click on a step shows its claim in the
// Selection tab even while the Findings list is on show; with the list on show, `n` walks the
// findings in it. A search hit for a step shows its claim, and in a narrow panel it opens the
// collapsed sheet. A claim read in the docked rail stays open when the panel narrows into the
// sheet.
//
// The shipped stylesheet is injected into the jsdom page. The document is a small one written
// here, mounted in the built bundle.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

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
const keydown = (ctx, target, key, init = {}) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};

/* ── What a selection shows ─────────────────────────────────────────── */

const click = (ctx, target, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, ...init }));
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);
const tab = (ctx) => ctx.app.getState().railTab;
const rail = (ctx) => $(ctx, '.mlv-rail');
const pane = (ctx) => $(ctx, '.mlv-rail__panel:not([hidden]) .mlv-sel');

test('a canvas click on a step shows its claim even when the Findings list was on show (1440 docked and 541 sheet)', async () => {
  for (const width of [1440, 541]) {
    const ctx = await mount(doc(), { width });
    try {
      ctx.app.showRailTab('issues');
      assert.equal(tab(ctx), 'issues');
      if (width === 541) assert.equal(rail(ctx).getAttribute('data-expanded'), 'true', 'precondition: the sheet is open on Findings');
      click(ctx, card(ctx, 'aug'));
      assert.equal(tab(ctx), 'inspector', `${width}: the Selection tab shows the step`);
      assert.equal(pane(ctx).querySelector('.mlv-insp__title').textContent, 'Augment');
      assert.ok(pane(ctx).querySelector('.mlv-quote__open'), 'with its quotes and Open');
      // `n` walks the findings: the Findings list on show keeps its place and expands each one.
      ctx.app.showRailTab('issues');
      keydown(ctx, ctx.app.view.canvasEl, 'n');
      assert.equal(tab(ctx), 'issues');
      assert.ok($(ctx, '.mlv-issue__detail'), 'the walked finding is expanded in the list');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('a search hit for a step shows its claim: the Selection tab at 1440, and the collapsed sheet opens at 541 and 900', async () => {
  const wide = await mount(doc(), { width: 1440 });
  try {
    wide.app.setRailTab('issues');
    wide.app.activateHit({ kind: 'node', id: 'step', label: 'Optimizer step' });
    assert.equal(wide.app.getState().selection.id, 'step');
    assert.equal(tab(wide), 'inspector');
    assert.equal(pane(wide).querySelector('.mlv-insp__title').textContent, 'Optimizer step');
  } finally {
    wide.app.destroy();
  }
  for (const width of [541, 900]) {
    const ctx = await mount(doc(), { width });
    try {
      assert.equal(rail(ctx).getAttribute('data-expanded'), 'false', 'precondition: the sheet is collapsed');
      ctx.app.activateHit({ kind: 'node', id: 'step', label: 'Optimizer step' });
      assert.equal(rail(ctx).getAttribute('data-expanded'), 'true', `${width}: the sheet opens on the hit`);
      assert.equal(tab(ctx), 'inspector');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('a claim read in the docked rail stays open when the panel narrows into the sheet (Enter opens the source beside)', async () => {
  const ctx = await mount(doc(), { width: 1382 });
  try {
    assert.equal(rail(ctx).getAttribute('data-mode'), 'docked');
    click(ctx, card(ctx, 'load'));
    keydown(ctx, ctx.app.view.canvasEl, 'Enter');
    assert.ok(ctx.bridge.posted.some((m) => m.type === 'openLocation'), 'precondition: Enter asked to open the source');
    // The file opens beside the panel, which the test stands in for by halving the panel.
    ctx.resize(691);
    assert.equal(rail(ctx).getAttribute('data-mode'), 'sheet');
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true', 'the claim stays on screen');
    assert.equal(tab(ctx), 'inspector');
    assert.equal(pane(ctx).querySelector('.mlv-insp__title').textContent, 'Load batches');
  } finally {
    ctx.app.destroy();
  }
  // A rail nobody used still starts the sheet as its tab strip.
  const idle = await mount(doc(), { width: 1382 });
  try {
    idle.resize(691);
    assert.equal(rail(idle).getAttribute('data-expanded'), 'false');
  } finally {
    idle.app.destroy();
  }
});
