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
import type { Diagnostic } from '../types.js';

/** One `12 nodes` pill for the toolbar's stat row. */
export function stat(value: string, label: string): HTMLElement {
  const wrap = el('span', 'mlv-stat');
  add(wrap, el('span', 'mlv-stat__value', value));
  add(wrap, el('span', '', label));
  return wrap;
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
