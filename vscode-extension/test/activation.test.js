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

// Activation registers two commands, MLView: Open Generated Diagram and MLView: Reveal in Diagram
// (its context key, the list of cited files, starts empty); the read-only custom editor
// `mlview.diagram` (a *.mlview.json opens as its diagram), several editors per file allowed; and
// the serializer of the `mlview.authoredDiagram` webview panel type, which reopens a restored tab
// of that type as the diagram editor. No other command, custom editor or serializer is registered,
// and no file is watched until a diagram opens.
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
