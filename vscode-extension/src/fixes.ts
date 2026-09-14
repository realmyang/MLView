/**
 * H5 — structured fixes, host half.
 *
 * `REQUIREMENTS.md` §5 non-goal 5 barred quick fixes that edit ML logic. The lead lifted it
 * for H5 with five guardrails, and FOUR of the five are enforced right here, in the one
 * module that turns an analyzer finding into an edit of somebody's training loop:
 *
 *   1. **Rules opt in.** `Issue.fix` is absent on every rule that did not compute an edit, so
 *      the lightbulb is empty rather than lying. Nothing in this file invents a fix.
 *   2. **The edits come from the analyzer's AST**, never from string splicing here. This
 *      module validates coordinates and builds a `WorkspaceEdit`; it never reads the source
 *      to decide what to write.
 *   3. **`isPreferred` only for `mechanical`.** A `needs-review` fix is offered, never
 *      promoted: `Ctrl+.`+Enter and "fix all" must not land on a judgement call.
 *   4. **Never auto-applied.** Every entry carries `needsConfirmation`, and the edit is
 *      applied with `isRefactoring: true`, so VS Code routes it through the refactor PREVIEW
 *      — the user sees the diff and picks. There is deliberately no `source.fixAll` kind
 *      here: that is the kind `editor.codeActionsOnSave` runs behind your back. And the
 *      lightbulb carries a COMMAND rather than a `WorkspaceEdit`, so that it too goes through
 *      `applyIssueFix` instead of VS Code's bulk-edit service.
 *
 * The fifth guardrail — no fix below the `likely` bucket — is the analyzer's to enforce and
 * is re-checked here anyway (`FIXABLE_BUCKETS`), because this is the module that does the
 * damage if the other half is wrong, and a speculative edit to a training loop is exactly
 * the high-severity failure the product cannot survive.
 *
 * **What this cannot do, stated where it is decided.** It cannot verify that the analyzer's
 * coordinates match the buffer the user is looking at: a document edited since the analysis
 * may have moved the line, and VS Code's preview is the mitigation, not a proof. It refuses
 * outright rather than guessing whenever ANY edit of a fix is unusable — a partially applied
 * fix is worse than none. And it never touches a notebook cell: a finding inside an `.ipynb`
 * names the generated shadow module, and editing that would write to a file the user does
 * not own.
 */

import * as vscode from 'vscode';
import { writableFile } from './codeActions';
import { DIAGNOSTIC_SOURCE } from './diagnostics';
import type { FixEdit, Issue, IssueFix, MLGraph } from './graph';
// CONTRACTS §0: the 1-based-graph <-> 0-based-editor arithmetic happens exactly once.
import { toRangeTuple } from './location';
import type { Logger } from './log';

export const APPLY_FIX_COMMAND = 'mlview.applyFix';

/** H5: no fix at all below `likely`. The analyzer enforces it; so does the host. */
export const FIXABLE_BUCKETS: readonly string[] = ['certain', 'likely'];

/** `mechanical` is an unambiguous slot; `needs-review` is a judgement call, offered unranked. */
export const FIX_SAFETIES: readonly string[] = ['mechanical', 'needs-review'];

/** A fix is a small, local repair. Anything larger is a refactor and not this feature. */
export const MAX_FIX_EDITS = 16;

/** Bytes of replacement text one edit may carry. `zero_grad()` is 20; 8 KiB is generous. */
export const MAX_FIX_TEXT_CHARS = 8192;

export type FixRefusal =
  | 'no-fix'
  | 'low-confidence'
  | 'malformed'
  | 'too-many-edits'
  | 'outside-workspace'
  | 'stale-document';

export type FixReading =
  | { ok: true; fix: IssueFix }
  | { ok: false; reason: FixRefusal; detail: string };

/**
 * A coordinate is an INTEGER line/column or it is not a coordinate.
 *
 * `Number.isFinite` alone would let `3.9` through and `Math.trunc` would then quietly turn it
 * into line 3 — a half-understood coordinate written into somebody's file, which is precisely
 * what §11.43 A6 says this module exists to refuse. The value arrives from a child process, so
 * "the current analyzer only emits ints" is not a check.
 */
