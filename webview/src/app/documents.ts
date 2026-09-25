/**
 * The DOCUMENT and what narrows it: the whole-workspace graph, the scope, the
 * diff overlay and the pipeline chooser.
 *
 * One rule runs through all of it (CONTRACTS 11.8): narrowing is LOCAL. A scope
 * change, a depth step, "changed only" and a dismissed comparison never post
 * `requestRefresh`, never reach the analyzer and never throw — an unresolvable
 * selector is a no-op plus a toast. `setGraph` owns the full graph and the
 * collapse set; `applyProjection` draws whatever the scope currently selects, so
 * chrome, rail, outline, minimap and layout are scoped with no further edits —
 * they all read only the index (FEATURES 5.1).
 */

import { GraphIndex } from '../layout/model.js';
import { adoptDiff } from '../diff/adopt.js';
import { adoptCellMap } from '../notebook.js';
import { mergeCollapsed, sameScope } from '../scope/session.js';
import { pipelineRows } from '../scope/catalog.js';
import { chooserRows, shouldAskPipeline } from '../ui/pipelinechooser.js';
import { renderChrome, renderRail } from './surfaces.js';
import type { DiffIndex } from '../diff/overlay.js';
import type { App } from '../app.js';
import type { MLGraph, ScopeSummary, ViewState, Viewport } from '../types.js';

/* ── graph + layout ──────────────────────────────────────────────────── */

/**
 * A NEW whole-workspace document. `setGraph` owns the full graph and the
 * collapse set; `applyProjection` draws whatever the scope currently selects.
 */
export function setGraph(app: App, graph: MLGraph, preserve?: Partial<ViewState>, reresolve = false): void {
  // What the HOST currently believes the scope is. A new document can move it
  // without any user gesture — the scope is re-resolved, and dropped when it
  // now matches nothing — and `scopeChanged` is the host's only writer of the
  // panel title and description (CONTRACTS 11.7, 11.11). Without this the tab
  // kept reading `MLView — validate()` over a whole-workspace diagram
  // (R2H-01 / R2-REG-02).
  const before = app.scopes.full ? app.scopes.summary() : null;
  // NB / 11.29 N6. The notebook cell mapping arrives in `Node.attrs` as
  // strings, because `Loc` is frozen (§2). Lift it onto each node's own `Loc`
  // once, here, so every label surface keeps reading a plain `Loc` and none of
  // them has to know where the analyzer keeps its provenance. A `.py`
  // document, and a notebook node the ingest could not map, are untouched.
  adoptCellMap(graph.nodes);
  app.rawGraph = graph;
  // VIEW-08. The overlay is lifted onto a COPY: `diffStatus` lands on the
  // nodes it describes and the removed ones come back as ghosts in place, so
  // every drawing surface below keeps reading a plain document (11.38, and the
  // same shape as `adoptCellMap` above).
  const diff = app.scopes.diff;
  if (diff) graph = adoptDiff(graph, diff);
  app.scopes.setGraph(graph);
  app.fullIndex = new GraphIndex(graph);
  // The collapse set is held against the FULL id space and filtered at
  // projection time, so collapsing inside a scope and then clearing it does
  // not lose the collapse (FEATURES 3.5).
  if (preserve && preserve.collapsed) app.collapsedState = preserve.collapsed.slice();
  else if (!app.collapsedState.length && app.view.collapsed.size === 0) {
    app.collapsedState = app.fullIndex.defaultCollapsed();
  }
  if (reresolve && app.scopes.reresolve()) app.view.toast('Scope no longer matches — cleared');
  applyProjection(app, preserve, true);
  const pending = app.pendingScope;
  app.pendingScope = null;
  // A drained scope announces, posts and persists through `afterScopeChange`,
  // so it needs no second post; anything else that moved the host's view of
  // the scope does. A viewport restored with the scope (webview recreation,
  // VIEWUI-3) belongs to the scoped view, so the drain applies it too.
  if (pending && drainScope(app, pending, preserve && preserve.viewport ? preserve.viewport : undefined)) return;
  if (before && !sameScope(before, app.scopes.summary())) postScopeChanged(app);
  // MLV-P12: after the document is drawn and any pending scope has drained,
  // so a reader who already has a scope is never asked which pipeline to open.
  maybeOpenPipelineChooser(app);
}

