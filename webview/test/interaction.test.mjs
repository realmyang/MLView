/**
 * Interaction and accessibility gates: keyboard model, search, collapse/expand,
 * lineage highlight, the side rail and the designed states.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample, makeSyntheticGraph } from './helpers.mjs';
import { afterDeferredClick } from './until.mjs';

const sample = await readSample();

/** Hover-card delays, mirrored from canvasview.ts (UX_DESIGN section 9). */
const HOVER_OPEN_MS = 400;
const HOVER_CLOSE_MS = 120;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

test('the canvas is an application region with a live announcer', async () => {
  const ctx = await app();
  assert.equal(ctx.canvas.getAttribute('role'), 'application');
  assert.equal(ctx.canvas.getAttribute('aria-label'), 'ML pipeline diagram');
  assert.equal(ctx.canvas.getAttribute('tabindex'), '0');
  const live = ctx.document.querySelector('[aria-live="polite"]');
  assert.ok(live && live.textContent.indexOf('Analysis loaded') >= 0);
  const tree = ctx.document.querySelector('[role="tree"]');
  assert.ok(tree, 'the outline is a real tree');
  assert.ok(ctx.document.querySelector('[role="listbox"]'), 'issues are a listbox');
});

test('every node card is a labelled, focusable button', async () => {
  const ctx = await app();
  const cards = ctx.document.querySelectorAll('.mlv-node[data-node-id]');
  assert.ok(cards.length > 0);
  for (const card of cards) {
    assert.equal(card.getAttribute('role'), 'button');
    assert.equal(card.getAttribute('tabindex'), '-1');
    const label = card.getAttribute('aria-label') || '';
    assert.ok(label.length > 10, 'card ' + card.getAttribute('data-node-id') + ' has a full label');
    assert.ok(/stage/.test(label));
  }
});

test('selection sets aria-activedescendant and the selected class', async () => {
  const ctx = await app();
  const card = ctx.document.querySelector('[data-node-id="n:b45c96e0d817"]');
  click(ctx, card);
  assert.ok(card.classList.contains('is-selected'));
  assert.equal(ctx.canvas.getAttribute('aria-activedescendant'), card.id);
  key(ctx, ctx.canvas, 'Escape');
  assert.equal(card.classList.contains('is-selected'), false);
  assert.equal(ctx.canvas.getAttribute('aria-activedescendant'), null);
});

test('hovering a node lights its lineage and dims the rest', async () => {
  const ctx = await app();
  const card = ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]');
  card.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
  // UX_DESIGN section 9: the card waits 400 ms before it commits (MLV-R2-W04).
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false, 'nothing happens on the way past');
  await sleep(HOVER_OPEN_MS + 80);
  assert.ok(ctx.canvas.classList.contains('is-tracing'));
  assert.ok(card.classList.contains('is-lit'));
  const downstream = ctx.document.querySelector('[data-node-id="n:9c8d7e6f5a4b"]');
  assert.ok(downstream.classList.contains('is-lit'), 'the consumer of train_loader is lit');
  const unrelated = ctx.document.querySelector('[data-node-id="n:4e8b21c05a97"]');
  assert.equal(unrelated.classList.contains('is-lit'), false, 'unrelated nodes stay dim');
  const tooltip = ctx.document.querySelector('.mlv-tooltip');
  assert.equal(tooltip.hidden, false);
  card.dispatchEvent(new ctx.window.Event('pointerleave', { bubbles: false }));
  assert.ok(ctx.canvas.classList.contains('is-tracing'), 'and 120 ms before it drops');
  await sleep(HOVER_CLOSE_MS + 80);
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false);
});

test('a pointer sweeping across the diagram never opens a card (MLV-R2-W04)', async () => {
  const ctx = await app();
  const cards = Array.from(ctx.document.querySelectorAll('.mlv-node[data-node-id]')).slice(0, 5);
  for (const card of cards) {
    card.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
    await sleep(30);
    card.dispatchEvent(new ctx.window.Event('pointerleave', { bubbles: false }));
  }
  await sleep(HOVER_CLOSE_MS + 80);
  assert.equal(ctx.document.querySelector('.mlv-tooltip').hidden, true, 'no card ever opened');
  assert.equal(ctx.canvas.classList.contains('is-tracing'), false, 'and nothing was dimmed');
  // The flow layer hangs off this same intent, so a sweep allocates nothing at
  // all: lazy creation happens inside the 400 ms callback (F1-A11).
  assert.equal(ctx.document.querySelectorAll('.mlv-edge__flow').length, 0, 'and no flow element was built');
  assert.equal(ctx.document.querySelectorAll('.mlv-edge.is-flowing').length, 0);
});

