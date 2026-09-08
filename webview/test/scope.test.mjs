/**
 * Feature 2 — the scoped view in the VIEWER (FEATURES section 3,
 * CONTRACTS 11.2 / 11.4 F3 / 11.8 / 11.9).
 *
 * The algorithm itself is gated by `scope_parity.test.mjs` against the Python
 * implementation. This suite is about what the user sees: no empty swimlane
 * bands, a breadcrumb that cannot be read as a statement about the project, a
 * rail that always says how many findings are outside the scope, the fourth
 * empty state, and a ViewState that round-trips.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

async function app(opts = {}) {
  const ctx = await loadBundle();
  const posted = [];
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: (cb) => {
      ctx.listener = cb;
      return () => undefined;
    },
    saveState(s) {
      this.saved = s;
    },
    loadState: () => opts.state || null,
  };
  const root = ctx.document.getElementById('mlview-root');
  if (opts.attrScope) root.setAttribute('data-mlview-scope', opts.attrScope);
  if (opts.attrDepth !== undefined) root.setAttribute('data-mlview-depth', String(opts.attrDepth));
  // `graph: null` is the VS Code host's real mount: the panel mounts the viewer
  // empty and posts `restoreState` and then `graph` (vscode-extension/src/panel.ts).
  const instance = ctx.MLView.mount(root, 'graph' in opts ? opts.graph : sample, bridge);
  return { ...ctx, posted, bridge, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const key = (ctx, el, k, opts = {}) =>
  el.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));
const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
const laneIds = (ctx) => Array.from(ctx.document.querySelectorAll('[data-lane-id]')).map((l) => l.getAttribute('data-lane-id'));

/* ── F2-A8: no empty bands ────────────────────────────────────────────── */

test('a scope draws no empty swimlane band (F2-A8, CONTRACTS 11.4 F3)', async () => {
  const ctx = await app();
  assert.equal(laneIds(ctx).length, 7, 'unscoped, the seven present stages are all drawn');

  ctx.app.setScope('concern:evaluation');
  const lanes = laneIds(ctx);
  assert.deepEqual(lanes, ['eval'], 'only the lane with drawn roots survives');
  for (const lane of lanes) {
    const boxes = ctx.document.querySelectorAll('[data-node-id][data-stage="' + lane + '"]');
    assert.ok(boxes.length > 0, 'lane ' + lane + ' has content');
  }

  // The information is not lost — it is correctly labelled.
  const chips = Array.from(ctx.document.querySelectorAll('[data-out-of-scope]')).map((c) => c.getAttribute('data-out-of-scope'));
  assert.ok(chips.indexOf('config') >= 0, 'config is present in the project but not in this scope');
  assert.ok(chips.indexOf('objective') >= 0);
  const label = Array.from(ctx.document.querySelectorAll('.mlv-chiprow__label')).map((e) => e.textContent);
  assert.ok(label.indexOf('not in this scope') >= 0, 'beside the existing "not detected" row: ' + label.join(' / '));

  ctx.app.setScope(null);
  assert.equal(laneIds(ctx).length, 7, 'clearing puts every lane back');
  assert.equal(ctx.document.querySelectorAll('[data-out-of-scope]').length, 0);
});

/* ── the breadcrumb ───────────────────────────────────────────────────── */

test('the breadcrumb states the scope, the depth and the PROJECT total', async () => {
  const ctx = await app();
  const crumb = ctx.document.querySelector('.mlv-breadcrumb');
  assert.ok(crumb.hidden, 'no chip while the whole workspace is shown');

  ctx.app.setScope('unit:train.train', { depth: 1 });
  assert.equal(crumb.hidden, false);
  assert.equal(text(crumb).indexOf('Scoped to train() · depth 1 · 9 of 12 nodes'), 0, text(crumb));
  assert.equal(crumb.getAttribute('role'), 'status');
  assert.equal(crumb.title, 'unit:train.train', 'the raw selector is one copy away');

  const clear = crumb.querySelector('.mlv-breadcrumb__clear');
  assert.match(clear.getAttribute('aria-label'), /Filters are separate/, 'the one sentence that keeps the two narrowings apart');
  click(ctx, clear);
  assert.ok(crumb.hidden, '[x] clears the scope');
  assert.equal(ctx.app.getScope().spec, null);
});

