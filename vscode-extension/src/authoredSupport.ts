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

/** Why a tracked file no longer matches its published fingerprint (workflowDocument.ts `StaleReason`). */
type StaleReasonWord = 'changed' | 'missing' | 'unreadable' | 'too-large';

const STALE_ORDER: readonly StaleReasonWord[] = ['changed', 'missing', 'unreadable', 'too-large'];
const STALE_WORD: Record<StaleReasonWord, string> = {
    changed: 'changed',
    missing: 'missing',
    unreadable: 'unreadable',
    'too-large': 'too large to check'
};

/**
 * "1 changed, 2 missing" — the stale set counted by reason, in a fixed order (Campaign 3,
 * issue 21). Null when every file simply changed, which keeps the established wording.
 */
export function staleBreakdown(stale: readonly { reason: StaleReasonWord }[]): string | null {
    const counts = new Map<StaleReasonWord, number>();
    for (const file of stale)
        counts.set(file.reason, (counts.get(file.reason) ?? 0) + 1);
    if (!stale.length || (counts.size === 1 && counts.has('changed')))
        return null;
    return STALE_ORDER.filter(reason => counts.has(reason)).map(reason => `${counts.get(reason)} ${STALE_WORD[reason]}`).join(', ');
}

/**
 * The stale banner. A deleted cited file used to be reported as "changed"; the reason each file
 * is stale now shapes the sentence, and in a mixed set every file that did not merely change is
 * marked with its reason. `list` bounds and escapes the names (authoredPanel.ts `listFiles`).
 */
export function staleBannerText(stale: readonly { rel: string; reason: StaleReasonWord }[], revisionId: string, list: (names: readonly string[]) => string): string {
    const tail = 'Jumps into those files are blocked; other evidence still opens. Ask the assistant to publish a fresh revision to update the diagram.';
    const breakdown = staleBreakdown(stale);
    if (breakdown === null)
        return `This historical diagram is visible, but ${stale.length} source file(s) changed after revision ${revisionId} was published: ${list(stale.map(s => s.rel))}. ${tail}`;
    const mixed = new Set(stale.map(s => s.reason)).size > 1;
    const names = stale.map(s => (mixed && s.reason !== 'changed' ? `${s.rel} (${STALE_WORD[s.reason]})` : s.rel));
    return `This historical diagram is visible, but ${stale.length} source file(s) no longer match revision ${revisionId} as published (${breakdown}): ${list(names)}. ${tail}`;
}

/** The one-time warning toast for the same set. */
export function staleToastText(stale: readonly { reason: StaleReasonWord }[]): string {
    const breakdown = staleBreakdown(stale);
    return breakdown === null
        ? `MLView: ${stale.length} source file(s) changed after the displayed revision was published.`
        : `MLView: ${stale.length} source file(s) no longer match the displayed revision (${breakdown}).`;
}

/** Why a jump into one stale file is blocked, in the words of its reason. */
export function staleJumpText(evidenceId: string, file: string, reason: StaleReasonWord, revisionId: string): string {
    const why = reason === 'missing'
        ? `which is missing since revision ${revisionId} was published`
        : reason === 'unreadable'
            ? `which can no longer be read (it could when revision ${revisionId} was published)`
            : reason === 'too-large'
                ? `which has grown past the size MLView can check since revision ${revisionId} was published`
                : `which changed after revision ${revisionId} was published`;
    return `MLView: evidence ${evidenceId} cites ${file}, ${why}; navigation to it is blocked.`;
}
