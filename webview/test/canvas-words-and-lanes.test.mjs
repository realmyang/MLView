// The words and the lanes of the diagram in the mounted viewer. Announcements and accessible
// names say steps, connections and F labels. A lane names the total of its findings after the
// numbers by severity, and its heading is numbered, in the text colour at the title size, on a
// plate. A card with a detail shows two lines of it in place of its file:line row. The Outline
// and the exported SVG carry the same lane words, and the SVG the same card face.
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
const keydown = (ctx, target, key, init = {}) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};

const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);

/* ── What a screen reader hears uses the diagram's own words ──────────────────────── */

test('announcements and names say steps, connections and F labels, never nodes and edges', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    assert.equal(ctx.app.liveEl.textContent, 'Workflow loaded: 5 steps, 3 connections, 2 findings (1 high severity).');
    ctx.app.view.toggleCollapse('loop');
    assert.equal(ctx.app.liveEl.textContent, 'Group Epoch loop collapsed, 2 steps hidden.');
    assert.match(card(ctx, 'loop').getAttribute('aria-label'), /2 nested steps/);
    ctx.app.view.toggleCollapse('loop');
    keydown(ctx, ctx.app.view.canvasEl, 'n');
    assert.equal(ctx.app.liveEl.textContent, 'Finding F1 (f-amp), high severity: Loss scaling skipped');
    const hit = $(ctx, '.mlv-edge[data-edge-id="c1"] .mlv-edge__hit');
    assert.match(hit.getAttribute('aria-label'), /^connection labelled images, flows from Load batches to Augment/);
    // No accessible name or announcement calls a step a node or a connection an edge.
    const names = Array.from(ctx.document.querySelectorAll('[aria-label]'), (e) => e.getAttribute('aria-label')).join(' | ');
    assert.doesNotMatch(names + ' | ' + ctx.app.liveEl.textContent, /\b(nodes?|edges?)\b/i);
  } finally {
    ctx.app.destroy();
  }
  const none = await mount(doc({ findings: [] }), { width: 1440 });
  try {
    assert.equal(none.app.liveEl.textContent, 'Workflow loaded: 5 steps, 3 connections, 0 findings.', 'no "0 high severity"');
  } finally {
    none.app.destroy();
  }
});

/** The SVG the ... menu's "Export SVG" hands the host. */
function exportedSvg(ctx) {
  $(ctx, '.mlv-btn--more').click();
  $(ctx, '[data-export-action="svg"]').click();
  const frame = ctx.bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  return Buffer.from(frame.base64, 'base64').toString('utf8');
}

/** One card's markup in the exported SVG: from its group to the next card's. */
function svgCard(svg, id) {
  const at = svg.indexOf('data-node-id="' + id + '"');
  assert.ok(at >= 0, id + ' is in the export');
  const next = svg.indexOf('data-node-id="', at + 1);
  return svg.slice(at, next < 0 ? undefined : next);
}

test('a lane with two severities names their total after the numbers, on the canvas, in the Outline and in the SVG', async () => {
  const d = doc();
  d.findings.push({ id: 'f-sched', title: 'Schedule stepped per batch', message: 'm', severity: 'medium', nodeIds: ['sched'], basis: 'observed', evidence: ['e2'] });
  const ctx = await mount(d, { width: 1440 });
  try {
    const lane = $(ctx, '.mlv-lane[data-lane-id="fit"]');
    const unit = lane.querySelector('.mlv-lane__unit');
    // The phrase carries the total: "1 1 findings touch this phase" would read as one finding.
    assert.equal(unit.textContent, '2 findings touch this phase');
    const parts = Array.from(lane.querySelectorAll('.mlv-lane__header > *'));
    assert.ok(parts.indexOf(unit) > parts.indexOf(lane.querySelector('.mlv-cluster')), 'after the per-severity numbers');
    assert.equal($(ctx, '.mlv-lane[data-lane-id="data"] .mlv-lane__unit').textContent, '1 finding touches this phase');
    ctx.app.setRailTab('outline');
    const row = $(ctx, '[data-outline-lane="fit"] .mlv-outline__row--lane');
    assert.equal(row.querySelector('.mlv-outline__phasecount').textContent, '2 findings touch this phase');
    const svg = exportedSvg(ctx);
    assert.match(svg, />· 2 findings touch this phase</);
    assert.match(svg, />· 1 finding touches this phase</);
    assert.doesNotMatch(svg, />findings touch this phase</, 'no phrase without its number');
  } finally {
    ctx.app.destroy();
  }
});

