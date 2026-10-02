// Viewer M2, steps 5 and 9: the claim-first Selection pane, the About tab and the bottom sheet.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies the real
// rules (screen media only). jsdom performs no layout: the panel width is a stubbed
// `getBoundingClientRect` on the root, and the canvas box above the sheet is stubbed the way the
// shipped CSS stacks them. The real-Chromium boxes at 1440, 900 and 541 px are measured with the
// screenshot harness outside the gate. None of this is a live VS Code check, and none of it says
// whether a reader understands the diagram.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sha256 = (text) => createHash('sha256').update(text).digest('hex');

const SUMMARY = 'Data: CIFAR-10 is read from disk and normalised. Model: a ResNet-18 from torchvision, with a new head. Training: Adam for 10 epochs under mixed precision.';
const CONFIG = 'Run with lr=3e-4, batch_size=64 and amp=true (see config.yaml).';

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Fine-tune a classifier',
    producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r1' },
    request: { question: 'How is the classifier trained?', scope: 'train.py and data.py', entrypoints: ['train.py'], configuration: CONFIG },
    phases: [{ id: 'ph-data', label: 'Data' }, { id: 'ph-fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'ph-data', kind: 'dataset', basis: 'observed', evidence: ['e1', 'e3'], detail: 'Reads CIFAR-10 with batch size 64. Shuffles every epoch.' },
      { id: 'aug', label: 'Augment', phase: 'ph-data', kind: 'transform', basis: 'inferred', evidence: ['e1'] },
      { id: 'loop', label: 'Epoch loop', phase: 'ph-fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'ph-fit', parent: 'loop', kind: 'optimizer', basis: 'observed', evidence: ['e2'] },
      { id: 'sched', label: 'LR schedule', phase: 'ph-fit', parent: 'loop', kind: 'scheduler', basis: 'unresolved', evidence: [] },
    ],
    edges: [
      { id: 'c1', source: 'load', target: 'aug', label: 'images', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'c2', source: 'aug', target: 'step', label: 'batches', kind: 'data', basis: 'inferred', evidence: ['e1', 'e2'] },
      { id: 'c3', source: 'step', target: 'sched', label: 'optimizer handle', kind: 'state', basis: 'unresolved', evidence: [] },
    ],
    findings: [
      { id: 'f-amp', title: 'Loss scaling skipped', message: 'The scaler is built but never used. Gradients may underflow.', severity: 'high',
        nodeIds: ['load', 'step', 'sched'], basis: 'inferred', evidence: ['e2'], counterEvidence: ['e1'], suggestion: 'Call scaler.scale(loss).backward().' },
      { id: 'f-edge', title: 'Batches cross an unchecked cast', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c2'], basis: 'observed', evidence: ['e1'] },
    ],
    evidence: [
      { id: 'e1', file: 'data.py', line: 3, endLine: 4, quote: 'loader = DataLoader(ds,\n    batch_size=64)' },
      { id: 'e2', file: 'train.py', line: 9, endLine: 9, quote: 'opt.step()' },
      { id: 'e3', file: 'notes.py', line: 1, endLine: 1, quote: 'SEED = 0' },
    ],
    coverage: { status: 'scoped', summary: SUMMARY, inspectedFiles: ['train.py', 'data.py'], limitations: ['Launcher not read.', 'Config file not read.'] },
    verification: { publishedAt: '2026-10-01T00:00:00Z', files: { 'data.py': sha256('a'), 'train.py': sha256('b') } },
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
  return { ...ctx, root, bridge, app, resize };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const keydown = (ctx, target, key, init = {}) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const click = (ctx, target, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, ...init }));
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);
const pane = (ctx) => $(ctx, '.mlv-rail__panel:not([hidden]) .mlv-sel');
const tab = (ctx) => ctx.app.getState().railTab;
const rail = (ctx) => $(ctx, '.mlv-rail');

/** Shown to a reader: neither it nor an ancestor is `hidden`, `display: none` or `visibility: hidden`. */
function visible(ctx, element) {
  if (!element) return false;
  for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
    if (node.hidden) return false;
    const style = ctx.window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
  }
  return true;
}

/** The order of `parts` inside `container`, as document positions: ascending when in that order. */
function inOrder(container, parts) {
  const all = Array.from(container.querySelectorAll('*'));
  const at = parts.map((part) => all.indexOf(part));
  return at.every((value, i) => value >= 0 && (i === 0 || value > at[i - 1]));
}

