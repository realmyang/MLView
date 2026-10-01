'use strict';
/**
 * Extension host restarts inside one window ("Developer: Restart Extension Host", an extension
 * update, a single-folder window becoming a multi-root workspace through the root hint's "Add
 * folder" or VS Code's own "Add Folder to Workspace...", "Save Workspace As..."). The open panels
 * keep their tabs, but VS Code never revives them: it calls the serializer only for tabs it
 * restores when a window loads. Each host keeps a registry of its open panels in the global
 * state, under the window's session; the next host in the same window replaces each dead tab with
 * a new panel for the same artifact in the same group.
 *
 * A dead tab looks exactly like a restored tab that VS Code has not shown yet, so only the front
 * tab of a group is judged, after a settle delay in which VS Code revives a restored tab through
 * the serializer. Reload Window starts a new session and goes through the serializer.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;

const KEY = api.OPEN_PANELS_KEY;
const TAB_VIEW_TYPE = 'mainThreadWebview-mlview.authoredDiagram';
/** The settle delay of the hosts started by these tests (the product's is `RECOVERY_SETTLE_MS`). */
const SETTLE = 40;
const fixtures = [];
const restores = [];
test.afterEach(() => {
  for (const restore of restores.splice(0)) restore();
  h.cleanup(fixtures);
});

const entry = (state, session = 'mock-session') => state.get(KEY)?.[session];
const deadTab = (label, isActive = true) => ({ label, viewType: TAB_VIEW_TYPE, isActive });
const textTab = (file, isActive = true) => ({ label: path.basename(file), uri: file, isActive });
/** Wait until a registry write has run (writes are queued behind each other). */
const settled = () => h.sleep(15);

/** A panel on the Stage 1 case: the window's folder is the parent of the folder the artifact cites from. */
async function parentFolderPanel(options = {}) {
  const document = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  const fixture = await h.openPanel({ raw: document, files: { 'copy/source.py': 'fit()\n' }, artifactName: 'copy/run.mlview.json', ...options });
  fixtures.push(fixture);
  assert.deepEqual(h.lastBanner(fixture.panel).codes, ['root-hint']);
  // VS Code places the Beside panel in group 2 and reports it.
  fixture.panel.__setViewState({ viewColumn: 2 });
  await h.waitFor(() => entry(fixture.ctx.globalState)?.panels[0]?.column === 2, 'the panel\'s column was not recorded');
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
  await h.waitFor(() => panel.title === `MLView: ${document.title}`, 'the copy was not shown');
  if (column) panel.__setViewState({ viewColumn: column });
  await settled();
  return { file, panel };
}

/**
 * The restart: the old host shuts down (its panels' tabs stay open, dead) and a new host
 * activates in the same window, with the same global state and session. `groups` are the tabs
 * VS Code shows then; `folders` the workspace folders after the restart.
 */
function restart(fixture, groups, { folders, settleMs = SETTLE } = {}) {
  fixture.controller.dispose();
  if (folders) vscode.__setWorkspaceFolders(folders);
  const tabGroups = vscode.__setTabGroups(groups);
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

test('the registry lists each open panel under the window session and follows retitles, moves and closes', async () => {
  const other = { at: Date.now(), panels: [{ artifact: '/elsewhere/x.mlview.json', title: 'MLView: X', column: 1 }] };
  const fixture = await parentFolderPanel({ globalState: vscode.__memento({ [KEY]: { 'another-window': other } }) });
  const state = fixture.ctx.globalState;
  assert.deepEqual(entry(state).panels, [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 2 }]);
  const { file, panel } = await openCopy(fixture, 'second.mlview.json', { title: 'Second' });
  assert.deepEqual(entry(state).panels.map((p) => [p.artifact, p.title]), [[fixture.artifact, 'MLView: Authored'], [file, 'MLView: Second']]);
  assert.equal(entry(state).panels[1].column, undefined, 'a column VS Code has not reported (Beside) is left out');
  // A new revision with another title.
  const document = JSON.parse(fs.readFileSync(file, 'utf8'));
  document.title = 'Renamed';
  document.revision = { id: 'r2', parent: 'r1' };
  h.writeJson(file, document);
  await h.diskEvent(panel, 'change', file);
  await h.waitFor(() => entry(state).panels[1].title === 'MLView: Renamed', 'the new title was not recorded');
  // The tab moved to group 3.
  panel.__setViewState({ viewColumn: 3 });
  await h.waitFor(() => entry(state).panels[1].column === 3, 'the move was not recorded');
  // Closing the tabs removes them; the last one removes the session.
  fixture.panel.dispose();
  await h.waitFor(() => entry(state).panels.length === 1, 'the closed panel stayed registered');
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
  assert.deepEqual(call.stored?.['mock-session']?.panels, [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 1 }], 'the window had the registry, up to date, before the folder was added');
});

