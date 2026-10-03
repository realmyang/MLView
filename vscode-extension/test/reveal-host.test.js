'use strict';
/**
 * Viewer M3 (roadmap step 14): MLView: Reveal in Diagram, the host side. The citation index built
 * from the validated document (claims by cited file and range), the `mlview.citedFiles` context key
 * (the open panels' cited files that are unchanged since publishing) and the manifest's `when`
 * clause evaluated against it for the editor under the pointer, the index following each
 * revalidation, the claim and diagram QuickPicks, the `reveal {kind, id}` frame and the one explicit
 * focus move, notebook cell editors, and everything going with the last panel. Mock `vscode` only:
 * none of this is a live check (the clause is evaluated here by a small stand-in for VS Code's).
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
const KEY = 'mlview.citedFiles';
const key = () => vscode.__recorded.contexts.get(KEY);
const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
/**
 * A stand-in for VS Code's when-clause evaluation, for the clause shapes the manifest uses: terms
 * joined by `&&`, each `key =~ /re/`, `key in listKey` or a bare key (truthy). VS Code's renderer
 * evaluates the clause against the context of the editor under the pointer, with the context keys
 * as they are at that moment: no extension code runs in between.
 */
function evaluateWhen(clause, context) {
  return clause.split('&&').map((term) => term.trim()).every((term) => {
    let m = /^([\w.]+) =~ \/(.*)\/$/.exec(term);
    if (m) return new RegExp(m[2]).test(String(context[m[1]] ?? ''));
    m = /^([\w.]+) in ([\w.]+)$/.exec(term);
    if (m) {
      const list = context[m[2]];
      return Array.isArray(list) ? list.includes(context[m[1]]) : !!list && typeof list === 'object' && Object.prototype.hasOwnProperty.call(list, context[m[1]]);
    }
    if (/^[\w.]+$/.test(term)) return !!context[term];
    throw new Error('clause term not understood: ' + term);
  });
}
/**
 * Whether the editor context menu offers Reveal in Diagram on a right-click in an editor of `fsPath`
 * (a text file, or with `cell` a notebook cell), with the keys as they are now and whatever editor
 * VS Code calls active (the diagram may have the focus: no active text editor at all).
 */
function offered(fsPath, { cell = false } = {}) {
  const item = MANIFEST.contributes.menus['editor/context'].find((x) => x.command === 'mlview.revealInDiagram');
  // VS Code's `resourcePath`: the fsPath of a file URI, the path of any other URI (a notebook cell's
  // `vscode-notebook-cell` URI has the notebook's path).
  const context = cell
    ? { resourceScheme: 'vscode-notebook-cell', resourcePath: vscode.Uri.file(fsPath).path }
    : { resourceScheme: 'file', resourcePath: vscode.Uri.file(fsPath).fsPath };
  for (const [name, value] of vscode.__recorded.contexts) context[name] = value;
  return evaluateWhen(item.when, context);
}
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

test('M3 review F1: the menu item is offered on a cited, unchanged file while a panel is open, even when the diagram has the focus (no active text editor)', async () => {
  const fixture = await openCited();
  const file = (rel) => path.join(fixture.root, rel);
  // The reader pressed Enter on a card: the editor beside shows source.py, and the focus is still in
  // the diagram, so VS Code reports no active text editor. The right-click comes next, at once.
  vscode.__setActiveEditor(undefined);
  await settle();
  assert.equal(offered(file('source.py')), true, 'source.py is cited: offered on the first right-click');
  assert.equal(offered(file('other.py')), true, 'other.py is cited');
  assert.equal(offered(file('plain.py')), false, 'plain.py is not cited');
  assert.equal(offered(path.join(fixture.root, '..', 'elsewhere.py')), false);
  assert.ok(Array.isArray(key()), 'the key is a list');
  // The active editor plays no part: the list is the same whichever editor is active.
  const before = JSON.stringify(key());
  cursor(fixture, 'plain.py', 0);
  await settle();
  assert.equal(JSON.stringify(key()), before);
  assert.equal(offered(file('source.py')), true, 'coming from an uncited editor too');
  // Only the cited files of the displayed revision, absolute, in every spelling VS Code may use.
  assert.deepEqual([...new Set(key())].sort(), [...new Set([file('other.py'), file('source.py')].flatMap(api.citedPathForms))].sort());
});

