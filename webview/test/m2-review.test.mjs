// Viewer M2 review fixes: one regression test per confirmed finding (ids in each test's name).
//
// The shipped stylesheet is injected into the jsdom page. jsdom lays nothing out and lets the later
// rule win whatever its specificity, so: what Chrome would measure is modelled where a test says
// so (the header's widths, which elements have boxes), and a rule that depends on specificity is
// resolved with `cascadeWinner` (helpers.mjs). The real-Chromium numbers come from headless-Chrome
// probes outside the gate. None of this is a live VS Code, screen-reader or usability check.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { build } from 'esbuild';
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

/** Three severities, so the header carries three toggles (the review's widest case). */
function threeSeverities() {
  const d = doc();
  d.findings.push({ id: 'f-low', title: 'A low one', message: 'm', severity: 'low', nodeIds: ['aug'], basis: 'observed', evidence: ['e1'] });
  return d;
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

/** Give every header element the boxes Chrome would: a rect while shown, none while not. */
function emulateBoxes(ctx) {
  for (const element of [$(ctx, '.mlv-header__bar'), ...$$(ctx, '.mlv-header__bar *')]) {
    element.getClientRects = () => (visible(ctx, element) ? [{ width: 10, height: 10 }] : []);
  }
}

/* ── M2R-1, A11Y-1, A11Y-3: the header toolbar's one tab stop is a control on screen ──────── */

test('M2R-1 / A11Y-1 / A11Y-3: at 541, 900 and 1440 px exactly one shown header control is the tab stop, and the arrows only visit shown controls', async () => {
  for (const width of [541, 900, 1440]) {
    const ctx = await mount(threeSeverities(), { width });
    try {
      emulateBoxes(ctx);
      ctx.app.refreshChrome();
      const controls = $$(ctx, '.mlv-header__bar button').filter((b) => b.getAttribute('role') !== 'option');
      const stops = controls.filter((b) => b.tabIndex === 0);
      assert.equal(stops.length, 1, `${width}: one tab stop (${stops.map((b) => b.className).join(', ')})`);
      assert.ok(visible(ctx, stops[0]), `${width}: the tab stop ${stops[0].className} is on screen`);
      const shown = controls.filter((b) => visible(ctx, b));
      // The arrows walk every shown control once and come back; the focus never stays put.
      stops[0].focus();
      const seen = [];
      for (let i = 0; i < shown.length; i++) {
        const before = ctx.document.activeElement;
        keydown(ctx, before, 'ArrowRight');
        const now = ctx.document.activeElement;
        assert.notEqual(now, before, `${width}: ArrowRight from ${before.className} moved`);
        assert.ok(visible(ctx, now), `${width}: ArrowRight landed on a shown control (${now.className})`);
        assert.equal(now.tabIndex, 0, 'the tab stop moved with the focus');
        seen.push(now);
      }
      assert.equal(new Set(seen).size, shown.length, `${width}: every shown control is reachable`);
      assert.equal(seen[seen.length - 1], stops[0], 'and the walk wraps');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('M2R-1: opening and closing the folded search field re-derives the tab stop', async () => {
  const ctx = await mount(doc(), { width: 900 });
  try {
    emulateBoxes(ctx);
    ctx.app.refreshChrome();
    const icon = $(ctx, '.mlv-header__searchbtn');
    icon.focus();
    assert.equal(icon.tabIndex, 0);
    ctx.app.focusSearch();
    assert.equal(visible(ctx, icon), false, 'the open field replaces the icon');
    const stops = $$(ctx, '.mlv-header__bar button').filter((b) => b.tabIndex === 0);
    assert.equal(stops.length, 1);
    assert.ok(visible(ctx, stops[0]), 'the stop left the hidden icon (' + stops[0].className + ')');
    // The results are options of the field's listbox, reached with its arrow keys, never by Tab.
    const input = ctx.app.chrome.searchInput;
    input.value = 'loss';
    input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
    const options = $$(ctx, '.mlv-header .mlv-result');
    assert.ok(options.length > 0, 'the query has results');
    assert.deepEqual(options.map((o) => o.tabIndex), options.map(() => -1));
    assert.equal($$(ctx, '.mlv-header__bar button').filter((b) => b.tabIndex === 0).length, 1, 'still one tab stop');
  } finally {
    ctx.app.destroy();
  }
});

let rovingPromise = null;
/** src/ui/roving.ts as an ES module (it touches no DOM on import). */
function roving() {
  if (!rovingPromise) {
    rovingPromise = build({
      stdin: { contents: "export { RovingGroup } from './ui/roving.ts';", resolveDir: join(WEBVIEW_ROOT, 'src'), loader: 'ts', sourcefile: 'roving-entry.ts' },
      bundle: true, format: 'esm', platform: 'neutral', write: false, logLevel: 'silent',
    }).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));
  }
  return rovingPromise;
}

test('A11Y-1: a roving group skips a control a stylesheet hides (no boxes), even without a hidden attribute', async () => {
  const { RovingGroup } = await roving();
  const ctx = await loadBundle();
  const bar = ctx.document.createElement('div');
  ctx.document.body.appendChild(bar);
  const [a, b, c] = ['a', 'b', 'c'].map((name) => {
    const button = ctx.document.createElement('button');
    button.textContent = name;
    bar.appendChild(button);
    return button;
  });
  // Chrome: the bar and a and c have boxes; b is `display: none` from a layout rule.
  bar.getClientRects = () => [{ width: 100 }];
  a.getClientRects = () => [{ width: 10 }];
  b.getClientRects = () => [];
  c.getClientRects = () => [{ width: 10 }];
  const group = new RovingGroup(bar);
  assert.deepEqual([a.tabIndex, b.tabIndex, c.tabIndex], [0, -1, -1]);
  a.focus();
  a.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, c, 'ArrowRight skips the unrendered control');
  // The first control becomes unrendered (a narrower layout): the stop never sits on it.
  a.getClientRects = () => [];
  c.blur();
  group.sync();
  assert.equal(a.tabIndex, -1);
  assert.equal(c.tabIndex, 0, 'the stop stays on the control the user left it on');
  group.destroy();
});

/* ── M2R-2, A11Y-8: the header row folds until it fits ──────────────────────────────────────── */

/**
 * The header's widths as Chrome draws them at the shipped type scale (rounded from headless-Chrome
 * measurements): what the row needs for the controls that are on screen now. `scrollWidth` reports
 * that need, `clientWidth` the panel.
 */
function emulateRow(ctx) {
  const header = $(ctx, '.mlv-header');
  const need = () => {
    const fit = Number(header.getAttribute('data-fit') || 0);
    // Padding 12 + 8, gaps 6 (8 after the title); the tightest rows close up to 6 + 6 and 4.
    const tight = fit >= 3;
    let total = tight ? 12 : 20;
    const add = (selector, w, gap = tight ? 4 : 6) => {
      for (const element of header.querySelectorAll(selector)) if (visible(ctx, element)) total += w + gap;
    };
    if (fit < 3) add('.mlv-header__title', 48, 8);
    add('.mlv-header__prov', 120);
    add('.mlv-search', 120);
    add('.mlv-header__searchbtn', 26);
    add('.mlv-chip--sev', 44);
    add('.mlv-header__unit', 50);
    add('.mlv-chip--exceptions', 150);
    add('.mlv-btn--more', 26);
    add('.mlv-workflow__refine', 70, 0);
    return total;
  };
  Object.defineProperty(header, 'clientWidth', { configurable: true, get: () => ctx.width() });
  Object.defineProperty(header, 'scrollWidth', { configurable: true, get: () => Math.max(ctx.width(), need()) });
  return need;
}

test('M2R-2 / A11Y-8: the row folds the revision, "not observed", then the title until Refine… fits; the menu takes what was folded', async () => {
  const ctx = await mount(threeSeverities(), { width: 900 });
  try {
    const need = emulateRow(ctx);
    // Search open at 541 px with three severities: the review measured Refine… past the edge.
    ctx.resize(541);
    ctx.app.focusSearch();
    const input = $(ctx, '.mlv-search .mlv-input');
    input.value = 'loss';
    input.dispatchEvent(new ctx.window.Event('input'));
    assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'open');
    assert.ok(need() <= 541, `the open search row fits 541 px (needs ${need()})`);
    assert.equal($(ctx, '.mlv-header').getAttribute('data-fit'), '2', 'folded as far as needed');
    assert.equal(visible(ctx, $(ctx, '.mlv-chip--exceptions')), false, '"not observed" is folded');
    assert.ok(visible(ctx, $(ctx, '.mlv-workflow__refine')));
    $(ctx, '.mlv-btn--more').click();
    const item = $(ctx, '[data-more-item="exceptions"]');
    assert.ok(visible(ctx, item), 'the menu carries the folded toggle');
    assert.equal(item.getAttribute('role'), 'menuitemcheckbox');
    assert.equal(item.querySelector('.mlv-moremenu__label').textContent, '3 not observed (1 step, 1 connection, 1 finding)', 'with its count and units');
    item.click();
    assert.equal($(ctx, '.mlv-canvas').getAttribute('data-exceptions'), 'on', 'and it toggles the exceptions');
    // A field left empty closes, and the row unfolds.
    input.value = '';
    input.dispatchEvent(new ctx.window.Event('input'));
    input.dispatchEvent(new ctx.window.Event('blur'));
    assert.equal($(ctx, '.mlv-header').getAttribute('data-search'), 'closed');
    assert.ok(need() <= 541);
    assert.equal($(ctx, '.mlv-header').getAttribute('data-fit'), '0', 'the closed row needs no folding at 541 px');
    assert.ok(visible(ctx, $(ctx, '.mlv-chip--exceptions')));
    // 320 px (WCAG 1.4.10): the title gives way last, kept for screen readers.
    ctx.resize(320);
    assert.ok(need() <= 320, `the 320 px row fits (needs ${need()})`);
    assert.equal($(ctx, '.mlv-header').getAttribute('data-fit'), '3');
    assert.ok(visible(ctx, $(ctx, '.mlv-workflow__refine')));
    assert.equal($(ctx, '.mlv-header__title').textContent, doc().title, 'the h1 keeps its text');
    // 640 px, search open: the revision chip folds first and About moves into the menu.
    ctx.resize(640);
    ctx.app.focusSearch();
    input.value = 'loss';
    input.dispatchEvent(new ctx.window.Event('input'));
    assert.ok(need() <= 640, `needs ${need()}`);
    assert.equal(visible(ctx, $(ctx, '.mlv-header__prov')), false);
    $(ctx, '.mlv-btn--more').click();
    assert.ok(visible(ctx, $(ctx, '[data-more-item="about"]')), 'About is in the menu while the chip is folded');
  } finally {
    ctx.app.destroy();
  }
});

/* ── M2-INT-2, A11Y-5: every count on the row names its unit on screen ────────────────────── */

/** The header's visible text, in order, as a reader sees it. */
function headerText(ctx) {
  const parts = [];
  const walk = (node) => {
    if (node.nodeType === 3) { if (node.textContent.trim()) parts.push(node.textContent.trim()); return; }
    if (node.nodeType !== 1 || !visible(ctx, node) || node.classList.contains('mlv-sr')) return;
    for (const child of node.childNodes) walk(child);
  };
  walk($(ctx, '.mlv-header__bar'));
  return parts.join(' ');
}

test('M2-INT-2 / A11Y-5: the severity numbers and "not observed" name their unit on screen at 541, 900 and 1440 px', async () => {
  for (const [width, expected] of [
    [541, /1\s+1\s+findings\s+3 claims not observed/],
    [900, /1\s+1\s+findings\s+3 claims not observed/],
    [1440, /1\s+1\s+findings\s+3 not observed\s*\(1 step, 1 connection, 1 finding\)/],
  ]) {
    const ctx = await mount(doc(), { width });
    try {
      assert.match(headerText(ctx), expected, `${width}: ${headerText(ctx)}`);
      // The unit word is not read twice: each toggle's name already has it.
      assert.equal($(ctx, '.mlv-header__unit').getAttribute('aria-hidden'), 'true');
      assert.equal($(ctx, '.mlv-chip--sev[data-severity="high"]').getAttribute('aria-label'), '1 high finding. Press to hide them.');
    } finally {
      ctx.app.destroy();
    }
  }
  // One severity with one finding: "finding".
  const one = await mount(doc({ findings: [doc().findings[0]] }), { width: 541 });
  try {
    assert.equal($(one, '.mlv-header__unit').textContent, 'finding');
  } finally {
    one.app.destroy();
  }
});

/* ── M2R-9: Ctrl/Cmd+F leaves a modal surface alone (Ctrl/Cmd+K is no longer bound) ───────── */

test('M2R-9: Ctrl+F in the shortcut sheet and Cmd+F in the Refine… popover keep the focus inside them', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    ctx.app.toggleShortcuts(true);
    const sheet = $(ctx, '.mlv-sheet');
    assert.ok(sheet.contains(ctx.document.activeElement), 'precondition: the focus is in the sheet');
    keydown(ctx, ctx.document.activeElement, 'f', { ctrlKey: true });
    assert.ok(sheet.contains(ctx.document.activeElement), 'the focus stayed in the open sheet');
    assert.equal(ctx.app.sheet.open, true);
    ctx.app.toggleShortcuts(false);

    $(ctx, '.mlv-workflow__refine').click();
    const composer = $(ctx, '.mlv-workflow__composer');
    assert.equal(composer.hidden, false);
    const inside = composer.querySelector('select, input, button');
    inside.focus();
    keydown(ctx, inside, 'f', { metaKey: true });
    assert.ok(composer.contains(ctx.document.activeElement), 'the focus stayed in the open popover');
    // Outside any modal the key still focuses the search.
    keydown(ctx, ctx.document.activeElement, 'Escape');
    const canvas = $(ctx, '.mlv-canvas');
    canvas.focus();
    keydown(ctx, $(ctx, '[role="tab"]'), 'f', { ctrlKey: true });
    assert.equal(ctx.document.activeElement, $(ctx, '.mlv-search .mlv-input'));
  } finally {
    ctx.app.destroy();
  }
});

