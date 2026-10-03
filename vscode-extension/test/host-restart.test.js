'use strict';
/**
 * Extension host restarts inside one window ("Developer: Restart Extension Host", an extension
 * update, a single-folder window becoming a multi-root workspace through the root hint's "Add
 * folder" or VS Code's own "Add Folder to Workspace...", "Save Workspace As..."). The open diagrams
 * keep their tabs, but nothing answers them: VS Code resolves a custom editor tab again only when a
 * window loads, and calls a panel serializer only then too (both checked live in VS Code 1.139).
 * Each host keeps a registry of its open diagrams in the global state, under the window's session;
 * the next host in the same window replaces each dead tab with the diagram editor of the same
 * artifact in the same group.
 *
 * Viewer M4 (step 18), rewritten deliberately: the diagrams are diagram editors (a custom editor,
 * `mlview.diagram`), found again by their file; an entry without `kind` comes from an earlier
 * MLView's webview panel, found again by its tab's title, and is reopened as the diagram editor.
 *
 * A dead tab looks exactly like a restored tab that VS Code has not shown yet, so only the front
 * tab of a group is judged, after a settle delay in which VS Code resolves a restored tab. Reload
 * Window starts a new session, and VS Code resolves the restored diagram editors itself.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;

const KEY = api.OPEN_PANELS_KEY;
const LEGACY_TAB_VIEW_TYPE = 'mainThreadWebview-mlview.authoredDiagram';
/** The settle delay of the hosts started by these tests (the product's is `RECOVERY_SETTLE_MS`). */
const SETTLE = 40;
const fixtures = [];
const restores = [];
test.afterEach(() => {
  for (const restore of restores.splice(0)) restore();
  h.cleanup(fixtures);
});

const entry = (state, session = 'mock-session') => state.get(KEY)?.[session];
/** A diagram editor tab of `file` (dead or restored: the tabs API cannot tell). */
const editorTab = (file, isActive = true) => ({ label: path.basename(file), custom: file, isActive });
/** A tab of an earlier MLView's webview panel. */
const legacyTab = (label, isActive = true) => ({ label, viewType: LEGACY_TAB_VIEW_TYPE, isActive });
const textTab = (file, isActive = true) => ({ label: path.basename(file), uri: file, isActive });
/** Wait until a registry write has run (writes are queued behind each other). */
const settled = () => h.sleep(15);
const editorEntry = (artifact, column) => (column === undefined ? { artifact, title: path.basename(artifact), kind: 'editor' } : { artifact, title: path.basename(artifact), column, kind: 'editor' });

/** A diagram on the Stage 1 case: the window's folder is the parent of the folder the artifact cites from. */
async function parentFolderPanel(options = {}) {
  const document = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  const fixture = await h.openPanel({ raw: document, files: { 'copy/source.py': 'fit()\n' }, artifactName: 'copy/run.mlview.json', ...options });
  fixtures.push(fixture);
  assert.deepEqual(h.lastBanner(fixture.panel).codes, ['root-hint']);
  // VS Code places the Beside editor in group 2 and reports it.
  fixture.panel.__setViewState({ viewColumn: 2 });
  await h.waitFor(() => entry(fixture.ctx.globalState)?.panels[0]?.column === 2, 'the diagram\'s column was not recorded');
  return fixture;
}

/** A second artifact, a copy of the first, shown by the same host; its document gets `title`. */
async function openCopy(fixture, name, { title, column } = {}) {
  const file = path.join(path.dirname(fixture.artifact), name);
  const document = JSON.parse(fs.readFileSync(fixture.artifact, 'utf8'));
  if (title) document.title = title;
  fs.writeFileSync(file, JSON.stringify(document));
  await fixture.controller.open(vscode.Uri.file(file));
  const panel = vscode.__recorded.panels.at(-1);
  panel.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(panel).length === 1, 'the copy was not shown');
  if (column) panel.__setViewState({ viewColumn: column });
  await settled();
  return { file, panel };
}

