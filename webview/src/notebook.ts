/**
 * NB — notebook locations, in the viewer's words.
 *
 * A `.ipynb` is analyzed by concatenating its code cells in DOCUMENT order into
 * one shadow module, so every `Loc` the analyzer emits carries a FLAT line into
 * that concatenation. A flat line is the right thing to send a host — VS Code
 * maps it onto a `vscode-notebook-cell:` URI, the plugin slices the shadow `.py`
 * — and the WRONG thing to show a human, who has never seen the concatenation
 * and counts lines from the top of a cell.
 *
 * So this module owns exactly one translation: given a location that carries a
 * cell mapping, say `name.ipynb > cell 3 : 4`; given one that does not, say
 * `name.ipynb:27` exactly as it has always said `train.py:27`. Nothing here ever
 * INVENTS a cell: a `.ipynb` path with no mapping prints the flat line, because
 * a fabricated cell index is a broken click-to-code that looks correct.
 *
 * The flat line is never lost. It stays on the wire (`openLocation` posts
 * `loc.line` unchanged — `app.ts` is not notebook-aware and must not become so)
 * and it stays visible in the `title` of every cell-mapped label, so a reader
 * who needs to talk to the analyzer about line 27 still can.
 *
 * No DOM here, and no import of `dom.ts`: `dom.ts` imports THIS module for
 * `fileLine`, so the dependency runs one way only.
 */

import type { Diagnostic } from './types.js';

/**
 * The two optional `Loc` fields the notebook ingest adds (schema `Loc`, which is
 * `additionalProperties: false`, so these are declared rather than smuggled).
 *
 * Both must be present and sane for a location to count as cell-mapped. The
 * analyzer numbers the cells; this renderer prints the number VERBATIM and never
 * adds or subtracts one, because only the side that built the offset table knows
 * whether it counted from zero.
 */
export interface CellRef {
  /** The code cell, numbered as the analyzer numbers it. */
  cell: number;
  /** 1-based line WITHIN that cell. */
  line: number;
}

/** Everything the label functions need. A full `Loc` satisfies it. */
export interface LocLike {
  file: string;
  line: number;
  /** NB. The code cell this location fell in. Absent on every `.py` location. */
  cell?: number;
  /** NB. 1-based line inside `cell`. Absent on every `.py` location. */
  cellLine?: number;
  /** Accepted alias for `cell` — see NOTE ON SPELLING below. */
  notebookCell?: number;
  /** Accepted alias for `cellLine` — see NOTE ON SPELLING below. */
  notebookCellLine?: number;
}

/**
 * NOTE ON SPELLING. `{cell, cellLine}` is the pair this renderer expects and the
 * pair it tests. `{notebookCell, notebookCellLine}` is accepted as an alias so
 * that the viewer half and the analyzer half of NB cannot ship broken against
 * each other over a naming difference — exactly the interop note §11.24 carries
 * for `exportFile`. Reading two spellings costs one `typeof` check; showing a
 * notebook reader a flat line into a file they have never seen costs the
 * feature. 11.29 N6 settled it: the analyzer names them `cell` and `cellLine`,
 * and puts them in `Node.attrs`, from where `adoptCellMap` copies them onto the
 * node's own `Loc`. The alias is kept for a host that hands the viewer a
 * document from a newer analyzer that puts them on the `Loc` directly.
 */
function pick(loc: LocLike, primary: 'cell' | 'cellLine'): number | null {
  const alias = primary === 'cell' ? loc.notebookCell : loc.notebookCellLine;
  const raw = typeof loc[primary] === 'number' ? loc[primary] : alias;
  if (typeof raw !== 'number' || !isFinite(raw)) return null;
  return Math.trunc(raw);
}

