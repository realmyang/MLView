/**
 * MLV-P12 — the pipeline relation, the `pipeline:` selector and the chooser
 * (CONTRACTS 11.47).
 *
 * The relation is ported line for line from `core/pipelines.py` and the
 * projection is the same `project()` every other selector goes through, so the
 * PARITY of the algorithm is `scope_parity.test.mjs`'s job against the
 * regenerated fixture. This suite is about the two things that gate cannot see:
 *
 *   - the RULE, stated rather than transcribed — the closure includes but does
 *     not expand through another entrypoint's own nodes, a shared node becomes
 *     `context` in every view rather than `core` in one, and a finding anchored
 *     only on a shared node is reported as outside the view rather than shown;
 *   - the CHOOSER, which is renderer-owned outright (11.47 F): it opens once,
 *     every exit is an answer, the answer persists, and it says what the list
 *     cannot tell you.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();
const { pipelines, scope } = (await loadBundle()).MLView.__internal;

/**
 * The frozen golden with three entrypoints instead of one.
 *
 * `data.py` is reached from `train()` AND owns its own nodes, so `build_loaders`
 * comes back SHARED — which is the case worth gating, because a shared node is
 * `context` in both views and its findings are outside both.
 */
function multi(entrypoints = ['train.py', 'data.py', 'sklearn_baseline.py']) {
  const g = JSON.parse(JSON.stringify(sample));
  g.workspace = { ...g.workspace, entrypoints };
  return g;
}

async function app(graph, opts = {}) {
  const ctx = await loadBundle();
  const posted = [];
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: () => () => undefined,
    saved: null,
    saveState(s) {
      this.saved = s;
    },
    loadState: () => opts.state || null,
  };
  const root = ctx.document.getElementById('mlview-root');
  if (opts.attrScope) root.setAttribute('data-mlview-scope', opts.attrScope);
  const instance = ctx.MLView.mount(root, graph, bridge);
  return { ...ctx, posted, bridge, app: instance };
}

const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
/**
 * Values built inside the jsdom realm have a different `Array.prototype`, and
 * `assert/strict` compares prototypes — the same round-trip every other suite
 * here makes, for the same reason.
 */
const plain = (value) => JSON.parse(JSON.stringify(value));
const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const roles = (doc) => {
  const out = {};
  for (const node of doc.nodes) out[node.id] = node.viewRole;
  return out;
};

/* ── the grammar (11.47 B) ─────────────────────────────────────────────── */

test('pipeline joins SCOPE_KINDS, and therefore the bad_selector candidates', () => {
  const parsed = scope.parseScope('pipeline:train.py');
  assert.equal(parsed.kind, 'pipeline');
  assert.equal(parsed.target, 'train.py');
  assert.equal(parsed.depth, 0, 'a pipeline is already a region: default depth 0');
  assert.equal(parsed.spec, 'pipeline:train.py');
  assert.equal(scope.parseScope('PIPELINE:train.py').kind, 'pipeline', 'the KIND folds case');
  assert.equal(scope.parseScope('pipeline:src\\exp.py').target, 'src/exp.py', 'and the target normalizes');

  let thrown = null;
  try {
    scope.parseScope('bogus:x');
  } catch (err) {
    thrown = err;
  }
  assert.ok(thrown);
  assert.ok(thrown.candidates.indexOf('pipeline') >= 0, thrown.candidates.join(', '));
});

test('an empty pipeline target falls through to the resolver, which names the entrypoints', () => {
  // 11.47 B1, and the same rule `node:` and `file:` already live by: only the
  // resolver knows this graph's entrypoints, so only it can raise with a real
  // candidate list. `unit:` stays the one kind rejected by the grammar.
  const parsed = scope.parseScope('pipeline:');
  assert.equal(parsed.target, '');
  let thrown = null;
  try {
    scope.project(multi(), parsed);
  } catch (err) {
    thrown = err;
  }
  assert.ok(thrown, 'pipeline: is refused, not silently applied');
  assert.equal(thrown.code, 'unknown_pipeline');
  assert.equal(thrown.term, '');
  assert.deepEqual(plain(thrown.candidates), ['data.py', 'sklearn_baseline.py', 'train.py'], 'sorted, capped at 10');

  let bad = null;
  try {
    scope.project(multi(), scope.parseScope('pipeline:nope.py'));
  } catch (err) {
    bad = err;
  }
  assert.equal(bad.code, 'unknown_pipeline');
  assert.equal(bad.term, 'nope.py');
});

