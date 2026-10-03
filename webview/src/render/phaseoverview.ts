/**
 * Viewer M3, roadmap step 13: the phase overview (Shift+0), as a PURE geometry.
 *
 * One block per phase, in the order the canvas draws its lanes: the phase's number and label, a
 * line of counts, then its step titles in reading order (the Outline's and the review walk's
 * order: a group before the steps it contains, depth first), each with its basis mark (◌ inferred,
 * ? unresolved; an observed step has none) and the F labels of the findings on it. Neighbouring
 * phases are joined by an arrow that says how many connections go from one to the next; a
 * connection that skips a phase or goes back is drawn as a bracket on the right with its count
 * (dashed when it goes back).
 *
 * Everything here is computed from the authored phases, steps, connections and findings (through
 * `GraphIndex`) and the canvas size. Nothing is categorised for the author and nothing is called.
 * It is drawn as an overlay over the canvas (`ui/overview.ts`), never inside the world layer, so
 * the routed geometry and its golden do not move.
 *
 * COUNTS. Every step is listed or counted: a block that does not fit lists its first steps and
 * ends with "… N more steps", so per block `listed + more = steps`, and the blocks sum to the
 * document's step count. The connections are a partition too: inside a phase, from a phase to the
 * next one (the arrows), and those that skip ahead or go back (the brackets) sum to the document's
 * connection count. A finding touching two phases counts in each (the PR #14 rule, `laneCounts`),
 * so the per-phase finding counts are labelled "touch this phase" and are not summed.
 *
 * FIT. Blocks are trimmed from the one with the most rows until the overview fits the canvas, but
 * never below `MIN_SLOTS` title slots (two titles and the count). When even that does not
 * fit, the overview scrolls (`height` is then larger than the canvas): beside the code at 541 px a
 * six-phase document scrolls a little rather than showing phase names only.
 */

import { normalizeSeverity } from '../markers.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { IssueCounts, Severity } from '../types.js';

/* ── input ─────────────────────────────────────────────────────────────── */

export interface OverviewTag {
  /** The finding's F label (`Issue.short`). */
  short: string;
  /** The finding's real id, for the tooltip. */
  id: string;
  severity: Severity;
}

export interface OverviewStep {
  id: string;
  title: string;
  /** `observed`, `inferred` or `unresolved` as authored ('' when absent). */
  basis: string;
  /** 0 for a lane root, 1 inside a group, and so on. */
  depth: number;
  /** The findings on this step that the severity toggles keep, in document order. */
  tags: OverviewTag[];
}

export interface OverviewPhase {
  id: string;
  label: string;
  /** The phase's position among the declared phases (0-based): its number and its colour. */
  index: number;
  steps: OverviewStep[];
  /** Findings touching this phase, by severity (PR #14: a finding on two phases counts in both). */
  findings: IssueCounts;
  inferred: number;
  unresolved: number;
}

export interface OverviewLink {
  /** Positions in `OverviewInput.phases` (drawn order), never equal. */
  from: number;
  to: number;
  count: number;
}

export interface OverviewInput {
  phases: OverviewPhase[];
  /** Connections between two different phases, one entry per ordered pair, in pair order. */
  links: OverviewLink[];
  /** Connections whose two ends are in the same phase. */
  inside: number;
  /** Connections with an end the document lacks (validation refuses them; kept so the sum holds). */
  unplacedConnections: number;
  /** Steps in no drawn phase (none today; kept so the sum holds). */
  unplacedSteps: number;
  totalSteps: number;
  totalConnections: number;
}

