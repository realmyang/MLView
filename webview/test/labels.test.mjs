/**
 * VIEW-03 — lane-seam-aware edge label placement.
 *
 * `render/edges.ts` used to place every label at the route midpoint. Since ~70 %
 * of edges cross a lane, that midpoint IS the lane seam, and the flagship demo
 * measured **5 label-label overlaps, 6 labels drawn over node cards** and three
 * labels stacked in the 20 px gutter between two bands.
 *
 * Every assertion below re-derives the overlap itself, from the rectangles the
 * planner reports and the boxes `__internal.layout` reports, so the gate is
 * arithmetic this file owns rather than a self-report from the code under test.
 *
 * Which labels are counted: the ones drawn WITHOUT hovering — data and control
 * labels at LOD `full`, plus back-edges and merged routes at every zoom, exactly
 * as `styles/edge.css` decides. A call or config label appears one at a time
 * under the pointer, where it cannot collide with a sibling that is not drawn.
 *
 * Placement is computed in WORLD coordinates and the viewport is a pure
 * transform, so an overlap count is zoom-invariant: proving 0 overlaps here
 * proves 0 at every zoom the labels are drawn at, which is `data-lod: full`,
 * i.e. zoom >= 0.62 (`render/canvas.ts:111`, asserted below through the
 * stylesheet rule that hides every label below it).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, makeSyntheticGraph, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

function rectsOverlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

/** Only the labels the reader sees without a pointer on the cable. */
function visibleLabels(plan) {
  return plan.labels.filter((l) => l.always && !l.hidden);
}

function labelLabelOverlaps(labels) {
  const out = [];
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      if (rectsOverlap(labels[i].rect, labels[j].rect)) out.push(labels[i].text + ' × ' + labels[j].text);
    }
  }
  return out;
}

/** A card is a leaf box or a collapsed group — an expanded group is background. */
function cardsOf(layout) {
  return layout.nodes.filter((n) => !n.isGroup || n.collapsed);
}

function labelsOverCards(labels, layout) {
  const cards = cardsOf(layout);
  const out = [];
  for (const label of labels) {
    for (const card of cards) {
      if (rectsOverlap(label.rect, { x: card.x, y: card.y, w: card.w, h: card.h })) {
        out.push(label.text + ' over ' + card.id);
        break;
      }
    }
  }
  return out;
}

/** Inside no lane's band, inset by LANE_PAD from both of its boundaries. */
function labelsOnSeams(labels, layout, lanePad) {
  const out = [];
  for (const label of labels) {
    const inside = layout.lanes.some(
      (lane) => label.rect.y >= lane.y + lanePad && label.rect.y + label.rect.h <= lane.y + lane.h - lanePad,
    );
    if (!inside) out.push(label.text + ' at y=' + label.rect.y);
  }
  return out;
}

/* ── the demo graph: 0 / 0 / 0 ─────────────────────────────────────────── */

test('the demo graph reports 0 label-label overlaps, 0 over cards, 0 on a seam (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const { labels: api, layout } = ctx.MLView.__internal;
  const plan = api.plan(sample);
  const frame = layout(sample);
  const shown = visibleLabels(plan);

  assert.ok(
    shown.length >= 8,
    'the demo draws its always-on edge labels: ' + shown.length + ' of ' + plan.stats.labels + ' labelled routes',
  );
  assert.deepEqual(labelLabelOverlaps(shown), [], 'label-label overlaps');
  assert.deepEqual(labelsOverCards(shown, frame), [], 'labels over cards');
  assert.deepEqual(labelsOnSeams(shown, frame, api.metrics.LANE_PAD), [], 'labels within LANE_PAD of a lane boundary');
  assert.equal(plan.stats.hidden, 0, 'nothing had to be hidden on the demo');
});

test('every label is anchored inside one lane band, and names it (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const plan = ctx.MLView.__internal.labels.plan(sample);
  for (const label of plan.labels) {
    if (label.hidden) continue;
    assert.ok(label.laneId, label.text + ' names the band it was placed in');
  }
  // The whole point: a cross-lane route anchors to a VERTICAL leg inside a
  // band, not to the horizontal gutter leg its midpoint sits on.
  const vertical = plan.labels.filter((l) => !l.hidden && l.axis === 'v');
  assert.ok(vertical.length > 0, 'cross-lane labels anchor to a vertical run: ' + vertical.length);
});

