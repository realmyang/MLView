import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

/** A posted request without its generated `requestId`, which is checked separately. */
function withoutRequestId(message) {
  const { requestId, ...rest } = JSON.parse(JSON.stringify(message));
  assert.match(requestId, /^[A-Za-z0-9_-]{1,64}$/, 'every result-bearing request carries a valid requestId');
  return rest;
}

function workflow(revision = 'r1') {
  return {
    workflowVersion: '1.0', title: 'Training and review',
    producer: { kind: 'host-llm', host: 'codex', model: 'gpt-test' }, revision: { id: revision },
    request: { question: 'How is this model trained?', scope: 'src/', entrypoints: ['src/train.py'] },
    phases: [{ id: 'load', label: 'Load' }, { id: 'loop', label: 'Repeated training' }, { id: 'review', label: 'Human review' }],
    nodes: [
      { id: 'dataset', label: 'Read records', phase: 'load', basis: 'observed', evidence: ['ev-load'] },
      { id: 'epoch', label: 'Epoch', phase: 'loop', kind: 'group', basis: 'inferred', evidence: [] },
      { id: 'step', label: 'Update weights', phase: 'loop', parent: 'epoch', basis: 'observed', evidence: ['ev-step', 'ev-loss'] },
      { id: 'gate', label: 'Approval gate', phase: 'review', basis: 'unresolved', evidence: [] },
    ],
    edges: [
      { id: 'flow', source: 'dataset', target: 'step', label: 'batches', basis: 'observed', evidence: ['ev-load'] },
      { id: 'cycle', source: 'step', target: 'epoch', label: 'next epoch', kind: 'control', basis: 'inferred', evidence: ['ev-step', 'ev-load'] },
      { id: 'review', source: 'step', target: 'gate', label: 'candidate', basis: 'unresolved', evidence: [] },
    ],
    findings: [{ id: 'loss-risk', title: 'Loss is aggregated late', message: 'The update uses a delayed aggregate.', severity: 'medium', nodeIds: ['step'], edgeIds: ['cycle'], basis: 'inferred', evidence: ['ev-step', 'ev-loss'], counterEvidence: ['ev-load'], suggestion: 'Verify the intended reduction.' }],
    evidence: [
      { id: 'ev-load', file: 'src/data.py', line: 10, endLine: 14, quote: 'load()' },
      { id: 'ev-step', file: 'src/train.py', line: 42, endLine: 47, quote: 'optimizer.step()', cell: 0 },
      { id: 'ev-loss', file: 'src/train.py', line: 35, endLine: 36, quote: 'loss.mean()' },
    ],
    coverage: { status: 'partial', summary: 'Core training path inspected', inspectedFiles: ['src/train.py', 'src/data.py'], limitations: ['Approval implementation was not found.'] },
  };
}

test('normalizes authored phases, hierarchy, cycles, evidence, and findings without static rule codes', async () => {
  const { MLView } = await loadBundle();
  const graph = MLView.normalizeWorkflow(workflow());
  assert.equal(graph.schemaVersion, 'workflow-view/1');
  assert.deepEqual(Array.from(graph.stages, (s) => s.id), ['load', 'loop', 'review']);
  assert.equal(graph.nodes.find((n) => n.id === 'step').parent, 'epoch');
  assert.equal(graph.nodes.find((n) => n.id === 'gate').ghost, false,
    'unresolved is uncertainty, never a claim that the step is missing');
  assert.equal(graph.edges.find((e) => e.id === 'cycle').target, 'epoch');
  assert.match(graph.edges.find((e) => e.id === 'cycle').label, /inferred/);
  assert.equal(graph.issues[0].code, 'loss-risk');
  assert.equal(graph.issues[0].relatedLocs.length, 3);
  assert.deepEqual(Array.from(graph.issues[0].relatedLocs, (loc) => loc.role), ['Supporting evidence', 'Supporting evidence', 'Counter-evidence']);
  assert.equal(graph.issues[0].loc.evidenceId, 'ev-step');
  assert.equal(graph.issues[0].confidenceBucket, 'inferred');
  assert.equal(Number.isNaN(graph.issues[0].confidence), true, 'authored basis must not invent a numeric confidence');
  assert.equal(graph.stats.truncated, false, 'authored partial coverage is not legacy node-cap truncation');
  assert.equal(graph.nodes.find((n) => n.id === 'epoch').loc.absFile, '');
  assert.deepEqual(Array.from(graph.nodes.find((n) => n.id === 'step').evidenceLocs, (loc) => loc.evidenceId), ['ev-step', 'ev-loss']);
  assert.deepEqual(Array.from(graph.edges.find((e) => e.id === 'cycle').evidenceLocs, (loc) => loc.evidenceId), ['ev-step', 'ev-load']);
});

