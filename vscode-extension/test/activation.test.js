'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
require('./harness.js');
const vscode = require('./mock-vscode.js');
const extension = require(path.join(__dirname, '..', 'out', 'extension.js'));

function context() {
  const extensionPath = path.join(__dirname, '..');
  return {
    subscriptions: [],
    extensionPath,
    extensionUri: vscode.Uri.file(extensionPath),
    extension: { packageJSON: { version: '0.2.0' } }
  };
}

test('activation registers only the authored workflow surface', () => {
  vscode.__recorded.commands.clear();
  vscode.__recorded.serializers.clear();
  const ctx = context();
  extension.activate(ctx);
  assert.deepEqual([...vscode.__recorded.commands.keys()], ['mlview.openGeneratedDiagram']);
  assert.ok(vscode.__recorded.serializers.has('mlview.authoredDiagram'));
  assert.ok(ctx.subscriptions.length >= 2);
  extension.deactivate();
});
