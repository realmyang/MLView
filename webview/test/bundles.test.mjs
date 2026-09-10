/**
 * VIEW-04 — bundle and order the cross-lane channel.
 *
 * 160 of 230 connections leave their lane, 100 skip one, and every skipping hop
 * funnelled through a flat 56 px channel that `routeCrossLane` fanned out at
 * `n * 7` with no bound — roughly twenty near-parallel vertical runs, the
 * seventh of them drawn straight through the first column of lane boxes. This
 * file gates the replacement: one trunk per (source lane, target lane) pair,
 * members ordered by the y of their target, the channel reserved by the number
 * of lane PAIRS rather than the number of edges, and — the hard constraint —
 * every per-edge `points` array and every per-edge `d` left exactly as the
 * router produced it, because the flow charge and the SVG export read them.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, makeSyntheticGraph, WEBVIEW_ROOT } from './helpers.mjs';

const ctx = await loadBundle();
const { MLView } = ctx;
const sample = await readSample();
const devCss = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css'), 'utf8');

const CORPORA = [
  ['sample', sample],
  ['synthetic 150', makeSyntheticGraph(150, 300)],
  ['synthetic 300', makeSyntheticGraph(300, 600)],
];

const layoutOf = (graph, collapsed) => MLView.__internal.layout(graph, collapsed);

/** Distinct ordered stage pairs that skip a lane, computed from the document. */
function skippingPairs(graph, layout) {
  const order = new Map(layout.lanes.map((l, i) => [l.id, i]));
  const stage = new Map(graph.nodes.map((n) => [n.id, n.stage]));
  const keys = new Set();
  for (const e of graph.edges) {
    if (e.kind === 'control' && e.subkind === 'back') continue;
    const a = order.get(stage.get(e.source));
    const b = order.get(stage.get(e.target));
    if (a === undefined || b === undefined) continue;
    if (Math.abs(a - b) > 1) keys.add(stage.get(e.source) + '>' + stage.get(e.target));
  }
  return keys;
}

/* ── the hard constraint: routes are untouched ───────────────────────────── */

test('every routed edge still owns its points array and its d (VIEW-04)', () => {
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const seen = new Set();
    for (const edge of layout.edges) {
      assert.ok(edge.points.length >= 2, name + ': ' + edge.id + ' has ' + edge.points.length + ' points');
      assert.ok(edge.d.indexOf('M ') === 0, name + ': ' + edge.id + ' has no path data');
      // The `d` starts at points[0] and ends at the last point: a bundle that
      // had rewritten the polyline into a shared trunk would break exactly this.
      const first = edge.points[0];
      const last = edge.points[edge.points.length - 1];
      assert.ok(edge.d.indexOf('M ' + first.x + ' ' + first.y) === 0, name + ': ' + edge.id + ' does not start at its own first point');
      assert.ok(edge.d.endsWith('L ' + last.x + ' ' + last.y), name + ': ' + edge.id + ' does not end at its own last point');
      assert.ok(!seen.has(edge.id), name + ': ' + edge.id + ' was routed twice');
      seen.add(edge.id);
    }
  }
});

test('bundling is a second drawing, not a re-route: the layout is deterministic (VIEW-04)', () => {
  for (const [name, graph] of CORPORA) {
    const a = layoutOf(graph);
    const b = layoutOf(graph);
    assert.equal(JSON.stringify(a), JSON.stringify(b), name + ': two layouts of one document disagree');
  }
});

test('buildBundles is pure over the routes it reads (VIEW-04)', () => {
  // The bundle builder is handed the live `RoutedEdge[]`; running it twice must
  // leave both the routes and its own answer identical.
  const layout = layoutOf(sample);
  const before = JSON.stringify(layout.edges);
  const one = JSON.stringify(layout.bundles);
  const again = layoutOf(sample);
  assert.equal(JSON.stringify(again.edges), before);
  assert.equal(JSON.stringify(again.bundles), one);
});

/* ── one trunk per lane pair ─────────────────────────────────────────────── */

