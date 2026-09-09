/**
 * NB, viewer half — notebook locations and the execution-order caveat.
 *
 * The analyzer concatenates a notebook's code cells into one shadow module and
 * emits a FLAT line into that concatenation, which is the right thing to put on
 * the wire and the wrong thing to show a human. These tests hold both halves of
 * that at once:
 *
 *   1. every surface that shows a location — card, rail row, inspector,
 *      tooltip, search meta, SVG export — says `name.ipynb > cell 3 : 4`;
 *   2. `openLocation` still posts the FLAT line, byte for byte, because the
 *      hosts own the mapping onto a `vscode-notebook-cell:` URI (CONTRACTS §4
 *      is frozen and this feature does not touch it);
 *   3. nothing invents a cell — a `.ipynb` location with no mapping, or a
 *      half-written one, falls back to the flat line, which is always true;
 *   4. a notebook last run out of order raises a BANNER, because "the order you
 *      are reading is not the order this ran in" de-rates the fit-before-split
 *      family and has to be read before the findings it de-rates.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadBundle, readSample, DIST_CSS_DEV } from './helpers.mjs';

const sample = await readSample();
const devCss = await readFile(DIST_CSS_DEV, 'utf8');

/** A location inside a notebook cell, in the analyzer's shape. */
function nbLoc(file, flatLine, cell, cellLine, extra = {}) {
  return {
    file,
    absFile: '/w/' + file,
    line: flatLine,
    col: 0,
    endLine: flatLine,
    endCol: 12,
    cell,
    cellLine,
    ...extra,
  };
}

/**
 * The demo document with its first node and first issue moved into a notebook.
 * Everything else is untouched, so any assertion that fires is about NB.
 */
function withNotebook(graph, opts = {}) {
  const g = JSON.parse(JSON.stringify(graph));
  const node = g.nodes[0];
  node.loc = nbLoc('notebooks/leak.ipynb', 27, 3, 4, { snippet: node.loc.snippet, symbol: node.loc.symbol });
  const issue = g.issues[0];
  issue.loc = nbLoc('notebooks/leak.ipynb', 27, 3, 4);
  issue.nodeIds = [node.id];
  node.issueIds = [issue.id];
  if (issue.relatedLocs && issue.relatedLocs.length) {
    issue.relatedLocs[0] = { ...issue.relatedLocs[0], ...nbLoc('notebooks/leak.ipynb', 41, 5, 2) };
  }
  if (opts.diagnostics) g.diagnostics = opts.diagnostics;
  return { graph: g, node, issue };
}

