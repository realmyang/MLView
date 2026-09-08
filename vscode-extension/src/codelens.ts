/**
 * "MLView: show in diagram" above every analyzed unit (a class, function or loop), anchored on
 * the unit's `defLoc` when it has one and its `loc` otherwise. Toggled by `mlview.codeLens`.
 */

import * as vscode from 'vscode';
import type { MLGraph } from './graph';
import { toEditorLine, toWorkspaceRelative } from './location';
import { unitAnchors } from './locationIndex';

export const CODELENS_TITLE = 'MLView: show in diagram';

export class MlviewCodeLensProvider implements vscode.CodeLensProvider {
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.emitter.event;

  constructor(
    private readonly getGraph: () => MLGraph | undefined,
    private readonly isEnabled: () => boolean
  ) {}

  refresh(): void {
    this.emitter.fire();
  }

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (!this.isEnabled()) {
      return [];
    }
    const graph = this.getGraph();
    if (!graph || graph.nodes.length === 0) {
      return [];
    }
    const relative = toWorkspaceRelative(graph.workspace.root, document.uri.fsPath);
    const anchors = unitAnchors(graph, relative);
    const lenses: vscode.CodeLens[] = [];
    for (const anchor of anchors) {
      // toEditorLine is THE conversion (CONTRACTS.md §0); the clamp keeps a stale graph in range.
      const line = Math.min(toEditorLine(anchor.line), Math.max(0, document.lineCount - 1));
      lenses.push(
        new vscode.CodeLens(new vscode.Range(line, 0, line, 0), {
          title: CODELENS_TITLE,
          tooltip: `Reveal "${anchor.label}" in the MLView diagram`,
          command: 'mlview.revealInDiagram',
          arguments: [{ nodeId: anchor.nodeId }]
        })
      );
    }
    return lenses;
  }

  dispose(): void {
    this.emitter.dispose();
  }
}
