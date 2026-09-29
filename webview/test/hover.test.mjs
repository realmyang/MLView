// Hover trace lifecycle with the real 400 ms / 120 ms intent timers
// (RENDER-1, RENDER-19).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

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

/* ── Stage 1 review: a connection's card lists its findings ─────────────── */

/** `workflow()` plus a merged pair (m1, m2: same ends and kind) and three edge findings. */
function edgeFindingWorkflow() {
  const doc = workflow();
  doc.edges.push(
    { id: 'm1', source: 'read', target: 'other', label: 'rows', kind: 'data', basis: 'observed', evidence: ['e'] },
    { id: 'm2', source: 'read', target: 'other', label: 'labels', kind: 'data', basis: 'observed', evidence: ['e'] },
  );
  doc.findings = [
    { id: 'f-edge', title: 'Weights leak into eval', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['b'], basis: 'inferred', evidence: ['e'] },
    { id: 'f-shared', title: 'Rows and labels drift', message: 'm', severity: 'high', nodeIds: [], edgeIds: ['m1', 'm2'], basis: 'inferred', evidence: ['e'] },
    { id: 'f-one', title: 'Labels unchecked', message: 'm', severity: 'low', nodeIds: [], edgeIds: ['m2'], basis: 'inferred', evidence: ['e'] },
  ];
  return doc;
}

async function mountEdges(doc = edgeFindingWorkflow()) {
  const ctx = await loadBundle();
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, recordingBridge(ctx.window, 'vscode'));
  const tooltip = ctx.document.querySelector('.mlv-tooltip');
  const hit = (id) => ctx.document.querySelector(`.mlv-edge[data-edge-id="${id}"] .mlv-edge__hit`);
  const pointer = (type, element) => element.dispatchEvent(new ctx.window.Event(type, { bubbles: false }));
  /** The hover card's finding rows, as "<glyph severity> <code> <title>". */
  const rows = () => Array.from(tooltip.querySelectorAll('.mlv-tooltip__row'))
    .filter((row) => row.querySelector('.mlv-glyph'))
    .map((row) => row.querySelector('.mlv-glyph').getAttribute('class').replace(/.*mlv-glyph--/, '') + row.textContent);
  return { ...ctx, app, canvas: ctx.document.querySelector('.mlv-canvas'), tooltip, hit, pointer, rows };
}

test('hovering a connection shows its finding on the card, as hovering a card does', async () => {
  const ctx = await mountEdges();
  ctx.pointer('pointerenter', ctx.hit('b'));
  await wait(450);
  assert.equal(ctx.tooltip.hidden, false);
  assert.deepEqual(ctx.rows(), ['medium f-edge Weights leak into eval']);
  ctx.app.destroy();
});

test('a merged route lists a finding its members share once, in document order', async () => {
  const ctx = await mountEdges();
  const merged = ctx.document.querySelector('.mlv-edge[data-edge-id="m1"]');
  assert.equal(merged.getAttribute('data-edge-ids'), 'm1 m2', 'precondition: m1 and m2 are one route');
  ctx.pointer('pointerenter', ctx.hit('m1'));
  await wait(450);
  assert.match(ctx.tooltip.textContent, /2 merged connections/);
  assert.deepEqual(ctx.rows(), ['high f-shared Rows and labels drift', 'low f-one Labels unchecked']);
  ctx.app.destroy();
});

test('a merged route lists its findings in document order, not in member order', async () => {
  // m1 carries only the later-declared finding and m2 only the earlier one, so walking the
  // members in route order meets them the wrong way round.
  const doc = edgeFindingWorkflow();
  doc.findings.find((f) => f.id === 'f-shared').edgeIds = ['m2'];
  doc.findings.find((f) => f.id === 'f-one').edgeIds = ['m1'];
  const ctx = await mountEdges(doc);
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="m1"]').getAttribute('data-edge-ids'), 'm1 m2');
  ctx.pointer('pointerenter', ctx.hit('m1'));
  await wait(450);
  assert.deepEqual(ctx.rows(), ['high f-shared Rows and labels drift', 'low f-one Labels unchecked']);
  ctx.app.destroy();
});

