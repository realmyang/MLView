'use strict';
/**
 * Shared helpers for the panel-level tests (not a test file itself: tools/run-tests.mjs only
 * runs `*.test.js`).
 */
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { api, vscode } = require('./harness');

const tick = () => new Promise((resolve) => setImmediate(resolve));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function waitFor(predicate, message, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) assert.fail(message);
    await sleep(10);
  }
}
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
/** A temporary root that is already its own realpath, so macOS (/var -> /private/var) exercises identity lookups. */
function tempRoot(prefix) {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
}
function context() {
  const extensionPath = path.join(__dirname, '..');
  return { extensionPath, extensionUri: vscode.Uri.file(extensionPath), subscriptions: [] };
}
function log() {
  const lines = [];
  return { lines, info() {}, warn(m) { lines.push(m); }, error() {}, debug() {}, trace() {}, raw() {}, show() {}, dispose() {} };
}
/** A small valid document citing `fit()` on line 1 of `file`. */
function workflow(file = 'source.py', revision = { id: 'r1' }) {
  return {
    workflowVersion: '1.0', title: 'Authored', producer: { kind: 'host-llm', host: 'codex' }, revision,
    request: { question: 'Explain training', scope: 'training', entrypoints: ['train.py'], configuration: 'config=fast' },
    phases: [{ id: 'p', label: 'Train' }],
    nodes: [{ id: 'n', label: 'Fit', phase: 'p', basis: 'observed', evidence: ['e'] }, { id: 'out', label: 'Weights', phase: 'p', basis: 'unresolved', evidence: [] }],
    edges: [{ id: 'flow', source: 'n', target: 'out', label: 'produces', basis: 'inferred', evidence: ['e'] }],
    findings: [{ id: 'risk', title: 'Unverified output', message: 'Output needs checking', severity: 'medium', nodeIds: ['out'], edgeIds: ['flow'], basis: 'inferred', evidence: ['e'], counterEvidence: [] }],
    evidence: [{ id: 'e', file, line: 1, endLine: 1, quote: 'fit()' }],
    coverage: { status: 'scoped', summary: 'source', inspectedFiles: [file], limitations: [] }
  };
}
function verify(doc, files) {
  doc.verification = { files: Object.fromEntries(Object.entries(files).map(([rel, text]) => [rel, sha256(text)])), publishedAt: '2026-09-16T12:00:00Z' };
  return doc;
}
const banners = (panel) => panel.posted.filter((m) => m.type === 'workflowError');
const lastBanner = (panel) => banners(panel).at(-1) || { message: '', codes: [] };
const workflows = (panel) => panel.posted.filter((m) => m.type === 'workflow');
const shownRevision = (panel) => workflows(panel).at(-1)?.document.revision.id;
const results = (panel) => panel.posted.filter((m) => m.type === 'actionResult');

/**
 * Open a panel on a fresh realpath'd workspace. `files` maps rel -> text (default source.py = "fit()\n");
 * `raw` is the artifact document (object or string).
 */
async function openPanel(options = {}) {
  vscode.__reset();
  const root = options.root || tempRoot(options.prefix || 'mlview-panel-');
  const files = options.files || { 'source.py': 'fit()\n' };
  for (const [rel, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  }
  const artifact = path.join(root, options.artifactName || 'run.mlview.json');
  const raw = options.raw === undefined ? workflow() : options.raw;
  fs.writeFileSync(artifact, typeof raw === 'string' ? raw : JSON.stringify(raw));
  vscode.__setWorkspaceFolders([options.folder || root]);
  const logger = log();
  const controller = new api.AuthoredDiagramController(context(), logger, options.validator, options.io);
  controller.register();
  await controller.open(vscode.Uri.file(options.openPath || artifact));
  const panel = vscode.__recorded.panels.at(-1);
  if (panel && options.ready !== false) {
    panel.fire({ v: 1, type: 'ready' });
    await tick();
  }
  return { root, artifact, controller, panel, log: logger };
}
/** Fire one watcher event and wait until the resulting reload has settled (the checking banner is replaced). */
async function diskEvent(panel, kind, file, label = 'reload did not settle') {
  vscode.__fireWatcher(kind, file);
  await waitFor(() => (lastBanner(panel).codes || [])[0] !== 'checking', label);
  await tick();
}
function writeJson(file, value) {
  fs.writeFileSync(file, JSON.stringify(value));
}
/** The fenced JSON data block of a refinement prompt, parsed. */
function promptData(prompt) {
  const match = /\n```json\n([\s\S]*)\n```$/.exec(prompt);
  assert.ok(match, 'prompt ends with one fenced JSON block');
  return JSON.parse(match[1]);
}
function cleanup(fixtures) {
  for (const fixture of fixtures.splice(0)) {
    try { fixture.controller?.dispose(); } finally { if (fixture.root) fs.rmSync(fixture.root, { recursive: true, force: true }); }
  }
}

module.exports = {
  api, vscode, tick, sleep, waitFor, sha256, tempRoot, context, log, workflow, verify,
  banners, lastBanner, workflows, shownRevision, results, openPanel, diskEvent, writeJson, promptData, cleanup
};