test('after Add folder restarts the host, the dead tab in front is replaced in its group, validated against the added folder', async () => {
  const fixture = await parentFolderPanel();
  stopsTheHost(fixture);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await settled();
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [deadTab('MLView: Authored')] }
  ], { folders: [fixture.root, path.join(fixture.root, 'copy')] });
  const [dead] = tabGroups[1].tabs;
  const first = controller.recoverAfterRestart();
  await h.sleep(SETTLE / 4);
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'nothing happens before the settle delay');
  assert.equal(await first, 1);
  assert.equal(created(), before + 1, 'one new panel');
  const reopened = vscode.__recorded.panels.at(-1);
  assert.equal(reopened.viewColumn, 2, 'in the dead tab\'s group');
  const [close] = vscode.__recorded.closedTabs;
  assert.deepEqual(close.tabs, [dead], 'only the dead tab is closed');
  assert.equal(close.preserveFocus, true);
  assert.equal(close.panels, before + 1, 'the new panel opens before the dead tab closes, so the group stays');
  assert.deepEqual(tabGroups[1].tabs, [reopened.tab]);
  assert.equal(tabGroups[0].tabs.length, 1, 'the text tab stays');
  assert.equal(vscode.__tabListeners(), 0, 'nothing is left to find: the recovery stops');
  reopened.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(reopened).length === 1, 'the new panel showed no diagram');
  assert.equal(h.lastBanner(reopened).message, '', 'no root hint: the added folder owns the artifact');
  assert.equal(initArtifact(reopened), fixture.artifact);
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels, [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 2 }]);
});

test('a tab behind others is left alone until it comes to the front; a restored tab VS Code revives is never closed', async () => {
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  const second = await openCopy(fixture, 'second.mlview.json', { column: 1 });
  const third = await openCopy(fixture, 'third.mlview.json', { title: 'Third', column: 2 });
  // Same title as the first two, in the same group, but never shown since the window loaded:
  // nothing in this session registered it.
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => [path.basename(p.artifact), p.title, p.column]), [
    ['run.mlview.json', 'MLView: Authored', 1], ['second.mlview.json', 'MLView: Authored', 1], ['third.mlview.json', 'MLView: Third', 2]
  ]);
  const before = created();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Authored', false), deadTab('MLView: Authored', false), deadTab('MLView: Authored', true)] },
    { viewColumn: 2, tabs: [deadTab('MLView: Third', false), textTab(path.join(fixture.root, 'train.py'))] }
  ]);
  const [lazy, deadSecond, deadFirst] = tabGroups[0].tabs;
  const [deadThird, text] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1, 'only the front dead tab is replaced at first');
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[deadFirst]]);
  const first = vscode.__recorded.panels.at(-1);
  assert.equal(first.viewColumn, 1);
  first.fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(first), fixture.artifact, 'the first registered diagram of that title and group');
  assert.ok(tabGroups[0].tabs.includes(lazy) && tabGroups[0].tabs.includes(deadSecond), 'the tabs behind are left alone');
  assert.equal(text.isActive, true, 'group 2 keeps its front tab: nothing is opened over it');
  assert.ok(tabGroups[1].tabs.includes(deadThird));

  // The restored tab comes to the front, and VS Code revives it through the serializer a little later.
  vscode.__activateTab(lazy);
  await h.sleep(SETTLE / 4);
  const revived = vscode.__reviveTab(lazy);
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: lazyArtifact });
  await h.sleep(SETTLE * 2);
  assert.equal(revived.disposed, false, 'the revived tab is not closed');
  assert.equal(vscode.__recorded.closedTabs.length, 1, 'no tab was closed');

  // The dead tab behind comes to the front: it takes the remaining entry of its title.
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
  assert.equal(created(), before + 4, 'three replacements and the revived tab');
  await h.waitFor(() => vscode.__tabListeners() === 0, 'the recovery did not stop');
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => path.basename(p.artifact)).sort(), ['lazy.mlview.json', 'run.mlview.json', 'second.mlview.json', 'third.mlview.json']);
});

