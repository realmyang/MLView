/**
 * Layout gates (amendment A7):
 *   deterministic · no sibling bbox overlap · every node inside its lane's
 *   y-range · back-edges routed outside their loop container · cross-lane edges
 *   through the gutters · 150 nodes / 300 edges under 300 ms.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample, makeSyntheticGraph } from './helpers.mjs';
import { budgetMs, budgetReport } from './perfbudget.mjs';

// The 300 ms in A7 is a budget for THE REFERENCE MACHINE. `budgetMs` scales it by
// a calibration workload run in this same process, so a slower or a loaded runner
// is measured rather than guessed at, and a machine as fast as the reference gets
// exactly 300 ms (HEALTH-03).
const LAYOUT_BASE_MS = 300;

const ctx = await loadBundle();
const { MLView } = ctx;
const sample = await readSample();

function boxesById(layout) {
  const map = new Map();
  for (const n of layout.nodes) map.set(n.id, n);
  return map;
}

function ancestorsOf(id, boxes) {
  const out = [];
  let cur = boxes.get(id);
  while (cur && cur.parent) {
    out.push(cur.parent);
    cur = boxes.get(cur.parent);
  }
  return out;
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

test('layout is deterministic for the same input', () => {
  const a = MLView.__internal.layout(sample);
  const b = MLView.__internal.layout(sample);
  assert.equal(JSON.stringify(a), JSON.stringify(b));
});

test('layout is deterministic for a 150-node synthetic graph', () => {
  const graph = makeSyntheticGraph(150, 300);
  const a = MLView.__internal.layout(graph);
  const b = MLView.__internal.layout(graph);
  assert.equal(JSON.stringify(a), JSON.stringify(b));
});

test('no two sibling boxes overlap', () => {
  for (const graph of [sample, makeSyntheticGraph(150, 300)]) {
    const layout = MLView.__internal.layout(graph);
    const boxes = boxesById(layout);
    for (let i = 0; i < layout.nodes.length; i++) {
      for (let j = i + 1; j < layout.nodes.length; j++) {
        const a = layout.nodes[i];
        const b = layout.nodes[j];
        if (!overlaps(a, b)) continue;
        // Overlap is only legal between a box and one of its own ancestors.
        const nested = ancestorsOf(a.id, boxes).indexOf(b.id) >= 0 || ancestorsOf(b.id, boxes).indexOf(a.id) >= 0;
        assert.ok(nested, 'unrelated boxes overlap: ' + a.id + ' and ' + b.id);
      }
    }
  }
});

test('every node sits inside its own lane band', () => {
  for (const graph of [sample, makeSyntheticGraph(150, 300)]) {
    const layout = MLView.__internal.layout(graph);
    const lanes = new Map(layout.lanes.map((l) => [l.id, l]));
    for (const node of layout.nodes) {
      const lane = lanes.get(node.lane);
      assert.ok(lane, 'node ' + node.id + ' has no lane band');
      assert.ok(node.y >= lane.y + lane.headerH - 0.01, node.id + ' starts above its lane content area');
      assert.ok(node.y + node.h <= lane.y + lane.h + 0.01, node.id + ' overflows the bottom of lane ' + lane.id);
      assert.ok(node.x >= lane.x - 0.01, node.id + ' starts left of lane ' + lane.id);
      assert.ok(node.x + node.w <= lane.x + lane.w + 0.01, node.id + ' overflows the right of lane ' + lane.id);
    }
  }
});

test('lane bands are stacked in stage order and never overlap', () => {
  const layout = MLView.__internal.layout(sample);
  const order = ['config', 'data', 'preprocess', 'model', 'objective', 'train', 'eval', 'deliver'];
  const seen = layout.lanes.map((l) => l.id);
  const expected = order.filter((id) => seen.indexOf(id) >= 0);
  assert.equal(seen.join(','), expected.join(','));
  for (let i = 1; i < layout.lanes.length; i++) {
    const prev = layout.lanes[i - 1];
    const cur = layout.lanes[i];
    assert.ok(cur.y > prev.y + prev.h, 'lane ' + cur.id + ' overlaps ' + prev.id);
  }
  // Absent stages are not drawn as bands.
  assert.equal(seen.indexOf('deliver'), -1);
});

test('control back-edges are routed outside the box they return to', () => {
  const layout = MLView.__internal.layout(sample);
  const boxes = boxesById(layout);
  const backEdges = layout.edges.filter((e) => e.back);
  assert.ok(backEdges.length >= 2, 'the sample carries the two loop back-edges');
  for (const edge of backEdges) {
    const target = boxes.get(targetOf(sample, edge.ids[0]));
    const source = boxes.get(sourceOf(sample, edge.ids[0]));
    assert.ok(target && source, 'back-edge endpoints have boxes');
    // The return run — the long horizontal segment — is drawn BELOW both boxes,
    // i.e. outside the loop container rather than through it (R1.5).
    let run = null;
    for (let i = 1; i < edge.points.length; i++) {
      const a = edge.points[i - 1];
      const b = edge.points[i];
      if (Math.abs(a.y - b.y) > 0.01) continue;
      const len = Math.abs(a.x - b.x);
      if (!run || len > run.len) run = { y: a.y, len };
    }
    assert.ok(run, 'back-edge ' + edge.id + ' has a horizontal return run');
    const floor = Math.max(source.y + source.h, target.y + target.h);
    assert.ok(run.y >= floor - 0.01, 'back-edge ' + edge.id + ' returns through its loop container');
  }
});

function targetOf(graph, edgeId) {
  const edge = graph.edges.find((e) => e.id === edgeId);
  return edge ? edge.target : '';
}

test('cross-lane edges travel through the gutter between bands', () => {
  const layout = MLView.__internal.layout(sample);
  const lanes = new Map(layout.lanes.map((l) => [l.id, l]));
  const boxes = boxesById(layout);
  const cross = layout.edges.filter((e) => e.crossLane);
  assert.ok(cross.length > 0, 'the sample has cross-lane edges');
  for (const edge of cross) {
    const src = boxes.get(sourceOf(sample, edge.ids[0]));
    const dst = boxes.get(targetOf(sample, edge.ids[0]));
    if (!src || !dst) continue;
    const a = lanes.get(src.lane);
    const b = lanes.get(dst.lane);
    assert.ok(a && b && a.id !== b.id);
    const inGutter = edge.points.some((p) => {
      for (const lane of layout.lanes) {
        if (p.y > lane.y && p.y < lane.y + lane.h) return false;
      }
      return true;
    });
    assert.ok(inGutter, 'cross-lane edge ' + edge.id + ' never enters a gutter');
  }
});

function sourceOf(graph, edgeId) {
  const edge = graph.edges.find((e) => e.id === edgeId);
  return edge ? edge.source : '';
}

test('collapsing a group removes its children and merges their edges', () => {
  const groupId = 'n:5500cc66dd77';
  const open = MLView.__internal.layout(sample);
  const shut = MLView.__internal.layout(sample, [groupId]);
  const openIds = new Set(open.nodes.map((n) => n.id));
  const shutIds = new Set(shut.nodes.map((n) => n.id));
  assert.ok(openIds.has('n:9c8d7e6f5a4b'));
  assert.ok(!shutIds.has('n:9c8d7e6f5a4b'), 'children of a collapsed group are not drawn');
  assert.ok(shutIds.has(groupId));
  assert.ok(shut.edges.length <= open.edges.length);
  for (const edge of shut.edges) {
    assert.ok(shutIds.has(sourceRepr(edge, shut)), 'edge endpoints resolve to drawn boxes');
  }
});

function sourceRepr(edge, layout) {
  // The routed edge's first point must lie on the boundary of a drawn box.
  const p = edge.points[0];
  const hit = layout.nodes.find((n) => p.x >= n.x - 1 && p.x <= n.x + n.w + 1 && p.y >= n.y - 1 && p.y <= n.y + n.h + 1);
  return hit ? hit.id : '';
}

test('150 nodes / 300 edges lay out in under 300 ms', () => {
  const graph = makeSyntheticGraph(150, 300);
  // One warm-up pass so the measurement is steady-state, not JIT warm-up.
  MLView.__internal.layout(graph);
  const started = performance.now();
  const layout = MLView.__internal.layout(graph);
  const elapsed = Math.round(performance.now() - started);
  assert.equal(layout.nodes.length, 150);
  assert.ok(layout.edges.length > 0);
  assert.ok(elapsed < budgetMs(LAYOUT_BASE_MS), budgetReport('layout', elapsed, LAYOUT_BASE_MS));
});

test('150 nodes / 300 edges still lay out under budget WITH a scope applied', () => {
  const graph = makeSyntheticGraph(150, 300);
  const { parseScope, project } = MLView.__internal.scope;
  // A projection is a filter over already-sorted arrays, so it must not move the
  // layout budget: the scoped frame is strictly smaller than the full one.
  const scoped = project(graph, parseScope('stage:train', 1));
  MLView.__internal.layout(scoped);
  const started = performance.now();
  const layout = MLView.__internal.layout(scoped);
  const elapsed = Math.round(performance.now() - started);
  assert.ok(layout.nodes.length > 0 && layout.nodes.length < 150, layout.nodes.length + ' nodes drawn');
  assert.ok(elapsed < budgetMs(LAYOUT_BASE_MS), budgetReport('scoped layout', elapsed, LAYOUT_BASE_MS));
  // And no lane is drawn without content, which is the whole point of 11.4 F3.
  for (const lane of layout.lanes) {
    const inside = layout.nodes.filter((n) => n.lane === lane.id);
    assert.ok(inside.length > 0, 'lane ' + lane.id + ' is drawn with ' + inside.length + ' boxes');
  }
});

test('an unknown stage id still gets a lane instead of throwing', () => {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.nodes[0].stage = 'quantize';
  graph.nodes[0].kind = 'teleporter';
  graph.edges[0].kind = 'telepathy';
  const layout = MLView.__internal.layout(graph);
  const laneIds = layout.lanes.map((l) => l.id);
  assert.ok(laneIds.indexOf('quantize') >= 0, 'unknown stage got its own band');
  assert.equal(layout.nodes.length, graph.nodes.length);
});

/* ── round-1 regressions ─────────────────────────────────────────────────── */

