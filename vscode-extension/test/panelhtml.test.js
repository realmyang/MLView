/**
 * Integration: the panel's webview HTML builder and the real media/ directory.
 *
 * panel.test.js already proves the builder produces a well-formed, CSP-locked
 * document from arbitrary URIs. This file closes the other half of the loop —
 * that the two files it points at are the two files tools/sync-assets.py writes,
 * and that they are actually on disk after a build. Before the sync it asserts
 * the A13 fallback instead, so it is meaningful in both states.
 */

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api } = require('./harness.js');

const { buildPanelHtml } = api;
const MEDIA_DIR = path.join(__dirname, '..', 'media');
const bundlePresent = fs.existsSync(path.join(MEDIA_DIR, 'mlview.js'));

function html(overrides = {}) {
  return buildPanelHtml({
    cspSource: 'vscode-resource://mlview',
    nonce: 'TEST-NONCE-0123456789ab',
    scriptUri: 'vscode-resource://mlview/ext/media/mlview.js',
    styleUri: 'vscode-resource://mlview/ext/media/mlview.css',
    bundlePresent: true,
    ...overrides,
  });
}

test('the panel HTML points at media/mlview.js and media/mlview.css', () => {
  const doc = html();
  assert.match(doc, /media\/mlview\.js/, 'the script tag must load the synced bundle');
  assert.match(doc, /media\/mlview\.css/, 'the stylesheet must load the synced bundle');
  assert.match(doc, /id="mlview-root"/);
  assert.match(doc, /MLView\.bridges\.vscode\(\)/, 'A5: the bootstrap builds the vscode bridge');
  assert.match(doc, /MLView\.mount/, 'A5: the bootstrap mounts the viewer');
});

test('every script tag in the panel carries the CSP nonce', () => {
  const doc = html();
  const scripts = doc.match(/<script\b[^>]*>/g) || [];
  assert.ok(scripts.length > 0, 'the panel must load at least one script');
  for (const tag of scripts) {
    assert.match(tag, /nonce="TEST-NONCE-0123456789ab"/, 'un-nonced script tag: ' + tag);
  }
});

test('the A13 fallback panel names the build script instead of loading a bundle', () => {
  const doc = html({ bundlePresent: false });
  assert.doesNotMatch(doc, /<script[^>]+src=/, 'the fallback must not try to load a missing bundle');
  assert.match(doc, /build\.ps1/, 'the fallback must tell the user how to produce it');
});

test('tools/sync-assets.py wrote exactly the two files the panel loads', { skip: bundlePresent ? false : 'media/ not synced yet (pre-build state)' }, () => {
  for (const name of ['mlview.js', 'mlview.css']) {
    const file = path.join(MEDIA_DIR, name);
    assert.ok(fs.existsSync(file), 'media/' + name + ' is missing — run tools/sync-assets.py');
    assert.ok(fs.statSync(file).size > 1024, 'media/' + name + ' looks truncated');
  }
  // The bundle the panel loads must be the self-contained viewer, not a stub.
  const js = fs.readFileSync(path.join(MEDIA_DIR, 'mlview.js'), 'utf8');
  assert.match(js, /MLView/, 'the synced bundle must define the MLView global');
  assert.doesNotMatch(js, /\bhttps?:\/\//, 'the viewer bundle must have no external references');
});
