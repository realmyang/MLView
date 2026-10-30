/**
 * Theme ownership for the viewer.
 *
 * The renderer stamps `data-theme="light|dark|hc"` on the element it mounts into,
 * never on `<html>`, which belongs to the host, and `styles/tokens.css` keys every
 * palette on `.mlv-root[data-theme=…]` as well as `:root[data-theme=…]` so that
 * attribute actually repaints.
 *
 * In a VS Code webview the host owns the theme and pushes it over the `theme`
 * message.
 */

import type { ThemeKind } from '../types.js';

/** The three themes `styles/tokens.css` defines a palette for. */
export function isThemeKind(value: unknown): value is ThemeKind {
  return value === 'light' || value === 'dark' || value === 'hc';
}

export class ThemeController {
  private root: HTMLElement;
  private current: ThemeKind;

  constructor(root: HTMLElement, theme: ThemeKind) {
    this.root = root;
    this.current = isThemeKind(theme) ? theme : 'light';
  }

  get kind(): ThemeKind {
    return this.current;
  }

  /**
   * Apply a resolved theme. The host message and the public setTheme land here.
   * A value outside `light` / `dark` / `hc` (for example `high-contrast`) has
   * no palette, so it is ignored and the current theme stays.
   */
  apply(kind: ThemeKind): void {
    if (!isThemeKind(kind)) return;
    this.current = kind;
    this.root.setAttribute('data-theme', kind);
  }

  destroy(): void {
    this.root.removeAttribute('data-theme');
  }
}