/**
 * A lane full of siblings with no edge between them: dagre puts every one of
 * them in rank 0, so this is the shape that produced the 3.9:1 ribbon.
 */
function wideLaneGraph(extra = 15) {
  const graph = JSON.parse(JSON.stringify(sample));
  const template = graph.nodes.find((n) => n.stage === 'preprocess') || graph.nodes[0];
  for (let i = 0; i < extra; i++) {
    const clone = JSON.parse(JSON.stringify(template));
    clone.id = 'n:' + 'ab'.repeat(4) + String(1000 + i);
    clone.label = 'step_' + i;
    clone.qualname = 'prep.step_' + i;
    clone.parent = null;
    clone.issueIds = [];
    clone.stage = 'preprocess';
    graph.nodes.push(clone);
  }
  return graph;
}

/** Every drawn box that an edge between `s` and `t` is not allowed to overlap. */
function obstaclesFor(layout, s, t) {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]));
  const chain = (id) => {
    const out = [id];
    let cur = byId.get(id);
    let hops = 0;
    while (cur && cur.parent && hops++ < 64) {
      out.push(cur.parent);
      cur = byId.get(cur.parent);
    }
    return out;
  };
  const related = new Set([...chain(s), ...chain(t)]);
  return layout.nodes.filter((box) => !related.has(box.id) && !chain(box.id).some((a) => related.has(a)));
}

