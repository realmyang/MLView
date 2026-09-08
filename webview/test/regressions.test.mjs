/**
 * Round-2 review regressions (MLV-R2-W01 … W12). One test per finding, each
 * failing against the code as it was reported and passing against the fix.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, makeSyntheticGraph, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();

async function app() {
  const ctx = await loadBundle();
  const posted = [];
  const bridge = {
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: (cb) => {
      ctx.listener = cb;
      return () => undefined;
    },
    saveState: () => undefined,
    loadState: () => null,
  };
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, sample, bridge);
  return { ...ctx, posted, app: instance, canvas: ctx.document.querySelector('.mlv-canvas') };
}

function key(ctx, target, k, opts = {}) {
  target.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...opts }));
}

function click(ctx, target, type = 'click') {
  target.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true }));
}

/* ── MLV-R2-W01: the Outline listed 15 of 45 nodes twice ─────────────────── */

test('the Outline lists every node exactly once (MLV-R2-W01)', async () => {
  const ctx = await app();
  assert.equal(ctx.app.getState().collapsed.length, 0, 'nothing is collapsed in the sample');
  const rows = Array.from(ctx.document.querySelectorAll('[data-outline-id]'));
  const ids = rows.map((r) => r.getAttribute('data-outline-id'));
  const distinct = new Set(ids);
  assert.equal(rows.length, sample.nodes.length, 'one row per node, not 60 rows for 45 nodes');
  assert.equal(distinct.size, rows.length, 'no node is emitted twice');

});

test('a cross-lane child is listed under its OWN stage, once (MLV-R2-W01)', async () => {
  // The exact shape of the bug: a node whose LEXICAL parent sits in another
  // stage is promoted to a root of its own lane by GraphIndex, so walking the
  // lexical `children()` emitted it a second time inside that parent's subtree.
  const ctx = await loadBundle();
  const graph = JSON.parse(JSON.stringify(sample));
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const parent = graph.nodes.filter((n) => n.stage === 'preprocess')[0];
  const child = graph.nodes.filter((n) => n.stage === 'data' && !n.parent)[0];
  assert.ok(parent && child, 'the sample has a preprocess node and an unparented data node');
  child.parent = parent.id;

  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, ctx.MLView.bridges.standalone());
  const rows = Array.from(ctx.document.querySelectorAll('[data-outline-id="' + child.id + '"]'));
  assert.equal(rows.length, 1, child.label + ' appears exactly once, not once per parent');
  assert.equal(rows[0].closest('[data-outline-lane]').getAttribute('data-outline-lane'), 'data');
  assert.equal(
    ctx.document.querySelectorAll('[data-outline-id]').length,
    graph.nodes.length,
    'and the tree still has one row per node',
  );
  assert.equal(byId.get(child.id).parent, parent.id, 'the document itself was not touched');
  instance.destroy();
});

/* ── MLV-R2-W02: the high-contrast marker rule never matched ─────────────── */

test('every theme rule is keyed on the mount root as well as :root (MLV-R2-W02)', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const selectors = css
    .split('}')
    .map((block) => block.slice(block.lastIndexOf('{') === -1 ? 0 : 0, block.indexOf('{')))
    .filter((sel) => sel.indexOf('data-theme') >= 0);
  assert.ok(selectors.length >= 3, 'the stylesheet really does theme things');
  for (const sel of selectors) {
    const themes = sel.match(/data-theme="([a-z]+)"/g) || [];
    for (const theme of new Set(themes)) {
      // The renderer stamps data-theme on the element it mounts into (A3), and
      // both hosts mount into a <div>, so :root alone can never match.
      assert.ok(
        sel.indexOf('.mlv-root[' + theme + ']') >= 0,
        'a rule keyed on :root[' + theme + '] must also list .mlv-root[' + theme + ']: ' + sel.trim(),
      );
    }
    if (sel.indexOf('body.vscode-high-contrast ') >= 0 || /body\.vscode-high-contrast,/.test(sel)) {
      assert.ok(sel.indexOf('vscode-high-contrast-light') >= 0, 'HC-light is a high-contrast theme too: ' + sel.trim());
    }
  }
});

