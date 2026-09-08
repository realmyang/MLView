'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { api } = require('./harness.js');

const {
  PROTOCOL_VERSION,
  UI_TO_HOST_TYPES,
  HOST_TO_UI_TYPES,
  ACTION_IDS,
  isUiToHost,
  isHostToUi,
  parseUiToHost,
  nextRequestId
} = api;

/** One well-formed example of every UiToHost message. */
const SAMPLES = {
  ready: { v: 1, type: 'ready' },
  openLocation: {
    v: 1,
    type: 'openLocation',
    file: 'train.py',
    absFile: 'C:/repo/train.py',
    line: 44,
    col: 8,
    endLine: 50,
    endCol: 34,
    preview: true
  },
  selectNode: { v: 1, type: 'selectNode', nodeId: 'n:7c1a90b4e2f0' },
  requestRefresh: { v: 1, type: 'requestRefresh', scope: 'workspace' },
  exportHtml: { v: 1, type: 'exportHtml' },
  copy: { v: 1, type: 'copy', text: 'train.py:44' },
  saveState: { v: 1, type: 'saveState', state: { viewport: { x: 1, y: 2, zoom: 1.5 } } },
  action: { v: 1, type: 'action', id: 'retry' },
  askAssistant: { v: 1, type: 'askAssistant', nodeId: 'n:1', prompt: 'why?' },
  log: { v: 1, type: 'log', level: 'warn', message: 'hi' },
  // MLV-P10: the rail's suppression gesture (docs/CONTRACTS.md §11.27).
  suppressRule: {
    v: 1,
    type: 'suppressRule',
    code: 'MLV201',
    action: 'insert',
    absFile: 'C:/repo/train.py',
    line: 44
  },
  // CONTRACTS.md 11.7: the selector field is `spec`, never `scope`.
  scopeChanged: {
    v: 1,
    type: 'scopeChanged',
    spec: 'unit:train.validate',
    label: 'validate()',
    nodes: 4,
    of: 45
  }
};

test('every UiToHost type has a sample and survives a JSON round trip', () => {
  assert.equal(PROTOCOL_VERSION, 1);
  assert.deepEqual(Object.keys(SAMPLES).sort(), [...UI_TO_HOST_TYPES].sort());
  for (const [type, message] of Object.entries(SAMPLES)) {
    const roundTripped = JSON.parse(JSON.stringify(message));
    assert.ok(isUiToHost(roundTripped), `${type} should be accepted`);
    const parsed = parseUiToHost(roundTripped);
    assert.equal(parsed.ok, true, `${type} should parse`);
    assert.deepEqual(parsed.msg, message);
  }
});

test('a cleared scope round-trips as spec: null', () => {
  const cleared = { v: 1, type: 'scopeChanged', spec: null, label: 'Everything', nodes: 45, of: 45 };
  const parsed = parseUiToHost(JSON.parse(JSON.stringify(cleared)));
  assert.equal(parsed.ok, true);
  assert.deepEqual(parsed.msg, cleared);
});

test('setScope is a host -> ui message and carries an optional depth', () => {
  assert.ok(isHostToUi({ v: 1, type: 'setScope', spec: 'concern:evaluation', depth: 1 }));
  assert.ok(isHostToUi({ v: 1, type: 'setScope', spec: null }));
  // ...and it is NOT a webview -> host message: a viewer may not scope the host.
  assert.equal(parseUiToHost({ v: 1, type: 'setScope', spec: null }).reason, 'unknown-type');
});

test('selectNode accepts an explicit null nodeId', () => {
  assert.ok(isUiToHost({ v: 1, type: 'selectNode', nodeId: null }));
});

test('unknown message types are reported as unknown-type, not thrown', () => {
  const result = parseUiToHost({ v: 1, type: 'somethingFromTheFuture', payload: 42 });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'unknown-type');
  assert.equal(result.detail, 'somethingFromTheFuture');
});

test('a future protocol version degrades instead of crashing', () => {
  const result = parseUiToHost({ v: 2, type: 'ready' });
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'bad-version');
});

test('malformed known messages are rejected', () => {
  for (const bad of [
    { v: 1, type: 'openLocation', file: 'a.py' },
    { v: 1, type: 'copy' },
    { v: 1, type: 'action', id: 7 },
    { v: 1, type: 'log', level: 'shout', message: 'x' },
    { v: 1, type: 'requestRefresh', scope: 'galaxy' },
    { v: 1, type: 'scopeChanged', spec: 'unit:train' },
    { v: 1, type: 'scopeChanged', spec: 'unit:train', label: 'train()', nodes: '4', of: 45 },
    { v: 1, type: 'scopeChanged', spec: 7, label: 'train()', nodes: 4, of: 45 }
  ]) {
    const result = parseUiToHost(bad);
    assert.equal(result.ok, false, `${JSON.stringify(bad)} should be rejected`);
    assert.equal(result.reason, 'malformed');
  }
  assert.equal(parseUiToHost(null).reason, 'not-an-object');
  assert.equal(parseUiToHost('ready').reason, 'not-an-object');
  assert.equal(parseUiToHost([1, 2]).reason, 'not-an-object');
});

test('host -> ui types cover the contract and are guarded', () => {
  assert.deepEqual(
    [...HOST_TO_UI_TYPES].sort(),
    [
      'analysisFailed',
      'analysisProgress',
      'analysisStarted',
      'cursorHint',
      'graph',
      'init',
      'restoreState',
      'revealIssue',
      'revealNode',
      'setFilter',
      'setScope',
      'stale',
      'theme'
    ]
  );
  assert.ok(isHostToUi({ v: 1, type: 'theme', kind: 'dark' }));
  assert.ok(!isHostToUi({ v: 1, type: 'nope' }));
  assert.ok(!isHostToUi({ v: 3, type: 'theme' }));
});

test('the four error-banner action ids are the frozen set', () => {
  assert.deepEqual([...ACTION_IDS], ['retry', 'selectInterpreter', 'showOutput', 'installCore']);
});

test('request ids are unique', () => {
  const a = nextRequestId('analyze');
  const b = nextRequestId('analyze');
  assert.notEqual(a, b);
  assert.match(a, /^analyze-\d+$/);
});
