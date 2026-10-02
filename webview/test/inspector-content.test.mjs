// Viewer M1, step 2; viewer M2, step 5: what the Selection pane (the Inspector until M2) shows,
// checked by VISIBILITY where it matters.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies the real
// rules: a `display: none` rule hides an element from these checks exactly as it hides it from a
// reader. (Before this, workflow.test.mjs asserted the authored suggestion on textContent, which
// includes text an analyzer-era rule kept hidden.) None of this is a live VS Code check.
//
// Covered: the claim-first order (eyebrow with the phase number and label, kind and parent group;
// title; basis sentence; the authored detail; findings; quotes; connections; actions); no repeated
// title line; basis once, with a sentence only for inferred and unresolved; "What to change"
// visible in the pane and the Findings list, and absent when there is no suggestion;
// document-wide limitations listed once, in About, with one line and a link in the pane; the
// evidence caption; the claim in the card's accessible name; notebook cells counted from 0 as the
// artifact records them; a finding's title once in its pane; the connection hover.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { loadBundle, recordingBridge, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const CAPTION = 'A matching quote shows these lines exist unchanged since publishing. Whether they support the claim is for you to judge.';
const LOAD_DETAIL = 'Builds the training DataLoader with batch size 64 and shuffle on. Each batch is a tuple of images and labels.';
const OPT_DETAIL = 'Adam over all model parameters at lr 3e-5.\nThe scheduler is built but never stepped.';

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Inspector content fixture',
    producer: { kind: 'host-llm', host: 'claude-code' }, revision: { id: 'r1' },
    request: { question: 'How is the model trained?', scope: 'train.py' },
    phases: [{ id: 'ph-data-x', label: 'Data preparation' }, { id: 'ph-opt-x', label: 'Objective and optimizer' }],
    nodes: [
      { id: 'load', label: 'Load CIFAR-10 batches', phase: 'ph-data-x', kind: 'dataset', basis: 'observed', evidence: ['e1'], detail: LOAD_DETAIL },
      { id: 'opt', label: 'Adam optimizer', phase: 'ph-opt-x', kind: 'optimizer', basis: 'inferred', evidence: ['e2'], detail: OPT_DETAIL },
      { id: 'sched', label: 'StepLR scheduler', phase: 'ph-opt-x', kind: 'scheduler', basis: 'unresolved', evidence: [] },
    ],
    edges: [
      { id: 'feeds', source: 'load', target: 'opt', label: 'image batches', kind: 'data', basis: 'inferred', evidence: ['e1'] },
      { id: 'handle', source: 'opt', target: 'sched', label: 'optimizer handle', kind: 'state', basis: 'observed', evidence: ['e2'] },
    ],
    findings: [
      { id: 'f-sched', title: 'Scheduler never stepped', message: 'The learning rate stays constant.', severity: 'medium',
        nodeIds: ['opt'], basis: 'inferred', evidence: ['e2'], suggestion: 'Call scheduler.step() once per epoch.' },
      { id: 'f-none', title: 'Validation is shuffled', message: 'Shuffle is on for validation too.', severity: 'low',
        nodeIds: ['load'], basis: 'observed', evidence: ['e1'] },
      { id: 'f-blank', title: 'Blank suggestion', message: 'A whitespace suggestion.', severity: 'low',
        nodeIds: ['load'], basis: 'observed', evidence: ['e1'], suggestion: '   ' },
    ],
    evidence: [
      { id: 'e1', file: 'train.py', line: 10, endLine: 12, quote: 'loader = DataLoader(ds, batch_size=64, shuffle=True)' },
      { id: 'e2', file: 'train.py', line: 30, endLine: 30, quote: 'opt = Adam(model.parameters(), lr=3e-5)' },
    ],
    coverage: {
      status: 'scoped', summary: 's', inspectedFiles: ['train.py'],
      limitations: ['Distributed launch was not inspected.', 'The config file was not read.'],
    },
    ...overrides,
  };
}

