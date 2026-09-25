/**
 * Exercise the real authored panel host, its inline bootstrap and the built viewer bundle together
 * (Campaign 1 SPEC §1e and §4.2 step 1; integration-owned).
 *
 * The host is the compiled extension (`vscode-extension/out/test-entry.cjs` over the mock `vscode`
 * module); the page is `panel.webview.html` evaluated in JSDOM with `dist/mlview.js`. Every frame in
 * both directions is recorded, so the assertions cover the wire protocol as the two sides actually
 * speak it: one `ready` per page load, `init` → `workflow` → `workflowError`, one render per
 * later revision, `actionResult` answers, and the fenced refinement prompt.
 */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { JSDOM, VirtualConsole } from 'jsdom';

const require = createRequire(import.meta.url);
const { api, vscode } = require('../../vscode-extension/test/harness.js');
const BUNDLE = readFileSync(new URL('../dist/mlview.js', import.meta.url), 'utf8');
const SOURCE = 'loss()\nstep()\n';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
async function waitFor(predicate, label, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) assert.fail(typeof label === 'function' ? label() : label);
    await sleep(10);
  }
}
const sha256 = (text) => createHash('sha256').update(text).digest('hex');
const plain = (value) => JSON.parse(JSON.stringify(value));

function baseDocument() {
  return {
    workflowVersion: '1.0', title: 'Authored handshake',
    producer: { kind: 'host-llm', host: 'codex' }, revision: { id: 'r1' },
    request: { question: 'Explain the update', scope: 'source.py', entrypoints: ['source.py'], configuration: 'training mode' },
    phases: [{ id: 'loop', label: 'Training' }],
    nodes: [
      { id: 'loss', label: 'Compute loss', phase: 'loop', basis: 'observed', evidence: ['e1'] },
      { id: 'update', label: 'Update weights', phase: 'loop', basis: 'observed', evidence: ['e2'] }
    ],
    edges: [{ id: 'step', source: 'loss', target: 'update', label: 'backward', basis: 'inferred', evidence: ['e2'] }],
    findings: [{ id: 'risk', title: 'Update risk', message: 'Check the update', severity: 'medium', nodeIds: ['update'], edgeIds: ['step'], basis: 'inferred', evidence: ['e2'] }],
    evidence: [
      { id: 'e1', file: 'source.py', line: 1, endLine: 1, quote: 'loss()' },
      { id: 'e2', file: 'source.py', line: 2, endLine: 2, quote: 'step()' }
    ],
    coverage: { status: 'scoped', summary: 'Two statements read', inspectedFiles: ['source.py'], limitations: [] }
  };
}

/** The fenced JSON data block that ends every refinement prompt, parsed. */
function promptData(prompt) {
  const match = /\n```json\n([\s\S]*)\n```$/.exec(prompt);
  assert.ok(match, 'the prompt ends with one fenced JSON data block');
  return JSON.parse(match[1]);
}

/**
 * Open the real host on a fresh realpath'd workspace and wire its `postMessage` to the newest
 * JSDOM page. `wire.hostPosts` records every host → webview frame; each page records its own
 * webview → host frames, its `mountWorkflow` calls and the mounted App's later `setWorkflow` calls.
 */
async function openWire(document, files) {
  vscode.__reset();
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'mlview-authored-wire-')));
  for (const [rel, text] of Object.entries(files)) writeFileSync(join(root, rel), text);
  const artifact = join(root, 'workflow.mlview.json');
  writeFileSync(artifact, JSON.stringify(document));
  vscode.__setWorkspaceFolders([root]);
  const extensionPath = resolve('../vscode-extension');
  const controller = new api.AuthoredDiagramController(
    { extensionPath, extensionUri: vscode.Uri.file(extensionPath), subscriptions: [] },
    { info() {}, warn() {}, error() {}, debug() {}, trace() {}, raw() {}, show() {}, dispose() {} }
  );
  controller.register();
  await controller.open(vscode.Uri.file(artifact));
  const panel = vscode.__recorded.panels.at(-1);
  assert.ok(panel, 'the host opened a webview panel');
  const wire = {
    root, artifact, controller, panel, hostPosts: [], pages: [], state: undefined,
    closeOnOpenLocation: false, closedAtOpenLocation: false,
    /** Called just before a host frame is dispatched into the page. */
    beforeDeliver: undefined
  };
  panel.webview.postMessage = async (message) => {
    wire.hostPosts.push(message);
    const page = wire.pages.at(-1);
    queueMicrotask(() => {
      wire.beforeDeliver?.(message, page);
      page.window.dispatchEvent(new page.window.MessageEvent('message', { data: message }));
    });
    return true;
  };
  return wire;
}

