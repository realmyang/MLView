/**
 * The diagram webview panel (CONTRACTS.md §4 + amendments A5, A13).
 *
 * The panel renders; it never analyses. It owns the frozen webview creation options, the nonce
 * CSP, the host side of the message protocol, and the disposal guard on every postMessage.
 *
 * `retainContextWhenHidden` is deliberately NOT set: state lives in the webview's own
 * getState/setState plus a WebviewPanelSerializer registered for 'mlview.diagram'.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { chatAvailable, openAssistantChat } from './chatSurfaces';
import type { SuppressRequest } from './codeActions';
import { coverageChip, coverageNotes } from './coverage';
import { saveExportedFile } from './exportDiagram';
import type { MLGraph } from './graph';
import { SCHEMA_VERSION } from './graph';
import { resolveOpenTarget, toRangeTuple } from './location';
import type { Logger } from './log';
import { DeferredMessages, preserveFromState, type PreserveState } from './panelState';
import { buildPanelHtml, createNonce, type PanelHtmlOptions } from './panelHtml';
import {
  activeScopeFrom,
  PANEL_TITLE,
  scopeChrome,
  type ActiveScope,
  type ScopeChrome
} from './panelScope';
import {
  parseUiToHost,
  type AnalysisScope,
  type ExportKind,
  type ExportScope,
  type HostToUi,
  type ScopeChangedMessage,
  type ThemeKind,
  type UiToHost,
  type ViewState
} from './protocol';

// Re-exported so `./panel` keeps the exact public surface it had before the scope helpers
// (src/panelScope.ts) and the webview document (src/panelHtml.ts) moved out - every importer,
// and test/scope.test.js, is unchanged.
export { activeScopeFrom, PANEL_TITLE, scopeChrome };
export type { ActiveScope, ScopeChrome };
export { buildPanelHtml, createNonce };
export type { PanelHtmlOptions };

export const VIEW_TYPE = 'mlview.diagram';
export const VIEW_STATE_KEY = 'mlview.viewState';

export function themeKindOf(kind: vscode.ColorThemeKind): ThemeKind {
  switch (kind) {
    case vscode.ColorThemeKind.Light:
    case vscode.ColorThemeKind.HighContrastLight:
      return kind === vscode.ColorThemeKind.HighContrastLight ? 'hc' : 'light';
    case vscode.ColorThemeKind.HighContrast:
      return 'hc';
    default:
      return 'dark';
  }
}

/** Everything the panel needs from the extension host, kept behind an interface for testability. */
export interface PanelDelegate {
  readonly log: Logger;
  /** Called once the webview says `ready`; the host answers with init + a graph. */
  onReady(panel: MlviewPanel): void;
  onRequestRefresh(scope: AnalysisScope, path?: string): void;
  onExportHtml(): void;
  onAction(id: string): void;
  onSelectNode(nodeId: string | null): void;
  /**
   * MLV-P10: the viewer asked to suppress a rule. The host answers with exactly the
   * behaviour the editor lightbulb has — confirm dialog, containment check and all —
   * so the two surfaces cannot drift apart.
   */
  onSuppressRule(request: SuppressRequest): void;
  /** Absolute root the graph's relative paths resolve against. */
  workspaceRoot(): string | undefined;
}

export class MlviewPanel implements vscode.Disposable {
  static current: MlviewPanel | undefined;

  private disposed = false;
  /** Holds back what the webview cannot act on yet; see src/panelState.ts. */
  private readonly deferred = new DeferredMessages();
  /**
   * H3: request ids whose analysis has already been reported as failed, so a late
   * `analysisProgress` frame from the same child is dropped instead of drawing a bar
   * over the banner. Bounded — this is a guard, not a history.
   */
  private readonly failedRequests = new Set<string>();
  /** The webview's latest `saveState`, used as the `preserve` of the next `graph`. */
  private lastViewState: ViewState | undefined;
  /** The selector from the last `scopeChanged`; `null` while the diagram is unscoped. */
  private scopeSpec: string | null = null;
  /** The last `scopeChanged` chrome, so a new graph can redraw the description without one. */
  private lastScopeChrome: ScopeChrome | undefined;
  /** COVERAGE: "coverage: incomplete (N blind spots)", or undefined when the run saw everything. */
  private coverageChipText: string | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly decoration: vscode.TextEditorDecorationType;

