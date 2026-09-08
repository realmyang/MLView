/**
 * Feature 1 — flow visibility (FEATURES section 2, CONTRACTS 11.13).
 *
 * The runner executes no CSS animations at all, which is exactly why the design
 * puts every branch behind an OBSERVABLE attribute (`data-motion`, `data-flow`)
 * and an element identity (`.mlv-edge__flow`, `.mlv-edge__port`,
 * `.mlv-edge__dir`) rather than behind a timing.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, makeSyntheticGraph, WEBVIEW_ROOT } from './helpers.mjs';

const sample = await readSample();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Mirrored from canvasview.ts — the delays the flow deliberately hangs off. */
const HOVER_OPEN_MS = 400;
const HOVER_CLOSE_MS = 120;
const DOUBLE_CLICK_MS = 220;

/** The one data edge that already carries a high-severity finding. */
const ISSUE_EDGE = 'e:4c7d0e2f8a91';
const SMALLNET = 'n:8d3e0f7a2b61';
const CRITERION = 'n:b45c96e0d817';
const TRAIN = 'n:5500cc66dd77';
const BUILD_LOADERS = 'n:1100aa22bb33';

async function app(graph = sample, opts = {}) {
  const ctx = await loadBundle();
  if (opts.matchMedia) {
    // A FULL stub, installed BEFORE mount: ui/theme.ts calls addEventListener on
    // the result, so a bare `{ matches }` object throws during mount.
    ctx.window.matchMedia = (q) => ({
      media: q,
      matches: opts.matchMedia(q),
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      onchange: null,
      dispatchEvent() {
        return false;
      },
    });
  }
  const posted = [];
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: () => () => undefined,
    saveState(s) {
      this.saved = s;
    },
    loadState: () => opts.state || null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, graph, bridge);
  return { ...ctx, posted, bridge, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const enter = (ctx, el) => el.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
const leave = (ctx, el) => el.dispatchEvent(new ctx.window.Event('pointerleave', { bubbles: false }));
const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const key = (ctx, el, k, opts = {}) =>
  el.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));

const edgeEl = (ctx, id) => ctx.document.querySelector('[data-edge-id="' + id + '"]');
const hoverTarget = (ctx, id) => {
  const el = ctx.document.querySelector('[data-node-id="' + id + '"]');
  return el.querySelector('.mlv-group__header') || el;
};

/* ── F1-A1 / F1-A2: the pulse and its parts ───────────────────────────── */

test('hovering an edge builds one charge on the visible geometry and two ports (F1-A1)', async () => {
  const ctx = await app();
  const g = edgeEl(ctx, ISSUE_EDGE);
  const hit = g.querySelector('.mlv-edge__hit');
  enter(ctx, hit);
  assert.equal(g.querySelector('.mlv-edge__flow'), null, 'nothing is built on the way past');
  await sleep(HOVER_OPEN_MS + 80);

  assert.ok(g.classList.contains('is-flowing--pulse'));
  const flow = g.querySelector('.mlv-edge__flow');
  assert.ok(flow, 'the charge element exists');
  assert.equal(flow.getAttribute('pathLength'), '100');
  assert.equal(flow.getAttribute('d'), g.querySelector('.mlv-edge__path').getAttribute('d'), 'the charge rides the VISIBLE geometry');

  const ports = g.querySelectorAll('.mlv-edge__port');
  assert.equal(ports.length, 2);
  const out = g.querySelector('.mlv-edge__port--out');
  const inn = g.querySelector('.mlv-edge__port--in');
  const coords = flow
    .getAttribute('d')
    .match(/-?\d+(?:\.\d+)?/g)
    .map(Number);
  assert.equal(Number(out.getAttribute('cx')), coords[0], 'the outlet sits on the first coordinate pair of d');
  assert.equal(Number(out.getAttribute('cy')), coords[1]);
  assert.ok(Number(inn.getAttribute('cx')) >= 0 && Number(inn.getAttribute('cy')) >= 0);
  assert.equal(g.querySelector('.mlv-edge__dir'), null, 'no static chevron while the charge moves');

  leave(ctx, hit);
  await sleep(HOVER_CLOSE_MS + 120);
  assert.equal(g.querySelector('.mlv-edge__flow'), null, 'the charge is removed');
  assert.equal(g.querySelectorAll('.mlv-edge__port').length, 0, 'and so are the ports');
  assert.equal(g.classList.contains('is-flowing--pulse'), false);
  assert.equal((g.getAttribute('style') || '').indexOf('--mlv-flow'), -1, 'every --mlv-flow-* inline property is cleared');
});

test('the endpoint cards ring, and the connection says which way it flows (F1-A2)', async () => {
  const ctx = await app();
  const g = edgeEl(ctx, ISSUE_EDGE);
  const hit = g.querySelector('.mlv-edge__hit');
  const label = hit.getAttribute('aria-label');
  assert.match(label, /flows from .* to .*/);
  assert.ok(label.indexOf('SmallNet') >= 0 && label.indexOf('CrossEntropyLoss') >= 0, label);

  enter(ctx, hit);
  await sleep(HOVER_OPEN_MS + 80);
  assert.ok(ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]').classList.contains('is-flow-source'));
  assert.ok(ctx.document.querySelector('[data-node-id="' + CRITERION + '"]').classList.contains('is-flow-target'));

  ctx.app.setFilters({ showSuppressed: true }); // forces a re-render
  assert.equal(ctx.document.querySelectorAll('.is-flow-source').length, 0, 'a re-render leaves no ring behind');
  assert.equal(ctx.document.querySelectorAll('.is-flow-target').length, 0);
});

