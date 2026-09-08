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
import { nextRequestId } from './protocol';
import { readSettings, type MlviewSettings } from './settings';
import { isTrusted, RESTRICTED_MESSAGE } from './trust';

export interface ToolAnalyzeDeps {
  log: Logger;
  core: CoreClient;
  /** The graph the panel is currently showing, or undefined. */
  currentGraph(): MLGraph | undefined;
  /** How many files changed since that graph was produced. */
  staleCount(): number;
  /** Publish a whole-workspace result the way the diagram path does. */
  applyGraph(graph: MLGraph, requestId: string, settings: MlviewSettings): void;
}

export async function analyzeForTools(
  input: { path?: string },
  token: vscode.CancellationToken | undefined,
  deps: ToolAnalyzeDeps
): Promise<MLGraph> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new CoreError('usage', 'No folder is open, so there is nothing to analyze.');
  }
  if (!isTrusted()) {
    throw new CoreError('restricted', RESTRICTED_MESSAGE);
  }
  const root = folder.uri.fsPath;
  const cached = deps.currentGraph();
  if (!input.path && cached && deps.staleCount() === 0) {
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
    ...(token ? { token } : {})
  });
  if (!input.path) {
    deps.applyGraph(result.graph, nextRequestId('tool'), settings);
  }
  return result.graph;
}
