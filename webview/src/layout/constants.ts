/**
 * Geometry and layout constants. The card widths, NODE_H and GROUP_HEADER_H equal their tokens
 * in styles/tokens.css.
 */

export const NODE_W = 216;
export const NODE_W_LG = 248;
export const NODE_W_SM = 176;
/** Padding, border, title, sublabel and the `file : line` row (70.2 px, the sum of the table in `layout/cardmetrics.ts`). */
export const NODE_H = 72;
/** The same card without its `file : line` row (54.4 px by the same table). */
export const NODE_H_GHOST = 60;
/**
 * The chip row: a 22 px chip (an 18 px line, 1 px of padding and a 1 px border
 * above and below, in base.css and node.css) plus its 4 px top margin, added to
 * the box of a card that draws one: only a collapsed group, for its count. See
 * `layout/cardmetrics.ts`: it owns the decision, this is only the number.
 */
export const NODE_CHIP_ROW_H = 26;
/**
 * One more line of a wrapped authored card title: the
 * 13 px title at line-height 1.35 is 17.55 px; the half pixel is headroom.
 */
export const NODE_TITLE_LINE_H = 18;
/** An authored title wraps to at most this many lines on the card. */
export const NODE_TITLE_MAX_LINES = 3;

export const GROUP_HEADER_H = 34;
export const GROUP_PAD = 16;
export const GROUP_MIN_W = 200;
export const GROUP_MIN_H = 56;

export const LANE_HEADER_H = 28;
export const LANE_PAD = 28;
export const LANE_GUTTER = 40;
/**
 * The floor on a lane box's width. Lane boxes are not stretched to the widest
 * lane, so this is the ONLY thing that can leave a lane box wider than its own
 * content: it gives a nearly empty band room for its header, the phase name,
 * the step count and the severity cluster.
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
 * Card sizing is in `layout/cardmetrics.ts`: the height depends on what the
 * card will DRAW (a `file : line` row, a chip row), and a flat constant per
 * node would make the layout disagree with the ink. The constants above are the
 * vocabulary it works in.
 */

export const BACK_EDGE_DROP = 26;

/**
 * Rank wrapping. dagre puts every edge-less sibling in rank 0, so a
 * lane of unconnected calls becomes one very tall column and `fit()` lands at
 * the zoom floor. Any rank taller than MAX_RANK_H is wrapped into sub-columns,
 * which grows the lane along the axis the canvas actually has width in.
 */
export const MAX_RANK_H = 3 * NODE_H + 2 * 24;
export const RANK_ROW_GAP = 24;
export const RANK_COL_GAP = 28;

/**
 * Row wrapping, the width twin of MAX_RANK_H.
 *
 * Under `rankdir: LR` a rank is a COLUMN, so a lane's width is the sum of its
 * ranks: many sibling groups side by side lay one very wide row, and the whole
 * document then fits only at the zoom floor. A container whose dagre result is
 * wider than MAX_RANK_W has its rank sequence wrapped into stacked rows — the
 * same trade MAX_RANK_H makes in the other axis, spending height (which the
 * reader pans through anyway) to buy back the zoom.
 *
 * It is a CONSTANT, not a function of the viewport: the layout must be the
 * same at every canvas size.
 */
export const MAX_RANK_W = 2000;

/** A free horizontal band reserved at the bottom of every lane for detours. */
export const LANE_ROUTE_BAND = 20;
/** Clearance kept between a routed run and any node box. */
export const ROUTE_CLEARANCE = 8;
export const GUTTER_LANE_STEP = 14;
export const CORNER_R = 8;

/**
 * The left channel is reserved per lane PAIR, not per edge. Every observed edge
 * of a pair shares ONE trunk, so the channel needs one slot per distinct
 * (source lane, target lane) pair and its width is a function of the pair
 * count. A slot for every edge would have no bound, and the later edges of a
 * large pair would run through the first column of lane boxes.
 *
 * `CHANNEL_PAD_L` keeps `channelX` at `CANVAS_MARGIN + 16`, so a document with
 * two skipping pairs reserves 56 px.
 */
export const CHANNEL_PAD_L = 16;
export const CHANNEL_PAD_R = 12;
/** Distance between two trunks in the channel, per PAIR: the gutter's lane step. */
export const CHANNEL_PAIR_STEP = GUTTER_LANE_STEP;
/**
 * The channel stops growing here: every pixel reserved on the left is a pixel
 * `fit()` has to zoom out to show. Two pairs reserve 56 px; past six pairs the
 * STEP shrinks instead of the world growing, down to `CHANNEL_MIN_STEP`, and
 * past that the trunks share slots.
 *
 * This caps the observed trunks only. The tracks of inferred and unresolved
 * cables that skip a lane (`EXCEPTION_TRACK_STEP` apart, below) are not
 * capped, so many of them widen the channel past it.
 */
export const CHANNEL_MAX_W = 112;
/** Two trunks closer than this read as one, so trunks past the last slot share the innermost. */
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

/**
 * An inferred or unresolved cable is never in a trunk and runs on a
 * track of its own. In the left channel each one that skips a lane takes a slot
 * `EXCEPTION_TRACK_STEP` px inside the innermost observed trunk, and the channel widens only when
 * those slots would come closer than `EXCEPTION_PAD` px to the bands. `layout/separate.ts` moves its
 * other runs off shared ones: it aims for `EXCEPTION_CLEAR` px from any parallel stroke and counts
 * `EXCEPTION_HIDDEN` px as drawn on it, the distance at which a dash pattern reads as the solid line
 * beside it. A run moves at most `EXCEPTION_MAX_SHIFT` px.
 */
export const EXCEPTION_TRACK_STEP = 8;
export const EXCEPTION_PAD = 10;
export const EXCEPTION_CLEAR = 8;
export const EXCEPTION_HIDDEN = 4;
export const EXCEPTION_MAX_SHIFT = 40;