test('the hover card flips below its anchor instead of being clipped (MLV-R2-W04)', async () => {
  const { tooltipPlacement } = (await loadBundle()).MLView.__internal;
  // A card 72 px tall anchored 40 px from the top of the canvas cannot go above it.
  const flipped = tooltipPlacement(500, 40, 108, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(flipped.below, true, 'it flips under the node');
  assert.ok(flipped.top >= 8, 'and lands inside the canvas: ' + flipped.top);

  // With room above, it stays above.
  const above = tooltipPlacement(500, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(above.below, false);
  assert.equal(above.top, 388);

  // Horizontal shift: a card anchored at the left edge is pushed in, never cut.
  const shifted = tooltipPlacement(10, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(shifted.left, 108, 'left edge clears the canvas by the margin');
  const shiftedRight = tooltipPlacement(995, 400, 468, { w: 200, h: 72 }, { w: 1000, h: 800 });
  assert.equal(shiftedRight.left, 892);

  // Unmeasurable (jsdom, pre-paint): no guessing, the old behaviour stands.
  const plain = tooltipPlacement(500, 40, 108, { w: 0, h: 0 }, { w: 0, h: 0 });
  assert.equal(plain.left, 500);
  assert.equal(plain.top, 28);
  assert.equal(plain.below, false);
});

test('F toggles focus mode on the selection', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]'));
  key(ctx, ctx.canvas, 'f');
  assert.ok(ctx.canvas.classList.contains('is-focusing'));
  key(ctx, ctx.canvas, 'f');
  assert.equal(ctx.canvas.classList.contains('is-focusing'), false);
});

test('zoom keys and buttons change the viewport without relayout', async () => {
  const ctx = await app();
  const before = ctx.app.getState().viewport.zoom;
  const positions = Array.from(ctx.document.querySelectorAll('.mlv-node')).map((n) => n.style.left);
  key(ctx, ctx.canvas, '+');
  const after = ctx.app.getState().viewport.zoom;
  assert.ok(after > before, 'zoom in raised the scale');
  key(ctx, ctx.canvas, '-');
  key(ctx, ctx.canvas, '0');
  const positionsAfter = Array.from(ctx.document.querySelectorAll('.mlv-node')).map((n) => n.style.left);
  assert.equal(positions.join('|'), positionsAfter.join('|'), 'zoom never reflows node boxes');
  assert.ok(/scale\(/.test(ctx.document.querySelector('.mlv-world').style.transform));
});

test('n / p cycle issues and Enter opens the selection', async () => {
  const ctx = await app();
  key(ctx, ctx.canvas, 'n');
  const state = ctx.app.getState();
  assert.equal(state.selection.kind, 'issue');
  const first = state.selection.id;
  key(ctx, ctx.canvas, 'n');
  assert.notEqual(ctx.app.getState().selection.id, first);
  key(ctx, ctx.canvas, 'p');
  assert.equal(ctx.app.getState().selection.id, first);
  key(ctx, ctx.canvas, 'Enter');
  const open = ctx.posted.filter((m) => m.type === 'openLocation').pop();
  assert.ok(open, 'Enter opened the issue location');
});

test('the canvas is not a keyboard trap: Tab is never intercepted (MLV-R1-005)', async () => {
  const ctx = await app();
  ctx.canvas.focus();
  for (const opts of [{}, { shiftKey: true }]) {
    const ev = new ctx.window.KeyboardEvent('keydown', {
      key: 'Tab',
      bubbles: true,
      cancelable: true,
      ...opts,
    });
    ctx.canvas.dispatchEvent(ev);
    // jsdom implements no sequential focus navigation, so preventDefault() is the
    // thing that actually decides whether focus can leave: it must stay false.
    assert.equal(ev.defaultPrevented, false, 'Tab reaches the browser focus manager');
  }
  // and the selection is untouched — Tab is not a cycling gesture any more
  assert.equal(ctx.app.getState().selection, null);
});

test('? opens the shortcut sheet and Escape closes it (MLV-R1-005)', async () => {
  const ctx = await app();
  assert.equal(ctx.document.querySelector('.mlv-sheet').hidden, true);
  key(ctx, ctx.canvas, '?');
  const sheet = ctx.document.querySelector('.mlv-sheet');
  assert.equal(sheet.hidden, false, 'the sheet opened');
  const rows = sheet.querySelectorAll('.mlv-sheet__keys');
  assert.equal(rows.length, ctx.MLView.__internal.keymap.length, 'the sheet renders KEYMAP itself');
  assert.ok(sheet.textContent.indexOf('Next / previous issue') >= 0);
  // The sheet is the only place the Escape cascade is described to the user, and
  // a scoped diagram is exactly where someone presses it expecting the selection
  // to go and loses the scope instead (MLV-R1-F2-06).
  const escapeRow = ctx.MLView.__internal.keymap.filter((row) => row.keys.indexOf('Escape') >= 0);
  assert.equal(escapeRow.length, 1);
  assert.match(escapeRow[0].description, /scope/, 'the Escape row names the scope rung: ' + escapeRow[0].description);
  assert.ok(sheet.textContent.indexOf(escapeRow[0].description) >= 0, 'and the sheet renders it');
  key(ctx, ctx.canvas, 'Escape');
  assert.equal(sheet.hidden, true, 'Escape closes the sheet first');
});

test('the rest of the documented keymap is wired (MLV-R1-005)', async () => {
  const ctx = await app();
  // Ctrl+B toggles the rail
  const rail = ctx.document.querySelector('.mlv-rail');
  assert.equal(rail.hidden, false);
  key(ctx, ctx.canvas, 'b', { ctrlKey: true });
  assert.equal(rail.hidden, true, 'Ctrl+B hid the rail');
  key(ctx, ctx.canvas, 'b', { ctrlKey: true });
  assert.equal(rail.hidden, false);

  // Ctrl+1/2/3 switch tabs
  key(ctx, ctx.canvas, '2', { ctrlKey: true });
  assert.equal(ctx.app.getState().railTab, 'inspector');
  key(ctx, ctx.canvas, '3', { ctrlKey: true });
  assert.equal(ctx.app.getState().railTab, 'outline');
  key(ctx, ctx.canvas, '1', { ctrlKey: true });
  assert.equal(ctx.app.getState().railTab, 'issues');

  // bare 1/2/3 toggle the severity filters
  const before = ctx.app.getState().filters.severities.length;
  key(ctx, ctx.canvas, '1');
  assert.equal(ctx.app.getState().filters.severities.length, before - 1, '1 dropped the high filter');
  assert.equal(ctx.app.getState().filters.severities.indexOf('high'), -1);
  key(ctx, ctx.canvas, '1');
  assert.equal(ctx.app.getState().filters.severities.length, before);

  // Ctrl+K focuses the search box
  key(ctx, ctx.canvas, 'k', { ctrlKey: true });
  assert.equal(ctx.document.activeElement, ctx.document.querySelector('.mlv-search .mlv-input'));
});

test('clicking an issue row fills the Inspector and expands in place (MLV-R1-006)', async () => {
  const ctx = await app();
  const row = ctx.document.querySelector('.mlv-issue[data-issue-id]');
  const issueId = row.getAttribute('data-issue-id');
  const issue = sample.issues.find((i) => i.id === issueId);
  assert.ok(issue && issue.message && issue.why && issue.fixHint);
  click(ctx, row);

  // (1) the row itself expands with message / why / fix hint and Go to buttons
  const detail = ctx.document.querySelector('[data-issue-detail="' + issueId + '"]');
  assert.ok(detail, 'the selected row expanded');
  assert.ok(detail.textContent.indexOf(issue.message) >= 0, 'the message is reachable from the Issues tab');
  assert.ok(detail.textContent.indexOf(issue.why) >= 0, 'the why line is reachable');
  assert.ok(detail.querySelector('.mlv-insp__fix').textContent.indexOf(issue.fixHint) >= 0, 'the fix hint is reachable');
  const gotos = Array.from(detail.querySelectorAll('.mlv-issue__goto .mlv-btn'));
  assert.equal(gotos.length, 1 + (issue.relatedLocs || []).length, 'a Go to button per location');
  click(ctx, gotos[gotos.length - 1]);
  assert.ok(ctx.posted.filter((m) => m.type === 'openLocation').pop(), 'Go to opens the code');

  // (2) the Inspector resolves the issue's primary node instead of going blank
  const inspector = ctx.document.querySelector('[id$="-panel-inspector"]');
  assert.equal(inspector.textContent.indexOf('Select a node to inspect it.'), -1);
  assert.ok(inspector.querySelector('[data-issue-id="' + issueId + '"]'), 'the inspector shows the issue');
});

test('a clean run says so instead of blaming the filters (MLV-R1-013)', async () => {
  const ctx = await loadBundle();
  const clean = JSON.parse(JSON.stringify(sample));
  clean.issues = [];
  for (const node of clean.nodes) node.issueIds = [];
  clean.stats.issues = { low: 0, medium: 0, high: 0 };
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), clean, ctx.MLView.bridges.standalone());
  const panel = ctx.document.querySelector('[id$="-panel-issues"]');
  assert.ok(panel.querySelector('.mlv-clean'), 'the zero-issue state is its own state');
  assert.ok(panel.textContent.indexOf('No issues found') >= 0);
  assert.ok(panel.textContent.indexOf(clean.nodes.length + ' nodes') >= 0, 'it reports what was checked');
  assert.equal(panel.textContent.indexOf('No issues match these filters'), -1);
  instance.destroy();
});

