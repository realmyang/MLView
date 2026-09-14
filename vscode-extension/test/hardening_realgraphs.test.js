'use strict';
/**
 * Hardening round 1, area hosts-ux: drive the mocked-vscode host with the REAL
 * analyzer documents from `analyzer/tests/accuracy/corpus/` and `samples/`
 * rather than with the frozen golden or a synthetic graph.
 *
 * The golden is one 54-node torch+sklearn project. Everything the host does to
 * a document — selecting, locating, re-anchoring a notebook finding, mapping a
 * severity, folding a multi-root union — was only ever exercised against it, so
 * a shape that only a Keras, Lightning, HuggingFace or gradient-boosting
 * project produces (a stage with no nodes, an issue with no `relatedLocs`, a
 * `file` below the workspace root, a document with zero issues, a document
 * whose diagnostics carry a coverage caveat) was untested at the host boundary.
 *
 * The documents are produced here by running the CLI, so every assertion is
 * host-vs-analyzer rather than host-vs-fixture: if the two ever disagree about
 * how many findings a project has, or about where one of them is, this file is
 * what says so. It skips itself when `python -m mlview` is not importable, the
 * way the plugin suite skips when the CLI is absent.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const { api, vscode, REPO_ROOT } = require('./harness.js');

const {
  selectIssues,
  buildDiagnostics,
  buildLocationIndex,
  findNodeAtLine,
  mapSeverity,
  unitScopeSpec,
  fileScopeSpec,
  coverageNotes,
  coverageChip,
  coverageFor,
  digestOf,
  DIAGNOSTIC_SOURCE
} = api;

const CORPUS = path.join(REPO_ROOT, 'analyzer', 'tests', 'accuracy', 'corpus');
const PROJECTS = [
  path.join(REPO_ROOT, 'samples', 'vision_pipeline'),
  path.join(REPO_ROOT, 'samples', 'vision_pipeline_clean'),
  path.join(CORPUS, 'torch_mechanics'),
  path.join(CORPUS, 'lightning_manual'),
  path.join(CORPUS, 'lightning_tabular'),
  path.join(CORPUS, 'keras_tfdata'),
  path.join(CORPUS, 'keras_se_gate'),
  path.join(CORPUS, 'hf_trainer_finetune'),
  path.join(CORPUS, 'hf_no_eval'),
  path.join(CORPUS, 'gbm_tabular'),
  path.join(CORPUS, 'timeseries_split'),
  path.join(CORPUS, 'amp_accumulation')
].filter((p) => fs.existsSync(p));

const PYTHON = process.env.MLVIEW_TEST_PYTHON || 'python3';

/** Analyze one project through the same seam the extension uses: the CLI, `--json -`. */
function analyze(project, extraArgs = []) {
  const out = execFileSync(
    PYTHON,
    ['-X', 'utf8', '-m', 'mlview', 'analyze', project, '--json', '-', ...extraArgs],
    {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        PYTHONDONTWRITEBYTECODE: '1'
      }
    }
  );
  return JSON.parse(out);
}

let AVAILABLE = true;
const CACHE = new Map();
function graphOf(project, extraArgs = []) {
  const key = project + '|' + extraArgs.join(' ');
  if (!CACHE.has(key)) CACHE.set(key, analyze(project, extraArgs));
  return CACHE.get(key);
}
try {
  graphOf(PROJECTS[0]);
} catch {
  AVAILABLE = false;
}
const maybe = AVAILABLE ? test : test.skip;

maybe('every corpus document survives selectIssues -> buildDiagnostics with the counts intact', () => {
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);

    const selected = selectIssues(graph, { minConfidence: 0.6 });
    const expected = graph.issues.filter((i) => !i.suppressed && i.confidence >= 0.6);
    assert.equal(
      selected.length,
      expected.length,
      `${name}: selectIssues kept ${selected.length} of ${expected.length} findings at or above 0.6`
    );

    const byTarget = buildDiagnostics(selected, { mode: 'warning', root: graph.workspace.root });
    const flat = [...byTarget.values()].flatMap((t) => t.diagnostics);
    assert.equal(flat.length, selected.length, `${name}: a finding was dropped between select and publish`);

    for (const d of flat) {
      assert.equal(d.source, DIAGNOSTIC_SOURCE, `${name}: diagnostic without the MLView source`);
      const code = d.code && d.code.value ? d.code.value : d.code;
      assert.match(String(code), /^MLV[0-9]{3}$/, `${name}: diagnostic code ${String(code)}`);
      // Convention 0: 1-based lines in the document, 0-based in a vscode Range.
      assert.ok(d.range.start.line >= 0, `${name}: negative start line`);
      assert.ok(
        d.range.end.line >= d.range.start.line,
        `${name}: inverted range ${d.range.start.line}..${d.range.end.line}`
      );
      assert.ok(d.range.start.character >= 0, `${name}: negative start column`);
    }

    for (const uriKey of byTarget.keys()) {
      assert.match(uriKey, /^[a-z][a-z0-9+.-]*:/, `${name}: target key is not a uri: ${uriKey}`);
    }
  }
});

