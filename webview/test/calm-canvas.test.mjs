// Viewer M2, roadmap step 8: a calm canvas.
//
// - Phase colour by document ORDER: every authored phase gets a tone, whatever its id.
// - Mark the exceptions: observed claims carry no basis mark; inferred and unresolved cards and
//   connections carry a line style plus a word, never colour alone.
// - Edge dashes encode certainty (solid observed, dashed inferred, dotted unresolved), not kind.
// - Contrast: connections and card borders at 3:1 or better in Dark Modern, Light Modern and
//   Dark High Contrast, computed from the screenshot harness's theme table (VS Code 1.139 values);
//   text on a faded card in exceptions mode stays at 4.5:1 or better.
// - Counts: F1..Fn short labels in document order (the real id stays in tooltips, the Inspector
//   and Refine), and every count names its unit.
// - Motion: VS Code's `vscode-reduce-motion` body class is honoured like the media query, and a
//   flow settles after two passes and can be played again (Shift+A).
//
// These are local jsdom and stylesheet checks. They are not live VS Code, screen-reader or
// usability validation, and the contrast figures are computed from theme values, not pixels.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import vm from 'node:vm';
import { cascadeWinner, loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const STYLES = join(WEBVIEW_ROOT, 'src', 'styles');
const css = async (name) => (await readFile(join(STYLES, name), 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '');

/* ── colour arithmetic ─────────────────────────────────────────────────────────────────────── */

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

function hex(text) {
  const h = text.slice(1);
  const full = h.length <= 4 ? h.split('').map((c) => c + c).join('') : h;
  const rgb = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
  const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
  return [...rgb, a];
}

/** A number expression: a literal, or var() of one. */
function number(expr, vars) {
  const text = expr.trim();
  if (text.startsWith('var(')) {
    const [name, fallback] = args(text.slice(4, -1));
    return number(vars[name] !== undefined ? vars[name] : fallback, vars);
  }
  const n = Number(text);
  assert.ok(Number.isFinite(n), 'not a number: ' + text);
  return n;
}

/** A colour-mix share: `54%` or `calc(var(--x) * 100%)`, as 0..1. */
function share(expr, vars) {
  const text = expr.trim();
  const calc = /^calc\((.+?)\s*\*\s*100%\)$/.exec(text);
  if (calc) return number(calc[1], vars);
  assert.match(text, /^[\d.]+%$/);
  return Number(text.slice(0, -1)) / 100;
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
    const m = /^(.*\S)\s+((?:calc\(.*\))|(?:[\d.]+%))$/.exec(first);
    assert.ok(m, 'colour-mix share in ' + first);
    const p = share(m[2], vars);
    const a = colour(m[1], vars, depth + 1);
    const b = colour(second, vars, depth + 1);
    // Premultiplied interpolation, as CSS Color 5 mixes colours with alpha.
    const alpha = a[3] * p + b[3] * (1 - p);
    if (alpha === 0) return [0, 0, 0, 0];
    const rgb = [0, 1, 2].map((i) => (a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha);
    return [...rgb, alpha];
  }
  throw new Error('cannot resolve colour ' + text);
}

/** `top` painted over the opaque `under`. */
function over(top, under) {
  const a = top[3];
  return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat([1]);
}

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

/* ── the theme table and the stylesheet ────────────────────────────────────────────────────── */

/** Run webview/tools/screenshots/themes.js and read the --vscode-* variables it injects. */
async function harnessThemes() {
  const code = await readFile(join(WEBVIEW_ROOT, 'tools', 'screenshots', 'themes.js'), 'utf8');
  const sandbox = { window: {}, document: null };
  const out = {};
  for (const name of ['dark-modern', 'light-modern', 'hc-dark']) {
    const props = {};
    sandbox.document = {
      documentElement: { style: { setProperty: (k, v) => { props[k] = v; }, background: '' } },
      body: { className: '', setAttribute() {} },
    };
    vm.runInNewContext(code, sandbox);
    const theme = sandbox.window.MLVIEW_SCREENSHOT_APPLY_THEME(name, 'darwin');
    out[name] = { label: theme.label, kind: theme.kind, vars: props };
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

/** Every rule whose selector list contains `needle`, as [selector, declarations text]. */
function rulesWith(text, needle) {
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text))) if (m[1].includes(needle)) out.push([m[1].trim(), m[2]]);
  return out;
}

const LIGHT_ROOT = ':root, .mlv-root[data-theme="light"]';
const DARK_BODY = 'body.vscode-dark, :root[data-theme="dark"], .mlv-root[data-theme="dark"]';
const HC_BODY = 'body.vscode-high-contrast, body.vscode-high-contrast-light, :root[data-theme="hc"], .mlv-root[data-theme="hc"]';

/** The custom properties in force on the canvas for a harness theme, as tokens.css declares them. */
async function themeVars() {
  const tokens = await css('tokens.css');
  const themes = await harnessThemes();
  const light = block(tokens, LIGHT_ROOT);
  const dark = block(tokens, DARK_BODY);
  const hc = block(tokens, HC_BODY);
  const root = block(tokens, '.mlv-root');
  const out = {};
  for (const [name, theme] of Object.entries(themes)) {
    const own = theme.kind === 'dark' ? dark : theme.kind === 'hc' ? hc : {};
    out[name] = { label: theme.label, kind: theme.kind, vars: { ...theme.vars, ...light, ...own, ...root } };
  }
  return out;
}

const SEVERITIES = ['high', 'medium', 'low'];
const PHASES = [0, 1, 2, 3, 4, 5, 6, 7];

test('connections, card borders and phase tones reach 3:1 in Dark Modern, Light Modern and Dark High Contrast', async () => {
  const themes = await themeVars();
  const canvas = await css('canvas.css');
  const node = await css('node.css');
  const edge = await css('edge.css');
  assert.deepEqual(Object.values(themes).map((t) => t.label), ['Dark Modern', 'Light Modern', 'Dark High Contrast']);
  // The stroke is the token at full opacity: no per-kind opacity left to eat the contrast.
  const stroke = block(edge, '.mlv-edge__path, .mlv-legend__edge');
  assert.equal(stroke.stroke, 'var(--mlv-edge)');
  assert.equal(stroke.opacity, undefined);
  const laneBackground = block(canvas, '.mlv-lane').background;
  const cardBackground = block(node, '.mlv-node').background;
  const cardBorder = block(node, '.mlv-node').border.replace(/^1px solid /, '');
  const report = [];
  for (const [name, { label, kind, vars }] of Object.entries(themes)) {
    const bg = colour('var(--mlv-bg)', vars);
    assert.equal(bg[3], 1, label + ': the canvas is opaque');
    const surface = over(colour(cardBackground, vars), bg);
    const lane = over(colour(laneBackground, vars), bg);
    const line = over(colour('var(--mlv-edge)', vars), bg);
    const border = over(colour(cardBorder, vars), bg);
    const checks = [
      ['connection on the canvas', line, bg],
      ['connection on a lane', line, lane],
      ['connection on a card surface', line, surface],
      ['card border on the canvas', border, bg],
      ['card border on its own surface', border, surface],
      ['basis border (dashed/dotted) on a card', over(colour('var(--mlv-text-2)', vars), bg), surface],
    ];
    for (const sev of SEVERITIES) {
      const ink = `color-mix(in srgb, var(--mlv-sev-${sev}) 70%, var(--mlv-text))`;
      checks.push([`basis border on a ${sev} card`, over(colour(ink, vars), bg), surface]);
    }
    const tones = PHASES.map((i) => over(colour(`var(--mlv-phase-${i})`, vars), bg));
    tones.forEach((tone, i) => {
      checks.push([`phase tone ${i} (card rail) on a card`, tone, surface]);
      checks.push([`phase tone ${i} (lane rule) on a lane`, tone, lane]);
    });
    for (const [what, fg, under] of checks) {
      const ratio = contrast(fg, under);
      report.push(`${name} ${what}: ${ratio.toFixed(2)}`);
      assert.ok(ratio >= 3, `${label}: ${what} is ${ratio.toFixed(2)}:1, under 3:1`);
    }
    // Eight distinct tones outside high contrast; high contrast has no hues at all.
    const distinct = new Set(tones.map((t) => t.slice(0, 3).map(Math.round).join(',')));
    assert.equal(distinct.size, kind === 'hc' ? 1 : 8, label + ': phase tones');
  }
  assert.ok(report.length > 0);
});

/* ── viewer M2 live fix 3: phase tones keep clear of the warning and error hues ────────────────── */

/** HSL hue in degrees (NaN for a grey). */
function hslHue([r, g, b]) {
  const [x, y, z] = [r / 255, g / 255, b / 255];
  const max = Math.max(x, y, z);
  const d = max - Math.min(x, y, z);
  if (!d) return NaN;
  const h = max === x ? ((y - z) / d) % 6 : max === y ? (z - x) / d + 2 : (x - y) / d + 4;
  return (h * 60 + 360) % 360;
}

/** OKLab (Björn Ottosson, 2020) of an sRGB colour, for a perceptual hue and distance. */
function oklab([r, g, b]) {
  const lin = (v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [R, G, B] = [lin(r), lin(g), lin(b)];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
const okHue = (c) => {
  const [, a, b] = oklab(c);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
};
const hueGap = (p, q) => {
  const d = Math.abs(p - q) % 360;
  return d > 180 ? 360 - d : d;
};

test('live fix 3: no phase tone is within 30 degrees of hue of the warning, stale or error colour, and the tones stay apart', async () => {
  // Before the fix, phase 3 (tone 2, #C9A56B dark and #8D6E2F light) was 2-14 degrees of hue (HSL
  // and OKLCH) from editorWarning.foreground, so a stale card in phase 3 read as one colour; tone 3
  // (#D98CB3) was 30.4 degrees of HSL hue from Dark Modern's editorError.foreground.
  const themes = await themeVars();
  for (const { label, kind, vars } of Object.values(themes)) {
    const bg = colour('var(--mlv-bg)', vars);
    const refs = {
      'editorWarning.foreground': over(colour('var(--vscode-editorWarning-foreground)', vars), bg),
      'the stale mark (--mlv-stale-ink)': over(colour('var(--mlv-stale-ink)', vars), bg),
      'editorError.foreground': over(colour('var(--vscode-editorError-foreground)', vars), bg),
    };
    const tones = PHASES.map((i) => over(colour(`var(--mlv-phase-${i})`, vars), bg));
    tones.forEach((tone, i) => {
      for (const [name, ref] of Object.entries(refs)) {
        for (const [measure, hue] of [['HSL', hslHue], ['OKLCH', okHue]]) {
          const gap = hueGap(hue(tone), hue(ref));
          assert.ok(gap >= 30, `${label}: phase tone ${i} is ${gap.toFixed(1)} degrees of ${measure} hue from ${name}`);
        }
      }
    });
    if (kind === 'hc') continue;
    // Distinguishable from each other: no two tones closer in OKLab than 0.06 (the M2 palette's
    // closest pairs, among the teal, cyan, slate and blue tones, were 0.067-0.069 apart; the moved
    // tones keep further than that from every other tone).
    let closest = Infinity;
    for (let i = 0; i < tones.length; i++) {
      for (let j = i + 1; j < tones.length; j++) {
        const [p, q] = [oklab(tones[i]), oklab(tones[j])];
        closest = Math.min(closest, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]));
      }
    }
    assert.ok(closest >= 0.06, `${label}: two phase tones are ${closest.toFixed(3)} apart in OKLab`);
  }
});

test('exceptions mode fades observed claims through fill and stroke only, so text keeps 4.5:1', async () => {
  const themes = await themeVars();
  const node = await css('node.css');
  const edge = await css('edge.css');
  // No opacity on anything the toggle fades: opacity would take the text with it.
  for (const [selector, body] of rulesWith(node + edge, '[data-exceptions="on"]')) {
    assert.doesNotMatch(body.replace(/stroke-opacity\s*:[^;]*/g, ''), /(^|[;\s])opacity\s*:/, selector + ' fades with opacity');
  }
  const faded = block(node, '.mlv-canvas[data-exceptions="on"] .mlv-node[data-basis="observed"]');
  const tag = block(node, '.mlv-basis-tag');
  for (const { label, vars } of Object.values(themes)) {
    const bg = colour('var(--mlv-bg)', vars);
    const card = over(colour(faded.background, vars), bg);
    for (const ink of ['var(--mlv-text)', 'var(--mlv-text-2)', 'var(--mlv-text-3)']) {
      const ratio = contrast(over(colour(ink, vars), card), card);
      assert.ok(ratio >= 4.5, `${label}: ${ink} on a faded card is ${ratio.toFixed(2)}:1`);
    }
    const tagBg = over(colour(tag.background, vars), bg);
    assert.ok(contrast(over(colour(tag.color, vars), tagBg), tagBg) >= 4.5, label + ': basis tag text');
  }
});

test('edge dashes encode certainty, not kind; the tags and dashes keep their size on screen', async () => {
  const edge = await css('edge.css');
  const node = await css('node.css');
  assert.match(block(edge, '.mlv-edge[data-basis="inferred"] .mlv-edge__path, .mlv-edge[data-basis="inferred"] .mlv-legend__edge')['stroke-dasharray'], /\/ var\(--mlv-z, 1\)/);
  assert.match(block(edge, '.mlv-edge[data-basis="unresolved"] .mlv-edge__path, .mlv-edge[data-basis="unresolved"] .mlv-legend__edge')['stroke-dasharray'], /\/ var\(--mlv-z, 1\)/);
  for (const [selector, body] of rulesWith(edge, '.mlv-edge--')) {
    assert.doesNotMatch(body, /stroke-dasharray/, selector + ' dashes by kind');
  }
  assert.equal(rulesWith(edge, '[data-basis="observed"]').filter(([, body]) => /stroke-dasharray/.test(body)).length, 0, 'observed is solid');
  assert.match(block(node, '.mlv-node > .mlv-basis-tag').transform, /scale\(calc\(1 \/ var\(--mlv-z, 1\)\)\)/);
});

/* ── the rendered diagram ──────────────────────────────────────────────────────────────────── */

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Calm canvas fixture',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    // Authored ids an analyzer never knew: every phase must still get a colour.
    phases: [{ id: 'ingest', label: 'Ingest' }, { id: 'fit', label: 'Fit the model' }, { id: 'report', label: 'Report' }],
    nodes: [
      { id: 'read', label: 'Read rows', phase: 'ingest', basis: 'observed', evidence: ['e'] },
      { id: 'split', label: 'Split', phase: 'ingest', basis: 'inferred', evidence: ['e'] },
      { id: 'loop', label: 'Epochs', phase: 'fit', kind: 'group', basis: 'inferred', evidence: [] },
      { id: 'step', label: 'Step', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e'] },
      { id: 'eval', label: 'Eval', phase: 'fit', parent: 'loop', basis: 'unresolved', evidence: ['e'] },
      { id: 'save', label: 'Save', phase: 'report', basis: 'observed', evidence: ['e'] },
    ],
    edges: [
      { id: 'c-read-split', source: 'read', target: 'split', label: 'rows', kind: 'data', basis: 'observed', evidence: ['e'] },
      { id: 'c-split-step', source: 'split', target: 'step', label: 'batches', kind: 'call', basis: 'inferred', evidence: ['e'] },
      { id: 'c-step-eval', source: 'step', target: 'eval', label: 'weights', kind: 'state', basis: 'unresolved', evidence: ['e'] },
      { id: 'c-eval-save', source: 'eval', target: 'save', label: 'metrics', kind: 'control', basis: 'observed', evidence: ['e'] },
    ],
    findings: [
      { id: 'f-alpha', title: 'Alpha', message: 'm', severity: 'low', nodeIds: ['read'], edgeIds: [], basis: 'observed', evidence: ['e'] },
      { id: 'f-beta', title: 'Beta', message: 'm', severity: 'high', nodeIds: ['read'], edgeIds: ['c-read-split'], basis: 'inferred', evidence: ['e'] },
      { id: 'f-gamma', title: 'Gamma', message: 'm', severity: 'medium', nodeIds: ['read', 'save'], edgeIds: [], basis: 'unresolved', evidence: ['e'] },
    ],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: ['one'] },
    ...overrides,
  };
}

