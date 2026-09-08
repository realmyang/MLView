/**
 * Scene building: turn one LayoutFrame plus its routed edges into DOM.
 *
 * Bands and expanded group boxes go into the backdrop layer, the SVG edge layer
 * sits above them, and the node cards sit on top — so an edge is drawn under
 * the cards it connects and over the band it crosses.
 */

import { clear } from '../dom.js';
import { highestSeverity } from '../markers.js';
import { buildEdge } from './edges.js';
import { buildGroupBox, buildLane, buildNodeCard, NodeVisual } from './nodes.js';
import type { GraphIndex, IssuePredicate } from '../layout/model.js';
import type { LabelPlacement } from '../layout/labels.js';
import type { LayoutFrame } from '../layout/layout.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { Issue, MLNode } from '../types.js';

export interface SceneLayers {
  world: HTMLElement;
  lanes: HTMLElement;
  edgesSvg: SVGElement;
  edgeGroup: SVGElement;
  connectors: SVGElement;
  nodes: HTMLElement;
}

export interface SceneOptions {
  index: GraphIndex;
  frame: LayoutFrame;
  routes: RoutedEdge[];
  /** VIEW-03: the label placements for those routes, keyed by route id. */
  labels?: Map<string, LabelPlacement> | null;
  /** This view's serial — it qualifies every edge path id (CONTRACTS 11.13.1). */
  mountSerial: number;
  keep: IssuePredicate;
  staleFiles: string[];
  isFilteredOut(node: MLNode): boolean;
  wireNode(element: HTMLElement, id: string, isGroup: boolean): void;
  wireEdge(element: SVGElement, route: RoutedEdge): void;
}

export interface SceneResult {
  nodeEls: Map<string, HTMLElement>;
  edgeEls: Map<string, SVGElement>;
}

export function renderScene(layers: SceneLayers, opts: SceneOptions): SceneResult {
  const { index, frame, routes, keep } = opts;
  clear(layers.lanes);
  clear(layers.nodes);
  clear(layers.edgeGroup);
  clear(layers.connectors);

  layers.world.style.width = frame.width + 'px';
  layers.world.style.height = frame.height + 'px';
  layers.edgesSvg.setAttribute('width', String(frame.width));
  layers.edgesSvg.setAttribute('height', String(frame.height));
  layers.edgesSvg.setAttribute('viewBox', '0 0 ' + frame.width + ' ' + frame.height);

  for (const lane of frame.lanes) {
    layers.lanes.appendChild(buildLane(lane, index.laneCounts(lane.id, keep), false));
  }

  const nodeEls = new Map<string, HTMLElement>();
  // Shallowest first: a group box must be appended before the cards inside it.
  const boxes = Array.from(frame.boxes.values()).sort((a, b) => a.depth - b.depth || compare(a.id, b.id));
  for (const box of boxes) {
    const node = index.nodeById.get(box.id);
    if (!node) continue;
    const expandedGroup = box.isGroup && !box.collapsed;
    const counts =
      expandedGroup || box.collapsed ? index.subtreeCounts(box.id, keep) : index.ownCounts(box.id, keep);
    const visual: NodeVisual = {
      node,
      box,
      counts,
      descendants: index.descendantCount(box.id),
      stale: opts.staleFiles.indexOf(node.loc.file) >= 0,
      filteredOut: opts.isFilteredOut(node),
    };
    const element = expandedGroup ? buildGroupBox(visual) : buildNodeCard(visual, box.collapsed);
    opts.wireNode(element, node.id, expandedGroup);
    nodeEls.set(node.id, element);
    if (expandedGroup) layers.lanes.appendChild(element);
    else layers.nodes.appendChild(element);
  }

  const edgeEls = new Map<string, SVGElement>();
  for (const route of routes) {
    const issues: Issue[] = [];
    for (const id of route.ids) for (const issue of index.issuesOfEdge(id, keep)) issues.push(issue);
    const top = highestSeverity(index.countsFor(issues));
    // Back-edges always carry their label (`next batch` / `next epoch` with a
    // return glyph); data-edge labels come in with the `full` LOD class, driven
    // from CSS so zooming never re-renders a component (MLV-R1-012).
    const src = index.nodeById.get(route.source);
    const dst = index.nodeById.get(route.target);
    const element = buildEdge({
      route,
      severity: top,
      suppressed: false,
      labelVisible: route.back,
      stage: src ? src.stage : undefined,
      sourceLabel: src ? src.label || src.qualname : undefined,
      targetLabel: dst ? dst.label || dst.qualname : undefined,
      mountSerial: opts.mountSerial,
      placement: opts.labels ? opts.labels.get(route.id) : undefined,
    });
    if ((src && opts.isFilteredOut(src)) || (dst && opts.isFilteredOut(dst))) element.classList.add('is-filtered');
    opts.wireEdge(element, route);
    layers.edgeGroup.appendChild(element);
    edgeEls.set(route.id, element);
  }

  return { nodeEls, edgeEls };
}

/** Minimap dots: one per drawn box, coloured by stage and ringed by severity. */
export function minimapDots(index: GraphIndex, frame: LayoutFrame, keep: IssuePredicate) {
  const dots = [];
  for (const box of frame.boxes.values()) {
    const node = index.nodeById.get(box.id);
    if (!node) continue;
    dots.push({
      x: box.x,
      y: box.y,
      w: box.w,
      h: box.h,
      stage: node.stage,
      severity: highestSeverity(index.subtreeCounts(box.id, keep)),
    });
  }
  return dots;
}

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}
