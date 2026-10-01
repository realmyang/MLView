import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { createNonce, findRootHint, rootHintJumpText, rootHintText, staleBannerText, staleJumpText, staleToastText, themeKindOf, toEditorLine, type RootHint } from './authoredSupport';
import { MAX_EXPORT_BYTES, parseExportFileMessage, saveExportedFile } from './exportDiagram';
import { DependencySet, identity } from './fileIdentity';
import type { Logger } from './log';
import { buildRefinementPrompt, REFINE_INTENTS, toPosixRelative, type RefineIntent, type RefineSelection } from './refinePrompt';
import { displayIssue, displayText } from './displayText';
import { canonicalJson, jsonDepth, lenientRevision, MAX_JSON_DEPTH, RevisionLineage, semanticJson, type Candidate, type Verdict } from './revisionLineage';
import { ID_PATTERN, MAX_DOCUMENT_BYTES, MAX_SOURCE_BYTES, quoteMatches, readSourceBytes, trackedFiles, validateWorkflow, validateWorkflowStructure, type ValidatedWorkflow, type ValidationIssue, type WorkflowEvidence } from './workflowDocument';
export const AUTHORED_VIEW_TYPE = 'mlview.authoredDiagram';
export const OPEN_AUTHORED_COMMAND = 'mlview.openGeneratedDiagram';
const RELOAD_DEBOUNCE_MS = 120;
const DIRTY_THROTTLE_MS = 150;
const RETRY_DELAYS_MS = [250, 1000, 4000];
const TRANSIENT_CODES = new Set(['EBUSY', 'EAGAIN', 'EPERM', 'EACCES', 'EMFILE', 'ENFILE']);
const REQUEST_ID = /^[A-Za-z0-9_-]{1,64}$/;
/** How long a jump into a notebook waits for VS Code to create the cited cell's editor. */
const CELL_EDITOR_WAIT_MS = 500;
const ADD_FOLDER = 'Add Folder to Workspace';
const OPEN_FOLDER = 'Open Folder';
/**
 * The cited range in the editor beside the panel: the theme's range highlight on every cited
 * line plus a mark in the overview ruler, so the lines stay visible while focus stays on the
 * diagram. Built from theme colours only. High Contrast themes leave
 * `editor.rangeHighlightBackground` undefined and mark a range highlight with
 * `editor.rangeHighlightBorder` instead (A11Y-1), so the border is set too; outside High Contrast
 * that colour is undefined and draws nothing.
 */
const HIGHLIGHT_STYLE = (): vscode.DecorationRenderOptions => ({
    isWholeLine: true,
    backgroundColor: new vscode.ThemeColor('editor.rangeHighlightBackground'),
    borderColor: new vscode.ThemeColor('editor.rangeHighlightBorder'),
    borderStyle: 'solid',
    borderWidth: '1px',
    overviewRulerColor: new vscode.ThemeColor('editorOverviewRuler.rangeHighlightForeground'),
    overviewRulerLane: vscode.OverviewRulerLane.Full,
    rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed
});
interface SavedState {
    artifact?: string;
}
/**
 * The root hint's "Add folder" in a single-folder window: VS Code turns the window into an
 * untitled multi-root workspace and restarts every extension host, so this extension restarts
 * too. The panels the old host drew keep their tabs, but nothing answers them any more. VS Code
 * calls the panel serializer only for tabs it restores when a window loads, never after an
 * extension host restart (checked live in VS Code 1.139). So before it adds the folder, the host
 * saves this note, and the next host closes the dead tabs and opens the diagrams again
 * (`recoverAfterRestart`).
 *
 * The note lives in the global state: the new workspace starts with an empty workspace state
 * (VS Code 1.139 does not copy it). The global state is shared by every window, so the note
 * carries `vscode.env.sessionId`, which stays the same across an extension host restart and
 * differs between windows and after a window reload.
 */
export const REOPEN_STATE_KEY = 'mlview.reopenAfterFolderAdd';
/** A note older than this is ignored: VS Code restarts the extension host within about a second. */
export const REOPEN_WINDOW_MS = 60_000;
/**
 * The view type the tabs API reports for a panel tab. VS Code 1.139 reports it with a
 * `mainThreadWebview-` prefix; the bare form is accepted too, in case a later release drops it.
 */
const AUTHORED_TAB_VIEW_TYPES = new Set([AUTHORED_VIEW_TYPE, `mainThreadWebview-${AUTHORED_VIEW_TYPE}`]);
interface ReopenNote {
    /** When the note was saved (ms since the epoch). */
    at: number;
    /** The window's `vscode.env.sessionId`. */
    session: string;
    /** The folder being added. */
    added: string;
    /** Every open diagram: its artifact and its tab's title. */
    panels: { artifact: string; title: string }[];
}
/** The note read back from storage, or undefined when it is malformed. */
function parseReopenNote(value: unknown): ReopenNote | undefined {
    if (!value || typeof value !== 'object')
        return undefined;
    const note = value as Record<string, unknown>;
    if (typeof note.at !== 'number' || !Number.isFinite(note.at) || typeof note.session !== 'string' || typeof note.added !== 'string' || !path.isAbsolute(note.added) || !Array.isArray(note.panels))
        return undefined;
    const panels: ReopenNote['panels'] = [];
    for (const entry of note.panels.slice(0, 50)) {
        const item = entry as Record<string, unknown> | null;
        if (item && typeof item.artifact === 'string' && typeof item.title === 'string')
            panels.push({ artifact: item.artifact, title: item.title });
    }
    return { at: note.at, session: note.session, added: note.added, panels };
}
/** The note belongs to this window. */
const ownNote = (value: unknown): boolean => parseReopenNote(value)?.session === vscode.env.sessionId;
const isAuthoredTab = (tab: vscode.Tab): boolean => tab.input instanceof vscode.TabInputWebview && AUTHORED_TAB_VIEW_TYPES.has(tab.input.viewType);
/** Saves and withdraws the reopen note (see `REOPEN_STATE_KEY`); the controller owns it. */
interface RestartNotes {
    note(added: string): Promise<void>;
    forget(): Promise<void>;
}
/**
 * One source jump: the revision and freshness it was decided against, and its place in the order
 * of jumps. A jump that a newer one overtook stops before it touches an editor or the highlight
 * (M1-R2: a notebook jump waiting for its cell editor cleared the highlight of a later jump).
 */
interface Jump {
    revision: string;
    freshness: number;
    seq: number;
}
/** Outcome of reading the artifact bytes from disk (never from an editor buffer). */
export type ArtifactRead = { kind: 'bytes'; bytes: Uint8Array } | { kind: 'missing' } | { kind: 'unreadable'; detail: string; transient?: boolean };
export interface AuthoredPanelIo {
    readArtifact(fsPath: string): Promise<ArtifactRead>;
}
function readError(error: unknown): ArtifactRead {
    const code = (error as NodeJS.ErrnoException | undefined)?.code;
    if (code === 'ENOENT')
        return { kind: 'missing' };
    // Never put String(error) in a message: it contains the absolute path.
    return { kind: 'unreadable', detail: typeof code === 'string' ? code : 'read error', transient: typeof code === 'string' && TRANSIENT_CODES.has(code) };
}
export async function readArtifactFile(fsPath: string): Promise<ArtifactRead> {
    let stat: Awaited<ReturnType<typeof fs.stat>>;
    try {
        stat = await fs.stat(fsPath);
    }
    catch (error) {
        return readError(error);
    }
    if (!stat.isFile())
        return { kind: 'unreadable', detail: 'it is not a regular file' };
    if (stat.size > MAX_DOCUMENT_BYTES)
        return { kind: 'unreadable', detail: `it exceeds the ${MAX_DOCUMENT_BYTES}-byte limit` };
    let bytes: Buffer;
    try {
        bytes = await fs.readFile(fsPath);
    }
    catch (error) {
        return readError(error);
    }
    if (bytes.length > MAX_DOCUMENT_BYTES)
        return { kind: 'unreadable', detail: `it exceeds the ${MAX_DOCUMENT_BYTES}-byte limit` };
    return { kind: 'bytes', bytes: new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) };
}
const defaultIo: AuthoredPanelIo = { readArtifact: readArtifactFile };
const asciiLower = (value: string): string => value.replace(/[A-Z]/g, c => String.fromCharCode(c.charCodeAt(0) + 32));
const isArtifactPath = (value: string): boolean => asciiLower(value).endsWith('.mlview.json');
/**
 * An artifact path read back from storage (the webview state or the reopen note): accepted only
 * as an absolute *.mlview.json inside a workspace folder.
 */
