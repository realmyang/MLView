#!/usr/bin/env node
// Layout metrics: a dev tool that measures the canvas layout of the built viewer. No layout number
// is a gate.
//
//   node tools/layout-metrics.mjs                       # every sample diagram and four synthetic documents, tables
//   node tools/layout-metrics.mjs --dev                 # + the eight test documents
//   node tools/layout-metrics.mjs <document>.mlview.json --no-repo --json
//   node tools/layout-metrics.mjs --baseline            # what moved since layout-metrics.baseline.json
//   node tools/layout-metrics.mjs --write-baseline      # re-record it (repo-held documents only)
//   node tools/layout-metrics.mjs --help
//
// Each document is mounted in the BUILT bundle (dist/mlview.js) in jsdom, as the tests mount it, and
// its laid-out frame, routes, label plan and trunk bundles are read back from the scene plan (the
// plan both renderers draw). Layout does no DOM text measurement, so jsdom gives the browser's
// geometry (test/geometry-golden.test.mjs rests on the same fact). The measures are pure functions
// of that scene, so a prototype can feed `measureLayout` a scene of its own.
//
// Nothing here is imported by src/, so none of it is in the bundle or the VSIX (only
// vscode-extension/ is packaged, with media/ copied from dist/).
// test/layout-metrics.test.mjs checks that the tool runs, reports its keys and counts what each
// measure says on hand-made scenes, and that the command measures every repo-held document; it
// pins no measured value of the viewer's layout.
//
// Every number is a geometric proxy on boxes and polylines (crossings, overlaps, label ownership,
// camera travel, whole cards in view). The walk is a replay of the viewer's camera policy as a pure
// function, not the viewer. It does not follow the viewer on a connection whose two steps do not
// fit the view together: the replay moves to the rectangle around both steps, where the viewer
// shows the start of the connection or, for a dashed or dotted line, may zoom out to show both.

import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';
import { DIST_JS, REPO_ROOT, WEBVIEW_ROOT, recordingBridge, rendererRegressionWorkflow, shapedWorkflow, SHAPE_79_CLAIMS, SHAPE_176_CLAIMS } from '../test/helpers.mjs';
import { benchmarkWorkflow } from './benchmark-model.mjs';

/** Written into every JSON output, so a stray copy says where it came from. */
export const TOOL_ID = 'mlview-layout-metrics';
export const BASELINE_FILE = join(WEBVIEW_ROOT, 'tools', 'layout-metrics.baseline.json');

/* ── constants copied from the viewer (src/render/canvas.ts; keep them in step) ───────────── */

export const READABLE_ZOOM = 0.9;
export const READABLE_MIN_ZOOM = 0.75;
export const LOD_FULL_ZOOM = 0.62;
export const FRAME_MIN_ZOOM = 0.45;
export const FRAME_MAX_ZOOM = 1;
export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 2.5;
export const MAX_FIT_ZOOM = 1.2;

/**
 * The canvas the viewer gets per panel, measured in a browser:
 * `first` is the canvas at first paint (the bottom sheet collapsed below a 1260 px panel, the rail
 * docked at 360 px from 1260 px), `walk` the canvas while the review walk runs (the walk bar shown
 * and, below 1260 px, the bottom sheet open), and `covered` the phase index over the walk canvas
 * (its pill below a 1000 px panel, its panel of rows above; the width follows the longest phase
 * label, measured on a 4-phase document). 541 x 798 is a panel beside the code, 900 x 800
 * the screenshot harness's narrow panel and 1440 x 900 its default. A change to the chrome's
 * heights changes these; re-measure them before trusting a walk number after such a change.
 */
export const PANELS = {
  '541': { panel: { w: 541, h: 798 }, first: { w: 541, h: 708 }, walk: { w: 541, h: 363 }, covered: { x: 288, y: 323, w: 241, h: 28 } },
  '900': { panel: { w: 900, h: 800 }, first: { w: 900, h: 710 }, walk: { w: 900, h: 323 }, covered: { x: 647, y: 283, w: 241, h: 28 } },
  '1440': { panel: { w: 1440, h: 900 }, first: { w: 1080, h: 842 }, walk: { w: 1080, h: 793 }, covered: { x: 708, y: 649, w: 360, h: 132 } },
};
export const WIDTHS = Object.keys(PANELS);

/* ── small geometry ──────────────────────────────────────────────────────────────────────── */

const EPS = 1e-6;
const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
const round = (v, k = 100) => Math.round(v * k) / k;
const sum = (xs) => xs.reduce((a, b) => a + b, 0);
const mean = (xs) => (xs.length ? sum(xs) / xs.length : 0);
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
export function quantile(xs, q) {
  if (!xs.length) return 0;
  const s = xs.slice().sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}
const cx = (r) => r.x + r.w / 2;
const cy = (r) => r.y + r.h / 2;
const unionRect = (rects) => {
  const x = Math.min(...rects.map((r) => r.x));
  const y = Math.min(...rects.map((r) => r.y));
  return { x, y, w: Math.max(...rects.map((r) => r.x + r.w)) - x, h: Math.max(...rects.map((r) => r.y + r.h)) - y };
};
const rectsOverlap = (a, b, pad = 0) => a.x - pad < b.x + b.w && a.x + a.w + pad > b.x && a.y - pad < b.y + b.h && a.y + a.h + pad > b.y;
const pick = (r) => ({ x: r.x, y: r.y, w: r.w, h: r.h });

/** Drop repeated points and merge collinear runs, so a bend is a real change of direction. */
export function simplify(points) {
  const out = [];
  for (const p of points) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - p.x) < 0.01 && Math.abs(prev.y - p.y) < 0.01) continue;
    out.push({ x: p.x, y: p.y });
  }
  for (let i = out.length - 2; i >= 1; i--) {
    const a = out[i - 1], b = out[i], c = out[i + 1];
    const cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    const dot = (b.x - a.x) * (c.x - b.x) + (b.y - a.y) * (c.y - b.y);
    if (Math.abs(cross) < 0.01 * Math.max(1, dist(a, b) * dist(b, c)) && dot > 0) out.splice(i, 1);
  }
  return out;
}

export function polyLength(points) {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += dist(points[i - 1], points[i]);
  return total;
}

function segmentsOf(points, keepEmpty = false) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    if (!keepEmpty && dist(a, b) < 0.01) continue;
    out.push({ a, b, x0: Math.min(a.x, b.x), x1: Math.max(a.x, b.x), y0: Math.min(a.y, b.y), y1: Math.max(a.y, b.y) });
  }
  return out;
}

/** Proper intersection point of two segments, or null (collinear overlaps return null). */
function intersect(s, t) {
  const r = { x: s.b.x - s.a.x, y: s.b.y - s.a.y };
  const q = { x: t.b.x - t.a.x, y: t.b.y - t.a.y };
  const den = r.x * q.y - r.y * q.x;
  if (Math.abs(den) < EPS) return null;
  const u = ((t.a.x - s.a.x) * q.y - (t.a.y - s.a.y) * q.x) / den;
  const v = ((t.a.x - s.a.x) * r.y - (t.a.y - s.a.y) * r.x) / den;
  if (u < -EPS || u > 1 + EPS || v < -EPS || v > 1 + EPS) return null;
  return { x: s.a.x + u * r.x, y: s.a.y + u * r.y };
}

function pointSegDist(p, s) {
  const dx = s.b.x - s.a.x, dy = s.b.y - s.a.y;
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((p.x - s.a.x) * dx + (p.y - s.a.y) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (s.a.x + t * dx), p.y - (s.a.y + t * dy));
}

/** Does a segment pass through a rectangle's interior (inset by `m`)? */
function segHitsRect(s, r, m = 1) {
  const x0 = r.x + m, x1 = r.x + r.w - m, y0 = r.y + m, y1 = r.y + r.h - m;
  if (x1 <= x0 || y1 <= y0) return false;
  if (s.x1 <= x0 || s.x0 >= x1 || s.y1 <= y0 || s.y0 >= y1) return false;
  // Axis-aligned segments: the bounding test above is exact. Otherwise clip (Liang-Barsky).
  if (s.a.x === s.b.x || s.a.y === s.b.y) return true;
  let t0 = 0, t1 = 1;
  const dx = s.b.x - s.a.x, dy = s.b.y - s.a.y;
  for (const [p, q] of [[-dx, s.a.x - x0], [dx, x1 - s.a.x], [-dy, s.a.y - y0], [dy, y1 - s.a.y]]) {
    if (Math.abs(p) < EPS) { if (q < 0) return false; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
  }
  return t1 - t0 > EPS;
}

/** Points every `step` px along a polyline, with the unit direction there. */
function samples(points, step = 2) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const len = dist(a, b);
    if (len < 0.01) continue;
    const ux = (b.x - a.x) / len, uy = (b.y - a.y) / len;
    const n = Math.max(1, Math.round(len / step));
    for (let k = 0; k < n; k++) {
      const t = (k + 0.5) / n;
      out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, ux, uy, w: len / n });
    }
  }
  return out;
}

/** A uniform grid of segments for near-neighbour queries. */
class SegGrid {
  constructor(cell = 64) { this.cell = cell; this.cells = new Map(); }
  add(seg, owner) {
    const c = this.cell, pad = 6;
    for (let gx = Math.floor((seg.x0 - pad) / c); gx <= Math.floor((seg.x1 + pad) / c); gx++)
      for (let gy = Math.floor((seg.y0 - pad) / c); gy <= Math.floor((seg.y1 + pad) / c); gy++) {
        const k = gx + ':' + gy;
        const list = this.cells.get(k);
        const item = { seg, owner };
        if (list) list.push(item); else this.cells.set(k, [item]);
      }
  }
  near(p) {
    return this.cells.get(Math.floor(p.x / this.cell) + ':' + Math.floor(p.y / this.cell)) || [];
  }
}

