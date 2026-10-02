import assert from 'node:assert/strict';
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

/* ── the cascade, for the rules jsdom resolves wrongly ──────────────────────────────────────── */

/** Split `a, b` at top-level commas (not inside parentheses or brackets). */
function splitTop(text) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '(' || c === '[') depth++;
    else if (c === ')' || c === ']') depth--;
    else if (c === ',' && depth === 0) {
      out.push(text.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(text.slice(start).trim());
  return out.filter(Boolean);
}

/** The specificity of one complex selector, as [ids, classes/attributes/pseudo-classes, types]. */
export function specificity(selector) {
  let a = 0, b = 0, c = 0;
  let s = selector;
  const max = (list) => splitTop(list).map(specificity).reduce((m, x) => (cmp(x, m) > 0 ? x : m), [0, 0, 0]);
  // Functional pseudo-classes first: :where() adds nothing; :not(), :is() and :has() add their most
  // specific argument.
  for (;;) {
    const m = /:(where|not|is|has)\(/.exec(s);
    if (!m) break;
    let depth = 1;
    let i = m.index + m[0].length;
    for (; i < s.length && depth; i++) {
      if (s[i] === '(') depth++;
      else if (s[i] === ')') depth--;
    }
    const inner = s.slice(m.index + m[0].length, i - 1);
    if (m[1] !== 'where') {
      const x = max(inner);
      a += x[0]; b += x[1]; c += x[2];
    }
    s = s.slice(0, m.index) + ' ' + s.slice(i);
  }
  s = s.replace(/\[[^\]]*\]/g, () => { b++; return ' '; });
  s = s.replace(/::[\w-]+(\([^)]*\))?/g, () => { c++; return ' '; });
  s = s.replace(/:[\w-]+(\([^)]*\))?/g, () => { b++; return ' '; });
  s = s.replace(/#[\w-]+/g, () => { a++; return ' '; });
  s = s.replace(/\.[\w-]+/g, () => { b++; return ' '; });
  for (const part of s.split(/[\s>+~]+/)) if (/^[a-zA-Z][\w-]*$/.test(part)) c++;
  return [a, b, c];
}

function cmp(x, y) {
  return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
}

/** Every style rule of `css` in source order, outside `@media print` (comments stripped). */
export function screenRules(css) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = [];
  const walk = (body) => {
    let i = 0;
    while (i < body.length) {
      const open = body.indexOf('{', i);
      if (open < 0) break;
      const prelude = body.slice(i, open).trim();
      let depth = 1;
      let j = open + 1;
      for (; j < body.length && depth; j++) {
        if (body[j] === '{') depth++;
        else if (body[j] === '}') depth--;
      }
      const inner = body.slice(open + 1, j - 1);
      if (prelude.startsWith('@')) {
        if (/^@media\b/.test(prelude) && !/\bprint\b/.test(prelude)) walk(inner);
      } else {
        const decls = {};
        for (const part of inner.split(';')) {
          const k = part.indexOf(':');
          if (k > 0) decls[part.slice(0, k).trim()] = part.slice(k + 1).trim();
        }
        rules.push({ selectors: splitTop(prelude), decls });
      }
      i = j;
    }
  };
  walk(text);
  return rules;
}

/**
 * The declared value of `property` that wins on `element` under the real cascade (specificity, then
 * source order), from the stylesheet text. jsdom's `getComputedStyle` lets the later rule win
 * whatever its specificity, so it cannot catch a reset that outranks a component rule. Returns
 * `{ value, selector }`, or null when no rule sets the property (it is inherited or initial).
 */
export function cascadeWinner(css, element, property) {
  let best = null;
  screenRules(css).forEach((rule, order) => {
    if (!(property in rule.decls)) return;
    for (const selector of rule.selectors) {
      if (selector.includes('::')) continue;
      let hit = false;
      try {
        hit = element.matches(selector);
      } catch (_e) {
        hit = false;
      }
      if (!hit) continue;
      const spec = specificity(selector);
      if (!best || cmp(spec, best.spec) > 0 || (cmp(spec, best.spec) === 0 && order >= best.order)) {
        best = { spec, order, value: rule.decls[property], selector };
      }
    }
  });
  return best ? { value: best.value, selector: best.selector } : null;
}

/* ── shaped synthetic documents (viewer M3: the review walk and the phase overview) ──────────── */

export function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/**
 * A document with a given shape: phases, steps (some in groups, listed out of phase order),
 * connections, findings citing several steps (in several phases) or connections, a number of
 * inferred or unresolved claims of each kind, steps without quotes, and notebook-cell quotes.
 */
