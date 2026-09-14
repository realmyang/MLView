'use strict';
/**
 * PACKAGING (docs/CONTRACTS.md §11.25) — the marketplace install, asserted.
 *
 * Two audits wanted opposite things ("bundle the analyzer" vs "pip install from PyPI")
 * and the resolution is a precedence chain, so the chain itself is what these tests
 * pin: an installed core wins when it is present, schema-compatible and not older;
 * otherwise the copy in `<extension>/core` answers, run through PYTHONPATH.
 *
 * The rest is the manifest work that makes `vsce package` legal at all. Every one of
 * those assertions is a bug that shipped: `private: true` (vsce refuses to publish),
 * no `repository` (the package script carried `--allow-missing-repository`), no icon,
 * and no `extensionKind`, so a Remote-SSH install landed wherever the default put it
 * rather than on the machine that owns the files and the interpreter.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { api } = require('./harness.js');
const { readBundledCore, chooseCore, compareVersions, coreLabel } = api;

const EXTENSION_ROOT = path.join(__dirname, '..');
const REPO_ROOT = path.join(EXTENSION_ROOT, '..');
// C2: a gitignored BUILD artifact, written by `node tools/sync-core.mjs`, which
// `pretest` runs before this file executes. `core-untracked.test.js` asserts that
// it is built AND that git does not track it; here it is simply expected to exist.
const CORE_DIR = path.join(EXTENSION_ROOT, 'core');
const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_ROOT, 'package.json'), 'utf8'));

// --------------------------------------------------------------- the chain

test('compareVersions orders numerically, not lexically, and sorts pre-releases below', () => {
  assert.equal(compareVersions('0.1.0', '0.1.0'), 0);
  assert.equal(compareVersions('0.10.0', '0.9.0'), 1, '0.10 is newer than 0.9');
  assert.equal(compareVersions('0.9.0', '0.10.0'), -1);
  assert.equal(compareVersions('1.0', '1.0.0'), 0, 'a missing component is a zero');
  assert.equal(compareVersions('1.2.3', '1.2'), 1);
  assert.equal(compareVersions('0.2.0rc1', '0.2.0'), -1, 'a release candidate is older');
  assert.equal(compareVersions('0.2.0', '0.2.0rc1'), 1);
  assert.equal(compareVersions('nonsense', '0.1.0'), -1, 'an unreadable version never wins');
});

const BUNDLED = { pythonPath: '/ext/core', version: '0.1.0', schemaVersion: '1.0' };

test('an installed core wins when it is present, schema-compatible and not older', () => {
  const choice = chooseCore({ version: '0.1.0', schemaVersion: '1.0' }, BUNDLED, '1.0');
  assert.equal(choice.kind, 'installed');
  assert.equal(choice.reason, 'installed-is-current');

  const newer = chooseCore({ version: '0.3.0', schemaVersion: '1.0' }, BUNDLED, '1.0');
  assert.equal(newer.kind, 'installed');
});

test('the bundled core answers when there is no installed core at all', () => {
  const choice = chooseCore(undefined, BUNDLED, '1.0');
  assert.equal(choice.kind, 'bundled');
  assert.equal(choice.reason, 'no-installed-core');
  assert.equal(choice.bundled.pythonPath, '/ext/core');
});

test('an older installed core loses to the bundled one', () => {
  const choice = chooseCore({ version: '0.0.9', schemaVersion: '1.0' }, BUNDLED, '1.0');
  assert.equal(choice.kind, 'bundled');
  assert.equal(choice.reason, 'installed-is-older');
  assert.equal(choice.installed.version, '0.0.9');
});

test('a schema-major mismatch is no longer fatal — the bundled core answers instead', () => {
  const choice = chooseCore({ version: '9.9.9', schemaVersion: '2.0' }, BUNDLED, '1.0');
  assert.equal(choice.kind, 'bundled', 'a newer core that speaks schema 2 cannot be read');
  assert.equal(choice.reason, 'installed-schema-mismatch');
  // Same major, different minor: readable, so the installed core still wins.
  assert.equal(chooseCore({ version: '9.9.9', schemaVersion: '1.7' }, BUNDLED, '1.0').kind,
    'installed');
});

test('with neither core there is nothing to run, and the chain says so', () => {
  assert.equal(chooseCore(undefined, undefined, '1.0').kind, 'none');
  // A build with no bundled core behaves exactly as it did before PACKAGING.
  const legacy = chooseCore({ version: '0.0.1' }, undefined, '1.0');
  assert.equal(legacy.kind, 'installed');
  assert.equal(legacy.reason, 'no-bundled-core');
});

test('coreLabel names which core is in use and why — that is the whole tooltip', () => {
  const installed = coreLabel(chooseCore({ version: '0.1.0', schemaVersion: '1.0' }, BUNDLED), '/py');
  assert.match(installed, /^core: mlview 0\.1\.0 installed in the interpreter/);
  assert.match(installed, /\/py$/);

  const bundled = coreLabel(chooseCore(undefined, BUNDLED), '/py');
  assert.match(bundled, /^core: mlview 0\.1\.0 bundled with the extension/);
  assert.match(bundled, /no mlview installed in the interpreter/);

  const older = coreLabel(chooseCore({ version: '0.0.9', schemaVersion: '1.0' }, BUNDLED));
  assert.match(older, /the installed mlview 0\.0\.9 is older/);
});

// ------------------------------------------------------- the bundled core

test('readBundledCore reads the real <extension>/core that sync-core.py wrote', () => {
  const bundled = readBundledCore(EXTENSION_ROOT);
  assert.ok(bundled, 'run `npm run compile` — it builds vscode-extension/core');
  assert.equal(bundled.pythonPath, CORE_DIR, 'PYTHONPATH points at core/, the parent of mlview/');
  assert.equal(bundled.version, manifest.version, 'CONTRACTS A2: one version string everywhere');
  assert.match(bundled.schemaVersion, /^\d+\.\d+$/);
});

test('a build with no bundled core degrades to undefined, never to a throw', () => {
  assert.equal(readBundledCore(path.join(EXTENSION_ROOT, 'does-not-exist')), undefined);
  assert.equal(
    readBundledCore('/ext', { exists: () => true, read: () => 'nothing useful in here' }),
    undefined,
    'a version.py that does not declare __version__ is not a usable core'
  );
  assert.equal(
    readBundledCore('/ext', {
      exists: () => true,
      read: () => {
        throw new Error('EACCES');
      }
    }),
    undefined,
    'an unreadable core is absent, not fatal'
  );
});

test('the bundled core is a runnable package, not just a directory', () => {
  for (const rel of [
    'mlview/__init__.py',
    'mlview/__main__.py',
    'mlview/cli.py',
    'mlview/version.py',
    'mlview/schema/graph.schema.json',
    'mlview/emit/assets/mlview.js'
  ]) {
    assert.ok(fs.existsSync(path.join(CORE_DIR, rel)), `the VSIX core is missing ${rel}`);
  }
  // sync-core.py's skip rules: no tests, no bytecode.
  assert.ok(!fs.existsSync(path.join(CORE_DIR, 'mlview', 'tests')), 'tests must not ship');
  const stray = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === '__pycache__') stray.push(full);
        else walk(full);
      } else if (/\.py[cod]$/.test(entry.name)) {
        stray.push(full);
      }
    }
  };
  walk(CORE_DIR);
  assert.deepEqual(stray, [], 'bytecode compiled from another revision must never ship');
});

test('the bundled core is byte-identical to analyzer/src/mlview, file for file', () => {
  // The cheap half of `tools/verify.py --vsix`, so a drifted copy fails in this suite too.
  const source = path.join(REPO_ROOT, 'analyzer', 'src', 'mlview');
  for (const rel of ['version.py', 'cli.py', 'api.py', 'schema/graph.schema.json']) {
    const a = fs.readFileSync(path.join(source, rel));
    const b = fs.readFileSync(path.join(CORE_DIR, 'mlview', rel));
    assert.ok(a.equals(b), `${rel} has drifted — run python tools/sync-core.py`);
  }
});

// ------------------------------------------------------------ the manifest

test('the manifest is publishable: no private flag, and a real repository', () => {
  assert.ok(!('private' in manifest), 'vsce refuses to publish a private package');
  assert.equal(manifest.repository.type, 'git');
  assert.match(manifest.repository.url, /^https:\/\/github\.com\/.+\.git$/);
  assert.equal(manifest.repository.directory, 'vscode-extension');
  assert.match(manifest.bugs.url, /^https:\/\/github\.com\//);
  assert.match(manifest.homepage, /^https:\/\/github\.com\//);
  assert.equal(manifest.preview, true, 'preview de-risks a one-way publish');
  assert.match(manifest.galleryBanner.color, /^#[0-9a-fA-F]{6}$/);
  assert.ok(['dark', 'light'].includes(manifest.galleryBanner.theme));
});

test('extensionKind is declared, not relied on: workspace, so remote installs land right', () => {
  assert.deepEqual(manifest.extensionKind, ['workspace']);
});

test('the package script no longer needs --allow-missing-repository', () => {
  assert.ok(!manifest.scripts.package.includes('--allow-missing-repository'));
  assert.match(manifest.scripts.package, /vsce package/);
});

test('the icon is a committed 128x128 PNG that tools/make_icon.py can regenerate', () => {
  assert.equal(manifest.icon, 'media/icon.png');
  const iconPath = path.join(EXTENSION_ROOT, manifest.icon);
  const data = fs.readFileSync(iconPath);
  assert.ok(data.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
    'not a PNG');
  // IHDR is always the first chunk: 8-byte signature, 4-byte length, 4-byte type.
  assert.equal(data.toString('ascii', 12, 16), 'IHDR');
  assert.equal(data.readUInt32BE(16), 128, 'the marketplace wants 128x128');
  assert.equal(data.readUInt32BE(20), 128);
  assert.ok(fs.existsSync(path.join(EXTENSION_ROOT, 'tools', 'make_icon.py')),
    'a binary asset nobody can regenerate is a liability');
});

test('.vscodeignore keeps the bundled core IN the package and its bytecode out', () => {
  const text = fs.readFileSync(path.join(EXTENSION_ROOT, '.vscodeignore'), 'utf8');
  const patterns = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('#'));
  const excludesCore = patterns.filter((p) => /^core([/\\]|$)/.test(p) && !p.includes('__pycache__'));
  assert.deepEqual(excludesCore, [], 'a VSIX without core/ has no analyzer at all');
  assert.ok(patterns.includes('!core/**'), 'the core is kept explicitly, not by omission');
  assert.ok(patterns.some((p) => p.includes('__pycache__')));
  assert.ok(patterns.includes('**/*.pyc'));
});