test('the depth steppers narrow and widen without changing the selector', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  const before = ctx.app.getScope().nodes;
  key(ctx, ctx.canvas, '[');
  assert.equal(ctx.app.getScope().depth, 0);
  assert.ok(ctx.app.getScope().nodes < before, 'narrower');
  key(ctx, ctx.canvas, ']');
  key(ctx, ctx.canvas, ']');
  assert.equal(ctx.app.getScope().depth, 2);
  assert.equal(ctx.app.getScope().spec, 'unit:train.train', 'the selector never changed');
});

/* ── the rail ─────────────────────────────────────────────────────────── */

test('the rail always says how many findings are outside the scope', async () => {
  const ctx = await app();
  assert.equal(ctx.document.querySelector('[data-scope-line]'), null, 'no scope, no line');

  ctx.app.setScope('unit:train.train', { depth: 1 });
  const line = ctx.document.querySelector('[data-scope-line]');
  assert.ok(line, 'the rail carries a scope line');
  assert.match(text(line), /^2 of 6 findings shown · 4 outside this scope/);
  assert.ok(text(line).indexOf('Show all') > 0);

  click(ctx, line.querySelector('button'));
  assert.equal(ctx.app.getScope().spec, null, 'Show all clears the scope');
  assert.equal(ctx.document.querySelector('[data-scope-line]'), null);
});

test('the FOURTH empty state: in scope, and clean HERE (FEATURES 3.7)', async () => {
  const ctx = await app();
  ctx.app.setScope('stage:preprocess');
  const box = ctx.document.querySelector('[data-scope-empty-rail]');
  assert.ok(box, 'a scope with no findings gets its own state');
  assert.match(text(box), /No findings in this scope/);
  assert.match(text(box), /6 elsewhere in this project/);
  // and it is NOT the clean bill of health, nor the filter-empty state
  assert.equal(text(box).indexOf('No issues found'), -1);
  assert.equal(text(box).indexOf('No issues match these filters'), -1);
});

test('an empty scope gets the scope-empty canvas state, not the filter one', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:NoSuchThing');
  const state = ctx.document.querySelector('[data-scope-empty]');
  assert.ok(state, 'the canvas says what happened');
  assert.equal(state.getAttribute('data-scope-empty'), 'unit:NoSuchThing');
  assert.match(text(state), /Nothing in this scope/);
  assert.match(text(state), /matched no nodes/);
  assert.equal(ctx.document.querySelectorAll('.mlv-state--empty h2')[0].textContent, 'Nothing in this scope');
  assert.equal(ctx.app.getScope().nodes, 0);
  assert.equal(ctx.app.getScope().of, 12, 'and it still knows how big the project is');
});

/* ── roles, rendered ──────────────────────────────────────────────────── */

test('boundary cards are dashed, badge-free and named as outside the scope', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 1 });
  const boundary = ctx.document.querySelectorAll('[data-view-role="boundary"]');
  assert.ok(boundary.length >= 4, boundary.length + ' boundary stubs drawn');
  // A boundary node with kept children is drawn as a FRAME, whose accessible
  // name lives on its header; a leaf is drawn as a card and carries its own.
  const named = (el) => el.getAttribute('aria-label') || el.querySelector('[aria-label]').getAttribute('aria-label');
  for (const card of boundary) {
    assert.equal(card.querySelector('.mlv-badge'), null, 'a badge you cannot open is a lie');
    assert.equal(card.querySelector('.mlv-cluster'), null, 'nor an aggregated one on a boundary frame');
    assert.equal(card.getAttribute('data-sev'), null);
    assert.match(named(card), /outside the current scope/);
  }
  const core = ctx.document.querySelectorAll('[data-view-role="core"]');
  assert.ok(core.length >= 3);
  for (const card of core) assert.equal(named(card).indexOf('outside the current scope'), -1);
});

test('a context ancestor is kept as a frame (unit:batch_loop)', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:batch_loop', { depth: 0 });
  const context = ctx.document.querySelectorAll('[data-view-role="context"]');
  assert.equal(context.length, 1, 'train() is kept so `parent` still forms a forest');
  assert.equal(context[0].getAttribute('data-node-id'), 'n:5500cc66dd77');
});

