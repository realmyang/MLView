'use strict';
/**
 * The root hint's "Add folder to workspace" in a single-folder window. VS Code turns the window
 * into an untitled multi-root workspace and restarts the extension host; the open panels keep
 * their tabs but are never revived (VS Code calls the serializer only for tabs it restores when a
 * window loads). Before adding the folder the host saves a reopen note in the global state, keyed
 * by the window's session; the next host closes the dead tabs and opens the diagrams again.
 * A multi-root window keeps its host and validates in place. Reload Window goes through the
 * serializer, with the artifact the webview state keeps.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;

const KEY = api.REOPEN_STATE_KEY;
const TAB_VIEW_TYPE = 'mainThreadWebview-mlview.authoredDiagram';
const fixtures = [];
const restores = [];
test.afterEach(() => {
  for (const restore of restores.splice(0)) restore();
  h.cleanup(fixtures);
});

/** The Stage 1 case: the window's folder is the parent of the folder the artifact cites from. */
async function parentFolderPanel(options = {}) {
  const document = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  const fixture = await h.openPanel({ raw: document, files: { 'copy/source.py': 'fit()\n' }, artifactName: 'copy/run.mlview.json', ...options });
  fixtures.push(fixture);
  assert.deepEqual(h.lastBanner(fixture.panel).codes, ['root-hint']);
  return fixture;
}

/**
 * Stand in for VS Code's `updateWorkspaceFolders` in a single-folder window: it stops the
 * extension host before it changes the folders, so this host never sees the change. Records the
 * reopen note as it was when the call was made.
 */
function stopsTheHost(fixture, answer = true) {
  const calls = [];
  const original = vscode.workspace.updateWorkspaceFolders;
  vscode.workspace.updateWorkspaceFolders = (start, deleteCount, ...folders) => {
    calls.push({ start, deleteCount, folders, note: fixture.ctx.globalState.get(KEY) });
    return answer;
  };
  restores.push(() => { vscode.workspace.updateWorkspaceFolders = original; });
  return calls;
}

/**
 * The restart: the old host deactivates (its panels stay open, dead), VS Code opens the new
 * untitled workspace with both folders, and a new host activates with the same global state and
 * the tabs the window still shows.
 */
function restart(fixture, groups) {
  fixture.controller.dispose();
  vscode.__setWorkspaceFolders([fixture.root, path.join(fixture.root, 'copy')]);
  vscode.__setWorkspaceFile('untitled:Untitled-1');
  const tabGroups = vscode.__setTabGroups(groups);
  const controller = new api.AuthoredDiagramController(h.context(fixture.ctx.globalState), h.log());
  controller.register();
  fixtures.push({ controller });
  return { controller, tabGroups };
}

const deadTab = (label, isActive = true) => ({ label, viewType: TAB_VIEW_TYPE, isActive });
async function addFolderFromSingleFolderWindow(fixture) {
  const calls = stopsTheHost(fixture);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => calls.length === 1, 'the folder was not added');
  return calls[0];
}

test('single-folder window: Add folder saves the reopen note before asking VS Code to add the folder', async () => {
  const fixture = await parentFolderPanel();
  assert.equal(vscode.workspace.workspaceFile, undefined, 'a single-folder window');
  const before = Date.now();
  const call = await addFolderFromSingleFolderWindow(fixture);
  assert.equal(call.start, 1);
  assert.equal(call.deleteCount, 0);
  assert.equal(call.folders[0].uri.fsPath, path.join(fixture.root, 'copy'));
  const note = call.note;
  assert.ok(note, 'the note was saved before the folder was added');
  assert.equal(note.session, 'mock-session');
  assert.equal(note.added, path.join(fixture.root, 'copy'));
  assert.deepEqual(note.panels, [{ artifact: fixture.artifact, title: 'MLView: Authored' }]);
  assert.ok(note.at >= before && note.at <= Date.now());
  assert.equal(fixture.panel.title, 'MLView: Authored', 'the noted title is the tab title');
});

test('the next host closes the dead tab and opens the diagram again in its group, validated against the added folder', async () => {
  const fixture = await parentFolderPanel();
  await addFolderFromSingleFolderWindow(fixture);
  const created = vscode.__recorded.panels.length;
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [{ label: 'train.py', uri: path.join(fixture.root, 'train.py'), isActive: true }] },
    { viewColumn: 2, tabs: [deadTab('MLView: Authored')] }
  ]);
  const dead = tabGroups[1].tabs[0];
  assert.equal(await controller.recoverAfterRestart(), 1);
  assert.equal(vscode.__recorded.panels.length, created + 1, 'one new panel');
  const reopened = vscode.__recorded.panels.at(-1);
  assert.notEqual(reopened, fixture.panel);
  assert.equal(reopened.viewType, 'mlview.authoredDiagram');
  assert.equal(reopened.viewColumn, 2, 'in the dead tab\'s group');
  assert.equal(vscode.__recorded.closedTabs.length, 1);
  const [close] = vscode.__recorded.closedTabs;
  assert.deepEqual(close.tabs, [dead], 'only the dead diagram tab is closed');
  assert.equal(close.preserveFocus, true);
  assert.equal(close.panels, created + 1, 'the new panel is opened before the dead tab closes, so the group stays');
  assert.equal(tabGroups[0].tabs.length, 1, 'the text tab stays');
  assert.equal(fixture.ctx.globalState.get(KEY), undefined, 'the note is used once');
  // The new panel validates against the folder that now owns the artifact: no hint, no stale files.
  reopened.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(reopened).length === 1, 'the reopened panel showed no diagram');
  assert.equal(h.lastBanner(reopened).message, '');
  assert.deepEqual(reopened.posted.filter((m) => m.type === 'stale').map((m) => m.files).at(-1) ?? [], []);
  assert.equal(reopened.posted.find((m) => m.type === 'init').artifact, fixture.artifact, 'the webview state keeps the artifact for a later revival');
  // A second activation finds no note and touches nothing.
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__recorded.closedTabs.length, 1);
});

