/**
 * VIEW-06: wheel-device normalization, the ctrl/pinch branch, two-axis pan and
 * two-pointer pinch.
 *
 * The four defects this file gates were measured on the shipped build:
 * a pixel-mode click zoomed −9.5 % while the SAME notch in line mode zoomed
 * −0.3 % (32× less); five `deltaX: 120` swipes moved a 5672 px document by
 * exactly 0 px; `ctrlKey` was unbranched, so a two-finger scroll zoomed; and
 * `touch-action: none` was set with zero touch handlers.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

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
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);
  return { ...ctx, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

/** jsdom has no layout, so the canvas rect is zero — stub a real one. */
function sizeCanvas(canvas, w = 1600, h = 1000) {
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: w, bottom: h, width: w, height: h, x: 0, y: 0 });
}

function wheel(ctx, canvas, init) {
  const ev = new ctx.window.WheelEvent('wheel', { bubbles: true, cancelable: true, ...init });
  canvas.dispatchEvent(ev);
  return ev;
}

function pointer(ctx, canvas, type, init) {
  // jsdom 26 has no PointerEvent constructor; the app only reads clientX/Y,
  // pointerId and the modifier flags, so a MouseEvent carrying them is faithful.
  const ev = new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, ...init });
  Object.defineProperty(ev, 'pointerId', { value: init.pointerId, configurable: true });
  canvas.dispatchEvent(ev);
  return ev;
}

const vp = (ctx) => ctx.app.getState().viewport;

/* ── the pure normalizer ───────────────────────────────────────────────── */

test('deltaMode is normalized to pixels (VIEW-06)', async () => {
  const ctx = await loadBundle();
  const { normalizeWheel, LINE_PX } = ctx.MLView.__internal.gestures;
  assert.equal(normalizeWheel({ deltaX: 0, deltaY: 100, deltaMode: 0 }, 900).dy, 100, 'pixel mode is the identity');
  assert.equal(normalizeWheel({ deltaX: 0, deltaY: 3, deltaMode: 1 }, 900).dy, 3 * LINE_PX);
  assert.equal(normalizeWheel({ deltaX: 0, deltaY: 1, deltaMode: 2 }, 900).dy, 900, 'a page is the viewport');
  assert.equal(normalizeWheel({ deltaX: 0, deltaY: 1, deltaMode: 2 }, 0).dy, 800, 'and falls back when there is none');
  // A device that reports nothing must not produce NaN in the transform.
  assert.equal(normalizeWheel({ deltaY: undefined, deltaX: null, deltaMode: undefined }, 900).dy, 0);
});

test('a line-mode notch zooms the same as a pixel-mode notch, within 10% (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const before = vp(ctx).zoom;
  wheel(ctx, ctx.canvas, { deltaY: 100, deltaMode: 0, clientX: 800, clientY: 500 });
  const pixelZoom = vp(ctx).zoom;
  const pixelDelta = (pixelZoom - before) / before;

  ctx.app.setTheme('light');
  const ctx2 = await app();
  sizeCanvas(ctx2.canvas);
  const before2 = vp(ctx2).zoom;
  // Firefox reports one notch as 3 LINES where Chromium reports 100 px.
  wheel(ctx2, ctx2.canvas, { deltaY: 3, deltaMode: 1, clientX: 800, clientY: 500 });
  const lineDelta = (vp(ctx2).zoom - before2) / before2;

  assert.ok(pixelDelta < -0.05, 'a pixel-mode notch still zooms out ~9.5%: ' + pixelDelta);
  assert.ok(
    Math.abs(lineDelta - pixelDelta) <= Math.abs(pixelDelta) * 0.1,
    'line mode ' + lineDelta + ' is within 10% of pixel mode ' + pixelDelta,
  );
});

test('the pixel-mode mouse path is bit-identical to the shipped one (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const start = { ...vp(ctx) };
  wheel(ctx, ctx.canvas, { deltaY: 100, deltaMode: 0, clientX: 400, clientY: 300 });
  const after = vp(ctx);
  // Exactly what `zoomAt(0.999 ** deltaY, px, py)` produced before VIEW-06.
  const factor = Math.pow(0.999, 100);
  const expectedZoom = start.zoom * factor;
  const k = expectedZoom / start.zoom;
  assert.ok(Math.abs(after.zoom - expectedZoom) < 1e-12, after.zoom + ' vs ' + expectedZoom);
  assert.ok(Math.abs(after.x - (400 - (400 - start.x) * k)) < 1e-9, 'anchored at the cursor in x');
  assert.ok(Math.abs(after.y - (300 - (300 - start.y) * k)) < 1e-9, 'anchored at the cursor in y');
});

/* ── the branch ────────────────────────────────────────────────────────── */

test('plain two-axis wheel pans, ctrl+wheel zooms (VIEW-06)', async () => {
  const ctx = await loadBundle();
  const { normalizeWheel, wheelIntent } = ctx.MLView.__internal.gestures;
  const intent = (ev) => wheelIntent(ev, normalizeWheel(ev, 900));
  assert.equal(intent({ deltaX: 0, deltaY: 100, deltaMode: 0 }), 'zoom', 'a coarse mouse notch still zooms');
  assert.equal(intent({ deltaX: 0, deltaY: 8, deltaMode: 0 }), 'pan', 'a fine trackpad glide scrolls');
  assert.equal(intent({ deltaX: 120, deltaY: 0, deltaMode: 0 }), 'pan', 'a horizontal swipe pans');
  assert.equal(intent({ deltaX: 4, deltaY: 60, deltaMode: 0 }), 'pan', 'a two-axis glide pans');
  assert.equal(intent({ deltaX: 0, deltaY: 6, deltaMode: 0, ctrlKey: true }), 'zoom', 'a pinch zooms');
  assert.equal(intent({ deltaX: 0, deltaY: 100, deltaMode: 0, ctrlKey: true }), 'zoom', 'and so does ctrl+wheel');
  assert.equal(intent({ deltaX: 0, deltaY: 100, deltaMode: 0, shiftKey: true }), 'pan', 'shift+wheel is the browser pan');
});

