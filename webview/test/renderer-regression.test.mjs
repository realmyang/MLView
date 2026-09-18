import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

function workflow(size = 48) {
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

async function mount(size = 48) {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow(size), bridge);
  return { ...ctx, bridge, app, canvas: ctx.document.querySelector('.mlv-canvas') };
}

function key(ctx, target, value, opts = {}) {
  target.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true, ...opts }));
}

test('large authored workflows render every phase, node, and routed connection', async () => {
  const ctx = await mount();
  assert.equal(ctx.document.querySelectorAll('.mlv-lane').length, 8);
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, 48);
  assert.ok(ctx.document.querySelectorAll('[data-edge-id]').length >= 40);
  assert.ok(ctx.document.querySelectorAll('[data-edge-id] .mlv-edge__path').length >= 40);
  ctx.app.destroy();
});

test('layout remains stable across zoom, fit, selection, and filter repaint', async () => {
  const ctx = await mount();
  const positions = () => Array.from(ctx.document.querySelectorAll('.mlv-node')).map((node) => `${node.style.left}:${node.style.top}`).join('|');
  const before = positions();
  key(ctx, ctx.canvas, '+');
  assert.ok(ctx.app.getState().viewport.zoom > 0);
  key(ctx, ctx.canvas, '0');
  ctx.app.focusNode('node-9');
  ctx.app.setFilters({ severities: ['high'] });
  assert.equal(positions(), before);
  assert.match(ctx.document.querySelector('.mlv-world').style.transform, /scale\(/);
  ctx.app.destroy();
});

test('group hierarchy collapses and expands without losing descendants', async () => {
  const ctx = await mount();
  const group = ctx.document.querySelector('[data-node-id="node-0"]');
  (group.querySelector('.mlv-group__header') || group).dispatchEvent(new ctx.window.MouseEvent('dblclick', { bubbles: true, cancelable: true }));
  assert.ok(ctx.app.getState().collapsed.includes('node-0'));
  assert.equal(ctx.document.querySelector('[data-node-id="node-8"]'), null);
  const collapsed = ctx.document.querySelector('[data-node-id="node-0"]');
  (collapsed.querySelector('.mlv-group__header') || collapsed).dispatchEvent(new ctx.window.MouseEvent('dblclick', { bubbles: true, cancelable: true }));
  assert.equal(ctx.app.getState().collapsed.includes('node-0'), false);
  assert.ok(ctx.document.querySelector('[data-node-id="node-8"]'));
  ctx.app.destroy();
});

test('keyboard navigation, focus mode, and issue cycling operate on authored data', async () => {
  const ctx = await mount();
  ctx.app.focusNode('node-8');
  key(ctx, ctx.canvas, 'f');
  assert.ok(ctx.canvas.classList.contains('is-focusing'));
  key(ctx, ctx.canvas, 'f');
  key(ctx, ctx.canvas, 'n');
  assert.equal(ctx.app.getState().selection.kind, 'issue');
  key(ctx, ctx.canvas, 'Enter');
  assert.ok(ctx.bridge.posted.some((message) => message.type === 'openLocation'));
  ctx.app.destroy();
});

test('search finds authored labels and evidence locations and Enter selects a hit', async () => {
  const ctx = await mount();
  const input = ctx.document.querySelector('.mlv-search .mlv-input');
  input.value = 'Step 23';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.ok(ctx.document.querySelectorAll('.mlv-search__results .mlv-result').length >= 1);
  key(ctx, input, 'Enter');
  assert.equal(ctx.app.getState().selection.id, 'node-23');
  input.value = 'phase-7.py:24';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.ok(ctx.document.querySelectorAll('.mlv-search__results .mlv-result').length >= 1);
  ctx.app.destroy();
});

test('scope projection and clearing preserve the complete authored document', async () => {
  const ctx = await mount();
  const all = ctx.app.getScope().of;
  ctx.app.setScope('stage:phase-3');
  assert.equal(ctx.app.getScope().spec, 'stage:phase-3');
  const scoped = Array.from(ctx.document.querySelectorAll('[data-node-id]'));
  assert.ok(scoped.length > 0 && scoped.length < all);
  assert.ok(scoped.every((node) => node.getAttribute('data-stage') === 'phase-3'));
  ctx.app.setScope(null);
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, all);
  ctx.app.destroy();
});

test('full and scoped SVG exports contain matching authored geometry and no external resources', async () => {
  const ctx = await mount();
  const exportSvg = () => {
    ctx.document.querySelector('.mlv-btn--exportmenu').click();
    ctx.document.querySelector('[data-export-action="svg"]').click();
    const frame = ctx.bridge.posted.findLast((message) => message.type === 'exportFile' && message.kind === 'svg');
    return Buffer.from(frame.base64, 'base64').toString('utf8');
  };
  const full = exportSvg();
  assert.equal((full.match(/data-node-id=/g) || []).length, 48);
  assert.doesNotMatch(full, /<foreignObject|https?:\/\/(?!www\.w3\.org\/2000\/svg)/);
  ctx.app.setScope('stage:phase-2');
  const scoped = exportSvg();
  assert.ok((scoped.match(/data-node-id=/g) || []).length < 48);
  assert.match(scoped, /Renderer regression fixture/);
  ctx.app.destroy();
});

test('repeated authored revisions produce deterministic node geometry', async () => {
  const ctx = await mount();
  const geometry = () => Array.from(ctx.document.querySelectorAll('.mlv-node')).map((node) => [node.getAttribute('data-node-id'), node.style.left, node.style.top, node.style.width, node.style.height]);
  const first = geometry();
  ctx.app.setWorkflow({ ...workflow(), revision: { id: 'fixture-r2', parent: 'fixture-r1' } });
  assert.deepEqual(JSON.parse(JSON.stringify(geometry())), JSON.parse(JSON.stringify(first)));
  ctx.app.destroy();
});
