/**
 * VIEW-12 — accessibility scaffolding.
 *
 * The keyboard model inside the diagram was already unusually good: one focus
 * stop, a working `aria-activedescendant` roving selection and a polite live
 * region announcing every selection. Everything AROUND it was not:
 *
 *   - **22 Tab presses** to reach the canvas, behind the scope button, the
 *     search box, three severity chips, the flow toggle, four viewport buttons,
 *     four theme chips and seven stage chips;
 *   - no skip link and no `main` landmark;
 *   - **no `h1` at all**, with three rail `h3`s preceding the two `h2`s, so
 *     screen-reader heading navigation started mid-document;
 *   - an unlabelled minimap that was not `aria-hidden`, whose "Collapse
 *     minimap" button was tab stop 22 — AFTER the canvas.
 *
 * jsdom implements no sequential focus navigation, so the tab order is computed
 * here the way the spec defines it: the focusable elements in DOM order whose
 * `tabIndex` is not negative, skipping anything inside a hidden subtree.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

async function mount(graph = sample) {
  const ctx = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app, root: ctx.document.getElementById('mlview-root') };
}

const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';

function hiddenAnywhere(element) {
  let cur = element;
  while (cur && cur.nodeType === 1) {
    if (cur.hidden) return true;
    cur = cur.parentElement;
  }
  return false;
}

/** Every element Tab visits, in order. */
function tabOrder(root) {
  const out = [];
  for (const element of root.querySelectorAll(FOCUSABLE)) {
    if (element.disabled) continue;
    if (hiddenAnywhere(element)) continue;
    if (element.tabIndex < 0) continue;
    out.push(element);
  }
  return out;
}

function describe(element) {
  const cls = (element.getAttribute('class') || '').split(/\s+/)[0] || element.tagName.toLowerCase();
  return cls + (element.getAttribute('aria-label') ? '[' + element.getAttribute('aria-label') + ']' : '');
}

/* ── the path to the canvas ────────────────────────────────────────────── */

test('the canvas is reachable in <= 4 Tab presses, and the skip link is the first (VIEW-12)', async () => {
  const ctx = await mount();
  const order = tabOrder(ctx.root);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const at = order.indexOf(canvas);
  assert.ok(at >= 0, 'the canvas is in the tab order');
  assert.equal(
    order[0].classList.contains('mlv-skiplink'),
    true,
    'the first tab stop is the skip link, not the scope button: ' + describe(order[0]),
  );
  assert.ok(
    at + 1 <= 4,
    'the canvas is press ' + (at + 1) + ': ' + order.slice(0, at + 1).map(describe).join(' -> '),
  );
  ctx.app.destroy();
});

test('the skip link lands on the canvas without navigating the document (VIEW-12)', async () => {
  const ctx = await mount();
  const skip = ctx.document.querySelector('.mlv-skiplink');
  const canvas = ctx.document.querySelector('.mlv-canvas');
  assert.equal(skip.getAttribute('href'), '#' + canvas.id, 'it is a real link to the canvas');
  const before = ctx.window.location.href;
  const ev = new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true });
  skip.dispatchEvent(ev);
  assert.equal(ev.defaultPrevented, true, 'the default is prevented — 11.17: the report never navigates itself');
  assert.equal(ctx.document.activeElement, canvas, 'focus is on the canvas');
  assert.equal(ctx.window.location.href, before, 'and the document stayed where it was');
  // One Tab to the link, one activation: at most three presses either way.
  const order = tabOrder(ctx.root);
  assert.equal(order.indexOf(skip), 0);
  ctx.app.destroy();
});

/* ── landmarks and headings ────────────────────────────────────────────── */

test('the canvas sits inside a <main> landmark, beside the rail (VIEW-12)', async () => {
  const ctx = await mount();
  const mains = ctx.document.querySelectorAll('main');
  assert.equal(mains.length, 1, 'exactly one main landmark');
  const canvas = ctx.document.querySelector('.mlv-canvas');
  assert.ok(mains[0].contains(canvas), 'it contains the diagram');
  assert.equal(ctx.document.querySelectorAll('aside.mlv-rail').length, 1, 'the rail is a complementary landmark');
  assert.equal(mains[0].contains(ctx.document.querySelector('.mlv-rail')), false, 'the rail is not inside main');
  ctx.app.destroy();
});

test('exactly one h1, carrying the workspace name (VIEW-12)', async () => {
  const ctx = await mount();
  const h1s = ctx.document.querySelectorAll('h1');
  assert.equal(h1s.length, 1, 'exactly one h1');
  assert.ok(
    h1s[0].textContent.indexOf(sample.workspace.root) >= 0,
    'it names the workspace: ' + h1s[0].textContent,
  );
  ctx.app.destroy();
});

