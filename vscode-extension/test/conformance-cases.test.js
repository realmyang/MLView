'use strict';
/**
 * Staging runner for the extension side of the conformance corpus (Campaign 1, contract 1g).
 * Each case in test/conformance/cases is self-contained: its files are materialised from
 * `text`, `base64` or `generate` into a fresh temporary workspace, `$sha256` placeholders are
 * replaced by digests, and `expect.extension` is asserted against validateWorkflow.
 * Stream E moves these cases to contracts/conformance/cases and replaces this runner.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { api } = require('./harness');

const CASES = path.join(__dirname, 'conformance', 'cases');
const AREAS = new Set(['shape', 'path', 'evidence', 'notebook', 'fingerprint', 'freshness', 'encoding', 'revision', 'size']);
const CASE_KEYS = new Set(['id', 'findings', 'description', 'files', 'artifact', 'document', 'raw', 'expect', 'divergence']);

function bytesOf(spec) {
  if (typeof spec.text === 'string') return Buffer.from(spec.text, 'utf8');
  if (typeof spec.base64 === 'string') return Buffer.from(spec.base64, 'base64');
  if (spec.generate && Number.isInteger(spec.generate.bytes) && typeof spec.generate.fill === 'string' && spec.generate.fill.length === 1)
    return Buffer.alloc(spec.generate.bytes, spec.generate.fill);
  throw new Error(`unsupported file spec ${JSON.stringify(spec)}`);
}
/** Replace every {"$sha256": {text|base64}} placeholder with the lowercase hex digest. */
function resolvePlaceholders(value) {
  if (Array.isArray(value)) return value.map(resolvePlaceholders);
  if (value && typeof value === 'object') {
    const keys = Object.keys(value);
    if (keys.length === 1 && keys[0] === '$sha256') return crypto.createHash('sha256').update(bytesOf(value.$sha256)).digest('hex');
    return Object.fromEntries(keys.map(key => [key, resolvePlaceholders(value[key])]));
  }
  return value;
}
function checkFormat(file, spec) {
  const stem = path.basename(file, '.json');
  assert.equal(spec.id, stem, 'id equals the file stem');
  assert.match(stem, /^[a-z]+-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*$/);
  assert.ok(AREAS.has(stem.split('-')[0]), `unknown area in ${stem}`);
  for (const key of Object.keys(spec)) assert.ok(CASE_KEYS.has(key), `unknown case key ${key}`);
  assert.ok(Array.isArray(spec.findings) && spec.findings.length > 0);
  assert.equal(typeof spec.description, 'string');
  assert.notEqual('document' in spec, 'raw' in spec, 'exactly one of document or raw');
  if ('raw' in spec) assert.equal(typeof spec.raw, 'string');
  else assert.ok(spec.document && typeof spec.document === 'object' && !Array.isArray(spec.document));
  for (const rel of Object.keys(spec.files || {})) {
    assert.ok(!rel.startsWith('/') && !rel.includes('\\') && !rel.split('/').some(part => part === '' || part === '.' || part === '..'), `file path ${rel} must be relative POSIX`);
  }
  assert.ok(['valid', 'invalid', 'skip'].includes(spec.expect.schema));
  for (const layer of ['helper', 'extension'])
    assert.ok(spec.expect[layer] === 'unverified' || (spec.expect[layer] && typeof spec.expect[layer] === 'object'), `expect.${layer}`);
  if (spec.divergence !== null) {
    assert.ok(Array.isArray(spec.divergence.layers) && Array.isArray(spec.divergence.findings) && typeof spec.divergence.note === 'string');
    assert.ok(['open', 'accepted'].includes(spec.divergence.status));
  }
  assert.ok(fs.statSync(file).size <= 100 * 1024, 'case files stay under 100 KB');
}

const files = fs.readdirSync(CASES).filter(name => name.endsWith('.json')).sort().map(name => path.join(CASES, name));

test('the staged corpus contains the extension-side cases', () => {
  const ids = files.map(file => path.basename(file, '.json'));
  for (const id of [
    'freshness-001-crlf-source-raw-hash',
    'freshness-002-bom-source-fresh',
    'freshness-003-latin1-inspected-with-key-fresh',
    'freshness-004-owned-key-changed-not-stale',
    'freshness-005-missing-tracked-file-with-key',
    'freshness-006-missing-inspected-without-key-verified',
    'shape-003-inspected-directory-unverified'
  ]) assert.ok(ids.includes(id), id);
});

for (const file of files) {
  const spec = JSON.parse(fs.readFileSync(file, 'utf8'));
  test(`conformance ${path.basename(file, '.json')}`, async (t) => {
    checkFormat(file, spec);
    if (spec.expect.extension === 'unverified') {
      t.skip('extension expectation not staged yet');
      return;
    }
    const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-conformance-')));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    for (const [rel, fileSpec] of Object.entries(spec.files || {})) {
      const target = path.join(root, ...rel.split('/'));
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, bytesOf(fileSpec));
    }
    let value;
    let parsed = true;
    if ('raw' in spec) {
      fs.writeFileSync(path.join(root, ...spec.artifact.split('/')), spec.raw);
      try { value = JSON.parse(spec.raw); } catch { parsed = false; }
    } else {
      value = resolvePlaceholders(spec.document);
      fs.writeFileSync(path.join(root, ...spec.artifact.split('/')), JSON.stringify(value, null, 2) + '\n');
    }
    let actual;
    if (!parsed) {
      actual = { ok: false, stale: [], issuePaths: ['$'] };
    } else {
      const result = await api.validateWorkflow(value, root);
      actual = {
        ok: !!result.value,
        stale: (result.value?.stale || []).map(entry => entry.rel).sort(),
        issuePaths: [...new Set(result.issues.map(issue => issue.path))].sort()
      };
    }
    const expected = spec.expect.extension;
    assert.deepEqual(actual, { ok: expected.ok, stale: [...expected.stale].sort(), issuePaths: [...new Set(expected.issuePaths)].sort() });
  });
}
