/**
 * The analysis engine: single-flight, supersession, the busy count, and what happens to a
 * finished graph.
 *
 * Split out of `extension.ts` when H10's per-folder map pushed that file past the repo's
 * ~600-line budget (`test/hygiene.test.js`). The seam is a real one: everything here is about
 * RUNNING an analysis and publishing its result, and everything left in `extension.ts` is
 * about wiring VS Code surfaces to it.
 *
 * The three behaviours that are easy to lose in a rewrite and are the reason this is one class:
 *
 * 1. **`busyRuns` is a COUNT, not a flag.** A run superseded mid-flight must not clear the
 *    spinner for the run that replaced it, or the status bar flicks back to idle while
 *    analysis continues.
 * 2. **`once()` joins, `run()` supersedes.** Opening the diagram is `ensurePanel()` + a run,
 *    and the webview's `ready` arrives while that run is still going; without joining, one
 *    whole interpreter is spawned and killed on every first open.
 * 3. **The key is FOLDER + scope** (H10). Two folders both analysing `workspace` are two runs,
 *    not one that keeps cancelling the other.
 */

import { CoreError, scopeKey, type CoreClient } from './coreClient';
import { focusScopeSpec } from './currentFile';
import type { FolderState } from './folders';
import type { MLGraph } from './graph';
import { allowedRuleCodes } from './issues';
import { toWorkspaceRelative } from './location';
import { buildLocationIndex } from './locationIndex';
import type { Logger } from './log';
import type { MlviewPanel } from './panel';
import { nextRequestId } from './protocol';
import type { MlviewSettings } from './settings';
import { ensureTrusted } from './trust';
import type { ReportedFailure } from './failure';

/** Everything the runner needs of the controller. Every member is called during a run. */
export interface RunnerDeps {
  log: Logger;
  core: CoreClient;
  settingsFor(root: string): MlviewSettings;
  /** True when this folder is the one the diagram and the status bar are showing. */
  isActive(state: FolderState): boolean;
  /** The live diagram panel, or undefined. Never opens one. */
  panel(): MlviewPanel | undefined;
  /** Every analyzed folder's graph — the Problems panel publishes them as one set. */
  analyzedGraphs(): MLGraph[];
  publish(graphs: MLGraph[], settings: MlviewSettings): void;
  refreshCodeLens(): void;
  /** Redraw the status bar; called on every busy / failed transition. */
  onStateChanged(): void;
  /** Report a failure exactly as the controller does, and say what it reported. */
  reportError(err: unknown, requestId: string): ReportedFailure;
  /** Clear the controller's `failed` flag when a run starts or succeeds. */
  setFailed(failed: boolean): void;
}

export class AnalysisRunner {
  private busyRuns = 0;
  private readonly inFlight = new Map<string, Promise<void>>();

  constructor(private readonly deps: RunnerDeps) {}

  busy(): boolean {
    return this.busyRuns > 0;
  }

  /** Folder + scope, so two folders analysing `workspace` do not share one in-flight run. */
  private keyFor(state: FolderState): string {
    return `${state.key}|${scopeKey(state.lastScope.scope, state.lastScope.path)}`;
  }

  /**
   * Start (or supersede) an analysis of this folder's scope. The returned promise never
   * rejects: every failure is already reported to the panel, the status bar and the output
   * channel.
   */
  run(state: FolderState): Promise<void> {
    const key = this.keyFor(state);
    const promise = this.execute(state).finally(() => {
      if (this.inFlight.get(key) === promise) {
        this.inFlight.delete(key);
      }
    });
    this.inFlight.set(key, promise);
    return promise;
  }

  /** Join the run already in flight for this folder + scope instead of starting a duplicate. */
  once(state: FolderState): Promise<void> {
    const running = this.inFlight.get(this.keyFor(state));
    if (running) {
      this.deps.log.debug('joining the analysis already in flight for this scope');
      return running;
    }
    return this.run(state);
  }

  private paths(state: FolderState): string[] {
    const scope = state.lastScope;
    return scope.scope === 'file' && scope.path ? [scope.path] : [state.root];
  }

