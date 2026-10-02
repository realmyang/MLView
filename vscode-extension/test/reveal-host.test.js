'use strict';
/**
 * Viewer M3 (roadmap step 14): MLView: Reveal in Diagram, the host side. The citation index built
 * from the validated document (claims by cited file and range), the `mlview.citedFile` context key
 * (on only while a panel is open and the active editor's file is cited, unchanged, and still has the
 * quotes at the cited lines), the index following each revalidation, the claim and diagram
 * QuickPicks, the `reveal {kind, id}` frame and the one explicit focus move, notebook cell editors,
 * and everything going with the last panel. Mock `vscode` only: none of this is a live check.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;

const fixtures = [];
test.afterEach(() => h.cleanup(fixtures));
async function open(options) {
  const fixture = await h.openPanel(options);
  fixtures.push(fixture);
  return fixture;
}
const KEY = 'mlview.citedFile';
const key = () => vscode.__recorded.contexts.get(KEY);
const reveals = (panel) => panel.posted.filter((m) => m.type === 'reveal');
const infos = () => vscode.__recorded.messages.filter((m) => m[0] === 'info').map((m) => m[1]);
const picks = () => vscode.__recorded.quickPicks;
const plain = (value) => JSON.parse(JSON.stringify(value));
/** Run MLView: Reveal in Diagram as the context menu does. */
const runReveal = () => vscode.__recorded.commands.get('mlview.revealInDiagram')();
/** Wait until every pending context-key computation has settled. */
const settle = async () => { for (let i = 0; i < 5; i++) await h.tick(); };

const SOURCE = 'import x\ntrain()\nsave()\n\n\nlog()\n';
/**
 * source.py: lines 2-3 cited by the step Fit, the connection Fit -> Weights and (as counter-evidence)
 * the finding F1; line 6 by the step Log and F1. other.py line 1 by Fit.
 */
function citedDoc(revision = { id: 'r1' }) {
  const document = h.workflow('source.py', revision);
  document.evidence = [
    { id: 'e', file: 'source.py', line: 2, endLine: 3, quote: 'train()\nsave()' },
    { id: 'e2', file: 'source.py', line: 6, endLine: 6, quote: 'log()' },
    { id: 'e3', file: 'other.py', line: 1, endLine: 1, quote: 'other()' }
  ];
  document.nodes[0].evidence = ['e', 'e3'];
  document.nodes.push({ id: 'log', label: 'Log', phase: 'p', basis: 'observed', evidence: ['e2'] });
  document.edges[0].evidence = ['e'];
  document.findings[0].evidence = ['e2'];
  document.findings[0].counterEvidence = ['e'];
  document.coverage.inspectedFiles = ['source.py', 'other.py'];
  const files = { 'source.py': SOURCE, 'other.py': 'other()\n', 'plain.py': 'pass\n' };
  return { document: h.verify(document, files), files };
}
async function openCited(extra = {}) {
  const { document, files } = citedDoc();
  return open({ raw: document, files, ...extra });
}
/** Put the cursor (zero-based line) or a selection in `rel` of the fixture's root. */
function cursor(fixture, rel, line, endLine = line, endChar = 0) {
  return vscode.__setActiveEditor({ path: path.join(fixture.root, rel), viewColumn: 1, selection: [line, 0, endLine, endChar] });
}

/* ── the index ───────────────────────────────────────────────────────── */