async function mount(document = doc(), { bodyClass = '' } = {}) {
  const ctx = await loadBundle();
  if (bodyClass) ctx.document.body.classList.add(bodyClass);
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), document, bridge);
  const q = (selector) => ctx.document.querySelector(selector);
  const card = (id) => q(`.mlv-node[data-node-id="${id}"], .mlv-group[data-node-id="${id}"]`);
  const edge = (id) => q(`.mlv-edge[data-edge-id="${id}"]`);
  const key = (value, init = {}) => app.view.canvasEl.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...init }));
  return { ...ctx, bridge, app, q, card, edge, key, canvas: app.view.canvasEl };
}

test('A11Y-2 (viewer M2 review): Refine… draws button.foreground on button.background at 4.5:1, and keeps an edge in high contrast', async () => {
  // jsdom lets the later rule win whatever its specificity, so the winner is resolved by hand: the
  // reset `.mlv-root button { color: inherit }` outranked `.mlv-btn--primary` and the label drew
  // the header's text colour on the accent (2.82:1 Dark Modern, 1.78:1 Light Modern).
  const dist = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const themes = await themeVars();
  const ctx = await mount();
  const refine = ctx.q('.mlv-workflow__refine');
  assert.ok(refine.classList.contains('mlv-btn--primary'));
  const color = cascadeWinner(dist, refine, 'color');
  assert.equal(color.value, 'var(--mlv-on-accent)', 'the winning colour rule is ' + color.selector);
  assert.equal(cascadeWinner(dist, refine, 'background').value, 'var(--mlv-accent-solid)');
  for (const { label, vars } of Object.values(themes)) {
    const ratio = contrast(colour('var(--mlv-on-accent)', vars), colour('var(--mlv-accent-solid)', vars));
    assert.ok(ratio >= 4.5, `${label}: Refine… label ${ratio.toFixed(2)}:1`);
  }
  // High contrast: the accent is the canvas colour, so the border must be the theme's contrast edge.
  ctx.document.getElementById('mlview-root').setAttribute('data-theme', 'hc');
  const border = cascadeWinner(dist, refine, 'border-color');
  const hc = themes['hc-dark'].vars;
  const edge = colour(border.value, hc);
  assert.ok(contrast(edge, colour('var(--mlv-bg)', hc)) >= 3, `Dark High Contrast: the button edge (${border.value}) is visible`);
  ctx.app.destroy();
});

