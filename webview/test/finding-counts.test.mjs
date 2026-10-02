// Stage 1 review: every aggregate badge counts DISTINCT findings.
//
// One finding that names three steps and two connections of one phase drew 5 on the lane header
// and on the Outline's lane row, while the toolbar and the status bar said 1: the lane total was
// summed per node and per edge. A group's badge summed its own findings and each child's the
// same way.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

const plain = (value) => JSON.parse(JSON.stringify(value));

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Finding counts fixture',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'train', label: 'Train' }, { id: 'persist', label: 'Persistence and reload demo' }],
    nodes: [
      { id: 'fit', label: 'Fit', phase: 'train', basis: 'observed', evidence: ['e'] },
      { id: 'dump', label: 'Dump model', phase: 'persist', basis: 'observed', evidence: ['e'] },
      { id: 'reload-deps', label: 'Reload dependencies', phase: 'persist', basis: 'observed', evidence: ['e'] },
      { id: 'reload', label: 'Reload model', phase: 'persist', basis: 'observed', evidence: ['e'] },
    ],
    edges: [
      { id: 'e-fit-dump', source: 'fit', target: 'dump', label: 'model', basis: 'observed', evidence: ['e'] },
      { id: 'e-deps-reload', source: 'reload-deps', target: 'reload', label: 'imports', basis: 'observed', evidence: ['e'] },
      { id: 'e-dump-reload', source: 'dump', target: 'reload', label: 'pickle', basis: 'observed', evidence: ['e'] },
    ],
    findings: [{
      id: 'f-reload-fresh-process', title: 'Reload runs in the same process', message: 'm', severity: 'medium',
      nodeIds: ['reload-deps', 'reload', 'dump'], edgeIds: ['e-deps-reload', 'e-dump-reload'], basis: 'inferred', evidence: ['e'],
    }],
    evidence: [{ id: 'e', file: 'demo.ipynb', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['demo.ipynb'], limitations: [] },
    ...overrides,
  };
}

async function mount(document) {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, document, recordingBridge(ctx.window, 'vscode'));
  return { ...ctx, root, app };
}

/** A severity cluster as { severity: count }, read from the drawn items. */
function cluster(element) {
  const out = {};
  if (!element) return out;
  for (const item of element.querySelectorAll('.mlv-cluster__item')) {
    const sev = ['high', 'medium', 'low'].find((s) => item.classList.contains('mlv-cluster__item--' + s));
    out[sev] = Number(item.querySelector('.mlv-cluster__count').textContent);
  }
  return out;
}

const laneCluster = (ctx, lane) => ctx.document.querySelector(`.mlv-lane[data-lane-id="${lane}"] .mlv-cluster`);
const headerCount = (ctx, sev) => Number(ctx.document.querySelector(`.mlv-chip--btn[data-severity="${sev}"] .mlv-chip__count`).textContent);
/** Viewer M2: the findings are counted once, on the header's severity toggles; the status bar never repeats them. */
const statusFindingText = (ctx) => /finding/.test(ctx.document.querySelector('.mlv-status').textContent);

/** The Outline lane row's count. Viewer M2: it names its unit ("2 findings touch this phase"). */
function outlineLaneCount(ctx, lane) {
  ctx.app.setRailTab('outline');
  const count = ctx.document.querySelector(`[data-outline-lane="${lane}"] .mlv-outline__row--lane .mlv-outline__stage`);
  if (!count) return 0;
  const m = /^(\d+) (finding touches|findings touch) this phase$/.exec(count.textContent);
  assert.ok(m, 'the Outline lane count names its unit: ' + count.textContent);
  return Number(m[1]);
}

test('one finding on three steps and two connections of a phase counts once on the lane badge and the outline row', async () => {
  const ctx = await mount(doc());
  assert.equal(headerCount(ctx, 'medium'), 1, 'precondition: the header counts one finding');
  assert.equal(statusFindingText(ctx), false, 'precondition: the status bar does not count them a second time');
  const lane = laneCluster(ctx, 'persist');
  assert.deepEqual(cluster(lane), { medium: 1 }, 'the lane header agrees with the toolbar');
  // Viewer M2: the lane says what it counts, and that this is not a partition (PR #14 rule).
  assert.equal(lane.getAttribute('aria-label'), '1 finding touches this phase, highest severity medium. A finding that cites steps or connections in several phases counts in each of them.');
  assert.equal(ctx.document.querySelector('.mlv-lane[data-lane-id="persist"] .mlv-lane__unit').textContent, 'finding touches this phase');
  assert.equal(laneCluster(ctx, 'train'), null, 'the finding names nothing in the other phase');
  assert.equal(outlineLaneCount(ctx, 'persist'), 1, 'the Outline lane row agrees too');
  assert.deepEqual(plain(ctx.app.index.laneCounts('persist', () => true)), { low: 0, medium: 1, high: 0 });
  // The filter still applies: hiding medium findings empties the badge.
  ctx.app.setFilters({ severities: ['high', 'low'] });
  assert.equal(laneCluster(ctx, 'persist'), null);
  ctx.app.destroy();
});

