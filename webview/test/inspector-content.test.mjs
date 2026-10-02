// Viewer M1, step 2: what the Inspector shows, checked by VISIBILITY where it matters.
//
// The shipped stylesheet is injected into the jsdom page, so `getComputedStyle` applies the real
// rules: a `display: none` rule hides an element from these checks exactly as it hides it from a
// reader. (Before this, workflow.test.mjs asserted the authored suggestion on textContent, which
// includes text an analyzer-era rule kept hidden.) None of this is a live VS Code check.
//
// Covered: the authored detail as a paragraph after the title and the phase label; no repeated
// title line; basis once, with a sentence only for inferred and unresolved; "What to change"
// visible in the Inspector and the Findings list, and absent when there is no suggestion;
// document-wide limitations listed once, in the header Details, with one line and a Show link in
// the Inspector; the evidence caption; the claim in the card's accessible name; notebook cells
// counted from 0 as the artifact records them; a finding's title once in its Inspector; the connection hover.
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
  assert.ok(visible(ctx, inspector(ctx)), 'precondition: the Inspector is shown');
}

test('a step Inspector shows the authored detail as a paragraph after the title and the phase label, with the kind', async () => {
  const ctx = await mount();
  try {
    clickCard(ctx, 'load');
    const panel = inspector(ctx);
    const children = Array.from(panel.children);
    const title = panel.querySelector('.mlv-insp__title');
    const meta = panel.querySelector('.mlv-insp__meta');
    const detail = panel.querySelector('.mlv-insp__detail');
    assert.equal(title.textContent, 'Load CIFAR-10 batches');
    assert.ok(detail, 'the detail paragraph exists');
    assert.equal(detail.tagName, 'P');
    assert.equal(detail.textContent, LOAD_DETAIL, 'the whole detail, verbatim');
    assert.ok(visible(ctx, detail), 'the detail is visible');
    assert.ok(children.indexOf(title) < children.indexOf(meta) && children.indexOf(meta) < children.indexOf(detail),
      'title, then the phase and kind, then the detail');
    const firstSection = panel.querySelector('h5');
    assert.ok(children.indexOf(detail) < children.indexOf(firstSection), 'the detail comes before every section');
    const chips = Array.from(meta.querySelectorAll('.mlv-chip'), (chip) => chip.textContent);
    assert.equal(chips[0], 'Data preparation', 'the phase label, first');
    assert.ok(chips.includes('dataset'), 'the kind');
    assert.doesNotMatch(panel.textContent, /ph-data-x/, 'never the phase id');
    assert.equal(meta.querySelector('.mlv-chip--stage').getAttribute('data-stage'), 'ph-data-x', 'the id stays on the attribute');

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
    assert.deepEqual(Array.from(panel.querySelectorAll('.mlv-insp__basis-chip'), (c) => c.textContent), ['basis · observed']);
    assert.equal(panel.querySelector('.mlv-insp__basis'), null, 'observed needs no explanation');
    assert.equal(panel.querySelector('table.mlv-table'), null, 'no Attributes table repeating the basis');
    assert.doesNotMatch(panel.textContent, /Attributes/);

    clickCard(ctx, 'opt');
    panel = inspector(ctx);
    assert.equal(panel.querySelectorAll('.mlv-insp__basis-chip').length, 1);
    let note = panel.querySelector('.mlv-insp__basis');
    assert.ok(visible(ctx, note));
    assert.equal(note.getAttribute('data-basis'), 'inferred');
    assert.match(note.textContent, /^Reasoned from the cited code/);
    const children = Array.from(panel.children);
    assert.ok(children.indexOf(note) < children.indexOf(panel.querySelector('.mlv-insp__detail')), 'the sentence sits above the claim');

    clickCard(ctx, 'sched');
    note = inspector(ctx).querySelector('.mlv-insp__basis');
    assert.match(note.textContent, /does not settle this claim\. It does not mean the step is missing\./);

    // A connection: the authored label without the canvas's " · basis" suffix, and the basis once.
    ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' });
    panel = inspector(ctx);
    assert.equal(panel.querySelector('.mlv-insp__title').textContent, 'image batches');
    assert.deepEqual(Array.from(panel.querySelectorAll('.mlv-insp__basis-chip'), (c) => c.textContent), ['basis · inferred']);
    assert.equal((panel.textContent.match(/inferred/g) || []).length, 1,
      'the word appears once, in the chip; the sentence explains without repeating it');
    assert.match(panel.querySelector('.mlv-insp__basis').textContent, /^Reasoned from the cited code/);
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
    const sections = Array.from(panel.querySelectorAll('h5'), (h) => h.textContent);
    assert.ok(sections.indexOf('Findings') < sections.indexOf('Source evidence'), 'findings on this step come before its evidence');
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
    // A step whose two findings have no suggestion.
    clickCard(ctx, 'load');
    assert.doesNotMatch(inspector(ctx).textContent, /What to change|Suggested check/);
  } finally {
    ctx.app.destroy();
  }
});

