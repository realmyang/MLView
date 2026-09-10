/**
 * VIEW-08, the viewer half — the diff overlay as a rendered document.
 *
 * The analyzer half landed in Sprint 5 wave 1 (`mlview diff`, CONTRACTS §11.38)
 * and explicitly left the ledge, the ghost outline, the banner and the "changed
 * only" chip to the renderer. This file is the gate on all four, plus the two
 * properties that make the feature safe to ship:
 *
 *   - the overlay is a SIBLING document, so a page without one is byte-for-byte
 *     the page it always was, and a malformed one degrades to that same page;
 *   - `notes[]` is NEVER elided (§11.38 C), and the viewer's own blind spots —
 *     removed edges it cannot draw, ghosts that carry no findings, a rename it
 *     cannot detect — are stated beside the analyzer's.
 *
 * The fixture is not hand-written: it is the block embedded in
 * `webview/dev/index.html`, which is the real output of
 * `mlview diff BASE.json HEAD.json --format json` over a base built from
 * `contracts/graph.sample.json`. Reading it from there is what keeps the dev
 * harness and this gate from drifting apart.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, readSample, WEBVIEW_ROOT } from './helpers.mjs';

const sample = await readSample();

/** The overlay `dev/index.html` embeds — real `mlview diff` output. */
async function readDevOverlay() {
  const html = await readFile(join(WEBVIEW_ROOT, 'dev', 'index.html'), 'utf8');
  const start = html.indexOf('<!-- MLVIEW-DIFF-START -->');
  const end = html.indexOf('<!-- MLVIEW-DIFF-END -->');
  assert.ok(start > 0 && end > start, 'dev/index.html carries the diff block');
  const block = html.slice(start, end);
  const opener = 'type="application/json">';
  const from = block.indexOf(opener) + opener.length;
  const to = block.lastIndexOf('</' + 'script>');
  return JSON.parse(block.slice(from, to));
}

const overlay = await readDevOverlay();

function bridgeFor(host, sink, state) {
  return {
    host,
    theme: 'light',
    capabilities: {
      canOpenSource: true,
      canReanalyze: host === 'vscode',
      canExport: host === 'vscode',
      canAskAssistant: false,
    },
    post: (msg) => sink.posted.push(msg),
    onMessage: (cb) => {
      sink.send = cb;
      return () => undefined;
    },
    saveState: (s) => sink.saved.push(s),
    loadState: () => state || null,
  };
}

/**
 * Mount with the overlay embedded the way the standalone report will embed it:
 * a second `application/json` block beside the graph, read at construction.
 */
async function mount(opts = {}) {
  const ctx = await loadBundle();
  const sink = { posted: [], saved: [], send: null };
  if (opts.embed !== false) {
    const block = ctx.document.createElement('script');
    block.id = 'mlview-diff';
    block.type = 'application/json';
    block.textContent = JSON.stringify(opts.overlay === undefined ? overlay : opts.overlay);
    ctx.document.body.appendChild(block);
  }
  const graph = opts.graph || sample;
  const app = ctx.MLView.mount(
    ctx.document.getElementById('mlview-root'),
    graph,
    bridgeFor(opts.host || 'standalone', sink, opts.state),
  );
  return { ...ctx, app, sink, graph };
}

const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));

const entriesWith = (status) => overlay.nodes.filter((n) => n.status === status);

/* ── the document is a sibling, never an edit to the graph ─────────────── */

test('a page with no overlay renders exactly the page it always rendered (VIEW-08)', async () => {
  const withOut = await mount({ embed: false });
  assert.equal(withOut.document.querySelector('[data-diff-bar]'), null, 'no banner');
  assert.equal(withOut.document.querySelectorAll('[data-diff]').length, 0, 'no card carries a status');
  assert.equal(withOut.document.querySelectorAll('[data-node-id]').length, sample.nodes.length);
});

test('the overlay never mutates the document it decorates (VIEW-08)', async () => {
  const before = JSON.stringify(sample);
  const ctx = await mount();
  assert.ok(ctx.document.querySelector('[data-diff-bar]'), 'the overlay was adopted');
  assert.equal(JSON.stringify(sample), before, 'the host document is untouched');
});