test('the severity marker is nudged off the label box (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const api = ctx.MLView.__internal.labels;
  const plan = api.plan(sample);
  const r = api.metrics.MARKER_R;
  for (const label of plan.labels) {
    if (label.hidden) continue;
    const disc = { x: label.marker.x - r, y: label.marker.y - r, w: r * 2, h: r * 2 };
    assert.equal(rectsOverlap(disc, label.rect), false, 'marker clear of ' + label.text);
  }
});

test('the placement pass is deterministic over the same bytes (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const api = ctx.MLView.__internal.labels;
  const a = api.plan(sample).labels.map((l) => [l.id, l.x, l.y, l.hidden, l.flipped].join(':'));
  const b = api.plan(JSON.parse(JSON.stringify(sample))).labels.map((l) => [l.id, l.x, l.y, l.hidden, l.flipped].join(':'));
  assert.deepEqual(b, a, 'two runs over the same document place every label identically');
});

/* ── the rendered scene agrees with the plan ───────────────────────────── */

test('the scene draws exactly the labels the plan kept (VIEW-03)', async () => {
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
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);
  const plan = ctx.MLView.__internal.labels.plan(sample);
  const drawn = Array.from(ctx.document.querySelectorAll('.mlv-edge-label'));
  const kept = plan.labels.filter((l) => !l.hidden);
  assert.equal(drawn.length, kept.length, 'one <text> per kept label');
  const byText = new Map(kept.map((l) => [l.text, l]));
  for (const node of drawn) {
    const placement = byText.get(node.textContent);
    assert.ok(placement, 'drew a label the plan knows: ' + node.textContent);
    assert.equal(Number(node.getAttribute('x')), placement.x, 'x of ' + node.textContent);
    assert.equal(Number(node.getAttribute('y')), placement.y, 'y of ' + node.textContent);
    assert.ok(node.getAttribute('data-label-lane'), 'every drawn label names its band');
  }
  app.destroy();
});

test('a label the pass could not place is not drawn, and the edge says so (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const api = ctx.MLView.__internal.labels;
  // A crowded document is what actually exhausts the cap: 400 routes over 150
  // nodes leaves runs with nowhere legal left. Hiding is the documented
  // outcome — a label is never drawn over a card or over another label.
  const graph = makeSyntheticGraph(150, 400);
  const plan = api.plan(graph);
  assert.ok(plan.stats.hidden > 0, 'the cap is reachable: ' + JSON.stringify(plan.stats));

  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  // The mounted app collapses its big groups by default, so the scene is planned
  // against THAT collapse set, not the empty one.
  const mounted = api.plan(graph, app.getState().collapsed);
  const hiddenGroups = ctx.document.querySelectorAll('[data-label-hidden]');
  assert.ok(mounted.stats.hidden > 0, 'the mounted scene hides some too: ' + JSON.stringify(mounted.stats));
  assert.equal(hiddenGroups.length, mounted.stats.hidden, 'every hidden label marks its edge group');
  for (const label of mounted.labels) {
    if (!label.hidden) continue;
    const group = ctx.document.querySelector('[data-edge-id="' + label.id + '"]');
    assert.ok(group && group.getAttribute('data-label-hidden') === '1', 'the edge says its label was dropped');
    assert.equal(group.querySelector('.mlv-edge-label'), null, 'and draws no text for it');
  }
  app.destroy();
});

/* ── the 300-node synthetic ────────────────────────────────────────────── */