test('a bare basename and a case-folded path both resolve to the same DRAWING', () => {
  // The same golden with `train.py` moved into `src/exp03/`, so a bare
  // basename has a deep path to resolve TO.
  const g = multi(['src/exp03/train.py', 'sklearn_baseline.py']);
  for (const node of g.nodes) {
    if (node.loc.file === 'train.py') node.loc.file = 'src/exp03/train.py';
  }
  const byBase = scope.project(g, scope.parseScope('pipeline:train.py'));
  // `view.scope` echoes what the user TYPED, exactly as `file:` does and exactly
  // as `core/project.py` builds it — the canonical entrypoint decides what is
  // drawn, not what the breadcrumb says. The scope note names the canonical
  // path, so the reader is never left guessing which script this is.
  assert.equal(byBase.view.scope, 'pipeline:train.py');
  assert.ok(byBase.nodes.length > 0, 'a bare basename really does resolve to the deep path');
  assert.equal(byBase.view.empty, false, 'and it is not the empty scope a wrong path would give');
  assert.ok(
    byBase.nodes.some((n) => n.viewRole === 'core' && n.loc.file === 'src/exp03/train.py'),
    'the core it draws is that entrypoint’s own',
  );
  assert.ok(
    (byBase.diagnostics || []).some((d) => d.message.indexOf('pipeline:src/exp03/train.py') === 0),
    'the note names the canonical entrypoint',
  );
  const folded = scope.project(g, scope.parseScope('pipeline:SKLEARN_BASELINE.PY'));
  assert.ok(
    (folded.diagnostics || []).some(
      (d) => d.kind === 'config_warning' && d.message.indexOf('case-insensitively') >= 0,
    ),
    'a case-folded match is SAID, exactly as file: says it',
  );
  const exact = scope.project(g, scope.parseScope('pipeline:sklearn_baseline.py'));
  // The two documents differ in EXACTLY one thing: the note that says the match
  // was case-folded. Everything the reader is shown — the nodes, the edges, the
  // findings and the whole `view` — is byte-identical, which is what 11.47 B
  // means by "produce byte-identical documents" and is why the note is a
  // diagnostic rather than a different projection.
  assert.deepEqual(
    plain({ ...folded, diagnostics: [], view: { ...folded.view, scope: '', label: '' } }),
    plain({ ...exact, diagnostics: [], view: { ...exact.view, scope: '', label: '' } }),
    'pipeline:X and pipeline:x draw exactly the same document',
  );
  assert.equal(
    folded.diagnostics.length - exact.diagnostics.length,
    1,
    'and the only extra note is the one that says the match was case-folded',
  );
});

/* ── the relation (11.47 A) ────────────────────────────────────────────── */

test('the closure includes another entrypoint’s nodes but does not expand through them', () => {
  const g = multi();
  const index = pipelines.indexOf(g);
  const train = index.reach('train.py');
  const data = index.reach('data.py');
  assert.ok(train.indexOf('n:1100aa22bb33') >= 0, 'train() calls build_loaders(), so it reaches it');
  assert.ok(data.indexOf('n:1100aa22bb33') >= 0, 'and data.py owns it');
  assert.ok(
    index.shared.has('n:1100aa22bb33'),
    'a node two entrypoints reach is shared — which is the number that says the components overlap',
  );
  assert.equal(
    train.indexOf('n:6a2f83b19c40'),
    -1,
    'and the walk stops there: train.py does not swallow sklearn_baseline.py through it',
  );
});