test('a malformed, wrong-kind or wrong-version overlay degrades to no overlay (1.1/6)', async () => {
  for (const bad of [
    { kind: 'mlview-graph', nodes: [] },
    { kind: 'mlview-diff', diffVersion: '2.0', nodes: overlay.nodes },
    { kind: 'mlview-diff', diffVersion: '1.0', nodes: [], issues: [] },
    'not an object',
  ]) {
    const ctx = await mount({ overlay: bad });
    assert.equal(ctx.document.querySelector('[data-diff-bar]'), null, JSON.stringify(bad).slice(0, 40));
    assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, sample.nodes.length);
  }
});

test('a truncated JSON block never takes the report down (VIEW-08)', async () => {
  const ctx = await loadBundle();
  const block = ctx.document.createElement('script');
  block.id = 'mlview-diff';
  block.type = 'application/json';
  block.textContent = '{"kind":"mlview-diff","nodes":[{"id":"n:a"';
  ctx.document.body.appendChild(block);
  const sink = { posted: [], saved: [], send: null };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), sample, bridgeFor('standalone', sink));
  assert.ok(app, 'the viewer still mounted');
  assert.equal(ctx.document.querySelector('[data-diff-bar]'), null);
});

/* ── the banner ────────────────────────────────────────────────────────── */

test('the banner reads "+N nodes · −N nodes · N new findings · N fixed" (VIEW-08)', async () => {
  const ctx = await mount();
  const headline = ctx.document.querySelector('[data-diff-headline]');
  assert.ok(headline, 'the banner draws a headline');
  assert.equal(headline.textContent, overlay.summary.headline, 'verbatim, in the analyzer’s own wording');
  assert.ok(headline.textContent.indexOf('−') > 0, 'and with §11.38’s MINUS SIGN, not a hyphen');
  assert.equal(headline.getAttribute('role'), 'status', 'announced when an overlay arrives after the graph');
});

test('the banner names the two documents it is comparing (VIEW-08 D)', async () => {
  const ctx = await mount();
  const sides = ctx.document.querySelector('[data-diff-sides]');
  assert.ok(sides, 'the sides row exists');
  assert.ok(sides.textContent.indexOf('base ') >= 0 && sides.textContent.indexOf('head ') >= 0, sides.textContent);
});

test('every count on the banner comes from the lists it drew (VIEW-08 B1)', async () => {
  const ctx = await mount();
  const read = (label) => {
    const chip = ctx.document.querySelector('[data-diff-count="' + label + '"]');
    return Number(chip.textContent.split(' ')[0]);
  };
  assert.equal(read('added'), overlay.summary.nodes.added);
  assert.equal(read('removed'), overlay.summary.nodes.removed);
  assert.equal(read('changed'), overlay.summary.nodes.changed);
  assert.equal(read('unchanged'), overlay.summary.nodes.unchanged);
  assert.equal(read('new findings'), overlay.summary.issues.new);
  assert.equal(read('fixed'), overlay.summary.issues.fixed);
  assert.equal(read('still present'), overlay.summary.issues.persisting);
});

test('a headline the arrays do not support is corrected, and the difference is a note', async () => {
  const lying = JSON.parse(JSON.stringify(overlay));
  lying.summary.headline = '+99 nodes · −0 nodes · 0 new findings · 0 fixed';
  const ctx = await mount({ overlay: lying });
  const headline = ctx.document.querySelector('[data-diff-headline]').textContent;
  assert.equal(headline, overlay.summary.headline, 'the lists win, because the lists are what is drawn');
  const notes = Array.from(ctx.document.querySelectorAll('[data-note-kind]')).map((n) => n.getAttribute('data-note-kind'));
  assert.ok(notes.indexOf('counts-disagree') >= 0, notes.join(', '));
});

/* ── §11.38 C: the notes are never elided ──────────────────────────────── */

test('a pair with nothing to declare says so in one line (§11.38 C)', async () => {
  assert.equal(overlay.notes.length, 0, 'this fixture pair has no analyzer note');
  const ctx = await mount();
  const clean = ctx.document.querySelector('[data-note-kind="none"]');
  assert.ok(clean, 'the clean line is drawn rather than nothing');
  assert.ok(clean.textContent.indexOf('a removed node is a removed node') > 0, clean.textContent);
});

