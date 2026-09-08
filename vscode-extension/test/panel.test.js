'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { api, vscode } = require('./harness.js');

const { buildPanelHtml, createNonce, themeKindOf, VIEW_TYPE } = api;

const CSP_SOURCE = 'vscode-resource://mlview';
const SCRIPT_URI = 'https-less://file%2B.vscode-resource.vscode-cdn.net/ext/media/mlview.js';
const STYLE_URI = 'https-less://file%2B.vscode-resource.vscode-cdn.net/ext/media/mlview.css';

function html(overrides = {}) {
  return buildPanelHtml({
    cspSource: CSP_SOURCE,
    nonce: 'TEST-NONCE-0123456789ab',
    scriptUri: SCRIPT_URI,
    styleUri: STYLE_URI,
    bundlePresent: true,
    ...overrides
  });
}

test('the panel html carries the frozen nonce CSP', () => {
  const out = html();
  assert.match(out, /Content-Security-Policy/);
  assert.match(out, /default-src 'none';/);
  assert.ok(out.includes(`img-src ${CSP_SOURCE} data:;`));
  assert.ok(out.includes(`style-src ${CSP_SOURCE} 'unsafe-inline';`));
  assert.ok(out.includes(`font-src ${CSP_SOURCE};`));
  assert.ok(out.includes("script-src 'nonce-TEST-NONCE-0123456789ab';"));
  // 'unsafe-inline' is granted for STYLES ONLY.
  assert.ok(!/script-src[^;]*unsafe-inline/.test(out));
  assert.ok(!/script-src[^;]*unsafe-eval/.test(out));
});

test('every script tag is nonce-locked and both media uris are referenced', () => {
  const out = html();
  const scriptTags = out.match(/<script[^>]*>/g) ?? [];
  assert.ok(scriptTags.length >= 2, 'expected the bundle plus the bootstrap');
  for (const tag of scriptTags) {
    assert.match(tag, /nonce="TEST-NONCE-0123456789ab"/, `unnonced script: ${tag}`);
  }
  assert.ok(out.includes(SCRIPT_URI), 'media/mlview.js is referenced');
  assert.ok(out.includes(STYLE_URI), 'media/mlview.css is referenced');
  assert.match(out, /<div id="mlview-root">/);
});

