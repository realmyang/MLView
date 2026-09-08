/**
 * MLV-P6 ("show the evidence") and RAIL-GROUP ("group findings by rule").
 *
 * Two trust artifacts were computed, shipped in the JSON and never rendered:
 * all 15 sample findings carry 3–5 evidence factors of real substance, and
 * `evidence` appeared exactly once in `webview/src` — its own type declaration.
 * The bucket chip was drawn only for `possible` / `speculative`. And the rule
 * documentation could not be reached from the standalone report at all.
 *
 * RAIL-GROUP: 113 rows / 6334 px in an 830 px panel, from 12 distinct codes.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample, makeSyntheticGraph } from './helpers.mjs';

const sample = await readSample();

async function mount(graph = sample, state = null) {
  const ctx = await loadBundle();
  const saved = [];
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: (s) => saved.push(s),
    loadState: () => state,
  };
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app: instance, saved, panel: ctx.document.querySelector('[id$="-panel-issues"]') };
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

const rowOf = (ctx, id) => ctx.document.querySelector('.mlv-issue[data-issue-id="' + id + '"]');

/* ── MLV-P6: the chip on every row ─────────────────────────────────────── */

test('every rail row shows its bucket chip, in all four buckets (MLV-P6)', async () => {
  const graph = JSON.parse(JSON.stringify(sample));
  const buckets = ['certain', 'likely', 'possible', 'speculative'];
  graph.issues.forEach((issue, i) => {
    issue.confidenceBucket = buckets[i % 4];
  });
  const ctx = await mount(graph);
  const rows = ctx.document.querySelectorAll('.mlv-issue[data-issue-id]');
  assert.ok(rows.length >= 4, rows.length + ' rows');
  const seen = new Set();
  for (const row of rows) {
    const chip = row.querySelector('.mlv-chip--conf');
    assert.ok(chip, 'a row with no confidence chip: ' + row.getAttribute('data-issue-id'));
    seen.add(chip.getAttribute('data-confidence'));
    assert.ok(chip.getAttribute('aria-label').indexOf('Confidence: ') === 0, chip.getAttribute('aria-label'));
  }
  for (const bucket of buckets) assert.ok(seen.has(bucket), 'no row rendered ' + bucket);
});

test('an unknown bucket renders generically instead of throwing (invariant 1.1/6)', async () => {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues[0].confidenceBucket = 'wildly-confident';
  const ctx = await mount(graph);
  const chip = rowOf(ctx, graph.issues[0].id).querySelector('.mlv-chip--conf');
  assert.equal(chip.getAttribute('data-confidence'), 'unknown');
  assert.equal(chip.textContent, 'wildly-confident', 'and it still says what the document said');
});

/* ── MLV-P6: the evidence checklist ────────────────────────────────────── */

test('an expanded row lists its evidence factors verbatim (MLV-P6)', async () => {
  const ctx = await mount();
  const issue = sample.issues.find((i) => (i.evidence || []).length >= 3);
  assert.ok(issue, 'the sample ships findings with evidence');
  click(ctx, rowOf(ctx, issue.id));
  const box = ctx.document.querySelector('[data-evidence-for="' + issue.id + '"]');
  assert.ok(box, 'the disclosure exists');
  assert.equal(box.tagName, 'DETAILS', 'progressive disclosure, never permanently expanded');
  assert.equal(box.hasAttribute('open'), false, 'collapsed until asked, or a 111-row rail drowns');
  const list = box.querySelector('.mlv-ev');
  assert.equal(Number(list.getAttribute('data-evidence-count')), issue.evidence.length);
  const items = list.querySelectorAll('.mlv-ev__item');
  assert.equal(items.length, issue.evidence.length);
  issue.evidence.forEach((factor, i) => {
    assert.equal(items[i].getAttribute('data-evidence-kind'), factor.kind);
    assert.ok(items[i].textContent.indexOf(factor.detail) >= 0, 'the detail text, verbatim: ' + factor.detail);
    const weight = items[i].querySelector('.mlv-ev__weight');
    assert.equal(weight.getAttribute('data-weight'), factor.weight.toFixed(2), 'and a weight indicator');
    assert.ok(weight.querySelector('.mlv-ev__bar'), 'shown as a bar as well as a number');
  });
});

