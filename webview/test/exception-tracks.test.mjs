// Decluttering never hides an inferred or unresolved connection.
//
// Such a cable is drawn dashed or dotted, and a dash pattern drawn on or beside a solid stroke
// reads as that stroke. So it never joins a trunk (`layout/routing.ts`, and `layout/bundles.ts`
// refuses it again), it takes a left-channel track of its own inside the innermost observed trunk
// (`layout/channel.ts`, reserved in `layout/layout.ts`), and `layout/separate.ts` moves its other
// runs off the strokes they would share where it finds room.
//
// Checked on the renderer-regression fixture (expanded and folded), the two synthetic shapes, the
// test document d06-refinement and a benchmark: no such cable has a trunk reference or is a
// bundle member; less than half of each lies within 4 px of a parallel stroke drawn at rest
// (another cable, a trunk or a spur) or under a card it does not belong to; none passes through
// such a card, lies within 4 px along a card, group or lane border, runs through a lane or group
// header or within 4 px along its edges, or has a run under 8 px, beyond what the router already
// drew. On the two of them where a run inside the bands lies within the pass's reach of their
// left edge, each cable keeps its vertical runs on the side of that edge the router put them on.
// On hand-made documents: a channel track keeps 8 px from every other channel run beside it and
// 10 px from the bands, also where the trunk step is a fraction of a pixel, the channel widens only
// when the tracks need it, and folding changes none of it; a moved cable does not cross or lie on
// itself, does not settle on the line under a lane's header, and leaves the frame no further than
// the router drew it.
//
// The numbers are geometry, read from the scene plan that the built bundle draws in jsdom.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { benchmarkWorkflow } from '../tools/benchmark-model.mjs';
import {
  REPO_ROOT, SHAPE_79_CLAIMS, SHAPE_176_CLAIMS, loadBundle, recordingBridge, rendererRegressionWorkflow, shapedWorkflow,
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

/**
 * How far a polyline runs along the header strip of a lane or a group, where the headings are:
 * inside it, on its edges or within 4 px of them. A lane header's lower edge is a drawn line; a
 * group heading has none, and its lower edge is read the same way.
 */
function inHeaders(plan, points) {
  const strips = plan.frame.lanes.map((l) => ({ x: l.x, y: l.y, w: l.w, h: l.headerH }))
    .concat(Array.from(plan.frame.boxes.values()).filter((b) => b.headerH > 0).map((b) => ({ x: b.x, y: b.y, w: b.w, h: b.headerH })));
  let total = 0;
  for (const [a, b] of segments(points)) {
    if (Math.abs(a.y - b.y) >= 0.01) continue;
    const lo = Math.min(a.x, b.x), hi = Math.max(a.x, b.x);
    for (const r of strips) if (a.y >= r.y - HIDDEN && a.y <= r.y + r.h + HIDDEN) total += Math.max(0, Math.min(hi, r.x + r.w) - Math.max(lo, r.x));
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

const testDocument = () => JSON.parse(readFileSync(join(REPO_ROOT, 'contracts', 'conformance', 'documents', 'workspace', 'd06-refinement.mlview.json'), 'utf8'));
// `before` lists what the router draws before the separation pass runs, which the pass never makes
// worse and does not repair: cards a cable passes through, and runs shorter than 8 px.
const FIXTURES = [
  ['the renderer-regression fixture', () => rendererRegressionWorkflow(), null, {}],
  ['the renderer-regression fixture, every group folded', () => rendererRegressionWorkflow(), Array.from({ length: 8 }, (_, i) => `node-${i}`), {}],
  ['the 79-claim shape', () => shapedWorkflow(SHAPE_79_CLAIMS), null, {}],
  // An up-lane cable drawn, like the observed c15 beside it, through five cards.
  ['the 176-claim shape', () => shapedWorkflow(SHAPE_176_CLAIMS), null, { crossed: { c90: ['n16', 'n22', 'n23', 'n29', 'n32'] } }],
  ['the test document d06-refinement', testDocument, null, {}],
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

/* ── what a move is refused for, on documents small enough to read ────────────────────────── */

/** A document from rows: steps as [id, phase, parent, label], connections as [id, source, target, basis, kind]. */
function rowsWorkflow(title, phaseIds, steps, connections) {
  return {
    workflowVersion: '1.0', title, producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    phases: phaseIds.map((id) => ({ id, label: 'Phase ' + id })),
    nodes: steps.map(([id, phase, parent, label]) => ({ id, label: label || id, phase, kind: 'operation', basis: 'observed', evidence: ['e'], ...(parent ? { parent } : {}) })),
    edges: connections.map(([id, source, target, basis = 'observed', kind = 'data']) => ({ id, source, target, label: '', kind, basis, evidence: ['e'] })),
    findings: [],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

/** How often a polyline crosses, touches or lies on a run of its own that is not a neighbour. */
function selfContacts(points) {
  const runs = segments(points).map(([a, b]) => ({ x0: Math.min(a.x, b.x), x1: Math.max(a.x, b.x), y0: Math.min(a.y, b.y), y1: Math.max(a.y, b.y) }));
  let n = 0;
  for (let i = 0; i < runs.length; i++) {
    for (let j = i + 2; j < runs.length; j++) {
      const a = runs[i], b = runs[j];
      if (a.x0 <= b.x1 && b.x0 <= a.x1 && a.y0 <= b.y1 && b.y0 <= a.y1) n++;
    }
  }
  return n;
}

// A connection to a card left of its source is routed out, down to the lane's band, a short jog
// back and up again: two legs side by side. Sliding one leg past the other turns the jog
// round, and the last run then crosses the first leg, or lies on the first run when both ports
// share a y.
const HAIRPINS = [
  ['crosses', rowsWorkflow('Hairpin, ports apart', ['p0'],
    [['n0', 'p0'], ['n1', 'p0', 'n0'], ['n2', 'p0'], ['n3', 'p0', null, 'checkpoint forward loss augment 3'], ['n4', 'p0'], ['n5', 'p0']],
    [['c0', 'n3', 'n5'], ['c1', 'n5', 'n0', 'inferred'], ['c2', 'n2', 'n3', 'observed', 'loop'], ['c3', 'n4', 'n2', 'inferred'], ['c4', 'n0', 'n3'], ['c5', 'n1', 'n5'], ['c6', 'n2', 'n4']])],
  ['lies on', rowsWorkflow('Hairpin, ports level', ['p0', 'p1'],
    [['n0', 'p0'], ['n1', 'p0'], ['n2', 'p0', null, 'optimizer evaluate metrics 2'], ['n3', 'p0'], ['n4', 'p1']],
    [['c0', 'n0', 'n2', 'inferred'], ['c1', 'n2', 'n0', 'inferred'], ['c2', 'n2', 'n0', 'inferred', 'reads'], ['c3', 'n4', 'n1']])],
];

for (const [what, doc] of HAIRPINS) {
  test(`a moved hairpin neither crosses nor lies on itself (${doc.title}: without the rule it ${what} itself)`, async () => {
    const plan = await planOf(doc);
    const uncertain = plan.edges.filter((v) => notObserved(v.basis));
    assert.ok(uncertain.some((v) => v.route.points.length === 6), 'the fixture draws a hairpin');
    for (const v of uncertain) assert.equal(selfContacts(v.route.points), 0, `${v.route.id} meets itself: ${JSON.stringify(v.route.points.map((p) => [p.x, p.y]))}`);
  });
}

test('a moved gutter run does not settle on the underline of the next lane\'s header', async () => {
  // c15 is an inferred detour inside p0, routed in the gutter under it, close to the observed c14.
  // The first clear offset below it lies on the line drawn under p1's header.
  const doc = rowsWorkflow('Header underline', ['p0', 'p1'],
    [['n0', 'p0'], ['n1', 'p0', null, 'schedule load checkpoint 1'], ['n2', 'p0'], ['n3', 'p1'], ['n5', 'p0'], ['n6', 'p0'], ['n8', 'p0'], ['n9', 'p0'], ['n10', 'p0'],
      ['n11', 'p0', null, 'forward metrics load evaluate loss tokenize batch optimizer forward 11'], ['n12', 'p0'], ['n13', 'p0'], ['n14', 'p0'],
      ['n15', 'p0', null, 'model.fit evaluate augment 15'], ['n18', 'p0'], ['n22', 'p1'], ['n27', 'p1']],
    [['c0', 'n5', 'n2'], ['c1', 'n5', 'n13', 'observed', 'reads'], ['c2', 'n1', 'n5'], ['c3', 'n12', 'n6'], ['c4', 'n15', 'n13'], ['c5', 'n15', 'n1'], ['c6', 'n9', 'n14'], ['c7', 'n9', 'n0'],
      ['c8', 'n6', 'n8'], ['c9', 'n22', 'n27'], ['c10', 'n12', 'n18', 'observed', 'output'], ['c11', 'n8', 'n11', 'observed', 'reads'], ['c12', 'n2', 'n8'], ['c13', 'n8', 'n12'], ['c14', 'n11', 'n1'],
      ['c15', 'n8', 'n13', 'inferred', 'loop']]);
  const plan = await planOf(doc);
  const [below] = plan.frame.lanes.filter((l) => l.id === 'p1');
  const [c15] = exceptions(plan);
  assert.equal(c15.id, 'c15');
  assert.equal(c15.inHeaders, 0, `c15 runs ${c15.inHeaders} px along a header`);
  // It is still a gutter run: above p1's band, not inside it.
  const gutter = segments(plan.edges.find((v) => v.route.id === 'c15').route.points).filter(([a, b]) => Math.abs(a.y - b.y) < 0.01 && dist(a, b) > 200);
  assert.equal(gutter.length, 1);
  assert.ok(gutter[0][0].y < below.y, `the gutter run at y ${gutter[0][0].y} is above p1 at y ${below.y}`);
});

test('a run beside a group heading is not moved into the heading', async () => {
  // n6 holds the group n7 and the card n9. The cable from n6 to n9 is routed just under n7's
  // heading, by its lower edge but not in the strip, and a move may not trade one for the other.
  const doc = rowsWorkflow('Nested heading', ['p0'], [['n6', 'p0'], ['n7', 'p0', 'n6'], ['n8', 'p0', 'n6'], ['n9', 'p0', 'n6'], ['n17', 'p0', 'n7']], [['c0', 'n6', 'n9', 'inferred']]);
  const plan = await planOf(doc);
  const heading = plan.frame.boxes.get('n7');
  assert.ok(heading.headerH > 0, 'n7 is drawn as a group');
  const across = segments(plan.edges[0].route.points).filter(([a, b]) => Math.abs(a.y - b.y) < 0.01 && Math.max(a.x, b.x) > heading.x && Math.min(a.x, b.x) < heading.x + heading.w);
  assert.equal(across.length, 1, 'the cable passes n7 on its way to n9');
  const y = across[0][0].y;
  assert.ok(y >= heading.y + heading.headerH, `the run at y ${y} is in n7's heading, y ${heading.y} to ${heading.y + heading.headerH}`);
});

/** How far each route lies outside the frame, in px, by route id. */
function outsideFrame(plan) {
  const { width, height } = plan.frame;
  return new Map(plan.edges.map((v) => [v.route.id, Math.max(0, ...v.route.points.map((p) => Math.max(-p.x, p.x - width, -p.y, p.y - height)))]));
}

test('no cable is moved further out of the frame than the router drew it', async () => {
  // Two tall phases: the router itself sends cables under the last band, on and past the frame's
  // floor, the same whatever their basis. So each inferred cable is held to its observed drawing.
  const doc = shapedWorkflow({ ...SHAPE_176_CLAIMS, seed: 30, phases: 2 });
  const withBasis = (basis) => ({ ...doc, edges: doc.edges.map((e) => ({ ...e, basis })) });
  const observed = await planOf(withBasis('observed'));
  const inferred = await planOf(withBasis('inferred'));
  assert.deepEqual([inferred.frame.width, inferred.frame.height], [observed.frame.width, observed.frame.height]);
  const before = outsideFrame(observed);
  assert.ok(Array.from(before.values()).some((d) => d > 0), 'the router draws a cable past the frame on this fixture');
  for (const [id, now] of outsideFrame(inferred)) assert.ok(now <= before.get(id) + 0.01, `${id} lies ${now} px outside the frame, ${before.get(id)} px when observed`);
});

/* ── the left channel ─────────────────────────────────────────────────────────────────────── */

/**
 * Four phases of two steps each, the steps of a phase chained, two observed connections that skip
 * a lane (p0 to p2 and p1 to p3), and `extra` more that skip lanes, each with its basis. `count`
 * and `skips` give another number of phases and other observed lane-skipping pairs.
 */
function channelWorkflow(extra, count = 4, skips = [[0, 2], [1, 3]]) {
  const phases = Array.from({ length: count }, (_, i) => ({ id: 'p' + i, label: 'Phase ' + i }));
  const nodes = [];
  for (let i = 0; i < count; i++) for (const s of ['a', 'b']) nodes.push({ id: 'n' + i + s, label: 'Step ' + i + s, phase: 'p' + i, basis: 'observed', evidence: ['e'] });
  const edge = (id, source, target, basis = 'observed') => ({ id, source, target, label: id, kind: 'data', basis, evidence: ['e'] });
  const edges = [
    ...Array.from({ length: count - 1 }, (_, i) => edge('a' + i + (i + 1), 'n' + i + 'a', 'n' + (i + 1) + 'a')),
    ...skips.map(([s, t]) => edge('s' + s + t, 'n' + s + 'a', 'n' + t + 'a')),
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
      // Two tracks 8 px apart on a fractional trunk step differ by 7.999999999999986 in doubles.
      assert.ok(Math.abs(o[2] - r[2]) >= TRACK_CLEAR - 0.01, `${r[0]} at x ${r[2]} runs ${Math.abs(o[2] - r[2])} px from ${o[0]} at x ${o[2]}`);
    }
  }
  return runs;
}

/**
 * Which side of the bands' left edge the router puts an inferred or unresolved cable's vertical
 * runs on: one that skips a lane has one run left of it, on a planned track, and any other has
 * none. The separation pass moves no run across that edge, so the drawn cables keep the rule.
 */
function assertChannelSides(plan) {
  const { runs } = channelRuns(plan);
  const frame = plan.frame;
  const laneOf = (id) => frame.laneIndex.get(frame.boxes.get(id).laneId);
  for (const v of plan.edges.filter((e) => notObserved(e.basis))) {
    const own = runs.filter((r) => r[0] === v.route.id).map((r) => r[2]);
    if (Math.abs(laneOf(v.route.source) - laneOf(v.route.target)) < 2) {
      assert.deepEqual(own, [], `${v.route.id} skips no lane and runs left of the bands at x ${own}`);
      continue;
    }
    assert.equal(own.length, 1, `${v.route.id} skips a lane and has ${own.length} runs left of the bands, at x ${own}`);
    const track = (own[0] - frame.exceptionX) / TRACK_CLEAR;
    assert.ok(Math.abs(track - Math.round(track)) < 0.01 && Math.round(track) >= 0 && Math.round(track) < frame.exceptionTracks, `${v.route.id} runs at x ${own[0]}, off the ${frame.exceptionTracks} tracks from x ${frame.exceptionX}`);
  }
}

const boxesOf = (plan) => JSON.stringify(Array.from(plan.frame.boxes.values()).map((b) => [b.id, b.x, b.y, b.w, b.h]));

test('an inferred cable that skips a lane takes a channel track of its own, inside the observed trunks', async () => {
  const observed = await planOf(channelWorkflow([['x03', 'n0b', 'n3b', 'observed']]));
  const inferred = await planOf(channelWorkflow([['x03', 'n0b', 'n3b', 'inferred']]));
  // The channel is wide enough without the track: the reservation, the bands and the cards are
  // where the all-observed document has them.
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

// Nine lane-skipping pairs over seven phases: the trunk step is 84 / 9 rounded down to the
// hundredth, 9.33 px.
const NINE_PAIRS = [[0, 2], [1, 3], [2, 4], [3, 5], [4, 6], [0, 3], [1, 4], [2, 5], [0, 6]];

test('on a fractional trunk step an inferred cable stays on its channel track, 8 px inside the innermost trunk', async () => {
  const plan = await planOf(channelWorkflow([['x06', 'n0b', 'n6b', 'inferred']], 7, NINE_PAIRS));
  assert.equal(plan.frame.channelStep, 9.33);
  const runs = assertOwnTracks(plan);
  assertChannelSides(plan);
  assert.equal(runs.find((r) => r[0] === 'x06')[2], plan.frame.exceptionX, 'x06 is drawn on the track planned for it');
});

test('on a fractional trunk step two cables whose spans overlap stay on their two tracks', async () => {
  // p0 to p4 is a tenth pair with no observed member: the step is 8.4 px and the two tracks sit at
  // 123.2 and 131.2, which are 7.999999999999986 apart in doubles.
  const plan = await planOf(channelWorkflow([['x04', 'n0b', 'n4b', 'inferred'], ['y03', 'n0b', 'n3b', 'unresolved']], 7, NINE_PAIRS));
  assert.equal(plan.frame.channelStep, 8.4);
  assert.equal(plan.frame.exceptionTracks, 2);
  const runs = assertOwnTracks(plan);
  assertChannelSides(plan);
  const xs = ['x04', 'y03'].map((id) => runs.find((r) => r[0] === id)[2]).sort((a, b) => a - b);
  assert.deepEqual(xs, [plan.frame.exceptionX, Math.round((plan.frame.exceptionX + TRACK_CLEAR) * 100) / 100]);
});

// Only the two fixtures where the rule has something to refuse: a vertical run inside the bands
// that a move of up to 40 px could take into the channel (the precondition read first below). In
// the other four states no such run is within that reach. No fixture has a channel track that a
// move could take into the bands, so that direction is not exercised here.
const REACH = 40;
for (const [name, make, collapsed] of FIXTURES.filter(([name]) => name === 'the renderer-regression fixture' || name === 'the 176-claim shape')) {
  test(`${name}: no inferred or unresolved cable changes sides of the bands' left edge`, async () => {
    const plan = await planOf(make(), collapsed);
    const laneX = Math.min(...plan.frame.lanes.map((l) => l.x));
    const inside = plan.edges.filter((v) => notObserved(v.basis)).flatMap((v) => segments(v.route.points)).filter(([a, b]) => Math.abs(a.x - b.x) < 0.5 && a.x >= laneX).map(([a]) => a.x - laneX);
    assert.ok(Math.min(...inside) <= REACH, `precondition: a vertical run lies within ${REACH} px inside the bands' left edge (the nearest is ${Math.min(...inside)} px)`);
    assertChannelSides(plan);
  });
}

test('the 176-claim shape: a run routed inside the bands is not moved into the channel beside a track', async () => {
  assertOwnTracks(await planOf(shapedWorkflow(SHAPE_176_CLAIMS)));
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
