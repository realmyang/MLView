import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { createNonce } from './panelHtml';
import { saveExportedFile } from './exportDiagram';
import type { Logger } from './log';
import { toEditorLine } from './location';
import { themeKindOf } from './panel';
import { parseUiToHost } from './protocol';
import { validateWorkflow, type ValidatedWorkflow, type WorkflowEvidence } from './workflowDocument';
export const AUTHORED_VIEW_TYPE = 'mlview.authoredDiagram';
export const OPEN_AUTHORED_COMMAND = 'mlview.openGeneratedDiagram';
const MAX_ARTIFACT_BYTES = 2 * 1024 * 1024;
const MAX_SOURCE_BYTES = 8 * 1024 * 1024;
interface SavedState {
    artifact?: string;
}
export class ReloadGeneration {
    private value = 0;
    begin(): number { return ++this.value; }
    isCurrent(value: number): boolean { return value === this.value; }
}
export class AuthoredDiagramController implements vscode.Disposable {
    private readonly panels = new Map<string, AuthoredPanel>();
    private readonly disposables: vscode.Disposable[] = [];
    constructor(private readonly ctx: vscode.ExtensionContext, private readonly log: Logger) { }
    register(): vscode.Disposable[] {
        const watcher = vscode.workspace.createFileSystemWatcher('**/*');
        const registered = [
            vscode.commands.registerCommand(OPEN_AUTHORED_COMMAND, (uri?: vscode.Uri) => this.open(uri)),
            vscode.window.registerWebviewPanelSerializer(AUTHORED_VIEW_TYPE, { deserializeWebviewPanel: async (panel, state: unknown) => this.restore(panel, state) }),
            vscode.workspace.onDidSaveTextDocument(doc => this.changed(doc.uri)),
            vscode.workspace.onDidChangeTextDocument(event => this.changed(event.document.uri)),
            watcher,
            watcher.onDidChange(uri => this.changed(uri)),
            watcher.onDidCreate(uri => this.changed(uri)),
            watcher.onDidDelete(uri => this.changed(uri))
        ];
        this.disposables.push(...registered);
        return registered;
    }
    async open(uri?: vscode.Uri): Promise<void> {
        let selected = uri;
        if (!selected && vscode.window.activeTextEditor?.document.fileName.endsWith('.mlview.json'))
            selected = vscode.window.activeTextEditor.document.uri;
        if (!selected) {
            const picks = await vscode.workspace.findFiles('**/*.mlview.json', '**/{node_modules,.git}/**', 50);
            selected = picks.length === 1 ? picks[0] : await vscode.window.showQuickPick(picks.map(x => ({ label: path.basename(x.fsPath), description: x.fsPath, uri: x }))).then(x => x?.uri);
            if (!selected && picks.length === 0)
                void vscode.window.showInformationMessage('MLView: no generated *.mlview.json diagrams were found in this workspace.');
        }
        if (!selected)
            return;
        if (selected.scheme !== 'file') {
            void vscode.window.showErrorMessage('MLView: generated diagrams currently require a local file workspace.');
            return;
        }
        const folder = vscode.workspace.getWorkspaceFolder(selected);
        if (!folder) {
            void vscode.window.showErrorMessage('MLView: the generated diagram must belong to an open workspace folder.');
            return;
        }
        const key = selected.fsPath;
        const existing = this.panels.get(key);
        if (existing) {
            existing.reveal();
            await existing.reload();
            return;
        }
        const panel = vscode.window.createWebviewPanel(AUTHORED_VIEW_TYPE, 'MLView Generated Diagram', { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true }, { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'media')] });
        const authored = new AuthoredPanel(panel, selected, folder, this.ctx, this.log, () => this.panels.delete(key));
        this.panels.set(key, authored);
        await authored.reload();
    }
    private async restore(panel: vscode.WebviewPanel, state: unknown): Promise<void> {
        const artifact = state && typeof state === 'object' && typeof (state as SavedState).artifact === 'string' ? (state as SavedState).artifact : undefined;
        if (!artifact) {
            panel.dispose();
            return;
        }
        panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'media')] };
        const uri = vscode.Uri.file(artifact);
        const folder = vscode.workspace.getWorkspaceFolder(uri);
        if (!folder) {
            panel.dispose();
            return;
        }
        const authored = new AuthoredPanel(panel, uri, folder, this.ctx, this.log, () => this.panels.delete(artifact));
        this.panels.set(artifact, authored);
        await authored.reload();
    }
    private changed(uri: vscode.Uri): void {
        for (const panel of this.panels.values())
            if (panel.dependsOn(uri.fsPath))
                void panel.reload();
    }
    dispose(): void {
        for (const p of this.panels.values())
            p.dispose();
        this.panels.clear();
        for (const d of this.disposables)
            d.dispose();
    }
}
class AuthoredPanel implements vscode.Disposable {
    private disposed = false;
    private ready = false;
    private lastValid: ValidatedWorkflow | undefined;
    private dependencies = new Set<string>();
    private readonly disposables: vscode.Disposable[] = [];
    private readonly reloads = new ReloadGeneration();
    private pendingError: string | undefined;
    private lastFingerprint: string | undefined;
    constructor(private readonly panel: vscode.WebviewPanel, private readonly artifact: vscode.Uri, private readonly folder: vscode.WorkspaceFolder, private readonly ctx: vscode.ExtensionContext, private readonly log: Logger, private readonly onDispose: () => void) { this.render(); panel.onDidDispose(() => this.dispose(), null, this.disposables); panel.webview.onDidReceiveMessage((m: unknown) => void this.message(m), null, this.disposables); this.disposables.push(vscode.window.onDidChangeActiveColorTheme(theme => this.post({ v: 1, type: 'theme', kind: themeKindOf(theme.kind) }))); }
    reveal(): void { this.panel.reveal(vscode.ViewColumn.Beside, true); }
    dependsOn(file: string): boolean { return file === this.artifact.fsPath || this.dependencies.has(file); }
    private async textFor(file: string): Promise<string> {
        const limit = path.resolve(file) === path.resolve(this.artifact.fsPath) ? MAX_ARTIFACT_BYTES : MAX_SOURCE_BYTES;
        const open = vscode.workspace.textDocuments.find(d => d.uri.scheme === 'file' && path.resolve(d.uri.fsPath) === path.resolve(file));
        if (open) {
            const value = open.getText();
            if (Buffer.byteLength(value) > limit)
                throw new Error(`file exceeds ${limit} byte limit`);
            return value;
        }
        const stat = await fs.stat(file);
        if (!stat.isFile())
            throw new Error('path is not a regular file');
        if (stat.size > limit)
            throw new Error(`file exceeds ${limit} byte limit`);
        return fs.readFile(file, 'utf8');
    }
    private async notebookCellFor(file: string, cell: number): Promise<string | undefined> { const notebook = vscode.workspace.notebookDocuments.find(n => n.uri.scheme === 'file' && path.resolve(n.uri.fsPath) === path.resolve(file)); return notebook?.cellAt(cell)?.document.getText(); }
    async reload(): Promise<void> {
        if (this.disposed)
            return;
        const generation = this.reloads.begin();
        let source: string;
        let parsed: unknown;
        try {
            source = await this.textFor(this.artifact.fsPath);
            parsed = JSON.parse(source);
        }
        catch (err) {
            if (this.reloads.isCurrent(generation))
                this.invalid(`JSON parse error: ${String(err)}`);
            return;
        }
        const result = await validateWorkflow(parsed, this.folder.uri.fsPath, p => this.textFor(p), (p, c) => this.notebookCellFor(p, c));
        if (this.disposed || !this.reloads.isCurrent(generation))
            return;
        if (!result.value) {
            this.invalid(result.issues.slice(0, 8).map(x => `${x.path}: ${x.message}`).join('\n'));
            return;
        }
        const fingerprint = source;
        const prior = this.lastValid?.document.revision;
        if (prior && result.value.staleFiles.length) {
            this.invalid(`revision ${result.value.document.revision.id} has ${result.value.staleFiles.length} stale verified file(s)`);
            return;
        }
        if (prior && result.value.document.revision.id === prior.id && fingerprint !== this.lastFingerprint) {
            this.invalid(`revision ${prior.id} changed content without a new revision id`);
            return;
        }
        if (prior && result.value.document.revision.id !== prior.id && result.value.document.revision.parent !== prior.id) {
            this.invalid(`revision ${result.value.document.revision.id} does not supersede displayed revision ${prior.id}`);
            return;
        }
        this.lastValid = result.value;
        this.lastFingerprint = fingerprint;
        this.pendingError = result.value.staleFiles.length ? `This historical diagram is visible, but ${result.value.staleFiles.length} source file(s) differ from its published hashes. Source navigation is blocked until the assistant publishes a fresh revision.` : undefined;
        this.dependencies = new Set(result.value.files);
        for (const rel of [...result.value.document.coverage.inspectedFiles, ...result.value.document.evidence.map(e => e.file)])
            this.dependencies.add(path.resolve(this.folder.uri.fsPath, rel));
        this.panel.title = `MLView: ${result.value.document.title}`;
        if (this.ready) {
            this.post({ v: 1, type: 'workflowError', message: '', retained: false });
            this.post({ v: 1, type: 'workflow', document: result.value.document });
            if (this.pendingError)
                this.post({ v: 1, type: 'workflowError', message: this.pendingError, retained: true });
        }
        if (result.value.staleFiles.length)
            void vscode.window.showWarningMessage(`MLView: ${result.value.staleFiles.length} cited file(s) differ from the published revision.`);
    }
    private invalid(reason: string): void {
        this.pendingError = `Generated diagram update rejected; ${this.lastValid ? 'retaining the last valid revision.' : 'nothing valid can be displayed yet.'}\n${reason}`;
        this.log.warn(`authored artifact ${this.artifact.fsPath} rejected: ${reason}`);
        if (this.ready)
            this.post({ v: 1, type: 'workflowError', message: this.pendingError, retained: !!this.lastValid });
    }
    private async message(raw: unknown): Promise<void> {
        if (!raw || typeof raw !== 'object')
            return;
        const m = raw as Record<string, unknown>;
        if (m.v !== 1 || typeof m.type !== 'string')
            return;
        if (m.type === 'ready') {
            this.ready = true;
            this.post({
                v: 1,
                type: 'init',
                theme: themeKindOf(vscode.window.activeColorTheme.kind),
                capabilities: {
                    canOpenSource: true,
                    canReanalyze: false,
                    // The shared viewer's canExport flag controls its legacy host-side HTML
                    // report action. Authored panels save SVG/PNG through the independent
                    // export menu and exportFile protocol, so keep that unsupported action hidden.
                    canExport: false,
                    canAskAssistant: false,
                    canRefine: true
                },
                artifact: this.artifact.fsPath
            });
            if (this.pendingError)
                this.post({ v: 1, type: 'workflowError', message: this.pendingError, retained: !!this.lastValid });
            if (this.lastValid)
                this.post({ v: 1, type: 'workflow', document: this.lastValid.document });
            return;
        }
        if (m.type === 'openLocation') {
            await this.openEvidence(m);
            return;
        }
        if (m.type === 'refineWorkflow') {
            await this.copyRefinementPrompt(m);
            return;
        }
        if (m.type === 'exportFile') {
            const parsed = parseUiToHost(raw);
            if (parsed.ok && parsed.msg.type === 'exportFile')
                await saveExportedFile(parsed.msg, { log: this.log, workspaceRoot: () => this.folder.uri.fsPath });
        }
    }
    private async copyRefinementPrompt(m: Record<string, unknown>): Promise<void> {
        const doc = this.lastValid?.document;
        if (!doc || m.revisionId !== doc.revision.id)
            return;
        const prompt = `Use the MLView skill to refine ${path.relative(this.folder.uri.fsPath, this.artifact.fsPath)} revision ${doc.revision.id}. Continue from the current question: ${doc.request.question}\nRequested scope: ${doc.request.scope}\nWrite a new revision whose parent is ${doc.revision.id}, then validate and publish the artifact.`;
        await vscode.env.clipboard.writeText(prompt);
        void vscode.window.showInformationMessage('MLView refinement prompt copied. Paste it into the assistant that authored this diagram.');
    }
    private async openEvidence(m: Record<string, unknown>): Promise<void> {
        const id = typeof m.evidenceId === 'string' ? m.evidenceId : undefined;
        const evidence = this.lastValid?.document.evidence.find(x => x.id === id);
        if (!evidence)
            return;
        const fresh = await validateWorkflow(this.lastValid!.document, this.folder.uri.fsPath, p => this.textFor(p), (p, c) => this.notebookCellFor(p, c));
        const candidate = path.resolve(this.folder.uri.fsPath, evidence.file);
        let cited = candidate;
        try {
            cited = await fs.realpath(candidate);
        }
        catch { }
        if (!fresh.value || fresh.value.staleFiles.some(x => path.resolve(x) === cited)) {
            void vscode.window.showWarningMessage(`MLView: evidence ${evidence.id} is stale or invalid; source navigation was stopped.`);
            return;
        }
        await this.navigate(evidence);
    }
    private async navigate(e: WorkflowEvidence): Promise<void> {
        const uri = vscode.Uri.file(path.join(this.folder.uri.fsPath, e.file));
        const start = toEditorLine(e.line), end = toEditorLine(e.endLine);
        if (e.cell !== undefined) {
            const notebook = await vscode.workspace.openNotebookDocument(uri);
            const cell = notebook.cellAt(e.cell);
            if (!cell) {
                void vscode.window.showWarningMessage(`MLView: notebook cell ${e.cell} no longer exists.`);
                return;
            }
            const editor = await vscode.window.showTextDocument(cell.document, { preview: true });
            const range = new vscode.Range(start, 0, end, Math.max(0, cell.document.lineAt(end).text.length));
            editor.selection = new vscode.Selection(range.start, range.start);
            editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
            return;
        }
        const doc = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(doc, { preview: true });
        const range = new vscode.Range(start, 0, end, doc.lineAt(end).text.length);
        editor.selection = new vscode.Selection(range.start, range.start);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
    }
    private post(message: unknown): void {
        if (!this.disposed)
            void this.panel.webview.postMessage(message);
    }
    private render(): void { const nonce = createNonce(); const script = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.js')); const style = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.css')); this.panel.webview.html = `<!doctype html><html><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this.panel.webview.cspSource} data:; style-src ${this.panel.webview.cspSource}; script-src 'nonce-${nonce}' ${this.panel.webview.cspSource};"><link rel="stylesheet" href="${style}"></head><body><div id="mlview-root"></div><script nonce="${nonce}" src="${script}"></script><script nonce="${nonce}">(function(){var root=document.getElementById('mlview-root');var bridge=window.MLView.bridges.vscode();var save=bridge.saveState.bind(bridge);var artifact=null;bridge.saveState=function(state){save(Object.assign({},state,{artifact:artifact}));};var app=null;bridge.onMessage(function(m){if(!m)return;if(m.type==='init'&&m.artifact){artifact=m.artifact;bridge.saveState({});}if(m.type==='workflow'){if(app&&app.setWorkflow){app.setWorkflow(m.document,m.preserve);return;}app=window.MLView.mountWorkflow(root,m.document,bridge);}if(m.type==='workflowError'){var e=document.getElementById('mlview-authored-error');if(!m.message){if(e)e.remove();return;}if(!e){e=document.createElement('pre');e.id='mlview-authored-error';root.prepend(e);}e.textContent=m.message;}});bridge.post({v:1,type:'ready'});}());</script></body></html>`; }
    dispose(): void {
        if (this.disposed)
            return;
        this.disposed = true;
        for (const d of this.disposables)
            d.dispose();
        this.onDispose();
    }
}
