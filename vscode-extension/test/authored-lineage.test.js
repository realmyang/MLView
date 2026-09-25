'use strict';
/**
 * Panel-level revision acceptance (Campaign 1, contract 1a). Every reload here is driven the way
 * helper publications arrive in VS Code: a file-system watcher event, never `controller.open`
 * (which resets the lineage).
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
const rev = (id, parent, mutate) => {
  const doc = h.workflow('source.py', parent ? { id, parent } : { id });
  if (mutate) mutate(doc);
  return doc;
};

test('a watcher-driven external replace adopts the child revision', async () => {
  const { panel, artifact } = await open({});
  assert.equal(h.shownRevision(panel), 'r1');
  h.writeJson(artifact, rev('r2', 'r1'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r2');
  assert.deepEqual(h.lastBanner(panel).codes, []);
  assert.equal(panel.title, 'MLView: Authored');
});

test('S1b: a viewer-only rejection does not wedge the lineage; its child is adopted', async () => {
  const { panel, artifact, controller } = await open({});
  h.writeJson(artifact, rev('r2', 'r1', doc => { doc.nodes[0].parent = null; }));
  await h.diskEvent(panel, 'change', artifact);
  const banner = h.lastBanner(panel);
  assert.deepEqual(banner.codes, ['invalid']);
  assert.equal(banner.retained, true);
  assert.equal(banner.message, 'Generated diagram update rejected; retaining the last valid revision.\nRevision r2 cannot be displayed:\n$.nodes[0].parent: must be a string');
  assert.equal(h.shownRevision(panel), 'r1');
  // While r2 is rejected, Refine continues from the revision in the file.
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'expand', requestId: 'refine-1' });
  await h.waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'refine prompt was not copied');
  const prompt = vscode.__recorded.clipboardWrites[0];
  assert.match(prompt, /^The artifact file now holds revision r2, which the viewer could not display \(see "viewerRejection" in the JSON block\)\. Read the artifact file and resolve the selected item in revision r2 first\. If you publish, set revision\.parent to r2 and fix those problems\.$/m);
  assert.deepEqual(h.promptData(prompt).viewerRejection, ['$.nodes[0].parent: must be a string']);
  assert.match(vscode.__recorded.messages.at(-1)[1], / The diagram shows revision r1; the artifact file holds revision r2, so the prompt continues from r2\.$/);
  assert.deepEqual(h.results(panel).at(-1), { v: 1, type: 'actionResult', requestId: 'refine-1', action: 'refineWorkflow', outcome: 'done' });
  h.writeJson(artifact, rev('r3', 'r2'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  assert.deepEqual(h.lastBanner(panel).codes, []);
  controller.dispose();
});

test('a newer revision whose sources changed is adopted as historical, never rejected', async () => {
  const { panel, artifact, root } = await open({ raw: h.verify(rev('r1'), { 'source.py': 'fit()\n' }) });
  const r2 = h.verify(rev('r2', 'r1'), { 'source.py': 'fit()\n' });
  fs.writeFileSync(path.join(root, 'source.py'), 'fit()\n# edited after publish\n');
  h.writeJson(artifact, r2);
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r2');
  assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
  assert.match(h.lastBanner(panel).message, /historical diagram is visible, but 1 source file\(s\) changed after revision r2 was published: source\.py\./);
  assert.ok(vscode.__recorded.messages.some(m => m[0] === 'warn' && m[1] === 'MLView: 1 source file(s) changed after the displayed revision was published.'));
});

test('S4: a restored older revision is obsolete until Open resets the lineage', async () => {
  const { panel, artifact, controller } = await open({});
  h.writeJson(artifact, rev('r2', 'r1'));
  const r2Bytes = fs.readFileSync(artifact);
  await h.diskEvent(panel, 'change', artifact);
  h.writeJson(artifact, rev('r3', 'r2'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  fs.writeFileSync(artifact, r2Bytes);
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  assert.deepEqual(h.lastBanner(panel).codes, ['obsolete']);
  assert.equal(h.lastBanner(panel).message, "Generated diagram update rejected; retaining the last valid revision.\nThe artifact file holds revision r2, which the displayed revision r3 already superseded (for example, it was restored from version control). Run MLView: Open Generated Diagram to show the file's revision instead.");
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r3', intent: 'trace' });
  await h.waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'refine prompt was not copied');
  assert.match(vscode.__recorded.clipboardWrites[0], /^The artifact file holds revision r2, which the displayed revision r3 already superseded, so the file was probably restored or replaced\. Read the artifact file, tell the user, and ask whether to continue from revision r2 before publishing\. If you publish, set revision\.parent to r2\.$/m);
  const posted = h.workflows(panel).length;
  await controller.open(vscode.Uri.file(artifact));
  assert.equal(h.workflows(panel).length, posted + 1);
  assert.equal(h.shownRevision(panel), 'r2');
  assert.deepEqual(h.lastBanner(panel).codes, []);
  assert.equal(panel.revealed, 1);
});

test('S6: an observed delete resets the lineage so a fresh analysis may reuse ids', async () => {
  const { panel, artifact } = await open({});
  h.writeJson(artifact, rev('r2', 'r1'));
  await h.diskEvent(panel, 'change', artifact);
  fs.rmSync(artifact);
  await h.diskEvent(panel, 'delete', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['missing']);
  assert.equal(h.lastBanner(panel).message, 'Generated diagram update rejected; retaining the last valid revision.\nThe artifact file does not exist. Restore it, or ask the assistant for a new analysis.');
  assert.equal(h.shownRevision(panel), 'r2');
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r2', intent: 'expand', requestId: 'missing-1' });
  await h.waitFor(() => h.results(panel).length === 1, 'refusal result missing');
  assert.equal(vscode.__recorded.messages.at(-1)[1], 'MLView: the artifact file is missing, so there is nothing to refine. Restore it (for example from version control) or ask the assistant for a new analysis.');
  assert.deepEqual(h.results(panel)[0], { v: 1, type: 'actionResult', requestId: 'missing-1', action: 'refineWorkflow', outcome: 'failed', message: 'the artifact file is missing, so there is nothing to refine. Restore it (for example from version control) or ask the assistant for a new analysis.' });
  assert.equal(vscode.__recorded.clipboardWrites.length, 0);
  h.writeJson(artifact, rev('r1', undefined, doc => { doc.title = 'Fresh analysis'; }));
  await h.diskEvent(panel, 'create', artifact);
  assert.equal(h.shownRevision(panel), 'r1');
  assert.equal(h.workflows(panel).at(-1).document.title, 'Fresh analysis');
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('S8: a reformatted artifact (4-space indent, CRLF) refreshes without a banner or re-post', async () => {
  const { panel, artifact } = await open({});
  fs.writeFileSync(artifact, JSON.stringify(rev('r1'), null, 4).replace(/\n/g, '\r\n'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.workflows(panel).length, 1);
  assert.equal(h.lastBanner(panel).message, '');
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('S3: malformed JSON keeps the display, refuses Refine, and undo refreshes it', async () => {
  const { panel, artifact } = await open({});
  const original = fs.readFileSync(artifact);
  fs.writeFileSync(artifact, '{bad');
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['parse']);
  assert.match(h.lastBanner(panel).message, /^Generated diagram update rejected; retaining the last valid revision\.\nJSON parse error: /);
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'explain' });
  await h.waitFor(() => vscode.__recorded.messages.some(m => /cannot be read right now/.test(m[1])), 'parse refusal missing');
  assert.match(vscode.__recorded.messages.at(-1)[1], /^MLView: the artifact file cannot be read right now \(.+\); the MLView helper refuses to publish over it\. Repair or restore run\.mlview\.json first\.$/);
  assert.equal(vscode.__recorded.clipboardWrites.length, 0);
  fs.writeFileSync(artifact, original);
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.workflows(panel).length, 1);
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('an artifact with a byte-order mark fails to parse, like the helper', async () => {
  const { panel } = await open({ raw: String.fromCharCode(0xfeff) + JSON.stringify(rev('r1')) });
  assert.deepEqual(panel.postedTypes(), ['init', 'workflowError']);
  assert.deepEqual(h.lastBanner(panel).codes, ['parse']);
  assert.equal(h.lastBanner(panel).retained, false);
  assert.match(h.lastBanner(panel).message, /^Generated diagram update rejected; nothing valid can be displayed yet\.\nJSON parse error: /);
});

test('S5: a double publish inside one debounce is adopted with a lineage note', async () => {
  const { panel, artifact } = await open({});
  h.writeJson(artifact, rev('r2', 'r1'));
  h.writeJson(artifact, rev('r3', 'r2'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  assert.deepEqual(h.lastBanner(panel).codes, ['lineage']);
  assert.equal(h.lastBanner(panel).message, 'Showing revision r3, which does not directly follow revision r1 last read from the artifact file (for example after a quick second publish or a restore).');
  h.writeJson(artifact, rev('r4', 'r3'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r4');
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('EXT-11: a rejected artifact re-arms on its cited files and adopts once they exist', async () => {
  const document = rev('r1', undefined, doc => {
    doc.evidence[0].file = 'later.py';
    doc.coverage.inspectedFiles = ['later.py'];
  });
  const { panel, root } = await open({ raw: document, files: {} });
  assert.deepEqual(h.lastBanner(panel).codes, ['invalid']);
  assert.match(h.lastBanner(panel).message, /nothing valid can be displayed yet\.\nRevision r1 cannot be displayed:\n\$\.evidence\[0\]\.file: does not exist/);
  fs.writeFileSync(path.join(root, 'later.py'), 'fit()\n');
  await h.diskEvent(panel, 'create', path.join(root, 'later.py'));
  assert.equal(h.shownRevision(panel), 'r1');
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('a transient artifact read error is retried without a disk event', async () => {
  let calls = 0;
  const io = {
    readArtifact: async (fsPath) => (++calls === 1 ? { kind: 'unreadable', detail: 'EBUSY', transient: true } : api.readArtifactFile(fsPath))
  };
  const { panel } = await open({ io });
  assert.deepEqual(panel.postedTypes(), ['init', 'workflowError']);
  assert.deepEqual(h.lastBanner(panel).codes, ['unreadable']);
  assert.equal(h.lastBanner(panel).message, 'Generated diagram update rejected; nothing valid can be displayed yet.\nThe artifact could not be read: EBUSY.');
  await h.waitFor(() => h.shownRevision(panel) === 'r1', 'retry did not adopt the artifact', 3000);
  assert.equal(calls, 2);
  assert.deepEqual(panel.postedTypes().slice(-2), ['workflowError', 'workflow']);
  assert.equal(panel.posted.at(-2).message, '');
});

test('artifact read failures are reported without absolute paths', async () => {
  const { panel, artifact, root } = await open({});
  fs.rmSync(artifact);
  fs.mkdirSync(artifact);
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['unreadable']);
  assert.equal(h.lastBanner(panel).message, 'Generated diagram update rejected; retaining the last valid revision.\nThe artifact could not be read: it is not a regular file.');
  assert.equal(panel.posted.some(m => JSON.stringify(m).includes(root) && m.type !== 'init'), false);
});

// ---- Review round 1 regressions ----

/** An unverified r1 citing fit() in source.py (e) and other() in other.py (e2). */
function twoFileDraft() {
  const doc = rev('r1');
  doc.evidence.push({ id: 'e2', file: 'other.py', line: 1, endLine: 1, quote: 'other()' });
  doc.nodes[0].evidence = ['e', 'e2'];
  doc.coverage.inspectedFiles = ['source.py', 'other.py'];
  return doc;
}
async function jumpOpens(panel, evidenceId) {
  const before = vscode.__recorded.shownDocuments.length;
  const warnings = vscode.__recorded.messages.length;
  panel.fire({ v: 1, type: 'openLocation', evidenceId });
  await h.waitFor(() => vscode.__recorded.shownDocuments.length > before || vscode.__recorded.messages.length > warnings, `jump to ${evidenceId} had no effect`);
  return vscode.__recorded.shownDocuments.length > before;
}