test('a 300-node graph reports 0 label-label overlaps at zoom >= 0.62 (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const { labels: api, layout } = ctx.MLView.__internal;
  const graph = makeSyntheticGraph(300, 600);
  const plan = api.plan(graph);
  const frame = layout(graph);
  const shown = visibleLabels(plan);

  assert.ok(shown.length >= 100, 'the synthetic draws a real crowd of labels: ' + shown.length);
  assert.deepEqual(labelLabelOverlaps(shown).slice(0, 5), [], 'label-label overlaps');
  assert.deepEqual(labelsOverCards(shown, frame).slice(0, 5), [], 'labels over cards');
  assert.deepEqual(labelsOnSeams(shown, frame, api.metrics.LANE_PAD).slice(0, 5), [], 'labels on a lane seam');

  process.stdout.write(
    '  VIEW-03 300 nodes: ' +
      JSON.stringify(plan.stats) +
      ' · ms ' +
      JSON.stringify({
        layout: Math.round(plan.ms.layout),
        route: Math.round(plan.ms.route),
        labels: Math.round(plan.ms.labels),
      }) +
      '\n',
  );
});

test('the placement pass costs a fraction of the relayout it rides on (VIEW-03)', async () => {
  const ctx = await loadBundle();
  const api = ctx.MLView.__internal.labels;
  const graph = makeSyntheticGraph(300, 600);
  // Warm the JIT, then measure: the relayout budget is what VIEW-03 promised not
  // to move materially, so the label pass is bounded against the passes it was
  // added to rather than against a wall-clock number that varies by machine.
  api.plan(graph);
  const plan = api.plan(graph);
  const relayout = plan.ms.layout + plan.ms.route;
  assert.ok(plan.ms.labels < Math.max(relayout, 8), 'labels ' + plan.ms.labels.toFixed(1) + ' ms vs relayout ' + relayout.toFixed(1) + ' ms');
});

/* ── the LOD rule the zoom clause rests on ─────────────────────────────── */

test('no label is drawn below the LOD threshold, so the count is zoom-invariant', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  assert.ok(
    css.indexOf('.mlv-canvas[data-lod="compact"] .mlv-edge-label') >= 0,
    'the stylesheet still hides every edge label below LOD full',
  );
});

/* ── VW-01: the obstacles are the cards that are DRAWN ─────────────────── */

/**
 * Every assertion above derives its obstacles from `layout.nodes`, i.e. from
 * the same 72 px model the planner uses. That made this suite blind to the one
 * thing it exists to prevent: the CARD DID NOT FIT ITS BOX. `render/nodes.ts`
 * set `min-height`, so a card that also drew an attribute chip row measured
 * 96.1 px against a plan of 72, and the 24 px of extra ink was invisible to the
 * layout, to the declutter pass and to the SVG export alike. On the demo
 * exactly one card carries chips, so nothing collided and every gate stayed
 * green; on a NOTEBOOK report every node carries `attrs.cell` /
 * `attrs.cellLine`, so all 26 cards overflowed, two pairs physically overlapped
 * (216 x 12 px) and 6 of 26 visible labels were drawn over a card.
 *
 * So these two tests read the geometry back off the MOUNTED DOM — the same
 * `left/top/width/height` a browser lays the card out with — and use THAT as
 * the obstacle set. `nodes.ts` now pins `height` (not `min-height`) to the
 * reserved box, so the two agree by construction; if they ever stop agreeing,
 * this fails instead of shipping.
 */
const testBridge = {
  host: 'standalone',
  theme: 'light',
  capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
  post: () => undefined,
  onMessage: () => () => undefined,
  saveState: () => undefined,
  loadState: () => null,
};

/** A notebook-shaped document: every node carries the NB cell attributes. */
function everyNodeChipped(graph) {
  const out = JSON.parse(JSON.stringify(graph));
  for (const node of out.nodes) node.attrs = { ...(node.attrs || {}), cell: '3', cellLine: '2' };
  return out;
}

/** The card rectangles as the DOM will paint them, in world coordinates. */
function drawnCards(ctx) {
  return Array.from(ctx.document.querySelectorAll('.mlv-node[data-node-id]')).map((el) => ({
    id: el.getAttribute('data-node-id'),
    chips: !!el.querySelector('.mlv-node__chips'),
    minHeight: el.style.minHeight,
    x: parseFloat(el.style.left),
    y: parseFloat(el.style.top),
    w: parseFloat(el.style.width),
    h: parseFloat(el.style.height),
  }));
}

