'use strict';
/**
 * VIEW-07 — exporting the diagram as a picture (docs/contracts/11.33-diagram-export.md).
 *
 * Two halves, because the feature has two halves:
 *
 *   1. the pure decode/naming rules in src/exportDiagram.ts, asserted directly;
 *   2. the real `out/extension.js` driven through the mocked `vscode`: the commands post
 *      `requestExport`, and an `exportFile` coming back from the (mocked) webview lands on
 *      disk through `showSaveDialog` + `workspace.fs.writeFile` with the EXACT bytes.
 *
 * The host never renders anything here — it cannot — so what these tests protect is the
 * boundary: what the host asks for, what it is willing to write, and where it writes it.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const cp = require('node:child_process');

const { api, readSampleGraph } = require('./harness.js'); // installs the `vscode` -> mock hook
const vscode = require('./mock-vscode.js');

const {
  decodeExportPayload,
  defaultExportName,
  exportScopeChoices,
  DeferredMessages,
  MAX_EXPORT_BYTES,
  isUiToHost
} = api;

const EXTENSION_ROOT = path.join(__dirname, '..');
const WORKSPACE = 'C:/mlview-test-workspace';
const FAKE_PYTHON = 'C:/mlview-test-workspace/.venv/Scripts/python.exe';
const extension = require(path.join(EXTENSION_ROOT, 'out', 'extension.js'));

const SVG_TEXT = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>';
const SVG_BYTES = Buffer.from(SVG_TEXT, 'utf8');
const PNG_BYTES = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.from('IHDR-and-the-rest', 'utf8')
]);
const b64 = (buf) => buf.toString('base64');

// ------------------------------------------------------------------ the pure rules

test('a real SVG and a real PNG decode to their exact bytes', () => {
  const svg = decodeExportPayload('svg', b64(SVG_BYTES));
  assert.equal(svg.ok, true);
  assert.deepEqual(Buffer.from(svg.bytes), SVG_BYTES);

  const png = decodeExportPayload('png', b64(PNG_BYTES));
  assert.equal(png.ok, true);
  assert.deepEqual(Buffer.from(png.bytes), PNG_BYTES);
});

test('the payload must BE the format that was asked for', () => {
  // The protocol guard proves the string is base64; it says nothing about the bytes. A `.svg`
  // is executable content in a browser, so the host refuses to write one it did not recognise.
  assert.equal(decodeExportPayload('svg', b64(PNG_BYTES)).reason, 'wrong-format');
  assert.equal(decodeExportPayload('png', b64(SVG_BYTES)).reason, 'wrong-format');
  assert.equal(decodeExportPayload('svg', b64(Buffer.from('not markup at all'))).reason, 'wrong-format');
  // ...but a real SVG that opens with an XML prologue or a BOM is still an SVG.
  assert.equal(decodeExportPayload('svg', b64(Buffer.from(`<?xml version="1.0"?>${SVG_TEXT}`))).ok, true);
  assert.equal(decodeExportPayload('svg', b64(Buffer.from(`\uFEFF${SVG_TEXT}`))).ok, true);
});

test('a payload that is not base64, is empty, or is oversized is refused before any write', () => {
  assert.equal(decodeExportPayload('svg', '').reason, 'empty');
  assert.equal(decodeExportPayload('svg', 'not base64!!').reason, 'not-base64');
  assert.equal(decodeExportPayload('svg', 'AAAA=').reason, 'not-base64'); // length % 4
  assert.equal(decodeExportPayload('png', 'A'.repeat(4 * 1024)).reason, 'wrong-format');
  const overCeiling = 'A'.repeat(Math.ceil((MAX_EXPORT_BYTES + 1024) / 3) * 4);
  assert.equal(decodeExportPayload('png', overCeiling).reason, 'too-large');
});

test('the default file name uses the viewer hint only when it is a safe basename', () => {
  assert.equal(defaultExportName('svg', 'vision-pipeline.svg'), 'vision-pipeline.svg');
  assert.equal(defaultExportName('png', 'vision pipeline'), 'vision-pipeline.png');
  // A hint is never allowed to become a path.
  assert.equal(defaultExportName('svg', '../../etc/passwd'), 'passwd.svg');
  assert.equal(defaultExportName('svg', 'C:/Windows/system32/evil'), 'evil.svg');
  assert.equal(defaultExportName('svg', '...'), 'mlview-diagram.svg');
  // No hint: the host names it, and says which projection it is.
  assert.equal(defaultExportName('svg', undefined, 'all'), 'mlview-diagram.svg');
  assert.equal(defaultExportName('png', undefined, 'view'), 'mlview-diagram-view.png');
  assert.equal(defaultExportName('svg', undefined, 'scope'), 'mlview-diagram-scope.svg');
});

test('the scope offer grows the third choice only when the diagram is scoped', () => {
  assert.deepEqual(
    exportScopeChoices().map((c) => c.scope),
    ['all', 'view']
  );
  const scoped = exportScopeChoices('unit:train.train');
  assert.deepEqual(scoped.map((c) => c.scope), ['all', 'view', 'scope']);
  assert.equal(scoped[2].description, 'unit:train.train');
});

test('exportFile is guarded structurally, like every other webview message', () => {
  const good = { v: 1, type: 'exportFile', kind: 'svg', data: b64(SVG_BYTES) };
  assert.ok(isUiToHost(good));
  assert.ok(isUiToHost({ ...good, suggestedName: 'pipeline.svg', scope: 'all' }));
  for (const bad of [
    { ...good, kind: 'pdf' },
    { ...good, data: 'data:image/svg+xml;base64,AAAA' },
    { ...good, data: '' },
    { ...good, suggestedName: '../escape.svg' },
    { ...good, suggestedName: 'sub/dir.svg' },
    { ...good, scope: 'everything' }
  ]) {
    assert.ok(!isUiToHost(bad), `${JSON.stringify(bad).slice(0, 60)} should be rejected`);
  }
});

test('a requestExport posted before the first graph is held, not dropped', () => {
  const deferred = new DeferredMessages();
  assert.equal(deferred.shouldDefer('requestExport'), true, 'no handshake yet');
  deferred.onReady();
  assert.equal(deferred.shouldDefer('requestExport'), true, 'ready, but no graph to draw');
  deferred.onGraphDelivered();
  assert.equal(deferred.shouldDefer('requestExport'), false);
});

// ------------------------------------------------------- the host, end to end

const realExecFile = cp.execFile;

function installExecFileStub(graph) {
  cp.execFile = function (file, args, opts, callback) {
    const done = typeof opts === 'function' ? opts : callback;
    let stdout = '';
    if (args.includes('-c')) {
      stdout = JSON.stringify([3, 13, FAKE_PYTHON]);
    } else if (args.includes('--version')) {
      stdout = JSON.stringify({ version: '0.1.0', schemaVersion: '1.0' });
    } else if (args.includes('analyze')) {
      stdout = JSON.stringify(graph);
    }
    setTimeout(() => done(null, stdout, ''), 5);
    return {
      stderr: { setEncoding() {}, on() {} },
      stdout: { setEncoding() {}, on() {} },
      on() {},
      kill() {},
      exitCode: null,
      killed: false
    };
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const run = (id, ...args) => vscode.__recorded.commands.get(id)(...args);
const panel = () => vscode.__recorded.panels[vscode.__recorded.panels.length - 1];
const posted = (type) => panel().posted.filter((m) => m.type === type);

function boot() {
  vscode.__reset();
  vscode.__setWorkspaceFolders([WORKSPACE]);
  vscode.__setConfig('mlview', 'pythonPath', FAKE_PYTHON);
  const graph = readSampleGraph();
  graph.workspace.root = WORKSPACE;
  installExecFileStub(graph);
  extension.activate(makeContext());
}

function shutdown() {
  extension.deactivate();
  cp.execFile = realExecFile;
  vscode.__reset();
}

/** Open the diagram and let the analysis finish, so the panel has a graph on screen. */
async function openDiagram() {
  void run('mlview.visualizeWorkspace');
  await sleep(60);
  panel().fire({ v: 1, type: 'ready' });
  await sleep(120);
}

