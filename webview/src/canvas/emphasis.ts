/**
 * The TRANSIENT states of the diagram surface: selection, hover, the lineage
 * trace and focus mode.
 *
 * Layout depends only on (graph, collapsed), so none of this moves a box: every
 * state here is a class toggle over the scene DOM the canvas last rendered, plus
 * the flow the state owns. Keeping it out of `canvasview.ts` keeps the four
 * pieces of mutable UI state that are NOT geometry — which node the pointer
 * settled on, the pending hover timer, whether focus mode is latched and on
 * what — in one object that owns all four together.
 *
 * `CanvasView` delegates `applySelection`, `hoverIntent`, `setHover` and
 * `toggleFocusMode` here unchanged, and the flow binding reads the hovered and
 * latched node ids off this object.
 */

import { clear } from '../dom.js';
import { applyTrace } from '../render/trace.js';
import { drawIssueConnectors } from '../render/connectors.js';
import { HOVER_CLOSE_MS, HOVER_OPEN_MS } from './host.js';
import type { FlowBinding } from '../render/flowbinding.js';
import type { Tooltip } from '../render/tooltip.js';
import type { GraphIndex } from '../layout/model.js';
import type { LayoutFrame } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { Issue, Sel } from '../types.js';

/**
 * Everything the transient states reach. The scene DOM is read through
 * functions because `render()` REPLACES the maps, the routes and the frame
 * wholesale; the canvas element, the connector layer, the tooltip and the flow
 * binding are the same objects for the life of the view.
 */
export interface EmphasisContext {
  readonly canvas: HTMLElement;
  readonly connectors: SVGElement;
  readonly flow: FlowBinding;
  readonly tooltip: Tooltip;
  nodeEls(): Map<string, HTMLElement>;
  edgeEls(): Map<string, SVGElement>;
  routes(): RoutedEdge[];
  index(): GraphIndex | null;
  frame(): LayoutFrame | null;
  collapsed(): Set<string>;
  syncBundles(): void;
  keep(issue: Issue): boolean;
  announce(text: string): void;
  toast(text: string): void;
}

export class Emphasis {
  private ctx: EmphasisContext;
  private hoverId: string | null = null;
  private hoverTimer: ReturnType<typeof setTimeout> | null = null;
  /** The target the pending `hoverTimer` will apply. */
  private pendingHover: string | null = null;
  private focusLocked = false;
  /** The node whose lineage stream is latched by focus mode (row 7). */
  private focusNodeId: string | null = null;
  /** The card that carries the focused lineage: the node, or its collapsed group. */
  private focusShown: string | null = null;

  constructor(ctx: EmphasisContext) {
    this.ctx = ctx;
  }

  /** The node the pointer has settled on, or null — a flow trigger (row 3). */
  get hoverNodeId(): string | null {
    return this.hoverId;
  }

  /** The node focus mode has latched, or null when it is off (row 7). */
  get lockedNodeId(): string | null {
    return this.focusLocked ? this.focusShown ?? this.focusNodeId : null;
  }

  get isFocusLocked(): boolean {
    return this.focusLocked;
  }

