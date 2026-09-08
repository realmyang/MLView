/**
 * MLV-P10 (suppression as a one-click action), MLV-P1 (the Pipeline Answer
 * Card) and CI-ADOPT's rendering half — the three viewer surfaces that let a
 * reader act on a finding rather than only read it.
 *
 * MLV-P10: suppression works on the CLI and was unreachable from every UI, so
 * the workflow for "this one is a false positive" was to find a doc in the repo,
 * memorise the syntax, switch to the editor and type it. The viewer never writes
 * anything: "copy" goes through the host's clipboard and "disable" is a REQUEST
 * the host answers.
 *
 * MLV-P1: the four headline questions, answered in words, above the diagram.
 *
 * CI-ADOPT: a run attributed against a base revision marks each finding `new`,
 * `touched` or `existing`, and a baselined finding is marked, never deleted.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, readSample } from './helpers.mjs';

const sample = await readSample();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function clone() {
  return JSON.parse(JSON.stringify(sample));
}

async function mount(graph = sample, opts = {}) {
  const ctx = await loadBundle();
  const posted = [];
  const copied = [];
  Object.defineProperty(ctx.window.navigator, 'clipboard', {
    value: {
      writeText: (text) => {
        copied.push(text);
        return Promise.resolve();
      },
    },
    configurable: true,
  });
  const bridge = opts.standalone
    ? ctx.MLView.bridges.standalone({ theme: 'light', onPost: (msg) => posted.push(msg) })
    : {
        host: 'standalone',
        theme: 'light',
        capabilities: { canOpenSource: true, canReanalyze: false, canExport: false, canAskAssistant: false },
        post: (msg) => posted.push(msg),
        onMessage: () => () => undefined,
        saveState: () => undefined,
        loadState: () => null,
      };
  const app = ctx.MLView.mount(ctx.document.getElementById('mlview-root'), graph, bridge);
  return { ...ctx, app, posted, copied };
}

function click(ctx, target) {
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
}

/* ── MLV-P10: the two actions ──────────────────────────────────────────── */

test('every rail row carries both suppression actions (MLV-P10)', async () => {
  const ctx = await mount();
  const rows = Array.from(ctx.document.querySelectorAll('[data-issue-id][role="option"]'));
  assert.ok(rows.length >= 3, 'the rail lists findings: ' + rows.length);
  for (const row of rows) {
    const li = row.parentElement;
    const code = row.getAttribute('aria-label').split(' ')[0];
    assert.ok(li.querySelector('[data-copy-ignore="' + code + '"]'), code + ' offers "Copy ignore comment"');
    assert.ok(li.querySelector('[data-disable-rule="' + code + '"]'), code + ' offers "Disable this rule"');
  }
  // `role="option"` may not contain a focusable descendant (MLV-R2-W03).
  for (const row of rows) {
    assert.equal(row.querySelector('button'), null, 'the actions are siblings of the option, never children');
  }
  ctx.app.destroy();
});

test('"Copy ignore comment" copies the documented comment and says so (MLV-P10)', async () => {
  const ctx = await mount();
  const btn = ctx.document.querySelector('[data-copy-ignore]');
  const code = btn.getAttribute('data-copy-ignore');
  click(ctx, btn);
  const copy = ctx.posted.filter((m) => m.type === 'copy');
  assert.equal(copy.length, 1, 'exactly one copy message');
  assert.equal(copy[0].text, '# mlview: ignore[' + code + ']', 'the comment the analyzer actually reads');
  const toast = ctx.document.querySelector('.mlv-toast');
  assert.ok(toast && toast.textContent.indexOf('# mlview: ignore[' + code + ']') >= 0, 'and a toast: ' + (toast && toast.textContent));
  ctx.app.destroy();
});