test('observed claims carry no basis mark; inferred and unresolved ones carry a line style and a word', async () => {
  const ctx = await mount();
  // Cards: the tag is on the exceptions only, with its meaning in the tooltip and the name.
  assert.equal(ctx.card('read').querySelector('.mlv-basis-tag'), null);
  assert.equal(ctx.card('step').querySelector('.mlv-basis-tag'), null);
  assert.equal(ctx.card('split').getAttribute('data-basis'), 'inferred');
  assert.equal(ctx.card('split').querySelector('.mlv-basis-tag').textContent, 'inferred');
  assert.equal(ctx.card('eval').querySelector('.mlv-basis-tag').textContent, '? unresolved');
  assert.match(ctx.card('eval').querySelector('.mlv-basis-tag').title, /^Unresolved: the evidence does not settle this claim/);
  assert.match(ctx.card('split').getAttribute('aria-label'), /inferred, not observed/);
  assert.match(ctx.card('eval').getAttribute('aria-label'), /unresolved/);
  assert.doesNotMatch(ctx.card('read').getAttribute('aria-label'), /observed|basis/);
  // A group carries the same tag in its header, and its frame is dashed only for its own basis.
  assert.equal(ctx.card('loop').getAttribute('data-basis'), 'inferred');
  assert.equal(ctx.card('loop').querySelector('.mlv-group__header .mlv-basis-tag').textContent, 'inferred');
  // No card anywhere still prints a basis chip or a basis= attribute row.
  assert.doesNotMatch(ctx.q('.mlv-layer--nodes').textContent, /basis|observed/);
  // Connections: the basis is on the <g> for the dash; the label carries the authored text only.
  assert.deepEqual(['c-read-split', 'c-split-step', 'c-step-eval'].map((id) => ctx.edge(id).getAttribute('data-basis')), ['observed', 'inferred', 'unresolved']);
  for (const label of ctx.document.querySelectorAll('.mlv-edge-label')) assert.doesNotMatch(label.textContent, /observed|inferred|unresolved/);
  const name = (id) => ctx.edge(id).querySelector('.mlv-edge__hit').getAttribute('aria-label');
  assert.doesNotMatch(name('c-read-split'), /observed/);
  assert.match(name('c-split-step'), /inferred, not observed/);
  assert.match(name('c-step-eval'), /unresolved/);
  // The kind is still told in words: the hover card and the Inspector say it.
  ctx.app.select({ kind: 'edge', id: 'c-split-step' }, { tab: 'inspector' });
  assert.equal(ctx.q('.mlv-insp__edgekind').textContent, 'call');
  ctx.app.destroy();
});

