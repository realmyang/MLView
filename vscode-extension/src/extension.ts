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
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { registerChatSurfaces } from './chatSurfaces';
import { registerSuppressionActions, runSuppression, type SuppressRequest } from './codeActions';
import { MlviewCodeLensProvider } from './codelens';
import { exportHtml, showIssues, showRuleDoc, type CommandHost } from './commands';
import { requestDiagramExport, type ExportPanelLike } from './exportDiagram';
import { CoreClient, CoreError, scopeKey, type CoreAction } from './coreClient';
import { focusScopeSpec, resolveCurrentFileTarget } from './currentFile';
import { DiagnosticsPublisher } from './diagnostics';
import { reportAnalysisFailure, type ReportedFailure } from './failure';
import { replayForReadyPanel, resolveRefreshScope, runHostAction } from './hostActions';
import { type MLGraph } from './graph';
import { allowedRuleCodes } from './issues';
import { toWorkspaceRelative } from './location';
import { buildLocationIndex, type LocationIndex } from './locationIndex';
import { createLogger, type Logger } from './log';
import { type CoreLike } from './lmTools';
import { MlviewPanel, themeKindOf, VIEW_TYPE, type PanelDelegate } from './panel';
import { nextRequestId, type AnalysisScope, type ExportScope } from './protocol';
import { PythonEnvironment } from './pythonEnv';
import { revealInDiagram, type RevealArgs } from './revealInDiagram';
import { clearScope, scopeToSymbol, type ScopeDeps } from './scopeCommands';
import { readSettings, type MlviewSettings } from './settings';
import { renderStatusBar } from './statusBar';
import { analyzeForTools } from './toolAnalyze';
import { recordStale, registerWatchers } from './watchers';
import { ensureTrusted, manageTrust } from './trust';

let controller: MlviewController | undefined;

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

interface Scope {
  scope: AnalysisScope;
  /** Absolute path when the scope is a single file. */
  path?: string;
  /**
   * COVERAGE: the file the DIAGRAM is narrowed to once the graph arrives, when the analysis
   * itself deliberately went wider (`mlview.currentFileAnalysisScope` = `package` /
   * `workspace`). It is not part of `scopeKey`: it changes the projection, never the run.
   */
  focusFile?: string;
}

