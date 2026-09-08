/**
 * VIEW-10 ("orient the first-time reader") and COVERAGE ("say when the analysis
 * was blind"), viewer half.
 *
 * VIEW-10 fixes three discoverability failures: no legend existed anywhere in
 * `webview/src`; there was no way to see the whole pipeline as a dozen cards;
 * and the marquee flow feature sat behind an icon-only button with no visible
 * label and no keyboard binding.
 *
 * COVERAGE adds five diagnostic kinds and renders the two the viewer owns, so a
 * run that could not look somewhere says so instead of reading clean.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

async function mount(graph = sample) {
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

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

function key(ctx, target, k, opts = {}) {
  target.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));
}

/* ── VIEW-10 (a): the legend ───────────────────────────────────────────── */

test('the legend is generated from what actually draws (VIEW-10)', async () => {
  const ctx = await mount();
  const { legendModel, severityShapes } = ctx.MLView.__internal;
  // Joined, not deep-compared: the model comes from the bundle's realm, and a
  // cross-realm array is never deep-strict-equal to a local one.
  assert.equal(legendModel().map((s) => s.id).join(','), 'severity,edges,states,confidence');

  const legend = ctx.document.querySelector('[data-legend]');
  assert.ok(legend, 'the panel is mounted');
  assert.equal(legend.hidden, true, 'closed until asked, and remembered per viewer');
  const rowKeys = Array.from(legend.querySelectorAll('[data-legend-row]')).map((r) => r.getAttribute('data-legend-row'));

  // Severity: the three glyphs the renderer really draws, by their real shapes.
  for (const sev of Object.keys(severityShapes)) assert.ok(rowKeys.indexOf('severity:' + sev) >= 0, sev);
  const shapes = new Set(Array.from(legend.querySelectorAll('.mlv-glyph__shape')).map((p) => p.getAttribute('d')));
  assert.equal(shapes.size, 3, 'three distinct marker paths, taken from markers.ts');
  for (const d of Object.values(severityShapes)) assert.ok(shapes.has(d), 'a legend glyph is not the drawn glyph');

  // Edges: every kind the renderer knows, plus unknown and the back-edge.
  const drawnKinds = new Set(Array.from(ctx.document.querySelectorAll('[data-edge-kind]')).map((e) => e.getAttribute('data-edge-kind')));
  for (const kind of drawnKinds) assert.ok(rowKeys.indexOf('edge:' + kind) >= 0, 'the diagram draws a ' + kind + ' edge the key omits');
  assert.ok(rowKeys.indexOf('edge:unknown') >= 0);
  assert.ok(rowKeys.indexOf('edge:back') >= 0);

  // Card states, named exactly as render/nodes.ts stamps them.
  for (const state of ['is-ghost', 'is-collapsed-group', 'is-dynamic', 'is-lowconf', 'is-stale', 'boundary']) {
    assert.ok(rowKeys.indexOf('state:' + state) >= 0, state);
  }
  for (const bucket of ['certain', 'likely', 'possible', 'speculative']) {
    assert.ok(rowKeys.indexOf('confidence:' + bucket) >= 0, bucket);
  }
  // Every row explains itself; a swatch with no words is not a key.
  for (const dd of legend.querySelectorAll('.mlv-legend__desc')) assert.ok(dd.textContent.length > 10, dd.textContent);

  // ...and no row says its own name twice (TB-16). The Confidence chip already
  // SPELLS the bucket, so the label beside it made every row in that section
  // read "certain / certain / Every factor the rule wants is present." -- the
  // only self-repeating row in the legend, in the section a first-time reader
  // is most likely to be reading.
  for (const dt of legend.querySelectorAll('[data-legend-row]')) {
    const words = dt.textContent.trim().split(/\s+/).filter((w) => w.length);
    assert.ok(words.length < 2 || words[0] !== words[1], 'row repeats itself: ' + dt.textContent);
  }
  const conf = legend.querySelector('[data-legend-row="confidence:certain"]');
  assert.equal(conf.textContent.trim(), 'certain', 'the chip is the label: ' + conf.textContent);
});

