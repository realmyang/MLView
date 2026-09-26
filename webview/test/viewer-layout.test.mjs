// Campaign 3 viewer fixes: the authored header, the canvas floor, the rail and minimap rules,
// refit and reveal, single-truncation titles, authored kind glyphs and the edge-kind vocabulary.
//
// jsdom performs no layout, so the header regression is asserted as DOM state (collapsed by
// default, the disclosure's behaviour) plus the shipped CSS constraints that make the canvas
// survive a contract-maximum header. The real-Chromium measurement of the same fix is a
// separate script run outside the gate (the Campaign 3 viewer-fix notes record it); none of this
// is a claim about how a human reads the diagram.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { WEBVIEW_ROOT, loadBundle, recordingBridge, rendererRegressionWorkflow } from './helpers.mjs';

/** The legacy question-mark glyph; no authored node may draw it. */
const QUESTION_GLYPH_PREFIX = 'M8 2.2A5.8 5.8 0 1 0 8 13.8 5.8 5.8 0 0 0 8 2.2ZM6.2 6.3';

const words = (n, seed) => {
  let s = '';
  for (let i = 0; s.length < n; i++) s += (i ? ' ' : '') + seed + i;
  return s.slice(0, n);
};

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Layout fixture',
    producer: { kind: 'host-llm', host: 'claude-code', model: 'fixture-model' }, revision: { id: 'r1' },
    request: { question: 'How does the loop update state?', scope: 'src/', entrypoints: ['src/train.py'], configuration: 'defaults' },
    phases: [{ id: 'prep', label: 'Prepare' }, { id: 'loop', label: 'Loop' }],
    nodes: [
      { id: 'a', label: 'Read the records', phase: 'prep', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'b', label: 'Update weights', phase: 'loop', kind: 'optimizer', basis: 'inferred', evidence: ['e1'] },
    ],
    edges: [{ id: 'ab', source: 'a', target: 'b', label: 'batches', kind: 'data', basis: 'observed', evidence: ['e1'] }],
    findings: [{ id: 'f1', title: 'Late reduction', message: 'm', severity: 'medium', nodeIds: ['b'], edgeIds: [], basis: 'inferred', evidence: ['e1'] }],
    evidence: [{ id: 'e1', file: 'src/train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'partial', summary: 'Core path', inspectedFiles: ['src/train.py'], limitations: ['Launcher not read.'] },
    ...overrides,
  };
}

/** Every header-visible string at its contract maximum (contracts/workflow.schema.json). */
function contractMaxHeader() {
  return doc({
    title: words(200, 'Title'),
    producer: { kind: 'host-llm', host: 'claude-code', model: 'M'.repeat(200) },
    revision: { id: 'r' + 'x'.repeat(127) },
    request: {
      question: words(4000, 'question'), scope: words(2000, 'scope'),
      entrypoints: Array.from({ length: 100 }, (_, i) => `src/${'d'.repeat(480)}/entry${i}.py`),
      configuration: words(2000, 'config'),
    },
    phases: Array.from({ length: 100 }, (_, i) => ({ id: `p${i}`, label: words(200, `phase${i}w`) })).concat([{ id: 'prep', label: 'Prepare' }, { id: 'loop', label: 'Loop' }]),
    coverage: { status: 'partial', summary: words(4000, 'summary'), inspectedFiles: ['src/train.py'], limitations: Array.from({ length: 500 }, (_, i) => words(2000, `lim${i}w`)) },
  });
}

async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  if (opts.rootWidth) root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: opts.rootWidth(), height: 798, right: opts.rootWidth(), bottom: 798 });
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  return { ...ctx, root, bridge, app };
}

function sizeCanvas(ctx, size) {
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width: size.w, height: size.h, right: size.w, bottom: size.h });
}

const resize = (ctx) => ctx.window.dispatchEvent(new ctx.window.Event('resize'));

/** Declarations the built stylesheet applies to `selector`, merged across every rule that lists it. */
function declarationsFor(css, selector) {
  const out = {};
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const selectors = m[1].split(',').map((s) => s.trim());
    if (!selectors.includes(selector)) continue;
    for (const decl of m[2].split(';')) {
      const i = decl.indexOf(':');
      if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
  }
  return out;
}

/* ── issue 1: the header ──────────────────────────────────────────────── */

