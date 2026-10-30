// A group larger than the canvas, and the keyboard's place in it. An expanded group (a training
// loop) is often wider or taller than the canvas at reading size, and focusing never scrolls the
// canvas, so only the viewport can keep what has the keyboard on screen:
//
// - Reveal in Diagram aligns such a group on its top-left corner, where its header is, instead
//   of centring it with the header off the canvas. A card that fits the canvas is centred.
// - `e` / Shift+E from it pan the least distance that shows where each connection meets it. From a
//   card wholly in view nothing moves, also one a walk step left 16 px from the canvas edge.
// - Folding it from the keyboard leaves the keyboard on its card (unfolding, on its header), and a
//   folded card whose corner was panned off the canvas is brought into view.
//
// The fixture is SYNTHETIC: the 176-claim shape of helpers.mjs, whose first group holds 12
// steps. jsdom lays nothing out: the panel and canvas boxes are stubbed as in reveal.test.mjs, and
// positions are the layout's boxes under the applied viewport, not DOM rectangles. The viewer is
// the built bundle, mounted in jsdom.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, shapedWorkflow, WEBVIEW_ROOT, SHAPE_176_CLAIMS } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));

const RAIL_W = 360;
const SHEET_SHARE = 0.47;
const PANELS = [
  ['1440x900', { width: 1440, bodyH: 842 }],
  ['900x800', { width: 900, bodyH: 742 }],
  ['541x798', { width: 541, bodyH: 740 }],
];

/** Mount `document` in a panel `width` px wide whose body (between header and status bar) is `bodyH` px. */
async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  ctx.document.body.classList.add('vscode-reduce-motion');
  const root = ctx.document.getElementById('mlview-root');
  const width = opts.width || 1440;
  const bodyH = opts.bodyH || 842;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: bodyH + 58, right: width, bottom: bodyH + 58 });
  const bridge = recordingBridge(ctx.window, 'vscode');
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
  ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  app.view.fit();
  canvas.focus();
  return { ...ctx, root, bridge, app, canvas, rail, box };
}

const reveal = (ctx, kind, id) => ctx.bridge.send({ v: 1, type: 'reveal', kind, id });
const press = (ctx, key, target = ctx.document.activeElement || ctx.canvas) => {
  const event = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
};
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const boxOf = (ctx, id) => ctx.app.view.frameData.boxes.get(ctx.app.index.visibleRepresentative(id, ctx.app.view.collapsed));
/** A world box on screen, at the current viewport. */
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
const headerOf = (ctx, id) => ctx.app.view.nodeElement(id).querySelector('.mlv-group__header');

/** The 176-claim shape and its first group, which holds 12 steps. */
function bigGroup() {
  const document = shapedWorkflow(SHAPE_176_CLAIMS);
  const group = document.nodes.find((n) => n.kind === 'group').id;
  assert.equal(document.nodes.filter((n) => n.parent === group).length, 12);
  return { document, group };
}

/* ── Reveal in Diagram ───────────────────────────────────────────────── */

for (const [name, panel] of PANELS) {
  test(`${name}: Reveal in Diagram of a group larger than the canvas aligns it on its top-left corner, so its header, which takes the keyboard, is on the canvas`, async () => {
    const { document, group } = bigGroup();
    const ctx = await mount(document, panel);
    try {
      reveal(ctx, 'node', group);
      assert.deepEqual(plain(ctx.app.selection), { kind: 'node', id: group });
      assert.equal(ctx.document.activeElement, headerOf(ctx, group), 'the keyboard is on the group\'s header');
      const { w, h } = ctx.box();
      const s = onScreen(ctx, boxOf(ctx, group));
      assert.ok(s.w > w || s.h > h, `precondition: the group (${s.w.toFixed(0)}x${s.h.toFixed(0)}) is larger than the canvas (${w}x${h})`);
      // The header runs along the group's top edge from its left corner.
      assert.ok(s.x >= -0.5 && s.x < w / 2, `the group's left edge is on the canvas (x ${s.x.toFixed(0)})`);
      assert.ok(s.y >= -0.5 && s.y < h / 2, `the group's top edge is on the canvas (y ${s.y.toFixed(0)})`);
    } finally {
      ctx.app.destroy();
    }
  });
}

/* ── e / Shift+E ─────────────────────────────────────────────────────── */

/** Where the connection `id` meets the step `anchor`, in canvas pixels. */
function endAt(ctx, id, anchor) {
  const route = ctx.app.view.routes.find((r) => r.id === id);
  const p = route.source === anchor ? route.points[0] : route.points[route.points.length - 1];
  const vp = ctx.app.getState().viewport;
  return { x: p.x * vp.zoom + vp.x, y: p.y * vp.zoom + vp.y };
}

