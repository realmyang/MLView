/**
 * Node cards, group boxes and lane bands. Every element is created with
 * document.createElement / createElementNS and filled with textContent.
 */

import { el, add, middleTruncate, fileLine } from '../dom.js';
import { kindIcon, uiIcon, isKnownKind } from '../icons.js';
import { severityBadge, severityCluster, highestSeverity, countsTotal } from '../markers.js';
import type { IssueCounts, MLNode } from '../types.js';
import type { LayoutBox, LayoutLane } from '../layout/layout.js';

export interface NodeVisual {
  node: MLNode;
  box: LayoutBox;
  counts: IssueCounts;
  descendants: number;
  stale: boolean;
  filteredOut: boolean;
}

export function nodeDomId(id: string): string {
  return 'mlv-n-' + id.replace(/[^A-Za-z0-9_-]/g, '_');
}

function stageOf(node: MLNode): string {
  return node.stage || 'unknown';
}

/**
 * Attribute chips (UX_DESIGN section 4.1), with two rules that keep them honest.
 *
 * 1. An attribute the SUBLABEL already spells out is dropped. The card used to
 *    print "CIFAR10 . download=False . train=False" and then repeat
 *    `download=False` `train=False` as chips one line below — the only
 *    redundant element on the card was also the only clipped one (MLV-R2-W11).
 * 2. What is left is budgeted by MEASURED WIDTH wherever a text metric is
 *    available, because `.mlv-node__chips` is clipped by rendered width on a
 *    fixed-width card while a character count cannot see the font. With no
 *    metric (jsdom, or before first paint) it falls back to the character
 *    budget, which is why `.mlv-node__chips .mlv-chip` also ellipsises in CSS.
 */
export interface ChipMetrics {
  /** Rendered width of `text` in px, or null when it cannot be measured. */
  measure(text: string): number | null;
  /** Width available to the chip row, in px. */
  width: number;
}

/** Per-chip horizontal chrome: padding (2x --mlv-s3), border and the flex gap. */
const CHIP_CHROME_PX = 18;

/**
 * Everything the chip row does NOT get on a card of width w: the two card
 * borders, the stage rail, the main padding, the icon box and its gap
 * (node.css `.mlv-node__main` / `.mlv-node__iconbox`).
 */
const CHIP_ROW_INSET = 60;

/**
 * Average glyph width of the chip font, measured ONCE against the live
 * stylesheet, so the budget follows the host's actual font size instead of
 * guessing (a VS Code user with a 16 px UI font clipped chips a character
 * count could never see). Returns null where nothing can be measured — jsdom,
 * or before the stylesheet lands — and the caller falls back to the character
 * budget, which is why `.mlv-node__chips .mlv-chip` also ellipsises in CSS.
 */
const CALIBRATION = 'download=False, train=True, batch_size=64, num_workers=4';
let perCharPx: number | null | undefined;

function charWidthPx(): number | null {
  if (perCharPx !== undefined) return perCharPx;
  perCharPx = null;
  try {
    const probe = el('span', 'mlv-chip');
    probe.style.position = 'absolute';
    probe.style.left = '-9999px';
    probe.style.top = '0';
    probe.style.visibility = 'hidden';
    probe.style.whiteSpace = 'pre';
    probe.style.padding = '0';
    probe.style.border = '0';
    probe.textContent = CALIBRATION;
    document.body.appendChild(probe);
    const width = probe.getBoundingClientRect().width || 0;
    document.body.removeChild(probe);
    // 5% of headroom: an average cannot know which glyphs a given chip uses.
    if (width > 0) perCharPx = (width / CALIBRATION.length) * 1.05;
  } catch (_e) {
    perCharPx = null;
  }
  return perCharPx;
}

function chipMetrics(width: number): ChipMetrics | null {
  const perChar = charWidthPx();
  if (perChar === null || width <= 0) return null;
  return {
    width,
    measure(text: string): number | null {
      return text.length * perChar;
    },
  };
}

/**
 * Exported for VIEW-07: the SVG export draws the SAME chips as the card, with
 * its own advance metric. Two budgeting rules would put a different chip row on
 * the picture you export from the one on the picture you were looking at.
 */