test('a filtered-empty result offers the way back (MLV-R1-013)', async () => {
  const ctx = await app();
  ctx.app.setFilters({ severities: [] });
  const panel = ctx.document.querySelector('[id$="-panel-issues"]');
  assert.ok(panel.textContent.indexOf('No issues match these filters') >= 0);
  const clear = Array.from(panel.querySelectorAll('.mlv-btn')).find((b) => b.textContent === 'Clear filters');
  assert.ok(clear, 'the promised Clear filters affordance exists');
  click(ctx, clear);
  assert.equal(ctx.app.getState().filters.severities.length, 3);
  assert.ok(ctx.document.querySelector('.mlv-issue[data-issue-id]'), 'the rows came back');
});

/*
 * MLV-P6 REVERSES the second half of MLV-R1-014.
 *
 * The chip used to be drawn only for `possible` / `speculative` -- "flag doubt
 * only". Measured consequence: `certain` and `likely`, the two buckets a
 * reviewer acts on, rendered identically, and a row with no chip was ambiguous
 * between "the analyzer is sure" and "the renderer forgot". MLV-P6's acceptance
 * is "every rail row shows its bucket chip", so the assertion is inverted here
 * on purpose. What MLV-R1-014 actually protected -- that the bucket is never
 * colour-only and always reaches assistive technology -- is kept and extended.
 */
