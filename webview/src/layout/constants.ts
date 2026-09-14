/** Geometry and layout constants. Mirrors the token geometry in styles/tokens.css. */

export const NODE_W = 216;
export const NODE_W_LG = 248;
export const NODE_W_SM = 176;
/** Padding, border, title, sublabel and the `file : line` row (70.1 px drawn). */
export const NODE_H = 72;
/** The same card without its `file : line` row (54.4 px drawn). */
export const NODE_H_GHOST = 60;
/**
 * The attribute chip row: an 18 px chip line plus its 4 px top margin, added to
 * the box of every card that draws one (VW-01). See `layout/cardmetrics.ts` —
 * it owns the decision, this is only the number.
 */
export const NODE_CHIP_ROW_H = 26;

export const GROUP_HEADER_H = 34;
export const GROUP_PAD = 16;
export const GROUP_MIN_W = 200;
export const GROUP_MIN_H = 56;

export const LANE_HEADER_H = 28;
export const LANE_PAD = 28;
export const LANE_GUTTER = 40;
/**
 * The floor on a lane box's width (VIEW-01). Lane boxes are no longer stretched
 * to the widest lane, so this is now the ONLY thing that can leave a lane box
 * wider than its own content: it exists so a nearly empty band still has room
 * for its header — the stage name, the node count and the severity cluster,
 * which measure about 250 px together at the 11/10 px caps type in canvas.css.
 */
export const LANE_MIN_W = 320;
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

/**
 * Card sizing moved to `layout/cardmetrics.ts` (VW-01): the height depends on
 * what the card will DRAW — a `file : line` row, an attribute chip row — and a
 * flat constant per node made the layout disagree with the ink on every
 * notebook report. The constants above are still the vocabulary it works in.
 */

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

/**
 * Row wrapping (VIEW-01), the width twin of MAX_RANK_H.
 *
 * Under `rankdir: LR` a rank is a COLUMN, so a lane's width is the sum of its
 * ranks: nine sibling groups in a 300-node project laid one 10 232 px row, the
 * world became 10 408 x 3 234 and `fit()` picked the 0.15 zoom floor at every
 * viewport. A container whose dagre result is wider than MAX_RANK_W has its
 * rank sequence wrapped into stacked rows — the same trade MAX_RANK_H makes in
 * the other axis, spending height (which the reader pans through anyway) to buy
 * back the zoom.
 *
 * It is a CONSTANT, not a function of the viewport: the layout must be
 * byte-identical in the VS Code webview, the standalone report and the layout
 * gates, all of which see different canvas sizes. 2000 px is roughly a
 * comfortable 1600 px canvas at the ~0.6 zoom a legible first paint wants, and
 * it sits above every lane in the shipped demo — whose widest lane content is
 * 1400 px before and after the ANA-1/2/3 re-baseline — so the flagship layout is
 * untouched.
 */
export const MAX_RANK_W = 2000;

/** A free horizontal band reserved at the bottom of every lane for detours. */
export const LANE_ROUTE_BAND = 20;
/** Clearance kept between a routed run and any node box. */
export const ROUTE_CLEARANCE = 8;
export const GUTTER_LANE_STEP = 14;
export const CORNER_R = 8;

/**
 * VIEW-04 — the left channel is reserved per lane PAIR, not per edge.
 *
 * It used to be a flat 56 px whatever the document held, while `routeCrossLane`
 * fanned the edges inside it at `n * 7` with no bound: the seventh skipping edge
 * of a lane pair was drawn at x = 90 in a channel that ends at 88, i.e. through
 * the first column of lane boxes, and a 300-node project put roughly twenty
 * near-parallel runs in there. Every edge of a pair now shares ONE trunk, so the
 * channel needs one slot per distinct (source lane, target lane) pair and the
 * width is a function of the pair count.
 *
 * `CHANNEL_PAD_L` keeps `channelX` at `CANVAS_MARGIN + 16` — where it has always
 * been — so a document with two skipping pairs reserves exactly the 56 px it
 * reserved before.
 */
export const CHANNEL_PAD_L = 16;
export const CHANNEL_PAD_R = 12;
/** Distance between two trunks in the channel. The old fan-out step, per PAIR. */
export const CHANNEL_PAIR_STEP = GUTTER_LANE_STEP;
/**
 * The channel stops growing here, and this is the number VIEW-01 cares about:
 * every pixel reserved on the left is a pixel `fit()` has to zoom out to show.
 * Two pairs still reserve exactly the 56 px the flat channel always did; past
 * four pairs the STEP shrinks instead of the world growing, down to
 * `CHANNEL_MIN_STEP`, and past that the trunks share slots. 112 px is twice the
 * old reservation and costs the shipped demo 3.4 % of its width.
 */
export const CHANNEL_MAX_W = 112;
/** Two trunks closer than this read as one, so slots wrap instead. */
export const CHANNEL_MIN_STEP = 4;

/**
 * How far a bundle member may splay off its trunk's shoulder, and the step it
 * takes. The spread is bounded by the corridor: a lane gutter is `LANE_GUTTER`
 * = 40 px, so ±13 leaves 7 px of clearance to the bands on either side however
 * many edges the pair carries.
 */
export const BUNDLE_MEMBER_SPREAD = 13;
export const BUNDLE_MEMBER_STEP = 6;
/**
 * A trunk shorter than this is not worth drawing: the group is rendered as its
 * individual strokes instead, which is also what a one-member group gets.
 */
export const BUNDLE_MIN_TRUNK = 28;
