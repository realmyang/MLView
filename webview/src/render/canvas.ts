/**
 * Viewport control: pan by dragging the background, zoom by wheel or buttons,
 * the readable first view, fit, zoom-to-selection, and (viewer M3) the move to a phase and the
 * part of the canvas the phase index covers. Zoom writes
 * at most one attribute (data-lod) and one bucketed custom property (--mlv-z)
 * per frame, so no component re-renders and nothing is laid out again while
 * zooming (R4.3).
 */

import { motionMode } from '../motion.js';
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
 * Viewer M3: how long a move to a phase takes (the phase overview's blocks, the phase index's
 * rows). Instant under VS Code's Reduce Motion, the OS setting or VS Code's screen-reader mode
 * (`motionMode`).
 */
export const VIEW_ANIMATION_MS = 240;

/**
 * Viewer M3: the view of phase `k` (its position among the lanes) at reading size, as a pure
 * function of the frame and the canvas size, for the phase overview and the phase index. The rule
 * is the readable plan's for phase 1: the lane (with the left routing channel, where the trunks
 * that leave or enter it run) fitted whole when that zoom is PHASE_FIT_MIN_ZOOM (0.75) or more,
 * capped at READABLE_ZOOM (0.9); otherwise READABLE_ZOOM anchored at its top-left. A document
 * narrower (or shorter) than the canvas at that zoom is centred on that axis. A lane that fits is
 * never left with empty canvas under the end of the document: the view stops where the world ends.
 */
export function phasePlan(frame: ReadableFrame, k: number, w: number, h: number, padding = 24): ReadablePlan | null {
  const lane = frame.lanes[k];
  if (!lane) return null;
  const contentW = Math.max(1, frame.width);
  const contentH = Math.max(1, frame.height);
  const left = lane.x - Math.max(0, frame.channelW || 0);
  const rectW = Math.max(1, lane.x + lane.w - left);
  const rectH = Math.max(1, lane.h);
  const fits = Math.min((w - padding * 2) / rectW, (h - padding * 2) / rectH);
  const phaseFit = fits >= PHASE_FIT_MIN_ZOOM;
  const zoom = clamp(phaseFit ? Math.min(fits, READABLE_ZOOM) : READABLE_ZOOM, MIN_ZOOM, MAX_ZOOM);
  const x = contentW * zoom <= w ? (w - contentW * zoom) / 2 : padding - left * zoom;
  let y: number;
  if (contentH * zoom <= h) y = (h - contentH * zoom) / 2;
  else {
    y = padding - lane.y * zoom;
    // The last phases: keep the end of the world at the foot of the canvas when the lane fits.
    const floor = h - padding - contentH * zoom;
    if (rectH * zoom + 2 * padding <= h && y < floor) y = floor;
  }
  return { zoom, x, y, mode: phaseFit ? 'phase-fit' : 'phase-anchor' };
}

/** True when two rectangles overlap (touching edges do not). */
export function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/**
 * Viewer M3: the least pan that moves a screen rectangle `r` (canvas pixels) off `covered` while
 * keeping it inside a `w` x `h` canvas: to the left of it, above it, to its right or below it,
 * whichever is shortest, with `gap` px to spare. Null when it is already clear, or when no such pan
 * keeps it inside the canvas (a card wider and taller than the room around the phase index).
 */
