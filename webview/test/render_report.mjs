/**
 * Renders the STANDALONE HTML report (.mlview/report.html) in jsdom — the real
 * artifact a user double-clicks, not the bundle plus a graph — and asserts the
 * integration acceptance checks:
 *
 *   >= 20 node cards · all three marker shapes · >= 1 ghost node
 *   7 lane bands + a "not detected" chip row · zero thrown errors
 *   clicking a node card dispatches openLocation on the standalone bridge
 *
 *   node test/render_report.mjs [path/to/report.html] [--min-ghosts=N]
 *                                [--scope=<SPEC>] [--depth=<0-2>]
 *
 * With `--scope` the report is loaded, then projected IN THE VIEWER through the
 * same code path `--html --scope` uses (the root element's `data-mlview-scope`
 * attribute, CONTRACTS 11.8), and the scoped checks replace the whole-project
 * ones: no empty swimlane band, a breadcrumb naming the project total, and
 * every boundary stub badge-free.
 *
 * Exits 0 when every check passes, 1 otherwise.
 */

import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(join(HERE, '..', '..'));
const args = process.argv.slice(2);
const ghostFlag = args.find((a) => a.indexOf('--min-ghosts=') === 0);
// The clean twin has no findings, so it declares no ghost slots: pass
// --min-ghosts=0 there. Every ghost a document DOES declare must still be drawn.
const MIN_GHOSTS = ghostFlag ? Number(ghostFlag.split('=')[1]) : 1;
const scopeFlag = args.find((a) => a.indexOf('--scope=') === 0);
const depthFlag = args.find((a) => a.indexOf('--depth=') === 0);
const SCOPE = scopeFlag ? scopeFlag.slice('--scope='.length) : null;
const DEPTH = depthFlag ? Number(depthFlag.slice('--depth='.length)) : undefined;
const positional = args.filter((a) => a.indexOf('--') !== 0);
const reportPath = positional[0] ? resolve(positional[0]) : join(REPO_ROOT, '.mlview', 'report.html');

const out = (line) => process.stdout.write(line + '\n');
const failures = [];
function check(ok, label, detail) {
  out((ok ? '  PASS  ' : '  FAIL  ') + label.padEnd(52) + (detail === undefined ? '' : detail));
  if (!ok) failures.push(label + ' -- ' + detail);
}

/* -- load the report exactly as a browser would ------------------------- */

let html = await readFile(reportPath, 'utf8');

// `--scope` exercises the REAL bootstrap path: a report written with --scope
// carries `data-mlview-scope` on its root element and the viewer projects the
// embedded FULL graph itself (CONTRACTS 11.8). When the caller asks for a scope
// the report does not already declare, stamp the attribute the same way the
// emitter does — mount() keeps its frozen three arguments either way.
if (SCOPE) {
  // Match the BODY element, not the identical string inside the inlined
  // stylesheet's comments — nor the attribute NAME, which the inlined bundle
  // itself contains because that is the attribute mount() reads.
  const plain = '<div id="mlview-root"></div>';
  const attrs = ' data-mlview-scope="' + SCOPE + '"' + (DEPTH === undefined ? '' : ' data-mlview-depth="' + DEPTH + '"');
  if (html.indexOf(plain) >= 0) html = html.replace(plain, '<div id="mlview-root"' + attrs + '></div>');
  else if (!/<div id="mlview-root"[^>]*data-mlview-scope=/.test(html)) {
    out('  WARN: could not stamp the scope onto #mlview-root');
  }
}

const consoleErrors = [];
const jsdomErrors = [];
const navigations = [];
const clipboard = [];

const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', (err) => {
  const msg = String((err && err.message) || err);
  // The standalone bridge deliberately navigates to vscode://file/... ; jsdom
  // cannot navigate, so that specific error is a signal, not a fault.
  if (/Not implemented: navigation/i.test(msg)) navigations.push(msg);
  else jsdomErrors.push(msg);
});
virtualConsole.on('error', (...args) => consoleErrors.push(args.map(String).join(' ')));

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  url: 'https://mlview.test/report.html',
  virtualConsole,
  beforeParse(window) {
    // jsdom 26 has no structuredClone; dagre uses it. Every real host ships it.
    if (typeof window.structuredClone !== 'function') window.structuredClone = deepClone;
    // A NAVIGATION TRIPWIRE, not a stub. Since CONTRACTS 11.17 the standalone
    // bridge must never navigate its own document: over http(s) — which is what
    // this jsdom is — a location opens by COPYING `file:line` and offering an
    // "Open in VS Code" link in the toast. Anything recorded here is the bug
    // that replaced an embedded report with the browser's blocked-content page.
    const proto = window.HTMLAnchorElement.prototype;
    const realClick = proto.click;
    proto.click = function patchedClick() {
      const href = this.getAttribute('href') || '';
      if (/^vscode:/.test(href)) {
        navigations.push(href);
        return undefined;
      }
      return realClick.apply(this, arguments);
    };
    // jsdom ships no clipboard, and without one the honest-reporting path in
    // `copyText` would toast "Copy blocked". Every real host has one.
    Object.defineProperty(window.navigator, 'clipboard', {
      value: {
        writeText: (text) => {
          clipboard.push(text);
          return Promise.resolve();
        },
      },
      configurable: true,
    });
  },
});

