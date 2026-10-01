/**
 * The basis chip a finding row and its Inspector both draw.
 */

import { el } from '../dom.js';
import type { Issue } from '../types.js';

const BUCKETS = ['certain', 'likely', 'possible', 'speculative'];

/** `certain` / `likely` / `possible` / `speculative`, or a passthrough. */
export function normalizeBucket(bucket: string): string {
  return BUCKETS.indexOf(bucket) >= 0 ? bucket : 'unknown';
}

/**
 * The bucket chip, on EVERY row.
 *
 * It used to appear only when the analyzer was unsure, which drained the signal
 * from the two buckets a reviewer acts on: a row with no chip could equally mean
 * "certain" or "the renderer forgot".
 */
export function confidenceChip(issue: Issue): HTMLElement {
  if (issue.basis) {
    const chip = el('span', 'mlv-chip mlv-chip--basis mlv-chip--basis-' + issue.basis, issue.basis);
    chip.setAttribute('data-basis', issue.basis);
    chip.title = 'Basis: ' + issue.basis;
    chip.setAttribute('aria-label', chip.title);
    return chip;
  }
  const bucket = normalizeBucket(issue.confidenceBucket);
  const chip = el('span', 'mlv-chip mlv-chip--conf mlv-chip--conf-' + bucket, issue.confidenceBucket || bucket);
  chip.setAttribute('data-confidence', bucket);
  const pct = typeof issue.confidence === 'number' && isFinite(issue.confidence)
    ? ' (' + Math.round(issue.confidence * 100) + '%)'
    : '';
  chip.title = 'Confidence: ' + (issue.confidenceBucket || bucket) + pct;
  chip.setAttribute('aria-label', chip.title);
  return chip;
}
