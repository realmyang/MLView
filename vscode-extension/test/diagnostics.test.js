'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { api, vscode, readSampleGraph } = require('./harness.js');

const {
  mapSeverity,
  toVsSeverity,
  buildDiagnostics,
  resolveRuleDocPath,
  selectIssues,
  publishedIssueFilter,
  buildLocationIndex,
  scopeToSymbol,
  DIAGNOSTIC_SOURCE,
  DIAGNOSTIC_COLLECTION_NAME
} = api;

test('the frozen severity table', () => {
  // mlview.diagnosticSeverity = "warning" (default)
  assert.equal(mapSeverity('high', 'warning'), 'warning');
  assert.equal(mapSeverity('medium', 'warning'), 'warning');
  assert.equal(mapSeverity('low', 'warning'), 'information');
  // = "error" escalates high only
  assert.equal(mapSeverity('high', 'error'), 'error');
  assert.equal(mapSeverity('medium', 'error'), 'warning');
  assert.equal(mapSeverity('low', 'error'), 'information');

  assert.equal(toVsSeverity('error'), vscode.DiagnosticSeverity.Error);
  assert.equal(toVsSeverity('warning'), vscode.DiagnosticSeverity.Warning);
  assert.equal(toVsSeverity('information'), vscode.DiagnosticSeverity.Information);
});

test('diagnostics carry source, code and the frozen severity', () => {
  const graph = readSampleGraph();
  const issues = selectIssues(graph, { minConfidence: 0.6 });
  const byFile = buildDiagnostics(issues, { mode: 'warning' });
  const flat = [...byFile.values()].flat();
  assert.equal(flat.length, issues.length);
  for (const diagnostic of flat) {
    assert.equal(diagnostic.source, DIAGNOSTIC_SOURCE);
    assert.match(String(diagnostic.code), /^MLV[0-9]{3}$/);
    assert.ok([0, 1, 2].includes(diagnostic.severity));
  }
  const high = issues.find((i) => i.severity === 'high');
  const highDiagnostic = byFile.get(high.loc.absFile).find((d) => String(d.code) === high.code);
  assert.equal(highDiagnostic.severity, vscode.DiagnosticSeverity.Warning);

  const escalated = buildDiagnostics([high], { mode: 'error' });
  assert.equal(escalated.get(high.loc.absFile)[0].severity, vscode.DiagnosticSeverity.Error);
});

test('the diagnostic range is the single 1-based -> 0-based conversion', () => {
  const graph = readSampleGraph();
  const issue = graph.issues[0];
  const diagnostic = buildDiagnostics([issue], { mode: 'warning' }).get(issue.loc.absFile)[0];
  assert.equal(diagnostic.range.start.line, issue.loc.line - 1);
  assert.equal(diagnostic.range.start.character, issue.loc.col);
  assert.equal(diagnostic.range.end.line, issue.loc.endLine - 1);
  assert.equal(diagnostic.range.end.character, issue.loc.endCol);
});

test('relatedInformation is built from relatedLocs', () => {
  const graph = readSampleGraph();
  const issue = graph.issues.find((i) => i.relatedLocs.length > 0);
  assert.ok(issue, 'the sample must exercise multi-location findings');
  const diagnostic = buildDiagnostics([issue], { mode: 'warning' }).get(issue.loc.absFile)[0];
  assert.equal(diagnostic.relatedInformation.length, issue.relatedLocs.length);
  issue.relatedLocs.forEach((rel, i) => {
    const related = diagnostic.relatedInformation[i];
    assert.equal(related.location.uri.fsPath, rel.absFile);
    assert.equal(related.location.range.start.line, rel.line - 1);
    assert.equal(related.location.range.start.character, rel.col);
    assert.ok(related.message.length > 0);
    if (rel.message) {
      assert.equal(related.message, rel.message);
    }
  });
});

test('an issue with no relatedLocs has no relatedInformation', () => {
  const graph = readSampleGraph();
  const issue = { ...graph.issues[0], relatedLocs: [] };
  const diagnostic = buildDiagnostics([issue], { mode: 'warning' }).get(issue.loc.absFile)[0];
  assert.equal(diagnostic.relatedInformation, undefined);
});

test('code.target points at a local rule doc when one exists, extension copy first', () => {
  const extensionDocsDir = path.join('C:', 'ext', 'docs', 'rules');
  const repoDocsDir = path.join('C:', 'repo', 'docs', 'rules');
  const inExtension = path.join(extensionDocsDir, 'MLV201.md');
  const inRepo = path.join(repoDocsDir, 'MLV201.md');

  assert.equal(
    resolveRuleDocPath('MLV201', { extensionDocsDir, repoDocsDir, exists: (p) => p === inExtension }),
    inExtension
  );
  assert.equal(
    resolveRuleDocPath('MLV201', { extensionDocsDir, repoDocsDir, exists: (p) => p === inRepo }),
    inRepo
  );
  assert.equal(
    resolveRuleDocPath('MLV999', { extensionDocsDir, repoDocsDir, exists: () => false }),
    undefined
  );
  assert.equal(
    resolveRuleDocPath('MLV201', {
      extensionDocsDir,
      repoDocsDir,
      exists: () => {
        throw new Error('unreadable');
      }
    }),
    undefined
  );
});

