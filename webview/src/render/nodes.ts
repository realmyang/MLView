/**
 * Node cards, group boxes and lane bands. Every element is created with
 * document.createElement / createElementNS and filled with textContent.
 */

import { el, add, middleTruncate, locSpan } from '../dom.js';
import { locSpoken } from '../notebook.js';
import { kindIcon, uiIcon, isKnownKind } from '../icons.js';
import { severityBadge, severityCluster, highestSeverity, countsTotal } from '../markers.js';
import { alternativeCount, configSpoken, configSublabel, isAlternatives, resolvedConfig } from '../config/resolved.js';
import type { IssueCounts, MLNode } from '../types.js';
import type { LayoutBox, LayoutLane } from '../layout/layout.js';
import { chipCandidates } from '../layout/cardmetrics.js';

/**
 * VIEW-08. How each diff status reads on a card, and to a screen reader.
 *
 * `added` gets a LEDGE — a small tab on the card's leading edge — because it has
 * to be legible at the compact LOD where the chip row is not drawn at all, and
 * because it must not be confused with the severity badge on the opposite
 * corner. `removed` reuses the ghost outline that already means "this is not
 * here", with its own word so the two absences are told apart. `changed` gets a
 * chip, which is the lightest of the three on purpose: most changed nodes are
 * changed in one field.
 */
const DIFF_WORD: Record<string, string> = {
  added: 'added',
  removed: 'removed',
  changed: 'changed',
};

