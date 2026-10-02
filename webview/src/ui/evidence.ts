/**
 * The basis chip a finding row and its Selection pane both draw.
 */

import { el } from '../dom.js';
import type { Issue } from '../types.js';

/** The authored basis (`observed`, `inferred`, `unresolved`), on EVERY row. */
export function basisChip(issue: Issue): HTMLElement {
  const basis = issue.basis || 'unknown';
  const chip = el('span', 'mlv-chip mlv-chip--basis mlv-chip--basis-' + basis, basis);
  chip.setAttribute('data-basis', basis);
  chip.title = 'Basis: ' + basis;
  chip.setAttribute('aria-label', chip.title);
  return chip;
}
