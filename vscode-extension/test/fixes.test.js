'use strict';
/**
 * H5 — structured fixes, host half (docs/contracts/11.43-host-fixes-and-comparison.md).
 *
 * `REQUIREMENTS.md` §5 non-goal 5 was lifted for exactly this feature and exactly these
 * guardrails, so these tests are the guardrails rather than a tour of the happy path:
 *
 *   1. Rules OPT IN — a finding with no `fix` produces no code action at all.
 *   2. Nothing below the `likely` bucket ever produces an edit.
 *   3. `isPreferred` is set for `mechanical` and for nothing else.
 *   4. NEVER auto-applied — every entry carries `needsConfirmation`, the apply asks for
 *      `isRefactoring`, and no `source.fixAll` kind is offered to `codeActionsOnSave`.
 *   5. An edit outside every open workspace folder is REFUSED, not redirected.
 *
 * The edits themselves are asserted against a virtual document, byte for byte, because a fix
 * that lands one column off is a fix that broke somebody's training loop.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { api, vscode } = require('./harness.js');

const {
  readFix,
  buildFixEdit,
  isMechanical,
  fixActionTitle,
  issuesAt,
  issueById,
  applyIssueFix,
  registerFixActions,
  MlviewFixActionProvider,
  APPLY_FIX_COMMAND,
  FIXABLE_BUCKETS,
  MAX_FIX_EDITS,
  isUiToHost
} = api;

const ROOT = '/repo';
const TRAIN = '/repo/train.py';
const OUTSIDE = '/elsewhere/train.py';

const log = {
  lines: [],
  info(m) {
    this.lines.push(`info ${m}`);
  },
  warn(m) {
    this.lines.push(`warn ${m}`);
  },
  error(m) {
    this.lines.push(`error ${m}`);
  },
  debug() {},
  trace() {},
  raw() {},
  show() {},
  dispose() {}
};

/** The exact shape `analyzer/src/mlview/schema/graph.schema.json` defines for `Fix`. */
function fixOf(overrides = {}) {
  return {
    title: 'Add optimizer.zero_grad() before the backward pass',
    safety: 'mechanical',
    edits: [
      {
        file: 'train.py',
        absFile: TRAIN,
        line: 3,
        col: 8,
        endLine: 3,
        endCol: 8,
        newText: 'optimizer.zero_grad()\n        '
      }
    ],
    ...overrides
  };
}

function issueOf(overrides = {}) {
  return {
    id: 'i:zero-grad',
    code: 'MLV201',
    severity: 'high',
    confidence: 0.95,
    confidenceBucket: 'certain',
    title: 'Gradients are never zeroed',
    message: 'no zero_grad() before backward()',
    why: 'gradients accumulate across steps',
    fixHint: 'call optimizer.zero_grad()',
    loc: { file: 'train.py', absFile: TRAIN, line: 3, col: 8, endLine: 3, endCol: 22 },
    relatedLocs: [],
    nodeIds: [],
    edgeIds: [],
    stage: 'train',
    frameworks: [],
    tags: [],
    evidence: [],
    suppressed: false,
    fix: fixOf(),
    ...overrides
  };
}

function depsOf(issues) {
  return { log, graphs: () => [{ issues }] };
}

function setUp() {
  vscode.__reset();
  log.lines.length = 0;
  vscode.__setWorkspaceFolders([ROOT]);
}

// ------------------------------------------------------- 1. rules opt in, and only rules

test('a finding with no fix produces no reading, no action and no complaint', () => {
  setUp();
  const issue = issueOf({ fix: undefined });
  const reading = readFix(issue);
  assert.equal(reading.ok, false);
  assert.equal(reading.reason, 'no-fix');

  const provider = new MlviewFixActionProvider(depsOf([issue]));
  const actions = provider.provideCodeActions(
    { uri: vscode.Uri.file(TRAIN) },
    new vscode.Range(2, 0, 2, 0),
    { diagnostics: [] }
  );
  assert.deepEqual(actions, []);
  // "no fix" is the normal case for 31 of the 36 rules, so it must not be logged as a problem.
  assert.deepEqual(log.lines, []);
});