/**
 * The restart: the old host shuts down (its diagrams' tabs stay open, dead) and a new host
 * activates in the same window, with the same global state and session. `groups` are the tabs
 * VS Code shows then; `folders` the workspace folders after the restart. VS Code closes an emptied
 * group, and a text document shown in a group gets a tab there.
 */
function restart(fixture, groups, { folders, settleMs = SETTLE } = {}) {
  fixture.controller.dispose();
  if (folders) vscode.__setWorkspaceFolders(folders);
  const tabGroups = vscode.__setTabGroups(groups);
  vscode.__setCloseEmptyGroups(true);
  vscode.__setShownEditorsTabbed(true);
  // Only the new host's opens count.
  vscode.__recorded.openWith.length = 0;
  const logger = h.log();
  const controller = new api.AuthoredDiagramController(h.context(fixture.ctx.globalState), logger, undefined, undefined, settleMs);
  controller.register();
  fixtures.push({ controller });
  return { controller, tabGroups, logger };
}

/** Stand in for VS Code's `updateWorkspaceFolders` in a single-folder window, which stops the host before it changes the folders. */
function stopsTheHost(fixture, answer = true) {
  const calls = [];
  const original = vscode.workspace.updateWorkspaceFolders;
  vscode.workspace.updateWorkspaceFolders = (start, deleteCount, ...folders) => {
    calls.push({ start, deleteCount, folders, stored: fixture.ctx.globalState.persisted.get(KEY) });
    return answer;
  };
  restores.push(() => { vscode.workspace.updateWorkspaceFolders = original; });
  return calls;
}

const created = () => vscode.__recorded.panels.length;
const initArtifact = (panel) => panel.posted.find((m) => m.type === 'init')?.artifact;
const opens = () => vscode.__recorded.openWith.map((call) => [call.uri.fsPath, call.viewType, call.options.viewColumn, call.options.preserveFocus, call.options.preview]);
const tabNames = (group) => group.tabs.map((tab) => tab.label + (tab.isActive ? '*' : ''));

test('the registry lists each open diagram under the window session, with its file and kind, and follows moves and closes', async () => {
  const other = { at: Date.now(), panels: [{ artifact: '/elsewhere/x.mlview.json', title: 'MLView: X', column: 1 }] };
  const fixture = await parentFolderPanel({ globalState: vscode.__memento({ [KEY]: { 'another-window': other } }) });
  const state = fixture.ctx.globalState;
  assert.deepEqual(entry(state).panels, [editorEntry(fixture.artifact, 2)]);
  const { file, panel } = await openCopy(fixture, 'second.mlview.json', { title: 'Second' });
  assert.deepEqual(entry(state).panels, [editorEntry(fixture.artifact, 2), editorEntry(file, 2)]);
  // A column VS Code has not reported is left out.
  panel.__setViewState({ viewColumn: 0 });
  await h.waitFor(() => entry(state).panels[1].column === undefined, 'an unreported column was recorded');
  assert.deepEqual(entry(state).panels, [editorEntry(fixture.artifact, 2), editorEntry(file)]);
  // A new revision with another title: the tab keeps the file's name, so the entry is unchanged.
  const document = JSON.parse(fs.readFileSync(file, 'utf8'));
  document.title = 'Renamed';
  document.revision = { id: 'r2', parent: 'r1' };
  h.writeJson(file, document);
  await h.diskEvent(panel, 'change', file);
  assert.equal(h.workflows(panel).at(-1).document.title, 'Renamed');
  await settled();
  assert.deepEqual(entry(state).panels[1], editorEntry(file));
  // The tab moved to group 3.
  panel.__setViewState({ viewColumn: 3 });
  await h.waitFor(() => entry(state).panels[1].column === 3, 'the move was not recorded');
  // Closing the tabs removes them; the last one removes the session.
  fixture.panel.dispose();
  await h.waitFor(() => entry(state).panels.length === 1, 'the closed diagram stayed registered');
  assert.equal(entry(state).panels[0].artifact, file);
  panel.dispose();
  await h.waitFor(() => entry(state) === undefined, 'the session stayed registered');
  assert.deepEqual(state.get(KEY), { 'another-window': other }, 'another window\'s entry is kept');
});

