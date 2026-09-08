/**
 * Lineage highlight. Walks the ROUTED edges (so a collapsed group behaves like
 * the nodes it hides) upstream and downstream from one node, then toggles
 * classes — never a re-render, which is what keeps hover under the 100 ms
 * response budget.
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

/**
 * Light the lineage of `id` and mark the canvas with `cls` so the CSS dims the
 * rest. Passing `null` clears both.
 */
export function applyTrace(targets: TraceTargets, routes: RoutedEdge[], id: string | null, cls: string): void {
  for (const element of targets.nodes.values()) element.classList.remove('is-lit');
  for (const element of targets.edges.values()) element.classList.remove('is-lit');
  if (!id) {
    targets.canvas.classList.remove(cls);
    return;
  }
  const lineage = lineageOf(routes, id);
  for (const nodeId of lineage.nodes) {
    const element = targets.nodes.get(nodeId);
    if (element) element.classList.add('is-lit');
  }
  for (const edgeId of lineage.edges) {
    const element = targets.edges.get(edgeId);
    if (element) element.classList.add('is-lit');
  }
  targets.canvas.classList.add(cls);
}
