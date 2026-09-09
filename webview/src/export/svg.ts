/**
 * The standalone SVG renderer (VIEW-07).
 *
 * It walks the SAME `ScenePlan` the DOM renderer walks — the same
 * `LayoutFrame` boxes, the same `RoutedEdge.d` strings verbatim, the same
 * VIEW-03 label placements — and emits real `<rect>` / `<text>` / `<path>`.
 * That is the item's mandatory mitigation: there is one decision about what is
 * drawn, so the gate can assert one `<g data-node-id>` per planned node and one
 * `<path data-edge-id>` per planned route and know the two renderers agree.
 *
 * Four hard rules, all gated by `test/export.test.mjs`:
 *
 *   1. **No external reference.** No `url(...)`, so no `<marker>`, no
 *      `clip-path`, no gradient and no filter; no `<image>`, no `xlink:href`,
 *      no `@import`, no webfont. The only `http` in the file is the SVG
 *      namespace declaration itself, which a standalone SVG cannot omit.
 *   2. **No `foreignObject`.** Text is `<text>`, which is fragile only in the
 *      sense that it needs a font stack the consumer has — hence rule 3.
 *   3. **A generic font stack.** `ui-sans-serif` / `ui-monospace` with the usual
 *      platform families behind them and `sans-serif` / `monospace` last.
 *   4. **Literal colours.** Every paint comes from `export/palette.ts`, which
 *      resolves the live `--mlv-*` tokens and falls back to the transcribed
 *      `styles/tokens.css` literals. `color-mix()` washes become `fill-opacity`,
 *      which is the same picture over the emitted background rectangle.
 *
 * Output is a STRING, built without touching the DOM, so it is identical in the
 * VS Code webview, the standalone report and a headless gate.
 */

import { SVG_NS, middleTruncate } from '../dom.js';
import { locParts } from '../notebook.js';
import { kindPath } from '../icons.js';
import { countsTotal, highestSeverity, normalizeSeverity } from '../markers.js';
import { ARROW_HEADS, edgeKindClass } from '../render/edges.js';
import { ariaLabelFor, chipsFor } from '../render/nodes.js';
import { stageColor, severityColor, Palette } from './palette.js';
import {
  ADVANCE_CAPS,
  EXPORT_MONO,
  EXPORT_SANS,
  badge,
  boundsOf,
  cluster,
  ellipsise,
  esc,
  glyphPath,
  intersects,
  normalizeRect,
  num,
  pad,
  severityGlyphMarkup,
  text,
  width,
} from './svgprim.js';

// Re-exported so every import site keeps naming ONE module for the export
// renderer: the split is an internal one between the pen and the picture.
export { EXPORT_MONO, EXPORT_SANS, esc, intersects, width } from './svgprim.js';
import type { ScenePlan } from '../render/plan.js';
import type { LayoutBox } from '../layout/layout.js';
import type { Point } from '../layout/routing.js';
import type { Rect } from '../render/canvas.js';
import type { IssueCounts, ThemeKind } from '../types.js';

/* ── the three offers (VIEW-07) ─────────────────────────────────────────── */

export type ExportRegionKind = 'view' | 'diagram' | 'scope';

export const EXPORT_REGIONS: { id: ExportRegionKind; label: string; hint: string }[] = [
  { id: 'view', label: 'Current view', hint: 'Exactly what is on screen right now.' },
  { id: 'diagram', label: 'Whole diagram', hint: 'Every lane and every card, at natural size.' },
  { id: 'scope', label: 'Current scope', hint: 'The scoped subject only — the shareable artifact.' },
];

/* ── geometry, transcribed from styles/node.css and styles/canvas.css ───── */

const CARD_R = 10;
const RAIL_W = 4;
const PAD_L = 8;
const PAD_R = 12;
const PAD_T = 10;
const ICON_BOX = 26;
const ICON_GAP = 8;
const TEXT_X = RAIL_W + PAD_L + ICON_BOX + ICON_GAP;

const FS_TITLE = 13;
const FS_SUB = 11;
const FS_LOC = 10.5;
const FS_CHIP = 10.5;
const FS_LANE = 11;
const FS_COUNT = 10.5;
const FS_GROUP = 12;
const FS_EDGE_LABEL = 10;

