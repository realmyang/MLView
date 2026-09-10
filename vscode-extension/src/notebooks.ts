/**
 * NB — the notebook half of the host.
 *
 * What the analyzer gives us, and why it is shaped this way. Given `--include-notebooks` it
 * converts each `.ipynb` into ONE generated Python module, materialised on disk under
 * `<root>/.mlview/notebooks/`, and every `Loc` points at that module: `Loc` is frozen
 * (CONTRACTS §2) and cannot carry a cell index, and a location that pointed at the `.ipynb`
 * would name a line of JSON. The cell mapping therefore rides beside the location:
 *
 *   • on a NODE, as `attrs.notebook` / `attrs.cell` / `attrs.cellLine` (all strings);
 *   • on an ISSUE, as one `context_confirmed` evidence row reading
 *     `"<notebook>.ipynb cell <N>, line <M>; <execution-order verdict>"`;
 *   • per notebook, as one `notebook_analyzed` diagnostic whose `file` is the `.ipynb`.
 *
 * `cell` is the 0-based index among ALL cells, markdown included — the number
 * `NotebookDocument.cellAt` takes and the number the Jupyter UI shows.
 *
 * What the HOST has to add. A squiggle published on the generated module lands in a file the
 * user never wrote; published on the `.ipynb` file uri it lands on JSON. VS Code draws a
 * notebook as one editor per cell, each backed by its own document on a
 * `vscode-notebook-cell:` uri, and that is the only uri a notebook squiggle can usefully go
 * on. So this module walks evidence -> cell -> open `NotebookDocument` -> cell document uri,
 * and degrades one honest step at a time: the cell uri, else the `.ipynb` file uri (right
 * file, wrong granularity), else the generated module (which at least exists and slices).
 *
 * The evidence string is a parsed contract, so `test/notebooks.test.js` pins the format
 * against `analyzer/src/mlview/rules/confidence.py` itself — a rename on either side reddens,
 * the same discipline `progress.test.js` uses for `--progress-json`.
 */

import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Evidence, GraphDiagnostic, Loc, MLGraph } from './graph';
import { cellRangeFor, toRangeTuple, type RangeTuple } from './location';

export const NOTEBOOK_EXTENSION = '.ipynb';

/** Where the analyzer materialises a generated module, workspace-relative. */
export const SHADOW_DIR = '.mlview/notebooks';

/** The `NotebookCellKind.Code` value, named once so the mock and the real enum agree. */
export const CODE_CELL_KIND = 2;

/** The `Diagnostic.kind` the analyzer emits once per notebook it actually read. */
export const NOTEBOOK_ANALYZED_KIND = 'notebook_analyzed';

/**
 * `<notebook>.ipynb cell <N>, line <M>` — the head of the `context_confirmed` evidence row
 * `rules/confidence.notebook_evidence` writes for every finding inside a notebook. Anchored,
 * because the notebook path is the start of the detail and may itself contain spaces.
 */
export const CELL_EVIDENCE_RE = /^(.+?\.ipynb) cell (\d+), line (\d+)/;

/**
 * The other form the same function writes: a location in the generated module's header or in
 * a `# %%` marker, which belongs to no cell. It names the notebook and says so, and an
 * invented cell index would be worse than none.
 */
export const OUTSIDE_CELL_EVIDENCE_RE = /^(.+?\.ipynb) \(generated module line \d+, outside any cell\)/;

export function isNotebookPath(fsPath: string): boolean {
  return typeof fsPath === 'string' && fsPath.toLowerCase().endsWith(NOTEBOOK_EXTENSION);
}

/**
 * `.mlview/notebooks/nb/leak.py` -> `nb/leak.ipynb`, the inverse of
 * `ingest.notebook.shadow_relpath`. Undefined for any other path, including a real `.py`.
 */
export function notebookForShadow(relFile: string): string | undefined {
  const rel = String(relFile ?? '').replace(/\\/g, '/');
  if (!rel.startsWith(`${SHADOW_DIR}/`) || !rel.endsWith('.py')) {
    return undefined;
  }
  return `${rel.slice(SHADOW_DIR.length + 1, -'.py'.length)}${NOTEBOOK_EXTENSION}`;
}