test('the high-contrast marker treatment fires from the mount root (MLV-R2-W02)', async () => {
  const css = await readFile(DIST_CSS_DEV, 'utf8');
  const start = css.indexOf('.mlv-glyph__shape {');
  assert.ok(start > 0);
  const hcRule = css.slice(css.indexOf('.mlv-glyph--high'));
  const block = hcRule.slice(0, hcRule.indexOf('fill: none'));
  for (const selector of [
    'body.vscode-high-contrast .mlv-glyph__shape',
    'body.vscode-high-contrast-light .mlv-glyph__shape',
    ':root[data-theme="hc"] .mlv-glyph__shape',
    '.mlv-root[data-theme="hc"] .mlv-glyph__shape',
  ]) {
    assert.ok(block.indexOf(selector) >= 0, 'missing ' + selector);
  }
});

/* ── MLV-R2-W03: a <button> nested inside a role="option" ────────────────── */

test('an issue row is a valid option with the open button beside it (MLV-R2-W03)', async () => {
  const ctx = await app();
  const options = Array.from(ctx.document.querySelectorAll('.mlv-rail__panel [role="option"]'));
  assert.ok(options.length >= 3);
  for (const option of options) {
    assert.notEqual(option.tagName, 'BUTTON', 'the option is not itself a button');
    assert.equal(option.querySelectorAll('button, a, input, [tabindex]').length, 0, 'no focusable descendant');
  }
  const row = options[0];
  const open = row.parentElement.querySelector('.mlv-issue__open');
  assert.ok(open && open.parentElement === row.parentElement, 'open is a sibling of the option, not a child');

  // one tab stop per listbox, not one per row plus one per icon
  const list = row.closest('[role="listbox"]');
  const stops = Array.from(list.querySelectorAll('[role="option"]')).filter((o) => o.tabIndex === 0);
  assert.equal(stops.length, 1, 'a roving tabindex, so the rail costs N Tab presses and not 2N');

  const active = stops[0];
  active.focus();
  key(ctx, active, 'ArrowDown');
  assert.notEqual(ctx.document.activeElement, active, 'ArrowDown moves inside the listbox');
  assert.equal(ctx.document.activeElement.getAttribute('role'), 'option');
  key(ctx, ctx.document.activeElement, 'Enter');
  assert.equal(ctx.app.getState().selection.kind, 'issue', 'Enter activates the row');
});

/* ── MLV-R2-W04: hover card had no delay and no flip/shift ───────────────── */

