// Reveal in Diagram and the review walk keep the cards they bring into view clear of the phase
// index (the panel of rows, or the pill below 1000 px).
//
// - `clearOfAll` (render/canvas.ts) moves a connection's two end cards off the index together; the
//   empty corner of their union may stay under it. Pure, compiled from the sources here.
// - `ViewportController.frameClear` frames a union at the first zoom, from the current one down to
//   a floor, at which both end cards fit on the canvas and clear of the index. A Reveal in Diagram
//   of a connection uses it (`frameEdge`), and so does a step of the walk onto a connection whose
//   union fits the canvas but not the room the index leaves, down to READABLE_MIN_ZOOM.
// - After a move the index can change shape (the pill names the phase in view), so the target is
//   cleared once more of the index as it is then: by `revealRect`, `centerOn`, `frameRect`'s anchor
//   step and `frameClear`, each checked on its own with an index that follows the applied transform.
// - Focusing a card or a connection never scrolls the canvas, and a canvas that shrinks after a
//   reveal (the sheet's height landing a frame later) keeps the revealed card, or both cards of a
//   revealed connection, in view. A card the reader left under the index stays there on a resize.
// - The zoom floors: a Reveal and a resize never frame below FRAME_MIN_ZOOM (0.45), a walk step
//   never below READABLE_MIN_ZOOM (0.75), and a walk step only pans a connection too large for
//   the canvas. Each is checked on a fixture whose cards would clear the index only below it.
// - A zoom a shrinking canvas took from a selected connection is given back when the canvas grows
//   again, unless the reader has zoomed since: to that connection on any growth, as far as the
//   canvas holds it, and to anything else once the canvas has the room back that the shrink took:
//   whole, or to another connection in view as far as the canvas holds its cards, what that leaves
//   staying on loan for the next growth.
//   An index that changed shape (hidden, folded, its list closed) is what the next resize judges
//   "was in view" by.
//
// The fixtures are synthetic: the two generated documents of helpers.mjs, also with another seed,
// and hand-placed rectangles. jsdom lays nothing out: the panel and canvas boxes are stubbed as in
// reveal.test.mjs, and the index is its jsdom fallback (the pill or the panel at its widest) or a
// rectangle a test sets. The viewer is the built bundle, mounted in jsdom.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { build } from 'esbuild';
import { loadBundle, recordingBridge, shapedWorkflow, SHAPE_79_CLAIMS, WEBVIEW_ROOT, SHAPE_176_CLAIMS } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));

let sourcePromise = null;
/** The pure geometry as one ES module (nothing touches the DOM on import). */
function source() {
  if (!sourcePromise) {
    sourcePromise = build({
      stdin: {
        contents: "export { clearOf, clearOfAll, rectsOverlap } from './render/canvas.ts';",
        resolveDir: join(WEBVIEW_ROOT, 'src'),
        loader: 'ts',
        sourcefile: 'phase-index-clear-entry.ts',
      },
      bundle: true,
      format: 'esm',
      platform: 'neutral',
      write: false,
      logLevel: 'silent',
    }).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));
  }
  return sourcePromise;
}

const RAIL_W = 360;
const SHEET_SHARE = 0.47;

