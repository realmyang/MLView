'use strict';
/**
 * Recorded artifacts are immutable evidence: every tracked *.mlview.json must keep passing the
 * extension's structural validation, and the shipped sample must validate fresh against the
 * repository root (which pins raw-byte hashing to the helper's recorded digests).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { api, REPO_ROOT } = require('./harness');

function recordedArtifacts() {
  const listed = spawnSync('git', ['ls-files', '-z', '--', '*.mlview.json'], { cwd: REPO_ROOT, encoding: 'utf8', shell: false });
  if (listed.status === 0 && listed.stdout) return listed.stdout.split('\0').filter(Boolean).sort();
  // Outside a git checkout, walk the two places recorded artifacts live.
  const found = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(path.join(REPO_ROOT, dir), { withFileTypes: true })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (entry.name.endsWith('.mlview.json')) found.push(rel);
    }
  };
  walk('evals/workflow');
  walk('samples');
  return found.sort();
}

test('every recorded artifact passes validateWorkflowStructure', () => {
  const files = recordedArtifacts();
  assert.ok(files.length >= 23, `expected at least 23 recorded artifacts, found ${files.length}`);
  assert.ok(files.includes('samples/configured_training.mlview.json'));
  const rejected = [];
  for (const rel of files) {
    const result = api.validateWorkflowStructure(JSON.parse(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8')));
    if (!result.document) rejected.push(`${rel}: ${result.issues.slice(0, 3).map(x => `${x.path} ${x.message}`).join('; ')}`);
  }
  assert.deepEqual(rejected, []);
});

test('recorded artifacts that fingerprinted installed MLView skill files keep those keys out of tracked files', () => {
  let owned = 0;
  for (const rel of recordedArtifacts()) {
    const doc = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, rel), 'utf8'));
    const tracked = new Set(api.trackedFiles(doc));
    for (const key of Object.keys(doc.verification?.files || {})) {
      if (api.isOwnedPath(key)) {
        owned++;
        assert.equal(tracked.has(key), false, `${rel}: ${key}`);
      }
    }
  }
  assert.ok(owned > 0, 'the recorded corpus contains owned fingerprint keys (CRIT-1)');
});

test('the shipped sample validates fresh against the repository root', async () => {
  const doc = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'samples', 'configured_training.mlview.json'), 'utf8'));
  const result = await api.validateWorkflow(doc, REPO_ROOT);
  assert.deepEqual(result.issues, []);
  assert.ok(result.value);
  assert.deepEqual(result.value.stale, []);
  assert.deepEqual(result.value.fingerprints, doc.verification.files);
});
