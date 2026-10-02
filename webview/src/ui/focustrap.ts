/**
 * Viewer M2: Tab and Shift+Tab stay inside a modal surface (the `?` shortcut sheet, the Refine…
 * popover), and closing it gives the focus back to what had it before (WCAG 2.4.3, 2.1.2: a trap
 * a reader can always leave with Escape).
 *
 * Only Tab is handled: arrow keys, Escape and everything else stay with the surface's own handlers.
 */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** The elements Tab can reach inside `container`, in document order: shown and enabled. */
export function tabbables(container: HTMLElement): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (const element of Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))) {
    if (element.tabIndex < 0) continue;
    let shown = true;
    for (let node: HTMLElement | null = element; node && node !== container.parentElement; node = node.parentElement) {
      if (node.hidden) {
        shown = false;
        break;
      }
    }
    if (shown) out.push(element);
  }
  return out;
}

/**
 * Handle one keydown inside a modal surface: Tab from the last element goes to the first, Shift+Tab
 * from the first goes to the last, and with nothing to reach the focus stays put. True when the
 * event was consumed.
 */
export function trapTab(container: HTMLElement, ev: KeyboardEvent): boolean {
  if (ev.key !== 'Tab' || ev.altKey || ev.ctrlKey || ev.metaKey) return false;
  const items = tabbables(container);
  const active = container.ownerDocument ? (container.ownerDocument.activeElement as HTMLElement | null) : null;
  if (!items.length) {
    ev.preventDefault();
    return true;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const inside = !!active && container.contains(active);
  let next: HTMLElement | null = null;
  if (ev.shiftKey && (!inside || active === first)) next = last;
  else if (!ev.shiftKey && (!inside || active === last)) next = first;
  if (!next) return false;
  ev.preventDefault();
  try {
    next.focus();
  } catch (_e) {
    /* a host may have detached the surface */
  }
  return true;
}

/**
 * Where the focus goes back to when a surface closes: the element that had it when the surface
 * opened, if it is still in the document and can take it; otherwise `fallback`.
 */
export function restoreFocus(previous: HTMLElement | null, fallback: HTMLElement | null): void {
  const usable = (element: HTMLElement | null): element is HTMLElement =>
    !!element && element.isConnected && !(element as HTMLButtonElement).disabled && typeof element.focus === 'function';
  const attempt = (element: HTMLElement | null): boolean => {
    if (!usable(element) || element === element.ownerDocument.body) return false;
    try {
      element.focus();
    } catch (_e) {
      return false;
    }
    return element.ownerDocument.activeElement === element;
  };
  // A hidden element silently refuses the focus; the fallback takes it then.
  if (!attempt(previous)) attempt(fallback);
}
