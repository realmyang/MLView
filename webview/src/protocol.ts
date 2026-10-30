/**
 * Host → UI message dispatch.
 *
 * Every declared type has a named handler; an unknown type is reported through
 * `onUnknown` and otherwise ignored, so a version skew degrades instead of
 * crashing. Malformed frames (no object, wrong `v`) are dropped silently.
 */

import { sanitizeStaleFiles } from './freshness.js';
import { sanitizeComparison } from './revisiondiff.js';
import type { WorkflowComparison } from './revisiondiff.js';
import type { ActionResult, Capabilities, Filters, HostToUi, StaleFile, ThemeKind, ViewState, WorkflowDocument } from './types.js';

export interface ProtocolHandlers {
  init(theme: ThemeKind, capabilities: Capabilities | undefined): void;
  /**
   * `comparison`: the frame's `previous` or `replaced`, checked against the
   * document (`sanitizeComparison`); `{}` when it carried neither or they do not fit.
   */
  workflow(document: WorkflowDocument, comparison: WorkflowComparison): void;
  /**
   * The codes of a new host status banner, used only to drop a refusal they show is out of
   * date; the banner's text goes to `hostNotice`. `undefined` when the frame carried no code
   * list.
   */
  workflowStatus(codes: string[] | undefined): void;
  /**
   * The same banner's text, which the mounted App draws as a notice under the header.
   * Before the mount the host bootstrap draws it in a `<pre>` instead.
   */
  hostNotice(message: string, codes: string[] | undefined): void;
  /** The displayed revision's stale files, each with its reason (`[]` clears). */
  stale(files: StaleFile[]): void;
  /** The answer to a request that carried a `requestId`. */
  actionResult(result: ActionResult): void;
  theme(kind: ThemeKind): void;
  /**
   * MLView: Reveal in Diagram (the host's `reveal` frame; a single-kind `revealNode` or
   * `revealIssue` frame is answered the same way): show the step, connection or finding the
   * reader chose in the editor.
   */
  revealNode(nodeId: string, center: boolean): void;
  revealEdge(edgeId: string): void;
  revealIssue(issueId: string): void;
  /** Applies a saved `ViewState`. The host does not send it; tests set collapse or the viewport with it. */
  restoreState(state: ViewState): void;
  onUnknown(type: string): void;
}

export function dispatchHostMessage(msg: HostToUi, h: ProtocolHandlers): void {
  if (!msg || typeof msg !== 'object' || (msg as any).v !== 1) return;
  switch (msg.type) {
    case 'init':
      h.init(msg.theme, msg.capabilities);
      return;
    case 'workflow':
      h.workflow(msg.document, sanitizeComparison(msg.document, msg));
      return;
    case 'workflowError': {
      // Before the mount the host bootstrap draws the banner; after it, the App does.
      const codes = Array.isArray(msg.codes) ? msg.codes.filter((code): code is string => typeof code === 'string') : undefined;
      h.workflowStatus(codes);
      h.hostNotice(typeof msg.message === 'string' ? msg.message : '', codes);
      return;
    }
    case 'stale':
      h.stale(sanitizeStaleFiles(msg.files));
      return;
    case 'actionResult':
      h.actionResult(msg);
      return;
    case 'theme':
      h.theme(msg.kind);
      return;
    case 'reveal': {
      // One frame for the three kinds. A malformed one is dropped.
      const id = (msg as { id?: unknown }).id;
      if (typeof id !== 'string' || !id) return;
      if (msg.kind === 'node') h.revealNode(id, true);
      else if (msg.kind === 'edge') h.revealEdge(id);
      else if (msg.kind === 'issue') h.revealIssue(id);
      return;
    }
    case 'revealNode':
      if (typeof msg.nodeId === 'string' && msg.nodeId) h.revealNode(msg.nodeId, msg.center !== false);
      return;
    case 'revealIssue':
      if (typeof msg.issueId === 'string' && msg.issueId) h.revealIssue(msg.issueId);
      return;
    case 'restoreState':
      h.restoreState(msg.state);
      return;
    default:
      h.onUnknown(String((msg as any).type));
  }
}

/**
 * Coerce saved filters into filters the viewer can trust. Only `severities` and
 * `query` are kept; any other key (`showSuppressed`, `changedOnly`, `stages`) is
 * dropped. So a phase that a saved `stages` list hid comes back shown, because
 * nothing on screen could show it again.
 */
export function sanitizeFilters(filters: any, fallback: Filters): Filters {
  if (!filters || typeof filters !== 'object') return { ...fallback, severities: fallback.severities.slice() };
  return {
    severities: Array.isArray(filters.severities) ? filters.severities.slice() : fallback.severities.slice(),
    query: typeof filters.query === 'string' ? filters.query : '',
  };
}