test('a bundle is one lane pair with two or more members (VIEW-04)', () => {
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const ids = new Set();
    const memberOf = new Map();
    for (const bundle of layout.bundles) {
      assert.ok(!ids.has(bundle.id), name + ': two bundles claim ' + bundle.id);
      ids.add(bundle.id);
      // VIEW-R3: a gutter group that covers two disjoint stretches of the gutter
      // draws one trunk per stretch, and `part` numbers them inside the pair.
      assert.ok(Number.isInteger(bundle.part) && bundle.part >= 0, name + ': ' + bundle.id + ' has no part number');
      assert.equal(
        bundle.id,
        'bundle:' + bundle.sourceLane + '>' + bundle.targetLane + (bundle.part ? '#' + bundle.part : ''),
      );
      if (bundle.part) assert.equal(bundle.axis, 'x', name + ': only a gutter group splits into sub-trunks');
      assert.ok(bundle.count >= 2, name + ': ' + bundle.id + ' bundles ' + bundle.count + ' route(s)');
      assert.ok(bundle.edgeCount >= bundle.count, name + ': ' + bundle.id + ' carries fewer edges than routes');
      assert.equal(bundle.memberIds.length, bundle.count);
      for (const id of bundle.memberIds) {
        assert.ok(!memberOf.has(id), name + ': ' + id + ' is in two bundles');
        memberOf.set(id, bundle.id);
      }
      // Two spurs per member — one into the trunk's head, one out of its tail —
      // minus any that degenerated to a point because the member IS the shoulder.
      assert.ok(bundle.spurs.length <= 2 * bundle.count, name + ': ' + bundle.id + ' drew more spurs than shoulders');
    }
    // Every member really does belong to that lane pair.
    const laneOf = new Map(layout.nodes.map((n) => [n.id, n.lane]));
    const byId = new Map(layout.edges.map((e) => [e.id, e]));
    const docById = new Map(graph.edges.map((e) => [e.id, e]));
    for (const [routeId, bundleId] of memberOf) {
      const route = byId.get(routeId);
      const doc = docById.get(route.ids[0]);
      assert.ok(route.crossLane, name + ': ' + routeId + ' is bundled but does not leave its lane');
      assert.equal(route.trunk.key, bundleId.slice('bundle:'.length).replace(/#\d+$/, ''));
      const s = laneOf.get(doc.source);
      const t = laneOf.get(doc.target);
      if (s && t) assert.equal(s + '>' + t, route.trunk.key, name + ': ' + routeId + ' is in the wrong lane pair');
    }
  }
});

test('a one-member lane pair is drawn as an individual stroke (VIEW-04)', () => {
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const size = new Map();
    for (const edge of layout.edges) {
      if (!edge.trunk) continue;
      size.set(edge.trunk.key, (size.get(edge.trunk.key) || 0) + 1);
    }
    const drawn = new Set(layout.bundles.map((b) => b.id.slice('bundle:'.length).replace(/#\d+$/, '')));
    for (const [key, n] of size) {
      if (n === 1) assert.ok(!drawn.has(key), name + ': ' + key + ' has one member and was still bundled');
    }
  }
});

/* ── barycentre order ────────────────────────────────────────────────────── */

test("a pair's members leave the trunk in the order their targets are stacked (VIEW-04)", () => {
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const box = new Map(layout.nodes.map((n) => [n.id, n]));
    const doc = new Map(graph.edges.map((e) => [e.id, e]));
    const byId = new Map(layout.edges.map((e) => [e.id, e]));
    for (const bundle of layout.bundles) {
      let previous = -Infinity;
      for (const id of bundle.memberIds) {
        const route = byId.get(id);
        const target = box.get(doc.get(route.ids[0]).target);
        if (!target) continue;
        const y = target.y + target.h / 2;
        assert.ok(
          y >= previous - 0.01,
          name + ': ' + bundle.id + ' leaves at y ' + y.toFixed(1) + ' after ' + previous.toFixed(1) + ' — the spurs braid',
        );
        previous = y;
      }
      // And the index the router stamped rises with the order they are listed in.
      // A sub-trunk holds a SUBSEQUENCE of its pair's members (VIEW-R3), so the
      // claim is monotonicity, not identity — the spurs must not braid.
      let last = -1;
      for (const id of bundle.memberIds) {
        const index = byId.get(id).trunk.index;
        assert.ok(index > last, name + ': ' + bundle.id + ' lists trunk index ' + index + ' after ' + last);
        last = index;
      }
    }
  }
});

test('trunks nest rather than braid (VIEW-04)', () => {
  // The precise claim, and the only one a single-column channel can honour: when
  // one trunk's vertical span CONTAINS another's, the containing trunk takes the
  // outer slot and the two never cross. Two hops whose spans merely INTERLEAVE
  // -- lanes 0..4 against lanes 1..5 -- cannot be nested by any ordering, so
  // they are counted and reported rather than asserted away.
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const trunks = layout.bundles.filter((b) => b.axis === 'y');
    let interleaved = 0;
    for (let i = 0; i < trunks.length; i++) {
      for (let j = i + 1; j < trunks.length; j++) {
        const a = span(trunks[i]);
        const b = span(trunks[j]);
        const nested = (a.lo <= b.lo && a.hi >= b.hi) || (b.lo <= a.lo && b.hi >= a.hi);
        const cross = polylinesCross(trunks[i].trunk, trunks[j].trunk);
        if (nested) {
          assert.ok(!cross, name + ': ' + trunks[i].id + ' and ' + trunks[j].id + ' nest but still cross');
        } else if (cross) {
          interleaved++;
        }
      }
    }
    const total = (trunks.length * (trunks.length - 1)) / 2;
    assert.ok(
      total === 0 || interleaved / total < 0.5,
      name + ': ' + interleaved + ' of ' + total + ' trunk pairs cross, all of them span-interleaved',
    );
  }
});

/* ── the channel is reserved by pairs, not by edges ──────────────────────── */

test('the channel is widened by lane PAIRS and never by more edges (VIEW-04)', () => {
  const { CHANNEL_PAD_L, CHANNEL_PAD_R, CHANNEL_PAIR_STEP, CHANNEL_MAX_W } = MLView.__internal.layoutConstants;
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const pairs = skippingPairs(graph, layout);
    assert.equal(layout.channel.pairs, pairs.size, name + ': the frame counted ' + layout.channel.pairs + ' pairs, the document has ' + pairs.size);
    const wanted = CHANNEL_PAD_L + pairs.size * CHANNEL_PAIR_STEP + CHANNEL_PAD_R;
    assert.equal(layout.channel.w, pairs.size ? Math.min(wanted, CHANNEL_MAX_W) : 0, name + ': channel is ' + layout.channel.w + ' px');
  }

  // The regression the item names: N connections between the SAME two lanes must
  // not widen the channel at all. Duplicating one skipping edge twenty times
  // leaves the world exactly as wide as it was.
  const base = layoutOf(sample);
  const grown = JSON.parse(JSON.stringify(sample));
  const skipper = grown.edges.find((e) => {
    const order = new Map(base.lanes.map((l, i) => [l.id, i]));
    const stage = new Map(grown.nodes.map((n) => [n.id, n.stage]));
    return Math.abs(order.get(stage.get(e.source)) - order.get(stage.get(e.target))) > 1;
  });
  assert.ok(skipper, 'the sample has a hop that skips a lane');
  for (let i = 0; i < 20; i++) {
    const clone = JSON.parse(JSON.stringify(skipper));
    clone.id = 'e:' + 'cafe'.repeat(2) + String(2000 + i);
    clone.label = 'dup' + i;
    grown.edges.push(clone);
  }
  const after = layoutOf(grown);
  assert.equal(after.channel.w, base.channel.w, 'twenty more edges on one lane pair widened the channel');
  assert.equal(after.width, base.width, 'and made the world wider');
});