for (const trigger of ['re-Open', 'artifact delete and same-bytes recreate']) {
  test(`LINEAGE1-1: ${trigger} keeps an edited unverified revision stale, not rejected`, async () => {
    const { panel, root, artifact, controller } = await open({ raw: twoFileDraft(), files: { 'source.py': 'fit()\n', 'other.py': 'other()\n' } });
    fs.writeFileSync(path.join(root, 'source.py'), 'train()\n');
    await h.diskEvent(panel, 'change', path.join(root, 'source.py'));
    assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
    if (trigger === 're-Open') {
      await controller.open(vscode.Uri.file(artifact));
    }
    else {
      const bytes = fs.readFileSync(artifact);
      fs.rmSync(artifact);
      await h.diskEvent(panel, 'delete', artifact);
      assert.deepEqual(h.lastBanner(panel).codes, ['missing', 'stale']);
      fs.writeFileSync(artifact, bytes);
      await h.diskEvent(panel, 'create', artifact);
    }
    assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
    assert.equal(await jumpOpens(panel, 'e2'), true, 'a jump into the unchanged other.py opens');
    assert.equal(await jumpOpens(panel, 'e'), false, 'a jump into the edited source.py stays blocked');
    assert.match(vscode.__recorded.messages.at(-1)[1], /^MLView: evidence e cites source\.py, which changed after revision r1 was published; navigation to it is blocked\.$/);
    // The next dependency event must not turn the historical diagram into a rejection.
    fs.writeFileSync(path.join(root, 'other.py'), 'other()\n');
    await h.diskEvent(panel, 'change', path.join(root, 'other.py'));
    assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
  });
}

