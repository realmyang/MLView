import { randomBytes } from 'node:crypto';
import * as vscode from 'vscode';

export function createNonce(): string {
  return randomBytes(24).toString('base64');
}

/**
 * The webview's theme word. Both high-contrast kinds map to `hc`: the viewer's HC palette is
 * built from VS Code's own `--vscode-*` colours, so it serves HC Dark and HC Light alike.
 */
export function themeKindOf(kind: vscode.ColorThemeKind): 'light' | 'dark' | 'hc' {
  if (kind === vscode.ColorThemeKind.HighContrast || kind === vscode.ColorThemeKind.HighContrastLight) {
    return 'hc';
  }
  if (kind === vscode.ColorThemeKind.Light) {
    return 'light';
  }
  return 'dark';
}

export function toEditorLine(line: number): number {
  return Math.max(0, line - 1);
}