/* ── entry points ─────────────────────────────────────────────────────── */

test('the toolbar picker lists Everything, the four concerns and the units', async () => {
  const ctx = await app();
  const button = ctx.document.querySelector('.mlv-btn--scope');
  assert.ok(button, 'the toolbar carries a scope button');
  assert.equal(text(button.querySelector('.mlv-btn__label')), 'Everything');

  click(ctx, button);
  const picker = ctx.document.querySelector('.mlv-scopepicker');
  assert.equal(picker.hidden, false);
  const specs = Array.from(picker.querySelectorAll('[data-scope-spec]')).map((r) => r.getAttribute('data-scope-spec'));
  assert.ok(specs.indexOf('all') >= 0);
  for (const concern of ['config', 'data', 'evaluation', 'optimization']) {
    assert.ok(specs.indexOf('concern:' + concern) >= 0, 'concern:' + concern + ' is offered');
  }
  assert.ok(specs.some((s) => s.indexOf('unit:') === 0), 'and the scopable units');

  // One name per concern: the row, the breadcrumb and the toolbar button all
  // read CONCERN_LABELS, so a row saying 'optimization' cannot rename itself
  // 'Model & optimization' one click later (MLV-R3-005).
  const evaluation = picker.querySelector('[data-scope-spec="concern:evaluation"]');
  assert.ok(text(evaluation).indexOf('Evaluation & inference') >= 0, text(evaluation));
  for (const slug of ['config', 'data', 'evaluation', 'optimization']) {
    const row = picker.querySelector('[data-scope-spec="concern:' + slug + '"]');
    const label = ctx.MLView.__internal.scope.concerns(sample).filter((c) => c.spec === 'concern:' + slug)[0].label;
    assert.ok(text(row).indexOf(label) >= 0, slug + ' row reads "' + label + '"');
  }

  // A concern that matches nothing is a finding, rendered as one.
  const rows = Array.from(picker.querySelectorAll('[data-scope-spec="concern:config"]'));
  assert.equal(rows.length, 1);
  assert.match(text(rows[0]), /1 node/);

  const pick = picker.querySelector('[data-scope-spec="concern:optimization"]');
  click(ctx, pick);
  assert.equal(ctx.app.getScope().spec, 'concern:optimization');
  assert.ok(ctx.document.querySelector('.mlv-scopepicker').hidden, 'picking closes the picker');
  assert.equal(text(ctx.document.querySelector('.mlv-btn--scope .mlv-btn__label')), 'Model & optimization');
});

test('the inspector scopes to the selected unit or step', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="n:8d3e0f7a2b61"]'));
  const button = ctx.document.querySelector('[data-scope-node="n:8d3e0f7a2b61"]');
  assert.ok(button, 'the Inspector offers it');
  assert.equal(text(button), 'Scope to this unit', 'a definition is a unit');
  click(ctx, button);
  assert.equal(ctx.app.getScope().spec, 'unit:model.SmallNet');

  ctx.app.setScope(null);
  click(ctx, ctx.document.querySelector('[data-node-id="n:6a2f83b19c40"]'));
  assert.equal(text(ctx.document.querySelector('[data-scope-node="n:6a2f83b19c40"]')), 'Scope to this step', 'a call-site op is a step');
});

test('s scopes to the selection, Shift+S clears it', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="n:8d3e0f7a2b61"]'));
  key(ctx, ctx.canvas, 's');
  assert.equal(ctx.app.getScope().spec, 'unit:model.SmallNet');
  key(ctx, ctx.canvas, 'S', { shiftKey: true });
  assert.equal(ctx.app.getScope().spec, null);
});

/* ── the host protocol ────────────────────────────────────────────────── */

