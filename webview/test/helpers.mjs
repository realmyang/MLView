import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

export const HERE = dirname(fileURLToPath(import.meta.url));
export const WEBVIEW_ROOT = join(HERE, '..');
export const REPO_ROOT = join(WEBVIEW_ROOT, '..');
export const DIST_JS = join(WEBVIEW_ROOT, 'dist', 'mlview.js');

export async function loadBundle() {
  const code = await readFile(DIST_JS, 'utf8');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', () => undefined);
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://mlview.test/', virtualConsole,
  });
  if (typeof dom.window.structuredClone !== 'function') {
    dom.window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
  }
  const script = dom.window.document.createElement('script');
  script.textContent = code;
  dom.window.document.head.appendChild(script);
  if (!dom.window.MLView) throw new Error('bundle did not define window.MLView');
  return { dom, window: dom.window, document: dom.window.document, MLView: dom.window.MLView };
}

export function recordingBridge(window, host = 'vscode', overrides = {}) {
  const posted = [];
  let listener = null;
  return {
    host, theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false, ...(overrides.capabilities || {}) },
    posted,
    post(message) { posted.push(message); },
    onMessage(callback) { listener = callback; return () => { listener = null; }; },
    send(message) { if (listener) listener(message); },
    saveState(state) { this.saved = state; },
    loadState() { return overrides.state || null; },
  };
}

/** The renderer-regression fixture: 8 phases, 8 groups, cycles and two findings. */
export function rendererRegressionWorkflow(size = 48) {
  const phases = Array.from({ length: 8 }, (_, i) => ({ id: `phase-${i}`, label: `Phase ${i}` }));
  const evidence = Array.from({ length: size }, (_, i) => ({
    id: `ev-${i}`, file: `src/phase-${i % 8}.py`, line: i + 1, endLine: i + 1, quote: `step_${i}()`,
  }));
  const nodes = Array.from({ length: size }, (_, i) => ({
    id: `node-${i}`, label: `Step ${i}`, detail: `operation ${i}`, phase: `phase-${i % 8}`,
    kind: i < 8 ? 'group' : 'operation',
    parent: i >= 8 ? `node-${i % 8}` : undefined,
    basis: i % 3 === 0 ? 'observed' : i % 3 === 1 ? 'inferred' : 'unresolved', evidence: [`ev-${i}`],
  }));
  const edges = Array.from({ length: size + 16 }, (_, i) => ({
    id: `edge-${i}`, source: `node-${i % size}`, target: `node-${(i * 5 + 7) % size}`,
    label: `flow ${i}`, kind: i % 7 === 0 ? 'control' : 'data',
    basis: i % 2 ? 'inferred' : 'observed', evidence: [`ev-${i % size}`],
  })).filter((edge) => edge.source !== edge.target);
  return {
    workflowVersion: '1.0', title: 'Renderer regression fixture',
    producer: { kind: 'host-llm', host: 'codex', model: 'fixture' }, revision: { id: 'fixture-r1' },
    request: { question: 'Trace the complete cyclic workflow', scope: 'src/', entrypoints: ['src/phase-0.py'] },
    phases, nodes, edges,
    findings: [
      { id: 'finding-a', title: 'Review cycle', message: 'The cycle needs review.', severity: 'high', nodeIds: ['node-8'], edgeIds: ['edge-7'], basis: 'inferred', evidence: ['ev-8'] },
      { id: 'finding-b', title: 'Unresolved output', message: 'The output destination is unresolved.', severity: 'medium', nodeIds: ['node-23'], edgeIds: [], basis: 'unresolved', evidence: ['ev-23'] },
    ],
    evidence, coverage: { status: 'scoped', summary: 'Synthetic renderer coverage', inspectedFiles: phases.map((p) => `src/${p.id}.py`), limitations: [] },
  };
}

const roundNumbers = (text) => String(text ?? '').replace(/-?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi, (n) => (Math.round(Number(n) * 10) / 10).toFixed(1));

function boxOf(element) {
  const s = element.style;
  return [roundNumbers(s.left), roundNumbers(s.top), roundNumbers(s.width), roundNumbers(s.height)].join(' ');
}

/**
 * The routed picture as plain data: lane bands, cards and group boxes, edge and
 * bundle paths, and edge label placements, with every number rounded to 0.1.
 */
export function routedGeometry(document) {
  const boxes = [];
  for (const lane of document.querySelectorAll('.mlv-lane')) boxes.push(['lane', lane.getAttribute('data-stage') || lane.getAttribute('data-lane-id') || '', boxOf(lane)]);
  for (const node of document.querySelectorAll('[data-node-id]')) {
    const kind = node.classList.contains('mlv-group') ? 'group' : 'node';
    boxes.push([kind, node.getAttribute('data-node-id'), boxOf(node)]);
  }
  const routes = [];
  for (const edge of document.querySelectorAll('.mlv-edge[data-edge-id]')) {
    const path = edge.querySelector('.mlv-edge__path');
    routes.push(['edge', edge.getAttribute('data-edge-id'), roundNumbers(path && path.getAttribute('d'))]);
  }
  for (const bundle of document.querySelectorAll('.mlv-bundle')) {
    const paths = Array.from(bundle.querySelectorAll('path')).map((p) => (p.getAttribute('class') || '') + ':' + roundNumbers(p.getAttribute('d')));
    const badge = bundle.querySelector('.mlv-bundle__badge');
    routes.push(['bundle', paths.join('|'), roundNumbers(badge && badge.getAttribute('transform'))]);
  }
  const labels = [];
  for (const edge of document.querySelectorAll('.mlv-edge[data-edge-id]')) {
    const id = edge.getAttribute('data-edge-id');
    if (edge.getAttribute('data-label-hidden') === '1') { labels.push([id, 'hidden']); continue; }
    const label = edge.querySelector('.mlv-edge-label');
    if (!label) continue;
    labels.push([id, roundNumbers(label.getAttribute('x')) + ' ' + roundNumbers(label.getAttribute('y')), label.textContent,
      label.getAttribute('data-label-axis') || '', label.getAttribute('data-label-flipped') || '']);
  }
  return { boxes, routes, labels };
}
