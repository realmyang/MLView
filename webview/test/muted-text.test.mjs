// Viewer M4: secondary text (--mlv-text-2) and muted text (--mlv-text-3) clear 4.5:1 on every
// background they are drawn on, in every shipped theme, keep their order (the text colour at least
// as strong as secondary text, secondary text at least as strong as muted text), and keep a
// visible distance from the text: on the CIE L* line from the text to the card surface, muted text
// uses most of the room the theme has there at 4.5:1, at 25% or more of the way, and secondary text
// sits a step from each, wherever the theme has room for three levels; otherwise secondary text is
// muted text (two levels, Dark 2026).
//
// History. Both tokens were VS Code's descriptionForeground. Light Modern sets it to its text
// colour (#3B3B3B), so secondary and muted text were not quieter than the text; Light+'s (#717171)
// is 4.40:1 on its widget background; Dark 2026's (#8C8C8C, VS Code 1.139's default dark theme) is
// about 3.8:1 on a hovered row. The first M4 fix darkened the card surface for light-theme muted
// text only. The second mixed the text into the card surface at 90% and 80% in sRGB in every theme,
// which cleared 4.5:1 but left secondary text 9-12% of the L* distance from the text (viewer M4
// verification, F3). The third mixed in CIE Lab, 87% and 74% in light themes (13% and 26% of the L*
// distance), which left Light+'s near-black text near-black steps (#000000, #202020, #3B3B3B) and
// moved Light 2026's secondary text by 1% (viewer M4 hierarchy verification, V1). Now a light theme
// mixes muted text 74% in Lab and lifts it to L* 42 where that is lighter, with secondary text
// halfway to it; a dark theme steps 9 and 18 L* below the text, never under L* 64.5 and never above
// the text, and joins secondary to muted text where the text is under L* 79.5 (relative colour
// syntax, each rule gated by @supports on its own expression; an engine without it keeps the plain
// light mix and a two-level dark color-mix). High contrast keeps the text colour.
//
// The matrix is theme x token x background. The themes are the screenshot harness's table
// (webview/tools/screenshots/themes.js, VS Code 1.139's colours). The backgrounds are read from the
// shipped stylesheet: a census classifies every background the stylesheets paint, and the stacks
// below say what is painted over what (a hovered row is --mlv-surface-2 over the card surface; a
// lane header is its plate over the lane's wash over the canvas). Secondary text is held to every
// stack; muted text to the stacks its selectors sit on, and a second census keeps that list
// complete. A --mlv-surface-2 box inside a --mlv-surface-2 container (a chip in a hovered row) is
// composited with the fill the stylesheet gives it there (RAISED_INK, with its own census). jsdom
// has no cascade for custom properties, color-mix() or relative colours, so the tokens are resolved
// here from tokens.css (test/colour-lab.mjs for Lab and the CSS math). The figures are computed
// from theme values, not measured in pixels, and are not a live VS Code or screen-reader check.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import vm from 'node:vm';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { WEBVIEW_ROOT } from './helpers.mjs';
import { labToSrgb, lstar, mixLab, relativeLab, splitSupports } from './colour-lab.mjs';

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
    assert.ok(space === 'in srgb' || space === 'in lab', space);
    const m = /^(.*\S)\s+((?:calc\(.*\))|(?:[\d.]+%))$/.exec(first);
    assert.ok(m, 'colour-mix share in ' + first);
    const p = share(m[2], vars);
    const a = colour(m[1], vars, depth + 1);
    const b = colour(second, vars, depth + 1);
    if (space === 'in lab') return mixLab(a, b, p);
    // Premultiplied interpolation, as CSS Color 5 mixes colours with alpha.
    const alpha = a[3] * p + b[3] * (1 - p);
    if (alpha === 0) return [0, 0, 0, 0];
    const rgb = [0, 1, 2].map((i) => (a[i] * a[3] * p + b[i] * b[3] * (1 - p)) / alpha);
    return [...rgb, alpha];
  }
  // A dark theme's secondary and muted text: lab(from var(--mlv-text) <L> a b).
  if (text.startsWith('lab(from ')) return relativeLab(text, (origin) => colour(origin, vars, depth + 1));
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

/** The declarations of the rule whose selector list is exactly `selector`. */
function block(text, selector) {
  const rule = rules(text).find((r) => r.selector === selector);
  if (!rule) throw new Error('no rule ' + selector);
  return rule.decls;
}

const LIGHT_ROOT = ':root, .mlv-root[data-theme="light"]';
const DARK_BODY = 'body.vscode-dark, :root[data-theme="dark"], .mlv-root[data-theme="dark"]';
const DARK_MEDIA = ':root:not([data-theme="light"]):not([data-theme="hc"]), .mlv-root:not([data-theme="light"]):not([data-theme="hc"])';
const HC_BODY = 'body.vscode-high-contrast, body.vscode-high-contrast-light, :root[data-theme="hc"], .mlv-root[data-theme="hc"]';

/** A light theme's secondary text (halfway to muted text) and muted text without relative colour syntax. */
const LIGHT_SECONDARY = 'color-mix(in lab, var(--mlv-text) 50%, var(--mlv-text-3))';
const LIGHT_MIX = 'color-mix(in lab, var(--mlv-text) 74%, var(--mlv-surface))';
/** A light theme's muted text, in the @supports block: the mix, lifted to L* 42 where that is lighter. */
const LIGHT_MUTED_L = 'max(l, 42)';
const LIGHT_MUTED = `lab(from ${LIGHT_MIX} ${LIGHT_MUTED_L} a b)`;
/** A dark theme's secondary and muted text without relative colour syntax. */
const DARK_FALLBACK = 'color-mix(in lab, var(--mlv-text) 80%, var(--mlv-surface))';
/** A dark theme's, in the @supports block: steps below the text's L*, a floor, the text as a cap. */
const DARK_SECONDARY_L = 'min(l, max(64.5, l - 9 - clamp(0, (79.5 - l) * 100, 100)))';
const DARK_MUTED_L = 'min(l, max(64.5, l - 18))';
const DARK_SECONDARY = `lab(from var(--mlv-text) ${DARK_SECONDARY_L} a b)`;
const DARK_MUTED = `lab(from var(--mlv-text) ${DARK_MUTED_L} a b)`;

/** tokens.css without its @supports blocks, and the light and dark rule blocks in it. */
async function tokenBlocks() {
  const { blocks, rest } = splitSupports(await css('tokens.css'));
  assert.equal(blocks.length, 2, 'two @supports blocks in tokens.css: the light rule and the dark rule');
  const [light, dark] = blocks;
  return { rest, light, dark };
}

/**
 * The custom properties in force for each harness theme. `engine` is 'relative' for an engine
 * with relative colour syntax (Chromium 119+, every VS Code the extension supports), which applies
 * tokens.css's @supports blocks, or 'fallback' for one without, which does not.
 */
async function themeVars(engine = 'relative') {
  const { rest, light: lightRule, dark: darkRule } = await tokenBlocks();
  const relative = engine === 'relative';
  const light = { ...block(rest, LIGHT_ROOT), ...(relative ? block(lightRule.body, LIGHT_ROOT) : {}) };
  const dark = { ...block(rest, DARK_BODY), ...(relative ? block(darkRule.body, DARK_BODY) : {}) };
  const hc = block(rest, HC_BODY);
  const root = block(rest, '.mlv-root');
  const out = {};
  for (const [name, theme] of Object.entries(await harnessThemes())) {
    const own = theme.kind === 'dark' ? dark : theme.kind === 'hc' ? hc : {};
    out[name] = { ...theme, vars: { ...theme.vars, ...light, ...own, ...root } };
  }
  return out;
}

