/**
 * Viewport control: pan by dragging the background, zoom by wheel or buttons,
 * the readable first view, fit, zoom-to-selection, and the minimap. Zoom writes
 * at most one attribute (data-lod) and one bucketed custom property (--mlv-z)
 * per frame, so no component re-renders and nothing is laid out again while
 * zooming (R4.3).
 */

import { svg, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { stampPhase } from './phase.js';
import type { Viewport } from '../types.js';

export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 2.5;

/**
 * The largest zoom a whole-document fit opens at: a two-card document is not blown up to fill a
 * wide panel.
 */
export const MAX_FIT_ZOOM = 1.2;

export interface FitPlan {
  zoom: number;
}

/**
 * The zoom that fits the WHOLE document, as a pure function of the two rectangles, so a gate can
 * state it without a DOM and the viewer and the gate can never drift (VIEW-01).
 *
 * Viewer M2: this used to be the first paint too, with a "tall" branch that opened a deep
 * document top-anchored at between 0.5 and 1.75 screens of height (VIEW-01). The first paint is
 * now `readablePlan`, which reads this as its whole-document case, so the tall branch, its
 * TALL_SCREENS bound and its MIN_FIT_ZOOM floor (0.5) are gone.
 */
export function fitPlan(contentW: number, contentH: number, w: number, h: number, padding = 24): FitPlan {
  const zw = (w - padding * 2) / Math.max(1, contentW);
  const zh = (h - padding * 2) / Math.max(1, contentH);
  return { zoom: clamp(Math.min(zw, zh), MIN_ZOOM, MAX_FIT_ZOOM) };
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The zoom at which cards switch to full detail (`data-lod`, UX_DESIGN 4.5). */
export const LOD_FULL_ZOOM = 0.62;

/**
 * Viewer M2: the zoom steps `--mlv-z` is written at. The stylesheet divides by it to keep a few
 * marks the same size on screen at every zoom — the inferred / unresolved tags, the exception
 * dashes and a 1 px floor on connection strokes — so an exception stays visible zoomed out.
 * Quantised so a wheel zoom restyles those marks only when it crosses a step (about 25% apart),
 * never on every frame.
 */
export const ZOOM_BUCKETS = [0.15, 0.2, 0.25, 0.32, 0.4, 0.5, 0.62, 0.8, 1, 1.25, 1.6, 2, 2.5];

/**
 * The bucket nearest `zoom` on a log scale, as `--mlv-z` holds it: a constant-size mark is then
 * within about 12% of its intended screen size at any zoom (the buckets are about 25% apart).
 */
export function zoomBucket(zoom: number): number {
  if (!(zoom > 0)) return 1;
  let best = ZOOM_BUCKETS[0];
  let gap = Infinity;
  for (const bucket of ZOOM_BUCKETS) {
    const d = Math.abs(Math.log(zoom / bucket));
    if (d < gap - 1e-9) {
      gap = d;
      best = bucket;
    }
  }
  return best;
}

/**
 * The zoom a selection from the rail lands at when the diagram is below the
 * detail threshold (Campaign 3, issue 6): card titles at about 12 px, edge
 * labels and `file:line` drawn.
 */
export const READABLE_ZOOM = 0.9;

/**
 * Viewer M2: phase 1 is fitted whole, rather than opened at READABLE_ZOOM, when it fits at this
 * zoom or more: titles are still about 10 px on screen (13 px x 0.75) and the reader sees where
 * the first phase ends.
 */
export const PHASE_FIT_MIN_ZOOM = 0.75;

/** The part of a laid-out frame the readable plan reads: its size and its phase lanes. */
export interface ReadableFrame {
  width: number;
  height: number;
  /** The phase lanes in document order; the first is phase 1. */
  lanes: ReadonlyArray<{ x: number; y: number; w: number; h: number }>;
  /** The left routing channel's width, before the first lane (0 or absent when there is none). */
  channelW?: number;
}

/** How the readable plan opened the document. */
export type ReadableMode = 'whole' | 'phase-fit' | 'phase-anchor';

export interface ReadablePlan {
  zoom: number;
  /** The viewport translation, in canvas pixels, as `Viewport.x` / `Viewport.y` hold it. */
  x: number;
  y: number;
  mode: ReadableMode;
}

/**
 * Viewer M2: the first view, as a pure function of the frame and the canvas size, so a test can
 * state it without a DOM. Readable, or the whole document; never the in-between thumbnail.
 *
 * - The whole document, centred, when it fits at LOD_FULL_ZOOM (0.62) or more.
 * - Otherwise phase 1, anchored at its top-left with the left routing channel (the trunks that
 *   leave phase 1 for later phases start there): fitted whole when that zoom is
 *   PHASE_FIT_MIN_ZOOM (0.75) or more, never above READABLE_ZOOM; else at READABLE_ZOOM (0.9),
 *   where a 13 px title is 11.7 px on screen.
 *
 * A document narrower (or shorter) than the canvas at that zoom is centred on that axis instead,
 * as a fit always placed it. With no lane to anchor on, the whole document is fitted.
 */
export function readablePlan(frame: ReadableFrame, w: number, h: number, padding = 24): ReadablePlan {
  const contentW = Math.max(1, frame.width);
  const contentH = Math.max(1, frame.height);
  const whole = fitPlan(contentW, contentH, w, h, padding).zoom;
  const lane = frame.lanes.length ? frame.lanes[0] : null;
  if (whole >= LOD_FULL_ZOOM || !lane) {
    return { zoom: whole, x: (w - contentW * whole) / 2, y: Math.max(padding, (h - contentH * whole) / 2), mode: 'whole' };
  }
  const left = lane.x - Math.max(0, frame.channelW || 0);
  const rectW = Math.max(1, lane.x + lane.w - left);
  const rectH = Math.max(1, lane.h);
  const fits = Math.min((w - padding * 2) / rectW, (h - padding * 2) / rectH);
  const phaseFit = fits >= PHASE_FIT_MIN_ZOOM;
  const zoom = clamp(phaseFit ? Math.min(fits, READABLE_ZOOM) : READABLE_ZOOM, MIN_ZOOM, MAX_ZOOM);
  const x = contentW * zoom <= w ? (w - contentW * zoom) / 2 : padding - left * zoom;
  const y = contentH * zoom <= h ? (h - contentH * zoom) / 2 : padding - lane.y * zoom;
  return { zoom, x, y, mode: phaseFit ? 'phase-fit' : 'phase-anchor' };
}

/**
 * A resize this large, in either dimension, refits a viewport the reader has
 * not moved since the last fit (issue 6): the panel opening narrow beside the
 * artifact editor and then being widened, a side bar closing, the header
 * disclosure opening. Smaller changes (a scrollbar, a one-pixel settle) keep
 * the picture where it is.
 */
export const REFIT_MIN_PX = 80;
export const REFIT_MIN_RATIO = 0.1;

/**
 * Viewer M2: the zoom bounds a finding's frame stays within (`frameRect`): never so far out that
 * the cited cards are unreadable shapes, never blown up past their natural size.
 */
export const FRAME_MIN_ZOOM = 0.45;
export const FRAME_MAX_ZOOM = 1;

export class ViewportController {
  readonly canvas: HTMLElement;
  readonly world: HTMLElement;
  vp: Viewport = { x: 0, y: 0, zoom: 1 };
  contentW = 1;
  contentH = 1;
  private onChange: (vp: Viewport) => void;
  private lod = 'full';
  /** The `--mlv-z` bucket last written onto the canvas (viewer M2). */
  private zBucket = 0;
  /**
   * True while the transform is exactly what the last fit produced — nothing
   * the reader did (pan, zoom, a jump, a restored viewport) has moved it since.
   * Only such a viewport is refitted on resize, with the same kind of fit
   * (issue 6).
   */
  private fitted = false;
  /** The canvas size the last fit was computed for, and which fit it was (readable or whole). */
  private fitSize: { w: number; h: number; whole: boolean; padding: number } | null = null;
  /** The frame the readable plan anchors on (viewer M2); null before the first layout. */
  private frame: ReadableFrame | null = null;
  constructor(canvas: HTMLElement, world: HTMLElement, onChange: (vp: Viewport) => void) {
    this.canvas = canvas;
    this.world = world;
    this.onChange = onChange;
  }

  setContent(w: number, h: number, frame: ReadableFrame | null = null): void {
    this.contentW = Math.max(1, w);
    this.contentH = Math.max(1, h);
    this.frame = frame;
  }

  apply(): void {
    const { x, y, zoom } = this.vp;
    this.world.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + zoom + ')';
    const lod = zoom < LOD_FULL_ZOOM ? 'compact' : 'full';
    if (lod !== this.lod) {
      this.lod = lod;
      this.canvas.setAttribute('data-lod', lod);
    }
    const bucket = zoomBucket(zoom);
    if (bucket !== this.zBucket) {
      this.zBucket = bucket;
      this.canvas.style.setProperty('--mlv-z', String(bucket));
    }
    this.onChange(this.vp);
  }

  set(vp: Partial<Viewport>): void {
    this.fitted = false;
    if (typeof vp.x === 'number' && isFinite(vp.x)) this.vp.x = vp.x;
    if (typeof vp.y === 'number' && isFinite(vp.y)) this.vp.y = vp.y;
    if (typeof vp.zoom === 'number' && isFinite(vp.zoom)) this.vp.zoom = clamp(vp.zoom, MIN_ZOOM, MAX_ZOOM);
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.fitted = false;
    this.vp.x += dx;
    this.vp.y += dy;
    this.apply();
  }

  /** Zoom about a point in canvas-local coordinates. */
  zoomAt(factor: number, px: number, py: number): void {
    this.fitted = false;
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
   * Viewer M2: the readable first view (`readablePlan`), for the first paint and
   * key 0. The whole document when it fits at full detail; otherwise phase 1 at
   * a zoom where card titles can be read (11.7 px at READABLE_ZOOM), anchored
   * top-left. It replaces the top-anchored "tall" fit, which opened the vit and
   * yolov5 shakedown documents at 39-48 % (4.7-5.8 px titles) at 900 and 1440 px
   * and at 17-23 % (2.1-2.7 px) beside the code at 541 px. The whole document is
   * `fitWhole()`, the toolbar's "Fit the whole diagram"; Overview (Shift+0)
   * folds the groups first.
   *
   * Key 0 always means this view, from any zoom. Before M2 a reader below the
   * old floor (50 %) who pressed Fit got the whole document instead
   * (HOSTS-UX-FITZOOM), because a control named "Fit to view" that zooms IN
   * shows less; that control is now named for what it does, and fits the whole.
   */
  fit(padding = 24): void {
    this.applyFit(padding, false);
  }

  /**
   * Fit the WHOLE document, centred (VIEW-10 Overview, and the toolbar's "Fit
   * the whole diagram" since viewer M2). Overview folds every group to its card
   * first and then asks for the picture a reviewer can paste, which is by
   * definition the whole document.
   */
  fitWhole(padding = 24): void {
    this.applyFit(padding, true);
  }

  private applyFit(padding: number, whole: boolean): void {
    const { w, h } = this.size();
    if (whole || !this.frame) {
      const { zoom } = fitPlan(this.contentW, this.contentH, w, h, padding);
      this.vp.zoom = zoom;
      this.vp.x = (w - this.contentW * zoom) / 2;
      this.vp.y = Math.max(padding, (h - this.contentH * zoom) / 2);
    } else {
      const plan = readablePlan(this.frame, w, h, padding);
      this.vp.zoom = plan.zoom;
      this.vp.x = plan.x;
      this.vp.y = plan.y;
    }
    this.fitted = true;
    this.fitSize = { w, h, whole, padding };
    this.apply();
  }

  /** True while nothing has moved the viewport since the last fit. */
  get isFitted(): boolean {
    return this.fitted;
  }

  /**
   * Re-run the last fit for the canvas's CURRENT size, if the reader has not
   * moved the viewport since and the size changed at all. Used after the app
   * adds chrome above the canvas once the first fit has already run (the
   * authored header is built after the document is laid out).
   */
  refitIfFitted(): boolean {
    if (!this.fitted || !this.fitSize) return false;
    const { w, h } = this.size();
    if (w === this.fitSize.w && h === this.fitSize.h) return false;
    this.applyFit(this.fitSize.padding, this.fitSize.whole);
    return true;
  }

  /**
   * A resized canvas (issue 6). A fitted viewport is refitted when the size
   * changed by at least REFIT_MIN_PX and REFIT_MIN_RATIO in either dimension;
   * anything else only refreshes the derived chrome (zoom readout, minimap
   * rectangle) without moving what the reader is looking at.
   */
  onResize(): boolean {
    if (this.fitted && this.fitSize) {
      const { w, h } = this.size();
      const dw = Math.abs(w - this.fitSize.w);
      const dh = Math.abs(h - this.fitSize.h);
      const large = (dw >= REFIT_MIN_PX && dw >= this.fitSize.w * REFIT_MIN_RATIO) || (dh >= REFIT_MIN_PX && dh >= this.fitSize.h * REFIT_MIN_RATIO);
      if (large) {
        this.applyFit(this.fitSize.padding, this.fitSize.whole);
        return true;
      }
    }
    this.apply();
    return false;
  }

  /**
   * The part of the canvas a reveal can use. Viewer M2: the whole canvas. The drawer that lay over
   * its right side below 900 px (Campaign 3 review, VL-1) is gone; the bottom sheet that replaced
   * it sits under the canvas and shrinks it, so the canvas IS the area above the sheet.
   */
  visibleArea(): { w: number; h: number } {
    return this.size();
  }

  /**
   * Viewer M2: the canvas changed size for a reason that is not a new picture (the bottom sheet
   * opened or collapsed under it). A fitted viewport stays fitted but takes this size as the one it
   * was fitted for, so the resize that follows does not refit (and move) the diagram the reader is
   * reading.
   */
  acceptResize(): void {
    if (!this.fitted || !this.fitSize) return;
    const { w, h } = this.size();
    this.fitSize = { ...this.fitSize, w, h };
  }

  /**
   * Viewer M2: bring a rectangle (a finding's cited cards) into view. At full detail the zoom is
   * kept when the rectangle fits and it is only centred; otherwise the zoom is the largest that
   * fits it, at most `readable` (READABLE_ZOOM) below full detail and FRAME_MAX_ZOOM above, and at
   * least FRAME_MIN_ZOOM. A rectangle too large even at that floor is centred on `anchor` (the first
   * cited card), so the reader starts where the finding starts.
   */
  /** Whether `rect` fits the visible area at `zoom` or more, with the frame's margin (`frameRect`). */
  fitsAt(rect: Rect, zoom: number, margin = 48): boolean {
    const { w, h } = this.visibleArea();
    return Math.min((w - margin) / Math.max(1, rect.w), (h - margin) / Math.max(1, rect.h)) >= zoom;
  }

  frameRect(rect: Rect, anchor: Rect, readable: number, margin = 48): void {
    const { w, h } = this.visibleArea();
    const fits = Math.min((w - margin) / Math.max(1, rect.w), (h - margin) / Math.max(1, rect.h));
    const zoom = this.vp.zoom;
    if (zoom >= LOD_FULL_ZOOM && fits >= zoom) {
      this.centerOn(rect);
      return;
    }
    const ceiling = zoom >= LOD_FULL_ZOOM ? Math.max(FRAME_MAX_ZOOM, zoom) : readable;
    const next = Math.max(FRAME_MIN_ZOOM, Math.min(ceiling, fits));
    this.centerOn(fits >= FRAME_MIN_ZOOM ? rect : anchor, next);
  }

  centerOn(rect: Rect, zoom?: number): void {
    this.fitted = false;
    const { w, h } = this.visibleArea();
    if (typeof zoom === 'number') this.vp.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const z = this.vp.zoom;
    this.vp.x = w / 2 - (rect.x + rect.w / 2) * z;
    this.vp.y = h / 2 - (rect.y + rect.h / 2) * z;
    this.apply();
  }

  /**
   * Viewer M2 live fix: pan the least distance that puts `rect` wholly inside the visible area,
   * keeping the zoom, with `margin` px to spare on the side it comes in from (less when the area is
   * barely larger than the rect). A rect larger than the area is aligned on its top or left edge,
   * where a card's title is. Nothing moves when it is already wholly inside.
   */
  revealRect(rect: Rect, margin = 16): void {
    const { w, h } = this.visibleArea();
    const z = this.vp.zoom;
    const shift = (start: number, size: number, extent: number): number => {
      const pad = Math.max(0, Math.min(margin, (extent - size) / 2));
      if (size > extent) return -start;
      if (start < 0) return pad - start;
      if (start + size > extent) return extent - pad - (start + size);
      return 0;
    };
    const dx = shift(rect.x * z + this.vp.x, rect.w * z, w);
    const dy = shift(rect.y * z + this.vp.y, rect.h * z, h);
    if (dx || dy) this.panBy(dx, dy);
  }

  zoomToBox(rect: Rect, padding = 80): void {
    const { w, h } = this.visibleArea();
    const z = clamp(Math.min((w - padding) / Math.max(rect.w, 1), (h - padding) / Math.max(rect.h, 1)), MIN_ZOOM, MAX_ZOOM);
    this.centerOn(rect, z);
  }

  /** True when the rect is fully inside the visible area (by default the current one). */
  isVisible(rect: Rect, area: { w: number; h: number } = this.visibleArea()): boolean {
    const { w, h } = area;
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
  /** Viewer M2: the phase's document position, the key of its colour. */
  phase?: number;
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
    // VIEW-12. The minimap is a DUPLICATE of a canvas that is already fully
    // navigable — one focus stop, `aria-activedescendant` roving, a live region
    // announcing every selection — so it is hidden from assistive tech rather
    // than described twice.
    this.root.setAttribute('aria-hidden', 'true');
    // The widget sits on top of live diagram, so it must be dismissable
    // (UX_DESIGN section 1: "collapsible to a 28 px chevron tab") — MLV-R2-W12.
    this.toggleBtn = iconButton('mlv-btn mlv-btn--icon mlv-minimap__toggle', 'Collapse minimap');
    this.toggleBtn.appendChild(uiIcon('chevron', 12));
    this.toggleBtn.setAttribute('aria-expanded', 'true');
    // ...and an `aria-hidden` subtree may not hold a tab stop, so this chevron
    // is the POINTER affordance only. The keyboard's copy of it is the labelled
    // "Minimap" toggle in the toolbar, which is before the canvas in DOM order
    // instead of the tab stop after it that this button used to be (VIEW-12).
    this.toggleBtn.tabIndex = -1;
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
      if (d.phase !== undefined) stampPhase(r, d.phase);
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
