/**
 * Hardening round 2, area hosts-ux — three defects found by driving the built
 * report in Chromium over 90 real analyzer documents, each pinned here at the
 * level jsdom can actually decide.
 *
 *   HOSTS-UX-LEGENDPAN    `app.ts` appends the legend INTO `shell.canvas`, but
 *                         the canvas pan guard in `ui/shell.ts` names only
 *                         `.mlv-node, .mlv-group__header, .mlv-minimap,
 *                         .mlv-zoom, .mlv-edge__hit`. So a pointerdown anywhere
 *                         on the legend starts a canvas drag-pan and takes
 *                         pointer capture. MEASURED in Chromium on
 *                         `samples/vision_pipeline`: `pointerdown` lands on the
 *                         legend's close icon, `mouseup` and `click` retarget to
 *                         `.mlv-canvas`, so the ✕ never fires; a 160x100 drag
 *                         inside the legend body pans the world from
 *                         translate(158.7, 24) to translate(-1.3, 124) and
 *                         selects the whole diagram's text; and the wheel zooms
 *                         0.543 -> 0.402 instead of scrolling the panel, which
 *                         leaves 329 px of a 846 px legend (clientHeight 517)
 *                         unreachable with a mouse.
 *
 *   HOSTS-UX-ANSWERWRAP   `.mlv-answers__sentence` and `.mlv-answers__cites`
 *                         declare no wrapping, and a workspace-relative path is
 *                         one unbreakable token. MEASURED at 1600x1000 on
 *                         DeepLearningExamples: the "How is it evaluated?"
 *                         sentence is scrollWidth 391 in a clientWidth 295
 *                         column and, being `overflow: visible`, is PAINTED OVER
 *                         the next answer — "…image_classification/training.py:205"
 *                         and "MLV803 (low) at" composite into
 *                         "…/tMLIVN803G.(low)205at", and the citation button
 *                         under it is illegible the same way. 7 of the 90
 *                         reports do it, at both viewports. The Inspector
 *                         already solves this (`.mlv-insp__fqn` is
 *                         `word-break: break-all`); the answer card was missed.
 *
 *   HOSTS-UX-ROWCOUNT     Round 1's HOSTS-UX-PIPELINECOUNT made the PIPELINE row
 *                         promise `drawnCount(row)` — "the number the CLICK
 *                         delivers, not the relation's". `unitRow()` and
 *                         `groupRow()` were not changed, so they still promise
 *                         the match set while the click applies the per-kind
 *                         default depth and keeps the context ancestors. On the
 *                         FROZEN GOLDEN, unedited: `unit:model.SmallNet` offers
 *                         "1 node" and delivers "5 of 12 nodes"; `unit:train.train`
 *                         offers 4 and delivers 9. On `analyzer/tests/clean` the
 *                         same gap opens at depth 0, where no depth is involved
 *                         at all: `stage:objective` offers 5 and delivers 10
 *                         (5 core + 5 context), `concern:config` 26 and 34.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

async function app(graph = sample) {
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
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const click = (ctx, target) =>
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));

/** jsdom has no PointerEvent; a MouseEvent of that type reaches the same listener. */
function pointerdown(ctx, target, pointerId = 1) {
  const ev = new ctx.window.MouseEvent('pointerdown', {
    bubbles: true,
    cancelable: true,
    clientX: 120,
    clientY: 120,
  });
  Object.defineProperty(ev, 'pointerId', { value: pointerId });
  target.dispatchEvent(ev);
  return ev;
}

/* ── HOSTS-UX-LEGENDPAN: the legend is not a place to grab the diagram ──── */

test('a pointerdown inside the legend does not start a canvas pan', async () => {
  const ctx = await app();
  const legendButton = ctx.document.querySelector('.mlv-btn--legend');
  assert.ok(legendButton, 'the toolbar has a Legend button');
  click(ctx, legendButton);

  const legend = ctx.document.querySelector('.mlv-legend');
  assert.equal(legend.hidden, false, 'the toolbar button opens the legend');
  assert.ok(
    ctx.canvas.contains(legend),
    'the legend lives inside .mlv-canvas — which is why the pan guard has to know about it'
  );

  for (const selector of ['.mlv-legend', '.mlv-legend__body', '.mlv-legend__close', '.mlv-legend__title']) {
    const target = ctx.document.querySelector(selector);
    assert.ok(target, selector + ' exists');
    ctx.canvas.classList.remove('is-panning');
    pointerdown(ctx, target);
    assert.equal(
      ctx.canvas.classList.contains('is-panning'),
      false,
      'pointerdown on ' + selector + ' must not start a drag-pan: in a real browser the canvas ' +
        'then takes pointer capture and the click is retargeted away from the legend'
    );
  }
});

test('the pan guard still lets the bare canvas pan, and still exempts a card', async () => {
  const ctx = await app();

  ctx.canvas.classList.remove('is-panning');
  pointerdown(ctx, ctx.canvas, 7);
  assert.equal(
    ctx.canvas.classList.contains('is-panning'),
    true,
    'dragging empty canvas is still a pan — the guard must narrow, never disable, it'
  );

  const card = ctx.document.querySelector('.mlv-node');
  assert.ok(card, 'the golden draws at least one card');
  ctx.canvas.classList.remove('is-panning');
  pointerdown(ctx, card, 8);
  assert.equal(
    ctx.canvas.classList.contains('is-panning'),
    false,
    'a card is still that widget’s gesture'
  );
});

