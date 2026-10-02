/**
 * `ViewState`, both directions (CONTRACTS 11.9).
 *
 * One rule decides the shape of everything here: **a field is ABSENT at its
 * default**. An older host then round-trips a state it has never seen, and a
 * newer viewer restores to the documented default rather than to whatever
 * `undefined` happens to render as. The reader of a restored state must
 * therefore treat a missing field as the default, never as "off".
 */

import { sanitizeScope } from '../protocol.js';
import { syncCollapsed } from './documents.js';
import { composerViewState } from '../workflow.js';
import { renderChrome, renderRail } from './surfaces.js';
import type { App } from '../app.js';
import type { HostBridge, ViewState } from '../types.js';

export function applyState(app: App, state: ViewState, rerender: boolean): void {
  if (!state || typeof state !== 'object') return;
  if (state.filters) app.filters.restore(state.filters);
  if (state.railTab) app.railTab = state.railTab;
  if (Array.isArray(state.collapsed)) {
    app.collapsedState = state.collapsed.slice();
    const index = app.index;
    if (index) app.view.setCollapsed(state.collapsed.filter((id) => index.isGroup(id)));
  }
  if (state.selection) app.selection = state.selection;
  if (typeof state.minimapCollapsed === 'boolean') app.view.setMinimapCollapsed(state.minimapCollapsed);
  if (typeof state.flow === 'boolean') app.setFlow(state.flow);
  if (typeof state.legendOpen === 'boolean') app.setLegend(state.legendOpen);
  // Keys this viewer no longer writes (`railGroupBy`, `answersOpen`, `diffOnly`,
  // `pipelineChosen` from the analyzer-era viewer) are ignored, never an error.
  const scope = sanitizeScope(state.scope);
  // No graph yet? The host mounts the viewer empty and restores state before
  // it posts one, so applying here would drop the scope on the floor (R2H-03).
  if (scope && app.scopes.full) app.setScope(scope.spec, { depth: scope.depth });
  else if (scope) app.pendingScope = { spec: scope.spec, depth: scope.depth };
  if (rerender && app.index) {
    app.view.relayout();
    renderChrome(app);
    renderRail(app);
    app.view.applySelection(app.selection);
  }
  if (state.viewport) app.view.viewport.set(state.viewport);
}

export function snapshotState(app: App): ViewState {
  syncCollapsed(app);
  const state: ViewState = {
    viewport: { ...app.viewportState },
    selection: app.selection ? { ...app.selection } : null,
    collapsed: app.collapsedState.slice(),
    filters: app.filters.snapshot(),
    railTab: app.railTab,
    minimapCollapsed: app.view.minimapCollapsed,
  };
  const spec = app.scopes.spec;
  if (spec) state.scope = { spec, depth: app.scopes.depth };
  if (!app.flowOn) state.flow = false;
  // Absent at its default, like `scope` and `flow`: an older host round-trips
  // a state it has never seen, and a newer one restores to the documented
  // default rather than to whatever `undefined` renders as.
  if (app.legendOpen) state.legendOpen = true;
  // VIEWUI-3: which authored revision the viewport belongs to, so a remount
  // restores it only for that revision.
  if (app.graph && app.workflowRevision) {
    state.workflowRevision = app.workflowRevision;
    // VIEWUI-4: the Refine composer of that revision, absent at its default.
    const composer = composerViewState(app.root);
    if (composer) state.composer = composer;
  }
  return state;
}

/** A host whose `loadState` throws must not take the viewer down with it. */
export function safeLoad(bridge: HostBridge): ViewState | null {
  try {
    return bridge.loadState();
  } catch (_e) {
    return null;
  }
}