test('e from a group larger than the canvas pans to where each connection meets the group, not at all when that place is on the canvas already, and the keyboard is on that connection (541x798)', async () => {
  const { document, group } = bigGroup();
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    reveal(ctx, 'node', group);
    const { w, h } = ctx.box();
    const routes = ctx.app.view.incidentRoutes(group).map((r) => r.id);
    assert.ok(routes.length >= 3, 'precondition: the group has several connections');
    // Precondition: with the group aligned on its corner, a connection meets it beyond the canvas.
    assert.ok(routes.some((id) => { const p = endAt(ctx, id, group); return p.x > w || p.y > h; }), 'a connection meets the group off the canvas');
    let still = 0;
    for (const id of routes) {
      // The place where the connection meets the group, with the 24 px asked for around it, before the press.
      const was = endAt(ctx, id, group);
      const around = { x: was.x - 24, y: was.y - 24, w: 48, h: 48 };
      const index = ctx.app.view.viewport.covered();
      const shown = around.x >= 0 && around.y >= 0 && around.x + around.w <= w && around.y + around.h <= h && !(index && overlaps(around, index));
      const before = plain(ctx.app.getState().viewport);
      press(ctx, 'e');
      assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id });
      assert.equal(ctx.document.activeElement, ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"] .mlv-edge__hit`), 'the keyboard is on the connection');
      const p = endAt(ctx, id, group);
      assert.ok(p.x >= 16 && p.y >= 16 && p.x <= w - 16 && p.y <= h - 16, `${id} meets the group on the canvas (${p.x.toFixed(0)},${p.y.toFixed(0)} of ${w}x${h})`);
      const covered = ctx.app.view.viewport.covered();
      assert.ok(!covered || !overlaps({ x: p.x - 1, y: p.y - 1, w: 2, h: 2 }, covered), `${id} meets the group clear of the phase index`);
      if (shown) {
        still++;
        assert.deepEqual(plain(ctx.app.getState().viewport), before, `${id} met the group on the canvas already: the viewport did not move`);
      }
    }
    assert.ok(still > 0, 'precondition: a connection meets the group where an earlier pan left that place on the canvas');
  } finally {
    ctx.app.destroy();
  }
});

test('Reveal in Diagram still centres a card that fits the canvas, and e from it moves nothing (541x798)', async () => {
  const { document } = bigGroup();
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    reveal(ctx, 'node', 'n30');
    assert.equal(offScreen(ctx, 'n30'), null);
    const { w, h } = ctx.box();
    const card = onScreen(ctx, boxOf(ctx, 'n30'));
    assert.ok(Math.abs(card.x + card.w / 2 - w / 2) < 0.01 && Math.abs(card.y + card.h / 2 - h / 2) < 0.01, `the card is centred, not aligned on its corner (${card.x.toFixed(1)},${card.y.toFixed(1)} on ${w}x${h})`);
    const routes = ctx.app.view.incidentRoutes('n30');
    assert.ok(routes.length >= 2, 'precondition: the step has connections');
    const before = plain(ctx.app.getState().viewport);
    for (let i = 0; i < routes.length; i++) press(ctx, 'e');
    assert.equal(ctx.app.selection.kind, 'edge');
    assert.deepEqual(plain(ctx.app.getState().viewport), before, 'the viewport did not move');
  } finally {
    ctx.app.destroy();
  }
});

test('e from a card a walk step left 16 px from the canvas edge moves nothing: a connection that meets the card less than 24 px from that edge starts on screen all the same (541x798)', async () => {
  const { document } = bigGroup();
  const ctx = await mount(document, { width: 541, bodyH: 740 });
  try {
    assert.equal(ctx.app.walk.start('all'), true);
    for (let i = 0; i < 400 && ctx.app.walk.current().id !== 'n8'; i++) ctx.app.walk.step(1);
    assert.deepEqual([ctx.app.walk.current().kind, ctx.app.walk.current().id], ['node', 'n8']);
    assert.equal(offScreen(ctx, 'n8'), null, 'precondition: the card is wholly in view');
    const { w, h } = ctx.box();
    const card = onScreen(ctx, boxOf(ctx, 'n8'));
    assert.ok(Math.abs(card.x + card.w - (w - 16)) < 0.01, `precondition: the step's least pan left the card 16 px from the canvas's right edge (${(w - card.x - card.w).toFixed(1)})`);
    const routes = ctx.app.view.incidentRoutes('n8').map((r) => r.id);
    const near = routes.filter((id) => { const p = endAt(ctx, id, 'n8'); return p.x < 24 || p.y < 24 || p.x > w - 24 || p.y > h - 24; });
    assert.ok(near.length > 0, 'precondition: a connection meets the card less than 24 px from the canvas edge');
    const before = plain(ctx.app.getState().viewport);
    for (const id of routes) {
      press(ctx, 'e');
      assert.deepEqual(plain(ctx.app.selection), { kind: 'edge', id });
      assert.deepEqual(plain(ctx.app.getState().viewport), before, `e onto ${id}: the viewport did not move`);
    }
  } finally {
    ctx.app.destroy();
  }
});

