/**
 * Hardening round 1, area hosts-ux — HOSTS-UX-CHIPWALL, and the gate that keeps
 * it closed: the diagnostic chip row may never take the viewport and leave the
 * diagram none.
 *
 * THE DEFECT, MEASURED in Chromium (Playwright) on reports written by this
 * analyzer from the pinned public corpus (`tools/public_corpus.py fetch`), at
 * 1600x1000 AND 1280x800:
 *
 *   repo target                         .mlv-chiprow   .mlv-banners   .mlv-canvas
 *   ultralytics/yolov5 .                    2132 px        323 px          0 px
 *   huggingface/pytorch-image-models .      3765 px        425 px          0 px
 *   mlflow/mlflow examples                   508 px        511 px          0 px
 *   analyzer/tests/fixtures                  256 px        (3 banners)     0 px
 *
 * Seven of the sixteen public-repo targets measured drew a **zero-pixel
 * canvas**: every card was in the DOM (366-405 of them on those four) and none
 * of it was on screen, while the toolbar went on reading `400 nodes · 813
 * edges`. That is a misrepresentation, not a layout bug — the page states a
 * size for a picture it is not showing.
 *
 * Two causes, both in this package, and either one alone still leaves the other
 * symptom:
 *
 *  1. `ui/chrome.ts` emitted ONE chip per diagnostic with no fold and no cap —
 *     yolov5's 84 diagnostics became 70 chips of which only 49 were distinct,
 *     and the sentence "MLView did not open `data/coco128.yaml`: …" was drawn
 *     **8 times verbatim**; `analyzer/tests/fixtures` drew `1 value not traced`
 *     36 times.
 *  2. `styles/chrome.css` gave `.mlv-chiprow` `flex: none` and `flex-wrap:
 *     wrap` with **no `max-height`**, while `.mlv-body` is `flex: 1 1 auto;
 *     min-height: 0` — so the row grew without bound and the canvas was the
 *     flex item that absorbed it.
 *
 * THE FIX is collect / fold / cap in `ui/chrome.ts` plus a height bound on both
 * bands in `styles/chrome.css`. Both halves are asserted here, and so is the
 * thing a cap must never cost: nothing is deleted. The folded tail is one press
 * away, the messages stay on the tooltips, and the status bar keeps counting
 * every diagnostic as a note.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

/** The sentence yolov5 produced 8 times, shortened but the same shape. */
const REPEATED =
  'MLView did not open `data/coco128.yaml`: the YAML / Hydra half of config ' +
  'resolution is deferred, so any value that comes from it is unresolved rather than guessed.';

/** The `.mlv-chip` count the row may never exceed: MAX_CHIPS plus its opener. */
const CEILING = 9;

function withDiagnostics(count, { identical = 0 } = {}) {
  const graph = JSON.parse(JSON.stringify(sample));
  const diagnostics = [];
  for (let i = 0; i < identical; i += 1) {
    diagnostics.push({ kind: 'config_unresolved', message: REPEATED, file: 'train.py', line: i + 1 });
  }
  for (let i = identical; i < count; i += 1) {
    diagnostics.push({
      kind: 'config_unresolved',
      message: `MLView did not open \`conf/${i}.yaml\`: the YAML / Hydra half of config resolution is deferred.`,
      file: `mod_${i}.py`,
      line: i + 1,
    });
  }
  graph.diagnostics = diagnostics;
  return graph;
}

