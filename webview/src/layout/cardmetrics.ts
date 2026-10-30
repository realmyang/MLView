/**
 * How tall a node card is.
 *
 * `layout.ts` reserves a box, `labels.ts` clears that box, `export/svg.ts`
 * draws that box and `render/nodes.ts` paints the card into it. All four have
 * to agree: a card taller than its box can overlap the card under it, and the
 * label placement then clears rectangles that are not the ones painted.
 *
 * So the reservation is DERIVED FROM THE CONTENT, from the same predicates the
 * renderer uses to decide what to draw:
 *
 *   padding + border                                22.0
 *   .mlv-node__title      13/1.35                   17.6
 *   .mlv-node__sub        11/1.35                   14.8
 *   .mlv-node__loc        10.5 mono                 15.8   (only with a loc)
 *   .mlv-node__chips      22 px chip + 4 px margin  26.0   (only on a collapsed group)
 *
 * which is 70.2 for a three-row card (`NODE_H` 72), 54.4 for a card with no loc
 * line (`NODE_H_GHOST` 60) and 96.2 with the chip row (`+ NODE_CHIP_ROW_H`). The
 * reserved heights are each a little larger than the matching sum.
 *
 * The only chip row is a collapsed group's "N steps" count. An authored card
 * draws its basis only where it is not `observed`, as a border and a tag that
 * take no layout space.
 *
 * WHAT THIS CANNOT KNOW: the reservation is a constant, so a host whose UI font
 * is materially larger than the viewer's (a VS Code user at 16 px) draws taller
 * rows than the table above. That is why `render/nodes.ts` sets the card's
 * `height` — not `min-height` — and `.mlv-node__main` (node.css) clips: past this point the
 * PLAN is authoritative and the ink is what gives way, as it does in the SVG
 * export. It also cannot know how a chip row WRAPS, because it never wraps:
 * `.mlv-node__chips` is one clipped flex row.
 *
 * Everything here is pure — types only, no DOM — so `layout/` can call it
 * without dragging the renderer in.
 */

import type { MLNode } from '../types.js';
import {
  NODE_H,
  NODE_H_GHOST,
  NODE_CHIP_ROW_H,
  NODE_TITLE_LINE_H,
  NODE_TITLE_MAX_LINES,
  NODE_W,
  NODE_W_LG,
  NODE_W_SM,
} from './constants.js';

/**
 * The card's text column: the width minus the stage rail, the main padding, the
 * icon tile and its gap (node.css), i.e. what the SVG export calls
 * `box.w - TEXT_X - PAD_R`; the two 1 px borders are not taken off.
 */
export const CARD_TEXT_INSET = 58;

/**
 * Average advance of the 13 px semibold title, in px: the SVG export's
 * `ADVANCE_SANS_BOLD` (0.55 em) at 13 px. An estimate — it only decides how
 * many lines to reserve; the DOM wraps by real metrics and clamps to that count.
 */
const TITLE_ADVANCE_PX = 13 * 0.55;

/**
 * The title as the lines a card of `width` draws: greedy word wrap on the
 * average advance, at most NODE_TITLE_MAX_LINES, the last line ending in one
 * ellipsis when text remains. A word longer than a line (a dotted path, an
 * identifier) is broken, as `overflow-wrap: anywhere` does on the card. Pure,
 * so the layout (how tall) and the SVG export (what text) agree.
 */
export function wrapTitle(label: string, width: number, maxLines = NODE_TITLE_MAX_LINES): string[] {
  const key = width + '|' + maxLines + '|' + label;
  const hit = wrapCache.get(key);
  if (hit) return hit;
  const lines = wrapUncached(label, width, maxLines);
  // Layout and the card both ask, once per relayout and per render; a bounded
  // memo keeps a 2000-node document from re-splitting every label each time.
  if (wrapCache.size >= WRAP_CACHE_MAX) wrapCache.clear();
  wrapCache.set(key, lines);
  return lines;
}

const WRAP_CACHE_MAX = 8192;
const wrapCache = new Map<string, string[]>();

function wrapUncached(label: string, width: number, maxLines: number): string[] {
  const perLine = Math.max(4, Math.floor((width - CARD_TEXT_INSET) / TITLE_ADVANCE_PX));
  const words = String(label || '').trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = '';
  let rest = false;
  for (let i = 0; i < words.length; i++) {
    let word = words[i];
    while (word.length > perLine) {
      // Break an over-long word, filling the current line first.
      const room = line ? perLine - line.length - 1 : perLine;
      if (room >= 4) {
        line = line ? line + ' ' + word.slice(0, room) : word.slice(0, room);
        word = word.slice(room);
      }
      lines.push(line);
      line = '';
      if (lines.length === maxLines) break;
    }
    if (lines.length === maxLines) { rest = true; break; }
    const next = line ? line + ' ' + word : word;
    if (next.length <= perLine) {
      line = next;
      continue;
    }
    lines.push(line);
    line = word;
    if (lines.length === maxLines) { rest = true; break; }
  }
  if (!rest && line) lines.push(line);
  else if (rest && lines.length) {
    const last = lines[lines.length - 1];
    lines[lines.length - 1] = (last.length >= perLine ? last.slice(0, perLine - 1) : last) + '…';
  }
  if (lines.length > maxLines) lines.length = maxLines;
  return lines.length ? lines : [''];
}

/**
 * How many title lines the card reserves: a title wraps (`wrapTitle`) rather
 * than being cut at one line.
 */
export function titleLines(node: MLNode, width: number): number {
  return wrapTitle(node.label || node.qualname || node.id, width).length;
}

/**
 * Whether the card draws its chip row: only a COLLAPSED GROUP does, for its
 * "N steps" count (authored cards carry no attribute chips).
 */
export function drawsChipRow(collapsedGroup = false): boolean {
  return collapsedGroup;
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
  const extraTitle = (titleLines(node, cardWidth(node, collapsedGroup)) - 1) * NODE_TITLE_LINE_H;
  return base + extraTitle + (drawsChipRow(collapsedGroup) ? NODE_CHIP_ROW_H : 0);
}

/** The reserved width of one card. */
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