/** Shortest distance between a rectangle and a polyline, sampled every 2 px (0: they touch). */
function distRectPoly(r, points) {
  let d = Infinity;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const n = Math.max(1, Math.ceil(dist(a, b) / 2));
    for (let k = 0; k <= n; k++) {
      const p = { x: a.x + ((b.x - a.x) * k) / n, y: a.y + ((b.y - a.y) * k) / n };
      const dx = Math.max(r.x - p.x, 0, p.x - (r.x + r.w)), dy = Math.max(r.y - p.y, 0, p.y - (r.y + r.h));
      d = Math.min(d, Math.hypot(dx, dy));
      if (d === 0) return 0;
    }
  }
  return d;
}

/* ── the layout metrics ──────────────────────────────────────────────────────────────────── */

/**
 * Measure one laid-out scene (world px, origin at the frame's top-left):
 *
 *   {
 *     name, width, height,               // the frame ("fit the whole" fits it)
 *     channelW,                          // optional: the left routing channel's width
 *     lanes: [{ id, x, y, w, h }],       // optional: phase bands, in phase order
 *     nodes: [{ id, x, y, w, h,          // every DRAWN box
 *               group,                   // true for an expanded group's frame (drawn behind its children)
 *               parent,                  // the drawn container's id, or null
 *               lane }],
 *     edges: [{ id, source, target,      // drawn box ids (a collapsed group stands for its children)
 *               points: [{ x, y }],      // the drawn polyline; flatten curves to chords of 4 px or less
 *               basis,                   // 'observed' | 'inferred' | 'unresolved' (a merged cable: the least certain)
 *               docIds,                  // the document connections the cable stands for (default [id])
 *               label, labelRect, labelHidden, labelAlways }],
 *     overlays: [{ id, kind: 'trunk' | 'spur', bundle, member, points }],
 *                                        // strokes drawn at rest that are not cables (member: the cable a spur is drawn for)
 *     restHidden: ['edge-id'],           // bundle members: their own stroke is transparent at rest when observed
 *     repOf: { hiddenId: 'drawnGroupId' },  // steps folded into a collapsed group
 *     walkOrder: [{ kind, id }],         // optional: the walk's claim order, read from the viewer
 *   }
 *
 * Options: `flow` decides what "backward" means: 'lanes-then-x' (the default with lanes: phase bands
 * top to bottom, left to right inside a band), 'x' (left to right) or 'y' (top to bottom); `nearPx`
 * is the distance at which two parallel strokes read as one (default 4 world px), `collinearPx` the
 * distance at which they are drawn on each other (default 1 px).
 */
