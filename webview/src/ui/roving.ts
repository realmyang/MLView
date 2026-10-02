/**
 * Roving-tabindex focus management for the chrome (VIEW-12).
 *
 * The measured cost of reaching the diagram from the top of the document was
 * **22 Tab presses**: the scope button, the search box, three severity chips,
 * the flow toggle, the legend toggle, four viewport
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
 *   - `sync()` re-derives the item list after the chrome re-renders or changes
 *     shape (a width that hides controls, a search field that opens), keeping the
 *     tab stop on the same element when it is still an item and on the same
 *     INDEX when it is not;
 *   - an item must be rendered: a control a stylesheet hides is skipped.
 *
 * It is deliberately generic and DOM-only: no graph knowledge, no callbacks.
 */

import { on } from '../dom.js';

/** Focusable controls the roving group owns. Text inputs are excluded on purpose. */
const ITEM_SELECTOR = 'button, [role="button"], a[href], select';

/** The element has a box: it is not `display: none`, not inside one, and attached. */
function isRendered(element: HTMLElement): boolean {
  return typeof element.getClientRects === 'function' && element.getClientRects().length > 0;
}

export class RovingGroup {
  private container: HTMLElement;
  /** Elements that keep their own Tab stop and their own keys. */
  private ownStopSelector: string;
  private activeIndex = 0;
  /**
   * The control the user put the tab stop on (focus, arrows), kept across a re-render that leaves
   * it in place. Null until the user moves it: the stop is then the first item.
   */
  private activeEl: HTMLElement | null = null;
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

  /**
   * Every roving item, in DOM order, skipping hidden, disabled and unrendered controls.
   *
   * Viewer M2 review (M2R-1, A11Y-1): a control a stylesheet hides (`display: none` for a
   * `data-layout`) has no `hidden` attribute, yet it cannot take the focus. Left in the list it
   * could hold the group's only `tabindex="0"`, and then Tab skipped the whole header (541 px), or
   * ArrowRight "moved" to it and the focus stayed put (1440 px). So an item must be rendered:
   * `getClientRects()` is empty for an element that is `display: none` or inside one. That test
   * runs only while the container itself is rendered; a container with no boxes (jsdom, which lays
   * nothing out, or a detached header) keeps the attribute checks alone.
   */
  private items(): HTMLElement[] {
    const found = this.container.querySelectorAll(ITEM_SELECTOR);
    const rendered = isRendered(this.container);
    const out: HTMLElement[] = [];
    for (let i = 0; i < found.length; i++) {
      const element = found[i] as HTMLElement;
      if ((element as HTMLButtonElement).disabled) continue;
      if (element.hidden) continue;
      if (typeof element.closest === 'function' && element.closest('[hidden]')) continue;
      if (element.getAttribute('aria-hidden') === 'true') continue;
      // A search result is an option of the search field's listbox, driven by the field's keys.
      if (element.getAttribute('role') === 'option') continue;
      if (rendered && !isRendered(element)) continue;
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
   * Re-derive the tab stop after a re-render or a change of shape. The stop stays on its control
   * while that control is still an item; otherwise the index is kept.
   */
  sync(): void {
    const items = this.items();
    for (const input of this.ownStops()) input.tabIndex = 0;
    // Every owned control that is not an item (hidden, disabled, unrendered) is out of the Tab order.
    const all = this.container.querySelectorAll(ITEM_SELECTOR);
    for (let i = 0; i < all.length; i++) {
      const element = all[i] as HTMLElement;
      if (items.indexOf(element) < 0 && element.getAttribute('role') !== 'option') element.tabIndex = -1;
    }
    if (!items.length) return;
    const doc = this.container.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    const focused = active ? items.indexOf(active) : -1;
    // The focused control; else the control the user left the stop on, while it is still an item
    // (a layout change that hid an earlier control must not move it), else the same position; and
    // the first item until the user has moved the stop at all.
    const kept = this.activeEl ? items.indexOf(this.activeEl) : -1;
    const index = focused >= 0 ? focused : kept >= 0 ? kept : this.activeEl ? Math.min(this.activeIndex, items.length - 1) : 0;
    this.activeIndex = index;
    if (focused >= 0 || this.activeEl) this.activeEl = items[index];
    for (let i = 0; i < items.length; i++) items[i].tabIndex = i === index ? 0 : -1;
  }

  private setActive(index: number, moveFocus: boolean): void {
    const items = this.items();
    if (!items.length) return;
    const at = ((index % items.length) + items.length) % items.length;
    this.activeIndex = at;
    this.activeEl = items[at];
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