const { window } = dom;
const { document } = window;

/* -- the checks --------------------------------------------------------- */

out('MLView standalone report -- jsdom render check');
out('  file: ' + reportPath);
if (SCOPE) out('  scope: ' + SCOPE + (DEPTH === undefined ? '' : ' (depth ' + DEPTH + ')'));
out('  size: ' + html.length + ' bytes');
out('');

const graphEl = document.getElementById('mlview-graph');
const graph = graphEl ? JSON.parse(graphEl.textContent) : null;
check(!!graph, 'embedded graph parses', graph ? graph.nodes.length + ' nodes, ' + graph.edges.length + ' edges' : 'no #mlview-graph');
check(!!window.MLView, 'window.MLView defined by the inlined bundle', window.MLView ? 'v' + window.MLView.version : '');

const root = document.getElementById('mlview-root');
check(!!root && root.children.length > 0, 'the viewer mounted into #mlview-root', root ? root.children.length + ' child element(s)' : 'no root');

/* -- optional: project the embedded FULL graph in the viewer ------------- */

if (SCOPE) {
  check(
    root && root.getAttribute('data-mlview-scope') === SCOPE,
    'the root element declares the scope',
    root ? String(root.getAttribute('data-mlview-scope')) : 'no root',
  );

  const crumb = document.querySelector('.mlv-breadcrumb');
  const crumbText = crumb ? crumb.textContent.replace(/\s+/g, ' ').trim() : '';
  check(!!crumb && !crumb.hidden, 'the viewer projected the embedded FULL graph', crumbText || 'no breadcrumb');
  check(
    crumbText.indexOf(' of ' + graph.nodes.length + ' node') > 0,
    'and the breadcrumb still names the PROJECT total',
    crumbText,
  );

  const bands = Array.from(document.querySelectorAll('[data-lane-id]'));
  const empty = bands.filter(
    (b) => document.querySelectorAll('[data-node-id][data-stage="' + b.getAttribute('data-lane-id') + '"]').length === 0,
  );
  check(
    empty.length === 0,
    'no empty swimlane band is drawn',
    bands.length + ' bands: ' + bands.map((b) => b.getAttribute('data-lane-id')).join(', '),
  );

  const stubs = Array.from(document.querySelectorAll('[data-view-role="boundary"]'));
  const badged = stubs.filter((stub) => stub.querySelector('.mlv-badge, .mlv-cluster'));
  check(badged.length === 0, 'every boundary stub is badge-free', stubs.length + ' boundary stub(s)');
}

const cards = document.querySelectorAll('.mlv-node[data-node-id], .mlv-group[data-node-id]');
check(cards.length >= (SCOPE ? 1 : 20), 'node cards drawn (>= ' + (SCOPE ? 1 : 20) + ')', cards.length + ' cards');

const shapes = new Set();
for (const g of document.querySelectorAll('.mlv-glyph')) {
  for (const cls of g.getAttribute('class').split(/\s+/)) {
    if (cls.indexOf('mlv-glyph--') === 0) shapes.add(cls.slice('mlv-glyph--'.length));
  }
}
const paths = new Set();
for (const p of document.querySelectorAll('.mlv-glyph__shape')) paths.add(p.getAttribute('d'));
const allThree = ['low', 'medium', 'high'].every((s) => shapes.has(s));
check(allThree, 'all three marker severities present', Array.from(shapes).sort().join(', '));
check(paths.size >= 3, 'the three marker SHAPES are distinct paths', paths.size + ' distinct <path d>');

const ghostGraph = (graph ? graph.nodes : []).filter((n) => n.ghost);
const ghostDrawn = ghostGraph.filter((n) => document.querySelector('[data-node-id="' + n.id + '"]'));
if (!SCOPE) {
  check(
    ghostDrawn.length >= MIN_GHOSTS && ghostDrawn.length === ghostGraph.length,
    'every declared ghost is drawn (>= ' + MIN_GHOSTS + ')',
    ghostDrawn.length + ' of ' + ghostGraph.length + ' ghosts' + (ghostGraph.length ? ': ' + ghostDrawn.map((n) => n.label).join(', ') : ''),
  );
}

const lanes = document.querySelectorAll('[data-lane-id]');
const presentStages = (graph ? graph.stages : []).filter((s) => s.present);
if (!SCOPE) {
  check(lanes.length === 7, 'lane bands drawn (7)', lanes.length + ' bands: ' + Array.from(lanes).map((l) => l.getAttribute('data-lane-id')).join(', '));
}
check(presentStages.length === 7, 'the document declares 7 present stages', presentStages.map((s) => s.id).join(', '));

