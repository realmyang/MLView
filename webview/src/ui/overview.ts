/**
 * Viewer M3, roadmap step 13: the phase overview's DOM (Shift+0). The geometry is
 * `render/phaseoverview.ts`; this file only draws it, over the canvas and outside the world layer
 * that pans and zooms, so nothing in the routed picture (or its golden) moves.
 *
 * Keyboard: each phase block is one focusable element of a roving group. ↓ / → and ↑ / ← move
 * between blocks, Home and End jump to the first and last, Enter or Space goes to the phase, and
 * Shift+0 goes back to where the reader was. Escape goes on to the canvas's Escape cascade, which
 * closes a legend or phase list opened over the overview first and then leaves the overview (M3
 * review, F5). Tab is never held. Every other key goes on to the canvas, whose handler closes the
 * overview first and then acts (app/keys.ts).
 *
 * Names: a block is a button named "Phase 2 of 6: Data preparation. 9 steps (1 inferred). 2
 * findings touch this phase. 3 connections to phase 3; 4 connections ahead to phase 5. Enter goes
 * to this phase." and described by its list of titles, which ends with "… 7 more steps" when it is
 * trimmed.
 */

import { add, clear, el, on, svg } from '../dom.js';
import { uiIcon } from '../icons.js';
import { countsTotal, severityCluster, severityGlyph, SEVERITY_WORD } from '../markers.js';
import { stampPhase } from '../render/phase.js';
import { phaseFindingsSpoken, phaseFindingsText } from '../render/nodes.js';
import { blockStepsText, isNextLink, phaseOverviewLayout } from '../render/phaseoverview.js';
import type { OverviewInput, OverviewLayout, OverviewPhase } from '../render/phaseoverview.js';

export interface OverviewCallbacks {
  /** Go to a phase (a click, or Enter / Space on its block). */
  go(phaseId: string, byKeyboard: boolean): void;
  /** Back to the diagram as it was (Escape, Shift+0, the Back button). */
  back(): void;
}

let overviewSeq = 0;

const plural = (n: number, one: string, many: string): string => n + ' ' + (n === 1 ? one : many);

export class PhaseOverview {
  readonly root: HTMLElement;
  private content: HTMLElement;
  private cb: OverviewCallbacks;
  private uid: string;
  private input: OverviewInput | null = null;
  private layoutData: OverviewLayout | null = null;
  private blockEls: HTMLElement[] = [];
  private active = 0;
  /**
   * How much of the overlay's top the sticky header covers while the overview scrolls (0 when the
   * header is too tall to stick and scrolls with the blocks). A block brought into view is placed
   * below it.
   */
  private covered = 0;
  private disposers: (() => void)[] = [];

  constructor(cb: OverviewCallbacks) {
    this.cb = cb;
    this.uid = 'mlv-ov' + ++overviewSeq;
    this.root = el('section', 'mlv-overview');
    this.root.setAttribute('aria-label', 'Phase overview');
    this.root.hidden = true;
    this.content = add(this.root, el('div', 'mlv-overview__content'));
    this.disposers.push(on(this.root, 'keydown', (ev: KeyboardEvent) => this.onKey(ev)));
    // The overview scrolls by itself; the canvas's wheel zoom must not see it (it would move the
    // hidden diagram under the overlay).
    this.disposers.push(on(this.root, 'wheel', (ev: WheelEvent) => ev.stopPropagation()));
  }

  get open(): boolean {
    return !this.root.hidden;
  }

  /** The layout last drawn (tests and the harness read it). */
  get layout(): OverviewLayout | null {
    return this.layoutData;
  }

  /** The block that has (or would get) the focus, by position in drawn order. */
  get activeIndex(): number {
    return this.active;
  }

  /** Draw it for `input` at the canvas size and show it, with `activePhase` (drawn position) current. */
  show(input: OverviewInput, w: number, h: number, activePhase: number): void {
    this.root.hidden = false;
    this.active = Math.max(0, Math.min(input.phases.length - 1, activePhase));
    this.draw(input, w, h);
    this.focusBlock(this.active);
  }

  hide(): void {
    this.root.hidden = true;
  }

  /** Draw again for a new size or new data (a resize, a severity toggle), keeping the current block. */
  redraw(input: OverviewInput, w: number, h: number): void {
    if (!this.open) return;
    const doc = this.root.ownerDocument;
    const hadFocus = !!doc && !!doc.activeElement && this.root.contains(doc.activeElement);
    this.active = Math.max(0, Math.min(input.phases.length - 1, this.active));
    this.draw(input, w, h);
    if (hadFocus) this.focusBlock(this.active);
  }