test('shutting the host down keeps the registry: the tabs stay open for the next host', async () => {
  const fixture = await parentFolderPanel();
  const state = fixture.ctx.globalState;
  const updates = state.updates.length;
  fixture.controller.dispose();
  await settled();
  assert.equal(state.updates.length, updates, 'nothing is written while the host shuts down');
  assert.equal(entry(state).panels.length, 1);
});

test('the root hint\'s Add folder stores the registry before VS Code adds the folder', async () => {
  // The window stores a global state update a little after the call, as VS Code does.
  const fixture = await parentFolderPanel({ globalState: vscode.__memento({}, { delayMs: 30 }) });
  // The latest change is still on its way to the window when the reader clicks.
  fixture.panel.__setViewState({ viewColumn: 1 });
  const calls = stopsTheHost(fixture);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => calls.length === 1, 'the folder was not added');
  const [call] = calls;
  assert.equal(call.start, 1);
  assert.equal(call.deleteCount, 0);
  assert.equal(call.folders[0].uri.fsPath, path.join(fixture.root, 'copy'));
  assert.deepEqual(call.stored?.['mock-session']?.panels, [editorEntry(fixture.artifact, 1)], 'the window had the registry, up to date, before the folder was added');
});

test('after Add folder restarts the host, the dead diagram in front is reopened in its group, validated against the added folder', async () => {
  const fixture = await parentFolderPanel();
  stopsTheHost(fixture);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await settled();
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [editorTab(fixture.artifact)] }
  ], { folders: [fixture.root, path.join(fixture.root, 'copy')] });
  const [dead] = tabGroups[1].tabs;
  const first = controller.recoverAfterRestart();
  await h.sleep(SETTLE / 4);
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'nothing happens before the settle delay');
  assert.equal(await first, 1);
  assert.equal(created(), before + 1, 'one new diagram');
  const reopened = vscode.__recorded.panels.at(-1);
  assert.equal(reopened.viewType, 'mlview.diagram');
  assert.equal(reopened.viewColumn, 2, 'in the dead tab\'s group');
  assert.deepEqual(opens(), [[fixture.artifact, 'mlview.diagram', 2, true, false]]);
  // The dead tab was alone in group 2: the file's text editor held the group open meanwhile.
  assert.equal(vscode.__recorded.shownDocuments.length, 1);
  const { document, options } = vscode.__recorded.shownDocuments[0];
  assert.equal(document.uri.fsPath, fixture.artifact);
  assert.deepEqual(options, { viewColumn: 2, preserveFocus: true, preview: true });
  const closes = vscode.__recorded.closedTabs;
  assert.deepEqual(closes[0].tabs, [dead], 'the dead tab closes first');
  assert.equal(closes[0].preserveFocus, true);
  assert.equal(closes[0].panels, before, 'before the diagram opens (VS Code would only bring the dead tab to the front)');
  assert.equal(closes.length, 2);
  assert.equal(closes[1].tabs[0].input.uri.fsPath, fixture.artifact, 'then the text editor that held the group');
  assert.equal(closes[1].panels, before + 1);
  assert.equal(tabGroups.length, 2, 'both groups stay');
  assert.deepEqual(vscode.window.tabGroups.all[1].tabs, [reopened.tab]);
  assert.deepEqual(tabNames(vscode.window.tabGroups.all[0]), ['train.py*'], 'the text tab stays');
  assert.equal(vscode.__tabListeners(), 0, 'nothing is left to find: the recovery stops');
  reopened.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(reopened).length === 1, 'the new diagram showed nothing');
  assert.equal(h.lastBanner(reopened).message, '', 'no root hint: the added folder owns the artifact');
  assert.equal(initArtifact(reopened), fixture.artifact);
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels, [editorEntry(fixture.artifact, 2)]);
});

