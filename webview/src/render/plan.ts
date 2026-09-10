/**
 * The scene plan: ONE description of what is drawn, consumed by two renderers.
 *
 * VIEW-07 adds a second renderer — `export/svg.ts` emits real `<rect>` / `<text>`
 * for the same picture — and the item's mandatory mitigation is that the two
 * must not be able to disagree. So neither of them decides *what* to draw any
 * more: `planScene()` does, once, from (index, frame, routes, labels, filters),
 * and both renderers walk the result.
 *
 * Everything here is pure. No DOM, no measurement, no ordering that is not the
 * document's own — the same determinism `layoutGraph` and `routeEdges` promise,
 * because the export gate asserts one `<g>` per planned node and one `<path>`
 * per planned edge and a plan that reordered itself would make that flaky.
 */

import { highestSeverity } from '../markers.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { LabelPlacement } from '../layout/labels.js';
import type { LayoutFrame, LayoutLane } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { EdgeVisual } from './edges.js';
import type { NodeVisual } from './nodes.js';
import type { Issue, IssueCounts, MLNode } from '../types.js';

/** A swimlane band plus the aggregated counts its header shows. */
export interface LaneVisual {
  lane: LayoutLane;
  counts: IssueCounts;
}

/** A drawn box, and whether it is the dashed frame of an EXPANDED group. */
export interface PlannedNode {
  visual: NodeVisual;
  expandedGroup: boolean;
}

export interface ScenePlanOptions {
  index: GraphIndex;
  frame: LayoutFrame;
  routes: RoutedEdge[];
  /** VIEW-03 label placements, keyed by route id. */
  labels?: Map<string, LabelPlacement> | null;
  /** This view's serial — it qualifies every edge path id (CONTRACTS 11.13.1). */
  mountSerial: number;
  keep: IssuePredicate;
  staleFiles: string[];
  isFilteredOut(node: MLNode): boolean;
}

export interface ScenePlan {
  index: GraphIndex;
  frame: LayoutFrame;
  lanes: LaneVisual[];
  /** Shallowest first, so a group frame is always planned before its children. */
  nodes: PlannedNode[];
  edges: EdgeVisual[];
}

/**
 * Decide the whole scene. `render/scene.ts` turns this into DOM and
 * `export/svg.ts` turns the same object into SVG.
 */
export function planScene(opts: ScenePlanOptions): ScenePlan {
  const { index, frame, routes, keep } = opts;

  const lanes: LaneVisual[] = [];
  for (const lane of frame.lanes) {
    lanes.push({ lane, counts: index.laneCounts(lane.id, keep) });
  }

  const nodes: PlannedNode[] = [];
  // Shallowest first: a group box must be drawn before the cards inside it.
  const boxes = Array.from(frame.boxes.values()).sort((a, b) => a.depth - b.depth || compare(a.id, b.id));
  for (const box of boxes) {
    const node = index.nodeById.get(box.id);
    if (!node) continue;
    const expandedGroup = box.isGroup && !box.collapsed;
    const counts =
      expandedGroup || box.collapsed ? index.subtreeCounts(box.id, keep) : index.ownCounts(box.id, keep);
    nodes.push({
      expandedGroup,
      visual: {
        node,
        box,
        counts,
        descendants: index.descendantCount(box.id),
        stale: opts.staleFiles.indexOf(node.loc.file) >= 0,
        filteredOut: opts.isFilteredOut(node),
      },
    });
  }

  const edges: EdgeVisual[] = [];
  for (const route of routes) {
    const issues: Issue[] = [];
    for (const id of route.ids) for (const issue of index.issuesOfEdge(id, keep)) issues.push(issue);
    const src = index.nodeById.get(route.source);
    const dst = index.nodeById.get(route.target);
    edges.push({
      route,
      severity: highestSeverity(index.countsFor(issues)),
      suppressed: false,
      // Back-edges always carry their label; data-edge labels come in with the
      // `full` LOD class, driven from CSS so zooming never re-renders (MLV-R1-012).
      labelVisible: route.back,
      stage: src ? src.stage : undefined,
      sourceLabel: src ? src.label || src.qualname : undefined,
      targetLabel: dst ? dst.label || dst.qualname : undefined,
      mountSerial: opts.mountSerial,
      placement: opts.labels ? opts.labels.get(route.id) : undefined,
      filtered: !!((src && opts.isFilteredOut(src)) || (dst && opts.isFilteredOut(dst))),
    });
  }

  return { index, frame, lanes, nodes, edges };
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