async function mount(graph) {
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
  ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  const row = ctx.document.querySelector('.mlv-chiprow');
  const chips = () => Array.from(row ? row.querySelectorAll('.mlv-chip') : []);
  return { ...ctx, row, chips, texts: () => chips().map((c) => (c.textContent || '').trim()) };
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

/**
 * Visible to Tab. A HIDDEN control keeps whatever tabIndex it was built with —
 * the toolbar's "N suppressed" chip is `hidden` on a document with nothing set
 * aside and still reads `tabIndex 0` — so a tab-stop count that does not filter
 * on this counts a control nobody can reach.
 */
function shown(element) {
  let node = element;
  while (node && node.nodeType === 1) {
    if (node.hidden) return false;
    node = node.parentElement;
  }
  return true;
}

test('the chip row is bounded: 10 diagnostics and 400 draw the same number of chips', async () => {
  const ten = await mount(withDiagnostics(10));
  const many = await mount(withDiagnostics(400));
  assert.ok(ten.chips().length <= CEILING, 'ten diagnostics: ' + ten.chips().length + ' chips');
  assert.equal(
    many.chips().length,
    ten.chips().length,
    'the row must stop being a function of the diagnostic count — that is what took the canvas to 0 px',
  );
});

test('identical diagnostic sentences fold into one chip that carries its count', async () => {
  const ctx = await mount(withDiagnostics(12, { identical: 8 }));
  const repeats = ctx.texts().filter((t) => t.indexOf('data/coco128.yaml') >= 0).length;
  assert.equal(repeats, 1, 'the same sentence was drawn ' + repeats + ' times');
  const folded = ctx.chips().find((c) => (c.textContent || '').indexOf('data/coco128.yaml') >= 0);
  assert.equal(folded.querySelector('[data-chip-fold]').getAttribute('data-chip-fold'), '8', 'with its count');
  assert.ok(
    (folded.title || '').indexOf('8× ') === 0,
    'and the tooltip opens with the count: ' + JSON.stringify((folded.title || '').slice(0, 40)),
  );
});

test('a folded chip lists the DISTINCT messages behind it on its tooltip', async () => {
  // The coverage chips are the case where the text is short and identical while
  // the messages differ per file: `1 value not traced`, 36 times, on
  // analyzer/tests/fixtures. The count folds them; the tooltip keeps the files.
  const graph = JSON.parse(JSON.stringify(sample));
  graph.diagnostics = [0, 1, 2].map((i) => ({
    kind: 'untagged_dataflow',
    message: 'mod_' + i + '.py:7 — X reached train_test_split with no traced origin.',
    file: 'mod_' + i + '.py',
    line: 7,
    count: 1,
  }));
  const ctx = await mount(graph);
  const chips = ctx.chips().filter((c) => c.getAttribute('data-coverage') === 'untagged_dataflow');
  assert.equal(chips.length, 1, 'three identical texts are one chip');
  assert.equal(chips[0].querySelector('[data-chip-fold]').getAttribute('data-chip-fold'), '3');
  for (const i of [0, 1, 2]) {
    assert.ok(chips[0].title.indexOf('mod_' + i + '.py:7') >= 0, 'message ' + i + ' is on the tooltip');
  }
});

test('a repository with many diagnostics does not get one chip each', async () => {
  const ctx = await mount(withDiagnostics(84));
  assert.ok(
    ctx.chips().length <= 12,
    '84 diagnostics produced ' + ctx.chips().length + ' chips. yolov5 produced 70 of them, 2132 px tall, ' +
      'and the canvas below was then 0 px.',
  );
  const more = ctx.row.querySelector('[data-chip-more]');
  assert.ok(more, 'the tail is behind one chip');
  assert.equal(more.tagName, 'BUTTON', 'which is a real control, not a label');
  assert.equal(more.getAttribute('aria-expanded'), 'false');
  assert.equal(more.getAttribute('aria-pressed'), null, 'a disclosure is never a filter: that treatment strikes it through');
});

test('the folded tail is a DISCLOSURE — one press draws every chip that was held back', async () => {
  const ctx = await mount(withDiagnostics(84));
  const capped = ctx.chips().length;
  const more = ctx.row.querySelector('[data-chip-more]');
  const held = Number(more.getAttribute('data-chip-more'));
  assert.ok(held > 0, 'the chip states how many it stands for');
  click(ctx, more);
  const opened = ctx.chips().length;
  assert.equal(opened, capped + held, 'every held-back chip is drawn: ' + capped + ' + ' + held + ' = ' + opened);
  const less = ctx.row.querySelector('[data-chip-more]');
  assert.equal(less.getAttribute('aria-expanded'), 'true', 'and the control says it is open');
  click(ctx, less);
  assert.equal(ctx.chips().length, capped, 'and folds back');
});

test('.mlv-chiprow and .mlv-banners are height-bounded, so neither can starve .mlv-body', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  for (const selector of ['.mlv-chiprow', '.mlv-banners']) {
    // Every rule block that names this selector, in the authored stylesheet.
    const blocks = [...css.matchAll(new RegExp(`([^}]*\\${selector}[^{}]*)\\{([^}]*)\\}`, 'g'))].map(
      (m) => m[2],
    );
    assert.ok(blocks.length > 0, `${selector} has no rule in dist/mlview.dev.css`);
    const bounded = blocks.some((body) => /max-height\s*:/.test(body) && /overflow-y\s*:\s*auto/.test(body));
    assert.ok(
      bounded,
      `${selector} declares no max-height with overflow-y:auto, so it grows without bound. ` +
        '.mlv-body is `flex: 1 1 auto; min-height: 0`, so the canvas is the item that collapses — ' +
        'measured at 0 px on 7 of 16 public-repo reports.',
    );
  }
});

