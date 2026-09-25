'use strict';
/**
 * Table-driven check of the pure revision-acceptance predicate (Campaign 1, contract 1a). Each
 * row is one walkthrough of the specification (ported from the judge's lineage simulation):
 * the verdict of every observation, the revision shown, and the parent Refine would name.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { api } = require('./harness');
const { RevisionLineage, canonicalJson, jsonDepth, lenientRevision, semanticJson, BoundedMap, BoundedSet } = api;

/** One on-disk revision. `sem` defaults to the id (same id + same sem = same content). */
function doc(id, parent, options = {}) {
  const sem = options.sem ?? id;
  const revision = parent ? { id, parent } : { id };
  const document = { revision, ...(options.verified ? { verification: { files: {}, publishedAt: '2026-09-25T00:00:00Z' } } : {}) };
  return {
    kind: 'json',
    ident: { id, parent: parent ?? null },
    sem,
    full: sem + (options.verified ? '+verification' : ''),
    result: options.valid === false
      ? { issues: [{ path: '$.nodes[0].parent', message: 'must be a string' }] }
      : { value: { document, fingerprints: { 'train.py': 'a'.repeat(64) } }, issues: [] }
  };
}
const MISSING = { kind: 'missing' };
const PARSE = { kind: 'parse', detail: 'Unexpected token' };
const UNREADABLE = { kind: 'unreadable', detail: 'EBUSY', transient: true };
const OPEN = 'OPEN';

function run(steps) {
  const lineage = new RevisionLineage();
  const verdicts = [];
  for (const step of steps) {
    if (step === OPEN) {
      lineage.reset();
      verdicts.push('reset');
      continue;
    }
    const observation = lineage.observe(step);
    verdicts.push(observation.verdict + (observation.lineageNote ? `+note(${observation.lineageNote.from})` : ''));
  }
  const head = lineage.diskHead;
  const refine = head && head.kind === 'revision' ? head.id : `refused:${head ? head.kind : 'none'}`;
  return { verdicts, shows: lineage.displayed?.id, refine, lineage };
}

