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
 *
 * Three neighbours hold the parts that are not geometry, and this class is what
 * composes them:
 *
 *   `canvas/host.ts`      the contract with the App, and the surface's timings
 *   `canvas/wiring.ts`    the gestures a rendered card or cable answers
 *   `canvas/emphasis.ts`  selection, hover, the lineage trace and focus mode
 */

import { GraphIndex } from './layout/model.js';
import { layoutGraph, LayoutFrame } from './layout/layout.js';
import { routeEdges, RoutedEdge } from './layout/routing.js';
import { planLabels, LabelPlan } from './layout/labels.js';
import { firstBox, nextBox } from './layout/navigate.js';
import { minimapDots, renderScene } from './render/scene.js';
import { planScene, ScenePlan, ScenePlanOptions } from './render/plan.js';
import { nextMountSerial } from './render/edges.js';
import { BundleBinding } from './render/bundles.js';
import { Minimap, ViewportController } from './render/canvas.js';
import { FlowBinding } from './render/flowbinding.js';
import { EdgeHover } from './render/edgehover.js';
import { Tooltip } from './render/tooltip.js';
import { Toasts, buildEmptyState, buildFilterEmptyState, buildScopeEmptyState } from './ui/states.js';
import { wireCanvasGestures } from './ui/shell.js';
import { Emphasis } from './canvas/emphasis.js';
import { wireEdgeEvents, wireNodeEvents } from './canvas/wiring.js';
import { HOVER_CLOSE_MS, HOVER_OPEN_MS, MINIMAP_MIN_NODES } from './canvas/host.js';
import type { CanvasHost, NextSelection } from './canvas/host.js';
import type { Shell } from './ui/shell.js';
import type { Sel } from './types.js';

export type { CanvasHost, NextSelection };
export { HOVER_CLOSE_MS, HOVER_OPEN_MS };

export class CanvasView {
  readonly canvasEl: HTMLElement;
  readonly viewport: ViewportController;
  readonly toasts: Toasts;

  private worldEl: HTMLElement;
  private lanesLayer: HTMLElement;
  private edgesSvg: SVGElement;
  private bundleGroup: SVGElement;
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
  /** VIEW-03: where every edge label and severity marker goes. */
  private labelPlan: LabelPlan | null = null;
  private collapsedSet = new Set<string>();
  private staleFiles: string[] = [];
  private nodeEls = new Map<string, HTMLElement>();
  private edgeEls = new Map<string, SVGElement>();
  /** VIEW-04: which cross-lane trunks are drawn, and which cables they hold. */
  private bundles = new BundleBinding();
  /**
   * This view's identity inside the DOCUMENT. It qualifies every edge path id,
   * so two apps on one page (dev/states.html, or two reports in one host) can
   * never share the motion path a charge rides (CONTRACTS 11.13.1).
   */
  private readonly mountSerial = nextMountSerial();
  private disposers: (() => void)[] = [];
  /** WHEN a charge runs, and the latch cascade that keeps it running. */
  readonly flow: FlowBinding;
  /** Selection, hover, the lineage trace and focus mode (canvas/emphasis.ts). */
  private emphasis: Emphasis;
  /** Which cable the pointer owns, and the delay before that means anything. */
  private edgeHover: EdgeHover;

