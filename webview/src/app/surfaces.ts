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
import type { NotObservedCounts } from '../ui/chrome.js';
import type { IssueCounts, Severity } from '../types.js';

/**
 * Viewer M2: the claims in view the author marked inferred or unresolved, by unit. A merged
 * cable is not counted as one: every authored connection counts once.
 */
export function notObservedCounts(app: App): NotObservedCounts {
  const out: NotObservedCounts = { steps: 0, connections: 0, findings: 0 };
  if (!app.graph) return out;
  const exception = (basis: string | undefined) => !!basis && basis !== 'observed';
  for (const node of app.graph.nodes) if (exception(node.basis)) out.steps++;
  for (const edge of app.graph.edges) if (exception(edge.basis)) out.connections++;
  for (const issue of app.graph.issues) if (exception(issue.basis)) out.findings++;
  return out;
}

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
  const notObserved = notObservedCounts(app);
  // A revision (or scope) with nothing left to single out cannot keep the observed claims faded:
  // the toggle that would undo it is hidden.
  if (app.exceptionsOn && notObserved.steps + notObserved.connections + notObserved.findings === 0) {
    app.exceptionsOn = false;
    app.view.canvasEl.removeAttribute('data-exceptions');
  }
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
    notObserved,
    exceptionsOn: app.exceptionsOn,
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
