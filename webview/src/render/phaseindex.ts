/**
 * Viewer M3, roadmap step 13: the labelled phase index. It replaces the unlabelled minimap.
 *
 * A panel in the lower right corner of the canvas with one row per phase: the phase number (in
 * its colour), the label, the findings touching it by severity (the PR #14 rule: a finding on two
 * phases counts in both) and its step count. The phases in view are marked. A click on a row goes
 * to that phase at reading size (the same move as the phase overview's blocks).
 *
 * Below 1000 px (and on a canvas under 350 px tall) it is a pill instead: "4/6 Objective,
 * optimizer & scheduler ▴", the phase most in view. The pill opens the rows above itself. Wide,
 * the panel's chevron folds it to the pill and the pill unfolds it. The ... menu shows or hides it.
 *
 * It never hides the card the keyboard is on: `coveredRect` is the part of the canvas it covers,
 * and the viewport's reveal, centring and visibility test keep a target out of it
 * (`ViewportController.setCovered`). It sits inside the canvas, so in the bottom sheet's layout it
 * stays above the sheet (and above the review walk's bar), never on it.
 *
 * Keyboard: its rows are not Tab stops; the phase overview (Shift+0) is the keyboard's way to the
 * same moves, with arrows between phases. The rows are labelled buttons, so a screen reader can
 * still read and press them.
 */

