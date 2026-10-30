#!/usr/bin/env node
// The key table of docs/user-guide.md, from the viewer's key map.
//
//   node tools/keys-table.mjs            # print the table
//   node tools/keys-table.mjs --check    # compare it with the table in docs/user-guide.md
//
// The table has one row for each binding of `KEYMAP` in src/ui/keymap.ts, in the order of the
// array: the keys as code spans, then the description. docs/user-guide.md holds the table between
// the lines `<!-- keys:begin -->` and `<!-- keys:end -->`. After a change of the key map, replace
// the lines between the two markers with what this tool prints. The tool writes no file.
//
// src/ui/keymap.ts imports nothing, so one esbuild transform of that one file gives a module that
// Node can import. The tool reads the source and not the built bundle, so it needs no build.
// test/keys-table.test.mjs compares the guide's table with this one, and the key map with the
// shortcut sheet of the built viewer. No file under src/ imports this tool, so it is not in the
// bundle.
//
// Exit status: 0 the table was printed, or the guide's table equals it; 1 the guide's table
// differs, or the guide has no table between the two markers; 2 the tool could not run.

import { readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const WEBVIEW_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const KEYMAP_FILE = join(WEBVIEW_ROOT, 'src', 'ui', 'keymap.ts');
export const GUIDE_FILE = join(WEBVIEW_ROOT, '..', 'docs', 'user-guide.md');
export const BEGIN = '<!-- keys:begin -->';
export const END = '<!-- keys:end -->';

const USAGE = 'Usage: node tools/keys-table.mjs [--check]\n'
  + '  no option   print the key table, as Markdown, from src/ui/keymap.ts\n'
  + '  --check     compare that table with the one in docs/user-guide.md\n';

/** `KEYMAP` of src/ui/keymap.ts: the bindings in their order, each with its `keys` and its `description`. */
export async function readKeyMap() {
  const { transformSync } = await import('esbuild');
  const { code } = transformSync(readFileSync(KEYMAP_FILE, 'utf8'), { loader: 'ts', format: 'esm' });
  const { KEYMAP } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
  if (!Array.isArray(KEYMAP) || KEYMAP.length === 0) throw new Error('src/ui/keymap.ts exports no KEYMAP array');
  return KEYMAP;
}

/** The table as Markdown, one line for each row and no newline at the end. */
export function keyTable(keymap) {
  const cell = (text) => String(text).replace(/\|/g, '\\|');
  return [
    '| Keys | What they do |',
    '|---|---|',
    ...keymap.map((binding) => `| ${binding.keys.map((key) => '`' + cell(key) + '`').join(', ')} | ${cell(binding.description)} |`),
  ].join('\n');
}

/** The lines of a guide between its two markers, or null when it does not hold both, in that order. */
export function guideTable(text) {
  const lines = text.split(/\r?\n/);
  const begin = lines.indexOf(BEGIN);
  const end = lines.indexOf(END, begin + 1);
  return begin < 0 || end < 0 ? null : lines.slice(begin + 1, end).join('\n');
}

/** What the command prints for `argv`, and its exit status. */
export async function run(argv) {
  if (argv.includes('--help')) return { text: USAGE, status: 0 };
  const unknown = argv.find((arg) => arg !== '--check');
  if (unknown !== undefined) throw new Error('unknown argument ' + unknown + '\n' + USAGE.trimEnd());
  const keymap = await readKeyMap();
  const table = keyTable(keymap);
  if (!argv.includes('--check')) return { text: table + '\n', status: 0 };
  const guide = guideTable(readFileSync(GUIDE_FILE, 'utf8'));
  if (guide === null) {
    return { text: `keys-table: docs/user-guide.md has no table between ${BEGIN} and ${END}\n`, status: 1 };
  }
  const have = guide.split('\n');
  const want = table.split('\n');
  const differing = [];
  for (let line = 0; line < Math.max(have.length, want.length); line += 1) {
    if (have[line] !== want[line]) differing.push(line + 1);
  }
  if (differing.length === 0) {
    return { text: `keys-table: the key table of docs/user-guide.md equals the key map (${keymap.length} rows)\n`, status: 0 };
  }
  const first = differing[0];
  return {
    text: `keys-table: the key table of docs/user-guide.md differs from the key map in ${differing.length} line(s); the first is line ${first} of the table\n`
      + `  the guide:   ${have[first - 1] ?? '(no line)'}\n`
      + `  the key map: ${want[first - 1] ?? '(no line)'}\n`,
    status: 1,
  };
}

// Node resolves the entry file's symlinks for import.meta.url and leaves process.argv[1] as typed,
// so the two are compared as real paths.
function invokedDirectly() {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(resolve(process.argv[1]));
  } catch {
    return false;
  }
}

if (invokedDirectly()) {
  try {
    const result = await run(process.argv.slice(2));
    process.stdout.write(result.text);
    process.exitCode = result.status;
  } catch (err) {
    process.stderr.write('keys-table: cannot run: ' + (err && err.message ? err.message : String(err)) + '\n');
    process.exitCode = 2;
  }
}
