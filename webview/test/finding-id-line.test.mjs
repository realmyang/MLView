// A finding listed on its step shows its id on a line of its own under its title, where a long id
// wraps at the box edge; the F-label stays in the head, and the finding's own pane keeps the id
// beside the F-label.
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

test('under "Findings on this step" the real id is a muted line below the title; the F-label stays in the head', async () => {
  // The id has a line of its own under the head row: in a narrow column beside the title a long
  // id breaks letter by letter.
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