/** Where a finding really is: which notebook, and which cell of it when that is knowable. */
export interface CellRef {
  /** Workspace-relative `.ipynb`. */
  notebook: string;
  /** 0-based index among all cells; absent for the module header and the `# %%` markers. */
  cell?: number;
  /** 1-based line inside that cell. */
  cellLine?: number;
}

/** Read the cell mapping out of a finding's evidence rows. */
export function cellRefFromEvidence(evidence: readonly Evidence[] | undefined): CellRef | undefined {
  for (const row of evidence ?? []) {
    const detail = String(row?.detail ?? '');
    const inCell = CELL_EVIDENCE_RE.exec(detail);
    if (inCell) {
      return {
        notebook: String(inCell[1]),
        cell: Number(inCell[2]),
        cellLine: Number(inCell[3])
      };
    }
    const outside = OUTSIDE_CELL_EVIDENCE_RE.exec(detail);
    if (outside) {
      return { notebook: String(outside[1]) };
    }
  }
  return undefined;
}

/**
 * Where a finding belongs, given its location and its evidence. Evidence first, because it is
 * per-finding and exact; the shadow path second, because it still names the right notebook
 * when a rule emitted no notebook evidence. Undefined for ordinary Python.
 */
export function cellRefFor(
  loc: Pick<Loc, 'file'>,
  evidence?: readonly Evidence[]
): CellRef | undefined {
  const fromEvidence = cellRefFromEvidence(evidence);
  if (fromEvidence) {
    return fromEvidence;
  }
  const notebook = notebookForShadow(loc.file);
  return notebook ? { notebook } : undefined;
}

// ------------------------------------------------------------------ the editor's own cells

/** The structural slice of `vscode.NotebookCell` this module needs. */
export interface NotebookCellLike {
  readonly index: number;
  readonly kind: number;
  readonly document: { readonly uri: vscode.Uri; readonly lineCount: number };
}

/** The structural slice of `vscode.NotebookDocument` this module needs. */
export interface NotebookDocumentLike {
  readonly uri: vscode.Uri;
  getCells(): readonly NotebookCellLike[];
}

function normalize(fsPath: string): string {
  return String(fsPath).replace(/\\/g, '/');
}

/**
 * The open notebook for an absolute path, or undefined. Compared case-sensitively first so a
 * case-sensitive filesystem is answered exactly, then case-insensitively so macOS and Windows
 * — where the analyzer's path and the editor's can differ only in case — still match.
 */
export function findNotebook(
  absFile: string,
  notebooks: readonly NotebookDocumentLike[]
): NotebookDocumentLike | undefined {
  const want = normalize(absFile);
  const exact = notebooks.find((nb) => normalize(nb.uri.fsPath) === want);
  if (exact) {
    return exact;
  }
  const lower = want.toLowerCase();
  return notebooks.find((nb) => normalize(nb.uri.fsPath).toLowerCase() === lower);
}

/**
 * The cell a `CellRef.cell` names.
 *
 * The analyzer counts ALL cells, so `getCells()[cell]` is the answer and `cellAt` agrees.
 * The fallback covers the one case that number can be stale in: the notebook has been edited
 * since it was analyzed, and the index now lands on a markdown cell. Reading it as a
 * code-cell ordinal then lands on a code cell rather than on prose, which is the better of
 * two wrong answers; a stale index is why the caller still re-checks nothing else.
 */
export function cellAtIndex(
  notebook: NotebookDocumentLike,
  cell: number
): NotebookCellLike | undefined {
  const cells = notebook.getCells();
  const direct = cells[cell];
  if (direct && direct.kind === CODE_CELL_KIND) {
    return direct;
  }
  const code = cells.filter((c) => c.kind === CODE_CELL_KIND);
  return code[cell] ?? direct;
}

export interface NotebookTarget {
  uri: vscode.Uri;
  range: RangeTuple;
  /** `cell` when the range is inside a cell, `notebook` for the `.ipynb`, `module` otherwise. */
  level: 'cell' | 'notebook' | 'module';
  /** Absolute path of the `.ipynb` this finding came from. */
  notebookFile: string;
}

export interface NotebookTargetOptions {
  /** `graph.workspace.root` — the notebook paths in evidence are relative to it. */
  root: string;
  notebooks: readonly NotebookDocumentLike[];
}