/**
 * Apply a scope that arrived BEFORE the document did — a restored
 * `ViewState.scope`, or the report's `data-mlview-scope` attribute.
 *
 * CONTRACTS 11.9's re-resolve applies here too: a spec that matches nothing in
 * the document that finally arrived is dropped with the same toast rather than
 * left standing as an empty diagram the user never asked for. Returns true when
 * it applied the scope and therefore already posted `scopeChanged`.
 */
function drainScope(app: App, pending: { spec: string; depth?: number }, viewport?: Viewport): boolean {
  const result = app.scopes.set(pending.spec, pending.depth);
  if (!result.ok) {
    const error = result.error;
    app.view.toast(error ? error.code + ': ' + error.term : 'That scope could not be applied');
    return false;
  }
  if (result.empty) {
    app.scopes.set(null);
    app.view.toast('Scope no longer matches — cleared');
    return false;
  }
  afterScopeChange(app, viewport);
  return true;
}

/** Draw the current projection. */
export function applyProjection(app: App, preserve?: Partial<ViewState>, announce = false): void {
  const doc = app.scopes.document;
  if (!doc) return;
  const graph = doc;
  app.graph = graph;
  // Reuse the full index only when the document really IS the full one. The
  // test used to be `spec === null`, which VIEW-08 made wrong: a diff
  // projection narrows the document without any selector being set, and
  // indexing the whole graph for it drew every node the projection had just
  // removed.
  const index = graph === app.scopes.full && app.fullIndex ? app.fullIndex : new GraphIndex(graph);
  app.index = index;
  app.error = null;
  app.showLoading(false);

  const known = new Set(graph.nodes.map((n) => n.id));
  const collapsed = preserve && preserve.collapsed ? preserve.collapsed : app.collapsedState;
  app.view.setIndex(index);
  // Every flow element and every --mlv-flow-* property goes before the scene
  // is rebuilt, and the remembered endpoint ids reset (CONTRACTS 11.14 C1).
  app.view.flow.clear();
  app.view.setCollapsed(collapsed.filter((id) => known.has(id) && index.isGroup(id)));

  if (preserve && preserve.selection !== undefined) app.selection = preserve.selection;
  if (app.selection && app.selection.kind === 'node' && !known.has(app.selection.id)) app.selection = null;
  if (app.selection && app.selection.kind === 'edge' && !index.edgeById.has(app.selection.id)) app.selection = null;
  // VIEWUI-15: a finding the new revision removed is not a selection either,
  // or the Inspector goes blank and the composer posts a stale id.
  if (app.selection && app.selection.kind === 'issue' && !index.issueById.has(app.selection.id)) app.selection = null;

  app.view.relayout();
  const vp = preserve && preserve.viewport ? preserve.viewport : null;
  if (vp) app.view.viewport.set(vp);
  else app.view.fit();
  renderChrome(app);
  renderRail(app);
  app.view.applySelection(app.selection);
  if (announce) {
    app.announce(
      'Workflow loaded: ' +
        graph.nodes.length +
        ' nodes, ' +
        graph.issues.length +
        ' findings, ' +
        graph.stats.issues.high +
        ' high severity.',
    );
  }
  app.saveSoon();
}

/* ── scope ───────────────────────────────────────────────────────────── */

/** Merge the drawn collapse set back into the full-id-space one. */
export function syncCollapsed(app: App): void {
  app.collapsedState = mergeCollapsed(
    app.collapsedState,
    app.graph ? app.graph.nodes.map((n) => n.id) : [],
    app.view.collapsed,
  );
}

export function toggleScopePicker(app: App): void {
  app.scopeBar.togglePicker(app.scopes.full, app.scopes.spec, app.scopes.depth);
}

