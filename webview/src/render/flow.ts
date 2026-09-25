/**
 * The flow layer — "an electron moving through a cable from one end to the
 * other" (CONTRACTS 11.13, FEATURES section 2).
 *
 * An edge is a cable: an OUTLET on the producer, an INLET on the consumer, and a
 * CHARGE that travels between them. Hovering one cable runs a single charge
 * along it (pulse); hovering a card runs a train of charges along everything the
 * card is wired to, hop by hop (stream).
 *
 * Three properties make this cheap, and none of them may be given up:
 *
 * 1. DIRECTION IS NEVER DERIVED. Every router emits `points` source -> target
 *    (`layout/routing.ts`), so animating `stroke-dashoffset` along the edge's own
 *    `d` flows inward on an upstream edge and outward on a downstream one with
 *    zero reversal logic. Nothing here may reintroduce a per-edge direction
 *    decision.
 * 2. LENGTH IS THE POLYLINE SUM over `RoutedEdge.points`. The DOM path API for
 *    measuring a path is NEVER called: jsdom does not implement it, so measuring
 *    the DOM would make the tested path a different path from the shipped one.
 *    `test/bundle.test.mjs` asserts the built bundle never names that call.
 * 3. NOTHING ANIMATES THAT THE USER DID NOT CAUSE. Every element here is created
 *    lazily inside an already-debounced hover callback and destroyed by the next
 *    `render()` or `clear()`.
 *
 * On the two SHAPES a charge takes (CONTRACTS 11.13.1, 2026-09-08). A single
 * hovered or latched cable runs a DOT: a `<g class="mlv-edge__charge">` of three
 * concentric circles moved by a SMIL `<animateMotion>` whose `<mpath>` rides the
 * edge's own visible path. A lineage STREAM keeps the dash train, because there
 * the reading is "how dense is the traffic on this hop", which a dash pattern
 * states in one glance and thirty independent dots do not — and because a stream
 * may decorate up to `FLOW.MAX_EDGES` cables at once, where one SMIL timeline
 * per edge is a cost the dash pattern does not pay.
 *
 * On `pathLength="100"`: the contract fixes it, and it is what lets the charge
 * geometry be expressed in ONE normalized space. A dash value on such a path is
 * read in hundredths of the route, so the px intent of the tokens
 * (`--mlv-flow-head`, `--mlv-flow-gap`) is converted to path units per edge —
 * `100 * px / L` — and written back onto the same custom properties inline. The
 * apparent head, gap and speed of a STREAM are then constant across a 60 px stub
 * and a 900 px cross-lane detour, which is the whole point of the constant-speed
 * spec: a stream's period is a constant per kind, so the conversion is the only
 * per-edge value it needs.
 *
 * A PULSE is the documented exception, and the exception is the CLAMP, not the
 * conversion — see `pulseDurationMs`.
 */

import { svg, XLINK_NS } from '../dom.js';
import type { MotionMode } from '../motion.js';
import type { Point, RoutedEdge } from '../layout/routing.js';

/**
 * Every number the animation depends on, in one frozen table. Exported through
 * `__internal.flow` so tests assert against the shipped constants instead of
 * hard-coding a timing that can drift (CONTRACTS 11.13).
 */