test('the legend opens from the toolbar and from a key, and persists (VIEW-10)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--legend');
  assert.ok(button, 'a toolbar button');
  assert.equal(button.querySelector('.mlv-btn__label').textContent, 'Legend', 'labelled, not icon-only');
  assert.equal(button.getAttribute('aria-pressed'), 'false');

  click(ctx, button);
  const legend = ctx.document.querySelector('[data-legend]');
  assert.equal(legend.hidden, false);
  assert.equal(ctx.document.querySelector('.mlv-btn--legend').getAttribute('aria-pressed'), 'true');
  assert.equal(ctx.app.getState().legendOpen, true, 'remembered per viewer');

  click(ctx, legend.querySelector('.mlv-legend__close'));
  assert.equal(ctx.document.querySelector('[data-legend]').hidden, true);
  assert.equal(ctx.app.getState().legendOpen, undefined, 'closed is the default, so it is absent');

  key(ctx, ctx.canvas, 'l');
  assert.equal(ctx.document.querySelector('[data-legend]').hidden, false, 'and `l` toggles it');
});

test('the legend appears in the ? shortcut sheet (VIEW-10)', async () => {
  const ctx = await mount();
  const sheet = ctx.document.querySelector('.mlv-sheet');
  const text = sheet.textContent;
  assert.ok(text.indexOf('Show or hide the legend') >= 0, 'the sheet renders KEYMAP, so the binding is documented');
  assert.ok(text.indexOf('Overview: collapse every group and fit') >= 0);
  assert.ok(text.indexOf('Turn the connection flow animation on or off') >= 0);
  const keys = ctx.MLView.__internal.keymap.map((b) => b.keys.join('/'));
  assert.ok(keys.indexOf('l') >= 0 && keys.indexOf('a') >= 0 && keys.indexOf('Shift+0') >= 0, keys.join(' '));
});

/* ── VIEW-10 (c): Overview mode ────────────────────────────────────────── */

test('Shift+0 collapses every group and fits (VIEW-10)', async () => {
  const ctx = await mount();
  const { GraphIndex } = ctx.MLView.__internal;
  const index = new GraphIndex(sample);
  const groups = sample.nodes.filter((n) => index.isGroup(n.id));
  assert.ok(groups.length > 0, 'the demo has groups to collapse');
  const before = ctx.document.querySelectorAll('[data-node-id]').length;

  key(ctx, ctx.canvas, ')');
  const state = ctx.app.getState();
  for (const g of groups) assert.ok(state.collapsed.indexOf(g.id) >= 0, g.id + ' is still expanded');
  const after = ctx.document.querySelectorAll('[data-node-id]').length;
  assert.ok(after < before, 'fewer cards: ' + after + ' from ' + before);
  assert.ok(after <= 14, 'a screenful, not a wall: ' + after + ' cards');

  // The aggregated severity markers survive the fold.
  assert.ok(ctx.document.querySelector('.mlv-badge, .mlv-cluster'), 'severity is still visible on the folded cards');
  const live = ctx.document.querySelector('[aria-live="polite"]');
  assert.ok(live.textContent.indexOf('Overview') >= 0, live.textContent);
});