/**
 * Mount `document` in a panel `width` px wide whose body is `bodyH` px, as reveal.test.mjs does.
 * `ctx.hold()` keeps the canvas at its size until `ctx.release()`: the case, under reduced motion
 * (which the mount turns on), where the sheet's new height reaches the canvas a frame after the
 * reveal that opened it. `ctx.resize(w, h)` makes the panel `w` px wide, its body `h` px when given.
 */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  ctx.document.body.classList.add('vscode-reduce-motion');
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 1440;
  let bodyH = opts.bodyH || 842;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: bodyH + 58, right: width, bottom: bodyH + 58 });
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const rail = ctx.document.querySelector('.mlv-rail');
  let held = null;
  const measure = () => {
    const docked = rail.getAttribute('data-mode') !== 'sheet';
    const w = docked ? width - (rail.hidden ? 0 : RAIL_W) : width;
    const sheet = docked ? 0 : rail.getAttribute('data-expanded') === 'true' ? Math.round(bodyH * SHEET_SHARE) : 32;
    return { w, h: bodyH - sheet };
  };
  const box = () => held || measure();
  canvas.getBoundingClientRect = () => {
    const { w, h } = box();
    return { x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h };
  };
  ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  app.view.fit();
  canvas.focus();
  // The canvas keeps the size it has now until `release`, which reports the new one as a resize.
  const hold = () => {
    held = measure();
  };
  const release = () => {
    held = null;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  // The panel becomes `w` px wide (and its body `h` px), reported as a resize.
  const resize = (w, h = bodyH) => {
    width = w;
    bodyH = h;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  return { ...ctx, root, bridge, app, canvas, rail, box, hold, release, resize };
}

const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const boxOf = (ctx, id) => ctx.app.view.frameData.boxes.get(ctx.app.index.visibleRepresentative(id, ctx.app.view.collapsed));
function onScreen(ctx, b) {
  const vp = ctx.app.getState().viewport;
  return { x: b.x * vp.zoom + vp.x, y: b.y * vp.zoom + vp.y, w: b.w * vp.zoom, h: b.h * vp.zoom };
}
/** Why the card `id` is not wholly on the canvas and clear of the phase index, or null. */
function offScreen(ctx, id) {
  const s = onScreen(ctx, boxOf(ctx, id));
  const { w, h } = ctx.box();
  if (!(s.x >= -0.5 && s.y >= -0.5 && s.x + s.w <= w + 0.5 && s.y + s.h <= h + 0.5)) return `${id}: card ${s.x.toFixed(0)},${s.y.toFixed(0)} ${s.w.toFixed(0)}x${s.h.toFixed(0)} outside the canvas ${w}x${h}`;
  const covered = ctx.app.view.viewport.covered();
  if (covered && overlaps(s, covered)) return `${id}: card under the phase index`;
  return null;
}
function unionOf(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
}
const reveal = (ctx, kind, id) => ctx.bridge.send({ v: 1, type: 'reveal', kind, id });
const press = (ctx, key, target = ctx.document.activeElement || ctx.canvas) => {
  const event = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
};
const click = (ctx, element) => element.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
const zoomOf = (ctx) => ctx.app.getState().viewport.zoom;
/** The reader pans (the zoom kept, or set to `zoom`) so that the two cards of `edge` are centred on the canvas. */
function centreEnds(ctx, edge, zoom = zoomOf(ctx)) {
  const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
  const { w, h } = ctx.box();
  ctx.app.view.viewport.set({ zoom, x: w / 2 - (union.x + union.w / 2) * zoom, y: h / 2 - (union.y + union.h / 2) * zoom });
}
/** The reader pans so that the card `id` is centred on the screen rectangle `r` (canvas pixels). */
function panCardOnto(ctx, id, r) {
  const box = boxOf(ctx, id);
  const zoom = zoomOf(ctx);
  ctx.app.view.viewport.set({ x: r.x + r.w / 2 - (box.x + box.w / 2) * zoom, y: r.y + r.h / 2 - (box.y + box.h / 2) * zoom });
}

/* ── clearOfAll ──────────────────────────────────────────────────────── */

test('clearOfAll: the least pan that puts every card on the canvas and clear of the index, the empty corner of their union aside', async () => {
  const { clearOf, clearOfAll, rectsOverlap } = await source();
  const pill = { x: 300, y: 352, w: 229, h: 28 };
  // Clear and on the canvas: no move.
  assert.deepEqual(plain(clearOfAll([{ x: 10, y: 10, w: 100, h: 50 }, { x: 200, y: 100, w: 100, h: 50 }], pill, 541, 392)), { dx: 0, dy: 0 });
  // One card: the move clearOf makes, when it keeps the card on the canvas.
  const card = { x: 360, y: 300, w: 150, h: 70 };
  assert.deepEqual(plain(clearOfAll([card], pill, 541, 392)), plain(clearOf(card, pill, 541, 392)));
  // A tall end (an expanded group's frame) runs down beside the index, and the other end sits on it.
  // Their union cannot move off the index on the canvas; the two cards can: 12 px up, which leaves
  // the target 8 px above the index.
  const group = { x: 30, y: 16, w: 150, h: 360 };
  const target = { x: 360, y: 266, w: 150, h: 90 };
  assert.equal(clearOf({ x: 30, y: 16, w: 480, h: 360 }, pill, 541, 392), null, 'precondition: the union has nowhere to go');
  const shift = clearOfAll([group, target], pill, 541, 392);
  assert.deepEqual(plain(shift), { dx: 0, dy: -12 });
  for (const p of [group, target]) {
    const moved = { ...p, x: p.x + shift.dx, y: p.y + shift.dy };
    assert.ok(moved.y >= 0 && moved.y + moved.h <= 392 && !rectsOverlap(moved, pill), 'on the canvas and off the index');
  }
  // No pan does: the cards span the canvas's height and one is under the index.
  assert.equal(clearOfAll([{ x: 30, y: 0, w: 150, h: 80 }, { x: 360, y: 300, w: 150, h: 90 }], pill, 541, 392), null);
  // Nor here: 22 px up would put the top card against the canvas's edge and leave the other 4 px
  // above the index, and a card a pan moves off the index keeps `gap` (8 px) from it, as clearOf's do.
  assert.equal(clearOfAll([{ x: 40, y: 22, w: 145, h: 77 }, { x: 357, y: 293, w: 145, h: 77 }], pill, 541, 392), null);
  // Cards partly off the canvas are brought onto it (the index aside, the least pan).
  assert.deepEqual(plain(clearOfAll([{ x: -20, y: 10, w: 100, h: 50 }], pill, 541, 392)), { dx: 20, dy: 0 });
  // No index: only onto the canvas; nothing to place: no move.
  assert.deepEqual(plain(clearOfAll([{ x: 10, y: 380, w: 100, h: 50 }], null, 541, 392)), { dx: 0, dy: -38 });
  assert.deepEqual(plain(clearOfAll([], pill, 541, 392)), { dx: 0, dy: 0 });
});

/* ── the viewport: frameClear, the index after a move ────────────────── */

/**
 * A mounted viewer whose canvas is `w` x `h` and whose phase index covers what `covered(applied)`
 * returns. `applied` is the viewport as drawn, read from the world's transform: the real index
 * changes only once a move is applied (the pill's text follows the viewport's change callback), so
 * an index read from `vp`, which a move sets before it applies it, would be cleared by the move's
 * own pass off the index and test nothing after it.
 */
async function bareViewport(w, h, covered) {
  const ctx = await mount(shapedWorkflow(SHAPE_176_CLAIMS), { width: 1440, bodyH: 842 });
  ctx.canvas.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: w, height: h, right: w, bottom: h });
  const vpc = ctx.app.view.viewport;
  const applied = () => {
    const m = /translate\(([-\d.e]+)px,\s*([-\d.e]+)px\)\s*scale\(([-\d.e]+)\)/.exec(vpc.world.style.transform);
    assert.ok(m, `a transform is applied (${vpc.world.style.transform})`);
    return { x: Number(m[1]), y: Number(m[2]), zoom: Number(m[3]) };
  };
  vpc.setCovered(() => covered(applied()));
  const screen = (r) => ({ x: r.x * vpc.vp.zoom + vpc.vp.x, y: r.y * vpc.vp.zoom + vpc.vp.y, w: r.w * vpc.vp.zoom, h: r.h * vpc.vp.zoom });
  const clear = (r, index) => {
    const s = screen(r);
    return s.x >= -0.01 && s.y >= -0.01 && s.x + s.w <= w + 0.01 && s.y + s.h <= h + 0.01 && !overlaps(s, index);
  };
  return { ...ctx, vpc, screen, clear };
}

test('frameClear: the first zoom, from the current one down to the floor, at which both end cards fit on the canvas and clear of the index', async () => {
  const pill = { x: 300, y: 352, w: 229, h: 28 };
  const ctx = await bareViewport(541, 392, () => pill);
  try {
    const { vpc } = ctx;
    // The tall end (a group's frame) beside the index, the other end on it: 12 px up, same zoom.
    const group = { x: 0, y: 0, w: 150, h: 360 };
    const target = { x: 330, y: 250, w: 150, h: 90 };
    const union = { x: 0, y: 0, w: 480, h: 360 };
    vpc.set({ x: 0, y: 0, zoom: 1 });
    assert.equal(vpc.frameClear(union, [group, target], { margin: 16 }), true);
    assert.deepEqual(plain(vpc.vp), { x: 30.5, y: 4, zoom: 1 }, 'centred, then the least pan off the index');
    assert.ok(ctx.clear(group, pill) && ctx.clear(target, pill));
    // Corner to corner: no pan clears the target at 1, the first 5 % step down does.
    const top = { x: 0, y: 0, w: 150, h: 80 };
    const corner = { x: 330, y: 280, w: 150, h: 80 };
    vpc.set({ x: 0, y: 0, zoom: 1 });
    assert.equal(vpc.frameClear(union, [top, corner], { margin: 16 }), true);
    assert.equal(vpc.vp.zoom, 0.95);
    assert.ok(ctx.clear(top, pill) && ctx.clear(corner, pill));
    // Above the floor there is none: nothing moves.
    vpc.set({ x: 7, y: 9, zoom: 1 });
    assert.equal(vpc.frameClear(union, [top, corner], { margin: 16, floor: 0.99 }), false);
    assert.deepEqual(plain(vpc.vp), { x: 7, y: 9, zoom: 1 });
  } finally {
    ctx.app.destroy();
  }
});

test('frameClear with no floor given stops at FRAME_MIN_ZOOM (0.45): a union that fits the canvas only under it is refused, and nothing moves', async () => {
  const pill = { x: 300, y: 352, w: 229, h: 28 };
  const ctx = await bareViewport(541, 392, () => pill);
  try {
    const { vpc } = ctx;
    const top = { x: 0, y: 0, w: 150, h: 80 };
    const far = { x: 1050, y: 280, w: 150, h: 80 };
    // (541 - 16) / 1200 = 0.4375, where both cards would sit on the canvas clear of the pill.
    vpc.set({ x: 7, y: 9, zoom: 1 });
    assert.equal(vpc.frameClear({ x: 0, y: 0, w: 1200, h: 360 }, [top, far], { margin: 16 }), false);
    assert.deepEqual(plain(vpc.vp), { x: 7, y: 9, zoom: 1 });
    // The same frame with a lower floor is taken, so only the floor refused it.
    assert.equal(vpc.frameClear({ x: 0, y: 0, w: 1200, h: 360 }, [top, far], { margin: 16, floor: 0.4 }), true);
    assert.ok(vpc.vp.zoom < 0.45 && vpc.vp.zoom >= 0.4, `framed under 0.45 (${vpc.vp.zoom})`);
  } finally {
    ctx.app.destroy();
  }
});