test('the citation index finds the claims whose cited lines include the cursor or overlap the selection: steps, connections, findings', () => {
  const { document } = citedDoc();
  const index = api.CitationIndex.from(document);
  assert.deepEqual(index.files().sort(), ['other.py', 'source.py']);
  const ranges = index.ranges('source.py');
  const at = (start, end) => api.claimsAt(ranges, undefined, start, end).map((m) => `${m.claim.kind}:${m.claim.id}${m.counter ? ' (counter)' : ''}`);
  assert.deepEqual(at(2, 2), ['node:n', 'edge:flow', 'issue:risk (counter)']);
  assert.deepEqual(at(3, 3), ['node:n', 'edge:flow', 'issue:risk (counter)']);
  assert.deepEqual(at(1, 1), []);
  assert.deepEqual(at(4, 5), []);
  assert.deepEqual(at(6, 6), ['node:log', 'issue:risk']);
  // A selection overlapping both ranges: each claim once, a supporting citation before a counter one.
  assert.deepEqual(at(3, 6), ['node:n', 'node:log', 'edge:flow', 'issue:risk']);
  // A notebook cell's ranges match only in that cell.
  const notebook = api.CitationIndex.from({ ...document, evidence: [{ id: 'e', file: 'nb.ipynb', cell: 2, line: 1, endLine: 2, quote: 'q' }, { id: 'e2', file: 'nb.ipynb', cell: 5, line: 1, endLine: 1, quote: 'r' }, { id: 'e3', file: 'other.py', line: 1, endLine: 1, quote: 'other()' }] });
  const cells = notebook.ranges('nb.ipynb');
  assert.deepEqual(api.claimsAt(cells, 2, 1, 1).map((m) => m.claim.id), ['n', 'flow', 'risk']);
  assert.deepEqual(api.claimsAt(cells, 5, 1, 1).map((m) => m.claim.id), ['log', 'risk']);
  assert.deepEqual(api.claimsAt(cells, 3, 1, 1), []);
  assert.deepEqual(api.claimsAt(cells, undefined, 1, 1), [], 'a plain file never matches a cell');
});

test('the nearest claims: the same cell first, then the fewest lines away, each claim once from its nearest range', () => {
  const { document } = citedDoc();
  const index = api.CitationIndex.from(document);
  const near = api.nearestClaims(index.ranges('source.py'), undefined, 4, 4, 30);
  assert.deepEqual(near.map((m) => [m.claim.id, m.lines, m.above]), [['n', 1, true], ['flow', 1, true], ['risk', 1, true], ['log', 2, false]]);
  assert.equal(api.nearestClaims(index.ranges('source.py'), undefined, 4, 4, 2).length, 2, 'at most the limit');
  const notebook = api.CitationIndex.from({ ...document, evidence: [{ id: 'e', file: 'nb.ipynb', cell: 1, line: 3, endLine: 4, quote: 'q' }, { id: 'e2', file: 'nb.ipynb', cell: 6, line: 1, endLine: 1, quote: 'r' }, { id: 'e3', file: 'nb.ipynb', cell: 4, line: 9, endLine: 9, quote: 's' }] });
  const cells = notebook.ranges('nb.ipynb');
  assert.deepEqual(api.nearestClaims(cells, 4, 1, 1, 30).map((m) => [m.claim.id, m.cells, m.lines]), [['n', 0, 8], ['log', 2, 0], ['risk', 2, 0], ['flow', 3, 0]]);
});

test('claims carry their kind, title, F label, phases and basis; QuickPick text is bounded and cannot draw icons', () => {
  const { document } = citedDoc();
  document.phases.push({ id: 'q', label: 'Evaluate' });
  document.nodes.push({ id: 'ev', label: 'Score', phase: 'q', basis: 'observed', evidence: ['e3'] });
  document.edges.push({ id: 'to-ev', source: 'ev', target: 'n', label: 'scores', basis: 'observed', evidence: ['e3'] });
  document.findings.push({ id: 'second', title: 'Bad $(alert) title\nwith a newline', message: 'm', severity: 'low', nodeIds: [], edgeIds: ['to-ev'], basis: 'observed', evidence: ['e3'], counterEvidence: [] });
  const index = api.CitationIndex.from(document);
  const risk = index.claim({ kind: 'issue', id: 'risk' });
  assert.deepEqual({ label: risk.label, severity: risk.severity, phases: risk.phases, basis: risk.basis }, { label: 'F1', severity: 'medium', phases: ['Train'], basis: 'inferred' });
  const second = index.claim({ kind: 'issue', id: 'second' });
  assert.equal(second.label, 'F2', 'F labels by document order');
  assert.deepEqual(second.phases, ['Evaluate'], 'a finding touches the phase of a cited connection\'s source (PR #14)');
  const flow = index.claim({ kind: 'edge', id: 'flow' });
  assert.deepEqual(flow.ends, ['Fit', 'Weights']);
  const at = (rel, line) => api.claimsAt(index.ranges(rel), undefined, line, line);
  const [step, connection, finding] = at('source.py', 2).map((m) => api.claimPickText(m));
  assert.deepEqual(step, { label: 'Step: Fit', description: 'Train', detail: 'Cited at lines 2–3' });
  assert.deepEqual(connection, { label: 'Connection: Fit → Weights', description: '“produces” · Train · inferred', detail: 'Cited at lines 2–3' });
  assert.deepEqual(finding, { label: 'F1 Finding: Unverified output', description: 'medium · Train · inferred', detail: 'Counter-evidence at lines 2–3' });
  const bad = at('other.py', 1).find((m) => m.claim.id === 'second');
  assert.equal(api.claimPickText(bad).label, 'F2 Finding: Bad \\$(alert) title\\u000awith a newline');
  const near = api.nearestClaims(index.ranges('source.py'), undefined, 4, 4, 30).map((m) => api.claimPickText(m, true).detail);
  assert.deepEqual(near, ['Cited at lines 2–3, 1 line above', 'Cited at lines 2–3, 1 line above', 'Counter-evidence at lines 2–3, 1 line above', 'Cited at line 6, 2 lines below']);
  assert.equal(api.pickText('x'.repeat(500)).length, 121);
});

