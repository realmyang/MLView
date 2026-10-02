// Headless Chrome over the DevTools pipe, for the opt-in screenshot harness.
//
// Chrome is started with --remote-debugging-pipe: it reads protocol commands on
// file descriptor 3 and writes responses and events on descriptor 4, each
// message one JSON text followed by a NUL byte. No WebSocket is involved, so
// this runs on Node 20, which has no global WebSocket.
//
// Importing this module has no side effects; test/screenshot-pipe.test.mjs
// checks the message framing without Chrome.
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, posix } from 'node:path';

/** One protocol message as Chrome expects it on the pipe: JSON, then NUL. */
export function encodeMessage(message) {
  return Buffer.concat([Buffer.from(JSON.stringify(message), 'utf8'), Buffer.from([0])]);
}

/**
 * Returns a function that takes raw pipe chunks and calls `onMessage` once per
 * complete NUL-terminated JSON message. A message may span chunks, a chunk may
 * hold several messages, and a multi-byte UTF-8 character may be split between
 * chunks: bytes are joined before they are decoded.
 */
export function createMessageParser(onMessage) {
  let pending = [];
  return (chunk) => {
    let start = 0;
    for (;;) {
      const end = chunk.indexOf(0, start);
      if (end < 0) {
        if (start < chunk.length) pending.push(chunk.subarray(start));
        return;
      }
      pending.push(chunk.subarray(start, end));
      const text = Buffer.concat(pending).toString('utf8');
      pending = [];
      start = end + 1;
      if (text.length) onMessage(JSON.parse(text));
    }
  };
}

/**
 * Where Chrome usually lives, in the order tried. `CHROME` overrides all of them. The macOS and
 * Linux candidates are POSIX paths whatever the host is, so they are joined (and `PATH` split)
 * with `path.posix`, never the host's `path`: on a Windows runner that gave
 * `\Applications\Google Chrome.app\...` (PRUNE-1).
 */
export function chromeCandidates(platform = process.platform, env = process.env) {
  if (platform === 'darwin') {
    const apps = [
      'Google Chrome.app/Contents/MacOS/Google Chrome',
      'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      'Chromium.app/Contents/MacOS/Chromium',
      'Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
      'Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    ];
    const roots = ['/Applications', env.HOME ? posix.join(env.HOME, 'Applications') : null].filter(Boolean);
    return roots.flatMap((root) => apps.map((app) => posix.join(root, app)));
  }
  if (platform === 'win32') {
    const roots = [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean);
    const exes = ['Google\\Chrome\\Application\\chrome.exe', 'Chromium\\Application\\chrome.exe', 'Microsoft\\Edge\\Application\\msedge.exe'];
    return roots.flatMap((root) => exes.map((exe) => `${root}\\${exe}`));
  }
  const names = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'microsoft-edge'];
  const dirs = (env.PATH || '').split(posix.delimiter).filter(Boolean);
  return [...dirs.flatMap((dir) => names.map((name) => posix.join(dir, name))), '/snap/bin/chromium'];
}

/** The Chrome executable to use, or an error message that says how to point at one. */
export function findChrome({ platform = process.platform, env = process.env, exists = existsSync } = {}) {
  if (env.CHROME) {
    return exists(env.CHROME) ? { path: env.CHROME } : { error: `CHROME is set to ${env.CHROME}, but no file is there.` };
  }
  const found = chromeCandidates(platform, env).find((candidate) => exists(candidate));
  if (found) return { path: found };
  return { error: 'No Chrome or Chromium found. Install Google Chrome, or set CHROME to the browser executable, for example\n  CHROME=/usr/bin/chromium node webview/tools/screenshots/capture.mjs' };
}

/** A protocol client over any writer; `handle` takes each decoded message from Chrome. */
export function createClient(write) {
  let nextId = 0;
  const pending = new Map();
  const listeners = new Map();
  const key = (method, sessionId) => `${sessionId || ''} ${method}`;
  return {
    send(method, params = {}, sessionId) {
      const id = ++nextId;
      const message = { id, method, params };
      if (sessionId) message.sessionId = sessionId;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject, method });
        write(encodeMessage(message));
      });
    },
    on(method, callback, sessionId) {
      const k = key(method, sessionId);
      if (!listeners.has(k)) listeners.set(k, []);
      listeners.get(k).push(callback);
    },
    handle(message) {
      if (message.id !== undefined && pending.has(message.id)) {
        const { resolve, reject, method } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) reject(new Error(`${method}: ${message.error.message}${message.error.data ? ' ' + message.error.data : ''}`));
        else resolve(message.result);
        return;
      }
      for (const callback of listeners.get(key(message.method, message.sessionId)) || []) callback(message.params);
    },
    failAll(error) {
      for (const { reject } of pending.values()) reject(error);
      pending.clear();
    },
  };
}

/** Resolves after `ms` without keeping the process alive; for timeouts in Promise.race. */
export const deadline = (ms) => new Promise((resolve) => setTimeout(resolve, ms).unref());

/**
 * Start headless Chrome with a throwaway profile and return a browser-level
 * client plus `newPage()`, which opens a tab and returns a session-bound client.
 */
export async function launchChrome(executable, { timeoutMs = 20000 } = {}) {
  const profile = mkdtempSync(join(tmpdir(), 'mlview-shots-'));
  const args = [
    '--headless=new', '--remote-debugging-pipe', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-sync',
    '--disable-background-networking', '--disable-component-update', '--disable-default-apps',
    '--force-color-profile=srgb', '--disable-background-timer-throttling',
    '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--mute-audio',
  ];
  if (process.platform === 'linux' && typeof process.getuid === 'function' && process.getuid() === 0) args.push('--no-sandbox');
  args.push('about:blank');
  const proc = spawn(executable, args, { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  let stderr = '';
  proc.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString('utf8')).slice(-4000); });
  const toChrome = proc.stdio[3];
  const fromChrome = proc.stdio[4];
  const client = createClient((bytes) => toChrome.write(bytes));
  const parse = createMessageParser((message) => client.handle(message));
  fromChrome.on('data', (chunk) => {
    try { parse(chunk); } catch (error) { client.failAll(error); }
  });
  let exited = false;
  const exit = new Promise((resolve) => proc.once('exit', () => { exited = true; resolve(); }));
  proc.once('error', (error) => client.failAll(error));
  exit.then(() => client.failAll(new Error(`Chrome exited.${stderr ? '\n' + stderr.trim() : ''}`)));
  toChrome.on('error', () => undefined);

  let version;
  try {
    version = await Promise.race([
      client.send('Browser.getVersion'),
      deadline(timeoutMs).then(() => { throw new Error(`Chrome did not answer on the DevTools pipe within ${timeoutMs} ms.${stderr ? '\n' + stderr.trim() : ''}`); }),
    ]);
  } catch (error) {
    proc.kill('SIGKILL');
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    throw error;
  }

  async function newPage() {
    const { targetId } = await client.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await client.send('Target.attachToTarget', { targetId, flatten: true });
    const send = (method, params) => client.send(method, params, sessionId);
    return {
      targetId, sessionId, send,
      on: (method, callback) => client.on(method, callback, sessionId),
      async evaluate(expression) {
        const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
        if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
        return result.result.value;
      },
    };
  }

  async function close() {
    if (!exited) {
      await Promise.race([client.send('Browser.close').catch(() => undefined), deadline(3000)]);
      await Promise.race([exit, deadline(5000)]);
      if (!exited) proc.kill('SIGKILL');
      await Promise.race([exit, deadline(2000)]);
    }
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }

  return { version, client, newPage, close };
}
