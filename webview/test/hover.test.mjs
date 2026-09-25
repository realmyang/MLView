// Hover trace lifecycle with the real 400 ms / 120 ms intent timers
// (RENDER-1, RENDER-19).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function workflow(revision = 'r1') {
  return {
    workflowVersion: '1.0', title: 'Hover fixture',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: revision },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'load', label: 'Load' }, { id: 'loop', label: 'Loop' }],
    nodes: [
      { id: 'read', label: 'Read', phase: 'load', basis: 'observed', evidence: ['e'] },
      { id: 'other', label: 'Other', phase: 'load', basis: 'observed', evidence: ['e'] },
      { id: 'loop', label: 'Loop', phase: 'loop', kind: 'group', basis: 'inferred', evidence: [] },
      { id: 'step', label: 'Step', phase: 'loop', parent: 'loop', basis: 'observed', evidence: ['e'] },
      { id: 'eval', label: 'Eval', phase: 'loop', parent: 'loop', basis: 'observed', evidence: ['e'] },
    ],
    edges: [
      { id: 'a', source: 'read', target: 'step', label: 'batches', basis: 'observed', evidence: ['e'] },
      { id: 'b', source: 'step', target: 'eval', label: 'weights', basis: 'observed', evidence: ['e'] },
    ],
    findings: [],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

async function mount({ reducedMotion = false } = {}) {
  const ctx = await loadBundle();
  if (reducedMotion) {
    ctx.window.matchMedia = (query) => ({
      media: query, matches: /prefers-reduced-motion:\s*reduce/.test(query),
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    });
  }
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow(), recordingBridge(ctx.window, 'vscode'));
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const tooltip = ctx.document.querySelector('.mlv-tooltip');
  const pointer = (type, element) => element.dispatchEvent(new ctx.window.Event(type, { bubbles: false }));
  return { ...ctx, app, canvas, tooltip, pointer };
}

test('collapsing the hovered group clears the trace and the stale tooltip', async () => {
  const ctx = await mount();
  const header = ctx.document.querySelector('[data-node-id="loop"] .mlv-group__header');
  ctx.pointer('pointerenter', header);
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true, 'precondition: the settled hover traces');
  header.dispatchEvent(new ctx.window.MouseEvent('dblclick', { bubbles: true, cancelable: true }));
  assert.ok(ctx.app.getState().collapsed.includes('loop'));
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false, 'no whole-diagram dim over the new scene');
  assert.equal(ctx.tooltip.hidden, true);
  // Hover still works afterwards: the next settle traces and leaving clears it.
  const card = ctx.document.querySelector('[data-node-id="read"]');
  ctx.pointer('pointerenter', card);
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true);
  ctx.pointer('pointerleave', card);
  await wait(200);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
  ctx.app.destroy();
});

test('a revision arriving under a hovered card leaves no dimming and no tooltip', async () => {
  const ctx = await mount();
  const card = ctx.document.querySelector('[data-node-id="read"]');
  ctx.pointer('pointerenter', card);
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true);
  assert.equal(ctx.tooltip.hidden, false);
  ctx.app.setWorkflow(workflow('r2'));
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
  assert.equal(ctx.tooltip.hidden, true);
  assert.equal(ctx.document.querySelectorAll('.mlv-node.is-lit').length, 0);
  ctx.app.destroy();
});

test('a hover pending at rebuild time does not fire over the new scene', async () => {
  const ctx = await mount();
  ctx.pointer('pointerenter', ctx.document.querySelector('[data-node-id="read"]'));
  await wait(100);
  ctx.app.setWorkflow(workflow('r2'));
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
  ctx.app.destroy();
});

test('reduced motion keeps the hover-intent delays, so a sweep does not toggle the dim', async () => {
  const ctx = await mount({ reducedMotion: true });
  const cards = ['read', 'other', 'step'].map((id) => ctx.document.querySelector(`[data-node-id="${id}"]`));
  let toggles = 0;
  const observer = new ctx.window.MutationObserver((records) => {
    for (const record of records) if (record.attributeName === 'class') toggles++;
  });
  observer.observe(ctx.canvas, { attributes: true, attributeFilter: ['class'] });
  for (const card of cards) {
    ctx.pointer('pointerenter', card);
    assert.equal(ctx.canvas.classList.contains('is-tracing'), false, 'entering a card is not an immediate trace');
    ctx.pointer('pointerleave', card);
  }
  await wait(450);
  await Promise.resolve();
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
  assert.equal(toggles, 0, 'the sweep never touched the canvas classes');
  ctx.pointer('pointerenter', cards[0]);
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true, 'a settled hover still traces');
  observer.disconnect();
  ctx.app.destroy();
});
