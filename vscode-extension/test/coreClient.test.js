'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { api, readSampleGraph } = require('./harness.js');

const {
  buildAnalyzeArgs,
  classifyExit,
  tailLines,
  scopeKey,
  forwardSlashes,
  Debouncer,
  CoreError,
  MAX_BUFFER_BYTES,
  SAVE_DEBOUNCE_MS,
  looksLikeGraph,
  isSchemaCompatible,
  schemaMajor,
  emptyGraph,
  countIssues
} = api;

test('the analyze argv is exactly the frozen CLI call', () => {
  const args = buildAnalyzeArgs({
    paths: ['C:/repo/samples/vision_pipeline'],
    maxFiles: 500,
    maxNodes: 400,
    exclude: ['**/legacy/**', '  ', '**/notebooks/**']
  });
  assert.deepEqual(args, [
    '-X',
    'utf8',
    '-m',
    'mlview',
    'analyze',
    'C:/repo/samples/vision_pipeline',
    '--json',
    '-',
    '--max-files',
    '500',
    '--max-nodes',
    '400',
    '--exclude',
    '**/legacy/**',
    '--exclude',
    '**/notebooks/**'
  ]);
  // -X utf8 is the Windows/UTF-8 invariant and must lead the argv.
  assert.deepEqual(args.slice(0, 2), ['-X', 'utf8']);
});

test('the html export argv writes a report instead of stdout json', () => {
  const args = buildAnalyzeArgs({
    paths: ['C:/repo'],
    maxFiles: 10,
    maxNodes: 20,
    exclude: [],
    htmlOut: 'C:/repo/report.html'
  });
  assert.ok(args.includes('--html'));
  assert.equal(args[args.indexOf('--html') + 1], 'C:/repo/report.html');
  assert.ok(!args.includes('--json'));
});

test('a scoped export appends --scope (and --depth) and nothing else', () => {
  const base = { paths: ['C:/repo'], maxFiles: 10, maxNodes: 20, exclude: [], htmlOut: 'C:/r.html' };
  const unscoped = buildAnalyzeArgs(base);
  assert.ok(!unscoped.includes('--scope'), 'an unscoped run must be argv-identical to before');
  assert.ok(!unscoped.includes('--depth'));

  const scoped = buildAnalyzeArgs({ ...base, scopeSpec: 'concern:evaluation', depth: 2 });
  assert.deepEqual(scoped.slice(0, unscoped.length), unscoped, 'the projection flags only APPEND');
  assert.deepEqual(scoped.slice(unscoped.length), ['--scope', 'concern:evaluation', '--depth', '2']);

  // Depth is optional: without one the CLI applies the per-kind default (CONTRACTS.md §11.5).
  assert.deepEqual(
    buildAnalyzeArgs({ ...base, scopeSpec: 'unit:train.validate' }).slice(unscoped.length),
    ['--scope', 'unit:train.validate']
  );
  // A blank selector is not a selector.
  assert.deepEqual(buildAnalyzeArgs({ ...base, scopeSpec: '   ' }), unscoped);
  // A depth of 0 is a real value and must survive the falsy check.
  assert.ok(
    buildAnalyzeArgs({ ...base, scopeSpec: 'stage:train', depth: 0 }).join(' ').endsWith('--depth 0')
  );
});

test('exit codes follow CONTRACTS §3', () => {
  assert.equal(classifyExit(0), 'ok');
  assert.equal(classifyExit(1), 'usage');
  assert.equal(classifyExit(2), 'fail-on');
  assert.equal(classifyExit(3), 'internal');
  assert.equal(classifyExit(4), 'nothing-analyzable');
  assert.equal(classifyExit(null), 'unknown');
  assert.equal(classifyExit(9009), 'unknown');
});

test('exit code 4 maps to a schema-valid empty graph, not an error', () => {
  const graph = emptyGraph('C:/repo');
  assert.ok(looksLikeGraph(graph));
  assert.equal(graph.stages.length, 8);
  assert.ok(graph.stages.every((s) => s.present === false));
  assert.deepEqual(graph.stats.issues, { low: 0, medium: 0, high: 0 });
  assert.match(graph.generator.rendererSha, /^0{64}$/);
  assert.match(graph.generator.generatedAt, /^\d{4}-\d{2}-\d{2}T[\d:]+Z$/);
});

test('schema major mismatch detection', () => {
  assert.equal(schemaMajor('1.0'), '1');
  assert.equal(schemaMajor('2.5'), '2');
  assert.equal(isSchemaCompatible('1.0'), true);
  assert.equal(isSchemaCompatible('1.7'), true);
  assert.equal(isSchemaCompatible('2.0'), false);
  assert.equal(isSchemaCompatible(undefined), false);
});

test('a graph document is recognised and rubbish is not', () => {
  assert.ok(looksLikeGraph(readSampleGraph()));
  assert.ok(!looksLikeGraph({ hello: 'world' }));
  assert.ok(!looksLikeGraph(null));
  assert.ok(!looksLikeGraph('{}'));
});

test('stderr tails are trimmed to the last lines', () => {
  const text = ['a', '', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'].join('\r\n');
  assert.equal(tailLines(text, 3), 'h\ni\nj');
  assert.equal(tailLines('', 3), '');
});

test('scope keys keep workspace and per-file runs single-flight', () => {
  assert.equal(scopeKey('workspace'), 'workspace');
  assert.equal(scopeKey('file', 'C:/repo/train.py'), 'file:C:/repo/train.py');
  assert.notEqual(scopeKey('file', 'a.py'), scopeKey('file', 'b.py'));
  assert.equal(forwardSlashes('C:\\repo\\train.py'), 'C:/repo/train.py');
});

test('the save debounce is trailing-edge and 400 ms', async () => {
  assert.equal(SAVE_DEBOUNCE_MS, 400);
  assert.equal(MAX_BUFFER_BYTES, 32 * 1024 * 1024);
  const debouncer = new Debouncer(20);
  let runs = 0;
  debouncer.schedule(() => (runs += 1));
  debouncer.schedule(() => (runs += 1));
  debouncer.schedule(() => (runs += 1));
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.equal(runs, 1, 'a burst of saves collapses to one analysis');
  debouncer.schedule(() => (runs += 1));
  debouncer.cancel();
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(runs, 1);
  debouncer.dispose();
});

test('CoreError carries the remediation actions the webview banner offers', () => {
  const err = new CoreError('interpreter', 'no python', 'details here', [
    { id: 'installCore', label: 'Install MLView core' }
  ]);
  assert.ok(err instanceof Error);
  assert.equal(err.kind, 'interpreter');
  assert.equal(err.detail, 'details here');
  assert.deepEqual(err.actions[0], { id: 'installCore', label: 'Install MLView core' });
});

test('issue counts ignore suppressed findings', () => {
  const graph = readSampleGraph();
  const counts = countIssues(graph.issues);
  const unsuppressed = graph.issues.filter((i) => !i.suppressed);
  assert.equal(
    counts.low + counts.medium + counts.high,
    unsuppressed.length
  );
});