test('setScope arrives from the host and scopeChanged goes back (CONTRACTS 11.7)', async () => {
  const ctx = await app();
  ctx.listener({ v: 1, type: 'setScope', spec: 'concern:evaluation', depth: 1 });
  const changed = ctx.posted.filter((m) => m.type === 'scopeChanged');
  assert.equal(changed.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(changed[0])), {
    v: 1,
    type: 'scopeChanged',
    spec: 'concern:evaluation',
    label: 'Evaluation & inference',
    nodes: 3,
    of: 12,
  });
  assert.equal(ctx.posted.filter((m) => m.type === 'requestRefresh').length, 0, 'a scope NEVER re-analyses');

  ctx.listener({ v: 1, type: 'setScope', spec: null });
  const cleared = ctx.posted.filter((m) => m.type === 'scopeChanged').pop();
  assert.equal(cleared.spec, null);
  assert.equal(cleared.label, 'Everything');
  assert.equal(cleared.nodes, cleared.of, 'a cleared scope shows the whole project');
});

test('an unresolvable selector is a no-op plus a toast, never a throw', async () => {
  const ctx = await app();
  ctx.app.setScope('bogus:x');
  assert.equal(ctx.app.getScope().spec, null, 'the previous view still stands');
  const toast = ctx.document.querySelector('.mlv-toast');
  assert.ok(toast && toast.textContent.indexOf('bad_selector') >= 0, text(toast));

  ctx.app.setScope('stage:train');
  ctx.app.setScope('stage:nope');
  assert.equal(ctx.app.getScope().spec, 'stage:train', 'a bad selector does not drop a good scope');
  ctx.listener({ v: 1, type: 'setScope', spec: 'node:n:deadbeefdead' });
  assert.equal(ctx.app.getScope().spec, 'stage:train');
});

/* ── ViewState ────────────────────────────────────────────────────────── */

test('ViewState.scope round-trips through the bridge (CONTRACTS 11.9)', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train', { depth: 2 });
  await new Promise((r) => setTimeout(r, 320));
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.bridge.saved.scope)), { spec: 'unit:train.train', depth: 2 });

  const back = await app({ state: JSON.parse(JSON.stringify(ctx.bridge.saved)) });
  assert.equal(back.app.getScope().spec, 'unit:train.train');
  assert.equal(back.app.getScope().depth, 2);

  // An older saved state restores to the defaults: no scope, flow on.
  const older = await app({ state: { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['low', 'medium', 'high'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues' } });
  assert.equal(older.app.getScope().spec, null);
  assert.equal(older.canvas.getAttribute('data-flow'), 'motion');
});

test('a mangled saved scope is dropped rather than crashing the mount', async () => {
  for (const scope of [{ spec: 42 }, { depth: 9 }, 'unit:x', null, { spec: '' }]) {
    const ctx = await app({ state: { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['high'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', scope } });
    assert.equal(ctx.app.getScope().spec, null, JSON.stringify(scope) + ' is not a scope');
    assert.ok(ctx.document.querySelectorAll('[data-node-id]').length > 5, 'and the diagram still mounted');
  }
});

test('a saved scope that no longer matches a NEW graph is dropped with a toast', async () => {
  const ctx = await app();
  ctx.app.setScope('unit:train.train');
  const smaller = JSON.parse(JSON.stringify(sample));
  smaller.nodes = smaller.nodes.filter((n) => n.stage === 'data');
  smaller.edges = [];
  smaller.issues = [];
  for (const node of smaller.nodes) node.issueIds = [];
  smaller.stats = { ...smaller.stats, nodes: smaller.nodes.length, edges: 0, issues: { low: 0, medium: 0, high: 0 } };
  ctx.listener({ v: 1, type: 'graph', requestId: 'r1', graph: smaller });
  assert.equal(ctx.app.getScope().spec, null, 'the scope was dropped');
  const toasts = Array.from(ctx.document.querySelectorAll('.mlv-toast')).map((t) => t.textContent);
  assert.ok(toasts.some((t) => /Scope no longer matches/.test(t)), toasts.join(' | '));
});

/* ── the report's bootstrap ───────────────────────────────────────────── */

test('mount() reads the initial scope off the root element (CONTRACTS 11.8)', async () => {
  const ctx = await app({ attrScope: 'concern:evaluation', attrDepth: 1 });
  assert.equal(ctx.app.getScope().spec, 'concern:evaluation');
  assert.equal(ctx.app.getScope().depth, 1);
  assert.equal(ctx.app.getScope().of, 12, 'the report embeds the FULL graph and the viewer projects it');
  assert.ok(ctx.document.querySelector('.mlv-breadcrumb').hidden === false);
});

/* ── a scope is not a filter ──────────────────────────────────────────── */

test('a scope and the stage filters never clear each other (FEATURES 3.8)', async () => {
  const ctx = await app();
  ctx.app.setFilters({ severities: ['high'] });
  ctx.app.setScope('concern:optimization');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().filters.severities)), ['high'], 'the scope left the filters alone');
  ctx.app.setScope(null);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().filters.severities)), ['high'], 'and so did clearing it');
});