test('the Inspector carries the same evidence and rule card (MLV-P6)', async () => {
  const ctx = await mount();
  const issue = sample.issues.find((i) => (i.evidence || []).length >= 2);
  ctx.app.focusIssue(issue.id);
  const inspector = ctx.document.querySelector('[id$="-panel-inspector"]');
  const box = inspector.querySelector('.mlv-insp__issue[data-issue-id="' + issue.id + '"]');
  assert.ok(box, 'the Inspector shows the issue');
  assert.ok(box.querySelector('[data-evidence-for="' + issue.id + '"]'), 'with its evidence');
  assert.ok(box.querySelector('[data-rule-doc="' + issue.code + '"]'), 'and its rule card');
  assert.ok(box.querySelector('.mlv-chip--conf'), 'and its bucket chip');
});

test('a finding with no evidence grows no empty twisty (MLV-P6)', async () => {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues[0].evidence = [];
  const ctx = await mount(graph);
  click(ctx, rowOf(ctx, graph.issues[0].id));
  assert.equal(ctx.document.querySelector('[data-evidence-for="' + graph.issues[0].id + '"]'), null);
  assert.ok(ctx.document.querySelector('[data-issue-detail="' + graph.issues[0].id + '"]'), 'the row still expands');
});

/* ── MLV-P6: the rule-doc sidecar and its hook ─────────────────────────── */

test('the rule card is composed from the finding when no sidecar exists (MLV-P6)', async () => {
  const ctx = await mount();
  const issue = sample.issues[0];
  click(ctx, rowOf(ctx, issue.id));
  const card = ctx.document.querySelector('[data-rule-doc="' + issue.code + '"]');
  assert.ok(card, 'a rule card for ' + issue.code);
  assert.ok(card.querySelector('.mlv-disclosure__summary').textContent.indexOf('About ' + issue.code) >= 0);
  const section = (label) => card.querySelector('[data-ruledoc-section="' + label + '"]');
  assert.ok(section('Why it matters').textContent.indexOf(issue.why) >= 0);
  assert.ok(section('How it is detected').textContent.indexOf(issue.message) >= 0);
  assert.ok(section('How to fix it').textContent.indexOf(issue.fixHint) >= 0);
  assert.equal(section('False positives it avoids'), null, 'that section needs the sidecar');
  assert.equal(card.querySelector('[data-ruledoc-source]').getAttribute('data-ruledoc-source'), issue.docs);
});

test('the sidecar hook supplies the false-positive text when it lands (MLV-P6)', async () => {
  const ctx = await mount();
  const issue = sample.issues[0];
  const { ruleDocFor, setRuleDocs } = ctx.MLView.__internal.ruleDocs;
  // The shape `analyzer/tools/gen_rule_docs.py` will emit, installed through the
  // documented hook. Nothing else in the viewer needs to change when it lands.
  setRuleDocs({
    [issue.code]: {
      why: 'Sidecar why.',
      detection: 'Sidecar detection.',
      fix: 'Sidecar fix.',
      falsePositives: 'gradient accumulation, LBFGS and factory-built optimizers',
      docs: 'docs/rules/' + issue.code + '.md',
    },
  });
  try {
    const doc = ruleDocFor(issue);
    assert.equal(doc.why, 'Sidecar why.', 'the sidecar outranks the composed fallback');
    assert.equal(doc.falsePositives, 'gradient accumulation, LBFGS and factory-built optimizers');
    // A rule the sidecar does not carry still composes.
    const other = sample.issues.find((i) => i.code !== issue.code);
    assert.equal(ruleDocFor(other).why, other.why);
  } finally {
    setRuleDocs(null);
  }
});

