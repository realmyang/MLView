// Webview half of the host <-> webview protocol (Campaign 1 §1e): one owner
// per frame, request/result pairs for export, copy and refine, viewport and
// composer preservation, and the theme guard.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';
import { benchmarkWorkflow } from '../tools/benchmark-model.mjs';

function workflow(revision = 'r1', overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Protocol fixture',
    producer: { kind: 'host-llm', host: 'codex', model: 'gpt-test' }, revision: { id: revision },
    request: { question: 'How is this model trained?', scope: 'src/', entrypoints: ['src/train.py'] },
    phases: [{ id: 'load', label: 'Load' }, { id: 'loop', label: 'Training' }],
    nodes: [
      { id: 'dataset', label: 'Read records', phase: 'load', basis: 'observed', evidence: ['ev-load'] },
      { id: 'step', label: 'Update weights', phase: 'loop', basis: 'observed', evidence: ['ev-step'] },
    ],
    edges: [{ id: 'flow', source: 'dataset', target: 'step', label: 'batches', basis: 'observed', evidence: ['ev-load'] }],
    findings: [{ id: 'loss-risk', title: 'Loss is aggregated late', message: 'The update uses a delayed aggregate.', severity: 'medium', nodeIds: ['step'], basis: 'inferred', evidence: ['ev-step'] }],
    evidence: [
      { id: 'ev-load', file: 'src/data.py', line: 10, endLine: 14, quote: 'load()' },
      { id: 'ev-step', file: 'src/train.py', line: 42, endLine: 47, quote: 'optimizer.step()' },
    ],
    coverage: { status: 'scoped', summary: 'Core training path inspected', inspectedFiles: ['src/train.py', 'src/data.py'], limitations: [] },
    ...overrides,
  };
}

async function mount(doc = workflow(), state = null) {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode', state ? { state } : {});
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, bridge);
  return { ...ctx, bridge, app };
}

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
const toasts = (ctx) => Array.from(ctx.document.querySelectorAll('.mlv-toast'), (t) => t.textContent);
const lastOf = (bridge, type) => bridge.posted.findLast((m) => m.type === type);
const reply = (ctx, request, outcome, extra = {}) =>
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: request.requestId, action: request.type, outcome, ...extra });

test('the App posts no ready, logs no known host frame, and applies one document object once', async () => {
  const ctx = await mount();
  assert.equal(ctx.bridge.posted.some((m) => m.type === 'ready'), false, 'only the host bootstrap posts ready');
  ctx.bridge.send({ v: 1, type: 'workflowError', message: 'Changes detected; checking diagram freshness.', retained: true, codes: ['checking'] });
  ctx.bridge.send({ v: 1, type: 'workflowError', message: '', retained: true, codes: [] });
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: 'r9-zzzz', action: 'copy', outcome: 'done' });
  assert.equal(ctx.bridge.posted.some((m) => m.type === 'log'), false, 'workflowError and actionResult are known frames');

  let renders = 0;
  const setWorkflow = ctx.app.setWorkflow.bind(ctx.app);
  ctx.app.setWorkflow = (doc, preserve) => { renders++; return setWorkflow(doc, preserve); };
  const next = workflow('r2');
  ctx.bridge.send({ v: 1, type: 'workflow', document: next });
  ctx.bridge.send({ v: 1, type: 'workflow', document: next });
  assert.equal(renders, 1, 'the same document object is applied once');
  assert.equal(ctx.document.getElementById('mlview-root').getAttribute('data-workflow-revision'), 'r2');
  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r3') });
  assert.equal(renders, 2, 'one render per later frame');
  ctx.bridge.send({ v: 1, type: 'unknownFrame' });
  assert.ok(ctx.bridge.posted.some((m) => m.type === 'log' && /unknownFrame/.test(m.message)), 'truly unknown frames are still logged');
  ctx.app.destroy();
});

