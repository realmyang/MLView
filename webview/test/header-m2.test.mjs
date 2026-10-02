// Viewer M2, step 10: the one-row header, the ... menu, the status bar, and what was removed.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies the real
// rules (screen media only): an element hidden by a `data-layout` rule is hidden from these checks
// exactly as from a reader. jsdom performs no layout, so the panel width is a stubbed
// `getBoundingClientRect` on the root, and "one row" is asserted as the controls each width keeps
// plus the no-wrap CSS (viewer-layout.test.mjs); the real-Chromium heights are measured with the
// screenshot harness outside the gate. None of this is a live VS Code check.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sha256 = (text) => createHash('sha256').update(text).digest('hex');

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Fine-tune a classifier on CIFAR-10 with mixed precision',
    producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r7' },
    request: { question: 'How is the classifier trained?', scope: 'train.py' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'inferred', evidence: ['e1'] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', basis: 'observed', evidence: ['e2'] },
    ],
    edges: [
      { id: 'c1', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c2', source: 'aug', target: 'step', label: 'batches', basis: 'unresolved', evidence: [] },
    ],
    findings: [
      { id: 'f-amp', title: 'Loss scaling skipped', message: 'm', severity: 'high', nodeIds: ['step'], basis: 'inferred', evidence: ['e2'] },
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

const VERIFIED = { verification: { publishedAt: '2026-10-01T00:00:00Z', files: { 'data.py': sha256('a'), 'train.py': sha256('b') } } };

async function mount(document = doc(), opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
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

/** What the header shows, as names a reader would use, in DOM order. */
function headerShows(ctx) {
  const parts = [];
  const header = $(ctx, '.mlv-header');
  if (visible(ctx, header.querySelector('.mlv-header__title'))) parts.push('title');
  const prov = header.querySelector('.mlv-header__prov');
  if (visible(ctx, prov)) parts.push(visible(ctx, prov.querySelector('.mlv-header__host')) ? 'host · revision' : 'revision');
  if (visible(ctx, header.querySelector('.mlv-search .mlv-input'))) parts.push('search field');
  if (visible(ctx, header.querySelector('.mlv-header__searchbtn'))) parts.push('search icon');
  for (const sev of ['high', 'medium', 'low']) {
    if (visible(ctx, header.querySelector(`.mlv-chip--sev[data-severity="${sev}"]`))) parts.push(sev);
  }
  const exceptions = header.querySelector('.mlv-chip--exceptions');
  if (visible(ctx, exceptions)) parts.push(visible(ctx, exceptions.querySelector('.mlv-chip__detail')) ? 'not observed (breakdown)' : 'not observed');
  if (visible(ctx, header.querySelector('.mlv-btn--more'))) parts.push('more');
  if (visible(ctx, header.querySelector('.mlv-workflow__refine'))) parts.push('Refine…');
  return parts;
}

function openMenu(ctx) {
  $(ctx, '.mlv-btn--more').click();
  return $(ctx, '.mlv-moremenu');
}

const menuItems = (ctx) => $$(ctx, '.mlv-moremenu__item').filter((item) => visible(ctx, item)).map((item) => item.getAttribute('data-more-item'));

/* ── the header at three widths ──────────────────────────────────────── */

test('at 1440 px the header row holds every control, with the "not observed" breakdown', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  assert.equal($(ctx, '.mlv-header').getAttribute('data-layout'), 'full');
  assert.deepEqual(headerShows(ctx), ['title', 'host · revision', 'search field', 'high', 'medium', 'not observed (breakdown)', 'more', 'Refine…']);
  assert.equal($(ctx, '.mlv-header__title').textContent, 'Fine-tune a classifier on CIFAR-10 with mixed precision');
  assert.equal($(ctx, '.mlv-header__title').title, 'Fine-tune a classifier on CIFAR-10 with mixed precision');
  assert.equal($(ctx, '.mlv-header__prov').textContent, 'claude-code · r7');
  assert.equal($(ctx, '.mlv-chip--exceptions').textContent, '3 not observed (1 step, 1 connection, 1 finding)', 'an inferred step, an unresolved connection, an inferred finding');
  ctx.app.destroy();
});

test('at 900 px search folds behind an icon and the chip keeps the revision; still one row of controls', async () => {
  const ctx = await mount(doc(), { width: 900 });
  assert.equal($(ctx, '.mlv-header').getAttribute('data-layout'), 'mid');
  assert.deepEqual(headerShows(ctx), ['title', 'revision', 'search icon', 'high', 'medium', 'not observed', 'more', 'Refine…']);
  // The breakdown folds into the accessible name and the tooltip.
  assert.equal($(ctx, '.mlv-chip--exceptions').getAttribute('aria-label'), '3 not observed (1 step, 1 connection, 1 finding)');
  // The icon opens the field and focuses it; leaving it empty folds it again.
  $(ctx, '.mlv-header__searchbtn').click();
  assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'open');
  assert.ok(visible(ctx, $(ctx, '.mlv-search .mlv-input')));
  assert.equal(ctx.document.activeElement, $(ctx, '.mlv-search .mlv-input'));
  $(ctx, '.mlv-search .mlv-input').dispatchEvent(new ctx.window.Event('blur'));
  assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'closed');
  // The ... menu stands in for nothing at this width: the row has room for every control.
  openMenu(ctx);
  assert.deepEqual(menuItems(ctx), ['legend', 'flow', 'minimap', 'rail', 'fit', 'zoomsel', 'svg', 'png', 'copy-svg', 'shortcuts']);
  ctx.app.destroy();
});

