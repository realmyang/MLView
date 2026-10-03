import { createHash } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { blockedOpenText, createNonce, findRootHint, hintFolderName, rootHintJumpText, rootHintText, staleBannerText, staleJumpText, staleToastText, themeKindOf, toEditorLine, type OpenBlockReason, type RootHint } from './authoredSupport';
import { MAX_EXPORT_BYTES, parseExportFileMessage, saveExportedFile } from './exportDiagram';
import { CitationIndex, type ClaimRef } from './citationIndex';
import { DependencySet, identity } from './fileIdentity';
import type { Logger } from './log';
import { buildRefinementPrompt, REFINE_INTENTS, toPosixRelative, type RefineIntent, type RefineSelection } from './refinePrompt';
import { displayIssue, displayText } from './displayText';
import { RevealInDiagram, type CitationState, type EditorPlace, type RevealPanel } from './revealCommand';
import { canonicalJson, jsonDepth, lenientRevision, MAX_JSON_DEPTH, RevisionLineage, semanticJson, type Candidate, type Verdict } from './revisionLineage';
import { ID_PATTERN, MAX_DOCUMENT_BYTES, MAX_SOURCE_BYTES, quoteMatches, readSourceBytes, trackedFiles, validateWorkflow, validateWorkflowStructure, type StaleFile, type ValidatedWorkflow, type ValidationIssue, type WorkflowEvidence } from './workflowDocument';
export const AUTHORED_VIEW_TYPE = 'mlview.authoredDiagram';
export const OPEN_AUTHORED_COMMAND = 'mlview.openGeneratedDiagram';
const RELOAD_DEBOUNCE_MS = 120;
const DIRTY_THROTTLE_MS = 150;
const RETRY_DELAYS_MS = [250, 1000, 4000];
const TRANSIENT_CODES = new Set(['EBUSY', 'EAGAIN', 'EPERM', 'EACCES', 'EMFILE', 'ENFILE']);
const REQUEST_ID = /^[A-Za-z0-9_-]{1,64}$/;
/**
 * Viewer M3 (step 14): a reveal the page may not have received (it was hidden, so VS Code discarded
 * it, or it was reloading) is posted again after the page's next `ready`, if that comes this soon.
 */
