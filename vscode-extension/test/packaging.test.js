'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

// What the manifest contributes, and nothing else:
// - Two commands. MLView: Reveal in Diagram (the way from the code back to the diagram) is offered
//   in the editor context menu and the Command Palette only on a file that an open diagram cites
//   and that is unchanged since publishing: `resourcePath in mlview.citedFiles`, a list the
//   extension keeps of the open panels' cited files, so that VS Code can decide for the editor
//   under the pointer at once. The command has no default keybinding.
// - One custom editor, `mlview.diagram`, for *.mlview.json with priority "default", so a click in
//   the Explorer, Quick Open or a link opens the diagram; the JSON stays one step away through
//   Reopen Editor With… and Open With….
// - MLView: Open Generated Diagram in the editor's and the Explorer's context menus, and in the
//   editor title only on the JSON's text editor (`activeEditor` is set per editor group), so the
//   diagram's own tab does not offer to open itself.
// - Activation: VS Code (1.74 and later; engines ^1.100) activates on a contributed command and on
//   `onCustomEditor:mlview.diagram` from the contributions themselves, so neither has an entry.
//   The two entries are `onWebviewPanel:mlview.authoredDiagram`, for a restored tab of that panel
//   type, and `workspaceContains:**/*.mlview.json`.
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
    'onWebviewPanel:mlview.authoredDiagram',
    'workspaceContains:**/*.mlview.json'
  ]);
});

test('extension notice is byte-identical to the repository notice', () => {
  const repositoryNotice = fs.readFileSync(path.join(root, '..', 'THIRD_PARTY_NOTICES.md'));
  const extensionNotice = fs.readFileSync(path.join(root, 'THIRD_PARTY_NOTICES.md'));
  assert.ok(extensionNotice.equals(repositoryNotice));
});

test('the extension\'s changelog is byte-identical to the repository changelog', () => {
  const repositoryChangelog = fs.readFileSync(path.join(root, '..', 'CHANGELOG.md'));
  const extensionChangelog = fs.readFileSync(path.join(root, 'CHANGELOG.md'));
  assert.ok(extensionChangelog.equals(repositoryChangelog));
});

test('packaging uses the pinned local vsce tool', () => {
  assert.equal(manifest.scripts.package, 'vsce package --no-dependencies');
  assert.equal(manifest.devDependencies['@vscode/vsce'], '3.9.2');
  assert.ok(!manifest.scripts.package.includes('npx'));
});

test('the package holds the production build; compile, watch and pretest build the unminified bundle', () => {
  assert.equal(manifest.scripts['vscode:prepublish'], 'node tools/sync-notices.mjs && node esbuild.mjs --production');
  assert.equal(manifest.scripts.compile, 'node tools/sync-notices.mjs && node esbuild.mjs');
  assert.equal(manifest.scripts.watch, 'node tools/sync-notices.mjs && node esbuild.mjs --watch');
  assert.equal(manifest.scripts.pretest, 'node tools/sync-notices.mjs --check && node esbuild.mjs');
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