  focusBlock(i: number): void {
    const block = this.blockEls[i];
    if (!block) {
      try {
        this.root.focus();
      } catch (_e) {
        /* detached */
      }
      return;
    }
    this.active = i;
    for (const [j, b] of this.blockEls.entries()) b.tabIndex = j === i ? 0 : -1;
    try {
      block.focus({ preventScroll: true });
    } catch (_e) {
      /* a host may have detached the overlay mid-gesture */
    }
    scrollIntoViewIfNeeded(this.root, block, this.covered, i === 0);
  }

  private draw(input: OverviewInput, w: number, h: number): void {
    this.input = input;
    const layout = phaseOverviewLayout(input, w, h);
    this.layoutData = layout;
    clear(this.content);
    this.blockEls = [];
    this.root.setAttribute('data-layout', layout.narrow ? 'narrow' : 'wide');
    this.root.setAttribute('data-scrolls', layout.scrolls ? 'true' : 'false');
    this.content.style.width = layout.width + 'px';
    this.content.style.height = layout.height + 'px';

    // Header: what this is, the way back, the counts and (with room) the key. M3 live check, W4: it
    // sticks to the top of the overlay while the overview scrolls, so Back, the counts and the key
    // stay on screen when the focused block is low (at 901 and 541 px they scrolled away). It is
    // the first box of the content, as tall as the space above the first block less the gap, so
    // nothing below it moves; a header taller than half the overlay scrolls with the blocks.
    const header = add(this.content, el('div', 'mlv-overview__header'));
    const headerBox = layout.header.y + layout.header.h;
    const sticky = layout.scrolls && headerBox * 2 <= layout.viewH;
    this.covered = sticky ? headerBox : 0;
    header.setAttribute('data-sticky', sticky ? 'true' : 'false');
    header.style.width = layout.width + 'px';
    header.style.height = headerBox + 'px';
    header.style.paddingTop = layout.header.y + 'px';
    header.style.paddingLeft = layout.header.x + 'px';
    header.style.paddingRight = Math.max(0, layout.width - layout.header.x - layout.header.w) + 'px';
    const top = add(header, el('div', 'mlv-overview__top'));
    const title = add(top, el('h3', 'mlv-overview__title', 'Phase overview'));
    title.id = this.uid + '-title';
    this.root.setAttribute('aria-labelledby', title.id);
    const back = add(top, el('button', 'mlv-btn mlv-overview__back')) as HTMLButtonElement;
    back.type = 'button';
    back.tabIndex = -1;
    back.setAttribute('aria-label', 'Back to the diagram (Escape)');
    back.title = 'Back to the diagram where you were (Escape or Shift+0)';
    back.appendChild(uiIcon('close', 12));
    add(back, el('span', 'mlv-overview__backlabel', 'Back'));
    add(back, el('kbd', 'mlv-overview__kbd', 'Esc')).setAttribute('aria-hidden', 'true');
    on(back, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.cb.back();
    });
    const summary = add(header, el('p', 'mlv-overview__summary', layout.header.summary));
    summary.id = this.uid + '-summary';
    this.root.setAttribute('aria-describedby', summary.id);
    if (layout.header.key) {
      // The ◌ is drawn (a dotted ring), not typed: system fonts on macOS have no visible glyph for it.
      const key = add(header, el('p', 'mlv-overview__key'));
      layout.header.key.split('◌').forEach((part, k) => {
        if (k > 0) key.appendChild(inferredMark());
        key.appendChild(doc(header).createTextNode(part));
      });
    }

