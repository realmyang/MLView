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
// context key, the list of cited files, starts empty.
// Viewer M4 (roadmap step 18), changed deliberately: activation also registers the read-only
// custom editor `mlview.diagram` (a *.mlview.json opens as its diagram), several editors per file
// allowed, and keeps the serializer of the earlier webview panel type, now only to reopen such a
// restored tab as the diagram editor. No other command, setting or provider is registered.
test('activation registers the authored workflow surface, Reveal in Diagram and the diagram editor', () => {
  vscode.__recorded.commands.clear();
  vscode.__recorded.serializers.clear();
  vscode.__recorded.contexts.clear();
  vscode.__recorded.customEditors.clear();
  const ctx = context();
  extension.activate(ctx);
  assert.deepEqual([...vscode.__recorded.commands.keys()], ['mlview.openGeneratedDiagram', 'mlview.revealInDiagram']);
  assert.deepEqual(vscode.__recorded.contexts.get('mlview.citedFiles'), [], 'the cited-files key starts empty');
  assert.deepEqual([...vscode.__recorded.customEditors.keys()], ['mlview.diagram']);
  assert.deepEqual(vscode.__recorded.customEditors.get('mlview.diagram').options, { supportsMultipleEditorsPerDocument: true });
  assert.deepEqual([...vscode.__recorded.serializers.keys()], ['mlview.authoredDiagram']);
  assert.equal(vscode.__recorded.watchers.length, 0, 'no file watcher until a diagram opens');
  assert.ok(ctx.subscriptions.length >= 2);
  extension.deactivate();
  assert.equal(vscode.__recorded.customEditors.size, 0, 'deactivation unregisters the editor');
});
