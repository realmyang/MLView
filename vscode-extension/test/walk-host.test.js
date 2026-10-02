'use strict';
/**
 * Viewer M3, the host side of the review walk (roadmap step 12): numbered opens (`seq`) whose
 * superseded requests are dropped, one `actionResult` per open with a `requestId`, blocked opens of
 * stale or missing files that never open them and raise no notification for the walk, the
 * whole-range highlight with its overview-ruler mark cleared at the walk's end and on dispose, and
 * the jump checks cached per revision and freshness version. Mock `vscode` only: none of this is a
 * live check.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
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
const shown = () => vscode.__recorded.shownDocuments;
const warnings = () => vscode.__recorded.messages.filter((m) => m[0] === 'warn').map((m) => m[1]);
const openResults = (panel) => h.results(panel).filter((m) => m.action === 'openLocation');
const range = (r) => [r.start.line, r.start.character, r.end.line, r.end.character];
const walkOpen = (panel, evidenceId, seq, extra = {}) => panel.fire({ v: 1, type: 'openLocation', evidenceId, walk: true, seq, requestId: `w${seq}`, ...extra });

/** Two evidence records in two files, lines 2-3 of source.py and line 1 of other.py, published with hashes. */
function twoFiles() {
  const document = h.workflow();
  document.evidence = [
    { id: 'e', file: 'source.py', line: 2, endLine: 3, quote: 'train()\nsave()' },
    { id: 'e2', file: 'other.py', line: 1, endLine: 1, quote: 'other()' }
  ];
  document.nodes[0].evidence = ['e', 'e2'];
  document.coverage.inspectedFiles = ['source.py', 'other.py'];
  const files = { 'source.py': 'import x\ntrain()\nsave()\n', 'other.py': 'other()\n' };
  return { document: h.verify(document, files), files };
}

function notebookDocument() {
  const document = h.workflow('notes.ipynb');
  document.evidence = [
    { id: 'e', file: 'notes.ipynb', cell: 1, line: 2, endLine: 3, quote: 'fit()\nsave()' },
    { id: 'e2', file: 'source.py', line: 1, endLine: 1, quote: 'fit()' }
  ];
  document.nodes[0].evidence = ['e', 'e2'];
  document.coverage.inspectedFiles = ['notes.ipynb', 'source.py'];
  const notebook = JSON.stringify({ cells: [{ source: ['a()'] }, { source: ['x = 1\n', 'fit()\n', 'save()'] }], metadata: {}, nbformat: 4, nbformat_minor: 5 });
  return { document, files: { 'notes.ipynb': notebook, 'source.py': 'fit()\n' } };
}
async function openNotebookPanel({ cellEditors = true } = {}) {
  const { document, files } = notebookDocument();
  const fixture = await open({ raw: document, files, ready: false });
  vscode.__setNotebooks([{ path: path.join(fixture.root, 'notes.ipynb'), cells: [{ text: 'a()' }, { text: 'x = 1\nfit()\nsave()' }] }]);
  vscode.__setNotebookCellEditors(cellEditors);
  fixture.panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  return fixture;
}

test('a walk open is answered done, keeps focus on the diagram and highlights the range with an overview-ruler mark', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered');
  assert.deepEqual(openResults(panel)[0], { v: 1, type: 'actionResult', requestId: 'w1', action: 'openLocation', outcome: 'done', seq: 1 });
  assert.equal(shown().length, 1);
  assert.equal(shown()[0].options.preserveFocus, true, 'preserveFocus stays the default');
  const [style] = vscode.__recorded.decorationTypes;
  assert.equal(style.options.overviewRulerColor.id, 'editorOverviewRuler.rangeHighlightForeground');
  assert.equal(style.options.overviewRulerLane, vscode.OverviewRulerLane.Full);
  assert.deepEqual(shown()[0].editor.decorations[0].ranges.map(range), [[1, 0, 2, 'save()'.length]]);
});

