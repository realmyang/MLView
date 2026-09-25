/**
 * Host → UI message dispatch (CONTRACTS section 4).
 *
 * Every declared type has a named handler; an unknown type is reported through
 * `onUnknown` and otherwise ignored, so a version skew degrades instead of
 * crashing. Malformed frames (no object, wrong `v`) are dropped silently.
 */

import type { ActionResult, Capabilities, Filters, HostToUi, Severity, ThemeKind, ViewState, WorkflowDocument } from './types.js';

export interface ProtocolHandlers {
  init(theme: ThemeKind, capabilities: Capabilities | undefined): void;
  workflow(document: WorkflowDocument): void;
  /**
   * The codes of a new host status banner (§1a). The host bootstrap draws the banner itself; the
   * App only uses the codes to drop a refusal they show is out of date (LINEAGE2-1). `undefined`
   * when the frame carried no code list.
   */
  workflowStatus(codes: string[] | undefined): void;
  /** The answer to a request that carried a `requestId` (§1e). */
  actionResult(result: ActionResult): void;
  theme(kind: ThemeKind): void;
  revealNode(nodeId: string, center: boolean): void;
  revealIssue(issueId: string): void;
  setFilter(severities: Severity[] | undefined, codes: string[] | undefined, query: string | undefined): void;
  restoreState(state: ViewState): void;
  /** `spec: null` clears the scope. NEVER triggers a re-analysis (11.7). */
  setScope(spec: string | null, depth: number | undefined): void;
  /** VIEW-07: draw the diagram and answer with one `exportFile`. */
  requestExport(kind: 'svg' | 'png', scope: 'view' | 'all' | 'scope' | undefined): void;
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
    case 'workflowError':
      // The host bootstrap owns the banner element, which lives outside the
      // App's shell; the App only reads the codes.
      h.workflowStatus(Array.isArray(msg.codes) ? msg.codes.filter((code): code is string => typeof code === 'string') : undefined);
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
    case 'setFilter':
      h.setFilter(msg.severities, msg.codes, msg.query);
      return;
    case 'restoreState':
      h.restoreState(msg.state);
      return;
    case 'setScope':
      h.setScope(msg.spec, msg.depth);
      return;
    case 'requestExport':
      h.requestExport(msg.kind === 'png' ? 'png' : 'svg', msg.scope);
      return;
    case 'cursorHint':
      // followCursor is designed but out of scope for the prototype (A6).
      return;
    default:
      h.onUnknown(String((msg as any).type));
  }
}

/**
 * Coerce a restored scope into something safe. A host predating this feature
 * round-trips the field untouched; a host that mangles it gets no scope rather
 * than a crash (CONTRACTS 11.9).
 */
export function sanitizeScope(scope: any): { spec: string; depth: number } | null {
  if (!scope || typeof scope !== 'object') return null;
  if (typeof scope.spec !== 'string' || !scope.spec) return null;
  const depth = typeof scope.depth === 'number' && isFinite(scope.depth) ? Math.round(scope.depth) : 0;
  if (depth < 0 || depth > 2) return { spec: scope.spec, depth: 0 };
  return { spec: scope.spec, depth };
}

/** Coerce whatever the host handed back into a ViewState we can trust. */
export function sanitizeFilters(filters: any, fallback: Filters): Filters {
  if (!filters || typeof filters !== 'object') return { ...fallback, severities: fallback.severities.slice() };
  const out: Filters = {
    severities: Array.isArray(filters.severities) ? filters.severities.slice() : fallback.severities.slice(),
    stages: Array.isArray(filters.stages) ? filters.stages.slice() : [],
    showSuppressed: !!filters.showSuppressed,
    query: typeof filters.query === 'string' ? filters.query : '',
  };
  // Written only when it is ON, so a restored state keeps the exact key set an
  // older host round-trips (CI-ADOPT, and the same rule as `flow` in 11.9).
  if (filters.changedOnly) out.changedOnly = true;
  return out;
}
