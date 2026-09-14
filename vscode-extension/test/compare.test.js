'use strict';
/**
 * VIEW-08 — compare two analyses, host half
 * (docs/contracts/11.43-host-fixes-and-comparison.md).
 *
 * The analyzer owns the comparison (CONTRACTS §11.38); these tests hold the four host
 * promises that make it usable and safe:
 *
 *   1. The host NEVER computes a diff. `mlview diff BASE HEAD --json -` is the only source,
 *      and the argv is asserted verbatim.
 *   2. The overlay is a SIBLING of the graph: it is posted as its own message and nothing in
 *      the graph document moves.
 *   3. `notes[]` is never swallowed — §11.38 C's caveats reach the output channel in full and
 *      the toast says how many there are.
 *   4. A comparison dies with the document it described: a new graph clears the overlay.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { api, vscode } = require('./harness.js');

const {
  withinRoot,
  comparisonBasePath,
  findCleanTwin,
  readOverlay,
  overlayHeadline,
  overlayNoteLines,
  saveComparisonBase,
  compareWithSavedBase,
  compareWithCleanSample,
  registerComparisonCommands,
  COMPARISON_BASE_RELATIVE,
  CLEAN_TWIN_RELATIVE,
  SAVE_BASE_COMMAND,
  COMPARE_BASE_COMMAND,
  COMPARE_CLEAN_COMMAND,
  MlviewPanel,
  isHostToUi
} = api;

/** The overlay §11.38 B specifies, trimmed to what the host reads. */
const OVERLAY = {
  kind: 'mlview-diff',
  diffVersion: '1.0',
  schemaVersion: '1.0',
  base: { root: '/repo', nodes: 64, edges: 55, issues: 0 },
  head: { root: '/repo', nodes: 54, edges: 51, issues: 15 },
  summary: {
    nodes: { added: 26, removed: 16, changed: 11, unchanged: 27 },
    issues: { new: 0, fixed: 15, persisting: 0 },
    headline: '+26 nodes · −16 nodes · 0 new findings · 15 fixed'
  },
  nodes: [],
  edges: [],
  issues: [],
  notes: [
    {
      kind: 'different-roots',
      side: 'base',
      count: 1,
      message: 'the two analyses read different workspace roots'
    },
    { kind: 'truncated', side: 'head', count: 1, message: 'the head document was capped' }
  ]
};

function makeLog() {
  return {
    lines: [],
    info(m) {
      this.lines.push(String(m));
    },
    warn(m) {
      this.lines.push(String(m));
    },
    error(m) {
      this.lines.push(String(m));
    },
    debug() {},
    trace() {},
    raw() {},
    show() {},
    dispose() {}
  };
}

function graphOf(nodes, issues) {
  return {
    schemaVersion: '1.0',
    workspace: { root: '/repo', entrypoints: [], filesAnalyzed: 5 },
    nodes: Array.from({ length: nodes }, (_, i) => ({ id: `n:${i}` })),
    edges: [],
    issues: Array.from({ length: issues }, (_, i) => ({ id: `i:${i}` })),
    diagnostics: []
  };
}

function makeHost(root, overrides = {}) {
  const log = makeLog();
  const storage = fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-cmp-'));
  const posted = [];
  const calls = [];
  return {
    log,
    storage,
    posted,
    calls,
    ctx: { globalStorageUri: vscode.Uri.file(storage) },
    core: {
      async runCli(args, request) {
        calls.push({ args, request });
        return { stdout: JSON.stringify(OVERLAY), stderr: '' };
      },
      async analyze(request) {
        calls.push({ analyze: request });
        return { graph: graphOf(64, 0), empty: false, durationMs: 1 };
      }
    },
    getGraph: () => graphOf(54, 15),
    ensureGraph: async () => graphOf(54, 15),
    workspaceRoot: () => root,
    settingsFor: () => ({ maxFiles: 500, maxNodes: 400, exclude: [] }),
    comparisonPanel: () => ({
      postDiffOverlay(overlay, baseLabel) {
        posted.push({ overlay, baseLabel });
      }
    }),
    ...overrides
  };
}

function tempRoot() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-root-'));
}

// ------------------------------------------------------------------ containment

test('the base path is inside the workspace, and an escape is refused', () => {
  assert.equal(comparisonBasePath('/repo'), path.resolve('/repo', COMPARISON_BASE_RELATIVE));
  assert.equal(COMPARISON_BASE_RELATIVE, '.mlview/comparison-base.json');
  assert.equal(withinRoot('/repo', '../../etc/passwd'), undefined);
  assert.equal(withinRoot('/repo', 'a/../b.json'), path.resolve('/repo/b.json'));
});

// ------------------------------------------------------------------ the overlay guard

