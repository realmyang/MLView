// Viewer M1: the verification loop, in the webview.
//
// A click selects and shows the claim; it never opens source. Enter, a double-click and the
// Inspector's Open links open the cited range beside the panel with focus kept in the diagram;
// Alt+Enter asks the host to move focus to the editor. The host's `stale` frame marks the cards,
// connections, quotes and findings that cite a changed or missing file, blocks their jumps, and
// counts them in the status bar. Once mounted, the host's banner is drawn under the header, and
// the workspace-root hint offers its two actions.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadBundle, recordingBridge } from './helpers.mjs';

function doc(overrides = {}) {
  return {
    workflowVersion: '1.0', title: 'Verification loop fixture',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'q', scope: 's' },
    phases: [{ id: 'train', label: 'Train' }],
    nodes: [
      { id: 'load', label: 'Load batch', phase: 'train', basis: 'observed', evidence: ['e1'] },
      { id: 'loss', label: 'Compute loss', phase: 'train', basis: 'observed', evidence: ['e2'] },
      { id: 'step', label: 'Optimizer step', phase: 'train', basis: 'observed', evidence: ['e3', 'e2'] },
    ],
    edges: [
      { id: 'load-loss', source: 'load', target: 'loss', label: 'batch', basis: 'observed', evidence: ['e2'] },
      { id: 'loss-step', source: 'loss', target: 'step', label: 'grads', basis: 'observed', evidence: ['e1'] },
    ],
    findings: [
      { id: 'f-load', title: 'Shuffle is off', message: 'm', severity: 'medium', nodeIds: ['load'], edgeIds: [], basis: 'inferred', evidence: ['e1'] },
      { id: 'f-loss', title: 'Loss is summed', message: 'm', severity: 'low', nodeIds: ['loss'], edgeIds: [], basis: 'inferred', evidence: ['e2'] },
    ],
    evidence: [
      { id: 'e1', file: 'data.py', line: 3, endLine: 5, quote: 'loader = DataLoader(ds)' },
      { id: 'e2', file: 'train.py', line: 10, endLine: 12, quote: 'loss = crit(out, y)' },
      { id: 'e3', file: 'data.py', line: 20, endLine: 20, quote: 'opt.step()' },
    ],
    coverage: { status: 'scoped', summary: 's', inspectedFiles: ['data.py', 'train.py', 'notes.py'], limitations: [] },
    ...overrides,
  };
}

async function mount(document = doc()) {
  const ctx = await loadBundle();
  const root = ctx.document.getElementById('mlview-root');
  const bridge = recordingBridge(ctx.window, 'vscode');
  const app = ctx.MLView.mountWorkflow(root, document, bridge);
  return { ...ctx, root, app, bridge };
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const opens = (ctx) => ctx.bridge.posted.filter((m) => m.type === 'openLocation');
const $ = (ctx, selector) => ctx.document.querySelector(selector);
const card = (ctx, id) => $(ctx, `.mlv-node[data-node-id="${id}"]`);
const edgeHit = (ctx, id) => $(ctx, `[data-edge-id="${id}"] .mlv-edge__hit`);
const findingRow = (ctx, id) => $(ctx, `.mlv-issue[data-issue-id="${id}"][role="option"]`);
const outlineRow = (ctx, id) => $(ctx, `[data-outline-id="${id}"] > .mlv-outline__row`);
const mouse = (ctx, target, type, init = {}) => target.dispatchEvent(new ctx.window.MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
const key = (ctx, target, keyName, init = {}) => target.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: keyName, bubbles: true, cancelable: true, ...init }));
const stale = (ctx, files) => ctx.bridge.send({ v: 1, type: 'stale', files });
const sourceButtons = (ctx) => Array.from(ctx.document.querySelectorAll('.mlv-insp__source-evidence li'));

