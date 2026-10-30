// A selected card stays wholly in view, moved the least distance at the same zoom, when the rail
// becomes the sheet or the sheet opens; a card the reader moved out of view stays there. A remount
// of the same revision restores the selection and the open sheet, and another revision restores
// neither; a selection kind the viewer does not have, or an id the revision lacks, is dropped. A
// docked rail saves nothing for the sheet.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies its rules.
// jsdom performs no layout: the panel width is a stubbed `getBoundingClientRect` on the root, and
// the canvas box is stubbed the way the shipped CSS stacks it beside a docked rail or above the
// bottom sheet. The document is the renderer-regression fixture of helpers.mjs, mounted in the
// built bundle.
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
const click = (ctx, target) => target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));

/** A card's box on screen, from the viewport and the laid-out frame. */
function screenBox(ctx, id) {
  const vp = ctx.app.getState().viewport;
  const b = ctx.app.view.frameData.boxes.get(id);
  return { left: b.x * vp.zoom + vp.x, top: b.y * vp.zoom + vp.y, right: (b.x + b.w) * vp.zoom + vp.x, bottom: (b.y + b.h) * vp.zoom + vp.y };
}
const inside = (b, area) => b.left >= 0 && b.top >= 0 && b.right <= area.w && b.bottom <= area.h;

/* ── a selection the layout hid is revealed again with the least pan ──────────────────────────── */

test('a card selected beside the docked rail stays wholly in view when Enter halves the panel into the open sheet', async () => {
  // The scene: the diagram alone in a panel 1430 px wide, the first view untouched, a card selected
  // with the rail docked. The panel then halves to 715 px, as when Enter opens the source beside
  // it, and the rail becomes the open sheet. The card must not end under the sheet: keeping it in
  // view comes before the readable fit for the new size.
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

test('the sheet opening under a selected card moves it the least distance, at the same zoom', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 715 });
  try {
    ctx.app.view.fit();
    assert.equal(ctx.rail.getAttribute('data-mode'), 'sheet');
    assert.equal(ctx.rail.getAttribute('data-expanded'), 'false');
    const tall = ctx.box();
    const id = 'node-8';
    const b = ctx.app.view.frameData.boxes.get(id);
    const zoom = ctx.app.getState().viewport.zoom;
    // Put the card low in the tall canvas, where the open sheet will be, and select it with
    // `app.select` rather than a click or a list row, so only the layout change can move it.
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

test('a card the reader moved out of view is not pulled back by a layout change', async () => {
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

/* ── a remount restores the selection and the open sheet of the same revision ────────────────── */

test('a remount of the same revision restores the selection and the open sheet with the tab', async () => {
  // A page loaded again in its panel mounts from the saved view (the host sends the document again
  // on each `ready`). It must bring back the selection and the open sheet, not only the tab.
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

test('another revision, or a selection that is not one, restores neither', async () => {
  const document = rendererRegressionWorkflow(48);
  const state = { viewport: { x: 0, y: 0, zoom: 1 }, selection: { kind: 'node', id: 'node-12' }, collapsed: [], filters: { severities: ['high', 'medium', 'low'], query: '' }, railTab: 'inspector', workflowRevision: 'fixture-r0', sheetOpen: true };
  const other = await mount(document, { width: 541, state });
  try {
    assert.equal(other.app.getState().selection, null, 'a selection saved for another revision is dropped');
    assert.equal(other.rail.getAttribute('data-expanded'), 'false', 'and so is its open sheet');
    assert.equal(other.app.getState().railTab, 'about', 'a new revision opens on About');
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
