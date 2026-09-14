/**
 * Hardening round 2, area webview — TAB2-10 and HOSTS-UX-R2-06.
 *
 * Round 1 bounded the two chrome bands (CONTRACTS 11.55 B1): `.mlv-chiprow` at
 * 14vh and `.mlv-banners` at 20vh, so nothing collapses the canvas to zero any
 * more. Two things it did not do are what this file pins.
 *
 * TAB2-10 — A CHIP WAS A PARAGRAPH.
 * `unresolved_callee` had no purpose-built surface in the viewer, so it fell
 * through to the generic note chip whose visible text is the diagnostic's WHOLE
 * message. MEASURED on `analyzer/tests/accuracy/corpus/tabular_survival_cox`
 * (`python -m mlview analyze … --json`), which is 2 diagnostics:
 *
 *     unresolved_callee  scope=lifelines  count=3  survival.py  message 349 chars
 *     unresolved_callee  scope=sksurv     count=2  survival.py  message 327 chars
 *
 * and the row drew those 349 and 327 characters verbatim, beside the two
 * three-word chips "Objective" and "Save / Deploy". `.mlv-chiprow .mlv-chip` is
 * `white-space: normal` (VW-08), so the two sentences wrapped to fill the
 * scroller's 12vh and the reader had to scroll a CHIP ROW to discover that two
 * stage chips were there at all — the honest disclosure was the least readable
 * thing on the page.
 *
 * Swept over the 260 pre-built public-corpus documents in jsdom: on the build
 * before this one, 227 of them drew a chip whose visible text was over 48
 * characters — 1257 chips, the longest 486 — and 1255 chips carried NO `title`
 * at all, so for those the cut text had nowhere to be recovered from. 226 of
 * the 260 carry `unresolved_callee` (10 834 diagnostics, longest message 558
 * chars): it is not an edge case, it is every workspace with a dependency
 * MLView has no table for.
 *
 * The fix is to treat it as what the OTHER half of the product already treats
 * it as. `emit/answers._COVERAGE_KINDS` has counted `unresolved_callee` as a
 * coverage gap since CONTRACTS 11.52 — it is what makes the verdict say "so
 * this is not a clean bill of health" — while `ui/chromenotes.COVERAGE_KINDS`
 * did not. It now does, which gives it the shape its two siblings already had:
 * a short chip built from the diagnostic's STRUCTURED fields, the sentence on
 * the chip's `title`, and the sentence again in the coverage banner.
 *
 * HOSTS-UX-R2-06 — THREE BANDS, THREE SEPARATE BUDGETS, AND NO BUDGET FOR THE
 * SUM. Measured at first paint across 45 large workspaces: at 1280x800 the
 * canvas was 247 px of 800 — 31 %, the SAME 247 on 24 of them — behind 160 px
 * of banners, 105 px of chips and a 165 px answer card. The card is the only
 * one of the three whose content the reader can ask for later without losing
 * anything, because its header states `1 of 4 answered · 3 not detected`
 * whether it is open or shut. So on a document whose bands above it already
 * come to CHROME_CROWDED_PX it starts closed. Over the same 260 documents that
 * is 153 of them; on the 92-program labelled corpus it is none.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

/** The two diagnostics `tabular_survival_cox` actually emits, verbatim. */
const LIFELINES = {
  kind: 'unresolved_callee',
  file: 'survival.py',
  line: 67,
  scope: 'lifelines',
  count: 3,
  message:
    'MLView has no knowledge table for `lifelines`, so it read 3 calls into it ' +
    '(`CoxPHFitter(...)` at line 67, `KaplanMeierFitter(...)` at line 73, ' +
    '`concordance_index(...)` at line 96) without understanding what they do. ' +
    'Those calls draw no node, and any stage they belong to may be present without ' +
    'being detected - a gap in coverage, not a clean result.',
};
const SKSURV = {
  kind: 'unresolved_callee',
  file: 'survival.py',
  line: 82,
  scope: 'sksurv',
  count: 2,
  message:
    'MLView has no knowledge table for `sksurv`, so it read 2 calls into it ' +
    '(`RandomSurvivalForest(...)` at line 82, `concordance_index_censored(...)` at line 99) ' +
    'without understanding what they do. Those calls draw no node, and any stage they ' +
    'belong to may be present without being detected - a gap in coverage, not a clean result.',
};