test('every channel trunk stays inside the reserved channel (VIEW-04)', () => {
  // The old fan put the seventh member of a lane pair at x = 90 in a channel
  // that ends at 88 — i.e. through the first column of lane boxes.
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    if (!layout.channel.w) continue;
    const laneX = Math.min.apply(null, layout.lanes.map((l) => l.x));
    const byId = new Map(layout.edges.map((e) => [e.id, e]));
    for (const bundle of layout.bundles) {
      if (bundle.axis !== 'y') continue;
      const x = bundle.trunk[1].x;
      assert.ok(x >= layout.channel.x - 0.01, name + ': trunk at ' + x + ' is left of the channel');
      assert.ok(x <= laneX - 8, name + ': trunk at ' + x + ' is inside the lane boxes (lane starts at ' + laneX + ')');
      // Every member shares that one x — that is what makes it a trunk.
      for (const id of bundle.memberIds) {
        const route = byId.get(id);
        assert.equal(route.points[route.trunk.joinFrom].x, x, name + ': ' + id + ' runs its own column');
        assert.equal(route.points[route.trunk.joinTo].x, x);
      }
    }
  }
});

test('a member never splays out of the corridor it was reserved in (VIEW-04)', () => {
  const { BUNDLE_MEMBER_SPREAD } = MLView.__internal.layoutConstants;
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    for (const edge of layout.edges) {
      if (!edge.trunk) continue;
      const shoulder = edge.points[edge.trunk.joinFrom];
      const exit = edge.points[edge.trunk.joinTo];
      assert.ok(
        Math.abs(shoulder.y - edge.trunk.entryY) <= BUNDLE_MEMBER_SPREAD + 0.01,
        name + ': ' + edge.id + ' enters ' + Math.abs(shoulder.y - edge.trunk.entryY).toFixed(1) + ' px off its gutter',
      );
      assert.ok(
        Math.abs(exit.y - edge.trunk.exitY) <= BUNDLE_MEMBER_SPREAD + 0.01,
        name + ': ' + edge.id + ' leaves ' + Math.abs(exit.y - edge.trunk.exitY).toFixed(1) + ' px off its gutter',
      );
    }
  }
});