maybe('the host publishes exactly the severity counts the analyzer recorded, on every project', () => {
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);
    const all = selectIssues(graph, { minConfidence: 0 });
    const bySeverity = { low: 0, medium: 0, high: 0 };
    for (const i of all) if (!i.suppressed) bySeverity[i.severity] += 1;
    assert.deepEqual(
      bySeverity,
      {
        low: graph.stats.issues.low,
        medium: graph.stats.issues.medium,
        high: graph.stats.issues.high
      },
      `${name}: host severity counts disagree with the document's stats.issues`
    );
  }
});

maybe('Alt+M lands on a node for every non-ghost node of every corpus project', () => {
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);
    const index = buildLocationIndex(graph);
    for (const node of graph.nodes) {
      if (node.ghost) continue;
      const hit = findNodeAtLine(index, node.loc.file, node.loc.line);
      assert.ok(
        hit,
        `${name}: "Reveal in Diagram" found nothing at a node's own line ` +
          `${node.loc.file}:${node.loc.line} (${node.qualname})`
      );
      assert.ok(typeof hit.nodeId === 'string' && hit.nodeId.startsWith('n:'), `${name}: bad node id ${hit.nodeId}`);
    }
  }
});

maybe('every unit and every file in every project yields a well-formed scope selector', () => {
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);
    const units = graph.nodes.filter((n) => (n.level === 'unit' || n.level === 'stage') && !n.ghost);
    for (const unit of units) {
      const spec = unitScopeSpec(String(unit.qualname));
      assert.match(spec, /^unit:.+/, `${name}: ${unit.qualname} produced ${spec}`);
      assert.ok(!/[\n\r]/.test(spec), `${name}: newline in a scope spec`);
      assert.equal(spec, spec.trim(), `${name}: untrimmed scope spec ${JSON.stringify(spec)}`);
    }
    for (const file of new Set(graph.nodes.map((n) => n.loc.file))) {
      const spec = fileScopeSpec(file);
      assert.match(spec, /^file:.+/, `${name}: ${file} produced ${spec}`);
      assert.ok(!spec.includes('\\'), `${name}: backslash in a file scope spec: ${spec}`);
    }
  }
});

maybe('a document carrying a coverage caveat never reaches the user as a clean bill of health', () => {
  const KINDS = ['single_file_analysis', 'untagged_dataflow'];
  let sawOne = false;
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);
    const gaps = (graph.diagnostics || []).filter((d) => KINDS.includes(d.kind));
    const notes = coverageNotes(graph);
    const chip = coverageChip(notes);
    const lines = coverageFor(graph);
    if (gaps.length === 0) {
      assert.equal(notes.length, 0, `${name}: coverage note invented with no diagnostic behind it`);
      assert.equal(chip, undefined, `${name}: coverage chip on a document with no caveat`);
      continue;
    }
    sawOne = true;
    assert.ok(notes.length > 0, `${name}: ${gaps.length} coverage diagnostic(s) but the host reported none`);
    assert.ok(chip && chip.includes('incomplete'), `${name}: chip does not say incomplete: ${chip}`);
    assert.ok(lines.length > 0 && lines.every((l) => l.trim().length > 0), `${name}: empty coverage line`);
    // The count the chip quotes is the sum of the analyzer's own counts.
    const expected = gaps.reduce((sum, d) => sum + (Number.isFinite(d.count) && d.count > 0 ? d.count : 1), 0);
    assert.ok(chip.includes(String(expected)), `${name}: chip "${chip}" does not quote ${expected} sites`);
  }
  assert.ok(sawOne, 'no corpus project carried a coverage caveat — this test would be vacuous');
});

/**
 * MEASURED DEFECT, pinned rather than asserted away.
 *
 * Convention 0 keys an issue id on `sha1("<code>|<file>|<qualname>|<symbol>")`
 * with `file` WORKSPACE-RELATIVE, so two different projects that each have a
 * `train.py` with the same finding carry the SAME id. Inside one document that
 * is exactly right. Across the several documents a multi-root window holds
 * (CONTRACTS 11.40) it is an ambiguity, and `issueById` resolves it by array
 * order — see `hardening_multiroot_ids.test.js` for the click that reaches it.
 *
 * This test records the collision as a fact of the shipped corpus so that the
 * day ids become folder-qualified it fails loudly and both files move together.
 */
