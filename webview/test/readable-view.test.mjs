// Viewer M2, roadmap step 6: a readable first view and readable compact titles.
//
// readablePlan() is pure, so its cases run against render/canvas.ts itself, compiled here with
// the esbuild the build already uses; the integration cases run on the built bundle like every
// other test. The compact-title sizing is checked from the shipped stylesheet's own numbers
// against the card heights layout/cardmetrics.ts reserves. jsdom lays nothing out, so none of
// this measures pixels on screen (the screenshot harness does); it pins the plan and the rules.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { build } from 'esbuild';
import { WEBVIEW_ROOT, VIT_SHAPE, YOLO_SHAPE, loadBundle, recordingBridge, rendererRegressionWorkflow, shapedWorkflow } from './helpers.mjs';

let sourcePromise = null;
/** render/canvas.ts and layout/cardmetrics.ts as one ES module (no DOM is touched on import). */
function source() {
  if (!sourcePromise) {
    sourcePromise = build({
      stdin: {
        contents: "export * from './render/canvas.ts'; export { cardHeight } from './layout/cardmetrics.ts';",
        resolveDir: join(WEBVIEW_ROOT, 'src'),
        loader: 'ts',
        sourcefile: 'readable-view-entry.ts',
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

const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9, `${message}: ${actual} vs ${expected}`);

/* ── readablePlan, pure ──────────────────────────────────────────────── */

/** A frame with phase lanes stacked from y=32, each `laneW` x `laneH`, after a left channel. */
function frame({ width, height, laneW = 600, laneH = 400, lanes = 3, channelW = 0 }) {
  const x = 32 + channelW;
  return { width, height, channelW, lanes: Array.from({ length: lanes }, (_, i) => ({ x, y: 32 + i * (laneH + 40), w: laneW, h: laneH })) };
}

test('readablePlan opens the whole document, centred, when it fits at READABLE_MIN_ZOOM (0.75) or more', async () => {
  const { readablePlan, READABLE_MIN_ZOOM, READABLE_ZOOM, LOD_FULL_ZOOM, MAX_FIT_ZOOM } = await source();
  assert.equal(READABLE_MIN_ZOOM, 0.75, 'a 13 px card title is 9.75 px on screen');
  assert.equal(LOD_FULL_ZOOM, 0.62, 'the level of detail is not part of this change');
  const small = readablePlan(frame({ width: 600, height: 400, lanes: 1, laneH: 336 }), 1200, 800);
  assert.equal(small.mode, 'whole');
  assert.equal(small.zoom, MAX_FIT_ZOOM, 'a small document is not blown up past 1.2');
  near(small.x, (1200 - 600 * 1.2) / 2, 'centred across');
  near(small.y, (800 - 400 * 1.2) / 2, 'and down');
  // Exactly at the bound it is still the whole document.
  const edge = readablePlan(frame({ width: 500, height: (800 - 48) / READABLE_MIN_ZOOM }), 1200, 800);
  assert.equal(edge.mode, 'whole');
  near(edge.zoom, READABLE_MIN_ZOOM, 'whole fit at 0.75');
  // Viewer M4 (A11Y-7, deliberate): a whole fit under 0.75 opens phase 1 at 0.9. Under M2 the whole
  // document opened down to LOD_FULL_ZOOM (0.62, 8.1 px titles); this frame was the M2 edge case.
  const m2edge = readablePlan(frame({ width: 500, height: (800 - 48) / LOD_FULL_ZOOM }), 1200, 800);
  assert.equal(m2edge.mode, 'phase-fit');
  assert.equal(m2edge.zoom, READABLE_ZOOM);
  const under = readablePlan(frame({ width: 500, height: (800 - 48) / 0.749 }), 1200, 800);
  assert.notEqual(under.mode, 'whole');
  assert.equal(under.zoom, READABLE_ZOOM);
});

test('readablePlan otherwise opens phase 1 at READABLE_ZOOM, anchored top-left with the left channel', async () => {
  const { readablePlan, READABLE_ZOOM } = await source();
  // The owner's beside-the-code canvas (541x480) and a wide, deep document: phase 1 would fit at
  // 0.21 there, far under 0.75, so it opens at 0.9 and is read by panning.
  const doc = frame({ width: 2400, height: 3000, laneW: 2200, laneH: 600, channelW: 98 });
  const plan = readablePlan(doc, 541, 480);
  assert.equal(plan.mode, 'phase-anchor');
  assert.equal(plan.zoom, READABLE_ZOOM);
  // The anchor is the channel's left edge (lane.x - channelW = 32), not the lane's.
  near(plan.x, 24 - 32 * 0.9, 'the left channel lands at the padding');
  near(plan.y, 24 - 32 * 0.9, 'phase 1 lands at the top');
  const without = readablePlan({ ...doc, channelW: 0 }, 541, 480);
  near(without.x, 24 - 130 * 0.9, 'with no channel the lane itself is the anchor');
});

test('readablePlan opens phase 1 at READABLE_ZOOM, never fitted under it (viewer M4)', async () => {
  const { readablePlan, READABLE_ZOOM } = await source();
  // Viewer M4 (A11Y-7, deliberate): M2 fitted phase 1 whole when that zoom was 0.75 to 0.9, so a
  // panel just wide enough for that painted smaller titles than a narrower one at 0.9 (vit-cc opened
  // at 81% at 786 px, at 90% at 700 and 900 px). Phase 1 now always opens at 0.9: here it is 1440
  // wide in a 1200 canvas, (1200 - 48) / 1440 = 0.8, and opens at 0.9 anchored at its left edge.
  const wide = readablePlan(frame({ width: 1600, height: 4000, laneW: 1440, laneH: 500 }), 1200, 800);
  assert.equal(wide.mode, 'phase-anchor', 'phase 1 is wider than the canvas at 0.9');
  assert.equal(wide.zoom, READABLE_ZOOM);
  near(wide.x, 24 - 32 * 0.9, 'anchored at its left edge');
  // Phase 1 that fits at 0.9 or more is wholly in view at 0.9, never blown up; a document narrower
  // than the canvas is centred.
  const small = readablePlan(frame({ width: 700, height: 4000, laneW: 600, laneH: 300 }), 1200, 800);
  assert.equal(small.mode, 'phase-fit');
  assert.equal(small.zoom, READABLE_ZOOM);
  near(small.x, (1200 - 700 * 0.9) / 2, 'centred across');
  near(small.y, 24 - 32 * 0.9, 'phase 1 at the top');
  // Exactly at 0.9 it is wholly in view; just under, it is read by panning, at the same zoom.
  const at = readablePlan(frame({ width: 1600, height: 4000, laneW: 1152 / READABLE_ZOOM, laneH: 500 }), 1200, 800);
  assert.equal(at.mode, 'phase-fit');
  const under = readablePlan(frame({ width: 1600, height: 4000, laneW: 1152 / 0.899, laneH: 500 }), 1200, 800);
  assert.equal(under.mode, 'phase-anchor');
  assert.deepEqual([at.zoom, under.zoom], [READABLE_ZOOM, READABLE_ZOOM]);
});

test('readablePlan with no lane fits the whole document when it reads at 0.75, else anchors its top-left at 0.9', async () => {
  const { readablePlan, fitPlan, READABLE_ZOOM } = await source();
  const fits = readablePlan({ width: 600, height: 400, lanes: [] }, 900, 700);
  assert.equal(fits.mode, 'whole');
  assert.equal(fits.zoom, fitPlan(600, 400, 900, 700).zoom);
  // Viewer M4 (deliberate): only an empty frame has no lane (every drawn step gets one), but the
  // first view keeps its 9.75 px floor there too. Under M2 this opened whole at 0.22.
  const plan = readablePlan({ width: 3000, height: 3000, lanes: [] }, 900, 700);
  assert.equal(plan.mode, 'phase-anchor');
  assert.equal(plan.zoom, READABLE_ZOOM);
  near(plan.x, 24, 'the document\'s left edge at the padding');
  near(plan.y, 24, 'and its top');
});

/* ── viewer M4 (A11Y-7): first-paint title size across widths and shapes ── */

/**
 * The canvas the viewer gets in a panel W x H at first paint, as the screenshot harness measured it
 * on the M4 build: below 1260 px the rail is a collapsed bottom sheet (header 36 + status 22 + the
 * sheet's tab row 32 px); from 1260 px it docks (360 px wide), leaving header and status bar.
 */
const canvasIn = (W, H) => (W - 360 >= 900 ? { w: W - 360, h: H - 58, docked: true } : { w: W, h: H - 90, docked: false });
const WIDTHS = [320, 541, 700, 786, 900, 1100, 1382, 1440, 1920];

/**
 * Synthetic frames with the sizes the layout gave the three public shakedown documents of the M2
 * and M3 live checks (sizes only, no content), and small and medium documents.
 */
const SIZED = {
  'vit-cc size': { width: 2132, height: 2481, channelW: 112, lanes: [[144, 32, 804, 316], [144, 388, 1956, 537], [144, 965, 1076, 366], [144, 1371, 560, 316], [144, 1727, 1124, 366], [144, 2133, 320, 316]] },
  'dino-copilot size': { width: 1400, height: 1098, channelW: 0, lanes: [[32, 32, 1200, 280], [32, 352, 1336, 394], [32, 786, 560, 280]] },
  'yolov5-cc2 size': { width: 2184, height: 5017, channelW: 56, lanes: [[88, 32, 1168, 307], [88, 379, 1996, 3094], [88, 3513, 2064, 1248], [88, 4801, 1136, 184]] },
  'small, one phase': { width: 1000, height: 500, channelW: 0, lanes: [[32, 32, 936, 436]] },
  'medium, two phases': { width: 1300, height: 700, channelW: 56, lanes: [[88, 32, 1180, 300], [88, 360, 900, 300]] },
};
const sized = (spec) => ({ width: spec.width, height: spec.height, channelW: spec.channelW, lanes: spec.lanes.map(([x, y, w, h]) => ({ x, y, w, h })) });

/** The frames: the sized ones above and the viewer's own layout of the synthetic test shapes. */
async function shapes() {
  const out = Object.fromEntries(Object.entries(SIZED).map(([name, spec]) => [name, sized(spec)]));
  for (const [name, document] of [['VIT_SHAPE', shapedWorkflow(VIT_SHAPE)], ['YOLO_SHAPE', shapedWorkflow(YOLO_SHAPE)], ['regression fixture', rendererRegressionWorkflow(48)]]) {
    const ctx = await mount(document);
    const f = ctx.app.view.frameData;
    out[name] = { width: f.width, height: f.height, channelW: f.channelW || 0, lanes: f.lanes.map((l) => ({ x: l.x, y: l.y, w: l.w, h: l.h })) };
    ctx.app.destroy();
  }
  return out;
}

/** A smaller zoom for a larger canvas is allowed only where it shows the whole document instead of phase 1, at 0.75 or more. */
const allowedDrop = (from, to, min) => from.mode !== 'whole' && to.mode === 'whole' && to.zoom >= min - 1e-9;

test('A11Y-7: the first view paints titles at 9.75 px or more, and a larger canvas never paints them smaller', async () => {
  const { readablePlan, READABLE_MIN_ZOOM, READABLE_ZOOM, LOD_FULL_ZOOM } = await source();
  const frames = await shapes();
  const titlePx = (zoom) => 13 * zoom;
  const failures = [];
  for (const [name, f] of Object.entries(frames)) {
    for (let h = 200; h <= 1400; h += 25) {
      let prev = null;
      for (let w = 200; w <= 2600; w += 4) {
        const plan = readablePlan(f, w, h);
        if (plan.zoom < READABLE_MIN_ZOOM - 1e-9) failures.push(`${name} ${w}x${h}: ${titlePx(plan.zoom).toFixed(2)} px titles`);
        if (plan.zoom < LOD_FULL_ZOOM) failures.push(`${name} ${w}x${h}: opens at the compact level`);
        if (plan.mode !== 'whole' && plan.zoom !== READABLE_ZOOM) failures.push(`${name} ${w}x${h}: phase 1 at ${plan.zoom}`);
        if (prev && plan.zoom < prev.zoom - 1e-9 && !allowedDrop(prev, plan, READABLE_MIN_ZOOM)) failures.push(`${name} at ${h} px tall, ${w - 4} -> ${w} px wide: ${prev.zoom.toFixed(3)} (${prev.mode}) -> ${plan.zoom.toFixed(3)} (${plan.mode})`);
        prev = plan;
      }
    }
    for (let w = 200; w <= 2600; w += 50) {
      let prev = null;
      for (let h = 200; h <= 1600; h += 4) {
        const plan = readablePlan(f, w, h);
        if (prev && plan.zoom < prev.zoom - 1e-9 && !allowedDrop(prev, plan, READABLE_MIN_ZOOM)) failures.push(`${name} at ${w} px wide, ${h - 4} -> ${h} px tall: ${prev.zoom.toFixed(3)} -> ${plan.zoom.toFixed(3)}`);
        prev = plan;
      }
    }
  }
  assert.deepEqual(failures.slice(0, 12), [], `${failures.length} failures`);
});

test('A11Y-7: panel widths 320 to 1920 px, by panel; only the rail docking at 1260 px can shrink the canvas', async () => {
  const { readablePlan, READABLE_MIN_ZOOM, READABLE_ZOOM } = await source();
  const frames = await shapes();
  // The cases the live checks saw, now at 0.9 (11.7 px titles): dino-copilot opened whole at 69-72%
  // (9.0-9.4 px) from 1100 px, vit-cc at 81% (10.5 px) at 786 px and yolov5-cc2 at 80-86% from
  // 1100 px, each next to 90% in a narrower panel (the M2 plan, measured in the screenshot harness
  // at these panel sizes).
  const was = { 'dino-copilot size': [1100, 1382, 1440, 1920], 'vit-cc size': [786], 'yolov5-cc2 size': [1100, 1382, 1440] };
  for (const [name, widths] of Object.entries(was)) {
    for (const W of widths) {
      const c = canvasIn(W, 900);
      const plan = readablePlan(frames[name], c.w, c.h);
      assert.equal(plan.zoom, READABLE_ZOOM, `${name} in a ${W}x900 panel`);
      assert.notEqual(plan.mode, 'whole');
    }
  }
  for (const [name, f] of Object.entries(frames)) {
    for (const H of [600, 900, 1200]) {
      const zooms = WIDTHS.map((W) => { const c = canvasIn(W, H); return readablePlan(f, c.w, c.h); });
      zooms.forEach((plan, i) => assert.ok(plan.zoom >= READABLE_MIN_ZOOM, `${name} ${WIDTHS[i]}x${H}: ${plan.zoom}`));
      // Width by width, a wider panel never paints smaller titles except across the docking width,
      // where the canvas loses 360 px to the rail; even there the first view stays at 0.75 or more.
      let prev = null;
      for (let W = 200; W <= 2600; W += 2) {
        const c = canvasIn(W, H);
        const plan = readablePlan(f, c.w, c.h);
        if (prev && plan.zoom < prev.zoom - 1e-9 && !allowedDrop(prev, plan, READABLE_MIN_ZOOM)) {
          assert.equal(W, 1260, `${name} at ${H} px tall: ${W - 2} -> ${W} px wide drops ${prev.zoom.toFixed(3)} -> ${plan.zoom.toFixed(3)}`);
          assert.ok(plan.zoom >= READABLE_MIN_ZOOM);
        }
        prev = plan;
      }
    }
  }
  // The docking drop exists: a small document whole at 1.2 beside a collapsed sheet opens whole at
  // 0.85 once the rail docks (the canvas goes from 1258 to 900 px wide).
  const before = readablePlan(frames['small, one phase'], ...Object.values(canvasIn(1258, 900)).slice(0, 2));
  const after = readablePlan(frames['small, one phase'], ...Object.values(canvasIn(1260, 900)).slice(0, 2));
  assert.deepEqual([before.mode, before.zoom, after.mode, Math.round(after.zoom * 1000) / 1000], ['whole', 1.2, 'whole', 0.852]);
});

/* ── the viewer: first paint, key 0, the whole-document fit, a restored viewport ── */

async function mount(document, state) {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode', state ? { state } : {});
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), document, bridge);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const press = (key, opts = {}) => canvas.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...opts }));
  return { ...ctx, bridge, app, canvas, press };
}

