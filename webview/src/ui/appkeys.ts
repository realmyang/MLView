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
 *  - THE Escape cascade, in this exact order — shortcut sheet -> the Refine…
 *    popover -> the phase index's open list -> legend -> the phase overview ->
 *    the review walk -> the open bottom panel -> focus mode -> selection -> blur.
 *    One owner writes that order ONCE; whichever rung fires also stops the flow
 *    it owned.
 *  - `e` / `Shift+E`, which walk the selection's connections over the LIVE
 *    routes, so only routes present in the current projection are ever selected.
 *    A cached incident list could focus a route that has left the DOM.
 */

import type { CommandPort } from './commands.js';
import type { Issue, Sel, Severity } from '../types.js';
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
  openSelection(focusEditor: boolean): boolean;
  zoomToSelection(): void;
  move(key: string): void;
  /** The legend panel and the flow animation, both keyboard-reachable. */
  toggleLegend(): void;
  /** Whether the legend is showing — its rung of the Escape cascade. */
  legendOpen(): boolean;
  closeLegend(): void;
  toggleFlow(): void;
  toggleSeverity(sev: Severity): void;
  toggleRail(): void;
  focusRailTabs(): void;
  toggleShortcuts(next?: boolean): void;
  sheetOpen(): boolean;
  /** Close the Refine… popover; false when it is not open. */
  closeHeaderPanels(): boolean;
  /** Collapse the open bottom panel to its tab strip; false when there is none. */
  collapseSheet(): boolean;
  announce(text: string): void;
  /** Close the phase index's open list (the pill's); false when it was not open. */
  closePhasePopover(): boolean;
  /** Leave the phase overview for where the reader was; false when it was not open. */
  closeOverview(): boolean;
  /** Open or close the phase overview (Shift+0). */
  toggleOverview(): void;
  /** The review walk. */
  walking(): boolean;
  /** End the walk; false when it was not running. */
  endWalk(): boolean;
  review(): void;
  walkStep(delta: number): boolean;
  walkQuote(delta: number): boolean;
  walkJump(kind: 'notObserved' | 'findings', backwards: boolean): boolean;
  /** Look at the other end of the walk's connection; false when the walk is not on one. */
  walkOtherEnd(): boolean;
}

export function commandPortFor(ctx: KeyContext): CommandPort {
  return {
    focusSearch: () => ctx.focusSearch(),

    dismissTopmost: () => {
      if (ctx.sheetOpen()) ctx.toggleShortcuts(false);
      // The panels that open over the diagram from the header, before anything on the canvas.
      else if (ctx.closeHeaderPanels()) return true;
      // The phase index's open list (the pill's), a small panel over the diagram.
      else if (ctx.closePhasePopover()) return true;
      // The legend is a PANEL over the diagram, opened with `l` and closed with
      // its own [x] — and Escape is what a reader presses at a panel. It sits
      // above focus mode because it is the shallower thing on screen: dismissing
      // it must never also throw away the focus or selection underneath.
      else if (ctx.legendOpen()) ctx.closeLegend();
      // The phase overview covers the whole canvas; Escape goes back to the diagram as it
      // was (the overview's own keys do the same when it has the focus).
      else if (ctx.closeOverview()) return true;
      // The review walk ends before anything it opened is closed: the claim it was on
      // stays selected and the bottom panel stays open on it. One Escape ends it, whatever else is
      // on screen below it, so it never takes two presses to leave the walk.
      else if (ctx.endWalk()) return true;
      // The open bottom panel collapses to its tab strip before anything on the canvas
      // is undone: the selection it shows stays selected.
      else if (ctx.collapseSheet()) return true;
      else if (ctx.view().isFocusLocked) ctx.view().toggleFocusMode(ctx.selection());
      else if (ctx.selection()) {
        // A connection reached with `e` still holds DOM focus, and focus alone
        // is a flow trigger. Clearing the selection without blurring would leave
        // it emphasised, focused and stripped of every port and charge.
        ctx.view().blurFocusedEdge();
        ctx.clearSelection();
      } else {
        // Leave the canvas. When the focus is already off it, there is nothing left for this
        // Escape to do here, and the key goes on to VS Code.
        const canvas = ctx.view().canvasEl;
        const active = canvas.ownerDocument ? canvas.ownerDocument.activeElement : null;
        if (!active || !canvas.contains(active)) return false;
        canvas.blur();
      }
      return true;
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
    overview: () => ctx.toggleOverview(),
    toggleLegend: () => ctx.toggleLegend(),
    toggleFlow: () => ctx.toggleFlow(),
    // A flow settles after two passes; Shift+A runs it again from its first pass.
    replayFlow: () => {
      if (!ctx.view().flow.replay()) return false;
      ctx.announce('Playing the connection flow again.');
      return true;
    },

    collapseSelection: () => {
      const sel = ctx.selection();
      const index = ctx.index();
      if (!sel || sel.kind !== 'node' || !index) return false;
      const target = index.isGroup(sel.id) ? sel.id : index.parentOf.get(sel.id) || null;
      if (!target || !index.isGroup(target)) return false;
      ctx.view().toggleCollapse(target);
      return true;
    },

    openSelection: (focusEditor) => ctx.openSelection(focusEditor),
    move: (key) => ctx.move(key),
    toggleSeverity: (sev) => ctx.toggleSeverity(sev),
    toggleRail: () => ctx.toggleRail(),
    focusRailTabs: () => ctx.focusRailTabs(),
    toggleShortcuts: () => ctx.toggleShortcuts(),

    cycleConnections: (backwards) => cycleConnections(ctx, backwards),

    walking: () => ctx.walking(),
    review: () => ctx.review(),
    walkStep: (delta) => ctx.walkStep(delta),
    walkQuote: (delta) => ctx.walkQuote(delta),
    walkNotObserved: (backwards) => ctx.walkJump('notObserved', backwards),
    walkFindings: (backwards) => ctx.walkJump('findings', backwards),
    walkOtherEnd: () => ctx.walkOtherEnd(),
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
  ctx.setEdgeAnchor(anchor); // set again, whatever `select` did (it keeps it only for an edge)
  // Focusing never scrolls the canvas, so the connection's end at the step is panned in.
  ctx.view().revealRouteEnd(next, anchor);
  ctx.view().focusEdge(next.id);
  // Announced only for KEYBOARD-driven flows: narrating every mouse sweep into
  // the live region is the aural equivalent of strobing.
  ctx.announce(ctx.view().edgeAnnouncement(next));
  return true;
}