test('an open whose seq is not above the last one is dropped and answered cancelled', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  walkOpen(panel, 'e', 5);
  await h.waitFor(() => openResults(panel).length === 1, 'the first open was not answered');
  walkOpen(panel, 'e2', 3);
  walkOpen(panel, 'e2', 5);
  await h.waitFor(() => openResults(panel).length === 3, 'the late opens were not answered');
  assert.deepEqual(openResults(panel).map((r) => [r.seq, r.outcome]), [[5, 'done'], [3, 'cancelled'], [5, 'cancelled']]);
  assert.equal(shown().length, 1, 'neither late open touched an editor');
  assert.equal(path.basename(shown()[0].document.uri.fsPath), 'source.py');
  // A malformed seq is ignored, not trusted: the open is treated as unnumbered.
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e2', seq: 'x', requestId: 'm1' });
  await h.waitFor(() => openResults(panel).length === 4, 'the unnumbered open was not answered');
  assert.equal(openResults(panel)[3].outcome, 'done');
  assert.equal('seq' in openResults(panel)[3], false);
});

test('a burst of numbered opens navigates once, for the last, and answers every one', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  for (let seq = 1; seq <= 12; seq++) walkOpen(panel, seq % 2 ? 'e' : 'e2', seq);
  await h.waitFor(() => openResults(panel).length === 12, 'not every open was answered');
  const outcomes = openResults(panel).map((r) => [r.seq, r.outcome]).sort((a, b) => a[0] - b[0]);
  assert.deepEqual(outcomes, [...Array.from({ length: 11 }, (_, i) => [i + 1, 'cancelled']), [12, 'done']]);
  assert.equal(shown().length, 1, 'only the last open showed its source');
  assert.equal(path.basename(shown()[0].document.uri.fsPath), 'other.py');
  assert.equal(vscode.__recorded.decorationTypes.length, 1);
});

test('a later open supersedes a notebook open still waiting for its cell editor', async () => {
  const { panel } = await openNotebookPanel({ cellEditors: false });
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => vscode.__recorded.shownNotebooks.length === 1, 'the notebook open did not start');
  walkOpen(panel, 'e2', 2);
  await h.waitFor(() => openResults(panel).length === 2, 'both opens were not answered', 3000);
  assert.deepEqual(openResults(panel).map((r) => [r.seq, r.outcome]).sort((a, b) => a[0] - b[0]), [[1, 'cancelled'], [2, 'done']]);
  const [highlight] = vscode.__recorded.decorationTypes;
  assert.equal(highlight.disposed, false, 'the superseded notebook open left the later highlight alone');
});

test('a changed or missing file is blocked with its reason, never opened, and a walk open raises no notification', async () => {
  const { document, files } = twoFiles();
  const { panel, root } = await open({ raw: document, files: { 'source.py': files['source.py'] + '# edited\n' } });
  const before = warnings().length;
  walkOpen(panel, 'e', 1);
  walkOpen(panel, 'e2', 2, { requestId: 'w2' });
  await h.waitFor(() => openResults(panel).length === 2, 'the blocked opens were not answered');
  const [changed, missing] = openResults(panel).sort((a, b) => a.seq - b.seq);
  // The first is superseded by the second before its check ends; ask again on its own.
  assert.equal(changed.outcome, 'cancelled');
  assert.deepEqual(missing, { v: 1, type: 'actionResult', requestId: 'w2', action: 'openLocation', outcome: 'blocked', seq: 2, reason: 'missing', message: 'other.py is missing since revision r1 was published; not opened.' });
  walkOpen(panel, 'e', 3);
  await h.waitFor(() => openResults(panel).length === 3, 'the changed open was not answered');
  assert.deepEqual(openResults(panel)[2], { v: 1, type: 'actionResult', requestId: 'w3', action: 'openLocation', outcome: 'blocked', seq: 3, reason: 'changed', message: 'source.py changed after revision r1 was published; not opened.' });
  assert.equal(shown().length, 0, 'a stale file is never opened');
  assert.equal(vscode.__recorded.decorationTypes.length, 0);
  assert.equal(warnings().length, before, 'no notification for an open from the walk');
  assert.equal(fs.existsSync(path.join(root, 'other.py')), false);
});

