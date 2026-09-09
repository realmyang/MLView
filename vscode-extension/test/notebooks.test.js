'use strict';
/**
 * NB — the host half of notebook analysis.
 *
 * Four things have to be true for a notebook finding to be worth anything in VS Code:
 *
 *   1. the analyzer has to be ASKED for it (`mlview.includeNotebooks` -> `--include-notebooks`),
 *      and the argv has to be byte-identical when it is not asked for;
 *   2. the squiggle has to land in the CELL the user is looking at. The analyzer's `Loc` names
 *      the generated module it materialised under `.mlview/notebooks/`, because `Loc` is
 *      frozen and cannot hold a cell index; the cell mapping rides in one `context_confirmed`
 *      evidence row per finding, and re-anchoring it onto a `vscode-notebook-cell:` uri is
 *      exactly the host's job;
 *   3. saving the notebook has to re-analyze it, which is a DIFFERENT event from saving a text
 *      document and fires for nothing else;
 *   4. the status bar has to be able to say "analyzed" and "not analyzed" and tell them apart.
 *
 * The evidence row is a parsed contract, so the first test in section 2 asserts its format
 * against `analyzer/src/mlview/rules/confidence.py` itself — the same discipline
 * `progress.test.js` uses for `--progress-json`, so a rename on either side reddens here.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api, vscode, readSampleGraph, REPO_ROOT } = require('./harness.js');

const {
  buildAnalyzeArgs,
  buildDiagnostics,
  DEFAULT_SETTINGS,
  readSettings,
  isNotebookPath,
  notebookForShadow,
  cellRefFromEvidence,
  cellRefFor,
  findNotebook,
  cellAtIndex,
  resolveNotebookTarget,
  notebookCounts,
  notebookTooltipFragment,
  analyzedAnyNotebook,
  openNotebooks,
  cellRangeFor,
  statusBarTooltip,
  reactToTextSave,
  reactToNotebookSave,
  reactToConfigChange,
  registerWatchers,
  REANALYZE_KEYS,
  buildAnalyzeDigest,
  analyzeDigestToText,
  NOTEBOOK_EXTENSION,
  NOTEBOOK_ANALYZED_KIND,
  SHADOW_DIR,
  NO_NOTEBOOKS
} = api;

const ROOT = '/ws';
const NB = '/ws/leak.ipynb';
const SHADOW = '.mlview/notebooks/leak.py';
const ORDER_OK = 'execution_count [1, 2, 3] is monotonic, so document order was the last run order';

/** The notebook the whole file works against: markdown, code, code, code — as the analyzer sees it. */
function openLeakNotebook() {
  return vscode.__setNotebooks([
    {
      path: NB,
      cells: [
        { kind: vscode.NotebookCellKind.Markup, lines: 1 },
        { kind: vscode.NotebookCellKind.Code, lines: 3 },
        { kind: vscode.NotebookCellKind.Code, lines: 4 },
        { kind: vscode.NotebookCellKind.Code, lines: 3 }
      ]
    }
  ])[0];
}

/** One `context_confirmed` row, spelled exactly as `notebook_evidence` spells it. */
function cellEvidence(cell, line, tail = ORDER_OK) {
  return {
    kind: 'context_confirmed',
    detail: `leak.ipynb cell ${cell}, line ${line}; ${tail}`,
    weight: 1
  };
}

function loc(over = {}) {
  return {
    file: SHADOW,
    absFile: `${ROOT}/${SHADOW}`,
    line: 17,
    col: 5,
    endLine: 17,
    endCol: 28,
    ...over
  };
}

function issue(over = {}) {
  return {
    id: 'i:0',
    code: 'MLV101',
    title: 'Preprocessing fitted before the train/test split',
    message: 'the scaler was fitted on everything',
    fixHint: 'split first',
    severity: 'high',
    confidence: 0.9,
    confidenceBucket: 'certain',
    loc: loc(),
    relatedLocs: [],
    nodeIds: [],
    edgeIds: [],
    stage: 'preprocess',
    frameworks: ['sklearn'],
    tags: ['correctness'],
    evidence: [cellEvidence(3, 2)],
    suppressed: false,
    docs: 'docs/rules/MLV101.md',
    ...over
  };
}

