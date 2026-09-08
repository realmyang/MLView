/**
 * The charge is a DOT with a halo (CONTRACTS 11.13.1, amended 2026-09-08).
 *
 * Feature 1 shipped the single-cable charge as a moving DASH SEGMENT: a 12 px
 * head sliding along `stroke-dashoffset`. On a 3 px stroke, in the middle of a
 * diagram full of 3 px strokes, that reads as a brighter piece of cable rather
 * than as a thing travelling through one — the "electron in a wire" the feature
 * is named after never actually appeared. It is now a travelling DOT: three
 * concentric circles moved by SMIL `<animateMotion>` riding the edge's own
 * visible path through `<mpath>`.
 *
 * The runner executes neither CSS animations nor SMIL, which is why every
 * assertion here is about DOM IDENTITY and DECLARED TIMING — the element that
 * exists, the id it points at, the duration it was given — and never about a
 * position at a moment in time.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, WEBVIEW_ROOT } from './helpers.mjs';

const sample = await readSample();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Mirrored from canvasview.ts — the delays the flow deliberately hangs off. */
const HOVER_OPEN_MS = 400;
const HOVER_CLOSE_MS = 120;

/** The one data edge that already carries a high-severity finding. */
const ISSUE_EDGE = 'e:4c7d0e2f8a91';
/** A long cross-lane route: 1453 px, comfortably over FLOW.CHARGE_TWIN_PX. */
const LONG_EDGE = 'e:9f21ab34cd56';
const SMALLNET = 'n:8d3e0f7a2b61';

const XLINK = ['http', '//www.w3.org/1999/xlink'].join(':');

