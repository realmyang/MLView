// Authored documents must not inherit analyzer claims: zero-finding wording,
// workflow-level findings, scope and search handles, notebook cells, grouping,
// provenance text, finding connectors, config parsing, DOM ids and exports.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

function workflow(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Training and review',
    producer: { kind: 'host-llm', host: 'codex', model: 'gpt-test' }, revision: { id: 'r1' },
    request: { question: 'How is this model trained?', scope: 'src/', entrypoints: ['src/train.py'] },
    phases: [{ id: 'load', label: 'Load' }, { id: 'loop', label: 'Repeated training' }],
    nodes: [
      { id: 'dataset', label: 'Read records', phase: 'load', basis: 'observed', evidence: ['ev-load'] },
      { id: 'epoch', label: 'Epoch', phase: 'loop', kind: 'group', basis: 'inferred', evidence: [] },
      { id: 'step', label: 'Update weights', phase: 'loop', parent: 'epoch', basis: 'observed', evidence: ['ev-step', 'ev-loss'] },
    ],
    edges: [
      { id: 'flow', source: 'dataset', target: 'step', label: 'batches', basis: 'observed', evidence: ['ev-load'] },
    ],
    findings: [{ id: 'loss-risk', title: 'Loss is aggregated late', message: 'The update uses a delayed aggregate.', severity: 'medium', nodeIds: ['step'], basis: 'inferred', evidence: ['ev-step'] }],
    evidence: [
      { id: 'ev-load', file: 'src/data.py', line: 10, endLine: 14, quote: 'load()' },
      { id: 'ev-step', file: 'src/train.py', line: 42, endLine: 47, quote: 'optimizer.step()' },
      { id: 'ev-loss', file: 'src/train.py', line: 35, endLine: 36, quote: 'loss.mean()' },
    ],
    coverage: { status: 'partial', summary: 'Core training path inspected', inspectedFiles: ['src/train.py', 'src/data.py'], limitations: ['Approval implementation was not found.'] },
    ...overrides,
  };
}

async function mount(doc = workflow()) {
  const ctx = await loadBundle();
  const bridge = recordingBridge(ctx.window, 'vscode');
  const root = ctx.document.getElementById('mlview-root');
  const app = ctx.MLView.mountWorkflow(root, doc, bridge);
  return { ...ctx, root, bridge, app };
}

const issueRows = (ctx) => Array.from(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]'), (row) => row.getAttribute('data-issue-id'));

test('zero authored findings are described as none recorded, never as a clean check', async () => {
  const ctx = await mount(workflow({ findings: [] }));
  const panel = ctx.root.querySelector('.mlv-rail__panel:not([hidden])').textContent;
  assert.match(panel, /No findings recorded in this revision/);
  assert.match(panel, /The assistant recorded no findings\. Coverage: partial; 1 limitation listed above\. This is not a check result\./);
  assert.doesNotMatch(panel, /nothing to flag|checked|No issues found/);
  ctx.app.destroy();

  const scoped = await mount(workflow({ findings: [], coverage: { status: 'scoped', summary: 's', inspectedFiles: ['src/train.py'], limitations: [] } }));
  assert.match(scoped.root.querySelector('.mlv-rail__panel:not([hidden])').textContent,
    /The assistant recorded no findings\. Coverage: scoped\. This is not a check result\./);
  scoped.app.destroy();
});

test('a workflow-level finding stays listed under every severity filter, and an old phase filter is ignored', async () => {
  // Port of critic-repros/wf_finding.mjs.
  const doc = {
    workflowVersion: '1.0', title: 'T', producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'load', label: 'Load' }, { id: 'train', label: 'Train' }],
    nodes: [
      { id: 'a', label: 'Read', phase: 'load', basis: 'observed', evidence: ['e'] },
      { id: 'b', label: 'Fit', phase: 'train', basis: 'observed', evidence: ['e'] },
    ],
    edges: [{ id: 'ab', source: 'a', target: 'b', label: 'batches', basis: 'observed', evidence: ['e'] }],
    findings: [
      { id: 'node-level', title: 'Node finding', message: 'm', severity: 'medium', nodeIds: ['b'], basis: 'inferred', evidence: ['e'] },
      { id: 'workflow-level', title: 'Workflow-level finding', message: 'No seed is set anywhere in the run', severity: 'high', nodeIds: [], basis: 'inferred', evidence: ['e'] },
    ],
    evidence: [{ id: 'e', file: 'train.py', line: 1, endLine: 1, quote: 'x' }],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] },
  };
  const ctx = await mount(doc);
  assert.deepEqual(issueRows(ctx).sort(), ['node-level', 'workflow-level']);
  // Viewer M2 removed the phase chips and the scope picker: a host still sending the old phase
  // filter changes nothing, and the whole document stays drawn.
  ctx.app.setFilters({ stages: ['load'] });
  assert.deepEqual(issueRows(ctx).sort(), ['node-level', 'workflow-level'], 'the old phase filter is ignored');
  assert.equal('stages' in ctx.app.getState().filters, false, 'and never written back');
  ctx.app.setFilters({ severities: ['high'] });
  assert.deepEqual(issueRows(ctx), ['workflow-level']);
  ctx.app.setFilters({ severities: ['medium'] });
  assert.deepEqual(issueRows(ctx), ['node-level']);
  assert.deepEqual(Array.from(ctx.app.graph.issues, (issue) => issue.id).sort(), ['node-level', 'workflow-level']);
  assert.equal(typeof ctx.app.setScope, 'undefined');
  ctx.app.destroy();
});

