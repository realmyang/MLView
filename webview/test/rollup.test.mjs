/**
 * PERF-04 — the viewer half of the hierarchical rollup (CONTRACTS 11.46).
 *
 * The item's whole point is a DISTINCTION: a capped document used to be a
 * mutilated one and is now a summarised one, and the reader has to be able to
 * tell which they are looking at. So the assertions here are mostly about
 * honesty rather than about pixels:
 *
 *   - a rolled-up card borrows the collapsed-group VISUAL and none of its
 *     affordance, because what it swallowed is not in this document;
 *   - a weighted cable is never thick ALONE — it carries a `x n` pill and says
 *     "weight n" to a screen reader;
 *   - the banner says "rolled up", derives how many were DROPPED from the
 *     analyzer's own count, and says "the document does not say" when it cannot;
 *   - a document that was truncated by an analyzer predating the amendment
 *     keeps the old sentence, because for that document the old sentence is
 *     true;
 *   - an untruncated document draws none of it (11.46 C5).
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();
const { rollup } = (await loadBundle()).MLView.__internal;

/** Two folded cards, two weighted cables, and the cap's own diagnostic. */
const ROLLED = { 'n:1100aa22bb33': 4, 'n:c072e5a41d38': 7 };
const WEIGHTS = { 'e:9f21ab34cd56': 3, 'e:7f0a3b5c1d24': 9 };

function rolledGraph(opts = {}) {
  const g = JSON.parse(JSON.stringify(sample));
  for (const node of g.nodes) if (ROLLED[node.id]) node.rolledUp = ROLLED[node.id];
  for (const edge of g.edges) if (WEIGHTS[edge.id]) edge.weight = WEIGHTS[edge.id];
  g.stats.truncated = true;
  if (opts.diagnostic !== false) {
    g.diagnostics = (g.diagnostics || []).concat([
      {
        kind: 'truncated',
        count: opts.count === undefined ? 13 : opts.count,
        message:
          'node budget 12: 12 node(s) kept. 11 node(s) rolled up and 2 node(s) were dropped.',
      },
    ]);
  }
  return g;
}

async function app(graph) {
  const ctx = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState() {},
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, graph, bridge);
  return { ...ctx, app: instance };
}

const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);

/* ── the two field readers (11.46 B1, B2) ──────────────────────────────── */

test('rolledUp is read only as a positive integer (invariant 1.1/6)', () => {
  assert.equal(rollup.count({ rolledUp: 4 }), 4);
  assert.equal(rollup.count({ rolledUp: 4.7 }), 4, 'floored, never rounded up');
  assert.equal(rollup.count({}), 0, 'absent means zero');
  for (const bad of [-3, 0, 0.5, NaN, Infinity, '5', null, true]) {
    assert.equal(rollup.count({ rolledUp: bad }), 0, 'refuses ' + String(bad));
  }
  assert.equal(rollup.count(null), 0);
});

test('weight is 1 when absent, and a bad value never widens a stroke', () => {
  assert.equal(rollup.edgeWeight({ weight: 9 }), 9);
  assert.equal(rollup.edgeWeight({}), 1, 'absent means one');
  for (const bad of [-2, 0, NaN, '4', null]) assert.equal(rollup.edgeWeight({ weight: bad }), 1);
  assert.equal(rollup.weightStroke(1), rollup.weightStroke(0), 'below the minimum, nothing grows');
  assert.ok(rollup.weightStroke(9) > rollup.weightStroke(2), 'and it grows with the weight');
  assert.ok(rollup.weightStroke(2000) <= 5, 'but it is capped: 2000 is not 2000 px wide');
});

test('a route reports the SUM of the document edges it stands for', () => {
  const byId = new Map([
    ['a', { id: 'a', weight: 3 }],
    ['b', { id: 'b' }],
    ['c', { id: 'c', weight: 9 }],
  ]);
  assert.equal(rollup.routeWeight(['a'], byId), 3);
  assert.equal(rollup.routeWeight(['a', 'b'], byId), 4, 'a plain edge counts one');
  assert.equal(rollup.routeWeight(['a', 'c'], byId), 12);
  assert.equal(rollup.routeWeight(['missing'], byId), 1, 'an unknown id is never zero');
});

/* ── the summary and its arithmetic (11.46 D) ──────────────────────────── */

test('a document with no folded card and no weighted edge has no rollup summary', () => {
  assert.equal(rollup.summary(sample), null, 'the frozen golden is not a capped document');
  const truncatedOnly = JSON.parse(JSON.stringify(sample));
  truncatedOnly.stats.truncated = true;
  assert.equal(
    rollup.summary(truncatedOnly),
    null,
    'stats.truncated ALONE is not the test: an analyzer predating 11.46 really did delete',
  );
});

