// Viewer M3, roadmap step 11: the claim-by-claim review walk, webview side.
//
// The fixtures are SYNTHETIC: generated documents with the shapes of the two public shakedown
// artifacts the design was measured on (vit-cc: 6 phases, 31 steps in two groups, 41 connections,
// 7 findings, 7 claims not observed; yolov5-cc2: 4 phases, 59 steps in two groups, 113
// connections, 4 findings, 16 claims not observed, two steps without quotes), plus small
// hand-made documents for the order rules. No third-party text is used. The shipped stylesheet is
// injected into jsdom; jsdom lays nothing out, so the panel width is a stubbed
// `getBoundingClientRect`, and the host is the test's recording bridge, which answers the walk's
// opens by hand. None of this is a live VS Code check, a usability check or a semantic review.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { inPane, loadBundle, recordingBridge, shapedWorkflow, stubPaneLayout, VIT_SHAPE, WEBVIEW_ROOT, YOLO_SHAPE } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
/** Values from the page's realm compared by content (their prototypes are the page's). */
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const eq = (actual, expected, message) => (message === undefined ? assert.deepEqual(plain(actual), plain(expected)) : assert.deepEqual(plain(actual), plain(expected), message));

/* ── synthetic documents ─────────────────────────────────────────────── */

// The shaped synthetic documents (`shapedWorkflow`, VIT_SHAPE, YOLO_SHAPE) moved to helpers.mjs in
// viewer M3 step 13, so the phase overview's tests read the same shapes.

/** A small document for the order rules, with groups, a cross-phase parent and homeless findings. */
function orderDoc() {
  const ev = (id, file = 'train.py', line = 1) => ({ id, file, line, endLine: line + 1, quote: 'x()' });
  return {
    workflowVersion: '1.0', title: 'Order rules', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'o1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      // Listed fit-first: drawn order still starts with the Data lane.
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', basis: 'inferred', evidence: ['e3', 'e4'] },
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'observed', evidence: ['e2'] },
      // A parent in another phase: drawn as a root of its own lane, after the lane's other roots.
      { id: 'sched', label: 'LR schedule', phase: 'data', parent: 'loop', basis: 'unresolved', evidence: [] },
      { id: 'zero', label: 'Zero grads', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e5'] },
    ],
    edges: [
      { id: 'c-step-zero', source: 'step', target: 'zero', label: 'then', basis: 'observed', evidence: ['e4'] },
      { id: 'c-load-aug', source: 'load', target: 'aug', label: 'images', basis: 'observed', evidence: ['e1'] },
      { id: 'c-aug-step', source: 'aug', target: 'step', label: 'batches', basis: 'inferred', evidence: ['e2', 'e3'] },
      { id: 'c-load-step', source: 'load', target: 'step', label: 'labels', basis: 'observed', evidence: ['e1'] },
    ],
    findings: [
      { id: 'f-whole', title: 'No seed', message: 'm', severity: 'low', nodeIds: [], basis: 'observed', evidence: ['e1'] },
      // Cites zero then aug: its first cited step in DRAWN order is aug (Data lane), not zero.
      { id: 'f-two', title: 'Order risk', message: 'm', severity: 'high', nodeIds: ['zero', 'aug'], basis: 'inferred', evidence: ['e5'], counterEvidence: ['e2'] },
      { id: 'f-edge', title: 'Cast on batches', message: 'm', severity: 'medium', nodeIds: [], edgeIds: ['c-aug-step'], basis: 'unresolved', evidence: ['e2'] },
      { id: 'f-step', title: 'Clip missing', message: 'm', severity: 'medium', nodeIds: ['step'], basis: 'observed', evidence: ['e3'] },
    ],
    evidence: [ev('e1', 'data.py', 3), ev('e2', 'data.py', 9), ev('e3', 'train.py', 4), ev('e4', 'train.py', 8), ev('e5', 'nb.ipynb', 2)].map((e) => (e.file === 'nb.ipynb' ? { ...e, cell: 7 } : e)),
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['data.py', 'train.py'], limitations: ['Launcher not read.'] },
  };
}

/* ── mounting ────────────────────────────────────────────────────────── */

async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  if (opts.bodyClass) ctx.document.body.classList.add(opts.bodyClass);
  const root = ctx.document.getElementById('mlview-root');
  let width = opts.width || 0;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: 798, right: width, bottom: 798 });
  const bridge = recordingBridge(ctx.window, 'vscode', { ...(opts.state ? { state: opts.state } : {}), ...(opts.capabilities ? { capabilities: opts.capabilities } : {}) });
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  const resize = (next) => {
    width = next;
    ctx.window.dispatchEvent(new ctx.window.Event('resize'));
  };
  const canvas = ctx.document.querySelector('.mlv-canvas');
  canvas.focus();
  return { ...ctx, root, bridge, app, resize, canvas };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const press = (ctx, key, init = {}, target = ctx.document.activeElement || ctx.canvas) => {
  const ev = new ctx.window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
};
const live = (ctx) => $(ctx, '.mlv-root > [aria-live]').textContent;
const opens = (ctx) => ctx.bridge.posted.filter((m) => m.type === 'openLocation');
const walkFrames = (ctx) => ctx.bridge.posted.filter((m) => m.type === 'walk');
const answer = (ctx, frame, outcome, extra = {}) =>
  ctx.bridge.send({ v: 1, type: 'actionResult', requestId: frame.requestId, action: 'openLocation', outcome, seq: frame.seq, ...extra });
const key = (claim) => claim.kind + ':' + claim.id;
/** Press `k` (or `j`) until the walk is on claim `id` (at most 20 presses, so a regression fails, never hangs). */
function walkTo(ctx, id, k) {
  for (let i = 0; i < 20 && (!ctx.app.walk.current() || ctx.app.walk.current().id !== id); i++) press(ctx, k);
  assert.equal(ctx.app.walk.current() && ctx.app.walk.current().id, id, 'the walk reached ' + id);
}

function visible(ctx, element) {
  if (!element) return false;
  for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
    if (node.hidden) return false;
    const style = ctx.window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
  }
  return true;
}

/* ── the order: every claim exactly once ─────────────────────────────── */