test('every row shows its confidence bucket, styled by bucket (MLV-P6, was MLV-R1-014)', async () => {
  const ctx = await loadBundle();
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues[0].confidenceBucket = 'certain';
  graph.issues[1].confidenceBucket = 'speculative';
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, ctx.MLView.bridges.standalone());
  const rowOf = (id) => ctx.document.querySelector('.mlv-issue[data-issue-id="' + id + '"]');
  const chipOf = (id) => rowOf(id).querySelector('.mlv-chip--conf');
  assert.ok(chipOf(graph.issues[0].id), 'a certain finding carries its chip too');
  assert.equal(chipOf(graph.issues[0].id).getAttribute('data-confidence'), 'certain');
  assert.equal(chipOf(graph.issues[1].id).getAttribute('data-confidence'), 'speculative');
  assert.ok(rowOf(graph.issues[0].id).textContent.indexOf('certain') >= 0);
  assert.ok(rowOf(graph.issues[1].id).textContent.indexOf('speculative') >= 0);
  // Styled by bucket, so the four are told apart by more than the word...
  assert.ok(chipOf(graph.issues[0].id).className.indexOf('mlv-chip--conf-certain') >= 0);
  assert.ok(chipOf(graph.issues[1].id).className.indexOf('mlv-chip--conf-speculative') >= 0);
  // ...and the bucket still reaches assistive tech on every row.
  assert.ok(rowOf(graph.issues[0].id).getAttribute('aria-label').indexOf('confidence certain') >= 0);
  assert.ok(chipOf(graph.issues[0].id).getAttribute('aria-label').indexOf('Confidence: certain') >= 0);
  instance.destroy();
});

test('the standalone report gets a mounted theme switch that repaints (MLV-R1-014, MLV-R1-004)', async () => {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const instance = ctx.MLView.mount(root, sample, ctx.MLView.bridges.standalone({ theme: 'light' }));
  const sw = ctx.document.querySelector('.mlv-themeswitch');
  assert.ok(sw, 'the switch is actually mounted, not just written');
  const options = Array.from(sw.querySelectorAll('[data-theme-option]')).map((b) => b.getAttribute('data-theme-option'));
  assert.deepEqual(options, ['auto', 'light', 'dark', 'hc']);
  const hc = sw.querySelector('[data-theme-option="hc"]');
  click(ctx, hc);
  assert.equal(root.getAttribute('data-theme'), 'hc', 'the mount root carries the theme');
  assert.equal(hc.getAttribute('aria-pressed'), 'true');
  instance.setTheme('dark');
  assert.equal(root.getAttribute('data-theme'), 'dark');
  instance.destroy();
  assert.equal(root.getAttribute('data-theme'), null, 'destroy leaves no theme behind');
});