test('an ordinary open of a stale file keeps its notification and, with a requestId, is answered blocked too', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files: { ...files, 'source.py': 'changed()\n' } });
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e', requestId: 'plain1' });
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered');
  assert.equal(openResults(panel)[0].outcome, 'blocked');
  assert.equal(openResults(panel)[0].reason, 'changed');
  assert.ok(warnings().includes('MLView: evidence e cites source.py, which changed after revision r1 was published; navigation to it is blocked.'));
  // Without a requestId nothing is answered (the M1 and M2 opens send none).
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e2' });
  await h.waitFor(() => shown().length === 1, 'the fresh file did not open');
  assert.equal(openResults(panel).length, 1);
});

test('a removed notebook cell and unknown evidence are answered blocked without a notification from the walk', async () => {
  const { panel, root } = await openNotebookPanel();
  vscode.__setNotebooks([{ path: path.join(root, 'notes.ipynb'), cells: [{ text: 'a()' }] }]);
  const before = warnings().length;
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered');
  assert.equal(openResults(panel)[0].outcome, 'blocked');
  assert.equal(openResults(panel)[0].reason, 'cell-missing');
  assert.equal(openResults(panel)[0].message, 'Cell 1 of notes.ipynb no longer exists; not opened.');
  walkOpen(panel, 'nope', 2);
  await h.waitFor(() => openResults(panel).length === 2, 'the unknown evidence was not answered');
  assert.equal(openResults(panel)[1].reason, 'unknown');
  assert.equal(warnings().length, before);
});

test('the walk end clears the highlight and drops a walk open still on its way; dispose clears it too', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => vscode.__recorded.decorationTypes.length === 1, 'the open did not highlight');
  panel.fire({ v: 1, type: 'walk', state: 'end' });
  assert.equal(vscode.__recorded.decorationTypes[0].disposed, true, 'the walk end cleared the highlight');
  // Any other state is ignored.
  walkOpen(panel, 'e2', 2);
  await h.waitFor(() => vscode.__recorded.decorationTypes.length === 2, 'the next open did not highlight');
  panel.fire({ v: 1, type: 'walk', state: 'paused' });
  assert.equal(vscode.__recorded.decorationTypes[1].disposed, false);
  panel.dispose();
  assert.equal(vscode.__recorded.decorationTypes[1].disposed, true, 'closing the panel cleared the highlight');
});

test('the walk end drops a notebook open waiting for its cell editor', async () => {
  const { panel } = await openNotebookPanel({ cellEditors: false });
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => vscode.__recorded.shownNotebooks.length === 1, 'the notebook open did not start');
  panel.fire({ v: 1, type: 'walk', state: 'end' });
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered', 3000);
  assert.equal(openResults(panel)[0].outcome, 'cancelled');
});

test('highlight: false selects and reveals the range without the decoration, and clears the previous one', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  walkOpen(panel, 'e', 1);
  await h.waitFor(() => vscode.__recorded.decorationTypes.length === 1, 'the open did not highlight');
  walkOpen(panel, 'e2', 2, { highlight: false });
  await h.waitFor(() => shown().length === 2, 'the second open did not show');
  assert.equal(vscode.__recorded.decorationTypes.length, 1, 'no new decoration');
  assert.equal(vscode.__recorded.decorationTypes[0].disposed, true, 'the previous highlight is gone');
  assert.deepEqual(range(shown()[1].editor.selection), [0, 0, 0, 'other()'.length]);
});

test('a new page numbers its opens from the start again', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  walkOpen(panel, 'e', 9);
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered');
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  walkOpen(panel, 'e2', 1);
  await h.waitFor(() => openResults(panel).length === 2, 'the open from the new page was not answered');
  assert.equal(openResults(panel)[1].outcome, 'done');
});