/**
 * Copy 11.29 N6's cell mapping off `Node.attrs` and onto the node's own `Loc`.
 *
 * `Loc` is frozen by CONTRACTS §2, so the analyzer cannot put the mapping there:
 * N6 puts it in `attrs`, as STRINGS, beside `attrs.notebook`. Every label in this
 * renderer takes a `LocLike`, so rather than teach twelve call sites where the
 * analyzer keeps its provenance, the document is enriched ONCE, here, on the way
 * in. Idempotent, and a node the ingest could not map is left exactly alone —
 * `cellRef` then reports no mapping and the label falls back to the flat line,
 * which is always true.
 *
 * Only `Node.attrs` carries the mapping. An `Issue.loc` and a `relatedLocs` entry
 * carry no `attrs` (N6, and the "deliberately does not" list under it), so they
 * keep printing the flat line into the generated module — the wrong granularity,
 * never a broken link, because the generated module is a real file that slices.
 */
export function adoptCellMap(nodes: { loc?: LocLike; attrs?: Record<string, string> }[]): void {
  for (const n of nodes || []) {
    const attrs = n.attrs;
    const loc = n.loc;
    if (!attrs || !loc) continue;
    const cell = numeric(attrs.cell);
    const cellLine = numeric(attrs.cellLine);
    if (cell === null || cellLine === null) continue;
    if (typeof loc.cell !== 'number') loc.cell = cell;
    if (typeof loc.cellLine !== 'number') loc.cellLine = cellLine;
  }
}

/** An `attrs` value that is a whole number, or `null`. `attrs` values are strings. */
function numeric(raw: string | undefined): number | null {
  if (typeof raw !== 'string' || !/^-?\d+$/.test(raw)) return null;
  const n = Number(raw);
  return isFinite(n) ? n : null;
}

/**
 * The cell mapping on a location, or `null` when it carries none.
 *
 * Deliberately strict. A cell index below zero, a cell line below one, or either
 * half missing means the mapping is not trustworthy, and an untrustworthy
 * mapping is reported as NO mapping — the label falls back to the flat line,
 * which is always true.
 */
export function cellRef(loc: LocLike | null | undefined): CellRef | null {
  if (!loc) return null;
  const cell = pick(loc, 'cell');
  const line = pick(loc, 'cellLine');
  if (cell === null || line === null) return null;
  if (cell < 0 || line < 1) return null;
  return { cell, line };
}

/** True for a path this renderer would call a notebook. Presentation only. */
export function isNotebookPath(file: string): boolean {
  return typeof file === 'string' && /\.ipynb$/i.test(file);
}

/**
 * The one label every surface prints: cards, rail rows, the inspector, tooltips,
 * search result meta and the SVG export.
 *
 * `name.ipynb > cell 3 : 4` when the location is cell-mapped, `train.py:27`
 * otherwise. One function, so the four surfaces can never disagree about where a
 * finding is.
 */
export function locLabel(loc: LocLike): string {
  const parts = locParts(loc);
  return parts.head + parts.tail;
}

/**
 * The label split into the part that may be shortened and the part that must
 * not be.
 *
 * Both renderers truncate a location that does not fit — the DOM card with
 * `text-overflow: ellipsis`, the SVG export with `ellipsise()` — and both used
 * to truncate from the END, which on `notebooks/leak.ipynb > cell 3 : 4` cuts
 * off the entire answer and leaves `notebooks/leak.ipynb > c…`. The directory is
 * the disposable half; the cell reference is the payload. (The same was already
 * true, less visibly, of `:27` on a long `.py` path.)
 */
export function locParts(loc: LocLike): { head: string; tail: string } {
  const ref = cellRef(loc);
  return ref ? { head: loc.file, tail: ' > cell ' + ref.cell + ' : ' + ref.line } : { head: loc.file, tail: ':' + loc.line };
}

/**
 * The same fact for a screen reader, which should not have to decode `>` and
 * `:`. `name.ipynb cell 3 line 4`, or `train.py line 27`.
 */
export function locSpoken(loc: LocLike): string {
  const ref = cellRef(loc);
  if (!ref) return loc.file + ' line ' + loc.line;
  return loc.file + ' cell ' + ref.cell + ' line ' + ref.line;
}

