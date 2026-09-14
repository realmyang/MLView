/**
 * Hardening round 1, area hosts-ux — the rail's clean state is the one surface
 * that still says "nothing to flag" about a run that was blind.
 *
 * The standing criterion is *never look clean when you were blind*, and every
 * other surface honours it. On `karpathy/nanoGPT` (pinned public corpus), the
 * report carries `untagged_dataflow` x2, `unresolved_callee` and
 * `notebook_skipped`, and says so three times:
 *
 *   banner   "Coverage: 2 values reaching a fit or split could not be traced.
 *             A clean result here is not a clean bill of health."
 *   banner   "Partial understanding: some calls could not be resolved …"
 *   answers  the verdict appends the coverage caveat (CONTRACTS 11.22 P7)
 *
 * and then the Issues rail — the panel a reviewer reads first — says, with
 * nothing beside it:
 *
 *   "No issues found · 213 nodes across 8 stages checked — nothing to flag."
 *
 * Measured the same way on `adv_advanced_clean` (5 coverage diagnostics, 155
 * nodes) and `tabular_feature_store` (4, 29 nodes). The VS Code host already
 * computes the sentence for its own surfaces (`src/coverage.ts`:
 * `coverage: incomplete (N blind spots)`); the viewer's rail does not.
 *
 * `cleanState()` (`src/ui/issuelist.ts`) never reads `graph.diagnostics` —
 * while `nothingAnalyzedState()`, twenty lines below it, lists them. The fix is
 * to make the clean state do what its neighbour already does.
 *
 * The two assertions that fail today are `todo`, so the suite's exit code still
 * reports the state of everything else; the fix is to delete the option.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

/** The shipped clean twin's shape: a real graph with its issues removed. */
function cleanGraph(diagnostics = []) {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues = [];
  graph.diagnostics = diagnostics;
  return graph;
}

const COVERAGE = [
  {
    kind: 'untagged_dataflow',
    message:
      'train.py:84 — the loop at train.py:84 contains backward() and an optimizer step, but MLView ' +
      'could not confirm it as a training loop: MLV201 / MLV202 / MLV203 did not judge it.',
    file: 'train.py',
    line: 84,
    count: 2,
  },
  {
    kind: 'unresolved_callee',
    message: 'MLView could not resolve 2 calls in sample: `encode(…)` at line 80 is a lambda.',
    file: 'sample.py',
    line: 80,
    count: 2,
  },
  { kind: 'notebook_skipped', message: '2 notebooks were not analyzed.', count: 2 },
];

async function railText(graph) {
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
  const panel = ctx.document.querySelector('.mlv-rail__panel');
  return {
    ctx,
    text: (panel ? panel.textContent : '').replace(/\s+/g, ' ').trim(),
    clean: ctx.document.querySelector('.mlv-clean'),
  };
}

test('the premise: a zero-issue document draws the clean state and says so', async () => {
  const { text, clean } = await railText(cleanGraph());
  assert.ok(clean, 'a document with no findings must draw the clean state');
  assert.match(text, /No issues found/);
  assert.match(text, /nothing to flag/);
});

test(
  'a clean result over a BLIND run never reads as a clean bill of health',
  { todo: 'HOSTS-UX-CLEANSTATE: ui/issuelist.ts cleanState() ignores graph.diagnostics' },
  async () => {
    const { text } = await railText(cleanGraph(COVERAGE));
    assert.doesNotMatch(
      text,
      /nothing to flag\.?\s*$/,
      'the clean state ended on "nothing to flag" over a document carrying 3 coverage diagnostics',
    );
    assert.match(
      text,
      /coverage|could not|blind|not a clean bill/i,
      'the rail must name the blind spots; a banner elsewhere on the page is not the panel a ' +
        'reviewer reads first',
    );
  },
);

test(
  'the clean state names how many blind spots there were, the way the VS Code chip does',
  { todo: 'HOSTS-UX-CLEANSTATE: ui/issuelist.ts cleanState() ignores graph.diagnostics' },
  async () => {
    const { text } = await railText(cleanGraph(COVERAGE));
    // 2 + 2 + 2 = 6 sites across the three diagnostics; any honest count is fine,
    // silence is not.
    assert.match(text, /\b[1-9]\d*\b(?=[^.]*(gap|blind|untraced|could not))/i, text);
  },
);

test('a clean result over a run with NO diagnostics is still allowed to be good news', async () => {
  const { text } = await railText(cleanGraph());
  assert.match(text, /nothing to flag/, 'an unqualified clean result must survive the fix');
  assert.doesNotMatch(text, /coverage|blind/i, 'and must not grow a caveat it has no evidence for');
});

test('the "nothing analyzed" state already lists its diagnostics — the pattern to copy', async () => {
  const graph = cleanGraph(COVERAGE);
  graph.nodes = [];
  graph.edges = [];
  graph.workspace.filesAnalyzed = 0;
  const { ctx, text } = await railText(graph);
  const empty = ctx.document.querySelector('.mlv-empty-note');
  if (!empty) return; // a different zero-state was chosen; the clean-state tests are the gate
  assert.match(text, /Nothing analyzed/);
  assert.match(text, /untagged_dataflow|unresolved_callee|notebook_skipped/);
});
