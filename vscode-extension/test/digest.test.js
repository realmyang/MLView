'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { api, readSampleGraph, syntheticGraph } = require('./harness.js');

const {
  DIGEST_LIMIT_BYTES,
  buildAnalyzeDigest,
  buildIssuesDigest,
  analyzeDigestToText,
  issuesDigestToText,
  jsonBytes,
  selectIssues,
  emptyGraph
} = api;

test('the analyze digest of a 500-node synthetic graph stays under 4 KB', () => {
  const graph = syntheticGraph(500, 120);
  const digest = buildAnalyzeDigest(graph);
  const size = jsonBytes(digest);
  assert.ok(size <= DIGEST_LIMIT_BYTES, `digest was ${size} bytes`);
  assert.ok(digest.topIssues.length > 0, 'the digest still names the worst findings');
  assert.equal(digest.truncated, true, 'stats.truncated is carried through');
  assert.ok(Buffer.byteLength(analyzeDigestToText(digest), 'utf8') <= DIGEST_LIMIT_BYTES);
});

test('the issues digest of a 500-node synthetic graph stays under 4 KB', () => {
  const graph = syntheticGraph(500, 120);
  const digest = buildIssuesDigest(graph);
  const size = jsonBytes(digest);
  assert.ok(size <= DIGEST_LIMIT_BYTES, `issues digest was ${size} bytes`);
  assert.equal(digest.digestTruncated, true);
  assert.deepEqual(digest.countBySeverity, { low: 40, medium: 40, high: 40 });
  assert.ok(Buffer.byteLength(issuesDigestToText(digest), 'utf8') <= DIGEST_LIMIT_BYTES * 2);
});

test('a pathological single issue is still squeezed under the budget', () => {
  const graph = syntheticGraph(4, 1);
  graph.issues[0].title = 'T'.repeat(6000);
  graph.issues[0].message = 'M'.repeat(6000);
  graph.issues[0].fixHint = 'F'.repeat(6000);
  assert.ok(jsonBytes(buildAnalyzeDigest(graph)) <= DIGEST_LIMIT_BYTES);
  assert.ok(jsonBytes(buildIssuesDigest(graph)) <= DIGEST_LIMIT_BYTES);
});

test('the sample graph digest carries the contract fields', () => {
  const graph = readSampleGraph();
  const digest = buildAnalyzeDigest(graph, { graphPath: '.mlview/graph.json' });
  assert.equal(digest.schemaVersion, '1.0');
  assert.equal(digest.root, graph.workspace.root);
  assert.equal(digest.filesAnalyzed, graph.workspace.filesAnalyzed);
  assert.deepEqual(digest.frameworks, graph.workspace.frameworks);
  assert.equal(digest.graphPath, '.mlview/graph.json');
  assert.ok(digest.lanes.length >= 1);
  for (const lane of digest.lanes) {
    assert.equal(typeof lane.stage, 'string');
    assert.equal(typeof lane.nodeCount, 'number');
  }
  assert.ok(digest.topIssues.length <= 10);
  assert.equal(digest.topIssues[0].severity, 'high', 'highest severity first');
  assert.ok(jsonBytes(digest) <= DIGEST_LIMIT_BYTES);
});

test('issue selection honours severity, confidence, suppression and disabled rules', () => {
  const graph = readSampleGraph();
  const all = selectIssues(graph, {});
  assert.ok(all.length > 0);
  assert.ok(all.every((i) => !i.suppressed));

  const highOnly = selectIssues(graph, { minSeverity: 'high' });
  assert.ok(highOnly.every((i) => i.severity === 'high'));
  assert.ok(highOnly.length < all.length);

  const confident = selectIssues(graph, { minConfidence: 0.95 });
  assert.ok(confident.every((i) => i.confidence >= 0.95));

  const firstCode = all[0].code;
  const withoutFirst = selectIssues(graph, { disabledRules: [firstCode.toLowerCase()] });
  assert.ok(withoutFirst.every((i) => i.code !== firstCode), 'disabledRules is case-insensitive');

  const oneCode = selectIssues(graph, { code: firstCode });
  assert.ok(oneCode.every((i) => i.code === firstCode));
});

test('an empty graph digests to a valid, tiny summary', () => {
  const digest = buildAnalyzeDigest(emptyGraph('C:/repo'));
  assert.equal(digest.stats.nodes, 0);
  assert.deepEqual(digest.topIssues, []);
  assert.match(analyzeDigestToText(digest), /No issues were reported/);
  assert.ok(jsonBytes(digest) <= DIGEST_LIMIT_BYTES);
});
