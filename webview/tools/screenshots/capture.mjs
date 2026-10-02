#!/usr/bin/env node
// Opt-in screenshots of the MLView viewer in headless Chrome. Not part of CI or the e2e gates.
//
//   node webview/tools/screenshots/capture.mjs [options]
//
// It serves the viewer bundle (webview/dist) and a page that plays the VS Code side: VS Code
// theme variables, a stub acquireVsCodeApi and the panel's own inline bootstrap, read from
// vscode-extension/src/authoredPanel.ts. When the bootstrap posts `ready`, the page receives
// the frames the extension posts: `init`, then `workflow`, and for the stale states a `stale`
// frame and the stale banner (`workflowError`). Then it drives each state with real mouse and
// key events and writes one PNG per state plus index.json.
//
// What it is not: the host is simulated. There is no validation of the artifact, no source
// navigation and no editor; an `openLocation` the viewer posts is only recorded. Screenshots
// are a rendering check, not live VS Code validation, usability or semantic review.
//
// Run `--help` for the options. Chrome is found through CHROME or the usual install paths.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { basename, dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { benchmarkWorkflow } from '../benchmark-model.mjs';
import { deadline, findChrome, launchChrome } from './cdp.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..', '..');
const SAMPLE = join(REPO, 'samples', 'configured_training.mlview.json');
const THEMES = { 'dark-modern': 'dark', 'light-modern': 'light', 'hc-dark': 'hc' };
const NARROW = [900, 800];

const STATES = {
  'initial': 'as opened',
  'select-node': 'clicked a step card',
  'hover-node': 'pointer resting on a step card',
  'hover-connection': 'pointer resting on a connection',
  'focus-mode': 'clicked a step card, then pressed F',
  'focus-settled': 'clicked a step card, pressed F, then waited 7 s for the flow to settle',
  'exceptions': 'turned on the "not observed" toggle, which fades the observed claims',
  'legend': 'pressed L to open the legend',
  'filter': 'turned off the lowest severity that has findings (a phase chip when there are none)',
  'search': 'typed a word from a step label into the search box',
  'finding': 'clicked a finding with a suggestion in the Findings list',
  'stale': 'opened with a stale frame for one cited file',
  'stale-selected': 'opened with a stale frame, then clicked a step that cites that file',
  'narrow-selected': `${NARROW[0]}x${NARROW[1]} panel, clicked a step card`,
};

const USAGE = `Usage: node webview/tools/screenshots/capture.mjs [options]

Opens *.mlview.json documents in the viewer in headless Chrome and saves one PNG
per state plus index.json. The host is simulated; this is a rendering check.

Inputs (default: samples/configured_training.mlview.json and a synthetic
120-step document; both are only read):
  --artifact <file>   a *.mlview.json to open, read-only; repeat for several
  --workspace <dir>   the folder the preceding --artifact's paths are relative
                      to; its cited files are hashed against the published
                      hashes, and real stale files are posted as in VS Code
  --label <name>      file-name label for the preceding --artifact
  --search <word>     search term for the preceding --artifact
  --defaults          also capture the default inputs when --artifact is given

Output:
  --out <dir>         where PNGs and index.json go
                      (default: .mlview/screenshots/<UTC time> in this checkout)
  --states <a,b,...>  subset of: ${Object.keys(STATES).join(', ')}
  --theme <a,b|all>   ${Object.keys(THEMES).join(', ')} (default: dark-modern)
  --size <WxH>        viewport for every state but narrow-selected (default 1440x900)
  --scale <n>         device pixel ratio (default 1)
  --viewer <dir>      an MLView checkout whose webview/dist and panel bootstrap
                      are loaded (default: this checkout), for before/after runs

Chrome: set CHROME to the executable, or install Chrome or Chromium in the usual place.
`;

function fail(message) {
  process.stderr.write(`capture: ${message}\n`);
  process.exit(2);
}