// Each pass is checked on its own: with any one of them removed, its case leaves the card under the
// index the move brought in.
test('after a move the target is cleared once more of the index as it is then (the pill widens with the phase it names): revealRect and centerOn', async () => {
  // revealRect: a card comes in from below beside the narrow pill; the move widens it over the card.
  const narrow = { x: 400, y: 352, w: 129, h: 28 };
  const wide = { x: 300, y: 352, w: 229, h: 28 };
  let ctx = await bareViewport(541, 392, (vp) => (vp.y < 400 ? wide : narrow));
  try {
    const card = { x: 0, y: 0, w: 194, h: 97 };
    ctx.vpc.set({ x: 200, y: 500, zoom: 1 });
    ctx.vpc.revealRect(card);
    assert.ok(ctx.clear(card, wide), `the card ${JSON.stringify(ctx.screen(card))} is clear of the widened pill`);
  } finally {
    ctx.app.destroy();
  }
  // centerOn: the index the move brings in covers the centre.
  const corner = { x: 0, y: 0, w: 1, h: 1 };
  const middle = { x: 200, y: 150, w: 141, h: 92 };
  ctx = await bareViewport(541, 392, (vp) => (vp.x < 1000 ? middle : corner));
  try {
    const card = { x: 0, y: 0, w: 100, h: 50 };
    ctx.vpc.set({ x: 5000, y: 0, zoom: 1 });
    ctx.vpc.centerOn(card);
    assert.ok(ctx.clear(card, middle), `the card ${JSON.stringify(ctx.screen(card))} is clear of the index it moved under`);
  } finally {
    ctx.app.destroy();
  }
});

test("after a move the target is cleared once more of the index as it is then: frameRect's anchor step and frameClear", async () => {
  // frameRect: the union fills the canvas's height, so centring cannot move it off the index; the
  // anchor's own pass off it (keepClear) moves it up, and that move brings in a taller index.
  const low = { x: 300, y: 340, w: 229, h: 40 };
  const tall = { x: 300, y: 300, w: 229, h: 80 };
  let ctx = await bareViewport(541, 392, (vp) => (vp.y < -4 ? tall : low));
  try {
    const union = { x: 0, y: 0, w: 480, h: 344 };
    const anchor = { x: 330, y: 250, w: 150, h: 90 };
    ctx.vpc.set({ x: 0, y: 0, zoom: 1 });
    ctx.vpc.frameRect(union, anchor, 0.9);
    assert.equal(ctx.vpc.vp.zoom, 1, 'the union fits at 1: centred and kept');
    assert.ok(ctx.clear(anchor, tall), `the anchor ${JSON.stringify(ctx.screen(anchor))} is clear of the taller index`);
  } finally {
    ctx.app.destroy();
  }
  // frameClear: both cards clear of the pill where the frame centres them; the frame brings in the
  // taller index over the lower card.
  const pill = { x: 300, y: 352, w: 229, h: 28 };
  ctx = await bareViewport(541, 392, (vp) => (vp.y > 0 ? tall : pill));
  try {
    const top = { x: 0, y: 0, w: 150, h: 80 };
    const corner = { x: 330, y: 200, w: 150, h: 80 };
    ctx.vpc.set({ x: 0, y: 0, zoom: 1 });
    assert.equal(ctx.vpc.frameClear({ x: 0, y: 0, w: 480, h: 280 }, [top, corner], { margin: 16 }), true);
    assert.equal(ctx.vpc.vp.zoom, 1);
    assert.ok(ctx.clear(top, tall) && ctx.clear(corner, tall), `the cards ${JSON.stringify([ctx.screen(top), ctx.screen(corner)])} are clear of the taller index`);
  } finally {
    ctx.app.destroy();
  }
});

/* ── Reveal in Diagram and the walk, at 541 px ───────────────────────── */

test('Reveal in Diagram of a connection whose ends are too far apart for the room above or beside the index: both cards clear of it (the 176-claim shape, seed 1, 541x798)', async () => {
  const document = shapedWorkflow({ ...SHAPE_176_CLAIMS, seed: 1 });
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    reveal(ctx, 'edge', 'c93');
    const edge = document.edges.find((e) => e.id === 'c93');
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    const covered = ctx.app.view.viewport.covered();
    const { w, h } = ctx.box();
    // Precondition: at the floor the frame fits the canvas, but neither the room above the index
    // nor the room beside it.
    assert.ok(ctx.app.view.viewport.fitsAt(union, 0.45), 'fits the canvas at 0.45');
    assert.ok((h - covered.h - 48) / union.h < 0.45, 'too tall for the room above the index');
    assert.ok((w - covered.w - 48) / union.w < 0.45, 'too wide for the room beside it');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.ok(ctx.app.getState().viewport.zoom >= 0.45);
  } finally {
    ctx.app.destroy();
  }
});

test('a walk step onto a connection that fits the canvas, but whose cards no pan clears of the index, is framed down to 0.75 with both cards clear (the 176-claim shape, 541x798)', async () => {
  const { clearOfAll } = await source();
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    assert.equal(ctx.app.walk.start('all'), true);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'c82'; i++) ctx.app.walk.step(1);
    assert.equal(ctx.app.walk.current().id, 'c82');
    const edge = document.edges.find((e) => e.id === 'c82');
    const ends = [boxOf(ctx, edge.source), boxOf(ctx, edge.target)];
    const union = unionOf(ends[0], ends[1]);
    const covered = ctx.app.view.viewport.covered();
    const { w, h } = ctx.box();
    // Precondition: at reading size the union fits the canvas, yet no pan clears both cards of the index.
    assert.ok(union.w * 0.9 <= w && union.h * 0.9 <= h, 'fits the canvas at 0.9');
    assert.equal(clearOfAll(ends.map((b) => ({ x: b.x * 0.9, y: b.y * 0.9, w: b.w * 0.9, h: b.h * 0.9 })), covered, w, h), null, 'no pan at 0.9 clears both');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    const zoom = ctx.app.getState().viewport.zoom;
    assert.ok(zoom >= 0.75 && zoom < 0.9, `zoomed out a little, to 0.75 or more (${zoom})`);
  } finally {
    ctx.app.destroy();
  }
});

test('Reveal in Diagram of a connection whose cards do not fit the canvas at 0.45 stays at 0.45, on its source card (the 79-claim shape, c1, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    reveal(ctx, 'edge', 'c1');
    const edge = document.edges.find((e) => e.id === 'c1');
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    assert.equal(ctx.app.view.viewport.fitsAt(union, 0.45), false, 'precondition: the two cards do not fit at 0.45');
    assert.ok(ctx.app.view.viewport.fitsAt(union, 0.2), 'precondition: they would at 0.2');
    assert.equal(zoomOf(ctx), 0.45, 'the floor, not the zoom that fits');
    assert.equal(offScreen(ctx, edge.source), null, 'the source card is whole and clear of the index');
  } finally {
    ctx.app.destroy();
  }
});

