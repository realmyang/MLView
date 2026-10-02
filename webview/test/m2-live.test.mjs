// Viewer M2 live fixes: what the live check in an Extension Development Host (VS Code 1.139,
// macOS, 2026-10-02) found wrong, each pinned here. The phase-tone hue check is in
// calm-canvas.test.mjs, beside the contrast check it shares a colour resolver with; the host's
// choice of editor group is in vscode-extension/test/verification-loop.test.js.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies its rules.
// jsdom performs no layout: the panel width is a stubbed `getBoundingClientRect` on the root, and
// the canvas box is stubbed the way the shipped CSS stacks it beside a docked rail or above the
// bottom sheet. None of this is a live check or a usability result.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, rendererRegressionWorkflow, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');

/** The default docked rail (`--mlv-rail-width`) and the open sheet's share of the body. */
const RAIL_W = 360;
const SHEET_SHARE = 0.47;

/**
 * Mount `document` in a panel `width` px wide whose body (between the header and the status bar)
 * is `bodyH` px tall. `opts.mac` makes the page report macOS; `opts.state` is a saved view.
 */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  if (opts.mac) Object.defineProperty(ctx.window.navigator, 'platform', { value: 'MacIntel', configurable: true });
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 0;
  const bodyH = opts.bodyH || 742;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: bodyH + 58, right: width, bottom: bodyH + 58 });
  const bridge = recordingBridge(ctx.window, 'vscode', opts.state ? { state: opts.state } : {});
  // The canvas box exists only once the App is built; until then the viewer measures nothing.
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const rail = ctx.document.querySelector('.mlv-rail');
  const box = () => {
    const docked = rail.getAttribute('data-mode') !== 'sheet';
    const w = docked ? width - (rail.hidden ? 0 : RAIL_W) : width;
    const sheet = docked ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * SHEET_SHARE) : 32;
    return { w, h: bodyH - sheet };
  };
  canvas.getBoundingClientRect = () => {
    const { w, h } = box();
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  const resize = (next) => {
    width = next;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  return { ...ctx, root, bridge, app, canvas, rail, box, resize };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const keydown = (ctx, target, key, init = {}) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const click = (ctx, target) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
const openMenu = (ctx) => {
  const button = $(ctx, '.mlv-btn--more');
  if (button.getAttribute('aria-expanded') !== 'true') button.click();
};

/** A card's box on screen, from the viewport and the laid-out frame. */
function screenBox(ctx, id) {
  const vp = ctx.app.getState().viewport;
  const b = ctx.app.view.frameData.boxes.get(id);
  return { left: b.x * vp.zoom + vp.x, top: b.y * vp.zoom + vp.y, right: (b.x + b.w) * vp.zoom + vp.x, bottom: (b.y + b.h) * vp.zoom + vp.y };
}
const inside = (b, area) => b.left >= 0 && b.top >= 0 && b.right <= area.w && b.bottom <= area.h;

/* ── 1. a selection the layout hid is revealed again with the least pan ───────────────────────── */

test('live fix 1: a card selected beside the docked rail stays wholly in view when Enter halves the panel into the open sheet', async () => {
  // MEASURED live before the fix: the diagram alone at about 1430 px, the first view untouched, a
  // card selected with the rail docked; Enter opened the source beside the panel, which halved to
  // about 715 px, and the card ended under the open sheet (selectedInCanvas=false). The readable
  // fit for the new size, anchored on phase 1, won over the selection.
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1430 });
  try {
    ctx.app.view.fit();
    assert.equal(ctx.app.view.viewport.isFitted, true, 'precondition: the first view, untouched');
    const docked = ctx.box();
    assert.deepEqual([docked.w, docked.h], [1430 - RAIL_W, 742]);
    // The card lowest in the docked canvas that is still wholly inside it: where the sheet will be.
    const cards = Array.from(ctx.app.view.frameData.boxes.keys()).filter((id) => !ctx.app.index.isGroup(id) && $(ctx, `.mlv-node[data-node-id="${id}"]`));
    const target = cards.filter((id) => inside(screenBox(ctx, id), docked)).sort((a, b) => screenBox(ctx, b).bottom - screenBox(ctx, a).bottom)[0];
    assert.ok(target, 'a card is in view');
    const before = screenBox(ctx, target);
    click(ctx, $(ctx, `.mlv-node[data-node-id="${target}"]`));
    assert.equal(ctx.app.getState().selection.id, target);
    assert.deepEqual(screenBox(ctx, target), before, 'a click beside the docked rail moves nothing');
    const zoom = ctx.app.getState().viewport.zoom;
    ctx.resize(715);
    assert.equal(ctx.rail.getAttribute('data-mode'), 'sheet');
    assert.equal(ctx.rail.getAttribute('data-expanded'), 'true', 'the claim being read stays open, as the sheet');
    const area = ctx.box();
    assert.deepEqual([area.w, area.h], [715, 742 - Math.round(742 * SHEET_SHARE)]);
    const after = screenBox(ctx, target);
    assert.ok(inside(after, area), `the card (${after.left.toFixed(0)}-${after.right.toFixed(0)} x ${after.top.toFixed(0)}-${after.bottom.toFixed(0)}) is wholly above the sheet`);
    assert.equal(ctx.app.getState().viewport.zoom, zoom, 'at the same zoom');
    // The least pan: the card stops 16 px inside the edge it came in from, not centred.
    const gaps = [after.left, after.top, area.w - after.right, area.h - after.bottom];
    assert.ok(gaps.some((gap) => Math.abs(gap - 16) < 0.5), 'one edge 16 px inside: ' + gaps.map((g) => g.toFixed(1)).join(', '));
  } finally {
    ctx.app.destroy();
  }
});