  private async execute(state: FolderState): Promise<void> {
    if (!ensureTrusted(this.deps.log)) {
      return;
    }
    const scope = state.lastScope;
    const key = scopeKey(scope.scope, scope.path);
    if (state.lastFailure?.key === key) {
      // This scope is being attempted again; the remembered banner is about to be replaced.
      state.lastFailure = undefined;
    }
    const requestId = nextRequestId('analyze');
    const root = state.root;
    const settings = this.deps.settingsFor(root);
    this.busyRuns += 1;
    this.deps.setFailed(false);
    this.deps.onStateChanged();
    const active = this.deps.isActive(state);
    const panel = active ? this.deps.panel() : undefined;
    if (panel) {
      panel.postAnalysisStarted(
        requestId,
        scope.scope,
        scope.path ? toWorkspaceRelative(root, scope.path) : undefined
      );
    }
    try {
      const result = await this.deps.core.analyze({
        scope: scope.scope,
        paths: this.paths(state),
        cwd: root,
        settings,
        // H3: `--progress-json` is passed EXACTLY when there is a panel to draw the bar, so
        // the headless paths (`mlview.showIssues`, the chat digests, the LM tools) spawn the
        // analyzer with the argv they have always spawned it with.
        ...(panel && !panel.isDisposed
          ? { onProgress: panel.progressListener(requestId) }
          : {})
      });
      this.apply(state, result.graph, requestId, settings);
      this.deps.log.info(
        `analysis finished in ${result.durationMs} ms: ${result.graph.stats.nodes} nodes, ` +
          `${result.graph.stats.edges} edges`
      );
    } catch (err) {
      if (err instanceof CoreError && err.kind === 'cancelled') {
        this.deps.log.info('analysis cancelled');
      } else {
        state.lastFailure = { key, requestId, ...this.deps.reportError(err, requestId) };
      }
    } finally {
      this.busyRuns = Math.max(0, this.busyRuns - 1);
      this.deps.onStateChanged();
    }
  }

  /**
   * Adopt a finished graph as this folder's. Public because the language-model path produces
   * one too (`toolAnalyze.ts`) and must publish it exactly the way the diagram path does.
   */
  apply(
    state: FolderState,
    graph: MLGraph,
    requestId: string,
    settings: MlviewSettings
  ): void {
    state.graph = graph;
    state.lastFailure = undefined;
    state.index = buildLocationIndex(graph);
    state.staleFiles.clear();
    // H10: the Problems panel is a WINDOW surface, so it publishes every analyzed folder at
    // once. Publishing only this one would clear the other folder's squiggles.
    this.deps.publish(this.deps.analyzedGraphs(), settings);
    this.deps.refreshCodeLens();
    this.deps.setFailed(false);
    this.deps.onStateChanged();
    const panel = this.deps.panel();
    if (panel && this.deps.isActive(state)) {
      panel.postGraph(requestId, graph);
      panel.postSetFilter(allowedRuleCodes(graph, settings.disabledRules));
      this.applyFocusScope(state, panel, graph);
    }
  }

  /**
   * COVERAGE: the analysis went as wide as `mlview.currentFileAnalysisScope` asked for, so the
   * DIAGRAM is narrowed back to the file the user pointed at — through the same §11.7 message
   * `MLView: Scope Diagram to Symbol` uses, which means no new protocol and no re-analysis.
   * Posted once per command: after that the viewer owns its scope.
   */
  private applyFocusScope(state: FolderState, panel: MlviewPanel, graph: MLGraph): void {
    const focus = state.lastScope.focusFile;
    if (!focus || state.appliedFocus === focus) {
      return;
    }
    state.appliedFocus = focus;
    const spec = focusScopeSpec(graph.workspace.root, focus);
    if (spec) {
      panel.postSetScope(spec);
    } else {
      this.deps.log.warn(
        `focus file ${focus} is outside the analyzed root; leaving the scope alone`
      );
    }
  }
}