class MlviewController implements PanelDelegate, CoreLike, CommandHost, vscode.Disposable {
  private graph: MLGraph | undefined;
  private index: LocationIndex | undefined;
  private lastScope: Scope = { scope: 'workspace' };
  private readonly staleFiles = new Set<string>();
  /**
   * A COUNT, not a flag: a run that is superseded mid-flight must not clear the spinner for the
   * run that replaced it (the status bar would flick back to idle while analysis continues).
   */
  private busyRuns = 0;
  /** One promise per scope key, so a second caller joins the run instead of starting another. */
  private readonly inFlight = new Map<string, Promise<void>>();
  private failed = false;
  /**
   * The last analysis failure, remembered per scope. `analyzeScopeOnce` can only join a run that
   * is STILL in flight, so without this a first analysis that fails before the webview finishes
   * booting is silently repeated by `onReady` — a second interpreter chain, a second analyzer
   * spawn and a second identical modal, which is exactly the first-run experience of anyone who
   * has no `mlview` core installed.
   */
  private lastFailure:
    | { key: string; requestId: string; message: string; detail: string; actions: CoreAction[] }
    | undefined;
  private pendingRestore: unknown;
  /**
   * The `focusFile` whose `file:` scope has already been posted for the current command, so a
   * save-triggered re-analysis does not snap the diagram back over a scope the user has since
   * changed by hand. Cleared whenever a visualize command sets a new scope.
   */
  private appliedFocus: string | undefined;
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
      () => this.graph,
      () => readSettings().codeLens
    );
    this.disposables.push(this.statusBar, this.codeLens);
    this.updateStatusBar();
  }

  // ---------------------------------------------------------------- registration

  registerUnconditional(): void {
    const ctx = this.ctx;
    const cmd = vscode.commands.registerCommand;

    ctx.subscriptions.push(
      this,
      cmd('mlview.visualize', () => this.visualizeActiveFile()),
      cmd('mlview.visualizeWorkspace', () => this.visualizeWorkspace()),
      cmd('mlview.refresh', () => this.refresh()),
      cmd('mlview.showIssues', () => showIssues(this)),
      cmd('mlview.revealInDiagram', (args?: RevealArgs) => this.reveal(args)),
      cmd('mlview.scopeToSymbol', () => scopeToSymbol(this.diagramDeps())),
      cmd('mlview.clearScope', () => clearScope(this.diagramDeps())),
      cmd('mlview.exportHtml', () => exportHtml(this)),
      // VIEW-07 (11.33): the host cannot draw, so these ASK the open panel for the bytes.
      cmd('mlview.exportSvg', (s?: ExportScope) => requestDiagramExport('svg', this.exportDeps(), s)),
      cmd('mlview.exportPng', (s?: ExportScope) => requestDiagramExport('png', this.exportDeps(), s)),
      cmd('mlview.selectInterpreter', () => this.env.selectInterpreter()),
      cmd('mlview.showOutput', () => this.log.show(false)),
      cmd('mlview.showRuleDoc', (code?: string) => showRuleDoc(this, code)),
      vscode.languages.registerCodeLensProvider({ language: 'python' }, this.codeLens),
      // MLV-P10: the lightbulb and its three commands. Unconditional, like every other
      // editor surface - a code action provider has no API to feature-detect.
      ...registerSuppressionActions(this.log),
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
      showDiagram: (focusNodeId?: string) => this.showDiagram(focusNodeId)
    });
  }

  // ---------------------------------------------------------------- commands

  /**
   * `MLView: Visualize (Current File)`.
   *
   * COVERAGE: analysing the file ALONE loses the cross-file rules silently — 3 findings where
   * its directory yields 7. `mlview.currentFileAnalysisScope` defaults to `package`, so the
   * command analyses the package directory around the file and then narrows the diagram to the
   * file through the §11.7 `setScope` path. The picture is the same; the findings are not.
   */
  private async visualizeActiveFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      await this.visualizeWorkspace();
      return;
    }
    const file = editor.document.uri.fsPath;
    this.appliedFocus = undefined;
    const folder = vscode.workspace.getWorkspaceFolder(editor.document.uri);
    const mode = readSettings(editor.document.uri).currentFileAnalysisScope;
    const target = resolveCurrentFileTarget(
      file,
      folder?.uri.fsPath ?? path.dirname(file),
      mode,
      (candidate) => fs.existsSync(candidate)
    );
    this.lastScope = {
      scope: target.scope,
      ...(target.path ? { path: target.path } : {}),
      ...(target.focusFile ? { focusFile: target.focusFile } : {})
    };
    this.log.info(
      `visualize current file (${mode}): analyzing ${target.path ?? 'the workspace'}` +
        (target.focusFile ? `, diagram scoped to ${path.basename(target.focusFile)}` : '')
    );
    await this.ensurePanel();
    await this.analyzeScopeOnce(this.lastScope);
  }

  private async visualizeWorkspace(): Promise<void> {
    this.lastScope = { scope: 'workspace' };
    this.appliedFocus = undefined;
    await this.ensurePanel();
    // `Once`, not a fresh run: `ensurePanel` yields, so a command issued in the same tick (or
    // the panel's own `ready`) must join this analysis instead of superseding it.
    await this.analyzeScopeOnce(this.lastScope);
  }

  /** `MLView: Re-analyze` — the user explicitly asked for fresh results, so never join. */
  private async refresh(): Promise<void> {
    this.env.invalidate();
    await this.analyzeScope(this.lastScope);
  }

  /**
   * The members `RevealDeps` (Alt+M) and `ScopeDeps` (Alt+Shift+M, §11.11) need. `getPanel`
   * is the read-only twin of `ensurePanel`: it answers with the live panel and never opens
   * one, so `clearScope` can stay a no-op in a window with no diagram.
   */
  private diagramDeps(): ScopeDeps {
    return {
      log: this.log,
      getGraph: () => this.graph,
      getIndex: () => this.index,
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

  // ---------------------------------------------------------------- analysis

  private pathsFor(scope: Scope, root: string): string[] {
    return scope.scope === 'file' && scope.path ? [scope.path] : [root];
  }

  // --- CommandHost -------------------------------------------------------------

  currentPaths(root: string): string[] {
    return this.pathsFor(this.lastScope, root);
  }

  currentScope(): AnalysisScope {
    return this.lastScope.scope;
  }

  getGraph(): MLGraph | undefined {
    return this.graph;
  }

  async ensureGraph(): Promise<MLGraph | undefined> {
    await this.analyzeScopeOnce(this.lastScope);
    return this.graph;
  }

  private workspaceFolderFor(scope: Scope): vscode.WorkspaceFolder | undefined {
    if (scope.scope === 'file' && scope.path) {
      const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(scope.path));
      if (folder) {
        return folder;
      }
    }
    return vscode.workspace.workspaceFolders?.[0];
  }

  workspaceRoot(): string | undefined {
    if (this.graph?.workspace.root) {
      return this.graph.workspace.root;
    }
    return this.workspaceFolderFor(this.lastScope)?.uri.fsPath;
  }

  /**
   * Start (or supersede) an analysis of this scope. The returned promise never rejects: every
   * failure is already reported to the panel, the status bar and the output channel.
   */
  private analyzeScope(scope: Scope): Promise<void> {
    const key = scopeKey(scope.scope, scope.path);
    const promise = this.runAnalysis(scope).finally(() => {
      if (this.inFlight.get(key) === promise) {
        this.inFlight.delete(key);
      }
    });
    this.inFlight.set(key, promise);
    return promise;
  }

  /**
   * Join the run already in flight for this scope instead of starting a duplicate. Opening the
   * diagram is `ensurePanel()` + `analyzeScope()`, and the webview's `ready` then arrives while
   * that first run is still going: without this, `onReady` would start a second analyzer, the
   * single-flight in CoreClient would kill the first, and one whole process would be spawned and
   * killed on every first open.
   */
  private analyzeScopeOnce(scope: Scope): Promise<void> {
    const running = this.inFlight.get(scopeKey(scope.scope, scope.path));
    if (running) {
      this.log.debug('joining the analysis already in flight for this scope');
      return running;
    }
    return this.analyzeScope(scope);
  }

  private async runAnalysis(scope: Scope): Promise<void> {
    const folder = this.workspaceFolderFor(scope);
    if (!folder) {
      void vscode.window.showWarningMessage('MLView: open a folder or a Python file first.');
      return;
    }
    if (!ensureTrusted(this.log)) {
      return;
    }
    const key = scopeKey(scope.scope, scope.path);
    if (this.lastFailure?.key === key) {
      // This scope is being attempted again; the remembered banner is about to be replaced.
      this.lastFailure = undefined;
    }
    const requestId = nextRequestId('analyze');
    const settings = readSettings(folder.uri);
    const root = folder.uri.fsPath;
    this.busyRuns += 1;
    this.failed = false;
    this.updateStatusBar();
    MlviewPanel.current?.postAnalysisStarted(
      requestId,
      scope.scope,
      scope.path ? toWorkspaceRelative(root, scope.path) : undefined
    );
    // H3: `--progress-json` is passed EXACTLY when there is a panel to draw the bar,
    // so the headless paths (`mlview.showIssues`, the chat digests, the LM tools)
    // spawn the analyzer with the argv they have always spawned it with.
    const progressPanel = MlviewPanel.current;
    try {
      const result = await this.core.analyze({
        scope: scope.scope,
        paths: this.pathsFor(scope, root),
        cwd: root,
        settings,
        ...(progressPanel && !progressPanel.isDisposed
          ? { onProgress: progressPanel.progressListener(requestId) }
          : {})
      });
      this.applyGraph(result.graph, requestId, settings);
      this.log.info(
        `analysis finished in ${result.durationMs} ms: ${result.graph.stats.nodes} nodes, ` +
          `${result.graph.stats.edges} edges`
      );
    } catch (err) {
      if (err instanceof CoreError && err.kind === 'cancelled') {
        this.log.info('analysis cancelled');
      } else {
        this.lastFailure = { key, requestId, ...this.reportError(err, requestId) };
      }
    } finally {
      this.busyRuns = Math.max(0, this.busyRuns - 1);
      this.updateStatusBar();
    }
  }

  private applyGraph(graph: MLGraph, requestId: string, settings: MlviewSettings): void {
    this.graph = graph;
    this.lastFailure = undefined;
    this.index = buildLocationIndex(graph);
    this.staleFiles.clear();
    this.diagnostics.publish(graph, settings);
    this.codeLens.refresh();
    this.failed = false;
    this.updateStatusBar();
    const panel = MlviewPanel.current;
    if (panel) {
      panel.postGraph(requestId, graph);
      panel.postSetFilter(allowedRuleCodes(graph, settings.disabledRules));
      this.applyFocusScope(panel, graph);
    }
  }

  /**
   * COVERAGE: the analysis went as wide as `mlview.currentFileAnalysisScope` asked for, so the
   * DIAGRAM is narrowed back to the file the user pointed at — through the same §11.7 message
   * `MLView: Scope Diagram to Symbol` uses, which means no new protocol and no re-analysis.
   * Posted once per command: after that the viewer owns its scope.
   */
  private applyFocusScope(panel: MlviewPanel, graph: MLGraph): void {
    const focus = this.lastScope.focusFile;
    if (!focus || this.appliedFocus === focus) {
      return;
    }
    this.appliedFocus = focus;
    const spec = focusScopeSpec(graph.workspace.root, focus);
    if (spec) {
      panel.postSetScope(spec);
    } else {
      this.log.warn(`focus file ${focus} is outside the analyzed root; leaving the scope alone`);
    }
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

  settingsFor(uri: vscode.Uri): MlviewSettings {
    return readSettings(uri);
  }

  markStale(fsPath: string): void {
    if (recordStale(this.graph?.workspace.root, fsPath, this.staleFiles)) {
      MlviewPanel.current?.postStale(Array.from(this.staleFiles));
    }
  }

  reanalyze(): void {
    this.core.scheduleAnalyze(() => void this.analyzeScope(this.lastScope));
  }

  refreshCodeLens(): void {
    this.codeLens.refresh();
  }

  republish(): void {
    if (!this.graph) {
      return;
    }
    const settings = readSettings();
    this.diagnostics.publish(this.graph, settings);
    MlviewPanel.current?.postSetFilter(allowedRuleCodes(this.graph, settings.disabledRules));
    this.updateStatusBar();
  }

  resetForWorkspaceChange(): void {
    this.graph = undefined;
    this.index = undefined;
    this.lastFailure = undefined;
    this.staleFiles.clear();
    this.diagnostics.clear();
    this.codeLens.refresh();
    this.updateStatusBar();
  }

  private updateStatusBar(): void {
    renderStatusBar(this.statusBar, {
      ...(this.graph ? { graph: this.graph } : {}),
      settings: readSettings(this.workspaceFolderFor(this.lastScope)?.uri),
      busy: this.busyRuns > 0,
      failed: this.failed,
      // PACKAGING: names the installed-vs-bundled core, once the chain has run once.
      ...(this.env.coreDescription() ? { core: this.env.coreDescription()! } : {})
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
    const key = scopeKey(this.lastScope.scope, this.lastScope.path);
    replayForReadyPanel(panel, {
      graph: this.graph,
      pendingRestore: this.pendingRestore,
      disabledRules: readSettings().disabledRules,
      staleFiles: Array.from(this.staleFiles),
      replayableFailure: this.lastFailure?.key === key ? this.lastFailure : undefined,
      analyzeOnce: () => void this.analyzeScopeOnce(this.lastScope),
      themeKind: () => themeKindOf(vscode.window.activeColorTheme.kind)
    });
    this.pendingRestore = undefined;
  }

  onRequestRefresh(scope: AnalysisScope, targetPath?: string): void {
    this.lastScope = resolveRefreshScope(
      scope,
      targetPath,
      this.workspaceRoot(),
      this.lastScope.path
    );
    void this.analyzeScope(this.lastScope);
  }

  /** VIEW-07: the export commands see the LIVE panel only; they never open one. */
  private exportDeps(): { log: Logger; panel(): ExportPanelLike | undefined } {
    return { log: this.log, panel: () => this.livePanel() };
  }

  onExportHtml(): void {
    void exportHtml(this);
  }

  onAction(id: string): void {
    runHostAction(id, {
      log: this.log,
      retry: () => void this.analyzeScope(this.lastScope),
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
    input: { path?: string },
    token?: vscode.CancellationToken
  ): Promise<MLGraph> {
    return analyzeForTools(input, token, {
      log: this.log,
      core: this.core,
      currentGraph: () => this.graph,
      staleCount: () => this.staleFiles.size,
      applyGraph: (graph, requestId, settings) => this.applyGraph(graph, requestId, settings)
    });
  }

  showDiagram(focusNodeId?: string): Promise<void> {
    return this.ensurePanel().then((panel) => {
      if (panel && focusNodeId) {
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
