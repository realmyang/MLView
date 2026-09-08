/**
 * Host → UI message dispatch (CONTRACTS section 4).
 *
 * Every declared type has a named handler; an unknown type is reported through
 * `onUnknown` and otherwise ignored, so a version skew degrades instead of
 * crashing. Malformed frames (no object, wrong `v`) are dropped silently.
 */

import type { Capabilities, Filters, HostAction, HostToUi, MLGraph, Severity, ThemeKind, ViewState } from './types.js';

export interface ProtocolHandlers {
  init(theme: ThemeKind, capabilities: Capabilities | undefined): void;
  graph(graph: MLGraph, preserve: Partial<ViewState> | undefined): void;
  analysisStarted(): void;
  analysisProgress(done: number, total: number, file?: string): void;
  analysisFailed(message: string, detail: string | undefined, actions: HostAction[] | undefined): void;
  theme(kind: ThemeKind): void;
  revealNode(nodeId: string, center: boolean): void;
  revealIssue(issueId: string): void;
  setFilter(severities: Severity[] | undefined, codes: string[] | undefined, query: string | undefined): void;
  stale(changedFiles: string[]): void;
  restoreState(state: ViewState): void;
  /** `spec: null` clears the scope. NEVER triggers a re-analysis (11.7). */
  setScope(spec: string | null, depth: number | undefined): void;
  onUnknown(type: string): void;
}

export function dispatchHostMessage(msg: HostToUi, h: ProtocolHandlers): void {
  if (!msg || typeof msg !== 'object' || (msg as any).v !== 1) return;
  switch (msg.type) {
    case 'init':
      h.init(msg.theme, msg.capabilities);
      return;
    case 'graph':
      h.graph(msg.graph, msg.preserve as Partial<ViewState> | undefined);
      return;
    case 'analysisStarted':
      h.analysisStarted();
      return;
    case 'analysisProgress':
      h.analysisProgress(msg.done, msg.total, msg.file);
      return;
    case 'analysisFailed':
      h.analysisFailed(msg.message, msg.detail, msg.actions);
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
    case 'stale':
      h.stale(msg.changedFiles || []);
      return;
    case 'restoreState':
      h.restoreState(msg.state);
      return;
    case 'setScope':
      h.setScope(msg.spec, msg.depth);
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
  return {
    severities: Array.isArray(filters.severities) ? filters.severities.slice() : fallback.severities.slice(),
    stages: Array.isArray(filters.stages) ? filters.stages.slice() : [],
    showSuppressed: !!filters.showSuppressed,
    query: typeof filters.query === 'string' ? filters.query : '',
  };
}
