// Bundle hygiene over the BUILT files (VIEWUI-17), plus the stylesheet rules
// that source comments promise (RENDER-12, RENDER-13, RENDER-21, CRIT-10).
// Every displayed string is model-authored data, so the bundle must never
// parse markup or code from strings, and the viewer makes no network request.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DIST_JS, WEBVIEW_ROOT } from './helpers.mjs';

const js = readFileSync(DIST_JS, 'utf8');
const css = readFileSync(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');

test('the built bundle has no markup, code-from-string or dynamic-import sink', () => {
  const forbidden = [
    ['innerHTML', /innerHTML/],
    ['outerHTML', /outerHTML/],
    ['insertAdjacentHTML', /insertAdjacentHTML/],
    ['document.write', /document\.write/],
    ['eval(', /(?<![\w$.])eval\s*\(/],
    ['new Function', /new\s+Function\b/],
    ['import(', /(?<![\w$.])import\s*\(/],
  ];
  for (const [name, pattern] of forbidden) assert.doesNotMatch(js, pattern, 'dist/mlview.js contains ' + name);
});

test('the built bundle carries no absolute URL literal', () => {
  // The SVG and XLink namespaces are assembled at runtime from parts (dom.ts).
  assert.doesNotMatch(js, /https?:\/\//i);
});

test('the flow layer never measures a DOM path', () => {
  // render/flow.ts: length is the polyline sum; jsdom has no path measurement.
  assert.doesNotMatch(js, /getTotalLength|getPointAtLength/);
});

test('no keyframe animates a calc() expression', () => {
  // styles/flow.css: Chromium cannot interpolate a var()-derived calc().
  const keyframes = css.match(/@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g) || [];
  assert.ok(keyframes.length > 0, 'the stylesheet has keyframes to check');
  for (const block of keyframes) assert.doesNotMatch(block, /calc\(/, block.slice(0, 80));
});

test('the authored panel uses defined tokens, styles the host banner, and precedes the print block', () => {
  assert.doesNotMatch(css, /--mlv-muted|--mlv-warning/, 'workflow.css must not use undefined tokens');
  const banner = css.indexOf('#mlview-authored-error');
  assert.ok(banner >= 0, 'the host banner is styled');
  assert.match(css.slice(banner, css.indexOf('}', banner)), /white-space:\s*pre-wrap/);
  const print = css.lastIndexOf('@media print');
  assert.ok(print > banner, 'export.css, which owns the print block, is the last layer');
  const tokens = readFileSync(join(WEBVIEW_ROOT, 'src', 'styles', 'tokens.css'), 'utf8');
  for (const token of ['--mlv-text-2', '--mlv-sev-medium']) {
    assert.equal((tokens.match(new RegExp(token + ':', 'g')) || []).length >= 3, true, token + ' is defined for every theme');
  }
});

test('the build writes no readable dev stylesheet', () => {
  const build = readFileSync(join(WEBVIEW_ROOT, 'build.mjs'), 'utf8');
  assert.doesNotMatch(build, /writeFile\([^)]*mlview\.dev\.css/);
});
