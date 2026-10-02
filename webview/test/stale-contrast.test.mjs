// The stale marks are graphics, so WCAG 1.4.11 asks for 3:1 against what they sit on (viewer M1
// review, A11Y-2: editorWarning.foreground alone was 2.93:1 on the Light Modern widget
// background). This resolves the colour each stale rule uses, through the tokens, for VS Code's
// default themes, and checks it against the card surface and the canvas background.
//
// jsdom has no cascade for custom properties or color-mix(), so the few tokens involved are
// mapped here to the VS Code colours tokens.css reads, and color-mix(in srgb, ...) is computed.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { WEBVIEW_ROOT } from './helpers.mjs';

const STYLES = join(WEBVIEW_ROOT, 'src', 'styles');
const css = async (name) => (await readFile(join(STYLES, name), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');

/**
 * VS Code 1.139 colours (theme files in extensions/theme-defaults/themes, and the colour
 * registry's default where a theme leaves a key out: no default theme sets
 * editorWarning.foreground). `surface` is what --mlv-surface reads: editorWidget.background, or
 * editor.background in High Contrast (tokens.css); `border` is widget.border, or contrastBorder
 * in High Contrast.
 */
const THEMES = {
  'Light Modern': { warning: '#BF8803', text: '#3B3B3B', surface: '#F8F8F8', bg: '#FFFFFF', border: '#E5E5E5' },
  '2026 Light': { warning: '#BF8803', text: '#202020', surface: '#FAFAFD', bg: '#FFFFFF', border: '#E2E2E5' },
  'Dark Modern': { warning: '#CCA700', text: '#CCCCCC', surface: '#202020', bg: '#1F1F1F', border: '#313131' },
  '2026 Dark': { warning: '#CCA700', text: '#BBBEBF', surface: '#202122', bg: '#121314', border: '#2A2B2C' },
  'Dark High Contrast': { warning: '#FFD370', text: '#FFFFFF', surface: '#000000', bg: '#000000', border: '#6FC3DF' },
  'Light High Contrast': { warning: '#895503', text: '#292929', surface: '#FFFFFF', bg: '#FFFFFF', border: '#0F4A85' },
};

/** The value of `property` in the first rule whose selector list is exactly `selector`, or null. */
function find(text, selector, property) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const rule = new RegExp('(?:^|})\\s*' + escaped + '\\s*\\{([^}]*)\\}', 'm').exec(text);
  if (!rule) return null;
  const decl = new RegExp('(?:^|;)\\s*' + property.replace(/-/g, '\\-') + '\\s*:\\s*([^;]+)').exec(rule[1]);
  return decl ? decl[1].trim() : null;
}

function declaration(text, selector, property) {
  const value = find(text, selector, property);
  assert.ok(value, selector + ' sets no ' + property);
  return value;
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

const hex = (value) => {
  const h = value.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
};

/** A colour expression as [r, g, b], with `vars` for the custom properties it reads. */
function resolve(expr, vars) {
  const text = expr.trim();
  if (text.startsWith('#')) return hex(text);
  if (text.startsWith('var(')) {
    const [name, fallback] = args(text.slice(4, -1));
    if (vars[name] !== undefined) return resolve(vars[name], vars);
    assert.ok(fallback, 'unresolved ' + name);
    return resolve(fallback, vars);
  }
  if (text.startsWith('color-mix(')) {
    const [space, a, b] = args(text.slice('color-mix('.length, -1));
    assert.equal(space, 'in srgb');
    const share = (part) => {
      const m = /\s(\d+(?:\.\d+)?)%$/.exec(part);
      return m ? { color: part.slice(0, m.index), p: Number(m[1]) / 100 } : { color: part, p: null };
    };
    const left = share(a);
    const right = share(b);
    const pl = left.p !== null ? left.p : right.p !== null ? 1 - right.p : 0.5;
    const ca = resolve(left.color, vars);
    const cb = resolve(right.color, vars);
    return ca.map((v, i) => v * pl + cb[i] * (1 - pl));
  }
  throw new Error('cannot resolve ' + text);
}

function luminance([r, g, b]) {
  const lin = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

const contrast = (a, b) => {
  const x = luminance(a);
  const y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

test('the stale marks clear 3:1 against the card surface and the canvas in every default theme', async () => {
  const tokens = await css('tokens.css');
  const node = await css('node.css');
  const edge = await css('edge.css');
  const ink = find(tokens, '.mlv-root', '--mlv-stale-ink');
  const marks = {
    'card corner mark': declaration(node, '.mlv-node__stale', 'color'),
    'card dashed border': declaration(node, '.mlv-node.is-stale', 'border-color'),
    'connection mark ring': declaration(edge, '.mlv-edge__stalebg', 'stroke'),
    'connection mark glyph': declaration(edge, '.mlv-edge__staleicon', 'stroke'),
  };
  const failures = [];
  for (const [theme, c] of Object.entries(THEMES)) {
    const vars = {
      '--vscode-editorWarning-foreground': c.warning,
      '--vscode-editor-foreground': c.text,
      '--mlv-sev-medium': 'var(--vscode-editorWarning-foreground)',
      '--mlv-text': 'var(--vscode-editor-foreground)',
      '--mlv-surface': c.surface,
      '--mlv-bg': c.bg,
      '--mlv-border': c.border,
    };
    if (ink) vars['--mlv-stale-ink'] = ink;
    for (const [mark, expr] of Object.entries(marks)) {
      const colour = resolve(expr, vars);
      for (const [under, ground] of [['surface', c.surface], ['background', c.bg]]) {
        const ratio = contrast(colour, hex(ground));
        if (ratio < 3) failures.push(`${theme}: ${mark} on the ${under} is ${ratio.toFixed(2)}:1`);
      }
    }
  }
  assert.deepEqual(failures, []);
});
