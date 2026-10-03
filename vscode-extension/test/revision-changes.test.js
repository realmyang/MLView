'use strict';
/**
 * Viewer M4, roadmap step 16 (host side): the panel keeps the valid revision it showed and posts
 * it with the next `workflow` frame as `previous`, only when the new revision names it as its
 * parent; otherwise the frame carries `replaced`, the id of the revision it replaced. Memory only:
 * a new page gets the comparison again, a new panel has none. Every reload is driven the way helper
 * publications arrive (a watcher event). Mock `vscode` tests only, not a live VS Code check.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const h = require('./panel-helpers');
const { api } = h;

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
const lastFrame = (panel) => h.workflows(panel).at(-1);
/** What a frame compares with: the previous revision's id, or `replaced:<id>`, or 'none'. */
const comparison = (frame) => (frame.previous ? frame.previous.revision.id : frame.replaced ? 'replaced:' + frame.replaced : 'none');

test('nextComparison: a child of the shown revision compares with it; another revision records only what it replaced; the same revision keeps what it had', () => {
  const doc = (id, parent) => ({ revision: parent ? { id, parent } : { id } });
  const r1 = doc('r1');
  const r2 = doc('r2', 'r1');
  assert.deepEqual(api.nextComparison({}, undefined, r1), {}, 'a first revision compares with nothing');
  assert.deepEqual(api.nextComparison({}, undefined, r2), {}, 'even when it names a parent the panel never showed');
  assert.equal(api.nextComparison({}, r1, r2).previous, r1, 'the very document the panel showed');
  assert.deepEqual(api.nextComparison({ previous: r1 }, r2, doc('r3', 'r9')), { replaced: 'r2' });
  assert.deepEqual(api.nextComparison({ previous: r1 }, r2, doc('r3')), { replaced: 'r2' }, 'no parent: does not follow');
  // The same revision again (a reopen, a file read again): the comparison stays while it still fits.
  assert.equal(api.nextComparison({ previous: r1 }, r2, doc('r2', 'r1')).previous, r1);
  assert.deepEqual(api.nextComparison({ previous: r1 }, r2, doc('r2', 'r0')), {});
  assert.deepEqual(api.nextComparison({ replaced: 'r1' }, doc('r3', 'r9'), doc('r3', 'r9')), { replaced: 'r1' });
  assert.deepEqual(api.nextComparison({ replaced: 'r1' }, doc('r3', 'r1'), doc('r3', 'r1')), {}, 'never "replaced" by its own parent');
  assert.deepEqual(api.nextComparison({}, r1, doc('r1')), {});
});

test('the panel posts the previous revision with its child, again for a new page, and keeps it through a refresh', async () => {
  const { panel, artifact } = await open({});
  assert.equal(comparison(lastFrame(panel)), 'none', 'a first revision carries no comparison');
  const r2 = rev('r2', 'r1', doc => { doc.nodes[0].label = 'Fit the model'; });
  h.writeJson(artifact, r2);
  await h.diskEvent(panel, 'change', artifact);
  const frame = lastFrame(panel);
  assert.equal(frame.document.revision.id, 'r2');
  assert.equal(comparison(frame), 'r1');
  assert.equal(frame.replaced, undefined);
  assert.equal(frame.previous.nodes[0].label, 'Fit', 'the whole previous document, as validated');
  assert.equal(frame.previous.title, 'Authored');
  // VS Code rebuilt the page: its first frame carries the comparison again.
  const before = h.workflows(panel).length;
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.equal(h.workflows(panel).length, before + 1);
  assert.equal(comparison(lastFrame(panel)), 'r1');
  // The same revision published with source hashes (a refresh): re-posted, still compared.
  h.writeJson(artifact, h.verify(rev('r2', 'r1', doc => { doc.nodes[0].label = 'Fit the model'; }), { 'source.py': 'fit()\n' }));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.workflows(panel).length, before + 2, 'the refresh re-posts once');
  assert.ok(lastFrame(panel).document.verification);
  assert.equal(comparison(lastFrame(panel)), 'r1');
  // The next child compares with r2 only.
  h.writeJson(artifact, rev('r3', 'r2'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(comparison(lastFrame(panel)), 'r2');
  assert.equal(lastFrame(panel).previous.nodes[0].label, 'Fit the model');
});

test('a revision that does not follow the shown one is posted with "replaced", never with a previous document', async () => {
  const { panel, artifact } = await open({});
  h.writeJson(artifact, rev('r3', 'r9'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  assert.equal(comparison(lastFrame(panel)), 'replaced:r1');
  assert.equal(lastFrame(panel).previous, undefined);
  // A child of r3 compares with r3 again.
  h.writeJson(artifact, rev('r4', 'r3'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(comparison(lastFrame(panel)), 'r3');
  // A revision with no parent at all does not follow either.
  h.writeJson(artifact, rev('r5'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(comparison(lastFrame(panel)), 'replaced:r4');
});

test('a rejected revision is never a comparison: its valid child replaced the shown revision without following it', async () => {
  const { panel, artifact } = await open({});
  h.writeJson(artifact, rev('r2', 'r1', doc => { doc.nodes[0].parent = null; }));
  await h.diskEvent(panel, 'change', artifact);
  assert.deepEqual(h.lastBanner(panel).codes, ['invalid']);
  assert.equal(h.shownRevision(panel), 'r1');
  h.writeJson(artifact, rev('r3', 'r2'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(h.shownRevision(panel), 'r3');
  assert.equal(comparison(lastFrame(panel)), 'replaced:r1', 'r3 follows r2, which this panel never showed');
});

test('Open Generated Diagram on the open panel keeps the comparison; a new panel starts with none', async () => {
  const fixture = await open({});
  const { panel, artifact, controller } = fixture;
  h.writeJson(artifact, rev('r2', 'r1'));
  await h.diskEvent(panel, 'change', artifact);
  assert.equal(comparison(lastFrame(panel)), 'r1');
  const before = h.workflows(panel).length;
  await controller.open(h.vscode.Uri.file(artifact));
  await h.waitFor(() => h.workflows(panel).length > before, 'the reopen did not post the revision');
  assert.equal(lastFrame(panel).document.revision.id, 'r2');
  assert.equal(comparison(lastFrame(panel)), 'r1', 'the same panel still compares r2 with r1');
  // A new panel (a window reload revives it as a new one) has seen only r2.
  controller.dispose();
  const next = await open({ root: fixture.root, raw: JSON.parse(fs.readFileSync(artifact, 'utf8')), files: { 'source.py': 'fit()\n' } });
  assert.equal(next.panel === panel, false);
  assert.equal(lastFrame(next.panel).document.revision.id, 'r2');
  assert.equal(comparison(lastFrame(next.panel)), 'none');
});