export function measureLayout(scene, opts = {}) {
  const nearPx = opts.nearPx ?? 4;
  const collinearPx = opts.collinearPx ?? 1;
  const flow = opts.flow || (scene.lanes && scene.lanes.length ? 'lanes-then-x' : 'x');
  const nodes = scene.nodes || [];
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const cards = nodes.filter((n) => !n.group);
  const groups = nodes.filter((n) => n.group);
  const lanes = scene.lanes || [];
  const laneIndex = new Map(lanes.map((l, i) => [l.id, i]));
  const W = scene.width, H = scene.height;
  const frameArea = Math.max(1, W * H);

  // Ancestors (drawn containers) of each node, for "an edge may run inside its own group".
  const ancestors = (id) => {
    const out = new Set();
    let cur = nodeById.get(id)?.parent || null;
    let hops = 0;
    while (cur && hops++ < 64) { out.add(cur); cur = nodeById.get(cur)?.parent || null; }
    return out;
  };

  const edges = (scene.edges || []).map((e) => {
    const points = simplify(e.points || []);
    return { ...e, raw: e.points || [], points, segs: segmentsOf(points), length: polyLength(points), bends: Math.max(0, points.length - 2), docIds: e.docIds || [e.id] };
  });
  const restHidden = new Set(scene.restHidden || []);
  const overlays = (scene.overlays || []).map((o) => {
    const points = simplify(o.points || []);
    return { ...o, raw: o.points || [], points, segs: segmentsOf(points), length: polyLength(points) };
  });
  const uncertainBasis = (e) => e.basis === 'inferred' || e.basis === 'unresolved';

  /* size and space */
  const cardArea = sum(cards.map((n) => n.w * n.h));
  const laneArea = sum(lanes.map((l) => l.w * l.h));
  const bbox = cards.length ? unionRect(cards) : { x: 0, y: 0, w: 0, h: 0 };
  const size = {
    width: round(W), height: round(H), aspect: round(W / Math.max(1, H), 1000), area: Math.round(frameArea),
    // Cards (leaf cards and collapsed groups) as a share of the frame; laneEmptyShare is the empty
    // part inside the phase bands, outsideLaneShare the frame no band covers (gutters, the left
    // channel, and the space right of bands narrower than the widest).
    cardShare: round(cardArea / frameArea, 1000),
    laneShare: lanes.length ? round(laneArea / frameArea, 1000) : null,
    laneEmptyShare: lanes.length ? round(1 - cardArea / Math.max(1, laneArea), 1000) : null,
    outsideLaneShare: lanes.length ? round(1 - laneArea / frameArea, 1000) : null,
    cardBBox: { w: round(bbox.w), h: round(bbox.h) },
  };

  /* edges: bends and length */
  const lengths = edges.map((e) => e.length);
  const bends = edges.map((e) => e.bends);
  let longest = null;
  for (const e of edges) if (!longest || e.length > longest.length) longest = e;
  // Excess: drawn length minus the Manhattan gap between the two boxes (0 = as short as an
  // orthogonal connection between those boxes can be).
  const excess = edges.filter((e) => e.source !== e.target).map((e) => {
    const s = nodeById.get(e.source), t = nodeById.get(e.target);
    if (!s || !t) return null;
    const gx = Math.max(0, Math.max(s.x, t.x) - Math.min(s.x + s.w, t.x + t.w));
    const gy = Math.max(0, Math.max(s.y, t.y) - Math.min(s.y + s.h, t.y + t.h));
    return Math.max(0, e.length - (gx + gy));
  }).filter((v) => v !== null);
  const edgeStats = {
    cables: edges.length,
    documentEdges: sum(edges.map((e) => e.docIds.length)),
    bendsMean: round(mean(bends)), bendsMax: bends.length ? Math.max(...bends) : 0,
    lengthMean: Math.round(mean(lengths)), lengthP90: Math.round(quantile(lengths, 0.9)),
    lengthMax: longest ? Math.round(longest.length) : 0, longestId: longest ? longest.id : null,
    excessMean: Math.round(mean(excess)), excessP90: Math.round(quantile(excess, 0.9)),
  };

  /* crossings */
  const endpointsOf = (e) => [e.points[0], e.points[e.points.length - 1]].filter(Boolean);
  const nearEnd = (p, e) => endpointsOf(e).some((q) => dist(p, q) <= 1.5);
  function countCrossings(strokes) {
    let n = 0;
    const per = new Map(strokes.map((s) => [s.id, 0]));
    for (let i = 0; i < strokes.length; i++) {
      for (let j = i + 1; j < strokes.length; j++) {
        const A = strokes[i], B = strokes[j];
        if (A.group && A.group === B.group) continue; // pieces of one drawn object
        for (const s of A.segs) for (const t of B.segs) {
          if (s.x1 < t.x0 - EPS || t.x1 < s.x0 - EPS || s.y1 < t.y0 - EPS || t.y1 < s.y0 - EPS) continue;
          const p = intersect(s, t);
          if (!p) continue;
          if (nearEnd(p, A) || nearEnd(p, B)) continue; // touching at a shared port is not a crossing
          // A bend that lies on the other stroke is where two strokes merge or part (an orthogonal
          // router's shared run), not a crossing: count only points inside both segments.
          if (Math.min(dist(p, s.a), dist(p, s.b), dist(p, t.a), dist(p, t.b)) < 0.5) continue;
          n++;
          per.set(A.id, per.get(A.id) + 1);
          per.set(B.id, per.get(B.id) + 1);
        }
      }
    }
    return { n, per };
  }
  const cableStrokes = edges.map((e) => ({ id: e.id, segs: e.segs, points: e.points }));
  const cablesX = countCrossings(cableStrokes);
  // At rest: the cables a bundle does not hide (its inferred and unresolved members keep their own
  // dashed or dotted stroke, drawn above the trunk), plus trunks and spurs, one object per bundle.
  const restStrokes = edges.filter((e) => !restHidden.has(e.id) || (e.basis && e.basis !== 'observed'))
    .map((e) => ({ id: e.id, edge: e, segs: e.segs, points: e.points, raw: e.raw }))
    .concat(overlays.map((o) => ({ id: o.id, group: o.bundle || o.id, member: o.member, segs: o.segs, points: o.points, raw: o.raw })));
  const restX = countCrossings(restStrokes);
  const crossings = {
    cables: cablesX.n,
    perCable: round(cablesX.n / Math.max(1, edges.length)),
    atRest: restX.n,
    cablesCrossed: [...cablesX.per.values()].filter((v) => v > 0).length,
  };

  /* overlaps: parallel strokes drawn on, or nearly on, each other */
  function overlapShares(subjects, others, tol) {
    // For each subject stroke: the share of its length within `tol` px of another stroke that runs
    // parallel to it there (|cos| > 0.96), sampled every 2 px. A stroke drawn FOR the subject (its
    // own bundle spur, `member`) is the same connection.
    const grid = new SegGrid(64);
    for (const o of others) for (const seg of o.segs) grid.add(seg, o.member || o.id);
    const out = new Map();
    for (const s of subjects) {
      let covered = 0, total = 0;
      for (const p of samples(s.points, 2)) {
        total += p.w;
        let hit = false;
        for (const { seg, owner } of grid.near(p)) {
          if (owner === s.id) continue;
          const len = dist(seg.a, seg.b);
          const ux = (seg.b.x - seg.a.x) / len, uy = (seg.b.y - seg.a.y) / len;
          if (Math.abs(ux * p.ux + uy * p.uy) < 0.96) continue;
          if (pointSegDist(p, seg) <= tol) { hit = true; break; }
        }
        if (hit) covered += p.w;
      }
      out.set(s.id, total ? covered / total : 0);
    }
    return out;
  }
  const collinear = overlapShares(cableStrokes, cableStrokes, collinearPx);
  const near = overlapShares(cableStrokes, cableStrokes, nearPx);
  const lenOf = new Map(edges.map((e) => [e.id, e.length]));
  const overlapLen = (m) => Math.round(sum([...m.entries()].map(([id, share]) => share * (lenOf.get(id) || 0))));
  const overlaps = {
    // Cable length lying on another cable (<= collinearPx) or beside one (<= nearPx), as a share of
    // all cable length, and how many cables have half or more of their length so.
    collinearShare: round(overlapLen(collinear) / Math.max(1, sum(lengths)), 1000),
    nearShare: round(overlapLen(near) / Math.max(1, sum(lengths)), 1000),
    cablesHalfCollinear: [...collinear.values()].filter((v) => v >= 0.5).length,
    // The overlap split: the share lying on (within 1 px, same axis) a cable that shares neither its
    // source nor its target. A run shared with a cable from the same source or to the same target
    // carries one meaning; a run shared with an unrelated cable is where a reader loses the trace.
    unrelatedShare: unrelatedOverlap(edges),
  };

  /* edges through cards */
  let throughCards = 0;
  const throughEdges = new Set();
  let throughGroups = 0;
  for (const e of edges) {
    const own = new Set([e.source, e.target, ...ancestors(e.source), ...ancestors(e.target)]);
    for (const n of nodes) {
      if (own.has(n.id)) continue;
      // An edge may run inside a group that contains an endpoint; a group frame it merely passes
      // through is counted apart (it crosses the frame, not a card).
      const anc = ancestors(n.id);
      if (anc.has(e.source) || anc.has(e.target)) continue;
      if (!e.segs.some((s) => segHitsRect(s, n))) continue;
      if (n.group) throughGroups++;
      else { throughCards++; throughEdges.add(e.id); }
    }
  }

  /* labels */
  const labelled = edges.filter((e) => e.label || e.labelRect || e.labelHidden);
  const placed = labelled.filter((e) => e.labelRect && !e.labelHidden && e.labelRect.w > 0);
  const always = labelled.filter((e) => e.labelAlways);
  // Overlaps are counted for the labels drawn at rest (labelAlways): a hover-only label appears
  // alone under the pointer, so its overlaps are with nothing the reader sees at the same time.
  const shown = placed.filter((e) => e.labelAlways);
  let labelOnCard = 0, labelOnLabel = 0, labelOnOtherEdge = 0;
  for (let i = 0; i < shown.length; i++) {
    const r = shown[i].labelRect;
    if (cards.some((n) => rectsOverlap(r, n, -0.5))) labelOnCard++;
    for (let j = i + 1; j < shown.length; j++) if (rectsOverlap(r, shown[j].labelRect, -0.5)) labelOnLabel++;
    if (edges.some((e) => e.id !== shown[i].id && e.segs.some((s) => segHitsRect(s, r, 0.5)))) labelOnOtherEdge++;
  }
  const labels = {
    withText: labelled.length,
    alwaysOn: always.length,
    alwaysHidden: always.filter((e) => e.labelHidden).length,
    alwaysPlaced: shown.length,
    // Labels drawn at rest overlapping a card, another such label, or ANY other cable's stroke
    // (shared endpoints included, whether or not a bundle hides that stroke).
    onCard: labelOnCard, onLabel: labelOnLabel, onOtherCable: labelOnOtherEdge,
    ...labelOwnership(edges, restStrokes),
  };

  /* reading direction */
  let netLeft = 0, netUp = 0, backward = 0, upLane = 0, counted = 0, sameLane = 0, sameLaneLeft = 0;
  for (const e of edges) {
    const s = nodeById.get(e.source), t = nodeById.get(e.target);
    if (!s || !t || e.source === e.target) continue;
    counted++;
    const dx = cx(t) - cx(s), dy = cy(t) - cy(s);
    if (dx < -1) netLeft++;
    if (dy < -1) netUp++;
    const sl = laneIndex.get(s.lane), tl = laneIndex.get(t.lane);
    if (sl !== undefined && tl !== undefined && sl === tl) { sameLane++; if (dx < -1) sameLaneLeft++; }
    if (flow === 'lanes-then-x' && sl !== undefined && tl !== undefined) {
      if (tl < sl) upLane++;
      if (tl < sl || (tl === sl && dx < -1)) backward++;
    } else if (flow === 'y') { if (dy < -1) backward++; } else if (dx < -1) backward++;
  }
  const direction = {
    flow,
    counted,
    // Target box centre left of / above the source box centre.
    netLeftShare: round(netLeft / Math.max(1, counted), 1000),
    netUpShare: round(netUp / Math.max(1, counted), 1000),
    // Against the reading order of `flow` (lanes-then-x: an earlier band, or the same band and to the left).
    backwardShare: round(backward / Math.max(1, counted), 1000),
    // Into an earlier phase band: fixed by the document, no lanes layout can make these forward.
    toEarlierLaneShare: lanes.length ? round(upLane / Math.max(1, counted), 1000) : null,
    sameLaneLeftShare: lanes.length ? round(sameLaneLeft / Math.max(1, sameLane), 1000) : null,
  };

  /* uncertain connections: how visible are they at rest? */
  const uncertainEdges = edges.filter(uncertainBasis);
  const subjects = uncertainEdges.map((e) => ({ id: e.id, points: e.points, segs: e.segs }));
  const restNear = overlapShares(subjects, restStrokes, nearPx);
  const restOn = overlapShares(subjects, restStrokes, collinearPx);
  const onOverlay = overlapShares(subjects, overlays.filter((o) => o.kind === 'trunk'), nearPx);
  const uncertainList = uncertainEdges.map((e) => {
    const own = new Set([e.source, e.target, ...ancestors(e.source), ...ancestors(e.target)]);
    let underCards = 0, total = 0;
    for (const p of samples(e.points, 2)) {
      total += p.w;
      if (cards.some((n) => !own.has(n.id) && p.x > n.x + 1 && p.x < n.x + n.w - 1 && p.y > n.y + 1 && p.y < n.y + n.h - 1)) underCards += p.w;
    }
    return {
      id: e.id, basis: e.basis, length: Math.round(e.length), docIds: e.docIds,
      // Within nearPx of another stroke drawn at rest (a cable, a trunk or a spur, its own spur
      // excepted), of a trunk stroke alone, and under a card it does not belong to.
      overlapShare: round(restNear.get(e.id) || 0, 1000),
      // Within collinearPx of such a stroke: drawn on it, where the dash pattern is lost entirely.
      onStrokeShare: round(restOn.get(e.id) || 0, 1000),
      onTrunkShare: round(onOverlay.get(e.id) || 0, 1000),
      underCardShare: round(total ? underCards / total : 0, 1000),
      crossings: cablesX.per.get(e.id) || 0,
      labelHidden: !!e.labelHidden,
      // A member of a trunk bundle (`is-bundled` in the viewer), whatever its stroke looks like.
      inTrunk: restHidden.has(e.id),
    };
  });
  const uncertain = {
    cables: uncertainList.length,
    documentEdges: sum(uncertainList.map((u) => u.docIds.length)),
    // "Half hidden": half or more of the dashed or dotted stroke lies within nearPx of another
    // stroke drawn at rest or under a card, so its dash pattern is lost there.
    hiddenHalf: uncertainList.filter((u) => u.overlapShare + u.underCardShare >= 0.5).length,
    hiddenQuarter: uncertainList.filter((u) => u.overlapShare + u.underCardShare >= 0.25).length,
    // "Drawn on": more than 8 px of the stroke within collinearPx of another stroke drawn at rest
    // (a few px where cables meet at a shared port aside).
    drawnOn: uncertainList.filter((u) => u.onStrokeShare * u.length > 8).length,
    // Drawn inside a trunk bundle, and with more than 5% of the stroke along a trunk's stroke. The
    // two sets differ: a cable can be half hidden beside solid cables without being in a trunk.
    inTrunk: uncertainList.filter((u) => u.inTrunk).length,
    onTrunk: uncertainList.filter((u) => u.onTrunkShare > 0.05).length,
    labelHidden: uncertainList.filter((u) => u.labelHidden).length,
    list: uncertainList,
  };

  return {
    name: scene.name || null,
    size, edges: edgeStats, crossings, overlaps,
    throughCards: { hits: throughCards, cables: throughEdges.size, groupFrameHits: throughGroups },
    labels, direction, uncertain,
    counts: { cards: cards.length, groups: groups.length, lanes: lanes.length, overlays: overlays.length },
  };
}

/**
 * The overlap split. Every cable's polyline, as drawn, is sampled every 2 px; a sample counts when
 * it lies within 1 px of a segment of another cable on the same axis (horizontal, or not) whose
 * cable shares neither the source nor the target. Returns that length as a share of all cable length.
 */