test('kind is checked before anything else, exactly as 11.38 B says a consumer must', () => {
  assert.equal(readOverlay(JSON.stringify(OVERLAY)).diffVersion, '1.0');
  // A graph is not an overlay, and an older core prints a usage error rather than JSON.
  assert.equal(readOverlay(JSON.stringify({ schemaVersion: '1.0', nodes: [] })), undefined);
  assert.equal(readOverlay('usage: mlview [-h] ...'), undefined);
  assert.equal(readOverlay('[]'), undefined);
  assert.equal(readOverlay(''), undefined);
  assert.equal(readOverlay(JSON.stringify({ kind: 'mlview-diff' })), undefined);
});

test('the headline and every note are recoverable from the document', () => {
  assert.equal(overlayHeadline(OVERLAY), '+26 nodes · −16 nodes · 0 new findings · 15 fixed');
  assert.deepEqual(overlayNoteLines(OVERLAY), [
    'different-roots (base): the two analyses read different workspace roots',
    'truncated (head): the head document was capped'
  ]);
  assert.equal(overlayHeadline({ kind: 'mlview-diff', diffVersion: '1.0' }), 'comparison complete');
  assert.deepEqual(overlayNoteLines({ kind: 'mlview-diff', diffVersion: '1.0' }), []);
});

// ------------------------------------------------------------------ saving a base

test('the base is the analyzed document written verbatim, never a fresh analysis', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  const written = await saveComparisonBase(host);
  assert.equal(written, path.join(root, '.mlview', 'comparison-base.json'));
  const back = JSON.parse(fs.readFileSync(written, 'utf8'));
  assert.deepEqual(back, graphOf(54, 15), 'the document the analyzer produced, byte for byte');
  assert.equal(host.calls.length, 0, 'saving a base must not spawn the analyzer');
  assert.ok(
    vscode.__recorded.messages.some((m) => /54 nodes, 15 findings/.test(String(m[1]))),
    'the toast says what was captured, so a base is never a mystery'
  );
});

test('with no folder open there is nowhere to put a base, and it says so', async () => {
  vscode.__reset();
  const host = makeHost(undefined);
  assert.equal(await saveComparisonBase(host), undefined);
  assert.equal(vscode.__recorded.messages.at(-1)[0], 'warn');
});

// ------------------------------------------------------------------ comparing

test('the diff is the ANALYZER\'s, invoked with the frozen argv', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  const basePath = await saveComparisonBase(host);
  const overlay = await compareWithSavedBase(host);

  assert.equal(overlay.kind, 'mlview-diff');
  const call = host.calls.at(-1);
  assert.deepEqual(call.args, [
    '-X',
    'utf8',
    '-m',
    'mlview',
    'diff',
    basePath,
    path.join(host.storage, 'comparison-head.json'),
    '--json',
    '-'
  ]);
  assert.equal(call.request.cwd, root);
  assert.equal(call.request.key, 'diff');
  // The head is staged in the extension's OWN storage, never in the user's repository.
  assert.ok(!fs.existsSync(path.join(root, 'comparison-head.json')));
});

test('the overlay is posted as its own message, with the base named', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  await saveComparisonBase(host);
  await compareWithSavedBase(host);
  assert.equal(host.posted.length, 1);
  assert.deepEqual(host.posted[0].overlay, OVERLAY);
  assert.equal(host.posted[0].baseLabel, COMPARISON_BASE_RELATIVE);
  // It is a HostToUi message in its own right; the graph document is untouched.
  assert.equal(isHostToUi({ v: 1, type: 'diffOverlay', overlay: OVERLAY }), true);
  assert.equal(isHostToUi({ v: 1, type: 'diffOverlay', overlay: null }), true);
});

test('every caveat reaches the output channel and the toast counts them', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  await saveComparisonBase(host);
  await compareWithSavedBase(host);
  const logged = host.log.lines.filter((l) => l.startsWith('diff note — '));
  assert.equal(logged.length, 2, '11.38 C: notes are NEVER elided');
  assert.ok(logged.some((l) => l.includes('different-roots')));
  assert.ok(
    vscode.__recorded.messages.some((m) => /2 caveat\(s\)/.test(String(m[1]))),
    'a reader of "−16 nodes" is told there are caveats before they conclude anything'
  );
});

test('no saved base offers to make one and never runs a comparison', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  vscode.__answerMessage('Cancel');
  assert.equal(await compareWithSavedBase(host), undefined);
  assert.equal(host.calls.length, 0);
  assert.match(String(vscode.__recorded.messages[0][1]), /no comparison base/);
});

test('a core that cannot produce an overlay is reported, not drawn', async () => {
  vscode.__reset();
  const root = tempRoot();
  const host = makeHost(root);
  await saveComparisonBase(host);
  host.core.runCli = async () => ({ stdout: 'usage: mlview [-h]', stderr: '' });
  assert.equal(await compareWithSavedBase(host), undefined);
  assert.equal(host.posted.length, 0);
  assert.ok(
    vscode.__recorded.messages.some((m) => /predate "mlview diff"/.test(String(m[1])))
  );
});

// ------------------------------------------------------------------ the clean twin

