import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
// The package holds a copy of each of these files of the repository root.
const COPIES = ['THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'];
const check = process.argv.includes('--check');

for (const name of COPIES) {
  const expected = fs.readFileSync(path.resolve(extensionRoot, '..', name));
  const target = path.join(extensionRoot, name);
  if (check) {
    const actual = fs.existsSync(target) ? fs.readFileSync(target) : undefined;
    if (!actual?.equals(expected)) {
      throw new Error(`vscode-extension/${name} is missing or stale`);
    }
  } else {
    fs.writeFileSync(target, expected);
  }
}