test('a dead diagram alone in the first group comes back there, not in the next group', async () => {
  // MEASURED live (VS Code 1.139, a probe extension): closing the dead tab first removed the empty
  // group 1, and the diagram reopened in column 1, which was the code's group by then.
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  await h.waitFor(() => entry(fixture.ctx.globalState)?.panels[0]?.column === 1, 'the move was not recorded');
  const { controller } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(fixture.artifact)] },
    { viewColumn: 2, isActive: true, tabs: [textTab(path.join(fixture.root, 'other.py'))] }
  ]);
  assert.equal(await controller.recoverAfterRestart(), 1);
  const groups = vscode.window.tabGroups.all;
  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map(tabNames), [['run.mlview.json*'], ['other.py*']]);
  assert.equal(groups[0].tabs[0].panel, vscode.__recorded.panels.at(-1));
});

test('a dead diagram that shares its group closes and reopens there, with no text editor in between', async () => {
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  await h.waitFor(() => entry(fixture.ctx.globalState)?.panels[0]?.column === 1, 'the move was not recorded');
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'), false), editorTab(fixture.artifact)] }
  ]);
  const [, dead] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1);
  assert.equal(vscode.__recorded.shownDocuments.length, 0);
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[dead]]);
  assert.deepEqual(tabNames(vscode.window.tabGroups.all[0]), ['train.py', 'run.mlview.json*']);
});

test('a tab behind others is left alone until it comes to the front; a restored tab VS Code resolves is never closed', async () => {
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  const second = await openCopy(fixture, 'second.mlview.json', { column: 1 });
  const third = await openCopy(fixture, 'third.mlview.json', { title: 'Third', column: 2 });
  // Never shown since the window loaded: nothing in this session registered it.
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => [path.basename(p.artifact), p.column]), [
    ['run.mlview.json', 1], ['second.mlview.json', 1], ['third.mlview.json', 2]
  ]);
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(lazyArtifact, false), editorTab(second.file, false), editorTab(fixture.artifact, true)] },
    { viewColumn: 2, tabs: [editorTab(third.file, false), textTab(path.join(fixture.root, 'train.py'))] }
  ]);
  const [lazy, deadSecond, deadFirst] = tabGroups[0].tabs;
  const [deadThird, text] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1, 'only the front dead tab is replaced at first');
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[deadFirst]]);
  const first = vscode.__recorded.panels.at(-1);
  assert.equal(first.viewColumn, 1);
  first.fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(first), fixture.artifact);
  assert.ok(tabGroups[0].tabs.includes(lazy) && tabGroups[0].tabs.includes(deadSecond), 'the tabs behind are left alone');
  assert.equal(text.isActive, true, 'group 2 keeps its front tab: nothing is opened over it');
  assert.ok(tabGroups[1].tabs.includes(deadThird));

  // The restored tab comes to the front, and VS Code resolves it a little later.
  vscode.__activateTab(lazy);
  await h.sleep(SETTLE / 4);
  const resolved = await vscode.__resolveCustomTab(lazy);
  await h.sleep(SETTLE * 2);
  assert.equal(resolved.disposed, false, 'the resolved tab is not closed');
  assert.equal(vscode.__recorded.closedTabs.length, 1, 'no tab was closed');

  // The dead tab behind comes to the front: it takes the remaining entry of its file.
  vscode.__activateTab(deadSecond);
  await h.waitFor(() => vscode.__recorded.closedTabs.length === 2, 'the dead tab was not replaced when it came to the front');
  assert.deepEqual(vscode.__recorded.closedTabs[1].tabs, [deadSecond]);
  const replacement = vscode.__recorded.panels.at(-1);
  replacement.fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(replacement), second.file);
  assert.equal(replacement.viewColumn, 1);
  assert.notEqual(vscode.__tabListeners(), 0, 'a dead tab is still behind in group 2');

  vscode.__activateTab(deadThird);
  await h.waitFor(() => vscode.__recorded.closedTabs.length === 3, 'the third dead tab was not replaced');
  const thirdPanel = vscode.__recorded.panels.at(-1);
  thirdPanel.fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(thirdPanel), third.file);
  assert.equal(thirdPanel.viewColumn, 2);
  assert.equal(created(), before + 4, 'three replacements and the resolved tab');
  assert.equal(vscode.__recorded.shownDocuments.length, 0, 'no dead tab was alone in its group');
  await h.waitFor(() => vscode.__tabListeners() === 0, 'the recovery did not stop');
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => path.basename(p.artifact)).sort(), ['lazy.mlview.json', 'run.mlview.json', 'second.mlview.json', 'third.mlview.json']);
});

