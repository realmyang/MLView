/**
 * Rank re-flow: the two passes that run on dagre's OUTPUT coordinates before a
 * container is measured (MLV-R1-002, VIEW-01).
 *
 * dagre is asked for a `rankdir: 'LR'` layout, so a RANK is a column. That makes
 * a container's height the tallest rank and its width the sum of every rank —
 * and dagre optimises neither against a canvas. Two shapes fall out of it:
 *
 *   - every edge-less sibling lands in rank 0, so fifteen unconnected calls
 *     become one 1400 px column and the document is a 4:1 ribbon;
 *   - nine connected sibling groups become nine ranks in a row 10 232 px wide,
 *     so `fit()` opens the document at the zoom floor with 3 px text.
 *
 * `wrapTallRanks` fixes the first by splitting an over-tall rank into
 * sub-columns; `wrapWideRows` fixes the second by wrapping the rank SEQUENCE
 * into stacked rows. Both are pure moves of `x`/`y` on dagre's node objects:
 * edge points are recomputed from the boxes by routing.ts, so nothing
 * downstream depends on dagre's own routing, and both walk their input in
 * document order so the result stays deterministic.
 */

import { MAX_RANK_H, MAX_RANK_W, RANK_COL_GAP, RANK_ROW_GAP } from './constants.js';

interface Placed {
  id: string;
  n: any;
}

/** Every id that dagre actually positioned, in document order. */
function placedNodes(g: any, ids: string[]): Placed[] {
  const placed: Placed[] = [];
  for (const id of ids) {
    const n = g.node(id);
    if (n && isFinite(n.x) && isFinite(n.y)) placed.push({ id, n });
  }
  return placed;
}

/**
 * Bucket by rank. Same rank => same centre x, so the rounded centre is the key;
 * the returned keys are ascending, which is left-to-right under `rankdir: LR`.
 */
function columnsOf(placed: Placed[]): { keys: number[]; columns: Map<number, Placed[]> } {
  const columns = new Map<number, Placed[]>();
  for (const entry of placed) {
    const key = Math.round(entry.n.x * 100) / 100;
    const bucket = columns.get(key);
    if (bucket) bucket.push(entry);
    else columns.set(key, [entry]);
  }
  return { keys: Array.from(columns.keys()).sort((a, b) => a - b), columns };
}

/**
 * Wrap over-tall ranks into sub-columns (MLV-R1-002).
 *
 * Any rank whose stacked height exceeds MAX_RANK_H is re-flowed into
 * ceil(H / MAX_RANK_H) sub-columns and every later rank is shifted right by the
 * width that added, so the lane grows across the axis the canvas has room in.
 */
export function wrapTallRanks(g: any, ids: string[]): void {
  const placed = placedNodes(g, ids);
  if (placed.length < 2) return;

  const { keys, columns } = columnsOf(placed);
  let shift = 0;
  for (const key of keys) {
    const members = columns.get(key)!;
    for (const m of members) m.n.x += shift;
    if (members.length < 2) continue;

    members.sort((a, b) => a.n.y - b.n.y || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    let stacked = 0;
    let colW = 0;
    for (const m of members) {
      stacked += m.n.height;
      colW = Math.max(colW, m.n.width);
    }
    stacked += (members.length - 1) * RANK_ROW_GAP;
    if (stacked <= MAX_RANK_H) continue;

    const subColumns = Math.ceil(stacked / MAX_RANK_H);
    const rows = Math.max(1, Math.ceil(members.length / subColumns));
    const top = Math.min.apply(null, members.map((m) => m.n.y - m.n.height / 2));
    let column = 0;
    let cursor = top;
    for (let i = 0; i < members.length; i++) {
      if (i > 0 && i % rows === 0) {
        column++;
        cursor = top;
      }
      const m = members[i];
      m.n.x = key + shift + column * (colW + RANK_COL_GAP);
      m.n.y = cursor + m.n.height / 2;
      cursor += m.n.height + RANK_ROW_GAP;
    }
    shift += column * (colW + RANK_COL_GAP);
  }
}

/**
 * Wrap an over-wide rank sequence into stacked rows (VIEW-01).
 *
 * Ranks are taken left to right and packed into rows no wider than MAX_RANK_W;
 * a rank is never split, so a rank wider than the budget on its own simply gets
 * a row to itself and the container is as wide as its widest rank. Each row is
 * left-aligned to the first rank's left edge and dropped RANK_ROW_GAP below the
 * deepest box of the row above, which keeps the reading order — rank order is
 * pipeline order — as the row-major order of the result.
 *
 * Returns true when anything moved, which is only ever the case for a container
 * that was over budget: under it, this is a no-op and the layout is exactly the
 * one dagre produced.
 */
export function wrapWideRows(g: any, ids: string[]): boolean {
  const placed = placedNodes(g, ids);
  if (placed.length < 2) return false;

  const { keys, columns } = columnsOf(placed);
  if (keys.length < 2) return false;

  interface Rank {
    members: Placed[];
    left: number;
    right: number;
  }
  const ranks: Rank[] = [];
  for (const key of keys) {
    const members = columns.get(key)!;
    let left = Infinity;
    let right = -Infinity;
    for (const m of members) {
      left = Math.min(left, m.n.x - m.n.width / 2);
      right = Math.max(right, m.n.x + m.n.width / 2);
    }
    ranks.push({ members, left, right });
  }

  const originLeft = ranks[0].left;
  if (ranks[ranks.length - 1].right - originLeft <= MAX_RANK_W) return false;

  // Pack ranks into rows. A rank that is over budget by itself still starts a
  // row rather than being split: splitting a rank would reorder the pipeline.
  const rows: Rank[][] = [];
  let row: Rank[] = [];
  let rowLeft = originLeft;
  for (const rank of ranks) {
    if (row.length > 0 && rank.right - rowLeft > MAX_RANK_W) {
      rows.push(row);
      row = [];
      rowLeft = rank.left;
    }
    row.push(rank);
  }
  if (row.length > 0) rows.push(row);
  if (rows.length < 2) return false;

  let originTop = Infinity;
  for (const p of placed) originTop = Math.min(originTop, p.n.y - p.n.height / 2);

  let cursorY = originTop;
  for (const current of rows) {
    let top = Infinity;
    for (const rank of current) for (const m of rank.members) top = Math.min(top, m.n.y - m.n.height / 2);
    const dx = originLeft - current[0].left;
    const dy = cursorY - top;
    let bottom = cursorY;
    for (const rank of current) {
      for (const m of rank.members) {
        m.n.x += dx;
        m.n.y += dy;
        bottom = Math.max(bottom, m.n.y + m.n.height / 2);
      }
    }
    cursorY = bottom + RANK_ROW_GAP;
  }
  return true;
}