/** Every stylesheet but the tokens, as one text. */
async function sheets() {
  const names = (await readdir(STYLES)).filter((n) => n.endsWith('.css') && n !== 'tokens.css').sort();
  assert.ok(names.length >= 10, 'the stylesheets are found');
  return (await Promise.all(names.map(css))).join('\n');
}

/*
 * Every background the stylesheets paint, by value. A ground is a layer text can sit on; the rest
 * paint no text (a swatch, a rail, a grip, a dot). A new background value fails the census until
 * it is added here, so the matrix below cannot miss a ground.
 */
const PAINTS = {
  'none': null,
  'transparent': null,
  'var(--mlv-bg)': 'canvas',
  'var(--mlv-surface)': 'surface',
  'var(--mlv-surface-2)': 'raised',
  'var(--mlv-surface-2, var(--vscode-editorWidget-background, transparent))': 'raised',
  'color-mix(in srgb, var(--mlv-text) calc(var(--mlv-lane-tint) * 100%), transparent)': 'lane',
  'color-mix(in srgb, var(--mlv-text) calc(var(--mlv-group-tint) * 100%), transparent)': 'group',
  'color-mix(in srgb, var(--mlv-text) 5%, var(--mlv-surface))': 'plate',
  'color-mix(in srgb, var(--mlv-accent) 12%, transparent)': 'in view',
  'color-mix(in srgb, var(--mlv-stage, var(--mlv-text-2)) 7%, var(--mlv-surface))': 'block',
  'var(--vscode-menu-background, var(--mlv-surface))': 'menu',
  'repeating-linear-gradient(135deg, transparent 0 7px, color-mix(in srgb, var(--mlv-text) 8%, transparent) 7px 8px)': 'hatch',
  'repeating-linear-gradient(135deg, transparent 0 4px, color-mix(in srgb, var(--mlv-text) 8%, transparent) 4px 5px)': 'hatch',
  // The hovered menu item: its secondary text takes the menu's selection colour (a test below).
  'var(--vscode-menu-selectionBackground, var(--mlv-surface-2))': 'no secondary or muted text: a hovered menu item',
  'var(--mlv-stage, var(--mlv-stage-unknown))': 'no text: a phase swatch or rail',
  'color-mix(in srgb, var(--mlv-stage, var(--mlv-stage-unknown)) 30%, var(--mlv-bg))': 'no text: a faded card\'s phase rail',
  'var(--mlv-accent)': 'no text: the side panel\'s grip, hovered',
  'var(--mlv-accent-solid)': 'no secondary or muted text: a primary button (--mlv-on-accent)',
  'var(--vscode-menu-separatorBackground, var(--mlv-border))': 'no text: a menu separator',
  'var(--mlv-text-3)': 'no text: the provenance dot',
  'var(--mlv-stale-ink)': 'no text: the stale provenance dot',
  'var(--mlv-border-strong)': 'no text: the bottom sheet\'s grip',
  'var(--mlv-scrim)': 'no text: the scrim behind the bottom sheet',
  'radial-gradient(var(--mlv-canvas-dot) 1px, transparent 1px)': 'no text: the canvas\'s 1 px dot grid',
  'linear-gradient(to bottom, var(--mlv-surface) 30%, transparent), linear-gradient(to top, var(--mlv-surface) 30%, transparent), linear-gradient(to bottom, var(--mlv-border-strong), transparent), linear-gradient(to top, var(--mlv-border-strong), transparent)': 'no text: the legend\'s 8 px scroll shadows',
};

/**
 * What is painted over what, bottom first. A name in a stack is a ground from PAINTS (`badge` is
 * the bundle badge's SVG box, `block N` the phase overview's block for phase N, `kbd` the key cap
 * VS Code's default webview stylesheet paints under a <kbd> that has no background of its own).
 */
const STACKS = {
  'canvas': ['canvas'],
  'lane': ['canvas', 'lane'],
  'group on a lane': ['canvas', 'lane', 'group'],
  'surface (card, side panel, header, status bar, tooltip, phase index)': ['canvas', 'surface'],
  'hatched (unresolved) card': ['canvas', 'surface', 'hatch'],
  'raised on a surface (hovered or selected row, quote, chip)': ['canvas', 'surface', 'raised'],
  'raised on the canvas (walk bar, hovered phase pill)': ['canvas', 'raised'],
  'raised on a lane (hovered group header, group count)': ['canvas', 'lane', 'raised'],
  'lane header': ['canvas', 'lane', 'plate'],
  'phase index row in view': ['canvas', 'surface', 'in view'],
  'menu': ['canvas', 'menu'],
  'bundle badge on a lane': ['canvas', 'lane', 'badge'],
  'key hint on the canvas (the overview\'s Esc)': ['canvas', 'kbd'],
  'key hint in the menu': ['canvas', 'menu', 'kbd'],
  ...Object.fromEntries([0, 1, 2, 3, 4, 5, 6, 7].map((i) => [`overview block, phase tone ${i}`, ['canvas', `block ${i}`]])),
  'overview block, no phase tone': ['canvas', 'block'],
};

const SURFACE = 'surface (card, side panel, header, status bar, tooltip, phase index)';
const RAISED = 'raised on a surface (hovered or selected row, quote, chip)';

/**
 * The boxes that paint --mlv-surface-2 under their own secondary or muted text (a census below
 * finds every one), the stack each box is drawn on, and the --mlv-surface-2 containers the DOM
 * puts it in, each with the stack under the container. In a container the box is drawn on the
 * container's fill and then on its own fill as the stylesheet paints it there, which a census of
 * values cannot see. --mlv-surface-2 is list.hoverBackground, translucent in Dark 2026 and Light
 * 2026, so two of them stack: the stale chip ("cites a changed file") in a hovered or selected
 * Findings row was 4.49:1 computed and 4.53:1 by a pixel probe in Dark 2026 (viewer M4
 * verification, F2), and a group count on a hovered group header was 5.00:1, the lightest
 * background under secondary text in Dark 2026. Both drop their fill there now (rail.css,
 * canvas.css), so the stack under each is the container's alone; the matrix used to hold
 * secondary text to a static "raised twice on a lane" stack as well, which only the group count
 * was drawn on.
 */
const RAISED_INK = {
  // The header's provenance chip, the legend's chips and a Findings row's chips.
  '.mlv-chip': { on: [SURFACE], inside: [['.mlv-issue:hover', SURFACE], ['.mlv-issue.is-selected', SURFACE]] },
  '.mlv-group__count': { on: ['lane'], inside: [['.mlv-group__header:hover', 'lane']] },
  '.mlv-node__iconbox': { on: [SURFACE], inside: [] },
};

/** The background the last rule naming exactly `selector` (in a selector list) declares, or undefined. */
function lastPaint(all, selector) {
  const paints = all.filter((r) => r.selector.split(',').map((s) => s.trim()).includes(selector))
    .map((r) => r.decls.background ?? r.decls['background-color']).filter((v) => v !== undefined);
  return paints.length ? paints[paints.length - 1].replace(/\s*!important$/, '') : undefined;
}