test('LINEAGE1-1: a deleted cited file keeps its baseline entry across re-Open', async () => {
  const { panel, root, artifact, controller } = await open({ raw: twoFileDraft(), files: { 'source.py': 'fit()\n', 'other.py': 'other()\n' } });
  fs.rmSync(path.join(root, 'source.py'));
  await h.diskEvent(panel, 'delete', path.join(root, 'source.py'));
  assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
  await controller.open(vscode.Uri.file(artifact));
  assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
  assert.equal(await jumpOpens(panel, 'e2'), true);
});

const deeplyNested = (depth) => '{"revision":{"id":"r2","parent":"r1"},"x":' + '['.repeat(depth) + ']'.repeat(depth) + '}';

test('LINEAGE1-2: a deeply nested artifact is a parse error, never a stuck checking status', async () => {
  const { panel, artifact } = await open({});
  fs.writeFileSync(artifact, deeplyNested(20000));
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['parse']);
  assert.equal(h.lastBanner(panel).message, 'Generated diagram update rejected; retaining the last valid revision.\nJSON parse error: the JSON is nested too deeply');
  panel.fire({ v: 1, type: 'refineWorkflow', revisionId: 'r1', intent: 'expand', requestId: 'deep-1' });
  await h.waitFor(() => h.results(panel).length === 1, 'refusal result missing');
  assert.equal(h.results(panel)[0].outcome, 'failed');
  assert.match(h.results(panel)[0].message, /^the artifact file cannot be read right now \(the JSON is nested too deeply\)/);
  assert.equal(vscode.__recorded.clipboardWrites.length, 0);
});

