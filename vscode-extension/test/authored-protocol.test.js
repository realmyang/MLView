'use strict';
/**
 * Host side of the host <-> webview protocol (Campaign 1, contract 1e): the reply to `ready`,
 * banner ordering, re-post rules, `actionResult` for export / copy / refine, theme mapping and
 * the content security policy.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./panel-helpers');
const { api, vscode } = h;

const fixtures = [];
test.afterEach(() => h.cleanup(fixtures));
async function open(options) {
  const fixture = await h.openPanel(options);
  fixtures.push(fixture);
  return fixture;
}
const svg = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"></svg>').toString('base64');
async function result(panel, count) {
  await h.waitFor(() => h.results(panel).length >= count, 'no actionResult was posted');
  return h.results(panel).at(-1);
}

test('each ready gets init, workflow and then the banner, in that order', async () => {
  const stale = h.verify(h.workflow(), { 'source.py': 'fit()\n' });
  const { panel } = await open({ raw: stale, files: { 'source.py': 'changed()\n' } });
  assert.deepEqual(panel.postedTypes(), ['init', 'workflow', 'workflowError']);
  assert.deepEqual(panel.posted[2].codes, ['stale']);
  assert.equal(panel.posted[2].retained, true);
  assert.equal(panel.posted[0].theme, 'dark');
  assert.equal(typeof panel.posted[0].artifact, 'string');
  // A recreated webview posts ready again and gets the same burst.
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.deepEqual(panel.postedTypes(), ['init', 'workflow', 'workflowError', 'init', 'workflow', 'workflowError']);
});

test('a fresh artifact gets no banner and an invalid one gets only the banner', async () => {
  const fresh = await open({});
  assert.deepEqual(fresh.panel.postedTypes(), ['init', 'workflow']);
  const invalid = await open({ raw: { workflowVersion: '1.0' } });
  assert.deepEqual(invalid.panel.postedTypes(), ['init', 'workflowError']);
  assert.deepEqual(invalid.panel.posted[1].codes, ['invalid']);
  assert.equal(invalid.panel.posted[1].retained, false);
  assert.match(invalid.panel.posted[1].message, /^Generated diagram update rejected; nothing valid can be displayed yet\.\nThe artifact cannot be displayed:\n/);
});

test('an identical refresh re-posts nothing; a changed verification block re-posts the workflow', async () => {
  const { panel, artifact } = await open({});
  fs.writeFileSync(artifact, fs.readFileSync(artifact));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.workflows(panel).length, 1);
  h.writeJson(artifact, h.verify(h.workflow(), { 'source.py': 'fit()\n' }));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.workflows(panel).length, 2);
  assert.ok(h.workflows(panel).at(-1).document.verification);
  assert.deepEqual(h.lastBanner(panel).codes, []);
  // The banner is posted only when its text changes.
  const posted = panel.posted.length;
  fs.writeFileSync(artifact, fs.readFileSync(artifact));
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(panel.posted.slice(posted).map(m => [m.type, m.codes]), [['workflowError', ['checking']], ['workflowError', []]]);
  assert.equal(panel.posted.at(-1).message, '');
});

test('exportFile answers every request that carries a requestId', async () => {
  const { panel, root } = await open({});
  const target = vscode.Uri.file(path.join(root, 'out', 'diagram.svg'));
  vscode.__answerSaveDialog(target);
  panel.fire({ v: 1, type: 'exportFile', kind: 'svg', data: svg, suggestedName: 'diagram.svg', scope: 'all', requestId: 'exp-1' });
  assert.deepEqual(await result(panel, 1), { v: 1, type: 'actionResult', requestId: 'exp-1', action: 'exportFile', outcome: 'done', name: 'diagram.svg' });
  assert.equal(vscode.__recorded.writtenFiles.at(-1).fsPath, target.fsPath);
  vscode.__answerSaveDialog(undefined);
  panel.fire({ v: 1, type: 'exportFile', kind: 'svg', data: svg, requestId: 'exp-2' });
  assert.deepEqual(await result(panel, 2), { v: 1, type: 'actionResult', requestId: 'exp-2', action: 'exportFile', outcome: 'cancelled' });
  panel.fire({ v: 1, type: 'exportFile', kind: 'svg', data: '', requestId: 'exp-3' });
  assert.deepEqual(await result(panel, 3), { v: 1, type: 'actionResult', requestId: 'exp-3', action: 'exportFile', outcome: 'failed', message: 'the payload was refused (empty)' });
  panel.fire({ v: 1, type: 'exportFile', kind: 'png', data: svg, requestId: 'exp-4' });
  assert.deepEqual(await result(panel, 4), { v: 1, type: 'actionResult', requestId: 'exp-4', action: 'exportFile', outcome: 'failed', message: 'the payload was refused (wrong-format)' });
  vscode.__answerSaveDialog(target);
  vscode.__failNextWrite();
  panel.fire({ v: 1, type: 'exportFile', kind: 'svg', data: svg, requestId: 'exp-5' });
  const failed = await result(panel, 5);
  assert.deepEqual(failed, { v: 1, type: 'actionResult', requestId: 'exp-5', action: 'exportFile', outcome: 'failed', message: 'the file could not be written' });
  assert.equal(JSON.stringify(failed).includes(root), false, 'results never carry absolute paths');
  panel.fire({ v: 1, type: 'exportFile', kind: 'gif', data: svg, requestId: 'exp-6' });
  assert.deepEqual(await result(panel, 6), { v: 1, type: 'actionResult', requestId: 'exp-6', action: 'exportFile', outcome: 'failed', message: 'the export request was malformed' });
  // Without a valid requestId the action still runs, but no result is sent.
  const written = vscode.__recorded.writtenFiles.length;
  vscode.__answerSaveDialog(target);
  panel.fire({ v: 1, type: 'exportFile', kind: 'svg', data: svg, requestId: 'not valid!' });
  await h.waitFor(() => vscode.__recorded.writtenFiles.length === written + 1, 'export without a valid id did not run');
  await h.sleep(20);
  assert.equal(h.results(panel).length, 6);
});

test('copy writes the clipboard and reports its outcome without a notification', async () => {
  const { panel } = await open({});
  const notifications = vscode.__recorded.messages.length;
  panel.fire({ v: 1, type: 'copy', text: 'stage:train', requestId: 'copy-1' });
  assert.deepEqual(await result(panel, 1), { v: 1, type: 'actionResult', requestId: 'copy-1', action: 'copy', outcome: 'done' });
  assert.equal(vscode.__recorded.clipboardWrites.at(-1), 'stage:train');
  panel.fire({ v: 1, type: 'copy', text: '', requestId: 'copy-2' });
  assert.deepEqual(await result(panel, 2), { v: 1, type: 'actionResult', requestId: 'copy-2', action: 'copy', outcome: 'failed', message: 'nothing to copy' });
  panel.fire({ v: 1, type: 'copy', text: 42, requestId: 'copy-3' });
  assert.equal((await result(panel, 3)).message, 'nothing to copy');
  panel.fire({ v: 1, type: 'copy', text: 'x'.repeat(api.MAX_EXPORT_BYTES + 1), requestId: 'copy-4' });
  assert.deepEqual(await result(panel, 4), { v: 1, type: 'actionResult', requestId: 'copy-4', action: 'copy', outcome: 'failed', message: 'the text is too large to copy' });
  const original = vscode.env.clipboard.writeText;
  vscode.env.clipboard.writeText = async () => { throw new Error('clipboard unavailable'); };
  try {
    panel.fire({ v: 1, type: 'copy', text: 'stage:train', requestId: 'copy-5' });
    assert.deepEqual(await result(panel, 5), { v: 1, type: 'actionResult', requestId: 'copy-5', action: 'copy', outcome: 'failed', message: 'the clipboard refused the text' });
  } finally {
    vscode.env.clipboard.writeText = original;
  }
  assert.equal(vscode.__recorded.clipboardWrites.length, 1);
  assert.equal(vscode.__recorded.messages.length, notifications);
});

test('refineWorkflow reports done or the refusal without its MLView prefix', async () => {
  const { panel } = await open({});
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'explain', requestId: 'ref-1' });
  assert.deepEqual(await result(panel, 1), { v: 1, type: 'actionResult', requestId: 'ref-1', action: 'refineWorkflow', outcome: 'done' });
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r0', intent: 'explain', requestId: 'ref-2' });
  assert.deepEqual(await result(panel, 2), { v: 1, type: 'actionResult', requestId: 'ref-2', action: 'refineWorkflow', outcome: 'failed', message: 'refinement request is stale; the displayed revision is now r1. Select the item again.' });
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'summarize', requestId: 'ref-3' });
  assert.equal((await result(panel, 3)).message, 'unknown refinement intent.');
});

test('themeKindOf maps both high-contrast kinds to hc', async () => {
  const kinds = vscode.ColorThemeKind;
  assert.deepEqual([kinds.Light, kinds.Dark, kinds.HighContrast, kinds.HighContrastLight].map(api.themeKindOf), ['light', 'dark', 'hc', 'hc']);
  const { panel } = await open({});
  for (const listener of vscode.__recorded.themeListeners) listener({ kind: kinds.HighContrastLight });
  assert.deepEqual(panel.posted.at(-1), { v: 1, type: 'theme', kind: 'hc' });
});

test('the webview HTML keeps a strict nonce-based content security policy', async () => {
  const { panel } = await open({ ready: false });
  const html = panel.webview.html;
  const csp = /<meta http-equiv="Content-Security-Policy" content="([^"]+)">/.exec(html);
  assert.ok(csp, 'CSP meta tag present');
  assert.match(csp[1], /^default-src 'none';/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval/);
  const nonce = /script-src 'nonce-([^']+)'/.exec(csp[1])[1];
  const scripts = [...html.matchAll(/<script nonce="([^"]+)"/g)].map(m => m[1]);
  assert.equal(scripts.length, 2);
  assert.deepEqual(scripts, [nonce, nonce]);
  assert.ok(nonce.length >= 24);
  const second = await open({ ready: false });
  assert.notEqual(/script-src 'nonce-([^']+)'/.exec(second.panel.webview.html)[1], nonce, 'a fresh nonce per panel');
});