test('search still runs over the FULL graph while scoped (FEATURES 3.5)', async () => {
  const ctx = await app();
  ctx.app.setScope('concern:evaluation');
  const { GraphIndex, searchGraph } = ctx.MLView.__internal;
  const hits = searchGraph(new GraphIndex(sample), 'SmallNet');
  assert.ok(hits.length > 0, 'a node outside the scope is still findable');
  // revealing it clears the scope rather than claiming the node does not exist
  ctx.app.focusNode('n:8d3e0f7a2b61');
  assert.equal(ctx.app.getScope().spec, null, 'an explicit navigation beats a scope set two minutes ago');
  const toasts = Array.from(ctx.document.querySelectorAll('.mlv-toast')).map((t) => t.textContent);
  assert.ok(toasts.some((t) => /Scope cleared/.test(t)), toasts.join(' | '));
});

test('the collapse set survives a scope round trip (FEATURES 3.5)', async () => {
  const ctx = await app();
  ctx.app.focusNode('n:5500cc66dd77');
  key(ctx, ctx.canvas, ' ');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), ['n:5500cc66dd77'], 'collapsed');
  ctx.app.setScope('concern:evaluation');
  assert.deepEqual(
    JSON.parse(JSON.stringify(ctx.app.getState().collapsed)),
    ['n:5500cc66dd77'],
    'the collapse is held against the FULL id space, not the projection',
  );
  ctx.app.setScope(null);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), ['n:5500cc66dd77'], 'and it is still there afterwards');
});

test('scope and flow round-trip through BOTH real bridges', async () => {
  // The vscode bridge is exercised by the `app()` helper above (setState/getState
  // through the recording bridge). This is the standalone one, which persists to
  // localStorage — the report has no host to keep the state for it.
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const first = ctx.MLView.mount(root, sample, ctx.MLView.bridges.standalone({ theme: 'light' }));
  first.setScope('stage:train', { depth: 1 });
  ctx.document.querySelector('.mlv-btn--flow').dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true }));
  await new Promise((r) => setTimeout(r, 320));
  first.destroy();

  const saved = JSON.parse(ctx.window.localStorage.getItem('mlview.viewState.v1'));
  assert.deepEqual(saved.scope, { spec: 'stage:train', depth: 1 });
  assert.equal(saved.flow, false);

  const again = ctx.MLView.mount(root, sample, ctx.MLView.bridges.standalone({ theme: 'light' }));
  assert.equal(again.getScope().spec, 'stage:train');
  assert.equal(again.getScope().depth, 1);
  assert.equal(ctx.document.querySelector('.mlv-canvas').getAttribute('data-flow'), 'off');
  again.destroy();
  ctx.window.localStorage.clear();
});

test('a host predating the feature round-trips both fields untouched', async () => {
  // `applyState` tolerates missing keys, and `getState` omits `flow` while it is
  // on, so an older saved state restores to the defaults (CONTRACTS 11.9).
  const ctx = await app();
  const state = ctx.app.getState();
  assert.equal(state.scope, undefined, 'no scope, no key');
  assert.equal(state.flow, undefined, 'flow on, no key');
  assert.deepEqual(Object.keys(JSON.parse(JSON.stringify(state))).sort(), [
    'collapsed',
    'filters',
    'minimapCollapsed',
    'railTab',
    'selection',
    'viewport',
  ]);
});


/* ── a scope opens showing its subject (MLV-R3-001) ───────────────────── */

