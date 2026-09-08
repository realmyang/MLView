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

import * as path from 'node:path';
import * as vscode from 'vscode';
import { registerChatSurfaces } from './chatSurfaces';
import { MlviewCodeLensProvider } from './codelens';
import { exportHtml, showIssues, showRuleDoc, type CommandHost } from './commands';
import { CoreClient, CoreError, scopeKey, type CoreAction } from './coreClient';
import { DiagnosticsPublisher } from './diagnostics';
import { countIssues, type IssueCounts, type MLGraph } from './graph';
import { allowedRuleCodes, publishedIssueFilter, selectIssues } from './issues';
import { resolveAnalysisTarget, toWorkspaceRelative } from './location';
import { buildLocationIndex, type LocationIndex } from './locationIndex';
import { createLogger, type Logger } from './log';
import { type CoreLike } from './lmTools';
import { MlviewPanel, themeKindOf, VIEW_TYPE, type PanelDelegate } from './panel';
import { nextRequestId, type AnalysisScope } from './protocol';
import { PythonEnvironment } from './pythonEnv';
import { revealInDiagram, type RevealArgs } from './revealInDiagram';
import { clearScope, scopeToSymbol, type ScopeDeps } from './scopeCommands';
import { readSettings, type MlviewSettings } from './settings';
import { statusBarText, statusBarTooltip } from './statusBar';
import { ensureTrusted, isTrusted, manageTrust, RESTRICTED_MESSAGE } from './trust';

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
      cmd('mlview.selectInterpreter', () => this.env.selectInterpreter()),
      cmd('mlview.showOutput', () => this.log.show(false)),
      cmd('mlview.showRuleDoc', (code?: string) => showRuleDoc(this, code)),
      vscode.languages.registerCodeLensProvider({ language: 'python' }, this.codeLens),
      vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
        deserializeWebviewPanel: async (panel, state: unknown) => {
          this.log.info('restoring the MLView panel from a saved window state');
          this.pendingRestore = state;
          MlviewPanel.revive(panel, this.ctx, this);
        }
      }),
      vscode.workspace.onDidSaveTextDocument((doc) => this.onDocumentSaved(doc)),
      vscode.workspace.onDidChangeTextDocument((e) => this.onDocumentChanged(e.document)),
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.graph = undefined;
        this.index = undefined;
        this.lastFailure = undefined;
        this.staleFiles.clear();
        this.diagnostics.clear();
        this.codeLens.refresh();
        this.updateStatusBar();
      }),
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('mlview.codeLens')) {
          this.codeLens.refresh();
        }
        if (
          this.graph &&
          (e.affectsConfiguration('mlview.minConfidence') ||
            e.affectsConfiguration('mlview.minSeverity') ||
            e.affectsConfiguration('mlview.diagnosticSeverity') ||
            e.affectsConfiguration('mlview.diagnosticsEnabled') ||
            e.affectsConfiguration('mlview.disabledRules'))
        ) {
          const settings = readSettings();
          this.diagnostics.publish(this.graph, settings);
          MlviewPanel.current?.postSetFilter(
            allowedRuleCodes(this.graph, settings.disabledRules)
          );
          this.updateStatusBar();
        }
      })
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

  private async visualizeActiveFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      await this.visualizeWorkspace();
      return;
    }
    this.lastScope = { scope: 'file', path: editor.document.uri.fsPath };
    await this.ensurePanel();
    await this.analyzeScopeOnce(this.lastScope);
  }

  private async visualizeWorkspace(): Promise<void> {
    this.lastScope = { scope: 'workspace' };
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
    try {
      const result = await this.core.analyze({
        scope: scope.scope,
        paths: this.pathsFor(scope, root),
        cwd: root,
        settings
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
    }
  }

  /** Returns what it reported, so a caller can remember the banner for a webview that boots late. */
  reportError(
    err: unknown,
    requestId: string
  ): { message: string; detail: string; actions: CoreAction[] } {
    this.failed = true;
    this.updateStatusBar();
    const coreError = err instanceof CoreError ? err : undefined;
    const message = coreError?.message ?? (err instanceof Error ? err.message : String(err));
    const detail = coreError?.detail ?? '';
    const actions = coreError?.actions ?? [{ id: 'showOutput', label: 'Show Output' }];
    this.log.error(`analysis failed: ${message}${detail ? `\n${detail}` : ''}`);
    MlviewPanel.current?.postAnalysisFailed(requestId, message, detail, actions);
    void vscode.window
      .showErrorMessage(`MLView: ${message}`, ...actions.map((a) => a.label))
      .then((choice) => {
        const action = actions.find((a) => a.label === choice);
        if (action) {
          void this.onAction(action.id);
        }
      });
    return { message, detail, actions };
  }

  private onDocumentSaved(doc: vscode.TextDocument): void {
    if (doc.languageId !== 'python') {
      return;
    }
    this.markStale(doc);
    if (!readSettings(doc.uri).analyzeOnSave) {
      return;
    }
    this.core.scheduleAnalyze(() => void this.analyzeScope(this.lastScope));
  }

  private onDocumentChanged(doc: vscode.TextDocument): void {
    if (doc.languageId === 'python') {
      this.markStale(doc);
    }
  }

  private markStale(doc: vscode.TextDocument): void {
    if (!this.graph) {
      return;
    }
    const relative = toWorkspaceRelative(this.graph.workspace.root, doc.uri.fsPath);
    if (relative.startsWith('..') || this.staleFiles.has(relative)) {
      return;
    }
    this.staleFiles.add(relative);
    MlviewPanel.current?.postStale(Array.from(this.staleFiles));
  }

  private updateStatusBar(): void {
    // The same filter the Problems panel and the quick pick use: the status bar is a click
    // through to that list, so a raw `stats.issues` count (every unsuppressed finding at any
    // confidence) would advertise findings neither surface can show.
    const counts: IssueCounts = this.graph
      ? countIssues(
          selectIssues(
            this.graph,
            publishedIssueFilter(readSettings(this.workspaceFolderFor(this.lastScope)?.uri))
          )
        )
      : { low: 0, medium: 0, high: 0 };
    const busy = this.busyRuns > 0;
    this.statusBar.text = statusBarText(counts, busy, this.failed);
    this.statusBar.tooltip = statusBarTooltip(
      counts,
      busy,
      this.failed,
      this.graph?.workspace.notebooksSkipped ?? 0
    );
    this.statusBar.show();
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
    panel.postInit(themeKindOf(vscode.window.activeColorTheme.kind));
    const restore = this.pendingRestore ?? panel.savedState();
    if (restore && typeof restore === 'object') {
      panel.postRestoreState(restore as Record<string, unknown>);
    }
    this.pendingRestore = undefined;
    if (this.graph) {
      panel.postGraph(nextRequestId('restore'), this.graph);
      panel.postSetFilter(allowedRuleCodes(this.graph, readSettings().disabledRules));
      if (this.staleFiles.size > 0) {
        panel.postStale(Array.from(this.staleFiles));
      }
    } else if (this.lastFailure?.key === scopeKey(this.lastScope.scope, this.lastScope.path)) {
      // The run that opened this panel already failed, and a settled run is no longer in
      // `inFlight` for `analyzeScopeOnce` to join. Replay its banner instead of re-running the
      // whole failing chain and showing the user a second identical notification.
      const failure = this.lastFailure;
      panel.postAnalysisFailed(
        failure.requestId,
        failure.message,
        failure.detail,
        failure.actions
      );
    } else {
      // Join the run that opened this panel rather than spawning a second analyzer for it.
      void this.analyzeScopeOnce(this.lastScope);
    }
  }

  onRequestRefresh(scope: AnalysisScope, targetPath?: string): void {
    const root = this.workspaceRoot();
    const absolute =
      targetPath && root ? path.resolve(root, targetPath) : this.lastScope.path;
    this.lastScope =
      scope === 'file' && absolute ? { scope: 'file', path: absolute } : { scope: 'workspace' };
    void this.analyzeScope(this.lastScope);
  }

  onExportHtml(): void {
    void exportHtml(this);
  }

  onAction(id: string): void {
    switch (id) {
      case 'retry':
        void this.analyzeScope(this.lastScope);
        return;
      case 'showOutput':
        this.log.show(false);
        return;
      case 'selectInterpreter':
      case 'installCore':
        void this.env.runAction(id);
        return;
      case 'manageTrust':
        manageTrust();
        return;
      default:
        this.log.warn(`unknown webview action: ${id}`);
    }
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
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      throw new CoreError('usage', 'No folder is open, so there is nothing to analyze.');
    }
    if (!isTrusted()) {
      throw new CoreError('restricted', RESTRICTED_MESSAGE);
    }
    const root = folder.uri.fsPath;
    if (!input.path && this.graph && this.staleFiles.size === 0) {
      return this.graph;
    }
    // SECURITY: `input.path` is MODEL-supplied. Refuse anything outside the open workspace
    // before it reaches the analyzer (CONTRACTS.md §4's openLocation guard, same reasoning).
    const resolved = resolveAnalysisTarget(root, input.path, {
      isInWorkspace: (fsPath) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath))
    });
    if (!resolved.ok) {
      this.log.warn(`refused out-of-workspace analyze: ${resolved.fsPath || String(input.path)}`);
      throw new CoreError(
        'usage',
        'MLView only analyzes paths inside the open workspace.',
        `Refused ${String(input.path)}`
      );
    }
    const target = resolved.fsPath;
    const scope: Scope = input.path ? { scope: 'file', path: target } : { scope: 'workspace' };
    const settings = readSettings(folder.uri);
    const result = await this.core.analyze({
      scope: scope.scope,
      paths: [target],
      cwd: root,
      settings,
      ...(token ? { token } : {})
    });
    if (!input.path) {
      this.applyGraph(result.graph, nextRequestId('tool'), settings);
    }
    return result.graph;
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
