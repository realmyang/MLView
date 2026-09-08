/**
 * The diagram webview panel (CONTRACTS.md §4 + amendments A5, A13).
 *
 * The panel renders; it never analyses. It owns the frozen webview creation options, the nonce
 * CSP, the host side of the message protocol, and the disposal guard on every postMessage.
 *
 * `retainContextWhenHidden` is deliberately NOT set: state lives in the webview's own
 * getState/setState plus a WebviewPanelSerializer registered for 'mlview.diagram'.
 */

import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { MLGraph } from './graph';
import { SCHEMA_VERSION } from './graph';
import { resolveOpenTarget, toRangeTuple } from './location';
import type { Logger } from './log';
import { DeferredMessages, preserveFromState, type PreserveState } from './panelState';
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
  type HostToUi,
  type ScopeChangedMessage,
  type ThemeKind,
  type UiToHost,
  type ViewState
} from './protocol';

// Re-exported so `./panel` keeps the exact public surface it had before the scope helpers
// moved out (src/panelScope.ts) - every importer, and test/scope.test.js, is unchanged.
export { activeScopeFrom, PANEL_TITLE, scopeChrome };
export type { ActiveScope, ScopeChrome };

export const VIEW_TYPE = 'mlview.diagram';
export const VIEW_STATE_KEY = 'mlview.viewState';

export interface PanelHtmlOptions {
  cspSource: string;
  nonce: string;
  scriptUri: string;
  styleUri: string;
  /** False before `tools/sync-assets.py` has run — A13 requires a message, not a throw. */
  bundlePresent: boolean;
}

export function createNonce(): string {
  return randomBytes(24).toString('base64');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * The frozen webview document. `'unsafe-inline'` is granted for STYLES ONLY (nodes carry
 * positional styles); scripts are nonce-locked and `default-src 'none'` is the CSP-level
 * enforcement of the offline requirement.
 */
export function buildPanelHtml(opts: PanelHtmlOptions): string {
  const csp =
    `default-src 'none'; ` +
    `img-src ${opts.cspSource} data:; ` +
    `style-src ${opts.cspSource} 'unsafe-inline'; ` +
    `font-src ${opts.cspSource}; ` +
    `script-src 'nonce-${opts.nonce}';`;

  const head =
    `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1.0">` +
    `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<title>${PANEL_TITLE}</title>` +
    `<link rel="stylesheet" href="${escapeHtml(opts.styleUri)}">`;

  if (!opts.bundlePresent) {
    // A13: tolerate a missing bundle with a designed message instead of a blank, broken panel.
    return (
      head +
      `<style nonce="${opts.nonce}">
        body { font-family: var(--vscode-font-family, sans-serif); padding: 2.5rem; line-height: 1.55; }
        code { background: rgba(127,127,127,0.16); padding: 0.1rem 0.35rem; border-radius: 3px; }
        .hint { opacity: 0.8; max-width: 46rem; }
      </style></head><body><div id="mlview-root">
        <h2>MLView viewer bundle not built</h2>
        <p class="hint">The diagram renderer has not been synced into this extension yet, so there is
        nothing to draw. Build the viewer and sync the assets:</p>
        <p><code>powershell -ExecutionPolicy Bypass -File scripts/build.ps1</code></p>
        <p class="hint">That writes <code>webview/dist/mlview.js</code> and <code>mlview.css</code> into
        <code>vscode-extension/media/</code>. Analysis, the Problems panel and
        <em>Reveal in Diagram</em> keep working without it.</p>
      </div>
      <!-- referenced so the resource roots and the sync target stay visible: ${escapeHtml(
        opts.scriptUri
      )} -->
      </body></html>`
    );
  }

  return (
    head +
    `</head><body><div id="mlview-root"></div>` +
    `<script nonce="${opts.nonce}" src="${escapeHtml(opts.scriptUri)}"></script>` +
    `<script nonce="${opts.nonce}">
(function () {
  var root = document.getElementById('mlview-root');
  if (!window.MLView || typeof window.MLView.mount !== 'function') {
    var box = document.createElement('p');
    box.textContent = 'MLView viewer bundle failed to load. Run scripts/build.ps1 and reopen the panel.';
    root.appendChild(box);
    return;
  }
  var bridge = window.MLView.bridges.vscode();
  // The viewer posts 'ready' from its own constructor; wrap post so we never send it twice.
  var readyPosted = false;
  var post = bridge.post.bind(bridge);
  bridge.post = function (msg) {
    if (msg && msg.type === 'ready') { readyPosted = true; }
    post(msg);
  };
  var app = null;
  try {
    // Mount immediately with no graph: the viewer owns the loading, empty and hard-error states,
    // so an interpreter failure shows a designed banner instead of a blank panel.
    app = window.MLView.mount(root, null, bridge);
  } catch (e) {
    // A viewer that requires a graph at mount time: mount on the first 'graph' message instead,
    // and keep the subscription so every later graph updates in place.
    bridge.onMessage(function (msg) {
      if (!msg || msg.type !== 'graph') { return; }
      if (app) { app.update(msg.graph, msg.preserve); return; }
      app = window.MLView.mount(root, msg.graph, bridge);
    });
  }
  if (!readyPosted) { bridge.post({ v: 1, type: 'ready' }); }
}());
</script></body></html>`
  );
}

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
  /** Absolute root the graph's relative paths resolve against. */
  workspaceRoot(): string | undefined;
}

export class MlviewPanel implements vscode.Disposable {
  static current: MlviewPanel | undefined;

  private disposed = false;
  /** Holds back what the webview cannot act on yet; see src/panelState.ts. */
  private readonly deferred = new DeferredMessages();
  /** The webview's latest `saveState`, used as the `preserve` of the next `graph`. */
  private lastViewState: ViewState | undefined;
  /** The selector from the last `scopeChanged`; `null` while the diagram is unscoped. */
  private scopeSpec: string | null = null;
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
        // A3: askAssistant is posted by the bridge but ignored by both hosts in the prototype.
        canAskAssistant: false
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

  postAnalysisFailed(
    requestId: string,
    message: string,
    detail?: string,
    actions?: { id: string; label: string }[]
  ): void {
    this.post({
      v: 1,
      type: 'analysisFailed',
      requestId,
      message,
      ...(detail ? { detail } : {}),
      ...(actions && actions.length ? { actions } : {})
    });
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
        // Ignored in the prototype; the button is hidden via capabilities.canAskAssistant.
        this.delegate.log.info(`askAssistant ignored for node ${msg.nodeId}`);
        return;
      case 'log':
        this.delegate.log.info(`[webview] ${msg.level}: ${msg.message}`);
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
    this.panel.title = chrome.title;
    // `description` is declared on `WebviewView`, not on `WebviewPanel` (@types/vscode
    // 1.100.0), so the contractual assignment goes through a narrow cast: VS Code ignores the
    // extra property today and would pick it up unchanged if the API ever grows it. The same
    // count is drawn by the viewer's own scope breadcrumb, so nothing is lost meanwhile.
    (this.panel as vscode.WebviewPanel & { description?: string }).description =
      chrome.description;
    this.delegate.log.info(
      `scope ${msg.spec ?? '(cleared)'}: ${msg.nodes} of ${msg.of} nodes`
    );
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
