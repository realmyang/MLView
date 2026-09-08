'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { api, readSampleGraph } = require('./harness.js');

const {
  toRangeTuple,
  resolveOpenTarget,
  toWorkspaceRelative,
  locLabel,
  buildLocationIndex,
  findNodeAtLine,
  unitAnchors
} = api;

const ROOT = process.platform === 'win32' ? 'C:\\repo\\ws' : '/repo/ws';

test('loc -> Range conversion: 1-based line becomes 0-based, column passes through', () => {
  // CONTRACTS.md §0: `new vscode.Position(loc.line - 1, loc.col)`, exactly once, here.
  assert.deepEqual(toRangeTuple({ line: 44, col: 8, endLine: 50, endCol: 34 }), {
    startLine: 43,
    startChar: 8,
    endLine: 49,
    endChar: 34
  });
  assert.deepEqual(toRangeTuple({ line: 1, col: 0, endLine: 1, endCol: 0 }), {
    startLine: 0,
    startChar: 0,
    endLine: 0,
    endChar: 0
  });
});

test('a nonsensical end collapses to the start instead of throwing', () => {
  assert.deepEqual(toRangeTuple({ line: 10, col: 4, endLine: 2, endCol: 0 }), {
    startLine: 9,
    startChar: 4,
    endLine: 9,
    endChar: 4
  });
  assert.deepEqual(toRangeTuple({ line: 0, col: -3, endLine: 0, endCol: -1 }), {
    startLine: 0,
    startChar: 0,
    endLine: 0,
    endChar: 0
  });
});

test('openLocation resolves a workspace-relative file against the root', () => {
  const target = resolveOpenTarget(
    {
      file: 'models/net.py',
      absFile: `${ROOT}/models/net.py`,
      line: 12,
      col: 4,
      endLine: 12,
      endCol: 20
    },
    { workspaceRoot: ROOT, isInWorkspace: () => true }
  );
  assert.equal(target.ok, true);
  assert.equal(target.fsPath, path.resolve(ROOT, 'models/net.py'));
  assert.deepEqual(target.range, { startLine: 11, startChar: 4, endLine: 11, endChar: 20 });
  assert.equal(target.preview, false);
});

test('the workspace-containment guard refuses an out-of-workspace path', () => {
  // SECURITY: node paths come from parsing arbitrary source; the webview must not be able to
  // talk the extension into opening ~/.ssh/id_rsa.
  const escaped = '../../../../Users/realm/.ssh/id_rsa';
  const inside = (p) => p.startsWith(path.resolve(ROOT) + path.sep);
  const target = resolveOpenTarget(
    { file: escaped, absFile: escaped, line: 1, col: 0, endLine: 1, endCol: 1 },
    { workspaceRoot: ROOT, isInWorkspace: inside }
  );
  assert.equal(target.ok, false);
  assert.equal(target.reason, 'out-of-workspace');
  assert.ok(!target.fsPath.includes('repo'), 'the resolved path escaped the workspace');
});

test('an absolute path outside the workspace is refused even when it looks plausible', () => {
  const outside = process.platform === 'win32' ? 'C:\\Windows\\System32\\drivers\\etc\\hosts' : '/etc/hosts';
  const target = resolveOpenTarget(
    { file: outside, absFile: outside, line: 1, col: 0, endLine: 1, endCol: 1 },
    { workspaceRoot: ROOT, isInWorkspace: (p) => p.startsWith(path.resolve(ROOT) + path.sep) }
  );
  assert.equal(target.ok, false);
  assert.equal(target.reason, 'out-of-workspace');
});

test('with no workspace open nothing is opened', () => {
  const target = resolveOpenTarget(
    { file: 'a.py', absFile: '/a.py', line: 1, col: 0, endLine: 1, endCol: 1 },
    { workspaceRoot: undefined, isInWorkspace: () => true }
  );
  assert.equal(target.ok, false);
  assert.equal(target.reason, 'no-workspace');
});

test('path helpers stay forward-slashed and stable', () => {
  assert.equal(
    toWorkspaceRelative(ROOT, path.join(ROOT, 'models', 'net.py')),
    'models/net.py'
  );
  assert.equal(locLabel({ file: 'train.py', line: 44 }), 'train.py:44');
});

test('the location index picks the narrowest containing node', () => {
  const graph = readSampleGraph();
  graph.nodes = [
    node('n:000000000001', 'unit', 'train.py', 10, 60, 'train'),
    node('n:000000000002', 'unit', 'train.py', 40, 55, 'batch_loop'),
    node('n:000000000003', 'op', 'train.py', 48, 48, 'loss.backward'),
    node('n:000000000004', 'op', 'data.py', 5, 9, 'DataLoader')
  ];
  const index = buildLocationIndex(graph);
  assert.equal(findNodeAtLine(index, 'train.py', 48).nodeId, 'n:000000000003');
  assert.equal(findNodeAtLine(index, 'train.py', 41).nodeId, 'n:000000000002');
  assert.equal(findNodeAtLine(index, 'train.py', 12).nodeId, 'n:000000000001');
  assert.equal(findNodeAtLine(index, 'train.py', 48).exact, true);
});

test('with no containing node the nearest node in the same file is used', () => {
  const graph = readSampleGraph();
  graph.nodes = [node('n:000000000004', 'op', 'data.py', 5, 9, 'DataLoader')];
  const index = buildLocationIndex(graph);
  const hit = findNodeAtLine(index, 'data.py', 200);
  assert.equal(hit.nodeId, 'n:000000000004');
  assert.equal(hit.exact, false);
  assert.equal(findNodeAtLine(index, 'nowhere.py', 1), null);
});

test('the real sample graph indexes every node file and yields CodeLens anchors', () => {
  const graph = readSampleGraph();
  const index = buildLocationIndex(graph);
  assert.ok(index.byFile.size > 0);
  for (const node of graph.nodes) {
    assert.ok(index.nodes.has(node.id));
  }
  const filesWithUnits = new Set(
    graph.nodes.filter((n) => n.level === 'unit' && !n.ghost).map((n) => (n.defLoc ?? n.loc).file)
  );
  for (const file of filesWithUnits) {
    const anchors = unitAnchors(graph, file);
    assert.ok(anchors.length > 0, `expected a CodeLens anchor in ${file}`);
    for (const anchor of anchors) {
      assert.ok(anchor.line >= 1);
      assert.match(anchor.nodeId, /^n:[0-9a-f]{12}$/);
    }
  }
});

test('ghost nodes never shadow a real node in the cursor lookup', () => {
  const graph = readSampleGraph();
  const ghost = graph.nodes.find((n) => n.ghost);
  if (!ghost) {
    return; // the sample always has one, but do not fail if it is trimmed
  }
  const index = buildLocationIndex(graph);
  const hit = findNodeAtLine(index, ghost.loc.file, ghost.loc.line);
  assert.notEqual(hit.nodeId, ghost.id);
});

function node(id, level, file, line, endLine, label) {
  return {
    id,
    kind: 'function',
    level,
    stage: 'train',
    label,
    qualname: `x.${label}`,
    loc: {
      file,
      absFile: `C:/repo/${file}`,
      line,
      col: 0,
      endLine,
      endCol: 10,
      symbol: label
    },
    parent: null,
    attrs: {},
    produces: [],
    consumes: [],
    ghost: false,
    dynamic: false,
    confidence: 1,
    confidenceBucket: 'certain',
    issueIds: [],
    collapsedByDefault: false,
    stageEvidence: []
  };
}