/** Stub the canvas box: the body's height less the sheet (32 px collapsed, 47 % open). */
function canvasOverSheet(ctx, w, bodyH) {
  const canvas = $(ctx, '.mlv-canvas');
  canvas.getBoundingClientRect = () => {
    const r = rail(ctx);
    const sheet = r.getAttribute('data-mode') !== 'sheet' ? 0 : r.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * 0.47) : 32;
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: bodyH - sheet, right: w, bottom: bodyH - sheet };
  };
  return () => canvas.getBoundingClientRect();
}

function screenBox(ctx, id) {
  const vp = ctx.app.getState().viewport;
  const box = ctx.app.view.frameData.boxes.get(id);
  return { left: box.x * vp.zoom + vp.x, right: (box.x + box.w) * vp.zoom + vp.x, top: box.y * vp.zoom + vp.y, bottom: (box.y + box.h) * vp.zoom + vp.y };
}

/* ── tabs ─────────────────────────────────────────────────────────────── */

test('a new revision opens on About; the reader\'s tab is then kept, saved, and restored for that revision only', async () => {
  let ctx = await mount();
  try {
    assert.deepEqual($$(ctx, '.mlv-rail__tab').map((b) => b.textContent), ['About', 'Findings (2)', 'Selection', 'Outline']);
    assert.equal(tab(ctx), 'about');
    assert.ok(visible(ctx, $(ctx, '.mlv-about')));
    ctx.app.setRailTab('outline');
    assert.equal(ctx.app.getState().railTab, 'outline', 'the tab is saved with the view state');
    assert.equal(ctx.app.getState().workflowRevision, 'r1', 'for this revision');
  } finally {
    ctx.app.destroy();
  }
  // A remount of the same revision restores the tab; another revision opens on About.
  ctx = await mount(doc(), { state: { workflowRevision: 'r1', railTab: 'outline' } });
  assert.equal(tab(ctx), 'outline', 'the same revision keeps the reader\'s tab');
  ctx.app.destroy();
  ctx = await mount(doc(), { state: { workflowRevision: 'r0', railTab: 'outline' } });
  assert.equal(tab(ctx), 'about', 'a tab saved for another revision is not restored');
  ctx.app.destroy();
  ctx = await mount(doc(), { state: { workflowRevision: 'r1', railTab: 'inspector-v2' } });
  assert.equal(tab(ctx), 'about', 'a tab this viewer does not have is ignored');
  ctx.app.destroy();
});

test('a selection shows its claim in Selection, unless it is made from the Findings list or the Outline on screen', async () => {
  const ctx = await mount();
  try {
    click(ctx, card(ctx, 'load'));
    assert.equal(tab(ctx), 'inspector', 'from About, a click shows the claim');
    assert.match(ctx.app.liveEl.textContent, /^Selected .*Load batches/, 'and says what was chosen');
    // Viewer M2 review (M2-INT-1): a canvas click shows the claim whichever tab was on show, as in
    // viewer M1; a step with no finding has no row to mark in the Findings list.
    ctx.app.setRailTab('issues');
    click(ctx, card(ctx, 'aug'));
    assert.equal(tab(ctx), 'inspector', 'a canvas click leaves the Findings list for the claim');
    assert.equal(ctx.app.getState().selection.id, 'aug');
    assert.match(ctx.app.liveEl.textContent, /^Selected .*Augment/);
    // A row of the Findings list keeps the list, with the finding expanded in it.
    ctx.app.setRailTab('issues');
    click(ctx, $(ctx, '.mlv-issue[data-issue-id="f-amp"]'));
    assert.equal(tab(ctx), 'issues', 'the Findings list keeps its place');
    assert.ok($(ctx, '[data-issue-detail="f-amp"]'), 'where the finding is expanded');
    // So does a row of the Outline, where the selection is marked.
    ctx.app.setRailTab('outline');
    click(ctx, $(ctx, '[data-outline-id="step"] .mlv-outline__row'));
    assert.equal(tab(ctx), 'outline', 'so does the Outline');
    assert.equal(ctx.app.getState().selection.id, 'step');
    assert.ok($(ctx, '[data-outline-id="step"] .mlv-outline__row.is-selected'), 'where the selection is marked');
    click(ctx, card(ctx, 'load'));
    assert.equal(tab(ctx), 'inspector', 'a canvas click from the Outline shows the claim too');
    // A list that is not on screen is not being walked: `n` with the rail hidden shows the claim.
    ctx.app.setRailTab('issues');
    ctx.app.toggleRail();
    ctx.app.focusIssue('f-amp', { fromList: 'issues' });
    assert.equal(tab(ctx), 'inspector');
    assert.equal(rail(ctx).hidden, false, 'a finding opens the rail');
  } finally {
    ctx.app.destroy();
  }
  // In a collapsed sheet the Findings tab is not on screen either: the sheet opens on Selection.
  const narrow = await mount(doc(), { width: 541 });
  try {
    narrow.app.setRailTab('issues');
    narrow.app.collapseSheet(false);
    click(narrow, card(narrow, 'load'));
    assert.equal(rail(narrow).getAttribute('data-expanded'), 'true');
    assert.equal(tab(narrow), 'inspector');
  } finally {
    narrow.app.destroy();
  }
});