test('a revived tab whose group VS Code has not reported yet (column 0) is not taken for a dead tab', async () => {
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  await settled();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Authored', false), textTab(path.join(fixture.root, 'train.py'))] },
    { viewColumn: 2, tabs: [deadTab('MLView: Authored', false), textTab(path.join(fixture.root, 'other.py'))] }
  ]);
  const [lazy] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  // VS Code revives the restored tab with column 0 (live VS Code 1.139) and reports its group later.
  vscode.__activateTab(lazy);
  const revived = vscode.__reviveTab(lazy);
  revived.viewColumn = 0;
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: lazyArtifact });
  await h.sleep(SETTLE * 3);
  assert.equal(revived.disposed, false, 'the revived tab is not closed');
  assert.equal(vscode.__recorded.closedTabs.length, 0);
  revived.__setViewState({ viewColumn: 1 });
  await h.sleep(SETTLE * 2);
  assert.equal(vscode.__recorded.closedTabs.length, 0);
});

test('each dead front tab takes the entry of its own group when titles repeat', async () => {
  const fixture = await parentFolderPanel();
  const second = await openCopy(fixture, 'second.mlview.json', { column: 1 });
  // The registry lists the group-2 panel first.
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => p.column), [2, 1]);
  const before = created();
  const { controller } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Authored')] },
    { viewColumn: 2, tabs: [deadTab('MLView: Authored')] }
  ]);
  assert.equal(await controller.recoverAfterRestart(), 2);
  const opened = vscode.__recorded.panels.slice(before);
  for (const panel of opened) panel.fire({ v: 1, type: 'ready' });
  assert.deepEqual(opened.map((panel) => [panel.viewColumn, initArtifact(panel)]), [[1, second.file], [2, fixture.artifact]]);
});

test('a dead tab whose diagram was opened again since the restart is closed, without a second panel', async () => {
  const fixture = await parentFolderPanel();
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 2, tabs: [deadTab('MLView: Authored')] }]);
  const before = created();
  const recovery = controller.recoverAfterRestart();
  // MLView: Open Generated Diagram, before the settle delay ends; VS Code puts it in group 1.
  await controller.open(vscode.Uri.file(fixture.artifact));
  const shown = vscode.__recorded.panels.at(-1);
  shown.__setViewState({ viewColumn: 1 });
  assert.equal(await recovery, 0);
  assert.equal(created(), before + 1, 'only the panel the command opened, no second one');
  assert.equal(tabGroups[0].tabs.length, 0, 'the dead tab is closed');
  assert.equal(shown.disposed, false);
});

test('an entry whose title is on no tab is dropped (the reader closed it); a front tab no entry matches is left alone', async () => {
  const fixture = await parentFolderPanel();
  await openCopy(fixture, 'gone.mlview.json', { title: 'Gone' });
  await openCopy(fixture, 'behind.mlview.json', { title: 'Behind' });
  const { controller, tabGroups, logger } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Behind', false), deadTab('MLView: Unknown', true)] }
  ]);
  const [behind, unknown] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'the front tab matches no entry: left alone');
  await settled();
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => p.title), ['MLView: Behind'], 'the entries with no tab are dropped');
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
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 2, tabs: [deadTab('MLView: Authored')] }], { folders: [path.join(fixture.root, 'elsewhere')] });
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(created(), before);
  assert.equal(tabGroups[0].tabs.length, 0);
});

test('only this window\'s session is used; other sessions are pruned after 14 days or beyond the most recent 20', async () => {
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  const panels = [{ artifact: '/x/run.mlview.json', title: 'MLView: Authored' }];
  const sessions = { 'another-window': { at: now - day, panels }, old: { at: now - api.OPEN_PANELS_TTL_MS - day, panels }, future: { at: now + api.OPEN_PANELS_TTL_MS + day, panels } };
  for (let i = 0; i < api.MAX_OTHER_SESSIONS + 3; i++) sessions[`reload-${i}`] = { at: now - 2 * day - i * 1000, panels };
  const fixture = await parentFolderPanel({ globalState: vscode.__memento({ [KEY]: sessions }) });
  const state = fixture.ctx.globalState;
  const kept = Object.keys(state.get(KEY)).filter((session) => session !== 'mock-session');
  assert.equal(kept.length, api.MAX_OTHER_SESSIONS);
  assert.ok(kept.includes('another-window'), 'the most recent other session is kept');
  assert.ok(!kept.includes('old') && !kept.includes('future'), 'sessions 14 days away are dropped');
  assert.ok(!kept.includes(`reload-${api.MAX_OTHER_SESSIONS + 2}`), 'the oldest beyond the limit are dropped');
  // A host in another window (another session) with a dead-looking front tab of the same title.
  fixture.controller.dispose();
  vscode.env.sessionId = 'third-window';
  const before = created();
  const { controller, tabGroups } = restart(fixture, [{ viewColumn: 1, tabs: [deadTab('MLView: Authored')] }]);
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
  let { controller } = restart(fixture, [{ viewColumn: 1, tabs: [deadTab('MLView: Authored')] }]);
  assert.equal(await controller.recoverAfterRestart(), 0);
  await settled();
  assert.equal(state.get(KEY), undefined, 'the value is deleted');
  controller.dispose();
  await state.update(KEY, {
    'mock-session': { at: 'yesterday', panels: [] },
    good: { at: Date.now(), panels: [{ artifact: 7 }, { artifact: '/a/b.mlview.json', title: 'MLView: B', column: -2 }, null] }
  });
  ({ controller } = restart(fixture, [{ viewColumn: 1, tabs: [deadTab('MLView: Authored')] }]));
  assert.equal(await controller.recoverAfterRestart(), 0);
  await settled();
  assert.equal(vscode.__recorded.closedTabs.length, 0);
  assert.deepEqual(state.get(KEY), { good: { at: state.get(KEY).good.at, panels: [{ artifact: '/a/b.mlview.json', title: 'MLView: B' }] } });
});