const viewport = (ctx) => JSON.parse(JSON.stringify(ctx.app.getState().viewport));

/** jsdom measures nothing, so the viewer fits a 1200x800 canvas (ViewportController.size). */
async function expectedPlan(ctx, w = 1200, h = 800) {
  const { readablePlan } = await source();
  const plan = readablePlan(ctx.app.view.frameData, w, h);
  return { x: plan.x, y: plan.y, zoom: plan.zoom, mode: plan.mode };
}

test('the first paint is the readable plan, and key 0 returns to it from any zoom', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const plan = await expectedPlan(ctx);
  assert.equal(plan.mode, 'phase-fit', 'phase 1 (646x390) fits a 1200x800 canvas, capped at 0.9');
  assert.deepEqual(viewport(ctx), { x: plan.x, y: plan.y, zoom: plan.zoom });
  ctx.app.view.viewport.set({ x: -900, y: -1200, zoom: 0.2 });
  ctx.press('0');
  assert.deepEqual(viewport(ctx), { x: plan.x, y: plan.y, zoom: plan.zoom }, 'from 20 %');
  ctx.app.view.viewport.set({ x: 50, y: 60, zoom: 2 });
  ctx.press('0');
  assert.deepEqual(viewport(ctx), { x: plan.x, y: plan.y, zoom: plan.zoom }, 'from 200 %');
  // Viewer M3 step 13 (deliberate): Shift+0 is the phase overview, an overlay; the diagram under
  // it does not move (it used to fold every group and fit the whole document).
  ctx.press('0', { shiftKey: true });
  assert.equal(ctx.app.view.overviewOpen, true, 'Shift+0 opens the phase overview');
  assert.deepEqual(viewport(ctx), { x: plan.x, y: plan.y, zoom: plan.zoom }, 'and leaves the diagram where it was');
  ctx.app.destroy();
});