test('mountWorkflow identifies authored provenance and accepts revision updates and inbound documents', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, workflow(), bridge);
  assert.ok(root.classList.contains('mlv-root--workflow'));
  assert.match(root.querySelector('.mlv-workflow').textContent, /Training and review/);
  assert.match(root.querySelector('.mlv-workflow').textContent, /codex · gpt-test/);
  assert.match(root.querySelector('.mlv-workflow').textContent, /partial · Core training path inspected/);
  assert.doesNotMatch(root.querySelector('.mlv-banners').textContent, /Graph truncated|graph was truncated/i);
  assert.match(root.querySelector('.mlv-workflow__verification').textContent, /Draft · source freshness not verified/);
  assert.equal(root.querySelector('[role="tab"][aria-controls$="-panel-issues"]').textContent, 'Findings');
  const search = root.querySelector('.mlv-search input[type="search"]');
  assert.equal(search.placeholder, 'Search steps, findings, IDs, or cited text…');
  assert.equal(root.querySelector(`label[for="${search.id}"]`).textContent, 'Search steps, findings, IDs, or cited text');
  assert.equal(root.querySelector('[data-node-id="step"]') !== null, true);
  app.setWorkflow(workflow('r2'));
  assert.equal(root.getAttribute('data-workflow-revision'), 'r2');
  bridge.send({ v: 1, type: 'workflow', document: workflow('r3') });
  assert.equal(root.getAttribute('data-workflow-revision'), 'r3');
  app.destroy();
});

test('rail tabs support wrapped arrow navigation plus Home and End without consuming Tab', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, workflow(), recordingBridge(ctx.window, 'vscode'));
  const tabs = [...root.querySelectorAll('[role="tab"]')];
  assert.deepEqual(tabs.map((tab) => tab.textContent), ['Findings', 'Inspector', 'Outline']);

  tabs[0].focus();
  tabs[0].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, tabs[1]);
  assert.equal(tabs[1].getAttribute('aria-selected'), 'true');

  tabs[1].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, tabs[2]);
  tabs[2].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, tabs[0], 'ArrowRight wraps to the first tab');
  tabs[0].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, tabs[2], 'ArrowLeft wraps to the last tab');
  tabs[2].dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Home', bubbles: true, cancelable: true }));
  assert.equal(ctx.document.activeElement, tabs[0]);

  const tabEvent = new ctx.window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
  tabs[0].dispatchEvent(tabEvent);
  assert.equal(tabEvent.defaultPrevented, false);
  assert.equal(ctx.document.activeElement, tabs[0], 'the browser remains responsible for Tab movement');
  app.destroy();
});

test('SVG export carries authored producer, model, revision, and title provenance', async () => {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow('export-rev'), bridge);
  ctx.document.querySelector('.mlv-btn--exportmenu').click();
  ctx.document.querySelector('[data-export-action="svg"]').click();
  const frame = bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  assert.ok(frame);
  const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
  assert.match(svg, /MLView — Training and review/);
  assert.match(svg, /authored by codex · model gpt-test · revision export-rev/);
  assert.doesNotMatch(svg, /NaN|confidence="100|100%/);
});

