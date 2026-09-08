/**
 * MLView renderer — data + protocol types.
 *
 * These mirror contracts/graph.schema.json and CONTRACTS.md sections 4 and 8.
 * Enum-ish fields are typed as `string` on purpose: invariant 1.1/6 requires an
 * unknown kind / stage / edge kind to render with the `unknown` visual instead
 * of throwing, so the renderer must never narrow them at the type level.
 */

export type Severity = 'low' | 'medium' | 'high';
export type ConfidenceBucket = 'certain' | 'likely' | 'possible' | 'speculative';
export type ThemeKind = 'light' | 'dark' | 'hc';
export type HostKind = 'vscode' | 'standalone';

export interface Loc {
  file: string;
  absFile: string;
  /** 1-based, inclusive. */
  line: number;
  /** 0-based. */
  col: number;
  endLine: number;
  endCol: number;
  symbol?: string;
  snippet?: string;
}

export interface RelatedLoc extends Loc {
  role: string;
  message?: string;
}

export interface Port {
  name: string;
  tags: string[];
}

export interface Evidence {
  kind: string;
  detail: string;
  weight: number;
}

export interface IssueCounts {
  low: number;
  medium: number;
  high: number;
}

export interface Stage {
  id: string;
  label: string;
  order: number;
  present: boolean;
  nodeCount: number;
  issueCounts: IssueCounts;
  maxSeverity: Severity | null;
}

export interface MLNode {
  id: string;
  kind: string;
  level: string;
  stage: string;
  label: string;
  sublabel?: string;
  qualname: string;
  fqn?: string;
  framework?: string;
  var?: string;
  loc: Loc;
  defLoc?: Loc;
  parent: string | null;
  attrs: Record<string, string>;
  produces: Port[];
  consumes: Port[];
  ghost: boolean;
  dynamic: boolean;
  confidence: number;
  confidenceBucket: string;
  issueIds: string[];
  collapsedByDefault: boolean;
  stageEvidence: Evidence[];
  /**
   * Present ONLY in a projected document (one carrying `view`). Absent means
   * "this document is not a projection" (CONTRACTS 11.3).
   */
  viewRole?: ViewRole;
}

export interface MLEdge {
  id: string;
  kind: string;
  subkind?: string;
  source: string;
  target: string;
  label?: string;
  loc: Loc;
  tags: string[];
  confidence: number;
  issueIds: string[];
}

export interface Issue {
  id: string;
  code: string;
  ruleVersion: number;
  severity: string;
  confidence: number;
  confidenceBucket: string;
  title: string;
  message: string;
  why: string;
  fixHint: string;
  loc: Loc;
  relatedLocs: RelatedLoc[];
  nodeIds: string[];
  edgeIds: string[];
  stage: string;
  frameworks: string[];
  tags: string[];
  evidence: Evidence[];
  suppressed: boolean;
  docs: string;
}

/**
 * Every `Diagnostic.kind` the analyzer is known to emit today.
 *
 * The field itself stays `string` (invariant 1.1/6: an unknown kind renders
 * generically, it never throws), so this list is documentation the renderer can
 * loop over — `ui/chrome.ts` branches on the members it draws specially and lets
 * everything else fall through to the generic note chip.
 *
 * The last five are the COVERAGE batch: they exist so the product can tell
 * "I checked and it is fine" apart from "I could not check".
 */
export const KNOWN_DIAGNOSTIC_KINDS = [
  'parse_error',
  'dynamic_scope',
  'rule_error',
  'truncated',
  'notebook_skipped',
  'framework_suppressed',
  'config_warning',
  'untagged_dataflow',
  'single_file_analysis',
  'unresolved_callee',
  'config_unresolved',
  'notebook_analyzed',
] as const;

export type DiagnosticKind = (typeof KNOWN_DIAGNOSTIC_KINDS)[number];

export function isKnownDiagnosticKind(kind: string): kind is DiagnosticKind {
  return (KNOWN_DIAGNOSTIC_KINDS as readonly string[]).indexOf(kind) >= 0;
}

