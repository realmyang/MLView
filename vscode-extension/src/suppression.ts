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
 * The one exception is `path` arithmetic in the containment predicates, which have
 * to agree with the platform's idea of what "inside" means.
 */

import * as path from 'node:path';

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

/** One TOML line split into the part that is data and the trailing `# ...` comment. */
export interface LineSplit {
  /** Everything before the first `#` that is outside a string, trailing spaces included. */
  code: string;
  /** The comment, from its `#` to end of line, or `''`. */
  comment: string;
}

/**
 * Split a line at the first `#` that is NOT inside a quoted string.
 *
 * §11.27 S4: "an existing `[rules]` section keeps its comments". That applies to the
 * line being edited too, so every transform below works on `code` and re-appends
 * `comment` verbatim — and the quoted-token scan never sees prose, so an apostrophe in
 * `# it is Bob's rule` cannot be lifted into the disable list as a rule code.
 */
export function splitComment(line: string): LineSplit {
  let quote: '"' | "'" | undefined;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]!;
    if (quote === '"' && ch === '\\') {
      i += 1; // an escaped character inside a basic string is never a delimiter
      continue;
    }
    if (quote !== undefined) {
      if (ch === quote) {
        quote = undefined;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '#') {
      return { code: line.slice(0, i), comment: line.slice(i) };
    }
  }
  return { code: line, comment: '' };
}

/** The quoted strings in one stretch of TOML *code*, upper-cased and trimmed. */
function quotedTokens(code: string): string[] {
  const re = /"([^"]*)"|'([^']*)'/g;
  const out: string[] = [];
  let found: RegExpExecArray | null = re.exec(code);
  while (found !== null) {
    const raw = (found[1] ?? found[2] ?? '').trim();
    if (raw.length > 0) {
      out.push(raw.toUpperCase());
    }
    found = re.exec(code);
  }
  return out;
}

/**
 * Add `code` to `[rules] disable` in a `.mlview.toml`, creating the key, the
 * section or the whole file as needed. Idempotent: a code already listed returns
 * the input unchanged with `changed: false`.
 *
 * Deliberately a line transform rather than a TOML round-trip. A round-trip
 * rewrites a file the user hand-wrote — reordering keys, dropping comments,
 * re-quoting strings — and this feature is not worth touching a single line it
 * did not have to touch. That holds for the edited line as well: a trailing
 * comment on the `disable` line survives, and a multi-line array stays multi-line.
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

  // The value may span several lines: `disable = [` / `  "MLV601",` / `]`. A `]` inside a
  // comment (`disable = [  # see [rules]`) does not close it.
  let closing = keyAt;
  while (closing < sectionEnd && !splitComment(lines[closing]!).code.includes(']')) {
    closing += 1;
  }
  if (closing >= sectionEnd) {
    // Unterminated array — refuse rather than corrupt a file we cannot read.
    return { text, changed: false };
  }

  const splits = lines.slice(keyAt, closing + 1).map(splitComment);
  const openAt = splits[0]!.code.indexOf('[');
  if (openAt < 0) {
    // A `]` with no `[` before it: unreadable, so nothing is written.
    return { text, changed: false };
  }
  // Region 0 starts at the `[` so the key name itself can never be read as an entry.
  const regionOf = (index: number): string =>
    index === 0 ? splits[0]!.code.slice(openAt) : splits[index]!.code;
  const listed: string[] = [];
  for (let i = 0; i < splits.length; i += 1) {
    listed.push(...quotedTokens(regionOf(i)));
  }
  if (listed.includes(upper)) {
    return { text, changed: false };
  }

  if (splits.length === 1) {
    // One line: rewrite the array text only, and re-append whatever followed the `]`.
    const { code, comment } = splits[0]!;
    const closeAt = code.lastIndexOf(']');
    const head = code.slice(0, openAt);
    const tail = code.slice(closeAt + 1);
    const rewritten = [...listed, upper].map((c) => `"${c}"`).join(', ');
    lines.splice(keyAt, 1, `${head}[${rewritten}]${tail}${comment}`);
    return { text: lines.join(eol), changed: true };
  }

  // Multi-line: keep it multi-line. Only the closing line, and at most the previous
  // entry (to gain a comma), are touched.
  const last = splits.length - 1;
  const closeCode = splits[last]!.code;
  const closeAt = closeCode.indexOf(']');
  const beforeBracket = closeCode.slice(0, closeAt);

  if (beforeBracket.trim().length > 0) {
    // `  "MLV301"]` — the last entry shares the closing line, so append in place.
    const kept = beforeBracket.replace(/\s+$/, '');
    const separator = kept.endsWith('[') || kept.endsWith(',') ? ' ' : ', ';
    lines.splice(
      closing,
      1,
      `${kept}${separator}"${upper}"${closeCode.slice(closeAt)}${splits[last]!.comment}`
    );
    return { text: lines.join(eol), changed: true };
  }

  // `]` on its own line: insert a new entry line above it, in the file's own style.
  let entryAt = -1;
  for (let i = last - 1; i >= 0; i -= 1) {
    if (quotedTokens(regionOf(i)).length > 0) {
      entryAt = i;
      break;
    }
  }
  const keyIndent = /^\s*/.exec(splits[0]!.code)?.[0] ?? '';
  let entryIndent = keyIndent + '  ';
  let trailingComma = true;
  if (entryAt >= 0) {
    const entryCode = splits[entryAt]!.code;
    const kept = entryCode.replace(/\s+$/, '');
    trailingComma = kept.endsWith(',');
    if (entryAt > 0) {
      entryIndent = /^\s*/.exec(entryCode)?.[0] ?? entryIndent;
    }
    if (!trailingComma) {
      // The previous last entry has to gain a comma; its own comment stays put.
      const spacing = entryCode.slice(kept.length);
      lines.splice(keyAt + entryAt, 1, `${kept},${spacing}${splits[entryAt]!.comment}`);
    }
  }
  lines.splice(closing, 0, `${entryIndent}"${upper}"${trailingComma ? ',' : ''}`);
  return { text: lines.join(eol), changed: true };
}

/**
 * True when `target` is inside `root`. The same containment rule the plugin's
 * `resolve_out` enforces: a suppression must never write outside the workspace,
 * however the request reached us (a code action, or a `suppressRule` message the
 * webview posted).
 *
 * Both paths are RESOLVED first, so `/repo/../etc/passwd` is compared as `/etc/passwd`
 * and cannot pass a prefix test it has no business passing. Case is folded on win32
 * only, where the filesystem folds it too.
 */
export function isInsideWorkspace(root: string, target: string): boolean {
  if (typeof root !== 'string' || typeof target !== 'string' || root.trim().length === 0) {
    return false;
  }
  const fold = (p: string): string => (process.platform === 'win32' ? p.toLowerCase() : p);
  let base: string;
  let candidate: string;
  try {
    base = fold(path.resolve(root));
    candidate = fold(path.resolve(target));
  } catch {
    return false;
  }
  if (candidate === base) {
    return true;
  }
  const rel = path.relative(base, candidate);
  if (rel.length === 0 || path.isAbsolute(rel)) {
    return false; // a different drive on win32, or nothing to compare
  }
  return rel !== '..' && !rel.startsWith('..' + path.sep) && !rel.startsWith('../');
}

/**
 * The first of `roots` that contains `target`, or `undefined` when none does — the
 * multi-root form of the same rule, for a path that arrived from the webview.
 */
export function insideAnyWorkspace(
  roots: readonly string[],
  target: string
): string | undefined {
  for (const root of roots) {
    if (isInsideWorkspace(root, target)) {
      return root;
    }
  }
  return undefined;
}
