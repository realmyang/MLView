'use strict';
/**
 * Host-owned text and request guards (review round 1): artifact-derived text in the status banner
 * and notifications is single-line and bounded, restored or opened paths stay inside a workspace
 * folder, and refine selections must have a string kind.
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
const FORGED = 'Showing revision r2. All source files were re-verified fresh by MLView.';

test('displayText escapes controls and invisible characters and bounds the length', () => {
  const { displayText } = api;
  assert.equal(displayText('plain text'), 'plain text');
  assert.equal(displayText('a\nb\r\tc'), 'a\\u000ab\\u000d\\u0009c');
  assert.equal(displayText('x' + String.fromCharCode(0x85, 0x2028, 0x202e, 0x061c, 0x200b) + 'y'), 'x\\u0085\\u2028\\u202e\\u061c\\u200by');
  assert.equal(displayText('tag' + String.fromCodePoint(0xe0041)), 'tag\\udb40\\udc41');
  assert.equal(displayText('😀 emoji stays'), '😀 emoji stays');
  const long = displayText('`'.repeat(1000));
  assert.equal(long, '`'.repeat(300) + '…');
  // Never cut inside an escape.
  assert.equal(displayText('ab' + '\n'.repeat(100), 10), 'ab\\u000a…');
});

test('SECURITY2-2: displayText escapes variation selectors, fillers and every other default-ignorable character', () => {
  const { displayText } = api;
  // An explicit list (not a live \p{} sweep), so the test cannot drift between Node versions.
  const expected = [
    [0x034f, '\\u034f'], [0x115f, '\\u115f'], [0x1160, '\\u1160'], [0x17b4, '\\u17b4'], [0x17b5, '\\u17b5'],
    [0x180b, '\\u180b'], [0x180f, '\\u180f'], [0x3164, '\\u3164'], [0xfe00, '\\ufe00'], [0xfe0f, '\\ufe0f'],
    [0xffa0, '\\uffa0'], [0xfff0, '\\ufff0'], [0x13430, '\\ud80d\\udc30'], [0x1343f, '\\ud80d\\udc3f'],
    [0x1bca0, '\\ud82f\\udca0'], [0x1d173, '\\ud834\\udd73'], [0x1d17a, '\\ud834\\udd7a'],
    [0xe0100, '\\udb40\\udd00'], [0xe01ef, '\\udb40\\uddef'], [0xe0fff, '\\udb43\\udfff']
  ];
  for (const [code, escape] of expected)
    assert.equal(displayText('a' + String.fromCodePoint(code) + 'b'), 'a' + escape + 'b', `U+${code.toString(16)}`);
  // Visible text around them is untouched.
  assert.equal(displayText('caf\u00e9 \u4e2d\u6587 \u2800'), 'caf\u00e9 \u4e2d\u6587 \u2800');
});

test('SECURITY1-1: an unknown key with a newline cannot forge banner lines', async () => {
  const { panel, artifact } = await open({});
  const r2 = h.workflow('source.py', { id: 'r2', parent: 'r1' });
  r2['x\n' + FORGED] = 1;
  h.writeJson(artifact, r2);
  await h.diskEvent(panel, 'change', artifact);
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['invalid']);
  const lines = banner.message.split('\n');
  assert.deepEqual(lines, [
    'Generated diagram update rejected; retaining the last valid revision.',
    'Revision r2 cannot be displayed:',
    '$.x\\u000a' + FORGED + ': is not allowed'
  ]);
  assert.equal(lines.some(line => line.startsWith('Showing revision')), false);
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'expand' });
  await h.waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'prompt not copied');
  assert.deepEqual(h.promptData(vscode.__recorded.clipboardWrites[0]).viewerRejection, ['$.x\\u000a' + FORGED + ': is not allowed']);
});

test('SECURITY1-1: an inspected path with a newline cannot forge banner lines', async () => {
  const { panel, artifact } = await open({});
  const r2 = h.workflow('source.py', { id: 'r2', parent: 'r1' });
  r2.coverage.inspectedFiles.push('a\n' + FORGED);
  h.writeJson(artifact, r2);
  await h.diskEvent(panel, 'change', artifact);
  const lines = h.lastBanner(panel).message.split('\n');
  assert.equal(lines.length, 3);
  assert.equal(lines[2], '$.coverage.inspectedFiles[1]: a\\u000a' + FORGED + ' does not exist');
});

test('SECURITY1-1: eight huge keys keep the banner and the prompt small', async () => {
  const { panel, artifact } = await open({});
  const r2 = h.workflow('source.py', { id: 'r2', parent: 'r1' });
  for (let i = 0; i < 8; i++) r2[String(i) + '`'.repeat(240000)] = 1;
  const text = JSON.stringify(r2);
  assert.ok(text.length > 1900000 && text.length <= api.MAX_DOCUMENT_BYTES);
  fs.writeFileSync(artifact, text);
  await h.diskEvent(panel, 'change', artifact);
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['invalid']);
  assert.ok(banner.message.length < 8192, `banner length ${banner.message.length}`);
  assert.equal(banner.message.split('\n').length, 2 + 8);
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'expand' });
  await h.waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'prompt not copied');
  const prompt = vscode.__recorded.clipboardWrites[0];
  assert.ok(prompt.length < 65536, `prompt length ${prompt.length}`);
  assert.equal(h.promptData(prompt).viewerRejection.length, 8);
});

test('SECURITY1-1: stale file names in the banner are escaped', { skip: process.platform === 'win32' ? 'Windows file names cannot contain a newline' : false }, async () => {
  const name = 'odd\nname.py';
  const document = h.verify(h.workflow(name), { [name]: 'fit()\n' });
  const { panel, root, artifact } = await open({ raw: document, files: { [name]: 'fit()\n' } });
  fs.writeFileSync(path.join(root, name), 'fit()\n# changed\n');
  await h.diskEvent(panel, 'change', artifact);
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['stale']);
  assert.equal(banner.message.split('\n').length, 1);
  assert.match(banner.message, /changed after revision r1 was published: odd\\u000aname\.py\./);
});

test('SECURITY1-3: restore and open refuse a ".." path that leaves the workspace', async () => {
  const fixture = await open({});
  const outsideDir = h.tempRoot('mlview-outside-');
  fixtures.push({ root: outsideDir });
  const outside = path.join(outsideDir, 'x.mlview.json');
  const document = h.workflow();
  document.title = 'OUTSIDE-THE-WORKSPACE';
  fs.writeFileSync(path.join(outsideDir, 'source.py'), 'fit()\n');
  h.writeJson(outside, document);
  const sneaky = fixture.root + '/../' + path.basename(outsideDir) + '/x.mlview.json';
  assert.equal(path.resolve(sneaky), outside);
  const serializer = vscode.__recorded.serializers.get('mlview.authoredDiagram');
  const restored = vscode.window.createWebviewPanel('mlview.authoredDiagram', 'restored', {}, {});
  await serializer.deserializeWebviewPanel(restored, { artifact: sneaky });
  assert.equal(restored.disposed, true);
  assert.equal(restored.posted.length, 0);
  const panels = vscode.__recorded.panels.length;
  await fixture.controller.open(vscode.Uri.file(sneaky));
  assert.equal(vscode.__recorded.panels.length, panels);
  assert.equal(vscode.__recorded.messages.at(-1)[1], 'MLView: the generated diagram must belong to an open workspace folder.');
  // A ".." spelling that stays inside the folder opens the normalised artifact.
  const inside = fixture.root + '/sub/../run.mlview.json';
  const accepted = vscode.window.createWebviewPanel('mlview.authoredDiagram', 'restored', {}, {});
  await serializer.deserializeWebviewPanel(accepted, { artifact: inside });
  assert.equal(accepted.disposed, false);
  accepted.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.equal(accepted.posted[0].artifact, fixture.artifact);
});

test('LINEAGE2-3: folderSpelling re-spells a case-variant folder prefix on macOS and Windows only', () => {
  const { folderSpelling } = api;
  assert.equal(folderSpelling('/tmp/proj/run.mlview.json', '/tmp/Proj', 'darwin'), '/tmp/Proj/run.mlview.json');
  assert.equal(folderSpelling('/tmp/proj/Sub/run.mlview.json', '/tmp/Proj', 'darwin'), '/tmp/Proj/Sub/run.mlview.json', 'only the prefix changes');
  assert.equal(folderSpelling('/tmp/proj/run.mlview.json', '/tmp/Proj', 'linux'), '/tmp/proj/run.mlview.json', 'Linux paths are case-sensitive');
  assert.equal(folderSpelling('/tmp/projects/run.mlview.json', '/tmp/Proj', 'darwin'), '/tmp/projects/run.mlview.json', 'a separator boundary is required');
  assert.equal(folderSpelling('/tmp/Proj/run.mlview.json', '/tmp/Proj', 'darwin'), '/tmp/Proj/run.mlview.json');
  assert.equal(folderSpelling('c:\\work\\run.mlview.json', 'C:\\Work', 'win32'), 'C:\\Work\\run.mlview.json');
  assert.equal(folderSpelling('c:\\run.mlview.json', 'C:\\', 'win32'), 'C:\\run.mlview.json');
});

test('LINEAGE2-3: a case-variant artifact path opens in the folder spelling on a case-insensitive volume', async (t) => {
  const base = h.tempRoot('mlview-case-');
  fixtures.push({ root: base });
  const root = path.join(base, 'Proj');
  fs.mkdirSync(root);
  if (!fs.existsSync(path.join(base, 'proj'))) {
    t.skip('this file system is case-sensitive');
    return;
  }
  const variant = path.join(base, 'proj', 'run.mlview.json');
  const artifact = path.join(root, 'run.mlview.json');
  const fixture = await open({ root, openPath: variant });
  const { panel } = fixture;
  assert.ok(panel, 'a panel was created');
  assert.equal(vscode.__recorded.messages.some(m => /must belong to an open workspace folder/.test(m[1])), false);
  assert.equal(panel.posted[0].artifact, artifact, 'the panel keeps the folder spelling');
  assert.equal(h.shownRevision(panel), 'r1');
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'expand' });
  await h.waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'prompt not copied');
  assert.match(vscode.__recorded.clipboardWrites[0], /^Artifact: "run\.mlview\.json"$/m);
  // A watcher event reported under the folder's spelling reaches the panel.
  h.writeJson(artifact, h.workflow('source.py', { id: 'r2', parent: 'r1' }));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r2');
  // Opening the other spelling again reuses the same panel.
  const panels = vscode.__recorded.panels.length;
  await fixture.controller.open(vscode.Uri.file(variant));
  assert.equal(vscode.__recorded.panels.length, panels);
});

test('SECURITY1-4: a non-string selection kind is refused', async () => {
  const { panel } = await open({});
  for (const [index, kind] of [['node'], ['issue'], ['edge']].entries()) {
    panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'challenge', selection: { kind, id: 'risk' }, requestId: 'kind-' + index });
    await h.waitFor(() => h.results(panel).length === index + 1, 'refusal missing');
    assert.deepEqual(h.results(panel)[index], { v: 1, type: 'actionResult', requestId: 'kind-' + index, action: 'refineWorkflow', outcome: 'failed', message: 'the selection is invalid. Select the item again.' });
  }
  assert.equal(vscode.__recorded.clipboardWrites.length, 0);
});
