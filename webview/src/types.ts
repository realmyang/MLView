/**
 * MLView renderer — the authored WorkflowDocument, the renderer's internal view
 * model (`MLGraph`, built by `workflow.ts`), and the host protocol.
 *
 * Enum-ish fields are typed as `string` on purpose: an unknown kind / phase /
 * edge kind renders with the `unknown` visual instead of throwing, so the
 * renderer must never narrow them at the type level.
 */

export type Severity = 'low' | 'medium' | 'high';
export type ThemeKind = 'light' | 'dark' | 'hc';
export type HostKind = 'vscode';

export interface Loc {
  file: string;
  absFile: string;
  /** 1-based, inclusive. */
  line: number;
  /** 0-based. */
  col: number;
  endLine: number;
  endCol: number;
  /** The cited quote. */
  snippet?: string;
  /**
   * An authored notebook citation's cell: the contract's zero-based cell index
   * (markdown cells count), with `line` relative to that cell. Absent elsewhere.
   */
  cell?: number;
  /** Authored-workflow evidence record that supplied this location. */
  evidenceId?: string;
}

export interface RelatedLoc extends Loc {
  role: string;
  message?: string;
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
  /** What the card's second line draws: the authored detail, or the basis. */
  sublabel?: string;
  /** The authored label again (the scope resolver and the outline read it). */
  qualname: string;
  loc: Loc;
  parent: string | null;
  /** `{ basis }`: the card's chip row, which the layout reserves (re-recorded in M2). */
  attrs: Record<string, string>;
  issueIds: string[];
  /** Renderer-local authored-workflow epistemic basis. */
  basis?: WorkflowBasis;
  /** Renderer-local authored evidence anchors, in document order. */
  evidenceLocs?: Loc[];
  /**
   * Viewer M1: the authored `detail`, verbatim, or absent when the author wrote
   * none. Read by the Inspector and the card's accessible name only; the card
   * itself still draws `sublabel`, so layout does not depend on it.
   */
  detail?: string;
  /** Viewer M1: the authored label of the node's phase (`stage` is its id). */
  phaseLabel?: string;
  /**
   * Present ONLY in a projected document (one carrying `view`). Absent means
   * "this document is not a projection" (CONTRACTS 11.3).
   */
  viewRole?: ViewRole;
}

export interface MLEdge {
  id: string;
  kind: string;
  /** Read by the layout core (`subkind === 'back'`); authored edges never set it. */
  subkind?: string;
  source: string;
  target: string;
  label?: string;
  loc: Loc;
  issueIds: string[];
  /** Renderer-local authored-workflow epistemic basis. */
  basis?: WorkflowBasis;
  /** Renderer-local authored evidence anchors, in document order. */
  evidenceLocs?: Loc[];
  /**
   * Renderer-local: the kind word the author wrote, when `kind` is the styled
   * kind it was normalised to (`dataflow` drawn as `data`; Campaign 3, issue 9).
   * Absent when the two are the same or the author gave no kind.
   */
  authoredKind?: string;
  /**
   * Viewer M1: the authored label, verbatim. `label` is what the canvas draws,
   * which still carries the " · basis" suffix until the card re-record (M2).
   */
  authoredLabel?: string;
}

/** An authored finding, as the renderer reads it. */
export interface Issue {
  id: string;
  /** The finding id again (search and the Findings list print it). */
  code: string;
  severity: string;
  title: string;
  message: string;
  /** The authored `suggestion`, shown as "What to change"; '' when there is none. */
  fixHint: string;
  loc: Loc;
  relatedLocs: RelatedLoc[];
  nodeIds: string[];
  edgeIds: string[];
  stage: string;
  /** Renderer-local authored-workflow epistemic basis. */
  basis?: WorkflowBasis;
}

/**
 * A document-level note: `workflow_limitation` (one per authored coverage
 * limitation) or `config_warning` (a scope note the projection appends).
 */
export interface Diagnostic {
  kind: string;
  message: string;
}

export interface Stats {
  nodes: number;
  edges: number;
  issues: IssueCounts;
  durationMs: number;
}