export const FLOW = {
  /** Above this many lit edges a trace goes static: nothing animates. */
  MAX_EDGES: 120,
  /** Single-pass charge speed, px/s, clamped to [MIN_MS, MAX_MS]. */
  PULSE_SPEED: 320,
  PULSE_MIN_MS: 380,
  PULSE_MAX_MS: 2200,
  /** One stream speed for every edge kind; only the gap varies. */
  STREAM_SPEED: 220,
  HEAD_PX: 12,
  GAP_DATA: 34,
  GAP_CALL: 96,
  GAP_BACK: 24,
  /** (head + gap) / STREAM_SPEED, rounded — mirrored by the CSS tokens. */
  PERIOD_DATA: 210,
  PERIOD_CALL: 490,
  PERIOD_BACK: 165,
  /** Per-hop wave delay, capped at HOP_MAX hops. */
  HOP_MS: 90,
  HOP_MAX: 6,
  PORT_R: 3.5,
  /* The travelling dot (CONTRACTS 11.13.1). Three stacked opacities, never a
   * filter primitive: `feGaussianBlur` on a moving element re-rasterizes its
   * filter region every frame, which is exactly the cost flow.css's header
   * rules out. */
  CHARGE_HALO_R: 9,
  CHARGE_GLOW_R: 5.5,
  CHARGE_CORE_R: 2.6,
  /**
   * Above this route length ONE dot leaves most of the cable empty for most of
   * the cycle, so a second rides half a period behind it. 360 px is the width of
   * roughly one and a half node cards — the point at which the eye stops reading
   * "a charge is crossing" and starts reading "nothing is happening".
   */
  CHARGE_TWIN_PX: 360,
};

/** The effective mode, mirrored onto `.mlv-canvas` as `data-flow`. */
export type FlowMode = 'motion' | 'static' | 'off';

/**
 * What a lineage stream actually did, so the VIEW can speak for it.
 * `capped` is the one branch a user cannot see for themselves: the trace was
 * suppressed because it is denser than `FLOW.MAX_EDGES`, and scoping the
 * diagram is the way to get the animation back (CONTRACTS 11.14 C5).
 */
export interface StreamResult {
  mode: FlowMode;
  /** True only when DENSITY is the reason nothing was decorated. */
  capped: boolean;
  /** Lit edges in the lineage — the number the capped copy quotes. */
  edges: number;
}

/** Inline custom properties this layer writes; cleared as one set. */
const FLOW_PROPS = [
  '--mlv-flow-dur',
  '--mlv-flow-len',
  '--mlv-flow-head',
  '--mlv-flow-gap',
  '--mlv-flow-end',
  '--mlv-flow-delay',
];

const FLOW_CLASSES = ['is-flowing', 'is-flowing--pulse'];

/** Sum of the segment lengths of the route's own polyline. Never the DOM. */
export function polylineLength(points: Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const dx = points[i].x - points[i - 1].x;
    const dy = points[i].y - points[i - 1].y;
    total += Math.sqrt(dx * dx + dy * dy);
  }
  return total;
}

/**
 * `length / PULSE_SPEED`, CLAMPED — and the clamp is what a reader has to know
 * before quoting "constant apparent speed" at this function (R3-CHG-04).
 *
 * Between the clamps the speed really is 320 px/s; at either clamp it is not,
 * and in the shipped sample both bind — a 72 px call edge stretched from 225 ms
 * to `PULSE_MIN_MS` (0.59x nominal), a 2128 px data edge compressed from 6650 ms
 * to `PULSE_MAX_MS` (3.02x), a 5.1x spread under one gesture. Invisible while
 * the charge was a scrolling dash; legible now that it is one trackable bead.
 * The three numbers are pinned in CONTRACTS 11.13 / 11.13.2, FEATURES 2.4 (F1-A3
 * asserts them) and UX_DESIGN, so widening the clamp is a contract amendment,
 * not a renderer-local change.
 */
export function pulseDurationMs(length: number): number {
  const raw = Math.round((length / FLOW.PULSE_SPEED) * 1000);
  return Math.max(FLOW.PULSE_MIN_MS, Math.min(FLOW.PULSE_MAX_MS, raw));
}

/**
 * Density per kind (FEATURES 2.6): a loop looks busy and a call looks sparse
 * while everything moves at the same 220 px/s.
 */
export function streamGapPx(kind: string, subkind?: string, back?: boolean): number {
  if (kind === 'control') return back || subkind === 'back' ? FLOW.GAP_BACK : FLOW.GAP_CALL;
  if (kind === 'call') return FLOW.GAP_CALL;
  return FLOW.GAP_DATA;
}

