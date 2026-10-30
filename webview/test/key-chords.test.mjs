// The canvas answers b and t, and no Ctrl or Cmd chord but the find key, which takes either
// modifier on every platform; the shortcut sheet and the ... menu label the keys for the platform.
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
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const keydown = (ctx, target, key, init = {}) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const openMenu = (ctx) => {
  const button = $(ctx, '.mlv-btn--more');
  if (button.getAttribute('aria-expanded') !== 'true') button.click();
};

test('the canvas answers b and t and leaves every Ctrl/Cmd chord but the find key to the workbench', async () => {
  // The canvas answers no Ctrl or Cmd chord but the find key, and leaves every other one
  // unconsumed (`handleCanvasKey` in ui/keymap.ts), so a chord that the workbench binds does only
  // what the workbench does with it.
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

test('on macOS the labels read ⌘F, B and t; elsewhere Ctrl+F; nothing advertises Ctrl+K, Ctrl+B or Ctrl+1', async () => {
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
