/**
 * Node cards, group boxes and lane bands. Every element is created with
 * document.createElement / createElementNS and filled with textContent.
 */

import { el, add, locSpan } from '../dom.js';
import { locSpoken } from '../notebook.js';
import { kindIcon, uiIcon, isKnownKind, nodeGlyphKind } from '../icons.js';
import { severityBadge, severityCluster, highestSeverity, countsTotal } from '../markers.js';
import type { IssueCounts, MLNode } from '../types.js';
import type { LayoutBox, LayoutLane } from '../layout/layout.js';
import { titleLines } from '../layout/cardmetrics.js';

/**
 * An authored sublabel is the model's `detail`, up to 8000 characters. The card
 * shows one ellipsised line of it (CSS), so the DOM keeps only a prefix far
 * longer than any card can draw; the Inspector shows the whole text (viewer M1,
 * `MLNode.detail`), and the card's accessible name its first sentence.
 */
const SUB_DOM_CHARS = 240;

export interface NodeVisual {
  node: MLNode;
  box: LayoutBox;
  counts: IssueCounts;
  descendants: number;
  /** Viewer M1: some of this item's evidence cites a file the host reported stale. */
  stale: boolean;
  /** How many of its quotes do, for the words beside the mark. */
  staleQuotes?: { stale: number; total: number };
  /** Every stale quote cites a file that is unchanged in another folder (the host's root hint). */
  staleElsewhere?: boolean;
  filteredOut: boolean;
}

/**
 * "1 of 2 quotes cite a changed or missing file" — what a stale mark means, in words. In the
 * root-hint case the files did not change: "… cite a file in another folder" (COPY-1).
 */
export function staleWords(v: Pick<NodeVisual, 'stale' | 'staleQuotes' | 'staleElsewhere'>): string {
  if (!v.stale) return '';
  const q = v.staleQuotes;
  const what = v.staleElsewhere ? 'a file in another folder' : 'a changed or missing file';
  return q
    ? q.stale + ' of ' + q.total + (q.total === 1 ? ' quote cites ' : ' quotes cite ') + what
    : 'cites ' + what;
}

/**
 * The DOM id of a card or group box. Injective (RENDER-7): every character
 * outside `[A-Za-z0-9-]`, `_` included, becomes `_<hex>_`, so `load.data`,
 * `load:data` and `load_data` get three different ids and
 * `aria-activedescendant` always names the selected card.
 */
export function nodeDomId(id: string): string {
  return 'mlv-n-' + id.replace(/[^A-Za-z0-9-]/g, (c) => '_' + c.charCodeAt(0).toString(16) + '_');
}

function stageOf(node: MLNode): string {
  return node.stage || 'unknown';
}

/**
 * The card's second line: the authored detail, else the authored kind word when the renderer
 * knows it, else nothing. Viewer M2: never the basis (it used to fall back to `observed`), and
 * never the adapter's `unknown`. The SVG export draws the same line.
 */
export function cardSubline(node: MLNode): string {
  if (node.sublabel) return node.sublabel;
  return node.kind && node.kind !== 'unknown' && isKnownKind(node.kind) ? node.kind.replace(/_/g, ' ') : '';
}

/**
 * The kind word a screen reader hears before the label. A node without a kind
 * the renderer knows is a "step": the adapter's `unknown` default is not
 * something the author wrote (VIEWUI-14).
 */
function kindSpoken(n: NodeVisual['node']): string {
  if (n.kind === 'unknown' || !isKnownKind(n.kind)) return 'step';
  return n.kind.replace(/_/g, ' ');
}

export function ariaLabelFor(v: NodeVisual): string {
  const n = v.node;
  const bits: string[] = [];
  bits.push(kindSpoken(n) + ' ' + n.label);
  // Viewer M1: a step names its phase by label, as the lane does; the id is internal.
  bits.push(n.phaseLabel ? n.phaseLabel + ' phase' : stageOf(n) + ' stage');
  if (n.loc.file) bits.push(locSpoken(n.loc));
  if (n.basis) bits.push('basis ' + n.basis);
  const total = countsTotal(v.counts);
  const top = highestSeverity(v.counts);
  // VIEWUI-14: the same "finding" wording as the card's own severity badge.
  if (total > 0) bits.push(total + (total === 1 ? ' finding' : ' findings') + ', highest severity ' + top);
  if (v.descendants > 0) bits.push(v.descendants + ' nested nodes');
  if (v.stale) bits.push(staleWords(v));
  if (n.viewRole === 'boundary') bits.push('outside the current scope');
  // Viewer M1: the claim's first sentence, so the name says what the step does. The Inspector
  // has the whole text.
  const claim = n.detail ? detailSpoken(n.detail) : '';
  return bits.join(', ') + '.' + (claim ? ' ' + claim : '');
}

/** Longest spoken claim before it is cut at a word boundary. */
const DETAIL_SPOKEN_CHARS = 160;

/**
 * Words whose closing period does not end a sentence (M1-R4: "per channel, i.e. pixel values …"
 * was cut after "i.e."). Lower case, without the final period. Dotted initials such as "e.g",
 * "i.e" or "a.k.a" are recognised by shape in `abbreviationBefore`.
 */
const ABBREVIATIONS = new Set(['etc', 'vs', 'cf', 'approx', 'incl', 'esp', 'resp', 'fig', 'figs', 'eq', 'eqs', 'al']);

