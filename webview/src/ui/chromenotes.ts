/**
 * The chrome's diagnostic vocabulary: the words it uses for a coverage gap, and
 * the one-stat pill the toolbar counts nodes and edges with.
 *
 * Split out of `ui/chrome.ts` when the Sprint 4 viewer drop pushed that file
 * over the size bar. Pure functions over `Diagnostic[]` and strings — no state,
 * no callbacks, nothing that knows the toolbar exists.
 *
 * COVERAGE is why the two `coverage*` functions are worded the way they are:
 * MLView's worst failure mode is that it cannot tell *"I checked and it is
 * fine"* from *"I could not check"*, so every string here has to name what was
 * NOT looked at rather than summarise what was.
 */

import { add, el } from '../dom.js';
import { OUT_OF_ORDER_KINDS } from '../notebook.js';
import type { Diagnostic } from '../types.js';

/**
 * Diagnostic kinds the chrome surfaces somewhere OTHER than the generic note
 * chip: as a banner, as a purpose-built chip, or folded into the status bar.
 * Anything not listed here — including a kind invented by a newer analyzer —
 * falls through to the generic chip, which is what invariant 1.1/6 asks for.
 */
export const SPECIALLY_RENDERED = [
  'parse_error',
  'dynamic_scope',
  'truncated',
  'notebook_skipped',
  'framework_suppressed',
  'config_warning',
  'config_unresolved',
  'untagged_dataflow',
  'single_file_analysis',
  'notebook_analyzed',
  // NB. Drawn as a BANNER, not a chip.
].concat(OUT_OF_ORDER_KINDS);

/**
 * COVERAGE. The product's worst failure mode is that it cannot tell *"I checked
 * and it is fine"* from *"I could not check"*: MLV101 is silent whenever
 * features arrive as a function parameter, and analysing `train.py` alone yields
 * 3 findings where its directory yields 7 — a 57 % loss, with nothing said. Both
 * now arrive as diagnostics, and both get a banner that says what was NOT
 * looked at.
 */
export const COVERAGE_KINDS = ['untagged_dataflow', 'single_file_analysis'];


/** One `12 nodes` pill for the toolbar's stat row. */
export function stat(value: string, label: string): HTMLElement {
  const wrap = el('span', 'mlv-stat');
  add(wrap, el('span', 'mlv-stat__value', value));
  add(wrap, el('span', '', label));
  return wrap;
}

/**
 * NB. The chip for `notebook_analyzed` — the counterpart of the
 * `notebook_skipped` chip the chrome has always drawn. Its opposite sat in the
 * "specially rendered" list with nothing rendering it, so a run that DID read
 * the notebooks said so nowhere outside the "N notes" count.
 */
export function notebooksAnalyzedText(d: Diagnostic): string {
  const n = d.count || 0;
  return n + (n === 1 ? ' notebook analyzed' : ' notebooks analyzed');
}

/** The chip text for one coverage diagnostic — short, countable, honest. */
export function coverageChipText(d: Diagnostic): string {
  if (d.kind === 'single_file_analysis') {
    const codes = d.codes && d.codes.length ? ' — ' + d.codes.join(', ') + ' need more files' : '';
    return 'single-file analysis' + codes;
  }
  const n = d.count || 0;
  return n > 0 ? n + (n === 1 ? ' value not traced' : ' values not traced') : 'dataflow not traced';
}

/** The banner headline: what was not checked, in the reader's words. */
export function coverageHeadline(diags: Diagnostic[]): string {
  const single = diags.some((d) => d.kind === 'single_file_analysis');
  const untagged = diags.filter((d) => d.kind === 'untagged_dataflow');
  const parts: string[] = [];
  if (single) parts.push('only part of this project was analyzed, so cross-file rules could not run');
  if (untagged.length) {
    const n = untagged.reduce((sum, d) => sum + (d.count || 1), 0);
    parts.push(n + (n === 1 ? ' value' : ' values') + ' reaching a fit or split could not be traced');
  }
  return 'Coverage: ' + parts.join('; ') + '. A clean result here is not a clean bill of health.';
}

/** The `<pre>` body under a banner: up to eight diagnostics, file and line first. */
export function describe(diags: Diagnostic[]): string {
  return diags
    .slice(0, 8)
    .map((d) => (d.file ? d.file + (d.line ? ':' + d.line : '') + ' — ' : '') + d.message)
    .join('\n');
}
