/**
 * VIEW-04 — the cross-lane bundle layer.
 *
 * One `<g class="mlv-bundle">` per lane pair: the trunk, one splayed spur per
 * member at each end, and a badge saying how many connections it stands for.
 * It is drawn UNDER the edge layer, and while a bundle is collapsed its members
 * carry `.is-bundled`, which makes their stroke and label transparent — the
 * cables are still in the DOM, still hit-testable, still carrying their own
 * `points`, their own `d` and their own motion-path id. Nothing about a bundle
 * is allowed to be load-bearing: hide this layer with CSS and the diagram is
 * exactly the diagram that shipped before the item.
 *
 * Expansion is a class, not a stylesheet trick, because it has four triggers —
 * pointer, keyboard focus, selection and a lineage highlight — and `:hover`
 * only knows about one of them. `BundleBinding.sync()` reads the state off the
 * member elements themselves, so it can never disagree with what the rest of the
 * viewer already decided.
 */

import { svg } from '../dom.js';
import type { EdgeBundle } from '../layout/bundles.js';
import type { Severity } from '../types.js';

/** Any of these on a member means its bundle must be showing real strokes. */
export const BUNDLE_ACTIVE_CLASSES = ['is-hover', 'is-selected', 'is-lit', 'is-flowing', 'is-traced'];

export interface BundleVisual {
  bundle: EdgeBundle;
  /** The worst severity carried by any member, so the trunk says so too. */
  severity: Severity | null;
  /** The source lane's stage id — the trunk takes its colour like an edge does. */
  stage?: string;
  /** Human lane names, for the accessible title. */
  sourceLabel?: string;
  targetLabel?: string;
}

/** `6 connections from Data to Train` — what the trunk's `<title>` says. */
export function bundleTitle(v: BundleVisual): string {
  const b = v.bundle;
  const from = v.sourceLabel || b.sourceLane;
  const to = v.targetLabel || b.targetLane;
  const what = b.edgeCount === 1 ? '1 connection' : b.edgeCount + ' connections';
  return what + ' from ' + from + ' to ' + to + '. Hover to separate them.';
}

export function buildBundle(v: BundleVisual): SVGElement {
  const b = v.bundle;
  const kind = b.kinds.length === 1 ? b.kinds[0] : 'mixed';
  const g = svg('g', {
    class: 'mlv-bundle mlv-bundle--' + kind,
    'data-bundle-id': b.id,
    'data-count': String(b.edgeCount),
    'data-members': String(b.count),
    'data-axis': b.axis,
  });
  g.setAttribute('data-lane-pair', b.sourceLane + '>' + b.targetLane);
  if (v.stage) g.setAttribute('data-stage', v.stage);
  if (v.severity) {
    g.setAttribute('data-sev', v.severity);
    g.classList.add('has-issue');
  }

  const title = svg('title');
  title.textContent = bundleTitle(v);
  g.appendChild(title);

  for (const spur of b.spurs) g.appendChild(svg('path', { class: 'mlv-bundle__spur', d: spur.d }));
  g.appendChild(svg('path', { class: 'mlv-bundle__trunk', d: b.d }));

  const text = String(b.edgeCount);
  const w = 15 + 6 * text.length;
  const badge = svg('g', { class: 'mlv-bundle__badge', transform: 'translate(' + b.badge.x + ',' + b.badge.y + ')' });
  badge.appendChild(svg('rect', { class: 'mlv-bundle__badge-box', x: -w / 2, y: -8, width: w, height: 16, rx: 8 }));
  const label = svg('text', { class: 'mlv-bundle__badge-text', x: 0, y: 0 });
  label.textContent = text;
  badge.appendChild(label);
  g.appendChild(badge);
  return g;
}

/**
 * Keeps the drawn bundles and their members in step.
 *
 * `adopt` is called once per scene build with what the renderer just made;
 * `sync` is called whenever anything that lights a cable changes. Both are
 * O(members) over at most a few hundred elements and touch nothing but two
 * class names, so they stay inside the 100 ms hover budget A6 sets.
 */
export class BundleBinding {
  private els = new Map<string, SVGElement>();
  private memberOf = new Map<string, string>();

  adopt(els: Map<string, SVGElement>, bundles: EdgeBundle[]): void {
    this.els = els;
    this.memberOf = new Map();
    for (const bundle of bundles) for (const id of bundle.memberIds) this.memberOf.set(id, bundle.id);
  }

  /**
   * Collapse every bundle whose members are all idle and expand the rest.
   *
   * A bundle of one is never built, so `expand on a single member` is the
   * degenerate case of this rule rather than a branch of its own.
   */
  sync(edgeEls: Map<string, SVGElement>): void {
    if (this.els.size === 0) return;
    const open = new Set<string>();
    for (const [routeId, bundleId] of this.memberOf) {
      const element = edgeEls.get(routeId);
      if (!element) continue;
      if (isActive(element)) open.add(bundleId);
    }
    for (const [bundleId, element] of this.els) element.classList.toggle('is-expanded', open.has(bundleId));
    for (const [routeId, bundleId] of this.memberOf) {
      const element = edgeEls.get(routeId);
      if (element) element.classList.toggle('is-bundled', !open.has(bundleId));
    }
  }
}

function isActive(element: SVGElement): boolean {
  const list = element.classList;
  for (const name of BUNDLE_ACTIVE_CLASSES) if (list.contains(name)) return true;
  return false;
}
