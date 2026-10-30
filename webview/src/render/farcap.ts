/**
 * The cap a far connection's lit line ends in, where it runs out of sight on
 * its way to a card that is not in view. A lozenge with three dots, 22 x 14 px on screen at every
 * zoom, in the colour the line is drawn in and, on a line drawn dashed or dotted (it carries an
 * inferred or unresolved connection), with that outline (styles/workflow.css). It states no
 * direction and no distance: the walk bar's line does (`ui/walkbar.ts`), and starts with the same
 * lozenge.
 *
 * Where a cap goes is `capPoint` in `far.ts`; this file is only the element.
 */

import { el, svg } from '../dom.js';
import { CAP_LONG, CAP_SHORT } from '../far.js';
import type { CapAt, End } from '../far.js';

/** The lozenge with three dots: the cap on the canvas and the first mark of the walk bar's line. */
export function capGlyph(cls: string): HTMLElement {
  const root = el('span', cls);
  const dots = svg('svg', { class: 'mlv-farglyph__dots', viewBox: '0 0 18 6', width: 18, height: 6, 'aria-hidden': 'true', focusable: 'false' });
  for (const cx of [4, 9, 14]) dots.appendChild(svg('circle', { cx, cy: 3, r: 1.5 }));
  root.appendChild(dots);
  return root;
}

export interface CapState {
  /** The cap's centre, in canvas pixels, and whether it lies along a vertical stretch. */
  at: CapAt;
  /** The end of the connection this cap continues to. */
  end: End;
  /** The basis the line is drawn with: the cap takes its dash when that is not observed. */
  basis?: string | null;
  /** The lit line's colour: the source card's phase tone, or its finding's severity, once it is `lit` in them. */
  tone?: string | null;
  severity?: string | null;
  lit: boolean;
  title: string;
}

/**
 * The caps on the canvas (at most two: one towards each end that is out of sight). They are a
 * pointer's shortcut and a picture for the walk bar's line; the control with a name, a role and a
 * place in the Tab order is that line, so the caps are hidden from assistive technology and never
 * take the keyboard focus.
 */
export class FarCaps {
  readonly root: HTMLElement;
  private caps: HTMLElement[] = [];
  private onGo: (end: End, ev: MouseEvent) => void;
  private onCue: (on: boolean) => void;
  /** The walk bar's line has the pointer or the focus (`cue`): a cap drawn meanwhile answers too. */
  private cued = false;
  /** The cap the pointer is on, which the walk bar's line answers. */
  private pointed: HTMLElement | null = null;

  constructor(onGo: (end: End, ev: MouseEvent) => void, onCue: (on: boolean) => void) {
    this.root = el('div', 'mlv-farcaps');
    this.root.setAttribute('aria-hidden', 'true');
    this.onGo = onGo;
    this.onCue = onCue;
  }

  /** Draw these caps (none: remove them). */
  set(states: readonly CapState[]): void {
    while (this.caps.length > states.length) {
      const gone = this.caps.pop() as HTMLElement;
      if (gone.parentNode) gone.parentNode.removeChild(gone);
      // A cap taken away under the pointer is sent no pointerleave: the line stops answering here.
      if (gone === this.pointed) {
        this.pointed = null;
        this.onCue(false);
      }
    }
    states.forEach((s, i) => {
      let cap = this.caps[i];
      if (!cap) {
        cap = capGlyph('mlv-farcap mlv-farglyph');
        cap.addEventListener('click', (ev) => {
          ev.stopPropagation();
          this.onGo(cap.getAttribute('data-far-end') === 'source' ? 'source' : 'target', ev);
        });
        cap.addEventListener('pointerenter', () => {
          this.pointed = cap;
          this.onCue(true);
        });
        cap.addEventListener('pointerleave', () => {
          if (this.pointed === cap) this.pointed = null;
          this.onCue(false);
        });
        cap.classList.toggle('is-cued', this.cued);
        this.root.appendChild(cap);
        this.caps[i] = cap;
      }
      const w = s.at.vertical ? CAP_SHORT : CAP_LONG;
      const h = s.at.vertical ? CAP_LONG : CAP_SHORT;
      cap.classList.toggle('mlv-farcap--v', s.at.vertical);
      cap.style.left = Math.round(s.at.x - w / 2) + 'px';
      cap.style.top = Math.round(s.at.y - h / 2) + 'px';
      cap.setAttribute('data-far-end', s.end);
      setOrRemove(cap, 'data-basis', s.basis && s.basis !== 'observed' ? s.basis : null);
      setOrRemove(cap, 'data-phase-tone', s.tone || null);
      setOrRemove(cap, 'data-sev', s.severity || null);
      cap.classList.toggle('is-lit', s.lit);
      if (cap.title !== s.title) cap.title = s.title;
    });
  }

  /** The walk bar's line has the pointer or the focus: the caps answer. */
  cue(on: boolean): void {
    this.cued = on;
    for (const cap of this.caps) cap.classList.toggle('is-cued', on);
  }

  get count(): number {
    return this.caps.length;
  }
}

/** Set an attribute, or remove it for no value; nothing is written when it already holds the value. */
export function setOrRemove(element: Element, name: string, value: string | null | undefined): void {
  if (value === null || value === undefined || value === '') element.removeAttribute(name);
  else if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}