test('two dead diagrams of one file come back each in its own group', async () => {
  const fixture = await parentFolderPanel();
  // VS Code's Split Editor: a second diagram editor of the same file, in group 1.
  const split = vscode.__setTabGroups([{ viewColumn: 1, tabs: [] }]);
  await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(fixture.artifact), 'mlview.diagram', { viewColumn: 1 });
  assert.equal(split[0].tabs.length, 1);
  vscode.__setTabGroups([]);
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => p.column), [2, 1]);
  const before = created();
  const { controller } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(fixture.artifact)] },
    { viewColumn: 2, tabs: [editorTab(fixture.artifact)] }
  ]);
  assert.equal(await controller.recoverAfterRestart(), 2);
  const opened = vscode.__recorded.panels.slice(before);
  assert.deepEqual(opened.map((panel) => [panel.viewColumn, panel.customUri.fsPath]), [[1, fixture.artifact], [2, fixture.artifact]]);
  assert.deepEqual(vscode.window.tabGroups.all.map(tabNames), [['run.mlview.json*'], ['run.mlview.json*']]);
});

test('a dead diagram whose file was opened again elsewhere since the restart still comes back in its group', async () => {
  const fixture = await parentFolderPanel();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, isActive: true, tabs: [textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [editorTab(fixture.artifact)] }
  ]);
  const recovery = controller.recoverAfterRestart();
  // MLView: Open Generated Diagram, before the settle delay ends: VS Code opens it beside group 1, in a new group 3.
  await controller.open(vscode.Uri.file(fixture.artifact));
  const shown = vscode.__recorded.panels.at(-1);
  assert.equal(shown.viewColumn, 3);
  assert.equal(await recovery, 1, 'the dead tab in group 2 is reopened there: several diagrams of one file are allowed');
  assert.equal(tabGroups[1].tabs[0].panel, vscode.__recorded.panels.at(-1));
  assert.equal(shown.disposed, false);
});

test('an entry with no tab left is dropped (the reader closed it); a front tab no entry matches is left alone', async () => {
  const fixture = await parentFolderPanel();
  await openCopy(fixture, 'gone.mlview.json', { title: 'Gone' });
  const behindFile = (await openCopy(fixture, 'behind.mlview.json', { title: 'Behind' })).file;
  const { controller, tabGroups, logger } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(behindFile, false), editorTab(path.join(fixture.root, 'copy', 'unknown.mlview.json'), true)] }
  ]);
  const [behind, unknown] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'the front tab matches no entry: left alone');
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => path.basename(p.artifact)), ['behind.mlview.json'], 'the entries with no tab are dropped');
  // Another tab change: the unmatched front tab is logged once only.
  vscode.__activateTab(unknown);
  await h.sleep(SETTLE * 2);
  assert.equal(logger.infos.filter((line) => /matches no open diagram/.test(line)).length, 1);
  assert.notEqual(vscode.__tabListeners(), 0, 'still watching for the tab behind');
  // The reader closes the tab behind: nothing is left to find.
  await vscode.window.tabGroups.close(behind);
  await h.waitFor(() => vscode.__tabListeners() === 0, 'the recovery did not stop');
  await settled();
  assert.equal(entry(fixture.ctx.globalState), undefined);
});

test('a registered diagram no longer in the workspace: its dead tab is closed and nothing is opened', async () => {
  const fixture = await parentFolderPanel();
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [editorTab(fixture.artifact)] }
  ], { folders: [path.join(fixture.root, 'elsewhere')] });
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(created(), before);
  assert.equal(vscode.__recorded.openWith.length, 0);
  assert.equal(tabGroups[1].tabs.length, 0);
});

