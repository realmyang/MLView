/**
 * SVG edge layer. One <g> per routed edge: a wide transparent hit path, the
 * visible stroke, an optional label and an optional severity marker at the
 * midpoint. Arrowheads come from <marker> definitions in <defs>, one per kind.
 */

import { svg, setAttrs } from '../dom.js';
import { edgeMarker } from '../markers.js';
import {
  WEIGHT_BADGE_H,
  WEIGHT_MIN,
  weightBadgeAt,
  weightBadgeText,
  weightBadgeWidth,
  weightStroke,
} from '../rollup/rolled.js';
import { labelTextOf } from '../layout/labels.js';
import type { LabelPlacement } from '../layout/labels.js';
import type { RoutedEdge } from '../layout/routing.js';
import type { Severity } from '../types.js';

/**
 * The four contracted edge kinds. Exported because the legend (VIEW-10) is
 * GENERATED from this table and `buildDefs`'s arrowheads rather than
 * hand-written, so a key can never describe a stroke the renderer stopped
 * drawing.
 */
export const KNOWN_EDGE_KINDS = ['data', 'call', 'control', 'config'];

/**
 * One serial per MOUNTED view, handed out here because this is where the ids it
 * qualifies are written.
 *
 * The flow layer's charge rides its cable through a SMIL `<mpath href="#...">`,
 * which is a DOCUMENT-wide reference: `dev/states.html` mounts several apps on
 * one page, and the standalone report is embedded in pages that may hold more
 * than one, so an id built from the edge id alone would make two apps share a
 * motion path and run one app's charge along the other's cable.
 */
let mountSerial = 0;

export function nextMountSerial(): number {
  mountSerial++;
  return mountSerial;
}

/**
 * `mlv-p-<mount serial>-<edge id as hex>` — the id of an edge's VISIBLE path,
 * and the only thing `<mpath>` is allowed to point at (CONTRACTS 11.13.1).
 *
 * Each UTF-16 code unit becomes exactly four hex digits, so the mapping is
 * injective by construction (a fixed-width code cannot alias) and the result is
 * a bare `[0-9a-f]` token — always a valid id, a valid CSS identifier tail and a
 * valid URL fragment, whatever characters the analyzer put in the edge id.
 */
export function edgePathId(serial: number, edgeId: string): string {
  let hex = '';
  for (let i = 0; i < edgeId.length; i++) {
    const unit = edgeId.charCodeAt(i).toString(16);
    hex += '0000'.slice(unit.length) + unit;
  }
  return 'mlv-p-' + serial + '-' + hex;
}

export function edgeKindClass(kind: string): string {
  return KNOWN_EDGE_KINDS.indexOf(kind) >= 0 ? kind : 'unknown';
}

function marker(id: string, cls: string, d: string, filled: boolean): SVGElement {
  const m = svg('marker', {
    id,
    viewBox: '0 0 10 10',
    refX: 8.5,
    refY: 5,
    markerWidth: 9,
    markerHeight: 9,
    markerUnits: 'userSpaceOnUse',
    orient: 'auto',
  });
  const p = svg('path', { class: cls, d });
  if (!filled) setAttrs(p, { fill: 'none' });
  m.appendChild(p);
  return m;
}

/**
 * Arrowheads: filled triangle for data, open chevrons for call and control.
 *
 * One table, two consumers: `buildDefs()` turns it into the scene's <marker>
 * elements, and the legend (VIEW-10) draws the same paths inline — a <marker>
 * id may exist only once per document, so the key cannot reuse the scene's.
 */
export const ARROW_HEADS: Record<string, { d: string; filled: boolean }> = {
  data: { d: 'M0.5 1 L9 5 L0.5 9 Z', filled: true },
  unknown: { d: 'M0.5 1 L9 5 L0.5 9 Z', filled: true },
  call: { d: 'M1 1.2 L8.4 5 L1 8.8', filled: false },
  control: { d: 'M2 2 L7.6 5 L2 8', filled: false },
  config: { d: 'M2 2 L7.6 5 L2 8', filled: false },
};

export function buildDefs(): SVGElement {
  const defs = svg('defs');
  for (const kind of Object.keys(ARROW_HEADS)) {
    const head = ARROW_HEADS[kind];
    defs.appendChild(marker('mlv-arrow-' + kind, 'mlv-arrow mlv-arrow--' + kind, head.d, head.filled));
  }
  return defs;
}