function savedArtifact(value: unknown): ReturnType<typeof workspaceArtifact> {
    if (typeof value !== 'string' || !path.isAbsolute(value) || !isArtifactPath(value))
        return undefined;
    return workspaceArtifact(value);
}
/**
 * The artifact at `fsPath` after lexical normalisation, with the workspace folder that contains
 * it; undefined when it lies outside every folder. VS Code's Uri.file and getWorkspaceFolder keep
 * `..` segments, so `<folder>/../outside/x.mlview.json` would otherwise match the folder.
 */
function workspaceArtifact(fsPath: string): { uri: vscode.Uri; folder: vscode.WorkspaceFolder; key: string } | undefined {
    const resolved = path.resolve(fsPath);
    const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(resolved));
    if (!folder)
        return undefined;
    // VS Code matches workspace folders ignoring case on macOS and Windows, so the matched prefix
    // can be spelled differently from the folder. Spell it the folder's way, so containment, the
    // panel key, the artifact's relative path and the watched path all agree with the folder
    // (LINEAGE2-3). Only the prefix changes: the rest keeps its spelling, which is right on a
    // case-sensitive volume.
    const artifact = folderSpelling(resolved, path.resolve(folder.uri.fsPath));
    const rel = path.relative(folder.uri.fsPath, artifact);
    if (!rel || rel === '..' || rel.startsWith('..' + path.sep) || path.isAbsolute(rel))
        return undefined;
    return { uri: vscode.Uri.file(artifact), folder, key: artifact };
}
/** `resolved` with a case-variant prefix equal to `root` re-spelled as `root` (macOS and Windows only). */
export function folderSpelling(resolved: string, root: string, platform: NodeJS.Platform = process.platform): string {
    if (platform !== 'darwin' && platform !== 'win32')
        return resolved;
    const sep = platform === 'win32' ? '\\' : '/';
    const head = resolved.slice(0, root.length);
    if (head === root || head.toLowerCase() !== root.toLowerCase())
        return resolved;
    const boundary = resolved.length === root.length || root.endsWith(sep) || resolved[root.length] === sep;
    return boundary ? root + resolved.slice(root.length) : resolved;
}
export class ReloadGeneration {
    private value = 0;
    begin(): number { return ++this.value; }
    isCurrent(value: number): boolean { return value === this.value; }
}
type TimerHandle = ReturnType<typeof setTimeout>;
type TimerApi = {
    set(callback: () => void, delay: number): TimerHandle;
    clear(handle: TimerHandle): void;
};
const systemTimers: TimerApi = {
    set: (callback, delay) => setTimeout(callback, delay),
    clear: handle => clearTimeout(handle)
};
export class ValidationScheduler implements vscode.Disposable {
    private active = false;
    private queued = false;
    private disposed = false;
    private timer: TimerHandle | undefined;
    private waiters: (() => void)[] = [];
    constructor(private readonly work: () => Promise<void>, private readonly delay = RELOAD_DEBOUNCE_MS, private readonly timers: TimerApi = systemTimers, private readonly onError: (error: unknown) => void = () => undefined) { }
    immediate(): Promise<void> {
        if (this.disposed)
            return Promise.resolve();
        this.cancelTimer();
        this.queued = true;
        const done = new Promise<void>(resolve => this.waiters.push(resolve));
        void this.drain();
        return done;
    }
    debounce(): void {
        if (this.disposed)
            return;
        this.cancelTimer();
        this.timer = this.timers.set(() => {
            this.timer = undefined;
            this.queued = true;
            void this.drain();
        }, this.delay);
    }
    private cancelTimer(): void {
        if (this.timer !== undefined) {
            this.timers.clear(this.timer);
            this.timer = undefined;
        }
    }
    private async drain(): Promise<void> {
        if (this.active || this.disposed)
            return;
        this.active = true;
        try {
            while (this.queued && !this.disposed) {
                this.queued = false;
                try {
                    await this.work();
                }
                catch (error) {
                    this.onError(error);
                }
            }
        }
        finally {
            this.active = false;
            if ((!this.queued && this.timer === undefined) || this.disposed) {
                const waiters = this.waiters;
                this.waiters = [];
                waiters.forEach(resolve => resolve());
            }
            else if (this.queued) {
                void this.drain();
            }
        }
    }
    dispose(): void {
        if (this.disposed)
            return;
        this.disposed = true;
        this.cancelTimer();
        this.queued = false;
        const waiters = this.waiters;
        this.waiters = [];
        waiters.forEach(resolve => resolve());
    }
}
export class AuthoredDiagramController implements vscode.Disposable {
    private readonly panels = new Map<string, AuthoredPanel>();
    private readonly disposables: vscode.Disposable[] = [];
    constructor(private readonly ctx: vscode.ExtensionContext, private readonly log: Logger, private readonly validator: typeof validateWorkflow = validateWorkflow, private readonly io: AuthoredPanelIo = defaultIo) { }
    register(): vscode.Disposable[] {
        const watcher = vscode.workspace.createFileSystemWatcher('**/*');
        const registered = [
            vscode.commands.registerCommand(OPEN_AUTHORED_COMMAND, (uri?: vscode.Uri) => this.open(uri)),
            vscode.window.registerWebviewPanelSerializer(AUTHORED_VIEW_TYPE, { deserializeWebviewPanel: async (panel, state: unknown) => this.restore(panel, state) }),
            // Saves and watcher events change the files on disk: revalidate.
            vscode.workspace.onDidSaveTextDocument(doc => this.diskChanged(doc.uri)),
            vscode.workspace.onDidSaveNotebookDocument(doc => this.diskChanged(doc.uri)),
            watcher,
            watcher.onDidChange(uri => this.diskChanged(uri)),
            watcher.onDidCreate(uri => this.diskChanged(uri)),
            watcher.onDidDelete(uri => this.diskChanged(uri)),
            // Buffer edits never change what is validated; they only update the unsaved-changes status.
            vscode.workspace.onDidChangeTextDocument(event => this.bufferChanged(event.document.uri)),
            vscode.workspace.onDidChangeNotebookDocument(event => this.bufferChanged(event.notebook.uri)),
            // A folder added or removed can change which folder owns an artifact (the root hint's
            // "Add Folder to Workspace"), so every open panel validates again.
            vscode.workspace.onDidChangeWorkspaceFolders(() => this.foldersChanged())
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
        if (!isArtifactPath(selected.fsPath)) {
            void vscode.window.showErrorMessage('MLView: select a *.mlview.json generated diagram.');
            return;
        }
        const target = workspaceArtifact(selected.fsPath);
        if (!target) {
            void vscode.window.showErrorMessage('MLView: the generated diagram must belong to an open workspace folder.');
            return;
        }
        const existing = this.panels.get(target.key);
        if (existing) {
            // Re-running the command shows the file as it is, even a revision the panel had refused.
            await existing.reopen();
            return;
        }
        await this.create(target, vscode.ViewColumn.Beside).reload();
    }
    /** A new panel for `target` in `column`, keeping focus where it is. */
    private create(target: NonNullable<ReturnType<typeof workspaceArtifact>>, column: vscode.ViewColumn): AuthoredPanel {
        const panel = vscode.window.createWebviewPanel(AUTHORED_VIEW_TYPE, 'MLView Generated Diagram', { viewColumn: column, preserveFocus: true }, { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'media')] });
        return this.adopt(panel, target);
    }
    private adopt(panel: vscode.WebviewPanel, target: NonNullable<ReturnType<typeof workspaceArtifact>>): AuthoredPanel {
        const { uri, folder, key } = target;
        const authored: AuthoredPanel = new AuthoredPanel(panel, uri, folder, this.ctx, this.log, () => {
            if (this.panels.get(key) === authored)
                this.panels.delete(key);
        }, this.restartNotes, this.validator, this.io);
        this.panels.set(key, authored);
        return authored;
    }
    private async restore(panel: vscode.WebviewPanel, state: unknown): Promise<void> {
        // The saved state comes from the webview: accept only an absolute *.mlview.json inside a workspace folder.
        const target = savedArtifact(state && typeof state === 'object' ? (state as SavedState).artifact : undefined);
        // One panel per artifact: a revived tab whose diagram is already shown (opened, or reopened
        // after a restart, before VS Code revived this tab) is closed.
        if (!target || this.panels.has(target.key)) {
            panel.dispose();
            return;
        }
        panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'media')] };
        await this.adopt(panel, target).reload();
    }
    private readonly restartNotes: RestartNotes = {
        note: added => this.noteReopen(added),
        forget: () => this.forgetReopen()
    };
    /** Save the reopen note for the next extension host, listing every open diagram (see `REOPEN_STATE_KEY`). */
    private async noteReopen(added: string): Promise<void> {
        const note: ReopenNote = { at: Date.now(), session: vscode.env.sessionId, added, panels: [...this.panels.values()].map(panel => panel.reopenEntry()) };
        try {
            await this.ctx.globalState.update(REOPEN_STATE_KEY, note);
        }
        catch (error) {
            this.log.warn(`could not save the reopen note: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
    /** Delete the reopen note: only this window's note, unless `any`. */
    private async forgetReopen(any = false): Promise<void> {
        const raw = this.ctx.globalState.get<unknown>(REOPEN_STATE_KEY);
        if (raw === undefined || (!any && !ownNote(raw)))
            return;
        try {
            await this.ctx.globalState.update(REOPEN_STATE_KEY, undefined);
        }
        catch (error) {
            this.log.warn(`could not clear the reopen note: ${error instanceof Error ? error.message : String(error)}`);
        }
    }
    /**
     * Run once at activation. When the root hint's "Add folder" made VS Code restart the extension
     * host (see `REOPEN_STATE_KEY`), close the dead tabs the old host left and open each diagram
     * again in the same editor group. The new panel validates against the workspace as it is now,
     * so the artifact belongs to the added folder. Another window's note is left alone until it
     * expires; this window's note is deleted whatever it held, and ignored when it is older than a
     * minute or the folder it names is not in the workspace. Only one diagram tab per noted panel,
     * titled like it, is closed; other tabs are left alone. Returns how many diagrams were opened.
     */
    async recoverAfterRestart(now: number = Date.now()): Promise<number> {
        const raw = this.ctx.globalState.get<unknown>(REOPEN_STATE_KEY);
        if (raw === undefined)
            return 0;
        // Taken before anything else can run: no panel of this host exists yet, so every diagram
        // tab now open was drawn by the old host or is a restored tab not yet shown.
        const tabs = vscode.window.tabGroups.all.flatMap(group => group.tabs).filter(isAuthoredTab);
        const note = parseReopenNote(raw);
        const expired = !note || now < note.at || now - note.at > REOPEN_WINDOW_MS;
        if (!expired && note.session !== vscode.env.sessionId)
            return 0;
        await this.forgetReopen(true);
        if (expired) {
            this.log.info('ignored an expired or malformed reopen note');
            return 0;
        }
        const added = path.resolve(note.added);
        if (!(vscode.workspace.workspaceFolders ?? []).some(folder => path.resolve(folder.uri.fsPath) === added)) {
            this.log.info('ignored a reopen note: its folder is not in the workspace');
            return 0;
        }
        // One tab per noted panel, the front tab of a group first: a restored tab that was never
        // shown (and so is not dead) is never in front, since VS Code revives the front tab at once.
        tabs.sort((a, b) => Number(b.isActive) - Number(a.isActive));
        const dead = new Set<vscode.Tab>();
        const plans: { target: NonNullable<ReturnType<typeof workspaceArtifact>>; column: vscode.ViewColumn; active: boolean }[] = [];
        for (const entry of note.panels) {
            const tab = tabs.find(candidate => !dead.has(candidate) && candidate.label === entry.title);
            // No tab left for it: the reader closed it, so there is nothing to replace.
            if (!tab)
                continue;
            dead.add(tab);
            const target = savedArtifact(entry.artifact);
            if (target && !plans.some(plan => plan.target.key === target.key))
                plans.push({ target, column: tab.group.viewColumn, active: tab.isActive });
        }
        // The diagram that was in front of its group is opened last, so it is in front again.
        plans.sort((a, b) => Number(a.active) - Number(b.active));
        // Open the new panels next to the dead tabs before closing those, so their groups stay.
        const opened = plans.filter(plan => !this.panels.has(plan.target.key)).map(plan => this.create(plan.target, plan.column));
        if (dead.size) {
            try {
                await vscode.window.tabGroups.close([...dead], true);
            }
            catch (error) {
                this.log.warn(`could not close the diagram tabs left by the restart: ${error instanceof Error ? error.message : String(error)}`);
            }
        }
        this.log.info(`VS Code restarted the extension host to add a workspace folder: closed ${dead.size} dead diagram tab(s) and opened ${opened.length} diagram(s) again`);
        await Promise.all(opened.map(panel => panel.reload()));
        return opened.length;
    }
    private diskChanged(uri: vscode.Uri): void {
        for (const panel of this.panels.values())
            if (panel.dependsOn(uri.fsPath))
                panel.sourceChanged();
    }
    private bufferChanged(uri: vscode.Uri): void {
        for (const panel of this.panels.values())
            if (panel.dependsOn(uri.fsPath))
                panel.bufferChanged();
    }
    private foldersChanged(): void {
        // This host saw the change, so it was not restarted: no tab needs replacing. (In a
        // single-folder window VS Code stops the old host before it changes the folders.)
        void this.forgetReopen();
        for (const panel of this.panels.values())
            panel.foldersChanged();
    }
    dispose(): void {
        for (const p of this.panels.values())
            p.dispose();
        this.panels.clear();
        for (const d of this.disposables)
            d.dispose();
    }
}
type ValidationResult = Awaited<ReturnType<typeof validateWorkflow>>;
type BannerItem = { code: string; text: string };
type ParsedStructure = ReturnType<typeof validateWorkflowStructure>['document'];
type ParsedCandidate = Exclude<Candidate, { kind: 'json' }> | (Omit<Extract<Candidate, { kind: 'json' }>, 'result'> & { result: ValidationResult; structural?: ParsedStructure });
/** Lines `start`..`end` (zero-based), clamped to the document, from column 0 to the end of the last line. */
function citedRange(document: vscode.TextDocument, start: number, end: number): vscode.Range {
    const last = Math.max(0, Math.min(end, document.lineCount - 1));
    const first = Math.max(0, Math.min(start, last));
    return new vscode.Range(first, 0, last, document.lineAt(last).text.length);
}
/** The visible text editor showing `document`, waiting up to `timeoutMs` for VS Code to create it. */
function visibleEditorFor(document: vscode.TextDocument, timeoutMs: number): Promise<vscode.TextEditor | undefined> {
    const key = document.uri.toString();
    const find = (): vscode.TextEditor | undefined => vscode.window.visibleTextEditors.find(editor => editor.document.uri.toString() === key);
    const found = find();
    if (found || timeoutMs <= 0)
        return Promise.resolve(found);
    return new Promise(resolve => {
        let settled = false;
        const finish = (editor: vscode.TextEditor | undefined): void => {
            if (settled)
                return;
            settled = true;
            clearTimeout(timer);
            subscription.dispose();
            resolve(editor);
        };
        const subscription = vscode.window.onDidChangeVisibleTextEditors(() => {
            const editor = find();
            if (editor)
                finish(editor);
        });
        const timer = setTimeout(() => finish(find()), timeoutMs);
    });
}
const listFiles = (rels: readonly string[]): string => rels.slice(0, 3).map(rel => displayText(rel, 200)).join(', ') + (rels.length > 3 ? `, and ${rels.length - 3} more` : '');
class AuthoredPanel implements vscode.Disposable {
    private disposed = false;
    private ready = false;
    /** The displayed revision's latest validation. */
    private lastValid: ValidatedWorkflow | undefined;
    private readonly lineage = new RevisionLineage();
    private dependencies = new DependencySet();
    private readonly disposables: vscode.Disposable[] = [];
    private readonly reloads = new ReloadGeneration();
    private readonly scheduler: ValidationScheduler;
    /** The artifact relative to its workspace folder; changes only when the owning folder does. */
    private artifactRel: string;
    private validationTail: Promise<void> = Promise.resolve();
    private freshnessVersion = 0;
    private pendingCheck = false;
    private rejection: BannerItem | undefined;
    private lineageNote: BannerItem | undefined;
    private dirty: string[] = [];
    private dirtyVersion = 0;
    private dirtyTimer: TimerHandle | undefined;
    private retryTimer: TimerHandle | undefined;
    private retryCount = 0;
    private lastPostedBanner = '';
    private lastPostedFull: string | undefined;
    private lastStaleToast: string | undefined;
    /** The stale set last posted to this webview page, as JSON; undefined means none (an empty set). */
    private lastPostedStale: string | undefined;
    /** Where the missing cited files exist with their published hashes, when the root is wrong. */
    private rootHint: RootHint | undefined;
    private lastHintToast: string | undefined;
    /** The whole-range highlight of the last source jump; disposing it clears it from every editor. */
    private highlight: vscode.TextEditorDecorationType | undefined;
    /** The number of the latest source jump (see `Jump`). */
    private jumpSeq = 0;
    constructor(private readonly panel: vscode.WebviewPanel, private readonly artifact: vscode.Uri, private folder: vscode.WorkspaceFolder, private readonly ctx: vscode.ExtensionContext, private readonly log: Logger, private readonly onDispose: () => void, private readonly restartNotes: RestartNotes, private readonly validator: typeof validateWorkflow, private readonly io: AuthoredPanelIo) {
        this.artifactRel = toPosixRelative(folder.uri.fsPath, artifact.fsPath);
        this.dependencies.addPath(artifact.fsPath);
        this.scheduler = new ValidationScheduler(() => this.runReload(), RELOAD_DEBOUNCE_MS, systemTimers, error => this.log.warn(`authored reload failed: ${error instanceof Error ? error.message : String(error)}`));
        this.render();
        panel.onDidDispose(() => this.dispose(), null, this.disposables);
        panel.webview.onDidReceiveMessage((m: unknown) => { void this.message(m).catch(error => this.log.warn(`authored message failed: ${error instanceof Error ? error.message : String(error)}`)); }, null, this.disposables);
        this.disposables.push(vscode.window.onDidChangeActiveColorTheme(theme => this.post({ v: 1, type: 'theme', kind: themeKindOf(theme.kind) })));
    }
    reveal(): void { this.panel.reveal(vscode.ViewColumn.Beside, true); }
    /** This panel in the reopen note: the artifact and the tab title (see `REOPEN_STATE_KEY`). */
    reopenEntry(): { artifact: string; title: string } { return { artifact: this.artifact.fsPath, title: this.panel.title }; }
    /** MLView: Open Generated Diagram for an already-open artifact. */
    async reopen(): Promise<void> {
        this.lineage.reset();
        this.cancelRetry();
        this.retryCount = 0;
        this.reveal();
        await this.reload();
    }
    dependsOn(file: string): boolean { return this.dependencies.has(file); }
    /** A dependency changed on disk: show the checking status and revalidate after the debounce. */
    sourceChanged(): void {
        if (this.disposed)
            return;
        this.reloads.begin();
        this.freshnessVersion++;
        // Every disk-triggered reload starts a fresh budget of transient-read retries.
        this.cancelRetry();
        this.retryCount = 0;
        this.pendingCheck = true;
        this.postBanner();
        this.scheduler.debounce();
    }
    /** An editor buffer changed: recompute only the unsaved-changes status, at most once per 150 ms. */
    bufferChanged(): void {
        if (this.disposed || this.dirtyTimer !== undefined)
            return;
        this.dirtyTimer = setTimeout(() => {
            this.dirtyTimer = undefined;
            void this.computeDirty().then(() => this.postBanner());
        }, DIRTY_THROTTLE_MS);
    }
    /**
     * The workspace folders changed: the artifact may now belong to another (innermost) folder,
     * for example the one the root hint added. Validate again either way; the product always
     * validates against the folder that really owns the artifact, never against the hint.
     */
    foldersChanged(): void {
        if (this.disposed)
            return;
        const target = workspaceArtifact(this.artifact.fsPath);
        if (target && path.resolve(target.folder.uri.fsPath) !== path.resolve(this.folder.uri.fsPath)) {
            this.folder = target.folder;
            this.artifactRel = toPosixRelative(this.folder.uri.fsPath, this.artifact.fsPath);
        }
        this.sourceChanged();
    }
    private async validate(raw: unknown, baseline?: Record<string, string>): Promise<ValidationResult | undefined> {
        const previous = this.validationTail;
        let release!: () => void;
        this.validationTail = new Promise<void>(resolve => { release = resolve; });
        await previous;
        if (this.disposed) {
            release();
            return undefined;
        }
        try {
            // The artifact is an MLView file under any name: a link or alias of it is never fingerprinted.
            return await this.validator(raw, this.folder.uri.fsPath, baseline ? { baseline, ownedFiles: [this.artifact.fsPath] } : { ownedFiles: [this.artifact.fsPath] });
        }
        finally {
            release();
        }
    }
    async reload(): Promise<void> {
        await this.scheduler.immediate();
    }
    /** Read the artifact from disk, parse it and validate it (contract 1a candidate read). */
    private async readCandidate(): Promise<ParsedCandidate | undefined> {
        const read = await this.io.readArtifact(this.artifact.fsPath);
        if (read.kind === 'missing')
            return { kind: 'missing' };
        if (read.kind === 'unreadable')
            return read.transient ? { kind: 'unreadable', detail: read.detail, transient: true } : { kind: 'unreadable', detail: read.detail };
        let text: string;
        try {
            text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(read.bytes);
        }
        catch {
            return { kind: 'parse', detail: 'the file is not valid UTF-8' };
        }
        let value: unknown;
        try {
            // A leading byte-order mark is kept and fails, exactly as it does for the helper.
            value = JSON.parse(text);
        }
        catch (error) {
            // V8's message quotes part of the file, which may hold newlines or invisible text.
            return { kind: 'parse', detail: displayText(error instanceof Error ? error.message : 'invalid JSON') };
        }
        // The helper refuses JSON nested this deeply (no WorkflowDocument needs it), so no revision
        // in such a file can be a parent.
        if (jsonDepth(value) > MAX_JSON_DEPTH)
            return { kind: 'parse', detail: 'the JSON is nested too deeply' };
        const ident = lenientRevision(value);
        let sem: string;
        let full: string;
        try {
            sem = semanticJson(value);
            full = canonicalJson(value);
        }
        catch {
            return { kind: 'parse', detail: 'the JSON is nested too deeply' };
        }
        const displayed = this.lineage.displayed;
        const baseline = ident && displayed && ident.id === displayed.id && sem === displayed.sem && !displayed.verified ? displayed.baseline : undefined;
        let result: ValidationResult;
        try {
            const validated = await this.validate(value, baseline);
            if (!validated)
                return undefined;
            result = validated;
        }
        catch (error) {
            const code = (error as NodeJS.ErrnoException | undefined)?.code;
            result = { issues: [{ path: '$', message: `validation failed (${typeof code === 'string' ? code : 'error'})` }] };
        }
        // The structural check only decides which extra files to watch. A throw here must not turn a
        // readable revision (whose valid revision.id the helper accepts as a parent) into
        // "unreadable" (LINEAGE2-2).
        let structural: ParsedStructure;
        if (result.value)
            structural = result.value.document;
        else {
            try {
                structural = validateWorkflowStructure(value).document;
            }
            catch {
                structural = undefined;
            }
        }
        return { kind: 'json', ident, sem, full, result, structural };
    }
    private async runReload(): Promise<void> {
        if (this.disposed)
            return;
        const generation = this.reloads.begin();
        let candidate: ParsedCandidate | undefined;
        try {
            candidate = await this.readCandidate();
        }
        catch (error) {
            // Never leave the checking status (or a blank panel) behind: report the file as unreadable.
            this.log.warn(`authored reload failed: ${error instanceof Error ? error.message : String(error)}`);
            candidate = { kind: 'unreadable', detail: 'the viewer could not process it' };
        }
        // A discarded run changes no lineage state; the newer run re-reads the file.
        if (!candidate || this.disposed || !this.reloads.isCurrent(generation))
            return;
        await this.apply(candidate);
    }
    private async apply(candidate: ParsedCandidate): Promise<void> {
        const observation = this.lineage.observe(candidate);
        const verdict = observation.verdict;
        this.pendingCheck = false;
        const displayed = this.lineage.displayed;
        this.lineageNote = observation.lineageNote && displayed
            ? { code: 'lineage', text: `Showing revision ${displayed.id}, which does not directly follow revision ${observation.lineageNote.from} last read from the artifact file (for example after a quick second publish or a restore).` }
            : undefined;
        const value = candidate.kind === 'json' ? candidate.result.value : undefined;
        let candidateTracked: string[] = [];
        let candidateFiles: string[] = [];
        if (verdict === 'adopt' || verdict === 'refresh') {
            this.rejection = undefined;
            this.lastValid = value;
        }
        else {
            this.rejection = this.rejectionFor(candidate, verdict);
            this.log.warn(`authored artifact ${this.artifactRel} rejected (${this.rejection.code})`);
            // A structurally valid candidate can be repaired by editing its sources: watch them too.
            if (candidate.kind === 'json' && candidate.structural) {
                candidateTracked = trackedFiles(candidate.structural);
                candidateFiles = value?.files ?? [];
            }
        }
        await this.rebuildDependencies(candidateTracked, candidateFiles);
        await this.computeDirty();
        this.rootHint = await this.computeRootHint();
        if (this.disposed)
            return;
        if (verdict === 'adopt' && this.lastValid && candidate.kind === 'json') {
            const document = this.lastValid.document;
            this.panel.title = `MLView: ${document.title}`;
            if (this.ready) {
                this.postBanner(true, true);
                this.post({ v: 1, type: 'workflow', document });
                this.lastPostedFull = candidate.full;
            }
            const staleFiles = this.lastValid.stale;
            const toastKey = `${document.revision.id}\n${staleFiles.map(s => `${s.reason}:${s.rel}`).join('\n')}`;
            if (this.rootHint)
                this.showRootHintToast(this.rootHint, document.revision.id);
            else if (staleFiles.length && toastKey !== this.lastStaleToast) {
                this.lastStaleToast = toastKey;
                void vscode.window.showWarningMessage(staleToastText(staleFiles));
            }
        }
        else if (verdict === 'refresh' && this.lastValid && candidate.kind === 'json' && this.ready && candidate.full !== this.lastPostedFull) {
            // Same semantic content; re-post only when the verification block changed.
            this.post({ v: 1, type: 'workflow', document: this.lastValid.document });
            this.lastPostedFull = candidate.full;
        }
        this.postStale();
        this.postBanner();
        if (candidate.kind === 'unreadable' && candidate.transient)
            this.scheduleRetry();
        else
            this.retryCount = 0;
    }
    /**
     * The stale cited and inspected files of the displayed revision, each with its reason, so the
     * webview can mark the cards, connections, findings and quotes that cite them. Posted after
     * the workflow frame, only when the set changed for this page. A file the root hint found
     * unchanged in another folder is sent as `elsewhere`, so the webview does not call it changed
     * or missing while the notice says it did not change (COPY-1).
     */
    private postStale(): void {
        if (!this.ready || this.disposed)
            return;
        const elsewhere = new Set(this.rootHint?.files ?? []);
        const files = (this.lastValid?.stale ?? []).map(s => ({ path: s.rel, reason: elsewhere.has(s.rel) ? 'elsewhere' : s.reason }));
        const key = JSON.stringify(files);
        if (key === (this.lastPostedStale ?? '[]'))
            return;
        this.lastPostedStale = key;
        this.post({ v: 1, type: 'stale', files });
    }
    /** A root hint for the displayed revision, or undefined (see `findRootHint`). */
    private async computeRootHint(): Promise<RootHint | undefined> {
        const shown = this.lastValid;
        const published = shown?.document.verification?.files;
        if (!shown || !published || !shown.stale.length)
            return undefined;
        try {
            return await findRootHint({
                tracked: trackedFiles(shown.document),
                published,
                stale: shown.stale,
                artifact: this.artifact.fsPath,
                root: this.folder.uri.fsPath,
                limit: MAX_SOURCE_BYTES,
                readBytes: readSourceBytes
            });
        }
        catch {
            return undefined;
        }
    }
    /** Once per revision and folder: the hint as a notification with the same two actions as the panel. */
    private showRootHintToast(hint: RootHint, revisionId: string): void {
        const key = `${revisionId}\n${hint.base}\n${hint.root}`;
        if (key === this.lastHintToast)
            return;
        this.lastHintToast = key;
        void Promise.resolve(vscode.window.showInformationMessage(`MLView: ${rootHintText(hint, listFiles)}`, ADD_FOLDER, OPEN_FOLDER)).then(choice => {
            if (choice === ADD_FOLDER)
                return this.workspaceHintAction('add');
            if (choice === OPEN_FOLDER)
                return this.workspaceHintAction('open');
            return undefined;
        }).catch(error => this.log.warn(`root hint action failed: ${error instanceof Error ? error.message : String(error)}`));
    }
    /**
     * The root hint's two actions. The folder comes from the host's own hint, never from the
     * webview message, and nothing here changes what validation reads: a new folder takes effect
     * through `foldersChanged`, in the panel reopened after an extension host restart, or in the
     * new window.
     */
    private async workspaceHintAction(action: 'add' | 'open'): Promise<void> {
        const hint = this.rootHint;
        if (this.disposed || !hint)
            return;
        const uri = vscode.Uri.file(hint.base);
        if (action === 'open') {
            await vscode.commands.executeCommand('vscode.openFolder', uri, { forceNewWindow: true });
            return;
        }
        const folders = vscode.workspace.workspaceFolders ?? [];
        if (folders.some(folder => path.resolve(folder.uri.fsPath) === path.resolve(hint.base))) {
            this.foldersChanged();
            return;
        }
        // A single-folder window becomes an untitled multi-root workspace, and VS Code restarts the
        // extension host (this extension too) and leaves this panel's tab dead: save the reopen
        // note first (see `REOPEN_STATE_KEY`). A multi-root window keeps its extension host, and
        // `foldersChanged` validates in place.
        const restarts = vscode.workspace.workspaceFile === undefined;
        if (restarts)
            await this.restartNotes.note(hint.base);
        // Appended, so the first folder is left alone.
        if (!vscode.workspace.updateWorkspaceFolders(folders.length, 0, { uri })) {
            if (restarts)
                await this.restartNotes.forget();
            void vscode.window.showWarningMessage('MLView: VS Code did not add the folder to the workspace.');
        }
    }
    private scheduleRetry(): void {
        if (this.disposed || this.retryTimer !== undefined || this.retryCount >= RETRY_DELAYS_MS.length)
            return;
        const delay = RETRY_DELAYS_MS[this.retryCount++]!;
        this.retryTimer = setTimeout(() => {
            this.retryTimer = undefined;
            void this.reload();
        }, delay);
    }
    private cancelRetry(): void {
        if (this.retryTimer !== undefined) {
            clearTimeout(this.retryTimer);
            this.retryTimer = undefined;
        }
    }
    private rejectionPrefix(): string {
        return this.lineage.displayed
            ? 'Generated diagram update rejected; retaining the last valid revision.'
            : 'Generated diagram update rejected; nothing valid can be displayed yet.';
    }
    private rejectionFor(candidate: Candidate, verdict: Verdict): BannerItem {
        const P = this.rejectionPrefix();
        if (candidate.kind === 'missing')
            return { code: 'missing', text: `${P}\nThe artifact file does not exist. Restore it, or ask the assistant for a new analysis.` };
        if (candidate.kind === 'unreadable')
            return { code: 'unreadable', text: `${P}\nThe artifact could not be read: ${candidate.detail}.` };
        if (candidate.kind === 'parse')
            return { code: 'parse', text: `${P}\nJSON parse error: ${candidate.detail}` };
        const D = this.lineage.displayed?.id ?? '';
        if (verdict === 'obsolete')
            return { code: 'obsolete', text: `${P}\nThe artifact file holds revision ${candidate.ident?.id ?? ''}, which the displayed revision ${D} already superseded (for example, it was restored from version control). Run MLView: Open Generated Diagram to show the file's revision instead.` };
        if (verdict === 'same-id-changed')
            return { code: 'same-id-changed', text: `${P}\nRevision ${D} changed content without a new revision id. Run MLView: Open Generated Diagram to show the file as it is.` };
        const issues: ValidationIssue[] = candidate.result.issues;
        const heading = candidate.ident ? `\nRevision ${candidate.ident.id} cannot be displayed:` : '\nThe artifact cannot be displayed:';
        // Issue paths can carry arbitrary artifact key text: one bounded, escaped line each.
        const lines = issues.slice(0, 8).map(issue => `\n${displayIssue(issue)}`).join('');
        const more = issues.length > 8 ? `\n…and ${issues.length - 8} more` : '';
        return { code: 'invalid', text: `${P}${heading}${lines}${more}` };
    }
    private banner(): { message: string; codes: string[] } {
        const items: BannerItem[] = [];
        const displayed = this.lineage.displayed;
        if (this.pendingCheck) {
            items.push({
                code: 'checking',
                text: displayed
                    ? 'Changes detected; checking diagram freshness. The last valid revision remains visible while validation catches up.'
                    : 'Changes detected; checking the artifact again.'
            });
        }
        else {
            if (this.rejection)
                items.push(this.rejection);
            if (this.lineageNote)
                items.push(this.lineageNote);
            // Campaign 3, issue 21: worded from each file's reason ("1 changed, 1 missing"), so a
            // deleted cited file is no longer reported as "changed".
            const stale = this.lastValid?.stale ?? [];
            // The parent-folder case: the files did not change, the root is wrong. The stale
            // wording ("no longer match", "ask the assistant") would be false here.
            if (displayed && stale.length && this.rootHint)
                items.push({ code: 'root-hint', text: rootHintText(this.rootHint, listFiles) });
            else if (displayed && stale.length)
                items.push({ code: 'stale', text: staleBannerText(stale, displayed.id, listFiles) });
            if (this.dirty.length)
                items.push({ code: 'dirty', text: `Unsaved editor changes in ${listFiles(this.dirty)} are not checked; freshness uses the saved files. A jump is blocked when the unsaved text no longer contains the cited lines.` });
        }
        return { message: items.map(x => x.text).join('\n'), codes: items.map(x => x.code) };
    }
    /** Post the status banner when it changed (or always, with `force`); `clear` posts an empty banner. */
    private postBanner(force = false, clear = false): void {
        if (!this.ready || this.disposed)
            return;
        const { message, codes } = clear ? { message: '', codes: [] as string[] } : this.banner();
        if (!force && message === this.lastPostedBanner)
            return;
        this.lastPostedBanner = message;
        this.post({ v: 1, type: 'workflowError', message, retained: this.lineage.displayed !== null, codes });
    }
    private async rebuildDependencies(candidateTracked: readonly string[], candidateFiles: readonly string[]): Promise<void> {
        const root = this.folder.uri.fsPath;
        const deps = new DependencySet();
        deps.addPath(this.artifact.fsPath);
        if (this.lastValid) {
            for (const rel of trackedFiles(this.lastValid.document))
                deps.add(rel, root);
            for (const real of this.lastValid.files)
                deps.addPath(real);
        }
        await Promise.all(candidateTracked.map(async rel => {
            let real: string | undefined;
            try {
                real = await fs.realpath(path.resolve(root, rel));
            }
            catch { }
            deps.add(rel, root, real);
        }));
        for (const real of candidateFiles)
            deps.addPath(real);
        this.dependencies = deps;
    }
    /** dirty = tracked(D) ∪ {artifact} files that have an open, dirty editor with the same identity. */
    private async computeDirty(): Promise<void> {
        const version = ++this.dirtyVersion;
        const dirtyDocuments = [
            ...vscode.workspace.textDocuments.filter(d => d.uri.scheme === 'file' && d.isDirty).map(d => d.uri.fsPath),
            ...vscode.workspace.notebookDocuments.filter(n => n.uri.scheme === 'file' && n.isDirty).map(n => n.uri.fsPath)
        ];
        let result: string[] = [];
        if (dirtyDocuments.length) {
            const open = new Set(await Promise.all(dirtyDocuments.map(p => identity(p))));
            const root = this.folder.uri.fsPath;
            const rels = [...(this.lastValid ? trackedFiles(this.lastValid.document) : []), this.artifactRel];
            const ids = await Promise.all(rels.map(rel => identity(path.resolve(root, rel))));
            result = rels.filter((_, i) => open.has(ids[i]!));
        }
        if (version === this.dirtyVersion)
            this.dirty = result;
    }
    private actionResult(requestId: string | undefined, action: 'exportFile' | 'copy' | 'refineWorkflow', outcome: 'done' | 'cancelled' | 'failed', extra: { message?: string; name?: string } = {}): void {
        if (requestId)
            this.post({ v: 1, type: 'actionResult', requestId, action, outcome, ...extra });
    }
    private async message(raw: unknown): Promise<void> {
        if (!raw || typeof raw !== 'object')
            return;
        const m = raw as Record<string, unknown>;
        if (m.v !== 1 || typeof m.type !== 'string')
            return;
        const requestId = typeof m.requestId === 'string' && REQUEST_ID.test(m.requestId) ? m.requestId : undefined;
        if (m.type === 'ready') {
            this.ready = true;
            this.post({
                v: 1,
                type: 'init',
                theme: themeKindOf(vscode.window.activeColorTheme.kind),
                capabilities: {
                    canOpenSource: true,
                    canReanalyze: false,
                    // The shared viewer's canExport flag controls its host-side HTML
                    // report action. Authored panels save SVG/PNG through the independent
                    // export menu and exportFile protocol, so keep that unsupported action hidden.
                    canExport: false,
                    canAskAssistant: false,
                    canRefine: true
                },
                artifact: this.artifact.fsPath
            });
            if (this.lastValid) {
                this.post({ v: 1, type: 'workflow', document: this.lastValid.document });
                this.lastPostedFull = this.lineage.displayed?.full;
            }
            // A new page starts with no stale marks.
            this.lastPostedStale = undefined;
            this.postStale();
            const { message, codes } = this.banner();
            this.lastPostedBanner = message;
            if (message)
                this.post({ v: 1, type: 'workflowError', message, retained: this.lineage.displayed !== null, codes });
            return;
        }
        if (m.type === 'openLocation') {
            await this.openEvidence(m);
            return;
        }
        if (m.type === 'workspaceHint') {
            if (m.action === 'add' || m.action === 'open')
                await this.workspaceHintAction(m.action);
            return;
        }
        if (m.type === 'refineWorkflow') {
            await this.copyRefinementPrompt(m, requestId);
            return;
        }
        if (m.type === 'copy') {
            await this.copyText(m, requestId);
            return;
        }
        if (m.type === 'exportFile') {
            const parsed = parseExportFileMessage(raw);
            if (!parsed) {
                this.log.warn('ignored a malformed exportFile message');
                this.actionResult(requestId, 'exportFile', 'failed', { message: 'the export request was malformed' });
                return;
            }
            const result = await saveExportedFile(parsed, { log: this.log, workspaceRoot: () => this.folder.uri.fsPath });
            if (result.outcome === 'done')
                this.actionResult(requestId, 'exportFile', 'done', { name: result.name });
            else if (result.outcome === 'failed')
                this.actionResult(requestId, 'exportFile', 'failed', { message: result.message });
            else
                this.actionResult(requestId, 'exportFile', 'cancelled');
        }
    }
    private async copyText(m: Record<string, unknown>, requestId: string | undefined): Promise<void> {
        const text = m.text;
        if (typeof text !== 'string' || text.length === 0) {
            this.actionResult(requestId, 'copy', 'failed', { message: 'nothing to copy' });
            return;
        }
        if (text.length > MAX_EXPORT_BYTES || Buffer.byteLength(text) > MAX_EXPORT_BYTES) {
            this.actionResult(requestId, 'copy', 'failed', { message: 'the text is too large to copy' });
            return;
        }
        try {
            await vscode.env.clipboard.writeText(text);
        }
        catch {
            this.actionResult(requestId, 'copy', 'failed', { message: 'the clipboard refused the text' });
            return;
        }
        this.actionResult(requestId, 'copy', 'done');
    }
    private refuseRefinement(requestId: string | undefined, warning: string): void {
        void vscode.window.showWarningMessage(warning);
        this.actionResult(requestId, 'refineWorkflow', 'failed', { message: warning.replace(/^MLView: /, '') });
    }
    private async copyRefinementPrompt(m: Record<string, unknown>, requestId: string | undefined): Promise<void> {
        await this.computeDirty();
        this.postBanner();
        const doc = this.lastValid?.document;
        if (!doc)
            return this.refuseRefinement(requestId, 'MLView: no valid workflow revision is available to refine.');
        if (typeof m.revisionId !== 'string' || !ID_PATTERN.test(m.revisionId) || m.revisionId !== doc.revision.id)
            return this.refuseRefinement(requestId, `MLView: refinement request is stale; the displayed revision is now ${doc.revision.id}. Select the item again.`);
        const intent = typeof m.intent === 'string' && (REFINE_INTENTS as readonly string[]).includes(m.intent) ? m.intent as RefineIntent : undefined;
        if (!intent)
            return this.refuseRefinement(requestId, 'MLView: unknown refinement intent.');
        let customText: string | undefined;
        if (intent === 'custom') {
            customText = typeof m.customText === 'string' ? m.customText.trim() : '';
            if (customText.length < 1 || customText.length > 500)
                return this.refuseRefinement(requestId, 'MLView: provide a refinement request between 1 and 500 characters.');
        }
        let selection: RefineSelection | undefined;
        if (m.selection !== undefined && m.selection !== null) {
            const candidate = m.selection as Record<string, unknown>;
            if (typeof m.selection !== 'object' || Array.isArray(m.selection) || typeof candidate.kind !== 'string' || !['node', 'edge', 'issue'].includes(candidate.kind) || typeof candidate.id !== 'string' || !ID_PATTERN.test(candidate.id))
                return this.refuseRefinement(requestId, 'MLView: the selection is invalid. Select the item again.');
            selection = { kind: candidate.kind as RefineSelection['kind'], id: candidate.id };
            const present = selection.kind === 'node' ? doc.nodes.some(x => x.id === selection!.id) : selection.kind === 'edge' ? doc.edges.some(x => x.id === selection!.id) : doc.findings.some(x => x.id === selection!.id);
            if (!present) {
                const word = selection.kind === 'issue' ? 'finding' : selection.kind;
                return this.refuseRefinement(requestId, `MLView: selected ${word} ${selection.id} is no longer in revision ${doc.revision.id}.`);
            }
        }
        const head = this.lineage.diskHead;
        if (!head || head.kind === 'missing')
            return this.refuseRefinement(requestId, 'MLView: the artifact file is missing, so there is nothing to refine. Restore it (for example from version control) or ask the assistant for a new analysis.');
        if (head.kind !== 'revision') {
            const detail = head.kind === 'bad-revision' ? 'it has no valid revision.id' : head.detail || 'it has no valid revision.id';
            return this.refuseRefinement(requestId, `MLView: the artifact file cannot be read right now (${detail}); the MLView helper refuses to publish over it. Repair or restore ${displayText(this.artifactRel, 200)} first.`);
        }
        const prompt = buildRefinementPrompt({
            artifactRel: this.artifactRel,
            displayed: doc,
            diskHead: head,
            intent,
            ...(customText !== undefined ? { customText } : {}),
            ...(selection ? { selection } : {}),
            stale: this.lastValid!.stale.map(s => s.rel),
            dirty: [...this.dirty],
            trusted: vscode.workspace.isTrusted !== false
        });
        try {
            await vscode.env.clipboard.writeText(prompt);
        }
        catch {
            return this.refuseRefinement(requestId, 'MLView: the clipboard refused the refinement prompt.');
        }
        const note = head.id !== doc.revision.id ? ` The diagram shows revision ${doc.revision.id}; the artifact file holds revision ${head.id}, so the prompt continues from ${head.id}.` : '';
        void vscode.window.showInformationMessage(`MLView refinement prompt copied. Paste it into the assistant that authored this diagram.${note}`);
        this.actionResult(requestId, 'refineWorkflow', 'done');
    }
    private async openEvidence(m: Record<string, unknown>): Promise<void> {
        const id = typeof m.evidenceId === 'string' ? m.evidenceId : undefined;
        // `focus: true` is the explicit "open and go to the editor" gesture; every other open keeps
        // the keyboard on the diagram.
        const focus = m.focus === true;
        const shown = this.lastValid;
        const evidence = shown?.document.evidence.find(x => x.id === id);
        if (!shown || !evidence)
            return;
        const jump: Jump = { revision: shown.document.revision.id, freshness: this.freshnessVersion, seq: ++this.jumpSeq };
        let behind = false;
        try {
            await this.jumpTo(evidence, shown, jump, focus, () => { behind = true; });
        }
        finally {
            // The jump's own check found files the panel has not caught up with (no watcher event
            // yet): validate the panel again, after this jump has been decided.
            if (behind)
                this.sourceChanged();
        }
    }
    private async jumpTo(evidence: WorkflowEvidence, shown: ValidatedWorkflow, jump: Jump, focus: boolean, markBehind: () => void): Promise<void> {
        let fresh: ValidatedWorkflow;
        if (await this.unchangedSinceValidation(shown, evidence)) {
            // The cited file's bytes are the ones the displayed revision was validated against, so
            // the quote still matches: no full revalidation for this jump.
            if (!this.navigationCurrent(jump))
                return;
            fresh = shown;
        }
        else {
            const displayed = this.lineage.displayed;
            let result: ValidationResult | undefined;
            try {
                result = await this.validate(shown.document, displayed && !displayed.verified ? displayed.baseline : undefined);
            }
            catch {
                result = { issues: [{ path: '$', message: 'validation failed' }] };
            }
            if (!result || !this.navigationCurrent(jump))
                return;
            if (!result.value) {
                const first = result.issues[0];
                void vscode.window.showWarningMessage(`MLView: evidence ${evidence.id} could not be checked (${first ? displayIssue(first) : 'unknown problem'}); source navigation was stopped.`);
                return;
            }
            fresh = result.value;
            if (JSON.stringify(fresh.stale) !== JSON.stringify(shown.stale))
                markBehind();
        }
        const staleFile = fresh.stale.find(s => s.rel === evidence.file);
        if (staleFile) {
            const hint = this.rootHint;
            void vscode.window.showWarningMessage(hint && hint.files.includes(evidence.file)
                ? rootHintJumpText(evidence.id, displayText(evidence.file, 200), hint, listFiles)
                : staleJumpText(evidence.id, displayText(evidence.file, 200), staleFile.reason, jump.revision));
            return;
        }
        const open = await this.findOpenDocument(evidence);
        if (!this.navigationCurrent(jump))
            return;
        if (!this.unsavedTextStillCites(evidence, open)) {
            void vscode.window.showWarningMessage(`MLView: unsaved changes in ${displayText(evidence.file, 200)} no longer contain the lines cited by evidence ${evidence.id}; save or revert the file, then try again.`);
            return;
        }
        await this.navigate(evidence, jump, open, focus);
    }
    /**
     * True when the cited file is fresh in the displayed revision's last validation and its bytes
     * on disk still hash to what that validation read. Reads one file instead of every tracked
     * file (KI-09: a full validation on every jump). Any doubt answers false, and the caller runs
     * the full validation as before.
     */
    private async unchangedSinceValidation(shown: ValidatedWorkflow, evidence: WorkflowEvidence): Promise<boolean> {
        if (shown.stale.some(s => s.rel === evidence.file))
            return false;
        if (!Object.prototype.hasOwnProperty.call(shown.fingerprints, evidence.file))
            return false;
        const expected = shown.fingerprints[evidence.file];
        try {
            const real = await fs.realpath(path.resolve(this.folder.uri.fsPath, evidence.file));
            if (!shown.files.includes(real))
                return false;
            const bytes = await readSourceBytes(real, MAX_SOURCE_BYTES);
            return createHash('sha256').update(bytes).digest('hex') === expected;
        }
        catch {
            return false;
        }
    }
    /** The open editor document for the evidence file, matched by file identity (realpath, win32 case-folded). */
    private async findOpenDocument(e: WorkflowEvidence): Promise<{ text?: vscode.TextDocument; notebook?: vscode.NotebookDocument }> {
        const target = await identity(path.resolve(this.folder.uri.fsPath, e.file));
        if (e.cell !== undefined) {
            for (const notebook of vscode.workspace.notebookDocuments)
                if (notebook.uri.scheme === 'file' && await identity(notebook.uri.fsPath) === target)
                    return { notebook };
            return {};
        }
        for (const text of vscode.workspace.textDocuments)
            if (text.uri.scheme === 'file' && await identity(text.uri.fsPath) === target)
                return { text };
        return {};
    }
    private unsavedTextStillCites(e: WorkflowEvidence, open: { text?: vscode.TextDocument; notebook?: vscode.NotebookDocument }): boolean {
        if (open.text?.isDirty)
            return quoteMatches(e.quote, open.text.getText().split(/\r\n|\r|\n/), e.line, e.endLine);
        if (open.notebook?.isDirty && e.cell !== undefined) {
            // cellAt clamps its index in VS Code, so check the count first.
            if (e.cell >= open.notebook.cellCount)
                return false;
            return quoteMatches(e.quote, open.notebook.cellAt(e.cell).document.getText().split(/\r\n|\r|\n/), e.line, e.endLine);
        }
        return true;
    }
    /** The jump may still act: same revision and freshness, and no newer jump has started. */
    private navigationCurrent(jump: Jump): boolean {
        return !this.disposed && this.lastValid?.document.revision.id === jump.revision && this.freshnessVersion === jump.freshness && this.jumpSeq === jump.seq;
    }
    private navigationColumn(document: vscode.TextDocument, notebook?: vscode.NotebookDocument): vscode.ViewColumn {
        const sameUri = (left: vscode.Uri, right: vscode.Uri): boolean => left.toString() === right.toString();
        const visibleDocument = vscode.window.visibleTextEditors.find(editor => sameUri(editor.document.uri, document.uri) && editor.viewColumn !== undefined);
        if (visibleDocument?.viewColumn !== undefined)
            return visibleDocument.viewColumn;
        const visibleNotebook = notebook && vscode.window.visibleNotebookEditors.find(editor => sameUri(editor.notebook.uri, notebook.uri) && editor.viewColumn !== undefined);
        if (visibleNotebook?.viewColumn !== undefined)
            return visibleNotebook.viewColumn;
        const sourceEditor = [vscode.window.activeTextEditor, ...vscode.window.visibleTextEditors]
            .find(editor => editor?.viewColumn !== undefined && editor.viewColumn !== this.panel.viewColumn);
        return sourceEditor?.viewColumn ?? vscode.ViewColumn.Beside;
    }
    /**
     * Open the cited source beside the panel, select the whole cited range and highlight it.
     * `focus` false (the default gesture) keeps the keyboard on the diagram.
     */
    private async navigate(e: WorkflowEvidence, jump: Jump, open: { text?: vscode.TextDocument; notebook?: vscode.NotebookDocument }, focus: boolean): Promise<void> {
        const uri = open.notebook?.uri ?? open.text?.uri ?? vscode.Uri.file(path.join(this.folder.uri.fsPath, e.file));
        const start = toEditorLine(e.line), end = toEditorLine(e.endLine);
        if (e.cell !== undefined) {
            await this.navigateCell(e.cell, uri, start, end, jump, focus);
            return;
        }
        const doc = await vscode.workspace.openTextDocument(uri);
        if (!this.navigationCurrent(jump))
            return;
        const editor = await vscode.window.showTextDocument(doc, { preview: true, preserveFocus: !focus, viewColumn: this.navigationColumn(doc) });
        if (!this.navigationCurrent(jump))
            return;
        this.showRange(editor, citedRange(doc, start, end));
    }
    /**
     * A notebook citation: show the notebook with the cited cell selected and revealed, then
     * select and highlight the cited lines in that cell's editor. VS Code creates a cell's editor
     * only once the cell is drawn; when it does not appear in time, the cell stays selected and
     * revealed without the line highlight.
     */
    private async navigateCell(index: number, uri: vscode.Uri, start: number, end: number, jump: Jump, focus: boolean): Promise<void> {
        const notebook = await vscode.workspace.openNotebookDocument(uri);
        if (!this.navigationCurrent(jump))
            return;
        // VS Code clamps cellAt's index, so a removed cell must be detected by count.
        if (index >= notebook.cellCount) {
            void vscode.window.showWarningMessage(`MLView: notebook cell ${index} no longer exists.`);
            return;
        }
        const cell = notebook.cellAt(index);
        const cells = new vscode.NotebookRange(index, index + 1);
        const notebookEditor = await vscode.window.showNotebookDocument(notebook, { preview: true, preserveFocus: !focus, viewColumn: this.navigationColumn(cell.document, notebook), selections: [cells] });
        if (!this.navigationCurrent(jump))
            return;
        notebookEditor.revealRange(cells, vscode.NotebookEditorRevealType.InCenterIfOutsideViewport);
        const cellEditor = await visibleEditorFor(cell.document, CELL_EDITOR_WAIT_MS);
        // A newer jump may have started during the wait: it owns the selection and the highlight.
        if (!this.navigationCurrent(jump))
            return;
        if (cellEditor)
            this.showRange(cellEditor, citedRange(cell.document, start, end));
        else
            this.clearHighlight();
    }
    /** Select the whole range, reveal it, and move the highlight to it. */
    private showRange(editor: vscode.TextEditor, range: vscode.Range): void {
        editor.selection = new vscode.Selection(range.start, range.end);
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
        this.clearHighlight();
        this.highlight = vscode.window.createTextEditorDecorationType(HIGHLIGHT_STYLE());
        editor.setDecorations(this.highlight, [range]);
    }
    private clearHighlight(): void {
        this.highlight?.dispose();
        this.highlight = undefined;
    }
    private post(message: unknown): void {
        if (!this.disposed)
            void this.panel.webview.postMessage(message);
    }
    /**
     * The inline bootstrap owns the host handshake: it alone posts `ready`, stashes the `init`
     * theme and capabilities on the bridge before the viewer mounts, mounts on the first
     * `workflow`, and shows `workflowError` banners until then, in a `<pre>`. After the mount the
     * viewer's own listener applies every later frame, and draws the banner itself.
     */
    private render(): void { const nonce = createNonce(); const script = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.js')); const style = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.css')); this.panel.webview.html = `<!doctype html><html><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this.panel.webview.cspSource} data:; style-src ${this.panel.webview.cspSource}; script-src 'nonce-${nonce}' ${this.panel.webview.cspSource};"><link rel="stylesheet" href="${style}"></head><body><div id="mlview-root"></div><script nonce="${nonce}" src="${script}"></script><script nonce="${nonce}">(function(){var root=document.getElementById('mlview-root');var bridge=window.MLView.bridges.vscode();var save=bridge.saveState.bind(bridge);var artifact=null;bridge.saveState=function(state){save(Object.assign({},state,{artifact:artifact}));};var app=null;bridge.onMessage(function(m){if(!m||m.v!==1)return;if(m.type==='init'){if(typeof m.artifact==='string'){artifact=m.artifact;bridge.saveState(bridge.loadState()||{});}if(!app){if(m.theme)bridge.theme=m.theme;if(m.capabilities)bridge.capabilities=m.capabilities;}return;}if(m.type==='theme'){if(!app&&m.kind)bridge.theme=m.kind;return;}if(m.type==='workflow'){if(!app&&m.document)app=window.MLView.mountWorkflow(root,m.document,bridge);return;}if(m.type==='workflowError'){var e=document.getElementById('mlview-authored-error');if(app||!m.message){if(e)e.remove();return;}if(!e){e=document.createElement('pre');e.id='mlview-authored-error';e.setAttribute('role','status');root.prepend(e);}e.textContent=m.message;}});bridge.post({v:1,type:'ready'});}());</script></body></html>`; }
    dispose(): void {
        if (this.disposed)
            return;
        this.disposed = true;
        this.scheduler.dispose();
        this.cancelRetry();
        this.clearHighlight();
        if (this.dirtyTimer !== undefined) {
            clearTimeout(this.dirtyTimer);
            this.dirtyTimer = undefined;
        }
        for (const d of this.disposables)
            d.dispose();
        this.onDispose();
    }
}
