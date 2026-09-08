/**
 * Contrast is a build gate (R4.8). Every declared foreground/background token
 * pair must clear WCAG AA 4.5:1 for text, in light and in dark, using the
 * LITERAL fallbacks in tokens.css — the values a plain browser actually paints
 * when no --vscode-* variable is present.
 *
 * The pairs come from `@contrast: --fg on --bg` annotations in tokens.css, so
 * adding a colour without declaring its pairing is a review-visible omission
 * rather than a silent gap.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { WEBVIEW_ROOT, DIST_CSS_DEV } from './helpers.mjs';

const TOKENS_PATH = join(WEBVIEW_ROOT, 'src', 'styles', 'tokens.css');
const tokensCss = await readFile(TOKENS_PATH, 'utf8');
const distCss = await readFile(DIST_CSS_DEV, 'utf8');

/** Split a stylesheet into { selector, body } blocks, honouring one nesting level. */
function blocks(css) {
  const out = [];
  let depth = 0;
  let start = 0;
  let selectorStart = 0;
  for (let i = 0; i < css.length; i++) {
    const ch = css[i];
    if (ch === '{') {
      if (depth === 0) {
        out.push({ selector: css.slice(selectorStart, i).trim(), from: i + 1 });
        start = i + 1;
      }
      depth++;
    } else if (ch === '}') {
      depth--;
      if (depth === 0) {
        const block = out[out.length - 1];
        block.body = css.slice(start, i);
        selectorStart = i + 1;
      }
    }
  }
  return out.filter((b) => b.body !== undefined);
}

function declarations(body) {
  const map = new Map();
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let m;
  while ((m = re.exec(body)) !== null) map.set(m[1], m[2].trim());
  return map;
}

/** The literal fallback is the LAST hex in the declaration. */
function literalOf(value) {
  const hexes = value.match(/#[0-9a-fA-F]{3,8}/g);
  return hexes ? hexes[hexes.length - 1] : null;
}

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
}

function parseTheme(css, selectorTest) {
  const all = blocks(stripComments(css));
  const map = new Map();
  for (const block of all) {
    if (!selectorTest(block.selector)) continue;
    for (const [k, v] of declarations(block.body)) map.set(k, v);
  }
  return map;
}

function nestedRootIn(css) {
  // the @media (prefers-color-scheme: dark) branch
  const at = css.indexOf('@media (prefers-color-scheme: dark)');
  if (at < 0) return new Map();
  const open = css.indexOf('{', at);
  let depth = 0;
  let end = open;
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') {
      depth--;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  return declarations(css.slice(open + 1, end));
}

const clean = stripComments(tokensCss);
/** Selector lists are matched part by part: `:root, .mlv-root[data-theme="light"]`. */
function hasPart(selector, part) {
  return selector.split(',').some((s) => s.trim() === part);
}

const light = parseTheme(tokensCss, (sel) => hasPart(sel, ':root'));
const darkExplicit = parseTheme(tokensCss, (sel) => sel.indexOf('[data-theme="dark"]') >= 0);
const darkMedia = nestedRootIn(clean);

const pairs = [];
{
  const re = /@contrast:\s*(--[a-z0-9-]+)\s+on\s+(--[a-z0-9-]+)/gi;
  let m;
  while ((m = re.exec(tokensCss)) !== null) pairs.push([m[1], m[2]]);
}