export interface Workspace {
  /** The document title. */
  root: string;
  entrypoints: string[];
  /** How many files the author lists as inspected. */
  filesAnalyzed: number;
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
  /**
   * Renderer-local, set only by the WorkflowDocument adapter: the authored
   * coverage status and how many limitations the author listed, so the
   * zero-findings state can name them instead of claiming a check (VIEWUI-1).
   */
  authoredCoverage?: { status: string; limitations: number };
}

/* ── model-authored workflow document ───────────────────────────────── */

export type WorkflowBasis = 'observed' | 'inferred' | 'unresolved';
export interface WorkflowEvidence { id: string; file: string; line: number; endLine: number; quote: string; cell?: number }
export interface WorkflowNode { id: string; label: string; phase: string; parent?: string; kind?: string; detail?: string; basis: WorkflowBasis; evidence: string[] }
export interface WorkflowEdge { id: string; source: string; target: string; label: string; kind?: string; basis: WorkflowBasis; evidence: string[] }
export interface WorkflowFinding { id: string; title: string; message: string; severity: Severity; nodeIds: string[]; edgeIds?: string[]; basis: WorkflowBasis; evidence: string[]; counterEvidence?: string[]; suggestion?: string }
export interface WorkflowDocument {
  workflowVersion: '1.0';
  title: string;
  producer: { kind: 'host-llm'; host: 'copilot' | 'codex' | 'claude-code' | 'unknown'; model?: string };
  revision: { id: string; parent?: string };
  request: { question: string; scope: string; entrypoints?: string[]; configuration?: string };
  phases: { id: string; label: string }[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  findings: WorkflowFinding[];
  evidence: WorkflowEvidence[];
  coverage: { status: 'scoped' | 'partial'; summary: string; inspectedFiles: string[]; limitations: string[] };
  verification?: { files: Record<string, string>; publishedAt: string };
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
  query: string;
}

export type RailTab = 'issues' | 'inspector' | 'outline';

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
  /** Optional: the legend panel's open state, remembered per viewer (VIEW-10). */
  legendOpen?: boolean;
  /**
   * The authored revision id the viewport belongs to. Written only for a
   * `workflow-view/1` graph and absent otherwise, like every optional field
   * here. A remounted viewer restores `viewport` instead of fitting only when
   * this equals the revision it is handed (VIEWUI-3).
   */
  workflowRevision?: string;
  /**
   * The Refine composer of that authored revision: open, intent and custom
   * text (VIEWUI-4). Absent at its default (closed, Explain, no text), and
   * restored on a remount only when `workflowRevision` matches.
   */
  composer?: ComposerState;
}

/** A Refine composer's reader-visible state. */
export interface ComposerState {
  open: boolean;
  intent: RefineIntent;
  custom: string;
}

/* ── host protocol (CONTRACTS section 4) ───────────────────────────────── */

/**
 * The host's `init` capabilities. The viewer reads `canOpenSource` only; the host also sends
 * `canRefine` and three flags of the retired analyzer UI (`canReanalyze`, `canExport`,
 * `canAskAssistant`), all ignored here.
 */
export interface Capabilities {
  canOpenSource: boolean;
  canRefine?: boolean;
}

/** The five refinement intents the composer offers (Campaign 1 §1e/§1f). */
export type RefineIntent = 'explain' | 'expand' | 'challenge' | 'trace' | 'custom';

/** The requests that carry a `requestId` and are answered by one `actionResult`. */
export type ResultAction = 'exportFile' | 'copy' | 'refineWorkflow';

/**
 * The host's single answer to an `exportFile`, `copy` or `refineWorkflow`
 * request that carried a valid `requestId` (§1e). `message` is host-authored
 * and never contains an absolute path; `name` is the saved basename and is sent
 * only for a completed export.
 */
export interface ActionResult {
  v: 1;
  type: 'actionResult';
  requestId: string;
  action: ResultAction;
  outcome: 'done' | 'cancelled' | 'failed';
  message?: string;
  name?: string;
}

/** Why a cited or inspected file no longer matches the published revision (the host's hash check). */
export type StaleReason = 'changed' | 'missing' | 'unreadable' | 'too-large';