test('at 541 px only the title, the severity toggles, "not observed", ... and Refine… stay; the rest is in the menu', async () => {
  const ctx = await mount(doc(), { width: 541 });
  assert.equal($(ctx, '.mlv-header').getAttribute('data-layout'), 'narrow');
  assert.deepEqual(headerShows(ctx), ['title', 'high', 'medium', 'not observed', 'more', 'Refine…']);
  const menu = openMenu(ctx);
  assert.equal(menu.hidden, false);
  assert.deepEqual(menuItems(ctx), ['search', 'about', 'legend', 'flow', 'minimap', 'rail', 'fit', 'zoomsel', 'svg', 'png', 'copy-svg', 'shortcuts']);
  assert.equal($(ctx, '[data-more-item="about"] .mlv-moremenu__label').textContent, 'About revision r7 · claude-code');
  assert.equal($(ctx, '[data-more-item="rail"] .mlv-moremenu__label').textContent, 'Bottom panel', 'at 541 px the rail is the bottom sheet');
  // The menu's Search opens the field in the title's place.
  $(ctx, '[data-more-item="search"]').click();
  assert.equal(menu.hidden, true, 'an item closes the menu');
  assert.ok(visible(ctx, $(ctx, '.mlv-search .mlv-input')));
  assert.equal(visible(ctx, $(ctx, '.mlv-header__title')), false, 'an open search takes the title\'s place');
  assert.equal(ctx.document.activeElement, $(ctx, '.mlv-search .mlv-input'));
  // The menu's revision item opens About, in the bottom sheet.
  ctx.app.setRailTab('issues');
  ctx.app.collapseSheet(false);
  assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'false');
  openMenu(ctx);
  $(ctx, '[data-more-item="about"]').click();
  assert.equal(ctx.app.getState().railTab, 'about');
  assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'true');
  assert.ok($(ctx, '.mlv-rail__panel:not([hidden]) .mlv-about'));
  ctx.app.destroy();
});

test('resizing the panel moves controls between the row and the menu, and the status bar follows', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  ctx.resize(541);
  assert.equal($(ctx, '.mlv-header').getAttribute('data-layout'), 'narrow');
  assert.equal($(ctx, '.mlv-status').getAttribute('data-layout'), 'narrow');
  assert.equal(visible(ctx, $(ctx, '.mlv-header__prov')), false);
  assert.equal(visible(ctx, $(ctx, '.mlv-status .mlv-zoom__btn')), false, 'beside the code the zoom keeps only its readout');
  assert.ok(visible(ctx, $(ctx, '.mlv-status .mlv-zoom__value, .mlv-status .mlv-zoom')));
  ctx.resize(1100);
  assert.equal($(ctx, '.mlv-header').getAttribute('data-layout'), 'wide');
  assert.deepEqual(headerShows(ctx), ['title', 'host · revision', 'search field', 'high', 'medium', 'not observed', 'more', 'Refine…']);
  assert.ok(visible(ctx, $(ctx, '.mlv-status .mlv-zoom__btn')));
  ctx.app.destroy();
});

