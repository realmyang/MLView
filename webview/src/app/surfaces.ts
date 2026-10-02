/**
 * The two surfaces outside the diagram — the chrome and the side rail —
 * repainted from the App's state.
 *
 * Both are pure functions of (document, scope, filters, selection): none
 * of them decides anything, and none of them may disagree with another about
 * the same number. That is why the toolbar's counts are computed here, next to
 * the rail's, rather than inside the chrome.
 */

import { emptyCounts, normalizeSeverity } from '../markers.js';
import { railScopeCounts } from '../scope/session.js';
import { freshnessSummary } from '../freshness.js';
import type { App } from '../app.js';
import type { IssueCounts, Severity } from '../types.js';

/** Counts for the toolbar chips: every finding in view, so a severity filter never hides its own count. */
export function visibleCounts(app: App): IssueCounts {
  const counts = emptyCounts();
  if (!app.graph) return counts;
  for (const issue of app.graph.issues) counts[normalizeSeverity(issue.severity) as Severity]++;
  return counts;
}

export function renderChrome(app: App): void {
  const summary = app.scopes.summary();
  const view = app.graph ? app.graph.view || null : null;
  app.scopeBar.update(view, app.scopes.full, app.scopes.spec, app.scopes.depth);
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
    visibleCounts: visibleCounts(app),
    minimapCollapsed: app.view.minimapCollapsed,
    freshness: freshnessSummary(app.workflowDocument, app.freshness),
    checking: app.freshness.checking,
  });
  // VIEW-07: "Current scope" is offered only while there IS a projection.
  app.exportMenu.setScopeAvailable(!!view);
}

export function renderRail(app: App): void {
  const sel = app.selection;
  // An issue selection resolves to its primary node, so the Inspector is never
  // empty just because the user clicked the issue row instead of the card
  // (MLV-R1-006).
  const nodeId = app.selectedNodeId();
  const selectedNode = nodeId && app.index ? app.index.nodeById.get(nodeId) || null : null;
  const selectedEdge = sel && sel.kind === 'edge' && app.index ? app.index.edgeById.get(sel.id) || null : null;
  const selectedIssue = sel && sel.kind === 'issue' && app.index ? app.index.issueById.get(sel.id) || null : null;
  app.rail.update({
    index: app.index,
    tab: app.railTab,
    issues: app.graph ? app.graph.issues : [],
    selectedNode,
    selectedEdge,
    selectedIssueId: sel && sel.kind === 'issue' ? sel.id : null,
    selectedIssue,
    collapsed: app.view.collapsed,
    keep: app.filters.keep,
    scope: railScopeCounts(app.graph),
    staleReason: (file) => app.freshness.reasonOf(file),
  });
}