async function mount(graph, posted = []) {
  const ctx = await loadBundle();
  const bridge = {
    host: 'standalone',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
    post: (m) => posted.push(m),
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app, posted };
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

/* ── 1. the translation itself ─────────────────────────────────────────── */

test('a cell-mapped location reads as "name.ipynb > cell 3 : 4" (NB)', async () => {
  const ctx = await loadBundle();
  const { locLabel, locSpoken, locTitle } = ctx.MLView.__internal.notebook;
  const loc = nbLoc('notebooks/leak.ipynb', 27, 3, 4);
  assert.equal(locLabel(loc), 'notebooks/leak.ipynb > cell 3 : 4');
  // A screen reader should not have to decode `>` and `:`.
  assert.equal(locSpoken(loc), 'notebooks/leak.ipynb cell 3 line 4');
  // ...and the flat line is never lost: it is what the host is sent.
  assert.equal(locTitle(loc), 'notebooks/leak.ipynb cell 3 line 4 — line 27 of the concatenated code cells');
});

test('a .py location is byte-identical to what it always was (NB)', async () => {
  const ctx = await loadBundle();
  const { locLabel, locSpoken, locTitle } = ctx.MLView.__internal.notebook;
  const loc = { file: 'src/train.py', line: 27 };
  assert.equal(locLabel(loc), 'src/train.py:27');
  assert.equal(locSpoken(loc), 'src/train.py line 27');
  // Nothing extra to say, so nothing is said — no invented hover on a .py row.
  assert.equal(locTitle(loc), '');
});

test('nothing invents a cell the analyzer did not map (NB)', async () => {
  const ctx = await loadBundle();
  const { cellRef, locLabel } = ctx.MLView.__internal.notebook;
  // A notebook path is NOT itself a mapping. Guessing one here would produce a
  // click-to-code that looks right and lands in the wrong cell.
  const unmapped = { file: 'notebooks/leak.ipynb', line: 27 };
  assert.equal(cellRef(unmapped), null);
  assert.equal(locLabel(unmapped), 'notebooks/leak.ipynb:27');

  // Half a mapping is no mapping.
  assert.equal(cellRef({ file: 'a.ipynb', line: 9, cell: 2 }), null);
  assert.equal(cellRef({ file: 'a.ipynb', line: 9, cellLine: 2 }), null);
  // And an impossible one is no mapping either: cells count from zero at the
  // lowest, cell lines from one.
  assert.equal(cellRef({ file: 'a.ipynb', line: 9, cell: -1, cellLine: 2 }), null);
  assert.equal(cellRef({ file: 'a.ipynb', line: 9, cell: 1, cellLine: 0 }), null);
  assert.equal(cellRef({ file: 'a.ipynb', line: 9, cell: 1, cellLine: Number.NaN }), null);
  // Cell 0 is legal — only the analyzer knows whether it counted from zero, and
  // this renderer prints its number verbatim rather than adding one.
  const zero = cellRef({ file: 'a.ipynb', line: 9, cell: 0, cellLine: 1 });
  assert.deepEqual({ cell: zero.cell, line: zero.line }, { cell: 0, line: 1 });
  assert.equal(locLabel({ file: 'a.ipynb', line: 9, cell: 0, cellLine: 1 }), 'a.ipynb > cell 0 : 1');
});

test('the alias spelling of the mapping is read too (NB, interop)', async () => {
  const ctx = await loadBundle();
  const { locLabel, cellRef } = ctx.MLView.__internal.notebook;
  // See the NOTE ON SPELLING in notebook.ts. `{cell, cellLine}` is the pair this
  // renderer expects; `{notebookCell, notebookCellLine}` is read as well so the
  // viewer half and the analyzer half of NB cannot ship broken against each
  // other over a naming difference. The primary spelling wins when both appear.
  const alias = { file: 'a.ipynb', line: 9, notebookCell: 2, notebookCellLine: 5 };
  assert.equal(locLabel(alias), 'a.ipynb > cell 2 : 5');
  const both = { file: 'a.ipynb', line: 9, cell: 1, cellLine: 1, notebookCell: 9, notebookCellLine: 9 };
  assert.equal(cellRef(both).cell, 1);
  assert.equal(cellRef(both).line, 1);
});

test('the alias spelling of the out-of-order kind raises the same banner (NB, interop)', async () => {
  const { graph } = withNotebook(sample, {
    diagnostics: [{ kind: 'notebook_execution_order', message: 'ran out of order', file: 'a.ipynb', codes: ['MLV101'] }],
  });
  const ctx = await mount(graph);
  const banner = ctx.document.querySelector('[data-notebook-order-banner]');
  assert.ok(banner, 'the honesty half of NB must not be the half that silently fails to draw');
  assert.ok(banner.textContent.indexOf('a.ipynb was last run out of order') >= 0, banner.textContent);
  // ...and it is claimed, so it does not ALSO become a generic chip.
  assert.equal(ctx.document.querySelector('[data-diagnostic-kind="notebook_execution_order"]'), null);
});

test('isNotebookPath is presentation only, and case-insensitive (NB)', async () => {
  const ctx = await loadBundle();
  const { isNotebookPath } = ctx.MLView.__internal.notebook;
  assert.equal(isNotebookPath('a/b/Leak.IPYNB'), true);
  assert.equal(isNotebookPath('a/b/train.py'), false);
  assert.equal(isNotebookPath('ipynb'), false);
  assert.equal(isNotebookPath(undefined), false);
});

test('the stylesheet shrinks the path and never the cell (NB)', async () => {
  // jsdom has no layout, so this is the one thing the DOM tests cannot observe:
  // that `notebooks/leak.ipynb > cell 3 : 4` in a card too narrow for it loses
  // the directory rather than the answer. The rule itself is the gate.
  const loc = devCss.slice(devCss.indexOf('.mlv-loc {'));
  assert.ok(loc.indexOf('display: inline-flex') > 0, 'the label is a flex box, so its two halves shrink independently');
  const file = loc.slice(loc.indexOf('.mlv-loc__file {'), loc.indexOf('.mlv-loc__at {'));
  assert.ok(file.indexOf('text-overflow: ellipsis') > 0, 'the PATH is the half that ellipsises');
  assert.ok(file.indexOf('min-width: 0') > 0, 'and it is allowed to shrink below its content');
  const at = loc.slice(loc.indexOf('.mlv-loc__at {'));
  assert.ok(at.indexOf('flex: 0 0 auto') > 0, 'the cell reference never shrinks');
  assert.equal(at.slice(0, at.indexOf('}')).indexOf('text-overflow'), -1, 'and never ellipsises');
  // The card's own rule delegates to it rather than end-ellipsising the whole
  // string, which is what used to cut `> cell 3 : 4` off entirely.
  const card = devCss.slice(devCss.indexOf('.mlv-node__loc {'));
  const body = card.slice(0, card.indexOf('}'));
  assert.ok(body.indexOf('display: flex') > 0, body);
  assert.equal(body.indexOf('text-overflow'), -1, body);
});

/* ── 2. the four surfaces ──────────────────────────────────────────────── */

test('the node card shows the cell, and keeps the flat line in its hover (NB)', async () => {
  const { graph, node } = withNotebook(sample);
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-node-id="' + node.id + '"]');
  assert.ok(card, 'the notebook node is drawn');
  const locEl = card.querySelector('.mlv-node__loc');
  assert.equal(locEl.textContent, 'notebooks/leak.ipynb > cell 3 : 4');
  assert.equal(locEl.getAttribute('data-cell'), '3');
  assert.equal(locEl.getAttribute('data-cell-line'), '4');
  assert.ok(locEl.title.indexOf('line 27 of the concatenated code cells') > 0, locEl.title);
  // The card's accessible name says the same thing in words, not in punctuation.
  assert.ok(card.getAttribute('aria-label').indexOf('notebooks/leak.ipynb cell 3 line 4') >= 0, card.getAttribute('aria-label'));
});

