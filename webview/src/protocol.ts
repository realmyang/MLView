/**
 * Host → UI message dispatch (CONTRACTS section 4).
 *
 * Every declared type has a named handler; an unknown type is reported through
 * `onUnknown` and otherwise ignored, so a version skew degrades instead of
 * crashing. Malformed frames (no object, wrong `v`) are dropped silently.
 */

import { sanitizeStaleFiles } from './freshness.js';
import type { ActionResult, Capabilities, Filters, HostToUi, StaleFile, ThemeKind, ViewState, WorkflowDocument } from './types.js';

export interface ProtocolHandlers {
  init(theme: ThemeKind, capabilities: Capabilities | undefined): void;
  workflow(document: WorkflowDocument): void;
  /**
   * The codes of a new host status banner (§1a). The host bootstrap draws the banner itself; the
   * App only uses the codes to drop a refusal they show is out of date (LINEAGE2-1). `undefined`
   * when the frame carried no code list.
   */
  workflowStatus(codes: string[] | undefined): void;
  /**
   * The same banner's text, which the mounted App draws as a notice under the header (viewer M1).
   * Before the mount the host bootstrap draws it in a `<pre>` instead.
   */
  hostNotice(message: string, codes: string[] | undefined): void;
  /** Viewer M1: the displayed revision's stale files, each with its reason (`[]` clears). */
  stale(files: StaleFile[]): void;
  /** The answer to a request that carried a `requestId` (§1e). */
  actionResult(result: ActionResult): void;
  theme(kind: ThemeKind): void;
  /** Not sent by the host today; kept for the planned "Reveal in Diagram" (M3). */
  revealNode(nodeId: string, center: boolean): void;
  /** Not sent by the host today; kept for the planned "Reveal in Diagram" (M3). */
  revealIssue(issueId: string): void;
  /** Applies a saved `ViewState` (the geometry golden and the protocol tests drive collapse with it). */
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
      h.workflow(msg.document);
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
    case 'revealNode':
      h.revealNode(msg.nodeId, msg.center !== false);
      return;
    case 'revealIssue':
      h.revealIssue(msg.issueId);
      return;
    case 'restoreState':
      h.restoreState(msg.state);
      return;
    default:
      h.onUnknown(String((msg as any).type));
  }
}

/**
 * Coerce saved filters into filters we can trust. Keys this viewer no longer
 * writes (`showSuppressed`, `changedOnly`, and since viewer M2 the phase chips'
 * `stages`) are ignored: a phase hidden by an older viewer comes back shown,
 * because nothing on screen could show it again.
 */
export function sanitizeFilters(filters: any, fallback: Filters): Filters {
  if (!filters || typeof filters !== 'object') return { ...fallback, severities: fallback.severities.slice() };
  return {
    severities: Array.isArray(filters.severities) ? filters.severities.slice() : fallback.severities.slice(),
    query: typeof filters.query === 'string' ? filters.query : '',
  };
}
