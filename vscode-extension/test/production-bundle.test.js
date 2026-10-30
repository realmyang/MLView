'use strict';
/**
 * The bundle that the package holds: `node esbuild.mjs --production`, minified. Every other test
 * runs the unminified bundles in out/, so this file builds the production bundle into a temporary
 * folder, which leaves out/ as it is, and executes it against the mock `vscode`.
 *
 * The last tests read the packaged code as text: the modules that the bundle loads, the names by
 * which a script reaches a network, the two calls by which the editor's own interface opens an
 * address or starts a terminal, and the content security policy of each page.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./panel-helpers');
const { vscode } = h;

const root = path.join(__dirname, '..');
// Every module that the packaged bundle may load. The extension reads files and computes hashes.
// The four modules of Node open no connection and start no process. `vscode` is the editor's own
// interface: through it an extension can open an address and start a terminal, so EDITOR_CALLS
// below counts those two calls. Any other module fails the test.
const ALLOWED_MODULES = ['node:crypto', 'node:fs', 'node:fs/promises', 'node:path', 'vscode'];
// The names by which a script reaches a network. `fetch` counts as a word, called or not.
const NETWORK_NAMES = ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon', 'RTCPeerConnection', 'window.open'];
// How often the bundle may name each call. The one openExternal is the Open button after an export,
// on the file that was written. Other calls of the editor's interface are not searched for.
const EDITOR_CALLS = { openExternal: 1, createTerminal: 0 };
const POLICY = /Content-Security-Policy" content="([^"]+)"/g;
// The sources of each directive, per page, in the order the bundle states them. FILLED stands for
// a value that is filled in when the page is made: the nonce, or the editor's own resource origin.
const FILLED = '<filled>';
const PAGE_POLICIES = [
  // The page for a file that cannot be drawn: text and one style sheet in the page.
  { 'default-src': ["'none'"], 'style-src': [`'nonce-${FILLED}'`] },
  // The diagram page: pictures, styles and scripts from the extension's own folder only.
  { 'default-src': ["'none'"], 'img-src': [FILLED, 'data:'], 'style-src': [FILLED], 'script-src': [`'nonce-${FILLED}'`, FILLED] }
];

/**
 * The modules a bundle loads with `require`, whether every `require` names its module as a string, and
 * every other way to a module: `require` taken as a value, and `getBuiltinModule`. The word between
 * two spaces is a word of a message, not the function.
 */
