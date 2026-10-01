'use strict';
/**
 * Viewer M1, the host half of the verification loop: a source jump opens beside the panel with
 * focus kept on the diagram, selects and highlights the whole cited range (text and notebook
 * cells), has an explicit open-and-focus variant and skips the full revalidation when the cited
 * file is unchanged; the typed `stale` frame; the workspace-root hint, which is checked against
 * the published hashes and never changes what validation reads; and revalidation when the
 * workspace folders change.
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
const shown = () => vscode.__recorded.shownDocuments;
const staleFrames = (panel) => panel.posted.filter((m) => m.type === 'stale');
const plain = (value) => JSON.parse(JSON.stringify(value));
const range = (r) => [r.start.line, r.start.character, r.end.line, r.end.character];

/** Two evidence records in two files, lines 2-3 of source.py and line 1 of other.py. */
function twoFiles() {
  const document = h.workflow();
  document.evidence = [
    { id: 'e', file: 'source.py', line: 2, endLine: 3, quote: 'train()\nsave()' },
    { id: 'e2', file: 'other.py', line: 1, endLine: 1, quote: 'other()' }
  ];
  document.nodes[0].evidence = ['e', 'e2'];
  document.coverage.inspectedFiles = ['source.py', 'other.py'];
  return { document, files: { 'source.py': 'import x\ntrain()\nsave()\n', 'other.py': 'other()\n' } };
}

test('a jump opens beside the panel, keeps focus on the diagram, selects the whole range and highlights it', async () => {
  const { document, files } = twoFiles();
  const { panel, root } = await open({ raw: document, files });
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => shown().length === 1, 'the jump did not open the source');
  const { document: opened, options, editor } = shown()[0];
  assert.equal(opened.uri.fsPath, path.join(root, 'source.py'));
  assert.equal(options.preserveFocus, true, 'the diagram keeps the keyboard');
  assert.equal(options.preview, true);
  assert.equal(options.viewColumn, vscode.ViewColumn.Beside, 'with no source editor open, the source opens beside the panel');
  assert.deepEqual(range(editor.selection), [1, 0, 2, 'save()'.length], 'the whole cited range is selected');
  assert.deepEqual(range(editor.revealed[0].range), [1, 0, 2, 'save()'.length]);
  assert.equal(vscode.__recorded.decorationTypes.length, 1);
  const style = vscode.__recorded.decorationTypes[0].options;
  assert.equal(style.isWholeLine, true);
  assert.equal(style.backgroundColor.id, 'editor.rangeHighlightBackground', 'the highlight uses the theme colour');
  assert.equal(style.overviewRulerColor.id, 'editorOverviewRuler.rangeHighlightForeground');
  assert.equal(style.overviewRulerLane, vscode.OverviewRulerLane.Full);
  assert.equal(editor.decorations.length, 1);
  assert.equal(editor.decorations[0].type, vscode.__recorded.decorationTypes[0]);
  assert.deepEqual(editor.decorations[0].ranges.map(range), [[1, 0, 2, 'save()'.length]]);
});

test('the next jump moves the highlight, and closing the panel clears it', async () => {
  const { document, files } = twoFiles();
  const { panel } = await open({ raw: document, files });
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => shown().length === 1, 'the first jump did not open');
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e2' });
  await h.waitFor(() => shown().length === 2, 'the second jump did not open');
  const [first, second] = vscode.__recorded.decorationTypes;
  assert.equal(first.disposed, true, 'the previous highlight is cleared on the next jump');
  assert.equal(second.disposed, false);
  assert.deepEqual(shown()[1].editor.decorations[0].ranges.map(range), [[0, 0, 0, 'other()'.length]]);
  panel.dispose();
  assert.equal(second.disposed, true, 'closing the panel clears the highlight');
});

test('focus: true is the explicit gesture that opens the source and moves focus to the editor', async () => {
  const { panel } = await open({});
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e', focus: true });
  await h.waitFor(() => shown().length === 1, 'the jump did not open');
  assert.equal(shown()[0].options.preserveFocus, false);
  // Anything but literal true keeps focus on the diagram.
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e', focus: 'yes' });
  await h.waitFor(() => shown().length === 2, 'the second jump did not open');
  assert.equal(shown()[1].options.preserveFocus, true);
});