test('Overview fits the WHOLE diagram inside the canvas at 1440x900 (VIEW-10, TB-03)', async () => {
  // VIEW-10(c)'s acceptance, stated directly. `overview()` used to call
  // `viewport.fit()`, which routes through `fitPlan`'s `tall` branch: the folded
  // demo is still much taller than it is wide, so Shift+0 inherited the
  // deliberate MLV-R3-001 top anchoring, zoomed IN from 0.747 to 0.837, and left
  // CrossEntropyLoss, train() and validate() -- 454 px of content -- entirely
  // below the fold at 1440x900, with nothing on screen saying so.
  const ctx = await mount();
  const canvas = ctx.canvas;
  const W = 1440;
  const H = 900;
  canvas.getBoundingClientRect = () => ({ left: 0, top: 0, right: W, bottom: H, width: W, height: H, x: 0, y: 0 });

  key(ctx, canvas, ')');
  const cards = ctx.document.querySelectorAll('[data-node-id]').length;
  assert.ok(cards <= 14, 'a screenful, not a wall: ' + cards + ' cards');

  // jsdom has no layout, so the geometry is read where the browser reads it:
  // the world's own size and the transform the viewport wrote on it. Every card
  // is inside the world by construction, so world-inside-canvas IS the
  // acceptance -- and it is the same arithmetic Chromium applies.
  const world = ctx.document.querySelector('.mlv-world');
  const size = { w: parseFloat(world.style.width), h: parseFloat(world.style.height) };
  const m = /translate\((-?[\d.]+)px,(-?[\d.]+)px\) scale\(([\d.]+)\)/.exec(world.style.transform);
  assert.ok(m, world.style.transform);
  const [x, y, zoom] = [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])];
  assert.ok(x >= -0.5 && y >= -0.5, 'the diagram starts inside the canvas: ' + x + ',' + y);
  assert.ok(x + size.w * zoom <= W + 0.5, 'clipped on the right: ' + (x + size.w * zoom));
  assert.ok(y + size.h * zoom <= H + 0.5, 'clipped below the fold: ' + (y + size.h * zoom) + ' of ' + H);

  // And the fix is the branch, not a lucky number: the same content fitted the
  // ordinary way still takes the top-anchored path.
  const { fitPlan } = ctx.MLView.__internal.viewport;
  assert.equal(fitPlan(size.w, size.h, W, H, 24, true).tall, false, 'a whole fit never top-anchors');
  assert.ok(zoom <= fitPlan(size.w, size.h, W, H, 24, false).zoom, 'Overview zooms out, never in');
});

test('Shift+0 and 0 are different commands (VIEW-10)', async () => {
  const ctx = await mount();
  const before = ctx.app.getState().collapsed.length;
  key(ctx, ctx.canvas, '0');
  assert.equal(ctx.app.getState().collapsed.length, before, 'plain 0 still just fits, collapsing nothing');
  // Some layouts report Shift+0 as ')', others as '0' with shiftKey; both mean
  // Overview, and neither may fall through to `fit`.
  key(ctx, ctx.canvas, '0', { shiftKey: true });
  assert.ok(ctx.app.getState().collapsed.length > before, 'Shift+0 collapsed the groups');
});

/* ── VIEW-10 (d): the labelled flow toggle ─────────────────────────────── */

test('the flow toggle carries a visible label, a tooltip and a binding (VIEW-10)', async () => {
  const ctx = await mount();
  const button = ctx.document.querySelector('.mlv-btn--flow');
  assert.equal(button.querySelector('.mlv-btn__label').textContent, 'Flow');
  assert.ok(button.title.indexOf('Connection flow animation is on') >= 0, button.title);
  assert.ok(button.title.indexOf('press A') >= 0, 'the tooltip names the key: ' + button.title);
  assert.equal(button.getAttribute('aria-pressed'), 'true');

  key(ctx, ctx.canvas, 'a');
  assert.equal(ctx.document.querySelector('.mlv-btn--flow').getAttribute('aria-pressed'), 'false');
  assert.equal(ctx.app.getState().flow, false, 'the same state the button writes');
  key(ctx, ctx.canvas, 'a');
  assert.equal(ctx.app.getState().flow, undefined, 'back to the default, which is absent');
});

/* ── COVERAGE ──────────────────────────────────────────────────────────── */

function withDiagnostics(diagnostics) {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.diagnostics = diagnostics;
  return graph;
}

