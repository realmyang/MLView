'use strict';
/**
 * H3 — `analysisProgress`, finally sent by a host.
 *
 * The frame is written by `analyzer/src/mlview/core/progress.py` to **stderr**
 * (stdout purity is a frozen gate), one per analyzed file, throttled to 50 ms with a
 * guaranteed final frame:
 *
 *     {"t":"progress","done":3,"total":45,"file":"src/train.py"}
 *
 * Three properties are what make it safe to turn on: the flag is passed only when a
 * panel is live, ordinary stderr still reaches the output channel byte for byte, and
 * a frame that arrives after the run already failed is dropped rather than drawing a
 * progress bar over an error banner.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { api } = require('./harness.js');
const { parseProgressLine, ProgressSplitter, PROGRESS_PREFIX, buildAnalyzeArgs } = api;

const REPO_ROOT = path.join(__dirname, '..', '..');

const BASE = { paths: ['/repo'], maxFiles: 500, maxNodes: 400, exclude: [] };

// ------------------------------------------------------------------ the flag

test('--progress-json is added only when a progress sink was supplied', () => {
  const quiet = buildAnalyzeArgs(BASE);
  assert.ok(!quiet.includes('--progress-json'), 'the headless argv must not change');
  const loud = buildAnalyzeArgs({ ...BASE, progress: true });
  assert.deepEqual(loud.slice(0, quiet.length), quiet, 'the flag is appended, never inserted');
  assert.deepEqual(loud.slice(quiet.length), ['--progress-json']);
});

test('the flag this extension passes is the flag the analyzer declares', () => {
  // A typo here is invisible until a real analyzer rejects it with exit 1.
  const parser = path.join(REPO_ROOT, 'analyzer', 'src', 'mlview', 'cli_parser.py');
  if (!fs.existsSync(parser)) {
    return; // an extension-only checkout
  }
  assert.match(fs.readFileSync(parser, 'utf8'), /"--progress-json"/);
});

// ----------------------------------------------------------------- the parse

test('a well-formed frame parses, and nothing else does', () => {
  assert.deepEqual(parseProgressLine('{"t":"progress","done":3,"total":45,"file":"a/b.py"}'), {
    done: 3,
    total: 45,
    file: 'a/b.py'
  });
  assert.deepEqual(parseProgressLine('{"t":"progress","done":45,"total":45}'), {
    done: 45,
    total: 45
  });
  assert.equal(PROGRESS_PREFIX, '{"t":"progress"');
});

test('ordinary stderr is never mistaken for a frame', () => {
  for (const line of [
    'mlview: WARNING could not parse train.py',
    'Traceback (most recent call last):',
    '{"t":"other","done":1,"total":2}',
    '{"t":"progress" but not json',
    '',
    '   '
  ]) {
    assert.equal(parseProgressLine(line), undefined, line);
  }
});

test('a malformed frame is rejected rather than rendered as nonsense', () => {
  assert.equal(parseProgressLine('{"t":"progress","done":"3","total":45}'), undefined);
  assert.equal(parseProgressLine('{"t":"progress","done":-1,"total":45}'), undefined);
  assert.equal(parseProgressLine('{"t":"progress","total":45}'), undefined);
  // done > total would draw 451 of 445; clamp instead of trusting it.
  assert.deepEqual(parseProgressLine('{"t":"progress","done":99,"total":45}'), {
    done: 45,
    total: 45
  });
});

// -------------------------------------------------------------- the splitter

function split(chunks) {
  const frames = [];
  const text = [];
  const splitter = new ProgressSplitter(
    (f) => frames.push(f),
    (t) => text.push(t)
  );
  for (const chunk of chunks) {
    splitter.push(chunk);
  }
  splitter.flush();
  return { frames, log: text.join('') };
}

test('frames are peeled off and every other byte still reaches the log', () => {
  const { frames, log } = split([
    'mlview: INFO starting\n',
    '{"t":"progress","done":1,"total":3,"file":"a.py"}\n',
    '{"t":"progress","done":2,"total":3,"file":"b.py"}\n',
    'mlview: WARNING b.py failed to parse\n',
    '{"t":"progress","done":3,"total":3,"file":"c.py"}\n'
  ]);
  assert.deepEqual(frames.map((f) => f.done), [1, 2, 3]);
  assert.equal(log, 'mlview: INFO starting\nmlview: WARNING b.py failed to parse\n');
});

test('a frame split across two chunks is still one frame', () => {
  const { frames, log } = split(['{"t":"progress","done":7,', '"total":9,"file":"x.py"}\n']);
  assert.deepEqual(frames, [{ done: 7, total: 9, file: 'x.py' }]);
  assert.equal(log, '', 'a half-arrived frame must not be logged as garbage');
});

test('a partial NON-frame line reaches the log immediately, not at exit', () => {
  const frames = [];
  const text = [];
  const splitter = new ProgressSplitter((f) => frames.push(f), (t) => text.push(t));
  splitter.push('Traceback (most recent call last):');
  assert.equal(text.join(''), 'Traceback (most recent call last):',
    'a crashing analyzer must not hold its last line hostage');
  splitter.flush();
  assert.deepEqual(frames, []);
});

test('an unterminated frame at exit is log output, not a lost frame', () => {
  const { frames, log } = split(['{"t":"progress","done":1']);
  assert.deepEqual(frames, []);
  assert.equal(log, '{"t":"progress","done":1');
});

test('the real analyzer frame format round-trips through the parser', () => {
  // `frame_text` in core/progress.py: compact separators, key order t,done,total,file.
  const produced = JSON.stringify({ t: 'progress', done: 12, total: 445, file: 'src/train.py' })
    .replace(/, /g, ',')
    .replace(/": /g, '":');
  assert.deepEqual(parseProgressLine(produced), { done: 12, total: 445, file: 'src/train.py' });
});