/**
 * Each RAISED_INK box in each of its containers: the ground's name, the box, its ink and the
 * paints from the container's stack up: the container's fill, then the box's fill in it (a rule
 * for `container box`, which outranks the box's own rule, or else the box's own fill).
 */
function nestedGrounds(all) {
  const out = [];
  for (const [box, { inside }] of Object.entries(RAISED_INK)) {
    const own = all.filter((r) => r.selector === box).map((r) => r.decls).reduce((a, b) => ({ ...a, ...b }), {});
    for (const [container, base] of inside) {
      const fill = lastPaint(all, `${container} ${box}`) ?? lastPaint(all, box);
      out.push({ name: `${box} in ${container}`, box, ink: own.color ?? own.fill, base, paints: [lastPaint(all, container), fill] });
    }
  }
  return out;
}

/** The stacks each muted-text selector sits on. Secondary text is held to every stack. */
const MUTED_ON = {
  '.mlv-input::placeholder': [SURFACE],
  '.mlv-lane__count': ['lane header'],
  '.mlv-lane__unit': ['lane header'],
  '.mlv-tooltip__loc': [SURFACE],
  '.mlv-search__glyph': [SURFACE],
  '.mlv-result__foot': [SURFACE],
  '.mlv-legend__heading': [SURFACE],
  // A card's location line: on the card, on an unresolved card's hatching, and on the canvas when
  // exceptions mode fades an observed card to the background.
  '.mlv-node__loc': [SURFACE, 'hatched (unresolved) card', 'canvas'],
  '.mlv-rail__count': [SURFACE],
  '.mlv-rail__heading': [SURFACE],
  '.mlv-issue__meta': [SURFACE, RAISED],
  '.mlv-insp__sep': [SURFACE],
  '.mlv-insp__issue-head .mlv-mono': [RAISED],
  '.mlv-insp__issue-id': [RAISED],
  '.mlv-quote__fresh.is-muted': [SURFACE],
  '.mlv-quote__ln': [RAISED],
  '.mlv-about__meta, .mlv-about__note': [SURFACE],
  '.mlv-about__changeid, .mlv-about__changefields': [SURFACE],
  '.mlv-insp__change': [SURFACE],
  '.mlv-outline__chevron': [SURFACE, RAISED],
  '.mlv-outline__stage': [SURFACE, RAISED],
  '.mlv-relations__detail': [RAISED],
};

/**
 * The declarations VS Code's default webview stylesheet gives `tag`, as the screenshot harness's
 * page copies them: `kbd { background-color: var(--vscode-keybindingLabel-background); … }` and
 * `code { color: var(--vscode-textPreformat-foreground); background-color: … }`.
 */
