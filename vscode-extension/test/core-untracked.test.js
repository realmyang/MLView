'use strict';
/**
 * C2 — the analyzer the VSIX ships is a BUILD ARTIFACT, and this is the test that
 * keeps it one.
 *
 * `vscode-extension/core/mlview` used to be ~120 tracked files: a second copy of
 * `analyzer/src/mlview` in the index, re-committed on every analyzer change, and
 * pure review surface — nobody reads a mechanical copy, and `tools/sync-core.py`
 * already refuses to let it drift. It is now gitignored and written at build
 * time: `npm run compile`, `npm run pretest` and `vsce package`'s
 * `vscode:prepublish` all run `tools/sync-core.mjs` first.
 *
 * Which moves the risk rather than removing it. The old failure was "the tracked
 * copy drifted", caught by `tools/sync-core.py --check`. The new one is "nothing
 * built it", which no other suite can see: a VSIX packaged without `core/` is
 * under the size ceiling, passes every unit test, installs cleanly and has no
 * analyzer at all. So this file asserts the whole chain that makes the artifact
 * appear — the ignore rule, the three scripts that run the builder, the builder
 * itself, and `.vscodeignore`'s negation that keeps the result in the package —
 * plus, when a git is available, that the directory really is out of the index.
 *
 * Its Python twin is `python tools/verify.py --vsix` (strict: the directory must
 * exist and be byte-identical), and its end-to-end twin is
 * `vscode-extension/tools/vsix_smoke.py`, which runs the analyzer out of the
 * packaged VSIX.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const EXTENSION_ROOT = path.join(__dirname, '..');
const REPO_ROOT = path.join(EXTENSION_ROOT, '..');
const CORE_DIR = path.join(EXTENSION_ROOT, 'core');
const manifest = JSON.parse(
  fs.readFileSync(path.join(EXTENSION_ROOT, 'package.json'), 'utf8')
);

/** `git <args>` in the repo root, or undefined when there is no usable git. */
function git(...args) {
  const result = spawnSync('git', args, {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (result.error !== undefined || result.status === null) return undefined;
  return result;
}

// ------------------------------------------------------- the artifact exists
test('the bundled core is on disk when the tests run — pretest builds it', () => {
  // `npm test` runs `pretest`, which runs `node tools/sync-core.mjs`. If this
  // fails, the build chain is broken and `npm run package` would ship a VSIX
  // with no analyzer in it.
  assert.ok(
    fs.existsSync(path.join(CORE_DIR, 'mlview', '__init__.py')),
    'vscode-extension/core/mlview is missing — run `npm run compile` (or ' +
      '`python tools/sync-core.py`); it is a gitignored build artifact'
  );
  assert.ok(
    fs.existsSync(path.join(CORE_DIR, 'mlview', 'version.py')),
    'the built core has no version.py, so bundledCore.ts would read it as absent'
  );
});

// --------------------------------------------------------- it is not tracked
test('and it is NOT in git — a build artifact in the index is the thing C2 removed', () => {
  const tracked = git('ls-files', '--', 'vscode-extension/core');
  if (tracked === undefined) {
    // A published extension folder, or a machine with no git. Nothing to assert;
    // the ignore-rule test below still runs off the file itself.
    return;
  }
  const listed = tracked.stdout.split('\n').filter((line) => line.trim() !== '');
  assert.deepEqual(
    listed,
    [],
    `git tracks ${listed.length} file(s) under vscode-extension/core — the ` +
      'bundled analyzer is a build artifact; `git rm -r --cached ' +
      'vscode-extension/core` and let .gitignore hold it'
  );
});

test('.gitignore carries the rule, so a build never shows up as untracked noise', () => {
  const ignore = fs.readFileSync(path.join(REPO_ROOT, '.gitignore'), 'utf8');
  const rules = ignore
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '' && !line.startsWith('#'));
  assert.ok(
    rules.includes('vscode-extension/core/'),
    '.gitignore must ignore vscode-extension/core/ — without it every build ' +
      'writes ~120 untracked files into `git status`'
  );

  // `--no-index` because check-ignore otherwise stays silent about a path that is
  // still TRACKED, which would make this assertion a second, worse spelling of the
  // one above. The question here is only "does an ignore rule match this path".
  const checked = git('check-ignore', '-q', '--no-index', '--', 'vscode-extension/core/mlview');
  if (checked !== undefined) {
    assert.equal(
      checked.status,
      0,
      'git matches no ignore rule against vscode-extension/core/mlview, whatever ' +
        '.gitignore appears to say — something else (a negation, an exclude file) ' +
        're-admits it'
    );
  }
});

// ------------------------------------------------ everything that builds it
test('the builder exists and is the wrapper, not a second copier', () => {
  const builder = path.join(EXTENSION_ROOT, 'tools', 'sync-core.mjs');
  assert.ok(fs.existsSync(builder), 'vscode-extension/tools/sync-core.mjs is missing');
  const source = fs.readFileSync(builder, 'utf8');
  assert.match(
    source,
    /tools['"],\s*['"]sync-core\.py/,
    'sync-core.mjs must delegate to tools/sync-core.py — one copier, one set of ' +
      'skip rules, one gate'
  );
});

test('compile, pretest and vscode:prepublish all build the core FIRST', () => {
  const scripts = manifest.scripts || {};
  for (const name of ['compile', 'pretest']) {
    const script = scripts[name];
    assert.ok(script, `package.json has no "${name}" script`);
    assert.match(
      script,
      /node tools\/sync-core\.mjs/,
      `"${name}" must run tools/sync-core.mjs — it is what puts the bundled ` +
        'analyzer on disk'
    );
    assert.ok(
      script.indexOf('tools/sync-core.mjs') < script.indexOf('esbuild.mjs'),
      `"${name}" must build the core BEFORE bundling, so a failure there stops ` +
        'the build instead of producing a coreless extension'
    );
  }
  // `vsce package` runs `vscode:prepublish`; without it, packaging on a fresh
  // clone produces a VSIX with no `core/` and no warning of any kind.
  assert.equal(
    scripts['vscode:prepublish'],
    'npm run compile',
    'vscode:prepublish must run the compile chain — it is the only hook ' +
      '`vsce package` calls'
  );
});

test('.vscodeignore still negates core/**, so the built copy reaches the package', () => {
  const text = fs.readFileSync(path.join(EXTENSION_ROOT, '.vscodeignore'), 'utf8');
  const patterns = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '' && !line.startsWith('#'));
  assert.ok(
    patterns.includes('!core/**'),
    '.vscodeignore must negate core/** explicitly: vsce falls back to .gitignore ' +
      'only when this file is absent, and .gitignore now excludes core/'
  );
  const drops = patterns.filter(
    (p) =>
      (p === 'core' || p.startsWith('core/')) &&
      !p.includes('__pycache__') &&
      !/\.py[cod]$/.test(p)
  );
  assert.deepEqual(
    drops,
    [],
    `.vscodeignore would drop the bundled analyzer out of the package (${drops.join(', ')})`
  );
});
