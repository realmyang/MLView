/**
 * The flow BINDING — when a charge runs, and what the user is told about it.
 *
 * `render/flow.ts` decides WHAT is drawn on an edge. This decides WHEN, which is
 * a different job with different state: the pulse a selection latches, the
 * stream focus mode latches, the card the pointer is still resting on, the DOM
 * focus a connection holds, and the one message the viewer owes the user when a
 * lineage is too dense to animate.
 *
 * It was lifted out of `canvasview.ts` because that file had grown past the
 * ~600-line bar and because burying this bookkeeping among pan, zoom, collapse
 * and minimap is what let a whole latch rung go missing (MLV-R1-FLOW-005: a
 * click on the card you were already hovering killed the running stream, since
 * `stop()` knew about the selection and focus-mode latches but not about the
 * hover the user had just spent 400 ms earning).
 *
 * The stop cascade is the heart of it and reads top to bottom:
 *   selected edge -> focus-mode lock -> the card still under the pointer -> off.
 */

import { FlowController, FLOW } from './flow.js';
import { MotionWatcher } from '../motion.js';
import type { MotionMode } from '../motion.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { GraphIndex } from '../layout/model.js';
import type { TraceReach } from './trace.js';

/** Everything the flow needs from the canvas view, and nothing more. */
export interface FlowBindingHost {
  canvas: HTMLElement;
  edges(): Map<string, SVGElement>;
  nodes(): Map<string, HTMLElement>;
  routes(): RoutedEdge[];
  index(): GraphIndex | null;
  /** The card the pointer has settled on, or null (interaction table row 5). */
  hoverNodeId(): string | null;
  /** The node whose lineage stream focus mode has latched, or null (row 7). */
  lockedNodeId(): string | null;
  /** The cable the pointer owns right now, or null — the cascade's last rung. */
  hoverEdgeId(): string | null;
  toast(text: string): void;
}

/**
 * The capped-trace copy (CONTRACTS 11.14 C5). The message that says nothing will
 * animate is also the message that says how to get the animation back. Without it
 * the headline gesture of Feature 1 simply stops working on any real repo, silently.
 * Viewer M2 removed the scope picker, so the remedy for a long lineage is a single
 * connection (hovered, or walked with `e`), as it always was for a busy card.
 */
export function cappedTraceMessage(edges: number, motion: MotionMode = 'full', reach: TraceReach = 'lineage'): string {
  // A hover streams only the card's own connections, so its copy names the
  // card. The remedy is the single-connection hover, which pulses any drawn
  // cable (11.14 C3).
  if (reach === 'direct') {
    const lead = 'This card has ' + edges + ' connections, ';
    return motion === 'reduced'
      ? lead + 'more than the ' + FLOW.MAX_EDGES + ' that can be marked at once. Hover a single connection to see its direction.'
      : lead + 'past the ' + FLOW.MAX_EDGES + ' the animation can carry. Hover a single connection to see its flow.';
  }
  // "298 of 120 connections" is a subset construction, and it read as a bug at
  // exactly the moment the feature stopped working (R2-FLOW-06). And under
  // `reduce` nothing was ever going to animate, so the copy names what that
  // reader actually loses — the per-edge marks — rather than the animation
  // (R2-FLOW-03 / R2-FLOW-07).
  if (motion === 'reduced') {
    return (
      'This lineage has ' +
      edges +
      ' connections, more than the ' +
      FLOW.MAX_EDGES +
      ' that can be marked at once. Hover a single connection, or walk them with e, to see each direction.'
    );
  }
  return (
    'This lineage has ' +
    edges +
    ' connections, past the ' +
    FLOW.MAX_EDGES +
    ' the animation can carry. Hover a single connection, or walk them with e, to see each flow.'
  );
}

export class FlowBinding {
  readonly controller: FlowController;
  private host: FlowBindingHost;
  private motionWatch: MotionWatcher;
  /** The edge whose pulse is LATCHED by the selection (interaction row 4). */
  private latchedEdgeId: string | null = null;
  /**
   * The node and reach the capped message was last raised for; a sweep may not
   * spam it. The reach is part of the key because a hover and focus mode on the
   * same card quote different counts.
   */
  private cappedKey: string | null = null;

