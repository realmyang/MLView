/**
 * The `?` shortcut sheet (UX_DESIGN §9). It renders `KEYMAP` directly, which is
 * the point: the documented bindings and the implemented ones are one array.
 */

import { add, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { KEYMAP } from './keymap.js';
import { isMac, keyLabel } from './platform.js';
import { restoreFocus, trapTab } from './focustrap.js';

export class ShortcutSheet {
  readonly root: HTMLElement;
  private closeBtn: HTMLButtonElement;
  private panel: HTMLElement;
  /** Viewer M2: what had the focus when the sheet opened; it gets it back on close. */
  private opener: HTMLElement | null = null;

  constructor(onClose: () => void) {
    this.root = el('div', 'mlv-sheet');
    this.root.hidden = true;
    const scrim = add(this.root, el('div', 'mlv-sheet__scrim'));
    on(scrim, 'click', () => onClose());

    const panel = add(this.root, el('div', 'mlv-sheet__panel'));
    this.panel = panel;
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
    // focus on open, so the canvas key handler never sees the key. Viewer M2: it is a modal
    // dialog, so Tab stays inside it.
    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (trapTab(this.panel, ev)) {
        ev.stopPropagation();
        return;
      }
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      onClose();
    });

    // Viewer M1: the pointer gestures, which KEYMAP (keys only) cannot list. Only what each
    // target does (DOC-1): a group's double-click collapses it, and the Outline's connection and
    // phase rows only select.
    // Viewer M2 live fix: every key is printed for the reader's platform (⌘F, ⌥Enter on macOS).
    const mac = isMac();
    const alt = mac ? 'Option' : 'Alt';
    add(panel, el('p', 'mlv-sheet__note',
      'Click a card, connection, finding or Outline row to select it and read its claim. ' +
      'Double-click a step, connection, finding or Outline step, or press Enter on it, to open the cited source beside the diagram; focus stays here. ' +
      'Double-click a group to collapse it. ' +
      alt + '+click an Open link, or press ' + keyLabel('Alt+Enter', mac) + ', to move focus to the editor.'));
    const list = add(panel, el('dl', 'mlv-sheet__list'));
    for (const binding of KEYMAP) {
      const keys = add(list, el('dt', 'mlv-sheet__keys'));
      for (const k of binding.keys) add(keys, el('kbd', 'mlv-kbd', keyLabel(k, mac)));
      add(list, el('dd', 'mlv-sheet__desc', binding.description));
    }
  }

  get open(): boolean {
    return !this.root.hidden;
  }

  show(): void {
    if (!this.open) {
      const doc = this.root.ownerDocument;
      const active = doc ? (doc.activeElement as HTMLElement | null) : null;
      this.opener = active && !this.root.contains(active) ? active : null;
    }
    this.root.hidden = false;
    try {
      this.closeBtn.focus();
    } catch (_e) {
      /* a detached sheet cannot take focus */
    }
  }

  /** Close; the focus goes back to what had it when the sheet opened, else to `fallback`. */
  hide(fallback: HTMLElement | null = null): void {
    const wasOpen = this.open;
    this.root.hidden = true;
    if (!wasOpen) return;
    const opener = this.opener;
    this.opener = null;
    restoreFocus(opener, fallback);
  }

  toggle(): boolean {
    if (this.open) this.hide();
    else this.show();
    return this.open;
  }
}
