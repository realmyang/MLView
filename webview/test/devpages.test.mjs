/**
 * The dev harness pages must actually work from file:// with no server and no
 * network — the same constraint the standalone HTML report lives under. jsdom
 * loads them straight off disk, follows their relative <link>/<script> paths
 * and runs their bootstrap.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { JSDOM, VirtualConsole } from 'jsdom';
import { WEBVIEW_ROOT } from './helpers.mjs';

function deepClone(value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(deepClone);
  const out = {};
  for (const key of Object.keys(value)) out[key] = deepClone(value[key]);
  return out;
}

async function openPage(name) {
  const virtualConsole = new VirtualConsole();
  const errors = [];
  virtualConsole.on('jsdomError', (e) => errors.push(e));
  const dom = await JSDOM.fromFile(join(WEBVIEW_ROOT, 'dev', name), {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    virtualConsole,
  });
  if (typeof dom.window.structuredClone !== 'function') dom.window.structuredClone = deepClone;
  await new Promise((resolve) => {
    if (dom.window.document.readyState === 'complete') resolve();
    else dom.window.addEventListener('load', resolve, { once: true });
  });
  await new Promise((r) => setTimeout(r, 50));
  return { dom, window: dom.window, document: dom.window.document, errors };
}

test('dev/index.html mounts the inlined sample with the standalone bridge', async () => {
  const page = await openPage('index.html');
  assert.deepEqual(page.errors.map((e) => String(e.message || e)), []);
  assert.ok(page.window.MLView, 'the bundle loaded over a relative path');
  assert.ok(page.window.mlviewApp, 'the page mounted an app');
  const nodes = page.document.querySelectorAll('[data-node-id]');
  assert.ok(nodes.length >= 12, 'the inlined graph rendered ' + nodes.length + ' nodes');
  assert.ok(page.document.querySelectorAll('[data-edge-id]').length >= 14);
  assert.ok(page.document.querySelectorAll('[data-issue-id]').length >= 6);
  assert.ok(page.document.querySelector('.mlv-lane[data-lane-id="train"]'), 'the train band is drawn');
});

test('dev/index.html demonstrates a scope through the real bootstrap path', async () => {
  const page = await openPage('index.html');
  const select = page.document.getElementById('dev-scope');
  assert.ok(select, 'the harness offers a scope picker of its own');
  const specs = Array.from(select.options).map((o) => o.value);
  assert.ok(specs.indexOf('concern:evaluation') >= 0, specs.join(', '));
  assert.equal(page.window.mlviewApp.getScope().spec, null, 'unscoped by default');

  select.value = 'concern:evaluation';
  select.dispatchEvent(new page.window.Event('change', { bubbles: true }));
  assert.equal(page.window.mlviewApp.getScope().spec, 'concern:evaluation');
  assert.ok(page.document.querySelector('.mlv-breadcrumb').hidden === false, 'and the breadcrumb appears');

  // The query-string path sets the SAME root attribute the report emits.
  const html = await readFile(join(WEBVIEW_ROOT, 'dev', 'index.html'), 'utf8');
  assert.ok(html.indexOf('data-mlview-scope') > 0, 'through data-mlview-scope, not a fourth mount argument');
  assert.equal(html.indexOf('MLView.mount(root, graph, bridge)') > 0, true, 'mount keeps its three arguments');
});

test('dev/index.html inlines the graph rather than fetching it', async () => {
  const html = await readFile(join(WEBVIEW_ROOT, 'dev', 'index.html'), 'utf8');
  assert.ok(html.indexOf('type="application/json"') >= 0);
  assert.equal(html.indexOf('fetch('), -1, 'the page must work from file://');
  assert.equal(html.indexOf('http' + '://'), -1);
  assert.equal(html.indexOf('https' + '://'), -1);
  const start = html.indexOf('<!-- MLVIEW-SAMPLE-START -->');
  const end = html.indexOf('<!-- MLVIEW-SAMPLE-END -->');
  assert.ok(start > 0 && end > start, 'the refresh markers are intact');
  const block = html.slice(start, end);
  const opener = 'type="application/json">';
  const jsonStart = block.indexOf(opener) + opener.length;
  const jsonEnd = block.lastIndexOf('</' + 'script>');
  assert.ok(jsonStart > opener.length && jsonEnd > jsonStart, 'the inline JSON block is well formed');
  const graph = JSON.parse(block.slice(jsonStart, jsonEnd));
  assert.equal(graph.schemaVersion, '1.0');
  assert.ok(graph.nodes.length > 0);
});

test('dev/states.html renders every node kind in every state plus the markers', async () => {
  const page = await openPage('states.html');
  assert.deepEqual(page.errors.map((e) => String(e.message || e)), []);
  const kinds = page.window.MLView.__internal.nodeKinds;
  const cards = page.document.querySelectorAll('.mlv-node');
  assert.equal(cards.length, kinds.length * 6, 'every kind is drawn in all six states');
  assert.ok(page.document.querySelectorAll('.mlv-node.is-ghost').length === kinds.length);
  assert.ok(page.document.querySelectorAll('.mlv-node.is-selected').length === kinds.length);
  assert.ok(page.document.querySelectorAll('.mlv-node.is-stale').length === kinds.length);
  assert.ok(page.document.querySelectorAll('.mlv-glyph--low').length > 0);
  assert.ok(page.document.querySelectorAll('.mlv-glyph--medium').length > 0);
  assert.ok(page.document.querySelectorAll('.mlv-glyph--high').length > 0);
});
