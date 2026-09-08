/**
 * VIEW-09ab: a pasted `path:line` becomes a node jump, and a truncated result
 * list says so.
 *
 * Measured before this: `train.py:29` — the exact string the CLI prints and the
 * Problems panel shows — found the ISSUE at that line and never the NODE,
 * because `file + ':' + line` is assembled for a hit's display `meta` and was
 * never scored; and `pipeline_5` and `loss` each returned exactly 40 rows with
 * nothing saying the list had been cut.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample, makeSyntheticGraph } from './helpers.mjs';

const sample = await readSample();

async function app() {
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
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridge);
  return { ...ctx, app: instance, input: ctx.document.querySelector('.mlv-search .mlv-input') };
}

function type(ctx, value) {
  ctx.input.value = value;
  ctx.input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
}

/* ── the parser ────────────────────────────────────────────────────────── */

test('a pasted location parses, and an ordinary query does not (VIEW-09a)', async () => {
  const ctx = await loadBundle();
  const { parseLocation } = ctx.MLView.__internal.search;
  // The parsed object comes from the bundle's realm, so its FIELDS are compared
  // rather than its identity: a cross-realm object is never deep-strict-equal.
  const parsed = (q) => {
    const p = parseLocation(q);
    return p === null ? null : p.path + '|' + p.line;
  };
  assert.equal(parsed('train.py:29'), 'train.py|29');
  assert.equal(parsed('src/train.py:29'), 'src/train.py|29');
  assert.equal(parsed('src\\train.py:29'), 'src/train.py|29', 'windows separators');
  assert.equal(parsed('train.py:29:4'), 'train.py|29', 'a trailing column is accepted');
  assert.equal(parsed('train.py'), 'train.py|null');
  assert.equal(parsed('./train.py'), 'train.py|null');
  // Amendment A6 keeps the palette at substring matching: these stay ordinary.
  assert.equal(parsed('MLV101'), null);
  assert.equal(parsed('train_test_split'), null);
  assert.equal(parsed('loss'), null);
  assert.equal(parsed('1.0'), null, 'a version is not a file');
  assert.equal(parsed('confidence: 0.6'), null);
  assert.equal(parsed(''), null);
});

test('a path suffix matches on segment boundaries only (VIEW-09a)', async () => {
  const ctx = await loadBundle();
  const { pathMatches } = ctx.MLView.__internal.search;
  assert.equal(pathMatches('train.py', 'train.py'), true);
  assert.equal(pathMatches('src/models/train.py', 'train.py'), true);
  assert.equal(pathMatches('src/models/train.py', 'models/train.py'), true);
  assert.equal(pathMatches('src/pretrain.py', 'train.py'), false, 'not a bare endsWith');
  assert.equal(pathMatches('src\\models\\train.py', 'train.py'), true);
});

/* ── resolution ────────────────────────────────────────────────────────── */

test('the narrowest node containing the line wins, with a nearest fallback (VIEW-09a)', async () => {
  const ctx = await loadBundle();
  const { locationHit } = ctx.MLView.__internal.search;
  const { GraphIndex } = ctx.MLView.__internal;
  const graph = JSON.parse(JSON.stringify(sample));
  const file = graph.nodes[0].loc.file;
  // A wide span and a narrow one over the same line, plus a distant neighbour.
  graph.nodes[0].loc = { ...graph.nodes[0].loc, file, line: 10, endLine: 60 };
  graph.nodes[1].loc = { ...graph.nodes[1].loc, file, line: 28, endLine: 31 };
  graph.nodes[2].loc = { ...graph.nodes[2].loc, file, line: 200, endLine: 201 };
  const index = new GraphIndex(graph);

  const inside = locationHit(index, { path: file, line: 29 });
  assert.equal(inside.node.id, graph.nodes[1].id, 'the narrowest container, not the first one');
  assert.equal(inside.contains, true);

  const between = locationHit(index, { path: file, line: 150 });
  assert.equal(between.node.id, graph.nodes[2].id, 'nothing contains 150; the nearest node answers');
  assert.equal(between.contains, false);

  const bare = locationHit(index, { path: file, line: null });
  assert.equal(bare.node.id, graph.nodes[0].id, 'a bare file name means the top of that file');

  assert.equal(locationHit(index, { path: 'nowhere.py', line: 3 }), null);
});