function parseArgs(argv) {
  const opts = { out: null, viewer: REPO, states: Object.keys(STATES), themes: ['dark-modern'], size: [1440, 900], scale: 1, inputs: [], defaults: false };
  const last = (flag) => opts.inputs[opts.inputs.length - 1] || fail(`${flag} must follow an --artifact`);
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    const value = () => {
      const v = argv[++i];
      if (v === undefined || v.startsWith('--')) fail(`${flag} needs a value`);
      return v;
    };
    switch (flag) {
      case '-h': case '--help': process.stdout.write(USAGE); process.exit(0); break;
      case '--out': opts.out = resolve(value()); break;
      case '--viewer': opts.viewer = resolve(value()); break;
      case '--states': opts.states = value().split(',').filter(Boolean); break;
      case '--theme': { const v = value(); opts.themes = v === 'all' ? Object.keys(THEMES) : v.split(',').filter(Boolean); break; }
      case '--size': { const m = /^(\d+)x(\d+)$/.exec(value()); if (!m) fail('--size takes WIDTHxHEIGHT, for example 1440x900'); opts.size = [Number(m[1]), Number(m[2])]; break; }
      case '--scale': opts.scale = Number(value()); if (!(opts.scale > 0 && opts.scale <= 4)) fail('--scale takes a number above 0, at most 4'); break;
      case '--artifact': opts.inputs.push({ artifact: resolve(value()) }); break;
      case '--workspace': last(flag).workspace = resolve(value()); break;
      case '--label': last(flag).label = value(); break;
      case '--search': last(flag).search = value(); break;
      case '--defaults': opts.defaults = true; break;
      default: fail(`unknown option ${flag} (see --help)`);
    }
  }
  for (const s of opts.states) if (!STATES[s]) fail(`unknown state ${s}; states are ${Object.keys(STATES).join(', ')}`);
  for (const t of opts.themes) if (!THEMES[t]) fail(`unknown theme ${t}; themes are ${Object.keys(THEMES).join(', ')}`);
  if (!opts.inputs.length || opts.defaults) {
    opts.inputs.unshift({ artifact: SAMPLE, workspace: REPO, label: 'sample' }, { synthetic: true, label: 'synthetic' });
  }
  return opts;
}

/** A deterministic synthetic document: the benchmark fixture at 120 steps, with details and suggestions. */
function syntheticDocument() {
  const document = benchmarkWorkflow(120, 'screenshots-r1');
  document.title = 'Synthetic screenshot document (120 steps)';
  for (const node of document.nodes) if (node.id.startsWith('node-') && Number(node.id.slice(5)) % 3 === 0) node.detail = `Synthetic detail for ${node.label}; no semantic claim.`;
  for (const finding of document.findings) finding.suggestion = `Synthetic suggestion for ${finding.title}; no semantic claim.`;
  return document;
}

const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

/** Published hashes against the workspace files, like the extension's freshness check (no size limit here). */
function freshness(document, workspace) {
  const published = document.verification && document.verification.files;
  if (!workspace || !published || typeof published !== 'object') return { checked: false, stale: [] };
  const stale = [];
  for (const [rel, hash] of Object.entries(published)) {
    const file = resolve(workspace, rel);
    const inside = relative(workspace, file);
    if (!inside || inside.startsWith('..') || isAbsolute(inside)) { stale.push({ path: rel, reason: 'unreadable' }); continue; }
    if (!existsSync(file)) { stale.push({ path: rel, reason: 'missing' }); continue; }
    let bytes;
    try { bytes = readFileSync(file); } catch { stale.push({ path: rel, reason: 'unreadable' }); continue; }
    if (sha256(bytes) !== hash) stale.push({ path: rel, reason: 'changed' });
  }
  return { checked: true, files: Object.keys(published).length, stale };
}

function loadInput(input) {
  const document = input.synthetic ? syntheticDocument() : JSON.parse(readFileSync(input.artifact, 'utf8'));
  const label = (input.label || basename(dirname(input.artifact)) || 'artifact').replace(/[^A-Za-z0-9._-]+/g, '-');
  const evidenceFile = new Map((document.evidence || []).map((e) => [e.id, e.file]));
  const filesOf = (item) => (item.evidence || []).map((id) => evidenceFile.get(id)).filter(Boolean);
  const fresh = freshness(document, input.workspace);
  const counts = new Map();
  for (const node of document.nodes) for (const file of new Set(filesOf(node))) counts.set(file, (counts.get(file) || 0) + 1);
  // Steps to click, best first: leaves with evidence, then those with a suggested finding, then those with detail.
  const parents = new Set(document.nodes.map((n) => n.parent).filter(Boolean));
  const suggested = new Set((document.findings || []).filter((f) => f.suggestion).flatMap((f) => f.nodeIds || []));
  const leaves = document.nodes.filter((n) => n.kind !== 'group' && !parents.has(n.id) && (n.evidence || []).length);
  const score = (n) => (suggested.has(n.id) ? 2 : 0) + (n.detail ? 1 : 0);
  const nodeOrder = leaves.map((n, i) => [n, i]).sort((a, b) => score(b[0]) - score(a[0]) || a[1] - b[1]).map(([n]) => n.id);
  // Findings to click: those with a suggestion first, the most severe first (the list is grouped by severity).
  const rank = { high: 0, medium: 1, low: 2 };
  const findingOrder = (document.findings || []).map((f, i) => [f, i])
    .sort((a, b) => (a[0].suggestion ? 0 : 1) - (b[0].suggestion ? 0 : 1) || (rank[a[0].severity] ?? 3) - (rank[b[0].severity] ?? 3) || a[1] - b[1])
    .map(([f]) => f.id);
  const findingEdges = new Set((document.findings || []).flatMap((f) => f.edgeIds || []));
  const edgeOrder = document.edges.filter((e) => findingEdges.has(e.id)).concat(document.edges.filter((e) => !findingEdges.has(e.id))).map((e) => e.id);
  const pickedLabel = (document.nodes.find((n) => n.id === nodeOrder[0]) || {}).label || '';
  const words = pickedLabel.match(/[A-Za-z]{4,}/g) || [];
  const search = input.search || (words.length ? words.reduce((a, b) => (b.length > a.length ? b : a)).toLowerCase() : 'loss');
  const loaded = {
    label, document, artifact: input.artifact || null, workspace: input.workspace || null, synthetic: !!input.synthetic,
    freshness: fresh, nodeOrder, findingOrder, edgeOrder, search, firstPick: null,
    staleSet: null, staleSimulated: !fresh.stale.length, staleNodeOrder: [],
    /** Fix the stale set: the real one, or else one file cited by `pickedId` (the most cited of its files). */
    chooseStale(pickedId) {
      let stale = fresh.stale;
      if (!stale.length) {
        const own = filesOf(document.nodes.find((n) => n.id === pickedId) || {});
        const pool = own.length ? own : [...counts.keys()];
        const file = pool.reduce((best, f) => (best === null || counts.get(f) > counts.get(best) ? f : best), null);
        stale = file ? [{ path: file, reason: 'changed' }] : [];
      }
      const paths = new Set(stale.map((s) => s.path));
      const cites = nodeOrder.filter((id) => filesOf(document.nodes.find((n) => n.id === id)).some((f) => paths.has(f)));
      loaded.staleSet = stale;
      loaded.staleNodeOrder = cites.includes(pickedId) ? [pickedId, ...cites.filter((id) => id !== pickedId)] : cites;
    },
  };
  return loaded;
}

