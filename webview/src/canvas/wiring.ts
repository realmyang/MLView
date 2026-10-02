/**
 * The gestures a freshly rendered card or cable answers.
 *
 * `render/scene.ts` builds the DOM; this file is what makes it live. It is
 * separate from `canvasview.ts` because it is the only part of the surface that
 * is pure event plumbing — no layout, no viewport, no state of its own — and
 * because the two double-click / focus subtleties below are worth reading
 * without 700 lines of canvas around them.
 */

import { on } from '../dom.js';
import { DOUBLE_CLICK_MS } from './host.js';
import type { RoutedEdge } from '../layout/routing.js';

/** What wiring a node card needs from the canvas. */
export interface NodeWiring {
  isGroup(id: string): boolean;
  toggleCollapse(id: string): void;
  hoverIntent(id: string | null): void;
  /** A click: select only (viewer M1). `ev` lets the second click of a double-click open it. */
  activateNode(id: string, ev?: MouseEvent): void;
  /** Enter or a double-click: select and open the cited source; `focusEditor` for Alt+Enter. */
  openNode(id: string, focusEditor: boolean): void;
  /** Timers a teardown has to cancel; the canvas owns the list. */
  addDisposer(dispose: () => void): void;
}

/** What wiring a connection needs from the canvas. */
export interface EdgeWiring {
  /** A click: select only (viewer M1). `ev` lets the second click of a double-click open it. */
  activateEdge(id: string, ev?: MouseEvent): void;
  /** Enter or a double-click: select and open the cited source; `focusEditor` for Alt+Enter. */
  openEdge(id: string, focusEditor: boolean): void;
  enterEdge(route: RoutedEdge): void;
  leaveEdge(route: RoutedEdge): void;
  syncBundles(): void;
  pulse(route: RoutedEdge): void;
  stopFlow(): void;
}

export function wireNodeEvents(element: HTMLElement, id: string, isGroup: boolean, port: NodeWiring): void {
  const target: HTMLElement = isGroup ? (element.querySelector('.mlv-group__header') as HTMLElement) : element;
  if (!target) return;

  // The chevron owns the collapse gesture outright (UX_DESIGN §2.4).
  const chevron = element.querySelector('.mlv-group__chevron-btn') as HTMLElement | null;
  if (chevron) {
    on(chevron, 'click', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (port.isGroup(id)) port.toggleCollapse(id);
    });
    on(chevron, 'dblclick', (ev: MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
    });
  }

  // A double-click emits click, click, dblclick. Anything that also answers a
  // double-click must therefore hold its single-click back long enough to see
  // the second one, or collapsing a group selects it first (MLV-R1-010). A card
  // that is not collapsible answers the double-click by opening its source
  // (viewer M1): its first click selects it and arms the App's double-click
  // opener (ui/doubleclick.ts), which takes the second click wherever it lands.
  // The `dblclick` handler below is the fallback for a bare `dblclick`.
  const collapsible = isGroup || port.isGroup(id);
  let pending: ReturnType<typeof setTimeout> | null = null;
  const cancelPending = () => {
    if (pending === null) return;
    clearTimeout(pending);
    pending = null;
  };
  port.addDisposer(cancelPending);

  on(target, 'click', (ev: MouseEvent) => {
    ev.stopPropagation();
    if (!collapsible) {
      port.activateNode(id, ev);
      return;
    }
    cancelPending();
    pending = setTimeout(() => {
      pending = null;
      port.activateNode(id);
    }, DOUBLE_CLICK_MS);
  });
  on(target, 'dblclick', (ev: MouseEvent) => {
    ev.preventDefault();
    ev.stopPropagation();
    cancelPending();
    if (port.isGroup(id)) port.toggleCollapse(id);
    else if (!collapsible) port.openNode(id, false);
  });
  on(target, 'pointerenter', () => port.hoverIntent(id));
  on(target, 'pointerleave', () => port.hoverIntent(null));
  on(target, 'keydown', (ev: KeyboardEvent) => {
    if (ev.key === 'Enter' && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) {
      ev.preventDefault();
      // Handled here, for THIS card: the canvas's own Enter must not open it a second time.
      ev.stopPropagation();
      port.openNode(id, ev.altKey);
    } else if (ev.key === ' ' && port.isGroup(id)) {
      ev.preventDefault();
      port.toggleCollapse(id);
    }
  });
}

export function wireEdgeEvents(g: SVGElement, route: RoutedEdge, port: EdgeWiring): void {
  const hit = g.querySelector('.mlv-edge__hit') as SVGElement | null;
  if (!hit) return;
  const element = hit as unknown as HTMLElement;
  on(element, 'click', (ev: MouseEvent) => {
    ev.stopPropagation();
    port.activateEdge(route.id, ev);
  });
  on(element, 'dblclick', (ev: MouseEvent) => {
    ev.preventDefault();
    ev.stopPropagation();
    port.openEdge(route.id, false);
  });
  on(element, 'pointerenter', () => port.enterEdge(route));
  on(element, 'pointerleave', () => port.leaveEdge(route));
  on(element, 'keydown', (ev: KeyboardEvent) => {
    if (ev.key !== 'Enter' || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
    ev.preventDefault();
    ev.stopPropagation();
    port.openEdge(route.id, ev.altKey);
  });
  // A connection was unreachable from the keyboard before this (FEATURES 2.2):
  // `e` / `Shift+E` focus the hit path, and focus alone runs the charge.
  on(element, 'focus', () => {
    g.classList.add('is-hover');
    port.syncBundles();
    port.pulse(route);
  });
  on(element, 'blur', () => {
    g.classList.remove('is-hover');
    port.syncBundles();
    port.stopFlow();
  });
}
