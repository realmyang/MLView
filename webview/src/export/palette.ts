/**
 * Theme tokens, resolved to literal colours (VIEW-07).
 *
 * An exported SVG has to open in Inkscape, in a PR description and in a slide
 * deck, none of which have this app's stylesheet — so every paint the export
 * writes is a literal, never a `var(--mlv-…)` and never a `color-mix()`.
 *
 * Two sources, in this order:
 *
 *   1. THE LIVE ROOT. `getComputedStyle(root).getPropertyValue('--mlv-text')`
 *      returns the *substituted* value of a custom property, so in a VS Code
 *      webview it yields the colour the user's actual theme supplied through
 *      `var(--vscode-…, fallback)`. An export therefore looks like the app the
 *      reader was looking at, not like our default palette.
 *   2. THE TABLE BELOW, which is the literal fallback chain of
 *      `styles/tokens.css` transcribed once. It serves jsdom, a mount before
 *      first paint, and any engine that declines to compute a custom property.
 *
 * The transcription is the drift risk, and no automated test checks it (the
 * gate that did was removed with the analyzer, and `dist/mlview.dev.css` is no
 * longer built): keep every entry equal to the last literal in that token's
 * declaration in `styles/tokens.css`, for all three themes, by hand.
 */

import type { ThemeKind } from '../types.js';

export interface Palette {
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  borderStrong: string;
  text: string;
  text2: string;
  text3: string;
  link: string;
  accent: string;
  edge: string;
  sevHigh: string;
  sevMedium: string;
  sevLow: string;
  sevHighInk: string;
  sevMediumInk: string;
  sevLowInk: string;
  stageUnknown: string;
  /**
   * Viewer M2: a card's border, about 3:1 against the canvas (`--mlv-node-edge`, a mix of the
   * text colour into the background).
   */
  nodeEdge: string;
  /** Viewer M2: the phase tones by document order (`--mlv-phase-0` … `--mlv-phase-7`). */
  phases: string[];
  /** Opacity of a lane band's neutral wash (text colour over the background), in 0..1. */
  laneTint: number;
  /** Opacity of a group box's wash. */
  groupTint: number;
}

/** Which `--mlv-*` custom property each colour field comes from. */
export const PALETTE_TOKENS: Record<string, string> = {
  bg: '--mlv-bg',
  surface: '--mlv-surface',
  surface2: '--mlv-surface-2',
  border: '--mlv-border',
  borderStrong: '--mlv-border-strong',
  text: '--mlv-text',
  text2: '--mlv-text-2',
  text3: '--mlv-text-3',
  link: '--mlv-link',
  accent: '--mlv-accent',
  edge: '--mlv-edge',
  sevHigh: '--mlv-sev-high',
  sevMedium: '--mlv-sev-medium',
  sevLow: '--mlv-sev-low',
  sevHighInk: '--mlv-sev-high-ink',
  sevMediumInk: '--mlv-sev-medium-ink',
  sevLowInk: '--mlv-sev-low-ink',
  stageUnknown: '--mlv-stage-unknown',
  nodeEdge: '--mlv-node-edge',
};

/** Viewer M2: the phase tone tokens, in order. */
export const PHASE_TOKENS = ['--mlv-phase-0', '--mlv-phase-1', '--mlv-phase-2', '--mlv-phase-3', '--mlv-phase-4', '--mlv-phase-5', '--mlv-phase-6', '--mlv-phase-7'];

/**
 * Viewer M2: how much of the text colour styles/tokens.css mixes into the background for a
 * connection (`--mlv-edge`) and a card border (`--mlv-node-edge`). High contrast uses the
 * contrast border instead. The export recomputes the mix from the resolved text and background
 * when the live value is not a literal.
 */
export const EDGE_MIX: Record<ThemeKind, number> = { light: 0.64, dark: 0.54, hc: 1 };
export const NODE_EDGE_MIX: Record<ThemeKind, number> = { light: 0.58, dark: 0.46, hc: 1 };

/**
 * Viewer M4: in a light theme, muted text (`--mlv-text-3`) is the card surface mixed with black at
 * this share of surface, color-mix(in srgb, surface 38%, #000000). Dark themes keep
 * descriptionForeground and high contrast the text colour, so only the light palette derives it.
 */
export const TEXT3_LIGHT_MIX = 0.38;

/** The two numeric tokens, kept apart because they are opacities, not paints. */
export const TINT_TOKENS: Record<string, string> = {
  laneTint: '--mlv-lane-tint',
  groupTint: '--mlv-group-tint',
};

