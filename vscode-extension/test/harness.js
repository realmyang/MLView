'use strict';
/**
 * Loads the bundled extension modules with `vscode` redirected to the mock.
 *
 * `node esbuild.mjs --test` (the `pretest` npm script) bundles src/testEntry.ts to
 * out/test-entry.cjs with `--external:vscode`, so the bundle contains a literal
 * `require("vscode")` that this Module._resolveFilename hook intercepts.
 */

const Module = require('node:module');
const path = require('node:path');
const fs = require('node:fs');

const MOCK = path.join(__dirname, 'mock-vscode.js');
const BUNDLE = path.join(__dirname, '..', 'out', 'test-entry.cjs');

if (!Module.__mlviewHookInstalled) {
  const original = Module._resolveFilename;
  Module._resolveFilename = function (request, ...rest) {
    if (request === 'vscode') {
      return MOCK;
    }
    return original.call(this, request, ...rest);
  };
  Module.__mlviewHookInstalled = true;
}

if (!fs.existsSync(BUNDLE)) {
  throw new Error(
    `${BUNDLE} is missing. Run "npm run pretest" (or "node esbuild.mjs --test") before "node --test".`
  );
}

const api = require(BUNDLE);
const vscode = require(MOCK);

const REPO_ROOT = path.resolve(__dirname, '..', '..');

module.exports = { api, vscode, REPO_ROOT, MOCK, BUNDLE };
