'use strict';
/**
 * Hardening round 2, area hosts-ux — HOSTS-UX-FLAGDEFAULT.
 *
 * CONTRACTS 11.37 C2 is normative: *"A flag beats the file for every
 * `[analysis]` option — `relevance`, `relevance_hops`, `dataflow`, `max_nodes`,
 * `include_notebooks` — and for `[rules] min_confidence`, because a flag is
 * something a human typed just now."*
 *
 * `analyzer/src/mlview/core/config.py:apply()` decides "did the caller ask?" by
 * comparing the option against its `AnalyzeOptions` default:
 *
 *     current = getattr(options, key, None)
 *     if current != _default_of(spec):
 *         continue                        # the caller asked; the caller wins
 *     changes[key] = value
 *
 * So a flag typed AT its default value is indistinguishable from an absent one
 * and the file silently wins. MEASURED on `samples/vision_pipeline`:
 *
 *     [analysis] max_nodes = 12   + --max-nodes 400  ->  12 nodes, truncated
 *     [analysis] max_nodes = 12   + --max-nodes 401  ->  54 nodes, not truncated
 *     [rules] min_confidence=0.96 + --min-confidence 0.0  ->   1 finding
 *     [rules] min_confidence=0.96 + --min-confidence 0.1  ->  15 findings
 *
 * — a strictly LOWER floor returning strictly FEWER findings.
 *
 * This is a host test and not only an analyzer one because `buildAnalyzeArgs`
 * emits `--max-nodes`/`--max-files` on EVERY run (CFG-ONE also emits `--config`
 * whenever the folder has one), so the VS Code seam is exactly the caller that
 * always types the flag at its default. `mlview.maxNodes` defaults to 400,
 * which is also the analyzer's default, so today a checked-in
 * `[analysis] max_nodes` quietly overrides the setting — and the behaviour
 * flips the moment either default moves.
 *
 * The suite skips itself when `python -m mlview` is not importable, exactly the
 * way `hardening_realgraphs.test.js` does.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const { api, REPO_ROOT } = require('./harness.js');

const { buildAnalyzeArgs, DEFAULT_SETTINGS } = api;
const PYTHON = process.env.MLVIEW_TEST_PYTHON || 'python3';
const SAMPLE = path.join(REPO_ROOT, 'samples', 'vision_pipeline');

/** Run the analyzer with exactly the argv the extension would have spawned. */
function runHostArgs(args) {
  return JSON.parse(
    execFileSync(PYTHON, args, {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        PYTHONDONTWRITEBYTECODE: '1'
      }
    })
  );
}

let AVAILABLE = true;
try {
  runHostArgs(['-X', 'utf8', '-m', 'mlview', 'analyze', SAMPLE, '--json', '-']);
} catch {
  AVAILABLE = false;
}
const maybe = AVAILABLE ? test : test.skip;

/** A throwaway copy of the sample with `body` written into its .mlview.toml. */
function workspaceWith(body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-cfg-'));
  fs.cpSync(SAMPLE, dir, { recursive: true });
  fs.writeFileSync(path.join(dir, '.mlview.toml'), body, 'utf8');
  return dir;
}

test('the host types --max-nodes and --max-files on every single run', () => {
  const args = buildAnalyzeArgs({
    paths: ['/w'],
    maxFiles: DEFAULT_SETTINGS.maxFiles,
    maxNodes: DEFAULT_SETTINGS.maxNodes,
    exclude: []
  });
  assert.ok(args.includes('--max-nodes'), 'buildAnalyzeArgs always emits --max-nodes: ' + args.join(' '));
  assert.ok(args.includes('--max-files'), 'buildAnalyzeArgs always emits --max-files: ' + args.join(' '));
  assert.equal(
    args[args.indexOf('--max-nodes') + 1],
    String(DEFAULT_SETTINGS.maxNodes),
    'and it emits the setting verbatim, which defaults to the analyzer default — the exact ' +
      'collision 11.37 C2 has to survive'
  );
});

maybe('--max-nodes beats [analysis] max_nodes, even when it is typed at the default', () => {
  const dir = workspaceWith('[analysis]\nmax_nodes = 12\n');
  try {
    const flag = DEFAULT_SETTINGS.maxNodes; // 400, and also the analyzer's own default
    const args = buildAnalyzeArgs({
      paths: [dir],
      maxFiles: DEFAULT_SETTINGS.maxFiles,
      maxNodes: flag,
      exclude: [],
      configPath: path.join(dir, '.mlview.toml')
    });
    const withDefaultFlag = runHostArgs(['-X', 'utf8', ...args]);

    const oneMore = buildAnalyzeArgs({
      paths: [dir],
      maxFiles: DEFAULT_SETTINGS.maxFiles,
      maxNodes: flag + 1,
      exclude: [],
      configPath: path.join(dir, '.mlview.toml')
    });
    const withRaisedFlag = runHostArgs(['-X', 'utf8', ...oneMore]);

    assert.equal(
      withDefaultFlag.nodes.length,
      withRaisedFlag.nodes.length,
      'a budget of ' + flag + ' drew ' + withDefaultFlag.nodes.length + ' nodes and a budget of ' +
        (flag + 1) + ' drew ' + withRaisedFlag.nodes.length +
        ': the file won over the flag only because the flag happened to equal the default ' +
        '(analyzer/src/mlview/core/config.py apply())'
    );
    assert.equal(
      withDefaultFlag.stats.truncated,
      false,
      'and the document must not be reported as truncated when the caller asked for the whole graph'
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

maybe('--min-confidence 0.0 shows everything, even against a [rules] min_confidence floor', () => {
  const dir = workspaceWith('[rules]\nmin_confidence = 0.96\n');
  try {
    const base = ['-X', 'utf8', '-m', 'mlview', 'analyze', dir, '--json', '-', '--config', path.join(dir, '.mlview.toml')];
    const atZero = runHostArgs([...base, '--min-confidence', '0.0']);
    const atTenth = runHostArgs([...base, '--min-confidence', '0.1']);

    assert.ok(
      atZero.issues.length >= atTenth.issues.length,
      'lowering the floor from 0.1 to 0.0 lost findings: 0.1 -> ' + atTenth.issues.length +
        ', 0.0 -> ' + atZero.issues.length +
        '. --min-confidence 0.0 is the one value a human types to mean "no floor at all", ' +
        'and it is the one value config.apply() reads as "the caller did not ask".'
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
