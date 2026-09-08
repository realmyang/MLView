'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { api, readSampleGraph, syntheticGraph } = require('./harness.js');

const {
  runAnalyzeTool,
  runListIssuesTool,
  runShowDiagramTool,
  DIGEST_LIMIT_BYTES,
  TOOL_ANALYZE,
  TOOL_ISSUES,
  TOOL_DIAGRAM
} = api;

/** The stubbed core: this is the substitute for the untestable Copilot agent-mode path. */
function stubCore(graph, log = []) {
  return {
    calls: log,
    async analyze(input) {
      log.push({ kind: 'analyze', input });
      return graph;
    },
    async showDiagram(focusNodeId) {
      log.push({ kind: 'showDiagram', focusNodeId });
    }
  };
}

test('the tool names match the manifest', () => {
  assert.equal(TOOL_ANALYZE, 'mlview_analyzeWorkspace');
  assert.equal(TOOL_ISSUES, 'mlview_listIssues');
  assert.equal(TOOL_DIAGRAM, 'mlview_showDiagram');
});

test('runAnalyzeTool returns a <=4KB digest of contracts/graph.sample.json', async () => {
  const graph = readSampleGraph();
  const core = stubCore(graph);
  const text = await runAnalyzeTool({}, core);
  assert.ok(Buffer.byteLength(text, 'utf8') <= DIGEST_LIMIT_BYTES, 'the tool result must fit 4 KB');
  assert.match(text, /MLView analyzed 5 file\(s\)/);
  assert.match(text, /torch/);
  assert.match(text, /Stages:/);
  assert.match(text, /\[HIGH\] MLV/);
  assert.match(text, /train\.py:\d+/);
  assert.deepEqual(core.calls, [{ kind: 'analyze', input: {} }]);
});

test('runAnalyzeTool forwards an explicit path', async () => {
  const core = stubCore(readSampleGraph());
  await runAnalyzeTool({ path: 'train.py' }, core);
  assert.deepEqual(core.calls[0].input, { path: 'train.py' });
});

test('runListIssuesTool filters by severity and by rule code', async () => {
  const graph = readSampleGraph();
  const core = stubCore(graph);
  const all = await runListIssuesTool({}, core);
  assert.match(all, /high, /);
  assert.match(all, /fix: /);

  const highOnly = await runListIssuesTool({ minSeverity: 'high' }, core);
  assert.ok(!/\[LOW\]/.test(highOnly), 'low findings must not appear under minSeverity=high');

  const code = graph.issues[0].code;
  const oneCode = await runListIssuesTool({ code }, core);
  const codes = [...oneCode.matchAll(/MLV[0-9]{3}/g)].map((m) => m[0]);
  assert.ok(codes.length > 0);
  assert.ok(codes.every((c) => c === code));
});

test('runListIssuesTool honours host-level disabled rules', async () => {
  const graph = readSampleGraph();
  const code = graph.issues[0].code;
  const text = await runListIssuesTool({}, stubCore(graph), { disabledRules: [code] });
  assert.ok(!text.includes(`] ${code} `), `${code} should have been filtered out`);
});

test('runShowDiagramTool opens the panel and reports the focus node', async () => {
  const core = stubCore(readSampleGraph());
  const text = await runShowDiagramTool({ focusNodeId: 'n:7c1a90b4e2f0' }, core);
  assert.match(text, /diagram panel is open/);
  assert.match(text, /n:7c1a90b4e2f0/);
  assert.deepEqual(core.calls[0], { kind: 'showDiagram', focusNodeId: 'n:7c1a90b4e2f0' });
  assert.ok(Buffer.byteLength(text, 'utf8') <= DIGEST_LIMIT_BYTES);
});

test('runShowDiagramTool works when the host cannot open a panel', async () => {
  const core = { analyze: async () => readSampleGraph() };
  const text = await runShowDiagramTool({}, core);
  assert.match(text, /diagram panel is open/);
});

test('every tool stays inside the 4 KB budget on a 500-node graph', async () => {
  const core = stubCore(syntheticGraph(500, 120));
  for (const run of [
    runAnalyzeTool({}, core),
    runListIssuesTool({}, core),
    runShowDiagramTool({}, core)
  ]) {
    const text = await run;
    assert.ok(
      Buffer.byteLength(text, 'utf8') <= DIGEST_LIMIT_BYTES,
      `tool result was ${Buffer.byteLength(text, 'utf8')} bytes`
    );
  }
});

test('a failing core surfaces the error to the caller rather than a broken payload', async () => {
  const core = {
    async analyze() {
      throw new Error('interpreter missing');
    }
  };
  await assert.rejects(() => runAnalyzeTool({}, core), /interpreter missing/);
});