test('a walk step onto a connection too large for the canvas at reading size is only panned: the zoom is kept (the 79-claim shape, c11, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    assert.equal(ctx.app.walk.start('all'), true);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'c11'; i++) ctx.app.walk.step(1);
    assert.equal(ctx.app.walk.current().id, 'c11');
    const edge = document.edges.find((e) => e.id === 'c11');
    const ends = [boxOf(ctx, edge.source), boxOf(ctx, edge.target)];
    const union = unionOf(ends[0], ends[1]);
    const { w, h } = ctx.box();
    // Precondition: too large for the canvas at reading size, yet it would fit at 0.75 or more with
    // the frame's 32 px margin, so a frame would zoom out; and the pan left an end card out of view.
    assert.ok(union.w * 0.9 > w || union.h * 0.9 > h, 'does not fit the canvas at 0.9');
    assert.ok(Math.min((w - 32) / union.w, (h - 32) / union.h) >= 0.75, 'would fit at 0.75 or more');
    assert.ok(!(ctx.app.view.viewport.isVisible(ends[0]) && ctx.app.view.viewport.isVisible(ends[1])), 'an end card is out of view after the pan');
    assert.equal(zoomOf(ctx), 0.9, 'only panned');
  } finally {
    ctx.app.destroy();
  }
});

test('a walk step onto a connection whose cards clear the index only under 0.75 keeps its zoom (the 176-claim shape, seed 1, c27, 1440 px)', async () => {
  const document = shapedWorkflow({ ...SHAPE_176_CLAIMS, seed: 1 });
  const ctx = await mount(document, { width: 1440, bodyH: 842 });
  try {
    assert.equal(ctx.app.walk.start('all'), true);
    let before = zoomOf(ctx);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'c27'; i++) {
      before = zoomOf(ctx);
      ctx.app.walk.step(1);
    }
    assert.equal(ctx.app.walk.current().id, 'c27');
    const edge = document.edges.find((e) => e.id === 'c27');
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    assert.ok(before >= 0.75, `precondition: the walk is at reading size (${before})`);
    assert.ok(ctx.app.view.viewport.fitsAt(union, before, 0), 'precondition: the two cards fit the canvas at that zoom');
    assert.ok(offScreen(ctx, edge.source) || offScreen(ctx, edge.target), 'precondition: no zoom from there down to 0.75 clears both cards');
    assert.equal(zoomOf(ctx), before, 'not zoomed out under 0.75');
  } finally {
    ctx.app.destroy();
  }
});

/** Walk the "All claims" filter to the claim before connection `id`, fit the whole diagram from the ⋯ menu, and step onto it. */
function stepFromWholeFit(ctx, id) {
  assert.equal(ctx.app.walk.start('all'), true);
  const at = ctx.app.walk.list.findIndex((claim) => claim.kind === 'edge' && claim.id === id);
  assert.ok(at > 0, `the walk holds ${id}`);
  for (let i = 1; i < at; i++) ctx.app.walk.step(1);
  click(ctx, ctx.document.querySelector('[data-more-item="fit"]'));
  assert.ok(zoomOf(ctx) < 0.62, `precondition: the whole diagram is below the detail threshold (${zoomOf(ctx)})`);
  ctx.app.walk.step(1);
  assert.equal(ctx.app.walk.current().id, id);
}

test('a walk step onto a connection from below the detail threshold is framed like one at reading size: both cards clear of the index, at 0.75 or more (the 176-claim shape, c82, 541x798)', async () => {
  const { clearOfAll } = await source();
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    stepFromWholeFit(ctx, 'c82');
    const edge = document.edges.find((e) => e.id === 'c82');
    const ends = [boxOf(ctx, edge.source), boxOf(ctx, edge.target)];
    const union = unionOf(ends[0], ends[1]);
    const covered = ctx.app.view.viewport.covered();
    const { w, h } = ctx.box();
    // Precondition: the step zooms in to the largest zoom that fits the two cards (a 39 px margin on
    // a canvas this short), where no pan clears both of the index.
    const landed = Math.min(0.9, (w - 39) / union.w, (h - 39) / union.h);
    assert.ok(landed >= 0.75, `the two cards fit at reading size (${landed})`);
    assert.equal(clearOfAll(ends.map((b) => ({ x: b.x * landed, y: b.y * landed, w: b.w * landed, h: b.h * landed })), covered, w, h), null, 'no pan at that zoom clears both');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.ok(zoomOf(ctx) >= 0.75 && zoomOf(ctx) < landed, `zoomed out a little, to 0.75 or more (${zoomOf(ctx)})`);
  } finally {
    ctx.app.destroy();
  }
});

test('a walk step from below the detail threshold onto a connection that fits only under 0.75 is panned clear of the index, not zoomed out again (the 176-claim shape, c22, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    stepFromWholeFit(ctx, 'c22');
    const edge = document.edges.find((e) => e.id === 'c22');
    const ends = [boxOf(ctx, edge.source), boxOf(ctx, edge.target)];
    const union = unionOf(ends[0], ends[1]);
    const covered = ctx.app.view.viewport.covered();
    const { w, h } = ctx.box();
    const landed = Math.min(0.9, (w - 39) / union.w, (h - 39) / union.h);
    assert.ok(landed >= 0.62 && landed < 0.75, `precondition: the two cards fit only between 0.62 and 0.75 (${landed})`);
    // Precondition: centred at that zoom, an end card is under the index.
    const centred = { x: w / 2 - (union.x + union.w / 2) * landed, y: h / 2 - (union.y + union.h / 2) * landed };
    assert.ok(ends.some((b) => overlaps({ x: b.x * landed + centred.x, y: b.y * landed + centred.y, w: b.w * landed, h: b.h * landed }, covered)), 'centred, a card is under the index');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.equal(zoomOf(ctx), landed, 'the zoom the step landed at');
  } finally {
    ctx.app.destroy();
  }
});

test('a walk step from below the detail threshold onto a connection whose cards clear the index only under 0.75 is not zoomed out under 0.75 (the 176-claim shape, seed 1, c27, 1440 px)', async () => {
  const document = shapedWorkflow({ ...SHAPE_176_CLAIMS, seed: 1 });
  const ctx = await mount(document, { width: 1440, bodyH: 842 });
  try {
    stepFromWholeFit(ctx, 'c27');
    const edge = document.edges.find((e) => e.id === 'c27');
    assert.ok(zoomOf(ctx) >= 0.75 && zoomOf(ctx) < 0.9, `the step landed at reading size, under 0.9 (${zoomOf(ctx)})`);
    assert.ok(offScreen(ctx, edge.source) || offScreen(ctx, edge.target), 'precondition: no zoom from there down to 0.75 clears both cards');
  } finally {
    ctx.app.destroy();
  }
});

