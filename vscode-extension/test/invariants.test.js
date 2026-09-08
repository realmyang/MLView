'use strict';
/**
 * Invariants that are asserted over the SOURCE, because they are the kind of thing a future
 * edit silently breaks while every behavioural test stays green.
 *
 *   1. CONTRACTS.md §0: "Convert exactly once, at the host boundary." src/location.ts says the
 *      same in its header. Three modules used to do their own `line - 1` arithmetic anyway.
 *   2. CONTRACTS.md §6 freezes `code.target` as a LOCAL file, so the rule pages must actually
 *      ship inside the extension - `<parent-of-extensionPath>/docs/rules` only exists in a dev
 *      checkout, never in an installed `.vsix`.
 *   3. `vscode.WebviewPanel` has a `title` and NO `description` (that member is on
 *      `WebviewView`), so the README must not promise a subtitle beside the panel title. The
 *      scoped node count is drawn by the viewer's own breadcrumb, inside the panel.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', 'src');
const README = path.join(__dirname, '..', 'README.md');
const EXTENSION_DOCS = path.join(__dirname, '..', 'docs', 'rules');
const REPO_DOCS = path.join(__dirname, '..', '..', 'docs', 'rules');

/** `loc.line - 1`, `anchor.line - 1`, `editor.selection.active.line + 1`, ... */
const CONVERSION = /[A-Za-z_.]*line\s*\)?\s*[-+]\s*1\b/i;
const RULE_PAGE = /^MLV[0-9]{3}\.md$/;

test('only location.ts converts between graph lines and editor lines', () => {
  const offenders = [];
  for (const name of fs.readdirSync(SRC)) {
    if (!name.endsWith('.ts') || name === 'location.ts') {
      continue;
    }
    const lines = fs.readFileSync(path.join(SRC, name), 'utf8').split(/\r?\n/);
    lines.forEach((line, i) => {
      if (CONVERSION.test(line)) {
        offenders.push(`${name}:${i + 1}: ${line.trim()}`);
      }
    });
  }
  assert.deepEqual(
    offenders,
    [],
    'route these through toRangeTuple / toEditorLine / toGraphLine in src/location.ts:\n' +
      offenders.join('\n')
  );
});

test('location.ts really is where the conversion lives', () => {
  const text = fs.readFileSync(path.join(SRC, 'location.ts'), 'utf8');
  assert.ok(CONVERSION.test(text), 'the conversion must exist somewhere');
  assert.match(text, /export function toEditorLine/);
  assert.match(text, /export function toGraphLine/);
});

test('every generated rule page ships inside the extension, not just in the repo', () => {
  const shipped = fs.readdirSync(EXTENSION_DOCS).filter((n) => RULE_PAGE.test(n)).sort();
  assert.ok(shipped.length >= 14, `expected the generated rule pages, found ${shipped.length}`);
  assert.ok(
    fs.existsSync(path.join(EXTENSION_DOCS, 'README.md')),
    'the directory README explains the mechanism and must survive the sync'
  );
  for (const name of shipped) {
    const text = fs.readFileSync(path.join(EXTENSION_DOCS, name), 'utf8');
    assert.ok(text.length > 200, `${name} looks truncated`);
    assert.ok(text.includes(name.replace('.md', '')), `${name} must document its own code`);
  }

  if (!fs.existsSync(REPO_DOCS)) {
    return; // a packaged tree has no repo copy; the pages above are what matters
  }
  const upstream = fs.readdirSync(REPO_DOCS).filter((n) => RULE_PAGE.test(n)).sort();
  assert.deepEqual(
    shipped,
    upstream,
    'run `npm run sync:rule-docs` - the extension copy has drifted from docs/rules/'
  );
  for (const name of upstream) {
    assert.equal(
      fs.readFileSync(path.join(EXTENSION_DOCS, name), 'utf8'),
      fs.readFileSync(path.join(REPO_DOCS, name), 'utf8'),
      `${name} differs from the generated page`
    );
  }
});

test('.vscodeignore keeps docs/ in the package and the sync script out of it', () => {
  const ignore = fs
    .readFileSync(path.join(__dirname, '..', '.vscodeignore'), 'utf8')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  assert.ok(
    !ignore.some((line) => /^docs/.test(line)),
    'docs/** must stay in the package - the rule docs are the offline code.target'
  );
  assert.ok(ignore.includes('tools/**'), 'the build-time sync script is not shipped');
});

test('the rule-doc sync is wired into the build, not a manual step', () => {
  const scripts = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8')
  ).scripts;
  assert.match(scripts.compile, /sync-rule-docs/, 'scripts/build.ps1 runs `npm run compile`');
  assert.match(scripts.pretest, /sync-rule-docs/);
  assert.ok(fs.existsSync(path.join(__dirname, '..', 'tools', 'sync-rule-docs.mjs')));
});

// -------------------------------------------------------------- 3. the panel has no subtitle

test('the README does not promise a node count beside the panel title', () => {
  const text = fs.readFileSync(README, 'utf8');
  assert.doesNotMatch(
    text,
    /beside the (panel )?title/i,
    'vscode.WebviewPanel has no `description`: a scoped count can only be drawn inside the panel'
  );
  const scoping = text.slice(text.indexOf('### Scoping the diagram'));
  assert.match(
    scoping,
    /breadcrumb/,
    'the scoping section must say where the `N of M nodes` count really appears'
  );
});

test('src/panel.ts is honest about the WebviewPanel cast', () => {
  const text = fs.readFileSync(path.join(SRC, 'panel.ts'), 'utf8');
  // The §11.11 assignment stays; what must not rot is the comment that says VS Code ignores it.
  assert.match(text, /description\?: string \}\)\.description/, 'the §11.11 assignment must stay');
  assert.match(
    text,
    /`description` is declared on `WebviewView`, not on `WebviewPanel`/,
    'keep the note explaining why the cast is not a rendered subtitle'
  );
});