/** The overview's data, from the index the canvas draws. `keep` is the severity toggles' filter. */
export function overviewInput(index: GraphIndex, keep: IssuePredicate): OverviewInput {
  const phases: OverviewPhase[] = [];
  const position = new Map<string, number>();
  for (const lane of index.lanes) {
    position.set(lane.id, phases.length);
    phases.push({
      id: lane.id,
      label: lane.label || lane.id,
      index: index.phaseIndexOf(lane.id),
      steps: [],
      findings: index.laneCounts(lane.id, keep),
      inferred: 0,
      unresolved: 0,
    });
  }
  const seen = new Set<string>();
  let unplacedSteps = 0;
  const add = (id: string, depth: number): void => {
    if (seen.has(id)) return;
    const node = index.nodeById.get(id);
    if (!node) return;
    seen.add(id);
    const at = position.get(node.stage);
    if (at === undefined) unplacedSteps++;
    else {
      const phase = phases[at];
      const basis = node.basis || '';
      if (basis === 'inferred') phase.inferred++;
      else if (basis === 'unresolved') phase.unresolved++;
      phase.steps.push({
        id,
        title: node.label || node.qualname || id,
        basis,
        depth,
        tags: index.issuesOf(id, keep).map((issue) => ({ short: issue.short || issue.id, id: issue.id, severity: normalizeSeverity(issue.severity) })),
      });
    }
    for (const child of index.laneChildren(id)) add(child, depth + 1);
  };
  for (const lane of index.lanes) for (const root of index.roots(lane.id)) add(root, 0);
  // A step the drawn hierarchy did not reach (none can, today) is still listed in its phase.
  for (const node of index.graph.nodes || []) add(node.id, 0);

  const pairs = new Map<string, OverviewLink>();
  let inside = 0;
  let unplacedConnections = 0;
  for (const edge of index.graph.edges || []) {
    const source = index.nodeById.get(edge.source);
    const target = index.nodeById.get(edge.target);
    const a = source ? position.get(source.stage) : undefined;
    const b = target ? position.get(target.stage) : undefined;
    if (a === undefined || b === undefined) unplacedConnections++;
    else if (a === b) inside++;
    else {
      const key = a + '>' + b;
      const link = pairs.get(key);
      if (link) link.count++;
      else pairs.set(key, { from: a, to: b, count: 1 });
    }
  }
  const links = Array.from(pairs.values()).sort((p, q) => p.from - q.from || p.to - q.to);
  return {
    phases,
    links,
    inside,
    unplacedConnections,
    unplacedSteps,
    totalSteps: (index.graph.nodes || []).length,
    totalConnections: (index.graph.edges || []).length,
  };
}

/* ── wording ───────────────────────────────────────────────────────────── */

const plural = (n: number, one: string, many: string): string => n + ' ' + (n === 1 ? one : many);

/** Whether a link is drawn as an arrow (to the next phase) rather than a bracket. */
export function isNextLink(link: OverviewLink): boolean {
  return link.to === link.from + 1;
}

/** The connection partition: inside, to the next phase, skipping ahead or going back. */
export function connectionPartition(input: OverviewInput): { inside: number; next: number; jumps: number; unplaced: number } {
  let next = 0;
  let jumps = 0;
  for (const link of input.links) {
    if (isNextLink(link)) next += link.count;
    else jumps += link.count;
  }
  return { inside: input.inside, next, jumps, unplaced: input.unplacedConnections };
}

/**
 * The header's count sentence, every count with its unit, the connections as a partition that
 * sums to the total: "6 phases · 31 steps · 41 connections: 19 inside a phase, 8 to the next
 * phase, 14 skip ahead or go back."
 */
export function overviewSummary(input: OverviewInput): string {
  const part = connectionPartition(input);
  const pieces = [plural(part.inside, 'inside a phase', 'inside a phase'), plural(part.next, 'to the next phase', 'to the next phase'),
    plural(part.jumps, 'skips ahead or goes back', 'skip ahead or go back')];
  if (part.unplaced) pieces.push(plural(part.unplaced, 'with an end the document lacks', 'with an end the document lacks'));
  return plural(input.phases.length, 'phase', 'phases') + ' · ' + plural(input.totalSteps, 'step', 'steps') + ' · ' +
    plural(input.totalConnections, 'connection', 'connections') + ': ' + pieces.join(', ') + '.';
}

/**
 * What the arrows, brackets and marks mean, under the counts; it says what a bracket's number counts
 * (M3 review, A11Y-M3-8). One line at 900 px (at most 127 characters at SUMMARY_CHAR_W). Below
 * 620 px a shorter key keeps the marks and the brackets explained on screen (the arrows carry their
 * own "N connections" labels).
 */
export const OVERVIEW_KEY = 'Arrows go to the next phase; brackets count connections that skip ahead (solid) or back (dashed). ◌ inferred, ? unresolved.';
export const OVERVIEW_KEY_NARROW = '◌ inferred, ? unresolved. Brackets count connections that skip ahead (solid) or go back (dashed).';