async function mount(document = doc()) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  return { ...ctx, root, bridge, app };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const inspector = (ctx) => $(ctx, '.mlv-rail__panel[id$="-panel-inspector"]');
/** A section heading's words, without the count beside them ("Source evidence", not "Source evidence2 quotes"). */
const headings = (panel) => Array.from(panel.querySelectorAll('h5'), (h) => (h.querySelector('.mlv-rail__headtext') || h).textContent);
const mouse = (ctx, target, type, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"]`);
const wait = (ms) => new Promise((done) => setTimeout(done, ms));

/** Shown to a reader: neither it nor an ancestor is `hidden`, `display: none` or `visibility: hidden`. */
function visible(ctx, element) {
  if (!element) return false;
  for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
    if (node.hidden) return false;
    const style = ctx.window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
  }
  return true;
}

/** Every rule in the shipped stylesheet that hides an element carrying `className`. */
function hidingRules(className) {
  const out = [];
  for (const m of CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = m[1].split(',').map((s) => s.trim());
    if (!selectors.some((s) => new RegExp('\\.' + className + '(?![\\w-])').test(s))) continue;
    if (/(^|;)\s*display\s*:\s*none|(^|;)\s*visibility\s*:\s*hidden/.test(m[2])) out.push(m[0].trim());
  }
  return out;
}

/** Click a card, the reader's own way to select it (viewer M1: a click selects and shows the claim). */
function clickCard(ctx, id) {
  mouse(ctx, card(ctx, id), 'click');
  assert.equal(ctx.app.getState().selection.id, id, 'precondition: the click selected ' + id);
  assert.ok(visible(ctx, inspector(ctx)), 'precondition: the Selection tab is shown');
}

