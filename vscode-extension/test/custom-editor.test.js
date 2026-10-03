'use strict';
/**
 * Viewer M4 (roadmap step 18): a *.mlview.json opens as its diagram, from the Explorer, Quick Open
 * or a link, through a read-only custom editor (`mlview.diagram`, priority "default"). One hosting
 * path: VS Code resolves the editor and `AuthoredPanel` hosts its webview panel, with the same
 * validation, watchers, freshness, revisions, navigation, walk, citation index and refinement as
 * before; MLView: Open Generated Diagram opens the same editor. Mock `vscode` only: none of this is
 * a live check.
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
const VIEW_TYPE = 'mlview.diagram';
const token = () => new vscode.CancellationTokenSource().token;
const citedKey = () => vscode.__recorded.contexts.get('mlview.citedFiles');
/** The listeners a diagram needs from the workspace: the file watcher and the save and edit events. */
const sourceListeners = () => ({
  watchers: vscode.__recorded.watchers.length,
  saves: vscode.__recorded.saveListeners.length + vscode.__recorded.notebookSaveListeners.length,
  edits: vscode.__recorded.changeListeners.length + vscode.__recorded.notebookChangeListeners.length
});
/** VS Code resolving a diagram editor for `file` in a panel it made (`viewColumn` 1). */
async function resolveIn(controller, file, { scheme } = {}) {
  const uri = scheme ? new vscode.Uri(file, scheme) : vscode.Uri.file(file);
  const panel = vscode.window.createWebviewPanel(VIEW_TYPE, path.basename(file), { viewColumn: 1 }, {});
  const document = await controller.openCustomDocument(uri, {}, token());
  await controller.resolveCustomEditor(document, panel, token());
  return panel;
}

test('the custom editor is registered for mlview.diagram, several editors per file allowed', async () => {
  await open({});
  const registration = vscode.__recorded.customEditors.get(VIEW_TYPE);
  assert.ok(registration, 'a provider for the manifest\'s view type');
  assert.equal(api.DIAGRAM_EDITOR_VIEW_TYPE, VIEW_TYPE);
  assert.notEqual(api.DIAGRAM_EDITOR_VIEW_TYPE, api.AUTHORED_VIEW_TYPE, 'the editor and the earlier webview panel do not share a view type');
  assert.deepEqual(registration.options, { supportsMultipleEditorsPerDocument: true });
  assert.equal(typeof registration.provider.openCustomDocument, 'function');
  assert.equal(typeof registration.provider.resolveCustomEditor, 'function');
  assert.equal(registration.provider.saveCustomDocument, undefined, 'read-only: no save, no edits');
});

test('resolveCustomEditor hosts the diagram: options, page, validation, registry and the cited-files key', async () => {
  const fixture = await open({});
  fixture.panel.dispose();
  const panel = await resolveIn(fixture.controller, fixture.artifact);
  assert.deepEqual(panel.webview.options, { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(fixture.ctx.extensionUri, 'media')] });
  assert.match(panel.webview.html, /Content-Security-Policy/);
  assert.match(panel.webview.html, /mountWorkflow/);
  assert.equal(panel.title, 'run.mlview.json', 'the tab keeps the file\'s name');
  panel.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(panel).length === 1, 'the diagram was not shown');
  assert.equal(panel.posted.find((m) => m.type === 'init').artifact, fixture.artifact);
  assert.equal(h.shownRevision(panel), 'r1');
  await h.sleep(15);
  assert.deepEqual(fixture.ctx.globalState.get(api.OPEN_PANELS_KEY)['mock-session'].panels, [{ artifact: fixture.artifact, title: 'run.mlview.json', column: 1, kind: 'editor' }]);
  assert.deepEqual(citedKey(), [path.join(fixture.root, 'source.py')]);
  // A disk change reaches it through the watchers, as before.
  h.writeJson(fixture.artifact, h.workflow('source.py', { id: 'r2', parent: 'r1' }));
  await h.diskEvent(panel, 'change', fixture.artifact);
  assert.equal(h.shownRevision(panel), 'r2');
});

