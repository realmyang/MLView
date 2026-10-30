// Details of the rail's panes in the mounted viewer. A collapsed group's pane lists the findings
// inside the group, its steps and the connections across its edge. Observed findings carry no
// basis mark in the Findings list or the Selection pane; inferred ones carry the canvas tag. The
// handle of the bottom sheet reports no more height than the canvas floor leaves, and after a
// drag collapses the sheet it reopens at the height it had.
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

const click = (ctx, target, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, ...init }));
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);
const rail = (ctx) => $(ctx, '.mlv-rail');
const pane = (ctx) => $(ctx, '.mlv-rail__panel:not([hidden]) .mlv-sel');

/* ── A group's pane says what the group stands for ──────────────────────────────────── */

test('a collapsed group\'s pane lists the findings inside it, its steps, and the connections across its edge', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    ctx.app.view.toggleCollapse('loop');
    // A group's single click waits out the double-click delay (it may be a collapse).
    click(ctx, card(ctx, 'loop'));
    await new Promise((done) => setTimeout(done, 600));
    assert.equal(ctx.app.getState().selection.id, 'loop');
    const p = pane(ctx);
    assert.equal(p.getAttribute('data-kind'), 'group');
    // What the card's badge counts: the high finding on "Optimizer step", inside it.
    const findings = p.querySelector('[data-section="findings"]');
    assert.ok(findings, 'the findings inside the group are listed');
    assert.equal(findings.querySelector('.mlv-rail__headtext').textContent, 'Findings in this group');
    assert.deepEqual(Array.from(findings.querySelectorAll('.mlv-insp__issue'), (b) => b.getAttribute('data-issue-id')), ['f-amp']);
    const members = p.querySelector('[data-section="members"]');
    assert.equal(members.querySelector('.mlv-rail__count').textContent, '2 steps');
    assert.deepEqual(Array.from(members.querySelectorAll('[data-node-id]'), (b) => b.textContent), ['Optimizer step', 'LR schedule']);
    // The connection drawn into the group, with the step inside it; not the one between its steps.
    assert.deepEqual(Array.from(p.querySelectorAll('.mlv-insp__sentences li'), (li) => li.textContent),
      ['Comes from Augment into Optimizer step: batches (unresolved).']);
    assert.match(p.querySelector('.mlv-insp__no-evidence').textContent, /^No source evidence was authored for this group\./);
    // A member is a link.
    members.querySelector('[data-node-id="sched"]').click();
    assert.equal(ctx.app.getState().selection.id, 'sched');
  } finally {
    ctx.app.destroy();
  }
});

/* ── Only the exceptions carry a basis mark in the rail ─────────────────────── */

test('observed findings carry no basis mark in the Findings list or the Selection pane; inferred ones carry the canvas tag', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    ctx.app.setRailTab('issues');
    const row = (id) => $(ctx, `.mlv-issue[data-issue-id="${id}"]`);
    assert.equal(row('f-shuffle').querySelector('[data-basis]'), null, 'no mark on the observed finding');
    assert.doesNotMatch(row('f-shuffle').getAttribute('aria-label'), /basis|observed/);
    const tag = row('f-amp').querySelector('.mlv-basis-tag');
    assert.equal(tag.getAttribute('data-basis'), 'inferred');
    assert.equal(tag.textContent, 'inferred');
    assert.match(row('f-amp').getAttribute('aria-label'), /, inferred, not observed/);
    assert.equal($(ctx, '.mlv-rail [data-basis="observed"]'), null);
    // The finding's own pane.
    ctx.app.focusIssue('f-shuffle');
    assert.equal(pane(ctx).querySelector('.mlv-insp__eyebrow [data-basis]'), null);
    assert.equal($(ctx, '.mlv-rail [data-basis="observed"]'), null);
    ctx.app.focusIssue('f-amp');
    assert.equal(pane(ctx).querySelector('.mlv-insp__eyebrow .mlv-basis-tag').textContent, 'inferred');
    // A step's pane lists its findings the same way.
    ctx.app.select({ kind: 'node', id: 'load' });
    assert.equal($(ctx, '.mlv-rail [data-basis="observed"]'), null);
  } finally {
    ctx.app.destroy();
  }
});

/* ── The sheet's handle reports the height drawn, and a drag collapse keeps the height ─ */

test('the handle never reports more than the canvas floor leaves, and a drag that collapses the sheet keeps its height', async () => {
  const ctx = await mount(doc(), { width: 541 });
  try {
    const body = $(ctx, '.mlv-body');
    body.getBoundingClientRect = () => ({ x: 0, y: 36, top: 36, left: 0, width: 541, height: 740, right: 541, bottom: 776 });
    click(ctx, card(ctx, 'load'));
    const grip = $(ctx, '.mlv-rail__grip');
    assert.equal(grip.getAttribute('aria-valuenow'), '47');
    for (let i = 0; i < 10; i++) keydown(ctx, grip, 'ArrowUp');
    // The stylesheet keeps min(240px, 45%) = 240 px of 740 for the canvas: the sheet is 500 px.
    assert.equal(grip.getAttribute('aria-valuenow'), '68', 'what the stylesheet draws (500 of 740 px)');
    assert.equal(grip.getAttribute('aria-valuemax'), '68');
    assert.ok(ctx.app.sheetFraction <= 500 / 740 + 1e-9);
    // Back to the default, then drag the handle down past the collapse line.
    ctx.app.setSheetFraction(0.47);
    const pointer = (type, y) => {
      const ev = new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, clientX: 270, clientY: y });
      (type === 'pointerdown' ? grip : ctx.document).dispatchEvent(ev);
    };
    pointer('pointerdown', 430);
    for (const y of [480, 560, 640, 720, 770]) pointer('pointermove', y);
    pointer('pointerup', 770);
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false', 'the drag collapsed the sheet');
    $(ctx, '.mlv-rail__chevron').click();
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true');
    assert.equal(grip.getAttribute('aria-valuenow'), '47', 'it reopens at the height it had before the drag');
  } finally {
    ctx.app.destroy();
  }
});