test('the heading outline is monotonic, top-down (VIEW-12)', async () => {
  const ctx = await mount();
  const headings = Array.from(ctx.document.querySelectorAll('h1, h2, h3, h4, h5, h6')).filter((h) => !hiddenAnywhere(h));
  const levels = headings.map((h) => Number(h.tagName.slice(1)));
  assert.equal(levels[0], 1, 'the outline starts at h1: ' + headings.map((h) => h.tagName + ' ' + h.textContent.slice(0, 24)).join(' | '));
  for (let i = 1; i < levels.length; i++) {
    assert.ok(
      levels[i] <= levels[i - 1] + 1,
      'no level is skipped at ' + headings[i].tagName + ' "' + headings[i].textContent.slice(0, 40) + '"',
    );
  }
  // The rail's severity sections are h4 under the panel h3 — they used to be
  // h3s that came BEFORE the document's only h2s.
  const railHeadings = Array.from(ctx.document.querySelectorAll('.mlv-rail [data-severity-section] .mlv-rail__heading'));
  assert.ok(railHeadings.length > 0, 'the rail draws severity sections');
  for (const h of railHeadings) assert.equal(h.tagName, 'H4', 'severity headings are h4');
  ctx.app.destroy();
});

/* ── the roving toolbar ────────────────────────────────────────────────── */

test('the chrome is one role=toolbar with a single tab stop (VIEW-12)', async () => {
  const ctx = await mount();
  const bar = ctx.document.querySelector('[role="toolbar"]');
  assert.ok(bar, 'the control strip declares role=toolbar');
  assert.ok(bar.contains(ctx.document.querySelector('.mlv-toolbar')), 'it holds the toolbar row');
  assert.ok(bar.contains(ctx.document.querySelector('.mlv-filterrow')), 'and the stage filter row');
  const stops = tabOrder(bar);
  const input = ctx.document.querySelector('.mlv-input');
  assert.equal(stops.length, 2, 'one roving item plus the search input: ' + stops.map(describe).join(', '));
  assert.ok(stops.indexOf(input) >= 0, 'the search input keeps its own stop');
  ctx.app.destroy();
});

test('arrow keys move the tab stop inside the toolbar (VIEW-12)', async () => {
  const ctx = await mount();
  const bar = ctx.document.querySelector('[role="toolbar"]');
  const items = Array.from(bar.querySelectorAll('button')).filter((b) => !b.hidden && !hiddenAnywhere(b));
  assert.ok(items.length > 8, 'the strip really does carry a dozen controls: ' + items.length);
  assert.equal(items.filter((b) => b.tabIndex === 0).length, 1, 'exactly one item is the tab stop');

  items[0].focus();
  items[0].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, items[1], 'ArrowRight moves the focus');
  assert.equal(items[1].tabIndex, 0, 'and the tab stop with it');
  assert.equal(items[0].tabIndex, -1, 'the old item steps out of the tab order');

  items[1].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, items[items.length - 1], 'End jumps to the last control');
  ctx.app.destroy();
});

test('the search box keeps its own keys inside the toolbar (VIEW-12)', async () => {
  const ctx = await mount();
  const input = ctx.document.querySelector('.mlv-input');
  input.focus();
  const ev = new ctx.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true });
  input.dispatchEvent(ev);
  assert.equal(ctx.document.activeElement, input, 'ArrowRight in a text field moves the caret, not the toolbar');
  assert.equal(ev.defaultPrevented, false, 'and the roving group never preventDefaults it');
  ctx.app.destroy();
});

test('the stage chips still filter after the roving group takes them over (VIEW-12)', async () => {
  const ctx = await mount();
  const chip = ctx.document.querySelector('[data-stage-filter="train"]');
  assert.ok(chip, 'the stage chips are still there');
  chip.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  const state = ctx.app.getState();
  assert.deepEqual(JSON.parse(JSON.stringify(state.filters.stages)).indexOf('train') >= 0, false, 'clicking a chip toggles it off');
  const bar = ctx.document.querySelector('[role="toolbar"]');
  const zero = Array.from(bar.querySelectorAll('button')).filter((b) => b.tabIndex === 0 && !hiddenAnywhere(b));
  assert.equal(zero.length, 1, 'and the rebuilt row still has exactly one tab stop');
  ctx.app.destroy();
});

/* ── the minimap ───────────────────────────────────────────────────────── */