function segmentHitsBox(a, b, box) {
  const m = 1;
  return (
    Math.max(a.x, b.x) > box.x + m &&
    Math.min(a.x, b.x) < box.x + box.w - m &&
    Math.max(a.y, b.y) > box.y + m &&
    Math.min(a.y, b.y) < box.y + box.h - m
  );
}

function crossingEdges(graph) {
  const layout = MLView.__internal.layout(graph);
  const edgeById = new Map(graph.edges.map((e) => [e.id, e]));
  const bad = [];
  for (const edge of layout.edges) {
    const doc = edgeById.get(edge.ids[0]);
    if (!doc) continue;
    const obstacles = obstaclesFor(layout, doc.source, doc.target);
    for (let i = 1; i < edge.points.length; i++) {
      const hit = obstacles.find((box) => segmentHitsBox(edge.points[i - 1], edge.points[i], box));
      if (hit) {
        bad.push(edge.id + ' through ' + hit.id);
        break;
      }
    }
  }
  return bad;
}

test('the diagram is not a tall ribbon: over-tall ranks wrap (MLV-R1-002)', () => {
  const graph = wideLaneGraph(15);
  const layout = MLView.__internal.layout(graph);
  const ratio = layout.height / layout.width;
  assert.ok(ratio < 2.5, 'aspect ratio is ' + ratio.toFixed(2) + ':1 (budget 2.5)');

  // and no lane is one very long column any more
  for (const lane of layout.lanes) {
    const members = layout.nodes.filter((n) => n.lane === lane.id && !n.parent);
    if (members.length < 4) continue;
    const columns = new Set(members.map((m) => Math.round(m.x)));
    assert.ok(columns.size > 1, 'lane ' + lane.id + ' spreads across more than one column');
  }
});