/* ── the number the item exists for ──────────────────────────────────────── */

test('bundling cuts the crossings the reader actually sees (VIEW-04)', () => {
  // Measured with the audit's own method: sample each polyline into 9 points and
  // count the pairs of DIFFERENT strokes whose segments properly intersect.
  // `routes` is every cable drawn separately, `drawn` is what a collapsed
  // diagram puts on screen — trunks, spurs and the cables nothing bundled.
  for (const [name, graph, budget] of [
    // VIEW-R3 re-baselines both: the union trunk bundles every gutter group the
    // intersection rule silently dropped, so the measured numbers fell to 0.64
    // and 24.77 per edge (the pre-fix answer, 30.47 on synthetic 300, now fails).
    ['sample', sample, 1.0],
    ['synthetic 300', makeSyntheticGraph(300, 600), 27],
  ]) {
    const layout = layoutOf(graph);
    const routes = crossings(layout.edges.map((e) => e.points));
    const drawn = crossings(drawnPolylines(layout));
    const perRoute = routes / layout.edges.length;
    const perDrawn = drawn / layout.edges.length;
    assert.ok(perDrawn < perRoute, name + ': bundling did not reduce crossings (' + perDrawn.toFixed(2) + ' vs ' + perRoute.toFixed(2) + ')');
    assert.ok(
      perDrawn <= budget,
      name + ': ' + perDrawn.toFixed(2) + ' crossings per edge on screen, budget ' + budget,
    );
  }
});

/* ── VIEW-R3: no group is silently left unbundled ────────────────────────── */

/** Every usable member of every trunk group, keyed by lane pair. */
function trunkGroups(layout) {
  const groups = new Map();
  for (const edge of layout.edges) {
    const ref = edge.trunk;
    if (!ref) continue;
    if (ref.joinFrom < 1 || ref.joinTo <= ref.joinFrom) continue;
    if (ref.joinTo + 1 > edge.points.length - 1) continue;
    const list = groups.get(ref.key);
    if (list) list.push(edge);
    else groups.set(ref.key, [edge]);
  }
  return groups;
}

/** One member's stretch of the gutter it crosses. */
function gutterSpan(edge) {
  const a = edge.points[edge.trunk.joinFrom].x;
  const b = edge.points[edge.trunk.joinTo].x;
  return { lo: Math.min(a, b), hi: Math.max(a, b) };
}

/** Maximal clusters of spans that chain into one contiguous stretch. */
function overlapClusters(spans) {
  const sorted = spans.slice().sort((a, b) => a.lo - b.lo || a.hi - b.hi);
  const out = [];
  let current = [];
  let reach = -Infinity;
  for (const span of sorted) {
    if (current.length && span.lo > reach) {
      out.push(current);
      current = [];
    }
    current.push(span);
    reach = current.length === 1 ? span.hi : Math.max(reach, span.hi);
  }
  if (current.length) out.push(current);
  return out;
}

