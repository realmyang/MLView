/**
 * SVG primitives for the export renderer (VIEW-07).
 *
 * Strings and arithmetic only — no DOM, no measurement, no state. `export/svg.ts`
 * owns the picture; this owns the pen: escaping, the font stacks and the
 * average-advance ellipsis, the two rectangle helpers the region crop needs, and
 * the three severity marks that appear on cards, group headers and lane headers
 * alike.
 *
 * It exists because `svg.ts` crossed 600 lines with the pen and the picture in
 * one file, and the pen is the half nothing about the diagram depends on.
 */

import { SEVERITY_INK, SEVERITY_SHAPE, SEVERITY_ORDER, countsTotal, highestSeverity, normalizeSeverity } from '../markers.js';
import { severityColor, severityInk, Palette } from './palette.js';
import type { Rect } from '../render/canvas.js';
import type { IssueCounts } from '../types.js';

/**
 * Generic families only — VIEW-07 forbids embedding a webfont, and a consumer
 * that has none of the named families still gets the generic keyword.
 */
export const EXPORT_SANS =
  "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
export const EXPORT_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

/** Average advance as a fraction of the em, per face. Used only to ellipsise. */
const ADVANCE_SANS = 0.51;
const ADVANCE_SANS_BOLD = 0.55;
const ADVANCE_MONO = 0.6;
/**
 * Uppercase is much wider than the mixed-case average, and the lane header is
 * the one place the export sets an all-caps string. Measured in Chromium: the
 * mixed-case factor put "CONFIGURATION" 14 px short and the node count landed
 * on top of the label.
 */
export const ADVANCE_CAPS = 0.72;

export interface TextOptions {
  size: number;
  fill: string;
  weight?: number;
  mono?: boolean;
  italic?: boolean;
  letterSpacing?: number;
}

export function text(value: string, x: number, y: number, o: TextOptions): string {
  if (!value) return '';
  return (
    '<text x="' + num(x) + '" y="' + num(y) + '" font-size="' + num(o.size) + '" fill="' + esc(o.fill) + '"' +
    (o.weight ? ' font-weight="' + o.weight + '"' : '') +
    (o.mono ? ' font-family="' + esc(EXPORT_MONO) + '"' : '') +
    (o.italic ? ' font-style="italic"' : '') +
    (o.letterSpacing ? ' letter-spacing="' + num(o.letterSpacing) + '"' : '') +
    '>' + esc(value) + '</text>'
  );
}

/** A 16x16 line-art glyph from `icons.ts`, scaled and stroked in one colour. */
export function glyphPath(d: string, x: number, y: number, scale: number, colour: string, strokeWidth: number): string {
  return (
    '<path d="' + esc(d) + '" transform="translate(' + num(x) + ',' + num(y) + ') scale(' + num(scale) +
    ')" fill="none" stroke="' + esc(colour) + '" stroke-width="' + num(strokeWidth) +
    '" stroke-linecap="round" stroke-linejoin="round"/>'
  );
}

/** Average-advance width. Only ever used to decide where to put an ellipsis. */
export function width(value: string, fontPx: number, mono: boolean, bold: boolean): number {
  const factor = mono ? ADVANCE_MONO : bold ? ADVANCE_SANS_BOLD : ADVANCE_SANS;
  return value.length * fontPx * factor;
}

export function ellipsise(value: string, maxPx: number, fontPx: number, mono: boolean, bold: boolean): string {
  if (width(value, fontPx, mono, bold) <= maxPx) return value;
  let keep = value.length;
  while (keep > 1 && width(value.slice(0, keep) + '…', fontPx, mono, bold) > maxPx) keep--;
  return value.slice(0, Math.max(1, keep)) + '…';
}

/* ── severity marks ─────────────────────────────────────────────────────── */

/**
 * One severity glyph: the shape plus its ink letter, from the SAME two path
 * tables `markers.ts` draws the DOM glyph from. High contrast drops the fill to
 * a stroke exactly as `styles/node.css` does, with the width divided by the
 * scale so it lands at the 2 px `vector-effect: non-scaling-stroke` would give.
 */