test('cited path forms: the path and its URI path; either case of a Windows drive letter', () => {
  assert.deepEqual(api.citedPathForms('/repo/train.py'), ['/repo/train.py']);
  const windows = api.citedPathForms('c:\\repo\\nb.ipynb');
  for (const form of ['c:\\repo\\nb.ipynb', 'C:\\repo\\nb.ipynb']) assert.ok(windows.includes(form), form);
});

test('the item goes when the cited file goes stale and comes back when it is restored', async () => {
  const fixture = await openCited();
  const file = path.join(fixture.root, 'source.py');
  cursor(fixture, 'source.py', 1);
  await settle();
  assert.equal(offered(file), true);
  fs.writeFileSync(file, SOURCE + '# edited\n');
  await h.diskEvent(fixture.panel, 'change', file);
  await settle();
  assert.equal(offered(file), false, 'changed since publishing');
  assert.equal(offered(path.join(fixture.root, 'other.py')), true, 'the other cited file is still offered');
  // The command (from a keybinding the reader made, say) says why, plainly, and reveals nothing.
  await runReveal();
  assert.equal(reveals(fixture.panel).length, 0);
  assert.match(infos().at(-1), /^MLView: source\.py changed after revision r1 was published, so its lines no longer match the diagram\./);
  fs.writeFileSync(file, SOURCE);
  await h.diskEvent(fixture.panel, 'change', file);
  await settle();
  assert.equal(offered(file), true, 'restored');
});

test('unsaved edits that move the cited lines: the item stays (the list cannot see the buffer) and the command explains in one line', async () => {
  const fixture = await openCited();
  const file = path.join(fixture.root, 'source.py');
  cursor(fixture, 'source.py', 1);
  await settle();
  const type = async (text, dirty) => {
    vscode.__setDocument(file, text);
    vscode.__setDirty(file, dirty);
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(file));
    vscode.window.activeTextEditor.document = document;
    for (const listener of [...vscode.__recorded.changeListeners]) listener({ document, contentChanges: [] });
  };
  // Two lines added at the top: no quote is at its cited lines any more.
  await type('# a\n# b\n' + SOURCE, true);
  await settle();
  assert.equal(offered(file), true);
  await runReveal();
  assert.match(infos().at(-1), /^MLView: the unsaved text of source\.py no longer has the quoted lines where the diagram cites them/);
  assert.equal(reveals(fixture.panel).length, 0);
  // Undone: the command reveals again (three claims cite line 2: the reader picks the first).
  await type(SOURCE, false);
  vscode.__answerQuickPick(0);
  await runReveal();
  assert.equal(reveals(fixture.panel).length, 1);
});