test('the rail row and its aria label show the cell (NB)', async () => {
  const { graph, issue } = withNotebook(sample);
  const ctx = await mount(graph);
  const row = ctx.document.querySelector('.mlv-issue[data-issue-id="' + issue.id + '"]');
  assert.ok(row, 'the notebook finding is listed');
  const locEl = row.querySelector('.mlv-issue__meta [data-cell]');
  assert.ok(locEl, 'the row carries a cell-marked location');
  assert.equal(locEl.textContent, 'notebooks/leak.ipynb > cell 3 : 4');
  assert.equal(locEl.getAttribute('data-cell-line'), '4');
  assert.ok(row.getAttribute('aria-label').indexOf('notebooks/leak.ipynb cell 3 line 4') >= 0, row.getAttribute('aria-label'));
  // The row's "open in editor" button names it too, so its tooltip is not the
  // one place in the product that still says line 27.
  const open = ctx.document.querySelector('.mlv-issue__open');
  assert.ok(open.getAttribute('aria-label').indexOf('cell 3 : 4') > 0, open.getAttribute('aria-label'));
});

test('the inspector shows the cell on the node and on every related location (NB)', async () => {
  const { graph, node, issue } = withNotebook(sample);
  const ctx = await mount(graph);
  ctx.app.focusNode(node.id);
  const tab = ctx.document.querySelector('[data-rail-tab="inspector"]');
  if (tab) click(ctx, tab);
  const openBtn = ctx.document.querySelector('.mlv-insp__actions .mlv-btn--primary');
  assert.equal(openBtn.textContent, 'Open notebooks/leak.ipynb > cell 3 : 4');
  assert.equal(openBtn.getAttribute('data-cell'), '3');
  assert.ok(openBtn.title.indexOf('line 27') > 0, openBtn.title);
  if ((issue.relatedLocs || []).length) {
    const links = Array.from(ctx.document.querySelectorAll('.mlv-insp__related .mlv-link')).map((b) => b.textContent);
    assert.ok(
      links.some((t) => t.indexOf('notebooks/leak.ipynb > cell 5 : 2') >= 0),
      links.join(' | '),
    );
  }
});