/* ── F1-A3: length is the polyline sum, never the DOM ─────────────────── */

test('duration comes from RoutedEdge.points only (F1-A3)', async () => {
  const { flow } = (await loadBundle()).MLView.__internal;
  assert.equal(flow.pulseDurationMs(160), 500);
  assert.equal(flow.pulseDurationMs(40), 380, 'clamped at the floor');
  assert.equal(flow.pulseDurationMs(4000), 2200, 'clamped at the ceiling');
  assert.ok(flow.pulseDurationMs(900) > flow.pulseDurationMs(600), 'longer is strictly slower until the clamp');

  assert.equal(flow.polylineLength([{ x: 0, y: 0 }, { x: 3, y: 4 }]), 5);
  assert.equal(flow.polylineLength([{ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }]), 20);
  assert.equal(flow.polylineLength([{ x: 1, y: 1 }]), 0, 'a degenerate route has no length');

  assert.equal(flow.FLOW.MAX_EDGES, 120);
  assert.equal(flow.FLOW.STREAM_SPEED, 220);
  assert.equal(flow.FLOW.HEAD_PX, 12);
  assert.equal(flow.FLOW.HOP_MS, 90);
  // (head + gap) / 220 px/s, rounded — the CSS tokens encode the same numbers.
  const period = (gap) => ((flow.FLOW.HEAD_PX + gap) / flow.FLOW.STREAM_SPEED) * 1000;
  for (const [gap, declared] of [[flow.FLOW.GAP_DATA, flow.FLOW.PERIOD_DATA], [flow.FLOW.GAP_CALL, flow.FLOW.PERIOD_CALL], [flow.FLOW.GAP_BACK, flow.FLOW.PERIOD_BACK]]) {
    assert.ok(Math.abs(period(gap) - declared) <= 2, 'period for gap ' + gap + ': ' + declared + 'ms vs ' + period(gap).toFixed(1) + 'ms');
  }
  assert.deepEqual([flow.FLOW.PERIOD_DATA, flow.FLOW.PERIOD_CALL, flow.FLOW.PERIOD_BACK], [210, 490, 165], 'the declared periods are the tokens the stylesheet carries');
  assert.equal(flow.streamGapPx('data'), 34);
  assert.equal(flow.streamGapPx('call'), 96);
  assert.equal(flow.streamGapPx('control', 'enter'), 96);
  assert.equal(flow.streamGapPx('control', 'back'), 24);
});

test('no source file calls getTotalLength (F1-A3)', async () => {
  const { readdir } = await import('node:fs/promises');
  const files = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (/\.(ts|css)$/.test(entry.name)) files.push(full);
    }
  };
  await walk(join(WEBVIEW_ROOT, 'src'));
  assert.ok(files.length > 25, 'scanned ' + files.length + ' source files');
  for (const file of files) {
    const text = await readFile(file, 'utf8');
    assert.equal(text.indexOf('getTotal' + 'Length'), -1, file + ' measures the DOM instead of the route');
  }
});

/* ── F1-A4: the lineage stream ────────────────────────────────────────── */

test('a node hover streams its lineage hop by hop (F1-A4)', async () => {
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 100);

  const flowing = Array.from(ctx.document.querySelectorAll('.mlv-edge.is-flowing'));
  assert.ok(flowing.length >= 8, 'the lineage streams: ' + flowing.length + ' edges');
  for (const g of flowing) {
    assert.ok(g.classList.contains('is-lit'), 'a flowing edge is always a lit edge');
    assert.ok(/^\d+ms$/.test(g.style.getPropertyValue('--mlv-flow-delay')), 'every streaming edge carries a hop delay');
  }
  // train.train -> build_loaders is one hop; train_loader -> batch_loop is two.
  assert.equal(edgeEl(ctx, 'e:8a1b4c6d2e35').style.getPropertyValue('--mlv-flow-delay'), '90ms');
  assert.equal(edgeEl(ctx, 'e:9f21ab34cd56').style.getPropertyValue('--mlv-flow-delay'), '180ms');

  const unlit = ctx.document.querySelector('[data-edge-id="e:1a2b3c4d5e6f"]');
  assert.equal(unlit.classList.contains('is-lit'), false, 'an unrelated edge is not lit');
  assert.equal(unlit.style.getPropertyValue('--mlv-flow-delay'), '', 'and carries no delay');
  assert.equal(unlit.querySelector('.mlv-edge__flow'), null);
});

test('config edges light but never flow (F1-A4)', async () => {
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, BUILD_LOADERS));
  await sleep(HOVER_OPEN_MS + 100);
  const config = edgeEl(ctx, 'e:df6a9b1c7d8a');
  assert.equal(config.getAttribute('data-edge-kind'), 'config');
  assert.ok(config.classList.contains('is-lit'), 'the config edge is real and it is drawn');
  assert.equal(config.classList.contains('is-flowing'), false, 'but a fan-out hub never joins a stream');
  assert.equal(config.querySelector('.mlv-edge__flow'), null);
});

/* ── F1-A5: the latch ─────────────────────────────────────────────────── */

