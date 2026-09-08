'use strict';
/**
 * Host-level regression tests: the real `out/extension.js` driven through the mocked `vscode`,
 * with `child_process.execFile` stubbed so no interpreter and no analyzer are needed.
 *
 * These cover the four things that unit tests over pure functions structurally cannot see,
 * because each of them is about ORDER and LIFECYCLE rather than about a value:
 *
 *   - a `revealNode` posted before the webview has booted must still arrive, and must arrive
 *     after the graph (`App.focusNode` needs the index to resolve the id);
 *   - every graph after the first must carry `preserve`, or a Ctrl+S throws the viewport away;
 *   - opening the diagram must spawn the analyzer ONCE, and the spinner must not blink off
 *     while a run is still in flight;
 *   - `mlview.disabledRules` must reach the canvas as a `setFilter` keep-list.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const cp = require('node:child_process');

const { readSampleGraph } = require('./harness.js'); // installs the `vscode` -> mock hook
const vscode = require('./mock-vscode.js');

const EXTENSION_ROOT = path.join(__dirname, '..');
const WORKSPACE = 'C:/mlview-test-workspace';
const FAKE_PYTHON = 'C:/mlview-test-workspace/.venv/Scripts/python.exe';

const extension = require(path.join(EXTENSION_ROOT, 'out', 'extension.js'));

// ---------------------------------------------------------------- the stubbed interpreter

const realExecFile = cp.execFile;
/** Every `analyze` argv the extension asked for, in order. */
let spawns = [];
/** EVERY child process the extension asked for: the probe and the handshake included. */
let childProcesses = [];

/**
 * H3: `stderrChunks` lets a test play the analyzer's `--progress-json` stream. The
 * chunks are delivered on the next tick, exactly like a real child's stderr, so the
 * ordering against the callback that ends the run is the ordering production sees.
 */
function fakeChild(stderrChunks = [], delayMs = 1) {
  const listeners = { data: [], end: [] };
  if (stderrChunks.length > 0) {
    setTimeout(() => {
      for (const chunk of stderrChunks) {
        for (const listener of listeners.data) listener(chunk);
      }
      for (const listener of listeners.end) listener();
    }, delayMs);
  }
  return {
    stderr: {
      setEncoding() {},
      on(event, listener) {
        if (listeners[event]) listeners[event].push(listener);
      }
    },
    stdout: { setEncoding() {}, on() {} },
    on() {},
    kill() {},
    exitCode: null,
    killed: false
  };
}

function installExecFileStub(graph, options = {}) {
  spawns = [];
  childProcesses = [];
  cp.execFile = function (file, args, opts, callback) {
    const done = typeof opts === 'function' ? opts : callback;
    childProcesses.push(args.join(' '));
    let stdout = '';
    let failure = null;
    if (args.includes('-c')) {
      stdout = JSON.stringify([3, 13, FAKE_PYTHON]); // the version probe
    } else if (args.includes('--version')) {
      stdout = JSON.stringify({ version: '0.1.0', schemaVersion: '1.0' }); // the core handshake
    } else if (args.includes('analyze')) {
      spawns.push(args.join(' '));
      if (options.failAnalyze) {
        // A spawn failure, exactly like a bad mlview.pythonPath or a missing core.
        failure = Object.assign(new Error('spawn ENOENT'), { code: 'ENOENT' });
      } else {
        stdout = JSON.stringify(graph);
      }
    }
    setTimeout(() => done(failure, stdout, ''), 5);
    return fakeChild(
      args.includes('--progress-json') ? options.stderrChunks ?? [] : [],
      options.stderrDelayMs ?? 1
    );
  };
}

function restoreExecFile() {
  cp.execFile = realExecFile;
}

function makeContext(savedState) {
  const state = new Map(savedState ? Object.entries(savedState) : []);
  return {
    subscriptions: [],
    extensionPath: EXTENSION_ROOT,
    extensionUri: vscode.Uri.file(EXTENSION_ROOT),
    extension: { packageJSON: { version: '0.1.0' } },
    workspaceState: {
      get: (key) => state.get(key),
      update: async (key, value) => void state.set(key, value)
    },
    globalState: { get: (key) => state.get(key), update: async () => undefined }
  };
}

