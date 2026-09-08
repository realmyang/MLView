/**
 * The canvas view — everything inside the diagram surface.
 *
 * It owns the layout frame, the routed edges, the scene DOM, the viewport, the
 * minimap, the tooltip and the transient states (hover, focus mode, collapse).
 * The App owns the chrome, the rail, the filters and the host protocol, and
 * drives this class through the `CanvasHost` callbacks.
 *
 * Layout depends only on (graph, collapsed). Selection, hover, focus and the
 * lineage trace are pure class toggles here, so they never trigger a re-render.
 */

import { clear, on } from './dom.js';
import { GraphIndex } from './layout/model.js';
import { layoutGraph, LayoutFrame } from './layout/layout.js';
import { routeEdges, RoutedEdge } from './layout/routing.js';
import { firstBox, nextBox } from './layout/navigate.js';
import { minimapDots, renderScene } from './render/scene.js';
import { nextMountSerial } from './render/edges.js';
import { Minimap, ViewportController } from './render/canvas.js';
import { applyTrace } from './render/trace.js';
import { FlowBinding } from './render/flowbinding.js';
import { EdgeHover } from './render/edgehover.js';
import { Tooltip } from './render/tooltip.js';
import { drawIssueConnectors } from './render/connectors.js';
import { Toasts, buildEmptyState, buildFilterEmptyState, buildScopeEmptyState } from './ui/states.js';
import { wireCanvasGestures } from './ui/shell.js';
import { prefersReducedMotion } from './motion.js';
import type { Shell } from './ui/shell.js';
import type { Issue, MLNode, Sel, Viewport } from './types.js';

/** How long a click on a collapsible box waits for a possible second click. */
const DOUBLE_CLICK_MS = 220;

/**
 * Hover-card timing (UX_DESIGN §9: "180 ms; 400 ms open delay, 120 ms close
 * delay"). Without them a single sweep of the pointer across the diagram popped
 * and dropped a card — and re-dimmed every unrelated node — once per card it
 * passed over (MLV-R2-W04). The close delay is what stops two adjacent cards
 * from strobing as the pointer crosses the gap between them.
 */
export const HOVER_OPEN_MS = 400;
export const HOVER_CLOSE_MS = 120;

/** The graph size at which an overview earns the corner it occupies (UX_DESIGN §1). */
const MINIMAP_MIN_NODES = 30;

export interface CanvasHost {
  /** The App's issue filter — a marker is drawn only for issues this keeps. */
  keep(issue: Issue): boolean;
  /** True when the stage filters exclude this node (dimmed, not removed). */
  isFilteredOut(node: MLNode): boolean;
  /** A node card was clicked or activated with Enter. */
  activateNode(id: string): void;
  /** An edge was clicked or activated with Enter. */
  activateEdge(id: string): void;
  /** The "clear all filters" affordance of the filtered-empty state. */
  clearFilters(): void;
  canReanalyze(): boolean;
  requestRefresh(): void;
  announce(text: string): void;
  /** After a collapse/expand: the App re-applies selection, rail and state. */
  afterCollapse(): void;
  onViewportChange(vp: Viewport): void;
  /** The minimap was collapsed or expanded; the App persists the flag. */
  onMinimapCollapsed(collapsed: boolean): void;
  onKeyDown(ev: KeyboardEvent): void;
  onBackgroundClick(): void;
  /** The empty scope's two ways out (FEATURES 3.7). */
  widenScope(): void;
  clearScope(): void;
  /** The active scope's selector, or null — drives the scope-empty state. */
  scopeSpec(): string | null;
}

export interface NextSelection {
  id: string;
  /** False when the box is (partly) outside the viewport and needs centring. */
  visible: boolean;
}

export class CanvasView {
  readonly canvasEl: HTMLElement;
  readonly viewport: ViewportController;
  readonly toasts: Toasts;

  private worldEl: HTMLElement;
  private lanesLayer: HTMLElement;
  private edgesSvg: SVGElement;
  private edgeGroup: SVGElement;
  private connectorLayer: SVGElement;
  private nodesLayer: HTMLElement;
  private zoomLevelEl: HTMLElement;
  private stateHost: HTMLElement;
  private tooltip: Tooltip;
  private minimap: Minimap;

