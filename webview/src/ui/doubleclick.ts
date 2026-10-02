/**
 * A double-click opens what its first click selected (viewer M1 review: M1-R1, M1-R3, UX-1).
 *
 * A click selects and shows the claim, and that first click changes the page under the pointer:
 * the Findings and Outline rows are rebuilt, a finding expanded above the clicked one collapses so
 * the rows shift, and a rail that the width rule had closed opens (docked, the canvas refits; in a
 * narrow panel, the bottom sheet opens under the pointer and the canvas above it shrinks). The
 * second click of the same double-click, and the browser's `dblclick`, then land on a detached row,
 * another row, the sheet's tab strip, the canvas background or a Selection pane control.
 *
 * The browser counts the clicks of one double-click in `MouseEvent.detail`, with its own interval
 * and distance, whatever the second click lands on. So the first click arms an opener for what it
 * selected; a capture listener on the app root takes any later click of the same sequence
 * (`detail >= 2`) before anything under the pointer sees it, and runs that opener. The rest of the
 * sequence (its `mousedown`s, further clicks and the `dblclick`) is swallowed, so nothing opens
 * twice, no Selection pane control is pressed and focus stays where the first click left it.
 */

import { on } from '../dom.js';

export class DoubleClickOpener {
  /** What the last single click selected, ready to open. */
  private armed: (() => void) | null = null;
  /** This click sequence already opened something; swallow the rest of it. */
  private consumed = false;
  private disposers: (() => void)[] = [];

  constructor(root: HTMLElement) {
    this.disposers.push(
      on(root, 'mousedown', (ev: MouseEvent) => {
        // Keeps focus and the text selection where the first click left them.
        if (ev.detail >= 2 && (this.armed || this.consumed)) ev.preventDefault();
      }, true),
      on(root, 'click', (ev: MouseEvent) => this.onClick(ev), true),
      on(root, 'dblclick', (ev: MouseEvent) => {
        if (!this.consumed) return;
        ev.preventDefault();
        ev.stopPropagation();
      }, true),
    );
  }

  /**
   * A pointer click (`detail` 1) selected something; `open` opens its cited source. Keyboard
   * activation (`detail` 0) and the clicks of a running sequence arm nothing.
   */
  arm(ev: MouseEvent | undefined, open: () => void): void {
    if (!ev || ev.detail !== 1) return;
    this.armed = open;
    this.consumed = false;
  }

  dispose(): void {
    for (const dispose of this.disposers) dispose();
    this.disposers = [];
    this.armed = null;
  }

  private onClick(ev: MouseEvent): void {
    if (ev.detail >= 2 && (this.armed || this.consumed)) {
      ev.preventDefault();
      ev.stopPropagation();
      const open = this.armed;
      this.armed = null;
      this.consumed = true;
      if (open) open();
      return;
    }
    // A new click sequence (or a keyboard click): whatever it lands on may arm again.
    this.armed = null;
    this.consumed = false;
  }
}