test('the tooltip shows the cell (NB)', async () => {
  const { graph, node } = withNotebook(sample);
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-node-id="' + node.id + '"]');
  // UX_DESIGN section 9: the hover card waits 400 ms before it commits.
  card.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
  await new Promise((r) => setTimeout(r, 520));
  const tooltip = ctx.document.querySelector('.mlv-tooltip');
  assert.equal(tooltip.hidden, false, 'the hover card is open');
  const tip = tooltip.querySelector('.mlv-tooltip__loc');
  assert.ok(tip, 'the hover card names a location');
  assert.equal(tip.textContent, 'notebooks/leak.ipynb > cell 3 : 4');
  assert.equal(tip.getAttribute('data-cell'), '3');
});

test('search results are pinned by cell, not by a line nobody can see (NB)', async () => {
  const { graph, node, issue } = withNotebook(sample);
  const ctx = await mount(graph);
  const { searchGraph } = ctx.MLView.__internal;
  const index = new ctx.MLView.__internal.GraphIndex(graph);
  const hits = searchGraph(index, 'leak.ipynb');
  const nodeHit = hits.find((h) => h.id === node.id);
  const issueHit = hits.find((h) => h.id === issue.id);
  assert.ok(nodeHit || issueHit, 'the notebook path is searchable');
  for (const h of [nodeHit, issueHit]) {
    if (h) assert.equal(h.meta, 'notebooks/leak.ipynb > cell 3 : 4');
  }
});

test('the SVG export prints the cell, like the card it is a picture of (NB)', async () => {
  const { graph } = withNotebook(sample);
  const ctx = await mount(graph);
  const built = ctx.MLView.__internal.exportDiagram.build(graph, { theme: 'light', region: 'diagram' });
  const svg = typeof built === 'string' ? built : built.svg || built.markup || '';
  assert.ok(svg.length > 0, 'the export produced markup');
  assert.ok(svg.indexOf('cell 3 : 4') > 0, 'the exported card still says which cell');
  // The flat line is not printed on the card in either renderer, so an exported
  // picture cannot disagree with the screen it was taken from.
  assert.equal(svg.indexOf('leak.ipynb:27'), -1);
});

/* ── 3. the wire is untouched ──────────────────────────────────────────── */

test('openLocation still posts the FLAT line — hosts own the cell mapping (NB)', async () => {
  const { graph, issue } = withNotebook(sample);
  const posted = [];
  const ctx = await mount(graph, posted);
  const open = ctx.document.querySelector('.mlv-issue__open');
  click(ctx, open);
  const msg = posted.find((m) => m.type === 'openLocation');
  assert.ok(msg, 'clicking Open posts openLocation');
  assert.equal(msg.line, 27, 'the FLAT line, exactly as the analyzer emitted it');
  assert.equal(msg.file, 'notebooks/leak.ipynb');
  assert.equal(msg.absFile, '/w/notebooks/leak.ipynb');
  // CONTRACTS §4 froze this frame at six fields plus `preview`. NB adds none:
  // a host that has never heard of a notebook cell reads exactly what it read
  // before, and a host that has, maps the flat line itself.
  assert.equal(Object.keys(msg).sort().join(','), 'absFile,col,endCol,endLine,file,line,preview,type,v');
});

