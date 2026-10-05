// Stage 0a (requirement R7): decluttering never hides an inferred or unresolved connection.
//
// Such a cable is drawn dashed or dotted, and a dash pattern drawn on or beside a solid stroke
// reads as that stroke. So it never joins a VIEW-04 trunk (`layout/routing.ts`, and
// `layout/bundles.ts` refuses it again), it takes a left-channel track of its own inside the
// innermost observed trunk (`layout/channel.ts`, reserved in `layout/layout.ts`), and
// `layout/separate.ts` moves its other runs off the strokes they would share where it finds room.
//
// Checked on the renderer-regression fixture (expanded and folded), the two synthetic shapes, the
// repo sample and a benchmark: no such cable has a trunk reference or is a bundle member; less than
// half of each lies within 4 px of a parallel stroke drawn at rest (another cable, a trunk or a
// spur) or under a card it does not belong to; none passes through such a card, lies within 4 px
// along a card, group or lane border, runs through a lane or group header, or has a run under 8 px,
// beyond what the router already drew.
// On hand-made documents: a channel track keeps 8 px from every other channel run beside it and
// 10 px from the bands, the channel widens only when the tracks need it, and folding changes none
// of it.
//
// The numbers are a geometric proxy read from the scene plan in jsdom. They say nothing about how
// a reader sees the dashes in a live VS Code webview.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { benchmarkWorkflow } from '../tools/benchmark-model.mjs';
import {
  REPO_ROOT, VIT_SHAPE, YOLO_SHAPE, loadBundle, recordingBridge, rendererRegressionWorkflow, shapedWorkflow,
} from './helpers.mjs';

const HIDDEN = 4;
const TRACK_CLEAR = 8;
const BAND_CLEAR = 10;
const notObserved = (basis) => basis === 'inferred' || basis === 'unresolved';

async function planOf(doc, collapsed = null) {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, bridge);
  if (collapsed) bridge.send({ v: 1, type: 'restoreState', state: { collapsed } });
  const plan = app.view.scenePlan();
  assert.ok(plan, 'the viewer drew a scene');
  app.destroy();
  ctx.window.close();
  return plan;
}

const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);

/** Points every 2 px along a polyline, with the unit direction there and the length each stands for. */
function samples(points) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1], b = points[i];
    const len = dist(a, b);
    if (len < 0.01) continue;
    const n = Math.max(1, Math.round(len / 2));
    for (let k = 0; k < n; k++) {
      const t = (k + 0.5) / n;
      out.push({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, ux: (b.x - a.x) / len, uy: (b.y - a.y) / len, w: len / n });
    }
  }
  return out;
}

function segments(points) {
  const out = [];
  for (let i = 1; i < points.length; i++) if (dist(points[i - 1], points[i]) > 0.01) out.push([points[i - 1], points[i]]);
  return out;
}

function pointSegDist(p, [a, b]) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

/** The strokes drawn at rest: every cable a bundle does not hide, and every trunk and spur. */
function restStrokes(plan) {
  const hidden = new Set(plan.bundles.flatMap((v) => v.bundle.memberIds));
  const out = plan.edges.filter((v) => !hidden.has(v.route.id)).map((v) => ({ owner: v.route.id, segs: segments(v.route.points) }));
  for (const { bundle } of plan.bundles) {
    out.push({ owner: bundle.id, segs: segments(bundle.trunk) });
    for (const spur of bundle.spurs) out.push({ owner: spur.id, segs: segments(spur.points) });
  }
  return out;
}

/** Cards a cable must not cross: leaf cards and folded groups, minus its own ends and their groups. */
function foreignCards(plan, route) {
  const own = new Set();
  for (const id of [route.source, route.target]) {
    for (let at = id; at; at = plan.index.parentOf.get(at)) own.add(at);
  }
  return Array.from(plan.frame.boxes.values()).filter((b) => (!b.isGroup || b.collapsed) && !own.has(b.id));
}

const inside = (p, b) => p.x > b.x + 1 && p.x < b.x + b.w - 1 && p.y > b.y + 1 && p.y < b.y + b.h - 1;