/**
 * Where a notebook finding's squiggle belongs, or undefined when the finding is not in a
 * notebook at all (the signal to publish it on its own file uri, unchanged).
 *
 * The cell-relative range is clamped to the cell's real line count, because the flat span is
 * the analyzer's arithmetic and the open cell is the ground truth: VS Code refuses a range
 * past the end of a document outright, and a squiggle on the last line of the right cell is a
 * far better failure than no squiggle at all.
 */
export function resolveNotebookTarget(
  issue: { loc: Loc; evidence?: readonly Evidence[] },
  opts: NotebookTargetOptions
): NotebookTarget | undefined {
  const ref = cellRefFor(issue.loc, issue.evidence);
  if (!ref) {
    return undefined;
  }
  const notebookFile = path.resolve(opts.root, ref.notebook);
  const fileLevel = (): NotebookTarget => ({
    uri: vscode.Uri.file(notebookFile),
    range: toRangeTuple(issue.loc),
    level: 'notebook',
    notebookFile
  });
  if (typeof ref.cell !== 'number' || typeof ref.cellLine !== 'number') {
    return fileLevel();
  }
  const notebook = findNotebook(notebookFile, opts.notebooks);
  const cell = notebook ? cellAtIndex(notebook, ref.cell) : undefined;
  if (!cell) {
    return fileLevel();
  }
  const wanted = cellRangeFor(issue.loc, ref.cellLine);
  const lastLine = Math.max(0, cell.document.lineCount - 1);
  const startLine = Math.min(wanted.startLine, lastLine);
  const endLine = Math.min(Math.max(wanted.endLine, startLine), lastLine);
  return {
    uri: cell.document.uri,
    range: {
      startLine,
      startChar: wanted.startChar,
      endLine,
      endChar: endLine === wanted.endLine ? wanted.endChar : wanted.startChar
    },
    level: 'cell',
    notebookFile
  };
}

/** Every `.ipynb` currently open in the window, as the structural type this module uses. */
export function openNotebooks(): readonly NotebookDocumentLike[] {
  const docs = (vscode.workspace as { notebookDocuments?: readonly NotebookDocumentLike[] })
    .notebookDocuments;
  return Array.isArray(docs) ? docs : [];
}

// --------------------------------------------------------------------------- the honest count

export interface NotebookCounts {
  /** `.ipynb` files the analyzer actually read — one `notebook_analyzed` diagnostic each. */
  analyzed: number;
  /** `.ipynb` files it saw and set aside, which never becomes 0 because the flag was on. */
  skipped: number;
}

export const NO_NOTEBOOKS: NotebookCounts = { analyzed: 0, skipped: 0 };

/**
 * What the run did with the notebooks it found. `analyzed` is COUNTED from the diagnostics
 * rather than read from a workspace field, because there is no such field: the workspace
 * carries `notebooksSkipped` only, and the analyzer states each success as its own
 * `notebook_analyzed` row (whose `count` is that notebook's CODE CELLS, not a notebook count
 * — adding those up would report "17 notebooks analyzed" for one file).
 */
export function notebookCounts(graph?: {
  workspace: { notebooksSkipped: number };
  diagnostics?: readonly GraphDiagnostic[];
}): NotebookCounts {
  if (!graph) {
    return NO_NOTEBOOKS;
  }
  const analyzed = (graph.diagnostics ?? []).filter(
    (d) => d?.kind === NOTEBOOK_ANALYZED_KIND
  ).length;
  return {
    analyzed,
    skipped: Math.max(0, Math.trunc(graph.workspace.notebooksSkipped ?? 0))
  };
}

/**
 * The status-bar fragment: `N notebooks analyzed` when the flag was on and found something,
 * `N notebooks not analyzed` when they were set aside, and BOTH when a run analyzed some and
 * could not read others — which is exactly the case a single number would have hidden.
 * Empty when there were no notebooks at all, so the common tooltip is unchanged.
 */
export function notebookTooltipFragment(counts: NotebookCounts): string {
  const parts: string[] = [];
  if (counts.analyzed > 0) {
    parts.push(`${counts.analyzed} notebooks analyzed`);
  }
  if (counts.skipped > 0) {
    parts.push(`${counts.skipped} notebooks not analyzed`);
  }
  return parts.length > 0 ? ` · ${parts.join(', ')}` : '';
}

/** True when the graph reports at least one notebook it read (NB, for the digest wording). */
export function analyzedAnyNotebook(graph: MLGraph): boolean {
  return notebookCounts(graph).analyzed > 0;
}