test('the authored header opens collapsed: title, provenance chips, one question line and a disclosure', async () => {
  const ctx = await mount(doc());
  const panel = ctx.document.querySelector('.mlv-workflow');
  assert.equal(panel.getAttribute('data-expanded'), 'false');
  const toggle = panel.querySelector('.mlv-workflow__toggle');
  const details = panel.querySelector('.mlv-workflow__details');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(toggle.getAttribute('aria-controls'), details.id);
  assert.equal(details.hidden, true, 'scope, configuration and coverage wait behind the disclosure');
  assert.match(panel.querySelector('.mlv-workflow__title').textContent, /Layout fixture/);
  assert.equal(panel.querySelector('.mlv-workflow__producer').textContent, 'claude-code · fixture-model');
  assert.equal(panel.querySelector('.mlv-workflow__revision').textContent, 'revision r1');
  const question = panel.querySelector('.mlv-workflow__question');
  assert.equal(question.textContent, 'How does the loop update state?');
  assert.equal(question.title, 'How does the loop update state?', 'the whole question is on hover');
  assert.equal(question.closest('.mlv-workflow__details'), null, 'the question line is outside the collapsed region');
  assert.equal(panel.querySelector('.mlv-workflow__coverage-chip').textContent, 'partial');
  // Everything is still in the DOM for search, copy and assistive technology.
  assert.match(details.textContent, /Scope: src\//);
  assert.match(details.textContent, /Configuration: defaults/);
  assert.match(details.textContent, /partial · Core path/);
  assert.match(details.textContent, /1 coverage limitation/);
  ctx.app.destroy();
});

test('the disclosure expands and collapses the request details and survives a same-panel rebuild', async () => {
  const ctx = await mount(doc());
  const panel = () => ctx.document.querySelector('.mlv-workflow');
  panel().querySelector('.mlv-workflow__toggle').click();
  assert.equal(panel().getAttribute('data-expanded'), 'true');
  assert.equal(panel().querySelector('.mlv-workflow__toggle').getAttribute('aria-expanded'), 'true');
  assert.equal(panel().querySelector('.mlv-workflow__details').hidden, false);
  assert.match(ctx.document.querySelector('[aria-live="polite"]').textContent, /details shown/);
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc() });
  assert.equal(panel().getAttribute('data-expanded'), 'true', 'a re-posted revision keeps the reader\'s choice');
  panel().querySelector('.mlv-workflow__toggle').click();
  assert.equal(panel().getAttribute('data-expanded'), 'false');
  assert.equal(panel().querySelector('.mlv-workflow__details').hidden, true);
  ctx.app.destroy();
});

test('a contract-maximum header stays collapsed to its one-line form with every word in the DOM', async () => {
  const max = contractMaxHeader();
  const ctx = await mount(max);
  const panel = ctx.document.querySelector('.mlv-workflow');
  assert.equal(panel.getAttribute('data-expanded'), 'false');
  assert.equal(panel.querySelector('.mlv-workflow__details').hidden, true);
  assert.equal(panel.querySelector('.mlv-workflow__title').title, max.title);
  assert.equal(panel.querySelector('.mlv-workflow__producer').title, 'claude-code · ' + 'M'.repeat(200));
  assert.equal(panel.querySelector('.mlv-workflow__question').textContent.length, 4000);
  assert.equal(panel.querySelectorAll('.mlv-workflow__limitations li').length, 500);
  // The visible (not hidden) header holds the title, the chips and ONE question element.
  const visibleText = [...panel.children].filter((child) => !child.hidden).map((child) => child.className).join(' ');
  assert.doesNotMatch(visibleText, /mlv-workflow__details/);
  ctx.app.destroy();
});

