'use strict';
/**
 * H10 — multi-root workspaces (docs/contracts/11.40-lm-tools-scope.md).
 *
 * The defect these cover is measured, not hypothetical: `workspaceFolderFor` fell back to
 * `workspaceFolders?.[0]` (`extension.ts:299`) and the language-model analyze path hardcoded
 * the same (`toolAnalyze.ts:38`), so in a window with two folders open **the second was never
 * analyzed and nothing said so** — a green status bar and an empty Problems panel describing
 * one of two projects.
 *
 * Driven end to end against the real `out/extension.js` with a two-folder mocked workspace and
 * `child_process.execFile` stubbed, because every one of these is about which folder a surface
 * chose — a question no test over a pure function can ask.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const cp = require('node:child_process');

const { readSampleGraph } = require('./harness.js'); // installs the `vscode` -> mock hook
const vscode = require('./mock-vscode.js');

const EXTENSION_ROOT = path.join(__dirname, '..');
const ALPHA = 'C:/ws/alpha';
const BETA = 'C:/ws/beta';
const FAKE_PYTHON = 'C:/ws/.venv/Scripts/python.exe';

const extension = require(path.join(EXTENSION_ROOT, 'out', 'extension.js'));

// ---------------------------------------------------------------- the stubbed analyzer

const realExecFile = cp.execFile;
/** Every `analyze` argv the extension asked for, with the cwd it asked for it in. */
let spawns = [];

/** The sample graph, retargeted at `root` so its issues land in that folder's files. */
function graphFor(root) {
  const graph = readSampleGraph();
  const from = graph.workspace.root;
  const retarget = (value) =>
    typeof value === 'string' && value.startsWith(from) ? root + value.slice(from.length) : value;
  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    if (!node || typeof node !== 'object') {
      return;
    }
    for (const [key, value] of Object.entries(node)) {
      if (key === 'absFile' || key === 'root') {
        node[key] = retarget(value);
      } else {
        walk(value);
      }
    }
  };
  walk(graph);
  graph.workspace.root = root;
  return graph;
}

function fakeChild() {
  return {
    stderr: { setEncoding() {}, on() {} },
    stdout: { setEncoding() {}, on() {} },
    on() {},
    kill() {},
    exitCode: null,
    killed: false
  };
}

function installExecFileStub() {
  spawns = [];
  cp.execFile = function (file, args, opts, callback) {
    const done = typeof opts === 'function' ? opts : callback;
    const cwd = (typeof opts === 'object' && opts && opts.cwd) || '';
    let stdout = '';
    if (args.includes('-c')) {
      stdout = JSON.stringify([3, 13, FAKE_PYTHON]); // the version probe
    } else if (args.includes('--version')) {
      stdout = JSON.stringify({ version: '0.1.0', schemaVersion: '1.0' });
    } else if (args.includes('analyze')) {
      spawns.push({ argv: args.join(' '), cwd });
      // The analyzer answers about the directory it was pointed at, so a graph produced for
      // the wrong folder is visible as the wrong root rather than as identical output.
      const target = args.find((a) => a === BETA || String(a).startsWith(BETA + '/'))
        ? BETA
        : ALPHA;
      stdout = JSON.stringify(graphFor(target));
    }
    setTimeout(() => done(null, stdout, ''), 5);
    return fakeChild();
  };
}

function makeContext() {
  const state = new Map();
  return {
    subscriptions: [],
    extensionPath: EXTENSION_ROOT,
    extensionUri: vscode.Uri.file(EXTENSION_ROOT),
    extension: { packageJSON: { version: '0.1.0' } },
    workspaceState: { get: (k) => state.get(k), update: async (k, v) => void state.set(k, v) },
    globalState: { get: (k) => state.get(k), update: async () => undefined }
  };
}

function boot(folders = [ALPHA, BETA]) {
  vscode.__reset();
  vscode.__setWorkspaceFolders(folders);
  vscode.__setConfig('mlview', 'pythonPath', FAKE_PYTHON);
  installExecFileStub();
  const ctx = makeContext();
  extension.activate(ctx);
  return ctx;
}

function shutdown() {
  extension.deactivate();
  cp.execFile = realExecFile;
  vscode.__disableChatAndLm();
  vscode.__reset();
}

