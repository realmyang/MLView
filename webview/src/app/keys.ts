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
    focusSearch: () => app.focusSearch(),
    visibleIssues: () => filteredIssues(app),
    // `n` / `p` walk the findings in the Findings list's order: that list keeps its place while it
    // is the tab on screen, and expands each finding in turn (viewer M2 review, M2-INT-1).
    focusIssue: (id) => app.focusIssue(id, { fromList: 'issues' }),
    // Viewer M1: Enter opens beside the panel and keeps focus here, so the keys keep working;
    // Alt+Enter moves focus to the editor.
    openSelection: (focusEditor) => {
      const sel = app.selection;
      if (!sel) return false;
      const loc = app.locOf(sel);
      if (loc) app.openLocation(loc, focusEditor);
      return true;
    },
    zoomToSelection: () => app.zoomToSelection(),
    move: (key) => moveSelection(app, key),
    toggleSeverity: (sev) => app.applyFilters(() => app.filters.toggleSeverity(sev)),
    toggleRail: () => app.toggleRail(),
    focusRailTabs: () => app.focusRailTabs(),
    toggleShortcuts: (next) => app.toggleShortcuts(next),
    sheetOpen: () => app.sheet.open,
    closeHeaderPanels: () => app.closeHeaderPanels(),
    collapseSheet: () => app.collapseSheet(false),
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
