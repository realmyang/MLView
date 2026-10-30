'use strict';
/**
 * Every upper bound of the schema is a bound that the extension applies, at the same value.
 *
 * The extension does not load the schema: it holds its limits as numbers in its own code. For each
 * `max*` keyword of contracts/workflow.schema.json this file makes two copies of a generated test
 * document, one with the field at the bound and one a single step past it. The extension's
 * structural validator must accept the first and refuse the second, and a message that says
 * "at most" must name the bound's number. The message for a path that is too long names no number.
 * A string is made a second time from characters outside the basic plane, which count once each.
 *
 * A bound that the file cannot drive fails it, so a new upper bound in the schema needs a case
 * here. tools/test_format_bounds.py asks the schema and the helper the same questions.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { api, REPO_ROOT } = require('./harness');

const SCHEMA = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'contracts', 'workflow.schema.json'), 'utf8'));
const BASE = fs.readFileSync(path.join(REPO_ROOT, 'contracts', 'conformance', 'documents', 'workspace', 'd03-two-files.mlview.json'), 'utf8');
// The keywords of JSON Schema that set an upper bound.
const UPPER = ['maxLength', 'maxItems', 'maxProperties', 'maxContains', 'maximum', 'exclusiveMaximum'];
// The record definitions of the schema and the list of the document that holds such records.
const RECORDS = { phase: 'phases', node: 'nodes', edge: 'edges', finding: 'findings', evidence: 'evidence' };

/** [JSON pointer, value] for every upper bound that a schema states. */
function bounds(node, pointer = '') {
  if (Array.isArray(node)) return node.flatMap((value, index) => bounds(value, `${pointer}/${index}`));
  if (node === null || typeof node !== 'object') return [];
  return Object.entries(node).flatMap(([key, value]) => {
    const here = `${pointer}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;
    return UPPER.includes(key) && Number.isInteger(value) ? [[here, value]] : bounds(value, here);
  });
}

/** Grow a list of records to the size with copies of one that cites evidence, each under an ID of its own. */
function padded(records, size) {
  const first = JSON.stringify(records.find((record) => (record.evidence ?? []).length > 0) ?? records[0]);
  while (records.length < size) records.push({ ...JSON.parse(first), id: `pad-${records.length}` });
}

/** A copy of the base document whose field under the bound has the size, or null for a bound with no case here. */
function sized(pointer, size, wide = false) {
  const doc = JSON.parse(BASE);
  const text = (wide ? '\u{1F600}' : 'a').repeat(size);
  const parts = pointer.split('/').slice(1);
  const keyword = parts[parts.length - 1];
  const under = (...names) => names.every((name, index) => name === null || parts[index] === name);
  if (under('$defs', null, 'properties') && RECORDS[parts[1]] && parts.length === 5 && keyword === 'maxLength') {
    doc[RECORDS[parts[1]]][0][parts[3]] = text;
  } else if (under('$defs', 'refs') && parts.length === 3 && keyword === 'maxItems') {
    // The evidence list of the first node, with as many evidence records as it names.
    padded(doc.evidence, doc.evidence.length + size);
    doc.nodes[0].evidence = size ? doc.evidence.slice(-size).map((record) => record.id) : [];
  } else if (under('properties') && parts.length === 3 && keyword === 'maxLength') {
    doc[parts[1]] = text;
  } else if (under('properties') && parts.length === 3 && keyword === 'maxItems') {
    padded(doc[parts[1]], size);
  } else if (under('properties', null, 'properties') && parts.length === 5 && keyword === 'maxLength') {
    doc[parts[1]][parts[3]] = text;
  } else if (under('properties', null, 'properties') && parts.length === 5 && keyword === 'maxItems') {
    const held = doc[parts[1]][parts[3]] ?? [];
    doc[parts[1]][parts[3]] = held.concat(Array.from({ length: Math.max(0, size - held.length) }, (_, index) => `pad/${index}.py`));
  } else if (under('properties', null, 'properties', null, 'items', 'maxLength') && parts.length === 6) {
    doc[parts[1]][parts[3]] = (doc[parts[1]][parts[3]] ?? []).concat([text]);
  } else if (under('properties', 'verification', 'properties', 'files', 'maxProperties') && parts.length === 5) {
    const files = doc.verification.files;
    const digest = Object.values(files)[0];
    for (let index = 0; Object.keys(files).length < size; index += 1) files[`pad/${index}.py`] = digest;
  } else if (under('properties', 'verification', 'properties', 'files', 'propertyNames', 'maxLength') && parts.length === 6) {
    doc.verification.files[text] = Object.values(doc.verification.files)[0];
  } else {
    return null;
  }
  return doc;
}

const said = (doc) => api.validateWorkflowStructure(doc).issues.map((issue) => `${issue.path}: ${issue.message}`);
/** The numbers that the messages give after "at most". The path before a message can hold any text. */
const stated = (lines) => lines.flatMap((line) => [...line.slice(line.lastIndexOf(': ')).matchAll(/at most (\d+)/g)].map((match) => Number(match[1])));

test('every upper bound of the schema has a case, and the base document is within every limit', () => {
  const found = bounds(SCHEMA);
  assert.deepEqual(found.filter(([pointer, value]) => sized(pointer, value) === null), []);
  // The reading is not empty: the schema bounds strings, lists and one object.
  assert.deepEqual([...new Set(found.map(([pointer]) => pointer.split('/').pop()))].sort(), ['maxItems', 'maxLength', 'maxProperties']);
  assert.deepEqual(said(JSON.parse(BASE)), []);
});

test('a bound without a case is seen', () => {
  const changed = JSON.parse(JSON.stringify(SCHEMA));
  changed.$defs.evidence.properties.line.maximum = 100000;
  const before = new Set(bounds(SCHEMA).map(([pointer]) => pointer));
  const added = bounds(changed).filter(([pointer]) => !before.has(pointer));
  assert.deepEqual(added, [['/$defs/evidence/properties/line/maximum', 100000]]);
  assert.equal(sized(...added[0]), null);
});

test('the extension accepts each bound of the schema and refuses one step past it', async (t) => {
  for (const [pointer, value] of bounds(SCHEMA).sort()) {
    for (const wide of pointer.endsWith('/maxLength') ? [false, true] : [false]) {
      await t.test(`${pointer} = ${value}${wide ? ', characters outside the basic plane' : ''}`, () => {
        assert.deepEqual(said(sized(pointer, value, wide)), []);
        const over = said(sized(pointer, value + 1, wide));
        assert.notEqual(over.length, 0, 'one step past the bound is accepted');
        assert.deepEqual(stated(over).filter((number) => number !== value), [], JSON.stringify(over.map((line) => line.slice(-120))));
      });
    }
  }
});