test('train.py:29 returns the node at that line as the first hit (VIEW-09a)', async () => {
  const ctx = await app();
  const { detailed } = ctx.MLView.__internal.search;
  const { GraphIndex } = ctx.MLView.__internal;
  const index = new GraphIndex(sample);
  const node = sample.nodes.find((n) => n.loc.file.indexOf('train.py') >= 0);
  assert.ok(node, 'the sample has a node in train.py');
  const query = 'train.py:' + node.loc.line;
  const result = detailed(index, query);
  assert.ok(result.hits.length > 0, query + ' found nothing');
  assert.equal(result.hits[0].kind, 'node', 'a NODE, which is what the old box could never return');
  assert.equal(result.hits[0].id, node.id);
  assert.ok(result.hits[0].location, 'the pinned hit is labelled as a jump');
  assert.equal(result.hits[0].location.line, node.loc.line);
  // ...and it reaches the DOM with its affordance.
  type(ctx, query);
  const first = ctx.document.querySelector('.mlv-search__results li');
  assert.equal(first.getAttribute('data-search-pinned'), '1');
  assert.ok(first.querySelector('[data-search-jump]'), 'the row says it is a jump');
});

/**
 * VIEW-09a's third acceptance clause — "every query that returns hits today
 * returns the identical ordered list" — frozen as LITERALS.
 *
 * It used to be gated by comparing `searchGraph(index, q)` with
 * `detailed(index, q).hits`. But `searchGraph` IS `searchGraphDetailed(…).hits`
 * (search.ts), so the test compared one function's output with itself and could
 * never fail — and the invariant was in fact broken (TB-05): a bare `train.py`
 * parses as a location, so it grew a pinned first row, `validate() train.py:11`,
 * which had ranked TENTH. These are the lists the ranking produces with no pin
 * applied, i.e. the lists main returned before this item; `train.py` and
 * `data.py` are in the set precisely because they are the queries that moved.
 */
const RANKED = {
  train: [
    'MLV201 · Gradients are never zeroed',
    'MLV601 · No random seed is set anywhere in the workspace',
    'train()',
    'MLV401 · Softmax output is fed to CrossEntropyLoss',
    'MLV302 · Evaluation loop is not wrapped in torch.no_grad()',
    'CrossEntropyLoss',
    'Adam',
    'for images, labels in train_loader',
    'zero_grad()',
    'validate()',
    'train_loader',
    'TrainConfig()',
    'train_test_split()',
    'MLV110 · Training DataLoader does not shuffle',
    'MLV602 · Split without random_state',
  ],
  MLV: [
    'MLV401 · Softmax output is fed to CrossEntropyLoss',
    'MLV201 · Gradients are never zeroed',
    'MLV110 · Training DataLoader does not shuffle',
    'MLV302 · Evaluation loop is not wrapped in torch.no_grad()',
    'MLV602 · Split without random_state',
    'MLV601 · No random seed is set anywhere in the workspace',
  ],
  loss: [
    'CrossEntropyLoss',
    'MLV401 · Softmax output is fed to CrossEntropyLoss',
    'MLV201 · Gradients are never zeroed',
  ],
  SmallNet: [
    'SmallNet',
    'MLV401 · Softmax output is fed to CrossEntropyLoss',
    'MLV601 · No random seed is set anywhere in the workspace',
  ],
  preprocess: [
    'StandardScaler',
  ],
  zzz: [],
  // The two queries a bare-filename pin reordered.
  'train.py': [
    'MLV401 · Softmax output is fed to CrossEntropyLoss',
    'MLV201 · Gradients are never zeroed',
    'MLV302 · Evaluation loop is not wrapped in torch.no_grad()',
    'MLV601 · No random seed is set anywhere in the workspace',
    'CrossEntropyLoss',
    'train()',
    'Adam',
    'for images, labels in train_loader',
    'zero_grad()',
    'validate()',
    'MLV110 · Training DataLoader does not shuffle',
  ],
  'data.py': [
    'build_loaders()',
    'train_loader',
    'MLV110 · Training DataLoader does not shuffle',
    'MLV601 · No random seed is set anywhere in the workspace',
  ],
};