for (const [name, shape, totals] of [
  ['vit-cc', VIT_SHAPE, { steps: 31, connections: 41, findings: 7, all: 79, notObserved: 7 }],
  ['yolov5-cc2', YOLO_SHAPE, { steps: 59, connections: 113, findings: 4, all: 176, notObserved: 16 }],
]) {
  test(`the ${name} shape: the walk visits all ${totals.all} claims (${totals.steps}+${totals.connections}+${totals.findings}) exactly once, each step before its connections and findings`, async () => {
    const document = shapedWorkflow(shape);
    const ctx = await mount(document, { width: 1440 });
    try {
      const order = ctx.app.walk.claims();
      assert.equal(order.length, totals.all);
      assert.equal(new Set(order.map(key)).size, totals.all, 'no claim twice');
      for (const node of document.nodes) assert.equal(order.filter((c) => key(c) === 'node:' + node.id).length, 1, node.id);
      for (const edge of document.edges) assert.equal(order.filter((c) => key(c) === 'edge:' + edge.id).length, 1, edge.id);
      for (const finding of document.findings) assert.equal(order.filter((c) => key(c) === 'issue:' + finding.id).length, 1, finding.id);
      // Steps in drawn order: lanes in phase order, each lane as the Outline lists it.
      const outline = $$(ctx, '.mlv-rail__tab[data-tab="outline"]')[0];
      outline.click();
      const outlineSteps = $$(ctx, '[data-outline-id]').map((row) => row.getAttribute('data-outline-id'));
      eq(order.filter((c) => c.kind === 'node').map((c) => c.id), outlineSteps, 'steps in the Outline\'s (drawn) order');
      const phaseRank = new Map(document.phases.map((p, i) => [p.id, i]));
      const stepPhases = order.filter((c) => c.kind === 'node').map((c) => phaseRank.get(document.nodes.find((n) => n.id === c.id).phase));
      eq(stepPhases, stepPhases.slice().sort((a, b) => a - b), 'lanes in phase order');
      // Each connection right after its source step's block; each finding after its first cited step.
      const stepRank = new Map(order.filter((c) => c.kind === 'node').map((c, i) => [c.id, i]));
      let current = null;
      for (const claim of order) {
        if (claim.kind === 'node') current = claim.id;
        else if (claim.kind === 'edge') assert.equal(document.edges.find((e) => e.id === claim.id).source, current, claim.id + ' follows its source');
        else {
          const cited = document.findings.find((f) => f.id === claim.id).nodeIds.slice().sort((a, b) => stepRank.get(a) - stepRank.get(b));
          assert.equal(cited[0], current, claim.id + ' follows its first cited step');
        }
      }
    } finally {
      ctx.app.destroy();
    }
  });

  test(`the ${name} shape: each filter's count equals the header's count with its unit (Not observed ${totals.notObserved})`, async () => {
    const ctx = await mount(shapedWorkflow(shape), { width: 1440 });
    try {
      const chip = $(ctx, '.mlv-chip--exceptions');
      const headerNotObserved = Number(/^(\d+) not observed/.exec(chip.getAttribute('aria-label'))[1]);
      assert.equal(headerNotObserved, totals.notObserved);
      const severityTotal = $$(ctx, '.mlv-chip--sev .mlv-chip__count').reduce((sum, el) => sum + Number(el.textContent), 0);
      const status = $(ctx, '.mlv-status__counts').textContent;
      assert.equal(status, `${totals.steps} steps · ${totals.connections} connections`);
      press(ctx, 'r');
      const count = (filter) => Number($(ctx, `.mlv-walkbar__filter[data-walk-filter="${filter}"] .mlv-walkbar__fcount`).textContent);
      assert.equal(count('notObserved'), headerNotObserved, 'Not observed = the header chip');
      assert.equal(count('findings'), severityTotal, 'Findings = the severity toggles\' findings');
      assert.equal(count('all'), totals.steps + totals.connections + severityTotal, 'All = steps + connections + findings');
      assert.equal($(ctx, '.mlv-walkbar__filter[data-walk-filter="changed"]').hidden, true, 'no Changed files without stale files');
      // The default filter is Not observed, and the bar says so with the count.
      assert.equal($(ctx, '.mlv-walkbar__postext').textContent, `Claim 1 of ${totals.notObserved} · Not observed`);
      assert.equal($(ctx, '.mlv-walkbar__filter[aria-pressed="true"]').getAttribute('data-walk-filter'), 'notObserved');
      // Stepping through the whole filter visits each not-observed claim once.
      const seen = [];
      for (let i = 0; i < totals.notObserved; i++) {
        seen.push(key(ctx.app.walk.current()));
        press(ctx, 'j');
      }
      assert.equal(new Set(seen).size, totals.notObserved);
      assert.match(live(ctx), new RegExp(`^Claim ${totals.notObserved} of ${totals.notObserved} is the last one\\.$`));
    } finally {
      ctx.app.destroy();
    }
  });
}

test('order rules: lanes in phase order, a group before its steps, a step before its connections and the findings it hosts; findings with no cited step last', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    eq(ctx.app.walk.claims().map(key), [
      // Data lane: load, aug, then sched (its parent is in Fit, so it is a root of Data).
      'node:load', 'edge:c-load-aug', 'edge:c-load-step',
      'node:aug', 'edge:c-aug-step', 'issue:f-two',
      'node:sched',
      // Fit lane: the group, then its steps.
      'node:loop', 'node:step', 'edge:c-step-zero', 'issue:f-step', 'node:zero',
      // No cited step: the connection-only finding and the whole-workflow one, in document order.
      'issue:f-whole', 'issue:f-edge',
    ]);
  } finally {
    ctx.app.destroy();
  }
});

/* ── the keys ────────────────────────────────────────────────────────── */

test('r starts the walk on Not observed and ends it; the header Review button and the ⋯ item do the same', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    const bar = $(ctx, '.mlv-walkbar');
    const review = $(ctx, '.mlv-header__review');
    assert.equal(bar.hidden, true, 'no bar before the walk');
    assert.ok(visible(ctx, review), 'Review is on the header row');
    assert.equal(review.getAttribute('aria-pressed'), 'false');
    assert.equal(press(ctx, 'r').defaultPrevented, true);
    assert.equal(ctx.app.walk.active, true);
    assert.equal(bar.hidden, false);
    assert.equal(review.getAttribute('aria-pressed'), 'true');
    // The not-observed claims, in the drawn order.
    eq(ctx.app.walk.list.map(key), ['edge:c-aug-step', 'issue:f-two', 'node:sched', 'node:step', 'issue:f-edge']);
    eq(ctx.app.selection, ctx.app.walk.current(), 'the first claim is selected');
    assert.equal(ctx.app.getState().railTab, 'inspector', 'and shown in the Selection tab');
    press(ctx, 'r');
    assert.equal(ctx.app.walk.active, false);
    assert.equal(bar.hidden, true);
    eq(walkFrames(ctx).at(-1), { v: 1, type: 'walk', state: 'end' }, 'the host is told the walk ended');
    review.click();
    assert.equal(ctx.app.walk.active, true, 'the Review button starts it');
    review.click();
    assert.equal(ctx.app.walk.active, false, 'and ends it');
    $(ctx, '.mlv-btn--more').click();
    const item = $(ctx, '[data-more-item="review"]');
    assert.ok(visible(ctx, item));
    assert.equal(item.querySelector('.mlv-moremenu__label').textContent, 'Review the claims');
    assert.equal(item.querySelector('.mlv-moremenu__keys').textContent, 'R');
    item.click();
    assert.equal(ctx.app.walk.active, true, 'the ⋯ item starts it');
    $(ctx, '.mlv-btn--more').click();
    assert.equal($(ctx, '[data-more-item="review"] .mlv-moremenu__label').textContent, 'End the review');
  } finally {
    ctx.app.destroy();
  }
});