const run = (id, ...args) => vscode.__recorded.commands.get(id)(...args);
const statusItem = () => vscode.__recorded.statusBarItems[0];
const collection = () => vscode.__recorded.diagnosticCollections[0];
const analyzedRoots = () => spawns.map((s) => s.cwd);

// ------------------------------------------------------------------------------- tests

test('the first folder is still the default, so a single-folder window is unchanged', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace');
    assert.deepEqual(analyzedRoots(), [ALPHA]);
    assert.equal(statusItem().tooltip.value ? true : false, true, 'multi-root gets a MarkdownString');
  } finally {
    shutdown();
  }
});

test('a one-folder window keeps the plain-string tooltip and offers no picker', async () => {
  boot([ALPHA]);
  try {
    await run('mlview.visualizeWorkspace');
    const tooltip = statusItem().tooltip;
    assert.equal(typeof tooltip, 'string', 'a single folder must not become a MarkdownString');
    assert.ok(!tooltip.includes('Folder:'), 'nothing to choose between, so nothing is said');
    assert.ok(!tooltip.includes('command:'));
  } finally {
    shutdown();
  }
});

test('the status-bar tooltip names the active folder and carries the picker command', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace');
    const tooltip = statusItem().tooltip;
    assert.equal(typeof tooltip, 'object', 'two folders make the tooltip a MarkdownString');
    assert.equal(tooltip.isTrusted, true, 'a command link needs a trusted markdown string');
    assert.match(tooltip.value, /Folder: ws0/);
    // The honesty clause: a count that describes one of two folders must say so.
    assert.match(tooltip.value, /1 other folder in this workspace is not shown here/);
    assert.match(tooltip.value, /\(command:mlview\.activeFolder\)/);
  } finally {
    shutdown();
  }
});

test('MLView: Select Active Folder analyzes the second folder, which nothing else would', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace');
    assert.deepEqual(analyzedRoots(), [ALPHA]);

    vscode.__answerQuickPick(1); // the second row of the folder pick
    await run('mlview.activeFolder');
    assert.deepEqual(analyzedRoots(), [ALPHA, BETA], 'the picked folder is the one analyzed');

    const pick = vscode.__recorded.quickPicks.at(-1);
    assert.deepEqual(
      pick.items.map((i) => i.label),
      ['ws0', 'ws1']
    );
    assert.equal(pick.items[0].description, 'active', 'the current folder is marked');
    assert.deepEqual(
      pick.items.map((i) => i.detail),
      [ALPHA, BETA],
      'two folders can share a name, so the path is what disambiguates them'
    );
    assert.match(statusItem().tooltip.value, /Folder: ws1/);
  } finally {
    shutdown();
  }
});

test('the Problems panel holds BOTH folders once both are analyzed, not the last one', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace');
    const afterAlpha = [...collection().entries.keys()];
    assert.ok(afterAlpha.length > 0);
    assert.ok(afterAlpha.every((p) => p.startsWith(ALPHA)));

    vscode.__answerQuickPick(1);
    await run('mlview.activeFolder');

    const both = [...collection().entries.keys()];
    assert.ok(
      both.some((p) => p.startsWith(ALPHA)),
      'analysing beta must not clear alpha - the Problems panel is a WINDOW surface'
    );
    assert.ok(both.some((p) => p.startsWith(BETA)));
    assert.equal(both.length, afterAlpha.length * 2);
  } finally {
    shutdown();
  }
});

test('closing a folder drops its graph and its squiggles, and keeps the survivor', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace');
    vscode.__answerQuickPick(1);
    await run('mlview.activeFolder');
    assert.ok([...collection().entries.keys()].some((p) => p.startsWith(BETA)));

    vscode.__setWorkspaceFolders([ALPHA]);
    for (const listener of vscode.__recorded.folderListeners) {
      listener({ added: [], removed: [] });
    }
    const left = [...collection().entries.keys()];
    assert.ok(left.length > 0, 'the folder that is still open keeps its findings');
    assert.ok(
      left.every((p) => p.startsWith(ALPHA)),
      'the closed folder cannot go on publishing diagnostics for files nobody has open'
    );
  } finally {
    shutdown();
  }
});