test('only this window\'s session is used; other sessions are pruned after 14 days or beyond the most recent 20', async () => {
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  const panels = [{ artifact: '/x/run.mlview.json', title: 'run.mlview.json', kind: 'editor' }];
  const sessions = { 'another-window': { at: now - day, panels }, old: { at: now - api.OPEN_PANELS_TTL_MS - day, panels }, future: { at: now + api.OPEN_PANELS_TTL_MS + day, panels } };
  for (let i = 0; i < api.MAX_OTHER_SESSIONS + 3; i++) sessions[`reload-${i}`] = { at: now - 2 * day - i * 1000, panels };
  const fixture = await parentFolderPanel({ globalState: vscode.__memento({ [KEY]: sessions }) });
  const state = fixture.ctx.globalState;
  const kept = Object.keys(state.get(KEY)).filter((session) => session !== 'mock-session');
  assert.equal(kept.length, api.MAX_OTHER_SESSIONS);
  assert.ok(kept.includes('another-window'), 'the most recent other session is kept');
  assert.ok(!kept.includes('old') && !kept.includes('future'), 'sessions 14 days away are dropped');
  assert.ok(!kept.includes(`reload-${api.MAX_OTHER_SESSIONS + 2}`), 'the oldest beyond the limit are dropped');
  // A host in another window (another session) with a dead-looking front tab of the same file.
  fixture.controller.dispose();
  vscode.env.sessionId = 'third-window';
  const before = created();
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 1, tabs: [editorTab(fixture.artifact)] }]);
  assert.equal(await controller.recoverAfterRestart(), 0);
  await h.sleep(SETTLE * 2);
  assert.equal(created(), before);
  assert.equal(tabGroups[0].tabs.length, 1, 'another window\'s entry is never used');
  assert.equal(vscode.__tabListeners(), 0);
});

test('a malformed registry is ignored and repaired', async () => {
  const fixture = await parentFolderPanel();
  const state = fixture.ctx.globalState;
  fixture.controller.dispose();
  await state.update(KEY, 'not an object');
  let { controller } = restart(fixture, [{ viewColumn: 1, tabs: [editorTab(fixture.artifact)] }]);
  assert.equal(await controller.recoverAfterRestart(), 0);
  await settled();
  assert.equal(state.get(KEY), undefined, 'the value is deleted');
  controller.dispose();
  await state.update(KEY, {
    'mock-session': { at: 'yesterday', panels: [] },
    good: { at: Date.now(), panels: [{ artifact: 7 }, { artifact: '/a/b.mlview.json', title: 'MLView: B', column: -2 }, null, { artifact: '/a/c.mlview.json', title: 'c.mlview.json', column: 3, kind: 'editor' }, { artifact: '/a/d.mlview.json', title: 'd', kind: 'tab' }] }
  });
  ({ controller } = restart(fixture, [{ viewColumn: 1, tabs: [editorTab(fixture.artifact)] }]));
  assert.equal(await controller.recoverAfterRestart(), 0);
  await settled();
  assert.equal(vscode.__recorded.closedTabs.length, 0);
  assert.deepEqual(state.get(KEY), { good: { at: state.get(KEY).good.at, panels: [
    { artifact: '/a/b.mlview.json', title: 'MLView: B' },
    { artifact: '/a/c.mlview.json', title: 'c.mlview.json', column: 3, kind: 'editor' },
    { artifact: '/a/d.mlview.json', title: 'd' }
  ] } });
});

test('multi-root window: Add folder validates in place, with the same diagram', async () => {
  const fixture = await parentFolderPanel();
  vscode.__setWorkspaceFile(path.join(fixture.root, 'work.code-workspace'));
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.workspaceFolderUpdates.length === 1, 'no folder was added');
  await h.waitFor(() => h.lastBanner(fixture.panel).message === '', 'the diagram did not validate again in place');
  assert.equal(created(), 1, 'the same diagram');
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => p.artifact), [fixture.artifact]);
});

