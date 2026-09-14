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
    async showDiagram(focusNodeId, scopeSpec) {
      // H10: the second argument is the §11.1 selector the panel is opened AT.
      log.push({ kind: 'showDiagram', focusNodeId, ...(scopeSpec ? { scopeSpec } : {}) });
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

// --------------------------------------------------------------------------- H10 (11.40)
//
// `scope` and `depth` on the three tools. CONTRACTS 11.11 cut them for v1, which left the two
// hosts describing DIFFERENT products: the MCP tools take the whole §11.1 grammar while Copilot
// agent mode could not ask about `concern:evaluation`. The flags were already built by
// `buildAnalyzeArgs({scopeSpec, depth})` and reached only from `exportHtml`.

const fs = require('node:fs');
const path = require('node:path');
const { scopeArgs, scopeNote } = api;
const { REPO_ROOT } = require('./harness.js');

const MANIFEST = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
);
const MCP_SERVER = path.join(REPO_ROOT, 'claude-plugin', 'server', 'mlview_mcp.py');

/** Whitespace-normalized, so a docstring's wrapping is not a difference in wording. */
const flat = (text) => text.replace(/\s+/g, ' ').trim();

test('scopeArgs keeps a real selector and drops a depth no host could act on', () => {
  assert.deepEqual(scopeArgs({}), {});
  assert.deepEqual(scopeArgs({ scope: '   ' }), {});
  // A depth without a scope means nothing; the CLI ignores it and so do we.
  assert.deepEqual(scopeArgs({ depth: 2 }), {});
  assert.deepEqual(scopeArgs({ scope: ' concern:evaluation ' }), {
    scopeSpec: 'concern:evaluation'
  });
  assert.deepEqual(scopeArgs({ scope: 'unit:train', depth: 2 }), {
    scopeSpec: 'unit:train',
    depth: 2
  });
  // A model that invents `depth: 5` or sends a string gets the per-kind default rather than a
  // refusal it cannot act on. An invented SCOPE is a refusal - that one changes the answer.
  for (const bad of [5, -1, 1.5, '2', null]) {
    assert.deepEqual(scopeArgs({ scope: 'unit:train', depth: bad }), { scopeSpec: 'unit:train' });
  }
});

test('a scoped answer says it is a filtered view before it says anything else', async () => {
  const graph = readSampleGraph();
  const core = stubCore(graph);
  const text = await runAnalyzeTool({ scope: 'concern:evaluation', depth: 0 }, core);
  assert.deepEqual(core.calls[0].input, { scopeSpec: 'concern:evaluation', depth: 0 });
  assert.match(text, /^This is a filtered view of concern:evaluation at depth 0/);
  assert.match(text, /counts below describe that scope, not the whole project/);
  assert.match(text, /Re-run without a scope for the project-wide numbers/);
  assert.ok(Buffer.byteLength(text, 'utf8') <= DIGEST_LIMIT_BYTES);
});

test('an unscoped answer is byte-identical to the one before scopes existed', async () => {
  const core = stubCore(readSampleGraph());
  const text = await runAnalyzeTool({}, core);
  assert.equal(scopeNote({}), '');
  assert.ok(!text.startsWith('This is a filtered view'));
  assert.deepEqual(core.calls[0].input, {});
});

test('listIssues forwards the scope and keeps its own filters', async () => {
  const graph = readSampleGraph();
  const core = stubCore(graph);
  const text = await runListIssuesTool(
    { scope: 'stage:train', depth: 1, minSeverity: 'high' },
    core
  );
  assert.deepEqual(core.calls[0].input, { scopeSpec: 'stage:train', depth: 1 });
  assert.match(text, /filtered view of stage:train at depth 1/);
  assert.ok(!/\[LOW\]/.test(text), 'minSeverity still applies inside a scope');
});