function describeInput(i) {
  return {
    label: i.label, artifact: i.artifact, workspace: i.workspace, synthetic: i.synthetic, revision: i.document.revision && i.document.revision.id,
    nodes: i.document.nodes.length, edges: i.document.edges.length, findings: (i.document.findings || []).length,
    freshness: i.freshness, staleForStaleStates: i.staleSet, staleSimulated: i.staleSimulated, search: i.search,
  };
}

/** The banner text of vscode-extension/src/authoredSupport.ts staleBannerText, with the panel's three-name list. */
function staleBanner(stale, revisionId) {
  const tail = 'Jumps into those files are blocked; other evidence still opens. Ask the assistant to publish a fresh revision to update the diagram.';
  const word = { changed: 'changed', missing: 'missing', unreadable: 'unreadable', 'too-large': 'too large to check' };
  const list = (names) => names.slice(0, 3).join(', ') + (names.length > 3 ? `, and ${names.length - 3} more` : '');
  const reasons = ['changed', 'missing', 'unreadable', 'too-large'].filter((r) => stale.some((s) => s.reason === r));
  if (reasons.length === 1 && reasons[0] === 'changed') {
    return `This historical diagram is visible, but ${stale.length} source file(s) changed after revision ${revisionId} was published: ${list(stale.map((s) => s.path))}. ${tail}`;
  }
  const breakdown = reasons.map((r) => `${stale.filter((s) => s.reason === r).length} ${word[r]}`).join(', ');
  const names = stale.map((s) => (reasons.length > 1 && s.reason !== 'changed' ? `${s.path} (${word[s.reason]})` : s.path));
  return `This historical diagram is visible, but ${stale.length} source file(s) no longer match revision ${revisionId} as published (${breakdown}): ${list(names)}. ${tail}`;
}

/** What the extension posts after `ready` (vscode-extension/src/authoredPanel.ts message()). */
function framesFor(input, theme, stale) {
  const frames = [
    { v: 1, type: 'init', theme: THEMES[theme], capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false, canRefine: true }, artifact: input.artifact || `${input.label}.mlview.json` },
    { v: 1, type: 'workflow', document: input.document },
  ];
  if (stale.length) {
    frames.push({ v: 1, type: 'stale', files: stale.map((s) => ({ path: s.path, reason: s.reason })) });
    frames.push({ v: 1, type: 'workflowError', message: staleBanner(stale, input.document.revision && input.document.revision.id), retained: true, codes: ['stale'] });
  }
  return frames;
}