test('a resolved rule doc becomes a { value, target } code, otherwise a plain string', () => {
  const graph = readSampleGraph();
  const issue = graph.issues[0];
  const withDoc = buildDiagnostics([issue], {
    mode: 'warning',
    ruleDocs: { extensionDocsDir: path.join('C:', 'ext', 'docs', 'rules'), exists: () => true }
  }).get(issue.loc.absFile)[0];
  assert.equal(withDoc.code.value, issue.code);
  assert.equal(withDoc.code.target.scheme, 'file');
  assert.ok(String(withDoc.code.target.fsPath).endsWith(`${issue.code}.md`));

  const withoutDoc = buildDiagnostics([issue], {
    mode: 'warning',
    ruleDocs: { extensionDocsDir: path.join('C:', 'ext', 'docs', 'rules'), exists: () => false }
  }).get(issue.loc.absFile)[0];
  assert.equal(withoutDoc.code, issue.code);
});

test('suppressed and low-confidence findings never reach the Problems panel', () => {
  const graph = readSampleGraph();
  graph.issues = graph.issues.map((issue, i) => ({
    ...issue,
    suppressed: i === 0,
    confidence: i === 1 ? 0.4 : 0.9
  }));
  const published = selectIssues(graph, { minConfidence: 0.6 });
  assert.ok(published.every((i) => !i.suppressed));
  assert.ok(published.every((i) => i.confidence >= 0.6));
  assert.equal(published.length, graph.issues.length - 2);
});

test('diagnostics are grouped per file so a file dropping to zero can be cleared', () => {
  const graph = readSampleGraph();
  const byFile = buildDiagnostics(selectIssues(graph, {}), { mode: 'warning' });
  const files = new Set(graph.issues.filter((i) => !i.suppressed).map((i) => i.loc.absFile));
  assert.deepEqual(new Set(byFile.keys()), files);
  assert.equal(DIAGNOSTIC_COLLECTION_NAME, 'mlview');
});

// ---------------------------------------------------------------- F2-A11 (CONTRACTS §11.11)

/**
 * A scope is a VIEW. It must never quietly reduce the number of defects a developer is told
 * about, so the Problems panel, the status-bar count and the issue quick pick all keep reading
 * the full graph. These two cases are the guard: the publisher's output is byte-identical
 * across a scope command, and `src/diagnostics.ts` itself is untouched by this change.
 */

const FIXTURE_GRAPH = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'fixtures', 'vision_pipeline.graph.json'), 'utf8')
);

const SETTINGS = {
  minSeverity: 'low',
  minConfidence: 0.6,
  disabledRules: [],
  diagnosticSeverity: 'warning'
};

/** Exactly what `DiagnosticsPublisher.publish` puts into the collection, as bytes. */
function publishedBytes(graph) {
  const byFile = buildDiagnostics(selectIssues(graph, publishedIssueFilter(SETTINGS)), {
    mode: SETTINGS.diagnosticSeverity
  });
  return JSON.stringify(
    [...byFile.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([file, diagnostics]) => [
        file,
        diagnostics.map((d) => ({
          range: d.range,
          message: d.message,
          severity: d.severity,
          source: d.source,
          code: typeof d.code === 'object' && d.code ? d.code.value : d.code,
          related: (d.relatedInformation ?? []).map((r) => [r.location.uri.fsPath, r.message])
        }))
      ])
  );
}

test('F2-A11: setting a scope and re-rendering leaves the publisher output byte-identical', async () => {
  const before = publishedBytes(FIXTURE_GRAPH);

  // The whole host side of a scope: resolve the cursor, post one `setScope`. Nothing else.
  const posted = [];
  const panel = {
    postSetScope(spec) {
      posted.push(spec);
    }
  };
  vscode.window.activeTextEditor = {
    document: {
      uri: vscode.Uri.file(`${FIXTURE_GRAPH.workspace.root}/train.py`),
      languageId: 'python'
    },
    selection: { active: { line: 43, character: 0 } }
  };
  try {
    await scopeToSymbol({
      log: { trace() {}, debug() {}, info() {}, warn() {}, error() {} },
      getGraph: () => FIXTURE_GRAPH,
      getIndex: () => buildLocationIndex(FIXTURE_GRAPH),
      ensurePanel: async () => panel,
      ensureGraph: async () => FIXTURE_GRAPH
    });
  } finally {
    vscode.window.activeTextEditor = undefined;
  }
  assert.deepEqual(posted, ['unit:train.validate'], 'the scope really was applied');

  // Re-render with the graph the host still holds - the FULL one, exactly as before.
  assert.equal(publishedBytes(FIXTURE_GRAPH), before);

  // ...and the assertion has teeth: a publisher fed the PROJECTION would say something else.
  const projected = {
    ...FIXTURE_GRAPH,
    issues: FIXTURE_GRAPH.issues.filter(
      (i) => i.loc.file === 'train.py' && i.loc.line >= 41 && i.loc.line <= 49
    )
  };
  assert.ok(projected.issues.length > 0 && projected.issues.length < FIXTURE_GRAPH.issues.length);
  assert.notEqual(publishedBytes(projected), before);
});

test('F2-A11: diagnostics.ts, chat.ts and lmTools.ts have no diff in this change', () => {
  const snapshot = path.join(__dirname, '..', '..', '.workflows', 'backup', 'pre-features');
  if (!fs.existsSync(snapshot)) {
    return; // a packaged tree has no pre-feature snapshot to compare against
  }
  // CONTRACTS.md 11.11: a scope never changes the Problems panel, the status-bar count or the
  // issue quick pick, and prose-to-scope resolution is cut for v1.
  for (const name of ['diagnostics.ts', 'chat.ts', 'lmTools.ts']) {
    assert.deepEqual(
      fs.readFileSync(path.join(__dirname, '..', 'src', name)),
      fs.readFileSync(path.join(snapshot, 'vscode-extension', 'src', name)),
      `src/${name} is frozen for this feature and has drifted`
    );
  }
});