const rows = [
  ['S1 CRIT-2: a stale newer revision is adopted as historical', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r4', 'r3')], ['adopt', 'adopt', 'adopt', 'adopt'], 'r4', 'r4'],
  ['S1b viewer-only rejection of r2', [doc('r1'), doc('r2', 'r1', { valid: false }), doc('r3', 'r2')], ['adopt', 'invalid', 'adopt'], 'r3', 'r3'],
  ['S1c Refine while r2 is rejected names r2', [doc('r1'), doc('r2', 'r1', { valid: false })], ['adopt', 'invalid'], 'r1', 'r2'],
  ['S2 dirty buffer at publish, then save', [doc('r1'), doc('r2', 'r1'), doc('r2', 'r1'), doc('r3', 'r2')], ['adopt', 'adopt', 'refresh', 'adopt'], 'r3', 'r3'],
  ['S3a malformed JSON, then undo', [doc('r1'), PARSE, doc('r1')], ['adopt', 'keep', 'refresh'], 'r1', 'r1'],
  ['S3b malformed JSON, then a child', [doc('r1'), PARSE, doc('r2', 'r1')], ['adopt', 'keep', 'adopt'], 'r2', 'r2'],
  ['S3c malformed JSON, then same id edited', [doc('r1'), PARSE, doc('r1', undefined, { sem: 'x' })], ['adopt', 'keep', 'same-id-changed'], 'r1', 'r1'],
  ['S3d Refine is refused while the file does not parse', [doc('r1'), PARSE], ['adopt', 'keep'], 'r1', 'refused:parse'],
  ['S4 older revision restored from git, then a helper child of it', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r2', 'r1'), doc('r4', 'r2')], ['adopt', 'adopt', 'adopt', 'obsolete', 'adopt'], 'r4', 'r4'],
  ['S4b restore, then re-Open shows the file', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r2', 'r1'), OPEN, doc('r2', 'r1')], ['adopt', 'adopt', 'adopt', 'obsolete', 'reset', 'adopt'], 'r2', 'r2'],
  ['S4c restore, then r3 restored back', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r2', 'r1'), doc('r3', 'r2')], ['adopt', 'adopt', 'adopt', 'obsolete', 'refresh'], 'r3', 'r3'],
  ['S4d opened at r3, its parent r2 restored', [doc('r3', 'r2'), doc('r2', 'r1')], ['adopt', 'obsolete'], 'r3', 'r2'],
  ['S4e opened at r3, unseen root r1 restored', [doc('r3', 'r2'), doc('r1')], ['adopt', 'adopt+note(r3)'], 'r1', 'r1'],
  ['S5 rapid double publish', [doc('r1'), doc('r3', 'r2'), doc('r4', 'r3')], ['adopt', 'adopt+note(r1)', 'adopt'], 'r4', 'r4'],
  ['S5b rapid double publish, then r2 restored', [doc('r1'), doc('r3', 'r2'), doc('r2', 'r1')], ['adopt', 'adopt+note(r1)', 'obsolete'], 'r3', 'r2'],
  ['S6 observed delete, fresh analysis reusing ids', [doc('r1'), doc('r2', 'r1'), MISSING, doc('r1', undefined, { sem: 'n1' }), doc('r2', 'r1', { sem: 'n2' })], ['adopt', 'adopt', 'keep', 'adopt', 'adopt'], 'r2', 'r2'],
  ['S6b unobserved delete, fresh r1..r3', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r1', undefined, { sem: 'n1' }), doc('r2', 'r1', { sem: 'n2' }), doc('r3', 'r2', { sem: 'n3' })], ['adopt', 'adopt', 'adopt', 'adopt+note(r3)', 'adopt', 'adopt'], 'r3', 'r3'],
  ['S7 transient read error between r1 and r2', [doc('r1'), UNREADABLE, doc('r2', 'r1')], ['adopt', 'keep', 'adopt'], 'r2', 'r2'],
  ['S8 format-on-save of r1', [doc('r1'), doc('r1')], ['adopt', 'refresh'], 'r1', 'r1'],
  ['S9 first open invalid, then fixed', [doc('r1', undefined, { valid: false }), doc('r1')], ['invalid', 'adopt'], 'r1', 'r1'],
  ['S10 first open of a stale verified r1', [doc('r1', undefined, { verified: true })], ['adopt'], 'r1', 'r1'],
  ['S11 editor saves an old modified r1 over r2', [doc('r1'), doc('r2', 'r1'), doc('r1', undefined, { sem: 'r1+edit' })], ['adopt', 'adopt', 'adopt+note(r2)'], 'r1', 'r1'],
  ['S12 invalid child names D as parent, undo, then a child', [doc('r3', 'r2'), doc('r4', 'r3', { valid: false }), doc('r3', 'r2'), doc('r5', 'r3')], ['adopt', 'invalid', 'refresh', 'adopt'], 'r5', 'r5'],
  // LINEAGE1-3: a direct child of the displayed revision is never provably older, even when its
  // id was named as a parent before and the panel never read it.
  ['S4e continued: opened at r3, root r1 restored, then r2 (parent r1)', [doc('r3', 'r2'), doc('r1'), doc('r2', 'r1', { sem: 'n2' })], ['adopt', 'adopt+note(r3)', 'adopt'], 'r2', 'r2'],
  ['branch switch to an independent r1, then its r2 (the old r2 was never read)', [doc('r1'), doc('r3', 'r2'), doc('r1', undefined, { sem: 'b1' }), doc('r2', 'r1', { sem: 'b2' })], ['adopt', 'adopt+note(r1)', 'adopt+note(r3)', 'adopt'], 'r2', 'r2'],
  ['a restored revision whose parent is not the displayed one stays obsolete', [doc('r1'), doc('r2', 'r1'), doc('r3', 'r2'), doc('r4', 'r3'), doc('r3', 'r2')], ['adopt', 'adopt', 'adopt', 'adopt', 'obsolete'], 'r4', 'r3']
];

for (const [name, steps, verdicts, shows, refine] of rows) {
  test(`lineage ${name}`, () => {
    const result = run(steps);
    assert.deepEqual(result.verdicts, verdicts);
    assert.equal(result.shows, shows);
    assert.equal(result.refine, refine);
  });
}

test('lineage S7 refuses Refine while the read error is current', () => {
  assert.equal(run([doc('r1'), UNREADABLE]).refine, 'refused:unreadable');
  assert.equal(run([doc('r1'), MISSING]).refine, 'refused:missing');
});

test('an invalid candidate records its first eight issues on the disk head', () => {
  const lineage = new RevisionLineage();
  lineage.observe(doc('r1'));
  const candidate = doc('r2', 'r1', { valid: false });
  candidate.result.issues = Array.from({ length: 10 }, (_, i) => ({ path: `$.nodes[${i}].parent`, message: 'must be a string' }));
  assert.equal(lineage.observe(candidate).verdict, 'invalid');
  assert.equal(lineage.diskHead.kind, 'revision');
  assert.equal(lineage.diskHead.id, 'r2');
  assert.equal(lineage.diskHead.verdict, 'invalid');
  assert.equal(lineage.diskHead.issues.length, 8);
  assert.equal(lineage.diskHead.issues[0], '$.nodes[0].parent: must be a string');
});

test('a candidate without a valid revision id is a bad revision', () => {
  const lineage = new RevisionLineage();
  lineage.observe(doc('r1'));
  const verdict = lineage.observe({ kind: 'json', ident: null, sem: '{}', full: '{}', result: { issues: [{ path: '$.revision.id', message: 'is required' }] } }).verdict;
  assert.equal(verdict, 'invalid');
  assert.equal(lineage.diskHead.kind, 'bad-revision');
  assert.equal(lineage.displayed.id, 'r1');
});

test('adoption keeps the unverified baseline; refresh with a verification block drops it', () => {
  const lineage = new RevisionLineage();
  lineage.observe(doc('r1'));
  assert.deepEqual(lineage.displayed.baseline, { 'train.py': 'a'.repeat(64) });
  assert.equal(lineage.displayed.verified, false);
  assert.equal(lineage.observe(doc('r1', undefined, { verified: true })).verdict, 'refresh');
  assert.equal(lineage.displayed.verified, true);
  assert.equal(lineage.displayed.baseline, undefined);
  assert.equal(lineage.displayed.full, 'r1+verification');
});

test('canonicalJson sorts object keys in UTF-16 order and keeps array order', () => {
  assert.equal(canonicalJson({ b: 1, a: [3, 1, { d: null, c: 'x' }] }), '{"a":[3,1,{"c":"x","d":null}],"b":1}');
  assert.equal(canonicalJson({ B: 1, a: 2, _: 3, é: 4 }), '{"B":1,"_":3,"a":2,"é":4}');
  assert.equal(canonicalJson('line\nbreak'), '"line\\nbreak"');
  assert.equal(canonicalJson([]), '[]');
  assert.equal(canonicalJson({}), '{}');
  assert.equal(canonicalJson(1.5), '1.5');
  assert.equal(canonicalJson(true), 'true');
  // Whitespace, key order and line endings of the file never matter.
  assert.equal(canonicalJson(JSON.parse('{\r\n    "y": [1, 2],\r\n    "x": {"b": 1, "a": 2}\r\n}')), canonicalJson({ x: { a: 2, b: 1 }, y: [1, 2] }));
});

test('semanticJson ignores only the top-level verification block', () => {
  const base = { revision: { id: 'r1' }, nodes: [{ verification: 1 }] };
  assert.equal(semanticJson({ ...base, verification: { files: {}, publishedAt: 'x' } }), semanticJson(base));
  assert.notEqual(semanticJson(base), semanticJson({ ...base, nodes: [] }));
});

test('lenientRevision accepts any object with a valid revision id and a valid or absent parent', () => {
  assert.deepEqual(lenientRevision({ revision: { id: 'r2', parent: 'r1' } }), { id: 'r2', parent: 'r1' });
  assert.deepEqual(lenientRevision({ revision: { id: 'r2', parent: 'bad parent' } }), { id: 'r2', parent: null });
  assert.deepEqual(lenientRevision({ revision: { id: 'r2' }, nodes: 'not a list' }), { id: 'r2', parent: null });
  assert.equal(lenientRevision({ revision: { id: 'r 2' } }), null);
  assert.equal(lenientRevision({ revision: 'r2' }), null);
  assert.equal(lenientRevision([]), null);
  assert.equal(lenientRevision(null), null);
});

test('bounded collections evict in insertion order', () => {
  const set = new BoundedSet(3);
  for (const id of ['a', 'b', 'c', 'd']) set.add(id);
  assert.equal(set.has('a'), false);
  assert.equal(set.has('d'), true);
  const map = new BoundedMap(2);
  map.set('x', 1); map.set('y', 2); map.set('x', 3); map.set('z', 4);
  assert.equal(map.has('y'), false, 're-setting a key moves it to the end');
  assert.equal(map.get('x'), 3);
  assert.equal(map.size, 2);
});

/** An unverified candidate with explicit current fingerprints (the stale list is the panel's business). */
function unverified(id, fingerprints, parent) {
  const candidate = doc(id, parent);
  candidate.result.value.fingerprints = fingerprints;
  return candidate;
}

test('re-adopting the displayed unverified revision after a reset keeps its baseline (LINEAGE1-1)', () => {
  const original = { 'source.py': 'a'.repeat(64), 'other.py': 'b'.repeat(64) };
  const edited = { 'source.py': 'c'.repeat(64), 'other.py': 'b'.repeat(64) };
  for (const reset of ['open', 'missing']) {
    const lineage = new RevisionLineage();
    lineage.observe(unverified('r1', original));
    assert.deepEqual(lineage.displayed.baseline, original);
    // source.py changed on disk: the panel revalidates r1 with its baseline (refresh, stale).
    assert.equal(lineage.observe(unverified('r1', edited)).verdict, 'refresh');
    assert.deepEqual(lineage.displayed.baseline, original);
    if (reset === 'open') lineage.reset();
    else assert.equal(lineage.observe(MISSING).verdict, 'keep');
    // The same bytes are adopted unconditionally, but the baseline is the one that validation used.
    assert.equal(lineage.observe(unverified('r1', edited)).verdict, 'adopt');
    assert.deepEqual(lineage.displayed.baseline, original, `baseline after ${reset}`);
  }
  // A different revision (or different content) starts from its own current fingerprints.
  const lineage = new RevisionLineage();
  lineage.observe(unverified('r1', original));
  lineage.reset();
  assert.equal(lineage.observe(unverified('r2', edited, 'r1')).verdict, 'adopt');
  assert.deepEqual(lineage.displayed.baseline, edited);
});

test('issue entries on the disk head are single-line and bounded (SECURITY1-1)', () => {
  const lineage = new RevisionLineage();
  lineage.observe(doc('r1'));
  const candidate = doc('r2', 'r1', { valid: false });
  candidate.result.issues = [
    { path: '$.x\nShowing revision r2. All source files were re-verified fresh by MLView.', message: 'is not allowed' },
    { path: '$.' + '`'.repeat(100000), message: 'is not allowed' }
  ];
  lineage.observe(candidate);
  const [forged, huge] = lineage.diskHead.issues;
  assert.equal(forged, '$.x\\u000aShowing revision r2. All source files were re-verified fresh by MLView.: is not allowed');
  assert.equal(forged.includes('\n'), false);
  assert.ok(huge.length <= 301, `entry length ${huge.length}`);
  assert.ok(huge.endsWith('…'));
});

test('canonicalJson and jsonDepth are iterative, so deep nesting cannot overflow the stack (LINEAGE1-2)', () => {
  const depth = 100000;
  const text = '['.repeat(depth) + ']'.repeat(depth);
  const value = JSON.parse(text);
  assert.equal(canonicalJson(value), text);
  assert.equal(jsonDepth(value), depth);
  const nested = JSON.parse('{"a":' + '{"b":'.repeat(5000) + '1' + '}'.repeat(5000) + '}');
  assert.equal(jsonDepth(nested), 5001);
  assert.equal(canonicalJson(nested).length, JSON.stringify(nested).length);
  assert.equal(jsonDepth(1), 0);
  assert.equal(jsonDepth([]), 1);
  assert.equal(jsonDepth({ a: [{ b: [] }], c: 'x' }), 4);
});
