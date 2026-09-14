/**
 * H5 — the structured fix, rendered.
 *
 * `REQUIREMENTS.md` §5 non-goal 5 was lifted for this item with five guardrails
 * attached, and four of the five are properties of THIS half of it:
 *
 *   - rules OPT IN, so the marker is drawn from `Issue.fix`'s presence and never
 *     inferred from `fixHint`, which all 36 rules carry as prose;
 *   - the edit is shown VERBATIM, so what a reader approves is what would be
 *     written — no re-indentation, no prettifying, no wrapping;
 *   - it is NEVER auto-applied: the viewer posts `applyFix` and stops, and a
 *     host that cannot edit gets the clipboard instead and is told so;
 *   - `needs-review` never reads as `mechanical`, including for a safety word a
 *     newer analyzer invents.
 *
 * The fifth — no fix below the `likely` bucket — is the analyzer's, and the
 * confidence chip beside the marker is what makes it auditable from here.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();

const MECHANICAL = {
  title: 'Add optimizer.zero_grad() before the backward pass',
  safety: 'mechanical',
  edits: [
    {
      file: 'train.py',
      absFile: '/w/train.py',
      line: 29,
      col: 12,
      endLine: 29,
      endCol: 12,
      newText: 'optimizer.zero_grad()\n            ',
    },
  ],
};

const NEEDS_REVIEW = {
  title: 'Pass shuffle=True to the training DataLoader',
  safety: 'needs-review',
  edits: [
    { file: 'data.py', absFile: '/w/data.py', line: 33, col: 34, endLine: 33, endCol: 34, newText: ', shuffle=True' },
  ],
};

/** The sample, with a fix on the first high finding and on the first medium. */
function graphWithFixes(overrides = {}) {
  const graph = JSON.parse(JSON.stringify(sample));
  const high = graph.issues.find((i) => i.severity === 'high');
  const medium = graph.issues.find((i) => i.severity === 'medium');
  high.fix = JSON.parse(JSON.stringify(overrides.high || MECHANICAL));
  medium.fix = JSON.parse(JSON.stringify(overrides.medium || NEEDS_REVIEW));
  return { graph, high, medium };
}

async function mount(graph, host = 'standalone') {
  const ctx = await loadBundle();
  const posted = [];
  const bridge = {
    host,
    theme: 'light',
    capabilities: {
      canOpenSource: true,
      canReanalyze: host === 'vscode',
      canExport: host === 'vscode',
      canAskAssistant: false,
    },
    post: (msg) => posted.push(msg),
    onMessage: () => () => undefined,
    saveState: () => undefined,
    loadState: () => null,
  };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app, posted };
}

const click = (ctx, el) => el.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
const rowOf = (ctx, id) => ctx.document.querySelector('.mlv-issue[data-issue-id="' + id + '"]');

/* ── the marker ────────────────────────────────────────────────────────── */

test('a rule that did not opt in gets no marker at all (H5)', async () => {
  const ctx = await mount(sample);
  assert.equal(ctx.document.querySelector('[data-fix]'), null, 'the shipped sample carries no Issue.fix');
  assert.equal(ctx.document.querySelector('[data-apply-fix]'), null);
  // ...and every one of those findings still carries its prose hint, which is
  // what makes the marker's absence information rather than an omission.
  const row = rowOf(ctx, sample.issues[0].id);
  click(ctx, row);
  const detail = ctx.document.querySelector('[data-issue-detail="' + sample.issues[0].id + '"]');
  assert.ok(detail.querySelector('.mlv-insp__fix').textContent.length > 0, 'fixHint is still drawn');
});

