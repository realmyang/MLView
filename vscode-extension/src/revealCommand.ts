/**
 * Viewer M3 (roadmap step 14): MLView: Reveal in Diagram, the way from the code back to the diagram.
 *
 * The editor context menu (and the Command Palette) offers the command while an open diagram cites
 * the active editor's file and that file is unchanged: the `mlview.citedFile` context key. Run on a
 * cited line or selection, it finds the claims whose cited lines include it; one is shown at once, a
 * QuickPick lists several, and a place no claim cites offers the nearest claims in the file. The
 * chosen claim is shown in its diagram, and the keyboard focus moves to that panel: the one place
 * the viewer moves the focus by itself, because the reader asked for the diagram.
 *
 * Nothing here reads or interprets code: the claims and their ranges come from the panel's
 * validated document (`CitationIndex`), and a range counts only while the editor's text still has
 * the quote at the cited lines. No default keybinding, no hover, no CodeLens, no diagnostics.
 */
import * as path from 'node:path';
import * as vscode from 'vscode';
import { claimPickText, claimsAt, linesText, nearestClaims, pickText, type ClaimMatch, type ClaimRef, type CitedRange } from './citationIndex';
import { displayText } from './displayText';
import type { Logger } from './log';
import { splitLines, type StaleReason, type WorkflowEvidence } from './workflowDocument';

export const REVEAL_COMMAND = 'mlview.revealInDiagram';
export const CITED_FILE_CONTEXT = 'mlview.citedFile';
/** The context key follows edits to the active file at most this often. */
export const CITED_KEY_THROTTLE_MS = 150;
/** At most this many nearest claims are offered for a line no claim cites. */
export const NEAREST_LIMIT = 30;

/** Where the reader is: the file on disk (the notebook, for a cell), the cell, and the lines. */
export interface EditorPlace {
    fsPath: string;
    /** The notebook cell's index, counted from 0 as the artifact records it; undefined in a plain file. */
    cell?: number;
    /** The editor shows a notebook's cell (undefined for a text editor, even on an .ipynb file). */
    notebook: boolean;
    /** The selection's first and last lines, one-based; the cursor's line when nothing is selected. */
    start: number;
    end: number;
    /** The text has unsaved changes. */
    dirty: boolean;
    /** The editor's current text of the document or cell `evidence` addresses, as lines; undefined when it has none. */
    linesFor(evidence: WorkflowEvidence): readonly string[] | undefined;
}
/** What a panel says about the reader's file. */
export type CitationState =
    | { kind: 'none' }
    | { kind: 'stale'; rel: string; reason: StaleReason; revision: string }
    /** A cited file, unchanged, in the folder the panel's root hint names, not at the workspace root. */
    | { kind: 'elsewhere'; rel: string; folder: string }
    /** The diagram cites the notebook by cell, and the file is open as text (or the other way round). */
    | { kind: 'form'; rel: string; cells: boolean }
    /** No cited range still has its quote at the cited lines of the editor's text. */
    | { kind: 'moved'; rel: string; dirty: boolean }
    | { kind: 'cited'; rel: string; revision: string; ranges: readonly CitedRange[] };
/** The panel side of the command (authoredPanel.ts). */
export interface RevealPanel {
    /** The displayed revision's title, for the diagram picker. */
    documentTitle(): string;
    /** The artifact, relative to its workspace folder. */
    artifactPath(): string;
    citationState(place: EditorPlace): Promise<CitationState>;
    /** Validate now when a change is waiting to be checked, so the answer is about the files as they are. */
    settle(): Promise<void>;
    /** The file no longer has the quoted lines though nothing reported a change: validate again. */
    recheck(): void;
    /** Show `ref` of revision `revision` and move the focus to the panel; false when the revision changed. */
    revealClaim(ref: ClaimRef, revision: string): boolean;
}
type Timers = { set(callback: () => void, ms: number): ReturnType<typeof setTimeout>; clear(handle: ReturnType<typeof setTimeout>): void };
const systemTimers: Timers = { set: (callback, ms) => setTimeout(callback, ms), clear: handle => clearTimeout(handle) };

