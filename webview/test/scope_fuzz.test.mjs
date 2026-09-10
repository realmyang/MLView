/**
 * THE DIFFERENTIAL FUZZ HARNESS (HEALTH-02, CONTRACTS 11.30).
 *
 * `scope_parity.test.mjs` proves the two `project()` implementations agree on
 * ONE frozen 45-node document across 16 selectors. This file is the same
 * comparison against *generated* documents: `analyzer/tools/scope_fuzz.py`
 * builds schema-valid graphs (5..500 nodes, hierarchy depth, cross-stage
 * parents, ghosts, four-node issue anchoring, issues anchored on an edge whose
 * nodes are elsewhere, disconnected components, and — since Sprint 5 — rolled-up
 * documents carrying `rolledUp` counts and merged edges with a `weight` (11.46)
 * and multi-pipeline documents carrying a root `pipelines[]` block (11.47)),
 * picks random selectors across every scope kind at every legal depth
 * (`pipeline:` included), computes the PYTHON answer for each, and hands the
 * whole batch to one node process.
 *
 * `batch.digestExtras` names the fields the driver wants compared HERE rather
 * than inside the shared digest; `extrasOf` builds them and the Python
 * `extras_of` is its twin. In replay mode the same block is compared only when
 * the stored expectation carries one, so a promoted counterexample is never
 * measured against a key no Python side ever wrote.
 *
 * Two modes, and neither needs a browser:
 *
 * * **batch** (`MLVIEW_FUZZ_BATCH` set) - the fuzzer is driving. Every case is
 *   compared, a machine-readable report is written to `MLVIEW_FUZZ_REPORT` so
 *   the Python side can minimize and promote the counterexample, and each case
 *   is also emitted as a TAP assertion so a human sees which one moved.
 *   `MLVIEW_FUZZ_BUNDLE` points the port at a different build, which is how the
 *   fuzzer is proved to bite: a bundle with `rotateToCore` dropped must fail.
 * * **replay** (no `MLVIEW_FUZZ_BATCH`) - the promoted counterexamples in
 *   `contracts/scope.cases.json`'s `fuzzCases`, each carrying its own graph,
 *   checked against `contracts/scope.expected.json`. `MLVIEW_FUZZ_BUNDLE`
 *   works here too, so a promoted case can be shown to still catch the build it
 *   was found on. The battery grows; the fuzzer never replaces it.
 *
 * `digestOf` below is the JavaScript twin of `digest_of` in
 * `analyzer/tools/gen_scope_fixtures.py`. They are the only two places the
 * compared shape is written, and they must be edited together.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { existsSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEBVIEW_ROOT = join(HERE, '..');
const REPO_ROOT = join(WEBVIEW_ROOT, '..');
const DEFAULT_BUNDLE = join(WEBVIEW_ROOT, 'dist', 'mlview.js');
const CASES_PATH = join(REPO_ROOT, 'contracts', 'scope.cases.json');
const EXPECTED_PATH = join(REPO_ROOT, 'contracts', 'scope.expected.json');

const STAGE_KEYS = ['id', 'label', 'order', 'present', 'nodeCount', 'issueCounts', 'maxSeverity'];

/**
 * A jsdom window with a built bundle in it.
 *
 * Deliberately local rather than `helpers.loadBundle`: the fuzzer must be able
 * to aim the same comparison at a DIFFERENT bundle (`MLVIEW_FUZZ_BUNDLE`), and
 * `helpers.mjs` hard-codes `dist/mlview.js`.
 */
async function loadScopeApi(bundlePath) {
  const code = await readFile(bundlePath, 'utf8');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', () => undefined);
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url: 'https://mlview.test/',
    virtualConsole,
  });
  if (typeof dom.window.structuredClone !== 'function') {
    dom.window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
  }
  const script = dom.window.document.createElement('script');
  script.textContent = code;
  dom.window.document.head.appendChild(script);
  if (!dom.window.MLView) throw new Error('bundle did not define window.MLView: ' + bundlePath);
  return dom.window.MLView.__internal;
}