const DIFF_SPOKEN: Record<string, string> = {
  added: 'added in this change',
  removed: 'removed in this change, drawn where it used to be',
  changed: 'changed in this change',
};

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
  // NB. The candidate list is `layout/cardmetrics.ts`'s, not a second copy of
  // the same rule: the layout reserves a chip row exactly when this is
  // non-empty, and only the WIDTH budget below is a rendering decision (VW-01).
  const candidates = chipCandidates(node);
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
  // VIEW-08: a resurrected ghost is a REMOVED node, not a missing step. Saying
  // "Missing step" over it would name the wrong kind of absence.
  if (n.diffStatus === 'removed') bits.push('Removed: ' + n.label);
  else if (n.ghost) bits.push('Missing step: ' + n.label);
  else bits.push((isKnownKind(n.kind) ? n.kind.replace(/_/g, ' ') : 'node') + ' ' + n.label);
  bits.push(stageOf(n) + ' stage');
  bits.push(locSpoken(n.loc));
  // ANA-10: the resolved value, spoken. A config card that reads "batch_size"
  // to a screen reader and "batch_size = 64" on screen is two different cards.
  const config = configSpoken(n);
  if (config) bits.push(config);
  const diff = n.diffStatus ? DIFF_SPOKEN[n.diffStatus] : '';
  if (diff) bits.push(diff);
  if (n.diffStatus === 'changed' && (n.diffChanged || []).length) {
    bits.push('what changed: ' + (n.diffChanged || []).join(', '));
  }
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
  // VW-01: `height`, not `min-height`. The box `layout/cardmetrics.ts` reserved
  // is what `labels.ts` clears and what `export/svg.ts` draws, so a card that
  // grew past it put ink where the planner had promised none — 26 of 26 cards
  // on a notebook report, two overlapping pairs and 6 labels drawn over cards.
  // The reservation now counts the loc row and the chip row, so nothing is
  // clipped at our own type scale; where a host's font is bigger, the plan wins
  // and `.mlv-node__text` clips, exactly as the SVG export already did.
  card.style.height = v.box.h + 'px';

  // VIEW-08. The status is a data attribute AND a class: the attribute is what
  // tests and the export read, the class is what the stylesheet paints.
  if (n.diffStatus) {
    card.setAttribute('data-diff', n.diffStatus);
    if (DIFF_WORD[n.diffStatus]) card.classList.add('is-diff-' + n.diffStatus);
  }
  // ANA-10. `data-config-alt` is the one-of-N marker; the count is on the
  // attribute so a test can assert the card knows how many it could not choose
  // between, not merely that it drew something.
  const config = resolvedConfig(n);
  if (config && isAlternatives(config)) {
    card.setAttribute('data-config-alt', String(alternativeCount(config)));
    card.classList.add('is-alternatives');
  } else if (config && config.unresolved) {
    card.setAttribute('data-config-unresolved', '1');
  } else if (config && config.value) {
    card.setAttribute('data-config-value', config.value);
  }

  // VIEW-08 reuses the ghost VISUAL for a removed node without claiming the
  // schema's `ghost` flag, which means "a step the analyzer expected and did not
  // find" and is what 11.2 step 7 prunes on.
  if (n.ghost || n.diffStatus === 'removed') card.classList.add('is-ghost');
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
  // ANA-10: the RESOLVED value outranks the document's own sublabel, because
  // "where does batch_size come from" is the question the config lane exists to
  // answer and `download=False` is not the answer to it. Absent when the
  // analyzer resolved nothing, which leaves the card exactly as it was.
  const resolved = configSublabel(n);
  const sub = resolved || n.sublabel || (n.fqn ? n.fqn : n.kind);
  const subEl = add(text, el('div', 'mlv-node__sub', middleTruncate(sub, 40)));
  if (resolved) {
    subEl.classList.add('mlv-node__sub--config');
    // The card middle-truncates at 40 characters, so a three-candidate registry
    // or a reason sentence loses its middle. `data-config-sub` carries the
    // untruncated string and the hover shows it: a resolved value the reader
    // cannot read is not a resolved value.
    subEl.setAttribute('data-config-sub', resolved);
    subEl.title = resolved + (config && config.from ? ' · resolved from ' + config.from : '');
  }
  // NB. `notebooks/leak.ipynb > cell 3 : 4` on the card, with the flat line it
  // was translated from in the hover. `locSpan` splits the path from the cell so
  // a card too narrow for both loses the path, never the cell.
  add(text, locSpan('mlv-node__loc', n.loc, 'div'));

  // The collapsed-group count chip is PREPENDED after budgeting, so it can never
  // push the "+n" overflow chip off the end (MLV-R1-011).
  const chips = collapsedGroup
    ? [v.descendants + ' nodes'].concat(chipsFor(n, null, 14, 1))
    : chipsFor(n, chipMetrics(v.box.w - CHIP_ROW_INSET));
  // VIEW-08: the `changed` chip is PREPENDED, like the collapsed-group count, so
  // the width budget can never push the one thing a reviewer opened this view to
  // see off the end of the row.
  const diffChip = n.diffStatus === 'changed' ? changedChipText(n) : '';
  if (chips.length || diffChip) {
    const row = add(text, el('div', 'mlv-node__chips'));
    if (diffChip) {
      const chip = add(row, el('span', 'mlv-chip mlv-chip--diff mlv-chip--diff-changed', diffChip));
      chip.setAttribute('data-diff-chip', 'changed');
      chip.title = (n.diffChanged || []).length
        ? 'Changed in this diff: ' + (n.diffChanged || []).join(', ')
        : 'Changed in this diff';
    }
    for (const c of chips) add(row, el('span', 'mlv-chip', c));
  }

  // VIEW-08. The LEDGE: a tab on the leading edge of an added card, drawn as a
  // child of the CARD so it survives the compact LOD that hides the chip row —
  // the zoom level a reviewer skims a whole diff at is exactly the one where a
  // chip would have disappeared.
  if (n.diffStatus === 'added' || n.diffStatus === 'removed') {
    const ledge = add(card, el('span', 'mlv-node__ledge', DIFF_WORD[n.diffStatus]));
    ledge.setAttribute('data-ledge', n.diffStatus);
    ledge.setAttribute('aria-hidden', 'true');
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

/**
 * `changed` on its own, or `changed: issueCodes` when the overlay named ONE
 * field — which is the case a reviewer acts on. Two or more fields are counted
 * rather than listed: the card has one chip's worth of room, and the full list
 * is in the chip's own hover and in the Inspector.
 */
function changedChipText(node: MLNode): string {
  const fields = node.diffChanged || [];
  if (fields.length === 1) return 'changed: ' + fields[0];
  if (fields.length > 1) return 'changed · ' + fields.length + ' fields';
  return 'changed';
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
  // VIEW-08: an expanded group carries the same status as a card would, so a
  // function that was added does not look untouched just because it has children.
  if (n.diffStatus) {
    box.setAttribute('data-diff', n.diffStatus);
    if (DIFF_WORD[n.diffStatus]) box.classList.add('is-diff-' + n.diffStatus);
  }
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
