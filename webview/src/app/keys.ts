/**
 * The App's end of the keyboard triple (`ui/keymap.ts` -> `ui/commands.ts` ->
 * `ui/appkeys.ts`): what each operation the keyboard may reach actually is.
 *
 * Nothing here decides what a key MEANS — that is `keymap.ts` — and nothing here
 * composes the Escape cascade or the connection walk, which are keyboard
 * behaviours and live in `appkeys.ts`. This is the binding, and only the
 * binding.
 */

import { handleCanvasKey } from '../ui/keymap.js';
import { canvasCommands } from '../ui/commands.js';
import { commandPortFor } from '../ui/appkeys.js';
import { scopeToNode, setScope, stepDepth, toggleScopePicker } from './documents.js';
import type { CommandPort } from '../ui/commands.js';
import type { App } from '../app.js';
import type { Issue } from '../types.js';

export function onCanvasKey(app: App, ev: KeyboardEvent): void {
  handleCanvasKey(ev, canvasCommands(commandPort(app)));
}

/** Everything the keyboard model is allowed to reach (see ui/commands.ts). */
function commandPort(app: App): CommandPort {
  return commandPortFor({
    view: () => app.view,
    index: () => app.index,
    selection: () => app.selection,
    edgeAnchor: () => app.edgeAnchor,
    setEdgeAnchor: (id) => {
      app.edgeAnchor = id;
    },
    select: (sel) => app.select(sel),
    clearSelection: () => app.clearSelection(),
    focusSearch: () => app.search.focus(),
    visibleIssues: () => filteredIssues(app),
    focusIssue: (id) => app.focusIssue(id),
    openSelection: () => {
      const sel = app.selection;
      if (!sel) return false;
      const loc = app.locOf(sel);
      if (loc) app.openLocation(loc);
      return true;
    },
    zoomToSelection: () => app.zoomToSelection(),
    move: (key) => moveSelection(app, key),
    toggleSeverity: (sev) => app.applyFilters(() => app.filters.toggleSeverity(sev)),
    toggleRail: () => app.toggleRail(),
    setRailTab: (tab) => app.setRailTab(tab),
    toggleShortcuts: (next) => app.toggleShortcuts(next),
    sheetOpen: () => app.sheet.open,
    closeScopePicker: () => app.scopeBar.closePicker(),
    scopeSpec: () => app.scopes.spec,
    setScope: (spec) => setScope(app, spec),
    stepDepth: (delta) => stepDepth(app, delta),
    scopeToNode: (id) => scopeToNode(app, id),
    openScopePicker: () => toggleScopePicker(app),
    selectedNodeId: () => app.selectedNodeId(),
    announce: (text) => app.announce(text),
    toggleLegend: () => app.setLegend(!app.legendOpen),
    legendOpen: () => app.legendOpen,
    closeLegend: () => app.setLegend(false),
    toggleFlow: () => app.setFlow(!app.flowOn),
  });
}

function filteredIssues(app: App): Issue[] {
  if (!app.graph) return [];
  return app.graph.issues.filter(app.filters.keep);
}

/** Arrows move the selection among visible siblings, in spatial order. */
function moveSelection(app: App, key: string): void {
  const sel = app.selection;
  const next = app.view.nextSelection(sel && sel.kind === 'node' ? sel.id : null, key);
  if (!next) return;
  app.select({ kind: 'node', id: next.id }, { center: !next.visible });
  const element = app.view.nodeElement(next.id);
  if (element) element.focus();
}