/**
 * The hover text for a cell-mapped label: what the label says, plus the flat
 * line it came from. Empty string when there is nothing extra to say, so a
 * caller can assign it unconditionally without inventing a tooltip for `.py`.
 */
export function locTitle(loc: LocLike): string {
  const ref = cellRef(loc);
  if (!ref) return '';
  return locSpoken(loc) + ' — line ' + loc.line + ' of the concatenated code cells';
}

/* ── the execution-order caveat ────────────────────────────────────────── */

/**
 * The diagnostic kinds that mean "this notebook was last run out of order".
 *
 * Kept as aliases for a newer analyzer that gives the caveat a kind of its own.
 * 11.29 N10 does not: it emits ONE `notebook_analyzed` per analyzed notebook and
 * distinguishes the two verdicts by `codes` — the three order-sensitive rules
 * when and only when the counts are not monotonic. So the predicate below is
 * "the kind, or an analyzed notebook that named the rules it cost confidence
 * in", and an in-order notebook draws the chip and no banner.
 */
export const OUT_OF_ORDER_KINDS = ['notebook_out_of_order', 'notebook_execution_order'];

/** `notebook_analyzed` — the count of notebooks that WERE read (11.18's enum). */
export const NOTEBOOK_ANALYZED = 'notebook_analyzed';

/** True when this diagnostic says its notebook was last run out of order. */
function isOutOfOrder(d: Diagnostic): boolean {
  if (OUT_OF_ORDER_KINDS.indexOf(d.kind) >= 0) return true;
  return d.kind === NOTEBOOK_ANALYZED && (d.codes || []).length > 0;
}

/** Every out-of-order diagnostic in a document, in document order. */
export function outOfOrderDiagnostics(diags: Diagnostic[]): Diagnostic[] {
  return (diags || []).filter(isOutOfOrder);
}

/** The notebooks named by those diagnostics, deduplicated, in order. */
export function outOfOrderFiles(diags: Diagnostic[]): string[] {
  const seen: string[] = [];
  for (const d of outOfOrderDiagnostics(diags)) {
    const f = d.file;
    if (typeof f === 'string' && f && seen.indexOf(f) < 0) seen.push(f);
  }
  return seen;
}

/** The rule codes those diagnostics say were de-rated, deduplicated, in order. */
export function derated(diags: Diagnostic[]): string[] {
  const seen: string[] = [];
  for (const d of outOfOrderDiagnostics(diags)) {
    for (const c of d.codes || []) {
      if (typeof c === 'string' && c && seen.indexOf(c) < 0) seen.push(c);
    }
  }
  return seen;
}

/**
 * The banner headline.
 *
 * Worded the way the COVERAGE banner is worded, and for the same reason: it has
 * to say what MLView could NOT decide, not summarise what it found. Execution
 * order in a notebook is genuinely undecidable from the file — the analyzer read
 * the cells top to bottom because that is the only order it can see — so the
 * sentence says that plainly and names the rules it cost confidence in, instead
 * of implying the fit-before-split verdict below it is safe.
 */
export function outOfOrderHeadline(diags: Diagnostic[]): string {
  const files = outOfOrderFiles(diags);
  const n = outOfOrderDiagnostics(diags).length;
  const who =
    files.length === 1
      ? files[0]
      : files.length > 1
        ? files.slice(0, 3).join(', ') + (files.length > 3 ? ' and ' + (files.length - 3) + ' more' : '')
        : n + (n === 1 ? ' notebook' : ' notebooks');
  const was = files.length === 1 || n === 1 ? 'was' : 'were';
  const codes = derated(diags);
  const which = codes.length ? ' (' + codes.join(', ') + ')' : '';
  return (
    'Execution order: ' +
    who +
    ' ' +
    was +
    ' last run out of order, so MLView read the cells top to bottom — the only order a file can show. ' +
    'Order-sensitive findings' +
    which +
    ' are reported with lower confidence, and one that depends on the real run order may be missing entirely.'
  );
}