/**
 * The four members of an 11.47 D row that BOTH ports compute.
 *
 * `label` is not among them on purpose: the document's block carries one and the
 * viewer's chooser row derives its own name (`pipelines.name`), so comparing it
 * would report a shape decision as a divergence. Everything a reader counts on —
 * which entrypoint, how many nodes, how many of them are shared, and the
 * findings — is compared.
 */
function pipelineRow(row) {
  return {
    entrypoint: row.entrypoint,
    nodeCount: row.nodeCount,
    exclusiveCount: row.exclusiveCount,
    sharedCount: row.sharedCount,
    issueCounts: row.issueCounts,
  };
}

/**
 * The LATER fields the shared digest does not carry — the JavaScript twin of
 * `extras_of` in `analyzer/tools/scope_fuzz.py`.
 *
 * PERF-04 puts a `rolledUp` count on a node that swallowed its children and a
 * `weight` on an edge that swallowed its parallels; MLV-P12 puts a `pipelines[]`
 * block at the root. A port that projected the ids correctly and dropped the
 * count would otherwise pass. `extras` names exactly which of them to compare —
 * the Python driver probes its own twin and asks for the rest, so each field is
 * compared once and never twice.
 */
export function extrasOf(doc, extras) {
  const want = new Set(extras || []);
  const out = {};
  if (want.has('rolledUp')) {
    out.rolledUp = (doc.nodes || [])
      .filter((n) => n && n.rolledUp !== undefined)
      .map((n) => [n.id, n.rolledUp]);
  }
  if (want.has('weight')) {
    out.weight = (doc.edges || [])
      .filter((e) => e && e.weight !== undefined)
      .map((e) => [e.id, e.weight]);
  }
  if (want.has('pipelines')) {
    out.pipelines = doc.pipelines === undefined ? null : doc.pipelines;
  }
  return out;
}

/**
 * The comparable subset of a projected document — the JavaScript twin of
 * `digest_of` in `analyzer/tools/gen_scope_fixtures.py`, plus the `_extras`
 * block when the driver asked for one.
 *
 * The JSON round-trip is not cosmetic: objects built inside the jsdom realm
 * have a different `Object.prototype` and `assert/strict` compares prototypes,
 * so the comparison has to be about VALUES — the same round-trip
 * `scope_parity.test.mjs` makes for the same reason.
 */
export function digestOf(doc, extras) {
  const nodes = doc.nodes || [];
  const edges = doc.edges || [];
  const issues = doc.issues || [];
  const hasExtras = (extras || []).length > 0;
  return JSON.parse(
    JSON.stringify({
      nodes: nodes.map((n) => [n.id, n.viewRole === undefined ? null : n.viewRole, n.issueIds || []]),
      edges: edges.map((e) => [e.id, e.issueIds || []]),
      issues: issues.map((i) => [i.id, i.nodeIds || [], i.edgeIds || []]),
      stages: (doc.stages || []).map((s) => {
        const row = {};
        for (const key of STAGE_KEYS) row[key] = s[key] === undefined ? null : s[key];
        return row;
      }),
      stats: doc.stats === undefined ? null : doc.stats,
      view: doc.view === undefined ? null : doc.view,
      ...(hasExtras ? { _extras: extrasOf(doc, extras) } : {}),
    }),
  );
}

/** `project()`, or the contractual triple of the error it raised (11.1). */
function outcomeOf(api, graph, spec, depth, extras) {
  let scope;
  try {
    scope = api.parseScope(spec, depth === null || depth === undefined ? undefined : depth);
  } catch (err) {
    if (err && err.name === 'ScopeError') {
      return { kind: 'error', raisedBy: 'parse', error: { code: err.code, term: err.term, candidates: [...err.candidates] } };
    }
    throw err;
  }
  try {
    return { kind: 'project', digest: digestOf(api.project(graph, scope), extras) };
  } catch (err) {
    if (err && err.name === 'ScopeError') {
      return { kind: 'error', raisedBy: 'resolve', error: { code: err.code, term: err.term, candidates: [...err.candidates] } };
    }
    throw err;
  }
}