test('every phase gets a colour by its place in the document, not by its id', async () => {
  const many = doc({
    phases: Array.from({ length: 10 }, (_, i) => ({ id: 'p-' + 'abcdefghij'[i], label: 'Phase ' + i })),
    nodes: Array.from({ length: 10 }, (_, i) => ({ id: 'n' + i, label: 'Step ' + i, phase: 'p-' + 'abcdefghij'[i], basis: 'observed', evidence: ['e'] })),
    edges: [{ id: 'c', source: 'n0', target: 'n9', label: 'x', basis: 'observed', evidence: ['e'] }],
    findings: [],
  });
  const ctx = await mount(many);
  for (let i = 0; i < 10; i++) {
    const lane = ctx.q(`.mlv-lane[data-lane-id="p-${'abcdefghij'[i]}"]`);
    assert.equal(lane.getAttribute('data-stage'), 'p-' + 'abcdefghij'[i], 'data-stage stays (the golden hashes it)');
    assert.equal(lane.getAttribute('data-phase-index'), String(i));
    assert.equal(lane.getAttribute('data-phase-tone'), String(i % 8), 'past eight phases the tones repeat');
    assert.equal(ctx.card('n' + i).getAttribute('data-phase-tone'), String(i % 8));
  }
  assert.equal(ctx.edge('c').getAttribute('data-phase-index'), '0', 'a connection takes its source phase');
  const nodeCss = await css('node.css');
  for (const i of PHASES) assert.equal(block(nodeCss, `[data-phase-tone="${i}"]`)['--mlv-stage'], `var(--mlv-phase-${i})`);
  // The legend says what the colour means, and that it means nothing else.
  assert.match(ctx.q('[data-legend-row="phase:order"]').nextElementSibling.textContent, /by its place in the document.*It means nothing else/);
  ctx.app.destroy();
});