test('clicking an edge latches the pulse; Escape stops it (F1-A5)', async () => {
  const ctx = await app();
  const g = edgeEl(ctx, ISSUE_EDGE);
  click(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(1000);
  assert.ok(g.classList.contains('is-selected'), 'still selected a second later');
  assert.ok(g.classList.contains('is-flowing--pulse'), 'and still flowing, with no pointer anywhere');
  assert.ok(g.querySelector('.mlv-edge__flow'), 'the charge survives');

  key(ctx, ctx.canvas, 'Escape');
  assert.equal(g.classList.contains('is-selected'), false);
  assert.equal(g.classList.contains('is-flowing--pulse'), false);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});

test('clicking a node card produces no flow at all (F1-A5)', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing--pulse').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});

test('a pointer sweeping the diagram allocates no flow element (F1-A11)', async () => {
  const ctx = await app();
  const hits = Array.from(ctx.document.querySelectorAll('.mlv-edge__hit')).slice(0, 6);
  for (const hit of hits) {
    enter(ctx, hit);
    await sleep(25);
    leave(ctx, hit);
  }
  await sleep(HOVER_CLOSE_MS + 80);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'nothing was ever built');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__port').length, 0);
});

/* ── F1-A6: reduced motion, both halves ───────────────────────────────── */

test('prefers-reduced-motion never BUILDS a charge, and substitutes a chevron (F1-A6)', async () => {
  const ctx = await app(sample, { matchMedia: (q) => /prefers-reduced-motion/.test(q) });
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'reduced');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'static');

  const g = edgeEl(ctx, ISSUE_EDGE);
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(60); // the hover delays collapse to 0 under `reduce`
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'ZERO charge elements in the document');

  const dirs = g.querySelectorAll('.mlv-edge__dir');
  assert.equal(dirs.length, 1, 'exactly one direction mark');
  assert.match(dirs[0].getAttribute('transform'), /rotate\(/, 'rotated by the route midAngle');
  assert.equal(g.querySelectorAll('.mlv-edge__port').length, 2, 'hollow outlet, filled inlet');
  assert.ok(g.classList.contains('is-flowing--pulse'), 'the static substitute is still a marked edge');
  assert.ok(ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]').classList.contains('is-flow-source'));
});

test('the positive case: matchMedia present and NOT matching still animates (F1-A6)', async () => {
  const ctx = await app(sample, { matchMedia: () => false });
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'full');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
  const g = edgeEl(ctx, ISSUE_EDGE);
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_OPEN_MS + 80);
  assert.equal(g.querySelectorAll('.mlv-edge__flow').length, 1, '"no flow because reduced motion" and "no flow because broken" are different');
  assert.equal(g.querySelectorAll('.mlv-edge__dir').length, 0);
});

/* ── F1-A7: the toolbar toggle and its persistence ────────────────────── */

test('the flow toggle turns the whole layer off and persists (F1-A7)', async () => {
  const ctx = await app();
  const button = ctx.document.querySelector('.mlv-btn--flow');
  assert.ok(button, 'the toolbar carries a flow toggle');
  assert.equal(button.getAttribute('aria-pressed'), 'true');

  click(ctx, button);
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'off');
  assert.match(button.getAttribute('aria-label'), /off/);

  const g = edgeEl(ctx, ISSUE_EDGE);
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_OPEN_MS + 80);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'nothing is built while flow is off');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__port').length, 0);

  await sleep(300); // the debounced saveState
  assert.equal(ctx.bridge.saved.flow, false, 'the choice reached the host state');

  const back = await app(sample, { state: JSON.parse(JSON.stringify(ctx.bridge.saved)) });
  assert.equal(back.canvas.getAttribute('data-flow'), 'off', 'and it is restored on remount');
  assert.equal(back.document.querySelector('.mlv-btn--flow').getAttribute('aria-pressed'), 'false');
});

/* ── F1-A8: the cap ───────────────────────────────────────────────────── */

test('a 150-node / 300-edge hub hover goes static instead of animating 300 strokes (F1-A8)', async () => {
  const graph = makeSyntheticGraph(150, 300);
  const degree = new Map();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  const hub = Array.from(degree.entries()).sort((a, b) => b[1] - a[1])[0][0];
  const ctx = await app(graph);
  enter(ctx, hoverTarget(ctx, hub));
  await sleep(HOVER_OPEN_MS + 150);

  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0, 'nothing animates above the cap');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'static');
  const lit = ctx.document.querySelectorAll('.mlv-edge.is-lit').length;
  assert.ok(lit > 120, 'the lineage still READS: ' + lit + ' lit edges');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});

/* ── F1-A9: colour, resolved order-independently ──────────────────────── */

test('the charge takes the severity colour on a finding edge and the stage hue elsewhere (F1-A9)', async () => {
  const ctx = await app();
  const g = edgeEl(ctx, ISSUE_EDGE);
  assert.equal(g.getAttribute('data-sev'), 'high');
  assert.ok(g.classList.contains('has-issue'));
  assert.equal(g.getAttribute('data-stage'), 'model', 'stamped from the SOURCE node');

  const plain = edgeEl(ctx, 'e:9f21ab34cd56');
  assert.equal(plain.getAttribute('data-stage'), 'data');
  assert.equal(plain.classList.contains('has-issue'), false);

  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');
  const bySeverity = /\.mlv-edge\.has-issue\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-sev\)/.test(css);
  const byStage = /\.mlv-edge\[data-stage\]:not\(\.has-issue\)\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-stage\)/.test(css);
  assert.ok(bySeverity, 'the severity rule exists');
  assert.ok(byStage, 'the stage rule exists');
  // The two selectors are mutually exclusive, so their source order is irrelevant.
});

/* ── F1-A10: the keyboard reaches a connection at last ────────────────── */