test('the diagram is drawn from the file on disk, never from the editor\'s unsaved text', async () => {
  const fixture = await open({});
  // The JSON is open as text too, with unsaved edits naming another revision.
  vscode.__setDocument(fixture.artifact, JSON.stringify(h.workflow('source.py', { id: 'unsaved' })));
  vscode.__setDirty(fixture.artifact);
  vscode.__fireWatcher('change', path.join(fixture.root, 'source.py'));
  await h.waitFor(() => (h.lastBanner(fixture.panel).codes || []).includes('dirty'), 'the unsaved edits were not reported');
  assert.equal(h.shownRevision(fixture.panel), 'r1');
  assert.match(h.lastBanner(fixture.panel).message, /Unsaved editor changes in run\.mlview\.json are not checked/);
});

test('MLView: Open Generated Diagram opens the diagram editor beside, keeping the focus, and brings an open one to the front', async () => {
  const fixture = await open({});
  assert.deepEqual(vscode.__recorded.openWith.map((call) => [call.uri.fsPath, call.viewType, call.options]), [
    [fixture.artifact, VIEW_TYPE, { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true, preview: false }]
  ]);
  assert.equal(fixture.panel.viewType, VIEW_TYPE);
  assert.equal(h.shownRevision(fixture.panel), 'r1', 'open waits for the first check');
  // Again, while it is shown: no second editor; it shows the file as it is, in its own group.
  await fixture.controller.open(vscode.Uri.file(fixture.artifact));
  assert.equal(vscode.__recorded.openWith.length, 1);
  assert.equal(fixture.panel.viewColumn, 2);
  assert.deepEqual(fixture.panel.revealCalls.at(-1), { viewColumn: 2, preserveFocus: true });
  // Hidden behind another tab: it comes to the front of its own group too. Revealed with no group or
  // another group's, VS Code would show the one editor in two groups (M4 live finding).
  fixture.panel.__setViewState({ visible: false });
  await fixture.controller.open(vscode.Uri.file(fixture.artifact));
  assert.deepEqual(fixture.panel.revealCalls.at(-1), { viewColumn: 2, preserveFocus: true });
  assert.equal(vscode.__recorded.openWith.length, 1);
  assert.deepEqual(vscode.__recorded.splitReveals, []);
});

test('a diagram whose group VS Code has not reported comes to the front of the group holding its tab, never another', async () => {
  const fixture = await open({});
  vscode.__setTabGroups([
    { viewColumn: 1, tabs: [{ label: 'code.py', uri: path.join(fixture.root, 'code.py'), isActive: true }] },
    { viewColumn: 2, tabs: [
      { label: 'run.mlview.json', custom: fixture.artifact, customViewType: VIEW_TYPE },
      { label: 'notes.md', uri: path.join(fixture.root, 'notes.md'), isActive: true }
    ] }
  ]);
  fixture.panel.__setViewState({ viewColumn: 0, visible: false });
  await fixture.controller.open(vscode.Uri.file(fixture.artifact));
  assert.deepEqual(fixture.panel.revealCalls.at(-1), { viewColumn: 2, preserveFocus: true }, 'the group whose tab shows this file, behind another');
  // No group holds it: no reveal rather than one into the active group.
  vscode.__setTabGroups([{ viewColumn: 1, tabs: [{ label: 'code.py', uri: path.join(fixture.root, 'code.py'), isActive: true }] }]);
  const calls = fixture.panel.revealCalls.length;
  await fixture.controller.open(vscode.Uri.file(fixture.artifact));
  assert.equal(fixture.panel.revealCalls.length, calls);
  assert.deepEqual(vscode.__recorded.splitReveals, []);
});

test('the command run from a diagram editor (no text editor active) uses that editor\'s file', async () => {
  const fixture = await open({});
  const other = path.join(fixture.root, 'other.mlview.json');
  fs.copyFileSync(fixture.artifact, other);
  vscode.__setTabGroups([{ viewColumn: 1, isActive: true, tabs: [{ label: 'other.mlview.json', custom: other, isActive: true }] }]);
  await vscode.__recorded.commands.get('mlview.openGeneratedDiagram')();
  assert.equal(vscode.__recorded.quickPicks.length, 0, 'no file picker');
  assert.equal(vscode.__recorded.openWith.at(-1).uri.fsPath, other);
});