/**
 * Re-project and relayout LOCALLY. Never posts `requestRefresh`, never touches
 * the analyzer, and never throws: an unresolvable spec is a no-op plus a toast
 * (CONTRACTS 11.8).
 */
export function setScope(app: App, spec: string | null, opts?: { depth?: number }): void {
  if (!app.scopes.full) return;
  const wasScoped = app.scopes.spec !== null;
  if (!wasScoped && spec) {
    // Clearing restores the viewport and the selection from before the scope
    // was set, so [x] feels like a back button rather than a reset.
    app.preScope = { viewport: { ...app.viewportState }, selection: app.selection ? { ...app.selection } : null };
  }
  const result = app.scopes.set(spec, opts ? opts.depth : undefined);
  if (!result.ok) {
    const error = result.error;
    app.view.toast(error ? error.code + ': ' + error.term : 'That scope could not be applied');
    return;
  }
  afterScopeChange(app);
  if (!app.scopes.spec && app.preScope) {
    const back = app.preScope;
    app.preScope = null;
    // The viewport always comes back, so [x] feels like a back button. The
    // SELECTION only comes back when the user has not made a new one inside
    // the scope — clearing a scope must never throw away what they just
    // picked, and the Escape cascade's next rung is that selection.
    if (!app.selection) app.selection = back.selection;
    app.view.viewport.set(back.viewport);
    app.view.applySelection(app.selection);
    renderRail(app);
  }
  if (result.empty) app.view.toast('Nothing in this scope — ' + (spec || ''));
}

export function stepDepth(app: App, delta: number): void {
  const result = app.scopes.stepDepth(delta);
  if (!result.ok) return;
  afterScopeChange(app);
}

/**
 * The Inspector's "Scope to this unit / step". An authored node is scoped by
 * its stable id, never by its label: labels are free text and may repeat
 * (VIEWUI-7). `resolveUnit` matches the id first.
 */
export function scopeToNode(app: App, nodeId: string): void {
  const node = app.fullIndex ? app.fullIndex.nodeById.get(nodeId) : null;
  if (!node) return;
  const authored = !!app.scopes.full && app.scopes.full.schemaVersion === 'workflow-view/1';
  app.setScope('unit:' + (authored ? node.id : node.qualname));
}

/**
 * Applied, announced, posted and persisted. A scope change is LOCAL: it never
 * posts `requestRefresh` and never reaches the analyzer (CONTRACTS 11.8).
 */
function afterScopeChange(app: App, viewport?: Viewport): void {
  syncCollapsed(app);
  // Only a drained, restored scope passes a viewport; every user gesture refits.
  applyProjection(app, viewport ? { viewport } : undefined);
  const summary = postScopeChanged(app);
  app.announce(
    summary.spec
      ? 'Scoped to ' + summary.label + ', ' + summary.nodes + ' of ' + summary.of + ' nodes.'
      : 'Scope cleared, showing all ' + summary.of + ' nodes.',
  );
  app.saveSoon();
}

/**
 * The ONE place `scopeChanged` is posted. Every scope change goes through it,
 * including a clear (`spec: null`, `label: "Everything"`, `nodes === of`) and
 * including the one nobody asked for: a re-analysis whose new document no
 * longer contains the scoped unit (CONTRACTS 11.7).
 */
function postScopeChanged(app: App): ScopeSummary {
  const summary = app.scopes.summary();
  app.bridge.post({
    v: 1,
    type: 'scopeChanged',
    spec: summary.spec,
    label: summary.label,
    nodes: summary.nodes,
    of: summary.of,
  });
  return summary;
}

/* ── the pipeline chooser (MLV-P12) ──────────────────────────────────── */

/**
 * Open the chooser on a workspace with two or more pipelines — once.
 *
 * A reader who arrived with a scope already applied (a restored `ViewState`,
 * the report's `data-mlview-scope`, a host `setScope`) has ALREADY answered
 * the question, so they are not asked; nor is anyone who answered it before,
 * which `ViewState.pipelineChosen` remembers. The relation is computed here,
 * never read off the emitted `pipelines[]` block (CONTRACTS 11.47 A).
 */