test('a collapsed group card lists the findings its badge counts, including a hidden connection', async () => {
  // `b` joins two steps inside `loop`; collapsing the group hides the cable and its marker.
  const doc = edgeFindingWorkflow();
  doc.findings.push({ id: 'f-child', title: 'Step reuses a stale batch', message: 'm', severity: 'low', nodeIds: ['step'], edgeIds: [], basis: 'inferred', evidence: ['e'] });
  const ctx = await mountEdges(doc);
  ctx.app.view.toggleCollapse('loop');
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="b"]'), null, 'precondition: the cable is hidden');
  const card = ctx.document.querySelector('.mlv-node[data-node-id="loop"]');
  assert.match(card.getAttribute('aria-label'), /2 findings, highest severity medium/);
  ctx.pointer('pointerenter', card);
  await wait(450);
  assert.deepEqual(ctx.rows(), ['medium f-edge Weights leak into eval', 'low f-child Step reuses a stale batch']);
  ctx.app.destroy();
});

test('the edge Inspector lists the findings the connection card shows', async () => {
  const ctx = await mountEdges();
  ctx.app.select({ kind: 'edge', id: 'b' }, { tab: 'inspector' });
  const issue = ctx.document.querySelector('.mlv-insp__issue[data-issue-id="f-edge"]');
  assert.ok(issue, 'the Inspector names the finding');
  assert.match(issue.textContent, /Weights leak into eval/);
  ctx.app.setFilters({ severities: ['high'] });
  ctx.app.select({ kind: 'edge', id: 'b' }, { tab: 'inspector' });
  assert.equal(ctx.document.querySelector('.mlv-insp__issue[data-issue-id="f-edge"]'), null, 'the filter applies there too');
  ctx.app.destroy();
});

test('the severity filter hides a filtered finding from the connection card', async () => {
  const ctx = await mountEdges();
  ctx.app.setFilters({ severities: ['medium', 'low'] });
  ctx.pointer('pointerenter', ctx.hit('m1'));
  await wait(450);
  assert.deepEqual(ctx.rows(), ['low f-one Labels unchecked']);
  ctx.app.setFilters({ severities: ['high'] });
  ctx.pointer('pointerenter', ctx.hit('b'));
  await wait(450);
  assert.equal(ctx.tooltip.hidden, false);
  assert.deepEqual(ctx.rows(), [], 'the card still opens, without the filtered finding');
  ctx.app.destroy();
});

