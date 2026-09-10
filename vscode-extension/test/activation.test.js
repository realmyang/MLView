'use strict';
/**
 * Activation smoke test against the real `out/extension.js` bundle with a mocked `vscode`.
 *
 * REQUIREMENTS §11 expects activation to succeed with Copilot absent and to log
 * "chat API unavailable - participant not registered". That is exactly the situation here: the
 * mock exposes neither `vscode.chat` nor `vscode.lm`.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
require('./harness.js'); // installs the `vscode` -> mock resolve hook

const vscode = require('./mock-vscode.js');
const extension = require(path.join(__dirname, '..', 'out', 'extension.js'));

function makeContext() {
  const extensionPath = path.join(__dirname, '..');
  const state = new Map();
  return {
    subscriptions: [],
    extensionPath,
    extensionUri: vscode.Uri.file(extensionPath),
    extension: { packageJSON: { version: '0.1.0' } },
    workspaceState: {
      get: (key) => state.get(key),
      update: async (key, value) => void state.set(key, value)
    },
    globalState: {
      get: (key) => state.get(key),
      update: async (key, value) => void state.set(key, value)
    }
  };
}

test('activate registers every command unconditionally and never throws', () => {
  const recorded = vscode.__recorded;
  recorded.commands.clear();
  recorded.outputChannels.length = 0;
  const ctx = makeContext();

  extension.activate(ctx);

  assert.deepEqual(
    [...recorded.commands.keys()].sort(),
    [
      // MLV-P10's three suppression commands are driven by the code-action lightbulb, so
      // they are deliberately NOT contributed in package.json (they take arguments and
      // would be broken from the palette) - but they register unconditionally, here.
      'mlview.addIgnoreComment',
      // CONTRACTS.md 11.11 added the two scope commands; they register unconditionally too.
      'mlview.clearScope',
      'mlview.copyIgnoreComment',
      'mlview.disableRule',
      'mlview.exportHtml',
      // VIEW-07: the two picture exports; both are contributed AND registered here.
      'mlview.exportPng',
      'mlview.exportSvg',
      'mlview.refresh',
      'mlview.revealInDiagram',
      'mlview.scopeToSymbol',
      'mlview.selectInterpreter',
      'mlview.showIssues',
      'mlview.showOutput',
      'mlview.showRuleDoc',
      'mlview.visualize',
      'mlview.visualizeWorkspace'
    ]
  );
  assert.ok(ctx.subscriptions.length > 5, 'disposables are registered on the context');

  const channel = recorded.outputChannels.find((c) => c.name === 'MLView');
  assert.ok(channel, 'the MLView output channel is created');
  const text = channel.lines.join('\n');
  assert.match(text, /MLView 0\.1\.0 activating/);
  assert.match(text, /chat API unavailable - participant not registered/);
  assert.match(text, /language-model tool API unavailable/);
  assert.match(text, /commands, panel serializer, diagnostics, CodeLens and status bar registered/);

  extension.deactivate();
});

test('a status bar item and a diagnostic collection are created', () => {
  const recorded = vscode.__recorded;
  recorded.statusBarItems.length = 0;
  recorded.diagnosticCollections.length = 0;
  const ctx = makeContext();

  extension.activate(ctx);

  const item = recorded.statusBarItems[recorded.statusBarItems.length - 1];
  assert.ok(item, 'a status bar item is created');
  assert.equal(item.command, 'mlview.showIssues');
  assert.match(item.text, /MLView/);

  const collection = recorded.diagnosticCollections[recorded.diagnosticCollections.length - 1];
  assert.ok(collection, 'a diagnostic collection is created');
  assert.equal(collection.name, 'mlview');

  extension.deactivate();
});

test('the status bar summarises the issue counts', () => {
  const { api } = require('./harness.js');
  assert.equal(api.statusBarText({ low: 0, medium: 0, high: 0 }, false, false), '$(graph) MLView');
  assert.equal(
    api.statusBarText({ low: 4, medium: 6, high: 5 }, false, false),
    '$(graph) MLView: 5 high · 6 med · 4 low'
  );
  assert.equal(api.statusBarText({ low: 1, medium: 0, high: 0 }, false, false), '$(graph) MLView: 1 low');
  assert.match(api.statusBarText({ low: 0, medium: 0, high: 0 }, true, false), /sync~spin/);
  assert.match(api.statusBarText({ low: 0, medium: 0, high: 0 }, false, true), /error/);
});
