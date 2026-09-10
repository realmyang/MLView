/**
 * PERF-04 — reading a ROLLED-UP document (CONTRACTS 11.46).
 *
 * `--max-nodes` used to be a deletion: on the 525-file synthetic the default
 * kept 400 of 16 861 nodes and 255 of 8 305 edges, and 31 % of the survivors had
 * no edge at all — a disconnected dot cloud answering requirement 1 ("visualise
 * the complete workflow") with a lie. The cap is now a three-phase hierarchical
 * rollup: ops fold into their unit, units fold into a per-file summary node, and
 * only then does anything get dropped. Edges are re-pointed at the surviving
 * ancestor and parallels are merged into one carrying a `weight`, so the graph
 * stays connected at every budget and the cap becomes a zoom level.
 *
 * This module is the ONLY place in the renderer that knows the names of
 * `Node.rolledUp` (11.46 B1) and `Edge.weight` (11.46 B2). Everything else asks
 * it a question — "how many cards does this card stand for", "how heavy is this
 * cable" — so a schema that spelled them differently would move one file.
 *
 * THREE RULES, and they are honesty rules rather than drawing rules.
 *
 * 1. **A rolled-up card is not a collapsed group.** They share a VISUAL — the
 *    roadmap asked for exactly that, "reusing the existing collapsed-group
 *    visual so the viewer needs no new language", and 11.46 A3 sets
 *    `collapsedByDefault: true` on a file summary for the same reason — but a
 *    collapsed group can be opened and a rolled-up card cannot: its children are
 *    not in this document at all. So the card gets the visual and no chevron,
 *    and `rollupCaveats()` says why.
 * 2. **A weight is a count of connections, not of call sites.** `×7` means seven
 *    document edges were merged after some of them were re-pointed here from
 *    children that were folded away, and 11.46 F says the labels they disagreed
 *    on are gone rather than stored.
 * 3. **The viewer never re-rolls.** The rollup happens in the analyzer, before
 *    projection (11.2.2, unchanged, precisely so the two ports cannot disagree).
 *    Everything here reads; nothing here decides.
 *
 * Pure: no DOM, no clock, no `this`.
 */

import type { Diagnostic, MLEdge, MLGraph, MLNode } from '../types.js';

/** A weight of 1 is an ordinary edge; 11.46 B2 emits the field only at 2+. */
export const WEIGHT_MIN = 2;

/** Stroke width in px at weight 1, and the widest a cable is ever drawn. */
const STROKE_BASE = 1.5;
const STROKE_MAX = 5;

/** `attrs.rollup` on a synthesized per-file summary node (11.46 A3). */
export const FILE_ROLLUP = 'file';

/**
 * How many nodes were folded into `node`, or 0.
 *
 * 11.46 B1: an integer ≥ 1, counted TRANSITIVELY, absent when nothing was
 * folded. A negative, fractional or non-finite value is read as "not rolled up"
 * rather than believed — invariant 1.1/6 says an unknown value renders
 * generically, and a card claiming `-3 rolled up` is worse than one claiming
 * nothing.
 */
export function rollupCount(node: MLNode | null | undefined): number {
  if (!node) return 0;
  const raw = (node as { rolledUp?: unknown }).rolledUp;
  if (typeof raw !== 'number' || !isFinite(raw) || raw < 1) return 0;
  return Math.floor(raw);
}

export function isRolledUp(node: MLNode | null | undefined): boolean {
  return rollupCount(node) > 0;
}

/** True for the synthesized file summary node of 11.46 A3. */
export function isFileSummary(node: MLNode | null | undefined): boolean {
  return !!node && !!node.attrs && node.attrs.rollup === FILE_ROLLUP;
}

/**
 * How many document edges this edge stands for (11.46 B2). Absent means one, so
 * an uncapped document is byte-for-byte what it always was.
 */
export function edgeWeight(edge: MLEdge | null | undefined): number {
  if (!edge) return 1;
  const raw = (edge as { weight?: unknown }).weight;
  if (typeof raw !== 'number' || !isFinite(raw) || raw < 1) return 1;
  return Math.floor(raw);
}

/**
 * The weight of a drawn ROUTE, which may itself merge several document edges.
 *
 * 11.46 C3 forbids two edges sharing `(source, kind, target)`, so the renderer's
 * own merge in `layout/routing.ts` only ever joins edges of different KINDS, or
 * edges whose distinct endpoints collapsed into the same two boxes. Either way a
 * cable that is both merges must report the SUM, or the number on the picture is
 * smaller than the number of connections it stands for — the one direction this
 * must never err.
 */
export function routeWeight(ids: string[], byId: Map<string, MLEdge>): number {
  let total = 0;
  for (const id of ids) total += edgeWeight(byId.get(id));
  return total || ids.length || 1;
}