test('the shipped CSS caps the header, lets it shrink, and gives the authored canvas a floor', async () => {
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const header = declarationsFor(css, '.mlv-workflow');
  assert.equal(header.flex, '0 1 auto', 'the header may shrink when the canvas floor needs the room');
  assert.equal(header['min-height'], '0', 'without min-height:0 a flex item never shrinks below its content');
  assert.match(header['max-height'] || '', /^\d+vh$/, 'the expanded header is height-capped');
  assert.ok(parseInt(header['max-height'], 10) <= 45, 'at most 45vh');
  assert.equal(header['overflow-y'], 'auto', 'and scrolls inside its cap');
  const body = declarationsFor(css, '.mlv-root--workflow>.mlv-body');
  assert.equal(body.flex, '1 1 0', 'basis 0: the body takes free space and never out-shrinks the header');
  assert.match(body['min-height'] || '', /^min\(320px,\s*50vh\)$/, 'the canvas keeps at least 320 px (half a short panel)');
  const title = declarationsFor(css, '.mlv-workflow__title');
  assert.equal(title['-webkit-line-clamp'], '2', 'the title is two lines at most');
  const question = declarationsFor(css, '.mlv-workflow__question');
  assert.equal(question['white-space'], 'nowrap', 'collapsed, the question is one line');
  assert.equal(question['text-overflow'], 'ellipsis');
  assert.equal(declarationsFor(css, '.mlv-workflow__details[hidden]').display, 'none');
  const chips = declarationsFor(css, '.mlv-workflow__heading>.mlv-chip');
  assert.equal(chips.display, 'block', 'a flex chip cannot ellipsise its text');
  assert.equal(chips['text-overflow'], 'ellipsis');
  assert.equal(chips['max-width'], '100%');
  const stages = declarationsFor(css, '.mlv-root--workflow .mlv-filterrow');
  assert.match(stages['max-height'] || '', /vh$/, '100 authored phases cannot push the canvas off the page');
  assert.equal(stages['overflow-y'], 'auto');
  const banner = declarationsFor(css, '#mlview-authored-error');
  assert.match(banner['max-height'] || '', /vh$/);
  assert.equal(declarationsFor(css, '.mlv-minimap.is-short').display, 'none');
});

/* ── issue 6: rail, minimap, refit, reveal, default collapse ─────────── */

test('the rail starts closed when the canvas beside it would be under 900 px, and follows the panel until the reader chooses', async () => {
  let width = 541;
  const ctx = await mount(doc(), { rootWidth: () => width });
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.hidden, true, 'at 541 px the rail would cover the canvas');
  width = 1382;
  resize(ctx);
  assert.equal(rail.hidden, false, 'a panel wide enough to dock it opens it again');
  width = 1086;
  resize(ctx);
  assert.equal(rail.hidden, true, '1086 - 360 leaves a canvas under 900 px');
  ctx.document.querySelector('button[aria-label="Toggle side rail"]').click();
  assert.equal(rail.hidden, false, 'the reader opened it');
  width = 541;
  resize(ctx);
  assert.equal(rail.hidden, false, 'after an explicit choice the width rule no longer decides');
  ctx.app.destroy();
});

test('working in the rail keeps it: a narrower panel after following evidence does not close it', async () => {
  let width = 1382;
  const ctx = await mount(doc(), { rootWidth: () => width });
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.hidden, false);
  rail.dispatchEvent(new ctx.window.Event('pointerdown', { bubbles: true }));
  width = 691;
  resize(ctx);
  assert.equal(rail.hidden, false, 'the split beside the source must not take the finding away');
  ctx.app.destroy();
});

test('selecting a finding opens a collapsed rail', async () => {
  const ctx = await mount(doc(), { rootWidth: () => 541 });
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.hidden, true);
  ctx.app.focusIssue('f1');
  assert.equal(rail.hidden, false);
  assert.equal(ctx.app.getState().selection.id, 'f1');
  ctx.app.destroy();
});

test('an unmeasurable root leaves the rail open (jsdom, detached mounts)', async () => {
  const ctx = await mount(doc());
  assert.equal(ctx.document.querySelector('.mlv-rail').hidden, false);
  ctx.app.destroy();
});

test('the minimap is not drawn over a canvas under 350 px tall', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const minimap = ctx.document.querySelector('.mlv-minimap');
  assert.equal(minimap.classList.contains('is-short'), false);
  sizeCanvas(ctx, { w: 900, h: 300 });
  resize(ctx);
  assert.equal(minimap.classList.contains('is-short'), true);
  sizeCanvas(ctx, { w: 900, h: 500 });
  resize(ctx);
  assert.equal(minimap.classList.contains('is-short'), false);
  ctx.app.destroy();
});