/* ── About ────────────────────────────────────────────────────────────── */

test('About: the summary is split at its own run-in heads only when it has three; k=v tokens are monospace', async () => {
  let ctx = await mount();
  try {
    const traced = $(ctx, '.mlv-about [data-about="traced"]');
    assert.equal(traced.getAttribute('data-paragraphs'), '3');
    assert.deepEqual(Array.from(traced.querySelectorAll('.mlv-about__lead'), (b) => b.textContent), ['Data:', 'Model:', 'Training:']);
    const words = Array.from(traced.querySelectorAll('.mlv-about__para'), (p) => p.textContent).join(' ');
    assert.equal(words, SUMMARY, 'every word of the summary, in order, nothing added');
    const config = $(ctx, '.mlv-about .mlv-about__config');
    assert.equal(config.textContent, CONFIG, 'the configuration verbatim');
    assert.deepEqual(Array.from(config.querySelectorAll('code.mlv-about__kv'), (c) => c.textContent), ['lr=3e-4', 'batch_size=64', 'amp=true']);
    assert.match(ctx.window.getComputedStyle(config.querySelector('code')).fontFamily, /mono/i);
    // Scope and entrypoints, coverage in plain words, and the limitations listed once.
    assert.match($(ctx, '.mlv-about [data-about="scope"]').textContent, /train\.py and data\.pyEntrypoints: train\.py/);
    assert.match($(ctx, '.mlv-about__status').textContent, /^Scoped: the assistant lists no remaining work within the stated scope\./);
    for (const limitation of ['Launcher not read.', 'Config file not read.']) {
      assert.equal($$(ctx, 'li').filter((li) => li.textContent === limitation).length, 1, limitation + ' is listed once');
    }
  } finally {
    ctx.app.destroy();
  }
  // Two heads are not a structure: the summary stays one paragraph, as written.
  ctx = await mount(doc({ coverage: { status: 'partial', summary: 'Data: read from disk. Model: a ResNet.', inspectedFiles: ['train.py'], limitations: [] } }));
  try {
    const traced = $(ctx, '.mlv-about [data-about="traced"]');
    assert.equal(traced.getAttribute('data-paragraphs'), '1');
    assert.equal(traced.querySelector('.mlv-about__lead'), null);
    assert.equal(traced.querySelector('.mlv-about__para').textContent, 'Data: read from disk. Model: a ResNet.');
    assert.equal($(ctx, '.mlv-about [data-about="coverage"] .mlv-about__note').textContent, 'The assistant listed no coverage limitations.');
  } finally {
    ctx.app.destroy();
  }
});

test('About lists every cited file with its freshness: muted when unchanged or unchecked, a warning only when stale', async () => {
  const ctx = await mount();
  try {
    const badge = (file) => $(ctx, `.mlv-about__file[data-file="${file}"] .mlv-quote__fresh`);
    assert.deepEqual($$(ctx, '.mlv-about__file').map((li) => li.getAttribute('data-file')), ['data.py', 'train.py', 'notes.py']);
    assert.equal($(ctx, '.mlv-about [data-about="files"] .mlv-rail__count').textContent, '3 files');
    assert.equal(badge('data.py').textContent, 'unchanged');
    assert.equal(badge('data.py').getAttribute('data-fresh'), 'unchanged');
    assert.equal(badge('notes.py').textContent, 'not checked', 'no published hash for this file');
    for (const file of ['data.py', 'notes.py']) {
      assert.ok(badge(file).classList.contains('is-muted'));
      assert.equal(badge(file).querySelector('svg'), null, 'no icon for a state that is not a problem');
    }
    // Muted is the secondary text colour, the same as any note: never a success colour.
    const note = $(ctx, '.mlv-about [data-about="files"] .mlv-about__note');
    assert.equal(ctx.window.getComputedStyle(badge('data.py')).color, ctx.window.getComputedStyle(note).color);
    assert.match(note.textContent, /It does not mean they support the claims\./);
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    assert.equal(badge('data.py').getAttribute('data-fresh'), 'stale');
    assert.ok(badge('data.py').querySelector('svg'), 'a problem carries an icon, not colour alone');
    assert.equal(badge('data.py').textContent, 'changed since publishing');
    assert.equal(badge('train.py').textContent, 'unchanged');
    // Provenance, and what MLView checks.
    assert.equal($(ctx, '.mlv-about [data-about="provenance"] .mlv-about__meta').textContent,
      'claude-code · fixture-model · revision r1 · published 2026-10-01T00:00:00Z');
    assert.equal($(ctx, '.mlv-about__trust').textContent, 'Model-authored; MLView checks citations, not the interpretation.');
  } finally {
    ctx.app.destroy();
  }
});