test('a malformed sidecar never takes the report down (MLV-P6)', async () => {
  const ctx = await mount();
  const { ruleDocFor, setRuleDocs } = ctx.MLView.__internal.ruleDocs;
  const issue = sample.issues[0];
  for (const junk of [{ [issue.code]: 'not an object' }, { [issue.code]: { why: 42, fix: null } }, {}]) {
    setRuleDocs(junk);
    const doc = ruleDocFor(issue);
    assert.equal(doc.code, issue.code);
    assert.equal(doc.why, issue.why, 'a bad field falls back to the finding');
  }
  setRuleDocs(null);
});

/* ── RAIL-GROUP ────────────────────────────────────────────────────────── */

test('the rail offers Group by: none | rule | file, defaulting to none (RAIL-GROUP)', async () => {
  const ctx = await mount();
  const control = ctx.panel.querySelector('.mlv-rail__groupby');
  assert.ok(control, 'the first in-rail control there has ever been');
  assert.equal(control.getAttribute('data-group-by'), 'none', 'default none, so the flat rail is unchanged');
  const modes = Array.from(control.querySelectorAll('[data-group-mode]')).map((b) => b.getAttribute('data-group-mode'));
  assert.deepEqual(modes, ['none', 'rule', 'file']);
  assert.equal(control.querySelector('[data-group-mode="none"]').getAttribute('aria-pressed'), 'true');
  assert.equal(ctx.panel.querySelector('.mlv-railgroup'), null, 'and nothing is grouped');
});

test('grouped by rule: one header per code with its occurrence count (RAIL-GROUP)', async () => {
  // 60 findings, 6 codes, 10 files: the shape both audits measured.
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues = [];
  for (const node of graph.nodes) node.issueIds = [];
  const target = graph.nodes[0];
  for (let i = 0; i < 60; i++) {
    const code = 'MLV' + (701 + (i % 6));
    const issue = {
      ...JSON.parse(JSON.stringify(sample.issues[0])),
      id: 'i:gen' + i,
      code,
      severity: 'high',
      title: code + ' title',
      // code = i % 6 and file = floor(i / 6), so each of the six codes lands in
      // all ten files exactly once -- the "10 occurrences in 10 files" shape.
      loc: { ...target.loc, file: 'pipeline_' + Math.floor(i / 6) + '.py', line: i + 1 },
      nodeIds: [target.id],
      confidenceBucket: i % 6 === 0 ? 'speculative' : 'certain',
    };
    graph.issues.push(issue);
    target.issueIds.push(issue.id);
  }
  graph.stats.issues = { low: 0, medium: 0, high: 60 };
  const ctx = await mount(graph);
  assert.equal(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]').length, 60, 'flat draws all 60');

  click(ctx, ctx.panel.querySelector('[data-group-mode="rule"]'));
  const groups = ctx.panel.querySelectorAll('.mlv-railgroup');
  assert.equal(groups.length, 6, '60 rows became 6 headers');
  const first = groups[0];
  assert.equal(first.getAttribute('data-group-key'), 'MLV701');
  assert.equal(first.querySelector('[data-group-occurrences]').textContent, '10 occurrences in 10 files');
  assert.equal(first.querySelector('.mlv-railgroup__head').getAttribute('aria-expanded'), 'false', 'collapsed at >= 3');
  assert.equal(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]').length, 0, 'and the 60 rows are folded away');

  // Expanding one lists its ten sites, and nothing else.
  const headKey = first.querySelector('.mlv-railgroup__head').getAttribute('data-group-toggle');
  click(ctx, first.querySelector('.mlv-railgroup__head'));
  // The panel's DOM was replaced; a keyboard user must not be dumped on <body>.
  assert.equal(
    ctx.document.activeElement.getAttribute('data-group-toggle'),
    headKey,
    'the focus followed the header through the re-render',
  );
  const opened = ctx.panel.querySelector('[data-group-key="MLV701"]');
  assert.equal(opened.querySelector('.mlv-railgroup__head').getAttribute('aria-expanded'), 'true');
  assert.equal(opened.querySelectorAll('.mlv-issue[data-issue-id]').length, 10);
  assert.equal(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]').length, 10);
  // The worst bucket in the group is the one a reviewer should read first.
  assert.ok(opened.querySelector('.mlv-chip--conf-speculative'), 'the header carries the group is worst bucket');
});

