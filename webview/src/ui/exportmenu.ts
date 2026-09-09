/**
 * The export menu (VIEW-07) — one button beside Fit, one popup.
 *
 * Two things are chosen here and nothing else is decided: WHICH REGION
 * (current view / whole diagram / current scope) and WHICH OUTPUT (SVG, 2× PNG,
 * copy PNG, copy SVG, print). The region is a `menuitemradio` group because it
 * is a persistent choice the next output inherits; the outputs are plain
 * `menuitem`s because each one does its thing and closes.
 *
 * The popup is mounted on the APP ROOT, not inside the toolbar. The chrome is
 * one roving `role="toolbar"` (VIEW-12) and an open menu inside it would put
 * eight more controls under the toolbar's arrow keys, which is exactly the
 * flattening the roving group exists to undo. So the trigger stays a toolbar
 * item and the panel is a sibling with its own arrow keys, its own Escape and
 * its own focus return — the standard menu-button pattern.
 */

import { add, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { EXPORT_REGIONS, ExportRegionKind } from '../export/svg.js';

export type ExportActionId = 'svg' | 'png' | 'copy-png' | 'copy-svg' | 'print';

interface ActionRow {
  id: ExportActionId;
  label: string;
  hint: string;
}

const ACTIONS: ActionRow[] = [
  { id: 'svg', label: 'Save SVG', hint: 'Vector, no external references — opens in a browser or Inkscape.' },
  { id: 'png', label: 'Save PNG (2×)', hint: 'Drawn from that same SVG, at twice the size.' },
  { id: 'copy-png', label: 'Copy PNG', hint: 'Straight onto the clipboard, for a PR or a slide.' },
  { id: 'copy-svg', label: 'Copy SVG', hint: 'The markup itself, for a doc that embeds vectors.' },
  { id: 'print', label: 'Print / Save as PDF…', hint: 'The whole diagram at natural size, no toolbar or rail.' },
];

export interface ExportMenuCallbacks {
  onRegion(kind: ExportRegionKind): void;
  onAction(action: ExportActionId): void;
}

let menuSeq = 0;

export class ExportMenu {
  /** Goes in the toolbar, beside Fit. */
  readonly button: HTMLButtonElement;
  /** Goes on the app root, so the toolbar's roving group never sees it. */
  readonly panel: HTMLElement;

  private cb: ExportMenuCallbacks;
  private regionButtons = new Map<ExportRegionKind, HTMLButtonElement>();
  private actionButtons: HTMLButtonElement[] = [];
  private region: ExportRegionKind = 'diagram';
  private openState = false;
  private disposers: (() => void)[] = [];

  constructor(cb: ExportMenuCallbacks) {
    this.cb = cb;
    const uid = 'mlv-export' + ++menuSeq;

    this.button = iconButton('mlv-btn mlv-btn--icon mlv-btn--exportmenu', 'Export the diagram');
    this.button.appendChild(uiIcon('image'));
    this.button.setAttribute('aria-haspopup', 'menu');
    this.button.setAttribute('aria-expanded', 'false');
    this.button.setAttribute('aria-controls', uid);
    on(this.button, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.setOpen(!this.openState);
    });
    // VW-03. Every key here STOPS PROPAGATION. The trigger is a toolbar item,
    // and the toolbar is one roving `role="toolbar"` whose keydown listener sits
    // on the container: it reads ArrowDown as "next toolbar button", calls
    // preventDefault + stopPropagation and moves focus. Without the stop below
    // the roving group ran after this handler and won — the menu opened and
    // focus landed on "Toggle side rail", outside it.
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
      this.focusItem(ev.key === 'ArrowDown' ? 0 : this.items().length - 1);
    });

    this.panel = el('div', 'mlv-exportmenu');
    this.panel.id = uid;
    this.panel.setAttribute('role', 'menu');
    this.panel.setAttribute('aria-label', 'Export the diagram');
    this.panel.hidden = true;

    const regionGroup = add(this.panel, el('div', 'mlv-exportmenu__group'));
    regionGroup.setAttribute('role', 'group');
    regionGroup.setAttribute('aria-label', 'What to export');
    add(regionGroup, el('div', 'mlv-exportmenu__label', 'Region'));
    for (const region of EXPORT_REGIONS) {
      const item = el('button', 'mlv-exportmenu__item mlv-exportmenu__item--region') as HTMLButtonElement;
      item.type = 'button';
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', region.id === this.region ? 'true' : 'false');
      item.setAttribute('data-export-region', region.id);
      item.tabIndex = -1;
      item.title = region.hint;
      add(item, el('span', 'mlv-exportmenu__name', region.label));
      add(item, el('span', 'mlv-exportmenu__hint', region.hint));
      on(item, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        if (item.disabled) return;
        this.setRegion(region.id);
        this.cb.onRegion(region.id);
      });
      regionGroup.appendChild(item);
      this.regionButtons.set(region.id, item);
    }

    const sep = add(this.panel, el('div', 'mlv-exportmenu__sep'));
    sep.setAttribute('role', 'separator');

    const actionGroup = add(this.panel, el('div', 'mlv-exportmenu__group'));
    actionGroup.setAttribute('role', 'group');
    actionGroup.setAttribute('aria-label', 'Output');
    for (const action of ACTIONS) {
      const item = el('button', 'mlv-exportmenu__item') as HTMLButtonElement;
      item.type = 'button';
      item.setAttribute('role', 'menuitem');
      item.setAttribute('data-export-action', action.id);
      item.tabIndex = -1;
      item.title = action.hint;
      add(item, el('span', 'mlv-exportmenu__name', action.label));
      add(item, el('span', 'mlv-exportmenu__hint', action.hint));
      on(item, 'click', (ev: MouseEvent) => {
        ev.preventDefault();
        this.setOpen(false);
        this.cb.onAction(action.id);
      });
      actionGroup.appendChild(item);
      this.actionButtons.push(item);
    }

    on(this.panel, 'keydown', (ev: KeyboardEvent) => this.onKey(ev));

    // Anything outside the menu closes it — a popup that survives the next
    // click is a popup covering the diagram it is about to export.
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
      // VW-03. Escape closes an open menu from ANYWHERE, not only from inside
      // the panel — a 268 x 478 px popup over the diagram with no keyboard way
      // out is a trap. Capture phase, so it is the innermost thing Escape
      // dismisses: the app's own Escape cascade (clear selection, leave the
      // canvas) never sees the key while this menu is open.
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
            if (inside) {
              try {
                this.button.focus();
              } catch (_e) {
                /* the toolbar may have been rebuilt under us */
              }
            }
          },
          true,
        ),
      );
    }
  }

  get open(): boolean {
    return this.openState;
  }

  get currentRegion(): ExportRegionKind {
    return this.region;
  }

  setOpen(next: boolean): void {
    if (this.openState === next) return;
    this.openState = next;
    this.panel.hidden = !next;
    this.button.setAttribute('aria-expanded', next ? 'true' : 'false');
    if (next) {
      this.position();
      // VW-03. The menu-button pattern puts focus on the first item for EVERY
      // open gesture, not only for ArrowDown. Every item is `tabIndex = -1`, as
      // a `role="menu"` requires, so without this the panel was unreachable
      // after Enter or a click: Tab from the trigger went straight past eight
      // controls to the canvas.
      this.focusItem(0);
    } else {
      this.restoreFocus();
    }
  }

  setRegion(kind: ExportRegionKind): void {
    this.region = kind;
    for (const [id, item] of this.regionButtons) {
      item.setAttribute('aria-checked', id === kind ? 'true' : 'false');
    }
  }

  /**
   * "Current scope" is offered only when there IS one. A menu entry that can
   * only ever export the whole diagram under a different name is a lie about
   * what the tool did.
   */
  setScopeAvailable(available: boolean): void {
    const item = this.regionButtons.get('scope');
    if (!item) return;
    item.disabled = !available;
    item.setAttribute('aria-disabled', available ? 'false' : 'true');
    item.title = available
      ? 'The scoped subject only — the shareable artifact.'
      : 'Nothing is scoped: pick a scope first, or export the whole diagram.';
    if (!available && this.region === 'scope') {
      this.setRegion('diagram');
      this.cb.onRegion('diagram');
    }
  }

  /** Place the panel under the trigger. A host with no layout gets 0,0 — fine. */
  private position(): void {
    let rect: { left: number; bottom: number; right: number } | null = null;
    try {
      rect = this.button.getBoundingClientRect();
    } catch (_e) {
      rect = null;
    }
    if (!rect) return;
    this.panel.style.position = 'fixed';
    this.panel.style.top = Math.round(rect.bottom + 6) + 'px';
    this.panel.style.left = 'auto';
    this.panel.style.right = Math.max(8, Math.round(viewportWidth() - rect.right)) + 'px';
  }

  private items(): HTMLButtonElement[] {
    const out: HTMLButtonElement[] = [];
    for (const region of EXPORT_REGIONS) {
      const item = this.regionButtons.get(region.id);
      if (item && !item.disabled) out.push(item);
    }
    for (const item of this.actionButtons) out.push(item);
    return out;
  }

  private focusItem(index: number): void {
    const items = this.items();
    if (!items.length) return;
    const at = ((index % items.length) + items.length) % items.length;
    try {
      items[at].focus();
    } catch (_e) {
      /* a host may have detached the panel mid-gesture */
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
    const items = this.items();
    const target = ev.target as HTMLElement | null;
    const at = target ? items.indexOf(target as HTMLButtonElement) : -1;
    if (at < 0) return;
    if (ev.key === 'ArrowDown') this.focusItem(at + 1);
    else if (ev.key === 'ArrowUp') this.focusItem(at - 1);
    else if (ev.key === 'Home') this.focusItem(0);
    else if (ev.key === 'End') this.focusItem(items.length - 1);
    else return;
    ev.preventDefault();
    ev.stopPropagation();
  }

  private restoreFocus(): void {
    const doc = this.panel.ownerDocument;
    const active = doc ? (doc.activeElement as HTMLElement | null) : null;
    if (!active || !this.panel.contains(active)) return;
    try {
      this.button.focus();
    } catch (_e) {
      /* the toolbar may have been rebuilt under us */
    }
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

/** Exported so a gate can state the menu's contents rather than re-typing them. */
export const EXPORT_ACTIONS = ACTIONS;
