'use strict';
/**
 * C2 — one analyzer in git, one analyzer in the package.
 *
 * `vscode-extension/core/mlview` used to be 96 tracked files: a third copy of
 * `analyzer/src/mlview`, reviewed on every pull request, conflicting on every
 * rebase, and kept honest only by a gate. It is now a BUILD ARTIFACT — written by
 * `python tools/sync-core.py` (which `npm run compile`, `npm run pretest` and
 * `vsce package`'s `vscode:prepublish` all run first), gitignored, and checked
 * against `analyzer/src/mlview` by `python tools/verify.py --vsix` and by
 * `packaging.test.js`.
 *
 * Both halves of that sentence are asserted here, because each without the other
 * is a shipped bug: a tracked copy is the review surface we just removed, and a
 * missing copy is a VSIX that installs with no analyzer at all.
 *
 * `claude-plugin/vendor/mlview` is deliberately still tracked and is NOT asserted
 * here: `claude plugin install` copies the plugin directory verbatim off a git
 * ref, so for that host what git holds is what the user runs. It goes away once
 * the wheel is on PyPI — see the root `.gitignore` and `tools/sync-core.py`.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const EXTENSION_ROOT = path.join(__dirname, '..');
const REPO_ROOT = path.join(EXTENSION_ROOT, '..');
const CORE_DIR = path.join(EXTENSION_ROOT, 'core');
/** Repo-relative and forward-slashed: git speaks that spelling on every platform. */
const CORE_RELATIVE = 'vscode-extension/core';

/** `git <args>` in the repo root, or undefined when there is no usable git here. */
function git(...args) {
  const result = spawnSync('git', args, { cwd: REPO_ROOT, encoding: 'utf8' });
  if (result.error !== undefined) return undefined;
  return result;
}

/** A source tarball, or a machine with no git, is not a failing repository. */
function inGitWorkTree() {
  const result = git('rev-parse', '--is-inside-work-tree');
  return result !== undefined && result.status === 0 && result.stdout.trim() === 'true';
}

test('the bundled analyzer is not tracked: `git ls-files` is empty for it', (t) => {
  if (!inGitWorkTree()) {
    t.skip('no git work tree here (a packaged or exported tree)');
    return;
  }
  const listed = git('ls-files', '--', CORE_RELATIVE);
  assert.equal(listed.status, 0, `git ls-files failed: ${listed.stderr}`);
  const tracked = listed.stdout.split(/\r?\n/).filter((line) => line.length > 0);
  assert.deepEqual(
    tracked,
    [],
    `${tracked.length} file(s) under ${CORE_RELATIVE} are still tracked, starting with ` +
      `${tracked[0]}. The bundled core is a build artifact: remove it from the index ` +
      'with `git rm -r --cached vscode-extension/core` (the working tree keeps it, and ' +
      '`npm run compile` rebuilds it).'
  );
});

test('and it is ignored by a rule, not merely absent from the index', (t) => {
  if (!inGitWorkTree()) {
    t.skip('no git work tree here (a packaged or exported tree)');
    return;
  }
  // `-v` names the file and line that ignores it, so a rule deleted by accident
  // fails here with the thing to restore rather than with a bare exit code.
  const ignored = git('check-ignore', '-v', '--no-index', `${CORE_RELATIVE}/mlview/version.py`);
  assert.equal(
    ignored.status,
    0,
    'nothing in .gitignore ignores vscode-extension/core/, so the next `git add -A` ' +
      'commits the whole bundled analyzer back into the repository'
  );
  assert.match(ignored.stdout, /\.gitignore/);
});

test('but it IS built, because a VSIX without it has no analyzer at all', () => {
  // `npm test` runs `pretest`, which runs `node tools/sync-core.mjs` first, so by
  // the time this file executes the copy has been written.
  assert.ok(
    fs.existsSync(path.join(CORE_DIR, 'mlview', '__init__.py')),
    'vscode-extension/core/mlview is missing — run `npm run compile` (or ' +
      '`python tools/sync-core.py` at the repo root)'
  );
  const entry = fs.readFileSync(path.join(CORE_DIR, 'mlview', 'version.py'), 'utf8');
  const source = fs.readFileSync(
    path.join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'version.py'),
    'utf8'
  );
  assert.equal(entry, source, 'the built core has drifted — run python tools/sync-core.py');
});

test('the npm scripts that need the core build it first, so nobody has to remember', () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(EXTENSION_ROOT, 'package.json'), 'utf8')
  );
  for (const script of ['compile', 'pretest']) {
    assert.match(
      manifest.scripts[script],
      /^node tools\/sync-core\.mjs &&/,
      `${script} must build the bundled core before anything else uses it`
    );
  }
  // `vsce package` and `vsce publish` both run `vscode:prepublish`, which is the
  // only hook that covers a package built by hand rather than through `npm run
  // package`.
  assert.equal(manifest.scripts['vscode:prepublish'], 'npm run compile');
  assert.ok(fs.existsSync(path.join(EXTENSION_ROOT, 'tools', 'sync-core.mjs')));
});
