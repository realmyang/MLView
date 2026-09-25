import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.resolve(extensionRoot, '..', 'THIRD_PARTY_NOTICES.md');
const target = path.join(extensionRoot, 'THIRD_PARTY_NOTICES.md');
const expected = fs.readFileSync(source);

if (process.argv.includes('--check')) {
  const actual = fs.existsSync(target) ? fs.readFileSync(target) : undefined;
  if (!actual?.equals(expected)) {
    throw new Error('vscode-extension/THIRD_PARTY_NOTICES.md is missing or stale');
  }
} else {
  fs.writeFileSync(target, expected);
}