function isCoordinate(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

/** One edit, structurally. `endLine`/`endCol` may equal the start: that is an insertion. */
function readEdit(raw: unknown): FixEdit | undefined {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const edit = raw as Record<string, unknown>;
  const absFile = edit['absFile'];
  const newText = edit['newText'];
  if (
    typeof absFile !== 'string' ||
    absFile.length === 0 ||
    absFile.includes('\0') ||
    !(/^[/\\]/.test(absFile) || /^[A-Za-z]:[/\\]/.test(absFile))
  ) {
    return undefined;
  }
  if (typeof newText !== 'string' || newText.length > MAX_FIX_TEXT_CHARS) {
    return undefined;
  }
  const line = edit['line'];
  const col = edit['col'];
  const endLine = edit['endLine'];
  const endCol = edit['endCol'];
  if (
    !isCoordinate(line) ||
    !isCoordinate(col) ||
    !isCoordinate(endLine) ||
    !isCoordinate(endCol)
  ) {
    return undefined;
  }
  if (line < 1 || endLine < line || col < 0 || endCol < 0) {
    return undefined;
  }
  if (endLine === line && endCol < col) {
    return undefined;
  }
  const file = edit['file'];
  // No `Math.trunc` here, deliberately: `isCoordinate` already refused anything fractional, and
  // a truncation would imply the check is somewhere else.
  return { file: typeof file === 'string' ? file : absFile, absFile, line, col, endLine, endCol, newText };
}

/**
 * Read `issue.fix` defensively, because it arrives from a child process: a core newer than
 * this extension may spell it differently, and the answer to that must be "no lightbulb",
 * never "an edit built from half-understood coordinates".
 */
export function readFix(issue: Pick<Issue, 'confidenceBucket'> & { fix?: unknown }): FixReading {
  const raw = issue.fix;
  if (raw === undefined || raw === null) {
    return { ok: false, reason: 'no-fix', detail: 'the rule did not opt in' };
  }
  if (!FIXABLE_BUCKETS.includes(String(issue.confidenceBucket))) {
    return {
      ok: false,
      reason: 'low-confidence',
      detail: `bucket ${String(issue.confidenceBucket)} is below "likely"`
    };
  }
  if (typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, reason: 'malformed', detail: 'fix is not an object' };
  }
  const fix = raw as Record<string, unknown>;
  const title = fix['title'];
  const safety = fix['safety'];
  const edits = fix['edits'];
  if (typeof title !== 'string' || title.trim().length === 0 || title.length > 200) {
    return { ok: false, reason: 'malformed', detail: 'fix.title' };
  }
  if (typeof safety !== 'string' || !FIX_SAFETIES.includes(safety)) {
    return { ok: false, reason: 'malformed', detail: `fix.safety ${String(safety)}` };
  }
  if (!Array.isArray(edits) || edits.length === 0) {
    return { ok: false, reason: 'malformed', detail: 'fix.edits is empty' };
  }
  if (edits.length > MAX_FIX_EDITS) {
    return { ok: false, reason: 'too-many-edits', detail: `${edits.length} edits` };
  }
  const read: FixEdit[] = [];
  for (const candidate of edits) {
    const one = readEdit(candidate);
    if (!one) {
      // All or nothing: half of a fix is a broken file, so one bad entry sinks the fix.
      return { ok: false, reason: 'malformed', detail: 'fix.edits[] entry' };
    }
    read.push(one);
  }
  return { ok: true, fix: { title: title.trim(), safety, edits: read } };
}

/** `true` when the fix is a single unambiguous slot, which is the only kind we promote. */
export function isMechanical(fix: IssueFix): boolean {
  return fix.safety === 'mechanical';
}

/**
 * Build the `WorkspaceEdit`, or refuse.
 *
 * HOST-6's containment rule applies to every path in the fix, not just the first: the
 * analyzer runs on a workspace the user opened, so an absolute path outside it means either
 * a stale document or something worse, and neither is a thing to write to. A refusal is
 * logged rather than silently redirected, for the reason `writableFile` gives.
 */
export function buildFixEdit(
  fix: IssueFix,
  log: Logger
): { ok: true; edit: vscode.WorkspaceEdit } | { ok: false; reason: FixRefusal; detail: string } {
  const edit = new vscode.WorkspaceEdit();
  for (const one of fix.edits) {
    const file = writableFile(one.absFile, log);
    if (file === undefined) {
      return { ok: false, reason: 'outside-workspace', detail: one.absFile };
    }
    const tuple = toRangeTuple(one);
    edit.replace(
      vscode.Uri.file(file),
      new vscode.Range(tuple.startLine, tuple.startChar, tuple.endLine, tuple.endChar),
      one.newText,
      {
        // THE never-auto-apply guarantee, per entry. VS Code shows the refactor preview
        // whenever an entry needs confirmation, so the user reads the diff before it lands.
        needsConfirmation: true,
        label: fix.title,
        description: `MLView · ${fix.safety}`
      }
    );
  }
  return { ok: true, edit };
}

/** The action title a user reads in the lightbulb. The code is there so two fixes never collide. */
export function fixActionTitle(issue: Pick<Issue, 'code'>, fix: IssueFix): string {
  return `${fix.title} (${issue.code})`;
}

/** What the fix surfaces need from the extension host. */
export interface FixDeps {
  readonly log: Logger;
  /** Every analyzed folder's graph — the Problems panel publishes the union, so this must too. */
  graphs(): readonly MLGraph[];
}