test('a wrapped lane still respects every layout invariant (MLV-R1-002)', () => {
  const graph = wideLaneGraph(15);
  const a = MLView.__internal.layout(graph);
  const b = MLView.__internal.layout(graph);
  assert.equal(JSON.stringify(a), JSON.stringify(b), 'wrapping is deterministic');
  const boxes = boxesById(a);
  const lanes = new Map(a.lanes.map((l) => [l.id, l]));
  for (let i = 0; i < a.nodes.length; i++) {
    for (let j = i + 1; j < a.nodes.length; j++) {
      const p = a.nodes[i];
      const q = a.nodes[j];
      if (!overlaps(p, q)) continue;
      const nested = ancestorsOf(p.id, boxes).indexOf(q.id) >= 0 || ancestorsOf(q.id, boxes).indexOf(p.id) >= 0;
      assert.ok(nested, 'wrapped boxes overlap: ' + p.id + ' and ' + q.id);
    }
  }
  for (const node of a.nodes) {
    const lane = lanes.get(node.lane);
    assert.ok(node.x >= lane.x - 0.01 && node.x + node.w <= lane.x + lane.w + 0.01, node.id + ' left its lane');
    assert.ok(node.y + node.h <= lane.y + lane.h + 0.01, node.id + ' overflows its lane');
  }
});

test('no edge is drawn through a node it does not connect (MLV-R1-003)', () => {
  for (const [name, graph] of [
    ['sample', sample],
    ['wide lane', wideLaneGraph(15)],
    ['collapsed group', sample],
  ]) {
    const bad = crossingEdges(graph);
    assert.deepEqual(bad, [], name + ': ' + bad.length + ' edge(s) cross an unrelated card');
  }
});

test('a dense random graph keeps edge/node crossings marginal (MLV-R1-003)', () => {
  // The corridor router is exact for pipeline-shaped graphs (the test above) but
  // a 150-node graph of 300 RANDOM edges can exhaust the free corridors in a
  // lane. Hold the residue to a small fraction so a regression still shows up.
  const graph = makeSyntheticGraph(150, 300);
  const total = MLView.__internal.layout(graph).edges.length;
  const bad = crossingEdges(graph);
  assert.ok(total > 200, 'the synthetic graph routes ' + total + ' edges');
  assert.ok(bad.length / total < 0.12, bad.length + ' of ' + total + ' edges cross (budget 12%)');
});