test('two diagrams with the same title are each replaced in their own group; other tabs are left alone', async () => {
  const fixture = await parentFolderPanel();
  const second = path.join(fixture.root, 'copy', 'second.mlview.json');
  fs.copyFileSync(fixture.artifact, second);
  await fixture.controller.open(vscode.Uri.file(second));
  const secondPanel = vscode.__recorded.panels.at(-1);
  secondPanel.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => secondPanel.title === 'MLView: Authored', 'the second diagram was not shown');
  const call = await addFolderFromSingleFolderWindow(fixture);
  assert.deepEqual(call.note.panels.map((p) => p.artifact), [fixture.artifact, second]);
  const created = vscode.__recorded.panels.length;
  const { controller, tabGroups } = restart(fixture, [
    // A restored tab never shown (so not dead) is behind the front tab; it must stay.
    { viewColumn: 1, tabs: [deadTab('MLView: Authored', false), deadTab('MLView: Authored', true), deadTab('MLView: Other diagram', false)] },
    { viewColumn: 2, tabs: [{ label: 'MLView: Authored', viewType: 'mainThreadWebview-other.extension', isActive: false }, deadTab('MLView: Authored', true)] }
  ]);
  const [restored, front1, otherTitle] = tabGroups[0].tabs;
  const [otherExtension, front2] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 2);
  const reopened = vscode.__recorded.panels.slice(created);
  assert.deepEqual(reopened.map((p) => p.viewColumn).sort(), [1, 2]);
  assert.deepEqual(new Set(vscode.__recorded.closedTabs[0].tabs), new Set([front1, front2]));
  assert.deepEqual(tabGroups[0].tabs, [restored, otherTitle]);
  assert.deepEqual(tabGroups[1].tabs, [otherExtension]);
});

test('the note is ignored when expired, malformed, from another window or for a folder not in the workspace', async () => {
  const fixture = await parentFolderPanel();
  const { note } = await addFolderFromSingleFolderWindow(fixture);
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 1, tabs: [deadTab('MLView: Authored')] }]);
  const state = fixture.ctx.globalState;
  const created = vscode.__recorded.panels.length;
  const untouched = (label) => {
    assert.equal(vscode.__recorded.panels.length, created, `${label}: no panel opened`);
    assert.equal(vscode.__recorded.closedTabs.length, 0, `${label}: no tab closed`);
    assert.equal(tabGroups[0].tabs.length, 1);
  };

  assert.equal(await controller.recoverAfterRestart(note.at + api.REOPEN_WINDOW_MS + 1), 0);
  untouched('expired');
  assert.equal(state.get(KEY), undefined, 'an expired note is deleted');

  await state.update(KEY, { panels: 'not a list' });
  assert.equal(await controller.recoverAfterRestart(), 0);
  untouched('malformed');
  assert.equal(state.get(KEY), undefined, 'a malformed note is deleted');

  await state.update(KEY, { ...note, at: Date.now(), session: 'another-window' });
  assert.equal(await controller.recoverAfterRestart(), 0);
  untouched('another window');
  assert.equal(state.get(KEY).session, 'another-window', 'another window\'s fresh note is left for that window');
  assert.equal(await controller.recoverAfterRestart(Date.now() + api.REOPEN_WINDOW_MS + 1), 0);
  assert.equal(state.get(KEY), undefined, 'another window\'s expired note is deleted');

  await state.update(KEY, { ...note, at: Date.now(), added: path.join(fixture.root, 'elsewhere') });
  assert.equal(await controller.recoverAfterRestart(), 0);
  untouched('folder not added');
  assert.equal(state.get(KEY), undefined);
});

test('a noted artifact outside the workspace is not opened, but its dead tab is still closed', async () => {
  const fixture = await parentFolderPanel();
  const { note } = await addFolderFromSingleFolderWindow(fixture);
  const outside = path.join(path.dirname(fixture.root), 'outside', 'run.mlview.json');
  await fixture.ctx.globalState.update(KEY, { ...note, panels: [{ artifact: outside, title: 'MLView: Authored' }, { artifact: 'relative.mlview.json', title: 'MLView: Second' }] });
  const created = vscode.__recorded.panels.length;
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 1, tabs: [deadTab('MLView: Authored'), deadTab('MLView: Second', false)] }]);
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__recorded.panels.length, created);
  assert.equal(vscode.__recorded.closedTabs[0].tabs.length, 2);
  assert.equal(tabGroups[0].tabs.length, 0);
});

