'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

test('manifest exposes only the authored artifact command and activation path', () => {
  assert.deepEqual(manifest.contributes.commands.map(x => x.command), ['mlview.openGeneratedDiagram']);
  assert.deepEqual(manifest.activationEvents, [
    'onCommand:mlview.openGeneratedDiagram',
    'onWebviewPanel:mlview.authoredDiagram',
    'workspaceContains:**/*.mlview.json'
  ]);
  assert.equal(manifest.contributes.configuration, undefined);
  assert.equal(manifest.contributes.chatParticipants, undefined);
  assert.equal(manifest.contributes.languageModelTools, undefined);
  assert.ok(!manifest.keywords.includes('static-analysis'));
});

test('extension package contains no Python analyzer or rule documentation', () => {
  assert.equal(fs.existsSync(path.join(root, 'core')), false);
  assert.equal(fs.existsSync(path.join(root, 'docs', 'rules')), false);
  assert.equal(fs.existsSync(path.join(root, 'src', 'analysisRunner.ts')), false);
});

test('extension notice is byte-identical to the repository notice', () => {
  const repositoryNotice = fs.readFileSync(path.join(root, '..', 'THIRD_PARTY_NOTICES.md'));
  const extensionNotice = fs.readFileSync(path.join(root, 'THIRD_PARTY_NOTICES.md'));
  assert.ok(extensionNotice.equals(repositoryNotice));
});

test('packaging uses the pinned local vsce tool', () => {
  assert.equal(manifest.scripts.package, 'vsce package --no-dependencies');
  assert.equal(manifest.devDependencies['@vscode/vsce'], '3.9.2');
  assert.ok(!manifest.scripts.package.includes('npx'));
});

test('test script uses the cross-platform Node launcher', () => {
  assert.equal(manifest.scripts.test, 'node tools/run-tests.mjs');
  assert.ok(fs.existsSync(path.join(root, 'tools', 'run-tests.mjs')));
});

test('the marketplace icon remains reproducible', () => {
  const data = fs.readFileSync(path.join(root, manifest.icon));
  assert.ok(data.subarray(0, 8).equals(Buffer.from([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a])));
  assert.equal(data.readUInt32BE(16), 128);
  assert.equal(data.readUInt32BE(20), 128);
  assert.ok(fs.existsSync(path.join(root, 'tools', 'make_icon.py')));
});