test('e / Shift+E walk the selected node\'s connections and announce them (F1-A10)', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  key(ctx, ctx.canvas, 'e');

  const selected = ctx.document.querySelectorAll('.mlv-edge.is-selected');
  assert.equal(selected.length, 1, 'exactly one incident edge is selected');
  const first = selected[0].getAttribute('data-edge-id');
  assert.ok(selected[0].classList.contains('is-flowing--pulse'), 'and it pulses');
  const live = ctx.document.querySelector('[aria-live="polite"]').textContent;
  assert.match(live, /^Connection: /);
  assert.ok(live.indexOf('SmallNet') >= 0, live);

  key(ctx, ctx.canvas, 'E', { shiftKey: true });
  const next = ctx.document.querySelector('.mlv-edge.is-selected');
  assert.notEqual(next.getAttribute('data-edge-id'), first, 'Shift+E branches on shiftKey explicitly');

  const keymap = ctx.MLView.__internal.keymap;
  const rows = keymap.filter((row) => row.keys.indexOf('e') >= 0 && row.keys.indexOf('Shift+E') >= 0);
  assert.equal(rows.length, 1, 'the ? sheet lists the pair');
});

test('the canvas advertises its motion and flow modes at rest', async () => {
  const ctx = await app();
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'full');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
  const g = edgeEl(ctx, ISSUE_EDGE);
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_OPEN_MS + 60);
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
  leave(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(HOVER_CLOSE_MS + 80);
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion', 'and it returns to the resting mode');
});

/* ── review round 1: the regressions, one per confirmed finding ───────── */

test('high contrast paints the charge in ink, ON the edge (MLV-R1-FLOW-001)', async () => {
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');
  // The hc TOKEN block cannot win this one: a custom property declared on the
  // element itself always beats one inherited from an ancestor, whatever the
  // ancestor selector's specificity — so `.mlv-edge.has-issue` on the edge kept
  // the light theme's severity hue on a white cable over a black canvas. The
  // override therefore has to name the edge too, and to carry the class it must
  // outrank, so specificity decides it rather than source order.
  const ink = css.split('}').filter((rule) => /--mlv-flow-color:\s*var\(--mlv-text\)/.test(rule));
  assert.ok(ink.length >= 1, 'the hc charge colour exists at all');
  const onTheEdge = ink.filter((rule) => /\.mlv-edge\.has-issue/.test(rule) && /\.mlv-edge\[data-stage\]/.test(rule));
  assert.equal(onTheEdge.length, 1, 'exactly one element-level hc override, covering both colour rules');
  const selectors = onTheEdge[0];
  for (const host of ['body.vscode-high-contrast', 'body.vscode-high-contrast-light', ':root[data-theme="hc"]', '.mlv-root[data-theme="hc"]']) {
    assert.ok(selectors.indexOf(host + ' .mlv-edge.has-issue') >= 0, host + ' is covered');
    assert.ok(selectors.indexOf(host + ' .mlv-edge[data-stage]') >= 0, host + ' covers the stage rule too');
  }
});

test('a capped trace SAYS it is capped, and names scoping (11.14 C5, MLV-R1-FLOW-003)', async () => {
  const graph = makeSyntheticGraph(150, 300);
  const degree = new Map();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  const hub = Array.from(degree.entries()).sort((a, b) => b[1] - a[1])[0][0];
  const ctx = await app(graph);
  const card = hoverTarget(ctx, hub);
  enter(ctx, card);
  await sleep(HOVER_OPEN_MS + 150);

  const toasts = Array.from(ctx.document.querySelectorAll('.mlv-toast')).map((t) => t.textContent);
  assert.equal(toasts.length, 1, 'the silent branch now speaks: ' + JSON.stringify(toasts));
  assert.match(toasts[0], /scope/i, 'and it names scoping as the way to get the animation back');
  assert.ok(toasts[0].indexOf(String(ctx.MLView.__internal.flow.FLOW.MAX_EDGES)) >= 0, 'it quotes the cap: ' + toasts[0]);
  // The copy is the flow layer's own, so the two cannot drift apart.
  assert.ok(ctx.MLView.__internal.flow.cappedTraceMessage(300).indexOf('scope') >= 0);

  // A hover sweep may not spam it: the same card, twice, is one message.
  leave(ctx, card);
  await sleep(HOVER_CLOSE_MS + 80);
  enter(ctx, card);
  await sleep(HOVER_OPEN_MS + 150);
  assert.equal(ctx.document.querySelectorAll('.mlv-toast').length, 1, 'once per node, not once per hover');
});

test('clicking the card you are hovering does not kill the stream (MLV-R1-FLOW-005)', async () => {
  const ctx = await app();
  const card = hoverTarget(ctx, TRAIN);
  enter(ctx, card);
  await sleep(HOVER_OPEN_MS + 100);
  const streaming = ctx.document.querySelectorAll('.mlv-edge.is-flowing').length;
  assert.ok(streaming > 0, 'the lineage streams first: ' + streaming);

  click(ctx, card);
  await sleep(DOUBLE_CLICK_MS + 200); // a group's click waits for a possible second one
  assert.ok(ctx.document.querySelector('[data-node-id="' + TRAIN + '"]').classList.contains('is-selected'));
  assert.equal(
    ctx.document.querySelectorAll('.mlv-edge.is-flowing').length,
    streaming,
    'the hover the user earned survives the click that reads it in the rail',
  );
  // Row 8 stays honest: a click on a card nobody is hovering still starts nothing.
  const other = ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]');
  click(ctx, other);
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing--pulse').length, 0);
});

