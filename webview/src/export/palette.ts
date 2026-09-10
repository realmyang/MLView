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
 * The transcription is the drift risk, so it is gated: `test/export.test.mjs`
 * parses `dist/mlview.dev.css` and asserts every entry here is the last literal
 * in that token's declaration, for all three themes.
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
  fgBoundary: string;
  sevHigh: string;
  sevMedium: string;
  sevLow: string;
  sevHighInk: string;
  sevMediumInk: string;
  sevLowInk: string;
  stageConfig: string;
  stageData: string;
  stagePreprocess: string;
  stageModel: string;
  stageObjective: string;
  stageTrain: string;
  stageEval: string;
  stageDeliver: string;
  stageUnknown: string;
  /** Opacity of a lane band's stage wash, as a number in 0..1. */
  laneTint: number;
  /** Opacity of a group box's stage wash. */
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
  fgBoundary: '--mlv-fg-boundary',
  sevHigh: '--mlv-sev-high',
  sevMedium: '--mlv-sev-medium',
  sevLow: '--mlv-sev-low',
  sevHighInk: '--mlv-sev-high-ink',
  sevMediumInk: '--mlv-sev-medium-ink',
  sevLowInk: '--mlv-sev-low-ink',
  stageConfig: '--mlv-stage-config',
  stageData: '--mlv-stage-data',
  stagePreprocess: '--mlv-stage-preprocess',
  stageModel: '--mlv-stage-model',
  stageObjective: '--mlv-stage-objective',
  stageTrain: '--mlv-stage-train',
  stageEval: '--mlv-stage-eval',
  stageDeliver: '--mlv-stage-deliver',
  stageUnknown: '--mlv-stage-unknown',
};

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
  text3: '#676E81',
  link: '#2B57C4',
  accent: '#3B6CF6',
  edge: '#8C93A3',
  fgBoundary: '#6B7284',
  sevHigh: '#D0342C',
  sevMedium: '#E8A317',
  sevLow: '#2F5FD0',
  sevHighInk: '#FFFFFF',
  sevMediumInk: '#3A2500',
  sevLowInk: '#FFFFFF',
  stageConfig: '#667085',
  stageData: '#0E7C85',
  stagePreprocess: '#6A48E8',
  stageModel: '#3B6CF6',
  stageObjective: '#B05F17',
  stageTrain: '#14895F',
  stageEval: '#A3308B',
  stageDeliver: '#6E7484',
  stageUnknown: '#7A8090',
  laneTint: 0.05,
  groupTint: 0.05,
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
  fgBoundary: '#98A0B0',
  sevHigh: '#FF6169',
  sevMedium: '#F2B03C',
  sevLow: '#6E96FF',
  sevHighInk: '#1A0405',
  sevMediumInk: '#2A1A00',
  sevLowInk: '#0B1020',
  stageConfig: '#8B93A7',
  stageData: '#2DC5D0',
  stagePreprocess: '#9E86FF',
  stageModel: '#6E96FF',
  stageObjective: '#F0954A',
  stageTrain: '#34C08A',
  stageEval: '#E169C9',
  stageDeliver: '#8B93A7',
  stageUnknown: '#8B93A7',
  laneTint: 0.1,
  groupTint: 0.09,
};

/**
 * High contrast drops every wash and every hue that is not load-bearing. It
 * does NOT redeclare the stage or severity hues, so those stay exactly as the
 * light branch declares them — which is why this is an override map rather than
 * a third full table.
 */
const HC_OVERRIDES: Partial<Palette> = {
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
  fgBoundary: '#FFFFFF',
  laneTint: 0,
  groupTint: 0,
};

export const EXPORT_PALETTES: Record<ThemeKind, Palette> = {
  light: LIGHT,
  dark: { ...LIGHT, ...DARK_OVERRIDES },
  hc: { ...LIGHT, ...HC_OVERRIDES },
};

export function paletteFor(theme: ThemeKind): Palette {
  return EXPORT_PALETTES[theme] || EXPORT_PALETTES.light;
}

/** The eight canonical stage ids, mapped to their palette field. */
const STAGE_FIELD: Record<string, keyof Palette> = {
  config: 'stageConfig',
  data: 'stageData',
  preprocess: 'stagePreprocess',
  model: 'stageModel',
  objective: 'stageObjective',
  train: 'stageTrain',
  eval: 'stageEval',
  deliver: 'stageDeliver',
};

/** A stage id's colour. An id this renderer never heard of gets the neutral hue. */
export function stageColor(palette: Palette, stage: string | undefined): string {
  const field = stage ? STAGE_FIELD[stage] : undefined;
  return field ? (palette[field] as string) : palette.stageUnknown;
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
  for (const field of Object.keys(PALETTE_TOKENS)) {
    const value = clean(style.getPropertyValue(PALETTE_TOKENS[field]));
    if (value) (out as unknown as Record<string, string>)[field] = value;
  }
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

/** A usable literal, or '' when the engine handed back something unresolved. */
function clean(raw: string | null | undefined): string {
  const value = (raw || '').trim();
  if (!value) return '';
  if (value.indexOf('var(') >= 0 || value.indexOf('color-mix(') >= 0) return '';
  return value;
}