test('the card a reveal centred stays in view, clear of the index, when the opening sheet shrinks the canvas a frame later', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    assert.equal(ctx.rail.getAttribute('data-mode'), 'sheet');
    ctx.app.collapseSheet(false);
    assert.equal(ctx.box().h, 708, 'precondition: the sheet is collapsed');
    ctx.hold();
    reveal(ctx, 'node', 'n30');
    assert.equal(ctx.rail.getAttribute('data-expanded'), 'true', 'the reveal opened the sheet');
    assert.equal(offScreen(ctx, 'n30'), null, 'centred on the canvas it still had');
    ctx.release();
    assert.equal(ctx.box().h, 392, 'the canvas is now above the open sheet');
    assert.equal(offScreen(ctx, 'n30'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('both cards of a connection a reveal framed stay in view, clear of the index, when the opening sheet shrinks the canvas a frame later (the 79-claim shape, c4)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    ctx.hold();
    reveal(ctx, 'edge', 'c4');
    assert.equal(ctx.rail.getAttribute('data-expanded'), 'true', 'the reveal opened the sheet');
    const edge = document.edges.find((e) => e.id === 'c4');
    assert.equal(offScreen(ctx, edge.source), null, 'framed on the canvas it still had');
    assert.equal(offScreen(ctx, edge.target), null, 'framed on the canvas it still had');
    const framed = ctx.app.getState().viewport.zoom;
    ctx.release();
    const { w, h } = ctx.box();
    assert.equal(h, 392, 'the canvas is now above the open sheet');
    // Precondition: at the frame's zoom the two cards do not fit the shorter canvas, so no pan shows
    // both; at 0.45 they do.
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    assert.ok(union.h * framed > h, `the cards span ${Math.round(union.h * framed)} px at ${framed}, taller than ${h}`);
    assert.ok(Math.min((w - 48) / union.w, (h - 48) / union.h) >= 0.45, 'they fit at 0.45');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    const zoom = ctx.app.getState().viewport.zoom;
    assert.ok(zoom < framed && zoom >= 0.45, `zoomed out, to 0.45 or more (${zoom})`);
  } finally {
    ctx.app.destroy();
  }
});

test('a revealed connection whose cards do not fit the shorter canvas at 0.45 keeps its zoom when the opening sheet shrinks the canvas a frame later (the 79-claim shape, c5)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    ctx.hold();
    reveal(ctx, 'edge', 'c5');
    const edge = document.edges.find((e) => e.id === 'c5');
    assert.equal(offScreen(ctx, edge.source), null, 'framed on the canvas it still had');
    assert.equal(offScreen(ctx, edge.target), null, 'framed on the canvas it still had');
    const framed = zoomOf(ctx);
    ctx.release();
    const { w, h } = ctx.box();
    assert.equal(h, 392, 'the canvas is now above the open sheet');
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    const fits = Math.min((w - 48) / union.w, (h - 48) / union.h);
    assert.ok(fits < 0.45 && fits >= 0.2, `precondition: the cards fit the shorter canvas only at ${fits}`);
    assert.equal(zoomOf(ctx), framed, 'not zoomed out under 0.45');
  } finally {
    ctx.app.destroy();
  }
});

test('when no zoom down to 0.45 holds both cards of a revealed connection on the canvas the late sheet left, its source card is kept in view by a pan (the 176-claim shape, c15)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    ctx.hold();
    reveal(ctx, 'edge', 'c15');
    const edge = document.edges.find((e) => e.id === 'c15');
    assert.equal(offScreen(ctx, edge.source), null, 'framed on the canvas it still had');
    assert.equal(offScreen(ctx, edge.target), null, 'framed on the canvas it still had');
    const framed = zoomOf(ctx);
    ctx.release();
    assert.equal(ctx.box().h, 392, 'the canvas is now above the open sheet');
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    assert.equal(ctx.app.view.viewport.fitsAt(union, 0.45), false, 'precondition: the cards do not fit the shorter canvas at 0.45');
    assert.equal(offScreen(ctx, edge.source), null, 'the source card, where the connection starts');
    assert.equal(zoomOf(ctx), framed, 'by a pan alone');
  } finally {
    ctx.app.destroy();
  }
});

test('a connection too far apart for 0.45, which a reveal centres on its source card, keeps that card in view, clear of the index, when the opening sheet shrinks the canvas a frame later (the 176-claim shape, c0)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    ctx.hold();
    reveal(ctx, 'edge', 'c0');
    const edge = document.edges.find((e) => e.id === 'c0');
    assert.equal(zoomOf(ctx), 0.45, 'precondition: the cards do not fit at 0.45');
    assert.equal(offScreen(ctx, edge.source), null, 'centred on its source card, on the canvas it still had');
    assert.notEqual(offScreen(ctx, edge.target), null, 'precondition: the target card is not in view');
    ctx.release();
    assert.equal(ctx.box().h, 392, 'the canvas is now above the open sheet');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(zoomOf(ctx), 0.45, 'by a pan alone');
  } finally {
    ctx.app.destroy();
  }
});

/* ── a zoom a shrinking canvas took away is given back ───────────────── */

test('a click on a connection with the sheet collapsed zooms out to show both cards above the opening sheet, and collapsing the sheet gives the zoom back (the 79-claim shape, c14, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    const edge = document.edges.find((e) => e.id === 'c14');
    const hit = ctx.document.querySelector('.mlv-edge[data-edge-id="c14"] .mlv-edge__hit');
    ctx.app.collapseSheet(false);
    centreEnds(ctx, edge, 0.9);
    assert.equal(ctx.box().h, 708, 'precondition: the sheet is collapsed');
    assert.equal(offScreen(ctx, edge.source), null, 'precondition: both cards are in view at 0.9');
    assert.equal(offScreen(ctx, edge.target), null, 'precondition: both cards are in view at 0.9');
    const centred = plain(ctx.app.getState().viewport);
    click(ctx, hit);
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c14' });
    assert.equal(ctx.box().h, 392, 'the click opened the sheet');
    const opened = zoomOf(ctx);
    assert.ok(opened < 0.62, `zoomed out, here down to compact detail (${opened})`);
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    press(ctx, 'Escape');
    assert.equal(ctx.box().h, 708, 'Escape collapsed the sheet');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.equal(ctx.app.getState().framedZoom, undefined, 'it is the reader\'s zoom again');
    // A reader who zoomed while the sheet was open keeps that zoom.
    click(ctx, hit);
    assert.equal(zoomOf(ctx), opened, 'the same click again');
    press(ctx, '+');
    const chosen = zoomOf(ctx);
    assert.ok(chosen > opened && chosen < 0.9, `the reader zoomed in one step (${chosen})`);
    press(ctx, 'Escape');
    assert.equal(ctx.box().h, 708);
    assert.equal(zoomOf(ctx), chosen, 'not given back over a zoom the reader chose');
    // Nor one that left and returned: + then - is the reader's zoom too.
    ctx.app.view.viewport.set(centred);
    click(ctx, hit);
    assert.equal(zoomOf(ctx), opened);
    press(ctx, '+');
    press(ctx, '-');
    assert.equal(zoomOf(ctx), opened, 'precondition: + then - came back to the same zoom');
    press(ctx, 'Escape');
    assert.equal(zoomOf(ctx), opened, 'not given back after the reader zoomed');
  } finally {
    ctx.app.destroy();
  }
});