function notebookDocument() {
  const document = h.workflow('notes.ipynb');
  document.evidence = [{ id: 'e', file: 'notes.ipynb', cell: 1, line: 2, endLine: 3, quote: 'fit()\nsave()' }];
  const notebook = JSON.stringify({ cells: [{ source: ['a()'] }, { source: ['x = 1\n', 'fit()\n', 'save()'] }], metadata: {}, nbformat: 4, nbformat_minor: 5 });
  return { document, files: { 'notes.ipynb': notebook } };
}

test('a notebook jump selects and reveals the cell, then selects and highlights the cited lines in its editor', async () => {
  const { document, files } = notebookDocument();
  const fixture = await open({ raw: document, files, ready: false });
  const [notebook] = vscode.__setNotebooks([{ path: path.join(fixture.root, 'notes.ipynb'), cells: [{ text: 'a()' }, { text: 'x = 1\nfit()\nsave()' }] }]);
  fixture.panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  fixture.panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.decorationTypes.length === 1, 'the cell lines were not highlighted');
  assert.equal(shown().length, 0, 'the notebook is shown as a notebook, not as a bare cell document');
  const { options, editor: notebookEditor } = vscode.__recorded.shownNotebooks[0];
  assert.equal(options.preserveFocus, true);
  assert.deepEqual(plain(options.selections), [{ start: 1, end: 2 }], 'the cited cell is selected');
  assert.deepEqual(plain(notebookEditor.revealed[0].range), { start: 1, end: 2 });
  assert.equal(notebookEditor.revealed[0].revealType, vscode.NotebookEditorRevealType.InCenterIfOutsideViewport);
  const cellEditor = vscode.window.visibleTextEditors.find((editor) => editor.document === notebook.cellAt(1).document);
  assert.ok(cellEditor, 'the cell editor became visible');
  assert.deepEqual(range(cellEditor.selection), [1, 0, 2, 'save()'.length]);
  assert.deepEqual(cellEditor.decorations[0].ranges.map(range), [[1, 0, 2, 'save()'.length]]);
});

test('when the cell editor does not appear, the cell stays selected and the last highlight is cleared', async () => {
  const { document, files } = notebookDocument();
  document.evidence.push({ id: 'e2', file: 'source.py', line: 1, endLine: 1, quote: 'fit()' });
  document.nodes[0].evidence.push('e2');
  document.coverage.inspectedFiles.push('source.py');
  const fixture = await open({ raw: document, files: { ...files, 'source.py': 'fit()\n' }, ready: false });
  vscode.__setNotebooks([{ path: path.join(fixture.root, 'notes.ipynb'), cells: [{ text: 'a()' }, { text: 'x = 1\nfit()\nsave()' }] }]);
  vscode.__setNotebookCellEditors(false);
  fixture.panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  fixture.panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e2' });
  await h.waitFor(() => shown().length === 1, 'the text jump did not open');
  fixture.panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.shownNotebooks.length === 1, 'the notebook jump did not open');
  await h.waitFor(() => vscode.__recorded.decorationTypes[0].disposed, 'the earlier highlight was not cleared', 2000);
  assert.equal(vscode.__recorded.decorationTypes.length, 1, 'no highlight without a cell editor');
  assert.deepEqual(plain(vscode.__recorded.shownNotebooks[0].options.selections), [{ start: 1, end: 2 }]);
});

test('a jump into an unchanged file reads that file only and skips the full validation', async () => {
  let calls = 0;
  const validator = async (...args) => { calls++; return api.validateWorkflow(...args); };
  const { panel } = await open({ validator });
  assert.equal(calls, 1, 'one validation to display the revision');
  for (let i = 1; i <= 3; i++) {
    panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
    await h.waitFor(() => shown().length === i, 'the jump did not open');
  }
  assert.equal(calls, 1, 'three jumps into an unchanged file ran no further validation');
});

