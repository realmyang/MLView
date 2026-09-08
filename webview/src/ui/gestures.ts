/**
 * Wheel and pinch normalization (VIEW-06).
 *
 * Four measured defects lived in one unconditional line
 * (`shell.ts`: `zoomAt(0.999 ** deltaY, …)` on every wheel event):
 *
 *   1. `deltaMode` was ignored, so the SAME physical notch zoomed −9.5 % in
 *      pixel mode (Chromium) and −0.3 % in line mode (Firefox, many mice) — 32×
 *      less for the same gesture.
 *   2. `deltaX` was dropped, so five horizontal trackpad swipes moved a 5672 px
 *      document by exactly zero pixels.
 *   3. `ctrlKey` — the browser's pinch signal — was not branched, so a two-finger
 *      SCROLL zoomed (the classic broken-canvas feel) and a pinch was a slow
 *      wheel.
 *   4. `touch-action: none` was set with no touch handlers at all, so a tablet
 *      lost the browser's pinch and got nothing back.
 *
 * The pixel-mode MOUSE path is bit-identical to what shipped: a coarse
 * `|deltaY| >= COARSE_PX` with no `deltaX` and no modifier still zooms by
 * exactly `ZOOM_BASE ** deltaY` about the cursor.
 */

import { on } from '../dom.js';
import type { ViewportController } from '../render/canvas.js';

/** `WheelEvent.deltaMode`: 0 pixels, 1 lines, 2 pages. */
export const DOM_DELTA_PIXEL = 0;
export const DOM_DELTA_LINE = 1;
export const DOM_DELTA_PAGE = 2;

/**
 * Pixels per line.
 *
 * A wheel NOTCH is the unit the user actually turns. Chromium reports one notch
 * as `deltaY: 100` in pixel mode; Firefox reports the same notch as `deltaY: 3`
 * in line mode (its `mousewheel.default.delta_multiplier_y` is 100 over 3
 * lines). So one line is 100/3 px of the same gesture, and using it makes a
 * line-mode click and a pixel-mode click zoom by the same amount — which is the
 * acceptance this constant exists to meet. (The roadmap's sketch said ×16, a
 * CSS line box; that leaves a notch 2× weak in Firefox.)
 */
export const LINE_PX = 100 / 3;

/** A page-mode notch is a viewport, so the caller passes the real height. */
export const FALLBACK_PAGE_PX = 800;

/** The zoom law, unchanged from the shipped one. */
export const ZOOM_BASE = 0.999;

/**
 * Above this, a delta came from a wheel notch rather than a trackpad glide.
 * A classic mouse therefore still zooms with no modifier, exactly as before.
 */
export const COARSE_PX = 40;

/**
 * Pinch deltas are tiny (±1..10 px per event) because the browser reports a
 * pinch as a fine ctrl+wheel. Multiply only in that regime, so a mouse user
 * holding Ctrl gets the ordinary notch and a trackpad pinch feels direct.
 */
export const PINCH_GAIN = 6;

export interface NormalizedWheel {
  /** Pixels, sign preserved, whatever `deltaMode` the device used. */
  dx: number;
  dy: number;
  mode: number;
}

/** `deltaMode` -> pixels. `viewH` is the canvas height for page-mode events. */
export function normalizeWheel(ev: WheelEvent, viewH = FALLBACK_PAGE_PX): NormalizedWheel {
  const mode = typeof ev.deltaMode === 'number' ? ev.deltaMode : DOM_DELTA_PIXEL;
  let scale = 1;
  if (mode === DOM_DELTA_LINE) scale = LINE_PX;
  else if (mode === DOM_DELTA_PAGE) scale = viewH > 0 ? viewH : FALLBACK_PAGE_PX;
  return {
    dx: finite(ev.deltaX) * scale,
    dy: finite(ev.deltaY) * scale,
    mode,
  };
}

function finite(v: number): number {
  return typeof v === 'number' && isFinite(v) ? v : 0;
}

export type WheelIntent = 'zoom' | 'pan';

/**
 * What a wheel event MEANS.
 *
 * `ctrl`/`cmd` is the browser's pinch signal and always zooms. Everything else
 * pans in two axes — except a coarse, axis-locked, modifier-free notch, which is
 * a classic mouse wheel and keeps its shipped zoom behaviour.
 */