test('five deltaX swipes pan the world horizontally at unchanged zoom (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const start = { ...vp(ctx) };
  for (let i = 0; i < 5; i++) wheel(ctx, ctx.canvas, { deltaX: 120, deltaY: 0, deltaMode: 0, clientX: 800, clientY: 500 });
  const after = vp(ctx);
  assert.equal(after.zoom, start.zoom, 'panning never changes the zoom');
  assert.equal(after.y, start.y, 'nor the other axis');
  assert.equal(after.x, start.x - 600, 'five 120 px swipes move the world 600 px: ' + (start.x - after.x));
});

test('shift+wheel pans horizontally from a vertical delta (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const start = { ...vp(ctx) };
  wheel(ctx, ctx.canvas, { deltaX: 0, deltaY: 100, deltaMode: 0, shiftKey: true, clientX: 800, clientY: 500 });
  const after = vp(ctx);
  assert.equal(after.zoom, start.zoom);
  assert.equal(after.x, start.x - 100);
  assert.equal(after.y, start.y);
});

test('ctrl+wheel zooms about the cursor, and a pinch delta is amplified (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const start = { ...vp(ctx) };
  wheel(ctx, ctx.canvas, { deltaX: 0, deltaY: -6, deltaMode: 0, ctrlKey: true, clientX: 200, clientY: 150 });
  const after = vp(ctx);
  const { ZOOM_BASE, PINCH_GAIN } = ctx.MLView.__internal.gestures;
  const expected = start.zoom * Math.pow(ZOOM_BASE, -6 * PINCH_GAIN);
  assert.ok(after.zoom > start.zoom, 'a pinch-open zooms in');
  assert.ok(Math.abs(after.zoom - expected) < 1e-12, after.zoom + ' vs ' + expected);
  const k = after.zoom / start.zoom;
  assert.ok(Math.abs(after.x - (200 - (200 - start.x) * k)) < 1e-9, 'anchored at the cursor');
  // A trackpad pinch of 6 px must actually move: 0.999^-6 alone is +0.6%.
  assert.ok((after.zoom - start.zoom) / start.zoom > 0.03, 'a pinch is responsive, not a slow wheel');
});

test('a page-mode wheel is normalized by the canvas height (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas, 1600, 900);
  const start = { ...vp(ctx) };
  wheel(ctx, ctx.canvas, { deltaX: 0, deltaY: 1, deltaMode: 2, clientX: 800, clientY: 450 });
  // 1 page = 900 px, which is coarse and axis-locked, so it zooms.
  assert.ok(Math.abs(vp(ctx).zoom - start.zoom * Math.pow(0.999, 900)) < 1e-12);
});

/* ── two-pointer pinch ─────────────────────────────────────────────────── */

test('a two-pointer pinch zooms and its midpoint pans (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  const start = { ...vp(ctx) };
  pointer(ctx, ctx.canvas, 'pointerdown', { pointerId: 1, clientX: 700, clientY: 500 });
  pointer(ctx, ctx.canvas, 'pointerdown', { pointerId: 2, clientX: 900, clientY: 500 });
  // Fingers move apart from 200 px to 400 px about the same midpoint.
  pointer(ctx, ctx.canvas, 'pointermove', { pointerId: 1, clientX: 600, clientY: 500 });
  pointer(ctx, ctx.canvas, 'pointermove', { pointerId: 2, clientX: 1000, clientY: 500 });
  const after = vp(ctx);
  assert.ok(after.zoom > start.zoom * 1.5, 'a 2x spread roughly doubles the zoom: ' + after.zoom + ' from ' + start.zoom);
  pointer(ctx, ctx.canvas, 'pointerup', { pointerId: 2, clientX: 1000, clientY: 500 });
  pointer(ctx, ctx.canvas, 'pointerup', { pointerId: 1, clientX: 600, clientY: 500 });
});

test('a second finger takes the gesture away from the one-pointer pan (VIEW-06)', async () => {
  const ctx = await app();
  sizeCanvas(ctx.canvas);
  pointer(ctx, ctx.canvas, 'pointerdown', { pointerId: 1, clientX: 700, clientY: 500 });
  assert.ok(ctx.canvas.classList.contains('is-panning'), 'one finger pans');
  pointer(ctx, ctx.canvas, 'pointerdown', { pointerId: 2, clientX: 900, clientY: 500 });
  assert.equal(ctx.canvas.classList.contains('is-panning'), false, 'two fingers pinch instead');
  const zoomed = { ...vp(ctx) };
  // A pure translation of both fingers pans without zooming.
  pointer(ctx, ctx.canvas, 'pointermove', { pointerId: 1, clientX: 720, clientY: 500 });
  pointer(ctx, ctx.canvas, 'pointermove', { pointerId: 2, clientX: 920, clientY: 500 });
  const after = vp(ctx);
  assert.ok(Math.abs(after.zoom - zoomed.zoom) < 1e-9, 'a parallel drag does not scale');
  assert.ok(after.x > zoomed.x, 'it pans with the midpoint');
});
