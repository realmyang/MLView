/**
 * The two small routers the webview drives, split out of `extension.ts` to keep it
 * under the repo's ~600-line file budget (`test/hygiene.test.js`).
 *
 * Both are pure dispatch: they decide WHICH host behaviour a message asks for and
 * hand back to the controller to perform it. Neither analyses, spawns or draws.
 */

import * as path from 'node:path';
import type { MLGraph } from './graph';
import { allowedRuleCodes } from './issues';
import type { Logger } from './log';
import type { MlviewPanel } from './panel';
import { ACTION_IDS, nextRequestId, type AnalysisScope } from './protocol';
import type { CoreAction } from './coreClient';

export interface HostActionDeps {
  log: Logger;
  /** `retry` — re-run the analysis for the current scope. */
  retry: () => void;
  /** `showOutput` — reveal the output channel. */
  showOutput: () => void;
  /** `selectInterpreter` / `installCore` — the PythonEnvironment remediations. */
  envAction: (id: string) => void;
  /** `manageTrust` — the workspace-trust affordance (§6). */
  manageTrust: () => void;
}

/**
 * The error-banner action ids, answered exactly as `protocol.ts` freezes them, plus
 * `manageTrust` which the restricted-mode banner adds. An id nobody knows is logged
 * and ignored — a viewer from a newer build must degrade, never crash the host.
 */
export function runHostAction(id: string, deps: HostActionDeps): void {
  switch (id) {
    case 'retry':
      deps.retry();
      return;
    case 'showOutput':
      deps.showOutput();
      return;
    case 'selectInterpreter':
    case 'installCore':
      deps.envAction(id);
      return;
    case 'manageTrust':
      deps.manageTrust();
      return;
    default:
      deps.log.warn(
        `unknown webview action: ${id} (known: ${[...ACTION_IDS, 'manageTrust'].join(', ')})`
      );
  }
}

export interface RefreshScope {
  scope: AnalysisScope;
  path?: string;
}

/**
 * `requestRefresh` carries a WORKSPACE-RELATIVE path (CONTRACTS §4); the analyzer is
 * always handed an absolute one. A `file` refresh with nothing to resolve against
 * degrades to the whole workspace rather than to an analysis of `undefined`.
 */
export function resolveRefreshScope(
  scope: AnalysisScope,
  targetPath: string | undefined,
  root: string | undefined,
  fallbackPath: string | undefined
): RefreshScope {
  const absolute = targetPath && root ? path.resolve(root, targetPath) : fallbackPath;
  return scope === 'file' && absolute ? { scope: 'file', path: absolute } : { scope: 'workspace' };
}

export interface ReadyDeps {
  graph: MLGraph | undefined;
  /** The `restoreState` a window reload left behind, consumed exactly once. */
  pendingRestore: unknown;
  disabledRules: readonly string[];
  staleFiles: readonly string[];
  /** The banner a run that already failed left, when it belongs to the CURRENT scope. */
  replayableFailure:
    | { requestId: string; message: string; detail: string; actions: CoreAction[] }
    | undefined;
  /** Join the run that opened this panel; never start a second one. */
  analyzeOnce: () => void;
  themeKind: () => Parameters<MlviewPanel['postInit']>[0];
}

/**
 * The `ready` handshake: init, the restored view state, then either the graph the host
 * already holds, the banner the failed run already produced, or the analysis that is
 * still in flight.
 *
 * The middle branch is the subtle one. `analyzeScopeOnce` can only join a run that is
 * STILL in flight, so a first analysis that failed before the webview finished booting
 * would otherwise be silently repeated by `onReady` — a second interpreter chain, a
 * second analyzer spawn and a second identical modal, which is exactly the first-run
 * experience of anyone with no `mlview` core installed.
 */
export function replayForReadyPanel(panel: MlviewPanel, deps: ReadyDeps): void {
  panel.postInit(deps.themeKind());
  const restore = deps.pendingRestore ?? panel.savedState();
  if (restore && typeof restore === 'object') {
    panel.postRestoreState(restore as Record<string, unknown>);
  }
  if (deps.graph) {
    panel.postGraph(nextRequestId('restore'), deps.graph);
    panel.postSetFilter(allowedRuleCodes(deps.graph, [...deps.disabledRules]));
    if (deps.staleFiles.length > 0) {
      panel.postStale([...deps.staleFiles]);
    }
    return;
  }
  if (deps.replayableFailure) {
    const failure = deps.replayableFailure;
    panel.postAnalysisFailed(failure.requestId, failure.message, failure.detail, failure.actions);
    return;
  }
  deps.analyzeOnce();
}