test('refinement posts the current stable selection and short intent', async () => {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow('revision-7'), bridge);
  app.select({ kind: 'edge', id: 'cycle' }, { tab: 'inspector' });
  ctx.document.querySelector('.mlv-workflow__refine').click();
  assert.equal(ctx.document.querySelector('.mlv-workflow__selection').textContent, 'edge: cycle');
  ctx.document.querySelector('.mlv-workflow__intent').value = 'trace';
  ctx.document.querySelector('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.deepEqual(withoutRequestId(bridge.posted.at(-1)), {
    v: 1, type: 'refineWorkflow', revisionId: 'revision-7', selection: { kind: 'edge', id: 'cycle' }, intent: 'trace',
  });
  assert.match(ctx.document.querySelector('.mlv-workflow__meta').textContent, /Entrypoints: src\/train.py/);
  assert.match(ctx.document.querySelector('.mlv-workflow__meta').textContent, /Configuration: not specified/);
});

test('source-less concepts do not fabricate file jumps and epistemic basis stays visible', async () => {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow(), bridge);
  app.select({ kind: 'node', id: 'epoch' }, { open: true, tab: 'inspector' });
  assert.equal(bridge.posted.some((item) => item.type === 'openLocation'), false);
  assert.equal(ctx.document.querySelector('.mlv-insp__actions').textContent.includes('Open'), false);
  assert.match(ctx.document.querySelector('[data-node-id="epoch"]').textContent, /inferred/);
  app.focusIssue('loss-risk');
  assert.equal(ctx.document.querySelector('[data-issue-id="loss-risk"] [data-basis="inferred"]') !== null, true);
  const basis = ctx.document.querySelector('[data-issue-id="loss-risk"] [data-basis="inferred"]');
  assert.equal(basis.getAttribute('aria-label'), 'Basis: inferred');
  assert.doesNotMatch(basis.getAttribute('title'), /100%/);
  assert.equal(ctx.document.querySelector('[data-node-id="epoch"]').classList.contains('is-lowconf'), false,
    'absence of a calibrated percentage must not fabricate a low-confidence state');
  app.setFilters({ severities: ['high'] });
  assert.equal(ctx.document.querySelector('.mlv-issue[data-issue-id="loss-risk"]'), null,
    'authored basis does not bypass ordinary severity filtering');
  app.setFilters({ severities: ['medium'] });
  assert.ok(ctx.document.querySelector('.mlv-issue[data-issue-id="loss-risk"]'),
    'authored finding remains available after filters are restored');
  assert.match(ctx.document.querySelector('[data-edge-id="cycle"] [role="button"]').getAttribute('aria-label'), /inferred/);
  app.destroy();
});

test('ten authored phases keep array order, duplicate labels, cycles, and exact stage scopes', async () => {
  const doc = workflow();
  doc.phases = Array.from({ length: 10 }, (_, i) => ({ id: 'phase-' + i, label: i === 2 || i === 7 ? 'Repeat' : 'Phase ' + i }));
  doc.nodes = doc.phases.map((phase, i) => ({ id: 'node-' + i, label: 'Node ' + i, phase: phase.id, parent: i === 4 ? 'node-3' : undefined, basis: i % 3 === 0 ? 'observed' : i % 3 === 1 ? 'inferred' : 'unresolved', evidence: i === 0 ? ['ev-load'] : [] }));
  doc.edges = doc.nodes.map((node, i) => ({ id: 'edge-' + i, source: node.id, target: doc.nodes[(i + 1) % doc.nodes.length].id, label: 'flow ' + i, basis: i % 2 ? 'inferred' : 'observed', evidence: [] }));
  doc.findings = [];
  const ctx = await loadBundle();
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), doc, recordingBridge(ctx.window, 'vscode'));
  assert.deepEqual(Array.from(app.graph.stages, (stage) => stage.id), doc.phases.map((phase) => phase.id));
  assert.equal(app.graph.stages.filter((stage) => stage.label === 'Repeat').length, 2);
  assert.equal(app.index.edgeById.get('edge-9').target, 'node-0');
  app.setScope('stage:phase-7');
  assert.equal(app.getScope().nodes, 1);
  assert.equal(app.graph.nodes[0].stage, 'phase-7');
  app.destroy();
});

test('authored source navigation carries the evidence id and notebook cell', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, workflow(), bridge);
  app.focusNode('step');
  app.openLocation(app.locOf({ kind: 'node', id: 'step' }));
  const message = bridge.posted.findLast((item) => item.type === 'openLocation');
  assert.equal(message.evidenceId, 'ev-step');
  assert.equal(message.cell, 0);
  assert.equal(message.line, 42);
  app.destroy();
});