async function app(graph = sample, opts = {}) {
  const ctx = await loadBundle();
  if (opts.matchMedia) {
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
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => opts.state || null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, graph, bridge);
  return { ...ctx, bridge, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const enter = (ctx, el) => el.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
const leave = (ctx, el) => el.dispatchEvent(new ctx.window.Event('pointerleave', { bubbles: false }));
const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const key = (ctx, el, k) => el.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
const edgeEl = (ctx, id) => ctx.document.querySelector('[data-edge-id="' + id + '"]');

/** The declared duration of the charge on an edge, from the ROUTE, never the DOM. */
function expectedDur(ctx, id) {
  const { flow, layout } = ctx.MLView.__internal;
  const route = layout(sample).edges.filter((r) => r.id === id)[0];
  assert.ok(route, 'the sample still routes ' + id);
  return { dur: flow.pulseDurationMs(flow.polylineLength(route.points)), length: flow.polylineLength(route.points) };
}

async function hoverEdge(ctx, id) {
  const g = edgeEl(ctx, id);
  const hit = g.querySelector('.mlv-edge__hit');
  enter(ctx, hit);
  await sleep(HOVER_OPEN_MS + 80);
  return { g, hit };
}

/* ── F1-A12: the shape of the charge ──────────────────────────────────── */

test('a hovered cable carries a charge GROUP of three concentric circles (F1-A12)', async () => {
  const ctx = await app();
  const { g } = await hoverEdge(ctx, ISSUE_EDGE);

  const charges = g.querySelectorAll('.mlv-edge__charge');
  assert.equal(charges.length, 1, 'a 132 px route runs exactly one dot');
  const charge = charges[0];
  assert.equal(charge.tagName.toLowerCase(), 'g', 'the charge is a group, so one transform moves all of it');

  const halo = charge.querySelector('.mlv-edge__charge-halo');
  const glow = charge.querySelector('.mlv-edge__charge-glow');
  const core = charge.querySelector('.mlv-edge__charge-core');
  assert.ok(halo && glow && core, 'halo, glow and core all exist');
  for (const circle of [halo, glow, core]) {
    assert.equal(circle.tagName.toLowerCase(), 'circle');
    assert.equal(circle.getAttribute('cx'), '0', 'every ring sits at the group origin, so they stay concentric');
    assert.equal(circle.getAttribute('cy'), '0');
  }
  // The radii are the shipped constants, so a redesign cannot silently drift.
  const { FLOW } = ctx.MLView.__internal.flow;
  assert.equal(Number(halo.getAttribute('r')), FLOW.CHARGE_HALO_R);
  assert.equal(Number(glow.getAttribute('r')), FLOW.CHARGE_GLOW_R);
  assert.equal(Number(core.getAttribute('r')), FLOW.CHARGE_CORE_R);
  assert.ok(
    Number(halo.getAttribute('r')) > Number(glow.getAttribute('r')) &&
      Number(glow.getAttribute('r')) > Number(core.getAttribute('r')),
    'the soft edge is a stack, widest first',
  );

  // The line it replaced is still there, but only as the static energised wash.
  const flow = g.querySelector('.mlv-edge__flow');
  assert.ok(flow, 'the cable keeps its full-length underlay');
  assert.equal(flow.getAttribute('d'), g.querySelector('.mlv-edge__path').getAttribute('d'));
});

test('the charge is moved by animateMotion riding the edge path (F1-A12)', async () => {
  const ctx = await app();
  const { g } = await hoverEdge(ctx, ISSUE_EDGE);
  const { dur } = expectedDur(ctx, ISSUE_EDGE);

  const motion = g.querySelector('.mlv-edge__charge animateMotion');
  assert.ok(motion, 'the dot is moved by SMIL, not by a per-frame script');
  assert.equal(motion.getAttribute('dur'), dur + 'ms', 'the duration is pulseDurationMs(route length)');
  assert.equal(motion.getAttribute('repeatCount'), 'indefinite');
  assert.equal(motion.getAttribute('calcMode'), 'linear', 'constant speed, as the contract requires');
  assert.equal(motion.getAttribute('rotate'), 'auto');
  assert.equal(motion.getAttribute('begin'), null, 'the leading dot starts at zero phase');

  const path = g.querySelector('.mlv-edge__path');
  const id = path.getAttribute('id');
  assert.ok(id, 'the visible path carries an id for <mpath> to name');
  const mpath = motion.querySelector('mpath');
  assert.ok(mpath, 'and the motion is a reference to it, not a second copy of d');
  assert.equal(mpath.getAttribute('href'), '#' + id, 'SVG 2 href');
  assert.equal(mpath.getAttributeNS(XLINK, 'href'), '#' + id, 'and the SVG 1.1 xlink:href, in the XLink namespace');
});

test('every charge points at a path that actually exists (F1-A12)', async () => {
  // `<mpath>` pointing at nothing is undefined behaviour, and the degenerate
  // route is the branch that would do it (CONTRACTS 11.13.1 rule 5).
  const ctx = await app();
  for (const id of [ISSUE_EDGE, LONG_EDGE]) {
    const { g } = await hoverEdge(ctx, id);
    const charges = g.querySelectorAll('.mlv-edge__charge');
    assert.ok(charges.length >= 1, id + ' runs a charge');
    for (const charge of charges) {
      const ref = charge.querySelector('mpath').getAttribute('href');
      assert.match(ref, /^#mlv-p-/);
      const target = ctx.document.getElementById(ref.slice(1));
      assert.ok(target, 'the motion path resolves: ' + ref);
      assert.ok(target.classList.contains('mlv-edge__path'), 'and it is the VISIBLE geometry');
      assert.equal(target.getAttribute('d'), g.querySelector('.mlv-edge__path').getAttribute('d'));
    }
  }
});

test('a long route runs a SECOND dot half a period behind (F1-A12)', async () => {
  const ctx = await app();
  const { g } = await hoverEdge(ctx, LONG_EDGE);
  const { dur, length } = expectedDur(ctx, LONG_EDGE);
  const { FLOW } = ctx.MLView.__internal.flow;
  assert.ok(length > FLOW.CHARGE_TWIN_PX, 'this route really is a long one: ' + Math.round(length) + 'px');

  const charges = g.querySelectorAll('.mlv-edge__charge');
  assert.equal(charges.length, 2, 'so the cable never looks empty');
  const begins = Array.from(charges).map((c) => c.querySelector('animateMotion').getAttribute('begin'));
  assert.deepEqual(begins, [null, '-' + Math.round(dur / 2) + 'ms'], 'a NEGATIVE begin is a phase offset, not a delay');
  for (const charge of charges) {
    assert.equal(charge.querySelector('animateMotion').getAttribute('dur'), dur + 'ms', 'both run at the same speed');
  }
});

/* ── F1-A13: the path id is unique across mounts ──────────────────────── */

test('two apps on ONE document never share a motion path (F1-A13)', async () => {
  // dev/states.html mounts several apps on one page, and a report may be
  // embedded next to another one. `<mpath href="#...">` is a document-wide
  // reference, so a colliding id would run one app's charge along the other
  // app's cable.
  const ctx = await loadBundle();
  const bridge = () => ({
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  });
  const first = ctx.document.getElementById('mlview-root');
  const second = ctx.document.createElement('div');
  ctx.document.body.appendChild(second);
  ctx.MLView.mount(first, sample, bridge());
  ctx.MLView.mount(second, sample, bridge());

  const idsIn = (root) => Array.from(root.querySelectorAll('.mlv-edge__path')).map((p) => p.getAttribute('id'));
  const a = idsIn(first);
  const b = idsIn(second);
  assert.ok(a.length > 10 && a.length === b.length, 'both mounts drew the same edges: ' + a.length);
  for (const id of a.concat(b)) assert.match(id, /^mlv-p-\d+-[0-9a-f]+$/, 'the id is a bare hex token: ' + id);
  assert.equal(new Set(a).size, a.length, 'ids are unique WITHIN a mount');
  assert.equal(new Set(a.concat(b)).size, a.length + b.length, 'and across two mounts on one document');

  // The format is the flow layer's own, so no test hard-codes it.
  const { edgePathId } = ctx.MLView.__internal.flow;
  assert.notEqual(edgePathId(1, ISSUE_EDGE), edgePathId(2, ISSUE_EDGE), 'the serial is what separates them');
  assert.notEqual(edgePathId(1, ISSUE_EDGE), edgePathId(1, LONG_EDGE), 'and the edge id is what separates these');
  assert.equal(edgePathId(3, 'ab'), edgePathId(3, 'ab'), 'and it is a pure function');
  assert.notEqual(edgePathId(1, 'ab'), edgePathId(1, '慢'), 'fixed-width hex cannot alias two different ids');
});

/* ── F1-A14: nothing leaks ────────────────────────────────────────────── */

test('unhovering strips every part of the charge (F1-A14)', async () => {
  const ctx = await app();
  const { g, hit } = await hoverEdge(ctx, ISSUE_EDGE);
  assert.equal(g.querySelectorAll('.mlv-edge__charge').length, 1);

  leave(ctx, hit);
  await sleep(HOVER_CLOSE_MS + 120);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'the dot goes');
  assert.equal(ctx.document.querySelectorAll('animateMotion').length, 0, 'and so does its timeline');
  assert.equal(ctx.document.querySelectorAll('mpath').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'with the underlay it rode');
});

test('no charge survives a selection change, a scope change or destroy (F1-A14, 11.14 C1)', async () => {
  const ctx = await app();

  // A latched pulse: click the cable, take the pointer off it, and the dot
  // stays. Then select a card instead, and it must go.
  const { hit } = await hoverEdge(ctx, ISSUE_EDGE);
  click(ctx, hit);
  leave(ctx, hit);
  await sleep(HOVER_CLOSE_MS + 120);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 1, 'the latch keeps exactly one, with no pointer on it');
  click(ctx, ctx.document.querySelector('[data-node-id="' + SMALLNET + '"]'));
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'selecting a card drops the latched dot');

  // A re-projection replaces the whole scene (11.14 C1).
  await hoverEdge(ctx, ISSUE_EDGE);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 1);
  ctx.app.setScope('concern:evaluation');
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'the re-projection cleared it');
  ctx.app.setScope(null);
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'and so did clearing the scope');

  // Escape, with the pointer off the cable — a pointer still resting on it is
  // rung 4 of the latch cascade and legitimately keeps its own pulse.
  const again = await hoverEdge(ctx, ISSUE_EDGE);
  click(ctx, again.hit);
  leave(ctx, again.hit);
  await sleep(HOVER_CLOSE_MS + 120);
  key(ctx, ctx.canvas, 'Escape');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'Escape leaves none behind');

  await hoverEdge(ctx, ISSUE_EDGE);
  ctx.app.destroy();
  await sleep(60);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'and destroy() leaves none running');
});