const chipRow = document.querySelector('.mlv-chiprow');
const chipLabel = chipRow ? chipRow.querySelector('.mlv-chiprow__label') : null;
const chips = chipRow ? chipRow.querySelectorAll('.mlv-chip') : [];
if (SCOPE) {
  // A scope adds a "not in this scope" row beside the "not detected" one, so the
  // stages it excluded are labelled rather than silently missing (11.4 F3).
  // A scope that happens to touch every present stage excludes none — then the
  // row is correctly absent, and demanding it would be the wrong assertion.
  const labels = Array.from(chipRow ? chipRow.querySelectorAll('.mlv-chiprow__label') : []).map((l) => l.textContent);
  const drawnLanes = new Set(Array.from(document.querySelectorAll('[data-lane-id]')).map((l) => l.getAttribute('data-lane-id')));
  const excluded = presentStages.filter((s) => !drawnLanes.has(s.id)).map((s) => s.id);
  check(
    excluded.length === 0 || labels.indexOf('not in this scope') >= 0,
    'excluded stages are labelled, not dropped',
    excluded.length ? 'excluded: ' + excluded.join(', ') + ' — rows: ' + labels.join(' / ') : 'this scope excludes no present stage',
  );
} else {
  check(
    !!chipLabel && chipLabel.textContent === 'not detected' && chips.length === 1,
    'a "not detected" chip row with exactly 1 chip',
    chipRow ? '"' + (chipLabel ? chipLabel.textContent : '') + '": ' + Array.from(chips).map((c) => c.textContent).join(', ') : 'no chip row',
  );
}

check(jsdomErrors.length === 0, 'no errors thrown during load and mount', jsdomErrors.length ? jsdomErrors.join(' | ') : 'clean');
check(consoleErrors.length === 0, 'no console.error output', consoleErrors.length ? consoleErrors.join(' | ') : 'clean');

/* -- clicking a node card must open the location WITHOUT navigating ------ */

navigations.length = 0;
clipboard.length = 0;
const target = Array.from(cards).find((c) => {
  const id = c.getAttribute('data-node-id');
  const n = graph.nodes.find((x) => x.id === id);
  return n && !n.ghost && c.classList.contains('mlv-node') && c.getAttribute('data-view-role') !== 'context';
});
const targetNode = target ? graph.nodes.find((n) => n.id === target.getAttribute('data-node-id')) : null;
if (!target) {
  check(false, 'clicking a node card opens its location', 'no clickable node card found');
} else {
  const hrefBefore = window.location.href;
  const cardsBefore = document.querySelectorAll('[data-node-id]').length;
  target.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 80));

  const expected = 'vscode://file/' + targetNode.loc.absFile + ':' + targetNode.loc.line + ':' + (targetNode.loc.col + 1);
  const ref = targetNode.loc.file + ':' + targetNode.loc.line;
  // CONTRACTS 11.17. This jsdom is a top-level https document, so the plan is
  // COPY: the clipboard gets `file:line` and the toast carries the deep link as
  // an anchor. The old path clicked a same-frame <a href="vscode://...">, which
  // a sandboxed host answered by replacing the whole report with its
  // blocked-content page -- the reason this check now reads the way it does.
  check(
    navigations.length === 0,
    'the report never navigates itself (11.17)',
    navigations.length ? 'NAVIGATED to ' + navigations[0] : 'no navigation attempted',
  );
  check(window.location.href === hrefBefore, 'the document stayed where it was', window.location.href);
  check(
    document.querySelectorAll('[data-node-id]').length === cardsBefore,
    'the diagram survived the click',
    cardsBefore + ' cards before, ' + document.querySelectorAll('[data-node-id]').length + ' after',
  );
  check(
    clipboard.length === 1 && clipboard[0] === ref,
    'clicking a node card copies file:line',
    (clipboard.length ? clipboard[0] : 'nothing copied') + '  (node ' + targetNode.label + ')',
  );
  const toast = document.querySelector('.mlv-toast--floating');
  const link = toast ? toast.querySelector('a') : null;
  check(
    !!toast && toast.textContent.indexOf(ref) >= 0,
    'and says so in a toast',
    toast ? toast.textContent : 'no floating toast',
  );
  check(
    !!link && link.getAttribute('href') === expected && link.getAttribute('target') === '_blank',
    'which still offers the deep link, in a NEW context',
    link ? link.getAttribute('href') + ' target=' + link.getAttribute('target') : 'no link in the toast',
  );
  check(
    target.classList.contains('is-selected') || target.getAttribute('aria-selected') === 'true',
    'the clicked card became the selection',
    'class="' + target.getAttribute('class') + '"',
  );
  check(jsdomErrors.length === 0, 'no errors thrown by the click', jsdomErrors.length ? jsdomErrors.join(' | ') : 'clean');
}

out('');
out(failures.length ? 'RENDER CHECK FAILED -- ' + failures.length + ' problem(s)' : 'RENDER CHECK OK -- every assertion passed');
for (const f of failures) out('  - ' + f);
process.exit(failures.length ? 1 : 0);

function deepClone(value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(deepClone);
  if (value instanceof Date) return new Date(value.getTime());
  if (value instanceof Map) return new Map(Array.from(value).map(([k, v]) => [deepClone(k), deepClone(v)]));
  if (value instanceof Set) return new Set(Array.from(value).map(deepClone));
  const clone = {};
  for (const key of Object.keys(value)) clone[key] = deepClone(value[key]);
  return clone;
}