test('multi-root window: Add folder saves no note and validates in place', async () => {
  const fixture = await parentFolderPanel();
  vscode.__setWorkspaceFile(path.join(fixture.root, 'work.code-workspace'));
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.workspaceFolderUpdates.length === 1, 'no folder was added');
  await h.waitFor(() => h.lastBanner(fixture.panel).message === '', 'the panel did not validate again in place');
  assert.equal(fixture.ctx.globalState.updates.length, 0, 'no note');
  assert.equal(vscode.__recorded.panels.length, 1, 'the same panel');
});

test('a host that sees the folder change was not restarted: it withdraws its own note only', async () => {
  const fixture = await parentFolderPanel();
  // The mock adds the folder in this host, like a VS Code that did not restart it.
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => h.lastBanner(fixture.panel).message === '', 'the panel did not validate again in place');
  const keys = fixture.ctx.globalState.updates.map((u) => [u.key, u.value === undefined ? 'deleted' : 'saved']);
  assert.deepEqual(keys, [[KEY, 'saved'], [KEY, 'deleted']]);
  // Another window's note survives a folder change here.
  const foreign = { at: Date.now(), session: 'another-window', added: path.join(fixture.root, 'x'), panels: [] };
  await fixture.ctx.globalState.update(KEY, foreign);
  vscode.workspace.updateWorkspaceFolders(2, 0, { uri: vscode.Uri.file(path.join(fixture.root, 'x')) });
  await h.waitFor(() => (h.lastBanner(fixture.panel).codes || [])[0] === 'checking', 'the folder change was not seen');
  await h.sleep(20);
  assert.deepEqual(fixture.ctx.globalState.get(KEY), foreign);
});

test('VS Code refuses the folder: the note is withdrawn', async () => {
  const fixture = await parentFolderPanel();
  const calls = stopsTheHost(fixture, false);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.messages.some((m) => m[1] === 'MLView: VS Code did not add the folder to the workspace.'), 'no warning');
  assert.ok(calls[0].note, 'the note was saved first');
  assert.equal(fixture.ctx.globalState.get(KEY), undefined);
});

test('Reload Window after the folder was added: the serializer revives the panel and it validates against the added folder', async () => {
  const fixture = await parentFolderPanel();
  fixture.controller.dispose();
  vscode.__setWorkspaceFolders([fixture.root, path.join(fixture.root, 'copy')]);
  const controller = new api.AuthoredDiagramController(h.context(), h.log());
  controller.register();
  fixtures.push({ controller });
  const revived = vscode.window.createWebviewPanel('mlview.authoredDiagram', 'MLView: Authored', { viewColumn: 1 }, {});
  // The state the webview saved: the bootstrap adds the artifact to the viewer's own state.
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { viewport: { zoom: 2 }, artifact: fixture.artifact });
  assert.equal(revived.disposed, false);
  revived.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(revived).length === 1, 'the revived panel showed no diagram');
  assert.equal(h.lastBanner(revived).message, '');
  assert.equal(revived.posted.find((m) => m.type === 'init').artifact, fixture.artifact);
});

test('activation runs the recovery', async () => {
  const extension = require(path.join(__dirname, '..', 'out', 'extension.js'));
  const fixture = await parentFolderPanel();
  const { note } = await addFolderFromSingleFolderWindow(fixture);
  fixture.controller.dispose();
  vscode.__setWorkspaceFolders([fixture.root, path.join(fixture.root, 'copy')]);
  vscode.__setWorkspaceFile('untitled:Untitled-1');
  const [group] = vscode.__setTabGroups([{ viewColumn: 1, tabs: [deadTab(note.panels[0].title)] }]);
  const created = vscode.__recorded.panels.length;
  const ctx = { ...h.context(fixture.ctx.globalState), extension: { packageJSON: { version: '0.3.0' } } };
  extension.activate(ctx);
  try {
    await h.waitFor(() => vscode.__recorded.closedTabs.length === 1, 'activation did not close the dead tab');
    assert.equal(vscode.__recorded.panels.length, created + 1);
    assert.equal(group.tabs.length, 0);
  } finally {
    extension.deactivate();
  }
});

test('one panel per artifact: a revived tab whose diagram is already shown is closed, and the shown panel keeps working', async () => {
  const fixture = await parentFolderPanel();
  const revived = vscode.window.createWebviewPanel('mlview.authoredDiagram', 'MLView: Authored', { viewColumn: 2 }, {});
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: fixture.artifact });
  assert.equal(revived.disposed, true, 'the duplicate is closed');
  assert.equal(revived.posted.length, 0);
  // The shown panel is still registered: a change to the artifact reaches it.
  await h.diskEvent(fixture.panel, 'change', fixture.artifact);
  assert.ok(h.banners(fixture.panel).some((m) => (m.codes || [])[0] === 'checking'), 'the shown panel no longer gets disk events');
});