function sampleGraph() {
  const graph = readSampleGraph();
  graph.workspace.root = WORKSPACE;
  return graph;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Boot the extension against the mock with an interpreter that answers instantly. */
function boot(options = {}) {
  vscode.__reset();
  vscode.__setWorkspaceFolders([WORKSPACE]);
  vscode.__setConfig('mlview', 'pythonPath', FAKE_PYTHON);
  for (const [key, value] of Object.entries(options.config ?? {})) {
    vscode.__setConfig('mlview', key, value);
  }
  installExecFileStub(options.graph ?? sampleGraph(), options);
  const ctx = makeContext(options.savedState);
  extension.activate(ctx);
  return ctx;
}

function shutdown() {
  extension.deactivate();
  restoreExecFile();
  vscode.__disableChatAndLm();
  vscode.__reset();
}

const run = (id, ...args) => vscode.__recorded.commands.get(id)(...args);
const panel = () => vscode.__recorded.panels[vscode.__recorded.panels.length - 1];

// ---------------------------------------------------------------- VSX-01

test('a reveal issued while the panel is closed is delivered AFTER the graph', async () => {
  boot();
  try {
    const graph = sampleGraph();
    const nodeId = graph.nodes[3].id;
    void run('mlview.revealInDiagram', { nodeId });
    await sleep(120);

    const created = panel();
    assert.ok(created, 'the reveal opened the diagram panel');
    assert.deepEqual(
      created.postedTypes(),
      [],
      'nothing may be posted before the webview has said ready - it would be dropped'
    );

    created.fire({ v: 1, type: 'ready' });
    await sleep(120);

    const types = created.postedTypes();
    assert.ok(types.includes('revealNode'), `revealNode was never delivered: ${types.join(', ')}`);
    assert.ok(
      types.indexOf('revealNode') > types.indexOf('graph'),
      `revealNode must arrive after the graph, got ${types.join(', ')}`
    );
    const reveal = created.posted.find((m) => m.type === 'revealNode');
    assert.equal(reveal.nodeId, nodeId);
    assert.equal(reveal.center, true);
  } finally {
    shutdown();
  }
});

test('the newest reveal wins and a queued reveal never outlives the panel', async () => {
  boot();
  try {
    const graph = sampleGraph();
    void run('mlview.revealInDiagram', { nodeId: graph.nodes[1].id });
    await sleep(80);
    void run('mlview.revealInDiagram', { nodeId: graph.nodes[2].id });
    await sleep(80);

    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(120);

    const reveals = created.posted.filter((m) => m.type === 'revealNode');
    assert.equal(reveals.length, 1, 'two presses before boot collapse to one reveal');
    assert.equal(reveals[0].nodeId, graph.nodes[2].id, 'the newest press wins');
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-02

test('the graph carries preserve from the serialized view state after a window reload', async () => {
  const viewport = { x: -1234, y: -567, zoom: 2.5 };
  boot({
    savedState: {
      'mlview.viewState': {
        viewport,
        selection: { kind: 'node', id: 'n:000000000001' },
        collapsed: ['n:000000000002'],
        filters: {},
        railTab: 'issues'
      }
    }
  });
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    panel().fire({ v: 1, type: 'ready' });
    await sleep(200);

    const graphs = panel().posted.filter((m) => m.type === 'graph');
    assert.ok(graphs.length >= 1);
    assert.deepEqual(graphs[0].preserve.viewport, viewport, 'the restored viewport must survive');
    assert.deepEqual(graphs[0].preserve.selection, { kind: 'node', id: 'n:000000000001' });
    assert.deepEqual(graphs[0].preserve.collapsed, ['n:000000000002']);
  } finally {
    shutdown();
  }
});

test('a re-analysis preserves the viewport the webview last reported', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(200);

    const first = created.posted.filter((m) => m.type === 'graph');
    assert.equal(first[0].preserve, undefined, 'the very first graph of a fresh panel fits');

    created.fire({
      v: 1,
      type: 'saveState',
      state: {
        viewport: { x: -10, y: -20, zoom: 1.75 },
        selection: null,
        collapsed: [],
        filters: {},
        railTab: 'issues'
      }
    });
    await sleep(20);

    const before = created.posted.length;
    void run('mlview.refresh');
    await sleep(250);

    const next = created.posted.slice(before).filter((m) => m.type === 'graph');
    assert.equal(next.length, 1, 'the re-analysis produced one graph');
    assert.deepEqual(next[0].preserve.viewport, { x: -10, y: -20, zoom: 1.75 });
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-04

test('opening the diagram spawns the analyzer once and keeps the spinner up', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(40);
    panel().fire({ v: 1, type: 'ready' }); // the webview boots mid-analysis
    await sleep(300);

    assert.equal(spawns.length, 1, `expected one analyzer spawn, got ${spawns.length}`);
    const bar = vscode.__recorded.statusBarItems[vscode.__recorded.statusBarItems.length - 1];
    const idleAfterBusy = bar.texts.findIndex((t, i) => i > 0 && /sync~spin/.test(bar.texts[i - 1]) && t === '$(graph) MLView');
    assert.equal(idleAfterBusy, -1, `the spinner blinked off mid-analysis: ${bar.texts.join(' -> ')}`);
    assert.match(bar.texts[bar.texts.length - 1], /MLView: \d+ high/);
  } finally {
    shutdown();
  }
});

test('a second visualize while one is in flight does not double-spawn', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    void run('mlview.showIssues'); // ensureGraph() joins instead of starting its own run
    await sleep(40);
    panel().fire({ v: 1, type: 'ready' });
    await sleep(300);
    assert.equal(spawns.length, 1, `expected one analyzer spawn, got ${spawns.length}`);
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-06

test('mlview.disabledRules reaches the diagram as a setFilter keep-list', async () => {
  const graph = sampleGraph();
  const hidden = graph.issues[0].code;
  boot({ graph, config: { disabledRules: [hidden] } });
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(250);

    const filters = created.posted.filter((m) => m.type === 'setFilter');
    assert.ok(filters.length > 0, 'the host must tell the canvas which codes survive');
    const codes = filters[filters.length - 1].codes;
    assert.ok(!codes.includes(hidden), `${hidden} must not be in the keep-list`);
    const expected = [...new Set(graph.issues.map((i) => i.code))].filter((c) => c !== hidden);
    for (const code of expected) {
      assert.ok(codes.includes(code), `${code} is still enabled and must be kept`);
    }
    const types = created.postedTypes();
    assert.ok(types.indexOf('setFilter') > types.indexOf('graph'), 'setFilter follows the graph');
  } finally {
    shutdown();
  }
});

test('no rules disabled means no code restriction at all', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    panel().fire({ v: 1, type: 'ready' });
    await sleep(250);
    const filters = panel().posted.filter((m) => m.type === 'setFilter');
    assert.ok(filters.length > 0);
    assert.deepEqual(filters[filters.length - 1].codes, [], 'an empty keep-list is "show all"');
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-05

test('the language-model tools refuse a model-supplied path outside the workspace', async () => {
  vscode.__enableChatAndLm();
  boot();
  try {
    const tool = vscode.__recorded.tools.get('mlview_analyzeWorkspace');
    assert.ok(tool, 'the analyze tool is registered when vscode.lm exists');
    const source = new vscode.CancellationTokenSource();
    // An absolute path outside the workspace, spelled the way the platform
    // spells one: `C:/...` is not absolute on POSIX, so there it resolves INSIDE
    // the workspace and the refusal under test is never reached (CI-01).
    const outside = process.platform === 'win32' ? 'C:/Windows/System32' : '/etc';
    for (const escape of ['../..', '../../analyzer/src/mlview', outside, '../../../']) {
      await assert.rejects(
        () => tool.invoke({ input: { path: escape } }, source.token),
        /only analyzes paths inside the open workspace/,
        `${escape} must be refused`
      );
    }
    assert.equal(spawns.length, 0, 'a refused path must never reach the analyzer');

    // ...and a legitimate workspace-relative path still works.
    const ok = await tool.invoke({ input: { path: 'train.py' } }, source.token);
    assert.match(ok.content[0].value, /MLView analyzed/);
    assert.equal(spawns.length, 1);
    assert.ok(spawns[0].includes(path.resolve(WORKSPACE, 'train.py')));
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-08

test('the HTML export uses the folder-scoped settings, not the user-level ones', async () => {
  boot();
  const out = `${WORKSPACE}/mlview-report.html`;
  const realDialog = vscode.window.showSaveDialog;
  // A folder-level .vscode/settings.json override of mlview.maxNodes.
  vscode.__setConfig('mlview', 'maxNodes', 400);
  vscode.__setConfig('mlview', 'maxNodes', 20, WORKSPACE);
  vscode.window.showSaveDialog = async () => vscode.Uri.file(out);
  try {
    await run('mlview.exportHtml');
    await sleep(120);
    const exported = spawns.find((argv) => argv.includes('--html'));
    assert.ok(exported, `no export spawn: ${spawns.join(' | ')}`);
    assert.match(exported, /--max-nodes 20\b/, `the export ignored the folder setting: ${exported}`);
  } finally {
    vscode.window.showSaveDialog = realDialog;
    shutdown();
  }
});

// ---------------------------------------------------------------- R2H-06

/**
 * What you see is what you export. A panel narrowed to one concern must not quietly export the
 * whole workspace: `--scope` (and the depth the viewer saved, §11.9) rides the export argv.
 * The report still embeds the FULL graph (§11.8), so a scope narrows the view, never the data.
 */
async function bootScopedPanel(scopeMessage, state) {
  await run('mlview.visualizeWorkspace');
  await sleep(200);
  const created = panel();
  created.fire({ v: 1, type: 'ready' });
  await sleep(120);
  if (state) {
    created.fire({ v: 1, type: 'saveState', state });
  }
  created.fire(scopeMessage);
  await sleep(60);
  return created;
}

test('the HTML export is taken at the scope the panel is showing', async () => {
  boot();
  const out = `${WORKSPACE}/mlview-report.html`;
  const realDialog = vscode.window.showSaveDialog;
  vscode.window.showSaveDialog = async () => vscode.Uri.file(out);
  try {
    await bootScopedPanel(
      { v: 1, type: 'scopeChanged', spec: 'concern:evaluation', label: 'Evaluation', nodes: 9, of: 45 },
      { scope: { spec: 'concern:evaluation', depth: 2 } }
    );
    await run('mlview.exportHtml');
    await sleep(200);

    const exported = spawns.find((argv) => argv.includes('--html'));
    assert.ok(exported, `no export spawn: ${spawns.join(' | ')}`);
    assert.match(exported, /--scope concern:evaluation\b/, `the export lost the scope: ${exported}`);
    assert.match(exported, /--depth 2\b/, `the export lost the depth: ${exported}`);
  } finally {
    vscode.window.showSaveDialog = realDialog;
    shutdown();
  }
});

test('an unscoped or cleared panel exports the whole workspace, argv unchanged', async () => {
  boot();
  const out = `${WORKSPACE}/mlview-report.html`;
  const realDialog = vscode.window.showSaveDialog;
  vscode.window.showSaveDialog = async () => vscode.Uri.file(out);
  try {
    // Scoped, then cleared: the clear must win, or a report would be frozen at a dead selector.
    const created = await bootScopedPanel(
      { v: 1, type: 'scopeChanged', spec: 'unit:train.validate', label: 'validate()', nodes: 9, of: 45 },
      { scope: { spec: 'unit:train.validate', depth: 1 } }
    );
    created.fire({ v: 1, type: 'scopeChanged', spec: null, label: 'Everything', nodes: 45, of: 45 });
    await sleep(60);

    await run('mlview.exportHtml');
    await sleep(200);

    const exported = spawns.find((argv) => argv.includes('--html'));
    assert.ok(exported, `no export spawn: ${spawns.join(' | ')}`);
    assert.ok(!exported.includes('--scope'), `an unscoped export must stay unscoped: ${exported}`);
    assert.ok(!exported.includes('--depth'), `an unscoped export must carry no depth: ${exported}`);
  } finally {
    vscode.window.showSaveDialog = realDialog;
    shutdown();
  }
});

// ---------------------------------------------------------------- deferred analysis events

test('a spinner queued before the webview booted is dropped once its graph has landed', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(300); // the analysis finishes while the webview is still booting
    const created = panel();
    // `graph` and `setFilter` are re-sent by onReady, so they may be posted early; the one-shot
    // spinner may not - it would sit on a webview that has no run to clear it.
    assert.ok(
      !created.postedTypes().includes('analysisStarted'),
      'analysisStarted must be held back until the webview can act on it'
    );

    created.fire({ v: 1, type: 'ready' });
    await sleep(120);

    const types = created.postedTypes();
    assert.ok(types.includes('graph'), `the graph must be re-sent on ready: ${types.join(', ')}`);
    assert.ok(
      !types.includes('analysisStarted'),
      `a stale spinner would never clear: ${types.join(', ')}`
    );
  } finally {
    shutdown();
  }
});

test('a webview that boots mid-analysis still gets its spinner', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(10);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(300);
    const types = created.postedTypes();
    assert.ok(types.includes('analysisStarted'), `no spinner: ${types.join(', ')}`);
    assert.ok(
      types.indexOf('analysisStarted') < types.indexOf('graph'),
      `the spinner must precede its graph: ${types.join(', ')}`
    );
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-R2-001

test('Restricted Mode: Export HTML Report spawns nothing at all', async () => {
  boot();
  const realDialog = vscode.window.showSaveDialog;
  vscode.window.showSaveDialog = async () => vscode.Uri.file(`${WORKSPACE}/report.html`);
  vscode.workspace.isTrusted = false;
  try {
    // The control: the command every other entry point goes through.
    await run('mlview.visualizeWorkspace');
    await sleep(60);
    assert.equal(childProcesses.length, 0, 'visualizeWorkspace is the known-good control');

    await run('mlview.exportHtml');
    await sleep(150);
    assert.equal(
      childProcesses.length,
      0,
      `the export spawned ${childProcesses.length} process(es) in Restricted Mode: ` +
        childProcesses.join(' | ')
    );
    assert.equal(spawns.length, 0, 'no analyzer may run in Restricted Mode');
    const warnings = vscode.__recorded.messages.filter(([level]) => level === 'warn');
    assert.ok(
      warnings.some(([, text]) => /Restricted Mode/.test(text)),
      `the user must be told why nothing happened: ${JSON.stringify(vscode.__recorded.messages)}`
    );
  } finally {
    vscode.window.showSaveDialog = realDialog;
    shutdown();
  }
});

test('Restricted Mode: the process seam itself refuses, whoever calls it', async () => {
  vscode.__enableChatAndLm();
  boot();
  vscode.workspace.isTrusted = false;
  try {
    // The webview's own export button takes the same path as the palette command.
    void run('mlview.visualize');
    await sleep(60);
    const tool = vscode.__recorded.tools.get('mlview_analyzeWorkspace');
    const source = new vscode.CancellationTokenSource();
    await assert.rejects(
      () => tool.invoke({ input: {} }, source.token),
      /Restricted Mode/,
      'the language-model tool must refuse too'
    );
    assert.equal(childProcesses.length, 0, `spawned: ${childProcesses.join(' | ')}`);
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-R2-003

test('a first analysis that fails before the webview boots is not repeated by ready', async () => {
  boot({ failAnalyze: true });
  try {
    await run('mlview.visualizeWorkspace');
    await sleep(120); // run 1 has already failed by the time the webview boots
    const created = panel();
    assert.ok(created, 'the command opened the panel');
    created.fire({ v: 1, type: 'ready' });
    await sleep(250);

    assert.equal(spawns.length, 1, `the failing analysis ran ${spawns.length} times`);
    const failures = created.posted.filter((m) => m.type === 'analysisFailed');
    assert.equal(
      failures.length,
      1,
      `the viewer must get exactly one banner: ${JSON.stringify(created.postedTypes())}`
    );
    const started = created.posted.filter((m) => m.type === 'analysisStarted');
    assert.equal(
      started.length,
      0,
      'a spinner whose run already failed would never clear: ' + JSON.stringify(started)
    );
    const errors = vscode.__recorded.messages.filter(([level]) => level === 'error');
    assert.equal(errors.length, 1, `one failure, one notification: ${JSON.stringify(errors)}`);
  } finally {
    shutdown();
  }
});

test('after a failure, a successful re-analysis clears the remembered banner', async () => {
  boot({ failAnalyze: true });
  try {
    await run('mlview.visualizeWorkspace');
    await sleep(120);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(200);
    assert.equal(spawns.length, 1);

    // The user fixes the interpreter and hits Retry: the next run must actually happen.
    installExecFileStub(sampleGraph());
    await run('mlview.refresh');
    await sleep(250);
    assert.equal(spawns.length, 1, 'the retry ran');
    assert.ok(created.posted.some((m) => m.type === 'graph'), 'the graph reached the viewer');
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-R2-004

test('the status bar and the issue quick pick agree with the Problems panel', async () => {
  const graph = sampleGraph();
  // Everything below 0.95 is published nowhere but the canvas.
  boot({ graph, config: { minConfidence: 0.95 } });
  const realQuickPick = vscode.window.showQuickPick;
  let pickedItems;
  vscode.window.showQuickPick = async (items) => {
    pickedItems = items;
    return undefined;
  };
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    panel().fire({ v: 1, type: 'ready' });
    await sleep(250);

    const expected = graph.issues.filter((i) => i.confidence >= 0.95 && !i.suppressed);
    assert.ok(expected.length > 0 && expected.length < graph.issues.length, 'a meaningful split');

    const collection = vscode.__recorded.diagnosticCollections[0];
    const published = [...collection.entries.values()].reduce((n, list) => n + list.length, 0);
    assert.equal(published, expected.length, 'the Problems panel is the reference');

    await run('mlview.showIssues');
    await sleep(60);
    assert.equal(
      pickedItems.length,
      expected.length,
      'the quick pick claims to be the same list as the Problems panel'
    );

    const counts = { high: 0, medium: 0, low: 0 };
    for (const issue of expected) {
      counts[issue.severity] += 1;
    }
    const parts = ['high', 'medium', 'low']
      .filter((sev) => counts[sev] > 0)
      .map((sev) => `${counts[sev]} ${sev === 'medium' ? 'med' : sev}`);
    const bar = vscode.__recorded.statusBarItems[vscode.__recorded.statusBarItems.length - 1];
    assert.equal(bar.text, `$(graph) MLView: ${parts.join(' · ')}`);
    // PACKAGING appends the core line, so the count is asserted as the FIRST line and
    // the core line is asserted for what it must always say: which analyzer answered.
    const [headline, ...rest] = String(bar.tooltip).split('\n');
    assert.equal(
      headline,
      `MLView: ${counts.high} high, ${counts.medium} medium, ${counts.low} low`
    );
    assert.match(
      rest.join('\n'),
      /^core: mlview 0\.1\.0 (installed in the interpreter|bundled with the extension)/,
      `the tooltip must name which core is in use, got ${JSON.stringify(bar.tooltip)}`
    );
  } finally {
    vscode.window.showQuickPick = realQuickPick;
    shutdown();
  }
});

// ---------------------------------------------------------------- VSX-R2-005

test('prepareInvocation tolerates a missing input on every tool', async () => {
  vscode.__enableChatAndLm();
  boot();
  try {
    const source = new vscode.CancellationTokenSource();
    const analyze = vscode.__recorded.tools.get('mlview_analyzeWorkspace');
    const prepared = analyze.prepareInvocation({}, source.token);
    assert.match(prepared.invocationMessage, /Analyzing ML workflow/);

    const issues = vscode.__recorded.tools.get('mlview_listIssues');
    assert.match(issues.prepareInvocation({}, source.token).invocationMessage, /ML issues/);

    // The confirmation dialog is the contract-mandated safety step for the side-effecting tool.
    const diagram = vscode.__recorded.tools.get('mlview_showDiagram');
    const confirm = diagram.prepareInvocation({}, source.token).confirmationMessages;
    assert.equal(confirm.title, 'Open MLView diagram?');
    assert.match(confirm.message, /open the workflow diagram/);

    // ...and it still names the node when there is one.
    const focused = diagram.prepareInvocation({ input: { focusNodeId: 'n:abc123abc123' } });
    assert.match(focused.confirmationMessages.message, /n:abc123abc123/);
    assert.equal(spawns.length, 0, 'preparing an invocation never analyzes');
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- Feature 2 (CONTRACTS §11.11)

/** Put the cursor on `train.py`, 0-based editor line `editorLine`. */
function focusTrainPy(editorLine) {
  vscode.window.activeTextEditor = {
    document: {
      uri: vscode.Uri.file(`${WORKSPACE}/train.py`),
      languageId: 'python',
      fileName: 'train.py'
    },
    selection: { active: { line: editorLine, character: 4 } }
  };
}

test('a scope issued while the panel is closed is delivered AFTER the graph', async () => {
  boot();
  try {
    focusTrainPy(43); // graph line 44 - inside the batch loop of train()
    void run('mlview.scopeToSymbol');
    await sleep(120);

    const created = panel();
    assert.ok(created, 'the scope command opened the diagram panel');
    assert.deepEqual(created.postedTypes(), [], 'nothing may be posted before `ready`');

    created.fire({ v: 1, type: 'ready' });
    await sleep(150);

    const types = created.postedTypes();
    assert.ok(types.includes('setScope'), `setScope was never delivered: ${types.join(', ')}`);
    assert.ok(
      types.indexOf('setScope') > types.indexOf('graph'),
      `setScope must arrive after the graph it projects, got ${types.join(', ')}`
    );
    const scope = created.posted.find((m) => m.type === 'setScope');
    // The narrowest node at line 44 is the batch loop; the SCOPE is the unit that contains it.
    assert.deepEqual(scope, { v: 1, type: 'setScope', spec: 'unit:train.train' });
    assert.equal(spawns.length, 1, 'a scope re-projects in the viewer; it never re-analyzes');
  } finally {
    vscode.window.activeTextEditor = undefined;
    shutdown();
  }
});

test('scopeChanged retitles the panel, and clearing puts the plain title back', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    assert.equal(created.title, 'MLView');

    created.fire({
      v: 1,
      type: 'scopeChanged',
      spec: 'unit:train.train',
      label: 'train()',
      nodes: 4,
      of: 12
    });
    await sleep(20);
    assert.equal(created.title, 'MLView — train()');
    assert.equal(created.description, '4 of 12 nodes');
    assert.equal(spawns.length, 1, 'scopeChanged must never trigger a re-analysis');

    focusTrainPy(43);
    void run('mlview.clearScope');
    await sleep(60);
    const cleared = created.posted.filter((m) => m.type === 'setScope');
    assert.deepEqual(cleared, [{ v: 1, type: 'setScope', spec: null }]);

    created.fire({
      v: 1,
      type: 'scopeChanged',
      spec: null,
      label: 'Everything',
      nodes: 12,
      of: 12
    });
    await sleep(20);
    assert.equal(created.title, 'MLView');
    assert.equal(created.description, '12 of 12 nodes');
  } finally {
    vscode.window.activeTextEditor = undefined;
    shutdown();
  }
});

test('an unknown message from a newer viewer is still dropped, scope or not', async () => {
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    const before = created.title;
    created.fire({ v: 1, type: 'scopeSomethingNew', spec: 'unit:train.train' });
    created.fire({ v: 2, type: 'scopeChanged', spec: 'x', label: 'y', nodes: 1, of: 2 });
    created.fire({ v: 1, type: 'scopeChanged', spec: 'x' }); // malformed: no label/counts
    await sleep(20);
    assert.equal(created.title, before, 'only a well-formed scopeChanged may retitle the panel');
    assert.equal(created.description, undefined);
  } finally {
    shutdown();
  }
});

// ------------------------------------------------------- ROADMAP COVERAGE / CLEANUP (host)

/** Put the cursor in a Python file that is NOT at the workspace root. */
function focusPackageFile(relative) {
  vscode.window.activeTextEditor = {
    document: {
      uri: vscode.Uri.file(`${WORKSPACE}/${relative}`),
      languageId: 'python',
      fileName: relative.split('/').pop()
    },
    selection: { active: { line: 0, character: 0 } }
  };
}

test('Visualize (Current File) analyses the containing directory, then scopes to the file', async () => {
  // COVERAGE: analysing `train.py` alone reports 3 findings where its directory reports 7, and
  // MLV301/302/401/501 cannot fire at all. The default `package` scope analyses the directory
  // and narrows the DIAGRAM instead, so the user sees the same file and gets the real findings.
  boot();
  try {
    focusPackageFile('pkg/train.py');
    void run('mlview.visualize');
    await sleep(80);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);

    assert.equal(spawns.length, 1, 'one analysis, not one per surface');
    const argv = spawns[0];
    assert.ok(
      argv.includes(`${WORKSPACE}/pkg`) || argv.includes(`${WORKSPACE}\pkg`),
      `the analyzer was pointed at the package directory, got: ${argv}`
    );
    assert.ok(!/train\.py/.test(argv), `the file itself must not be the analyzed path: ${argv}`);

    const scopes = created.posted.filter((m) => m.type === 'setScope');
    assert.deepEqual(scopes, [{ v: 1, type: 'setScope', spec: 'file:pkg/train.py' }]);
    const types = created.postedTypes();
    assert.ok(
      types.indexOf('setScope') > types.indexOf('graph'),
      `the projection must arrive after the document it projects: ${types.join(', ')}`
    );
  } finally {
    vscode.window.activeTextEditor = undefined;
    shutdown();
  }
});

test('currentFileAnalysisScope="file" keeps the old single-file run and posts no scope', async () => {
  boot({ config: { currentFileAnalysisScope: 'file' } });
  try {
    focusPackageFile('pkg/train.py');
    void run('mlview.visualize');
    await sleep(80);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);

    assert.ok(/train\.py/.test(spawns[0]), `the file itself is the analyzed path: ${spawns[0]}`);
    assert.deepEqual(created.posted.filter((m) => m.type === 'setScope'), []);
  } finally {
    vscode.window.activeTextEditor = undefined;
    shutdown();
  }
});

test('a save-triggered re-analysis does not re-post the file scope over the user\'s own', async () => {
  boot();
  try {
    focusPackageFile('pkg/train.py');
    void run('mlview.visualize');
    await sleep(80);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    assert.equal(created.posted.filter((m) => m.type === 'setScope').length, 1);

    void run('mlview.refresh');
    await sleep(200);
    assert.equal(
      created.posted.filter((m) => m.type === 'setScope').length,
      1,
      'the scope is posted once per command; after that the viewer owns it'
    );
  } finally {
    vscode.window.activeTextEditor = undefined;
    shutdown();
  }
});

test('canAskAssistant follows the chat API, and askAssistant opens chat with the prompt', async () => {
  // CLEANUP 5: the viewer composed the prompt and posted it; the host logged it and stopped.
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    const init = created.posted.find((m) => m.type === 'init');
    assert.equal(init.capabilities.canAskAssistant, false, 'no chat API in this build');
  } finally {
    shutdown();
  }

  vscode.__enableChatAndLm();
  const executed = [];
  const realExecute = vscode.commands.executeCommand;
  vscode.commands.executeCommand = async (id, arg) => void executed.push([id, arg]);
  boot();
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    const init = created.posted.find((m) => m.type === 'init');
    assert.equal(init.capabilities.canAskAssistant, true, 'the chat API is present');

    created.fire({ v: 1, type: 'askAssistant', nodeId: 'n:1', prompt: 'Explain SmallCNN.' });
    await sleep(40);
    const opened = executed.find(([id]) => id === 'workbench.action.chat.open');
    assert.ok(opened, `chat was never opened: ${executed.map(([id]) => id).join(', ')}`);
    assert.equal(opened[1].query, '@mlview Explain SmallCNN.');
  } finally {
    vscode.commands.executeCommand = realExecute;
    shutdown();
  }
});

test('a blind run says so on the panel tab, not just inside the canvas', async () => {
  const graph = sampleGraph();
  graph.diagnostics = [
    {
      kind: 'single_file_analysis',
      message: 'Only train.py was analyzed; 4 cross-file rules could not run.',
      codes: ['MLV301', 'MLV302', 'MLV401', 'MLV501']
    }
  ];
  boot({ graph });
  try {
    void run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);
    assert.equal(created.description, 'coverage: incomplete (1 blind spot)');

    created.fire({
      v: 1,
      type: 'scopeChanged',
      spec: 'file:train.py',
      label: 'train.py',
      nodes: 9,
      of: 45
    });
    await sleep(20);
    assert.equal(created.description, '9 of 45 nodes · coverage: incomplete (1 blind spot)');
  } finally {
    shutdown();
  }
});

// ---------------------------------------------------------------- H3 + MLV-P10

test('progress frames are asked for only when a panel is live, and reach the viewer', async () => {
  const frames = [
    '{"t":"progress","done":1,"total":3,"file":"a.py"}\n',
    'mlview: INFO a note that is not a frame\n',
    '{"t":"progress","done":3,"total":3,"file":"c.py"}\n'
  ];
  boot({ stderrChunks: frames });
  try {
    // The headless path first: `mlview.showIssues` analyzes with no panel open.
    await run('mlview.showIssues');
    await sleep(120);
    assert.equal(spawns.length, 1);
    assert.ok(
      !spawns[0].includes('--progress-json'),
      `a headless run must emit the bytes it always emitted: ${spawns[0]}`
    );

    await run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(200);

    const withPanel = spawns[spawns.length - 1];
    assert.ok(withPanel.includes('--progress-json'), `expected the flag, got: ${withPanel}`);
    const progress = created.posted.filter((m) => m.type === 'analysisProgress');
    assert.deepEqual(
      progress.map((m) => [m.done, m.total, m.file]),
      [
        [1, 3, 'a.py'],
        [3, 3, 'c.py']
      ]
    );
    for (const message of progress) {
      assert.equal(message.v, 1);
      assert.match(message.requestId, /^analyze-/, 'every frame is correlated with its run');
    }
    // The non-frame stderr line still reached the output channel.
    const channel = vscode.__recorded.outputChannels[0];
    const logged = (channel?.lines ?? []).join('\n');
    assert.ok(
      logged.includes('a note that is not a frame'),
      'ordinary stderr must still reach the log'
    );
    assert.ok(!logged.includes('"t":"progress"'), 'a frame is not a log line');
  } finally {
    shutdown();
  }
});

test('a progress frame that arrives after the run failed never reaches the viewer', async () => {
  // The child's stderr and its exit are two separate events: a buffered chunk can land
  // after the banner is up, and a progress bar drawn over an error message is worse
  // than no bar at all. `failAnalyze` settles the run at ~5 ms; the frames arrive at 80.
  boot({
    failAnalyze: true,
    stderrDelayMs: 80,
    stderrChunks: ['{"t":"progress","done":2,"total":9,"file":"late.py"}\n']
  });
  try {
    await run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(300);

    const types = created.postedTypes();
    assert.ok(types.includes('analysisFailed'), `the run must have failed: ${types.join(', ')}`);
    const failedAt = types.indexOf('analysisFailed');
    const late = types.slice(failedAt).filter((t) => t === 'analysisProgress');
    assert.deepEqual(late, [], `a frame was drawn over the error banner: ${types.join(', ')}`);
  } finally {
    shutdown();
  }
});

test('a suppressRule message from the diagram runs the same host code as the lightbulb', async () => {
  boot();
  const copied = [];
  const realClipboard = vscode.env.clipboard.writeText;
  vscode.env.clipboard.writeText = async (text) => void copied.push(text);
  try {
    await run('mlview.visualizeWorkspace');
    await sleep(60);
    const created = panel();
    created.fire({ v: 1, type: 'ready' });
    await sleep(150);

    created.fire({ v: 1, type: 'suppressRule', code: 'MLV201', action: 'copy' });
    await sleep(60);
    assert.deepEqual(copied, ['# mlview: ignore[MLV201]']);

    // A malformed message is logged and ignored, never acted on.
    created.fire({ v: 1, type: 'suppressRule', code: 'nonsense', action: 'copy' });
    await sleep(60);
    assert.equal(copied.length, 1, 'only a real rule code is ever acted on');
  } finally {
    vscode.env.clipboard.writeText = realClipboard;
    shutdown();
  }
});
