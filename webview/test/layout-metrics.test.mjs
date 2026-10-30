// The layout-metrics dev tool (tools/layout-metrics.mjs), run as a command and imported as a
// module. What is checked: the command runs on the sample configured_training
// (samples/configured_training.mlview.json) and reports every summary key at every panel width,
// and when its path goes through a symlink; it measures every repo-held document and exits 1 when
// it cannot read one; each measure counts what it says on a scene small enough to work out by hand;
// the baseline holds exactly the repo-held documents, with the step and connection counts of the
// tracked files; and the bundle carries none of the tool.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  BASELINE_FILE, TOOL_ID, WIDTHS, devDocuments, makeCamera, measureLayout, repoDocuments, run, walkCamera, walkStep,
} from '../tools/layout-metrics.mjs';
import { DIST_JS, REPO_ROOT, WEBVIEW_ROOT } from './helpers.mjs';

const SAMPLE = join(REPO_ROOT, 'samples', 'configured_training.mlview.json');
const TOOL = join(WEBVIEW_ROOT, 'tools', 'layout-metrics.mjs');
// The sample diagrams, read from the folder here and not from the tool.
const SAMPLE_NAMES = readdirSync(join(REPO_ROOT, 'samples')).filter((file) => file.endsWith('.mlview.json')).map((file) => file.slice(0, -'.mlview.json'.length)).sort();
// The documents the tool reads from files, by the name it gives them: every sample diagram and
// the eight generated test documents of contracts/conformance/documents.
const TEST_DOCUMENTS = ['d01-minimal', 'd02-notebook', 'd03-two-files', 'd04-loop', 'd05-groups', 'd06-refinement', 'd07-multi-file', 'd08-dense'];
const FILES = {
  ...Object.fromEntries(SAMPLE_NAMES.map((name) => ['sample ' + name, join(REPO_ROOT, 'samples', name + '.mlview.json')])),
  ...Object.fromEntries(TEST_DOCUMENTS.map((name) => ['doc ' + name, join(REPO_ROOT, 'contracts', 'conformance', 'documents', 'workspace', name + '.mlview.json')])),
};

/** Every `a.b.c` path of an object's leaves (arrays are leaves). */
const keyPaths = (value, prefix = '') => (value && typeof value === 'object' && !Array.isArray(value)
  ? Object.entries(value).flatMap(([k, v]) => keyPaths(v, prefix ? prefix + '.' + k : k))
  : [prefix]).sort();

const box = (id, x, y, w = 20, h = 20) => ({ id, x, y, w, h, group: false, parent: null, lane: 'p' });
const line = (...xy) => xy.map(([x, y]) => ({ x, y }));
const scene = (nodes, edges, extra = {}) => ({ width: 400, height: 300, lanes: [], nodes, edges, overlays: [], restHidden: [], ...extra });

test('the command measures the sample configured_training and reports every summary key at every panel width', () => {
  const out = spawnSync(process.execPath, [TOOL, '--no-repo', '--json', SAMPLE], { encoding: 'utf8' });
  assert.equal(out.status, 0, out.stderr);
  const report = JSON.parse(out.stdout);
  assert.equal(report.tool, TOOL_ID);
  assert.equal(report.documents.length, 1);
  const s = report.documents[0].summary;
  assert.ok(s, report.documents[0].error);
  for (const key of ['crossings', 'crossingsAtRest', 'cardHits', 'cardHitCables', 'unrelatedOverlap']) assert.equal(typeof s[key], 'number', key);
  assert.deepEqual(Object.keys(s.uncertain).sort(), ['cables', 'drawnOn', 'hiddenHalf', 'inTrunk']);
  assert.deepEqual(Object.keys(s.labels).sort(), ['alwaysHidden', 'alwaysOn', 'atRest', 'crossedByUnrelated']);
  assert.deepEqual(Object.keys(s.perPanel), WIDTHS);
  const doc = JSON.parse(readFileSync(SAMPLE, 'utf8'));
  const notObserved = [...doc.nodes, ...doc.edges, ...(doc.findings || [])].filter((x) => x.basis && x.basis !== 'observed').length;
  for (const w of WIDTHS) {
    const p = s.perPanel[w];
    assert.deepEqual(Object.keys(p).sort(), ['firstViewCards', 'uncertainFramable045', 'walkAll', 'walkAllClaims', 'walkNotObserved', 'walkNotObservedClaims']);
    for (const v of Object.values(p)) assert.ok(Number.isFinite(v), w + ': ' + JSON.stringify(p));
    // Every claim is walked once; the Not observed walk holds exactly the inferred and unresolved ones.
    assert.equal(p.walkAllClaims, doc.nodes.length + doc.edges.length + (doc.findings || []).length);
    assert.equal(p.walkNotObservedClaims, notObserved);
  }
});