test('live fix 1: the sheet opening under a selected card moves it the least distance, at the same zoom', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 715 });
  try {
    ctx.app.view.fit();
    assert.equal(ctx.rail.getAttribute('data-mode'), 'sheet');
    assert.equal(ctx.rail.getAttribute('data-expanded'), 'false');
    const tall = ctx.box();
    const id = 'node-8';
    const b = ctx.app.view.frameData.boxes.get(id);
    const zoom = ctx.app.getState().viewport.zoom;
    // Put the card low in the tall canvas, where the open sheet will be, and select it from the
    // Outline-free API so only the layout change can move it.
    ctx.app.view.viewport.set({ x: 100 - b.x * zoom, y: tall.h - 20 - (b.y + b.h) * zoom });
    ctx.app.select({ kind: 'node', id });
    const before = screenBox(ctx, id);
    ctx.app.setRailOpen(true);
    const area = ctx.box();
    const after = screenBox(ctx, id);
    assert.ok(inside(after, area), 'wholly above the open sheet');
    assert.equal(ctx.app.getState().viewport.zoom, zoom);
    assert.ok(Math.abs(after.left - before.left) < 0.5, 'no sideways move: the card was inside horizontally');
    assert.ok(Math.abs(area.h - after.bottom - 16) < 0.5, 'its bottom 16 px above the sheet');
  } finally {
    ctx.app.destroy();
  }
});

test('live fix 1: a card the reader moved out of view is not pulled back by a layout change', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1430 });
  try {
    ctx.app.view.fit();
    click(ctx, $(ctx, '.mlv-node[data-node-id="node-8"]'));
    // The reader pans until the card is half off the canvas, deliberately.
    const b = screenBox(ctx, 'node-8');
    ctx.app.view.viewport.panBy(-b.left - (b.right - b.left) / 2, 0);
    const moved = ctx.app.getState().viewport;
    ctx.resize(715);
    assert.equal(ctx.rail.getAttribute('data-mode'), 'sheet');
    assert.deepEqual(ctx.app.getState().viewport, moved, 'the docked-to-sheet change leaves it where the reader put it');
    ctx.app.collapseSheet(false);
    ctx.app.setRailOpen(true);
    assert.deepEqual(ctx.app.getState().viewport, moved, 'so do the sheet collapsing and opening');
    // Nothing runs on a frame without a change of size: a resize to the same size moves nothing.
    ctx.app.view.handleResize();
    assert.deepEqual(ctx.app.getState().viewport, moved);
  } finally {
    ctx.app.destroy();
  }
});

/* ── 4. the ... menu's overview map item tells the truth ───────────────────────────────────────── */