test('showDiagram opens the panel AT the scope, through the same setScope path a keystroke uses', async () => {
  const core = stubCore(readSampleGraph());
  const text = await runShowDiagramTool({ scope: 'unit:train.train', focusNodeId: 'n:1' }, core);
  assert.deepEqual(core.calls[0], {
    kind: 'showDiagram',
    focusNodeId: 'n:1',
    scopeSpec: 'unit:train.train'
  });
  assert.match(text, /Narrowed to unit:train\.train/);
  assert.match(text, /widen or clear the scope in the diagram's own toolbar/);
  assert.ok(Buffer.byteLength(text, 'utf8') <= DIGEST_LIMIT_BYTES);
});

test('every tool declares scope and depth, with depth bounded at 0..2', () => {
  const tools = MANIFEST.contributes.languageModelTools;
  assert.equal(tools.length, 3);
  for (const tool of tools) {
    const props = tool.inputSchema.properties;
    assert.ok(props.scope, `${tool.name} must accept a scope`);
    assert.equal(props.scope.type, 'string');
    assert.ok(props.scope.description.length > 400, 'the grammar has to be spelled out');
    assert.equal(props.depth.type, 'integer');
    assert.equal(props.depth.minimum, 0);
    assert.equal(props.depth.maximum, 2);
  }
});

test('the LM tools and the MCP tools describe ONE selector grammar, word for word', () => {
  // 11.40's whole justification is that two hosts were describing different products. This is
  // the gate: the shared entries of `mlview_graph`'s `scope:` docstring must appear verbatim
  // (modulo wrapping) in the extension's schema, so the two can never drift apart again.
  if (!fs.existsSync(MCP_SERVER)) {
    return; // an extension-only checkout has no plugin to compare against
  }
  const source = fs.readFileSync(MCP_SERVER, 'utf8');
  const start = source.indexOf('scope: omit for the whole graph, or pass one of --');
  assert.ok(start > 0, 'the MCP docstring must still carry the selector grammar');
  const block = source.slice(start, source.indexOf('depth: 0, 1 or 2 boundary hops', start));

  const entries = new Map();
  let current = null;
  for (const line of block.split('\n').slice(1)) {
    const text = line.trim();
    if (!text) {
      continue;
    }
    if (text.startsWith('"')) {
      current = text.slice(0, text.indexOf('"', 1) + 1);
      entries.set(current, text);
    } else if (current) {
      entries.set(current, `${entries.get(current)} ${text}`);
    }
  }

  const description = flat(
    MANIFEST.contributes.languageModelTools[0].inputSchema.properties.scope.description
  );
  // The seven the CLI actually accepts (`--scope stages` is a `bad_selector` refusal).
  for (const key of [
    '"all"',
    '"stage:<id>"',
    '"unit:<name>"',
    '"file:<path.py>"',
    '"concern:<name>"',
    '"node:<nodeId>"',
    '"symbol:<name>"'
  ]) {
    const entry = entries.get(key);
    assert.ok(entry, `the MCP docstring must still document ${key}`);
    assert.ok(
      description.includes(flat(entry)),
      `${key} differs between the two hosts:\n  MCP: ${flat(entry)}\n  LM : ${description}`
    );
  }
  // And the two MCP-only listing payloads must NOT be advertised here: they are not
  // projections of the document, and the CLI refuses them by name.
  assert.ok(entries.has('"stages"') && entries.has('"units"'), 'they still exist over there');
  assert.ok(!/"stages"/.test(description));
  assert.ok(!/"units"/.test(description));

  const depthStart = source.indexOf('depth: 0, 1 or 2 boundary hops');
  const depthBlock = source.slice(depthStart, source.indexOf('Ignored by', depthStart));
  const depthDescription = flat(
    MANIFEST.contributes.languageModelTools[0].inputSchema.properties.depth.description
  );
  assert.ok(
    depthDescription.includes(flat(depthBlock.replace('depth: ', ''))),
    `depth differs between the two hosts:\n  MCP: ${flat(depthBlock)}\n  LM : ${depthDescription}`
  );
});