/** Baselines inside a card, measured off the flex box in `styles/node.css`. */
const Y_TITLE = 22.5;
const Y_SUB = 38.5;
const Y_LOC = 52.5;
const Y_CHIP = 66.5;
/** Below this height a card has no room for the attribute chip row. */
const CHIP_MIN_H = 72;

const LANE_R = 14;
const GROUP_R = 12;
const GROUP_HEADER_H = 34;

export interface ExportSvgOptions {
  plan: ScenePlan;
  palette: Palette;
  theme: ThemeKind;
  /** World-space rectangle to emit. Anything not intersecting it is dropped. */
  region: Rect;
  regionKind: ExportRegionKind;
  /** `<title>` — what a screen reader and a browser tab call the picture. */
  title: string;
  /** `<desc>` — provenance, so a pasted SVG still says where it came from. */
  desc?: string;
}

export interface ExportSvgResult {
  svg: string;
  width: number;
  height: number;
  region: Rect;
  regionKind: ExportRegionKind;
  /** Node ids that got a `<g data-node-id>`, in emission order. */
  nodeIds: string[];
  /** Route ids that got a `<path data-edge-id>`, in emission order. */
  edgeIds: string[];
  /** Every DOCUMENT edge id those routes carry — routes merge parallel edges. */
  edgeDocIds: string[];
  /** Lane ids that got a band. */
  laneIds: string[];
  /** Edge labels actually drawn (a decluttered-away label is not one). */
  labels: number;
  /** Stage colours that appear in the file, for the gate's "stage colours" check. */
  stageColors: string[];
}

/* ── the renderer ───────────────────────────────────────────────────────── */

export function buildExportSvg(opts: ExportSvgOptions): ExportSvgResult {
  const { plan, palette, theme } = opts;
  const hc = theme === 'hc';
  const region = normalizeRect(opts.region);
  const parts: string[] = [];
  const nodeIds: string[] = [];
  const edgeIds: string[] = [];
  const edgeDocIds: string[] = [];
  const laneIds: string[] = [];
  const stageColors: string[] = [];
  let labels = 0;

  const noteStage = (colour: string) => {
    if (stageColors.indexOf(colour) < 0) stageColors.push(colour);
  };

  /* background — an exported picture must carry its own paper */
  parts.push(
    '<rect data-layer="background" x="' + num(region.x) + '" y="' + num(region.y) +
      '" width="' + num(region.w) + '" height="' + num(region.h) + '" fill="' + esc(palette.bg) + '"/>',
  );

  /* lanes, then the dashed frames of expanded groups — the backdrop layer */
  const backdrop: string[] = [];
  for (const laneVisual of plan.lanes) {
    const lane = laneVisual.lane;
    const rect: Rect = { x: lane.x, y: lane.y, w: lane.w, h: lane.h };
    if (!intersects(rect, region)) continue;
    laneIds.push(lane.id);
    const colour = stageColor(palette, lane.id);
    noteStage(colour);
    backdrop.push(laneBand(lane, laneVisual.counts, colour, palette, hc));
  }

  const cards: string[] = [];
  for (const planned of plan.nodes) {
    const box = planned.visual.box;
    const rect: Rect = { x: box.x - 8, y: box.y - 8, w: box.w + 16, h: box.h + 16 };
    if (!intersects(rect, region)) continue;
    nodeIds.push(planned.visual.node.id);
    const colour = stageColor(palette, planned.visual.node.stage);
    noteStage(colour);
    const markup = planned.expandedGroup
      ? groupFrame(planned.visual, colour, palette, hc)
      : nodeCard(planned.visual, colour, palette, hc);
    if (planned.expandedGroup) backdrop.push(markup);
    else cards.push(markup);
  }

  /* edges sit above the bands and under the cards, exactly as the DOM stacks */
  const cables: string[] = [];
  for (const visual of plan.edges) {
    const route = visual.route;
    if (!intersects(pad(boundsOf(route.points), 16), region)) continue;
    edgeIds.push(route.id);
    for (const id of route.ids) edgeDocIds.push(id);
    const drawn = edgeMarkup(visual, palette, hc);
    cables.push(drawn.markup);
    if (drawn.labelled) labels++;
  }

  parts.push('<g data-layer="lanes">' + backdrop.join('') + '</g>');
  parts.push('<g data-layer="edges">' + cables.join('') + '</g>');
  parts.push('<g data-layer="nodes">' + cards.join('') + '</g>');

  const head =
    '<svg xmlns="' + SVG_NS + '" width="' + num(region.w) + '" height="' + num(region.h) +
    '" viewBox="' + num(region.x) + ' ' + num(region.y) + ' ' + num(region.w) + ' ' + num(region.h) +
    '" font-family="' + esc(EXPORT_SANS) + '" data-mlview-export="' + esc(opts.regionKind) +
    '" data-mlview-theme="' + esc(theme) + '">';
  const meta =
    '<title>' + esc(opts.title) + '</title>' + (opts.desc ? '<desc>' + esc(opts.desc) + '</desc>' : '');

  return {
    svg: '<?xml version="1.0" encoding="UTF-8"?>\n' + head + meta + parts.join('') + '</svg>\n',
    width: region.w,
    height: region.h,
    region,
    regionKind: opts.regionKind,
    nodeIds,
    edgeIds,
    edgeDocIds,
    laneIds,
    labels,
    stageColors,
  };
}