test('the app claims the page-fill chain and gives it back (MLV-R1-001)', async () => {
  const ctx = await loadBundle();
  const html = ctx.document.documentElement;
  const root = ctx.document.getElementById('mlview-root');
  assert.equal(html.classList.contains('mlv-fills-page'), false);
  const instance = ctx.MLView.mount(root, sample, ctx.MLView.bridges.standalone());
  assert.ok(html.classList.contains('mlv-fills-page'), '<html> gets a definite height');
  assert.ok(ctx.document.body.classList.contains('mlv-fills-page'), '<body> too');
  instance.destroy();
  assert.equal(html.classList.contains('mlv-fills-page'), false, 'and it is released again');

  // A viewer mounted into a nested container is a guest and claims nothing.
  const nested = ctx.document.createElement('div');
  const wrapper = ctx.document.createElement('section');
  wrapper.appendChild(nested);
  ctx.document.body.appendChild(wrapper);
  const guest = ctx.MLView.mount(nested, sample, ctx.MLView.bridges.standalone());
  assert.equal(html.classList.contains('mlv-fills-page'), false, 'a nested mount never touches <html>');
  guest.destroy();
  ctx.document.body.removeChild(wrapper);
});

test('double-clicking a group header collapses without opening the file twice (MLV-R1-010)', async () => {
  const ctx = await app();
  const header = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"] .mlv-group__header');
  assert.ok(header);
  const before = ctx.posted.filter((m) => m.type === 'openLocation').length;
  // exactly what a browser emits for a double click
  header.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
  header.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 2 }));
  header.dispatchEvent(new ctx.window.MouseEvent('dblclick', { bubbles: true, cancelable: true, detail: 2 }));
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), ['n:5500cc66dd77'], 'it collapsed');
  // A control single click on the collapsed group, waited on until ITS deferred
  // openLocation lands: equal-delay timers fire in registration order, so a
  // stray from the double click would already be in the log (HEALTH-03). A
  // collapsed group re-renders as a plain node, so re-query rather than reuse
  // the now-detached header.
  const collapsed = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"]');
  const after = await afterDeferredClick(ctx, collapsed);
  assert.equal(after, before + 1, 'the double click posted no openLocation of its own');
});

test('the chevron is its own collapse target (MLV-R1-010)', async () => {
  const ctx = await app();
  const chevron = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"] .mlv-group__chevron-btn');
  assert.ok(chevron, 'the group header carries a real chevron button');
  const before = ctx.posted.filter((m) => m.type === 'openLocation').length;
  click(ctx, chevron);
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), ['n:5500cc66dd77']);
  // Same control-click proof as the double-click test above (HEALTH-03).
  const collapsed = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"]');
  const after = await afterDeferredClick(ctx, collapsed);
  assert.equal(after, before + 1, 'the chevron click posted no openLocation of its own');
});

test('a denied clipboard write never claims success (MLV-R1-007)', async () => {
  const ctx = await loadBundle();
  const rejections = [];
  ctx.window.addEventListener('unhandledrejection', (e) => rejections.push(e));
  let asked = null;
  Object.defineProperty(ctx.window.navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText(text) {
        asked = text;
        return Promise.reject(new Error('Write permission denied.'));
      },
    },
  });
  const bridge = ctx.MLView.bridges.standalone();
  bridge.post({ v: 1, type: 'copy', text: 'train.py:44' });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(asked, 'train.py:44', 'the clipboard was tried');
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast, 'a toast appeared');
  assert.ok(toast.textContent.indexOf('Copy blocked') >= 0, 'and it tells the truth: ' + toast.textContent);
  assert.deepEqual(rejections, [], 'the rejection was handled, not dropped on the page');
});

