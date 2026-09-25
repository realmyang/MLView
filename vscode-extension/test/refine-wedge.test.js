'use strict';
/**
 * CRIT-2 regression (Campaign 1, section 4.3): the real MLView helper publishes revisions, the
 * panel sees them only through file-system watcher events (never `controller.open`, which resets
 * the lineage), and every prompt Refine copies names a parent the helper accepts.
 *
 * Needs Python 3.10+ (MLVIEW_PYTHON, else python3, else python). Skipped with a reason when none
 * is available, unless MLVIEW_REQUIRE_PYTHON=1, which turns a missing interpreter into a failure.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./panel-helpers');
const { api, vscode } = h;
const { REPO_ROOT } = require('./harness');

const HELPER = path.join(REPO_ROOT, 'skills', 'mlview', 'scripts', 'artifact.py');

function findPython() {
  for (const candidate of [process.env.MLVIEW_PYTHON, 'python3', 'python'].filter(Boolean)) {
    const probe = spawnSync(candidate, ['-c', 'import sys; sys.exit(sys.version_info < (3, 10))'], { encoding: 'utf8', shell: false });
    if (probe.status === 0) return candidate;
  }
  return undefined;
}

function draft(id, parent, inspected = ['train.py']) {
  return {
    workflowVersion: '1.0',
    title: 'Training entrypoint',
    producer: { kind: 'host-llm', host: 'claude-code' },
    revision: parent ? { id, parent } : { id },
    request: { question: 'What does train.py run?', scope: 'train.py' },
    phases: [{ id: 'train', label: 'Train' }],
    nodes: [{ id: 'step', label: `Run training step (${id})`, phase: 'train', basis: 'observed', evidence: ['ev-1'] }],
    edges: [],
    findings: [],
    evidence: [{ id: 'ev-1', file: 'train.py', line: 1, endLine: 1, quote: 'def train():' }],
    coverage: { status: 'scoped', summary: 'Read the training entrypoint.', inspectedFiles: inspected, limitations: [] }
  };
}

test('refine never wedges: every copied parent is one the real helper accepts', async (t) => {
  const python = findPython();
  if (!python) {
    if (process.env.MLVIEW_REQUIRE_PYTHON === '1') assert.fail('MLVIEW_REQUIRE_PYTHON=1 but no Python 3.10+ interpreter was found (set MLVIEW_PYTHON)');
    t.skip('no Python 3.10+ interpreter found; set MLVIEW_PYTHON to run the helper round trip');
    return;
  }
  vscode.__reset();
  const root = h.tempRoot('mlview-wedge-');
  const artifact = path.join(root, 'workflow.mlview.json');
  fs.mkdirSync(path.join(root, '.mlview', 'llm', 'run'), { recursive: true });
  fs.writeFileSync(path.join(root, 'train.py'), 'def train():\n    pass\n');
  vscode.__setWorkspaceFolders([root]);
  const publish = (doc) => {
    fs.writeFileSync(path.join(root, '.mlview', 'llm', 'run', 'draft.json'), JSON.stringify(doc, null, 2));
    const run = spawnSync(python, [HELPER, 'publish', '.mlview/llm/run/draft.json', '--workspace', root, '--output', 'workflow.mlview.json'], {
      cwd: root, encoding: 'utf8', shell: false, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' }
    });
    try {
      return JSON.parse(run.stdout);
    } catch {
      return assert.fail(`the helper printed no JSON (exit ${run.status}): ${run.stdout}${run.stderr}`);
    }
  };
  const published = (doc) => {
    const out = publish(doc);
    assert.equal(out.ok, true, `helper refused ${doc.revision.id}: ${JSON.stringify(out.errors)}`);
    return out;
  };
  const controller = new api.AuthoredDiagramController(h.context(), h.log());
  controller.register();
  t.after(() => {
    controller.dispose();
    fs.rmSync(root, { recursive: true, force: true });
  });
  let copies = 0;
  const refine = async (panel, intent, revisionId) => {
    panel.fire({ v: 1, type: 'refineWorkflow', revisionId, intent });
    await h.waitFor(() => vscode.__recorded.clipboardWrites.length > copies, 'refine prompt was not copied');
    copies = vscode.__recorded.clipboardWrites.length;
    return vscode.__recorded.clipboardWrites.at(-1);
  };
  const codes = (panel) => h.lastBanner(panel).codes || [];

  published(draft('r1'));
  await controller.open(vscode.Uri.file(artifact));
  const panel = vscode.__recorded.panels.at(-1);
  panel.fire({ v: 1, type: 'ready' });
  await h.tick();
  assert.equal(h.shownRevision(panel), 'r1');
  let r4Bytes;

  await t.test('1. CRIT-2 wedge (S1): an owned inspected entry never makes the refinement stale', async () => {
    published(draft('r2', 'r1', ['train.py', 'workflow.mlview.json']));
    const r2 = JSON.parse(fs.readFileSync(artifact, 'utf8'));
    t.diagnostic(`helper wrote an owned fingerprint key for the artifact: ${Object.prototype.hasOwnProperty.call(r2.verification.files, 'workflow.mlview.json')}`);
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r2');
    assert.equal(codes(panel).includes('stale'), false, 'the owned key is ignored, so r2 is fresh');
    published(draft('r3', 'r2'));
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r3');
    const prompt = await refine(panel, 'expand', 'r3');
    assert.match(prompt, /^Published revision on disk: r3\. If you publish, set revision\.parent to r3\.$/m);
    published(draft('r4', 'r3'));
    r4Bytes = fs.readFileSync(artifact);
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r4');
  });

  await t.test('2. viewer-only rejection (S1b): the prompt continues from the rejected file revision', async () => {
    const r5 = JSON.parse(r4Bytes.toString('utf8'));
    r5.revision = { id: 'r5', parent: 'r4' };
    r5.nodes[0].parent = null;
    fs.writeFileSync(artifact, JSON.stringify(r5, null, 2));
    await h.diskEvent(panel, 'change', artifact);
    assert.ok(codes(panel).includes('invalid'));
    assert.equal(h.shownRevision(panel), 'r4');
    const prompt = await refine(panel, 'challenge', 'r4');
    assert.match(prompt, /^The artifact file now holds revision r5, which the viewer could not display .* If you publish, set revision\.parent to r5 and fix those problems\.$/m);
    assert.ok(h.promptData(prompt).viewerRejection.some(line => /^\$\.nodes\[\d+\]\.parent: /.test(line)));
    published(draft('r6', 'r5'));
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r6');
    assert.equal(codes(panel).includes('invalid'), false);
  });

  await t.test('3. obsolete restore (S4): the prompt names the restored revision and asks the user', async () => {
    fs.writeFileSync(artifact, r4Bytes);
    await h.diskEvent(panel, 'change', artifact);
    assert.ok(codes(panel).includes('obsolete'));
    assert.equal(h.shownRevision(panel), 'r6');
    const prompt = await refine(panel, 'trace', 'r6');
    assert.match(prompt, /^The artifact file holds revision r4, which the displayed revision r6 already superseded, .* ask whether to continue from revision r4 before publishing\. If you publish, set revision\.parent to r4\.$/m);
    published(draft('r7', 'r4'));
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r7');
  });

  await t.test('4. dirty buffer at publish (S2): adopted from disk, jumps guarded by the buffer', async () => {
    const trainPath = path.join(root, 'train.py');
    vscode.__setDocument(trainPath, 'def fit():\n    pass\n');
    vscode.__setDirty(trainPath);
    published(draft('r8', 'r7'));
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r8');
    assert.ok(codes(panel).includes('dirty'));
    assert.equal(codes(panel).includes('stale'), false);
    panel.fire({ v: 1, type: 'openLocation', evidenceId: 'ev-1' });
    await h.waitFor(() => vscode.__recorded.messages.some(m => m[1] === 'MLView: unsaved changes in train.py no longer contain the lines cited by evidence ev-1; save or revert the file, then try again.'), 'the dirty buffer did not block the jump');
    assert.equal(vscode.__recorded.shownDocuments.length, 0);
  });

  await t.test('5. rapid double publish (S5): one event shows the newest revision with a lineage note', async () => {
    published(draft('r9', 'r8'));
    published(draft('r10', 'r9'));
    await h.diskEvent(panel, 'change', artifact);
    assert.equal(h.shownRevision(panel), 'r10');
    assert.ok(codes(panel).includes('lineage'));
    const prompt = await refine(panel, 'expand', 'r10');
    assert.match(prompt, /^Published revision on disk: r10\. If you publish, set revision\.parent to r10\.$/m);
    published(draft('r11', 'r10'));
  });
});