/** True when the period at `at` closes an abbreviation rather than a sentence. */
function abbreviationBefore(text: string, at: number): boolean {
  if (text[at] !== '.') return false;
  const word = /[A-Za-z.]*$/.exec(text.slice(0, at));
  const token = (word ? word[0] : '').toLowerCase();
  if (!token) return false;
  // Dotted initials: "e.g", "i.e", "a.k.a", "u.s".
  if (/^(?:[a-z]\.)+[a-z]$/.test(token)) return true;
  return ABBREVIATIONS.has(token);
}

/**
 * Viewer M1: a short form of an authored `detail` for an accessible name. The first sentence
 * when it ends within 160 characters; otherwise the first 160 characters, cut at a word and
 * ended with an ellipsis. A period after an abbreviation ("e.g.", "i.e.", "etc.") does not end
 * the sentence. Whitespace runs read as one space.
 */
function detailSpoken(detail: string): string {
  const text = detail.replace(/\s+/g, ' ').trim();
  if (!text) return '';
  const ends = /[.!?](?=\s|$)/g;
  for (let end = ends.exec(text); end && end.index < DETAIL_SPOKEN_CHARS; end = ends.exec(text)) {
    if (!abbreviationBefore(text, end.index)) return text.slice(0, end.index + 1);
  }
  if (text.length <= DETAIL_SPOKEN_CHARS) return text;
  const cut = text.slice(0, DETAIL_SPOKEN_CHARS);
  const space = cut.lastIndexOf(' ');
  return (space > DETAIL_SPOKEN_CHARS / 2 ? cut.slice(0, space) : cut).replace(/[\s,;:]+$/, '') + '…';
}

/** A full node card, positioned absolutely inside the world layer. */
export function buildNodeCard(v: NodeVisual, collapsedGroup: boolean): HTMLElement {
  const n = v.node;
  const groupLike = collapsedGroup;
  const card = el('div', 'mlv-node');
  card.id = nodeDomId(n.id);
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '-1');
  card.setAttribute('data-node-id', n.id);
  card.setAttribute('data-stage', stageOf(n));
  card.setAttribute('data-kind', n.kind);
  card.setAttribute('data-level', n.level);
  // Issue 14: the uncertainty treatment belongs to the authored basis, not to
  // an unfamiliar kind word (node.css `[data-basis="unresolved"]`).
  if (n.basis) card.setAttribute('data-basis', n.basis);
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

  if (top && !boundary) card.classList.add('has-issues');
  if (v.stale) card.classList.add('is-stale');
  if (v.filteredOut) card.classList.add('is-filtered');
  if (groupLike) card.classList.add('is-collapsed-group');

  add(card, el('div', 'mlv-node__rail'));
  const main = add(card, el('div', 'mlv-node__main'));
  const iconbox = add(main, el('div', 'mlv-node__iconbox'));
  iconbox.appendChild(kindIcon(nodeGlyphKind(n, groupLike)));

  const text = add(main, el('div', 'mlv-node__text'));
  const label = n.label || n.qualname || n.id;
  // Campaign 3, issue 14: truncated ONCE. The title used to be cut to 34
  // characters in the middle and then again by the CSS end ellipsis
  // ("Acquire the dataset ......"); 723 of 865 shakedown labels were longer.
  // Now the whole label is in the DOM and wraps to the lines the layout
  // reserved (`cardmetrics.titleLines`), clamped with one ellipsis. The full
  // label is in the hover card and the accessible name.
  // `data-lines` (1-3) selects the clamp in node.css; an attribute rather
  // than a custom property, because a style write per card is the slow path
  // on a 2000-node document.
  const title = add(text, el('div', 'mlv-node__title mlv-node__title--wrap', label));
  title.setAttribute('data-lines', String(titleLines(n, v.box.w)));
  // Issue 14: the sublabel is prose, cut once by the CSS end ellipsis.
  add(text, el('div', 'mlv-node__sub', cardSubline(n).slice(0, SUB_DOM_CHARS)));
  // `notebooks/leak.ipynb › cell 3, line 4` on the card. `locSpan` splits the
  // path from the cell so a card too narrow for both loses the path, never the cell.
  if (n.loc.file) add(text, locSpan('mlv-node__loc', n.loc, 'div'));

  // Viewer M2: the only chip row left is a collapsed group's count (layout/cardmetrics.ts).
  if (groupLike) {
    const row = add(text, el('div', 'mlv-node__chips'));
    add(row, el('span', 'mlv-chip', v.descendants + ' nodes'));
  }

  // Viewer M1: a corner mark with its meaning in words (title and accessible name), never colour alone.
  if (v.stale) card.appendChild(staleMark(v));

  if (groupLike) {
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
  header.appendChild(kindIcon(nodeGlyphKind(n, false), 14));
  // Issue 14: a group name is cut once, by the CSS end ellipsis.
  add(header, el('span', 'mlv-group__name', n.label || n.qualname));
  if (n.basis) add(header, el('span', 'mlv-chip mlv-chip--basis', n.basis));
  add(header, el('span', 'mlv-group__count', String(v.descendants)));
  const cluster = boundary ? null : severityCluster(v.counts, 13);
  if (cluster) header.appendChild(cluster);
  if (v.stale) {
    box.classList.add('is-stale');
    header.appendChild(staleMark(v));
  }
  box.appendChild(header);
  return box;
}

/** The stale mark (viewer M1): a warning icon whose title says what it means. */
function staleMark(v: NodeVisual): HTMLElement {
  const mark = el('span', 'mlv-node__stale');
  mark.setAttribute('data-stale', '1');
  mark.setAttribute('aria-hidden', 'true');
  mark.title = staleWords(v) + (v.staleElsewhere
    ? '. Its jumps are blocked; the notice above says which folder to add.'
    : ' since publishing. Its jumps are blocked.');
  mark.appendChild(uiIcon('warning', 12));
  return mark;
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