  constructor(host: FlowBindingHost) {
    this.host = host;
    this.controller = new FlowController({
      canvas: host.canvas,
      edges: () => host.edges(),
      nodes: () => host.nodes(),
      routes: () => host.routes(),
      // Composition rule C2 limited streams to a projection's core; viewer M2 removed projections.
      streamEligible: () => true,
    });
    // Re-read the preference when the OS flips it mid-session: the charge must
    // stop being BUILT, not merely be frozen by the blanket clamp (11.13 rule 3).
    //
    // …and then whatever was running has to be REBUILT in the new mode, which is
    // the `stop()` below (R3-CHG-02). `setMotion` only ever clears, exactly as
    // `setEnabled` does, so a flip to `reduce` used to strip a SELECTED or
    // KEYBOARD-FOCUSED connection of its charge AND of the ports and chevron that
    // are supposed to replace it: a connection visibly emphasised, holding DOM
    // focus, with no direction cue at all — the one state MLV-R1-FLOW-011 says
    // cannot exist — and it was handed to the single reader with no animation to
    // fall back on. Flipping back did not restore it either; only a fresh hover
    // did. `stop()` walks selected edge -> focus lock -> hovered card -> hovered
    // cable and re-runs whichever rung is live, and `decorate()` draws the static
    // substitute for the new mode, so one line covers both directions.
    //
    // The capped-message memo is dropped with it: the copy differs per mode
    // (`cappedTraceMessage`), so the reader must be told what THEY lose now.
    this.motionWatch = new MotionWatcher((mode) => {
      this.controller.setMotion(mode);
      this.controller.syncCanvas();
      this.cappedKey = null;
      this.stop();
    });
    this.controller.setMotion(this.motionWatch.mode);
    this.controller.syncCanvas();
  }

  /* ── the host protocol app.ts already speaks ───────────────────────── */

  get enabled(): boolean {
    return this.controller.enabled;
  }

  get motion(): MotionMode {
    return this.controller.motion;
  }

  /**
   * Turning the layer back on must restore the flow the pointer or the latches
   * already own. `setEnabled` only CLEARS, and the hover-intent timer fired long
   * ago, so re-enabling left a cable holding `.is-hover` with no charge until the
   * pointer left and came back — the feature reading as broken (R2-FLOW-08).
   * This is the same class of miss as MLV-R1-FLOW-005, and the same cascade
   * fixes it: `stop()` re-establishes whatever rung is live.
   */
  setEnabled(on: boolean): void {
    this.controller.setEnabled(on);
    if (on) this.stop();
  }

  syncCanvas(): void {
    this.controller.syncCanvas();
  }

  /** Idempotent, and the only thing the re-projection path needs (11.14 C1). */
  clear(): void {
    this.cappedKey = null;
    this.controller.clear();
  }

  /* ── running a flow ────────────────────────────────────────────────── */

  /** One charge along one cable. Any DRAWN edge qualifies (11.14 C3). */
  pulse(route: RoutedEdge): void {
    this.controller.pulse(route);
  }

  /**
   * Viewer M2 (Shift+A): run the flow on screen again. A flow settles after two passes so nothing
   * moves while the reader reads; this restarts it from its first pass. False when nothing is lit,
   * the layer is off, or motion is reduced (there is no motion to replay).
   */
  replay(): boolean {
    return this.controller.replay();
  }

  /**
   * A stream — a hovered card's direct routes, or a focused node's lineage —
   * plus the one thing the animation cannot say for itself: that it was
   * suppressed for density and that scoping brings it back.
   */
  stream(nodeId: string, reach: TraceReach): void {
    const result = this.controller.stream(nodeId, reach);
    if (!result.capped) return;
    const key = reach + ':' + nodeId;
    if (this.cappedKey === key) return; // a hover sweep may not spam it
    this.cappedKey = key;
    this.host.toast(cappedTraceMessage(result.edges, this.controller.motion, reach));
  }