/* ── 4. the execution-order caveat ─────────────────────────────────────── */

const OUT_OF_ORDER = [
  {
    kind: 'notebook_out_of_order',
    message: 'notebooks/leak.ipynb was last run with execution_count [1, 3, 2, 4].',
    file: 'notebooks/leak.ipynb',
    codes: ['MLV101', 'MLV203', 'MLV209'],
  },
];

test('an out-of-order notebook raises a banner that names the de-rated rules (NB)', async () => {
  const { graph } = withNotebook(sample, { diagnostics: OUT_OF_ORDER });
  const ctx = await mount(graph);
  const banner = ctx.document.querySelector('[data-notebook-order-banner]');
  assert.ok(banner, 'the caveat is a banner, not a chip');
  assert.equal(banner.getAttribute('data-notebook-order-banner'), '1');
  const text = banner.textContent;
  assert.ok(text.indexOf('notebooks/leak.ipynb was last run out of order') >= 0, text);
  // It says WHY it cannot know better, rather than implying the result is safe.
  assert.ok(text.indexOf('read the cells top to bottom') > 0, text);
  assert.ok(text.indexOf('MLV101, MLV203, MLV209') > 0, text);
  assert.ok(text.indexOf('may be missing entirely') > 0, text);
  // The diagnostic's own message is the banner's detail, so the actual
  // execution_count is one glance away.
  assert.ok(banner.querySelector('.mlv-banner__detail').textContent.indexOf('[1, 3, 2, 4]') > 0);
  // And it does NOT also become a chip.
  assert.equal(ctx.document.querySelector('[data-diagnostic-kind="notebook_out_of_order"]'), null);
});

test('the caveat is read before the coverage banner it de-rates (NB)', async () => {
  const { graph } = withNotebook(sample, {
    diagnostics: OUT_OF_ORDER.concat([{ kind: 'untagged_dataflow', message: 'two values not traced', count: 2 }]),
  });
  const ctx = await mount(graph);
  const banners = Array.from(ctx.document.querySelectorAll('.mlv-banner'));
  const order = banners.indexOf(ctx.document.querySelector('[data-notebook-order-banner]'));
  const coverage = banners.indexOf(ctx.document.querySelector('[data-coverage-banner]'));
  assert.ok(order >= 0 && coverage >= 0, 'both banners are drawn');
  assert.ok(order < coverage, 'execution order outranks coverage');
});

test('several out-of-order notebooks are one banner, and it can be dismissed (NB)', async () => {
  const diags = [
    { kind: 'notebook_out_of_order', message: 'a ran out of order', file: 'a.ipynb', codes: ['MLV101'] },
    { kind: 'notebook_out_of_order', message: 'b ran out of order', file: 'b.ipynb', codes: ['MLV101', 'MLV209'] },
  ];
  const { graph } = withNotebook(sample, { diagnostics: diags });
  const ctx = await mount(graph);
  const banner = ctx.document.querySelector('[data-notebook-order-banner]');
  assert.equal(banner.getAttribute('data-notebook-order-banner'), '2');
  const text = banner.textContent;
  assert.ok(text.indexOf('a.ipynb, b.ipynb were last run out of order') >= 0, text);
  // De-rated codes are the union, deduplicated, in the order they were reported.
  assert.ok(text.indexOf('(MLV101, MLV209)') > 0, text);
  const dismiss = banner.querySelector('.mlv-btn--icon');
  click(ctx, dismiss);
  assert.equal(ctx.document.querySelector('[data-notebook-order-banner]'), null, 'dismissible like every other banner');
});

