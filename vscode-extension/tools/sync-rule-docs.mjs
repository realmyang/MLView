// Copy the generated rule pages into the extension so they SHIP with it.
//
//   node tools/sync-rule-docs.mjs [--check]
//
// CONTRACTS.md §6 freezes a diagnostic's code as
// `{ value: "MLV201", target: Uri.joinPath(ctx.extensionUri, 'docs', 'rules', 'MLV201.md') }`
// — "a LOCAL file, so rule docs work offline". `<extensionPath>/docs/rules` is the only
// candidate that exists in a real install: the dev fallback `<parent>/docs/rules` resolves to
// `~/.vscode/extensions` once the extension is packaged. Without this step every diagnostic
// falls back to a bare string code, the Problems-panel rule code stops being a link, and
// `MLView: Open Rule Documentation` degrades to a one-line notification.
//
// Source of truth is `<repo>/docs/rules/MLV*.md`, written by analyzer/tools/gen_rule_docs.py.
// This script is wired into `npm run compile` and `npm run pretest`, so `scripts/build.ps1`
// picks it up for free. When the repo copy is absent (an installed extension, a source tarball)
// it warns and exits 0 — a missing generator must never fail a build.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(here, '..');
const repoDocs = path.resolve(extensionRoot, '..', 'docs', 'rules');
const shippedDocs = path.join(extensionRoot, 'docs', 'rules');
const check = process.argv.includes('--check');

const PAGE = /^MLV[0-9]{3}\.md$/;

function pages(dir) {
  try {
    return fs.readdirSync(dir).filter((name) => PAGE.test(name)).sort();
  } catch {
    return [];
  }
}

const source = pages(repoDocs);
if (source.length === 0) {
  console.warn(`sync-rule-docs: no rule pages under ${repoDocs} - nothing to sync`);
  process.exit(0);
}

fs.mkdirSync(shippedDocs, { recursive: true });

let copied = 0;
let removed = 0;
const drift = [];

for (const name of source) {
  const from = path.join(repoDocs, name);
  const to = path.join(shippedDocs, name);
  const want = fs.readFileSync(from);
  let have;
  try {
    have = fs.readFileSync(to);
  } catch {
    have = undefined;
  }
  if (have && have.equals(want)) {
    continue;
  }
  drift.push(name);
  if (!check) {
    fs.writeFileSync(to, want);
    copied += 1;
  }
}

// A rule that was withdrawn upstream must not keep a stale page in the package.
for (const name of pages(shippedDocs)) {
  if (source.includes(name)) {
    continue;
  }
  drift.push(`${name} (stale)`);
  if (!check) {
    fs.unlinkSync(path.join(shippedDocs, name));
    removed += 1;
  }
}

if (check) {
  if (drift.length > 0) {
    console.error(`sync-rule-docs: ${shippedDocs} is out of date: ${drift.join(', ')}`);
    process.exit(1);
  }
  console.log(`sync-rule-docs: ${source.length} rule page(s) up to date`);
  process.exit(0);
}

console.log(
  `sync-rule-docs: ${source.length} rule page(s) in ${path.relative(extensionRoot, shippedDocs)} ` +
    `(${copied} written, ${removed} removed)`
);