export function unrelatedOverlap(edges) {
  const items = edges.map((e) => ({ e, segs: segmentsOf(e.raw || e.points || [], true) }));
  const grid = new SegGrid(64);
  items.forEach((item, k) => { for (const seg of item.segs) grid.add(seg, k); });
  let total = 0, unrelated = 0;
  items.forEach(({ e, segs }, k) => {
    for (const { a, b } of segs) {
      const len = dist(a, b);
      if (len < 0.01) continue;
      const n = Math.max(1, Math.round(len / 2));
      const horizontal = Math.abs(a.y - b.y) < 0.01;
      for (let i = 0; i < n; i++) {
        const t = (i + 0.5) / n, x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t, w = len / n;
        total += w;
        for (const { seg, owner } of grid.near({ x, y })) {
          if (owner === k) continue;
          const f = items[owner].e;
          if (f.source === e.source || f.target === e.target) continue;
          const c = seg.a, d = seg.b;
          if ((Math.abs(c.y - d.y) < 0.01) !== horizontal) continue;
          const on = horizontal
            ? Math.abs(c.y - y) <= 1 && x >= seg.x0 - 0.01 && x <= seg.x1 + 0.01
            : Math.abs(c.x - x) <= 1 && y >= seg.y0 - 0.01 && y <= seg.y1 + 0.01;
          if (on) { unrelated += w; break; }
        }
      }
    }
  });
  return round(unrelated / Math.max(1, total), 1000);
}

/**
 * Label ownership, over the labels drawn at rest (always-on and
 * placed), against the strokes drawn at rest except the label's own cable, its own spurs, and cables
 * from the same source or to the same target (nearby, they carry the same meaning):
 *   crossedByUnrelated: such a stroke touches the label's rectangle;
 *   nearerOther: such a stroke is more than 2 px nearer the label than its own cable (misattribution risk);
 *   floating: the label is more than 16 px from its own cable.
 * A trunk is never exempt, even the one its own cable belongs to.
 */
export function labelOwnership(edges, restStrokes) {
  let atRest = 0, crossed = 0, nearerOther = 0, floating = 0;
  for (const e of edges) {
    if (!e.labelAlways || e.labelHidden || !e.labelRect) continue;
    atRest++;
    const r = e.labelRect;
    const own = distRectPoly(r, e.raw || e.points);
    let other = Infinity;
    for (const s of restStrokes) {
      if (s.id === e.id || s.member === e.id) continue;
      if (s.edge && (s.edge.source === e.source || s.edge.target === e.target)) continue;
      other = Math.min(other, distRectPoly(r, s.raw || s.points));
      if (other === 0) break;
    }
    if (other === 0) crossed++;
    if (other + 2 < own) nearerOther++;
    if (own > 16) floating++;
  }
  return { atRest, crossedByUnrelated: crossed, nearerOther, floating };
}

/**
 * Connections whose route and both end cards fit the walk canvas (32 px margin) at `zoom`: at 0.45
 * the frame's floor, at 0.9 the reading zoom. All cables, and the inferred or unresolved ones.
 */
export function framing(scene, canvas, zoom) {
  const box = new Map((scene.nodes || []).map((n) => [n.id, n]));
  let cables = 0, fit = 0, uncertain = 0, uncertainFit = 0;
  for (const e of scene.edges || []) {
    const ends = [box.get(e.source), box.get(e.target)].filter(Boolean).flatMap((b) => [{ x: b.x, y: b.y }, { x: b.x + b.w, y: b.y + b.h }]);
    const ps = (e.points || []).concat(ends);
    if (!ps.length) continue;
    const xs = ps.map((p) => p.x), ys = ps.map((p) => p.y);
    const ok = (Math.max(...xs) - Math.min(...xs)) * zoom <= canvas.w - 32 && (Math.max(...ys) - Math.min(...ys)) * zoom <= canvas.h - 32;
    cables++;
    if (ok) fit++;
    if (e.basis && e.basis !== 'observed') { uncertain++; if (ok) uncertainFit++; }
  }
  return { zoom, cables, fit, uncertain, uncertainFit };
}

/* ── the first view (render/canvas.ts readablePlan) ───────────────────────────────────────── */

export function fitPlan(contentW, contentH, w, h, padding = 24) {
  const zw = (w - padding * 2) / Math.max(1, contentW);
  const zh = (h - padding * 2) / Math.max(1, contentH);
  return { zoom: clamp(Math.min(zw, zh), MIN_ZOOM, MAX_FIT_ZOOM) };
}

/** The viewer's first view: the whole drawing when it fits at 0.75, else phase 1 at 0.9, top-left. */
export function readablePlan(frame, w, h, padding = 24) {
  const contentW = Math.max(1, frame.width), contentH = Math.max(1, frame.height);
  const whole = fitPlan(contentW, contentH, w, h, padding).zoom;
  if (whole >= READABLE_MIN_ZOOM) return { zoom: whole, x: (w - contentW * whole) / 2, y: Math.max(padding, (h - contentH * whole) / 2), mode: 'whole' };
  const lanes = frame.lanes || [];
  const lane = lanes.length ? lanes[0] : { x: 0, y: 0, w: contentW, h: contentH };
  const left = lane.x - (lanes.length ? Math.max(0, frame.channelW || 0) : 0);
  const fits = Math.min((w - padding * 2) / Math.max(1, lane.x + lane.w - left), (h - padding * 2) / Math.max(1, lane.h));
  const zoom = READABLE_ZOOM;
  const x = contentW * zoom <= w ? (w - contentW * zoom) / 2 : padding - left * zoom;
  const y = contentH * zoom <= h ? (h - contentH * zoom) / 2 : padding - lane.y * zoom;
  return { zoom, x, y, mode: fits >= zoom ? 'phase-fit' : 'phase-anchor' };
}

const screenRect = (r, vp) => ({ x: r.x * vp.zoom + vp.x, y: r.y * vp.zoom + vp.y, w: r.w * vp.zoom, h: r.h * vp.zoom });
const inside = (r, area) => r.x >= 0 && r.y >= 0 && r.x + r.w <= area.w && r.y + r.h <= area.h;

/**
 * What the first view shows on a canvas: its zoom and mode, the cards wholly in view (the phase
 * index is not subtracted), the share of the frame in view, and the zoom "Fit the whole diagram" uses.
 */
export function firstView(scene, canvas, plan = null) {
  const vp = plan || readablePlan(scene, canvas.w, canvas.h);
  const cards = (scene.nodes || []).filter((n) => !n.group);
  const shown = cards.filter((n) => inside(screenRect(n, vp), canvas)).length;
  const view = { x: -vp.x / vp.zoom, y: -vp.y / vp.zoom, w: canvas.w / vp.zoom, h: canvas.h / vp.zoom };
  const ix = Math.max(0, Math.min(view.x + view.w, scene.width) - Math.max(view.x, 0));
  const iy = Math.max(0, Math.min(view.y + view.h, scene.height) - Math.max(view.y, 0));
  return {
    zoom: round(vp.zoom, 1000), mode: vp.mode,
    cardsInView: shown, cards: cards.length,
    frameInViewShare: round((ix * iy) / Math.max(1, scene.width * scene.height), 1000),
    wholeZoom: round(fitPlan(scene.width, scene.height, canvas.w, canvas.h).zoom, 1000),
  };
}

/* ── the review walk's claims (src/walk.ts claimOrder) ────────────────────────────────────── */

/**
 * Every claim once, in the walk's order, from a WorkflowDocument: the phases in document order; in
 * each, its steps in document order with a group before its same-phase children, depth first; each
 * step followed by its outgoing connections, then the findings whose first cited step it is;
 * connections with no known source and findings that cite no step last. Used only when a scene does
 * not carry the viewer's own order (`walkOrder`), as a scene read from the bundle does.
 */
export function claimOrder(doc) {
  const nodes = doc.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lexical = new Map();
  for (const n of nodes) lexical.set(n.id, n.parent && byId.has(n.parent) ? n.parent : null);
  const cyclic = (id) => { let cur = lexical.get(id), hops = 0; while (cur) { if (cur === id || ++hops > 4096) return true; cur = lexical.get(cur); } return false; };
  for (const n of nodes) if (cyclic(n.id)) lexical.set(n.id, null);
  const laneChildren = new Map(), roots = new Map();
  const push = (m, k, v) => { const l = m.get(k); if (l) l.push(v); else m.set(k, [v]); };
  for (const n of nodes) {
    const p = lexical.get(n.id);
    if (p && byId.get(p).phase === n.phase) push(laneChildren, p, n.id);
    else push(roots, n.phase, n.id);
  }
  const declared = (doc.phases || []).map((p) => p.id);
  const unknown = [...new Set(nodes.map((n) => n.phase).filter((p) => !declared.includes(p)))].sort();
  const order = [], at = new Map();
  const visit = (id) => {
    if (at.has(id) || !byId.has(id)) return;
    at.set(id, order.length); order.push(id);
    for (const c of laneChildren.get(id) || []) visit(c);
  };
  for (const lane of declared.concat(unknown)) for (const r of roots.get(lane) || []) visit(r);
  for (const n of nodes) visit(n.id);
  const out = [];
  const outEdges = new Map();
  for (const e of (doc.edges || []).filter((e) => byId.has(e.source) && byId.has(e.target))) push(outEdges, e.source, e);
  const homed = new Map(), homeless = [];
  for (const f of doc.findings || []) {
    let home = null;
    for (const id of f.nodeIds || []) { const k = at.get(id); if (k !== undefined && (home === null || k < at.get(home))) home = id; }
    if (home === null) homeless.push(f.id); else push(homed, home, f.id);
  }
  const seenE = new Set(), seenF = new Set();
  for (const id of order) {
    out.push({ kind: 'node', id });
    for (const e of outEdges.get(id) || []) if (!seenE.has(e.id)) { seenE.add(e.id); out.push({ kind: 'edge', id: e.id }); }
    for (const f of homed.get(id) || []) if (!seenF.has(f)) { seenF.add(f); out.push({ kind: 'issue', id: f }); }
  }
  for (const e of doc.edges || []) if (!seenE.has(e.id)) { seenE.add(e.id); out.push({ kind: 'edge', id: e.id }); }
  for (const f of homeless) if (!seenF.has(f)) { seenF.add(f); out.push({ kind: 'issue', id: f }); }
  return out;
}

