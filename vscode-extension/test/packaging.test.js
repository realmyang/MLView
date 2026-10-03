'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

// Viewer M3 (roadmap step 14), changed deliberately: the manifest's one widening, approved by the
// owner, is a SECOND command, MLView: Reveal in Diagram (the way from the code back to the diagram).
// It is offered in the editor context menu and the Command Palette only on a file an open diagram
// cites, unchanged since publishing (`resourcePath in mlview.citedFiles`, a list the extension keeps
// of the open panels' cited files, so the renderer can decide for the editor under the pointer at
// once: M3 review, F1), has no default keybinding, and adds no activation event, setting, hover,
// CodeLens or diagnostics.
// Viewer M4 (roadmap step 18), changed deliberately, the owner's choice of native opening: one
// custom editor, `mlview.diagram`, for *.mlview.json with priority "default", so a click in the
// Explorer, Quick Open or a link opens the diagram (the JSON stays one step away through Reopen
// Editor With… and Open With…); MLView: Open Generated Diagram in the Explorer's context menu; and
// the existing editor/title entry limited to the JSON's text editor (`activeEditor` is set per
// editor group), so the diagram's own tab does not offer to open itself. No new command, setting,
// keybinding or explicit activation event: VS Code (1.74 and later; engines ^1.100) activates on
// `onCustomEditor:mlview.diagram` from the contribution itself, and `onWebviewPanel:` stays for
// reopening a panel tab left by an earlier MLView.
test('manifest exposes only the authored artifact command, Reveal in Diagram, the diagram editor and the activation path', () => {
  assert.deepEqual(manifest.contributes.commands.map(x => x.command), ['mlview.openGeneratedDiagram', 'mlview.revealInDiagram']);
  const reveal = manifest.contributes.commands.find(x => x.command === 'mlview.revealInDiagram');
  assert.equal(reveal.title, 'Reveal in Diagram');
  assert.equal(reveal.category, 'MLView');
  const gated = (list) => (list || []).filter(x => x.command === 'mlview.revealInDiagram');
  const when = 'resourceScheme =~ /^(file|vscode-notebook-cell)$/ && resourcePath in mlview.citedFiles';
  assert.deepEqual(gated(manifest.contributes.menus['editor/context']).map(x => x.when), [when]);
  assert.deepEqual(gated(manifest.contributes.menus.commandPalette).map(x => x.when), [when]);
  assert.deepEqual(gated(manifest.contributes.menus['editor/title']), []);
  assert.deepEqual(manifest.contributes.customEditors, [{
    viewType: 'mlview.diagram',
    displayName: 'MLView Diagram',
    selector: [{ filenamePattern: '*.mlview.json' }],
    priority: 'default'
  }]);
  const open = (menu) => (manifest.contributes.menus[menu] || []).filter(x => x.command === 'mlview.openGeneratedDiagram');
  assert.deepEqual(open('explorer/context'), [{ command: 'mlview.openGeneratedDiagram', when: 'resourceFilename =~ /\\.mlview\\.json$/ && !explorerResourceIsFolder', group: 'navigation@99' }]);
  assert.deepEqual(open('editor/title'), [{ command: 'mlview.openGeneratedDiagram', when: 'resourceFilename =~ /\\.mlview\\.json$/ && activeEditor == workbench.editors.files.textFileEditor', group: 'navigation@99' }]);
  assert.deepEqual(open('editor/context').map(x => x.when), ['resourceFilename =~ /\\.mlview\\.json$/']);
  assert.deepEqual(Object.keys(manifest.contributes).sort(), ['commands', 'customEditors', 'menus']);
  assert.deepEqual(Object.keys(manifest.contributes.menus).sort(), ['commandPalette', 'editor/context', 'editor/title', 'explorer/context']);
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