test('node and edge inspectors expose every authored evidence anchor and post its identity', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, workflow(), bridge);

  app.select({ kind: 'node', id: 'step' }, { tab: 'inspector' });
  let anchors = Array.from(root.querySelectorAll('.mlv-rail__panel:not([hidden]) .mlv-insp__source-evidence [data-evidence-id]'));
  assert.deepEqual(anchors.map((item) => item.getAttribute('data-evidence-id')), ['ev-step', 'ev-loss']);
  anchors[1].click();
  let opened = bridge.posted.findLast((item) => item.type === 'openLocation');
  assert.equal(opened.evidenceId, 'ev-loss');
  assert.equal(opened.line, 35);

  app.select({ kind: 'edge', id: 'cycle' }, { tab: 'inspector' });
  anchors = Array.from(root.querySelectorAll('.mlv-rail__panel:not([hidden]) .mlv-insp__source-evidence [data-evidence-id]'));
  assert.deepEqual(anchors.map((item) => item.getAttribute('data-evidence-id')), ['ev-step', 'ev-load']);
  assert.match(root.querySelector('.mlv-rail__panel:not([hidden])').textContent, /basis · inferred/);
  anchors[0].click();
  opened = bridge.posted.findLast((item) => item.type === 'openLocation');
  assert.equal(opened.evidenceId, 'ev-step');
  assert.equal(opened.cell, 0);
  assert.match(root.querySelector('.mlv-rail__panel:not([hidden])').textContent, /optimizer\.step\(\).*load\(\)/s,
    'edge inspector shows every evidence quote');
  app.destroy();
});

test('authored legend separates basis, severity impact, and source freshness', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, workflow(), recordingBridge(ctx.window, 'vscode'));
  root.querySelector('.mlv-btn--legend').click();
  const legend = root.querySelector('.mlv-legend').textContent;
  assert.match(legend, /Claim basis/);
  assert.match(legend, /Unresolved.*does not mean the step is absent/);
  assert.match(legend, /Severity does not express certainty/);
  assert.match(legend, /Source freshness/);
  assert.doesNotMatch(legend, /Missing step|rule wants|analyzer could not resolve statically/);
  assert.equal(root.querySelector('[data-node-id="gate"]').classList.contains('is-ghost'), false);
  app.destroy();
});

test('outline enumerates textual relationships by direction and preserves basis', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, workflow(), recordingBridge(ctx.window, 'vscode'));
  app.focusNode('step');
  app.setRailTab('outline');
  let panel = root.querySelector('.mlv-rail__panel:not([hidden])');
  assert.match(panel.querySelector('.mlv-relations__context').textContent, /Update weights/);
  assert.equal(panel.querySelector('[data-outline-id="dataset"] .mlv-outline__stage').textContent, 'observed');
  assert.equal(panel.querySelector('[data-outline-id="epoch"] .mlv-outline__stage').textContent, 'inferred');
  assert.equal(panel.querySelector('[data-outline-id="gate"] .mlv-outline__stage').textContent, 'unresolved');
  assert.doesNotMatch(panel.querySelector('[data-outline-id="dataset"]').textContent, /unknown/i);
  assert.deepEqual(Array.from(panel.querySelectorAll('[data-relation-id]'), (row) => row.getAttribute('data-relation-id')), ['cycle', 'review']);
  assert.match(panel.querySelector('[data-relation-id="cycle"]').getAttribute('aria-label'), /Outgoing: Update weights to Epoch; next epoch · inferred; basis inferred/);

  panel.querySelector('[data-relation-view="incoming"]').click();
  assert.deepEqual(Array.from(panel.querySelectorAll('[data-relation-id]'), (row) => row.getAttribute('data-relation-id')), ['flow']);
  assert.match(panel.querySelector('[data-relation-id="flow"]').textContent, /Read records → Update weights/);
  panel.querySelector('[data-relation-id="flow"]').click();
  app.setRailTab('outline');
  panel = root.querySelector('.mlv-rail__panel:not([hidden])');
  assert.equal(panel.querySelector('[data-relation-view="incoming"]').getAttribute('aria-pressed'), 'true');
  assert.deepEqual(Array.from(panel.querySelectorAll('[data-relation-id]'), (row) => row.getAttribute('data-relation-id')), ['flow']);

  panel.querySelector('[data-relation-view="all"]').click();
  assert.equal(panel.querySelectorAll('[data-relation-id]').length, 3);
  panel.querySelector('[data-relation-view="unresolved"]').click();
  assert.deepEqual(Array.from(panel.querySelectorAll('[data-relation-id]'), (row) => row.getAttribute('data-relation-id')), ['review']);
  panel.querySelector('[data-relation-view="all"]').click();
  panel.querySelector('[data-relation-id="review"]').click();
  assert.deepEqual(JSON.parse(JSON.stringify(app.getState().selection)), { kind: 'edge', id: 'review' });
  assert.match(root.querySelector('.mlv-rail__panel:not([hidden])').textContent, /Update weights → Approval gate/);
  app.destroy();
});