export interface EdgeVisual {
  route: RoutedEdge;
  severity: Severity | null;
  suppressed: boolean;
  labelVisible: boolean;
  /**
   * The SOURCE node's stage, stamped on the <g> as `data-stage`. It makes
   * `--mlv-stage` resolve for free through the bare `[data-stage]` selector in
   * node.css, which is what colours the charge by lane (CONTRACTS 11.13 rule 4).
   */
  stage?: string;
  /** Endpoint labels, so the accessible name can say which way the value flows. */
  sourceLabel?: string;
  targetLabel?: string;
  /** The mounted view's serial, which makes this edge's path id unique. */
  mountSerial: number;
  /**
   * VIEW-03: where this edge's label goes, and where its severity marker goes
   * once nudged off the label box. Absent means "nobody planned one", and the
   * label falls back to the route midpoint it used before VIEW-03 — the dev
   * pages build edges without a frame, and a missing plan must not lose a label.
   */
  placement?: LabelPlacement;
  /**
   * VIEW-07: true when a stage filter dims one of the endpoints. The DOM adds
   * `.is-filtered`; the SVG export drops the same opacity inline, so the two
   * renderers dim the same cables.
   */
  filtered?: boolean;
  /**
   * PERF-04: how many DOCUMENT edges this cable stands for, summed by
   * `render/plan.ts` over the route's own merge and the analyzer's rollup
   * dedupe. Absent or 1 draws exactly what it always drew.
   */
  weight?: number;
}

export function buildEdge(v: EdgeVisual): SVGElement {
  const r = v.route;
  const kind = edgeKindClass(r.kind);
  const weight = v.weight && v.weight > 1 ? Math.floor(v.weight) : 1;
  const weighted = weight >= WEIGHT_MIN;
  const g = svg('g', {
    class:
      'mlv-edge mlv-edge--' + kind + (r.count > 1 ? ' mlv-edge--merged' : '') +
      (weighted ? ' mlv-edge--weighted' : '') + (r.back ? ' mlv-edge--back' : ''),
    'data-edge-id': r.id,
    'data-edge-kind': r.kind,
  });
  g.setAttribute('data-edge-ids', r.ids.join(' '));
  if (weighted) {
    // PERF-04. The thicker stroke is a CUSTOM PROPERTY on the group rather than
    // an inline `stroke-width` on the path: hover, selection and the severity
    // tint all set that property in CSS, and an inline style would win over all
    // three, so a heavy cable would stop responding to the pointer.
    g.setAttribute('data-edge-weight', String(weight));
    g.style.setProperty('--mlv-edge-w', weightStroke(weight) + 'px');
  }
  // NOTE: this now also matches the 45-300 SVG groups of the edge layer, not
  // only node cards — the bare [data-stage] rule in node.css is what binds
  // --mlv-stage, and the flow layer reads it as --mlv-flow-color.
  if (v.stage) g.setAttribute('data-stage', v.stage);
  if (v.severity) {
    g.setAttribute('data-sev', v.severity);
    g.classList.add('has-issue');
  }
  const hit = svg('path', { class: 'mlv-edge__hit', d: r.d });
  hit.setAttribute('tabindex', '-1');
  hit.setAttribute('role', 'button');
  hit.setAttribute('aria-label', edgeAria(r, v.sourceLabel, v.targetLabel, weight));
  g.appendChild(hit);

  const path = svg('path', { class: 'mlv-edge__path', d: r.d });
  path.setAttribute('marker-end', 'url(#mlv-arrow-' + kind + ')');
  // The charge's `<mpath>` rides THIS element, so it needs a document-unique id
  // (CONTRACTS 11.13.1). It is written for every edge, not only a flowing one:
  // the flow layer is built lazily inside a hover callback and must never have
  // to mutate the scene it is decorating.
  path.setAttribute('id', edgePathId(v.mountSerial, r.id));
  g.appendChild(path);

  const placement = v.placement;
  // VIEW-03. A label whose declutter pass ran out of positions is NOT drawn:
  // hiding it is the documented outcome, and the group says so rather than
  // leaving the reader to wonder which edge the missing name belonged to.
  if (r.label && placement && placement.hidden) {
    g.setAttribute('data-label-hidden', '1');
  } else if (r.label) {
    const x = placement ? placement.x : r.mid.x;
    const y = placement ? placement.y : r.mid.y - 8;
    const label = svg('text', { class: 'mlv-edge-label', x, y });
    // A control back-edge is the loop return path; the glyph says so at a glance.
    label.textContent = labelTextOf(r);
    if (placement) {
      label.setAttribute('data-label-axis', placement.axis);
      if (placement.flipped) label.setAttribute('data-label-flipped', '1');
      if (placement.laneId) label.setAttribute('data-label-lane', placement.laneId);
    }
    g.appendChild(label);
    if (v.labelVisible) g.classList.add('has-label');
  }

  // The severity marker rides the nudged point, so a glyph and a name never sit
  // centred on each other (VIEW-03).
  const mark = placement ? placement.marker : r.mid;
  if (v.severity) {
    const m = edgeMarker(v.severity, 14);
    m.setAttribute('transform', 'translate(' + mark.x + ',' + mark.y + ')');
    g.appendChild(m);
  } else if (r.back) {
    // A back-edge gets a small return chevron so the loop reads as a loop.
    const chev = svg('path', {
      class: 'mlv-edge__loopmark',
      d: 'M4 -4 L0 0 L4 4',
      fill: 'none',
      stroke: 'var(--mlv-edge)',
      'stroke-width': 1.3,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      transform: 'translate(' + mark.x + ',' + mark.y + ')',
    });
    g.appendChild(chev);
  }
  // PERF-04. The weight badge goes LAST, so it sits over the stroke it counts.
  // It is nudged along the route's own normal whenever the midpoint is already
  // occupied by a severity glyph or a loop chevron — a number drawn on top of a
  // severity marker is two facts and one readable glyph.
  if (weighted) g.appendChild(weightBadge(weight, mark, r.midAngle, !!v.severity || r.back));
  return g;
}