test('the two export commands are contributed and registered', async () => {
  boot();
  try {
    assert.ok(vscode.__recorded.commands.has('mlview.exportSvg'));
    assert.ok(vscode.__recorded.commands.has('mlview.exportPng'));
  } finally {
    shutdown();
  }
});

test('exporting with no diagram open warns instead of opening a dialog', async () => {
  boot();
  try {
    await run('mlview.exportSvg');
    const warnings = vscode.__recorded.messages.filter((m) => m[0] === 'warn');
    assert.ok(warnings.length >= 1);
    assert.match(warnings.at(-1)[1], /open the diagram/i);
    assert.equal(vscode.__recorded.saveDialogs.length, 0);
  } finally {
    shutdown();
  }
});

test('mlview.exportSvg asks the panel for the picture the user picked', async () => {
  boot();
  try {
    await openDiagram();
    vscode.__answerQuickPick(1); // "Current view"
    await run('mlview.exportSvg');
    await sleep(20);

    const offered = vscode.__recorded.quickPicks.at(-1).items.map((i) => i.scope);
    assert.deepEqual(offered, ['all', 'view'], 'an unscoped diagram offers two choices');
    assert.deepEqual(posted('requestExport'), [
      { v: 1, type: 'requestExport', kind: 'svg', scope: 'view' }
    ]);
  } finally {
    shutdown();
  }
});

test('an explicit scope argument skips the quick pick, and PNG asks for PNG', async () => {
  boot();
  try {
    await openDiagram();
    await run('mlview.exportPng', 'all');
    await sleep(20);
    assert.equal(vscode.__recorded.quickPicks.length, 0);
    assert.deepEqual(posted('requestExport'), [
      { v: 1, type: 'requestExport', kind: 'png', scope: 'all' }
    ]);
  } finally {
    shutdown();
  }
});