test('a scoped report fits whole; the whole workspace still fits its width', async () => {
  const ctx = await app();
  const world = ctx.document.querySelector('.mlv-world');
  const read = () => {
    const m = /translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/.exec(world.style.transform);
    assert.ok(m, world.style.transform);
    return { x: Number(m[1]), y: Number(m[2]), zoom: Number(m[3]) };
  };
  // jsdom reports a zero-sized canvas, so ViewportController falls back to its
  // documented 1200x800 — the same arithmetic the browser runs.
  const CANVAS = { w: 1200, h: 800 };
  const PAD = 24;

  const full = ctx.MLView.__internal.layout(sample);
  const unscoped = read();
  assert.ok(
    Math.abs(unscoped.zoom - Math.min((CANVAS.w - PAD * 2) / full.width, 1)) < 0.001,
    'a whole workspace is taller than it is wide: it fits the WIDTH and is read by panning down',
  );

  ctx.app.setScope('concern:evaluation', { depth: 1 });
  const scoped = read();
  const scopeApi = ctx.MLView.__internal.scope;
  const projected = ctx.MLView.__internal.layout(scopeApi.project(sample, scopeApi.parseScope('concern:evaluation', 1)));
  assert.ok(
    scoped.zoom * projected.height <= CANVAS.h - PAD,
    'the whole projection is on screen: ' + (scoped.zoom * projected.height).toFixed(0) + 'px of ' + CANVAS.h,
  );
  assert.ok(scoped.zoom * projected.width <= CANVAS.w - PAD, 'and it fits horizontally too');
  assert.ok(scoped.y >= 0, 'anchored inside the canvas, not above it');

  ctx.app.setScope(null);
  assert.ok(Math.abs(read().zoom - unscoped.zoom) < 0.001, 'clearing the scope restores the whole-workspace fit');
});

/* ── review round 2: what the HOST is told, and when ──────────────────── */

test('a graph that invalidates the scope posts scopeChanged {spec:null} (11.7, R2H-01/R2-REG-02)', async () => {
  // The viewer drops a scope nobody can see any more; `scopeChanged` is the
  // host's ONLY writer of the panel title and description (CONTRACTS 11.11), so
  // a silent drop left the VS Code tab reading `MLView — train()` over a
  // whole-workspace diagram until the user happened to take another scope.
  const ctx = await app();
  ctx.app.setScope('unit:train.train');
  const scoped = ctx.posted.filter((m) => m.type === 'scopeChanged');
  assert.equal(scoped.length, 1, 'the deliberate scope posts exactly one');

  const smaller = JSON.parse(JSON.stringify(sample));
  smaller.nodes = smaller.nodes.filter((n) => n.stage === 'data');
  const kept = new Set(smaller.nodes.map((n) => n.id));
  smaller.edges = smaller.edges.filter((e) => kept.has(e.source) && kept.has(e.target));
  smaller.issues = [];
  for (const node of smaller.nodes) node.issueIds = [];
  ctx.listener({ v: 1, type: 'graph', requestId: 'r1', graph: smaller });

  const after = ctx.posted.filter((m) => m.type === 'scopeChanged').slice(scoped.length);
  assert.equal(after.length, 1, 'exactly one post for the drop: ' + JSON.stringify(after));
  assert.equal(after[0].spec, null);
  assert.equal(after[0].label, 'Everything');
  assert.equal(after[0].nodes, after[0].of, 'and it reports the whole document');
  assert.equal(ctx.app.getScope().spec, null, 'the viewer really did drop it');
});

