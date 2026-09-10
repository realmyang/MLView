/**
 * The analysis path the chat participant and the language-model tools take (CONTRACTS.md §5).
 *
 * It is deliberately NOT the same code as the diagram's `runAnalysis`: a tool call may name a
 * path the MODEL chose, so the workspace-containment refusal is the first thing that happens
 * here, and a whole-workspace call reuses the graph the panel already has instead of spawning
 * a second analyzer for an answer the extension can already give.
 *
 * Split out of extension.ts to keep that file inside the repo's ~600-line budget; the
 * controller keeps the one-line `analyze()` method the `CoreLike` interface requires.
 */

import * as vscode from 'vscode';
import { CoreError, type CoreClient } from './coreClient';
import type { MLGraph } from './graph';
import { resolveAnalysisTarget } from './location';
import type { Logger } from './log';
import type { ToolAnalyzeInput } from './lmTools';
import { nextRequestId } from './protocol';
import { readSettings, type MlviewSettings } from './settings';
import { isTrusted, RESTRICTED_MESSAGE } from './trust';

export interface ToolAnalyzeDeps {
  log: Logger;
  core: CoreClient;
  /**
   * H10: the ACTIVE workspace folder, not `workspaceFolders?.[0]`. In a two-folder window the
   * old hardcode meant a question about the second folder was answered with the first folder's
   * code and nothing said so. `MLView: Select Active Folder` and the status-bar picker move it.
   */
  activeFolder(): vscode.WorkspaceFolder | undefined;
  /** The graph the panel is currently showing, or undefined. */
  currentGraph(): MLGraph | undefined;
  /** How many files changed since that graph was produced. */
  staleCount(): number;
  /** Publish a whole-workspace result the way the diagram path does. */
  applyGraph(graph: MLGraph, requestId: string, settings: MlviewSettings): void;
}

export async function analyzeForTools(
  input: ToolAnalyzeInput,
  token: vscode.CancellationToken | undefined,
  deps: ToolAnalyzeDeps
): Promise<MLGraph> {
  const folder = deps.activeFolder();
  if (!folder) {
    throw new CoreError('usage', 'No folder is open, so there is nothing to analyze.');
  }
  if (!isTrusted()) {
    throw new CoreError('restricted', RESTRICTED_MESSAGE);
  }
  const root = folder.uri.fsPath;
  // H10: a SCOPED call asks for a projection of the document, so neither half of the
  // whole-workspace shortcut applies - the cached graph is the wrong shape to answer with, and
  // the projected result must never be published as this folder's graph. `mlview.exclude`,
  // the Problems panel and the status bar all keep describing the project, not the question.
  const projected = typeof input.scope === 'string' && input.scope.trim().length > 0;
  const cached = deps.currentGraph();
  if (!input.path && !projected && cached && deps.staleCount() === 0) {
    return cached;
  }
  // SECURITY: `input.path` is MODEL-supplied. Refuse anything outside the open workspace
  // before it reaches the analyzer (CONTRACTS.md §4's openLocation guard, same reasoning).
  const resolved = resolveAnalysisTarget(root, input.path, {
    isInWorkspace: (fsPath) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath))
  });
  if (!resolved.ok) {
    deps.log.warn(`refused out-of-workspace analyze: ${resolved.fsPath || String(input.path)}`);
    throw new CoreError(
      'usage',
      'MLView only analyzes paths inside the open workspace.',
      `Refused ${String(input.path)}`
    );
  }
  const target = resolved.fsPath;
  const settings = readSettings(folder.uri);
  const result = await deps.core.analyze({
    scope: input.path ? 'file' : 'workspace',
    paths: [target],
    cwd: root,
    settings,
    ...(projected ? { scopeSpec: String(input.scope).trim() } : {}),
    ...(projected && typeof input.depth === 'number' ? { depth: input.depth } : {}),
    ...(token ? { token } : {})
  });
  if (!input.path && !projected) {
    deps.applyGraph(result.graph, nextRequestId('tool'), settings);
  }
  return result.graph;
}
