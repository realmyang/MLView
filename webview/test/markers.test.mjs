/**
 * Severity markers (spec requirement 3 / R3.1). Three DIFFERENT shapes so
 * severity is never colour-only: circled "i", warning triangle, exclamation
 * octagon. Asserted structurally, plus the aggregation rules.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const ctx = await loadBundle();
const { MLView, document, window } = ctx;
const sample = await readSample();

function shapeD(severity) {
  const glyph = MLView.__internal.severityGlyph(severity, 18, severity + ' severity');
  const path = glyph.querySelector('.mlv-glyph__shape');
  return path.getAttribute('d');
}

test('the three severity shapes are structurally different', () => {
  const low = shapeD('low');
  const medium = shapeD('medium');
  const high = shapeD('high');
  assert.notEqual(low, medium);
  assert.notEqual(medium, high);
  assert.notEqual(low, high);
  // Different silhouettes, not just different numbers: a circle is arcs, the
  // triangle is three long straight runs, the octagon is eight short ones.
  const commands = (d) => d.replace(/[^A-Za-z]/g, '');
  assert.notEqual(commands(low), commands(medium));
  assert.notEqual(commands(medium), commands(high));
  assert.notEqual(commands(low), commands(high));
  assert.ok(/[Aa]/.test(low), 'low is a circle (arc commands)');
  assert.ok(!/[Aa]/.test(high), 'high is an octagon (straight edges only)');
  const highCorners = (high.match(/[HhVvLl]/g) || []).length;
  assert.ok(highCorners >= 6, 'the octagon has its eight edges');
});

test('every marker carries a letter as well as a shape', () => {
  for (const severity of ['low', 'medium', 'high']) {
    const glyph = MLView.__internal.severityGlyph(severity, 18, '');
    const ink = glyph.querySelector('.mlv-glyph__ink');
    assert.ok(ink && ink.getAttribute('d').length > 20, severity + ' has an ink glyph');
  }
});

test('markers announce their severity in words', () => {
  const glyph = MLView.__internal.severityGlyph('high', 18);
  assert.equal(glyph.getAttribute('role'), 'img');
  assert.ok(glyph.getAttribute('aria-label').indexOf('high') >= 0);
});

test('an unknown severity degrades to the low marker instead of throwing', () => {
  const glyph = MLView.__internal.severityGlyph('catastrophic', 18, '');
  assert.equal(glyph.querySelector('.mlv-glyph__shape').getAttribute('d'), shapeD('low'));
});

test('node badges show the highest glyph and the total count', () => {
  const root = document.getElementById('mlview-root');
  const bridge = MLView.bridges.standalone({ theme: 'light' });
  const app = MLView.mount(root, sample, bridge);

  // n:7c1a90b4e2f0 has exactly one issue -> glyph, no count.
  const single = document.querySelector('[data-node-id="n:7c1a90b4e2f0"] .mlv-badge');
  assert.ok(single, 'a node with an issue carries a badge');
  assert.equal(single.querySelector('.mlv-badge__count'), null, 'a single issue shows no count');
  assert.ok(single.getAttribute('aria-label').indexOf('1 issue') >= 0);

  // The train entrypoint group aggregates its subtree upward.
  const group = document.querySelector('[data-node-id="n:5500cc66dd77"] .mlv-cluster');
  assert.ok(group, 'an expanded group header carries the aggregated cluster');
  const label = group.getAttribute('aria-label');
  assert.ok(label.indexOf('highest severity high') >= 0, 'group aggregates to the highest severity present');

  // A node with no issues has no badge.
  assert.equal(document.querySelector('[data-node-id="n:4e8b21c05a97"] .mlv-badge'), null);
  app.destroy();
});

test('a collapsed group carries the aggregated marker cluster', () => {
  const root = document.getElementById('mlview-root');
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => ({
      viewport: { x: 0, y: 0, zoom: 1 },
      selection: null,
      collapsed: ['n:5500cc66dd77'],
      filters: { severities: ['low', 'medium', 'high'], stages: [], showSuppressed: false, query: '' },
      railTab: 'issues',
    }),
  };
  const app = MLView.mount(root, sample, bridge);
  const card = document.querySelector('[data-node-id="n:5500cc66dd77"]');
  assert.ok(card.classList.contains('is-collapsed-group'));
  const cluster = card.querySelector('.mlv-cluster');
  assert.ok(cluster, 'the collapsed card carries the aggregated cluster');
  assert.ok(cluster.getAttribute('aria-label').indexOf('highest severity high') >= 0);
  app.destroy();
});

test('an issue-bearing edge carries a marker at its midpoint', () => {
  const root = document.getElementById('mlview-root');
  const app = MLView.mount(root, sample, MLView.bridges.standalone({ theme: 'light' }));
  const edge = document.querySelector('[data-edge-id="e:4c7d0e2f8a91"]');
  assert.ok(edge, 'the model -> loss edge is drawn');
  assert.equal(edge.getAttribute('data-sev'), 'high');
  const marker = edge.querySelector('.mlv-edge-marker');
  assert.ok(marker, 'the edge carries the severity marker');
  assert.ok(/translate\(/.test(marker.getAttribute('transform')));
  app.destroy();
});

test('lane headers aggregate their band severity counts', () => {
  const root = document.getElementById('mlview-root');
  const app = MLView.mount(root, sample, MLView.bridges.standalone({ theme: 'light' }));
  const lane = document.querySelector('[data-lane-id="train"] .mlv-cluster');
  assert.ok(lane, 'the train lane header shows its counts');
  assert.ok(lane.querySelectorAll('.mlv-cluster__item').length >= 1);
  app.destroy();
});

test('ghost nodes are dashed, labelled "missing", and keep their marker', () => {
  const root = document.getElementById('mlview-root');
  const app = MLView.mount(root, sample, MLView.bridges.standalone({ theme: 'light' }));
  const ghost = document.querySelector('[data-node-id="n:ffee11223344"]');
  assert.ok(ghost.classList.contains('is-ghost'));
  assert.equal(ghost.querySelector('.mlv-node__sub').textContent, 'missing');
  assert.ok(ghost.querySelector('.mlv-badge'), 'the ghost carries the severity marker');
  assert.ok(ghost.getAttribute('aria-label').indexOf('Missing step') === 0);
  app.destroy();
});

test('filtering a severity removes its badges but keeps the node in place', () => {
  const root = document.getElementById('mlview-root');
  const app = MLView.mount(root, sample, MLView.bridges.standalone({ theme: 'light' }));
  const before = document.querySelector('[data-node-id="n:7c1a90b4e2f0"]');
  const beforeBox = before.style.left + ',' + before.style.top;
  assert.ok(before.querySelector('.mlv-badge'));
  app.setFilters({ severities: ['high'] });
  const after = document.querySelector('[data-node-id="n:7c1a90b4e2f0"]');
  assert.equal(after.querySelector('.mlv-badge'), null, 'medium badge is gone');
  assert.equal(after.style.left + ',' + after.style.top, beforeBox, 'the node did not move');
  app.destroy();
});