export interface Diagnostic {
  /** One of `KNOWN_DIAGNOSTIC_KINDS`, or anything a newer analyzer invents. */
  kind: string;
  message: string;
  file?: string;
  line?: number;
  scope?: string;
  ruleCode?: string;
  codes?: string[];
  count?: number;
}

export interface Stats {
  nodes: number;
  edges: number;
  issues: IssueCounts;
  suppressed?: number;
  durationMs: number;
  truncated: boolean;
}

export interface Workspace {
  root: string;
  entrypoints: string[];
  filesAnalyzed: number;
  filesFailed: number;
  notebooksSkipped: number;
  frameworks: string[];
  configPath?: string;
}

export interface Generator {
  name: string;
  version: string;
  rendererSha: string;
  generatedAt: string;
}

/**
 * A node's role in a PROJECTION (CONTRACTS 11.3).
 *
 * `core` is the scope itself and the only role an issue may be retained
 * through; `boundary` was pulled in by `view.depth` edge hops and is drawn as a
 * faded, dashed stub with NO severity badge (its findings are out of scope, and
 * a badge you cannot open is a lie); `context` is an ancestor kept so `parent`
 * still forms a forest, drawn as an empty frame.
 */
export type ViewRole = 'core' | 'boundary' | 'context';

export interface ViewAnchor {
  id: string;
  qualname: string;
  label: string;
  file: string;
  line: number;
}

/**
 * Present ONLY when this document is a PROJECTION of a whole-workspace
 * analysis. A projection never restates project-level truth: `workspace`,
 * `generator`, `diagnostics` and every `stage.present` still describe the FULL
 * analysis, while `stats` and the stage counts describe the projection.
 */
export interface View {
  scope: string;
  label: string;
  depth: number;
  counts: { core: number; boundary: number; context: number };
  of: { nodes: number; edges: number; issues: IssueCounts };
  hidden: { nodes: number; edges: number; inboundEdges: number; outboundEdges: number };
  resolvedTo: ViewAnchor[];
  ambiguous?: boolean;
  empty?: boolean;
}

export interface MLGraph {
  schemaVersion: string;
  generator: Generator;
  workspace: Workspace;
  stages: Stage[];
  nodes: MLNode[];
  edges: MLEdge[];
  issues: Issue[];
  diagnostics: Diagnostic[];
  stats: Stats;
  /** Appended as the LAST key by a projection; absent in a whole-workspace document. */
  view?: View;
}

/* ── view state ────────────────────────────────────────────────────────── */

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface Sel {
  kind: 'node' | 'edge' | 'issue';
  id: string;
}

export interface Filters {
  severities: Severity[];
  stages: string[];
  showSuppressed: boolean;
  query: string;
}

export type RailTab = 'issues' | 'inspector' | 'outline';

/** How the Issues rail groups its rows (RAIL-GROUP). `none` is the default. */
export type RailGroupBy = 'none' | 'rule' | 'file';

export interface ViewState {
  viewport: Viewport;
  selection: Sel | null;
  collapsed: string[];
  filters: Filters;
  railTab: RailTab;
  /** Optional: the minimap's collapsed tab survives a reload the way `collapsed` does. */
  minimapCollapsed?: boolean;
  /** Optional: the active scope, as one canonical selector string (CONTRACTS 11.9). */
  scope?: { spec: string; depth: number };
  /** Optional: flow animation on/off, like `minimapCollapsed`. Absent = on. */
  flow?: boolean;
  /** Optional: the Issues rail's grouping. Absent = 'none' (RAIL-GROUP). */
  railGroupBy?: RailGroupBy;
  /** Optional: the legend panel's open state, remembered per viewer (VIEW-10). */
  legendOpen?: boolean;
}

/* ── host protocol (CONTRACTS section 4) ───────────────────────────────── */

export interface Capabilities {
  canOpenSource: boolean;
  canReanalyze: boolean;
  canExport: boolean;
  canAskAssistant: boolean;
}

export interface HostAction {
  id: string;
  label: string;
}

