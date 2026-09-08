/**
 * The one place an analysis failure is turned into user-visible surfaces.
 *
 * Three of them, always together (CONTRACTS.md §4, UX_DESIGN §12 "hard error"): the webview's
 * error banner with its action buttons, a modal notification carrying the same buttons, and the
 * output channel with the full detail. Returning what it reported is what lets the controller
 * replay the banner for a webview that finishes booting after the run has already failed.
 *
 * Split out of extension.ts to keep that file inside the repo's ~600-line budget.
 */

import * as vscode from 'vscode';
import { CoreError, type CoreAction } from './coreClient';
import type { Logger } from './log';
import { MlviewPanel } from './panel';

export interface ReportedFailure {
  message: string;
  detail: string;
  actions: CoreAction[];
}

export interface FailureDeps {
  log: Logger;
  /** Runs the banner/notification action the user chose. */
  onAction(id: string): void;
}

export function reportAnalysisFailure(
  err: unknown,
  requestId: string,
  deps: FailureDeps
): ReportedFailure {
  const coreError = err instanceof CoreError ? err : undefined;
  const message = coreError?.message ?? (err instanceof Error ? err.message : String(err));
  const detail = coreError?.detail ?? '';
  const actions = coreError?.actions ?? [{ id: 'showOutput', label: 'Show Output' }];
  deps.log.error(`analysis failed: ${message}${detail ? `\n${detail}` : ''}`);
  MlviewPanel.current?.postAnalysisFailed(requestId, message, detail, actions);
  void vscode.window
    .showErrorMessage(`MLView: ${message}`, ...actions.map((a) => a.label))
    .then((choice) => {
      const action = actions.find((a) => a.label === choice);
      if (action) {
        deps.onAction(action.id);
      }
    });
  return { message, detail, actions };
}