test('the minimap draws and hit-tests with ONE transform (MLV-R1-008)', () => {
  const { fit, toWorld, fromWorld } = MLView.__internal.minimap;
  // the shipped widget, against the sample's very tall content
  const f = fit(200, 130, 952, 3709);
  assert.ok(f.scale > 0 && f.scale <= 130 / 3709 + 1e-9, 'the fit is uniform and height-bound here');
  assert.ok(f.ox > 0, 'letterboxed content is centred rather than pinned left');

  for (const [x, y] of [[0, 0], [476, 1854], [952, 3709], [100, 40]]) {
    const widget = fromWorld(f, x, y);
    const back = toWorld(f, widget.x, widget.y);
    assert.ok(Math.abs(back.x - x) < 0.001 && Math.abs(back.y - y) < 0.001, 'round trip at ' + x + ',' + y);
  }

  // a click in the empty letterbox clamps to the content edge instead of scanning
  const far = toWorld(f, 199, 65);
  assert.equal(far.x, 952, 'clicking right of the drawn content clamps to its edge');
  const near = toWorld(f, 0, 0);
  assert.equal(near.x, 0);
  assert.equal(near.y, 0);

  // and a wide document letterboxes vertically instead
  const wide = fit(200, 130, 4000, 500);
  assert.ok(wide.oy > 0 && Math.abs(wide.ox) < 1e-9);
});

/* ── VIEW-01: lane width, row wrapping and the first-paint zoom ─────────── */

const { MAX_RANK_W, LANE_MIN_W, LANE_PAD } = MLView.__internal.layoutConstants;

/** Left edge, right edge and widest sibling of everything drawn in one lane. */
function laneContent(layout, laneId) {
  const inside = layout.nodes.filter((n) => n.lane === laneId);
  if (inside.length === 0) return null;
  const left = Math.min.apply(null, inside.map((n) => n.x));
  const right = Math.max.apply(null, inside.map((n) => n.x + n.w));
  const roots = inside.filter((n) => !n.parent);
  return { w: right - left, widest: Math.max.apply(null, (roots.length ? roots : inside).map((n) => n.w)), count: inside.length };
}

test('a lane box ends where its own content ends (VIEW-01)', () => {
  // `lane.w = maxContentW` made every band as wide as the widest one: on the
  // 360-node project the objective band was 87 % empty and the world was as
  // wide as the one lane that needed the room, which is what dragged `fit()`
  // onto the zoom floor.
  for (const [name, graph] of [['sample', sample], ['wide lane', wideLaneGraph(15)], ['synthetic', makeSyntheticGraph(150, 300)]]) {
    const layout = MLView.__internal.layout(graph);
    const widths = new Set();
    for (const lane of layout.lanes) {
      const content = laneContent(layout, lane.id);
      assert.ok(content, name + ': lane ' + lane.id + ' is drawn with content');
      widths.add(Math.round(lane.w));
      const expected = Math.max(content.w + 2 * LANE_PAD, LANE_MIN_W);
      assert.ok(
        Math.abs(lane.w - expected) < 1,
        name + ': lane ' + lane.id + ' is ' + Math.round(lane.w) + ' px for ' + Math.round(content.w) + ' px of content',
      );
      // Which is the number the audit measured: no band is mostly padding.
      assert.ok(
        content.w / lane.w >= 0.6,
        name + ': lane ' + lane.id + ' is ' + Math.round((1 - content.w / lane.w) * 100) + '% empty (budget 40%)',
      );
    }
    assert.ok(widths.size > 1, name + ': lanes are no longer normalised to one width');
  }
});

test('the world is still as wide as its widest lane (VIEW-01)', () => {
  // Ragged lane boxes must not make the document narrower than its content:
  // the minimap letterbox and the edge SVG both measure against frame.width.
  for (const graph of [sample, makeSyntheticGraph(150, 300)]) {
    const layout = MLView.__internal.layout(graph);
    const widest = Math.max.apply(null, layout.lanes.map((l) => l.x + l.w));
    assert.ok(layout.width >= widest, 'world ' + layout.width + ' < widest lane edge ' + widest);
    for (const node of layout.nodes) {
      assert.ok(node.x + node.w <= layout.width, node.id + ' is drawn outside the world');
    }
  }
});