test('a large resize refits a viewport nobody moved, and never one the reader moved', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  sizeCanvas(ctx, { w: 300, h: 450 });
  ctx.app.view.fit();
  const narrow = ctx.app.getState().viewport.zoom;
  sizeCanvas(ctx, { w: 300, h: 440 });
  resize(ctx);
  assert.equal(ctx.app.getState().viewport.zoom, narrow, 'a 10 px settle keeps the picture');
  sizeCanvas(ctx, { w: 1382, h: 600 });
  resize(ctx);
  const wide = ctx.app.getState().viewport.zoom;
  assert.ok(wide > narrow, `widening refits (${narrow} -> ${wide})`);
  ctx.document.querySelector('button[aria-label="Zoom in"]').click();
  const zoomed = ctx.app.getState().viewport.zoom;
  sizeCanvas(ctx, { w: 541, h: 450 });
  resize(ctx);
  assert.equal(ctx.app.getState().viewport.zoom, zoomed, 'a reader-set zoom is never refitted');
  ctx.app.destroy();
});

test('Fit after widening re-runs the first-paint plan; after zooming out below the floor it still fits the whole', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  const fitButton = () => ctx.document.querySelector('button[aria-label="Fit to view"]');
  sizeCanvas(ctx, { w: 400, h: 300 });
  ctx.app.view.fit();
  const small = ctx.app.getState().viewport.zoom;
  assert.ok(small < 0.5, 'the fixture opens below MIN_FIT_ZOOM in a small canvas');
  sizeCanvas(ctx, { w: 1382, h: 431 });
  fitButton().click();
  const refit = ctx.app.getState().viewport.zoom;
  assert.ok(refit >= small, `Fit after widening must not zoom out (${small} -> ${refit})`);
  const firstPaint = refit;
  // HOSTS-UX-FITZOOM still holds for a reader who zoomed out past the floor.
  for (let i = 0; i < 8; i++) ctx.document.querySelector('button[aria-label="Zoom out"]').click();
  assert.ok(ctx.app.getState().viewport.zoom < 0.5);
  fitButton().click();
  assert.ok(ctx.app.getState().viewport.zoom <= firstPaint, 'below the floor Fit shows the whole document');
  ctx.app.destroy();
});

test('a finding or rail item selected below the detail threshold zooms to its target', async () => {
  const ctx = await mount(rendererRegressionWorkflow(48));
  ctx.app.view.viewport.set({ zoom: 0.2 });
  ctx.app.focusIssue('finding-a');
  assert.equal(ctx.app.getState().viewport.zoom, 0.9, 'READABLE_ZOOM');
  // Above the threshold the zoom is left alone and the target is only centred.
  ctx.app.view.viewport.set({ zoom: 0.7 });
  ctx.app.focusIssue('finding-b');
  assert.equal(ctx.app.getState().viewport.zoom, 0.7);
  // An Outline row is a rail item too.
  ctx.app.view.viewport.set({ zoom: 0.25 });
  ctx.app.setRailTab('outline');
  const row = ctx.document.querySelector('[data-outline-id="node-12"] .mlv-outline__row') || ctx.document.querySelector('[data-outline-id] .mlv-outline__row');
  row.click();
  assert.ok(ctx.app.getState().viewport.zoom >= 0.62, 'the outline selection is readable');
  ctx.app.destroy();
});

test('an edge-only finding reveals its connection', async () => {
  const document = doc({ findings: [{ id: 'fe', title: 'Edge finding', message: 'm', severity: 'low', nodeIds: [], edgeIds: ['ab'], basis: 'inferred', evidence: ['e1'] }] });
  const ctx = await mount(document);
  ctx.app.view.viewport.set({ zoom: 0.2 });
  ctx.app.focusIssue('fe');
  assert.ok(ctx.app.getState().viewport.zoom >= 0.62);
  ctx.app.destroy();
});

