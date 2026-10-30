// The mounted viewer's header: one tab stop among the shown controls, kept off a control a
// stylesheet hides, how the row folds, units on its numbers, a severity toggle that is off. The
// find key keeps the focus inside the shortcut sheet and the Refine… popover; in the status bar a
// stale warning keeps its width.
//
// The shipped stylesheet is injected into the jsdom page. jsdom lays nothing out and lets the later
// rule win whatever its specificity, so: what a browser would measure is modelled where a test says
// so (the header's widths, which elements have boxes), and a rule that depends on specificity is
// resolved with `cascadeWinner` (helpers.mjs). The document is a small one written here, mounted in
// the built bundle; `RovingGroup` (src/ui/roving.ts) is also compiled from the sources.
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

/** Three severities, so the header carries three toggles: its widest row. */
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

/** Give every header element the boxes a browser would: a rect while shown, none while not. */
function emulateBoxes(ctx) {
  for (const element of [$(ctx, '.mlv-header__bar'), ...$$(ctx, '.mlv-header__bar *')]) {
    element.getClientRects = () => (visible(ctx, element) ? [{ width: 10, height: 10 }] : []);
  }
}

/* ── The header toolbar's one tab stop is a control on screen ──────── */

test('at 541, 900 and 1440 px exactly one shown header control is the tab stop, and the arrows only visit shown controls', async () => {
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

test('opening the folded search field re-derives the tab stop; the results of a query are not tab stops', async () => {
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

test('a roving group skips a control a stylesheet hides (no boxes), even without a hidden attribute', async () => {
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
  // A browser's boxes: the bar and a and c have them; b is `display: none` from a layout rule.
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

/* ── The header row folds until it fits ──────────────────────────────────────── */

/**
 * An approximation of the header's widths in a browser at the shipped type scale, in round
 * figures: what the row needs for the controls that are on screen now. `scrollWidth` reports
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
    // The Review button (an icon and a word), shown from 620 px until the row folds.
    add('.mlv-header__review', 78);
    add('.mlv-btn--more', 26);
    add('.mlv-workflow__refine', 70, 0);
    return total;
  };
  Object.defineProperty(header, 'clientWidth', { configurable: true, get: () => ctx.width() });
  Object.defineProperty(header, 'scrollWidth', { configurable: true, get: () => Math.max(ctx.width(), need()) });
  return need;
}

test('the row folds the revision, "not observed", then the title until Refine… fits; the menu takes what was folded', async () => {
  const ctx = await mount(threeSeverities(), { width: 900 });
  try {
    const need = emulateRow(ctx);
    // Search open at 541 px with three severities is the widest row: Refine… must stay on it.
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

/* ── Every count on the row names its unit on screen ────────────────────── */

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

test('the severity numbers and "not observed" name their unit on screen at 541, 900 and 1440 px', async () => {
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

/* ── Ctrl/Cmd+F leaves a modal surface alone ───────────────────────────────────────── */

test('Ctrl+F in the shortcut sheet and Cmd+F in the Refine… popover keep the focus inside them', async () => {
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

/* ── An off severity toggle keeps its count readable ──────────────────────────────── */

test('a severity toggle that is off is struck through and dashed, never faded', async () => {
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

/* ── The status bar never cuts a stale warning ─────────────────────────────────────── */

test('beside the code a stale warning keeps its width; the coverage item gives way first', async () => {
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
