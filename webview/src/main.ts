/**
 * The single global (CONTRACTS section 8, amendment A3):
 *
 *   window.MLView = { version, mount, bridges: { vscode(), standalone(opts) } }
 *
 * `__internal` is an additional debug surface used by webview/test and
 * dev/states.html only; hosts must not depend on it.
 */

import { App } from './app.js';
import { standaloneBridge, vscodeBridge, StandaloneOptions } from './bridges.js';
import { internals } from './demo.js';
import type { HostBridge, MLGraph, MLViewApp } from './types.js';
import type { WorkflowDocument, WorkflowViewApp } from './types.js';
import { normalizeWorkflow } from './workflow.js';

export const version = '0.1.0';

export function mount(root: HTMLElement, graph: MLGraph, bridge: HostBridge): MLViewApp {
  if (!root) throw new Error('MLView.mount: a root element is required');
  if (!bridge) throw new Error('MLView.mount: a HostBridge is required');
  return new App(root, graph || null, bridge);
}

export function mountWorkflow(root: HTMLElement, document: WorkflowDocument, bridge: HostBridge): WorkflowViewApp {
  if (!root) throw new Error('MLView.mountWorkflow: a root element is required');
  if (!bridge) throw new Error('MLView.mountWorkflow: a HostBridge is required');
  const app = new App(root, null, bridge);
  app.setWorkflow(document);
  return app;
}

export { normalizeWorkflow };

export const bridges = {
  vscode(): HostBridge {
    return vscodeBridge();
  },
  standalone(opts?: StandaloneOptions): HostBridge {
    return standaloneBridge(opts);
  },
};

export const __internal = internals;