test('the command measures every repo-held document: the default ones and the eight test documents', () => {
  const out = spawnSync(process.execPath, [TOOL, '--dev', '--json'], { encoding: 'utf8' });
  assert.equal(out.status, 0, out.stderr);
  const report = JSON.parse(out.stdout);
  assert.deepEqual(report.documents.map((d) => d.name), [...repoDocuments(), ...devDocuments()].map((d) => d.name));
  // Every sample diagram, the four synthetic documents and the eight test documents.
  assert.ok(SAMPLE_NAMES.includes('configured_training'));
  assert.deepEqual(report.documents.filter((d) => d.name.startsWith('sample ')).map((d) => d.name), SAMPLE_NAMES.map((name) => 'sample ' + name));
  assert.equal(report.documents.length, SAMPLE_NAMES.length + 4 + TEST_DOCUMENTS.length);
  for (const d of report.documents) assert.ok(d.summary, d.name + ': ' + d.error);
});

test('the command exits 1 when it cannot read a document, after printing the rest', () => {
  const missing = join(REPO_ROOT, 'samples', 'no-such-document.mlview.json');
  const out = spawnSync(process.execPath, [TOOL, '--no-repo', SAMPLE, missing], { encoding: 'utf8' });
  assert.equal(out.status, 1, out.stderr);
  assert.match(out.stdout, /\| configured_training \|/);
  assert.match(out.stdout, /no-such-document: not measured \(ENOENT/);
  assert.match(out.stderr, /^layout-metrics: not measured: no-such-document$/m);
  const json = spawnSync(process.execPath, [TOOL, '--no-repo', '--json', missing], { encoding: 'utf8' });
  assert.equal(json.status, 1, json.stderr);
  assert.match(JSON.parse(json.stdout).documents[0].error, /ENOENT/);
});

test('the command runs when its path goes through a directory symlink', (t) => {
  // Node gives the entry module its real path and leaves the argument as typed, so a check that
  // compares the two as written takes the tool for an import: no output, exit 0, any option.
  const dir = mkdtempSync(join(tmpdir(), 'mlview-layout-metrics-'));
  try {
    const link = join(dir, 'webview');
    try {
      symlinkSync(WEBVIEW_ROOT, link, 'dir');
    } catch (err) {
      t.skip('no symlink can be created here (' + (err && err.code) + ')');
      return;
    }
    const tool = join(link, 'tools', 'layout-metrics.mjs');
    const help = spawnSync(process.execPath, [tool, '--help'], { encoding: 'utf8' });
    assert.equal(help.status, 0, help.stderr);
    assert.match(help.stdout, /^Usage: node tools\/layout-metrics\.mjs/);
    const unknown = spawnSync(process.execPath, [tool, '--nonsense'], { encoding: 'utf8' });
    assert.equal(unknown.status, 2);
    assert.match(unknown.stderr, /unknown option --nonsense/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('a crossing is counted once, and not where two cables meet at a shared port', () => {
  const nodes = [box('a', 0, 0), box('b', 200, 0), box('c', 100, -100), box('d', 100, 100)];
  const across = { id: 'ab', source: 'a', target: 'b', points: line([20, 10], [200, 10]), basis: 'observed' };
  const down = { id: 'cd', source: 'c', target: 'd', points: line([110, -80], [110, 100]), basis: 'observed' };
  const fromPort = { id: 'ad', source: 'a', target: 'd', points: line([20, 10], [20, 110], [100, 110]), basis: 'observed' };
  const m = measureLayout(scene(nodes, [across, down, fromPort]));
  assert.equal(m.crossings.cables, 1);
  assert.equal(m.crossings.atRest, 1);
});

test('a route through a card that is neither of its ends is a card hit', () => {
  const nodes = [box('a', 0, 0), box('b', 200, 0), box('m', 90, 0)];
  const m = measureLayout(scene(nodes, [{ id: 'ab', source: 'a', target: 'b', points: line([20, 10], [200, 10]), basis: 'observed' }]));
  assert.deepEqual(m.throughCards, { hits: 1, cables: 1, groupFrameHits: 0 });
  const clear = measureLayout(scene(nodes, [{ id: 'ab', source: 'a', target: 'b', points: line([20, 10], [40, 10], [40, 40], [180, 40], [180, 10], [200, 10]), basis: 'observed' }]));
  assert.equal(clear.throughCards.hits, 0);
});

test('the overlap split counts a shared run with an unrelated cable, not with one from the same source', () => {
  const nodes = [box('a', 0, 0), box('b', 200, 0), box('c', 0, 100), box('d', 200, 100)];
  const ab = { id: 'ab', source: 'a', target: 'b', points: line([20, 10], [200, 10]), basis: 'observed' };
  // c -> d runs on top of a -> b for 100 px: 200 px of the 180 + 380 px of cable lie on an unrelated cable.
  const cd = { id: 'cd', source: 'c', target: 'd', points: line([20, 110], [60, 110], [60, 10], [160, 10], [160, 110], [200, 110]), basis: 'observed' };
  assert.equal(measureLayout(scene(nodes, [ab, cd])).overlaps.unrelatedShare, Math.round((200 / 560) * 1000) / 1000);
  // a -> d leaves the same card along the same run: the run is shared, but by one source.
  const ad = { id: 'ad', source: 'a', target: 'd', points: line([20, 10], [100, 10], [100, 110], [200, 110]), basis: 'observed' };
  const shared = measureLayout(scene(nodes, [ab, ad]));
  assert.ok(shared.overlaps.collinearShare > 0, 'the two cables do lie on each other');
  assert.equal(shared.overlaps.unrelatedShare, 0);
});

test('an uncertain cable in a trunk is counted in the trunk and half hidden; a clear one is neither', () => {
  const nodes = [box('a', 0, 0), box('b', 300, 0), box('c', 0, 100), box('d', 300, 100)];
  const inTrunk = { id: 'ab', source: 'a', target: 'b', points: line([20, 10], [300, 10]), basis: 'inferred' };
  const clear = { id: 'cd', source: 'c', target: 'd', points: line([20, 110], [300, 110]), basis: 'unresolved' };
  const m = measureLayout(scene(nodes, [inTrunk, clear], {
    overlays: [{ id: 'b1', bundle: 'b1', kind: 'trunk', points: line([40, 12], [280, 12]) }],
    restHidden: ['ab'],
  }));
  assert.equal(m.uncertain.cables, 2);
  assert.equal(m.uncertain.hiddenHalf, 1);
  assert.equal(m.uncertain.inTrunk, 1);
  assert.deepEqual(m.uncertain.list.map((u) => [u.id, u.inTrunk, u.overlapShare >= 0.5]), [['ab', true, true], ['cd', false, false]]);
  // 2 px from the trunk is beside it, not on it.
  assert.equal(m.uncertain.drawnOn, 0);
});

test('an uncertain cable drawn on another stroke for more than 8 px is drawn on it; one that only meets it at a port is not', () => {
  const nodes = [box('a', 0, 0), box('b', 300, 0), box('c', 0, 100), box('d', 300, 100), box('e', 0, 200), box('f', 300, 200)];
  const solid = { id: 'ab', source: 'a', target: 'b', points: line([20, 10], [300, 10]), basis: 'observed' };
  // 100 px of it on the solid line: drawn on it, though less than half of it is hidden.
  const on = { id: 'cb', source: 'c', target: 'b', points: line([20, 110], [100, 110], [100, 10.5], [200, 10.5], [200, 50], [300, 50]), basis: 'inferred' };
  // 6 px on it where both leave a's face, then away.
  const port = { id: 'ae', source: 'a', target: 'e', points: line([20, 10], [26, 10], [26, 210], [300, 210]), basis: 'unresolved' };
  const m = measureLayout(scene(nodes, [solid, on, port]));
  assert.equal(m.uncertain.hiddenHalf, 0);
  assert.equal(m.uncertain.drawnOn, 1);
  assert.deepEqual(m.uncertain.list.filter((u) => u.onStrokeShare * u.length > 8).map((u) => u.id), ['cb']);
});

test('an at-rest label is crossed by an unrelated cable, not by one that shares its source', () => {
  const nodes = [box('a', 0, 0), box('b', 300, 0), box('c', 140, -100), box('d', 140, 100), box('e', 0, 100)];
  const labelled = { id: 'ab', source: 'a', target: 'b', points: line([20, 10], [300, 10]), basis: 'observed', label: 'batches', labelAlways: true, labelRect: { x: 60, y: 2, w: 40, h: 16 } };
  const unrelated = { id: 'ce', source: 'c', target: 'e', points: line([145, -80], [145, -60], [80, -60], [80, 110], [20, 110]), basis: 'observed' };
  const sameSource = { id: 'ad', source: 'a', target: 'd', points: line([20, 14], [70, 14], [70, 110], [140, 110]), basis: 'observed' };
  const crossed = measureLayout(scene(nodes, [labelled, unrelated])).labels;
  assert.equal(crossed.atRest, 1);
  assert.equal(crossed.crossedByUnrelated, 1);
  assert.equal(measureLayout(scene(nodes, [labelled, sameSource])).labels.crossedByUnrelated, 0);
  const hoverOnly = measureLayout(scene(nodes, [{ ...labelled, labelAlways: false }, unrelated])).labels;
  assert.equal(hoverOnly.atRest, 0, 'a hover-only label is not drawn at rest');
});

test('the walk replay pans the least distance, and W1 returns to 0.9 after a finding left the zoom under 0.75, or as far as the next box fits', () => {
  const canvas = { w: 400, h: 300 };
  const wide = { width: 3000, height: 300, lanes: [{ id: 'p', x: 0, y: 0, w: 3000, h: 300 }], nodes: [], edges: [] };
  const a = { x: 0, y: 100, w: 100, h: 50 }, b = { x: 1000, y: 100, w: 100, h: 50 }, g = { x: 420, y: 100, w: 100, h: 50 };
  // Phase 1 opens at 0.9 at x 24: b's right edge is at 924 + 90 px, so the least pan is 630 px.
  const pan = walkCamera(wide, [{ kind: 'node', id: 'a', rect: a }, { kind: 'node', id: 'b', rect: b }], { firstCanvas: canvas, walkCanvas: canvas });
  assert.equal(pan.summary.panTotal, 630);
  // A finding citing a and g fits only at (400 - 48) / 520 = 0.68; the next step keeps it under W0.
  const claims = [{ kind: 'issue', id: 'f', rect: { x: 0, y: 100, w: 520, h: 50 }, steps: [a, g], ends: [] }, { kind: 'node', id: 'g', rect: g }];
  const w0 = walkCamera(wide, claims, { firstCanvas: canvas, walkCanvas: canvas, policy: 'W0' });
  const w1 = walkCamera(wide, claims, { firstCanvas: canvas, walkCanvas: canvas, policy: 'W1' });
  assert.equal(w0.steps[0].zoom, 0.677);
  assert.equal(w0.steps[1].zoom, 0.677);
  assert.equal(w1.steps[1].zoom, 0.9);
  assert.equal(walkCamera(wide, claims, { firstCanvas: canvas, walkCanvas: canvas }).policy, 'W1', 'W1 is the default: the viewer\'s walk');
  // A connection 470 px wide after that finding fits only at (400 - 30) / 470 = 0.787 (a step keeps
  // 30 px on a 300 px canvas): W1 stops there, with the box whole.
  const edge = { kind: 'edge', id: 'e', rect: { x: 50, y: 100, w: 470, h: 50 } };
  const part = walkCamera(wide, [claims[0], edge], { firstCanvas: canvas, walkCanvas: canvas, policy: 'W1' });
  assert.equal(part.steps[1].zoom, 0.787);
  assert.equal(part.steps[1].visibleAfter, true);
});

test('the walk replay keeps a connection\'s end cards clear of the phase index as the viewer does', () => {
  const area = { w: 541, h: 392 };
  const pill = { x: 300, y: 352, w: 229, h: 28 };
  const union = { x: 0, y: 0, w: 480, h: 360 };
  const clear = (cam, ends) => ends.every((b) => cam.isVisible(b));
  // The tall end (a group's frame) beside the pill, the other on it: the least pan leaves the union
  // where it is, so it is framed: centred, then 12 px up, which clears both cards at the same zoom.
  const besides = [{ x: 0, y: 0, w: 150, h: 360 }, { x: 330, y: 250, w: 150, h: 90 }];
  let cam = makeCamera({ x: 10, y: 16, zoom: 1 }, area, pill);
  walkStep(cam, { kind: 'edge', id: 'e', rect: union, ends: besides });
  assert.deepEqual(cam.vp, { x: 30.5, y: 4, zoom: 1 });
  assert.ok(clear(cam, besides));
  // Corner to corner: no pan clears the target at 1; the first zoom down that does is 0.95, a 5 %
  // step (the zoom that fits the union wholly above the pill, 0.92, is further out).
  const corners = [{ x: 0, y: 0, w: 150, h: 80 }, { x: 330, y: 280, w: 150, h: 80 }];
  cam = makeCamera({ x: 30.5, y: 16, zoom: 1 }, area, pill);
  walkStep(cam, { kind: 'edge', id: 'e', rect: union, ends: corners });
  assert.equal(cam.vp.zoom, 0.95);
  assert.ok(clear(cam, corners));
});

test('the baseline holds exactly the repo-held documents, with their counts and the summary keys the tool reports', () => {
  const baseline = JSON.parse(readFileSync(BASELINE_FILE, 'utf8'));
  assert.equal(baseline.tool, TOOL_ID);
  assert.deepEqual(Object.keys(baseline), ['tool', 'about', 'policy', 'panels', 'documents']);
  assert.deepEqual(Object.keys(baseline.documents).sort(), [...repoDocuments(), ...devDocuments()].map((d) => d.name).sort());
  assert.deepEqual(devDocuments().map((d) => d.name), TEST_DOCUMENTS.map((name) => 'doc ' + name));
  // An entry measured from a file has that file's counts, so the baseline was recorded from the
  // tracked documents. These four counts are compared here, and every summary's key paths below.
  for (const [name, file] of Object.entries(FILES)) {
    const doc = JSON.parse(readFileSync(file, 'utf8'));
    const { steps, connections, phases, findings } = baseline.documents[name].summary.counts;
    assert.deepEqual({ steps, connections, phases, findings }, { steps: doc.nodes.length, connections: doc.edges.length, phases: doc.phases.length, findings: (doc.findings || []).length }, name);
  }
  const report = JSON.parse(run(['--no-repo', '--json', SAMPLE]).text);
  const keys = keyPaths(report.documents[0].summary);
  for (const [name, entry] of Object.entries(baseline.documents)) assert.deepEqual(keyPaths(entry.summary), keys, name);
  // Re-recording it with a document from outside the repository is refused.
  assert.throws(() => run(['--write-baseline', join(REPO_ROOT, 'elsewhere.mlview.json')]), /repo-held documents only/);
});

test('the built bundle carries none of the tool', () => {
  assert.doesNotMatch(readFileSync(DIST_JS, 'utf8'), new RegExp(TOOL_ID));
});
