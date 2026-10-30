'use strict';
/** Untrusted export payload guards: decodeExportPayload, defaultExportName, parseExportFileMessage. */
const test = require('node:test');
const assert = require('node:assert/strict');
const { api } = require('./harness');
const { decodeExportPayload, defaultExportName, parseExportFileMessage, MAX_EXPORT_BYTES, MAX_EXPORT_BASE64_LENGTH } = api;

const b64 = (value) => Buffer.from(value).toString('base64');
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]);

test('decodeExportPayload refuses empty, non-base64, oversized and wrong-format payloads', () => {
  assert.deepEqual(decodeExportPayload('svg', ''), { ok: false, reason: 'empty' });
  assert.deepEqual(decodeExportPayload('svg', 'not base64!'), { ok: false, reason: 'not-base64' });
  assert.deepEqual(decodeExportPayload('svg', 'abc'), { ok: false, reason: 'not-base64' }, 'length must be a multiple of four');
  assert.deepEqual(decodeExportPayload('svg', '===='), { ok: false, reason: 'not-base64' });
  assert.deepEqual(decodeExportPayload('png', b64('<svg></svg>')), { ok: false, reason: 'wrong-format' });
  assert.deepEqual(decodeExportPayload('svg', PNG.toString('base64')), { ok: false, reason: 'wrong-format' });
  assert.deepEqual(decodeExportPayload('svg', b64('<html><script>alert(1)</script></html>')), { ok: false, reason: 'wrong-format' });
  const oversized = 'A'.repeat(4 * Math.ceil((MAX_EXPORT_BYTES + 3) / 3));
  assert.deepEqual(decodeExportPayload('png', oversized), { ok: false, reason: 'too-large' });
});

test('decodeExportPayload accepts SVG after a byte-order mark or leading whitespace, and a PNG signature', () => {
  const bom = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>')]);
  const withBom = decodeExportPayload('svg', bom.toString('base64'));
  assert.equal(withBom.ok, true);
  assert.equal(Buffer.from(withBom.bytes).equals(bom), true, 'the bytes are written unchanged');
  assert.equal(decodeExportPayload('svg', b64('\n\t  <?xml version="1.0"?><svg/>')).ok, true);
  assert.equal(decodeExportPayload('svg', b64('<!DOCTYPE svg><svg/>')).ok, true);
  assert.equal(decodeExportPayload('png', PNG.toString('base64')).ok, true);
});

test('defaultExportName keeps only a safe basename with the right extension', () => {
  assert.equal(defaultExportName('svg', 'diagram.svg'), 'diagram.svg');
  assert.equal(defaultExportName('png', 'diagram'), 'diagram.png');
  assert.equal(defaultExportName('svg', '../../etc/passwd'), 'passwd.svg');
  assert.equal(defaultExportName('svg', 'C:\\Users\\me\\report.SVG'), 'report.SVG');
  assert.equal(defaultExportName('svg', '...hidden.svg'), 'hidden.svg');
  assert.equal(defaultExportName('svg', '-.-x.svg'), 'x.svg');
  assert.equal(defaultExportName('png', 'a b/c:d?.png'), 'c-d-.png');
  const long = defaultExportName('png', 'x'.repeat(200));
  assert.equal(long, 'x'.repeat(80) + '.png');
  assert.equal(defaultExportName('svg', ''), 'mlview-diagram.svg');
  assert.equal(defaultExportName('svg', '...', 'view'), 'mlview-diagram-view.svg');
  assert.equal(defaultExportName('png', undefined, 'scope'), 'mlview-diagram-scope.png');
});

test('parseExportFileMessage checks the shape, the optional requestId and caps the base64 length', () => {
  const message = { v: 1, type: 'exportFile', kind: 'svg', data: b64('<svg/>'), requestId: 'r-1' };
  assert.deepEqual(parseExportFileMessage(message), message);
  assert.equal(parseExportFileMessage({ ...message, kind: 'gif' }), undefined);
  assert.equal(parseExportFileMessage({ ...message, data: 7 }), undefined);
  assert.equal(parseExportFileMessage({ ...message, scope: 'page' }), undefined);
  assert.equal(parseExportFileMessage({ ...message, requestId: 7 }), undefined);
  assert.equal(parseExportFileMessage({ ...message, v: 2 }), undefined);
  assert.equal(parseExportFileMessage([message]), undefined);
  assert.equal(MAX_EXPORT_BASE64_LENGTH, 4 * Math.ceil(MAX_EXPORT_BYTES / 3));
  assert.equal(parseExportFileMessage({ ...message, data: 'A'.repeat(MAX_EXPORT_BASE64_LENGTH + 4) }), undefined);
});
