/**
 * The hover card. Positioned in canvas space from the world coordinates of the
 * thing being described, so it tracks pan and zoom without its own listeners.
 * Nothing lives only in here — everything it shows is also in the inspector.
 */

import { add, clear, el, locSpan } from '../dom.js';
import { severityGlyph } from '../markers.js';
import { EDGE_MARKER_R, edgeKindText } from './edges.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { LayoutBox } from '../layout/layout.js';
import type { Point, RoutedEdge } from '../layout/routing.js';
import type { Issue, Viewport } from '../types.js';

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
    if (node.ghost) add(this.root, el('div', 'mlv-tooltip__row', node.basis === 'unresolved' ? 'Basis · unresolved' : 'This step is missing from the code.'));
    if (node.loc.file) add(this.root, locSpan('mlv-tooltip__loc', node.loc, 'div'));
    // A group's badge counts what it contains (`planScene`), so its card lists
    // the same findings: a collapsed group listed only its own, often none.
    const aggregate = box.isGroup || box.collapsed;
    this.issueRows(aggregate ? index.subtreeIssues(id, keep) : index.issuesOf(id, keep));
    this.placeAt(box.x + box.w / 2, box.y, box.y + box.h);
  }

  /**
   * A connection's hover card lists its findings exactly as a step's does. It
   * listed none, so hovering the severity marker on a cable showed everything
   * but the finding the marker stood for. A merged route lists the union of its
   * members' findings, each once, in document order. `marker` is where the
   * cable's severity marker is drawn, when it has one: the card sits clear of
   * that disc rather than over it.
   */
  showEdge(index: GraphIndex, route: RoutedEdge, keep: IssuePredicate, marker?: Point): void {
    const edge = index.edgeById.get(route.id);
    clear(this.root);
    add(this.root, el('div', 'mlv-tooltip__title', route.label || edgeKindText(route.kind)));
    // Issue 9: the authored kind word, never `unknown`.
    const authored = edge && edge.authoredKind ? ' · authored as ' + edge.authoredKind : '';
    add(this.root, el('div', 'mlv-tooltip__row', edgeKindText(route.kind) + (route.subkind ? ' · ' + route.subkind : '') + authored));
    if (edge && edge.basis) add(this.root, el('div', 'mlv-tooltip__row', 'Basis · ' + edge.basis));
    if (edge && edge.loc.file) add(this.root, locSpan('mlv-tooltip__loc', edge.loc, 'div'));
    if (route.count > 1) add(this.root, el('div', 'mlv-tooltip__row', route.count + ' merged connections'));
    this.issueRows(index.issuesOfEdges(route.ids, keep));
    if (marker) this.placeAt(marker.x, marker.y - EDGE_MARKER_R, marker.y + EDGE_MARKER_R);
    else this.placeAt(route.mid.x, route.mid.y, route.mid.y);
  }

  /** One row per finding: its severity glyph, code and title. */
  private issueRows(issues: Issue[]): void {
    for (const issue of issues) {
      const row = add(this.root, el('div', 'mlv-tooltip__row'));
      row.appendChild(severityGlyph(issue.severity, 12, ''));
      add(row, el('span', '', ' ' + issue.code + ' ' + issue.title));
    }
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