/* ── the Selection pane ───────────────────────────────────────────────── */

test('a step\'s pane: the parent group in the eyebrow, numbered quotes with line numbers, freshness and Open', async () => {
  const ctx = await mount();
  try {
    click(ctx, card(ctx, 'step'));
    const p = pane(ctx);
    assert.equal(p.querySelector('.mlv-insp__eyebrow').textContent, '2 · Fit · optimizer · in Epoch loop');
    // An exception's basis: its tag and one sentence. This step is observed: none.
    assert.equal(p.querySelector('.mlv-insp__basis'), null);
    click(ctx, card(ctx, 'load'));
    const quotes = $$(ctx, '.mlv-rail__panel:not([hidden]) .mlv-quote');
    assert.equal(quotes.length, 2);
    assert.deepEqual(quotes.map((q) => q.querySelector('.mlv-quote__num').textContent), ['1', '2']);
    assert.deepEqual(quotes.map((q) => q.querySelector('.mlv-quote__loc').textContent), ['data.py, lines 3–4', 'notes.py, line 1']);
    // The quote verbatim, one row per line, each with its source line number.
    assert.deepEqual(Array.from(quotes[0].querySelectorAll('.mlv-quote__ln'), (n) => n.textContent), ['3', '4']);
    assert.deepEqual(Array.from(quotes[0].querySelectorAll('.mlv-quote__code'), (c) => c.textContent), ['loader = DataLoader(ds,', '    batch_size=64)']);
    assert.deepEqual(quotes.map((q) => q.querySelector('.mlv-quote__fresh').textContent), ['unchanged', 'not checked']);
    assert.ok(quotes.every((q) => q.querySelector('.mlv-quote__fresh').classList.contains('is-muted')));
    const open = quotes[0].querySelector('.mlv-quote__open');
    assert.equal(open.textContent, 'Open');
    assert.equal(open.getAttribute('aria-label'), 'Open data.py:3');
    open.click();
    const posted = ctx.bridge.posted.findLast((m) => m.type === 'openLocation');
    assert.equal(posted.evidenceId, 'e1');
    assert.equal(posted.focus, undefined, 'Open keeps the focus here');
    assert.equal(pane(ctx).querySelector('[data-section="quotes"] .mlv-rail__count').textContent, '2 quotes');
    // "Comes from" and "Feeds" as sentences; this step only feeds.
    assert.deepEqual(Array.from(pane(ctx).querySelectorAll('.mlv-insp__sentences li'), (li) => li.textContent), ['Feeds Augment: images.']);
    pane(ctx).querySelector('.mlv-insp__flow-step[data-node-id="aug"]').click();
    assert.equal(ctx.app.getState().selection.id, 'aug', 'a step named in a sentence is a link');
    assert.deepEqual(Array.from(pane(ctx).querySelectorAll('.mlv-insp__sentences li'), (li) => li.textContent),
      ['Comes from Load batches: images.', 'Feeds Optimizer step: batches (inferred, not observed).']);
  } finally {
    ctx.app.destroy();
  }
});

test('a connection\'s pane: its kind in words, label, from → to, basis, findings, then quotes', async () => {
  const ctx = await mount();
  try {
    ctx.app.select({ kind: 'edge', id: 'c2' });
    const p = pane(ctx);
    assert.equal(p.getAttribute('data-kind'), 'connection');
    const parts = ['.mlv-insp__eyebrow', '.mlv-insp__title', '.mlv-insp__ends', '.mlv-insp__basis', '[data-section="findings"]', '[data-section="quotes"]', '.mlv-insp__actions'].map((s) => p.querySelector(s));
    assert.ok(parts.every(Boolean));
    assert.ok(inOrder(p, parts), 'eyebrow, title, from → to, basis, findings, quotes, actions');
    assert.equal(parts[0].textContent, 'Connection · data');
    assert.equal(parts[1].textContent, 'batches');
    assert.equal(parts[2].textContent, 'Augment → Optimizer step');
    assert.match(parts[3].textContent, /^inferred Reasoned from the cited code/);
    assert.equal(p.querySelector('[data-section="findings"] .mlv-rail__headtext').textContent, 'Findings on this connection');
    assert.deepEqual(Array.from(p.querySelectorAll('.mlv-quote__open'), (b) => b.getAttribute('data-evidence-id')), ['e1', 'e2']);
    // Each end is a link to its step.
    parts[2].querySelector('[data-node-id="step"]').click();
    assert.equal(ctx.app.getState().selection.id, 'step');
  } finally {
    ctx.app.destroy();
  }
});