test('every analyzer note is drawn in full, none elided (§11.38 C)', async () => {
  const noisy = JSON.parse(JSON.stringify(overlay));
  noisy.notes = [
    { kind: 'different-roots', side: '', count: 0, message: 'the two documents describe different workspace roots.' },
    { kind: 'truncated', side: 'head', count: 1, message: 'the head graph was capped by --max-nodes.' },
    { kind: 'not-analyzed', side: 'base', count: 3, message: '3 file(s) were set aside by the relevance prefilter.' },
    { kind: 'projection', side: 'head', count: 0, message: 'the head document is a scoped view.' },
    { kind: 'different-analyzers', side: '', count: 0, message: 'generator.version differs.' },
  ];
  const ctx = await mount({ overlay: noisy });
  const box = ctx.document.querySelector('[data-diff-notes]');
  assert.equal(box.getAttribute('data-diff-notes'), '5');
  for (const note of noisy.notes) {
    const li = ctx.document.querySelector('[data-note-kind="' + note.kind + '"]');
    assert.ok(li, 'no note drawn for ' + note.kind);
    assert.ok(li.textContent.indexOf(note.message) > 0, note.kind + ': ' + li.textContent);
  }
});

test('the viewer states its OWN blind spots beside the analyzer’s (VIEW-08)', async () => {
  const ctx = await mount();
  const own = Array.from(ctx.document.querySelectorAll('[data-note-kind="viewer"]')).map((n) => n.textContent);
  const joined = own.join(' | ');
  assert.ok(joined.indexOf('rename') >= 0, 'no rename detection is stated: ' + joined);
  assert.ok(joined.indexOf('ghost outlines') >= 0, 'the ghosts carry no findings: ' + joined);
});

/* ── the cards ─────────────────────────────────────────────────────────── */

test('an added node gets a ledge that survives the compact LOD (VIEW-08)', async () => {
  const ctx = await mount();
  const added = entriesWith('added');
  assert.ok(added.length >= 2, added.length + ' added in the fixture');
  for (const entry of added) {
    const card = ctx.document.querySelector('.mlv-node[data-node-id="' + entry.id + '"]');
    assert.ok(card, 'no card for added node ' + entry.id);
    assert.equal(card.getAttribute('data-diff'), 'added');
    const ledge = card.querySelector('[data-ledge="added"]');
    assert.ok(ledge, 'no ledge on ' + entry.label);
    assert.equal(ledge.textContent, 'added', 'never colour alone');
    // The ledge is a child of the CARD, not of `.mlv-node__text`, which is what
    // `[data-lod="compact"]` hides.
    assert.equal(ledge.parentElement, card, 'the ledge must outlive the compact LOD');
    assert.ok(card.getAttribute('aria-label').indexOf('added in this change') > 0, card.getAttribute('aria-label'));
  }
});

test('a removed node is drawn as a ghost outline in place (VIEW-08)', async () => {
  const ctx = await mount();
  const removed = entriesWith('removed');
  assert.ok(removed.length >= 2, removed.length + ' removed in the fixture');
  for (const entry of removed) {
    const card = ctx.document.querySelector('.mlv-node[data-node-id="' + entry.id + '"]');
    assert.ok(card, 'the removed node was not resurrected: ' + entry.label);
    assert.equal(card.getAttribute('data-diff'), 'removed');
    assert.ok(card.classList.contains('is-ghost'), 'it reuses the ghost visual');
    assert.ok(card.querySelector('[data-ledge="removed"]'), 'and says the word');
    // In place: inside its own stage band, not appended to the last lane.
    const lane = ctx.document.querySelector('.mlv-lane[data-lane-id="' + entry.stage + '"]');
    assert.ok(lane, 'its stage band is drawn: ' + entry.stage);
    const label = card.getAttribute('aria-label');
    assert.ok(label.indexOf('Removed: ') === 0, 'a removed node is not a "missing step": ' + label);
    assert.ok(label.indexOf('drawn where it used to be') > 0, label);
  }
});

test('a resurrected ghost carries no severity badge and no findings (VIEW-08)', async () => {
  const ctx = await mount();
  const entry = entriesWith('removed')[0];
  const card = ctx.document.querySelector('.mlv-node[data-node-id="' + entry.id + '"]');
  assert.equal(card.querySelector('.mlv-node__badge, [data-sev]'), null, 'nothing to open, so nothing to badge');
  assert.equal(card.hasAttribute('data-sev'), false);
});

