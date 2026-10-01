/**
 * Notebook locations, in the viewer's words.
 *
 * WorkflowDocument evidence on a `.ipynb` carries `cell` as the contract's
 * ZERO-BASED cell index (markdown cells count) and `line` as a line within that
 * cell. This module owns the one translation: such a location reads
 * `name.ipynb › cell 3, line 4`; every other location reads `train.py:27`.
 * Nothing here ever INVENTS a cell: a location with no recorded cell prints its
 * line, because a fabricated cell index is a broken click-to-code that looks
 * correct.
 *
 * No DOM here, and no import of `dom.ts`: `dom.ts` imports THIS module for
 * `fileLine`, so the dependency runs one way only.
 */

/** An authored citation's cell and the line within it. */
export interface CellRef {
  /** The zero-based cell index, as the artifact records it. */
  cell: number;
  /** 1-based line WITHIN that cell. */
  line: number;
}

/** Everything the label functions need. A full `Loc` satisfies it. */
export interface LocLike {
  file: string;
  line: number;
  /** The zero-based cell index of an authored notebook citation. Absent elsewhere. */
  cell?: number;
  /**
   * Set only on an AUTHORED location (WorkflowDocument evidence), the only
   * kind whose `cell` is read.
   */
  evidenceId?: string;
}

/**
 * The cell of an AUTHORED notebook citation, or `null` (VIEWUI-8).
 *
 * Viewer M1: the index is printed as recorded, counted from 0. It used to be
 * printed plus one, so a step the model labelled "(cell 34)" (the skill, the
 * helper's `--cell` and the extension all count from 0) showed "cell 35" beside
 * its own label. The title says how the cells are counted.
 */
export function authoredCell(loc: LocLike | null | undefined): CellRef | null {
  if (!loc || typeof loc.evidenceId !== 'string') return null;
  const cell = loc.cell;
  if (typeof cell !== 'number' || !isFinite(cell) || cell < 0 || Math.trunc(cell) !== cell) return null;
  return { cell, line: loc.line };
}

/**
 * The one label every surface prints: cards, rail rows, the inspector, tooltips,
 * search result meta and the SVG export. One function, so the surfaces can never
 * disagree about where a finding is.
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
 * `text-overflow: ellipsis`, the SVG export with `ellipsise()`. The directory is
 * the disposable half; the cell and line are the payload, so they are the tail
 * that is never cut.
 */
export function locParts(loc: LocLike): { head: string; tail: string } {
  const authored = authoredCell(loc);
  if (authored) return { head: loc.file, tail: ' › cell ' + authored.cell + ', line ' + authored.line };
  return { head: loc.file, tail: ':' + loc.line };
}

/**
 * The same fact for a screen reader, which should not have to decode `›` and
 * `:`. `name.ipynb cell 3 line 4`, or `train.py line 27`.
 */
export function locSpoken(loc: LocLike): string {
  const authored = authoredCell(loc);
  if (authored) return loc.file + ' cell ' + authored.cell + ' line ' + authored.line;
  return loc.file + ' line ' + loc.line;
}

/**
 * The hover text for a cell label: how the cells are counted. Empty string when
 * there is nothing extra to say, so a caller can assign it unconditionally.
 */
export function locTitle(loc: LocLike): string {
  const authored = authoredCell(loc);
  if (!authored) return '';
  return 'cell ' + authored.cell + ', counted from 0 as the artifact records it (markdown cells count too); line ' + authored.line + ' of that cell';
}