test('live fix 4: beside the code the overview map item is disabled, unchecked and says why; wide, it toggles the map', async () => {
  // MEASURED live before the fix: at 900 and 541 px the menu showed "Overview map" checked while
  // the stylesheet hid the map (`display: none`).
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1440 });
  try {
    const map = $(ctx, '.mlv-minimap');
    const item = () => $(ctx, '[data-more-item="minimap"]');
    const note = () => item().querySelector('.mlv-moremenu__note');
    assert.equal(map.classList.contains('is-narrow'), false);
    openMenu(ctx);
    assert.equal(item().disabled, false);
    assert.equal(item().getAttribute('aria-checked'), 'true', 'drawn and not collapsed: checked');
    assert.equal(note().hidden, true);
    item().click();
    assert.equal(ctx.app.getState().minimapCollapsed, true);
    openMenu(ctx);
    assert.equal(item().getAttribute('aria-checked'), 'false');
    item().click();
    for (const width of [900, 541]) {
      ctx.resize(width);
      assert.equal(map.classList.contains('is-narrow'), true, width + ': no room for the map');
      assert.equal(ctx.window.getComputedStyle(map).display, 'none', width + ': the stylesheet hides it');
      openMenu(ctx);
      assert.equal(item().disabled, true, width + ': the item is disabled');
      assert.equal(item().getAttribute('aria-checked'), 'false', width + ': and never checked');
      assert.equal(note().hidden, false);
      assert.equal(note().textContent, 'No room in a panel 900 px wide or narrower');
      assert.match(item().title, /^Overview map: no room in a panel 900 px wide or narrower$/);
      item().click();
      assert.equal(ctx.app.getState().minimapCollapsed, false, 'a disabled item changes nothing');
      $(ctx, '.mlv-btn--more').click();
    }
    // Back at 1440 px the reader's choice (shown) is what the item says again.
    ctx.resize(1440);
    openMenu(ctx);
    assert.equal(item().disabled, false);
    assert.equal(item().getAttribute('aria-checked'), 'true');
    // The width rule is the class the App sets, not a media query the menu cannot see.
    assert.doesNotMatch(CSS, /@media\s*\(max-width:\s*900px\)\s*\{\s*\.mlv-minimap/);
  } finally {
    ctx.app.destroy();
  }
});

test('live fix 4: a canvas too short for the map gives that reason', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1440, bodyH: 300 });
  try {
    ctx.app.view.handleResize();
    assert.equal($(ctx, '.mlv-minimap').classList.contains('is-short'), true);
    openMenu(ctx);
    const item = $(ctx, '[data-more-item="minimap"]');
    assert.equal(item.disabled, true);
    assert.equal(item.querySelector('.mlv-moremenu__note').textContent, 'No room in a canvas under 350 px tall');
  } finally {
    ctx.app.destroy();
  }
});

/* ── 5. keys the workbench leaves alone, labelled for the platform ─────────────────────────────── */

test('live fix 5: the canvas answers b and t and leaves every Ctrl/Cmd chord but the find key to the workbench', async () => {
  // MEASURED live in VS Code 1.139 on macOS, keys sent to the focused webview over the DevTools
  // protocol: Cmd+B collapsed the sheet AND hid the side bar; Cmd+K focused the search AND started
  // a workbench chord; Ctrl+2 brought the diagram's group to its second tab, hiding the diagram.
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1440 });
  try {
    const canvas = ctx.canvas;
    canvas.focus();
    for (const key of ['b', 'B', 'k', 'K', '1', '2', '3', '4']) {
      for (const init of [{ ctrlKey: true }, { metaKey: true }]) {
        const ev = keydown(ctx, canvas, key, init);
        assert.equal(ev.defaultPrevented, false, `${init.ctrlKey ? 'Ctrl' : 'Cmd'}+${key} is not consumed`);
      }
    }
    assert.equal(ctx.rail.hidden, false, 'no chord toggled the rail');
    assert.equal(ctx.app.getState().railTab, 'about', 'no chord switched the tab');
    assert.equal(ctx.document.activeElement, canvas, 'and the focus stayed on the diagram');
    assert.equal(keydown(ctx, canvas, 'b').defaultPrevented, true);
    assert.equal(ctx.rail.hidden, true, '`b` hides the docked rail');
    keydown(ctx, canvas, 'b');
    assert.equal(ctx.rail.hidden, false, 'and shows it again');
    assert.equal(keydown(ctx, canvas, 't').defaultPrevented, true);
    assert.equal(ctx.document.activeElement, $(ctx, '.mlv-rail__tab[data-tab="about"]'), '`t` focuses the current tab');
    canvas.focus();
    assert.equal(keydown(ctx, canvas, 'f', { metaKey: true }).defaultPrevented, true, 'the find key is still the viewer\'s');
    assert.equal(ctx.document.activeElement, $(ctx, '.mlv-search .mlv-input'));
  } finally {
    ctx.app.destroy();
  }
});