/** `config` fans out from a literal to everything; it never joins a stream. */
export function streamsInLineage(route: RoutedEdge): boolean {
  return route.kind !== 'config';
}

/**
 * Lineage with a HOP COUNT per edge, so a node hover streams outward and inward
 * in order instead of lighting everything at once. Same traversal as
 * `render/trace.ts` — forward-reachable union backward-reachable — so the
 * flowing set is always a subset of the lit set.
 */
export function lineageHops(routes: RoutedEdge[], id: string): { nodes: Map<string, number>; edges: Map<string, number> } {
  const nodes = new Map<string, number>([[id, 0]]);
  const edges = new Map<string, number>();
  const walk = (forward: boolean): void => {
    let frontier = [id];
    const seen = new Set<string>([id]);
    let hop = 0;
    while (frontier.length) {
      hop++;
      const next: string[] = [];
      for (const cur of frontier) {
        for (const route of routes) {
          const from = forward ? route.source : route.target;
          const to = forward ? route.target : route.source;
          if (from !== cur) continue;
          const seenHop = edges.get(route.id);
          if (seenHop === undefined || hop < seenHop) edges.set(route.id, hop);
          if (seen.has(to)) continue;
          seen.add(to);
          const nodeHop = nodes.get(to);
          if (nodeHop === undefined || hop < nodeHop) nodes.set(to, hop);
          next.push(to);
        }
      }
      frontier = next;
    }
  };
  walk(true);
  walk(false);
  return { nodes, edges };
}

export interface FlowHost {
  canvas: HTMLElement;
  edges(): Map<string, SVGElement>;
  nodes(): Map<string, HTMLElement>;
  routes(): RoutedEdge[];
  /**
   * Composition rule C2 (CONTRACTS 11.14): a charge may stream along an edge
   * only when the document is unprojected, or when BOTH endpoints are `core`.
   * A boundary node's other connections are cut, so a charge animating into it
   * would lie about where the value goes.
   */
  streamEligible(route: RoutedEdge): boolean;
}

/**
 * Owns every flow element on the canvas. One instance per CanvasView; the view
 * decides WHEN a flow starts (hover intent, focus, selection latch) and this
 * decides WHAT is drawn.
 */
export class FlowController {
  private host: FlowHost;
  private enabledFlag = true;
  private motionFlag: MotionMode = 'full';
  /** Edge ids currently carrying flow elements or inline properties. */
  private decorated: string[] = [];
  private sourceId: string | null = null;
  private targetId: string | null = null;

  constructor(host: FlowHost) {
    this.host = host;
  }

  get enabled(): boolean {
    return this.enabledFlag;
  }

  get motion(): MotionMode {
    return this.motionFlag;
  }

  /** The mode with nothing flowing — what `data-flow` reads at rest. */
  get restMode(): FlowMode {
    return this.modeFor(0);
  }

  setEnabled(on: boolean): void {
    if (this.enabledFlag === on) return;
    this.enabledFlag = on;
    this.clear();
  }

  setMotion(mode: MotionMode): void {
    if (this.motionFlag === mode) return;
    this.motionFlag = mode;
    this.clear();
  }

  /** Stamp `data-motion` and the resting `data-flow` onto the canvas. */
  syncCanvas(): void {
    this.host.canvas.setAttribute('data-motion', this.motionFlag);
    this.host.canvas.setAttribute('data-flow', this.restMode);
  }

