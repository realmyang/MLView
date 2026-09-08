/**
 * Edge hover: which cable the pointer owns, and when that becomes a gesture.
 *
 * Two jobs, deliberately separated from the canvas view because both grew with
 * Feature 1 and neither has anything to do with pan, zoom, collapse or layout:
 *
 *  1. ARBITRATION. `.mlv-edge__hit` is a 12 px transparent stroke over the
 *     route, and edges sharing a gutter are drawn on top of one another, so DOM
 *     hit-testing hands the whole shared run to whichever `<g>` is last in
 *     document order — five of the shipped sample's connections owned none of
 *     their own pixels (MLV-R1-FLOW-006). The owner is therefore resolved from
 *     the route polylines (`render/edgepick.ts`), and the winner is raised so
 *     the DOM agrees with the geometry for as long as the pointer tracks it.
 *  2. INTENT. The same 400 ms open / 120 ms close delays the hover card uses.
 *     Nothing is ever built before the pointer settles, which is what keeps a
 *     sweep across the diagram free (`interaction.test.mjs`, F1-A11).
 */

import { on } from '../dom.js';
import { nearestRoute } from './edgepick.js';
import { prefersReducedMotion } from '../motion.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { ViewportController } from './canvas.js';

/**
 * How close, in SCREEN px, the pointer must come to a cable for that cable to
 * own it. Wider than the 12 px hit stroke buys nothing; narrower makes a thin
 * edge hard to catch.
 */
export const EDGE_PICK_PX = 10;

/** Anything on this list owns its own pixels outright; cables never win there. */
const OPAQUE = '.mlv-node, .mlv-group, .mlv-minimap, .mlv-zoom, .mlv-tooltip, .mlv-toasts, .mlv-state';

export interface EdgeHoverHost {
  canvas: HTMLElement;
  viewport: ViewportController;
  routes(): RoutedEdge[];
  edges(): Map<string, SVGElement>;
  /** The pointer settled on a cable: show its card and run the charge. */
  open(route: RoutedEdge): void;
  /** The pointer settled on nothing: hide and stop, honouring the latches. */
  close(): void;
  openDelayMs: number;
  closeDelayMs: number;
}

export class EdgeHover {
  private host: EdgeHoverHost;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private currentId: string | null = null;

  constructor(host: EdgeHoverHost) {
    this.host = host;
  }

  /** The cable the pointer owns right now, or null. */
  get hoveredId(): string | null {
    return this.currentId;
  }

  /** Bind the canvas-level arbitration. Returns its disposer. */
  wire(): () => void {
    return on(this.host.canvas, 'pointermove', (ev: PointerEvent) => this.resolve(ev));
  }

  /** A hit path took the pointer. The resolver may still overrule it. */
  enter(route: RoutedEdge): void {
    this.set(route);
  }

  /** Only the cable that OWNS the pointer gives it up. */
  leave(route: RoutedEdge): void {
    if (this.currentId === route.id) this.set(null);
  }

  /**
   * The scene DOM was replaced: nothing is hovered, and a pending callback must
   * not fire — it holds a route from the scene that just went away, whose
   * geometry is no longer what is drawn.
   */
  reset(): void {
    this.currentId = null;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  destroy(): void {
    this.reset();
  }

  private resolve(ev: PointerEvent): void {
    const routes = this.host.routes();
    if (!routes.length) return;
    if (this.host.canvas.classList.contains('is-panning')) return;
    const target = ev.target as HTMLElement | null;
    if (target && typeof target.closest === 'function' && target.closest(OPAQUE)) {
      if (this.currentId) this.set(null);
      return;
    }
    const rect = this.host.canvas.getBoundingClientRect();
    const vp = this.host.viewport.vp;
    const zoom = vp.zoom > 0 ? vp.zoom : 1;
    const point = { x: (ev.clientX - rect.left - vp.x) / zoom, y: (ev.clientY - rect.top - vp.y) / zoom };
    this.set(nearestRoute(routes, point, EDGE_PICK_PX / zoom));
  }

  /** The one place `.is-hover` moves between cables. Idempotent per edge id. */
  private set(route: RoutedEdge | null): void {
    const id = route ? route.id : null;
    if (this.currentId === id) return;
    const edges = this.host.edges();
    if (this.currentId) {
      const previous = edges.get(this.currentId);
      if (previous) previous.classList.remove('is-hover');
    }
    this.currentId = id;
    if (route) {
      const g = edges.get(route.id);
      if (g) {
        g.classList.add('is-hover');
        // Raise it, so the cable the user is on is also the one the DOM hands
        // the next pointer event to. Guarded: re-appending an element that is
        // already last would re-enter this on every move.
        const parent = g.parentNode;
        if (parent && parent.lastChild !== g) parent.appendChild(g);
      }
    }
    this.intent(route);
  }

  /** The hover-card delays, so nothing opens on the way past. */
  private intent(route: RoutedEdge | null): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const run = () => {
      if (route) this.host.open(route);
      else this.host.close();
    };
    const delay = prefersReducedMotion() ? 0 : route ? this.host.openDelayMs : this.host.closeDelayMs;
    if (delay <= 0) {
      run();
      return;
    }
    this.timer = setTimeout(() => {
      this.timer = null;
      run();
    }, delay);
  }
}