/* ── A11Y-12: an off severity toggle keeps its count readable ──────────────────────────────── */

test('A11Y-12: a severity toggle that is off is struck through and dashed, never faded', async () => {
  const ctx = await mount(doc(), { width: 1440 });
  try {
    const high = $(ctx, '.mlv-chip--sev[data-severity="high"]');
    high.click();
    assert.equal(high.getAttribute('aria-pressed'), 'false');
    const opacity = cascadeWinner(CSS, high, 'opacity');
    assert.ok(!opacity || Number(opacity.value) === 1, 'no opacity on the off toggle (' + (opacity && opacity.selector) + ')');
    assert.equal(cascadeWinner(CSS, high, 'text-decoration').value, 'line-through');
    assert.equal(cascadeWinner(CSS, high, 'border-style').value, 'dashed');
    assert.equal(cascadeWinner(CSS, high, 'color').value, 'var(--mlv-text)', 'the count keeps the text colour');
    // "Not observed" is a toggle whose off state is the normal state: neither struck nor dashed.
    const exceptions = $(ctx, '.mlv-chip--exceptions');
    assert.equal(cascadeWinner(CSS, exceptions, 'text-decoration').value, 'none');
    assert.equal(cascadeWinner(CSS, exceptions, 'border-style').value, 'solid');
  } finally {
    ctx.app.destroy();
  }
});

