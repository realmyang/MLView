'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const manifest = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
);

const REQUIRED_COMMANDS = [
  'mlview.visualize',
  'mlview.visualizeWorkspace',
  'mlview.refresh',
  'mlview.showIssues',
  'mlview.revealInDiagram',
  'mlview.scopeToSymbol',
  'mlview.clearScope',
  'mlview.exportHtml',
  'mlview.selectInterpreter',
  'mlview.showOutput',
  'mlview.showRuleDoc'
];

test('engine, version and entry point are pinned as specified', () => {
  assert.equal(manifest.version, '0.1.0');
  assert.equal(manifest.engines.vscode, '^1.100.0');
  assert.equal(manifest.main, './out/extension.js');
  assert.equal(manifest.devDependencies['@types/vscode'], '1.100.0');
  assert.equal(manifest.devDependencies.typescript, '5.9.3');
  assert.equal(manifest.devDependencies.esbuild, '0.28.2');
  assert.match(manifest.devDependencies['@types/node'], /^20\./);
});

test('activation events and untrusted-workspace support', () => {
  assert.deepEqual(manifest.activationEvents, [
    'onLanguage:python',
    'workspaceContains:**/*.py',
    'onWebviewPanel:mlview.diagram'
  ]);
  assert.equal(manifest.capabilities.untrustedWorkspaces.supported, 'limited');
});

test('Restricted Mode also ignores a workspace-supplied interpreter path', () => {
  // mlview.pythonPath is machine-overridable; without listing it here VS Code keeps applying a
  // cloned repository's own .vscode/settings.json value in Restricted Mode, and any command
  // that slipped past the trust guard would execute whatever executable that repo ships.
  const untrusted = manifest.capabilities.untrustedWorkspaces;
  assert.ok(
    untrusted.restrictedConfigurations.includes('mlview.pythonPath'),
    'mlview.pythonPath must be restricted until the folder is trusted'
  );
  assert.ok(untrusted.description.length > 0);
});

test('virtual workspaces are declared unsupported, and the declared licence exists', () => {
  // The extension spawns a local interpreter with cwd: folder.uri.fsPath and reads media/ and
  // docs/rules/ from disk, so it cannot work over vscode-vfs://.
  assert.equal(manifest.capabilities.virtualWorkspaces.supported, false);
  assert.ok(manifest.capabilities.virtualWorkspaces.description.length > 0);
  assert.equal(manifest.license, 'MIT');
  const licence = fs.readFileSync(path.join(__dirname, '..', 'LICENSE'), 'utf8');
  assert.match(licence, /MIT License/);
  assert.match(licence, /WITHOUT WARRANTY OF ANY KIND/);
});

test('every contributed command has a title and the MLView category', () => {
  const commands = manifest.contributes.commands;
  const ids = commands.map((c) => c.command);
  for (const id of REQUIRED_COMMANDS) {
    assert.ok(ids.includes(id), `missing command ${id}`);
  }
  for (const command of commands) {
    assert.equal(command.category, 'MLView', `${command.command} needs the MLView category`);
    assert.ok(command.title && command.title.length > 0);
    assert.match(command.icon, /^\$\([a-z-]+\)$/);
  }
});

test('Alt+M is bound to reveal-in-diagram and the editor context menu carries it', () => {
  const binding = manifest.contributes.keybindings.find(
    (k) => k.command === 'mlview.revealInDiagram'
  );
  assert.ok(binding, 'mlview.revealInDiagram must have a keybinding');
  assert.equal(binding.key, 'alt+m');
  assert.match(binding.when, /editorTextFocus/);
  assert.match(binding.when, /python/);

  const contextItems = manifest.contributes.menus['editor/context'].map((m) => m.command);
  assert.ok(contextItems.includes('mlview.revealInDiagram'));
  const titleItems = manifest.contributes.menus['editor/title'].map((m) => m.command);
  assert.ok(titleItems.includes('mlview.visualize'));
});

test('the two scope commands are contributed exactly as CONTRACTS 11.11 specifies', () => {
  const byId = new Map(manifest.contributes.commands.map((c) => [c.command, c]));

  const scope = byId.get('mlview.scopeToSymbol');
  assert.ok(scope, 'mlview.scopeToSymbol must be contributed');
  assert.equal(scope.title, 'Scope Diagram to Symbol');
  assert.equal(scope.category, 'MLView'); // -> "MLView: Scope Diagram to Symbol"
  assert.equal(scope.icon, '$(list-tree)');

  const clear = byId.get('mlview.clearScope');
  assert.ok(clear, 'mlview.clearScope must be contributed');
  assert.equal(clear.title, 'Clear Diagram Scope');
  assert.equal(clear.category, 'MLView');
  assert.equal(clear.icon, '$(clear-all)');

  const binding = manifest.contributes.keybindings.find(
    (k) => k.command === 'mlview.scopeToSymbol'
  );
  assert.ok(binding, 'Alt+Shift+M must be bound');
  assert.equal(binding.key, 'alt+shift+m');
  assert.equal(binding.mac, 'alt+shift+m');
  assert.equal(binding.when, 'editorTextFocus && editorLangId == python');
  assert.equal(
    manifest.contributes.keybindings.filter((k) => k.key === 'alt+shift+m').length,
    1,
    'alt+shift+m must not be claimed twice'
  );

  const item = manifest.contributes.menus['editor/context'].find(
    (m) => m.command === 'mlview.scopeToSymbol'
  );
  assert.ok(item, 'the editor context menu carries the scope command');
  assert.equal(item.group, 'mlview@3');
  assert.equal(item.when, 'editorLangId == python');
  // Clearing a scope is a palette-only command: there is nothing to point at in the editor.
  assert.ok(
    !manifest.contributes.menus['editor/context'].some((m) => m.command === 'mlview.clearScope')
  );
});