test('the rim of a severity marker opens its connection card at high zoom', async () => {
  // The disc (8.5 world px) is centred on the cable, but EDGE_PICK_PX (10 screen px) shrinks in
  // world units as the zoom grows: at 2.5x the pick reached 4 px, and the outer ring of the
  // marker belonged to no cable.
  const ctx = await mountEdges();
  const zoom = 2.5;
  ctx.app.view.viewport.set({ zoom });
  const marker = ctx.document.querySelector('.mlv-edge[data-edge-id="b"] .mlv-edge-marker');
  const [mx, my] = marker.getAttribute('transform').match(/-?\d+(?:\.\d+)?/g).map(Number);
  const route = ctx.app.view.routes.find((r) => r.id === 'b');
  const horizontal = route.points.some((p, i) => i > 0 && p.y === my && route.points[i - 1].y === my);
  const point = horizontal ? { x: mx, y: my + 7 } : { x: mx + 7, y: my };
  const distance = (r) => {
    let best = Infinity;
    for (let i = 1; i < r.points.length; i++) {
      const a = r.points[i - 1];
      const b = r.points[i];
      const len2 = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
      const t = len2 ? Math.max(0, Math.min(1, ((point.x - a.x) * (b.x - a.x) + (point.y - a.y) * (b.y - a.y)) / len2)) : 0;
      best = Math.min(best, Math.hypot(point.x - (a.x + t * (b.x - a.x)), point.y - (a.y + t * (b.y - a.y))));
    }
    return best;
  };
  assert.ok(ctx.app.view.routes.every((r) => distance(r) > 10 / zoom), 'precondition: no cable is within the pick distance');
  const vp = ctx.app.getState().viewport;
  ctx.canvas.dispatchEvent(new ctx.window.MouseEvent('pointermove', { bubbles: true, clientX: point.x * vp.zoom + vp.x, clientY: point.y * vp.zoom + vp.y }));
  assert.ok(ctx.document.querySelector('.mlv-edge[data-edge-id="b"]').classList.contains('is-hover'));
  await wait(450);
  assert.equal(ctx.tooltip.hidden, false);
  assert.deepEqual(ctx.rows(), ['medium f-edge Weights leak into eval']);
  // The card sits above the whole disc (8.5 world px), not over its top half: jsdom cannot
  // measure the card, so its anchor is the disc's top minus the 12 px gap.
  assert.equal(ctx.tooltip.style.left, Math.round(mx * vp.zoom + vp.x) + 'px');
  assert.equal(ctx.tooltip.style.top, Math.round((my - 8.5) * vp.zoom + vp.y - 12) + 'px');
  ctx.app.destroy();
});

/* ── Hover lights a card's direct connections; focus mode keeps the lineage ── */

/**
 * root -> src -> mid -> next -> far is a chain across two phases; `loop` groups the
 * four-step cycle l1 -> l2 -> l3 -> l4 -> l1, fed from root and src and feeding
 * summary -> sink in a third phase.
 */
function reachWorkflow() {
  const n = (id, phase, extra = {}) => ({ id, label: id, phase, basis: 'observed', evidence: ['e'], ...extra });
  const e = (id, source, target) => ({ id, source, target, label: id, basis: 'observed', evidence: ['e'] });
  return {
    workflowVersion: '1.0', title: 'Reach fixture',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'prep', label: 'Prep' }, { id: 'train', label: 'Train' }, { id: 'report', label: 'Report' }],
    nodes: [
      n('root', 'prep'), n('src', 'prep'), n('mid', 'train'), n('next', 'train'), n('far', 'train'),
      n('loop', 'train', { kind: 'group', basis: 'inferred', evidence: [] }),
      n('l1', 'train', { parent: 'loop' }), n('l2', 'train', { parent: 'loop' }),
      n('l3', 'train', { parent: 'loop' }), n('l4', 'train', { parent: 'loop' }),
      n('summary', 'report'), n('sink', 'report'),
    ],
    edges: [
      e('e-root', 'root', 'src'), e('e-in', 'src', 'mid'), e('e-out', 'mid', 'next'), e('e-far', 'next', 'far'),
      e('x1', 'root', 'l1'), e('x2', 'src', 'l2'),
      e('c12', 'l1', 'l2'), e('c23', 'l2', 'l3'), e('c34', 'l3', 'l4'), e('c41', 'l4', 'l1'),
      e('y', 'l4', 'summary'), e('z', 'summary', 'sink'),
    ],
    findings: [],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
}

async function mountReach(doc = reachWorkflow()) {
  const ctx = await loadBundle();
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, recordingBridge(ctx.window, 'vscode'));
  const ids = (selector, attr) => Array.from(ctx.document.querySelectorAll(selector), (el) => el.getAttribute(attr)).sort();
  return {
    ...ctx, app,
    canvas: ctx.document.querySelector('.mlv-canvas'),
    card: (id) => ctx.document.querySelector(`.mlv-node[data-node-id="${id}"]`),
    pointer: (type, element) => element.dispatchEvent(new ctx.window.Event(type, { bubbles: false })),
    litNodes: () => ids('.mlv-node.is-lit', 'data-node-id'),
    litEdges: () => ids('.mlv-edge.is-lit', 'data-edge-id'),
    flowing: () => ids('.mlv-edge.is-flowing', 'data-edge-id'),
    toasts: () => Array.from(ctx.document.querySelectorAll('.mlv-toast'), (t) => t.textContent),
  };
}

