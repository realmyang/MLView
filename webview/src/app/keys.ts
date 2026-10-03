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
import { renderChrome } from './surfaces.js';
import type { CommandPort } from '../ui/commands.js';
import type { App } from '../app.js';
import type { Issue } from '../types.js';

export function onCanvasKey(app: App, ev: KeyboardEvent): void {
  const port = commandPort(app);
  handleCanvasKey(ev, canvasCommands(holdingHover(app, app.view.overviewOpen ? closingOverview(app, port) : port)));
}

/**
 * Viewer M3 (live check, W3): the keys that move the selection or the view (the arrows, `e` /
 * Shift+E, `n` / `p`, zoom, fit and `z`). Each first holds the hover back until the pointer moves
 * (`CanvasView.holdHover`), so a card the diagram pans under a resting pointer shows no hover card.
 * The review walk's steps do the same in `App.showWalkClaim`.
 */
const HOLDS_HOVER: ReadonlySet<string> = new Set(['move', 'cycleConnections', 'focusIssue', 'zoom', 'fit', 'zoomToSelection']);

function holdingHover(app: App, port: CommandPort): CommandPort {
  const out = { ...port } as Record<string, unknown>;
  for (const name of HOLDS_HOVER) {
    const fn = (port as unknown as Record<string, (...a: unknown[]) => unknown>)[name];
    out[name] = (...args: unknown[]) => {
      app.view.holdHover();
      return fn(...args);
    };
  }
  return out as unknown as CommandPort;
}

/**
 * What leaves the phase overview open: the port's questions (asking must not close it), Escape and
 * Shift+0 (they close it themselves), and the panels that open over it or beside it (the shortcut
 * sheet, the search, the legend, the side panel and its tabs).
 */
const KEEP_OPEN: ReadonlySet<string> = new Set(['walking', 'visibleIssues', 'selectedIssueId', 'dismissTopmost', 'overview',
  'toggleShortcuts', 'focusSearch', 'toggleLegend', 'toggleRail', 'focusRailTabs']);

/**
 * Viewer M3: while the phase overview is open, a key the canvas acts on (r, 0, f, n, a severity
 * toggle…) first closes the overview without moving the diagram, then acts on it, as if the reader
 * had pressed Escape first. `KEEP_OPEN` lists what does not, and a key the canvas does not answer
 * leaves the overview open too.
 */
function closingOverview(app: App, port: CommandPort): CommandPort {
  const out = {} as Record<string, unknown>;
  for (const [name, fn] of Object.entries(port)) {
    out[name] = KEEP_OPEN.has(name)
      ? fn
      : (...args: unknown[]) => {
          if (app.view.overviewOpen) {
            app.view.closeOverview(false);
            renderChrome(app);
          }
          return (fn as (...a: unknown[]) => unknown)(...args);
        };
  }
  return out as unknown as CommandPort;
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
      // Viewer M3: in the review walk, Enter opens the walk's current quote of this claim again.
      if (app.walk.active && app.walkOwns(sel)) return app.walk.reopen(focusEditor);
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
    closePhasePopover: () => app.view.closePhasePopover(),
    closeOverview: () => {
      if (!app.view.closeOverview(true)) return false;
      renderChrome(app);
      return true;
    },
    toggleOverview: () => app.toggleOverview(),
    walking: () => app.walk.active,
    endWalk: () => app.walk.stop(),
    review: () => app.walk.toggle(),
    walkStep: (delta) => app.walk.step(delta),
    walkQuote: (delta) => app.walk.stepQuote(delta),
    walkJump: (kind, backwards) => app.walk.jump(kind, backwards),
  });
}

function filteredIssues(app: App): Issue[] {
  if (!app.graph) return [];
  return app.graph.issues.filter(app.filters.keep);
}

/**
 * Arrows move the selection among visible siblings, in spatial order. Viewer M3: right after a move
 * to a phase (the overview, the phase index), the first arrow selects that phase's first step; from
 * a connection an arrow selects the end that lies that way, and from a finding it moves as from the
 * step marked for it (`CanvasView.nextSelection`).
 */
function moveSelection(app: App, key: string): void {
  const lane = app.view.takeArrowLane();
  const first = lane && app.index ? app.index.roots(lane)[0] : undefined;
  if (first) {
    const box = app.view.frame ? app.view.frame.boxes.get(first) : undefined;
    app.select({ kind: 'node', id: first }, { center: !!box && !app.view.viewport.isVisible(box) });
    const element = app.view.nodeElement(first);
    if (element) element.focus();
    return;
  }
  // Viewer M3 (live check, W5): from a connection or a finding too, not only from a step.
  const next = app.view.nextSelection(app.selection, key);
  if (!next) return;
  app.select({ kind: 'node', id: next.id }, { center: !next.visible });
  const element = app.view.nodeElement(next.id);
  if (element) element.focus();
}