test('the headline degrades cleanly when a diagnostic names no file or code (NB)', async () => {
  const ctx = await loadBundle();
  const { headline, outOfOrderFiles, derated } = ctx.MLView.__internal.notebook;
  const bare = [{ kind: 'notebook_out_of_order', message: 'a notebook ran out of order' }];
  // Joined, not deep-compared: these arrays come from the bundle's realm.
  assert.equal(outOfOrderFiles(bare).join(','), '');
  assert.equal(derated(bare).join(','), '');
  const text = headline(bare);
  assert.ok(text.indexOf('1 notebook was last run out of order') >= 0, text);
  // No parenthesis with nothing in it.
  assert.equal(text.indexOf('()'), -1, text);
});

test('a run that DID read notebooks says so, instead of vanishing into "N notes" (NB)', async () => {
  const { graph } = withNotebook(sample, {
    diagnostics: [{ kind: 'notebook_analyzed', message: '2 notebooks analyzed as 41 code cells', count: 2 }],
  });
  const ctx = await mount(graph);
  const chip = ctx.document.querySelector('[data-notebooks-analyzed]');
  assert.ok(chip, 'notebook_analyzed was in the "specially rendered" list with nothing rendering it');
  assert.equal(chip.textContent, '2 notebooks analyzed');
  assert.ok(chip.title.indexOf('41 code cells') > 0);
  // It is news, not a warning: no banner, and no coverage claim.
  assert.equal(ctx.document.querySelector('[data-notebook-order-banner]'), null);
  assert.equal(ctx.document.querySelector('[data-coverage-banner]'), null);
});

test('without the flag, a document is exactly what it was (NB)', async () => {
  // The whole feature is inert on a document that carries no cell mapping and
  // no notebook diagnostic — which is every document `--include-notebooks` was
  // not passed for.
  const ctx = await mount(sample);
  assert.equal(ctx.document.querySelector('[data-cell]'), null);
  assert.equal(ctx.document.querySelector('[data-notebook-order-banner]'), null);
  assert.equal(ctx.document.querySelector('[data-notebooks-analyzed]'), null);
  const locs = Array.from(ctx.document.querySelectorAll('.mlv-node__loc')).map((e) => e.textContent);
  assert.ok(locs.length > 0);
  for (const t of locs) assert.match(t, /^[^>]+:\d+$/, t);
});

/* ── 5. reconciled against 11.29, i.e. what the analyzer REALLY emits ──── */

/*
 * This suite was written before the analyzer half of NB landed, against an
 * inferred contract: optional `Loc.cell` / `Loc.cellLine` fields and a
 * `notebook_out_of_order` diagnostic kind. 11.29 settled it differently, and
 * these four cases pin the renderer to the settled shape:
 *
 *   N6  — the mapping lives in `Node.attrs`, as STRINGS, because `Loc` is
 *         frozen by §2. `adoptCellMap` lifts it onto the node's own `Loc` once
 *         per document, so the twelve label surfaces above are unchanged.
 *   N10 — there is ONE `notebook_analyzed` per analyzed notebook, and the
 *         out-of-order verdict is carried by its `codes`, not by a kind of its
 *         own. The banner has to read that, or the honesty half of NB never
 *         draws against a real run.
 *
 * The aliases the earlier cases exercise are kept deliberately, for a host that
 * hands the viewer a document from a newer analyzer.
 */

/** The demo document with its first node mapped the way 11.29 N6 maps it. */
function withAttrsMapping(graph, attrs) {
  const g = JSON.parse(JSON.stringify(graph));
  const node = g.nodes[0];
  node.loc = { ...node.loc, file: 'notebooks/leak.ipynb', line: 27 };
  node.attrs = { ...(node.attrs || {}), ...attrs };
  return { graph: g, node };
}