test('a re-sent revision keeps the viewport; a new revision fits', async () => {
  const ctx = await mount();
  const fitted = ctx.app.getState().viewport;
  assert.equal(ctx.app.getState().workflowRevision, 'r1');
  ctx.bridge.send({ v: 1, type: 'restoreState', state: { viewport: { x: -300, y: -200, zoom: 2 } } });
  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r1') });
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().viewport)), { x: -300, y: -200, zoom: 2 });
  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r2') });
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().viewport)), JSON.parse(JSON.stringify(fitted)));
  assert.equal(ctx.app.getState().workflowRevision, 'r2');
  ctx.app.destroy();
});

test('a remount restores the saved viewport only for the same revision', async () => {
  const saved = { x: -123, y: -45, zoom: 1.7 };
  const same = await mount(workflow('r1'), { viewport: saved, workflowRevision: 'r1' });
  assert.deepEqual(JSON.parse(JSON.stringify(same.app.getState().viewport)), saved);
  same.app.destroy();
  const other = await mount(workflow('r2'), { viewport: saved, workflowRevision: 'r1' });
  assert.notDeepEqual(JSON.parse(JSON.stringify(other.app.getState().viewport)), saved, 'a different revision fits');
  other.app.destroy();
  const legacy = await mount(workflow('r1'), { viewport: saved });
  assert.notDeepEqual(JSON.parse(JSON.stringify(legacy.app.getState().viewport)), saved, 'a state without workflowRevision fits');
  legacy.app.destroy();
});

