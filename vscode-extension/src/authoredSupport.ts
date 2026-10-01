import { createHash, randomBytes } from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
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

/** A folder under the workspace root where the missing cited files exist with their published hashes. */
export interface RootHint {
    /** Absolute path of the folder the citations resolve against. */
    base: string;
    /** Absolute path of the workspace folder the panel validates against. */
    root: string;
    /** The missing tracked files (cited or inspected) found there with matching hashes. */
    files: string[];
}

const inside = (child: string, parent: string): boolean => {
    const rel = path.relative(parent, child);
    return !!rel && rel !== '..' && !rel.startsWith('..' + path.sep) && !path.isAbsolute(rel);
};

/**
 * The folders that could hold the citations instead of `root`: the artifact's own folder and its
 * parents, nearest first, stopping before `root`. The helper writes an artifact inside the folder
 * its citations are relative to, so a folder that does not contain the artifact cannot be the
 * right root.
 */
export function rootHintCandidates(artifact: string, root: string): string[] {
    const top = path.resolve(root);
    const out: string[] = [];
    let dir = path.dirname(path.resolve(artifact));
    while (inside(dir, top)) {
        out.push(dir);
        const up = path.dirname(dir);
        if (up === dir)
            break;
        dir = up;
    }
    return out;
}

/**
 * The missing files to look for, when most of the hashed tracked files are missing (a strict
 * majority); otherwise an empty list. Only files with a published hash count, because only those
 * can be confirmed elsewhere.
 */
export function mostlyMissing(tracked: readonly string[], published: Readonly<Record<string, string>>, stale: readonly { rel: string; reason: string }[]): string[] {
    const own = (rel: string): boolean => Object.prototype.hasOwnProperty.call(published, rel);
    const hashed = new Set(tracked.filter(own));
    const missing = stale.filter(s => s.reason === 'missing' && hashed.has(s.rel)).map(s => s.rel);
    return missing.length * 2 > hashed.size ? missing : [];
}

/**
 * Look for a folder where every missing file exists with its published SHA-256. Product
 * validation never uses the result: it only words the hint. Each file is read as raw bytes, at
 * most `limit` bytes, and must resolve inside the candidate folder.
 */
export async function findRootHint(input: {
    tracked: readonly string[];
    published: Readonly<Record<string, string>>;
    stale: readonly { rel: string; reason: string }[];
    artifact: string;
    root: string;
    limit: number;
    readBytes: (absolutePath: string, limit: number) => Promise<Uint8Array>;
}): Promise<RootHint | undefined> {
    const missing = mostlyMissing(input.tracked, input.published, input.stale);
    if (!missing.length)
        return undefined;
    for (const base of rootHintCandidates(input.artifact, input.root)) {
        let realBase: string;
        try {
            realBase = await fs.realpath(base);
        }
        catch {
            continue;
        }
        let all = true;
        for (const rel of missing) {
            try {
                const real = await fs.realpath(path.join(base, ...rel.split('/')));
                if (!inside(real, realBase)) {
                    all = false;
                    break;
                }
                const bytes = await input.readBytes(real, input.limit);
                if (createHash('sha256').update(bytes).digest('hex') !== input.published[rel]) {
                    all = false;
                    break;
                }
            }
            catch {
                all = false;
                break;
            }
        }
        if (all)
            return { base, root: input.root, files: missing };
    }
    return undefined;
}

/** A folder as the reader sees it in the hint: relative to the workspace root, with a trailing slash. */
export function hintFolderName(hint: RootHint): string {
    const rel = path.relative(hint.root, hint.base).split(path.sep).join('/');
    return './' + rel + '/';
}

/** The banner and notification text for a root hint. */
export function rootHintText(hint: RootHint, list: (names: readonly string[]) => string): string {
    const root = list([path.basename(hint.root) || hint.root]);
    const folder = list([hintFolderName(hint)]);
    const one = hint.files.length === 1;
    return `${one ? 'This file exists' : 'These files exist'} under ${folder} but the workspace root is ${root}: ${list(hint.files)}. ` +
        `${one ? 'It matches its' : 'They match their'} published hash${one ? '' : 'es'}, so the source did not change; MLView looks for ${one ? 'it' : 'them'} in the wrong folder. ` +
        `Add ${folder} to the workspace, or open it in its own window.`;
}