test('a click on a card, connection, finding or outline row selects it and opens nothing', async () => {
  const ctx = await mount();
  try {
    mouse(ctx, card(ctx, 'loss'), 'click');
    assert.ok(card(ctx, 'loss').classList.contains('is-selected'), 'the clicked card is selected');
    assert.equal(ctx.app.getState().selection.id, 'loss');
    assert.ok(sourceButtons(ctx).some((li) => /Open train\.py:10/.test(li.textContent)), 'the Inspector shows the claim and its evidence');

    mouse(ctx, edgeHit(ctx, 'load-loss'), 'click');
    assert.equal(ctx.app.getState().selection.kind, 'edge');
    assert.equal(ctx.app.getState().selection.id, 'load-loss');

    ctx.app.setRailTab('issues');
    mouse(ctx, findingRow(ctx, 'f-load'), 'click');
    assert.equal(ctx.app.getState().selection.kind, 'issue');

    ctx.app.setRailTab('outline');
    assert.ok(outlineRow(ctx, 'step'), 'the outline is drawn');
    mouse(ctx, outlineRow(ctx, 'step'), 'click');
    assert.equal(ctx.app.getState().selection.id, 'step');
    await sleep(20);
    assert.deepEqual(opens(ctx), [], 'no click posted openLocation');
  } finally {
    ctx.app.destroy();
  }
});

test('Enter and a double-click open the cited range with focus kept; Alt+Enter asks for focus', async () => {
  const ctx = await mount();
  try {
    const target = card(ctx, 'loss');
    target.focus();
    key(ctx, target, 'Enter');
    assert.equal(opens(ctx).length, 1, 'Enter on a card opens once');
    const first = opens(ctx)[0];
    assert.equal(first.evidenceId, 'e2');
    assert.equal(first.file, 'train.py');
    assert.equal(first.line, 10);
    assert.equal(first.endLine, 12);
    assert.equal(first.focus, undefined, 'Enter keeps focus in the diagram');
    assert.equal(ctx.app.getState().selection.id, 'loss', 'Enter also selects');
    await sleep(20);
    assert.equal(ctx.document.activeElement?.getAttribute('data-node-id'), 'loss', 'focus stays on the card after the open');
    // Keyboard navigation keeps working from there: Enter again opens again.
    key(ctx, ctx.document.activeElement, 'Enter');
    assert.equal(opens(ctx).length, 2);

    key(ctx, card(ctx, 'loss'), 'Enter', { altKey: true });
    assert.equal(opens(ctx).length, 3);
    assert.equal(opens(ctx)[2].focus, true, 'Alt+Enter is the open-and-focus gesture');

    mouse(ctx, card(ctx, 'load'), 'dblclick');
    assert.equal(opens(ctx).length, 4, 'a double-click on a card opens');
    assert.equal(opens(ctx)[3].evidenceId, 'e1');
    assert.equal(opens(ctx)[3].focus, undefined);

    mouse(ctx, edgeHit(ctx, 'load-loss'), 'dblclick');
    assert.equal(opens(ctx).length, 5, 'a double-click on a connection opens');
    assert.equal(opens(ctx)[4].evidenceId, 'e2');
    assert.equal(ctx.app.getState().selection.id, 'load-loss');

    key(ctx, edgeHit(ctx, 'loss-step'), 'Enter');
    assert.equal(opens(ctx).length, 6, 'Enter on a connection opens');
    assert.equal(opens(ctx)[5].evidenceId, 'e1');
  } finally {
    ctx.app.destroy();
  }
});

test('the Inspector Open link opens beside; Alt+click moves focus', async () => {
  const ctx = await mount();
  try {
    mouse(ctx, card(ctx, 'step'), 'click');
    const buttons = sourceButtons(ctx).map((li) => li.querySelector('button'));
    assert.equal(buttons.length, 2);
    buttons[1].click();
    assert.equal(opens(ctx).length, 1);
    assert.equal(opens(ctx)[0].evidenceId, 'e2');
    assert.equal(opens(ctx)[0].focus, undefined);
    mouse(ctx, sourceButtons(ctx)[0].querySelector('button'), 'click', { altKey: true });
    assert.equal(opens(ctx)[1].evidenceId, 'e3');
    assert.equal(opens(ctx)[1].focus, true);
  } finally {
    ctx.app.destroy();
  }
});