test('the two bands together can never claim more than half the viewport', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  // The EXACT selector, not a substring of one: `.mlv-chiprow__chips` is the
  // inner scroller and carries its own cap, and a loose match would count both.
  const cap = (selector) => {
    const rule = new RegExp('\\n\\' + selector + ' \\{([^}]*)\\}').exec(css);
    assert.ok(rule, selector + ' has no rule of its own in dist/mlview.dev.css');
    const found = /max-height:\s*([\d.]+)vh/.exec(rule[1]);
    assert.ok(found, selector + ' declares no vh cap: ' + rule[1]);
    return Number(found[1]);
  };
  const total = cap('.mlv-chiprow') + cap('.mlv-banners');
  assert.ok(total <= 50, 'the chip row and the banners together cap at ' + total + 'vh; the diagram gets the rest');
});

test('the document under a wall of diagnostics is still fully drawn — nothing is dropped', async () => {
  const ctx = await mount(withDiagnostics(84));
  assert.ok(ctx.document.querySelectorAll('.mlv-node').length > 0, 'the cards are in the DOM');
  // The count the toolbar states, the notes the status bar counts and the cards
  // drawn all have to agree — a cap on the CHIPS is not a cap on the truth.
  const status = ctx.document.querySelector('.mlv-status').textContent;
  assert.ok(status.indexOf('84 notes') >= 0, 'every diagnostic is still counted: ' + status);
  const stats = (ctx.document.querySelector('.mlv-stats') || {}).textContent || '';
  assert.match(stats, /\d+/, 'and the toolbar still states the graph size');
});

test('the disclosure costs the path to the canvas nothing (VIEW-12)', async () => {
  // The first attempt at this fix put the "+N more" button in a chip row that
  // sits between the search box and the canvas, which made the canvas the FIFTH
  // Tab press on any document with more than MAX_CHIPS notes — VIEW-12 allows
  // four, and the a11y gate never saw it because the demo has no diagnostics at
  // all. The row is now the third row of the one `role="toolbar"`, so its
  // control is inside the roving group and the strip stays one tab stop.
  const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';
  const order = (ctx) => {
    const out = [];
    for (const element of ctx.document.getElementById('mlview-root').querySelectorAll(FOCUSABLE)) {
      if (element.disabled || element.tabIndex < 0) continue;
      if (!shown(element)) continue;
      out.push(element);
    }
    return out;
  };
  for (const count of [0, 84]) {
    const ctx = await mount(withDiagnostics(count));
    const stops = order(ctx);
    const at = stops.indexOf(ctx.document.querySelector('.mlv-canvas'));
    assert.ok(at >= 0, count + ' diagnostics: the canvas is in the tab order');
    assert.ok(
      at + 1 <= 4,
      count + ' diagnostics: the canvas is press ' + (at + 1) + ' — ' +
        stops.slice(0, at + 1).map((e) => (e.getAttribute('class') || e.tagName).split(/\s+/)[0]).join(' -> '),
    );
    // ...and the strip is still ONE tab stop, the rebuilt row included.
    const bar = ctx.document.querySelector('.mlv-chromebar');
    assert.ok(bar.contains(ctx.row), 'the chip row is inside the toolbar');
    const zero = Array.from(bar.querySelectorAll('button')).filter((b) => b.tabIndex === 0 && shown(b));
    assert.equal(zero.length, 1, count + ' diagnostics: ' + zero.length + ' tab stops inside the toolbar');
  }
});

test('opening the fold keeps the strip at one tab stop (VIEW-12)', async () => {
  const ctx = await mount(withDiagnostics(84));
  click(ctx, ctx.row.querySelector('[data-chip-more]'));
  const bar = ctx.document.querySelector('.mlv-chromebar');
  const zero = Array.from(bar.querySelectorAll('button')).filter((b) => b.tabIndex === 0 && shown(b));
  assert.equal(zero.length, 1, 'the rebuilt row handed the single tab stop back');
});

test('a document with a handful of notes is untouched by the cap', async () => {
  const ctx = await mount(withDiagnostics(3));
  assert.equal(ctx.row.querySelector('[data-chip-more]'), null, 'no opener where there is nothing to open');
  assert.equal(ctx.row.querySelector('[data-chip-fold]'), null, 'and no count on a chip that stands for itself');
  for (const chip of ctx.chips()) {
    assert.ok((chip.textContent || '').indexOf('×') < 0, 'an unfolded chip reads exactly as it always did');
  }
});
