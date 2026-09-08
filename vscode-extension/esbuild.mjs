// Build script for the MLView VS Code extension.
//   node esbuild.mjs           -> out/extension.js   (the extension bundle)
//   node esbuild.mjs --watch   -> the same, in watch mode
//   node esbuild.mjs --test    -> out/test-entry.cjs (pure modules, for node --test)
//
// The extension bundle follows the official VS Code recipe: CJS, platform node,
// `vscode` left external (it is supplied by the host at runtime).
import * as esbuild from 'esbuild';
import { fileURLToPath } from 'node:url';
import * as path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const testOnly = process.argv.includes('--test');

/** @type {import('esbuild').BuildOptions} */
const common = {
  bundle: true,
  format: 'cjs',
  platform: 'node',
  target: 'node20',
  external: ['vscode'],
  sourcemap: true,
  logLevel: 'info',
  absWorkingDir: here
};

/** @type {import('esbuild').BuildOptions} */
const extensionBuild = {
  ...common,
  entryPoints: ['src/extension.ts'],
  outfile: 'out/extension.js'
};

// A second bundle that re-exports the host-independent modules so `node --test`
// can exercise them with a mocked `vscode` module (see test/mock-vscode.js).
/** @type {import('esbuild').BuildOptions} */
const testBuild = {
  ...common,
  entryPoints: ['src/testEntry.ts'],
  outfile: 'out/test-entry.cjs',
  sourcemap: false
};

const targets = testOnly ? [testBuild] : [extensionBuild, testBuild];

if (watch) {
  const contexts = await Promise.all(targets.map((t) => esbuild.context(t)));
  await Promise.all(contexts.map((c) => c.watch()));
} else {
  await Promise.all(targets.map((t) => esbuild.build(t)));
}