test('Enter and a double-click on a finding row open its first quote; Space only selects', async () => {
  const ctx = await mount();
  try {
    ctx.app.setRailTab('issues');
    const row = findingRow(ctx, 'f-loss');
    assert.ok(row, 'the findings list is drawn');
    key(ctx, row, ' ');
    assert.equal(ctx.app.getState().selection.id, 'f-loss');
    assert.equal(opens(ctx).length, 0, 'Space selects without opening');
    key(ctx, findingRow(ctx, 'f-loss'), 'Enter');
    assert.equal(opens(ctx).length, 1, 'Enter on a finding row opens');
    assert.equal(opens(ctx)[0].evidenceId, 'e2');
    mouse(ctx, findingRow(ctx, 'f-load'), 'dblclick');
    assert.equal(opens(ctx).length, 2, 'a double-click on a finding row opens');
    assert.equal(opens(ctx)[1].evidenceId, 'e1');
    assert.equal(ctx.app.getState().selection.id, 'f-load');
  } finally {
    ctx.app.destroy();
  }
});

test('Enter and a double-click on an Outline step open its first quote', async () => {
  const ctx = await mount();
  try {
    ctx.app.setRailTab('outline');
    const item = $(ctx, '[data-outline-id="loss"]');
    assert.ok(item, 'the outline is drawn');
    key(ctx, item, 'Enter');
    assert.equal(opens(ctx).length, 1, 'Enter on an Outline step opens');
    assert.equal(opens(ctx)[0].evidenceId, 'e2');
    mouse(ctx, $(ctx, '[data-outline-id="load"] > .mlv-outline__row'), 'dblclick');
    assert.equal(opens(ctx).length, 2, 'a double-click on an Outline step opens');
    assert.equal(opens(ctx)[1].evidenceId, 'e1');
  } finally {
    ctx.app.destroy();
  }
});