test('j / k and ↓ / ↑ step while walking; outside the walk the arrows move spatially and j, k, [ and ] are left alone', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { width: 1440 });
  try {
    ctx.app.select({ kind: 'node', id: ctx.app.walk.claims()[0].id });
    ctx.canvas.focus();
    for (const k of ['j', 'k', '[', ']']) assert.equal(press(ctx, k).defaultPrevented, false, k + ' is not consumed outside the walk');
    let before = ctx.app.selection.id;
    assert.equal(press(ctx, 'ArrowRight').defaultPrevented, true);
    assert.notEqual(ctx.app.selection.id, before, 'ArrowRight moved the selection spatially');
    before = ctx.app.selection.id;
    assert.equal(press(ctx, 'ArrowDown').defaultPrevented, true);
    assert.notEqual(ctx.app.selection.id, before, 'ArrowDown moved the selection spatially');
    ctx.canvas.focus();
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    const at = () => ctx.app.walk.position;
    const start = at();
    press(ctx, 'j');
    assert.equal(at(), start + 1);
    press(ctx, 'ArrowDown');
    assert.equal(at(), start + 2);
    press(ctx, 'k');
    press(ctx, 'ArrowUp');
    assert.equal(at(), start);
    eq(ctx.app.selection, ctx.app.walk.current(), 'each step selects its claim');
    // ← and → keep their spatial meaning during the walk; the walk follows a claim it holds.
    ctx.app.walk.setFilter('all');
    press(ctx, 'ArrowRight');
    eq(ctx.app.walk.current(), ctx.app.selection, 'the walk followed the spatial move');
    // No Ctrl/Cmd chord is answered by the walk.
    for (const init of [{ ctrlKey: true }, { metaKey: true }]) {
      for (const k of ['j', 'k', 'r', 'u', '[', ']']) assert.equal(press(ctx, k, init).defaultPrevented, false, k + ' with a modifier goes to VS Code');
    }
  } finally {
    ctx.app.destroy();
  }
});

test('[ and ] step through the claim\'s quotes; Enter opens the current quote again at once', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    // The first not-observed claim is the connection Augment → Optimizer step, with two quotes.
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    ctx.app.walk.flushOpen();
    assert.equal(opens(ctx).at(-1).evidenceId, 'e2');
    // The pane is 315 px tall; the second quote starts 490 px into it (helpers.mjs, stubPaneLayout).
    stubPaneLayout(ctx.window);
    const pane = $(ctx, '.mlv-rail [role="tabpanel"][data-tab="inspector"]');
    assert.equal(pane.scrollTop, 0);
    press(ctx, ']');
    assert.equal(live(ctx), 'Quote 2 of 2: train.py · lines 4–5.');
    // The pane's mark moves to the second quote at once and is scrolled into view (least distance):
    // its file line and the walk's line show, the walk's line 8 px above the pane's foot. (Since
    // the M3 live check, W1, the same rule brings a new claim's quote into view; it was
    // scrollIntoView({ block: 'nearest' }) on the whole quote.)
    const marked = $(ctx, '.mlv-quote.is-walk');
    assert.equal(marked, $$(ctx, '.mlv-sel .mlv-insp__source-evidence > .mlv-quote')[1]);
    assert.ok(inPane(marked.querySelector('.mlv-quote__head')) && inPane(marked.querySelector('.mlv-quote__walk')), 'the second quote shows');
    assert.equal(pane.scrollTop, 490 + 24 + 18 + 8 - 315);
    assert.equal($(ctx, '.mlv-walkbar__editor').getAttribute('data-walk-status'), 'opening');
    assert.equal(ctx.app.walk.pendingOpen, true, 'the quote opens after the same pause as a step');
    ctx.app.walk.flushOpen();
    assert.equal(opens(ctx).at(-1).evidenceId, 'e3');
    assert.equal(press(ctx, ']').defaultPrevented, true);
    assert.equal(live(ctx), 'Quote 2 of 2 is the last one.');
    press(ctx, '[');
    ctx.app.walk.flushOpen();
    assert.equal(opens(ctx).at(-1).evidenceId, 'e2');
    const count = opens(ctx).length;
    assert.equal(press(ctx, 'Enter').defaultPrevented, true);
    assert.equal(opens(ctx).length, count + 1, 'Enter opens at once, without the pause');
    const last = opens(ctx).at(-1);
    assert.equal(last.evidenceId, 'e2');
    assert.equal(last.walk, true);
    assert.equal(last.focus, undefined, 'focus stays here');
    press(ctx, 'Enter', { altKey: true });
    assert.equal(opens(ctx).at(-1).focus, true, 'Alt+Enter moves focus to the editor');
  } finally {
    ctx.app.destroy();
  }
});

test('u starts the walk on Not observed and steps through it (Shift+U back); n / p walk the findings in the walk', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    // Outside the walk, n is the M2 findings walk (document order) and starts nothing.
    press(ctx, 'n');
    assert.equal(ctx.app.walk.active, false);
    eq(ctx.app.selection, { kind: 'issue', id: 'f-whole' });
    ctx.canvas.focus();
    press(ctx, 'u');
    assert.equal(ctx.app.walk.active, true);
    assert.equal(ctx.app.walk.filter, 'notObserved');
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
    press(ctx, 'u');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-two' }, 'u: the next not-observed claim in the drawn order');
    press(ctx, 'U', { shiftKey: true });
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' }, 'Shift+U: the previous one');
    // On All, u keeps the filter and jumps to the next not-observed claim.
    ctx.app.walk.setFilter('all');
    press(ctx, 'u');
    assert.equal(ctx.app.walk.filter, 'all');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-two' });
    // In the walk, n and p go to the next and previous finding in the walk's (drawn) order.
    press(ctx, 'n');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-step' }, 'the next finding after F2');
    press(ctx, 'n');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-whole' }, 'then the findings without a cited step, at the end');
    press(ctx, 'p');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-step' });
    // Not observed holds no F4: the walk moves to the next claim it holds, the F3 at the end.
    ctx.app.walk.setFilter('notObserved');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-edge' });
    // n wraps to F2, which Not observed holds; the next, F4, is observed: the filter becomes Findings.
    press(ctx, 'n');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-two' });
    assert.equal(ctx.app.walk.filter, 'notObserved');
    press(ctx, 'n');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-step' });
    assert.equal(ctx.app.walk.filter, 'findings');
    assert.equal($(ctx, '.mlv-walkbar__filter[aria-pressed="true"]').getAttribute('data-walk-filter'), 'findings');
  } finally {
    ctx.app.destroy();
  }
});

