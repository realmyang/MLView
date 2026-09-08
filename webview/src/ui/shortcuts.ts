/**
 * The `?` shortcut sheet (UX_DESIGN §9). It renders `KEYMAP` directly, which is
 * the point: the documented bindings and the implemented ones are one array.
 */

import { add, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { KEYMAP } from './keymap.js';

export class ShortcutSheet {
  readonly root: HTMLElement;
  private closeBtn: HTMLButtonElement;

  constructor(onClose: () => void) {
    this.root = el('div', 'mlv-sheet');
    this.root.hidden = true;
    const scrim = add(this.root, el('div', 'mlv-sheet__scrim'));
    on(scrim, 'click', () => onClose());

    const panel = add(this.root, el('div', 'mlv-sheet__panel'));
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', 'Keyboard shortcuts');

    const head = add(panel, el('div', 'mlv-sheet__head'));
    add(head, el('h2', 'mlv-sheet__title', 'Keyboard shortcuts'));
    this.closeBtn = iconButton('mlv-btn mlv-btn--icon', 'Close shortcuts');
    this.closeBtn.appendChild(uiIcon('close'));
    on(this.closeBtn, 'click', () => onClose());
    head.appendChild(this.closeBtn);

    // Escape must close the sheet from inside it too — the close button takes
    // focus on open, so the canvas key handler never sees the key.
    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      onClose();
    });

    const list = add(panel, el('dl', 'mlv-sheet__list'));
    for (const binding of KEYMAP) {
      const keys = add(list, el('dt', 'mlv-sheet__keys'));
      for (const k of binding.keys) add(keys, el('kbd', 'mlv-kbd', k));
      add(list, el('dd', 'mlv-sheet__desc', binding.description));
    }
  }

  get open(): boolean {
    return !this.root.hidden;
  }

  show(): void {
    this.root.hidden = false;
    try {
      this.closeBtn.focus();
    } catch (_e) {
      /* a detached sheet cannot take focus */
    }
  }

  hide(): void {
    this.root.hidden = true;
  }

  toggle(): boolean {
    if (this.open) this.hide();
    else this.show();
    return this.open;
  }
}