/** "9 steps (1 inferred, 3 unresolved)": the block's step count with its exceptions. */
export function blockStepsText(phase: OverviewPhase): string {
  const extra: string[] = [];
  if (phase.inferred) extra.push(phase.inferred + ' inferred');
  if (phase.unresolved) extra.push(phase.unresolved + ' unresolved');
  return plural(phase.steps.length, 'step', 'steps') + (extra.length ? ' (' + extra.join(', ') + ')' : '');
}

/* ── geometry ──────────────────────────────────────────────────────────── */

/** Outer padding (CSS px); `PAD_NARROW` below `NARROW_W`. */
export const PAD = 16;
export const PAD_NARROW = 12;
/** Below this canvas width the overview is one column of blocks with one column of titles. */
export const NARROW_W = 620;
/** A block this wide or wider lists its titles in two columns and has a one-line head. */
export const TWO_COLUMNS_MIN_W = 600;
/** The widest a block is drawn (wider canvases leave room on the right). */
export const BLOCK_MAX_W = 980;
/** The head: number, label and counts on one line, or the counts on a second line. */
export const HEAD_H = 32;
export const HEAD_H_TWO_LINES = 50;
/** One title row (12.5 px text on an 18 px line). */
export const ROW_H = 18;
export const BLOCK_PAD_B = 8;
/** Inner padding left and right of the title columns, and the gap between the columns. */
export const BLOCK_PAD_X = 12;
export const COLUMN_GAP = 16;
/** Indentation per group level, at most two levels. */
export const INDENT = 12;
/** The vertical gap between two blocks, where the "N connections" arrow goes. */
export const GAP = 26;
/** Brackets: the first slot's distance from the blocks, then one slot every SLOT_STEP. */
export const BRACKET_INSET = 12;
export const SLOT_STEP = 12;
export const SLOT_STEP_MIN = 7;
/** Room after the last slot for its count. */
export const BRACKET_TAIL = 14;
/**
 * A block never shows fewer title slots than this (unless it has fewer steps): two titles and the
 * "… N more steps" row, in as many rows as its columns need. Below that, the overview scrolls.
 */
export const MIN_SLOTS = 3;
/** The header: a title row, then the summary lines. */
export const HEADER_TITLE_H = 24;
export const HEADER_LINE_H = 17;
export const HEADER_PAD = 8;
/** The space between the header and the first block. */
export const HEADER_GAP = 12;
/**
 * A conservative average character width of the 12 px summary text, so the estimated line count
 * is never short (a line too many only leaves a gap; one too few would hide the counts).
 */
export const SUMMARY_CHAR_W = 6.8;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface OverviewItem {
  /** A step's position in its phase's `steps`, or -1 for the "… N more steps" row. */
  step: number;
  /** For the "more" row: how many steps it stands for. */
  more: number;
  col: number;
  row: number;
  x: number;
  y: number;
  w: number;
  /** Group depth, clamped to 2 (the item's x already includes the indentation). */
  depth: number;
}

export interface OverviewBlock {
  /** Position in `OverviewInput.phases`. */
  phase: number;
  x: number;
  y: number;
  w: number;
  h: number;
  headH: number;
  twoLineHead: boolean;
  cols: number;
  rows: number;
  /** Rows the block would need to list every step. */
  rowsNeeded: number;
  items: OverviewItem[];
  /** Steps listed by title. */
  listed: number;
  /** Steps counted in the "… N more steps" row (0 when every step is listed). */
  more: number;
}

export interface OverviewArrow {
  from: number;
  to: number;
  count: number;
  x: number;
  y1: number;
  y2: number;
  labelX: number;
  labelY: number;
}

export interface OverviewBracket {
  from: number;
  to: number;
  count: number;
  /** It goes back (to an earlier phase): dashed. */
  back: boolean;
  slot: number;
  /** The blocks' right edge, where the bracket leaves and enters. */
  x0: number;
  /** The slot's vertical line. */
  x: number;
  y1: number;
  y2: number;
  labelX: number;
  labelY: number;
}

export interface OverviewLayout {
  /** The canvas size the layout is for. */
  viewW: number;
  viewH: number;
  /** The content size; `height > viewH` means the overview scrolls. */
  width: number;
  height: number;
  scrolls: boolean;
  /** One column of blocks with one column of titles (below NARROW_W). */
  narrow: boolean;
  header: Rect & { lines: number; summary: string; key: string };
  blocks: OverviewBlock[];
  arrows: OverviewArrow[];
  brackets: OverviewBracket[];
  /** Some block lists fewer titles than it has steps. */
  trimmed: boolean;
}

