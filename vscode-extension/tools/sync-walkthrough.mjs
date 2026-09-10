// MLV-P11 — copy the walkthrough pages into the extension so they SHIP with it.
//
//   node tools/sync-walkthrough.mjs [--check]
//
// `contributes.walkthroughs[].steps[].media.markdown` is resolved relative to the EXTENSION
// root, so a step whose page lives only in `<repo>/docs/walkthrough` renders as an empty panel
// in a packaged install — the same failure `tools/sync-rule-docs.mjs` exists to prevent for the
// rule pages, and this script is that one's twin down to the `--check` mode.
//
// Source of truth is `<repo>/docs/walkthrough/*.md`; the copies under
// `vscode-extension/docs/walkthrough/` are generated and must never be hand-edited. When the
// repo copy is absent (an installed extension, a source tarball) it warns and exits 0 — a
// missing source must never fail a build.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(here, '..');
const repoPages = path.resolve(extensionRoot, '..', 'docs', 'walkthrough');
const shippedPages = path.join(extensionRoot, 'docs', 'walkthrough');
const check = process.argv.includes('--check');

const PAGE = /^[a-z][a-z0-9-]*\.md$/;

function pages(dir) {
  if (!fs.existsSync(dir)) {
    return [];
  }
  return fs
    .readdirSync(dir)
    .filter((name) => PAGE.test(name))
    .sort();
}

/** The step ids the manifest declares, so a page nobody references is caught here. */
function declaredSteps() {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8')
  );
  const walkthroughs = manifest.contributes?.walkthroughs ?? [];
  return walkthroughs
    .flatMap((w) => w.steps ?? [])
    .map((s) => s.media?.markdown)
    .filter((p) => typeof p === 'string')
    .map((p) => path.basename(p))
    .sort();
}

const source = pages(repoPages);
if (source.length === 0) {
  console.warn(`sync-walkthrough: no pages in ${repoPages}; nothing to do.`);
  process.exit(0);
}

const declared = declaredSteps();
const missing = declared.filter((name) => !source.includes(name));
if (missing.length > 0) {
  console.error(
    `sync-walkthrough: package.json references ${missing.join(', ')}, which do not exist in ${repoPages}`
  );
  process.exit(1);
}

fs.mkdirSync(shippedPages, { recursive: true });
let stale = 0;
for (const name of source) {
  const from = path.join(repoPages, name);
  const to = path.join(shippedPages, name);
  const wanted = fs.readFileSync(from, 'utf8');
  const current = fs.existsSync(to) ? fs.readFileSync(to, 'utf8') : null;
  if (current === wanted) {
    continue;
  }
  stale += 1;
  if (!check) {
    fs.writeFileSync(to, wanted, 'utf8');
  }
}

// A page that was deleted upstream must not linger in the package.
for (const name of pages(shippedPages)) {
  if (source.includes(name)) {
    continue;
  }
  stale += 1;
  if (!check) {
    fs.rmSync(path.join(shippedPages, name));
  }
}

if (check && stale > 0) {
  console.error(
    `sync-walkthrough: ${stale} page(s) differ from ${repoPages}. Run "node tools/sync-walkthrough.mjs".`
  );
  process.exit(1);
}
console.log(
  check
    ? `sync-walkthrough: ${source.length} page(s) up to date`
    : `sync-walkthrough: ${source.length} page(s) synced (${stale} written)`
);
