/**
 * Hardening round 1, area hosts-ux — the five smaller defects fixed alongside
 * HOSTS-UX-CHIPWALL, each pinned by the measurement that found it.
 *
 *   DGRG-12                the answer card counted rows rendered, not questions
 *                          answered: "4 of 4 answered" over three rows that all
 *                          begin "No … was detected" (stable-baselines3).
 *   HOSTS-UX-FITZOOM       "Fit to view" is floored at 50 % and could zoom IN:
 *                          on the demo at 1280x800, five presses of Zoom out ->
 *                          20 % and 29 of 53 cards inside the canvas, then one
 *                          press of Fit -> 50 % and 10 of 53, with nothing said.
 *   HOSTS-UX-ANSWERSCROLL  the answer card clipped its last answer mid-sentence
 *                          at 1280x800 (258 px of 317) behind a macOS overlay
 *                          scrollbar, with no fade, ellipsis or "more" marker.
 *   HOSTS-UX-PIPELINECOUNT the scope picker promised N nodes and the projection
 *                          the click applies delivered N+1 (`vision_detector_bad`:
 *                          row `55 nodes`, breadcrumb `56 of 63 nodes`, and the
 *                          CLI's `view.counts` summing to 56).
 *   HOSTS-UX-STAGERESET    turning off the SEVENTH stage chip turned every
 *                          filter back on — off 6 -> 0, dimmed 45 -> 1, rail 0
 *                          -> 15 findings — with no toast and no announcement.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

async function app(graph = sample, host = 'standalone') {
  const ctx = await loadBundle();
  const bridge = {
    host,
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const click = (ctx, target) =>
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));

const text = (node) => (node ? node.textContent || '' : '').replace(/\s+/g, ' ').trim();

/* ── DGRG-12: the counter says what the answers say ────────────────────── */

/** An answer that names a place in the code, and one that names none. */
const LOCATED = {
  sentence: 'Data enters through load_data() and is split by train_test_split.',
  nodeIds: [],
  locs: [{ file: 'data.py', absFile: '/w/data.py', line: 26, col: 0, endLine: 26, endCol: 10 }],
  confidence: 0.9,
};
const NOT_DETECTED = {
  sentence: 'No loss function was detected: nothing in the objective stage and no backward() call.',
  nodeIds: [],
  locs: [],
  confidence: 0.0,
};

async function answers(block) {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.answers = block;
  const ctx = await app(graph);
  return { ctx, count: text(ctx.document.querySelector('.mlv-answers__count')) };
}

test('an answer that detected nothing is not counted as answered (DGRG-12)', async () => {
  // The stable-baselines3 shape: one real answer, three that found nothing.
  const { ctx, count } = await answers({
    dataEntry: NOT_DETECTED,
    objective: NOT_DETECTED,
    evaluation: NOT_DETECTED,
    verdict: LOCATED,
  });
  assert.equal(count, '1 of 4 answered · 3 not detected', count);
  assert.equal(ctx.document.querySelector('[data-answers]').getAttribute('data-answers-answered'), '1');
  const rows = Array.from(ctx.document.querySelectorAll('[data-answer]'));
  assert.equal(rows.filter((r) => r.getAttribute('data-answer-located') === '1').length, 1);
});

test('four real answers still read "4 of 4 answered", with no caveat (DGRG-12)', async () => {
  const { count } = await answers({
    dataEntry: LOCATED,
    objective: LOCATED,
    evaluation: LOCATED,
    verdict: LOCATED,
  });
  assert.equal(count, '4 of 4 answered', 'a good report must not grow a qualifier it has no evidence for');
});

test('a partial block counts against four, never against what it drew (DGRG-12)', async () => {
  const { count } = await answers({ objective: LOCATED, verdict: NOT_DETECTED });
  assert.equal(count, '1 of 4 answered · 1 not detected', count);
});

/* ── HOSTS-UX-FITZOOM: Fit never shows less ────────────────────────────── */

function transform(ctx) {
  const world = ctx.document.querySelector('.mlv-world');
  const m = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/.exec(world.style.transform);
  assert.ok(m, 'the world carries a transform: ' + world.style.transform);
  return {
    x: Number(m[1]),
    y: Number(m[2]),
    zoom: Number(m[3]),
    w: parseFloat(world.style.width),
    h: parseFloat(world.style.height),
  };
}

const fitButton = (ctx) =>
  Array.from(ctx.document.querySelectorAll('.mlv-btn')).find(
    (b) => (b.getAttribute('aria-label') || b.title || '').indexOf('Fit') >= 0,
  );

const zoomOutButton = (ctx) =>
  Array.from(ctx.document.querySelectorAll('.mlv-btn')).find(
    (b) => (b.getAttribute('aria-label') || b.title || '') === 'Zoom out',
  );