test('a changed node gets a chip that NAMES what changed (VIEW-08 B3)', async () => {
  const ctx = await mount();
  const changed = entriesWith('changed');
  assert.ok(changed.length >= 1, 'the fixture has a changed node');
  for (const entry of changed) {
    const card = ctx.document.querySelector('.mlv-node[data-node-id="' + entry.id + '"]');
    assert.equal(card.getAttribute('data-diff'), 'changed');
    const chip = card.querySelector('[data-diff-chip="changed"]');
    assert.ok(chip, 'no changed chip on ' + entry.label);
    if (entry.changed && entry.changed.length === 1) {
      assert.equal(chip.textContent, 'changed: ' + entry.changed[0]);
    } else if (entry.changed && entry.changed.length > 1) {
      assert.equal(chip.textContent, 'changed · ' + entry.changed.length + ' fields');
      assert.equal(chip.title, 'Changed in this diff: ' + entry.changed.join(', '));
    }
  }
});

test('an unchanged node is decorated with nothing at all (VIEW-08 B2)', async () => {
  const ctx = await mount();
  const entry = entriesWith('unchanged')[0];
  const card = ctx.document.querySelector('.mlv-node[data-node-id="' + entry.id + '"]');
  assert.equal(card.getAttribute('data-diff'), 'unchanged');
  assert.equal(card.querySelector('[data-ledge]'), null);
  assert.equal(card.querySelector('[data-diff-chip]'), null);
});

/* ── the findings ──────────────────────────────────────────────────────── */

test('a rail row says how the finding stands against the base (VIEW-08)', async () => {
  const ctx = await mount();
  const newOne = overlay.issues.find((i) => i.status === 'new');
  const persisting = overlay.issues.find((i) => i.status === 'persisting');
  const chipOf = (id) => {
    const row = ctx.document.querySelector('.mlv-issue[data-issue-id="' + id + '"]');
    assert.ok(row, 'no rail row for ' + id);
    return row.querySelector('[data-diff-issue]');
  };
  assert.equal(chipOf(newOne.id).textContent, 'new vs base');
  assert.equal(chipOf(persisting.id).textContent, 'still there');
  // It must never be mistaken for CI-ADOPT's `new` chip, which is about git
  // hunks inside ONE analysis.
  assert.notEqual(chipOf(newOne.id).getAttribute('data-diff-issue'), null);
  assert.equal(chipOf(newOne.id).hasAttribute('data-change'), false);
});

test('what the change FIXED is listed, and said to be from the earlier analysis', async () => {
  const ctx = await mount();
  const fixed = overlay.issues.filter((i) => i.status === 'fixed');
  assert.ok(fixed.length >= 1, 'the fixture fixes something');
  const section = ctx.document.querySelector('[data-fixed-section]');
  assert.ok(section, 'the fixed section is drawn');
  assert.equal(section.getAttribute('data-fixed-section'), String(fixed.length));
  const head = section.querySelector('[data-group-toggle="diff-fixed"]');
  assert.equal(head.getAttribute('aria-expanded'), 'false', 'folded away, but present');
  click(ctx, head);
  const reopened = ctx.document.querySelector('[data-fixed-section]');
  for (const entry of fixed) {
    const row = reopened.querySelector('[data-fixed-issue="' + entry.id + '"]');
    assert.ok(row, 'no row for fixed finding ' + entry.code);
    assert.ok(row.textContent.indexOf(entry.code) >= 0, row.textContent);
  }
  assert.ok(
    reopened.textContent.indexOf('EARLIER analysis') > 0,
    'the section says these are not findings in this document',
  );
});

/* ── "changed only" reuses the scope projection ────────────────────────── */

test('"changed only" is a projection: core = changed, boundary = one hop', async () => {
  const ctx = await mount();
  const before = ctx.document.querySelectorAll('[data-node-id]').length;
  const chip = ctx.document.querySelector('[data-changed-only]');
  assert.ok(chip, 'the chip is on the banner');
  assert.equal(chip.getAttribute('aria-pressed'), 'false');
  click(ctx, chip);

  const after = ctx.document.querySelectorAll('[data-node-id]').length;
  assert.ok(after <= before, after + ' of ' + before + ' nodes after the projection');
  // Every changed node that survived is `core`; nothing else may be.
  const changed = new Set(overlay.nodes.filter((n) => n.status !== 'unchanged').map((n) => n.id));
  const roles = new Map();
  for (const card of ctx.document.querySelectorAll('[data-node-id]')) {
    roles.set(card.getAttribute('data-node-id'), card.getAttribute('data-view-role'));
  }
  for (const [id, role] of roles) {
    if (role === 'core') assert.ok(changed.has(id), id + ' is core but did not change');
  }
  for (const id of changed) {
    if (roles.has(id)) assert.equal(roles.get(id), 'core', id + ' changed but is not core');
  }
  assert.ok(Array.from(roles.values()).indexOf('boundary') >= 0, 'one hop of context is drawn');
  assert.equal(ctx.document.querySelector('[data-changed-only]').getAttribute('aria-pressed'), 'true');
});