test('document-wide limitations are listed once, in the header Details; the Inspector links to them', async () => {
  const ctx = await mount();
  try {
    const listed = () => $$(ctx, 'li').filter((li) => li.textContent === 'Distributed launch was not inspected.');
    for (const select of [
      () => clickCard(ctx, 'load'),
      () => ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' }),
      () => { ctx.app.focusIssue('f-sched'); ctx.app.setRailTab('inspector'); },
    ]) {
      select();
      const panel = inspector(ctx);
      assert.equal(listed().length, 1, 'the limitation is listed once in the whole page');
      assert.ok($(ctx, '.mlv-workflow__limitations').contains(listed()[0]), 'and that list is the header Details');
      assert.doesNotMatch(panel.textContent, /Distributed launch was not inspected|Coverage limitations/);
      const line = panel.querySelector('.mlv-insp__limits');
      assert.ok(visible(ctx, line));
      assert.equal(line.textContent, '2 document-wide limitations apply. Show');
      assert.equal(line.getAttribute('data-limitations'), '2');
    }

    // Show opens Details and the list, and moves the focus to it.
    const header = $(ctx, '.mlv-workflow');
    assert.notEqual(header.getAttribute('data-expanded'), 'true', 'precondition: Details starts closed');
    assert.equal($(ctx, '.mlv-workflow__limitations').open, false, 'precondition: the list starts closed');
    const show = inspector(ctx).querySelector('.mlv-insp__limits-show');
    assert.equal(show.getAttribute('aria-label'), 'Show the 2 document-wide limitations');
    show.click();
    assert.equal(header.getAttribute('data-expanded'), 'true');
    assert.equal($(ctx, '.mlv-workflow__details').hidden, false);
    const limits = $(ctx, '.mlv-workflow__limitations');
    assert.equal(limits.open, true);
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
    assert.equal(inspector(ctx).querySelector('.mlv-insp__limits').textContent, '1 document-wide limitation applies. Show');
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
    const heading = Array.from(panel.querySelectorAll('h5')).find((h) => h.textContent === 'Source evidence');
    const caption = heading.nextElementSibling;
    assert.ok(caption.classList.contains('mlv-insp__caption'));
    assert.equal(caption.textContent, CAPTION);
    assert.ok(visible(ctx, caption));
    assert.equal(panel.querySelectorAll('.mlv-insp__caption').length, 1, 'once, although the finding above it also has evidence');

    ctx.app.select({ kind: 'edge', id: 'feeds' }, { tab: 'inspector' });
    assert.equal(inspector(ctx).querySelectorAll('.mlv-insp__caption').length, 1);

    // A finding's own Inspector: under its evidence heading.
    ctx.app.focusIssue('f-sched');
    ctx.app.setRailTab('inspector');
    panel = inspector(ctx);
    const review = Array.from(panel.querySelectorAll('h5')).find((h) => h.textContent === 'Evidence review');
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
    assert.equal(card(ctx, 'crit').querySelector('.mlv-node__loc').textContent, 'train.ipynb › cell 34, line 2');
    assert.match(card(ctx, 'crit').getAttribute('aria-label'), /train\.ipynb cell 34 line 2/);

    clickCard(ctx, 'crit');
    const open = inspector(ctx).querySelector('.mlv-insp__source-evidence [data-evidence-id="nb"]');
    assert.equal(open.textContent, 'Open train.ipynb › cell 34, line 2');
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

test('a finding Inspector shows its title once; a finding listed under a step keeps it', async () => {
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