test('three authored entrypoints open no pipeline chooser and no scope picker', async () => {
  const doc = workflow({
    request: { question: 'q', scope: 's', entrypoints: ['a.py', 'b.py', 'c.py'] },
    phases: [{ id: 'train', label: 'Train' }],
    nodes: ['a', 'b', 'c'].flatMap((name) => [
      { id: name + '-1', label: name + ' one', phase: 'train', basis: 'observed', evidence: ['ev-' + name] },
      { id: name + '-2', label: name + ' two', phase: 'train', basis: 'observed', evidence: ['ev-' + name] },
      { id: name + '-3', label: name + ' three', phase: 'train', basis: 'observed', evidence: ['ev-' + name] },
    ]),
    edges: [],
    findings: ['a', 'b', 'c'].map((name) => ({ id: 'f-' + name, title: 't', message: 'm', severity: 'high', nodeIds: [name + '-1'], basis: 'inferred', evidence: ['ev-' + name] })),
    evidence: ['a', 'b', 'c'].map((name) => ({ id: 'ev-' + name, file: name + '.py', line: 1, endLine: 1, quote: 'x' })),
  });
  doc.nodes.push({ id: 'concept', label: 'Concept group', phase: 'train', kind: 'group', basis: 'unresolved', evidence: [] });
  doc.nodes.push({ id: 'child', label: 'Concept child', phase: 'train', parent: 'concept', basis: 'unresolved', evidence: [] });
  const ctx = await mount(doc);
  assert.equal(ctx.root.querySelector('.mlv-pipechooser'), null, 'no pipeline chooser is built');
  // Viewer M2: the scope picker is gone; every step of the three entrypoints is drawn.
  assert.equal(ctx.root.querySelector('.mlv-btn--scope'), null);
  assert.equal(ctx.root.querySelector('.mlv-scopepicker'), null);
  assert.doesNotMatch(ctx.root.textContent, /not detected in this project|Pipelines|Concerns/);
  assert.equal(ctx.root.querySelectorAll('[data-node-id]').length, doc.nodes.length);
  ctx.app.destroy();
});

test('authored notebook evidence names its cell as the artifact records it, counted from 0, as the model labels it', async () => {
  const doc = workflow({
    evidence: [
      { id: 'ev-load', file: 'nb/explore.ipynb', cell: 7, line: 3, endLine: 3, quote: 'df = load()' },
      { id: 'ev-step', file: 'src/train.py', line: 42, endLine: 47, quote: 'optimizer.step()' },
      { id: 'ev-loss', file: 'src/train.py', line: 35, endLine: 36, quote: 'loss.mean()' },
    ],
  });
  const ctx = await mount(doc);
  ctx.app.select({ kind: 'node', id: 'dataset' }, { tab: 'inspector' });
  const anchor = ctx.root.querySelector('.mlv-rail__panel:not([hidden]) [data-evidence-id="ev-load"]');
  // Viewer M1: cell 7 is cell 7 everywhere (the skill, the helper's --cell, the extension and
  // the model's own labels count from 0); it used to print as "cell 8 : 3".
  assert.equal(anchor.textContent, 'Open nb/explore.ipynb › cell 7, line 3');
  assert.equal(anchor.title, 'cell 7, counted from 0 as the artifact records it (markdown cells count too); line 3 of that cell');
  assert.doesNotMatch(ctx.root.textContent, /concatenated code cells/);
  const card = ctx.root.querySelector('[data-node-id="dataset"]');
  assert.match(card.getAttribute('aria-label'), /nb\/explore\.ipynb cell 7 line 3/);
  ctx.app.destroy();
});