test('a finding\'s pane: severity, F-label and id, title, description, What to change, cited steps, quotes', async () => {
  const ctx = await mount();
  try {
    ctx.app.focusIssue('f-amp');
    const p = pane(ctx);
    assert.equal(p.getAttribute('data-kind'), 'finding');
    const eyebrow = p.querySelector('.mlv-insp__eyebrow');
    assert.equal(eyebrow.querySelector('.mlv-insp__severity').textContent, 'High finding');
    assert.equal(eyebrow.querySelector('.mlv-insp__short').textContent, 'F1');
    assert.equal(eyebrow.querySelector('.mlv-mono').textContent, 'f-amp', 'the real id beside the label');
    const parts = [eyebrow, p.querySelector('.mlv-insp__title'), p.querySelector('.mlv-insp__message'), p.querySelector('.mlv-insp__fix'),
      p.querySelector('[data-section="cited"]'), p.querySelector('[data-section="quotes"]')];
    assert.ok(parts.every(Boolean));
    assert.ok(inOrder(p, parts), 'severity, title, description, What to change, cited steps, quotes');
    assert.equal(parts[1].textContent, 'Loss scaling skipped');
    assert.equal(parts[2].textContent, 'The scaler is built but never used. Gradients may underflow.');
    assert.deepEqual(Array.from(parts[4].querySelectorAll('[data-node-id]'), (b) => b.textContent), ['Load batches', 'Optimizer step', 'LR schedule']);
    assert.equal(parts[4].querySelector('.mlv-rail__count').textContent, '3 steps');
    assert.deepEqual(Array.from(parts[5].querySelectorAll('.mlv-quote__role'), (r) => r.textContent), ['Supporting evidence', 'Counter-evidence']);
    assert.deepEqual(Array.from(p.querySelectorAll('.mlv-insp__actions button'), (b) => b.textContent), ['Challenge this claim', 'Refine…']);
    // A finding with no cited step names its connection instead.
    ctx.app.focusIssue('f-edge');
    assert.deepEqual(Array.from(pane(ctx).querySelectorAll('[data-section="cited"] [data-edge-id]'), (b) => b.textContent), ['batches']);
  } finally {
    ctx.app.destroy();
  }
});

test('selecting a finding frames every step it cites, not only the first', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const area = canvasOverSheet(ctx, 1080, 742);
    ctx.app.view.viewport.set({ x: -4000, y: -4000, zoom: 1.6 });
    ctx.app.focusIssue('f-amp');
    const box = area();
    for (const id of ['load', 'step', 'sched']) {
      const b = screenBox(ctx, id);
      assert.ok(b.left >= 0 && b.top >= 0 && b.right <= box.width && b.bottom <= box.height, `${id} is framed (${b.left.toFixed(0)}-${b.right.toFixed(0)}, ${b.top.toFixed(0)}-${b.bottom.toFixed(0)})`);
    }
    const zoom = ctx.app.getState().viewport.zoom;
    assert.ok(zoom >= 0.45 && zoom <= 1.6, `the zoom stays readable (${zoom})`);
    // At 541 px the sheet opens and the cards are framed in the canvas above it.
    ctx.resize(541);
    const narrow = canvasOverSheet(ctx, 541, 742);
    ctx.app.clearSelection();
    ctx.app.collapseSheet(false);
    ctx.app.view.viewport.set({ x: -4000, y: -4000, zoom: 0.2 });
    ctx.app.focusIssue('f-amp');
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true');
    const c = narrow();
    const inView = (id) => {
      const b = screenBox(ctx, id);
      return b.left >= 0 && b.top >= 0 && b.right <= c.width && b.bottom <= c.height;
    };
    const narrowZoom = ctx.app.getState().viewport.zoom;
    if (!['load', 'step', 'sched'].every(inView)) {
      // Too wide for 541 px even at the 0.45 floor: the floor, centred on the first cited card.
      assert.equal(narrowZoom, 0.45);
    }
    assert.ok(inView('load'), 'the first cited card is in view above the sheet');
    assert.ok(narrowZoom >= 0.45);
  } finally {
    ctx.app.destroy();
  }
});