test('untagged_dataflow and single_file_analysis are stated, not swallowed (COVERAGE)', async () => {
  const ctx = await mount(
    withDiagnostics([
      { kind: 'single_file_analysis', message: 'Only train.py was analyzed; MLV301, MLV302, MLV401, MLV501 need its neighbours.', codes: ['MLV301', 'MLV302', 'MLV401', 'MLV501'] },
      { kind: 'untagged_dataflow', message: 'make_splits(X, y): X reached train_test_split with no traced origin.', file: 'data.py', line: 12, count: 2 },
    ]),
  );
  const banner = ctx.document.querySelector('[data-coverage-banner]');
  assert.ok(banner, 'a coverage banner');
  assert.equal(banner.getAttribute('data-coverage-banner'), '2');
  const text = banner.textContent;
  assert.ok(text.indexOf('Coverage:') >= 0, text);
  assert.ok(text.indexOf('cross-file rules could not run') >= 0, text);
  assert.ok(text.indexOf('2 values') >= 0, 'the count is carried: ' + text);
  assert.ok(text.indexOf('not a clean bill of health') >= 0, 'the honest sentence, verbatim');
  // Both messages reach the reader, not only the headline.
  assert.ok(text.indexOf('MLV301, MLV302, MLV401, MLV501') >= 0);
  assert.ok(text.indexOf('make_splits(X, y)') >= 0);
  assert.ok(text.indexOf('data.py:12') >= 0, 'with its location');

  const chips = Array.from(ctx.document.querySelectorAll('[data-coverage]'));
  assert.deepEqual(chips.map((c) => c.getAttribute('data-coverage')).sort(), ['single_file_analysis', 'untagged_dataflow']);
  assert.ok(chips.find((c) => c.textContent.indexOf('single-file analysis') >= 0));
  assert.ok(chips.find((c) => c.textContent.indexOf('2 values not traced') >= 0));
});

test('a clean run draws no coverage banner (COVERAGE)', async () => {
  const ctx = await mount();
  assert.equal(sample.diagnostics.length, 0, 'the demo document declares none');
  assert.equal(ctx.document.querySelector('[data-coverage-banner]'), null);
  assert.equal(ctx.document.querySelector('[data-coverage]'), null);
  // ...and the "not detected" chip row is untouched, which render_report gates.
  const chips = ctx.document.querySelectorAll('.mlv-chiprow .mlv-chip');
  assert.equal(chips.length, 1, Array.from(chips).map((c) => c.textContent).join(', '));
});

test('the whole COVERAGE batch is accepted, and unknown kinds still render (COVERAGE)', async () => {
  const ctx = await mount(
    withDiagnostics([
      { kind: 'config_unresolved', message: 'MVL601 is not a rule code; did you mean MLV601?' },
      { kind: 'unresolved_callee', message: 'dispatch() is built by a lambda', file: 'odd.py', line: 4 },
      { kind: 'notebook_analyzed', message: '2 notebooks analyzed', count: 2 },
      { kind: 'a_kind_from_the_future', message: 'Something this renderer has never heard of.' },
    ]),
  );
  const row = ctx.document.querySelector('.mlv-chiprow');
  assert.ok(row.textContent.indexOf('did you mean MLV601?') >= 0, 'config_unresolved reads like config_warning');
  const generic = Array.from(ctx.document.querySelectorAll('[data-diagnostic-kind]'));
  const kinds = generic.map((c) => c.getAttribute('data-diagnostic-kind')).sort();
  // `unresolved_callee` has no purpose-built surface in the viewer half, so it
  // takes the same generic path a kind from the future does -- which is the
  // point: neither vanishes into the "N notes" count.
  assert.equal(kinds.join(','), 'a_kind_from_the_future,unresolved_callee');
  const future = generic.find((c) => c.getAttribute('data-diagnostic-kind') === 'a_kind_from_the_future');
  assert.equal(future.textContent, 'Something this renderer has never heard of.');
  // None of the four is a coverage claim, so no coverage banner is raised.
  assert.equal(ctx.document.querySelector('[data-coverage-banner]'), null);
  // And the status bar still counts every note.
  assert.ok(ctx.document.querySelector('.mlv-status').textContent.indexOf('4 notes') >= 0);
});