test('search finds stable ids and cited text, and shows no fake location', async () => {
  const ctx = await mount();
  const input = ctx.root.querySelector('.mlv-search .mlv-input');
  const search = (value) => {
    input.value = value;
    input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
    return Array.from(ctx.root.querySelectorAll('.mlv-search__results .mlv-result'));
  };
  assert.ok(search('dataset').some((row) => /Read records/.test(row.textContent)), 'node id');
  assert.ok(search('optimizer.step').some((row) => /Update weights/.test(row.textContent)), 'quoted evidence');
  assert.ok(search('src/data.py').some((row) => /Read records/.test(row.textContent)), 'cited file');
  const epoch = search('Epoch').find((row) => /Epoch/.test(row.textContent));
  assert.ok(epoch);
  assert.doesNotMatch(epoch.textContent, /:1\b/, 'an evidence-less step has no location');
  ctx.app.destroy();
});

test('the header names host and revision, its tooltip the model, and limitations are not chips', async () => {
  const ctx = await mount();
  // Viewer M2: the provenance chip is the one place the revision is named; the status bar no
  // longer repeats it.
  const chip = ctx.root.querySelector('.mlv-header__prov');
  assert.equal(chip.textContent, 'codex · r1');
  assert.match(chip.title, /^Revision r1 by codex \(gpt-test\)\. Published without source hashes\./);
  assert.doesNotMatch(ctx.app.chrome.status.textContent, /r1|codex|gpt-test/);
  assert.equal(ctx.root.querySelector('[data-diagnostic-kind="workflow_limitation"]'), null);
  assert.equal(ctx.root.querySelector('.mlv-chiprow'), null, 'no chip row to hold a limitation');
  assert.doesNotMatch(ctx.root.querySelector('.mlv-header').textContent, /Approval implementation/);
  ctx.app.destroy();
  const unnamed = await mount(workflow({ producer: { kind: 'host-llm', host: 'claude-code' } }));
  const named = unnamed.root.querySelector('.mlv-header__prov');
  assert.equal(named.textContent, 'claude-code · r1');
  assert.match(named.title, /^Revision r1 by claude-code\. /);
  assert.doesNotMatch(named.title, /unspecified model/);
  unnamed.app.destroy();
});

test('authored readers see finding wording, no adapter chips and no duplicated message', async () => {
  const ctx = await mount();
  ctx.app.focusIssue('loss-risk');
  assert.match(ctx.app.liveEl.textContent, /^Finding loss-risk, medium severity: Loss is aggregated late$/);
  const list = ctx.root.querySelector('.mlv-issues[role="listbox"]');
  assert.equal(list.getAttribute('aria-label'), 'medium severity findings');
  const row = ctx.root.querySelector('.mlv-issue[data-issue-id="loss-risk"]');
  assert.equal((row.textContent.match(/The update uses a delayed aggregate\./g) || []).length <= 1, true, 'the message is printed once');
  assert.equal(row.querySelector('.mlv-insp__why'), null);
  ctx.app.focusNode('dataset');
  const meta = Array.from(ctx.root.querySelectorAll('.mlv-rail__panel:not([hidden]) .mlv-insp__meta .mlv-chip'), (chip) => chip.textContent);
  assert.equal(meta.includes('unknown'), false, 'no kind chip when the author gave no kind');
  assert.equal(meta.includes('unit') || meta.includes('op'), false, 'no level chip');
  ctx.app.focusNode('step');
  const headings = Array.from(ctx.root.querySelectorAll('.mlv-rail__panel:not([hidden]) h4, .mlv-rail__panel:not([hidden]) h5'), (h) => h.textContent);
  assert.ok(headings.includes('Findings'));
  assert.equal(headings.includes('Issues'), false);
  const badge = ctx.root.querySelector('[data-node-id="step"] [aria-label*="highest severity"]');
  assert.ok(badge);
  // Viewer M2: the badge names its finding by short label (F1…Fn, document order), not a bare count.
  assert.match(badge.getAttribute('aria-label'), /^Finding F\d+, highest severity medium$/);
  ctx.app.setFilters({ severities: ['high'] });
  assert.match(ctx.root.querySelector('.mlv-rail').textContent, /No findings match these filters\./);
  ctx.app.destroy();
});