test('config edges are cut on purpose, so a shared config module joins nothing', () => {
  const g = multi();
  const index = pipelines.indexOf(g);
  assert.deepEqual(plain(pipelines.EDGE_KINDS), ['data', 'call'], 'only data and call join a pipeline');
  // `TrainConfig()` reaches `build_loaders` and `train_loader` by `config`
  // edges only, so nothing reaches it and it belongs to no pipeline at all.
  assert.ok(index.unreached.indexOf('n:0c0f19a3b7d2') >= 0, 'the config node belongs to no pipeline');
  for (const entry of index.entrypoints) {
    assert.equal(index.reach(entry).indexOf('n:0c0f19a3b7d2'), -1, entry + ' does not claim it');
  }
});

test('a workspace with no entrypoints has no pipelines and every node unreached', () => {
  const g = multi([]);
  const index = pipelines.indexOf(g);
  assert.deepEqual(plain(pipelines.rows(g)), []);
  assert.equal(index.unreached.length, g.nodes.length);
});

/* ── the projection (11.47 C) ──────────────────────────────────────────── */

test('a shared node is context in EVERY pipeline view, never core in one of them', () => {
  const g = multi();
  const train = scope.project(g, scope.parseScope('pipeline:train.py'));
  const data = scope.project(g, scope.parseScope('pipeline:data.py'));
  const shared = 'n:1100aa22bb33';
  assert.equal(roles(train)[shared], 'context', 'shared in train.py’s view');
  assert.equal(
    roles(data)[shared],
    'core',
    'but data.py OWNS it — a script’s own statements are never handed to a neighbour',
  );

  const trainCore = train.nodes.filter((n) => n.viewRole === 'core').map((n) => n.id);
  const dataCore = data.nodes.filter((n) => n.viewRole === 'core').map((n) => n.id);
  for (const id of trainCore) {
    assert.equal(dataCore.indexOf(id), -1, id + ' is claimed by two pipelines');
  }
});

test('a pipeline view never assigns boundary to a node it shares (11.47 C)', () => {
  const g = multi();
  const doc = scope.project(g, scope.parseScope('pipeline:train.py', 1));
  const index = pipelines.indexOf(g);
  for (const node of doc.nodes) {
    if (!index.shared.has(node.id)) continue;
    assert.notEqual(
      node.viewRole,
      'boundary',
      node.id + ' is shared, so it is context — a boundary stub means "out of scope", which is a different statement',
    );
  }
});

test('the scope note names what the view is NOT showing (11.47 C1)', () => {
  const doc = scope.project(multi(), scope.parseScope('pipeline:train.py'));
  const note = (doc.diagnostics || []).filter(
    (d) => d.kind === 'config_warning' && d.message.indexOf('pipeline:train.py') === 0,
  )[0];
  assert.ok(note, 'every pipeline projection appends one');
  assert.match(note.message, /reaches \d+ of \d+ node\(s\)/, 'how much it drew');
  assert.match(note.message, /shared with another entrypoint/, 'how much it shares');
  assert.match(note.message, /belong to no pipeline at all/, 'and how much belongs to nobody');
  assert.match(note.message, /config-only dependency is not shown/, 'and which edges were cut');
});

test('an entrypoint that reaches nothing is an EMPTY SCOPE, not an error', () => {
  const g = multi(['train.py', 'notes/scratch.py']);
  const doc = scope.project(g, scope.parseScope('pipeline:notes/scratch.py'));
  assert.equal(doc.view.empty, true, 'a finding about the workspace, not a refusal');
  assert.equal(doc.nodes.length, 0);
  assert.equal(doc.stages.length, 8, 'all eight stage rows survive, at nodeCount 0');
  assert.ok(
    (doc.diagnostics || []).some((d) => d.message.indexOf('matched no nodes') >= 0),
    'and the empty-scope note is the one every kind already gets',
  );
});

test('view.of stays PROJECT-level, so a pipeline can never read as a clean bill of health', () => {
  const doc = scope.project(multi(), scope.parseScope('pipeline:sklearn_baseline.py'));
  assert.equal(doc.view.of.nodes, sample.nodes.length, 'the denominator is the whole graph');
  assert.ok(doc.nodes.length < sample.nodes.length, 'while the view is smaller');
  const shownIssues = doc.issues.length;
  const allIssues = doc.view.of.issues.low + doc.view.of.issues.medium + doc.view.of.issues.high;
  assert.ok(shownIssues <= allIssues);
  assert.equal(doc.workspace.entrypoints.length, 3, 'workspace is carried verbatim');
});