test('VS Code refuses the folder: a warning, and the diagram stays registered', async () => {
  const fixture = await parentFolderPanel();
  stopsTheHost(fixture, false);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.messages.some((m) => m[1] === 'MLView: VS Code did not add the folder to the workspace.'), 'no warning');
  assert.equal(entry(fixture.ctx.globalState).panels.length, 1);
});

test('the root hint has no notification: the diagram\'s notice carries its actions', async () => {
  await parentFolderPanel();
  assert.equal(vscode.__recorded.messages.length, 0);
});

test('Reload Window: the new session finds no entry and closes nothing; VS Code resolves the restored diagrams', async () => {
  const fixture = await parentFolderPanel();
  const state = fixture.ctx.globalState;
  fixture.controller.dispose();
  // A reload starts a new session; VS Code restores the tabs and resolves the front one.
  vscode.env.sessionId = 'reloaded';
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(fixture.artifact, true)] },
    { viewColumn: 2, tabs: [editorTab(fixture.artifact, false), textTab(path.join(fixture.root, 'train.py'))] }
  ]);
  const [front] = tabGroups[0].tabs;
  const [behind] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__tabListeners(), 0, 'nothing to watch');
  const resolved = await vscode.__resolveCustomTab(front);
  resolved.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(resolved).length === 1, 'the resolved diagram showed nothing');
  assert.equal(initArtifact(resolved), fixture.artifact);
  assert.equal(vscode.__recorded.closedTabs.length, 0);
  assert.ok(tabGroups[1].tabs.includes(behind), 'the restored tab behind stays');
  await settled();
  assert.deepEqual(entry(state, 'reloaded').panels, [editorEntry(fixture.artifact, 1)]);
  assert.ok(entry(state, 'mock-session'), 'the earlier session\'s entry waits for pruning');
  // The tab behind is a second diagram of the same file; both follow the file.
  vscode.__activateTab(behind);
  const second = await vscode.__resolveCustomTab(behind);
  second.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(second).length === 1, 'the second diagram showed nothing');
  await h.diskEvent(resolved, 'change', fixture.artifact);
  assert.ok(h.banners(second).some((m) => (m.codes || [])[0] === 'checking'), 'both diagrams get disk events');
});

test('an earlier MLView\'s dead panel tab (an entry without kind) comes back as the diagram editor in its group', async () => {
  const fixture = await parentFolderPanel();
  fixture.controller.dispose();
  // What an earlier MLView's host left in the registry.
  await fixture.ctx.globalState.update(KEY, { 'mock-session': { at: Date.now(), panels: [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 2 }] } });
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [legacyTab('MLView: Authored')] }
  ]);
  const [dead] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1);
  assert.deepEqual(opens(), [[fixture.artifact, 'mlview.diagram', 2, true, false]]);
  const [close] = vscode.__recorded.closedTabs;
  assert.deepEqual(close.tabs, [dead]);
  assert.equal(close.panels, before + 1, 'the diagram editor opens before the old tab closes, so the group stays');
  assert.equal(vscode.__recorded.shownDocuments.length, 0, 'no text editor needed');
  assert.deepEqual(vscode.window.tabGroups.all.map(tabNames), [['train.py*'], ['run.mlview.json*']]);
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels, [editorEntry(fixture.artifact, 2)]);
});

test('an earlier MLView\'s dead panel tab is matched by title, never by its group alone', async () => {
  const fixture = await parentFolderPanel();
  const other = path.join(path.dirname(fixture.artifact), 'other.mlview.json');
  fs.copyFileSync(fixture.artifact, other);
  fixture.controller.dispose();
  await fixture.ctx.globalState.update(KEY, { 'mock-session': { at: Date.now(), panels: [
    { artifact: fixture.artifact, title: 'MLView: Authored', column: 2 }, { artifact: other, title: 'MLView: Other', column: 1 }
  ] } });
  // Group 2, where the Authored diagram was, now shows the Other diagram's dead tab in front, and
  // a diagram tab no entry has is in front of group 3.
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 2, tabs: [legacyTab('MLView: Authored', false), legacyTab('MLView: Other', true)] },
    { viewColumn: 3, tabs: [legacyTab('MLView: Unknown', true)] }
  ]);
  const [authoredBehind, otherFront] = tabGroups[0].tabs;
  const [unknown] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1);
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[otherFront]]);
  assert.deepEqual(opens(), [[other, 'mlview.diagram', 2, true, false]], 'the tab gets the entry with its title, not the entry of its group');
  assert.ok(tabGroups[0].tabs.includes(authoredBehind));
  assert.ok(tabGroups[1].tabs.includes(unknown), 'a front tab with no entry of its title is left alone');
});

