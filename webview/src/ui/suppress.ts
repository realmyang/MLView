/**
 * Suppression as a one-click action (MLV-P10).
 *
 * Suppression works on the CLI — `# mlview: ignore[MLV101]` and
 * `[rules] MLV101 = "off"` both behave as documented — and was unreachable from
 * every UI: rail rows exposed "Open file:line" and nothing else, and the comment
 * syntax lived only in rule docs the report cannot reach. So the workflow for
 * *"this one is a false positive"* was: find a doc in the repo, memorise the
 * syntax, switch to the editor, type it.
 *
 * A suppression comment is NOT a logic edit, so this sits inside
 * `REQUIREMENTS.md` §5 non-goal 5, which bars fixes that edit user ML logic.
 * Two actions, on every rail row, on every group header and in the Inspector:
 *
 *   - **Copy ignore comment** posts `copy`, which the standalone bridge answers
 *     with the clipboard plus the existing copy toast (CONTRACTS 11.17.1) and a
 *     VS Code host answers with its own clipboard. Nothing is written anywhere.
 *   - **Disable this rule** posts `suppressRule`, a REQUEST: the viewer never
 *     edits configuration. The standalone bridge, which cannot write a file at
 *     all, answers with a copy toast carrying the `.mlview.toml` snippet.
 *
 * The two strings are built here, once, so the rail, the Inspector, the group
 * headers and the bridge can never disagree about the syntax the user is told
 * to type.
 */

import { add, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';

/** The inline comment the analyzer's suppression reader accepts. */
export function ignoreComment(code: string): string {
  return '# mlview: ignore[' + code + ']';
}

/** The `.mlview.toml` stanza that turns one rule off for the workspace. */
export function disableSnippet(code: string): string {
  return '[rules]\n' + code + ' = "off"';
}

/** What the standalone host says when it answers a `suppressRule` request. */
export function disableToast(code: string): string {
  return 'Copied the .mlview.toml snippet that disables ' + code;
}

export interface SuppressCallbacks {
  /** Copy `ignoreComment(code)` through the host's clipboard path. */
  onCopyIgnore(code: string): void;
  /** Post `suppressRule` for this code. */
  onDisableRule(code: string): void;
}

export interface SuppressActionOptions {
  /** Icon-only buttons for a dense list; text buttons for the Inspector. */
  compact?: boolean;
  /** "this finding" vs "all 10 MLV101 findings" — named in the titles. */
  subject?: string;
}

/**
 * Append the two actions to `host`.
 *
 * Both are real buttons and both stop propagation: on a rail row they sit beside
 * the `role="option"`, never inside it (an option may not contain a focusable
 * descendant — the same rule `ui/issuelist.ts` already follows for "Open").
 */
export function appendSuppressActions(
  host: HTMLElement,
  code: string,
  cb: SuppressCallbacks,
  opts?: SuppressActionOptions,
): void {
  const compact = !!(opts && opts.compact);
  const subject = (opts && opts.subject) || 'this finding';
  const copyTitle = 'Copy ignore comment for ' + subject + ' — ' + ignoreComment(code);
  const offTitle = 'Disable ' + code + ' for this workspace — adds ' + code + ' = "off" under [rules]';

  const copy = compact
    ? iconButton('mlv-btn mlv-btn--icon mlv-issue__ignore', copyTitle)
    : textButton('mlv-btn mlv-issue__ignore', 'Copy ignore comment', copyTitle);
  if (compact) copy.appendChild(uiIcon('copy', 12));
  copy.setAttribute('data-copy-ignore', code);
  on(copy, 'click', (ev: Event) => {
    ev.stopPropagation();
    cb.onCopyIgnore(code);
  });
  host.appendChild(copy);

  const off = compact
    ? iconButton('mlv-btn mlv-btn--icon mlv-issue__disable', offTitle)
    : textButton('mlv-btn mlv-issue__disable', 'Disable this rule', offTitle);
  if (compact) off.appendChild(uiIcon('mute', 12));
  off.setAttribute('data-disable-rule', code);
  on(off, 'click', (ev: Event) => {
    ev.stopPropagation();
    cb.onDisableRule(code);
  });
  host.appendChild(off);
}

function textButton(cls: string, label: string, title: string): HTMLButtonElement {
  const b = el('button', cls, label) as HTMLButtonElement;
  b.type = 'button';
  b.title = title;
  b.setAttribute('aria-label', title);
  return b;
}

/**
 * The collapsed "N suppressed" section header (MLV-P10).
 *
 * A suppression that is invisible is not auditable, and CI-ADOPT's baselined
 * findings arrive through the same door — "marked, not deleted" — so the count
 * says how many of each when both are present.
 */
export function suppressedSummary(suppressed: number, baselined: number): string {
  const total = suppressed + baselined;
  const head = total + ' suppressed';
  if (baselined > 0 && suppressed > 0) return head + ' · ' + baselined + ' baselined';
  if (baselined > 0) return total + ' baselined';
  return head;
}

/** A small labelled chip, used for `suppressed`, `baselined` and `new`. */
export function stateChip(parent: HTMLElement, cls: string, text: string, title?: string): HTMLElement {
  const chip = add(parent, el('span', 'mlv-chip ' + cls, text));
  if (title) chip.title = title;
  return chip;
}