test('a granted clipboard write reports success once it lands (MLV-R1-007)', async () => {
  const ctx = await loadBundle();
  Object.defineProperty(ctx.window.navigator, 'clipboard', {
    configurable: true,
    value: { writeText: () => Promise.resolve() },
  });
  const bridge = ctx.MLView.bridges.standalone();
  bridge.post({ v: 1, type: 'copy', text: 'train.py:44' });
  assert.equal(ctx.document.querySelector('.mlv-toast--floating'), null, 'no toast before the write resolves');
  await new Promise((r) => setTimeout(r, 20));
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast && toast.textContent.indexOf('Copied') >= 0);
});

test('arrow keys move the selection among siblings', async () => {
  const ctx = await app();
  key(ctx, ctx.canvas, 'ArrowDown');
  const first = ctx.app.getState().selection;
  assert.equal(first.kind, 'node');
  key(ctx, ctx.canvas, 'ArrowDown');
  const second = ctx.app.getState().selection;
  assert.notEqual(second.id, first.id);
  key(ctx, ctx.canvas, 'ArrowUp');
  assert.equal(ctx.app.getState().selection.id, first.id);
});

test('slash focuses the search box, typing filters, Enter jumps', async () => {
  const ctx = await app();
  key(ctx, ctx.canvas, '/');
  const input = ctx.document.querySelector('.mlv-search .mlv-input');
  assert.equal(ctx.document.activeElement, input);
  input.value = 'zero_grad';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const results = ctx.document.querySelectorAll('.mlv-search__results .mlv-result');
  assert.ok(results.length >= 1, 'search found the ghost node');
  key(ctx, input, 'Enter');
  assert.equal(ctx.app.getState().selection.id, 'n:ffee11223344');

  input.value = 'MLV201';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  const codeHits = Array.from(ctx.document.querySelectorAll('.mlv-result__label')).map((n) => n.textContent);
  assert.ok(codeHits.some((t) => t.indexOf('MLV201') >= 0), 'rule codes are searchable');

  input.value = 'zzzznothing';
  input.dispatchEvent(new ctx.window.Event('input', { bubbles: true }));
  assert.ok(ctx.document.querySelector('.mlv-result__empty'), 'empty search state');
});

test('double-clicking a group header collapses and expands it', async () => {
  const ctx = await app();
  const header = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"] .mlv-group__header');
  assert.ok(header);
  assert.ok(ctx.document.querySelector('[data-node-id="n:9c8d7e6f5a4b"]'));
  click(ctx, header, 'dblclick');
  assert.equal(ctx.document.querySelector('[data-node-id="n:9c8d7e6f5a4b"]'), null, 'children hidden');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx.app.getState().collapsed)), ['n:5500cc66dd77']);
  const collapsedCard = ctx.document.querySelector('[data-node-id="n:5500cc66dd77"]');
  click(ctx, collapsedCard, 'dblclick');
  assert.ok(ctx.document.querySelector('[data-node-id="n:9c8d7e6f5a4b"]'), 'children restored');
  assert.equal(ctx.app.getState().collapsed.length, 0);
});

test('the rail issue rows select, reveal and open', async () => {
  const ctx = await app();
  const row = ctx.document.querySelector('[data-issue-id="i:1234abcd5678"]');
  assert.ok(row);
  click(ctx, row);
  const state = ctx.app.getState();
  assert.equal(state.selection.kind, 'issue');
  assert.equal(state.selection.id, 'i:1234abcd5678');
  assert.equal(state.railTab, 'issues');
  const primary = ctx.document.querySelector('[data-node-id="n:ffee11223344"]');
  assert.ok(primary.classList.contains('is-selected'), 'the primary node is revealed');
  const open = ctx.document
    .querySelector('[data-issue-id="i:1234abcd5678"]')
    .parentElement.querySelector('.mlv-issue__open');
  click(ctx, open);
  const msg = ctx.posted.filter((m) => m.type === 'openLocation').pop();
  assert.equal(msg.file, 'train.py');
  assert.equal(msg.line, 44);
});

test('the inspector shows attrs, ports, evidence, issues and related locations', async () => {
  const ctx = await app();
  click(ctx, ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]'));
  const inspector = Array.from(ctx.document.querySelectorAll('.mlv-rail__panel')).find(
    (p) => p.id.indexOf('-panel-inspector') >= 0,
  );
  assert.equal(inspector.hidden, false, 'selecting a node opens the inspector');
  const text = inspector.textContent;
  assert.ok(text.indexOf('train_loader') >= 0);
  assert.ok(text.indexOf('num_workers') >= 0, 'attrs table');
  assert.ok(text.indexOf('LOADER') >= 0, 'ports and value tags');
  assert.ok(text.indexOf('knowledge_table') >= 0, 'stage evidence "why"');
  assert.ok(text.indexOf('MLV110') >= 0, 'its issues');
  const related = inspector.querySelectorAll('.mlv-insp__related .mlv-link');
  assert.ok(related.length >= 1, 'related locations are clickable');
  click(ctx, related[0]);
  assert.ok(ctx.posted.filter((m) => m.type === 'openLocation').length > 0);
});

