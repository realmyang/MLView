/**
 * MLV-P10 — suppression as a one-click action (docs/contracts/11.27-suppression-actions.md).
 *
 * The lightbulb on any MLView diagnostic offers three things, and the diagram's own
 * rail reaches the same three through the `suppressRule` message so a user is never
 * told two different stories about how to silence a finding:
 *
 *   Copy ignore comment for MLV201          -> the clipboard, with a toast
 *   Add ignore comment on this line (MLV201) -> a WorkspaceEdit on the open document
 *   Disable rule MLV201 in .mlview.toml      -> a confirmed write at the workspace root
 *
 * Three rules this module keeps, all of them the reason it is its own file:
 *
 * 1. **A suppression is not a fix.** `REQUIREMENTS.md` §5 non-goal 5 bars quick fixes
 *    that edit ML logic; a comment and a config key edit neither, which is exactly
 *    why MLV-P10 sits inside the non-goal rather than lifting it.
 * 2. **The config write is confirmed, and never leaves the workspace.** Disabling a
 *    rule is a project-wide decision someone else will inherit, so it asks first, and
 *    the path is checked against the workspace root the same way every other write
 *    path in this repo is.
 * 3. **Nothing here analyses.** The rule code comes from a diagnostic the analyzer
 *    published; this module only ever moves text around.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { DIAGNOSTIC_SOURCE } from './diagnostics';
// CONTRACTS §0: "convert exactly once, at the host boundary" — src/location.ts owns the
// 1-based-graph <-> 0-based-editor arithmetic, and `test/invariants.test.js` enforces it.
import { toEditorLine, toGraphLine } from './location';
import type { Logger } from './log';
import {
  addDisabledRule,
  ignoreComment,
  insideAnyWorkspace,
  isInsideWorkspace,
  isRuleCode,
  withIgnoreComment
} from './suppression';

export const COPY_IGNORE_COMMAND = 'mlview.copyIgnoreComment';
export const ADD_IGNORE_COMMAND = 'mlview.addIgnoreComment';
export const DISABLE_RULE_COMMAND = 'mlview.disableRule';

export const CONFIG_FILE = '.mlview.toml';

/** The rule code a published diagnostic carries, whichever shape it is in. */
export function diagnosticCode(diagnostic: vscode.Diagnostic): string | undefined {
  const code = diagnostic.code;
  if (typeof code === 'string') {
    return isRuleCode(code) ? code : undefined;
  }
  if (code && typeof code === 'object' && 'value' in code) {
    const value = (code as { value: unknown }).value;
    return isRuleCode(value) ? value : undefined;
  }
  return undefined;
}

/** MLView's own diagnostics in `context`, deduped by rule code, in first-seen order. */
export function mlviewCodesIn(diagnostics: readonly vscode.Diagnostic[]): string[] {
  const codes: string[] = [];
  for (const diagnostic of diagnostics) {
    if (diagnostic.source !== DIAGNOSTIC_SOURCE) {
      continue;
    }
    const code = diagnosticCode(diagnostic);
    if (code && !codes.includes(code)) {
      codes.push(code);
    }
  }
  return codes;
}

export function copyActionTitle(code: string): string {
  return `Copy ignore comment for ${code}`;
}

export function addActionTitle(code: string): string {
  return `Add ignore comment on this line (${code})`;
}

export function disableActionTitle(code: string): string {
  return `Disable rule ${code} in ${CONFIG_FILE}`;
}

/**
 * The provider. It answers from `context.diagnostics` alone — no graph lookup, no
 * analysis — so the lightbulb is instant and works on a stale document too.
 */
export class MlviewCodeActionProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    void range;
    const actions: vscode.CodeAction[] = [];
    for (const code of mlviewCodesIn(context.diagnostics)) {
      const anchor = context.diagnostics.find(
        (d) => d.source === DIAGNOSTIC_SOURCE && diagnosticCode(d) === code
      );
      const line = anchor?.range.start.line ?? 0;
      const related = anchor ? [anchor] : [];

      const copy = new vscode.CodeAction(copyActionTitle(code), vscode.CodeActionKind.QuickFix);
      copy.command = {
        command: COPY_IGNORE_COMMAND,
        title: copyActionTitle(code),
        arguments: [code]
      };
      copy.diagnostics = related;

      const add = new vscode.CodeAction(addActionTitle(code), vscode.CodeActionKind.QuickFix);
      add.command = {
        command: ADD_IGNORE_COMMAND,
        title: addActionTitle(code),
        arguments: [document.uri, line, code]
      };
      add.diagnostics = related;
      // The one action that changes the file the user is looking at is the one they
      // almost always mean, so it is the preferred fix.
      add.isPreferred = true;

      const disable = new vscode.CodeAction(
        disableActionTitle(code),
        vscode.CodeActionKind.QuickFix
      );
      disable.command = {
        command: DISABLE_RULE_COMMAND,
        title: disableActionTitle(code),
        arguments: [code, document.uri]
      };
      disable.diagnostics = related;

      actions.push(copy, add, disable);
    }
    return actions;
  }
}

