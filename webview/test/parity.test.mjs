/**
 * Parity: the sample rendered through the vscode bridge and through the
 * standalone bridge must produce IDENTICAL sets of data-node-id, data-edge-id
 * and data-issue-id. One renderer, two hosts (amendment A7).
 *
 * Also covers the protocol surface: every HostToUi type of CONTRACTS section 4
 * is handled, unknown types are logged and ignored, and `ready` is posted on
 * mount.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

function idsIn(document) {
  const collect = (attr) => {
    const out = [];
    for (const element of document.querySelectorAll('[' + attr + ']')) out.push(element.getAttribute(attr));
    return out.sort();
  };
  return {
    nodes: collect('data-node-id'),
    edges: collect('data-edge-id'),
    issues: collect('data-issue-id'),
  };
}

async function mountWith(host) {
  const ctx = await loadBundle();
  const posted = [];
  if (host === 'vscode') {
    ctx.window.acquireVsCodeApi = () => ({
      postMessage: (msg) => posted.push(msg),
      setState: () => undefined,
      getState: () => null,
    });
  }
  const bridge = host === 'vscode' ? ctx.MLView.bridges.vscode() : ctx.MLView.bridges.standalone({ theme: 'light', onPost: (m) => posted.push(m) });
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mount(root, sample, bridge);
  return { ...ctx, app, bridge, posted, root };
}

test('both bridges render the same node, edge and issue ids', async () => {
  const a = await mountWith('vscode');
  const b = await mountWith('standalone');
  const left = idsIn(a.document);
  const right = idsIn(b.document);
  assert.equal(left.nodes.join(','), right.nodes.join(','));
  assert.equal(left.edges.join(','), right.edges.join(','));
  assert.equal(left.issues.join(','), right.issues.join(','));
  assert.equal(left.nodes.length, sample.nodes.length, 'every node in the document is drawn');
  assert.ok(left.edges.length > 0);
  assert.equal(left.issues.length, sample.issues.length);
});

test('capabilities hide the host-only buttons in standalone', async () => {
  const a = await mountWith('vscode');
  const b = await mountWith('standalone');
  const refreshOf = (doc) => doc.querySelector('button[aria-label="Re-analyze workspace"]');
  const exportOf = (doc) => doc.querySelector('button[aria-label="Export standalone HTML report"]');
  assert.equal(refreshOf(a.document).hidden, false);
  assert.equal(exportOf(a.document).hidden, false);
  assert.equal(refreshOf(b.document).hidden, true);
  assert.equal(exportOf(b.document).hidden, true);
});

test('mount posts ready, and clicking a node posts selectNode + openLocation', async () => {
  const ctx = await mountWith('vscode');
  assert.ok(ctx.posted.some((m) => m.type === 'ready'), 'ready is posted on mount');
  const card = ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]');
  assert.ok(card);
  card.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true }));
  const select = ctx.posted.filter((m) => m.type === 'selectNode').pop();
  const open = ctx.posted.filter((m) => m.type === 'openLocation').pop();
  assert.equal(select.nodeId, 'n:7c1a90b4e2f0');
  assert.equal(open.file, 'data.py');
  assert.equal(open.line, 31);
  assert.equal(open.col, 19);
  assert.equal(open.v, 1);
});

test('clicking an edge opens the CALL SITE, not either endpoint definition', async () => {
  const ctx = await mountWith('vscode');
  const edge = ctx.document.querySelector('[data-edge-id="e:9f21ab34cd56"] .mlv-edge__hit');
  assert.ok(edge);
  edge.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true }));
  const open = ctx.posted.filter((m) => m.type === 'openLocation').pop();
  assert.equal(open.file, 'train.py');
  assert.equal(open.line, 44);
  assert.equal(open.col, 30);
});

test('every HostToUi message type is handled and unknown ones are ignored', async () => {
  const ctx = await loadBundle();
  const posted = [];
  let listener = null;
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: (cb) => {
      listener = cb;
      return () => undefined;
    },
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mount(root, null, bridge);
  assert.ok(listener, 'the app subscribed to host messages');

  const messages = [
    { v: 1, type: 'init', schemaVersion: '1.0', theme: 'dark', host: 'vscode', capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false } },
    { v: 1, type: 'analysisStarted', requestId: 'r1', scope: 'workspace' },
    { v: 1, type: 'analysisProgress', requestId: 'r1', done: 2, total: 5, file: 'train.py' },
    { v: 1, type: 'graph', requestId: 'r1', graph: sample },
    { v: 1, type: 'theme', kind: 'hc' },
    { v: 1, type: 'revealNode', nodeId: 'n:9c8d7e6f5a4b', center: true },
    { v: 1, type: 'revealIssue', issueId: 'i:1234abcd5678' },
    { v: 1, type: 'setFilter', severities: ['high'], codes: ['MLV201'], query: 'zero' },
    { v: 1, type: 'stale', changedFiles: ['train.py'] },
    { v: 1, type: 'cursorHint', file: 'train.py', line: 44 },
    { v: 1, type: 'restoreState', state: { viewport: { x: 10, y: 20, zoom: 0.8 }, selection: null, collapsed: [], filters: { severities: ['low', 'medium', 'high'], stages: [], showSuppressed: true, query: '' }, railTab: 'outline' } },
    { v: 1, type: 'analysisFailed', requestId: 'r2', message: 'python not found', detail: 'Traceback…', actions: [{ id: 'mlview.selectInterpreter', label: 'Select Interpreter' }] },
    { v: 1, type: 'somethingFromTheFuture', payload: 42 },
  ];
  for (const msg of messages) listener(msg);

  assert.equal(ctx.document.querySelector('.mlv-root').getAttribute('data-theme'), 'hc');
  assert.ok(ctx.document.querySelector('.mlv-banner--error'), 'analysisFailed raises the error banner');
  assert.ok(ctx.document.querySelector('.mlv-banner--warn'), 'stale raises a warning banner');
  assert.equal(app.getState().railTab, 'outline');
  assert.equal(app.getState().filters.showSuppressed, true);
  assert.ok(posted.some((m) => m.type === 'log' && m.message.indexOf('somethingFromTheFuture') >= 0), 'unknown type logged and ignored');
  assert.ok(ctx.document.querySelectorAll('[data-node-id]').length > 0, 'the graph still rendered');

  // A malformed message must not throw either.
  listener(null);
  listener({ type: 'graph' });
  listener({ v: 2, type: 'graph', graph: sample });
  assert.ok(ctx.document.querySelectorAll('[data-node-id]').length > 0);
  app.destroy();
});

test('view state round-trips through the bridge', async () => {
  const ctx = await loadBundle();
  let saved = null;
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: (s) => {
      saved = s;
    },
    loadState: () => ({
      viewport: { x: 5, y: 6, zoom: 0.75 },
      selection: { kind: 'node', id: 'n:7c1a90b4e2f0' },
      collapsed: ['n:5500cc66dd77'],
      filters: { severities: ['high'], stages: [], showSuppressed: false, query: '' },
      railTab: 'inspector',
    }),
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);
  const state = app.getState();
  assert.equal(state.railTab, 'inspector');
  assert.deepEqual(JSON.parse(JSON.stringify(state.filters.severities)), ['high']);
  assert.deepEqual(JSON.parse(JSON.stringify(state.collapsed)), ['n:5500cc66dd77']);
  assert.equal(Math.round(state.viewport.zoom * 100), 75);
  assert.equal(ctx.document.querySelector('[data-node-id="n:9c8d7e6f5a4b"]'), null, 'collapsed group hides its children');

  app.setFilters({ severities: ['low', 'medium', 'high'] });
  await new Promise((r) => setTimeout(r, 320));
  assert.ok(saved, 'state was saved (debounced) after a change');
  assert.equal(saved.filters.severities.length, 3);
  app.destroy();
});

test('destroy() empties the root and stops listening', async () => {
  const ctx = await mountWith('standalone');
  assert.ok(ctx.root.childElementCount > 0);
  ctx.app.destroy();
  assert.equal(ctx.root.childElementCount, 0);
  assert.equal(ctx.root.classList.contains('mlv-root'), false);
});

test('a partial setFilter leaves the other filters intact', async () => {
  // The host legitimately sends setFilter with only the field it is changing.
  // A naive spread would write `undefined` over `severities` and make every
  // later predicate throw on the next render.
  const ctx = await loadBundle();
  let listener = null;
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: () => undefined,
    onMessage: (cb) => {
      listener = cb;
      return () => undefined;
    },
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);

  listener({ v: 1, type: 'setFilter', query: 'loader' });
  let state = app.getState();
  assert.deepEqual(JSON.parse(JSON.stringify(state.filters.severities)), ['low', 'medium', 'high']);
  assert.equal(state.filters.query, 'loader');
  assert.ok(ctx.document.querySelectorAll('.mlv-badge').length > 0, 'markers survive a query-only filter');

  listener({ v: 1, type: 'setFilter', severities: ['high'] });
  state = app.getState();
  assert.deepEqual(JSON.parse(JSON.stringify(state.filters.severities)), ['high']);
  assert.equal(state.filters.query, 'loader', 'the query is not cleared by a severity-only filter');

  listener({ v: 1, type: 'setFilter', codes: ['MLV201'] });
  const rows = ctx.document.querySelectorAll('[data-issue-id]');
  assert.equal(rows.length, 1, 'the code restriction narrowed the rail to MLV201');
  app.destroy();
});
