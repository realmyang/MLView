/**
 * REV-02 / H2 — the third copy of §2.6 C9's subset rule, and the gate nobody
 * wrote for this host.
 *
 * CONTRACTS §2.6 C9 is normative and names four copies of one set:
 * `core.coverage.COVERAGE_KINDS` is the AUTHORITY and must be a **subset** of
 * the set each host reads; the copies are the core's,
 * `claude-plugin/server/mlview_notes.py::COVERAGE_KINDS`,
 * `vscode-extension/src/coverage.ts::COVERAGE_DIAGNOSTIC_KINDS` and
 * `webview/src/ui/chromenotes.ts::COVERAGE_KINDS`. Two gates enforce it —
 * `claude-plugin/tests/test_framework_suppression.py::test_every_kind_this_host_reads_is_one_the_core_or_this_host_emits`
 * and `vscode-extension/test/coverage.test.js` — and both are about the OTHER
 * two hosts. Nothing compared the viewer's copy against the analyzer, so when
 * C8 added `framework_filter` to the core's tuple the viewer silently did not
 * grow it, and every suite in this directory stayed green while the shipped
 * bundle broke the contract.
 *
 * MEASURED, before the fix, on a clean workspace analysed with
 * `--framework torch` (zero issues, one `framework_filter` diagnostic saying
 * five rules the detected frameworks would have run did not):
 *
 *   rail     "No issues found · 70 nodes across 7 stages checked — nothing to
 *             flag."                       ← the sentence hardening_cleanstate
 *                                            exists to forbid
 *   banners  none
 *   chips    one 287-character generic chip carrying the whole message, the
 *            chip-wall defect TAB2-10 fixed for `unresolved_callee`
 *
 * So this file is two things at once: the missing STRUCTURAL gate (read the
 * analyzer's declaration, never a transcription of it), and the behavioural
 * regression tests for the three surfaces that one constant drives — the chip
 * row, the coverage banner and the rail's clean state.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, REPO_ROOT } from './helpers.mjs';

const sample = await readSample();

const CORE_COVERAGE = join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'core', 'coverage.py');

/**
 * The analyzer's own declaration, read out of the source.
 *
 * The plugin's gate imports the module and the extension's reads its sibling
 * TypeScript; a Node test cannot import Python, so it parses the one tuple —
 * which is still the analyzer's text rather than a copy of it kept in step by
 * hand. A shape this parser cannot read is a FAILURE, never a skip: a gate that
 * quietly stops checking is the thing this file is here to prevent.
 */
