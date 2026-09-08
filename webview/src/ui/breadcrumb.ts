/**
 * The scope breadcrumb — the first element after the brand, `role="status"`.
 *
 *   Scoped to baseline()  ·  depth 1  ·  13 of 45 nodes   [−] [+]   [×]
 *
 * Two things it must never get wrong:
 *
 *  - `13 of 45` comes from `view.of.nodes`, which is PROJECT-LEVEL truth, so a
 *    scoped view can never be read as a statement about the project;
 *  - `[×]`'s tooltip says "Filters are separate", because a scope and the stage
 *    filter chips are two narrowings living on one screen and that one sentence
 *    is what keeps them apart (FEATURES 3.8).
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import type { View } from '../types.js';

export interface BreadcrumbCallbacks {
  onClear(): void;
  onDepth(delta: number): void;
  onCopy(spec: string): void;
}

export class Breadcrumb {
  readonly root: HTMLElement;
  private cb: BreadcrumbCallbacks;

  constructor(cb: BreadcrumbCallbacks) {
    this.cb = cb;
    this.root = el('div', 'mlv-breadcrumb');
    this.root.setAttribute('role', 'status');
    this.root.hidden = true;
  }

  /** `view` null means the whole workspace: the chip disappears entirely. */
  update(view: View | null, truncated: boolean): void {
    clear(this.root);
    if (!view) {
      this.root.hidden = true;
      return;
    }
    this.root.hidden = false;
    this.root.title = view.scope;

    const icon = uiIcon('target', 13);
    icon.setAttribute('class', 'mlv-uicon mlv-breadcrumb__icon');
    this.root.appendChild(icon);

    add(this.root, el('span', 'mlv-breadcrumb__label', 'Scoped to ' + view.label));
    // The whole chip is one `role="status"` string, so the separators carry
    // their own spacing: a screen reader reads it as a sentence.
    add(this.root, el('span', 'mlv-breadcrumb__sep', ' · '));
    add(this.root, el('span', 'mlv-breadcrumb__depth', 'depth ' + view.depth));
    add(this.root, el('span', 'mlv-breadcrumb__sep', ' · '));
    // Under truncation the denominator is the CAPPED graph, and the truncation
    // banner stays up beside it, so neither number can be read as the project.
    const total = view.of.nodes;
    add(
      this.root,
      el(
        'span',
        'mlv-breadcrumb__count',
        view.counts.core + view.counts.boundary + view.counts.context + ' of ' + total + (truncated ? ' shown' : ' nodes'),
      ),
    );

    const steppers = add(this.root, el('div', 'mlv-breadcrumb__steppers'));
    const minus = iconButton('mlv-btn mlv-btn--icon', 'Narrow the scope by one hop');
    minus.appendChild(uiIcon('minus', 12));
    minus.disabled = view.depth <= 0;
    on(minus, 'click', () => this.cb.onDepth(-1));
    steppers.appendChild(minus);
    const plus = iconButton('mlv-btn mlv-btn--icon', 'Widen the scope by one hop');
    plus.appendChild(uiIcon('plus', 12));
    plus.disabled = view.depth >= 2;
    on(plus, 'click', () => this.cb.onDepth(1));
    steppers.appendChild(plus);

    const copy = button('mlv-btn mlv-breadcrumb__copy', 'Copy scope', 'Copy ' + view.scope + ' to the clipboard');
    on(copy, 'click', () => this.cb.onCopy(view.scope));
    this.root.appendChild(copy);

    const close = iconButton('mlv-btn mlv-btn--icon mlv-breadcrumb__clear', 'Clear the scope. Filters are separate.');
    close.appendChild(uiIcon('close', 12));
    on(close, 'click', () => this.cb.onClear());
    this.root.appendChild(close);
  }
}
