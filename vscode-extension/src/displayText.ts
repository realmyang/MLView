/**
 * Artifact- and workspace-derived text shown in host-owned places (the status banner, VS Code
 * notifications, the refinement prompt). Such text may come from anyone who can edit the
 * artifact, so it must not forge extra lines, reorder what the user reads, hide text, or grow
 * without bound.
 */
import type { ValidationIssue } from './workflowDocument';

/**
 * Code points that are invisible or reorder the text around them: every Unicode
 * Default_Ignorable_Code_Point (the soft hyphen, the combining grapheme joiner, the Arabic letter
 * mark and the other Bidi_Control characters, Hangul fillers, Khmer inherent vowels, Mongolian
 * variation selectors, zero-width and word-joiner characters, deprecated format controls,
 * variation selectors VS1-VS256, the byte-order mark, the halfwidth Hangul filler, shorthand and
 * musical format controls, the tag characters, which many models read as ASCII, and the reserved
 * default-ignorable blocks), plus line and paragraph separators, interlinear annotation controls
 * and Egyptian hieroglyph format controls (SECURITY1-2, SECURITY2-2).
 */
export const INVISIBLE_RANGES: readonly (readonly [number, number])[] = [
  [0x00ad, 0x00ad], [0x034f, 0x034f], [0x061c, 0x061c], [0x115f, 0x1160], [0x17b4, 0x17b5],
  [0x180b, 0x180f], [0x200b, 0x200f], [0x2028, 0x202e], [0x2060, 0x206f], [0x3164, 0x3164],
  [0xfe00, 0xfe0f], [0xfeff, 0xfeff], [0xffa0, 0xffa0], [0xfff0, 0xfffb], [0x13430, 0x1343f],
  [0x1bca0, 0x1bca3], [0x1d173, 0x1d17a], [0xe0000, 0xe0fff]
];
const hex4 = (unit: number): string => '\\u' + unit.toString(16).padStart(4, '0');
/** `\uXXXX` for a BMP code point; both surrogate halves for an astral one (valid inside JSON strings). */
export function unicodeEscape(codePoint: number): string {
  if (codePoint <= 0xffff)
    return hex4(codePoint);
  const offset = codePoint - 0x10000;
  return hex4(0xd800 + (offset >> 10)) + hex4(0xdc00 + (offset & 0x3ff));
}
/** A global, code-point-aware (`u`) regex matching one character from `ranges`. */
export function rangeRegex(ranges: readonly (readonly [number, number])[]): RegExp {
  const unit = (code: number): string => `\\u{${code.toString(16)}}`;
  return new RegExp('[' + ranges.map(([from, to]) => from === to ? unit(from) : unit(from) + '-' + unit(to)).join('') + ']', 'gu');
}
/** Display text escapes C0 and C1 controls (so no newline reaches a banner line) plus the invisible set. */
const DISPLAY_RANGES: readonly (readonly [number, number])[] = [[0x00, 0x1f], [0x7f, 0x9f], ...INVISIBLE_RANGES];
const escapedForDisplay = (codePoint: number): boolean => DISPLAY_RANGES.some(([from, to]) => codePoint >= from && codePoint <= to);

/**
 * One entry of a host banner or notification: controls and invisible characters become `\uXXXX`
 * escapes, and the result is cut to at most `max` UTF-16 units (never inside an escape or a
 * surrogate pair) followed by an ellipsis.
 */
export function displayText(value: string, max = 300): string {
  let out = '';
  for (const ch of value) {
    const codePoint = ch.codePointAt(0)!;
    const piece = escapedForDisplay(codePoint) ? unicodeEscape(codePoint) : ch;
    if (out.length + piece.length > max)
      return out + '…';
    out += piece;
  }
  return out;
}

/** A validation issue as one bounded, single-line `path: message` entry. */
export function displayIssue(issue: ValidationIssue): string {
  return displayText(`${issue.path}: ${issue.message}`);
}