test('a pointer sweeping the diagram allocates no charge at all (F1-A14)', async () => {
  const ctx = await app();
  const hits = Array.from(ctx.document.querySelectorAll('.mlv-edge__hit')).slice(0, 6);
  for (const hit of hits) {
    enter(ctx, hit);
    await sleep(25);
    leave(ctx, hit);
  }
  await sleep(HOVER_CLOSE_MS + 80);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'nothing was ever built');
});

/* ── F1-A15: reduced motion, and the layer switch ─────────────────────── */

test('reduced motion builds NO charge, and keeps the chevron (F1-A15)', async () => {
  const ctx = await app(sample, { matchMedia: (q) => /prefers-reduced-motion/.test(q) });
  assert.equal(ctx.canvas.getAttribute('data-motion'), 'reduced');
  const g = edgeEl(ctx, ISSUE_EDGE);
  enter(ctx, g.querySelector('.mlv-edge__hit'));
  await sleep(80); // the hover delays collapse to 0 under `reduce`
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'zero charge groups in the document');
  assert.equal(ctx.document.querySelectorAll('animateMotion').length, 0, 'and zero SMIL timelines');
  assert.equal(g.querySelectorAll('.mlv-edge__dir').length, 1, 'the static substitute is unchanged');
});

test('the flow toggle removes the charge with everything else (F1-A15)', async () => {
  const ctx = await app();
  await hoverEdge(ctx, ISSUE_EDGE);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 1);
  click(ctx, ctx.document.querySelector('.mlv-btn--flow'));
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'off');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'off means off');
  click(ctx, ctx.document.querySelector('.mlv-btn--flow'));
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 1, 'and back on means back on');
});