function segHitsCard([a, b], card) {
  for (let k = 0; k <= 32; k++) {
    const t = k / 32;
    if (inside({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }, card)) return true;
  }
  return false;
}

/**
 * The longest stretch of a polyline within 4 px of a border and parallel to it: a card's, a group's
 * or a lane's, its own included. A dash pattern on a border reads as the border, and an inferred
 * card or group is drawn dashed itself.
 */
function alongBorder(plan, points) {
  let longest = 0;
  const outlines = plan.frame.lanes.concat(Array.from(plan.frame.boxes.values()));
  for (const [a, b] of segments(points)) {
    const h = Math.abs(a.y - b.y) < 0.01;
    if (!h && Math.abs(a.x - b.x) >= 0.01) continue;
    const c = h ? a.y : a.x, lo = h ? Math.min(a.x, b.x) : Math.min(a.y, b.y), hi = h ? Math.max(a.x, b.x) : Math.max(a.y, b.y);
    for (const r of outlines) {
      const sides = h ? [r.y, r.y + r.h] : [r.x, r.x + r.w];
      const from = h ? r.x : r.y, to = h ? r.x + r.w : r.y + r.h;
      if (sides.some((side) => Math.abs(side - c) <= HIDDEN)) longest = Math.max(longest, Math.min(hi, to) - Math.max(lo, from));
    }
  }
  return longest;
}

/** How far a polyline runs inside the header strip of a lane or a group, where the headings are. */
function inHeaders(plan, points) {
  const strips = plan.frame.lanes.map((l) => ({ x: l.x, y: l.y, w: l.w, h: l.headerH }))
    .concat(Array.from(plan.frame.boxes.values()).filter((b) => b.headerH > 0).map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.headerH })));
  let total = 0;
  for (const [a, b] of segments(points)) {
    if (Math.abs(a.y - b.y) >= 0.01) continue;
    const lo = Math.min(a.x, b.x), hi = Math.max(a.x, b.x);
    for (const r of strips) if (a.y > r.y && a.y < r.y + r.h) total += Math.max(0, Math.min(hi, r.x + r.w) - Math.max(lo, r.x));
  }
  return total;
}

/** For each inferred or unresolved cable: its hidden share, and what the checks below read. */
function exceptions(plan) {
  const strokes = restStrokes(plan);
  return plan.edges.filter((v) => notObserved(v.basis)).map((v) => {
    const route = v.route;
    const cards = foreignCards(plan, route);
    let covered = 0, total = 0;
    for (const p of samples(route.points)) {
      total += p.w;
      const onStroke = strokes.some((s) => s.owner !== route.id && s.segs.some((seg) => {
        const len = dist(seg[0], seg[1]);
        const cos = ((seg[1].x - seg[0].x) * p.ux + (seg[1].y - seg[0].y) * p.uy) / len;
        return Math.abs(cos) > 0.96 && pointSegDist(p, seg) <= HIDDEN;
      }));
      if (onStroke || cards.some((c) => inside(p, c))) covered += p.w;
    }
    const through = cards.filter((c) => segments(route.points).some((seg) => segHitsCard(seg, c))).map((c) => c.id);
    const shortest = Math.min(...segments(route.points).map(([a, b]) => dist(a, b)));
    return { id: route.id, share: total ? covered / total : 0, through, alongBorder: alongBorder(plan, route.points), inHeaders: inHeaders(plan, route.points), shortest };
  });
}

