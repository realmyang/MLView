'use strict';
/**
 * The authored panel's inline bootstrap, evaluated with node:vm against a stub window and DOM.
 * It must post exactly one `ready`, stash the `init` theme and capabilities before mounting, mount
 * on the first `workflow` only, and create, update and remove the banner `pre`.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const h = require('./panel-helpers');

const fixtures = [];
test.afterEach(() => h.cleanup(fixtures));
/** Objects created inside the vm context have that realm's prototypes; compare their JSON. */
const plain = (value) => JSON.parse(JSON.stringify(value));

async function bootstrapSource() {
  const fixture = await h.openPanel({ ready: false });
  fixtures.push(fixture);
  const scripts = [...fixture.panel.webview.html.matchAll(/<script nonce="[^"]+">([\s\S]*?)<\/script>/g)].map(match => match[1]);
  assert.equal(scripts.length, 1, 'exactly one inline script');
  return scripts[0];
}

function stubEnvironment() {
  const elements = new Map();
  const root = {
    id: 'mlview-root',
    children: [],
    prepend(element) {
      element.parent = root;
      root.children.unshift(element);
      elements.set(element.id, element);
    }
  };
  elements.set('mlview-root', root);
  const document = {
    getElementById: (id) => elements.get(id) || null,
    createElement: (tag) => {
      const element = {
        tag, id: '', attributes: {}, textContent: '',
        setAttribute(name, value) { element.attributes[name] = value; },
        remove() {
          root.children.splice(root.children.indexOf(element), 1);
          elements.delete(element.id);
        }
      };
      return element;
    }
  };
  let listener;
  let state = null;
  const bridge = {
    theme: 'light',
    capabilities: { canOpenSource: true },
    posted: [],
    saved: [],
    post(message) { bridge.posted.push(message); },
    onMessage(callback) { listener = callback; return () => undefined; },
    saveState(value) { state = value; bridge.saved.push(value); },
    loadState() { return state; }
  };
  const mounts = [];
  const window = {
    MLView: {
      bridges: { vscode: () => bridge },
      mountWorkflow(target, doc, withBridge) {
        mounts.push({ target, doc, theme: withBridge.theme, capabilities: withBridge.capabilities });
        return { setWorkflow() { throw new Error('the bootstrap never drives the mounted app'); } };
      }
    }
  };
  return { window, document, root, bridge, mounts, deliver: (message) => listener(message) };
}

test('bootstrap posts one ready, stashes init before mount, and mounts on the first workflow only', async () => {
  const source = await bootstrapSource();
  const env = stubEnvironment();
  vm.runInNewContext(source, { window: env.window, document: env.document, Object });
  assert.deepEqual(plain(env.bridge.posted), [{ v: 1, type: 'ready' }]);
  env.deliver({ v: 1, type: 'init', theme: 'hc', capabilities: { canOpenSource: true, canRefine: true }, artifact: '/ws/run.mlview.json' });
  assert.equal(env.bridge.theme, 'hc');
  assert.deepEqual(env.bridge.capabilities, { canOpenSource: true, canRefine: true });
  assert.equal(env.bridge.saved.at(-1).artifact, '/ws/run.mlview.json');
  env.deliver({ v: 1, type: 'theme', kind: 'dark' });
  assert.equal(env.bridge.theme, 'dark', 'a pre-mount theme change updates the stashed theme');
  const first = { revision: { id: 'r1' } };
  env.deliver({ v: 1, type: 'workflow', document: first });
  assert.equal(env.mounts.length, 1);
  assert.equal(env.mounts[0].doc, first);
  assert.equal(env.mounts[0].target, env.root);
  assert.equal(env.mounts[0].theme, 'dark');
  env.deliver({ v: 1, type: 'workflow', document: { revision: { id: 'r2' } } });
  assert.equal(env.mounts.length, 1, 'later workflow frames belong to the mounted app');
  env.deliver({ v: 1, type: 'init', theme: 'light', capabilities: { canOpenSource: false }, artifact: '/ws/run.mlview.json' });
  assert.equal(env.bridge.theme, 'dark', 'after mount the app owns the theme');
  assert.deepEqual(env.bridge.capabilities, { canOpenSource: true, canRefine: true });
  env.bridge.saveState({ viewport: { zoom: 2 } });
  assert.deepEqual(plain(env.bridge.saved.at(-1)), { viewport: { zoom: 2 }, artifact: '/ws/run.mlview.json' });
  env.deliver({ v: 2, type: 'workflow', document: {} });
  env.deliver(null);
  assert.equal(env.bridge.posted.length, 1, 'only the bootstrap ready is ever posted');
});

test('bootstrap creates, updates and removes the banner', async () => {
  const source = await bootstrapSource();
  const env = stubEnvironment();
  vm.runInNewContext(source, { window: env.window, document: env.document, Object });
  env.deliver({ v: 1, type: 'workflowError', message: 'Generated diagram update rejected; nothing valid can be displayed yet.\nJSON parse error: x', retained: false, codes: ['parse'] });
  const banner = env.document.getElementById('mlview-authored-error');
  assert.ok(banner);
  assert.equal(banner.tag, 'pre');
  assert.equal(banner.attributes.role, 'status');
  assert.equal(env.root.children[0], banner);
  assert.match(banner.textContent, /JSON parse error/);
  env.deliver({ v: 1, type: 'workflowError', message: 'second', retained: true, codes: ['stale'] });
  assert.equal(env.document.getElementById('mlview-authored-error'), banner);
  assert.equal(banner.textContent, 'second');
  assert.equal(env.root.children.length, 1);
  env.deliver({ v: 1, type: 'workflowError', message: '', retained: true, codes: [] });
  assert.equal(env.document.getElementById('mlview-authored-error'), null);
  assert.equal(env.root.children.length, 0);
  env.deliver({ v: 1, type: 'workflowError', message: '', retained: true, codes: [] });
  assert.equal(env.root.children.length, 0);
});
