/**
 * Standalone deep-link safety (CONTRACTS 11.17, 2026-09-08).
 *
 * The standalone report used to open a source location by clicking a hidden
 * `<a href="vscode://file/...">` in its own frame. Embedded in a sandboxed
 * iframe — which is how the report is shared on claude.ai — that is a top-level
 * navigation to a scheme the sandbox forbids, so the browser REPLACES THE FRAME
 * with "This content is blocked. Contact the site owner to fix the issue." The
 * Issues rail's Go to button, the Inspector's Open file:line, the related
 * locations and every node / edge click all led there.
 *
 * The rule this file gates is absolute: the report NEVER navigates itself.
 *
 * Two of the three contexts are real here — a genuine nested browsing context
 * for `embedded`, a genuine `file:` document for `local` — and the third, the
 * cross-origin sandbox, is unbuildable in jsdom by construction. That is why the
 * decision is a pure exported function: the environment only has to report two
 * booleans, and the table those booleans index is pinned directly.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { JSDOM, VirtualConsole } from 'jsdom';
import { readBundle, readSample, WEBVIEW_ROOT } from './helpers.mjs';

const bundleCode = await readBundle();
const sample = await readSample();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const LOC = { v: 1, type: 'openLocation', file: 'train.py', absFile: '/w/train.py', line: 44, col: 3 };
const DEEP_LINK = 'vscode://file//w/train.py:44:4';

/** A window at `url` with the built bundle evaluated in it, plus a clipboard spy. */
function page(url) {
  const virtualConsole = new VirtualConsole();
  const errors = [];
  virtualConsole.on('jsdomError', (e) => errors.push(String((e && e.message) || e)));
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url,
    virtualConsole,
  });
  const script = dom.window.document.createElement('script');
  script.textContent = bundleCode;
  dom.window.document.head.appendChild(script);
  return wrap(dom.window, errors);
}

/**
 * A REAL nested browsing context: an iframe inside a top-level document, with
 * the bundle evaluated inside the frame. `window.top` is not configurable in
 * jsdom, so this is the only honest way to make `self !== top` true — and it is
 * a better test than a stub, because it exercises the same code path a hosted
 * report actually takes.
 */
function embeddedPage(url) {
  const virtualConsole = new VirtualConsole();
  const errors = [];
  virtualConsole.on('jsdomError', (e) => errors.push(String((e && e.message) || e)));
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    url,
    virtualConsole,
  });
  const frame = dom.window.document.createElement('iframe');
  dom.window.document.body.appendChild(frame);
  const inner = frame.contentWindow;
  const root = inner.document.createElement('div');
  root.id = 'mlview-root';
  inner.document.body.appendChild(root);
  const script = inner.document.createElement('script');
  script.textContent = bundleCode;
  inner.document.head.appendChild(script);
  return wrap(inner, errors, dom.window);
}