test('a new page drops a numbered open the old page started', async () => {
  const { panel } = await openNotebookPanel({ cellEditors: false });
  walkOpen(panel, 'e', 4);
  await h.waitFor(() => vscode.__recorded.shownNotebooks.length === 1, 'the notebook open did not start');
  // The webview was recreated (hidden and shown again, or reloaded) while the open waited.
  panel.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => openResults(panel).length === 1, 'the open was not answered', 3000);
  assert.equal(openResults(panel)[0].outcome, 'cancelled');
});

/** Count fs.promises.readFile calls for `file` while `run` runs (the bundle reads through live getters). */
async function countReads(file, run) {
  const original = fsp.readFile;
  let reads = 0;
  fsp.readFile = function (target, ...rest) {
    if (String(target) === file) reads++;
    return original.call(this, target, ...rest);
  };
  try {
    await run();
  } finally {
    fsp.readFile = original;
  }
  return reads;
}

test('jump checks are cached per freshness version: one read for a fresh file, one validation for a stale one', async () => {
  let validations = 0;
  const validator = async (...args) => { validations++; return api.validateWorkflow(...args); };
  const { document, files } = twoFiles();
  const { panel, root } = await open({ raw: document, files: { ...files, 'source.py': 'changed()\n' }, validator });
  assert.equal(validations, 1, 'one validation to display the revision');
  const other = path.join(root, 'other.py');
  let seq = 0;
  const reads = await countReads(other, async () => {
    for (let i = 1; i <= 4; i++) {
      walkOpen(panel, 'e2', ++seq);
      await h.waitFor(() => openResults(panel).length === seq, 'the fresh open was not answered');
    }
  });
  assert.equal(reads, 1, 'four opens of an unchanged file read it once');
  for (let i = 1; i <= 3; i++) {
    walkOpen(panel, 'e', ++seq);
    await h.waitFor(() => openResults(panel).length === seq, 'the stale open was not answered');
    assert.equal(openResults(panel).at(-1).reason, 'changed');
  }
  assert.equal(validations, 2, 'three opens of a stale file ran one full validation');
  // A watcher event starts a new freshness version: the next open checks again.
  await h.diskEvent(panel, 'change', path.join(root, 'source.py'));
  const afterEvent = validations;
  walkOpen(panel, 'e', ++seq);
  await h.waitFor(() => openResults(panel).length === seq, 'the open after the event was not answered');
  assert.equal(validations, afterEvent + 1, 'the cache did not outlive the freshness version');
  // A file rewritten with no watcher event has a new identity on disk: checked again, and blocked.
  fs.writeFileSync(other, 'other()\n# edited\n');
  walkOpen(panel, 'e2', ++seq);
  await h.waitFor(() => openResults(panel).length === seq, 'the open of the rewritten file was not answered');
  assert.equal(openResults(panel).at(-1).outcome, 'blocked');
  assert.equal(openResults(panel).at(-1).reason, 'changed');
});

test('blocked-open wording names the file, the reason and that nothing was opened', () => {
  assert.equal(api.blockedOpenText('changed', 'a.py', { revisionId: 'r2' }), 'a.py changed after revision r2 was published; not opened.');
  assert.equal(api.blockedOpenText('too-large', 'a.py'), 'a.py has grown past the size MLView can check; not opened.');
  assert.equal(api.blockedOpenText('elsewhere', 'a.py', { folder: './copy/' }), 'a.py is not in the workspace root; it is unchanged in ./copy/. Not opened.');
  assert.equal(api.blockedOpenText('unsaved', 'a.py'), 'Unsaved changes in a.py no longer contain the cited lines; not opened. Save or revert the file.');
  assert.equal(api.blockedOpenText('unchecked', 'a.py', { issue: 'bad' }), 'a.py could not be checked (bad); not opened.');
});
