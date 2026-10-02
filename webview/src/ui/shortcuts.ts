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

    // Viewer M1: the pointer gestures, which KEYMAP (keys only) cannot list. Only what each
    // target does (DOC-1): a group's double-click collapses it, and the Outline's connection and
    // phase rows only select.
    add(panel, el('p', 'mlv-sheet__note',
      'Click a card, connection, finding or Outline row to select it and read its claim. ' +
      'Double-click a step, connection, finding or Outline step, or press Enter on it, to open the cited source beside the diagram; focus stays here. ' +
      'Double-click a group to collapse it. ' +
      'Alt+click an Open link, or press Alt+Enter, to move focus to the editor.'));
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
