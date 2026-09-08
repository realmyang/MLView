/**
 * The hover card. Positioned in canvas space from the world coordinates of the
 * thing being described, so it tracks pan and zoom without its own listeners.
 * Nothing lives only in here — everything it shows is also in the inspector.
 */

import { add, clear, el } from '../dom.js';
import { severityGlyph } from '../markers.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { LayoutBox } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { Viewport } from '../types.js';

export interface Size {
  w: number;
  h: number;
}

export interface Placement {
  left: number;
  top: number;
  /** True when the card was flipped under its anchor to stay inside the canvas. */
  below: boolean;
}

/** Distance between the anchor and the card. */
const GAP = 12;
/** How close the card may come to the canvas edge. */
const MARGIN = 8;

/**
 * Flip / shift positioning (UX_DESIGN §11 "HoverCard (flip/shift positioning)").
 *
 * Pure, so the arithmetic is testable without a layout engine: the previous
 * implementation placed the card unconditionally above the anchor and any node in
 * the top band of the viewport had its card sliced off by the canvas's own
 * overflow — at the default fit, the very first row of cards (MLV-R2-W04).
 *
 * A zero-sized card means "not measurable" (jsdom, or a host that has not laid
 * the card out yet); every adjustment is then skipped rather than guessed.
 */
export function tooltipPlacement(cx: number, topY: number, bottomY: number, card: Size, view: Size): Placement {
  const measurable = card.w > 0 && card.h > 0;
  let below = false;
  if (measurable) {
    const fitsAbove = topY - GAP - card.h >= MARGIN;
    const fitsBelow = view.h <= 0 || bottomY + GAP + card.h <= view.h - MARGIN;
    below = !fitsAbove && fitsBelow;
  }
  let top = below ? bottomY + GAP : topY - GAP;
  if (measurable) {
    // Neither side fits: keep the card on screen rather than half off it.
    if (below) top = Math.min(top, Math.max(MARGIN, view.h - MARGIN - card.h));
    else top = Math.max(top, MARGIN + card.h);
  }
  let left = cx;
  if (measurable && view.w > 0) {
    const half = card.w / 2;
    const min = half + MARGIN;
    const max = view.w - half - MARGIN;
    left = max >= min ? Math.min(Math.max(cx, min), max) : view.w / 2;
  }
  return { left: Math.round(left), top: Math.round(top), below };
}

export class Tooltip {
  readonly root: HTMLElement;
  private viewport: () => Viewport;
  private bounds: () => Size;

  constructor(viewport: () => Viewport, bounds?: () => Size) {
    this.root = el('div', 'mlv-tooltip');
    this.root.setAttribute('role', 'tooltip');
    this.root.hidden = true;
    this.viewport = viewport;
    this.bounds = bounds || (() => ({ w: 0, h: 0 }));
  }

  showNode(index: GraphIndex, id: string, box: LayoutBox, keep: IssuePredicate): void {
    const node = index.nodeById.get(id);
    if (!node) return;
    clear(this.root);
    add(this.root, el('div', 'mlv-tooltip__title', node.label || node.qualname));
    if (node.sublabel) add(this.root, el('div', 'mlv-tooltip__row', node.sublabel));
    if (node.fqn) add(this.root, el('div', 'mlv-tooltip__row', node.fqn));
    if (node.ghost) add(this.root, el('div', 'mlv-tooltip__row', 'This step is missing from the code.'));
    add(this.root, el('div', 'mlv-tooltip__loc', node.loc.file + ':' + node.loc.line));
    for (const issue of index.issuesOf(id, keep)) {
      const row = add(this.root, el('div', 'mlv-tooltip__row'));
      row.appendChild(severityGlyph(issue.severity, 12, ''));
      add(row, el('span', '', ' ' + issue.code + ' ' + issue.title));
    }
    this.placeAt(box.x + box.w / 2, box.y, box.y + box.h);
  }

  showEdge(index: GraphIndex, route: RoutedEdge): void {
    const edge = index.edgeById.get(route.id);
    clear(this.root);
    add(this.root, el('div', 'mlv-tooltip__title', route.label || route.kind));
    add(this.root, el('div', 'mlv-tooltip__row', route.kind + (route.subkind ? ' · ' + route.subkind : '')));
    if (edge) add(this.root, el('div', 'mlv-tooltip__loc', edge.loc.file + ':' + edge.loc.line));
    if (route.count > 1) add(this.root, el('div', 'mlv-tooltip__row', route.count + ' merged connections'));
    this.placeAt(route.mid.x, route.mid.y, route.mid.y);
  }

  /**
   * `worldTopY` is the anchor's top edge and `worldBottomY` its bottom, so the
   * card can flip under the thing it describes when there is no room above it.
   */
  placeAt(worldX: number, worldTopY: number, worldBottomY: number): void {
    const vp = this.viewport();
    // Measure only once the card is displayed and filled: a hidden element has
    // no box.
    this.root.hidden = false;
    this.root.style.transform = 'translate(-50%, -100%)';
    const box = this.root.getBoundingClientRect();
    const place = tooltipPlacement(
      worldX * vp.zoom + vp.x,
      worldTopY * vp.zoom + vp.y,
      worldBottomY * vp.zoom + vp.y,
      { w: box.width, h: box.height },
      this.bounds(),
    );
    this.root.style.left = place.left + 'px';
    this.root.style.top = place.top + 'px';
    this.root.style.transform = place.below ? 'translate(-50%, 0)' : 'translate(-50%, -100%)';
  }

  hide(): void {
    this.root.hidden = true;
  }
}