export type HostToUi =
  | { v: 1; type: 'init'; schemaVersion: string; theme: ThemeKind; host: HostKind; capabilities: Capabilities }
  | { v: 1; type: 'graph'; requestId: string; graph: MLGraph; preserve?: { viewport?: Viewport; selection?: Sel | null; collapsed?: string[] } }
  | { v: 1; type: 'analysisStarted'; requestId: string; scope: 'workspace' | 'file'; path?: string }
  | { v: 1; type: 'analysisProgress'; requestId: string; done: number; total: number; file?: string }
  | { v: 1; type: 'analysisFailed'; requestId: string; message: string; detail?: string; actions?: HostAction[] }
  | { v: 1; type: 'theme'; kind: ThemeKind }
  | { v: 1; type: 'revealNode'; nodeId: string; center?: boolean; approximate?: boolean }
  | { v: 1; type: 'revealIssue'; issueId: string }
  | { v: 1; type: 'cursorHint'; file: string; line: number }
  | { v: 1; type: 'setFilter'; severities?: Severity[]; codes?: string[]; query?: string }
  | { v: 1; type: 'stale'; changedFiles: string[] }
  | { v: 1; type: 'restoreState'; state: ViewState }
  /** `spec: null` clears the scope. Never triggers a re-analysis (CONTRACTS 11.7). */
  | { v: 1; type: 'setScope'; spec: string | null; depth?: number };

export type UiToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'openLocation'; file: string; absFile: string; line: number; col: number; endLine: number; endCol: number; preview?: boolean }
  | { v: 1; type: 'selectNode'; nodeId: string | null }
  | { v: 1; type: 'requestRefresh'; scope: 'workspace' | 'file'; path?: string }
  | { v: 1; type: 'exportHtml' }
  | { v: 1; type: 'copy'; text: string }
  | { v: 1; type: 'saveState'; state: ViewState }
  | { v: 1; type: 'action'; id: string }
  | { v: 1; type: 'askAssistant'; nodeId: string; prompt: string }
  | { v: 1; type: 'log'; level: 'debug' | 'info' | 'warn' | 'error'; message: string }
  /**
   * Posted on EVERY scope change including a clear (then `spec: null`,
   * `label: "Everything"`, `nodes === of`). The field is named `spec`, not
   * `scope`: `analysisStarted` and `requestRefresh` already carry a field
   * literally named `scope` with a different meaning (CONTRACTS 11.7).
   */
  | { v: 1; type: 'scopeChanged'; spec: string | null; label: string; nodes: number; of: number };

export interface HostBridge {
  host: HostKind;
  theme: ThemeKind;
  /**
   * OPTIONAL, viewer-internal. `theme` is always a resolved kind (CONTRACTS
   * section 8); a bridge that was asked for 'auto' may additionally report that
   * here so the standalone theme switch can pre-select Auto and keep following
   * the OS. Hosts may omit it — nothing in the frozen protocol depends on it.
   */
  themePreference?: 'auto' | ThemeKind;
  capabilities: Capabilities;
  post(msg: UiToHost): void;
  onMessage(cb: (msg: HostToUi) => void): () => void;
  saveState(s: ViewState): void;
  loadState(): ViewState | null;
}

export interface ScopeSummary {
  spec: string | null;
  label: string;
  depth: number;
  nodes: number;
  of: number;
}

export interface MLViewApp {
  update(graph: MLGraph, preserve?: Partial<ViewState>): void;
  /**
   * Re-project and relayout LOCALLY. Never posts `requestRefresh`, never
   * touches the analyzer. An unresolvable spec is a no-op plus a toast; it
   * never throws out of `mount` or `setScope` (CONTRACTS 11.8).
   */
  setScope(spec: string | null, opts?: { depth?: number }): void;
  getScope(): ScopeSummary;
  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean }): void;
  focusIssue(id: string): void;
  setFilters(f: Partial<Filters>): void;
  setTheme(kind: ThemeKind): void;
  getState(): ViewState;
  destroy(): void;
}