  private host: CanvasHost;
  private index: GraphIndex | null = null;
  private frameData: LayoutFrame | null = null;
  private routes: RoutedEdge[] = [];
  private collapsedSet = new Set<string>();
  private staleFiles: string[] = [];
  private hoverId: string | null = null;
  private hoverTimer: ReturnType<typeof setTimeout> | null = null;
  private focusLocked = false;
  private nodeEls = new Map<string, HTMLElement>();
  private edgeEls = new Map<string, SVGElement>();
  /**
   * This view's identity inside the DOCUMENT. It qualifies every edge path id,
   * so two apps on one page (dev/states.html, or two reports in one host) can
   * never share the motion path a charge rides (CONTRACTS 11.13.1).
   */
  private readonly mountSerial = nextMountSerial();
  private disposers: (() => void)[] = [];
  /** WHEN a charge runs, and the latch cascade that keeps it running. */
  readonly flow: FlowBinding;
  /** The node whose lineage stream is latched by focus mode (row 7). */
  private focusNodeId: string | null = null;
  /** Which cable the pointer owns, and the delay before that means anything. */
  private edgeHover: EdgeHover;

  constructor(shell: Shell, host: CanvasHost) {
    this.host = host;
    this.canvasEl = shell.canvas;
    this.worldEl = shell.world;
    this.lanesLayer = shell.lanesLayer;
    this.edgesSvg = shell.edgesSvg;
    this.edgeGroup = shell.edgeGroup;
    this.connectorLayer = shell.connectorLayer;
    this.nodesLayer = shell.nodesLayer;
    this.zoomLevelEl = shell.zoomLevel;
    this.stateHost = shell.stateHost;

    this.tooltip = new Tooltip(
      () => this.viewport.vp,
      () => this.viewport.size(),
    );
    this.canvasEl.appendChild(this.tooltip.root);

    this.minimap = new Minimap(
      (x, y) => {
        const size = this.viewport.size();
        this.viewport.set({ x: size.w / 2 - x * this.viewport.vp.zoom, y: size.h / 2 - y * this.viewport.vp.zoom });
      },
      (collapsed) => this.host.onMinimapCollapsed(collapsed),
    );
    this.canvasEl.appendChild(this.minimap.root);

    this.toasts = new Toasts();
    this.canvasEl.appendChild(this.toasts.root);

    this.viewport = new ViewportController(this.canvasEl, this.worldEl, (vp) => {
      this.zoomLevelEl.textContent = Math.round(vp.zoom * 100) + '%';
      const size = this.viewport.size();
      this.minimap.setViewport(vp, size.w, size.h);
      this.host.onViewportChange(vp);
    });

    for (const dispose of wireCanvasGestures(this.canvasEl, this.viewport, {
      onKeyDown: (ev) => this.host.onKeyDown(ev),
      onBackgroundClick: () => this.host.onBackgroundClick(),
    })) {
      this.disposers.push(dispose);
    }

    this.flow = new FlowBinding({
      canvas: this.canvasEl,
      edges: () => this.edgeEls,
      nodes: () => this.nodeEls,
      routes: () => this.routes,
      index: () => this.index,
      hoverNodeId: () => this.hoverId,
      lockedNodeId: () => (this.focusLocked ? this.focusNodeId : null),
      hoverEdgeId: () => this.edgeHover.hoveredId,
      toast: (text) => this.toasts.show(text),
    });

    // Which cable the pointer owns is decided by geometry, not by document
    // order (`render/edgehover.ts`). Nothing is built before the pointer
    // settles, so a sweep across the diagram still allocates nothing.
    this.edgeHover = new EdgeHover({
      canvas: this.canvasEl,
      viewport: this.viewport,
      routes: () => this.routes,
      edges: () => this.edgeEls,
      open: (route) => {
        if (!this.index) return;
        this.tooltip.showEdge(this.index, route);
        this.flow.pulse(route);
      },
      close: () => {
        if (!this.hoverId) this.tooltip.hide();
        this.flow.stop();
      },
      openDelayMs: HOVER_OPEN_MS,
      closeDelayMs: HOVER_CLOSE_MS,
    });
    this.disposers.push(this.edgeHover.wire());
  }

  /* ── data ──────────────────────────────────────────────────────────── */

  get frame(): LayoutFrame | null {
    return this.frameData;
  }

  get collapsed(): Set<string> {
    return this.collapsedSet;
  }

  setIndex(index: GraphIndex | null): void {
    this.index = index;
  }

  setCollapsed(ids: string[]): void {
    this.collapsedSet = new Set(ids);
  }

