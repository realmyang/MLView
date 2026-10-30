// The phase index and its item in the ... menu. The item says whether the index is drawn, and
// gives the reason when it cannot be; the index is a panel of rows when the viewer is wide, and
// its pill beside the code or on a canvas under 350 px tall.
//
// The shipped stylesheet is injected into the jsdom page, and its text is read for the width rule.
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
const openMenu = (ctx) => {
  const button = $(ctx, '.mlv-btn--more');
  if (button.getAttribute('aria-expanded') !== 'true') button.click();
};

// The rule for the phase index's menu item: never checked while the index is not drawn, with the
// reason on the item. In a panel beside the code the index is drawn too, as its pill.
test('the phase index: the item says whether it is drawn; beside the code it is the pill, wide the panel', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1440 });
  try {
    const index = $(ctx, '.mlv-phaseindex');
    const item = () => $(ctx, '[data-more-item="phaseindex"]');
    const note = () => item().querySelector('.mlv-moremenu__note');
    assert.equal(index.hidden, false);
    assert.equal(index.getAttribute('data-form'), 'list', '1440 px: the panel of rows');
    openMenu(ctx);
    assert.equal(item().disabled, false);
    assert.equal(item().getAttribute('aria-checked'), 'true', 'drawn: checked');
    assert.equal(note().hidden, true);
    item().click();
    assert.equal(ctx.app.getState().phaseIndex, 'hidden');
    assert.equal(index.hidden, true);
    openMenu(ctx);
    assert.equal(item().getAttribute('aria-checked'), 'false');
    item().click();
    for (const width of [900, 541]) {
      ctx.resize(width);
      assert.equal(index.hidden, false, width + ': still drawn');
      assert.equal(index.getAttribute('data-form'), 'pill', width + ': as its pill');
      openMenu(ctx);
      assert.equal(item().disabled, false, width + ': the item works');
      assert.equal(item().getAttribute('aria-checked'), 'true', width + ': and says it is drawn');
      $(ctx, '.mlv-btn--more').click();
    }
    ctx.resize(1440);
    assert.equal(index.getAttribute('data-form'), 'list');
    // The width rule is the App's, not a media query the menu cannot see.
    assert.doesNotMatch(CSS, /@media[^{]*\{\s*\.mlv-phaseindex/);
  } finally {
    ctx.app.destroy();
  }
});

test('the phase index: a canvas under 350 px tall gets the pill; one phase gives the reason', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48), { width: 1440, bodyH: 300 });
  try {
    ctx.app.view.handleResize();
    assert.equal($(ctx, '.mlv-phaseindex').getAttribute('data-form'), 'pill');
  } finally {
    ctx.app.destroy();
  }
  const one = rendererRegressionWorkflow(16);
  one.phases = one.phases.slice(0, 1);
  for (const node of one.nodes) node.phase = one.phases[0].id;
  const single = await mount(one, { width: 1440 });
  try {
    assert.equal($(single, '.mlv-phaseindex').hidden, true, 'one phase: nothing to index');
    openMenu(single);
    const item = $(single, '[data-more-item="phaseindex"]');
    assert.equal(item.disabled, true);
    assert.equal(item.getAttribute('aria-checked'), 'false');
    assert.equal(item.querySelector('.mlv-moremenu__note').textContent, 'Shown when the diagram has two or more phases');
  } finally {
    single.app.destroy();
  }
});