test('all mlview.* settings are contributed with the contract defaults', () => {
  const props = manifest.contributes.configuration.properties;
  const expected = {
    'mlview.pythonPath': '',
    'mlview.analyzeOnSave': true,
    'mlview.currentFileAnalysisScope': 'package',
    'mlview.exclude': [],
    'mlview.maxFiles': 500,
    'mlview.maxNodes': 400,
    'mlview.minSeverity': 'low',
    'mlview.minConfidence': 0.6,
    'mlview.diagnosticsEnabled': true,
    'mlview.diagnosticSeverity': 'warning',
    'mlview.disabledRules': [],
    'mlview.codeLens': true,
    'mlview.trace': 'off'
  };
  // CHANGED by ROADMAP CLEANUP 4 and COVERAGE (2026-09-08). Two rows LEFT: mlview.showSpeculative
  // and mlview.followCursor both shipped in the Settings UI with a description reading "Not
  // implemented in this prototype", and A6 cut followCursor outright - a settings row that says
  // it does nothing is worse than not shipping it. One row JOINED:
  // mlview.currentFileAnalysisScope, which COVERAGE names explicitly, because "Visualize
  // (Current File)" analysing the file alone loses 4 of 7 findings silently. Nothing else may
  // grow this set: CONTRACTS.md 11.11 is still "Settings: none added", the flow preference is
  // renderer-owned (ViewState.flow) and mlview.defaultScope is cut.
  assert.deepEqual(Object.keys(props).sort(), Object.keys(expected).sort());
  for (const [key, value] of Object.entries(expected)) {
    assert.deepEqual(props[key].default, value, `${key} default`);
  }
  assert.deepEqual(props['mlview.minSeverity'].enum, ['low', 'medium', 'high']);
  assert.deepEqual(props['mlview.diagnosticSeverity'].enum, ['warning', 'error']);
  assert.deepEqual(props['mlview.trace'].enum, ['off', 'messages', 'verbose']);
  assert.deepEqual(props['mlview.currentFileAnalysisScope'].enum, [
    'file',
    'package',
    'workspace'
  ]);
  // The enum is only half a setting: a row whose values are undocumented is a row nobody picks.
  assert.equal(props['mlview.currentFileAnalysisScope'].enumDescriptions.length, 3);
});

test('the chat participant matches the registered id', () => {
  const participants = manifest.contributes.chatParticipants;
  assert.equal(participants.length, 1);
  const participant = participants[0];
  assert.equal(participant.id, 'mlview.chat');
  assert.equal(participant.name, 'mlview');
  assert.equal(participant.fullName, 'MLView');
  assert.equal(participant.isSticky, true);
  assert.deepEqual(
    participant.commands.map((c) => c.name),
    ['diagram', 'issues', 'explain']
  );
  for (const command of participant.commands) {
    assert.ok(command.description.length > 0);
  }
});

test('all three language-model tools carry BOTH canBeReferencedInPrompt and toolReferenceName', () => {
  // Without both, the tool exists in vscode.lm.tools but agent mode never calls it.
  const tools = manifest.contributes.languageModelTools;
  assert.deepEqual(
    tools.map((t) => t.name),
    ['mlview_analyzeWorkspace', 'mlview_listIssues', 'mlview_showDiagram']
  );
  assert.deepEqual(
    tools.map((t) => t.toolReferenceName),
    ['mlviewAnalyze', 'mlviewIssues', 'mlviewDiagram']
  );
  for (const tool of tools) {
    assert.equal(tool.canBeReferencedInPrompt, true, `${tool.name} canBeReferencedInPrompt`);
    assert.ok(tool.toolReferenceName, `${tool.name} toolReferenceName`);
    assert.ok(tool.modelDescription.length > 40, `${tool.name} needs a real modelDescription`);
    assert.ok(tool.userDescription.length > 0);
    assert.ok(tool.displayName.length > 0);
    assert.equal(tool.inputSchema.type, 'object');
    assert.ok(Array.isArray(tool.tags) && tool.tags.includes('mlview'));
    assert.match(tool.icon, /^\$\([a-z-]+\)$/);
  }
});

test('npm scripts cover compile, check, test and packaging', () => {
  const scripts = manifest.scripts;
  assert.match(scripts.compile, /esbuild/);
  assert.equal(scripts.check, 'tsc --noEmit');
  // tools/run-tests.mjs enumerates test/*.test.js and spawns `node --test` itself:
  // Node 21+ rejects a bare directory argument and cmd.exe does not expand globs.
  assert.equal(scripts.test, 'node tools/run-tests.mjs');
  assert.match(scripts.pretest, /esbuild/, 'pretest must build the bundles node --test loads');
  assert.match(scripts.package, /vsce package/);
});

test('media/ holds the sync placeholder, plus the bundle once sync-assets.py has run (A13)', () => {
  const mediaDir = path.join(__dirname, '..', 'media');
  const entries = fs.readdirSync(mediaDir).sort();
  assert.ok(entries.includes('README.md'), 'the A13 placeholder README must survive the sync');
  if (!entries.includes('mlview.js')) {
    // Pre-sync state: the placeholder is the only thing there.
    assert.deepEqual(entries, ['README.md']);
    return;
  }
  // Post-sync state: tools/sync-assets.py is the sole writer of this directory and
  // it writes exactly two files, so nothing else may appear alongside the README.
  assert.deepEqual(entries, ['README.md', 'mlview.css', 'mlview.js']);
  for (const name of ['mlview.js', 'mlview.css']) {
    assert.ok(fs.statSync(path.join(mediaDir, name)).size > 1024, name + ' looks truncated');
  }
});