/* ── M2R-11: the status bar never cuts a stale warning ─────────────────────────────────────── */

test('M2R-11: beside the code a stale warning keeps its width; the coverage item gives way first', async () => {
  const ctx = await mount(doc(), { width: 541 });
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'train.py', reason: 'changed' }] });
    const fresh = $(ctx, '.mlv-status__freshness');
    assert.equal(fresh.getAttribute('data-stale'), 'true');
    assert.equal(cascadeWinner(CSS, fresh, 'flex').value, 'none', 'the warning never shrinks');
    const coverage = Number(cascadeWinner(CSS, $(ctx, '.mlv-status__coverage'), 'flex-shrink').value);
    const counts = Number(cascadeWinner(CSS, $(ctx, '.mlv-status__counts'), 'flex-shrink').value);
    assert.ok(coverage > counts && counts > 0, `coverage shrinks first (${coverage}), then the counts (${counts})`);
    // And it is short enough not to need to: the status and the limitations with their unit.
    assert.equal($(ctx, '.mlv-status__coverage').textContent, 'scoped · 2 limitations');
    assert.equal($(ctx, '.mlv-status__coverage').getAttribute('aria-label'), 'Coverage: scoped · 2 limitations');
    ctx.bridge.send({ v: 1, type: 'stale', files: [] });
    assert.equal(fresh.getAttribute('data-stale'), 'false');
  } finally {
    ctx.app.destroy();
  }
});