test('an authored group that holds a finding target is never folded by the size rule', async () => {
  const phases = [{ id: 'p', label: 'P' }];
  const nodes = [
    { id: 'loop', label: 'Main loop', phase: 'p', kind: 'group', basis: 'observed', evidence: [] },
    { id: 'side', label: 'Side work', phase: 'p', kind: 'group', basis: 'observed', evidence: [] },
  ];
  for (let i = 0; i < 14; i++) nodes.push({ id: `l${i}`, label: `Loop step ${i}`, phase: 'p', parent: 'loop', basis: 'observed', evidence: ['e1'] });
  for (let i = 0; i < 14; i++) nodes.push({ id: `s${i}`, label: `Side step ${i}`, phase: 'p', parent: 'side', basis: 'observed', evidence: ['e1'] });
  const document = doc({ phases, nodes, edges: [], findings: [{ id: 'f', title: 'T', message: 'm', severity: 'high', nodeIds: ['l7'], edgeIds: [], basis: 'inferred', evidence: ['e1'] }] });
  const ctx = await mount(document);
  assert.deepEqual([...ctx.app.getState().collapsed], ['side'], 'only the group without a finding target folds');
  assert.ok(ctx.document.querySelector('[data-node-id="l7"]'), 'the finding target is drawn at first paint');
  ctx.app.destroy();
});

/* ── issue 14: titles and glyphs ──────────────────────────────────────── */

test('an authored title is truncated once: whole label in the DOM, wrapped to the reserved lines', async () => {
  const label = 'Alpha beta gamma delta epsilon zeta eta theta iota kappa';
  const document = doc();
  document.nodes[1].label = label;
  const ctx = await mount(document);
  const card = ctx.document.querySelector('[data-node-id="b"]');
  const title = card.querySelector('.mlv-node__title');
  assert.equal(title.textContent, label, 'no middle ellipsis in the DOM');
  assert.ok(title.classList.contains('mlv-node__title--wrap'));
  assert.equal(title.style.getPropertyValue('--mlv-title-lines'), '3');
  const short = ctx.document.querySelector('[data-node-id="a"]');
  assert.equal(short.querySelector('.mlv-node__title').style.getPropertyValue('--mlv-title-lines'), '1');
  assert.equal(parseFloat(card.style.height) - parseFloat(short.style.height), 36, 'two extra 18 px title lines are reserved');
  // The SVG export draws the same lines.
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="svg"]').click();
  const frame = ctx.bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
  for (const line of ['Alpha beta gamma delta', 'epsilon zeta eta theta', 'iota kappa']) assert.match(svg, new RegExp('>' + line + '<'));
  ctx.app.destroy();
});

test('authored kinds draw mapped glyphs, never the question mark; uncertainty follows basis unresolved', async () => {
  const kinds = { k1: 'preprocessing', k2: 'transform', k3: 'Configuration', k4: 'config', k5: 'eval', k6: 'evaluation', k7: 'objective', k8: 'loss', k9: 'data-source', k10: 'dataset', k11: 'something-new', k12: 'operation', k13: 'checkpoint', k14: 'scheduler', k15: 'state_update', k16: 'state' };
  const nodes = Object.entries(kinds).map(([id, kind]) => ({ id, label: id, phase: 'prep', kind, basis: id === 'k11' ? 'unresolved' : 'observed', evidence: ['e1'] }));
  nodes.push({ id: 'g', label: 'Group', phase: 'loop', kind: 'group', basis: 'observed', evidence: [] });
  nodes.push({ id: 'gc', label: 'Child', phase: 'loop', parent: 'g', basis: 'observed', evidence: ['e1'] });
  const ctx = await mount(doc({ nodes, edges: [], findings: [] }));
  const glyph = (id) => ctx.document.querySelector(`[data-node-id="${id}"] .mlv-icon path`).getAttribute('d');
  for (const id of [...Object.keys(kinds), 'g', 'gc']) assert.ok(!glyph(id).startsWith(QUESTION_GLYPH_PREFIX), `${id} (${kinds[id] || 'no kind'}) must not draw the question mark`);
  assert.equal(glyph('k1'), glyph('k2'), 'preprocessing draws the transform glyph');
  assert.equal(glyph('k3'), glyph('k4'), 'Configuration is config');
  assert.equal(glyph('k5'), glyph('k6'), 'eval is evaluation');
  assert.equal(glyph('k7'), glyph('k8'), 'objective is loss');
  assert.equal(glyph('k9'), glyph('k10'), 'data-source is a dataset');
  assert.equal(glyph('k15'), glyph('k16'), 'state_update is state');
  assert.notEqual(glyph('k13'), glyph('k14'), 'checkpoint and scheduler keep their own glyphs');
  assert.equal(glyph('k11'), glyph('gc'), 'an unfamiliar or absent kind draws the same neutral glyph');
  assert.notEqual(glyph('k11'), glyph('k12'));
  assert.equal(ctx.document.querySelector('[data-node-id="k11"]').getAttribute('data-basis'), 'unresolved');
  assert.equal(ctx.document.querySelector('[data-node-id="k12"]').getAttribute('data-basis'), 'observed');
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const rule = declarationsFor(css, '.mlv-node[data-basis=unresolved] .mlv-node__iconbox');
  assert.match(rule.outline || declarationsFor(css, '.mlv-node[data-basis="unresolved"] .mlv-node__iconbox').outline || '', /dashed/);
  ctx.app.destroy();
});