export const REVEAL_REPLAY_MS = 5000;
/** How long a jump into a notebook waits for VS Code to create the cited cell's editor. */
const CELL_EDITOR_WAIT_MS = 500;
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
 * Extension host restarts. VS Code restarts the extension host inside the same window for
 * "Developer: Restart Extension Host", for an extension install, update or removal that needs it,
 * when a single-folder window becomes an untitled multi-root workspace (the root hint's "Add
 * folder", "Workspaces: Add Folder to Workspace...") and when an untitled workspace is saved
 * ("Save Workspace As..."). The panels the old host drew keep their tabs, but nothing answers
 * them any more: VS Code calls a panel serializer only for the tabs it restores when a window
 * loads, never for a live panel after a restart (checked live in VS Code 1.139).
 *
 * So each host keeps a registry of the panels it has open, and the next host in the same window
 * puts each diagram back in its dead tab's place (`recoverAfterRestart`). The registry lives in
 * the global state, because a workspace change starts the new host with an empty workspace
 * state. The global state is shared by every window, so the registry is keyed by
 * `vscode.env.sessionId`, which stays the same across an extension host restart and changes when
 * the window reloads (a reload goes through the serializer instead) and between windows:
 * `{ [sessionId]: { at, panels: [{ artifact, title, column? }] } }`.
 */
export const OPEN_PANELS_KEY = 'mlview.openPanels';
/** Other sessions' entries unchanged for this long are dropped (a window reload leaves one behind). */
export const OPEN_PANELS_TTL_MS = 14 * 24 * 60 * 60 * 1000;
/** At most this many other sessions are kept, the most recently changed first. */
export const MAX_OTHER_SESSIONS = 20;
const MAX_RECORDED_PANELS = 50;
/**
 * How long the recovery waits, after activation and after a diagram tab comes to the front of its
 * group, before it calls that front tab dead: by then VS Code has revived a restored tab through
 * the serializer, and the panels' view states have caught up with the tabs.
 */
export const RECOVERY_SETTLE_MS = 500;
/**
 * The view type the tabs API reports for a panel tab. VS Code 1.139 reports it with a
 * `mainThreadWebview-` prefix; the bare form is accepted too, in case a later release drops it.
 */
const AUTHORED_TAB_VIEW_TYPES = new Set([AUTHORED_VIEW_TYPE, `mainThreadWebview-${AUTHORED_VIEW_TYPE}`]);
/** One open panel in the registry: its artifact, its tab's title and its editor group's column. */
interface PanelRecord {
    artifact: string;
    title: string;
    column?: number;
}
interface SessionRecord {
    /** When this session's entry last changed (ms since the epoch). */
    at: number;
    panels: PanelRecord[];
}
function parsePanelRecord(value: unknown): PanelRecord | undefined {
    if (!value || typeof value !== 'object')
        return undefined;
    const item = value as Record<string, unknown>;
    if (typeof item.artifact !== 'string' || typeof item.title !== 'string')
        return undefined;
    return typeof item.column === 'number' && Number.isInteger(item.column) && item.column > 0
        ? { artifact: item.artifact, title: item.title, column: item.column }
        : { artifact: item.artifact, title: item.title };
}
/** The registry read back from storage; malformed sessions and records are left out. */
function parseRegistry(value: unknown): Map<string, SessionRecord> {
    const registry = new Map<string, SessionRecord>();
    if (!value || typeof value !== 'object' || Array.isArray(value))
        return registry;
    for (const [session, raw] of Object.entries(value as Record<string, unknown>)) {
        const entry = raw as Record<string, unknown> | null;
        if (!entry || typeof entry !== 'object' || typeof entry.at !== 'number' || !Number.isFinite(entry.at) || !Array.isArray(entry.panels))
            continue;
        const panels = entry.panels.slice(0, MAX_RECORDED_PANELS).map(parsePanelRecord).filter((record): record is PanelRecord => record !== undefined);
        registry.set(session, { at: entry.at, panels });
    }
    return registry;
}
/**
 * Drop the other sessions' entries that have not changed for `OPEN_PANELS_TTL_MS` (or are dated
 * that far ahead, after a clock change), then all but the `MAX_OTHER_SESSIONS` most recent.
 */
function pruneRegistry(registry: Map<string, SessionRecord>, own: string, now: number): void {
    const others = [...registry].filter(([session, entry]) => {
        if (session === own)
            return false;
        if (Math.abs(now - entry.at) <= OPEN_PANELS_TTL_MS)
            return true;
        registry.delete(session);
        return false;
    });
    others.sort((a, b) => b[1].at - a[1].at);
    for (const [session] of others.slice(MAX_OTHER_SESSIONS))
        registry.delete(session);
}
const isAuthoredTab = (tab: vscode.Tab | undefined): tab is vscode.Tab => tab !== undefined && tab.input instanceof vscode.TabInputWebview && AUTHORED_TAB_VIEW_TYPES.has(tab.input.viewType);
/** What a panel tells its controller (see `OPEN_PANELS_KEY`). */
interface PanelHooks {
    /** The panel's title or column changed: update the registry. */
    changed(): void;
    /** Write the registry now; resolves once it is stored. */
    flush(): Promise<void>;
    /** Viewer M3 (step 14): the panel validated again; the cited-files context key follows. */
    citationsChanged(): void;
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
    /** The webview's own sequence number for this open, when it sent one (the review walk does). */
    openSeq?: number;
}
/**
 * What became of one source jump (viewer M3): opened; dropped because a newer jump, a new revision
 * or a freshness change overtook it; or blocked, with the reason, the short sentence the webview
 * shows and the warning an ordinary (non-walk) open still raises as a notification.
 */
type JumpOutcome =
    | { outcome: 'done' }
    | { outcome: 'cancelled' }
    | { outcome: 'blocked'; reason: OpenBlockReason; message: string; warning: string };
const CANCELLED: JumpOutcome = { outcome: 'cancelled' };
/**
 * The jump checks of one revision and freshness version (viewer M3, KI-09): per cited file, the
 * file's identity on disk when it was checked (device, inode, size and change times) and whether it
 * was stale then. A walk that steps through 27 citations of one notebook reads and hashes it once,
 * and runs at most one full validation, instead of once per step.
 */
interface JumpChecks {
    revision: string;
    freshness: number;
    files: Map<string, { signature: string; stale: StaleFile | undefined }>;
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
 * An artifact path read back from storage (the webview state or the registry): accepted only
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
    private disposed = false;
    /** The previous host's panels whose dead tab has not been found yet (see `recoverAfterRestart`). */
    private pending: PanelRecord[] = [];
    private registryWrites: Promise<void> = Promise.resolve();
    private tabWatch: vscode.Disposable | undefined;
    private sweepTimer: TimerHandle | undefined;
    private sweepWaiters: ((opened: number) => void)[] = [];
    private sweeps: Promise<number> = Promise.resolve(0);
    /** Front tabs already reported as dead without a registry entry, so each is logged once. */
    private readonly unmatched = new WeakSet<vscode.Tab>();
    /** Viewer M3 (step 14): MLView: Reveal in Diagram and the `mlview.citedFiles` context key. */
    readonly revealer: RevealInDiagram;
    constructor(private readonly ctx: vscode.ExtensionContext, private readonly log: Logger, private readonly validator: typeof validateWorkflow = validateWorkflow, private readonly io: AuthoredPanelIo = defaultIo, private readonly settleMs: number = RECOVERY_SETTLE_MS) {
        this.revealer = new RevealInDiagram(() => [...this.panels.values()], log);
    }
    register(): vscode.Disposable[] {
        const watcher = vscode.workspace.createFileSystemWatcher('**/*');
        const registered = [
            vscode.commands.registerCommand(OPEN_AUTHORED_COMMAND, (uri?: vscode.Uri) => this.open(uri)),
            // Viewer M3 (step 14): the way back from the code; its context key lists the cited files
            // of the open panels (`panelsChanged`, `citationsChanged`).
            this.revealer.register(),
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
            if (this.panels.get(key) === authored) {
                this.panels.delete(key);
                // A closed tab leaves the registry. When the host shuts down (`dispose`), the
                // panels stay registered: their tabs stay open for the next host.
                void this.recordPanels();
                // The reveal command's list of cited files follows; the last panel empties it.
                this.revealer.panelsChanged();
            }
        }, this.hooks, this.validator, this.io);
        this.panels.set(key, authored);
        void this.recordPanels();
        this.revealer.panelsChanged();
        return authored;
    }
    private async restore(panel: vscode.WebviewPanel, state: unknown): Promise<void> {
        // The saved state comes from the webview: accept only an absolute *.mlview.json inside a workspace folder.
        const target = savedArtifact(state && typeof state === 'object' ? (state as SavedState).artifact : undefined);
        // One panel per artifact: a revived tab whose diagram is already shown (opened, or reopened
        // in a dead tab's place after an extension host restart, before VS Code revived this tab)
        // is closed.
        if (!target || this.panels.has(target.key)) {
            panel.dispose();
            return;
        }
        panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(this.ctx.extensionUri, 'media')] };
        await this.adopt(panel, target).reload();
    }
    private readonly hooks: PanelHooks = {
        changed: () => { void this.recordPanels(); },
        flush: () => this.recordPanels(),
        citationsChanged: () => this.revealer.citationsChanged()
    };
    /**
     * Queue a write of this window's registry entry (see `OPEN_PANELS_KEY`): every open panel,
     * then the previous host's panels whose dead tab is still to be replaced. Writes run one at a
     * time, each from the state at its turn. Nothing is written once the controller is disposed,
     * which is how the extension host shuts down: the entry must outlive it.
     */
    private recordPanels(): Promise<void> {
        if (this.disposed)
            return this.registryWrites;
        this.registryWrites = this.registryWrites.then(() => this.writeRegistry()).catch((error: unknown) => {
            this.log.warn(`could not save the open diagrams: ${error instanceof Error ? error.message : String(error)}`);
        });
        return this.registryWrites;
    }
    private async writeRegistry(): Promise<void> {
        if (this.disposed)
            return;
        const session = vscode.env.sessionId;
        const now = Date.now();
        // Read again before each write: other windows write their own entries.
        const raw = this.ctx.globalState.get<unknown>(OPEN_PANELS_KEY);
        const registry = parseRegistry(raw);
        pruneRegistry(registry, session, now);
        const panels = [...[...this.panels.values()].map(panel => panel.record()), ...this.pending].slice(0, MAX_RECORDED_PANELS);
        const previous = registry.get(session);
        if (!panels.length)
            registry.delete(session);
        else if (!previous || JSON.stringify(previous.panels) !== JSON.stringify(panels))
            registry.set(session, { at: now, panels });
        const value = registry.size ? Object.fromEntries(registry) : undefined;
        if (JSON.stringify(value) === JSON.stringify(raw))
            return;
        await this.ctx.globalState.update(OPEN_PANELS_KEY, value);
    }
    /**
     * Run once at activation (see `OPEN_PANELS_KEY`). When the registry lists panels for this
     * window's session, an earlier extension host in this window had them open and VS Code
     * restarted it: their tabs are still open, dead. Each is replaced by a new panel for the same
     * artifact in the same editor group, which validates against the workspace as it is now (for
     * the root hint's "Add folder", against the added folder).
     *
     * A dead tab cannot be told from a tab VS Code restored at window load and has not shown yet:
     * the tabs API gives both the same title and view type. But a restored tab comes to life
     * through the serializer as soon as it comes to the front of its group, so only front tabs
     * are judged, and only after `RECOVERY_SETTLE_MS`: a diagram tab in front of its group that no
     * panel of this host shows by then is dead. A tab behind others is left alone until it comes
     * to the front. A dead tab takes the registry entry with its title, in its group if there is
     * one; a front tab no entry matches is left alone (Reload Window still revives it). An entry
     * whose title is on no diagram tab is dropped: the reader closed that tab.
     *
     * Returns how many diagrams the first check opened again.
     */
    async recoverAfterRestart(): Promise<number> {
        const raw = this.ctx.globalState.get<unknown>(OPEN_PANELS_KEY);
        if (raw === undefined)
            return 0;
        this.pending = parseRegistry(raw).get(vscode.env.sessionId)?.panels.slice() ?? [];
        // Also prunes the other sessions' old entries and repairs a malformed value.
        void this.recordPanels();
        if (!this.pending.length)
            return 0;
        this.log.info(`an earlier extension host in this window had ${this.pending.length} diagram(s) open; replacing their dead tabs`);
        const changed = (): void => { void this.scheduleSweep(); };
        this.tabWatch = vscode.Disposable.from(vscode.window.tabGroups.onDidChangeTabs(changed), vscode.window.tabGroups.onDidChangeTabGroups(changed));
        return this.scheduleSweep();
    }
    /** Check the front tabs `settleMs` after the last tab change (see `recoverAfterRestart`). */
    private scheduleSweep(): Promise<number> {
        if (this.disposed || !this.tabWatch)
            return Promise.resolve(0);
        if (this.sweepTimer !== undefined)
            clearTimeout(this.sweepTimer);
        const done = new Promise<number>(resolve => this.sweepWaiters.push(resolve));
        this.sweepTimer = setTimeout(() => {
            this.sweepTimer = undefined;
            const waiters = this.sweepWaiters.splice(0);
            this.sweeps = this.sweeps.then(() => this.sweep()).catch((error: unknown) => {
                this.log.warn(`replacing the dead diagram tabs failed: ${error instanceof Error ? error.message : String(error)}`);
                return 0;
            });
            void this.sweeps.then(opened => waiters.forEach(resolve => resolve(opened)));
        }, this.settleMs);
        return done;
    }
    /** Some panel of this host shows `tab`, the front tab of the group in `column`. */
    private showsIn(tab: vscode.Tab, column: vscode.ViewColumn): boolean {
        return [...this.panels.values()].some(panel => panel.showsIn(column, tab.label));
    }
    private async sweep(): Promise<number> {
        if (this.disposed || !this.tabWatch)
            return 0;
        const groups = vscode.window.tabGroups.all;
        const titles = new Set(groups.flatMap(group => group.tabs).filter(isAuthoredTab).map(tab => tab.label));
        const before = this.pending.length;
        this.pending = this.pending.filter(entry => titles.has(entry.title));
        const dead: { tab: vscode.Tab; entry: PanelRecord; column: vscode.ViewColumn }[] = [];
        for (const group of groups) {
            const tab = group.activeTab;
            if (!isAuthoredTab(tab) || this.showsIn(tab, group.viewColumn))
                continue;
            const sameTitle = (entry: PanelRecord): boolean => entry.title === tab.label;
            let index = this.pending.findIndex(entry => sameTitle(entry) && entry.column === group.viewColumn);
            if (index < 0)
                index = this.pending.findIndex(sameTitle);
            if (index < 0) {
                if (!this.unmatched.has(tab)) {
                    this.unmatched.add(tab);
                    this.log.info('a diagram tab in front of its group has no panel and matches no open diagram of the earlier extension host; left as it is');
                }
                continue;
            }
            dead.push({ tab, entry: this.pending.splice(index, 1)[0]!, column: group.viewColumn });
        }
        const opened: AuthoredPanel[] = [];
        if (dead.length) {
            // Open the new panels beside the dead tabs before closing those, so their groups stay.
            // An artifact already shown (opened again since the restart) gets no second panel.
            for (const { entry, column } of dead) {
                const target = savedArtifact(entry.artifact);
                if (target && !this.panels.has(target.key))
                    opened.push(this.create(target, column));
            }
            try {
                await vscode.window.tabGroups.close(dead.map(item => item.tab), true);
            }
            catch (error) {
                this.log.warn(`could not close the dead diagram tabs: ${error instanceof Error ? error.message : String(error)}`);
            }
            this.log.info(`VS Code restarted the extension host: closed ${dead.length} dead diagram tab(s) and opened ${opened.length} diagram(s) again`);
        }
        if (dead.length || this.pending.length !== before)
            void this.recordPanels();
        if (!this.pending.length)
            this.stopRecovery();
        await Promise.all(opened.map(panel => panel.reload()));
        return opened.length;
    }
    /** No dead tab is left to find: stop watching the tabs. */
    private stopRecovery(): void {
        this.tabWatch?.dispose();
        this.tabWatch = undefined;
        if (this.sweepTimer !== undefined) {
            clearTimeout(this.sweepTimer);
            this.sweepTimer = undefined;
        }
        this.sweepWaiters.splice(0).forEach(resolve => resolve(0));
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
        for (const panel of this.panels.values())
            panel.foldersChanged();
    }
    dispose(): void {
        // First, so the panels disposed below stay in the registry for the next host.
        this.disposed = true;
        this.stopRecovery();
        for (const p of this.panels.values())
            p.dispose();
        this.panels.clear();
        this.revealer.dispose();
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
class AuthoredPanel implements vscode.Disposable, RevealPanel {
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
    /** The whole-range highlight of the last source jump; disposing it clears it from every editor. */
    private highlight: vscode.TextEditorDecorationType | undefined;
    /** The editor and selection the last source jump set, until the walk releases it (see `releaseJumpSelection`). */
    private jumpSelection: { editor: vscode.TextEditor; selection: vscode.Selection } | undefined;
    /** The number of the latest source jump (see `Jump`). */
    private jumpSeq = 0;
    /**
     * The highest `seq` the webview page sent with an open (viewer M3); an open with a lower or equal
     * one is superseded. A new page starts again from 0 (`ready`).
     */
    private lastOpenSeq = 0;
    /** The cached checks behind source jumps, for the current revision and freshness (`JumpChecks`). */
    private jumpChecks: JumpChecks | undefined;
    /** The editor group the last jump showed its source in (`navigationColumn`). */
    private jumpColumn: vscode.ViewColumn | undefined;
    /** Editor groups the reader used outside the panel, most recent first (`navigationColumn`). */
    private recentColumns: vscode.ViewColumn[] = [];
    /**
     * Viewer M3 (step 14): the claims the displayed revision cites, by file and range, for MLView:
     * Reveal in Diagram. Built from the validated document whenever it changes.
     */
    private citations: CitationIndex | undefined;
    /** The cited files' identities on disk (realpath), for `citations` under the current root; rebuilt after each validation. */
    private citedIdentities: Promise<Map<string, string>> | undefined;
    /** A reveal the page may not have received yet (`REVEAL_REPLAY_MS`). */
    private pendingReveal: { ref: ClaimRef; revision: string; until: number } | undefined;
    constructor(private readonly panel: vscode.WebviewPanel, private readonly artifact: vscode.Uri, private folder: vscode.WorkspaceFolder, private readonly ctx: vscode.ExtensionContext, private readonly log: Logger, private readonly onDispose: () => void, private readonly hooks: PanelHooks, private readonly validator: typeof validateWorkflow, private readonly io: AuthoredPanelIo) {
        this.artifactRel = toPosixRelative(folder.uri.fsPath, artifact.fsPath);
        this.dependencies.addPath(artifact.fsPath);
        this.scheduler = new ValidationScheduler(() => this.runReload(), RELOAD_DEBOUNCE_MS, systemTimers, error => this.log.warn(`authored reload failed: ${error instanceof Error ? error.message : String(error)}`));
        this.render();
        panel.onDidDispose(() => this.dispose(), null, this.disposables);
        // A tab moved to another group: the registry keeps each panel's column.
        panel.onDidChangeViewState(() => this.hooks.changed(), null, this.disposables);
        panel.webview.onDidReceiveMessage((m: unknown) => { void this.message(m).catch(error => this.log.warn(`authored message failed: ${error instanceof Error ? error.message : String(error)}`)); }, null, this.disposables);
        this.disposables.push(vscode.window.onDidChangeActiveColorTheme(theme => this.post({ v: 1, type: 'theme', kind: themeKindOf(theme.kind) })));
        // The reader's last editor outside the panel names the group a jump reuses. A text or
        // notebook editor that takes focus is never the panel's own (that is this webview).
        this.noteActiveEditor(vscode.window.activeNotebookEditor);
        this.noteActiveEditor(vscode.window.activeTextEditor);
        this.disposables.push(vscode.window.onDidChangeActiveTextEditor(editor => this.noteActiveEditor(editor)), vscode.window.onDidChangeActiveNotebookEditor(editor => this.noteActiveEditor(editor)));
    }
    reveal(): void { this.panel.reveal(vscode.ViewColumn.Beside, true); }
    /** This panel in the registry: the artifact, the tab title and the group's column (see `OPEN_PANELS_KEY`). */
    record(): PanelRecord {
        const column = this.panel.viewColumn;
        return typeof column === 'number' && column > 0 ? { artifact: this.artifact.fsPath, title: this.panel.title, column } : { artifact: this.artifact.fsPath, title: this.panel.title };
    }
    /**
     * This panel is the visible editor of the group in `column`, whose front tab is titled
     * `title`. VS Code revives a restored panel with column 0 and reports its group a moment
     * later (20 ms in a live VS Code 1.139 check); until then a visible panel with the tab's title
     * counts.
     */
    showsIn(column: vscode.ViewColumn, title: string): boolean {
        if (this.disposed || !this.panel.visible)
            return false;
        const own = this.panel.viewColumn;
        return own === column || (!(typeof own === 'number' && own > 0) && this.panel.title === title);
    }
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
            // Viewer M3 (step 14): the citation index follows the validated document.
            if (value && this.citations?.document !== value.document)
                this.citations = CitationIndex.from(value.document);
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
        // The cited files' identities are looked up again after every validation (a folder change
        // can move the root, a rename can move a file).
        this.citedIdentities = undefined;
        await this.rebuildDependencies(candidateTracked, candidateFiles);
        await this.computeDirty();
        this.rootHint = await this.computeRootHint();
        if (this.disposed)
            return;
        if (verdict === 'adopt' && this.lastValid && candidate.kind === 'json') {
            const document = this.lastValid.document;
            const title = `MLView: ${document.title}`;
            if (this.panel.title !== title) {
                this.panel.title = title;
                this.hooks.changed();
            }
            if (this.ready) {
                this.postBanner(true, true);
                this.post({ v: 1, type: 'workflow', document });
                this.lastPostedFull = candidate.full;
            }
            const staleFiles = this.lastValid.stale;
            const toastKey = `${document.revision.id}\n${staleFiles.map(s => `${s.reason}:${s.rel}`).join('\n')}`;
            // The root hint has no notification: the panel's notice carries its two actions, and a
            // notification would outlive an extension host restart with dead buttons.
            if (!this.rootHint && staleFiles.length && toastKey !== this.lastStaleToast) {
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
        // Viewer M3 (step 14): a new revision, or a changed or restored cited file, changes the
        // reveal command's list of cited files.
        this.hooks.citationsChanged();
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
    /**
     * The root hint's two actions, from the panel's notice. The folder comes from the host's own
     * hint, never from the webview message, and nothing here changes what validation reads: a new
     * folder takes effect through `foldersChanged`, in the panel reopened after an extension host
     * restart, or in the new window.
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
        // extension host, which leaves this panel's tab dead until the next host replaces it from
        // the registry (see `OPEN_PANELS_KEY`): store the registry before the folder is added. A
        // multi-root window keeps its extension host, and `foldersChanged` validates in place.
        await this.hooks.flush();
        // Appended, so the first folder is left alone.
        if (!vscode.workspace.updateWorkspaceFolders(folders.length, 0, { uri }))
            void vscode.window.showWarningMessage('MLView: VS Code did not add the folder to the workspace.');
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
    private actionResult(requestId: string | undefined, action: 'exportFile' | 'copy' | 'refineWorkflow' | 'openLocation', outcome: 'done' | 'cancelled' | 'failed' | 'blocked', extra: { message?: string; name?: string; reason?: OpenBlockReason; seq?: number } = {}): void {
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
            // A new page numbers its opens from the start again.
            this.lastOpenSeq = 0;
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
            // Viewer M3 (step 14): a reveal the old page may have missed, after the document.
            this.replayReveal();
            return;
        }
        if (m.type === 'openLocation') {
            await this.openEvidence(m, requestId);
            return;
        }
        // Viewer M3: the review walk ended (`end`), or moved to a claim it opens nothing for
        // (`clear`: no quote, or a claim the reader only selected). Its highlight goes, and a walk
        // open still on its way (a notebook waiting for its cell editor) no longer lands.
        if (m.type === 'walk') {
            if (m.state === 'end' || m.state === 'clear')
                this.endWalk();
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
    /**
     * One `openLocation` request. `focus: true` is the explicit "open and go to the editor" gesture;
     * every other open keeps the keyboard on the diagram. Viewer M3, for the review walk: `seq`
     * (a positive integer, increasing per page) drops an open that a later one already replaced;
     * `requestId` asks for one `actionResult` (`done`, `blocked` with the reason, `cancelled` when it
     * was superseded, `failed` when VS Code could not show the file); `walk: true` raises no
     * notification for a blocked open, whose reason goes back to the webview instead; `highlight:
     * false` selects and reveals the range without the whole-range decoration.
     */
    private async openEvidence(m: Record<string, unknown>, requestId: string | undefined): Promise<void> {
        const id = typeof m.evidenceId === 'string' ? m.evidenceId : undefined;
        const focus = m.focus === true;
        const walk = m.walk === true;
        const highlight = m.highlight !== false;
        const seq = typeof m.seq === 'number' && Number.isSafeInteger(m.seq) && m.seq > 0 ? m.seq : undefined;
        const answer = (outcome: JumpOutcome | { outcome: 'failed'; message: string }): void => {
            const extra = outcome.outcome === 'blocked' ? { message: outcome.message, reason: outcome.reason } : outcome.outcome === 'failed' ? { message: outcome.message } : {};
            this.actionResult(requestId, 'openLocation', outcome.outcome, seq === undefined ? extra : { ...extra, seq });
        };
        if (seq !== undefined) {
            // Superseded: the page already sent a later open (messages can overtake one another
            // across a page reload, never within one page, but the order is the page's to decide).
            if (seq <= this.lastOpenSeq) {
                answer(CANCELLED);
                return;
            }
            this.lastOpenSeq = seq;
        }
        const shown = this.lastValid;
        const evidence = shown?.document.evidence.find(x => x.id === id);
        if (!shown || !evidence) {
            if (walk) {
                this.clearHighlight();
                this.releaseJumpSelection();
            }
            answer({ outcome: 'blocked', reason: 'unknown', message: blockedOpenText('unknown', ''), warning: '' });
            return;
        }
        const jump: Jump = { revision: shown.document.revision.id, freshness: this.freshnessVersion, seq: ++this.jumpSeq, ...(seq !== undefined ? { openSeq: seq } : {}) };
        let behind = false;
        let outcome: JumpOutcome;
        try {
            outcome = await this.jumpTo(evidence, shown, jump, { focus, highlight }, () => { behind = true; });
        }
        catch (error) {
            this.log.warn(`source navigation failed: ${error instanceof Error ? error.message : String(error)}`);
            answer({ outcome: 'failed', message: `VS Code could not show ${displayText(evidence.file, 200)}.` });
            return;
        }
        finally {
            // The jump's own check found files the panel has not caught up with (no watcher event
            // yet): validate the panel again, after this jump has been decided.
            if (behind)
                this.sourceChanged();
        }
        // Viewer M3: an open from the review walk raises no notification (no toast storm while
        // stepping through changed files); the webview shows the reason in its walk bar instead.
        if (outcome.outcome === 'blocked' && !walk && outcome.warning)
            void vscode.window.showWarningMessage(outcome.warning);
        // Viewer M3 (step 11): a blocked walk open also clears the previous claim's highlight, so
        // the editor beside never shows an earlier claim's lines while the walk says this claim's
        // file was not opened. A blocked Enter, double-click or Open link keeps it, as in M2.
        if (outcome.outcome === 'blocked' && walk) {
            this.clearHighlight();
            this.releaseJumpSelection();
        }
        answer(outcome);
    }
    private async jumpTo(evidence: WorkflowEvidence, shown: ValidatedWorkflow, jump: Jump, options: { focus: boolean; highlight: boolean }, markBehind: () => void): Promise<JumpOutcome> {
        const checked = await this.checkCitedFile(evidence, shown, jump, markBehind);
        if ('outcome' in checked)
            return checked;
        const file = displayText(evidence.file, 200);
        const staleFile = checked.stale;
        if (staleFile) {
            const hint = this.rootHint;
            if (hint && hint.files.includes(evidence.file))
                return { outcome: 'blocked', reason: 'elsewhere', message: blockedOpenText('elsewhere', file, { folder: listFiles([hintFolderName(hint)]) }), warning: rootHintJumpText(evidence.id, file, hint, listFiles) };
            return { outcome: 'blocked', reason: staleFile.reason, message: blockedOpenText(staleFile.reason, file, { revisionId: jump.revision }), warning: staleJumpText(evidence.id, file, staleFile.reason, jump.revision) };
        }
        const open = await this.findOpenDocument(evidence);
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        if (!this.unsavedTextStillCites(evidence, open))
            return { outcome: 'blocked', reason: 'unsaved', message: blockedOpenText('unsaved', file), warning: `MLView: unsaved changes in ${file} no longer contain the lines cited by evidence ${evidence.id}; save or revert the file, then try again.` };
        return this.navigate(evidence, jump, open, options);
    }
    /**
     * Whether the cited file is stale, decided once per revision, freshness version and file
     * identity (`JumpChecks`): from the cache while the file's identity on disk is unchanged; else
     * by hashing that one file when the displayed revision's validation read it fresh; else by a
     * full validation, whose verdicts are cached for every cited file. The identities are taken
     * before the file is read, so a cached verdict is never newer than the bytes it was decided on.
     */
    private async checkCitedFile(evidence: WorkflowEvidence, shown: ValidatedWorkflow, jump: Jump, markBehind: () => void): Promise<JumpOutcome | { stale: StaleFile | undefined }> {
        const signature = await this.fileSignature(evidence.file);
        const cached = this.cachedCheck(jump, evidence.file, signature);
        if (cached) {
            if (!this.navigationCurrent(jump))
                return CANCELLED;
            return { stale: cached.stale };
        }
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        if (await this.unchangedSinceValidation(shown, evidence)) {
            // The cited file's bytes are the ones the displayed revision was validated against, so
            // the quote still matches: no full revalidation for this jump.
            if (!this.navigationCurrent(jump))
                return CANCELLED;
            this.storeChecks(jump, new Map([[evidence.file, signature]]), shown.stale);
            return { stale: undefined };
        }
        const cited = [...new Set(shown.document.evidence.map(e => e.file))];
        const signatures = new Map(await Promise.all(cited.map(async rel => [rel, rel === evidence.file ? signature : await this.fileSignature(rel)] as const)));
        const displayed = this.lineage.displayed;
        let result: ValidationResult | undefined;
        try {
            result = await this.validate(shown.document, displayed && !displayed.verified ? displayed.baseline : undefined);
        }
        catch {
            result = { issues: [{ path: '$', message: 'validation failed' }] };
        }
        if (!result || !this.navigationCurrent(jump))
            return CANCELLED;
        if (!result.value) {
            const first = result.issues[0];
            const issue = first ? displayIssue(first) : 'unknown problem';
            return { outcome: 'blocked', reason: 'unchecked', message: blockedOpenText('unchecked', displayText(evidence.file, 200), { issue }), warning: `MLView: evidence ${evidence.id} could not be checked (${issue}); source navigation was stopped.` };
        }
        const fresh = result.value;
        // The panel is behind (no watcher event yet): it validates again and moves to a new
        // freshness version, so these verdicts are not kept.
        if (JSON.stringify(fresh.stale) !== JSON.stringify(shown.stale))
            markBehind();
        else
            this.storeChecks(jump, signatures, fresh.stale);
        return { stale: fresh.stale.find(s => s.rel === evidence.file) };
    }
    /** A cited file's identity on disk, or why it has none; any change to the file changes it. */
    private async fileSignature(rel: string): Promise<string> {
        try {
            const stat = await fs.stat(path.resolve(this.folder.uri.fsPath, rel), { bigint: true });
            return `${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}`;
        }
        catch (error) {
            const code = (error as NodeJS.ErrnoException | undefined)?.code;
            return `error:${typeof code === 'string' ? code : 'unknown'}`;
        }
    }
    private cachedCheck(jump: Jump, rel: string, signature: string): { stale: StaleFile | undefined } | undefined {
        const checks = this.jumpChecks;
        if (!checks || checks.revision !== jump.revision || checks.freshness !== jump.freshness)
            return undefined;
        const entry = checks.files.get(rel);
        return entry && entry.signature === signature ? { stale: entry.stale } : undefined;
    }
    /** Keep the verdicts for `signatures` while the jump's revision and freshness are still current. */
    private storeChecks(jump: Jump, signatures: ReadonlyMap<string, string>, stale: readonly StaleFile[]): void {
        if (this.disposed || this.lastValid?.document.revision.id !== jump.revision || this.freshnessVersion !== jump.freshness)
            return;
        if (!this.jumpChecks || this.jumpChecks.revision !== jump.revision || this.jumpChecks.freshness !== jump.freshness)
            this.jumpChecks = { revision: jump.revision, freshness: jump.freshness, files: new Map() };
        for (const [rel, signature] of signatures)
            this.jumpChecks.files.set(rel, { signature, stale: stale.find(s => s.rel === rel) });
    }
    /**
     * Viewer M3: the walk ended, or moved to a claim with nothing to open. Its highlight is cleared
     * and an open still on its way is dropped.
     */
    private endWalk(): void {
        this.jumpSeq++;
        this.clearHighlight();
        this.releaseJumpSelection();
    }
    /**
     * Viewer M3 (live check): the walk ended, cleared or was blocked, and its highlight went, but the
     * editor kept the earlier claim's lines selected (drawn in the inactive-selection colour). When
     * that editor is still visible and its selection is still exactly the one the jump set, it is
     * collapsed to the start of the cited range; a selection the reader changed is left alone.
     */
    private releaseJumpSelection(): void {
        const set = this.jumpSelection;
        this.jumpSelection = undefined;
        if (!set || !vscode.window.visibleTextEditors.includes(set.editor))
            return;
        const same = (a: vscode.Position, b: vscode.Position): boolean => a.line === b.line && a.character === b.character;
        const current = set.editor.selection;
        if (!current || !same(current.anchor, set.selection.anchor) || !same(current.active, set.selection.active))
            return;
        try {
            set.editor.selection = new vscode.Selection(set.selection.anchor, set.selection.anchor);
        }
        catch (error) {
            this.log.warn(`could not collapse the walk's selection: ${error instanceof Error ? error.message : String(error)}`);
        }
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
    /**
     * The jump may still act: same revision and freshness, no newer jump has started, and (for an
     * open the webview numbered) the page has sent no later open (viewer M3).
     */
    private navigationCurrent(jump: Jump): boolean {
        return !this.disposed && this.lastValid?.document.revision.id === jump.revision && this.freshnessVersion === jump.freshness && this.jumpSeq === jump.seq
            && (jump.openSeq === undefined || jump.openSeq === this.lastOpenSeq);
    }
    /**
     * The panel's own editor group. VS Code revives a restored panel with column 0 and reports its
     * group a moment later; until then it is the group whose front tab is this diagram.
     */
    private ownColumn(): vscode.ViewColumn | undefined {
        const column = this.panel.viewColumn;
        if (typeof column === 'number' && column > 0)
            return column;
        return vscode.window.tabGroups.all.find(group => isAuthoredTab(group.activeTab) && group.activeTab?.label === this.panel.title)?.viewColumn;
    }
    /**
     * Where a jump shows its source (viewer M2 live fix). Always an editor group other than the
     * panel's own, and an existing one when there is any: the group that already shows the cited
     * file; else the group of the previous jump, while it exists; else the group the reader used
     * last outside the panel; else the open group nearest the panel. Only a panel alone in the
     * window opens a group beside it. Text files and notebooks go to the same group.
     *
     * MEASURED live before the fix (VS Code 1.139): a 541 px diagram beside a notebook group, Enter
     * on a .py citation opened a third group, because a notebook's cell editors report no column
     * and the rule fell through to ViewColumn.Beside; the diagram dropped to 271 px.
     */
    private navigationColumn(document: vscode.TextDocument, notebook?: vscode.NotebookDocument): vscode.ViewColumn {
        const own = this.ownColumn();
        const groups = vscode.window.tabGroups.all;
        const exists = (column: vscode.ViewColumn | undefined): column is vscode.ViewColumn =>
            typeof column === 'number' && column > 0 && column !== own
            && (groups.length === 0 || groups.some(group => group.viewColumn === column));
        const sameUri = (left: vscode.Uri, right: vscode.Uri): boolean => left.toString() === right.toString();
        const showing = vscode.window.visibleTextEditors.find(editor => sameUri(editor.document.uri, document.uri) && exists(editor.viewColumn))?.viewColumn
            ?? (notebook ? vscode.window.visibleNotebookEditors.find(editor => sameUri(editor.notebook.uri, notebook.uri) && exists(editor.viewColumn))?.viewColumn : undefined);
        if (showing !== undefined)
            return showing;
        if (exists(this.jumpColumn))
            return this.jumpColumn;
        const recent = this.recentColumns.find(exists);
        if (recent !== undefined)
            return recent;
        // Any other open group, nearest the panel first (the mock and an older host may report no
        // tab groups; then the visible editors' groups stand in for them).
        const others = (groups.length ? groups.map(group => group.viewColumn) : [vscode.window.activeTextEditor, ...vscode.window.visibleTextEditors, ...vscode.window.visibleNotebookEditors].map(editor => editor?.viewColumn))
            .filter(exists);
        if (others.length) {
            const distance = (column: number): number => own === undefined ? column : Math.abs(column - own);
            return others.slice().sort((a, b) => distance(a) - distance(b) || a - b)[0]!;
        }
        return vscode.ViewColumn.Beside;
    }
    /** Remember the group a jump showed its source in, for the next jump. */
    private noteJumpColumn(column: vscode.ViewColumn | undefined): void {
        if (typeof column === 'number' && column > 0)
            this.jumpColumn = column;
    }
    /** The reader moved to an editor outside the panel: its group is the most recently used one. */
    private noteActiveEditor(editor: { viewColumn?: vscode.ViewColumn } | undefined): void {
        const column = editor?.viewColumn;
        if (typeof column !== 'number' || column <= 0)
            return;
        this.recentColumns = [column, ...this.recentColumns.filter(other => other !== column)].slice(0, 8);
    }
    /**
     * Open the cited source beside the panel, select the whole cited range and highlight it.
     * `focus` false (the default gesture) keeps the keyboard on the diagram; `highlight` false
     * leaves the whole-range decoration off.
     */
    private async navigate(e: WorkflowEvidence, jump: Jump, open: { text?: vscode.TextDocument; notebook?: vscode.NotebookDocument }, options: { focus: boolean; highlight: boolean }): Promise<JumpOutcome> {
        const uri = open.notebook?.uri ?? open.text?.uri ?? vscode.Uri.file(path.join(this.folder.uri.fsPath, e.file));
        const start = toEditorLine(e.line), end = toEditorLine(e.endLine);
        if (e.cell !== undefined)
            return this.navigateCell(e.cell, displayText(e.file, 200), uri, start, end, jump, options);
        const doc = await vscode.workspace.openTextDocument(uri);
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        const editor = await vscode.window.showTextDocument(doc, { preview: true, preserveFocus: !options.focus, viewColumn: this.navigationColumn(doc) });
        this.noteJumpColumn(editor.viewColumn);
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        this.showRange(editor, citedRange(doc, start, end), options.highlight);
        return { outcome: 'done' };
    }
    /**
     * A notebook citation: show the notebook with the cited cell selected and revealed, then
     * select and highlight the cited lines in that cell's editor. VS Code creates a cell's editor
     * only once the cell is drawn; when it does not appear in time, the cell stays selected and
     * revealed without the line highlight.
     */
    private async navigateCell(index: number, file: string, uri: vscode.Uri, start: number, end: number, jump: Jump, options: { focus: boolean; highlight: boolean }): Promise<JumpOutcome> {
        const notebook = await vscode.workspace.openNotebookDocument(uri);
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        // VS Code clamps cellAt's index, so a removed cell must be detected by count.
        if (index >= notebook.cellCount)
            return { outcome: 'blocked', reason: 'cell-missing', message: blockedOpenText('cell-missing', file, { cell: index }), warning: `MLView: notebook cell ${index} no longer exists.` };
        const cell = notebook.cellAt(index);
        const cells = new vscode.NotebookRange(index, index + 1);
        const notebookEditor = await vscode.window.showNotebookDocument(notebook, { preview: true, preserveFocus: !options.focus, viewColumn: this.navigationColumn(cell.document, notebook), selections: [cells] });
        this.noteJumpColumn(notebookEditor.viewColumn);
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        notebookEditor.revealRange(cells, vscode.NotebookEditorRevealType.InCenterIfOutsideViewport);
        const cellEditor = await visibleEditorFor(cell.document, CELL_EDITOR_WAIT_MS);
        // A newer jump may have started during the wait: it owns the selection and the highlight.
        if (!this.navigationCurrent(jump))
            return CANCELLED;
        if (cellEditor)
            this.showRange(cellEditor, citedRange(cell.document, start, end), options.highlight);
        else
            this.clearHighlight();
        return { outcome: 'done' };
    }
    /** Select the whole range, reveal it, and move the highlight to it (`highlight` false: only clear the old one). */
    private showRange(editor: vscode.TextEditor, range: vscode.Range, highlight = true): void {
        const selection = new vscode.Selection(range.start, range.end);
        editor.selection = selection;
        this.jumpSelection = { editor, selection };
        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
        this.clearHighlight();
        if (!highlight)
            return;
        this.highlight = vscode.window.createTextEditorDecorationType(HIGHLIGHT_STYLE());
        editor.setDecorations(this.highlight, [range]);
    }
    private clearHighlight(): void {
        this.highlight?.dispose();
        this.highlight = undefined;
    }
    /* ── viewer M3 (step 14): MLView: Reveal in Diagram (see revealCommand.ts) ── */

    /** The displayed revision's title, for the diagram picker. */
    documentTitle(): string {
        return this.lastValid?.document.title ?? this.panel.title;
    }
    artifactPath(): string {
        return this.artifactRel;
    }
    /**
     * The displayed revision's cited files that are unchanged since publishing, as absolute paths
     * under this panel's workspace folder: the reveal command's context key (M3 review, F1). A stale
     * file (changed, missing, unreadable, too large, or found only under the folder the root hint
     * names) is left out, as the command would not match it.
     */
    citedFiles(): string[] {
        const index = this.citations;
        const shown = this.lastValid;
        if (this.disposed || !index || !shown || index.document !== shown.document)
            return [];
        const stale = new Set(shown.stale.map(s => s.rel));
        const root = this.folder.uri.fsPath;
        return index.files().filter(rel => !stale.has(rel)).map(rel => path.resolve(root, rel));
    }
    /**
     * What the displayed revision says about the reader's file: not cited; a cited file found in the
     * folder the root hint names instead of the workspace root; cited but stale (changed, missing,
     * unreadable or too large since publishing); cited in the other form (notebook cells
     * against a text editor); cited, but no range still has its quote at the cited lines of the
     * editor's text (unsaved edits moved them, or a change nothing reported yet); or cited, with the
     * ranges that still hold. The file is matched by its workspace-relative path, then by identity
     * on disk (a symlinked folder, a case alias).
     */
    async citationState(place: EditorPlace): Promise<CitationState> {
        const index = this.citations;
        const shown = this.lastValid;
        if (this.disposed || !index || !shown || index.document !== shown.document)
            return { kind: 'none' };
        const rel = await this.citedRel(index, place.fsPath);
        if (this.disposed || this.citations !== index)
            return { kind: 'none' };
        if (!rel) {
            // The parent-folder case: the file is a cited one, unchanged, in the folder the root
            // hint names, not at the workspace root the diagram is validated against.
            const hint = this.rootHint;
            const underHint = hint ? toPosixRelative(hint.base, place.fsPath) : undefined;
            return hint && underHint && hint.files.includes(underHint) && index.ranges(underHint).length
                ? { kind: 'elsewhere', rel: underHint, folder: hintFolderName(hint) }
                : { kind: 'none' };
        }
        const stale = shown.stale.find(s => s.rel === rel);
        if (stale)
            return { kind: 'stale', rel, reason: stale.reason, revision: index.revision };
        const ranges = index.ranges(rel);
        const sameForm = ranges.filter(range => (range.evidence.cell !== undefined) === place.notebook);
        if (!sameForm.length)
            return { kind: 'form', rel, cells: ranges.some(range => range.evidence.cell !== undefined) };
        const holding = sameForm.filter(range => {
            const lines = place.linesFor(range.evidence);
            return lines !== undefined && quoteMatches(range.evidence.quote, lines, range.evidence.line, range.evidence.endLine);
        });
        if (!holding.length)
            return { kind: 'moved', rel, dirty: place.dirty };
        return { kind: 'cited', rel, revision: index.revision, ranges: holding };
    }
    /** The cited file `fsPath` is, as the evidence records spell it, or undefined. */
    private async citedRel(index: CitationIndex, fsPath: string): Promise<string | undefined> {
        const root = this.folder.uri.fsPath;
        const lexical = toPosixRelative(root, fsPath);
        if (index.ranges(lexical).length)
            return lexical;
        if (!this.citedIdentities) {
            const files = index.files();
            this.citedIdentities = Promise.all(files.map(rel => identity(path.resolve(root, rel)))).then(ids => new Map(ids.map((id, i) => [id, files[i]!])));
        }
        const [ids, target] = await Promise.all([this.citedIdentities, identity(fsPath)]);
        return ids.get(target);
    }
    /** A change is waiting to be checked: validate now, so the answer is about the files as they are. */
    async settle(): Promise<void> {
        if (this.pendingCheck && !this.disposed)
            await this.reload();
    }
    recheck(): void {
        this.sourceChanged();
    }
    /**
     * Show the claim in the diagram: post `reveal {kind, id}` (the webview selects it, brings it into
     * view and shows it in the Selection tab), and move the keyboard focus to this panel, in its own
     * group. This is the one place the viewer moves the focus by itself: the reader asked for the
     * diagram. False when the displayed revision is no longer `revision` or lacks the claim.
     *
     * VS Code discards a hidden panel's page (this panel does not retain its context), so a page
     * that was hidden or reloading may miss the frame: it is posted again after the page's next
     * `ready`, if that comes within REVEAL_REPLAY_MS.
     */
    revealClaim(ref: ClaimRef, revision: string): boolean {
        const index = this.citations;
        if (this.disposed || !index || index.revision !== revision || this.lastValid?.document !== index.document || !index.claim(ref))
            return false;
        this.pendingReveal = { ref: { kind: ref.kind, id: ref.id }, revision, until: Date.now() + REVEAL_REPLAY_MS };
        if (this.ready)
            this.post({ v: 1, type: 'reveal', kind: ref.kind, id: ref.id });
        this.panel.reveal(undefined, false);
        return true;
    }
    /** After a page's `ready`: post the reveal it may have missed, once, while it is recent and its revision is still shown. */
    private replayReveal(): void {
        const pending = this.pendingReveal;
        this.pendingReveal = undefined;
        if (!pending || Date.now() > pending.until || this.citations?.revision !== pending.revision || !this.citations.claim(pending.ref))
            return;
        this.post({ v: 1, type: 'reveal', kind: pending.ref.kind, id: pending.ref.id });
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
     *
     * Viewer M3: VS Code's webview host forwards every keydown to the workbench from a listener on
     * the page's window, even a key the page already handled, and the workbench runs any keybinding
     * that matches. MEASURED live (VS Code 1.139): one Escape on a card collapsed the bottom sheet
     * and also dismissed a VS Code notification. An Escape the viewer acted on (it collapsed the
     * sheet, closed the legend, cleared the selection) marks the event handled, and a listener on
     * the document stops it there, before it reaches the window: one Escape, one action. It is added
     * once the viewer has mounted, so it runs after the viewer's own document listeners. (A listener
     * on the window would come too late: VS Code's forwarder is attached to that window before this
     * page's scripts run, and it stays attached; checked live.)
     */
    private render(): void { const nonce = createNonce(); const script = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.js')); const style = this.panel.webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'mlview.css')); this.panel.webview.html = `<!doctype html><html><head><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${this.panel.webview.cspSource} data:; style-src ${this.panel.webview.cspSource}; script-src 'nonce-${nonce}' ${this.panel.webview.cspSource};"><link rel="stylesheet" href="${style}"></head><body><div id="mlview-root"></div><script nonce="${nonce}" src="${script}"></script><script nonce="${nonce}">(function(){var root=document.getElementById('mlview-root');var bridge=window.MLView.bridges.vscode();var save=bridge.saveState.bind(bridge);var artifact=null;bridge.saveState=function(state){save(Object.assign({},state,{artifact:artifact}));};var app=null;bridge.onMessage(function(m){if(!m||m.v!==1)return;if(m.type==='init'){if(typeof m.artifact==='string'){artifact=m.artifact;bridge.saveState(bridge.loadState()||{});}if(!app){if(m.theme)bridge.theme=m.theme;if(m.capabilities)bridge.capabilities=m.capabilities;}return;}if(m.type==='theme'){if(!app&&m.kind)bridge.theme=m.kind;return;}if(m.type==='workflow'){if(!app&&m.document){app=window.MLView.mountWorkflow(root,m.document,bridge);document.addEventListener('keydown',function(e){if(e.key==='Escape'&&e.defaultPrevented)e.stopPropagation();});}return;}if(m.type==='workflowError'){var e=document.getElementById('mlview-authored-error');if(app||!m.message){if(e)e.remove();return;}if(!e){e=document.createElement('pre');e.id='mlview-authored-error';e.setAttribute('role','status');root.prepend(e);}e.textContent=m.message;}});bridge.post({v:1,type:'ready'});}());</script></body></html>`; }
    dispose(): void {
        if (this.disposed)
            return;
        this.disposed = true;
        this.scheduler.dispose();
        this.cancelRetry();
        this.clearHighlight();
        this.jumpSelection = undefined;
        this.citations = undefined;
        this.citedIdentities = undefined;
        this.pendingReveal = undefined;
        if (this.dirtyTimer !== undefined) {
            clearTimeout(this.dirtyTimer);
            this.dirtyTimer = undefined;
        }
        for (const d of this.disposables)
            d.dispose();
        this.onDispose();
    }
}
