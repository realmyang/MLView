/**
 * VIEW-04 — the cross-lane channel plan.
 *
 * Every edge that leaves its lane runs through one of two reserved corridors:
 * the GUTTER between two adjacent bands, or the left CHANNEL for a hop that
 * skips a lane. Before this module they were fanned out one edge at a time —
 * `routeCrossLane` staggered by a per-lane-pair counter, `n * 7` — so a lane
 * pair with twenty connections spread 140 px of near-parallel vertical runs
 * across a 56 px channel, walked straight through the lane boxes beside it, and
 * braided with every other pair on the way. That fan is where most of the 49.5
 * crossings per edge came from.
 *
 * The plan replaces the counter with three decisions, all of them made ONCE per
 * (source lane, target lane) pair:
 *
 *  1. **One trunk per pair.** Every member of a pair shares one channel x (a
 *     skipping hop) or one gutter y (an adjacent hop). What used to be N runs
 *     is one run with N shoulders.
 *  2. **Barycentre order.** A pair's members are ordered by the y of their
 *     target inside the destination lane, and the pairs themselves are ordered
 *     so the longest hop takes the OUTERMOST slot — a trunk whose entry and
 *     exit sit outside every other trunk's span cannot be crossed by them, so
 *     the trunks nest instead of braiding.
 *  3. **A bounded splay.** A member sits `±BUNDLE_MEMBER_SPREAD` off its
 *     trunk's shoulder at most, so a run can never leave the corridor it was
 *     reserved in, however many edges the pair carries.
 *
 * Pure geometry over the LayoutFrame and the routing buckets: no DOM, no
 * measurement, and every collection walked in document order, so it is exactly
 * as deterministic as the layout it consumes.
 */

import type { LayoutBox, LayoutFrame } from './layout.js';
import { BUNDLE_MEMBER_SPREAD, BUNDLE_MEMBER_STEP } from './constants.js';

/** One routing bucket that leaves its lane, as the plan needs to see it. */
export interface CrossBucket {
  /** The routing bucket key — `source target kind subkind`. */
  key: string;
  sBox: LayoutBox;
  tBox: LayoutBox;
}

export interface LanePair {
  /** `<source lane>><target lane>`. */
  key: string;
  sourceLane: string;
  targetLane: string;
  /** True when the two bands touch, so the hop uses a gutter and not the channel. */
  adjacent: boolean;
  /** True when the target lane is BELOW the source lane. */
  down: boolean;
  /** Bucket keys, barycentre-ordered by the y of their target. */
  members: string[];
  /** The shared vertical trunk x in the left channel. Skipping pairs only. */
  trunkX: number;
  /** The gutter the entry spurs converge in, and the one the exit spurs leave. */
  entryY: number;
  exitY: number;
  /** Slot inside the channel, 0 = outermost (leftmost). Skipping pairs only. */
  slot: number;
}

export interface ChannelPlan {
  /** pair key -> the pair. */
  pairs: Map<string, LanePair>;
  /** bucket key -> the pair it belongs to. */
  pairOf: Map<string, LanePair>;
  /** bucket key -> its index inside that pair, in barycentre order. */
  indexOf: Map<string, number>;
}

/** Mid-gutter y between lane `i` and lane `i + 1`. */
export function gutterY(frame: LayoutFrame, i: number): number {
  const a = frame.lanes[i];
  const b = frame.lanes[i + 1];
  if (a && b) return (a.y + a.h + b.y) / 2;
  if (a) return a.y + a.h + 12;
  if (b) return b.y - 12;
  return 0;
}

/**
 * How far member `i` of an `m`-member trunk sits off the shoulder.
 *
 * Centred on the trunk and CLAMPED: the whole splay always fits inside
 * `±limit`, whatever `m` is, because the corridor it lives in — a 40 px lane
 * gutter — does not grow with the number of edges that want to use it. A pair
 * of two splays by the full step; a pair of thirty splays by a hair and reads
 * as the single cable it is drawn as.
 */
export function memberSplay(i: number, m: number, limit = BUNDLE_MEMBER_SPREAD, step = BUNDLE_MEMBER_STEP): number {
  if (m <= 1) return 0;
  const used = Math.min(step, (2 * limit) / (m - 1));
  return round((i - (m - 1) / 2) * used);
}