test('"Disable this rule" posts suppressRule and never writes anything (MLV-P10)', async () => {
  const ctx = await mount();
  const btn = ctx.document.querySelector('[data-disable-rule]');
  const code = btn.getAttribute('data-disable-rule');
  click(ctx, btn);
  const asked = ctx.posted.filter((m) => m.type === 'suppressRule');
  assert.equal(asked.length, 1, 'exactly one request');
  // `scope` is what the viewer means; `action` is the discriminator the VS Code
  // host validates against (its isUiToHost rejects a suppressRule without one).
  assert.deepEqual(JSON.parse(JSON.stringify(asked[0])), {
    v: 1,
    type: 'suppressRule',
    code,
    scope: 'workspace',
    action: 'disable',
  });
  ctx.app.destroy();
});

test('the standalone bridge answers suppressRule with the .mlview.toml snippet (MLV-P10)', async () => {
  const ctx = await mount(sample, { standalone: true });
  const btn = ctx.document.querySelector('[data-disable-rule]');
  const code = btn.getAttribute('data-disable-rule');
  click(ctx, btn);
  await sleep(20);
  assert.deepEqual(ctx.copied, ['[rules]\n' + code + ' = "off"'], 'the snippet reaches the clipboard');
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast && toast.textContent.indexOf(code) >= 0, 'through the copy toast: ' + (toast && toast.textContent));
  ctx.app.destroy();
});

test('a rule group header silences the whole class in one gesture (MLV-P10, RAIL-GROUP)', async () => {
  const graph = clone();
  // Two occurrences of one code make a group with a header (GROUP_HEADER_MIN).
  const twin = JSON.parse(JSON.stringify(graph.issues[0]));
  twin.id = twin.id.slice(0, -1) + 'f';
  graph.issues.push(twin);
  const ctx = await mount(graph);
  ctx.app.getState();
  const railGroup = ctx.document.querySelector('[data-group-mode="rule"]');
  click(ctx, railGroup);
  const header = ctx.document.querySelector('.mlv-railgroup__bar');
  assert.ok(header, 'a rule group header is drawn');
  const disable = header.querySelector('[data-disable-rule]');
  assert.ok(disable, 'and carries "Disable this rule"');
  assert.ok(
    (disable.getAttribute('aria-label') || '').indexOf('Disable ' + graph.issues[0].code) >= 0,
    'named for the whole class: ' + disable.getAttribute('aria-label'),
  );
  click(ctx, disable);
  assert.equal(ctx.posted.filter((m) => m.type === 'suppressRule').length, 1);

  // Grouped by FILE the actions are absent: a file group's key is a path, and
  // "disable this rule" over several codes would be a lie about what it does.
  click(ctx, ctx.document.querySelector('[data-group-mode="file"]'));
  assert.equal(ctx.document.querySelector('.mlv-railgroup__bar'), null, 'no rule actions on a file group');
  ctx.app.destroy();
});

test('the Inspector spells both actions out (MLV-P10)', async () => {
  const ctx = await mount();
  const row = ctx.document.querySelector('[data-issue-id][role="option"]');
  click(ctx, row);
  const inspectorTab = Array.from(ctx.document.querySelectorAll('.mlv-rail__tab')).find((t) => t.textContent === 'Inspector');
  click(ctx, inspectorTab);
  const box = ctx.document.querySelector('.mlv-insp__suppress');
  assert.ok(box, 'the Inspector issue carries the action row');
  assert.equal(box.querySelectorAll('button').length, 2, 'both actions');
  assert.equal(box.querySelector('[data-copy-ignore]').textContent, 'Copy ignore comment', 'spelled out, not icon-only');
  ctx.app.destroy();
});

/* ── MLV-P10 + CI-ADOPT: the collapsed "N suppressed" section ──────────── */