test('hovering a mid-chain card lights only its neighbours, not a card two hops away', async () => {
  const ctx = await mountReach();
  const card = ctx.card('mid');
  ctx.pointer('pointerenter', card);
  await wait(450);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true, 'a settled hover traces');
  assert.deepEqual(ctx.litNodes(), ['mid', 'next', 'src']);
  assert.deepEqual(ctx.litEdges(), ['e-in', 'e-out']);
  assert.equal(ctx.card('root').classList.contains('is-lit'), false, 'two hops upstream stays dim');
  assert.equal(ctx.card('far').classList.contains('is-lit'), false, 'two hops downstream stays dim');
  ctx.pointer('pointerleave', card);
  await wait(200);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
  assert.deepEqual(ctx.litNodes(), []);
  ctx.app.destroy();
});

test('focus mode on the same card still lights and streams the whole chain', async () => {
  const ctx = await mountReach();
  ctx.app.select({ kind: 'node', id: 'mid' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(ctx.canvas.classList.contains('is-focusing'), true);
  const chain = ['e-far', 'e-in', 'e-out', 'e-root'];
  assert.deepEqual(ctx.litNodes(), ['far', 'mid', 'next', 'root', 'src']);
  assert.deepEqual(ctx.litEdges(), chain);
  assert.deepEqual(ctx.flowing(), chain, 'focus mode streams the full lineage');
  // A hover while focus mode is latched changes nothing.
  ctx.app.view.setHover('l2');
  assert.deepEqual(ctx.litNodes(), ['far', 'mid', 'next', 'root', 'src']);
  assert.deepEqual(ctx.flowing(), chain);
  ctx.app.view.setHover(null);
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(ctx.canvas.classList.contains('is-focusing'), false);
  assert.deepEqual(ctx.litNodes(), []);
  // The shortcut sheet says where the lineage went.
  ctx.app.toggleShortcuts(true);
  assert.match(ctx.document.querySelector('.mlv-sheet').textContent, /Focus mode: light the full lineage of the selection/);
  ctx.app.destroy();
});

test('hovering a card inside a loop does not light the whole loop', async () => {
  const ctx = await mountReach();
  ctx.app.view.setHover('l2');
  assert.deepEqual(ctx.litNodes(), ['l1', 'l2', 'l3', 'src']);
  assert.deepEqual(ctx.litEdges(), ['c12', 'c23', 'x2']);
  assert.equal(ctx.card('l4').classList.contains('is-lit'), false, 'the far side of the loop stays dim');
  ctx.app.view.setHover(null);
  // Focus mode on the same card does light the whole loop and what it reaches.
  ctx.app.select({ kind: 'node', id: 'l2' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  for (const id of ['l1', 'l3', 'l4', 'root', 'src', 'summary', 'sink']) {
    assert.ok(ctx.card(id).classList.contains('is-lit'), id + ' is in the focused lineage');
  }
  ctx.app.destroy();
});

test('the hover stream runs only along the direct connections it lit', async () => {
  const ctx = await mountReach();
  ctx.app.view.setHover('mid');
  assert.deepEqual(ctx.flowing(), ['e-in', 'e-out']);
  // Clicking the hovered card re-runs the hover rung of the stop cascade; it
  // must stay the direct stream, not grow into the lineage.
  ctx.app.select({ kind: 'node', id: 'mid' });
  assert.deepEqual(ctx.flowing(), ['e-in', 'e-out']);
  assert.deepEqual(ctx.litEdges(), ['e-in', 'e-out']);
  ctx.app.view.setHover(null);
  ctx.app.clearSelection();
  ctx.app.view.setHover('l2');
  assert.deepEqual(ctx.flowing(), ['c12', 'c23', 'x2']);
  ctx.app.view.setHover(null);
  assert.deepEqual(ctx.flowing(), []);
  ctx.app.destroy();
});

test('a collapsed group lights like the steps it hides, one hop only', async () => {
  const ctx = await mountReach();
  ctx.app.view.toggleCollapse('loop');
  ctx.app.view.setHover('loop');
  assert.deepEqual(ctx.litNodes(), ['loop', 'root', 'src', 'summary']);
  assert.deepEqual(ctx.litEdges(), ['x1', 'x2', 'y']);
  assert.deepEqual(ctx.flowing(), ['x1', 'x2', 'y']);
  assert.equal(ctx.card('sink').classList.contains('is-lit'), false, 'two hops past the group stays dim');
  ctx.app.view.setHover('summary');
  assert.deepEqual(ctx.litNodes(), ['loop', 'sink', 'summary'], 'a neighbour lights the group card');
  ctx.app.destroy();
});

test('a trunk opens for a lit direct connection, stays folded for one two hops away, and folds when the hover ends', async () => {
  const ctx = await mountReach();
  const bundle = ctx.document.querySelector('.mlv-bundle[data-bundle-id="bundle:prep>train"]');
  assert.ok(bundle, 'precondition: the prep -> train connections are bundled');
  const bundled = () => ctx.document.querySelector('.mlv-edge[data-edge-id="e-in"]').classList.contains('is-bundled');
  assert.equal(bundled(), true, 'precondition: e-in is folded into the trunk');
  ctx.app.view.setHover('next');
  assert.equal(bundle.classList.contains('is-expanded'), false, 'e-in is two hops from next');
  assert.equal(bundled(), true);
  ctx.app.view.setHover('mid');
  assert.equal(bundle.classList.contains('is-expanded'), true, 'e-in is wired to mid');
  assert.equal(bundled(), false);
  ctx.app.view.setHover(null);
  assert.equal(bundle.classList.contains('is-expanded'), false, 'the trunk folds again when the hover ends');
  assert.equal(bundled(), true);
  // Focus mode on `next` reaches e-in through its lineage, so the trunk opens,
  // and folds again when focus mode is turned off.
  ctx.app.select({ kind: 'node', id: 'next' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(bundle.classList.contains('is-expanded'), true, 'focus mode reaches e-in through the lineage');
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(bundle.classList.contains('is-expanded'), false, 'the trunk folds again when focus mode ends');
  ctx.app.destroy();
});

test('a hover denser than the flow cap names the card, and focus mode names the lineage', async () => {
  const leaves = Array.from({ length: 121 }, (_, i) => 'leaf-' + i);
  const doc = reachWorkflow();
  doc.phases = [{ id: 'p', label: 'P' }];
  doc.nodes = ['hub', ...leaves].map((id) => ({ id, label: id, phase: 'p', basis: 'observed', evidence: ['e'] }));
  doc.edges = leaves.map((id) => ({ id: 'to-' + id, source: 'hub', target: id, label: id, basis: 'observed', evidence: ['e'] }));
  const ctx = await mountReach(doc);
  ctx.app.view.setHover('hub');
  assert.equal(ctx.litEdges().length, 121);
  assert.deepEqual(ctx.flowing(), [], 'over the cap nothing animates');
  // Scoping to the card keeps every one of its connections, so the hover copy
  // names the single-connection hover instead of scoping.
  assert.deepEqual(ctx.toasts(), ['This card has 121 connections, past the 120 the animation can carry. Hover a single connection to see its flow.']);
  ctx.app.view.setHover(null);
  ctx.app.select({ kind: 'node', id: 'hub' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(ctx.toasts().at(-1), 'This lineage has 121 connections, past the 120 the animation can carry. Press s to scope the diagram and the flow returns.');
  ctx.app.destroy();
});

test('focus mode re-streams the full lineage when the stop cascade runs again', async () => {
  const ctx = await mountReach();
  const chain = ['e-far', 'e-in', 'e-out', 'e-root'];
  ctx.app.select({ kind: 'node', id: 'mid' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.deepEqual(ctx.flowing(), chain);
  // Turning the flow layer off and on re-runs the cascade's focus-mode rung.
  ctx.app.setFlow(false);
  assert.deepEqual(ctx.flowing(), []);
  ctx.app.setFlow(true);
  assert.deepEqual(ctx.flowing(), chain, 'the latched stream is still the whole chain');
  // Selecting the chain's end moves focus there; its direct reach would be e-far alone.
  ctx.app.select({ kind: 'node', id: 'far' });
  assert.deepEqual(ctx.litEdges(), chain);
  assert.deepEqual(ctx.flowing(), chain);
  ctx.app.destroy();
});

test('selecting a connection while focus mode is latched folds the trunk its stream opened', async () => {
  const ctx = await mountReach();
  const bundle = ctx.document.querySelector('.mlv-bundle[data-bundle-id="bundle:prep>train"]');
  const bundled = () => ctx.document.querySelector('.mlv-edge[data-edge-id="e-in"]').classList.contains('is-bundled');
  ctx.app.select({ kind: 'node', id: 'next' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(bundle.classList.contains('is-expanded'), true, 'precondition: the lineage stream opened the trunk');
  ctx.app.select({ kind: 'edge', id: 'z' });
  assert.deepEqual(ctx.litEdges(), []);
  assert.deepEqual(ctx.flowing(), []);
  assert.equal(bundle.classList.contains('is-expanded'), false, 'nothing on the trunk is lit or flowing');
  assert.equal(bundled(), true);
  ctx.app.destroy();
});

test('turning focus mode off with the pointer on a card brings back its hover', async () => {
  const ctx = await mountReach();
  const bundle = ctx.document.querySelector('.mlv-bundle[data-bundle-id="bundle:prep>train"]');
  ctx.app.view.setHover('mid');
  ctx.app.select({ kind: 'node', id: 'mid' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(ctx.canvas.classList.contains('is-focusing'), false);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), true, 'the hovered card is traced again');
  assert.deepEqual(ctx.litEdges(), ['e-in', 'e-out']);
  assert.deepEqual(ctx.flowing(), ['e-in', 'e-out']);
  // A later stop cascade streams only what is lit, and opens the trunk its cable is in.
  ctx.app.clearSelection();
  assert.deepEqual(ctx.flowing(), ['e-in', 'e-out']);
  assert.deepEqual(ctx.litEdges(), ['e-in', 'e-out']);
  assert.equal(bundle.classList.contains('is-expanded'), true);
  ctx.app.view.setHover(null);
  assert.deepEqual(ctx.flowing(), []);
  assert.equal(bundle.classList.contains('is-expanded'), false);
  ctx.app.destroy();
});

test('a card the hover dims still takes the pointer; only focus mode makes dimmed cards inert', async () => {
  // jsdom applies no CSS, so the rule is read from the shipped stylesheet.
  const css = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
  const declarations = (selector) => {
    const out = {};
    for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!m[1].split(',').map((s) => s.trim()).includes(selector)) continue;
      for (const decl of m[2].split(';')) {
        const i = decl.indexOf(':');
        if (i > 0) out[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
      }
    }
    return out;
  };
  const tracing = declarations('.mlv-canvas.is-tracing .mlv-node:not(.is-lit)');
  const focusing = declarations('.mlv-canvas.is-focusing .mlv-node:not(.is-lit)');
  assert.equal(tracing.opacity, '.22', 'a hover still dims');
  assert.equal(tracing['pointer-events'], undefined, 'a dimmed card can still be hovered and clicked');
  assert.equal(focusing.opacity, '.22');
  assert.equal(focusing['pointer-events'], 'none');
});
