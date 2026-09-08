/**
 * MLV-P10 — the two suppression gestures, as pure text transforms.
 *
 * Suppression already works perfectly on the CLI and is unreachable from any UI:
 * the workflow for "this one is a false positive" is find a doc in the repo,
 * memorise the syntax, switch to the editor, type it. The syntax
 * (`analyzer/src/mlview/rules/suppress.py`) is:
 *
 *     # mlview: ignore[MLV201]        on the issue's line, or the line above
 *     [rules]
 *     disable = ["MLV601"]            in .mlview.toml at the workspace root
 *
 * A suppression comment is not a logic edit, which is what keeps this inside
 * `REQUIREMENTS.md` §5 non-goal 5 (no fix that edits user ML logic). Everything
 * here is a string -> string function so `test/suppression.test.js` can assert the
 * exact bytes that reach someone's file without an editor, a workspace or a disk.
 */

/** `MLV201`, and nothing that merely looks like it. */
export const RULE_CODE_RE = /^MLV[0-9]{3}$/;

export function isRuleCode(value: unknown): value is string {
  return typeof value === 'string' && RULE_CODE_RE.test(value);
}

/** The comment the CLI honours, exactly as `docs/rules/<CODE>.md` spells it. */
export function ignoreComment(code: string): string {
  return `# mlview: ignore[${code}]`;
}

//: `# mlview : ignore [ MLV201 , MLV301 ]` is legal; this matches what the analyzer matches.
const EXISTING_IGNORE =
  /#\s*mlview\s*:\s*ignore(?<file>-file)?(?:\s*\[(?<codes>[^\]]*)\])?/i;

export interface IgnoreEdit {
  /** The whole replacement line, without its newline. */
  text: string;
  /** False when the line already suppresses this code — the caller must not edit. */
  changed: boolean;
  /** Why nothing changed, for the message the user sees. */
  reason?: 'already-listed' | 'already-blanket';
}

/**
 * Add `code` to the ignore comment on one source line, creating the comment when
 * there is none and MERGING into the list when there is.
 *
 * Merging matters: two findings on one line are common (`MLV101` and `MLV301` on the
 * same `fit_transform`), and a second `# mlview: ignore[...]` appended after the first
 * is dead text — the analyzer reads the first match on the line.
 */
export function withIgnoreComment(line: string, code: string): IgnoreEdit {
  const found = EXISTING_IGNORE.exec(line);
  if (!found) {
    const body = line.replace(/\s+$/, '');
    const spacer = body.length === 0 ? '' : '  ';
    return { text: `${body}${spacer}${ignoreComment(code)}`, changed: true };
  }
  if (found.groups?.['codes'] === undefined) {
    // A bare `# mlview: ignore` (or `ignore-file`) already covers every code.
    return { text: line, changed: false, reason: 'already-blanket' };
  }
  const listed = found.groups['codes']
    .split(',')
    .map((part) => part.trim().toUpperCase())
    .filter((part) => part.length > 0);
  if (listed.includes(code.toUpperCase())) {
    return { text: line, changed: false, reason: 'already-listed' };
  }
  const merged = [...listed, code.toUpperCase()].join(', ');
  const replacement = found[0].replace(/\[[^\]]*\]/, `[${merged}]`);
  return {
    text: line.slice(0, found.index) + replacement + line.slice(found.index + found[0].length),
    changed: true
  };
}

export interface ConfigEdit {
  text: string;
  changed: boolean;
}

const RULES_HEADER = /^\s*\[rules\]\s*$/;
const SECTION_HEADER = /^\s*\[[^\]]+\]\s*$/;
const DISABLE_KEY = /^\s*disable\s*=/;

/**
 * Add `code` to `[rules] disable` in a `.mlview.toml`, creating the key, the
 * section or the whole file as needed. Idempotent: a code already listed returns
 * the input unchanged with `changed: false`.
 *
 * Deliberately a line transform rather than a TOML round-trip. A round-trip
 * rewrites a file the user hand-wrote — reordering keys, dropping comments,
 * re-quoting strings — and this feature is not worth touching a single line it
 * did not have to touch.
 */
export function addDisabledRule(text: string, code: string): ConfigEdit {
  const upper = code.toUpperCase();
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  const lines = text.length === 0 ? [] : text.split(/\r?\n/);

  let sectionStart = -1;
  for (let i = 0; i < lines.length; i += 1) {
    if (RULES_HEADER.test(lines[i]!)) {
      sectionStart = i;
      break;
    }
  }

  if (sectionStart < 0) {
    const body = text.replace(/\s+$/, '');
    const head = body.length === 0 ? '' : body + eol + eol;
    return {
      text: `${head}[rules]${eol}disable = ["${upper}"]${eol}`,
      changed: true
    };
  }

  let sectionEnd = lines.length;
  for (let i = sectionStart + 1; i < lines.length; i += 1) {
    if (SECTION_HEADER.test(lines[i]!)) {
      sectionEnd = i;
      break;
    }
  }

  let keyAt = -1;
  for (let i = sectionStart + 1; i < sectionEnd; i += 1) {
    if (DISABLE_KEY.test(lines[i]!)) {
      keyAt = i;
      break;
    }
  }

  if (keyAt < 0) {
    lines.splice(sectionStart + 1, 0, `disable = ["${upper}"]`);
    return { text: lines.join(eol), changed: true };
  }

  // The value may span several lines: `disable = [` / `  "MLV601",` / `]`.
  let closing = keyAt;
  while (closing < sectionEnd && !lines[closing]!.includes(']')) {
    closing += 1;
  }
  if (closing >= sectionEnd) {
    // Unterminated array — refuse rather than corrupt a file we cannot read.
    return { text, changed: false };
  }
  const value = lines.slice(keyAt, closing + 1).join('\n');
  const listed = (value.match(/["']([^"']+)["']/g) ?? []).map((token) =>
    token.slice(1, -1).trim().toUpperCase()
  );
  if (listed.includes(upper)) {
    return { text, changed: false };
  }
  const rewritten = [...listed, upper].map((c) => `"${c}"`).join(', ');
  const indent = /^\s*/.exec(lines[keyAt]!)?.[0] ?? '';
  const span = closing + 1 - keyAt;
  lines.splice(keyAt, span, `${indent}disable = [${rewritten}]`);
  return { text: lines.join(eol), changed: true };
}

/**
 * True when `target` is inside `root`. The same containment rule the plugin's
 * `resolve_out` enforces: a suppression must never write outside the workspace,
 * however the request reached us (a code action, or a `suppressRule` message the
 * webview posted).
 */
export function isInsideWorkspace(root: string, target: string): boolean {
  const norm = (p: string): string => {
    const forward = p.replace(/\\/g, '/').replace(/\/+$/, '');
    return process.platform === 'win32' ? forward.toLowerCase() : forward;
  };
  const base = norm(root);
  const candidate = norm(target);
  if (base.length === 0) {
    return false;
  }
  return candidate === base || candidate.startsWith(base + '/');
}