/* ── the bottom sheet at 1440, 900 and 541 px ─────────────────────────── */

test('1440 px docks the rail; 900 and 541 px use the sheet, with two columns at 900 and one at 541', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    click(ctx, card(ctx, 'load'));
    assert.equal(rail(ctx).getAttribute('data-mode'), 'docked');
    assert.equal(pane(ctx).getAttribute('data-columns'), '1', 'the docked rail is one column');
    assert.ok(visible(ctx, $(ctx, '.mlv-rail__grip')));
    assert.equal(visible(ctx, $(ctx, '.mlv-rail__chevron')), false, 'no chevron while docked');

    ctx.resize(900);
    assert.equal(rail(ctx).getAttribute('data-mode'), 'sheet');
    assert.equal($(ctx, '.mlv-body').getAttribute('data-rail'), 'sheet');
    // The reader was using the docked rail (it showed the claim), so the sheet opens (viewer M2
    // review, M2R-5: this used to call toggleRail() when it did not, which hid the bug).
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true');
    const two = pane(ctx);
    assert.equal(two.getAttribute('data-columns'), '2');
    assert.equal(ctx.window.getComputedStyle(two).display, 'grid');
    const claim = two.querySelector('.mlv-sel__col--claim');
    const evidence = two.querySelector('.mlv-sel__col--evidence');
    for (const s of ['.mlv-insp__eyebrow', '.mlv-insp__title', '.mlv-insp__detail', '[data-section="findings"]', '[data-section="connections"]']) assert.ok(claim.querySelector(s), s + ' on the left');
    for (const s of ['[data-section="quotes"]', '.mlv-insp__actions', '.mlv-insp__limits']) assert.ok(evidence.querySelector(s), s + ' on the right');

    ctx.resize(541);
    assert.equal(rail(ctx).getAttribute('data-mode'), 'sheet');
    assert.equal(pane(ctx).getAttribute('data-columns'), '1', 'one column below 620 px');
    assert.equal(pane(ctx).querySelector('.mlv-sel__col'), null);
    // The sheet's chrome: a handle with its value, a chevron, both named.
    const grip = $(ctx, '.mlv-rail__grip');
    assert.equal(grip.getAttribute('role'), 'separator');
    assert.equal(grip.getAttribute('aria-orientation'), 'horizontal');
    assert.equal(grip.getAttribute('aria-label'), 'Resize the bottom panel');
    assert.equal(grip.getAttribute('aria-valuenow'), '47');
    keydown(ctx, grip, 'ArrowUp');
    assert.equal(grip.getAttribute('aria-valuenow'), '52', 'the arrow keys move the handle');
    assert.equal(rail(ctx).style.getPropertyValue('--mlv-sheet-fraction'), '0.52');
    const chevron = $(ctx, '.mlv-rail__chevron');
    assert.ok(visible(ctx, chevron));
    assert.equal(chevron.getAttribute('aria-expanded'), 'true');
    assert.equal(chevron.getAttribute('aria-label'), 'Collapse the bottom panel (Escape)');
    chevron.click();
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false');
    assert.equal(chevron.getAttribute('aria-expanded'), 'false');
    assert.equal($$(ctx, '.mlv-rail__panel').filter((panel) => visible(ctx, panel)).length, 0, 'collapsed: the tab strip only');
    assert.ok(visible(ctx, $(ctx, '.mlv-rail__tabs')));
    // A tab in the collapsed strip opens the sheet on that tab.
    $(ctx, '.mlv-rail__tab[data-tab="about"]').click();
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true');
    assert.equal(tab(ctx), 'about');
    // Enter on the handle collapses it again.
    keydown(ctx, grip, 'Enter');
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false');
    // Collapsing the sheet is not hiding the rail: back at docking width it is shown.
    ctx.resize(1440);
    assert.equal(rail(ctx).getAttribute('data-mode'), 'docked');
    assert.equal(rail(ctx).hidden, false);
    // A docked rail the reader hid stays hidden through a narrow spell.
    ctx.app.toggleRail();
    assert.equal(rail(ctx).hidden, true);
    ctx.resize(541);
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false');
    ctx.resize(1440);
    assert.equal(rail(ctx).hidden, true, 'the reader\'s choice holds');
  } finally {
    ctx.app.destroy();
  }
});