test('a step\'s Selection pane reads eyebrow, title, detail, findings, quotes, connections, actions, limitations', async () => {
  const ctx = await mount();
  try {
    clickCard(ctx, 'load');
    const panel = inspector(ctx);
    const pane = panel.querySelector('.mlv-sel');
    assert.equal(pane.getAttribute('data-kind'), 'step');
    assert.equal(pane.getAttribute('data-columns'), '1', 'one column in the docked rail');
    const children = Array.from(pane.children);
    const eyebrow = pane.querySelector('.mlv-insp__eyebrow');
    const title = pane.querySelector('.mlv-insp__title');
    const detail = pane.querySelector('.mlv-insp__detail');
    const section = (name) => pane.querySelector(`[data-section="${name}"]`);
    assert.equal(title.textContent, 'Load CIFAR-10 batches');
    assert.ok(detail, 'the detail paragraph exists');
    assert.equal(detail.tagName, 'P');
    assert.equal(detail.textContent, LOAD_DETAIL, 'the whole detail, verbatim');
    assert.ok(visible(ctx, detail), 'the detail is visible');
    const order = [eyebrow, title, detail, section('findings'), section('quotes'), section('connections'),
      pane.querySelector('.mlv-insp__actions'), pane.querySelector('.mlv-insp__limits')];
    assert.ok(order.every(Boolean), 'every part is drawn');
    assert.deepEqual(order.map((part) => children.indexOf(part)), order.map((part) => children.indexOf(part)).slice().sort((a, b) => a - b),
      'eyebrow, title, detail, findings, quotes, connections, actions, limitations');
    // The eyebrow: the phase's number and authored label, the kind; never the phase id.
    assert.equal(eyebrow.textContent, '1 · Data preparation · dataset');
    assert.doesNotMatch(panel.textContent, /ph-data-x/, 'never the phase id');
    assert.equal(eyebrow.querySelector('.mlv-insp__phase').getAttribute('data-stage'), 'ph-data-x', 'the id stays on the attribute');
    assert.equal(eyebrow.querySelector('.mlv-insp__phase').getAttribute('data-phase-index'), '0');
    // The connections as sentences, each end a link.
    assert.deepEqual(Array.from(section('connections').querySelectorAll('li'), (li) => li.textContent), ['Feeds Adam optimizer: image batches (inferred, not observed).']);
    assert.equal(section('connections').querySelector('[data-node-id="opt"]').textContent, 'Adam optimizer');
    assert.equal(section('connections').querySelector('[data-edge-id="feeds"]').textContent, 'image batches');
    assert.deepEqual(Array.from(pane.querySelectorAll('.mlv-insp__actions button'), (b) => b.textContent), ['Challenge this claim', 'Refine…']);

    // A multi-line detail keeps its line break.
    clickCard(ctx, 'opt');
    const optDetail = inspector(ctx).querySelector('.mlv-insp__detail');
    assert.equal(optDetail.textContent, OPT_DETAIL);
    assert.equal(ctx.window.getComputedStyle(optDetail).whiteSpace, 'pre-wrap');

    // No detail, no empty paragraph.
    clickCard(ctx, 'sched');
    assert.equal(inspector(ctx).querySelector('.mlv-insp__detail'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('the Inspector no longer repeats the title on a monospace line', async () => {
  const ctx = await mount();
  try {
    clickCard(ctx, 'load');
    const panel = inspector(ctx);
    assert.equal(panel.querySelector('.mlv-insp__fqn'), null, 'no qualname line under an authored title');
    assert.equal((panel.textContent.match(/Load CIFAR-10 batches/g) || []).length, 1, 'the title appears once');
  } finally {
    ctx.app.destroy();
  }
});

test('basis is shown once; inferred and unresolved get one plain sentence, observed none', async () => {
  const ctx = await mount();
  try {
    clickCard(ctx, 'load');
    let panel = inspector(ctx);
    // Viewer M2: observed is the common case and carries no mark at all.
    assert.equal(panel.querySelector('.mlv-insp__basis-chip'), null, 'no basis chip');
    assert.equal(panel.querySelector('.mlv-insp__basis'), null, 'observed needs no explanation');
    for (const part of ['.mlv-insp__eyebrow', '.mlv-insp__title', '.mlv-insp__detail']) {
      assert.doesNotMatch(panel.querySelector(part).textContent, /observed/, part + ' says nothing about an observed basis');
    }
    assert.equal(panel.querySelector('table.mlv-table'), null, 'no Attributes table repeating the basis');
    assert.doesNotMatch(panel.textContent, /Attributes/);

    clickCard(ctx, 'opt');
    panel = inspector(ctx);
    assert.equal(panel.querySelectorAll('.mlv-insp__basis').length, 1);
    let note = panel.querySelector('.mlv-insp__basis');
    assert.ok(visible(ctx, note));
    assert.equal(note.getAttribute('data-basis'), 'inferred');
    // The tag word the card carries, then what it means.
    assert.equal(note.querySelector('.mlv-basis-tag').textContent, 'inferred');
    assert.match(note.textContent, /^inferred Reasoned from the cited code/);
    const children = Array.from(panel.querySelector('.mlv-sel').children);
    assert.ok(children.indexOf(note) < children.indexOf(panel.querySelector('.mlv-insp__detail')), 'the sentence sits above the claim');

    clickCard(ctx, 'sched');
    note = inspector(ctx).querySelector('.mlv-insp__basis');
    assert.match(note.textContent, /does not settle this claim\. It does not mean the step is missing\./);

    // A connection: the authored label without the canvas's " · basis" suffix, and the basis once.
    ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' });
    panel = inspector(ctx);
    assert.equal(panel.querySelector('.mlv-insp__title').textContent, 'image batches');
    assert.equal(panel.querySelector('.mlv-insp__basis-chip'), null);
    assert.equal((panel.textContent.match(/inferred/g) || []).length, 1,
      'the word appears once, in the tag; the sentence explains without repeating it');
    assert.match(panel.querySelector('.mlv-insp__basis').textContent, /^inferred Reasoned from the cited code/);
    // Viewer M2: the kind in words, since the line no longer shows it.
    assert.equal(panel.querySelector('.mlv-insp__eyebrow').textContent, 'Connection · data');
    assert.match(panel.querySelector('.mlv-insp__ends').textContent, /^Load CIFAR-10 batches → Adam optimizer$/);
    ctx.app.select({ kind: 'edge', id: 'handle' }, { tab: 'inspector' });
    assert.equal(inspector(ctx).querySelector('.mlv-insp__title').textContent, 'optimizer handle');
    assert.equal(inspector(ctx).querySelector('.mlv-insp__basis'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('no stylesheet rule hides the authored suggestion or its label', () => {
  for (const name of ['mlv-insp__fix', 'mlv-insp__fix-label', 'mlv-insp__fix-text']) {
    assert.deepEqual(hidingRules(name), [], name + ' is hidden by: ' + hidingRules(name).join(' | '));
  }
});

test('a suggestion is visible as "What to change" in the Inspector and in the Findings list', async () => {
  const ctx = await mount();
  try {
    // The step's Inspector lists its finding with the suggestion, before the step's evidence.
    clickCard(ctx, 'opt');
    let panel = inspector(ctx);
    const box = panel.querySelector('.mlv-insp__issue[data-issue-id="f-sched"]');
    const block = box.querySelector('.mlv-insp__fix');
    assert.ok(visible(ctx, block), 'the suggestion block is visible in the Inspector');
    assert.equal(block.querySelector('.mlv-insp__fix-label').textContent, 'What to change');
    assert.ok(visible(ctx, block.querySelector('.mlv-insp__fix-label')));
    const text = block.querySelector('.mlv-insp__fix-text');
    assert.equal(text.textContent, 'Call scheduler.step() once per epoch.');
    assert.ok(visible(ctx, text), 'the suggestion text is visible in the Inspector');
    const sections = headings(panel);
    assert.ok(sections.indexOf('Findings on this step') >= 0, sections.join(' | '));
    assert.ok(sections.indexOf('Findings on this step') < sections.indexOf('Source evidence'), 'findings on this step come before its evidence');
    // Every count names its unit.
    assert.equal(panel.querySelector('[data-section="findings"] .mlv-rail__count').textContent, '1 finding');
    assert.equal(sections.includes('Suggested check'), false);

    // The finding's own Inspector.
    ctx.app.focusIssue('f-sched');
    ctx.app.setRailTab('inspector');
    panel = inspector(ctx);
    assert.ok(visible(ctx, panel.querySelector('.mlv-insp__fix-text')));

    // The expanded row in the Findings list.
    ctx.app.setRailTab('issues');
    const detail = $(ctx, '[data-issue-detail="f-sched"]');
    assert.ok(detail, 'the selected row is expanded');
    const rowText = detail.querySelector('.mlv-insp__fix-text');
    assert.equal(rowText.textContent, 'Call scheduler.step() once per epoch.');
    assert.ok(visible(ctx, rowText), 'the suggestion text is visible in the Findings list');
    assert.ok(visible(ctx, detail.querySelector('.mlv-insp__fix-label')));
    assert.equal(detail.querySelector('.mlv-insp__fix-label').textContent, 'What to change');
  } finally {
    ctx.app.destroy();
  }
});

test('a finding without a suggestion shows no "What to change" label and no empty heading', async () => {
  const ctx = await mount();
  try {
    for (const id of ['f-none', 'f-blank']) {
      ctx.app.focusIssue(id);
      ctx.app.setRailTab('inspector');
      const panel = inspector(ctx);
      assert.equal(panel.querySelector('.mlv-insp__fix'), null, id + ': no suggestion block');
      assert.doesNotMatch(panel.textContent, /What to change|Suggested check/, id + ': no label over nothing');
      ctx.app.setRailTab('issues');
      const detail = $(ctx, `[data-issue-detail="${id}"]`);
      assert.ok(detail);
      assert.equal(detail.querySelector('.mlv-insp__fix'), null, id + ': no suggestion block in the list');
    }
    // A step whose two findings have no suggestion. (From the Findings tab a click keeps the list;
    // the reader goes back to Selection first.)
    ctx.app.setRailTab('inspector');
    clickCard(ctx, 'load');
    assert.doesNotMatch(inspector(ctx).textContent, /What to change|Suggested check/);
  } finally {
    ctx.app.destroy();
  }
});

test('document-wide limitations are listed once, in About; the Selection pane links to them', async () => {
  const ctx = await mount();
  try {
    const listed = () => $$(ctx, 'li').filter((li) => li.textContent === 'Distributed launch was not inspected.');
    // A new revision opens on About, where they are listed once.
    assert.equal(listed().length, 1, 'About lists the limitation once');
    assert.ok($(ctx, '.mlv-about__limitations').contains(listed()[0]));
    for (const select of [
      () => clickCard(ctx, 'load'),
      () => ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' }),
      () => { ctx.app.focusIssue('f-sched'); ctx.app.setRailTab('inspector'); },
    ]) {
      select();
      const panel = inspector(ctx);
      assert.equal(listed().length, 0, 'the Selection pane does not repeat them');
      assert.doesNotMatch(panel.textContent, /Distributed launch was not inspected|Coverage limitations/);
      const line = panel.querySelector('.mlv-insp__limits');
      assert.ok(visible(ctx, line));
      assert.equal(line.textContent, '2 document-wide limitations apply to every claim. Read them in About');
      assert.equal(line.getAttribute('data-limitations'), '2');
    }

    // The link opens About at the list and moves the focus to it.
    const show = inspector(ctx).querySelector('.mlv-insp__limits-show');
    assert.equal(show.getAttribute('aria-label'), 'Read the 2 document-wide limitations in About');
    show.click();
    assert.equal(ctx.app.getState().railTab, 'about');
    const limits = $(ctx, '.mlv-about__limitations');
    assert.equal(limits.open, true);
    assert.equal(listed().length, 1, 'listed once in the whole page');
    assert.ok(visible(ctx, listed()[0]), 'the limitation is now visible');
    assert.equal(ctx.document.activeElement, limits.querySelector('summary'), 'focus lands on the list');
  } finally {
    ctx.app.destroy();
  }
});

test('one limitation reads in the singular, and none draws no line', async () => {
  let ctx = await mount(doc({ coverage: { status: 'partial', summary: 's', inspectedFiles: ['train.py'], limitations: ['Only one.'] } }));
  try {
    clickCard(ctx, 'load');
    assert.equal(inspector(ctx).querySelector('.mlv-insp__limits').textContent, '1 document-wide limitation applies to every claim. Read it in About');
  } finally {
    ctx.app.destroy();
  }
  ctx = await mount(doc({ coverage: { status: 'scoped', summary: 's', inspectedFiles: ['train.py'], limitations: [] } }));
  try {
    clickCard(ctx, 'load');
    assert.equal(inspector(ctx).querySelector('.mlv-insp__limits'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('the evidence heading carries the caption, once per Inspector', async () => {
  const ctx = await mount();
  try {
    clickCard(ctx, 'opt');
    let panel = inspector(ctx);
    const heading = Array.from(panel.querySelectorAll('h5')).find((h) => headings({ querySelectorAll: () => [h] })[0] === 'Source evidence');
    assert.equal(heading.querySelector('.mlv-rail__count').textContent, '1 quote');
    const caption = heading.nextElementSibling;
    assert.ok(caption.classList.contains('mlv-insp__caption'));
    assert.equal(caption.textContent, CAPTION);
    assert.ok(visible(ctx, caption));
    assert.equal(panel.querySelectorAll('.mlv-insp__caption').length, 1, 'once, although the finding above it also has evidence');

    ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' });
    assert.equal(inspector(ctx).querySelectorAll('.mlv-insp__caption').length, 1);

    // A finding's own pane: under its evidence heading.
    ctx.app.focusIssue('f-sched');
    ctx.app.setRailTab('inspector');
    panel = inspector(ctx);
    const review = panel.querySelector('[data-section="quotes"] h5');
    assert.equal(review.querySelector('.mlv-rail__headtext').textContent, 'Source evidence');
    assert.equal(review.nextElementSibling.textContent, CAPTION);
    assert.equal(panel.querySelectorAll('.mlv-insp__caption').length, 1);

    // No evidence, no caption.
    clickCard(ctx, 'sched');
    assert.equal(inspector(ctx).querySelectorAll('.mlv-insp__caption').length, 0);
  } finally {
    ctx.app.destroy();
  }
});

test('a card\'s accessible name carries the phase label and the claim\'s first sentence, and a click announces it', async () => {
  const long = 'Wraps the model in DistributedDataParallel across every visible device and then keeps going without any sentence break at all so that the spoken form has to be cut somewhere sensible';
  const nodes = doc().nodes.map((node) => (node.id === 'sched' ? { ...node, detail: long } : node));
  const ctx = await mount(doc({ nodes }));
  try {
    const name = card(ctx, 'load').getAttribute('aria-label');
    assert.match(name, /Load CIFAR-10 batches/);
    assert.match(name, /Data preparation phase/);
    assert.doesNotMatch(name, /ph-data-x/, 'not the phase id');
    assert.ok(name.endsWith('. Builds the training DataLoader with batch size 64 and shuffle on.'), name);
    assert.doesNotMatch(name, /Each batch is a tuple/, 'the first sentence only');

    const opt = card(ctx, 'opt').getAttribute('aria-label');
    assert.ok(opt.endsWith(' Adam over all model parameters at lr 3e-5.'), opt);

    const cut = card(ctx, 'sched').getAttribute('aria-label');
    const claim = cut.slice(cut.indexOf('. ') + 2);
    assert.ok(claim.startsWith('Wraps the model in DistributedDataParallel'), cut);
    assert.ok(claim.endsWith('…'), 'a long claim with no sentence break is cut and marked');
    assert.ok(claim.length <= 161, 'at most 160 characters plus the ellipsis: ' + claim.length);
    assert.ok(long.startsWith(claim.slice(0, -1)), 'cut at a word, not mid-word');

    mouse(ctx, card(ctx, 'load'), 'click');
    assert.match(ctx.app.liveEl.textContent, /^Selected .*Builds the training DataLoader with batch size 64 and shuffle on\.$/);
  } finally {
    ctx.app.destroy();
  }
});

test('an abbreviation such as "i.e." or "e.g." does not end the spoken claim (M1-R4)', async () => {
  const ie = 'Applies RandomHorizontalFlip, ToTensor and Normalize per channel, i.e. pixel values end up in [-1, 1]. Labels are left as they are.';
  const eg = 'Builds the loaders (e.g. train and val) from the config, etc. Each loader shuffles.';
  const runOn = 'Logs the loss, i.e. the mean over the batch, and keeps going with more words so that no real sentence end falls inside the first one hundred and sixty characters of it';
  const details = { load: ie, opt: eg, sched: runOn };
  const nodes = doc().nodes.map((node) => (details[node.id] ? { ...node, detail: details[node.id] } : node));
  const ctx = await mount(doc({ nodes }));
  try {
    const claimOf = (id) => {
      const name = card(ctx, id).getAttribute('aria-label');
      return name.slice(name.indexOf('. ') + 2);
    };
    assert.equal(claimOf('load'), 'Applies RandomHorizontalFlip, ToTensor and Normalize per channel, i.e. pixel values end up in [-1, 1].');
    assert.equal(claimOf('opt'), 'Builds the loaders (e.g. train and val) from the config, etc. Each loader shuffles.');
    const cut = claimOf('sched');
    assert.ok(cut.endsWith('…'), 'no real sentence end within 160 characters: cut at a word and marked, not stopped at "i.e.": ' + cut);
    assert.ok(cut.length > 'Logs the loss, i.e.'.length + 10, cut);
  } finally {
    ctx.app.destroy();
  }
});

test('notebook cells are counted from 0 everywhere, as the evidence records them and the model labels them', async () => {
  const notebook = doc({
    nodes: [
      { id: 'crit', label: 'criterion = nn.CrossEntropyLoss() (cell 34)', phase: 'ph-opt-x', basis: 'observed', evidence: ['nb'], detail: 'Cross-entropy loss.' },
      { id: 'opt', label: 'Adam optimizer', phase: 'ph-opt-x', basis: 'observed', evidence: ['e2'] },
    ],
    edges: [{ id: 'c-o', source: 'crit', target: 'opt', label: 'loss', basis: 'observed', evidence: ['nb'] }],
    findings: [{ id: 'f-nb', title: 'Loss on logits', message: 'm', severity: 'low', nodeIds: ['crit'], basis: 'observed', evidence: ['nb'] }],
    evidence: [
      { id: 'nb', file: 'train.ipynb', cell: 34, line: 2, endLine: 2, quote: 'criterion = nn.CrossEntropyLoss()' },
      { id: 'e2', file: 'train.py', line: 30, endLine: 30, quote: 'opt = Adam(model.parameters(), lr=3e-5)' },
    ],
  });
  const ctx = await mount(notebook);
  try {
    assert.equal(card(ctx, 'crit').querySelector('.mlv-node__title').textContent.includes('(cell 34)'), true, 'the author\'s label is untouched');
    // Viewer M2 review (A11Y-6): a card with a detail draws two lines of it where the file:line row
    // was; the place stays in its name and the Selection pane, counted from 0. One without a
    // detail keeps the row.
    assert.equal(card(ctx, 'crit').querySelector('.mlv-node__loc'), null);
    assert.equal(card(ctx, 'crit').querySelector('.mlv-node__sub').getAttribute('data-lines'), '2');
    assert.equal(card(ctx, 'opt').querySelector('.mlv-node__loc').textContent, 'train.py:30');
    assert.match(card(ctx, 'crit').getAttribute('aria-label'), /train\.ipynb cell 34 line 2/);

    clickCard(ctx, 'crit');
    const open = inspector(ctx).querySelector('.mlv-insp__source-evidence [data-evidence-id="nb"]');
    // Viewer M2: the quote names its place; its button says Open and its name says what.
    assert.equal(open.textContent, 'Open');
    assert.equal(open.getAttribute('aria-label'), 'Open train.ipynb › cell 34, line 2');
    assert.equal(open.closest('.mlv-quote').querySelector('.mlv-quote__loc').textContent, 'train.ipynb › cell 34, line 2');
    assert.match(open.title, /^cell 34, counted from 0 as the artifact records it/);
    open.click();
    const posted = ctx.bridge.posted.filter((m) => m.type === 'openLocation').at(-1);
    assert.equal(posted.cell, 34, 'the wire still carries the recorded index');
    assert.equal(posted.line, 2);

    ctx.app.focusIssue('f-nb');
    ctx.app.setRailTab('issues');
    const goTo = Array.from(ctx.document.querySelectorAll('[data-issue-detail="f-nb"] .mlv-btn'), (b) => b.textContent);
    assert.ok(goTo.some((t) => t === 'Go to train.ipynb › cell 34, line 2'), goTo.join(' | '));
    assert.doesNotMatch(ctx.root.textContent, /cell 35/, 'never the index plus one');
  } finally {
    ctx.app.destroy();
  }
});

test('a finding\'s pane shows its title once; a finding listed under a step keeps it', async () => {
  const ctx = await mount();
  try {
    ctx.app.focusIssue('f-sched');
    ctx.app.setRailTab('inspector');
    const panel = inspector(ctx);
    assert.equal(panel.querySelector('.mlv-insp__title').textContent, 'Scheduler never stepped');
    assert.equal((panel.textContent.match(/Scheduler never stepped/g) || []).length, 1, 'viewer M2: the title appears once');
    assert.equal(panel.querySelector('.mlv-insp__issue-title'), null);
    assert.equal(panel.querySelector('.mlv-insp__issue-head .mlv-mono').textContent, 'f-sched', 'the id stays beside the label');
    // Under a step, the finding's head row is the only place its title is printed.
    clickCard(ctx, 'opt');
    const listed = inspector(ctx).querySelector('.mlv-insp__issue[data-issue-id="f-sched"] .mlv-insp__issue-title');
    assert.equal(listed.textContent, 'Scheduler never stepped');
    // Viewer M2 removed the phase chip row and its tooltip; nothing filters by phase.
    assert.equal($(ctx, '[data-stage-filter]'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('a connection\'s hover card names it as authored and states the basis once', async () => {
  const ctx = await mount();
  try {
    const hit = $(ctx, '.mlv-edge[data-edge-id="feeds"] .mlv-edge__hit');
    hit.dispatchEvent(new ctx.window.Event('pointerenter', { bubbles: false }));
    await wait(450);
    const tooltip = $(ctx, '.mlv-tooltip');
    assert.equal(tooltip.hidden, false);
    assert.equal(tooltip.querySelector('.mlv-tooltip__title').textContent, 'image batches');
    assert.equal((tooltip.textContent.match(/inferred/g) || []).length, 1, tooltip.textContent);
  } finally {
    ctx.app.destroy();
  }
});
