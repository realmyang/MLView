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

import { SEVERITY_ORDER, highestSeverity } from '../markers.js';
import { routeWeight } from './weight.js';
import { buildBundles } from '../layout/bundles.js';
import { allElsewhere } from '../freshness.js';
import type { BundleVisual } from './bundles.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { LabelPlacement } from '../layout/labels.js';
import type { LayoutFrame, LayoutLane } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { EdgeVisual } from './edges.js';
import type { NodeVisual } from './nodes.js';
import type { IssueCounts, Loc, MLNode, Severity, StaleReason, WorkflowBasis } from '../types.js';

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
  /** Viewer M1: workspace-relative paths the host reported stale, with the reason. Empty draws no mark. */
  staleFiles: ReadonlyMap<string, StaleReason>;
  isFilteredOut(node: MLNode): boolean;
}

export interface ScenePlan {
  index: GraphIndex;
  frame: LayoutFrame;
  lanes: LaneVisual[];
  /** Shallowest first, so a group frame is always planned before its children. */
  nodes: PlannedNode[];
  edges: EdgeVisual[];
  /**
   * VIEW-04: the cross-lane trunks, one per lane pair with two or more members.
   * The DOM renderer draws them under the cables; `export/svg.ts` deliberately
   * does NOT — a static picture cannot be hovered, so it keeps every stroke.
   */
  bundles: BundleVisual[];
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
        ...staleOf(node.evidenceLocs, node.loc, opts.staleFiles),
        filteredOut: opts.isFilteredOut(node),
      },
    });
  }

  const edges: EdgeVisual[] = [];
  for (const route of routes) {
    // Each finding once, however many of the merged members name it.
    const issues = index.issuesOfEdges(route.ids, keep);
    const src = index.nodeById.get(route.source);
    const dst = index.nodeById.get(route.target);
    edges.push({
      route,
      severity: highestSeverity(index.countsFor(issues)),
      // Back-edges always carry their label; data-edge labels come in with the
      // `full` LOD class, driven from CSS so zooming never re-renders (MLV-R1-012).
      labelVisible: route.back,
      stage: src ? src.stage : undefined,
      sourceLabel: src ? src.label || src.qualname : undefined,
      targetLabel: dst ? dst.label || dst.qualname : undefined,
      mountSerial: opts.mountSerial,
      placement: opts.labels ? opts.labels.get(route.id) : undefined,
      filtered: !!((src && opts.isFilteredOut(src)) || (dst && opts.isFilteredOut(dst))),
      // How many connections the route merges. Decided here, in the plan, so the
      // DOM and the SVG export cannot draw two different numbers on the same cable.
      weight: routeWeight(route.ids),
      // Viewer M1: a cable is marked when any connection it stands for cites a stale file.
      ...staleOfRoute(route.ids, index, opts.staleFiles),
      // Viewer M2: the least certain basis among the connections the cable stands for.
      basis: routeBasis(route.ids, index),
    });
  }

  // VIEW-04. The bundles are decided from the ROUTES, so both renderers see the
  // same trunks even though only one of them draws them, and the severity a
  // trunk shows is the worst of the cables it stands for — a bundle that hid a
  // high finding behind a neutral stroke would be the one thing this layer must
  // never do.
  const severityOf = new Map<string, Severity | null>();
  for (const visual of edges) severityOf.set(visual.route.id, visual.severity);
  const laneLabel = new Map<string, string>();
  for (const lane of frame.lanes) laneLabel.set(lane.id, lane.label);
  const bundles: BundleVisual[] = [];
  for (const bundle of buildBundles(routes)) {
    let severity: Severity | null = null;
    for (const id of bundle.memberIds) {
      const member = severityOf.get(id) || null;
      if (member && (!severity || SEVERITY_ORDER.indexOf(member) < SEVERITY_ORDER.indexOf(severity))) severity = member;
    }
    bundles.push({
      bundle,
      severity,
      stage: bundle.sourceLane,
      sourceLabel: laneLabel.get(bundle.sourceLane),
      targetLabel: laneLabel.get(bundle.targetLane),
    });
  }

  return { index, frame, lanes, nodes, edges, bundles };
}

/** Least certain first: a merged cable is only as certain as its weakest member. */
const BASIS_RANK: Record<string, number> = { unresolved: 0, inferred: 1, observed: 2 };

/**
 * Viewer M2: the basis a cable is drawn and named with. A merged route stands for several
 * connections, so it takes the least certain of them; a route with no authored basis has none.
 */
export function routeBasis(ids: string[], index: GraphIndex): WorkflowBasis | undefined {
  let out: WorkflowBasis | undefined;
  for (const id of ids) {
    const basis = index.edgeById.get(id)?.basis;
    if (!basis) continue;
    if (!out || (BASIS_RANK[basis] ?? 2) < (BASIS_RANK[out] ?? 2)) out = basis;
  }
  return out;
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

type StaleOf = { stale: boolean; staleQuotes?: { stale: number; total: number }; staleElsewhere?: boolean };

/**
 * Viewer M1. Whether an item's evidence cites a stale file, and how many of its quotes do. An
 * authored item has `evidenceLocs` (possibly empty); anything else falls back to its one `loc`.
 * `staleElsewhere`: every stale quote cites a file the host found unchanged in another folder
 * (the root hint), which is worded apart (COPY-1).
 */
function staleOf(locs: Loc[] | undefined, loc: Loc, staleFiles: ReadonlyMap<string, StaleReason>): StaleOf {
  if (!staleFiles.size) return { stale: false };
  const list = locs || (loc.file ? [loc] : []);
  const reasons: StaleReason[] = [];
  for (const item of list) {
    const reason = item.file ? staleFiles.get(item.file) : undefined;
    if (reason) reasons.push(reason);
  }
  if (!reasons.length) return { stale: false };
  const out: StaleOf = { stale: true, staleQuotes: { stale: reasons.length, total: list.length } };
  if (allElsewhere(reasons)) out.staleElsewhere = true;
  return out;
}

function staleOfRoute(ids: string[], index: GraphIndex, staleFiles: ReadonlyMap<string, StaleReason>): { stale?: boolean; staleElsewhere?: boolean } {
  if (!staleFiles.size) return {};
  let stale = false;
  let elsewhere = true;
  for (const id of ids) {
    const edge = index.edgeById.get(id);
    const of = edge ? staleOf(edge.evidenceLocs, edge.loc, staleFiles) : null;
    if (!of || !of.stale) continue;
    stale = true;
    if (!of.staleElsewhere) elsewhere = false;
  }
  if (!stale) return {};
  return elsewhere ? { stale: true, staleElsewhere: true } : { stale: true };
}
