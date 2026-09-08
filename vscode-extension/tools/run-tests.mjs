// Runs every test/*.test.js through `node --test`, on every Node version the
// project supports. `node --test test/` (a bare directory) is accepted by Node 20
// but rejected by Node 21+ ("Cannot find module .../test"), and shell globs are
// not expanded by cmd.exe on Windows, so the file list is built here instead.
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
  console.error('run-tests: no test/*.test.js files found');
  process.exit(1);
}

const extra = process.argv.slice(2);
const result = spawnSync(process.execPath, ['--test', ...extra, ...files], {
  cwd: pkgDir,
  stdio: 'inherit',
});
process.exit(result.status ?? 1);