/* ── F1-A16: colour and cost, in the stylesheet ───────────────────────── */

test('the dot is painted from --mlv-flow-color, so severity still runs RED (F1-A16)', async () => {
  const ctx = await app();
  const { g } = await hoverEdge(ctx, ISSUE_EDGE);
  assert.equal(g.getAttribute('data-sev'), 'high', 'this is the softmax -> CrossEntropyLoss edge');
  assert.ok(g.classList.contains('has-issue'), 'so --mlv-flow-color resolves to var(--mlv-sev)');

  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const ruleFor = (cls) => {
    const at = css.indexOf('.' + cls + ' {');
    assert.ok(at > 0, cls + ' has no rule in the stylesheet');
    return css.slice(at, css.indexOf('}', at)).replace(/\s+/g, ' ');
  };
  const halo = ruleFor('mlv-edge__charge-halo');
  const glow = ruleFor('mlv-edge__charge-glow');
  const core = ruleFor('mlv-edge__charge-core');
  assert.ok(halo.indexOf('fill: var(--mlv-flow-color') >= 0, halo);
  assert.ok(glow.indexOf('fill: var(--mlv-flow-color') >= 0, glow);
  assert.ok(core.indexOf('stroke: var(--mlv-flow-color') >= 0, core);
  // The core is a surface-filled bead RINGED in the hue, so it stays visible on
  // a cable of its own colour — the same trick the inlet port plays.
  assert.ok(core.indexOf('fill: var(--mlv-surface)') >= 0, core);
  // Stacked opacities, widest and faintest first.
  const alpha = (rule) => Number((/fill-opacity: var\([^,]+, ([0-9.]+)\)/.exec(rule) || [])[1]);
  assert.ok(alpha(halo) > 0 && alpha(halo) < alpha(glow), 'the halo is the faintest ring: ' + halo);
});