/** ANA-5a's flavour of the same kind: a scope qualname, not a package. */
const ANA5A = {
  kind: 'unresolved_callee',
  file: 'odd.py',
  line: 4,
  scope: 'train.build',
  count: 2,
  message:
    'MLView could not resolve 2 calls in train.build: `dispatch(...)` at line 4 is a lambda; ' +
    'the call at line 9 has a subscript as its callee. Each one is drawn as an `unknown` op ' +
    'rather than dropped, and any stage those calls belong to may be present without being ' +
    'detected - a gap in coverage, not a clean result.',
};

const ANSWERS = {
  dataEntry: {
    sentence: 'Data enters through load_data() and is split by train_test_split.',
    nodeIds: [],
    locs: [{ file: 'data.py', absFile: '/w/data.py', line: 26, col: 0, endLine: 26, endCol: 10 }],
    confidence: 0.9,
  },
  objective: {
    sentence: 'CrossEntropyLoss is minimised by Adam at lr=1e-3.',
    nodeIds: [],
    locs: [{ file: 'train.py', absFile: '/w/train.py', line: 23, col: 0, endLine: 23, endCol: 10 }],
    confidence: 0.8,
  },
  evaluation: {
    sentence: 'The eval loop is guarded by model.eval() and torch.no_grad().',
    nodeIds: [],
    locs: [{ file: 'train.py', absFile: '/w/train.py', line: 44, col: 0, endLine: 44, endCol: 10 }],
    confidence: 0.7,
  },
  verdict: { sentence: 'Could not determine which finding matters most.', nodeIds: [], locs: [], confidence: 0.3 },
};

/**
 * Three banners plus a chip row — the shape 153 of the 260 public-corpus
 * documents have. `parse_error` and `dynamic_scope` are banner-only kinds
 * (SPECIALLY_RENDERED), `untagged_dataflow` draws both, and the demo's one
 * absent stage draws the fourth chip.
 */
const CROWDING = [
  { kind: 'parse_error', file: 'broken.py', line: 3, message: 'broken.py:3 — invalid syntax' },
  { kind: 'dynamic_scope', file: 'registry.py', line: 12, message: 'registry.py builds its model by name.' },
  { kind: 'untagged_dataflow', file: 'data.py', line: 7, count: 2, message: 'data.py:7 — X reached train_test_split with no traced origin.' },
];

function withGraph({ diagnostics = [], answers = ANSWERS } = {}) {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.diagnostics = diagnostics;
  if (answers) graph.answers = answers;
  return graph;
}