  /**
   * Idempotent (CONTRACTS 11.14 C1). Removes every flow element, every
   * `--mlv-flow-*` inline property and both endpoint rings, and returns the
   * canvas to its resting mode. The re-projection path calls it once.
   */
  clear(): void {
    const edges = this.host.edges();
    for (const id of this.decorated) {
      const g = edges.get(id);
      if (g) stripEdge(g);
    }
    this.decorated = [];
    // A re-render replaces the map, so also sweep whatever is still standing.
    for (const g of edges.values()) {
      if (g.classList.contains('is-flowing') || g.classList.contains('is-flowing--pulse')) stripEdge(g);
    }
    const nodes = this.host.nodes();
    if (this.sourceId) {
      const el = nodes.get(this.sourceId);
      if (el) el.classList.remove('is-flow-source');
    }
    if (this.targetId) {
      const el = nodes.get(this.targetId);
      if (el) el.classList.remove('is-flow-target');
    }
    this.sourceId = null;
    this.targetId = null;
    for (const el of nodes.values()) {
      el.classList.remove('is-flow-source');
      el.classList.remove('is-flow-target');
    }
    this.host.canvas.setAttribute('data-motion', this.motionFlag);
    this.host.canvas.setAttribute('data-flow', this.restMode);
  }

  /**
   * One charge along one cable — edge hover, edge focus, edge selection. A
   * DIRECT gesture pulses ANY drawn edge, including one touching a boundary or
   * context node (CONTRACTS 11.14 C3): the user pointed at that edge, not at a
   * lineage, and it is fully drawn and fully real.
   */
  pulse(route: RoutedEdge): void {
    this.clear();
    const mode = this.modeFor(1);
    this.host.canvas.setAttribute('data-flow', mode);
    if (mode === 'off') return;
    const g = this.host.edges().get(route.id);
    if (!g) return;
    this.decorate(g, route, mode, null);
    g.classList.add('is-flowing--pulse');
    this.decorated.push(route.id);
    const nodes = this.host.nodes();
    const src = nodes.get(route.source);
    const dst = nodes.get(route.target);
    if (src) {
      src.classList.add('is-flow-source');
      this.sourceId = route.source;
    }
    if (dst) {
      dst.classList.add('is-flow-target');
      this.targetId = route.target;
    }
  }

  /**
   * A train of charges along the lineage of one node, hop by hop. The lit set is
   * the trace's; the FLOWING set is the flow-eligible subset of it.
   *
   * Two branches decorate nothing, for different reasons, and the difference is
   * reported back so the view can say which happened:
   *
   *  - DENSITY. Above `FLOW.MAX_EDGES` lit edges the trace goes `static` and
   *    nothing is drawn: 120 animated strokes repaint the edge layer every
   *    frame, and 120 chevrons are noise rather than information. The lineage
   *    still reads through `.is-lit`, and `capped` in the result is what lets
   *    the view name scoping as the way to get the animation back (11.14 C5).
   *  - `off`. The user turned the layer off; there is nothing to explain.
   *
   * Under `reduce` — but INSIDE the cap — the stream is still decorated, with
   * the static substitute of FEATURES 2.8: ports and a chevron per eligible
   * edge. Motion is optional; the direction it carries is not (goal G4).
   */
  stream(nodeId: string): StreamResult {
    this.clear();
    const routes = this.host.routes();
    const hops = lineageHops(routes, nodeId);
    const count = hops.edges.size;
    const mode = this.modeFor(count);
    this.host.canvas.setAttribute('data-flow', mode);
    const dense = count > FLOW.MAX_EDGES;
    // DENSITY is reported as density whatever the motion preference. Reduced
    // motion is a preference, not a limit — but a dense lineage decorates
    // nothing for EITHER audience, and the reduced-motion user is the one who
    // has no animation to fall back on. Suppressing the message for them left
    // the single audience with the least feedback as the only one told nothing
    // at all (R2-FLOW-03 / R2-FLOW-07). The copy names the outcome the reader
    // actually gets (`cappedTraceMessage`), not the word "animate".
    const capped = dense && mode !== 'off';
    if (mode === 'off' || dense) return { mode, capped, edges: count };
    const edges = this.host.edges();
    for (const route of routes) {
      const hop = hops.edges.get(route.id);
      if (hop === undefined) continue;
      if (!streamsInLineage(route)) continue;
      if (!this.host.streamEligible(route)) continue;
      const g = edges.get(route.id);
      if (!g) continue;
      this.decorate(g, route, mode, hop);
      g.classList.add('is-flowing');
      this.decorated.push(route.id);
    }
    return { mode, capped, edges: count };
  }