function srgb(channel) {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function luminance(hex) {
  let h = hex.slice(1);
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
}

function ratio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

function resolve(theme, token) {
  const value = theme.get(token) || light.get(token);
  assert.ok(value, 'token ' + token + ' is declared');
  const hex = literalOf(value);
  assert.ok(hex, 'token ' + token + ' has a literal fallback (got: ' + value + ')');
  return hex;
}

test('tokens.css declares at least a dozen contrast pairs', () => {
  assert.ok(pairs.length >= 12, 'found ' + pairs.length + ' @contrast annotations');
});

test('every declared text pair clears 4.5:1 in LIGHT', () => {
  for (const [fg, bg] of pairs) {
    const r = ratio(resolve(light, fg), resolve(light, bg));
    assert.ok(r >= 4.5, 'light ' + fg + ' on ' + bg + ' = ' + r.toFixed(2) + ':1');
  }
});

test('every declared text pair clears 4.5:1 in DARK', () => {
  const dark = new Map(light);
  for (const [k, v] of darkExplicit) dark.set(k, v);
  for (const [fg, bg] of pairs) {
    const r = ratio(resolve(dark, fg), resolve(dark, bg));
    assert.ok(r >= 4.5, 'dark ' + fg + ' on ' + bg + ' = ' + r.toFixed(2) + ':1');
  }
});

test('the two dark branches (media query and data-theme) declare the same values', () => {
  for (const [token, value] of darkExplicit) {
    if (!darkMedia.has(token)) {
      assert.fail('the prefers-color-scheme branch is missing ' + token);
    }
    assert.equal(darkMedia.get(token), value, token + ' drifted between the dark branches');
  }
  assert.equal(darkMedia.size, darkExplicit.size, 'the dark branches declare the same token set');
});

test('stage hues clear 3:1 against their own theme background (graphics)', () => {
  const dark = new Map(light);
  for (const [k, v] of darkExplicit) dark.set(k, v);
  const stages = ['config', 'data', 'preprocess', 'model', 'objective', 'train', 'eval', 'deliver', 'unknown'];
  for (const theme of [light, dark]) {
    const bg = resolve(theme, '--mlv-bg');
    for (const stage of stages) {
      const hue = resolve(theme, '--mlv-stage-' + stage);
      const r = ratio(hue, bg);
      assert.ok(r >= 3, 'stage ' + stage + ' rail is ' + r.toFixed(2) + ':1 against the canvas');
    }
  }
});

test('every --vscode-* reference in tokens.css carries a literal fallback', () => {
  const re = /var\(\s*(--vscode-[a-zA-Z0-9-]+)\s*([^)]*)\)/g;
  let m;
  let checked = 0;
  while ((m = re.exec(clean)) !== null) {
    checked++;
    assert.ok(m[2].trim().length > 0, m[1] + ' has no fallback');
  }
  assert.ok(checked > 30, 'checked ' + checked + ' theme variables');
});

test('the built stylesheet contains the token layer verbatim', () => {
  assert.ok(distCss.indexOf('--mlv-sev-medium-ink: #3A2500') >= 0, 'the built stylesheet carries the tokens');
  assert.ok(distCss.indexOf('---- tokens.css ----') >= 0, 'tokens are the first concatenated layer');
});

test('every theme block is keyed on the mount root as well as :root (MLV-R1-004)', () => {
  // The renderer stamps data-theme on the element it mounts into, never on
  // <html> — a block keyed only on :root can never fire in the standalone report.
  const all = blocks(stripComments(tokensCss)).map((b) => b.selector);
  for (const kind of ['dark', 'hc']) {
    const rootBlock = all.find((sel) => hasPart(sel, ':root[data-theme="' + kind + '"]'));
    assert.ok(rootBlock, 'a :root[data-theme="' + kind + '"] block exists');
    assert.ok(
      hasPart(rootBlock, '.mlv-root[data-theme="' + kind + '"]'),
      'the ' + kind + ' block is also keyed on .mlv-root[data-theme="' + kind + '"] (got: ' + rootBlock + ')',
    );
  }
  const lightBlock = all.find((sel) => hasPart(sel, ':root'));
  assert.ok(hasPart(lightBlock, '.mlv-root[data-theme="light"]'), 'light is restated on the mount root');
  assert.ok(clean.indexOf('.mlv-root:not([data-theme="light"]):not([data-theme="hc"])') >= 0,
    'the prefers-color-scheme branch also targets the mount root');
  // and it survives the concatenation into dist/mlview.css
  assert.ok(distCss.indexOf('.mlv-root[data-theme="hc"]') >= 0, 'dist carries the mount-root hc block');
});

test('the page-fill chain ships in the bundled stylesheet (MLV-R1-001)', () => {
  assert.ok(distCss.indexOf('html.mlv-fills-page') >= 0, 'dist declares the html/body height chain');
  const at = distCss.indexOf('html.mlv-fills-page');
  const block = distCss.slice(at, distCss.indexOf('}', at));
  for (const decl of ['height: 100%', 'margin: 0', 'padding: 0']) {
    assert.ok(block.indexOf(decl) >= 0, 'the page-fill chain declares ' + decl);
  }
});

test('the toolbar wraps and the rail becomes an overlay on narrow viewports (MLV-R1-009)', () => {
  const toolbar = blocks(stripComments(distCss)).find((b) => b.selector === '.mlv-toolbar');
  assert.ok(toolbar, '.mlv-toolbar is declared');
  assert.ok(toolbar.body.indexOf('flex-wrap: wrap') >= 0, 'the toolbar wraps instead of clipping its controls');
  assert.ok(distCss.indexOf('@media (max-width: 900px)') >= 0, 'the 900 px rail breakpoint exists');
});
