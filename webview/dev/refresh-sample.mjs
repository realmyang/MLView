/**
 * Regenerate the inline graph in dev/index.html from contracts/graph.sample.json.
 *
 *   npm run refresh-sample
 *
 * The copy is inlined (rather than fetched) so the page works from file:// with
 * no server and no network — the same constraint the standalone HTML report
 * lives under (amendment A4). Every `</` is escaped as `<\/` and `<!--` as
 * `<\!--` so the JSON can never terminate the script element early.
 */

import { readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const samplePath = join(here, '..', '..', 'contracts', 'graph.sample.json');
const pagePath = join(here, 'index.html');

const START = '<!-- MLVIEW-SAMPLE-START -->';
const END = '<!-- MLVIEW-SAMPLE-END -->';

export function escapeForScript(json) {
  return json.split('</').join('<\\/').split('<!--').join('<\\!--');
}

const raw = await readFile(samplePath, 'utf8');
const graph = JSON.parse(raw);
const json = escapeForScript(JSON.stringify(graph, null, 2));

const page = await readFile(pagePath, 'utf8');
const from = page.indexOf(START);
const to = page.indexOf(END);
if (from < 0 || to < 0) {
  process.stderr.write('dev/index.html is missing the MLVIEW-SAMPLE markers\n');
  process.exit(1);
}

const block =
  START +
  '\n    <script id="mlview-graph" type="application/json">\n' +
  json +
  '\n    </' +
  'script>\n    ' +
  END;

const next = page.slice(0, from) + block + page.slice(to + END.length);
await writeFile(pagePath, next, 'utf8');
process.stdout.write(
  'dev/index.html refreshed from contracts/graph.sample.json (' +
    graph.nodes.length +
    ' nodes, ' +
    graph.edges.length +
    ' edges, ' +
    graph.issues.length +
    ' issues)\n',
);