/** One stale file, workspace-relative, as the host's `stale` frame carries it. */
export interface StaleFile {
  path: string;
  reason: StaleReason;
}

export type HostToUi =
  | { v: 1; type: 'init'; theme: ThemeKind; capabilities: Capabilities; artifact?: string }
  | { v: 1; type: 'theme'; kind: ThemeKind }
  /** Not sent by the host today; kept for the planned "Reveal in Diagram" (M3). */
  | { v: 1; type: 'revealNode'; nodeId: string; center?: boolean }
  /** Not sent by the host today; kept for the planned "Reveal in Diagram" (M3). */
  | { v: 1; type: 'revealIssue'; issueId: string }
  /**
   * Viewer M1. The displayed revision's stale files, each with its reason, posted after the
   * `workflow` frame whenever the set changes (an empty list clears the marks).
   */
  | { v: 1; type: 'stale'; files: StaleFile[] }
  /** Applies a saved `ViewState`. The host does not send it; the tests drive collapse with it. */
  | { v: 1; type: 'restoreState'; state: ViewState }
  /** A new or refreshed authored revision. */
  | { v: 1; type: 'workflow'; document: WorkflowDocument }
  /**
   * The host's status banner. Before the mount the host bootstrap draws it; after it the App
   * draws it as a notice, and reads `codes` to clear a refinement refusal about the artifact
   * file once the file is readable again (LINEAGE2-1). `''` clears the banner.
   */
  | { v: 1; type: 'workflowError'; message: string; retained?: boolean; codes?: string[] }
  | ActionResult;

export type UiToHost =
  | { v: 1; type: 'ready' }
  /**
   * `focus: true` (viewer M1) is the explicit open-and-focus gesture (Alt+Enter, Alt+click); every
   * other open keeps the keyboard on the diagram.
   */
  | { v: 1; type: 'openLocation'; file: string; absFile: string; line: number; col: number; endLine: number; endCol: number; preview?: boolean; evidenceId?: string; cell?: number; focus?: boolean }
  /** Viewer M1: the workspace-root hint's two actions. The host owns the folder. */
  | { v: 1; type: 'workspaceHint'; action: 'add' | 'open' }
  /**
   * `customText` is sent only, and then required, when `intent` is `custom`.
   * `requestId` matches /^[A-Za-z0-9_-]{1,64}$/ and is answered by one
   * `actionResult`.
   */
  | {
      v: 1;
      type: 'refineWorkflow';
      requestId?: string;
      revisionId: string;
      intent: RefineIntent;
      customText?: string;
      selection?: { kind: 'node' | 'edge' | 'issue'; id: string };
    }
  /**
   * VIEW-07. The viewer rendered the diagram to bytes and asks the host to save
   * them. It is a REQUEST, never a write: the extension owns the save dialog.
   * `base64` carries the file (UTF-8 SVG markup or PNG bytes) because
   * `postMessage` is a structured-clone channel that a `Blob` does not reliably
   * survive. `name` is a suggested filename only.
   *
   * Two spellings of the same facts are always written: `name === suggestedName`
   * and `base64 === data` (the host validates `{kind, data, suggestedName?,
   * scope?}`). `scope` is the region in the host's vocabulary (`all`, not
   * `diagram`).
   */
  | {
      v: 1;
      type: 'exportFile';
      kind: 'svg' | 'png';
      name: string;
      base64: string;
      data: string;
      suggestedName: string;
      scope: 'view' | 'all' | 'scope';
      requestId?: string;
    }
  | { v: 1; type: 'copy'; text: string; requestId?: string }
  /** Posted for a host frame of an unknown type; the host ignores it. */
  | { v: 1; type: 'log'; level: 'debug' | 'info' | 'warn' | 'error'; message: string };

export interface HostBridge {
  host: HostKind;
  theme: ThemeKind;
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
  /**
   * Re-project and relayout LOCALLY; nothing is posted to the host. An
   * unresolvable spec is a no-op plus a toast; it
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

export interface WorkflowViewApp extends MLViewApp {
  setWorkflow(document: WorkflowDocument, preserve?: Partial<ViewState>): void;
}