test('"current scope" is offered once the viewer reports one, and never asked for otherwise', async () => {
  boot();
  try {
    await openDiagram();
    panel().fire({
      v: 1,
      type: 'scopeChanged',
      spec: 'unit:train.train',
      label: 'train()',
      nodes: 4,
      of: 45
    });
    vscode.__answerQuickPick(2);
    await run('mlview.exportSvg');
    await sleep(20);
    assert.deepEqual(posted('requestExport').at(-1).scope, 'scope');

    // ...and asking for a scope that is not set falls back to everything rather than
    // asking the viewer for a picture it would have to refuse.
    panel().fire({ v: 1, type: 'scopeChanged', spec: null, label: 'Everything', nodes: 45, of: 45 });
    await run('mlview.exportPng', 'scope');
    await sleep(20);
    assert.equal(posted('requestExport').at(-1).scope, 'all');
  } finally {
    shutdown();
  }
});

test('an exportFile message lands on disk with the exact bytes, defaulting to the workspace', async () => {
  boot();
  try {
    await openDiagram();
    const target = vscode.Uri.file(`${WORKSPACE}/diagram.svg`);
    vscode.__answerSaveDialog(target);
    panel().fire({
      v: 1,
      type: 'exportFile',
      kind: 'svg',
      data: b64(SVG_BYTES),
      suggestedName: 'vision-pipeline.svg',
      scope: 'all'
    });
    await sleep(30);

    const dialog = vscode.__recorded.saveDialogs.at(-1);
    assert.equal(
      dialog.defaultUri.fsPath,
      path.join(WORKSPACE, 'vision-pipeline.svg'),
      'the dialog opens in the workspace, on the name the viewer suggested'
    );
    assert.deepEqual(dialog.filters, { 'SVG image': ['svg'] });

    const written = vscode.__recorded.writtenFiles;
    assert.equal(written.length, 1);
    assert.equal(written[0].fsPath, target.fsPath);
    assert.deepEqual(written[0].bytes, SVG_BYTES, 'the file is byte-identical to the payload');

    const info = vscode.__recorded.messages.filter((m) => m[0] === 'info').at(-1);
    assert.match(info[1], /exported to/i);
    assert.match(info[1], /whole diagram/i);
    assert.deepEqual(info.slice(2), ['Open', 'Copy Path']);
  } finally {
    shutdown();
  }
});

test('a PNG payload is written as bytes, not as text', async () => {
  boot();
  try {
    await openDiagram();
    vscode.__answerSaveDialog(vscode.Uri.file(`${WORKSPACE}/diagram.png`));
    panel().fire({ v: 1, type: 'exportFile', kind: 'png', data: b64(PNG_BYTES) });
    await sleep(30);
    const written = vscode.__recorded.writtenFiles.at(-1);
    assert.deepEqual(written.bytes, PNG_BYTES);
    assert.equal(
      vscode.__recorded.saveDialogs.at(-1).defaultUri.fsPath,
      path.join(WORKSPACE, 'mlview-diagram.png')
    );
  } finally {
    shutdown();
  }
});

test('cancelling the save dialog writes nothing and says nothing', async () => {
  boot();
  try {
    await openDiagram();
    const before = vscode.__recorded.messages.length;
    panel().fire({ v: 1, type: 'exportFile', kind: 'svg', data: b64(SVG_BYTES) });
    await sleep(30);
    assert.equal(vscode.__recorded.writtenFiles.length, 0);
    assert.equal(vscode.__recorded.messages.length, before, 'no toast for a cancelled export');
  } finally {
    shutdown();
  }
});

test('a payload that is not the format it claims is refused, and a malformed one never parses', async () => {
  boot();
  try {
    await openDiagram();
    vscode.__answerSaveDialog(vscode.Uri.file(`${WORKSPACE}/diagram.svg`));
    // Right shape, wrong bytes: the guard passes it, the writer refuses it.
    panel().fire({ v: 1, type: 'exportFile', kind: 'svg', data: b64(PNG_BYTES) });
    await sleep(30);
    assert.equal(vscode.__recorded.writtenFiles.length, 0);
    assert.match(vscode.__recorded.messages.at(-1)[1], /will not write \(wrong-format\)/);
    assert.equal(vscode.__recorded.saveDialogs.length, 0, 'refused before the dialog');

    // Wrong shape: rejected by parseUiToHost, so the handler never runs at all.
    panel().fire({ v: 1, type: 'exportFile', kind: 'svg', data: 'nope!' });
    await sleep(20);
    assert.equal(vscode.__recorded.writtenFiles.length, 0);
  } finally {
    shutdown();
  }
});

test('a failed write is reported as an error, not swallowed', async () => {
  boot();
  try {
    await openDiagram();
    vscode.__answerSaveDialog(vscode.Uri.file('C:/read-only/diagram.svg'));
    vscode.__failNextWrite(new Error('EACCES: permission denied'));
    panel().fire({ v: 1, type: 'exportFile', kind: 'svg', data: b64(SVG_BYTES) });
    await sleep(30);
    assert.equal(vscode.__recorded.writtenFiles.length, 0);
    const errors = vscode.__recorded.messages.filter((m) => m[0] === 'error');
    assert.equal(errors.length, 1);
    assert.match(errors[0][1], /could not write/i);
  } finally {
    shutdown();
  }
});
