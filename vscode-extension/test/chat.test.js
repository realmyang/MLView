'use strict';
/**
 * The @mlview chat participant, exercised through its handler with a recording stream.
 *
 * The participant must never call a language model: `request.model` is deliberately a poison
 * object here, so any attempt to use it fails the test.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { api, readSampleGraph } = require('./harness.js');

const { handleChatRequest, PARTICIPANT_ID } = api;

function recordingStream() {
  const events = [];
  return {
    events,
    markdown: (value) => events.push({ kind: 'markdown', value: String(value) }),
    anchor: (location, title) => events.push({ kind: 'anchor', location, title }),
    button: (command) => events.push({ kind: 'button', command }),
    progress: (value) => events.push({ kind: 'progress', value }),
    reference: () => {},
    filetree: () => {},
    push: () => {},
    text: () => events.push({ kind: 'markdown', value: '' })
  };
}

const POISON_MODEL = new Proxy(
  {},
  {
    get() {
      throw new Error('the MLView participant must never touch a language model');
    }
  }
);

function makeRequest(command, prompt = '') {
  return { command, prompt, model: POISON_MODEL, references: [], toolReferences: [] };
}

function makeDeps(graph, calls = []) {
  return {
    calls,
    log: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {}, trace: () => {} },
    core: {
      analyze: async () => {
        calls.push('analyze');
        return graph;
      }
    },
    options: () => ({ minSeverity: 'low', disabledRules: [] }),
    showDiagram: async () => calls.push('showDiagram')
  };
}

const TOKEN = { isCancellationRequested: false, onCancellationRequested: () => ({ dispose() {} }) };

const markdownOf = (stream) =>
  stream.events.filter((e) => e.kind === 'markdown').map((e) => e.value).join('');

test('the participant id matches the manifest', () => {
  assert.equal(PARTICIPANT_ID, 'mlview.chat');
});

test('/issues streams every finding with a clickable file:line anchor', async () => {
  const graph = readSampleGraph();
  const stream = recordingStream();
  const deps = makeDeps(graph);
  await handleChatRequest(makeRequest('issues'), stream, TOKEN, deps);

  const unsuppressed = graph.issues.filter((i) => !i.suppressed);
  const anchors = stream.events.filter((e) => e.kind === 'anchor');
  assert.ok(anchors.length >= unsuppressed.length, 'one anchor per finding at least');
  for (const anchor of anchors) {
    assert.match(anchor.title, /.+:\d+$/);
    assert.equal(anchor.location.uri.scheme, 'file');
    assert.ok(anchor.location.range.start.line >= 0);
  }

  const markdown = markdownOf(stream);
  assert.match(markdown, /issue\(s\)/);
  assert.match(markdown, /\*Fix:\*/);
  assert.match(markdown, /HIGH · MLV/);
  assert.match(markdown, /no model call, no network/);

  const buttons = stream.events.filter((e) => e.kind === 'button').map((e) => e.command.command);
  assert.ok(buttons.includes('mlview.showIssues'));
  assert.ok(buttons.includes('mlview.visualizeWorkspace'));
  assert.deepEqual(deps.calls, ['analyze']);
});

test('an anchor range is the 1-based -> 0-based conversion of the issue loc', async () => {
  const graph = readSampleGraph();
  const stream = recordingStream();
  await handleChatRequest(makeRequest('issues'), stream, TOKEN, makeDeps(graph));
  const first = graph.issues
    .filter((i) => !i.suppressed)
    .sort((a, b) => ({ low: 0, medium: 1, high: 2 })[b.severity] - ({ low: 0, medium: 1, high: 2 })[a.severity])[0];
  const anchor = stream.events.find((e) => e.kind === 'anchor');
  assert.equal(anchor.title, `${first.loc.file}:${first.loc.line}`);
  assert.equal(anchor.location.range.start.line, first.loc.line - 1);
  assert.equal(anchor.location.range.start.character, first.loc.col);
});

test('/diagram opens the panel and summarises the pipeline', async () => {
  const stream = recordingStream();
  const deps = makeDeps(readSampleGraph());
  await handleChatRequest(makeRequest('diagram'), stream, TOKEN, deps);
  assert.ok(deps.calls.includes('showDiagram'));
  const markdown = markdownOf(stream);
  assert.match(markdown, /Opened the MLView diagram/);
  assert.match(markdown, /Pipeline: /);
  assert.match(markdown, /nodes\*\*/);
});

test('/explain resolves a rule code and offers its offline doc', async () => {
  const graph = readSampleGraph();
  const code = graph.issues[0].code;
  const stream = recordingStream();
  await handleChatRequest(makeRequest('explain', `what is ${code}?`), stream, TOKEN, makeDeps(graph));
  const markdown = markdownOf(stream);
  assert.match(markdown, new RegExp(`\\*\\*${code}\\*\\* fired`));
  const button = stream.events
    .filter((e) => e.kind === 'button')
    .find((e) => e.command.command === 'mlview.showRuleDoc');
  assert.ok(button, 'the rule doc button is offered');
  assert.deepEqual(button.command.arguments, [code]);
});

test('/explain resolves a stage name', async () => {
  const stream = recordingStream();
  await handleChatRequest(
    makeRequest('explain', 'tell me about the train stage'),
    stream,
    TOKEN,
    makeDeps(readSampleGraph())
  );
  assert.match(markdownOf(stream), /\*\*Train\*\* contains \d+ node\(s\)/);
});

test('/explain with no target explains what it accepts', async () => {
  const stream = recordingStream();
  await handleChatRequest(makeRequest('explain', 'hello'), stream, TOKEN, makeDeps(readSampleGraph()));
  assert.match(markdownOf(stream), /Name a rule code/);
});

test('the free-form path answers locally and points at the commands', async () => {
  const stream = recordingStream();
  await handleChatRequest(
    makeRequest(undefined, 'is my training loop correct?'),
    stream,
    TOKEN,
    makeDeps(readSampleGraph())
  );
  const markdown = markdownOf(stream);
  assert.match(markdown, /`\/diagram`/);
  assert.match(markdown, /`\/issues`/);
  assert.match(markdown, /no model call, no network/);
  assert.ok(stream.events.some((e) => e.kind === 'anchor'));
});

test('an analyzer failure is reported in chat with remediation buttons', async () => {
  const stream = recordingStream();
  const deps = makeDeps(readSampleGraph());
  deps.core.analyze = async () => {
    throw new Error('No Python 3.10+ interpreter found.');
  };
  await handleChatRequest(makeRequest('issues'), stream, TOKEN, deps);
  assert.match(markdownOf(stream), /could not analyze this workspace: No Python 3\.10\+/);
  const buttons = stream.events.filter((e) => e.kind === 'button').map((e) => e.command.command);
  assert.deepEqual(buttons, ['mlview.showOutput', 'mlview.selectInterpreter']);
});

test('a workspace with no findings still answers usefully', async () => {
  const graph = readSampleGraph();
  graph.issues = [];
  const stream = recordingStream();
  await handleChatRequest(makeRequest('issues'), stream, TOKEN, makeDeps(graph));
  assert.match(markdownOf(stream), /No MLView issues were detected/);
});
