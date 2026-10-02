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
    extension: { packageJSON: { version: '0.3.0' } },
    globalState: vscode.__memento()
  };
}

// Viewer M3 (roadmap step 14), changed deliberately: activation registers a second command, MLView:
// Reveal in Diagram, the owner-approved widening of the manifest (see packaging.test.js). Its
// context key starts off, and nothing else is registered.
test('activation registers only the authored workflow surface and Reveal in Diagram', () => {
  vscode.__recorded.commands.clear();
  vscode.__recorded.serializers.clear();
  vscode.__recorded.contexts.clear();
  const ctx = context();
  extension.activate(ctx);
  assert.deepEqual([...vscode.__recorded.commands.keys()], ['mlview.openGeneratedDiagram', 'mlview.revealInDiagram']);
  assert.equal(vscode.__recorded.contexts.get('mlview.citedFile'), false, 'the cited-file key starts off');
  assert.ok(vscode.__recorded.serializers.has('mlview.authoredDiagram'));
  assert.ok(ctx.subscriptions.length >= 2);
  extension.deactivate();
});
