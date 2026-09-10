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
  /**
   * NB. The code cell this location fell in, when the file is a notebook the
   * analyzer read. Absent on every `.py` location, and absent on a notebook
   * location the ingest could not map — in which case the viewer shows the flat
   * line rather than inventing a cell.
   *
   * `line` above stays the FLAT line into the concatenated code cells and is
   * what `openLocation` posts: the hosts own the mapping onto a
   * `vscode-notebook-cell:` URI. These two fields exist so the viewer can SHOW
   * a human `name.ipynb > cell 3 : 4` without changing a byte on the wire.
   */
  cell?: number;
  /** NB. 1-based line inside `cell`. Meaningless without `cell`. */
  cellLine?: number;
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
  /**
   * VIEW-08, RENDERER-LOCAL and never on the wire. The diff overlay is a
   * SEPARATE document (CONTRACTS 11.38 B) whose `nodes[]` is keyed on the same
   * stable ids, and `diff/adopt.ts` lifts each entry's `status` onto the node it
   * describes — exactly as `adoptCellMap` lifts the notebook cell map off
   * `attrs` — so every drawing surface keeps reading a plain `MLNode` and none
   * of them has to know the overlay exists. Absent means "no overlay is loaded",
   * which is not the same as `unchanged`.
   */
  diffStatus?: string;
  /** VIEW-08, renderer-local: the overlay's `changed[]` field names, if any. */
  diffChanged?: string[];
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

/**
 * H5. One edit an opted-in rule computed FROM THE AST.
 *
 * `newText` replaces the half-open range `[line:col, endLine:endCol)`, so an
 * insertion is an empty range and a deletion an empty `newText`. Lines are
 * 1-based and columns 0-based, exactly like `Loc` (§0): these are the analyzer's
 * own coordinates and the host boundary is the only place they are converted.
 *
 * The viewer NEVER applies one. It draws it, and it posts `applyFix` — the host
 * owns the edit, behind a preview, which is what keeps "never auto-applied" a
 * property of the system rather than a promise in a comment.
 */
export interface FixEdit {
  file: string;
  absFile: string;
  line: number;
  col: number;
  endLine: number;
  endCol: number;
  newText: string;
}

/**
 * H5. The structured fix a rule OPTED IN to, absent on every rule that did not —
 * which is what stops the field from ever being a lie. `fixHint` is prose on all
 * 36 rules; `fix` exists only where an edit was actually computed.
 *
 * `safety` is typed `string` like every other enum-ish field here (invariant
 * 1.1/6): an unknown value renders as the cautious form, never as `mechanical`.
 */
export interface IssueFix {
  title: string;
  safety: string;
  edits: FixEdit[];
}

/** The two safety words the renderer draws specially. Anything else is cautious. */
export const KNOWN_FIX_SAFETY = ['mechanical', 'needs-review'] as const;

/** True only for the word that means "one unambiguous slot, nothing to judge". */
export function isMechanicalFix(fix: IssueFix | undefined): boolean {
  return !!fix && fix.safety === 'mechanical';
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
  /**
   * CI-ADOPT. How this finding relates to the diff the run was attributed
   * against: `new` (inside an added hunk), `touched` (changed file, outside the
   * hunks) or `existing`. ABSENT means the run was not attributed at all — the
   * documented degradation when git is missing, the workspace is not a repo or
   * the base ref does not exist — and the viewer then shows every finding with
   * no chip, never an empty list.
   *
   * Typed `string`, like every other enum-ish field here: invariant 1.1/6 says
   * an unknown value renders generically instead of throwing.
   */
  change?: string;
  /**
   * CI-ADOPT. True when a baseline file already carried this finding. Baselined
   * is MARKED, never deleted: the row moves into the rail's collapsed
   * "N suppressed" section with a `baselined` chip, so the ratchet stays
   * auditable.
   */
  baselined?: boolean;
  /**
   * H5. Present only where the rule opted in AND the analyzer was at least
   * `likely` about the finding. Absent everywhere else, including on every rule
   * that ships prose only.
   */
  fix?: IssueFix;
}

/**
 * The three attributions CI-ADOPT emits. `Issue.change` stays `string`; this is
 * the list the renderer draws a chip for, and anything else falls through
 * unchipped rather than throwing.
 */
export const KNOWN_ISSUE_CHANGES = ['new', 'touched', 'existing'] as const;

export type IssueChange = (typeof KNOWN_ISSUE_CHANGES)[number];

export function isKnownIssueChange(value: unknown): value is IssueChange {
  return typeof value === 'string' && (KNOWN_ISSUE_CHANGES as readonly string[]).indexOf(value) >= 0;
}