const sample = () => JSON.parse(readFileSync(join(REPO_ROOT, 'samples', 'configured_training.mlview.json'), 'utf8'));
// `before` lists what the router already draws before stage 0a, which the separation pass never
// makes worse and does not repair: cards a cable passes through, and runs shorter than 8 px.
const FIXTURES = [
  ['the renderer-regression fixture', () => rendererRegressionWorkflow(), null, {}],
  ['the renderer-regression fixture, every group folded', () => rendererRegressionWorkflow(), Array.from({ length: 8 }, (_, i) => `node-${i}`), {}],
  ['the vit-cc shape', () => shapedWorkflow(VIT_SHAPE), null, {}],
  // An up-lane cable drawn, like the observed c15 beside it, through five cards.
  ['the yolov5-cc2 shape', () => shapedWorkflow(YOLO_SHAPE), null, { crossed: { c90: ['n16', 'n22', 'n23', 'n29', 'n32'] } }],
  ['the repo sample', sample, null, {}],
  // Two cables with a 2 px jog.
  ['the 100-step benchmark', () => benchmarkWorkflow(100), null, { short: { 'edge-1': 2, 'edge-3': 2 } }],
];

for (const [name, make, collapsed, before] of FIXTURES) {
  test(`${name}: no inferred or unresolved cable is in a trunk`, async () => {
    const plan = await planOf(make(), collapsed);
    const uncertain = plan.edges.filter((v) => notObserved(v.basis));
    assert.ok(uncertain.length > 0, 'the fixture draws an inferred or unresolved cable');
    const members = new Set(plan.bundles.flatMap((v) => v.bundle.memberIds));
    for (const v of plan.edges) {
      if (notObserved(v.basis)) {
        assert.equal(v.route.notObserved, true, v.route.id);
        assert.equal(v.route.trunk, undefined, v.route.id + ' has a trunk reference');
        assert.ok(!members.has(v.route.id), v.route.id + ' is a bundle member');
      } else {
        assert.equal(v.route.notObserved, undefined, v.route.id);
      }
    }
  });

  test(`${name}: less than half of each inferred or unresolved cable is hidden, none crosses a card, a border or a header`, async () => {
    const plan = await planOf(make(), collapsed);
    for (const e of exceptions(plan)) {
      assert.ok(e.share < 0.5, `${e.id}: ${(e.share * 100).toFixed(1)}% within ${HIDDEN} px of a parallel stroke or under a card`);
      assert.deepEqual(e.through.sort(), (before.crossed || {})[e.id] || [], e.id + ' passes through a card');
      assert.equal(e.alongBorder, 0, `${e.id} runs ${e.alongBorder} px along a border`);
      assert.equal(e.inHeaders, 0, `${e.id} runs ${e.inHeaders} px through a header`);
      assert.ok(e.shortest >= Math.min(8, (before.short || {})[e.id] || 8), `${e.id} has a run of ${e.shortest} px`);
    }
  });
}

/* ── the left channel ─────────────────────────────────────────────────────────────────────── */

/**
 * Four phases of two steps each, the steps of a phase chained, two observed connections that skip
 * a lane (p0 to p2 and p1 to p3), and `extra` more that skip lanes, each with its basis.
 */