test('"Fix available" is on the rail row, beside the bucket it was gated on (H5)', async () => {
  const { graph, high } = graphWithFixes();
  const ctx = await mount(graph);
  const row = rowOf(ctx, high.id);
  const chip = row.querySelector('[data-fix]');
  assert.ok(chip, 'the marker is on the row');
  assert.equal(chip.getAttribute('data-fix'), 'mechanical');
  assert.ok(chip.textContent.indexOf('Fix available') >= 0, chip.textContent);
  assert.ok(chip.title.indexOf(MECHANICAL.title) >= 0, chip.title);
  assert.ok(row.querySelector('.mlv-chip--conf'), 'and the confidence chip is beside it');
  // A row is a `role="option"`, which may not contain a focusable descendant.
  assert.equal(chip.tagName, 'SPAN');
  assert.equal(row.querySelector('button'), null, 'the marker never makes the row a nested control');
});

test('needs-review never reads as mechanical, including for an unknown word (H5)', async () => {
  const odd = { ...MECHANICAL, safety: 'probably-fine-honestly' };
  const { graph, high, medium } = graphWithFixes({ high: odd });
  const ctx = await mount(graph, 'vscode');
  assert.equal(rowOf(ctx, high.id).querySelector('[data-fix]').getAttribute('data-fix'), 'needs review');
  assert.equal(rowOf(ctx, medium.id).querySelector('[data-fix]').getAttribute('data-fix'), 'needs review');
});

test('a fix with no edits is not a fix (H5)', async () => {
  const { graph, high } = graphWithFixes({ high: { title: 'Something', safety: 'mechanical', edits: [] } });
  const ctx = await mount(graph);
  assert.equal(rowOf(ctx, high.id).querySelector('[data-fix]'), null, 'the field is present and says nothing');
});

/* ── the Inspector ─────────────────────────────────────────────────────── */

test('the Inspector shows the title, the safety and the edit as a snippet (H5)', async () => {
  const { graph, high } = graphWithFixes();
  const ctx = await mount(graph, 'vscode');
  ctx.app.focusNode(high.nodeIds[0]);
  const box = ctx.document.querySelector('[id$="-panel-inspector"] [data-fix-issue="' + high.id + '"]');
  assert.ok(box, 'the fix section is in the Inspector');
  assert.equal(box.getAttribute('data-fix-safety'), 'mechanical');
  assert.ok(box.querySelector('.mlv-fix__title').textContent === MECHANICAL.title, 'the title, verbatim');
  assert.equal(box.querySelector('.mlv-chip--fix-safety').textContent, 'mechanical');
  const where = box.querySelector('[data-fix-edit]');
  assert.equal(where.getAttribute('data-fix-edit'), 'train.py:29');
  assert.ok(where.textContent.indexOf('insert') > 0, 'an empty range is an insertion: ' + where.textContent);
  const pre = box.querySelector('[data-fix-newtext]');
  assert.equal(pre.tagName, 'PRE');
  assert.equal(pre.textContent, MECHANICAL.edits[0].newText, 'the edit, character for character');
});

test('a replacement and a deletion are named for what they are (H5)', async () => {
  const replace = {
    title: 'Replace the call',
    safety: 'mechanical',
    edits: [{ file: 'a.py', absFile: '/w/a.py', line: 3, col: 0, endLine: 3, endCol: 10, newText: 'g()' }],
  };
  const remove = {
    title: 'Drop the call',
    safety: 'mechanical',
    edits: [{ file: 'a.py', absFile: '/w/a.py', line: 4, col: 0, endLine: 4, endCol: 10, newText: '' }],
  };
  const { graph, high, medium } = graphWithFixes({ high: replace, medium: remove });
  const ctx = await mount(graph, 'vscode');
  ctx.app.focusIssue(high.id);
  click(ctx, rowOf(ctx, high.id));
  assert.ok(
    ctx.document.querySelector('[data-issue-detail="' + high.id + '"] [data-fix-edit]').textContent.indexOf('replace') > 0,
  );
  click(ctx, rowOf(ctx, medium.id));
  assert.ok(
    ctx.document.querySelector('[data-issue-detail="' + medium.id + '"] [data-fix-edit]').textContent.indexOf('delete') > 0,
  );
});