export function shapedWorkflow(spec) {
  const rand = lcg(spec.seed);
  const pick = (n) => Math.floor(rand() * n);
  const phases = Array.from({ length: spec.phases }, (_, i) => ({ id: 'p' + i, label: 'Phase ' + i }));
  const phaseOf = (i) => 'p' + Math.min(spec.phases - 1, Math.floor((i * spec.phases) / spec.nodes));
  const nodes = Array.from({ length: spec.nodes }, (_, i) => ({ id: 'n' + i, label: 'Step ' + i, phase: phaseOf(i), kind: 'operation', basis: 'observed', evidence: [] }));
  // Groups: a group step and its children, all in the group's phase.
  for (const [g, size] of spec.groups.entries()) {
    const phase = 'p' + (g % spec.phases);
    const members = nodes.filter((n) => n.phase === phase).slice(0, size + 1);
    assert.ok(members.length === size + 1, 'phase ' + phase + ' has room for a group of ' + size);
    const [head, ...children] = members;
    head.kind = 'group';
    for (const child of children) child.parent = head.id;
  }
  const evidence = [];
  const cite = (count) => {
    const ids = [];
    for (let k = 0; k < count; k++) {
      const id = 'ev' + evidence.length;
      const notebook = rand() < spec.notebookShare;
      const line = 1 + pick(40);
      evidence.push(notebook
        ? { id, file: 'notes.ipynb', cell: pick(30), line: 1 + pick(5), endLine: 1 + pick(5) + 5, quote: 'cell_code_' + id + '()' }
        : { id, file: 'src/file' + pick(4) + '.py', line, endLine: line + pick(3), quote: 'code_' + id + '()' });
      ids.push(id);
    }
    return ids;
  };
  const steps = nodes.slice();
  for (let i = 0; i < spec.notObserved.steps; i++) steps[(i * 7 + 3) % steps.length].basis = i % 2 ? 'unresolved' : 'inferred';
  let empty = spec.emptyEvidence;
  for (const node of nodes) {
    // A step without quotes is either a group head or unresolved (the contract's only two cases).
    if (empty > 0 && (node.kind === 'group' || node.basis === 'unresolved')) {
      empty--;
      continue;
    }
    node.evidence = cite(1 + pick(spec.maxEvidence));
  }
  assert.equal(empty, 0, 'the fixture places every step without quotes');
  const edges = [];
  for (let i = 0; i < spec.edges; i++) {
    let source = pick(spec.nodes);
    let target = pick(spec.nodes);
    if (target === source) target = (source + 1) % spec.nodes;
    edges.push({ id: 'c' + i, source: 'n' + source, target: 'n' + target, label: 'flow ' + i, kind: i % 5 ? 'data' : 'control', basis: 'observed', evidence: cite(1 + pick(spec.maxEvidence)) });
  }
  for (let i = 0; i < spec.notObserved.connections; i++) edges[(i * 11 + 2) % edges.length].basis = i % 3 ? 'inferred' : 'unresolved';
  const severities = ['high', 'medium', 'low'];
  const findings = spec.findings.map((f, i) => {
    const nodeIds = [];
    while (nodeIds.length < f.nodes) {
      const id = 'n' + pick(spec.nodes);
      if (!nodeIds.includes(id)) nodeIds.push(id);
    }
    const edgeIds = [];
    while (edgeIds.length < (f.edges || 0)) {
      const id = 'c' + pick(spec.edges);
      if (!edgeIds.includes(id)) edgeIds.push(id);
    }
    return { id: 'f' + i, title: 'Finding ' + i, message: 'Synthetic finding ' + i + '.', severity: severities[i % 3], nodeIds, edgeIds,
      basis: i < spec.notObserved.findings ? 'inferred' : 'observed', evidence: cite(1) };
  });
  // Document order is not drawn order: list the steps rotated, so later phases come first.
  const rotated = nodes.slice(Math.floor(spec.nodes / 3)).concat(nodes.slice(0, Math.floor(spec.nodes / 3)));
  return {
    workflowVersion: '1.0', title: spec.title, producer: { kind: 'host-llm', host: 'claude-code', model: 'synthetic' },
    revision: { id: spec.revision || 'syn-r1' },
    request: { question: 'How is the model trained?', scope: 'src/' },
    phases, nodes: rotated, edges, findings, evidence,
    coverage: { status: 'scoped', summary: 'Synthetic coverage.', inspectedFiles: ['notes.ipynb', 'src/file0.py'], limitations: [] },
  };
}

/** The vit-cc shape: 79 claims = 31 + 41 + 7, of which 7 are not observed (0 + 3 + 4). */
export const VIT_SHAPE = {
  seed: 7, title: 'Synthetic: the vit-cc shape', phases: 6, nodes: 31, groups: [4, 4], edges: 41,
  findings: [{ nodes: 3 }, { nodes: 3 }, { nodes: 3 }, { nodes: 1 }, { nodes: 3 }, { nodes: 2 }, { nodes: 3 }],
  notObserved: { steps: 0, connections: 3, findings: 4 }, emptyEvidence: 0, notebookShare: 0.84, maxEvidence: 2,
};
/** The yolov5-cc2 shape: 176 claims = 59 + 113 + 4, of which 16 are not observed (4 + 10 + 2). */
export const YOLO_SHAPE = {
  seed: 5, title: 'Synthetic: the yolov5-cc2 shape', phases: 4, nodes: 59, groups: [12, 8], edges: 113,
  findings: [{ nodes: 5 }, { nodes: 2, edges: 1 }, { nodes: 2 }, { nodes: 1 }],
  notObserved: { steps: 4, connections: 10, findings: 2 }, emptyEvidence: 2, notebookShare: 0, maxEvidence: 12,
};