test('Fit from below the fit floor shows the WHOLE document, never less (HOSTS-UX-FITZOOM)', async () => {
  const ctx = await app();
  const W = 1280;
  const H = 800;
  ctx.canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H, x: 0, y: 0 });
  const { MIN_FIT_ZOOM } = ctx.MLView.__internal.viewport;

  const out = zoomOutButton(ctx);
  assert.ok(out, 'the toolbar offers Zoom out');
  for (let i = 0; i < 5; i += 1) click(ctx, out);
  const zoomed = transform(ctx);
  assert.ok(zoomed.zoom < MIN_FIT_ZOOM, 'the reader is below the fit floor: ' + zoomed.zoom);

  click(ctx, fitButton(ctx));
  const fitted = transform(ctx);
  // The defect was that Fit returned the top-anchored plan, which is FLOORED at
  // MIN_FIT_ZOOM: on the demo at 1280x800 that meant 50 % and 10 of 53 cards,
  // from a state that had 29 of them. Below the floor, Fit now means the whole
  // document — so nothing that was on screen can leave it.
  assert.ok(
    fitted.zoom < MIN_FIT_ZOOM,
    'Fit returned the floored top-anchored plan (' + fitted.zoom + '), which is where the cards went',
  );
  const { fitPlan } = ctx.MLView.__internal.viewport;
  assert.equal(
    fitted.zoom,
    fitPlan(fitted.w, fitted.h, W, H, 24, true).zoom,
    'and it is exactly the whole-document plan Overview already uses',
  );
  assert.ok(fitted.x >= -0.5 && fitted.y >= -0.5, 'the diagram starts inside the canvas: ' + fitted.x + ',' + fitted.y);
  assert.ok(fitted.x + fitted.w * fitted.zoom <= W + 0.5, 'clipped on the right');
  assert.ok(fitted.y + fitted.h * fitted.zoom <= H + 0.5, 'clipped below the fold');
  // The acceptance in the reader's words: every card that was drawn is drawn
  // inside the canvas now, which the old plan could not say at any zoom.
  const cards = Array.from(ctx.document.querySelectorAll('.mlv-node'));
  assert.ok(cards.length > 0, 'the demo draws cards');
  for (const card of cards) {
    const x = parseFloat(card.style.left) || 0;
    const y = parseFloat(card.style.top) || 0;
    const w = parseFloat(card.style.width) || 0;
    const h = parseFloat(card.style.height) || 0;
    assert.ok(
      fitted.x + (x + w) * fitted.zoom <= W + 0.5 && fitted.y + (y + h) * fitted.zoom <= H + 0.5,
      'a card is outside the canvas after Fit: ' + card.getAttribute('data-node-id'),
    );
  }
});

test('Fit from ABOVE the floor still returns the first-paint plan (VIEW-01 unchanged)', async () => {
  const ctx = await app();
  const first = transform(ctx);
  const { MIN_FIT_ZOOM } = ctx.MLView.__internal.viewport;
  assert.ok(first.zoom >= MIN_FIT_ZOOM, 'the sample opens above the floor: ' + first.zoom);
  click(ctx, zoomOutButton(ctx));
  const moved = transform(ctx);
  assert.ok(moved.zoom >= MIN_FIT_ZOOM, 'one press is still above the floor: ' + moved.zoom);
  click(ctx, fitButton(ctx));
  assert.equal(transform(ctx).zoom, first.zoom, 'the deliberate top-anchored first paint is untouched');
});

/* ── HOSTS-UX-ANSWERSCROLL: a panel that scrolls says so ───────────────── */

test('the answer card and the legend body carry a scroll cue (HOSTS-UX-ANSWERSCROLL)', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const rule = /\.mlv-answers,\s*\.mlv-legend__body \{([^}]*)\}/.exec(css);
  assert.ok(rule, 'both scrolling panels are cued by one rule');
  const body = rule[1];
  // The cue must be HONEST: the covering layers are `local`, so they travel
  // with the content and hide the shadow exactly at the end of the scroll —
  // a panel whose content fits shows nothing at all.
  assert.match(body, /background-attachment:\s*local,\s*local,\s*scroll,\s*scroll/, body);
  assert.match(body, /background-image:/, body);
  assert.match(body, /scrollbar-gutter:\s*stable/, 'a scrollbar never lands on top of a sentence');
});

test('the legend clips its rounded corners now that its body paints (HOSTS-UX-ANSWERSCROLL)', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const rule = /\n\.mlv-legend \{([^}]*)\}/.exec(css);
  assert.ok(rule, 'the legend panel has a rule');
  assert.match(rule[1], /border-radius:/);
  assert.match(rule[1], /overflow:\s*hidden/, 'else the body’s square corners sit over the panel’s rounded ones');
});

/* ── HOSTS-UX-PIPELINECOUNT: the row promises what the click delivers ──── */

function multi(entrypoints = ['train.py', 'data.py', 'sklearn_baseline.py']) {
  const g = JSON.parse(JSON.stringify(sample));
  g.workspace = { ...g.workspace, entrypoints };
  return g;
}

