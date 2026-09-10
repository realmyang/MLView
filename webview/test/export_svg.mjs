/**
 * Export the REAL demo diagram to a standalone SVG and check it (VIEW-07).
 *
 * The twin of `test/render_report.mjs`: that one proves the shipped HTML report
 * renders, this one proves the shipped bundle can turn the same document into a
 * file somebody can put in a PR — with every card, every connection, the stage
 * colours as literals and nothing to fetch.
 *
 *   node test/export_svg.mjs [path/to/graph.json] [--out=FILE]
 *                            [--region=view|diagram|scope] [--theme=light|dark|hc]
 *
 * Exits 0 when every check passes, 1 otherwise. The written file is what the
 * Chromium screenshot in the VIEW-07 measurement note was taken from.
 */

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(join(HERE, '..', '..'));
const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const hit = args.find((a) => a.indexOf('--' + name + '=') === 0);
  return hit ? hit.slice(name.length + 3) : fallback;
};
const positional = args.filter((a) => a.indexOf('--') !== 0);
const graphPath = positional[0] ? resolve(positional[0]) : join(REPO_ROOT, '.mlview', 'graph.json');
const region = flag('region', 'diagram');
const theme = flag('theme', 'light');
const outPath = resolve(flag('out', join(REPO_ROOT, '.mlview', 'diagram.svg')));

const out = (line) => process.stdout.write(line + '\n');
const failures = [];
function check(ok, label, detail) {
  out((ok ? '  PASS  ' : '  FAIL  ') + label.padEnd(54) + (detail === undefined ? '' : detail));
  if (!ok) failures.push(label + ' -- ' + detail);
}

const graph = JSON.parse(await readFile(graphPath, 'utf8'));
const code = await readFile(join(HERE, '..', 'dist', 'mlview.js'), 'utf8');

const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', () => undefined);
const dom = new JSDOM('<!doctype html><html><body><div id="mlview-root"></div></body></html>', {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  url: 'https://mlview.test/',
  virtualConsole,
});
if (typeof dom.window.structuredClone !== 'function') {
  dom.window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
}
const script = dom.window.document.createElement('script');
script.textContent = code;
dom.window.document.head.appendChild(script);

const internal = dom.window.MLView.__internal;
const layout = internal.layout(graph, []);
const result = internal.exportDiagram.build(graph, { region, theme });
await writeFile(outPath, result.svg, 'utf8');

out('MLView diagram export -- SVG check');
out('  graph:  ' + graphPath + '  (' + graph.nodes.length + ' nodes, ' + graph.edges.length + ' edges)');
out('  region: ' + region + '   theme: ' + theme);
out('  wrote:  ' + outPath + '  (' + result.svg.length + ' bytes, ' + Math.round(result.width) + 'x' + Math.round(result.height) + ')');
out('');

const groups = (result.svg.match(/<g\b[^>]*\bdata-node-id="/g) || []).length;
const paths = (result.svg.match(/<path\b[^>]*\bdata-edge-id="/g) || []).length;
check(groups === layout.nodes.length, 'one <g> per drawn node', groups + ' of ' + layout.nodes.length);
check(paths === layout.edges.length, 'one path per routed edge', paths + ' of ' + layout.edges.length);

const covered = new Set(result.edgeDocIds);
const missing = graph.edges.filter((e) => !covered.has(e.id));
check(
  region !== 'diagram' || missing.length === 0,
  'every document edge reached the picture',
  covered.size + ' of ' + graph.edges.length + (missing.length ? ' (missing ' + missing.length + ')' : ''),
);

const httpHits = result.svg.split('http').length - 1;
check(httpHits === 1 && /xmlns="http/.test(result.svg), 'the only http is the xmlns declaration', httpHits + ' occurrence(s)');
for (const banned of ['url(', 'foreignObject', 'xlink', '<image', '<script', '@font-face', '@import', 'var(--']) {
  check(result.svg.indexOf(banned) === -1, 'no ' + banned, 'clean');
}

const palette = internal.exportDiagram.palettes[theme] || internal.exportDiagram.palettes.light;
const FIELD = {
  config: 'stageConfig',
  data: 'stageData',
  preprocess: 'stagePreprocess',
  model: 'stageModel',
  objective: 'stageObjective',
  train: 'stageTrain',
  eval: 'stageEval',
  deliver: 'stageDeliver',
};
const laneMisses = result.laneIds.filter((id) => result.svg.indexOf(palette[FIELD[id]] || palette.stageUnknown) < 0);
check(laneMisses.length === 0, 'every drawn lane put its stage colour in the file', result.laneIds.join(', '));

const doc = new dom.window.DOMParser().parseFromString(result.svg, 'image/svg+xml');
check(!doc.querySelector('parsererror'), 'the file is well-formed XML', doc.documentElement.tagName);
check(doc.querySelectorAll('text').length > 0, 'real <text>, not foreignObject', doc.querySelectorAll('text').length + ' text nodes');
check(doc.querySelectorAll('rect').length > 0, 'real <rect> geometry', doc.querySelectorAll('rect').length + ' rects');

out('');
out(failures.length ? 'SVG EXPORT CHECK FAILED -- ' + failures.length + ' problem(s)' : 'SVG EXPORT CHECK OK -- every assertion passed');
for (const f of failures) out('  - ' + f);
process.exit(failures.length ? 1 : 0);
