/** Exercise the real authored panel bootstrap and viewer bundle together. */
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { JSDOM, VirtualConsole } from 'jsdom';

const require = createRequire(import.meta.url);
const { api, vscode } = require('../../vscode-extension/test/harness.js');
const waitFor = async (predicate, label) => {
  for (let i = 0; i < 150; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.fail(label);
};

export async function authoredHandshake() {
  vscode.__reset();
  const root = mkdtempSync(join(tmpdir(), 'mlview-authored-wire-'));
  const extensionPath = resolve('../vscode-extension');
  const artifact = join(root, 'workflow.mlview.json');
  const document = {
    workflowVersion: '1.0', title: 'Authored handshake',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'Explain the update', scope: 'source.py' },
    phases: [{ id: 'loop', label: 'Training' }],
    nodes: [
      { id: 'loss', label: 'Compute loss', phase: 'loop', basis: 'observed', evidence: ['e1'] },
      { id: 'update', label: 'Update weights', phase: 'loop', basis: 'observed', evidence: ['e2'] }
    ],
    edges: [{ id: 'step', source: 'loss', target: 'update', label: 'backward', basis: 'inferred', evidence: ['e2'] }],
    findings: [], evidence: [
      { id: 'e1', file: 'source.py', line: 1, endLine: 1, quote: 'loss()' },
      { id: 'e2', file: 'source.py', line: 2, endLine: 2, quote: 'step()' }
    ],
    coverage: { status: 'scoped', summary: 'Two statements read', inspectedFiles: ['source.py'], limitations: [] }
  };
  writeFileSync(join(root, 'source.py'), 'loss()\nstep()\n');
  writeFileSync(artifact, JSON.stringify(document));
  vscode.__setWorkspaceFolders([root]);
  const controller = new api.AuthoredDiagramController(
    { extensionPath, extensionUri: vscode.Uri.file(extensionPath), subscriptions: [] },
    { info() {}, warn() {}, error() {}, dispose() {} }
  );
  controller.register();
  let dom;
  try {
    await controller.open(vscode.Uri.file(artifact));
    const panel = vscode.__recorded.panels.at(-1);
    const console = new VirtualConsole();
    dom = new JSDOM(panel.webview.html, {
      runScripts: 'outside-only', pretendToBeVisual: true,
      url: 'https://authored.mlview.test/', virtualConsole: console
    });
    const { window } = dom;
    window.structuredClone = value => JSON.parse(JSON.stringify(value));
    window.matchMedia = media => ({ media, matches: false, addEventListener() {}, removeEventListener() {} });
    let state;
    const outgoing = [];
    window.acquireVsCodeApi = () => ({
      postMessage: message => { outgoing.push(message); panel.fire(message); },
      setState: value => { state = value; }, getState: () => state
    });
    panel.webview.postMessage = async message => {
      queueMicrotask(() => window.dispatchEvent(new window.MessageEvent('message', { data: message })));
      return true;
    };
    // These are MLView's trusted built bundle and generated bootstrap, never target source.
    // Strict eval scopes `var`; a real script element exposes the IIFE global.
    window.eval(readFileSync(new URL('../dist/mlview.js', import.meta.url), 'utf8') + '\nwindow.MLView = MLView;');
    for (const script of window.document.querySelectorAll('script:not([src])')) window.eval(script.textContent);
    await waitFor(() => window.document.querySelector('[data-node-id="loss"]'), 'authored bootstrap did not mount');
    await new Promise(resolve => setTimeout(resolve, 30)); // settle the mount's second ready/init handshake
    assert.equal(state.artifact, artifact);

    window.document.querySelector('[data-node-id="loss"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const open = [...window.document.querySelectorAll('button')].find(button => button.textContent === 'Open source.py:1');
    assert.ok(open, 'real inspector offers the evidence link');
    open.click();
    await waitFor(() => vscode.__recorded.shownDocuments.length >= 1,
      'real source click lost canOpenSource or evidence identity: ' + JSON.stringify(outgoing));
    assert.equal(vscode.__recorded.shownDocuments[0].document.uri.fsPath, join(root, 'source.py'));

    window.document.querySelector('.mlv-workflow__refine').click();
    await waitFor(() => vscode.__recorded.clipboardWrites.length === 1, 'refine frame did not reach host');
    assert.match(vscode.__recorded.clipboardWrites[0], /parent is r1/);

    vscode.__answerSaveDialog(vscode.Uri.file(join(root, 'diagram.svg')));
    window.document.querySelector('.mlv-btn--exportmenu').click();
    window.document.querySelector('[data-export-action="svg"]').click();
    await waitFor(() => vscode.__recorded.writtenFiles.length === 1, 'real SVG frame did not reach guarded host save');
    assert.match(vscode.__recorded.writtenFiles[0].bytes.toString(), /Authored handshake/);

    const next = { ...document, title: 'Refined explanation', revision: { id: 'r2', parent: 'r1' } };
    writeFileSync(artifact, JSON.stringify(next));
    await controller.open(vscode.Uri.file(artifact));
    await waitFor(() => window.document.querySelector('[data-workflow-revision="r2"]'), 'new revision did not render');
    assert.equal(outgoing.some(message => ['requestRefresh', 'askAssistant'].includes(message.type)), false);
    process.stdout.write('  PASS  authored bootstrap → node citation → refinement → SVG → revision\n');
  } finally {
    controller.dispose();
    dom?.window.close();
    rmSync(root, { recursive: true, force: true });
  }
}
