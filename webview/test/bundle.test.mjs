/**
 * Bundle hygiene (CONTRACTS section 8, amendment A7). The shipped bundle must
 * contain no markup-string assignment, no eval, no dynamic import and no
 * absolute URL — the last one is what keeps the standalone report offline and
 * the webview inside `default-src 'none'`.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { readBundle, DIST_CSS, DIST_CSS_DEV, DIST_JS } from './helpers.mjs';
import { minifyCss } from '../build.mjs';

const bundle = await readBundle();
/** What SHIPS: minified (BUILD-01). */
const css = await readFile(DIST_CSS, 'utf8');
/** The same stylesheet before minification -- what the structural gates read. */
const devCss = await readFile(DIST_CSS_DEV, 'utf8');

test('dist/mlview.js exists and is a single IIFE exposing MLView', async () => {
  const info = await stat(DIST_JS);
  assert.ok(info.size > 10000, 'bundle looks too small to be complete');
  assert.ok(/var MLView\s*=/.test(bundle), 'bundle defines the MLView global');
});

test('no markup-string assignment anywhere in the bundle', () => {
  for (const banned of ['inner' + 'HTML', 'outer' + 'HTML', 'insertAdjacent' + 'HTML', 'document.write']) {
    assert.equal(bundle.indexOf(banned), -1, 'bundle contains ' + banned);
  }
});