  private constructor(
    readonly panel: vscode.WebviewPanel,
    private readonly ctx: vscode.ExtensionContext,
    private readonly delegate: PanelDelegate
  ) {
    this.decoration = vscode.window.createTextEditorDecorationType({
      backgroundColor: new vscode.ThemeColor('editor.findMatchHighlightBackground')
    });
    this.render();

    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage(
      (raw: unknown) => void this.handleMessage(raw),
      null,
      this.disposables
    );
    this.disposables.push(
      vscode.window.onDidChangeActiveColorTheme((theme) =>
        this.post({ v: 1, type: 'theme', kind: themeKindOf(theme.kind) })
      )
    );
  }

  static createOrShow(ctx: vscode.ExtensionContext, delegate: PanelDelegate): MlviewPanel {
    if (MlviewPanel.current && !MlviewPanel.current.disposed) {
      MlviewPanel.current.panel.reveal(vscode.ViewColumn.Beside, true);
      return MlviewPanel.current;
    }
    const panel = vscode.window.createWebviewPanel(
      VIEW_TYPE,
      PANEL_TITLE,
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, 'media')]
        // NOTE: retainContextWhenHidden is deliberately NOT set.
      }
    );
    MlviewPanel.current = new MlviewPanel(panel, ctx, delegate);
    return MlviewPanel.current;
  }

  /** Used by the WebviewPanelSerializer when a window reload restores the panel. */
  static revive(
    panel: vscode.WebviewPanel,
    ctx: vscode.ExtensionContext,
    delegate: PanelDelegate
  ): MlviewPanel {
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, 'media')]
    };
    MlviewPanel.current?.dispose();
    MlviewPanel.current = new MlviewPanel(panel, ctx, delegate);
    return MlviewPanel.current;
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  private mediaUri(file: string): { uri: string; exists: boolean } {
    const onDisk = vscode.Uri.joinPath(this.ctx.extensionUri, 'media', file);
    let exists = false;
    try {
      exists = fs.existsSync(path.join(this.ctx.extensionPath, 'media', file));
    } catch {
      exists = false;
    }
    return { uri: this.panel.webview.asWebviewUri(onDisk).toString(), exists };
  }

  private render(): void {
    const script = this.mediaUri('mlview.js');
    const style = this.mediaUri('mlview.css');
    const bundlePresent = script.exists;
    if (!bundlePresent) {
      this.delegate.log.warn(
        'media/mlview.js is missing - showing the "viewer bundle not built" panel (A13)'
      );
    }
    this.panel.webview.html = buildPanelHtml({
      cspSource: this.panel.webview.cspSource,
      nonce: createNonce(),
      scriptUri: script.uri,
      styleUri: style.uri,
      bundlePresent
    });
  }

  /**
   * Every outbound message goes through here, guarded against a disposed panel and against the
   * pre-handshake window: a `revealNode` posted before the webview booted (Alt+M with the panel
   * closed) is queued and flushed after the graph, instead of being dropped on the floor.
   */
  post(message: HostToUi): void {
    if (this.disposed) {
      return;
    }
    if (message.type === 'analysisFailed') {
      // BEFORE the deferral check, not after it: a failure that is itself queued (the run ended
      // while the webview was still booting) must still cancel its own queued spinner, and must
      // replace an earlier queued banner for the same run rather than being delivered twice.
      this.deferred.drop('analysisStarted', message.requestId);
      this.deferred.drop('analysisFailed', message.requestId);
    }
    if (this.deferred.shouldDefer(message.type)) {
      this.deferred.add(message);
      this.delegate.log.trace(`host -> ui: ${message.type} held until the webview is ready`);
      return;
    }
    this.send(message);
    if (message.type === 'graph') {
      // The run this graph belongs to is over: a queued spinner for it would never clear.
      this.deferred.drop('analysisStarted', message.requestId);
      this.deferred.onGraphDelivered();
      this.flushDeferred();
    }
  }

  private send(message: HostToUi): void {
    try {
      void this.panel.webview.postMessage(message);
      this.delegate.log.trace(`host -> ui: ${message.type}`);
    } catch (err) {
      this.delegate.log.warn(`postMessage(${message.type}) failed: ${String(err)}`);
    }
  }

  /** Send everything the webview can now act on, in the order it was posted. */
  private flushDeferred(): void {
    for (const message of this.deferred.take()) {
      this.send(message);
    }
  }

  postInit(theme: ThemeKind): void {
    this.post({
      v: 1,
      type: 'init',
      schemaVersion: SCHEMA_VERSION,
      theme,
      host: 'vscode',
      capabilities: {
        canOpenSource: true,
        canReanalyze: true,
        canExport: true,
        // CLEANUP 5: the diagram -> chat path was fully wired on both sides and dropped on the
        // floor here. It is offered exactly when the chat API this build would open is present,
        // so a VS Code without `vscode.chat` still hides the button instead of showing a dead one.
        canAskAssistant: chatAvailable()
      }
    });
  }

  /**
   * CONTRACTS.md §4: `preserve` is what stops a re-analysis (every Ctrl+S with
   * `mlview.analyzeOnSave`) and every window reload from throwing away the user's viewport —
   * without it `App.setGraph` calls `fit()` on every graph. The state comes from the webview's
   * own `saveState`, falling back to the serialized workspace state after a reload; only a panel
   * that has never reported a position gets the initial fit.
   */
  postGraph(requestId: string, graph: MLGraph, preserve?: PreserveState): void {
    // COVERAGE: the caveat rides the panel chrome as well as the viewer's own diagnostics,
    // because the tab strip is visible when the canvas is scrolled away from the banner.
    this.coverageChipText = coverageChip(coverageNotes(graph));
    this.refreshDescription();
    const carried = preserve ?? this.preserve();
    this.post({
      v: 1,
      type: 'graph',
      requestId,
      graph,
      ...(carried ? { preserve: carried } : {})
    });
  }

  private preserve(): PreserveState | undefined {
    return preserveFromState(this.lastViewState ?? this.savedState());
  }

  postAnalysisStarted(requestId: string, scope: AnalysisScope, targetPath?: string): void {
    this.post({
      v: 1,
      type: 'analysisStarted',
      requestId,
      scope,
      ...(targetPath ? { path: targetPath } : {})
    });
  }

  /**
   * H3. One frame per file, throttled by the analyzer, drawn by the viewer's existing
   * `done/total` bar (`webview/src/ui/states.ts`).
   *
   * A frame that arrives AFTER this run already failed is dropped: the child's stderr
   * and its exit are two separate events, so a queued chunk can land after the banner
   * is up, and a progress bar reappearing over an error message is the one thing worse
   * than no progress bar at all.
   */
  postAnalysisProgress(requestId: string, done: number, total: number, file?: string): void {
    if (this.failedRequests.has(requestId)) {
      return;
    }
    this.post({
      v: 1,
      type: 'analysisProgress',
      requestId,
      done,
      total,
      ...(file ? { file } : {})
    });
  }

  /**
   * A listener the analyzer's stderr frames can be piped straight into, bound to one
   * `requestId`. Handed to `CoreClient.analyze` so the controller never has to hold a
   * reference to a panel that may be disposed by the time a frame arrives.
   */
  progressListener(requestId: string): (frame: { done: number; total: number; file?: string }) => void {
    return (frame) => {
      MlviewPanel.current?.postAnalysisProgress(requestId, frame.done, frame.total, frame.file);
    };
  }

  postAnalysisFailed(
    requestId: string,
    message: string,
    detail?: string,
    actions?: { id: string; label: string }[]
  ): void {
    this.rememberFailure(requestId);
    this.post({
      v: 1,
      type: 'analysisFailed',
      requestId,
      message,
      ...(detail ? { detail } : {}),
      ...(actions && actions.length ? { actions } : {})
    });
  }

  /** Newest 16 failed request ids; older ones can no longer have a child alive. */
  private rememberFailure(requestId: string): void {
    this.failedRequests.add(requestId);
    while (this.failedRequests.size > 16) {
      const oldest = this.failedRequests.values().next().value;
      if (oldest === undefined) {
        break;
      }
      this.failedRequests.delete(oldest);
    }
  }

  postStale(changedFiles: string[]): void {
    this.post({ v: 1, type: 'stale', changedFiles });
  }

  postRevealNode(nodeId: string, approximate = false): void {
    this.post({ v: 1, type: 'revealNode', nodeId, center: true, approximate });
  }

  postRevealIssue(issueId: string): void {
    this.post({ v: 1, type: 'revealIssue', issueId });
  }

  /**
   * `mlview.disabledRules` reaching the canvas. The viewer's `setCodes` is a KEEP-list, so the
   * caller sends the codes that survive the setting (see `allowedRuleCodes` in extension.ts);
   * an empty list is the viewer's "no restriction".
   */
  postSetFilter(codes: string[]): void {
    this.post({ v: 1, type: 'setFilter', codes });
  }

  /**
   * CONTRACTS.md §11.7/§11.11. The viewer holds the full document and re-projects locally, so a
   * scope change never re-analyses anything; this is the whole host side of setting one.
   */
  postSetScope(spec: string | null, depth?: number): void {
    this.post({
      v: 1,
      type: 'setScope',
      spec,
      ...(typeof depth === 'number' ? { depth } : {})
    });
  }

  /**
   * VIEW-07 (docs/contracts/11.33-diagram-export.md). "Render this and send me the bytes."
   * Deferred like a reveal: a request reaching a webview with no graph draws nothing.
   */
  postRequestExport(kind: ExportKind, scope: ExportScope): void {
    this.post({ v: 1, type: 'requestExport', kind, scope });
  }

  postRestoreState(state: ViewState): void {
    this.post({ v: 1, type: 'restoreState', state });
  }

  postTheme(kind: ThemeKind): void {
    this.post({ v: 1, type: 'theme', kind });
  }

  private async handleMessage(raw: unknown): Promise<void> {
    const parsed = parseUiToHost(raw);
    if (!parsed.ok) {
      // Version skew must degrade, not crash.
      this.delegate.log.warn(`ignored webview message (${parsed.reason}: ${parsed.detail})`);
      return;
    }
    const msg: UiToHost = parsed.msg;
    this.delegate.log.trace(`ui -> host: ${msg.type}`);
    switch (msg.type) {
      case 'ready':
        // A reload remounts the viewer, so the graph gate closes again until the host re-sends.
        this.deferred.onReady();
        this.delegate.onReady(this);
        this.flushDeferred();
        return;
      case 'openLocation':
        await this.openLocation(msg);
        return;
      case 'selectNode':
        this.delegate.onSelectNode(msg.nodeId);
        return;
      case 'requestRefresh':
        this.delegate.onRequestRefresh(msg.scope, msg.path);
        return;
      case 'exportHtml':
        this.delegate.onExportHtml();
        return;
      case 'copy':
        await vscode.env.clipboard.writeText(msg.text);
        void vscode.window.setStatusBarMessage(`MLView: copied ${msg.text}`, 3000);
        return;
      case 'saveState':
        this.lastViewState = msg.state;
        await this.ctx.workspaceState.update(VIEW_STATE_KEY, msg.state);
        return;
      case 'action':
        this.delegate.onAction(msg.id);
        return;
      case 'askAssistant':
        await openAssistantChat(msg.nodeId, msg.prompt, this.delegate.log);
        return;
      case 'log':
        this.delegate.log.info(`[webview] ${msg.level}: ${msg.message}`);
        return;
      case 'exportFile':
        // VIEW-07: the save dialog and the write live in src/exportDiagram.ts.
        await saveExportedFile(msg, {
          log: this.delegate.log,
          workspaceRoot: () => this.delegate.workspaceRoot()
        });
        return;
      case 'suppressRule':
        this.delegate.onSuppressRule({
          code: msg.code,
          action: msg.action,
          ...(msg.absFile ? { absFile: msg.absFile } : {}),
          ...(typeof msg.line === 'number' ? { line: msg.line } : {})
        });
        return;
      case 'scopeChanged':
        this.onScopeChanged(msg);
        return;
      default:
        return;
    }
  }

  /**
   * The panel title and description follow the scope, and NOTHING else does: a scope never
   * re-analyses, never touches the Problems panel and never changes the status-bar count
   * (CONTRACTS.md §11.11, F2-A11).
   */
  private onScopeChanged(msg: ScopeChangedMessage): void {
    // Remembered so `MLView: Export HTML Report` writes the diagram the user is looking at
    // instead of silently falling back to the whole workspace.
    this.scopeSpec = msg.spec;
    const chrome = scopeChrome(msg);
    this.lastScopeChrome = chrome;
    this.panel.title = chrome.title;
    this.refreshDescription();
    this.delegate.log.info(
      `scope ${msg.spec ?? '(cleared)'}: ${msg.nodes} of ${msg.of} nodes`
    );
  }

  /**
   * `<drawn> of <analyzed> nodes · coverage: incomplete (N blind spots)`.
   *
   * `description` is declared on `WebviewView`, not on `WebviewPanel` (@types/vscode 1.100.0),
   * so the contractual assignment goes through a narrow cast: VS Code ignores the extra
   * property today and would pick it up unchanged if the API ever grows it. The same count is
   * drawn by the viewer's own scope breadcrumb, so nothing is lost meanwhile.
   */
  private refreshDescription(): void {
    const parts = [this.lastScopeChrome?.description, this.coverageChipText].filter(
      (part): part is string => typeof part === 'string' && part.length > 0
    );
    if (parts.length === 0) {
      return;
    }
    (this.panel as vscode.WebviewPanel & { description?: string }).description = parts.join(' · ');
  }

  /**
   * The scope the diagram is currently drawing, or undefined when it is showing everything.
   * Read by the HTML export so "what you see" and "what you export" agree.
   */
  get activeScope(): ActiveScope | undefined {
    return activeScopeFrom(this.scopeSpec, this.lastViewState ?? this.savedState());
  }

  savedState(): ViewState | undefined {
    return this.ctx.workspaceState.get<ViewState>(VIEW_STATE_KEY);
  }

  private async openLocation(
    msg: Extract<UiToHost, { type: 'openLocation' }>
  ): Promise<void> {
    const root = this.delegate.workspaceRoot();
    const target = resolveOpenTarget(msg, {
      workspaceRoot: root,
      isInWorkspace: (fsPath) => !!vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath))
    });
    if (!target.ok) {
      // SECURITY: never open a path the webview talked us into that is outside the workspace.
      this.delegate.log.warn(`refused ${target.reason} open: ${target.fsPath}`);
      return;
    }
    try {
      const uri = vscode.Uri.file(target.fsPath);
      const doc = await vscode.workspace.openTextDocument(uri);
      // THE ONE AND ONLY boundary conversion happened in toRangeTuple.
      const t = toRangeTuple(msg);
      const selection = new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
      const editor = await vscode.window.showTextDocument(doc, {
        viewColumn: vscode.ViewColumn.One,
        selection,
        preview: target.preview
      });
      editor.revealRange(selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
      editor.setDecorations(this.decoration, [selection]);
      setTimeout(() => {
        try {
          editor.setDecorations(this.decoration, []);
        } catch {
          /* the editor may be gone */
        }
      }, 1200);
    } catch (err) {
      this.delegate.log.error(`could not open ${target.fsPath}`, err);
    }
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    if (MlviewPanel.current === this) {
      MlviewPanel.current = undefined;
    }
    this.decoration.dispose();
    for (const d of this.disposables) {
      try {
        d.dispose();
      } catch {
        /* ignore */
      }
    }
    try {
      this.panel.dispose();
    } catch {
      /* already disposed by VS Code */
    }
  }
}

/** Convenience for the range conversion used outside the panel (reveal, chat anchors). */
export function rangeFromLoc(loc: {
  line: number;
  col: number;
  endLine: number;
  endCol: number;
}): vscode.Range {
  const t = toRangeTuple(loc);
  return new vscode.Range(t.startLine, t.startChar, t.endLine, t.endChar);
}