test('a graph that only changes the COUNTS still refreshes the host (R2-REG-02)', async () => {
  // `4 of 45` beside a diagram drawing `6 of 61` is as stale a panel description
  // as a title naming a unit that no longer exists.
  const ctx = await app();
  ctx.app.setScope('stage:train');
  const posts = () => ctx.posted.filter((m) => m.type === 'scopeChanged');
  const beforeCount = posts().length;
  const of = posts()[beforeCount - 1].of;

  const grown = JSON.parse(JSON.stringify(sample));
  const gone = 'n:4e8b21c05a97'; // a preprocess op, outside stage:train
  grown.nodes = grown.nodes.filter((n) => n.id !== gone);
  grown.edges = grown.edges.filter((e) => e.source !== gone && e.target !== gone);
  grown.issues = grown.issues.filter((i) => (i.nodeIds || []).indexOf(gone) < 0);
  const live = new Set(grown.issues.map((i) => i.id));
  for (const node of grown.nodes) node.issueIds = (node.issueIds || []).filter((id) => live.has(id));
  ctx.listener({ v: 1, type: 'graph', requestId: 'r2', graph: grown });

  const after = posts().slice(beforeCount);
  assert.equal(after.length, 1, 'the changed project total is posted once: ' + JSON.stringify(after));
  assert.equal(after[0].spec, 'stage:train', 'the scope itself still resolves');
  assert.equal(after[0].of, of - 1, 'and the host learns the new project total');
  assert.equal(ctx.app.getScope().spec, 'stage:train');
});

test('an unchanged scope survives a re-analysis WITHOUT a redundant post', async () => {
  const ctx = await app();
  ctx.app.setScope('stage:train');
  const before = ctx.posted.filter((m) => m.type === 'scopeChanged').length;
  ctx.listener({ v: 1, type: 'graph', requestId: 'r3', graph: JSON.parse(JSON.stringify(sample)) });
  assert.equal(ctx.posted.filter((m) => m.type === 'scopeChanged').length, before, 'nothing moved, nothing said');
  assert.equal(ctx.app.getScope().spec, 'stage:train');
});

test('ViewState.scope restores on a host that mounts with NO graph (11.9, R2H-03)', async () => {
  // The VS Code panel mounts the viewer empty and posts init -> restoreState ->
  // graph, so both restore routes ran before any graph existed and `scope` — the
  // single field of the state that is written on save — was dropped on the floor.
  const ctx = await app({ graph: null });
  ctx.listener({
    v: 1,
    type: 'restoreState',
    state: { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['low', 'medium', 'high'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', scope: { spec: 'unit:train.train', depth: 2 } },
  });
  assert.equal(ctx.app.getScope().spec, null, 'there is nothing to scope yet');
  ctx.listener({ v: 1, type: 'graph', requestId: 'r4', graph: sample });

  assert.equal(ctx.app.getScope().spec, 'unit:train.train', 'the stashed scope lands with the document');
  assert.equal(ctx.app.getScope().depth, 2, 'depth and all');
  assert.equal(ctx.app.getScope().of, 12, 'against project-level truth');
  const posted = ctx.posted.filter((m) => m.type === 'scopeChanged');
  assert.equal(posted.length, 1, 'and the host is told exactly once: ' + JSON.stringify(posted));
  assert.equal(posted[0].spec, 'unit:train.train');
  assert.equal(ctx.document.querySelector('.mlv-breadcrumb').hidden, false, 'the breadcrumb is up');
});

test('a saved scope restored BEFORE the graph is re-resolved against it', async () => {
  // 11.9's re-resolve applies to the stashed scope too: a spec that matches
  // nothing in the document that finally arrives is dropped, not applied blind.
  const ctx = await app({ graph: null });
  ctx.listener({ v: 1, type: 'restoreState', state: { scope: { spec: 'unit:gone.away', depth: 1 } } });
  ctx.listener({ v: 1, type: 'graph', requestId: 'r5', graph: sample });
  assert.equal(ctx.app.getScope().spec, null, 'an empty scope is not applied');
  assert.ok(ctx.document.querySelectorAll('[data-node-id]').length > 5, 'and the whole diagram is drawn');
});

test('the mount-time state route stashes a scope too (report and panel agree)', async () => {
  // `loadState()` runs before the graph in the constructor as well, so the
  // stash — not the old `scopes.full` guard — is what makes the two hosts agree.
  const state = { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['low', 'medium', 'high'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', scope: { spec: 'stage:train', depth: 0 } };
  const ctx = await app({ state });
  assert.equal(ctx.app.getScope().spec, 'stage:train');

  // The root attribute still outranks it (CONTRACTS 11.8).
  const attr = await app({ state, attrScope: 'concern:evaluation', attrDepth: 0 });
  assert.equal(attr.app.getScope().spec, 'concern:evaluation');
});