/* ── lanes ──────────────────────────────────────────────────────────────── */

function laneBand(
  lane: { id: string; label: string; x: number; y: number; w: number; h: number; headerH: number; nodeCount: number },
  counts: IssueCounts,
  colour: string,
  palette: Palette,
  hc: boolean,
): string {
  const out: string[] = ['<g data-lane-id="' + esc(lane.id) + '" data-stage="' + esc(lane.id) + '">'];
  out.push(
    '<rect x="' + num(lane.x) + '" y="' + num(lane.y) + '" width="' + num(lane.w) + '" height="' + num(lane.h) +
      '" rx="' + LANE_R + '" fill="' + esc(colour) + '" fill-opacity="' + num(palette.laneTint) +
      '" stroke="' + esc(palette.border) + '" stroke-width="1"/>',
  );
  const swatchY = lane.y + (lane.headerH - 8) / 2;
  out.push(
    '<rect x="' + num(lane.x + 12) + '" y="' + num(swatchY) + '" width="8" height="8" rx="2" fill="' + esc(colour) + '"/>',
  );
  const labelText = (lane.label || lane.id).toUpperCase();
  const labelX = lane.x + 26;
  const baseline = lane.y + lane.headerH / 2 + 4;
  out.push(
    text(labelText, labelX, baseline, {
      size: FS_LANE,
      fill: palette.text2,
      weight: 650,
      letterSpacing: 0.44,
    }),
  );
  const countX = labelX + labelText.length * (FS_LANE * ADVANCE_CAPS + 0.44) + 10;
  out.push(
    text(lane.nodeCount + (lane.nodeCount === 1 ? ' node' : ' nodes'), countX, baseline, {
      size: FS_COUNT,
      fill: palette.text3,
    }),
  );
  const total = countsTotal(counts);
  if (total > 0) {
    out.push(cluster(counts, lane.x + lane.w - 12, lane.y + lane.headerH / 2, 13, palette, hc));
  }
  out.push('</g>');
  return out.join('');
}

/* ── nodes ──────────────────────────────────────────────────────────────── */

