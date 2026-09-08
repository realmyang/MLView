/**
 * Code -> scope (`Alt+Shift+M`, the editor context menu, the command palette).
 *
 * CONTRACTS.md §11.11. `mlview.scopeToSymbol` resolves the cursor to its ENCLOSING UNIT and
 * posts `setScope` with a `unit:<qualname>` selector; `mlview.clearScope` posts `spec: null`.
 * Both mirror `revealInDiagram.ts`: an active editor, then the graph, then the panel, then one
 * message. Nothing here analyses, and nothing here touches diagnostics — a scope is a view
 * (F2-A11).
 *
 * When the cursor is inside no node at all we show the same "no node here" toast the reveal
 * path uses and stop. A scope is never guessed: `findNodeAtLine`'s nearest-node fallback would
 * silently narrow the diagram to something the user did not point at.
 */

import * as vscode from 'vscode';
import type { MLGraph } from './graph';
import { toGraphLine, toWorkspaceRelative } from './location';
import { findEnclosingUnit, type LocationIndex } from './locationIndex';
import type { Logger } from './log';
import type { MlviewPanel } from './panel';

/** The `unit:` selector kind of the §11.1 grammar — the only one this host produces. */
export const SCOPE_KIND_UNIT = 'unit';

/** `unit:<qualname>`, the normalized §11.1 selector for one resolved unit. */
export function unitScopeSpec(qualname: string): string {
  return `${SCOPE_KIND_UNIT}:${qualname.trim()}`;
}

export interface ScopeDeps {
  log: Logger;
  getGraph(): MLGraph | undefined;
  getIndex(): LocationIndex | undefined;
  /** Opens (or reveals) the diagram panel and returns it, or undefined when it cannot open. */
  ensurePanel(): Promise<MlviewPanel | undefined>;
  /** The live diagram panel, or undefined when none is open. NEVER opens one. */
  getPanel(): MlviewPanel | undefined;
  /** Runs an analysis when there is no graph yet. */
  ensureGraph(): Promise<MLGraph | undefined>;
}

/** `MLView: Scope Diagram to Symbol`. */
export async function scopeToSymbol(deps: ScopeDeps): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    void vscode.window.showInformationMessage(
      'MLView: open a Python file to scope the diagram to a symbol.'
    );
    return;
  }

  let graph = deps.getGraph();
  if (!graph) {
    graph = await deps.ensureGraph();
  }
  if (!graph) {
    return;
  }
  const index = deps.getIndex();
  if (!index) {
    return;
  }

  const relative = toWorkspaceRelative(graph.workspace.root, editor.document.uri.fsPath);
  // The single boundary conversion, in the one module allowed to do it (CONTRACTS.md §0).
  const line = toGraphLine(editor.selection.active.line);
  const unit = findEnclosingUnit(index, relative, line);
  if (!unit) {
    void vscode.window.showInformationMessage(
      `MLView: no diagram node was found in ${relative}. Re-analyze if the file is new.`
    );
    deps.log.info(`scope: no enclosing unit for ${relative}:${line}`);
    return;
  }

  const panel = await deps.ensurePanel();
  if (!panel) {
    return;
  }
  const spec = unitScopeSpec(unit.qualname);
  panel.postSetScope(spec);
  deps.log.debug(
    `scope: ${relative}:${line} -> ${spec} (from ${unit.fromNodeId} "${unit.fromLabel}")`
  );
}

/**
 * `MLView: Clear Diagram Scope` — back to the whole workspace, filters untouched.
 *
 * Clearing is only meaningful for a diagram that is already on screen, so this path uses
 * `getPanel()` and NOT `ensurePanel()`: running the palette command in a window that never
 * opened MLView must stay a no-op rather than pop an empty panel to clear a scope that
 * cannot exist. `scopeToSymbol` keeps `ensurePanel` — it has something to show.
 */
export async function clearScope(deps: ScopeDeps): Promise<void> {
  const panel = deps.getPanel();
  if (!panel) {
    deps.log.debug('scope: clear ignored, no diagram panel is open');
    return;
  }
  panel.postSetScope(null);
  deps.log.debug('scope: cleared');
}