/* ── the catalogue (11.47 D) ───────────────────────────────────────────── */

test('the rows are the analyzer’s ranked order, and exclusive + shared = nodeCount', () => {
  const g = multi();
  const rows = pipelines.rows(g);
  assert.deepEqual(
    plain(rows.map((r) => r.entrypoint)),
    ['train.py', 'data.py', 'sklearn_baseline.py'],
    'never re-sorted',
  );
  for (const row of rows) {
    assert.equal(row.exclusiveCount + row.sharedCount, row.nodeCount, row.entrypoint);
    assert.ok(row.nodeCount > 0, 'an empty pipeline is not a row');
  }
});

test('the emitted block is never trusted, and a disagreement is REPORTED', () => {
  const g = multi();
  const rows = pipelines.rows(g);
  assert.equal(pipelines.drift(g, rows), null, 'no block, nothing to say');
  g.pipelines = rows.map((r) => ({ ...r, label: r.entrypoint }));
  assert.equal(pipelines.drift(g, rows), null, 'a block that agrees is silent');
  g.pipelines = [{ entrypoint: 'gone.py', label: 'gone.py', nodeCount: 3, exclusiveCount: 3, sharedCount: 0, issueCounts: { low: 0, medium: 0, high: 0 } }];
  const drift = pipelines.drift(g, rows);
  assert.ok(drift, 'a block that disagrees is said out loud');
  assert.match(drift, /follows the computed one/, 'and the diagram follows the computed relation');
});

/* ── the picker ────────────────────────────────────────────────────────── */

test('the scope picker lists the pipelines with live counts, above the concerns', async () => {
  const ctx = await app(multi());
  ctx.app.setScope(null);
  const openBtn = ctx.document.querySelector('.mlv-btn--scope');
  click(ctx, openBtn);
  const headings = Array.from(ctx.document.querySelectorAll('.mlv-scopepicker__heading')).map(text);
  assert.deepEqual(headings.slice(0, 2), ['Pipelines', 'Concerns'], headings.join(' | '));
  // Scoped to the PICKER: the chooser draws rows with the same marker, and a
  // gate that counted both would pass with the picker empty.
  const rows = Array.from(ctx.document.querySelectorAll('.mlv-scopepicker [data-pipeline]'));
  assert.equal(rows.length, 3);
  assert.equal(rows[0].getAttribute('data-scope-spec'), 'pipeline:train.py');
  assert.match(text(rows[0]), /\d+ nodes/, 'with a live count');
  const shared = rows.filter((r) => /shared/.test(text(r)));
  assert.ok(shared.length, 'and the shared count, which is the only over-approximation signal');
});

test('a single-entrypoint workspace still offers its one pipeline', async () => {
  const ctx = await app(sample);
  click(ctx, ctx.document.querySelector('.mlv-btn--scope'));
  const rows = Array.from(ctx.document.querySelectorAll('.mlv-scopepicker [data-pipeline]'));
  assert.equal(rows.length, 1, 'one row: it is a legitimate scope even when there is nothing to choose');
});

/* ── the chooser (renderer-owned, 11.47 F) ─────────────────────────────── */

const chooser = (ctx) => ctx.document.querySelector('.mlv-pipechooser');

test('a two-or-more-pipeline report OPENS on the chooser', async () => {
  const ctx = await app(multi());
  const panel = chooser(ctx);
  assert.ok(panel, 'the chooser is mounted');
  assert.equal(panel.hidden, false, 'and open on first paint');
  assert.equal(panel.querySelectorAll('[data-pipeline]').length, 3);
  assert.match(text(panel.querySelector('.mlv-pipechooser__title')), /3 pipelines/);
  assert.ok(panel.querySelector('.mlv-pipechooser__all'), '"Show everything" is a first-class answer');
  const dialog = panel.querySelector('[role="dialog"]');
  assert.equal(dialog.getAttribute('aria-modal'), 'true');
  assert.ok(dialog.getAttribute('aria-labelledby'), 'and it is named');
});