function nodeCard(
  visual: { node: any; box: LayoutBox; counts: IssueCounts; descendants: number; stale: boolean; filteredOut: boolean },
  colour: string,
  palette: Palette,
  hc: boolean,
): string {
  const n = visual.node;
  const box = visual.box;
  const collapsedGroup = box.collapsed;
  const boundary = n.viewRole === 'boundary';
  const top = boundary ? null : highestSeverity(visual.counts);
  const ghost = !!n.ghost;
  const lowConf = typeof n.confidence === 'number' && n.confidence < 0.6;
  const dashed = ghost || lowConf || visual.stale;

  const attrs =
    ' data-node-id="' + esc(n.id) + '" data-stage="' + esc(n.stage || 'unknown') +
    '" data-kind="' + esc(n.kind) + '"' + (top ? ' data-sev="' + esc(top) + '"' : '') +
    (n.viewRole ? ' data-view-role="' + esc(n.viewRole) + '"' : '') +
    (visual.filteredOut ? ' opacity="0.18"' : ghost ? ' opacity="0.92"' : '');
  const out: string[] = ['<g' + attrs + '>'];
  out.push('<title>' + esc(ariaLabelFor(visual as any)) + '</title>');

  const stroke = top ? severityColor(palette, top) : ghost ? severityColor(palette, top) : palette.border;
  out.push(
    '<rect x="' + num(box.x) + '" y="' + num(box.y) + '" width="' + num(box.w) + '" height="' + num(box.h) +
      '" rx="' + CARD_R + '" fill="' + (ghost ? 'none' : esc(palette.surface)) + '" stroke="' + esc(stroke) +
      '" stroke-width="' + (ghost ? 1.5 : 1) + '"' + (top ? ' stroke-opacity="0.75"' : '') +
      (dashed ? ' stroke-dasharray="5 4"' : '') + '/>',
  );
  if (!ghost) {
    out.push(
      '<rect x="' + num(box.x + 0.5) + '" y="' + num(box.y + 1) + '" width="' + RAIL_W +
        '" height="' + num(box.h - 2) + '" rx="2" fill="' + esc(colour) + '"/>',
    );
  }

  /* icon tile + kind glyph */
  const iconX = box.x + RAIL_W + PAD_L;
  const iconY = box.y + PAD_T;
  out.push(
    '<rect x="' + num(iconX) + '" y="' + num(iconY) + '" width="' + ICON_BOX + '" height="' + ICON_BOX +
      '" rx="6" fill="' + esc(colour) + '" fill-opacity="0.12"/>',
  );
  out.push(glyphPath(kindPath(collapsedGroup ? 'artifact' : n.kind), iconX + 5, iconY + 5, 16 / 16, colour, 1.3));

  /* text block */
  const tx = box.x + TEXT_X;
  const tw = Math.max(24, box.w - TEXT_X - PAD_R);
  const title = ellipsise(middleTruncate(n.label || n.qualname || n.id, 34), tw, FS_TITLE, false, true);
  out.push(text(title, tx, box.y + Y_TITLE, { size: FS_TITLE, fill: ghost ? palette.text2 : palette.text, weight: 650 }));
  const subRaw = n.sublabel || (n.fqn ? n.fqn : n.kind);
  const sub = ellipsise(middleTruncate(subRaw, 40), tw, FS_SUB, false, false);
  out.push(
    text(sub, tx, box.y + Y_SUB, { size: FS_SUB, fill: palette.text2, italic: ghost }),
  );
  // NB. The cell reference (or, on a `.py` path, the line number) is reserved
  // out of the budget first, so a path too long for the card loses the
  // directory rather than the answer — the DOM card does the same in CSS.
  const locBits = locParts(n.loc);
  const tailPx = width(locBits.tail, FS_LOC, true, false);
  const loc = ellipsise(locBits.head, Math.max(12, tw - tailPx), FS_LOC, true, false) + locBits.tail;
  out.push(text(loc, tx, box.y + Y_LOC, { size: FS_LOC, fill: palette.text3, mono: true }));

  const chips = collapsedGroup
    ? [visual.descendants + ' nodes'].concat(chipsFor(n, null, 14, 1))
    : chipsFor(n, chipMetrics(tw), 26, 3);
  if (chips.length && box.h >= CHIP_MIN_H) {
    let cx = tx;
    for (const chip of chips) {
      const cw = width(chip, FS_CHIP, false, false) + 12;
      if (cx + cw > tx + tw) break;
      out.push(
        '<rect x="' + num(cx) + '" y="' + num(box.y + Y_CHIP - 11) + '" width="' + num(cw) + '" height="15" rx="4" fill="' +
          esc(palette.surface2) + '" stroke="' + esc(palette.border) + '" stroke-width="0.75"/>',
      );
      out.push(text(chip, cx + 6, box.y + Y_CHIP, { size: FS_CHIP, fill: palette.text2 }));
      cx += cw + 4;
    }
  }

  if (top && !collapsedGroup) out.push(badge(visual.counts, box.x + box.w + 6, box.y - 6, palette, hc));
  else if (collapsedGroup && countsTotal(visual.counts) > 0) {
    out.push(cluster(visual.counts, box.x + box.w + 6, box.y + 4, 14, palette, hc));
  }
  out.push('</g>');
  return out.join('');
}