test('a card with a detail shows two lines of it in place of the file:line row; one without keeps the row', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const load = card(ctx, 'load');
    const sub = load.querySelector('.mlv-node__sub');
    assert.equal(sub.getAttribute('data-lines'), '2');
    assert.equal(sub.textContent, 'Reads CIFAR-10 with batch size 64.');
    assert.equal(load.querySelector('.mlv-node__loc'), null, 'the place is in the name and the Selection pane');
    assert.match(load.getAttribute('aria-label'), /data\.py line 3/);
    assert.equal(cascadeWinner(CSS, sub, '-webkit-line-clamp').value, '2');
    // A card without a detail keeps its one-line sub and its file:line row.
    const aug = card(ctx, 'aug');
    assert.equal(aug.querySelector('.mlv-node__sub').hasAttribute('data-lines'), false);
    assert.equal(aug.querySelector('.mlv-node__loc').textContent, 'data.py:3');
    // The SVG export draws the same face.
    const svg = exportedSvg(ctx);
    assert.doesNotMatch(svgCard(svg, 'load'), />data\.py:3</);
    const lines = [...svgCard(svg, 'load').matchAll(/<text [^>]*font-size="11"[^>]*>([^<]*)</g)].map((m) => m[1]);
    assert.equal(lines.length, 2, 'two detail lines: ' + lines.join(' | '));
    assert.equal(lines.join(' '), 'Reads CIFAR-10 with batch size 64.');
    assert.match(svgCard(svg, 'aug'), />data\.py:3</);
  } finally {
    ctx.app.destroy();
  }
});

test('a lane heading is numbered, in the text colour at the title size, on a plate; the Outline numbers it too', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const header = $(ctx, '.mlv-lane[data-lane-id="fit"] .mlv-lane__header');
    assert.equal(header.querySelector('.mlv-lane__num').textContent, '2');
    const label = header.querySelector('.mlv-lane__label');
    assert.equal(label.textContent, 'Fit');
    assert.equal(cascadeWinner(CSS, label, 'color').value, 'var(--mlv-text)');
    assert.equal(cascadeWinner(CSS, label, 'font-size').value, 'var(--mlv-fs-13)');
    const caps = cascadeWinner(CSS, label, 'text-transform');
    assert.ok(!caps || caps.value !== 'uppercase', 'sentence case, as authored');
    assert.match(cascadeWinner(CSS, header, 'background').value, /color-mix\(in srgb, ?var\(--mlv-text\) 5%, ?var\(--mlv-surface\)\)/);
    ctx.app.setRailTab('outline');
    const row = $(ctx, '[data-outline-lane="fit"] .mlv-outline__row--lane');
    assert.equal(row.querySelector('.mlv-outline__label').textContent, '2 · Fit');
    const count = row.querySelector('.mlv-outline__phasecount');
    assert.equal(cascadeWinner(CSS, count, 'flex').value, '1 0 100%', 'on its own line under the name');
    assert.equal(cascadeWinner(CSS, count, 'text-transform').value, 'none');
    const svg = exportedSvg(ctx);
    assert.match(svg, /fill-opacity="0\.05"/, 'the export draws the plate');
    assert.doesNotMatch(svg, />FIT</, 'and no upper-case label');
  } finally {
    ctx.app.destroy();
  }
});
