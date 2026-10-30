// Runs every test/*.test.mjs, *.test.cjs and *.test.js through `node --test`, by discovery.
//
// The file list is read from `webview/test/` on every run, so a test file added
// there is run by `npm test`, in CI too, with no list to update. A `"test"`
// script that named its files one by one would leave out every file not added
// to it, and `npm test` would still pass.
//
// Discovery, not a glob, and not a bare directory:
//   * `node --test test/` is accepted by Node 20 but rejected by Node 21+, and
//     Node's own directory walk also matches `**/test/**/*.mjs` -- which would
//     sweep in the helper modules (`helpers.mjs`, `colour-lab.mjs`, and `authored-handshake.mjs`,
//     which `authored-integration.test.mjs` runs) that are libraries, not tests;
//   * `node --test test/*.test.mjs` needs the shell to expand the glob (Node 22
//     can glob its own arguments, Node 20 cannot), and cmd.exe does not -- and
//     `npm test` must work on Windows with Node 20.18.1, the oldest Node the
//     project supports.
// So the file list is built here, the same way `vscode-extension/tools/run-tests.mjs`
// builds its own. A file of test/ whose name does not end in `.test.mjs`,
// `.test.cjs` or `.test.js` is not run.
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