test('a finding draws connectors only to the nodes its author named', async () => {
  const doc = workflow({
    nodes: [
      { id: 'A', label: 'Whole script', phase: 'load', basis: 'observed', evidence: ['wide'] },
      { id: 'B', label: 'Inner step', phase: 'loop', basis: 'observed', evidence: ['narrow'] },
      { id: 'C', label: 'Other step', phase: 'loop', basis: 'observed', evidence: ['narrow'] },
    ],
    edges: [],
    evidence: [
      { id: 'wide', file: 'train.py', line: 1, endLine: 80, quote: 'x' },
      { id: 'narrow', file: 'train.py', line: 12, endLine: 12, quote: 'y' },
    ],
    findings: [
      { id: 'only-b', title: 'Only B', message: 'm', severity: 'high', nodeIds: ['B'], basis: 'inferred', evidence: ['narrow'], counterEvidence: ['wide'] },
      { id: 'b-and-c', title: 'B and C', message: 'm', severity: 'high', nodeIds: ['B', 'C'], basis: 'inferred', evidence: ['narrow'] },
    ],
  });
  const ctx = await mount(doc);
  ctx.app.focusIssue('only-b');
  const layer = ctx.app.view.connectorLayer;
  assert.equal(layer.childElementCount, 0, 'no connector to node A, which the finding never named');
  ctx.app.focusIssue('b-and-c');
  assert.equal(layer.childElementCount, 1);
  assert.match(layer.textContent, /Also affects — Other step/);
  ctx.app.destroy();
});

test('authored details are never read as resolved configuration values', async () => {
  const doc = workflow({
    nodes: [
      { id: 'pick', label: 'Pick checkpoint', detail: 'selects the best checkpoint by validation loss', phase: 'load', basis: 'observed', evidence: ['ev-load'] },
      { id: 'reg', label: 'Registry', detail: 'one of 3 in registry · a, b, c', phase: 'loop', basis: 'observed', evidence: ['ev-step'] },
    ],
    edges: [], findings: [],
  });
  const ctx = await mount(doc);
  for (const id of ['pick', 'reg']) {
    const card = ctx.root.querySelector(`[data-node-id="${id}"]`);
    assert.doesNotMatch(card.getAttribute('aria-label'), /resolved value|resolves to one of/);
    assert.equal(card.hasAttribute('data-config-value'), false);
    assert.equal(card.classList.contains('is-alternatives'), false);
  }
  ctx.app.focusNode('pick');
  assert.doesNotMatch(ctx.root.querySelector('.mlv-rail__panel:not([hidden])').textContent, /Resolved value/i);
  ctx.app.destroy();
});

test('card DOM ids are injective, so aria-activedescendant names the selected card', async () => {
  const doc = workflow({
    phases: [{ id: 'load', label: 'Load' }],
    nodes: ['load.data', 'load:data', 'load_data'].map((id) => ({ id, label: id, phase: 'load', basis: 'observed', evidence: ['ev-load'] })),
    edges: [], findings: [],
  });
  const ctx = await mount(doc);
  const ids = ['load.data', 'load:data', 'load_data'].map((id) => ctx.root.querySelector(`[data-node-id="${id}"]`).id);
  assert.equal(new Set(ids).size, 3, JSON.stringify(ids));
  ctx.app.focusNode('load_data');
  const canvas = ctx.root.querySelector('.mlv-canvas');
  const active = ctx.document.getElementById(canvas.getAttribute('aria-activedescendant'));
  assert.equal(active.getAttribute('data-node-id'), 'load_data');
  ctx.app.destroy();
});

test('exports keep a title containing a slash whole, and stay well-formed XML with U+FFFF', async () => {
  const exportOf = async (title) => {
    const ctx = await mount(workflow({ title }));
    ctx.root.querySelector('.mlv-btn--more').click();
    ctx.root.querySelector('[data-export-action="svg"]').click();
    const frame = ctx.bridge.posted.findLast((m) => m.type === 'exportFile');
    const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
    const parsed = new ctx.window.DOMParser().parseFromString(svg, 'image/svg+xml');
    const error = parsed.getElementsByTagName('parsererror').length;
    ctx.app.destroy();
    return { svg, name: frame.name, error };
  };
  const slash = await exportOf('Train/eval loop');
  assert.match(slash.svg, /<title>MLView — Train\/eval loop — whole diagram<\/title>/);
  assert.equal(slash.name, 'mlview-train-eval-loop-diagram.svg');
  const odd = await exportOf('Loss ￿ spike \ud83d end');
  assert.equal(odd.error, 0, 'the export parses as XML');
  assert.match(odd.svg, /Loss � spike � end/);
});

// ---- Review round 1 ----