test('a jump into a file changed without a watcher event validates, is blocked, and the panel catches up', async () => {
  let calls = 0;
  const validator = async (...args) => { calls++; return api.validateWorkflow(...args); };
  const { panel, root } = await open({ raw: h.verify(h.workflow(), { 'source.py': 'fit()\n' }), validator });
  fs.writeFileSync(path.join(root, 'source.py'), 'fit()\n# edited\n');
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.messages.some((m) => /evidence e cites source\.py, which changed/.test(m[1])), 'the changed file was not blocked');
  assert.equal(calls, 2, 'the jump fell back to the full validation');
  assert.equal(shown().length, 0);
  await h.waitFor(() => (h.lastBanner(panel).codes || []).includes('stale'), 'the panel did not catch up with the change');
  assert.deepEqual(staleFrames(panel).at(-1).files, [{ path: 'source.py', reason: 'changed' }]);
});

test('the stale frame names each file and its reason, is posted when the set changes, and a fresh revision clears it', async () => {
  const { document, files } = twoFiles();
  h.verify(document, files);
  const { panel, artifact, root } = await open({ raw: document, files: { 'source.py': 'import x\ntrain()\nsave()\n# edited\n' } });
  assert.deepEqual(panel.postedTypes(), ['init', 'workflow', 'stale', 'workflowError']);
  assert.deepEqual(staleFrames(panel)[0], { v: 1, type: 'stale', files: [{ path: 'other.py', reason: 'missing' }, { path: 'source.py', reason: 'changed' }] });
  // An event that changes nothing re-posts no stale frame.
  await h.diskEvent(panel, 'change', path.join(root, 'source.py'));
  assert.equal(staleFrames(panel).length, 1);
  // The deleted file comes back: the set shrinks to the one changed file.
  fs.writeFileSync(path.join(root, 'other.py'), 'other()\n');
  await h.diskEvent(panel, 'create', path.join(root, 'other.py'));
  assert.deepEqual(staleFrames(panel).at(-1).files, [{ path: 'source.py', reason: 'changed' }]);
  // A fresh child revision clears the marks, after its workflow frame.
  fs.writeFileSync(path.join(root, 'source.py'), files['source.py']);
  const child = h.verify(twoFiles().document, files);
  child.revision = { id: 'r2', parent: 'r1' };
  h.writeJson(artifact, child);
  await h.diskEvent(panel, 'change', artifact);
  await h.waitFor(() => h.shownRevision(panel) === 'r2', 'the child revision was not adopted');
  const types = panel.postedTypes();
  assert.equal(types.lastIndexOf('stale') > types.lastIndexOf('workflow'), true);
  assert.deepEqual(staleFrames(panel).at(-1).files, []);
});

/** The Stage 1 case: the workspace root is the parent of the folder the artifact cites from. */
async function parentFolderPanel(copyText = 'fit()\n', options = {}) {
  const document = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  return open({ raw: document, files: { 'copy/source.py': copyText }, artifactName: 'copy/run.mlview.json', ...options });
}

test('root hint: files that exist under the artifact folder with the published hashes get a hint, not the stale wording', async () => {
  const { panel, root } = await parentFolderPanel();
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['root-hint']);
  assert.match(banner.message, /^This file exists under \.\/copy\/ but the workspace root is [^:]+: source\.py\. It matches its published hash/);
  assert.ok(banner.message.includes(path.basename(root)));
  assert.doesNotMatch(banner.message, /no longer match|Ask the assistant/);
  // The product still validates against the real root: the file is missing there and its jump is blocked.
  assert.deepEqual(staleFrames(panel).at(-1).files, [{ path: 'source.py', reason: 'missing' }]);
  const hint = vscode.__recorded.messages.find((m) => m[0] === 'info' && /This file exists under \.\/copy\//.test(m[1]));
  assert.ok(hint, 'the notification is the hint');
  assert.deepEqual(hint.slice(2), ['Add Folder to Workspace', 'Open Folder']);
  assert.equal(vscode.__recorded.messages.some((m) => m[0] === 'warn' && /no longer match the displayed revision/.test(m[1])), false, 'no stale warning');
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.messages.some((m) => /cites source\.py, which is missing/.test(m[1])), 'the jump was not blocked');
  assert.equal(shown().length, 0, 'the hint never substitutes a path');
});