test('the builder introduces no urls of its own — only the two media uris it is handed', () => {
  const out = html();
  const urls = out.match(/[a-z][a-z0-9+.-]*:\/\/[^\s"'<>]*/gi) ?? [];
  for (const url of urls) {
    assert.ok(
      url === SCRIPT_URI || url === STYLE_URI || url.startsWith(CSP_SOURCE),
      `unexpected absolute URL in the webview document: ${url}`
    );
  }
  assert.ok(!/https?:\/\//.test(out), 'an external http(s) URL leaked into the document');
  assert.ok(!out.includes('@import'));
  assert.ok(!out.includes('cdn.jsdelivr'));
});

test('the bootstrap is valid javascript and references the documented viewer API', () => {
  const out = html();
  const script = inlineScript(out);
  new vm.Script(script); // throws on a syntax error
  assert.match(script, /MLView\.bridges\.vscode\(\)/);
  assert.match(script, /window\.MLView\.mount\(/);
  assert.match(script, /app\.update\(msg\.graph, msg\.preserve\)/);
  assert.match(script, /type: 'ready'/);
});

test('the bootstrap mounts immediately so loading and error states can render', () => {
  const run = runBootstrap({ acceptsNullGraph: true, postsReadyItself: true });
  assert.equal(run.mounts.length, 1, 'mounted once, before any graph arrived');
  assert.equal(run.mounts[0].graph, null);
  assert.equal(run.posted.filter((m) => m.type === 'ready').length, 1, 'exactly one ready');
});

test('the bootstrap posts ready itself when the viewer does not', () => {
  const run = runBootstrap({ acceptsNullGraph: true, postsReadyItself: false });
  assert.equal(run.posted.filter((m) => m.type === 'ready').length, 1);
});

test('a viewer that needs a graph at mount time falls back to mount-on-first-graph', () => {
  const run = runBootstrap({ acceptsNullGraph: false, postsReadyItself: true });
  assert.equal(run.mounts.length, 0, 'nothing mounted yet');
  assert.equal(run.posted.filter((m) => m.type === 'ready').length, 1);

  run.emit({ v: 1, type: 'analysisStarted', requestId: 'r1', scope: 'workspace' });
  assert.equal(run.mounts.length, 0, 'non-graph messages do not mount');

  run.emit({ v: 1, type: 'graph', requestId: 'r1', graph: { nodes: [] } });
  assert.equal(run.mounts.length, 1);
  assert.deepEqual(run.mounts[0].graph, { nodes: [] });

  run.emit({ v: 1, type: 'graph', requestId: 'r2', graph: { nodes: [1] } });
  assert.equal(run.mounts.length, 1, 'a second graph updates instead of remounting');
  assert.equal(run.updates.length, 1);
});

test('a webview whose bundle failed to load shows a message instead of throwing', () => {
  const run = runBootstrap({ noGlobal: true });
  assert.equal(run.mounts.length, 0);
  assert.match(run.root.children.map((c) => c.textContent).join(' '), /viewer bundle failed to load/);
});

test('A13: a missing viewer bundle renders a message, not a broken panel', () => {
  const out = html({ bundlePresent: false });
  assert.match(out, /viewer bundle not built/i);
  assert.match(out, /scripts\/build\.ps1/);
  assert.match(out, /default-src 'none';/);
  assert.ok(!out.includes(`src="${SCRIPT_URI}"`), 'the missing bundle must not be script-src-ed');
  assert.ok(!/https?:\/\//.test(out));
});

test('html interpolation is escaped', () => {
  const out = html({ styleUri: 'a"><script>alert(1)</script>' });
  assert.ok(!out.includes('<script>alert(1)</script>'));
  assert.ok(out.includes('&quot;&gt;&lt;script&gt;'));
});

test('nonces are 32 base64 characters and never repeat', () => {
  const a = createNonce();
  const b = createNonce();
  assert.notEqual(a, b);
  assert.match(a, /^[A-Za-z0-9+/=]{32}$/);
});

test('theme kinds map to the protocol vocabulary', () => {
  assert.equal(themeKindOf(vscode.ColorThemeKind.Light), 'light');
  assert.equal(themeKindOf(vscode.ColorThemeKind.Dark), 'dark');
  assert.equal(themeKindOf(vscode.ColorThemeKind.HighContrast), 'hc');
  assert.equal(themeKindOf(vscode.ColorThemeKind.HighContrastLight), 'hc');
});

test('the webview view type matches the manifest activation event', () => {
  assert.equal(VIEW_TYPE, 'mlview.diagram');
});

/** The inline (non-src) bootstrap script from the generated document. */
function inlineScript(document) {
  const match = /<script nonce="[^"]+">([\s\S]*?)<\/script>/.exec(document);
  assert.ok(match, 'the bootstrap script was not found');
  return match[1];
}

/**
 * Execute the bootstrap against a stubbed `window.MLView`, so the mount/ready/fallback logic is
 * exercised rather than merely pattern-matched.
 */
function runBootstrap(opts) {
  const mounts = [];
  const updates = [];
  const posted = [];
  const listeners = [];
  const root = { children: [], appendChild(child) { this.children.push(child); } };

  const app = {
    update: (graph, preserve) => updates.push({ graph, preserve })
  };

  const bridge = {
    post: (msg) => posted.push(msg),
    onMessage: (cb) => {
      listeners.push(cb);
      return () => {
        const i = listeners.indexOf(cb);
        if (i >= 0) listeners.splice(i, 1);
      };
    }
  };

  const MLView = {
    bridges: { vscode: () => bridge },
    mount(el, graph, b) {
      if (graph === null && !opts.acceptsNullGraph) {
        throw new Error('a graph is required');
      }
      mounts.push({ el, graph });
      if (opts.postsReadyItself) {
        b.post({ v: 1, type: 'ready' });
      }
      return app;
    }
  };

  const sandbox = {
    window: opts.noGlobal ? {} : { MLView },
    document: {
      getElementById: () => root,
      createElement: (tag) => ({ tag, textContent: '' })
    }
  };
  sandbox.window.document = sandbox.document;
  vm.createContext(sandbox);
  vm.runInContext(inlineScript(html()), sandbox);

  return {
    mounts,
    updates,
    posted,
    root,
    emit: (msg) => listeners.slice().forEach((cb) => cb(msg))
  };
}