test('a document that fits at full detail opens whole', async () => {
  const document = rendererRegressionWorkflow(16);
  document.nodes = document.nodes.filter((n) => n.phase === 'phase-0' || n.phase === 'phase-1').map((n) => ({ ...n, parent: undefined, kind: 'operation' }));
  const ids = new Set(document.nodes.map((n) => n.id));
  document.edges = document.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  document.findings = [];
  document.phases = document.phases.slice(0, 2);
  const ctx = await mount(document);
  const plan = await expectedPlan(ctx);
  assert.equal(plan.mode, 'whole');
  assert.deepEqual(viewport(ctx), { x: plan.x, y: plan.y, zoom: plan.zoom });
  ctx.app.destroy();
});

test('"Fit the whole diagram" fits the whole document with its groups as they are', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const { fitPlan } = await source();
  const collapsed = ctx.app.getState().collapsed.slice();
  // Viewer M2: the fit lives in the header's ... menu.
  ctx.document.querySelector('.mlv-btn--more').click();
  ctx.document.querySelector('[data-more-item="fit"]').click();
  const f = ctx.app.view.frameData;
  const zoom = fitPlan(f.width, f.height, 1200, 800).zoom;
  assert.deepEqual(viewport(ctx), { x: (1200 - f.width * zoom) / 2, y: Math.max(24, (800 - f.height * zoom) / 2), zoom });
  assert.deepEqual(ctx.app.getState().collapsed, collapsed, 'no group is folded');
  ctx.app.destroy();
});