test('root hint: Add Folder to Workspace adds the hinted folder, and the panel validates again against it', async () => {
  const { panel, root } = await parentFolderPanel();
  // The folder comes from the host's own hint; a path in the message is ignored.
  panel.fire({ v: 1, type: 'workspaceHint', action: 'add', path: '/elsewhere' });
  await h.waitFor(() => vscode.__recorded.workspaceFolderUpdates.length === 1, 'no folder was added');
  const update = vscode.__recorded.workspaceFolderUpdates[0];
  assert.equal(update.start, 1, 'appended after the existing folder');
  assert.equal(update.deleteCount, 0);
  assert.equal(update.folders[0].uri.fsPath, path.join(root, 'copy'));
  await h.waitFor(() => h.lastBanner(panel).message === '' && (h.lastBanner(panel).codes || []).length === 0, 'the panel did not validate again against the added folder');
  assert.deepEqual(staleFrames(panel).at(-1).files, []);
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => shown().length === 1, 'the jump did not open after the folder was added');
  assert.equal(shown()[0].document.uri.fsPath, path.join(root, 'copy', 'source.py'));
});

test('root hint: Open Folder opens the hinted folder in a new window', async () => {
  const { panel, root } = await parentFolderPanel();
  panel.fire({ v: 1, type: 'workspaceHint', action: 'open' });
  await h.waitFor(() => vscode.__recorded.executedCommands.length === 1, 'no folder was opened');
  const [call] = vscode.__recorded.executedCommands;
  assert.equal(call.id, 'vscode.openFolder');
  assert.equal(call.args[0].fsPath, path.join(root, 'copy'));
  assert.deepEqual(call.args[1], { forceNewWindow: true });
  assert.equal(vscode.__recorded.workspaceFolderUpdates.length, 0);
});

test('root hint: no hint when the file under the artifact folder does not match the published hash', async () => {
  const { panel } = await parentFolderPanel('fit()\n# a different copy\n');
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['stale']);
  assert.match(banner.message, /no longer match revision r1 as published \(1 missing\)/);
  assert.equal(vscode.__recorded.messages.some((m) => m[0] === 'info'), false);
  panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.sleep(30);
  assert.equal(vscode.__recorded.workspaceFolderUpdates.length, 0, 'without a hint the action does nothing');
});

test('root hint helpers: candidates stop below the root, and only a strict majority of missing files counts', () => {
  const root = path.resolve('/ws');
  assert.deepEqual(api.rootHintCandidates(path.join(root, 'a', 'b', 'run.mlview.json'), root), [path.join(root, 'a', 'b'), path.join(root, 'a')]);
  assert.deepEqual(api.rootHintCandidates(path.join(root, 'run.mlview.json'), root), [], 'an artifact at the root has no other candidate');
  const published = { 'a.py': 'x', 'b.py': 'y', 'c.py': 'z' };
  assert.deepEqual(api.mostlyMissing(['a.py', 'b.py', 'c.py'], published, [{ rel: 'a.py', reason: 'missing' }, { rel: 'b.py', reason: 'missing' }]), ['a.py', 'b.py']);
  assert.deepEqual(api.mostlyMissing(['a.py', 'b.py', 'c.py'], published, [{ rel: 'a.py', reason: 'missing' }, { rel: 'b.py', reason: 'changed' }]), [], 'one of three is not most');
  assert.deepEqual(api.mostlyMissing(['a.py', 'b.py'], published, [{ rel: 'a.py', reason: 'missing' }]), [], 'half is not most');
  const list = (names) => names.join(', ');
  assert.equal(api.rootHintText({ base: path.join(root, 'a'), root, files: ['x.py', 'y.py'] }, list),
    'These files exist under ./a/ but the workspace root is ws: x.py, y.py. They match their published hashes, so the source did not change; ' +
    'MLView looks for them in the wrong folder. Add ./a/ to the workspace, or open it in its own window.');
});

test('a workspace folder change validates every open panel again', async () => {
  let calls = 0;
  const validator = async (...args) => { calls++; return api.validateWorkflow(...args); };
  const { panel, root } = await open({ validator });
  assert.equal(calls, 1);
  vscode.workspace.updateWorkspaceFolders(1, 0, { uri: vscode.Uri.file(path.join(path.dirname(root), 'unrelated')) });
  await h.waitFor(() => (h.lastBanner(panel).codes || [])[0] === 'checking', 'the folder change did not start a check');
  await h.waitFor(() => calls === 2 && (h.lastBanner(panel).codes || []).length === 0, 'the panel did not validate again');
  assert.equal(h.workflows(panel).length, 1, 'an unchanged revision is not re-posted');
});