test('an earlier MLView\'s panel that VS Code revives during the recovery is reopened once, by the serializer', async () => {
  const fixture = await parentFolderPanel();
  fixture.controller.dispose();
  await fixture.ctx.globalState.update(KEY, { 'mock-session': { at: Date.now(), panels: [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 1 }] } });
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 1, tabs: [legacyTab('MLView: Authored')] }]);
  const [restored] = tabGroups[0].tabs;
  // VS Code takes longer to open the diagram editor than the settle delay.
  const original = vscode.commands.executeCommand;
  vscode.commands.executeCommand = async (id, ...args) => { if (id === 'vscode.openWith') await h.sleep(SETTLE * 3); return original(id, ...args); };
  restores.push(() => { vscode.commands.executeCommand = original; });
  const recovery = controller.recoverAfterRestart();
  const revived = vscode.__reviveTab(restored);
  const migration = vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: fixture.artifact });
  assert.equal(await recovery, 0, 'the tab being reopened is not taken for a dead one');
  await migration;
  assert.equal(revived.disposed, true);
  assert.equal(vscode.__recorded.openWith.length, 1, 'one diagram editor');
  await h.waitFor(() => vscode.__tabListeners() === 0, 'the entry of the closed tab was not dropped');
});

test('the settle delay counts from the latest tab change: a restored tab resolved within it is not closed', async () => {
  const fixture = await parentFolderPanel();
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  // The registry has an entry for the same file in group 1 (a diagram that was open and is closed now,
  // its entry kept by an earlier host), so only the timing keeps the restored tab alive.
  fixture.controller.dispose();
  await fixture.ctx.globalState.update(KEY, { 'mock-session': { at: Date.now(), panels: [editorEntry(lazyArtifact, 1)] } });
  // A long delay keeps the timing margins wide on a busy machine.
  const settleMs = 200;
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [editorTab(lazyArtifact, false), textTab(path.join(fixture.root, 'train.py'))] }
  ], { settleMs });
  const [lazy] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  // The restored tab comes to the front, and a second tab event follows before the delay ends.
  vscode.__activateTab(lazy);
  await h.sleep(settleMs * 0.6);
  vscode.__activateTab(lazy);
  await h.sleep(settleMs * 0.6);
  // VS Code resolves it after the delay counted from the first event, within the one from the second.
  const resolved = await vscode.__resolveCustomTab(lazy);
  await h.sleep(settleMs * 1.5);
  assert.equal(resolved.disposed, false, 'the resolved tab is not closed');
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'no tab was judged dead before the delay from the latest change ended');
});

test('activation runs the recovery', async () => {
  const extension = require(path.join(__dirname, '..', 'out', 'extension.js'));
  const fixture = await parentFolderPanel();
  fixture.controller.dispose();
  const [, group] = vscode.__setTabGroups([{ viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'))] }, { viewColumn: 2, tabs: [editorTab(fixture.artifact)] }]);
  vscode.__setShownEditorsTabbed(true);
  const before = created();
  const ctx = { ...h.context(fixture.ctx.globalState), extension: { packageJSON: { version: '0.3.0' } } };
  extension.activate(ctx);
  try {
    await h.waitFor(() => vscode.__recorded.closedTabs.length === 2, 'activation did not replace the dead tab', api.RECOVERY_SETTLE_MS + 2000);
    assert.equal(created(), before + 1);
    assert.deepEqual(group.tabs, [vscode.__recorded.panels.at(-1).tab]);
  } finally {
    extension.deactivate();
  }
});