function deepClone(value) {
  if (value === null || typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(deepClone);
  const out = {};
  for (const key of Object.keys(value)) out[key] = deepClone(value[key]);
  return out;
}

function wrap(window, errors, outer) {
  // jsdom 26 has no structuredClone; dagre uses it. Every real host ships it,
  // and a nested browsing context gets its own global object, so the shim has
  // to be installed there too.
  if (typeof window.structuredClone !== 'function') window.structuredClone = deepClone;
  const copied = [];
  Object.defineProperty(window.navigator, 'clipboard', {
    value: {
      writeText: (text) => {
        copied.push(text);
        return Promise.resolve();
      },
    },
    configurable: true,
  });
  // Any same-frame navigation would go through one of these two. Both are
  // recorded rather than blocked, so a regression fails loudly instead of
  // hiding behind a jsdom "Not implemented" line.
  const clicked = [];
  const realClick = window.HTMLAnchorElement.prototype.click;
  window.HTMLAnchorElement.prototype.click = function patched() {
    clicked.push(this.getAttribute('href') || '');
    return realClick.apply(this, arguments);
  };
  return {
    window,
    outer: outer || window,
    document: window.document,
    errors,
    copied,
    clicked,
    MLView: window.MLView,
    toasts: () => Array.from(window.document.querySelectorAll('.mlv-toast')),
    frames: () => Array.from(window.document.querySelectorAll('iframe')),
  };
}

/* ── the decision table itself ────────────────────────────────────────── */

test('deepLinkPlan is a pure two-boolean table (11.17)', async () => {
  const ctx = page('https://mlview.test/');
  const { deepLinkPlan } = ctx.MLView.__internal;
  const at = (embedded, local) => deepLinkPlan({ embedded, local, absFile: '/w/train.py', file: 'train.py', line: 44, col: 3 });

  assert.equal(at(false, true).mode, 'launch', 'top-level and local is the ONLY launch');
  assert.equal(at(true, true).mode, 'copy', 'embedded outranks local: a sandbox can kill the page either way');
  assert.equal(at(true, false).mode, 'copy');
  assert.equal(at(false, false).mode, 'copy', 'an http report has no OS handler to reach');

  for (const [embedded, local] of [[false, true], [true, true], [true, false], [false, false]]) {
    const plan = at(embedded, local);
    assert.equal(plan.url, DEEP_LINK, 'the URL is built either way, since the copy toast offers it');
    assert.equal(plan.copyText, 'train.py:44', 'the clipboard gets file:line, the thing a human retypes');
    assert.ok(plan.toast.indexOf('train.py:44') >= 0, plan.toast);
  }
  assert.ok(at(true, true).toast.indexOf('open the report locally') >= 0, at(true, true).toast);
  assert.equal(at(false, true).toast, 'Copied train.py:44', 'the launch fallback keeps the old copy');
  // col is 0-based in the protocol and 1-based in the URL; line is not shifted.
  assert.equal(
    deepLinkPlan({ embedded: false, local: false, absFile: '/w/a.py', file: 'a.py', line: 1, col: 0 }).url,
    'vscode://file//w/a.py:1:1',
  );
});

/* ── EMBEDDED: the bug this exists for ────────────────────────────────── */

test('an embedded report copies and never touches the frame (11.17)', async () => {
  const ctx = embeddedPage('file:///C:/w/report.html');
  assert.ok(ctx.window.self !== ctx.window.top, 'this really is a nested browsing context');
  const before = ctx.window.location.href;

  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  bridge.post(LOC);
  await sleep(40);

  assert.deepEqual(ctx.clicked, [], 'no anchor was clicked — that is what replaced the frame');
  assert.equal(ctx.frames().length, 0, 'and no launch iframe was attempted either');
  assert.equal(ctx.window.location.href, before, 'the document did not move');
  assert.deepEqual(ctx.copied, ['train.py:44'], 'the clipboard got file:line');

  const toasts = ctx.toasts();
  assert.equal(toasts.length, 1, 'the reader is told what happened');
  assert.ok(toasts[0].textContent.indexOf('Copied train.py:44') === 0, toasts[0].textContent);
  assert.ok(toasts[0].textContent.indexOf('open the report locally to jump into VS Code') > 0, toasts[0].textContent);

  const link = toasts[0].querySelector('a');
  assert.ok(link, 'and still offered a way through, for a host that permits the protocol');
  assert.equal(link.textContent, 'Open in VS Code');
  assert.equal(link.getAttribute('href'), DEEP_LINK);
  assert.equal(link.getAttribute('target'), '_blank', 'a NEW browsing context, so a sandbox drops the click');
  assert.equal(link.getAttribute('rel'), 'noopener noreferrer');
  assert.deepEqual(ctx.errors, [], 'and nothing threw on the way');
});

test('the whole viewer works inside a frame, and Go to never blanks it (11.17)', async () => {
  // The end-to-end shape of the report bug: mount the real app in a nested
  // context, click a node card, and check the diagram is still there.
  const ctx = embeddedPage('file:///C:/w/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  const root = ctx.document.getElementById('mlview-root');
  ctx.MLView.mount(root, sample, bridge);
  const before = ctx.window.location.href;
  const cards = ctx.document.querySelectorAll('[data-node-id]');
  assert.ok(cards.length > 10, 'the diagram rendered: ' + cards.length + ' cards');

  const card = ctx.document.querySelector('.mlv-node[data-node-id]');
  card.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true }));
  await sleep(60);

  assert.deepEqual(ctx.clicked, [], 'no navigation was even attempted');
  assert.equal(ctx.window.location.href, before);
  assert.equal(ctx.document.querySelectorAll('[data-node-id]').length, cards.length, 'the diagram survived the click');
  assert.equal(ctx.copied.length, 1, 'and the location is on the clipboard instead');
  assert.deepEqual(ctx.errors, []);
});