test('selection lines: the cursor\'s line; a selection; one that ends at the start of a line leaves that line out', () => {
  const sel = (l1, c1, l2, c2) => new vscode.Selection(new vscode.Position(l1, c1), new vscode.Position(l2, c2));
  assert.deepEqual(api.selectionLines(sel(4, 3, 4, 3)), { start: 5, end: 5 });
  assert.deepEqual(api.selectionLines(sel(1, 0, 3, 2)), { start: 2, end: 4 });
  assert.deepEqual(api.selectionLines(sel(1, 0, 3, 0)), { start: 2, end: 3 });
  assert.deepEqual(api.selectionLines(sel(2, 5, 2, 0)), { start: 3, end: 3 });
});

/* ── the context key ─────────────────────────────────────────────────── */

test('the context key is on only for a cited, unchanged file while a panel is open', async () => {
  const fixture = await openCited();
  await settle();
  assert.equal(key(), false, 'no active editor');
  cursor(fixture, 'source.py', 0);
  await settle();
  assert.equal(key(), true, 'source.py is cited');
  cursor(fixture, 'plain.py', 0);
  await settle();
  assert.equal(key(), false, 'plain.py is not cited');
  cursor(fixture, 'other.py', 0);
  await settle();
  assert.equal(key(), true, 'other.py is cited');
  // A webview (the panel itself) took the focus: no text editor.
  vscode.__setActiveEditor(undefined);
  await settle();
  assert.equal(key(), false);
});

test('the context key goes off when the cited file goes stale and comes back when it is restored', async () => {
  const fixture = await openCited();
  cursor(fixture, 'source.py', 1);
  await settle();
  assert.equal(key(), true);
  const file = path.join(fixture.root, 'source.py');
  fs.writeFileSync(file, SOURCE + '# edited\n');
  await h.diskEvent(fixture.panel, 'change', file);
  await settle();
  assert.equal(key(), false, 'changed since publishing');
  // The command says why, plainly, and reveals nothing.
  await runReveal();
  assert.equal(reveals(fixture.panel).length, 0);
  assert.match(infos().at(-1), /^MLView: source\.py changed after revision r1 was published, so its lines no longer match the diagram\./);
  fs.writeFileSync(file, SOURCE);
  await h.diskEvent(fixture.panel, 'change', file);
  await settle();
  assert.equal(key(), true, 'restored');
});