test('"changed only" really narrows: one changed node plus its one hop', async () => {
  // The shipped fixture touches five of twelve nodes in a densely wired sample,
  // so one hop legitimately reaches everything. A single-node overlay is what
  // proves the projection is doing the narrowing and not merely re-drawing.
  const one = JSON.parse(JSON.stringify(overlay));
  const target = overlay.nodes.find((n) => n.status === 'changed');
  one.nodes = overlay.nodes
    .filter((n) => n.status !== 'removed')
    .map((n) => ({ ...n, status: n.id === target.id ? 'changed' : 'unchanged', changed: n.id === target.id ? ['issueCodes'] : [] }));
  one.summary = {
    nodes: { added: 0, removed: 0, changed: 1, unchanged: one.nodes.length - 1 },
    edges: { added: 0, removed: 0, changed: 0, unchanged: 0 },
    issues: { new: 0, fixed: 0, persisting: 0 },
    headline: '+0 nodes · −0 nodes · 0 new findings · 0 fixed',
  };
  one.issues = [];
  const ctx = await mount({ overlay: one });
  const before = ctx.document.querySelectorAll('[data-node-id]').length;
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  const cards = Array.from(ctx.document.querySelectorAll('[data-node-id]'));
  assert.ok(cards.length < before, cards.length + ' of ' + before);
  const core = cards.filter((c) => c.getAttribute('data-view-role') === 'core').map((c) => c.getAttribute('data-node-id'));
  assert.deepEqual(core, [target.id], 'exactly the changed node is core');
  assert.ok(cards.some((c) => c.getAttribute('data-view-role') === 'boundary'), 'and its neighbours are boundary');
});

test('the projection can never read as a clean bill of health (FEATURES 3.7)', async () => {
  const ctx = await mount();
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  const line = ctx.document.querySelector('[data-scope-line]');
  assert.ok(line, 'the rail still says how many findings are outside the view');
  assert.ok(line.textContent.indexOf('outside the changed set') > 0, line.textContent);
  assert.ok(line.textContent.indexOf(' of ') > 0, line.textContent);
});

test('a diff projection never claims to be a scope the user picked (VIEW-08)', async () => {
  const ctx = await mount();
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  const crumb = ctx.document.querySelector('.mlv-breadcrumb');
  assert.equal(crumb.hidden, true, 'no breadcrumb offering a selector that does not parse');
  assert.equal(ctx.app.getScope().spec, null, 'and getScope() still says "no scope"');
});

test('"changed only" composes with a real scope rather than replacing it', async () => {
  const ctx = await mount();
  ctx.app.setScope('stage:train');
  const scoped = ctx.document.querySelectorAll('[data-node-id]').length;
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  const both = ctx.document.querySelectorAll('[data-node-id]').length;
  assert.ok(both <= scoped, both + ' <= ' + scoped);
  assert.equal(ctx.app.getScope().spec, 'stage:train', 'the scope is still the scope');
  const crumb = ctx.document.querySelector('.mlv-breadcrumb');
  assert.equal(crumb.hidden, false, 'and the breadcrumb still names it');
  assert.ok(crumb.textContent.indexOf('changed only') > 0, crumb.textContent);
  // The denominator stays PROJECT-LEVEL: a nested projection must not restate
  // a scope's totals as the project's.
  // 12 analysed nodes plus the 2 resurrected ghosts: the document on screen.
  assert.ok(crumb.textContent.indexOf('of ' + (sample.nodes.length + entriesWith('removed').length)) > 0, crumb.textContent);
});