  private modeFor(litEdges: number): FlowMode {
    if (!this.enabledFlag) return 'off';
    if (this.motionFlag === 'reduced') return 'static';
    if (litEdges > FLOW.MAX_EDGES) return 'static';
    return 'motion';
  }

  /**
   * Build the parts. `hop` non-null means a lineage stream (a dash train: gap
   * per kind, wave delay); null means a single-pass pulse (a travelling dot on a
   * static wash, duration from length — CONTRACTS 11.13.1).
   *
   * On the hop delay: `min(hop, HOP_MAX) * HOP_MS` is the contract's number
   * (11.13), and `animation-delay` only shifts the START of a loop — after the
   * first cycle the perceived phase is `delay mod period`, so on a 210 ms data
   * edge the radiating wave reads in hop order for its first pass and settles
   * into a fixed pattern afterwards. That is deliberate and contract-fixed; do
   * not "fix" it by scaling the delay into one period without amending 11.13,
   * which F1-A4 pins to 90 ms / 180 ms for hops 1 and 2.
   */
  private decorate(g: SVGElement, route: RoutedEdge, mode: FlowMode, hop: number | null): void {
    const points = route.points || [];
    if (points.length < 2) return;
    const length = polylineLength(points);
    const style = (g as unknown as HTMLElement).style;

    g.appendChild(portCircle('out', points[0]));
    g.appendChild(portCircle('in', points[points.length - 1]));

    if (mode === 'static') {
      // No motion is allowed, so direction is carried by a chevron at the route's
      // midpoint pointing at the inlet, plus hollow-outlet / filled-inlet ports.
      g.appendChild(directionMark(route));
      return;
    }

    // CONTRACTS 11.13: the charge rides the VISIBLE geometry — same `d`.
    //
    // In a STREAM this path IS the charge train (the dash pattern below). In a
    // PULSE it is kept as a static, faint, full-length UNDERLAY and the moving
    // part is the dot built underneath. Three reasons it was kept rather than
    // dropped (CONTRACTS 11.13.1): the underlay is what carries `--mlv-flow-color`
    // along the WHOLE cable, so the severity-red softmax -> CrossEntropyLoss
    // connection still reads red between passes instead of only under the 18 px
    // dot; it gives the halo a surface to sit on, which is what makes a soft dot
    // read as a charge inside a wire rather than a sticker on top of one; and it
    // keeps the cable visibly ENERGISED for the whole hover, which one dot on a
    // 900 px detour does not. It costs one extra path on exactly one edge,
    // because a pulse decorates exactly one edge.
    const flow = svg('path', { class: 'mlv-edge__flow', d: route.d, pathLength: 100 });
    g.appendChild(flow);

    const headU = pathUnits(FLOW.HEAD_PX, length);
    style.setProperty('--mlv-flow-len', round2(length) + 'px');
    style.setProperty('--mlv-flow-head', String(headU));
    if (hop === null) {
      const dur = pulseDurationMs(length);
      style.setProperty('--mlv-flow-dur', dur + 'ms');
      // A degenerate route has no geometry to ride; `<mpath>` on a zero-length
      // path is undefined behaviour, so nothing is built (11.13.1 rule 5).
      const pathId = length > 0 ? visiblePathId(g) : '';
      if (pathId) {
        // ONE reading of the document timeline for both dots, so the twin is
        // exactly half a period behind the lead one (R3-CHG-01).
        const t0 = timelineNow(g);
        g.appendChild(chargeDot(pathId, dur, 0, t0));
        // A long cable would otherwise be empty for most of every cycle.
        if (length > FLOW.CHARGE_TWIN_PX) g.appendChild(chargeDot(pathId, dur, -Math.round(dur / 2), t0));
      }
    } else {
      const gap = streamGapPx(route.kind, route.subkind, route.back);
      const gapU = pathUnits(gap, length);
      style.setProperty('--mlv-flow-gap', String(gapU));
      // The RESOLVED end of one dash period, as a plain number. It must never be
      // written as `calc(-1 * (var(--mlv-flow-head) + var(--mlv-flow-gap)))` in
      // the keyframe: Chromium leaves a var()-derived calc() unsimplified, fails
      // to interpolate it against `0`, and silently downgrades the animation to
      // a DISCRETE step between two endpoints that are exactly one period apart
      // — i.e. two identical frames, a stream that never moves (R2-FLOW-01).
      // The pulse keyframe already does it this way; so does this one now.
      style.setProperty('--mlv-flow-end', String(round2(-(headU + gapU))));
      style.setProperty('--mlv-flow-delay', Math.min(hop, FLOW.HOP_MAX) * FLOW.HOP_MS + 'ms');
    }
  }
}

