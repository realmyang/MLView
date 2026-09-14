'use strict';
/**
 * Hardening round 1, area hosts-ux — H10 × H5.
 *
 * §0 makes an issue id `sha1("<code>|<file>|<qualname>|<symbol>")[:12]`, and
 * `file` is **workspace-relative**. That is exactly right inside one document:
 * ids survive edits above a node and never move with a line number. It stops
 * being right the moment the host holds MORE THAN ONE document, which is what
 * H10 (multi-root folders, CONTRACTS 11.40) made the normal case: two folders
 * in one window, each with its own graph, and the Problems panel showing the
 * union.
 *
 * `issueById` (src/fixes.ts:231) flattens `deps.graphs()` and returns the FIRST
 * id match, with the comment "Ids are unique per document (§0)". They are; this
 * function searches across documents. `applyFix` from the diagram rail sends
 * **only** the issue id (README, H5), so the ambiguity is reachable from a
 * single click.
 *
 * Two real folders are enough to collide: any two projects that each contain a
 * `train.py` whose evaluation DataLoader shuffles produce the same MLV111 id.
 * Measured against the shipped corpus, `i:182be37565cd` (MLV601, `train.py`) is
 * emitted identically by `gbm_tabular`, `keras_tfdata`, `lightning_tabular` and
 * `timeseries_split` at four different line numbers.
 *
 * These tests pin the behaviour that must hold: a fix applied by id must land
 * in the folder the user was looking at, and never in a namesake file in
 * another folder.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { api, vscode } = require('./harness.js');

const { issueById, applyIssueFix, readFix } = api;

// `path.resolve` and not `path.join`: on Windows a root-relative path has no
// drive, and `Uri.file('\\work\\api\\train.py').fsPath` comes back as
// `D:\\work\\api\\train.py` - the current drive. Resolving here makes the
// fixtures and the expectations one spelling on every platform, and changes
// nothing on POSIX, where `path.resolve('/work/api') === '/work/api'`.
const API_ROOT = path.resolve(path.join(path.sep, 'work', 'api'));
const WORKER_ROOT = path.resolve(path.join(path.sep, 'work', 'worker'));
const API_TRAIN = path.join(API_ROOT, 'train.py');
const WORKER_TRAIN = path.join(WORKER_ROOT, 'train.py');

/** One spelling per file: these assertions are about WHICH file, never about
 *  the separator or the drive letter the host happens to spell it with. */
const resolved = (paths) => paths.map((p) => path.resolve(String(p)));

const log = { lines: [], info: (m) => log.lines.push(m), warn: (m) => log.lines.push(m), error: (m) => log.lines.push(m) };

/**
 * One MLV111 finding, as the analyzer emits it for a `train.py` whose eval
 * DataLoader shuffles. The id is a function of (code, relative file, qualname,
 * symbol) only — so BOTH folders below carry the identical id, exactly as the
 * real analyzer does.
 */
function shuffleIssue(root) {
  const absFile = path.join(root, 'train.py');
  return {
    id: 'i:4aaec0fa9d62',
    code: 'MLV111',
    ruleVersion: 1,
    severity: 'low',
    confidence: 0.95,
    confidenceBucket: 'certain',
    title: 'Evaluation DataLoader shuffles',
    message: 'val_loader shuffles the evaluation set.',
    why: 'Shuffling an evaluation loader makes per-batch logs unreproducible.',
    fixHint: 'Set shuffle=False on this evaluation DataLoader.',
    loc: {
      file: 'train.py',
      absFile,
      line: 12,
      col: 18,
      endLine: 12,
      endCol: 60,
      symbol: 'val_loader',
      snippet: '    val_loader = DataLoader(val_ds, batch_size=8, shuffle=True)'
    },
    relatedLocs: [],
    nodeIds: [],
    edgeIds: [],
    stage: 'eval',
    frameworks: ['torch'],
    tags: ['correctness'],
    evidence: [],
    suppressed: false,
    docs: 'docs/rules/MLV111.md',
    fix: {
      title: 'Set shuffle=False on this evaluation DataLoader',
      safety: 'mechanical',
      edits: [
        {
          file: 'train.py',
          absFile,
          line: 12,
          col: 51,
          endLine: 12,
          endCol: 63,
          newText: 'shuffle=False'
        }
      ]
    }
  };
}

