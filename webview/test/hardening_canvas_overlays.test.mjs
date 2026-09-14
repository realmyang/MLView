/**
 * Hardening round 1, area hosts-ux — the drag-pan guard and the overlays that
 * live INSIDE `.mlv-canvas`.
 *
 * MEASURED DEFECT. `wireCanvasGestures` (`src/ui/shell.ts`) starts a drag-pan on
 * every `pointerdown` whose target is not inside
 *
 *     .mlv-node, .mlv-group__header, .mlv-minimap, .mlv-zoom, .mlv-edge__hit
 *
 * and then calls `canvas.setPointerCapture(ev.pointerId)`. `app.ts` appends the
 * **legend** to `shell.canvas`, and `.mlv-legend` is not in that list — so
 * pressing the mouse anywhere in the legend panel starts a canvas pan, the
 * capture retargets the pointer stream, and the button's `click` never fires.
 *
 * Reproduced in Chromium (Playwright, the shipped standalone report):
 *
 *   open the legend, then `mouse.down()` on `.mlv-legend__close`
 *     -> `.mlv-canvas` gains `is-panning`
 *     -> `mouse.up()`  -> the legend is STILL OPEN
 *   `document.querySelector('.mlv-legend__close').click()`  -> it closes
 *   focus the same button and press Enter                   -> it closes
 *
 * So the one control the panel offers works from the keyboard and not from the
 * mouse, which is the wrong way round for a decorative-looking icon button. The
 * minimap and the zoom cluster are unaffected because they ARE in the list.
 *
 * These tests assert the behaviour that must hold — a pointer press on a
 * canvas-hosted overlay is that overlay's gesture, never the canvas's pan — and
 * the last one pins the guard list itself, so a new overlay appended to the
 * canvas cannot silently inherit the same bug.
 *
 * FOUR OF THEM FAIL TODAY and are marked `todo` so the suite's exit code still
 * reports the state of everything else. `node --test` prints a failing todo in
 * full and does not count it as a failure; the fix is to delete the `todo`
 * option from each, not to relax the assertion.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample } from './helpers.mjs';
import { DIST_JS } from './helpers.mjs';

const sample = await readSample();

async function app() {
  const ctx = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, sample, bridge);
  return { ...ctx, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

function pointer(ctx, target, type, init = {}) {
  const Ctor = ctx.window.PointerEvent || ctx.window.MouseEvent;
  target.dispatchEvent(
    new Ctor(type, { bubbles: true, cancelable: true, pointerId: 1, clientX: 10, clientY: 10, ...init }),
  );
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

test('the legend really is a child of the canvas — the premise of everything below', async () => {
  const ctx = await app();
  const legend = ctx.document.querySelector('.mlv-legend');
  assert.ok(legend, 'the viewer must mount a legend');
  assert.ok(ctx.canvas.contains(legend), 'app.ts appends the legend to shell.canvas');
});

test('a pointer press inside the legend must not start a canvas drag-pan', { todo: 'HOSTS-UX-LEGEND: shell.ts drag-pan guard; delete this option when it is fixed' }, async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('.mlv-btn--legend'));
  const legend = ctx.document.querySelector('.mlv-legend');
  assert.equal(legend.hidden, false, 'the toolbar button must open the legend');

  const close = ctx.document.querySelector('.mlv-legend__close');
  assert.ok(close, 'the legend must offer a close control');
  pointer(ctx, close, 'pointerdown');
  assert.equal(
    ctx.canvas.classList.contains('is-panning'),
    false,
    'pressing the legend close button started a canvas pan — the capture that follows ' +
      'swallows the button\'s click in a real browser (shell.ts drag-pan guard)',
  );
  pointer(ctx, close, 'pointerup');
});

test('a pointer press on the legend body must not start a canvas drag-pan either', { todo: 'HOSTS-UX-LEGEND: shell.ts drag-pan guard; delete this option when it is fixed' }, async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('.mlv-btn--legend'));
  const body = ctx.document.querySelector('.mlv-legend__body');
  assert.ok(body, 'the legend must have a body');
  pointer(ctx, body, 'pointerdown');
  assert.equal(
    ctx.canvas.classList.contains('is-panning'),
    false,
    'dragging inside the legend panned the diagram underneath it',
  );
  pointer(ctx, body, 'pointerup');
});

test('the close button closes the legend when it is clicked', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('.mlv-btn--legend'));
  const legend = ctx.document.querySelector('.mlv-legend');
  assert.equal(legend.hidden, false);
  const close = ctx.document.querySelector('.mlv-legend__close');
  // The full gesture, in the order a browser dispatches it.
  pointer(ctx, close, 'pointerdown');
  pointer(ctx, close, 'pointerup');
  click(ctx, close);
  assert.equal(legend.hidden, true, 'the legend stayed open after its own close button was clicked');
});

test('Escape closes the legend, as it closes every other overlay the viewer draws', { todo: 'HOSTS-UX-LEGEND: shell.ts drag-pan guard; delete this option when it is fixed' }, async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('.mlv-btn--legend'));
  const legend = ctx.document.querySelector('.mlv-legend');
  assert.equal(legend.hidden, false);
  for (const target of [legend, ctx.canvas, ctx.document.body]) {
    target.dispatchEvent(
      new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    );
    if (legend.hidden) break;
  }
  assert.equal(
    legend.hidden,
    true,
    'Escape left the legend open; the shortcuts sheet and the scope picker both close on it',
  );
});

test('the drag-pan guard names every overlay the app appends to the canvas', { todo: 'HOSTS-UX-LEGEND: shell.ts drag-pan guard; delete this option when it is fixed' }, async () => {
  const source = await readFile(DIST_JS, 'utf8');
  // The guard is one `closest(...)` call in the bundled shell; find its selector.
  const match = source.match(/closest\(["'](\.mlv-node,[^"']*)["']\)/);
  assert.ok(match, 'the drag-pan guard selector was not found in the bundle — has it moved?');
  const guard = match[1];
  const ctx = await app();
  // Every direct child of the canvas that is not the world layer is an overlay
  // painted over the diagram; a press on one of them belongs to it.
  const overlays = Array.from(ctx.canvas.children)
    .map((el) => String(el.className || ''))
    .filter((cls) => cls && !cls.includes('mlv-world'))
    .map((cls) => '.' + cls.trim().split(/\s+/)[0]);
  const missing = overlays.filter((sel) => !guard.includes(sel));
  assert.deepEqual(
    missing,
    [],
    `these canvas overlays are not in the drag-pan guard ("${guard}"), so a pointer press ` +
      'on one of them starts a pan and its controls cannot be clicked',
  );
});