test('LINEAGE1-2: first open of a deeply nested artifact reports it', async () => {
  const { panel } = await open({ raw: deeplyNested(20000) });
  assert.deepEqual(panel.postedTypes(), ['init', 'workflowError']);
  assert.deepEqual(h.lastBanner(panel).codes, ['parse']);
  assert.equal(h.lastBanner(panel).retained, false);
});

test('LINEAGE1-2: an unexpected reload failure clears the checking status', async () => {
  let calls = 0;
  const io = { readArtifact: async (fsPath) => { if (++calls === 2) throw new Error('boom'); return api.readArtifactFile(fsPath); } };
  const { panel, artifact, log } = await open({ io });
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['unreadable']);
  assert.equal(h.lastBanner(panel).message, 'Generated diagram update rejected; retaining the last valid revision.\nThe artifact could not be read: the viewer could not process it.');
  assert.ok(log.lines.some(line => line === 'authored reload failed: boom'));
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('LINEAGE1-3: a helper child of a restored root is adopted, not refused as obsolete', async () => {
  const { panel, artifact } = await open({ raw: rev('r3', 'r2') });
  h.writeJson(artifact, rev('r1', undefined, doc => { doc.title = 'restored root'; }));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r1');
  assert.deepEqual(h.lastBanner(panel).codes, ['lineage']);
  h.writeJson(artifact, rev('r2', 'r1', doc => { doc.title = 'continued from r1'; }));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r2');
  assert.deepEqual(h.lastBanner(panel).codes, []);
});

test('LINEAGE1-4: a disk event restores the transient-retry budget', async () => {
  let busy = false;
  let reads = 0;
  const io = { readArtifact: async (fsPath) => { reads++; return busy ? { kind: 'unreadable', detail: 'EBUSY', transient: true } : api.readArtifactFile(fsPath); } };
  const { panel, artifact } = await open({ io });
  h.writeJson(artifact, rev('r2', 'r1'));
  busy = true;
  vscode.__fireWatcher('change', artifact);
  // The first read and the 250 ms retry both fail; the next retry would wait 1 s.
  await h.waitFor(() => reads === 3, 'first retry did not run', 3000);
  assert.deepEqual(h.lastBanner(panel).codes, ['unreadable']);
  // Another publish arrives while the lock is held; it gets a fresh budget starting at 250 ms
  // (a spent budget would wait 4 s, or never retry once exhausted).
  const before = reads;
  vscode.__fireWatcher('change', artifact);
  await h.waitFor(() => reads === before + 1, 'disk event did not reload', 3000);
  busy = false;
  const start = Date.now();
  await h.waitFor(() => h.shownRevision(panel) === 'r2', 'retry after the disk event did not recover', 1500);
  assert.ok(Date.now() - start < 1500);
  assert.deepEqual(h.lastBanner(panel).codes, []);
});