test('a severity with no findings has no toggle, and every toggle names its unit', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  assert.equal($(ctx, '.mlv-chip--sev[data-severity="low"]').hidden, true, 'no low finding, no low toggle');
  const high = $(ctx, '.mlv-chip--sev[data-severity="high"]');
  assert.equal(high.querySelector('.mlv-chip__count').textContent, '1');
  assert.equal(high.getAttribute('aria-label'), '1 high finding. Press to hide them.');
  high.click();
  assert.equal(high.getAttribute('aria-pressed'), 'false');
  assert.equal(high.getAttribute('aria-label'), '1 high finding, hidden. Press to show them.');
  assert.equal(high.querySelector('.mlv-chip__count').textContent, '1', 'a toggle never hides its own count');
  ctx.app.destroy();
});

test('the "not observed" chip toggles the exception emphasis', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  const chip = $(ctx, '.mlv-chip--exceptions');
  assert.equal(chip.getAttribute('aria-pressed'), 'false');
  chip.click();
  assert.equal($(ctx, '.mlv-canvas').getAttribute('data-exceptions'), 'on');
  assert.equal($(ctx, '.mlv-chip--exceptions').getAttribute('aria-pressed'), 'true');
  ctx.app.destroy();
});

test('Refine… names its target by label', async () => {
  const ctx = await mount(doc(), { width: 541 });
  ctx.app.select({ kind: 'node', id: 'aug' });
  $(ctx, '.mlv-workflow__refine').click();
  assert.equal($(ctx, '.mlv-workflow__refine').getAttribute('aria-expanded'), 'true');
  assert.equal($(ctx, '.mlv-workflow__selection').textContent, 'Step: Augment');
  ctx.app.select({ kind: 'edge', id: 'c2' });
  $(ctx, '.mlv-workflow__refine').click();
  $(ctx, '.mlv-workflow__refine').click();
  assert.equal($(ctx, '.mlv-workflow__selection').textContent, 'Connection: batches');
  ctx.app.destroy();
});

/* ── the ... menu ────────────────────────────────────────────────────── */

test('the ... menu is a menu button: arrows, Home and End move; Escape and Tab close and give the focus back', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  const button = $(ctx, '.mlv-btn--more');
  const menu = $(ctx, '.mlv-moremenu');
  assert.equal(button.getAttribute('aria-haspopup'), 'menu');
  assert.equal(button.getAttribute('aria-controls'), menu.id);
  assert.equal(menu.getAttribute('role'), 'menu');
  assert.equal(menu.hidden, true);
  assert.equal(button.closest('[role="toolbar"]') !== null, true, 'the trigger is one stop of the header toolbar');
  assert.equal(menu.closest('[role="toolbar"]'), null, 'the items never join the toolbar\'s arrow keys');

  button.focus();
  keydown(ctx, button, 'ArrowDown');
  assert.equal(menu.hidden, false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'legend');
  keydown(ctx, ctx.document.activeElement, 'ArrowDown');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'flow');
  keydown(ctx, ctx.document.activeElement, 'End');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'shortcuts');
  keydown(ctx, ctx.document.activeElement, 'ArrowDown');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'legend', 'the arrows wrap');
  keydown(ctx, ctx.document.activeElement, 'Home');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'legend');
  const esc = keydown(ctx, ctx.document.activeElement, 'Escape');
  assert.equal(esc.defaultPrevented, true);
  assert.equal(menu.hidden, true);
  assert.equal(ctx.document.activeElement, button, 'Escape gives the focus back to the trigger');

  keydown(ctx, button, 'ArrowUp');
  assert.equal(ctx.document.activeElement.getAttribute('data-more-item'), 'shortcuts', 'ArrowUp opens at the last item');
  keydown(ctx, ctx.document.activeElement, 'Tab');
  assert.equal(menu.hidden, true, 'Tab closes the menu');

  // A press outside closes it.
  button.click();
  assert.equal(menu.hidden, false);
  $(ctx, '.mlv-canvas').dispatchEvent(new ctx.window.Event('pointerdown', { bubbles: true }));
  assert.equal(menu.hidden, true);
  ctx.app.destroy();
});

