/**
 * The canvas view — everything inside the diagram surface.
 *
 * It owns the layout frame, the routed edges, the scene DOM, the viewport, the
 * phase index and the phase overview, the tooltip and the transient states (hover,
 * focus mode, collapse).
 * The App owns the chrome, the rail, the filters and the host protocol, and
 * drives this class through the `CanvasHost` callbacks.
 *
 * Layout depends only on (graph, collapsed). Selection, hover, focus and their
 * highlights are pure class toggles here, so they never trigger a re-render.
 *
 * Three neighbours hold the parts that are not geometry, and this class is what
 * composes them:
 *
 *   `canvas/host.ts`      the contract with the App, and the surface's timings
 *   `canvas/wiring.ts`    the gestures a rendered card or cable answers
 *   `canvas/emphasis.ts`  selection, hover, the lineage trace and focus mode
 *
 * A fourth holds one piece of the camera: `canvas/far.ts`, the end of a far connection that the
 * review walk keeps in view, and the caps on its line.
 */

import { on } from './dom.js';
import { GraphIndex } from './layout/model.js';
import { layoutGraph, LayoutFrame } from './layout/layout.js';
import type { LayoutBox } from './layout/layout.js';
import { routeEdges, RoutedEdge } from './layout/routing.js';
import type { Point } from './layout/routing.js';
import { planLabels, LabelPlan } from './layout/labels.js';
import { connectionEnd, firstBox, nextBox } from './layout/navigate.js';
import { renderScene } from './render/scene.js';
import { planScene, ScenePlan, ScenePlanOptions } from './render/plan.js';
import { markerPoint, nextMountSerial } from './render/edges.js';
import { BundleBinding } from './render/bundles.js';
import { FRAME_MIN_ZOOM, LOD_FULL_ZOOM, READABLE_MIN_ZOOM, READABLE_ZOOM, ViewportController, phasePlan } from './render/canvas.js';
import { PhaseIndex } from './render/phaseindex.js';
import type { PhaseRow } from './render/phaseindex.js';
import { overviewInput } from './render/phaseoverview.js';
import { PhaseOverview } from './ui/overview.js';
import { FlowBinding } from './render/flowbinding.js';
import { EdgeHover } from './render/edgehover.js';
import { Tooltip } from './render/tooltip.js';
import { Toasts, buildEmptyState, buildFilterEmptyState } from './ui/states.js';
import { wireCanvasGestures } from './ui/shell.js';
import { Emphasis } from './canvas/emphasis.js';
import { FarView } from './canvas/far.js';
import { wireEdgeEvents, wireNodeEvents } from './canvas/wiring.js';
import { HOVER_CLOSE_MS, HOVER_OPEN_MS, PHASE_INDEX_LIST_MIN_H, PHASE_INDEX_LIST_MIN_W } from './canvas/host.js';
import type { CanvasHost, NextSelection } from './canvas/host.js';
import type { Shell } from './ui/shell.js';
import type { Sel, StaleFile, StaleReason } from './types.js';
import { changeOf } from './revisiondiff.js';
import type { RevisionDiff } from './revisiondiff.js';
import type { RevisionMark } from './render/nodes.js';

/** A step's card tag, from the comparison with the revision this panel showed before. */
function revisionMarkOf(diff: RevisionDiff | null, id: string): RevisionMark | undefined {
  const change = changeOf(diff, 'node', id);
  return change && diff ? { status: change.status === 'added' ? 'added' : 'changed', fields: change.fields, since: diff.since } : undefined;
}