test('every pipeline row quotes the count its own click delivers (HOSTS-UX-PIPELINECOUNT)', async () => {
  const graph = multi();
  const ctx = await app(graph);
  const { scope, pipelines } = ctx.MLView.__internal;
  ctx.app.setScope(null);
  click(ctx, ctx.document.querySelector('.mlv-btn--scope'));
  const rows = Array.from(ctx.document.querySelectorAll('.mlv-scopepicker [data-pipeline]'));
  assert.ok(rows.length >= 2, 'the picker lists the pipelines: ' + rows.length);
  for (const row of rows) {
    const entry = row.getAttribute('data-pipeline');
    const drawn = scope.project(graph, scope.parseScope('pipeline:' + entry)).nodes.length;
    assert.equal(
      Number(row.getAttribute('data-pipeline-nodes')),
      drawn,
      entry + ': the row promises ' + row.getAttribute('data-pipeline-nodes') + ' and project() draws ' + drawn,
    );
    assert.ok(
      text(row).indexOf(drawn + (drawn === 1 ? ' node' : ' nodes')) >= 0,
      entry + ': the row READS ' + JSON.stringify(text(row)) + ' against ' + drawn + ' drawn',
    );
  }
  // The relation itself is untouched: `nodeCount` is still |reach(E)|.
  for (const row of pipelines.rows(graph)) {
    assert.equal(row.exclusiveCount + row.sharedCount, row.nodeCount, row.entrypoint + ': 11.47 A still holds');
  }
});

test('the chooser and its accessible name use the same number (HOSTS-UX-PIPELINECOUNT)', async () => {
  const graph = multi();
  const ctx = await app(graph);
  const { scope, pipelines } = ctx.MLView.__internal;
  const panel = ctx.document.querySelector('.mlv-pipechooser');
  assert.ok(panel && !panel.hidden, 'a multi-pipeline report opens on the chooser');
  for (const row of Array.from(panel.querySelectorAll('[data-pipeline]'))) {
    const entry = row.getAttribute('data-pipeline');
    const drawn = scope.project(graph, scope.parseScope('pipeline:' + entry)).nodes.length;
    assert.ok(text(row).indexOf(String(drawn)) >= 0, entry + ' row: ' + text(row) + ' vs ' + drawn);
    assert.ok(
      (row.getAttribute('aria-label') || '').indexOf(drawn + (drawn === 1 ? ' node' : ' nodes')) >= 0,
      entry + ' aria-label: ' + row.getAttribute('aria-label'),
    );
  }
  // `drawnCount` falls back to the relation when nobody projected the row, so a
  // hand-built row is still drawable.
  const bare = { entrypoint: 'x.py', nodeCount: 7, exclusiveCount: 7, sharedCount: 0, issueCounts: { low: 0, medium: 0, high: 0 } };
  assert.ok(pipelines.rowLabel(bare).indexOf('7 nodes') >= 0, pipelines.rowLabel(bare));
});

/* ── HOSTS-UX-STAGERESET: the reset is explained, not observed ─────────── */

const stageChips = (ctx) => Array.from(ctx.document.querySelectorAll('[data-stage-filter]'));

test('turning off the LAST stage chip says that everything came back (HOSTS-UX-STAGERESET)', async () => {
  const ctx = await app();
  const chips = stageChips(ctx);
  assert.ok(chips.length >= 2, 'the demo draws several stage chips: ' + chips.length);
  const ids = chips.map((c) => c.getAttribute('data-stage-filter'));
  for (const id of ids.slice(0, -1)) {
    click(ctx, ctx.document.querySelector('[data-stage-filter="' + id + '"]'));
  }
  const off = stageChips(ctx).filter((c) => c.getAttribute('aria-pressed') === 'false').length;
  assert.equal(off, ids.length - 1, 'all but one lane are off');
  const live = ctx.document.querySelector('[aria-live="polite"]');

  click(ctx, ctx.document.querySelector('[data-stage-filter="' + ids[ids.length - 1] + '"]'));
  assert.equal(
    stageChips(ctx).filter((c) => c.getAttribute('aria-pressed') === 'false').length,
    0,
    'the model still resets — an empty selection is the only resting state it has',
  );
  assert.match(text(live), /every stage is shown again/i, 'and the reset is announced: ' + text(live));
  const toast = ctx.document.querySelector('.mlv-toast');
  assert.ok(toast, 'and shown');
  assert.match(text(toast), /showing everything again/i, text(toast));
});

test('turning a stage chip back ON the ordinary way announces nothing (HOSTS-UX-STAGERESET)', async () => {
  const ctx = await app();
  const ids = stageChips(ctx).map((c) => c.getAttribute('data-stage-filter'));
  // One off, then the same one on again: that reaches "everything" through the
  // other branch, which is the one a reader's gesture already describes.
  click(ctx, ctx.document.querySelector('[data-stage-filter="' + ids[0] + '"]'));
  click(ctx, ctx.document.querySelector('[data-stage-filter="' + ids[0] + '"]'));
  assert.equal(
    stageChips(ctx).filter((c) => c.getAttribute('aria-pressed') === 'false').length,
    0,
    'every chip is on again',
  );
  assert.equal(ctx.document.querySelector('.mlv-toast'), null, 'and nothing was explained that needed no explaining');
});