test('a one-pipeline workspace is never asked', async () => {
  const ctx = await app(sample);
  assert.equal(chooser(ctx).hidden, true, 'nothing to choose, so no question');
});

test('a reader who already has a scope is never asked', async () => {
  const ctx = await app(multi(), { attrScope: 'stage:train' });
  assert.equal(chooser(ctx).hidden, true, 'they have already answered');
  assert.equal(ctx.app.getScope().spec, 'stage:train');
});

test('picking a pipeline scopes the diagram, locally, and records the answer', async () => {
  const ctx = await app(multi());
  const row = chooser(ctx).querySelector('[data-pipeline="sklearn_baseline.py"]');
  assert.ok(row);
  click(ctx, row);
  assert.equal(chooser(ctx).hidden, true, 'the question is answered and closes');
  assert.equal(ctx.app.getScope().spec, 'pipeline:sklearn_baseline.py');
  assert.equal(ctx.app.getState().pipelineChosen, true);
  assert.equal(
    ctx.posted.filter((m) => m.type === 'requestRefresh').length,
    0,
    'a scope change never reaches the analyzer (CONTRACTS 11.8)',
  );
  const changed = ctx.posted.filter((m) => m.type === 'scopeChanged').pop();
  assert.equal(changed.spec, 'pipeline:sklearn_baseline.py', 'and the host is told');
});

test('"Show everything" and Escape are both answers, and both are remembered', async () => {
  const ctx = await app(multi());
  click(ctx, chooser(ctx).querySelector('.mlv-pipechooser__all'));
  assert.equal(chooser(ctx).hidden, true);
  assert.equal(ctx.app.getScope().spec, null, 'everything means everything');
  assert.equal(ctx.app.getState().pipelineChosen, true);

  const other = await app(multi());
  const panel = chooser(other);
  panel.dispatchEvent(
    new other.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
  );
  assert.equal(chooser(other).hidden, true, 'Escape is an answer, not an abandonment');
  assert.equal(other.app.getState().pipelineChosen, true);
});

test('the answer round-trips through ViewState, so the question is asked once', async () => {
  const first = await app(multi());
  click(first, chooser(first).querySelector('.mlv-pipechooser__all'));
  const state = first.app.getState();
  assert.equal(state.pipelineChosen, true);

  const second = await app(multi(), { state });
  assert.equal(chooser(second).hidden, true, 'a restored viewer is not asked again');

  const fresh = await app(multi(), { state: { ...state, pipelineChosen: undefined } });
  assert.equal(chooser(fresh).hidden, false, 'and a state that never answered still is');
});

test('aria-modal="true" is kept honest: Tab cycles inside the panel', async () => {
  // The diagram behind the chooser is full of tab stops, so the attribute would
  // be a promise the page does not keep without this.
  const ctx = await app(multi());
  const panel = chooser(ctx);
  const stops = Array.from(panel.querySelectorAll('button:not([disabled])'));
  assert.ok(stops.length >= 5, stops.length + ' focusable controls in the panel');
  const last = stops[stops.length - 1];
  last.focus();
  const tab = (shift) =>
    panel.dispatchEvent(
      new ctx.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: shift, bubbles: true, cancelable: true }),
    );
  tab(false);
  assert.equal(ctx.document.activeElement, stops[0], 'Tab off the end wraps to the first control');
  tab(true);
  assert.equal(ctx.document.activeElement, last, 'and Shift+Tab wraps back');
});