/** `# mlview: ignore[MLV201]` to the clipboard, with the toast the deep-link path uses. */
export async function copyIgnoreComment(code: string, log: Logger): Promise<boolean> {
  if (!isRuleCode(code)) {
    log.warn(`refusing to copy an ignore comment for a non-rule code: ${String(code)}`);
    return false;
  }
  const text = ignoreComment(code);
  await vscode.env.clipboard.writeText(text);
  void vscode.window.setStatusBarMessage(`MLView: copied ${text}`, 3000);
  log.info(`copied ${text}`);
  return true;
}

/**
 * Insert (or merge into) the ignore comment on one line, through a `WorkspaceEdit` so
 * it lands in the editor's undo stack rather than behind the user's back.
 */
export async function addIgnoreComment(
  uri: vscode.Uri,
  line: number,
  code: string,
  log: Logger
): Promise<boolean> {
  if (!isRuleCode(code)) {
    log.warn(`refusing to insert an ignore comment for a non-rule code: ${String(code)}`);
    return false;
  }
  let document: vscode.TextDocument;
  try {
    document = await vscode.workspace.openTextDocument(uri);
  } catch (err) {
    log.warn(`could not open ${uri.fsPath} to insert an ignore comment: ${String(err)}`);
    return false;
  }
  if (line < 0 || line >= document.lineCount) {
    log.warn(`line ${toGraphLine(line)} is outside ${uri.fsPath} (${document.lineCount} lines)`);
    return false;
  }
  const existing = document.lineAt(line);
  const edit = withIgnoreComment(existing.text, code);
  if (!edit.changed) {
    void vscode.window.showInformationMessage(
      edit.reason === 'already-blanket'
        ? `MLView: line ${toGraphLine(line)} already carries a blanket ignore comment.`
        : `MLView: ${code} is already ignored on line ${toGraphLine(line)}.`
    );
    return false;
  }
  const workspaceEdit = new vscode.WorkspaceEdit();
  workspaceEdit.replace(
    uri,
    new vscode.Range(line, 0, line, existing.text.length),
    edit.text
  );
  const applied = await vscode.workspace.applyEdit(workspaceEdit);
  if (applied) {
    log.info(`inserted ${ignoreComment(code)} at ${uri.fsPath}:${toGraphLine(line)}`);
  } else {
    log.warn(`the ignore-comment edit for ${uri.fsPath}:${toGraphLine(line)} was rejected`);
  }
  return applied;
}

/** The open workspace roots, in order, as absolute filesystem paths. */
function workspaceRoots(): string[] {
  return (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
}

/**
 * The absolute path of a file MLView is allowed to WRITE to, or `undefined`.
 *
 * §11.27 S4's containment rule is enforced here, at the one place a path arrives from
 * outside the extension: `suppressRule.absFile` is whatever the webview posted, and an
 * unchecked `Uri.file(...)` + `applyEdit` would append a comment to any file on the disk.
 * A refusal is logged rather than silently rewritten, for the reason `isExportFile` gives
 * in protocol.ts: a rejected write is visible and a redirected one is not.
 */
export function writableFile(absFile: string, log: Logger): string | undefined {
  const resolved = path.resolve(absFile);
  const roots = workspaceRoots();
  if (roots.length === 0) {
    log.warn(`refusing to edit ${resolved}: no folder is open, so nothing is inside the workspace`);
    return undefined;
  }
  if (!insideAnyWorkspace(roots, resolved)) {
    log.warn(`refusing to edit ${resolved}: it is outside every open workspace folder`);
    return undefined;
  }
  return resolved;
}

/** Where the containment rule says a `.mlview.toml` may be written for `uri`. */
export function configPathFor(uri?: vscode.Uri): { root: string; file: string } | undefined {
  const folder =
    (uri ? vscode.workspace.getWorkspaceFolder(uri) : undefined) ??
    vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    return undefined;
  }
  const root = folder.uri.fsPath;
  const file = path.join(root, CONFIG_FILE);
  // A constant basename joined to a root cannot escape it, so this is an invariant rather
  // than a guard: the guard for a path that came from OUTSIDE is `writableFile` above.
  return isInsideWorkspace(root, file) ? { root, file } : undefined;
}

/**
 * `[rules] disable = [...]` at the workspace root, behind an explicit confirm.
 *
 * The confirm is not ceremony: this silences the rule for everybody who opens the
 * repo, including CI, and it is the one gesture in MLV-P10 that a user cannot see
 * the consequences of from where they clicked.
 */