function setUp() {
  vscode.__reset();
  log.lines.length = 0;
  vscode.__setWorkspaceFolders([API_ROOT, WORKER_ROOT]);
}

test('the premise: two folders really do produce the same issue id (§0 keys on the RELATIVE file)', () => {
  const a = shuffleIssue(API_ROOT);
  const b = shuffleIssue(WORKER_ROOT);
  assert.equal(a.id, b.id, 'the ids must collide for the rest of this file to mean anything');
  assert.notEqual(a.loc.absFile, b.loc.absFile);
});

test('issueById on a multi-root window resolves an ambiguous id, and must not do so silently', () => {
  setUp();
  const apiIssue = shuffleIssue(API_ROOT);
  const workerIssue = shuffleIssue(WORKER_ROOT);
  const deps = { log, graphs: () => [{ issues: [apiIssue] }, { issues: [workerIssue] }] };

  const found = issueById(deps, 'i:4aaec0fa9d62');
  assert.ok(found, 'the id must still resolve');

  const matches = deps
    .graphs()
    .flatMap((g) => g.issues)
    .filter((i) => i.id === 'i:4aaec0fa9d62');
  assert.equal(matches.length, 2, 'two folders, one id');

  // The failure this pins: the id alone cannot say WHICH folder, and the host
  // picks the first graph without saying so. Whatever the fix is — a folder
  // argument on applyFix, a folder-qualified id, or a refusal — the one thing
  // that must not happen is a silent, order-dependent choice.
  assert.equal(
    found.loc.absFile,
    API_TRAIN,
    'today the first graph wins; if that changes the whole contract below changes with it'
  );
});

test('applying a fix by id alone edits the FIRST folder, not necessarily the one the user meant', async () => {
  setUp();
  const apiIssue = shuffleIssue(API_ROOT);
  const workerIssue = shuffleIssue(WORKER_ROOT);

  // The user is looking at the `worker` diagram and clicks its "Fix available".
  // The rail sends only the id (H5), and `worker` happens to be second in the
  // folder book.
  const deps = { log, graphs: () => [{ issues: [apiIssue] }, { issues: [workerIssue] }] };
  assert.equal(readFix(workerIssue).ok, true, 'the fixture must carry an applicable fix');

  const result = await applyIssueFix('i:4aaec0fa9d62', deps);
  assert.equal(result.applied, true, `the fix should apply, got ${JSON.stringify(result)}`);

  const edits = vscode.__recorded.appliedEdits;
  assert.equal(edits.length, 1, 'exactly one WorkspaceEdit');
  const touched = resolved(edits[0].edits.map((e) => e.uri.fsPath));
  assert.deepEqual(
    touched,
    [API_TRAIN],
    'the edit landed in /work/api/train.py — the user clicked the finding in /work/worker'
  );
  assert.ok(
    !touched.includes(WORKER_TRAIN),
    'REGRESSION MARKER: once applyFix is folder-aware this assertion flips, and the one above with it'
  );
});

test('the same id in the other folder order edits the other file — the choice is pure array order', async () => {
  setUp();
  const apiIssue = shuffleIssue(API_ROOT);
  const workerIssue = shuffleIssue(WORKER_ROOT);
  // Only the folder order changed. Nothing the user did changed.
  const deps = { log, graphs: () => [{ issues: [workerIssue] }, { issues: [apiIssue] }] };
  const result = await applyIssueFix('i:4aaec0fa9d62', deps);
  assert.equal(result.applied, true);
  const touched = resolved(vscode.__recorded.appliedEdits[0].edits.map((e) => e.uri.fsPath));
  assert.deepEqual(
    touched,
    [WORKER_TRAIN],
    'the same id, the same click, a different file — which is the defect this file records'
  );
});

test('a single-folder window is unaffected: the id names exactly one finding', async () => {
  vscode.__reset();
  log.lines.length = 0;
  vscode.__setWorkspaceFolders([API_ROOT]);
  const deps = { log, graphs: () => [{ issues: [shuffleIssue(API_ROOT)] }] };
  const result = await applyIssueFix('i:4aaec0fa9d62', deps);
  assert.equal(result.applied, true);
  const touched = resolved(vscode.__recorded.appliedEdits[0].edits.map((e) => e.uri.fsPath));
  assert.deepEqual(touched, [API_TRAIN]);
});
