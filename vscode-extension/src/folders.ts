/**
 * H10 — multi-root workspaces.
 *
 * Until this file existed the controller held ONE `graph`, ONE `index` and ONE `lastScope`,
 * and `workspaceFolderFor` fell back to `workspaceFolders?.[0]` (`extension.ts:299`) while the
 * language-model path hardcoded the same (`toolAnalyze.ts:38`). In a window with two folders
 * open the second was never analyzed and nothing said so — the exact failure mode the roadmap's
 * standing criterion forbids ("state what you could not analyze").
 *
 * The replacement is a MAP keyed by folder, with today's single-folder path as the one-entry
 * case: `FolderBook` hands out one `FolderState` per open folder and remembers which one is
 * ACTIVE. Everything that legitimately shows one graph at a time — the diagram panel, the
 * status bar, the issue quick pick, the HTML export, the chat and LM digests — reads the
 * active folder; everything that is per-file — CodeLens, the Problems panel — reads the state
 * of the folder that file lives in.
 *
 * The active folder is SESSION state, not a setting. A persisted `mlview.activeFolder` would
 * name a folder by a string that means nothing on the next machine, and CONTRACTS 11.11's
 * "Settings: none added" line is only worth relaxing for something a user types on purpose.
 * `MLView: Select Active Folder` (`mlview.activeFolder`) and the status-bar tooltip's picker
 * are how it moves; opening a file in another folder moves it too.
 */

import * as vscode from 'vscode';
import type { MLGraph } from './graph';
import type { LocationIndex } from './locationIndex';
import type { CoreAction } from './coreClient';
import type { AnalysisScope } from './protocol';