test('unsaved edits that move the cited lines turn the key off (throttled); undoing them turns it on', async () => {
  const fixture = await openCited();
  const file = path.join(fixture.root, 'source.py');
  cursor(fixture, 'source.py', 1);
  await settle();
  assert.equal(key(), true);
  const type = async (text, dirty) => {
    vscode.__setDocument(file, text);
    vscode.__setDirty(file, dirty);
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    vscode.window.activeTextEditor.document = document;
    for (const listener of [...vscode.__recorded.changeListeners]) listener({ document, contentChanges: [] });
  };
  // An edit that keeps every cited line where it was: still on.
  await type(SOURCE.replace('import x', 'import y'), true);
  await h.sleep(api.CITED_KEY_THROTTLE_MS + 60);
  await settle();
  assert.equal(key(), true, 'the quotes are still at the cited lines');
  // Two lines added at the top: no quote is at its cited lines any more.
  await type('# a\n# b\n' + SOURCE, true);
  assert.equal(key(), true, 'throttled: not at once');
  await h.sleep(api.CITED_KEY_THROTTLE_MS + 60);
  await settle();
  assert.equal(key(), false, 'the unsaved text moved the cited lines');
  await runReveal();
  assert.match(infos().at(-1), /^MLView: the unsaved text of source\.py no longer has the quoted lines where the diagram cites them/);
  assert.equal(reveals(fixture.panel).length, 0);
  await type(SOURCE, false);
  await h.sleep(api.CITED_KEY_THROTTLE_MS + 60);
  await settle();
  assert.equal(key(), true, 'undone');
});

test('the index and the key follow a new revision', async () => {
  const fixture = await openCited();
  cursor(fixture, 'plain.py', 0);
  await settle();
  assert.equal(key(), false);
  // Revision r2 cites plain.py instead of other.py.
  const { document, files } = citedDoc({ id: 'r2', parent: 'r1' });
  document.evidence[2] = { id: 'e3', file: 'plain.py', line: 1, endLine: 1, quote: 'pass' };
  document.coverage.inspectedFiles = ['source.py', 'plain.py'];
  h.writeJson(fixture.artifact, h.verify(document, files));
  await h.diskEvent(fixture.panel, 'change', fixture.artifact);
  assert.equal(h.shownRevision(fixture.panel), 'r2');
  await settle();
  assert.equal(key(), true, 'plain.py is cited by r2');
  await runReveal();
  assert.deepEqual(plain(reveals(fixture.panel).at(-1)), { v: 1, type: 'reveal', kind: 'node', id: 'n' });
  cursor(fixture, 'other.py', 0);
  await settle();
  assert.equal(key(), false, 'other.py is no longer cited');
});

/* ── the command ─────────────────────────────────────────────────────── */

test('one claim at the cursor is revealed at once: the reveal frame, and the focus moves to the panel', async () => {
  const fixture = await openCited();
  cursor(fixture, 'other.py', 0);
  await runReveal();
  assert.equal(picks().length, 0, 'no QuickPick for one claim');
  assert.deepEqual(plain(reveals(fixture.panel)), [{ v: 1, type: 'reveal', kind: 'node', id: 'n' }]);
  assert.deepEqual(fixture.panel.revealCalls.at(-1), { viewColumn: undefined, preserveFocus: false }, 'the one explicit focus move, in the panel\'s own group');
  assert.equal(vscode.__recorded.shownDocuments.length, 0, 'nothing is opened');
});

test('several claims at the cursor: a QuickPick lists them by kind, title, F label and phase; the chosen one is revealed', async () => {
  const fixture = await openCited();
  cursor(fixture, 'source.py', 2);
  vscode.__answerQuickPick(2);
  await runReveal();
  assert.equal(picks().length, 1);
  const { items, options } = picks()[0];
  assert.deepEqual(items.map((i) => i.label), ['Step: Fit', 'Connection: Fit → Weights', 'F1 Finding: Unverified output']);
  assert.deepEqual(items.map((i) => i.description), ['Train', '“produces” · Train · inferred', 'medium · Train · inferred']);
  assert.match(options.placeHolder, /^3 claims cite line 3 of source\.py/);
  assert.equal(options.matchOnDescription, true);
  assert.deepEqual(plain(reveals(fixture.panel)), [{ v: 1, type: 'reveal', kind: 'issue', id: 'risk' }]);
  // A selection over both ranges lists each claim once.
  cursor(fixture, 'source.py', 2, 5, 3);
  await runReveal();
  assert.deepEqual(picks()[1].items.map((i) => i.label), ['Step: Fit', 'Step: Log', 'Connection: Fit → Weights', 'F1 Finding: Unverified output']);
  assert.match(picks()[1].options.placeHolder, /^4 claims cite lines 3–6 of source\.py/);
  assert.equal(reveals(fixture.panel).length, 1, 'cancelled: nothing more is revealed');
});

