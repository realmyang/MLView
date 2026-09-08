/**
 * Roving-tabindex focus management for the chrome (VIEW-12).
 *
 * The measured cost of reaching the diagram from the top of the document was
 * **22 Tab presses**: the scope button, the search box, three severity chips,
 * the suppressed chip, the flow toggle, the legend toggle, four viewport
 * buttons, refresh, export, the rail toggle, four theme chips and seven stage
 * chips, each its own tab stop, all of them before the canvas.
 *
 * The ARIA toolbar pattern is the standard answer: the whole control strip is
 * ONE tab stop and the arrow keys move inside it. That alone takes the path to
 * the canvas from 22 presses to 3 (skip link, toolbar, search box, canvas — the
 * search input keeps its own stop, as text inputs conventionally do, and must,
 * since its own arrow keys drive the results listbox and the caret).
 *
 * Rules this implements, all from the pattern:
 *
 *   - exactly one item in the group has `tabindex="0"`; every other has `-1`;
 *   - Arrow keys move the focus and the tab stop together, wrapping at the ends;
 *     Home / End jump to the first and last item;
 *   - focusing an item by pointer makes it the tab stop, so Shift+Tab and Tab
 *     return to where the user actually was;
 *   - a text input inside the toolbar is never taken over: it keeps `tabindex=0`
 *     and every key it receives is left alone;
 *   - `sync()` re-derives the item list after the chrome re-renders (the stage
 *     chip row is rebuilt on every update), keeping the tab stop on the same
 *     element when it survived and on the same INDEX when it did not.
 *
 * It is deliberately generic and DOM-only: no graph knowledge, no callbacks.
 */

import { on } from '../dom.js';

/** Focusable controls the roving group owns. Text inputs are excluded on purpose. */
const ITEM_SELECTOR = 'button, [role="button"], a[href], select';

export class RovingGroup {
  private container: HTMLElement;
  /** Elements that keep their own Tab stop and their own keys. */
  private ownStopSelector: string;
  private activeIndex = 0;
  private disposers: (() => void)[] = [];

  constructor(container: HTMLElement, ownStopSelector = 'input, textarea') {
    this.container = container;
    this.ownStopSelector = ownStopSelector;
    this.disposers.push(on(container, 'keydown', (ev: KeyboardEvent) => this.onKey(ev)));
    this.disposers.push(
      on(container, 'focusin', (ev: FocusEvent) => {
        const target = ev.target as HTMLElement | null;
        if (!target || typeof target.closest !== 'function') return;
        const items = this.items();
        const at = items.indexOf(target);
        if (at >= 0) this.setActive(at, false);
      }),
    );
    this.sync();
  }

  /** Every roving item, in DOM order, skipping hidden and disabled controls. */
  private items(): HTMLElement[] {
    const found = this.container.querySelectorAll(ITEM_SELECTOR);
    const out: HTMLElement[] = [];
    for (let i = 0; i < found.length; i++) {
      const element = found[i] as HTMLElement;
      if ((element as HTMLButtonElement).disabled) continue;
      if (element.hidden) continue;
      if (typeof element.closest === 'function' && element.closest('[hidden]')) continue;
      if (element.getAttribute('aria-hidden') === 'true') continue;
      out.push(element);
    }
    return out;
  }

  /** Text inputs keep their own stop; nothing here touches them. */
  private ownStops(): HTMLElement[] {
    const found = this.container.querySelectorAll(this.ownStopSelector);
    const out: HTMLElement[] = [];
    for (let i = 0; i < found.length; i++) out.push(found[i] as HTMLElement);
    return out;
  }

  /**
   * Re-derive the tab stop after a re-render. The chrome rebuilds its stage chip
   * row on every update, so the previously active element may be gone; the index
   * is kept instead, which lands on the chip in the same position.
   */
  sync(): void {
    const items = this.items();
    for (const input of this.ownStops()) input.tabIndex = 0;
    if (!items.length) return;
    const doc = this.container.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    const focused = active ? items.indexOf(active) : -1;
    const index = focused >= 0 ? focused : Math.min(this.activeIndex, items.length - 1);
    this.activeIndex = index;
    for (let i = 0; i < items.length; i++) items[i].tabIndex = i === index ? 0 : -1;
  }

  private setActive(index: number, moveFocus: boolean): void {
    const items = this.items();
    if (!items.length) return;
    const at = ((index % items.length) + items.length) % items.length;
    this.activeIndex = at;
    for (let i = 0; i < items.length; i++) items[i].tabIndex = i === at ? 0 : -1;
    if (!moveFocus) return;
    try {
      items[at].focus();
    } catch (_e) {
      /* a host may have detached the control mid-gesture */
    }
  }

  private onKey(ev: KeyboardEvent): void {
    const target = ev.target as HTMLElement | null;
    if (!target || typeof target.closest !== 'function') return;
    // A text field owns every key it gets: Left / Right move the caret and
    // Down opens the search results listbox (ui/searchcontroller.ts).
    if (target.closest(this.ownStopSelector)) return;
    const items = this.items();
    const at = items.indexOf(target);
    if (at < 0) return;
    let next = -1;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') next = at + 1;
    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') next = at - 1;
    else if (ev.key === 'Home') next = 0;
    else if (ev.key === 'End') next = items.length - 1;
    else return;
    ev.preventDefault();
    ev.stopPropagation();
    this.setActive(next, true);
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