test('the SVG export draws the same marks and the same phase tones as the screen', async () => {
  const ctx = await mount();
  ctx.q('.mlv-btn--more').click();
  ctx.q('[data-export-action="svg"]').click();
  const frame = ctx.bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
  assert.match(svg, /data-node-id="split"[^>]*data-basis="inferred"/);
  assert.match(svg, /<g data-basis-tag="inferred">.*?>inferred</);
  assert.match(svg, /<g data-basis-tag="unresolved">.*?>\? unresolved</);
  assert.equal((svg.match(/data-basis-tag="/g) || []).length, 3, 'split, loop and eval; no observed card is tagged');
  assert.match(svg, /data-basis="inferred"><path [^>]*stroke-dasharray="6 4"/);
  assert.match(svg, /data-basis="unresolved"><path [^>]*stroke-dasharray="1\.5 3\.5"/);
  assert.doesNotMatch(svg, /data-basis="observed"><path [^>]*stroke-dasharray/);
  // The lane rule takes the tone of the lane's position, as tokens.css declares it (light theme).
  const tokens = block(await css('tokens.css'), LIGHT_ROOT);
  ['ingest', 'fit', 'report'].forEach((lane, i) => {
    const group = new RegExp(`<g data-lane-id="${lane}" data-stage="${lane}" data-phase-index="${i}">(.*?)</g>`).exec(svg);
    assert.ok(group, lane + ' lane');
    assert.match(group[1], new RegExp(`fill="${tokens['--mlv-phase-' + i]}"`, 'i'), lane + ' accent rule');
  });
  ctx.app.destroy();
});

test('finding badges use F1..Fn in document order; the real id stays in tooltips, the Selection pane and Refine', async () => {
  const ctx = await mount();
  // `read` carries all three findings: two labels, then "+1".
  const badge = ctx.card('read').querySelector('.mlv-badge');
  assert.equal(badge.querySelector('.mlv-badge__ids').textContent, 'F1 F2 +1');
  assert.equal(badge.getAttribute('aria-label'), 'Findings F1, F2 and F3, highest severity high');
  assert.equal(ctx.card('save').querySelector('.mlv-badge__ids').textContent, 'F3');
  assert.match(ctx.edge('c-read-split').querySelector('.mlv-edge-marker').getAttribute('aria-label'), /^Finding F2 on this connection, highest severity high$/);
  // The Findings list and the Selection pane print the short label beside the real id.
  ctx.app.setRailTab('issues');
  const row = ctx.q('.mlv-issue[data-issue-id="f-gamma"]');
  assert.equal(row.querySelector('.mlv-issue__short').textContent, 'F3');
  assert.match(row.textContent, /f-gamma/);
  ctx.app.select({ kind: 'node', id: 'save' }, { tab: 'inspector' });
  const head = ctx.q('.mlv-insp__issue[data-issue-id="f-gamma"] .mlv-insp__issue-head');
  assert.equal(head.querySelector('.mlv-insp__short').textContent, 'F3');
  // Viewer M2 live fix: the real id is on its own line under the title, not in the head row.
  assert.equal(head.querySelector('.mlv-mono'), null);
  assert.equal(ctx.q('.mlv-insp__issue[data-issue-id="f-gamma"] .mlv-insp__issue-id').textContent, 'f-gamma');
  // Refine and Challenge name the finding by its real id, never by the short label.
  ctx.app.select({ kind: 'issue', id: 'f-gamma' }, { tab: 'issues' });
  ctx.q('.mlv-workflow__refine').click();
  ctx.q('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  const request = ctx.bridge.posted.findLast((m) => m.type === 'refineWorkflow');
  assert.deepEqual(JSON.parse(JSON.stringify(request.selection)), { kind: 'issue', id: 'f-gamma' });
  assert.doesNotMatch(JSON.stringify(request), /"F3"/);
  // A new revision that reorders the findings renumbers them; the ids do not move.
  const next = doc({ revision: { id: 'r2' } });
  next.findings = next.findings.slice().reverse();
  ctx.bridge.send({ v: 1, type: 'workflow', document: next });
  ctx.app.setRailTab('issues');
  assert.equal(ctx.q('.mlv-issue[data-issue-id="f-gamma"] .mlv-issue__short').textContent, 'F1');
  assert.equal(ctx.card('save').querySelector('.mlv-badge__ids').textContent, 'F1');
  ctx.app.destroy();
});

test('every count names its unit', async () => {
  const ctx = await mount();
  const text = (selector) => ctx.q(selector).textContent.replace(/\s+/g, ' ').trim();
  // Inferred or unresolved claims, by unit: split, loop, eval; two connections; two findings.
  assert.equal(text('.mlv-chip--exceptions'), '7 not observed (3 steps, 2 connections, 2 findings)');
  // Under 1000 px the bracket folds away (chrome.css); the accessible name keeps the whole count.
  assert.equal(ctx.q('.mlv-chip--exceptions').getAttribute('aria-label'), '7 not observed (3 steps, 2 connections, 2 findings)');
  assert.equal(ctx.q('.mlv-chip--exceptions .mlv-chip__detail').textContent, ' (3 steps, 2 connections, 2 findings)');
  // Viewer M2: the status bar counts steps and connections once, and the limitations with the
  // coverage status; the findings are counted on the severity toggles only.
  assert.equal(text('.mlv-status__counts'), '6 steps · 4 connections');
  assert.match(text('.mlv-status__coverage'), /^Coverage: \w+ · 1 limitation$/);
  assert.doesNotMatch(text('.mlv-status'), /findings?\b/);
  assert.equal(text('.mlv-chip--btn[data-severity="high"] .mlv-chip__count'), '1');
  assert.equal(text('.mlv-lane[data-lane-id="ingest"] .mlv-lane__count'), '2 steps');
  assert.equal(text('.mlv-lane[data-lane-id="report"] .mlv-lane__count'), '1 step');
  assert.equal(text('.mlv-group[data-node-id="loop"] .mlv-group__count'), '2 steps');
  assert.equal(ctx.q('.mlv-chip--btn[data-severity="high"]').getAttribute('aria-label'), '1 high finding. Press to hide them.');
  ctx.app.setRailTab('issues');
  assert.deepEqual(Array.from(ctx.document.querySelectorAll('[data-severity-section] .mlv-rail__heading'), (h) => h.textContent), ['high · 1 finding', 'medium · 1 finding', 'low · 1 finding']);
  ctx.app.view.toggleCollapse('loop');
  assert.equal(text('.mlv-node[data-node-id="loop"] .mlv-chip'), '2 steps');
  // The legend lists the kinds in use with how many connections have each.
  assert.match(text('[data-legend-row="edge:kinds"] + dd'), /Connections in this diagram, by kind: call 1, control 1, data 1, state 1\./);
  ctx.app.destroy();
});

test('the "not observed" toggle fades the observed claims, and is hidden when there is nothing to single out', async () => {
  const ctx = await mount();
  const chip = ctx.q('.mlv-chip--exceptions');
  assert.equal(chip.hidden, false);
  assert.equal(chip.getAttribute('aria-pressed'), 'false');
  chip.click();
  assert.equal(ctx.canvas.getAttribute('data-exceptions'), 'on');
  assert.equal(ctx.q('.mlv-chip--exceptions').getAttribute('aria-pressed'), 'true');
  assert.match(ctx.app.liveEl.textContent, /Observed claims faded/);
  ctx.q('.mlv-chip--exceptions').click();
  assert.equal(ctx.canvas.hasAttribute('data-exceptions'), false);
  ctx.app.destroy();

  const plain = doc();
  for (const item of [...plain.nodes, ...plain.edges, ...plain.findings]) item.basis = 'observed';
  const all = await mount(plain);
  assert.equal(all.q('.mlv-chip--exceptions').hidden, true, 'no "0 not observed" mark: it would read as a check result');
  assert.equal(all.document.querySelectorAll('.mlv-basis-tag').length, 0);
  all.app.destroy();
});

test('--mlv-z follows the zoom in buckets, so constant-size marks restyle only at a bucket edge', async () => {
  const ctx = await mount();
  const z = () => ctx.canvas.style.getPropertyValue('--mlv-z');
  ctx.app.view.viewport.set({ zoom: 1 });
  assert.equal(z(), '1');
  ctx.app.view.viewport.set({ zoom: 0.59 });
  assert.equal(z(), '0.62', 'the nearest bucket on a log scale');
  ctx.app.view.viewport.set({ zoom: 0.3 });
  assert.equal(z(), '0.32');
  ctx.app.view.viewport.set({ zoom: 2.2 });
  assert.equal(z(), '2');
  ctx.app.destroy();
});

/* ── motion ────────────────────────────────────────────────────────────────────────────────── */

const MOVING = '.mlv-edge__flow, .mlv-edge__charge';

test('a focus-mode stream runs a finite number of passes, settles, and Shift+A plays it again', async () => {
  const ctx = await mount();
  ctx.app.select({ kind: 'node', id: 'step' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  const flowing = () => Array.from(ctx.document.querySelectorAll('.mlv-edge.is-flowing'));
  assert.ok(flowing().length >= 2, 'precondition: the lineage streams');
  for (const g of flowing()) {
    const iter = g.style.getPropertyValue('--mlv-flow-iter');
    assert.match(iter, /^[1-9]\d*$/, 'a whole number of passes, never infinite');
    assert.ok(g.querySelector('.mlv-edge__flow'));
  }
  // The browser fires animationend when a cable's passes are done (jsdom never animates).
  for (const part of ctx.document.querySelectorAll('.mlv-edge__flow')) part.dispatchEvent(new ctx.window.Event('animationend'));
  assert.equal(ctx.document.querySelectorAll(MOVING).length, 0, 'nothing moves after the passes');
  for (const g of flowing()) {
    assert.ok(g.classList.contains('is-flow-settled'));
    assert.ok(g.querySelector('.mlv-edge__dir'), 'a static direction mark replaces the motion');
  }
  assert.equal(ctx.canvas.getAttribute('data-flow-settled'), 'true');
  assert.ok(ctx.canvas.classList.contains('is-focusing'), 'focus mode itself stays on');
  // Shift+A runs it again from the first pass; plain `a` still turns the layer off.
  ctx.key('A', { shiftKey: true });
  assert.ok(ctx.document.querySelectorAll('.mlv-edge__flow').length >= 2);
  assert.equal(ctx.canvas.hasAttribute('data-flow-settled'), false);
  assert.match(ctx.app.liveEl.textContent, /Playing the connection flow again/);
  ctx.key('a');
  assert.equal(ctx.canvas.getAttribute('data-flow'), 'off');
  ctx.app.toggleShortcuts(true);
  assert.match(ctx.q('.mlv-sheet').textContent, /Shift\+A.*Play the connection flow again/);
  ctx.app.destroy();
});

test('a hovered connection pulses twice, not for as long as the pointer rests', async () => {
  const ctx = await mount();
  const route = ctx.app.view.routes.find((r) => r.id === 'c-split-step');
  ctx.app.view.flow.pulse(route);
  const motions = Array.from(ctx.edge('c-split-step').querySelectorAll('animateMotion'));
  assert.ok(motions.length >= 1);
  for (const m of motions) {
    assert.equal(m.getAttribute('repeatCount'), '2');
    assert.equal(m.getAttribute('fill'), 'freeze');
  }
  assert.equal(ctx.edge('c-split-step').style.getPropertyValue('--mlv-flow-iter'), '2');
  ctx.app.destroy();
});

test("VS Code's vscode-reduce-motion body class means reduced motion, at mount and when it changes", async () => {
  const still = await mount(doc(), { bodyClass: 'vscode-reduce-motion' });
  assert.equal(still.app.view.flow.motion, 'reduced');
  still.app.select({ kind: 'node', id: 'step' });
  still.app.view.toggleFocusMode(still.app.selection);
  assert.equal(still.canvas.getAttribute('data-flow'), 'static');
  assert.equal(still.document.querySelectorAll(MOVING).length, 0, 'no motion is built, only the static marks');
  assert.ok(still.document.querySelectorAll('.mlv-edge.is-flowing .mlv-edge__dir').length >= 1);
  still.key('A', { shiftKey: true });
  assert.equal(still.document.querySelectorAll(MOVING).length, 0, 'there is nothing to replay');
  still.app.destroy();

  const ctx = await mount();
  assert.equal(ctx.app.view.flow.motion, 'full');
  ctx.document.body.classList.add('vscode-reduce-motion');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(ctx.app.view.flow.motion, 'reduced', 'VS Code flipped its Reduce Motion setting');
  ctx.document.body.classList.remove('vscode-reduce-motion');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(ctx.app.view.flow.motion, 'full');
  ctx.app.destroy();

  // The stylesheet honours the class too, for the CSS transitions and the flow layer.
  const base = await css('base.css');
  const clamp = block(base, 'body.vscode-reduce-motion .mlv-root *, body.vscode-reduce-motion .mlv-root *::before, body.vscode-reduce-motion .mlv-root *::after');
  assert.match(clamp['animation-duration'], /^0\.01ms/);
  assert.match(clamp['transition-duration'], /^0\.01ms/);
  const flow = await css('flow.css');
  assert.match(block(flow, 'body.vscode-reduce-motion .mlv-edge__flow, body.vscode-reduce-motion .mlv-edge__charge').display, /^none/);
});
