/**
 * How tall a node card actually is (VW-01).
 *
 * `layout.ts` reserves a box, `labels.ts` clears that box, `export/svg.ts`
 * draws that box and `render/nodes.ts` paints the card into it. All four have
 * to agree, and until this module existed they did not: `nodeSize()` returned
 * a flat `NODE_H = 72` for every leaf while the card set `min-height: 72px` and
 * then grew to whatever its content needed. On the shipped demo exactly one
 * card carries an attribute chip row, so the 24 px of extra ink collided with
 * nothing and every gate stayed green; on a notebook report EVERY node carries
 * `attrs.cell` / `attrs.cellLine`, so all 26 cards drew 96 px against a plan of
 * 72 — two card pairs physically overlapped and 6 of 26 edge labels were placed
 * on top of a card, because the declutter pass was clearing rectangles nobody
 * painted.
 *
 * So the reservation is now DERIVED FROM THE CONTENT, from the same predicates
 * the renderer uses to decide what to draw:
 *
 *   padding + border                                22.0
 *   .mlv-node__title      13/1.35                   17.6
 *   .mlv-node__sub        11/1.35                   14.8
 *   .mlv-node__loc        10 mono                   15.8   (only with a loc)
 *   .mlv-node__chips      18 px line + 4 px margin  26.0   (only with chips)
 *
 * which is 70.1 for a three-row card (`NODE_H` 72, unchanged), 54.4 for a card
 * with no loc line (`NODE_H_GHOST` 60, unchanged) and 96.1 with the chip row
 * (`+ NODE_CHIP_ROW_H`). The three constants keep the ~2 px of headroom they
 * have always had; the numbers above were measured in Chromium at 1600×1000 on
 * a report of `analyzer/tests/fixtures/notebooks/`.
 *
 * WHAT THIS CANNOT KNOW: the reservation is still a constant, so a host whose
 * UI font is materially larger than ours (a VS Code user at 16 px) draws taller
 * rows than the table above. That is why `render/nodes.ts` now pins the card's
 * `height` — not `min-height` — and clips the text column: past this point the
 * PLAN is authoritative and the ink is what gives way, exactly as it already
 * does in the SVG export. It also cannot know how a chip row WRAPS, because it
 * never wraps: `.mlv-node__chips` is one clipped flex row.
 *
 * Everything here is pure — types only, no DOM — so `layout/` can call it
 * without dragging the renderer in.
 */

import type { MLNode } from '../types.js';
import { NODE_H, NODE_H_GHOST, NODE_CHIP_ROW_H, NODE_W, NODE_W_LG, NODE_W_SM } from './constants.js';

/**
 * The attribute chips a card COULD draw, before any width budget.
 *
 * Lifted out of `render/nodes.ts:chipsFor` so the layout can ask the question
 * without a font metric. It is metric-free on purpose: `chipsFor` always keeps
 * its first candidate (the budget only ever drops the second and later ones),
 * so "is there a chip row" is decided here and identically in every host, while
 * "how many chips fit" stays a rendering decision.
 */
export function chipCandidates(node: MLNode): string[] {
  const out: string[] = [];
  const attrs = node.attrs || {};
  const sublabel = node.sublabel || '';
  for (const k of Object.keys(attrs)) {
    const text = k + '=' + attrs[k];
    if (sublabel.indexOf(text) >= 0) continue;
    out.push(text);
  }
  return out;
}

/**
 * Whether the card draws its chip row. A COLLAPSED GROUP always does: its first
 * chip is the "N nodes" count, which is prepended after budgeting.
 */
export function drawsChipRow(node: MLNode, collapsedGroup = false): boolean {
  if (collapsedGroup) return true;
  return chipCandidates(node).length > 0;
}

/**
 * Whether the card draws its `file : line` row. `locSpan` emits two empty
 * spans for a location with neither, and an empty flex row is 0 px tall.
 */
export function drawsLocRow(node: MLNode): boolean {
  const loc = node.loc;
  return !!(loc && (loc.file || loc.line));
}

/** The reserved height of one card — the box every other layer trusts. */
export function cardHeight(node: MLNode, collapsedGroup = false): number {
  const base = drawsLocRow(node) || collapsedGroup ? NODE_H : NODE_H_GHOST;
  return base + (drawsChipRow(node, collapsedGroup) ? NODE_CHIP_ROW_H : 0);
}

/** The reserved width of one card. Unchanged from the old `nodeSize`. */
export function cardWidth(node: MLNode, collapsedGroup = false): number {
  if (collapsedGroup) return NODE_W_LG;
  if (node.kind === 'model' || node.kind === 'entrypoint' || node.level === 'stage') return NODE_W_LG;
  if (node.kind === 'layer') return NODE_W_SM;
  return NODE_W;
}

/** Cards are always measured at full detail so LOD changes never relayout. */
export function cardSize(node: MLNode, collapsedGroup = false): { w: number; h: number } {
  return { w: cardWidth(node, collapsedGroup), h: cardHeight(node, collapsedGroup) };
}