/** Every issue in every analyzed folder, in graph order. */
function allIssues(deps: FixDeps): Issue[] {
  return deps.graphs().flatMap((graph) => graph.issues ?? []);
}

/** The one issue an id names, or undefined. Ids are unique per document (§0). */
export function issueById(deps: FixDeps, issueId: string): Issue | undefined {
  return allIssues(deps).find((issue) => issue.id === issueId);
}

/**
 * The findings anchored in `document` whose range touches `range`, newest-analysis-first.
 *
 * Matching is on the graph, not on the published diagnostics, for one reason: a diagnostic
 * is filtered by `mlview.minConfidence` and re-anchored into notebook cells, and a fix must
 * be offered for exactly the finding it was computed for. The diagnostic is then attached to
 * the action when one happens to be there, so "fix all in file" and the Problems panel light
 * up correctly.
 */
export function issuesAt(
  deps: FixDeps,
  document: { uri: vscode.Uri },
  range: vscode.Range
): Issue[] {
  const target = document.uri.fsPath;
  const hits: Issue[] = [];
  for (const issue of allIssues(deps)) {
    if (issue.loc?.absFile !== target) {
      continue;
    }
    // Line overlap, deliberately, not a character-exact intersection: a lightbulb is asked
    // for wherever the caret is on the line, and a finding that spans lines must light up on
    // every line it spans. Columns decide where the EDIT goes, never whether it is offered.
    const tuple = toRangeTuple(issue.loc);
    if (range.start.line <= tuple.endLine && range.end.line >= tuple.startLine) {
      hits.push(issue);
    }
  }
  return hits;
}

/**
 * The provider. It contributes ONLY `QuickFix` actions: `source.fixAll` is the kind
 * `editor.codeActionsOnSave` runs unattended, and H5's whole risk budget is spent on
 * "never auto-applied".
 *
 * Every action it returns carries a `command` and NO `edit`. That is the point: a
 * `CodeAction.edit` is applied by VS Code's own bulk-edit service, which would make the
 * lightbulb the one surface that never reaches `applyIssueFix` — and therefore the one surface
 * with no `verifyAgainstBuffer`, no dirty-buffer refusal and no `isRefactoring` request. It is
 * also the surface a user actually clicks. So the action asks for the command instead, and the
 * three surfaces (lightbulb, `mlview.applyFix`, the viewer's `applyFix` message) are one path,
 * as §11.43 A1 requires.
 */
export class MlviewFixActionProvider implements vscode.CodeActionProvider {
  static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

  constructor(private readonly deps: FixDeps) {}

  provideCodeActions(
    document: vscode.TextDocument,
    range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    if (document.uri.scheme !== 'file') {
      // A notebook cell is a `vscode-notebook-cell:` document whose finding names the
      // generated shadow module. Editing that would repair a file the user never wrote.
      return [];
    }
    const actions: vscode.CodeAction[] = [];
    for (const issue of issuesAt(this.deps, document, range)) {
      const reading = readFix(issue);
      if (!reading.ok) {
        if (reading.reason !== 'no-fix') {
          this.deps.log.warn(
            `no code action for ${issue.code} (${issue.id}): ${reading.reason} — ${reading.detail}`
          );
        }
        continue;
      }
      // Built here ONLY to decide whether to offer a lightbulb at all: a fix that cannot be
      // contained in the workspace must not appear in the menu. The edit itself is thrown
      // away — see the note above on why it is never attached to the action.
      const built = buildFixEdit(reading.fix, this.deps.log);
      if (!built.ok) {
        this.deps.log.warn(
          `no code action for ${issue.code} (${issue.id}): ${built.reason} — ${built.detail}`
        );
        continue;
      }
      const action = new vscode.CodeAction(
        fixActionTitle(issue, reading.fix),
        vscode.CodeActionKind.QuickFix
      );
      // NOT `action.edit`. VS Code applies an attached `WorkspaceEdit` itself, which would
      // route the lightbulb around `applyIssueFix` and therefore around the staleness check.
      // With only a command, VS Code runs the command, and the lightbulb is the same path as
      // the palette command and the viewer's message — §11.43 A1.
      action.command = {
        title: fixActionTitle(issue, reading.fix),
        command: APPLY_FIX_COMMAND,
        arguments: [issue.id]
      };
      action.isPreferred = isMechanical(reading.fix);
      const diagnostic = context.diagnostics.find(
        (d) => d.source === DIAGNOSTIC_SOURCE && d.range.start.line === toRangeTuple(issue.loc).startLine
      );
      if (diagnostic) {
        action.diagnostics = [diagnostic];
      }
      actions.push(action);
    }
    return actions;
  }
}