test('a trunk group of two or more is bundled, or counted with a reason (VIEW-04, VIEW-R3)', () => {
  // The regression this exists for: the trunk used to be the INTERSECTION of
  // every member's x-span, so a wide gutter group's common ground was empty and
  // the WHOLE group fell back to N near-parallel runs — 150 of 300 routes on
  // `synthetic 300`, 250 of 375 on a capped 525-file repo, all-or-nothing and
  // worst on the biggest groups. Nothing asserted it, because the old tests only
  // described bundles that WERE built.
  const { BUNDLE_MIN_TRUNK } = MLView.__internal.layoutConstants;
  for (const [name, graph, budget] of [
    ['sample', sample, 2],
    ['synthetic 150', makeSyntheticGraph(150, 300), 0],
    ['synthetic 300', makeSyntheticGraph(300, 600), 2],
  ]) {
    const layout = layoutOf(graph);
    const bundled = new Set();
    for (const bundle of layout.bundles) for (const id of bundle.memberIds) bundled.add(id);
    let usable = 0;
    let residue = 0;
    for (const [key, members] of trunkGroups(layout)) {
      usable += members.length;
      if (members.length < 2) continue;
      const stray = members.filter((e) => !bundled.has(e.id));
      residue += stray.length;
      if (!stray.length) continue;
      // A member may only be left out for one of the two stated reasons.
      const ref = members[0].trunk;
      if (ref.axis === 'y') {
        assert.ok(
          Math.abs(ref.exitY - ref.entryY) < BUNDLE_MIN_TRUNK,
          name + ': ' + key + ' left ' + stray.length + ' of ' + members.length + ' channel members unbundled',
        );
        continue;
      }
      const spans = new Map(members.map((e) => [e.id, gutterSpan(e)]));
      const clusters = overlapClusters(members.map((e) => Object.assign({ id: e.id }, spans.get(e.id))));
      for (const edge of stray) {
        const cluster = clusters.find((c) => c.some((sp) => sp.id === edge.id));
        const lo = Math.min.apply(null, cluster.map((sp) => sp.lo));
        const hi = Math.max.apply(null, cluster.map((sp) => sp.hi));
        assert.ok(
          cluster.length < 2 || hi - lo < BUNDLE_MIN_TRUNK,
          name + ': ' + key + ' left ' + edge.id + ' out of a ' + cluster.length + '-member run ' +
            (hi - lo).toFixed(1) + ' px long',
        );
      }
    }
    assert.ok(
      residue <= budget,
      name + ': ' + residue + ' of ' + usable + ' cross-lane routes are drawn as their own run, budget ' + budget,
    );
  }
});

test('a gutter trunk is never drawn across ground no member covers (VIEW-04, VIEW-R3)', () => {
  // The price of a union trunk, bounded: the trunk may run further than any one
  // cable, but every x on it lies inside at least one member's own gutter run,
  // and it never reaches past the outermost of them.
  for (const [name, graph] of CORPORA) {
    const layout = layoutOf(graph);
    const byId = new Map(layout.edges.map((e) => [e.id, e]));
    for (const bundle of layout.bundles) {
      if (bundle.axis !== 'x') continue;
      const spans = bundle.memberIds.map((id) => gutterSpan(byId.get(id)));
      const lo = Math.min.apply(null, spans.map((s) => s.lo));
      const hi = Math.max.apply(null, spans.map((s) => s.hi));
      const ends = bundle.trunk.map((p) => p.x);
      assert.ok(Math.min.apply(null, ends) >= lo - 0.01, name + ': ' + bundle.id + ' starts left of every member');
      assert.ok(Math.max.apply(null, ends) <= hi + 0.01, name + ': ' + bundle.id + ' ends right of every member');
      // Contiguous: sweep the members and never leave a gap inside the trunk.
      const sorted = spans.slice().sort((a, b) => a.lo - b.lo);
      let reach = sorted[0].hi;
      for (const span of sorted.slice(1)) {
        assert.ok(
          span.lo <= reach + 0.01,
          name + ': ' + bundle.id + ' spans a ' + (span.lo - reach).toFixed(1) + ' px gap no cable crosses',
        );
        reach = Math.max(reach, span.hi);
      }
      // Every member really does touch the trunk it is drawn onto.
      for (const id of bundle.memberIds) {
        const edge = byId.get(id);
        for (const j of [edge.trunk.joinFrom, edge.trunk.joinTo]) {
          const x = edge.points[j].x;
          assert.ok(
            x >= Math.min.apply(null, ends) - 0.01 && x <= Math.max.apply(null, ends) + 0.01,
            name + ': ' + id + ' joins its trunk at ' + x + ', outside [' + ends + ']',
          );
        }
        // And the spur that carries it there is a drop of at most the splay.
        const { BUNDLE_MEMBER_SPREAD } = MLView.__internal.layoutConstants;
        for (const spur of bundle.spurs) {
          if (spur.id !== id) continue;
          const y = spur.points.map((p) => p.y);
          assert.ok(
            Math.abs(bundle.trunk[0].y - (spur.side === 'in' ? y[y.length - 1] : y[0])) < 0.01,
            name + ': ' + id + "'s " + spur.side + ' spur does not meet the trunk',
          );
        }
        assert.ok(BUNDLE_MEMBER_SPREAD > 0);
      }
    }
  }
});