/**
 * The overview for a canvas `w` x `h` (CSS px). Pure: the same input and size always give the same
 * picture, so tests pin it at fixed sizes without a DOM.
 */
export function phaseOverviewLayout(input: OverviewInput, w: number, h: number): OverviewLayout {
  const viewW = Math.max(1, Math.floor(w));
  const viewH = Math.max(1, Math.floor(h));
  const narrow = viewW < NARROW_W;
  const pad = narrow ? PAD_NARROW : PAD;
  const n = input.phases.length;

  // Brackets: every link that is not to the next phase, packed into as few slots as possible
  // (two brackets share a slot when the phases they span do not overlap).
  const jumps = input.links.filter((link) => !isNextLink(link));
  const order = jumps
    .map((link, i) => ({ link, i }))
    .sort((p, q) => span(p.link) - span(q.link) || Math.min(p.link.from, p.link.to) - Math.min(q.link.from, q.link.to) || p.i - q.i);
  const slotOf = new Map<OverviewLink, number>();
  const slots: Array<Array<[number, number]>> = [];
  for (const { link } of order) {
    const lo = Math.min(link.from, link.to);
    const hi = Math.max(link.from, link.to);
    let s = 0;
    while (s < slots.length && slots[s].some(([a, b]) => lo <= b && a <= hi)) s++;
    if (s === slots.length) slots.push([]);
    slots[s].push([lo, hi]);
    slotOf.set(link, s);
  }
  const slotCount = slots.length;
  const gutterMax = Math.max(60, Math.min(160, Math.round(viewW * 0.2)));
  let step = SLOT_STEP;
  if (slotCount && BRACKET_INSET + slotCount * step + BRACKET_TAIL > gutterMax) {
    step = Math.max(SLOT_STEP_MIN, (gutterMax - BRACKET_INSET - BRACKET_TAIL) / slotCount);
  }
  const gutter = slotCount ? Math.ceil(BRACKET_INSET + (slotCount - 1) * step + BRACKET_TAIL) : 0;

  const blockW = Math.max(120, Math.min(BLOCK_MAX_W, viewW - 2 * pad - gutter));
  const twoColumns = !narrow && blockW >= TWO_COLUMNS_MIN_W;
  const cols = twoColumns ? 2 : 1;
  const twoLineHead = !twoColumns;
  const headH = twoLineHead ? HEAD_H_TWO_LINES : HEAD_H;

  // The header: a title row, then the counts and the key (shorter when narrow), at an estimated
  // line count.
  const summary = overviewSummary(input);
  const key = narrow ? OVERVIEW_KEY_NARROW : OVERVIEW_KEY;
  const textW = Math.max(80, viewW - 2 * pad);
  const linesFor = (text: string) => Math.max(1, Math.ceil((text.length * SUMMARY_CHAR_W) / textW));
  const lines = linesFor(summary) + (key ? linesFor(key) : 0);
  const header = { x: pad, y: pad, w: viewW - 2 * pad, h: HEADER_TITLE_H + lines * HEADER_LINE_H + HEADER_PAD, lines, summary, key };

  // Rows per block, then trim the block with the most rows until the whole thing fits.
  const rowsNeeded = input.phases.map((phase) => Math.ceil(phase.steps.length / cols));
  const rows = rowsNeeded.slice();
  const minRows = input.phases.map((phase) => Math.ceil(Math.min(phase.steps.length, MIN_SLOTS) / cols));
  const blockH = (r: number) => headH + (r > 0 ? r * ROW_H : 0) + BLOCK_PAD_B;
  const contentH = () => header.y + header.h + HEADER_GAP + rows.reduce((sum, r) => sum + blockH(r), 0) + GAP * Math.max(0, n - 1) + pad;
  while (contentH() > viewH) {
    let pick = -1;
    for (let i = 0; i < n; i++) {
      if (rows[i] <= minRows[i]) continue;
      if (pick < 0 || rows[i] > rows[pick] || (rows[i] === rows[pick] && input.phases[i].steps.length >= input.phases[pick].steps.length)) pick = i;
    }
    if (pick < 0) break;
    rows[pick]--;
  }

  const blocks: OverviewBlock[] = [];
  let y = header.y + header.h + HEADER_GAP;
  const colW = (blockW - 2 * BLOCK_PAD_X - (cols - 1) * COLUMN_GAP) / cols;
  input.phases.forEach((phase, i) => {
    const r = rows[i];
    const slotsAvailable = r * cols;
    const total = phase.steps.length;
    const fits = slotsAvailable >= total;
    const listed = fits ? total : Math.max(0, slotsAvailable - 1);
    const more = total - listed;
    const items: OverviewItem[] = [];
    // Column-major, so reading order runs down the first column and on into the second.
    for (let k = 0; k < listed + (more ? 1 : 0); k++) {
      const col = Math.floor(k / Math.max(1, r));
      const row = k % Math.max(1, r);
      const isMore = k === listed;
      const depth = isMore ? 0 : Math.min(2, phase.steps[k].depth);
      const x0 = pad + BLOCK_PAD_X + col * (colW + COLUMN_GAP);
      items.push({
        step: isMore ? -1 : k,
        more: isMore ? more : 0,
        col,
        row,
        x: round1(x0 + depth * INDENT),
        y: round1(y + headH + row * ROW_H),
        w: round1(colW - depth * INDENT),
        depth,
      });
    }
    const height = blockH(r);
    blocks.push({ phase: i, x: pad, y: round1(y), w: round1(blockW), h: height, headH, twoLineHead, cols, rows: r, rowsNeeded: rowsNeeded[i], items, listed, more });
    y += height + GAP;
  });

  // Arrows between neighbours, in the gap under each block, at its left.
  const arrows: OverviewArrow[] = [];
  for (const link of input.links) {
    if (!isNextLink(link)) continue;
    const a = blocks[link.from];
    const b = blocks[link.to];
    if (!a || !b) continue;
    const x = a.x + 22;
    const y1 = a.y + a.h + 3;
    const y2 = b.y - 3;
    arrows.push({ from: link.from, to: link.to, count: link.count, x, y1: round1(y1), y2: round1(y2), labelX: x + 10, labelY: round1((y1 + y2) / 2) });
  }

  // Brackets: each block spreads its ends along its right edge, the ends to earlier phases on top.
  const x0 = pad + blockW;
  const ends = new Map<number, Array<{ link: OverviewLink; other: number }>>();
  for (const link of jumps) {
    pushEnd(ends, link.from, { link, other: link.to });
    pushEnd(ends, link.to, { link, other: link.from });
  }
  const endY = new Map<string, number>();
  for (const [at, list] of ends) {
    const block = blocks[at];
    if (!block) continue;
    list.sort((p, q) => p.other - q.other || (slotOf.get(p.link) || 0) - (slotOf.get(q.link) || 0));
    const top = block.y + 10;
    const usable = Math.max(1, block.h - 20);
    list.forEach((end, j) => endY.set(endKey(end.link, at), round1(top + ((j + 1) * usable) / (list.length + 1))));
  }
  const brackets: OverviewBracket[] = jumps.map((link) => {
    const slot = slotOf.get(link) || 0;
    const x = round1(x0 + BRACKET_INSET + slot * step);
    const y1 = endY.get(endKey(link, link.from)) || 0;
    const y2 = endY.get(endKey(link, link.to)) || 0;
    return { from: link.from, to: link.to, count: link.count, back: link.to < link.from, slot, x0: round1(x0), x, y1, y2, labelX: x, labelY: round1((y1 + y2) / 2) };
  });

  const height = Math.ceil(y - GAP + pad);
  const width = Math.ceil(Math.min(viewW, x0 + gutter + pad));
  return {
    viewW,
    viewH,
    width: Math.max(width, viewW),
    height,
    scrolls: height > viewH,
    narrow,
    header,
    blocks,
    arrows,
    brackets,
    trimmed: blocks.some((b) => b.more > 0),
  };
}

function span(link: OverviewLink): number {
  return Math.abs(link.to - link.from);
}

function endKey(link: OverviewLink, at: number): string {
  return link.from + '>' + link.to + '@' + at;
}

function pushEnd<V>(map: Map<number, V[]>, key: number, value: V): void {
  const list = map.get(key);
  if (list) list.push(value);
  else map.set(key, [value]);
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