test('"changed only" over a scope with nothing changed in it says so, and draws the scope', async () => {
  const ctx = await mount();
  ctx.app.setScope('stage:objective');
  const before = ctx.document.querySelectorAll('[data-node-id]').length;
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  assert.ok(ctx.document.querySelector('[data-diff-empty]'), 'the banner says nothing changed here');
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, before, 'and the diagram is unchanged');
});

test('"Show all" in the rail clears the scope AND the changed-only view', async () => {
  const ctx = await mount();
  ctx.app.setScope('stage:train');
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  const showAll = ctx.document.querySelector('[data-scope-line] .mlv-link');
  assert.ok(showAll, 'the scope line offers Show all');
  click(ctx, showAll);
  assert.equal(ctx.app.getScope().spec, null);
  assert.equal(ctx.document.querySelector('[data-changed-only]').getAttribute('aria-pressed'), 'false');
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, sample.nodes.length + entriesWith('removed').length);
});

/* ── the host message, and the state ───────────────────────────────────── */

test('the host’s `baseLabel` names what the comparison is against (11.43 D)', async () => {
  const ctx = await mount({ embed: false, host: 'vscode' });
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay, baseLabel: 'main@3af6f2c' });
  const sides = ctx.document.querySelector('[data-diff-sides]');
  assert.ok(sides.textContent.indexOf('base main@3af6f2c') >= 0, sides.textContent);
  // Both roots are the same string in this fixture, so without the label the row
  // would read "base X → head X" and name nothing at all.
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay: null });
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay });
  assert.ok(
    ctx.document.querySelector('[data-diff-sides]').textContent.indexOf('base vision_pipeline') >= 0,
    'and it falls back to the root when the host sends none',
  );
});

test('the `diffOverlay` host message installs and clears the overlay (§4, amended)', async () => {
  const ctx = await mount({ embed: false, host: 'vscode' });
  assert.equal(ctx.document.querySelector('[data-diff-bar]'), null);
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay });
  assert.ok(ctx.document.querySelector('[data-diff-bar]'), 'it arrived after the graph');
  assert.equal(
    ctx.document.querySelector('[data-diff-headline]').textContent,
    overlay.summary.headline,
  );
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay: null });
  assert.equal(ctx.document.querySelector('[data-diff-bar]'), null, 'and null clears it');
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, sample.nodes.length, 'the ghosts go with it');
});

test('an unreadable overlay on the wire is logged and ignored, never drawn', async () => {
  const ctx = await mount({ embed: false, host: 'vscode' });
  ctx.sink.send({ v: 1, type: 'diffOverlay', overlay: { kind: 'not-a-diff' } });
  assert.equal(ctx.document.querySelector('[data-diff-bar]'), null);
  const logs = ctx.sink.posted.filter((m) => m.type === 'log' && m.level === 'warn');
  assert.equal(logs.length, 1, 'and it said so');
  assert.ok(logs[0].message.indexOf('unreadable diff overlay') >= 0, logs[0].message);
});

test('the dismiss button puts the plain diagram back exactly as it was', async () => {
  const ctx = await mount();
  const close = ctx.document.querySelector('.mlv-diffbar__close');
  assert.ok(close, 'the banner offers a way out');
  click(ctx, close);
  assert.equal(ctx.document.querySelector('[data-diff-bar]'), null);
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, sample.nodes.length);
  assert.equal(ctx.document.querySelectorAll('[data-diff]').length, 0);
});

test('diffOnly round-trips through ViewState, absent at its default (11.9)', async () => {
  const ctx = await mount();
  assert.equal(ctx.app.getState().diffOnly, undefined, 'absent while off');
  click(ctx, ctx.document.querySelector('[data-changed-only]'));
  assert.equal(ctx.app.getState().diffOnly, true);

  const restored = await mount({ state: { ...ctx.app.getState() } });
  assert.equal(restored.document.querySelector('[data-changed-only]').getAttribute('aria-pressed'), 'true');
});

test('restoring diffOnly with no overlay loaded is a no-op, never an empty diagram', async () => {
  const ctx = await mount({
    embed: false,
    state: { viewport: { x: 0, y: 0, zoom: 1 }, selection: null, collapsed: [], filters: { severities: [], stages: [], showSuppressed: false, query: '' }, railTab: 'issues', diffOnly: true },
  });
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, sample.nodes.length);
  assert.equal(ctx.app.getState().diffOnly, undefined);
});
