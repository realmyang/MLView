'use strict';
/**
 * ROADMAP COVERAGE, host half — "I could not check" must never render as "I checked and it is
 * fine", and `MLView: Visualize (Current File)` must stop throwing away the cross-file rules.
 *
 * Two measured defects are behind every assertion here:
 *
 *   - `mlview issues <dir>/train.py` reports 3 findings where `mlview issues <dir> --scope
 *     file:train.py` reports 7. MLV301 / MLV302 / MLV401 / MLV501 need a sibling module, so a
 *     single-file run cannot fire them — and said nothing about it.
 *   - a workspace whose fit site is reached through an untagged parameter reports "0 high in
 *     preprocess" with no diagnostic at all.
 *
 * The analyzer now emits `single_file_analysis` and `untagged_dataflow` for those two; this file
 * asserts what the HOST does with them, plus the resolution table of the new setting. Everything
 * below is pure: no panel, no interpreter, no disk.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api, vscode } = require('./harness.js');

const REPO_ROOT = path.join(__dirname, '..', '..');

const {
  coverageChip,
  coverageFor,
  coverageLines,
  coverageNotes,
  COVERAGE_DIAGNOSTIC_KINDS,
  statusBarTooltip,
  NO_NOTEBOOKS,
  fileScopeSpec,
  focusScopeSpec,
  packageRootFor,
  resolveCurrentFileTarget,
  CURRENT_FILE_SCOPES,
  readSettings,
  DEFAULT_SETTINGS,
  buildAnalyzeDigest,
  buildIssuesDigest,
  analyzeDigestToText,
  issuesDigestToText,
  emptyGraph
} = api;

const SINGLE_FILE = {
  kind: 'single_file_analysis',
  message: 'Only train.py was analyzed; 4 cross-file rules could not run.',
  codes: ['MLV301', 'MLV302', 'MLV401', 'MLV501']
};
const UNTAGGED = {
  kind: 'untagged_dataflow',
  message: 'make_splits(X, y): the argument to train_test_split carries no data tag.',
  file: 'data.py',
  line: 12
};

const FRAMEWORK_FILTER = {
  kind: 'framework_filter',
  message:
    '--framework keras narrowed the rule set: 3 rule(s) that the detected frameworks would ' +
    'have run did not (MLV201, MLV202, MLV205). A clean result here is a clean result for ' +
    'keras alone - drop --framework (or pass auto) to judge the whole workspace.',
  codes: ['MLV201', 'MLV202', 'MLV205'],
  count: 3
};

function graphWith(diagnostics) {
  const graph = emptyGraph('C:/ws');
  graph.diagnostics = diagnostics;
  return graph;
}

// ------------------------------------------------------------------ reading the diagnostics

test('the coverage kinds are exactly the three the host claims to understand', () => {
  assert.deepEqual([...COVERAGE_DIAGNOSTIC_KINDS], [
    'single_file_analysis',
    'untagged_dataflow',
    'framework_filter'
  ]);
});

test('this host reads every coverage kind the core emits', () => {
  // The gate for the class, not the instance: `framework_filter` shipped in the core and in
  // neither host, so a run the user narrowed with `--framework` read as a clean bill of health.
  // Membership is compared as a SET — render order is each host's own (CONTRACTS §2.6 C8).
  const source = fs.readFileSync(
    path.join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'core', 'coverage.py'),
    'utf8'
  );
  const match = /^COVERAGE_KINDS = \(([^)]*)\)/m.exec(source);
  assert.ok(match, 'core.coverage must declare COVERAGE_KINDS as a tuple literal');
  const coreKinds = [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.ok(coreKinds.length >= 3, coreKinds.join(', '));
  assert.deepEqual(
    [...COVERAGE_DIAGNOSTIC_KINDS].sort(),
    [...coreKinds].sort(),
    `the core emits ${coreKinds.join(', ')}; this host reads ${COVERAGE_DIAGNOSTIC_KINDS.join(', ')}`
  );
  assert.equal(new Set(COVERAGE_DIAGNOSTIC_KINDS).size, COVERAGE_DIAGNOSTIC_KINDS.length);
});

test('a graph with no coverage diagnostics produces no caveat anywhere', () => {
  const graph = graphWith([{ kind: 'parse_error', message: 'bad.py: invalid syntax' }]);
  assert.deepEqual(coverageNotes(graph), []);
  assert.deepEqual(coverageFor(graph), []);
  assert.equal(coverageChip([]), undefined);
  assert.equal(
    statusBarTooltip({ low: 0, medium: 0, high: 0 }, false, false, NO_NOTEBOOKS, []),
    'MLView: 0 high, 0 medium, 0 low'
  );
});

test('the caveats are grouped per kind, counted, and ordered stably', () => {
  const graph = graphWith([
    { ...UNTAGGED },
    { kind: 'dynamic_scope', message: 'ignored here' },
    { ...UNTAGGED, file: 'model.py', line: 40, count: 3 },
    { ...SINGLE_FILE }
  ]);
  const notes = coverageNotes(graph);
  // single_file_analysis first, whatever order the analyzer emitted them in.
  assert.deepEqual(notes.map((n) => n.kind), ['single_file_analysis', 'untagged_dataflow']);
  assert.equal(notes[0].count, 1);
  assert.equal(notes[1].count, 4, 'one site plus a diagnostic that reported three');
  assert.deepEqual(notes[0].codes, ['MLV301', 'MLV302', 'MLV401', 'MLV501']);
});

test('a rendered caveat keeps the analyzer wording and names the rules that stayed silent', () => {
  const lines = coverageLines(coverageNotes(graphWith([SINGLE_FILE])));
  assert.equal(lines.length, 1);
  assert.ok(lines[0].startsWith('Only train.py was analyzed'), lines[0]);
  assert.ok(lines[0].includes('MLV301, MLV302, MLV401, MLV501'), lines[0]);
});

test('a kind sent with no message of its own still renders a usable sentence', () => {
  const lines = coverageLines(coverageNotes(graphWith([{ kind: 'untagged_dataflow' }])));
  assert.equal(lines.length, 1);
  assert.ok(lines[0].length > 20, lines[0]);
  assert.ok(!lines[0].includes('undefined'), lines[0]);
});

test('the chip counts blind spots and never uses the word clean', () => {
  assert.equal(
    coverageChip(coverageNotes(graphWith([SINGLE_FILE]))),
    'coverage: incomplete (1 blind spot)'
  );
  assert.equal(
    coverageChip(coverageNotes(graphWith([SINGLE_FILE, { ...UNTAGGED, count: 6 }]))),
    'coverage: incomplete (7 blind spots)'
  );
});

// ------------------------------------------------------------------- the narrowed framework

test('a narrowed framework is a caveat, not a clean result', () => {
  const notes = coverageNotes(graphWith([FRAMEWORK_FILTER]));
  assert.deepEqual(notes.map((n) => n.kind), ['framework_filter']);
  assert.equal(notes[0].count, 3, 'the count is suppressed rule codes');
  const lines = coverageLines(notes);
  assert.ok(lines[0].startsWith('--framework keras narrowed the rule set'), lines[0]);
  assert.ok(lines[0].includes('MLV201, MLV202, MLV205'), lines[0]);
  // The count is rules, not sites, so it is never suffixed as one.
  assert.ok(!lines[0].includes('(3 sites)'), lines[0]);
  assert.ok(!lines[0].toLowerCase().includes('clean result for the whole'), lines[0]);
});

test('suppressed rules are not tallied as blind spots', () => {
  assert.equal(
    coverageChip(coverageNotes(graphWith([FRAMEWORK_FILTER]))),
    'coverage: incomplete (framework filter)'
  );
  assert.equal(
    coverageChip(coverageNotes(graphWith([FRAMEWORK_FILTER, SINGLE_FILE]))),
    'coverage: incomplete (1 blind spot)',
    'three suppressed rule codes are not three blind sites'
  );
});

test('a framework_filter sent with no message of its own still renders a usable sentence', () => {
  const lines = coverageLines(coverageNotes(graphWith([{ kind: 'framework_filter' }])));
  assert.equal(lines.length, 1);
  assert.ok(lines[0].includes('framework'), lines[0]);
  assert.ok(!lines[0].includes('undefined'), lines[0]);
});

// -------------------------------------------------------------------------- the status bar

test('the status-bar tooltip says the count is a floor when the run was blind', () => {
  const tooltip = statusBarTooltip(
    { low: 0, medium: 0, high: 0 },
    false,
    false,
    NO_NOTEBOOKS,
    coverageFor(graphWith([SINGLE_FILE]))
  );
  assert.ok(tooltip.startsWith('MLView: 0 high, 0 medium, 0 low · coverage: incomplete'), tooltip);
  assert.ok(tooltip.includes('floor'), tooltip);
  assert.ok(tooltip.includes('MLV401'), tooltip);
});

test('a busy or failed status bar still says only that, coverage or not', () => {
  const coverage = coverageFor(graphWith([SINGLE_FILE]));
  assert.equal(statusBarTooltip({ low: 0, medium: 0, high: 0 }, true, false, NO_NOTEBOOKS, coverage),
    'MLView: analyzing…');
  assert.ok(
    statusBarTooltip({ low: 0, medium: 0, high: 0 }, false, true, NO_NOTEBOOKS, coverage).startsWith(
      'MLView: analysis failed'
    )
  );
});

// ------------------------------------------------------------------------- the LM digests

test('the analyze digest carries the caveat and the text form tells the model to repeat it', () => {
  const graph = graphWith([SINGLE_FILE]);
  const digest = buildAnalyzeDigest(graph);
  assert.equal(digest.coverage.length, 1);
  const text = analyzeDigestToText(digest);
  assert.ok(text.includes('INCOMPLETE'), text);
  assert.ok(text.includes('MLV301'), text);
});

test('an EMPTY issue list still carries the caveat - that is the whole point', () => {
  const digest = buildIssuesDigest(graphWith([UNTAGGED]));
  assert.equal(digest.issues.length, 0);
  const text = issuesDigestToText(digest);
  assert.ok(text.includes('No matching issues.'), text);
  assert.ok(text.includes('INCOMPLETE'), text);
  assert.ok(text.includes('train_test_split'), text);
});

// ------------------------------------------------------- what "Visualize (Current File)" runs

const WS = 'C:/ws';
const NO_FILES = () => false;
const packages = (...dirs) => {
  const set = new Set(dirs.map((d) => `${d}/__init__.py`));
  return (candidate) => set.has(candidate.replace(/\\/g, '/'));
};

test('the setting offers exactly file | package | workspace and defaults to package', () => {
  assert.deepEqual([...CURRENT_FILE_SCOPES], ['file', 'package', 'workspace']);
  assert.equal(DEFAULT_SETTINGS.currentFileAnalysisScope, 'package');
});

test('an unknown value in the settings file falls back to the default, never to file', () => {
  vscode.__resetConfig();
  vscode.__setConfig('mlview', 'currentFileAnalysisScope', 'everything');
  assert.equal(readSettings().currentFileAnalysisScope, 'package');
  vscode.__setConfig('mlview', 'currentFileAnalysisScope', 'file');
  assert.equal(readSettings().currentFileAnalysisScope, 'file');
  vscode.__resetConfig();
});

test('a file in no package resolves to its own directory - the COVERAGE acceptance case', () => {
  const target = resolveCurrentFileTarget(`${WS}/samples/vision/train.py`, WS, 'package', NO_FILES);
  assert.deepEqual(target, {
    scope: 'file',
    path: `${WS}/samples/vision`,
    focusFile: `${WS}/samples/vision/train.py`
  });
});

test('a nested package resolves to the OUTERMOST package directory, and stops there', () => {
  const exists = packages(`${WS}/src`, `${WS}/src/data`);
  assert.equal(packageRootFor(`${WS}/src/data/loader.py`, WS, exists), `${WS}/src`);
  // `${WS}` itself is not a package, so the climb stops at src rather than swallowing the repo.
  assert.equal(packageRootFor(`${WS}/src/train.py`, WS, exists), `${WS}/src`);
});

test('the climb never leaves the workspace root even when the root itself is a package', () => {
  const exists = packages(WS, `${WS}/pkg`);
  assert.equal(packageRootFor(`${WS}/pkg/mod.py`, WS, exists), `${WS}/pkg`);
});

test('backslashes and a trailing separator on the root do not defeat the containment check', () => {
  const exists = packages(`${WS}/pkg`);
  assert.equal(packageRootFor(`C:\\ws\\pkg\\mod.py`, 'C:/ws/', exists), 'C:/ws/pkg');
});

test('file scope keeps the old behaviour and asks for no projection', () => {
  const target = resolveCurrentFileTarget(`${WS}/pkg/train.py`, WS, 'file', NO_FILES);
  assert.deepEqual(target, { scope: 'file', path: `${WS}/pkg/train.py` });
  assert.equal(target.focusFile, undefined, 'a one-file graph scoped to that file changes nothing');
});

test('workspace scope analyses everything and still narrows the diagram to the file', () => {
  assert.deepEqual(resolveCurrentFileTarget(`${WS}/pkg/train.py`, WS, 'workspace', NO_FILES), {
    scope: 'workspace',
    focusFile: `${WS}/pkg/train.py`
  });
});

test('the projection uses the section 11.1 file: selector, workspace-relative', () => {
  assert.equal(fileScopeSpec('pkg/train.py'), 'file:pkg/train.py');
  assert.equal(focusScopeSpec(WS, `${WS}/pkg/train.py`), 'file:pkg/train.py');
});

test('a focus file outside the analyzed root is refused, not scoped to a .. path', () => {
  assert.equal(focusScopeSpec(WS, 'C:/elsewhere/train.py'), null);
});