/* ── TOP-LEVEL + file: the one context that may launch ────────────────── */

test('a local top-level report launches through a hidden iframe (11.17)', async () => {
  const ctx = page('file:///C:/w/report.html');
  assert.equal(ctx.window.location.protocol, 'file:');
  assert.ok(ctx.window.self === ctx.window.top, 'top-level');
  const before = ctx.window.location.href;

  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  bridge.post(LOC);

  const frames = ctx.frames();
  assert.equal(frames.length, 1, 'the OS hand-off goes through a frame, not through this document');
  assert.equal(frames[0].getAttribute('src'), DEEP_LINK);
  assert.equal(frames[0].hidden, true, 'invisible');
  assert.equal(frames[0].getAttribute('aria-hidden'), 'true', 'and out of the accessibility tree');
  assert.equal(frames[0].getAttribute('tabindex'), '-1');
  assert.deepEqual(ctx.clicked, [], 'no anchor click anywhere on this path');
  assert.equal(ctx.window.location.href, before, 'and the document itself never moved');

  // No blur follows in jsdom, so the 400 ms fallback copies, exactly as before.
  await sleep(500);
  assert.deepEqual(ctx.copied, ['train.py:44']);
  const toasts = ctx.toasts();
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].textContent, 'Copied train.py:44', 'the launch fallback keeps the old, shorter copy');
  assert.equal(toasts[0].querySelector('a'), null, 'no link here: this reader can already reach the handler');

  // The frame is temporary; a run of Go to clicks must not accumulate frames.
  await sleep(1300);
  assert.equal(ctx.frames().length, 0, 'the launch frame is removed again');
  assert.deepEqual(ctx.errors, []);
});

/* ── TOP-LEVEL + http(s): copy only ───────────────────────────────────── */

test('a report served over http copies and does not try the OS (11.17)', async () => {
  const ctx = page('https://mlview.test/report.html');
  const before = ctx.window.location.href;
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  bridge.post(LOC);
  await sleep(40);

  assert.equal(ctx.frames().length, 0, 'no launch frame');
  assert.deepEqual(ctx.clicked, []);
  assert.equal(ctx.window.location.href, before);
  assert.deepEqual(ctx.copied, ['train.py:44']);
  const toasts = ctx.toasts();
  assert.equal(toasts.length, 1);
  assert.ok(toasts[0].textContent.indexOf('open the report locally') > 0, toasts[0].textContent);
  assert.equal(toasts[0].querySelector('a').getAttribute('href'), DEEP_LINK);
  assert.deepEqual(ctx.errors, []);
});

/* ── the copy path still tells the truth ──────────────────────────────── */

test('a denied clipboard write still reports honestly (MLV-R1-007 kept)', async () => {
  const ctx = page('https://mlview.test/report.html');
  Object.defineProperty(ctx.window.navigator, 'clipboard', {
    value: { writeText: () => Promise.reject(new Error('denied')) },
    configurable: true,
  });
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  bridge.post(LOC);
  await sleep(60);
  const toasts = ctx.toasts();
  assert.equal(toasts.length, 1);
  assert.ok(toasts[0].textContent.indexOf('Copy blocked') === 0, toasts[0].textContent);
  assert.equal(toasts[0].querySelector('a').getAttribute('href'), DEEP_LINK, 'the way out survives a failed copy');
});

/* ── the source-level gate ────────────────────────────────────────────── */

test('nothing in bridges.ts can navigate the document (11.17)', async () => {
  // The failure mode is a one-line regression, and no DOM assertion can see it
  // in the environment where it bites. The source is therefore the gate.
  const src = await readFile(join(WEBVIEW_ROOT, 'src', 'bridges.ts'), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|\s)\/\/[^\n]*/g, ' ');
  assert.equal(code.indexOf('.click()'), -1, 'a programmatic click is how the frame was replaced');
  assert.equal(code.indexOf('location.href ='), -1, 'and an href assignment is the other way to do it');
  assert.equal(code.indexOf('location.assign'), -1);
  assert.equal(code.indexOf('location.replace'), -1);
  assert.equal(code.indexOf('window.open'), -1, 'a popup is a navigation the host may also kill');
  assert.ok(code.indexOf("createElement('iframe')") > 0, 'the launch goes through a frame');
  assert.ok(code.indexOf('deepLinkPlan') > 0, 'through the one decision function');
});