/** The selection's lines, one-based. A selection that ends at the start of a line leaves that line out. */
export function selectionLines(selection: { start: vscode.Position; end: vscode.Position }): { start: number; end: number } {
    // A Selection is a Range: `start` is never after `end`, whichever way it was made.
    const first = selection.start.line;
    let last = Math.max(first, selection.end.line);
    if (last > first && selection.end.character === 0)
        last -= 1;
    return { start: first + 1, end: last + 1 };
}
/** The reader's place in `editor`, or undefined when it shows no file on disk (an untitled or remote file). */
export function editorPlace(editor: vscode.TextEditor): EditorPlace | undefined {
    const document = editor.document;
    const { start, end } = selectionLines(editor.selection);
    const memo = new Map<vscode.TextDocument, readonly string[]>();
    const lines = (doc: vscode.TextDocument): readonly string[] => {
        let found = memo.get(doc);
        if (!found) {
            found = splitLines(doc.getText());
            memo.set(doc, found);
        }
        return found;
    };
    if (document.uri.scheme === 'file')
        return { fsPath: document.uri.fsPath, notebook: false, start, end, dirty: document.isDirty, linesFor: evidence => (evidence.cell === undefined ? lines(document) : undefined) };
    if (document.uri.scheme !== 'vscode-notebook-cell')
        return undefined;
    const key = document.uri.toString();
    for (const notebook of vscode.workspace.notebookDocuments) {
        if (notebook.uri.scheme !== 'file')
            continue;
        const cell = notebook.getCells().find(candidate => candidate.document.uri.toString() === key);
        if (!cell)
            continue;
        return {
            fsPath: notebook.uri.fsPath,
            cell: cell.index,
            notebook: true,
            start,
            end,
            dirty: notebook.isDirty,
            // cellAt clamps its index in VS Code, so check the count first.
            linesFor: evidence => (evidence.cell !== undefined && evidence.cell < notebook.cellCount ? lines(notebook.cellAt(evidence.cell).document) : undefined)
        };
    }
    return undefined;
}
const STALE_PHRASE: Record<StaleReason, string> = { changed: 'changed', missing: 'went missing', unreadable: 'could no longer be read', 'too-large': 'grew too large to check' };
/** "line 4 of train.py", "cell 3, lines 2–5 of notes.ipynb". */
function placeText(place: EditorPlace): string {
    return `${place.cell !== undefined ? `cell ${place.cell}, ` : ''}${linesText(place.start, place.end)} of ${displayText(path.basename(place.fsPath), 200)}`;
}
type ClaimItem = vscode.QuickPickItem & { ref: ClaimRef };
type PanelItem = vscode.QuickPickItem & { index: number };
export class RevealInDiagram implements vscode.Disposable {
    /** The editor listeners; they exist only while a panel is open. */
    private listeners: vscode.Disposable[] = [];
    private command: vscode.Disposable | undefined;
    private keyValue: boolean | undefined;
    private updates = 0;
    private timer: ReturnType<typeof setTimeout> | undefined;
    private disposed = false;
    constructor(private readonly panels: () => readonly RevealPanel[], private readonly log: Logger, private readonly timers: Timers = systemTimers) { }
    /** Register the command (always: VS Code needs a contributed command to exist) and start with the key off. */
    register(): vscode.Disposable {
        this.command = vscode.commands.registerCommand(REVEAL_COMMAND, () => this.run());
        // A restarted extension host may find the key the previous one left on.
        this.setKey(false);
        return this.command;
    }
    /** A panel opened or closed. The listeners exist while a panel does; the last one turns the key off. */
    panelsChanged(): void {
        if (this.disposed)
            return;
        if (this.panels().length) {
            this.attach();
            void this.update();
        }
        else
            this.detach();
    }
    /** A panel validated again (a new revision, a changed or restored file): the key follows. */
    citationsChanged(): void {
        if (!this.disposed && this.listeners.length)
            void this.update();
    }
    /** Whether the editor listeners are live (tests). */
    get attached(): boolean {
        return this.listeners.length > 0;
    }
    private attach(): void {
        if (this.listeners.length)
            return;
        const activeText = (document: vscode.TextDocument): boolean => vscode.window.activeTextEditor?.document === document;
        const activeNotebook = (notebook: vscode.NotebookDocument): boolean => {
            const document = vscode.window.activeTextEditor?.document;
            return !!document && document.uri.scheme === 'vscode-notebook-cell' && notebook.getCells().some(cell => cell.document === document);
        };
        this.listeners = [
            vscode.window.onDidChangeActiveTextEditor(() => { void this.update(); }),
            // Typing (or saving, or undoing back to the saved text) in the active file can move or
            // restore the cited lines.
            vscode.workspace.onDidChangeTextDocument(event => { if (activeText(event.document)) this.scheduleUpdate(); }),
            vscode.workspace.onDidChangeNotebookDocument(event => { if (activeNotebook(event.notebook)) this.scheduleUpdate(); })
        ];
    }
    private detach(): void {
        for (const listener of this.listeners.splice(0))
            listener.dispose();
        this.cancelTimer();
        this.updates++;
        this.setKey(false);
    }
    private scheduleUpdate(): void {
        if (this.timer !== undefined)
            return;
        this.timer = this.timers.set(() => {
            this.timer = undefined;
            void this.update();
        }, CITED_KEY_THROTTLE_MS);
    }
    private cancelTimer(): void {
        if (this.timer !== undefined) {
            this.timers.clear(this.timer);
            this.timer = undefined;
        }
    }
    private setKey(value: boolean): void {
        if (this.keyValue === value)
            return;
        this.keyValue = value;
        void Promise.resolve(vscode.commands.executeCommand('setContext', CITED_FILE_CONTEXT, value)).catch((error: unknown) => this.log.warn(`could not set ${CITED_FILE_CONTEXT}: ${error instanceof Error ? error.message : String(error)}`));
    }
    /**
     * Compute the key for the active editor: on while some open panel cites its file, the file is
     * unchanged since that revision was published, and at least one cited range still has its quote
     * at the cited lines of the editor's text. Only the latest computation sets it.
     */
    async update(): Promise<void> {
        const seq = ++this.updates;
        const editor = vscode.window.activeTextEditor;
        const place = editor ? editorPlace(editor) : undefined;
        let cited = false;
        if (place) {
            for (const panel of this.panels()) {
                let state: CitationState;
                try {
                    state = await panel.citationState(place);
                }
                catch (error) {
                    this.log.warn(`could not look up the cited files: ${error instanceof Error ? error.message : String(error)}`);
                    continue;
                }
                if (seq !== this.updates)
                    return;
                if (state.kind === 'cited') {
                    cited = true;
                    break;
                }
            }
        }
        if (seq !== this.updates || this.disposed || !this.listeners.length)
            return;
        this.setKey(cited);
    }
    /** MLView: Reveal in Diagram. */
    async run(): Promise<void> {
        const panels = this.panels();
        if (!panels.length) {
            void vscode.window.showInformationMessage('MLView: no diagram is open. Open a generated diagram, then use Reveal in Diagram on a line it cites.');
            return;
        }
        const editor = vscode.window.activeTextEditor;
        const place = editor ? editorPlace(editor) : undefined;
        if (!place) {
            void vscode.window.showInformationMessage('MLView: Reveal in Diagram works in the editor of a cited source file or notebook cell. Put the cursor on a cited line, then try again.');
            return;
        }
        await Promise.all(panels.map(panel => panel.settle()));
        const states = await Promise.all(panels.map(async panel => ({ panel, state: await panel.citationState(place) })));
        const cited = states.filter((entry): entry is { panel: RevealPanel; state: Extract<CitationState, { kind: 'cited' }> } => entry.state.kind === 'cited');
        const where = placeText(place);
        if (!cited.length) {
            for (const entry of states)
                if (entry.state.kind === 'moved' && !entry.state.dirty)
                    entry.panel.recheck();
            void vscode.window.showInformationMessage(this.notCited(states.map(entry => entry.state), place));
            return;
        }
        let chosen = cited[0]!;
        if (cited.length > 1) {
            const items: PanelItem[] = cited.map((entry, index) => {
                const count = claimsAt(entry.state.ranges, place.cell, place.start, place.end).length;
                return {
                    label: pickText(entry.panel.documentTitle()),
                    description: pickText(entry.panel.artifactPath(), 200),
                    detail: count ? `${count} ${count === 1 ? 'claim cites' : 'claims cite'} ${linesText(place.start, place.end)}` : `No claim cites ${linesText(place.start, place.end)}; the nearest are offered`,
                    index
                };
            });
            const picked = await vscode.window.showQuickPick(items, { title: 'Reveal in Diagram', placeHolder: `${cited.length} open diagrams cite ${displayText(path.basename(place.fsPath), 200)}: choose the diagram`, matchOnDescription: true });
            if (!picked)
                return;
            chosen = cited[picked.index]!;
        }
        const ref = await this.chooseClaim(chosen.state.ranges, place, where);
        if (!ref)
            return;
        if (!chosen.panel.revealClaim(ref, chosen.state.revision))
            void vscode.window.showInformationMessage('MLView: the diagram changed to another revision while you were choosing. Run Reveal in Diagram again.');
    }
    /** One claim at the place, the reader's choice of several, or of the nearest ones; undefined when cancelled. */
    private async chooseClaim(ranges: readonly CitedRange[], place: EditorPlace, where: string): Promise<ClaimRef | undefined> {
        const at = claimsAt(ranges, place.cell, place.start, place.end);
        if (at.length === 1)
            return refOf(at[0]!);
        const nearest = !at.length;
        const matches = nearest ? nearestClaims(ranges, place.cell, place.start, place.end, NEAREST_LIMIT) : at;
        if (!matches.length) {
            void vscode.window.showInformationMessage(`MLView: no claim in this diagram cites ${where}.`);
            return undefined;
        }
        const items: ClaimItem[] = matches.map(match => ({ ...claimPickText(match, nearest), ref: refOf(match) }));
        const picked = await vscode.window.showQuickPick(items, {
            title: nearest ? `Reveal in Diagram: no claim cites ${where}` : 'Reveal in Diagram',
            placeHolder: nearest ? 'The nearest claims in this file: choose one to show it in the diagram' : `${at.length} claims cite ${where}: choose one to show it in the diagram`,
            matchOnDescription: true,
            matchOnDetail: true
        });
        return picked?.ref;
    }
    /** Why no open diagram can answer for this file, in one sentence. */
    private notCited(states: readonly CitationState[], place: EditorPlace): string {
        const file = displayText(path.basename(place.fsPath), 200);
        const moved = states.find((state): state is Extract<CitationState, { kind: 'moved' }> => state.kind === 'moved');
        if (moved?.dirty)
            return `MLView: the unsaved text of ${file} no longer has the quoted lines where the diagram cites them, so the cursor cannot be matched to a claim. Undo those edits to use Reveal in Diagram here.`;
        if (moved)
            return `MLView: ${file} no longer has the quoted lines where the diagram cites them; MLView is checking it again.`;
        const elsewhere = states.find((state): state is Extract<CitationState, { kind: 'elsewhere' }> => state.kind === 'elsewhere');
        if (elsewhere)
            return `MLView: the diagram cites ${displayText(elsewhere.rel, 200)} from the workspace root, where it is missing; this copy in ${displayText(elsewhere.folder, 200)} is unchanged. Add that folder to the workspace (the diagram's notice offers it), then try again.`;
        const stale = states.find((state): state is Extract<CitationState, { kind: 'stale' }> => state.kind === 'stale');
        if (stale)
            return `MLView: ${file} ${STALE_PHRASE[stale.reason]} after revision ${displayText(stale.revision, 200)} was published, so its lines no longer match the diagram. Ask the assistant for a fresh revision.`;
        const form = states.find((state): state is Extract<CitationState, { kind: 'form' }> => state.kind === 'form');
        if (form)
            return form.cells
                ? `MLView: the diagram cites ${file} by notebook cell. Open it in the notebook editor and use Reveal in Diagram in a cell.`
                : `MLView: the diagram cites ${file} as a text file. Open it in the text editor and use Reveal in Diagram there.`;
        return `MLView: no open diagram cites ${file}.`;
    }
    dispose(): void {
        if (this.disposed)
            return;
        this.detach();
        this.disposed = true;
        this.command?.dispose();
        this.command = undefined;
    }
}
const refOf = (match: ClaimMatch): ClaimRef => ({ kind: match.claim.kind, id: match.claim.id });