test('a file MLView does not draw gets a page saying why, and nothing else', async () => {
  const fixture = await open({});
  const before = sourceListeners();
  const outsideRoot = h.tempRoot('mlview-outside-');
  fixtures.push({ root: outsideRoot });
  const outside = path.join(outsideRoot, 'x.mlview.json');
  h.writeJson(outside, h.workflow());
  const cases = [
    [await resolveIn(fixture.controller, fixture.artifact, { scheme: 'git' }), /comes from git: rather than from a file on disk/],
    [await resolveIn(fixture.controller, outside), /x\.mlview\.json is not inside one/],
    [await resolveIn(fixture.controller, path.join(fixture.root, 'notes.json')), /notes\.json is not one/]
  ];
  for (const [panel, why] of cases) {
    assert.match(panel.webview.html, /MLView cannot draw this file/);
    assert.match(panel.webview.html, why);
    assert.match(panel.webview.html, /View: Reopen Editor With… from the Command Palette and choose Text Editor/);
    assert.deepEqual(panel.webview.options, { enableScripts: false }, 'no script runs on it');
    assert.doesNotMatch(panel.webview.html, /<script/);
    panel.fire({ v: 1, type: 'ready' });
    await h.tick();
    assert.equal(panel.posted.length, 0, 'no diagram host answers it');
  }
  await h.sleep(15);
  // Viewer M4 review (M4R-3): the page for a file outside every folder is registered too, marked,
  // so the next host after an extension-host restart can replace its dead tab.
  const registered = fixture.ctx.globalState.get(api.OPEN_PANELS_KEY)['mock-session'].panels;
  assert.deepEqual(registered.map((p) => [p.artifact, !!p.notice]), [[fixture.artifact, false], [outside, true]], 'the real diagram, and the page for the file outside the folders');
  assert.deepEqual(sourceListeners(), before);
});

test('the page for a file outside every folder draws the diagram in the same tab once a folder holds the file (M4R-3)', async () => {
  // Before, the page said "add it to the workspace, then open the file again", and opening it again
  // in the same group only brought the page forward: VS Code reuses an open editor of the same file.
  const fixture = await open({});
  const outsideRoot = h.tempRoot('mlview-outside-');
  fixtures.push({ root: outsideRoot });
  fs.writeFileSync(path.join(outsideRoot, 'source.py'), 'fit()\n');
  const outside = path.join(outsideRoot, 'x.mlview.json');
  h.writeJson(outside, h.workflow());
  const panel = await resolveIn(fixture.controller, outside);
  assert.match(panel.webview.html, /MLView cannot draw this file/);
  assert.match(panel.webview.html, /Add the folder that holds it to the workspace \(Workspaces: Add Folder to Workspace…\) and this tab draws the diagram/);
  // A folder that does not hold it changes nothing.
  vscode.workspace.updateWorkspaceFolders(1, 0, { uri: vscode.Uri.file(h.tempRoot('mlview-other-')) });
  await h.sleep(15);
  assert.match(panel.webview.html, /MLView cannot draw this file/);
  // The reader adds the folder (a multi-root window keeps its extension host).
  vscode.workspace.updateWorkspaceFolders(2, 0, { uri: vscode.Uri.file(outsideRoot) });
  await h.waitFor(() => /mountWorkflow/.test(panel.webview.html), 'the page was not replaced by the diagram');
  assert.deepEqual(panel.webview.options, { enableScripts: true, localResourceRoots: [vscode.Uri.joinPath(fixture.ctx.extensionUri, 'media')] });
  panel.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(panel).length === 1, 'the diagram was not drawn');
  assert.equal(h.shownRevision(panel), 'r1');
  await h.sleep(15);
  const registered = fixture.ctx.globalState.get(api.OPEN_PANELS_KEY)['mock-session'].panels;
  assert.deepEqual(registered.map((p) => [p.artifact, !!p.notice]), [[fixture.artifact, false], [outside, false]], 'a diagram now, no longer the page');
  // Closing the tab leaves the registry as for any diagram.
  panel.dispose();
  await h.sleep(15);
  assert.deepEqual(fixture.ctx.globalState.get(api.OPEN_PANELS_KEY)['mock-session'].panels.map((p) => p.artifact), [fixture.artifact]);
});

