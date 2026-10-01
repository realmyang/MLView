// The screenshot harness's DevTools pipe plumbing (webview/tools/screenshots/cdp.mjs), without Chrome.
import assert from 'node:assert/strict';
import test from 'node:test';
import { createClient, createMessageParser, encodeMessage, findChrome } from '../tools/screenshots/cdp.mjs';

function collect() {
  const seen = [];
  return { seen, feed: createMessageParser((message) => seen.push(message)) };
}

test('the pipe parser splits NUL-terminated JSON across and within chunks', () => {
  const { seen, feed } = collect();
  const both = Buffer.concat([encodeMessage({ id: 1, result: {} }), encodeMessage({ method: 'Page.loadEventFired', params: {} })]);
  feed(both.subarray(0, 5));
  assert.equal(seen.length, 0, 'nothing before the first NUL');
  feed(both.subarray(5));
  assert.deepEqual(seen, [{ id: 1, result: {} }, { method: 'Page.loadEventFired', params: {} }]);
});

test('the pipe parser joins a UTF-8 character split between chunks and skips empty frames', () => {
  const { seen, feed } = collect();
  const bytes = encodeMessage({ text: 'naïve → ok' });
  const cut = bytes.indexOf(0xc3) + 1; // inside the two-byte "ï"
  feed(Buffer.from([0]));
  feed(bytes.subarray(0, cut));
  feed(bytes.subarray(cut));
  assert.deepEqual(seen, [{ text: 'naïve → ok' }]);
});

test('the client matches responses by id and routes events by session', async () => {
  const written = [];
  const client = createClient((bytes) => written.push(bytes));
  const events = [];
  client.on('Runtime.consoleAPICalled', (params) => events.push(params.type), 'S1');
  const answer = client.send('Runtime.evaluate', { expression: '1' }, 'S1');
  const sent = JSON.parse(written[0].subarray(0, written[0].length - 1).toString('utf8'));
  assert.equal(written[0][written[0].length - 1], 0, 'each command ends with NUL');
  assert.deepEqual(sent, { id: 1, method: 'Runtime.evaluate', params: { expression: '1' }, sessionId: 'S1' });
  client.handle({ method: 'Runtime.consoleAPICalled', params: { type: 'log' }, sessionId: 'S2' });
  client.handle({ method: 'Runtime.consoleAPICalled', params: { type: 'error' }, sessionId: 'S1' });
  client.handle({ id: 1, result: { value: 1 } });
  assert.deepEqual(await answer, { value: 1 });
  assert.deepEqual(events, ['error']);
  const failing = client.send('Page.navigate', {});
  client.handle({ id: 2, error: { message: 'Cannot navigate' } });
  await assert.rejects(failing, /Page\.navigate: Cannot navigate/);
});

test('findChrome honours CHROME and explains what to do when nothing is found', () => {
  const none = () => false;
  assert.deepEqual(findChrome({ platform: 'linux', env: { CHROME: '/opt/chrome' }, exists: (p) => p === '/opt/chrome' }), { path: '/opt/chrome' });
  assert.match(findChrome({ platform: 'linux', env: { CHROME: '/nowhere' }, exists: none }).error, /CHROME is set to \/nowhere/);
  assert.match(findChrome({ platform: 'linux', env: { PATH: '/usr/bin' }, exists: none }).error, /set CHROME/);
  const mac = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  assert.deepEqual(findChrome({ platform: 'darwin', env: {}, exists: (p) => p === mac }), { path: mac });
});
