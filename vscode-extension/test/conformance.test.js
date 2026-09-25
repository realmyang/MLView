'use strict';
/**
 * Extension layer of the WorkflowDocument conformance corpus (contracts/conformance/README.md).
 *
 * Every case in contracts/conformance/cases is self-contained: its files are materialised from
 * `text`, `base64` or `generate` into a fresh realpath'd temporary workspace, `$sha256`
 * placeholders become digests, and the artifact is written next to them (`raw` verbatim, else the
 * document as indented JSON). The artifact is then read the way the panel reads a candidate
 * (readArtifactFile, strict UTF-8 that keeps a BOM, JSON.parse) and checked with validateWorkflow
 * against `expect.extension`.
 *
 * With Python 3.10+ (MLVIEW_PYTHON, else python3, else python; required when
 * MLVIEW_REQUIRE_PYTHON=1) it also asks contracts/conformance/helper_bridge.py for the helper and
 * schema results to assert the parity invariant P1-P3 on actual results, and runs the round trip:
 * the real helper publishes each eligible case, and the published bytes must load fresh here.
 * tools/test_workflow_conformance.py runs the schema and helper layers on their own.
 *
 * These are local contract checks, not semantic accuracy or live-host validation.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { api, REPO_ROOT } = require('./harness');

const CONFORMANCE = path.join(REPO_ROOT, 'contracts', 'conformance');
const CASES_DIR = path.join(CONFORMANCE, 'cases');
const BRIDGE = path.join(CONFORMANCE, 'helper_bridge.py');
const HELPER = path.join(REPO_ROOT, 'skills', 'mlview', 'scripts', 'artifact.py');
const EXAMPLE = path.join(REPO_ROOT, 'skills', 'mlview', 'references', 'workflow-example.json');
const AREAS = new Set(['shape', 'path', 'evidence', 'notebook', 'fingerprint', 'freshness', 'encoding', 'revision', 'size']);

const caseFiles = fs.readdirSync(CASES_DIR).filter(name => name.endsWith('.json')).sort().map(name => path.join(CASES_DIR, name));
const cases = caseFiles.map(file => ({ file, spec: JSON.parse(fs.readFileSync(file, 'utf8')) }));

function findPython() {
  for (const candidate of [process.env.MLVIEW_PYTHON, 'python3', 'python'].filter(Boolean)) {
    const probe = spawnSync(candidate, ['-c', 'import sys; sys.exit(sys.version_info < (3, 10))'], { encoding: 'utf8', shell: false });
    if (probe.status === 0) return candidate;
  }
  return undefined;
}
/** The Python interpreter, or undefined after skipping `t` (a failure when MLVIEW_REQUIRE_PYTHON=1). */
function pythonOrSkip(t) {
  const python = findPython();
  if (python) return python;
  if (process.env.MLVIEW_REQUIRE_PYTHON === '1') assert.fail('MLVIEW_REQUIRE_PYTHON=1 but no Python 3.10+ interpreter was found (set MLVIEW_PYTHON)');
  t.skip('no Python 3.10+ interpreter found; set MLVIEW_PYTHON to compare with the helper');
  return undefined;
}

function bytesOf(spec) {
  const keys = Object.keys(spec);
  assert.equal(keys.length, 1, `file spec ${JSON.stringify(spec)}`);
  if (typeof spec.text === 'string') return Buffer.from(spec.text, 'utf8');
  if (typeof spec.base64 === 'string') return Buffer.from(spec.base64, 'base64');
  const g = spec.generate;
  if (g && Number.isInteger(g.bytes) && g.bytes >= 0 && typeof g.fill === 'string' && g.fill.length === 1 && g.fill.charCodeAt(0) < 128)
    return Buffer.alloc(g.bytes, g.fill);
  throw new Error(`unsupported file spec ${JSON.stringify(spec)}`);
}
/** Replace every {"$sha256": <file spec>} placeholder with the lowercase hex digest. */
function resolvePlaceholders(value) {
  if (Array.isArray(value)) return value.map(resolvePlaceholders);
  if (value && typeof value === 'object') {
    const keys = Object.keys(value);
    if (keys.length === 1 && keys[0] === '$sha256') return crypto.createHash('sha256').update(bytesOf(value.$sha256)).digest('hex');
    return Object.fromEntries(keys.map(key => [key, resolvePlaceholders(value[key])]));
  }
  return value;
}
const sorted = (values) => [...new Set(values)].sort();
const at = (root, rel) => path.join(root, ...rel.split('/'));