async function vscodeRule(tag) {
  const page = await readFile(join(WEBVIEW_ROOT, 'tools', 'screenshots', 'page.html'), 'utf8');
  const m = new RegExp('(?:^|\\n)' + tag + ' \\{([^}]*)\\}').exec(page);
  assert.ok(m, `page.html styles <${tag}> as VS Code does`);
  const decls = {};
  for (const part of m[1].split(';')) {
    const i = part.indexOf(':');
    if (i > 0) decls[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return decls;
}

async function vscodeKbdBackground() {
  const value = (await vscodeRule('kbd'))['background-color'];
  assert.ok(value, 'a <kbd> background');
  return value;
}

/** The <kbd> classes the viewer builds whose rule paints no background, so VS Code's key cap shows. */
const KBD_ON_VSCODE_CAP = ['mlv-overview__kbd', 'mlv-moremenu__keys'];

/** Each stack's colour, for one theme. */
async function grounds(vars) {
  const all = await sheets();
  const edge = await css('edge.css');
  const kbd = await vscodeKbdBackground();
  const paint = (name) => {
    if (name === 'kbd') return colour(kbd, vars);
    if (name === 'badge') {
      const box = block(edge, '.mlv-bundle__badge-box');
      const fill = colour(box.fill, vars);
      return [fill[0], fill[1], fill[2], fill[3] * Number(box.opacity)];
    }
    const phase = /^block (\d)$/.exec(name);
    const value = Object.keys(PAINTS).find((v) => PAINTS[v] === (phase ? 'block' : name));
    assert.ok(value, 'no paint for ' + name);
    if (name === 'hatch') {
      // The hatching's stripe colour: the gradient's color-mix(), parentheses balanced.
      const start = value.indexOf('color-mix(');
      let depth = 0;
      let end = start + 'color-mix'.length;
      do {
        if (value[end] === '(') depth++;
        else if (value[end] === ')') depth--;
        end++;
      } while (depth > 0 && end < value.length);
      return colour(value.slice(start, end), vars);
    }
    return colour(phase ? value.replace('var(--mlv-stage, var(--mlv-text-2))', `var(--mlv-phase-${phase[1]})`) : value, vars);
  };
  assert.ok(all.includes('.mlv-bundle__badge-text'), 'the badge text exists');
  const out = {};
  for (const [stack, layers] of Object.entries(STACKS)) {
    const base = paint(layers[0]);
    assert.equal(base[3], 1, stack + ': the canvas is opaque');
    out[stack] = layers.slice(1).reduce((under, layer) => over(paint(layer), under), base);
  }
  for (const { name, base, paints } of nestedGrounds(rules(all))) {
    out[name] = paints.reduce((under, value) => over(colour(value, vars), under), out[base]);
  }
  return out;
}

/** text, secondary and muted text as painted on the card surface, for one theme. */
function inks(vars) {
  const bg = colour('var(--mlv-bg)', vars);
  const surface = over(colour('var(--mlv-surface)', vars), bg);
  const on = (token) => colour(`var(${token})`, vars);
  return { surface, text: on('--mlv-text'), text2: on('--mlv-text-2'), text3: on('--mlv-text-3') };
}

/* ── the tests ─────────────────────────────────────────────────────────────────────────────── */

test('the harness table carries the six themes the viewer is checked in, 2026 Dark and Light, and their menu colours', async () => {
  const themes = await harnessThemes();
  assert.deepEqual(Object.values(themes).map((t) => t.label), ['Dark Modern', 'Dark+', 'Light Modern', 'Light+', 'Dark High Contrast', 'Light High Contrast', 'Dark 2026', 'Light 2026']);
  // VS Code stamps both classes on <body> for Light High Contrast, so the high contrast tokens apply.
  assert.equal(themes['hc-light'].bodyClass, 'vscode-high-contrast-light vscode-high-contrast');
  // Light Modern's descriptionForeground is its text colour, which is why neither token reads it.
  const lm = themes['light-modern'].vars;
  assert.equal(lm['--vscode-descriptionForeground'], lm['--vscode-editor-foreground']);
  // The ... menu paints the theme's menu colours; every theme outside high contrast has them.
  for (const { label, kind, vars } of Object.values(themes)) {
    if (kind === 'hc') continue;
    for (const key of ['menu-background', 'menu-foreground', 'menu-selectionBackground', 'menu-selectionForeground']) {
      assert.ok(vars['--vscode-' + key], `${label}: --vscode-${key}`);
    }
  }
});

test('secondary and muted text: a Lab mix lifted to L* 42 in light themes, steps below the text with a floor in dark themes (each gated by @supports, with a fallback), the text colour in high contrast', async () => {
  const tokens = await css('tokens.css');
  const { rest, light: lightRule, dark: darkRule } = await tokenBlocks();
  const light = block(rest, LIGHT_ROOT);
  assert.deepEqual([light['--mlv-text-2'], light['--mlv-text-3']], [LIGHT_SECONDARY, LIGHT_MIX], 'light: secondary text halfway to muted text, the plain mix as the fallback');
  for (const selector of [DARK_BODY, DARK_MEDIA]) {
    const decls = block(rest, selector);
    assert.deepEqual([decls['--mlv-text-2'], decls['--mlv-text-3']], [DARK_FALLBACK, DARK_FALLBACK], selector + ': the fallback');
  }
  // Each gate tests the exact expression its declarations use, with literals for the var()s (the
  // dark secondary one is the larger: it has every function and operator the muted one has), so an
  // engine that cannot compute it keeps the fallback instead of an invalid colour.
  assert.equal(lightRule.condition, `(color: lab(from color-mix(in lab, #000 74%, #fff) ${LIGHT_MUTED_L} a b))`);
  assert.equal(LIGHT_MUTED.replace('var(--mlv-text)', '#000').replace('var(--mlv-surface)', '#fff'), lightRule.condition.slice('(color: '.length, -1));
  const lightInside = rules(lightRule.body);
  assert.deepEqual(lightInside.map((r) => r.selector), [LIGHT_ROOT], 'the light branch, and nothing else');
  assert.deepEqual(lightInside[0].decls, { '--mlv-text-3': LIGHT_MUTED }, 'muted text only: secondary text follows it');
  assert.equal(darkRule.condition, `(color: lab(from #000 ${DARK_SECONDARY_L} a b))`);
  const inside = rules(darkRule.body);
  assert.deepEqual(inside.map((r) => r.selector).sort(), [DARK_BODY, DARK_MEDIA].sort(), 'both dark branches, and nothing else');
  for (const { selector, decls } of inside) assert.deepEqual(decls, { '--mlv-text-2': DARK_SECONDARY, '--mlv-text-3': DARK_MUTED }, selector);
  // The @supports blocks follow the dark blocks, so the dark rule wins the cascade where it applies
  // (the light rule's :root is less specific than every dark and high contrast selector on :root).
  assert.ok(tokens.indexOf('@supports') > tokens.indexOf(DARK_BODY.split(',')[0] + ','), 'after the dark blocks');
  assert.equal(block(rest, HC_BODY)['--mlv-text-2'], 'var(--vscode-editor-foreground, #FFFFFF)');
  assert.equal(block(rest, HC_BODY)['--mlv-text-3'], 'var(--vscode-editor-foreground, #FFFFFF)');
  // No per-theme rule: nothing in the stylesheets names a theme.
  assert.doesNotMatch(tokens + (await sheets()), /data-vscode-theme-name|vscode-theme-id/);
});

test('every background the stylesheets paint is a classified ground, or paints no text', async () => {
  const seen = new Set();
  const unknown = [];
  for (const { selector, decls } of rules(await sheets())) {
    for (const prop of ['background', 'background-color', 'background-image']) {
      if (decls[prop] === undefined) continue;
      const value = decls[prop].replace(/\s*!important$/, '').replace(/\s+/g, ' ');
      if (Object.prototype.hasOwnProperty.call(PAINTS, value)) seen.add(value);
      else unknown.push(`${selector} { ${prop}: ${value} }`);
    }
  }
  assert.deepEqual(unknown, [], 'a background the census does not know: add it to PAINTS (and STACKS when text sits on it)');
  assert.deepEqual(Object.keys(PAINTS).filter((v) => !seen.has(v)), [], 'a PAINTS entry no stylesheet paints any more');
});

test('every muted-text selector is mapped to the backgrounds it sits on', async () => {
  const found = rules(await sheets())
    .filter(({ decls }) => decls.color === 'var(--mlv-text-3)' || decls.fill === 'var(--mlv-text-3)')
    .map((r) => r.selector);
  assert.deepEqual(found.slice().sort(), Object.keys(MUTED_ON).sort());
  for (const stacks of Object.values(MUTED_ON)) for (const stack of stacks) assert.ok(STACKS[stack], stack);
});

test('every box that paints --mlv-surface-2 under its own secondary or muted text names its stack and the --mlv-surface-2 containers it sits in', async () => {
  const all = rules(await sheets());
  const inks = ['var(--mlv-text-2)', 'var(--mlv-text-3)'];
  const found = all.filter(({ decls }) => {
    const paint = (decls.background ?? decls['background-color'] ?? '').replace(/\s*!important$/, '').replace(/\s+/g, ' ');
    return PAINTS[paint] === 'raised' && (inks.includes(decls.color) || inks.includes(decls.fill));
  });
  assert.deepEqual(found.map((r) => r.selector).sort(), Object.keys(RAISED_INK).sort(), 'a --mlv-surface-2 box with its own secondary or muted text: add it to RAISED_INK');
  for (const [box, { on, inside }] of Object.entries(RAISED_INK)) {
    const muted = found.some((r) => r.selector === box && (r.decls.color === 'var(--mlv-text-3)' || r.decls.fill === 'var(--mlv-text-3)'));
    for (const stack of on) {
      assert.ok(STACKS[stack], stack);
      // Muted text is held to the stacks MUTED_ON names (secondary text to every stack).
      if (muted) assert.ok((MUTED_ON[box] || []).includes(stack), `${box}: MUTED_ON names ${stack}`);
    }
    for (const [container, base] of inside) {
      assert.ok(STACKS[base], base);
      assert.equal(PAINTS[lastPaint(all, container)], 'raised', `${container} paints --mlv-surface-2`);
    }
  }
  // The chip in a hovered or selected Findings row is a ground secondary text is held to.
  const names = nestedGrounds(all).map((g) => g.name);
  for (const name of ['.mlv-chip in .mlv-issue:hover', '.mlv-chip in .mlv-issue.is-selected', '.mlv-group__count in .mlv-group__header:hover']) assert.ok(names.includes(name), name);
});

test('every <kbd> the viewer builds paints its own background, or is modelled on VS Code\'s key cap', async () => {
  // VS Code's default webview stylesheet paints every <kbd>; the screenshot harness probe found the
  // phase overview's Esc on that key cap (keybindingLabel.background), not on the canvas.
  const ui = join(WEBVIEW_ROOT, 'src', 'ui');
  const source = (await Promise.all((await readdir(ui)).filter((n) => n.endsWith('.ts')).map((n) => readFile(join(ui, n), 'utf8')))).join('\n');
  const classes = [...new Set([...source.matchAll(/el\('kbd', '([\w-]+)'/g)].map((m) => m[1]))].sort();
  assert.ok(classes.length >= 3, 'the <kbd> elements are found');
  const all = rules(await sheets());
  for (const cls of classes) {
    const own = all.filter((r) => r.selector === '.' + cls).some((r) => r.decls.background !== undefined || r.decls['background-color'] !== undefined);
    assert.equal(!own, KBD_ON_VSCODE_CAP.includes(cls), `.${cls}: ${own ? 'paints its own background' : 'shows VS Code\'s key cap'}`);
  }
});

/** The stacks muted text is drawn on: MUTED_ON's, and the containers of a box in muted text. */
function mutedStacks(all) {
  const nested = nestedGrounds(all).filter((g) => g.ink === 'var(--mlv-text-3)').map((g) => g.name);
  return [...new Set([...Object.values(MUTED_ON).flat(), ...nested])];
}

const ENGINES = ['relative', 'fallback'];

test('secondary and muted text clear 4.5:1 on every background they are drawn on, in every theme outside high contrast, with or without relative colour syntax', async (t) => {
  const all = rules(await sheets());
  const failures = [];
  for (const engine of ENGINES) {
    const matrix = {};
    for (const { label, kind, vars } of Object.values(await themeVars(engine))) {
      if (kind === 'hc') continue;
      const ground = await grounds(vars);
      const { surface, text2, text3 } = inks(vars);
      const rows = [];
      for (const [token, ink, stacks] of [['--mlv-text-2', text2, Object.keys(ground)], ['--mlv-text-3', text3, mutedStacks(all)]]) {
        let worst = { ratio: Infinity, where: '' };
        for (const stack of stacks) {
          const under = ground[stack];
          const ratio = contrast(over(ink, under), under);
          (matrix[label] ||= {})[`${token} on ${stack}`] = Number(ratio.toFixed(2));
          if (ratio < worst.ratio) worst = { ratio, where: stack };
          if (ratio < 4.5) failures.push(`${engine} ${label}: ${token} on ${stack} is ${ratio.toFixed(2)}:1`);
        }
        rows.push(`${token} ${toHex(over(ink, surface))} ${contrast(over(ink, surface), surface).toFixed(2)}:1 on the surface, lowest ${worst.ratio.toFixed(2)}:1 (${worst.where})`);
      }
      t.diagnostic(`${engine} ${label}: ${rows.join('; ')}`);
    }
    t.diagnostic(`${engine} matrix ` + JSON.stringify(matrix));
  }
  assert.deepEqual(failures, []);
});

test('the text colour, secondary and muted text keep their order on every background, with or without relative colour syntax', async () => {
  for (const engine of ENGINES) {
    for (const { label, kind, vars } of Object.values(await themeVars(engine))) {
      const { surface, text, text2, text3 } = inks(vars);
      if (kind === 'hc') {
        // High contrast: both are the theme's own text colour.
        const fg = toHex(over(colour('var(--vscode-editor-foreground)', vars), surface));
        assert.deepEqual([toHex(over(text2, surface)), toHex(over(text3, surface))], [fg, fg], label);
        continue;
      }
      const ground = await grounds(vars);
      for (const [stack, under] of Object.entries(ground)) {
        const [c1, c2, c3] = [text, text2, text3].map((ink) => contrast(over(ink, under), under));
        assert.ok(c1 >= c2 && c2 >= c3, `${engine} ${label} on ${stack}: text ${c1.toFixed(2)}, secondary ${c2.toFixed(2)}, muted ${c3.toFixed(2)}`);
      }
    }
  }
});

/**
 * How far toward the card surface, as a share of the L* distance from the text, a colour on the
 * Lab line from the text to the surface can sit and still clear 4.5:1 on every one of `stacks`.
 */
function room(text, surface, ground, stacks) {
  const clears = (p) => {
    const ink = mixLab(text, surface, 1 - p);
    return stacks.every((s) => contrast(over(ink, ground[s]), ground[s]) >= 4.5);
  };
  assert.ok(clears(0), 'the text colour itself clears 4.5:1');
  let [lo, hi] = [0, 1];
  for (let i = 0; i < 30; i++) {
    const mid = (lo + hi) / 2;
    if (clears(mid)) lo = mid;
    else hi = mid;
  }
  return lo;
}

/**
 * The themes with no room for three levels at 4.5:1, and why. There secondary text is muted text,
 * as both were Dark Modern's descriptionForeground before viewer M4, rather than a secondary level
 * barely quieter than the text.
 */
const TWO_LEVEL = {
  'Dark 2026': 'its text (#BBBEBF, L* 76.8) is dim and its hovered rows light (8% white): muted text has room for about 21% of the L* distance to the card',
};

const pct = (x) => (x * 100).toFixed(1) + '%';

/*
 * The hierarchy's thresholds, as shares of the L* distance from the text to the card. Muted text
 * uses at least MUTED_ROOM of the room the theme has at 4.5:1, so it is as quiet as contrast
 * allows, give or take; the dark rule's 18 L* step uses 85% in Dark Modern and Dark+. Secondary
 * text sits at least SECONDARY_SHARE of the way and at least SECONDARY_ROOM of its own room, so it
 * is a step from the text where the theme has room for one, not a near-copy of it.
 */
const MUTED_ROOM = 0.8;
const SECONDARY_SHARE = 0.125;
const SECONDARY_ROOM = 0.4;

test('secondary and muted text keep a visible distance from the text: muted text uses the room the theme has at 4.5:1, 25% or more of the L* distance to the card, and secondary text a step from each, or two levels where the theme has no room', async (t) => {
  // Viewer M4 verification, F3: with the 90% and 80% sRGB mixes secondary text sat 9-12% of the L*
  // distance from the text to the card (ΔL* about 6 in the dark themes), muted text 18% in the dark
  // themes, and Light+ drew the three levels as #000000, #181818 and #313131.
  // Viewer M4 hierarchy verification: a uniform 87% and 74% Lab mix in light themes put secondary
  // text 13% of the way (Light+ #202020 beside #000000 titles, Light 2026 #383838 from #363636)
  // where Light+ has room for 44% and Light 2026 for 37% (V1): muted text used 59% and 71% of that
  // room, and secondary text 30% and 35% of its own. A secondary level 10-12% of the way (an 89%
  // mix, or the old 90% sRGB mix in Light Modern and Light 2026) passed a 10% step (V2).
  const all = rules(await sheets());
  const two = [];
  for (const { label, kind, vars } of Object.values(await themeVars())) {
    if (kind === 'hc') continue;
    const ground = await grounds(vars);
    const { surface, text, text2, text3 } = inks(vars);
    const [lt, ls] = [lstar(text), lstar(surface)];
    const share = (ink) => (lt - lstar(over(ink, surface))) / (lt - ls);
    const [s2, s3] = [share(text2), share(text3)];
    const mutedRoom = room(text, surface, ground, mutedStacks(all));
    const secondaryRoom = room(text, surface, ground, Object.keys(ground));
    t.diagnostic(`${label}: text ${toHex(text)} L* ${lt.toFixed(1)}, card L* ${ls.toFixed(1)}; secondary ${toHex(over(text2, surface))} ${pct(s2)} (ΔL* ${Math.abs(lt - lstar(over(text2, surface))).toFixed(1)}), muted ${toHex(over(text3, surface))} ${pct(s3)} (ΔL* ${Math.abs(lt - lstar(over(text3, surface))).toFixed(1)}); room at 4.5:1: muted ${pct(mutedRoom)}, secondary ${pct(secondaryRoom)}`);
    // Secondary text lies between the text and muted text, on the surface's side of the text.
    assert.ok(s2 > 0 && s2 <= s3, `${label}: secondary ${pct(s2)}, muted ${pct(s3)}`);
    // Muted text uses the room the theme has: a near-black level in a theme with room for a grey
    // one is not quieter than the text.
    assert.ok(s3 >= MUTED_ROOM * mutedRoom, `${label}: muted text is ${pct(s3)} of the way to the card, under ${pct(MUTED_ROOM)} of its room (${pct(mutedRoom)})`);
    if (mutedRoom >= 0.25 && secondaryRoom >= 0.1) {
      assert.ok(s3 >= 0.25, `${label}: muted text is ${pct(s3)} of the way to the card, with room for ${pct(mutedRoom)}`);
      assert.ok(s2 >= SECONDARY_SHARE, `${label}: secondary text is ${pct(s2)} of the way, under a step (${pct(SECONDARY_SHARE)}) from the text`);
      assert.ok(s2 >= SECONDARY_ROOM * secondaryRoom, `${label}: secondary text is ${pct(s2)} of the way, under ${pct(SECONDARY_ROOM)} of its room (${pct(secondaryRoom)})`);
      assert.ok(s3 - s2 >= 0.1, `${label}: secondary ${pct(s2)} and muted ${pct(s3)} are under a step apart`);
    } else {
      two.push(label);
      assert.ok(TWO_LEVEL[label], `${label} has room for only ${pct(mutedRoom)} (muted) and ${pct(secondaryRoom)} (secondary): name it in TWO_LEVEL`);
      assert.equal(toHex(over(text2, surface)), toHex(over(text3, surface)), `${label}: two levels, secondary text is muted text`);
      // ... and that level uses the room the theme has.
      assert.ok(s3 >= mutedRoom - 0.03, `${label}: muted text is ${pct(s3)} of the way, with room for ${pct(mutedRoom)}`);
    }
  }
  assert.deepEqual(two, Object.keys(TWO_LEVEL), 'the two-level themes are the ones TWO_LEVEL names');
});

test('the light rule keeps the order in any light theme: secondary text halfway from the text to muted text, muted text never darker than the plain mix or lighter than the card, and at L* 42 where the mix is darker', () => {
  // The rule reads the text and the card surface, so a sweep of both lightnesses (a few hues, and
  // Solarized Light's #657B83 on #EEE8D5) covers the order in any third-party light theme. Its
  // contrast depends on that theme's own backgrounds; on the card itself the lift keeps 4.5:1
  // wherever the plain mix had it, for any card from L* 89 (#DFDFDF) up.
  const pairs = [['#657B83', '#EEE8D5']];
  for (let L = 0; L <= 60; L += 1) {
    for (const [a, b] of [[0, 0], [-6, -3], [4, 8]]) {
      for (const card of [89, 92, 95.8, 98, 100]) pairs.push([toHex(labToSrgb([L, a, b])), toHex(labToSrgb([card, 0, -1]))]);
    }
  }
  const failures = [];
  for (const [text, surface] of pairs) {
    const vars = { '--mlv-text': text, '--mlv-surface': surface, '--mlv-text-3': LIGHT_MUTED };
    const [t, s2, s3, card, mix] = [hex(text), colour(LIGHT_SECONDARY, vars), colour(LIGHT_MUTED, vars), hex(surface), colour(LIGHT_MIX, vars)];
    const [l1, l2, l3, lc, lm] = [t, s2, s3, card, mix].map(lstar);
    const where = `${text} on ${surface} (L* ${l1.toFixed(2)} on ${lc.toFixed(2)})`;
    if (!(l1 <= l2 + 0.01 && l2 <= l3 + 0.01 && l3 <= lc + 0.01)) failures.push(`${where}: L* ${l2.toFixed(2)}, ${l3.toFixed(2)}`);
    if (Math.abs(l2 - (l1 + l3) / 2) > 0.3) failures.push(`${where}: secondary L* ${l2.toFixed(2)} is not halfway to ${l3.toFixed(2)}`);
    if (Math.abs(l3 - Math.max(lm, 42)) > 0.3) failures.push(`${where}: muted L* ${l3.toFixed(2)}, the mix ${lm.toFixed(2)}`);
    if (contrast(mix, card) >= 4.5 && contrast(s3, card) < 4.5) failures.push(`${where}: the lift takes muted text under 4.5:1 on the card (${contrast(s3, card).toFixed(2)}:1)`);
  }
  assert.deepEqual(failures, []);
});

test('the dark rule keeps the order in any dark theme: never above the text, secondary at or above muted text, two levels under L* 79.5, the text colour under L* 64.5', () => {
  // The rule reads only the text colour, so a sweep of the text's lightness (a few hues, and
  // Solarized Dark's #839496, L* 60) covers the order in any third-party dark theme. Not its
  // contrast, which depends on that theme's own backgrounds.
  const texts = ['#839496'];
  for (let L = 40; L <= 100; L += 0.5) for (const [a, b] of [[0, 0], [-6, -3], [4, 8]]) texts.push(toHex(labToSrgb([L, a, b])));
  const failures = [];
  for (const text of texts) {
    const vars = { '--mlv-text': text };
    const [t, s2, s3] = [hex(text), colour(DARK_SECONDARY, vars), colour(DARK_MUTED, vars)];
    const [l1, l2, l3] = [t, s2, s3].map(lstar);
    if (!(l1 >= l2 - 0.01 && l2 >= l3 - 0.01)) failures.push(`${text}: L* ${l1.toFixed(2)}, ${l2.toFixed(2)}, ${l3.toFixed(2)}`);
    if (l1 < 79.49 && toHex(s2) !== toHex(s3)) failures.push(`${text} (L* ${l1.toFixed(2)}): secondary ${toHex(s2)} is not muted ${toHex(s3)}`);
    if (l1 <= 64.49 && (toHex(s2) !== text || toHex(s3) !== text)) failures.push(`${text} (L* ${l1.toFixed(2)}): not the text colour`);
    if (l1 >= 79.51 && l2 - l3 < 6 - 0.01) failures.push(`${text} (L* ${l1.toFixed(2)}): secondary ${l2.toFixed(2)} under 6 L* above muted ${l3.toFixed(2)}`);
  }
  assert.deepEqual(failures, []);
});

test('inside a hovered or focused menu item, secondary text takes the menu\'s selection colour and the key hint drops VS Code\'s key cap', async () => {
  // VS Code's menu.selectionBackground is a solid blue in Dark Modern, Dark+, Light Modern and
  // Light+ (#0078D4, #005FB8, #0060C0) with a white selectionForeground: no grey reaches 4.5:1 on
  // it, so the item's icon, key hint and note inherit the item's colour there instead.
  const chrome = await css('chrome.css');
  const item = block(chrome, '.mlv-moremenu__item:hover, .mlv-moremenu__item:focus-visible');
  assert.equal(item.color, 'var(--vscode-menu-selectionForeground, var(--mlv-text))');
  const inherit = rules(chrome).find((r) => r.decls.color === 'inherit' && r.selector.includes(':hover .mlv-moremenu__keys'));
  assert.ok(inherit, 'a rule makes the hovered item\'s secondary text inherit');
  const selectors = inherit.selector.split(',').map((s) => s.trim());
  for (const state of [':hover', ':focus-visible']) {
    for (const part of ['.mlv-uicon', '.mlv-moremenu__keys', '.mlv-moremenu__note']) {
      assert.ok(selectors.includes(`.mlv-moremenu__item${state} ${part}`), `${state} ${part}`);
    }
    // The disabled phase index item keeps its label in secondary text (viewer M2 live fix); its
    // rule is more specific, so the hovered form is spelled out.
    assert.ok(selectors.includes(`.mlv-moremenu__item[data-more-item="phaseindex"][disabled]${state} .mlv-moremenu__label`), state + ' disabled label');
  }
  // The key hint is a <kbd> on VS Code's key cap (keybindingLabel.background, a translucent grey),
  // which lightens the blue under it: white on the cap over Light Modern's #005FB8 is 3.34:1
  // (viewer M4 verification, F1, measured in pixels too). The cap is composited unless the hovered
  // or focused key hint's own rule paints over it; the last background declared wins.
  const all = rules(chrome);
  const kbd = await vscodeKbdBackground();
  const keyCap = (state) => lastPaint(all, `.mlv-moremenu__item${state} .mlv-moremenu__keys`) ?? kbd;
  const themes = await themeVars();
  const failures = [];
  for (const { label, kind, vars } of Object.values(themes)) {
    if (kind === 'hc') continue;
    const menu = over(colour('var(--vscode-menu-background)', vars), colour('var(--mlv-bg)', vars));
    const hovered = over(colour('var(--vscode-menu-selectionBackground)', vars), menu);
    const fg = colour('var(--vscode-menu-selectionForeground)', vars);
    const label45 = contrast(over(fg, hovered), hovered);
    if (label45 < 4.5) failures.push(`${label}: the hovered item's text is ${label45.toFixed(2)}:1`);
    for (const state of [':hover', ':focus-visible']) {
      const cap = over(colour(keyCap(state), vars), hovered);
      const ratio = contrast(over(fg, cap), cap);
      if (ratio < 4.5) failures.push(`${label}: the ${state} item's key hint is ${ratio.toFixed(2)}:1 on ${toHex(cap)}`);
    }
  }
  assert.deepEqual(failures, []);
});

test('About\'s notes and provenance line, the Changes section\'s field lists and removed ids, and the Selection pane\'s "changed since" line are muted text (A11Y-M4-2)', async () => {
  const rail = await css('rail.css');
  for (const selector of ['.mlv-about__meta, .mlv-about__note', '.mlv-about__changeid, .mlv-about__changefields', '.mlv-insp__change', '.mlv-quote__fresh.is-muted']) {
    assert.equal(block(rail, selector).color, 'var(--mlv-text-3)', selector);
  }
});

test('every <code> the viewer builds that paints its own background sets its own colour; About\'s k=v tokens clear 4.5:1 in every theme', async () => {
  // VS Code's default webview stylesheet colours <code> with textPreformat.foreground over
  // textPreformat.background. A rule that replaces the background keeps the foreground unless it
  // sets a colour: About's k=v tokens kept it on --mlv-surface-2, 3.82:1 in Dark 2026 (#8C8C8C) and
  // white on white (1.00:1) in Light High Contrast (viewer M4 verification, F5; a pixel probe gave
  // the same).
  const ui = join(WEBVIEW_ROOT, 'src', 'ui');
  const source = (await Promise.all((await readdir(ui)).filter((n) => n.endsWith('.ts')).map((n) => readFile(join(ui, n), 'utf8')))).join('\n');
  const classes = [...new Set([...source.matchAll(/el\('code', '([\w-]+)'/g)].map((m) => m[1]))].sort();
  assert.ok(classes.includes('mlv-about__kv'), 'About\'s k=v tokens are <code>');
  const all = rules(await sheets());
  const failures = [];
  for (const cls of classes) {
    const own = Object.assign({}, ...all.filter((r) => r.selector === '.' + cls).map((r) => r.decls));
    if ((own.background !== undefined || own['background-color'] !== undefined) && !own.color) failures.push(`.${cls} paints its own background under VS Code's code colour`);
  }
  const code = await vscodeRule('code');
  const rail = await css('rail.css');
  const kv = block(rail, '.mlv-about__kv');
  const paragraph = block(rail, '.mlv-about__para, .mlv-about__text, .mlv-about__status');
  const ink = kv.color === undefined ? code.color : kv.color === 'inherit' ? paragraph.color : kv.color;
  const paint = kv.background ?? kv['background-color'] ?? code['background-color'];
  for (const { label, vars } of Object.values(await themeVars())) {
    const panel = over(colour('var(--mlv-surface)', vars), colour('var(--mlv-bg)', vars));
    const under = over(colour(paint, vars), panel);
    const ratio = contrast(over(colour(ink, vars), under), under);
    if (ratio < 4.5) failures.push(`${label}: ${toHex(over(colour(ink, vars), under))} on ${toHex(under)} is ${ratio.toFixed(2)}:1`);
  }
  assert.deepEqual(failures, []);
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

test('the SVG export derives secondary and muted text the same way: the lifted Lab mix in light themes, the steps below the text in dark ones', async () => {
  const { EXPORT_PALETTES, LIGHT_TEXT_LEVELS, DARK_TEXT_LEVELS, darkTextLevels, lightTextLevels, resolvePalette } = await palette();
  // The export's constants are the stylesheet's.
  const shareOf = (value) => Number(/var\(--mlv-text\) ([\d.]+)%/.exec(value)[1]) / 100;
  assert.equal(LIGHT_TEXT_LEVELS.mix, shareOf(LIGHT_MIX));
  assert.equal(LIGHT_MUTED_L, `max(l, ${LIGHT_TEXT_LEVELS.floor})`);
  assert.equal(shareOf(LIGHT_SECONDARY), 0.5, 'secondary text halfway to muted text');
  const { floor, step2, step3, split } = DARK_TEXT_LEVELS;
  assert.equal(DARK_SECONDARY_L, `min(l, max(${floor}, l - ${step2} - clamp(0, (${split} - l) * 100, 100)))`);
  assert.equal(DARK_MUTED_L, `min(l, max(${floor}, l - ${step3}))`);
  // Two implementations agree, the export's and this test's (colour-lab.mjs), to a unit per
  // channel: on the export's own tables and on every harness theme's text and card surface.
  const near = (a, b) => [1, 3, 5].every((i) => Math.abs(parseInt(a.slice(i, i + 2), 16) - parseInt(b.slice(i, i + 2), 16)) <= 1);
  const ours = (value, text, surface) => toHex(colour(value, { '--mlv-text': text, '--mlv-surface': surface, '--mlv-text-3': LIGHT_MUTED }));
  const cases = [['light', EXPORT_PALETTES.light.text, EXPORT_PALETTES.light.surface, EXPORT_PALETTES.light]];
  cases.push(['dark', EXPORT_PALETTES.dark.text, EXPORT_PALETTES.dark.surface, EXPORT_PALETTES.dark]);
  for (const { label, kind, vars } of Object.values(await themeVars())) {
    if (kind === 'hc') continue;
    const text = toHex(colour('var(--mlv-text)', vars));
    const surface = toHex(over(colour('var(--mlv-surface)', vars), colour('var(--mlv-bg)', vars)));
    const derived = kind === 'light' ? lightTextLevels(text, surface) : darkTextLevels(text);
    cases.push([label, text, surface, derived, kind]);
  }
  for (const [label, text, surface, p, kind = label] of cases) {
    const [s2, s3] = kind === 'light' ? [LIGHT_SECONDARY, LIGHT_MUTED] : [DARK_SECONDARY, DARK_MUTED];
    assert.ok(near(p.text2, ours(s2, text, surface)), `${label} secondary: ${p.text2} and ${ours(s2, text, surface)}`);
    assert.ok(near(p.text3, ours(s3, text, surface)), `${label} muted: ${p.text3} and ${ours(s3, text, surface)}`);
  }
  assert.deepEqual([EXPORT_PALETTES.hc.text2, EXPORT_PALETTES.hc.text3], [EXPORT_PALETTES.hc.text, EXPORT_PALETTES.hc.text], 'high contrast: the text colour');
  const rootWith = (values) => {
    const style = { getPropertyValue: (name) => values[name] || '' };
    return { ownerDocument: { defaultView: { getComputedStyle: () => style } } };
  };
  // A live light root holds the relative colour for muted text and a color-mix() of the text and
  // that for secondary text, neither of which an SVG can carry: derived from the text and the card.
  // Light+: #000000, #323232, #636363 (Light Modern's mix is lighter than L* 42: #515151, #676767).
  const lightRoot = (text, surface) => {
    const muted = `lab(from color-mix(in lab, ${text} 74%, ${surface}) ${LIGHT_MUTED_L} a b)`;
    return rootWith({ '--mlv-text': text, '--mlv-surface': surface, '--mlv-text-2': `color-mix(in lab, ${text} 50%, ${muted})`, '--mlv-text-3': muted });
  };
  const lightPlus = resolvePalette(lightRoot('#000000', '#f3f3f3'), 'light');
  assert.deepEqual([lightPlus.text2, lightPlus.text3], ['#323232', '#636363']);
  const lightModern = resolvePalette(lightRoot('#3b3b3b', '#f8f8f8'), 'light');
  assert.deepEqual([lightModern.text2, lightModern.text3], ['#515151', '#676767']);
  // An engine without relative colour syntax holds plain mixes, secondary text a mix with a mix:
  // read as the colours that engine paints (to a unit per channel; the inner mix is rounded first).
  const plain = resolvePalette(rootWith({
    '--mlv-text': '#000000', '--mlv-surface': '#f3f3f3',
    '--mlv-text-2': 'color-mix(in lab, #000000 50%, color-mix(in lab, #000000 74%, #f3f3f3))', '--mlv-text-3': 'color-mix(in lab, #000000 74%, #f3f3f3)',
  }), 'light');
  assert.ok(near(plain.text2, ours(LIGHT_SECONDARY.replace('var(--mlv-text-3)', LIGHT_MIX), '#000000', '#F3F3F3')), plain.text2);
  assert.equal(plain.text3, ours(LIGHT_MIX, '#000000', '#F3F3F3'));
  // A live dark root holds the relative colour, which an SVG cannot carry: derived from the text.
  const relative = (l, text) => `lab(from ${text} ${l} a b)`;
  const darkModern = resolvePalette(rootWith({
    '--mlv-text': '#cccccc', '--mlv-surface': '#202020',
    '--mlv-text-2': relative(DARK_SECONDARY_L, '#cccccc'), '--mlv-text-3': relative(DARK_MUTED_L, '#cccccc'),
  }), 'dark');
  assert.deepEqual([darkModern.text2, darkModern.text3], ['#B3B3B3', '#9C9C9C']);
  // Dark 2026: two levels. An engine that hands the tokens back unresolved derives the same.
  const dark2026 = resolvePalette(rootWith({
    '--mlv-text': '#BBBEBF', '--mlv-surface': '#202122',
    '--mlv-text-2': DARK_SECONDARY, '--mlv-text-3': DARK_MUTED,
  }), 'dark');
  assert.deepEqual([dark2026.text2, dark2026.text3], ['#9A9D9E', '#9A9D9E']);
});

/* ── the screenshot harness's colour probe (capture.mjs, facts.inks) ───────────────────────── */

/** capture.mjs's pageHelpers(), the function the harness evaluates in the page, as source. */
async function pageHelpersSource() {
  const code = await readFile(join(WEBVIEW_ROOT, 'tools', 'screenshots', 'capture.mjs'), 'utf8');
  const start = code.indexOf('\nfunction pageHelpers() {');
  assert.ok(start >= 0, 'capture.mjs defines pageHelpers()');
  const end = code.indexOf('\n}\n', start);
  assert.ok(end > start, 'pageHelpers() ends at a closing brace in column 0');
  return code.slice(start + 1, end + 2);
}

test('the screenshot probe reads each colour token afresh, and a token it matches to no element is an error', async () => {
  // Chrome 154 under prefers-reduced-motion: reduce (viewer M4 verification, F4): base.css sets
  // every transition under .mlv-root to 0.01 ms and transition-property is `all`, so an element
  // whose colour changes after it was styled reports the transition's start value. The probe read
  // the three tokens through one <span>: --mlv-text-2 and --mlv-text-3 both came back as an
  // oklab() no element matches, and the probe reported `below45: 0` having measured nothing.
  // Modelled here: an element whose colour changes after a read, with transitions on, reports an
  // oklab() start value.
  // --mlv-text-2 as Chrome 154 computes Dark Modern's secondary text, lab(from ...): the probe
  // reads lab() as well as rgb() and color(srgb).
  const TOKENS = {
    '--mlv-text': 'rgb(204, 204, 204)',
    '--mlv-text-2': 'lab(73.0448 0.0158548 -0.000929832)',
    '--mlv-text-3': 'color(srgb 0.665098 0.665098 0.665098)',
  };
  const dom = new JSDOM('<!doctype html><html><body><div class="mlv-root">'
    + `<div data-ground="rgb(32, 32, 32)"><span data-ink="${TOKENS['--mlv-text-2']}">secondary</span></div>`
    + `<p data-ink="${TOKENS['--mlv-text']}">text</p></div></body></html>`, { runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  const real = window.getComputedStyle.bind(window);
  const styled = new WeakMap();
  window.getComputedStyle = (el, pseudo) => {
    const attr = (name) => (el.getAttribute ? el.getAttribute(name) : null);
    let color = attr('data-ink') || 'rgb(0, 0, 0)';
    const token = /^var\((--[\w-]+)\)$/.exec((el.style && el.style.color) || '');
    if (token) {
      const before = styled.get(el);
      const transitions = el.style.transition !== 'none' && el.style.transitionProperty !== 'none';
      color = before !== undefined && before !== token[1] && transitions ? 'oklab(0.845217 0 0)' : TOKENS[token[1]];
      styled.set(el, token[1]);
    }
    return { color, backgroundColor: attr('data-ground') || 'rgba(0, 0, 0, 0)', opacity: '1', visibility: real(el, pseudo).visibility || 'visible' };
  };
  window.Element.prototype.getClientRects = function () { return [{ x: 0, y: 0, width: 1, height: 1 }]; };
  window.eval(`(${await pageHelpersSource()})()`);
  const inks = window.__shots.inks();
  assert.deepEqual([inks.text.computed, inks.text2.computed, inks.text3.computed], [TOKENS['--mlv-text'], TOKENS['--mlv-text-2'], TOKENS['--mlv-text-3']]);
  assert.equal(inks.text2.elements, 1);
  assert.equal(inks.text2.error, null);
  assert.equal(inks.text2.colour, '#B3B3B3');
  assert.equal(inks.text2.below45, 0);
  assert.equal(inks.text2.lowest.ground, '#202020');
  // Nothing here is painted in --mlv-text-3: an error, not `below45: 0`.
  assert.equal(inks.text3.elements, 0);
  assert.match(inks.text3.error, /no shown element/);
  assert.equal(inks.text3.below45, null);
});