test('every connection owns some of its own length (MLV-R1-FLOW-006)', async () => {
  const { layout, flow } = (await loadBundle()).MLView.__internal;
  const routes = layout(sample).edges;
  assert.ok(routes.length >= 10, routes.length + ' routes');

  const pointAt = (points, t) => {
    let total = 0;
    const spans = [];
    for (let i = 1; i < points.length; i++) {
      const d = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
      spans.push(d);
      total += d;
    }
    let want = total * t;
    for (let i = 0; i < spans.length; i++) {
      if (want > spans[i] && i < spans.length - 1) {
        want -= spans[i];
        continue;
      }
      const k = spans[i] > 0 ? want / spans[i] : 0;
      return {
        x: points[i].x + (points[i + 1].x - points[i].x) * k,
        y: points[i].y + (points[i + 1].y - points[i].y) * k,
      };
    }
    return points[0];
  };

  const unreachable = [];
  for (const route of routes) {
    let owned = 0;
    for (let i = 1; i <= 9; i++) {
      const p = pointAt(route.points, i / 10);
      const winner = flow.nearestRoute(routes, p, 10);
      if (winner && winner.id === route.id) owned++;
    }
    if (owned === 0) unreachable.push(route.id);
  }
  assert.deepEqual(unreachable, [], 'a cable nobody can point at cannot be the gesture the feature hangs off');
});

test('the pointer picks the NEAREST cable, and that cable is raised (MLV-R1-FLOW-006)', async () => {
  const ctx = await app();
  const { flow } = ctx.MLView.__internal;
  // The rendered geometry, read back off the scene: every command in an
  // orthogonal route is a coordinate pair, so the numbers of `d` ARE the path.
  const polyOf = (g) => {
    const n = g
      .querySelector('.mlv-edge__path')
      .getAttribute('d')
      .match(/-?\d+(?:\.\d+)?/g)
      .map(Number);
    const points = [];
    for (let i = 0; i + 1 < n.length; i += 2) points.push({ x: n[i], y: n[i + 1] });
    return points;
  };
  const drawn = Array.from(ctx.document.querySelectorAll('.mlv-edge[data-edge-id]')).map((g) => ({
    id: g.getAttribute('data-edge-id'),
    points: polyOf(g),
  }));
  const g = edgeEl(ctx, ISSUE_EDGE);
  const mine = drawn.filter((r) => r.id === ISSUE_EDGE)[0];
  const others = drawn.filter((r) => r.id !== ISSUE_EDGE);

  // The point on this cable with the most clearance from every other cable —
  // i.e. one where the answer is a fact about geometry, not about a tie.
  let best = null;
  for (const point of mine.points) {
    let clearance = Infinity;
    for (const other of others) clearance = Math.min(clearance, flow.routeDistance(other, point));
    if (!best || clearance > best.clearance) best = { point, clearance };
  }
  assert.ok(best.clearance > 20, 'a point that is unambiguously on this cable: ' + best.clearance.toFixed(1) + 'px');

  const world = ctx.document.querySelector('.mlv-world');
  const m = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/.exec(world.style.transform);
  assert.ok(m, 'the world carries a transform: ' + world.style.transform);
  const [tx, ty, zoom] = [Number(m[1]), Number(m[2]), Number(m[3])];
  ctx.canvas.dispatchEvent(
    new ctx.window.MouseEvent('pointermove', {
      bubbles: true,
      clientX: best.point.x * zoom + tx,
      clientY: best.point.y * zoom + ty,
    }),
  );
  const hovered = Array.from(ctx.document.querySelectorAll('.mlv-edge.is-hover')).map((e) => e.getAttribute('data-edge-id'));
  assert.deepEqual(hovered, [ISSUE_EDGE], 'geometry, not document order, decided it');
  assert.equal(g.parentNode.lastChild, g, 'and the hovered cable is raised above the ones it shares a gutter with');

  // Far from every cable, nothing is hovered.
  ctx.canvas.dispatchEvent(new ctx.window.MouseEvent('pointermove', { bubbles: true, clientX: -4000, clientY: -4000 }));
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-hover').length, 0);
});

test('the canvas keymap survives focus falling to the page (MLV-R1-FLOW-007)', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  // Focus sits on <body>, exactly where a clipboard fallback or a host dialog
  // leaves it. Every key below therefore never passes through `.mlv-canvas`.
  assert.equal(ctx.document.activeElement, ctx.document.body);

  key(ctx, ctx.document.body, 'e');
  const first = ctx.document.querySelector('.mlv-edge.is-selected');
  assert.ok(first, 'e reached the canvas keymap from the page');
  key(ctx, ctx.document.body, 'E', { shiftKey: true });
  assert.notEqual(ctx.document.querySelector('.mlv-edge.is-selected').getAttribute('data-edge-id'), first.getAttribute('data-edge-id'));
  key(ctx, ctx.document.body, 'Escape');
  assert.equal(ctx.document.querySelector('.mlv-edge.is-selected'), null, 'and so did Escape');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'the latched pulse can be dismissed again');
});

test('a keystroke inside the search field is never taken by the canvas (MLV-R1-FLOW-007)', async () => {
  const ctx = await app();
  const input = ctx.document.querySelector('.mlv-search input, input.mlv-search__input, .mlv-chrome input');
  assert.ok(input, 'the chrome has a search field');
  input.focus();
  key(ctx, input, 'e');
  assert.equal(ctx.document.querySelector('.mlv-edge.is-selected'), null, 'typing "e" is typing, not a shortcut');
  key(ctx, input, '0');
  assert.equal(ctx.document.querySelector('.mlv-edge.is-selected'), null);
});

