/**
 * The three "show me the diagram" commands, extracted from src/extension.ts (which is at the
 * ~600-line budget after H5 and VIEW-08 landed their wiring there).
 *
 *   MLView: Visualize ML Workflow (Current File)   visualizeActiveFile
 *   MLView: Visualize ML Workflow (Workspace)      visualizeWorkspace
 *   MLView: Re-analyze                             refreshAnalysis
 *
 * They are one module because they are one decision asked three ways: WHICH folder, WHICH
 * paths, and whether an in-flight analysis may be joined or must be superseded. The controller
 * keeps the state; this file keeps the rules about it.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { resolveCurrentFileTarget } from './currentFile';
import type { FolderState } from './folders';
import type { Logger } from './log';
import { readSettings } from './settings';

/** What the three commands need from the controller. */
export interface VisualizeHost {
  readonly log: Logger;
  /** The active folder's state, or undefined when no folder is open at all. */
  activeState(): FolderState | undefined;
  /** H10: make `folder` the active one. True when the active folder actually changed. */
  setActiveFolder(folder: vscode.WorkspaceFolder): boolean;
  ensurePanel(): Promise<unknown>;
  /** Join an in-flight analysis for this state, or start one. */
  runOnce(state: FolderState): Promise<void>;
  /** Always start a fresh analysis, superseding anything in flight. */
  runFresh(state: FolderState): Promise<void>;
  /** Forget the resolved interpreter, so `Re-analyze` re-probes it. */
  invalidateInterpreter(): void;
}

/**
 * `MLView: Visualize (Current File)`.
 *
 * COVERAGE: analysing the file ALONE loses the cross-file rules silently — 3 findings where
 * its directory yields 7. `mlview.currentFileAnalysisScope` defaults to `package`, so the
 * command analyses the package directory around the file and then narrows the diagram to the
 * file through the §11.7 `setScope` path. The picture is the same; the findings are not.
 *
 * H10: the file's OWN folder becomes the active one, so pointing at a file in the second
 * folder of a multi-root window analyses that folder instead of silently analysing the first.
 */
export async function visualizeActiveFile(host: VisualizeHost): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== 'python') {
    await visualizeWorkspace(host);
    return;
  }
  const file = editor.document.uri.fsPath;
  const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
  if (folder && host.setActiveFolder(folder)) {
    host.log.info(`active folder is now ${folder.name} (the file being visualized lives there)`);
  }
  const state = host.activeState();
  if (!state) {
    await visualizeWorkspace(host);
    return;
  }
  state.appliedFocus = undefined;
  const mode = readSettings(editor.document.uri).currentFileAnalysisScope;
  const target = resolveCurrentFileTarget(
    file,
    folder?.uri.fsPath ?? path.dirname(file),
    mode,
    (candidate) => fs.existsSync(candidate)
  );
  state.lastScope = {
    scope: target.scope,
    ...(target.path ? { path: target.path } : {}),
    ...(target.focusFile ? { focusFile: target.focusFile } : {})
  };
  host.log.info(
    `visualize current file (${mode}): analyzing ${target.path ?? 'the workspace'}` +
      (target.focusFile ? `, diagram scoped to ${path.basename(target.focusFile)}` : '')
  );
  await host.ensurePanel();
  await host.runOnce(state);
}

export async function visualizeWorkspace(host: VisualizeHost): Promise<void> {
  const state = host.activeState();
  if (!state) {
    void vscode.window.showWarningMessage('MLView: open a folder or a Python file first.');
    return;
  }
  state.lastScope = { scope: 'workspace' };
  state.appliedFocus = undefined;
  await host.ensurePanel();
  // `Once`, not a fresh run: `ensurePanel` yields, so a command issued in the same tick (or
  // the panel's own `ready`) must join this analysis instead of superseding it.
  await host.runOnce(state);
}

/** `MLView: Re-analyze` — the user explicitly asked for fresh results, so never join. */
export async function refreshAnalysis(host: VisualizeHost): Promise<void> {
  host.invalidateInterpreter();
  const state = host.activeState();
  if (!state) {
    void vscode.window.showWarningMessage('MLView: open a folder or a Python file first.');
    return;
  }
  await host.runFresh(state);
}