/* ── each step ───────────────────────────────────────────────────────── */

test('each step asks the host after a pause, numbered; a burst of steps sends one open; only the latest answer is shown', async () => {
  const ctx = await mount(shapedWorkflow(YOLO_SHAPE), { width: 1440 });
  try {
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    const before = opens(ctx).length;
    for (let i = 0; i < 6; i++) press(ctx, 'j');
    assert.equal(opens(ctx).length, before, 'nothing is asked while the reader keeps moving');
    assert.equal(ctx.app.walk.pendingOpen, true);
    await sleep(220);
    assert.equal(opens(ctx).length, before + 1, 'one open after the pause');
    const first = opens(ctx).at(-1);
    assert.equal(first.walk, true);
    assert.ok(Number.isInteger(first.seq) && first.seq > 0);
    assert.match(first.requestId, /^[A-Za-z0-9_-]{1,64}$/);
    assert.equal(first.preview, true);
    assert.equal($(ctx, '.mlv-walkbar__editor').getAttribute('data-walk-status'), 'opening');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /^Opening in the editor beside: /);
    press(ctx, 'j');
    ctx.app.walk.flushOpen();
    const second = opens(ctx).at(-1);
    assert.ok(second.seq > first.seq, 'the number rises with every open');
    // The first open's late answer changes nothing; the second's is shown.
    answer(ctx, first, 'blocked', { reason: 'changed', message: 'stale; not opened.' });
    assert.equal($(ctx, '.mlv-walkbar__editor').getAttribute('data-walk-status'), 'opening');
    answer(ctx, second, 'done');
    assert.equal($(ctx, '.mlv-walkbar__editor').getAttribute('data-walk-status'), 'done');
    const where = $(ctx, '.mlv-walkbar__editortext').textContent;
    assert.match(where, /^In the editor beside: src\/file\d\.py · lines? \d+(–\d+)?( \(quote 1 of \d+\))?, highlighted\. Focus stays here\.$/);
    // The pane marks the quote the editor shows.
    const mark = $(ctx, '.mlv-quote.is-walk');
    assert.ok(mark, 'the walk\'s quote is marked in the Selection pane');
    assert.equal(mark.getAttribute('data-walk-status'), 'done');
    assert.equal(mark.querySelector('.mlv-quote__walk').textContent, 'In the editor beside, highlighted.');
    // The focus stayed on the diagram the whole time.
    assert.equal(ctx.document.activeElement, ctx.canvas);
  } finally {
    ctx.app.destroy();
  }
});

test('a blocked result shows its reason in the bar and the pane and is announced; nothing is opened and nothing is toasted', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    ctx.app.walk.flushOpen();
    const frame = opens(ctx).at(-1);
    answer(ctx, frame, 'blocked', { reason: 'unsaved', message: 'Unsaved changes in data.py no longer contain the cited lines; not opened. Save or revert the file.' });
    const editor = $(ctx, '.mlv-walkbar__editor');
    assert.equal(editor.getAttribute('data-walk-status'), 'blocked');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /^Quote 1 of 2: Unsaved changes in data\.py no longer contain the cited lines; not opened\./);
    assert.ok(visible(ctx, $(ctx, '.mlv-walkbar__editoricon')), 'a warning mark with the words');
    const mark = $(ctx, '.mlv-quote.is-walk');
    assert.equal(mark.getAttribute('data-walk-status'), 'blocked');
    assert.match(mark.querySelector('.mlv-quote__walk').textContent, /no longer contain the cited lines; not opened/);
    // The host's message already says nothing was opened: it is announced as it is (M3 review, A11Y-M3-8).
    assert.equal(live(ctx), 'Unsaved changes in data.py no longer contain the cited lines; not opened. Save or revert the file.');
    assert.equal($$(ctx, '.mlv-toast').length, 0, 'no toast');
    // A file the host already reported stale is said at once, and still asked for (the host never
    // opens it, and clears the earlier claim's highlight).
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'load', 'k');
    assert.equal(editor.getAttribute('data-walk-status'), 'blocked');
    assert.equal($(ctx, '.mlv-walkbar__editortext').textContent, 'data.py: changed since publishing; not opened.');
    ctx.app.walk.flushOpen();
    assert.equal(opens(ctx).at(-1).evidenceId, 'e1', 'the walk still asks, so the host can clear the highlight');
    assert.equal($$(ctx, '.mlv-toast').length, 0, 'still no toast');
  } finally {
    ctx.app.destroy();
  }
});

test('a claim with no quotes opens nothing, says so, and tells the host to clear the highlight', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    walkTo(ctx, 'sched', 'j');
    assert.equal($(ctx, '.mlv-walkbar__editortext').textContent, 'This claim cites no lines, so nothing is opened for it.');
    const frames = walkFrames(ctx).length;
    ctx.app.walk.flushOpen();
    eq(walkFrames(ctx).slice(frames), [{ v: 1, type: 'walk', state: 'clear' }]);
  } finally {
    ctx.app.destroy();
  }
});

test('the live region announces the place, the filter, the kind, the title and an exception\'s basis', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    assert.equal(live(ctx), 'Claim 1 of 5, not observed: Connection batches, from Augment to Optimizer step, inferred.');
    press(ctx, 'j');
    assert.equal(live(ctx), 'Claim 2 of 5, not observed: Finding F2 Order risk, inferred.');
    press(ctx, 'j');
    assert.equal(live(ctx), 'Claim 3 of 5, not observed: Step LR schedule, unresolved.');
    ctx.app.walk.setFilter('all');
    assert.equal(live(ctx), 'All 14 claims. Claim 7 of 14: Step LR schedule, unresolved.');
    for (let i = 0; i < 3; i++) press(ctx, 'k');
    assert.equal(live(ctx), 'Claim 4 of 14: Step Augment.', 'no basis word for an observed claim, no filter word for All');
  } finally {
    ctx.app.destroy();
  }
});

/* ── Escape, Tab and the place ───────────────────────────────────────── */