test('an open composer keeps its text, focus and selection across re-posts and closes only on done', async () => {
  const ctx = await mount();
  const q = (selector) => ctx.document.querySelector(selector);
  ctx.app.select({ kind: 'node', id: 'step' }, { tab: 'inspector' });
  q('.mlv-workflow__refine').click();
  q('.mlv-workflow__intent').value = 'custom';
  q('.mlv-workflow__intent').dispatchEvent(new ctx.window.Event('change', { bubbles: true }));
  q('.mlv-workflow__custom').value = 'Why is the loss averaged twice?';
  q('.mlv-workflow__custom').focus();
  ctx.app.select({ kind: 'edge', id: 'flow' }, { tab: 'inspector' });

  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r1') });
  assert.equal(q('.mlv-workflow__composer').hidden, false, 'a same-revision re-post keeps the composer open');
  assert.equal(q('.mlv-workflow__custom').value, 'Why is the loss averaged twice?');
  assert.equal(q('.mlv-workflow__intent').value, 'custom');
  assert.equal(ctx.document.activeElement, q('.mlv-workflow__custom'), 'focus returns to the field being typed in');
  assert.equal(q('.mlv-workflow__selection').textContent, 'node: step', 'same revision keeps the captured selection');

  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r2') });
  assert.equal(q('.mlv-workflow__composer').hidden, false);
  assert.equal(q('.mlv-workflow__custom').value, 'Why is the loss averaged twice?', 'a new revision keeps the text');
  assert.equal(q('.mlv-workflow__selection').textContent, 'edge: flow', 'a new revision re-captures the selection');

  q('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  const first = lastOf(ctx.bridge, 'refineWorkflow');
  assert.match(first.requestId, /^[A-Za-z0-9_-]{1,64}$/);
  assert.deepEqual(JSON.parse(JSON.stringify({ ...first, requestId: undefined })), {
    v: 1, type: 'refineWorkflow', revisionId: 'r2', intent: 'custom', customText: 'Why is the loss averaged twice?',
    selection: { kind: 'edge', id: 'flow' },
  });
  reply(ctx, first, 'failed', { message: 'the selection is invalid. Select the item again.' });
  assert.equal(q('.mlv-workflow__composer').hidden, false, 'a failed copy leaves the composer open');
  assert.equal(q('.mlv-workflow__status').getAttribute('role'), 'status');
  assert.equal(q('.mlv-workflow__status').textContent, 'the selection is invalid. Select the item again.');

  q('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  const second = lastOf(ctx.bridge, 'refineWorkflow');
  assert.notEqual(second.requestId, first.requestId);
  reply(ctx, first, 'done');
  assert.equal(q('.mlv-workflow__composer').hidden, false, 'an answered request id is not answered twice');
  reply(ctx, second, 'done');
  assert.equal(q('.mlv-workflow__composer').hidden, true, 'done closes the composer');
  assert.equal(q('.mlv-workflow__custom').value, '', 'done clears the custom request');
  assert.equal(q('.mlv-workflow__status').textContent, '');
  assert.equal(ctx.document.activeElement, q('.mlv-workflow__refine'), 'focus returns to Refine');
  ctx.app.destroy();
});

test('built-in intents post no customText, and a revision that drops the selected finding clears it', async () => {
  const ctx = await mount();
  const q = (selector) => ctx.document.querySelector(selector);
  ctx.app.focusIssue('loss-risk');
  q('.mlv-workflow__refine').click();
  assert.equal(q('.mlv-workflow__selection').textContent, 'issue: loss-risk');
  q('.mlv-workflow__custom').value = 'typed, then switched away';
  q('.mlv-workflow__intent').value = 'expand';
  q('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  const expand = lastOf(ctx.bridge, 'refineWorkflow');
  assert.equal(expand.intent, 'expand');
  assert.equal('customText' in expand, false);

  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow('r2', { findings: [] }) });
  assert.equal(ctx.app.getState().selection, null, 'VIEWUI-15: a removed finding is not a selection');
  assert.equal(q('.mlv-workflow__selection').textContent, 'Whole diagram');
  q('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  const posted = lastOf(ctx.bridge, 'refineWorkflow');
  assert.equal(posted.revisionId, 'r2');
  assert.equal('selection' in posted, false, 'the composer posts no stale finding id');
  ctx.app.destroy();
});

test('SVG export claims nothing before the host answers, then announces each outcome', async () => {
  const ctx = await mount();
  const live = ctx.app.liveEl;
  const exportSvg = () => {
    ctx.document.querySelector('.mlv-btn--exportmenu').click();
    ctx.document.querySelector('[data-export-action="svg"]').click();
    return lastOf(ctx.bridge, 'exportFile');
  };
  const frame = exportSvg();
  assert.equal(frame.kind, 'svg');
  assert.match(frame.requestId, /^[A-Za-z0-9_-]{1,64}$/);
  assert.equal(live.textContent, 'Saving SVG…');
  assert.equal(toasts(ctx).some((t) => /Exported/.test(t)), false, 'no success toast before the result');
  reply(ctx, frame, 'done', { name: 'diagram.svg' });
  assert.match(live.textContent, /^Exported 2 cards and 1 connections as diagram\.svg\.$/);
  assert.equal(toasts(ctx).some((t) => /Exported/.test(t)), false, 'success is the host notification, not a toast');

  reply(ctx, exportSvg(), 'cancelled');
  assert.equal(live.textContent, 'Export cancelled.');
  reply(ctx, exportSvg(), 'failed', { message: 'the file could not be written' });
  assert.equal(live.textContent, 'Export failed: the file could not be written');
  assert.ok(toasts(ctx).includes('Export failed: the file could not be written'));
  ctx.app.destroy();
});

function stubCanvas(window, url, seen) {
  window.HTMLCanvasElement.prototype.getContext = function () { return { setTransform() {}, drawImage() {} }; };
  window.HTMLCanvasElement.prototype.toDataURL = function () { seen.push([this.width, this.height]); return url; };
  window.Image = class {
    set src(_value) { setTimeout(() => this.onload && this.onload(), 0); }
  };
}

test('a PNG the browser could not allocate falls back to the SVG and posts nothing', async () => {
  const ctx = await mount();
  const seen = [];
  stubCanvas(ctx.window, 'data:,', seen);
  const before = ctx.bridge.posted.length;
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="png"]').click();
  await tick(20);
  assert.equal(seen.length, 1, 'the stub canvas was drawn');
  assert.equal(ctx.bridge.posted.slice(before).some((m) => m.type === 'exportFile'), false);
  assert.ok(toasts(ctx).includes('Could not draw the PNG here — save the SVG instead.'));
  ctx.app.destroy();
});

test('a tall PNG is drawn at a clamped scale and announces the size actually drawn', async () => {
  const ctx = await mount(benchmarkWorkflow(500));
  const seen = [];
  stubCanvas(ctx.window, 'data:image/png;base64,iVBORw0KGgo=', seen);
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="png"]').click();
  await tick(20);
  const frame = lastOf(ctx.bridge, 'exportFile');
  assert.equal(frame.kind, 'png');
  assert.equal(frame.base64, 'iVBORw0KGgo=');
  const [width, height] = seen[0];
  assert.ok(Math.max(width, height) <= 16384 && width * height <= 16384 * 16384, `canvas ${width}x${height} stays within browser limits`);
  assert.equal(ctx.app.liveEl.textContent, 'Saving PNG…');
  reply(ctx, frame, 'done', { name: 'tall.png' });
  assert.equal(ctx.app.liveEl.textContent, 'Exported ' + width + '×' + height + ' PNG as tall.png.');
  ctx.app.destroy();
});

