/**
 * Scene building: turn one LayoutFrame plus its routed edges into DOM.
 *
 * Bands and expanded group boxes go into the backdrop layer, the SVG edge layer
 * sits above them, and the node cards sit on top — so an edge is drawn under
 * the cards it connects and over the band it crosses.
 *
 * WHAT is drawn is decided by `render/plan.ts`, not here: `export/svg.ts` walks
 * the same plan to emit a standalone SVG, and VIEW-07 requires the two
 * renderers to be incapable of disagreeing about the node and edge sets.
 */

import { clear } from '../dom.js';
import { buildBundle } from './bundles.js';
import { buildEdge } from './edges.js';
import { buildGroupBox, buildLane, buildNodeCard } from './nodes.js';
import type { RevisionMark } from './nodes.js';
import { planScene, ScenePlan, ScenePlanOptions } from './plan.js';
import type { RoutedEdge } from '../layout/routing.js';

export interface SceneLayers {
  world: HTMLElement;
  lanes: HTMLElement;
  edgesSvg: SVGElement;
  /** VIEW-04: the trunk layer, under the cables. */
  bundleGroup: SVGElement;
  edgeGroup: SVGElement;
  connectors: SVGElement;
  nodes: HTMLElement;
}

export interface SceneOptions extends ScenePlanOptions {
  wireNode(element: HTMLElement, id: string, isGroup: boolean): void;
  wireEdge(element: SVGElement, route: RoutedEdge): void;
  /**
   * Viewer M4 (step 16): a step's "new" or "changed" tag. DOM only, deliberately outside the plan:
   * it is an overlay on the card that changes no box, and the SVG export does not draw it.
   */
  revisionMark?(nodeId: string): RevisionMark | undefined;
}

export interface SceneResult {
  nodeEls: Map<string, HTMLElement>;
  edgeEls: Map<string, SVGElement>;
  /** VIEW-04: bundle id -> its `<g>`, so the binding can expand one. */
  bundleEls: Map<string, SVGElement>;
  /** The plan the DOM was built from — the export renders this same object. */
  plan: ScenePlan;
}

export function renderScene(layers: SceneLayers, opts: SceneOptions): SceneResult {
  const plan = planScene(opts);
  const frame = plan.frame;
  clear(layers.lanes);
  clear(layers.nodes);
  clear(layers.bundleGroup);
  clear(layers.edgeGroup);
  clear(layers.connectors);

  layers.world.style.width = frame.width + 'px';
  layers.world.style.height = frame.height + 'px';
  layers.edgesSvg.setAttribute('width', String(frame.width));
  layers.edgesSvg.setAttribute('height', String(frame.height));
  layers.edgesSvg.setAttribute('viewBox', '0 0 ' + frame.width + ' ' + frame.height);

  for (const lane of plan.lanes) {
    layers.lanes.appendChild(buildLane(lane.lane, lane.counts, false, lane.phase));
  }

  const nodeEls = new Map<string, HTMLElement>();
  for (const planned of plan.nodes) {
    const visual = planned.visual;
    const mark = opts.revisionMark ? opts.revisionMark(visual.node.id) : undefined;
    const element = planned.expandedGroup ? buildGroupBox(visual, mark) : buildNodeCard(visual, visual.box.collapsed, mark);
    opts.wireNode(element, visual.node.id, planned.expandedGroup);
    nodeEls.set(visual.node.id, element);
    if (planned.expandedGroup) layers.lanes.appendChild(element);
    else layers.nodes.appendChild(element);
  }

  // VIEW-04. Trunks first, so a cable that expands out of one is drawn over it.
  const bundleEls = new Map<string, SVGElement>();
  for (const visual of plan.bundles) {
    const element = buildBundle(visual);
    layers.bundleGroup.appendChild(element);
    bundleEls.set(visual.bundle.id, element);
  }

  const edgeEls = new Map<string, SVGElement>();
  for (const visual of plan.edges) {
    const element = buildEdge(visual);
    opts.wireEdge(element, visual.route);
    layers.edgeGroup.appendChild(element);
    edgeEls.set(visual.route.id, element);
  }

  return { nodeEls, edgeEls, bundleEls, plan };
}