test('Escape ends the walk at once, before the bottom sheet collapses, from the canvas, the bar, the header and the sheet', async () => {
  const ctx = await mount(orderDoc(), { width: 541 });
  try {
    press(ctx, 'r');
    assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'true', 'the step opened the bottom sheet');
    let ev = press(ctx, 'Escape');
    assert.equal(ev.defaultPrevented, true);
    assert.equal(ctx.app.walk.active, false, 'one Escape ends the walk');
    assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'true', 'the sheet stays open on the claim');
    assert.ok(ctx.app.selection, 'and the claim stays selected');
    eq(walkFrames(ctx).at(-1), { v: 1, type: 'walk', state: 'end' });
    // From the bar: Escape ends it and gives the focus back to the diagram.
    press(ctx, 'r');
    ctx.app.walkBar.focus();
    assert.ok($(ctx, '.mlv-walkbar').contains(ctx.document.activeElement));
    press(ctx, 'Escape');
    assert.equal(ctx.app.walk.active, false);
    assert.equal(ctx.document.activeElement, ctx.canvas);
    // From the header's toolbar.
    press(ctx, 'r');
    $(ctx, '.mlv-btn--more').focus();
    ev = press(ctx, 'Escape');
    assert.equal(ctx.app.walk.active, false);
    assert.equal(ev.defaultPrevented, true, 'marked handled, so VS Code does not also act on it');
    // From inside the open sheet: the walk ends; the sheet collapses only on the next Escape.
    ctx.canvas.focus();
    press(ctx, 'r');
    const tab = $(ctx, '.mlv-rail__tab[aria-selected="true"]');
    tab.focus();
    press(ctx, 'Escape');
    assert.equal(ctx.app.walk.active, false);
    assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'true');
    assert.equal(ctx.document.activeElement, ctx.canvas);
    press(ctx, 'Escape');
    assert.equal($(ctx, '.mlv-rail').getAttribute('data-expanded'), 'false', 'the next Escape collapses the sheet, as in M2');
  } finally {
    ctx.app.destroy();
  }
});

test('the bar sits at the foot of the diagram, above the bottom sheet: Tab goes canvas, walk controls, sheet, and is never held', async () => {
  for (const width of [1440, 900, 541]) {
    const ctx = await mount(orderDoc(), { width });
    try {
      press(ctx, 'r');
      const focusable = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]';
      const stops = $$(ctx, focusable).filter((element) => element.tabIndex >= 0 && visible(ctx, element));
      const inBar = stops.filter((element) => $(ctx, '.mlv-walkbar').contains(element));
      assert.equal(inBar.length, 1, `${width} px: one tab stop in the bar`);
      const at = stops.indexOf(ctx.canvas);
      assert.ok(at >= 0 && at <= 3, `${width} px: the canvas is Tab stop ${at + 1} (${stops.slice(0, at + 1).map((e) => e.className || e.tagName).join(' | ')})`);
      // In the diagram column, after the canvas; the rail (side panel or bottom sheet) after it.
      const bar = $(ctx, '.mlv-walkbar');
      assert.equal(bar.parentElement, $(ctx, '.mlv-main'), 'the bar is part of the diagram column');
      assert.equal(bar.previousElementSibling, ctx.canvas, 'directly under the diagram');
      assert.equal(bar.parentElement.nextElementSibling, $(ctx, '.mlv-rail'), 'and directly above the bottom sheet');
      assert.equal(stops[at + 1], inBar[0], 'Tab from the canvas reaches the walk\'s controls');
      assert.ok(stops.indexOf($(ctx, '.mlv-rail__tab[aria-selected="true"]')) > at + 1, 'then the claim in the sheet');
      assert.equal(press(ctx, 'Tab').defaultPrevented, false, 'Tab on the canvas goes to the browser');
      ctx.app.walkBar.focus();
      assert.equal(press(ctx, 'Tab').defaultPrevented, false, 'Tab in the bar goes to the browser');
    } finally {
      ctx.app.destroy();
    }
  }
});

test('the place is remembered per revision: r resumes it; a remount restores it; another revision starts fresh', async () => {
  const document = shapedWorkflow(VIT_SHAPE);
  const ctx = await mount(document, { width: 1440 });
  let saved;
  try {
    press(ctx, 'r');
    press(ctx, 'j');
    press(ctx, 'j');
    const there = ctx.app.walk.current();
    press(ctx, 'Escape');
    press(ctx, 'r');
    eq(ctx.app.walk.current(), there, 'r resumes where the walk ended');
    assert.equal(ctx.app.walk.position, 2);
    saved = ctx.app.getState();
    eq(saved.walk, { filter: 'notObserved', claim: there, active: true });
    assert.equal(saved.workflowRevision, 'syn-r1');
    // Nothing but the place is recorded: no verdict or "checked" mark anywhere in the state.
    assert.doesNotMatch(JSON.stringify(saved), /checked|verdict|reviewed/i);
  } finally {
    ctx.app.destroy();
  }
  // A remount of the same revision (VS Code rebuilt a hidden panel) brings the running walk back,
  // and asks the host for nothing until the reader moves or presses Enter.
  const again = await mount(document, { width: 1440, state: JSON.parse(JSON.stringify(saved)) });
  try {
    assert.equal(again.app.walk.active, true);
    assert.equal(again.app.walk.position, 2);
    assert.equal(opens(again).length, 0, 'no open on a remount');
    assert.match($(again, '.mlv-walkbar__editortext').textContent, /^Enter shows .* in the editor beside\.$/);
    eq(again.app.selection, saved.walk.claim);
    // Another revision: the walk ends and starts fresh.
    const next = { ...document, revision: { id: 'syn-r2', parent: 'syn-r1' } };
    again.app.setWorkflow(next);
    assert.equal(again.app.walk.active, false);
    eq(walkFrames(again).at(-1), { v: 1, type: 'walk', state: 'end' });
    assert.equal(again.app.getState().walk, undefined, 'the place of the old revision is dropped');
    again.canvas.focus();
    press(again, 'r');
    assert.equal(again.app.walk.position, 0, 'a fresh start');
  } finally {
    again.app.destroy();
  }
  // A saved place for another revision is not applied.
  const other = await mount({ ...document, revision: { id: 'syn-r9' } }, { width: 1440, state: JSON.parse(JSON.stringify(saved)) });
  try {
    assert.equal(other.app.walk.active, false);
    other.canvas.focus();
    press(other, 'r');
    assert.equal(other.app.walk.position, 0);
  } finally {
    other.app.destroy();
  }
});

/* ── changed files ───────────────────────────────────────────────────── */

test('Changed files is offered only with stale files; the stale notice\'s "Review affected claims" starts the walk on it', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'data.py changed since revision o1 was published.', codes: ['stale'] });
    assert.equal($(ctx, '[data-notice-action="review"]'), null, 'no action before the host reports which files');
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    const action = $(ctx, '[data-notice-action="review"]');
    assert.ok(visible(ctx, action));
    assert.equal(action.textContent, 'Review affected claims');
    action.click();
    assert.equal(ctx.app.walk.active, true);
    assert.equal(ctx.app.walk.filter, 'changed');
    // Claims whose quotes cite data.py: load, load→aug, load→step, aug, aug→step, f-two (counter-evidence), f-whole, f-edge.
    eq(ctx.app.walk.list.map(key), ['node:load', 'edge:c-load-aug', 'edge:c-load-step', 'node:aug', 'edge:c-aug-step', 'issue:f-two', 'issue:f-whole', 'issue:f-edge']);
    assert.equal($(ctx, '.mlv-walkbar__filter[data-walk-filter="changed"] .mlv-walkbar__fcount').textContent, '8');
    assert.equal($(ctx, '[data-notice-action="review"]'), null, 'the action goes while the walk runs');
    assert.equal(ctx.document.activeElement, ctx.canvas, 'the diagram has the keys');
    // The files are fixed: the filter goes, and the walk keeps its claim on All.
    const there = ctx.app.walk.current();
    ctx.bridge.send({ v: 1, type: 'stale', files: [] });
    assert.equal(ctx.app.walk.filter, 'all');
    eq(ctx.app.walk.current(), there);
    assert.equal($(ctx, '.mlv-walkbar__filter[data-walk-filter="changed"]').hidden, true);
  } finally {
    ctx.app.destroy();
  }
});