test('finding inspector keeps claim, supporting evidence, counter-evidence, and suggested check together', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, workflow(), recordingBridge(ctx.window, 'vscode'));
  app.focusNode('step');
  const issue = root.querySelector('.mlv-insp__issue[data-issue-id="loss-risk"]');
  assert.match(issue.textContent, /The update uses a delayed aggregate/);
  assert.match(issue.textContent, /Suggested check.*Verify the intended reduction/);
  assert.match(issue.textContent, /Evidence review.*Supporting evidence.*Counter-evidence/);
  assert.deepEqual(Array.from(issue.querySelectorAll('[data-evidence-id]'), (row) => row.getAttribute('data-evidence-id')), ['ev-step', 'ev-loss', 'ev-load']);
  assert.match(issue.textContent, /optimizer\.step\(\).*loss\.mean\(\).*load\(\)/s);
  assert.match(root.querySelector('.mlv-rail__panel:not([hidden])').textContent, /Coverage limitations.*Approval implementation was not found/s);
  app.destroy();
});

test('evidence navigation explains boundaries and source-less authored items', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, workflow(), bridge);
  app.focusNode('step');
  const previous = root.querySelector('.mlv-insp__evidence-nav button:first-child');
  const next = root.querySelector('.mlv-insp__evidence-nav button:last-child');
  assert.equal(previous.disabled, true);
  assert.match(previous.title, /first evidence item/);
  assert.equal(next.disabled, false);
  root.querySelector('.mlv-insp__source-evidence [data-evidence-id="ev-loss"]').click();
  assert.equal(next.disabled, true, 'opening an anchor moves the adjacent-evidence cursor');
  assert.equal(previous.disabled, false);
  previous.click();
  assert.equal(bridge.posted.findLast((item) => item.type === 'openLocation').evidenceId, 'ev-step');
  next.click();
  assert.equal(bridge.posted.findLast((item) => item.type === 'openLocation').evidenceId, 'ev-loss');
  assert.equal(next.disabled, true);
  assert.match(next.title, /last evidence item/);

  app.focusNode('epoch');
  assert.match(root.querySelector('.mlv-insp__no-evidence').textContent, /No source evidence was authored.*remains uncertain/);
  app.destroy();
});

test('finding-only selection has a complete inspector and direct challenge action', async () => {
  const doc = workflow('finding-only-revision');
  doc.findings.push({
    id: 'workspace-risk', title: 'Environment remains unknown', message: 'The runtime environment was not available.',
    severity: 'low', nodeIds: [], basis: 'unresolved', evidence: [], suggestion: 'Inspect the launch environment.',
  });
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, doc, bridge);
  app.focusIssue('workspace-risk');
  app.setRailTab('inspector');
  const panel = root.querySelector('.mlv-rail__panel:not([hidden])');
  assert.match(panel.textContent, /Environment remains unknown.*runtime environment was not available.*Inspect the launch environment/s);
  panel.querySelector('.mlv-insp__challenge').click();
  assert.equal(bridge.posted.some((item) => item.type === 'refineWorkflow'), false,
    'challenge prepares the prompt for review before copying');
  assert.equal(root.querySelector('.mlv-workflow__selection').textContent, 'issue: workspace-risk');
  root.querySelector('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.deepEqual(withoutRequestId(bridge.posted.at(-1)), {
    v: 1, type: 'refineWorkflow', revisionId: 'finding-only-revision',
    selection: { kind: 'issue', id: 'workspace-risk' }, intent: 'challenge',
  });
  app.destroy();
});

