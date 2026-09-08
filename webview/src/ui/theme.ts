/**
 * Theme ownership for the viewer.
 *
 * The renderer stamps `data-theme="light|dark|hc"` on the element it mounts into
 * (CONTRACTS amendment A3) — never on `<html>`, which belongs to the host — and
 * `styles/tokens.css` keys every palette on `.mlv-root[data-theme=…]` as well as
 * `:root[data-theme=…]` so that attribute actually repaints (MLV-R1-004).
 *
 * In a VS Code webview the host owns the theme and pushes it over the `theme`
 * message. The standalone report owns its own, so it also gets the Auto / Light /
 * Dark / High contrast switch UX_DESIGN §3 asks for, and follows the OS while the
 * preference is Auto.
 */

import { buildThemeSwitch, ThemeChoice } from '../bridges.js';
import type { ThemeKind } from '../types.js';

export function systemTheme(): ThemeKind {
  try {
    if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
  } catch (_e) {
    /* a host without matchMedia is treated as light */
  }
  return 'light';
}

function isChoice(value: unknown): value is ThemeChoice {
  return value === 'auto' || value === 'light' || value === 'dark' || value === 'hc';
}

export class ThemeController {
  private root: HTMLElement;
  private preference: ThemeChoice;
  private current: ThemeKind;
  private switchEl: HTMLElement | null = null;
  private stopWatch: (() => void) | null = null;

  constructor(root: HTMLElement, theme: ThemeKind, preference?: unknown) {
    this.root = root;
    this.current = theme;
    this.preference = isChoice(preference) ? preference : theme;
  }

  get kind(): ThemeKind {
    return this.current;
  }

  /** Apply a resolved theme. The host message and the public setTheme land here. */
  apply(kind: ThemeKind): void {
    this.current = kind;
    this.root.setAttribute('data-theme', kind);
    this.syncSwitch();
  }

  /** The standalone-only switch, appended to `host`. */
  mountSwitch(host: HTMLElement): void {
    this.switchEl = buildThemeSwitch(this.preference, (pick) => this.choose(pick));
    host.appendChild(this.switchEl);
    this.watch();
  }

  private choose(pick: ThemeChoice): void {
    this.preference = pick;
    this.watch();
    this.apply(pick === 'auto' ? systemTheme() : pick);
  }

  private syncSwitch(): void {
    if (!this.switchEl) return;
    for (const child of Array.from(this.switchEl.children)) {
      child.setAttribute('aria-pressed', child.getAttribute('data-theme-option') === this.preference ? 'true' : 'false');
    }
  }

  /** While the preference is Auto, follow the OS as it changes. */
  private watch(): void {
    if (this.stopWatch) {
      this.stopWatch();
      this.stopWatch = null;
    }
    if (this.preference !== 'auto' || typeof window === 'undefined' || !window.matchMedia) return;
    try {
      const query = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = () => {
        if (this.preference === 'auto') this.apply(systemTheme());
      };
      if (typeof query.addEventListener === 'function') {
        query.addEventListener('change', handler);
        this.stopWatch = () => query.removeEventListener('change', handler);
      }
    } catch (_e) {
      /* a host without matchMedia keeps the theme it was handed */
    }
  }

  destroy(): void {
    if (this.stopWatch) this.stopWatch();
    this.stopWatch = null;
    this.root.removeAttribute('data-theme');
  }
}