    // Arrows and brackets under the blocks' text, in one SVG over the whole content.
    const links = svg('svg', { class: 'mlv-overview__links', width: layout.width, height: layout.height, viewBox: '0 0 ' + layout.width + ' ' + layout.height, 'aria-hidden': 'true', focusable: 'false' });
    const defs = svg('defs');
    const marker = svg('marker', { id: this.uid + '-arrow', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' });
    marker.appendChild(svg('path', { d: 'M0 0.6 7.4 4 0 7.4Z', class: 'mlv-overview__head' }));
    defs.appendChild(marker);
    links.appendChild(defs);
    for (const a of layout.arrows) {
      links.appendChild(svg('path', { class: 'mlv-overview__arrow', d: 'M' + a.x + ' ' + a.y1 + 'V' + a.y2, 'marker-end': 'url(#' + this.uid + '-arrow)' }));
    }
    for (const b of layout.brackets) {
      const path = svg('path', {
        class: 'mlv-overview__bracket',
        d: 'M' + b.x0 + ' ' + b.y1 + 'H' + b.x + 'V' + b.y2 + 'H' + (b.x0 + 2),
        'marker-end': 'url(#' + this.uid + '-arrow)',
      });
      if (b.back) path.setAttribute('data-back', 'true');
      links.appendChild(path);
    }
    this.content.appendChild(links);
    for (const a of layout.arrows) {
      const label = add(this.content, el('span', 'mlv-overview__arrowlabel', plural(a.count, 'connection', 'connections')));
      label.style.left = a.labelX + 'px';
      label.style.top = a.labelY + 'px';
      label.setAttribute('aria-hidden', 'true');
    }
    for (const b of layout.brackets) {
      const from = input.phases[b.from];
      const to = input.phases[b.to];
      const count = add(this.content, el('span', 'mlv-overview__count', String(b.count)));
      count.style.left = b.labelX + 'px';
      count.style.top = b.labelY + 'px';
      if (b.back) count.setAttribute('data-back', 'true');
      count.setAttribute('aria-hidden', 'true');
      count.title = plural(b.count, 'connection', 'connections') + ' from phase ' + (from.index + 1) + (b.back ? ' back to' : ' ahead to') + ' phase ' + (to.index + 1);
    }

    const list = add(this.content, el('ol', 'mlv-overview__blocks'));
    list.setAttribute('aria-label', plural(input.phases.length, 'phase', 'phases'));
    layout.blocks.forEach((block, i) => {
      const phase = input.phases[block.phase];
      const li = add(list, el('li', 'mlv-overview__item'));
      const box = add(li, el('div', 'mlv-ovblock'));
      box.setAttribute('role', 'button');
      box.setAttribute('data-phase-id', phase.id);
      box.setAttribute('data-block', String(i));
      box.setAttribute('data-head', block.twoLineHead ? 'two-lines' : 'one-line');
      stampPhase(box, phase.index);
      box.tabIndex = i === this.active ? 0 : -1;
      place(box, block);
      box.setAttribute('aria-label', blockName(input, block.phase));
      const head = add(box, el('div', 'mlv-ovblock__head'));
      head.style.height = block.headH + 'px';
      const name = add(head, el('div', 'mlv-ovblock__name'));
      add(name, el('span', 'mlv-ovblock__num', String(phase.index + 1)));
      const label = add(name, el('span', 'mlv-ovblock__label', phase.label));
      label.title = 'Phase ' + (phase.index + 1) + ': ' + phase.label;
      const meta = add(head, el('div', 'mlv-ovblock__meta'));
      add(meta, el('span', 'mlv-ovblock__steps', blockStepsText(phase)));
      const total = countsTotal(phase.findings);
      if (total > 0) {
        const cluster = severityCluster(phase.findings, 12, phaseFindingsSpoken(phase.findings));
        if (cluster) meta.appendChild(cluster);
        add(meta, el('span', 'mlv-ovblock__unit', phaseFindingsText(total)));
      }
      const steps = add(box, el('ul', 'mlv-ovblock__list'));
      steps.id = this.uid + '-list-' + i;
      box.setAttribute('aria-describedby', steps.id);
      for (const item of block.items) {
        const row = add(steps, el('li', 'mlv-ovitem'));
        row.style.left = round1(item.x - block.x) + 'px';
        row.style.top = round1(item.y - block.y) + 'px';
        row.style.width = Math.max(0, item.w) + 'px';
        if (item.step < 0) {
          row.classList.add('mlv-ovitem--more');
          row.textContent = '… ' + plural(item.more, 'more step', 'more steps');
          add(row, el('span', 'mlv-sr', '.'));
          continue;
        }
        const step = phase.steps[item.step];
        row.setAttribute('data-node-ref', step.id);
        if (item.depth) row.setAttribute('data-depth', String(item.depth));
        if (step.basis && step.basis !== 'observed') row.setAttribute('data-basis', step.basis);
        const mark = add(row, el('span', 'mlv-ovitem__mark', step.basis === 'unresolved' ? '?' : ''));
        if (step.basis === 'inferred') mark.appendChild(inferredMark());
        mark.setAttribute('aria-hidden', 'true');
        if (step.basis === 'inferred' || step.basis === 'unresolved') add(row, el('span', 'mlv-sr', step.basis + ': '));
        const text = add(row, el('span', 'mlv-ovitem__title', step.title));
        text.title = step.title + (step.basis && step.basis !== 'observed' ? ' (' + step.basis + ')' : '');
        if (step.tags.length) {
          const tags = add(row, el('span', 'mlv-ovitem__tags'));
          for (const tag of step.tags) {
            const t = add(tags, el('span', 'mlv-ovitem__tag'));
            t.setAttribute('data-sev', tag.severity);
            t.title = tag.short + ' (' + tag.id + '), ' + SEVERITY_WORD[tag.severity] + ' severity';
            const glyph = severityGlyph(tag.severity, 10, '');
            glyph.setAttribute('aria-hidden', 'true');
            glyph.removeAttribute('role');
            t.appendChild(glyph);
            add(t, el('span', 'mlv-ovitem__tagid', tag.short));
          }
          // The tags are drawn for the eye; a screen reader hears the F labels once, in words.
          tags.setAttribute('aria-hidden', 'true');
          add(row, el('span', 'mlv-sr', ', ' + (step.tags.length === 1 ? 'finding ' : 'findings ') + step.tags.map((t) => t.short).join(', ')));
        }
        // A separator after each title, so the block's description does not run them together.
        if (step.tags.length || !/[.!?…]$/.test(step.title.trim())) add(row, el('span', 'mlv-sr', '. '));
        else add(row, el('span', 'mlv-sr', ' '));
      }
      on(box, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        ev.stopPropagation();
        this.active = i;
        this.cb.go(phase.id, ev.detail === 0);
      });
      on(box, 'focus', () => {
        if (this.active === i) return;
        this.active = i;
        for (const [j, b] of this.blockEls.entries()) b.tabIndex = j === i ? 0 : -1;
      });
      this.blockEls.push(box);
    });
  }