function groupFrame(
  visual: { node: any; box: LayoutBox; counts: IssueCounts; descendants: number },
  colour: string,
  palette: Palette,
  hc: boolean,
): string {
  const n = visual.node;
  const box = visual.box;
  const boundary = n.viewRole === 'boundary';
  const top = boundary ? null : highestSeverity(visual.counts);
  const out: string[] = [
    '<g data-node-id="' + esc(n.id) + '" data-group="1" data-stage="' + esc(n.stage || 'unknown') + '"' +
      (top ? ' data-sev="' + esc(top) + '"' : '') + '>',
  ];
  out.push('<title>' + esc(ariaLabelFor(visual as any)) + '</title>');
  out.push(
    '<rect x="' + num(box.x) + '" y="' + num(box.y) + '" width="' + num(box.w) + '" height="' + num(box.h) +
      '" rx="' + GROUP_R + '" fill="' + esc(colour) + '" fill-opacity="' + num(palette.groupTint) +
      '" stroke="' + esc(colour) + '" stroke-opacity="0.45" stroke-width="1" stroke-dasharray="' +
      (box.depth >= 2 ? '1 3' : '5 4') + '"/>',
  );
  const iconY = box.y + (GROUP_HEADER_H - 14) / 2;
  out.push(glyphPath(kindPath(n.kind), box.x + 8, iconY, 14 / 16, colour, 1.3));
  const nameX = box.x + 28;
  const baseline = box.y + GROUP_HEADER_H / 2 + 4;
  // The count pill needs ~40 px and a severity cluster up to ~90 more, so the
  // name's budget shrinks when there is one — measured against the flagship,
  // where `for images, labels in …` sat under its own "❗2 ⚠2".
  const nameBudget = Math.max(40, box.w - (top ? 170 : 96));
  const name = ellipsise(middleTruncate(n.label || n.qualname, 42), nameBudget, FS_GROUP, false, true);
  out.push(text(name, nameX, baseline, { size: FS_GROUP, fill: palette.text, weight: 650 }));
  const countText = String(visual.descendants);
  const countW = width(countText, FS_COUNT, false, false) + 12;
  const countX = nameX + width(name, FS_GROUP, false, true) + 8;
  out.push(
    '<rect x="' + num(countX) + '" y="' + num(baseline - 11) + '" width="' + num(countW) +
      '" height="15" rx="7.5" fill="' + esc(palette.surface2) + '"/>',
  );
  out.push(text(countText, countX + 6, baseline, { size: FS_COUNT, fill: palette.text2 }));
  if (top) out.push(cluster(visual.counts, box.x + box.w - 10, box.y + GROUP_HEADER_H / 2, 13, palette, hc));
  out.push('</g>');
  return out.join('');
}

/* ── edges ──────────────────────────────────────────────────────────────── */