import { add, clear, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { clusterTitle, countsTotal, severityCluster } from '../markers.js';
import { stampPhase } from './phase.js';
import type { IssueCounts, Viewport } from '../types.js';

export interface PhaseRow {
  id: string;
  label: string;
  /** The phase's position among the declared phases (0-based): its number and colour. */
  index: number;
  steps: number;
  /** Findings touching the phase, by severity (PR #14). */
  counts: IssueCounts;
  /** The lane's box in world coordinates. */
  rect: { x: number; y: number; w: number; h: number };
}

export interface CoveredRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Panel width, row and head heights, the pill's height and widest size, and the corner margin (CSS px). */
export const INDEX_W = 288;
export const INDEX_HEAD_H = 26;
export const INDEX_ROW_H = 24;
export const INDEX_PAD_Y = 4;
export const PILL_H = 28;
export const PILL_MAX_W = 360;
export const INDEX_MARGIN = 12;
/** The gap between the pill and the rows it opens above itself. */
export const POPOVER_GAP = 4;

/** Which phases a viewport shows, and the one it shows most of. */
export interface PhasesInView {
  ids: string[];
  /** The phase with the largest visible area; null when none is visible. */
  current: string | null;
}

/**
 * The phases whose lanes intersect the canvas at this viewport, and the one the reader is looking
 * at: the highest score of (share of the canvas the lane fills) + (share of the lane that is in
 * view), the first of equals. Either share alone misleads: by area a tall lane wins while a short
 * phase the reader just moved to is wholly on screen under it; by share a sliver of a small lane
 * in a corner would win over the lane that fills the canvas. Pure.
 */
export function phasesInView(rows: readonly PhaseRow[], vp: Viewport, w: number, h: number): PhasesInView {
  const ids: string[] = [];
  let current: string | null = null;
  let best = 0;
  const canvas = Math.max(1, w * h);
  for (const row of rows) {
    const x0 = Math.max(0, row.rect.x * vp.zoom + vp.x);
    const y0 = Math.max(0, row.rect.y * vp.zoom + vp.y);
    const x1 = Math.min(w, (row.rect.x + row.rect.w) * vp.zoom + vp.x);
    const y1 = Math.min(h, (row.rect.y + row.rect.h) * vp.zoom + vp.y);
    const area = Math.max(0, x1 - x0) * Math.max(0, y1 - y0);
    if (area <= 0) continue;
    ids.push(row.id);
    const lane = Math.max(1, row.rect.w * row.rect.h * vp.zoom * vp.zoom);
    const score = area / canvas + area / lane;
    if (score > best + 1e-9) {
      best = score;
      current = row.id;
    }
  }
  return { ids, current };
}

/** "2 findings touch this phase", or '' when none does. */
function findingsWords(counts: IssueCounts): string {
  const total = countsTotal(counts);
  if (!total) return '';
  return total + (total === 1 ? ' finding touches this phase' : ' findings touch this phase');
}

const steps = (n: number): string => n + (n === 1 ? ' step' : ' steps');

/** The highest phase number shown, the denominator of "4/6". */
function lastNumber(rows: readonly PhaseRow[]): number {
  let last = rows.length;
  for (const row of rows) last = Math.max(last, row.index + 1);
  return last;
}

export interface PhaseIndexCallbacks {
  /** A row was chosen: go to that phase. */
  go(id: string): void;
  /** The wide panel was folded to its pill, or unfolded (saved per viewer). */
  fold(folded: boolean): void;
}

export interface PhaseIndexMode {
  /** Room for the panel: a panel 1000 px wide or wider and a canvas 350 px tall or taller. */
  roomy: boolean;
  /** The reader folded the panel to its pill. */
  folded: boolean;
  /** The reader hid the index (the ... menu). */
  hidden: boolean;
  /** Something covers the whole canvas (the phase overview). */
  suppressed: boolean;
}

export class PhaseIndex {
  readonly root: HTMLElement;
  private panel: HTMLElement;
  private headSteps: HTMLElement;
  private foldBtn: HTMLButtonElement;
  private rowsEl: HTMLElement;
  private pill: HTMLButtonElement;
  private pillNum: HTMLElement;
  private pillLabel: HTMLElement;
  private cb: PhaseIndexCallbacks;
  private rowsData: PhaseRow[] = [];
  private rowEls = new Map<string, HTMLElement>();
  private mode: PhaseIndexMode = { roomy: true, folded: false, hidden: false, suppressed: false };
  private popover = false;
  private inViewKey = '';
  private currentId: string | null = null;
  private disposers: (() => void)[] = [];

  constructor(cb: PhaseIndexCallbacks) {
    this.cb = cb;
    this.root = el('nav', 'mlv-phaseindex');
    this.root.setAttribute('aria-label', 'Phase index');
    this.root.hidden = true;

    this.panel = add(this.root, el('div', 'mlv-phaseindex__panel'));
    const head = add(this.panel, el('div', 'mlv-phaseindex__head'));
    add(head, el('span', 'mlv-phaseindex__title', 'Phases'));
    this.headSteps = add(head, el('span', 'mlv-phaseindex__total'));
    this.foldBtn = add(head, el('button', 'mlv-btn mlv-btn--icon mlv-phaseindex__fold')) as HTMLButtonElement;
    this.foldBtn.type = 'button';
    this.foldBtn.tabIndex = -1;
    this.foldBtn.setAttribute('aria-label', 'Fold the phase index');
    this.foldBtn.title = 'Fold the phase index to one line';
    this.foldBtn.appendChild(uiIcon('chevron', 12));
    on(this.foldBtn, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.cb.fold(true);
    });
    this.rowsEl = add(this.panel, el('ol', 'mlv-phaseindex__rows'));

    this.pill = add(this.root, el('button', 'mlv-phaseindex__pill')) as HTMLButtonElement;
    this.pill.type = 'button';
    this.pill.tabIndex = -1;
    this.pill.setAttribute('aria-expanded', 'false');
    this.pillNum = add(this.pill, el('span', 'mlv-phaseindex__pillnum'));
    this.pillLabel = add(this.pill, el('span', 'mlv-phaseindex__pilllabel'));
    const chevron = uiIcon('chevron', 12);
    chevron.setAttribute('class', 'mlv-uicon mlv-phaseindex__pillchev');
    this.pill.appendChild(chevron);
    on(this.pill, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (this.mode.roomy && this.mode.folded) this.cb.fold(false);
      else this.setPopover(!this.popover);
    });

    // Enter and Space press the focused row or pill themselves; the canvas under the index must
    // not also read them as "open the selection". A long index scrolls itself, not the diagram.
    this.disposers.push(on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key === 'Enter' || ev.key === ' ') ev.stopPropagation();
    }));
    this.disposers.push(on(this.panel, 'wheel', (ev: WheelEvent) => ev.stopPropagation()));
    const doc = typeof document === 'undefined' ? null : document;
    if (doc) {
      this.disposers.push(on(doc, 'pointerdown', (ev: PointerEvent) => {
        if (!this.popover) return;
        const target = ev.target as Node | null;
        if (target && this.root.contains(target)) return;
        this.setPopover(false);
      }));
    }
  }

  /** The rows, as the canvas draws its lanes. */
  setRows(rows: PhaseRow[]): void {
    this.rowsData = rows;
    this.rowEls.clear();
    clear(this.rowsEl);
    const total = rows.reduce((sum, row) => sum + row.steps, 0);
    this.headSteps.textContent = steps(total);
    const last = lastNumber(rows);
    for (const row of rows) {
      const li = add(this.rowsEl, el('li', 'mlv-phaseindex__item'));
      const btn = add(li, el('button', 'mlv-phaseindex__row')) as HTMLButtonElement;
      btn.type = 'button';
      btn.tabIndex = -1;
      btn.setAttribute('data-phase-id', row.id);
      stampPhase(btn, row.index);
      add(btn, el('span', 'mlv-phaseindex__num', String(row.index + 1))).setAttribute('aria-hidden', 'true');
      add(btn, el('span', 'mlv-phaseindex__label', row.label));
      const cluster = severityCluster(row.counts, 11, findingsWords(row.counts));
      if (cluster) {
        cluster.classList.add('mlv-phaseindex__sev');
        cluster.setAttribute('aria-hidden', 'true');
        cluster.title = findingsWords(row.counts) + ' (' + clusterTitle(row.counts) + ')';
        btn.appendChild(cluster);
      }
      add(btn, el('span', 'mlv-phaseindex__steps', steps(row.steps))).setAttribute('aria-hidden', 'true');
      btn.setAttribute('data-name', 'Phase ' + (row.index + 1) + ' of ' + last + ': ' + row.label + ', ' + steps(row.steps) +
        (countsTotal(row.counts) ? ', ' + findingsWords(row.counts) + ' (' + clusterTitle(row.counts).replace(/^\d+ findings?: /, '') + ')' : ''));
      btn.title = btn.getAttribute('data-name') + '. Go to this phase.';
      on(btn, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        ev.stopPropagation();
        this.setPopover(false);
        this.cb.go(row.id);
      });
      this.rowEls.set(row.id, btn);
    }
    this.inViewKey = '\u0000';
    this.applyMode();
  }

  get rows(): readonly PhaseRow[] {
    return this.rowsData;
  }

  setMode(mode: Partial<PhaseIndexMode>): void {
    this.mode = { ...this.mode, ...mode };
    this.applyMode();
  }

  /** Whether the index has anything to show: two or more phases. */
  get available(): boolean {
    return this.rowsData.length >= 2;
  }

  /** The form on screen: the panel, the pill, or nothing. */
  get form(): 'list' | 'pill' | 'none' {
    if (this.root.hidden) return 'none';
    return this.root.getAttribute('data-form') === 'list' ? 'list' : 'pill';
  }

  get popoverOpen(): boolean {
    return this.popover && this.form === 'pill';
  }

  /** Close the pill's open rows; false when they were not open (an Escape rung). */
  closePopover(): boolean {
    if (!this.popoverOpen) return false;
    this.setPopover(false);
    return true;
  }

  private setPopover(open: boolean): void {
    this.popover = open;
    this.applyMode();
  }

  private applyMode(): void {
    const m = this.mode;
    const hidden = m.hidden || m.suppressed || !this.available;
    this.root.hidden = hidden;
    const list = m.roomy && !m.folded;
    if (list || hidden) this.popover = false;
    this.root.setAttribute('data-form', list ? 'list' : 'pill');
    if (this.popover) this.root.setAttribute('data-open', 'true');
    else this.root.removeAttribute('data-open');
    this.panel.hidden = !list && !this.popover;
    this.pill.hidden = list;
    this.pill.setAttribute('aria-expanded', this.popover ? 'true' : 'false');
    const unfold = m.roomy && m.folded;
    this.pill.title = unfold ? 'Unfold the phase index' : this.popover ? 'Close the phase list' : 'Show every phase';
    this.syncPill();
  }

  /** Mark the phases this viewport shows; only a change of the set touches the DOM. */
  setInView(vp: Viewport, w: number, h: number): void {
    const view = phasesInView(this.rowsData, vp, w, h);
    const key = view.ids.join('\u0000') + '\u0001' + (view.current || '');
    if (key === this.inViewKey) return;
    this.inViewKey = key;
    this.currentId = view.current;
    const shown = new Set(view.ids);
    for (const [id, btn] of this.rowEls) {
      const on_ = shown.has(id);
      if (on_) btn.setAttribute('data-in-view', 'true');
      else btn.removeAttribute('data-in-view');
      btn.setAttribute('aria-label', (btn.getAttribute('data-name') || '') + (on_ ? ', in view' : ''));
    }
    this.syncPill();
  }

  /** The phase the viewport shows most of, or null. */
  currentPhase(): string | null {
    return this.currentId;
  }

  /** The phases marked in view, in drawn order (tests and the harness read it). */
  inView(): string[] {
    const out: string[] = [];
    for (const [id, btn] of this.rowEls) if (btn.getAttribute('data-in-view') === 'true') out.push(id);
    return out;
  }

  private syncPill(): void {
    const rows = this.rowsData;
    const last = lastNumber(rows);
    const row = rows.find((r) => r.id === this.currentId) || null;
    this.pillNum.textContent = row ? row.index + 1 + '/' + last : String(rows.length);
    this.pillLabel.textContent = row ? row.label : rows.length === 1 ? 'phase' : 'phases';
    this.pill.setAttribute('aria-label', (row ? 'Phase ' + (row.index + 1) + ' of ' + last + ' in view: ' + row.label : rows.length + ' phases') +
      '. ' + (this.mode.roomy && this.mode.folded ? 'Unfold the phase index.' : this.popover ? 'Close the phase list.' : 'Show every phase.'));
  }

  /**
   * The part of the canvas the index covers, in canvas pixels, or null when it is not shown. Read
   * from the boxes on screen when the host lays them out; otherwise (jsdom, before layout) from the
   * same sizes the stylesheet gives them, the pill at its widest.
   */
  coveredRect(canvasW: number, canvasH: number, canvasLeft = 0, canvasTop = 0): CoveredRect | null {
    if (this.root.hidden || !(canvasW > 0) || !(canvasH > 0)) return null;
    const parts: CoveredRect[] = [];
    for (const part of [this.panel, this.pill]) {
      if (part.hidden) continue;
      const r = part.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) parts.push({ x: r.left - canvasLeft, y: r.top - canvasTop, w: r.width, h: r.height });
    }
    if (!parts.length) {
      const m = INDEX_MARGIN;
      const listH = INDEX_HEAD_H + this.rowsData.length * INDEX_ROW_H + 2 * INDEX_PAD_Y;
      if (this.root.getAttribute('data-form') === 'list') {
        const w = Math.min(INDEX_W, canvasW - 2 * m);
        const h = Math.min(listH, canvasH - 2 * m);
        parts.push({ x: canvasW - m - w, y: canvasH - m - h, w, h });
      } else {
        const w = Math.min(PILL_MAX_W, canvasW - 2 * m);
        parts.push({ x: canvasW - m - w, y: canvasH - m - PILL_H, w, h: PILL_H });
        if (this.popover) {
          const pw = Math.min(INDEX_W, canvasW - 2 * m);
          const ph = Math.min(listH, Math.max(0, canvasH - 2 * m - PILL_H - POPOVER_GAP));
          parts.push({ x: canvasW - m - pw, y: canvasH - m - PILL_H - POPOVER_GAP - ph, w: pw, h: ph });
        }
      }
    }
    const x = Math.min(...parts.map((p) => p.x));
    const y = Math.min(...parts.map((p) => p.y));
    return { x, y, w: Math.max(...parts.map((p) => p.x + p.w)) - x, h: Math.max(...parts.map((p) => p.y + p.h)) - y };
  }

  destroy(): void {
    for (const dispose of this.disposers) {
      try {
        dispose();
      } catch (_e) {
        /* already torn down */
      }
    }
    this.disposers = [];
  }
}