test('scope and SVG copies toast only when the host reports the clipboard written', async () => {
  const ctx = await mount();
  ctx.app.setScope('stage:loop');
  ctx.document.querySelector('.mlv-breadcrumb__copy').click();
  const copy = lastOf(ctx.bridge, 'copy');
  assert.equal(copy.text, 'stage:loop');
  assert.match(copy.requestId, /^[A-Za-z0-9_-]{1,64}$/);
  assert.equal(toasts(ctx).some((t) => /Scope copied/.test(t)), false, 'no toast before the result');
  reply(ctx, copy, 'done');
  assert.ok(toasts(ctx).includes('Scope copied: stage:loop'));
  ctx.document.querySelector('.mlv-breadcrumb__copy').click();
  reply(ctx, lastOf(ctx.bridge, 'copy'), 'failed', { message: 'the clipboard refused the text' });
  assert.ok(toasts(ctx).includes('Could not copy the scope.'));

  ctx.app.setScope(null);
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="copy-svg"]').click();
  await tick(0);
  const svgCopy = lastOf(ctx.bridge, 'copy');
  assert.match(svgCopy.text, /^<svg|<\?xml/);
  assert.equal(toasts(ctx).some((t) => /SVG copied/.test(t)), false);
  reply(ctx, svgCopy, 'done');
  assert.ok(toasts(ctx).includes('SVG copied — 2 cards, 1 connections.'));
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="copy-svg"]').click();
  await tick(0);
  reply(ctx, lastOf(ctx.bridge, 'copy'), 'failed', { message: 'the text is too large to copy' });
  assert.equal(ctx.app.liveEl.textContent, 'The SVG could not be copied.');
  ctx.app.destroy();
});

test('at most 32 requests wait for a result, and the oldest is forgotten first', async () => {
  const ctx = await mount();
  ctx.app.setScope('stage:loop');
  const ids = [];
  for (let i = 0; i < 33; i++) {
    ctx.document.querySelector('.mlv-breadcrumb__copy').click();
    ids.push(lastOf(ctx.bridge, 'copy').requestId);
  }
  assert.equal(new Set(ids).size, 33, 'request ids are unique');
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: ids[0], action: 'copy', outcome: 'done' });
  assert.equal(toasts(ctx).some((t) => /Scope copied/.test(t)), false, 'the evicted request is not answered');
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: ids[32], action: 'copy', outcome: 'done' });
  assert.ok(toasts(ctx).includes('Scope copied: stage:loop'));
  ctx.app.destroy();
});

test('a theme word outside light, dark and hc keeps the current theme', async () => {
  const ctx = await mount();
  const root = ctx.document.getElementById('mlview-root');
  ctx.app.setTheme('dark');
  assert.equal(root.getAttribute('data-theme'), 'dark');
  ctx.app.setTheme('high-contrast');
  assert.equal(root.getAttribute('data-theme'), 'dark');
  ctx.bridge.send({ v: 1, type: 'theme', kind: 'high-contrast-light' });
  assert.equal(root.getAttribute('data-theme'), 'dark');
  ctx.bridge.send({ v: 1, type: 'theme', kind: 'hc' });
  assert.equal(root.getAttribute('data-theme'), 'hc');
  ctx.app.destroy();
});
