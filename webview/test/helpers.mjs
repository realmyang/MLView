/**
 * Shared test helpers. Every test runs against the BUILT bundle in dist/, which
 * is what the VS Code webview and the standalone report actually load.
 */

import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

export const HERE = dirname(fileURLToPath(import.meta.url));
export const WEBVIEW_ROOT = join(HERE, '..');
export const REPO_ROOT = join(WEBVIEW_ROOT, '..');
export const DIST_JS = join(WEBVIEW_ROOT, 'dist', 'mlview.js');
export const DIST_CSS = join(WEBVIEW_ROOT, 'dist', 'mlview.css');
/**
 * The readable concatenation of the nine source layers (BUILD-01).
 *
 * `dist/mlview.css` is now MINIFIED, so a gate that asserts authored structure
 * -- a selector written a particular way, a layer marker, a declaration spelled
 * with its space after the colon -- reads this file instead. It is not a
 * different stylesheet: `bundle.test.mjs` proves byte for byte that the shipped
 * file is exactly `minifyCss(dev)`, so an assertion here is an assertion about
 * what ships.
 */
export const DIST_CSS_DEV = join(WEBVIEW_ROOT, 'dist', 'mlview.dev.css');
export const SAMPLE_PATH = join(REPO_ROOT, 'contracts', 'graph.sample.json');

export async function readBundle() {
  return readFile(DIST_JS, 'utf8');
}

export async function readSample() {
  return JSON.parse(await readFile(SAMPLE_PATH, 'utf8'));
}

/** A jsdom window with the built bundle evaluated in it. */
export async function loadBundle() {
  const code = await readBundle();
  // jsdom cannot navigate, and the standalone bridge deliberately tries a
  // vscode://file navigation; that is expected here, so keep it out of the log.
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', () => undefined);
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'https://mlview.test/',
    virtualConsole,
  });
  // jsdom 26 has no structuredClone; dagre uses it. Every real host (Chromium in
  // the VS Code webview, any current browser for the standalone report) ships it,
  // so this shim closes a jsdom gap rather than a product gap.
  if (typeof dom.window.structuredClone !== 'function') {
    dom.window.structuredClone = deepClone;
  }
  const script = dom.window.document.createElement('script');
  script.textContent = code;
  dom.window.document.head.appendChild(script);
  if (!dom.window.MLView) throw new Error('bundle did not define window.MLView');
  return { dom, window: dom.window, document: dom.window.document, MLView: dom.window.MLView };
}

/** A bridge that records every posted message, for the parity test. */
export function recordingBridge(window, host = 'standalone', overrides = {}) {
  const posted = [];
  let listener = null;
  return {
    host,
    theme: 'light',
    capabilities: {
      canOpenSource: true,
      canReanalyze: host === 'vscode',
      canExport: host === 'vscode',
      canAskAssistant: false,
      ...(overrides.capabilities || {}),
    },
    posted,
    post(msg) {
      posted.push(msg);
    },
    onMessage(cb) {
      listener = cb;
      return () => {
        listener = null;
      };
    },
    send(msg) {
      if (listener) listener(msg);
    },
    saveState(s) {
      this.saved = s;
    },
    loadState() {
      return overrides.state || null;
    },
  };
}

const HEX = '0123456789abcdef';

function idOf(prefix, n) {
  let s = '';
  let v = n + 1;
  for (let i = 0; i < 12; i++) {
    s = HEX[v % 16] + s;
    v = Math.floor(v / 16) + 7 * (i + 1);
  }
  return prefix + s;
}

const STAGES = [
  ['config', 'Configuration'],
  ['data', 'Data'],
  ['preprocess', 'Preprocess'],
  ['model', 'Model'],
  ['objective', 'Objective'],
  ['train', 'Train'],
  ['eval', 'Evaluate'],
  ['deliver', 'Save / Deploy'],
];

const KINDS = ['dataset', 'dataloader', 'split', 'transform', 'model', 'layer', 'loss', 'optimizer', 'metric', 'checkpoint'];
const EDGE_KINDS = ['data', 'call', 'control', 'config'];

function loc(file, line) {
  return {
    file,
    absFile: '/w/' + file,
    line,
    col: 4,
    endLine: line + 1,
    endCol: 20,
    symbol: 'sym' + line,
    snippet: 'x = f(' + line + ')',
  };
}

/**
 * A deterministic synthetic graph: `nodes` nodes spread over the eight stages
 * with one group per stage, and `edges` typed edges including back-edges and
 * cross-lane edges. Used for the layout perf assertion (amendment A7).
 */
