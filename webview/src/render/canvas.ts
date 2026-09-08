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
   * illegible on its own, fit the WIDTH, anchor at the top, and let the user pan
   * down — which is how a swimlane diagram is read anyway.
   *
   * A PROJECTION never takes that branch: the user asked for one part of the
   * pipeline, and the answer must open showing it (MLV-R3-001).
   */
  fit(padding = 24): void {
    const { w, h } = this.size();
    const zw = (w - padding * 2) / this.contentW;
    const zh = (h - padding * 2) / this.contentH;
    const tall = !this.projected && zh < zw * 0.6 && zh < 0.6;
    const zoom = clamp(tall ? Math.min(zw, 1) : Math.min(zw, zh), MIN_ZOOM, 1.2);
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
