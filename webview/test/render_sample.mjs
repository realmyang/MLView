/**
 * Renders contracts/graph.sample.json through the built bundle in jsdom and
 * prints a plain-text summary — lanes, node positions, edges and marker counts.
 *
 *   npm run render-sample
 *
 * This is the integrator's quick "did the renderer actually draw the document"
 * check without opening a browser.
 */

import { loadBundle, readSample } from './helpers.mjs';

const out = (line) => process.stdout.write(line + '\n');

const ctx = await loadBundle();
const sample = await readSample();
const { MLView, document } = ctx;

const bridge = MLView.bridges.standalone({ theme: 'light' });
const root = document.getElementById('mlview-root');
const app = MLView.mount(root, sample, bridge);
const layout = MLView.__internal.layout(sample);

out('MLView renderer ' + MLView.version + '  ·  schema ' + sample.schemaVersion + '  ·  ' + sample.workspace.root);
out('graph: ' + sample.nodes.length + ' nodes, ' + sample.edges.length + ' edges, ' + sample.issues.length + ' issues');
out('canvas: ' + layout.width + ' x ' + layout.height + ' px');
out('');

out('LANES (present stages, top to bottom)');
for (const lane of layout.lanes) {
  const band = document.querySelector('[data-lane-id="' + lane.id + '"]');
  const cluster = band ? band.querySelector('.mlv-cluster') : null;
  const counts = cluster ? cluster.getAttribute('aria-label') : 'no issues';
  out(
    '  ' +
      lane.id.padEnd(11) +
      'y=' + String(lane.y).padStart(5) +
      '  h=' + String(lane.h).padStart(4) +
      '  ' + (band ? band.querySelector('.mlv-lane__count').textContent : '') +
      '  [' + counts + ']',
  );
}
const absent = sample.stages.filter((s) => !s.present).map((s) => s.label);
out('  not detected: ' + (absent.length ? absent.join(', ') : '(none)'));
out('');

out('NODES');
for (const node of layout.nodes) {
  const element = document.querySelector('[data-node-id="' + node.id + '"]');
  const source = sample.nodes.find((n) => n.id === node.id);
  const badge = element ? element.querySelector('.mlv-badge, .mlv-cluster') : null;
  const flags = [];
  if (node.isGroup) flags.push(node.collapsed ? 'collapsed-group' : 'group');
  if (source && source.ghost) flags.push('ghost');
  if (source && source.dynamic) flags.push('dynamic');
  out(
    '  ' + node.id +
      '  ' + node.lane.padEnd(11) +
      ' (' + String(node.x).padStart(5) + ',' + String(node.y).padStart(5) + ') ' +
      String(node.w) + 'x' + String(node.h) +
      '  ' + (source ? source.label : '').slice(0, 34).padEnd(34) +
      (badge ? ' <' + badge.getAttribute('aria-label') + '>' : '') +
      (flags.length ? ' ' + flags.join(',') : ''),
  );
}
out('');

out('EDGES');
for (const edge of layout.edges) {
  const element = document.querySelector('[data-edge-id="' + edge.id + '"]');
  const severity = element ? element.getAttribute('data-sev') : null;
  const shape = edge.back ? 'loop' : edge.crossLane ? 'cross-lane' : 'in-lane';
  out(
    '  ' + edge.id +
      '  ' + edge.kind.padEnd(8) +
      shape.padEnd(11) +
      edge.points.length + ' pts' +
      (edge.count > 1 ? '  x' + edge.count : '') +
      (severity ? '  marker=' + severity : ''),
  );
}
out('');

const glyphCount = (severity) => document.querySelectorAll('.mlv-glyph--' + severity).length;
out('MARKERS drawn (canvas + rail + chrome)');
out('  high   ' + glyphCount('high'));
out('  medium ' + glyphCount('medium'));
out('  low    ' + glyphCount('low'));
out('  node badges ' + document.querySelectorAll('.mlv-badge').length + ', clusters ' + document.querySelectorAll('.mlv-cluster').length + ', edge markers ' + document.querySelectorAll('.mlv-edge-marker').length);
out('');
out('RAIL');
out('  issue rows ' + document.querySelectorAll('[data-issue-id]').length);
out('  outline items ' + document.querySelectorAll('[data-outline-id]').length);
out('  banners ' + document.querySelectorAll('.mlv-banner').length + ', chips ' + document.querySelectorAll('.mlv-chiprow .mlv-chip').length);
out('  status: ' + document.querySelector('.mlv-status').textContent);

app.destroy();