test('a viewport saved for the same revision wins over the readable plan; another revision gets the plan', async () => {
  const saved = { x: -321, y: -54, zoom: 0.33 };
  const same = await mount(rendererRegressionWorkflow(48), { viewport: saved, workflowRevision: 'fixture-r1' });
  assert.deepEqual(viewport(same), saved);
  // A re-post of the same revision keeps where the reader is, too.
  same.app.view.viewport.set({ x: 10, y: 20, zoom: 1.5 });
  same.app.setWorkflow(rendererRegressionWorkflow(48));
  assert.deepEqual(viewport(same), { x: 10, y: 20, zoom: 1.5 });
  same.app.destroy();
  const other = await mount(rendererRegressionWorkflow(48), { viewport: saved, workflowRevision: 'fixture-r0' });
  const plan = await expectedPlan(other);
  assert.deepEqual(viewport(other), { x: plan.x, y: plan.y, zoom: plan.zoom });
  other.app.destroy();
});

test('the shortcut sheet names key 0 the readable view', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  ctx.press('?');
  const describe = (key) => {
    const dt = [...ctx.document.querySelectorAll('.mlv-sheet__keys')].find((d) => [...d.querySelectorAll('kbd')].map((k) => k.textContent).join(' ') === key);
    return dt && dt.nextElementSibling ? dt.nextElementSibling.textContent : null;
  };
  assert.match(describe('0'), /^Readable view: the whole diagram if it fits at reading size, otherwise phase 1/);
  // Viewer M3 step 13 (deliberate): Shift+0 is the phase overview.
  assert.match(describe('Shift+0'), /^Phase overview: every phase as a block of its step titles/);
  ctx.app.destroy();
});