test('the last diagram closing disposes the watchers and the citation index; the next one creates them again', async () => {
  const fixture = await open({});
  assert.deepEqual(sourceListeners(), { watchers: 1, saves: 2, edits: 2 });
  assert.deepEqual(citedKey(), [path.join(fixture.root, 'source.py')]);
  // A second diagram of the same file (VS Code's Split Editor) shares them.
  const second = await resolveIn(fixture.controller, fixture.artifact);
  assert.deepEqual(sourceListeners(), { watchers: 1, saves: 2, edits: 2 });
  fixture.panel.dispose();
  assert.deepEqual(sourceListeners(), { watchers: 1, saves: 2, edits: 2 }, 'one diagram is still open');
  await h.waitFor(() => citedKey()?.length === 1, 'the key lost the file while a diagram cites it');
  second.dispose();
  assert.deepEqual(sourceListeners(), { watchers: 0, saves: 0, edits: 0 });
  assert.deepEqual(citedKey(), [], 'Reveal in Diagram is offered nowhere');
  // Reveal in Diagram has nothing to answer from.
  vscode.__setActiveEditor({ path: path.join(fixture.root, 'source.py'), viewColumn: 1 });
  await vscode.__recorded.commands.get('mlview.revealInDiagram')();
  assert.match(vscode.__recorded.messages.at(-1)[1], /no diagram is open/);
  // A new diagram watches again.
  await fixture.controller.open(vscode.Uri.file(fixture.artifact));
  assert.deepEqual(sourceListeners(), { watchers: 1, saves: 2, edits: 2 });
  await h.waitFor(() => citedKey()?.length === 1, 'the key did not come back');
});

test('two diagrams of one file follow it each with its own revisions, comparison and opens', async () => {
  const fixture = await open({});
  const second = await resolveIn(fixture.controller, fixture.artifact);
  second.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(second).length === 1, 'the second diagram showed nothing');
  h.writeJson(fixture.artifact, h.workflow('source.py', { id: 'r2', parent: 'r1' }));
  await h.diskEvent(fixture.panel, 'change', fixture.artifact);
  await h.waitFor(() => h.shownRevision(second) === 'r2', 'the second diagram did not follow');
  for (const panel of [fixture.panel, second]) {
    const frame = h.workflows(panel).at(-1);
    assert.equal(frame.document.revision.id, 'r2');
    assert.equal(frame.previous?.revision.id, 'r1', 'each compares with the revision it showed');
  }
  // The walk's numbered opens are per diagram: a high number in one does not cancel the other's.
  fixture.panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e', seq: 9, requestId: 'a9', walk: true });
  await h.waitFor(() => h.results(fixture.panel).some((m) => m.requestId === 'a9'), 'the first diagram\'s open got no answer');
  second.fire({ v: 1, type: 'openLocation', evidenceId: 'e', seq: 1, requestId: 'b1', walk: true });
  await h.waitFor(() => h.results(second).some((m) => m.requestId === 'b1'), 'the second diagram\'s open got no answer');
  assert.equal(h.results(second).find((m) => m.requestId === 'b1').outcome, 'done');
  // Closing one leaves the other working.
  fixture.panel.dispose();
  h.writeJson(fixture.artifact, h.workflow('source.py', { id: 'r3', parent: 'r2' }));
  await h.diskEvent(second, 'change', fixture.artifact);
  assert.equal(h.shownRevision(second), 'r3');
});