/** True when a finding is hidden from the main list but still auditable. */
export function isSetAside(issue: Issue): boolean {
  return !!issue.suppressed || !!issue.baselined;
}

/**
 * A citation inside an answer sentence.
 *
 * The emitter writes `{file, line}` and nothing else — an answer cites a place
 * to look, not a range to select — so this is a `Loc` with everything but those
 * two optional. `app.ts` completes it against `workspace.root` before posting
 * `openLocation`, which is what keeps the deep link working from a citation.
 */
export interface AnswerLoc {
  file: string;
  line: number;
  absFile?: string;
  col?: number;
  endLine?: number;
  endCol?: number;
}

/**
 * MLV-P1. One of the four answers, composed deterministically from the graph by
 * `analyzer/src/mlview/emit/answers.py` — no model, so it is identical in all
 * three hosts and stays offline.
 */
export interface Answer {
  sentence: string;
  nodeIds?: string[];
  locs?: AnswerLoc[];
  confidence?: number;
}

/**
 * MLV-P1. The optional `answers` block: the product's four headline questions,
 * answered in words. Every field is optional — an absent one is an answer the
 * emitter could not compose, and the card simply does not draw that row.
 */
export interface Answers {
  dataEntry?: Answer;
  objective?: Answer;
  evaluation?: Answer;
  verdict?: Answer;
}

/** The four answers in the order the card lists them, with their questions. */
export const ANSWER_ROWS: { key: keyof Answers; question: string }[] = [
  { key: 'dataEntry', question: 'Where does the data come in?' },
  { key: 'objective', question: 'What is being optimised?' },
  { key: 'evaluation', question: 'How is it evaluated?' },
  { key: 'verdict', question: 'What should I look at first?' },
];

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
  /**
   * NB. One per notebook whose `execution_count` is not monotonic: the file was
   * last run out of order, so the analyzer read the cells top to bottom and
   * de-rated every order-sensitive rule. `codes` names the rules it de-rated.
   */
  'notebook_out_of_order',
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
  /**
   * MLV-P1. Optional four-sentence summary of the pipeline. Absent means the
   * emitter wrote none — the card is not drawn at all rather than drawn empty.
   */
  answers?: Answers;
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
  /**
   * CI-ADOPT. Optional, absent at its default (off) exactly as `flow` and
   * `scope` are on `ViewState`: an older host round-trips a state it has never
   * seen. On it drops findings explicitly attributed `existing`, and NEVER an
   * unattributed one — a run that could not be attributed degrades to showing
   * everything, it does not degrade to an empty list.
   */
  changedOnly?: boolean;
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
  /**
   * Optional: whether the Pipeline Answer Card is expanded (MLV-P1). Absent =
   * open, so a document that carries `answers` answers its four questions on
   * the first screen without anyone opening anything.
   */
  answersOpen?: boolean;
  /**
   * VIEW-08. Optional, absent at its default (off) exactly as `flow`, `scope`
   * and `legendOpen` are: an older host round-trips a state it has never seen.
   * On, the diagram is projected down to the diff's changed set plus one hop.
   * Restoring it with no overlay loaded is a NO-OP, never an empty diagram.
   */
  diffOnly?: boolean;
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
  | { v: 1; type: 'setScope'; spec: string | null; depth?: number }
  /**
   * VIEW-07. The host asks for a picture — its two commands (`mlview.exportSvg`
   * / `mlview.exportPng`) have no geometry of their own, because the lane bands,
   * the card rectangles and the routed paths exist only here. The viewer answers
   * with exactly one `exportFile`, or with a toast when it has nothing drawn.
   * `scope` is the host's vocabulary: `all` is this renderer's `diagram`.
   */
  | { v: 1; type: 'requestExport'; kind: 'svg' | 'png'; scope?: 'view' | 'all' | 'scope' }
  /**
   * VIEW-08. The diff overlay `mlview diff` writes, handed over as an OPTIONAL
   * SIBLING of the graph (CONTRACTS 11.38 B): it is a separate document with its
   * own `kind` and `diffVersion`, it never changes a byte of the graph, and a
   * host that never sends one leaves the viewer exactly as it was.
   *
   * `overlay: null` clears it. The payload is typed `unknown` on purpose — it
   * arrives from a host, is validated by `diff/overlay.ts` before anything is
   * drawn, and a malformed one degrades to "no overlay" rather than throwing.
   *
   * `baseLabel` is the host's name for what the comparison is AGAINST — a git
   * ref, a saved run, a file it picked. The overlay itself only knows the two
   * workspace roots, which are the same string when both sides came from one
   * checkout, so without this the banner would read "base X → head X". Optional
   * everywhere: absent, the banner falls back to the root's last segment.
   */
  | { v: 1; type: 'diffOverlay'; overlay: unknown; baseLabel?: string };

