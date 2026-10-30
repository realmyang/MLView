'use strict';
/**
 * Whole documents: every sample diagram samples/*.mlview.json, at least one, and the eight
 * generated test documents of contracts/conformance/documents/workspace, listed by name. Each must
 * keep passing the extension's structural validation. Each sample diagram must validate fresh
 * against the repository root, and each test document against its workspace (which pins raw-byte
 * hashing to the digests the helper wrote).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api, REPO_ROOT } = require('./harness');

const SAMPLES = fs.readdirSync(path.join(REPO_ROOT, 'samples'))
  .filter(name => name.endsWith('.mlview.json'))
  .sort()
  .map(name => `samples/${name}`);
const WORKSPACE = 'contracts/conformance/documents/workspace';
const TEST_DOCUMENTS = [
  'd01-minimal', 'd02-notebook', 'd03-two-files', 'd04-loop',
  'd05-groups', 'd06-refinement', 'd07-multi-file', 'd08-dense',
];
const LISTED = [...SAMPLES, ...TEST_DOCUMENTS.map(name => `${WORKSPACE}/${name}.mlview.json`)];

const read = rel => JSON.parse(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8'));

test('the test workspace holds exactly the listed test documents', () => {
  const found = fs.readdirSync(path.join(REPO_ROOT, WORKSPACE)).filter(name => name.endsWith('.mlview.json')).sort();
  assert.deepEqual(found, TEST_DOCUMENTS.map(name => `${name}.mlview.json`));
});

test('every sample diagram and every test document pass validateWorkflowStructure', () => {
  assert.ok(SAMPLES.length >= 1);
  const rejected = [];
  for (const rel of LISTED) {
    const result = api.validateWorkflowStructure(read(rel));
    if (!result.document) rejected.push(`${rel}: ${result.issues.slice(0, 3).map(x => `${x.path} ${x.message}`).join('; ')}`);
  }
  assert.deepEqual(rejected, []);
});

test('every sample diagram validates fresh against the repository root', async () => {
  assert.ok(SAMPLES.length >= 1);
  for (const rel of SAMPLES) {
    const doc = read(rel);
    const result = await api.validateWorkflow(doc, REPO_ROOT);
    assert.deepEqual(result.issues, [], rel);
    assert.ok(result.value, rel);
    assert.deepEqual(result.value.stale, [], rel);
    assert.deepEqual(result.value.fingerprints, doc.verification.files, rel);
  }
});

test('every test document validates fresh against its workspace', async () => {
  for (const name of TEST_DOCUMENTS) {
    const doc = read(`${WORKSPACE}/${name}.mlview.json`);
    const result = await api.validateWorkflow(doc, path.join(REPO_ROOT, WORKSPACE));
    assert.deepEqual(result.issues, [], name);
    assert.ok(result.value, name);
    assert.deepEqual(result.value.stale, [], name);
    assert.deepEqual(result.value.fingerprints, doc.verification.files, name);
  }
});