/**
 * The id of the edge's VISIBLE path — written by `render/edges.ts` for every
 * edge, unique per mount and per edge. Returns '' when there is none, which is
 * the one branch that skips the dot rather than pointing `<mpath>` at nothing.
 */
function visiblePathId(g: SVGElement): string {
  const path = g.querySelector('.mlv-edge__path');
  return path ? path.getAttribute('id') || '' : '';
}

/**
 * The owning `<svg>`'s CURRENT SMIL TIME, in seconds, or null where there is no
 * SMIL clock to read (jsdom, and any renderer without `getCurrentTime`).
 *
 * This is the whole of the R3-CHG-01 fix (CONTRACTS 11.13.2 rule 7). An
 * `<animateMotion>` with no `begin` resolves to `0s` ON THE SVG DOCUMENT
 * TIMELINE — not on the element's insertion time — and that clock started with
 * the page and is never stopped, so a charge built inside a hover callback forty
 * seconds in starts at phase `(40000 mod dur) / dur`. Measured over twelve
 * hovers of one 1269 ms cable, the first painted position was scattered across
 * the route (0.05 … 0.99) and never near the outlet: about one hover in four
 * spent its whole visible life beside the INLET, in a feature whose one sentence
 * is "an electron moving through a cable from one end to the other". Writing an
 * ABSOLUTE begin off this reading anchors the travel to the GESTURE instead.
 */
function timelineNow(g: SVGElement): number | null {
  try {
    const anyG = g as any;
    const owner = anyG.ownerSVGElement || (typeof anyG.closest === 'function' ? anyG.closest('svg') : null);
    if (!owner || typeof owner.getCurrentTime !== 'function') return null;
    const t = owner.getCurrentTime();
    return typeof t === 'number' && isFinite(t) ? t : null;
  } catch (_e) {
    return null;
  }
}

/**
 * ONE charge: a dot with a halo, travelling the cable (CONTRACTS 11.13.1).
 *
 *   <g class="mlv-edge__charge">
 *     <circle class="mlv-edge__charge-halo" r="9"/>     <- the hue, ~18% alpha
 *     <circle class="mlv-edge__charge-glow" r="5.5"/>   <- the hue, ~42% alpha
 *     <circle class="mlv-edge__charge-core" r="2.6"/>   <- surface, hue ring
 *     <animateMotion dur="<pulse>ms" repeatCount="indefinite" …>
 *       <mpath href="#mlv-p-<serial>-<edge hex>"/>
 *     </animateMotion>
 *   </g>
 *
 * The soft edge is three stacked opacities, NOT `feGaussianBlur`: a filter on a
 * moving element re-rasterizes its filter region every frame, which is the one
 * cost flow.css's header rules out. The circles sit at the group's origin and
 * the whole group is translated by the motion, so the three stay concentric for
 * free — and `rotate="auto"` is invisible on a circle, which is why the dot can
 * carry the contract's rotate value without the smearing a dash head would show.
 *
 * `begin` is anchored to the GESTURE, not to the page (R3-CHG-01). `t0` is the
 * owning `<svg>`'s current SMIL time, so the lead dot begins at `t0` — now, at
 * the outlet — and the trailing dot at `t0 - dur/2`, a moment already past,
 * which is a PHASE offset rather than a delay and puts it half a period ahead
 * from its first frame. Where there is no SMIL clock to read (jsdom, and any
 * renderer without `getCurrentTime`) the old form is written instead: no `begin`
 * on the lead dot, a negative millisecond offset on the twin.
 */