/* ── folding ─────────────────────────────────────────────────────────── */

test('Space on a group\'s focused header folds it and leaves the keyboard on its card; Space again unfolds it, the keyboard on its header where the card was', async () => {
  const { document, group } = bigGroup();
  const ctx = await mount(document, { width: 1440, bodyH: 842 });
  try {
    reveal(ctx, 'node', group);
    assert.equal(ctx.document.activeElement, headerOf(ctx, group), 'precondition: the keyboard is on the header');
    press(ctx, ' ');
    assert.equal(ctx.app.view.collapsed.has(group), true, 'folded');
    const card = ctx.app.view.nodeElement(group);
    assert.equal(card.classList.contains('mlv-group'), false, 'the group is drawn as a card');
    assert.equal(ctx.document.activeElement, card, 'the keyboard is on the folded card');
    assert.equal(offScreen(ctx, group), null);
    // The reader pans the folded card to the middle of the canvas, where the unfolded group runs off it.
    const { w, h } = ctx.box();
    const box = boxOf(ctx, group);
    const zoom = ctx.app.getState().viewport.zoom;
    ctx.app.view.viewport.set({ x: w / 2 - (box.x + box.w / 2) * zoom, y: h / 2 - (box.y + box.h / 2) * zoom });
    const folded = onScreen(ctx, boxOf(ctx, group));
    press(ctx, ' ');
    assert.equal(ctx.app.view.collapsed.has(group), false, 'unfolded');
    assert.equal(ctx.document.activeElement, headerOf(ctx, group), 'the keyboard is on the header');
    // An unfolded group stays anchored on the corner its card had; it is not aligned again.
    const open = onScreen(ctx, boxOf(ctx, group));
    assert.ok(open.x + open.w > w, `precondition: the unfolded group runs off the canvas (${open.x.toFixed(0)} + ${open.w.toFixed(0)} of ${w})`);
    assert.ok(Math.abs(open.x - folded.x) < 0.01 && Math.abs(open.y - folded.y) < 0.01, 'anchored on the same corner');
  } finally {
    ctx.app.destroy();
  }
});

test('folding a group whose corner is panned off the canvas brings its card into view, the keyboard on it: from its header, and from a step inside it (541x798)', async () => {
  for (const from of ['header', 'step']) {
    const { document, group } = bigGroup();
    const ctx = await mount(document, { width: 541, bodyH: 740 });
    try {
      reveal(ctx, 'node', group);
      // The reader pans right along the group: its left edge, with its header's start, leaves the canvas.
      const box = boxOf(ctx, group);
      const zoom = ctx.app.getState().viewport.zoom;
      ctx.app.view.viewport.set({ x: -420 - box.x * zoom, y: 40 - box.y * zoom });
      const { w, h } = ctx.box();
      if (from === 'step') {
        // A step of the group that is wholly on the canvas there takes the selection and the keyboard.
        const inside = document.nodes.filter((n) => n.parent === group).map((n) => n.id).find((id) => offScreen(ctx, id) === null);
        assert.ok(inside, 'precondition: a step of the group is in view');
        ctx.app.select({ kind: 'node', id: inside });
        ctx.app.view.nodeElement(inside).focus();
        assert.equal(offScreen(ctx, inside), null, 'precondition: selecting it moved nothing');
      } else {
        assert.equal(ctx.document.activeElement, headerOf(ctx, group), 'precondition: the keyboard is on the header');
      }
      const corner = onScreen(ctx, boxOf(ctx, group));
      assert.ok(corner.x < -200 && corner.x + corner.w > w, `precondition: the group runs off both sides of the ${w}x${h} canvas (x ${corner.x.toFixed(0)})`);
      press(ctx, ' ');
      assert.equal(ctx.app.view.collapsed.has(group), true, `folded from its ${from}`);
      assert.equal(offScreen(ctx, group), null, `from its ${from}: the folded card is in view`);
      assert.equal(ctx.document.activeElement, ctx.app.view.nodeElement(group), `from its ${from}: the keyboard is on the folded card`);
    } finally {
      ctx.app.destroy();
    }
  }
});