test('the standalone copy fallback leaves focus where it found it (MLV-R1-FLOW-007)', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  ctx.MLView.mount(root, sample, ctx.MLView.bridges.standalone());
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.focus();
  assert.equal(ctx.document.activeElement, canvas);
  // The click schedules the vscode:// hand-off and, 400 ms later, the textarea
  // copy fallback. (jsdom's `select()` does not move focus, so this pins the
  // restore contract rather than reproducing the browser's theft; the keymap
  // guard above is what makes the symptom impossible either way.)
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  await sleep(700);
  assert.equal(ctx.document.activeElement, canvas, 'the canvas still has focus after the copy');
});

test('reduced motion keeps the DIRECTION on a node hover too (MLV-R3-002)', async () => {
  const ctx = await app(sample, { matchMedia: (q) => /prefers-reduced-motion/.test(q) });
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(120); // the hover delays collapse to 0 under `reduce`
  const streaming = Array.from(ctx.document.querySelectorAll('.mlv-edge.is-flowing'));
  assert.ok(streaming.length >= 8, 'the lineage still streams, statically: ' + streaming.length);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'and never builds a charge');
  for (const g of streaming) {
    assert.equal(g.querySelectorAll('.mlv-edge__dir').length, 1, 'a chevron per lineage edge');
    assert.match(g.querySelector('.mlv-edge__dir').getAttribute('transform'), /rotate\(/);
    assert.equal(g.querySelectorAll('.mlv-edge__port').length, 2, 'hollow outlet, filled inlet');
  }
});