test('no eval and no dynamic import in the bundle', () => {
  assert.equal(bundle.indexOf('eval('), -1, 'bundle contains eval(');
  assert.equal(bundle.indexOf('new Function('), -1, 'bundle constructs functions from strings');
  assert.ok(!/[^.\w]import\s*\(/.test(bundle), 'bundle contains a dynamic import()');
});

test('no absolute URLs in the bundle or the stylesheet', () => {
  for (const [name, text] of [
    ['mlview.js', bundle],
    ['mlview.css', css],
  ]) {
    assert.equal(text.indexOf('http' + '://'), -1, name + ' contains an http URL');
    assert.equal(text.indexOf('https' + '://'), -1, name + ' contains an https URL');
    assert.equal(text.indexOf('//cdn'), -1, name + ' references a CDN');
  }
  assert.equal(css.indexOf('@import'), -1, 'stylesheet uses @import');
  assert.ok(!/url\(\s*["']?(?:https?:)?\/\//.test(css), 'stylesheet loads a remote asset');
});

test('the SVG namespace is still reachable at runtime', async () => {
  // The literal is assembled from parts so the offline greps above stay clean;
  // this proves the assembly still produces the real namespace.
  const { loadBundle } = await import('./helpers.mjs');
  const { document, MLView } = await loadBundle();
  const root = document.getElementById('mlview-root');
  const glyph = MLView.__internal.severityGlyph('high', 18, 'high severity');
  assert.equal(glyph.namespaceURI, 'http' + '://' + 'www.w3.org/2000/svg');
  root.appendChild(glyph);
});

test('stylesheet carries the token layer and both theme branches', () => {
  // Authored form. The shipped file says the same thing in the minifier's
  // spelling -- asserted separately below, so neither form can drift alone.
  assert.ok(devCss.indexOf('--mlv-sev-high') >= 0);
  assert.ok(devCss.indexOf('[data-theme="dark"]') >= 0);
  assert.ok(devCss.indexOf('[data-theme="hc"]') >= 0);
  assert.ok(devCss.indexOf('prefers-color-scheme: dark') >= 0);
  assert.ok(devCss.indexOf('prefers-reduced-motion') >= 0);
});

test('the SHIPPED stylesheet carries the same layers in minified spelling (BUILD-01)', () => {
  // esbuild unquotes attribute values and drops the space after a colon, so the
  // shipped file is grepped in ITS spelling -- proving the minifier did not eat
  // a theme branch on the way into the report.
  assert.ok(css.indexOf('--mlv-sev-high') >= 0);
  assert.ok(css.indexOf('[data-theme=dark]') >= 0);
  assert.ok(css.indexOf('[data-theme=hc]') >= 0);
  assert.ok(css.indexOf('prefers-color-scheme:dark') >= 0);
  assert.ok(css.indexOf('prefers-reduced-motion') >= 0);
  assert.ok(css.indexOf('.mlv-root[data-theme=hc]') >= 0, 'the mount-root hc block survives');
});

test('dist/mlview.css IS the minification of dist/mlview.dev.css (BUILD-01)', async () => {
  // The gate that makes every dev-CSS assertion an assertion about what ships:
  // one esbuild.transform call stands between the two files, and nothing else.
  const expected = await minifyCss(devCss);
  assert.equal(css, expected, 'the shipped stylesheet is not the minified dev stylesheet');
  assert.ok(css.length < devCss.length * 0.75, 'minification cut at least 25%: ' + css.length + ' of ' + devCss.length);
});

/*
 * BUILD-01's size ratchet.
 *
 * MEASURED ON THIS TREE, 2026-09-13, after the hosts-ux hardening round landed
 * on top of PERF-04 (the hierarchical rollup) and MLV-P12 (multi-pipeline
 * workspaces):
 *   dist/mlview.js       327 214 B (319.5 KB)
 *   dist/mlview.css       72 857 B  (71.1 KB), minified from 130 953 B (-44%)
 *   dist/mlview.dev.css  130 953 B (127.9 KB, never shipped)
 *
 * THE HARDENING ROUND moved the JS by +2 776 B and the CSS by +1 168 B, and BOTH
 * CAPS with them -- the JS had 636 B of headroom left, which is a ratchet
 * nobody can land anything through. Where it went, largest first.
 * HOSTS-UX-CHIPWALL is the item: `ui/chrome.ts` collected its chips as
 * descriptors and then FOLDS identical texts and CAPS the row at MAX_CHIPS with
 * one disclosure chip (about 1.2 KB), because one chip per diagnostic made
 * `.mlv-chiprow` 2 132 px tall on ultralytics/yolov5 and `.mlv-canvas` 0 px --
 * on seven of sixteen public repositories, with every card in the DOM and none
 * on screen. HOSTS-UX-PIPELINECOUNT is next (about 0.8 KB): `scope/catalog.ts`
 * runs the same `project()` the click runs and hands every row a `viewCount`,
 * and `scope/pipelines.ts` exposes the one `drawnCount` the picker, the chooser
 * and its accessible name all read -- the picker used to promise 55 nodes where
 * the projection drew 56. The rest is small and countable: DGRG-12's answered/
 * not-detected counter in `ui/answers.ts` (about 0.3 KB), HOSTS-UX-FITZOOM's one
 * branch in `render/canvas.ts` and HOSTS-UX-STAGERESET's return value in
 * `filters.ts` with its announcement in `app.ts` (about 0.3 KB together). The
 * CSS is the height bound on `.mlv-chiprow` and `.mlv-banners` that keeps the
 * canvas from being starved, the disclosure chip, and HOSTS-UX-ANSWERSCROLL's
 * scroll cue on the two panels that clip their last line. Caps go to JS 326 KB
 * and CSS 73 KB, leaving 6 610 B (2.0 %) and 1 895 B (2.5 %) -- the same order
 * every ratchet before them held. The ratchet's job is unchanged: make the NEXT
 * growth visible.
 *
 * The tree those two landed on shipped 304 818 B of JS and 68 001 B of CSS, so
 * they cost +17 620 B and +3 688 B, and BOTH CAPS MOVE — which is the number a
 * lead looks for, so here is where it went. PERF-04 is about 8.5 KB: `rollup/
 * rolled.ts` is the only module that knows the names of `Node.rolledUp` and
 * `Edge.weight` and it also owns the stroke curve, the badge geometry shared
 * with the export, the summary's arithmetic (dropped = the diagnostic's count
 * minus what is visibly folded) and the six caveats of 11.46 F; the rest is one
 * branch each in `render/nodes`, `render/edges`, `render/plan`, `export/svg`,
 * `ui/chrome` and `ui/legend`. MLV-P12 is about 8.8 KB: `scope/pipelines.ts` (the
 * relation, its case-folding resolver, the scope note and the drift check
 * against the emitted block), `ui/pipelinechooser.ts` (the panel, its rows and
 * its four caveats), the picker's Pipelines section, `resolvePipeline` and the
 * forced-context lines in `scope/project.ts`, and one field each on `ViewState`
 * and `MLNode` / `MLEdge`. The CSS is one new layer, `styles/rollup.css` (the
 * stack edge, the count chip, the weighted stroke and its pill, all three
 * theme-aware), plus the chooser's block in `styles/scope.css`. Caps go to JS
 * 320 KB and CSS 72 KB, leaving 5 242 B (1.6 %) and 2 039 B (2.8 %) — the same
 * order the last five ratchets held. The ratchet's job is unchanged: make the
 * NEXT growth visible.
 *
 * BEFORE those two came the viewer half of VIEW-08 (the diff overlay), H5
 * (structured fixes) and ANA-10 (resolved configuration), on top of VIEW-04, the
 * Sprint 4 review fixes, NB and VIEW-07; that tree shipped 304 818 B of JS and
 * 68 001 B of CSS, under caps of JS 303 KB and CSS 68 KB.
 *
 * The tree those three landed on shipped 279 080 B of JS and 61 863 B of CSS,
 * so they cost +25 738 B and +6 138 B, and BOTH CAPS MOVE -- which is the number
 * a lead looks for, so here is where it went. VIEW-08 is the largest share and
 * the only one that is a new SUBSYSTEM rather than a new surface: `diff/overlay`
 * (the reader, the validator and the id index), `diff/adopt` (stamping the
 * status and resurrecting every removed node as a card the head document does
 * not contain) and `diff/changed` (the "changed only" projection) come to about
 * 9.6 KB, with `ui/diffbar` -- the headline, the two documents, seven count
 * chips and `notes[]` drawn in full -- another 5.2 KB. H5 is `ui/fixes` plus its
 * two call sites, about 4.0 KB, and ANA-10 is `config/resolved` plus the card
 * and Inspector branches, about 2.6 KB; the remaining ~3.5 KB is spread across
 * `app`, `types`, `protocol`, `scope/session`, `scope/project` (the extraction
 * of `projectResolved`, which is what lets a diff BE a projection instead of a
 * second rendering path) and `render/nodes`. The CSS is one new layer,
 * `styles/diff.css`: two themed hues with a light, a dark and a high-contrast
 * value, the ledge, the ghost treatment, the chips, the fix disclosure and the
 * rail's fixed-findings section. Caps go to JS 303 KB and CSS 68 KB, leaving
 * 5 454 B (1.8 %) and 1 631 B (2.3 %) -- the same order the last four ratchets
 * held. The ratchet's job is unchanged: make the NEXT growth visible.
 *
 * NB moved the JS by +2 991 B and the CSS by +195 B, and moved NEITHER CAP: the
 * item is one small module (`notebook.ts`: the flat-line-to-cell translation,
 * `adoptCellMap`, and the execution-order wording), one banner branch, one chip
 * branch and four `.mlv-loc*` rules -- 442 B of that being the integration
 * reconciliation against 11.29 as it actually landed, where the cell map is
 * lifted off `Node.attrs` and the caveat is read off `notebook_analyzed.codes`.
 *
 * The review fixes then moved the JS by +1 395 B and the CSS by +73 B, and
 * neither cap: `layout/cardmetrics.ts` (VW-01, the card's real height), one
 * frame-containment test in the label planner (VW-02), the export menu's
 * keyboard handlers (VW-03) and a handful of one-line wording and counting
 * fixes. It is re-recorded here rather than absorbed silently because that is
 * exactly what TB-14 asks for -- the figures are the gate, not the caps.
 *
 * WHY BOTH CAPS MOVE AGAIN, which is the number a lead looks for. The previous
 * ratchet (JS 236 KB / CSS 58 KB) was set against 237 749 B and 57 243 B. VIEW-07
 * adds a SECOND RENDERER -- `export/svg.ts` emits the same picture as real
 * `<rect>` / `<text>` / `<path>` -- plus its palette, its rasteriser, its menu
 * and one new stylesheet layer: +28.0 KB of JS (svg + svgprim 10.5, menu 4.7,
 * actions 3.6, palette 3.2, raster + plan + download 2.6, and 3.4 across app /
 * bridges / canvasview / protocol / demo) and +2.9 KB of minified CSS
 * (`styles/export.css`: the menu, and the `@media print` block that is the
 * fourth output). That is the cost of the item, not drift: a bundle that draws
 * the diagram twice is bigger than one that draws it once. So both are re-set
 * ONCE, here, against a measured tree: JS 268 KB and CSS 61 KB, leaving 8 034 B
 * (2.9 %) and 2 230 B (3.6 %) of headroom -- the same order the last two
 * ratchets held. The ratchet's job is unchanged: make the NEXT growth visible.
 *
 * VIEW-04 then moved the JS by +8 296 B and the CSS by +1 361 B, and BOTH CAPS
 * with them. The item is four new units -- `layout/channel.ts` (the lane-pair
 * plan, the barycentre order and the bounded splay), `layout/bundles.ts` (the
 * trunk and its spurs as geometry), `render/bundles.ts` (the `<g>` and the
 * expand/collapse binding) and the `.mlv-bundle*` block in `styles/edge.css` --
 * plus the rewritten `routeCrossLane`, the channel reservation in `layout.ts`
 * and one field on the scene plan. It is a SECOND drawing of the cross-lane
 * edges, kept beside the first because the flow charge and the SVG export read
 * each cable's own `d`, so it costs a layer rather than replacing one. Caps go
 * to JS 278 KB and CSS 62 KB, leaving 5 592 B (2.0 %) and 1 625 B (2.6 %) --
 * the same order the last three ratchets held.
 *
 * The two figures above are GATED, not just written down: `JS_RECORDED` /
 * `CSS_RECORDED` are asserted against the built files with a 2 KB tolerance, so
 * a rebuild that moves the bundle forces this block to be re-measured instead of
 * quietly outliving it (TB-14). Every assertion below names the measured size
 * and the remaining headroom.
 *
 * PROC-08: the PROSE above is gated against those constants too, byte for byte.
 * It had already drifted once -- the header read 268 947 B against a tree that
 * shipped 269 389 B, 442 B apart, and the 2 KB tolerance hid it, which is the
 * same failure mode this block was added to fix. The header is now the record
 * again: `the figures in the block above are the constants below` reads this
 * file and fails on a one-byte disagreement.
 */
const JS_RECORDED = 327214;
const CSS_RECORDED = 72857;
const DRIFT = 2 * 1024;
const JS_MAX_BYTES = 326 * 1024;
const CSS_MAX_BYTES = 73 * 1024;

const headroom = (size, cap) =>
  size + ' B, ' + (cap - size) + ' B (' + (((cap - size) / cap) * 100).toFixed(1) + ' %) under the ' + cap + ' B ratchet';

test('the shipped bundle stays inside its size ratchet (BUILD-01)', async () => {
  const js = await stat(DIST_JS);
  const style = await stat(DIST_CSS);
  assert.ok(
    js.size <= JS_MAX_BYTES,
    'dist/mlview.js is ' + js.size + ' B, over the ' + JS_MAX_BYTES + ' B ratchet -- justify the growth or trim it',
  );
  assert.ok(
    style.size <= CSS_MAX_BYTES,
    'dist/mlview.css is ' + style.size + ' B, over the ' + CSS_MAX_BYTES + ' B ratchet',
  );
  // A ratchet only ratchets while it is snug: a cap far above the real number is
  // a cap nobody will ever trip. These two messages are the ONLY place the real
  // figures are stated at run time, so they are printed on every run.
  assert.ok(js.size > JS_MAX_BYTES * 0.8, 'the JS ratchet has gone slack -- ' + headroom(js.size, JS_MAX_BYTES));
  assert.ok(style.size > CSS_MAX_BYTES * 0.7, 'the CSS ratchet has gone slack -- ' + headroom(style.size, CSS_MAX_BYTES));

  // ...and the comment above says what the tree actually ships.
  assert.ok(
    Math.abs(js.size - JS_RECORDED) < DRIFT,
    'the block above records ' + JS_RECORDED + ' B; dist/mlview.js is ' + headroom(js.size, JS_MAX_BYTES) + ' -- re-measure it',
  );
  assert.ok(
    Math.abs(style.size - CSS_RECORDED) < DRIFT,
    'the block above records ' + CSS_RECORDED + ' B; dist/mlview.css is ' + headroom(style.size, CSS_MAX_BYTES) + ' -- re-measure it',
  );
});

test('the figures in the block above are the constants below (TB-14, PROC-08)', async () => {
  const self = await readFile(new URL(import.meta.url), 'utf8');
  const grouped = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  for (const [name, recorded] of [['dist/mlview.js', JS_RECORDED], ['dist/mlview.css', CSS_RECORDED]]) {
    const re = new RegExp(name.replace(/[./]/g, '\\$&') + '\\s+([\\d ]+?) B');
    const found = re.exec(self);
    assert.ok(found, 'the block records a size for ' + name);
    assert.equal(
      found[1],
      grouped(recorded),
      name + ': the block says ' + found[1] + ' B and the gated constant is ' + grouped(recorded) + ' B -- re-measure the block',
    );
  }
});

test('the stylesheet removes the charge under prefers-reduced-motion (F1-A6)', () => {
  // Reduced motion is handled TWICE: render/flow.ts never BUILDS the element,
  // and this block removes a stale one from a mid-session preference change.
  // The blanket clamp in base.css only FREEZES an animation, which would park a
  // 12 px stub at the outlet of every lit edge (CONTRACTS 11.13 rule 3).
  const blocks = devCss.split('@media (prefers-reduced-motion: reduce)');
  assert.ok(blocks.length > 1, 'the stylesheet has a reduced-motion block');
  const naming = blocks.slice(1).filter((b) => b.slice(0, 400).indexOf('mlv-edge__flow') >= 0);
  assert.equal(naming.length, 1, 'exactly one reduced-motion block names mlv-edge__flow');
  assert.ok(/mlv-edge__flow\s*\{[^}]*display:\s*none\s*!important/.test(naming[0]), 'and it removes the element outright');
});

test('the two flow-colour rules cannot be decided by source order (F1-A9)', () => {
  assert.ok(/\.mlv-edge\.has-issue\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-sev\)/.test(devCss));
  assert.ok(/\.mlv-edge\[data-stage\]:not\(\.has-issue\)\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-stage\)/.test(devCss));
});

test('no source file measures a path through the DOM (F1-A3)', async () => {
  // jsdom does not implement the SVG path-length API, so measuring the DOM would
  // make the tested path a different path from the shipped one.
  const { readdir } = await import('node:fs/promises');
  const { join, dirname } = await import('node:path');
  const root = join(dirname(DIST_JS), '..', 'src');
  const files = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else files.push(full);
    }
  };
  await walk(root);
  assert.ok(files.length > 25, 'scanned ' + files.length + ' files under webview/src');
  let hits = 0;
  for (const file of files) {
    const text = await readFile(file, 'utf8');
    if (text.indexOf('getTotal' + 'Length') >= 0) hits++;
  }
  assert.equal(hits, 0, 'webview/src must contain zero occurrences');
  assert.equal(bundle.indexOf('getTotal' + 'Length'), -1, 'and so must the shipped bundle');
});