const KEY = (uri) => uri.toString();
const DIAGNOSTICS = { mode: 'warning', root: ROOT };

test.afterEach(() => {
  vscode.__reset();
});

// ------------------------------------------------------------------ 1. asking for it

test('the default argv is byte-identical: no --include-notebooks unless asked', () => {
  const base = { paths: ['C:/ws'], maxFiles: 500, maxNodes: 400, exclude: [] };
  const quiet = buildAnalyzeArgs(base);
  assert.ok(!quiet.includes('--include-notebooks'));
  assert.deepEqual(buildAnalyzeArgs({ ...base, includeNotebooks: false }), quiet);

  const loud = buildAnalyzeArgs({ ...base, includeNotebooks: true });
  assert.deepEqual(loud.slice(0, quiet.length), quiet, 'the flag is appended, never inserted');
  assert.deepEqual(loud.slice(quiet.length), ['--include-notebooks']);
});

test('the flag the extension passes is the flag the analyzer parses', () => {
  const parser = fs.readFileSync(
    path.join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'cli_parser.py'),
    'utf8'
  );
  assert.ok(
    parser.includes('--include-notebooks'),
    'analyzer/src/mlview/cli_parser.py must accept the flag the extension sends'
  );
});

test('the flag sits with the ingest flags, ahead of the projection flags', () => {
  const args = buildAnalyzeArgs({
    paths: ['C:/ws'],
    maxFiles: 500,
    maxNodes: 400,
    exclude: ['**/vendor/**'],
    includeNotebooks: true,
    scopeSpec: 'stage:train',
    depth: 0
  });
  assert.ok(args.indexOf('--exclude') < args.indexOf('--include-notebooks'));
  assert.ok(args.indexOf('--include-notebooks') < args.indexOf('--scope'));
});

test('mlview.includeNotebooks defaults to false and is read like every other setting', () => {
  assert.equal(DEFAULT_SETTINGS.includeNotebooks, false);
  assert.equal(readSettings().includeNotebooks, false);
  vscode.__setConfig('mlview', 'includeNotebooks', true);
  assert.equal(readSettings().includeNotebooks, true);
  // An absent value falls back to the default, exactly as every other mlview.* boolean does
  // (VS Code type-checks a contributed `"type": "boolean"` before it ever reaches us).
  vscode.__setConfig('mlview', 'includeNotebooks', undefined);
  assert.equal(readSettings().includeNotebooks, false);
});

// -------------------------------------------------------- 2. the squiggle lands in the cell

test('the evidence format this host parses is the one the analyzer writes', () => {
  const source = fs.readFileSync(
    path.join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'rules', 'confidence.py'),
    'utf8'
  );
  assert.ok(
    source.includes('"%s cell %d, line %d"'),
    'rules/confidence.notebook_evidence must still write "<nb> cell <N>, line <M>"'
  );
  assert.ok(
    source.includes('(generated module line %d, outside any cell)'),
    'the no-cell form must still be spelled the way this host recognises it'
  );
  assert.ok(source.includes('ORDER_SENSITIVE_CODES'), 'the de-rating hook must still exist');
});

test('a .ipynb path and a generated module are both recognised for what they are', () => {
  assert.equal(NOTEBOOK_EXTENSION, '.ipynb');
  assert.equal(SHADOW_DIR, '.mlview/notebooks');
  assert.ok(isNotebookPath('/ws/a.ipynb'));
  assert.ok(isNotebookPath('/ws/A.IPYNB'));
  assert.ok(!isNotebookPath('/ws/a.py'));

  assert.equal(notebookForShadow(SHADOW), 'leak.ipynb');
  assert.equal(notebookForShadow('.mlview/notebooks/nb/deep/leak.py'), 'nb/deep/leak.ipynb');
  assert.equal(notebookForShadow('.mlview\\notebooks\\leak.py'), 'leak.ipynb');
  assert.equal(notebookForShadow('src/train.py'), undefined);
  assert.equal(notebookForShadow('.mlview/cache/x.json'), undefined);
});

