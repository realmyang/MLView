// Viewer M4: muted text (--mlv-text-3) is muted, and readable, in every shipped theme.
//
// Light Modern sets descriptionForeground to its text colour (#3B3B3B), and --mlv-text-3 read
// descriptionForeground, so muted text was the text colour there. Light+'s descriptionForeground
// (#717171) is muted but 4.40:1 on its widget background. In a light theme muted text is now the
// card surface darkened to 38%; dark themes keep descriptionForeground, high contrast its text.
//
// The theme values are the screenshot harness's table (webview/tools/screenshots/themes.js), VS
// Code 1.139's colours. jsdom has no cascade for custom properties or color-mix(), so the tokens
// are resolved here from tokens.css the way calm-canvas.test.mjs does it. The figures are computed
// from theme values, not measured in pixels, and are not a live VS Code or screen-reader check.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import vm from 'node:vm';
import { build } from 'esbuild';
import { WEBVIEW_ROOT } from './helpers.mjs';

const STYLES = join(WEBVIEW_ROOT, 'src', 'styles');
const css = async (name) => (await readFile(join(STYLES, name), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');

/* ── colour arithmetic (as calm-canvas.test.mjs) ───────────────────────────────────────────── */

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

function hex(text) {
  const h = text.slice(1);
  const full = h.length <= 4 ? h.split('').map((c) => c + c).join('') : h;
  const rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
  return [...rgb, a];
}

/** A colour expression as [r, g, b, a], with `vars` for the custom properties it reads. */
function colour(expr, vars, depth = 0) {
  assert.ok(depth < 40, 'var() loop at ' + expr);
  const text = expr.trim();
  if (text === 'transparent') return [0, 0, 0, 0];
  if (text.startsWith('#')) return hex(text);
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
    const alpha = a[3] * p + b[3] * (1 - p);
    if (alpha === 0) return [0, 0, 0, 0];
    const rgb = [0, 1, 2].map((i) => (a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha);
    return [...rgb, alpha];
  }
  throw new Error('cannot resolve colour ' + text);
}

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

const toHex = (c) => '#' + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();

/* ── the harness themes and the stylesheet ─────────────────────────────────────────────────── */

const SHIPPED = ['dark-modern', 'dark-plus', 'light-modern', 'light-plus', 'hc-dark', 'hc-light', 'dark-2026', 'light-2026'];

async function harnessThemes() {
  const code = await readFile(join(WEBVIEW_ROOT, 'tools', 'screenshots', 'themes.js'), 'utf8');
  const sandbox = { window: {}, document: null };
  const out = {};
  for (const name of SHIPPED) {
    const props = {};
    let bodyClass = '';
    sandbox.document = {
      documentElement: { style: { setProperty: (k, v) => { props[k] = v; }, background: '' } },
      body: { set className(v) { bodyClass = v; }, get className() { return bodyClass; }, setAttribute() {} },
    };
    vm.runInNewContext(code, sandbox);
    const theme = sandbox.window.MLVIEW_SCREENSHOT_APPLY_THEME(name, 'darwin');
    out[name] = { label: theme.label, kind: theme.kind, bodyClass, vars: props };
  }
  return out;
}

/** The declarations of the rule whose selector list is exactly `selector` (comments stripped). */
function block(text, selector) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text))) {
    if (m[1].trim().replace(/\s+/g, ' ') !== selector) continue;
    const decls = {};
    for (const part of m[2].split(';')) {
      const i = part.indexOf(':');
      if (i > 0) decls[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
    return decls;
  }
  throw new Error('no rule ' + selector);
}

const LIGHT_ROOT = ':root, .mlv-root[data-theme="light"]';
const DARK_BODY = 'body.vscode-dark, :root[data-theme="dark"], .mlv-root[data-theme="dark"]';
const DARK_MEDIA = ':root:not([data-theme="light"]):not([data-theme="hc"]), .mlv-root:not([data-theme="light"]):not([data-theme="hc"])';
const HC_BODY = 'body.vscode-high-contrast, body.vscode-high-contrast-light, :root[data-theme="hc"], .mlv-root[data-theme="hc"]';

async function themeVars() {
  const tokens = await css('tokens.css');
  const light = block(tokens, LIGHT_ROOT);
  const dark = block(tokens, DARK_BODY);
  const hc = block(tokens, HC_BODY);
  const root = block(tokens, '.mlv-root');
  const out = {};
  for (const [name, theme] of Object.entries(await harnessThemes())) {
    const own = theme.kind === 'dark' ? dark : theme.kind === 'hc' ? hc : {};
    out[name] = { ...theme, vars: { ...theme.vars, ...light, ...own, ...root } };
  }
  return out;
}

/**
 * What muted text sits on: the canvas, the card / rail / header / status bar / tooltip / legend
 * surface, a hovered or selected Outline row and a quote (surface-2, painted over the surface), and
 * a lane's header plate. Read from the shipped stylesheet, not restated.
 */
async function grounds() {
  const node = await css('node.css');
  const rail = await css('rail.css');
  const chrome = await css('chrome.css');
  const canvas = await css('canvas.css');
  const surface = { card: block(node, '.mlv-node').background, rail: block(rail, '.mlv-rail').background, header: block(chrome, '.mlv-header').background, status: block(chrome, '.mlv-status').background };
  for (const [where, value] of Object.entries(surface)) assert.equal(value, 'var(--mlv-surface)', where + ' background');
  const hover = block(rail, '.mlv-outline__row:hover').background;
  const quote = block(rail, '.mlv-quote__text').background;
  assert.deepEqual([hover, quote], ['var(--mlv-surface-2)', 'var(--mlv-surface-2)']);
  assert.equal(block(rail, '.mlv-outline__stage').color, 'var(--mlv-text-3)');
  assert.equal(block(rail, '.mlv-quote__ln').color, 'var(--mlv-text-3)');
  assert.equal(block(canvas, '.mlv-lane__count').color, 'var(--mlv-text-3)');
  return { plate: block(canvas, '.mlv-lane__header').background };
}

/* ── the tests ─────────────────────────────────────────────────────────────────────────────── */

test('the harness table carries the six themes the viewer is checked in, and 2026 Dark and Light', async () => {
  const themes = await harnessThemes();
  assert.deepEqual(Object.values(themes).map((t) => t.label), ['Dark Modern', 'Dark+', 'Light Modern', 'Light+', 'Dark High Contrast', 'Light High Contrast', 'Dark 2026', 'Light 2026']);
  // VS Code stamps both classes on <body> for Light High Contrast, so the high contrast tokens apply.
  assert.equal(themes['hc-light'].bodyClass, 'vscode-high-contrast-light vscode-high-contrast');
  // The cause: Light Modern's descriptionForeground is its text colour.
  const lm = themes['light-modern'].vars;
  assert.equal(lm['--vscode-descriptionForeground'], lm['--vscode-foreground']);
  assert.equal(lm['--vscode-descriptionForeground'], lm['--vscode-editor-foreground']);
});

test('muted text is the card surface darkened in light themes, descriptionForeground in dark ones, the text colour in high contrast', async () => {
  const tokens = await css('tokens.css');
  assert.equal(block(tokens, LIGHT_ROOT)['--mlv-text-3'], 'color-mix(in srgb, var(--mlv-surface) 38%, #000000)');
  assert.equal(block(tokens, DARK_BODY)['--mlv-text-3'], 'var(--vscode-descriptionForeground, #969DAD)');
  assert.equal(block(tokens, DARK_MEDIA)['--mlv-text-3'], 'var(--vscode-descriptionForeground, #969DAD)');
  assert.equal(block(tokens, HC_BODY)['--mlv-text-3'], 'var(--vscode-editor-foreground, #FFFFFF)');
  // Secondary text is not part of this change.
  assert.equal(block(tokens, LIGHT_ROOT)['--mlv-text-2'], 'var(--vscode-descriptionForeground, #5A6070)');
});

test('muted text clears 4.5:1 on the canvas, cards, the rail, the header, hovered rows, quotes and lane headers', async (t) => {
  const themes = await themeVars();
  const { plate } = await grounds();
  const failures = [];
  for (const [name, { label, vars }] of Object.entries(themes)) {
    const bg = colour('var(--mlv-bg)', vars);
    const surface = over(colour('var(--mlv-surface)', vars), bg);
    const on = {
      canvas: bg,
      'card, rail, header': surface,
      'hovered row, quote': over(colour('var(--mlv-surface-2)', vars), surface),
      'lane header': over(colour(plate, vars), surface),
    };
    const ink = colour('var(--mlv-text-3)', vars);
    const ratios = Object.fromEntries(Object.entries(on).map(([where, ground]) => [where, contrast(over(ink, ground), ground)]));
    t.diagnostic(`${label}: --mlv-text-3 ${toHex(over(ink, surface))} ` + Object.entries(ratios).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(', '));
    // Dark 2026 (VS Code 1.139's default dark theme) keeps its descriptionForeground, #8C8C8C,
    // which is 3.80:1 on a hovered row and 4.34:1 on a lane header; its secondary text is the same
    // colour. Not changed here: the owner's list of themes for this fix did not include it.
    const required = name === 'dark-2026' ? ['canvas', 'card, rail, header'] : Object.keys(on);
    for (const where of required) if (ratios[where] < 4.5) failures.push(`${label}: muted text on the ${where} is ${ratios[where].toFixed(2)}:1`);
  }
  assert.deepEqual(failures, []);
});

test('muted text is visibly muted outside high contrast, and the text colour in high contrast', async () => {
  const themes = await themeVars();
  for (const [name, { label, kind, vars }] of Object.entries(themes)) {
    const bg = colour('var(--mlv-bg)', vars);
    const surface = over(colour('var(--mlv-surface)', vars), bg);
    const text = over(colour('var(--mlv-text)', vars), surface);
    const muted = over(colour('var(--mlv-text-3)', vars), surface);
    if (kind === 'hc') {
      assert.equal(toHex(muted), toHex(over(colour('var(--vscode-editor-foreground)', vars), surface)), label + ': the text colour');
      continue;
    }
    // At most 70% of the text colour's contrast on the card surface. Dark Modern's own
    // descriptionForeground sits at 59%; Light Modern's was 100% before viewer M4.
    const share = contrast(muted, surface) / contrast(text, surface);
    assert.ok(share <= 0.7, `${label}: muted text has ${(share * 100).toFixed(0)}% of the text colour's contrast`);
    if (name === 'light-modern') assert.equal(toHex(muted), '#5E5E5E');
    if (name === 'light-plus') assert.equal(toHex(muted), '#5C5C5C');
  }
});

let paletteModule = null;
function palette() {
  if (!paletteModule) {
    paletteModule = build({
      entryPoints: [join(WEBVIEW_ROOT, 'src', 'export', 'palette.ts')],
      bundle: true, format: 'esm', platform: 'neutral', write: false, logLevel: 'silent',
    }).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));
  }
  return paletteModule;
}

