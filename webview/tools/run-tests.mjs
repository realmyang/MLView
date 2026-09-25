// Runs every test/*.test.mjs through `node --test`, by discovery.
//
// HOSTS-UX-WEBVIEW-RUNNER. `"test"` used to name its thirty files one by one,
// so a file added to `webview/test/` was invisible to `npm test` and therefore
// to the `webview` CI job: three new regression files sat on disk, failing,
// while `npm test` reported "534 pass, todo 0". A regression test that the gate
// never runs is decoration, and this is the one package where writing the test
// was not enough to make it a gate.
//
// Discovery, not a glob, and not a bare directory:
//   * `node --test test/` is accepted by Node 20 but rejected by Node 21+, and
//     Node's own directory walk also matches `**/test/**/*.mjs` -- which would
//     sweep in the helper modules (`helpers.mjs`, and `authored-handshake.mjs`,
//     which `authored-integration.test.mjs` runs) that are libraries, not tests;
//   * `node --test test/*.test.mjs` needs the shell to expand the glob (Node 22
//     can glob its own arguments, Node 20 cannot), and cmd.exe does not -- and
//     CI's Windows e2e job runs `npm test` on Node 20.
// So the file list is built here, the same way `vscode-extension/tools/run-tests.mjs`
// builds its own. No gate checks that a package keeps using discovery: a test
// file that does not end in `.test.mjs` is simply never run.
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const pkgDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const testDir = join(pkgDir, 'test');
const files = readdirSync(testDir)
  .filter((name) => /\.test\.(c|m)?js$/.test(name))
  .sort()
  .map((name) => join('test', name));

if (files.length === 0) {
  console.error('run-tests: no test/*.test.mjs files found');
  process.exit(1);
}

const extra = process.argv.slice(2);
const result = spawnSync(process.execPath, ['--test', ...extra, ...files], {
  cwd: pkgDir,
  stdio: 'inherit',
});
process.exit(result.status ?? 1);