/** Load the panel's HTML as a fresh webview page: the built bundle, then the host's inline bootstrap. */
function mountPage(wire) {
  const dom = new JSDOM(wire.panel.webview.html, {
    runScripts: 'outside-only', pretendToBeVisual: true,
    url: 'https://authored.mlview.test/', virtualConsole: new VirtualConsole()
  });
  const { window } = dom;
  const page = { dom, window, outgoing: [], mounts: [], renders: [], app: undefined };
  wire.pages.push(page);
  window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
  window.matchMedia = (media) => ({ media, matches: false, addEventListener() {}, removeEventListener() {} });
  window.acquireVsCodeApi = () => ({
    postMessage: (message) => {
      page.outgoing.push(message);
      wire.panel.fire(message);
      if (wire.closeOnOpenLocation && message.type === 'openLocation') {
        wire.closeOnOpenLocation = false;
        wire.closedAtOpenLocation = true;
        window.close();
      }
    },
    setState: (value) => { wire.state = value; },
    getState: () => wire.state
  });
  // These are MLView's trusted built bundle and host-generated bootstrap, never target source.
  // Strict eval scopes `var`; a real script element exposes the IIFE global.
  window.eval(BUNDLE + '\nwindow.MLView = MLView;');
  // esbuild's IIFE exports are getter-only, so replace the object before wrapping mountWorkflow.
  window.MLView = { ...window.MLView };
  const mountWorkflow = window.MLView.mountWorkflow;
  window.MLView.mountWorkflow = (root, document, bridge) => {
    page.mounts.push({ revision: document.revision.id, theme: bridge.theme, capabilities: { ...bridge.capabilities } });
    const app = mountWorkflow(root, document, bridge);
    const setWorkflow = app.setWorkflow.bind(app);
    app.setWorkflow = (next, preserve) => {
      page.renders.push(next.revision.id);
      return setWorkflow(next, preserve);
    };
    page.app = app;
    return app;
  };
  const inline = [...window.document.querySelectorAll('script:not([src])')];
  assert.equal(inline.length, 1, 'the panel has exactly one inline bootstrap script');
  window.eval(inline[0].textContent);
  return page;
}

const types = (frames) => frames.map((m) => m.type);
const $ = (page, selector) => page.window.document.querySelector(selector);
const actionResults = (wire, action) => wire.hostPosts.filter((m) => m.type === 'actionResult' && m.action === action);