/* ── the DOM half ────────────────────────────────────────────────────────── */

async function app(graph = sample) {
  const fresh = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = fresh.document.getElementById('mlview-root');
  fresh.MLView.mount(root, graph, bridge);
  return fresh;
}

test('the trunks are drawn, and their members are transparent until asked for (VIEW-04)', async () => {
  const view = await app();
  const layout = layoutOf(sample);
  const drawn = view.document.querySelectorAll('.mlv-bundle');
  assert.equal(drawn.length, layout.bundles.length, 'one <g class="mlv-bundle"> per planned bundle');
  assert.ok(drawn.length > 0, 'the shipped sample has at least one cross-lane trunk');

  for (const g of drawn) {
    assert.equal(g.querySelectorAll('.mlv-bundle__trunk').length, 1, 'exactly one trunk per bundle');
    assert.ok(g.querySelectorAll('.mlv-bundle__spur').length >= 2, 'and a spur at each end');
    const badge = g.querySelector('.mlv-bundle__badge-text');
    assert.ok(badge, 'the member-count badge is drawn');
    assert.equal(badge.textContent, g.getAttribute('data-count'), 'the badge says what the group holds');
    const title = g.querySelector('title');
    assert.ok(title && title.textContent.indexOf('connections from') > 0, 'and it names both lanes: ' + (title && title.textContent));
  }

  const bundle = layout.bundles[0];
  for (const id of bundle.memberIds) {
    const g = view.document.querySelector('[data-edge-id="' + id + '"]');
    assert.ok(g, 'the member cable is still in the DOM');
    assert.ok(g.classList.contains('is-bundled'), id + ' is not marked as bundled');
    // It keeps everything the charge and the export read.
    assert.ok(g.querySelector('.mlv-edge__path').getAttribute('id'), 'and keeps its motion-path id');
    assert.ok(g.querySelector('.mlv-edge__hit'), 'and its hit stroke, so the pointer can still find it');
  }
});

test('touching one cable opens the trunk it belongs to (VIEW-04)', async () => {
  const view = await app();
  const layout = layoutOf(sample);
  const bundle = layout.bundles[0];
  const memberId = bundle.memberIds[0];
  const g = view.document.querySelector('[data-edge-id="' + memberId + '"]');
  const set = view.document.querySelector('[data-bundle-id="' + bundle.id + '"]');
  assert.ok(!set.classList.contains('is-expanded'), 'it starts collapsed');

  g.querySelector('.mlv-edge__hit').dispatchEvent(new view.window.Event('focus', { bubbles: false }));
  assert.ok(set.classList.contains('is-expanded'), 'focusing a member expands its trunk');
  for (const id of bundle.memberIds) {
    assert.ok(
      !view.document.querySelector('[data-edge-id="' + id + '"]').classList.contains('is-bundled'),
      id + ' is still hidden while its trunk is open',
    );
  }

  g.querySelector('.mlv-edge__hit').dispatchEvent(new view.window.Event('blur', { bubbles: false }));
  assert.ok(!set.classList.contains('is-expanded'), 'and it closes again');
  assert.ok(view.document.querySelector('[data-edge-id="' + memberId + '"]').classList.contains('is-bundled'));
});