async function mount(graph, state = null) {
  const ctx = await loadBundle();
  const saved = [];
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: (s) => saved.push(s),
    loadState: () => state,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  const chipsOf = () => Array.from(ctx.document.querySelectorAll('.mlv-chiprow .mlv-chip'));
  return {
    ...ctx,
    app,
    saved,
    chips: chipsOf,
    /** What a chip DRAWS, which is its text element and never its count. */
    textOf: (chip) => ((chip.querySelector('.mlv-chip__text') || chip).textContent || '').trim(),
    card: () => ctx.document.querySelector('.mlv-answers'),
    head: () => ctx.document.querySelector('.mlv-answers__head'),
  };
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

/* ── TAB2-10: a chip is a label, and the sentence has two homes ─────────── */

test('an unresolved_callee chip states the package and the count, not the paragraph', async () => {
  const ctx = await mount(withGraph({ diagnostics: [LIFELINES, SKSURV] }));
  const chips = ctx.chips().filter((c) => c.getAttribute('data-coverage') === 'unresolved_callee');
  assert.equal(chips.length, 2, 'one chip per (file, package), as 11.52 A2 emits them');
  const texts = chips.map(ctx.textOf);
  assert.deepEqual(texts, ['lifelines — 3 calls not understood', 'sksurv — 2 calls not understood']);
  for (const text of texts) {
    assert.ok(text.length <= 48, 'a chip is a label: ' + text.length + ' chars — ' + text);
  }
  // Nothing was dropped to get there: the whole 349-character sentence is on
  // the chip, one hover away, and the emitter's own words are unedited.
  assert.equal(chips[0].title, LIFELINES.message);
  assert.equal(chips[1].title, SKSURV.message);
  ctx.app.destroy();
});

test('the sentence has a second, visible home: the coverage banner', async () => {
  const ctx = await mount(withGraph({ diagnostics: [LIFELINES, SKSURV] }));
  const banner = ctx.document.querySelector('[data-coverage-banner]');
  assert.ok(banner, 'unresolved_callee is a coverage claim in the viewer, as it is in emit/answers');
  assert.equal(banner.getAttribute('data-coverage-banner'), '2');
  const text = banner.textContent;
  assert.ok(text.indexOf('5 calls were not understood (lifelines, sksurv)') >= 0, text.slice(0, 160));
  assert.ok(text.indexOf('not a clean bill of health') >= 0, 'the honest sentence, verbatim');
  // Both messages reach the reader with their location, which is what `describe`
  // gives every other coverage kind.
  assert.ok(text.indexOf('survival.py:67') >= 0, 'with its location: ' + text.slice(0, 120));
  assert.ok(text.indexOf('`CoxPHFitter(...)` at line 67') >= 0, 'and the callees it names');
  assert.ok(text.indexOf('`RandomSurvivalForest(...)` at line 82') >= 0);
  ctx.app.destroy();
});

test('the chip says only what is true of BOTH emitters of this kind', async () => {
  // 11.52 B1/B2: `core/unknown_framework.py` ("I read these calls and have no
  // table for this library") and `core/unresolved.py` ("I could not read these
  // callees") ship under ONE kind, and nothing in the document distinguishes
  // them. So the chip states the gap they share and leaves the distinction to
  // the message, which is on the title and in the banner, word for word.
  const ctx = await mount(withGraph({ diagnostics: [ANA5A] }));
  const chip = ctx.chips().find((c) => c.getAttribute('data-coverage') === 'unresolved_callee');
  assert.equal(ctx.textOf(chip), 'train.build — 2 calls not understood');
  assert.equal(chip.title, ANA5A.message);
  assert.ok(chip.title.indexOf('could not resolve') >= 0, 'the distinction survives in the words');
  ctx.app.destroy();
});

test('a diagnostic with no scope and no count still reads as a sentence', async () => {
  // Both emitters always set them; a hand-written document, an older analyzer
  // or a future one need not. The chip must not read "undefined — 0 calls".
  const ctx = await mount(withGraph({ diagnostics: [{ kind: 'unresolved_callee', message: 'Something went unread.' }] }));
  const chip = ctx.chips().find((c) => c.getAttribute('data-coverage') === 'unresolved_callee');
  assert.equal(ctx.textOf(chip), 'calls not understood');
  assert.equal(chip.title, 'Something went unread.');
  const banner = ctx.document.querySelector('[data-coverage-banner]');
  assert.ok(banner.textContent.indexOf('1 call was not understood') >= 0, banner.textContent.slice(0, 120));
  // ...and the headline is a sentence, not "Coverage: . A clean result…".
  assert.ok(banner.textContent.indexOf('Coverage: 1 call') === 0, banner.textContent.slice(0, 60));
  ctx.app.destroy();
});

test('every diagnostic chip carries its whole text on a title — the generic one included', async () => {
  // 1255 of the chips the previous build drew over the 260 public-corpus
  // documents had NO title at all. The stylesheet ellipsises a chip wider than
  // its bound, so a chip with nowhere to recover the tail from would be the
  // silent cut VW-08 was about.
  const long = 'A kind this renderer has never heard of, whose message runs well past the ' +
    'width of one chip and therefore has to be recoverable from somewhere.';
  const ctx = await mount(
    withGraph({
      diagnostics: [
        LIFELINES,
        { kind: 'config_unresolved', message: 'MLView did not open `conf/train.yaml`: the YAML / Hydra half of config resolution is deferred.' },
        { kind: 'a_kind_from_the_future', message: long },
      ],
    }),
  );
  const { CHIP_TEXT_CH } = ctx.MLView.__internal.chrome;
  for (const chip of ctx.chips()) {
    const text = ctx.textOf(chip);
    assert.ok(chip.title, 'no title on chip: ' + JSON.stringify(text));
    // Either the chip draws its text whole, or the title carries it. A long
    // text with a title that does not contain it would be the silent cut.
    assert.ok(
      text.length <= CHIP_TEXT_CH || chip.title.indexOf(text) >= 0,
      'a ' + text.length + '-char chip whose title does not hold it: ' + JSON.stringify(chip.title.slice(0, 60)),
    );
  }
  const future = ctx.chips().find((c) => c.getAttribute('data-diagnostic-kind') === 'a_kind_from_the_future');
  assert.equal(future.title, long, 'invariant 1.1/6: it still says what it says');
  assert.equal(ctx.textOf(future), long, 'and the element holds every character of it');
  ctx.app.destroy();
});

test('the chip text is bounded by the STYLESHEET, so nothing is cut from the document', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const rule = /\n\.mlv-chiprow \.mlv-chip__text \{([^}]*)\}/.exec(css);
  assert.ok(rule, '.mlv-chiprow .mlv-chip__text has no rule of its own in dist/mlview.dev.css');
  const body = rule[1];
  assert.match(body, /overflow:\s*hidden/, body);
  assert.match(body, /text-overflow:\s*ellipsis/, body);
  assert.match(body, /white-space:\s*nowrap/, body);
  assert.match(body, /max-width:\s*\d+ch/, 'the bound is in ch, so it follows the row\'s type: ' + body);
  // VW-08's own rule is untouched: the CHIP may still wrap and never exceeds the row.
  const chip = /\n\.mlv-chiprow \.mlv-chip \{([^}]*)\}/.exec(css);
  assert.match(chip[1], /white-space:\s*normal/);
  assert.match(chip[1], /max-width:\s*100%/);
});

