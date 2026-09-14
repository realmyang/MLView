'use strict';
/**
 * Hardening round 1, area hosts-ux — H5 (CONTRACTS 11.42 / 11.43) against REAL
 * analyzer documents rather than a hand-written `Issue.fix`.
 *
 * `test/fixes.test.js` drives the lightbulb with fixtures it authored itself, so
 * it can only be as right as its fixtures. This file takes the `fix` blocks the
 * analyzer actually emits over the shipped corpus — five rule codes
 * (MLV111, MLV201, MLV301, MLV302, MLV602) —
 * and asserts three things the editor path must hold for every one of them.
 * The eight projects below are the ones that carry an emitted fix; the whole
 * shipped corpus carries 80 of them over those five codes.
 *
 *  1. the lightbulb offers exactly the fixes the document carries, with the
 *     `isPreferred` / `QuickFix` / command-not-edit shape 11.42 and 11.43 fix;
 *  2. the `WorkspaceEdit` `buildFixEdit` produces converts §0's 1-based line and
 *     0-based column **exactly once** and lands inside the file it names, with
 *     `needsConfirmation` on every entry;
 *  3. **applying that edit to the bytes on disk produces a file that still
 *     parses.** An edit computed from the analyzer's AST that cannot survive a
 *     round trip through the host's range arithmetic is an off-by-one nobody
 *     would see until a user clicked it.
 *
 * The stronger claim — that the finding is gone after the fix and no new one
 * appeared — is measured out of process, because it needs a re-analysis per
 * fix; `python -m mlview analyze` on a patched copy is the check, and this file
 * pins the half that lives in the host.
 *
 * It skips itself when `python -m mlview` is not importable, the way the plugin
 * suite skips when the CLI is absent.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const { api, vscode, REPO_ROOT } = require('./harness.js');

const {
  MlviewFixActionProvider,
  readFix,
  isMechanical,
  buildFixEdit,
  issuesAt,
  fixActionTitle,
  APPLY_FIX_COMMAND,
  FIXABLE_BUCKETS
} = api;

const CORPUS = path.join(REPO_ROOT, 'analyzer', 'tests', 'accuracy', 'corpus');
const PYTHON = process.env.MLVIEW_TEST_PYTHON || 'python3';

/** Projects chosen because each one carries at least one emitted `Issue.fix`. */
const PROJECTS = [
  path.join(REPO_ROOT, 'samples', 'vision_pipeline'),
  path.join(CORPUS, 'torch_mechanics'),
  path.join(CORPUS, 'lightning_manual'),
  path.join(CORPUS, 'timeseries_split'),
  path.join(CORPUS, 'gbm_tabular'),
  path.join(CORPUS, 'keras_tfdata'),
  path.join(CORPUS, 'amp_accumulation'),
  path.join(CORPUS, 'hydra_research')
].filter((p) => fs.existsSync(p));

function analyze(project) {
  const out = execFileSync(
    PYTHON,
    ['-X', 'utf8', '-m', 'mlview', 'analyze', project, '--json', '-'],
    {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        PYTHONDONTWRITEBYTECODE: '1'
      }
    }
  );
  return JSON.parse(out);
}

let AVAILABLE = true;
const CACHE = new Map();
function graphOf(project) {
  if (!CACHE.has(project)) CACHE.set(project, analyze(project));
  return CACHE.get(project);
}
try {
  graphOf(PROJECTS[0]);
} catch {
  AVAILABLE = false;
}
const maybe = AVAILABLE ? test : test.skip;

const log = {
  lines: [],
  info: (m) => log.lines.push(m),
  warn: (m) => log.lines.push(m),
  error: (m) => log.lines.push(m)
};

/**
 * Point the mocked host at the project the graph came from. `buildFixEdit`
 * refuses an edit outside every open folder (11.42), so a test that forgets
 * this measures the containment guard rather than the arithmetic.
 */
function openFolder(project) {
  vscode.__reset();
  log.lines.length = 0;
  vscode.__setWorkspaceFolders([project]);
}

function fixableIssues(graph) {
  return (graph.issues || []).filter((i) => i.fix && FIXABLE_BUCKETS.includes(i.confidenceBucket));
}

/** A `TextDocument` stand-in: the provider reads only `uri`. */
function docFor(absFile) {
  return { uri: vscode.Uri.file(absFile) };
}

/**
 * One spelling for one file. The analyzer writes `absFile` forward-slashed
 * (CONTRACTS section 0: every path in the document is forward-slashed, on every
 * platform); `Uri.file(...).fsPath` gives the HOST separator. On Windows the
 * two are `D:/a/MLView/.../train.py` and `D:\\a\\MLView\\...\\train.py` -
 * the same file, and a strict compare of the two is a test of the separator
 * rather than of the edit's target.
 */