test('files that are only in another folder (the root hint) offer no Changed files filter and no review action', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'elsewhere' }, { path: 'train.py', reason: 'elsewhere' }] });
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'The cited files are under ./sub/.', codes: ['root-hint'] });
    assert.equal($(ctx, '[data-notice-action="review"]'), null);
    press(ctx, 'r');
    assert.equal($(ctx, '.mlv-walkbar__filter[data-walk-filter="changed"]').hidden, true);
  } finally {
    ctx.app.destroy();
  }
});

/* ── the narrow layout ───────────────────────────────────────────────── */

test('at 541 px the bar is "3/16", the filters and Exit; at 900 px it has the place, the keys and the editor line', async () => {
  const ctx = await mount(shapedWorkflow(YOLO_SHAPE), { width: 541 });
  try {
    press(ctx, 'r');
    press(ctx, 'j');
    press(ctx, 'j');
    const bar = $(ctx, '.mlv-walkbar');
    assert.equal(bar.getAttribute('data-layout'), 'narrow');
    assert.equal(visible(ctx, $(ctx, '.mlv-header__review')), false, 'the 541 px header keeps the M2 controls; Review is in the ⋯ menu');
    assert.equal($(ctx, '.mlv-walkbar__postext').textContent, '3/16');
    // The whole place is screen-reader text inside the paragraph, not a name on it (M3 review, A11Y-M3-6).
    assert.equal($(ctx, '.mlv-walkbar__pos').getAttribute('aria-label'), null);
    assert.equal($(ctx, '.mlv-walkbar__posspoken').textContent, 'Claim 3 of 16, Not observed');
    assert.equal($(ctx, '.mlv-walkbar__postext').getAttribute('aria-hidden'), 'true');
    assert.equal(visible(ctx, $(ctx, '.mlv-walkbar__keys')), false, 'no key hint');
    assert.equal(visible(ctx, $(ctx, '.mlv-walkbar__editor')), false, 'no editor line');
    assert.ok(visible(ctx, $(ctx, '.mlv-walkbar__filter[data-walk-filter="notObserved"]')));
    const exit = $(ctx, '.mlv-walkbar__exit');
    assert.ok(visible(ctx, exit));
    assert.equal(exit.getAttribute('aria-label'), 'Exit the review (Escape)', 'Exit keeps its name when its word is hidden');
    // A quote the host did not open puts a mark on the place; its name says why.
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'missing', message: 'utils.py is missing since revision syn-r1 was published; not opened.' });
    assert.ok(visible(ctx, $(ctx, '.mlv-walkbar__mark')));
    assert.match($(ctx, '.mlv-walkbar__posspoken').textContent, /^Claim 3 of 16, Not observed\. Quote 1 of \d+: utils\.py is missing since revision syn-r1 was published; not opened\.$|^Claim 3 of 16, Not observed\. utils\.py is missing since revision syn-r1 was published; not opened\.$/);
    assert.match($(ctx, '.mlv-quote.is-walk .mlv-quote__walk').textContent, /utils\.py is missing/, 'and the pane says it in full');
    ctx.resize(900);
    assert.equal(bar.getAttribute('data-layout'), 'wide');
    assert.equal($(ctx, '.mlv-walkbar__postext').textContent, 'Claim 3 of 16 · Not observed');
    assert.equal($(ctx, '.mlv-walkbar__postext').getAttribute('aria-hidden'), null, 'wide, the visible place is what is read');
    assert.equal(visible(ctx, $(ctx, '.mlv-walkbar__posspoken')), false);
    assert.ok(visible(ctx, $(ctx, '.mlv-walkbar__keys')));
    assert.ok(visible(ctx, $(ctx, '.mlv-walkbar__editor')));
  } finally {
    ctx.app.destroy();
  }
});

test('the header\'s Review button folds with the revision chip when the row is short; the ⋯ menu always has Review', async () => {
  const ctx = await mount(orderDoc(), { width: 900 });
  try {
    const header = $(ctx, '.mlv-header');
    // jsdom measures nothing: stand in a row that overflows until level 1.
    Object.defineProperty(header, 'clientWidth', { configurable: true, get: () => 500 });
    Object.defineProperty(header, 'scrollWidth', { configurable: true, get: () => (Number(header.getAttribute('data-fit')) >= 1 ? 500 : 640) });
    ctx.app.refreshChrome();
    assert.equal(header.getAttribute('data-fit'), '1');
    assert.equal($(ctx, '.mlv-header__review').hidden, true, 'Review folded');
    assert.equal($(ctx, '.mlv-header__prov').hidden, true, 'with the revision chip');
    assert.equal($(ctx, '.mlv-chip--exceptions').hidden, false, '"not observed" keeps its count on the row');
    $(ctx, '.mlv-btn--more').click();
    assert.ok(visible(ctx, $(ctx, '[data-more-item="review"]')));
  } finally {
    ctx.app.destroy();
  }
});

/* ── motion, opening and the record ──────────────────────────────────── */

test('the walk adds no motion: no transition or animation in its styles, and nothing moves under reduced motion', async () => {
  const rules = CSS.split('}').filter((rule) => /mlv-walkbar|mlv-quote\.is-walk|mlv-quote__walk|mlv-header__review/.test(rule));
  assert.ok(rules.length > 5, 'the walk\'s rules are in the shipped stylesheet');
  for (const rule of rules) assert.doesNotMatch(rule, /transition|animation/, rule.slice(0, 80));
  const ctx = await mount(orderDoc(), { width: 1440, bodyClass: 'vscode-reduce-motion' });
  try {
    press(ctx, 'r');
    press(ctx, 'j');
    assert.equal(ctx.app.walk.position, 1, 'the walk works the same with reduced motion');
    assert.equal($$(ctx, '.mlv-edge__flow').length, 0, 'and starts no flow');
  } finally {
    ctx.app.destroy();
  }
});

test('a host that cannot open source: the walk selects and announces, and asks for nothing', async () => {
  const ctx = await mount(orderDoc(), { width: 1440, capabilities: { canOpenSource: false } });
  try {
    press(ctx, 'r');
    assert.equal($(ctx, '.mlv-walkbar__editortext').textContent, 'This view cannot open source files.');
    await sleep(200);
    assert.equal(opens(ctx).length, 0);
    assert.equal(ctx.app.walk.active, true);
  } finally {
    ctx.app.destroy();
  }
});