export function chipsFor(node: MLNode, metrics?: ChipMetrics | null, budget = 26, maxChips = 3): string[] {
  const keys = Object.keys(node.attrs || {});
  const sublabel = node.sublabel || '';
  const candidates: string[] = [];
  for (const k of keys) {
    const text = k + '=' + node.attrs[k];
    if (sublabel.indexOf(text) >= 0) continue;
    candidates.push(text);
  }
  const out: string[] = [];
  let usedChars = 0;
  let usedPx = 0;
  let taken = 0;
  for (const text of candidates) {
    if (taken >= maxChips) break;
    const px = metrics ? metrics.measure(text) : null;
    if (metrics && px !== null) {
      const next = usedPx + px + CHIP_CHROME_PX;
      if (taken > 0 && next > metrics.width) break;
      usedPx = next;
    } else {
      if (taken > 0 && usedChars + text.length > budget) break;
      usedChars += text.length + 1;
    }
    out.push(text.length > budget ? text.slice(0, Math.max(3, budget - 1)) + '…' : text);
    taken++;
  }
  const rest = candidates.length - taken;
  if (rest > 0) out.push('+' + rest);
  return out;
}

export function ariaLabelFor(v: NodeVisual): string {
  const n = v.node;
  const bits: string[] = [];
  if (n.ghost) bits.push('Missing step: ' + n.label);
  else bits.push((isKnownKind(n.kind) ? n.kind.replace(/_/g, ' ') : 'node') + ' ' + n.label);
  bits.push(stageOf(n) + ' stage');
  bits.push(n.loc.file + ' line ' + n.loc.line);
  const total = countsTotal(v.counts);
  const top = highestSeverity(v.counts);
  if (total > 0) bits.push(total + (total === 1 ? ' issue' : ' issues') + ', highest severity ' + top);
  if (v.descendants > 0) bits.push(v.descendants + ' nested nodes');
  if (n.dynamic) bits.push('partially resolved');
  if (n.viewRole === 'boundary') bits.push('outside the current scope');
  return bits.join(', ') + '.';
}

/** A full node card, positioned absolutely inside the world layer. */
export function buildNodeCard(v: NodeVisual, collapsedGroup: boolean): HTMLElement {
  const n = v.node;
  const card = el('div', 'mlv-node');
  card.id = nodeDomId(n.id);
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '-1');
  card.setAttribute('data-node-id', n.id);
  card.setAttribute('data-stage', stageOf(n));
  card.setAttribute('data-kind', n.kind);
  card.setAttribute('data-level', n.level);
  const top = highestSeverity(v.counts);
  // A BOUNDARY stub carries no severity badge: its findings are out of scope,
  // and a badge you cannot open is a lie (FEATURES 3.7).
  const boundary = n.viewRole === 'boundary';
  if (top && !boundary) card.setAttribute('data-sev', top);
  if (n.viewRole) card.setAttribute('data-view-role', n.viewRole);
  card.setAttribute('aria-label', ariaLabelFor(v));
  card.style.left = v.box.x + 'px';
  card.style.top = v.box.y + 'px';
  card.style.width = v.box.w + 'px';
  card.style.minHeight = v.box.h + 'px';

  if (n.ghost) card.classList.add('is-ghost');
  if (n.dynamic) card.classList.add('is-dynamic');
  if (typeof n.confidence === 'number' && n.confidence < 0.6) card.classList.add('is-lowconf');
  if (top && !boundary) card.classList.add('has-issues');
  if (v.stale) card.classList.add('is-stale');
  if (v.filteredOut) card.classList.add('is-filtered');
  if (collapsedGroup) card.classList.add('is-collapsed-group');

  add(card, el('div', 'mlv-node__rail'));
  const main = add(card, el('div', 'mlv-node__main'));
  const iconbox = add(main, el('div', 'mlv-node__iconbox'));
  iconbox.appendChild(kindIcon(collapsedGroup ? 'artifact' : n.kind));

  const text = add(main, el('div', 'mlv-node__text'));
  add(text, el('div', 'mlv-node__title', middleTruncate(n.label || n.qualname || n.id, 34)));
  const sub = n.sublabel || (n.fqn ? n.fqn : n.kind);
  add(text, el('div', 'mlv-node__sub', middleTruncate(sub, 40)));
  add(text, el('div', 'mlv-node__loc', fileLine(n.loc)));

  // The collapsed-group count chip is PREPENDED after budgeting, so it can never
  // push the "+n" overflow chip off the end (MLV-R1-011).
  const chips = collapsedGroup
    ? [v.descendants + ' nodes'].concat(chipsFor(n, null, 14, 1))
    : chipsFor(n, chipMetrics(v.box.w - CHIP_ROW_INSET));
  if (chips.length) {
    const row = add(text, el('div', 'mlv-node__chips'));
    for (const c of chips) add(row, el('span', 'mlv-chip', c));
  }

  if (collapsedGroup) {
    const cluster = severityCluster(v.counts, 14);
    if (cluster) {
      cluster.classList.add('mlv-node__cluster');
      cluster.style.position = 'absolute';
      cluster.style.top = '-8px';
      cluster.style.right = '-6px';
      cluster.style.padding = '1px 6px';
      cluster.style.borderRadius = 'var(--mlv-r-pill)';
      cluster.style.background = 'var(--mlv-surface)';
      cluster.style.boxShadow = 'var(--mlv-sh-1)';
      card.appendChild(cluster);
    }
  } else if (!boundary) {
    const badge = severityBadge(v.counts, 18);
    if (badge) card.appendChild(badge);
  }
  return card;
}