export function clearOf(r: Rect, covered: Rect, w: number, h: number, gap = 8): { dx: number; dy: number } | null {
  if (!rectsOverlap(r, covered)) return null;
  const options: Array<{ dx: number; dy: number }> = [];
  const left = covered.x - gap - (r.x + r.w);
  if (r.x + left >= 0) options.push({ dx: left, dy: 0 });
  const up = covered.y - gap - (r.y + r.h);
  if (r.y + up >= 0) options.push({ dx: 0, dy: up });
  const right = covered.x + covered.w + gap - r.x;
  if (r.x + r.w + right <= w) options.push({ dx: right, dy: 0 });
  const down = covered.y + covered.h + gap - r.y;
  if (r.y + r.h + down <= h) options.push({ dx: 0, dy: down });
  if (!options.length) return null;
  options.sort((p, q) => Math.abs(p.dx) + Math.abs(p.dy) - (Math.abs(q.dx) + Math.abs(q.dy)));
  return options[0];
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
  /**
   * Viewer M3: the part of the canvas an overlay covers (the phase index), in canvas pixels, read
   * when it is needed. Reveals, centring and the visibility test keep a target out of it.
   */
  private coveredFn: (() => Rect | null) | null = null;
  /** Viewer M3: bumped by every move, so a running animation stops as soon as anything else moves the view. */
  private animToken = 0;
  /** The token of the animation in flight, 0 when none is. */
  private animLive = 0;
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
    this.animToken++;
    this.fitted = false;
    if (typeof vp.x === 'number' && isFinite(vp.x)) this.vp.x = vp.x;
    if (typeof vp.y === 'number' && isFinite(vp.y)) this.vp.y = vp.y;
    if (typeof vp.zoom === 'number' && isFinite(vp.zoom)) this.vp.zoom = clamp(vp.zoom, MIN_ZOOM, MAX_ZOOM);
    this.apply();
  }

  panBy(dx: number, dy: number): void {
    this.animToken++;
    this.fitted = false;
    this.vp.x += dx;
    this.vp.y += dy;
    this.apply();
  }

  /** Zoom about a point in canvas-local coordinates. */
  zoomAt(factor: number, px: number, py: number): void {
    this.animToken++;
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
    this.animToken++;
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
   * anything else only refreshes the derived chrome (zoom readout, the phase
   * index's in-view marks) without moving what the reader is looking at.
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
      this.keepClear(anchor);
      return;
    }
    const ceiling = zoom >= LOD_FULL_ZOOM ? Math.max(FRAME_MAX_ZOOM, zoom) : readable;
    const next = Math.max(FRAME_MIN_ZOOM, Math.min(ceiling, fits));
    this.centerOn(fits >= FRAME_MIN_ZOOM ? rect : anchor, next);
    this.keepClear(anchor);
  }

  /**
   * Viewer M3: a frame too large to move off the phase index as a whole (`centerOn` leaves it) still
   * keeps its anchor, the first cited card, out from under the index: the least pan off it.
   */
  private keepClear(anchor: Rect): void {
    const covered = this.covered();
    if (!covered) return;
    const { w, h } = this.visibleArea();
    const z = this.vp.zoom;
    const shift = clearOf({ x: anchor.x * z + this.vp.x, y: anchor.y * z + this.vp.y, w: anchor.w * z, h: anchor.h * z }, covered, w, h);
    if (shift) this.panBy(shift.dx, shift.dy);
  }

  centerOn(rect: Rect, zoom?: number): void {
    this.animToken++;
    this.fitted = false;
    const { w, h } = this.visibleArea();
    if (typeof zoom === 'number') this.vp.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const z = this.vp.zoom;
    this.vp.x = w / 2 - (rect.x + rect.w / 2) * z;
    this.vp.y = h / 2 - (rect.y + rect.h / 2) * z;
    // Viewer M3: a centred target the phase index would cover moves the least distance off it.
    const covered = this.covered();
    if (covered) {
      const shift = clearOf({ x: rect.x * z + this.vp.x, y: rect.y * z + this.vp.y, w: rect.w * z, h: rect.h * z }, covered, w, h);
      if (shift) {
        this.vp.x += shift.dx;
        this.vp.y += shift.dy;
      }
    }
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
    let dx = shift(rect.x * z + this.vp.x, rect.w * z, w);
    let dy = shift(rect.y * z + this.vp.y, rect.h * z, h);
    // Viewer M3: and off the part of the canvas the phase index covers, the least distance again.
    const covered = this.covered();
    if (covered) {
      const off = clearOf({ x: rect.x * z + this.vp.x + dx, y: rect.y * z + this.vp.y + dy, w: rect.w * z, h: rect.h * z }, covered, w, h, Math.min(margin, 8));
      if (off) {
        dx += off.dx;
        dy += off.dy;
      }
    }
    if (dx || dy) this.panBy(dx, dy);
  }

  zoomToBox(rect: Rect, padding = 80): void {
    const { w, h } = this.visibleArea();
    const z = clamp(Math.min((w - padding) / Math.max(rect.w, 1), (h - padding) / Math.max(rect.h, 1)), MIN_ZOOM, MAX_ZOOM);
    this.centerOn(rect, z);
  }

  /**
   * True when the rect is fully inside the visible area (by default the current one). Viewer M3: and
   * not under the phase index, so a card the index covers counts as out of view and is revealed.
   */
  isVisible(rect: Rect, area: { w: number; h: number } = this.visibleArea()): boolean {
    const { w, h } = area;
    const x = rect.x * this.vp.zoom + this.vp.x;
    const y = rect.y * this.vp.zoom + this.vp.y;
    const sw = rect.w * this.vp.zoom;
    const sh = rect.h * this.vp.zoom;
    if (!(x >= 0 && y >= 0 && x + sw <= w && y + sh <= h)) return false;
    const covered = this.covered();
    return !covered || !rectsOverlap({ x, y, w: sw, h: sh }, covered);
  }

  /** Viewer M3: say what part of the canvas is covered (the phase index), read on demand. */
  setCovered(fn: (() => Rect | null) | null): void {
    this.coveredFn = fn;
  }

  /** The covered part of the canvas now, or null. */
  covered(): Rect | null {
    if (!this.coveredFn) return null;
    try {
      const r = this.coveredFn();
      return r && r.w > 0 && r.h > 0 ? r : null;
    } catch (_e) {
      return null;
    }
  }

  /**
   * Viewer M3: move to `target` over VIEW_ANIMATION_MS (the move to a phase), or at once under
   * reduced motion (VS Code's Reduce Motion, the OS setting, VS Code's screen-reader mode) or where
   * there is no animation frame. The point at the canvas centre travels in a straight line while
   * the zoom changes on a log scale, eased out. Any other move (a pan, a wheel, a key, a reveal)
   * stops it where it is. Returns once the move is set up; `done` runs when it lands (not when it
   * is stopped).
   */
  animateTo(target: Viewport, ms = VIEW_ANIMATION_MS, done?: () => void): void {
    const token = ++this.animToken;
    this.fitted = false;
    const to: Viewport = { x: target.x, y: target.y, zoom: clamp(target.zoom, MIN_ZOOM, MAX_ZOOM) };
    const raf = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function' ? window.requestAnimationFrame.bind(window) : null;
    const land = () => {
      this.animLive = 0;
      this.vp = { ...to };
      this.apply();
      if (done) done();
    };
    if (!raf || !(ms > 0) || motionMode() === 'reduced') {
      land();
      return;
    }
    const from: Viewport = { ...this.vp };
    const { w, h } = this.size();
    const c0 = { x: (w / 2 - from.x) / from.zoom, y: (h / 2 - from.y) / from.zoom };
    const c1 = { x: (w / 2 - to.x) / to.zoom, y: (h / 2 - to.y) / to.zoom };
    const start = Date.now();
    this.animLive = token;
    const frame = () => {
      if (token !== this.animToken) return;
      const t = Math.min(1, (Date.now() - start) / ms);
      if (t >= 1) {
        land();
        return;
      }
      const e = 1 - Math.pow(1 - t, 3);
      const z = from.zoom * Math.pow(to.zoom / from.zoom, e);
      this.vp = { x: w / 2 - (c0.x + (c1.x - c0.x) * e) * z, y: h / 2 - (c0.y + (c1.y - c0.y) * e) * z, zoom: z };
      this.apply();
      raf(frame);
    };
    raf(frame);
  }

  /** True while an `animateTo` is under way (not landed, not stopped by another move). */
  get animating(): boolean {
    return this.animLive !== 0 && this.animLive === this.animToken;
  }
}

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}