/** Stroke width for a weight, growing with its log so 200 is not 200 px wide. */
export function weightStroke(weight: number): number {
  if (weight < WEIGHT_MIN) return STROKE_BASE;
  const grown = STROKE_BASE + Math.log2(weight) * 0.75;
  return Math.round(Math.min(STROKE_MAX, grown) * 100) / 100;
}

/** The `×7` a weighted cable carries. */
export function weightBadgeText(weight: number): string {
  return '×' + weight;
}

/** How far off the stroke the badge is pushed when the midpoint is taken. */
const WEIGHT_NUDGE = 13;

/**
 * Where the `×7` pill goes: the route's midpoint, pushed along the route's own
 * NORMAL when a severity glyph or a loop chevron already owns that point — a
 * number drawn on top of a severity marker is two facts and one readable glyph.
 *
 * It lives here, in the module both renderers already import, because VIEW-07's
 * standing requirement is that the DOM and the SVG export cannot disagree about
 * the picture. Two copies of this arithmetic would be two pictures.
 */
export function weightBadgeAt(
  mark: { x: number; y: number },
  angle: number,
  occupied: boolean,
): { x: number; y: number } {
  if (!occupied) return { x: mark.x, y: mark.y };
  const a = typeof angle === 'number' && isFinite(angle) ? angle : 0;
  return {
    x: mark.x + Math.cos(a + Math.PI / 2) * WEIGHT_NUDGE,
    y: mark.y + Math.sin(a + Math.PI / 2) * WEIGHT_NUDGE,
  };
}

/** Pill width for a weight, so both renderers size the same rectangle. */
export function weightBadgeWidth(weight: number): number {
  return Math.round(weightBadgeText(weight).length * 5.6 + 10);
}

/** Pill height, shared for the same reason. */
export const WEIGHT_BADGE_H = 13;

/** What the whole document looks like once the cap has been applied. */
export interface RollupSummary {
  /** Cards this document actually contains. */
  drawn: number;
  /** Cards that swallowed at least one other (11.46 B1). */
  rolled: number;
  /** Nodes folded into those cards — the ones the reader cannot open. */
  folded: number;
  /** Of those cards, how many are synthesized per-file summaries (11.46 A3). */
  fileSummaries: number;
  /** Edges this document contains. */
  edges: number;
  /** Edges standing for more than one connection (11.46 B2). */
  weighted: number;
  /** Connections those weighted edges stand for, beyond the one drawn. */
  merged: number;
  /** The heaviest single cable. */
  maxWeight: number;
  /**
   * Nodes phase 3 DROPPED outright, derived from the truncated diagnostic's
   * `count` — which 11.46 D defines as folded + dropped — minus what the
   * document shows was folded. `null` means the document did not say, which is
   * not the same as zero and is worded that way.
   */
  dropped: number | null;
  /**
   * The analyzer's own `truncated` sentence, verbatim. 11.46 D makes it the
   * place the per-phase counts and any lost findings are named, so the banner
   * draws it rather than paraphrasing numbers it cannot recompute.
   */
  message: string;
}

/**
 * Read the rollup facts off a document, or `null` when nothing was rolled up.
 *
 * `stats.truncated` alone is NOT the test. It is also set by an analyzer that
 * predates this amendment, whose cap really was a deletion, and for that
 * document the old "truncated" banner is the true sentence. So a document counts
 * as rolled up on EVIDENCE — at least one folded card or one weighted edge —
 * which 11.46 C5 makes safe by forbidding either field on an untruncated
 * document.
 */
export function rollupSummary(graph: MLGraph | null | undefined): RollupSummary | null {
  if (!graph) return null;
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  let rolled = 0;
  let folded = 0;
  let fileSummaries = 0;
  for (const node of nodes) {
    const n = rollupCount(node);
    if (!n) continue;
    rolled++;
    folded += n;
    if (isFileSummary(node)) fileSummaries++;
  }
  let weighted = 0;
  let merged = 0;
  let maxWeight = 1;
  for (const edge of edges) {
    const w = edgeWeight(edge);
    if (w < WEIGHT_MIN) continue;
    weighted++;
    merged += w - 1;
    if (w > maxWeight) maxWeight = w;
  }
  if (!rolled && !weighted) return null;
  const note = truncationNote(graph.diagnostics || []);
  return {
    drawn: nodes.length,
    rolled,
    folded,
    fileSummaries,
    edges: edges.length,
    weighted,
    merged,
    maxWeight,
    dropped: droppedFrom(note, folded),
    message: note ? note.message || '' : '',
  };
}

/**
 * The cap's own diagnostic. 11.46 C4 guarantees at least one on a truncated
 * document; the FIRST is used, because a second would be a second cap and there
 * is only ever one.
 */