test('multi-root window: Add folder validates in place, with the same panel', async () => {
  const fixture = await parentFolderPanel();
  vscode.__setWorkspaceFile(path.join(fixture.root, 'work.code-workspace'));
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.workspaceFolderUpdates.length === 1, 'no folder was added');
  await h.waitFor(() => h.lastBanner(fixture.panel).message === '', 'the panel did not validate again in place');
  assert.equal(created(), 1, 'the same panel');
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => p.artifact), [fixture.artifact]);
});

test('VS Code refuses the folder: a warning, and the panel stays registered', async () => {
  const fixture = await parentFolderPanel();
  stopsTheHost(fixture, false);
  fixture.panel.fire({ v: 1, type: 'workspaceHint', action: 'add' });
  await h.waitFor(() => vscode.__recorded.messages.some((m) => m[1] === 'MLView: VS Code did not add the folder to the workspace.'), 'no warning');
  assert.equal(entry(fixture.ctx.globalState).panels.length, 1);
});

test('the root hint has no notification: the panel\'s notice carries its actions', async () => {
  await parentFolderPanel();
  assert.equal(vscode.__recorded.messages.length, 0);
});

test('Reload Window: the new session finds no entry and closes nothing; the serializer revives the panel, one per artifact', async () => {
  const fixture = await parentFolderPanel();
  const state = fixture.ctx.globalState;
  fixture.controller.dispose();
  // A reload starts a new session; VS Code restores the tabs and revives the front one.
  vscode.env.sessionId = 'reloaded';
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Second', false), deadTab('MLView: Authored', true)] }
  ]);
  const [behind, front] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  assert.equal(vscode.__tabListeners(), 0, 'nothing to watch');
  const revived = vscode.__reviveTab(front);
  const serializer = vscode.__recorded.serializers.get('mlview.authoredDiagram');
  await serializer.deserializeWebviewPanel(revived, { viewport: { zoom: 2 }, artifact: fixture.artifact });
  revived.fire({ v: 1, type: 'ready' });
  await h.waitFor(() => h.workflows(revived).length === 1, 'the revived panel showed no diagram');
  assert.equal(initArtifact(revived), fixture.artifact);
  assert.equal(vscode.__recorded.closedTabs.length, 0);
  assert.ok(tabGroups[0].tabs.includes(behind), 'the restored tab behind stays');
  await settled();
  assert.deepEqual(entry(state, 'reloaded').panels, [{ artifact: fixture.artifact, title: 'MLView: Authored', column: 1 }]);
  assert.ok(entry(state, 'mock-session'), 'the earlier session\'s entry waits for pruning');
  // A second revived tab for the same artifact is closed; the shown panel keeps working.
  vscode.__activateTab(behind);
  const duplicate = vscode.__reviveTab(behind);
  await serializer.deserializeWebviewPanel(duplicate, { artifact: fixture.artifact });
  assert.equal(duplicate.disposed, true);
  assert.equal(duplicate.posted.length, 0);
  await h.diskEvent(revived, 'change', fixture.artifact);
  assert.ok(h.banners(revived).some((m) => (m.codes || [])[0] === 'checking'), 'the shown panel no longer gets disk events');
});