test('the cell mapping is read out of the evidence, and refuses to be invented', () => {
  assert.deepEqual(cellRefFromEvidence([cellEvidence(3, 2)]), {
    notebook: 'leak.ipynb',
    cell: 3,
    cellLine: 2
  });
  // A path with spaces and directories still parses; the row is anchored at the notebook.
  assert.deepEqual(
    cellRefFromEvidence([
      { kind: 'context_confirmed', detail: 'nb/my work/leak.ipynb cell 0, line 9; ' + ORDER_OK }
    ]),
    { notebook: 'nb/my work/leak.ipynb', cell: 0, cellLine: 9 }
  );
  // The module header and the `# %%` markers belong to no cell, and none is guessed at.
  assert.deepEqual(
    cellRefFromEvidence([
      {
        kind: 'context_confirmed',
        detail: 'leak.ipynb (generated module line 3, outside any cell); ' + ORDER_OK
      }
    ]),
    { notebook: 'leak.ipynb' }
  );
  assert.equal(cellRefFromEvidence([]), undefined);
  assert.equal(cellRefFromEvidence(undefined), undefined);
  assert.equal(
    cellRefFromEvidence([{ kind: 'fqn_resolved', detail: 'resolved through the import table' }]),
    undefined
  );

  // With no evidence at all the generated module still names its notebook.
  assert.deepEqual(cellRefFor({ file: SHADOW }, []), { notebook: 'leak.ipynb' });
  assert.equal(cellRefFor({ file: 'src/train.py' }, []), undefined);
});

test('cell coordinates convert exactly once, and the span survives the move', () => {
  const range = cellRangeFor({ line: 17, col: 5, endLine: 19, endCol: 28 }, 2);
  assert.equal(range.startLine, 1, '1-based cellLine 2 -> 0-based editor line 1');
  assert.equal(range.endLine, 3, 'the 2-line span is preserved');
  assert.equal(range.startChar, 5);
  assert.equal(range.endChar, 28);
});

test('a finding in a notebook is published on the cell uri, not on the generated module', () => {
  const notebook = openLeakNotebook();
  const target = resolveNotebookTarget(issue(), { root: ROOT, notebooks: openNotebooks() });
  assert.equal(target.level, 'cell');
  assert.equal(target.uri.scheme, 'vscode-notebook-cell');
  assert.equal(target.uri.toString(), notebook.getCells()[3].document.uri.toString());
  assert.equal(target.range.startLine, 1, 'cell line 2');
  assert.equal(target.notebookFile, path.resolve(ROOT, 'leak.ipynb'));
});

test('the cell index counts markdown cells too, exactly as the notebook does', () => {
  const notebook = openLeakNotebook();
  const cells = notebook.getCells();
  // Cell 1 is the FIRST code cell but the SECOND cell; the analyzer numbers all of them.
  assert.equal(cellAtIndex(notebook, 1).document.uri.toString(), cells[1].document.uri.toString());
  assert.equal(cellAtIndex(notebook, 3).document.uri.toString(), cells[3].document.uri.toString());
  // An index that has gone stale onto a markdown cell is re-read as a code-cell ordinal
  // rather than squiggling prose.
  assert.equal(cellAtIndex(notebook, 0).document.uri.toString(), cells[1].document.uri.toString());
});

test('a range past the end of its cell is clamped, never dropped', () => {
  openLeakNotebook();
  // Cell 1 has 3 lines; a cellLine of 40 means the notebook changed under us, and the
  // squiggle still lands in the right cell rather than being refused by VS Code.
  const target = resolveNotebookTarget(
    issue({ evidence: [cellEvidence(1, 40)], loc: loc({ line: 40, endLine: 42 }) }),
    { root: ROOT, notebooks: openNotebooks() }
  );
  assert.equal(target.level, 'cell');
  assert.equal(target.range.startLine, 2);
  assert.equal(target.range.endLine, 2);
});