test('a click on a claim the walk holds moves the walk there without opening it; an Open link of that claim opens it as the walk\'s quote', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    ctx.app.walk.flushOpen();
    const count = opens(ctx).length;
    const card = $(ctx, '.mlv-node[data-node-id="zero"]');
    card.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
    await ctx.app.doubleClick && sleep(10);
    eq(ctx.app.walk.current(), { kind: 'node', id: 'zero' }, 'the walk followed the click');
    assert.equal(opens(ctx).length, count, 'a click opens nothing');
    eq(walkFrames(ctx).at(-1), { v: 1, type: 'walk', state: 'clear' }, 'the old highlight is cleared');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /^Enter shows nb\.ipynb · cell 7 · lines 2–3 in the editor beside\.$/);
    $(ctx, '.mlv-quote__open').click();
    const frame = opens(ctx).at(-1);
    assert.equal(frame.evidenceId, 'e5');
    assert.equal(frame.walk, true, 'the Open link went through the walk (no notification when blocked)');
    assert.equal(frame.cell, 7);
  } finally {
    ctx.app.destroy();
  }
});

/* ── M3 review fixes ─────────────────────────────────────────────────── */

test('M3 review F2: "Review affected claims" after a walk elsewhere starts at Claim 1 of the affected claims; u after a walk on All starts at the first claim not observed', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    // Walk Not observed to its last claim, then end it.
    press(ctx, 'r');
    for (let i = 0; i < 6; i++) press(ctx, 'j');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-edge' }, 'precondition: the last claim not observed');
    press(ctx, 'Escape');
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'data.py changed since revision o1 was published.', codes: ['stale'] });
    $(ctx, '[data-notice-action="review"]').click();
    assert.equal(ctx.app.walk.filter, 'changed');
    assert.equal(ctx.app.walk.position, 0, 'the first affected claim, not the one after the old place');
    eq(ctx.app.walk.current(), { kind: 'node', id: 'load' });
    assert.equal($(ctx, '.mlv-walkbar__postext').textContent, 'Claim 1 of 8 · Changed files');
    // Resuming the same filter keeps its place.
    press(ctx, 'j');
    press(ctx, 'j');
    press(ctx, 'Escape');
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'data.py changed since revision o1 was published.', codes: ['stale'] });
    const again = $(ctx, '[data-notice-action="review"]');
    assert.ok(again, 'the action is back after the walk ended');
    again.click();
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-load-step' }, 'the same filter resumes where it ended');
    // u after a walk on All begins Not observed at its first claim.
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'zero', 'j');
    press(ctx, 'Escape');
    ctx.canvas.focus();
    press(ctx, 'u');
    assert.equal(ctx.app.walk.filter, 'notObserved');
    assert.equal(ctx.app.walk.position, 0);
    eq(ctx.app.walk.current(), { kind: 'edge', id: 'c-aug-step' });
  } finally {
    ctx.app.destroy();
  }
});

test('M3 review F3: when the current claim leaves Changed files, the walk shows the claim now in its place (selected, announced, nothing opened) and j does not skip it', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }, { path: 'train.py', reason: 'changed' }] });
    assert.equal(ctx.app.walk.start('changed'), true);
    walkTo(ctx, 'step', 'j');
    ctx.app.walk.flushOpen();
    const opensBefore = opens(ctx).length;
    const framesBefore = walkFrames(ctx).length;
    // train.py is unchanged again; data.py stays changed. Optimizer step cites only train.py.
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    eq(ctx.app.walk.list.map(key), ['node:load', 'edge:c-load-aug', 'edge:c-load-step', 'node:aug', 'edge:c-aug-step', 'issue:f-two', 'issue:f-whole', 'issue:f-edge']);
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-whole' }, 'the next affected claim after the old one');
    eq(ctx.app.selection, ctx.app.walk.current(), 'and it is the one selected and shown');
    assert.equal($(ctx, '.mlv-walkbar__postext').textContent, 'Claim 7 of 8 · Changed files');
    assert.match(live(ctx), /^Claim 7 of 8, changed files: Finding F1 No seed\.$/);
    assert.equal(ctx.app.walk.pendingOpen, false, 'nothing is opened by itself');
    assert.equal(opens(ctx).length, opensBefore);
    eq(walkFrames(ctx).slice(framesBefore), [{ v: 1, type: 'walk', state: 'clear' }], 'the old highlight is cleared');
    // Its quote cites data.py, still changed: the bar says why Enter will not open it.
    assert.equal($(ctx, '.mlv-walkbar__editortext').textContent, 'data.py: changed since publishing; not opened.');
    press(ctx, 'j');
    eq(ctx.app.walk.current(), { kind: 'issue', id: 'f-edge' }, 'j goes to the claim after it, nothing skipped');
  } finally {
    ctx.app.destroy();
  }
});

test('M3 review F4: a quote whose file the host reported stale never reads "Enter shows": a filter on the same claim, a click, a remount', async () => {
  const doc = orderDoc();
  const ctx = await mount(doc, { width: 1440 });
  let saved;
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    press(ctx, 'r');
    ctx.app.walk.setFilter('all');
    walkTo(ctx, 'load', 'k');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'changed', message: 'data.py changed after revision o1 was published; not opened.' });
    const text = () => $(ctx, '.mlv-walkbar__editortext').textContent;
    assert.equal(text(), 'data.py changed after revision o1 was published; not opened.');
    // A filter that holds the same claim keeps what the bar said.
    ctx.app.walk.setFilter('changed');
    eq(ctx.app.walk.current(), { kind: 'node', id: 'load' });
    assert.equal(text(), 'data.py changed after revision o1 was published; not opened.');
    assert.equal($(ctx, '.mlv-quote.is-walk').getAttribute('data-walk-status'), 'blocked');
    // A click on another claim of the walk that cites the stale file.
    ctx.app.walk.setFilter('all');
    const card = $(ctx, '.mlv-node[data-node-id="aug"]');
    card.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
    eq(ctx.app.walk.current(), { kind: 'node', id: 'aug' });
    assert.equal(text(), 'data.py: changed since publishing; not opened.');
    assert.doesNotMatch($(ctx, '.mlv-quote.is-walk .mlv-quote__walk').textContent, /Enter shows/);
    saved = JSON.parse(JSON.stringify(ctx.app.getState()));
  } finally {
    ctx.app.destroy();
  }
  // A remount brings the walk back before the host has sent its stale files; when they come, the
  // bar says why the quote will not open.
  const again = await mount(doc, { width: 1440, state: saved });
  try {
    assert.equal(again.app.walk.active, true);
    assert.match($(again, '.mlv-walkbar__editortext').textContent, /^Enter shows data\.py/);
    again.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'changed' }] });
    assert.equal($(again, '.mlv-walkbar__editortext').textContent, 'data.py: changed since publishing; not opened.');
  } finally {
    again.app.destroy();
  }
});

