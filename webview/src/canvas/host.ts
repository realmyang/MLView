/**
 * What the canvas is allowed to ask of the application, and the timings the
 * surface hangs off.
 *
 * It lives beside `canvasview.ts` rather than inside it so that the contract
 * between the two halves of the viewer — the App owns chrome, rail, filters and
 * the host protocol; `CanvasView` owns everything inside the diagram surface —
 * can be read on its own, and so that the modules the canvas is built from
 * (`wiring.ts`, `emphasis.ts`) can name it without importing the class that
 * implements it.
 */

import type { Issue, Viewport } from '../types.js';

/** How long a click on a collapsible box waits for a possible second click. */
export const DOUBLE_CLICK_MS = 220;

/**
 * Hover-card timing: the open delay and the close delay. Without them one sweep
 * of the pointer across the diagram would pop and drop a card, and dim every
 * unrelated node again, once for each card it passes over. The close delay is
 * what stops two adjacent cards from strobing as the pointer crosses the gap
 * between them.
 */
export const HOVER_OPEN_MS = 400;
export const HOVER_CLOSE_MS = 120;

/**
 * The phase index is a panel of rows when the panel is this wide or wider, and a pill
 * below it, as in a panel beside the code.
 */
export const PHASE_INDEX_LIST_MIN_W = 1000;

/**
 * Below this canvas height the phase index is its pill whatever the width: a panel of rows
 * over a short canvas would cover much of the diagram it summarises.
 */
export const PHASE_INDEX_LIST_MIN_H = 350;

export interface CanvasHost {
  /** The App's finding filter — a marker is drawn only for findings this keeps. */
  keep(issue: Issue): boolean;
  /**
   * A node card was clicked: select it and show its claim (a click never opens the source).
   * `ev` is the pointer click, so its second click of a double-click can open it.
   */
  activateNode(id: string, ev?: MouseEvent): void;
  /** A connection was clicked: select it and show its claim. */
  activateEdge(id: string, ev?: MouseEvent): void;
  /**
   * Enter or a double-click on a card: select it and open its cited source beside the panel,
   * keeping focus on the diagram; `focusEditor` (Alt+Enter) moves focus to the editor instead.
   */
  openNode(id: string, focusEditor: boolean): void;
  /** The same for a connection. */
  openEdge(id: string, focusEditor: boolean): void;
  /** The "clear all filters" affordance of the filtered-empty state. */
  clearFilters(): void;
  announce(text: string): void;
  /** After a collapse/expand: the App re-applies selection, rail and state. */
  afterCollapse(): void;
  onViewportChange(vp: Viewport): void;
  /** The phase index was folded or unfolded; the App saves it and repaints the menu. */
  onPhaseIndexChanged(): void;
  onKeyDown(ev: KeyboardEvent): void;
  onBackgroundClick(): void;
  /** The node or connection the current selection points at, kept in view across a resize. */
  keptTarget(): { kind: 'node' | 'edge'; id: string } | null;
  /** A cap of a far connection was clicked (`ev`): look at that end of the walk's connection. */
  onFarCap(end: 'source' | 'target', ev: MouseEvent): void;
  /** The pointer is on a cap, or left it: the walk bar's line answers. */
  onFarCue(on: boolean): void;
  /**
   * The phase index changed shape, or the lit line changed colour, with no change of
   * viewport: the caps are drawn again.
   */
  onFarStale(): void;
}

export interface NextSelection {
  id: string;
  /** False when the box is (partly) outside the viewport and needs centring. */
  visible: boolean;
}