test('search rows name an authored notebook cell like the card does, title first (WEBVIEW1-3)', async () => {
  const ctx = await mount(workflow({
    evidence: [
      { id: 'ev-load', file: 'nb/explore.ipynb', cell: 7, line: 3, endLine: 3, quote: 'df = load()' },
      { id: 'ev-step', file: 'src/train.py', line: 42, endLine: 47, quote: 'optimizer.step()' },
      { id: 'ev-loss', file: 'src/train.py', line: 35, endLine: 36, quote: 'loss.mean()' },
    ],
  }));
  // Viewer M2 removed the scope picker; the search rows are where a step's location is listed.
  const input = ctx.root.querySelector('.mlv-search .mlv-input');
  input.value = 'Read records';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const row = Array.from(ctx.root.querySelectorAll('.mlv-search__results .mlv-result')).find((r) => /Read records/.test(r.textContent));
  assert.ok(row);
  const parts = Array.from(row.children, (child) => child.className.baseVal === undefined ? child.className : child.className.baseVal);
  assert.ok(parts.indexOf('mlv-result__label') < parts.indexOf('mlv-result__meta'), 'the title comes before the location: ' + parts.join(','));
  assert.match(row.querySelector('.mlv-result__meta').textContent, /nb\/explore\.ipynb › cell 7, line 3/);
  assert.doesNotMatch(row.textContent, /explore\.ipynb:3/);
  assert.match(ctx.root.querySelector('[data-node-id="dataset"]').textContent, /nb\/explore\.ipynb › cell 7, line 3/);
  ctx.app.destroy();
});

test('focus mode stays lit after a deselect and a new revision, and follows a collapsed group (WEBVIEW1-4)', async () => {
  const lit = (ctx) => Array.from(ctx.root.querySelectorAll('.mlv-node.is-lit'), (n) => n.getAttribute('data-node-id')).sort();
  const focusing = (ctx) => ctx.root.querySelector('.mlv-canvas').classList.contains('is-focusing');
  const ctx = await mount();
  ctx.app.select({ kind: 'node', id: 'dataset' });
  ctx.app.view.toggleFocusMode(ctx.app.selection);
  assert.equal(focusing(ctx), true);
  const before = lit(ctx);
  assert.ok(before.includes('dataset'));
  ctx.app.clearSelection();
  assert.deepEqual(lit(ctx), before);
  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow() });
  assert.deepEqual(lit(ctx), before, 'a same-revision re-post re-lights focus');
  ctx.bridge.send({ v: 1, type: 'workflow', document: workflow({ revision: { id: 'r2', parent: 'r1' } }) });
  assert.equal(focusing(ctx), true);
  assert.deepEqual(lit(ctx), before, 'a new revision re-lights focus');
  ctx.app.setFilters({ severities: ['high'] });
  assert.ok(!focusing(ctx) || lit(ctx).length > 0, 'a filter never leaves every card dimmed');
  ctx.app.destroy();

  const nested = await mount();
  nested.app.select({ kind: 'node', id: 'step' });
  nested.app.view.toggleFocusMode(nested.app.selection);
  nested.app.view.toggleCollapse('epoch');
  assert.equal(focusing(nested), true);
  assert.ok(lit(nested).includes('epoch'), 'the collapsed group carries the focused lineage: ' + lit(nested).join(','));
  nested.app.view.toggleCollapse('epoch');
  assert.ok(lit(nested).includes('step'), 'expanding lights the focused node again');
  nested.app.destroy();

  const gone = await mount();
  gone.app.select({ kind: 'node', id: 'dataset' });
  gone.app.view.toggleFocusMode(gone.app.selection);
  const reduced = workflow({ revision: { id: 'r3' } });
  reduced.nodes = reduced.nodes.filter((n) => n.id !== 'dataset');
  reduced.edges = [];
  gone.bridge.send({ v: 1, type: 'workflow', document: reduced });
  assert.equal(focusing(gone), false, 'focus unlocks when its node is gone');
  assert.equal(gone.app.view.isFocusLocked, false);
  gone.app.destroy();
});

test('card names speak "step" and "finding" for authored nodes (WEBVIEW1-5)', async () => {
  const ctx = await mount();
  const label = (id) => {
    const card = ctx.root.querySelector(`[data-node-id="${id}"]`);
    return (card.querySelector('.mlv-group__header') || card).getAttribute('aria-label');
  };
  assert.match(label('step'), /^step Update weights, /);
  assert.match(label('step'), /, 1 finding, highest severity medium\.$/);
  assert.match(label('dataset'), /^step Read records, /);
  assert.doesNotMatch(label('step'), /unknown|issue/);
  assert.match(label('epoch'), /^step Epoch, /);
  assert.doesNotMatch(label('epoch'), /unknown|issue|^node /);
  ctx.app.destroy();
});