test('the sheet takes the focus only from the keyboard; Escape collapses it and gives the focus back to the canvas', async () => {
  const ctx = await mount(doc(), { width: 541 });
  try {
    const canvas = $(ctx, '.mlv-canvas');
    canvas.focus();
    click(ctx, card(ctx, 'load'));
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true', 'a selection opens the sheet');
    assert.equal(rail(ctx).contains(ctx.document.activeElement), false, 'a pointer selection leaves the focus out of the sheet');
    ctx.app.collapseSheet(false);
    canvas.focus();
    // Viewer M2 live fix: `t` replaced Ctrl+1 to Ctrl+4 (the workbench binds those chords too).
    keydown(ctx, canvas, 't');
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'true', '`t` opens the sheet');
    assert.equal(ctx.document.activeElement, $(ctx, '.mlv-rail__tab[data-tab="inspector"]'), 'and focuses its current tab, Selection');
    const esc = keydown(ctx, ctx.document.activeElement, 'Escape');
    assert.equal(esc.defaultPrevented, true);
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false', 'Escape collapses it');
    assert.equal(ctx.document.activeElement, canvas, 'and the canvas has the focus again');
    assert.equal(ctx.app.getState().selection.id, 'load', 'the selection stays');
    keydown(ctx, canvas, 't');
    keydown(ctx, ctx.document.activeElement, 'Home');
    assert.equal(tab(ctx), 'about', 'the tab strip\'s own keys pick a tab');
    assert.equal(ctx.document.activeElement, $(ctx, '.mlv-rail__tab[data-tab="about"]'));
    // Escape from the canvas collapses an open sheet before it clears the selection.
    canvas.focus();
    keydown(ctx, canvas, 'Escape');
    assert.equal(rail(ctx).getAttribute('data-expanded'), 'false');
    assert.equal(ctx.app.getState().selection.id, 'load');
    keydown(ctx, canvas, 'Escape');
    assert.equal(ctx.app.getState().selection, null, 'the next Escape clears the selection');
  } finally {
    ctx.app.destroy();
  }
  // Docked, `t` moves the focus to the current tab too, and the arrows switch tabs.
  const wide = await mount(doc(), { width: 1440 });
  try {
    const canvas = $(wide, '.mlv-canvas');
    canvas.focus();
    keydown(wide, canvas, 't');
    assert.equal(wide.document.activeElement, $(wide, '.mlv-rail__tab[data-tab="about"]'));
    keydown(wide, wide.document.activeElement, 'ArrowRight');
    assert.equal(tab(wide), 'issues');
    keydown(wide, wide.document.activeElement, 'End');
    assert.equal(tab(wide), 'outline');
    // A docked rail the reader hid (`b`, which replaced Ctrl+B) opens on `t`.
    canvas.focus();
    keydown(wide, canvas, 'b');
    assert.equal(rail(wide).hidden, true);
    keydown(wide, canvas, 't');
    assert.equal(rail(wide).hidden, false);
    assert.equal(wide.document.activeElement, $(wide, '.mlv-rail__tab[data-tab="outline"]'));
  } finally {
    wide.app.destroy();
  }
});

test('the sheet is a labelled region after the canvas: the canvas stays within four Tab stops at every width', async () => {
  for (const width of [1440, 900, 541]) {
    const ctx = await mount(doc(), { width });
    try {
      click(ctx, card(ctx, 'load'));
      const focusable = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]';
      const stops = $$(ctx, focusable).filter((element) => element.tabIndex >= 0 && visible(ctx, element));
      const at = stops.indexOf($(ctx, '.mlv-canvas'));
      assert.ok(at >= 0 && at <= 3, `${width} px: the canvas is Tab stop ${at + 1} (${stops.slice(0, at + 1).map((e) => e.className || e.tagName).join(' | ')})`);
      const r = rail(ctx);
      assert.ok(stops.indexOf(r.querySelector('.mlv-rail__tab[aria-selected="true"]')) > at, 'the rail comes after the canvas');
      assert.equal(r.getAttribute('role'), null, 'a region, not a dialog');
      assert.equal(r.getAttribute('aria-modal'), null);
      assert.equal($(ctx, '#' + r.getAttribute('aria-labelledby')).textContent, width >= 1260 ? 'Side panel' : 'Bottom panel');
    } finally {
      ctx.app.destroy();
    }
  }
});

/* ── modal surfaces and assistive technology ─────────────────────────── */