  constructor(shell: Shell, host: CanvasHost) {
    this.host = host;
    this.canvasEl = shell.canvas;
    this.worldEl = shell.world;
    this.lanesLayer = shell.lanesLayer;
    this.edgesSvg = shell.edgesSvg;
    this.bundleGroup = shell.bundleGroup;
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
    // VIEW-12: BEFORE the canvas, and outside it. The minimap duplicates a
    // diagram that is already fully navigable from the keyboard, so it is
    // `aria-hidden` — and an `aria-hidden` subtree may not contain a tab stop,
    // which is why its in-panel chevron is pointer-only and the keyboard's
    // toggle lives in the toolbar. It is absolutely positioned either way, so
    // it is drawn exactly where it always was.
    shell.main.insertBefore(this.minimap.root, this.canvasEl);

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
      hoverNodeId: () => this.emphasis.hoverNodeId,
      lockedNodeId: () => this.emphasis.lockedNodeId,
      hoverEdgeId: () => this.edgeHover.hoveredId,
      toast: (text) => this.toasts.show(text),
    });

    this.emphasis = new Emphasis({
      canvas: this.canvasEl,
      connectors: this.connectorLayer,
      flow: this.flow,
      tooltip: this.tooltip,
      nodeEls: () => this.nodeEls,
      edgeEls: () => this.edgeEls,
      routes: () => this.routes,
      index: () => this.index,
      frame: () => this.frameData,
      collapsed: () => this.collapsedSet,
      syncBundles: () => this.syncBundles(),
      keep: (issue) => this.host.keep(issue),
      announce: (text) => this.host.announce(text),
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
        if (!this.emphasis.hoverNodeId) this.tooltip.hide();
        this.flow.stop();
      },
      hide: () => this.tooltip.hide(),
      // VIEW-04: opening the bundle is not an intent, it is the hover itself.
      changed: () => this.syncBundles(),
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
    // VIEW-03. Pure geometry over the frame and the routes, so it costs one
    // O(labels) pass with grid bucketing and moves no box.
    this.labelPlan = planLabels(this.frameData, this.routes);
    this.viewport.setContent(this.frameData.width, this.frameData.height);
    // A SCOPE is small by construction, so the "fit the width and let them pan
    // down" rule written for a whole workspace does not apply to it: it opened a
    // report scoped to evaluation with the evaluation lane below the fold
    // (MLV-R3-001).
    this.viewport.setProjected(!!this.index.graph.view);
    this.render();
  }

  /**
   * The inputs both renderers share. VIEW-07's SVG export walks the plan these
   * produce, so a divergence would have to be introduced here, in one place,
   * rather than by two renderers drifting apart.
   */
  private planInputs(): ScenePlanOptions | null {
    if (!this.index || !this.frameData) return null;
    return {
      index: this.index,
      frame: this.frameData,
      routes: this.routes,
      labels: this.labelPlan ? this.labelPlan.placements : null,
      mountSerial: this.mountSerial,
      keep: (issue) => this.host.keep(issue),
      staleFiles: this.staleFiles,
      isFilteredOut: (node) => this.host.isFilteredOut(node),
    };
  }

  /** What is currently drawn, as data — the export's single source (VIEW-07). */
  scenePlan(): ScenePlan | null {
    const inputs = this.planInputs();
    return inputs ? planScene(inputs) : null;
  }

  /** The visible canvas, in WORLD coordinates — the "current view" region. */
  viewportRect(): { x: number; y: number; w: number; h: number } {
    const size = this.viewport.size();
    const vp = this.viewport.vp;
    const zoom = vp.zoom || 1;
    return { x: -vp.x / zoom, y: -vp.y / zoom, w: size.w / zoom, h: size.h / zoom };
  }

  /** Rebuild the scene DOM from the current frame. Never moves boxes. */
  render(): void {
    const inputs = this.planInputs();
    if (!inputs) return;
    // One port per render, not one per card: the scene below calls these for
    // every node and every edge it builds.
    const nodePort = this.nodeWiring();
    const edgePort = this.edgeWiring();
    const scene = renderScene(
      {
        world: this.worldEl,
        lanes: this.lanesLayer,
        edgesSvg: this.edgesSvg,
        bundleGroup: this.bundleGroup,
        edgeGroup: this.edgeGroup,
        connectors: this.connectorLayer,
        nodes: this.nodesLayer,
      },
      {
        ...inputs,
        wireNode: (element, id, isGroup) => wireNodeEvents(element, id, isGroup, nodePort),
        wireEdge: (element, route) => wireEdgeEvents(element, route, edgePort),
      },
    );
    this.nodeEls = scene.nodeEls;
    this.edgeEls = scene.edgeEls;
    this.bundles.adopt(scene.bundleEls, scene.plan.bundles.map((v) => v.bundle));
    this.syncBundles();
    // Every card and cable the pointer was over went with the old DOM, so no
    // hover survives a rebuild. Without this the latch cascade in `flow.stop()`
    // would resume a stream over a scene that no longer holds that node
    // (CONTRACTS 11.14 C1).
    this.emphasis.resetHover();
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

  /* ── event wiring (canvas/wiring.ts) ───────────────────────────────── */

  private nodeWiring() {
    return {
      isGroup: (id: string) => !!this.index && this.index.isGroup(id),
      toggleCollapse: (id: string) => this.toggleCollapse(id),
      hoverIntent: (id: string | null) => this.emphasis.hoverIntent(id),
      activateNode: (id: string) => this.host.activateNode(id),
      addDisposer: (dispose: () => void) => this.disposers.push(dispose),
    };
  }

  private edgeWiring() {
    return {
      activateEdge: (id: string) => this.host.activateEdge(id),
      enterEdge: (route: RoutedEdge) => this.edgeHover.enter(route),
      leaveEdge: (route: RoutedEdge) => this.edgeHover.leave(route),
      syncBundles: () => this.syncBundles(),
      pulse: (route: RoutedEdge) => this.flow.pulse(route),
      stopFlow: () => this.flow.stop(),
    };
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

  /* ── selection, hover, focus (canvas/emphasis.ts) ──────────────────── */

  applySelection(sel: Sel | null): void {
    this.emphasis.applySelection(sel);
  }

  hoverIntent(id: string | null): void {
    this.emphasis.hoverIntent(id);
  }

  setHover(id: string | null): void {
    this.emphasis.setHover(id);
  }

  get isFocusLocked(): boolean {
    return this.emphasis.isFocusLocked;
  }

  toggleFocusMode(sel: Sel | null): void {
    this.emphasis.toggleFocusMode(sel);
  }

  /**
   * VIEW-04. A cross-lane trunk shows its individual strokes exactly while one
   * of them is hovered, focused, selected, lit or flowing — four triggers, one
   * rule, read off the cables themselves so this can never disagree with them.
   */
  syncBundles(): void {
    this.bundles.sync(this.edgeEls);
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
    this.emphasis.destroy();
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
