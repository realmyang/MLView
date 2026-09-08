/**
 * VIEW-01 geometry probe (development tool, not a gate).
 *
 *   node test/measure_geometry.mjs [graph.json ...]
 *
 * Prints, per document: world size, the zoom `fit()` would choose, and per-lane
 * fill (content width / lane width). The two canvas sizes are the ones Chromium
 * actually gives `.mlv-canvas` inside a 1600x1000 and a 1280x800 window — the
 * chrome and the rail take the rest, so passing the window size here would
 * overstate the zoom by a third.
 */
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample } from './helpers.mjs';

const ctx = await loadBundle();
const { MLView } = ctx;
const { fitPlan } = MLView.__internal.viewport;
const fitZoom = (cw, ch, w, h) => fitPlan(cw, ch, w, h).zoom;

const docs = [];
const args = process.argv.slice(2);
if (args.length === 0) docs.push(['contracts/graph.sample.json', await readSample()]);
for (const path of args) docs.push([path, JSON.parse(await readFile(path, 'utf8'))]);

for (const [name, graph] of docs) {
  const t0 = performance.now();
  const layout = MLView.__internal.layout(graph);
  const ms = performance.now() - t0;
  const lanes = layout.lanes;
  console.log('\n== ' + name + ' == ' + graph.nodes.length + ' nodes / ' + graph.edges.length + ' edges');
  console.log('world ' + Math.round(layout.width) + ' x ' + Math.round(layout.height) +
    '  (aspect ' + (layout.height / layout.width).toFixed(2) + ':1)  layout ' + ms.toFixed(1) + ' ms');
  console.log('fit 1240x848 (a 1600x1000 window) = ' + fitZoom(layout.width, layout.height, 1240, 848).toFixed(3) +
    '   fit 920x648 (a 1280x800 window) = ' + fitZoom(layout.width, layout.height, 920, 648).toFixed(3));
  let worst = 0;
  for (const lane of lanes) {
    const inside = layout.nodes.filter((n) => n.lane === lane.id);
    let min = Infinity;
    let max = -Infinity;
    for (const n of inside) {
      min = Math.min(min, n.x);
      max = Math.max(max, n.x + n.w);
    }
    const content = isFinite(min) ? max - min : 0;
    const fill = content / lane.w;
    worst = Math.max(worst, 1 - fill);
    console.log('  lane ' + lane.id.padEnd(11) + ' w=' + String(Math.round(lane.w)).padStart(6) +
      ' content=' + String(Math.round(content)).padStart(6) +
      ' fill=' + (fill * 100).toFixed(0).padStart(3) + '%  empty=' + ((1 - fill) * 100).toFixed(0) + '%' +
      '  h=' + String(Math.round(lane.h)).padStart(5) + '  boxes=' + inside.length);
  }
  console.log('  worst lane emptiness: ' + (worst * 100).toFixed(0) + '%');
}