test('grouped by file, and the mode persists in ViewState (RAIL-GROUP)', async () => {
  const graph = JSON.parse(JSON.stringify(sample));
  const ctx = await mount(graph);
  click(ctx, ctx.panel.querySelector('[data-group-mode="file"]'));
  assert.equal(ctx.app.getState().railGroupBy, 'file');
  const keys = Array.from(ctx.panel.querySelectorAll('.mlv-railgroup')).map((g) => g.getAttribute('data-group-key'));
  for (const key of keys) assert.ok(graph.issues.some((i) => i.loc.file === key), key + ' is a file in the document');
  click(ctx, ctx.panel.querySelector('[data-group-mode="none"]'));
  assert.equal(ctx.app.getState().railGroupBy, undefined, 'the default is absent, like scope and flow (11.9)');

  // ...and it comes back from a restored state.
  const restored = await mount(graph, { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['high', 'medium', 'low'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', railGroupBy: 'rule' });
  assert.equal(restored.panel.querySelector('.mlv-rail__groupby').getAttribute('data-group-by'), 'rule');
  // Anything else restores the documented default rather than throwing.
  const junk = await mount(graph, { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: ['high', 'medium', 'low'], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', railGroupBy: 'by-phase-of-moon' });
  assert.equal(junk.panel.querySelector('.mlv-rail__groupby').getAttribute('data-group-by'), 'none');
});

test('a single-occurrence rule renders as a plain row, not a twisty (RAIL-GROUP)', async () => {
  const ctx = await mount();
  click(ctx, ctx.panel.querySelector('[data-group-mode="rule"]'));
  // The demo's six findings are six distinct codes, so nothing is grouped and
  // the rail looks exactly as it does flat.
  assert.equal(ctx.panel.querySelectorAll('.mlv-railgroup').length, 0);
  assert.equal(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]').length, sample.issues.length);
});

test('grouping never reshuffles the findings, and loses none (RAIL-GROUP)', async () => {
  const ctx = await loadBundle();
  const { groupIssues } = ctx.MLView.__internal.rail;
  const graph = makeSyntheticGraph(60, 60);
  const issues = graph.issues;
  for (const mode of ['rule', 'file']) {
    const groups = groupIssues(issues, mode);
    const flat = [];
    for (const g of groups) for (const i of g.issues) flat.push(i.id);
    assert.equal(flat.length, issues.length, mode + ' lost or duplicated a finding');
    assert.equal(new Set(flat).size, issues.length);
    for (const g of groups) {
      // Within a group, the document's own order survives.
      const order = g.issues.map((i) => issues.indexOf(i));
      assert.deepEqual(order.slice().sort((a, b) => a - b), order, mode + ' reordered a group');
    }
  }
  assert.equal(groupIssues(issues, 'none').length, 0, 'none does no grouping at all');
});

test('a selected finding is never hidden behind a collapsed group (RAIL-GROUP)', async () => {
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues = [];
  for (const node of graph.nodes) node.issueIds = [];
  const target = graph.nodes[0];
  for (let i = 0; i < 5; i++) {
    const issue = {
      ...JSON.parse(JSON.stringify(sample.issues[0])),
      id: 'i:same' + i,
      code: 'MLV777',
      severity: 'high',
      loc: { ...target.loc, line: 10 + i },
      nodeIds: [target.id],
    };
    graph.issues.push(issue);
    target.issueIds.push(issue.id);
  }
  graph.stats.issues = { low: 0, medium: 0, high: 5 };
  const ctx = await mount(graph);
  click(ctx, ctx.panel.querySelector('[data-group-mode="rule"]'));
  assert.equal(ctx.document.querySelectorAll('.mlv-issue[data-issue-id]').length, 0, 'five occurrences fold');
  ctx.app.focusIssue('i:same3');
  assert.ok(rowOf(ctx, 'i:same3'), 'selecting one opens its group');
  assert.equal(rowOf(ctx, 'i:same3').getAttribute('aria-selected'), 'true');
});
