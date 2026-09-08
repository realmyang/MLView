/**
 * The status-bar item's text and tooltip.
 *
 * Pure, and split out of extension.ts so the label logic can be asserted directly. The counts
 * handed in are always the ones that survive `publishedIssueFilter` (CONTRACTS.md §6), because
 * clicking the item opens `MLView: Show ML Issues`, which mirrors the Problems panel: a count
 * taken from `graph.stats.issues` instead would advertise findings neither surface can show.
 */

import type { IssueCounts } from './graph';

export function statusBarText(counts: IssueCounts, busy: boolean, failed: boolean): string {
  if (busy) {
    return '$(sync~spin) MLView';
  }
  if (failed) {
    return '$(graph) MLView $(error)';
  }
  const total = counts.high + counts.medium + counts.low;
  if (total === 0) {
    return '$(graph) MLView';
  }
  const parts: string[] = [];
  if (counts.high > 0) {
    parts.push(`${counts.high} high`);
  }
  if (counts.medium > 0) {
    parts.push(`${counts.medium} med`);
  }
  if (counts.low > 0) {
    parts.push(`${counts.low} low`);
  }
  return `$(graph) MLView: ${parts.join(' · ')}`;
}

export function statusBarTooltip(
  counts: IssueCounts,
  busy: boolean,
  failed: boolean,
  notebooksSkipped: number
): string {
  if (busy) {
    return 'MLView: analyzing…';
  }
  if (failed) {
    return 'MLView: analysis failed — click for the issue list, or run "MLView: Show Output".';
  }
  return (
    `MLView: ${counts.high} high, ${counts.medium} medium, ${counts.low} low` +
    (notebooksSkipped > 0 ? ` · ${notebooksSkipped} notebooks not analyzed` : '')
  );
}
