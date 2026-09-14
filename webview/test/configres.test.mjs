/**
 * ANA-10 (Python half) — the resolved configuration value, rendered.
 *
 * The measurement that funded the item: `num_workers=4` fires MLV112, a
 * module-level `WORKERS = 4` fires, `CFG["workers"]` is silent and
 * `cfg.data.workers` is silent — and a Hydra research repo gets a config lane of
 * four nodes, two of them `unknown` from a `getattr` registry, with zero
 * `config`-kind edges. The analyzer half resolves the value; this half has to
 * put it where the question is asked, which is the card.
 *
 * Two properties are gated here above all others:
 *
 *   - a node the analyzer said nothing about is drawn EXACTLY as it was, so an
 *     analyzer predating ANA-10 loses nothing;
 *   - "could not resolve" is drawn as *"not resolved"* and never as an absence.
 *     An empty sublabel and "MLView could not read this" are the two things this
 *     product must never confuse.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

/** The sample with `attrs` written onto its config node. */
function withAttrs(attrs, extra = {}) {
  const graph = JSON.parse(JSON.stringify(sample));
  const node = graph.nodes.find((n) => n.stage === 'config');
  node.attrs = { ...node.attrs, ...attrs };
  Object.assign(node, extra);
  return { graph, node };
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
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app };
}

const cardOf = (ctx, id) => ctx.document.querySelector('.mlv-node[data-node-id="' + id + '"]');
/** The card's own sublabel text, middle-truncated at 40 chars as it always was. */
const subOf = (ctx, id) => cardOf(ctx, id).querySelector('.mlv-node__sub').textContent;
/** The UNTRUNCATED string, which is what the reader gets from the hover. */
const fullSubOf = (ctx, id) => cardOf(ctx, id).querySelector('.mlv-node__sub').getAttribute('data-config-sub');

/* ── the resolved value ────────────────────────────────────────────────── */

test('a document with no resolution is drawn exactly as it always was (ANA-10)', async () => {
  const ctx = await mount(sample);
  const node = sample.nodes.find((n) => n.stage === 'config');
  assert.equal(subOf(ctx, node.id), node.sublabel || node.fqn || node.kind);
  assert.equal(cardOf(ctx, node.id).hasAttribute('data-config-value'), false);
  assert.equal(cardOf(ctx, node.id).hasAttribute('data-config-alt'), false);
});

test('the resolved value goes in the card sublabel, with its name (ANA-10)', async () => {
  const { graph, node } = withAttrs(
    { resolvedValue: '64', resolvedFrom: 'CONFIG["batch_size"] at config.py:9' },
    { var: 'batch_size' },
  );
  const ctx = await mount(graph);
  assert.equal(subOf(ctx, node.id), 'batch_size = 64');
  assert.equal(cardOf(ctx, node.id).getAttribute('data-config-value'), '64');
  assert.equal(
    cardOf(ctx, node.id).querySelector('.mlv-node__sub').title,
    'batch_size = 64 · resolved from CONFIG["batch_size"] at config.py:9',
  );
  const label = cardOf(ctx, node.id).getAttribute('aria-label');
  assert.ok(label.indexOf('resolved value 64') > 0, 'and the screen reader hears it too: ' + label);
  assert.ok(label.indexOf('from CONFIG["batch_size"]') > 0, label);
});

test('every spelling the analyzer might use resolves to the same card (ANA-10)', async () => {
  for (const key of ['resolvedValue', 'resolved', 'configValue', 'value']) {
    const { graph, node } = withAttrs({ [key]: '4' }, { var: 'num_workers' });
    const ctx = await mount(graph);
    assert.equal(subOf(ctx, node.id), 'num_workers = 4', key + ' was not read');
  }
});

test('a label that already IS the assignment is not repeated (ANA-10)', async () => {
  const { graph, node } = withAttrs({ resolvedValue: '64' }, { label: 'batch_size = 64', var: 'batch_size' });
  const ctx = await mount(graph);
  assert.equal(subOf(ctx, node.id), '64', 'the card says it once');
});

/* ── the one-of-N alternatives node ────────────────────────────────────── */

test('a getattr registry draws ONE node that says "one of N" (ANA-10)', async () => {
  const { graph, node } = withAttrs({
    alternatives: 'build_cifar, build_mnist, build_imagenet',
    resolvedFrom: 'getattr(datasets, CFG.dataset) at data.py:14',
  });
  const ctx = await mount(graph);
  const card = cardOf(ctx, node.id);
  assert.equal(card.getAttribute('data-config-alt'), '3', 'the card knows how many it could not choose between');
  assert.ok(card.classList.contains('is-alternatives'));
  assert.equal(fullSubOf(ctx, node.id), 'one of 3: build_cifar, build_mnist, build_imagenet');
  assert.ok(subOf(ctx, node.id).indexOf('one of 3: build_cifar') === 0, 'the card leads with the count: ' + subOf(ctx, node.id));
  assert.ok(card.getAttribute('aria-label').indexOf('one of 3') > 0, card.getAttribute('aria-label'));
});

test('a long candidate list is counted rather than clipped (ANA-10)', async () => {
  const names = ['a_one', 'b_two', 'c_three', 'd_four', 'e_five'];
  const { graph, node } = withAttrs({ alternatives: names.join('|') });
  const ctx = await mount(graph);
  assert.equal(fullSubOf(ctx, node.id), 'one of 5: a_one, b_two, c_three, +2', 'the pipe separator works too');
  assert.equal(cardOf(ctx, node.id).getAttribute('data-config-alt'), '5');
});