function samePath(a, b) {
  return path.resolve(String(a)) === path.resolve(String(b));
}

/** Apply one `vscode.Range`-shaped replacement (0-based line and character) to text. */
function applyRange(text, range, newText) {
  const lines = text.split('\n');
  assert.ok(range.start.line < lines.length, `start line ${range.start.line} past EOF (${lines.length})`);
  assert.ok(range.end.line < lines.length, `end line ${range.end.line} past EOF (${lines.length})`);
  const head = lines[range.start.line].slice(0, range.start.character);
  const tail = lines[range.end.line].slice(range.end.character);
  lines.splice(range.start.line, range.end.line - range.start.line + 1, head + newText + tail);
  return lines.join('\n');
}

maybe('the corpus really does carry emitted fixes — otherwise this file is vacuous', () => {
  const codes = new Set();
  let total = 0;
  for (const project of PROJECTS) {
    for (const issue of fixableIssues(graphOf(project))) {
      codes.add(issue.code);
      total += 1;
    }
  }
  assert.ok(total >= 8, `expected at least eight emitted fixes over the corpus, found ${total}`);
  assert.ok(codes.size >= 3, `expected at least three rule codes to compute a fix, found ${[...codes]}`);
});

maybe('the lightbulb offers exactly the emitted fixes, as a command and never as an attached edit', () => {
  for (const project of PROJECTS) {
    openFolder(project);
    const graph = graphOf(project);
    const name = path.basename(project);
    const deps = { log, graphs: () => [graph] };
    const provider = new MlviewFixActionProvider(deps);

    for (const issue of fixableIssues(graph)) {
      const line0 = issue.loc.line - 1;
      const range = new vscode.Range(line0, 0, line0, 0);
      const actions = provider.provideCodeActions(docFor(issue.loc.absFile), range, {
        diagnostics: []
      });
      const mine = actions.filter((a) => a.command && a.command.arguments[0] === issue.id);
      assert.equal(
        mine.length,
        1,
        `${name}: ${issue.code} at ${issue.loc.file}:${issue.loc.line} offered ${mine.length} actions`
      );
      const action = mine[0];
      assert.equal(action.kind, vscode.CodeActionKind.QuickFix, `${name}: ${issue.code} is not a QuickFix`);
      assert.equal(action.edit, undefined, `${name}: ${issue.code} attached an edit (11.43 A1 forbids it)`);
      assert.equal(action.command.command, APPLY_FIX_COMMAND);
      assert.equal(action.title, fixActionTitle(issue, issue.fix));
      assert.equal(
        action.isPreferred,
        isMechanical(issue.fix),
        `${name}: ${issue.code} isPreferred=${action.isPreferred} for safety=${issue.fix.safety}`
      );
    }
  }
});

maybe('an issue with no fix, and one below the bucket floor, get no lightbulb', () => {
  for (const project of PROJECTS) {
    openFolder(project);
    const graph = graphOf(project);
    const name = path.basename(project);
    const deps = { log, graphs: () => [graph] };
    const provider = new MlviewFixActionProvider(deps);
    for (const issue of graph.issues || []) {
      if (issue.fix && FIXABLE_BUCKETS.includes(issue.confidenceBucket)) continue;
      const line0 = issue.loc.line - 1;
      const actions = provider.provideCodeActions(
        docFor(issue.loc.absFile),
        new vscode.Range(line0, 0, line0, 0),
        { diagnostics: [] }
      );
      const mine = actions.filter((a) => a.command && a.command.arguments[0] === issue.id);
      assert.equal(
        mine.length,
        0,
        `${name}: ${issue.code} (${issue.confidenceBucket}, fix=${!!issue.fix}) was offered a lightbulb`
      );
    }
  }
});

maybe('a notebook-cell document is never offered a fix — the edit would repair a generated module', () => {
  openFolder(PROJECTS[0]);
  const graph = graphOf(PROJECTS[0]);
  const deps = { log, graphs: () => [graph] };
  const provider = new MlviewFixActionProvider(deps);
  const issue = fixableIssues(graph)[0];
  assert.ok(issue, 'the demo must carry at least one fixable finding');
  const cellUri = vscode.Uri.parse(`vscode-notebook-cell:${issue.loc.absFile}#ch0`);
  const actions = provider.provideCodeActions(
    { uri: cellUri },
    new vscode.Range(issue.loc.line - 1, 0, issue.loc.line - 1, 0),
    { diagnostics: [] }
  );
  assert.deepEqual(actions, [], 'a vscode-notebook-cell document must get no code actions');
});

