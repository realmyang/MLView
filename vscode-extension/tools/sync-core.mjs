// Build the analyzer the VSIX ships, before anything that needs it (C2).
//
//   node tools/sync-core.mjs            # write vscode-extension/core/mlview
//   node tools/sync-core.mjs --check    # verify only, exit 1 on drift
//
// `vscode-extension/core/mlview` is a BUILD ARTIFACT, not a source: it is
// gitignored, and this wrapper is what puts it on disk. `npm run compile`,
// `npm run pretest` and `vsce package`'s `vscode:prepublish` all run it first,
// so every path that ends in a packaged or a tested extension has a current
// core, and nobody has to remember `python tools/sync-core.py` before
// `vsce package`.
//
// The real work is `<repo>/tools/sync-core.py` — one copier, one set of skip
// rules, one gate (`python tools/verify.py --vsix`). This file only finds a
// Python to run it with, which is why it is 80 lines and not a second copier.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const extensionRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = resolve(extensionRoot, '..');
const script = join(repoRoot, 'tools', 'sync-core.py');

// Same order as scripts/pythonpick.sh, and for the same reason: on Windows
// `python3.exe` is usually the Microsoft Store alias that opens a web page, and
// on Linux/macOS `python` usually does not exist at all.
const candidates =
  process.platform === 'win32'
    ? [['python'], ['py', '-3'], ['python3']]
    : [['python3'], ['python']];
if (process.env.MLVIEW_PYTHON) candidates.unshift([process.env.MLVIEW_PYTHON]);

/** The first candidate that is a real Python 3.10+, or undefined. */
function findPython() {
  const probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)';
  for (const argv of candidates) {
    const [command, ...prefix] = argv;
    const result = spawnSync(command, [...prefix, '-c', probe], {
      stdio: 'ignore',
      // PYTHONDONTWRITEBYTECODE: a probe must not leave bytecode behind either.
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }
    });
    if (result.error === undefined && result.status === 0) return argv;
  }
  return undefined;
}

if (!existsSync(script)) {
  // A published extension folder has no repo around it; nothing to sync, and
  // failing here would break a build that is already complete.
  console.log(`sync-core: ${script} is not present — nothing to build`);
  process.exit(0);
}

const python = findPython();
if (python === undefined) {
  console.error(
    'sync-core: no Python 3.10+ on PATH, so the analyzer this extension ships\n' +
      '           cannot be built. vscode-extension/core/ is a gitignored build\n' +
      '           artifact (see the root .gitignore); install Python 3.10 or newer,\n' +
      '           or set MLVIEW_PYTHON to the interpreter to use, and re-run.'
  );
  process.exit(1);
}

const [command, ...prefix] = python;
const args = [...prefix, script, ...process.argv.slice(2)];
const result = spawnSync(command, args, {
  cwd: repoRoot,
  stdio: 'inherit',
  env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
});
if (result.error !== undefined) {
  console.error(`sync-core: could not run ${command}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
