'use strict';
/**
 * PUB-R07 — the two promises `test/fixtures/vision_pipeline.graph.json` makes.
 *
 * `scope.test.js` and the F2-A11 half of `diagnostics.test.js` are asserted against that
 * fixture on the strength of one sentence: it is a REAL analyzer run over
 * `samples/vision_pipeline`. Two things can quietly falsify it, and both had:
 *
 *   1. It goes STALE. The committed copy held 54 nodes while the analyzer on the tree emitted
 *      59 for the same input, so the host suite was green against a document the product had
 *      stopped producing. CONTRACTS §15.5 already requires the fixture to move in the same
 *      change as a graph-shape change; nothing enforced it.
 *   2. It LEAKS. The raw document embeds `workspace.root` and an `absFile` on every node,
 *      edge, issue, related location and fix edit, so running the documented CLI command
 *      verbatim writes ~164 copies of the runner's home directory into a public repository.
 *      The committed copy was neutralised to `/home/mlview/MLView` by hand and no step said so.
 *
 * `tools/make_scope_fixture.py` now does the run and the neutralisation together. This file is
 * its acceptance: the leak half is checked from the bytes on disk and always runs; the
 * staleness half shells out to `--check` and skips when no analyzer can be found, the way
 * `hardening_realgraphs.test.js` skips.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const EXTENSION_ROOT = path.join(__dirname, '..');
const FIXTURE = path.join(__dirname, 'fixtures', 'vision_pipeline.graph.json');
const MAKER = path.join(EXTENSION_ROOT, 'tools', 'make_scope_fixture.py');
const TEXT = fs.readFileSync(FIXTURE, 'utf8');
const GRAPH = JSON.parse(TEXT);

/** The neutral root `tools/make_scope_fixture.py` rewrites every path to. */
const FIXTURE_ROOT = '/home/mlview/MLView';

// ---------------------------------------------------------------- the leak half

test('the fixture is rooted at the neutral path, not at anybody’s checkout', () => {
  assert.equal(GRAPH.workspace.root, `${FIXTURE_ROOT}/samples/vision_pipeline`);
});

test('every absolute path in the fixture lives under that root', () => {
  const offenders = [];
  (function walk(node, where) {
    if (Array.isArray(node)) {
      node.forEach((item, i) => walk(item, `${where}[${i}]`));
    } else if (node && typeof node === 'object') {
      for (const [key, value] of Object.entries(node)) walk(value, `${where}.${key}`);
    } else if (typeof node === 'string' && /^(?:\/|[A-Za-z]:[\\/])/.test(node)) {
      if (!node.startsWith(`${FIXTURE_ROOT}/`) && node !== FIXTURE_ROOT) {
        offenders.push(`${where} = ${node}`);
      }
    }
  })(GRAPH, 'graph');
  assert.deepEqual(
    offenders.slice(0, 5),
    [],
    'regenerate with `python vscode-extension/tools/make_scope_fixture.py`, never with the ' +
      'bare CLI: ' + offenders.slice(0, 5).join(', ')
  );
});

test('no home directory, and no Windows path, survives anywhere in the bytes', () => {
  // Deliberately blunt, because it is the check a reviewer cannot be asked to do by eye:
  // `/Users/...`, any `/home/` that is not the neutral one, and any drive-lettered path.
  const leaks = [
    ...TEXT.matchAll(/\/Users\/[^"\\\s]*|\/home\/(?!mlview\/)[^"\\\s]*|[A-Za-z]:[\\/][^"\s]*/g)
  ].map((m) => m[0]);
  assert.deepEqual(
    [...new Set(leaks)].slice(0, 5),
    [],
    'the fixture ships in a public repository; it must carry no real path'
  );
});

test('the regeneration recipe scope.test.js documents is a file that exists', () => {
  assert.ok(fs.existsSync(MAKER), 'vscode-extension/tools/make_scope_fixture.py is missing');
  const recipe = fs.readFileSync(path.join(__dirname, 'scope.test.js'), 'utf8');
  assert.ok(
    recipe.includes('tools/make_scope_fixture.py'),
    'scope.test.js must point at the script that neutralises the paths, not at a bare CLI run'
  );
  assert.ok(
    !/--json\s+vscode-extension\/test\/fixtures/.test(recipe),
    'a documented command that writes the fixture straight from the CLI leaks a home path'
  );
});

// ---------------------------------------------------------------- the staleness half

const PYTHON = process.env.MLVIEW_TEST_PYTHON || 'python3';

/**
 * The environment `--check` needs: a Python 3.10+ (older ones cannot parse the sample at all,
 * and `python3` is still 3.9 on a stock macOS) that can import `mlview` — installed, or the
 * bundled core `npm run compile` builds (C2). Undefined when there is none, and the staleness
 * test then skips rather than failing for a reason that is not about the fixture.
 */
function analyzerEnv() {
  const base = {
    ...process.env,
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PYTHONDONTWRITEBYTECODE: '1'
  };
  const core = path.join(EXTENSION_ROOT, 'core');
  const candidates = [base];
  if (fs.existsSync(path.join(core, 'mlview'))) {
    candidates.push({
      ...base,
      PYTHONPATH: [core, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter)
    });
  }
  for (const env of candidates) {
    try {
      execFileSync(
        PYTHON,
        ['-c', 'import sys, mlview; sys.exit(0 if sys.version_info >= (3, 10) else 1)'],
        { env, stdio: 'ignore' }
      );
      return env;
    } catch {
      /* try the next one */
    }
  }
  return undefined;
}

const ENV = analyzerEnv();
const maybe = ENV === undefined ? test.skip : test;

maybe('the fixture is still what the analyzer emits for samples/vision_pipeline', () => {
  // `--check` re-runs the CLI into a temporary directory, neutralises it the same way, and
  // byte-compares with the committed fixture, ignoring only `generator.generatedAt` and
  // `stats.durationMs` — the two per-run fields the analyzer's own determinism test names. It
  // writes nothing, here or anywhere.
  try {
    execFileSync(PYTHON, [MAKER, '--check'], {
      cwd: path.join(EXTENSION_ROOT, '..'),
      env: ENV,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe']
    });
  } catch (err) {
    assert.fail(
      (err.stderr || err.stdout || String(err.message)).trim() ||
        'make_scope_fixture.py --check failed'
    );
  }
});