/* ── R3-DL-01: the toast is the whole outcome, so it must be reachable ── */

test('the toast is announced by a live region (R3-DL-01)', async () => {
  // Since 11.17 the toast IS the outcome of every open-in-editor gesture in an
  // embedded or http(s) report — and it carried no `role` and sat in no live
  // region, so a screen-reader user pressing "Open model.py:34" was told
  // nothing at all: not that the location was copied, not that a link existed.
  const ctx = page('https://mlview.test/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });

  // The region is up BEFORE the message lands, which is what makes the text a
  // live-region MUTATION rather than a node that appeared already announced.
  bridge.post(LOC);
  const host = ctx.document.querySelector('.mlv-toasts--floating');
  assert.ok(host, 'the live region exists as soon as the gesture runs');
  assert.equal(host.getAttribute('role'), 'status', 'role="status" IS a polite live region');
  assert.equal(host.getAttribute('aria-live'), null, 'and the app announcer stays the only [aria-live] element');
  assert.equal(ctx.document.querySelectorAll('.mlv-toast--floating').length, 0, 'nothing is claimed before the copy lands');

  await sleep(40);
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast, 'the message arrived');
  assert.equal(toast.closest('[role="status"]'), host, 'inside the region, so it is spoken');
  assert.equal(toast.parentNode, host);
  assert.ok(toast.querySelector('a'), 'with the only affordance this host has left');
});

test('the toast holds while the pointer is on it (R3-DL-01)', async () => {
  // 3000 ms was a hard deadline on the one control the reader is offered: the
  // card could expire under a cursor on its way to the link.
  const ctx = page('https://mlview.test/report.html');
  ctx.MLView.bridges.standalone({ theme: 'light' }).post(LOC);
  await sleep(40);
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast);

  toast.dispatchEvent(new ctx.window.Event('mouseenter'));
  await sleep(3300);
  assert.ok(toast.isConnected, 'the timer is held while the pointer is over it');

  toast.dispatchEvent(new ctx.window.Event('mouseleave'));
  await sleep(3300);
  assert.equal(toast.isConnected, false, 'and restarts when the pointer leaves');
  assert.ok(ctx.document.querySelector('.mlv-toasts--floating'), 'the region itself is kept, for the next message');
});