test('the zoom is given back whole when the two cards fit the canvas at it, also where they leave less than the frame\'s margin (the 176-claim shape, c21, from 1.0, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    const edge = document.edges.find((e) => e.id === 'c21');
    ctx.app.collapseSheet(false);
    centreEnds(ctx, edge, 1);
    const union = unionOf(boxOf(ctx, edge.source), boxOf(ctx, edge.target));
    const { w } = ctx.box();
    assert.ok(union.w <= w && union.w > w - 48, `precondition: at 1.0 the cards fit the canvas with less than 48 px to spare (${union.w} of ${w})`);
    assert.equal(offScreen(ctx, edge.source), null, 'precondition: both cards are in view at 1.0');
    assert.equal(offScreen(ctx, edge.target), null, 'precondition: both cards are in view at 1.0');
    click(ctx, ctx.document.querySelector('.mlv-edge[data-edge-id="c21"] .mlv-edge__hit'));
    assert.ok(zoomOf(ctx) < 1, `precondition: the click zoomed out (${zoomOf(ctx)})`);
    press(ctx, 'Escape');
    assert.equal(ctx.box().h, 708, 'Escape collapsed the sheet');
    assert.equal(zoomOf(ctx), 1, 'the zoom the reader had, not the largest that keeps the margin');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
  } finally {
    ctx.app.destroy();
  }
});

test('the zoom is given back to another selection, and to none: a card clicked while the sheet was open stays in view (the 79-claim shape, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const edge = document.edges.find((e) => e.id === 'c14');
  let ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    centreEnds(ctx, edge, 0.9);
    click(ctx, ctx.document.querySelector('.mlv-edge[data-edge-id="c14"] .mlv-edge__hit'));
    const opened = zoomOf(ctx);
    assert.ok(opened < 0.9, `precondition: the click zoomed out (${opened})`);
    click(ctx, ctx.app.view.nodeElement(edge.source));
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: edge.source });
    assert.equal(zoomOf(ctx), opened, 'a click on a card does not zoom');
    const vp = plain(ctx.app.getState().viewport);
    press(ctx, 'Escape');
    const { w, h } = ctx.box();
    assert.equal(h, 708, 'Escape collapsed the sheet');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    // Precondition: zoomed about the centre of the taller canvas and no more, the card would be cut off.
    const k = 0.9 / vp.zoom;
    const card = boxOf(ctx, edge.source);
    const top = card.y * 0.9 + h / 2 - (h / 2 - vp.y) * k;
    const left = card.x * 0.9 + w / 2 - (w / 2 - vp.x) * k;
    assert.ok(top < 0 || left < 0 || top + card.h * 0.9 > h || left + card.w * 0.9 > w, `precondition: about the centre alone the card would land at ${left.toFixed(0)},${top.toFixed(0)}, off the ${w}x${h} canvas`);
    assert.equal(offScreen(ctx, edge.source), null, 'the selected card is in view');
  } finally {
    ctx.app.destroy();
  }
  // Nothing selected (a click on the diagram's background): zoomed about the canvas centre.
  ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.collapseSheet(false);
    centreEnds(ctx, edge, 0.9);
    click(ctx, ctx.document.querySelector('.mlv-edge[data-edge-id="c14"] .mlv-edge__hit'));
    assert.ok(zoomOf(ctx) < 0.9, 'precondition: the click zoomed out');
    click(ctx, ctx.canvas);
    assert.equal(ctx.app.selection, null, 'precondition: nothing is selected');
    const vp = ctx.app.getState().viewport;
    const middle = (541 / 2 - vp.x) / vp.zoom;
    press(ctx, 'b');
    assert.equal(ctx.box().h, 708, 'b collapsed the sheet');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    // What was drawn at the canvas's mid-width is drawn there still.
    assert.ok(Math.abs(middle * 0.9 + ctx.app.getState().viewport.x - 541 / 2) < 0.01, 'zoomed about the canvas centre');
  } finally {
    ctx.app.destroy();
  }
});

/** Mount `document` at 541x798 with the sheet collapsed, centre the two cards of `id` at 0.9 and click the connection, which opens the sheet. */
async function clickedAt90(document, id) {
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  ctx.app.collapseSheet(false);
  centreEnds(ctx, document.edges.find((e) => e.id === id), 0.9);
  click(ctx, ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"] .mlv-edge__hit`));
  return ctx;
}

// To anything but the connection it was taken from, the zoom is given back only once the canvas has
// the room again that the shrink took: not by a window 2 px wider while the sheet is still open.
for (const [what, pick, collapse, narrow] of [
  ['its source card', (ctx, edge) => click(ctx, ctx.app.view.nodeElement(edge.source)), 'Escape', true],
  ['an empty selection', (ctx) => click(ctx, ctx.canvas), 'b', true],
  ['another connection', (ctx) => click(ctx, ctx.document.querySelector('.mlv-edge[data-edge-id="c7"] .mlv-edge__hit')), 'Escape', false],
]) {
  test(`a zoom the opening sheet took is not given back to ${what} by a wider window while the sheet is open, only once it is collapsed (the 79-claim shape, c14, 541x798)`, async () => {
    const document = shapedWorkflow(SHAPE_79_CLAIMS);
    const edge = document.edges.find((e) => e.id === 'c14');
    const ctx = await clickedAt90(document, 'c14');
    try {
      const opened = zoomOf(ctx);
      assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
      assert.ok(opened < 0.9, `precondition: the click zoomed out (${opened})`);
      pick(ctx, edge);
      assert.notDeepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c14' }, 'precondition: the connection is no longer selected');
      assert.equal(zoomOf(ctx), opened, 'precondition: the click did not zoom');
      if (ctx.app.selection && ctx.app.selection.kind === 'edge') {
        // Precondition: the other connection is in view and its cards fit this canvas at 0.9, so a frame of it at the zoom on loan would succeed.
        const now = document.edges.find((e) => e.id === ctx.app.selection.id);
        assert.equal(offScreen(ctx, now.source), null);
        assert.equal(offScreen(ctx, now.target), null);
        assert.ok(ctx.app.view.viewport.fitsAt(unionOf(boxOf(ctx, now.source), boxOf(ctx, now.target)), 0.9, 0), 'its cards fit the canvas at 0.9');
      }
      ctx.resize(543);
      assert.deepEqual(ctx.box(), { w: 543, h: 392 }, 'the window is 2 px wider, the sheet still open');
      assert.equal(zoomOf(ctx), opened, 'the zoom stays on loan');
      // The height the sheet took is what must come back; the window may be narrower by then.
      if (narrow) ctx.resize(500);
      assert.equal(zoomOf(ctx), opened, 'the zoom stays on loan');
      press(ctx, collapse);
      assert.equal(ctx.box().h, 708, 'the sheet is collapsed');
      assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    } finally {
      ctx.app.destroy();
    }
  });
}

test('another connection whose cards do not fit the canvas at the zoom on loan gets it back as far as the canvas holds them, and the rest comes with the next growth, here 2 px and nothing selected (the 79-claim shape, seed 1, c4 then c19, 541x798)', async () => {
  const document = shapedWorkflow({ ...SHAPE_79_CLAIMS, seed: 1 });
  const other = document.edges.find((e) => e.id === 'c19');
  const ctx = await clickedAt90(document, 'c4');
  try {
    const opened = zoomOf(ctx);
    assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
    assert.ok(opened < 0.9, `precondition: the click zoomed out (${opened})`);
    click(ctx, ctx.document.querySelector('.mlv-edge[data-edge-id="c19"] .mlv-edge__hit'));
    assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id: 'c19' });
    assert.equal(zoomOf(ctx), opened, 'precondition: the click did not zoom');
    assert.equal(offScreen(ctx, other.source), null, 'precondition: both its cards are in view');
    assert.equal(offScreen(ctx, other.target), null, 'precondition: both its cards are in view');
    press(ctx, 'Escape');
    assert.deepEqual(ctx.box(), { w: 541, h: 708 }, 'Escape collapsed the sheet: the canvas has the height back that the sheet took');
    const union = unionOf(boxOf(ctx, other.source), boxOf(ctx, other.target));
    assert.ok(!ctx.app.view.viewport.fitsAt(union, 0.9, 0), `precondition: its cards do not fit this canvas at 0.9 (${union.w} px across)`);
    const part = zoomOf(ctx);
    assert.ok(part > opened && part < 0.9, `part of the zoom, not the whole (${part})`);
    assert.equal(offScreen(ctx, other.source), null);
    assert.equal(offScreen(ctx, other.target), null);
    assert.equal(ctx.app.getState().framedZoom, part, 'still the viewer\'s zoom, not one the reader chose');
    // The rest is still on loan, and the canvas has the room back: any growth gives it.
    press(ctx, 'Escape');
    assert.equal(ctx.app.selection, null, 'precondition: Escape cleared the selection');
    assert.equal(zoomOf(ctx), part, 'precondition: clearing the selection did not zoom');
    ctx.resize(543);
    assert.deepEqual(ctx.box(), { w: 543, h: 708 }, 'the window is 2 px wider');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    assert.equal(ctx.app.getState().framedZoom, undefined, 'it is the reader\'s zoom again');
  } finally {
    ctx.app.destroy();
  }
});