test('selecting an issue with relatedLocs draws the numbered connectors', async () => {
  const ctx = await app();
  ctx.app.focusIssue('i:5b3c7d9e1f02');
  const connectors = ctx.document.querySelectorAll('.mlv-connector-group');
  assert.ok(connectors.length >= 1, 'a multi-location issue draws its connector');
  assert.equal(connectors[0].getAttribute('data-sev'), 'high');
});

test('the not-detected chip row names absent stages', async () => {
  const ctx = await app();
  const chips = ctx.document.querySelector('.mlv-chiprow');
  assert.equal(chips.hidden, false);
  assert.ok(chips.textContent.indexOf('not detected') >= 0);
  assert.ok(chips.textContent.indexOf('Save / Deploy') >= 0);
});

test('mounting without a graph shows the loading skeleton', async () => {
  const ctx = await loadBundle();
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), null, bridge);
  const loading = ctx.document.querySelector('.mlv-state--loading');
  assert.ok(loading && loading.hidden === false, 'skeleton is visible before the first graph');
  assert.ok(ctx.document.querySelectorAll('.mlv-skeleton__card').length === 9);
  instance.destroy();
});

test('an empty graph shows the designed empty state, not a blank canvas', async () => {
  const ctx = await loadBundle();
  const empty = JSON.parse(JSON.stringify(sample));
  empty.nodes = [];
  empty.edges = [];
  empty.issues = [];
  empty.diagnostics = [{ kind: 'parse_error', message: 'invalid syntax', file: 'legacy/old.py', line: 12 }];
  for (const stage of empty.stages) stage.present = false;
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), empty, ctx.MLView.bridges.standalone());
  const state = ctx.document.querySelector('.mlv-state--empty');
  assert.ok(state, 'the empty state is rendered');
  assert.ok(state.textContent.indexOf('No ML pipeline found') >= 0);
  assert.ok(state.textContent.indexOf('legacy/old.py') >= 0, 'diagnostics are listed');
  instance.destroy();
});

test('partial-understanding, truncated and notebook states surface', async () => {
  const ctx = await loadBundle();
  const graph = JSON.parse(JSON.stringify(sample));
  graph.nodes[0].dynamic = true;
  graph.stats.truncated = true;
  graph.diagnostics = [
    { kind: 'dynamic_scope', message: 'getattr factory in registry.py', file: 'registry.py', line: 7 },
    { kind: 'notebook_skipped', message: '2 notebooks detected but not analyzed.', count: 2 },
    { kind: 'framework_suppressed', message: 'Training loop handled by PyTorch Lightning', codes: ['MLV201', 'MLV301'] },
  ];
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, ctx.MLView.bridges.standalone());
  const banners = ctx.document.querySelector('.mlv-banners').textContent;
  assert.ok(banners.indexOf('Partial understanding') >= 0);
  assert.ok(banners.indexOf('truncated') >= 0);
  const chips = ctx.document.querySelector('.mlv-chiprow').textContent;
  assert.ok(chips.indexOf('notebooks not analyzed') >= 0);
  assert.ok(chips.indexOf('Lightning') >= 0);
  assert.ok(chips.indexOf('MLV201') >= 0);
  instance.destroy();
});

test('suppressed findings are hidden until the toggle is pressed', async () => {
  const ctx = await loadBundle();
  const graph = JSON.parse(JSON.stringify(sample));
  graph.issues[0].suppressed = true;
  const suppressedId = graph.issues[0].id;
  const instance = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, ctx.MLView.bridges.standalone());
  assert.equal(ctx.document.querySelector('[data-issue-id="' + suppressedId + '"]'), null);
  instance.setFilters({ showSuppressed: true });
  const row = ctx.document.querySelector('[data-issue-id="' + suppressedId + '"]');
  assert.ok(row, 'the suppressed row appears');
  assert.ok(row.classList.contains('is-suppressed'));
  instance.destroy();
});