test('challenge replaces an older composer selection with the current claim', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, workflow(), bridge);
  app.focusNode('epoch');
  root.querySelector('.mlv-workflow__refine').click();
  app.select({ kind: 'edge', id: 'cycle' }, { tab: 'inspector' });
  root.querySelector('.mlv-rail__panel:not([hidden]) .mlv-insp__challenge').click();
  assert.equal(root.querySelector('.mlv-workflow__selection').textContent, 'edge: cycle');
  root.querySelector('.mlv-workflow__composer').dispatchEvent(new ctx.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.deepEqual(JSON.parse(JSON.stringify(bridge.posted.at(-1).selection)), { kind: 'edge', id: 'cycle' });
  app.destroy();
});

test('authored help and grouping avoid retired rule terminology', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, workflow(), recordingBridge(ctx.window, 'vscode'));
  app.toggleShortcuts(true);
  const sheet = root.querySelector('.mlv-sheet').textContent;
  assert.match(sheet, /Search steps, findings, IDs, or cited text/);
  assert.match(sheet, /Next \/ previous finding \(document order\)/);
  assert.match(sheet, /Findings \/ Inspector \/ Outline/);
  assert.doesNotMatch(sheet, /rule codes|issue by severity/i);
  // VIEWUI-12: finding IDs are unique, so grouping by them is not offered and
  // a requested or restored `rule` grouping falls back to none.
  app.setRailGroupBy('rule');
  assert.equal(root.querySelector('[data-group-mode="rule"]'), null);
  assert.ok(root.querySelector('[data-group-mode="file"]'));
  assert.equal(app.getState().railGroupBy, undefined);
  assert.equal(root.querySelector('[data-disable-rule]'), null);
  app.destroy();
});

test('rejects a document that lacks the authored contract discriminant', async () => {
  const { MLView } = await loadBundle();
  assert.throws(() => MLView.normalizeWorkflow({ workflowVersion: '0.9' }), /workflowVersion must be 1.0/);
});

test('ships only the authored workflow public surface', async () => {
  const { MLView } = await loadBundle();
  assert.equal(typeof MLView.mountWorkflow, 'function');
  assert.equal(typeof MLView.bridges.vscode, 'function');
  assert.equal('mount' in MLView, false);
  assert.equal('standalone' in MLView.bridges, false);
  assert.equal('__internal' in MLView, false);
});

test('legacy graph messages and static finding actions are absent from the authored renderer', async () => {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow(), bridge);
  bridge.send({ v: 1, type: 'graph', graph: { schemaVersion: '1.0', nodes: [], edges: [], issues: [] } });
  assert.equal(app.graph.schemaVersion, 'workflow-view/1');
  assert.equal(ctx.document.querySelector('[data-copy-ignore]'), null);
  assert.equal(ctx.document.querySelector('[data-disable-rule]'), null);
  assert.equal(ctx.document.querySelector('[data-apply-fix]'), null);
  assert.equal(ctx.document.querySelector('[data-rule-doc]'), null);
  assert.ok(bridge.posted.some((message) => message.type === 'log' && /unknown message type: graph/.test(message.message)));
  app.destroy();
});

test('authored scope and selection survive a revision update', async () => {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(ctx.document.getElementById('mlview-root'), workflow(), bridge);
  app.setScope('stage:loop');
  app.focusNode('step');
  const before = app.getState();
  app.setWorkflow(workflow('r-next'), { scope: before.scope, selection: before.selection, viewport: before.viewport });
  assert.equal(app.getScope().spec, 'stage:loop');
  assert.deepEqual(JSON.parse(JSON.stringify(app.getState().selection)), { kind: 'node', id: 'step' });
  assert.ok(ctx.document.querySelector('[data-node-id="step"]'));
  assert.equal(ctx.document.querySelector('[data-node-id="dataset"]'), null);
  app.destroy();
});