async function coreCoverageKinds() {
  const src = await readFile(CORE_COVERAGE, 'utf8');
  const decl = /^COVERAGE_KINDS\s*=\s*\(([\s\S]*?)\)/m.exec(src);
  assert.ok(decl, 'core/coverage.py no longer declares COVERAGE_KINDS as a tuple literal — ' + 'teach this gate its new shape rather than deleting it');
  const kinds = (decl[1].match(/"[^"]+"|'[^']+'/g) || []).map((q) => q.slice(1, -1));
  assert.ok(kinds.length > 0, 'the analyzer declares an empty coverage set: ' + decl[1]);
  return kinds;
}

/**
 * The viewer's copy, taken from the BUILT bundle, which is what ships.
 *
 * Copied into an array of THIS realm: the bundle is evaluated inside a jsdom
 * window, so its arrays carry that realm's `Array.prototype` and a strict deep
 * comparison against a literal here fails on the prototype alone.
 */
async function viewerCoverageKinds() {
  const ctx = await loadBundle();
  return Array.from(ctx.MLView.__internal.chrome.coverageKinds, (kind) => String(kind));
}

/* ── the gate §2.6 C9 implies ───────────────────────────────────────────── */

test('the viewer reads every coverage kind the core emits (CONTRACTS §2.6 C9)', async () => {
  const core = await coreCoverageKinds();
  const viewer = await viewerCoverageKinds();
  const missing = core.filter((kind) => viewer.indexOf(kind) < 0);
  assert.deepEqual(
    missing,
    [],
    'a kind the analyzer emits as coverage and this host drops is a caveat the reader never ' +
      'sees: it falls through collectChips\' generic branch as a paragraph-long chip, never ' +
      'reaches the coverage banner, and never qualifies the rail\'s clean state. core=' +
      JSON.stringify(core) + ' viewer=' + JSON.stringify(viewer),
  );
});

test('each EXTRA kind the viewer lists is one the contract names (§17 E40)', async () => {
  const core = await coreCoverageKinds();
  const viewer = await viewerCoverageKinds();
  // `unresolved_callee` is the viewer's own, and §10.8 A5 is where it is named.
  // The rule is a subset and not an equality on purpose — but a list nobody can
  // explain is still a drift.
  assert.deepEqual(viewer.filter((kind) => core.indexOf(kind) < 0), ['unresolved_callee']);
});

test('the core tuple this gate reads is the one C8 shipped', async () => {
  // Belt and braces: if the parser above ever matched the wrong assignment it
  // would pass a subset check against an empty or unrelated list.
  const core = await coreCoverageKinds();
  assert.deepEqual([...core].sort(), ['framework_filter', 'single_file_analysis', 'untagged_dataflow']);
});

/* ── the three surfaces that constant drives ────────────────────────────── */

const FILTER_MESSAGE =
  '--framework torch narrowed the rule set: 5 rule(s) that the detected frameworks would have ' +
  'run did not (MLV103, MLV205, MLV301, MLV402, MLV501). A clean result here is a clean result ' +
  'for torch alone - drop --framework (or pass auto) to judge the whole workspace.';

const FILTER = {
  kind: 'framework_filter',
  message: FILTER_MESSAGE,
  codes: ['MLV103', 'MLV205', 'MLV301', 'MLV402', 'MLV501'],
  count: 5,
};

function graphWith(diagnostics, { clean = false } = {}) {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.diagnostics = diagnostics;
  if (clean) graph.issues = [];
  return graph;
}

async function mount(graph) {
  const ctx = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return ctx;
}

test('the caveat draws as a SHORT coverage chip, not as the whole message', async () => {
  const ctx = await mount(graphWith([FILTER]));
  const chip = ctx.document.querySelector('[data-coverage="framework_filter"]');
  assert.ok(chip, 'the framework filter must take the COVERAGE branch of collectChips');
  assert.ok(chip.className.indexOf('mlv-chip--coverage') >= 0, chip.className);
  const text = chip.textContent;
  assert.ok(text.indexOf('--framework torch') >= 0, text);
  assert.ok(/\b5 rules not run\b/.test(text), text);
  // TAB2-10's bound: a chip is a LABEL. The 287-character message is what the
  // generic branch used to draw here.
  assert.ok(text.length <= 48, 'chip text is ' + text.length + ' characters: ' + text);
  // ...and the sentence is still one hover away, word for word.
  assert.equal(chip.getAttribute('title'), FILTER_MESSAGE);
  assert.equal(ctx.document.querySelector('[data-diagnostic-kind="framework_filter"]'), null);
});

test('the caveat reaches the coverage banner, headline and sentence both', async () => {
  const ctx = await mount(graphWith([FILTER]));
  const banner = ctx.document.querySelector('[data-coverage-banner]');
  assert.ok(banner, 'a document whose only coverage kind is framework_filter had no banner at all');
  assert.equal(banner.getAttribute('data-coverage-banner'), '1');
  const text = banner.textContent;
  assert.ok(text.indexOf('Coverage: 5 rules the detected frameworks would have run were not run under --framework torch') >= 0, text);
  assert.ok(text.indexOf('not a clean bill of health') >= 0, text);
  // The analyzer's own sentence is the detail, verbatim.
  assert.ok(text.indexOf(FILTER_MESSAGE) >= 0, text);
});

test('a zero-issue run behind --framework never reads "nothing to flag"', async () => {
  const ctx = await mount(graphWith([FILTER], { clean: true }));
  const clean = ctx.document.querySelector('.mlv-clean');
  assert.ok(clean, 'the clean state still draws');
  const text = clean.textContent.replace(/\s+/g, ' ').trim();
  assert.doesNotMatch(
    text,
    /nothing to flag\.?\s*$/,
    'the rail ended on "nothing to flag" over a run that withheld five rules: ' + text,
  );
  assert.equal(clean.querySelector('[data-clean-coverage]').getAttribute('data-clean-coverage'), '1');
  assert.ok(text.indexOf('--framework torch') >= 0, text);
  assert.ok(text.indexOf('5 rules') >= 0, text);
});

test('the rules count is never folded into a blind-SITE total (§2.6 C9)', async () => {
  // `count` on this kind is suppressed RULE CODES. A headline that added five
  // rules to two untraced values and said "7 values" would be a number nobody
  // can check, and the contract forbids it in as many words.
  const ctx = await mount(
    graphWith([
      FILTER,
      { kind: 'untagged_dataflow', message: 'make_splits(X, y): X reached train_test_split untagged.', file: 'data.py', line: 12, count: 2 },
    ]),
  );
  const text = ctx.document.querySelector('[data-coverage-banner]').textContent;
  assert.ok(text.indexOf('2 values reaching a fit or split could not be traced') >= 0, text);
  assert.ok(text.indexOf('5 rules the detected frameworks would have run') >= 0, text);
  assert.ok(text.indexOf('7 values') < 0, text);
});

test('the chip states the cost even when the message no longer opens with the flag', async () => {
  // The framework NAME lives only in the prose, so the chip degrades to a
  // shorter TRUE chip rather than to a wrong one if that prose is reworded.
  const ctx = await mount(graphWith([{ ...FILTER, message: 'The rule set was narrowed: 5 rule(s) did not run.' }]));
  const chip = ctx.document.querySelector('[data-coverage="framework_filter"]');
  assert.equal(chip.textContent, '5 rules not run');
});

test('a run with no framework filter grows no clause and no chip', async () => {
  const ctx = await mount(graphWith([], { clean: true }));
  assert.equal(ctx.document.querySelector('[data-coverage="framework_filter"]'), null);
  assert.equal(ctx.document.querySelector('[data-coverage-banner]'), null);
  const clean = ctx.document.querySelector('.mlv-clean').textContent;
  assert.ok(clean.indexOf('nothing to flag') >= 0, clean);
  assert.ok(clean.indexOf('--framework') < 0, clean);
});
