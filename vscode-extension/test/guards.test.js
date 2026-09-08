'use strict';
/**
 * The pure guards and derivations behind the host fixes:
 *
 *   - `resolveAnalysisTarget` - the workspace-containment check for the MODEL-supplied `path`
 *     of `mlview_analyzeWorkspace` (the same reasoning as `resolveOpenTarget`, which only ever
 *     guarded the webview side);
 *   - `toEditorLine` / `toGraphLine` - the line-only half of THE boundary conversion;
 *   - `preserveFromState` - what a `graph` message carries back so a re-analysis does not
 *     reset the viewport;
 *   - `allowedRuleCodes` - `mlview.disabledRules` as the viewer's `setFilter` keep-list.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { api, readSampleGraph } = require('./harness.js');

const {
  resolveAnalysisTarget,
  toEditorLine,
  toGraphLine,
  toRangeTuple,
  preserveFromState,
  allowedRuleCodes,
  NO_RULE_CODES
} = api;

const ROOT = process.platform === 'win32' ? 'C:\\repo\\ws' : '/repo/ws';
const inside = (fsPath) => path.resolve(fsPath).startsWith(path.resolve(ROOT));

// ---------------------------------------------------------------- containment

test('no path at all means the whole workspace', () => {
  for (const value of [undefined, '', '   ']) {
    const target = resolveAnalysisTarget(ROOT, value, { isInWorkspace: inside });
    assert.equal(target.ok, true);
    assert.equal(target.fsPath, path.resolve(ROOT));
  }
});

test('a workspace-relative path resolves against the root', () => {
  const target = resolveAnalysisTarget(ROOT, 'src/train.py', { isInWorkspace: inside });
  assert.equal(target.ok, true);
  assert.equal(target.fsPath, path.resolve(ROOT, 'src/train.py'));
  // Forward slashes, back slashes and a redundant `.` all land in the same place.
  // A backslash is a separator only on Windows; on POSIX it is an ordinary
  // filename character, so `src\train.py` is a DIFFERENT file there (CI-01).
  const spellings = ['./src/train.py', 'src/../src/train.py'];
  if (process.platform === 'win32') spellings.push('src\\train.py');
  for (const spelling of spellings) {
    const other = resolveAnalysisTarget(ROOT, spelling, { isInWorkspace: inside });
    assert.equal(other.ok, true);
    assert.equal(other.fsPath, target.fsPath, spelling);
  }
});

test('an escape out of the workspace is refused, however it is spelled', () => {
  const escapes = [
    '..',
    '../..',
    '../../analyzer/src/mlview',
    '../sibling-checkout',
    'src/../../..',
    process.platform === 'win32' ? 'C:\\Windows\\System32' : '/etc',
    process.platform === 'win32' ? 'C:/Users/someone/.ssh' : '/home/someone/.ssh'
  ];
  for (const escape of escapes) {
    const target = resolveAnalysisTarget(ROOT, escape, { isInWorkspace: inside });
    assert.equal(target.ok, false, `${escape} must be refused`);
    assert.equal(target.reason, 'out-of-workspace');
  }
});

test('a second workspace folder is still analyzable, an unopened folder is not', () => {
  const other = process.platform === 'win32' ? 'C:\\repo\\other' : '/repo/other';
  const opened = (fsPath) =>
    inside(fsPath) || path.resolve(fsPath).startsWith(path.resolve(other));
  const ok = resolveAnalysisTarget(ROOT, path.join(other, 'train.py'), { isInWorkspace: opened });
  assert.equal(ok.ok, true, 'a path in another OPEN folder is allowed');
  const refused = resolveAnalysisTarget(ROOT, path.join(other, 'train.py'), {
    isInWorkspace: inside
  });
  assert.equal(refused.ok, false, 'the same path is refused when that folder is not open');
});

test('a NUL byte and a missing root are refused as invalid, never resolved', () => {
  const nul = resolveAnalysisTarget(ROOT, `train${String.fromCharCode(0)}.py`, {
    isInWorkspace: () => true
  });
  assert.equal(nul.ok, false);
  assert.equal(nul.reason, 'invalid-path');
  assert.equal(resolveAnalysisTarget('', 'train.py', { isInWorkspace: () => true }).ok, false);
});

test('the containment check is never skipped by the caller supplying a lenient predicate', () => {
  // Even with a predicate that says "yes" to everything, an in-root path is unchanged...
  const ok = resolveAnalysisTarget(ROOT, 'src', { isInWorkspace: () => true });
  assert.equal(ok.fsPath, path.resolve(ROOT, 'src'));
  // ...and the refusal is driven by the predicate alone once the path leaves the root.
  assert.equal(resolveAnalysisTarget(ROOT, '../x', { isInWorkspace: () => false }).ok, false);
});

// ---------------------------------------------------------------- line conversion

test('toEditorLine / toGraphLine are the line-only half of toRangeTuple, and invert', () => {
  assert.equal(toEditorLine(44), 43);
  assert.equal(toEditorLine(1), 0);
  assert.equal(toEditorLine(0), 0, 'a malformed 0 clamps instead of going negative');
  assert.equal(toGraphLine(43), 44);
  assert.equal(toGraphLine(0), 1);
  for (const line of [1, 2, 17, 4096]) {
    assert.equal(toGraphLine(toEditorLine(line)), line);
    assert.equal(toEditorLine(toRangeTuple({ line, col: 0, endLine: line, endCol: 1 }).startLine + 1), line - 1);
  }
});

// ---------------------------------------------------------------- preserve

test('preserveFromState keeps exactly the three fields the contract allows', () => {
  const state = {
    viewport: { x: -12, y: 34, zoom: 2.5 },
    selection: { kind: 'node', id: 'n:abc' },
    collapsed: ['n:g1', 'n:g2', 7],
    filters: { severities: ['high'] },
    railTab: 'issues'
  };
  assert.deepEqual(preserveFromState(state), {
    viewport: { x: -12, y: 34, zoom: 2.5 },
    selection: { kind: 'node', id: 'n:abc' },
    collapsed: ['n:g1', 'n:g2']
  });
});

test('preserveFromState is undefined when there is nothing worth preserving', () => {
  assert.equal(preserveFromState(undefined), undefined);
  assert.equal(preserveFromState(null), undefined);
  assert.equal(preserveFromState('nonsense'), undefined);
  assert.equal(preserveFromState({}), undefined);
  assert.equal(preserveFromState({ railTab: 'issues' }), undefined);
  assert.equal(preserveFromState({ viewport: { x: 1, y: 2 } }), undefined, 'zoom is required');
  assert.equal(
    preserveFromState({ viewport: { x: 1, y: 2, zoom: Number.NaN } }),
    undefined,
    'a non-finite viewport would black-hole the canvas'
  );
  assert.equal(preserveFromState({ selection: { id: 'n:abc' } }), undefined);
});

// ---------------------------------------------------------------- disabled rules

test('allowedRuleCodes turns disabledRules into the viewer keep-list', () => {
  const graph = readSampleGraph();
  const codes = [...new Set(graph.issues.map((i) => i.code))];
  assert.ok(codes.length > 1, 'the sample must carry more than one rule code');

  assert.deepEqual(allowedRuleCodes(graph, []), [], 'nothing disabled means no restriction');

  const kept = allowedRuleCodes(graph, [codes[0]]);
  assert.ok(!kept.includes(codes[0]));
  for (const code of codes.slice(1)) {
    assert.ok(kept.includes(code), `${code} is enabled and must be kept`);
  }
  assert.deepEqual(kept, [...kept].sort(), 'deterministic order');

  // Lower case and stray whitespace in the setting still match.
  assert.deepEqual(allowedRuleCodes(graph, [` ${codes[0].toLowerCase()} `]), kept);
});

test('disabling every code present hides everything instead of silently showing all', () => {
  const graph = readSampleGraph();
  const codes = [...new Set(graph.issues.map((i) => i.code))];
  // An empty keep-list is the viewer's "no restriction", so it must not be produced here.
  assert.deepEqual(allowedRuleCodes(graph, codes), [NO_RULE_CODES]);
  assert.ok(!codes.includes(NO_RULE_CODES));
});

// ---------------------------------------------------------------- the pre-handshake queue

test('DeferredMessages holds a reveal until the webview has a graph', () => {
  const { DeferredMessages } = api;
  const q = new DeferredMessages();
  const reveal = { v: 1, type: 'revealNode', nodeId: 'n:abc', center: true };
  const started = { v: 1, type: 'analysisStarted', requestId: 'analyze-1', scope: 'workspace' };

  assert.equal(q.shouldDefer('revealNode'), true, 'nothing can be delivered before ready');
  assert.equal(q.shouldDefer('analysisStarted'), true);
  assert.equal(q.shouldDefer('graph'), false, 'onReady re-sends the graph, so it is never queued');
  assert.equal(q.shouldDefer('theme'), false);

  q.add(reveal);
  q.add(started);
  assert.deepEqual(q.take(), [], 'still nothing to send: the webview has not booted');

  q.onReady();
  assert.equal(q.shouldDefer('revealNode'), true, 'a reveal still needs a graph');
  assert.deepEqual(
    q.take().map((m) => m.type),
    ['analysisStarted'],
    'the spinner can be shown as soon as the webview is up'
  );

  q.onGraphDelivered();
  assert.deepEqual(q.take(), [reveal], 'the reveal follows the graph');
  assert.deepEqual(q.take(), [], 'delivered messages leave the queue');
});

test('DeferredMessages keeps the newest of a type and forgets a concluded run', () => {
  const { DeferredMessages } = api;
  const q = new DeferredMessages();
  q.add({ v: 1, type: 'revealNode', nodeId: 'n:one' });
  q.add({ v: 1, type: 'revealNode', nodeId: 'n:two' });
  q.add({ v: 1, type: 'analysisStarted', requestId: 'analyze-1', scope: 'workspace' });
  assert.equal(q.pending.length, 2, 'one reveal, one spinner');

  q.drop('analysisStarted', 'analyze-2');
  assert.equal(q.pending.length, 2, 'another run concluding must not clear this spinner');
  q.drop('analysisStarted', 'analyze-1');
  assert.equal(q.pending.length, 1);

  q.onReady();
  q.onGraphDelivered();
  const sent = q.take();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].nodeId, 'n:two', 'the newest reveal wins');
});

test('DeferredMessages never grows without bound', () => {
  const { DeferredMessages } = api;
  const q = new DeferredMessages();
  for (let i = 0; i < 50; i += 1) {
    q.add({ v: 1, type: 'revealNode', nodeId: `n:${i}` });
    q.add({ v: 1, type: 'revealIssue', issueId: `i:${i}` });
  }
  assert.ok(q.pending.length <= 8, `queue grew to ${q.pending.length}`);
});
