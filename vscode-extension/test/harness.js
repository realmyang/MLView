'use strict';
/**
 * Loads the bundled extension modules with `vscode` redirected to the mock.
 *
 * `node esbuild.mjs --test` (the `pretest` npm script) bundles src/testEntry.ts to
 * out/test-entry.cjs with `--external:vscode`, so the bundle contains a literal
 * `require("vscode")` that this Module._resolveFilename hook intercepts.
 */

const Module = require('node:module');
const path = require('node:path');
const fs = require('node:fs');

const MOCK = path.join(__dirname, 'mock-vscode.js');
const BUNDLE = path.join(__dirname, '..', 'out', 'test-entry.cjs');

if (!Module.__mlviewHookInstalled) {
  const original = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    if (request === 'vscode') {
      return MOCK;
    }
    return original.call(this, request, ...rest);
  };
  Module.__mlviewHookInstalled = true;
}

if (!fs.existsSync(BUNDLE)) {
  throw new Error(
    `${BUNDLE} is missing. Run "npm run pretest" (or "node esbuild.mjs --test") before "node --test".`
  );
}

const api = require(BUNDLE);
const vscode = require(MOCK);

const REPO_ROOT = path.resolve(__dirname, '..', '..');

function readSampleGraph() {
  const file = path.join(REPO_ROOT, 'contracts', 'graph.sample.json');
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/** A deterministic synthetic graph with `nodeCount` nodes and a long issue list. */
function syntheticGraph(nodeCount, issueCount = 60) {
  const stages = [
    'config',
    'data',
    'preprocess',
    'model',
    'objective',
    'train',
    'eval',
    'deliver'
  ];
  const root = 'C:/Users/realm/Desktop/MLView/samples/synthetic_pipeline_with_a_long_name';
  const hex = (n) => n.toString(16).padStart(12, '0');
  const nodes = [];
  for (let i = 0; i < nodeCount; i += 1) {
    const stage = stages[i % stages.length];
    const file = `package/module_${String(i % 25).padStart(3, '0')}.py`;
    nodes.push({
      id: `n:${hex(i)}`,
      kind: 'function',
      level: i % 3 === 0 ? 'unit' : 'op',
      stage,
      label: `synthetic_node_${i}`,
      sublabel: `generated node number ${i} in stage ${stage}`,
      qualname: `package.module_${i % 25}.synthetic_node_${i}`,
      loc: {
        file,
        absFile: `${root}/${file}`,
        line: i + 1,
        col: 4,
        endLine: i + 6,
        endCol: 12,
        symbol: `synthetic_node_${i}`,
        snippet: `    synthetic_node_${i}()  # generated`
      },
      parent: null,
      attrs: {},
      produces: [],
      consumes: [],
      ghost: false,
      dynamic: false,
      confidence: 0.9,
      confidenceBucket: 'certain',
      issueIds: [],
      collapsedByDefault: false,
      stageEvidence: []
    });
  }
  const issues = [];
  for (let i = 0; i < issueCount; i += 1) {
    const severity = ['high', 'medium', 'low'][i % 3];
    const file = `package/module_${String(i % 25).padStart(3, '0')}.py`;
    issues.push({
      id: `i:${hex(1000 + i)}`,
      code: `MLV${String(100 + (i % 20)).padStart(3, '0')}`,
      ruleVersion: 1,
      severity,
      confidence: 0.75,
      confidenceBucket: 'likely',
      title: `Synthetic finding number ${i} with a deliberately long descriptive title`,
      message: `A generated message for finding ${i}. `.repeat(4),
      why: `A generated consequence sentence for finding ${i}. `.repeat(2),
      fixHint: `Do the generated thing for finding ${i}, at length, with API names. `.repeat(2),
      loc: {
        file,
        absFile: `${root}/${file}`,
        line: i + 2,
        col: 8,
        endLine: i + 2,
        endCol: 40,
        symbol: `synthetic_symbol_${i}`,
        snippet: `        synthetic_symbol_${i}()`
      },
      relatedLocs: [
        {
          role: 'call_site',
          message: `related location ${i}`,
          file,
          absFile: `${root}/${file}`,
          line: i + 3,
          col: 8,
          endLine: i + 3,
          endCol: 30
        }
      ],
      nodeIds: [`n:${hex(i % nodeCount)}`],
      edgeIds: [],
      stage: stages[i % stages.length],
      frameworks: ['torch'],
      tags: ['correctness'],
      evidence: [],
      suppressed: false,
      docs: `docs/rules/MLV${String(100 + (i % 20)).padStart(3, '0')}.md`
    });
  }
  return {
    schemaVersion: '1.0',
    generator: {
      name: 'mlview',
      version: '0.1.0',
      rendererSha: '0'.repeat(64),
      generatedAt: '2026-09-06T14:22:11Z'
    },
    workspace: {
      root,
      entrypoints: ['package/module_000.py'],
      filesAnalyzed: 25,
      filesFailed: 1,
      notebooksSkipped: 2,
      frameworks: ['torch', 'sklearn', 'numpy', 'pandas']
    },
    stages: stages.map((id, order) => ({
      id,
      label: `Stage ${id}`,
      order,
      present: true,
      nodeCount: Math.floor(nodeCount / stages.length),
      issueCounts: { low: 2, medium: 2, high: 2 },
      maxSeverity: 'high'
    })),
    nodes,
    edges: [],
    issues,
    diagnostics: [],
    stats: {
      nodes: nodeCount,
      edges: 0,
      issues: { low: 20, medium: 20, high: 20 },
      suppressed: 0,
      durationMs: 1234,
      truncated: true
    }
  };
}

module.exports = { api, vscode, readSampleGraph, syntheticGraph, REPO_ROOT, MOCK, BUNDLE };
