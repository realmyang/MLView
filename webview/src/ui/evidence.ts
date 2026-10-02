/**
 * The basis mark a finding row and its Selection pane both draw.
 */

import { basisTag } from '../render/nodes.js';
import type { Issue } from '../types.js';

/**
 * Viewer M2 review (M2R-7, A11Y-4): the exceptions only, as the canvas marks them. An inferred or
 * unresolved finding carries the same dashed or dotted tag a card does ("inferred",
 * "? unresolved"); an observed finding (or one without a basis) carries nothing, so the marks that
 * are drawn stand out. It used to print "observed" on every row, in the same grey as "inferred".
 */
export function basisChip(issue: Issue): HTMLElement | null {
  const tag = basisTag(issue.basis, 'finding');
  if (!tag) return null;
  // Read out here: the rail has no card name that says it already.
  tag.removeAttribute('aria-hidden');
  tag.classList.add('mlv-basis-tag--rail');
  return tag;
}
