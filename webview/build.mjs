/**
 * Build: src/main.ts -> dist/mlview.js (IIFE, global name MLView) and
 * src/styles/*.css -> dist/mlview.css, concatenated in a fixed order and
 * MINIFIED (BUILD-01). Nothing else is written: the readable
 * `dist/mlview.dev.css` had no remaining consumer and is no longer produced
 * (CRIT-10).
 *
 * Offline, no plugins, no network. The bundle must contain no innerHTML, no
 * outerHTML, no insertAdjacentHTML, no document.write, no eval, no new
 * Function, no dynamic import and no absolute URL; test/bundle.test.mjs
 * checks that against the built dist/mlview.js.
 */

import { build, transform } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dist = join(here, 'dist');

/** Order matters: tokens first, then the cascade layers. */
const CSS_FILES = [
  'tokens.css',
  'base.css',
  // The chrome is three layers, in this order and no other: the header row,
  // the menu, search and the status bar, then the transient toast and
  // empty-state surfaces, then the panels.
  'chrome.css',
  'chromestates.css',
  'chromepanels.css',
  'canvas.css',
  'node.css',
  'edge.css',
  'flow.css',
  'rail.css',
  // Viewer M3: the phase index and the phase overview, overlays inside the canvas.
  'overview.css',
  // PERF-04. After `edge.css`, because `.mlv-edge--weighted .mlv-edge__path`
  // has the same specificity as the per-kind stroke rules and has to win on
  // source order.
  'weight.css',
  // The authored-workflow panel and host banner. Before `export.css`, so the
  // print block keeps the last word (RENDER-21).
  'workflow.css',
  // VIEW-07, and LAST on purpose: it carries the `@media print` block, whose
  // `!important` overrides have to win over every layer above it.
  'export.css',
];

/** The ONE transform the shipped stylesheet goes through (BUILD-01). */
export async function minifyCss(source) {
  const result = await transform(source, { loader: 'css', minify: true });
  return result.code;
}

/**
 * The stylesheet ships minified: the layers are concatenated in `CSS_FILES`
 * order and minified once. `tools/sync-assets.py` copies `mlview.js` and
 * `mlview.css` to the extension.
 */
async function buildCss() {
  const parts = [];
  for (const name of CSS_FILES) {
    const text = await readFile(join(here, 'src', 'styles', name), 'utf8');
    parts.push('/* ---- ' + name + ' ---- */\n' + text.replace(/\r\n/g, '\n').trim() + '\n');
  }
  const source = parts.join('\n');
  const minified = await minifyCss(source);
  await writeFile(join(dist, 'mlview.css'), minified, 'utf8');
  return { bytes: minified.length, sourceBytes: source.length };
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
  const css = await buildCss();
  const cut = ((css.sourceBytes - css.bytes) / css.sourceBytes) * 100;
  process.stdout.write(
    'mlview.js  ' + (jsBytes / 1024).toFixed(1) + ' KB\n' +
      'mlview.css ' + (css.bytes / 1024).toFixed(1) + ' KB  (minified from ' +
      (css.sourceBytes / 1024).toFixed(1) + ' KB, -' + cut.toFixed(0) + '%)\n',
  );
}

// `import { minifyCss }` must not run a build, so only a direct invocation does.
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  main().catch((err) => {
    process.stderr.write(String((err && err.stack) || err) + '\n');
    process.exit(1);
  });
}