/* ── issue 9: edge kinds ──────────────────────────────────────────────── */

test('edge kind synonyms are drawn as the styled kinds; other kinds keep their authored text', async () => {
  const spellings = { e1: 'dataflow', e2: 'Data flow', e3: 'flow', e4: 'control-flow', e5: 'conditional-call', e6: 'state-update', e7: 'gradient', e8: 'ownership', e9: 'configuration flow', e10: 'loop', e11: 'output', e12: 'construction', e13: undefined, e14: 'call' };
  const ids = Object.keys(spellings);
  const nodes = ids.flatMap((id) => [
    { id: id + 's', label: id + ' source', phase: 'prep', basis: 'observed', evidence: ['e1'] },
    { id: id + 't', label: id + ' target', phase: 'loop', basis: 'observed', evidence: ['e1'] },
  ]);
  const edges = ids.map((id) => ({ id, source: id + 's', target: id + 't', label: id + ' label', basis: 'observed', evidence: ['e1'], ...(spellings[id] ? { kind: spellings[id] } : {}) }));
  const ctx = await mount(doc({ nodes, edges, findings: [] }));
  const expected = { e1: 'data', e2: 'data', e3: 'data', e4: 'control', e5: 'control', e6: 'state', e7: 'state', e8: 'state', e9: 'config', e10: 'loop', e11: 'output', e12: 'unknown', e13: 'unknown', e14: 'call' };
  for (const id of ids) {
    const g = ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"]`);
    assert.ok(g.classList.contains('mlv-edge--' + expected[id]), `${id} (${spellings[id]}) is drawn as ${expected[id]}`);
  }
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="e12"]').getAttribute('data-edge-kind'), 'construction');
  assert.doesNotMatch(ctx.document.querySelector('.mlv-edge[data-edge-id="e13"] .mlv-edge__hit').getAttribute('aria-label'), /unknown/);
  // The inspector names what the author wrote.
  const chip = (id) => {
    ctx.app.select({ kind: 'edge', id }, { tab: 'inspector' });
    return ctx.document.querySelector('.mlv-insp__edgekind').textContent;
  };
  assert.equal(chip('e1'), 'data · authored as dataflow');
  assert.equal(chip('e12'), 'construction');
  assert.equal(chip('e13'), 'kind not specified');
  assert.equal(chip('e14'), 'call');
  // The legend has the new rows, calls the catch-all "other", and lists this diagram's other kinds.
  const legend = ctx.document.querySelector('.mlv-legend');
  for (const kind of ['state', 'loop', 'output']) assert.ok(legend.querySelector(`[data-legend-row="edge:${kind}"]`), kind + ' has a legend row');
  const other = legend.querySelector('[data-legend-row="edge:unknown"]');
  assert.match(other.textContent, /other/);
  assert.match(other.nextElementSibling.textContent, /In this diagram: construction\./);
  assert.match(other.nextElementSibling.textContent, /1 connection has no kind\./);
  // Open arrowheads are stroked, so they draw (edge.css `.mlv-arrow--open`).
  for (const kind of ['call', 'control', 'loop', 'output']) assert.ok(ctx.document.querySelector(`#mlv-arrow-${kind}`).querySelector('.mlv-arrow--open'), kind + ' head is open');
  for (const kind of ['data', 'state']) assert.equal(ctx.document.querySelector(`#mlv-arrow-${kind} .mlv-arrow--open`), null, kind + ' head is filled');
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  assert.match(declarationsFor(css, '.mlv-arrow').fill || '', /var\(--mlv-edge\)/);
  assert.equal(declarationsFor(css, '.mlv-arrow.mlv-arrow--open').fill, 'none');
  ctx.app.destroy();
});