function chargeDot(pathId: string, durMs: number, beginMs: number, t0: number | null): SVGElement {
  // The twin is MARKED, because the CSS fade of 11.13.1 rule 7 has to be shifted
  // by the same half period the motion is: an un-shifted fade would dim the
  // trailing dot in the middle of the cable, where it is doing its whole job.
  const g = svg('g', { class: beginMs === 0 ? 'mlv-edge__charge' : 'mlv-edge__charge mlv-edge__charge--twin' });
  g.appendChild(svg('circle', { class: 'mlv-edge__charge-halo', cx: 0, cy: 0, r: FLOW.CHARGE_HALO_R }));
  g.appendChild(svg('circle', { class: 'mlv-edge__charge-glow', cx: 0, cy: 0, r: FLOW.CHARGE_GLOW_R }));
  g.appendChild(svg('circle', { class: 'mlv-edge__charge-core', cx: 0, cy: 0, r: FLOW.CHARGE_CORE_R }));
  const motion = svg('animateMotion', {
    dur: durMs + 'ms',
    repeatCount: 'indefinite',
    calcMode: 'linear',
    rotate: 'auto',
    fill: 'remove',
  });
  if (t0 !== null) motion.setAttribute('begin', round3(t0 + beginMs / 1000) + 's');
  else if (beginMs !== 0) motion.setAttribute('begin', beginMs + 'ms');
  const mpath = svg('mpath');
  // SVG 2 reads `href`; SVG 1.1 reads `xlink:href`, and only from the XLink
  // namespace — a plain setAttribute would land it in no namespace and be
  // ignored. Both are written so neither renderer has to guess.
  mpath.setAttribute('href', '#' + pathId);
  mpath.setAttributeNS(XLINK_NS, 'xlink:href', '#' + pathId);
  motion.appendChild(mpath);
  g.appendChild(motion);
  return g;
}

/** px along the route -> the `pathLength="100"` normalized space. */
function pathUnits(px: number, length: number): number {
  if (!(length > 0)) return 100;
  return round2(Math.min(100, (px / length) * 100));
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Milliseconds of precision on a seconds-valued SMIL time. */
function round3(n: number): number {
  return Math.round(n * 1000) / 1000;
}

function portCircle(end: 'in' | 'out', at: Point): SVGElement {
  return svg('circle', {
    class: 'mlv-edge__port mlv-edge__port--' + end,
    cx: round2(at.x),
    cy: round2(at.y),
    r: FLOW.PORT_R,
  });
}

/** The reduced-motion substitute: a chevron on the cable, aimed at the inlet. */
function directionMark(route: RoutedEdge): SVGElement {
  return svg('path', {
    class: 'mlv-edge__dir',
    d: 'M -3.4 -3.6 L 0 0 L -3.4 3.6',
    fill: 'none',
    transform: 'translate(' + round2(route.mid.x) + ',' + round2(route.mid.y) + ') rotate(' + round2(route.midAngle) + ')',
  });
}

function stripEdge(g: SVGElement): void {
  for (const cls of FLOW_CLASSES) g.classList.remove(cls);
  const style = (g as unknown as HTMLElement).style;
  if (style && typeof style.removeProperty === 'function') {
    for (const prop of FLOW_PROPS) style.removeProperty(prop);
  }
  const parts = g.querySelectorAll('.mlv-edge__flow, .mlv-edge__charge, .mlv-edge__port, .mlv-edge__dir');
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (part.parentNode) part.parentNode.removeChild(part);
  }
}
