/**
 * H5 — the structured fix, drawn.
 *
 * `Issue.fix` is the one field in the document that describes an edit to
 * somebody's training loop, so every surface here is built around the four
 * guardrails the lead attached to lifting REQUIREMENTS §5 non-goal 5:
 *
 *   1. **Rules opt in.** `fix` is absent on every rule that did not, so the
 *      marker is drawn from the field's PRESENCE and never inferred from
 *      `fixHint`, which all 36 rules carry as prose.
 *   2. **Edits come from the AST.** Not this file's business — but it is why the
 *      snippet is shown VERBATIM, character for character, rather than
 *      re-indented to look tidy: what you read is what would be written.
 *   3. **Never auto-applied.** The viewer posts `applyFix` and stops. The host
 *      opens a preview; the standalone report, which has no host to ask, copies
 *      the snippet and says so in the toast.
 *   4. **No fix below `likely`.** Analyzer-side, and the confidence chip is
 *      drawn beside the marker on every row so a reader can see the bucket the
 *      fix was allowed at.
 *
 * `safety` decides the wording and nothing else: `mechanical` is one unambiguous
 * slot, anything else — including a word a newer analyzer invents — reads as
 * "needs review" and gets the cautious verb. That asymmetry is deliberate:
 * mis-reading a judgement call as mechanical is the expensive direction.
 */