/**
 * Apply one issue's fix. THE single entry point: the `mlview.applyFix` command, the webview's
 * `applyFix` message and any future surface all land here, so the containment check, the
 * bucket floor and the preview cannot differ by where the user clicked — the same rule
 * MLV-P10's `runSuppression` follows, and for the same reason.
 */
export async function applyIssueFix(
  issueId: string,
  deps: FixDeps
): Promise<{ applied: boolean; reason?: FixRefusal }> {
  const issue = issueById(deps, issueId);
  if (!issue) {
    deps.log.warn(`applyFix: no finding with id ${issueId} in the current analysis`);
    void vscode.window.showWarningMessage(
      'MLView: that finding is not in the current analysis. Run "MLView: Re-analyze" and try again.'
    );
    return { applied: false, reason: 'no-fix' };
  }
  const reading = readFix(issue);
  if (!reading.ok) {
    deps.log.warn(`applyFix ${issue.code}: ${reading.reason} — ${reading.detail}`);
    void vscode.window.showWarningMessage(
      reading.reason === 'low-confidence'
        ? `MLView: ${issue.code} is only "${issue.confidenceBucket}", so no edit is offered. ${issue.fixHint}`
        : `MLView: ${issue.code} carries no applicable fix. ${issue.fixHint}`
    );
    return { applied: false, reason: reading.reason };
  }
  const built = buildFixEdit(reading.fix, deps.log);
  if (!built.ok) {
    deps.log.warn(`applyFix ${issue.code}: ${built.reason} — ${built.detail}`);
    void vscode.window.showWarningMessage(
      `MLView: refusing to edit ${built.detail} — it is outside every open workspace folder.`
    );
    return { applied: false, reason: built.reason };
  }
  // 11.42 I.3: verify before applying. The preview is the user's check; this is the host's.
  const fresh = await verifyAgainstBuffer(reading.fix, deps.log);
  if (!fresh.ok) {
    deps.log.warn(`applyFix ${issue.code}: ${fresh.reason} — ${fresh.detail}`);
    void vscode.window.showWarningMessage(
      `MLView: ${fresh.detail} since this analysis, so the fix would land at stale ` +
        'coordinates. Save the file and run "MLView: Re-analyze", then try again.'
    );
    return { applied: false, reason: fresh.reason };
  }
  // `isRefactoring` is what asks VS Code for the preview; `needsConfirmation` on each entry
  // is what makes it mandatory. Together: the edit is never applied behind the user's back.
  const applied = await vscode.workspace.applyEdit(built.edit, { isRefactoring: true });
  if (applied) {
    deps.log.info(`applied fix for ${issue.code} (${issue.id}): ${reading.fix.title}`);
  } else {
    deps.log.info(`the fix for ${issue.code} (${issue.id}) was not applied`);
  }
  return { applied };
}

/**
 * 11.42 I.3's obligation, discharged: *"a host that applies an edit from a stale document
 * applies it at stale coordinates"*.
 *
 * The document carries no content hash, so the host cannot prove the source is unchanged.
 * What it CAN prove is the two ways it is certainly wrong, and it checks both before the
 * preview rather than after the write:
 *
 *   - the buffer has **unsaved changes**. The analyzer read the file on disk; a dirty buffer
 *     is a different document, and the line the fix names may not be the line any more.
 *   - the range does not **exist** in the buffer at all, which happens whenever the file
 *     shrank since the analysis.
 *
 * Neither is a rewrite and neither is a guess: both are refusals that name the file.
 */
async function verifyAgainstBuffer(
  fix: IssueFix,
  log: Logger
): Promise<{ ok: true } | { ok: false; reason: FixRefusal; detail: string }> {
  for (const one of fix.edits) {
    let document: vscode.TextDocument;
    try {
      document = await vscode.workspace.openTextDocument(vscode.Uri.file(one.absFile));
    } catch (err) {
      log.warn(`could not open ${one.absFile} to check the fix against it: ${String(err)}`);
      return { ok: false, reason: 'stale-document', detail: one.absFile };
    }
    if (document.isDirty) {
      return { ok: false, reason: 'stale-document', detail: `${one.absFile} has unsaved changes` };
    }
    const tuple = toRangeTuple(one);
    if (tuple.endLine >= document.lineCount) {
      return {
        ok: false,
        reason: 'stale-document',
        detail: `${one.absFile} is shorter than the analysis saw`
      };
    }
  }
  return { ok: true };
}

/** Register the fix provider and its command. Called unconditionally at activation. */
export function registerFixActions(deps: FixDeps): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand(APPLY_FIX_COMMAND, (issueId: string) =>
      applyIssueFix(String(issueId), deps)
    ),
    vscode.languages.registerCodeActionsProvider(
      { language: 'python' },
      new MlviewFixActionProvider(deps),
      { providedCodeActionKinds: MlviewFixActionProvider.providedCodeActionKinds }
    )
  ];
}