test('every query that returns hits today returns the identical ordered list (VIEW-09a, TB-05)', async () => {
  const ctx = await loadBundle();
  const { searchGraph, GraphIndex } = ctx.MLView.__internal;
  const { detailed } = ctx.MLView.__internal.search;
  const index = new GraphIndex(sample);
  // `Array.from` in THIS realm: the hits come from the bundle's realm, and a
  // cross-realm array is never deep-strict-equal to a local one.
  const labels = (hits) => Array.from(hits, (h) => h.label);
  for (const query of Object.keys(RANKED)) {
    const hits = detailed(index, query).hits;
    assert.deepEqual(labels(hits), RANKED[query], 'the ranked list moved for ' + query);
    // Nothing in this set is a location jump, so nothing here may be pinned.
    for (const hit of hits) assert.equal(hit.location, undefined, query + ' pinned ' + hit.label);
    // ...and the list form every host publishes is still the same list.
    assert.deepEqual(labels(searchGraph(index, query)), RANKED[query]);
  }
});

test('a bare filename ranks; only path:line pins (VIEW-09a, TB-05)', async () => {
  const ctx = await loadBundle();
  const { GraphIndex } = ctx.MLView.__internal;
  const { detailed, parseLocation } = ctx.MLView.__internal.search;
  const index = new GraphIndex(sample);
  // The parser still reads a bare name as a location — the resolver takes it —
  // but the SEARCH BOX pins only a query that carries its line, which is what a
  // pasted CLI location, Problems entry or stack frame always does.
  assert.ok(parseLocation('train.py'), 'the parser still accepts it');
  const bare = detailed(index, 'train.py').hits;
  assert.equal(bare[0].label, RANKED['train.py'][0], 'a bare filename is ranked, not pinned');

  const pinned = detailed(index, 'train.py:11').hits;
  assert.equal(pinned[0].kind, 'node');
  assert.equal(pinned[0].label, 'validate()');
  assert.equal(pinned[0].location.line, 11);
});

/* ── truncation ────────────────────────────────────────────────────────── */

test('a cut list says "showing 40 of N" and offers more (VIEW-09b)', async () => {
  const ctx = await loadBundle();
  const { GraphIndex } = ctx.MLView.__internal;
  const { detailed } = ctx.MLView.__internal.search;
  const index = new GraphIndex(makeSyntheticGraph(150, 200));
  const result = detailed(index, 'synthetic');
  assert.equal(result.hits.length, 40, 'the budget still holds');
  assert.equal(result.truncated, true);
  assert.equal(result.total, result.totalNodes + result.totalIssues);
  assert.ok(result.total > 150, 'all 150 node sublabels and 24 issue titles matched: ' + result.total);

  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: () => undefined,
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), makeSyntheticGraph(150, 200), bridge);
  const input = ctx.document.querySelector('.mlv-search .mlv-input');
  input.value = 'synthetic';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const foot = ctx.document.querySelector('[data-search-truncated]');
  assert.ok(foot, 'the footer exists');
  assert.equal(foot.getAttribute('data-search-truncated'), String(result.total));
  assert.ok(foot.textContent.indexOf('showing 40 of ' + result.total) >= 0, foot.textContent);

  // "Show more" raises the budget instead of leaving the user stuck at 40.
  const more = foot.querySelector('[data-search-more]');
  more.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  const rows = ctx.document.querySelectorAll('.mlv-search__results .mlv-result');
  assert.equal(rows.length, 80, 'one more page: ' + rows.length);
  assert.ok(ctx.document.querySelector('[data-search-truncated]'), 'and it still says how many are left');
  instance.destroy();
});

test('an untruncated list draws no footer (VIEW-09b)', async () => {
  const ctx = await app();
  type(ctx, 'SmallNet');
  assert.ok(ctx.document.querySelectorAll('.mlv-search__results .mlv-result').length > 0);
  assert.equal(ctx.document.querySelector('[data-search-truncated]'), null);
});