test('a card that draws a chip row is RESERVED a chip row (VW-01)', async () => {
  const ctx = await loadBundle();
  const graph = everyNodeChipped(sample);
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, testBridge);
  const frame = ctx.MLView.__internal.layout(graph, app.getState().collapsed);
  const planned = new Map(frame.nodes.map((n) => [n.id, n]));
  const drawn = drawnCards(ctx);
  assert.ok(drawn.length >= 8, 'the document draws a real diagram: ' + drawn.length + ' cards');

  const metrics = ctx.MLView.__internal.layoutConstants;
  const bad = [];
  for (const card of drawn) {
    const box = planned.get(card.id);
    assert.ok(box, 'every drawn card is a planned box: ' + card.id);
    if (card.x !== box.x || card.y !== box.y || card.w !== box.w || card.h !== box.h) {
      bad.push(card.id + ' drawn ' + [card.x, card.y, card.w, card.h].join('/') + ' vs plan ' + [box.x, box.y, box.w, box.h].join('/'));
    }
    assert.equal(card.minHeight, '', card.id + ' pins its height rather than a floor it can grow past');
    assert.equal(card.chips, true, 'every node in this document carries attrs, so every card chips');
    // NODE_H is title + sublabel + loc; the chip row is reserved ON TOP of it.
    assert.ok(
      box.h >= metrics.NODE_H + metrics.NODE_CHIP_ROW_H,
      card.id + ' reserved ' + box.h + ' for four rows',
    );
  }
  assert.deepEqual(bad, [], 'the drawn box IS the planned box');
  app.destroy();
});

test('no visible label is drawn over a card that carries chips (VW-01)', async () => {
  const ctx = await loadBundle();
  const graph = everyNodeChipped(sample);
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, testBridge);
  const api = ctx.MLView.__internal.labels;
  const plan = api.plan(graph, app.getState().collapsed);
  const shown = visibleLabels(plan);
  const cards = drawnCards(ctx);
  assert.ok(shown.length >= 8, 'labels are drawn: ' + shown.length);

  const over = [];
  for (const label of shown) {
    for (const card of cards) {
      if (rectsOverlap(label.rect, card)) {
        over.push(label.text + ' over ' + card.id);
        break;
      }
    }
  }
  assert.deepEqual(over, [], 'labels over DRAWN cards');
  assert.deepEqual(labelLabelOverlaps(shown), [], 'label-label overlaps');
  app.destroy();
});

/* ── VW-02: a label is inside the picture ──────────────────────────────── */

/**
 * `bandFor` tests the Y axis only, and a lane band is as wide as the world, so
 * a label pushed onto a vertical run in the left gutter could be placed at
 * negative x with nothing to stop it: five of the flagship demo's 46 placed
 * labels were (X_train_pca at -34.2 through logits at -4.1). The frame is the
 * picture — the exported SVG's viewBox is `0 0 width height` and the print
 * stylesheet lays the page out at exactly that size — so those five were
 * clipped in the SVG, in the 2x PNG and on paper.
 */
function outsideFrame(labels, frame) {
  const out = [];
  for (const label of labels) {
    const r = label.rect;
    if (r.x < 0 || r.y < 0 || r.x + r.w > frame.width || r.y + r.h > frame.height) {
      out.push(label.text + ' at ' + r.x.toFixed(1) + ',' + r.y.toFixed(1) + ' in a ' + frame.width + 'x' + frame.height + ' frame');
    }
  }
  return out;
}

test('every placed label is inside the frame the export draws (VW-02)', async () => {
  const ctx = await loadBundle();
  const { labels: api, layout } = ctx.MLView.__internal;
  for (const [name, graph] of [
    ['the demo sample', sample],
    ['a notebook-shaped document', everyNodeChipped(sample)],
    ['a 150-node synthetic', makeSyntheticGraph(150, 400)],
  ]) {
    const plan = api.plan(graph);
    const frame = layout(graph);
    const placed = plan.labels.filter((l) => !l.hidden);
    assert.ok(placed.length > 0, name + ' places labels');
    assert.deepEqual(outsideFrame(placed, frame).slice(0, 5), [], name + ': labels outside the frame');
  }
});