test('the clean twin is found by name, under the root, or not at all', () => {
  assert.deepEqual([...CLEAN_TWIN_RELATIVE], [
    'samples/vision_pipeline_clean',
    'vision_pipeline_clean'
  ]);
  const seen = [];
  assert.equal(
    findCleanTwin('/repo', (p) => {
      seen.push(p);
      return p === path.resolve('/repo/samples/vision_pipeline_clean');
    }),
    path.resolve('/repo/samples/vision_pipeline_clean')
  );
  assert.equal(findCleanTwin('/repo', () => false), undefined);
});

test('the clean-sample comparison analyzes the twin and diffs it as the BASE', async () => {
  vscode.__reset();
  const root = tempRoot();
  fs.mkdirSync(path.join(root, 'samples', 'vision_pipeline_clean'), { recursive: true });
  const host = makeHost(root);
  const overlay = await compareWithCleanSample(host);
  assert.equal(overlay.kind, 'mlview-diff');

  const analyzed = host.calls.find((c) => c.analyze);
  assert.deepEqual(analyzed.analyze.paths, [path.join(root, 'samples', 'vision_pipeline_clean')]);
  const diff = host.calls.at(-1);
  assert.equal(diff.args[5], path.join(host.storage, 'clean-sample-base.json'));
  assert.equal(diff.args[6], path.join(host.storage, 'comparison-head.json'));
  // CONTRACTS §0: a workspace-relative path is forward-slashed on every platform, and
  // `baseLabel` crosses the protocol boundary into the webview. `path.join` here asserted
  // the host separator instead and was red on Windows only.
  assert.equal(host.posted[0].baseLabel, CLEAN_TWIN_RELATIVE[0]);
  assert.equal(host.posted[0].baseLabel.includes('\\'), false);
});

test('no twin names what it looked for instead of comparing something else', async () => {
  vscode.__reset();
  const host = makeHost(tempRoot());
  assert.equal(await compareWithCleanSample(host), undefined);
  assert.match(String(vscode.__recorded.messages[0][1]), /vision_pipeline_clean/);
  assert.equal(host.calls.length, 0);
});

// ------------------------------------------------------------------ registration

test('the three commands register under the ids package.json contributes', () => {
  vscode.__reset();
  const disposables = registerComparisonCommands(makeHost('/repo'));
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
  );
  const contributed = manifest.contributes.commands.map((c) => c.command);
  for (const id of [SAVE_BASE_COMMAND, COMPARE_BASE_COMMAND, COMPARE_CLEAN_COMMAND]) {
    assert.ok(vscode.__recorded.commands.has(id), `${id} must register`);
    assert.ok(contributed.includes(id), `${id} must be in the command palette`);
  }
  const titles = new Map(manifest.contributes.commands.map((c) => [c.command, c.title]));
  assert.equal(titles.get(SAVE_BASE_COMMAND), 'Save Current Graph As Comparison Base');
  assert.equal(titles.get(COMPARE_BASE_COMMAND), 'Compare With Saved Base');
  assert.equal(titles.get(COMPARE_CLEAN_COMMAND), 'Compare With Clean Sample');
  for (const d of disposables) {
    d.dispose();
  }
});

// ------------------------------------------------------------------ staleness

test('a new graph clears the overlay, so a comparison never outlives its document', async () => {
  vscode.__reset();
  const extensionPath = path.join(__dirname, '..');
  const state = new Map();
  const ctx = {
    subscriptions: [],
    extensionPath,
    extensionUri: vscode.Uri.file(extensionPath),
    extension: { packageJSON: { version: '0.1.0' } },
    workspaceState: {
      get: (k) => state.get(k),
      update: async (k, v) => void state.set(k, v)
    }
  };
  const delegate = {
    log: makeLog(),
    onReady() {},
    onRequestRefresh() {},
    onExportHtml() {},
    onAction() {},
    onSelectNode() {},
    onSuppressRule() {},
    onApplyFix() {},
    workspaceRoot: () => '/repo'
  };
  const panel = MlviewPanel.createOrShow(ctx, delegate);
  const mock = vscode.__recorded.panels.at(-1);
  mock.fire({ v: 1, type: 'ready' });
  mock.posted.length = 0;

  panel.postGraph('req-1', graphOf(54, 15));
  panel.postDiffOverlay(OVERLAY, 'base.json');
  panel.postGraph('req-2', graphOf(54, 15));

  const overlays = mock.posted.filter((m) => m.type === 'diffOverlay');
  assert.equal(overlays.length, 2, 'the overlay, then its clear');
  assert.deepEqual(overlays[0].overlay, OVERLAY);
  assert.equal(overlays[1].overlay, null);

  // ...and a THIRD graph does not post a redundant clear.
  panel.postGraph('req-3', graphOf(54, 15));
  assert.equal(mock.posted.filter((m) => m.type === 'diffOverlay').length, 2);
  panel.dispose();
});
