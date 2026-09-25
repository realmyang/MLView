import { readdirSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const extensionRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const testDir = path.join(extensionRoot, 'test');
const files = readdirSync(testDir)
  .filter(name => name.endsWith('.test.js'))
  .sort()
  .map(name => path.join(testDir, name));

if (files.length === 0) {
  throw new Error('no test/*.test.js files found');
}

const result = spawnSync(process.execPath, ['--test', ...files], {
  cwd: extensionRoot,
  stdio: 'inherit',
  shell: false
});

if (result.error) {
  throw result.error;
}
process.exit(result.status ?? 1);
