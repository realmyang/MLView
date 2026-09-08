/**
 * Severity markers — UX_DESIGN section 5, spec requirement 3.
 *
 * Three DIFFERENT shapes so severity is never colour-only:
 *   low    → filled circle with a white "i"      (the quietest mark)
 *   medium → filled amber triangle with a dark "!"
 *   high   → filled red octagon with a white "!" (the stop-sign silhouette)
 *
 * Rendered at 18px (node badge), 14px (group / lane header), 12px (rail rows).
 */

import { SVG_NS, svg, setAttrs, el } from './dom.js';
import type { IssueCounts, Severity } from './types.js';

/** The three shape outlines. Asserted structurally different by markers.test.mjs. */
export const SEVERITY_SHAPE: Record<Severity, string> = {
  low: 'M9 2A7 7 0 1 0 9 16A7 7 0 0 0 9 2Z',
  medium: 'M9.9 2.75a1.04 1.04 0 0 0-1.8 0L1.5 14.6a1.04 1.04 0 0 0 .9 1.56h13.2a1.04 1.04 0 0 0 .9-1.56Z',
  high: 'M6.05 1.4h5.9L16.6 6.05v5.9L11.95 16.6h-5.9L1.4 11.95v-5.9Z',
};

/** The letter inside each shape: "i" for low, "!" for medium and high. */
export const SEVERITY_INK: Record<Severity, string> = {
  low: 'M9 4.3a1.08 1.08 0 1 0 0 2.16A1.08 1.08 0 0 0 9 4.3ZM7.94 7.65h2.12v5.7H7.94Z',
  medium: 'M7.95 6.45h2.1l-.28 4.62h-1.54ZM9 12.1a1.12 1.12 0 1 0 0 2.24A1.12 1.12 0 0 0 9 12.1Z',
  high: 'M7.94 4.5h2.12l-.3 6.05h-1.52ZM9 11.7a1.15 1.15 0 1 0 0 2.3A1.15 1.15 0 0 0 9 11.7Z',
};

export const SEVERITY_ORDER: Severity[] = ['high', 'medium', 'low'];
export const SEVERITY_WORD: Record<Severity, string> = { high: 'high', medium: 'medium', low: 'low' };

export function isSeverity(value: string): value is Severity {
  return value === 'low' || value === 'medium' || value === 'high';
}

/** Unknown severities degrade to `low` rather than throwing (invariant 1.1/6). */
export function normalizeSeverity(value: string): Severity {
  return isSeverity(value) ? value : 'low';
}

export function emptyCounts(): IssueCounts {
  return { low: 0, medium: 0, high: 0 };
}

export function addCounts(into: IssueCounts, from: IssueCounts): IssueCounts {
  into.low += from.low;
  into.medium += from.medium;
  into.high += from.high;
  return into;
}

export function countsTotal(c: IssueCounts): number {
  return c.low + c.medium + c.high;
}

export function highestSeverity(c: IssueCounts): Severity | null {
  if (c.high > 0) return 'high';
  if (c.medium > 0) return 'medium';
  if (c.low > 0) return 'low';
  return null;
}

/** One severity glyph as a standalone <svg>. */
export function severityGlyph(severity: string, size = 18, label?: string): SVGElement {
  const sev = normalizeSeverity(severity);
  const root = svg('svg', {
    class: 'mlv-glyph mlv-glyph--' + sev,
    viewBox: '0 0 18 18',
    width: size,
    height: size,
    role: 'img',
    'aria-label': label || SEVERITY_WORD[sev] + ' severity',
  });
  const shape = document.createElementNS(SVG_NS, 'path');
  setAttrs(shape, {
    class: 'mlv-glyph__shape',
    d: SEVERITY_SHAPE[sev],
    'vector-effect': 'non-scaling-stroke',
  });
  const ink = document.createElementNS(SVG_NS, 'path');
  setAttrs(ink, { class: 'mlv-glyph__ink', d: SEVERITY_INK[sev] });
  root.appendChild(shape);
  root.appendChild(ink);
  return root;
}

function ariaForCounts(counts: IssueCounts): string {
  const total = countsTotal(counts);
  const top = highestSeverity(counts);
  return total + (total === 1 ? ' issue' : ' issues') + ', highest severity ' + (top ? SEVERITY_WORD[top] : 'none');
}

/**
 * Node badge: one pill carrying the HIGHEST glyph and, when more than one issue
 * is present, the TOTAL count. Anchored top-right, overhanging the card.
 */
export function severityBadge(counts: IssueCounts, size = 18): HTMLElement | null {
  const top = highestSeverity(counts);
  if (!top) return null;
  const total = countsTotal(counts);
  const pill = el('div', 'mlv-badge mlv-badge--' + top);
  pill.setAttribute('role', 'img');
  pill.setAttribute('aria-label', ariaForCounts(counts));
  pill.appendChild(severityGlyph(top, size, ''));
  if (total > 1) pill.appendChild(el('span', 'mlv-badge__count', String(total)));
  return pill;
}

/**
 * Group / lane header cluster: up to three glyphs with their individual counts,
 * highest first. This is the aggregated view (spec R3.2).
 */
export function severityCluster(counts: IssueCounts, size = 14): HTMLElement | null {
  if (countsTotal(counts) === 0) return null;
  const wrap = el('div', 'mlv-cluster');
  wrap.setAttribute('role', 'img');
  wrap.setAttribute('aria-label', ariaForCounts(counts));
  for (const sev of SEVERITY_ORDER) {
    const n = counts[sev];
    if (n <= 0) continue;
    const item = el('span', 'mlv-cluster__item mlv-cluster__item--' + sev);
    item.appendChild(severityGlyph(sev, size, ''));
    item.appendChild(el('span', 'mlv-cluster__count', String(n)));
    wrap.appendChild(item);
  }
  return wrap;
}

/** Edge marker: the glyph on a surface-coloured disc at the path midpoint. */
export function edgeMarker(severity: string, size = 16): SVGElement {
  const sev = normalizeSeverity(severity);
  const g = svg('g', { class: 'mlv-edge-marker mlv-edge-marker--' + sev, role: 'img' });
  g.setAttribute('aria-label', SEVERITY_WORD[sev] + ' severity issue on this connection');
  const disc = svg('circle', { class: 'mlv-edge-marker__disc', r: size / 2 + 1.5, cx: 0, cy: 0 });
  g.appendChild(disc);
  const inner = severityGlyph(sev, size, '');
  inner.setAttribute('x', String(-size / 2));
  inner.setAttribute('y', String(-size / 2));
  inner.removeAttribute('role');
  inner.removeAttribute('aria-label');
  inner.setAttribute('aria-hidden', 'true');
  g.appendChild(inner);
  return g;
}
