'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

// Viewer M3 (roadmap step 14), changed deliberately: the manifest's one widening, approved by the
// owner, is a SECOND command, MLView: Reveal in Diagram (the way from the code back to the diagram).
// It is offered in the editor context menu and the Command Palette only while an open diagram cites
// the active file (the `mlview.citedFile` context key), has no default keybinding, and adds no
// activation event, setting, hover, CodeLens or diagnostics.
test('manifest exposes only the authored artifact command, Reveal in Diagram, and the activation path', () => {
  assert.deepEqual(manifest.contributes.commands.map(x => x.command), ['mlview.openGeneratedDiagram', 'mlview.revealInDiagram']);
  const reveal = manifest.contributes.commands.find(x => x.command === 'mlview.revealInDiagram');
  assert.equal(reveal.title, 'Reveal in Diagram');
  assert.equal(reveal.category, 'MLView');
  const gated = (list) => (list || []).filter(x => x.command === 'mlview.revealInDiagram');
  assert.deepEqual(gated(manifest.contributes.menus['editor/context']).map(x => x.when), ['mlview.citedFile']);
  assert.deepEqual(gated(manifest.contributes.menus.commandPalette).map(x => x.when), ['mlview.citedFile']);
  assert.deepEqual(gated(manifest.contributes.menus['editor/title']), []);
  assert.equal(manifest.contributes.keybindings, undefined, 'no default keybinding');
  assert.deepEqual(manifest.activationEvents, [
    'onCommand:mlview.openGeneratedDiagram',
    'onWebviewPanel:mlview.authoredDiagram',
    'workspaceContains:**/*.mlview.json'
  ]);
  assert.equal(manifest.contributes.configuration, undefined);
  assert.equal(manifest.contributes.chatParticipants, undefined);
  assert.equal(manifest.contributes.languageModelTools, undefined);
  assert.ok(!manifest.keywords.includes('static-analysis'));
});

test('extension package contains no Python analyzer or rule documentation', () => {
  assert.equal(fs.existsSync(path.join(root, 'core')), false);
  assert.equal(fs.existsSync(path.join(root, 'docs', 'rules')), false);
  assert.equal(fs.existsSync(path.join(root, 'src', 'analysisRunner.ts')), false);
});

test('extension notice is byte-identical to the repository notice', () => {
  const repositoryNotice = fs.readFileSync(path.join(root, '..', 'THIRD_PARTY_NOTICES.md'));
  const extensionNotice = fs.readFileSync(path.join(root, 'THIRD_PARTY_NOTICES.md'));
  assert.ok(extensionNotice.equals(repositoryNotice));
});

test('packaging uses the pinned local vsce tool', () => {
  assert.equal(manifest.scripts.package, 'vsce package --no-dependencies');
  assert.equal(manifest.devDependencies['@vscode/vsce'], '3.9.2');
  assert.ok(!manifest.scripts.package.includes('npx'));
});

test('test script uses the cross-platform Node launcher', () => {
  assert.equal(manifest.scripts.test, 'node tools/run-tests.mjs');
  assert.ok(fs.existsSync(path.join(root, 'tools', 'run-tests.mjs')));
});

test('the marketplace icon remains reproducible', () => {
  const data = fs.readFileSync(path.join(root, manifest.icon));
  assert.ok(data.subarray(0, 8).equals(Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a])));
  assert.equal(data.readUInt32BE(16), 128);
  assert.equal(data.readUInt32BE(20), 128);
  assert.ok(fs.existsSync(path.join(root, 'tools', 'make_icon.py')));
});
