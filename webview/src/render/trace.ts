/**
 * The hover and focus-mode highlight. Walks the ROUTED edges (so a collapsed
 * group behaves like the nodes it hides) from one node, then toggles classes —
 * never a re-render, which is what keeps hover under the 100 ms response budget.
 *
 * Two reaches, one per gesture:
 *  - `direct` (node hover): the node, every route whose source or target is the
 *    node, and the nodes at the other ends of those routes — one hop, so a
 *    reader resting on a card sees what it is wired to and not a lit chain or
 *    loop two hops away;
 *  - `lineage` (focus mode, `f` on the selection): everything reachable
 *    upstream and downstream, the full transitive walk.
 */

import type { RoutedEdge } from '../layout/routing.js';

export interface TraceTargets {
  nodes: Map<string, HTMLElement>;
  edges: Map<string, SVGElement>;
  canvas: HTMLElement;
}

export interface Lineage {
  nodes: Set<string>;
  edges: Set<string>;
}

/** How far a highlight reaches from its node: one hop, or the whole lineage. */
export type TraceReach = 'direct' | 'lineage';

/** Everything reachable from `id` in either direction. */
export function lineageOf(routes: RoutedEdge[], id: string): Lineage {
  const nodes = new Set<string>([id]);
  const edges = new Set<string>();
  const walk = (forward: boolean) => {
    const stack = [id];
    const seen = new Set<string>([id]);
    while (stack.length) {
      const cur = stack.pop()!;
      for (const route of routes) {
        const from = forward ? route.source : route.target;
        const to = forward ? route.target : route.source;
        if (from !== cur) continue;
        edges.add(route.id);
        if (seen.has(to)) continue;
        seen.add(to);
        nodes.add(to);
        stack.push(to);
      }
    }
  };
  walk(true);
  walk(false);
  return { nodes, edges };
}

/** `id`, the routes that start or end at it, and the nodes at their other ends. */
export function neighboursOf(routes: RoutedEdge[], id: string): Lineage {
  const nodes = new Set<string>([id]);
  const edges = new Set<string>();
  for (const route of routes) {
    if (route.source !== id && route.target !== id) continue;
    edges.add(route.id);
    nodes.add(route.source);
    nodes.add(route.target);
  }
  return { nodes, edges };
}

/** The set a highlight of `id` covers at `reach`. */
export function reachOf(routes: RoutedEdge[], id: string, reach: TraceReach): Lineage {
  return reach === 'direct' ? neighboursOf(routes, id) : lineageOf(routes, id);
}

/**
 * Light what `id` reaches and mark the canvas with `cls` so the CSS dims the
 * rest. Passing `null` clears both.
 */
export function applyTrace(targets: TraceTargets, routes: RoutedEdge[], id: string | null, cls: string, reach: TraceReach): void {
  for (const element of targets.nodes.values()) element.classList.remove('is-lit');
  for (const element of targets.edges.values()) element.classList.remove('is-lit');
  if (!id) {
    targets.canvas.classList.remove(cls);
    return;
  }
  const lit = reachOf(routes, id, reach);
  for (const nodeId of lit.nodes) {
    const element = targets.nodes.get(nodeId);
    if (element) element.classList.add('is-lit');
  }
  for (const edgeId of lit.edges) {
    const element = targets.edges.get(edgeId);
    if (element) element.classList.add('is-lit');
  }
  targets.canvas.classList.add(cls);
}