/** Whether a claim is inferred or unresolved (the walk's default "Not observed" filter). */
export function notObserved(doc, claim) {
  const list = claim.kind === 'node' ? doc.nodes : claim.kind === 'edge' ? doc.edges : doc.findings;
  const item = (list || []).find((x) => x.id === claim.id);
  return !!item && !!item.basis && item.basis !== 'observed';
}

/**
 * The claims of a walk filter ('all' or 'notObserved') with what the camera frames for each: a
 * step's drawn box (a collapsed group's box when folded), a connection's two end boxes (`ends`, and
 * their union) and its drawn route, a finding's cited steps and the end boxes of its cited
 * connections.
 */
export function claimsFor(doc, scene, filter = 'all') {
  const box = new Map((scene.nodes || []).map((n) => [n.id, n]));
  const rep = (id) => box.get(id) || box.get((scene.repOf || {})[id]) || null;
  const routeOf = new Map();
  for (const e of scene.edges || []) for (const id of e.docIds || [e.id]) routeOf.set(id, e.points);
  const edgeById = new Map((doc.edges || []).map((e) => [e.id, e]));
  const findingById = new Map((doc.findings || []).map((f) => [f.id, f]));
  const endBoxes = (edgeId) => {
    const e = edgeById.get(edgeId);
    if (!e) return null;
    const a = rep(e.source), b = rep(e.target);
    return a && b ? [pick(a), pick(b)] : null;
  };
  const endsRect = (edgeId) => {
    const ends = endBoxes(edgeId);
    return ends ? unionRect(ends) : null;
  };
  const out = [];
  for (const c of scene.walkOrder || claimOrder(doc)) {
    if (filter === 'notObserved' && !notObserved(doc, c)) continue;
    if (c.kind === 'node') { const r = rep(c.id); if (r) out.push({ kind: c.kind, id: c.id, rect: pick(r) }); continue; }
    if (c.kind === 'edge') { const ends = endBoxes(c.id); if (ends) out.push({ kind: c.kind, id: c.id, rect: unionRect(ends), ends, route: routeOf.get(c.id) || null }); continue; }
    const f = findingById.get(c.id);
    if (!f) continue;
    const steps = (f.nodeIds || []).map(rep).filter(Boolean).map(pick);
    const ends = (f.edgeIds || []).map(endsRect).filter(Boolean);
    if (steps.length + ends.length) out.push({ kind: c.kind, id: c.id, rect: unionRect(steps.concat(ends)), steps, ends });
  }
  return out;
}

/* ── the walk camera (canvasview.ts revealTarget / frameIssue, render/canvas.ts) ──────────── */

/** render/canvas.ts clearOf: the least pan moving screen rect `r` off `covered`, inside the canvas. */
function clearOf(r, covered, w, h, gap = 8) {
  if (!(r.x < covered.x + covered.w && covered.x < r.x + r.w && r.y < covered.y + covered.h && covered.y < r.y + r.h)) return null;
  const options = [];
  const left = covered.x - gap - (r.x + r.w);
  if (r.x + left >= 0) options.push({ dx: left, dy: 0 });
  const up = covered.y - gap - (r.y + r.h);
  if (r.y + up >= 0) options.push({ dx: 0, dy: up });
  const right = covered.x + covered.w + gap - r.x;
  if (r.x + r.w + right <= w) options.push({ dx: right, dy: 0 });
  const down = covered.y + covered.h + gap - r.y;
  if (r.y + r.h + down <= h) options.push({ dx: 0, dy: down });
  if (!options.length) return null;
  options.sort((p, q) => Math.abs(p.dx) + Math.abs(p.dy) - (Math.abs(q.dx) + Math.abs(q.dy)));
  return options[0];
}

/** render/canvas.ts clearOfAll: the least pan putting every screen rect in `parts` on the canvas and off `covered`. */
function clearOfAll(parts, covered, w, h, gap = 8) {
  if (!parts.length) return { dx: 0, dy: 0 };
  const eps = 0.01;
  let x0 = -Infinity, x1 = Infinity, y0 = -Infinity, y1 = Infinity;
  for (const p of parts) {
    x0 = Math.max(x0, -p.x); x1 = Math.min(x1, w - p.x - p.w);
    y0 = Math.max(y0, -p.y); y1 = Math.min(y1, h - p.y - p.h);
  }
  if (x0 > x1 + eps || y0 > y1 + eps) return null;
  const clear = (dx, dy, g) => !covered || parts.every((p) => !rectsOverlap({ x: p.x + dx, y: p.y + dy, w: p.w, h: p.h }, covered, g));
  const start = { dx: Math.min(Math.max(0, x0), x1), dy: Math.min(Math.max(0, y0), y1) };
  if (clear(start.dx, start.dy, 0)) return start;
  const xs = [x0, x1], ys = [y0, y1];
  for (const p of parts) {
    xs.push(covered.x - gap - (p.x + p.w), covered.x + covered.w + gap - p.x);
    ys.push(covered.y - gap - (p.y + p.h), covered.y + covered.h + gap - p.y);
  }
  xs.push(start.dx); ys.push(start.dy);
  let best = null, cost = Infinity;
  for (const rawX of xs) {
    if (rawX < x0 - eps || rawX > x1 + eps) continue;
    const dx = Math.min(Math.max(rawX, x0), x1);
    for (const rawY of ys) {
      if (rawY < y0 - eps || rawY > y1 + eps) continue;
      const dy = Math.min(Math.max(rawY, y0), y1);
      if (!clear(dx, dy, gap - eps)) continue;
      const c = Math.abs(dx) + Math.abs(dy);
      if (c < cost - 1e-9) { cost = c; best = { dx, dy }; }
    }
  }
  return best;
}

class Camera {
  constructor(vp, area, covered = null) { this.vp = { ...vp }; this.area = area; this.covered = covered; }
  isVisible(r) {
    const s = screenRect(r, this.vp);
    if (!inside(s, this.area)) return false;
    return !this.covered || !rectsOverlap(s, this.covered);
  }
  centerOn(r, zoom) {
    if (typeof zoom === 'number') this.vp.zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
    const z = this.vp.zoom;
    this.vp.x = this.area.w / 2 - (r.x + r.w / 2) * z;
    this.vp.y = this.area.h / 2 - (r.y + r.h / 2) * z;
    if (this.covered) {
      const shift = clearOf(screenRect(r, this.vp), this.covered, this.area.w, this.area.h);
      if (shift) { this.vp.x += shift.dx; this.vp.y += shift.dy; }
    }
  }
  keepClear(anchor) {
    if (!this.covered) return;
    const shift = clearOf(screenRect(anchor, this.vp), this.covered, this.area.w, this.area.h);
    if (shift) { this.vp.x += shift.dx; this.vp.y += shift.dy; }
  }
  revealRect(r, margin = 16) {
    const { w, h } = this.area, z = this.vp.zoom;
    const shift = (start, size, extent) => {
      const pad = Math.max(0, Math.min(margin, (extent - size) / 2));
      if (size > extent) return -start;
      if (start < 0) return pad - start;
      if (start + size > extent) return extent - pad - (start + size);
      return 0;
    };
    let dx = shift(r.x * z + this.vp.x, r.w * z, w);
    let dy = shift(r.y * z + this.vp.y, r.h * z, h);
    if (this.covered) {
      const off = clearOf({ x: r.x * z + this.vp.x + dx, y: r.y * z + this.vp.y + dy, w: r.w * z, h: r.h * z }, this.covered, w, h, Math.min(margin, 8));
      if (off) { dx += off.dx; dy += off.dy; }
    }
    this.vp.x += dx;
    this.vp.y += dy;
  }
  /** render/canvas.ts frameClear: the first zoom from the current one down to `floor` at which `parts` can sit on the canvas, clear of the index. */
  frameClear(r, parts, { floor = FRAME_MIN_ZOOM, margin = 48 } = {}) {
    if (!this.covered || !parts.length) return false;
    const { w, h } = this.area, c = this.covered;
    const fit = (aw, ah) => Math.min((aw - margin) / Math.max(1, r.w), (ah - margin) / Math.max(1, r.h));
    const top = Math.min(this.vp.zoom, fit(w, h));
    if (!(top >= floor - 1e-9)) return false;
    const zooms = [top, fit(w, h - c.h), fit(w - c.w, h)];
    for (let z = top * 0.95; z > floor; z *= 0.95) zooms.push(z);
    zooms.push(floor);
    for (const z of zooms.filter((v) => v <= top + 1e-9 && v >= floor - 1e-9).sort((a, b) => b - a)) {
      const x = w / 2 - (r.x + r.w / 2) * z, y = h / 2 - (r.y + r.h / 2) * z;
      const shift = clearOfAll(parts.map((p) => ({ x: p.x * z + x, y: p.y * z + y, w: p.w * z, h: p.h * z })), c, w, h);
      if (!shift) continue;
      this.vp = { x: x + shift.dx, y: y + shift.dy, zoom: clamp(z, MIN_ZOOM, MAX_ZOOM) };
      return true;
    }
    return false;
  }
  readableZoomFor(r) {
    const margin = Math.min(48, Math.round(Math.min(this.area.w, this.area.h) / 10));
    return Math.min(READABLE_ZOOM, Math.min((this.area.w - margin) / Math.max(1, r.w), (this.area.h - margin) / Math.max(1, r.h)));
  }
  fitsAt(r, zoom, margin = 48) {
    return Math.min((this.area.w - margin) / Math.max(1, r.w), (this.area.h - margin) / Math.max(1, r.h)) >= zoom;
  }
  frameRect(r, anchor, readable, margin = 48) {
    const fits = Math.min((this.area.w - margin) / Math.max(1, r.w), (this.area.h - margin) / Math.max(1, r.h));
    const zoom = this.vp.zoom;
    if (zoom >= LOD_FULL_ZOOM && fits >= zoom) { this.centerOn(r); this.keepClear(anchor); return; }
    const ceiling = zoom >= LOD_FULL_ZOOM ? Math.max(FRAME_MAX_ZOOM, zoom) : readable;
    const next = Math.max(FRAME_MIN_ZOOM, Math.min(ceiling, fits));
    this.centerOn(fits >= FRAME_MIN_ZOOM ? r : anchor, next);
    this.keepClear(anchor);
  }
  zoomAboutCentre(zoom) {
    const { w, h } = this.area, z = this.vp.zoom;
    const px = (w / 2 - this.vp.x) / z, py = (h / 2 - this.vp.y) / z;
    this.vp.zoom = zoom;
    this.vp.x = w / 2 - px * zoom;
    this.vp.y = h / 2 - py * zoom;
  }
}