test('live fix 5: on macOS the labels read ⌘F, B and t; elsewhere Ctrl+F; nothing advertises Ctrl+K, Ctrl+B or Ctrl+1', async () => {
  for (const mac of [true, false]) {
    const ctx = await mount(rendererRegressionWorkflow(48), { width: 541, mac });
    try {
      const find = mac ? '⌘F' : 'Ctrl+F';
      ctx.app.toggleShortcuts(true);
      const rows = $$(ctx, '.mlv-sheet__keys').map((dt) => Array.from(dt.querySelectorAll('kbd'), (k) => k.textContent).join(' '));
      assert.ok(rows.includes(find + ' /'), rows.join(' | '));
      assert.ok(rows.includes('b') && rows.includes('t'), 'the panel keys');
      assert.ok(rows.includes(mac ? '⇧0' : 'Shift+0'), 'the other modifiers follow the platform too');
      assert.ok(rows.includes(mac ? '⌥Enter' : 'Alt+Enter'));
      const sheet = $(ctx, '.mlv-sheet').textContent;
      assert.doesNotMatch(sheet, /Ctrl\+K|Cmd\+K|⌘K|Ctrl\+B|⌘B|Ctrl\+1|Ctrl\/Cmd/);
      assert.match(sheet, mac ? /Option\+click an Open link, or press ⌥Enter/ : /Alt\+click an Open link, or press Alt\+Enter/);
      ctx.app.toggleShortcuts(false);
      // The ... menu: search is folded into it at 541 px, with the find key; the panel is B.
      openMenu(ctx);
      assert.equal($(ctx, '[data-more-item="search"] .mlv-moremenu__keys').textContent, find);
      assert.equal($(ctx, '[data-more-item="rail"] .mlv-moremenu__keys').textContent, 'B');
      assert.equal($(ctx, '.mlv-header__searchbtn').getAttribute('aria-label'), 'Search (' + find + ')');
    } finally {
      ctx.app.destroy();
    }
  }
});

/* ── 6. a listed finding's id reads as one line ────────────────────────────────────────────────── */

test('live fix 6: under "Findings on this step" the real id is a muted line below the title; the F-label stays in the head', async () => {
  // MEASURED live before the fix: the id sat in a narrow column right of the title and broke
  // letter by letter ("f-plot-/not-/random").
  const document = rendererRegressionWorkflow(48);
  document.findings[0].id = 'f-plot-not-random';
  const ctx = await mount(document, { width: 1440 });
  try {
    ctx.app.select({ kind: 'node', id: 'node-8' }, { tab: 'inspector' });
    const box = $(ctx, '.mlv-rail__panel:not([hidden]) .mlv-insp__issue[data-issue-id="f-plot-not-random"]');
    assert.ok(box, 'the finding is listed on its step');
    const head = box.querySelector('.mlv-insp__issue-head');
    assert.equal(head.querySelector('.mlv-insp__short').textContent, 'F1', 'the F-label stays');
    assert.ok(head.querySelector('.mlv-insp__issue-title'));
    assert.equal(head.querySelector('.mlv-mono'), null, 'no id column beside the title');
    const id = box.querySelector('.mlv-insp__issue-id');
    assert.equal(id.textContent, 'f-plot-not-random');
    assert.equal(id.previousElementSibling, head, 'directly under the head row');
    const style = ctx.window.getComputedStyle(id);
    assert.equal(style.overflowWrap, 'anywhere', 'a long id wraps at the box edge');
    assert.ok(id.classList.contains('mlv-mono'));
    // The finding's own pane keeps its id beside the F-label.
    ctx.app.focusIssue('f-plot-not-random');
    ctx.app.setRailTab('inspector');
    assert.equal($(ctx, '.mlv-rail__panel:not([hidden]) .mlv-insp__eyebrow .mlv-mono').textContent, 'f-plot-not-random');
  } finally {
    ctx.app.destroy();
  }
});

