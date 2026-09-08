'use strict';
/**
 * VSX-R2-006 — the extension source must stay TEXT.
 *
 * `src/pythonEnv.ts` used to build its dedup key with two literal NUL bytes instead of the
 * escape sequence. That compiles and behaves correctly, but it makes the file binary as far as
 * every text tool is concerned: `grep -rn` reports "Binary file ... matches" with no lines,
 * `git diff` refuses to show hunks, and reviewer tooling silently skips one of the largest
 * files in the extension. This test is the cheap guard: no control byte other than tab, LF and
 * CR may appear in any source file we own.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const ALLOWED_CONTROL = new Set([0x09, 0x0a, 0x0d]);

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else if (entry.isFile()) {
      out.push(full);
    }
  }
  return out;
}

test('no source file contains a control byte other than tab, LF or CR', () => {
  const files = [...walk(path.join(ROOT, 'src')), ...walk(path.join(ROOT, 'test'))];
  assert.ok(files.length > 20, 'the walk found the sources');
  for (const file of files) {
    const data = fs.readFileSync(file);
    const offsets = [];
    for (let i = 0; i < data.length; i += 1) {
      const byte = data[i];
      if ((byte < 0x20 && !ALLOWED_CONTROL.has(byte)) || byte === 0x7f) {
        offsets.push(i);
      }
    }
    assert.deepEqual(
      offsets.slice(0, 5),
      [],
      `${path.relative(ROOT, file)} carries raw control bytes at ${offsets
        .slice(0, 5)
        .join(', ')} - use an escape sequence, not the byte itself`
    );
  }
});

test('every source file is valid UTF-8', () => {
  for (const file of walk(path.join(ROOT, 'src'))) {
    const data = fs.readFileSync(file);
    const text = data.toString('utf8');
    assert.ok(!text.includes('�'), `${path.relative(ROOT, file)} is not valid UTF-8`);
    assert.ok(!text.startsWith('﻿'), `${path.relative(ROOT, file)} starts with a BOM`);
  }
});

/**
 * R2-REG-07 - the repo's ~600-line file budget, asserted instead of remembered. Two files
 * crossed it silently in the scope/flow pass; splitting a module is cheap while the split is
 * still small, and expensive once every reviewer has learned to scroll past it.
 */
test('no source file grows past the ~600-line budget', () => {
  const over = [];
  for (const file of walk(path.join(ROOT, 'src'))) {
    const lines = fs.readFileSync(file, 'utf8').split('\n').length;
    if (lines > 600) {
      over.push(path.relative(ROOT, file).split(path.sep).join('/') + ' (' + lines + ' lines)');
    }
  }
  assert.deepEqual(over, [], 'split these before they grow further: ' + over.join(', '));
});