test('an earlier MLView panel reopens as the diagram editor in its group before it closes, even before VS Code reports its column', async () => {
  const fixture = await open({});
  fixture.panel.dispose();
  const [group] = vscode.__setTabGroups([{ viewColumn: 1, tabs: [{ label: 'train.py', uri: path.join(fixture.root, 'train.py'), isActive: false }, { label: 'MLView: Authored', viewType: 'mainThreadWebview-mlview.authoredDiagram', isActive: true }] }]);
  const legacyTab = group.tabs[1];
  const legacy = vscode.__reviveTab(legacyTab);
  // VS Code revives a restored panel with column 0 and reports its group a moment later.
  legacy.viewColumn = 0;
  let disposedWhenResolved;
  const resolve = fixture.controller.resolveCustomEditor.bind(fixture.controller);
  fixture.controller.resolveCustomEditor = (...args) => { disposedWhenResolved = legacy.disposed; return resolve(...args); };
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(legacy, { artifact: fixture.artifact, viewport: { zoom: 2 } });
  assert.equal(disposedWhenResolved, false, 'the diagram editor opens first, so the group stays');
  assert.equal(legacy.disposed, true);
  assert.deepEqual(vscode.__recorded.openWith.at(-1).options, { viewColumn: 1, preserveFocus: true, preview: false });
  assert.deepEqual(group.tabs.map((tab) => tab.label), ['train.py', 'run.mlview.json']);
  assert.equal(group.tabs[1].input.viewType, VIEW_TYPE);
});

test('navigation beside a diagram editor tab reuses the other group, even before VS Code reports the editor\'s column', async () => {
  const fixture = await open({});
  const { panel, root } = fixture;
  // The diagram in group 1, the code in group 2.
  vscode.__setTabGroups([
    { viewColumn: 1, tabs: [{ label: 'run.mlview.json', custom: fixture.artifact, isActive: true }] },
    { viewColumn: 2, tabs: [{ label: 'code.py', uri: path.join(root, 'code.py'), isActive: true }] }
  ]);
  panel.__setViewState({ viewColumn: 0 });
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.shownDocuments.length === 1, 'the jump did not open');
  const { options } = vscode.__recorded.shownDocuments[0];
  assert.equal(options.viewColumn, 2, 'the group beside the diagram, not the diagram\'s own and not a new one');
  assert.equal(options.preserveFocus, true);
  assert.equal(vscode.window.tabGroups.all.length, 2);
  // With its column reported, the same.
  panel.__setViewState({ viewColumn: 1 });
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e', focus: true });
  await h.waitFor(() => vscode.__recorded.shownDocuments.length === 2, 'the second jump did not open');
  assert.equal(vscode.__recorded.shownDocuments[1].options.viewColumn, 2);
  assert.equal(vscode.__recorded.shownDocuments[1].options.preserveFocus, false, 'Alt+Enter moves the focus');
});

test('Reveal in Diagram finds diagram editors, one per file: the active one of several', async () => {
  const fixture = await open({});
  const second = await resolveIn(fixture.controller, fixture.artifact);
  second.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(second).length === 1, 'the second diagram showed nothing');
  second.__setViewState({ active: true });
  vscode.__setActiveEditor({ path: path.join(fixture.root, 'source.py'), viewColumn: 2, selection: [0, 0, 0, 0] });
  await vscode.__recorded.commands.get('mlview.revealInDiagram')();
  // The step and the connection cite line 1: the reader chooses the claim, never the diagram.
  assert.equal(vscode.__recorded.quickPicks.length, 1);
  assert.match(vscode.__recorded.quickPicks[0].options.placeHolder, /claims cite line 1 of source\.py/);
  vscode.__answerQuickPick(0);
  await vscode.__recorded.commands.get('mlview.revealInDiagram')();
  assert.deepEqual(second.posted.filter((m) => m.type === 'reveal').map((m) => [m.kind, m.id]), [['node', 'n']]);
  assert.deepEqual(second.revealCalls.at(-1), { viewColumn: second.viewColumn, preserveFocus: false }, 'the diagram editor comes to the front of its own group, with the focus');
  assert.deepEqual(vscode.__recorded.splitReveals, []);
  assert.equal(fixture.panel.posted.filter((m) => m.type === 'reveal').length, 0);
});