test('the settle delay counts from the latest tab change: a restored tab revived within it is not closed', async () => {
  const fixture = await parentFolderPanel();
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  await settled();
  // A long delay keeps the timing margins wide on a busy machine.
  const settleMs = 200;
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Authored', false), textTab(path.join(fixture.root, 'train.py'))] }
  ], { settleMs });
  const [lazy] = tabGroups[0].tabs;
  assert.equal(await controller.recoverAfterRestart(), 0);
  // The restored tab comes to the front, and a second tab event follows before the delay ends.
  vscode.__activateTab(lazy);
  await h.sleep(settleMs * 0.6);
  vscode.__activateTab(lazy);
  await h.sleep(settleMs * 0.6);
  // VS Code revives it after the delay counted from the first event, within the one from the second.
  const revived = vscode.__reviveTab(lazy);
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: lazyArtifact });
  await h.sleep(settleMs * 1.5);
  assert.equal(revived.disposed, false, 'the revived tab is not closed');
  assert.equal(vscode.__recorded.closedTabs.length, 0, 'no tab was judged dead before the delay from the latest change ended');
});

test('a front tab is matched by title, never by its group alone', async () => {
  const fixture = await parentFolderPanel();
  const other = await openCopy(fixture, 'other.mlview.json', { title: 'Other', column: 1 });
  assert.deepEqual(entry(fixture.ctx.globalState).panels.map((p) => [p.title, p.column]), [['MLView: Authored', 2], ['MLView: Other', 1]]);
  const before = created();
  // Group 2, where the Authored diagram was, now shows the Other diagram's dead tab in front, and
  // a diagram tab no entry has in front of group 3.
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 2, tabs: [deadTab('MLView: Authored', false), deadTab('MLView: Other', true)] },
    { viewColumn: 3, tabs: [deadTab('MLView: Unknown', true)] }
  ]);
  const [authoredBehind, otherFront] = tabGroups[0].tabs;
  const [unknown] = tabGroups[1].tabs;
  assert.equal(await controller.recoverAfterRestart(), 1);
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[otherFront]]);
  const opened = vscode.__recorded.panels.slice(before);
  assert.equal(opened.length, 1);
  opened[0].fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(opened[0]), other.file, 'the tab gets the entry with its title, not the entry of its group');
  assert.equal(opened[0].viewColumn, 2);
  assert.ok(tabGroups[0].tabs.includes(authoredBehind));
  assert.ok(tabGroups[1].tabs.includes(unknown), 'a front tab with no entry of its title is left alone');
});

test('a revived panel still at column 0 only covers a tab with its own title', async () => {
  const fixture = await parentFolderPanel();
  fixture.panel.__setViewState({ viewColumn: 1 });
  const third = await openCopy(fixture, 'third.mlview.json', { title: 'Third', column: 2 });
  const lazyArtifact = (await openCopy(fixture, 'lazy.mlview.json')).file;
  vscode.__recorded.panels.at(-1).dispose();
  await settled();
  const { controller, tabGroups } = restart(fixture, [
    { viewColumn: 1, tabs: [deadTab('MLView: Authored', true)] },
    { viewColumn: 2, tabs: [deadTab('MLView: Third', true)] }
  ], { settleMs: 200 });
  const [restored] = tabGroups[0].tabs;
  const [deadThird] = tabGroups[1].tabs;
  const recovery = controller.recoverAfterRestart();
  // VS Code revives group 1's tab before the delay ends, with column 0 (live VS Code 1.139).
  const revived = vscode.__reviveTab(restored);
  revived.viewColumn = 0;
  await vscode.__recorded.serializers.get('mlview.authoredDiagram').deserializeWebviewPanel(revived, { artifact: lazyArtifact });
  assert.equal(await recovery, 1, 'the Third tab is dead: the column-0 panel shows another title');
  assert.deepEqual(vscode.__recorded.closedTabs.map((c) => c.tabs), [[deadThird]]);
  const replacement = vscode.__recorded.panels.at(-1);
  replacement.fire({ v: 1, type: 'ready' });
  assert.equal(initArtifact(replacement), third.file);
  assert.equal(replacement.viewColumn, 2);
  assert.equal(revived.disposed, false, 'the revived tab is not closed');
});

test('activation runs the recovery', async () => {
  const extension = require(path.join(__dirname, '..', 'out', 'extension.js'));
  const fixture = await parentFolderPanel();
  fixture.controller.dispose();
  const [group] = vscode.__setTabGroups([{ viewColumn: 2, tabs: [deadTab('MLView: Authored')] }]);
  const before = created();
  const ctx = { ...h.context(fixture.ctx.globalState), extension: { packageJSON: { version: '0.3.0' } } };
  extension.activate(ctx);
  try {
    await h.waitFor(() => vscode.__recorded.closedTabs.length === 1, 'activation did not replace the dead tab', api.RECOVERY_SETTLE_MS + 2000);
    assert.equal(created(), before + 1);
    assert.deepEqual(group.tabs, [vscode.__recorded.panels.at(-1).tab]);
  } finally {
    extension.deactivate();
  }
});