import { add, button, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { isMechanicalFix } from '../types.js';
import type { FixEdit, Issue, IssueFix, UiToHost } from '../types.js';

export interface FixCallbacks {
  /**
   * "Apply" in a host that can edit; "Copy" in one that cannot. The viewer never
   * decides what happens — it names the issue and lets the host answer.
   */
  onApplyFix(issueId: string): void;
}

/** Everything acting on a fix is allowed to reach. Keeps the decision here. */
export interface FixPort {
  canApply: boolean;
  post(msg: UiToHost): void;
  toast(text: string): void;
  announce(text: string): void;
}

/**
 * The one place the "request or clipboard" decision is made.
 *
 * In a host that can edit, the viewer posts `applyFix` and STOPS: the host
 * resolves the id against its own copy of the document and previews the edits.
 * In one that cannot — the standalone report — it goes through the same `copy`
 * message MLV-P10's ignore comment uses. The announcement says which of the two
 * actually happened, because "Applied" over a clipboard write would be a claim
 * about somebody's source file that is not true.
 */
export function runFixAction(issue: Issue, port: FixPort): void {
  const fix = issue.fix;
  if (!fix || !hasFix(issue)) return;
  if (port.canApply) {
    port.post({ v: 1, type: 'applyFix', issueId: issue.id });
    port.toast('Sent to your editor for review: ' + fix.title);
    port.announce('Asked the editor to preview the fix for ' + issue.code + '. Nothing is written until you accept it.');
    return;
  }
  port.post({ v: 1, type: 'copy', text: fixSnippet(fix) });
  port.toast('Copied the fix for ' + issue.code);
  port.announce('Copied the fix for ' + issue.code + ' to the clipboard. This host cannot edit files.');
}

/** True when this finding carries a fix with at least one real edit. */
export function hasFix(issue: Issue): boolean {
  const fix = issue.fix;
  return !!(fix && fix.title && Array.isArray(fix.edits) && fix.edits.length > 0);
}

/** `mechanical` / anything else, as the word the reader sees. */
export function safetyWord(fix: IssueFix): string {
  return isMechanicalFix(fix) ? 'mechanical' : 'needs review';
}

/** What the safety word MEANS, spelled out wherever it is drawn. */
export function safetyTitle(fix: IssueFix): string {
  return isMechanicalFix(fix)
    ? 'Mechanical: one unambiguous insertion point, computed from the syntax tree. It is still previewed before anything is written.'
    : 'Needs review: this edit changes behaviour that may be deliberate. Read it before you apply it.';
}

/**
 * The compact rail-row marker: *"Fix available"*.
 *
 * A chip and not a button — the row is a `role="option"` and may not contain a
 * focusable descendant (the rule `ui/issuelist.ts` already follows for "Open").
 * The action lives in the expanded detail and in the Inspector, both of which
 * have the room to show the edit before offering to make it.
 */
export function fixMarker(issue: Issue): HTMLElement | null {
  const fix = issue.fix;
  if (!fix || !hasFix(issue)) return null;
  const chip = el('span', 'mlv-chip mlv-chip--fix mlv-chip--fix-' + (isMechanicalFix(fix) ? 'mechanical' : 'review'));
  chip.setAttribute('data-fix', safetyWord(fix));
  chip.appendChild(uiIcon('wrench', 11));
  add(chip, el('span', '', 'Fix available'));
  chip.title = fix.title + ' — ' + safetyTitle(fix);
  chip.setAttribute('aria-label', 'Fix available, ' + safetyWord(fix) + ': ' + fix.title);
  return chip;
}

/** `train.py:29` and what the edit does there, in one line per edit. */
function editLine(edit: FixEdit): string {
  const where = edit.file + ':' + edit.line;
  const inserts = edit.line === edit.endLine && edit.col === edit.endCol;
  if (!edit.newText) return where + ' — delete';
  return where + (inserts ? ' — insert' : ' — replace');
}

/**
 * The edit itself, verbatim, as a `<pre>`.
 *
 * One block per edit, each labelled with its file and line, because a fix that
 * touches two places must not look like a fix that touches one. `textContent`
 * only — the snippet is somebody's source code and never markup.
 */
export function fixSnippet(fix: IssueFix): string {
  const parts: string[] = [];
  for (const edit of fix.edits || []) {
    parts.push(editLine(edit) + '\n' + (edit.newText || ''));
  }
  return parts.join('\n\n');
}

export interface FixSectionOptions {
  /** True in a host that can actually make the edit (VS Code). */
  canApply: boolean;
}

/**
 * The full disclosure: title, safety, every edit as a snippet, and one action.
 *
 * Drawn in the Inspector and in the expanded rail row — the two places a reader
 * has already decided the finding is real. It states what the button will do
 * BEFORE the button, in both hosts, because "Apply" and "Copy" are very
 * different promises and the reader should not have to click to find out which
 * one they were offered.
 */
export function appendFixSection(host: HTMLElement, issue: Issue, cb: FixCallbacks, opts: FixSectionOptions): void {
  const fix = issue.fix;
  if (!fix || !hasFix(issue)) return;
  const box = add(host, el('div', 'mlv-fix'));
  box.setAttribute('data-fix-issue', issue.id);
  box.setAttribute('data-fix-safety', isMechanicalFix(fix) ? 'mechanical' : 'needs-review');

  const head = add(box, el('div', 'mlv-fix__head'));
  head.appendChild(uiIcon('wrench', 13));
  add(head, el('span', 'mlv-fix__title', fix.title));
  const safety = add(head, el('span', 'mlv-chip mlv-chip--fix-safety', safetyWord(fix)));
  safety.title = safetyTitle(fix);
  safety.setAttribute('aria-label', safetyTitle(fix));

  for (const edit of fix.edits || []) {
    const label = add(box, el('div', 'mlv-fix__where', editLine(edit)));
    label.setAttribute('data-fix-edit', edit.file + ':' + edit.line);
    const pre = add(box, el('pre', 'mlv-fix__snippet', edit.newText || ''));
    pre.setAttribute('data-fix-newtext', '1');
  }

  const promise = opts.canApply
    ? 'Your editor opens a preview of this edit; nothing is written until you accept it.'
    : 'This report cannot edit files. The snippet is copied to the clipboard.';
  add(box, el('p', 'mlv-fix__note', promise));

  const label = opts.canApply ? (isMechanicalFix(fix) ? 'Apply fix' : 'Review fix…') : 'Copy fix';
  const action = button('mlv-btn mlv-btn--primary mlv-fix__apply', label, fix.title + ' — ' + promise);
  action.setAttribute('data-apply-fix', issue.id);
  on(action, 'click', (ev: Event) => {
    ev.stopPropagation();
    cb.onApplyFix(issue.id);
  });
  box.appendChild(action);
}