test('with the notebook closed, or with no cell known, it degrades one honest step', () => {
  // Nothing open: the cell uris do not exist, so the .ipynb is the best answer there is.
  const closed = resolveNotebookTarget(issue(), { root: ROOT, notebooks: openNotebooks() });
  assert.equal(closed.level, 'notebook');
  assert.equal(closed.uri.scheme, 'file');
  assert.equal(closed.uri.fsPath, path.resolve(ROOT, 'leak.ipynb'));

  // Open, but the finding is outside any cell: the notebook, and no invented cell.
  openLeakNotebook();
  const outside = resolveNotebookTarget(
    issue({
      evidence: [
        { kind: 'context_confirmed', detail: 'leak.ipynb (generated module line 3, outside any cell)' }
      ]
    }),
    { root: ROOT, notebooks: openNotebooks() }
  );
  assert.equal(outside.level, 'notebook');
  assert.equal(outside.uri.fsPath, path.resolve(ROOT, 'leak.ipynb'));

  // Ordinary Python is not this module's business at all.
  assert.equal(
    resolveNotebookTarget(
      { loc: { ...loc(), file: 'src/train.py', absFile: '/ws/src/train.py' }, evidence: [] },
      { root: ROOT, notebooks: openNotebooks() }
    ),
    undefined
  );
});

test('the open notebook is matched by path, case-insensitively as a fallback', () => {
  const notebook = openLeakNotebook();
  assert.equal(findNotebook(NB, openNotebooks()), notebook);
  assert.equal(findNotebook('/WS/LEAK.IPYNB', openNotebooks()), notebook);
  assert.equal(findNotebook('/ws/other.ipynb', openNotebooks()), undefined);
  assert.deepEqual(openNotebooks(), [notebook]);
});

test('two findings in two cells become two Problems entries, one per cell', () => {
  const notebook = openLeakNotebook();
  const cells = notebook.getCells();
  const byTarget = buildDiagnostics(
    [
      issue({ id: 'i:0', code: 'MLV601', evidence: [cellEvidence(2, 1)], loc: loc({ line: 10 }) }),
      issue({ id: 'i:1', code: 'MLV101', evidence: [cellEvidence(3, 2)] })
    ],
    DIAGNOSTICS
  );
  assert.equal(byTarget.size, 2, 'one entry per CELL, not one per notebook and not one per file');
  const second = byTarget.get(KEY(cells[2].document.uri));
  const third = byTarget.get(KEY(cells[3].document.uri));
  assert.equal(second.diagnostics.length, 1);
  assert.equal(third.diagnostics.length, 1);
  assert.equal(second.diagnostics[0].range.start.line, 0);
  assert.equal(third.diagnostics[0].range.start.line, 1);
  assert.equal(String(third.diagnostics[0].code), 'MLV101');
  // Nothing was published on the generated module the user never wrote.
  assert.ok(!byTarget.has(KEY(vscode.Uri.file(`${ROOT}/${SHADOW}`))));
});

test('a related location keeps the generated module, which is a file that really slices', () => {
  const notebook = openLeakNotebook();
  const byTarget = buildDiagnostics(
    [
      issue({
        relatedLocs: [
          { ...loc({ line: 18, endLine: 18 }), role: 'split_site', message: 'the split is here' }
        ]
      })
    ],
    DIAGNOSTICS
  );
  const diagnostic = byTarget.get(KEY(notebook.getCells()[3].document.uri)).diagnostics[0];
  const related = diagnostic.relatedInformation[0];
  assert.equal(related.location.uri.fsPath, `${ROOT}/${SHADOW}`);
  assert.equal(related.location.range.start.line, 17, 'the flat line of the generated module');
  assert.equal(related.message, 'the split is here');
});