/* ── compact titles: readable, inside their card, no relayout ───────── */

/** The built stylesheet as rules, with each rule's @media (empty at the top level). */
function cssRules(css) {
  const out = [];
  const walk = (text, media) => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf('{', i);
      if (open < 0) break;
      const prelude = text.slice(i, open).trim();
      let depth = 1;
      let j = open + 1;
      while (j < text.length && depth) {
        if (text[j] === '{') depth++;
        else if (text[j] === '}') depth--;
        j++;
      }
      const body = text.slice(open + 1, j - 1);
      if (prelude.startsWith('@media')) walk(body, prelude.slice(6).trim());
      else if (!prelude.startsWith('@')) {
        const decls = {};
        for (const decl of body.split(';')) {
          const k = decl.indexOf(':');
          if (k > 0) decls[decl.slice(0, k).trim()] = decl.slice(k + 1).trim();
        }
        out.push({ media, selectors: prelude.split(',').map((s) => s.trim()), decls });
      }
      i = j;
    }
  };
  walk(css, '');
  return out;
}

async function stylesheet() {
  const rules = cssRules(await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8'));
  const merged = (selector, media) => Object.assign({}, ...rules.filter((r) => r.media === media && r.selectors.includes(selector)).map((r) => r.decls));
  return { screen: (selector) => merged(selector, ''), print: (selector) => merged(selector, 'print') };
}

const COMPACT = '.mlv-canvas[data-lod=compact]';

test('the compact level shows the title only, counter-scaled and capped by the card\'s own box', async () => {
  const { screen, print } = await stylesheet();
  for (const row of ['.mlv-node__sub', '.mlv-node__loc', '.mlv-node__chips', '.mlv-node__iconbox']) {
    assert.equal(screen(`${COMPACT} ${row}`).display, 'none', `${row} is hidden`);
  }
  const main = screen(`${COMPACT} .mlv-node__main`);
  assert.equal(main['container-type'], 'size', 'cqh units read the card\'s text box');
  const title = screen(`${COMPACT} .mlv-node__title`);
  assert.equal(title['font-size'], 'min(calc(var(--mlv-compact-title) / var(--mlv-z, 1)),calc(100cqh / 2.3))');
  assert.equal(title['line-height'], '1.15');
  assert.equal(screen(`${COMPACT} .mlv-node__title--wrap`)['-webkit-line-clamp'], '2');
  const three = screen(`${COMPACT} .mlv-node__title--wrap[data-lines="3"]`);
  assert.equal(three['-webkit-line-clamp'], '3');
  assert.equal(three['font-size'], 'min(calc(var(--mlv-compact-title) / var(--mlv-z, 1)),calc(100cqh / 3.45))');
  // The inferred / unresolved tag hangs from the card's bottom edge instead of covering the last line.
  const tag = screen(`${COMPACT} .mlv-node>.mlv-basis-tag`);
  assert.equal(tag['transform-origin'], '0 0');
  assert.match(tag.transform, /scale\(calc\(1 \/ var\(--mlv-z, 1\)\)\)/, 'still the same size on screen');
  // Print throws the zoom away and draws the full card.
  assert.equal(print(`${COMPACT} .mlv-node__title`)['font-size'], 'var(--mlv-fs-13)!important');
  assert.equal(print(`${COMPACT} .mlv-node__iconbox`).display, 'flex!important');
  for (const n of ['1', '2', '3']) {
    const selector = n === '1' ? `${COMPACT} .mlv-node__title--wrap` : `${COMPACT} .mlv-node__title--wrap[data-lines="${n}"]`;
    assert.equal(print(selector)['-webkit-line-clamp'], `${n}!important`, `print keeps ${n} reserved line(s)`);
  }
});

test('compact titles are 10 px or more on screen down to about 35 % and never overflow their card', async () => {
  const { screen } = await stylesheet();
  const { cardHeight, zoomBucket, ZOOM_BUCKETS, LOD_FULL_ZOOM, MIN_ZOOM } = await source();
  const target = parseFloat(screen(':root')['--mlv-compact-title']);
  assert.equal(target, 11.2);
  const lh = parseFloat(screen(`${COMPACT} .mlv-node__title`)['line-height']);
  const twoLines = Number(/100cqh \/ ([\d.]+)/.exec(screen(`${COMPACT} .mlv-node__title`)['font-size'])[1]);
  const threeLines = Number(/100cqh \/ ([\d.]+)/.exec(screen(`${COMPACT} .mlv-node__title--wrap[data-lines="3"]`)['font-size'])[1]);
  near(twoLines, 2 * lh, 'the two-line cap is two line boxes');
  near(threeLines, 3 * lh, 'the three-line cap is three');
  const padV = parseFloat(screen(`${COMPACT} .mlv-node__main`).padding.split(' ')[0]);
  const border = parseFloat(screen('.mlv-node').border);
  assert.deepEqual([padV, border], [2, 1]);

  // The cards layout/cardmetrics.ts reserves, by title lines, with and without a file:line row.
  const loc = { file: 'train.py', line: 1 };
  const label = (n) => ['Load the data', 'Build the optimizer from the config', 'Run the epoch loop with gradient clipping and AMP enabled'][n - 1];
  const cards = [
    { name: '1-line title, file:line', node: { id: 'a', label: label(1), kind: 'operation', loc }, lines: 2, floor: 0.35 },
    { name: '2-line title, file:line', node: { id: 'b', label: label(2), kind: 'operation', loc }, lines: 2, floor: 0.29 },
    { name: '3-line title, file:line', node: { id: 'c', label: label(3), kind: 'operation', loc }, lines: 3, floor: 0.34 },
    { name: '1-line title, no evidence', node: { id: 'd', label: label(1), kind: 'operation', loc: {} }, lines: 2, floor: 0.43 },
  ];
  const step = 0.0005;
  for (const card of cards) {
    const h = cardHeight(card.node, false);
    const room = h - 2 * border - 2 * padV;
    let lowest10 = LOD_FULL_ZOOM;
    for (let z = LOD_FULL_ZOOM - 1e-6; z >= MIN_ZOOM; z -= step) {
      const b = zoomBucket(z);
      assert.ok(ZOOM_BUCKETS.includes(b));
      const font = Math.min(target / b, room / (card.lines * lh));
      assert.ok(card.lines * lh * font <= room + 1e-9, `${card.name} at ${z.toFixed(3)}: ${card.lines} lines fit the ${room} px box`);
      const px = font * z;
      assert.ok(px <= target * 1.12, `${card.name} at ${z.toFixed(3)}: ${px.toFixed(2)} px, never far above the target`);
      if (px >= 10 && lowest10 - z < step * 1.5) lowest10 = z;
    }
    assert.ok(lowest10 <= card.floor, `${card.name} (${h} px card): 10 px or more down to ${lowest10.toFixed(3)}, expected ${card.floor} or lower`);
  }
  // Above the lowest bucket edge the bucket rounding alone keeps the counter-scale at 10 px or more.
  for (let z = 0.358; z < LOD_FULL_ZOOM; z += step) assert.ok((target / zoomBucket(z)) * z >= 10 - 1e-9, `${z.toFixed(3)}`);
});

test('a compact title changes size only when --mlv-z crosses a bucket, with no relayout', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const boxes = () => [...ctx.document.querySelectorAll('.mlv-node')].map((n) => n.style.cssText).join('|');
  const before = boxes();
  const z = () => ctx.canvas.style.getPropertyValue('--mlv-z');
  ctx.app.view.viewport.set({ zoom: 0.5 });
  assert.equal(ctx.canvas.getAttribute('data-lod'), 'compact');
  assert.equal(z(), '0.5');
  ctx.app.view.viewport.set({ zoom: 0.46 });
  assert.equal(z(), '0.5', 'inside a bucket nothing is restyled');
  ctx.app.view.viewport.set({ zoom: 0.43 });
  assert.equal(z(), '0.4');
  assert.equal(boxes(), before, 'the cards keep the boxes the layout reserved');
  for (const title of ctx.document.querySelectorAll('.mlv-node .mlv-node__title')) {
    assert.ok(['1', '2', '3'].includes(title.getAttribute('data-lines')), 'every card title carries the lines it reserved');
    assert.equal(title.style.fontSize, '', 'no per-card size is written');
  }
  ctx.app.destroy();
});