export type UiToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'openLocation'; file: string; absFile: string; line: number; col: number; endLine: number; endCol: number; preview?: boolean }
  | { v: 1; type: 'selectNode'; nodeId: string | null }
  | { v: 1; type: 'requestRefresh'; scope: 'workspace' | 'file'; path?: string }
  | { v: 1; type: 'exportHtml' }
  /**
   * VIEW-07. The viewer rendered the diagram to bytes and asks its host to put
   * them somewhere. It is a REQUEST, never a write: the VS Code extension owns
   * the save dialog, and the standalone bridge answers it with a download from
   * an object URL, falling back to the copy toast when a sandbox forbids one.
   *
   * `base64` carries the file itself — UTF-8 SVG markup or PNG bytes — because
   * `postMessage` between a webview and its host is a structured-clone channel
   * that a `Blob` does not reliably survive, and base64 makes the frame one
   * plain string whichever host reads it. `name` is a suggested filename only;
   * the host may rename it, and must sanitise it before touching a filesystem.
   *
   * A host predating this drops the message, which leaves the viewer exactly as
   * it was — the menu still copies to the clipboard and still prints.
   */
  /**
   * INTEROP NOTE. Two spellings of the same three facts are written, always
   * both, because the viewer half of VIEW-07 and the host half were specified
   * with different field names in the same sprint: this brief said
   * `{kind, name, base64}` and the host-side amendment (11.33) validates
   * `{kind, data, suggestedName?, scope?}` and rejects a frame without `data`.
   * A message carrying both is accepted by either validator and decoded
   * identically by both, so neither half has to ship broken while the two
   * amendments are reconciled. `name === suggestedName` and
   * `base64 === data` ALWAYS; whichever pair survives, no consumer changes.
   *
   * `scope` is the region in the HOST's vocabulary (`all`, not `diagram`).
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
    }
  | { v: 1; type: 'copy'; text: string }
  | { v: 1; type: 'saveState'; state: ViewState }
  | { v: 1; type: 'action'; id: string }
  | { v: 1; type: 'askAssistant'; nodeId: string; prompt: string }
  | { v: 1; type: 'log'; level: 'debug' | 'info' | 'warn' | 'error'; message: string }
  /**
   * MLV-P10. "Disable this rule": the viewer asks its host to turn one rule off
   * for the whole workspace. It is a REQUEST, never an edit — the host decides
   * (VS Code writes `.mlview.toml` behind an explicit confirm; the standalone
   * report cannot write anything and answers with a copy-toast carrying the
   * snippet). A host predating this drops the message silently, which leaves the
   * viewer exactly as it was.
   *
   * Two fields say the same thing to two readers, and both are always sent.
   * `scope` is what the viewer means: workspace-wide, never one file. `action`
   * is the discriminator `vscode-extension/src/protocol.ts` validates against —
   * its `isUiToHost` REJECTS a `suppressRule` without one — and the viewer only
   * ever sends `disable`: "copy the comment" goes through the generic `copy`
   * message that already owns the clipboard path, and `insert` belongs to the
   * editor's own lightbulb, which has a cursor to insert at.
   */
  | {
      v: 1;
      type: 'suppressRule';
      code: string;
      scope: 'workspace';
      action?: 'copy' | 'insert' | 'disable';
    }
  /**
   * Posted on EVERY scope change including a clear (then `spec: null`,
   * `label: "Everything"`, `nodes === of`). The field is named `spec`, not
   * `scope`: `analysisStarted` and `requestRefresh` already carry a field
   * literally named `scope` with a different meaning (CONTRACTS 11.7).
   */
  | { v: 1; type: 'scopeChanged'; spec: string | null; label: string; nodes: number; of: number }
  /**
   * H5. "Apply this fix": the viewer asks its host to make the edit `Issue.fix`
   * describes. It is a REQUEST, never an edit, and never an auto-apply — the
   * host resolves the issue id against its own copy of the document, applies the
   * edits behind a PREVIEW the user confirms, and owns every path check on the
   * way. The viewer sends an id and nothing else on purpose: a webview must not
   * be able to talk its host into writing bytes it chose.
   *
   * The standalone report has no host to ask, so it never sends this — it copies
   * the snippet through the `copy` message that already owns the clipboard path.
   * A host predating this drops the frame, which leaves the viewer as it was.
   */
  | { v: 1; type: 'applyFix'; issueId: string };

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