test('M3 review A11Y-M3-1: the header Review button and the ⋯ menu item give the keyboard to the diagram, so j steps at once', async () => {
  const wide = await mount(orderDoc(), { width: 1440 });
  try {
    const review = $(wide, '.mlv-header__review');
    review.focus();
    review.click();
    assert.equal(wide.app.walk.active, true);
    assert.equal(wide.document.activeElement, wide.canvas, 'the diagram has the keys');
    press(wide, 'j');
    press(wide, 'j');
    assert.equal(wide.app.walk.position, 2, 'j stepped twice');
    // Ending the walk with the button leaves the focus where it is.
    review.focus();
    review.click();
    assert.equal(wide.app.walk.active, false);
    assert.equal(wide.document.activeElement, review);
  } finally {
    wide.app.destroy();
  }
  const narrow = await mount(orderDoc(), { width: 541 });
  try {
    const more = $(narrow, '.mlv-btn--more');
    more.focus();
    more.click();
    $(narrow, '[data-more-item="review"]').click();
    assert.equal(narrow.app.walk.active, true);
    assert.equal(narrow.document.activeElement, narrow.canvas, 'not the ⋯ button');
    press(narrow, 'j');
    press(narrow, 'j');
    assert.equal(narrow.app.walk.position, 2);
  } finally {
    narrow.app.destroy();
  }
});

test('M3 review A11Y-M3-2: Previous and Next in the bar at every width step as k and j, named with their keys, inside the one tab stop', async () => {
  for (const width of [1440, 900, 541]) {
    const ctx = await mount(orderDoc(), { width });
    try {
      press(ctx, 'r');
      const prev = $(ctx, '.mlv-walkbar [data-walk-step="prev"]');
      const next = $(ctx, '.mlv-walkbar [data-walk-step="next"]');
      assert.ok(visible(ctx, prev) && visible(ctx, next), `${width} px: both are shown`);
      assert.equal(prev.getAttribute('aria-label'), 'Previous claim (k)');
      assert.equal(next.getAttribute('aria-label'), 'Next claim (j)');
      assert.ok($(ctx, '.mlv-walkbar__tools').contains(next), 'in the bar\'s toolbar');
      next.click();
      next.click();
      assert.equal(ctx.app.walk.position, 2, `${width} px: Next stepped twice`);
      eq(ctx.app.selection, ctx.app.walk.current());
      prev.click();
      assert.equal(ctx.app.walk.position, 1, `${width} px: Previous stepped back`);
      prev.click();
      prev.click();
      assert.equal(live(ctx), 'Claim 1 of 5 is the first one.');
      const stops = $$(ctx, '.mlv-walkbar button').filter((b) => b.tabIndex === 0 && visible(ctx, b));
      assert.equal(stops.length, 1, `${width} px: still one tab stop`);
    } finally {
      ctx.app.destroy();
    }
  }
});

test('M3 review A11Y-M3-3: after Alt+Enter the bar and the pane say the focus moved to the editor; after Enter that it stays here', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'done');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /, highlighted\. Focus stays here\.$/);
    assert.equal($(ctx, '.mlv-quote.is-walk .mlv-quote__walk').textContent, 'In the editor beside, highlighted.');
    press(ctx, 'Enter', { altKey: true });
    const frame = opens(ctx).at(-1);
    assert.equal(frame.focus, true);
    answer(ctx, frame, 'done');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /, highlighted\. Focus moved to the editor\.$/);
    assert.equal($(ctx, '.mlv-quote.is-walk .mlv-quote__walk').textContent, 'In the editor beside, highlighted; the focus moved there.');
    press(ctx, 'Enter', {}, ctx.canvas);
    answer(ctx, opens(ctx).at(-1), 'done');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /Focus stays here\.$/);
  } finally {
    ctx.app.destroy();
  }
});

test('M3 review A11Y-M3-4: a late answer for a claim the walk has left is not shown as the current claim\'s', async () => {
  const ctx = await mount(orderDoc(), { width: 1440 });
  try {
    press(ctx, 'r');
    ctx.app.walk.flushOpen();
    const first = opens(ctx).at(-1);
    // Two quick steps: to F2, then to LR schedule, which cites no lines; no open is sent yet.
    press(ctx, 'j');
    press(ctx, 'j');
    eq(ctx.app.walk.current(), { kind: 'node', id: 'sched' });
    answer(ctx, first, 'done');
    assert.equal($(ctx, '.mlv-walkbar__editortext').textContent, 'This claim cites no lines, so nothing is opened for it.');
    assert.doesNotMatch($(ctx, '.mlv-walkbar__editortext').textContent, /In the editor beside: ,/);
    // The same for a claim with lines: the answer for the claim left behind is ignored.
    press(ctx, 'j');
    ctx.app.walk.flushOpen();
    const stepOpen = opens(ctx).at(-1);
    press(ctx, ']');
    answer(ctx, stepOpen, 'done');
    assert.equal($(ctx, '.mlv-walkbar__editor').getAttribute('data-walk-status'), 'opening', 'the quote changed: still waiting for its own open');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'done');
    assert.match($(ctx, '.mlv-walkbar__editortext').textContent, /^In the editor beside: train\.py · lines 8–9 \(quote 2 of 2\), highlighted\./);
  } finally {
    ctx.app.destroy();
  }
});

test('M3 review A11Y-M3-8: "All claims" names its unit; a blocked open is announced without saying "not opened" twice', async () => {
  const ctx = await mount(shapedWorkflow(VIT_SHAPE), { width: 1440 });
  try {
    press(ctx, 'r');
    const all = $(ctx, '.mlv-walkbar__filter[data-walk-filter="all"]');
    assert.equal(all.querySelector('.mlv-walkbar__flabel').textContent, 'All claims');
    assert.equal(all.querySelector('.mlv-walkbar__fcount').textContent, '79');
    assert.equal(all.getAttribute('aria-label'), 'All 79 claims');
    assert.equal($(ctx, '.mlv-walkbar__filter[data-walk-filter="notObserved"]').getAttribute('aria-label'), 'Not observed, 7 claims');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { reason: 'changed', message: 'examples/cats_and_dogs.ipynb changed after revision syn-r1 was published; not opened.' });
    assert.equal(live(ctx), 'examples/cats_and_dogs.ipynb changed after revision syn-r1 was published; not opened.');
    assert.equal((live(ctx).match(/not opened/gi) || []).length, 1);
    // A message without those words is still said as not opened.
    press(ctx, 'j');
    ctx.app.walk.flushOpen();
    answer(ctx, opens(ctx).at(-1), 'blocked', { message: 'The file is outside the workspace.' });
    assert.equal(live(ctx), 'Not opened: The file is outside the workspace.');
  } finally {
    ctx.app.destroy();
  }
});
