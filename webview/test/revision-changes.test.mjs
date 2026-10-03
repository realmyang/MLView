// Viewer M4, roadmap step 16: changes since the previous revision.
//
// `revisionDiff` and the frame's comparison check (`src/revisiondiff.ts`) are pure, so their cases
// run against the source compiled here with the esbuild the build already uses. The viewer cases
// run on the built bundle in jsdom with the shipped stylesheet; the host is the test's recording
// bridge, and the comparison arrives as the host sends it, as the `workflow` frame's `previous`
// (or `replaced`). The documents are SYNTHETIC and small, plus the generated vit-cc shape
// (helpers.mjs) for the geometry check. None of this is a live VS Code check, a screen-reader or
// usability check, or a semantic review.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { build } from 'esbuild';
import { loadBundle, recordingBridge, routedGeometry, shapedWorkflow, VIT_SHAPE, WEBVIEW_ROOT } from './helpers.mjs';

const CSS = await readFile(join(WEBVIEW_ROOT, 'dist', 'mlview.css'), 'utf8');
const plain = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const eq = (actual, expected, message) => assert.deepEqual(plain(actual), plain(expected), message);
const clone = (value) => JSON.parse(JSON.stringify(value));
/** The words the comparison must never use (synthesis step 16; the owner's first complaint was overclaiming). */
const JUDGING = /\b(fix|fixed|fixes|wrong|better|worse|improv\w*|regress\w*|correct\w*)\b/i;