test('suppressed findings render in a collapsed section, not nowhere (MLV-P10)', async () => {
  const graph = clone();
  graph.issues[0].suppressed = true;
  graph.issues[1].suppressed = true;
  const ctx = await mount(graph);
  const section = ctx.document.querySelector('[data-suppressed-section]');
  assert.ok(section, 'the section exists');
  assert.equal(section.getAttribute('data-suppressed-section'), '2', 'and counts them');
  const head = section.querySelector('[data-suppressed-toggle]');
  assert.equal(head.textContent.indexOf('2 suppressed') >= 0, true, 'headed by the count: ' + head.textContent);
  assert.equal(head.getAttribute('aria-expanded'), 'false', 'collapsed by default');
  assert.equal(section.querySelectorAll('[data-issue-id]').length, 0, 'and folded away');

  click(ctx, head);
  const open = ctx.document.querySelector('[data-suppressed-section]');
  assert.equal(open.querySelector('[data-suppressed-toggle]').getAttribute('aria-expanded'), 'true');
  assert.equal(open.querySelectorAll('[data-issue-id][role="option"]').length, 2, 'both rows are auditable');
  ctx.app.destroy();
});

test('a document whose findings are all suppressed still says so (MLV-P10)', async () => {
  const graph = clone();
  for (const issue of graph.issues) issue.suppressed = true;
  const ctx = await mount(graph);
  const zero = ctx.document.querySelector('[data-all-suppressed]');
  assert.ok(zero, 'a fifth zero: silenced, not clean and not filtered');
  assert.equal(zero.getAttribute('data-all-suppressed'), String(graph.issues.length));
  assert.equal(ctx.document.querySelector('.mlv-clean'), null, '"No issues found" would be a clean bill of health');
  const section = ctx.document.querySelector('[data-suppressed-section]');
  assert.ok(section, '"No issues found" over six silenced findings is not a clean bill of health');
  assert.equal(section.getAttribute('data-suppressed-section'), String(graph.issues.length));
  ctx.app.destroy();
});

test('baselined findings land in the same section with their own chip (CI-ADOPT)', async () => {
  const graph = clone();
  graph.issues[0].baselined = true;
  graph.issues[1].baselined = true;
  graph.issues[2].suppressed = true;
  const ctx = await mount(graph);
  const section = ctx.document.querySelector('[data-suppressed-section]');
  assert.equal(section.getAttribute('data-suppressed-section'), '3');
  const head = section.querySelector('[data-suppressed-toggle]').textContent;
  assert.ok(head.indexOf('2 baselined') >= 0, 'the header counts them apart: ' + head);
  click(ctx, section.querySelector('[data-suppressed-toggle]'));
  const chips = Array.from(ctx.document.querySelectorAll('[data-suppressed-section] .mlv-chip--baselined'));
  assert.equal(chips.length, 2, 'each baselined row is chipped');
  assert.equal(chips[0].textContent, 'baselined');
  ctx.app.destroy();
});

/* ── CI-ADOPT: the change chips and the "only changed" filter ──────────── */

test('an attributed run chips every row new / touched / existing (CI-ADOPT)', async () => {
  const graph = clone();
  graph.issues[0].change = 'new';
  graph.issues[1].change = 'touched';
  for (const issue of graph.issues.slice(2)) issue.change = 'existing';
  const ctx = await mount(graph);
  const chips = Array.from(ctx.document.querySelectorAll('.mlv-rail [data-change]')).map((c) => c.textContent);
  assert.equal(chips.filter((c) => c === 'new').length, 1);
  assert.equal(chips.filter((c) => c === 'touched').length, 1);
  assert.equal(chips.filter((c) => c === 'existing').length, graph.issues.length - 2);
  ctx.app.destroy();
});

test('"only changed" drops existing findings and nothing else (CI-ADOPT)', async () => {
  const graph = clone();
  graph.issues[0].change = 'new';
  graph.issues[1].change = 'touched';
  for (const issue of graph.issues.slice(2)) issue.change = 'existing';
  const ctx = await mount(graph);
  const chip = ctx.document.querySelector('[data-changed-filter]');
  assert.ok(chip, 'the filter is offered on an attributed document');
  assert.equal(chip.getAttribute('aria-pressed'), 'false', 'off by default');
  click(ctx, chip);
  const rows = Array.from(ctx.document.querySelectorAll('.mlv-rail [data-issue-id][role="option"]'));
  assert.equal(rows.length, 2, 'only the new and the touched finding survive');
  assert.equal(ctx.app.getState().filters.changedOnly, true, 'and the filter persists');
  click(ctx, ctx.document.querySelector('[data-changed-filter]'));
  assert.equal(ctx.app.getState().filters.changedOnly, undefined, 'absent at its default, like `flow`');
  ctx.app.destroy();
});

