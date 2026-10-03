/**
 * The single global (CONTRACTS section 8, amendment A3):
 *
 *   window.MLView = { version, mountWorkflow, bridges: { vscode() } }
 */

import { App } from './app.js';
import { vscodeBridge } from './bridges.js';
import type { HostBridge } from './types.js';
import type { WorkflowDocument, WorkflowViewApp } from './types.js';
import { normalizeWorkflow } from './workflow.js';

export const version = '0.3.0';

/**
 * Mount the viewer on the first `workflow` frame. `comparison` (viewer M4, step 16) is that frame's
 * `previous` or `replaced`, which the host bootstrap passes on; the viewer checks it again.
 */
export function mountWorkflow(root: HTMLElement, document: WorkflowDocument, bridge: HostBridge, comparison?: { previous?: WorkflowDocument; replaced?: string }): WorkflowViewApp {
  if (!root) throw new Error('MLView.mountWorkflow: a root element is required');
  if (!bridge) throw new Error('MLView.mountWorkflow: a HostBridge is required');
  const app = new App(root, bridge);
  app.setWorkflow(document, undefined, comparison);
  return app;
}

export { normalizeWorkflow };

export const bridges = {
  vscode(): HostBridge {
    return vscodeBridge();
  },
};