test('each ... item does what it says: legend, flow, overview map, rail, fit, exports, shortcuts', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  const pick = (id) => {
    openMenu(ctx);
    const item = $(ctx, `[data-more-item="${id}"]`);
    item.click();
    return item;
  };
  assert.equal($(ctx, '[data-more-item="legend"]').getAttribute('role'), 'menuitemcheckbox');
  assert.equal(pick('legend').getAttribute('aria-checked'), 'true');
  assert.equal(ctx.app.getState().legendOpen, true);
  assert.equal(pick('legend').getAttribute('aria-checked'), 'false');
  assert.equal(pick('flow').getAttribute('aria-checked'), 'false');
  assert.equal(ctx.app.getState().flow, false);
  assert.equal(pick('minimap').getAttribute('aria-checked'), 'false');
  assert.equal(ctx.app.getState().minimapCollapsed, true);
  assert.equal(pick('rail').getAttribute('aria-checked'), 'false');
  assert.equal($(ctx, '.mlv-rail').hidden, true);
  ctx.app.view.viewport.set({ x: 5, y: 5, zoom: 2 });
  pick('fit');
  assert.notEqual(ctx.app.getState().viewport.zoom, 2, 'fit moved the viewport');
  pick('svg');
  assert.equal(ctx.bridge.posted.findLast((m) => m.type === 'exportFile').kind, 'svg');
  pick('shortcuts');
  assert.ok($(ctx, '.mlv-sheet') && !$(ctx, '.mlv-sheet').hidden, 'the shortcut sheet opens');
  // Every item names itself; the exports are the whole diagram, and nothing else is offered.
  assert.deepEqual($$(ctx, '.mlv-moremenu__item').map((item) => item.querySelector('.mlv-moremenu__label').textContent), [
    'Search steps and findings', 'About revision r7 · claude-code', '3 not observed (1 step, 1 connection, 1 finding)', 'Legend', 'Connection flow animation', 'Overview map', 'Side panel',
    'Fit the whole diagram', 'Zoom to the selection', 'Export SVG…', 'Export PNG…', 'Copy SVG', 'Keyboard shortcuts',
  ]);
  assert.equal($(ctx, '[data-more-item="zoomsel"]').disabled, true, 'nothing selected, nothing to zoom to');
  // The menu reads the selection as it opens.
  ctx.app.select({ kind: 'node', id: 'step' });
  openMenu(ctx);
  assert.equal($(ctx, '[data-more-item="zoomsel"]').disabled, false);
  $(ctx, '[data-more-item="zoomsel"]').click();
  assert.equal($(ctx, '.mlv-moremenu').hidden, true);
  ctx.app.destroy();
});

/* ── what viewer M2 removed ──────────────────────────────────────────── */

test('the scope picker, the phase chip row, the brand row and the old toolbar are gone', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  for (const selector of [
    '.mlv-btn--scope', '.mlv-scopepicker', '.mlv-scopebar', '.mlv-breadcrumb', '.mlv-filterrow', '.mlv-chiprow',
    '[data-stage-filter]', '.mlv-brand', '.mlv-toolbar', '.mlv-btn--exportmenu', '.mlv-btn--legend', '.mlv-btn--scope-node',
    '[data-scope-node]', '[data-scope-spec]', '.mlv-stats', '.mlv-workflow__heading', '.mlv-workflow__toggle',
  ]) assert.equal($(ctx, selector), null, selector + ' is not built');
  for (const name of ['setScope', 'getScope', 'scopeToNode', 'clearScope']) assert.equal(typeof ctx.app[name], 'undefined', name);
  ctx.app.select({ kind: 'node', id: 'step' }, { tab: 'inspector' });
  assert.doesNotMatch(ctx.root.textContent, /Scope to this|Scope the diagram|this codebase|Show all/);
  // The document has ONE h1, the authored title.
  assert.deepEqual($$(ctx, 'h1').map((h) => h.className), ['mlv-header__title']);
  ctx.app.destroy();
});