test('the stale frame marks cards, connections, quotes, findings and the status bar, and blocks those jumps', async () => {
  const ctx = await mount();
  try {
    assert.equal($(ctx, '.is-stale'), null, 'nothing is marked before the host reports a stale file');
    assert.equal($(ctx, '[data-freshness]'), null, 'no freshness item while every file is unchanged (no green)');

    stale(ctx, [{ path: 'data.py', reason: 'changed' }]);
    assert.ok(card(ctx, 'load').classList.contains('is-stale'), 'a card citing the changed file is marked');
    assert.ok(card(ctx, 'load').querySelector('.mlv-node__stale'), 'with a mark, not colour alone');
    assert.match(card(ctx, 'load').querySelector('.mlv-node__stale').title, /1 of 1 quote cites a changed or missing file/);
    assert.ok(card(ctx, 'step').classList.contains('is-stale'), 'a card with some stale quotes is marked');
    assert.match(card(ctx, 'step').querySelector('.mlv-node__stale').title, /1 of 2 quotes cite/);
    assert.equal(card(ctx, 'loss').classList.contains('is-stale'), false, 'a card citing only unchanged files is not');
    assert.ok($(ctx, '[data-edge-id="loss-step"]').classList.contains('is-stale'), 'a connection citing it is marked');
    assert.equal($(ctx, '[data-edge-id="load-loss"]').classList.contains('is-stale'), false);
    assert.match(edgeHit(ctx, 'loss-step').getAttribute('aria-label'), /cites a changed or missing file/);

    const status = $(ctx, '[data-freshness="stale"]');
    assert.ok(status, 'the status bar counts the stale files');
    assert.match(status.textContent, /^1 of 2 cited files changed$/);
    assert.match(status.title, /data\.py — changed since publishing/);

    // Quotes in the Inspector: the stale one says why and its Open link is disabled.
    mouse(ctx, card(ctx, 'step'), 'click');
    const rows = sourceButtons(ctx);
    assert.equal(rows.length, 2);
    assert.ok(rows[0].classList.contains('is-stale'));
    assert.equal(rows[0].getAttribute('data-stale'), 'changed');
    assert.equal(rows[0].querySelector('button').disabled, true, 'the stale quote cannot be opened');
    assert.match(rows[0].querySelector('button').title, /data\.py:20: changed since publishing\. Not opened\./);
    assert.match(rows[0].textContent, /changed since publishing/);
    assert.equal(rows[1].classList.contains('is-stale'), false);
    assert.equal(rows[1].querySelector('button').disabled, false);
    assert.match($(ctx, '.mlv-insp__stale-note').textContent, /1 of 2 quotes cite a file that no longer matches/);

    // Enter on a card whose first quote is stale says why and posts nothing.
    key(ctx, card(ctx, 'load'), 'Enter');
    assert.equal(opens(ctx).length, 0, 'a stale jump is not sent to the host');
    assert.match(ctx.app.liveEl.textContent, /data\.py: changed since publishing\. Not opened/);
    key(ctx, card(ctx, 'loss'), 'Enter');
    assert.equal(opens(ctx).length, 1, 'an unchanged quote still opens');

    // Findings: the row carries a chip in words.
    ctx.app.setRailTab('issues');
    assert.ok(findingRow(ctx, 'f-load').classList.contains('is-stale'));
    assert.match(findingRow(ctx, 'f-load').querySelector('.mlv-chip--stale').textContent, /changed/);
    assert.equal(findingRow(ctx, 'f-loss').classList.contains('is-stale'), false);

    // A missing file is worded as missing; an inspected-only file is counted apart.
    stale(ctx, [{ path: 'train.py', reason: 'missing' }, { path: 'notes.py', reason: 'missing' }]);
    assert.match($(ctx, '[data-freshness="stale"]').textContent, /^1 of 2 cited files missing · 1 inspected$/);
    assert.equal(card(ctx, 'load').classList.contains('is-stale'), false, 'marks follow the latest frame');
    assert.ok(card(ctx, 'loss').classList.contains('is-stale'));

    // An empty list clears every mark and the status item.
    stale(ctx, []);
    assert.equal($(ctx, '.mlv-node.is-stale'), null);
    assert.equal($(ctx, '.mlv-edge.is-stale'), null);
    assert.equal($(ctx, '.mlv-issue.is-stale'), null);
    assert.equal($(ctx, '[data-freshness]'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('a malformed stale frame marks nothing', async () => {
  const ctx = await mount();
  try {
    ctx.bridge.send({ v: 1, type: 'stale', files: 'data.py' });
    ctx.bridge.send({ v: 1, type: 'stale', files: [{ path: 'data.py', reason: 'gone' }, { path: 42, reason: 'changed' }, null] });
    assert.equal($(ctx, '.is-stale'), null);
    assert.equal($(ctx, '[data-freshness]'), null);
  } finally {
    ctx.app.destroy();
  }
});

test('after the mount the host banner is a notice under the header; the root hint offers its actions', async () => {
  const ctx = await mount();
  try {
    const notice = () => $(ctx, '.mlv-hostnotice');
    assert.ok(!notice() || notice().hidden, 'no notice for a fresh revision');
    const hint = 'These files exist under ./copy/ but the workspace root is /work. The diagram cites paths relative to ./copy/.';
    ctx.bridge.send({ v: 1, type: 'workflowError', message: hint, retained: true, codes: ['root-hint'] });
    assert.ok(notice() && !notice().hidden, 'the notice is shown');
    assert.equal(notice().textContent.indexOf(hint) >= 0, true, 'the host text is shown as is');
    assert.match(notice().className, /mlv-hostnotice--warn/);
    assert.ok(notice().querySelector('.mlv-hostnotice__icon svg'), 'a problem carries an icon, not colour alone');
    assert.ok(ctx.root.contains(notice()));
    const buttons = Array.from(notice().querySelectorAll('[data-workspace-hint]'));
    assert.deepEqual(buttons.map((b) => b.textContent), ['Add folder to workspace', 'Open folder']);
    buttons[0].click();
    buttons[1].click();
    assert.deepEqual(ctx.bridge.posted.filter((m) => m.type === 'workspaceHint').map((m) => m.action), ['add', 'open']);

    // The checking status goes to the status bar; the notice keeps its text.
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'Changes detected; checking diagram freshness.', retained: true, codes: ['checking'] });
    assert.match($(ctx, '[data-freshness="checking"]').textContent, /Checking source freshness/);
    assert.equal(notice().hidden, false);
    assert.ok(notice().textContent.indexOf(hint) >= 0);

    // A stale banner has no actions; an empty banner hides the notice and the checking item.
    ctx.bridge.send({ v: 1, type: 'workflowError', message: 'Source changed after revision r1 was published: data.py.', retained: true, codes: ['stale'] });
    assert.equal(notice().querySelectorAll('[data-workspace-hint]').length, 0);
    assert.equal($(ctx, '[data-freshness="checking"]'), null);
    ctx.bridge.send({ v: 1, type: 'workflowError', message: '', retained: true, codes: [] });
    assert.equal(notice().hidden, true);
  } finally {
    ctx.app.destroy();
  }
});