/**
 * Key-order-insensitive JSON equality, so this file's verdict and
 * `assert.deepEqual`'s can never disagree: two ports may write the same object
 * with its keys in a different order and still be the same document.
 */
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = canonical(value[key]);
    return out;
  }
  return value;
}

function sameJson(a, b) {
  return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
}

/** The first path at which two JSON values differ — the whole point of a report. */
function firstDifference(want, got, path = '') {
  if (sameJson(want, got)) return '';
  const shape = (v) => (Array.isArray(v) ? 'array' : v === null ? 'null' : typeof v);
  if (shape(want) !== shape(got) || shape(want) !== 'object') {
    if (Array.isArray(want) && Array.isArray(got)) {
      for (let i = 0; i < Math.max(want.length, got.length); i++) {
        const deeper = firstDifference(want[i], got[i], path + '[' + i + ']');
        if (deeper) return deeper;
      }
      return path + ': length ' + want.length + ' (python) vs ' + got.length + ' (typescript)';
    }
    return (path || 'value') + ': python ' + JSON.stringify(want) + ' vs typescript ' + JSON.stringify(got);
  }
  for (const key of new Set([...Object.keys(want || {}), ...Object.keys(got || {})])) {
    const deeper = firstDifference((want || {})[key], (got || {})[key], path + '.' + key);
    if (deeper) return deeper;
  }
  return path + ': differs';
}

const BATCH_PATH = process.env.MLVIEW_FUZZ_BATCH || '';

