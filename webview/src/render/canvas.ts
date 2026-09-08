/**
 * Viewport control: pan by dragging the background, zoom by wheel or buttons,
 * fit, zoom-to-selection, and the minimap. Zoom writes ONE attribute per frame
 * (data-lod) so no component re-renders while zooming (R4.3).
 */

import { svg, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import type { Viewport } from '../types.js';

export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 2.5;

/**
 * How many canvas-heights of document a top-anchored `fit()` may open (VIEW-01).
 *
 * The tall branch used to be a pure width fit, so the demo — 45 nodes when this
 * was measured, before the ANA-1/2/3 re-baseline — opened at 0.756 in a 1240x848
 * canvas with 22 of its 45 cards and 3 of its 7 lanes below the fold, and `fit()`
 * was a measured no-op, because it chose exactly the transform the viewer had
 * already mounted with. Bounding that width fit to one and three-quarter screens
 * of height opened the same document at 0.575 — 27 of the 45 cards and 5 of the 7
 * lanes, measured in Chromium at 1600x1000. The re-baselined demo is 54 nodes in
 * a 1576x2630 world and opens at 0.548 there, 0.5 at 1280x800;
 * `test/measure_geometry.mjs` re-measures any document against the same plan.
 */
export const TALL_SCREENS = 1.75;

/**
 * The zoom a first paint never goes below (VIEW-01).
 *
 * Not a legibility threshold — `data-lod` already concedes at 0.62 that cards
 * below it are read as shapes rather than text. It is the point where a card
 * stops being a recognisable object at all: at the 0.15 floor the 300-node
 * project used to land on, a 216x72 card is 32x11 px, which is smaller than the
 * severity glyph drawn on it. Opening a document smaller than this buys no
 * information, so a document too deep for TALL_SCREENS opens here and is read
 * by panning instead.
 */
export const MIN_FIT_ZOOM = 0.5;

export interface FitPlan {
  zoom: number;
  /** True when the document was opened top-anchored rather than whole. */
  tall: boolean;
}

/**
 * The zoom `fit()` will choose, as a pure function of the two rectangles — so a
 * gate can state the first-paint geometry of a document without a DOM, and the
 * viewer and the gate can never drift (VIEW-01).
 */
export function fitPlan(
  contentW: number,
  contentH: number,
  w: number,
  h: number,
  padding = 24,
  projected = false,
): FitPlan {
  const zw = (w - padding * 2) / Math.max(1, contentW);
  const zh = (h - padding * 2) / Math.max(1, contentH);
  const tall = !projected && zh < zw * 0.6 && zh < 0.6;
  const bounded = Math.min(zw, Math.max(zh * TALL_SCREENS, MIN_FIT_ZOOM));
  return { zoom: clamp(tall ? Math.min(bounded, 1) : Math.min(zw, zh), MIN_ZOOM, 1.2), tall };
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export class ViewportController {
  readonly canvas: HTMLElement;
  readonly world: HTMLElement;
  vp: Viewport = { x: 0, y: 0, zoom: 1 };
  contentW = 1;
  contentH = 1;
  private onChange: (vp: Viewport) => void;
  private lod = 'full';
  /** True while the document is a PROJECTION (`graph.view` present). */
  private projected = false;

  constructor(canvas: HTMLElement, world: HTMLElement, onChange: (vp: Viewport) => void) {
    this.canvas = canvas;
    this.world = world;
    this.onChange = onChange;
  }

  setContent(w: number, h: number): void {
    this.contentW = Math.max(1, w);
    this.contentH = Math.max(1, h);
  }

  /**
   * A scoped document fits WHOLE (MLV-R3-001). The tall-scene branch in `fit`
   * was written for the whole-workspace pipeline, which really is far taller
   * than it is wide; a scope is small by construction, so the same branch merely
   * opened a report scoped to `concern:evaluation` with the evaluation lane 351
   * px below the last visible pixel — a scope that does not show its subject.
   */
  setProjected(projected: boolean): void {
    this.projected = projected;
  }

  apply(): void {
    const { x, y, zoom } = this.vp;
    this.world.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + zoom + ')';
    const lod = zoom < 0.62 ? 'compact' : 'full';
    if (lod !== this.lod) {
      this.lod = lod;
      this.canvas.setAttribute('data-lod', lod);
    }
    this.onChange(this.vp);
  }

  set(vp: Partial<Viewport>): void {
    if (typeof vp.x === 'number' && isFinite(vp.x)) this.vp.x = vp.x;
    if (typeof vp.y === 'number' && isFinite(vp.y)) this.vp.y = vp.y;
    if (typeof vp.zoom === 'number' && isFinite(vp.zoom)) this.vp.zoom = clamp(vp.zoom, MIN_ZOOM, MAX_ZOOM);
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.vp.x += dx;
    this.vp.y += dy;
    this.apply();
  }

  /** Zoom about a point in canvas-local coordinates. */
  zoomAt(factor: number, px: number, py: number): void {
    const next = clamp(this.vp.zoom * factor, MIN_ZOOM, MAX_ZOOM);
    const k = next / this.vp.zoom;
    this.vp.x = px - (px - this.vp.x) * k;
    this.vp.y = py - (py - this.vp.y) * k;
    this.vp.zoom = next;
    this.apply();
  }

  size(): { w: number; h: number } {
    const r = this.canvas.getBoundingClientRect();
    const w = r.width || this.canvas.clientWidth || 1200;
    const h = r.height || this.canvas.clientHeight || 800;
    return { w, h };
  }

  /**
   * Fit the document. A pipeline is naturally much taller than it is wide, and
   * scaling its full height into a wide panel lands at the zoom floor with the
   * card text at 3 px and 80 % of the canvas empty (MLV-R1-002). So when the
   * height-bound fit would be both far tighter than the width-bound one and
   * illegible on its own, anchor at the top and let the user pan down — which is
   * how a swimlane diagram is read anyway.
   *
   * That branch used to fit the WIDTH outright, which on the demo as it stood
   * before the re-baseline (45 nodes) meant zoom 0.756, 22 of the 45 cards and 3
   * of the 7 lanes below the fold, and a Fit button that changed nothing
   * (VIEW-01). It is now bounded: never more than
   * TALL_SCREENS canvas-heights of document, never under MIN_FIT_ZOOM, and never
   * wider than the document itself — so a deeper document opens smaller until a
   * card would stop being a recognisable object, and then stops.
   *
   * A PROJECTION never takes that branch: the user asked for one part of the
   * pipeline, and the answer must open showing it (MLV-R3-001).
   */
  fit(padding = 24): void {
    this.applyFit(padding, false);
  }

  /**
   * Fit the WHOLE document, never top-anchored (VIEW-10 Overview).
   *
   * Overview mode folds every group to its card and then asks for the picture a
   * reviewer can paste — which is by definition the whole document. Routing it
   * through `fit()` handed it the `tall` branch: the folded demo is still much
   * taller than it is wide, so `Shift+0` opened top-anchored at 0.837 with
   * `CrossEntropyLoss`, `train()` and `validate()` entirely below the fold at
   * 1440x900 — it zoomed IN, and clipped the one picture the feature exists to
   * produce. The `tall` branch is deliberate for a first paint (MLV-R3-001) and
   * is untouched here; it is simply not what "fit everything" means, exactly as
   * a projection already opts out of it through `setProjected`.
   */
  fitWhole(padding = 24): void {
    this.applyFit(padding, true);
  }

  private applyFit(padding: number, whole: boolean): void {
    const { w, h } = this.size();
    const { zoom, tall } = fitPlan(this.contentW, this.contentH, w, h, padding, this.projected || whole);
    this.vp.zoom = zoom;
    this.vp.x = (w - this.contentW * zoom) / 2;
    this.vp.y = tall ? padding : Math.max(padding, (h - this.contentH * zoom) / 2);
    this.apply();
  }

  centerOn(rect: Rect, zoom?: number): void {
    const { w, h } = this.size();
    if (typeof zoom === 'number') this.vp.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const z = this.vp.zoom;
    this.vp.x = w / 2 - (rect.x + rect.w / 2) * z;
    this.vp.y = h / 2 - (rect.y + rect.h / 2) * z;
    this.apply();
  }

  zoomToBox(rect: Rect, padding = 80): void {
    const { w, h } = this.size();
    const z = clamp(Math.min((w - padding) / Math.max(rect.w, 1), (h - padding) / Math.max(rect.h, 1)), MIN_ZOOM, MAX_ZOOM);
    this.centerOn(rect, z);
  }

  /** True when the rect is fully inside the visible area. */
  isVisible(rect: Rect): boolean {
    const { w, h } = this.size();
    const x = rect.x * this.vp.zoom + this.vp.x;
    const y = rect.y * this.vp.zoom + this.vp.y;
    return x >= 0 && y >= 0 && x + rect.w * this.vp.zoom <= w && y + rect.h * this.vp.zoom <= h;
  }
}

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

export interface MinimapDot {
  x: number;
  y: number;
  w: number;
  h: number;
  stage: string;
  severity: string | null;
}

/**
 * The minimap's drawing transform: a uniform letterboxed fit, CENTRED in the
 * widget. Drawing, the viewport rectangle and click-to-jump all go through this
 * one object — they used to disagree, so a click landed nowhere near the dot
 * under the cursor (MLV-R1-008).
 */
export interface MinimapFit {
  scale: number;
  ox: number;
  oy: number;
  w: number;
  h: number;
  contentW: number;
  contentH: number;
}

export function minimapFit(w: number, h: number, contentW: number, contentH: number): MinimapFit {
  const cw = Math.max(1, contentW);
  const ch = Math.max(1, contentH);
  const scale = Math.min(w / cw, h / ch);
  return { scale, ox: (w - cw * scale) / 2, oy: (h - ch * scale) / 2, w, h, contentW: cw, contentH: ch };
}

/** Widget coordinates (viewBox units) -> world coordinates, clamped to content. */
export function minimapToWorld(fit: MinimapFit, vx: number, vy: number): { x: number; y: number } {
  return {
    x: clamp((vx - fit.ox) / fit.scale, 0, fit.contentW),
    y: clamp((vy - fit.oy) / fit.scale, 0, fit.contentH),
  };
}

/** World coordinates -> widget coordinates. The inverse of minimapToWorld. */
export function minimapFromWorld(fit: MinimapFit, x: number, y: number): { x: number; y: number } {
  return { x: fit.ox + x * fit.scale, y: fit.oy + y * fit.scale };
}

export class Minimap {
  readonly root: HTMLElement;
  private svgEl: SVGElement;
  private nodesG: SVGElement;
  private viewRect: SVGElement;
  private toggleBtn: HTMLButtonElement;
  private collapsedState = false;
  private w = 200;
  private h = 130;
  private fit: MinimapFit = minimapFit(200, 130, 1, 1);

  constructor(onJump: (x: number, y: number) => void, onToggle?: (collapsed: boolean) => void) {
    this.root = el('div', 'mlv-minimap');
    // The widget sits on top of live diagram, so it must be dismissable
    // (UX_DESIGN section 1: "collapsible to a 28 px chevron tab") — MLV-R2-W12.
    this.toggleBtn = iconButton('mlv-btn mlv-btn--icon mlv-minimap__toggle', 'Collapse minimap');
    this.toggleBtn.appendChild(uiIcon('chevron', 12));
    this.toggleBtn.setAttribute('aria-expanded', 'true');
    on(this.toggleBtn, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.setCollapsed(!this.collapsedState);
      if (onToggle) onToggle(this.collapsedState);
    });
    this.root.appendChild(this.toggleBtn);
    this.svgEl = svg('svg', { class: 'mlv-minimap__svg', viewBox: '0 0 200 130', 'aria-hidden': 'true' });
    this.nodesG = svg('g');
    this.viewRect = svg('rect', { class: 'mlv-minimap__view', x: 0, y: 0, width: 0, height: 0, rx: 2 });
    this.svgEl.appendChild(this.nodesG);
    this.svgEl.appendChild(this.viewRect);
    this.root.appendChild(this.svgEl);
    this.svgEl.addEventListener('pointerdown', (ev: Event) => {
      const e = ev as PointerEvent;
      const box = (this.svgEl as unknown as HTMLElement).getBoundingClientRect();
      // The widget is drawn in viewBox units; convert the click into those units
      // first, then invert the SAME transform the dots were drawn with.
      const vx = box.width ? ((e.clientX - box.left) / box.width) * this.w : 0;
      const vy = box.height ? ((e.clientY - box.top) / box.height) * this.h : 0;
      const world = minimapToWorld(this.fit, vx, vy);
      onJump(world.x, world.y);
    });
  }

  get collapsed(): boolean {
    return this.collapsedState;
  }

  setCollapsed(next: boolean): void {
    this.collapsedState = next;
    if (next) this.root.classList.add('is-collapsed');
    else this.root.classList.remove('is-collapsed');
    this.toggleBtn.setAttribute('aria-expanded', next ? 'false' : 'true');
    const label = next ? 'Expand minimap' : 'Collapse minimap';
    this.toggleBtn.title = label;
    this.toggleBtn.setAttribute('aria-label', label);
  }

  render(dots: MinimapDot[], contentW: number, contentH: number): void {
    this.fit = minimapFit(this.w, this.h, contentW, contentH);
    const { scale, ox, oy } = this.fit;
    while (this.nodesG.firstChild) this.nodesG.removeChild(this.nodesG.firstChild);
    for (const d of dots) {
      const r = svg('rect', {
        class: 'mlv-minimap__node' + (d.severity ? ' mlv-minimap__node--issue' : ''),
        x: round2(ox + d.x * scale),
        y: round2(oy + d.y * scale),
        width: round2(Math.max(2, d.w * scale)),
        height: round2(Math.max(2, d.h * scale)),
        rx: 1,
      });
      r.setAttribute('data-stage', d.stage);
      if (d.severity) r.setAttribute('data-sev', d.severity);
      this.nodesG.appendChild(r);
    }
  }

  setViewport(vp: Viewport, viewW: number, viewH: number): void {
    const { scale, ox, oy } = this.fit;
    const topLeft = minimapFromWorld(this.fit, -vp.x / vp.zoom, -vp.y / vp.zoom);
    const w = (viewW / vp.zoom) * scale;
    const h = (viewH / vp.zoom) * scale;
    const x = clamp(topLeft.x, ox, ox + this.fit.contentW * scale);
    const y = clamp(topLeft.y, oy, oy + this.fit.contentH * scale);
    this.viewRect.setAttribute('x', String(round2(x)));
    this.viewRect.setAttribute('y', String(round2(y)));
    this.viewRect.setAttribute('width', String(round2(Math.max(0, Math.min(w, ox + this.fit.contentW * scale - x)))));
    this.viewRect.setAttribute('height', String(round2(Math.max(0, Math.min(h, oy + this.fit.contentH * scale - y)))));
  }
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}
