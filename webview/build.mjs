/**
 * Build: src/main.ts -> dist/mlview.js (IIFE, global name MLView) and
 * src/styles/*.css -> dist/mlview.css, concatenated in a fixed order.
 *
 * Offline, no plugins, no network. The bundle must contain no innerHTML, no
 * eval, no dynamic import and no absolute URL — test/bundle.test.mjs enforces
 * that against the built file.
 */

import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, 'dist');

/** Order matters: tokens first, then the cascade layers. */
const CSS_FILES = [
  'tokens.css',
  'base.css',
  'chrome.css',
  'canvas.css',
  'node.css',
  'edge.css',
  'flow.css',
  'scope.css',
  'rail.css',
];

async function buildCss() {
  const parts = [];
  for (const name of CSS_FILES) {
    const text = await readFile(join(here, 'src', 'styles', name), 'utf8');
    parts.push('/* ---- ' + name + ' ---- */\n' + text.replace(/\r\n/g, '\n').trim() + '\n');
  }
  const css = parts.join('\n');
  await writeFile(join(dist, 'mlview.css'), css, 'utf8');
  return css.length;
}

async function main() {
  await mkdir(dist, { recursive: true });
  const result = await build({
    entryPoints: [join(here, 'src', 'main.ts')],
    bundle: true,
    format: 'iife',
    globalName: 'MLView',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    legalComments: 'none',
    sourcemap: false,
    charset: 'utf8',
    outfile: join(dist, 'mlview.js'),
    metafile: true,
    logLevel: 'warning',
  });
  const jsBytes = Object.values(result.metafile.outputs)[0].bytes;
  const cssBytes = await buildCss();
  process.stdout.write(
    'mlview.js  ' + (jsBytes / 1024).toFixed(1) + ' KB\n' + 'mlview.css ' + (cssBytes / 1024).toFixed(1) + ' KB\n',
  );
}

main().catch((err) => {
  process.stderr.write(String((err && err.stack) || err) + '\n');
  process.exit(1);
});
