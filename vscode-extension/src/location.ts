/**
 * The one and only line/column boundary conversion, plus the workspace-containment guards.
 *
 * CONTRACTS.md §0: line numbers are 1-based, columns are 0-based, and the conversion to a
 * `vscode.Position` happens EXACTLY ONCE, at the host boundary. This module is that place:
 * `toRangeTuple` for ranges, `toEditorLine` / `toGraphLine` for a bare line number. Nothing
 * else in this extension adds or subtracts 1 from a line number, and
 * `test/invariants.test.js` asserts that over the source tree.
 */

import * as path from 'node:path';
import type { Loc } from './graph';
import type { OpenLocationMessage } from './protocol';

export interface RangeTuple {
  /** 0-based, ready for `new vscode.Position(startLine, startChar)`. */
  startLine: number;
  startChar: number;
  endLine: number;
  endChar: number;
}

export type LocLike = Pick<Loc, 'line' | 'col' | 'endLine' | 'endCol'>;

/** THE boundary conversion. 1-based inclusive line -> 0-based line; column passes through. */
export function toRangeTuple(loc: LocLike): RangeTuple {
  const startLine = Math.max(0, Math.trunc(loc.line) - 1);
  const startChar = Math.max(0, Math.trunc(loc.col));
  const endLineRaw = Math.max(0, Math.trunc(loc.endLine) - 1);
  const endCharRaw = Math.max(0, Math.trunc(loc.endCol));
  // A malformed end that precedes the start collapses to the start rather than throwing.
  if (endLineRaw < startLine || (endLineRaw === startLine && endCharRaw < startChar)) {
    return { startLine, startChar, endLine: startLine, endChar: startChar };
  }
  return { startLine, startChar, endLine: endLineRaw, endChar: endCharRaw };
}

/**
 * NB: the same conversion, for a location the host has re-anchored into a notebook cell.
 *
 * A notebook finding's `Loc` names the GENERATED module the analyzer materialised under
 * `.mlview/notebooks/`, and `cellLine` is the 1-based line of `loc.line` inside the cell it
 * came from (`notebooks.ts` recovers it). Only the start is published in cell coordinates,
 * because a finding never straddles a cell boundary, so the end is the start plus the span
 * the flat lines already agree on — which is the span inside the cell.
 */
export function cellRangeFor(loc: LocLike, cellLine: number): RangeTuple {
  const span = Math.max(0, Math.trunc(loc.endLine) - Math.trunc(loc.line));
  const start = Math.max(1, Math.trunc(cellLine));
  return toRangeTuple({
    line: start,
    col: loc.col,
    endLine: start + span,
    endCol: loc.endCol
  });
}

/**
 * 1-based graph line -> 0-based editor line. The line-only half of `toRangeTuple`, for the
 * CodeLens anchors and anywhere else a `vscode.Position` is built from a graph line.
 */
export function toEditorLine(line: number): number {
  return Math.max(0, Math.trunc(line) - 1);
}

/** 0-based editor line -> 1-based graph line. The exact inverse of `toEditorLine`. */
export function toGraphLine(line: number): number {
  return Math.max(1, Math.trunc(line) + 1);
}

export type OpenTargetRefusal = 'no-workspace' | 'out-of-workspace' | 'invalid-path';

export type OpenTarget =
  | { ok: true; fsPath: string; range: RangeTuple; preview: boolean }
  | { ok: false; reason: OpenTargetRefusal; fsPath: string };

export interface OpenTargetOptions {
  /** Absolute path of the workspace folder the graph was produced for. */
  workspaceRoot: string | undefined;
  /**
   * The containment test. In the extension this is
   * `(p) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(p))`.
   */
  isInWorkspace: (fsPath: string) => boolean;
}

function isBlank(value: unknown): boolean {
  return typeof value !== 'string' || value.trim().length === 0;
}

/**
 * SECURITY: node paths originate from parsing arbitrary source. A webview must never be able
 * to talk the extension into opening `~/.ssh/id_rsa`. The workspace-relative `file` is resolved
 * against the workspace root and the result must still be inside a workspace folder.
 */
export function resolveOpenTarget(
  msg: Pick<OpenLocationMessage, 'file' | 'absFile' | 'line' | 'col' | 'endLine' | 'endCol'> & {
    preview?: boolean;
  },
  opts: OpenTargetOptions
): OpenTarget {
  if (isBlank(msg.file) && isBlank(msg.absFile)) {
    return { ok: false, reason: 'invalid-path', fsPath: '' };
  }
  if (isBlank(opts.workspaceRoot)) {
    return { ok: false, reason: 'no-workspace', fsPath: String(msg.file ?? '') };
  }
  const root = String(opts.workspaceRoot);
  const relative = isBlank(msg.file) ? msg.absFile : msg.file;
  const fsPath = path.resolve(root, relative);
  if (!opts.isInWorkspace(fsPath)) {
    return { ok: false, reason: 'out-of-workspace', fsPath };
  }
  return {
    ok: true,
    fsPath,
    range: toRangeTuple(msg),
    preview: msg.preview === true
  };
}

export type AnalysisTargetRefusal = 'invalid-path' | 'out-of-workspace';

export type AnalysisTarget =
  | { ok: true; fsPath: string }
  | { ok: false; reason: AnalysisTargetRefusal; fsPath: string };

export interface AnalysisTargetOptions {
  /** `(p) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(p))` in the extension. */
  isInWorkspace: (fsPath: string) => boolean;
}

/**
 * SECURITY: the `path` of `mlview_analyzeWorkspace` (and of the chat participant behind it) is
 * MODEL-supplied text — in agent mode it can be steered by content in the user's own repo. The
 * same reasoning that guards `openLocation` applies: the extension must never be talked into
 * reading, parsing and summarising `~/.ssh` or a sibling checkout. A request is accepted only
 * when it resolves inside the analysis root or inside some other open workspace folder;
 * `..`-escapes and absolute paths elsewhere on the machine are refused.
 */
export function resolveAnalysisTarget(
  root: string,
  requested: string | undefined,
  opts: AnalysisTargetOptions
): AnalysisTarget {
  if (isBlank(root)) {
    return { ok: false, reason: 'invalid-path', fsPath: '' };
  }
  if (requested === undefined || isBlank(requested)) {
    return { ok: true, fsPath: path.resolve(root) };
  }
  if (requested.indexOf('\u0000') >= 0) {
    return { ok: false, reason: 'invalid-path', fsPath: '' };
  }
  const target = path.resolve(root, requested);
  const rel = path.relative(path.resolve(root), target);
  const insideRoot =
    rel === '' || (!path.isAbsolute(rel) && rel !== '..' && !rel.startsWith(`..${path.sep}`));
  if (insideRoot || opts.isInWorkspace(target)) {
    return { ok: true, fsPath: target };
  }
  return { ok: false, reason: 'out-of-workspace', fsPath: target };
}

/** `train.py:44` — the clipboard fallback and the chat anchor label. */
export function locLabel(loc: Pick<Loc, 'file' | 'line'>): string {
  return `${loc.file}:${loc.line}`;
}

/** Workspace-relative, forward-slashed, matching `Loc.file` (§0 "Paths"). */
export function toWorkspaceRelative(root: string, absPath: string): string {
  const rel = path.relative(root, absPath);
  return rel.split(path.sep).join('/');
}
