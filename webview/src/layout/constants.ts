/** Geometry and layout constants. Mirrors the token geometry in styles/tokens.css. */

export const NODE_W = 216;
export const NODE_W_LG = 248;
export const NODE_W_SM = 176;
export const NODE_H = 72;
export const NODE_H_GHOST = 60;

export const GROUP_HEADER_H = 34;
export const GROUP_PAD = 16;
export const GROUP_MIN_W = 200;
export const GROUP_MIN_H = 56;

export const LANE_HEADER_H = 28;
export const LANE_PAD = 28;
export const LANE_GUTTER = 40;
export const LANE_MIN_W = 420;
export const LANE_MIN_H = 96;

export const CANVAS_MARGIN = 32;

export const DAGRE_OPTS = {
  rankdir: 'LR',
  ranksep: 72,
  nodesep: 24,
  edgesep: 12,
  marginx: 16,
  marginy: 16,
  ranker: 'network-simplex',
};

/** Edge weights bias dagre's ranking toward the real pipeline order. */
export const EDGE_WEIGHT: Record<string, number> = {
  data: 4,
  call: 2,
  control: 2,
  config: 1,
};

export function edgeWeight(kind: string): number {
  const w = EDGE_WEIGHT[kind];
  return typeof w === 'number' ? w : 1;
}

/** Cards are always measured at full detail so LOD changes never relayout. */
export function nodeSize(kind: string, level: string, ghost: boolean): { w: number; h: number } {
  let w = NODE_W;
  if (kind === 'model' || kind === 'entrypoint' || level === 'stage') w = NODE_W_LG;
  else if (kind === 'layer') w = NODE_W_SM;
  return { w, h: ghost ? NODE_H_GHOST : NODE_H };
}

export const BACK_EDGE_DROP = 26;

/**
 * Rank wrapping (MLV-R1-002). dagre puts every edge-less sibling in rank 0, so a
 * lane of unconnected calls becomes one very tall column and `fit()` lands at
 * the zoom floor. Any rank taller than MAX_RANK_H is wrapped into sub-columns,
 * which grows the lane along the axis the canvas actually has width in.
 */
export const MAX_RANK_H = 3 * NODE_H + 2 * 24;
export const RANK_ROW_GAP = 24;
export const RANK_COL_GAP = 28;

/** A free horizontal band reserved at the bottom of every lane for detours. */
export const LANE_ROUTE_BAND = 20;
/** Clearance kept between a routed run and any node box. */
export const ROUTE_CLEARANCE = 8;
export const GUTTER_LANE_STEP = 14;
export const CORNER_R = 8;
