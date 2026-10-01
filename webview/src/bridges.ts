/**
 * The host bridge (CONTRACTS section 8 + amendment A3).
 *
 * `vscode()` wraps acquireVsCodeApi() exactly once. The renderer never navigates
 * the document and never opens or writes a file itself: every request is a
 * message the VS Code host answers.
 */

import type { Capabilities, HostBridge, HostToUi, ThemeKind, UiToHost, ViewState } from './types.js';

let cachedVsCodeApi: any = null;

function acquireOnce(): any {
  if (cachedVsCodeApi) return cachedVsCodeApi;
  const g: any = typeof window !== 'undefined' ? (window as any) : {};
  if (typeof g.acquireVsCodeApi === 'function') {
    try {
      cachedVsCodeApi = g.acquireVsCodeApi();
    } catch (_e) {
      cachedVsCodeApi = null;
    }
  }
  return cachedVsCodeApi;
}

function detectVsCodeTheme(): ThemeKind {
  if (typeof document === 'undefined' || !document.body) return 'light';
  const cls = document.body.className || '';
  if (cls.indexOf('vscode-high-contrast') >= 0) return 'hc';
  if (cls.indexOf('vscode-dark') >= 0) return 'dark';
  return 'light';
}

function listenToWindow(cb: (msg: HostToUi) => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const handler = (ev: MessageEvent) => {
    const data = ev && (ev as any).data;
    if (data && typeof data === 'object') cb(data as HostToUi);
  };
  window.addEventListener('message', handler as EventListener);
  return () => window.removeEventListener('message', handler as EventListener);
}

export function vscodeBridge(): HostBridge {
  const api = acquireOnce();
  const capabilities: Capabilities = {
    canOpenSource: true,
    canReanalyze: true,
    canExport: true,
    canAskAssistant: false,
  };
  return {
    host: 'vscode',
    theme: detectVsCodeTheme(),
    capabilities,
    post(msg: UiToHost) {
      if (api && typeof api.postMessage === 'function') api.postMessage(msg);
    },
    onMessage(cb) {
      return listenToWindow(cb);
    },
    saveState(state: ViewState) {
      if (api && typeof api.setState === 'function') api.setState(state);
    },
    loadState() {
      if (api && typeof api.getState === 'function') {
        const s = api.getState();
        return s && typeof s === 'object' ? (s as ViewState) : null;
      }
      return null;
    },
  };
}