/** A camera at viewport `vp` over a canvas `area`, with the phase index's `covered` rectangle. */
export function makeCamera(vp, area, covered = null) { return new Camera(vp, area, covered); }

/**
 * Walk policies the replay knows:
 *   W0: the walk without W1's return to reading size. A finding frames its cited cards
 *       (frameIssue); a step or a connection pans the least distance that shows its box
 *       (revealRect), and below 0.62 it is centred at up to 0.9. A connection whose
 *       union fits the canvas, but whose end cards that pan leaves under the phase index, is framed
 *       (frameClear: centred, then the least pan that clears both, zooming out to 0.75 when none
 *       does). The viewer also clears a target once more after a move that reshaped the index (the
 *       pill's width follows the phase it names); the replay's index has one fixed rectangle, so
 *       that pass never runs here.
 *   W1: the viewer's policy. W0, and when a finding left the zoom between 0.62 and
 *       0.75, the next step or connection first zooms back about the canvas centre to 0.9, or as far
 *       as its box still fits (`readableZoomFor`), as CanvasView.walkTarget does. The viewer does so
 *       only from a zoom it chose itself, never one the reader set; the replay has no reader, so
 *       every zoom in that band is one a finding's frame (or a step after it) chose.
 */
export const WALK_POLICIES = ['W0', 'W1'];

export function walkStep(cam, claim, policy = 'W1') {
  if (claim.kind === 'issue') {
    const steps = claim.steps || [], ends = claim.ends || [];
    const rects = steps.concat(ends);
    if (!rects.length) return;
    const all = unionRect(rects);
    const target = !steps.length || !ends.length || cam.fitsAt(all, FRAME_MIN_ZOOM) ? all : unionRect(steps);
    cam.frameRect(target, rects[0], READABLE_ZOOM);
    return;
  }
  const r = claim.rect;
  if (policy === 'W1' && cam.vp.zoom < READABLE_MIN_ZOOM - 1e-9 && cam.vp.zoom >= LOD_FULL_ZOOM) cam.zoomAboutCentre(Math.max(cam.vp.zoom, cam.readableZoomFor(r)));
  if (cam.vp.zoom < LOD_FULL_ZOOM) { cam.centerOn(r, Math.max(cam.vp.zoom, cam.readableZoomFor(r))); return; }
  if (cam.isVisible(r)) return;
  cam.revealRect(r);
  // A union that fits the canvas but whose end cards the pan left under the index is framed down to 0.75.
  const ends = claim.kind === 'edge' && claim.ends && claim.ends.length === 2 ? claim.ends : null;
  if (ends && !(cam.isVisible(ends[0]) && cam.isVisible(ends[1])) && cam.fitsAt(r, cam.vp.zoom, 0)) cam.frameClear(r, ends, { floor: READABLE_MIN_ZOOM, margin: 32 });
}

/** The move as a vector in screen px at the new zoom: how far the canvas-centre point travels. */
export function panVector(a, b, area) {
  const c0 = { x: (area.w / 2 - a.x) / a.zoom, y: (area.h / 2 - a.y) / a.zoom };
  const c1 = { x: (area.w / 2 - b.x) / b.zoom, y: (area.h / 2 - b.y) / b.zoom };
  return { dx: (c1.x - c0.x) * b.zoom, dy: (c1.y - c0.y) * b.zoom };
}

function visibleShareOf(points, vp, area) {
  if (!points || points.length < 2) return null;
  let total = 0, shown = 0;
  for (const p of samples(points, 3)) {
    total += p.w;
    const sx = p.x * vp.zoom + vp.x, sy = p.y * vp.zoom + vp.y;
    if (sx >= 0 && sy >= 0 && sx <= area.w && sy <= area.h) shown += p.w;
  }
  return total ? shown / total : null;
}

/**
 * Replay the review walk over `claims` (claimsFor). The camera starts at the first view for
 * `firstCanvas`, keeps it when the walk opens the bottom sheet (`walkCanvas`), then takes each claim
 * in turn. It does not model a step that expands a folded group (a relayout in the viewer). Per
 * step: the pan distance, the zoom, whether the target was wholly in view before and after (clear
 * of `covered`), whether it fits the walk canvas at 0.9 at all, and for a connection the share of
 * its drawn route in view after the step.
 */
export function walkCamera(scene, claims, opts = {}) {
  const first = opts.firstCanvas || PANELS['900'].first;
  const area = opts.walkCanvas || first;
  const policy = opts.policy || 'W1';
  if (!WALK_POLICIES.includes(policy)) throw new Error('unknown walk policy ' + policy);
  const start = opts.start || readablePlan(scene, first.w, first.h);
  const cam = new Camera({ x: start.x, y: start.y, zoom: start.zoom }, area, opts.covered || null);
  const steps = [];
  for (const claim of claims) {
    const before = { ...cam.vp };
    const visibleBefore = cam.isVisible(claim.rect);
    walkStep(cam, claim, policy);
    const after = { ...cam.vp };
    const v = panVector(before, after, area);
    steps.push({
      kind: claim.kind, id: claim.id,
      dist: round(Math.hypot(v.dx, v.dy), 10), dx: round(v.dx, 10), dy: round(v.dy, 10), zoom: round(after.zoom, 1000), zoomChanged: Math.abs(after.zoom - before.zoom) > 1e-6,
      visibleBefore,
      fitsAt90: Math.min(area.w / Math.max(1, claim.rect.w), area.h / Math.max(1, claim.rect.h)) >= READABLE_ZOOM,
      visibleAfter: cam.isVisible(claim.rect),
      routeInView: claim.kind === 'edge' ? visibleShareOf(claim.route, after, area) : null,
    });
  }
  return { policy, steps, summary: summarizeWalk(steps, area) };
}

/** Travel between consecutive claims (the first step, from the first view, is apart), and how often a claim is off screen. */
export function summarizeWalk(steps, area) {
  const moves = steps.slice(1).map((s) => s.dist);
  const edges = steps.filter((s) => s.kind === 'edge' && s.routeInView !== null);
  const share = (n) => round(n / Math.max(1, steps.length), 1000);
  return {
    claims: steps.length,
    area: { w: area.w, h: area.h },
    firstStep: steps.length ? steps[0].dist : 0,
    panTotal: Math.round(sum(moves)),
    panMean: Math.round(mean(moves)), panMedian: Math.round(quantile(moves, 0.5)), panP90: Math.round(quantile(moves, 0.9)), panMax: Math.round(moves.length ? Math.max(...moves) : 0),
    movedShare: round(moves.filter((d) => d > 0.5).length / Math.max(1, moves.length), 1000),
    // Not wholly in view before its step; cannot be shown whole at 0.9 on this canvas; still not
    // wholly in view after its step.
    offscreenBeforeShare: share(steps.filter((s) => !s.visibleBefore).length),
    tooBigAt90Share: share(steps.filter((s) => !s.fitsAt90).length),
    offscreenAfterShare: share(steps.filter((s) => !s.visibleAfter).length),
    zoomChanges: steps.filter((s) => s.zoomChanged).length,
    // A finding's frame can zoom out (down to 0.45). Below 0.62 the next step or connection zooms
    // back in, to 0.9 or as far as its box still fits, and never out (it may stay where it is);
    // from 0.62 to 0.75 only W1 zooms back.
    belowReadableShare: share(steps.filter((s) => s.zoom < READABLE_MIN_ZOOM - 1e-9).length),
    minZoom: steps.length ? round(Math.min(...steps.map((s) => s.zoom)), 1000) : null,
    // A move of 100 px or more followed by one of 100 px or more roughly back (cos < -0.7).
    backAndForth: steps.slice(2).filter((s, i) => {
      const p = steps[i + 1];
      if (s.dist < 100 || p.dist < 100) return false;
      return (s.dx * p.dx + s.dy * p.dy) / (s.dist * p.dist) < -0.7;
    }).length,
    routePartlyOffShare: edges.length ? round(edges.filter((s) => s.routeInView < 0.9).length / edges.length, 1000) : null,
    routeInViewMean: edges.length ? round(mean(edges.map((s) => s.routeInView)), 1000) : null,
  };
}

/* ── the scene of a document, read from the built bundle ──────────────────────────────────── */

const bundleCache = new Map();

/** The bundle's bytes and a short sha256, read once per path. */
export function bundleInfo(path = DIST_JS) {
  if (!bundleCache.has(path)) {
    const code = readFileSync(path, 'utf8');
    bundleCache.set(path, { path, code, sha256: createHash('sha256').update(code).digest('hex').slice(0, 16) });
  }
  return bundleCache.get(path);
}

function loadBundleFrom(path) {
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', () => undefined);
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://mlview.test/', virtualConsole,
  });
  if (typeof dom.window.structuredClone !== 'function') dom.window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
  const script = dom.window.document.createElement('script');
  script.textContent = bundleInfo(path).code;
  dom.window.document.head.appendChild(script);
  if (!dom.window.MLView) throw new Error(path + ' did not define window.MLView');
  return { window: dom.window, document: dom.window.document, MLView: dom.window.MLView };
}