  /**
   * The scene DOM was replaced, so no hover survives it. Without this the latch
   * cascade in `flow.stop()` would resume a stream over a scene that no longer
   * holds that node (CONTRACTS 11.14 C1).
   *
   * RENDER-1: the hover's VISIBLE state goes too. `is-tracing` sits on the
   * persistent canvas element, so leaving it there dims every card of the new
   * scene (with `pointer-events: none`) and nothing could clear it; the tooltip
   * of a node from the old scene is hidden; a pending hover timer is dropped;
   * and focus mode is re-lit from its own node (or unlocks when the new scene
   * has no card for it), because the new cards arrive without `is-lit`.
   */
  resetHover(): void {
    if (this.hoverTimer !== null) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
    }
    this.pendingHover = null;
    this.hoverId = null;
    this.trace(null, 'is-tracing');
    this.ctx.tooltip.hide();
    this.retraceFocus();
  }

  /**
   * Light focus mode from `focusNodeId`, never from the selection: a
   * background click clears the selection, and a re-render drops every lit
   * class. The lineage is traced from the node's visible representative (its
   * collapsed group when it is inside one). When the scene has no card for it
   * (removed, filtered out, scoped away), focus mode unlocks instead of leaving
   * every card dimmed and unclickable.
   */
  private retraceFocus(): void {
    if (!this.focusLocked || !this.focusNodeId) return;
    const ctx = this.ctx;
    const index = ctx.index();
    const shown = index && index.nodeById.has(this.focusNodeId) ? index.visibleRepresentative(this.focusNodeId, ctx.collapsed()) : null;
    if (shown && ctx.nodeEls().has(shown)) {
      this.focusShown = shown;
      ctx.canvas.classList.remove('is-tracing');
      this.trace(shown, 'is-focusing');
      return;
    }
    this.focusLocked = false;
    this.focusNodeId = null;
    this.focusShown = null;
    ctx.canvas.classList.remove('is-focusing');
    this.trace(null, 'is-focusing');
    ctx.announce('Focus mode off.');
  }

  applySelection(sel: Sel | null): void {
    const ctx = this.ctx;
    for (const element of ctx.nodeEls().values()) element.classList.remove('is-selected');
    for (const element of ctx.edgeEls().values()) element.classList.remove('is-selected');
    clear(ctx.connectors);
    // Clicking a CARD produces no flow: a pulse on every click makes ordinary
    // navigation twitch (interaction table row 8). Selecting an EDGE latches one.
    ctx.flow.setLatchedEdge(sel && sel.kind === 'edge' ? sel.id : null);
    if (!sel) {
      ctx.canvas.removeAttribute('aria-activedescendant');
      // Deselecting (a background click) leaves focus mode latched on its node.
      this.retraceFocus();
      ctx.syncBundles();
      ctx.flow.stop();
      return;
    }
    if (sel.kind === 'node') {
      const element = ctx.nodeEls().get(sel.id);
      if (element) {
        element.classList.add('is-selected');
        ctx.canvas.setAttribute('aria-activedescendant', element.id);
      }
    } else if (sel.kind === 'edge') {
      const element = ctx.edgeEls().get(sel.id);
      if (element) element.classList.add('is-selected');
    } else if (sel.kind === 'issue') {
      this.highlightIssue(sel.id);
    }
    // Focus follows a newly selected node (through its collapsed group when
    // needed); an edge or finding selection shows the whole diagram, as before.
    if (this.focusLocked && sel.kind === 'node') {
      this.focusNodeId = sel.id;
      this.retraceFocus();
    }
    else if (this.focusLocked) this.trace(null, 'is-focusing');
    ctx.syncBundles();
    ctx.flow.stop();
  }

  private highlightIssue(issueId: string): void {
    const ctx = this.ctx;
    const index = ctx.index();
    const frame = ctx.frame();
    if (!index || !frame) return;
    const issue = index.issueById.get(issueId);
    if (!issue) return;
    const primary = issue.nodeIds[0];
    if (primary) {
      const element = ctx.nodeEls().get(index.visibleRepresentative(primary, ctx.collapsed()));
      if (element) {
        element.classList.add('is-selected');
        ctx.canvas.setAttribute('aria-activedescendant', element.id);
      }
    }
    for (const edgeId of issue.edgeIds) {
      for (const [id, element] of ctx.edgeEls()) {
        const ids = (element.getAttribute('data-edge-ids') || id).split(' ');
        if (ids.indexOf(edgeId) >= 0) element.classList.add('is-selected');
      }
    }
    drawIssueConnectors(ctx.connectors, index, frame, ctx.collapsed(), issue);
  }

  /**
   * Debounced hover. One timer for both directions: entering a neighbouring card
   * cancels the pending hide, and leaving cancels the pending show, so crossing
   * the diagram costs nothing until the pointer actually settles.
   */
  hoverIntent(id: string | null): void {
    if (this.hoverTimer !== null) {
      // Already on the way to this target: keep the timer that is running.
      if (this.pendingHover === id) return;
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
      this.pendingHover = null;
    }
    if (this.hoverId === id) return;
    // RENDER-19: the intent delays are not animation, so reduced motion keeps
    // them. Without them every card a pointer sweep crosses toggles the
    // whole-canvas dim; only the CSS transitions are removed (base.css).
    const delay = id ? HOVER_OPEN_MS : HOVER_CLOSE_MS;
    if (delay <= 0) {
      this.setHover(id);
      return;
    }
    this.pendingHover = id;
    this.hoverTimer = setTimeout(() => {
      this.hoverTimer = null;
      this.pendingHover = null;
      this.setHover(id);
    }, delay);
  }

  setHover(id: string | null): void {
    if (this.hoverId === id) return;
    this.hoverId = id;
    if (this.focusLocked) return;
    const ctx = this.ctx;
    if (!id) {
      this.trace(null, 'is-tracing');
      ctx.tooltip.hide();
      ctx.flow.stop();
      return;
    }
    this.trace(id, 'is-tracing');
    // Upstream edges flow inward and downstream outward with no reversal logic:
    // every route's points already run source -> target (FEATURES 2.2).
    ctx.flow.stream(id);
    // A charge on a cable inside a collapsed trunk would be a charge on an
    // invisible cable, so the trunk opens with the stream (VIEW-04).
    ctx.syncBundles();
    const index = ctx.index();
    const frame = ctx.frame();
    if (!index || !frame) return;
    const box = frame.boxes.get(id);
    if (box) ctx.tooltip.showNode(index, id, box, (issue) => ctx.keep(issue));
  }

  /** Lineage highlight: upstream + downstream over the routed edges. */
  private trace(id: string | null, cls: string): void {
    const ctx = this.ctx;
    applyTrace({ nodes: ctx.nodeEls(), edges: ctx.edgeEls(), canvas: ctx.canvas }, ctx.routes(), id, cls);
    ctx.syncBundles();
  }

  toggleFocusMode(sel: Sel | null): void {
    const ctx = this.ctx;
    if (this.focusLocked) {
      this.focusLocked = false;
      this.focusNodeId = null;
      this.focusShown = null;
      ctx.canvas.classList.remove('is-focusing');
      this.trace(null, 'is-focusing');
      ctx.flow.clear();
      ctx.announce('Focus mode off.');
      return;
    }
    if (!sel || sel.kind !== 'node') {
      ctx.toast('Select a node first, then press F to focus.');
      return;
    }
    this.focusLocked = true;
    this.focusNodeId = sel.id;
    this.retraceFocus();
    if (!this.focusLocked) return;
    // The same stream, latched, so a pipeline can be read at leisure (row 7).
    ctx.flow.stream(this.focusShown ?? sel.id);
    ctx.announce('Focus mode on.');
  }

  destroy(): void {
    if (this.hoverTimer === null) return;
    clearTimeout(this.hoverTimer);
    this.hoverTimer = null;
    this.pendingHover = null;
  }
}
