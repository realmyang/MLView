/**
 * Test and reference-page support. Exposed on window.MLView.__internal so that
 * webview/test/*.test.mjs and dev/states.html can drive the SAME code the app
 * uses, rather than a parallel copy that could drift.
 *
 * This is a debug surface, not part of the frozen renderer API in CONTRACTS
 * section 8 — hosts must not depend on it.
 */

import { GraphIndex } from './layout/model.js';
import { layoutGraph } from './layout/layout.js';
import { LANE_MIN_W, LANE_PAD, MAX_RANK_H, MAX_RANK_W, RANK_ROW_GAP } from './layout/constants.js';
import { routeEdges } from './layout/routing.js';
import { alwaysVisible, labelTextOf, labelWidth, planLabels, LABEL_METRICS } from './layout/labels.js';
import { buildNodeCard } from './render/nodes.js';
import { severityGlyph, SEVERITY_SHAPE, emptyCounts } from './markers.js';
import { KNOWN_KINDS } from './icons.js';
import { MIN_FIT_ZOOM, MIN_ZOOM, TALL_SCREENS, fitPlan, minimapFit, minimapFromWorld, minimapToWorld } from './render/canvas.js';
import { KEYMAP } from './ui/keymap.js';
import { tooltipPlacement } from './render/tooltip.js';
import { searchGraph, searchGraphDetailed } from './search.js';
import { locationHit, parseLocationQuery, pathMatches } from './searchloc.js';
import { normalizeWheel, panDelta, wheelIntent, wheelZoomFactor, COARSE_PX, LINE_PX, PINCH_GAIN, ZOOM_BASE } from './ui/gestures.js';
import { groupIssues, occurrenceText, sanitizeGroupBy } from './ui/railgroup.js';
import { disableSnippet, ignoreComment, suppressedSummary } from './ui/suppress.js';
import { ruleDocFor, setRuleDocs } from './ui/ruledocs.js';
import { legendModel } from './ui/legend.js';
import { FLOW, lineageHops, polylineLength, pulseDurationMs, streamGapPx } from './render/flow.js';
import { nearestRoute, routeDistance } from './render/edgepick.js';
import { cappedTraceMessage } from './render/flowbinding.js';
import { formatScope, parseScope, scopeLabel } from './scope/selector.js';
import { project, resolveScope } from './scope/project.js';
import { concernRows, scopeCatalog, stageRows } from './scope/catalog.js';
import { motionMode } from './motion.js';
import { deepLinkPlan } from './bridges.js';
import { edgePathId } from './render/edges.js';
import { planScene } from './render/plan.js';
import { EXPORT_PALETTES, PALETTE_TOKENS, TINT_TOKENS, paletteFor } from './export/palette.js';
import { EXPORT_MONO, EXPORT_REGIONS, EXPORT_SANS, ExportRegionKind, ExportSvgResult } from './export/svg.js';
import { PNG_SCALE, exportFileName, regionRect, renderExport } from './export/actions.js';
import { EXPORT_ACTIONS } from './ui/exportmenu.js';
import {
  cellRef,
  derated,
  isNotebookPath,
  locLabel,
  locSpoken,
  locTitle,
  outOfOrderDiagnostics,
  outOfOrderFiles,
  outOfOrderHeadline,
  OUT_OF_ORDER_KINDS,
} from './notebook.js';
import type { Rect } from './render/canvas.js';
import type { IssueCounts, MLGraph, MLNode, Severity, ThemeKind } from './types.js';

export interface PlainLayout {
  lanes: { id: string; label: string; x: number; y: number; w: number; h: number; headerH: number }[];
  nodes: {
    id: string;
    parent: string | null;
    x: number;
    y: number;
    w: number;
    h: number;
    lane: string;
    depth: number;
    isGroup: boolean;
    collapsed: boolean;
  }[];
  edges: {
    id: string;
    ids: string[];
    kind: string;
    back: boolean;
    crossLane: boolean;
    count: number;
    points: { x: number; y: number }[];
    d: string;
  }[];
  width: number;
  height: number;
}