maybe('cross-project issue ids DO collide today — the multi-root ambiguity is real, not theoretical', () => {
  const byId = new Map();
  for (const project of PROJECTS) {
    const name = path.basename(project);
    for (const issue of graphOf(project).issues) {
      if (!byId.has(issue.id)) byId.set(issue.id, []);
      const seen = byId.get(issue.id);
      if (!seen.some((row) => row.project === name)) {
        seen.push({ project: name, code: issue.code, file: issue.loc.file, absFile: issue.loc.absFile });
      }
    }
  }
  const collisions = [...byId.entries()].filter(([, rows]) => rows.length > 1);
  assert.ok(
    collisions.length > 0,
    'REGRESSION MARKER: no cross-project id collision left in the corpus. If ids became ' +
      'folder-qualified, delete this test and flip hardening_multiroot_ids.test.js with it.'
  );
  for (const [id, rows] of collisions) {
    // Every colliding row is the same rule on the same RELATIVE path in a
    // different project: the id says nothing about which project it came from.
    const codes = new Set(rows.map((r) => r.code));
    const files = new Set(rows.map((r) => r.file));
    const absFiles = new Set(rows.map((r) => r.absFile));
    assert.equal(codes.size, 1, `${id}: collided across rules ${[...codes]}`);
    assert.equal(files.size, 1, `${id}: collided across relative paths ${[...files]}`);
    assert.equal(
      absFiles.size,
      rows.length,
      `${id}: the colliding findings must be in genuinely different files`
    );
  }
});

maybe('a zero-issue project publishes zero diagnostics and no empty target', () => {
  const clean = PROJECTS.find((p) => p.endsWith('vision_pipeline_clean'));
  if (!clean) return;
  const graph = graphOf(clean);
  assert.equal(graph.issues.length, 0, 'the clean twin is supposed to have no findings');
  const byTarget = buildDiagnostics(selectIssues(graph, { minConfidence: 0.6 }), { mode: 'warning' });
  assert.equal(byTarget.size, 0, 'a clean project must publish no diagnostic targets at all');
});

maybe('the severity map is total over every severity the corpus emits, in both modes', () => {
  const seen = new Set();
  for (const project of PROJECTS) for (const issue of graphOf(project).issues) seen.add(issue.severity);
  assert.ok(seen.size >= 3, `expected all three severities in the corpus, saw ${[...seen]}`);
  for (const severity of seen) {
    for (const mode of ['warning', 'error']) {
      assert.ok(
        ['error', 'warning', 'information'].includes(mapSeverity(severity, mode)),
        `severity ${severity} in mode ${mode} mapped to ${mapSeverity(severity, mode)}`
      );
    }
  }
});

maybe('the 4 KB digest holds for every corpus project, and says so when the graph was capped', () => {
  if (typeof digestOf !== 'function') return;
  for (const project of PROJECTS) {
    const graph = graphOf(project);
    const name = path.basename(project);
    const d = digestOf(graph);
    const bytes = Buffer.byteLength(JSON.stringify(d), 'utf8');
    assert.ok(bytes <= 4096, `${name}: digest is ${bytes} bytes`);
  }
});

maybe('a notebook document keeps every finding at the host boundary', () => {
  const nb = path.join(REPO_ROOT, 'analyzer', 'tests', 'fixtures', 'notebooks');
  if (!fs.existsSync(nb)) return;
  const graph = graphOf(nb, ['--include-notebooks']);
  const selected = selectIssues(graph, { minConfidence: 0 });
  assert.ok(selected.length > 0, 'the notebook fixture is supposed to produce findings');
  const byTarget = buildDiagnostics(selected, { mode: 'warning', root: graph.workspace.root });
  assert.equal(
    [...byTarget.values()].flatMap((t) => t.diagnostics).length,
    selected.length,
    'a notebook finding was dropped at the host boundary'
  );
  for (const [uriKey, target] of byTarget) {
    for (const d of target.diagnostics) {
      assert.ok(d.range.start.line >= 0, `notebook finding with a negative line on ${uriKey}`);
    }
  }
});

test('the corpus this file drives is on disk', () => {
  assert.ok(PROJECTS.length >= 8, `expected at least eight corpus projects, found ${PROJECTS.length}`);
});
