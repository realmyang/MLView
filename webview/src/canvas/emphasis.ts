/**
 * The TRANSIENT states of the diagram surface: selection, hover, the hover
 * highlight and focus mode.
 *
 * Hover and focus mode light different reaches (`render/trace.ts`). A settled
 * hover on a card lights only its DIRECT connections — the routes whose source
 * or target is the card, and the cards at their other ends — and streams along
 * exactly those routes. Focus mode (`f` on a selected node) lights and streams
 * the node's full upstream + downstream lineage.
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
import type { TraceReach } from '../render/trace.js';
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
   * scene and nothing could clear it; the tooltip of a node from the old scene
   * is hidden; a pending hover timer is dropped; and focus mode is re-lit from
   * its own node (or unlocks when the new scene has no card for it), because
   * the new cards arrive without `is-lit`.
   */
  resetHover(): void {
    if (this.hoverTimer !== null) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
    }
    this.pendingHover = null;
    this.hoverId = null;
    this.trace(null, 'is-tracing', 'direct');
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
      this.trace(shown, 'is-focusing', 'lineage');
      return;
    }
    this.focusLocked = false;
    this.focusNodeId = null;
    this.focusShown = null;
    ctx.canvas.classList.remove('is-focusing');
    this.trace(null, 'is-focusing', 'lineage');
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
      ctx.flow.stop();
      // After the stop, so the trunks follow the flow it left running (VIEW-04).
      ctx.syncBundles();
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
    else if (this.focusLocked) this.trace(null, 'is-focusing', 'lineage');
    ctx.flow.stop();
    // After the stop: syncing first left a trunk the replaced stream had opened
    // expanded with nothing lit or flowing on it (VIEW-04).
    ctx.syncBundles();
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
      this.trace(null, 'is-tracing', 'direct');
      ctx.tooltip.hide();
      ctx.flow.stop();
      // The trace's sync ran while the stream still marked its cables
      // `.is-flowing`; sync again now the stream is gone, or a trunk the hover
      // opened stays open after the pointer leaves (VIEW-04).
      ctx.syncBundles();
      return;
    }
    // A hover lights only the card's direct connections (routed, so a collapsed
    // group stands in for what it hides); the full lineage is focus mode's job.
    this.trace(id, 'is-tracing', 'direct');
    // The stream runs along the same direct routes the trace lit. Incoming edges
    // flow inward and outgoing outward with no reversal logic: every route's
    // points already run source -> target (FEATURES 2.2).
    ctx.flow.stream(id, 'direct');
    // A charge on a cable inside a collapsed trunk would be a charge on an
    // invisible cable, so the trunk opens with the stream (VIEW-04).
    ctx.syncBundles();
    const index = ctx.index();
    const frame = ctx.frame();
    if (!index || !frame) return;
    const box = frame.boxes.get(id);
    if (box) ctx.tooltip.showNode(index, id, box, (issue) => ctx.keep(issue));
  }

  /**
   * Light what `id` reaches over the routed edges — its direct connections for
   * a hover, its upstream + downstream lineage for focus mode — and open the
   * bundles whose members that lit (VIEW-04).
   */
  private trace(id: string | null, cls: string, reach: TraceReach): void {
    const ctx = this.ctx;
    applyTrace({ nodes: ctx.nodeEls(), edges: ctx.edgeEls(), canvas: ctx.canvas }, ctx.routes(), id, cls, reach);
    ctx.syncBundles();
  }

  toggleFocusMode(sel: Sel | null): void {
    const ctx = this.ctx;
    if (this.focusLocked) {
      this.focusLocked = false;
      this.focusNodeId = null;
      this.focusShown = null;
      ctx.canvas.classList.remove('is-focusing');
      this.trace(null, 'is-focusing', 'lineage');
      ctx.flow.clear();
      ctx.syncBundles(); // the stream is gone, so its trunks fold again (VIEW-04)
      ctx.announce('Focus mode off.');
      // The card still under the pointer gets its hover back, lit and streaming,
      // so the stop cascade's hover rung never streams cables nothing lit.
      const hovered = this.hoverId;
      if (hovered) {
        this.hoverId = null;
        this.setHover(hovered);
      }
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
    // The full lineage stream, latched, so a pipeline can be read at leisure (row 7).
    ctx.flow.stream(this.focusShown ?? sel.id, 'lineage');
    ctx.announce('Focus mode on.');
  }

  destroy(): void {
    if (this.hoverTimer === null) return;
    clearTimeout(this.hoverTimer);
    this.hoverTimer = null;
    this.pendingHover = null;
  }
}
