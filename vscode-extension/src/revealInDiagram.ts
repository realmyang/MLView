/**
 * Code -> diagram (`Alt+M`, the editor context menu, and the CodeLens).
 *
 * The node whose range most NARROWLY contains the cursor wins; with nothing containing the
 * cursor the nearest node in the same file is selected and a toast says so (R2.5).
 */

import * as vscode from 'vscode';
import type { MLGraph } from './graph';
import { toGraphLine, toWorkspaceRelative } from './location';
import { findNodeAtLine, type LocationIndex } from './locationIndex';
import type { Logger } from './log';
import type { MlviewPanel } from './panel';

export interface RevealArgs {
  nodeId?: string;
}

export interface RevealDeps {
  log: Logger;
  getGraph(): MLGraph | undefined;
  getIndex(): LocationIndex | undefined;
  /** Opens (or reveals) the diagram panel and returns it, or undefined when it cannot open. */
  ensurePanel(): Promise<MlviewPanel | undefined>;
  /** Runs an analysis when there is no graph yet. */
  ensureGraph(): Promise<MLGraph | undefined>;
}

export async function revealInDiagram(args: RevealArgs | undefined, deps: RevealDeps): Promise<void> {
  const explicitNodeId = typeof args?.nodeId === 'string' ? args.nodeId : undefined;
  const editor = vscode.window.activeTextEditor;

  if (!explicitNodeId && !editor) {
    void vscode.window.showInformationMessage('MLView: open a Python file to reveal it in the diagram.');
    return;
  }

  let graph = deps.getGraph();
  if (!graph) {
    graph = await deps.ensureGraph();
  }
  if (!graph) {
    return;
  }

  const panel = await deps.ensurePanel();
  if (!panel) {
    return;
  }

  if (explicitNodeId) {
    panel.postRevealNode(explicitNodeId, false);
    return;
  }

  const index = deps.getIndex();
  if (!index || !editor) {
    return;
  }
  const relative = toWorkspaceRelative(graph.workspace.root, editor.document.uri.fsPath);
  // The single boundary conversion, in the one module allowed to do it (CONTRACTS.md §0).
  const line = toGraphLine(editor.selection.active.line);
  const hit = findNodeAtLine(index, relative, line);
  if (!hit) {
    void vscode.window.showInformationMessage(
      `MLView: no diagram node was found in ${relative}. Re-analyze if the file is new.`
    );
    deps.log.info(`reveal: no node for ${relative}:${line}`);
    return;
  }
  panel.postRevealNode(hit.nodeId, !hit.exact);
  if (!hit.exact) {
    void vscode.window.setStatusBarMessage(`MLView: nearest node "${hit.label}"`, 4000);
  }
  deps.log.debug(`reveal: ${relative}:${line} -> ${hit.nodeId} (${hit.exact ? 'exact' : 'nearest'})`);
}