const LIGHT: Palette = {
  bg: '#FBFBFD',
  surface: '#FFFFFF',
  surface2: '#F3F4F8',
  border: '#E3E5EB',
  borderStrong: '#C9CDD6',
  text: '#16181D',
  text2: '#5A6070',
  text3: '#616161', // derive(): color-mix(in srgb, surface 38%, #000000), as tokens.css (viewer M4)
  link: '#2B57C4',
  accent: '#3B6CF6',
  edge: '#8C93A3',
  sevHigh: '#D0342C',
  sevMedium: '#E8A317',
  sevLow: '#2F5FD0',
  sevHighInk: '#FFFFFF',
  sevMediumInk: '#3A2500',
  sevLowInk: '#FFFFFF',
  stageUnknown: '#7A8090',
  nodeEdge: '',
  phases: ['#00796B', '#6A4FB3', '#0A693C', '#A0388F', '#558B2F', '#0B7F99', '#546E7A', '#1F6FB2'],
  laneTint: 0.025,
  groupTint: 0,
};

/** Only what `[data-theme="dark"]` actually redeclares; the rest is inherited. */
const DARK_OVERRIDES: Partial<Palette> = {
  bg: '#131417',
  surface: '#1A1C21',
  surface2: '#22252C',
  border: '#2C3038',
  borderStrong: '#3B414C',
  text: '#E6E8EE',
  text2: '#9AA1B1',
  text3: '#969DAD',
  link: '#8FB0FF',
  accent: '#6E96FF',
  edge: '#79808F',
  sevHigh: '#FF6169',
  sevMedium: '#F2B03C',
  sevLow: '#6E96FF',
  sevHighInk: '#1A0405',
  sevMediumInk: '#2A1A00',
  sevLowInk: '#0B1020',
  stageUnknown: '#8B93A7',
  phases: ['#4DB6AC', '#A48BE0', '#4CA871', '#D684C5', '#9CCC65', '#4FC3D9', '#90A4AE', '#6FA8DC'],
  laneTint: 0.035,
  groupTint: 0,
};

/**
 * High contrast drops every wash and every hue that is not load-bearing. It
 * does NOT redeclare the severity hues, so those stay exactly as the light
 * branch declares them — which is why this is an override map rather than a
 * third full table. Phases have no hue there: every tone is the contrast border.
 */
const HC_OVERRIDES: Partial<Palette> = {
  phases: ['#FFFFFF', '#FFFFFF', '#FFFFFF', '#FFFFFF', '#FFFFFF', '#FFFFFF', '#FFFFFF', '#FFFFFF'],
  bg: '#000000',
  surface: '#000000',
  surface2: '#000000',
  border: '#FFFFFF',
  borderStrong: '#FFFFFF',
  text: '#FFFFFF',
  text2: '#FFFFFF',
  text3: '#FFFFFF',
  link: '#6BB7FF',
  edge: '#FFFFFF',
  laneTint: 0,
  groupTint: 0,
};

export const EXPORT_PALETTES: Record<ThemeKind, Palette> = {
  light: derive({ ...LIGHT }, 'light'),
  dark: derive({ ...LIGHT, ...DARK_OVERRIDES }, 'dark'),
  hc: derive({ ...LIGHT, ...HC_OVERRIDES }, 'hc'),
};

export function paletteFor(theme: ThemeKind): Palette {
  const base = EXPORT_PALETTES[theme] || EXPORT_PALETTES.light;
  return { ...base, phases: base.phases.slice() };
}

/**
 * Viewer M2: a phase's colour by its document position, never by its id. Phase i takes tone
 * i mod 8, as on the canvas (`render/phase.ts`).
 */
export function phaseColor(palette: Palette, phaseIndex: number | undefined): string {
  if (phaseIndex === undefined || !palette.phases.length) return palette.stageUnknown;
  const n = palette.phases.length;
  return palette.phases[((phaseIndex % n) + n) % n] || palette.stageUnknown;
}

/** The colours the stylesheet derives with color-mix(), recomputed from the resolved text and background (and, for muted text in a light theme, the card surface). */
function derive(palette: Palette, theme: ThemeKind): Palette {
  if (theme === 'hc') {
    palette.edge = palette.border;
    palette.nodeEdge = palette.border;
    return palette;
  }
  palette.edge = mixHex(palette.text, palette.bg, EDGE_MIX[theme]) || palette.edge;
  palette.nodeEdge = mixHex(palette.text, palette.bg, NODE_EDGE_MIX[theme]) || palette.border;
  if (theme === 'light') palette.text3 = mixHex(palette.surface, '#000000', TEXT3_LIGHT_MIX) || palette.text3;
  return palette;
}