test('the minimap appears only above 30 nodes and collapses away (MLV-R2-W12)', async () => {
  // UX_DESIGN section 1: "appears only above 30 nodes, collapsible to a 28 px
  // chevron tab". The sample's dozen boxes do not earn the corner it occupies.
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

test('stage chips filter the canvas and Clear filters restores it', async () => {
  const ctx = await app();
  const chips = ctx.document.querySelectorAll('[data-stage-filter]');
  assert.equal(chips.length, 7, 'one chip per present stage');
  const train = ctx.document.querySelector('[data-stage-filter="train"]');
  click(ctx, train);
  const state = ctx.app.getState();
  assert.deepEqual(JSON.parse(JSON.stringify(state.filters.stages)).sort().indexOf('train'), -1, 'train is filtered out');
  const trainNode = ctx.document.querySelector('[data-node-id="n:33dd44ee55ff"]');
  assert.ok(trainNode.classList.contains('is-filtered'), 'its nodes dim out');
  const evalNode = ctx.document.querySelector('[data-node-id="n:c072e5a41d38"]');
  assert.equal(evalNode.classList.contains('is-filtered'), false, 'other lanes are untouched');

  const clearBtn = Array.from(ctx.document.querySelectorAll('.mlv-filterrow .mlv-btn')).find(
    (b) => b.textContent === 'Clear filters',
  );
  assert.ok(clearBtn, 'a Clear filters affordance appears once a filter is active');
  click(ctx, clearBtn);
  assert.equal(ctx.app.getState().filters.stages.length, 0);
  assert.equal(
    ctx.document.querySelector('[data-node-id="n:33dd44ee55ff"]').classList.contains('is-filtered'),
    false,
  );
});

test('zoom-to-selection frames the selected node', async () => {
  const ctx = await app();
  const zoomSel = ctx.document.querySelector('button[aria-label="Zoom to selection"]');
  assert.equal(zoomSel.disabled, true, 'disabled with nothing selected');
  click(ctx, ctx.document.querySelector('[data-node-id="n:ffee11223344"]'));
  const before = ctx.app.getState().viewport;
  key(ctx, ctx.canvas, 'z');
  const after = ctx.app.getState().viewport;
  assert.notEqual(before.zoom + ':' + before.x, after.zoom + ':' + after.x, 'the viewport moved');
  assert.ok(after.zoom > before.zoom, 'it zoomed in on a single card');
});

test('askAssistant is posted only when the host offers the capability', async () => {
  const ctx = await loadBundle();
  const posted = [];
  const makeBridge = (canAsk) => ({
    host: 'vscode',
    theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: canAsk },
    post: (m) => posted.push(m),
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  });
  const root = ctx.document.getElementById('mlview-root');
  let instance = ctx.MLView.mount(root, sample, makeBridge(false));
  click(ctx, ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]'));
  assert.equal(
    Array.from(ctx.document.querySelectorAll('.mlv-insp__actions .mlv-btn')).some((b) => /Ask/.test(b.textContent)),
    false,
    'hidden when the host cannot ask',
  );
  instance.destroy();

  instance = ctx.MLView.mount(root, sample, makeBridge(true));
  click(ctx, ctx.document.querySelector('[data-node-id="n:7c1a90b4e2f0"]'));
  const ask = Array.from(ctx.document.querySelectorAll('.mlv-insp__actions .mlv-btn')).find((b) => /Ask/.test(b.textContent));
  assert.ok(ask, 'shown when the host offers it');
  click(ctx, ask);
  const msg = posted.filter((m) => m.type === 'askAssistant').pop();
  assert.equal(msg.nodeId, 'n:7c1a90b4e2f0');
  assert.ok(msg.prompt.indexOf('torch.utils.data.DataLoader') >= 0);
  assert.ok(msg.prompt.indexOf('data.py:31') >= 0);
  instance.destroy();
});

test('fit() prefers the width for a tall document instead of the zoom floor (MLV-R1-002)', async () => {
  const ctx = await app();
  const vp = ctx.app.getState().viewport;
  // A pipeline is much taller than it is wide; scaling its whole height into a
  // wide panel lands at MIN_ZOOM with 3 px text and an empty canvas.
  assert.ok(vp.zoom >= 0.45, 'first paint is at ' + vp.zoom + ' (floor was 0.15)');
  assert.equal(vp.y, 24, 'a width-fit anchors at the top so the user pans down');

  // pressing 0 re-fits to the same place
  key(ctx, ctx.canvas, '-');
  assert.ok(ctx.app.getState().viewport.zoom < vp.zoom);
  key(ctx, ctx.canvas, '0');
  assert.equal(ctx.app.getState().viewport.zoom, vp.zoom);
});