test('the SVG export resolves light muted text the same way', async () => {
  const { EXPORT_PALETTES, TEXT3_LIGHT_MIX, mixHex, resolvePalette } = await palette();
  const tokens = await css('tokens.css');
  const share = Number(/var\(--mlv-surface\) ([\d.]+)%/.exec(block(tokens, LIGHT_ROOT)['--mlv-text-3'])[1]) / 100;
  assert.equal(TEXT3_LIGHT_MIX, share, 'the export mixes at the stylesheet\'s share');
  assert.equal(EXPORT_PALETTES.light.text3, mixHex(EXPORT_PALETTES.light.surface, '#000000', share));
  assert.equal(EXPORT_PALETTES.dark.text3, '#969DAD', 'dark keeps its table value');
  // A live light root: the computed custom property is the color-mix() with its var() substituted.
  const rootWith = (values) => {
    const style = { getPropertyValue: (name) => values[name] || '' };
    const root = { ownerDocument: { defaultView: { getComputedStyle: () => style } } };
    return root;
  };
  const live = resolvePalette(rootWith({ '--mlv-surface': '#f8f8f8', '--mlv-text-3': 'color-mix(in srgb, #f8f8f8 38%, #000000)' }), 'light');
  assert.equal(live.text3, '#5E5E5E');
  // An engine that hands back the token unresolved: derived from the resolved surface instead.
  const unresolved = resolvePalette(rootWith({ '--mlv-surface': '#F3F3F3', '--mlv-text-3': 'color-mix(in srgb, var(--mlv-surface) 38%, #000000)' }), 'light');
  assert.equal(unresolved.text3, '#5C5C5C');
});