test('an unattributed run offers no filter and hides nothing (CI-ADOPT)', async () => {
  const ctx = await mount();
  assert.equal(ctx.document.querySelector('[data-changed-filter]'), null, 'no attribution, no filter');
  assert.equal(ctx.document.querySelectorAll('.mlv-rail [data-change]').length, 0, 'and no chips');
  // The degradation rule: `changedOnly` on a document with no `change` field
  // must show everything rather than nothing.
  ctx.app.setFilters({ changedOnly: true });
  const rows = ctx.document.querySelectorAll('.mlv-rail [data-issue-id][role="option"]');
  assert.equal(rows.length, sample.issues.length, 'unattributed findings are never dropped');
  ctx.app.destroy();
});

/* ── MLV-P1: the Pipeline Answer Card ──────────────────────────────────── */

const ANSWERS = {
  dataEntry: {
    sentence: 'Data enters through load_data() and is split by train_test_split.',
    nodeIds: [],
    locs: [
      { file: 'data.py', absFile: '/w/data.py', line: 26, col: 0, endLine: 26, endCol: 10 },
      { file: 'data.py', absFile: '/w/data.py', line: 31, col: 0, endLine: 31, endCol: 10 },
    ],
    confidence: 0.9,
  },
  objective: {
    sentence: 'CrossEntropyLoss is minimised by Adam at lr=1e-3.',
    nodeIds: [],
    locs: [{ file: 'train.py', absFile: '/w/train.py', line: 23, col: 0, endLine: 23, endCol: 10 }],
    confidence: 0.8,
  },
  evaluation: {
    sentence: 'The eval loop is guarded by model.eval() and torch.no_grad().',
    nodeIds: [],
    locs: [{ file: 'train.py', absFile: '/w/train.py', line: 44, col: 0, endLine: 44, endCol: 10 }],
    confidence: 0.7,
  },
  verdict: {
    sentence: 'Could not determine which finding matters most.',
    nodeIds: [],
    locs: [],
    confidence: 0.3,
  },
};

test('no answers block, no card (MLV-P1)', async () => {
  const ctx = await mount();
  const card = ctx.document.querySelector('[data-answers]');
  assert.ok(card, 'the card element exists');
  assert.equal(card.hidden, true, 'and is hidden outright when the document carries no answers');
  ctx.app.destroy();
});

test('the card states four sentences with clickable citations (MLV-P1)', async () => {
  const graph = clone();
  graph.answers = ANSWERS;
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-answers]');
  assert.equal(card.hidden, false, 'the card is drawn');
  const items = Array.from(card.querySelectorAll('[data-answer]'));
  assert.deepEqual(items.map((i) => i.getAttribute('data-answer')), ['dataEntry', 'objective', 'evaluation', 'verdict']);
  assert.equal(
    card.querySelector('[data-answer-sentence="objective"]').textContent,
    ANSWERS.objective.sentence,
    'verbatim, never paraphrased',
  );
  const cites = Array.from(card.querySelectorAll('[data-answer-loc]')).map((b) => b.textContent);
  assert.deepEqual(cites, ['data.py:26', 'data.py:31', 'train.py:23', 'train.py:44']);

  click(ctx, card.querySelector('[data-answer-loc="train.py:23"]'));
  const opened = ctx.posted.filter((m) => m.type === 'openLocation');
  assert.equal(opened.length, 1, 'a citation opens its location');
  assert.equal(opened[0].file, 'train.py');
  assert.equal(opened[0].line, 23);
  ctx.app.destroy();
});