/** `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()` or `rgba()` as [r, g, b] (alpha ignored), or null. */
export function parseColor(value: string): [number, number, number] | null {
  const text = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3,8})$/.exec(text);
  if (hex) {
    const h = hex[1];
    if (h.length === 3 || h.length === 4) return [0, 1, 2].map((i) => parseInt(h[i] + h[i], 16)) as [number, number, number];
    if (h.length === 6 || h.length === 8) return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
    return null;
  }
  const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(text);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])].map((v) => Math.max(0, Math.min(255, v))) as [number, number, number];
  return null;
}

function toHex(rgb: number[]): string {
  return '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('').toUpperCase();
}

/** `a` mixed into `b` at `share` (0..1), as color-mix(in srgb, a share, b) computes it; '' when either is unreadable. */
export function mixHex(a: string, b: string, share: number): string {
  const ca = parseColor(a);
  const cb = parseColor(b);
  if (!ca || !cb) return '';
  return toHex(ca.map((v, i) => v * share + cb[i] * (1 - share)));
}

/**
 * A `color-mix(in srgb, <colour> <p>%, <colour>)` whose colours are literals (what a custom
 * property holds once its var() references are substituted), as a hex literal; '' otherwise.
 */
export function resolveColorMix(value: string): string {
  const m = /^color-mix\(\s*in srgb\s*,\s*(.+?)\s+([\d.]+)%\s*,\s*(.+?)\s*\)$/i.exec(value.trim());
  if (!m) return '';
  return mixHex(m[1], m[3], Number(m[2]) / 100);
}

export function severityColor(palette: Palette, severity: string | null): string {
  if (severity === 'high') return palette.sevHigh;
  if (severity === 'medium') return palette.sevMedium;
  if (severity === 'low') return palette.sevLow;
  return palette.edge;
}

export function severityInk(palette: Palette, severity: string | null): string {
  if (severity === 'high') return palette.sevHighInk;
  if (severity === 'medium') return palette.sevMediumInk;
  return palette.sevLowInk;
}

/**
 * Read the palette off a mounted element, falling back to the table per token.
 *
 * Per TOKEN, not per palette: a host that supplies some `--vscode-*` colours and
 * not others would otherwise force an all-or-nothing choice, and half a theme is
 * worse than either whole one. A value that still contains `var(` or `color-mix(`
 * is refused — the export may not carry an unresolved reference.
 */
export function resolvePalette(root: Element | null, theme: ThemeKind): Palette {
  const base = paletteFor(theme);
  const out: Palette = { ...base };
  const view = ownerView(root);
  if (!root || !view || typeof view.getComputedStyle !== 'function') return out;
  let style: CSSStyleDeclaration;
  try {
    style = view.getComputedStyle(root as Element);
  } catch (_e) {
    return out;
  }
  if (!style || typeof style.getPropertyValue !== 'function') return out;
  const resolved = new Set<string>();
  for (const field of Object.keys(PALETTE_TOKENS)) {
    const value = literal(style.getPropertyValue(PALETTE_TOKENS[field]));
    if (value) {
      (out as unknown as Record<string, string>)[field] = value;
      resolved.add(field);
    }
  }
  PHASE_TOKENS.forEach((token, i) => {
    const value = literal(style.getPropertyValue(token));
    if (value) out.phases[i] = value;
  });
  // The derived colours follow the theme's own text and background when the live value could
  // not be read as a literal.
  const derived = derive({ ...out }, theme);
  if (!resolved.has('edge')) out.edge = derived.edge;
  if (!resolved.has('nodeEdge')) out.nodeEdge = derived.nodeEdge;
  if (!resolved.has('text3')) out.text3 = derived.text3;
  for (const field of Object.keys(TINT_TOKENS)) {
    const value = clean(style.getPropertyValue(TINT_TOKENS[field]));
    const n = value ? Number(value) : NaN;
    if (isFinite(n) && n >= 0 && n <= 1) (out as unknown as Record<string, number>)[field] = n;
  }
  return out;
}

function ownerView(root: Element | null): (Window & typeof globalThis) | null {
  if (!root) return null;
  const doc = root.ownerDocument;
  return doc ? (doc.defaultView as (Window & typeof globalThis) | null) : null;
}

/** A literal, or a color-mix() of literals computed to one; '' for anything unresolved. */
function literal(raw: string | null | undefined): string {
  const value = (raw || '').trim();
  if (value.toLowerCase().startsWith('color-mix(')) return resolveColorMix(value);
  return clean(value);
}

/** A usable literal, or '' when the engine handed back something unresolved. */
function clean(raw: string | null | undefined): string {
  const value = (raw || '').trim();
  if (!value) return '';
  if (value.indexOf('var(') >= 0 || value.indexOf('color-mix(') >= 0) return '';
  return value;
}