/**
 * Mount `doc` in a fresh jsdom with the built bundle and read the drawn scene from the view's scene
 * plan: boxes, routes with their least certain basis, label placements and trunk bundles. With
 * `collapsed`, those groups are folded as a restored view state folds them; without, the document
 * opens as a reader first sees it.
 */
export function sceneOf(doc, opts = {}) {
  const ctx = loadBundleFrom(opts.bundle || DIST_JS);
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, bridge);
  try {
    if (Array.isArray(opts.collapsed)) bridge.send({ v: 1, type: 'restoreState', state: { collapsed: opts.collapsed } });
    const view = app.view;
    const index = app.index;
    const plan = view.scenePlan();
    if (!index || !plan) throw new Error('the viewer drew no scene');
    const frame = plan.frame;
    const collapsed = view.collapsed;
    const nodes = [];
    for (const box of frame.boxes.values()) {
      nodes.push({
        id: box.id, x: box.x, y: box.y, w: box.w, h: box.h,
        group: box.isGroup && !box.collapsed, collapsed: box.collapsed,
        parent: index.parentOf.get(box.id) || null, lane: box.laneId,
      });
    }
    const repOf = {};
    for (const n of index.graph.nodes) {
      const rep = index.visibleRepresentative(n.id, collapsed);
      if (rep !== n.id) repOf[n.id] = rep;
    }
    const edges = plan.edges.map((visual) => {
      const r = visual.route, lp = visual.placement;
      return {
        id: r.id, docIds: r.ids.slice(), source: r.source, target: r.target,
        points: r.points.map((p) => ({ x: p.x, y: p.y })), basis: visual.basis,
        label: r.label || '', labelAlways: lp ? lp.always : false,
        labelRect: lp && !lp.hidden ? { x: lp.rect.x, y: lp.rect.y, w: lp.rect.w, h: lp.rect.h } : null, labelHidden: lp ? lp.hidden : false,
      };
    });
    const overlays = [], restHidden = [];
    for (const { bundle: b } of plan.bundles) {
      overlays.push({ id: b.id, bundle: b.id, kind: 'trunk', points: b.trunk.map((p) => ({ x: p.x, y: p.y })) });
      b.spurs.forEach((s, i) => overlays.push({ id: b.id + ':spur' + i, bundle: b.id, kind: 'spur', member: s.id, points: s.points.map((p) => ({ x: p.x, y: p.y })) }));
      for (const id of b.memberIds) restHidden.push(id);
    }
    const scene = {
      name: doc.title || null,
      width: frame.width, height: frame.height, channelW: frame.channelW,
      lanes: frame.lanes.map((l) => ({ id: l.id, x: l.x, y: l.y, w: l.w, h: l.h })),
      nodes, edges, overlays, restHidden, repOf,
      walkOrder: app.walk.claims().map((c) => ({ kind: c.kind, id: c.id })),
    };
    return { scene, info: { collapsed: [...collapsed], bundles: plan.bundles.length } };
  } finally {
    app.destroy();
    ctx.window.close();
  }
}

/* ── one document, measured ───────────────────────────────────────────────────────────────── */

/**
 * Everything the tool reports for one document: the layout measures (independent of the panel,
 * the layout being a function of the document and its folds), and per panel width the first view,
 * the framing of connections at 0.45 and 0.9, and the replayed walk over All claims and Not observed.
 */
export function measureDocument(doc, opts = {}) {
  const widths = opts.widths || WIDTHS;
  const policy = opts.policy || 'W1';
  const { scene, info } = sceneOf(doc, { bundle: opts.bundle, collapsed: opts.collapsed });
  const layout = measureLayout(scene);
  const perPanel = {};
  for (const w of widths) {
    const P = PANELS[w];
    if (!P) throw new Error('no measured canvas for a ' + w + ' px panel (known: ' + WIDTHS.join(', ') + ')');
    const walk = {};
    for (const filter of ['all', 'notObserved']) {
      const claims = claimsFor(doc, scene, filter);
      walk[filter] = walkCamera(scene, claims, { firstCanvas: P.first, walkCanvas: P.walk, covered: P.covered, policy });
    }
    perPanel[w] = {
      firstView: firstView(scene, P.first),
      framing045: framing(scene, P.walk, FRAME_MIN_ZOOM),
      framing090: framing(scene, P.walk, READABLE_ZOOM),
      walk: { all: walk.all.summary, notObserved: walk.notObserved.summary },
    };
  }
  return {
    counts: { steps: (doc.nodes || []).length, connections: (doc.edges || []).length, phases: (doc.phases || []).length, findings: (doc.findings || []).length },
    collapsed: info.collapsed,
    policy,
    layout,
    perPanel,
    ...(opts.scene ? { scene } : {}),
  };
}

/** The compact numbers the table prints and the baseline records. */
export function summarize(result) {
  const l = result.layout;
  const perPanel = {};
  for (const [w, p] of Object.entries(result.perPanel)) {
    perPanel[w] = {
      firstViewCards: p.firstView.cardsInView,
      walkAll: p.walk.all.panTotal,
      walkAllClaims: p.walk.all.claims,
      walkNotObserved: p.walk.notObserved.panTotal,
      walkNotObservedClaims: p.walk.notObserved.claims,
      uncertainFramable045: p.framing045.uncertainFit,
    };
  }
  return {
    counts: { ...result.counts, cards: l.counts.cards, cables: l.edges.cables },
    frame: [Math.round(l.size.width), Math.round(l.size.height)],
    crossings: l.crossings.cables,
    crossingsAtRest: l.crossings.atRest,
    cardHits: l.throughCards.hits,
    cardHitCables: l.throughCards.cables,
    unrelatedOverlap: l.overlaps.unrelatedShare,
    uncertain: { cables: l.uncertain.cables, hiddenHalf: l.uncertain.hiddenHalf, inTrunk: l.uncertain.inTrunk, drawnOn: l.uncertain.drawnOn },
    labels: { alwaysOn: l.labels.alwaysOn, alwaysHidden: l.labels.alwaysHidden, atRest: l.labels.atRest, crossedByUnrelated: l.labels.crossedByUnrelated },
    perPanel,
  };
}

/* ── the documents ────────────────────────────────────────────────────────────────────────── */

const readDoc = (path) => () => JSON.parse(readFileSync(path, 'utf8'));
const SAMPLES_DIR = join(REPO_ROOT, 'samples');
const TEST_WORKSPACE = join(REPO_ROOT, 'contracts', 'conformance', 'documents', 'workspace');
const TEST_DOCUMENTS = ['d01-minimal', 'd02-notebook', 'd03-two-files', 'd04-loop', 'd05-groups', 'd06-refinement', 'd07-multi-file', 'd08-dense'];

/** The names of the sample diagrams, `samples/<name>.mlview.json`, in sorted order. */
export function sampleDiagrams() {
  return readdirSync(SAMPLES_DIR).filter((file) => file.endsWith('.mlview.json')).map((file) => file.slice(0, -'.mlview.json'.length)).sort();
}

/**
 * The documents of the default run: every sample diagram, the synthetic shapes of
 * test/helpers.mjs and the benchmark chain. The synthetic shapes are stress cases (random
 * connections), not realistic layouts.
 */
export function repoDocuments() {
  return [
    ...sampleDiagrams().map((name) => ({ name: 'sample ' + name, set: 'repo sample', load: readDoc(join(SAMPLES_DIR, name + '.mlview.json')) })),
    { name: 'renderer-regression-48', set: 'synthetic (the geometry golden fixture)', load: () => rendererRegressionWorkflow(48) },
    { name: 'SHAPE_79_CLAIMS', set: 'synthetic (random connections)', load: () => shapedWorkflow(SHAPE_79_CLAIMS) },
    { name: 'SHAPE_176_CLAIMS', set: 'synthetic (random connections)', load: () => shapedWorkflow(SHAPE_176_CLAIMS) },
    { name: 'benchmark-120', set: 'synthetic (a chain over 8 phases)', load: () => benchmarkWorkflow(120, 'relayout-r1') },
  ];
}

/**
 * The documents `--dev` adds: the eight generated test documents of
 * contracts/conformance/documents. They are test fixtures, not diagrams of real programs. The
 * baseline holds these and the default documents, with each one's step and connection counts.
 */
export function devDocuments() {
  return TEST_DOCUMENTS.map((name) => ({ name: 'doc ' + name, set: 'generated test document', load: readDoc(join(TEST_WORKSPACE, name + '.mlview.json')) }));
}

/* ── output ───────────────────────────────────────────────────────────────────────────────── */

const pct = (v) => (v === null || v === undefined ? '-' : Math.round(v * 1000) / 10 + '%');
const row = (cells) => '| ' + cells.join(' | ') + ' |';

export function tables(entries, widths) {
  const ok = entries.filter((e) => e.summary);
  const out = [];
  out.push('Layout (independent of the panel width)', '');
  out.push(row(['Document', 'Steps/conn./phases', 'Frame', 'Crossings (at rest)', 'Card hits (cables)', 'On an unrelated cable', 'Uncertain: half hidden / in a trunk / drawn on a stroke / all', 'Always-on labels hidden', 'At-rest labels crossed by an unrelated cable']));
  out.push(row(Array(9).fill('---')));
  for (const { name, summary: s } of ok) {
    out.push(row([name, `${s.counts.steps}/${s.counts.connections}/${s.counts.phases}`, s.frame.join(' x '), `${s.crossings} (${s.crossingsAtRest})`, `${s.cardHits} (${s.cardHitCables})`,
      pct(s.unrelatedOverlap), `${s.uncertain.hiddenHalf} / ${s.uncertain.inTrunk} / ${s.uncertain.drawnOn} / ${s.uncertain.cables}`, `${s.labels.alwaysHidden} of ${s.labels.alwaysOn}`, `${s.labels.crossedByUnrelated} of ${s.labels.atRest}`]));
  }
  const ws = widths.join(' / ');
  out.push('', 'Per panel width (' + ws + ' px)', '');
  out.push(row(['Document', 'Whole cards in the first view', 'Walk travel, All claims (px)', 'Walk travel, Not observed (px)', 'Claims All / Not observed', 'Uncertain framable at 0.45']));
  out.push(row(Array(6).fill('---')));
  for (const { name, summary: s } of ok) {
    const at = (k) => widths.map((w) => s.perPanel[w][k]).join(' / ');
    const any = s.perPanel[widths[0]];
    out.push(row([name, `${at('firstViewCards')} of ${s.counts.cards}`, at('walkAll'), at('walkNotObserved'), `${any.walkAllClaims} / ${any.walkNotObservedClaims}`, `${at('uncertainFramable045')} of ${s.uncertain.cables}`]));
  }
  for (const e of entries.filter((x) => x.error)) out.push('', `${e.name}: not measured (${e.error})`);
  return out.join('\n');
}