function maybeOpenPipelineChooser(app: App): void {
  if (app.pipelineChosen || app.chooser.open) return;
  const graph = app.scopes.full;
  if (!graph || app.scopes.spec || app.pendingScope) return;
  // VIEWUI-5. Authored entrypoints are chosen by the user, not ranked by a
  // heuristic, and pipelines are not part of the WorkflowDocument contract, so
  // an authored document never gets the chooser or its analyzer caveats.
  if (graph.schemaVersion === 'workflow-view/1') return;
  const rows = pipelineRows(graph);
  // VIEW-R5. Two or more rows is not enough to earn a modal over the first
  // paint: `workspace.entrypoints` is a ranked heuristic, so on the 54-node
  // demo it offered a one-node `config.py` as a pipeline and covered the one
  // screen VIEW-01 exists to protect. `shouldAskPipeline` owns the floor, and
  // the chooser itself draws only the rows that clear it.
  if (!shouldAskPipeline(graph, rows)) return;
  app.chooser.show(graph, rows);
  app.announce(
    'This workspace has ' + chooserRows(rows).length + ' pipelines. Choose one, or show everything.',
  );
}

/**
 * The chooser's one exit. Every answer — a pipeline, "everything", Escape —
 * is recorded, so the question is asked once per viewer and never again.
 */
export function answerPipelineChooser(app: App, spec: string | null): void {
  app.chooser.hide();
  app.pipelineChosen = true;
  if (spec) app.setScope(spec);
  else app.announce('Showing the whole workspace, every pipeline at once.');
  // VIEW-R7. The chooser opens by itself, so there is no invoking element to
  // restore to and `hide()` alone drops focus onto <body> — a keyboard reader
  // would have to tab from the top of the document to reach the diagram they
  // just chose. Hand focus to the canvas, which owns the roving tab stop, the
  // same way the shortcuts sheet does when it closes.
  try {
    app.view.canvasEl.focus();
  } catch (_e) {
    /* a host may have torn the canvas down under us */
  }
  app.saveSoon();
}

/* ── the diff overlay (VIEW-08) ──────────────────────────────────────── */

/**
 * Install, replace or clear the overlay. It is a SIBLING document: nothing is
 * re-analysed, nothing is posted, and the graph the host gave us is re-adopted
 * from the pristine copy so dismissing a diff really does put the diagram back
 * exactly as it was.
 */
export function setDiff(app: App, diff: DiffIndex | null): void {
  if (!diff) app.diffBaseLabel = '';
  app.scopes.setDiff(diff);
  const graph = app.rawGraph;
  if (graph) {
    setGraph(app, graph, {
      viewport: { ...app.viewportState },
      selection: app.selection,
      collapsed: app.collapsedState.slice(),
    });
  } else {
    renderChrome(app);
  }
  app.announce(
    diff
      ? 'Comparison loaded: ' + diff.headline() + '.'
      : 'Comparison cleared; showing this analysis on its own.',
  );
  app.saveSoon();
}

/**
 * "Changed only" — the diff as a PROJECTION (ROADMAP VIEW-08). Local, like
 * every scope change: it never posts `requestRefresh` and never re-analyses.
 */
export function setChangedOnly(app: App, next: boolean): void {
  const ok = app.scopes.setChangedOnly(next);
  syncCollapsed(app);
  applyProjection(app);
  if (!ok) {
    app.view.toast('Nothing that changed is in this view');
    app.announce('Changed only: nothing that changed is in this view.');
    app.saveSoon();
    return;
  }
  const shown = app.graph ? app.graph.nodes.length : 0;
  const of = app.scopes.full ? app.scopes.full.nodes.length : 0;
  app.announce(
    next
      ? 'Showing what changed: ' + shown + ' of ' + of + ' nodes, plus one hop.'
      : 'Changed-only view off, showing all ' + of + ' nodes.',
  );
  app.saveSoon();
}