function edgeMarkup(
  visual: {
    route: { id: string; ids: string[]; kind: string; d: string; points: Point[]; mid: Point; back: boolean; count: number; label: string };
    severity: string | null;
    placement?: { x: number; y: number; hidden: boolean; always: boolean; text: string; marker: Point } | undefined;
    filtered?: boolean;
    stage?: string;
  },
  palette: Palette,
  hc: boolean,
): { markup: string; labelled: boolean } {
  const r = visual.route;
  const kind = edgeKindClass(r.kind);
  const colour = visual.severity ? severityColor(palette, visual.severity) : palette.edge;
  const style = EDGE_STYLE[kind] || EDGE_STYLE.data;
  const out: string[] = [
    '<g data-edge-kind="' + esc(r.kind) + '"' + (visual.filtered ? ' opacity="0.18"' : '') + '>',
  ];
  out.push(
    '<path data-edge-id="' + esc(r.id) + '" data-edge-ids="' + esc(r.ids.join(' ')) +
      '" d="' + esc(r.d) + '" fill="none" stroke="' + esc(colour) + '" stroke-width="' + style.width +
      '" stroke-linecap="round" stroke-linejoin="round"' +
      (style.dash ? ' stroke-dasharray="' + style.dash + '"' : '') +
      ' stroke-opacity="' + (visual.severity ? 0.85 : style.opacity) + '"/>',
  );
  if (style.arrow) out.push(arrowHead(r.points, kind, colour));

  let labelled = false;
  const placement = visual.placement;
  // Exactly the labels the DOM paints without a pointer on it: VIEW-03's
  // declutter pass only guarantees a clear position for THOSE (a hover-only
  // label takes the first candidate and may overlap), and `styles/edge.css`
  // only reveals data, control, back and merged labels at full LOD. Drawing the
  // rest would put text in the export that the diagram never shows.
  const visible = !placement || (!placement.hidden && placement.always);
  if (r.label && visible) {
    const lx = placement ? placement.x : r.mid.x;
    const ly = placement ? placement.y : r.mid.y - 8;
    const label = placement ? placement.text : r.label;
    out.push(
      '<text x="' + num(lx) + '" y="' + num(ly) + '" font-family="' + esc(EXPORT_MONO) + '" font-size="' + FS_EDGE_LABEL +
        '" fill="' + esc(palette.text2) + '" text-anchor="middle" dominant-baseline="middle" paint-order="stroke" stroke="' +
        esc(palette.bg) + '" stroke-width="3" stroke-linejoin="round">' + esc(label) + '</text>',
    );
    labelled = true;
  }

  const mark = placement ? placement.marker : r.mid;
  if (visual.severity) {
    const sev = normalizeSeverity(visual.severity);
    out.push(
      '<circle cx="' + num(mark.x) + '" cy="' + num(mark.y) + '" r="8.5" fill="' + esc(palette.surface) +
        '" stroke="' + esc(severityColor(palette, sev)) + '" stroke-width="1"/>',
    );
    out.push(severityGlyphMarkup(sev, mark.x - 7, mark.y - 7, 14, palette, hc));
  } else if (r.back) {
    out.push(
      '<path d="M ' + num(mark.x + 4) + ' ' + num(mark.y - 4) + ' L ' + num(mark.x) + ' ' + num(mark.y) +
        ' L ' + num(mark.x + 4) + ' ' + num(mark.y + 4) + '" fill="none" stroke="' + esc(palette.edge) +
        '" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>',
    );
  }
  out.push('</g>');
  return { markup: out.join(''), labelled };
}

/** Stroke treatments, transcribed from `styles/edge.css` one kind at a time. */
const EDGE_STYLE: Record<string, { width: number; dash: string; opacity: number; arrow: boolean }> = {
  data: { width: 1.5, dash: '', opacity: 1, arrow: true },
  call: { width: 1.5, dash: '4 3', opacity: 0.75, arrow: true },
  control: { width: 1.5, dash: '1 4', opacity: 0.65, arrow: true },
  config: { width: 1, dash: '2 4', opacity: 0.5, arrow: false },
  unknown: { width: 1.5, dash: '3 3', opacity: 0.6, arrow: true },
};

/**
 * The arrowhead the DOM gets from a `<marker>`, drawn inline instead.
 *
 * `render/edges.ts` declares its markers `markerUnits="userSpaceOnUse"` with
 * `markerWidth/Height 9` over a `0 0 10 10` viewBox — a 0.9 scale — anchored at
 * `refX 8.5, refY 5`. Reproducing that transform here is what lets the export
 * keep its no-`url(` promise without changing the picture.
 */
function arrowHead(points: Point[], kind: string, colour: string): string {
  const head = ARROW_HEADS[kind] || ARROW_HEADS.data;
  if (points.length < 2) return '';
  const end = points[points.length - 1];
  let prev = points[points.length - 2];
  for (let i = points.length - 2; i >= 0; i--) {
    if (points[i].x !== end.x || points[i].y !== end.y) {
      prev = points[i];
      break;
    }
  }
  const angle = (Math.atan2(end.y - prev.y, end.x - prev.x) * 180) / Math.PI;
  const transform =
    'translate(' + num(end.x) + ',' + num(end.y) + ') rotate(' + num(angle) + ') translate(-7.65,-4.5) scale(0.9)';
  const paint = head.filled
    ? 'fill="' + esc(colour) + '"'
    : 'fill="none" stroke="' + esc(colour) + '" stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round"';
  return '<path class="mlv-edge__arrow" d="' + esc(head.d) + '" transform="' + transform + '" ' + paint + '/>';
}

/** The chip budget, in the SVG's own metric — the same `chipsFor` the DOM uses. */
function chipMetrics(available: number) {
  return {
    width: available,
    measure(value: string): number {
      return width(value, FS_CHIP, false, false);
    },
  };
}
