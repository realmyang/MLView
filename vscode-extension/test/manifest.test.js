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
  'mlview.showRuleDoc',
  // H10 (11.40): the multi-root picker.
  'mlview.activeFolder',
  // CFG-ONE (11.40): the two configuration commands.
  'mlview.openConfiguration',
  'mlview.createBaseline'
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
    // NB: a notebooks-only workspace has no .py file to activate on, so mlview.includeNotebooks
    // would be unreachable there without this row.
    'workspaceContains:**/*.ipynb',
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
    'mlview.configPath': '',
    'mlview.baselinePath': '',
    'mlview.includeNotebooks': false,
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
  // renderer-owned (ViewState.flow) and mlview.defaultScope is cut. ONE row JOINED in Sprint 4:
  // mlview.includeNotebooks, which ROADMAP NB names explicitly ("behind --include-notebooks /
  // [paths].notebooks (byte-identical behaviour without it)") - the host half of that flag has
  // to be a setting, because there is no other way to reach a CLI flag from the extension.
  // TWO rows JOINED in Sprint 5 by CFG-ONE (docs/contracts/11.40): mlview.configPath and
  // mlview.baselinePath. Both are named explicitly by the roadmap entry ("add mlview.configPath,
  // mlview.baselinePath, MLView: Open MLView Configuration and MLView: Create Baseline From
  // Current Findings"), and neither can be anything but a setting: they name a FILE, which is
  // per-folder state a command argument cannot carry across sessions. The active folder is
  // deliberately NOT among them - it is session state behind `mlview.activeFolder`, the command.
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
  // PACKAGING adds exactly one more file: the marketplace icon, whose source is
  // `tools/make_icon.py` and whose bytes that script's --check mode owns.
  assert.ok(entries.includes('icon.png'), 'the 128x128 marketplace icon must be committed');
  if (!entries.includes('mlview.js')) {
    // Pre-sync state: the placeholder and the icon are the only things there.
    assert.deepEqual(entries, ['README.md', 'icon.png']);
    return;
  }
  // Post-sync state: tools/sync-assets.py is the sole writer of the two bundle files
  // and nothing else may appear alongside them, the README and the icon.
  assert.deepEqual(entries, ['README.md', 'icon.png', 'mlview.css', 'mlview.js']);
  for (const name of ['mlview.js', 'mlview.css']) {
    assert.ok(fs.statSync(path.join(mediaDir, name)).size > 1024, name + ' looks truncated');
  }
});

// PROC-11: the README is the only place a user reads a setting's name before typing it,
// so a row that names a key the manifest does not contribute earns them an "Unknown
// Configuration Setting" warning (mlview.showSpeculative and mlview.followCursor did,
// for a sprint after CLEANUP deleted them - docs/CONTRACTS.md 11.20 A). The two lists are
// asserted equal in BOTH directions: a new setting that never reaches the README is the
// same defect seen from the other side.
test('the README settings table names exactly the settings the manifest contributes', () => {
  const readme = fs.readFileSync(path.join(__dirname, '..', 'README.md'), 'utf8');
  const documented = new Set();
  for (const line of readme.split('\n')) {
    const row = /^\|\s*`(mlview\.[A-Za-z]+)`\s*\|/.exec(line);
    if (row) {
      documented.add(row[1]);
    }
  }
  const contributed = new Set(Object.keys(manifest.contributes.configuration.properties));
  assert.ok(documented.size > 0, 'the settings table must still be parseable');
  assert.deepEqual(
    [...documented].sort(),
    [...contributed].sort(),
    'every documented mlview.* setting must exist, and every contributed one must be documented'
  );
});

/**
 * MLV-P11 — the getting-started walkthrough.
 *
 * `vscode-extension/package.json` contributed **no `walkthroughs` key at all**, and the two
 * failure modes of one are both silent: a step that invokes a command nobody registered does
 * nothing when clicked, and a step whose `media.markdown` resolves outside the packaged
 * extension renders as an empty panel. Both are asserted here, because neither shows up in a
 * dev host where `<repo>/docs` happens to be next door.
 */
test('the walkthrough has five steps, each invoking a command that exists', () => {
  const walkthroughs = manifest.contributes.walkthroughs;
  assert.ok(Array.isArray(walkthroughs) && walkthroughs.length === 1);
  const walkthrough = walkthroughs[0];
  assert.equal(walkthrough.id, 'mlview.gettingStarted');
  assert.ok(walkthrough.title.length > 0);
  assert.ok(walkthrough.description.length > 0);
  assert.equal(walkthrough.steps.length, 5, 'the roadmap entry specifies five steps');

  const contributed = new Set(manifest.contributes.commands.map((c) => c.command));
  const ids = new Set();
  for (const step of walkthrough.steps) {
    assert.match(step.id, /^mlview\.step\.[a-z]+$/);
    assert.ok(!ids.has(step.id), `duplicate step id ${step.id}`);
    ids.add(step.id);
    assert.ok(step.title.length > 0);
    // Every step must be ACTIONABLE - "each invoking an already-registered command".
    const invoked = [...step.description.matchAll(/\(command:([\w.]+)\)/g)].map((m) => m[1]);
    assert.equal(invoked.length, 1, `${step.id} must offer exactly one command link`);
    assert.ok(contributed.has(invoked[0]), `${step.id} invokes uncontributed ${invoked[0]}`);
    assert.deepEqual(step.completionEvents, [`onCommand:${invoked[0]}`]);
  }
  // The five the roadmap names: install -> visualize -> read a finding -> Alt+M -> Alt+Shift+M.
  assert.deepEqual(
    walkthrough.steps.map((s) => s.id.replace('mlview.step.', '')),
    ['install', 'visualize', 'problems', 'reveal', 'scope']
  );
});

test('every walkthrough page is inside the extension, so a packaged install can render it', () => {
  const root = path.join(__dirname, '..');
  for (const step of manifest.contributes.walkthroughs[0].steps) {
    const markdown = step.media.markdown;
    assert.ok(markdown, `${step.id} needs a media.markdown page`);
    assert.ok(!path.isAbsolute(markdown) && !markdown.startsWith('..'), 'relative to the extension');
    const full = path.join(root, markdown);
    assert.ok(fs.existsSync(full), `${markdown} is missing - run "npm run sync:walkthrough"`);
    const text = fs.readFileSync(full, 'utf8');
    assert.ok(text.length > 200, `${markdown} looks like a placeholder`);
    assert.match(text, /^# /, `${markdown} must open with a heading`);
    assert.ok(step.media.altText && step.media.altText.length > 0);
  }
  // And the shipped copies are GENERATED: `tools/sync-walkthrough.mjs --check` is the gate
  // that stops the extension's copy drifting from `<repo>/docs/walkthrough`.
  const repoPages = path.join(root, '..', 'docs', 'walkthrough');
  if (!fs.existsSync(repoPages)) {
    return; // an extension-only checkout has no source to compare against
  }
  for (const step of manifest.contributes.walkthroughs[0].steps) {
    const name = path.basename(step.media.markdown);
    assert.equal(
      fs.readFileSync(path.join(root, 'docs', 'walkthrough', name), 'utf8'),
      fs.readFileSync(path.join(repoPages, name), 'utf8'),
      `${name} has drifted from docs/walkthrough - run "npm run sync:walkthrough"`
    );
  }
});