  private onKey(ev: KeyboardEvent): void {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const key = ev.key;
    const n = this.blockEls.length;
    let handled = true;
    // Escape is not handled here: the canvas's cascade (ui/appkeys.ts) closes what is on top of the
    // overview first (the legend, the phase list) and leaves the overview on the next press.
    if (key === ')' || (key === '0' && ev.shiftKey)) this.cb.back();
    else if (key === 'ArrowDown' || key === 'ArrowRight') this.focusBlock(Math.min(n - 1, this.active + 1));
    else if (key === 'ArrowUp' || key === 'ArrowLeft') this.focusBlock(Math.max(0, this.active - 1));
    else if (key === 'Home') this.focusBlock(0);
    else if (key === 'End') this.focusBlock(n - 1);
    else if (key === 'Enter' || key === ' ') {
      const phase = this.input && this.input.phases[this.active];
      if (phase) this.cb.go(phase.id, true);
    } else handled = false;
    if (!handled) return;
    // Marked handled (the panel's bootstrap then keeps VS Code from acting on an Escape), and kept
    // from the canvas's own keys under the overlay (the arrows would move the selection).
    ev.preventDefault();
    ev.stopPropagation();
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

/**
 * The block's accessible name: the phase, its counts with their units, and its connections to
 * other phases, as sentences. The titles are its description (the list inside it).
 */
export function blockName(input: OverviewInput, at: number): string {
  const phase: OverviewPhase = input.phases[at];
  const last = input.phases.length ? input.phases[input.phases.length - 1].index + 1 : 0;
  const parts = ['Phase ' + (phase.index + 1) + ' of ' + Math.max(last, input.phases.length) + ': ' + phase.label + '.', blockStepsText(phase) + '.'];
  const total = countsTotal(phase.findings);
  if (total > 0) parts.push(phaseFindingsText(total) + '.');
  const out: string[] = [];
  for (const link of input.links) {
    if (link.from !== at) continue;
    const to = input.phases[link.to];
    out.push(plural(link.count, 'connection', 'connections') + (isNextLink(link) ? ' to' : link.to < link.from ? ' back to' : ' ahead to') + ' phase ' + (to.index + 1));
  }
  if (out.length) parts.push(out.join('; ') + '.');
  parts.push('Enter goes to this phase.');
  return parts.join(' ');
}

/** The inferred mark, ◌, as a dotted ring the stylesheet draws (`.mlv-ovmark`). */
function inferredMark(): HTMLElement {
  const mark = el('span', 'mlv-ovmark');
  mark.setAttribute('aria-hidden', 'true');
  mark.setAttribute('data-mark', '◌');
  return mark;
}

function doc(node: Node): Document {
  return node.ownerDocument || document;
}

function place(element: HTMLElement, r: { x: number; y: number; w: number; h: number }): void {
  element.style.left = r.x + 'px';
  element.style.top = r.y + 'px';
  element.style.width = r.w + 'px';
  element.style.height = r.h + 'px';
}

/**
 * Scroll the overlay so the focused block is wholly in view below the sticky header (`covered`
 * pixels of the top), or shows its top when it is taller than the room. The first block scrolls
 * the overlay to its top, so the header shows whole even when it does not stick (it used to stop
 * 12 px above the block, with the header out of view).
 */
function scrollIntoViewIfNeeded(scroller: HTMLElement, block: HTMLElement, covered: number, first: boolean): void {
  const top = block.offsetTop;
  const bottom = top + block.offsetHeight;
  const view = scroller.clientHeight;
  if (!(view > 0)) return;
  let next = scroller.scrollTop;
  if (top - 12 < next + covered) next = top - 12 - covered;
  else if (bottom + 12 > next + view) next = Math.min(top - 12 - covered, bottom + 12 - view);
  if (first && bottom + 12 <= view) next = 0;
  next = Math.max(0, next);
  if (next !== scroller.scrollTop) scroller.scrollTop = next;
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}