test('no claim at the cursor: the nearest claims in the file are offered, nearest first', async () => {
  const fixture = await openCited();
  cursor(fixture, 'source.py', 3);
  vscode.__answerQuickPick(3);
  await runReveal();
  const { items, options } = picks()[0];
  assert.equal(options.title, 'Reveal in Diagram: no claim cites line 4 of source.py');
  assert.equal(options.placeHolder, 'The nearest claims in this file: choose one to show it in the diagram');
  assert.deepEqual(items.map((i) => [i.label, i.detail]), [
    ['Step: Fit', 'Cited at lines 2–3, 1 line above'],
    ['Connection: Fit → Weights', 'Cited at lines 2–3, 1 line above'],
    ['F1 Finding: Unverified output', 'Counter-evidence at lines 2–3, 1 line above'],
    ['Step: Log', 'Cited at line 6, 2 lines below']
  ]);
  assert.deepEqual(plain(reveals(fixture.panel)), [{ v: 1, type: 'reveal', kind: 'node', id: 'log' }]);
});

test('a file no open diagram cites, and no editor or no panel, are said plainly', async () => {
  const fixture = await openCited();
  cursor(fixture, 'plain.py', 0);
  await runReveal();
  assert.equal(infos().at(-1), 'MLView: no open diagram cites plain.py.');
  vscode.__setActiveEditor(undefined);
  await runReveal();
  assert.match(infos().at(-1), /^MLView: Reveal in Diagram works in the editor of a cited source file or notebook cell\./);
  fixture.panel.dispose();
  cursor(fixture, 'source.py', 1);
  await runReveal();
  assert.match(infos().at(-1), /^MLView: no diagram is open\./);
  assert.equal(picks().length, 0);
  assert.equal(reveals(fixture.panel).length, 0);
});

test('the parent-folder case: a cited file found only under the folder the notice names is explained, not revealed', async () => {
  const document = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  const fixture = await open({ raw: document, files: { 'copy/source.py': 'fit()\n' }, artifactName: 'copy/run.mlview.json' });
  assert.deepEqual(h.lastBanner(fixture.panel).codes, ['root-hint']);
  cursor(fixture, 'copy/source.py', 0);
  await settle();
  assert.equal(key(), false, 'the diagram is validated against the workspace root, where the file is missing');
  await runReveal();
  assert.equal(infos().at(-1), 'MLView: the diagram cites source.py from the workspace root, where it is missing; this copy in ./copy/ is unchanged. Add that folder to the workspace (the diagram\'s notice offers it), then try again.');
  assert.equal(reveals(fixture.panel).length, 0);
});

test('with several panels, the one whose artifact cites the file; when more than one does, the reader chooses', async () => {
  const fixture = await openCited();
  const { controller, root } = fixture;
  // A second diagram that cites only plain.py.
  const only = citedDoc().document;
  only.title = 'Second';
  only.evidence = [{ id: 'e', file: 'plain.py', line: 1, endLine: 1, quote: 'pass' }];
  only.nodes[0].evidence = ['e'];
  only.nodes.pop();
  only.edges[0].evidence = ['e'];
  only.findings[0].evidence = ['e'];
  only.findings[0].counterEvidence = [];
  only.coverage.inspectedFiles = ['plain.py'];
  const second = path.join(root, 'second.mlview.json');
  h.writeJson(second, h.verify(only, { 'plain.py': 'pass\n' }));
  await controller.open(vscode.Uri.file(second));
  const panel2 = vscode.__recorded.panels.at(-1);
  panel2.fire({ v: 1, type: 'ready' });
  await h.tick();
  // other.py: only the first diagram cites it, so it is used without asking.
  cursor(fixture, 'other.py', 0);
  await runReveal();
  assert.equal(picks().length, 0);
  assert.equal(reveals(fixture.panel).length, 1);
  assert.equal(reveals(panel2).length, 0);
  // A third diagram that also cites other.py: the reader chooses the diagram, then the claim.
  const third = path.join(root, 'third.mlview.json');
  const thirdDoc = citedDoc().document;
  thirdDoc.title = 'Third $(zap)';
  h.writeJson(third, thirdDoc);
  await controller.open(vscode.Uri.file(third));
  const panel3 = vscode.__recorded.panels.at(-1);
  panel3.fire({ v: 1, type: 'ready' });
  await h.tick();
  cursor(fixture, 'other.py', 0);
  vscode.__answerQuickPick(1);
  await runReveal();
  assert.equal(picks().length, 1);
  assert.deepEqual(picks()[0].items.map((i) => [i.label, i.description, i.detail]), [
    ['Authored', 'run.mlview.json', '1 claim cites line 1'],
    ['Third \\$(zap)', 'third.mlview.json', '1 claim cites line 1']
  ]);
  assert.match(picks()[0].options.placeHolder, /^2 open diagrams cite other\.py/);
  assert.equal(reveals(panel3).length, 1, 'revealed in the chosen diagram');
  assert.equal(reveals(fixture.panel).length, 1, 'not in the other');
  assert.deepEqual(panel3.revealCalls.at(-1), { viewColumn: undefined, preserveFocus: false });
});