test('the index and the list follow a new revision', async () => {
  const fixture = await openCited();
  const plainFile = path.join(fixture.root, 'plain.py');
  const otherFile = path.join(fixture.root, 'other.py');
  cursor(fixture, 'plain.py', 0);
  await settle();
  assert.equal(offered(plainFile), false);
  // Revision r2 cites plain.py instead of other.py.
  const { document, files } = citedDoc({ id: 'r2', parent: 'r1' });
  document.evidence[2] = { id: 'e3', file: 'plain.py', line: 1, endLine: 1, quote: 'pass' };
  document.coverage.inspectedFiles = ['source.py', 'plain.py'];
  h.writeJson(fixture.artifact, h.verify(document, files));
  await h.diskEvent(fixture.panel, 'change', fixture.artifact);
  assert.equal(h.shownRevision(fixture.panel), 'r2');
  await settle();
  assert.equal(offered(plainFile), true, 'plain.py is cited by r2');
  await runReveal();
  assert.deepEqual(plain(reveals(fixture.panel).at(-1)), { v: 1, type: 'reveal', kind: 'node', id: 'n' });
  assert.equal(offered(otherFile), false, 'other.py is no longer cited');
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
  assert.equal(offered(path.join(fixture.root, 'copy/source.py')), false, 'the diagram is validated against the workspace root, where the file is missing');
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

test('notebook cell editors: a cited notebook offers the item in its cells and reveals the claim; another cell offers the nearest; the raw file as text says how', async () => {
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
  assert.equal(offered(nb, { cell: true }), true, 'in a cell editor of the cited notebook');
  assert.equal(offered(nb), true, 'and with the notebook editor\'s own resource');
  vscode.__answerQuickPick(0);
  await runReveal();
  assert.deepEqual(picks()[0].items.map((i) => i.label), ['Step: Fit', 'Connection: Fit → Weights', 'F1 Finding: Unverified output']);
  assert.match(picks()[0].options.placeHolder, /^3 claims cite cell 1, line 2 of notes\.ipynb/);
  assert.deepEqual(plain(reveals(fixture.panel)), [{ v: 1, type: 'reveal', kind: 'node', id: 'n' }]);
  // Another cell of the same notebook: the file is cited, so the item is offered; the nearest are offered.
  vscode.__setActiveEditor({ cellOf: nb, cell: 0, viewColumn: 1 });
  await settle();
  await runReveal();
  assert.equal(picks()[1].options.title, 'Reveal in Diagram: no claim cites cell 0, line 1 of notes.ipynb');
  assert.deepEqual(picks()[1].items.map((i) => i.detail), ['Cited at cell 1, lines 2–3, 1 cell below', 'Cited at cell 1, lines 2–3, 1 cell below', 'Cited at cell 1, lines 2–3, 1 cell below']);
  // The notebook opened as raw JSON text: the item is offered (the list cannot tell the editor's
  // form), and the command says the diagram cites it by cell.
  cursor(fixture, 'notes.ipynb', 0);
  await settle();
  await runReveal();
  assert.equal(infos().at(-1), 'MLView: the diagram cites notes.ipynb by notebook cell. Open it in the notebook editor and use Reveal in Diagram in a cell.');
});

test('the list follows the panels alone: no editor listener, one setContext per change, a panel that throws is skipped', () => {
  const counts = () => [vscode.__recorded.activeEditorListeners.length, vscode.__recorded.changeListeners.length, vscode.__recorded.notebookChangeListeners.length];
  const before = counts();
  const warnings = [];
  const log = { info() {}, warn: (m) => warnings.push(m), error() {}, debug() {} };
  let files = ['/repo/a.py'];
  const panels = [{ citedFiles: () => files }, { citedFiles: () => { throw new Error('gone'); } }];
  const service = new api.RevealInDiagram(() => panels, log);
  vscode.__recorded.contexts.delete(KEY);
  service.panelsChanged();
  assert.deepEqual(key(), ['/repo/a.py']);
  assert.deepEqual(counts(), before, 'no editor listener');
  assert.equal(warnings.length, 1, 'the panel that threw is logged and skipped');
  vscode.__recorded.contexts.delete(KEY);
  service.citationsChanged();
  assert.equal(key(), undefined, 'an unchanged list is not sent again');
  files = ['/repo/a.py', '/repo/b.py'];
  service.citationsChanged();
  assert.deepEqual(key(), ['/repo/a.py', '/repo/b.py']);
  service.dispose();
  assert.deepEqual(key(), []);
});

test('everything goes with the last panel: the list empties; the command stays registered', async () => {
  const fixture = await openCited();
  const { controller, root } = fixture;
  const service = controller.revealer;
  const second = path.join(root, 'second.mlview.json');
  h.writeJson(second, citedDoc().document);
  await controller.open(vscode.Uri.file(second));
  const panel2 = vscode.__recorded.panels.at(-1);
  panel2.fire({ v: 1, type: 'ready' });
  await h.tick();
  await settle();
  const sourceFile = path.join(root, 'source.py');
  assert.equal(offered(sourceFile), true);
  fixture.panel.dispose();
  await settle();
  assert.equal(offered(sourceFile), true, 'the second diagram cites the file too');
  panel2.dispose();
  await settle();
  assert.deepEqual(key(), [], 'emptied with the last panel');
  assert.deepEqual(service.citedPaths, []);
  assert.equal(offered(sourceFile), false);
  // The list does not depend on the editor: an editor change after the last panel changes nothing.
  cursor(fixture, 'other.py', 0);
  await settle();
  assert.deepEqual(key(), []);
  assert.ok(vscode.__recorded.commands.has('mlview.revealInDiagram'), 'a contributed command stays registered');
  controller.dispose();
  assert.equal(vscode.__recorded.commands.has('mlview.revealInDiagram'), false, 'until the extension is disposed');
});

test('controller dispose with panels open empties the list and removes the command', async () => {
  const fixture = await openCited();
  await settle();
  assert.equal(offered(path.join(fixture.root, 'source.py')), true);
  fixture.controller.dispose();
  await settle();
  assert.deepEqual(key(), []);
  assert.equal(vscode.__recorded.commands.has('mlview.revealInDiagram'), false);
});