test('a folded chip keeps its ×N OUTSIDE the bounded text, so the count cannot be clipped', async () => {
  const ctx = await mount(withGraph({ diagnostics: [LIFELINES, LIFELINES, LIFELINES] }));
  const chip = ctx.chips().find((c) => c.getAttribute('data-coverage') === 'unresolved_callee');
  assert.equal(chip.querySelector('[data-chip-fold]').getAttribute('data-chip-fold'), '3');
  const textEl = chip.querySelector('.mlv-chip__text');
  assert.ok(textEl, 'the text is its own element');
  assert.equal(textEl.textContent, 'lifelines — 3 calls not understood');
  assert.equal(textEl.querySelector('.mlv-chip__count'), null, 'the count is a sibling, not inside the clip');
  assert.ok((chip.title || '').indexOf('3× ') === 0, 'and the tooltip still opens with the count: ' + chip.title.slice(0, 30));
  ctx.app.destroy();
});

/* ── HOSTS-UX-R2-06: one budget over the bands above the canvas ─────────── */

test('the band estimate reproduces the two heights it was measured from', async () => {
  const ctx = await loadBundle();
  const { bandHeight, BANNER_PX, CHROME_CROWDED_PX } = ctx.MLView.__internal.chrome;
  // yolov5 at 1280x800: three banners were 160 px, and a full chip row 105.
  assert.equal(bandHeight(3, 0), 3 * BANNER_PX);
  assert.ok(Math.abs(bandHeight(3, 0) - 160) <= 6, bandHeight(3, 0) + ' px against 160 measured');
  assert.ok(Math.abs(bandHeight(0, 9) - 105) <= 6, bandHeight(0, 9) + ' px against 105 measured');
  assert.ok(bandHeight(3, 9) >= CHROME_CROWDED_PX, 'yolov5 is over the line: ' + bandHeight(3, 9));
  // A report with nothing to say takes nothing, and one banner is not a crowd.
  assert.equal(bandHeight(0, 0), 0);
  assert.ok(bandHeight(1, 4) < CHROME_CROWDED_PX, 'one banner and four chips is not: ' + bandHeight(1, 4));
});

test('on a crowded document the answer card starts CLOSED, still stating its count', async () => {
  const ctx = await mount(withGraph({ diagnostics: CROWDING }));
  assert.equal(ctx.document.querySelectorAll('.mlv-banner').length, 3, 'three banners');
  const card = ctx.card();
  assert.equal(card.hidden, false, 'the card is drawn');
  assert.equal(card.getAttribute('data-answers-yielded'), '1');
  assert.equal(ctx.head().getAttribute('aria-expanded'), 'false');
  assert.equal(ctx.document.querySelector('.mlv-answers__body').hidden, true);
  // Nothing is hidden by it: the line a reader scans is still there, and the
  // header says why it is shut.
  assert.ok(
    ctx.document.querySelector('.mlv-answers__count').textContent.indexOf('of 4 answered') > 0,
    ctx.document.querySelector('.mlv-answers__count').textContent,
  );
  assert.ok(ctx.head().title.indexOf('already fill the top of the window') > 0, ctx.head().title);
  // ...and one press opens it.
  click(ctx, ctx.head());
  assert.equal(ctx.document.querySelector('.mlv-answers__head').getAttribute('aria-expanded'), 'true');
  assert.equal(ctx.document.querySelector('.mlv-answers__body').hidden, false);
  ctx.app.destroy();
});