test('a state saved by an older viewer is tolerated: old keys ignored, never written back', async () => {
  const state = {
    workflowRevision: 'r7', viewport: { x: -40, y: -20, zoom: 1.25 },
    scope: { spec: 'unit:load', depth: 2 }, filters: { severities: ['high'], stages: ['data'], query: 'loss' },
    railGroupBy: 'file', answersOpen: true, diffOnly: true, pipelineChosen: 'train', railTab: 'outline',
  };
  const ctx = await mount(doc(), { width: 1440, state });
  assert.equal($$(ctx, '.mlv-node[data-node-id]').length, 3, 'the whole document is drawn');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().viewport)), state.viewport);
  const saved = JSON.parse(JSON.stringify(ctx.app.getState()));
  for (const key of ['scope', 'railGroupBy', 'answersOpen', 'diffOnly', 'pipelineChosen']) assert.equal(key in saved, false, key);
  assert.deepEqual(saved.filters, { severities: ['high'], query: 'loss' });
  assert.equal(saved.railTab, 'outline');
  assert.equal($(ctx, '.mlv-chip--sev[data-severity="medium"]').getAttribute('aria-pressed'), 'false', 'the saved severities still apply');
  // Garbage in an old key is not an error either.
  const odd = await mount(doc(), { width: 541, state: { scope: 'stage:', filters: { stages: 'data' } } });
  assert.equal(odd.document.querySelectorAll('.mlv-node[data-node-id]').length, 3);
  odd.app.destroy();
  ctx.app.destroy();
});

/* ── keys ────────────────────────────────────────────────────────────── */

test('Ctrl/Cmd+F and Ctrl/Cmd+K focus the search from the canvas and from the rail, and open a folded field', async () => {
  const ctx = await mount(doc(), { width: 900 });
  const input = $(ctx, '.mlv-search .mlv-input');
  const canvas = $(ctx, '.mlv-canvas');
  assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'closed');
  canvas.focus();
  const ev = keydown(ctx, canvas, 'f', { ctrlKey: true });
  assert.equal(ev.defaultPrevented, true, 'the browser find never sees it');
  assert.equal(ctx.document.activeElement, input);
  assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'open');
  const tab = $(ctx, '[role="tab"]');
  tab.focus();
  keydown(ctx, tab, 'F', { metaKey: true });
  assert.equal(ctx.document.activeElement, input, 'Cmd+F from the rail');
  tab.focus();
  keydown(ctx, tab, 'k', { ctrlKey: true });
  assert.equal(ctx.document.activeElement, input, 'Ctrl+K from the rail');
  // Alt+Ctrl+F is not ours.
  tab.focus();
  const alt = keydown(ctx, tab, 'f', { ctrlKey: true, altKey: true });
  assert.equal(alt.defaultPrevented, false);
  ctx.app.destroy();
});

test('the scope keys are free: s, Shift+S, [ and ] do nothing and are not consumed', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  const canvas = $(ctx, '.mlv-canvas');
  ctx.app.select({ kind: 'node', id: 'step' });
  canvas.focus();
  const before = $$(ctx, '.mlv-node[data-node-id]').length;
  for (const [key, init] of [['s', {}], ['S', { shiftKey: true }], ['[', {}], [']', {}]]) {
    const ev = keydown(ctx, canvas, key, init);
    assert.equal(ev.defaultPrevented, false, key + ' is not consumed');
  }
  assert.equal($$(ctx, '.mlv-node[data-node-id]').length, before);
  assert.equal(ctx.app.getState().selection.id, 'step', 'the selection stays');
  ctx.app.destroy();
});

test('the shortcut sheet lists Ctrl/Cmd+F and no scope keys', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  ctx.app.toggleShortcuts(true);
  const rows = $$(ctx, '.mlv-sheet__keys').map((dt) => [Array.from(dt.querySelectorAll('kbd'), (k) => k.textContent).join(' '), dt.nextElementSibling ? dt.nextElementSibling.textContent : '']);
  const keys = rows.map((row) => row[0]);
  assert.ok(keys.some((k) => /Ctrl\/Cmd\+F/.test(k) && /Ctrl\/Cmd\+K/.test(k)), keys.join(' | '));
  assert.equal(keys.some((k) => /^s Shift\+S$|^\[ \]$/.test(k)), false, 'the scope keys are gone');
  const sheet = $(ctx, '.mlv-sheet').textContent;
  assert.doesNotMatch(sheet, /scope/i);
  assert.match(sheet, /Close the menu, this sheet, the Refine popover or the legend, collapse the bottom panel/);
  assert.match(sheet, /About \/ Findings \/ Selection \/ Outline/);
  ctx.app.destroy();
});