function requiredModules(text) {
  const calls = text.match(/\brequire\(/g) ?? [];
  const named = [...text.matchAll(/\brequire\((["'`])([^"'`]+)\1\)/g)].map((match) => match[2]);
  const otherWays = [...text.matchAll(/(.)\brequire\b(?!\()(.?)/gs)]
    .filter((match) => !(match[1] === ' ' && match[2] === ' '))
    .map(() => 'require as a value')
    .concat(text.includes('getBuiltinModule') ? ['getBuiltinModule'] : []);
  return { modules: [...new Set(named)].sort(), everyCallNamesItsModule: calls.length === named.length, otherWays };
}

function networkNames(text) {
  return NETWORK_NAMES.filter((name) => (name === 'fetch' ? /\bfetch\b/.test(text) : text.includes(name)));
}

function editorCalls(text) {
  return Object.fromEntries(Object.keys(EDITOR_CALLS).map((name) => [name, text.split(name).length - 1]));
}

/** A policy as its directives, each with its list of sources. Every `${...}` of the bundle's text reads as FILLED. */
function directivesOf(policy) {
  const parts = policy.replace(/\$\{[^}]*\}/g, FILLED).split(';').map((part) => part.trim()).filter(Boolean);
  return Object.fromEntries(parts.map((part) => part.split(/\s+/)).map(([name, ...sources]) => [name, sources]));
}

/** The text that sets each page: from one assignment to `webview.html` to the next, or to the end. */
function pagesOf(text) {
  const starts = [...text.matchAll(/\.html\s*=(?!=)/g)].map((match) => match.index);
  return starts.map((start, index) => text.slice(start, starts[index + 1] ?? text.length));
}

/** What a content security policy allows that a page of the extension must not have. */
function policyProblems(policy) {
  const problems = [];
  const directives = policy.split(';').map((part) => part.trim()).filter(Boolean).map((part) => part.split(/\s+/));
  if (directives.length === 0 || directives[0].join(' ') !== "default-src 'none'") {
    problems.push("the policy does not start with default-src 'none'");
  }
  for (const [name, ...sources] of directives) {
    if (name === 'connect-src') problems.push('the policy names connect-src');
    for (const source of sources) {
      if (/^https?:/i.test(source) || source === '*') problems.push(`${name} allows ${source}`);
    }
  }
  return problems;
}
const folder = h.tempRoot('mlview-production-');
const bundle = path.join(folder, 'extension.js');
const build = spawnSync(process.execPath, ['esbuild.mjs', '--production', `--out=${bundle}`], { cwd: root, encoding: 'utf8' });
const workspaces = [];
test.after(() => {
  for (const workspace of workspaces.splice(0)) fs.rmSync(workspace, { recursive: true, force: true });
  fs.rmSync(folder, { recursive: true, force: true });
});

function context() {
  return {
    subscriptions: [],
    extensionPath: root,
    extensionUri: vscode.Uri.file(root),
    extension: { packageJSON: { version: require('../package.json').version } },
    globalState: vscode.__memento()
  };
}

test('the production build writes a bundle with no comment line and no source map link, and its map beside it', () => {
  assert.equal(build.status, 0, build.stderr);
  const text = fs.readFileSync(bundle, 'utf8');
  assert.ok(!text.includes('sourceMappingURL'), 'the bundle links no source map');
  assert.deepEqual(text.split('\n').filter((line) => /^\s*(\/\/|\/\*)/.test(line)), [], 'no line is a comment');
  assert.ok(fs.existsSync(`${bundle}.map`), 'the source map is a separate file beside the bundle');
});

test('the production bundle activates: two commands and the diagram editor, and deactivation unregisters the editor', () => {
  vscode.__reset();
  const extension = require(bundle);
  const ctx = context();
  extension.activate(ctx);
  assert.deepEqual([...vscode.__recorded.commands.keys()], ['mlview.openGeneratedDiagram', 'mlview.revealInDiagram']);
  assert.deepEqual([...vscode.__recorded.customEditors.keys()], ['mlview.diagram']);
  assert.deepEqual([...vscode.__recorded.serializers.keys()], ['mlview.authoredDiagram']);
  extension.deactivate();
  assert.equal(vscode.__recorded.customEditors.size, 0, 'deactivation unregisters the editor');
});

test('the production bundle shows a diagram: the page, then the document once the viewer is ready', async () => {
  vscode.__reset();
  const workspace = h.tempRoot('mlview-production-workspace-');
  workspaces.push(workspace);
  fs.writeFileSync(path.join(workspace, 'source.py'), 'fit()\n');
  const artifact = path.join(workspace, 'run.mlview.json');
  h.writeJson(artifact, h.verify(h.workflow('source.py'), { 'source.py': 'fit()\n' }));
  vscode.__setWorkspaceFolders([workspace]);
  const extension = require(bundle);
  extension.activate(context());
  try {
    const { provider } = vscode.__recorded.customEditors.get('mlview.diagram');
    const token = new vscode.CancellationTokenSource().token;
    const panel = vscode.window.createWebviewPanel('mlview.diagram', 'run.mlview.json', { viewColumn: 1 }, {});
    const document = await provider.openCustomDocument(vscode.Uri.file(artifact), {}, token);
    await provider.resolveCustomEditor(document, panel, token);
    assert.match(panel.webview.html, /Content-Security-Policy/);
    assert.match(panel.webview.html, /mountWorkflow/);
    panel.fire({ v: 1, type: 'ready' });
    await h.waitFor(() => h.workflows(panel).length === 1, 'the diagram was not shown');
    assert.equal(h.shownRevision(panel), 'r1');
    assert.deepEqual(h.lastBanner(panel).codes, [], 'the sources match the document: nothing is reported');
    // A changed source file reaches the open diagram through the watcher.
    fs.writeFileSync(path.join(workspace, 'source.py'), 'fit(epochs=2)\n');
    await h.diskEvent(panel, 'change', path.join(workspace, 'source.py'));
    assert.deepEqual(panel.posted.filter((m) => m.type === 'stale').at(-1).files, [{ path: 'source.py', reason: 'changed' }]);
    assert.deepEqual(h.lastBanner(panel).codes, ['stale']);
  } finally {
    extension.deactivate();
  }
});

test('the production bundle loads only the listed modules: none opens a connection or starts a process', () => {
  assert.equal(build.status, 0, build.stderr);
  const text = fs.readFileSync(bundle, 'utf8');
  const { modules, everyCallNamesItsModule, otherWays } = requiredModules(text);
  assert.ok(everyCallNamesItsModule, 'every require names its module as a string');
  assert.deepEqual(otherWays, [], 'no other way to a module');
  assert.deepEqual(modules, ALLOWED_MODULES);
  assert.ok(!/\bimport\(/.test(text), 'the bundle imports no module at run time');
  for (const name of ['http', 'https', 'net', 'tls', 'dgram', 'child_process']) {
    assert.ok(!ALLOWED_MODULES.includes(name) && !ALLOWED_MODULES.includes(`node:${name}`), `${name} is not on the list`);
  }
});

test('neither the production bundle nor the viewer bundle names an interface that reaches a network', () => {
  assert.deepEqual(networkNames(fs.readFileSync(bundle, 'utf8')), [], 'the extension bundle');
  assert.deepEqual(networkNames(fs.readFileSync(path.join(root, 'media', 'mlview.js'), 'utf8')), [], 'the viewer bundle');
});

test('the production bundle opens an address in one place and starts no terminal', () => {
  assert.equal(build.status, 0, build.stderr);
  assert.deepEqual(editorCalls(fs.readFileSync(bundle, 'utf8')), EDITOR_CALLS);
  assert.deepEqual(editorCalls(fs.readFileSync(path.join(root, 'media', 'mlview.js'), 'utf8')), { openExternal: 0, createTerminal: 0 });
});

test('every page of the production bundle has a content security policy that allows no connection', async () => {
  // As the bundle states them, with the nonce and the editor's own resource origin still to be filled in.
  const text = fs.readFileSync(bundle, 'utf8');
  const stated = [...text.matchAll(POLICY)].map((match) => match[1]);
  for (const policy of stated) assert.deepEqual(policyProblems(policy), [], policy);
  // Each directive holds exactly its listed sources, and each page that the bundle sets states one policy.
  assert.deepEqual(stated.map(directivesOf), PAGE_POLICIES, 'the page for a file that cannot be drawn, then the diagram page');
  const pages = pagesOf(text);
  assert.equal(pages.length, PAGE_POLICIES.length, 'the bundle sets a page in as many places as it states a policy');
  for (const page of pages) assert.equal([...page.matchAll(POLICY)].length, 1, 'a page without a policy of its own');
  // As the diagram page receives it.
  vscode.__reset();
  const workspace = h.tempRoot('mlview-production-policy-');
  workspaces.push(workspace);
  fs.writeFileSync(path.join(workspace, 'source.py'), 'fit()\n');
  const artifact = path.join(workspace, 'run.mlview.json');
  h.writeJson(artifact, h.verify(h.workflow('source.py'), { 'source.py': 'fit()\n' }));
  vscode.__setWorkspaceFolders([workspace]);
  const extension = require(bundle);
  extension.activate(context());
  try {
    const { provider } = vscode.__recorded.customEditors.get('mlview.diagram');
    const token = new vscode.CancellationTokenSource().token;
    const panel = vscode.window.createWebviewPanel('mlview.diagram', 'run.mlview.json', { viewColumn: 1 }, {});
    const document = await provider.openCustomDocument(vscode.Uri.file(artifact), {}, token);
    await provider.resolveCustomEditor(document, panel, token);
    const given = [...panel.webview.html.matchAll(POLICY)].map((match) => match[1]);
    assert.equal(given.length, 1);
    assert.deepEqual(policyProblems(given[0]), [], given[0]);
    assert.deepEqual(given[0].split(';').map((part) => part.trim().split(/\s+/)[0]).filter(Boolean), ['default-src', 'img-src', 'style-src', 'script-src']);
    // The same lists with the two values filled in: the origin that the editor gave, and a nonce.
    const origin = panel.webview.cspSource;
    const received = directivesOf(given[0]);
    assert.match(received['script-src'][0], /^'nonce-[A-Za-z0-9+/=_-]{16,}'$/);
    received['script-src'][0] = `'nonce-${FILLED}'`;
    assert.deepEqual(received, JSON.parse(JSON.stringify(PAGE_POLICIES[1]).split(`"${FILLED}"`).join(JSON.stringify(origin))));
  } finally {
    extension.deactivate();
  }
});

test('a module that opens a connection, a network name and a policy that allows a connection are each reported', () => {
  const text = fs.readFileSync(bundle, 'utf8');
  assert.deepEqual(requiredModules(`${text};require("https");`).modules, ['https', ...ALLOWED_MODULES]);
  assert.deepEqual(requiredModules(`${text};require("node:child_process");`).modules, [...ALLOWED_MODULES.slice(0, 1), 'node:child_process', ...ALLOWED_MODULES.slice(1)].sort());
  assert.equal(requiredModules(`${text};require(name);`).everyCallNamesItsModule, false);
  // The function under another name, and the other door to the modules of Node.
  assert.deepEqual(requiredModules(`${text};let e=require;e("node:"+"https");`).otherWays, ['require as a value']);
  assert.deepEqual(requiredModules(`${text};let e=typeof require<"u"?require:null;`).otherWays, ['require as a value', 'require as a value']);
  assert.deepEqual(requiredModules(`${text};process.getBuiltinModule("node:https");`).otherWays, ['getBuiltinModule']);
  assert.deepEqual(requiredModules('throw new Error("These diagrams require a local folder.")').otherWays, []);
  assert.deepEqual(networkNames(`${text};fetch("https://example.com");`), ['fetch']);
  assert.deepEqual(networkNames('let{fetch:e}=globalThis;e(address)'), ['fetch']);
  assert.deepEqual(networkNames('prefetch(a); refetch'), []);
  assert.deepEqual(networkNames('new WebSocket(address); navigator.sendBeacon(address)'), ['WebSocket', 'sendBeacon']);
  assert.deepEqual(networkNames('new RTCPeerConnection(); window.open(address)'), ['RTCPeerConnection', 'window.open']);
  assert.deepEqual(editorCalls(`${text};L.env.openExternal(address);L.window.createTerminal().sendText(line)`), { openExternal: 2, createTerminal: 1 });
  // A source that a directive does not list, and a page without a policy.
  assert.deepEqual(directivesOf("default-src 'none'; script-src 'nonce-${e}' ${t.cspSource} 'strict-dynamic';"),
    { 'default-src': ["'none'"], 'script-src': [`'nonce-${FILLED}'`, FILLED, "'strict-dynamic'"] });
  assert.notDeepEqual(directivesOf(`default-src 'none'; img-src \${t} data: example.com; style-src \${t}; script-src 'nonce-\${e}' \${t};`), PAGE_POLICIES[1]);
  const third = `${text};n.webview.html=\`<!doctype html><html><body><script src="https://example.com/a.js"></script></body></html>\`;`;
  assert.deepEqual(pagesOf(third).map((page) => [...page.matchAll(POLICY)].length), [1, 1, 0]);
  assert.deepEqual(pagesOf('if(n.webview.html==="")n.webview.html=a;'), ['.html=a;']);
  const policy = "default-src 'none'; img-src vscode-webview://mock data:; style-src vscode-webview://mock; script-src 'nonce-abc' vscode-webview://mock;";
  assert.deepEqual(policyProblems(policy), []);
  assert.deepEqual(policyProblems(`${policy} connect-src https://example.com;`), ['the policy names connect-src', 'connect-src allows https://example.com']);
  assert.deepEqual(policyProblems(policy.replace("default-src 'none'", "default-src 'self'")), ["the policy does not start with default-src 'none'"]);
  assert.deepEqual(policyProblems(policy.replace('data:', 'data: https:')), ['img-src allows https:']);
  assert.deepEqual(policyProblems(`${policy} font-src *;`), ['font-src allows *']);
});