test('on a document with room the card starts OPEN, exactly as MLV-P1 wrote it', async () => {
  for (const diagnostics of [[], [LIFELINES, SKSURV]]) {
    const ctx = await mount(withGraph({ diagnostics }));
    assert.equal(ctx.card().getAttribute('data-answers-yielded'), '0', diagnostics.length + ' diagnostics');
    assert.equal(ctx.head().getAttribute('aria-expanded'), 'true');
    assert.equal(ctx.app.getState().answersOpen, undefined, 'and the default is still absent from the state');
    ctx.app.destroy();
  }
});

test('the reader outranks the default, in both directions, and it is remembered', async () => {
  // The case the old rule could not express: `answersOpen` was written only
  // when FALSE, so a card opened on a crowded report would have been shut again
  // by the default the next time that report was opened.
  const crowded = withGraph({ diagnostics: CROWDING });
  const ctx = await mount(crowded);
  click(ctx, ctx.head());
  assert.equal(ctx.app.getState().answersOpen, true, 'the choice is recorded, not left to the default');
  ctx.app.destroy();

  const again = await mount(withGraph({ diagnostics: CROWDING }), { answersOpen: true });
  assert.equal(again.head().getAttribute('aria-expanded'), 'true', 'and restored over a crowded document');
  assert.equal(again.card().getAttribute('data-answers-yielded'), '1', 'which still knows it is crowded');
  again.app.destroy();

  const shut = await mount(withGraph({ diagnostics: [] }), { answersOpen: false });
  assert.equal(shut.head().getAttribute('aria-expanded'), 'false', 'and closed over an empty one');
  assert.equal(shut.app.getState().answersOpen, false);
  shut.app.destroy();
});

test('dismissing a banner never reopens the card onto the space it just freed', async () => {
  const ctx = await mount(withGraph({ diagnostics: CROWDING }));
  assert.equal(ctx.head().getAttribute('aria-expanded'), 'false');
  for (const btn of ctx.document.querySelectorAll('.mlv-banner__actions .mlv-btn')) click(ctx, btn);
  assert.equal(ctx.document.querySelectorAll('.mlv-banner').length, 0, 'every banner is gone');
  assert.equal(
    ctx.document.querySelector('.mlv-answers__head').getAttribute('aria-expanded'),
    'false',
    'the 165 px card must not take the 159 px the reader just reclaimed',
  );
  ctx.app.destroy();
});

test('a scope change re-decides the default, and returns the same answer when it is cleared', async () => {
  // `applyProjection` replaces the drawn document, so the default is decided
  // again — the bands really are different under a scope. It has to be a pure
  // function of that document, or clearing a scope would leave the reader
  // somewhere they never asked to be.
  const ctx = await mount(withGraph({ diagnostics: CROWDING }));
  assert.equal(ctx.head().getAttribute('aria-expanded'), 'false', 'closed at first paint');
  ctx.app.setScope('stage:train');
  assert.equal(ctx.app.getScope().spec, 'stage:train', 'the scope took');
  ctx.app.setScope(null);
  assert.equal(
    ctx.document.querySelector('.mlv-answers__head').getAttribute('aria-expanded'),
    'false',
    'and the unscoped document decides exactly as it decided the first time',
  );
  // ...and a choice made under a scope survives the trip back.
  click(ctx, ctx.document.querySelector('.mlv-answers__head'));
  ctx.app.setScope('stage:train');
  ctx.app.setScope(null);
  assert.equal(
    ctx.document.querySelector('.mlv-answers__head').getAttribute('aria-expanded'),
    'true',
    'the reader opened it; no projection may shut it again',
  );
  ctx.app.destroy();
});

test('a card that starts closed still costs no tab stop before the canvas (VIEW-12)', async () => {
  const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';
  const ctx = await mount(withGraph({ diagnostics: CROWDING }));
  const stops = [];
  for (const element of ctx.document.getElementById('mlview-root').querySelectorAll(FOCUSABLE)) {
    if (element.disabled || element.tabIndex < 0) continue;
    let node = element;
    let shown = true;
    while (node && node.nodeType === 1) {
      if (node.hidden) shown = false;
      node = node.parentElement;
    }
    if (shown) stops.push(element);
  }
  const canvas = stops.indexOf(ctx.document.querySelector('.mlv-canvas'));
  assert.ok(canvas >= 0, 'the canvas is in the tab order');
  assert.ok(
    stops.indexOf(ctx.head()) > canvas,
    'the card is still after the canvas in tab order — `order: -1` lifts it visually only',
  );
  ctx.app.destroy();
});