  /**
   * The pointer left, or the focus did. Three latches outrank "stop", in this
   * order, and only when all three are absent does the layer go dark:
   *
   *  1. a SELECTED edge keeps its pulse with the pointer anywhere (row 4);
   *  2. focus mode keeps its lineage stream, so a pipeline can be read at
   *     leisure (row 7);
   *  3. the card the pointer is STILL resting on keeps its direct stream —
   *     clicking the card you are hovering must not extinguish the hover you
   *     already earned (row 8 asks that a click start no flow, not that it
   *     stop one);
   *  4. the CABLE the pointer is still resting on keeps its pulse, which is what
   *     lets the toolbar toggle restore a live hover (R2-FLOW-08). It is last so
   *     no earlier rung's behaviour moves; a hover CLOSE has already released the
   *     cable before it calls `stop()`, so this rung cannot resurrect one.
   */
  stop(): void {
    if (this.latchedEdgeId) {
      const route = this.routeById(this.latchedEdgeId);
      if (route) {
        this.controller.pulse(route);
        return;
      }
    }
    const locked = this.host.lockedNodeId();
    if (locked) {
      this.stream(locked, 'lineage');
      return;
    }
    const hovered = this.host.hoverNodeId();
    if (hovered) {
      this.stream(hovered, 'direct');
      return;
    }
    const cable = this.host.hoverEdgeId();
    if (cable) {
      const route = this.routeById(cable);
      if (route) {
        this.controller.pulse(route);
        return;
      }
    }
    this.controller.clear();
  }

  /** Selecting an edge latches its pulse; selecting anything else drops it. */
  setLatchedEdge(id: string | null): void {
    this.latchedEdgeId = id;
  }

  /* ── the keyboard's view of a connection ───────────────────────────── */

  routeById(id: string): RoutedEdge | null {
    for (const route of this.host.routes()) {
      if (route.id === id) return route;
    }
    return null;
  }

  /** Every route incident to `id` IN THE CURRENT PROJECTION (11.14 C4). */
  incidentRoutes(id: string): RoutedEdge[] {
    return this.host.routes().filter((r) => r.source === id || r.target === id);
  }

  /** Move the DOM focus onto a connection's hit path. */
  focusEdge(id: string): boolean {
    const g = this.host.edges().get(id);
    if (!g) return false;
    const hit = g.querySelector('.mlv-edge__hit') as unknown as HTMLElement | null;
    if (!hit || typeof hit.focus !== 'function') return false;
    try {
      hit.focus();
    } catch (_e) {
      return false;
    }
    return true;
  }

  /**
   * Take DOM focus OFF a connection, if it holds it.
   *
   * The Escape cascade clears the selection rung, which drops the latch — but
   * focus stayed on the hit path, so the edge kept `.is-hover` while losing
   * every port and charge: a connection visibly emphasised, holding focus, with
   * no direction cue at all — the one state the interaction table says cannot
   * exist (MLV-R1-FLOW-011). Blurring lets the existing `blur` handler clean
   * both up together.
   */
  blurFocusedEdge(): boolean {
    const doc = this.host.canvas.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    if (!active || !active.classList || !active.classList.contains('mlv-edge__hit')) return false;
    if (typeof active.blur !== 'function') return false;
    active.blur();
    return true;
  }

  /** "Connection: A to B, label" — what the live region says on `e`. */
  edgeAnnouncement(route: RoutedEdge): string {
    const index = this.host.index();
    const src = index ? index.nodeById.get(route.source) : null;
    const dst = index ? index.nodeById.get(route.target) : null;
    const from = src ? src.label || src.qualname : route.source;
    const to = dst ? dst.label || dst.qualname : route.target;
    return 'Connection: ' + from + ' to ' + to + (route.label ? ', ' + route.label : '') + '.';
  }

  destroy(): void {
    this.motionWatch.destroy();
  }
}
