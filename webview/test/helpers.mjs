import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

export const HERE = dirname(fileURLToPath(import.meta.url));
export const WEBVIEW_ROOT = join(HERE, '..');
export const REPO_ROOT = join(WEBVIEW_ROOT, '..');
export const DIST_JS = join(WEBVIEW_ROOT, 'dist', 'mlview.js');

export async function loadBundle() {
  const code = await readFile(DIST_JS, 'utf8');
  const virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', () => undefined);
  const dom = new JSDOM('<!doctype html><html><head></head><body><div id="mlview-root"></div></body></html>', {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'https://mlview.test/', virtualConsole,
  });
  if (typeof dom.window.structuredClone !== 'function') {
    dom.window.structuredClone = (value) => JSON.parse(JSON.stringify(value));
  }
  const script = dom.window.document.createElement('script');
  script.textContent = code;
  dom.window.document.head.appendChild(script);
  if (!dom.window.MLView) throw new Error('bundle did not define window.MLView');
  return { dom, window: dom.window, document: dom.window.document, MLView: dom.window.MLView };
}

export function recordingBridge(window, host = 'vscode', overrides = {}) {
  const posted = [];
  let listener = null;
  return {
    host, theme: 'light',
    capabilities: { canOpenSource: true, canReanalyze: true, canExport: true, canAskAssistant: false, ...(overrides.capabilities || {}) },
    posted,
    post(message) { posted.push(message); },
    onMessage(callback) { listener = callback; return () => { listener = null; }; },
    send(message) { if (listener) listener(message); },
    saveState(state) { this.saved = state; },
    loadState() { return overrides.state || null; },
  };
}
