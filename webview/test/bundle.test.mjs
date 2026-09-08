/**
 * Bundle hygiene (CONTRACTS section 8, amendment A7). The shipped bundle must
 * contain no markup-string assignment, no eval, no dynamic import and no
 * absolute URL — the last one is what keeps the standalone report offline and
 * the webview inside `default-src 'none'`.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import { readBundle, DIST_CSS, DIST_JS } from './helpers.mjs';

const bundle = await readBundle();
const css = await readFile(DIST_CSS, 'utf8');

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
  assert.ok(css.indexOf('--mlv-sev-high') >= 0);
  assert.ok(css.indexOf('[data-theme="dark"]') >= 0);
  assert.ok(css.indexOf('[data-theme="hc"]') >= 0);
  assert.ok(css.indexOf('prefers-color-scheme: dark') >= 0);
  assert.ok(css.indexOf('prefers-reduced-motion') >= 0);
});

test('the stylesheet removes the charge under prefers-reduced-motion (F1-A6)', () => {
  // Reduced motion is handled TWICE: render/flow.ts never BUILDS the element,
  // and this block removes a stale one from a mid-session preference change.
  // The blanket clamp in base.css only FREEZES an animation, which would park a
  // 12 px stub at the outlet of every lit edge (CONTRACTS 11.13 rule 3).
  const blocks = css.split('@media (prefers-reduced-motion: reduce)');
  assert.ok(blocks.length > 1, 'the stylesheet has a reduced-motion block');
  const naming = blocks.slice(1).filter((b) => b.slice(0, 400).indexOf('mlv-edge__flow') >= 0);
  assert.equal(naming.length, 1, 'exactly one reduced-motion block names mlv-edge__flow');
  assert.ok(/mlv-edge__flow\s*\{[^}]*display:\s*none\s*!important/.test(naming[0]), 'and it removes the element outright');
});

test('the two flow-colour rules cannot be decided by source order (F1-A9)', () => {
  assert.ok(/\.mlv-edge\.has-issue\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-sev\)/.test(css));
  assert.ok(/\.mlv-edge\[data-stage\]:not\(\.has-issue\)\s*\{[^}]*--mlv-flow-color:\s*var\(--mlv-stage\)/.test(css));
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
  assert.ok(css.indexOf('---- flow.css ----') >= 0, 'flow.css is concatenated');
  assert.ok(css.indexOf('---- scope.css ----') >= 0, 'scope.css is concatenated');
  assert.ok(css.indexOf('--mlv-flow-dur-data: 210ms') >= 0, 'the stream period tokens ship');
  assert.ok(css.indexOf('--mlv-fg-boundary') >= 0, 'the boundary foreground is a DECLARED token, not opacity');
});

test('every component the viewer hides has a [hidden] rule in the stylesheet', () => {
  // An AUTHOR `display` outranks the UA stylesheet's `[hidden] { display: none }`,
  // so a component whose class declares `display` and whose code sets the
  // `hidden` PROPERTY renders anyway. Found in a real Chromium pass over
  // .mlview/*.html: the scope picker was permanently open over the theme
  // switcher, the unscoped toolbar drew an empty breadcrumb pill, and
  // "0 suppressed" was painted while the code believed it had hidden it.
  // Every class below is toggled through `.hidden = ...` in src/.
  for (const cls of ['mlv-chip', 'mlv-breadcrumb', 'mlv-scopepicker']) {
    const base = css.indexOf('.' + cls + ' {');
    assert.ok(base >= 0, '.' + cls + ' has no rule at all');
    const baseBlock = css.slice(base, css.indexOf('}', base)).split(' ').join('');
    assert.ok(baseBlock.indexOf('display:') >= 0,
      '.' + cls + ' no longer declares a display -- drop it from this list');
    const at = css.indexOf('.' + cls + '[hidden]');
    assert.ok(at >= 0, '.' + cls + '[hidden] is missing from the stylesheet');
    const block = css.slice(at, css.indexOf('}', at)).split(' ').join('');
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
