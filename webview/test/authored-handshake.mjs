/**
 * Exercise the real authored panel host, its inline bootstrap and the built viewer bundle together
 * (Campaign 1 SPEC §1e and §4.2 step 1; integration-owned).
 *
 * The host is the compiled extension (`vscode-extension/out/test-entry.cjs` over the mock `vscode`
 * module); the page is `panel.webview.html` evaluated in JSDOM with `dist/mlview.js`. Every frame in
 * both directions is recorded, so the assertions cover the wire protocol as the two sides actually
 * speak it: one `ready` per page load, `init` → `workflow` → `stale` → `workflowError`, one render
 * per later revision, `actionResult` answers, and the fenced refinement prompt.
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

/**
 * Load the panel's HTML as a fresh webview page: the built bundle, then the host's inline bootstrap.
 * `beforeScripts(window)` runs first, the way VS Code's webview host attaches its own listeners to
 * the page's window before the page's scripts run.
 */
function mountPage(wire, beforeScripts) {
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
  if (beforeScripts) beforeScripts(window);
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
    // Viewer M1: a click on the card only selects it; the Selection pane's Open link opens the source.
    // Viewer M2: the link says Open; its accessible name says what.
    $(page, '[data-node-id="loss"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    await sleep(20);
    assert.equal(page.outgoing.some((m) => m.type === 'openLocation'), false, 'a card click selects without opening');
    const open = [...page.window.document.querySelectorAll('button')].find((button) => button.getAttribute('aria-label') === 'Open source.py:1');
    assert.ok(open, 'the Selection pane offers the evidence link');
    open.click();
    await waitFor(() => vscode.__recorded.shownDocuments.length >= 1,
      () => 'source click lost canOpenSource or evidence identity: ' + JSON.stringify(page.outgoing));
    assert.equal(vscode.__recorded.shownDocuments[0].document.uri.fsPath, join(wire.root, 'source.py'));
    assert.equal(page.outgoing.find((m) => m.type === 'openLocation').evidenceId, 'e1');
    assert.equal(page.outgoing.find((m) => m.type === 'openLocation').focus, undefined, 'an Open link keeps focus in the diagram');
    assert.equal(vscode.__recorded.shownDocuments[0].options.preserveFocus, true, 'the host opens beside without taking focus');

    // Viewer M2: the request's scope and configuration are in About.
    $(page, '.mlv-rail__tab[data-tab="about"]').click();
    assert.match($(page, '.mlv-about [data-about="scope"]').textContent, /Entrypoints: source.py/);
    assert.match($(page, '.mlv-about [data-about="config"]').textContent, /training mode/);

    // ── Refine a node (explain): the §1f header and fenced data block. ──
    $(page, '.mlv-workflow__refine').click();
    // Viewer M2: the composer names its target by label; the stable id stays on the attribute.
    assert.equal($(page, '.mlv-workflow__selection').textContent, 'Step: Compute loss');
    assert.equal($(page, '.mlv-workflow__composer').getAttribute('data-selection-id'), 'loss');
    $(page, '[data-node-id="update"]').click();
    assert.equal($(page, '.mlv-workflow__selection').textContent, 'Step: Compute loss',
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
    // Viewer M1 (updated deliberately): a click on a connection selects it; the handoff is the
    // double-click (or Enter), which selects and opens the cited source beside the panel.
    const fitted = plain(page.app.getState().viewport);
    page.window.document.querySelector('.mlv-status button[aria-label="Zoom in"]').click();
    await sleep(20);
    const zoomed = plain(page.app.getState().viewport);
    assert.notDeepEqual(zoomed, fitted, 'the status bar zoom changed the viewport');
    wire.closeOnOpenLocation = true;
    $(page, '[data-edge-id="step"] .mlv-edge__hit').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    assert.equal(wire.closedAtOpenLocation, false, 'a connection click selects without opening');
    $(page, '[data-edge-id="step"] .mlv-edge__hit').dispatchEvent(new page.window.MouseEvent('dblclick', { bubbles: true }));
    assert.equal(wire.closedAtOpenLocation, true, 'edge double-click exercises the immediate source handoff');
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
    assert.equal($(page, '.mlv-workflow__selection').textContent, 'Connection: backward');
    const edgePrompt = await submitRefine(wire, page, 2);
    assert.match(edgePrompt, /^Selected item: edge step$/m);
    assert.match(edgePrompt, /"source": \{/);
    const edgeData = promptData(edgePrompt);
    assert.equal(edgeData.selected.source.id, 'loss');
    assert.equal(edgeData.selected.target.label, 'Update weights');

    // The remount restored the Selection tab saved with r1; the finding is picked from Findings.
    assert.equal(page.app.getState().railTab, 'inspector', 'the remount restores the reader\'s tab for the same revision');
    $(page, '.mlv-rail__tab[data-tab="issues"]').click();
    $(page, '.mlv-issue[data-issue-id="risk"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
    $(page, '.mlv-workflow__refine').click();
    assert.equal($(page, '.mlv-workflow__selection').textContent, 'Finding: F1 · Update risk');
    const findingPrompt = await submitRefine(wire, page, 3);
    assert.match(findingPrompt, /^Selected item: finding risk$/m);
    assert.equal(promptData(findingPrompt).selected.title, 'Update risk');

    // ── SVG export: the file is written, and success is announced only after the actionResult. ──
    let announcedBeforeResult;
    wire.beforeDeliver = (message, target) => {
      if (message.type === 'actionResult' && message.action === 'exportFile') announcedBeforeResult = target.app.liveEl.textContent;
    };
    vscode.__answerSaveDialog(vscode.Uri.file(join(wire.root, 'diagram.svg')));
    $(page, '.mlv-btn--more').click();
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
    assert.equal(page.window.document.querySelector('.mlv-header__title').textContent, 'Refined explanation');

    assertNoLegacyFrames(wire);
    process.stdout.write('  PASS  authored bootstrap → citation → refine (node, edge, finding) → remount → SVG → watched revision\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}

/**
 * A verified revision whose cited source changed after publication shows the historical notice.
 * Viewer M1 (updated deliberately): after the mount the host's banner is drawn by the viewer as
 * `.mlv-hostnotice` under the header instead of the bootstrap's `<pre>`, the host's `stale` frame
 * marks the cards that cite the file, and the checking status goes to the status bar.
 */
export async function authoredStaleHandshake() {
  const document = { ...baseDocument(), verification: { files: { 'source.py': sha256(SOURCE) }, publishedAt: '2026-09-25T00:00:00Z' } };
  const edited = SOURCE + '# edited after publication\n';
  const wire = await openWire(document, { 'source.py': edited });
  try {
    const page = mountPage(wire);
    const notice = () => $(page, '.mlv-hostnotice');
    await waitFor(() => $(page, '[data-node-id="loss"]') && notice() && !notice().hidden,
      'the stale revision did not mount with its notice');
    await sleep(30);
    assert.equal(page.outgoing.filter((m) => m.type === 'ready').length, 1);
    assert.deepEqual(types(wire.hostPosts), ['init', 'workflow', 'stale', 'workflowError'],
      'the stale files and then the banner follow the workflow');
    assert.deepEqual(wire.hostPosts[2].files, [{ path: 'source.py', reason: 'changed' }]);
    assert.deepEqual(wire.hostPosts[3].codes, ['stale']);
    assert.equal(wire.hostPosts[3].retained, true);
    assert.equal(page.mounts.length, 1);
    const root = page.window.document.getElementById('mlview-root');
    assert.equal($(page, '#mlview-authored-error'), null, 'no bootstrap <pre> once the viewer is mounted');
    assert.ok(root.contains(notice()), 'the notice sits inside the mounted root');
    assert.ok(root.querySelector('[data-node-id="loss"]'), 'the historical diagram stays visible under the notice');
    assert.equal(notice().getAttribute('role'), 'status');
    assert.match(notice().className, /mlv-hostnotice--warn/);
    assert.match(notice().textContent, /historical diagram is visible/);
    assert.match(notice().textContent, /source\.py/);
    assert.ok($(page, '[data-node-id="loss"]').classList.contains('is-stale'), 'the card citing the changed file is marked');
    assert.ok($(page, '[data-edge-id="step"]').classList.contains('is-stale'), 'the connection citing it is marked');
    assert.match($(page, '[data-freshness="stale"]')?.textContent || '', /1 of 1 cited files changed/);

    // A disk change shows the checking status in the status bar and leaves the notice as it was;
    // a fresh child revision removes the notice and the marks.
    const child = { ...baseDocument(), title: 'Fresh child', revision: { id: 'r2', parent: 'r1' } };
    writeFileSync(wire.artifact, JSON.stringify(child));
    vscode.__fireWatcher('change', wire.artifact);
    await sleep(0);
    assert.match($(page, '[data-freshness="checking"]')?.textContent || '', /Checking source freshness/,
      'the status bar says the change is being checked');
    assert.equal(notice().hidden, false, 'the notice does not jump while the change is checked');
    await waitFor(() => $(page, '[data-workflow-revision="r2"]'), 'the fresh child revision did not render');
    await waitFor(() => notice().hidden, 'the notice was not hidden after a fresh adoption');
    await waitFor(() => !$(page, '[data-freshness="stale"]') && !$(page, '[data-freshness="checking"]'),
      'the status bar still shows a freshness warning after a fresh adoption');
    // Viewer M2: the fresh child carries no hashes, so the status bar says so in muted words.
    assert.equal($(page, '[data-freshness="unverified"]')?.textContent, 'Freshness not checked');
    assert.equal($(page, '.mlv-node.is-stale'), null, 'no stale marks after a fresh adoption');
    assert.equal($(page, '#mlview-authored-error'), null);
    await sleep(50);
    assert.deepEqual(page.renders, ['r2']);
    assert.equal(page.mounts.length, 1);
    assertNoLegacyFrames(wire);
    process.stdout.write('  PASS  stale verified revision → notice and marks in the mounted root → cleared by a fresh child\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}

/**
 * Viewer M3: one Escape, one action. VS Code's webview host forwards every keydown to the
 * workbench from a listener on the page's window, attached before the page's scripts run (checked
 * live with DOMDebugger.getEventListeners in VS Code 1.139), and the workbench runs any Escape
 * keybinding that matches (MEASURED live: one Escape on a card collapsed the bottom sheet and also
 * dismissed a VS Code notification). The page here is the real host bootstrap plus the built
 * viewer, with a stand-in forwarder attached first, as VS Code's is. An Escape the viewer acted on
 * never reaches it; an Escape with nothing left to dismiss does, and so does every other key.
 */
export async function authoredEscapeHandshake() {
  const wire = await openWire(baseDocument(), { 'source.py': SOURCE });
  try {
    const forwarded = [];
    const page = mountPage(wire, (win) => win.addEventListener('keydown', (ev) => forwarded.push(ev.key)));
    await waitFor(() => $(page, '[data-node-id="loss"]'), 'the viewer did not mount');
    const { window } = page;
    const press = (target, key) => {
      const event = new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event;
    };
    const card = $(page, '[data-node-id="loss"]');
    card.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
    await waitFor(() => page.app.selection && page.app.selection.id === 'loss', 'the click did not select the card');
    card.focus();
    assert.equal(window.document.activeElement, card);

    press(card, 'l');
    assert.equal(page.app.legendOpen, true, 'l opened the legend');
    assert.deepEqual(forwarded, ['l'], 'a key other than Escape still reaches VS Code');

    let event = press(card, 'Escape');
    assert.equal(page.app.legendOpen, false, 'Escape closed the legend');
    assert.equal(event.defaultPrevented, true);
    event = press(card, 'Escape');
    assert.equal(page.app.selection, null, 'the next Escape cleared the selection');
    assert.deepEqual(forwarded, ['l'], 'neither Escape the viewer used reached VS Code');

    // Escape in the search box clears it and returns to the diagram; VS Code does not see it either.
    const search = $(page, 'input[type="search"]');
    search.focus();
    search.value = 'loss';
    search.dispatchEvent(new window.Event('input', { bubbles: true }));
    event = press(search, 'Escape');
    assert.equal(event.defaultPrevented, true, 'the search box used the Escape');
    assert.equal(search.value, '', 'and cleared the query');
    assert.deepEqual(forwarded, ['l'], 'the search box Escape did not reach VS Code');

    // Nothing open, nothing selected and the focus off the canvas: nothing left for the viewer.
    window.document.activeElement.blur();
    event = press(window.document.body, 'Escape');
    assert.equal(event.defaultPrevented, false, 'an Escape with nothing to dismiss is left unconsumed');
    assert.deepEqual(forwarded, ['l', 'Escape'], 'and it reaches VS Code');
    process.stdout.write('  PASS  an Escape the viewer used stops at the page; one with nothing to dismiss reaches VS Code\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}

/**
 * Viewer M3, roadmap steps 11 and 12 together: the review walk in the built viewer driving the
 * real host. `r` on the diagram starts the walk on the claims not observed; after the pause each
 * step's quote is opened beside the panel with the focus kept on the diagram and its lines
 * highlighted; a claim with no quotes clears the highlight; one Escape ends the walk, clears the
 * highlight and does not reach VS Code. On a stale revision, the notice's "Review affected claims"
 * walks the claims citing the changed file: the host answers blocked, opens nothing and raises no
 * notification, and the viewer shows the host's reason. Mock `vscode` and JSDOM: not a live check.
 */
export async function authoredWalkHandshake() {
  const walkDocument = () => {
    const document = baseDocument();
    document.nodes.push({ id: 'save', label: 'Save checkpoint', phase: 'loop', basis: 'unresolved', evidence: [] });
    document.edges.push({ id: 'persist', source: 'update', target: 'save', label: 'weights', basis: 'observed', evidence: ['e2'] });
    return { ...document, verification: { files: { 'source.py': sha256(SOURCE) }, publishedAt: '2026-09-25T00:00:00Z' } };
  };
  const walkResults = (wire) => wire.hostPosts.filter((m) => m.type === 'actionResult' && m.action === 'openLocation');

  // A fresh revision: the walk opens, highlights, clears and ends.
  let wire = await openWire(walkDocument(), { 'source.py': SOURCE });
  try {
    const forwarded = [];
    const page = mountPage(wire, (win) => win.addEventListener('keydown', (ev) => forwarded.push(ev.key)));
    await waitFor(() => $(page, '[data-node-id="loss"]'), 'the viewer did not mount');
    const { window } = page;
    const press = (key, target = window.document.activeElement) => {
      const event = new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      return event;
    };
    const canvas = $(page, '.mlv-canvas');
    canvas.focus();
    assert.equal(press('r').defaultPrevented, true);
    assert.equal(page.app.walk.active, true);
    // Not observed: the inferred connection, the inferred finding and the unresolved step.
    assert.equal($(page, '.mlv-walkbar__postext').textContent, 'Claim 1 of 3 · Not observed');
    assert.deepEqual(plain(page.app.selection), { kind: 'edge', id: 'step' });
    await waitFor(() => walkResults(wire).length === 1, 'the host did not answer the walk\'s first open');
    const request = page.outgoing.filter((m) => m.type === 'openLocation').at(-1);
    assert.equal(request.walk, true);
    assert.equal(request.seq, 1);
    assert.deepEqual(plain(walkResults(wire)[0]), { v: 1, type: 'actionResult', requestId: request.requestId, action: 'openLocation', outcome: 'done', seq: 1 });
    const shown = vscode.__recorded.shownDocuments;
    assert.equal(shown.length, 1);
    assert.equal(shown[0].options.preserveFocus, true, 'the editor opens beside with the focus kept');
    assert.equal(vscode.__recorded.decorationTypes.length, 1, 'the cited lines are highlighted');
    assert.equal(vscode.__recorded.decorationTypes[0].disposed, false);
    await waitFor(() => $(page, '.mlv-walkbar__editor').getAttribute('data-walk-status') === 'done', 'the bar did not show the done answer');
    assert.equal($(page, '.mlv-walkbar__editortext').textContent, 'In the editor beside: source.py · line 2, highlighted. Focus stays here.');
    assert.equal(window.document.activeElement, canvas, 'the keyboard stayed on the diagram');

    // The finding, then the step with no quotes: the walk asks the host to clear the highlight.
    press('j');
    await waitFor(() => walkResults(wire).length === 2, 'the host did not answer the second open');
    assert.equal(walkResults(wire)[1].seq, 2);
    assert.deepEqual(plain(page.app.selection), { kind: 'issue', id: 'risk' });
    press('j');
    assert.deepEqual(plain(page.app.selection), { kind: 'node', id: 'save' });
    assert.equal($(page, '.mlv-walkbar__editortext').textContent, 'This claim cites no lines, so nothing is opened for it.');
    await waitFor(() => page.outgoing.some((m) => m.type === 'walk' && m.state === 'clear'), 'the walk did not ask for a clear');
    await waitFor(() => vscode.__recorded.decorationTypes.every((type) => type.disposed), 'the host kept the highlight of the earlier claim');

    // One Escape ends the walk; VS Code never sees it.
    press('k');
    await waitFor(() => walkResults(wire).length === 3, 'the host did not answer the step back');
    await waitFor(() => vscode.__recorded.decorationTypes.some((type) => !type.disposed), 'the step back did not highlight');
    const event = press('Escape');
    assert.equal(event.defaultPrevented, true);
    assert.equal(page.app.walk.active, false, 'one Escape ended the walk');
    assert.equal($(page, '.mlv-walkbar').hidden, true);
    assert.ok(page.app.selection, 'the claim stays selected');
    assert.deepEqual(forwarded.filter((key) => key === 'Escape'), [], 'the Escape did not reach VS Code');
    await waitFor(() => vscode.__recorded.decorationTypes.every((type) => type.disposed), 'the walk\'s end did not clear the highlight');
    // The place is kept in the webview's state for this revision, and nothing else is recorded.
    page.app.saveSoon.flush?.();
    page.app.bridge.saveState(page.app.getState());
    assert.deepEqual(plain(wire.state.walk), { filter: 'notObserved', claim: { kind: 'issue', id: 'risk' } });
    assert.equal(wire.state.workflowRevision, 'r1');
    assert.equal(vscode.__recorded.messages.filter((m) => m[0] === 'warn' || m[0] === 'error').length, 0, 'no notification');
    process.stdout.write('  PASS  review walk → opens beside with the focus kept and highlights → a claim with no quotes clears it → Escape ends it\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }

  // A stale revision: "Review affected claims" walks the claims citing source.py; nothing opens.
  wire = await openWire(walkDocument(), { 'source.py': SOURCE + '# edited after publication\n' });
  try {
    const page = mountPage(wire);
    const notice = () => $(page, '.mlv-hostnotice');
    await waitFor(() => $(page, '[data-node-id="loss"]') && notice() && !notice().hidden, 'the stale revision did not mount with its notice');
    await waitFor(() => $(page, '[data-notice-action="review"]'), 'the notice did not offer "Review affected claims"');
    const action = $(page, '[data-notice-action="review"]');
    assert.equal(action.textContent, 'Review affected claims');
    const notifications = () => vscode.__recorded.messages.filter((m) => m[0] === 'warn' || m[0] === 'error').length;
    const before = notifications();
    action.click();
    assert.equal(page.app.walk.active, true);
    assert.equal(page.app.walk.filter, 'changed');
    // Every claim but the unresolved step cites source.py: 2 steps, 2 connections, 1 finding.
    assert.equal($(page, '.mlv-walkbar__postext').textContent, 'Claim 1 of 5 · Changed files');
    assert.equal($(page, '.mlv-walkbar__editortext').textContent, 'source.py: changed since publishing; not opened.', 'said at once');
    await waitFor(() => walkResults(wire).length === 1, 'the host did not answer the stale open');
    const result = walkResults(wire)[0];
    assert.equal(result.outcome, 'blocked');
    assert.equal(result.seq, 1);
    assert.equal(vscode.__recorded.shownDocuments.length, 0, 'the changed file was never opened');
    assert.equal(notifications(), before, 'and the walk raised no notification (the one on load says the revision is stale)');
    // The host's own words replace the viewer's (one quote, so no "Quote 1 of 1").
    await waitFor(() => $(page, '.mlv-walkbar__editortext').textContent === result.message, () => 'the bar did not show the host\'s reason: ' + $(page, '.mlv-walkbar__editortext').textContent + ' / ' + result.message);
    assert.match(result.message, /source\.py/);
    assert.match(page.window.document.querySelector('.mlv-root > [aria-live]').textContent, /^Not opened: /);
    process.stdout.write('  PASS  stale revision → "Review affected claims" → blocked by the host, nothing opened, the reason in the bar\n');
  } finally {
    wire.controller.dispose();
    for (const page of wire.pages) page.window.close();
    rmSync(wire.root, { recursive: true, force: true });
  }
}