function channelWorkflow(extra) {
  const phases = Array.from({ length: 4 }, (_, i) => ({ id: 'p' + i, label: 'Phase ' + i }));
  const nodes = [];
  for (let i = 0; i < 4; i++) for (const s of ['a', 'b']) nodes.push({ id: 'n' + i + s, label: 'Step ' + i + s, phase: 'p' + i, basis: 'observed', evidence: ['e'] });
  const edge = (id, source, target, basis = 'observed') => ({ id, source, target, label: id, kind: 'data', basis, evidence: ['e'] });
  const edges = [
    edge('a01', 'n0a', 'n1a'), edge('a12', 'n1a', 'n2a'), edge('a23', 'n2a', 'n3a'),
    edge('s02', 'n0a', 'n2a'), edge('s13', 'n1a', 'n3a'),
    ...extra.map(([id, source, target, basis]) => edge(id, source, target, basis)),
  ];
  return {
    workflowVersion: '1.0', title: 'Channel fixture', producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' }, phases, nodes, edges, findings: [],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

/** The vertical runs a plan draws left of the bands: [route id, basis, x, y0, y1]. */
function channelRuns(plan) {
  const laneX = Math.min(...plan.frame.lanes.map((l) => l.x));
  const out = [];
  for (const v of plan.edges) {
    for (const [a, b] of segments(v.route.points)) {
      if (Math.abs(a.x - b.x) < 0.5 && a.x < laneX) out.push([v.route.id, v.basis, a.x, Math.min(a.y, b.y), Math.max(a.y, b.y)]);
    }
  }
  return { laneX, runs: out };
}

/** Every channel run of an inferred or unresolved cable keeps its distance from the others and the bands. */
function assertOwnTracks(plan) {
  const { laneX, runs } = channelRuns(plan);
  const own = runs.filter((r) => notObserved(r[1]));
  assert.ok(own.length > 0, 'an inferred or unresolved cable runs in the channel');
  for (const r of own) {
    assert.ok(laneX - r[2] >= BAND_CLEAR, `${r[0]} runs ${laneX - r[2]} px from the bands`);
    for (const o of runs) {
      if (o[0] === r[0] || o[4] <= r[3] || o[3] >= r[4]) continue;
      assert.ok(Math.abs(o[2] - r[2]) >= TRACK_CLEAR, `${r[0]} at x ${r[2]} runs ${Math.abs(o[2] - r[2])} px from ${o[0]} at x ${o[2]}`);
    }
  }
  return runs;
}

const boxesOf = (plan) => JSON.stringify(Array.from(plan.frame.boxes.values()).map((b) => [b.id, b.x, b.y, b.w, b.h]));

test('an inferred cable that skips a lane takes a channel track of its own, inside the observed trunks', async () => {
  const observed = await planOf(channelWorkflow([['x03', 'n0b', 'n3b', 'observed']]));
  const inferred = await planOf(channelWorkflow([['x03', 'n0b', 'n3b', 'inferred']]));
  // The channel was already wide enough: the reservation, the bands and the cards stay where they were.
  assert.equal(inferred.frame.channelW, observed.frame.channelW);
  assert.equal(boxesOf(inferred), boxesOf(observed));
  const runs = assertOwnTracks(inferred);
  const x03 = runs.find((r) => r[0] === 'x03');
  const trunks = runs.filter((r) => r[1] === 'observed').map((r) => r[2]);
  assert.equal(x03[2], Math.max(...trunks) + TRACK_CLEAR, 'one track step inside the innermost observed trunk');
  assert.equal(x03[2], inferred.frame.exceptionX);
});

test('inferred and unresolved cables whose spans overlap take separate tracks, and the channel widens for them', async () => {
  // Three observed pairs fill the channel's slots; the three tracks would come closer than 10 px to the bands.
  const extra = [['o03', 'n0a', 'n3a', 'observed'], ['x03', 'n0b', 'n3b', 'inferred'], ['x02', 'n0b', 'n2b', 'unresolved'], ['x13', 'n1b', 'n3b', 'inferred']];
  const plan = await planOf(channelWorkflow(extra));
  assert.equal(plan.frame.exceptionTracks, 3);
  const observed = await planOf(channelWorkflow(extra.map(([id, s, t]) => [id, s, t, 'observed'])));
  assert.ok(plan.frame.channelW > observed.frame.channelW, `${plan.frame.channelW} > ${observed.frame.channelW}`);
  // Only as far as the tracks need: the last one sits exactly 10 px from the bands.
  const laneX = Math.min(...plan.frame.lanes.map((l) => l.x));
  assert.equal(laneX - (plan.frame.exceptionX + 2 * TRACK_CLEAR), BAND_CLEAR);
  assertOwnTracks(plan);
});

test('the channel reservation does not change when groups fold', async () => {
  const groups = Array.from({ length: 8 }, (_, i) => `node-${i}`);
  const expanded = await planOf(rendererRegressionWorkflow());
  const folded = await planOf(rendererRegressionWorkflow(), groups);
  assert.ok(expanded.frame.exceptionTracks > 0);
  assert.equal(folded.frame.channelW, expanded.frame.channelW);
  assert.equal(folded.frame.exceptionX, expanded.frame.exceptionX);
  assert.equal(folded.frame.exceptionTracks, expanded.frame.exceptionTracks);
});