test('the hover card flips and shifts to stay inside the canvas (MLV-R2-W04)', async () => {
  const { tooltipPlacement } = (await loadBundle()).MLView.__internal;
  // A 72 px card anchored 40 px from the canvas top cannot go above it.
  const flipped = tooltipPlacement(500, 40, 108, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(flipped.below, true, 'it flips under the node');
  assert.ok(flipped.top >= 8, 'and lands inside the canvas: ' + flipped.top);

  const above = tooltipPlacement(500, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(above.below, false, 'with room above, it stays above');
  assert.equal(above.top, 388);

  const left = tooltipPlacement(10, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(left.left, 108, 'the left edge clears the canvas by the margin');
  const right = tooltipPlacement(995, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(right.left, 892);

  // Unmeasurable (jsdom, or before first paint): no guessing.
  const plain = tooltipPlacement(500, 40, 108, { w: 0, h: 0 }, { w: 0, h: 0 });
  assert.equal(plain.left, 500);
  assert.equal(plain.top, 28);
  assert.equal(plain.below, false);
});

/* ── MLV-R2-W05: an empty analysis reported a clean bill of health ───────── */

test('an analysis that found nothing does not congratulate the user (MLV-R2-W05)', async () => {
  const ctx = await loadBundle();
  const empty = JSON.parse(JSON.stringify(sample));
  empty.nodes = [];
  empty.edges = [];
  empty.issues = [];
  empty.diagnostics = [];
  empty.stats.issues = { low: 0, medium: 0, high: 0 };
  for (const stage of empty.stages) {
    stage.present = false;
    stage.nodeCount = 0;
  }
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), empty, ctx.MLView.bridges.standalone());
  const rail = ctx.document.querySelector('[id$="-panel-issues"]').textContent;
  const canvas = ctx.document.querySelector('.mlv-state--empty').textContent;
  assert.ok(canvas.indexOf('No ML pipeline found') >= 0);
  assert.equal(rail.indexOf('No issues found'), -1, 'the rail must not read as a clean result');
  assert.ok(rail.indexOf('Nothing analyzed') >= 0, 'it agrees with the canvas: ' + rail);
  assert.ok(rail.indexOf('files analyzed') >= 0);
  instance.destroy();
});

/* ── MLV-R2-W06: search truncated the issues away, unranked ──────────────── */

test('search ranks its hits and never starves the issues (MLV-R2-W06)', async () => {
  const ctx = await loadBundle();
  const { GraphIndex, searchGraph } = ctx.MLView.__internal;
  const index = new GraphIndex(makeSyntheticGraph(150, 200));
  // 'synthetic' matches all 150 node sublabels and all 24 issue titles: the old
  // code filled the 40-hit budget with nodes and dropped every issue silently.
  const hits = searchGraph(index, 'synthetic');
  assert.equal(hits.length, 40);
  assert.ok(hits.filter((h) => h.kind === 'issue').length > 0, 'issue hits survive a node-heavy query');
  assert.ok(hits.filter((h) => h.kind === 'node').length > 0);

  // Relevance, not document order: the exact prefix match sits 95 nodes later in
  // the graph than the substring match, and must still come out first.
  const graph = makeSyntheticGraph(150, 200);
  graph.nodes[5].sublabel = 'contains zebra somewhere';
  graph.nodes[100].label = 'zebra';
  const ranked = searchGraph(new GraphIndex(graph), 'zebra');
  assert.equal(ranked.length, 2);
  assert.equal(ranked[0].label, 'zebra', 'the prefix match ranks above the substring match');
  assert.equal(ranked[0].id, graph.nodes[100].id);
});

/* ── MLV-R2-W07: the combobox never set aria-activedescendant ────────────── */

test('the search combobox points at its active option (MLV-R2-W07)', async () => {
  const ctx = await app();
  const input = ctx.document.querySelector('.mlv-search .mlv-input');
  input.value = 'train';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const options = Array.from(ctx.document.querySelectorAll('.mlv-search__results .mlv-result'));
  assert.ok(options.length > 1);
  for (const option of options) assert.ok(option.id, 'every option carries an id');
  assert.equal(input.getAttribute('aria-activedescendant'), options[0].id);
  key(ctx, input, 'ArrowDown');
  // the list is rebuilt on every cursor move, so re-query it
  const moved = Array.from(ctx.document.querySelectorAll('.mlv-search__results .mlv-result'));
  assert.equal(input.getAttribute('aria-activedescendant'), moved[1].id, 'it follows the cursor');
  assert.equal(moved[1].getAttribute('aria-selected'), 'true');
  assert.equal(moved[0].getAttribute('aria-selected'), 'false');

  input.value = '';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.equal(input.getAttribute('aria-activedescendant'), null, 'and is dropped when the list closes');
});

/* ── MLV-R2-W08: the Outline was not navigable as a tree ─────────────────── */

test('the Outline is a navigable tree with jumpable lanes (MLV-R2-W08)', async () => {
  const ctx = await app();
  const tree = ctx.document.querySelector('[role="tree"]');
  const items = Array.from(tree.querySelectorAll('[role="treeitem"]'));
  assert.ok(items.length > 0);
  assert.equal(items.filter((i) => i.tabIndex === 0).length, 1, 'exactly one roving tab stop');
  assert.equal(tree.querySelectorAll('button').length, 0, 'the rows are not a flat run of buttons');

  const first = items.filter((i) => i.tabIndex === 0)[0];
  first.focus();
  key(ctx, first, 'ArrowDown');
  assert.notEqual(ctx.document.activeElement, first, 'ArrowDown moved the focus');
  assert.equal(ctx.document.activeElement.getAttribute('role'), 'treeitem');
  assert.equal(
    Array.from(tree.querySelectorAll('[role="treeitem"]')).filter((i) => i.tabIndex === 0).length,
    1,
    'still exactly one tab stop',
  );

  const lane = tree.querySelector('[data-outline-lane="train"]');
  assert.ok(lane, 'stages are in the tree');
  click(ctx, lane.querySelector('.mlv-outline__row'));
  const selected = ctx.app.getState().selection;
  assert.equal(selected.kind, 'node');
  const node = sample.nodes.filter((n) => n.id === selected.id)[0];
  assert.equal(node.stage, 'train', 'a lane row jumps to that stage');
});

test('the Outline mirrors the canvas collapse state (MLV-R2-W08)', async () => {
  const ctx = await app();
  const groupId = 'n:5500cc66dd77';
  const item = () => ctx.document.querySelector('[data-outline-id="' + groupId + '"]');
  assert.equal(item().getAttribute('aria-expanded'), 'true');

  const header = ctx.document.querySelector('[data-node-id="' + groupId + '"] .mlv-group__header');
  click(ctx, header, 'dblclick');
  assert.equal(item().getAttribute('aria-expanded'), 'false', 'collapsing on the canvas collapses the tree');
  assert.equal(item().querySelector('[role="group"]').hidden, true);

  item().focus();
  key(ctx, item(), 'ArrowRight');
  assert.equal(ctx.app.getState().collapsed.length, 0, 'ArrowRight expands the group on the canvas');
  assert.equal(item().getAttribute('aria-expanded'), 'true');
  key(ctx, item(), 'ArrowLeft');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), [groupId]);
});

