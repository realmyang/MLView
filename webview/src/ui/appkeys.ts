/**
 * The keyboard model, BOUND — the third and last file of the keyboard triple.
 *
 *   `keymap.ts`   what a key means, and the table the `?` sheet renders
 *   `commands.ts` the shape of the operations a key may reach
 *   this file     how those operations compose out of the application
 *
 * Two behaviours live here in full because they are keyboard behaviours and
 * nothing else calls them:
 *
 *  - THE Escape cascade, in this exact order — shortcut sheet -> focus mode ->
 *    scope -> selection -> blur. One owner writes that order ONCE
 *    (CONTRACTS 11.13); whichever rung fires also stops the flow it owned.
 *  - `e` / `Shift+E`, which walk the selection's connections over the LIVE
 *    routes, so only routes present in the current projection are ever selected
 *    (CONTRACTS 11.14 C4). A cached incident list would focus a route that is no
 *    longer in the DOM.
 */

import type { CommandPort } from './commands.js';
import type { Issue, RailTab, Sel, Severity } from '../types.js';
import type { CanvasView } from '../canvasview.js';
import type { GraphIndex } from '../layout/model.js';

/** Everything the keyboard needs from the application, and nothing more. */
export interface KeyContext {
  view(): CanvasView;
  index(): GraphIndex | null;
  selection(): Sel | null;
  /** The node whose connections `e` is walking, when an edge is selected. */
  edgeAnchor(): string | null;
  setEdgeAnchor(id: string | null): void;
  select(sel: Sel): void;
  clearSelection(): void;
  focusSearch(): void;
  visibleIssues(): Issue[];
  focusIssue(id: string): void;
  openSelection(): boolean;
  zoomToSelection(): void;
  move(key: string): void;
  toggleSeverity(sev: Severity): void;
  toggleRail(): void;
  setRailTab(tab: RailTab): void;
  toggleShortcuts(next?: boolean): void;
  sheetOpen(): boolean;
  closeScopePicker(): boolean;
  scopeSpec(): string | null;
  setScope(spec: string | null): void;
  stepDepth(delta: number): void;
  scopeToNode(id: string): void;
  openScopePicker(): void;
  selectedNodeId(): string | null;
  announce(text: string): void;
}

export function commandPortFor(ctx: KeyContext): CommandPort {
  return {
    focusSearch: () => ctx.focusSearch(),

    dismissTopmost: () => {
      if (ctx.closeScopePicker()) return;
      if (ctx.sheetOpen()) ctx.toggleShortcuts(false);
      else if (ctx.view().isFocusLocked) ctx.view().toggleFocusMode(ctx.selection());
      else if (ctx.scopeSpec()) ctx.setScope(null);
      else if (ctx.selection()) {
        // A connection reached with `e` still holds DOM focus, and focus alone
        // is a flow trigger (interaction table row 3). Clearing the selection
        // without blurring left it emphasised, focused and stripped of every
        // port and charge (MLV-R1-FLOW-011).
        ctx.view().blurFocusedEdge();
        ctx.clearSelection();
      } else ctx.view().canvasEl.blur();
    },

    visibleIssues: () => ctx.visibleIssues(),
    selectedIssueId: () => {
      const sel = ctx.selection();
      return sel && sel.kind === 'issue' ? sel.id : null;
    },
    focusIssue: (id) => ctx.focusIssue(id),
    zoom: (direction) => ctx.view().zoomStep(direction),
    fit: () => ctx.view().fit(),
    toggleFocusMode: () => ctx.view().toggleFocusMode(ctx.selection()),
    zoomToSelection: () => ctx.zoomToSelection(),

    collapseSelection: () => {
      const sel = ctx.selection();
      const index = ctx.index();
      if (!sel || sel.kind !== 'node' || !index) return false;
      const target = index.isGroup(sel.id) ? sel.id : index.parentOf.get(sel.id) || null;
      if (!target || !index.isGroup(target)) return false;
      ctx.view().toggleCollapse(target);
      return true;
    },

    openSelection: () => ctx.openSelection(),
    move: (key) => ctx.move(key),
    toggleSeverity: (sev) => ctx.toggleSeverity(sev),
    toggleRail: () => ctx.toggleRail(),
    setRailTab: (tab) => ctx.setRailTab(tab),
    toggleShortcuts: () => ctx.toggleShortcuts(),

    cycleConnections: (backwards) => cycleConnections(ctx, backwards),

    scopeToSelection: () => {
      const id = ctx.selectedNodeId();
      if (!id) {
        ctx.openScopePicker();
        return true;
      }
      ctx.scopeToNode(id);
      return true;
    },

    clearScope: () => {
      if (!ctx.scopeSpec()) return false;
      ctx.setScope(null);
      return true;
    },

    stepDepth: (delta) => {
      if (!ctx.scopeSpec()) return false;
      ctx.stepDepth(delta);
      return true;
    },
  };
}

function cycleConnections(ctx: KeyContext, backwards: boolean): boolean {
  const sel = ctx.selection();
  let anchor: string | null = null;
  if (sel && sel.kind === 'node') anchor = sel.id;
  else if (sel && sel.kind === 'edge') anchor = ctx.edgeAnchor();
  if (!anchor) return false;

  const routes = ctx.view().incidentRoutes(anchor);
  if (!routes.length) {
    ctx.view().toast('That node has no connections in this view.');
    return true;
  }
  const currentId = sel && sel.kind === 'edge' ? sel.id : null;
  let at = -1;
  for (let i = 0; i < routes.length; i++) {
    if (routes[i].id === currentId) at = i;
  }
  const next =
    at < 0
      ? routes[backwards ? routes.length - 1 : 0]
      : routes[(at + (backwards ? -1 : 1) + routes.length) % routes.length];

  ctx.setEdgeAnchor(anchor);
  ctx.select({ kind: 'edge', id: next.id });
  ctx.setEdgeAnchor(anchor); // `select` clears it for a non-edge selection
  ctx.view().focusEdge(next.id);
  // Announced only for KEYBOARD-driven flows: narrating every mouse sweep into
  // the live region is the aural equivalent of strobing (FEATURES 2.10).
  ctx.announce(ctx.view().edgeAnnouncement(next));
  return true;
}
