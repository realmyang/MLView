/**
 * The status-bar item's text and tooltip.
 *
 * Pure, and split out of extension.ts so the label logic can be asserted directly. The counts
 * handed in are always the ones that survive `publishedIssueFilter` (CONTRACTS.md §6), because
 * clicking the item opens `MLView: Show ML Issues`, which mirrors the Problems panel: a count
 * taken from `graph.stats.issues` instead would advertise findings neither surface can show.
 */

import * as vscode from 'vscode';
import { coverageFor } from './coverage';
import { folderTooltipLine } from './folders';
import { countIssues, type IssueCounts, type MLGraph } from './graph';
import { publishedIssueFilter, selectIssues } from './issues';
import { notebookCounts, notebookTooltipFragment, type NotebookCounts } from './notebooks';
import type { MlviewSettings } from './settings';

export function statusBarText(counts: IssueCounts, busy: boolean, failed: boolean): string {
  if (busy) {
    return '$(sync~spin) MLView Legacy';
  }
  if (failed) {
    return '$(graph) MLView Legacy $(error)';
  }
  const total = counts.high + counts.medium + counts.low;
  if (total === 0) {
    return '$(graph) MLView Legacy';
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
  return `$(graph) MLView Legacy: ${parts.join(' · ')}`;
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
  /**
   * NB: what the run did with the notebooks it found. Two numbers rather than one, because
   * "2 notebooks not analyzed" and "2 notebooks analyzed" are opposite bills of health and a
   * run can legitimately produce both at once.
   */
  notebooks: NotebookCounts,
  coverage: readonly string[] = [],
  /**
   * PACKAGING: which end of the precedence chain answered — the installed `mlview`
   * or the copy bundled in the VSIX (`pythonEnv.coreDescription()`). A user who
   * pip-installs a newer core and sees no change has to be able to find out which
   * analyzer produced the number they are looking at.
   */
  core?: string,
  /**
   * H10: which of the open folders these counts are about, and how many are not. Absent (and
   * silent) in a single-folder window, which is nearly every window — the status bar has
   * always been about one project there, so naming it would be noise. In a multi-root window
   * a green "MLView" that describes only one of three folders is exactly the "I could not
   * check" / "I checked and it is fine" confusion the roadmap's standing criterion is about.
   */
  folders?: { active?: string; names: readonly string[] }
): string {
  const folderLine = folders ? folderTooltipLine(folders.names, folders.active) : undefined;
  const tail = (core ? `\n${core}` : '') + (folderLine ? `\n${folderLine}` : '');
  if (busy) {
    return `MLView Legacy static analysis: analyzing…${tail}`;
  }
  if (failed) {
    return `MLView Legacy static analysis: failed — click for the issue list, or run "MLView: Show Output".${tail}`;
  }
  const head =
    `MLView Legacy static analysis: ${counts.high} high, ${counts.medium} medium, ${counts.low} low` +
    notebookTooltipFragment(notebooks);
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
    /** H10: the open folders and which one these counts describe. */
    folders?: { active?: string; names: readonly string[] };
  }
): void {
  const counts: IssueCounts = state.graph
    ? countIssues(selectIssues(state.graph, publishedIssueFilter(state.settings)))
    : { low: 0, medium: 0, high: 0 };
  item.text = statusBarText(counts, state.busy, state.failed);
  const text = statusBarTooltip(
    counts,
    state.busy,
    state.failed,
    notebookCounts(state.graph),
    coverageFor(state.graph),
    state.core,
    state.folders
  );
  item.tooltip = decorateTooltip(text, state.folders);
  item.show();
}

/**
 * H10 — the picker. In a multi-root window the tooltip becomes a trusted `MarkdownString`
 * carrying one command link, which is the only affordance VS Code gives a status-bar item for
 * a SECOND action (`item.command` is already `mlview.showIssues`, and the count is what people
 * click it for). A single-folder window keeps the plain string it has always had, so the
 * markdown escaping cannot change what anyone reads today.
 */
export function decorateTooltip(
  text: string,
  folders?: { active?: string; names: readonly string[] }
): string | vscode.MarkdownString {
  if (!folders || folders.names.length < 2) {
    return text;
  }
  const md = new vscode.MarkdownString();
  md.isTrusted = true;
  md.appendText(text);
  md.appendMarkdown('\n\n[Analyze a different folder](command:mlview.activeFolder)');
  return md;
}
