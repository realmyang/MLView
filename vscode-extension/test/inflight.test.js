'use strict';
/**
 * VSX-R2-002 — the in-flight registry must only ever forget its OWN child.
 *
 * Supersede is synchronous while a child's terminal callback is not, so a killed run's late
 * callback used to unregister the run that had already replaced it. From that moment the
 * running analyzer was untracked: `dispose()` (i.e. `deactivate()`) could not kill it, `cancel()`
 * was a no-op, and the next request for the same scope started a SECOND analyzer instead of
 * superseding the first — so the older run could finish last and republish a stale graph.
 *
 * `child_process.execFile` is stubbed with children whose termination this test drives by hand,
 * which is the only way to place a late callback exactly between a supersede and a dispose.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const cp = require('node:child_process');

const { api } = require('./harness.js'); // installs the `vscode` -> mock hook
const { CoreClient, CoreError } = api;

const EXECUTABLE = 'C:/mlview-test/python.exe';
const REQUEST = {
  scope: 'workspace',
  paths: ['C:/mlview-test-workspace'],
  cwd: 'C:/mlview-test-workspace',
  settings: { maxFiles: 500, maxNodes: 400, exclude: [] }
};

const log = {
  info() {},
  warn() {},
  error() {},
  debug() {},
  trace() {},
  raw() {},
  show() {},
  dispose() {}
};

const stubEnv = {
  resolve: async () => ({
    ok: true,
    interpreter: {
      executable: EXECUTABLE,
      args: [],
      source: 'path',
      version: [3, 13],
      hasCore: true
    }
  })
};

const realExecFile = cp.execFile;

/** Replace execFile with children this test terminates by hand; returns the child list. */
function installControllableExecFile() {
  const children = [];
  cp.execFile = function (_file, args, options, callback) {
    const done = typeof options === 'function' ? options : callback;
    const child = {
      args,
      killCalls: 0,
      killed: false,
      exitCode: null,
      stderr: { setEncoding() {}, on() {} },
      stdout: { setEncoding() {}, on() {} },
      on() {},
      kill() {
        child.killCalls += 1;
        child.killed = true;
      },
      /** Play the child's terminal callback, whenever the test wants it. */
      finish(err, stdout = '', stderr = '') {
        done(err, stdout, stderr);
      }
    };
    children.push(child);
    return child;
  };
  return children;
}

/** Let `analyze` get as far as `execFile` (it awaits the interpreter resolution first). */
const settle = async () => {
  for (let i = 0; i < 4; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};

const isCancelled = (err) => err instanceof CoreError && err.kind === 'cancelled';

test('a superseded run does not unregister its replacement, so dispose() still kills it', async () => {
  const children = installControllableExecFile();
  try {
    const client = new CoreClient(stubEnv, log);

    const runA = client.analyze(REQUEST);
    await settle();
    assert.equal(children.length, 1, 'run A spawned');

    const runB = client.analyze(REQUEST);
    await settle();
    assert.equal(children.length, 2, 'run B spawned');
    assert.equal(children[0].killCalls, 1, 'B superseded A');

    // A's terminal callback arrives LATE - after B was registered under the same scope key.
    children[0].finish(new Error('terminated'));
    await assert.rejects(runA, isCancelled);
    await settle();

    // deactivate(): CoreClient.dispose() -> cancelAll(). B is the run that is actually running.
    client.dispose();
    assert.equal(
      children[1].killCalls,
      1,
      'dispose() must kill the running analyzer; a leaked python process outlives the window'
    );
    children[1].finish(new Error('terminated'));
    await assert.rejects(runB, isCancelled);
  } finally {
    cp.execFile = realExecFile;
  }
});

test('single-flight survives a supersede: the third request kills the second', async () => {
  const children = installControllableExecFile();
  try {
    const client = new CoreClient(stubEnv, log);

    const runA = client.analyze(REQUEST);
    await settle();
    const runB = client.analyze(REQUEST);
    await settle();
    children[0].finish(new Error('terminated')); // A's late callback
    await assert.rejects(runA, isCancelled);
    await settle();

    const runC = client.analyze(REQUEST);
    await settle();
    assert.equal(children.length, 3, 'run C spawned');
    assert.equal(
      children[1].killCalls,
      1,
      'C must supersede B; two concurrent analyzers let the older run publish last'
    );
    children[1].finish(new Error('terminated'));
    await assert.rejects(runB, isCancelled);

    client.dispose();
    assert.equal(children[2].killCalls, 1, 'C is still tracked');
    children[2].finish(new Error('terminated'));
    await assert.rejects(runC, isCancelled);
  } finally {
    cp.execFile = realExecFile;
  }
});

test('cancel(scope) still reaches the run that replaced a superseded one', async () => {
  const children = installControllableExecFile();
  try {
    const client = new CoreClient(stubEnv, log);
    const runA = client.analyze(REQUEST);
    await settle();
    const runB = client.analyze(REQUEST);
    await settle();
    children[0].finish(new Error('terminated'));
    await assert.rejects(runA, isCancelled);
    await settle();

    client.cancel('workspace');
    assert.equal(children[1].killCalls, 1, 'cancel() must not be a no-op after a supersede');
    children[1].finish(new Error('terminated'));
    await assert.rejects(runB, isCancelled);
    client.dispose();
  } finally {
    cp.execFile = realExecFile;
  }
});