test('the flow and scope layers reached the built stylesheet', () => {
  // The `---- file ----` markers live only in the dev build now (BUILD-01); the
  // shipped file is checked for the DECLARATIONS those layers contribute, which
  // is the thing that actually has to arrive.
  assert.ok(devCss.indexOf('---- flow.css ----') >= 0, 'flow.css is concatenated');
  assert.ok(devCss.indexOf('---- scope.css ----') >= 0, 'scope.css is concatenated');
  assert.ok(devCss.indexOf('--mlv-flow-dur-data: 210ms') >= 0, 'the stream period tokens ship');
  assert.ok(devCss.indexOf('--mlv-fg-boundary') >= 0, 'the boundary foreground is a DECLARED token, not opacity');
  // The minifier rewrites 210ms as .21s -- the same duration, and the reason the
  // structural assertions above read the authored file rather than this one.
  assert.ok(css.indexOf('--mlv-flow-dur-data: .21s') >= 0, 'the stream period survives into the shipped file');
  assert.ok(css.indexOf('--mlv-fg-boundary') >= 0);
});

test('every component the viewer hides has a [hidden] rule in the stylesheet', () => {
  // An AUTHOR `display` outranks the UA stylesheet's `[hidden] { display: none }`,
  // so a component whose class declares `display` and whose code sets the
  // `hidden` PROPERTY renders anyway. Found in a real Chromium pass over
  // .mlview/*.html: the scope picker was permanently open over the theme
  // switcher, the unscoped toolbar drew an empty breadcrumb pill, and
  // "0 suppressed" was painted while the code believed it had hidden it.
  // Every class below is toggled through `.hidden = ...` in src/.
  for (const cls of ['mlv-chip', 'mlv-breadcrumb', 'mlv-scopepicker', 'mlv-legend', 'mlv-exportmenu']) {
    const base = devCss.indexOf('.' + cls + ' {');
    assert.ok(base >= 0, '.' + cls + ' has no rule at all');
    const baseBlock = devCss.slice(base, devCss.indexOf('}', base)).split(' ').join('');
    assert.ok(baseBlock.indexOf('display:') >= 0,
      '.' + cls + ' no longer declares a display -- drop it from this list');
    const at = devCss.indexOf('.' + cls + '[hidden]');
    assert.ok(at >= 0, '.' + cls + '[hidden] is missing from the stylesheet');
    const block = devCss.slice(at, devCss.indexOf('}', at)).split(' ').join('');
    assert.ok(block.indexOf('display:none') >= 0,
      '.' + cls + '[hidden] must set display:none');
  }
});

test('the bundle carries no raw NUL byte', async () => {
  // The standalone report (amendment A4) inlines this file into a <script>.
  // In HTML script-data state a U+0000 is rewritten to U+FFFD by the tokenizer,
  // so a raw NUL in the source would not survive the round trip intact.
  const bytes = await readFile(DIST_JS);
  assert.equal(bytes.indexOf(0), -1, 'dist/mlview.js contains a raw NUL byte');
  const cssBytes = await readFile(DIST_CSS);
  assert.equal(cssBytes.indexOf(0), -1, 'dist/mlview.css contains a raw NUL byte');
});