test('a citation carrying only file and line still opens (MLV-P1)', async () => {
  const graph = clone();
  // Exactly what `emit/answers.py` writes: an answer cites a place to look, not
  // a range to select, so `locs` is `{file, line}` and nothing else.
  graph.answers = {
    dataEntry: { sentence: 'Data enters at load_data().', nodeIds: [], locs: [{ file: 'data.py', line: 26 }], confidence: 0.9 },
  };
  const ctx = await mount(graph);
  click(ctx, ctx.document.querySelector('[data-answer-loc="data.py:26"]'));
  const opened = ctx.posted.filter((m) => m.type === 'openLocation');
  assert.equal(opened.length, 1);
  assert.equal(opened[0].file, 'data.py');
  assert.equal(opened[0].line, 26);
  assert.equal(opened[0].col, 0, 'the missing column defaults instead of posting undefined');
  assert.equal(opened[0].endLine, 26);
  assert.equal(
    opened[0].absFile,
    sample.workspace.root + '/data.py',
    'and the absolute path is rebuilt from workspace.root, so the deep link still resolves',
  );
  ctx.app.destroy();
});

test('a low-confidence answer is marked rather than asserted (MLV-P1)', async () => {
  const graph = clone();
  graph.answers = ANSWERS;
  const ctx = await mount(graph);
  const verdict = ctx.document.querySelector('[data-answer="verdict"]');
  assert.ok(verdict.querySelector('.mlv-chip--conf'), 'the 0.3-confidence answer carries a chip');
  const evaluation = ctx.document.querySelector('[data-answer="evaluation"]');
  assert.equal(evaluation.querySelector('.mlv-chip--conf'), null, 'a 0.7 answer does not');
  ctx.app.destroy();
});

test('a partial block draws only the answers it carries (MLV-P1)', async () => {
  const graph = clone();
  graph.answers = { objective: ANSWERS.objective, verdict: ANSWERS.verdict };
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-answers]');
  assert.equal(card.hidden, false);
  assert.deepEqual(
    Array.from(card.querySelectorAll('[data-answer]')).map((i) => i.getAttribute('data-answer')),
    ['objective', 'verdict'],
    'in the fixed order, with the missing two simply absent',
  );
  assert.ok(card.textContent.indexOf('2 of 4 answered') >= 0, 'and the header says how many: ' + card.textContent.slice(0, 60));
  ctx.app.destroy();
});

test('the card collapses, and the state is persisted as answersOpen (MLV-P1)', async () => {
  const graph = clone();
  graph.answers = ANSWERS;
  const ctx = await mount(graph);
  assert.equal(ctx.app.getState().answersOpen, undefined, 'absent while open, which is the default');
  const head = ctx.document.querySelector('.mlv-answers__head');
  assert.equal(head.getAttribute('aria-expanded'), 'true');
  click(ctx, head);
  assert.equal(ctx.document.querySelector('.mlv-answers__head').getAttribute('aria-expanded'), 'false');
  assert.equal(ctx.document.querySelector('.mlv-answers__body').hidden, true, 'the body folds away');
  assert.equal(ctx.app.getState().answersOpen, false, 'and the state records it');
  ctx.app.destroy();
});

test('the card costs no tab stop before the canvas (MLV-P1, VIEW-12)', async () => {
  const graph = clone();
  graph.answers = ANSWERS;
  const ctx = await mount(graph);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  const card = ctx.document.querySelector('[data-answers]');
  assert.equal(card.parentElement.tagName, 'MAIN', 'the card lives in the main landmark');
  assert.equal(
    canvas.compareDocumentPosition(card) & 4,
    4,
    'AFTER the canvas in DOM order, lifted above it by order: -1',
  );
  ctx.app.destroy();
});

test('a malformed answers block never takes the report down (invariant 1.1/6)', async () => {
  const graph = clone();
  graph.answers = { dataEntry: { sentence: 42 }, objective: null, nonsense: { sentence: 'x' } };
  const ctx = await mount(graph);
  const card = ctx.document.querySelector('[data-answers]');
  assert.equal(card.hidden, true, 'nothing readable, so nothing is drawn');
  assert.ok(ctx.document.querySelectorAll('.mlv-node').length > 0, 'and the diagram still rendered');
  ctx.app.destroy();
});