test('a .py finding is untouched by any of this', () => {
  openLeakNotebook();
  const py = issue({
    evidence: [{ kind: 'fqn_resolved', detail: 'sklearn.model_selection.train_test_split' }],
    loc: { ...loc(), file: 'src/train.py', absFile: '/ws/src/train.py' }
  });
  const entry = buildDiagnostics([py], DIAGNOSTICS).get(KEY(vscode.Uri.file('/ws/src/train.py')));
  assert.ok(entry, 'a .py path keeps its own file uri');
  assert.equal(entry.diagnostics[0].range.start.line, 16, 'the flat line, as always');
});

test('with no root there is nothing to resolve against, and nothing is guessed', () => {
  openLeakNotebook();
  const entry = buildDiagnostics([issue()], { mode: 'warning' });
  assert.equal([...entry.values()][0].uri.scheme, 'file');
  assert.equal([...entry.values()][0].uri.fsPath, `${ROOT}/${SHADOW}`);
});

test('the notebooks the builder uses default to the open ones and can be injected', () => {
  openLeakNotebook();
  const fromWindow = buildDiagnostics([issue()], DIAGNOSTICS);
  assert.equal([...fromWindow.values()][0].uri.scheme, 'vscode-notebook-cell');
  const injectedEmpty = buildDiagnostics([issue()], { ...DIAGNOSTICS, notebooks: [] });
  assert.equal([...injectedEmpty.values()][0].uri.scheme, 'file');
  assert.match([...injectedEmpty.values()][0].uri.fsPath, /leak\.ipynb$/);
});

// ------------------------------------------------------------------- 3. saving a notebook

test('saving a notebook re-analyzes only when the analyzer will actually read it', () => {
  const off = { ...DEFAULT_SETTINGS, includeNotebooks: false, analyzeOnSave: true };
  const on = { ...DEFAULT_SETTINGS, includeNotebooks: true, analyzeOnSave: true };
  const onQuiet = { ...DEFAULT_SETTINGS, includeNotebooks: true, analyzeOnSave: false };
  assert.equal(reactToNotebookSave(off), 'ignore');
  assert.equal(reactToNotebookSave(on), 'reanalyze');
  assert.equal(reactToNotebookSave(onQuiet), 'stale-only');
  // The text half is unchanged by any of this.
  assert.equal(reactToTextSave('python', on), 'reanalyze');
  assert.equal(reactToTextSave('python', { ...on, analyzeOnSave: false }), 'stale-only');
  assert.equal(reactToTextSave('markdown', on), 'ignore');
  assert.equal(reactToTextSave('json', off), 'ignore');
});

test('the notebook save event is registered, and it is not the text save event', () => {
  const calls = [];
  const host = {
    settingsFor: () => ({ ...DEFAULT_SETTINGS, includeNotebooks: true }),
    markStale: (p) => calls.push(['stale', p]),
    reanalyze: () => calls.push(['reanalyze']),
    refreshCodeLens: () => calls.push(['codeLens']),
    republish: () => calls.push(['republish']),
    resetForWorkspaceChange: () => calls.push(['reset'])
  };
  const disposables = registerWatchers(host);
  assert.equal(disposables.length, 5);
  assert.equal(vscode.__recorded.notebookSaveListeners.length, 1);
  assert.equal(vscode.__recorded.saveListeners.length, 1);

  vscode.__recorded.notebookSaveListeners[0]({ uri: vscode.Uri.file(NB) });
  assert.deepEqual(calls, [['stale', NB], ['reanalyze']]);

  // A saved text document does NOT go down the notebook path, and vice versa.
  calls.length = 0;
  vscode.__recorded.saveListeners[0]({ uri: vscode.Uri.file('/ws/train.py'), languageId: 'python' });
  assert.deepEqual(calls, [['stale', '/ws/train.py'], ['reanalyze']]);
  for (const d of disposables) {
    d.dispose();
  }
});

