/**
 * The status-bar item's text and tooltip.
 *
 * Pure, and split out of extension.ts so the label logic can be asserted directly. The counts
 * handed in are always the ones that survive `publishedIssueFilter` (CONTRACTS.md §6), because
 * clicking the item opens `MLView: Show ML Issues`, which mirrors the Problems panel: a count
 * taken from `graph.stats.issues` instead would advertise findings neither surface can show.
 */

import type * as vscode from 'vscode';
import { coverageFor } from './coverage';
import { countIssues, type IssueCounts, type MLGraph } from './graph';
import { publishedIssueFilter, selectIssues } from './issues';
import type { MlviewSettings } from './settings';

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

/**
 * `coverage` is the analyzer's `single_file_analysis` / `untagged_dataflow` caveats, already
 * rendered by `coverage.ts`. They belong in the tooltip and not in the label because the label
 * is a count and a count cannot say "and I was blind here" — but a reader who hovers a green
 * "MLView" and is told nothing has been told the run was clean (ROADMAP COVERAGE).
 */
export function statusBarTooltip(
  counts: IssueCounts,
  busy: boolean,
  failed: boolean,
  notebooksSkipped: number,
  coverage: readonly string[] = [],
  /**
   * PACKAGING: which end of the precedence chain answered — the installed `mlview`
   * or the copy bundled in the VSIX (`pythonEnv.coreDescription()`). A user who
   * pip-installs a newer core and sees no change has to be able to find out which
   * analyzer produced the number they are looking at.
   */
  core?: string
): string {
  const tail = core ? `\n${core}` : '';
  if (busy) {
    return `MLView: analyzing…${tail}`;
  }
  if (failed) {
    return `MLView: analysis failed — click for the issue list, or run "MLView: Show Output".${tail}`;
  }
  const head =
    `MLView: ${counts.high} high, ${counts.medium} medium, ${counts.low} low` +
    (notebooksSkipped > 0 ? ` · ${notebooksSkipped} notebooks not analyzed` : '');
  if (coverage.length === 0) {
    return `${head}${tail}`;
  }
  return (
    [
      `${head} · coverage: incomplete`,
      'This count is a floor, not a clean bill of health:',
      ...coverage.map((line) => `• ${line}`)
    ].join('\n') + tail
  );
}

/**
 * Draw the item. Lives here rather than in the controller so the label, the tooltip and the
 * FILTER that decides the counts are one unit: the status bar is a click through to
 * `MLView: Show ML Issues`, so a raw `stats.issues` count (every unsuppressed finding at any
 * confidence) would advertise findings neither that list nor the Problems panel can show.
 */
export function renderStatusBar(
  item: vscode.StatusBarItem,
  state: {
    graph?: MLGraph;
    settings: MlviewSettings;
    busy: boolean;
    failed: boolean;
    /** `pythonEnv.coreDescription()`; absent until the first resolution finishes. */
    core?: string;
  }
): void {
  const counts: IssueCounts = state.graph
    ? countIssues(selectIssues(state.graph, publishedIssueFilter(state.settings)))
    : { low: 0, medium: 0, high: 0 };
  item.text = statusBarText(counts, state.busy, state.failed);
  item.tooltip = statusBarTooltip(
    counts,
    state.busy,
    state.failed,
    state.graph?.workspace.notebooksSkipped ?? 0,
    coverageFor(state.graph),
    state.core
  );
  item.show();
}