test('the analyzer schema shape reads back exactly, field for field', () => {
  const reading = readFix(issueOf());
  assert.equal(reading.ok, true);
  assert.equal(reading.fix.safety, 'mechanical');
  assert.equal(reading.fix.edits.length, 1);
  assert.deepEqual(reading.fix.edits[0], {
    file: 'train.py',
    absFile: TRAIN,
    line: 3,
    col: 8,
    endLine: 3,
    endCol: 8,
    newText: 'optimizer.zero_grad()\n        '
  });
});

// ------------------------------------------------------- 2. the confidence floor

test('no fix at all below the likely bucket, whatever the analyzer sent', () => {
  assert.deepEqual([...FIXABLE_BUCKETS], ['certain', 'likely']);
  for (const bucket of ['possible', 'speculative']) {
    const reading = readFix(issueOf({ confidenceBucket: bucket }));
    assert.equal(reading.ok, false, `${bucket} must not yield a fix`);
    assert.equal(reading.reason, 'low-confidence');
  }
  for (const bucket of ['certain', 'likely']) {
    assert.equal(readFix(issueOf({ confidenceBucket: bucket })).ok, true);
  }
});

test('a malformed fix is refused rather than half-understood', () => {
  const bad = [
    { title: '', safety: 'mechanical', edits: fixOf().edits },
    { title: 'x', safety: 'automatic', edits: fixOf().edits },
    { title: 'x', safety: 'mechanical', edits: [] },
    { title: 'x', safety: 'mechanical', edits: [{ ...fixOf().edits[0], line: 0 }] },
    { title: 'x', safety: 'mechanical', edits: [{ ...fixOf().edits[0], endLine: 2 }] },
    { title: 'x', safety: 'mechanical', edits: [{ ...fixOf().edits[0], absFile: 'train.py' }] },
    { title: 'x', safety: 'mechanical', edits: [{ ...fixOf().edits[0], newText: 7 }] },
    // One bad entry sinks the whole fix: half of a fix is a broken file.
    { title: 'x', safety: 'mechanical', edits: [fixOf().edits[0], { newText: 'x' }] },
    'a string',
    []
  ];
  for (const fix of bad) {
    const reading = readFix(issueOf({ fix }));
    assert.equal(reading.ok, false, `${JSON.stringify(fix)} should be refused`);
    assert.ok(['malformed', 'too-many-edits'].includes(reading.reason));
  }
  const many = { title: 'x', safety: 'mechanical', edits: [] };
  for (let i = 0; i <= MAX_FIX_EDITS; i += 1) {
    many.edits.push(fixOf().edits[0]);
  }
  assert.equal(readFix(issueOf({ fix: many })).reason, 'too-many-edits');
});

// ------------------------------------------------------- 3. isPreferred only for mechanical

test('isPreferred is set for mechanical and for nothing else', () => {
  setUp();
  const mechanical = issueOf();
  const review = issueOf({
    id: 'i:needs-review',
    code: 'MLV111',
    fix: fixOf({ safety: 'needs-review', title: 'Insert model.eval() before evaluation' })
  });
  assert.equal(isMechanical(readFix(mechanical).fix), true);
  assert.equal(isMechanical(readFix(review).fix), false);

  const provider = new MlviewFixActionProvider(depsOf([mechanical, review]));
  const actions = provider.provideCodeActions(
    { uri: vscode.Uri.file(TRAIN) },
    new vscode.Range(2, 8, 2, 8),
    { diagnostics: [] }
  );
  assert.equal(actions.length, 2);
  assert.equal(actions[0].isPreferred, true);
  assert.equal(actions[1].isPreferred, false);
  assert.equal(actions[0].title, fixActionTitle(mechanical, readFix(mechanical).fix));
  assert.match(actions[0].title, /MLV201/);
});

// ------------------------------------------------------- 4. never auto-applied

test('every entry needs confirmation, so the edit cannot land without a preview', () => {
  setUp();
  const built = buildFixEdit(readFix(issueOf()).fix, log);
  assert.equal(built.ok, true);
  assert.equal(built.edit.edits.length, 1);
  for (const entry of built.edit.edits) {
    assert.equal(entry.metadata.needsConfirmation, true);
    assert.match(entry.metadata.description, /^MLView · (mechanical|needs-review)$/);
  }
});