/** Materialise a case into a fresh realpath'd temporary workspace (removed after `t`). */
function materialise(t, spec, { artifact = true } = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'mlview-conformance-')));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const [rel, fileSpec] of Object.entries(spec.files)) {
    fs.mkdirSync(path.dirname(at(root, rel)), { recursive: true });
    fs.writeFileSync(at(root, rel), bytesOf(fileSpec));
  }
  if (artifact) {
    fs.mkdirSync(path.dirname(at(root, spec.artifact)), { recursive: true });
    fs.writeFileSync(at(root, spec.artifact), 'raw' in spec ? spec.raw : JSON.stringify(resolvePlaceholders(spec.document), null, 2) + '\n');
  }
  return root;
}

/** Read and validate the artifact exactly as the panel reads a candidate revision. */
async function loadArtifact(root, rel) {
  const read = await api.readArtifactFile(at(root, rel));
  assert.equal(read.kind, 'bytes', `artifact read: ${JSON.stringify(read)}`);
  let value;
  try {
    value = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(read.bytes));
  } catch {
    return { ok: false, stale: [], issuePaths: ['$'] };
  }
  const result = await api.validateWorkflow(value, root);
  return {
    ok: !!result.value,
    stale: (result.value?.stale || []).map(entry => entry.rel).sort(),
    issuePaths: sorted(result.issues.map(issue => issue.path)),
    issues: result.issues,
    value,
    fingerprints: result.value?.fingerprints
  };
}
const extensionView = (actual) => ({ ok: actual.ok, stale: actual.stale, issuePaths: actual.issuePaths });
const expectedExtension = (expected) => ({ ok: expected.ok, stale: [...expected.stale].sort(), issuePaths: sorted(expected.issuePaths) });

test('the corpus is committed, complete and free of open divergences', () => {
  assert.ok(cases.length >= 24, `expected the staged cases and more, found ${cases.length}`);
  assert.equal(fs.existsSync(path.join(__dirname, 'conformance')), false, 'the staging directory is gone');
  assert.equal(fs.existsSync(path.join(__dirname, 'conformance-cases.test.js')), false, 'the staging runner is gone');
  for (const { file, spec } of cases) {
    const stem = path.basename(file, '.json');
    assert.equal(spec.id, stem, 'id equals the file stem');
    assert.match(stem, /^[a-z]+-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.ok(AREAS.has(stem.split('-')[0]), `unknown area in ${stem}`);
    assert.notEqual('document' in spec, 'raw' in spec, `${stem}: exactly one of document or raw`);
    for (const layer of ['helper', 'extension'])
      assert.ok(spec.expect[layer] && typeof spec.expect[layer] === 'object', `${stem}: expect.${layer} must be verified`);
    assert.ok(['valid', 'invalid', 'skip'].includes(spec.expect.schema), `${stem}: expect.schema`);
    if (spec.divergence !== null) assert.equal(spec.divergence.status, 'accepted', `${stem}: no open divergence may remain`);
    assert.ok(fs.statSync(file).size <= 100 * 1024, `${stem}: case files stay under 100 KB`);
  }
});

for (const { spec } of cases) {
  test(`extension layer: ${spec.id}`, async (t) => {
    const root = materialise(t, spec);
    const actual = await loadArtifact(root, spec.artifact);
    assert.deepEqual(extensionView(actual), expectedExtension(spec.expect.extension), JSON.stringify(actual.issues || []));
  });
}

test('helper and extension satisfy the parity invariant on actual results (helper_bridge.py)', async (t) => {
  const python = pythonOrSkip(t);
  if (!python) return;
  const run = spawnSync(python, [BRIDGE], { cwd: REPO_ROOT, encoding: 'utf8', shell: false, maxBuffer: 64 * 1024 * 1024 });
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stderr, '');
  const bridge = JSON.parse(run.stdout);
  let compared = 0;
  for (const { spec } of cases) {
    const helper = bridge.cases[spec.id]?.helper;
    assert.ok(helper, `${spec.id}: no helper result from the bridge`);
    const expected = spec.expect.helper;
    assert.deepEqual(
      { ok: helper.ok, codes: helper.codes, warnings: helper.warnings, stale: helper.stale },
      { ok: expected.ok, codes: sorted(expected.codes), warnings: sorted(expected.warnings), stale: sorted(expected.stale) },
      `${spec.id}: helper result`
    );
    if (expected.fingerprints !== null) assert.deepEqual(helper.fingerprints, resolvePlaceholders(expected.fingerprints), `${spec.id}: helper fingerprints`);
    const schema = bridge.cases[spec.id].schema ?? spec.expect.schema;
    if (spec.expect.schema !== 'skip') assert.equal(schema, spec.expect.schema, `${spec.id}: schema layer`);
    if (spec.divergence !== null) continue;
    const extension = await loadArtifact(materialise(t, spec), spec.artifact);
    if (extension.stale.length === 0) {
      compared++;
      assert.equal(helper.ok, extension.ok, `${spec.id}: P1 helper.ok === extension.ok`);
    }
    if (helper.ok && extension.ok && extension.stale.length === 0)
      assert.deepEqual(extension.fingerprints, helper.fingerprints, `${spec.id}: P2 fingerprints`);
    if (helper.ok && extension.ok && spec.expect.schema !== 'skip')
      assert.equal(schema, 'valid', `${spec.id}: P3 accepted documents are schema-valid`);
  }
  assert.ok(compared > 0);
});