test('the chooser says what the list cannot tell you (11.47 F)', async () => {
  const ctx = await app(multi());
  const notes = chooser(ctx).querySelector('[data-pipechooser-notes]');
  assert.ok(notes, 'the caveats are on the panel, not in a tooltip');
  assert.equal(notes.querySelectorAll('li').length, Number(notes.getAttribute('data-pipechooser-notes')));
  const said = text(notes);
  assert.match(said, /not a partition/, 'shared nodes are in two views');
  assert.match(said, /belong to no pipeline at all/, 'and some belong to none');
  assert.match(said, /Only data and call edges/, 'and a config-only dependency is invisible here');
  assert.match(said, /capped at ten/, 'and the entrypoint list is a heuristic');
});

test('a capped document says its pipeline counts describe the summarised graph', async () => {
  const g = multi();
  g.stats.truncated = true;
  const caveats = pipelines.chooserCaveats(g, pipelines.rows(g)).join('\n');
  assert.match(caveats, /describe the summarised graph/, 'PERF-04 and MLV-P12 interact, and it is said');
});

/* ── the floor, the roles and the focus (VIEW-R4, VIEW-R5, VIEW-R7) ─────── */

/** A row big enough to clear the floor, without inventing a whole document. */
function withRow(entrypoint, nodeCount, exclusiveCount, issues = { low: 0, medium: 0, high: 0 }) {
  return { entrypoint, nodeCount, exclusiveCount, sharedCount: nodeCount - exclusiveCount, issueCounts: issues };
}

test('a trivial entrypoint is not offered as a pipeline (VIEW-R5)', () => {
  // The measured case: the flagship demo's `config.py` is one node and no
  // findings, and it was offered under the lede "each one is a training script".
  const rows = [
    withRow('train.py', 27, 25, { low: 1, medium: 5, high: 4 }),
    withRow('config.py', 1, 1),
    withRow('data.py', 18, 15, { low: 2, medium: 5, high: 2 }),
  ];
  const offered = pipelines.chooserRows(rows).map((r) => r.entrypoint);
  assert.deepEqual(offered, ['train.py', 'data.py'], 'a one-node constants module is not a pipeline');
  // A small row that carries a finding IS worth offering: the finding is the
  // reason a reader would go there.
  const tiny = pipelines.chooserRows([withRow('smoke.py', 2, 2, { low: 1, medium: 0, high: 0 })]);
  assert.equal(tiny.length, 1, 'a finding earns a row however small it is');
});

test('the chooser does not interrupt a workspace a reader can take in (VIEW-R5)', () => {
  const small = { nodes: new Array(54).fill(0).map((_, i) => ({ id: 'n' + i })) };
  const two = [withRow('train.py', 27, 25, { low: 1, medium: 5, high: 4 }), withRow('data.py', 18, 15, { low: 2, medium: 5, high: 2 })];
  assert.equal(pipelines.shouldAsk(small, two), false, '54 nodes and two choices: show the diagram');
  const big = { nodes: new Array(320).fill(0).map((_, i) => ({ id: 'n' + i })) };
  assert.equal(pipelines.shouldAsk(big, two), true, 'the same two choices on a graph nobody can read: ask');
  const three = two.concat([withRow('sweep.py', 30, 30, { low: 0, medium: 1, high: 0 })]);
  assert.equal(pipelines.shouldAsk(small, three), true, 'three choices is a menu, whatever the size');
  const trivial = two.slice(0, 1).concat([withRow('config.py', 1, 1)]);
  assert.equal(pipelines.shouldAsk(big, trivial), false, 'one real pipeline and a module is not a choice');
});

test('the lede says what the relation computes, not what it hopes (VIEW-R5)', async () => {
  const ctx = await app(multi());
  const lede = text(chooser(ctx).querySelector('.mlv-pipechooser__lede'));
  assert.match(lede, /Each one is an entrypoint/, lede);
  assert.equal(/training script/.test(lede), false, 'the entrypoint heuristic promises no such thing');
});

test('rows held back by the floor are counted, not silently dropped (VIEW-R5)', () => {
  const g = multi();
  const rows = [
    withRow('train.py', 27, 25, { low: 1, medium: 5, high: 4 }),
    withRow('config.py', 1, 1),
    withRow('data.py', 18, 15, { low: 2, medium: 5, high: 2 }),
  ];
  const said = pipelines.chooserCaveats(g, pipelines.chooserRows(rows), 1).join('\n');
  assert.match(said, /1 more entrypoint\(s\) are not offered here/, said);
  assert.match(said, /still in the scope picker/, 'and they are still reachable');
});

