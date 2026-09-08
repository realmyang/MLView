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
import { routeEdges } from './layout/routing.js';
import { buildNodeCard } from './render/nodes.js';
import { severityGlyph, SEVERITY_SHAPE, emptyCounts } from './markers.js';
import { KNOWN_KINDS } from './icons.js';
import { minimapFit, minimapFromWorld, minimapToWorld } from './render/canvas.js';
import { KEYMAP } from './ui/keymap.js';
import { tooltipPlacement } from './render/tooltip.js';
import { searchGraph, searchGraphDetailed } from './search.js';
import { locationHit, parseLocationQuery, pathMatches } from './searchloc.js';
import { normalizeWheel, panDelta, wheelIntent, wheelZoomFactor, COARSE_PX, LINE_PX, PINCH_GAIN, ZOOM_BASE } from './ui/gestures.js';
import { groupIssues, occurrenceText, sanitizeGroupBy } from './ui/railgroup.js';
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
import type { IssueCounts, MLGraph, MLNode, Severity } from './types.js';

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
  legendModel,
  buildDemoCard,
  severityGlyph,
  severityShapes: SEVERITY_SHAPE,
  nodeKinds: KNOWN_KINDS,
  GraphIndex,
};