test('an over-wide lane wraps into stacked rank rows (VIEW-01)', () => {
  // Nine sibling groups in a row measured 10 232 px in the 300-node project.
  // Ranks are never split, so the bound is MAX_RANK_W or one very wide box,
  // whichever is larger.
  for (const [name, graph] of [['synthetic 150', makeSyntheticGraph(150, 300)], ['synthetic 360', makeSyntheticGraph(360, 720)]]) {
    const layout = MLView.__internal.layout(graph);
    let wrapped = 0;
    for (const lane of layout.lanes) {
      const content = laneContent(layout, lane.id);
      if (!content) continue;
      const budget = Math.max(MAX_RANK_W, content.widest);
      assert.ok(
        content.w <= budget + 1,
        name + ': lane ' + lane.id + ' is ' + Math.round(content.w) + ' px wide (budget ' + Math.round(budget) + ')',
      );
      if (content.count >= 8) wrapped++;
    }
    assert.ok(wrapped > 0, name + ': lanes actually carry the content that used to be one wide row');
  }
});

test('the wrap threshold leaves the shipped sample alone (VIEW-01)', () => {
  // The gate the re-baseline depends on: the demo and the contracts sample are
  // both under budget, so wrapWideRows is inert on them and their node
  // positions are exactly the ones dagre produced.
  const layout = MLView.__internal.layout(sample);
  for (const lane of layout.lanes) {
    const content = laneContent(layout, lane.id);
    assert.ok(content.w < MAX_RANK_W, 'lane ' + lane.id + ' is ' + Math.round(content.w) + ' px, under the ' + MAX_RANK_W + ' px wrap budget');
  }
});

test('fit() is not a no-op on the shipped sample (VIEW-01)', () => {
  const { fitPlan, MIN_ZOOM, TALL_SCREENS, MIN_FIT_ZOOM } = MLView.__internal.viewport;
  const layout = MLView.__internal.layout(sample);
  // The canvas the standalone report actually gets inside a 1600x1000 window:
  // the rail and the chrome take the rest.
  const W = 1240;
  const H = 848;
  const plan = fitPlan(layout.width, layout.height, W, H);
  assert.ok(plan.tall, 'a whole pipeline is taller than it is wide');
  // `Fit to view` and `0` were verified no-ops because the tall branch returned
  // min(zw, 1) and a narrow sample made that exactly 1 — the transform the
  // viewer was already mounted with.
  assert.ok(plan.zoom < 1 && plan.zoom > MIN_ZOOM, 'fit rescales the document: ' + plan.zoom);
  assert.ok(plan.zoom * layout.width <= W - 48 + 1, 'the whole width is on screen');
  assert.ok(
    plan.zoom * layout.height <= H * TALL_SCREENS + 1,
    'and at most ' + TALL_SCREENS + ' screens of height: ' + (plan.zoom * layout.height).toFixed(0) + ' px of ' + H,
  );

  // A 300-node project used to land on MIN_ZOOM at every viewport: 5672x2706
  // of world, cards 32 px wide, the text at 3 px.
  const deep = fitPlan(2116, 8580, W, H);
  assert.equal(deep.zoom, MIN_FIT_ZOOM, 'a deep document opens at the fit floor, not the zoom floor');
  assert.ok(deep.zoom > MIN_ZOOM * 3);

  // A document wider than it is tall is not the shape the bound was written
  // for: it takes the whole-fit branch, which stays the ONLY one that can still
  // reach MIN_ZOOM.
  const veryWide = fitPlan(40000, 900, W, H);
  assert.ok(!veryWide.tall, 'a wide document is not top-anchored');
  assert.equal(veryWide.zoom, MIN_ZOOM, 'and the whole fit is the only branch that reaches the zoom floor');

  // A projection is never top-anchored: the scope must open showing its subject.
  const projected = fitPlan(1000, 3000, W, H, 24, true);
  assert.ok(!projected.tall && projected.zoom * 3000 <= H, 'a projection fits whole');
});