function assertCsp(html) {
  const csp = /http-equiv="Content-Security-Policy" content="([^"]*)"/.exec(html);
  assert.ok(csp, 'the panel declares a Content-Security-Policy');
  assert.match(csp[1], /^default-src 'none';/);
  assert.doesNotMatch(html, /unsafe-inline|unsafe-eval/);
  const nonce = /'nonce-([^']+)'/.exec(csp[1]);
  assert.ok(nonce, 'scripts are allowed by nonce');
  const scriptNonces = [...html.matchAll(/<script nonce="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(scriptNonces, [nonce[1], nonce[1]], 'both scripts carry the CSP nonce');
}

/** Submit the open composer and wait for the host to copy the prompt and answer `done`. */
async function submitRefine(wire, page, count) {
  const composer = $(page, '.mlv-workflow__composer');
  composer.dispatchEvent(new page.window.Event('submit', { bubbles: true, cancelable: true }));
  await waitFor(() => vscode.__recorded.clipboardWrites.length === count, 'refine frame did not reach the host');
  await waitFor(() => actionResults(wire, 'refineWorkflow').length === count, 'the host did not answer the refine request');
  const result = actionResults(wire, 'refineWorkflow')[count - 1];
  assert.equal(result.outcome, 'done');
  const request = page.outgoing.filter((m) => m.type === 'refineWorkflow').at(-1);
  assert.equal(result.requestId, request.requestId, 'the result answers the request that carried its id');
  await waitFor(() => composer.hidden, 'the composer closes after a done result');
  return vscode.__recorded.clipboardWrites[count - 1];
}

function assertNoLegacyFrames(wire) {
  for (const page of wire.pages) {
    assert.equal(page.outgoing.some((m) => ['requestRefresh', 'askAssistant'].includes(m.type)), false,
      'no requestRefresh or askAssistant frames');
    assert.equal(page.outgoing.some((m) => m.type === 'log' && /workflowError|actionResult/.test(m.message)), false,
      'workflowError and actionResult are known frames, never logged as unknown');
  }
}

export async function authoredHandshake() {
  const document = baseDocument();
  const wire = await openWire(document, { 'source.py': SOURCE });
  try {
    assertCsp(wire.panel.webview.html);
    assert.deepEqual(wire.hostPosts, [], 'the host posts nothing before the page is ready');

    // ── Page load 1: exactly one ready, one init, one workflow, one mount render. ──
    let page = mountPage(wire);
    await waitFor(() => $(page, '[data-node-id="loss"]'), 'authored bootstrap did not mount');
    await sleep(30);
    assert.equal(page.outgoing.filter((m) => m.type === 'ready').length, 1, 'exactly one ready per page load');
    assert.deepEqual(types(wire.hostPosts), ['init', 'workflow'], 'a fresh revision is answered by init then one workflow');
    assert.equal(wire.hostPosts[1].document.revision.id, 'r1');
    assert.equal(page.mounts.length, 1, 'the bootstrap mounts once');
    assert.deepEqual(page.renders, [], 'no render beyond the mount');
    assert.equal(page.mounts[0].theme, wire.hostPosts[0].theme, 'init before the mount sets the theme');
    assert.equal(page.mounts[0].capabilities.canRefine, true, 'init before the mount sets the capabilities');
    assert.equal(page.mounts[0].capabilities.canOpenSource, true);
    assert.equal(wire.state.artifact, wire.artifact, 'the bootstrap saves the artifact path for restore');
    assert.equal($(page, '#mlview-authored-error'), null, 'no banner for a fresh revision');

    // ── Evidence citation opens the cited source through the host. ──
    $(page, '[data-node-id="loss"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    const open = [...page.window.document.querySelectorAll('button')].find((button) => button.textContent === 'Open source.py:1');
    assert.ok(open, 'the inspector offers the evidence link');
    open.click();
    await waitFor(() => vscode.__recorded.shownDocuments.length >= 1,
      () => 'source click lost canOpenSource or evidence identity: ' + JSON.stringify(page.outgoing));
    assert.equal(vscode.__recorded.shownDocuments[0].document.uri.fsPath, join(wire.root, 'source.py'));
    assert.equal(page.outgoing.find((m) => m.type === 'openLocation').evidenceId, 'e1');

    assert.match($(page, '.mlv-workflow__meta').textContent, /Entrypoints: source.py/);
    assert.match($(page, '.mlv-workflow__meta').textContent, /Configuration: training mode/);

    // ── Refine a node (explain): the §1f header and fenced data block. ──
    $(page, '.mlv-workflow__refine').click();
    assert.match($(page, '.mlv-workflow__selection').textContent, /node: loss/);
    $(page, '[data-node-id="update"]').click();
    assert.match($(page, '.mlv-workflow__selection').textContent, /node: loss/,
      'the composer submits the same selection it displays');
    const nodePrompt = await submitRefine(wire, page, 1);
    assert.match(nodePrompt, /^Intent: explain$/m);
    assert.equal(nodePrompt.match(/^Intent:/gm).length, 1, 'exactly one Intent line');
    assert.match(nodePrompt, /^Selected item: node loss$/m);
    assert.match(nodePrompt, /^Published revision on disk: r1\. If you publish, set revision\.parent to r1\.$/m);
    assert.match(nodePrompt, /^Artifact: "workflow\.mlview\.json"$/m);
    assert.doesNotMatch(nodePrompt, /^If you publish:/m, 'explain never publishes');
    assert.match(nodePrompt, /"label": "Compute loss"/);
    const nodeData = promptData(nodePrompt);
    assert.equal(nodeData.selected.kind, 'node');
    assert.equal(nodeData.selected.label, 'Compute loss');
    assert.deepEqual(nodeData.request.entrypoints, ['source.py']);
    assert.equal(nodeData.request.configuration, 'training mode');

    // ── Change the viewport, then hand off to source from an edge: the state is persisted first. ──
    const fitted = plain(page.app.getState().viewport);
    page.window.document.querySelector('button[aria-label="Zoom in"]').click();
    await sleep(20);
    const zoomed = plain(page.app.getState().viewport);
    assert.notDeepEqual(zoomed, fitted, 'the toolbar zoom changed the viewport');
    wire.closeOnOpenLocation = true;
    $(page, '[data-edge-id="step"] .mlv-edge__hit').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    assert.equal(wire.closedAtOpenLocation, true, 'edge activation exercises the immediate source handoff');
    assert.equal(wire.state?.selection?.kind, 'edge', 'the edge selection is persisted before the handoff');
    assert.equal(wire.state?.selection?.id, 'step');
    assert.equal(wire.state?.workflowRevision, 'r1', 'the saved viewport names its revision');
    const saved = plain(wire.state.viewport);
    assert.equal(saved.zoom, zoomed.zoom, 'the zoomed viewport is what was saved');

    // ── Page load 2 (the webview was destroyed): same handshake, selection and viewport restored. ──
    const before = wire.hostPosts.length;
    page = mountPage(wire);
    await waitFor(() => $(page, '[data-edge-id="step"].is-selected'),
      'the remount did not restore the persisted edge selection');
    await sleep(30);
    assert.equal(page.outgoing.filter((m) => m.type === 'ready').length, 1, 'exactly one ready for the new page');
    assert.deepEqual(types(wire.hostPosts.slice(before)), ['init', 'workflow'], 'the host replays init then one workflow');
    assert.equal(page.mounts.length, 1);
    assert.deepEqual(page.renders, []);
    assert.deepEqual(plain(page.app.getState().viewport), saved, 'the remount restores the saved viewport');

    // ── Refine the edge and the finding. ──
    $(page, '.mlv-workflow__refine').click();
    assert.match($(page, '.mlv-workflow__selection').textContent, /edge: step/);
    const edgePrompt = await submitRefine(wire, page, 2);
    assert.match(edgePrompt, /^Selected item: edge step$/m);
    assert.match(edgePrompt, /"source": \{/);
    const edgeData = promptData(edgePrompt);
    assert.equal(edgeData.selected.source.id, 'loss');
    assert.equal(edgeData.selected.target.label, 'Update weights');

    $(page, '.mlv-issue[data-issue-id="risk"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    $(page, '.mlv-workflow__refine').click();
    assert.match($(page, '.mlv-workflow__selection').textContent, /issue: risk/);
    const findingPrompt = await submitRefine(wire, page, 3);
    assert.match(findingPrompt, /^Selected item: finding risk$/m);
    assert.equal(promptData(findingPrompt).selected.title, 'Update risk');

    // ── SVG export: the file is written, and success is announced only after the actionResult. ──
    let announcedBeforeResult;
    wire.beforeDeliver = (message, target) => {
      if (message.type === 'actionResult' && message.action === 'exportFile') announcedBeforeResult = target.app.liveEl.textContent;
    };
    vscode.__answerSaveDialog(vscode.Uri.file(join(wire.root, 'diagram.svg')));
    $(page, '.mlv-btn--exportmenu').click();
    $(page, '[data-export-action="svg"]').click();
    await waitFor(() => vscode.__recorded.writtenFiles.length === 1, 'the SVG frame did not reach the guarded host save');
    assert.match(vscode.__recorded.writtenFiles[0].bytes.toString(), /Authored handshake/);
    await waitFor(() => actionResults(wire, 'exportFile').length === 1, 'the host did not answer the export');
    const exportResult = actionResults(wire, 'exportFile')[0];
    assert.equal(exportResult.outcome, 'done');
    assert.equal(exportResult.name, 'diagram.svg');
    assert.equal(exportResult.requestId, page.outgoing.find((m) => m.type === 'exportFile').requestId);
    await waitFor(() => /^Exported \d+ cards and \d+ connections as diagram\.svg\.$/.test(page.app.liveEl.textContent),
      () => 'export success was not announced: ' + JSON.stringify(page.app.liveEl.textContent));
    assert.equal(announcedBeforeResult, 'Saving SVG…', 'no success text before the actionResult');
    wire.beforeDeliver = undefined;

    // ── A later revision arrives through the file watcher: one workflow frame, one render. ──
    const next = { ...baseDocument(), title: 'Refined explanation', revision: { id: 'r2', parent: 'r1' } };
    writeFileSync(wire.artifact, JSON.stringify(next));
    const beforeR2 = wire.hostPosts.length;
    vscode.__fireWatcher('change', wire.artifact);
    await waitFor(() => $(page, '[data-workflow-revision="r2"]'), 'the new revision did not render');
    await sleep(200);
    const r2Frames = wire.hostPosts.slice(beforeR2);
    assert.equal(r2Frames.filter((m) => m.type === 'workflow').length, 1, 'the host posts exactly one workflow for r2');
    const r2Index = r2Frames.findIndex((m) => m.type === 'workflow');
    assert.equal(r2Frames[r2Index - 1]?.type, 'workflowError', 'the banner is cleared before the new workflow');
    assert.equal(r2Frames[r2Index - 1].message, '');
    assert.deepEqual(page.renders, ['r2'], 'exactly one setWorkflow call for the r2 frame');
    assert.equal(page.mounts.length, 1, 'the later workflow does not remount');
    assert.equal($(page, '#mlview-authored-error'), null, 'no banner after a fresh adoption');
    assert.equal(page.window.document.querySelector('.mlv-workflow__title').textContent, 'Refined explanation');

    assertNoLegacyFrames(wire);
    process.stdout.write('  PASS  authored bootstrap → citation → refine (node, edge, finding) → remount → SVG → watched revision\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}

/** A verified revision whose cited source changed after publication shows the historical banner. */
export async function authoredStaleHandshake() {
  const document = { ...baseDocument(), verification: { files: { 'source.py': sha256(SOURCE) }, publishedAt: '2026-09-25T00:00:00Z' } };
  const edited = SOURCE + '# edited after publication\n';
  const wire = await openWire(document, { 'source.py': edited });
  try {
    const page = mountPage(wire);
    await waitFor(() => $(page, '[data-node-id="loss"]') && $(page, '#mlview-authored-error'),
      'the stale revision did not mount with its banner');
    await sleep(30);
    assert.equal(page.outgoing.filter((m) => m.type === 'ready').length, 1);
    assert.deepEqual(types(wire.hostPosts), ['init', 'workflow', 'workflowError'], 'the banner follows the workflow');
    assert.deepEqual(wire.hostPosts[2].codes, ['stale']);
    assert.equal(wire.hostPosts[2].retained, true);
    assert.equal(page.mounts.length, 1);
    const root = page.window.document.getElementById('mlview-root');
    const banner = $(page, '#mlview-authored-error');
    assert.equal(banner.parentElement, root, 'the banner sits inside the mounted root');
    assert.ok(root.querySelector('[data-node-id="loss"]'), 'the historical diagram stays visible under the banner');
    assert.equal(banner.getAttribute('role'), 'status');
    assert.match(banner.textContent, /historical diagram is visible/);
    assert.match(banner.textContent, /source\.py/);

    // A disk change updates the banner to the checking status; a fresh child revision removes it.
    const child = { ...baseDocument(), title: 'Fresh child', revision: { id: 'r2', parent: 'r1' } };
    writeFileSync(wire.artifact, JSON.stringify(child));
    vscode.__fireWatcher('change', wire.artifact);
    await sleep(0);
    assert.match($(page, '#mlview-authored-error')?.textContent || '', /checking diagram freshness/,
      'the banner updates while the change is checked');
    await waitFor(() => $(page, '[data-workflow-revision="r2"]'), 'the fresh child revision did not render');
    await waitFor(() => $(page, '#mlview-authored-error') === null, 'the banner was not removed after a fresh adoption');
    await sleep(50);
    assert.deepEqual(page.renders, ['r2']);
    assert.equal(page.mounts.length, 1);
    assertNoLegacyFrames(wire);
    process.stdout.write('  PASS  stale verified revision → historical banner in the mounted root → cleared by a fresh child\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}