test('the cell map is lifted off Node.attrs, where 11.29 N6 puts it (NB)', async () => {
  const { graph, node } = withAttrsMapping(sample, {
    notebook: 'notebooks/leak.ipynb',
    cell: '3',
    cellLine: '4',
  });
  // The document as it arrives carries NO cell on the Loc — only strings in attrs.
  assert.equal(graph.nodes[0].loc.cell, undefined);
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-node-id="' + node.id + '"]');
  const loc = card.querySelector('.mlv-node__loc');
  assert.equal(loc.textContent, 'notebooks/leak.ipynb > cell 3 : 4');
  assert.equal(loc.getAttribute('data-cell'), '3');
  assert.equal(loc.getAttribute('data-cell-line'), '4');
  // ...and the flat line is still one hover away.
  assert.ok(loc.title.indexOf('line 27 of the concatenated code cells') > 0, loc.title);
});

test('a half-written or non-numeric attrs mapping invents nothing (NB)', async () => {
  for (const attrs of [
    { notebook: 'notebooks/leak.ipynb', cell: '3' },
    { notebook: 'notebooks/leak.ipynb', cellLine: '4' },
    { notebook: 'notebooks/leak.ipynb', cell: 'three', cellLine: '4' },
    { notebook: 'notebooks/leak.ipynb', cell: '3', cellLine: '' },
    { notebook: 'notebooks/leak.ipynb' },
  ]) {
    const { graph, node } = withAttrsMapping(sample, attrs);
    const ctx = await mount(graph);
    const card = ctx.document.querySelector('[data-node-id="' + node.id + '"]');
    const loc = card.querySelector('.mlv-node__loc');
    assert.equal(loc.textContent, 'notebooks/leak.ipynb:27', JSON.stringify(attrs));
    assert.equal(loc.getAttribute('data-cell'), null, JSON.stringify(attrs));
  }
});

test('11.29 N10: notebook_analyzed WITH codes is the out-of-order caveat (NB)', async () => {
  // The exact shape core/pipeline._ingest_notebooks emits for a notebook whose
  // execution_count is not monotonic: one diagnostic, the .ipynb as `file`, the
  // code-cell count, and ORDER_SENSITIVE_CODES as `codes`.
  const { graph } = withNotebook(sample, {
    diagnostics: [
      {
        kind: 'notebook_analyzed',
        message: 'notebooks/leak.ipynb: 4 cells, last run out of order (execution_count 1, 3, 2, 4)',
        file: 'notebooks/leak.ipynb',
        count: 4,
        codes: ['MLV101', 'MLV203', 'MLV209'],
      },
    ],
  });
  const ctx = await mount(graph);
  const banner = ctx.document.querySelector('[data-notebook-order-banner]');
  assert.ok(banner, 'a real out-of-order run must raise the banner, not just a chip');
  const text = banner.textContent;
  assert.ok(text.indexOf('notebooks/leak.ipynb was last run out of order') >= 0, text);
  assert.ok(text.indexOf('(MLV101, MLV203, MLV209)') >= 0, text);
  assert.ok(text.indexOf('execution_count 1, 3, 2, 4') >= 0, text);
  // The notebook WAS analyzed, so the chip is still owed alongside the caveat.
  const chip = ctx.document.querySelector('[data-notebooks-analyzed]');
  assert.ok(chip, 'an out-of-order notebook was still read, and the chip says so');
  assert.equal(chip.textContent, '4 notebooks analyzed');
});

test('an IN-ORDER notebook draws the chip and no caveat (NB)', async () => {
  // Same kind, no `codes` — 11.29 N10's other half. Drawing the banner here
  // would cry wolf on every notebook the tool ever reads.
  const { graph } = withNotebook(sample, {
    diagnostics: [
      {
        kind: 'notebook_analyzed',
        message: 'notebooks/leak.ipynb: 4 cells, run in order',
        file: 'notebooks/leak.ipynb',
        count: 4,
      },
    ],
  });
  const ctx = await mount(graph);
  assert.equal(ctx.document.querySelector('[data-notebook-order-banner]'), null);
  assert.ok(ctx.document.querySelector('[data-notebooks-analyzed]'));
});