test('dropped is derived from the diagnostic count, and admitted when it cannot be', () => {
  const full = rollup.summary(rolledGraph());
  assert.equal(full.folded, 11, '4 + 7 nodes folded');
  assert.equal(full.rolled, 2, 'into two cards');
  assert.equal(full.dropped, 2, 'count 13 minus 11 folded');
  assert.equal(full.weighted, 2);
  assert.equal(full.merged, 3 - 1 + (9 - 1), 'connections beyond the one drawn');
  assert.equal(full.maxWeight, 9);

  const noDiag = rollup.summary(rolledGraph({ diagnostic: false }));
  assert.equal(noDiag.dropped, null, 'no diagnostic: the document does not say');

  const impossible = rollup.summary(rolledGraph({ count: 4 }));
  assert.equal(impossible.dropped, null, 'a count below what is visibly folded is not believed');
});

test('the headline says folded, not deleted — and never claims a zero it cannot see', () => {
  assert.match(rollup.headline(rollup.summary(rolledGraph())), /folded, not deleted/);
  assert.match(rollup.headline(rollup.summary(rolledGraph())), /2 node\(s\) were dropped as well/);
  assert.match(
    rollup.headline(rollup.summary(rolledGraph({ diagnostic: false }))),
    /does not say whether anything was dropped/,
  );
  assert.match(rollup.headline(rollup.summary(rolledGraph({ count: 11 }))), /Nothing was dropped/);
});

test('the caveats name every one of 11.46 F that applies, and none that does not', () => {
  const notes = rollup.caveats(rollup.summary(rolledGraph())).join('\n');
  assert.match(notes, /cannot be opened/, 'a rolled-up card has no interior in this document');
  assert.match(notes, /counts CONNECTIONS, not call sites/);
  assert.match(notes, /variable names they disagreed on are gone/);
  assert.match(notes, /badge points at the parent/, 'a finding on a folded node moved');
  assert.match(notes, /heuristic, not[\s\S]*a measurement/, 'the fold order is not validated');
  assert.doesNotMatch(notes, /majority vote/, 'no file summary here, so no vote to disclose');

  const withFile = JSON.parse(JSON.stringify(rolledGraph()));
  withFile.nodes[1].attrs = { ...withFile.nodes[1].attrs, rollup: 'file' };
  const fileNotes = rollup.caveats(rollup.summary(withFile)).join('\n');
  assert.match(fileNotes, /MAJORITY VOTE/, 'a file summary discloses that its stage was a vote');
  assert.ok(rollup.isFileSummary(withFile.nodes[1]));
});

/* ── the card (the collapsed-group visual, and none of its affordance) ─── */

test('a rolled-up card reuses the collapsed-group visual and says how many', async () => {
  const ctx = await app(rolledGraph());
  // `[data-node-id]` on purpose: the LEGEND draws a swatch card carrying the
  // same classes, and a gate that matched it would pass without a diagram.
  const card = ctx.document.querySelector('.mlv-node[data-node-id="n:c072e5a41d38"]');
  assert.ok(card, 'the card is marked with the count it swallowed');
  assert.equal(card.getAttribute('data-rolled-up'), '7');
  assert.ok(card.classList.contains('is-collapsed-group'), 'it borrows the collapsed-group visual');
  assert.ok(card.classList.contains('is-rolled-up'), 'and is still distinguishable from one');
  const chip = card.querySelector('.mlv-chip--rollup');
  assert.ok(chip, 'the count is a chip on the card');
  assert.equal(text(chip), '7 rolled up', 'never "7 nodes" — that is what a group says');
  assert.equal(card.querySelector('.mlv-group__chevron-btn'), null, 'there is nothing to expand');
  assert.match(card.getAttribute('aria-label'), /7 nodes folded into this card, which cannot be opened/);
});

test('a rolled-up unit that kept its ghosts is still an expanded frame that says so', async () => {
  // 11.46 A5: ghosts are never folded, so a unit can swallow its ops and still
  // have a child in the document — and the FRAME then has to carry the count,
  // or the one card standing for four would be the one that says nothing.
  const ctx = await app(rolledGraph());
  const group = ctx.document.querySelector('.mlv-group[data-node-id="n:1100aa22bb33"]');
  assert.ok(group, 'build_loaders() is drawn as an expanded group');
  assert.equal(group.getAttribute('data-rolled-up'), '4');
  assert.equal(text(group.querySelector('.mlv-chip--rollup')), '4 rolled up');
  assert.notEqual(
    text(group.querySelector('.mlv-group__count')),
    '4',
    'the nested count and the folded count are different numbers and are drawn separately',
  );
});

test('a card that swallowed nothing is untouched', async () => {
  const ctx = await app(rolledGraph());
  const plain = Array.from(ctx.document.querySelectorAll('.mlv-node[data-node-id]')).filter(
    (el) => !el.hasAttribute('data-rolled-up'),
  );
  assert.ok(plain.length >= 5, 'most cards are ordinary: ' + plain.length);
  for (const card of plain) {
    assert.equal(card.querySelector('.mlv-chip--rollup'), null);
    assert.doesNotMatch(card.getAttribute('aria-label') || '', /folded into this card/);
  }
});

/* ── the cable ─────────────────────────────────────────────────────────── */