/* ── 7. reopening a hidden panel keeps the selection and the open sheet ─────────────────────────── */

test('live fix 7: a remount of the same revision restores the selection and the open sheet with the tab', async () => {
  // MEASURED live before the fix: reopening a hidden panel (VS Code rebuilds its page) kept the
  // tab but lost the selection and the open sheet.
  const document = rendererRegressionWorkflow(48);
  const first = await mount(document, { width: 541 });
  let saved;
  try {
    click(first, $(first, '.mlv-node[data-node-id="node-12"]'));
    assert.equal(first.rail.getAttribute('data-expanded'), 'true', 'precondition: the click opened the sheet');
    saved = JSON.parse(JSON.stringify(first.app.getState()));
    assert.deepEqual(saved.selection, { kind: 'node', id: 'node-12' });
    assert.equal(saved.sheetOpen, true, 'the open sheet is saved');
    assert.equal(saved.workflowRevision, 'fixture-r1');
  } finally {
    first.app.destroy();
  }
  const again = await mount(document, { width: 541, state: saved });
  try {
    assert.deepEqual(JSON.parse(JSON.stringify(again.app.getState().selection)), { kind: 'node', id: 'node-12' });
    assert.ok($(again, '.mlv-node[data-node-id="node-12"]').classList.contains('is-selected'), 'drawn selected');
    assert.equal(again.rail.getAttribute('data-expanded'), 'true', 'the sheet is open again');
    assert.equal(again.app.getState().railTab, 'inspector', 'on the Selection tab');
    assert.equal($(again, '.mlv-rail__panel:not([hidden]) .mlv-insp__title').textContent, 'Step 12');
  } finally {
    again.app.destroy();
  }
  // Collapsed, nothing is saved for the sheet, and it comes back collapsed with the selection.
  const collapsed = await mount(document, { width: 541, state: saved });
  let savedCollapsed;
  try {
    collapsed.app.collapseSheet(false);
    savedCollapsed = JSON.parse(JSON.stringify(collapsed.app.getState()));
    assert.equal('sheetOpen' in savedCollapsed, false, 'absent at its default');
  } finally {
    collapsed.app.destroy();
  }
  const back = await mount(document, { width: 541, state: savedCollapsed });
  try {
    assert.equal(back.rail.getAttribute('data-expanded'), 'false');
    assert.equal(back.app.getState().selection.id, 'node-12');
  } finally {
    back.app.destroy();
  }
});

test('live fix 7: another revision, or a selection that is not one, restores neither', async () => {
  const document = rendererRegressionWorkflow(48);
  const state = { viewport: { x: 0, y: 0, zoom: 1 }, selection: { kind: 'node', id: 'node-12' }, collapsed: [], filters: { severities: ['high', 'medium', 'low'], query: '' }, railTab: 'inspector', workflowRevision: 'fixture-r0', sheetOpen: true };
  const other = await mount(document, { width: 541, state });
  try {
    assert.equal(other.app.getState().selection, null, 'a selection saved for another revision is dropped');
    assert.equal(other.rail.getAttribute('data-expanded'), 'false', 'and so is its open sheet');
    assert.equal(other.app.getState().railTab, 'about', 'a new revision opens on About, as before');
  } finally {
    other.app.destroy();
  }
  const odd = await mount(document, { width: 541, state: { ...state, workflowRevision: 'fixture-r1', selection: { kind: 'scope', id: 'node-12' } } });
  try {
    assert.equal(odd.app.getState().selection, null, 'a selection kind the viewer does not have is ignored');
  } finally {
    odd.app.destroy();
  }
  const gone = await mount(document, { width: 541, state: { ...state, workflowRevision: 'fixture-r1', selection: { kind: 'node', id: 'node-999' } } });
  try {
    assert.equal(gone.app.getState().selection, null, 'an id the revision lacks is dropped');
  } finally {
    gone.app.destroy();
  }
  // Docked, the sheet's state is not written at all.
  const wide = await mount(document, { width: 1440 });
  try {
    click(wide, $(wide, '.mlv-node[data-node-id="node-12"]'));
    assert.equal('sheetOpen' in wide.app.getState(), false);
  } finally {
    wide.app.destroy();
  }
});