if (BATCH_PATH) {
  /* ── batch mode: the fuzzer is driving ─────────────────────────────── */
  const batch = JSON.parse(await readFile(BATCH_PATH, 'utf8'));
  const internal = await loadScopeApi(process.env.MLVIEW_FUZZ_BUNDLE || DEFAULT_BUNDLE);
  const api = internal.scope;
  // Which LATER fields this batch compares here rather than inside the shared
  // digest. The driver decides — see `digest_extras()` in scope_fuzz.py.
  const batchExtras = batch.digestExtras || [];
  const outcomes = [];
  const failures = [];

  for (const entry of batch.graphs || []) {
    // MLV-P12's relation, compared FIRST: `project()` carries the `pipelines[]`
    // block through verbatim (11.47 D), so a port that computes the relation
    // differently would never show up in a projection comparison. The viewer
    // recomputes it for its chooser, so the two answers are both live.
    const wantRows = entry.relation && entry.relation.pipelines;
    if (wantRows && internal.pipelines && typeof internal.pipelines.rows === 'function') {
      let gotRows = null;
      let relationDetail = '';
      try {
        gotRows = internal.pipelines.rows(entry.graph).map(pipelineRow);
      } catch (err) {
        relationDetail = 'the TypeScript relation threw ' + ((err && err.stack) || err);
      }
      const want = wantRows.map(pipelineRow);
      const relationOk = gotRows !== null && sameJson(want, gotRows);
      if (!relationOk) {
        relationDetail = relationDetail || firstDifference(want, gotRows);
        failures.push({
          graph: entry.name,
          case: entry.name + '/pipelines',
          kind: 'relation',
          spec: 'pipelines[] (11.47 A/D)',
          depth: null,
          detail: relationDetail,
        });
      }
      outcomes.push({
        name: entry.name + '/pipelines',
        ok: relationOk,
        want,
        got: gotRows,
        detail: relationDetail,
      });
    }
    for (const testCase of entry.cases || []) {
      let got = null;
      let detail = '';
      try {
        got = outcomeOf(api, entry.graph, testCase.spec, testCase.depth, batchExtras);
      } catch (err) {
        detail = 'the TypeScript port threw ' + ((err && err.stack) || err);
      }
      const ok = got !== null && sameJson(got, testCase.expect);
      if (!ok) {
        detail = detail || firstDifference(testCase.expect, got);
        failures.push({
          graph: entry.name,
          case: testCase.name,
          spec: testCase.spec,
          depth: testCase.depth === undefined ? null : testCase.depth,
          detail,
        });
      }
      outcomes.push({ name: testCase.name, ok, want: testCase.expect, got, detail });
    }
  }

  // Written BEFORE the assertions run: the report is what the Python side reads
  // to minimize and promote, and it must survive a failing run.
  if (process.env.MLVIEW_FUZZ_REPORT) {
    writeFileSync(
      process.env.MLVIEW_FUZZ_REPORT,
      JSON.stringify({ total: outcomes.length, failed: failures.length, failures }, null, 2),
      'utf8',
    );
  }

  for (const outcome of outcomes) {
    test('fuzz ' + outcome.name, () => {
      assert.deepEqual(outcome.got, outcome.want, outcome.detail);
    });
  }
} else {
  /* ── replay mode: the promoted counterexamples ─────────────────────── */
  const have = existsSync(CASES_PATH) && existsSync(EXPECTED_PATH);
  const cases = have ? JSON.parse(await readFile(CASES_PATH, 'utf8')) : {};
  const expected = have ? JSON.parse(await readFile(EXPECTED_PATH, 'utf8')) : {};
  const promoted = (cases.fuzzCases || []).slice();
  const answers = new Map((expected.fuzzCases || []).map((row) => [row.name, row]));

  const skip = !have
    ? 'contracts/scope.cases.json + scope.expected.json are not present'
    : promoted.length === 0
      ? 'no counterexamples promoted yet — run `python tools/verify.py --scopes --fuzz 2000`'
      : false;

  test('every promoted counterexample carries its own graph and an expectation', { skip }, () => {
    for (const row of promoted) {
      assert.ok(row.graph && Array.isArray(row.graph.nodes), row.name + ' carries its own graph');
      assert.ok(answers.has(row.name), 'contracts/scope.expected.json has fuzzCases entry ' + row.name);
    }
    assert.deepEqual(
      promoted.map((c) => c.name),
      (expected.fuzzCases || []).map((c) => c.name),
      'both files list the promoted counterexamples in the same order',
    );
  });

  // `MLVIEW_FUZZ_BUNDLE` works here too, so a promoted counterexample can be
  // aimed at the build it was found on and shown to still catch it.
  const api = skip ? null : (await loadScopeApi(process.env.MLVIEW_FUZZ_BUNDLE || DEFAULT_BUNDLE)).scope;
  for (const row of promoted) {
    test('promoted counterexample: ' + row.name + ' (' + row.spec + ')', { skip }, () => {
      const want = answers.get(row.name);
      // `gen_scope_fixtures.py` computes the expectation with the SHARED digest,
      // which carries no LATER field; a counterexample whose divergence lives in
      // one of them therefore travels in the CASE row (`expectExtras`), which
      // that generator passes through verbatim. Compare whichever is present —
      // never a key no Python side ever wrote.
      const wantExtras =
        (want.digest && want.digest._extras) || row.expectExtras || null;
      const extras = wantExtras ? Object.keys(wantExtras) : [];
      const got = outcomeOf(api, row.graph, row.spec, row.depth, extras);
      const expectation =
        want.kind === 'error'
          ? { kind: 'error', raisedBy: want.raisedBy, error: want.error }
          : { kind: 'project', digest: { ...want.digest, ...(wantExtras ? { _extras: wantExtras } : {}) } };
      assert.deepEqual(got, expectation, firstDifference(expectation, got));
    });
  }
}