test('a hidden or reloading page gets the reveal after its next ready, once, and only while it is recent', async () => {
  const fixture = await openCited();
  const { panel } = fixture;
  cursor(fixture, 'other.py', 0);
  await runReveal();
  assert.equal(reveals(panel).length, 1, 'posted at once to the page');
  // VS Code discarded the page (hidden) and loads it again: the new page gets the reveal after the document.
  panel.posted.length = 0;
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.deepEqual(panel.postedTypes().filter((t) => ['workflow', 'reveal'].includes(t)), ['workflow', 'reveal']);
  // Once: a later page load does not repeat it.
  panel.posted.length = 0;
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.equal(reveals(panel).length, 0);
  // Not recent any more: a page that loads after REVEAL_REPLAY_MS does not get it.
  await runReveal();
  const now = Date.now;
  try {
    Date.now = () => now() + api.REVEAL_REPLAY_MS + 1;
    panel.posted.length = 0;
    panel.fire({ v: 1, type: 'ready' });
    await h.tick();
    assert.equal(reveals(panel).length, 0);
  } finally {
    Date.now = now;
  }
});

test('a revision that changes while the reader chooses reveals nothing and says so', async () => {
  const fixture = await openCited();
  cursor(fixture, 'source.py', 1);
  // The QuickPick answers after a new revision was adopted.
  const original = vscode.window.showQuickPick;
  vscode.window.showQuickPick = async (items, options) => {
    const offered = await items;
    const { document, files } = citedDoc({ id: 'r2', parent: 'r1' });
    h.writeJson(fixture.artifact, h.verify(document, files));
    await h.diskEvent(fixture.panel, 'change', fixture.artifact);
    vscode.__recorded.quickPicks.push({ items: offered, options });
    return offered[0];
  };
  try {
    await runReveal();
  } finally {
    vscode.window.showQuickPick = original;
  }
  assert.equal(h.shownRevision(fixture.panel), 'r2');
  assert.equal(reveals(fixture.panel).length, 0);
  assert.equal(infos().at(-1), 'MLView: the diagram changed to another revision while you were choosing. Run Reveal in Diagram again.');
});