test('round trip: every artifact the helper publishes loads fresh in the extension', async (t) => {
  const python = pythonOrSkip(t);
  if (!python) return;
  let ran = 0;
  for (const { spec } of cases) {
    if (!spec.expect.helper.ok || spec.divergence !== null || 'raw' in spec || 'verification' in spec.document) continue;
    ran++;
    const root = materialise(t, spec, { artifact: false });
    fs.mkdirSync(path.join(root, '.mlview', 'llm', 'run'), { recursive: true });
    fs.writeFileSync(path.join(root, '.mlview', 'llm', 'run', 'draft.json'), JSON.stringify(resolvePlaceholders(spec.document), null, 2));
    const run = spawnSync(python, [HELPER, 'publish', '.mlview/llm/run/draft.json', '--workspace', root, '--output', spec.artifact], {
      cwd: root, encoding: 'utf8', shell: false
    });
    assert.equal(run.stderr, '', `${spec.id}: helper stderr`);
    assert.equal(run.status, 0, `${spec.id}: ${run.stdout}`);
    assert.equal(JSON.parse(run.stdout).ok, true);
    const loaded = await loadArtifact(root, spec.artifact);
    assert.deepEqual(loaded.issues, [], `${spec.id}: extension issues`);
    assert.equal(loaded.ok, true, spec.id);
    assert.deepEqual(loaded.stale, [], `${spec.id}: stale`);
    assert.deepEqual(loaded.fingerprints, loaded.value.verification.files, `${spec.id}: fingerprints === verification.files`);
  }
  assert.ok(ran >= 10, `expected at least 10 round-trip cases, ran ${ran}`);
});

test('recorded-artifact suite: the bundled skill example is valid and fresh in the extension', async (t) => {
  const example = JSON.parse(fs.readFileSync(EXAMPLE, 'utf8'));
  assert.deepEqual(api.validateWorkflowStructure(example).issues, []);
  const root = materialise(t, { files: { 'train.py': { text: 'def train():\n' } }, artifact: 'workflow.mlview.json', raw: JSON.stringify(example, null, 2) + '\n' });
  const loaded = await loadArtifact(root, 'workflow.mlview.json');
  assert.deepEqual(loaded.issues, []);
  assert.equal(loaded.ok, true);
  assert.deepEqual(loaded.stale, []);
});
