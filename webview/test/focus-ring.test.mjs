// The focus ring of the review walk's bar shows where the keyboard is, so WCAG 1.4.11 asks for 3:1
// against what it lies on. The ring is drawn 2 px off its button (base.css), so the bar's ground
// is on both sides of it; a button of the bar's last row has the ring's lower edge on the pane
// under the bar. The bar draws it in --mlv-focus-strong, since the theme's focusBorder alone can
// fall under 3:1 there. This resolves the ring's colour and the two grounds through the tokens,
// for the eight themes of the screenshot harness's table (webview/tools/screenshots/themes.js),
// and checks the ratio.
//
// jsdom has no cascade for custom properties or color-mix(), so the tokens are resolved here from
// tokens.css. The ratios are computed from the table's values.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import vm from 'node:vm';
import { WEBVIEW_ROOT } from './helpers.mjs';

const STYLES = join(WEBVIEW_ROOT, 'src', 'styles');
const css = async (name) => (await readFile(join(STYLES, name), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');

const THEMES = ['dark-modern', 'dark-plus', 'dark-2026', 'light-modern', 'light-plus', 'light-2026', 'hc-dark', 'hc-light'];

/** Each harness theme as { label, kind, vars }: the --vscode-* properties its table sets. */
async function harnessThemes() {
  const code = await readFile(join(WEBVIEW_ROOT, 'tools', 'screenshots', 'themes.js'), 'utf8');
  const sandbox = { window: {}, document: null };
  const out = {};
  for (const name of THEMES) {
    const vars = {};
    sandbox.document = {
      documentElement: { style: { setProperty: (k, v) => { vars[k] = v; }, background: '' } },
      body: { className: '', setAttribute() {} },
    };
    vm.runInNewContext(code, sandbox);
    const theme = sandbox.window.MLVIEW_SCREENSHOT_APPLY_THEME(name, 'darwin');
    out[name] = { label: theme.label, kind: theme.kind, vars };
  }
  return out;
}

/** Every rule as { selector, decls } (comments already stripped; a rule inside @media included). */
function rules(text) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text))) {
    const decls = {};
    for (const part of m[2].split(';')) {
      const i = part.indexOf(':');
      if (i > 0) decls[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
    out.push({ selector: m[1].trim().replace(/\s+/g, ' '), decls });
  }
  return out;
}

/** The declarations of the first rule whose selector list is exactly `selector`. */
function block(text, selector) {
  const rule = rules(text).find((r) => r.selector === selector);
  if (!rule) throw new Error('no rule ' + selector);
  return rule.decls;
}

/** Split `a, b, c` at top-level commas. */
function args(text) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '(') depth++;
    else if (text[i] === ')') depth--;
    else if (text[i] === ',' && depth === 0) {
      out.push(text.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(text.slice(start).trim());
  return out;
}

/** A colour expression as [r, g, b, a], with `vars` for the custom properties it reads. */
function colour(expr, vars, depth = 0) {
  assert.ok(depth < 40, 'var() loop at ' + expr);
  const text = expr.trim();
  if (text.startsWith('#')) {
    const h = text.slice(1);
    const full = h.length <= 4 ? h.split('').map((c) => c + c).join('') : h;
    const rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
    return [...rgb, full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1];
  }
  if (text.startsWith('var(')) {
    const [name, fallback] = args(text.slice(4, -1));
    if (vars[name] !== undefined) return colour(vars[name], vars, depth + 1);
    assert.ok(fallback, 'unresolved ' + name);
    return colour(fallback, vars, depth + 1);
  }
  if (text.startsWith('color-mix(')) {
    const [space, first, second] = args(text.slice(10, -1));
    assert.equal(space, 'in srgb');
    const m = /^(.*\S)\s+([\d.]+)%$/.exec(first);
    assert.ok(m, 'colour-mix share in ' + first);
    const p = Number(m[2]) / 100;
    const a = colour(m[1], vars, depth + 1);
    const b = colour(second, vars, depth + 1);
    // Premultiplied interpolation, as CSS Color 5 mixes colours with alpha (Dark 2026's focusBorder).
    const alpha = a[3] * p + b[3] * (1 - p);
    return [...[0, 1, 2].map((i) => (a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha), alpha];
  }
  throw new Error('cannot resolve colour ' + text);
}

/** `top` painted over the opaque `under`. */
const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);

function luminance(rgb) {
  const c = rgb.slice(0, 3).map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const LIGHT_ROOT = ':root, .mlv-root[data-theme="light"]';
const DARK_BODY = 'body.vscode-dark, :root[data-theme="dark"], .mlv-root[data-theme="dark"]';
const HC_BODY = 'body.vscode-high-contrast, body.vscode-high-contrast-light, :root[data-theme="hc"], .mlv-root[data-theme="hc"]';

test('the focus ring of the review walk\'s bar clears 3:1 against the bar and against the pane under it, in the eight harness themes', async (t) => {
  const tokens = await css('tokens.css');
  const workflow = await css('workflow.css');
  // One rule draws every ring in the bar: no focus rule of the workflow stylesheet sets its own.
  assert.equal(block(await css('base.css'), '.mlv-root :focus-visible').outline, '2px solid var(--mlv-focus)');
  const own = rules(workflow).filter((r) => /:focus/.test(r.selector) && Object.keys(r.decls).some((k) => k.startsWith('outline')));
  assert.deepEqual(own.map((r) => r.selector), []);
  const bar = block(workflow, '.mlv-walkbar');
  const light = block(tokens, LIGHT_ROOT);
  const root = block(tokens, '.mlv-root');
  const kinds = { dark: block(tokens, DARK_BODY), hc: block(tokens, HC_BODY) };

  const themes = await harnessThemes();
  assert.deepEqual(Object.keys(themes), THEMES);
  const failures = [];
  for (const [name, theme] of Object.entries(themes)) {
    // The custom properties in force on .mlv-root. A property the bar sets is computed from what
    // the bar inherits, so the var() in it reads these.
    const vars = { ...theme.vars, ...light, ...(kinds[theme.kind] || {}), ...root };
    const ring = colour(bar['--mlv-focus'] || 'var(--mlv-focus)', vars);
    const canvas = colour('var(--mlv-bg)', vars);
    const grounds = {
      'the bar': over(colour(bar.background, vars), canvas),
      'the pane under the bar': over(colour('var(--mlv-surface)', vars), canvas),
    };
    const ratios = [];
    for (const [what, ground] of Object.entries(grounds)) {
      const ratio = contrast(over(ring, ground), ground);
      ratios.push(`${what} ${ratio.toFixed(2)}:1`);
      if (ratio < 3) failures.push(`${theme.label}: the ring on ${what} is ${ratio.toFixed(2)}:1`);
    }
    t.diagnostic(`${theme.label}: ${ratios.join(', ')}`);
  }
  assert.deepEqual(failures, []);
});