test('a weighted cable is thicker AND carries a pill AND says so out loud', async () => {
  const ctx = await app(rolledGraph());
  const edge = ctx.document.querySelector('[data-edge-weight]');
  assert.ok(edge, 'a weighted edge is marked');
  const weight = Number(edge.getAttribute('data-edge-weight'));
  assert.ok(weight >= rollup.WEIGHT_MIN, 'only 2+ is a weight: ' + weight);
  assert.ok(edge.classList.contains('mlv-edge--weighted'));
  assert.equal(
    edge.style.getPropertyValue('--mlv-edge-w'),
    rollup.weightStroke(weight) + 'px',
    'the stroke rides a custom property, so hover and selection still win',
  );
  const pill = edge.querySelector('.mlv-edge__weight');
  assert.ok(pill, 'never thickness alone');
  assert.equal(text(pill.querySelector('.mlv-edge__weighttext')), rollup.badgeText(weight));
  assert.match(text(pill.querySelector('title')), /counts connections, not call sites/);
  const spoken = edge.querySelector('.mlv-edge__hit').getAttribute('aria-label');
  assert.match(spoken, new RegExp('weight ' + weight));
});

test('an unweighted cable gains nothing', async () => {
  const ctx = await app(rolledGraph());
  const plain = Array.from(ctx.document.querySelectorAll('.mlv-edge[data-edge-id]')).filter(
    (el) => !el.hasAttribute('data-edge-weight'),
  );
  assert.ok(plain.length >= 5, plain.length + ' plain cables');
  for (const edge of plain) {
    assert.equal(edge.querySelector('.mlv-edge__weight'), null);
    assert.equal(edge.style.getPropertyValue('--mlv-edge-w'), '');
  }
});

test('the pill is nudged off the midpoint only when something else is on it', () => {
  const mark = { x: 100, y: 50 };
  const free = rollup.badgeAt(mark, 0, false);
  assert.equal(free.x, 100, 'a free midpoint keeps it');
  assert.equal(free.y, 50);
  const nudged = rollup.badgeAt(mark, 0, true);
  assert.ok(Math.abs(nudged.y - mark.y) > 10, 'a severity glyph pushes it off, along the route normal');
  assert.ok(Number.isFinite(rollup.badgeAt(mark, NaN, true).x), 'a missing angle never yields NaN');
});

/* ── the banner (11.46 D) ──────────────────────────────────────────────── */

test('the banner says rolled up, draws the analyzer sentence, and lists the caveats', async () => {
  const ctx = await app(rolledGraph());
  const banner = ctx.document.querySelector('[data-rollup-banner]');
  assert.ok(banner, 'a rolled-up document gets the rollup banner');
  assert.equal(banner.getAttribute('data-rollup-banner'), '11', 'and it counts what was folded');
  assert.match(text(banner), /Rolled up to 12 nodes/);
  assert.match(text(banner), /node budget 12: 12 node\(s\) kept/, "the analyzer's own sentence, verbatim");
  const notes = banner.querySelector('.mlv-banner__notes');
  assert.ok(notes, 'the caveats are drawn in full, not elided');
  assert.equal(
    notes.querySelectorAll('li').length,
    Number(notes.getAttribute('data-rollup-notes')),
    'every caveat computed is a caveat drawn',
  );
});

test('a truncated document with no rollup evidence keeps the OLD sentence', async () => {
  const g = JSON.parse(JSON.stringify(sample));
  g.stats.truncated = true;
  const ctx = await app(g);
  assert.equal(ctx.document.querySelector('[data-rollup-banner]'), null);
  const banners = text(ctx.document.querySelector('.mlv-banners'));
  assert.match(banners, /Graph truncated at/, 'for that document the old sentence is the true one');
});

test('an untruncated document draws no rollup banner at all (11.46 C5)', async () => {
  const ctx = await app(sample);
  assert.equal(ctx.document.querySelector('[data-rollup-banner]'), null);
  assert.equal(ctx.document.querySelector('[data-rolled-up]'), null);
  assert.equal(ctx.document.querySelector('[data-edge-weight]'), null);
});

/* ── the exported picture must not disagree with the diagram (VIEW-07) ─── */

test('the SVG export draws the same count chip, the same thick stroke, the same pill', async () => {
  const ctx = await app(rolledGraph());
  const svg = ctx.MLView.__internal.exportDiagram.build(rolledGraph(), { region: 'diagram' }).svg;
  assert.match(svg, /data-rolled-up="7"/, 'the picture knows which cards stand for more');
  assert.match(svg, /7 rolled up/, 'and prints the same words as the card');
  assert.match(svg, /data-rolled-up="4"/, 'including on an expanded frame that kept its ghosts');
  assert.match(svg, /data-edge-weight="9"/);
  assert.match(svg, new RegExp('×9'), 'the pill survives into the picture, which cannot be hovered');
  const widths = Array.from(svg.matchAll(/data-edge-ids="[^"]*"[^>]*stroke-width="([\d.]+)"/g)).map((m) =>
    Number(m[1]),
  );
  assert.ok(
    widths.some((w) => w >= rollup.weightStroke(9) - 0.01),
    'a weighted cable is drawn thicker in the export too: ' + widths.join(', '),
  );
});