/** The panel's inline bootstrap script, read from the viewer checkout's authoredPanel.ts. */
function readBootstrap(viewer) {
  const source = join(viewer, 'vscode-extension', 'src', 'authoredPanel.ts');
  if (!existsSync(source)) fail(`no ${relative(viewer, source)} under ${viewer}`);
  const scripts = [...readFileSync(source, 'utf8').matchAll(/<script nonce="\$\{nonce\}">([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  if (scripts.length !== 1 || /\$\{|`/.test(scripts[0])) fail(`expected one plain inline <script nonce="\${nonce}"> in ${source}, found ${scripts.length}`);
  return scripts[0];
}

function gitInfo(dir) {
  const run = (args) => spawnSync('git', ['-C', dir, ...args], { encoding: 'utf8' });
  const head = run(['rev-parse', 'HEAD']);
  if (head.status !== 0) return null;
  const dirty = run(['status', '--porcelain', '--', 'webview/dist', 'vscode-extension/src/authoredPanel.ts']);
  return { commit: head.stdout.trim(), distOrBootstrapModified: !!dirty.stdout.trim() };
}

function startServer(viewer, loads) {
  const dist = join(viewer, 'webview', 'dist');
  for (const name of ['mlview.js', 'mlview.css']) if (!existsSync(join(dist, name))) fail(`no webview/dist/${name} under ${viewer}; run "npm run build" in its webview/`);
  const files = {
    '/index.html': [join(HERE, 'page.html'), 'text/html'],
    '/harness/themes.js': [join(HERE, 'themes.js'), 'text/javascript'],
    '/harness/shim.js': [join(HERE, 'shim.js'), 'text/javascript'],
    '/dist/mlview.js': [join(dist, 'mlview.js'), 'text/javascript'],
    '/dist/mlview.css': [join(dist, 'mlview.css'), 'text/css'],
  };
  const bootstrap = readBootstrap(viewer);
  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    const send = (status, type, body) => { res.writeHead(status, { 'content-type': `${type}; charset=utf-8`, 'cache-control': 'no-store' }); res.end(body); };
    if (url.pathname === '/favicon.ico') { res.writeHead(204); return res.end(); }
    if (url.pathname === '/bootstrap.js') return send(200, 'text/javascript', bootstrap);
    if (url.pathname === '/frames.json') {
      const frames = loads.get(url.searchParams.get('load'));
      return frames ? send(200, 'application/json', JSON.stringify(frames)) : send(404, 'text/plain', 'no such load');
    }
    const file = files[url.pathname];
    if (!file) return send(404, 'text/plain', 'not found');
    send(200, file[1], readFileSync(file[0]));
  });
  return new Promise((done) => server.listen(0, '127.0.0.1', () => done({ server, port: server.address().port, bundle: sha256(readFileSync(files['/dist/mlview.js'][0])) })));
}

// ── Page-side helpers, serialized into the page after each load ──────────────────────────────
function pageHelpers() {
  const rect = (e) => { const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height }; };
  const shown = (e) => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const txt = (e) => (e ? (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim() : '');
  const main = () => rect(document.querySelector('.mlv-main'));
  const blockers = () => ['.mlv-minimap', '.mlv-zoom', '.mlv-legend', '.mlv-toasts', '.mlv-tooltip'].map((s) => document.querySelector(s)).filter(shown).map(rect);
  const overlaps = (a, b) => !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
  const insideMain = (r) => { const m = main(); return r.w > 0 && r.x >= m.x + 4 && r.y >= m.y + 4 && r.x + r.w <= m.x + m.w - 4 && r.y + r.h <= m.y + m.h - 4; };
  /** A point inside `element` that the browser would really hit, or null. */
  const hitPoint = (element, r = rect(element)) => {
    for (const [fx, fy] of [[0.5, 0.5], [0.3, 0.5], [0.7, 0.5], [0.5, 0.3], [0.5, 0.7]]) {
      const x = r.x + r.w * fx, y = r.y + r.h * fy;
      const hit = document.elementFromPoint(x, y);
      if (hit && (hit === element || element.contains(hit))) return { x, y };
    }
    return null;
  };
  window.__shots = {
    pickNode(ids) {
      const usable = (card) => card && insideMain(rect(card)) && !blockers().some((b) => overlaps(rect(card), b)) && hitPoint(card);
      for (const id of ids) {
        const card = document.querySelector(`.mlv-node[data-node-id="${CSS.escape(id)}"]`);
        if (usable(card)) return { id, preferred: true, ...hitPoint(card) };
      }
      const cards = [...document.querySelectorAll('.mlv-node[data-node-id]')].filter(usable);
      cards.sort((a, b) => rect(b).w * rect(b).h - rect(a).w * rect(a).h);
      return cards[0] ? { id: cards[0].getAttribute('data-node-id'), preferred: false, ...hitPoint(cards[0]) } : null;
    },
    pickEdge(ids) {
      const order = new Map(ids.map((id, i) => [id, i]));
      const edges = [...document.querySelectorAll('.mlv-edge[data-edge-id]')].sort((a, b) => (order.get(a.getAttribute('data-edge-id')) ?? 1e9) - (order.get(b.getAttribute('data-edge-id')) ?? 1e9));
      for (const g of edges) {
        const path = g.querySelector('.mlv-edge__path');
        if (!path || !path.getTotalLength) continue;
        const length = path.getTotalLength();
        const m = path.getScreenCTM();
        if (!m || !length) continue;
        for (const t of [0.5, 0.4, 0.6, 0.3, 0.7]) {
          const p = path.getPointAtLength(length * t);
          const x = p.x * m.a + p.y * m.c + m.e, y = p.x * m.b + p.y * m.d + m.f;
          const box = { x: x - 3, y: y - 3, w: 6, h: 6 };
          if (!insideMain(box) || blockers().some((b) => overlaps(box, b))) continue;
          const hit = document.elementFromPoint(x, y);
          if (hit && hit.closest('.mlv-edge[data-edge-id]') === g) return { id: g.getAttribute('data-edge-id'), x, y };
        }
      }
      return null;
    },
    /** The centre of the first shown element matching `selector` (after scrolling it into view), or null. */
    pointOf(selector) {
      const element = [...document.querySelectorAll(selector)].find(shown);
      if (!element) return null;
      element.scrollIntoView({ block: 'nearest' });
      return hitPoint(element);
    },
    restPoint() {
      const status = document.querySelector('.mlv-status');
      if (!shown(status)) return { x: 2, y: innerHeight - 2 };
      const r = rect(status);
      return { x: r.x + r.w * 0.75, y: r.y + r.h / 2 };
    },
    severityChips: () => [...document.querySelectorAll('.mlv-chip--btn[data-severity]')].filter(shown)
      .map((c, i) => ({ i, severity: c.getAttribute('data-severity'), count: Number(txt(c.querySelector('.mlv-chip__count'))) || 0 })),
    facts() {
      const panel = [...document.querySelectorAll('.mlv-rail [role="tabpanel"]')].find((p) => !p.hidden && shown(p));
      const tab = document.querySelector('.mlv-rail__tab[aria-selected="true"]');
      const fix = panel && [...panel.querySelectorAll('.mlv-insp__fix')].find(shown);
      const inView = (e, box) => { const r = e.getBoundingClientRect(), b = box.getBoundingClientRect(); return r.height > 0 && r.top >= b.top - 1 && r.bottom <= b.bottom + 1; };
      const notice = [...document.querySelectorAll('.mlv-hostnotice, #mlview-authored-error')].find(shown);
      const tip = [...document.querySelectorAll('.mlv-tooltip')].find((t) => shown(t) && getComputedStyle(t).opacity !== '0');
      const rail = document.querySelector('.mlv-rail');
      return {
        viewport: `${innerWidth}x${innerHeight}`,
        canvasBox: (() => { const m = main(); return `${Math.round(m.x)},${Math.round(m.y)} ${Math.round(m.w)}x${Math.round(m.h)}`; })(),
        bars: Object.fromEntries(['.mlv-toolbar', '.mlv-status'].map((sel) => { const e = document.querySelector(sel); return [sel.slice(5), e && shown(e) ? Math.round(rect(e).h) : 0]; })),
        zoom: txt(document.querySelector('.mlv-zoom__level')) || null,
        selected: [...document.querySelectorAll('.is-selected[data-node-id], .is-selected[data-edge-id], .mlv-issue.is-selected')]
          .map((e) => e.getAttribute('data-node-id') || e.getAttribute('data-edge-id') || e.getAttribute('data-issue-id')),
        railOpen: shown(rail) && rail.offsetWidth > 0,
        railTab: tab ? txt(tab) : null,
        railText: panel ? txt(panel).slice(0, 500) : null,
        suggestionShown: !!fix,
        suggestionInView: !!fix && inView(fix, panel),
        suggestion: fix ? txt(fix).slice(0, 300) : null,
        status: txt(document.querySelector('.mlv-status')).slice(0, 200),
        notice: notice ? txt(notice).slice(0, 300) : null,
        staleMarks: {
          cards: document.querySelectorAll('[data-node-id].is-stale').length,
          connections: document.querySelectorAll('.mlv-edge.is-stale').length,
          rail: document.querySelectorAll('.mlv-rail .is-stale').length,
        },
        focusMode: !!document.querySelector('.is-focusing'),
        flow: {
          lit: document.querySelectorAll('.mlv-edge.is-flowing, .mlv-edge.is-flowing--pulse').length,
          moving: document.querySelectorAll('.mlv-edge__flow, .mlv-edge__charge').length,
          settled: (document.querySelector('.mlv-canvas') || { getAttribute: () => null }).getAttribute('data-flow-settled') === 'true',
        },
        exceptions: (document.querySelector('.mlv-canvas') || { getAttribute: () => null }).getAttribute('data-exceptions') === 'on',
        tooltip: tip ? txt(tip).slice(0, 300) : null,
        searchQuery: (document.querySelector('.mlv-search input') || {}).value || null,
        searchResults: [...document.querySelectorAll('.mlv-search__results [role="option"]')].filter(shown).length,
      };
    },
  };
  return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const opts = parseArgs(process.argv.slice(2));
const chromePath = findChrome();
if (chromePath.error) fail(chromePath.error);
const inputs = opts.inputs.map((input) => {
  if (!input.synthetic && !existsSync(input.artifact)) fail(`no artifact at ${input.artifact}`);
  if (input.workspace && !existsSync(input.workspace)) fail(`no workspace folder at ${input.workspace}`);
  return loadInput(input);
});
const out = opts.out || join(REPO, '.mlview', 'screenshots', new Date().toISOString().replace(/[:.]/g, '-'));
mkdirSync(out, { recursive: true });

const loads = new Map();
const { server, port, bundle } = await startServer(opts.viewer, loads);
let chrome;
const index = {
  tool: 'webview/tools/screenshots/capture.mjs',
  generatedAt: new Date().toISOString(),
  note: 'Headless Chrome with a simulated host (init, workflow, and stale + workflowError for the stale states). No validation, no source navigation, no editor. A rendering check only.',
  viewer: { root: opts.viewer, git: gitInfo(opts.viewer), bundleSha256: bundle },
  chrome: null,
  scale: opts.scale,
  inputs: [],
  shots: [],
  skipped: [],
};
function writeIndex() {
  index.inputs = inputs.map(describeInput);
  writeFileSync(join(out, 'index.json'), JSON.stringify(index, null, 1) + '\n');
}

try {
  chrome = await launchChrome(chromePath.path);
  index.chrome = chrome.version.product;
  const page = await chrome.newPage();
  const logs = [];
  let loadWaiter = null;
  page.on('Page.loadEventFired', () => { if (loadWaiter) { loadWaiter(); loadWaiter = null; } });
  page.on('Runtime.exceptionThrown', (p) => logs.push(`exception: ${p.exceptionDetails.exception?.description || p.exceptionDetails.text}`));
  page.on('Runtime.consoleAPICalled', (p) => { if (p.type === 'error' || p.type === 'warning') logs.push(`console.${p.type}: ${p.args.map((a) => a.value ?? a.description ?? '').join(' ')}`); });
  page.on('Log.entryAdded', (p) => { if (p.entry.level === 'error' || p.entry.level === 'warning') logs.push(`log.${p.entry.level}: ${p.entry.text}`); });
  await page.send('Page.enable');
  await page.send('Runtime.enable');
  await page.send('Log.enable');
  await page.send('Emulation.setFocusEmulationEnabled', { enabled: true });

  const evaluate = (expression) => page.evaluate(expression);
  const frame = () => evaluate('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))');
  const mouse = (type, x, y, extra = {}) => page.send('Input.dispatchMouseEvent', { type, x, y, button: 'none', clickCount: 0, ...extra });
  async function hover(x, y) {
    // Approach from nearby so pointerenter fires, then rest on the target.
    await mouse('mouseMoved', x - 30, y - 30); await sleep(60);
    await mouse('mouseMoved', x - 4, y - 2); await sleep(60);
    await mouse('mouseMoved', x, y);
  }
  async function click(x, y) {
    await mouse('mouseMoved', x, y); await sleep(40);
    await mouse('mousePressed', x, y, { button: 'left', buttons: 1, clickCount: 1 }); await sleep(40);
    await mouse('mouseReleased', x, y, { button: 'left', clickCount: 1 });
  }
  async function key(k) {
    const code = /^[a-z]$/i.test(k) ? 'Key' + k.toUpperCase() : k;
    const vk = k.length === 1 ? k.toUpperCase().charCodeAt(0) : { Escape: 27, Enter: 13 }[k] || 0;
    const base = { key: k, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk };
    await page.send('Input.dispatchKeyEvent', { type: k.length === 1 ? 'keyDown' : 'rawKeyDown', ...base, ...(k.length === 1 ? { text: k } : {}) });
    await page.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
  }
  async function rest() {
    const p = await evaluate('window.__shots.restPoint()');
    await mouse('mouseMoved', p.x, p.y);
    await sleep(400);
  }

  let loadSeq = 0;
  async function open(input, theme, [width, height], stale) {
    const id = String(++loadSeq);
    const frames = framesFor(input, theme, stale);
    loads.clear();
    loads.set(id, frames);
    await page.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: opts.scale, mobile: false });
    await page.send('Emulation.setEmulatedMedia', { features: [
      { name: 'prefers-color-scheme', value: THEMES[theme] === 'light' ? 'light' : 'dark' },
      { name: 'prefers-reduced-motion', value: 'no-preference' },
    ] });
    logs.length = 0;
    const loaded = new Promise((done) => { loadWaiter = done; });
    await page.send('Page.navigate', { url: `http://127.0.0.1:${port}/index.html?theme=${theme}&platform=${process.platform}&load=${id}` });
    await Promise.race([loaded, deadline(20000).then(() => { throw new Error('the harness page did not load within 20 s'); })]);
    const until = Date.now() + 20000;
    while (!(await evaluate(`!!window.__framesDelivered && !!document.querySelector('[data-node-id]')`))) {
      if (Date.now() > until) throw new Error(`the viewer did not render ${input.label} within 20 s${logs.length ? ': ' + logs.join(' | ') : ''}`);
      await sleep(100);
    }
    await sleep(900); // fit, fonts and the entry transition
    await frame();
    await evaluate(`(${pageHelpers.toString()})()`);
    return frames.map((f) => f.type);
  }

  async function snap(input, theme, size, state, frames, did, target) {
    const file = `${input.label}__${theme}__${size[0]}x${size[1]}__${state}.png`;
    await frame();
    const shot = await page.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(out, file), Buffer.from(shot.data, 'base64'));
    const facts = await evaluate('window.__shots.facts()');
    const posts = await evaluate('window.__uiPosts');
    index.shots.push({
      file, input: input.label, theme, viewport: `${size[0]}x${size[1]}`, state, did, target: target || null, hostFrames: frames,
      pagePosts: posts.map((p) => (p.type === 'openLocation' ? `openLocation ${p.file}:${p.line}${p.focus ? ' (focus)' : ''}` : p.type)),
      facts, console: logs.slice(),
    });
    writeIndex();
    process.stdout.write(`  ${file}${did ? ' - ' + did : ''}\n`);
  }

  async function clickNode(input, order) {
    const node = await evaluate(`window.__shots.pickNode(${JSON.stringify(order)})`);
    if (!node) return null;
    await click(node.x, node.y);
    await sleep(700);
    await rest();
    return node;
  }

  /** The stale states need a stale set; a simulated one is a file cited by the step the other states click. */
  async function ensureStale(input, theme, size) {
    if (input.staleSet) return;
    if (!input.firstPick) {
      await open(input, theme, size, input.freshness.stale);
      const node = await evaluate(`window.__shots.pickNode(${JSON.stringify(input.nodeOrder)})`);
      input.firstPick = node ? node.id : null;
    }
    input.chooseStale(input.firstPick);
  }

  const recipes = {
    async 'initial'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const node = await evaluate(`window.__shots.pickNode(${JSON.stringify(input.nodeOrder)})`);
      if (node && !input.firstPick) input.firstPick = node.id;
      await rest();
      return { frames, did: STATES.initial };
    },
    async 'select-node'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const node = await clickNode(input, input.nodeOrder);
      if (!node) return { skip: 'no step card visible to click' };
      return { frames, did: `clicked ${node.id}`, target: { node: node.id, preferred: node.preferred } };
    },
    async 'hover-node'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const node = await evaluate(`window.__shots.pickNode(${JSON.stringify(input.nodeOrder)})`);
      if (!node) return { skip: 'no step card visible to hover' };
      await hover(node.x, node.y);
      await sleep(900);
      return { frames, did: `pointer on ${node.id}`, target: { node: node.id, preferred: node.preferred } };
    },
    async 'hover-connection'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const edge = await evaluate(`window.__shots.pickEdge(${JSON.stringify(input.edgeOrder)})`);
      if (!edge) return { skip: 'no connection visible to hover' };
      await hover(edge.x, edge.y);
      await sleep(900);
      return { frames, did: `pointer on connection ${edge.id}`, target: { edge: edge.id } };
    },
    async 'focus-mode'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const node = await clickNode(input, input.nodeOrder);
      if (!node) return { skip: 'no step card visible to click' };
      await key('f');
      await sleep(900);
      return { frames, did: `clicked ${node.id}, pressed F`, target: { node: node.id, preferred: node.preferred } };
    },
    async 'focus-settled'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const node = await clickNode(input, input.nodeOrder);
      if (!node) return { skip: 'no step card visible to click' };
      await key('f');
      await sleep(7000);
      return { frames, did: `clicked ${node.id}, pressed F, waited 7 s`, target: { node: node.id, preferred: node.preferred } };
    },
    async 'legend'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const canvas = await evaluate(`window.__shots.pointOf('.mlv-canvas')`);
      if (canvas) { await click(canvas.x, canvas.y); await sleep(300); }
      await key('l');
      await sleep(500);
      await rest();
      return { frames, did: 'pressed L' };
    },
    async 'exceptions'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const chip = await evaluate(`window.__shots.pointOf('.mlv-chip--exceptions')`);
      if (!chip) return { skip: 'no "not observed" toggle (every claim is observed, or the viewer predates it)' };
      await click(chip.x, chip.y);
      await sleep(700);
      await rest();
      return { frames, did: 'turned on the "not observed" toggle' };
    },
    async 'filter'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const chips = await evaluate('window.__shots.severityChips()');
      const pick = ['low', 'medium', 'high'].map((sev) => chips.find((c) => c.severity === sev && c.count > 0)).find(Boolean);
      if (pick) {
        const p = await evaluate(`(() => { const c = [...document.querySelectorAll('.mlv-chip--btn[data-severity]')].filter((e) => e.getClientRects().length)[${pick.i}]; const b = c.getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; })()`);
        await click(p.x, p.y);
        await sleep(700);
        await rest();
        return { frames, did: `turned off ${pick.severity} severity findings (${pick.count} findings)` };
      }
      const chip = await evaluate(`window.__shots.pointOf('.mlv-chip--stage:not(:first-child)')`);
      if (!chip) return { skip: 'no finding severity or phase chip to click' };
      await click(chip.x, chip.y);
      await sleep(700);
      await rest();
      return { frames, did: 'no findings; clicked the second phase chip' };
    },
    async 'search'(input, theme, size) {
      const frames = await open(input, theme, size, input.freshness.stale);
      const box = await evaluate(`window.__shots.pointOf('.mlv-search input')`);
      if (!box) return { skip: 'no search box' };
      await click(box.x, box.y);
      await page.send('Input.insertText', { text: input.search });
      await sleep(900);
      return { frames, did: `typed "${input.search}"` };
    },
    async 'finding'(input, theme, size) {
      if (!input.findingOrder.length) return { skip: 'the document has no findings' };
      const frames = await open(input, theme, size, input.freshness.stale);
      const id = input.findingOrder[0];
      const selector = `.mlv-rail .mlv-issue[data-issue-id="${id.replace(/["\\]/g, '\\$&')}"]`;
      let row = await evaluate(`window.__shots.pointOf(${JSON.stringify(selector)})`);
      if (!row) {
        const tab = await evaluate(`window.__shots.pointOf('.mlv-rail__tab[id$="-tab-issues"]')`);
        if (tab) { await click(tab.x, tab.y); await sleep(500); }
        row = await evaluate(`window.__shots.pointOf(${JSON.stringify(selector)})`);
      }
      if (!row) return { skip: `finding ${id} is not in a visible Findings list` };
      await click(row.x, row.y);
      await sleep(900);
      // Bring the expanded row (message, suggestion, locations) into view, as a reader would scroll to it.
      const scrolled = await evaluate(`(() => {
        const li = document.querySelector(${JSON.stringify(selector)})?.closest('li');
        const panel = li && li.closest('[role="tabpanel"]');
        if (!li || !panel || li.getBoundingClientRect().bottom <= panel.getBoundingClientRect().bottom) return false;
        li.scrollIntoView({ block: 'start' });
        return true;
      })()`);
      await sleep(300);
      await rest();
      return { frames, did: `clicked finding ${id} in the Findings list${scrolled ? ', scrolled its expanded row into view' : ''}`, target: { finding: id } };
    },
    async 'stale'(input, theme, size) {
      await ensureStale(input, theme, size);
      if (!input.staleSet.length) return { skip: 'no cited file to mark stale' };
      const frames = await open(input, theme, size, input.staleSet);
      await rest();
      return { frames, did: `${input.staleSimulated ? 'simulated' : 'real'} stale: ${input.staleSet.map((s) => `${s.path} (${s.reason})`).join(', ')}` };
    },
    async 'stale-selected'(input, theme, size) {
      await ensureStale(input, theme, size);
      if (!input.staleSet.length) return { skip: 'no cited file to mark stale' };
      const frames = await open(input, theme, size, input.staleSet);
      const node = await clickNode(input, input.staleNodeOrder.concat(input.nodeOrder));
      if (!node) return { skip: 'no step card visible to click' };
      return { frames, did: `${input.staleSimulated ? 'simulated' : 'real'} stale: ${input.staleSet.map((s) => s.path).join(', ')}; clicked ${node.id}`, target: { node: node.id, citesStaleFile: input.staleNodeOrder.includes(node.id) } };
    },
    async 'narrow-selected'(input, theme) {
      const frames = await open(input, theme, NARROW, input.freshness.stale);
      const node = await clickNode(input, input.nodeOrder);
      if (!node) return { skip: 'no step card visible to click' };
      return { frames, did: `clicked ${node.id}`, target: { node: node.id, preferred: node.preferred } };
    },
  };

  for (const input of inputs) {
    process.stdout.write(`${input.label}\n`);
    for (const theme of opts.themes) {
      for (const state of opts.states) {
        const size = state === 'narrow-selected' ? NARROW : opts.size;
        try {
          const result = await recipes[state](input, theme, size);
          if (result.skip) { index.skipped.push(`${input.label} ${theme} ${state}: ${result.skip}`); process.stdout.write(`  skipped ${state}: ${result.skip}\n`); continue; }
          await snap(input, theme, size, state, result.frames, result.did, result.target);
        } catch (error) {
          index.skipped.push(`${input.label} ${theme} ${state}: failed: ${error.message}`);
          process.stdout.write(`  FAILED ${state}: ${error.message}\n`);
        }
      }
    }
  }
} finally {
  writeIndex();
  if (chrome) await chrome.close();
  server.close();
}
process.stdout.write(`${index.shots.length} screenshots, ${index.skipped.length} skipped -> ${out}\n`);
process.exitCode = index.skipped.some((s) => s.includes(': failed: ')) ? 1 : 0;
