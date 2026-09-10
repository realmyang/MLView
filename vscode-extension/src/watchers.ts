/**
 * The editor events the host listens to, and what each one means — the classification as pure
 * functions, the wiring as one `registerWatchers` call, so `extension.ts` keeps the state and
 * this file keeps the policy.
 *
 * There are two save events, not one. `onDidSaveTextDocument` fires for a `.py` file;
 * `onDidSaveNotebookDocument` fires for an `.ipynb`, and the text event does NOT fire for it,
 * so a notebook workspace with `mlview.analyzeOnSave` on would never re-analyze without the
 * second listener (NB).
 */

import * as vscode from 'vscode';
import { toWorkspaceRelative } from './location';
import type { MlviewSettings } from './settings';

/**
 * `ignore` — not ours, do nothing at all.
 * `stale-only` — mark the file stale so the diagram says it is out of date, but do not spend
 * an analysis on it: that is what `mlview.analyzeOnSave: false` asks for.
 * `reanalyze` — mark it stale and schedule the debounced re-analysis.
 */
export type SaveReaction = 'ignore' | 'stale-only' | 'reanalyze';

/** A saved text document. Only Python is ours; everything else is somebody else's file. */
export function reactToTextSave(languageId: string, settings: MlviewSettings): SaveReaction {
  if (languageId !== 'python') {
    return 'ignore';
  }
  return settings.analyzeOnSave ? 'reanalyze' : 'stale-only';
}

/**
 * NB: a saved notebook. `mlview.includeNotebooks` gates it before `analyzeOnSave` does,
 * because a run that will not read the notebook has nothing to say about the save — the graph
 * would come back identical, so marking it stale would be a lie and re-analyzing it would be
 * pure cost.
 */
export function reactToNotebookSave(settings: MlviewSettings): SaveReaction {
  if (!settings.includeNotebooks) {
    return 'ignore';
  }
  return settings.analyzeOnSave ? 'reanalyze' : 'stale-only';
}

/**
 * The settings whose change only re-filters a graph the host already has. Re-publishing is
 * cheap and instant; re-analysing for one of these would be a wasted interpreter.
 */
export const REPUBLISH_KEYS = [
  'mlview.minConfidence',
  'mlview.minSeverity',
  'mlview.diagnosticSeverity',
  'mlview.diagnosticsEnabled',
  'mlview.disabledRules'
] as const;

/**
 * The settings that change WHAT IS ANALYZED rather than how a finished graph is filtered.
 * Re-publishing for one of these would show the same graph back and read as "the setting does
 * nothing", so they are the only `mlview.*` keys that re-run the analyzer. NB put the first
 * one here: turning `includeNotebooks` on with no re-analysis leaves every notebook missing.
 */
export const REANALYZE_KEYS = ['mlview.includeNotebooks'] as const;

export interface ConfigReaction {
  refreshCodeLens: boolean;
  reanalyze: boolean;
  republish: boolean;
}

export function reactToConfigChange(affects: (key: string) => boolean): ConfigReaction {
  return {
    refreshCodeLens: affects('mlview.codeLens'),
    reanalyze: REANALYZE_KEYS.some((key) => affects(key)),
    republish: REPUBLISH_KEYS.some((key) => affects(key))
  };
}

/**
 * Record `fsPath` as stale relative to the analyzed root, and say whether that changed
 * anything. Returns undefined when there is no graph yet, when the file is outside the
 * analyzed root, or when it was already known stale — the three cases in which the viewer
 * must not be re-posted.
 */
export function recordStale(
  root: string | undefined,
  fsPath: string,
  seen: Set<string>
): string | undefined {
  if (!root) {
    return undefined;
  }
  const relative = toWorkspaceRelative(root, fsPath);
  if (relative.startsWith('..') || seen.has(relative)) {
    return undefined;
  }
  seen.add(relative);
  return relative;
}

/** What `registerWatchers` needs of the controller. Every member is called by an event. */
export interface WatchHost {
  settingsFor(uri: vscode.Uri): MlviewSettings;
  markStale(fsPath: string): void;
  reanalyze(): void;
  refreshCodeLens(): void;
  republish(): void;
  resetForWorkspaceChange(): void;
}

function applySave(host: WatchHost, reaction: SaveReaction, fsPath: string): void {
  if (reaction === 'ignore') {
    return;
  }
  host.markStale(fsPath);
  if (reaction === 'reanalyze') {
    host.reanalyze();
  }
}

/** The five workspace listeners, in registration order. */
export function registerWatchers(host: WatchHost): vscode.Disposable[] {
  return [
    vscode.workspace.onDidSaveTextDocument((doc) =>
      applySave(host, reactToTextSave(doc.languageId, host.settingsFor(doc.uri)), doc.uri.fsPath)
    ),
    vscode.workspace.onDidSaveNotebookDocument((nb) =>
      applySave(host, reactToNotebookSave(host.settingsFor(nb.uri)), nb.uri.fsPath)
    ),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.languageId === 'python') {
        host.markStale(e.document.uri.fsPath);
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => host.resetForWorkspaceChange()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      const reaction = reactToConfigChange((key) => e.affectsConfiguration(key));
      if (reaction.refreshCodeLens) {
        host.refreshCodeLens();
      }
      if (reaction.reanalyze) {
        host.reanalyze();
      }
      if (reaction.republish) {
        host.republish();
      }
    })
  ];
}