/** Run the full layout + routing pass with no DOM involved. */
export function layoutForTest(graph: MLGraph, collapsed?: string[]): PlainLayout {
  const index = new GraphIndex(graph);
  const set = new Set(collapsed || []);
  const frame = layoutGraph(index, set);
  const routes = routeEdges(index, frame, set);
  return {
    lanes: frame.lanes.map((l) => ({ id: l.id, label: l.label, x: l.x, y: l.y, w: l.w, h: l.h, headerH: l.headerH })),
    nodes: Array.from(frame.boxes.values()).map((b) => ({
      id: b.id,
      parent: index.parentOf.get(b.id) || null,
      x: b.x,
      y: b.y,
      w: b.w,
      h: b.h,
      lane: b.laneId,
      depth: b.depth,
      isGroup: b.isGroup,
      collapsed: b.collapsed,
    })),
    edges: routes.map((r) => ({
      id: r.id,
      ids: r.ids.slice(),
      kind: r.kind,
      back: r.back,
      crossLane: r.crossLane,
      count: r.count,
      points: r.points.map((p) => ({ x: p.x, y: p.y })),
      d: r.d,
    })),
    width: frame.width,
    height: frame.height,
  };
}

export interface PlainLabel {
  id: string;
  text: string;
  x: number;
  y: number;
  rect: { x: number; y: number; w: number; h: number };
  hidden: boolean;
  flipped: boolean;
  fallback: boolean;
  axis: string;
  laneId: string | null;
  always: boolean;
  marker: { x: number; y: number };
}

export interface PlainLabelPlan {
  labels: PlainLabel[];
  stats: Record<string, number>;
  /** Wall-clock cost of each pass, so a gate can state the relayout budget. */
  ms: { layout: number; route: number; labels: number };
}

/**
 * VIEW-03's placement pass with no DOM at all, plus the three timings.
 *
 * The gate re-derives every overlap itself from `layoutForTest`'s boxes and
 * these rectangles, so the assertion is arithmetic the test owns rather than a
 * self-report from the code under test.
 */
export function labelsForTest(graph: MLGraph, collapsed?: string[]): PlainLabelPlan {
  const clock = typeof performance !== 'undefined' && performance.now ? () => performance.now() : () => Date.now();
  const index = new GraphIndex(graph);
  const set = new Set(collapsed || []);
  const t0 = clock();
  const frame = layoutGraph(index, set);
  const t1 = clock();
  const routes = routeEdges(index, frame, set);
  const t2 = clock();
  const plan = planLabels(frame, routes);
  const t3 = clock();
  const labels: PlainLabel[] = [];
  for (const route of routes) {
    const placement = plan.placements.get(route.id);
    if (!placement) continue;
    labels.push({
      id: placement.id,
      text: placement.text,
      x: placement.x,
      y: placement.y,
      rect: { x: placement.rect.x, y: placement.rect.y, w: placement.rect.w, h: placement.rect.h },
      hidden: placement.hidden,
      flipped: placement.flipped,
      fallback: placement.fallback,
      axis: placement.axis,
      laneId: placement.laneId,
      always: placement.always,
      marker: { x: placement.marker.x, y: placement.marker.y },
    });
  }
  return {
    labels,
    stats: { ...plan.stats },
    ms: { layout: t1 - t0, route: t2 - t1, labels: t3 - t2 },
  };
}

export interface ExportTestOptions {
  collapsed?: string[];
  theme?: ThemeKind;
  region?: ExportRegionKind;
  /** The visible canvas in world coordinates; only the `view` region reads it. */
  viewRect?: Rect;
  scopeLabel?: string | null;
}

/**
 * VIEW-07's SVG export with no DOM at all (the same reasoning as `labelsForTest`).
 *
 * It runs the REAL pipeline — `layoutGraph` → `routeEdges` → `planLabels` →
 * `planScene` → `renderExport` — so the gate that counts `<g data-node-id>` and
 * `<path data-edge-id>` is counting the shipped renderer's output, not a
 * test-only imitation of it.
 */