test('the shortcut sheet and the Refine popover keep Tab inside and give the focus back on close', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const canvas = $(ctx, '.mlv-canvas');
    canvas.focus();
    keydown(ctx, canvas, '?');
    const sheet = $(ctx, '.mlv-sheet');
    assert.equal(sheet.hidden, false);
    const inSheet = () => sheet.contains(ctx.document.activeElement);
    assert.ok(inSheet(), 'the sheet takes the focus');
    const close = ctx.document.activeElement;
    let ev = keydown(ctx, close, 'Tab');
    assert.ok(inSheet(), 'Tab stays inside');
    ev = keydown(ctx, ctx.document.activeElement, 'Tab', { shiftKey: true });
    assert.equal(ev.defaultPrevented, true);
    assert.ok(inSheet(), 'Shift+Tab stays inside');
    keydown(ctx, ctx.document.activeElement, 'Escape');
    assert.equal(sheet.hidden, true);
    assert.equal(ctx.document.activeElement, canvas, 'the focus goes back to where it was');

    // The Refine… popover, opened from the Selection pane's Challenge button.
    click(ctx, card(ctx, 'load'));
    const challenge = pane(ctx).querySelector('.mlv-insp__challenge');
    challenge.focus();
    challenge.click();
    const composer = $(ctx, '.mlv-workflow__composer');
    assert.equal(composer.hidden, false);
    assert.equal(composer.getAttribute('role'), 'dialog');
    assert.equal(composer.getAttribute('aria-modal'), 'true');
    assert.ok(composer.contains(ctx.document.activeElement), 'the popover takes the focus');
    const reachable = Array.from(composer.querySelectorAll('button, select, input, textarea')).filter((e) => !e.disabled && visible(ctx, e));
    reachable.at(-1).focus();
    keydown(ctx, reachable.at(-1), 'Tab');
    assert.equal(ctx.document.activeElement, reachable[0], 'Tab from the last control wraps to the first');
    keydown(ctx, reachable[0], 'Tab', { shiftKey: true });
    assert.equal(ctx.document.activeElement, reachable.at(-1), 'Shift+Tab from the first wraps to the last');
    keydown(ctx, ctx.document.activeElement, 'Escape');
    assert.equal(composer.hidden, true);
    assert.equal(ctx.document.activeElement, challenge, 'the focus goes back to the Challenge button that opened it');
    // Opened from the header's Refine…, it gives the focus back to Refine….
    const refine = $(ctx, '.mlv-workflow__refine');
    refine.focus();
    refine.click();
    keydown(ctx, ctx.document.activeElement, 'Escape');
    assert.equal(ctx.document.activeElement, refine);
  } finally {
    ctx.app.destroy();
  }
});

test('with VS Code\'s screen-reader class a selection is announced by its claim, and nothing moves', async () => {
  const ctx = await mount(doc(), { width: 1440, bodyClass: 'vscode-using-screen-reader' });
  try {
    assert.equal(ctx.app.view.flow.motion, 'reduced', 'the flow is static');
    click(ctx, card(ctx, 'load'));
    assert.equal(ctx.app.liveEl.textContent, 'Step: Load batches. Reads CIFAR-10 with batch size 64.');
    click(ctx, card(ctx, 'aug'));
    assert.equal(ctx.app.liveEl.textContent, 'Step: Augment. Inferred, not observed.');
    ctx.app.select({ kind: 'edge', id: 'c3' });
    assert.equal(ctx.app.liveEl.textContent, 'Connection: optimizer handle, from Optimizer step to LR schedule. Unresolved.');
    ctx.app.focusIssue('f-amp');
    assert.equal(ctx.app.liveEl.textContent, 'Finding F1, high severity: Loss scaling skipped. Inferred, not observed. The scaler is built but never used.');
    const rule = /body\.vscode-using-screen-reader \.mlv-root \*,body\.vscode-using-screen-reader \.mlv-root \*:before,body\.vscode-using-screen-reader \.mlv-root \*:after\{animation-duration:\.01ms!important/;
    assert.match(CSS, rule, 'the CSS transitions are clamped too');
    assert.match(CSS, /body\.vscode-using-screen-reader \.mlv-edge__flow,body\.vscode-using-screen-reader \.mlv-edge__charge\{display:none!important\}/);
  } finally {
    ctx.app.destroy();
  }
  // Without the class the announcement stays the short one.
  const plain = await mount(doc(), { width: 1440 });
  try {
    click(plain, card(plain, 'load'));
    assert.match(plain.app.liveEl.textContent, /^Selected dataset Load batches, Data phase/);
  } finally {
    plain.app.destroy();
  }
});
