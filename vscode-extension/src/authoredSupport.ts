import { randomBytes } from 'node:crypto';
import * as vscode from 'vscode';

export function createNonce(): string {
  return randomBytes(24).toString('base64');
}

export function themeKindOf(kind: vscode.ColorThemeKind): 'light' | 'dark' | 'high-contrast' {
  if (kind === vscode.ColorThemeKind.Light || kind === vscode.ColorThemeKind.HighContrastLight) {
    return 'light';
  }
  if (kind === vscode.ColorThemeKind.HighContrast) {
    return 'high-contrast';
  }
  return 'dark';
}

export function toEditorLine(line: number): number {
  return Math.max(0, line - 1);
}
