/**
 * The three surfaces outside the diagram — the chrome, the diff band and the
 * side rail — repainted from the App's state.
 *
 * All three are pure functions of (document, scope, filters, selection): none
 * of them decides anything, and none of them may disagree with another about
 * the same number. That is why the toolbar's counts are computed here, next to
 * the rail's, rather than inside the chrome.
 */

import { emptyCounts, normalizeSeverity } from '../markers.js';
import { isSetAside } from '../types.js';
import { CHANGED_SPEC } from '../diff/changed.js';
import { drawnNamed, drawnRemoved } from '../diff/adopt.js';
import { railScopeCounts } from '../scope/session.js';
import type { App } from '../app.js';
import type { IssueCounts, Severity } from '../types.js';

/**
 * Counts for the toolbar chips: severity filters do not hide their own count.
 *
 * VW-04. "Visible" here means exactly what `Filters.keep` means everywhere
 * else — `isSetAside`, i.e. suppressed OR BASELINED. It used to test
 * `issue.suppressed` alone, so the moment a repo adopted `--baseline` the
 * most prominent number on the page (5 / 6 / 3) disagreed with the rail
 * ('high · 4', 'medium · 4'), with the MLV-P1 answer card ('8 finding(s)')
 * and with `mlview issues` ('8 issue(s) ... 6 baselined'), and the chip
 * labelled 5 hid four rows when clicked. The netting is now also SAID:
 * `chrome.update` draws the set-aside button as '1 suppressed · 6 baselined'.
 */
export function visibleCounts(app: App): IssueCounts {
  const counts = emptyCounts();
  if (!app.graph) return counts;
  for (const issue of app.graph.issues) {
    if (!app.filters.value.showSuppressed && isSetAside(issue)) continue;
    counts[normalizeSeverity(issue.severity) as Severity]++;
  }
  return counts;
}

export function renderChrome(app: App): void {
  const summary = app.scopes.summary();
  const view = app.graph ? app.graph.view || null : null;
  // VIEW-08. The breadcrumb is the SCOPE's chip. A diff projection with no
  // scope under it puts a `view` on the document without the user ever having
  // picked a selector, and drawing "Scoped to Changed in this diff · Copy
  // scope" over it would offer a selector that does not parse and an [x] that
  // clears nothing. The diff band owns that state instead.
  const diffOnlyView = !!view && view.scope === CHANGED_SPEC;
  app.scopeBar.update(
    diffOnlyView ? null : view,
    app.scopes.full,
    app.scopes.spec,
    app.scopes.depth,
    !!(app.graph && app.graph.stats.truncated),
  );
  renderDiffBar(app);
  app.chrome.update({
    graph: app.graph,
    scopeLabel: summary.label,
    scopeActive: summary.spec !== null,
    flowOn: app.flowOn,
    legendOpen: app.legendOpen,
    laneIds: app.laneIds(),
    outOfScopeStages: app.index ? app.index.outOfScopeStages : [],
    hasSelection: !!app.selection,
    filters: app.filters.value,
    capabilities: app.caps,
    stale: app.stale,
    error: app.error,
    dismissed: app.dismissed,
    visibleCounts: visibleCounts(app),
    dynamicNodes: app.graph ? app.graph.nodes.filter((n) => n.dynamic).length : 0,
    minimapCollapsed: app.view.minimapCollapsed,
  });
  // MLV-P1: hidden outright when the document carries no `answers` block.
  app.answers.update(app.graph ? app.graph.answers : undefined, app.answersOpen);
  // VIEW-07: "Current scope" is offered only while there IS a projection.
  app.exportMenu.setScopeAvailable(!!view);
}

/** VIEW-08: the comparison's own band, under the chip row. */
export function renderDiffBar(app: App): void {
  const diff = app.scopes.diff;
  app.diffBar.update({
    diff,
    changedOnly: app.scopes.changedOnly,
    ghostsDrawn: diff && app.graph ? drawnRemoved(app.graph, diff) : 0,
    namedDrawn: diff && app.graph ? drawnNamed(app.graph) : 0,
    shown: app.graph ? app.graph.nodes.length : 0,
    of: app.scopes.full ? app.scopes.full.nodes.length : 0,
    changedEmpty: app.scopes.changedOnly && !app.scopes.changedActive,
    baseLabel: app.diffBaseLabel,
  });
}

export function renderRail(app: App): void {
  const sel = app.selection;
  // An issue selection resolves to its primary node, so the Inspector is never
  // empty just because the user clicked the issue row instead of the card
  // (MLV-R1-006).
  const nodeId = app.selectedNodeId();
  const selectedNode = nodeId && app.index ? app.index.nodeById.get(nodeId) || null : null;
  app.rail.update({
    index: app.index,
    canAskAssistant: app.caps.canAskAssistant,
    tab: app.railTab,
    issues: app.graph ? app.graph.issues : [],
    selectedNode,
    selectedIssueId: sel && sel.kind === 'issue' ? sel.id : null,
    collapsed: app.view.collapsed,
    keep: app.filters.keep,
    keepBase: app.filters.keepBase,
    scope: railScopeCounts(app.graph),
    groupBy: app.railGroupBy,
    diff: app.scopes.diff,
    canApplyFix: app.canApplyFix(),
  });
}