/* ── M2-INT-1, M2R-3, M2R-5: what a selection shows ─────────────────────────────────────────── */

const click = (ctx, target, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1, ...init }));
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);
const tab = (ctx) => ctx.app.getState().railTab;
const rail = (ctx) => $(ctx, '.mlv-rail');
const pane = (ctx) => $(ctx, '.mlv-rail__panel:not([hidden]) .mlv-sel');

test('M2-INT-1: a canvas click on a step shows its claim even when the Findings list was on show (1440 docked and 541 sheet)', async () => {
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

test('M2R-3: a search hit for a step shows its claim: the Selection tab at 1440, and the collapsed sheet opens at 541 and 900', async () => {
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

test('M2R-5: a claim read in the docked rail stays open when the panel narrows into the sheet (Enter opens the source beside)', async () => {
  const ctx = await mount(doc(), { width: 1382 });
  try {
    assert.equal(rail(ctx).getAttribute('data-mode'), 'docked');
    click(ctx, card(ctx, 'load'));
    keydown(ctx, ctx.app.view.canvasEl, 'Enter');
    assert.ok(ctx.bridge.posted.some((m) => m.type === 'openLocation'), 'precondition: Enter asked to open the source');
    // The host opens the file beside: the panel halves.
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

/* ── M2R-6: a group's pane says what the group stands for ──────────────────────────────────── */

test('M2R-6: a collapsed group\'s pane lists the findings inside it, its steps, and the connections across its edge', async () => {
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

/* ── M2R-7, A11Y-4: only the exceptions carry a basis mark in the rail ─────────────────────── */

test('M2R-7 / A11Y-4: observed findings carry no basis mark in the Findings list or the Selection pane; inferred ones carry the canvas tag', async () => {
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

/* ── M2R-8: a finding frames the ends of the connections it cites too ─────────────────────── */

test('M2R-8: a finding that cites a step and a connection elsewhere frames both ends of the connection as well', async () => {
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

/* ── M2R-10: the sheet's handle reports the height drawn, and a drag collapse keeps the height ─ */

test('M2R-10: the handle never reports more than the canvas floor leaves, and a drag that collapses the sheet keeps its height', async () => {
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

/* ── A11Y-10: what a screen reader hears uses the diagram's own words ──────────────────────── */

test('A11Y-10: announcements and names say steps, connections and F labels, never nodes and edges', async () => {
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

test('M2R-4: a lane with two severities names their total after the numbers, on the canvas, in the Outline and in the SVG', async () => {
  const d = doc();
  d.findings.push({ id: 'f-sched', title: 'Schedule stepped per batch', message: 'm', severity: 'medium', nodeIds: ['sched'], basis: 'observed', evidence: ['e2'] });
  const ctx = await mount(d, { width: 1440 });
  try {
    const lane = $(ctx, '.mlv-lane[data-lane-id="fit"]');
    const unit = lane.querySelector('.mlv-lane__unit');
    // "1 1 findings touch this phase" read as one finding; the phrase now carries the total.
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

test('A11Y-6: a card with a detail shows two lines of it where the file:line row was; one without keeps the row', async () => {
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

test('A11Y-9: a hover dims no card; it rings the lit ones. Focus mode still dims and makes the rest inert', async () => {
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

test('A11Y-11: a lane heading is numbered, in the text colour at the title size, on a plate; the Outline numbers it too', async () => {
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