test('a finding that touches two phases is counted once in each lane', async () => {
  const base = doc();
  const ctx = await mount(doc({
    findings: base.findings.concat([{
      id: 'f-handoff', title: 'Model handed over unsaved', message: 'm', severity: 'high',
      nodeIds: ['fit', 'dump'], edgeIds: ['e-fit-dump'], basis: 'inferred', evidence: ['e'],
    }]),
  }));
  assert.equal(headerCount(ctx, 'high'), 1);
  assert.equal(headerCount(ctx, 'medium'), 1);
  assert.deepEqual(cluster(laneCluster(ctx, 'train')), { high: 1 });
  assert.deepEqual(cluster(laneCluster(ctx, 'persist')), { high: 1, medium: 1 });
  assert.equal(outlineLaneCount(ctx, 'persist'), 2);
  assert.equal(outlineLaneCount(ctx, 'train'), 1);
  // Viewer M2 keeps the PR #14 rule: the lanes count findings TOUCHING each phase, so they add up
  // to more than the header (3 > 2), and each lane says so instead of posing as a partition.
  assert.equal(outlineLaneCount(ctx, 'persist') + outlineLaneCount(ctx, 'train'), 3);
  assert.equal(headerCount(ctx, 'high') + headerCount(ctx, 'medium'), 2);
  assert.equal(ctx.document.querySelector('.mlv-lane[data-lane-id="persist"] .mlv-lane__unit').textContent, 'findings touch this phase');
  assert.match(laneCluster(ctx, 'train').getAttribute('aria-label'), /^1 finding touches this phase, highest severity high\. A finding that cites steps or connections in several phases counts in each of them\.$/);
  ctx.app.destroy();
});

test('a finding on a group and its children counts once on the group, expanded or collapsed', async () => {
  const ctx = await mount(doc({
    phases: [{ id: 'loop', label: 'Loop' }],
    nodes: [
      { id: 'epochs', label: 'Epochs', phase: 'loop', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Step', phase: 'loop', parent: 'epochs', basis: 'observed', evidence: ['e'] },
      { id: 'eval', label: 'Eval', phase: 'loop', parent: 'epochs', basis: 'observed', evidence: ['e'] },
    ],
    edges: [{ id: 'e-step-eval', source: 'step', target: 'eval', label: 'weights', basis: 'observed', evidence: ['e'] }],
    findings: [{ id: 'f-loop', title: 'Eval inside the step loop', message: 'm', severity: 'low', nodeIds: ['epochs', 'step', 'eval'], edgeIds: [], basis: 'inferred', evidence: ['e'] }],
  }));
  assert.deepEqual(plain(ctx.app.index.subtreeCounts('epochs', () => true)), { low: 1, medium: 0, high: 0 });
  const header = ctx.document.querySelector('.mlv-group[data-node-id="epochs"] .mlv-group__header .mlv-cluster');
  assert.deepEqual(cluster(header), { low: 1 }, 'the expanded group header');
  assert.equal(header.getAttribute('aria-label'), '1 finding, highest severity low');
  ctx.app.view.toggleCollapse('epochs');
  const card = ctx.document.querySelector('.mlv-node[data-node-id="epochs"]');
  assert.deepEqual(cluster(card.querySelector('.mlv-cluster')), { low: 1 }, 'the collapsed group card');
  assert.match(card.getAttribute('aria-label'), /1 finding, highest severity low/);
  assert.deepEqual(cluster(laneCluster(ctx, 'loop')), { low: 1 });
  ctx.app.destroy();
});

test('a collapsed group counts the finding on a connection it hides', async () => {
  // Collapsing `epochs` drops e-step-eval from the canvas (both ends inside), so the card is the
  // only place left to show its finding. The group's own self-loop stays drawn with its marker.
  const ctx = await mount(doc({
    phases: [{ id: 'loop', label: 'Loop' }],
    nodes: [
      { id: 'epochs', label: 'Epochs', phase: 'loop', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Step', phase: 'loop', parent: 'epochs', basis: 'observed', evidence: ['e'] },
      { id: 'eval', label: 'Eval', phase: 'loop', parent: 'epochs', basis: 'observed', evidence: ['e'] },
    ],
    edges: [
      { id: 'e-step-eval', source: 'step', target: 'eval', label: 'weights', basis: 'observed', evidence: ['e'] },
      { id: 'e-again', source: 'epochs', target: 'epochs', label: 'next epoch', kind: 'loop', basis: 'observed', evidence: ['e'] },
    ],
    findings: [
      { id: 'f-edge', title: 'Weights leak into eval', message: 'm', severity: 'high', nodeIds: [], edgeIds: ['e-step-eval'], basis: 'inferred', evidence: ['e'] },
      { id: 'f-child', title: 'Step reuses a batch', message: 'm', severity: 'low', nodeIds: ['step'], edgeIds: [], basis: 'inferred', evidence: ['e'] },
      { id: 'f-loop', title: 'Epoch count unchecked', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['e-again'], basis: 'inferred', evidence: ['e'] },
    ],
  }));
  const header = ctx.document.querySelector('.mlv-group[data-node-id="epochs"] .mlv-group__header .mlv-cluster');
  assert.deepEqual(cluster(header), { high: 1, low: 1 }, 'the expanded group header');
  ctx.app.view.toggleCollapse('epochs');
  assert.equal(ctx.document.querySelector('.mlv-edge[data-edge-id="e-step-eval"]'), null, 'precondition: the cable is hidden');
  assert.ok(ctx.document.querySelector('.mlv-edge[data-edge-id="e-again"] .mlv-edge-marker--medium'), 'the self-loop keeps its marker');
  const card = ctx.document.querySelector('.mlv-node[data-node-id="epochs"]');
  assert.deepEqual(cluster(card.querySelector('.mlv-cluster')), { high: 1, low: 1 }, 'the collapsed group card');
  assert.match(card.getAttribute('aria-label'), /2 findings, highest severity high/);
  assert.deepEqual(cluster(laneCluster(ctx, 'loop')), { high: 1, medium: 1, low: 1 });
  ctx.app.destroy();
});
