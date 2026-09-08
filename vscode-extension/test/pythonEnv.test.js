'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { api } = require('./harness.js');

const {
  buildCandidates,
  pickInterpreter,
  parseHandshake,
  meetsMinimum,
  isSchemaMismatch,
  schemaMismatchMessage,
  MIN_PYTHON
} = api;

const OK_CORE = { version: '0.1.0', schemaVersion: '1.0' };

function ok(executable, version = [3, 13], core = OK_CORE) {
  // pass `null` for "this interpreter has no mlview core"; `undefined` would take the default.
  return { kind: 'ok', executable, version, ...(core ? { core } : {}) };
}

test('the candidate chain is setting -> ms-python -> defaultInterpreterPath -> PATH', () => {
  const candidates = buildCandidates({
    settingPath: 'C:/py/setting/python.exe',
    msPythonPath: 'C:/py/conda/python.exe',
    defaultInterpreterPath: 'C:/py/default/python.exe'
  });
  assert.deepEqual(
    candidates.map((c) => `${c.source}:${c.command}${c.args.length ? ' ' + c.args.join(' ') : ''}`),
    [
      'setting:C:/py/setting/python.exe',
      'ms-python:C:/py/conda/python.exe',
      'defaultInterpreterPath:C:/py/default/python.exe',
      'path:python',
      'path:py -3',
      'path:python3'
    ]
  );
});

test('blank and duplicate candidates are skipped', () => {
  const candidates = buildCandidates({ settingPath: '   ', msPythonPath: 'python' });
  assert.deepEqual(candidates.map((c) => c.command), ['python', 'py', 'python3']);
  assert.equal(candidates[0].source, 'ms-python', 'the first "python" entry keeps its source');
});

test('the first candidate that is new enough AND has the core wins', async () => {
  const probed = [];
  const result = await pickInterpreter(buildCandidates({ settingPath: 'C:/py/old/python.exe' }), async (c) => {
    probed.push(c.command);
    if (c.command === 'C:/py/old/python.exe') {
      return { kind: 'too-old', version: [3, 8] };
    }
    if (c.command === 'python') {
      return ok('C:/py/path/python.exe');
    }
    return { kind: 'missing' };
  });
  assert.equal(result.interpreter.executable, 'C:/py/path/python.exe');
  assert.equal(result.interpreter.source, 'path');
  assert.equal(result.interpreter.hasCore, true);
  assert.deepEqual(probed, ['C:/py/old/python.exe', 'python']);
  assert.equal(result.attempts.length, 2, 'probing stops at the first usable interpreter');
});

test('an interpreter without the core is only a fallback, and is flagged', async () => {
  const result = await pickInterpreter(
    buildCandidates({ settingPath: 'C:/py/a/python.exe', msPythonPath: 'C:/py/b/python.exe' }),
    async (c) => {
      if (c.command === 'C:/py/a/python.exe') {
        return ok('C:/py/a/python.exe', [3, 12], null);
      }
      if (c.command === 'C:/py/b/python.exe') {
        return ok('C:/py/b/python.exe', [3, 11], OK_CORE);
      }
      return { kind: 'missing' };
    }
  );
  assert.equal(result.interpreter.executable, 'C:/py/b/python.exe');
  assert.equal(result.interpreter.hasCore, true);
});

test('when nothing has the core, the first valid interpreter is returned with hasCore false', async () => {
  const result = await pickInterpreter(buildCandidates({ settingPath: 'C:/py/a/python.exe' }), async (c) =>
    c.command === 'C:/py/a/python.exe' ? ok('C:/py/a/python.exe', [3, 12], null) : { kind: 'missing' }
  );
  assert.equal(result.interpreter.executable, 'C:/py/a/python.exe');
  assert.equal(result.interpreter.hasCore, false);
  assert.equal(result.attempts.length, 4, 'every candidate is probed before giving up');
});

test('no usable interpreter yields no interpreter and a full attempt log', async () => {
  const result = await pickInterpreter(buildCandidates({}), async () => ({
    kind: 'missing',
    detail: 'not found'
  }));
  assert.equal(result.interpreter, undefined);
  assert.equal(result.attempts.length, 3);
});

test('the minimum python version is 3.10', () => {
  assert.deepEqual([...MIN_PYTHON], [3, 10]);
  assert.equal(meetsMinimum([3, 10]), true);
  assert.equal(meetsMinimum([3, 13]), true);
  assert.equal(meetsMinimum([4, 0]), true);
  assert.equal(meetsMinimum([3, 9]), false);
  assert.equal(meetsMinimum([2, 7]), false);
});

test('the --version --json handshake is parsed defensively', () => {
  assert.deepEqual(parseHandshake('{"name":"mlview","version":"0.1.0","schemaVersion":"1.0"}'), {
    version: '0.1.0',
    schemaVersion: '1.0'
  });
  assert.deepEqual(parseHandshake('{"version":"0.2.1","schema_version":"1.0"}'), {
    version: '0.2.1',
    schemaVersion: '1.0'
  });
  assert.deepEqual(parseHandshake('mlview 0.1.0\n'), { version: '0.1.0' });
  assert.equal(parseHandshake('   '), undefined);
});

test('a schema major mismatch is detected and explained', () => {
  assert.equal(isSchemaMismatch({ version: '0.1.0', schemaVersion: '1.4' }), false);
  assert.equal(isSchemaMismatch({ version: '0.1.0', schemaVersion: '2.0' }), true);
  assert.equal(isSchemaMismatch({ version: '0.1.0' }), false);
  assert.equal(isSchemaMismatch(undefined), false);
  const message = schemaMismatchMessage('2.0');
  assert.match(message, /2\.0/);
  assert.match(message, /1\.0/);
});