/**
 * `×7` in a pill on the cable. It is drawn as a real `<rect>` + `<text>` rather
 * than borrowed from the edge LABEL, because a label is decluttered away when
 * it collides (VIEW-03) and the number of connections a merged cable stands for
 * is not something the picture may quietly drop.
 *
 * Its geometry comes from `rollup/rolled.ts`, so the SVG export puts the same
 * pill in the same place (VIEW-07: the two renderers must not be able to
 * disagree about the picture).
 */
function weightBadge(weight: number, at: { x: number; y: number }, angle: number, occupied: boolean): SVGElement {
  const text = weightBadgeText(weight);
  const w = weightBadgeWidth(weight);
  const point = weightBadgeAt(at, angle, occupied);
  const g = svg('g', {
    class: 'mlv-edge__weight',
    transform: 'translate(' + round(point.x) + ',' + round(point.y) + ')',
  });
  g.setAttribute('data-weight', String(weight));
  g.appendChild(
    svg('rect', {
      class: 'mlv-edge__weightbg',
      x: -w / 2,
      y: -WEIGHT_BADGE_H / 2,
      width: w,
      height: WEIGHT_BADGE_H,
      rx: WEIGHT_BADGE_H / 2,
    }),
  );
  const label = svg('text', { class: 'mlv-edge__weighttext', x: 0, y: 0 });
  label.textContent = text;
  g.appendChild(label);
  const title = svg('title');
  title.textContent =
    weight + ' connections merged into this edge. It counts connections, not call sites: the rollup ' +
    're-pointed edges from folded children at the card that swallowed them.';
  g.appendChild(title);
  return g;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * The accessible name carries the DIRECTION in words — a connection was
 * unreachable and undescribed from the keyboard before this (FEATURES 2.2, 2.10).
 */
export function edgeAria(r: RoutedEdge, sourceLabel?: string, targetLabel?: string, weight = 1): string {
  const kind = r.back ? 'loop back edge' : r.kind + ' edge';
  const label = r.label ? ' labelled ' + r.label : '';
  const flows = sourceLabel && targetLabel ? ', flows from ' + sourceLabel + ' to ' + targetLabel : '';
  const merged = r.count > 1 ? ', ' + r.count + ' merged connections' : '';
  // PERF-04. `count` is what THIS renderer merged; `weight` is what the rollup
  // merged before the document was written, and it is the larger number. Saying
  // only the first would understate the cable to the one reader who cannot see
  // how thick it is.
  const weighted = weight > 1 ? ', weight ' + weight + ' — ' + weight + ' connections in one cable' : '';
  return kind + label + flows + merged + weighted + '. Activate to open the call site.';
}

/** The dotted numbered connectors drawn for a selected issue's relatedLocs. */
export function buildConnector(from: { x: number; y: number }, to: { x: number; y: number }, index: number, severity: Severity, label: string): SVGElement {
  const g = svg('g', { class: 'mlv-connector-group', 'data-sev': severity });
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2;
  const d = 'M ' + from.x + ' ' + from.y + ' Q ' + mx + ' ' + (my - 28) + ' ' + to.x + ' ' + to.y;
  g.appendChild(svg('path', { class: 'mlv-connector', d }));
  const badge = svg('circle', { class: 'mlv-connector__badge', cx: mx, cy: my - 14, r: 8 });
  g.appendChild(badge);
  const text = svg('text', { class: 'mlv-connector__label', x: mx, y: my - 14 });
  text.textContent = String(index);
  g.appendChild(text);
  const title = svg('title');
  title.textContent = label;
  g.appendChild(title);
  return g;
}
