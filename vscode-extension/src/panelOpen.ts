/**
 * The viewer's `openLocation`, extracted from src/panel.ts (which is at the ~600-line budget
 * after VIEW-08's overlay transport).
 *
 * This is R2.1 — "click a node, land on the line" — and the one place a path arriving from
 * the WEBVIEW is turned into an editor. Two rules travel with it and are the reason it is its
 * own module rather than an inline method:
 *
 *   1. **Containment first.** `resolveOpenTarget` decides; a refused path is logged and
 *      nothing opens. A webview must not be able to open an arbitrary file on the disk.
 *   2. **One boundary conversion.** `toRangeTuple` (CONTRACTS §0) does the 1-based-to-0-based
 *      arithmetic, here as everywhere else.
 */

import * as vscode from 'vscode';
import { resolveOpenTarget, toRangeTuple } from './location';
import type { Logger } from './log';
import type { OpenLocationMessage } from './protocol';

/** How long the flash decoration stays on the landed range. */
export const HIGHLIGHT_MS = 1200;

export interface OpenLocationDeps {
  log: Logger;
  /** Absolute root the graph's relative paths resolve against. */
  workspaceRoot(): string | undefined;
  /** The panel's own flash decoration, disposed with the panel. */
  decoration: vscode.TextEditorDecorationType;
}

/** Open the file the viewer asked for, select the range and flash it. */
export async function openGraphLocation(
  msg: OpenLocationMessage,
  deps: OpenLocationDeps
): Promise<void> {
  const target = resolveOpenTarget(msg, {
    workspaceRoot: deps.workspaceRoot(),
    isInWorkspace: (fsPath) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath))
  });
  if (!target.ok) {
    // SECURITY: never open a path the webview talked us into that is outside the workspace.
    deps.log.warn(`refused ${target.reason} open: ${target.fsPath}`);
    return;
  }
  try {
    const uri = vscode.Uri.file(target.fsPath);
    const doc = await vscode.workspace.openTextDocument(uri);
    // THE ONE AND ONLY boundary conversion happened in toRangeTuple.
    const t = toRangeTuple(msg);
    const selection = new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
    const editor = await vscode.window.showTextDocument(doc, {
      viewColumn: vscode.ViewColumn.One,
      selection,
      preview: target.preview
    });
    editor.revealRange(selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
    editor.setDecorations(deps.decoration, [selection]);
    setTimeout(() => {
      try {
        editor.setDecorations(deps.decoration, []);
      } catch {
        /* the editor may be gone */
      }
    }, HIGHLIGHT_MS);
  } catch (err) {
    deps.log.error(`could not open ${target.fsPath}`, err);
  }
}

/** Convenience for the range conversion used outside the panel (reveal, chat anchors). */
export function rangeFromLoc(loc: {
  line: number;
  col: number;
  endLine: number;
  endCol: number;
}): vscode.Range {
  const t = toRangeTuple(loc);
  return new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
}