test('Escape never leaves a focused connection stripped of its ports (MLV-R1-FLOW-011)', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  key(ctx, ctx.canvas, 'e');
  const selected = ctx.document.querySelector('.mlv-edge.is-selected');
  assert.ok(selected.querySelectorAll('.mlv-edge__port').length === 2, 'the focused edge shows both ports first');

  key(ctx, ctx.canvas, 'Escape');
  for (const g of ctx.document.querySelectorAll('.mlv-edge.is-hover')) {
    assert.ok(g.querySelectorAll('.mlv-edge__port').length > 0, 'emphasised and focused, but with no direction cue');
  }
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-hover').length, 0, 'focus left the connection with the pulse');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});

/* ── review round 2: one regression per confirmed finding ─────────────── */

test('a streaming edge carries a RESOLVED dash endpoint, never a calc (R2-FLOW-01)', async () => {
  // Chromium keeps a var()-derived calc() unsimplified and cannot interpolate it
  // against `0`, so `to { stroke-dashoffset: calc(-1 * (var(--head) + var(--gap))) }`
  // degraded the whole stream to a DISCRETE step between two endpoints exactly
  // one dash period apart — two identical frames, a current that never moves.
  // Verified in Chromium 1243 on this bundle: with the calc keyframe the page is
  // byte-identical across six virtual-time screenshots; with this one all six differ.
  const ctx = await app();
  enter(ctx, hoverTarget(ctx, TRAIN));
  await sleep(HOVER_OPEN_MS + 120);
  const streaming = Array.from(ctx.document.querySelectorAll('.mlv-edge.is-flowing'));
  assert.ok(streaming.length >= 5, 'the lineage streams: ' + streaming.length);

  for (const g of streaming) {
    const style = g.getAttribute('style') || '';
    assert.equal(style.indexOf('calc('), -1, 'no calc reaches the animated side: ' + style);
    const num = (prop) => Number(g.style.getPropertyValue(prop));
    const head = num('--mlv-flow-head');
    const gap = num('--mlv-flow-gap');
    const end = num('--mlv-flow-end');
    assert.ok(head > 0 && gap > 0, 'head and gap are path units: ' + head + ' / ' + gap);
    assert.ok(end < 0, 'the endpoint runs backwards along the route: ' + end);
    assert.ok(Math.abs(end + (head + gap)) < 0.02, end + ' is -(head + gap) = ' + -(head + gap));
  }

  // ...and it is cleared with the rest of the set (11.14 C1).
  ctx.app.setFilters({ showSuppressed: true });
  for (const g of ctx.document.querySelectorAll('.mlv-edge')) {
    assert.equal((g.getAttribute('style') || '').indexOf('--mlv-flow-end'), -1, 'stripEdge clears the new property too');
  }
});

test('no keyframe animating stroke-dashoffset contains a calc (R2-FLOW-01 gate)', async () => {
  // jsdom executes no CSS animation, so this class of bug is invisible to every
  // DOM assertion above. The stylesheet itself is the gate.
  //
  // Amended 2026-09-08 (CONTRACTS 11.13.1): the PULSE no longer animates a dash
  // at all -- its charge is a DOT moved by SMIL <animateMotion> -- so the
  // `mlv-flow-pulse` keyframe was deleted with the line it drove. The STREAM
  // still animates `stroke-dashoffset`, and it is still the one that must never
  // see a calc() on the animated side.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');
  const blocks = css.match(/@keyframes\s+[\w-]+\s*\{[\s\S]*?\n\}/g) || [];
  assert.ok(blocks.length >= 2, 'found ' + blocks.length + ' keyframe blocks');
  const dashing = blocks.filter((b) => b.indexOf('stroke-dashoffset') >= 0);
  assert.equal(dashing.length, 1, 'the stream is the only dash animation left: ' + dashing.length);
  for (const block of dashing) {
    assert.equal(block.indexOf('calc('), -1, 'a var()-derived calc() cannot be interpolated:\n' + block);
  }
  const stream = dashing.find((b) => b.indexOf('mlv-flow-stream') >= 0);
  assert.ok(stream, 'and the survivor is the stream');
  assert.ok(/stroke-dashoffset:\s*var\(--mlv-flow-end/.test(stream), 'the stream ends at the inline endpoint:\n' + stream);
  assert.equal(css.indexOf('@keyframes mlv-flow-pulse'), -1, 'the retired pulse keyframe left no dead block behind');
  assert.equal(css.indexOf('animation: mlv-flow-pulse'), -1, 'and nothing still references it');
});

test('the two endpoint rings differ by GEOMETRY, not only hue (R2-FLOW-02)', async () => {
  // `--mlv-stage-model` is byte-identical to `--mlv-accent` in every theme, and
  // the hc block redefines no stage hue at all, so on any model-stage edge — the
  // demo's flagship SmallCNN --logits--> criterion included — the source and
  // target rings resolved to the same colour and the direction cue died. Measured
  // in Chromium 1243 after the fix: source `rgb(59,108,246) 0 0 0 2px`, target
  // `rgb(255,255,255) 0 0 0 2px, rgb(59,108,246) 0 0 0 4px`.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');
  const decl = (cls) => {
    const at = css.indexOf('.mlv-group.' + cls);
    assert.ok(at > 0, cls + ' has no rule');
    return css.slice(at, css.indexOf('}', at)).replace(/\s+/g, ' ');
  };
  const source = decl('is-flow-source');
  const target = decl('is-flow-target');
  const layers = (d) => (d.match(/0 0 0 \d+px/g) || []).length;
  assert.equal(layers(source), 1, 'the outlet card keeps its single stage-hue ring: ' + source);
  assert.equal(layers(target), 2, 'the inlet card reads as a DOUBLE ring: ' + target);
  assert.ok(target.indexOf('var(--mlv-surface)') >= 0, 'with a surface-coloured spacer: ' + target);
  // The worst case the finding measured: every hue in both rules collapses to one.
  const flatten = (d) => d.replace(/var\([^)]*\)/g, 'HUE');
  assert.notEqual(flatten(source), flatten(target), 'the pair must survive --mlv-stage === --mlv-accent');
});

test('a dense lineage speaks under REDUCED motion too (R2-FLOW-03 / R2-FLOW-07)', async () => {
  // The one audience with no animation to fall back on was the only one told
  // nothing at all: `capped` was suppressed whenever the motion flag was
  // `reduced`, so a reduced-motion user hovering a dense card got no chevrons,
  // no ports and no explanation.
  const graph = makeSyntheticGraph(150, 300);
  const degree = new Map();
  for (const edge of graph.edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }
  const hub = Array.from(degree.entries()).sort((a, b) => b[1] - a[1])[0][0];
  const ctx = await app(graph, { matchMedia: (q) => /prefers-reduced-motion/.test(q) });
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'reduced');
  enter(ctx, hoverTarget(ctx, hub));
  await sleep(HOVER_OPEN_MS + 150);

  assert.equal(ctx.document.querySelectorAll('.mlv-edge__dir').length, 0, 'still nothing is decorated at this density');
  const toasts = Array.from(ctx.document.querySelectorAll('.mlv-toast')).map((t) => t.textContent);
  assert.equal(toasts.length, 1, 'and the branch is no longer silent: ' + JSON.stringify(toasts));
  assert.match(toasts[0], /scope/i, 'it names scoping (11.14 C5)');
  assert.doesNotMatch(toasts[0], /animat/i, 'without promising an animation this reader never gets');
});

test('the capped copy is a sentence, not "298 of 120 connections" (R2-FLOW-06)', async () => {
  const { cappedTraceMessage, FLOW } = (await loadBundle()).MLView.__internal.flow;
  for (const motion of ['full', 'reduced']) {
    const text = cappedTraceMessage(298, motion);
    assert.equal(text.indexOf('298 of ' + FLOW.MAX_EDGES), -1, 'a subset construction reads as a bug: ' + text);
    assert.ok(text.indexOf('298 connections') >= 0, text);
    assert.ok(text.indexOf(String(FLOW.MAX_EDGES)) >= 0, 'the cap is still quoted: ' + text);
    assert.match(text, /scope/i);
  }
  assert.notEqual(cappedTraceMessage(298, 'full'), cappedTraceMessage(298, 'reduced'), 'each audience is told what IT loses');
});

test('re-enabling the flow restores the cable the pointer is on (R2-FLOW-08)', async () => {
  const ctx = await app();
  const g = edgeEl(ctx, ISSUE_EDGE);
  const hit = g.querySelector('.mlv-edge__hit');
  enter(ctx, hit);
  await sleep(HOVER_OPEN_MS + 80);
  assert.ok(g.querySelector('.mlv-edge__flow'), 'a charge runs first');

  const button = ctx.document.querySelector('.mlv-btn--flow');
  click(ctx, button);
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'off');
  assert.equal(g.querySelectorAll('.mlv-edge__flow').length, 0, 'off means off');

  click(ctx, button);
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
  assert.ok(g.classList.contains('is-flowing--pulse'), 'the pointer still owns this cable');
  assert.ok(g.querySelector('.mlv-edge__flow'), 'so the charge comes back without a second hover');

  // Row 8 stays honest: with the pointer on nothing, re-enabling starts nothing.
  leave(ctx, hit);
  await sleep(HOVER_CLOSE_MS + 120);
  click(ctx, button);
  click(ctx, button);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0);
});