function truncationNote(diagnostics: Diagnostic[]): Diagnostic | null {
  for (const d of diagnostics) {
    // 11.2 step 10 appends a SECOND `truncated` note to a scoped view of a
    // capped document ("capped before scoping"). That one carries no `count`,
    // so preferring a counted one keeps the arithmetic below on the cap's own.
    if (d.kind === 'truncated' && typeof d.count === 'number') return d;
  }
  for (const d of diagnostics) {
    if (d.kind === 'truncated') return d;
  }
  return null;
}

/**
 * `dropped = count − folded`, per 11.46 D ("`Diagnostic.count` stays the number
 * of nodes that are not in the emitted document (folded + dropped)").
 *
 * Anything that does not arithmetically work out — no diagnostic, no count, or a
 * count below what the document itself shows was folded — is reported as "the
 * document does not say" rather than as a number this module invented.
 */
function droppedFrom(note: Diagnostic | null, folded: number): number | null {
  if (!note || typeof note.count !== 'number' || !isFinite(note.count)) return null;
  const missing = Math.floor(note.count);
  if (missing < folded) return null;
  return missing - folded;
}

/** The banner headline: what this document IS, in one sentence. */
export function rollupHeadline(s: RollupSummary): string {
  const parts: string[] = [];
  if (s.folded) {
    parts.push(
      s.folded + (s.folded === 1 ? ' node was folded into ' : ' nodes were folded into ') +
        s.rolled + (s.rolled === 1 ? ' card' : ' cards'),
    );
  }
  if (s.merged) {
    parts.push(
      s.merged + (s.merged === 1 ? ' parallel connection was' : ' parallel connections were') + ' merged into ' +
        s.weighted + (s.weighted === 1 ? ' weighted edge' : ' weighted edges'),
    );
  }
  const body = parts.length ? parts.join(' and ') : 'the graph was folded to fit the node budget';
  const tail =
    s.dropped === 0
      ? ' Nothing was dropped.'
      : s.dropped === null
        ? ' This document does not say whether anything was dropped as well.'
        : ' ' + s.dropped + ' node(s) were dropped as well, after the rollup ran out of levels.';
  return 'Rolled up to ' + s.drawn + ' nodes: ' + body + ' — folded, not deleted.' + tail;
}

/**
 * What a rolled-up document CANNOT tell you — 11.46 F, in the reader's words,
 * plus the two blind spots that belong to this renderer rather than to the
 * analyzer.
 *
 * The standing acceptance criterion for this round is that every change states
 * what it could not do. Each line here is conditional on the thing it is about,
 * because a caveat that does not apply is noise that teaches a reader to skip
 * the block.
 */
export function rollupCaveats(s: RollupSummary): string[] {
  const out: string[] = [];
  if (s.rolled) {
    out.push(
      'A rolled-up card cannot be opened: what it swallowed is not in this document, so those ' +
        'locations, ports, attributes and nesting are not here to draw. The count is the whole ' +
        'disclosure — raise --max-nodes, or scope to one part of the project, to see inside one.',
    );
  }
  if (s.fileSummaries) {
    out.push(
      s.fileSummaries + ' of these ' + (s.fileSummaries === 1 ? 'card is a whole file summarised' : 'cards are whole files summarised') +
        ', whose stage and kind are a MAJORITY VOTE over what was inside. A file of 16 layers and ' +
        '14 metrics is drawn as a model card, and nothing here says the vote was close.',
    );
  }
  if (s.weighted) {
    out.push(
      'A weight counts CONNECTIONS, not call sites: ' + weightBadgeText(s.maxWeight) +
        ' on the heaviest cable means that many document edges were merged into it, some re-pointed ' +
        'here from children that were folded away — and the variable names they disagreed on are ' +
        'gone rather than stored.',
    );
  }
  if (s.dropped === null) {
    out.push(
      'This document does not say how many nodes, if any, were dropped outright after the rollup ' +
        'ran out of levels, so "folded" is what is claimed here and "nothing was lost" is not.',
    );
  } else if (s.dropped > 0) {
    out.push(
      s.dropped + ' node(s) really are absent rather than folded, and a missing-step ghost among ' +
        'them took its empty slot with it — its finding survives, re-anchored to the card above it.',
    );
  }
  out.push(
    'Every finding still resolves to a card, but a finding on a folded node now sits on the card ' +
      'that swallowed it: the badge points at the parent and the real line number is in the rail.',
  );
  out.push(
    'The fold order — fewest findings first, biggest group first — is a defensible heuristic, not ' +
      'a measurement of what a reader wanted to keep, and no gate would notice a better one.',
  );
  return out;
}

/** The card's count chip: `7 rolled up`, never `7 nodes` — that is a group. */
export function rollupChipText(count: number): string {
  return count + ' rolled up';
}

/** The same fact for a screen reader, where a chip is just three glyphs. */
export function rollupSpoken(count: number): string {
  return count + (count === 1 ? ' node folded into this card' : ' nodes folded into this card') +
    ', which cannot be opened';
}