test('the Inspector names ALL N alternatives and says why there are N (ANA-10)', async () => {
  const names = ['build_cifar', 'build_mnist', 'build_imagenet'];
  const { graph, node } = withAttrs({
    alternatives: names.join(', '),
    resolvedFrom: 'getattr(datasets, CFG.dataset) at data.py:14',
  });
  const ctx = await mount(graph);
  ctx.app.focusNode(node.id);
  const panel = ctx.document.querySelector('[id$="-panel-inspector"]');
  const table = panel.querySelector('[data-config-table]');
  assert.ok(table, 'the Inspector draws the resolution table');
  for (const name of names) {
    assert.ok(table.querySelector('[data-config-alternative="' + name + '"]'), 'missing candidate ' + name);
  }
  assert.ok(table.textContent.indexOf('getattr(datasets, CFG.dataset)') > 0, 'and where it read them from');
  assert.ok(
    panel.querySelector('.mlv-insp__altnote').textContent.indexOf('rather than guessing') > 0,
    'and says it did not guess',
  );
});

/* ── the source that exists today: the analyzer's own sublabel ─────────── */

/**
 * `core/config_nodes.py` writes these two sentences. They were measured on this
 * tree with a `getattr(pkg.optims, ...)` probe:
 *
 *   selects pkg.optims.build_adam
 *   one of 3 in pkg.optims · build_adam, build_rmsprop, build_sgd
 *
 * The wording is SHARED with `mlview issues` and the other two hosts, so the
 * card keeps it verbatim and the renderer only adds the visual around it.
 */
test('the analyzer’s own "one of N in M · …" sublabel drives the visual (ANA-10)', async () => {
  const { graph, node } = withAttrs({}, {
    label: 'factory',
    sublabel: 'one of 3 in pkg.optims · build_adam, build_rmsprop, build_sgd',
    confidenceBucket: 'speculative',
  });
  const ctx = await mount(graph);
  const card = cardOf(ctx, node.id);
  assert.equal(card.getAttribute('data-config-alt'), '3');
  assert.ok(card.classList.contains('is-alternatives'));
  assert.equal(
    subOf(ctx, node.id),
    'one of 3 in pkg.optims ·…prop, build_sgd',
    'the analyzer’s sentence, kept — only middle-truncated as every sublabel is',
  );
  assert.equal(fullSubOf(ctx, node.id), null, 'the renderer did not rewrite it');
  assert.ok(card.getAttribute('aria-label').indexOf('one of 3: build_adam, build_rmsprop, build_sgd') > 0, card.getAttribute('aria-label'));

  ctx.app.focusNode(node.id);
  const table = ctx.document.querySelector('[id$="-panel-inspector"] [data-config-table]');
  assert.ok(table, 'and the Inspector still names all three');
  for (const name of ['build_adam', 'build_rmsprop', 'build_sgd']) {
    assert.ok(table.querySelector('[data-config-alternative="' + name + '"]'), name);
  }
  assert.ok(table.textContent.indexOf('pkg.optims') > 0, 'and where they are defined');
});

test('the analyzer’s "selects <fqn>" sublabel is a resolved value (ANA-10)', async () => {
  const { graph, node } = withAttrs({}, {
    label: 'factory',
    sublabel: 'selects pkg.optims.build_adam',
    fqn: 'pkg.optims.build_adam',
  });
  const ctx = await mount(graph);
  const card = cardOf(ctx, node.id);
  assert.equal(card.getAttribute('data-config-value'), 'pkg.optims.build_adam');
  assert.equal(card.hasAttribute('data-config-alt'), false, 'one answer is not N answers');
  assert.equal(subOf(ctx, node.id), 'selects pkg.optims.build_adam', 'the analyzer’s sentence, kept');
  assert.ok(card.getAttribute('aria-label').indexOf('resolved value pkg.optims.build_adam') > 0);
});

test('a structured `attrs` reading outranks the parsed sentence (ANA-10 C1)', async () => {
  const { graph, node } = withAttrs(
    { alternatives: 'a_one|b_two', resolvedFrom: 'registry.py:4' },
    { label: 'factory', sublabel: 'one of 3 in pkg.optims · build_adam, build_rmsprop, build_sgd' },
  );
  const ctx = await mount(graph);
  assert.equal(cardOf(ctx, node.id).getAttribute('data-config-alt'), '2', 'the structured value wins');
  assert.equal(fullSubOf(ctx, node.id), 'one of 2: a_one, b_two');
});

/* ── "I could not resolve this" is not an absence ──────────────────────── */

test('an unresolved value says so, and says why when the analyzer said (ANA-10)', async () => {
  const { graph, node } = withAttrs({ unresolved: 'interpolated from ${env:BATCH}' });
  const ctx = await mount(graph);
  assert.equal(fullSubOf(ctx, node.id), 'not resolved — interpolated from ${env:BATCH}');
  assert.equal(cardOf(ctx, node.id).getAttribute('data-config-unresolved'), '1');
  assert.ok(cardOf(ctx, node.id).getAttribute('aria-label').indexOf('value not resolved') > 0);
});

test('a bare unresolved flag still says "not resolved", never nothing (ANA-10)', async () => {
  const { graph, node } = withAttrs({ unresolved: 'true' });
  const ctx = await mount(graph);
  assert.equal(subOf(ctx, node.id), 'not resolved');
});

test('the resolution never invents a bucket or a badge (ANA-10)', async () => {
  const { graph, node } = withAttrs({ resolvedValue: '64' }, { var: 'batch_size', confidenceBucket: 'possible' });
  const ctx = await mount(graph);
  ctx.app.focusNode(node.id);
  const panel = ctx.document.querySelector('[id$="-panel-inspector"]');
  const chips = Array.from(panel.querySelectorAll('.mlv-insp__meta .mlv-chip')).map((c) => c.textContent);
  assert.ok(chips.indexOf('possible') >= 0, 'the analyzer’s own bucket, unchanged: ' + chips.join(', '));
});