test('notebook cell editors: a cited cell turns the key on and reveals its claim; another cell offers the nearest; the raw file as text says how', async () => {
  const document = h.workflow('notes.ipynb');
  document.evidence = [{ id: 'e', file: 'notes.ipynb', cell: 1, line: 2, endLine: 3, quote: 'fit()\nsave()' }];
  document.edges[0].evidence = ['e'];
  document.findings[0].evidence = ['e'];
  document.coverage.inspectedFiles = ['notes.ipynb'];
  const notebookJson = JSON.stringify({ cells: [{ source: ['a()'] }, { source: ['x = 1\n', 'fit()\n', 'save()'] }], metadata: {}, nbformat: 4, nbformat_minor: 5 });
  const fixture = await open({ raw: document, files: { 'notes.ipynb': notebookJson } });
  const nb = path.join(fixture.root, 'notes.ipynb');
  vscode.__setNotebooks([{ path: nb, cells: [{ text: 'a()' }, { text: 'x = 1\nfit()\nsave()' }] }]);
  vscode.__setActiveEditor({ cellOf: nb, cell: 1, viewColumn: 1, selection: [1, 0, 1, 0] });
  await settle();
  assert.equal(key(), true, 'the cited cell');
  vscode.__answerQuickPick(0);
  await runReveal();
  assert.deepEqual(picks()[0].items.map((i) => i.label), ['Step: Fit', 'Connection: Fit → Weights', 'F1 Finding: Unverified output']);
  assert.match(picks()[0].options.placeHolder, /^3 claims cite cell 1, line 2 of notes\.ipynb/);
  assert.deepEqual(plain(reveals(fixture.panel)), [{ v: 1, type: 'reveal', kind: 'node', id: 'n' }]);
  // Another cell of the same notebook: the file is cited, so the key stays on; the nearest are offered.
  vscode.__setActiveEditor({ cellOf: nb, cell: 0, viewColumn: 1 });
  await settle();
  assert.equal(key(), true);
  await runReveal();
  assert.equal(picks()[1].options.title, 'Reveal in Diagram: no claim cites cell 0, line 1 of notes.ipynb');
  assert.deepEqual(picks()[1].items.map((i) => i.detail), ['Cited at cell 1, lines 2–3, 1 cell below', 'Cited at cell 1, lines 2–3, 1 cell below', 'Cited at cell 1, lines 2–3, 1 cell below']);
  // The notebook opened as raw JSON text: the diagram cites it by cell.
  cursor(fixture, 'notes.ipynb', 0);
  await settle();
  assert.equal(key(), false);
  await runReveal();
  assert.equal(infos().at(-1), 'MLView: the diagram cites notes.ipynb by notebook cell. Open it in the notebook editor and use Reveal in Diagram in a cell.');
});

test('everything goes with the last panel: the editor listeners, the key; the command stays registered', async () => {
  const fixture = await openCited();
  const { controller, root } = fixture;
  const service = controller.revealer;
  assert.equal(service.attached, true, 'listening while a panel is open');
  const second = path.join(root, 'second.mlview.json');
  h.writeJson(second, citedDoc().document);
  await controller.open(vscode.Uri.file(second));
  const panel2 = vscode.__recorded.panels.at(-1);
  panel2.fire({ v: 1, type: 'ready' });
  await h.tick();
  cursor(fixture, 'source.py', 1);
  await settle();
  assert.equal(key(), true);
  const listeners = { active: vscode.__recorded.activeEditorListeners.length, text: vscode.__recorded.changeListeners.length, notebook: vscode.__recorded.notebookChangeListeners.length };
  fixture.panel.dispose();
  await settle();
  assert.equal(service.attached, true, 'one panel is still open');
  assert.equal(key(), true, 'the second diagram cites the file too');
  panel2.dispose();
  await settle();
  assert.equal(service.attached, false);
  assert.equal(key(), false, 'cleared with the last panel');
  // The service's three listeners, and each panel's own active-editor listeners, are gone.
  assert.equal(vscode.__recorded.changeListeners.length, listeners.text - 1);
  assert.equal(vscode.__recorded.notebookChangeListeners.length, listeners.notebook - 1);
  assert.ok(vscode.__recorded.activeEditorListeners.length <= listeners.active - 3);
  // An editor change after the last panel changes nothing.
  cursor(fixture, 'other.py', 0);
  await settle();
  assert.equal(key(), false);
  assert.ok(vscode.__recorded.commands.has('mlview.revealInDiagram'), 'a contributed command stays registered');
  controller.dispose();
  assert.equal(vscode.__recorded.commands.has('mlview.revealInDiagram'), false, 'until the extension is disposed');
});

test('controller dispose with panels open turns the key off and removes the command', async () => {
  const fixture = await openCited();
  cursor(fixture, 'source.py', 1);
  await settle();
  assert.equal(key(), true);
  fixture.controller.dispose();
  await settle();
  assert.equal(key(), false);
  assert.equal(fixture.controller.revealer.attached, false);
  assert.equal(vscode.__recorded.commands.has('mlview.revealInDiagram'), false);
});