export function wheelIntent(ev: WheelEvent, n: NormalizedWheel): WheelIntent {
  if (ev.ctrlKey || ev.metaKey) return 'zoom';
  if (ev.shiftKey) return 'pan';
  if (n.dx === 0 && Math.abs(n.dy) >= COARSE_PX) return 'zoom';
  return 'pan';
}

/** The multiplier a zooming wheel event applies. */
export function wheelZoomFactor(ev: WheelEvent, n: NormalizedWheel): number {
  const pinch = (ev.ctrlKey || ev.metaKey) && Math.abs(n.dy) < COARSE_PX;
  return Math.pow(ZOOM_BASE, n.dy * (pinch ? PINCH_GAIN : 1));
}

/** Shift+wheel is the browser's own horizontal-scroll convention. */
export function panDelta(ev: WheelEvent, n: NormalizedWheel): { dx: number; dy: number } {
  if (ev.shiftKey && n.dx === 0) return { dx: -n.dy, dy: 0 };
  return { dx: -n.dx, dy: -n.dy };
}

/** Attach the wheel handler. Returns its disposer. */
export function wireWheel(canvas: HTMLElement, viewport: ViewportController): () => void {
  return on(canvas, 'wheel', (ev: WheelEvent) => {
    ev.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const n = normalizeWheel(ev, rect.height || canvas.clientHeight || FALLBACK_PAGE_PX);
    if (wheelIntent(ev, n) === 'zoom') {
      viewport.zoomAt(wheelZoomFactor(ev, n), ev.clientX - rect.left, ev.clientY - rect.top);
      return;
    }
    const pan = panDelta(ev, n);
    viewport.panBy(pan.dx, pan.dy);
  });
}

/* ── two-pointer pinch ─────────────────────────────────────────────────── */

interface Pt {
  x: number;
  y: number;
}

export function distance(a: Pt, b: Pt): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

export function midpoint(a: Pt, b: Pt): Pt {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Two-pointer pinch + pan, driven purely by pointer events.
 *
 * This is what makes `canvas.css`'s `touch-action: none` correct: the browser's
 * own pinch is suppressed there, so the canvas has to supply one. The tracker
 * owns the gesture while two pointers are down and tells the single-pointer pan
 * in `wireCanvasGestures` to stand down through `active()`.
 */
export class PinchTracker {
  private canvas: HTMLElement;
  private viewport: ViewportController;
  private points = new Map<number, Pt>();
  private lastDistance = 0;
  private lastMid: Pt | null = null;

  constructor(canvas: HTMLElement, viewport: ViewportController) {
    this.canvas = canvas;
    this.viewport = viewport;
  }

  /** True while two or more pointers are down: a pinch owns the canvas. */
  active(): boolean {
    return this.points.size >= 2;
  }

  down(ev: PointerEvent): void {
    this.points.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    this.reseed();
  }

  up(ev: PointerEvent): void {
    this.points.delete(ev.pointerId);
    this.reseed();
  }

  clear(): void {
    this.points.clear();
    this.lastDistance = 0;
    this.lastMid = null;
  }

  /** Returns true when the move was consumed as a pinch. */
  move(ev: PointerEvent): boolean {
    if (!this.points.has(ev.pointerId)) return false;
    this.points.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (this.points.size < 2) return false;
    const pair = this.pair();
    if (!pair) return false;
    const dist = distance(pair[0], pair[1]);
    const mid = midpoint(pair[0], pair[1]);
    const rect = this.canvas.getBoundingClientRect();
    if (this.lastDistance > 0 && dist > 0) {
      // Pan by the midpoint's travel first, then zoom about where the fingers
      // now are, so the content under them stays put.
      if (this.lastMid) this.viewport.panBy(mid.x - this.lastMid.x, mid.y - this.lastMid.y);
      this.viewport.zoomAt(dist / this.lastDistance, mid.x - rect.left, mid.y - rect.top);
    }
    this.lastDistance = dist;
    this.lastMid = mid;
    return true;
  }

  /** The two lowest pointer ids, so a third finger never re-seeds the gesture. */
  private pair(): [Pt, Pt] | null {
    const ids = Array.from(this.points.keys()).sort((a, b) => a - b);
    if (ids.length < 2) return null;
    return [this.points.get(ids[0])!, this.points.get(ids[1])!];
  }

  private reseed(): void {
    const pair = this.pair();
    if (!pair) {
      this.lastDistance = 0;
      this.lastMid = null;
      return;
    }
    this.lastDistance = distance(pair[0], pair[1]);
    this.lastMid = midpoint(pair[0], pair[1]);
  }
}