test('the halo is opacity, never a filter primitive (F1-A16)', async () => {
  // A filter on a moving element re-rasterizes its filter region every frame,
  // which is precisely the cost flow.css's header rules out.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  // Comments stripped first: this file's own header NAMES the things it bans.
  const flowLayer = css
    .slice(css.indexOf('---- flow.css ----'), css.indexOf('---- scope.css ----'))
    .replace(/\/\*[\s\S]*?\*\//g, ' ');
  assert.ok(flowLayer.length > 500, 'found the flow layer in the built stylesheet');
  for (const banned of ['filter:', 'backdrop-filter:', 'will-change:']) {
    assert.equal(flowLayer.indexOf(banned), -1, 'flow.css declares ' + banned);
  }
  // The SHIPPED bundle is the gate, not the sources: this layer's comments name
  // the primitives precisely in order to ban them, and esbuild strips comments,
  // so a hit here is a `createElementNS` call and nothing else.
  const bundle = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.js'), 'utf8');
  for (const primitive of ['feGaussianBlur', 'feDropShadow', 'feColorMatrix', 'feOffset', 'feMerge']) {
    assert.equal(bundle.indexOf(primitive), -1, 'the bundle builds an SVG filter primitive: ' + primitive);
  }
  assert.ok(bundle.indexOf('mlv-edge__charge-halo') > 0, 'and the halo it replaced them with does ship');
});

test('the stylesheet removes the DOT under reduced motion and under flow-off (F1-A15)', async () => {
  // SMIL is not CSS: the blanket `animation-duration: 0.01ms` clamp in base.css
  // does not touch `<animateMotion>` at all, so the charge needs its own removal
  // rather than relying on the clamp that covers the dash stream.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const blocks = css.split('@media (prefers-reduced-motion: reduce)');
  const naming = blocks.slice(1).filter((b) => b.slice(0, 600).indexOf('mlv-edge__charge') >= 0);
  assert.equal(naming.length, 1, 'exactly one reduced-motion block removes the charge');
  assert.ok(/mlv-edge__charge\s*\{[^}]*display:\s*none\s*!important/.test(naming[0]), 'and it removes it outright');

  const off = css.indexOf('[data-flow="off"] .mlv-edge__charge');
  assert.ok(off > 0, 'the flow toggle hides the charge too');
  assert.ok(/display:\s*none/.test(css.slice(off, css.indexOf('}', off))), 'with display:none');
});

test('the pulse underlay no longer animates a dash (F1-A12)', async () => {
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const at = css.indexOf('.mlv-edge.is-flowing--pulse .mlv-edge__flow');
  assert.ok(at > 0, 'the pulse underlay still has a rule');
  const rule = css.slice(at, css.indexOf('}', at)).replace(/\s+/g, ' ');
  assert.equal(rule.indexOf('animation'), -1, 'the moving part is the dot now: ' + rule);
  assert.ok(rule.indexOf('stroke-dasharray: none') >= 0, 'and the cable is a continuous wash: ' + rule);
  assert.ok(rule.indexOf('stroke-opacity: var(--mlv-flow-underlay-opacity') >= 0, rule);
});

/* ── the lineage STREAM is deliberately unchanged ─────────────────────── */

test('a lineage stream still runs the dash train, not dots', async () => {
  // The user's request was about the single hovered connection. A stream may
  // decorate up to FLOW.MAX_EDGES cables at once, where one SMIL timeline per
  // edge buys nothing the dash pattern does not already say better: on a stream
  // the reading is DENSITY per hop, which a dash pattern states in one glance.
  const ctx = await app();
  const card = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"]');
  const target = card.querySelector('.mlv-group__header') || card;
  enter(ctx, target);
  await sleep(HOVER_OPEN_MS + 120);
  const streaming = Array.from(ctx.document.querySelectorAll('.mlv-edge.is-flowing'));
  assert.ok(streaming.length >= 8, 'the lineage streams: ' + streaming.length);
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__charge').length, 0, 'and no dot was built for it');
  for (const g of streaming) assert.ok(g.querySelector('.mlv-edge__flow'), 'every streaming edge keeps its dash path');
});

/* ── R3-CHG-01: the charge starts at the OUTLET, on this gesture ───────── */

/**
 * The SVG document timeline is not the element's timeline. `<animateMotion>`
 * with no `begin` resolves to `0s` on the OWNING SVG's clock — a clock that has
 * been running since the page loaded and is never stopped — so a dot created
 * inside a hover callback forty seconds in starts at phase
 * `(40000 mod dur) / dur`. Measured over twelve hovers of one 1269 ms cable the
 * first painted position was scattered across the whole route (0.05 … 0.99) and
 * never near the outlet, so roughly one hover in four spent its entire visible
 * life beside the INLET.
 *
 * jsdom implements no SMIL clock, which is exactly why `getCurrentTime` is read
 * through a guard and why the test supplies one: the assertion is that the
 * begin is ANCHORED to whatever the clock said at build time.
 */
function withClock(ctx, id, seconds) {
  const g = edgeEl(ctx, id);
  const owner = g.ownerSVGElement || g.closest('svg');
  assert.ok(owner, 'the edge lives in an <svg>');
  owner.getCurrentTime = () => seconds;
  return g;
}

test('the charge begins at the GESTURE, not wherever the page clock stands (R3-CHG-01)', async () => {
  const ctx = await app();
  withClock(ctx, ISSUE_EDGE, 41.25);
  const { g } = await hoverEdge(ctx, ISSUE_EDGE);
  const motion = g.querySelector('.mlv-edge__charge animateMotion');
  assert.equal(motion.getAttribute('begin'), '41.25s', 'an ABSOLUTE begin on the SVG timeline: now, at the outlet');
});

test('a second hover is anchored to the second gesture (R3-CHG-01)', async () => {
  const ctx = await app();
  const g = withClock(ctx, ISSUE_EDGE, 3);
  const hit = g.querySelector('.mlv-edge__hit');
  enter(ctx, hit);
  await sleep(HOVER_OPEN_MS + 80);
  assert.equal(g.querySelector('animateMotion').getAttribute('begin'), '3s');

  leave(ctx, hit);
  await sleep(HOVER_CLOSE_MS + 120);
  assert.equal(g.querySelector('.mlv-edge__charge'), null, 'the first charge is gone');

  const owner = g.ownerSVGElement || g.closest('svg');
  owner.getCurrentTime = () => 17.5;
  enter(ctx, hit);
  await sleep(HOVER_OPEN_MS + 80);
  assert.equal(
    g.querySelector('animateMotion').getAttribute('begin'),
    '17.5s',
    'the phase follows the pointer, not the page — this is the whole fix',
  );
});

test('the twin keeps its half-period lead against the same clock reading (R3-CHG-01)', async () => {
  const ctx = await app();
  withClock(ctx, LONG_EDGE, 10);
  const { g } = await hoverEdge(ctx, LONG_EDGE);
  const { dur } = expectedDur(ctx, LONG_EDGE);
  const charges = g.querySelectorAll('.mlv-edge__charge');
  assert.equal(charges.length, 2, 'a long cable still runs two dots');
  const begins = Array.from(charges).map((c) => c.querySelector('animateMotion').getAttribute('begin'));
  const half = Math.round(dur / 2) / 1000;
  assert.deepEqual(begins, ['10s', 10 - half + 's'], 'the twin is anchored half a period IN THE PAST');
  assert.ok(charges[1].classList.contains('mlv-edge__charge--twin'), 'and is marked, so its fade shifts with it');
  assert.equal(charges[0].classList.contains('mlv-edge__charge--twin'), false);
});

test('a renderer with no SMIL clock keeps the original relative begin (R3-CHG-01)', async () => {
  // jsdom has no `getCurrentTime`, and neither may some SVG 1.1 renderer: the
  // fallback is the pre-fix form, never a thrown build.
  const ctx = await app();
  const { g } = await hoverEdge(ctx, LONG_EDGE);
  const { dur } = expectedDur(ctx, LONG_EDGE);
  const begins = Array.from(g.querySelectorAll('.mlv-edge__charge animateMotion')).map((m) => m.getAttribute('begin'));
  assert.deepEqual(begins, [null, '-' + Math.round(dur / 2) + 'ms']);
});

/* ── R3-CHG-03 / R3-CHG-05: the cycle ends, and the ink theme ──────────── */

test('the dot fades in at the outlet and out at the inlet (R3-CHG-03)', async () => {
  // `repeatCount="indefinite"` wraps instantaneously, so with a fixed opacity
  // the charge blinked out at the inlet and in at the outlet one frame later, at
  // full strength: a ~190 px jump on a short cable, ~640 px on a long one, once
  // per cycle for as long as the pointer rested.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const frames = css.slice(css.indexOf('@keyframes mlv-charge-ends'));
  assert.ok(frames.indexOf('@keyframes mlv-charge-ends') === 0, 'the fade keyframe exists');
  const body = frames.slice(0, frames.indexOf('}\n}') + 3).replace(/\s+/g, ' ');
  assert.match(body, /0% \{ opacity: 0/, 'it starts invisible: ' + body);
  assert.match(body, /100% \{ opacity: 0/, 'and ends invisible: ' + body);
  assert.equal(body.indexOf('filter'), -1, 'no filter primitive joined the moving element');

  const ruleAt = (sel) => {
    const at = css.indexOf(sel + ' {');
    assert.ok(at > 0, sel + ' has no rule');
    return css.slice(at, css.indexOf('}', at)).replace(/\s+/g, ' ');
  };
  const charge = ruleAt('.mlv-edge__charge');
  assert.ok(charge.indexOf('animation: mlv-charge-ends var(--mlv-flow-dur') >= 0, charge);
  const twin = ruleAt('.mlv-edge__charge--twin');
  assert.ok(twin.indexOf('animation-delay: calc(var(--mlv-flow-dur') >= 0, twin);
  assert.ok(twin.indexOf('/ -2') >= 0, 'shifted by the same half period the motion is: ' + twin);
  // And nothing new runs under `reduce`: the dot is still removed outright.
  const reduceBlocks = css.split('@media (prefers-reduced-motion: reduce)').slice(1);
  assert.ok(
    reduceBlocks.some((block) => block.slice(0, 900).indexOf('.mlv-edge__charge {') >= 0),
    'the reduce block still removes the charge outright — the fade must not become its substitute',
  );
});

test('high contrast rings the dot in ink instead of an invisible halo (R3-CHG-05)', async () => {
  // In hc `--mlv-flow-color` is `--mlv-text`, so the halo was the same white as
  // the cable it rode: the "hue around the dot" the feature is about, delivered
  // as white on white. HC has ruled hue out, so the ring comes back as geometry.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const at = css.indexOf('[data-theme="hc"] .mlv-edge__charge-halo');
  assert.ok(at > 0, 'no high-contrast rule for the halo');
  const rule = css.slice(css.lastIndexOf('}', at) + 1, css.indexOf('}', at)).replace(/\s+/g, ' ');
  assert.ok(rule.indexOf('body.vscode-high-contrast .mlv-edge__charge-halo') >= 0, 'the VS Code hc bodies too: ' + rule);
  assert.ok(rule.indexOf('fill: none') >= 0, rule);
  assert.ok(rule.indexOf('stroke: var(--mlv-text)') >= 0, 'an ink outline, on both hc grounds: ' + rule);
  // The base rule is still the hue one — order must not decide this, specificity does.
  const base = css.slice(css.indexOf('.mlv-edge__charge-halo {'));
  assert.ok(base.slice(0, base.indexOf('}')).indexOf('fill: var(--mlv-flow-color') >= 0, 'the themed default is untouched');
});