export function makeSyntheticGraph(nodeCount = 150, edgeCount = 300) {
  const nodes = [];
  const groupPerStage = new Map();
  for (let i = 0; i < nodeCount; i++) {
    const stageIndex = i % STAGES.length;
    const [stage] = STAGES[stageIndex];
    const id = idOf('n:', i);
    const isGroup = i < STAGES.length;
    if (isGroup) groupPerStage.set(stage, id);
    const parent = !isGroup && i % 3 === 0 ? groupPerStage.get(stage) || null : null;
    nodes.push({
      id,
      kind: isGroup ? 'model' : KINDS[i % KINDS.length],
      level: isGroup ? 'unit' : 'op',
      stage,
      label: 'node_' + i,
      sublabel: 'synthetic ' + i,
      qualname: 'mod' + stageIndex + '.node_' + i,
      framework: 'torch',
      loc: loc('mod' + stageIndex + '.py', i + 1),
      parent,
      attrs: { idx: String(i) },
      produces: [{ name: 'v' + i, tags: ['FEATURES'] }],
      consumes: [],
      ghost: false,
      dynamic: i % 37 === 0,
      confidence: 0.9,
      confidenceBucket: 'certain',
      issueIds: [],
      collapsedByDefault: false,
      stageEvidence: [{ kind: 'knowledge_table', detail: 'synthetic', weight: 1 }],
    });
  }

  const edges = [];
  for (let i = 0; i < edgeCount; i++) {
    const a = nodes[(i * 7) % nodes.length];
    const b = nodes[(i * 13 + 5) % nodes.length];
    if (a.id === b.id) continue;
    const kind = EDGE_KINDS[i % EDGE_KINDS.length];
    const edge = {
      id: idOf('e:', i),
      kind,
      source: a.id,
      target: b.id,
      label: 'v' + i,
      loc: loc(a.loc.file, a.loc.line),
      tags: [],
      confidence: 0.9,
      issueIds: [],
    };
    if (kind === 'control' && i % 8 === 0) edge.subkind = 'back';
    edges.push(edge);
  }

  const issues = [];
  const severities = ['low', 'medium', 'high'];
  for (let i = 0; i < 24; i++) {
    const node = nodes[(i * 5 + 2) % nodes.length];
    const severity = severities[i % 3];
    const issue = {
      id: idOf('i:', i),
      code: 'MLV' + (100 + (i % 9)),
      ruleVersion: 1,
      severity,
      confidence: 0.8,
      confidenceBucket: 'likely',
      title: 'Synthetic finding ' + i,
      message: 'Synthetic message ' + i,
      why: 'Because.',
      fixHint: 'Fix it.',
      loc: node.loc,
      relatedLocs: [],
      nodeIds: [node.id],
      edgeIds: [],
      stage: node.stage,
      frameworks: ['torch'],
      tags: [],
      evidence: [],
      suppressed: i % 11 === 0,
      docs: 'docs/rules/MLV101.md',
    };
    issues.push(issue);
    node.issueIds.push(issue.id);
  }

  const counts = { low: 0, medium: 0, high: 0 };
  for (const issue of issues) counts[issue.severity]++;

  return {
    schemaVersion: '1.0',
    generator: { name: 'mlview', version: '0.1.0', rendererSha: '0'.repeat(64), generatedAt: '2026-09-06T00:00:00Z' },
    workspace: {
      root: '/w',
      entrypoints: ['mod0.py'],
      filesAnalyzed: 8,
      filesFailed: 0,
      notebooksSkipped: 0,
      frameworks: ['torch'],
    },
    stages: STAGES.map(([id, label], order) => ({
      id,
      label,
      order,
      present: true,
      nodeCount: nodes.filter((n) => n.stage === id).length,
      issueCounts: { low: 0, medium: 0, high: 0 },
      maxSeverity: null,
    })),
    nodes,
    edges,
    issues,
    diagnostics: [],
    stats: { nodes: nodes.length, edges: edges.length, issues: counts, suppressed: 0, durationMs: 1, truncated: false },
  };
}

function deepClone(value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(deepClone);
  if (value instanceof Date) return new Date(value.getTime());
  if (value instanceof Map) {
    const out = new Map();
    for (const [k, v] of value) out.set(deepClone(k), deepClone(v));
    return out;
  }
  if (value instanceof Set) {
    const out = new Set();
    for (const v of value) out.add(deepClone(v));
    return out;
  }
  const out = {};
  for (const key of Object.keys(value)) out[key] = deepClone(value[key]);
  return out;
}