/**
 * Order the trunks that share the channel.
 *
 * The roadmap asks for a barycentre sort on the y of the target; what actually
 * makes trunks NEST is the vertical span, so the span leads and the barycentre
 * breaks its ties. Reason: every trunk is a vertical run at its own x, entered
 * and left by horizontal spurs. An outer (further left) trunk's spurs cross
 * every inner trunk whose span covers the spur's y — so the trunk that reaches
 * furthest belongs outermost, where its entry sits above and its exit below
 * everything nested inside it. Sorting by target y alone braids two hops that
 * end in the same band but start four lanes apart.
 */
function compareTrunks(a: LanePair, b: LanePair, bary: Map<string, number>): number {
  const spanA = Math.abs(a.exitY - a.entryY);
  const spanB = Math.abs(b.exitY - b.entryY);
  if (Math.abs(spanA - spanB) > 0.5) return spanB - spanA;
  const ba = bary.get(a.key) ?? 0;
  const bb = bary.get(b.key) ?? 0;
  if (Math.abs(ba - bb) > 0.5) return ba - bb;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/**
 * Group the cross-lane buckets into lane pairs and give each pair its trunk.
 *
 * `buckets` arrives in document order, which is what makes the barycentre sort
 * — and therefore every routed point — reproducible.
 */
export function planChannel(frame: LayoutFrame, buckets: CrossBucket[]): ChannelPlan {
  const pairs = new Map<string, LanePair>();
  const pairOf = new Map<string, LanePair>();
  const indexOf = new Map<string, number>();
  const grouped = new Map<string, CrossBucket[]>();
  const order: string[] = [];

  for (const bucket of buckets) {
    const key = bucket.sBox.laneId + '>' + bucket.tBox.laneId;
    const list = grouped.get(key);
    if (list) list.push(bucket);
    else {
      grouped.set(key, [bucket]);
      order.push(key);
    }
  }

  const bary = new Map<string, number>();
  const skipping: LanePair[] = [];

  for (const key of order) {
    const list = grouped.get(key)!;
    // Barycentre order: the y of the target inside the destination lane, so the
    // spurs leave the trunk in the order their targets are stacked.
    list.sort((a, b) => cy(a.tBox) - cy(b.tBox) || cx(a.tBox) - cx(b.tBox) || compareKey(a.key, b.key));
    const first = list[0];
    const si = frame.laneIndex.get(first.sBox.laneId) ?? 0;
    const ti = frame.laneIndex.get(first.tBox.laneId) ?? 0;
    const down = ti > si;
    const adjacent = Math.abs(ti - si) === 1;
    const entryY = round(adjacent ? gutterY(frame, Math.min(si, ti)) : down ? gutterY(frame, si) : gutterY(frame, si - 1));
    const exitY = round(adjacent ? entryY : down ? gutterY(frame, ti - 1) : gutterY(frame, ti));
    const pair: LanePair = {
      key,
      sourceLane: first.sBox.laneId,
      targetLane: first.tBox.laneId,
      adjacent,
      down,
      members: list.map((b) => b.key),
      trunkX: frame.channelX,
      entryY,
      exitY,
      slot: 0,
    };
    pairs.set(key, pair);
    let sum = 0;
    for (const bucket of list) sum += cy(bucket.tBox);
    bary.set(key, list.length ? sum / list.length : 0);
    list.forEach((bucket, i) => {
      pairOf.set(bucket.key, pair);
      indexOf.set(bucket.key, i);
    });
    if (!adjacent) skipping.push(pair);
  }

  // Slot the skipping trunks across the reserved channel. `channelSlots` is what
  // `layoutGraph` widened the channel by; a pair count that outruns the
  // reservation piles onto the INNERMOST slot rather than wrapping round to the
  // outermost, because the outer slots are the ones the widest-span trunks need
  // in order to nest. Two trunks that end up sharing a slot are collinear, which
  // is the one relationship a pair of vertical runs can have without crossing.
  const slots = Math.max(1, frame.channelSlots);
  skipping.sort((a, b) => compareTrunks(a, b, bary));
  skipping.forEach((pair, i) => {
    pair.slot = i;
    pair.trunkX = round(frame.channelX + Math.min(i, slots - 1) * frame.channelStep);
  });

  return { pairs, pairOf, indexOf };
}

function cx(b: LayoutBox): number {
  return b.x + b.w / 2;
}

function cy(b: LayoutBox): number {
  return b.y + b.h / 2;
}

function compareKey(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function round(v: number): number {
  return Math.round(v * 100) / 100;
}
