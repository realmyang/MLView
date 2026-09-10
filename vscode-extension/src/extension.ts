/**
 * MLView — VS Code / GitHub Copilot host adapter.
 *
 * This extension transports and renders; it never analyses. Everything it knows about Python
 * comes out of `python -m mlview analyze --json -`, and everything it draws comes out of the
 * shared viewer bundle in `media/`.
 *
 * Activation order matters (CONTRACTS.md §6): the diagram, diagnostics, reveal, CodeLens,
 * status bar and output channel register UNCONDITIONALLY; the chat participant and the
 * language-model tools register afterwards behind `typeof` guards inside try/catch, so a
 * chat-API change can never break activation.
 *
 * H10 (11.40): the controller no longer holds ONE graph. `src/folders.ts` keeps one
 * `FolderState` per open workspace folder and remembers which is active; a single-folder
 * window is the one-entry case and behaves exactly as it did.
 */

import * as vscode from 'vscode';
import { registerChatSurfaces } from './chatSurfaces';
import { registerComparisonCommands, type CompareHost } from './compare';
import { applyIssueFix, registerFixActions, type FixDeps } from './fixes';
import { registerSuppressionActions, runSuppression, type SuppressRequest } from './codeActions';
import { MlviewCodeLensProvider } from './codelens';
import { exportHtml, showIssues, showRuleDoc, type CommandHost } from './commands';
import { requestDiagramExport, type ExportPanelLike } from './exportDiagram';
import { AnalysisRunner } from './analysisRunner';
import { CoreClient, scopeKey } from './coreClient';
import { DiagnosticsPublisher } from './diagnostics';
import { reportAnalysisFailure, type ReportedFailure } from './failure';
import { FolderBook, pickFolder, type FolderState, type Scope } from './folders';
import { replayForReadyPanel, resolveRefreshScope, runHostAction } from './hostActions';
import { type MLGraph } from './graph';
import { allowedRuleCodes } from './issues';
import { createLogger, type Logger } from './log';
import { type CoreLike, type ToolAnalyzeInput } from './lmTools';
import { createBaseline, openConfiguration } from './mlviewConfig';
import { MlviewPanel, themeKindOf, VIEW_TYPE, type PanelDelegate } from './panel';
import { nextRequestId, type AnalysisScope, type ExportScope } from './protocol';
import { PythonEnvironment } from './pythonEnv';
import { revealInDiagram, type RevealArgs } from './revealInDiagram';
import { clearScope, scopeToSymbol, type ScopeDeps } from './scopeCommands';
import { readSettings, type MlviewSettings } from './settings';
import { renderStatusBar } from './statusBar';
import { analyzeForTools } from './toolAnalyze';
import { recordStale, registerWatchers } from './watchers';
import { manageTrust } from './trust';
import {
  refreshAnalysis,
  visualizeActiveFile,
  visualizeWorkspace,
  type VisualizeHost
} from './visualizeCommands';

let controller: MlviewController | undefined;

/** What a window with no folder open is scoped to; never analysed, only read. */
const NO_FOLDER_SCOPE: Scope = { scope: 'workspace' };

export function activate(ctx: vscode.ExtensionContext): void {
  const log = createLogger(() => readSettings().trace);
  ctx.subscriptions.push({ dispose: () => log.dispose() });
  const version = String(
    (ctx.extension?.packageJSON as { version?: string } | undefined)?.version ?? '0.1.0'
  );
  log.info(`MLView ${version} activating (VS Code ${vscode.version})`);

  const env = new PythonEnvironment(ctx, log);
  const core = new CoreClient(env, log);
  const diagnostics = new DiagnosticsPublisher(ctx, log);
  ctx.subscriptions.push(env, core, diagnostics);

  controller = new MlviewController(ctx, log, env, core, diagnostics);
  controller.registerUnconditional();
  controller.registerOptionalChatSurfaces();
}

export function deactivate(): void {
  controller?.dispose();
  controller = undefined;
}