  get minimapCollapsed(): boolean {
    return this.minimap.collapsed;
  }

  setMinimapCollapsed(collapsed: boolean): void {
    this.minimap.setCollapsed(collapsed);
  }

  setStale(files: string[]): void {
    this.staleFiles = files;
  }

  nodeElement(id: string): HTMLElement | undefined {
    return this.nodeEls.get(id);
  }

  /** Re-run layout + routing. The only thing that moves boxes. */
  relayout(): void {
    if (!this.index) return;
    this.frameData = layoutGraph(this.index, this.collapsedSet);
    this.routes = routeEdges(this.index, this.frameData, this.collapsedSet);
    this.viewport.setContent(this.frameData.width, this.frameData.height);
    // A SCOPE is small by construction, so the "fit the width and let them pan
    // down" rule written for a whole workspace does not apply to it: it opened a
    // report scoped to evaluation with the evaluation lane below the fold
    // (MLV-R3-001).
    this.viewport.setProjected(!!this.index.graph.view);
    this.render();
  }

  /** Rebuild the scene DOM from the current frame. Never moves boxes. */
  render(): void {
    if (!this.index || !this.frameData) return;
    const scene = renderScene(
      {
        world: this.worldEl,
        lanes: this.lanesLayer,
        edgesSvg: this.edgesSvg,
        edgeGroup: this.edgeGroup,
        connectors: this.connectorLayer,
        nodes: this.nodesLayer,
      },
      {
        index: this.index,
        frame: this.frameData,
        routes: this.routes,
        mountSerial: this.mountSerial,
        keep: (issue) => this.host.keep(issue),
        staleFiles: this.staleFiles,
        isFilteredOut: (node) => this.host.isFilteredOut(node),
        wireNode: (element, id, isGroup) => this.wireNode(element, id, isGroup),
        wireEdge: (element, route) => this.wireEdge(element, route),
      },
    );
    this.nodeEls = scene.nodeEls;
    this.edgeEls = scene.edgeEls;
    // Every card and cable the pointer was over went with the old DOM, so no
    // hover survives a rebuild. Without this the latch cascade in `flow.stop()`
    // would resume a stream over a scene that no longer holds that node
    // (CONTRACTS 11.14 C1).
    this.hoverId = null;
    this.edgeHover.reset();
    // The scene DOM was replaced, so every flow element went with it. Reset the
    // controller's memory and re-stamp the canvas (CONTRACTS 11.14 C1); a
    // latched pulse is re-applied by the applySelection that follows.
    this.flow.clear();
    this.renderMinimap();
    this.renderEmptyState();
  }

  private renderMinimap(): void {
    if (!this.index || !this.frameData) return;
    const dots = minimapDots(this.index, this.frameData, (issue) => this.host.keep(issue));
    this.minimap.render(dots, this.frameData.width, this.frameData.height);
    this.minimap.root.hidden = dots.length < MINIMAP_MIN_NODES;
  }

  private renderEmptyState(): void {
    const existing = this.stateHost.querySelector('.mlv-state--empty');
    if (existing) this.stateHost.removeChild(existing);
    if (!this.index) return;
    const graph = this.index.graph;
    if (graph.nodes.length === 0) {
      // "Nothing analyzed" and "nothing in this scope" are different findings.
      const scoped = this.scopeEmptyState();
      this.stateHost.appendChild(
        scoped || buildEmptyState(graph, this.host.canReanalyze() ? () => this.host.requestRefresh() : null),
      );
    } else if (this.frameData && this.frameData.boxes.size === 0) {
      this.stateHost.appendChild(buildFilterEmptyState(() => this.host.clearFilters()));
    }
  }

  /** The scope resolved to nothing: its OWN state, not the filter-empty one. */
  private scopeEmptyState(): HTMLElement | null {
    const spec = this.host.scopeSpec();
    if (!spec || !this.index) return null;
    if ((this.index.graph.nodes || []).length > 0) return null;
    return buildScopeEmptyState(spec, () => this.host.widenScope(), () => this.host.clearScope());
  }

  /* ── event wiring ──────────────────────────────────────────────────── */