test('applying asks VS Code for the refactor preview, never a silent write', async () => {
  setUp();
  vscode.__setDocument(TRAIN, ['for x in loader:', '    y = model(x)', '        loss.backward()'].join('\n'));
  const deps = depsOf([issueOf()]);
  const result = await applyIssueFix('i:zero-grad', deps);
  assert.equal(result.applied, true);
  assert.equal(vscode.__recorded.appliedEdits.length, 1);
  assert.deepEqual(vscode.__recorded.applyEditMetadata[0], { isRefactoring: true });
});

test('the provider contributes QuickFix ONLY - never the kind codeActionsOnSave runs', () => {
  setUp();
  const disposables = registerFixActions(depsOf([issueOf()]));
  const registration = vscode.__recorded.codeActionProviders.at(-1);
  assert.deepEqual(
    registration.metadata.providedCodeActionKinds.map((k) => k.value),
    ['quickfix'],
    'a source.fixAll kind would let editor.codeActionsOnSave edit a training loop unattended'
  );
  assert.deepEqual(registration.selector, { language: 'python' });
  assert.ok(vscode.__recorded.commands.has(APPLY_FIX_COMMAND));
  for (const d of disposables) {
    d.dispose();
  }
});

// ------------------------------------------------------- 4b. 11.42 I.3: stale coordinates

test('an unsaved buffer is refused: the analysis read the file on DISK', async () => {
  setUp();
  vscode.__setDocument(TRAIN, ['a', 'b', '        loss.backward()'].join('\n'));
  vscode.__setDirty(TRAIN);
  const result = await applyIssueFix('i:zero-grad', depsOf([issueOf()]));
  assert.equal(result.applied, false);
  assert.equal(result.reason, 'stale-document');
  assert.equal(vscode.__recorded.appliedEdits.length, 0);
  assert.ok(
    vscode.__recorded.messages.some((m) => /stale\s+coordinates/.test(String(m[1]))),
    'the refusal names the reason and what to do about it'
  );
});

test('a file shorter than the analysis saw is refused, not clamped', async () => {
  setUp();
  vscode.__setDocument(TRAIN, 'loss.backward()');
  const result = await applyIssueFix('i:zero-grad', depsOf([issueOf()]));
  assert.equal(result.applied, false);
  assert.equal(result.reason, 'stale-document');
  assert.equal(vscode.__recorded.appliedEdits.length, 0);
});

// ------------------------------------------------------- 5. containment

test('an edit outside every workspace folder is refused, not redirected', () => {
  setUp();
  const outside = fixOf({
    edits: [{ ...fixOf().edits[0], file: '../train.py', absFile: OUTSIDE }]
  });
  const built = buildFixEdit(outside, log);
  assert.equal(built.ok, false);
  assert.equal(built.reason, 'outside-workspace');
  assert.equal(built.detail, OUTSIDE);
  assert.ok(log.lines.some((l) => l.includes('outside every open workspace folder')));
});

test('a fix whose SECOND edit escapes is refused whole, so nothing partial lands', async () => {
  setUp();
  vscode.__setDocument(TRAIN, ['a', 'b', '        loss.backward()'].join('\n'));
  const half = fixOf({
    edits: [fixOf().edits[0], { ...fixOf().edits[0], absFile: OUTSIDE }]
  });
  const result = await applyIssueFix('i:zero-grad', depsOf([issueOf({ fix: half })]));
  assert.equal(result.applied, false);
  assert.equal(result.reason, 'outside-workspace');
  assert.equal(vscode.__recorded.appliedEdits.length, 0, 'not one byte may be written');
});

// ------------------------------------------------------- the edit itself

test('an insertion lands at the exact column and leaves the rest of the line alone', async () => {
  setUp();
  vscode.__setDocument(TRAIN, ['import torch', '', '        loss.backward()'].join('\n'));
  await applyIssueFix('i:zero-grad', depsOf([issueOf()]));
  const after = vscode.__getDocument(TRAIN);
  assert.equal(
    after,
    ['import torch', '', '        optimizer.zero_grad()\n        loss.backward()'].join('\n')
  );
});