/* ── the status bar ──────────────────────────────────────────────────── */

test('the status bar: steps and connections, coverage with its limitations, muted freshness, the zoom; nothing twice', async () => {
  const ctx = await mount(doc(VERIFIED), { width: 1440 });
  const status = $(ctx, '.mlv-status');
  assert.equal(status.querySelector('.mlv-status__counts').textContent, '3 steps · 2 connections');
  assert.equal(status.querySelector('.mlv-status__coverage').textContent, 'Coverage: scoped · 2 limitations');
  const fresh = status.querySelector('[data-freshness]');
  assert.equal(fresh.getAttribute('data-freshness'), 'unchanged');
  assert.equal(fresh.textContent, '2 cited files unchanged');
  assert.ok(fresh.classList.contains('is-muted'), 'unchanged is muted, never green');
  assert.equal(fresh.querySelector('svg'), null, 'and carries no icon');
  assert.match(fresh.title, /does not mean they support the claims/);
  assert.ok(status.querySelector('.mlv-zoom'), 'the zoom lives in the status bar');
  assert.deepEqual($$(ctx, '.mlv-status .mlv-zoom__btn').map((b) => b.getAttribute('aria-label')), ['Zoom out', 'Zoom in']);
  // Each count appears once on the page's chrome: no findings total, no revision, no host here.
  assert.doesNotMatch(status.textContent, /finding|r7|claude-code|notes?\b/);
  assert.equal((ctx.document.querySelector('.mlv-header').textContent.match(/r7/g) || []).length, 1, 'the revision is named once');
  // One limitation reads in the singular; none prints just the status.
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc({ ...VERIFIED, revision: { id: 'r8' }, coverage: { status: 'partial', summary: 's', inspectedFiles: ['train.py'], limitations: ['Only one.'] } }) });
  assert.equal($(ctx, '.mlv-status__coverage').textContent, 'Coverage: partial · 1 limitation');
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc({ ...VERIFIED, revision: { id: 'r9' }, coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] } }) });
  assert.equal($(ctx, '.mlv-status__coverage').textContent, 'Coverage: scoped');
  ctx.app.destroy();
});

test('a stale file is the only freshness warning: an icon, words and the amber chip dot', async () => {
  const ctx = await mount(doc(VERIFIED), { width: 1440 });
  assert.equal($(ctx, '.mlv-header__prov').getAttribute('data-stale'), 'false');
  ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'train.py', reason: 'changed' }] });
  const warn = $(ctx, '[data-freshness="stale"]');
  assert.ok(warn.classList.contains('is-warn'));
  assert.ok(warn.querySelector('svg'), 'a problem carries an icon, not colour alone');
  assert.equal(warn.textContent, '1 of 2 cited files changed');
  assert.equal($(ctx, '[data-freshness="unchanged"]'), null, 'no "unchanged" beside the warning');
  assert.equal($(ctx, '.mlv-header__prov').getAttribute('data-stale'), 'true');
  assert.match($(ctx, '.mlv-header__prov').title, /1 of 2 cited files changed/);
  ctx.bridge.send({ v: 1, type: 'stale', files: [] });
  assert.equal($(ctx, '[data-freshness="unchanged"]').textContent, '2 cited files unchanged');
  assert.equal($(ctx, '.mlv-header__prov').getAttribute('data-stale'), 'false');
  ctx.app.destroy();
});

test('search rows put the title before the location, and a count with its units heads the list', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  const input = $(ctx, '.mlv-search .mlv-input');
  input.value = 'a';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const count = $(ctx, '.mlv-search__results .mlv-result__count');
  assert.match(count.textContent, /^\d+ match(es)?: \d+ steps?(, \d+ findings?)?$/);
  input.value = 'Optimizer';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.equal($(ctx, '.mlv-search__results .mlv-result__count').textContent, '1 match: 1 step');
  const row = $(ctx, '.mlv-search__results .mlv-result');
  const label = row.querySelector('.mlv-result__label');
  const meta = row.querySelector('.mlv-result__meta');
  assert.equal(label.textContent, 'Optimizer step');
  assert.ok(label.compareDocumentPosition(meta) & ctx.window.Node.DOCUMENT_POSITION_FOLLOWING, 'the location comes after the title');
  assert.match(meta.textContent, /train\.py/);
  ctx.app.destroy();
});
