/**
 * VIEW-04 crossing probe (development tool, not a gate).
 *
 *   node crossings.mjs [graph.json ...]
 *
 * Reproduces the audit's method: sample every routed polyline into 9 points,
 * then count segment-pair intersections between DIFFERENT edges. Reports both
 * the number of crossing edge PAIRS (the audit's 226 / 45 = 5.0) and the raw
 * segment intersections.
 */
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, makeSyntheticGraph } from './helpers.mjs';

const ctx = await loadBundle();
const { MLView } = ctx;

function sample9(points) {
  let total = 0;
  const segs = [];
  for (let i = 1; i < points.length; i++) {
    const d = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    segs.push(d);
    total += d;
  }
  const out = [];
  const N = 9;
  if (total === 0) return points.slice(0, 1);
  for (let k = 0; k < N; k++) {
    let want = (total * k) / (N - 1);
    let i = 1;
    while (i < points.length && want > segs[i - 1]) { want -= segs[i - 1]; i++; }
    if (i >= points.length) { out.push(points[points.length - 1]); continue; }
    const f = segs[i - 1] === 0 ? 0 : want / segs[i - 1];
    out.push({ x: points[i - 1].x + (points[i].x - points[i - 1].x) * f, y: points[i - 1].y + (points[i].y - points[i - 1].y) * f });
  }
  return out;
}

function cross(o, a, b) { return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x); }
function properIntersect(p1, p2, p3, p4) {
  const d1 = cross(p3, p4, p1);
  const d2 = cross(p3, p4, p2);
  const d3 = cross(p1, p2, p3);
  const d4 = cross(p1, p2, p4);
  const EPS = 1e-9;
  if (((d1 > EPS && d2 < -EPS) || (d1 < -EPS && d2 > EPS)) && ((d3 > EPS && d4 < -EPS) || (d3 < -EPS && d4 > EPS))) return true;
  return false;
}

function bbox(pts) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of pts) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }
  return { x0, y0, x1, y1 };
}

function measure(polylines) {
  const polys = polylines.map(sample9);
  const boxes = polys.map(bbox);
  let pairs = 0;
  let hits = 0;
  for (let i = 0; i < polys.length; i++) {
    for (let j = i + 1; j < polys.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.x1 < b.x0 || b.x1 < a.x0 || a.y1 < b.y0 || b.y1 < a.y0) continue;
      let any = false;
      for (let s = 1; s < polys[i].length; s++) {
        for (let t = 1; t < polys[j].length; t++) {
          if (properIntersect(polys[i][s - 1], polys[i][s], polys[j][t - 1], polys[j][t])) { hits++; any = true; }
        }
      }
      if (any) pairs++;
    }
  }
  return { pairs, hits, edges: polys.length };
}

const docs = [];
const args = process.argv.slice(2);
if (args.length === 0) docs.push(['contracts/graph.sample.json', await readSample()]);
for (const path of args) {
  if (path.indexOf('synthetic:') === 0) {
    const n = Number(path.split(':')[1]);
    docs.push(['synthetic ' + n, makeSyntheticGraph(n, n * 2)]);
  } else {
    docs.push([path, JSON.parse(await readFile(path, 'utf8'))]);
  }
}

/**
 * What the reader actually SEES with the VIEW-04 trunks collapsed: every trunk,
 * every spur, and every route that is not a member of a bundle.
 */
function drawnPolylines(layout) {
  const bundled = new Set();
  const out = [];
  for (const b of layout.bundles || []) {
    for (const id of b.memberIds) bundled.add(id);
    out.push(b.trunk);
    for (const spur of b.spurs) out.push(spur.points);
  }
  for (const e of layout.edges) if (!bundled.has(e.id)) out.push(e.points);
  return out;
}

for (const [name, graph] of docs) {
  const layout = MLView.__internal.layout(graph);
  const m = measure(layout.edges.map((e) => e.points));
  const drawn = drawnPolylines(layout);
  const d = measure(drawn);
  const crossLane = layout.edges.filter((e) => e.crossLane).length;
  const ch = layout.channel || { w: 0, pairs: 0, slots: 0 };
  console.log(
    name.padEnd(30) +
      ' nodes=' + String(graph.nodes.length).padStart(4) +
      ' routes=' + String(m.edges).padStart(4) +
      ' crossLane=' + String(crossLane).padStart(4) +
      ' | ROUTES pairs=' + String(m.pairs).padStart(6) + ' perEdge=' + (m.pairs / m.edges).toFixed(2).padStart(6) +
      ' | DRAWN strokes=' + String(d.edges).padStart(4) + ' pairs=' + String(d.pairs).padStart(6) +
      ' perEdge=' + (d.pairs / m.edges).toFixed(2).padStart(6) +
      ' | bundles=' + String((layout.bundles || []).length).padStart(3) +
      ' channel=' + ch.w + 'px/' + ch.pairs + 'pairs' +
      ' world=' + Math.round(layout.width) + 'x' + Math.round(layout.height),
  );
}