test('a bundle never hides a finding (VIEW-04)', () => {
  // The one thing a decluttering device must not do. The stroke and the variable
  // name go; the severity glyph does not, and the trunk carries the worst
  // severity of the cables it stands for.
  assert.ok(
    /\.mlv-canvas \.mlv-edge\.is-bundled \.mlv-edge__path,\s*\.mlv-canvas \.mlv-edge\.is-bundled \.mlv-edge-label \{[^}]*opacity:\s*0/.test(devCss),
    'the collapsed member fades its stroke and its label',
  );
  assert.equal(
    /\.mlv-edge\.is-bundled[^{]*\.mlv-edge-marker\b/.test(devCss),
    false,
    'and NOT its severity marker',
  );
  assert.ok(/\.mlv-bundle\.has-issue \.mlv-bundle__trunk/.test(devCss), 'the trunk takes the severity colour');
});

test('every drawn bundle carries the worst severity of its members (VIEW-04)', async () => {
  const view = await app();
  const layout = layoutOf(sample);
  const rank = { high: 0, medium: 1, low: 2 };
  for (const bundle of layout.bundles) {
    let worst = null;
    for (const id of bundle.memberIds) {
      const g = view.document.querySelector('[data-edge-id="' + id + '"]');
      const sev = g.getAttribute('data-sev');
      if (sev && (worst === null || rank[sev] < rank[worst])) worst = sev;
    }
    const set = view.document.querySelector('[data-bundle-id="' + bundle.id + '"]');
    assert.equal(set.getAttribute('data-sev'), worst, bundle.id + ' shows ' + set.getAttribute('data-sev') + ', its members carry ' + worst);
  }
});

/* ── helpers ─────────────────────────────────────────────────────────────── */

function span(bundle) {
  const ys = bundle.trunk.map((p) => p.y);
  return { lo: Math.min.apply(null, ys), hi: Math.max.apply(null, ys) };
}

function drawnPolylines(layout) {
  const bundled = new Set();
  const out = [];
  for (const bundle of layout.bundles) {
    for (const id of bundle.memberIds) bundled.add(id);
    out.push(bundle.trunk);
    for (const spur of bundle.spurs) out.push(spur.points);
  }
  for (const edge of layout.edges) if (!bundled.has(edge.id)) out.push(edge.points);
  return out;
}

function sample9(points) {
  const segs = [];
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const d = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    segs.push(d);
    total += d;
  }
  if (total === 0) return points.slice(0, 1);
  const out = [];
  for (let k = 0; k < 9; k++) {
    let want = (total * k) / 8;
    let i = 1;
    while (i < points.length && want > segs[i - 1]) {
      want -= segs[i - 1];
      i++;
    }
    if (i >= points.length) {
      out.push(points[points.length - 1]);
      continue;
    }
    const f = segs[i - 1] === 0 ? 0 : want / segs[i - 1];
    out.push({ x: points[i - 1].x + (points[i].x - points[i - 1].x) * f, y: points[i - 1].y + (points[i].y - points[i - 1].y) * f });
  }
  return out;
}

function turn(o, a, b) {
  return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

function segmentsCross(p1, p2, p3, p4) {
  const e = 1e-9;
  const d1 = turn(p3, p4, p1);
  const d2 = turn(p3, p4, p2);
  const d3 = turn(p1, p2, p3);
  const d4 = turn(p1, p2, p4);
  return ((d1 > e && d2 < -e) || (d1 < -e && d2 > e)) && ((d3 > e && d4 < -e) || (d3 < -e && d4 > e));
}

function polylinesCross(a, b) {
  for (let i = 1; i < a.length; i++) {
    for (let j = 1; j < b.length; j++) if (segmentsCross(a[i - 1], a[i], b[j - 1], b[j])) return true;
  }
  return false;
}

function crossings(polylines) {
  const polys = polylines.map(sample9);
  let pairs = 0;
  for (let i = 0; i < polys.length; i++) {
    for (let j = i + 1; j < polys.length; j++) if (polylinesCross(polys[i], polys[j])) pairs++;
  }
  return pairs;
}