class MlviewController
  implements
    PanelDelegate,
    CoreLike,
    CommandHost,
    CompareHost,
    FixDeps,
    VisualizeHost,
    vscode.Disposable
{
  /** H10: one graph, index, scope, stale set and remembered failure PER OPEN FOLDER. */
  private readonly book = new FolderBook();
  /** Single-flight, supersession, the busy count and graph adoption; see analysisRunner.ts. */
  private readonly runner: AnalysisRunner;
  private failed = false;
  private pendingRestore: unknown;
  private readonly statusBar: vscode.StatusBarItem;
  private readonly codeLens: MlviewCodeLensProvider;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    readonly ctx: vscode.ExtensionContext,
    readonly log: Logger,
    private readonly env: PythonEnvironment,
    readonly core: CoreClient,
    private readonly diagnostics: DiagnosticsPublisher
  ) {
    this.statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.statusBar.command = 'mlview.showIssues';
    this.codeLens = new MlviewCodeLensProvider(
      (document) => this.graphForFile(document.uri.fsPath),
      () => readSettings().codeLens
    );
    this.disposables.push(this.statusBar, this.codeLens);
    this.runner = new AnalysisRunner({
      log,
      core,
      settingsFor: (root) => readSettings(vscode.Uri.file(root)),
      isActive: (state) => this.state() === state,
      panel: () => this.livePanel(),
      analyzedGraphs: () => this.analyzedGraphs(),
      publish: (graphs, settings) => void this.diagnostics.publish(graphs, settings),
      refreshCodeLens: () => this.codeLens.refresh(),
      onStateChanged: () => this.updateStatusBar(),
      reportError: (err, requestId) => this.reportError(err, requestId),
      setFailed: (failed) => {
        this.failed = failed;
      }
    });
    this.updateStatusBar();
  }

  // ---------------------------------------------------------------- folder state

  /** The active folder's state, or undefined when no folder is open at all. */
  private state(): FolderState | undefined {
    return this.book.active();
  }

  /** The active folder's scope; the workspace default when there is no folder. */
  private scopeOf(): Scope {
    return this.state()?.lastScope ?? NO_FOLDER_SCOPE;
  }

  /**
   * The graph that knows about one file — the folder it lives in, NOT the active folder.
   * CodeLens is per-document, so answering with the active folder's graph in a multi-root
   * window would draw one folder's line numbers on another folder's file.
   */
  private graphForFile(fsPath: string): MLGraph | undefined {
    return (this.book.stateForAnalyzedFile(fsPath) ?? this.state())?.graph;
  }

  /** Every folder that has been analyzed — what the Problems panel publishes as a whole. */
  private analyzedGraphs(): MLGraph[] {
    return this.book.analyzed().flatMap((s) => (s.graph ? [s.graph] : []));
  }

  // ---------------------------------------------------------------- registration

  registerUnconditional(): void {
    const ctx = this.ctx;
    const cmd = vscode.commands.registerCommand;

    ctx.subscriptions.push(
      this,
      cmd('mlview.visualize', () => visualizeActiveFile(this)),
      cmd('mlview.visualizeWorkspace', () => visualizeWorkspace(this)),
      cmd('mlview.refresh', () => refreshAnalysis(this)),
      cmd('mlview.showIssues', () => showIssues(this)),
      cmd('mlview.revealInDiagram', (args?: RevealArgs) => this.reveal(args)),
      cmd('mlview.scopeToSymbol', () => scopeToSymbol(this.diagramDeps())),
      cmd('mlview.clearScope', () => clearScope(this.diagramDeps())),
      cmd('mlview.exportHtml', () => exportHtml(this)),
      // VIEW-07 (11.33): the host cannot draw, so these ASK the open panel for the bytes.
      cmd('mlview.exportSvg', (s?: ExportScope) => requestDiagramExport('svg', this.exportDeps(), s)),
      cmd('mlview.exportPng', (s?: ExportScope) => requestDiagramExport('png', this.exportDeps(), s)),
      // H10: the multi-root picker, also reachable from the status-bar tooltip.
      cmd('mlview.activeFolder', () => this.selectActiveFolder()),
      // CFG-ONE: the two configuration commands (11.40).
      cmd('mlview.openConfiguration', () => openConfiguration(this)),
      cmd('mlview.createBaseline', () => createBaseline(this)),
      cmd('mlview.selectInterpreter', () => this.env.selectInterpreter()),
      cmd('mlview.showOutput', () => this.log.show(false)),
      cmd('mlview.showRuleDoc', (code?: string) => showRuleDoc(this, code)),
      vscode.languages.registerCodeLensProvider({ language: 'python' }, this.codeLens),
      // MLV-P10: the lightbulb and its three commands. Unconditional, like every other
      // editor surface - a code action provider has no API to feature-detect.
      ...registerSuppressionActions(this.log),
      // H5: the structured-fix lightbulb and `mlview.applyFix`. Also unconditional, and also
      // argument-taking, so `mlview.applyFix` is deliberately NOT in the command palette.
      ...registerFixActions(this),
      // VIEW-08: the three comparison commands.
      ...registerComparisonCommands(this),
      vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
        deserializeWebviewPanel: async (panel, state: unknown) => {
          this.log.info('restoring the MLView panel from a saved window state');
          this.pendingRestore = state;
          MlviewPanel.revive(panel, this.ctx, this);
        }
      }),
      // The five workspace listeners: two saves (text and notebook), a change, a folder
      // change and a configuration change. src/watchers.ts owns what each one means.
      ...registerWatchers(this)
    );
    this.statusBar.show();
    this.log.info('commands, panel serializer, diagnostics, CodeLens and status bar registered');
  }

  /** Feature-detected surfaces. Absence must degrade to "not present", never to a failure. */
  /** The guarded chat participant and language-model tools; see src/chatSurfaces.ts. */
  registerOptionalChatSurfaces(): void {
    registerChatSurfaces({
      ctx: this.ctx,
      log: this.log,
      analyzer: this,
      showDiagram: (focusNodeId?: string, scopeSpec?: string) =>
        this.showDiagram(focusNodeId, scopeSpec)
    });
  }

  // ---------------------------------------------------------------- commands

  // The three diagram commands live in src/visualizeCommands.ts; these are the adapters
  // that hand them the controller's folder state.

  activeState(): FolderState | undefined {
    return this.state();
  }

  setActiveFolder(folder: vscode.WorkspaceFolder): boolean {
    return this.book.setActive(folder);
  }

  runOnce(state: FolderState): Promise<void> {
    return this.runner.once(state);
  }

  runFresh(state: FolderState): Promise<void> {
    return this.runner.run(state);
  }

  invalidateInterpreter(): void {
    this.env.invalidate();
  }

  /**
   * H10 — `MLView: Select Active Folder`, and the tooltip's "Analyze a different folder" link.
   * A folder that has already been analyzed is shown from memory; one that has not is
   * analyzed, which is the whole point of the command in a window where only the first folder
   * has ever been looked at.
   */
  private async selectActiveFolder(): Promise<void> {
    const folder = await pickFolder(this.book);
    if (!folder) {
      return;
    }
    this.book.setActive(folder);
    const state = this.book.stateFor(folder);
    this.log.info(`active folder is now ${folder.name} (${folder.uri.fsPath})`);
    this.codeLens.refresh();
    this.updateStatusBar();
    if (!state.graph) {
      await this.ensurePanel();
      await this.runner.once(state);
      return;
    }
    const panel = this.livePanel();
    if (panel) {
      const settings = readSettings(folder.uri);
      panel.postGraph(nextRequestId('folder'), state.graph);
      panel.postSetFilter(allowedRuleCodes(state.graph, settings.disabledRules));
      panel.postStale(Array.from(state.staleFiles));
    }
  }

  /**
   * The members `RevealDeps` (Alt+M) and `ScopeDeps` (Alt+Shift+M, §11.11) need. `getPanel`
   * is the read-only twin of `ensurePanel`: it answers with the live panel and never opens
   * one, so `clearScope` can stay a no-op in a window with no diagram.
   */
  private diagramDeps(): ScopeDeps {
    return {
      log: this.log,
      getGraph: () => this.state()?.graph,
      getIndex: () => this.state()?.index,
      ensurePanel: () => this.ensurePanel(),
      getPanel: () => this.livePanel(),
      ensureGraph: () => this.ensureGraph()
    };
  }

  private async reveal(args?: RevealArgs): Promise<void> {
    await revealInDiagram(args, this.diagramDeps());
  }

  /**
   * MLV-P10 — the viewer's `suppressRule`. It runs `runSuppression`, which is the exact
   * function the three editor commands run, so the confirm dialog, the containment
   * check and the "already ignored" message are the same on both surfaces.
   */
  onSuppressRule(request: SuppressRequest): void {
    void runSuppression(request, this.log);
  }

  /**
   * H5 — the viewer's `applyFix`. It runs `applyIssueFix`, the exact function
   * `mlview.applyFix` and the editor lightbulb run, so the containment check, the `likely`
   * floor and VS Code's refactor preview are the same on both surfaces.
   */
  onApplyFix(issueId: string): void {
    void applyIssueFix(issueId, this);
  }

  // --- FixDeps -----------------------------------------------------------------

  /** Every analyzed folder's graph: the fix surfaces see what the Problems panel publishes. */
  graphs(): readonly MLGraph[] {
    return this.analyzedGraphs();
  }

  // --- CompareHost -------------------------------------------------------------

  /** VIEW-08: the live diagram an overlay is posted to. Never opens one. */
  comparisonPanel(): MlviewPanel | undefined {
    return this.livePanel();
  }

  // ---------------------------------------------------------------- analysis

  private pathsFor(scope: Scope, root: string): string[] {
    return scope.scope === 'file' && scope.path ? [scope.path] : [root];
  }

  // --- CommandHost -------------------------------------------------------------

  currentPaths(root: string): string[] {
    return this.pathsFor(this.scopeOf(), root);
  }

  currentScope(): AnalysisScope {
    return this.scopeOf().scope;
  }

  getGraph(): MLGraph | undefined {
    return this.state()?.graph;
  }

  async ensureGraph(): Promise<MLGraph | undefined> {
    const state = this.state();
    if (!state) {
      return undefined;
    }
    await this.runner.once(state);
    return state.graph;
  }

  settingsFor(uri: vscode.Uri): MlviewSettings {
    return readSettings(uri);
  }

  workspaceRoot(): string | undefined {
    const state = this.state();
    return state?.graph?.workspace.root ?? state?.root;
  }

  /** The `vscode.WorkspaceFolder` the language-model and chat paths analyze (H10). */
  private activeFolder(): vscode.WorkspaceFolder | undefined {
    return this.book.activeFolder();
  }

  /** Returns what it reported, so a caller can remember the banner for a webview that boots late. */
  reportError(err: unknown, requestId: string): ReportedFailure {
    this.failed = true;
    this.updateStatusBar();
    return reportAnalysisFailure(err, requestId, {
      log: this.log,
      onAction: (id) => this.onAction(id)
    });
  }

  // ------------------------------------------------------------------- WatchHost

  markStale(fsPath: string): void {
    const state = this.book.stateForAnalyzedFile(fsPath) ?? this.state();
    if (!state) {
      return;
    }
    if (recordStale(state.graph?.workspace.root, fsPath, state.staleFiles)) {
      if (this.state() === state) {
        MlviewPanel.current?.postStale(Array.from(state.staleFiles));
      }
    }
  }

  /**
   * H10: the active folder always (which is exactly what a single-folder window did), plus
   * every other folder that has an analyzed graph and a file marked stale in it — a save in
   * the second folder of a multi-root window used to update nothing at all.
   */
  reanalyze(): void {
    const targets = new Set<FolderState>();
    const active = this.state();
    if (active) {
      targets.add(active);
    }
    for (const state of this.book.analyzed()) {
      if (state.staleFiles.size > 0) {
        targets.add(state);
      }
    }
    if (targets.size === 0) {
      return;
    }
    this.core.scheduleAnalyze(() => {
      for (const state of targets) {
        void this.runner.run(state);
      }
    });
  }

  refreshCodeLens(): void {
    this.codeLens.refresh();
  }

  republish(): void {
    const graphs = this.analyzedGraphs();
    if (graphs.length === 0) {
      return;
    }
    const settings = readSettings();
    this.diagnostics.publish(graphs, settings);
    const shown = this.state()?.graph;
    if (shown) {
      MlviewPanel.current?.postSetFilter(allowedRuleCodes(shown, settings.disabledRules));
    }
    this.updateStatusBar();
  }

  resetForWorkspaceChange(): void {
    const dropped = this.book.prune();
    if (dropped > 0) {
      this.log.info(`${dropped} workspace folder(s) closed - their MLView graphs were dropped`);
    }
    this.diagnostics.clear();
    const graphs = this.analyzedGraphs();
    if (graphs.length > 0) {
      this.diagnostics.publish(graphs, readSettings());
    }
    this.codeLens.refresh();
    this.updateStatusBar();
  }

  private updateStatusBar(): void {
    const state = this.state();
    const names = this.book.open().map((f) => f.name);
    renderStatusBar(this.statusBar, {
      ...(state?.graph ? { graph: state.graph } : {}),
      settings: readSettings(state ? vscode.Uri.file(state.root) : undefined),
      busy: this.runner.busy(),
      failed: this.failed,
      // PACKAGING: names the installed-vs-bundled core, once the chain has run once.
      ...(this.env.coreDescription() ? { core: this.env.coreDescription()! } : {}),
      folders: { ...(state ? { active: state.name } : {}), names }
    });
  }

  // ---------------------------------------------------------------- PanelDelegate

  async ensurePanel(): Promise<MlviewPanel | undefined> {
    return MlviewPanel.createOrShow(this.ctx, this);
  }

  /** The open diagram panel, or undefined. Unlike `ensurePanel` this never creates one. */
  private livePanel(): MlviewPanel | undefined {
    const panel = MlviewPanel.current;
    return panel && !panel.isDisposed ? panel : undefined;
  }

  onReady(panel: MlviewPanel): void {
    const state = this.state();
    const key = state ? scopeKey(state.lastScope.scope, state.lastScope.path) : '';
    replayForReadyPanel(panel, {
      graph: state?.graph,
      pendingRestore: this.pendingRestore,
      disabledRules: readSettings().disabledRules,
      staleFiles: state ? Array.from(state.staleFiles) : [],
      replayableFailure: state?.lastFailure?.key === key ? state.lastFailure : undefined,
      analyzeOnce: () => {
        if (state) {
          void this.runner.once(state);
        }
      },
      themeKind: () => themeKindOf(vscode.window.activeColorTheme.kind)
    });
    this.pendingRestore = undefined;
  }

  onRequestRefresh(scope: AnalysisScope, targetPath?: string): void {
    const state = this.state();
    if (!state) {
      return;
    }
    state.lastScope = resolveRefreshScope(
      scope,
      targetPath,
      this.workspaceRoot(),
      state.lastScope.path
    );
    void this.runner.run(state);
  }

  /** VIEW-07: the export commands see the LIVE panel only; they never open one. */
  private exportDeps(): { log: Logger; panel(): ExportPanelLike | undefined } {
    return { log: this.log, panel: () => this.livePanel() };
  }

  onExportHtml(): void {
    void exportHtml(this);
  }

  onAction(id: string): void {
    const state = this.state();
    runHostAction(id, {
      log: this.log,
      retry: () => {
        if (state) {
          void this.runner.run(state);
        }
      },
      showOutput: () => this.log.show(false),
      envAction: (action) => void this.env.runAction(action),
      manageTrust
    });
  }

  onSelectNode(nodeId: string | null): void {
    this.log.debug(`node selected: ${nodeId ?? 'none'}`);
  }

  // ---------------------------------------------------------------- CoreLike

  /** Used by the chat participant and the language-model tools. */
  async analyze(
    input: ToolAnalyzeInput,
    token?: vscode.CancellationToken
  ): Promise<MLGraph> {
    return analyzeForTools(input, token, {
      log: this.log,
      core: this.core,
      activeFolder: () => this.activeFolder(),
      currentGraph: () => this.state()?.graph,
      staleCount: () => this.state()?.staleFiles.size ?? 0,
      applyGraph: (graph, requestId, settings) => {
        const state = this.state();
        if (state) {
          this.runner.apply(state, graph, requestId, settings);
        }
      }
    });
  }

  /**
   * H10: `scopeSpec` opens the diagram AT a §11.1 selector, through the same `setScope` message
   * `MLView: Scope Diagram to Symbol` posts — so "show me the evaluation stage" from agent mode
   * lands on the same projection a keyboard user would reach, and the reader can clear it.
   */
  showDiagram(focusNodeId?: string, scopeSpec?: string): Promise<void> {
    return this.ensurePanel().then((panel) => {
      if (!panel) {
        return;
      }
      if (scopeSpec) {
        panel.postSetScope(scopeSpec);
      }
      if (focusNodeId) {
        panel.postRevealNode(focusNodeId, false);
      }
    });
  }

  dispose(): void {
    for (const d of this.disposables) {
      d.dispose();
    }
    MlviewPanel.current?.dispose();
  }
}
