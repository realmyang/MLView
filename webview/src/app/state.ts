/**
 * `ViewState`, both directions (CONTRACTS 11.9).
 *
 * One rule decides the shape of everything here: **a field is ABSENT at its
 * default**. An older host then round-trips a state it has never seen, and a
 * newer viewer restores to the documented default rather than to whatever
 * `undefined` happens to render as. The reader of a restored state must
 * therefore treat a missing field as the default, never as "off".
 */

import { syncCollapsed } from './documents.js';
import { composerViewState } from '../workflow.js';
import { renderChrome, renderRail } from './surfaces.js';
import { sanitizeRailTab, sanitizeSelection } from '../ui/commands.js';
import type { App } from '../app.js';
import type { HostBridge, ViewState } from '../types.js';

export function applyState(app: App, state: ViewState, rerender: boolean): void {
  if (!state || typeof state !== 'object') return;
  if (state.filters) app.filters.restore(state.filters);
  // Viewer M2: a tab this viewer does not have (a hand-edited or future state) is ignored.
  const tab = sanitizeRailTab(state.railTab);
  if (tab) app.railTab = tab;
  if (Array.isArray(state.collapsed)) {
    app.collapsedState = state.collapsed.slice();
    const index = app.index;
    if (index) app.view.setCollapsed(state.collapsed.filter((id) => index.isGroup(id)));
  }
  // Viewer M2 live fix: a state the page restores itself (`rerender` false, the App's constructor)
  // keeps its selection for the first `setWorkflow`, which applies it only for the revision it was
  // saved with; a state the host posts (`restoreState`) applies at once.
  const selection = sanitizeSelection(state.selection);
  if (rerender && selection) app.selection = selection;
  // Viewer M3: the phase index (it replaced the minimap): folded to its pill, or hidden. A state
  // saved before M3 with the minimap collapsed opens with the index folded.
  if (state.phaseIndex === 'folded' || state.phaseIndex === 'hidden') app.view.setPhaseIndex({ folded: state.phaseIndex === 'folded', hidden: state.phaseIndex === 'hidden' });
  else if (state.phaseIndex === undefined && state.minimapCollapsed === true) app.view.setPhaseIndex({ folded: true });
  else if (state.phaseIndex === undefined && rerender) app.view.setPhaseIndex({ folded: false, hidden: false });
  if (typeof state.flow === 'boolean') app.setFlow(state.flow);
  if (typeof state.legendOpen === 'boolean') app.setLegend(state.legendOpen);
  // Keys this viewer no longer writes (`railGroupBy`, `answersOpen`, `diffOnly`,
  // `pipelineChosen` from the analyzer-era viewer; since viewer M2 the scope picker's `scope` and
  // the phase chips' `filters.stages`) are ignored, never an error: the whole document is drawn.
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
  };
  // Viewer M3: absent at its default (shown, unfolded); `minimapCollapsed` is no longer written.
  if (app.view.phaseIndexHidden) state.phaseIndex = 'hidden';
  else if (app.view.phaseIndexFolded) state.phaseIndex = 'folded';
  if (!app.flowOn) state.flow = false;
  // Absent at its default, like `flow`: an older host round-trips
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
    // Viewer M2 live fix: an open bottom sheet, absent when it is collapsed or the rail is docked.
    if (app.railMode === 'sheet' && app.railOpen) state.sheetOpen = true;
    // Viewer M3: the review walk's place (filter, claim, quote, running), absent before a walk.
    const walk = app.walk.viewState();
    if (walk) state.walk = walk;
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