test('a zoom a narrower window took is not given back to a card by a window 2 px wider, only once it is as wide again, whatever its height by then (the 79-claim shape, c7, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const edge = document.edges.find((e) => e.id === 'c7');
  const ctx = await clickedAt90(document, 'c7');
  try {
    assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
    assert.equal(zoomOf(ctx), 0.9, 'precondition: both cards fit above the sheet at 0.9');
    ctx.resize(400);
    const narrowed = zoomOf(ctx);
    assert.ok(narrowed < 0.9, `precondition: the narrower window zoomed out (${narrowed})`);
    click(ctx, ctx.app.view.nodeElement(edge.source));
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: edge.source });
    ctx.resize(402);
    assert.equal(zoomOf(ctx), narrowed, 'the zoom stays on loan');
    ctx.resize(541, 700);
    assert.deepEqual(ctx.box(), { w: 541, h: 371 }, 'as wide as it was, and shorter');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had');
    assert.equal(offScreen(ctx, edge.source), null, 'the selected card is in view');
  } finally {
    ctx.app.destroy();
  }
});

test('a second shrink keeps the first loan: the zoom comes back as far as each growth holds both cards, the viewer\'s until it is whole (the 79-claim shape, c11, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const edge = document.edges.find((e) => e.id === 'c11');
  const ctx = await clickedAt90(document, 'c11');
  try {
    const opened = zoomOf(ctx);
    assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
    assert.ok(opened < 0.9, `precondition: the click zoomed out (${opened})`);
    ctx.resize(380);
    const narrowed = zoomOf(ctx);
    assert.ok(narrowed < opened, `precondition: the narrower window zoomed out again (${narrowed})`);
    ctx.resize(541);
    assert.equal(zoomOf(ctx), opened, 'the window as wide as it was: as far as the canvas above the sheet holds both cards');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.equal(ctx.app.getState().framedZoom, opened, 'still the viewer\'s zoom, not one the reader chose');
    press(ctx, 'Escape');
    assert.equal(ctx.box().h, 708, 'Escape collapsed the sheet');
    assert.equal(zoomOf(ctx), 0.9, 'the zoom the reader had before the first shrink');
    assert.equal(ctx.app.getState().framedZoom, undefined, 'it is the reader\'s zoom again');
  } finally {
    ctx.app.destroy();
  }
});

test('a zoom still partly on loan is not given back by a canvas that shrinks (the 79-claim shape, c11, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await clickedAt90(document, 'c11');
  try {
    assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
    ctx.resize(380);
    const narrowed = zoomOf(ctx);
    assert.ok(narrowed < 0.9, `precondition: zoomed out (${narrowed})`);
    // The sheet collapses: the height it took returns, but the narrow canvas holds both cards no larger.
    press(ctx, 'Escape');
    assert.deepEqual(ctx.box(), { w: 380, h: 708 });
    assert.equal(zoomOf(ctx), narrowed, 'precondition: nothing could be given back yet');
    press(ctx, 'Escape');
    assert.equal(ctx.app.selection, null, 'precondition: Escape cleared the selection');
    ctx.resize(360);
    assert.equal(zoomOf(ctx), narrowed, 'a narrower window gives nothing back');
    ctx.resize(541);
    assert.equal(zoomOf(ctx), 0.9, 'a wider one does');
  } finally {
    ctx.app.destroy();
  }
});

test('a wider window that holds the two cards no larger leaves the picture where it was (the 79-claim shape, c14, 541x798)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await clickedAt90(document, 'c14');
  try {
    const before = plain(ctx.app.getState().viewport);
    assert.equal(ctx.box().h, 392, 'precondition: the click opened the sheet');
    assert.ok(before.zoom < 0.9, `precondition: the click zoomed out (${before.zoom})`);
    ctx.resize(600);
    assert.deepEqual(ctx.box(), { w: 600, h: 392 }, 'wider, the sheet still open');
    assert.deepEqual(plain(ctx.app.getState().viewport), before, 'neither zoomed nor centred again');
  } finally {
    ctx.app.destroy();
  }
});

test('with the phase index hidden, both cards of a revealed connection stay on the canvas when the opening sheet shrinks it a frame later (the 79-claim shape, c4)', async () => {
  const document = shapedWorkflow(SHAPE_79_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    ctx.app.view.setPhaseIndex({ folded: false, hidden: true });
    assert.equal(ctx.app.view.viewport.covered(), null, 'precondition: no index');
    ctx.app.collapseSheet(false);
    ctx.hold();
    reveal(ctx, 'edge', 'c4');
    const edge = document.edges.find((e) => e.id === 'c4');
    const framed = ctx.app.getState().viewport.zoom;
    ctx.release();
    assert.equal(ctx.box().h, 392);
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    assert.ok(ctx.app.getState().viewport.zoom < framed);
  } finally {
    ctx.app.destroy();
  }
});

test('a revealed connection whose cards are clear of the index, the empty corner of their union under it, stays in view when the window narrows (the 176-claim shape, c72, 1440 px)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 1440, bodyH: 842 });
  try {
    reveal(ctx, 'edge', 'c72');
    const edge = document.edges.find((e) => e.id === 'c72');
    assert.equal(offScreen(ctx, edge.source), null);
    assert.equal(offScreen(ctx, edge.target), null);
    const union = ctx.app.view.targetRect({ kind: 'edge', id: 'c72' });
    const vp = ctx.app.getState().viewport;
    const screen = { x: union.x * vp.zoom + vp.x, y: union.y * vp.zoom + vp.y, w: union.w * vp.zoom, h: union.h * vp.zoom };
    assert.ok(overlaps(screen, ctx.app.view.viewport.covered()), 'precondition: the union is partly under the index');
    // The resize judges the connection by its two cards, not by their union: it is in view, and
    // stays so on the narrower canvas.
    ctx.resize(1400);
    assert.equal(offScreen(ctx, edge.source), null, 'after the resize');
    assert.equal(offScreen(ctx, edge.target), null, 'after the resize');
  } finally {
    ctx.app.destroy();
  }
});