export function uncertainTable(entries) {
  const out = ['', 'Inferred and unresolved cables (shares of the stroke)', ''];
  out.push(row(['Document', 'Cable', 'Basis', 'Length', 'By a stroke at rest', 'On a stroke at rest', 'Along a trunk', 'Under a card', 'In a trunk', 'Crossings']));
  out.push(row(Array(10).fill('---')));
  for (const e of entries) {
    if (!e.result) continue;
    for (const u of e.result.layout.uncertain.list) {
      out.push(row([e.name, u.id + (u.docIds.length > 1 ? ` (x${u.docIds.length})` : ''), u.basis, u.length, pct(u.overlapShare), pct(u.onStrokeShare), pct(u.onTrunkShare), pct(u.underCardShare), u.inTrunk ? 'yes' : 'no', u.crossings]));
    }
  }
  return out.join('\n');
}

/** Flatten a summary to `path: value` pairs, for the comparison with the baseline. */
function flat(value, prefix = '', out = {}) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value)) flat(v, prefix ? prefix + '.' + k : k, out);
  } else out[prefix] = Array.isArray(value) ? value.join(' x ') : value;
  return out;
}

export function compareWithBaseline(entries, baseline, now) {
  const out = ['', `Compared with ${basename(BASELINE_FILE)} (walk ${baseline.policy}) on bundle ${now.bundleSha256}, walk ${now.policy}; informational only`, ''];
  let changed = 0;
  for (const e of entries) {
    if (!e.summary) continue;
    const before = baseline.documents[e.name];
    if (!before) { out.push(`${e.name}: not in the baseline`); continue; }
    const a = flat(before.summary), b = flat(e.summary);
    const keys = [...new Set(Object.keys(a).concat(Object.keys(b)))];
    const moved = keys.filter((k) => a[k] !== b[k]).map((k) => `${k} ${a[k] === undefined ? '-' : a[k]} -> ${b[k] === undefined ? '-' : b[k]}`);
    if (moved.length) { changed++; out.push(`${e.name}:`, ...moved.map((m) => '  ' + m)); }
  }
  if (!changed) out.push('No summary number differs from the baseline.');
  return out.join('\n');
}

/* ── the command line ─────────────────────────────────────────────────────────────────────── */

const HELP = `Usage: node tools/layout-metrics.mjs [options] [document.mlview.json ...]

Measures the layout the built viewer (dist/mlview.js) draws, in jsdom. The numbers
are informational: it exits 0 once it has printed, whatever they are. It exits 1
when a document could not be read or measured, and 2 on a bad option.

  --dev              also the eight test documents (contracts/conformance/documents)
  --no-repo          only the documents named on the command line
  --widths 541,900   panel widths (default ${WIDTHS.join(',')}; only those have measured canvases)
  --policy W1|W0     the walk policy replayed (default W1, the viewer's;
                     W0 is the walk without W1's return to reading size)
  --bundle <file>    another build of mlview.js (for example another checkout's dist/)
  --json             JSON instead of tables; --full adds every measure behind the summary
  --uncertain        list every inferred or unresolved cable and where its stroke is hidden
  --baseline         list the summary numbers that differ from layout-metrics.baseline.json
  --write-baseline   re-record layout-metrics.baseline.json (repo-held documents only)
`;

function parseArgs(argv) {
  const opts = { repo: true, dev: false, widths: WIDTHS, policy: 'W1', bundle: DIST_JS, json: false, full: false, uncertain: false, baseline: false, write: false, files: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const value = () => {
      if (i + 1 >= argv.length) throw new Error(a + ' needs a value');
      return argv[++i];
    };
    if (a === '--help' || a === '-h') opts.help = true;
    else if (a === '--dev') opts.dev = true;
    else if (a === '--no-repo') opts.repo = false;
    else if (a === '--widths') opts.widths = value().split(',').map((w) => w.trim()).filter(Boolean);
    else if (a === '--policy') opts.policy = value();
    else if (a === '--bundle') opts.bundle = resolve(value());
    else if (a === '--json') opts.json = true;
    else if (a === '--full') { opts.full = true; opts.json = true; }
    else if (a === '--uncertain') opts.uncertain = true;
    else if (a === '--baseline') opts.baseline = true;
    else if (a === '--write-baseline') opts.write = true;
    else if (a.startsWith('--')) throw new Error('unknown option ' + a);
    else opts.files.push(resolve(a));
  }
  for (const w of opts.widths) if (!PANELS[w]) throw new Error('no measured canvas for a ' + w + ' px panel (known: ' + WIDTHS.join(', ') + ')');
  if (!WALK_POLICIES.includes(opts.policy)) throw new Error('unknown walk policy ' + opts.policy + ' (known: ' + WALK_POLICIES.join(', ') + ')');
  if (opts.write) {
    // The baseline is committed: it holds repo-held documents only, measured as the viewer ships.
    if (opts.files.length || !opts.repo) throw new Error('--write-baseline records the repo-held documents only; drop the document paths and --no-repo');
    if (opts.widths.join() !== WIDTHS.join() || opts.policy !== 'W1' || opts.bundle !== DIST_JS) throw new Error('--write-baseline records every width, walk W1 and this checkout\'s dist/mlview.js');
    opts.dev = true;
  }
  return opts;
}

export function run(argv) {
  const opts = parseArgs(argv);
  if (opts.help) return { text: HELP, failed: [] };
  const docs = [];
  if (opts.repo) docs.push(...repoDocuments());
  if (opts.dev) docs.push(...devDocuments());
  for (const file of opts.files) docs.push({ name: basename(file).replace(/\.mlview\.json$|\.json$/, ''), set: 'command line', file, load: readDoc(file) });
  const bundle = bundleInfo(opts.bundle);
  const entries = docs.map((d) => {
    try {
      const result = measureDocument(d.load(), { widths: opts.widths, policy: opts.policy, bundle: opts.bundle });
      return { name: d.name, set: d.set, result, summary: summarize(result) };
    } catch (err) {
      return { name: d.name, set: d.set, error: err && err.message ? err.message : String(err) };
    }
  });
  const header = { tool: TOOL_ID, bundleSha256: bundle.sha256, policy: opts.policy, widths: opts.widths };
  // The documents that could not be read or measured: the command exits 1 when there is one.
  const failed = entries.filter((e) => e.error).map((e) => e.name);
  if (opts.write) {
    const baseline = {
      tool: TOOL_ID,
      about: 'Informational baseline of node tools/layout-metrics.mjs on the repo-held documents. No test compares a layout number with it; test/layout-metrics.test.mjs compares its document names and their step, connection, phase and finding counts with the tracked documents. Re-record with --write-baseline when a change moves the layout on purpose, and say so in the pull request.',
      policy: 'W1',
      panels: PANELS,
      documents: Object.fromEntries(entries.filter((e) => e.summary).map((e) => [e.name, { set: e.set, summary: e.summary }])),
    };
    if (failed.length) throw new Error('not recorded, some documents failed: ' + entries.filter((e) => e.error).map((e) => e.name + ' (' + e.error + ')').join('; '));
    writeFileSync(BASELINE_FILE, JSON.stringify(baseline, null, 1) + '\n');
    return { text: tables(entries, opts.widths) + '\n\nWrote ' + BASELINE_FILE + '\n', failed };
  }
  if (opts.json) {
    const documents = entries.map((e) => (e.error ? { name: e.name, set: e.set, error: e.error } : { name: e.name, set: e.set, summary: e.summary, ...(opts.full ? { detail: e.result } : {}) }));
    return { text: JSON.stringify({ ...header, panels: PANELS, documents }, null, 1) + '\n', failed };
  }
  let text = `${TOOL_ID}: bundle ${bundle.sha256}, walk ${opts.policy} (replayed), geometric proxies only\n\n` + tables(entries, opts.widths) + '\n';
  if (opts.uncertain) text += uncertainTable(entries) + '\n';
  if (opts.baseline) text += compareWithBaseline(entries, JSON.parse(readFileSync(BASELINE_FILE, 'utf8')), header) + '\n';
  return { text, failed };
}

// Node resolves the entry file's symlinks for import.meta.url and leaves process.argv[1] as typed
// (with --preserve-symlinks-main both stay as typed), so the two are compared as real paths.
function invokedDirectly() {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(resolve(process.argv[1]));
  } catch {
    return false;
  }
}

if (invokedDirectly()) {
  let result;
  try {
    result = run(process.argv.slice(2));
  } catch (err) {
    process.stderr.write('layout-metrics: ' + (err && err.message ? err.message : String(err)) + '\n');
    process.exit(2);
  }
  // jsdom can leave timers behind; exit once the output is flushed.
  const print = () => process.stdout.write(result.text, () => process.exit(result.failed.length ? 1 : 0));
  if (result.failed.length) process.stderr.write('layout-metrics: not measured: ' + result.failed.join(', ') + '\n', print);
  else print();
}