test('a KEYBOARD gesture puts focus on the link, and gives it back (R3-DL-01)', async () => {
  // Measured before the fix: 17 Tab presses from the activated button to the
  // toast's anchor, inside a 3000 ms window. There was no other route to it.
  const ctx = page('https://mlview.test/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  const button = ctx.document.createElement('button');
  ctx.document.body.appendChild(button);
  button.focus();
  button.dispatchEvent(new ctx.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  bridge.post(LOC);
  await sleep(40);

  const link = ctx.document.querySelector('.mlv-toast--floating a');
  assert.ok(link);
  assert.equal(ctx.document.activeElement, link, 'the affordance is where the keyboard already is');

  // Focus holds the toast open; releasing it starts the clock, and the return
  // must not land on <body> — that silently kills the canvas keymap.
  link.dispatchEvent(new ctx.window.Event('focusout', { bubbles: true }));
  await sleep(3300);
  assert.equal(ctx.document.querySelector('.mlv-toast--floating'), null, 'it does expire once released');
  assert.equal(ctx.document.activeElement, button, 'and focus goes back where the gesture started');
});

test('a POINTER gesture never steals focus (R3-DL-01)', async () => {
  const ctx = page('https://mlview.test/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  const button = ctx.document.createElement('button');
  ctx.document.body.appendChild(button);
  button.focus();
  button.dispatchEvent(new ctx.window.MouseEvent('mousedown', { bubbles: true }));
  bridge.post(LOC);
  await sleep(40);
  assert.ok(ctx.document.querySelector('.mlv-toast--floating a'), 'the link is there for the mouse');
  assert.equal(ctx.document.activeElement, button, 'but focus is not yanked at a pointer user');
});

/* ── R3-DL-02 / R3-DL-03: one card, one frame ─────────────────────────── */

test('floating toasts replace rather than stack (R3-DL-02)', async () => {
  // Two toasts landed at byte-identical rectangles — a node click plus the
  // Inspector's own "Open train.py:22" does it with no double-clicking — and the
  // buried ones kept live anchors in the tab order, pointing at stale locations.
  const ctx = page('https://mlview.test/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  bridge.post(LOC);
  await sleep(40);
  bridge.post({ ...LOC, file: 'model.py', absFile: '/w/model.py', line: 34 });
  await sleep(40);

  const cards = ctx.document.querySelectorAll('.mlv-toast--floating');
  assert.equal(cards.length, 1, 'one card, not a pile of them');
  assert.ok(cards[0].textContent.indexOf('model.py:34') >= 0, 'and it is the LAST location: ' + cards[0].textContent);
  const links = ctx.document.querySelectorAll('.mlv-toast--floating a');
  assert.equal(links.length, 1, 'so no stale deep link is left in the tab order');
  assert.equal(links[0].getAttribute('href'), 'vscode://file//w/model.py:34:4');
});

test('a run of Go to clicks never accumulates launch frames (R3-DL-03)', async () => {
  // The 1500 ms removal delay claimed to prevent this and never did: six clicks
  // inside the window left six frames attached, i.e. six simultaneous OS
  // protocol invocations.
  const ctx = page('file:///C:/w/report.html');
  const bridge = ctx.MLView.bridges.standalone({ theme: 'light' });
  for (let i = 0; i < 6; i++) bridge.post({ ...LOC, line: 40 + i });
  const frames = ctx.document.querySelectorAll('iframe.mlv-deeplink');
  assert.equal(frames.length, 1, 'one hand-off at a time');
  assert.equal(frames[0].getAttribute('src'), 'vscode://file//w/train.py:45:4', 'and it is the location last asked for');
  await sleep(1700);
  assert.equal(ctx.document.querySelectorAll('iframe.mlv-deeplink').length, 0, 'still temporary');
});

/* ── R3-DL-04: the URL is a URL ────────────────────────────────────────── */

test('a # or ? in the path cannot retarget the deep link (R3-DL-04)', async () => {
  // Both are URL syntax, and nothing said the link was wrong: the clipboard text
  // stayed correct and the anchor still read "Open in VS Code", while the
  // handler received `vscode://file/C:/w/issue` — wrong file, no line, no column.
  const ctx = page('https://mlview.test/');
  const { deepLinkPlan } = ctx.MLView.__internal;
  const url = (absFile) => deepLinkPlan({ embedded: true, local: false, absFile, file: 'a.py', line: 3, col: 0 }).url;
  const parse = (u) => {
    const a = ctx.document.createElement('a');
    a.href = u;
    return a;
  };

  assert.equal(url('C:/w/issue#1/a.py'), 'vscode://file/C:/w/issue%231/a.py:3:1');
  assert.equal(parse(url('C:/w/issue#1/a.py')).hash, '', 'nothing of the path is read as a fragment');
  assert.equal(url('C:/w/a?b/a.py'), 'vscode://file/C:/w/a%3Fb/a.py:3:1');
  assert.equal(parse(url('C:/w/a?b/a.py')).search, '', 'nor as a query string');
  assert.equal(url('C:/My Projects/a.py'), 'vscode://file/C:/My%20Projects/a.py:3:1', 'spaces were already fine');
  assert.equal(url('/w/train.py'), 'vscode://file//w/train.py:3:1', 'an ordinary path is untouched');
  assert.equal(url(''), '', 'and an empty path builds no link at all, rather than vscode://file/:3:1');
});

test('a location with no absolute path offers no dead anchor (R3-DL-04)', async () => {
  const ctx = page('https://mlview.test/report.html');
  ctx.MLView.bridges.standalone({ theme: 'light' }).post({ ...LOC, absFile: '' });
  await sleep(40);
  const toast = ctx.document.querySelector('.mlv-toast--floating');
  assert.ok(toast, 'the copy still happens and is still reported');
  assert.equal(toast.querySelector('a'), null, 'but nothing offers a link that points nowhere');
});