/* ── HOSTS-UX-ANSWERWRAP: a path is one token, and it must break ────────── */

test('the answer card breaks a long unbreakable token instead of painting over the next answer', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');

  /** The declarations block for one selector, as authored. */
  const blockFor = (selector) => {
    const at = css.indexOf(selector + ' {');
    assert.notEqual(at, -1, 'the shipped stylesheet declares ' + selector);
    return css.slice(at, css.indexOf('}', at));
  };

  const WRAPS = /(overflow-wrap:\s*(anywhere|break-word)|word-break:\s*(break-all|break-word)|hyphens:\s*auto)/;

  for (const selector of ['.mlv-answers__sentence', '.mlv-answers__cites']) {
    assert.match(
      blockFor(selector),
      WRAPS,
      selector + ' must declare a wrapping property. A workspace-relative path — ' +
        '"PyTorch/Classification/ConvNets/image_classification/training.py:205" — offers no break ' +
        'opportunity, so without one it overflows its grid column and is drawn on top of the ' +
        'neighbouring answer. `.mlv-insp__fqn` already does this with word-break: break-all.'
    );
  }
});

test('the long-path answer the wrap rule has to cover really is one text run in one column', async () => {
  // The DeepLearningExamples sentence, verbatim: 391 px of text in a 295 px
  // grid column, and no space between the slashes to break at.
  const LONG = {
    sentence:
      'Evaluation runs in train() at PyTorch/Classification/ConvNets/image_classification/training.py:205 ' +
      'and validate() at PyTorch/Classification/ConvNets/image_classification/training.py:257 (+3 more).',
    nodeIds: [],
    locs: [
      {
        file: 'PyTorch/Classification/ConvNets/image_classification/training.py',
        absFile: '/w/PyTorch/Classification/ConvNets/image_classification/training.py',
        line: 205,
        col: 0,
        endLine: 205,
        endCol: 10,
      },
    ],
    confidence: 0.9,
  };
  const graph = JSON.parse(JSON.stringify(sample));
  graph.answers = { evaluation: LONG };
  const ctx = await app(graph);

  const item = ctx.document.querySelector('.mlv-answers__item');
  assert.ok(item, 'the answer card renders when the document carries an answers block');
  const sentence = item.querySelector('.mlv-answers__sentence');
  assert.ok(sentence, 'the row carries the sentence element the wrap rule has to cover');
  const longest = (sentence.textContent || '')
    .split(/\s+/)
    .reduce((a, b) => (b.length > a.length ? b : a), '');
  assert.ok(
    longest.length > 60,
    'this sentence really does contain one unbreakable ' + longest.length + '-character token'
  );
  const cites = item.querySelector('.mlv-answers__cites');
  assert.ok(cites, 'and the citation row under it, which overflows the same way');
});

/* ── HOSTS-UX-ROWCOUNT: the menu promises what the click delivers ───────── */

test('every scope-picker row promises the node count its own click delivers', async () => {
  const ctx = await app();
  const d = ctx.document;
  const openPicker = () => click(ctx, d.querySelector('.mlv-btn--scope'));

  openPicker();
  const rows = [...d.querySelectorAll('.mlv-scopepicker__row')]
    .map((row) => ({
      spec: row.getAttribute('data-scope-spec'),
      detail: (row.querySelector('.mlv-scopepicker__rowdetail') || {}).textContent || '',
    }))
    .filter((row) => row.spec && row.spec !== 'all');
  assert.ok(rows.length >= 8, 'the golden offers a menu worth checking, got ' + rows.length);

  const mismatches = [];
  for (const row of rows) {
    const promised = (row.detail.match(/(\d+)\s+nodes?/) || [])[1];
    if (promised === undefined) continue;
    openPicker();
    const button = d.querySelector('.mlv-scopepicker__row[data-scope-spec="' + row.spec + '"]');
    assert.ok(button, 'the row for ' + row.spec + ' is still in the menu');
    click(ctx, button);
    const crumb = ((d.querySelector('.mlv-breadcrumb') || {}).textContent || '').replace(/\s+/g, ' ');
    const delivered = (crumb.match(/(\d+)\s+of\s+\d+\s+nodes?/) || [])[1];
    assert.ok(delivered !== undefined, 'the breadcrumb counts the projection for ' + row.spec + ': ' + crumb);
    if (promised !== delivered) {
      mismatches.push(row.spec + ': the row says ' + promised + ', the click draws ' + delivered);
    }
  }

  assert.deepEqual(
    mismatches,
    [],
    'the scope picker must offer the number the click delivers — round 1 fixed this for the ' +
      'pipeline rows (scopepicker.ts, drawnCount) and left unitRow()/groupRow() promising the ' +
      'match set, so a unit row under-counts by the default depth and a stage/concern row ' +
      'under-counts by the context ancestors the projection keeps.'
  );
});