/** What one analysis of one folder was asked for. Moved here from extension.ts unchanged. */
export interface Scope {
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

/** A failure remembered for a webview that boots after the run that failed. */
export interface RememberedFailure {
  key: string;
  requestId: string;
  message: string;
  detail: string;
  actions: CoreAction[];
}

/** Everything the controller used to keep in six fields, now once per open folder. */
export interface FolderState {
  /** `folderKey(root)` — the map key, and stable for the life of the folder. */
  readonly key: string;
  /** The folder's `uri.fsPath`. */
  readonly root: string;
  /** The folder's display name, for the picker and the tooltip. */
  readonly name: string;
  graph?: MLGraph;
  index?: LocationIndex;
  lastScope: Scope;
  readonly staleFiles: Set<string>;
  appliedFocus?: string;
  lastFailure?: RememberedFailure;
}

/**
 * One spelling for one folder. Case is folded because a workspace folder reaches us as
 * `c:\Repo` from one API and `C:/repo` from another on Windows, and two entries for one
 * folder is two graphs of the same code that disagree.
 */
export function folderKey(fsPath: string): string {
  return fsPath.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

/**
 * The tooltip's folder line, or undefined when there is nothing to choose between.
 *
 * Pure so the wording is asserted directly. A single-folder window gets NO line at all: the
 * status bar has always been about one project there, and adding "Folder: myrepo" to every
 * hover would be noise for the overwhelming majority of windows.
 */
export function folderTooltipLine(
  names: readonly string[],
  activeName: string | undefined
): string | undefined {
  if (names.length < 2) {
    return undefined;
  }
  const active = activeName ?? names[0];
  // `names.length - 1`, not a filter: two folders can legitimately have the SAME name
  // (`api/` under two checkouts), and filtering by name would then report "0 others".
  const others = names.length - 1;
  return `Folder: ${active} — ${others} other folder${others === 1 ? '' : 's'} in this workspace is not shown here.`;
}

/** The quick-pick rows for the folder picker. Pure; `detail` is the path a name cannot carry. */
export function folderPickItems(
  folders: readonly { name: string; fsPath: string }[],
  activeKey: string | undefined
): { label: string; description?: string; detail: string; key: string }[] {
  return folders.map((folder) => {
    const key = folderKey(folder.fsPath);
    return {
      label: folder.name,
      ...(key === activeKey ? { description: 'active' } : {}),
      detail: folder.fsPath,
      key
    };
  });
}

/**
 * The per-folder map. Holds state only for folders that are OPEN; `prune` is what a
 * `onDidChangeWorkspaceFolders` calls so a closed folder's graph cannot go on publishing
 * diagnostics for files nobody has open.
 */
export class FolderBook {
  private readonly states = new Map<string, FolderState>();
  private activeKey: string | undefined;

  /** The open folders, in the order VS Code lists them. */
  open(): readonly vscode.WorkspaceFolder[] {
    return vscode.workspace.workspaceFolders ?? [];
  }

  /**
   * The folder every "one graph" surface means. The remembered choice when it is still open,
   * otherwise the first folder — which is precisely the old `workspaceFolders?.[0]`, so a
   * single-folder window behaves exactly as it did.
   */
  activeFolder(): vscode.WorkspaceFolder | undefined {
    const folders = this.open();
    if (this.activeKey) {
      const remembered = folders.find((f) => folderKey(f.uri.fsPath) === this.activeKey);
      if (remembered) {
        return remembered;
      }
    }
    return folders[0];
  }

  activeFolderKey(): string | undefined {
    const folder = this.activeFolder();
    return folder ? folderKey(folder.uri.fsPath) : undefined;
  }

  /** Returns true when the active folder actually moved. */
  setActive(folder: vscode.WorkspaceFolder | undefined): boolean {
    const key = folder ? folderKey(folder.uri.fsPath) : undefined;
    if (key === this.activeKey) {
      return false;
    }
    this.activeKey = key;
    return true;
  }

  /** The state of one folder, created empty on first use. */
  stateFor(folder: vscode.WorkspaceFolder): FolderState {
    const key = folderKey(folder.uri.fsPath);
    const existing = this.states.get(key);
    if (existing) {
      return existing;
    }
    const created: FolderState = {
      key,
      root: folder.uri.fsPath,
      name: folder.name,
      lastScope: { scope: 'workspace' },
      staleFiles: new Set<string>()
    };
    this.states.set(key, created);
    return created;
  }

  /** The active folder's state, or undefined when no folder is open at all. */
  active(): FolderState | undefined {
    const folder = this.activeFolder();
    return folder ? this.stateFor(folder) : undefined;
  }

  /** Every state that has a graph — the set the Problems panel must publish as a whole. */
  analyzed(): FolderState[] {
    return [...this.states.values()].filter((s) => s.graph !== undefined);
  }

  /**
   * The state whose analyzed root contains `fsPath`, matched on `graph.workspace.root` rather
   * than on the folder — a `file:` scope analyses a package directory, and the graph it
   * produced is still the one that knows about that file.
   */
  stateForAnalyzedFile(fsPath: string): FolderState | undefined {
    const target = folderKey(fsPath);
    for (const state of this.analyzed()) {
      const root = folderKey(state.graph?.workspace.root ?? state.root);
      if (target === root || target.startsWith(`${root}/`)) {
        return state;
      }
    }
    return undefined;
  }

  /** Drop the states of folders that are no longer open. Returns how many went. */
  prune(): number {
    const live = new Set(this.open().map((f) => folderKey(f.uri.fsPath)));
    let dropped = 0;
    for (const key of [...this.states.keys()]) {
      if (!live.has(key)) {
        this.states.delete(key);
        dropped += 1;
      }
    }
    if (this.activeKey && !live.has(this.activeKey)) {
      this.activeKey = undefined;
    }
    return dropped;
  }

  /** Forget every graph, keeping the folders themselves. Used by the folder-change reset. */
  clear(): void {
    this.states.clear();
    this.activeKey = undefined;
  }
}

/**
 * `MLView: Select Active Folder` and the status-bar tooltip's picker share this. Returns the
 * chosen folder, or undefined when the user cancelled — and answers immediately in the
 * one-folder case rather than offering a pick with a single row.
 */
export async function pickFolder(
  book: FolderBook
): Promise<vscode.WorkspaceFolder | undefined> {
  const folders = book.open();
  if (folders.length === 0) {
    void vscode.window.showWarningMessage('MLView: no folder is open in this window.');
    return undefined;
  }
  if (folders.length === 1) {
    return folders[0];
  }
  const items = folderPickItems(
    folders.map((f) => ({ name: f.name, fsPath: f.uri.fsPath })),
    book.activeFolderKey()
  );
  const picked = await vscode.window.showQuickPick(items, {
    title: 'MLView — analyze which folder?',
    placeHolder: 'The diagram, the status bar and the chat answers all follow this folder'
  });
  if (!picked) {
    return undefined;
  }
  return folders.find((f) => folderKey(f.uri.fsPath) === picked.key);
}