test('flipping mlview.includeNotebooks re-runs the analyzer instead of re-filtering', () => {
  assert.deepEqual([...REANALYZE_KEYS], ['mlview.includeNotebooks']);
  const flip = reactToConfigChange((key) => key === 'mlview.includeNotebooks');
  assert.deepEqual(flip, { refreshCodeLens: false, reanalyze: true, republish: false });
  // The filter settings still only re-publish: they cannot change what the analyzer saw.
  const filter = reactToConfigChange((key) => key === 'mlview.minSeverity');
  assert.deepEqual(filter, { refreshCodeLens: false, reanalyze: false, republish: true });
});

// ------------------------------------------------------------ 4. the honest count, both ways

function graphWithNotebooks(analyzed, skipped) {
  const graph = readSampleGraph();
  graph.workspace.notebooksSkipped = skipped;
  graph.diagnostics = [
    { kind: 'parse_error', message: 'bad.py: invalid syntax' },
    ...Array.from({ length: analyzed }, (_, i) => ({
      kind: NOTEBOOK_ANALYZED_KIND,
      message: `nb${i}.ipynb: 3 of 4 cell(s) are code and were analyzed`,
      file: `nb${i}.ipynb`,
      count: 3
    }))
  ];
  return graph;
}

test('analyzed notebooks are COUNTED from the diagnostics, never from their cell counts', () => {
  assert.deepEqual(notebookCounts(undefined), NO_NOTEBOOKS);
  // One notebook whose `count` is 3 CODE CELLS must not be reported as 3 notebooks.
  assert.deepEqual(notebookCounts(graphWithNotebooks(1, 0)), { analyzed: 1, skipped: 0 });
  assert.deepEqual(notebookCounts(graphWithNotebooks(2, 1)), { analyzed: 2, skipped: 1 });
  // A core that never heard of notebooks reports 0 analyzed rather than undefined.
  assert.deepEqual(notebookCounts({ workspace: { notebooksSkipped: 2 } }), {
    analyzed: 0,
    skipped: 2
  });
  assert.equal(analyzedAnyNotebook(graphWithNotebooks(1, 0)), true);
  assert.equal(analyzedAnyNotebook(graphWithNotebooks(0, 2)), false);
});

test('the tooltip distinguishes analyzed from not analyzed, and can say both', () => {
  assert.equal(notebookTooltipFragment(NO_NOTEBOOKS), '');
  assert.equal(notebookTooltipFragment({ analyzed: 3, skipped: 0 }), ' · 3 notebooks analyzed');
  assert.equal(notebookTooltipFragment({ analyzed: 0, skipped: 2 }), ' · 2 notebooks not analyzed');
  assert.equal(
    notebookTooltipFragment({ analyzed: 3, skipped: 1 }),
    ' · 3 notebooks analyzed, 1 notebooks not analyzed'
  );

  const counts = { low: 0, medium: 0, high: 1 };
  assert.equal(
    statusBarTooltip(counts, false, false, { analyzed: 1, skipped: 0 }, []),
    'MLView: 1 high, 0 medium, 0 low · 1 notebooks analyzed'
  );
  assert.equal(
    statusBarTooltip(counts, false, false, { analyzed: 0, skipped: 1 }, []),
    'MLView: 1 high, 0 medium, 0 low · 1 notebooks not analyzed'
  );
});

test('the model is told the notebooks were read AND that their order is unknowable', () => {
  const digest = buildAnalyzeDigest(graphWithNotebooks(2, 0));
  assert.equal(digest.notebooksAnalyzed, 2);
  const text = analyzeDigestToText(digest);
  assert.match(text, /2 notebook\(s\) were analyzed/);
  assert.match(text, /execution order/);
  assert.ok(!text.includes('detected but not analyzed'));

  const none = buildAnalyzeDigest(graphWithNotebooks(0, 0));
  assert.equal(none.notebooksAnalyzed, 0);
  assert.ok(!analyzeDigestToText(none).includes('were analyzed'));
});