test('the arrowhead stands down for the inlet dot while a charge runs (R2-FLOW-09)', async () => {
  // The inlet is pinned to the last coordinate pair of `d` (F1-A1), which is
  // exactly where `marker-end` draws the arrowhead: on a horizontal arrival the
  // 9 px arrow covered the 7 px dot and the pair read as one dark smudge, losing
  // the filled-inlet half of the direction cue FEATURES 2.8 counts on.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');
  const at = css.indexOf('marker-end: none');
  assert.ok(at > 0, 'no rule stands the marker down');
  const rule = css.slice(css.lastIndexOf('}', at) + 1, css.indexOf('}', at)).replace(/\s+/g, ' ');
  assert.ok(rule.indexOf('.mlv-edge.is-flowing .mlv-edge__path') >= 0, rule);
  assert.ok(rule.indexOf('.mlv-edge.is-flowing--pulse .mlv-edge__path') >= 0, rule);
  assert.ok(rule.indexOf('[data-flow="motion"]') >= 0, 'only while a charge actually runs: ' + rule);
});

/* ── R3-CHG-02: a mid-session motion flip REBUILDS what was running ────── */

/**
 * A `prefers-reduced-motion` media query whose listeners actually fire, so a
 * flip can be driven from the test the way the OS drives it. `app()`'s stub
 * accepts listeners and drops them, which is enough to pin the state a mount
 * STARTS in and useless for pinning what a CHANGE does.
 */
function motionStub(ctx) {
  const listeners = [];
  let reduced = false;
  ctx.window.matchMedia = (q) => {
    const isMotion = /prefers-reduced-motion/.test(q);
    return {
      media: q,
      get matches() {
        return isMotion ? reduced : false;
      },
      addEventListener(_type, fn) {
        if (isMotion) listeners.push(fn);
      },
      removeEventListener(_type, fn) {
        const at = listeners.indexOf(fn);
        if (at >= 0) listeners.splice(at, 1);
      },
      addListener() {},
      removeListener() {},
      onchange: null,
      dispatchEvent() {
        return false;
      },
    };
  };
  return (next) => {
    reduced = next;
    for (const fn of listeners.slice()) fn({ matches: next });
  };
}

async function motionApp() {
  const ctx = await loadBundle();
  const flip = motionStub(ctx);
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, sample, bridge);
  return { ...ctx, flip, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

test('flipping to reduce mid-session leaves a LATCHED cable its static cue (R3-CHG-02)', async () => {
  // `setMotion` only clears, exactly as `setEnabled` did before R2-FLOW-08. The
  // selection latch was therefore stripped of the charge AND of the ports and
  // chevron that are meant to replace it — handed to the one reader who has no
  // animation to fall back on — and flipping back restored nothing.
  const ctx = await motionApp();
  const g = edgeEl(ctx, ISSUE_EDGE);
  click(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(60);
  assert.ok(g.classList.contains('is-selected'), 'the pulse is latched by the selection');
  assert.ok(g.querySelector('.mlv-edge__charge'), 'and a charge is running');

  ctx.flip(true);
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'reduced');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'static');
  assert.ok(g.classList.contains('is-selected'), 'the connection is still the selection');
  assert.ok(g.classList.contains('is-flowing--pulse'), 'and still the one carrying flow');
  assert.equal(g.querySelectorAll('.mlv-edge__charge').length, 0, 'nothing animates under reduce');
  assert.equal(g.querySelectorAll('.mlv-edge__port').length, 2, 'but the ports come back');
  assert.equal(g.querySelectorAll('.mlv-edge__dir').length, 1, 'and so does the chevron (FEATURES 2.8)');

  ctx.flip(false);
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'motion');
  assert.ok(g.querySelector('.mlv-edge__charge'), 'flipping back restores the dot without a second gesture');
  assert.equal(g.querySelectorAll('.mlv-edge__dir').length, 0, 'and retires the substitute');
});

test('a flip never leaves a FOCUSED connection with no direction cue (R3-CHG-02, MLV-R1-FLOW-011)', async () => {
  const ctx = await motionApp();
  key(ctx, ctx.canvas, 'ArrowDown');
  key(ctx, ctx.canvas, 'e');
  await sleep(60);
  const g = ctx.document.querySelector('.mlv-edge.is-hover, .mlv-edge.is-selected');
  assert.ok(g, 'the keyboard focused a connection');
  const hit = g.querySelector('.mlv-edge__hit');
  assert.equal(ctx.document.activeElement, hit, 'and DOM focus is on its hit path');
  assert.ok(g.querySelector('.mlv-edge__charge'), 'which pulses');

  ctx.flip(true);
  assert.equal(ctx.document.activeElement, hit, 'the flip does not move focus');
  assert.equal(g.querySelectorAll('.mlv-edge__charge').length, 0);
  assert.ok(
    g.querySelectorAll('.mlv-edge__port').length === 2 && g.querySelectorAll('.mlv-edge__dir').length === 1,
    'a connection holding focus is never left with NO direction cue: ' + g.getAttribute('class'),
  );

  ctx.flip(false);
  assert.ok(g.querySelector('.mlv-edge__charge'), 'and the charge returns with the preference');
});