/* ── MLV-R2-W09: a permanently struck-out, countless suppressed chip ─────── */

test('the suppressed chip appears only when something is suppressed (MLV-R2-W09)', async () => {
  const ctx = await app();
  const chipOf = (doc) =>
    Array.from(doc.querySelectorAll('.mlv-toolbar .mlv-chip--btn')).filter(
      (b) => (b.textContent || '').indexOf('suppressed') >= 0,
    )[0];
  const chip = chipOf(ctx.document);
  assert.ok(chip, 'the control exists');
  assert.equal(chip.hidden, true, 'but is not shown when nothing is suppressed');

  const other = await loadBundle();
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues[0].suppressed = true;
  graph.issues[1].suppressed = true;
  const instance = other.MLView.mount(
    other.document.getElementById('mlview-root'),
    graph,
    other.MLView.bridges.standalone(),
  );
  const shown = chipOf(other.document);
  assert.equal(shown.hidden, false);
  assert.equal(shown.textContent, '2 suppressed', 'and it carries a count like the severity chips');
  instance.destroy();
});

/* ── MLV-R2-W10: the toast stack was aria-hidden ─────────────────────────── */

test('toast-only messages reach assistive tech (MLV-R2-W10)', async () => {
  const ctx = await app();
  const stack = ctx.document.querySelector('.mlv-toasts');
  assert.equal(stack.getAttribute('aria-hidden'), null, 'the stack is not hidden from AT');
  assert.equal(stack.getAttribute('role'), 'status', 'it is a polite live region');
  ctx.app.focusNode('n:000000000000');
  assert.ok(stack.textContent.indexOf('Node not found') >= 0, 'the refusal is announced: ' + stack.textContent);
});

/* ── MLV-R2-W11: chips duplicated the sublabel and clipped ───────────────── */

test('node chips never repeat what the sublabel already says (MLV-R2-W11)', async () => {
  const ctx = await app();
  const cards = Array.from(ctx.document.querySelectorAll('.mlv-node[data-node-id]'));
  let checked = 0;
  let withChips = 0;
  for (const card of cards) {
    const sub = card.querySelector('.mlv-node__sub');
    const chips = Array.from(card.querySelectorAll('.mlv-node__chips .mlv-chip'));
    if (chips.length) withChips++;
    if (!sub || !chips.length) continue;
    for (const chip of chips) {
      const text = chip.textContent || '';
      if (text.charAt(0) === '+') continue;
      assert.equal(sub.textContent.indexOf(text), -1, card.getAttribute('data-node-id') + ' repeats "' + text + '"');
      checked++;
    }
  }
  assert.ok(withChips > 0, 'the sample really does render attribute chips');
  assert.ok(checked >= 0);
});

/* ── MLV-R2-W12: the minimap appeared at 8 nodes and never went away ─────── */

test('the minimap appears only above 30 nodes and collapses away (MLV-R2-W12)', async () => {
  const small = await app();
  assert.equal(small.document.querySelector('.mlv-minimap').hidden, true, 'hidden for a small graph');

  const ctx = await loadBundle();
  const instance = ctx.MLView.mount(
    ctx.document.getElementById('mlview-root'),
    makeSyntheticGraph(150, 200),
    ctx.MLView.bridges.standalone(),
  );
  const minimap = ctx.document.querySelector('.mlv-minimap');
  assert.equal(minimap.hidden, false, 'shown once an overview is worth having');
  assert.ok(minimap.querySelectorAll('.mlv-minimap__node').length >= 30);

  const toggle = minimap.querySelector('.mlv-minimap__toggle');
  assert.ok(toggle, 'the promised collapse affordance exists');
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  click(ctx, toggle);
  assert.ok(minimap.classList.contains('is-collapsed'), 'it collapses to a tab');
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(instance.getState().minimapCollapsed, true, 'and the flag survives a reload');
  instance.destroy();
});
