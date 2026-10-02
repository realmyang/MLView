/**
 * The header's ... menu (viewer M2): the view toggles, the whole-diagram fit, the exports and the
 * shortcut sheet, plus whatever a narrow header has no room for (search and the revision).
 *
 * The standard menu-button pattern, as the export menu it replaces used it (VW-03): the trigger is
 * an item of the header's roving toolbar, and the panel is mounted on the app root, so its items
 * never join the toolbar's arrow keys. Opening focuses the first item; the arrow keys, Home and End
 * move inside; Escape (from anywhere) and Tab close it and give the focus back to the trigger;
 * a pointer press outside closes it. Each item does one thing and closes the menu.
 */

import { add, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';

/** The three exports the menu offers, all of the whole diagram (VIEW-07). */
export type ExportActionId = 'svg' | 'png' | 'copy-svg';

export type MoreItemId =
  | 'search'
  | 'about'
  | 'legend'
  | 'flow'
  | 'minimap'
  | 'rail'
  | 'fit'
  | 'zoomsel'
  | ExportActionId
  | 'shortcuts';

interface ItemSpec {
  id: MoreItemId;
  label: string;
  icon: string;
  /** The key that does the same, shown at the right edge. */
  keys?: string;
  /** A checkbox item: `aria-checked` says whether the thing is on. */
  check?: boolean;
  /** Shown only when the header itself has no room for this control (a narrow panel). */
  narrowOnly?: boolean;
  /** Starts a new group (a separator above it). */
  group?: boolean;
}

const ITEMS: ItemSpec[] = [
  { id: 'search', label: 'Search steps and findings', icon: 'search', keys: 'Ctrl+K', narrowOnly: true },
  { id: 'about', label: 'About this revision', icon: 'info', narrowOnly: true },
  { id: 'legend', label: 'Legend', icon: 'legend', keys: 'L', check: true, group: true },
  { id: 'flow', label: 'Connection flow animation', icon: 'flow', keys: 'A', check: true },
  { id: 'minimap', label: 'Overview map', icon: 'minimap', check: true },
  { id: 'rail', label: 'Side panel', icon: 'rail', keys: 'Ctrl+B', check: true },
  { id: 'fit', label: 'Fit the whole diagram', icon: 'fit', group: true },
  { id: 'zoomsel', label: 'Zoom to the selection', icon: 'target', keys: 'Z' },
  { id: 'svg', label: 'Export SVG…', icon: 'image', group: true },
  { id: 'png', label: 'Export PNG…', icon: 'image' },
  { id: 'copy-svg', label: 'Copy SVG', icon: 'copy' },
  { id: 'shortcuts', label: 'Keyboard shortcuts', icon: 'keyboard', keys: '?', group: true },
];

const EXPORTS: readonly string[] = ['svg', 'png', 'copy-svg'];

export interface MoreMenuState {
  /** The header is narrow: search and the revision live in this menu. */
  narrow: boolean;
  /** The narrow header's `about` item: "About revision r2 · host" (the chip has no room there). */
  aboutLabel: string;
  legendOpen: boolean;
  flowOn: boolean;
  minimapShown: boolean;
  railOpen: boolean;
  /** Viewer M2: the rail item is "Side panel" while docked and "Bottom panel" as a sheet. */
  railMode: 'docked' | 'sheet';
  hasSelection: boolean;
  /** Something is drawn, so the exports have a picture to export. */
  canExport: boolean;
}

let menuSeq = 0;

export class MoreMenu {
  /** Goes in the header's toolbar. */
  readonly button: HTMLButtonElement;
  /** Goes on the app root, outside the toolbar's roving group. */
  readonly panel: HTMLElement;

  private items = new Map<MoreItemId, HTMLButtonElement>();
  private onPick: (id: MoreItemId, byKeyboard: boolean) => void;
  private beforeOpen: () => void;
  private openState = false;
  private disposers: (() => void)[] = [];

  /**
   * `beforeOpen` runs as the menu opens, so the owner can bring the items up to date first.
   * `onPick` learns whether the item was chosen from the keyboard (a click with no pointer detail).
   */
  constructor(onPick: (id: MoreItemId, byKeyboard: boolean) => void, beforeOpen: () => void = () => undefined) {
    this.onPick = onPick;
    this.beforeOpen = beforeOpen;
    const uid = 'mlv-more' + ++menuSeq;

    this.button = iconButton('mlv-btn mlv-btn--icon mlv-btn--more', 'More actions');
    this.button.title = 'More: legend, flow, fit, export, shortcuts';
    this.button.appendChild(uiIcon('more', 16));
    this.button.setAttribute('aria-haspopup', 'menu');
    this.button.setAttribute('aria-expanded', 'false');
    this.button.setAttribute('aria-controls', uid);
    on(this.button, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.setOpen(!this.openState);
    });
    // VW-03: every key the trigger answers stops propagation, or the roving toolbar's container
    // listener reads ArrowDown as "next toolbar button" and wins.
    on(this.button, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        if (!this.openState) return;
        ev.preventDefault();
        ev.stopPropagation();
        this.setOpen(false);
        return;
      }
      if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return;
      ev.preventDefault();
      ev.stopPropagation();
      this.setOpen(true);
      this.focusItem(ev.key === 'ArrowDown' ? 0 : this.shown().length - 1);
    });

    this.panel = el('div', 'mlv-moremenu');
    this.panel.id = uid;
    this.panel.setAttribute('role', 'menu');
    this.panel.setAttribute('aria-label', 'More actions');
    this.panel.hidden = true;
    for (const spec of ITEMS) {
      if (spec.group) {
        const sep = add(this.panel, el('div', 'mlv-moremenu__sep'));
        sep.setAttribute('role', 'separator');
        sep.setAttribute('data-sep-before', spec.id);
      }
      const item = el('button', 'mlv-moremenu__item') as HTMLButtonElement;
      item.type = 'button';
      item.tabIndex = -1;
      item.setAttribute('role', spec.check ? 'menuitemcheckbox' : 'menuitem');
      item.setAttribute('data-more-item', spec.id);
      if (EXPORTS.indexOf(spec.id) >= 0) item.setAttribute('data-export-action', spec.id);
      if (spec.narrowOnly) item.setAttribute('data-narrow-only', '1');
      item.appendChild(uiIcon(spec.icon, 14));
      add(item, el('span', 'mlv-moremenu__label', spec.label));
      if (spec.keys) add(item, el('kbd', 'mlv-moremenu__keys', spec.keys)).setAttribute('aria-hidden', 'true');
      on(item, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        if (item.disabled) return;
        const byKeyboard = ev.detail === 0;
        this.setOpen(false);
        this.onPick(spec.id, byKeyboard);
      });
      this.panel.appendChild(item);
      this.items.set(spec.id, item);
    }
    on(this.panel, 'keydown', (ev: KeyboardEvent) => this.onKey(ev));

    const doc = typeof document === 'undefined' ? null : document;
    if (doc) {
      this.disposers.push(
        on(doc, 'pointerdown', (ev: PointerEvent) => {
          if (!this.openState) return;
          const target = ev.target as HTMLElement | null;
          if (target && (this.panel.contains(target) || this.button.contains(target))) return;
          this.setOpen(false);
        }),
      );
      // Escape closes the open menu from anywhere, before the app's own Escape cascade sees it.
      this.disposers.push(
        on(
          doc,
          'keydown',
          (ev: KeyboardEvent) => {
            if (!this.openState || ev.key !== 'Escape') return;
            ev.preventDefault();
            ev.stopPropagation();
            const active = doc.activeElement as HTMLElement | null;
            const inside = !!active && (this.panel.contains(active) || this.button.contains(active));
            this.setOpen(false);
            if (inside) this.focusButton();
          },
          true,
        ),
      );
    }
  }

  get open(): boolean {
    return this.openState;
  }

  update(s: MoreMenuState): void {
    for (const [id, item] of this.items) {
      const spec = ITEMS.find((x) => x.id === id)!;
      const shown = !spec.narrowOnly || s.narrow;
      item.hidden = !shown;
      if (id === 'about') {
        const label = item.querySelector('.mlv-moremenu__label');
        if (label) label.textContent = s.aboutLabel;
        item.title = 'Show About: the request, coverage, limitations and provenance';
      }
      if (id === 'rail') {
        const label = item.querySelector('.mlv-moremenu__label');
        if (label) label.textContent = s.railMode === 'sheet' ? 'Bottom panel' : 'Side panel';
        item.title = s.railMode === 'sheet' ? 'Open or collapse the bottom panel' : 'Show or hide the side panel';
      }
      if (spec.check) {
        const on_ = id === 'legend' ? s.legendOpen : id === 'flow' ? s.flowOn : id === 'minimap' ? s.minimapShown : s.railOpen;
        item.setAttribute('aria-checked', on_ ? 'true' : 'false');
      }
      if (id === 'zoomsel') item.disabled = !s.hasSelection;
      if (EXPORTS.indexOf(id) >= 0) item.disabled = !s.canExport;
      if (item.disabled) item.setAttribute('aria-disabled', 'true');
      else item.removeAttribute('aria-disabled');
    }
    // A separator never leads the menu: the first shown group has none above it.
    const first = this.shown()[0];
    for (const sep of Array.from(this.panel.querySelectorAll<HTMLElement>('.mlv-moremenu__sep'))) {
      sep.hidden = !!first && sep.getAttribute('data-sep-before') === first.getAttribute('data-more-item');
    }
  }

  setOpen(next: boolean): void {
    if (this.openState === next) return;
    this.openState = next;
    this.panel.hidden = !next;
    this.button.setAttribute('aria-expanded', next ? 'true' : 'false');
    if (next) {
      try {
        this.beforeOpen();
      } catch (_e) {
        /* a stale item is better than no menu */
      }
      this.position();
      this.focusItem(0);
    } else {
      const active = this.panel.ownerDocument ? (this.panel.ownerDocument.activeElement as HTMLElement | null) : null;
      if (active && this.panel.contains(active)) this.focusButton();
    }
  }

  /** The items a reader can reach now: shown and enabled. */
  private shown(): HTMLButtonElement[] {
    return Array.from(this.items.values()).filter((item) => !item.hidden && !item.disabled);
  }

  /** Under the trigger, right-aligned to it, kept inside the panel. */
  private position(): void {
    let rect: { bottom: number; right: number } | null = null;
    try {
      rect = this.button.getBoundingClientRect();
    } catch (_e) {
      rect = null;
    }
    if (!rect) return;
    this.panel.style.position = 'fixed';
    this.panel.style.top = Math.round(rect.bottom + 4) + 'px';
    this.panel.style.left = 'auto';
    this.panel.style.right = Math.max(8, Math.round(viewportWidth() - rect.right)) + 'px';
  }

  private focusItem(index: number): void {
    const items = this.shown();
    if (!items.length) return;
    const at = ((index % items.length) + items.length) % items.length;
    try {
      items[at].focus();
    } catch (_e) {
      /* a host may have detached the panel mid-gesture */
    }
  }

  private focusButton(): void {
    try {
      this.button.focus();
    } catch (_e) {
      /* the header may have been rebuilt under us */
    }
  }

  private onKey(ev: KeyboardEvent): void {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      ev.stopPropagation();
      this.setOpen(false);
      return;
    }
    if (ev.key === 'Tab') {
      this.setOpen(false);
      return;
    }
    const items = this.shown();
    const at = items.indexOf(ev.target as HTMLButtonElement);
    if (at < 0) return;
    if (ev.key === 'ArrowDown') this.focusItem(at + 1);
    else if (ev.key === 'ArrowUp') this.focusItem(at - 1);
    else if (ev.key === 'Home') this.focusItem(0);
    else if (ev.key === 'End') this.focusItem(items.length - 1);
    else return;
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

function viewportWidth(): number {
  try {
    if (typeof window !== 'undefined' && window.innerWidth) return window.innerWidth;
  } catch (_e) {
    /* no window */
  }
  return 1280;
}