export function exportForTest(graph: MLGraph, opts?: ExportTestOptions): ExportSvgResult {
  const options = opts || {};
  const index = new GraphIndex(graph);
  const collapsed = new Set(options.collapsed || []);
  const frame = layoutGraph(index, collapsed);
  const routes = routeEdges(index, frame, collapsed);
  const labelPlan = planLabels(frame, routes);
  const plan = planScene({
    index,
    frame,
    routes,
    labels: labelPlan.placements,
    mountSerial: 1,
    keep: () => true,
    staleFiles: [],
    isFilteredOut: () => false,
  });
  const theme: ThemeKind = options.theme || 'light';
  return renderExport({
    plan,
    palette: paletteFor(theme),
    theme,
    graph,
    regionKind: options.region || 'diagram',
    viewRect: options.viewRect || { x: 0, y: 0, w: frame.width, h: frame.height },
    scopeLabel: options.scopeLabel === undefined ? null : options.scopeLabel,
    generatedAt: '2026-09-09',
  });
}

export interface DemoCardOptions {
  kind: string;
  stage?: string;
  state?: 'default' | 'hover' | 'selected' | 'dimmed' | 'ghost' | 'stale';
  severity?: Severity | null;
  label?: string;
  sublabel?: string;
}

const STATE_CLASS: Record<string, string> = {
  default: '',
  hover: 'is-hover-demo',
  selected: 'is-selected',
  dimmed: 'is-dimmed-demo',
  ghost: 'is-ghost',
  stale: 'is-stale',
};

/** One node card in one state — the atom dev/states.html tiles. */
export function buildDemoCard(opts: DemoCardOptions): HTMLElement {
  const state = opts.state || 'default';
  const stage = opts.stage || 'model';
  const counts: IssueCounts = emptyCounts();
  if (opts.severity) counts[opts.severity] = 1;
  const node: MLNode = {
    id: 'n:demo' + opts.kind + state,
    kind: opts.kind,
    level: 'op',
    stage,
    label: opts.label || opts.kind,
    sublabel: opts.sublabel || (state === 'ghost' ? 'missing' : opts.kind + ' node'),
    qualname: 'demo.' + opts.kind,
    loc: { file: 'demo.py', absFile: '/demo/demo.py', line: 12, col: 0, endLine: 12, endCol: 8 },
    parent: null,
    attrs: { lr: '1e-3' },
    produces: [],
    consumes: [],
    ghost: state === 'ghost',
    dynamic: false,
    confidence: 0.9,
    confidenceBucket: 'certain',
    issueIds: [],
    collapsedByDefault: false,
    stageEvidence: [],
  };
  const card = buildNodeCard(
    {
      node,
      box: { id: node.id, x: 0, y: 0, w: 216, h: 72, laneId: stage, depth: 0, isGroup: false, collapsed: false, headerH: 0 },
      counts,
      descendants: 0,
      stale: state === 'stale',
      filteredOut: false,
    },
    false,
  );
  card.style.position = 'relative';
  card.style.left = '0';
  card.style.top = '0';
  const extra = STATE_CLASS[state];
  if (extra) card.classList.add(extra);
  if (state === 'dimmed') {
    card.style.opacity = '0.22';
    card.style.filter = 'saturate(0.3)';
  }
  if (state === 'hover') {
    card.style.boxShadow = 'var(--mlv-sh-2)';
    card.style.transform = 'translateY(-1px)';
  }
  return card;
}