test('the language-model tools analyze the ACTIVE folder, not workspaceFolders[0]', async () => {
  vscode.__reset();
  vscode.__setWorkspaceFolders([ALPHA, BETA]);
  vscode.__setConfig('mlview', 'pythonPath', FAKE_PYTHON);
  vscode.__enableChatAndLm();
  installExecFileStub();
  extension.activate(makeContext());
  try {
    vscode.__answerQuickPick(1);
    await run('mlview.activeFolder');
    spawns = [];

    const tool = vscode.__recorded.tools.get('mlview_analyzeWorkspace');
    assert.ok(tool, 'the LM tools must be registered');
    const result = await tool.invoke({ input: {} }, undefined);
    const answer = String(result.content[0].value);
    assert.ok(answer.length > 0);
    assert.ok(
      answer.includes('MLView analyzed'),
      'the tool answers with a digest, not an error'
    );
    // The graph beta already had is reused when it is fresh, so the assertion is about the
    // ANSWER's root rather than about a spawn that need not happen.
    assert.deepEqual(
      analyzedRoots().filter((r) => r === ALPHA),
      [],
      'a question asked while beta is active must never be answered from alpha'
    );
  } finally {
    shutdown();
  }
});

test('CodeLens for a file uses ITS folder graph, not the active folder', async () => {
  boot();
  try {
    await run('mlview.visualizeWorkspace'); // alpha is analyzed and active
    vscode.__answerQuickPick(1);
    await run('mlview.activeFolder'); // beta is now active; alpha is still analyzed

    const { provider } = vscode.__recorded.codeLensProviders.at(-1);
    const document = (root) => ({
      uri: vscode.Uri.file(`${root}/train.py`),
      languageId: 'python',
      lineCount: 400
    });

    // A file in the folder that is NOT active must still get its own lenses. Before H10 the
    // provider read one graph, so this returned alpha's units for a beta file - the same line
    // numbers on a different project - or nothing at all.
    const inBeta = provider.provideCodeLenses(document(BETA));
    const inAlpha = provider.provideCodeLenses(document(ALPHA));
    assert.ok(inBeta.length > 0, 'the active folder answers');
    assert.ok(inAlpha.length > 0, 'and so does the one that is merely open');
    assert.deepEqual(
      inAlpha.map((l) => l.command.arguments[0].nodeId).sort(),
      inBeta.map((l) => l.command.arguments[0].nodeId).sort(),
      'the two graphs are the same shape, so the lenses are - what differs is which graph answered'
    );

    // And a file in neither folder gets nothing rather than the active folder\'s lenses.
    assert.deepEqual(provider.provideCodeLenses(document('C:/ws/gamma')), []);
  } finally {
    shutdown();
  }
});

// ------------------------------------------------------ the honesty clause, word for word

/**
 * 11.40: "The tooltip states what it is not showing." It is the ONLY user-visible text on the
 * multi-root path, and it is read exactly when a user is unsure which folder the counts
 * describe — so it has to be a sentence. The wave-1 test only ever exercised the one-other
 * case, where a hard-coded singular verb is invisible; three folders said "2 other folders
 * ... is not shown here".
 */
test('the tooltip line agrees in number for every folder count, not just for two', () => {
  const { folderTooltipLine } = require('./harness.js').api;
  assert.equal(folderTooltipLine(['a'], 'a'), undefined, 'nothing to choose between');
  assert.equal(
    folderTooltipLine(['a', 'b'], 'a'),
    'Folder: a — 1 other folder in this workspace is not shown here.'
  );
  assert.equal(
    folderTooltipLine(['a', 'b', 'c'], 'a'),
    'Folder: a — 2 other folders in this workspace are not shown here.'
  );
  assert.equal(
    folderTooltipLine(['a', 'b', 'c', 'd', 'e'], 'a'),
    'Folder: a — 4 other folders in this workspace are not shown here.'
  );
  // Two folders can share a name, so the count is `names.length - 1` and never a filter.
  assert.match(folderTooltipLine(['api', 'api', 'api'], 'api'), /2 other folders .* are not/);
});
