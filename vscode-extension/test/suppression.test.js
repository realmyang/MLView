'use strict';
/**
 * MLV-P10 — suppression as a one-click action (docs/CONTRACTS.md §11.27).
 *
 * The measured problem: suppression works perfectly on the CLI and is unreachable from
 * any UI, so the workflow for "this one is a false positive" is find a doc in the repo,
 * memorise the syntax, switch to the editor, type it. These tests hold the three
 * gestures that replace that, and the two things that make them safe to ship — the
 * config write is confirmed and inside the workspace, and nothing here edits ML logic.
 *
 * The text transforms are asserted byte for byte, because the analyzer's own
 * `rules/suppress.py` is the reader: a comment that is one character off suppresses
 * nothing and looks like it worked.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { api, vscode } = require('./harness.js');

const {
  ignoreComment,
  withIgnoreComment,
  addDisabledRule,
  isInsideWorkspace,
  isRuleCode,
  MlviewCodeActionProvider,
  mlviewCodesIn,
  diagnosticCode,
  copyActionTitle,
  addActionTitle,
  disableActionTitle,
  copyIgnoreComment,
  addIgnoreComment,
  disableRule,
  runSuppression,
  COPY_IGNORE_COMMAND,
  ADD_IGNORE_COMMAND,
  DISABLE_RULE_COMMAND,
  CONFIG_FILE,
  DIAGNOSTIC_SOURCE,
  isUiToHost
} = api;

const log = {
  info() {},
  warn() {},
  error() {},
  debug() {},
  trace() {},
  raw() {},
  show() {},
  dispose() {}
};

// ------------------------------------------------------------ the comment

test('the comment is exactly what analyzer/src/mlview/rules/suppress.py matches', () => {
  assert.equal(ignoreComment('MLV201'), '# mlview: ignore[MLV201]');
  // The analyzer's IGNORE_RE, transcribed. If this stops matching, the feature is a no-op.
  const IGNORE_RE = /#\s*mlview\s*:\s*ignore(?:-(?<file>file))?(?:\s*\[(?<codes>[^\]]*)\])?/i;
  const found = IGNORE_RE.exec(ignoreComment('MLV301'));
  assert.ok(found);
  assert.equal(found.groups.codes, 'MLV301');
});

test('a fresh line gets the comment appended, with trailing whitespace trimmed', () => {
  assert.deepEqual(withIgnoreComment('    X = scaler.fit_transform(X)', 'MLV101'), {
    text: '    X = scaler.fit_transform(X)  # mlview: ignore[MLV101]',
    changed: true
  });
  assert.deepEqual(withIgnoreComment('code()   \t', 'MLV201'), {
    text: 'code()  # mlview: ignore[MLV201]',
    changed: true
  });
  assert.deepEqual(withIgnoreComment('', 'MLV201'), {
    text: '# mlview: ignore[MLV201]',
    changed: true
  });
});

test('a second code MERGES into the existing list instead of being appended dead', () => {
  // The analyzer reads the FIRST match on the line, so a second comment does nothing.
  const merged = withIgnoreComment('fit(X)  # mlview: ignore[MLV101]', 'MLV301');
  assert.equal(merged.changed, true);
  assert.equal(merged.text, 'fit(X)  # mlview: ignore[MLV101, MLV301]');
  assert.equal((merged.text.match(/mlview: ignore/g) || []).length, 1);

  const three = withIgnoreComment(merged.text, 'MLV401');
  assert.equal(three.text, 'fit(X)  # mlview: ignore[MLV101, MLV301, MLV401]');
});

test('an already-suppressed line is left alone, and says which kind of already', () => {
  const listed = withIgnoreComment('fit(X)  # mlview: ignore[MLV101]', 'MLV101');
  assert.equal(listed.changed, false);
  assert.equal(listed.reason, 'already-listed');
  assert.equal(listed.text, 'fit(X)  # mlview: ignore[MLV101]');

  const blanket = withIgnoreComment('fit(X)  # mlview: ignore', 'MLV101');
  assert.equal(blanket.changed, false);
  assert.equal(blanket.reason, 'already-blanket');

  const wholeFile = withIgnoreComment('# mlview: ignore-file', 'MLV101');
  assert.equal(wholeFile.changed, false);
  assert.equal(wholeFile.reason, 'already-blanket');
});

// ------------------------------------------------------------- .mlview.toml

test('an empty or missing config gets the whole section', () => {
  assert.deepEqual(addDisabledRule('', 'MLV601'), {
    text: '[rules]\ndisable = ["MLV601"]\n',
    changed: true
  });
});

test('a config with other sections keeps them, and gains [rules] at the end', () => {
  const before = '[paths]\nexclude = ["experiments/**"]\n';
  const after = addDisabledRule(before, 'MLV601');
  assert.equal(after.changed, true);
  assert.ok(after.text.startsWith(before.trimEnd()), 'the existing content is untouched');
  assert.match(after.text, /\[rules\]\ndisable = \["MLV601"\]\n$/);
});

test('an existing [rules] section gains the key, and an existing key gains the code', () => {
  const noKey = addDisabledRule('[rules]\n# a comment\n', 'MLV601');
  assert.equal(noKey.text, '[rules]\ndisable = ["MLV601"]\n# a comment\n');

  const withKey = addDisabledRule('[rules]\ndisable = ["MLV101"]\n', 'MLV601');
  assert.equal(withKey.text, '[rules]\ndisable = ["MLV101", "MLV601"]\n');

  const other = addDisabledRule('[rules]\ndisable = ["MLV101"]\n\n[paths]\nexclude = []\n', 'MLV601');
  assert.equal(other.text, '[rules]\ndisable = ["MLV101", "MLV601"]\n\n[paths]\nexclude = []\n');
});

test('a multi-line array is folded into one line rather than corrupted', () => {
  const before = '[rules]\ndisable = [\n  "MLV101",\n  "MLV301",\n]\n';
  const after = addDisabledRule(before, 'MLV601');
  assert.equal(after.text, '[rules]\ndisable = ["MLV101", "MLV301", "MLV601"]\n');
});

test('adding a code twice is a no-op, and CRLF survives', () => {
  assert.deepEqual(addDisabledRule('[rules]\ndisable = ["MLV601"]\n', 'MLV601'), {
    text: '[rules]\ndisable = ["MLV601"]\n',
    changed: false
  });
  const crlf = addDisabledRule('[rules]\r\ndisable = ["MLV101"]\r\n', 'MLV601');
  assert.ok(crlf.text.includes('\r\n'), 'a CRLF file must not be rewritten to LF');
});

test('an unterminated array is refused rather than half-written', () => {
  const broken = '[rules]\ndisable = [\n  "MLV101",\n';
  assert.deepEqual(addDisabledRule(broken, 'MLV601'), { text: broken, changed: false });
});

// ------------------------------------------------------------- containment

test('containment is the same rule every other write path in the repo uses', () => {
  assert.equal(isInsideWorkspace('/repo', '/repo/.mlview.toml'), true);
  assert.equal(isInsideWorkspace('/repo', '/repo'), true);
  assert.equal(isInsideWorkspace('/repo', '/repo-evil/.mlview.toml'), false);
  assert.equal(isInsideWorkspace('/repo', '/etc/passwd'), false);
  assert.equal(isInsideWorkspace('', '/anything'), false, 'no root means no write');
});

test('only a real rule code is ever accepted', () => {
  for (const good of ['MLV101', 'MLV999']) assert.equal(isRuleCode(good), true);
  for (const bad of ['MLV1', 'mlv101', 'MLV101 ', '../../etc', 42, null, undefined]) {
    assert.equal(isRuleCode(bad), false, String(bad));
  }
});

// ----------------------------------------------------------- the lightbulb

function diagnostic(code, line = 3, source = DIAGNOSTIC_SOURCE) {
  const d = new vscode.Diagnostic(new vscode.Range(line, 4, line, 20), 'msg', 1);
  d.source = source;
  d.code = code;
  return d;
}

test('the lightbulb offers all three actions, per rule code, on MLView diagnostics only', () => {
  const provider = new MlviewCodeActionProvider();
  const document = { uri: vscode.Uri.file('/repo/train.py') };
  const context = {
    diagnostics: [
      diagnostic('MLV201', 43),
      diagnostic('MLV201', 43), // the same code twice must not double the menu
      diagnostic('MLV101', 12),
      diagnostic('E501', 7, 'flake8'), // somebody else's diagnostic
      diagnostic({ value: 'MLV301', target: vscode.Uri.file('/docs/MLV301.md') }, 9)
    ]
  };
  const actions = provider.provideCodeActions(document, new vscode.Range(43, 0, 43, 1), context);
  assert.deepEqual(
    actions.map((a) => a.title),
    [
      copyActionTitle('MLV201'), addActionTitle('MLV201'), disableActionTitle('MLV201'),
      copyActionTitle('MLV101'), addActionTitle('MLV101'), disableActionTitle('MLV101'),
      copyActionTitle('MLV301'), addActionTitle('MLV301'), disableActionTitle('MLV301')
    ]
  );
  assert.ok(actions.every((a) => a.kind === vscode.CodeActionKind.QuickFix));
  assert.deepEqual(
    actions.map((a) => a.command.command),
    Array.from({ length: 3 }, () => [COPY_IGNORE_COMMAND, ADD_IGNORE_COMMAND, DISABLE_RULE_COMMAND]).flat()
  );
  // The insert action targets the diagnostic's OWN line, not the cursor's.
  const insert = actions.find((a) => a.command.command === ADD_IGNORE_COMMAND);
  assert.deepEqual(insert.command.arguments, [document.uri, 43, 'MLV201']);
  assert.equal(insert.isPreferred, true);
  assert.equal(mlviewCodesIn(context.diagnostics).length, 3);
  assert.equal(diagnosticCode(diagnostic('E501', 1)), undefined);
});

test('a document with no MLView diagnostics gets no MLView lightbulb', () => {
  const provider = new MlviewCodeActionProvider();
  const actions = provider.provideCodeActions(
    { uri: vscode.Uri.file('/repo/train.py') },
    new vscode.Range(0, 0, 0, 1),
    { diagnostics: [diagnostic('E501', 1, 'flake8')] }
  );
  assert.deepEqual(actions, []);
});

// ------------------------------------------------------------ the commands

test('copy puts the comment on the clipboard and refuses a code that is not one', async () => {
  vscode.__reset();
  const copied = [];
  const real = vscode.env.clipboard.writeText;
  vscode.env.clipboard.writeText = async (text) => void copied.push(text);
  try {
    assert.equal(await copyIgnoreComment('MLV201', log), true);
    assert.deepEqual(copied, ['# mlview: ignore[MLV201]']);
    assert.equal(await copyIgnoreComment('../../etc/passwd', log), false);
    assert.equal(copied.length, 1, 'nothing but a rule code reaches the clipboard');
  } finally {
    vscode.env.clipboard.writeText = real;
  }
});

test('the line action edits the document through a WorkspaceEdit', async () => {
  vscode.__reset();
  const file = '/repo/train.py';
  vscode.__setDocument(file, 'import x\nfit(X)\ny = 2\n');
  const ok = await addIgnoreComment(vscode.Uri.file(file), 1, 'MLV101', log);
  assert.equal(ok, true);
  const edits = vscode.__recorded.appliedEdits;
  assert.equal(edits.length, 1, 'exactly one edit, so one undo step');
  assert.equal(edits[0].edits[0].kind, 'replace');
  assert.equal(edits[0].edits[0].newText, 'fit(X)  # mlview: ignore[MLV101]');
  assert.equal(
    vscode.__getDocument(file),
    'import x\nfit(X)  # mlview: ignore[MLV101]\ny = 2\n'
  );
});

test('the line action never edits a line that is already suppressed, or out of range', async () => {
  vscode.__reset();
  const file = '/repo/train.py';
  vscode.__setDocument(file, 'fit(X)  # mlview: ignore[MLV101]\n');
  assert.equal(await addIgnoreComment(vscode.Uri.file(file), 0, 'MLV101', log), false);
  assert.equal(vscode.__recorded.appliedEdits.length, 0);
  assert.equal(await addIgnoreComment(vscode.Uri.file(file), 99, 'MLV101', log), false);
  assert.equal(vscode.__recorded.appliedEdits.length, 0);
});

test('disabling a rule asks first, and a cancelled dialog writes nothing', async () => {
  vscode.__reset();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-suppress-'));
  vscode.__setWorkspaceFolders([root]);
  try {
    // No answer queued: showWarningMessage returns undefined, i.e. the user dismissed it.
    assert.equal(await disableRule('MLV601', vscode.Uri.file(path.join(root, 'a.py')), log), false);
    assert.equal(fs.existsSync(path.join(root, CONFIG_FILE)), false, 'nothing was written');
    const [level, message, options] = vscode.__recorded.messages[0];
    assert.equal(level, 'warn');
    assert.match(message, /Disable MLV601 for the whole workspace\?/);
    assert.equal(options.modal, true, 'a project-wide change must be modal');
    assert.match(options.detail, /Every file in this workspace/);
    assert.match(options.detail, /Add ignore comment on this line/, 'offer the narrower gesture');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('a confirmed disable writes .mlview.toml at the workspace root, and is idempotent', async () => {
  vscode.__reset();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-suppress-'));
  vscode.__setWorkspaceFolders([root]);
  try {
    vscode.__answerMessage('Disable MLV601');
    assert.equal(await disableRule('MLV601', undefined, log), true);
    const written = fs.readFileSync(path.join(root, CONFIG_FILE), 'utf8');
    assert.equal(written, '[rules]\ndisable = ["MLV601"]\n');

    vscode.__answerMessage('Disable MLV601');
    assert.equal(await disableRule('MLV601', undefined, log), false, 'already disabled');
    assert.equal(fs.readFileSync(path.join(root, CONFIG_FILE), 'utf8'), written);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('with no folder open there is nowhere legal to write, and the user is told', async () => {
  vscode.__reset();
  vscode.__setWorkspaceFolders(undefined);
  vscode.__answerMessage('Disable MLV601');
  assert.equal(await disableRule('MLV601', undefined, log), false);
  const warned = vscode.__recorded.messages.filter(([level]) => level === 'warn');
  assert.equal(warned.length, 1);
  assert.match(warned[0][1], /open a folder/);
});

// --------------------------------------------------- the webview's own path

test('the suppressRule message is accepted only in the three documented shapes', () => {
  const ok = (extra) => isUiToHost({ v: 1, type: 'suppressRule', code: 'MLV201', ...extra });
  assert.equal(ok({ action: 'copy' }), true);
  assert.equal(ok({ action: 'disable' }), true);
  assert.equal(ok({ action: 'insert', absFile: '/repo/train.py', line: 44 }), true);
  assert.equal(ok({ action: 'delete' }), false, 'the viewer may not invent an action');
  assert.equal(ok({ action: 'insert', line: 0 }), false, 'lines are 1-based in the document');
  assert.equal(
    isUiToHost({ v: 1, type: 'suppressRule', code: 'DROP TABLE', action: 'copy' }),
    false
  );
  assert.equal(isUiToHost({ v: 1, type: 'suppressRule', action: 'copy' }), false);
});

test('the rail and the lightbulb run the SAME code, including the 1-based conversion', async () => {
  vscode.__reset();
  const file = '/repo/train.py';
  vscode.__setDocument(file, 'import x\nfit(X)\n');
  // The viewer speaks the document's 1-based lines; the editor is 0-based.
  const applied = await runSuppression(
    { code: 'MLV101', action: 'insert', absFile: file, line: 2 },
    log
  );
  assert.equal(applied, true);
  assert.equal(vscode.__getDocument(file), 'import x\nfit(X)  # mlview: ignore[MLV101]\n');
});

test('an insert with nowhere to insert degrades to the clipboard, never to nothing', async () => {
  vscode.__reset();
  const copied = [];
  const real = vscode.env.clipboard.writeText;
  vscode.env.clipboard.writeText = async (text) => void copied.push(text);
  try {
    const done = await runSuppression({ code: 'MLV101', action: 'insert' }, log);
    assert.equal(done, true);
    assert.deepEqual(copied, ['# mlview: ignore[MLV101]']);
  } finally {
    vscode.env.clipboard.writeText = real;
  }
});