test('a card the reader left under the phase index stays where it is when the window resizes (1440 px, the panel of rows)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 1440, bodyH: 842 });
  try {
    assert.notEqual(ctx.rail.getAttribute('data-mode'), 'sheet', 'precondition: the rail is docked');
    const id = 'n30';
    ctx.app.select({ kind: 'node', id }, { tab: 'inspector' });
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
    const vpc = ctx.app.view.viewport;
    const covered = vpc.covered();
    const box = boxOf(ctx, id);
    const zoom = vpc.vp.zoom;
    vpc.set({ x: covered.x + covered.w / 2 - (box.x + box.w / 2) * zoom, y: covered.y + covered.h / 2 - (box.y + box.h / 2) * zoom });
    assert.match(offScreen(ctx, id) || '', /under the phase index/, 'precondition: the reader left the card under the index');
    const before = plain(ctx.app.getState().viewport);
    ctx.resize(1420);
    assert.deepEqual(plain(ctx.app.getState().viewport), before, 'nothing moved');
  } finally {
    ctx.app.destroy();
  }
});

// The index changes what it covers with no change of viewport. A resize judges "was in view" by
// what it covers at that time, not by the shape it had when the viewport last moved.
for (const [how, change] of [
  ['hidden from the ⋯ menu', (ctx) => click(ctx, ctx.document.querySelector('[data-more-item="phaseindex"]'))],
  ['folded to its pill', (ctx) => click(ctx, ctx.document.querySelector('.mlv-phaseindex__fold'))],
]) {
  test(`a selected card under the phase index, which is then ${how}, is in view and stays in view when the window narrows (1440 px)`, async () => {
    const document = shapedWorkflow(SHAPE_176_CLAIMS);
    const ctx = await mount(document, { width: 1440, bodyH: 842 });
    try {
      const id = 'n30';
      ctx.app.select({ kind: 'node', id }, { tab: 'inspector' });
      ctx.window.dispatchEvent(new ctx.window.Event('resize'));
      panCardOnto(ctx, id, ctx.app.view.viewport.covered());
      assert.match(offScreen(ctx, id) || '', /under the phase index/, 'precondition: the card is under the index');
      const moved = plain(ctx.app.getState().viewport);
      change(ctx);
      assert.deepEqual(plain(ctx.app.getState().viewport), moved, 'precondition: the viewport did not change');
      assert.equal(offScreen(ctx, id), null, 'precondition: the reader can now see the card whole');
      const card = onScreen(ctx, boxOf(ctx, id));
      assert.ok(card.x + card.w > 1270 - RAIL_W, 'precondition: the narrower canvas cuts the card off');
      ctx.resize(1270);
      assert.equal(ctx.box().w, 1270 - RAIL_W);
      assert.equal(offScreen(ctx, id), null, 'panned back into view');
    } finally {
      ctx.app.destroy();
    }
  });
}

test('a selected card under the pill\'s open list is in view once the list is closed, and stays in view when the sheet opens (541 px)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    const id = 'n30';
    ctx.app.collapseSheet(false);
    ctx.app.select({ kind: 'node', id }, { tab: 'inspector' });
    assert.equal(ctx.box().h, 708, 'precondition: the sheet is collapsed');
    const pill = plain(ctx.app.view.viewport.covered());
    click(ctx, ctx.document.querySelector('.mlv-phaseindex__pill'));
    const open = plain(ctx.app.view.viewport.covered());
    assert.ok(open.h > pill.h, 'precondition: the pill opened its list');
    // Under the list, above the pill: in view again as soon as the list closes.
    const list = { x: open.x, y: open.y, w: open.w, h: pill.y - open.y - 8 };
    const card = onScreen(ctx, boxOf(ctx, id));
    assert.ok(card.h < list.h - 16, 'precondition: the card fits the list\'s height');
    panCardOnto(ctx, id, list);
    assert.match(offScreen(ctx, id) || '', /under the phase index/, 'precondition: the card is under the open list');
    const moved = plain(ctx.app.getState().viewport);
    press(ctx, 'Escape');
    assert.deepEqual(plain(ctx.app.view.viewport.covered()), pill, 'Escape closed the list');
    assert.deepEqual(plain(ctx.app.getState().viewport), moved, 'precondition: the viewport did not change');
    assert.equal(offScreen(ctx, id), null, 'precondition: the reader can now see the card whole');
    assert.ok(onScreen(ctx, boxOf(ctx, id)).y + card.h > 392, 'precondition: the open sheet will cover the card');
    press(ctx, 'b');
    assert.equal(ctx.box().h, 392, 'b opened the sheet');
    assert.equal(offScreen(ctx, id), null, 'panned back into view above the sheet');
  } finally {
    ctx.app.destroy();
  }
});

test('focusing a card, a group\'s header or a connection never scrolls the canvas (preventScroll)', async () => {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    const calls = [];
    for (const proto of [ctx.window.HTMLElement.prototype, ctx.window.SVGElement.prototype]) {
      const original = proto.focus;
      proto.focus = function focus(options) {
        if (this !== ctx.canvas && ctx.canvas.contains(this)) calls.push({ element: this, options });
        return original.call(this, options);
      };
    }
    const group = document.nodes.find((n) => n.kind === 'group').id;
    reveal(ctx, 'node', 'n30');
    reveal(ctx, 'node', group);
    reveal(ctx, 'edge', 'c82');
    reveal(ctx, 'node', 'n30');
    press(ctx, 'ArrowRight');
    press(ctx, 'e');
    // The shortcut sheet gives the focus back to the connection that had it when it opened.
    const connection = ctx.document.activeElement;
    assert.ok(connection.classList.contains('mlv-edge__hit'), 'precondition: e put the focus on a connection');
    press(ctx, '?');
    assert.equal(ctx.app.sheet.open, true, 'the shortcut sheet opened');
    press(ctx, 'Escape');
    assert.equal(ctx.document.activeElement, connection, 'closing it gave the focus back');
    ctx.app.view.refresh(ctx.app.selection);
    // The first arrow key (here →) after a move to a phase selects and focuses its first step.
    const phase = ctx.app.view.frameData.lanes[2].id;
    const firstStep = ctx.app.index.roots(phase)[0];
    ctx.app.view.goToPhase(phase, { focusCanvas: true });
    press(ctx, 'ArrowRight');
    assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: firstStep }, 'the arrow key started at the phase\'s first step');
    assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement(firstStep), 'and its card has the focus');
    const kinds = new Set(calls.map((c) => (c.element.classList.contains('mlv-edge__hit') ? 'connection' : c.element.classList.contains('mlv-group__header') ? 'group' : c.element.hasAttribute('data-node-id') ? 'card' : 'other')));
    for (const kind of ['card', 'group', 'connection']) assert.ok(kinds.has(kind), `a ${kind} took the focus`);
    const scrolling = calls.filter((c) => !(c.options && c.options.preventScroll === true));
    assert.deepEqual(scrolling.map((c) => c.element.className.baseVal ?? c.element.className), []);
  } finally {
    ctx.app.destroy();
  }
});