  private wireNode(element: HTMLElement, id: string, isGroup: boolean): void {
    const target: HTMLElement = isGroup ? (element.querySelector('.mlv-group__header') as HTMLElement) : element;
    if (!target) return;

    // The chevron owns the collapse gesture outright (UX_DESIGN §2.4).
    const chevron = element.querySelector('.mlv-group__chevron-btn') as HTMLElement | null;
    if (chevron) {
      on(chevron, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (this.index && this.index.isGroup(id)) this.toggleCollapse(id);
      });
      on(chevron, 'dblclick', (ev: MouseEvent) => {
        ev.preventDefault();
        ev.stopPropagation();
      });
    }

    // A double-click emits click, click, dblclick. Anything that also answers a
    // double-click must therefore hold its single-click back long enough to see
    // the second one, or collapsing a group opens its file twice (MLV-R1-010).
    const collapsible = isGroup || (this.index ? this.index.isGroup(id) : false);
    let pending: ReturnType<typeof setTimeout> | null = null;
    const cancelPending = () => {
      if (pending === null) return;
      clearTimeout(pending);
      pending = null;
    };
    this.disposers.push(cancelPending);

    on(target, 'click', (ev: MouseEvent) => {
      ev.stopPropagation();
      if (!collapsible) {
        this.host.activateNode(id);
        return;
      }
      cancelPending();
      pending = setTimeout(() => {
        pending = null;
        this.host.activateNode(id);
      }, DOUBLE_CLICK_MS);
    });
    on(target, 'dblclick', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      cancelPending();
      if (this.index && this.index.isGroup(id)) this.toggleCollapse(id);
    });
    on(target, 'pointerenter', () => this.hoverIntent(id));
    on(target, 'pointerleave', () => this.hoverIntent(null));
    on(target, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        this.host.activateNode(id);
      } else if (ev.key === ' ' && this.index && this.index.isGroup(id)) {
        ev.preventDefault();
        this.toggleCollapse(id);
      }
    });
  }

  private wireEdge(g: SVGElement, route: RoutedEdge): void {
    const hit = g.querySelector('.mlv-edge__hit') as SVGElement | null;
    if (!hit) return;
    const element = hit as unknown as HTMLElement;
    on(element, 'click', (ev: MouseEvent) => {
      ev.stopPropagation();
      this.host.activateEdge(route.id);
    });
    on(element, 'pointerenter', () => this.edgeHover.enter(route));
    on(element, 'pointerleave', () => this.edgeHover.leave(route));
    on(element, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key !== 'Enter') return;
      ev.preventDefault();
      this.host.activateEdge(route.id);
    });
    // A connection was unreachable from the keyboard before this (FEATURES 2.2):
    // `e` / `Shift+E` focus the hit path, and focus alone runs the charge.
    on(element, 'focus', () => {
      g.classList.add('is-hover');
      this.flow.pulse(route);
    });
    on(element, 'blur', () => {
      g.classList.remove('is-hover');
      this.flow.stop();
    });
  }

  /* ── flow ──────────────────────────────────────────────── */

  /** Every route incident to `id` IN THE CURRENT PROJECTION (11.14 C4). */
  incidentRoutes(id: string): RoutedEdge[] {
    return this.flow.incidentRoutes(id);
  }

  /** Move the DOM focus onto a connection's hit path. */
  focusEdge(id: string): boolean {
    return this.flow.focusEdge(id);
  }

  /** Take focus off a connection, so `.is-hover` and the flow clear together. */
  blurFocusedEdge(): boolean {
    return this.flow.blurFocusedEdge();
  }

  /** "Connection: A to B, label" — what the live region says on `e`. */
  edgeAnnouncement(route: RoutedEdge): string {
    return this.flow.edgeAnnouncement(route);
  }

  /* ── selection, hover, focus ───────────────────────────────────────── */

  applySelection(sel: Sel | null): void {
    for (const element of this.nodeEls.values()) element.classList.remove('is-selected');
    for (const element of this.edgeEls.values()) element.classList.remove('is-selected');
    clear(this.connectorLayer);
    // Clicking a CARD produces no flow: a pulse on every click makes ordinary
    // navigation twitch (interaction table row 8). Selecting an EDGE latches one.
    this.flow.setLatchedEdge(sel && sel.kind === 'edge' ? sel.id : null);
    if (!sel) {
      this.canvasEl.removeAttribute('aria-activedescendant');
      this.flow.stop();
      return;
    }
    if (sel.kind === 'node') {
      const element = this.nodeEls.get(sel.id);
      if (element) {
        element.classList.add('is-selected');
        this.canvasEl.setAttribute('aria-activedescendant', element.id);
      }
    } else if (sel.kind === 'edge') {
      const element = this.edgeEls.get(sel.id);
      if (element) element.classList.add('is-selected');
    } else if (sel.kind === 'issue') {
      this.highlightIssue(sel.id);
    }
    if (this.focusLocked) this.applyTrace(sel.kind === 'node' ? sel.id : null, 'is-focusing');
    this.flow.stop();
  }

  private highlightIssue(issueId: string): void {
    if (!this.index || !this.frameData) return;
    const issue = this.index.issueById.get(issueId);
    if (!issue) return;
    const primary = issue.nodeIds[0];
    if (primary) {
      const element = this.nodeEls.get(this.index.visibleRepresentative(primary, this.collapsedSet));
      if (element) {
        element.classList.add('is-selected');
        this.canvasEl.setAttribute('aria-activedescendant', element.id);
      }
    }
    for (const edgeId of issue.edgeIds) {
      for (const [id, element] of this.edgeEls) {
        const ids = (element.getAttribute('data-edge-ids') || id).split(' ');
        if (ids.indexOf(edgeId) >= 0) element.classList.add('is-selected');
      }
    }
    drawIssueConnectors(this.connectorLayer, this.index, this.frameData, this.collapsedSet, issue);
  }

  /**
   * Debounced hover. One timer for both directions: entering a neighbouring card
   * cancels the pending hide, and leaving cancels the pending show, so crossing
   * the diagram costs nothing until the pointer actually settles.
   */
  hoverIntent(id: string | null): void {
    if (this.hoverTimer !== null) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
    }
    if (this.hoverId === id) return;
    const delay = prefersReducedMotion() ? 0 : id ? HOVER_OPEN_MS : HOVER_CLOSE_MS;
    if (delay <= 0) {
      this.setHover(id);
      return;
    }
    this.hoverTimer = setTimeout(() => {
      this.hoverTimer = null;
      this.setHover(id);
    }, delay);
  }

  setHover(id: string | null): void {
    if (this.hoverId === id) return;
    this.hoverId = id;
    if (this.focusLocked) return;
    if (!id) {
      this.applyTrace(null, 'is-tracing');
      this.tooltip.hide();
      this.flow.stop();
      return;
    }
    this.applyTrace(id, 'is-tracing');
    // Upstream edges flow inward and downstream outward with no reversal logic:
    // every route's points already run source -> target (FEATURES 2.2).
    this.flow.stream(id);
    if (!this.index || !this.frameData) return;
    const box = this.frameData.boxes.get(id);
    if (box) this.tooltip.showNode(this.index, id, box, (issue) => this.host.keep(issue));
  }

  /** Lineage highlight: upstream + downstream over the routed edges. */
  private applyTrace(id: string | null, cls: string): void {
    applyTrace({ nodes: this.nodeEls, edges: this.edgeEls, canvas: this.canvasEl }, this.routes, id, cls);
  }

  get isFocusLocked(): boolean {
    return this.focusLocked;
  }

  toggleFocusMode(sel: Sel | null): void {
    if (this.focusLocked) {
      this.focusLocked = false;
      this.focusNodeId = null;
      this.canvasEl.classList.remove('is-focusing');
      this.applyTrace(null, 'is-focusing');
      this.flow.clear();
      this.host.announce('Focus mode off.');
      return;
    }
    if (!sel || sel.kind !== 'node') {
      this.toasts.show('Select a node first, then press F to focus.');
      return;
    }
    this.focusLocked = true;
    this.focusNodeId = sel.id;
    this.canvasEl.classList.remove('is-tracing');
    this.applyTrace(sel.id, 'is-focusing');
    // The same stream, latched, so a pipeline can be read at leisure (row 7).
    this.flow.stream(sel.id);
    this.host.announce('Focus mode on.');
  }

  /* ── collapse, zoom, navigation ────────────────────────────────────── */

  /** Collapse or expand a group, keeping its header anchored on screen. */
  toggleCollapse(id: string): void {
    if (!this.frameData) return;
    const before = this.frameData.boxes.get(id);
    const zoom = this.viewport.vp.zoom;
    const screen = before
      ? { x: before.x * zoom + this.viewport.vp.x, y: before.y * zoom + this.viewport.vp.y }
      : null;
    if (this.collapsedSet.has(id)) this.collapsedSet.delete(id);
    else this.collapsedSet.add(id);
    this.relayout();
    const after = this.frameData.boxes.get(id);
    if (after && screen) {
      this.viewport.set({
        x: screen.x - after.x * this.viewport.vp.zoom,
        y: screen.y - after.y * this.viewport.vp.zoom,
      });
    }
    const node = this.index ? this.index.nodeById.get(id) : null;
    const hidden = this.index ? this.index.descendantCount(id) : 0;
    this.host.afterCollapse();
    this.host.announce(
      'Group ' +
        (node ? node.label : id) +
        (this.collapsedSet.has(id) ? ' collapsed, ' + hidden + ' nodes hidden.' : ' expanded.'),
    );
  }

  /**
   * Overview mode (VIEW-10, `Shift+0`): every group folded to its card, then a
   * WHOLE fit — the picture a reviewer actually wants to paste. The aggregated
   * severity markers survive, because a collapsed group already carries them.
   *
   * Measured on the emitted demo in Chromium after the ANA-1 re-baseline: 22
   * cards, all of them inside the canvas at 1440x900 and at 1600x1000. VIEW-10's
   * "<= 14 visible cards" was written against the 45-node demo; the count is a
   * property of how many top-level units the workspace has, not of this method.
   */
  overview(): number {
    if (!this.index) return 0;
    const groups: string[] = [];
    for (const node of this.index.graph.nodes || []) {
      if (this.index.isGroup(node.id)) groups.push(node.id);
    }
    this.collapsedSet = new Set(groups);
    this.relayout();
    // fitWhole, not fit: Overview must never take the top-anchored tall branch,
    // or the whole-diagram picture it exists to produce opens clipped.
    this.viewport.fitWhole();
    this.host.afterCollapse();
    this.host.announce('Overview: ' + groups.length + (groups.length === 1 ? ' group' : ' groups') + ' collapsed, whole diagram fitted.');
    return groups.length;
  }

  /** Expand every collapsed ancestor of `id`. Returns true when it relaid out. */
  expandAncestors(id: string): boolean {
    if (!this.index) return false;
    let changed = false;
    for (const ancestor of this.index.ancestors(id)) {
      if (this.collapsedSet.delete(ancestor)) changed = true;
    }
    if (changed) this.relayout();
    return changed;
  }

  centerOnNode(id: string, pulse: boolean): void {
    if (!this.index || !this.frameData) return;
    const visible = this.index.visibleRepresentative(id, this.collapsedSet);
    const box = this.frameData.boxes.get(visible);
    if (!box) return;
    this.viewport.centerOn(box);
    if (!pulse) return;
    const element = this.nodeEls.get(visible);
    if (!element) return;
    element.classList.add('is-pulse');
    setTimeout(() => element.classList.remove('is-pulse'), 700);
  }

  zoomStep(dir: number): void {
    const size = this.viewport.size();
    this.viewport.zoomAt(dir > 0 ? 1.2 : 1 / 1.2, size.w / 2, size.h / 2);
  }

  fit(): void {
    this.viewport.fit();
  }

  zoomToNode(id: string): void {
    if (!this.index || !this.frameData) return;
    const box = this.frameData.boxes.get(this.index.visibleRepresentative(id, this.collapsedSet));
    if (box) this.viewport.zoomToBox(box);
  }

  /** The next node an arrow key should select, in spatial sibling order. */
  nextSelection(currentId: string | null, key: string): NextSelection | null {
    if (!this.index || !this.frameData) return null;
    const anchored = currentId && this.frameData.boxes.has(currentId) ? currentId : null;
    const next = anchored ? nextBox(this.index, this.frameData, anchored, key) : firstBox(this.frameData);
    if (!next) return null;
    return { id: next.id, visible: this.viewport.isVisible(next) };
  }

  /** The rendered card's accessible name — used by the live announcer. */
  labelOf(id: string): string | null {
    const element = this.nodeEls.get(id);
    return element ? element.getAttribute('aria-label') : null;
  }

  toast(text: string): void {
    this.toasts.show(text);
  }

  destroy(): void {
    if (this.hoverTimer !== null) {
      clearTimeout(this.hoverTimer);
      this.hoverTimer = null;
    }
    this.edgeHover.destroy();
    for (const dispose of this.disposers) {
      try {
        dispose();
      } catch (_e) {
        /* a host may already have torn the listener down */
      }
    }
    this.disposers = [];
    this.flow.destroy();
    this.toasts.destroy();
  }
}