export async function disableRule(code: string, uri: vscode.Uri | undefined, log: Logger): Promise<boolean> {
  if (!isRuleCode(code)) {
    log.warn(`refusing to disable a non-rule code: ${String(code)}`);
    return false;
  }
  const target = configPathFor(uri);
  if (!target) {
    void vscode.window.showWarningMessage(
      `MLView: open a folder before disabling ${code} — ${CONFIG_FILE} is written at the workspace root.`
    );
    return false;
  }
  const choice = await vscode.window.showWarningMessage(
    `Disable ${code} for the whole workspace?`,
    {
      modal: true,
      detail:
        `MLView will add ${code} to [rules] disable in ${target.file}. ` +
        'Every file in this workspace stops reporting it, for everyone who opens the repo ' +
        'and for CI. To silence this one finding instead, use "Add ignore comment on this line".'
    },
    `Disable ${code}`
  );
  if (choice === undefined) {
    log.info(`disabling ${code} was cancelled`);
    return false;
  }
  let current = '';
  try {
    if (fs.existsSync(target.file)) {
      current = fs.readFileSync(target.file, 'utf8');
    }
  } catch (err) {
    log.warn(`could not read ${target.file}: ${String(err)}`);
    void vscode.window.showWarningMessage(`MLView: could not read ${CONFIG_FILE}: ${String(err)}`);
    return false;
  }
  const next = addDisabledRule(current, code);
  if (!next.changed) {
    void vscode.window.showInformationMessage(
      `MLView: ${code} is already disabled in ${CONFIG_FILE}.`
    );
    return false;
  }
  try {
    fs.writeFileSync(target.file, next.text, 'utf8');
  } catch (err) {
    log.warn(`could not write ${target.file}: ${String(err)}`);
    void vscode.window.showWarningMessage(`MLView: could not write ${CONFIG_FILE}: ${String(err)}`);
    return false;
  }
  log.info(`disabled ${code} in ${target.file}`);
  void vscode.window.showInformationMessage(
    `MLView: ${code} disabled in ${CONFIG_FILE}. Run "MLView: Re-analyze" to refresh the findings.`
  );
  return true;
}

/** What the webview's `suppressRule` message asks for; see protocol.ts. */
export interface SuppressRequest {
  code: string;
  action: 'copy' | 'insert' | 'disable';
  absFile?: string;
  /** 1-based, as every location in the graph document is (CONTRACTS §0). */
  line?: number;
}

/**
 * The single entry point both surfaces use. The lightbulb and the diagram rail must
 * do the SAME thing — including the confirm dialog and the containment check — or
 * "disable this rule" means two different things depending on where it was clicked.
 */
export async function runSuppression(request: SuppressRequest, log: Logger): Promise<boolean> {
  switch (request.action) {
    case 'copy':
      return copyIgnoreComment(request.code, log);
    case 'insert': {
      if (!request.absFile || typeof request.line !== 'number' || request.line < 1) {
        log.warn('suppressRule(insert) needs absFile and a 1-based line');
        return copyIgnoreComment(request.code, log);
      }
      // The path came from the webview, so it is checked HERE, before anything opens it.
      // Outside the workspace the gesture degrades to the clipboard, exactly as a missing
      // absFile does: the user still gets the comment, and no stranger's file is edited.
      const file = writableFile(request.absFile, log);
      if (file === undefined) {
        return copyIgnoreComment(request.code, log);
      }
      return addIgnoreComment(
        vscode.Uri.file(file),
        toEditorLine(request.line),
        request.code,
        log
      );
    }
    case 'disable':
      return disableRule(
        request.code,
        request.absFile ? vscode.Uri.file(path.resolve(request.absFile)) : undefined,
        log
      );
    default:
      return false;
  }
}

/** Register the provider and its three commands. Called unconditionally at activation. */
export function registerSuppressionActions(log: Logger): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand(COPY_IGNORE_COMMAND, (code: string) =>
      copyIgnoreComment(code, log)
    ),
    vscode.commands.registerCommand(
      ADD_IGNORE_COMMAND,
      (uri: vscode.Uri, line: number, code: string) => addIgnoreComment(uri, line, code, log)
    ),
    vscode.commands.registerCommand(DISABLE_RULE_COMMAND, (code: string, uri?: vscode.Uri) =>
      disableRule(code, uri, log)
    ),
    vscode.languages.registerCodeActionsProvider(
      { language: 'python' },
      new MlviewCodeActionProvider(),
      { providedCodeActionKinds: MlviewCodeActionProvider.providedCodeActionKinds }
    )
  ];
}