export const internals = {
  layout: layoutForTest,
  /**
   * The parity gate calls `scope.project` with no DOM at all, so the TypeScript
   * port is checked against `contracts/scope.expected.json` directly
   * (CONTRACTS 11.8, 11.15).
   */
  scope: {
    parseScope,
    formatScope,
    scopeLabel,
    resolveScope,
    project,
    catalog: scopeCatalog,
    concerns: concernRows,
    stages: stageRows,
  },
  /** Timings live here so no test hard-codes one (CONTRACTS 11.13). */
  flow: {
    FLOW,
    polylineLength,
    pulseDurationMs,
    streamGapPx,
    lineageHops,
    motionMode,
    /** Which cable owns a point — geometry, never `elementFromPoint`. */
    nearestRoute,
    routeDistance,
    cappedTraceMessage,
    /** The charge's motion-path id, so a test never hard-codes the format. */
    edgePathId,
  },
  /**
   * The standalone deep-link decision table (CONTRACTS 11.17), exposed because
   * the environment it protects against — a cross-origin sandboxed iframe —
   * cannot be built inside a unit test, but its two inputs can.
   */
  deepLinkPlan,
  keymap: KEYMAP,
  minimap: { fit: minimapFit, toWorld: minimapToWorld, fromWorld: minimapFromWorld },
  /**
   * VIEW-01: the first-paint zoom decision as a pure function, plus the two
   * constants that bound it, so a gate states the rule rather than a number.
   */
  viewport: { fitPlan, MIN_ZOOM, TALL_SCREENS, MIN_FIT_ZOOM },
  /** VIEW-01: the lane wrap budget, for the width gates. */
  layoutConstants: { MAX_RANK_W, MAX_RANK_H, LANE_MIN_W, LANE_PAD, RANK_ROW_GAP },
  /** VIEW-03: label placement, its metrics and which labels are always drawn. */
  labels: { plan: labelsForTest, metrics: LABEL_METRICS, textOf: labelTextOf, widthOf: labelWidth, alwaysVisible },
  /**
   * VIEW-07: the SVG export, its palette table and the menu's own contents, so
   * a gate states the renderer's output rather than a transcription of it.
   */
  exportDiagram: {
    build: exportForTest,
    palettes: EXPORT_PALETTES,
    paletteTokens: PALETTE_TOKENS,
    tintTokens: TINT_TOKENS,
    regions: EXPORT_REGIONS,
    actions: EXPORT_ACTIONS,
    fonts: { sans: EXPORT_SANS, mono: EXPORT_MONO },
    regionRect,
    fileName: exportFileName,
    pngScale: PNG_SCALE,
  },
  /** MLV-P10: the two strings the rail, the Inspector and the bridge all use. */
  suppression: { ignoreComment, disableSnippet, suppressedSummary },
  tooltipPlacement,
  searchGraph,
  /** VIEW-09ab: the detailed result and the `path:line` resolver behind it. */
  search: {
    detailed: searchGraphDetailed,
    parseLocation: parseLocationQuery,
    locationHit,
    pathMatches,
  },
  /**
   * VIEW-06: wheel normalization and its branch, so a test states the device
   * mode rather than a magic number (the same reasoning as `flow` above).
   */
  gestures: {
    normalizeWheel,
    wheelIntent,
    wheelZoomFactor,
    panDelta,
    LINE_PX,
    COARSE_PX,
    PINCH_GAIN,
    ZOOM_BASE,
  },
  /** RAIL-GROUP, MLV-P6 and VIEW-10: the data behind three rendered surfaces. */
  rail: { groupIssues, occurrenceText, sanitizeGroupBy },
  ruleDocs: { ruleDocFor, setRuleDocs },
  /**
   * NB: the one translation from a flat line into `name.ipynb > cell 3 : 4`,
   * and the execution-order caveat's wording. Exposed so a gate states the rule
   * rather than transcribing a string built somewhere else.
   */
  notebook: {
    cellRef,
    locLabel,
    locSpoken,
    locTitle,
    isNotebookPath,
    outOfOrder: outOfOrderDiagnostics,
    outOfOrderFiles,
    derated,
    headline: outOfOrderHeadline,
    KINDS: OUT_OF_ORDER_KINDS,
  },
  legendModel,
  buildDemoCard,
  severityGlyph,
  severityShapes: SEVERITY_SHAPE,
  nodeKinds: KNOWN_KINDS,
  GraphIndex,
};