test('a capped document says the counts stopped telling its pipelines apart (VIEW-R5)', () => {
  const g = multi();
  g.stats.truncated = true;
  const same = [withRow('exp0/train.py', 234, 14), withRow('exp1/train.py', 234, 14)];
  assert.match(pipelines.chooserCaveats(g, same).join('\n'), /the file name is the only thing/);
  // Not said on a whole document: identical counts there are a fact about the
  // workspace, not about the cap.
  const whole = multi();
  whole.stats.truncated = false;
  assert.equal(/the file name is the only thing/.test(pipelines.chooserCaveats(whole, same).join('\n')), false);
});

test('the chooser rows reach assistive tech as BUTTONS (VIEW-R4)', async () => {
  // `role` on a <button> REPLACES the implicit button role: these rows used to
  // compute as plain list items — the modal's only real actions, absent from a
  // screen reader's button rotor. Verified in Chromium's own AX tree.
  const ctx = await app(multi());
  const rows = Array.from(chooser(ctx).querySelectorAll('[data-pipeline]'));
  assert.equal(rows.length, 3);
  for (const row of rows) {
    assert.equal(row.tagName, 'BUTTON', row.getAttribute('data-pipeline') + ' is not a button');
    assert.equal(row.getAttribute('role'), null, 'and nothing overrides the button role');
    const item = row.parentElement;
    assert.equal(item.getAttribute('role'), 'listitem', 'the list semantics live on the wrapper');
    assert.equal(item.parentElement.getAttribute('role'), 'list');
  }
});

test('a row is announced exactly as it is drawn (VIEW-R4)', async () => {
  assert.equal(pipelines.rowLabel(withRow('config.py', 1, 1)), 'config.py, 1 node.');
  assert.equal(
    pipelines.rowLabel(withRow('train.py', 27, 25, { low: 1, medium: 5, high: 4 })),
    'train.py, 27 nodes, 2 shared with another pipeline, 10 findings.',
  );
  assert.equal(pipelines.rowLabel(withRow('one.py', 4, 4, { low: 1, medium: 0, high: 0 })), 'one.py, 4 nodes, 1 finding.');
  const ctx = await app(multi());
  for (const row of chooser(ctx).querySelectorAll('[data-pipeline]')) {
    const label = row.getAttribute('aria-label');
    assert.equal(/0 shared/.test(label), false, label + ' announces an empty chip the row does not draw');
    assert.equal(/0 findings/.test(label), false, label);
    assert.equal(/\b1 nodes\b/.test(label), false, label);
  }
});

test('closing the chooser hands focus to the diagram, not to <body> (VIEW-R7)', async () => {
  for (const close of ['escape', 'everything', 'pick']) {
    const ctx = await app(multi());
    const panel = chooser(ctx);
    assert.equal(panel.hidden, false);
    if (close === 'escape') {
      panel.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    } else if (close === 'everything') {
      click(ctx, panel.querySelector('.mlv-pipechooser__all'));
    } else {
      click(ctx, panel.querySelector('[data-pipeline="train.py"]'));
    }
    assert.equal(chooser(ctx).hidden, true, close + ': the chooser closed');
    const active = ctx.document.activeElement;
    assert.notEqual(active.tagName, 'BODY', close + ': focus fell out of the document onto ' + active.tagName);
    assert.ok(
      active.classList.contains('mlv-canvas') || active.closest('.mlv-canvas'),
      close + ': focus landed on ' + active.tagName + '.' + active.className + ', not on the diagram',
    );
  }
});

test('a deep entrypoint path is shortened for the row and kept in full everywhere else', () => {
  assert.equal(pipelines.name('train.py'), 'train.py');
  assert.equal(pipelines.name('src/train.py'), 'src/train.py');
  assert.equal(pipelines.name('experiments/exp03/train.py'), '…/exp03/train.py', 'the tail is what distinguishes ten siblings');
});