/** An expanded group: the dashed container plus its header strip. */
export function buildGroupBox(v: NodeVisual): HTMLElement {
  const n = v.node;
  const box = el('div', 'mlv-group');
  box.id = nodeDomId(n.id);
  box.setAttribute('data-node-id', n.id);
  box.setAttribute('data-group', '1');
  box.setAttribute('data-stage', stageOf(n));
  box.setAttribute('data-depth', String(Math.min(2, v.box.depth)));
  if (n.viewRole) box.setAttribute('data-view-role', n.viewRole);
  // A boundary FRAME is as badge-free as a boundary card: what it contains is
  // outside the scope, so an aggregated count would point at nothing openable.
  const boundary = n.viewRole === 'boundary';
  const top = boundary ? null : highestSeverity(v.counts);
  if (top) box.setAttribute('data-sev', top);
  box.style.left = v.box.x + 'px';
  box.style.top = v.box.y + 'px';
  box.style.width = v.box.w + 'px';
  box.style.height = v.box.h + 'px';

  // A div with role=button, not a <button>, so the chevron inside it can be a real
  // focusable button of its own (nesting buttons is invalid HTML). UX_DESIGN §2.4
  // wants "chevron click collapses, header click selects" — MLV-R1-010.
  const header = el('div', 'mlv-group__header');
  header.setAttribute('role', 'button');
  header.setAttribute('tabindex', '-1');
  header.setAttribute('aria-expanded', 'true');
  header.setAttribute('aria-label', ariaLabelFor(v) + ' Group, expanded. Double-click to collapse.');
  const chevBtn = el('button', 'mlv-group__chevron-btn') as HTMLButtonElement;
  chevBtn.type = 'button';
  chevBtn.tabIndex = -1;
  chevBtn.setAttribute('aria-label', 'Collapse ' + (n.label || n.qualname));
  const chev = uiIcon('chevron', 12);
  chev.setAttribute('class', 'mlv-uicon mlv-group__chevron');
  chevBtn.appendChild(chev);
  header.appendChild(chevBtn);
  header.appendChild(kindIcon(n.kind, 14));
  add(header, el('span', 'mlv-group__name', middleTruncate(n.label || n.qualname, 42)));
  add(header, el('span', 'mlv-group__count', String(v.descendants)));
  const cluster = boundary ? null : severityCluster(v.counts, 13);
  if (cluster) header.appendChild(cluster);
  box.appendChild(header);
  return box;
}

export function buildLane(lane: LayoutLane, counts: IssueCounts, absent: boolean): HTMLElement {
  const band = el('div', 'mlv-lane');
  band.setAttribute('data-lane-id', lane.id);
  band.setAttribute('data-stage', lane.id);
  band.style.left = lane.x + 'px';
  band.style.top = lane.y + 'px';
  band.style.width = lane.w + 'px';
  band.style.height = lane.h + 'px';
  band.style.setProperty('--mlv-lane-header-h', lane.headerH + 'px');
  if (absent) band.classList.add('is-absent');

  const header = add(band, el('div', 'mlv-lane__header'));
  add(header, el('span', 'mlv-lane__label', lane.label));
  add(header, el('span', 'mlv-lane__count', lane.nodeCount + (lane.nodeCount === 1 ? ' node' : ' nodes')));
  add(header, el('span', 'mlv-lane__spacer'));
  const cluster = severityCluster(counts, 13);
  if (cluster) header.appendChild(cluster);
  return band;
}