test('the minimap is aria-hidden, before the canvas, with a labelled toggle (VIEW-12)', async () => {
  const ctx = await mount();
  const minimap = ctx.document.querySelector('.mlv-minimap');
  const canvas = ctx.document.querySelector('.mlv-canvas');
  assert.equal(minimap.getAttribute('aria-hidden'), 'true', 'the overview duplicates a navigable canvas');
  assert.equal(minimap.parentElement.tagName, 'MAIN', 'it is a sibling of the canvas inside main');
  assert.equal(
    minimap.compareDocumentPosition(canvas) & 4,
    4,
    'and it comes BEFORE the canvas in DOM order, not after it',
  );
  // An aria-hidden subtree may not contain a tab stop.
  const inside = Array.from(minimap.querySelectorAll(FOCUSABLE)).filter((e) => e.tabIndex >= 0);
  assert.deepEqual(inside.map(describe), [], 'nothing inside it is a tab stop');

  const toggle = ctx.document.querySelector('.mlv-btn--minimap');
  assert.ok(toggle, 'the keyboard toggle exists');
  assert.ok(ctx.document.querySelector('[role="toolbar"]').contains(toggle), 'in the toolbar, before the canvas');
  assert.equal(toggle.getAttribute('aria-pressed'), 'true', 'pressed while the overview is shown');
  assert.ok((toggle.getAttribute('aria-label') || '').length > 0, 'and it is labelled: ' + toggle.getAttribute('aria-label'));

  toggle.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(minimap.classList.contains('is-collapsed'), true, 'it collapses the panel');
  assert.equal(toggle.getAttribute('aria-pressed'), 'false', 'and says so');
  assert.equal(ctx.app.getState().minimapCollapsed, true, 'the flag survives a reload');
  ctx.app.destroy();
});

test('the in-panel chevron still collapses the minimap by pointer (VIEW-12)', async () => {
  const ctx = await mount();
  const minimap = ctx.document.querySelector('.mlv-minimap');
  const chevron = minimap.querySelector('.mlv-minimap__toggle');
  assert.equal(chevron.tabIndex, -1, 'pointer-only, because the panel is aria-hidden');
  chevron.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(minimap.classList.contains('is-collapsed'), true, 'the pointer affordance still works');
  assert.equal(
    ctx.document.querySelector('.mlv-btn--minimap').getAttribute('aria-pressed'),
    'false',
    'and the toolbar toggle tracks it',
  );
  ctx.app.destroy();
});

/* ── the focus ring ────────────────────────────────────────────────────── */

test('node cards carry a :focus-visible ring of their own (VIEW-12)', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const at = css.indexOf('.mlv-node:focus-visible');
  assert.ok(at >= 0, 'the stylesheet declares a card focus ring');
  const block = css.slice(at, css.indexOf('}', at));
  assert.ok(block.indexOf('outline: 2px solid var(--mlv-focus)') >= 0, 'a real ring: ' + block);
});

/* ── nothing overrides a native role (VIEW-R4) ─────────────────────────── */

test('no control announces itself as something it is not (VIEW-R4)', async () => {
  // `role` on an interactive element REPLACES its implicit role, so a <button
  // role="listitem"> computes as an inert list item: it leaves the button rotor,
  // and a screen-reader user is told the dialog holds a list, not three actions.
  // MLV-P12's chooser rows shipped exactly that. Nothing may do it again.
  const graph = JSON.parse(JSON.stringify(sample));
  graph.workspace = { ...graph.workspace, entrypoints: ['train.py', 'data.py', 'sklearn_baseline.py'] };
  const ctx = await mount(graph);
  const chooser = ctx.document.querySelector('.mlv-pipechooser');
  assert.equal(chooser.hidden, false, 'the chooser is open, so its rows are on screen');
  const rows = Array.from(chooser.querySelectorAll('[data-pipeline]'));
  assert.ok(rows.length >= 2, rows.length + ' chooser rows');
  for (const row of rows) {
    assert.equal(row.tagName, 'BUTTON');
    assert.equal(row.getAttribute('role'), null, row.getAttribute('data-pipeline') + ' overrides the button role');
  }
  // And the same rule over the whole document: no <button> or <a href> anywhere
  // may claim a non-interactive role.
  const INERT = ['listitem', 'list', 'presentation', 'none', 'text', 'paragraph', 'heading', 'img'];
  for (const el of ctx.document.querySelectorAll('button[role], a[href][role], input[role]')) {
    const role = el.getAttribute('role');
    assert.equal(
      INERT.indexOf(role) >= 0,
      false,
      '<' + el.tagName.toLowerCase() + ' role="' + role + '"> hides an action from assistive tech',
    );
  }
  ctx.app.destroy();
});