/** A zoom a shrinking canvas took away (`CanvasView.lentZoom`). */
interface LentZoom {
  from: number;
  to: number;
  framed: boolean;
  id: string;
  w: number;
  h: number;
}

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
  /** The labelled phase index and the phase overview. */
  private phaseIndex: PhaseIndex;
  private overview: PhaseOverview;
  /** Where the keyboard was when the overview opened, so Escape gives it back. */
  private overviewReturn: HTMLElement | null = null;
  /** The panel's width as the App last measured it (0 when it cannot be measured). */
  private panelWidth = 0;
  private indexFolded = false;
  private indexHidden = false;
  /** The phase a move to a phase landed on, where the next arrow key starts. */
  private arrowLane: string | null = null;
  /**
   * A keyboard move or a walk step holds the hover back until the pointer really moves
   * (`holdHover`). `pointerAt` is the pointer's last place over the canvas; `heldAt` the place it
   * rested at when the hold began, null until it is known.
   */
  private hoverHeld = false;
  private pointerAt: { x: number; y: number } | null = null;
  private heldAt: { x: number; y: number } | null = null;

  private host: CanvasHost;
  private index: GraphIndex | null = null;
  private frameData: LayoutFrame | null = null;
  private routes: RoutedEdge[] = [];
  /** Where every edge label and severity marker goes. */
  private labelPlan: LabelPlan | null = null;
  private collapsedSet = new Set<string>();
  private staleFiles = new Map<string, StaleReason>();
  /** What changed since the revision this panel showed before (`setRevisionChanges`). */
  private revisionChanges: RevisionDiff | null = null;
  private nodeEls = new Map<string, HTMLElement>();
  private edgeEls = new Map<string, SVGElement>();
  /** Route id -> where its severity marker is drawn, for the edge hover resolver. */
  private markerPoints = new Map<string, Point>();
  /** Which cross-lane trunks are drawn, and which cables they hold. */
  private bundles = new BundleBinding();
  /**
   * This view's identity inside the DOCUMENT. It qualifies every edge path id,
   * so two viewers mounted on one page (each `mountWorkflow` call mounts one)
   * never share the motion path a charge rides.
   */
  private readonly mountSerial = nextMountSerial();
  private disposers: (() => void)[] = [];
  /** WHEN a charge runs, and the latch cascade that keeps it running. */
  readonly flow: FlowBinding;
  /** Selection, hover, the lineage trace and focus mode (canvas/emphasis.ts). */
  private emphasis: Emphasis;
  /** Which cable the pointer owns, and the delay before that means anything. */
  private edgeHover: EdgeHover;
  /** The visible area as of the last viewport change, so a resize knows what was in view. */
  private lastArea: { w: number; h: number } | null = null;
  /** The part of that area the phase index covered then (`ViewportController.covered`), or null. */
  private lastCovered: { x: number; y: number; w: number; h: number } | null = null;
  /**
   * Who chose the zoom on screen, the viewer or the reader.
   *
   * `framedZoom` is that zoom while the viewer chose it, and null while the reader did.
   * - Taken after the viewer's own moves, once they have moved (`noteFramedZoom`): a finding's
   *   frame (`frameIssue`), a walk step (`walkTarget`), a look at an end of the walk's connection
   *   (`FarView.look`) and a resize's frame of a kept connection (`handleResize`). A zoom such a
   *   move changed is the viewer's; one it kept stays whose it was.
   * - Dropped by every other change of zoom, in the viewport's change hook: the wheel, a pinch,
   *   + and -, 0, a fit, a move to a phase, a Reveal in Diagram of a step or a connection. So after
   *   + and then - the zoom is the reader's, even when it is the same value again, and the field
   *   is always null or the zoom on screen.
   * - Read by `walkTarget`: the walk returns to reading size from the viewer's zoom only.
   * - Saved with the viewport (`ViewState.framedZoom`, absent when null) and restored with it on
   *   a remount (`restoreFramedZoom`), so a walk resumed in a panel that was hidden and shown again
   *   still returns to reading size.
   *
   * `lentZoom` is a zoom a shrinking canvas took away, while it can still be given back: `from`,
   * the zoom the resize's frame of a kept connection replaced; `framed`, whether that one was the
   * viewer's; `to`, the lower zoom on screen since; `id`, that connection; `w` and `h`, the
   * canvas's width and height before the shrink, 0 for the one that did not shrink.
   * - Made by `handleResize` when its frame lowers the zoom; a further shrink keeps the first loan.
   * - Dropped by every change of zoom that is not a resize's own (the same hook), so a reader who
   *   has zoomed since keeps that zoom.
   * - Given back when the canvas grows again (`returnZoom`). To its connection, while that is kept
   *   with both cards in view, on any growth: whole or as far as the canvas allows. To anything
   *   else only once the canvas is as wide and as tall again as `w` and `h`: whole, except that
   *   another connection kept with both cards in view gets it as far as the canvas holds those
   *   two. What a connection leaves stays on loan, and on such a canvas the next growth of any
   *   size gives it to whatever is kept then. Whole, the zoom is again the reader's or the
   *   viewer's, as `framed` says.
   * - Not saved: after a remount the lower zoom stays.
   */
  private framedZoom: number | null = null;
  private lentZoom: LentZoom | null = null;
  /** The end of a far connection the walk keeps in view, and the caps on its line. */
  readonly far: FarView;

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
    // A card's hover card says what changed since the revision this panel showed before: the
    // card's tag takes no pointer events (node.css), so it cannot show a tooltip of its own.
    this.tooltip.revisionMark = (id) => revisionMarkOf(this.revisionChanges, id);
    this.canvasEl.appendChild(this.tooltip.root);

    // The phase index, inside the canvas (so in the bottom sheet's layout it stays above the
    // sheet) and outside the world layer. Its rows are not Tab stops; the phase overview is the
    // keyboard's way to the same moves. The viewport treats what it covers as out of view.
    this.phaseIndex = new PhaseIndex({
      go: (id) => this.goToPhase(id, { focusCanvas: true }),
      fold: (folded) => {
        this.indexFolded = folded;
        this.syncPhaseIndex();
        this.host.onPhaseIndexChanged();
      },
      shape: () => this.noteIndexShape(),
    });
    this.canvasEl.appendChild(this.phaseIndex.root);
    // The phase overview (Shift+0): an overlay over the whole canvas, drawn from its own geometry.
    this.overview = new PhaseOverview({
      go: (id, byKeyboard) => {
        // Enter on a block pans the diagram under a pointer that may rest over it.
        if (byKeyboard) this.holdHover();
        this.goToPhase(id, { focusCanvas: true });
      },
      back: () => this.closeOverview(true),
    });
    this.canvasEl.appendChild(this.overview.root);

    this.toasts = new Toasts();
    this.canvasEl.appendChild(this.toasts.root);

    this.viewport = new ViewportController(this.canvasEl, this.worldEl, (vp) => {
      this.zoomLevelEl.textContent = Math.round(vp.zoom * 100) + '%';
      const size = this.viewport.size();
      this.phaseIndex.setInView(vp, size.w, size.h);
      this.lastArea = this.viewport.visibleArea();
      this.lastCovered = this.viewport.covered();
      // A change of zoom ends the viewer's claim on the one before it, and a loan made at it; the
      // viewer's own moves take them again once they have moved (`framedZoom`).
      if (this.framedZoom !== null && vp.zoom !== this.framedZoom) this.framedZoom = null;
      if (this.lentZoom && vp.zoom !== this.lentZoom.to) this.lentZoom = null;
      this.host.onViewportChange(vp);
    });
    this.viewport.setCovered(() => this.indexCovered());

    // The caps of a far connection go over the world and under the phase index, the overview
    // and the toasts.
    this.far = new FarView({
      viewport: this.viewport,
      index: () => this.index,
      frame: () => this.frameData,
      routes: () => this.routes,
      collapsed: () => this.collapsedSet,
      edgeEls: () => this.edgeEls,
      endBoxes: (id) => this.endBoxes(id),
      inChargeColour: (id) => this.flow.controller.inChargeColour(id),
      readableZoomFor: (box) => this.readableZoomFor(box),
      viewerZoom: () => this.framedZoom,
      noteFramedZoom: (before) => this.noteFramedZoom(before),
      restoreFramedZoom: (zoom) => this.restoreFramedZoom(zoom),
      onCap: (end, ev) => this.host.onFarCap(end, ev),
      onCue: (on) => this.host.onFarCue(on),
    });
    this.canvasEl.insertBefore(this.far.root, this.phaseIndex.root);

    for (const dispose of wireCanvasGestures(this.canvasEl, this.viewport, {
      onKeyDown: (ev) => this.host.onKeyDown(ev),
      onBackgroundClick: () => this.host.onBackgroundClick(),
      onResize: () => this.handleResize(),
    })) {
      this.disposers.push(dispose);
    }
    // The canvas also changes size without the window doing so: the rail is
    // shown or hidden, the header's disclosure opens. Where the host has a
    // ResizeObserver (jsdom has none) it drives the same path.
    const RO = (typeof window !== 'undefined' ? (window as unknown as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver : undefined);
    if (RO) {
      const observer = new RO(() => this.handleResize());
      observer.observe(this.canvasEl);
      this.disposers.push(() => observer.disconnect());
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
      // The cap of a far connection takes the colour its line is drawn in.
      onFlowChange: () => this.host.onFarStale(),
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
      hoverHeld: () => this.hoverHeld,
    });

    // Which cable the pointer owns is decided by geometry, not by document
    // order (`render/edgehover.ts`). Nothing is built before the pointer
    // settles, so a sweep across the diagram still allocates nothing.
    this.edgeHover = new EdgeHover({
      canvas: this.canvasEl,
      viewport: this.viewport,
      routes: () => this.routes,
      edges: () => this.edgeEls,
      markers: () => this.markerPoints,
      open: (route) => {
        if (!this.index) return;
        this.tooltip.showEdge(this.index, route, (issue) => this.host.keep(issue), this.markerPoints.get(route.id));
        this.flow.pulse(route);
      },
      close: () => {
        if (!this.emphasis.hoverNodeId) this.tooltip.hide();
        this.flow.stop();
      },
      hide: () => this.tooltip.hide(),
      // Opening the bundle is not an intent, it is the hover itself.
      changed: () => this.syncBundles(),
      openDelayMs: HOVER_OPEN_MS,
      closeDelayMs: HOVER_CLOSE_MS,
      held: () => this.hoverHeld,
    });
    // Before the cable resolver's own pointermove, so a real move ends a hold before it resolves.
    this.disposers.push(on(this.canvasEl, 'pointermove', (ev: PointerEvent) => this.trackPointer(ev)));
    this.disposers.push(on(this.canvasEl, 'pointerdown', () => this.releaseHover()));
    this.disposers.push(this.edgeHover.wire());
  }

  /* ── the hover hold ────────────────────────────────────────────────── */

  /**
   * A keyboard move or a walk step is about to pan the diagram, or just did: the hover card goes,
   * with a card's trace and a cable's highlight, and no card or cable that passes under a resting
   * pointer takes the hover until the pointer moves again. Without the hold, the cards that a pan
   * moves under a resting pointer would open their hover cards over the diagram. A press of the
   * pointer also ends the hold.
   */
  holdHover(): void {
    this.hoverHeld = true;
    this.heldAt = this.pointerAt;
    this.emphasis.dropHover();
    this.edgeHover.drop();
    this.tooltip.hide();
  }

  /** True while the hover is held back (tests read it). */
  get hoverIsHeld(): boolean {
    return this.hoverHeld;
  }

  private releaseHover(): void {
    this.hoverHeld = false;
    this.heldAt = null;
  }

  /**
   * Every pointer move over the canvas. While the hover is held, a move to the place the pointer
   * rested at is not the reader's (the browser sends one when the picture moves under it); the
   * first move somewhere else ends the hold, and the card under the pointer gets its hover, whose
   * own pointerenter came during the hold.
   */
  private trackPointer(ev: PointerEvent): void {
    const at = { x: ev.clientX, y: ev.clientY };
    this.pointerAt = at;
    if (!this.hoverHeld) return;
    if (!this.heldAt) {
      this.heldAt = at;
      return;
    }
    if (at.x === this.heldAt.x && at.y === this.heldAt.y) return;
    this.releaseHover();
    const target = ev.target as Element | null;
    const hit = target && typeof target.closest === 'function' ? target.closest('.mlv-node[data-node-id], .mlv-group__header') : null;
    const card = hit && hit.classList.contains('mlv-group__header') ? hit.closest('[data-node-id]') : hit;
    const id = card ? card.getAttribute('data-node-id') : null;
    if (id && this.canvasEl.contains(card)) this.emphasis.hoverIntent(id);
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

  /* ── the phase index ───────────────────────────────────────────────── */

  /** The reader folded the wide phase index to its pill (saved per viewer). */
  get phaseIndexFolded(): boolean {
    return this.indexFolded;
  }

  /** The reader hid the phase index (the ... menu; saved per viewer). */
  get phaseIndexHidden(): boolean {
    return this.indexHidden;
  }

  setPhaseIndex(state: { folded?: boolean; hidden?: boolean }): void {
    if (typeof state.folded === 'boolean') this.indexFolded = state.folded;
    if (typeof state.hidden === 'boolean') this.indexHidden = state.hidden;
    this.syncPhaseIndex();
  }

  /** The phase index's element (tests read it). */
  get phaseIndexElement(): HTMLElement {
    return this.phaseIndex.root;
  }

  /** The phases the phase index marks as in view, in drawn order. */
  phasesInView(): string[] {
    return this.phaseIndex.inView();
  }

  /**
   * The panel's width and the canvas's height decide the phase index's form: the panel of rows
   * from PHASE_INDEX_LIST_MIN_W (1000 px) wide on a canvas at least PHASE_INDEX_LIST_MIN_H tall,
   * the pill otherwise (`syncPhaseIndex`). An unmeasurable panel or canvas (jsdom, a detached
   * mount) keeps the panel of rows.
   */
  setPanelWidth(width: number): void {
    if (!(width > 0)) return;
    this.panelWidth = width;
    this.syncPhaseIndex();
  }

  /**
   * Why the phase index cannot be drawn, in words for the ... menu, which then disables its item;
   * null when it can be (as the panel of rows or as the pill). It needs two or more phases.
   */
  phaseIndexUnavailable(): string | null {
    return this.phaseIndex.available ? null : 'Shown when the diagram has two or more phases';
  }

  /** Close the pill's open phase list (an Escape rung); false when it was not open. */
  closePhasePopover(): boolean {
    return this.phaseIndex.closePopover();
  }

  private syncPhaseIndex(): void {
    const height = this.canvasEl.getBoundingClientRect().height;
    const wide = !(this.panelWidth > 0) || this.panelWidth >= PHASE_INDEX_LIST_MIN_W;
    const tall = !(height > 0) || height >= PHASE_INDEX_LIST_MIN_H;
    this.phaseIndex.setMode({ roomy: wide && tall, folded: this.indexFolded, hidden: this.indexHidden, suppressed: this.overview.open });
    this.noteIndexShape();
  }

  /**
   * The phase index changed shape with no change of viewport: folded or unfolded, hidden or shown,
   * the pill's list opened or closed, the overview over it, the panel of rows and the pill swapped
   * (`syncPhaseIndex`). What it covers now is what the next resize judges "was in view" by
   * (`lastCovered`): judged by the shape it had before, a resize would leave off the canvas a
   * selected card that the reader can now see whole (under the index when it was hidden or folded,
   * or under the list that has closed). Only on a canvas of the remembered size: during a resize
   * the index where it was then is what `handleResize` needs.
   *
   * The caps of a far connection keep clear of the index, and an end card under it is out of view,
   * so the App places them again for the shape the index has now.
   */
  private noteIndexShape(): void {
    if (!this.viewport || !this.lastArea) return;
    const area = this.viewport.visibleArea();
    if (area.w === this.lastArea.w && area.h === this.lastArea.h) this.lastCovered = this.viewport.covered();
    this.host.onFarStale();
  }

  /** What the phase index covers, in canvas pixels (the viewport keeps targets out of it). */
  private indexCovered(): { x: number; y: number; w: number; h: number } | null {
    const r = this.canvasEl.getBoundingClientRect();
    const size = this.viewport.size();
    return this.phaseIndex.coveredRect(size.w, size.h, r.width > 0 ? r.left : 0, r.width > 0 ? r.top : 0);
  }

  private renderPhaseIndex(): void {
    if (!this.index || !this.frameData) return;
    const rows: PhaseRow[] = this.frameData.lanes.map((lane) => ({
      id: lane.id,
      label: lane.label,
      index: this.index!.phaseIndexOf(lane.id),
      steps: lane.nodeCount,
      counts: this.index!.laneCounts(lane.id, (issue) => this.host.keep(issue)),
      rect: { x: lane.x, y: lane.y, w: lane.w, h: lane.h },
    }));
    this.phaseIndex.setRows(rows);
    this.syncPhaseIndex();
    const size = this.viewport.size();
    this.phaseIndex.setInView(this.viewport.vp, size.w, size.h);
  }

  /* ── the phase overview (Shift+0) ──────────────────────────────────── */

  get overviewOpen(): boolean {
    return this.overview.open;
  }

  /** The overview's element and its layout (tests read the layout). */
  get overviewElement(): HTMLElement {
    return this.overview.root;
  }

  overviewLayout() {
    return this.overview.layout;
  }

  /**
   * Open the overview over the canvas, on the phase most in view. The diagram under it does not
   * move, so closing it is going back to exactly where the reader was. False with no phases.
   */
  openOverview(): boolean {
    if (!this.index || !this.frameData || this.overview.open || !this.index.lanes.length) return false;
    const doc = this.canvasEl.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    this.overviewReturn = active && active !== doc!.body ? active : null;
    this.tooltip.hide();
    const input = overviewInput(this.index, (issue) => this.host.keep(issue));
    const size = this.viewport.size();
    const current = this.phaseIndex.currentPhase();
    const at = Math.max(0, input.phases.findIndex((p) => p.id === current));
    this.overview.show(input, size.w, size.h, at);
    this.syncPhaseIndex();
    const n = input.phases.length;
    this.host.announce('Phase overview: ' + n + (n === 1 ? ' phase' : ' phases') + ', ' + input.totalSteps + (input.totalSteps === 1 ? ' step' : ' steps') +
      '. Arrow keys move between phases, Enter goes to one, Escape goes back.');
    return true;
  }

  /**
   * Close the overview. `back` (Escape, Shift+0, the Back button): the keyboard returns to where it
   * was, and the diagram is as it was. Otherwise (a phase was chosen, another key acted) the caller
   * decides where the focus goes. False when it was not open.
   */
  closeOverview(back: boolean): boolean {
    if (!this.overview.open) return false;
    const doc = this.canvasEl.ownerDocument;
    const hadFocus = !!doc && !!doc.activeElement && this.overview.root.contains(doc.activeElement);
    this.overview.hide();
    this.syncPhaseIndex();
    const target = this.overviewReturn;
    this.overviewReturn = null;
    if (back) {
      this.host.announce('Back to the diagram.');
      if (hadFocus) this.focusSafely(target && target.isConnected && !this.overview.root.contains(target) ? target : this.canvasEl);
    } else if (hadFocus) this.focusSafely(this.canvasEl);
    return true;
  }

  toggleOverview(): void {
    if (this.overview.open) this.closeOverview(true);
    else this.openOverview();
  }

  /**
   * Go to a phase at reading size (`phasePlan`), animated over VIEW_ANIMATION_MS unless motion is
   * reduced: a block of the overview, or a row of the phase index. The selection is unchanged; the
   * next arrow key starts at the phase's first step.
   */
  goToPhase(laneId: string, opts: { focusCanvas?: boolean } = {}): void {
    if (!this.index || !this.frameData) return;
    const k = this.frameData.lanes.findIndex((lane) => lane.id === laneId);
    if (k < 0) return;
    const wasOpen = this.closeOverview(false);
    const size = this.viewport.size();
    const plan = phasePlan(this.frameData, k, size.w, size.h);
    if (plan) this.viewport.animateTo({ x: plan.x, y: plan.y, zoom: plan.zoom });
    this.arrowLane = laneId;
    const lane = this.frameData.lanes[k];
    this.host.announce('Phase ' + (this.index.phaseIndexOf(laneId) + 1) + ': ' + lane.label + ', ' + lane.nodeCount + (lane.nodeCount === 1 ? ' step' : ' steps') + '.');
    if (opts.focusCanvas || wasOpen) this.focusSafely(this.canvasEl);
  }

  /** The phase a move to a phase landed on, once (the next arrow key starts there), or null. */
  takeArrowLane(): string | null {
    const lane = this.arrowLane;
    this.arrowLane = null;
    return lane;
  }

  /** Forget the arrow start (any selection replaces it). */
  clearArrowLane(): void {
    this.arrowLane = null;
  }

  /**
   * Without `preventScroll`, focusing an element that is not wholly on the canvas (a group's
   * header above it, a connection's hit path, whose box spans its whole route) makes the browser
   * scroll the canvas, although it clips (`overflow: hidden`). The world and the phase index then
   * move together on screen while the viewport still places them unscrolled, so every later
   * reveal is off by that scroll. Only the viewport moves the view.
   */
  private focusSafely(target: HTMLElement): void {
    try {
      target.focus({ preventScroll: true });
    } catch (_e) {
      /* a detached element cannot take focus */
    }
  }

  setStale(files: StaleFile[]): void {
    this.staleFiles = new Map(files.map((file) => [file.path, file.reason] as [string, StaleReason]));
  }

  /**
   * The steps added or changed since the revision this panel showed before carry a "new" or
   * "changed" tag on their card. The tag is an overlay drawn by the next render (the App sets this
   * before the document's layout); it moves no box and no route, and the SVG export, which walks
   * the scene plan, does not draw it.
   */
  setRevisionChanges(diff: RevisionDiff | null): void {
    this.revisionChanges = diff;
  }

  nodeElement(id: string): HTMLElement | undefined {
    return this.nodeEls.get(id);
  }

  /**
   * Put the keyboard on a step's card (a group's header), on a connection, or, with `null` or a
   * target that is not drawn on its own, on the canvas.
   */
  focusTarget(target: { kind: 'node' | 'edge'; id: string } | null): void {
    let element: Element | null | undefined = null;
    if (target && target.kind === 'node' && this.index) {
      const card = this.nodeEls.get(this.index.visibleRepresentative(target.id, this.collapsedSet));
      element = card && card.classList.contains('mlv-group') ? card.querySelector('.mlv-group__header') : card;
    } else if (target && target.kind === 'edge') {
      element = this.edgeEls.get(target.id)?.querySelector('.mlv-edge__hit');
    }
    this.focusSafely((element as HTMLElement | null) || this.canvasEl);
  }

  /** Re-run layout + routing. The only thing that moves boxes. */
  relayout(): void {
    if (!this.index) return;
    this.frameData = layoutGraph(this.index, this.collapsedSet);
    this.routes = routeEdges(this.index, this.frameData, this.collapsedSet);
    // Pure geometry over the frame and the routes: one O(labels) pass with grid
    // bucketing, and it moves no box.
    this.labelPlan = planLabels(this.frameData, this.routes);
    // The frame too, so the readable first view can anchor on phase 1.
    this.viewport.setContent(this.frameData.width, this.frameData.height, this.frameData);
    this.far.relaid();
    this.render();
  }

  /**
   * The inputs both renderers share. The SVG export walks the plan these
   * produce, so the export and the canvas cannot drift apart: a difference
   * would have to be made here, in one place.
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
    };
  }

  /** What is currently drawn, as data — the export's single source. */
  scenePlan(): ScenePlan | null {
    const inputs = this.planInputs();
    return inputs ? planScene(inputs) : null;
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
        revisionMark: (id) => revisionMarkOf(this.revisionChanges, id),
      },
    );
    this.nodeEls = scene.nodeEls;
    this.edgeEls = scene.edgeEls;
    this.markerPoints = new Map();
    for (const visual of scene.plan.edges) if (visual.severity) this.markerPoints.set(visual.route.id, markerPoint(visual));
    this.bundles.adopt(scene.bundleEls, scene.plan.bundles.map((v) => v.bundle));
    this.syncBundles();
    // Every card and cable the pointer was over went with the old DOM, so no
    // hover survives a rebuild. Without this the latch cascade in `flow.stop()`
    // would resume a stream for a node that the new scene does not hold.
    this.emphasis.resetHover();
    this.edgeHover.reset();
    // The scene DOM was replaced, so every flow element went with it. Reset the
    // controller's memory and re-stamp the canvas; a latched pulse is re-applied
    // by the applySelection that follows.
    this.flow.clear();
    this.renderPhaseIndex();
    this.renderEmptyState();
    // An open overview follows the new data (a severity toggle changes its F labels).
    if (this.overview.open && this.index) {
      const size = this.viewport.size();
      this.overview.redraw(overviewInput(this.index, (issue) => this.host.keep(issue)), size.w, size.h);
    }
  }

  /**
   * A canvas under PHASE_INDEX_LIST_MIN_H tall has no room for the panel of rows, so the phase
   * index is its pill there; an open overview is drawn for the new size.
   */
  private syncShortCanvas(): void {
    this.syncPhaseIndex();
    if (this.overview.open && this.index) {
      const size = this.viewport.size();
      this.overview.redraw(overviewInput(this.index, (issue) => this.host.keep(issue)), size.w, size.h);
    }
  }

  /**
   * The window or the canvas resized, or the rail changed shape: docked to the bottom sheet, the
   * sheet opening, collapsing or being dragged. A selected target that was wholly in view stays
   * wholly in view.
   *
   * Such a target is kept by the least pan that brings it back, at the same zoom, and a fitted
   * viewport is NOT refitted while it holds one: the readable fit may anchor on phase 1, so a refit
   * would leave a card selected anywhere else under the open sheet or off the canvas, as when Enter
   * opens the source beside the panel and narrows it. A target the reader had already moved out of
   * view is left where it is, and nothing here runs except on a change of size or layout, so a
   * reader panning away is never pulled back.
   *
   * "Was in view" is judged on the canvas before the resize and the phase index where it was then
   * (`lastArea`, `lastCovered`). The index sits in the canvas's lower corner and moves with it, so
   * judged by where it is now, a card that the new size cuts off at the foot would look as if it
   * had been under the index already, and would be left there. Under reduced motion every
   * transition takes 0.01 ms (base.css), and the opening sheet's new height can reach the canvas a
   * frame after a reveal centred the card on the taller canvas. A card the reader left under the
   * index was out of view, so it stays there.
   *
   * A connection is in view when both its cards are (`endBoxes`), the empty corner of their union
   * aside, as `frameEdge` frames it. A frame sized for the taller canvas may not fit the shorter one
   * at the same zoom, and then no pan shows both cards. Such a connection is framed again on the
   * new canvas (`frameClear`), zooming out no further than FRAME_MIN_ZOOM, or than the zoom it had
   * when that was lower. When no zoom down to that floor holds both cards, its source card, where
   * the connection starts, is kept by the least pan.
   *
   * A connection only one of whose cards was in view is kept by that card. That is how a Reveal
   * leaves one too far apart for FRAME_MIN_ZOOM (`frameEdge` centres on its source card); kept as
   * nothing, its source card would end under the pill or off the canvas when the sheet's new
   * height lands after the reveal.
   *
   * The zoom such a frame replaced is on loan (`lentZoom`). When the canvas grows again (the
   * sheet collapses, the window widens) and nothing else has changed the zoom, it is given back
   * (`returnZoom`). So a click on a connection with the sheet collapsed, which opens the sheet
   * and may zoom out to show both cards above it, down to compact detail, has the reader's zoom
   * again once the sheet is collapsed. Any growth gives it back to that connection while it is
   * kept with both cards in view, as far as the larger canvas holds them. Anything else selected
   * by then, or nothing, gets it back only once the canvas is as wide and as tall again as before
   * the shrink, so a window a few pixels wider, with the sheet that took the zoom still open,
   * leaves the zoom as it is. It comes whole, except to another connection kept with both cards
   * in view, which is framed as far as the canvas holds its two cards. What a frame leaves stays
   * on loan, and with that room back the next growth of any size gives it to whatever is
   * selected then.
   *
   * A far connection of the review walk is kept by the end the walk holds (its source
   * card, or the far card while the reader looks at it), together with the start of its line when
   * that was in view too (`FarView.kept`). The card comes first when the new canvas has no room
   * for both. When that end was not in view (the reader dragged away from it), the rules above
   * apply: the one card that was in view keeps the connection.
   */
  handleResize(): void {
    type Box = { x: number; y: number; w: number; h: number };
    const kept = this.host.keptTarget();
    const target = kept ? this.targetRect(kept) : null;
    const ends = kept && kept.kind === 'edge' ? this.endBoxes(kept.id) : null;
    const before = this.lastArea;
    const covered = this.lastCovered;
    const was = (r: Box): boolean => !!before && this.viewport.isVisible(r, before, covered);
    const held = kept && kept.kind === 'edge' ? this.far.kept(kept.id, was) : null;
    const latched = !!held && this.far.latched();
    // The end the walk holds keeps the connection while it was in view. A reader who has dragged
    // to the other card is kept by the card on the canvas, as on any connection.
    const far = held && (latched || was(held.box)) ? held : null;
    const seen = ends ? ends.filter(was) : [];
    const one = far ? far.box : seen.length === 1 ? seen[0] : null;
    const rect = one || target;
    const both = one ? null : ends;
    const parts: Box[] = both || (rect ? [rect] : []);
    const lent = this.lentZoom;
    const area = this.viewport.visibleArea();
    const grew = !!(lent && before && (area.w > before.w + 0.5 || area.h > before.h + 0.5));
    // The canvas has the width and the height again that the loan's shrink took.
    const regained = !!(lent && area.w >= lent.w - 0.5 && area.h >= lent.h - 0.5);
    const wasVisible = !!rect && parts.every(was);
    if (rect && wasVisible) {
      // Keep the picture (no refit) and take the new size as the one a fit would compare against.
      this.viewport.acceptResize();
      this.viewport.apply();
      const shown = () => parts.every((r) => this.viewport.isVisible(r));
      if (!shown()) this.viewport.revealRect(rect);
      if (both && !shown()) {
        const zoom = this.viewport.vp.zoom;
        const framed = this.framedZoom === zoom;
        if (!this.viewport.frameClear(rect, both, { floor: Math.min(zoom, FRAME_MIN_ZOOM) }) && !this.viewport.isVisible(both[0])) this.viewport.revealRect(both[0]);
        this.noteFramedZoom(zoom);
        const after = this.viewport.vp.zoom;
        if (after < zoom) this.lentZoom = lent ? { ...lent, to: after } : { from: zoom, to: after, framed, id: kept!.id, w: before!.w > area.w + 0.5 ? before!.w : 0, h: before!.h > area.h + 0.5 ? before!.h : 0 };
      } else if (lent && grew && (regained || (both && kept!.id === lent.id))) this.returnZoom(lent, rect, both);
    } else {
      this.viewport.onResize();
      if (lent && grew && regained) this.returnZoom(lent, null, null);
    }
    if (far && wasVisible && !this.far.inView(far.card)) this.viewport.revealRect(far.card);
    // An end the canvas could not show by the rule is shown as well as the new canvas can: again
    // on a larger canvas, which may have the room; where it stands on a smaller one.
    if (latched) this.far.relatch(!!before && (area.w > before.w + 0.5 || area.h > before.h + 0.5));
    this.syncShortCanvas();
  }

  /**
   * The canvas grew again while a zoom is on loan (`lentZoom`): give it back. A kept connection
   * with both cards in view is framed again (`frameClear`): at the zoom on loan when both cards
   * fit the canvas at it, clear of the phase index, whatever the margin (they did before the
   * canvas shrank); otherwise at the first zoom below it, down to the one on screen, at which they
   * fit with the frame's margin, and what the canvas does not allow yet stays on loan. Anything
   * else is zoomed about the canvas centre to the zoom on loan, and a kept card is then panned
   * back into view.
   */
  private returnZoom(lent: LentZoom, rect: { x: number; y: number; w: number; h: number } | null, ends: [LayoutBox, LayoutBox] | null): void {
    const zoom = this.viewport.vp.zoom;
    if (rect && ends) {
      const held = { ...this.viewport.vp };
      const framed = this.viewport.frameClear(rect, ends, { from: lent.from, floor: lent.from, margin: 0 }) || this.viewport.frameClear(rect, ends, { from: lent.from, floor: zoom });
      // No larger zoom shows both cards yet: the frame only centred them, so the picture stays.
      if (framed && this.viewport.vp.zoom <= zoom + 1e-9) this.viewport.set(held);
    } else {
      const { w, h } = this.viewport.visibleArea();
      const k = lent.from / zoom;
      this.viewport.set({ x: w / 2 - (w / 2 - this.viewport.vp.x) * k, y: h / 2 - (h / 2 - this.viewport.vp.y) * k, zoom: lent.from });
      if (rect && !this.viewport.isVisible(rect)) this.viewport.revealRect(rect);
    }
    const after = this.viewport.vp.zoom;
    const whole = after >= lent.from - 1e-9;
    this.lentZoom = whole ? null : { ...lent, to: after };
    this.framedZoom = whole && !lent.framed ? null : after;
  }

  /**
   * The bottom sheet opened, collapsed or was dragged to a new height. The canvas above
   * it changed height, which is not a reason to refit (the reader is reading a card): a fitted
   * viewport keeps its picture, and a selected target that was in view stays in view above the
   * sheet. A step is only panned. A connection whose two cards no longer fit above the sheet is
   * framed again at a lower zoom, and the sheet collapsing again gives the zoom it had back: whole
   * to a card or to nothing, and to a connection kept with both cards in view as far as the canvas
   * holds them (`handleResize`). Called synchronously by the App, so jsdom (no ResizeObserver) and
   * a real host agree; the observer's own call that follows finds nothing to do.
   */
  afterSheetToggle(): void {
    this.viewport.acceptResize();
    this.handleResize();
    this.lastArea = this.viewport.visibleArea();
    this.lastCovered = this.viewport.covered();
  }

  /**
   * The app changed chrome ABOVE the canvas after the first fit ran (the
   * authored header is built once the document is laid out), so a fitted
   * viewport is refitted to the canvas it really has.
   */
  afterChromeChange(): void {
    this.viewport.refitIfFitted();
    this.syncShortCanvas();
  }

  private renderEmptyState(): void {
    const existing = this.stateHost.querySelector('.mlv-state--empty');
    if (existing) this.stateHost.removeChild(existing);
    if (!this.index) return;
    const graph = this.index.graph;
    if (graph.nodes.length === 0) {
      this.stateHost.appendChild(buildEmptyState(graph));
    } else if (this.frameData && this.frameData.boxes.size === 0) {
      this.stateHost.appendChild(buildFilterEmptyState(() => this.host.clearFilters()));
    }
  }

  /* ── event wiring (canvas/wiring.ts) ───────────────────────────────── */

  private nodeWiring() {
    return {
      isGroup: (id: string) => !!this.index && this.index.isGroup(id),
      toggleCollapse: (id: string) => this.toggleCollapse(id),
      hoverIntent: (id: string | null) => this.emphasis.hoverIntent(id),
      activateNode: (id: string, ev?: MouseEvent) => this.host.activateNode(id, ev),
      openNode: (id: string, focusEditor: boolean) => this.host.openNode(id, focusEditor),
      addDisposer: (dispose: () => void) => this.disposers.push(dispose),
    };
  }

  private edgeWiring() {
    return {
      activateEdge: (id: string, ev?: MouseEvent) => this.host.activateEdge(id, ev),
      openEdge: (id: string, focusEditor: boolean) => this.host.openEdge(id, focusEditor),
      enterEdge: (route: RoutedEdge) => this.edgeHover.enter(route),
      leaveEdge: (route: RoutedEdge) => this.edgeHover.leave(route),
      syncBundles: () => this.syncBundles(),
      pulse: (route: RoutedEdge) => this.flow.pulse(route),
      stopFlow: () => this.flow.stop(),
    };
  }

  /* ── flow ──────────────────────────────────────────────── */

  /** Every route incident to `id` IN THE CURRENT PROJECTION. */
  incidentRoutes(id: string): RoutedEdge[] {
    return this.flow.incidentRoutes(id);
  }

  /** Move the DOM focus onto a connection's hit path. */
  focusEdge(id: string): boolean {
    return this.flow.focusEdge(id);
  }

  /**
   * `e` / Shift+E from the step `anchor`: when the place where the connection meets that step is
   * not on the canvas (the step is a group larger than it), pan the least distance that shows it
   * (`revealRect`), so the connection the keyboard is on starts on screen. Nothing moves when that
   * place is already there, nor when the step's card is wholly in view: the connection meets it
   * on its edge, which the least pan of a walk step or a resize leaves 16 px from the canvas edge,
   * nearer than the 24 px asked for around that place.
   */
  revealRouteEnd(route: RoutedEdge, anchor: string): void {
    const points = route.points;
    if (!points.length) return;
    const own = this.frameData ? this.frameData.boxes.get(anchor) : null;
    if (own && this.viewport.isVisible(own)) return;
    const p = route.source === anchor ? points[0] : points[points.length - 1];
    const m = 24 / this.viewport.vp.zoom;
    const box = { x: p.x - m, y: p.y - m, w: 2 * m, h: 2 * m };
    if (!this.viewport.isVisible(box)) this.viewport.revealRect(box);
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
   * A cross-lane trunk shows its individual strokes exactly while one of them
   * is hovered or focused, selected, lit, flowing or traced (`BUNDLE_ACTIVE_CLASSES`),
   * read off the cables themselves so this can never disagree with them.
   */
  syncBundles(): void {
    this.bundles.sync(this.edgeEls);
  }

  /* ── collapse, zoom, navigation ────────────────────────────────────── */

  /**
   * Collapse or expand a group, keeping its header anchored on screen. The scene is rebuilt, so a
   * card or group header that had the keyboard is focused again in the new one, as `refresh` does
   * (a step folded away hands it to its group's card), and the focus does not fall to the page
   * body. A folded group's card whose anchored corner is off the canvas or under the phase index
   * (the group was larger than the canvas and panned) is brought into view by the least pan. An
   * unfolded group stays anchored: it can be larger than the canvas.
   */
  toggleCollapse(id: string): void {
    if (!this.frameData) return;
    const before = this.frameData.boxes.get(id);
    const zoom = this.viewport.vp.zoom;
    const screen = before
      ? { x: before.x * zoom + this.viewport.vp.x, y: before.y * zoom + this.viewport.vp.y }
      : null;
    const doc = this.canvasEl.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    const inside = !!active && active !== this.canvasEl && this.canvasEl.contains(active) && typeof active.closest === 'function';
    const focused = inside ? active!.closest('[data-node-id]')?.getAttribute('data-node-id') || null : null;
    if (this.collapsedSet.has(id)) this.collapsedSet.delete(id);
    else this.collapsedSet.add(id);
    this.relayout();
    const after = this.frameData.boxes.get(id);
    if (after && screen) {
      this.viewport.set({
        x: screen.x - after.x * this.viewport.vp.zoom,
        y: screen.y - after.y * this.viewport.vp.zoom,
      });
      if (this.collapsedSet.has(id) && !this.viewport.isVisible(after)) this.viewport.revealRect(after);
    }
    const node = this.index ? this.index.nodeById.get(id) : null;
    const hidden = this.index ? this.index.descendantCount(id) : 0;
    this.host.afterCollapse();
    if (focused) this.focusTarget({ kind: 'node', id: focused });
    this.host.announce(
      'Group ' +
        (node ? node.label : id) +
        (this.collapsedSet.has(id) ? ' collapsed, ' + hidden + (hidden === 1 ? ' step' : ' steps') + ' hidden.' : ' expanded.'),
    );
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
    // A box larger than the canvas at this zoom (an expanded group) is aligned on its top-left
    // corner, where its header is, as a walk step aligns it (`revealRect`): centred, the header
    // that takes the focus would lie above the canvas.
    if (this.viewport.fitsAt(box, this.viewport.vp.zoom, 0)) this.viewport.centerOn(box);
    else this.viewport.revealRect(box);
    if (!pulse) return;
    const element = this.nodeEls.get(visible);
    if (!element) return;
    element.classList.add('is-pulse');
    setTimeout(() => element.classList.remove('is-pulse'), 700);
  }

  /**
   * Centre a node, and below the detail threshold (LOD_FULL_ZOOM) zoom in to
   * READABLE_ZOOM (or as far as the box still fits) first, so the card it
   * highlights is large enough to read.
   */
  revealNode(id: string, pulse: boolean): void {
    if (!this.index || !this.frameData) return;
    const box = this.frameData.boxes.get(this.index.visibleRepresentative(id, this.collapsedSet));
    if (!box) return;
    if (this.viewport.vp.zoom >= LOD_FULL_ZOOM) {
      this.centerOnNode(id, pulse);
      return;
    }
    this.viewport.centerOn(box, Math.max(this.viewport.vp.zoom, this.readableZoomFor(box)));
    if (pulse) this.pulseNode(this.index.visibleRepresentative(id, this.collapsedSet));
  }

  /**
   * Pan, never zoom, so the target lies in the visible area: a click that opens the bottom sheet
   * under the card it selected keeps that card in the canvas above it.
   */
  keepInView(target: { kind: 'node' | 'edge'; id: string }): void {
    const rect = this.targetRect(target);
    if (rect && !this.viewport.isVisible(rect)) this.viewport.centerOn(rect);
  }

  /**
   * Rebuild the scene for new marks (stale files) and give the keyboard back: a card,
   * group header or connection that had focus is focused again in the new DOM, so the diagram's
   * keys keep working.
   */
  refresh(sel: Sel | null): void {
    const doc = this.canvasEl.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    const inside = !!active && active !== this.canvasEl && this.canvasEl.contains(active) && typeof active.closest === 'function';
    const nodeId = inside ? active!.closest('[data-node-id]')?.getAttribute('data-node-id') || null : null;
    const edgeId = inside && !nodeId && active!.classList.contains('mlv-edge__hit') ? active!.closest('[data-edge-id]')?.getAttribute('data-edge-id') || null : null;
    this.render();
    this.applySelection(sel);
    let next: Element | null | undefined = null;
    if (nodeId) {
      const element = this.nodeEls.get(nodeId);
      next = element && element.classList.contains('mlv-group') ? element.querySelector('.mlv-group__header') : element;
    } else if (edgeId) {
      next = this.edgeEls.get(edgeId)?.querySelector('.mlv-edge__hit');
    }
    if (!next) return;
    try {
      // Never scroll the canvas (`focusSafely`).
      (next as HTMLElement).focus({ preventScroll: true });
    } catch (_e) {
      /* a detached scene cannot take focus */
    }
  }

  /**
   * Frame every step a finding cites and both ends of every connection it cites, also when it
   * cites steps, so a cited connection in another phase is on screen too. When all of it does not
   * fit at the frame's floor (FRAME_MIN_ZOOM), the cited steps alone are framed, the claim's
   * subject; when they do not fit either, `ViewportController.frameRect` centres on the first cited
   * step (with no step cited, on the first cited connection). The first cited step pulses.
   */
  frameIssue(id: string): void {
    if (!this.index || !this.frameData) return;
    const issue = this.index.issueById.get(id);
    if (!issue) return;
    type Box = { x: number; y: number; w: number; h: number };
    const steps: Box[] = [];
    const ends: Box[] = [];
    for (const nodeId of issue.nodeIds) {
      const rect = this.targetRect({ kind: 'node', id: nodeId });
      if (rect) steps.push(rect);
    }
    for (const edgeId of issue.edgeIds) {
      const rect = this.targetRect({ kind: 'edge', id: edgeId });
      if (rect) ends.push(rect);
    }
    const rects = steps.concat(ends);
    if (!rects.length) return;
    const unionOf = (list: Box[]): Box => {
      const x = Math.min(...list.map((r) => r.x));
      const y = Math.min(...list.map((r) => r.y));
      return { x, y, w: Math.max(...list.map((r) => r.x + r.w)) - x, h: Math.max(...list.map((r) => r.y + r.h)) - y };
    };
    const all = unionOf(rects);
    const target = !steps.length || !ends.length || this.viewport.fitsAt(all, FRAME_MIN_ZOOM) ? all : unionOf(steps);
    const before = this.viewport.vp.zoom;
    this.viewport.frameRect(target, rects[0], READABLE_ZOOM);
    this.noteFramedZoom(before);
    if (issue.nodeIds[0]) this.pulseNode(this.index.visibleRepresentative(issue.nodeIds[0], this.collapsedSet));
  }

  /**
   * A connection revealed from the code (Reveal in Diagram): frame both its ends as a finding's
   * cited cards are framed (`ViewportController.frameRect`). At full detail the zoom is kept when
   * they fit; otherwise it is the largest that fits them, at least FRAME_MIN_ZOOM and, below full
   * detail, at most READABLE_ZOOM; ends too far apart even at that floor centre on the source card,
   * where the connection starts. The source card is kept clear of the phase index. When either card
   * is still under the index or off the canvas, the frame zooms out from there (never below
   * FRAME_MIN_ZOOM) to the first zoom at which both cards fit on the canvas and clear of the index
   * (`ViewportController.frameClear`). It asks that each card be clear of the index, not their
   * whole union: a tall union can fit the canvas without fitting above the index or beside it.
   */
  frameEdge(id: string): void {
    if (!this.index || !this.frameData) return;
    const union = this.targetRect({ kind: 'edge', id });
    const ends = this.endBoxes(id);
    if (!union || !ends) return;
    const [source, target] = ends;
    this.viewport.frameRect(union, source, READABLE_ZOOM);
    if (this.viewport.isVisible(source) && this.viewport.isVisible(target)) return;
    this.viewport.frameClear(union, ends);
  }

  /** Bring a connection's two ends into view, zooming in when below the detail threshold. */
  revealEdge(id: string): void {
    const union = this.targetRect({ kind: 'edge', id });
    if (!union) return;
    if (this.viewport.vp.zoom < LOD_FULL_ZOOM) this.viewport.centerOn(union, Math.max(this.viewport.vp.zoom, this.readableZoomFor(union)));
    else if (!this.viewport.isVisible(union)) this.viewport.centerOn(union);
  }

  /**
   * A step of the review walk, and a step revealed without centring (`App.revealClaim`): below the
   * detail threshold, zoom to reading size on the step or the connection's two ends (`revealNode`,
   * `revealEdge`); at reading size, pan the least distance that shows it whole (`revealRect`), so
   * stepping through neighbours does not swing the picture to centre every card. The visible area
   * is the canvas above the bottom sheet.
   *
   * A connection and the phase index: when the least pan leaves one of its end cards under the
   * index, and their union fits the canvas at this zoom, it is framed as a Reveal frames it
   * (`frameClear`: centred, then the least pan that clears both cards, zooming out no further than
   * READABLE_MIN_ZOOM when no pan does). A union that does not fit the canvas at all is only
   * panned.
   *
   * The same holds for a connection reached from below the detail threshold (after a finding
   * framed under LOD_FULL_ZOOM, or a fit of the whole diagram): `revealEdge` centres its union at
   * reading size, and an end card that leaves under the index is cleared the same way. The floor
   * is the zoom the step landed at when that is under READABLE_MIN_ZOOM (a union that fits only
   * there), so such a step is panned, never zoomed out again.
   */
  revealTarget(target: { kind: 'node' | 'edge'; id: string }): void {
    const rect = this.targetRect(target);
    if (!rect) return;
    if (this.viewport.vp.zoom < LOD_FULL_ZOOM) {
      if (target.kind === 'node') this.revealNode(target.id, false);
      else {
        this.revealEdge(target.id);
        const cards = this.endBoxes(target.id);
        const zoom = this.viewport.vp.zoom;
        if (cards && !(this.viewport.isVisible(cards[0]) && this.viewport.isVisible(cards[1])) && this.viewport.fitsAt(rect, zoom, 0)) {
          this.viewport.frameClear(rect, cards, { floor: Math.min(zoom, READABLE_MIN_ZOOM), margin: 32 });
        }
      }
      return;
    }
    if (this.viewport.isVisible(rect)) return;
    this.viewport.revealRect(rect);
    const ends = target.kind === 'edge' ? this.endBoxes(target.id) : null;
    if (!ends || (this.viewport.isVisible(ends[0]) && this.viewport.isVisible(ends[1]))) return;
    if (this.viewport.fitsAt(rect, this.viewport.vp.zoom, 0)) this.viewport.frameClear(rect, ends, { floor: READABLE_MIN_ZOOM, margin: 32 });
  }

  /**
   * A step of the review walk onto a step or a connection (`revealTarget`). A finding's frame can
   * zoom out as far as FRAME_MIN_ZOOM to show its cited cards. A walk that kept any zoom at full
   * detail would leave every later claim at the zoom such a frame chose, between LOD_FULL_ZOOM and
   * READABLE_MIN_ZOOM, until the reader zoomed in. So when the zoom lies in that band and the
   * viewer chose it (a finding's frame, or a walk step onto a claim too large for reading size:
   * `framedZoom`), the step first zooms back about the canvas centre to READABLE_ZOOM, or only as
   * far as the claim still fits (`readableZoomFor`), so a connection's two cards stay whole, then
   * pans the least distance. A zoom the reader set is kept. Below LOD_FULL_ZOOM `revealTarget`
   * zooms in itself. The layout tool's walk replay follows the same rule (`walkStep` in
   * webview/tools/layout-metrics.mjs).
   *
   * A connection whose two cards cannot both be shown at the step's zoom keeps its source card in
   * view (`FarView.step`), and so does one that `revealTarget` leaves with an end card under the
   * phase index or off the canvas (`FarView.afterReveal`).
   */
  walkTarget(target: { kind: 'node' | 'edge'; id: string }): void {
    const before = this.viewport.vp.zoom;
    this.far.clear();
    if (target.kind === 'edge' && this.far.step(target.id)) {
      this.noteFramedZoom(before);
      return;
    }
    const rect = this.targetRect(target);
    if (rect && before === this.framedZoom && before >= LOD_FULL_ZOOM && before < READABLE_MIN_ZOOM) {
      const zoom = Math.max(before, this.readableZoomFor(rect));
      if (zoom > before) {
        const { w, h } = this.viewport.visibleArea();
        this.viewport.zoomAt(zoom / before, w / 2, h / 2);
      }
    }
    this.revealTarget(target);
    if (target.kind === 'edge') this.far.afterReveal(target.id);
    this.noteFramedZoom(before);
  }

  /**
   * Called after one of the viewer's own moves (a finding's frame, a walk step, a resize's frame, a
   * move of `FarView`) that started at zoom `before`. A zoom the move changed is the viewer's
   * choice; one it kept stays the viewer's only when it was before.
   */
  private noteFramedZoom(before: number): void {
    const after = this.viewport.vp.zoom;
    if (after !== before) this.framedZoom = after;
    else if (this.framedZoom !== before) this.framedZoom = null;
  }

  /** The zoom on screen when the viewer chose it, else null (`framedZoom`; saved as `ViewState.framedZoom`). */
  get viewerZoom(): number | null {
    return this.framedZoom;
  }

  /** A remount restored a viewport whose zoom the viewer had chosen (`ViewState.framedZoom`). */
  restoreFramedZoom(zoom: number): void {
    this.framedZoom = zoom === this.viewport.vp.zoom ? zoom : null;
  }

  /** The laid-out boxes of a connection's two drawn ends (a collapsed group's card for a hidden end), source first. */
  private endBoxes(id: string): [LayoutBox, LayoutBox] | null {
    if (!this.index || !this.frameData) return null;
    const edge = this.index.edgeById.get(id);
    if (!edge) return null;
    const a = this.frameData.boxes.get(this.index.visibleRepresentative(edge.source, this.collapsedSet));
    const b = this.frameData.boxes.get(this.index.visibleRepresentative(edge.target, this.collapsedSet));
    return a && b ? [a, b] : null;
  }

  /** The laid-out rect of a node's visible card, or of both ends of a connection. */
  private targetRect(target: { kind: 'node' | 'edge'; id: string }): { x: number; y: number; w: number; h: number } | null {
    if (!this.index || !this.frameData) return null;
    if (target.kind === 'node') return this.frameData.boxes.get(this.index.visibleRepresentative(target.id, this.collapsedSet)) || null;
    const edge = this.index.edgeById.get(target.id);
    if (!edge) return null;
    const a = this.frameData.boxes.get(this.index.visibleRepresentative(edge.source, this.collapsedSet));
    const b = this.frameData.boxes.get(this.index.visibleRepresentative(edge.target, this.collapsedSet));
    if (!a || !b) return null;
    const x = Math.min(a.x, b.x);
    const y = Math.min(a.y, b.y);
    return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
  }

  /**
   * READABLE_ZOOM, or less when the box would not fit the visible area at it. The margin shrinks
   * with a short canvas above an open sheet, so a card still lands at full detail there.
   */
  private readableZoomFor(box: { w: number; h: number }): number {
    const area = this.viewport.visibleArea();
    const margin = Math.min(48, Math.round(Math.min(area.w, area.h) / 10));
    const fits = Math.min((area.w - margin) / Math.max(1, box.w), (area.h - margin) / Math.max(1, box.h));
    return Math.min(READABLE_ZOOM, fits);
  }

  private pulseNode(id: string): void {
    const element = this.nodeEls.get(id);
    if (!element) return;
    element.classList.add('is-pulse');
    setTimeout(() => element.classList.remove('is-pulse'), 700);
  }

  zoomStep(dir: number): void {
    const size = this.viewport.size();
    this.viewport.zoomAt(dir > 0 ? 1.2 : 1 / 1.2, size.w / 2, size.h / 2);
  }

  /** The readable view (key 0 and the first paint): see `ViewportController.fit`. */
  fit(): void {
    this.viewport.fit();
  }

  /** The whole document, groups as they are (the ... menu's "Fit the whole diagram"). */
  fitWhole(): void {
    this.viewport.fitWhole();
  }

  zoomToNode(id: string): void {
    if (!this.index || !this.frameData) return;
    const box = this.frameData.boxes.get(this.index.visibleRepresentative(id, this.collapsedSet));
    if (box) this.viewport.zoomToBox(box);
  }

  /**
   * The card an arrow key selects from `sel`. From a step: the next card that way, in spatial
   * sibling order (`nextBox`), counted from its drawn card (the collapsed group around it, if any).
   * From a connection, the one of its two cards that lies further that way (`connectionEnd`); from
   * a finding, as from the step the diagram marks for it (its first cited step), else as from its
   * first cited connection. Only with nothing to start from (no selection, or a finding that cites
   * neither) is it the diagram's first card: a selected connection or finding starts from its own
   * cards.
   */
  nextSelection(sel: Sel | null, key: string): NextSelection | null {
    const index = this.index;
    const frame = this.frameData;
    if (!index || !frame) return null;
    const drawn = (id: string): string | null => (index.nodeById.has(id) ? index.visibleRepresentative(id, this.collapsedSet) : null);
    const fromStep = (id: string): LayoutBox | null | undefined => {
      const card = drawn(id);
      return card && frame.boxes.has(card) ? nextBox(index, frame, card, key) : undefined;
    };
    const fromEdge = (id: string): LayoutBox | null | undefined => {
      const edge = index.edgeById.get(id);
      return edge ? connectionEnd(frame, drawn(edge.source), drawn(edge.target), key) || undefined : undefined;
    };
    let next: LayoutBox | null | undefined;
    if (sel && sel.kind === 'node') next = fromStep(sel.id);
    else if (sel && sel.kind === 'edge') next = fromEdge(sel.id);
    else if (sel && sel.kind === 'issue') {
      const issue = index.issueById.get(sel.id);
      if (issue && issue.nodeIds.length) next = fromStep(issue.nodeIds[0]);
      if (next === undefined && issue && issue.edgeIds.length) next = fromEdge(issue.edgeIds[0]);
    }
    // `undefined`: nothing to count from, so the first card. `null`: no card further that way.
    if (next === undefined) next = firstBox(frame);
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
    this.phaseIndex.destroy();
    this.overview.destroy();
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