let sourcePromise = null;
function source() {
  if (!sourcePromise) {
    sourcePromise = build({
      stdin: {
        contents: "export * from './revisiondiff.ts';",
        resolveDir: join(WEBVIEW_ROOT, 'src'),
        loader: 'ts',
        sourcefile: 'revision-changes-entry.ts',
      },
      bundle: true,
      format: 'esm',
      platform: 'neutral',
      write: false,
      logLevel: 'silent',
    }).then((result) => import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64')));
  }
  return sourcePromise;
}

/* ── synthetic documents ─────────────────────────────────────────────── */

const ev = (id, file, line, quote, extra = {}) => ({ id, file, line, endLine: line, quote, ...extra });

/** Revision r1: two phases, a group with two steps, a step and a finding that r2 removes. */
function doc1() {
  return {
    workflowVersion: '1.0', title: 'Changes fixture', producer: { kind: 'host-llm', host: 'codex', model: 'm' }, revision: { id: 'r1' },
    request: { question: 'How does training run?', scope: 'train.py' },
    phases: [{ id: 'data', label: 'Data' }, { id: 'fit', label: 'Fit' }],
    nodes: [
      { id: 'load', label: 'Load batches', phase: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'aug', label: 'Augment', phase: 'data', basis: 'observed', evidence: ['e2'] },
      { id: 'loop', label: 'Epoch loop', phase: 'fit', kind: 'group', basis: 'observed', evidence: [] },
      { id: 'step', label: 'Optimizer step', phase: 'fit', parent: 'loop', detail: 'Adam over all parameters.', basis: 'inferred', evidence: ['e3'] },
      { id: 'zero', label: 'Zero grads', phase: 'fit', parent: 'loop', basis: 'observed', evidence: ['e4'] },
      { id: 'old', label: 'Old logging', phase: 'fit', basis: 'observed', evidence: ['e4'] },
    ],
    edges: [
      { id: 'c-load-aug', source: 'load', target: 'aug', label: 'images', kind: 'data', basis: 'observed', evidence: ['e1'] },
      { id: 'c-aug-step', source: 'aug', target: 'step', label: 'batches', kind: 'data', basis: 'inferred', evidence: ['e2', 'e3'] },
      { id: 'c-step-zero', source: 'step', target: 'zero', label: 'then', kind: 'control', basis: 'observed', evidence: ['e4'] },
      { id: 'c-old', source: 'zero', target: 'old', label: 'logs', basis: 'observed', evidence: ['e4'] },
    ],
    findings: [
      { id: 'f-clip', title: 'Clip missing', message: 'No gradient clipping.', severity: 'medium', nodeIds: ['step'], edgeIds: [], basis: 'observed', evidence: ['e3'], suggestion: 'Clip at 1.0.' },
      { id: 'f-old', title: 'Old risk', message: 'Logs every step.', severity: 'low', nodeIds: ['old'], edgeIds: ['c-old'], basis: 'observed', evidence: ['e4'] },
    ],
    evidence: [
      ev('e1', 'data.py', 3, 'loader = DataLoader(ds)'),
      ev('e2', 'data.py', 9, 'aug = RandomCrop(32)'),
      ev('e3', 'train.py', 4, 'opt.step()'),
      ev('e4', 'train.py', 5, 'opt.zero_grad()'),
    ],
    coverage: { status: 'scoped', summary: 'Data and fit read.', inspectedFiles: ['data.py', 'train.py'], limitations: [] },
  };
}

/**
 * Revision r2 (parent r1): one step relabelled, one quote changed under the same id (so a step and
 * a connection citing it changed their evidence), a step, a connection and a finding added, one of
 * each removed, and a finding's severity changed.
 */
function doc2() {
  const d = doc1();
  d.revision = { id: 'r2', parent: 'r1' };
  d.nodes.find((n) => n.id === 'step').label = 'Optimizer step (AdamW)';
  d.evidence.find((e) => e.id === 'e2').quote = 'aug = RandomCrop(28)';
  d.nodes = d.nodes.filter((n) => n.id !== 'old');
  d.nodes.push({ id: 'save', label: 'Save weights', phase: 'fit', basis: 'observed', evidence: ['e5'] });
  d.edges = d.edges.filter((e) => e.id !== 'c-old');
  d.edges.push({ id: 'c-zero-save', source: 'zero', target: 'save', label: 'weights', basis: 'observed', evidence: ['e5'] });
  d.findings = d.findings.filter((f) => f.id !== 'f-old');
  d.findings.find((f) => f.id === 'f-clip').severity = 'high';
  d.findings.push({ id: 'f-seed', title: 'No seed', message: 'No seed is set.', severity: 'low', nodeIds: ['load'], edgeIds: [], basis: 'observed', evidence: ['e1'] });
  d.evidence.push(ev('e5', 'train.py', 9, 'torch.save(model)'));
  return d;
}

const ids = (items) => items.map((item) => item.id);
const fieldsOf = (group, id) => group.changed.find((item) => item.id === id)?.fields;

/* ── revisionDiff, pure ──────────────────────────────────────────────── */

test('revisionDiff classifies by id: added, removed and changed steps, connections and findings, with the fields that changed', async () => {
  const m = await source();
  const diff = m.revisionDiff(doc1(), doc2());
  assert.equal(diff.since, 'r1');
  assert.equal(diff.revision, 'r2');
  eq(ids(diff.steps.added), ['save']);
  eq(ids(diff.steps.removed), ['old']);
  eq(ids(diff.steps.changed), ['aug', 'step'], 'changed steps in the new revision\'s document order');
  eq(fieldsOf(diff.steps, 'aug'), ['evidence'], 'a quote changed under the same evidence id is a change');
  eq(fieldsOf(diff.steps, 'step'), ['label']);
  eq(ids(diff.connections.added), ['c-zero-save']);
  eq(ids(diff.connections.removed), ['c-old']);
  eq(ids(diff.connections.changed), ['c-aug-step']);
  eq(fieldsOf(diff.connections, 'c-aug-step'), ['evidence']);
  eq(ids(diff.findings.added), ['f-seed']);
  eq(ids(diff.findings.removed), ['f-old']);
  eq(ids(diff.findings.changed), ['f-clip']);
  eq(fieldsOf(diff.findings, 'f-clip'), ['severity']);
  // Titles: the new revision's for added and changed items, the old one's for removed items.
  assert.equal(diff.steps.removed[0].title, 'Old logging');
  assert.equal(diff.connections.removed[0].title, 'logs · Zero grads → Old logging');
  assert.equal(diff.connections.added[0].title, 'weights · Zero grads → Save weights');
  assert.equal(diff.steps.changed[1].title, 'Optimizer step (AdamW)');
  // The marks hold every added and changed item, never a removed one.
  eq(Array.from(diff.marks.keys()).sort(), ['edge:c-aug-step', 'edge:c-zero-save', 'issue:f-clip', 'issue:f-seed', 'node:aug', 'node:save', 'node:step']);
  assert.equal(m.changeOf(diff, 'node', 'old'), undefined);
  assert.equal(m.changeOf(diff, 'node', 'step').status, 'changed');
  assert.equal(m.changeOf(null, 'node', 'step'), undefined);
  assert.equal(m.changeTotal(diff), 10);
  assert.equal(m.markedTotal(diff), 7);
});

test('revisionDiff names every compared field of a step, a connection and a finding', async () => {
  const m = await source();
  const steps = [
    ['label', (d) => { d.nodes[0].label = 'Read batches'; }],
    ['detail', (d) => { d.nodes[3].detail = 'AdamW over all parameters.'; }],
    ['basis', (d) => { d.nodes[0].basis = 'inferred'; }],
    ['phase', (d) => { d.nodes[5].phase = 'data'; }],
    ['group', (d) => { d.nodes[5].parent = 'loop'; }],
    ['kind', (d) => { d.nodes[0].kind = 'data'; }],
    ['evidence', (d) => { d.nodes[0].evidence = ['e2']; }],
  ];
  for (const [field, change] of steps) {
    const next = doc1();
    change(next);
    const diff = m.revisionDiff(doc1(), next);
    assert.equal(diff.steps.changed.length, 1, field);
    eq(diff.steps.changed[0].fields, [field], 'step ' + field);
  }
  const connections = [
    ['from', (d) => { d.edges[0].source = 'zero'; }],
    ['to', (d) => { d.edges[0].target = 'zero'; }],
    ['label', (d) => { d.edges[0].label = 'pixels'; }],
    ['kind', (d) => { d.edges[0].kind = 'call'; }],
    ['basis', (d) => { d.edges[0].basis = 'unresolved'; }],
    ['evidence', (d) => { d.edges[0].evidence = ['e1', 'e2']; }],
  ];
  for (const [field, change] of connections) {
    const next = doc1();
    change(next);
    const diff = m.revisionDiff(doc1(), next);
    assert.equal(diff.connections.changed.length, 1, field);
    eq(diff.connections.changed[0].fields, [field], 'connection ' + field);
  }
  const findings = [
    ['title', (d) => { d.findings[0].title = 'No clipping'; }],
    ['description', (d) => { d.findings[0].message = 'Gradients are not clipped.'; }],
    ['severity', (d) => { d.findings[0].severity = 'low'; }],
    ['basis', (d) => { d.findings[0].basis = 'inferred'; }],
    ['what to change', (d) => { d.findings[0].suggestion = 'Clip at 0.5.'; }],
    ['cited steps', (d) => { d.findings[0].nodeIds = ['step', 'zero']; }],
    ['cited connections', (d) => { d.findings[0].edgeIds = ['c-step-zero']; }],
    ['evidence', (d) => { d.findings[0].evidence = ['e4']; }],
    ['counter-evidence', (d) => { d.findings[0].counterEvidence = ['e4']; }],
  ];
  for (const [field, change] of findings) {
    const next = doc1();
    change(next);
    const diff = m.revisionDiff(doc1(), next);
    assert.equal(diff.findings.changed.length, 1, field);
    eq(diff.findings.changed[0].fields, [field], 'finding ' + field);
  }
  // Several at once come in the fixed order.
  const next = doc1();
  Object.assign(next.nodes[3], { label: 'Step', detail: 'New detail', basis: 'observed' });
  eq(m.revisionDiff(doc1(), next).steps.changed[0].fields, ['label', 'detail', 'basis']);
});

test('revisionDiff compares evidence by what it cites: a changed quote, lines, file or cell is a change; a renamed evidence id is not', async () => {
  const m = await source();
  for (const [what, change] of [
    ['quote', (e) => { e.quote = 'opt.step()  # adamw'; }],
    ['lines', (e) => { e.endLine = 6; }],
    ['file', (e) => { e.file = 'fit.py'; }],
    ['cell', (e) => { e.cell = 3; }],
  ]) {
    const next = doc1();
    change(next.evidence.find((e) => e.id === 'e3'));
    const diff = m.revisionDiff(doc1(), next);
    eq(ids(diff.steps.changed), ['step'], what);
    eq(ids(diff.connections.changed), ['c-aug-step'], what);
    eq(ids(diff.findings.changed), ['f-clip'], what);
    eq(fieldsOf(diff.findings, 'f-clip'), ['evidence'], what);
  }
  // The same file, lines and quote under another evidence id: nothing changed.
  const renamed = doc1();
  renamed.evidence.find((e) => e.id === 'e3').id = 'e3-renamed';
  for (const item of [...renamed.nodes, ...renamed.edges, ...renamed.findings]) item.evidence = item.evidence.map((id) => (id === 'e3' ? 'e3-renamed' : id));
  assert.equal(m.changeTotal(m.revisionDiff(doc1(), renamed)), 0);
});

test('revisionDiff: reorderings are not changes (document lists, evidence ids, cited ids, phases, evidence records); surrounding whitespace is not either', async () => {
  const m = await source();
  const next = doc1();
  next.nodes.reverse();
  next.edges.reverse();
  next.findings.reverse();
  next.evidence.reverse();
  next.phases.reverse();
  next.edges.find((e) => e.id === 'c-aug-step').evidence.reverse();
  next.findings.find((f) => f.id === 'f-old').edgeIds = ['c-old'];
  next.findings.find((f) => f.id === 'f-old').nodeIds = ['old'];
  next.nodes.find((n) => n.id === 'load').label = '  Load batches ';
  const diff = m.revisionDiff(doc1(), next);
  assert.equal(m.changeTotal(diff), 0, JSON.stringify(plain({ s: diff.steps, c: diff.connections, f: diff.findings })));
  // Cited steps as a set: a reordered list is the same set.
  const two = doc1();
  two.findings[0].nodeIds = ['step', 'zero'];
  const swapped = clone(two);
  swapped.findings[0].nodeIds = ['zero', 'step'];
  assert.equal(m.changeTotal(m.revisionDiff(two, swapped)), 0);
});

test('revisionDiff: a step\'s phase is its label as the reader sees it; a renamed id is one removed and one added', async () => {
  const m = await source();
  const relabelled = doc1();
  relabelled.phases[1].label = 'Training';
  const diff = m.revisionDiff(doc1(), relabelled);
  eq(ids(diff.steps.changed), ['loop', 'step', 'zero', 'old']);
  for (const item of diff.steps.changed) eq(item.fields, ['phase']);
  // The phase id renamed, the label kept: nothing the reader sees changed.
  const renamedPhase = doc1();
  renamedPhase.phases[1].id = 'train';
  for (const node of renamedPhase.nodes) if (node.phase === 'fit') node.phase = 'train';
  assert.equal(m.changeTotal(m.revisionDiff(doc1(), renamedPhase)), 0);
  // A step id renamed: removed plus added, and the connections that name it changed their ends.
  const renamed = doc1();
  renamed.nodes.find((n) => n.id === 'aug').id = 'augment';
  for (const edge of renamed.edges) {
    if (edge.source === 'aug') edge.source = 'augment';
    if (edge.target === 'aug') edge.target = 'augment';
  }
  const d = m.revisionDiff(doc1(), renamed);
  eq(ids(d.steps.removed), ['aug']);
  eq(ids(d.steps.added), ['augment']);
  eq(d.connections.changed.map((c) => [c.id, c.fields]), [['c-load-aug', ['to']], ['c-aug-step', ['from']]]);
});

test('revisionDiff reads a malformed frame without throwing, and the comparison check keeps only what fits the document', async () => {
  const m = await source();
  const broken = { workflowVersion: '1.0', revision: { id: 'r0' }, nodes: 'x', edges: [null, 3, { id: 'e' }], findings: [{ id: 'f', nodeIds: 'x' }] };
  const diff = m.revisionDiff(broken, doc1());
  assert.equal(diff.steps.added.length, 6);
  assert.equal(diff.connections.removed.length, 1);
  const next = doc2();
  eq(Object.keys(m.sanitizeComparison(next, { previous: doc1() })), ['previous']);
  eq(m.sanitizeComparison(next, { previous: { ...doc1(), revision: { id: 'r0' } } }), {}, 'a previous that is not the parent is ignored');
  eq(m.sanitizeComparison(next, { previous: { ...doc1(), workflowVersion: '2.0' } }), {}, 'not a 1.0 document');
  eq(m.sanitizeComparison(doc1(), { previous: doc1() }), {}, 'a document with no parent compares with nothing');
  eq(m.sanitizeComparison(next, { replaced: 'r7' }), { replaced: 'r7' });
  eq(m.sanitizeComparison(next, { replaced: 'r2' }), {}, 'never the displayed id');
  eq(m.sanitizeComparison(next, { replaced: 'r1' }), {}, 'never the parent (that would be a comparison)');
  eq(m.sanitizeComparison(next, { replaced: 7 }), {});
  eq(m.sanitizeComparison(next, { replaced: 'x'.repeat(201) }), {});
  eq(m.sanitizeComparison(next, null), {});
  eq(m.sanitizeComparison(null, { previous: doc1() }), {});
});

test('the words: "new" and "changed", the fields listed, never a judgement', async () => {
  const m = await source();
  assert.equal(m.fieldList([]), '');
  assert.equal(m.fieldList(['label']), 'label');
  assert.equal(m.fieldList(['label', 'evidence']), 'label and evidence');
  assert.equal(m.fieldList(['label', 'detail', 'evidence']), 'label, detail and evidence');
  assert.equal(m.changeTagText({ status: 'added' }), 'new');
  assert.equal(m.changeTagText({ status: 'changed' }), 'changed');
  assert.equal(m.changeSpoken({ status: 'added', fields: [] }), 'new in this revision');
  assert.equal(m.changeSpoken({ status: 'changed', fields: ['label', 'evidence'] }), 'changed in this revision: label and evidence');
  assert.equal(m.changeSentence({ status: 'added', fields: [] }, 'r1'), 'New since revision r1.');
  assert.equal(m.changeSentence({ status: 'changed', fields: ['severity'] }, 'r1'), 'Changed since revision r1: severity.');
  for (const text of [m.changeSpoken({ status: 'changed', fields: ['label'] }), m.changeSentence({ status: 'added', fields: [] }, 'r1')]) assert.doesNotMatch(text, JUDGING);
});

/* ── the viewer ──────────────────────────────────────────────────────── */

async function mount(document, opts = {}) {
  const ctx = await loadBundle();
  const style = ctx.document.createElement('style');
  style.textContent = CSS;
  ctx.document.head.appendChild(style);
  const root = ctx.document.getElementById('mlview-root');
  const width = opts.width || 1440;
  root.getBoundingClientRect = () => ({ x: 0, y: 0, top: 0, left: 0, width, height: 900, right: width, bottom: 900 });
  const bridge = recordingBridge(ctx.window, 'vscode', opts.state ? { state: opts.state } : {});
  const app = ctx.MLView.mountWorkflow(root, document, bridge, opts.comparison);
  const canvas = ctx.document.querySelector('.mlv-canvas');
  return { ...ctx, root, bridge, app, canvas };
}

const $ = (ctx, selector) => ctx.document.querySelector(selector);
const $$ = (ctx, selector) => Array.from(ctx.document.querySelectorAll(selector));
const tab = (ctx, id) => $(ctx, `.mlv-rail__tab[data-tab="${id}"]`).click();
const live = (ctx) => $(ctx, '.mlv-root > [aria-live]').textContent;

/** r1 mounted, then r2 sent by the host with r1 as `previous`, as the extension posts it. */
async function mountChanged(opts = {}) {
  const ctx = await mount(doc1(), opts);
  ctx.bridge.send({ v: 1, type: 'workflow', document: doc2(), previous: doc1() });
  return ctx;
}

test('About: a new revision that follows the one this panel showed opens on "Changes since r1", with counts per group, links to what was added or changed and the removed items as text', async () => {
  const ctx = await mountChanged();
  assert.equal(ctx.app.getState().railTab, 'about', 'a new revision opens on About');
  const section = $(ctx, '.mlv-about > [data-about]');
  assert.equal(section.getAttribute('data-about'), 'changes', 'the Changes section comes first');
  assert.equal(section.querySelector('h4').textContent, 'Changes since r1');
  assert.equal(ctx.window.getComputedStyle(section.querySelector('.mlv-about__revid')).textTransform, 'none', 'the id keeps its case under the capitalised heading');
  assert.match(section.textContent, /Compared with revision r1, which this panel showed before this one\./);
  assert.match(section.textContent, /matched by id, so one whose id changed is listed as removed and added/);
  assert.match(section.textContent, /covers only revisions this panel has shown; closing the panel, reloading the window or restarting extensions forgets it/);
  const head = (group) => section.querySelector(`[data-change-group="${group}"] .mlv-rail__count`).textContent;
  assert.equal(head('steps'), '1 added · 2 changed · 1 removed');
  assert.equal(head('connections'), '1 added · 1 changed · 1 removed');
  assert.equal(head('findings'), '1 added · 1 changed · 1 removed');
  const rows = $$(ctx, '.mlv-about__change').map((li) => [li.getAttribute('data-change-kind'), li.getAttribute('data-change-id'), li.getAttribute('data-change'), li.textContent]);
  eq(rows, [
    ['node', 'save', 'added', 'new Save weights'],
    ['node', 'aug', 'changed', 'changed Augment · evidence'],
    ['node', 'step', 'changed', 'changed Optimizer step (AdamW) · label'],
    ['node', 'old', 'removed', 'removed Old logging old'],
    ['edge', 'c-zero-save', 'added', 'new weights · Zero grads → Save weights'],
    ['edge', 'c-aug-step', 'changed', 'changed batches · Augment → Optimizer step (AdamW) · evidence'],
    ['edge', 'c-old', 'removed', 'removed logs · Zero grads → Old logging c-old'],
    ['issue', 'f-seed', 'added', 'new F2 · No seed'],
    ['issue', 'f-clip', 'changed', 'changed F1 · Clip missing · severity'],
    ['issue', 'f-old', 'removed', 'removed Old risk f-old'],
  ]);
  // Added and changed items are links; a removed item is text only, and nothing removed is drawn.
  for (const li of $$(ctx, '.mlv-about__change')) {
    const link = li.querySelector('button');
    if (li.getAttribute('data-change') === 'removed') assert.equal(link, null);
    else assert.ok(link && link.classList.contains('mlv-link'), li.textContent);
  }
  assert.equal($(ctx, '[data-node-id="old"]'), null, 'no ghost of the removed step');
  assert.equal($(ctx, '[data-edge-id="c-old"]'), null, 'no ghost of the removed connection');
  assert.equal($(ctx, '.mlv-about__review').textContent, 'Review the 7 added and changed claims');
  assert.doesNotMatch(section.textContent, JUDGING);
  assert.doesNotMatch($(ctx, '.mlv-about').textContent, JUDGING);
});

test('About\'s links select the step, the connection or the finding, whose Selection pane says what changed', async () => {
  const ctx = await mountChanged();
  const link = (id) => $(ctx, `.mlv-about__change[data-change-id="${id}"] button`);
  link('step').click();
  eq(ctx.app.selection, { kind: 'node', id: 'step' });
  assert.equal(ctx.app.getState().railTab, 'inspector');
  const line = $(ctx, '.mlv-sel .mlv-insp__change');
  assert.equal(line.textContent, 'changed since revision r1: label.');
  assert.equal(line.querySelector('.mlv-rev-tag').hasAttribute('aria-hidden'), false, 'the pane\'s tag is read with the words after it');
  tab(ctx, 'about');
  link('c-zero-save').click();
  eq(ctx.app.selection, { kind: 'edge', id: 'c-zero-save' });
  assert.equal($(ctx, '.mlv-sel .mlv-insp__change').textContent, 'new since revision r1.');
  tab(ctx, 'about');
  link('f-clip').click();
  eq(ctx.app.selection, { kind: 'issue', id: 'f-clip' });
  assert.equal($(ctx, '.mlv-sel .mlv-insp__change').textContent, 'changed since revision r1: severity.');
  // An unchanged claim says nothing.
  ctx.app.select({ kind: 'node', id: 'load' }, { tab: 'inspector' });
  assert.equal($(ctx, '.mlv-sel .mlv-insp__change'), null);
});

test('cards: a changed or added step carries a "changed" or "new" tag, said in its name; nothing else is tagged on the canvas', async () => {
  const ctx = await mountChanged();
  const tagOf = (id) => $(ctx, `[data-node-id="${id}"] > .mlv-rev-tag`);
  assert.equal(tagOf('step').textContent, 'changed');
  assert.equal(tagOf('step').getAttribute('data-change'), 'changed');
  assert.equal(tagOf('step').getAttribute('aria-hidden'), 'true', 'the card\'s name says it');
  assert.equal(tagOf('step').title, 'Changed since revision r1: label. About lists every change.');
  assert.equal(tagOf('save').textContent, 'new');
  assert.equal(tagOf('aug').textContent, 'changed');
  assert.equal(tagOf('load'), null);
  assert.equal(tagOf('zero'), null);
  assert.match($(ctx, '[data-node-id="step"]').getAttribute('aria-label'), /, changed in this revision: label\./);
  assert.match($(ctx, '[data-node-id="save"]').getAttribute('aria-label'), /, new in this revision\./);
  assert.doesNotMatch($(ctx, '[data-node-id="load"]').getAttribute('aria-label'), /in this revision/);
  assert.equal($$(ctx, '.mlv-edge .mlv-rev-tag, [data-edge-id] .mlv-rev-tag').length, 0, 'connections carry no tag on the canvas');
  assert.equal($$(ctx, '[data-node-id] .mlv-rev-tag').length, 3, 'one tag per changed or added step');
  // The tag is an overlay: absolutely placed at the bottom-right edge, scaled to screen size.
  const style = ctx.window.getComputedStyle(tagOf('step'));
  assert.equal(style.position, 'absolute');
  // A group's tag sits in its expanded header.
  const regroup = doc2();
  regroup.revision = { id: 'r3', parent: 'r2' };
  regroup.nodes.find((n) => n.id === 'loop').label = 'Training loop';
  ctx.bridge.send({ v: 1, type: 'workflow', document: regroup, previous: doc2() });
  const header = $(ctx, '.mlv-group[data-node-id="loop"] .mlv-group__header');
  assert.ok(header, 'the group is drawn expanded');
  assert.equal(header.querySelector('.mlv-rev-tag').textContent, 'changed');
  assert.match(header.getAttribute('aria-label'), /changed in this revision: label/);
  assert.equal($$(ctx, '[data-node-id] .mlv-rev-tag').length, 1, 'r3 compares with r2 only');
});

test('the tags move no box and no route: the routed geometry is the same with and without the comparison (vit-cc shape)', async () => {
  const next = shapedWorkflow(VIT_SHAPE);
  next.revision = { id: 'vit-r2', parent: 'vit-r1' };
  const previous = clone(next);
  previous.revision = { id: 'vit-r1' };
  // Ten steps relabelled in r2, three steps and four connections added, so tags land everywhere.
  for (let i = 0; i < 10; i++) previous.nodes[i * 3].label = 'Earlier ' + i;
  previous.nodes = previous.nodes.filter((n, i) => i % 9 !== 4 || n.kind === 'group' || next.nodes.some((m) => m.parent === n.id));
  previous.edges = previous.edges.filter((e) => previous.nodes.some((n) => n.id === e.source) && previous.nodes.some((n) => n.id === e.target)).slice(4);
  const plainCtx = await mount(next);
  const markedCtx = await mount(next, { comparison: { previous } });
  assert.ok(markedCtx.app.revisionChanges && markedCtx.app.revisionChanges.marks.size > 10, 'the comparison marks claims');
  assert.ok($$(markedCtx, '[data-node-id] .mlv-rev-tag').length >= 10);
  eq(routedGeometry(markedCtx.document), routedGeometry(plainCtx.document), 'byte-identical geometry');
  eq(markedCtx.app.getState().viewport, plainCtx.app.getState().viewport, 'the same first view');
});

test('Outline and Findings: a changed or added step, connection or finding carries the tag, and its row\'s name says it', async () => {
  const ctx = await mountChanged();
  tab(ctx, 'outline');
  const row = (id) => $(ctx, `[data-outline-id="${id}"] > .mlv-outline__row`);
  assert.equal(row('step').querySelector('.mlv-rev-tag').textContent, 'changed');
  assert.equal(row('step').querySelector('.mlv-rev-tag').getAttribute('aria-hidden'), 'true');
  assert.equal(row('step').querySelector('.mlv-sr').textContent, ', changed in this revision: label');
  assert.equal(row('save').querySelector('.mlv-sr').textContent, ', new in this revision');
  assert.equal(row('load').querySelector('.mlv-rev-tag'), null);
  const relation = (id) => $(ctx, `[data-relation-id="${id}"]`);
  assert.match(relation('c-zero-save').getAttribute('aria-label'), /; new in this revision$/);
  assert.match(relation('c-aug-step').getAttribute('aria-label'), /; changed in this revision: evidence$/);
  assert.equal(relation('c-aug-step').querySelector('.mlv-rev-tag').textContent, 'changed');
  assert.equal(relation('c-load-aug').querySelector('.mlv-rev-tag'), null);
  assert.doesNotMatch(relation('c-load-aug').getAttribute('aria-label'), /in this revision/);
  tab(ctx, 'issues');
  const finding = (id) => $(ctx, `.mlv-issue[data-issue-id="${id}"]`);
  assert.match(finding('f-clip').getAttribute('aria-label'), /, changed in this revision: severity$/);
  assert.equal(finding('f-clip').querySelector('.mlv-rev-tag').textContent, 'changed');
  assert.match(finding('f-seed').getAttribute('aria-label'), /, new in this revision$/);
  assert.equal(finding('f-seed').querySelector('.mlv-rev-tag').textContent, 'new');
});

test('the walk gains "Changed in this revision": the added and changed claims in drawn order, offered only when there are changes', async () => {
  const plainCtx = await mount(doc2());
  plainCtx.canvas.focus();
  plainCtx.app.walk.start('all');
  assert.equal($(plainCtx, '.mlv-walkbar__filter[data-walk-filter="revision"]').hidden, true, 'no comparison: no filter');
  assert.equal(plainCtx.app.walk.start('revision'), false, 'a filter with nothing in it is not offered');
  assert.equal(plainCtx.app.walk.filter, 'all');

  const ctx = await mountChanged();
  ctx.canvas.focus();
  assert.equal(ctx.app.walk.start('revision'), true);
  const button = $(ctx, '.mlv-walkbar__filter[data-walk-filter="revision"]');
  assert.equal(button.hidden, false);
  assert.equal(button.querySelector('.mlv-walkbar__flabel').textContent, 'Changed in this revision');
  assert.equal(button.getAttribute('aria-label'), 'Changed in this revision, 7 claims');
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  const order = ctx.app.walk.claims().map((c) => c.kind + ':' + c.id);
  const walked = ctx.app.walk.list.map((c) => c.kind + ':' + c.id);
  eq(walked, ['issue:f-seed', 'node:aug', 'edge:c-aug-step', 'node:step', 'issue:f-clip', 'edge:c-zero-save', 'node:save']);
  eq(walked, order.filter((key) => ctx.app.revisionChanges.marks.has(key)), 'the drawn order');
  assert.match(live(ctx), /^Claim 1 of 7, changed in this revision: Finding F2 No seed\.$/);
  // The bar's place names the filter.
  assert.equal($(ctx, '.mlv-walkbar__postext').textContent, 'Claim 1 of 7 · Changed in this revision');
  ctx.app.walk.stop(false);
  // About's Review button starts it there and gives the keyboard to the diagram.
  tab(ctx, 'about');
  $(ctx, '.mlv-about__review').click();
  assert.equal(ctx.app.walk.active, true);
  assert.equal(ctx.app.walk.filter, 'revision');
  assert.equal(ctx.document.activeElement, ctx.canvas);
});

test('a remounted page gets the comparison again from the host and brings back a walk on "Changed in this revision"', async () => {
  const first = await mountChanged();
  first.canvas.focus();
  first.app.walk.start('revision');
  first.app.walk.step(1);
  const saved = first.app.getState();
  assert.equal(saved.walk.filter, 'revision');
  assert.equal(saved.walk.active, true);
  // VS Code rebuilt the page; the host's first frame carries the same comparison.
  const again = await mount(doc2(), { state: plain(saved), comparison: { previous: doc1() } });
  assert.equal(again.app.walk.active, true);
  assert.equal(again.app.walk.filter, 'revision');
  eq(again.app.walk.current(), { kind: 'node', id: 'aug' });
  assert.ok($(again, '[data-node-id="step"] > .mlv-rev-tag'));
  // A page the host sends no comparison (a new panel after a window reload) falls back to All.
  const fresh = await mount(doc2(), { state: plain(saved) });
  assert.equal(fresh.app.walk.filter, 'all');
  assert.equal($(fresh, '[data-node-id] .mlv-rev-tag'), null);
});

test('a revision that does not follow the one this panel showed lists no changes and says why; a parent never shown is named in Provenance', async () => {
  const ctx = await mount(doc1());
  const r3 = doc2();
  r3.revision = { id: 'r3', parent: 'r2' };
  ctx.bridge.send({ v: 1, type: 'workflow', document: r3, replaced: 'r1' });
  const section = $(ctx, '.mlv-about [data-about="changes"]');
  assert.equal(section.querySelector('h4').textContent, 'Changes');
  assert.equal(section.querySelector('p').textContent,
    'No changes are listed: revision r3 does not follow revision r1, which this panel showed before it (its parent is r2). Changes are listed only against the revision this panel showed just before.');
  assert.equal($(ctx, '[data-node-id] .mlv-rev-tag, .mlv-rail .mlv-rev-tag'), null, 'no tags');
  assert.equal(ctx.app.revisionChanges, null);
  ctx.canvas.focus();
  assert.equal(ctx.app.walk.start('revision'), false, 'no filter to walk');
  assert.match(live(ctx), /No claim was added or changed since the revision this panel showed before\./);
  assert.equal($(ctx, '.mlv-about [data-about-note="parent-not-shown"]'), null);
  // A first revision with a parent this panel never showed: one line in Provenance, no section.
  const fresh = await mount(doc2());
  assert.equal($(fresh, '.mlv-about [data-about="changes"]'), null);
  assert.equal($(fresh, '.mlv-about [data-about-note="parent-not-shown"]').textContent, 'This panel did not show revision r1, so no changes since it are listed.');
  // A frame whose previous is not the document's parent is ignored.
  const odd = await mount(doc1());
  odd.bridge.send({ v: 1, type: 'workflow', document: doc2(), previous: { ...doc1(), revision: { id: 'r0' } } });
  assert.equal(odd.app.revisionChanges, null);
  assert.equal($(odd, '.mlv-about [data-about="changes"]'), null);
});

test('the comparison follows each frame: a refresh that carries it keeps the tags; the same revision with nothing changed says so', async () => {
  const ctx = await mountChanged();
  const refreshed = doc2();
  refreshed.verification = { files: {}, publishedAt: '2026-10-03T00:00:00Z' };
  ctx.bridge.send({ v: 1, type: 'workflow', document: refreshed, previous: doc1() });
  assert.ok($(ctx, '[data-node-id="step"] > .mlv-rev-tag'), 'a refresh of the same revision keeps the tags');
  // A child revision with nothing compared changed.
  const same = doc1();
  same.revision = { id: 'r1b', parent: 'r1' };
  const quiet = await mount(doc1());
  quiet.bridge.send({ v: 1, type: 'workflow', document: same, previous: doc1() });
  const section = $(quiet, '.mlv-about [data-about="changes"]');
  assert.match(section.textContent, /No step, connection or finding was added, removed or changed\./);
  assert.equal($(quiet, '.mlv-about__review'), null);
  quiet.canvas.focus();
  quiet.app.walk.start('all');
  assert.equal($(quiet, '.mlv-walkbar__filter[data-walk-filter="revision"]').hidden, true);
});

test('the SVG export draws no tag and names no change: it is a picture of the revision, not of the comparison', async () => {
  const ctx = await mountChanged();
  $(ctx, '.mlv-btn--more').click();
  $(ctx, '[data-export-action="svg"]').click();
  const frame = ctx.bridge.posted.findLast((item) => item.type === 'exportFile' && item.kind === 'svg');
  assert.ok(frame);
  const svg = Buffer.from(frame.base64, 'base64').toString('utf8');
  assert.match(svg, /Optimizer step \(AdamW\)/);
  assert.doesNotMatch(svg, /in this revision|mlv-rev-tag|since revision/);
});

test('the legend explains the two tags in words', async () => {
  const ctx = await mountChanged();
  const section = $(ctx, '[data-legend-section="revision"]');
  assert.ok(section);
  assert.equal(section.querySelector('h3').textContent, 'Changes since the previous revision');
  assert.equal(section.querySelector('[data-legend-row="revision:added"] .mlv-rev-tag').textContent, 'new');
  assert.equal(section.querySelector('[data-legend-row="revision:changed"] .mlv-rev-tag').textContent, 'changed');
  assert.match(section.textContent, /not whether the claim holds/);
  assert.doesNotMatch(section.textContent, JUDGING);
});