/* ── the action: a request, never an edit ──────────────────────────────── */

test('VS Code gets an `applyFix` request carrying an id and nothing else (H5)', async () => {
  const { graph, high } = graphWithFixes();
  const ctx = await mount(graph, 'vscode');
  ctx.app.focusNode(high.nodeIds[0]);
  const button = ctx.document.querySelector('[id$="-panel-inspector"] [data-apply-fix="' + high.id + '"]');
  assert.ok(button, 'the Inspector offers the action');
  assert.equal(button.textContent, 'Apply fix');
  click(ctx, button);
  const sent = ctx.posted.filter((m) => m.type === 'applyFix');
  assert.equal(sent.length, 1);
  // Compared field by field: the frame is built inside the bundle's realm, so a
  // prototype-strict deep compare fails on identical objects.
  assert.deepEqual(Object.keys(sent[0]).sort(), ['issueId', 'type', 'v'], 'an id, and no bytes the host did not choose');
  assert.equal(sent[0].v, 1);
  assert.equal(sent[0].issueId, high.id);
  assert.equal(ctx.posted.filter((m) => m.type === 'copy').length, 0, 'and nothing was written or copied here');
});

test('a needs-review fix asks to be read before it is applied (H5)', async () => {
  const { graph, medium } = graphWithFixes();
  const ctx = await mount(graph, 'vscode');
  ctx.app.focusNode(medium.nodeIds[0]);
  const button = ctx.document.querySelector('[id$="-panel-inspector"] [data-apply-fix="' + medium.id + '"]');
  assert.equal(button.textContent, 'Review fix…');
  const box = ctx.document.querySelector('[data-fix-issue="' + medium.id + '"]');
  assert.ok(box.textContent.indexOf('preview') > 0, 'and the promise is stated before the button: ' + box.textContent);
});

test('the standalone report copies the snippet and never claims to have edited (H5)', async () => {
  const { graph, high } = graphWithFixes();
  const ctx = await mount(graph, 'standalone');
  ctx.app.focusNode(high.nodeIds[0]);
  const box = ctx.document.querySelector('[data-fix-issue="' + high.id + '"]');
  assert.ok(box.textContent.indexOf('cannot edit files') > 0, box.textContent);
  const button = box.querySelector('[data-apply-fix]');
  assert.equal(button.textContent, 'Copy fix');
  click(ctx, button);
  assert.equal(ctx.posted.filter((m) => m.type === 'applyFix').length, 0, 'no host to ask, so nothing is asked');
  const copies = ctx.posted.filter((m) => m.type === 'copy');
  assert.equal(copies.length, 1);
  assert.ok(copies[0].text.indexOf('train.py:29') >= 0, copies[0].text);
  assert.ok(copies[0].text.indexOf('optimizer.zero_grad()') >= 0, copies[0].text);
  const live = ctx.document.querySelector('[aria-live]');
  assert.ok(live.textContent.indexOf('Copied') === 0, 'the announcement says what happened: ' + live.textContent);
  assert.ok(live.textContent.indexOf('cannot edit files') > 0, live.textContent);
});

test('the expanded rail row carries the same disclosure as the Inspector (H5)', async () => {
  const { graph, high } = graphWithFixes();
  const ctx = await mount(graph, 'vscode');
  click(ctx, rowOf(ctx, high.id));
  const detail = ctx.document.querySelector('[data-issue-detail="' + high.id + '"]');
  const box = detail.querySelector('[data-fix-issue="' + high.id + '"]');
  assert.ok(box, 'the row expands with the fix');
  assert.equal(box.querySelector('[data-fix-newtext]').textContent, MECHANICAL.edits[0].newText);
  // The prose hint comes FIRST: advice, then the diff of it.
  const order = Array.from(detail.children).map((el) => el.className);
  assert.ok(order.indexOf('mlv-insp__fix') < order.indexOf('mlv-fix'), order.join(' | '));
});