maybe('every emitted edit converts §0 exactly once and carries needsConfirmation', () => {
  for (const project of PROJECTS) {
    openFolder(project);
    const graph = graphOf(project);
    const name = path.basename(project);
    for (const issue of fixableIssues(graph)) {
      const built = buildFixEdit(issue.fix, log);
      assert.equal(built.ok, true, `${name}: ${issue.code} refused: ${JSON.stringify(built)}`);
      assert.equal(
        built.edit.edits.length,
        issue.fix.edits.length,
        `${name}: ${issue.code} lost an edit entry`
      );
      built.edit.edits.forEach((recorded, i) => {
        const source = issue.fix.edits[i];
        assert.equal(recorded.kind, 'replace');
        assert.equal(
          recorded.range.start.line,
          source.line - 1,
          `${name}: ${issue.code} start line converted ${source.line} -> ${recorded.range.start.line}`
        );
        assert.equal(recorded.range.end.line, source.endLine - 1);
        // Columns are 0-based on BOTH sides and must not be shifted.
        assert.equal(recorded.range.start.character, source.col);
        assert.equal(recorded.range.end.character, source.endCol);
        assert.equal(recorded.newText, source.newText);
        assert.equal(
          recorded.metadata && recorded.metadata.needsConfirmation,
          true,
          `${name}: ${issue.code} edit ${i} would apply without the refactor preview`
        );
        assert.ok(
          samePath(recorded.uri.fsPath, source.absFile),
          `${name}: ${issue.code} edit ${i} names ${recorded.uri.fsPath}, not ${source.absFile}`
        );
      });
    }
  }
});

maybe('applying the built edit to the bytes on disk leaves a file that still parses', () => {
  for (const project of PROJECTS) {
    openFolder(project);
    const graph = graphOf(project);
    const name = path.basename(project);
    for (const issue of fixableIssues(graph)) {
      const built = buildFixEdit(issue.fix, log);
      assert.equal(built.ok, true);
      // One file per fix in this corpus; the loop keeps it honest if that changes.
      const byFile = new Map();
      for (const recorded of built.edit.edits) {
        const file = recorded.uri.fsPath;
        const text = byFile.get(file) ?? fs.readFileSync(file, 'utf8');
        byFile.set(file, applyRange(text, recorded.range, recorded.newText));
      }
      for (const [file, text] of byFile) {
        assert.notEqual(
          text,
          fs.readFileSync(file, 'utf8'),
          `${name}: ${issue.code} produced a no-op edit on ${path.basename(file)}`
        );
        const rel = path.relative(REPO_ROOT, file);
        const check = execFileSync(
          PYTHON,
          ['-X', 'utf8', '-c', 'import ast,sys;ast.parse(sys.stdin.read())'],
          {
            cwd: REPO_ROOT,
            input: text,
            encoding: 'utf8',
            env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' },
            stdio: ['pipe', 'pipe', 'pipe']
          }
        );
        assert.equal(check, '', `${name}: ${issue.code} left ${rel} unparseable`);
      }
    }
  }
});

maybe('issuesAt answers on every line a finding spans, and on no other file', () => {
  openFolder(PROJECTS[0]);
  const graph = graphOf(PROJECTS[0]);
  const deps = { log, graphs: () => [graph] };
  for (const issue of fixableIssues(graph)) {
    const start = issue.loc.line - 1;
    const end = issue.loc.endLine - 1;
    for (let line = start; line <= end; line += 1) {
      const hits = issuesAt(deps, docFor(issue.loc.absFile), new vscode.Range(line, 0, line, 0));
      assert.ok(
        hits.some((h) => h.id === issue.id),
        `${issue.code} is not offered on line ${line + 1} of the ${start + 1}..${end + 1} it spans`
      );
    }
    const elsewhere = issuesAt(
      deps,
      docFor(path.join(path.dirname(issue.loc.absFile), '__not_a_file__.py')),
      new vscode.Range(start, 0, start, 0)
    );
    assert.deepEqual(elsewhere, [], 'a finding answered for a file it is not in');
  }
});

maybe('readFix refuses an edit that names a file outside every workspace folder', () => {
  vscode.__reset();
  vscode.__setWorkspaceFolders([path.join(path.sep, 'work', 'only')]);
  const graph = graphOf(PROJECTS[0]);
  const issue = fixableIssues(graph)[0];
  const reading = readFix(issue);
  assert.equal(reading.ok, true, 'the fixture must carry a readable fix');
  const built = buildFixEdit(reading.fix, log);
  assert.equal(built.ok, false, 'an edit outside the open folder must be refused');
  assert.equal(built.reason, 'outside-workspace');
  vscode.__reset();
});