test('a replacement replaces exactly its range', async () => {
  setUp();
  vscode.__setDocument(TRAIN, 'loader = DataLoader(ds, shuffle=True)');
  const issue = issueOf({
    id: 'i:shuffle',
    code: 'MLV110',
    loc: { file: 'train.py', absFile: TRAIN, line: 1, col: 24, endLine: 1, endCol: 36 },
    fix: fixOf({
      title: 'Set shuffle=False on this evaluation DataLoader',
      edits: [
        {
          file: 'train.py',
          absFile: TRAIN,
          line: 1,
          col: 32,
          endLine: 1,
          endCol: 36,
          newText: 'False'
        }
      ]
    })
  });
  await applyIssueFix('i:shuffle', depsOf([issue]));
  assert.equal(vscode.__getDocument(TRAIN), 'loader = DataLoader(ds, shuffle=False)');
});

// ------------------------------------------------------- the two surfaces are one path

test('the webview may send an issue id and NOTHING else', () => {
  assert.equal(isUiToHost({ v: 1, type: 'applyFix', issueId: 'i:zero-grad' }), true);
  assert.equal(isUiToHost({ v: 1, type: 'applyFix', issueId: '' }), false);
  assert.equal(
    isUiToHost({ v: 1, type: 'applyFix', issueId: 'i:x', newText: 'os.system("rm -rf /")' }),
    true,
    'extra keys are ignored by the guard - and by the handler, which reads only issueId'
  );
});

test("the command and the viewer's message run the SAME function", async () => {
  setUp();
  vscode.__setDocument(TRAIN, ['a', 'b', '        loss.backward()'].join('\n'));
  const deps = depsOf([issueOf()]);
  registerFixActions(deps);
  const handler = vscode.__recorded.commands.get(APPLY_FIX_COMMAND);
  await handler('i:zero-grad');
  const viaCommand = vscode.__getDocument(TRAIN);

  vscode.__setDocument(TRAIN, ['a', 'b', '        loss.backward()'].join('\n'));
  await applyIssueFix('i:zero-grad', deps);
  assert.equal(vscode.__getDocument(TRAIN), viaCommand);
});

test('an id that is not in the current analysis is reported, not guessed at', async () => {
  setUp();
  const result = await applyIssueFix('i:nothing', depsOf([issueOf()]));
  assert.equal(result.applied, false);
  assert.equal(vscode.__recorded.appliedEdits.length, 0);
  assert.equal(issueById(depsOf([issueOf()]), 'i:nothing'), undefined);
  assert.ok(
    vscode.__recorded.messages.some((m) => /not in the current analysis/.test(String(m[1]))),
    'the user is told why nothing happened'
  );
});

// ------------------------------------------------------- which findings are offered where

test('only findings anchored in THIS document, at the cursor, are offered', () => {
  setUp();
  const here = issueOf();
  const elsewhere = issueOf({
    id: 'i:other-file',
    loc: { file: 'data.py', absFile: '/repo/data.py', line: 3, col: 8, endLine: 3, endCol: 20 }
  });
  const farAway = issueOf({
    id: 'i:far',
    loc: { file: 'train.py', absFile: TRAIN, line: 90, col: 0, endLine: 90, endCol: 4 }
  });
  const deps = depsOf([here, elsewhere, farAway]);
  assert.deepEqual(
    issuesAt(deps, { uri: vscode.Uri.file(TRAIN) }, new vscode.Range(2, 0, 2, 0)).map((i) => i.id),
    ['i:zero-grad']
  );
});

test('a notebook cell document is never offered a fix', () => {
  setUp();
  const provider = new MlviewFixActionProvider(depsOf([issueOf()]));
  const cellUri = { scheme: 'vscode-notebook-cell', fsPath: TRAIN, path: TRAIN };
  assert.deepEqual(
    provider.provideCodeActions({ uri: cellUri }, new vscode.Range(2, 0, 2, 0), {
      diagnostics: []
    }),
    [],
    'the finding names the generated shadow module, which the user never wrote'
  );
});
