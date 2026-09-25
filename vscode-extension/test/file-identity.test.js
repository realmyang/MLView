'use strict';
/**
 * EXT-2: open editors are matched to cited files by identity (realpath, lower-cased on win32),
 * never by comparing path strings. Buffers only feed the unsaved-changes status and the
 * navigation guard; validation always reads the disk.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;
const { normCase, identity, DependencySet } = api;

const fixtures = [];
test.afterEach(() => h.cleanup(fixtures));

test('normCase folds case only on win32', () => {
  assert.equal(normCase('C:\\Repo\\a.py', 'win32'), normCase('c:\\repo\\a.py', 'win32'));
  assert.equal(normCase('C:\\Repo\\a.py', 'win32'), 'c:\\repo\\a.py');
  assert.notEqual(normCase('/Repo/a.py', 'linux'), normCase('/repo/a.py', 'linux'));
  assert.equal(normCase('/repo/sub/../a.py', 'linux'), '/repo/a.py');
});

test('DependencySet recognises both the lexical and the real spelling', () => {
  const deps = new DependencySet('linux');
  deps.add('src/train.py', '/ws', '/real/ws/src/train.py');
  deps.addPath('/ws/run.mlview.json');
  assert.equal(deps.has('/ws/src/train.py'), true);
  assert.equal(deps.has('/ws/src/../src/train.py'), true);
  assert.equal(deps.has('/real/ws/src/train.py'), true);
  assert.equal(deps.has('/ws/run.mlview.json'), true);
  assert.equal(deps.has('/ws/other.py'), false);
  const win = new DependencySet('win32');
  win.add('src/train.py', 'C:\\Ws');
  assert.equal(win.has('c:\\ws\\SRC\\train.py'), true);
});

test('identity resolves symlinks to one spelling', async (t) => {
  const real = h.tempRoot('mlview-identity-real-');
  const link = path.join(os.tmpdir(), `mlview-identity-link-${process.pid}-${Date.now()}`);
  try {
    fs.symlinkSync(real, link, 'junction');
  } catch {
    fs.rmSync(real, { recursive: true, force: true });
    t.skip('symlinks are not available here');
    return;
  }
  try {
    fs.writeFileSync(path.join(real, 'a.py'), 'x\n');
    assert.equal(await identity(path.join(link, 'a.py')), await identity(path.join(real, 'a.py')));
    const unresolved = path.resolve(link, 'missing.py');
    assert.equal(await identity(unresolved), process.platform === 'win32' ? unresolved.toLowerCase() : unresolved);
  } finally {
    removeLink(link);
    fs.rmSync(real, { recursive: true, force: true });
  }
});

function removeLink(link) {
  try {
    fs.unlinkSync(link);
  } catch {
    try { fs.rmdirSync(link); } catch { /* already gone */ }
  }
}

async function dirtyScenario(folder, sourcePath) {
  const fixture = await h.openPanel({ root: folder.realRoot, folder: folder.root, openPath: path.join(folder.root, 'run.mlview.json'), files: { 'source.py': 'fit()\n' }, ready: false });
  fixtures.push({ ...fixture, root: folder.cleanup });
  const { panel } = fixture;
  vscode.__setDocument(sourcePath, 'fit()\n# unsaved note\n');
  vscode.__setDirty(sourcePath);
  // Force a revalidation through the watcher so the dirty status is recomputed after adoption.
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  await h.diskEvent(panel, 'change', path.join(folder.root, 'source.py'));
  assert.equal(h.shownRevision(panel), 'r1', 'validation uses the disk, not the buffer');
  assert.deepEqual(h.lastBanner(panel).codes, ['dirty']);
  assert.match(h.lastBanner(panel).message, /^Unsaved editor changes in source\.py are not checked;/);
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.shownDocuments.length === 1, 'the still-matching dirty buffer did not open');
  assert.equal(path.resolve(vscode.__recorded.shownDocuments[0].document.uri.fsPath), path.resolve(sourcePath), 'navigation opens the open document itself');
  vscode.__setDocument(sourcePath, '# moved down\nfit()\n');
  panel.fire({ v: 1, type: 'openLocation', evidenceId: 'e' });
  await h.waitFor(() => vscode.__recorded.messages.some(m => m[1] === 'MLView: unsaved changes in source.py no longer contain the lines cited by evidence e; save or revert the file, then try again.'), 'the moved dirty line did not block navigation');
  assert.equal(vscode.__recorded.shownDocuments.length, 1);
  return fixture;
}

test('a dirty buffer in a realpath workspace is reported and guards navigation', async () => {
  const root = h.tempRoot('mlview-dirty-');
  await dirtyScenario({ root, realRoot: root, cleanup: root }, path.join(root, 'source.py'));
});

test('a dirty buffer under a symlinked workspace root is matched by identity', async (t) => {
  const real = h.tempRoot('mlview-dirty-real-');
  const link = path.join(os.tmpdir(), `mlview-dirty-link-${process.pid}-${Date.now()}`);
  try {
    fs.symlinkSync(real, link, 'junction');
  } catch {
    fs.rmSync(real, { recursive: true, force: true });
    t.skip('symlinks are not available here');
    return;
  }
  t.after(() => removeLink(link));
  // The workspace folder and every editor use the non-real spelling, as VS Code does.
  await dirtyScenario({ root: link, realRoot: real, cleanup: real }, path.join(link, 'source.py'));
});

test('with lower-cased drive letters (win32 Uri.fsPath) the dirty lookup still matches', async () => {
  const root = h.tempRoot('mlview-dirty-drive-');
  vscode.__reset();
  vscode.__setLowercaseDriveLetters(true);
  const spelled = process.platform === 'win32' ? root[0].toLowerCase() + root.slice(1) : root;
  const fixture = await h.openPanel({ root, folder: spelled, openPath: path.join(spelled, 'run.mlview.json'), files: { 'source.py': 'fit()\n' }, ready: false });
  fixtures.push(fixture);
  vscode.__setLowercaseDriveLetters(true);
  vscode.__setDocument(path.join(spelled, 'source.py'), 'fit()\n# unsaved\n');
  vscode.__setDirty(path.join(spelled, 'source.py'));
  fixture.panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  await h.diskEvent(fixture.panel, 'change', path.join(spelled, 'source.py'));
  assert.deepEqual(h.lastBanner(fixture.panel).codes, ['dirty']);
});
