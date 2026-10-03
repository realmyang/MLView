/**
 * The host protocol, inbound: every `HostToUi` frame the viewer answers.
 *
 * `protocol.ts` owns the shape of a frame and the dispatch; this file owns what
 * each one MEANS to the application. Two invariants run through it: an unknown
 * message is logged and ignored, never an error (invariant 1.1/6), and the host
 * is the only thing that may hand us a new document.
 */

import { dispatchHostMessage } from '../protocol.js';
import { renderChrome, renderRail } from './surfaces.js';
import { onWorkflowStatus } from '../workflow.js';
import { applyState } from './state.js';
import type { App } from '../app.js';
import type { HostToUi } from '../types.js';

export function onHostMessage(app: App, msg: HostToUi): void {
  dispatchHostMessage(msg, {
    init: (theme, capabilities) => {
      app.caps = capabilities || app.caps;
      app.setTheme(theme);
      renderChrome(app);
      renderRail(app);
    },
    // One owner per frame (§1e): the host bootstrap mounts on the first
    // `workflow` and ignores the rest; this listener applies every later one.
    // A frame carrying the very document object already applied is dropped, so
    // no path can render the same frame twice. Viewer M4: the frame's comparison goes with it.
    workflow: (document, comparison) => {
      if (document === app.workflowDocument) return;
      app.setWorkflow(document, undefined, comparison);
    },
    workflowStatus: (codes) => onWorkflowStatus(app, codes),
    hostNotice: (message, codes) => app.showHostNotice(message, codes),
    stale: (files) => app.setStale(files),
    actionResult: (result) => app.onActionResult(result),
    theme: (kind) => app.setTheme(kind),
    // Viewer M3 (step 14): MLView: Reveal in Diagram.
    revealNode: (nodeId, center) => app.revealClaim({ kind: 'node', id: nodeId }, { center }),
    revealEdge: (edgeId) => app.revealClaim({ kind: 'edge', id: edgeId }),
    revealIssue: (issueId) => app.revealClaim({ kind: 'issue', id: issueId }),
    restoreState: (state) => applyState(app, state, true),
    onUnknown: (type) =>
      app.bridge.post({ v: 1, type: 'log', level: 'debug', message: 'ignored unknown message type: ' + type }),
  });
}