export function severityGlyphMarkup(severity: string, x: number, y: number, size: number, palette: Palette, hc: boolean): string {
  const sev = normalizeSeverity(severity);
  const scale = size / 18;
  const colour = severityColor(palette, sev);
  const shape = hc
    ? '<path d="' + esc(SEVERITY_SHAPE[sev]) + '" fill="none" stroke="' + esc(colour) +
      '" stroke-width="' + num(2 / scale) + '"/>'
    : '<path d="' + esc(SEVERITY_SHAPE[sev]) + '" fill="' + esc(colour) + '"/>';
  const ink =
    '<path d="' + esc(SEVERITY_INK[sev]) + '" fill="' + esc(hc ? colour : severityInk(palette, sev)) + '"/>';
  return '<g transform="translate(' + num(x) + ',' + num(y) + ') scale(' + num(scale) + ')">' + shape + ink + '</g>';
}

/** The node badge: highest glyph, plus the total when there is more than one. */
export function badge(counts: IssueCounts, right: number, top: number, palette: Palette, hc: boolean): string {
  const sev = highestSeverity(counts);
  if (!sev) return '';
  const total = countsTotal(counts);
  const countText = total > 1 ? String(total) : '';
  const w = 8 + 18 + (countText ? width(countText, 10.5, false, true) + 4 : 0);
  const x = right - w;
  const out = [
    '<rect x="' + num(x) + '" y="' + num(top) + '" width="' + num(w) + '" height="20" rx="10" fill="' +
      esc(palette.surface) + '" stroke="' + esc(severityColor(palette, sev)) + '" stroke-opacity="0.45" stroke-width="1"/>',
    severityGlyphMarkup(sev, x + 4, top + 1, 18, palette, hc),
  ];
  if (countText) out.push(text(countText, x + 24, top + 14, { size: 10.5, fill: palette.text2, weight: 650 }));
  return out.join('');
}

/** The header cluster: up to three glyphs with their counts, highest first. */
export function cluster(counts: IssueCounts, right: number, middle: number, size: number, palette: Palette, hc: boolean): string {
  const items: { sev: string; n: number }[] = [];
  for (const sev of SEVERITY_ORDER) {
    if (counts[sev] > 0) items.push({ sev, n: counts[sev] });
  }
  if (!items.length) return '';
  let total = 0;
  for (const item of items) total += size + 2 + width(String(item.n), 10.5, false, false) + 6;
  let x = right - total;
  const out: string[] = [];
  for (const item of items) {
    out.push(severityGlyphMarkup(item.sev, x, middle - size / 2, size, palette, hc));
    x += size + 2;
    out.push(text(String(item.n), x, middle + 3.5, { size: 10.5, fill: palette.text2 }));
    x += width(String(item.n), 10.5, false, false) + 6;
  }
  return out.join('');
}

/* ── rectangles ─────────────────────────────────────────────────────────── */

export function boundsOf(points: { x: number; y: number }[]): Rect {
  if (!points.length) return { x: 0, y: 0, w: 0, h: 0 };
  let minX = points[0].x;
  let minY = points[0].y;
  let maxX = points[0].x;
  let maxY = points[0].y;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

export function pad(rect: Rect, by: number): Rect {
  return { x: rect.x - by, y: rect.y - by, w: rect.w + by * 2, h: rect.h + by * 2 };
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function normalizeRect(rect: Rect): Rect {
  return {
    x: round2(rect.x),
    y: round2(rect.y),
    w: round2(Math.max(1, rect.w)),
    h: round2(Math.max(1, rect.h)),
  };
}

export function round2(v: number): number {
  return Math.round((isFinite(v) ? v : 0) * 100) / 100;
}

export function num(v: number): string {
  return String(round2(v));
}

/** XML escaping. Attribute and text content go through the same five entities. */
export function esc(value: string): string {
  let out = '';
  const s = String(value === undefined || value === null ? '' : value);
  for (let i = 0; i < s.length; i++) {
    const ch = s.charAt(i);
    if (ch === '&') out += '&amp;';
    else if (ch === '<') out += '&lt;';
    else if (ch === '>') out += '&gt;';
    else if (ch === '"') out += '&quot;';
    else if (ch === "'") out += '&apos;';
    else if (ch < ' ' && ch !== '\n' && ch !== '\t') out += ' ';
    else out += ch;
  }
  return out;
}
