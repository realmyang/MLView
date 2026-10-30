/**
 * MLView renderer — the authored WorkflowDocument, the renderer's internal view
 * model (`MLGraph`, built by `workflow.ts`), and the host protocol.
 *
 * Enum-ish fields are typed as `string` on purpose: a node or edge kind the
 * renderer does not know draws a neutral visual (a plain step, an `unknown`
 * connection) instead of throwing, so the renderer must never narrow them.
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
  /** What the card's second line draws: the authored detail ('' when there is none). */
  sublabel?: string;
  /** The authored label again (search and the outline read it). */
  qualname: string;
  loc: Loc;
  parent: string | null;
  issueIds: string[];
  /** The authored basis: observed, inferred or unresolved. */
  basis?: WorkflowBasis;
  /** The authored evidence as locations, in document order (`evidenceLoc` in workflow.ts). */
  evidenceLocs?: Loc[];
  /**
   * The authored `detail`, verbatim, or absent when the author wrote
   * none. The Selection pane shows it whole and the card's accessible name its first sentence;
   * the card draws `sublabel`, cut by the CSS, so the layout does not depend on its length.
   */
  detail?: string;
  /** The authored label of the node's phase (`stage` is its id). */
  phaseLabel?: string;
}

export interface MLEdge {
  id: string;
  kind: string;
  /** Read by the layout core (`subkind === 'back'`); authored edges never set it. */
  subkind?: string;
  source: string;
  target: string;
  /** The authored label, verbatim (no basis suffix). */
  label?: string;
  loc: Loc;
  issueIds: string[];
  /** The authored basis: observed, inferred or unresolved. */
  basis?: WorkflowBasis;
  /** The authored evidence as locations, in document order (`evidenceLoc` in workflow.ts). */
  evidenceLocs?: Loc[];
  /**
   * The kind word the author wrote, when `kind` is the styled
   * kind it was normalised to (`dataflow` drawn as `data`).
   * Absent when the two are the same or the author gave no kind.
   */
  authoredKind?: string;
}

/** An authored finding, as the renderer reads it. */
export interface Issue {
  id: string;
  /** The finding id again (search and the Findings list print it). */
  code: string;
  /**
   * The short label `F1`…`Fn`, numbered in document order. Badges show it; it can
   * renumber between revisions, so tooltips, the Selection pane and Refine keep the real `id`.
   */
  short: string;
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
  /** The authored basis: observed, inferred or unresolved. */
  basis?: WorkflowBasis;
}

/** A document-level note: `workflow_limitation`, one per authored coverage limitation. */
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
  filesInspected: number;
}

export interface Generator {
  name: string;
  version: string;
  rendererSha: string;
  generatedAt: string;
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
   * Set by the WorkflowDocument adapter (workflow.ts): the authored
   * coverage status and how many limitations the author listed, so the
   * zero-findings state can name them instead of claiming a check.
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

/**
 * The severity toggles and the search query. A saved `stages` list, or any other
 * key, is dropped when the filters are restored (`sanitizeFilters` in protocol.ts).
 */
export interface Filters {
  severities: Severity[];
  query: string;
}

/**
 * The rail's tabs, in strip order: About · Findings · Selection · Outline. The Selection tab's
 * id is `inspector`, in a saved state and in the panel ids.
 */
export type RailTab = 'about' | 'issues' | 'inspector' | 'outline';

export interface ViewState {
  viewport: Viewport;
  selection: Sel | null;
  collapsed: string[];
  filters: Filters;
  /**
   * The reader's tab, for `workflowRevision`: a remount of the same revision restores
   * it, and a new revision opens on About.
   */
  railTab: RailTab;
  /**
   * The phase index folded to its pill, or hidden (the ... menu). Absent at its default
   * (shown, unfolded).
   */
  phaseIndex?: 'folded' | 'hidden';
  /**
   * Read, never written: a saved `true` with no `phaseIndex` opens the phase index folded
   * (`applyState` in app/state.ts).
   */
  minimapCollapsed?: boolean;
  /** Optional: flow animation on/off. Absent = on. */
  flow?: boolean;
  /** Optional: the legend panel's open state, remembered per viewer. */
  legendOpen?: boolean;
  /**
   * The authored revision id the viewport belongs to, written once a revision
   * is shown and absent before. A remounted viewer restores `viewport` instead
   * of fitting only when this equals the revision it is handed.
   */
  workflowRevision?: string;
  /**
   * The Refine composer of that authored revision: open, intent and custom
   * text. Absent at its default (closed, Explain, no text), and
   * restored on a remount only when `workflowRevision` matches.
   */
  composer?: ComposerState;
  /**
   * The rail was the bottom sheet and it was open. Absent at its default
   * (collapsed, or docked), and restored on a remount only when `workflowRevision` matches, like
   * `railTab` and `selection`.
   */
  sheetOpen?: boolean;
  /**
   * The review walk's place for `workflowRevision`: its filter, the claim it is on, the
   * quote of that claim, and whether it was running. Absent until the walk has been started, and
   * restored on a remount only when `workflowRevision` matches; another revision starts fresh. It
   * records no verdict and no "checked" mark, only the position.
   */
  walk?: WalkViewState;
  /**
   * The zoom of `viewport`, when the viewer chose it itself (a finding's frame, a walk
   * step) and nothing has changed it since. Absent when the reader chose the zoom, and restored on
   * a remount only with `viewport`, so only when `workflowRevision` matches. With it, a walk
   * resumed in a panel that was hidden and shown again still returns to reading size on its next
   * step (`CanvasView.walkTarget`).
   */
  framedZoom?: number;
}

/** The review walk's saved place (`ViewState.walk`). */
export interface WalkViewState {
  /** `revision`: Changed in this revision; `changed`: Changed files. */
  filter: 'notObserved' | 'findings' | 'revision' | 'changed' | 'all';
  claim: Sel;
  /** The claim's quote (0-based) the walk last showed; absent at 0. */
  quote?: number;
  /** The walk was running; absent when it was not. */
  active?: boolean;
}

/** A Refine composer's reader-visible state. */
export interface ComposerState {
  open: boolean;
  intent: RefineIntent;
  custom: string;
}

/* ── host protocol ─────────────────────────────────────────────────────── */

/**
 * The host's `init` capabilities. The viewer reads `canOpenSource` only. The host also sends
 * `canRefine` as true and three flags as false (`canReanalyze`, `canExport`, `canAskAssistant`);
 * the viewer reads none of them, so they change nothing here.
 */
export interface Capabilities {
  canOpenSource: boolean;
  canRefine?: boolean;
}

/** The five refinement intents the composer offers. */
export type RefineIntent = 'explain' | 'expand' | 'challenge' | 'trace' | 'custom';

/** The requests that carry a `requestId` and are answered by one `actionResult`. */
export type ResultAction = 'exportFile' | 'copy' | 'refineWorkflow' | 'openLocation';

/**
 * Why the host did not open a cited range: a stale reason, `elsewhere` (the root
 * hint), unsaved text that lost the cited lines, a removed notebook cell, a file that could not be
 * checked, or evidence the displayed revision does not have.
 */
export type OpenBlockReason = 'changed' | 'missing' | 'unreadable' | 'too-large' | 'elsewhere' | 'unsaved' | 'cell-missing' | 'unchecked' | 'unknown';

/**
 * The host's single answer to an `exportFile`, `copy`, `refineWorkflow` or
 * `openLocation` request that carried a valid `requestId`. `message` is host-authored
 * and never contains an absolute path; `name` is the saved basename and is sent
 * only for a completed export.
 *
 * For `openLocation`: `done` (shown beside the panel), `blocked` (not opened; `reason` and a short
 * `message` such as "train.py changed after revision r3 was published; not opened."), `cancelled`
 * (a later open, a new revision or a freshness change overtook it) or `failed` (VS Code could not
 * show the file). `seq` repeats the request's own `seq` when it had one.
 */
export interface ActionResult {
  v: 1;
  type: 'actionResult';
  requestId: string;
  action: ResultAction;
  outcome: 'done' | 'cancelled' | 'failed' | 'blocked';
  message?: string;
  name?: string;
  reason?: OpenBlockReason;
  seq?: number;
}

/**
 * Why a cited or inspected file no longer matches the published revision (the host's hash check).
 * `elsewhere`: missing under the workspace root but present, unchanged, in another folder; the
 * host's `root-hint` notice names the folder and offers to add it.
 */
export type StaleReason = 'changed' | 'missing' | 'unreadable' | 'too-large' | 'elsewhere';

/** One stale file, workspace-relative, as the host's `stale` frame carries it. */
export interface StaleFile {
  path: string;
  reason: StaleReason;
}

export type HostToUi =
  | { v: 1; type: 'init'; theme: ThemeKind; capabilities: Capabilities; artifact?: string }
  | { v: 1; type: 'theme'; kind: ThemeKind }
  /**
   * MLView: Reveal in Diagram: the reader chose this claim from the code in the
   * editor, and the host moved the keyboard focus to this panel. The viewer selects it, brings it
   * into view (above the bottom sheet, clear of the phase index), shows it in the Selection tab and
   * puts the keyboard on it. `issue` is a finding. A frame with another kind changes nothing; an id
   * the displayed revision lacks changes nothing, and the viewer says so.
   */
  | { v: 1; type: 'reveal'; kind: 'node' | 'edge' | 'issue'; id: string }
  /** The host sends `reveal`; a single-kind frame like this one is answered the same way. */
  | { v: 1; type: 'revealNode'; nodeId: string; center?: boolean }
  /** The host sends `reveal`; a single-kind frame like this one is answered the same way. */
  | { v: 1; type: 'revealIssue'; issueId: string }
  /**
   * The displayed revision's stale files, each with its reason, posted after the
   * `workflow` frame whenever the set changes (an empty list clears the marks).
   */
  | { v: 1; type: 'stale'; files: StaleFile[] }
  /**
   * Applies a saved `ViewState`. The host does not send it; the tests set collapse or the viewport
   * with it.
   */
  | { v: 1; type: 'restoreState'; state: ViewState }
  /**
   * A new or refreshed authored revision. Two fields are optional and never persisted:
   * `previous` is the valid revision this panel showed just before, sent only when `document`
   * names it as its `revision.parent` (the viewer lists the changes since it); `replaced` is the
   * id of the revision this panel showed before when `document` does not follow it (About says no
   * changes are listed). A new panel (a window reload, an extension restart) has neither.
   */
  | { v: 1; type: 'workflow'; document: WorkflowDocument; previous?: WorkflowDocument; replaced?: string }
  /**
   * The host's status banner. Before the mount the host bootstrap draws it; after it the App
   * draws it as a notice, and reads `codes` to clear a refinement refusal about the artifact
   * file once the file is readable again. `''` clears the banner.
   */
  | { v: 1; type: 'workflowError'; message: string; retained?: boolean; codes?: string[] }
  | ActionResult;

export type UiToHost =
  | { v: 1; type: 'ready' }
  /**
   * `focus: true` is the explicit open-and-focus gesture (Alt+Enter, Alt+click); every
   * other open keeps the keyboard on the diagram.
   *
   * For the review walk (it asks for an open `WALK_OPEN_DEBOUNCE_MS` after the reader stops moving):
   * `seq` is a positive integer that increases with every numbered open of a page (the host drops
   * an open whose `seq` is not above the last one it saw, and one a later open overtook);
   * `requestId` asks for one `actionResult`; `walk: true` marks an open from the walk, which never
   * raises a VS Code notification when it is blocked (the reason comes back in the result
   * instead); `highlight: false` selects the range without the whole-range decoration.
   */
  | { v: 1; type: 'openLocation'; file: string; absFile: string; line: number; col: number; endLine: number; endCol: number; preview?: boolean; evidenceId?: string; cell?: number; focus?: boolean; seq?: number; requestId?: string; walk?: boolean; highlight?: boolean }
  /**
   * The review walk ended (`end`), or it moved to a claim it opens nothing for (`clear`:
   * a claim with no quote, or one it only selected). Either way the host clears the cited-range
   * highlight, collapses the selection the walk set if the editor still has it, and drops a walk
   * open still on its way, so the editor never shows an earlier claim's lines as if they were this
   * one's.
   */
  | { v: 1; type: 'walk'; state: 'end' | 'clear' }
  /** The workspace-root hint's two actions. The host owns the folder. */
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
   * The viewer rendered the diagram to bytes and asks the host to save
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
      scope: 'all';
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

export interface MLViewApp {
  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean }): void;
  focusIssue(id: string): void;
  setFilters(f: Partial<Filters>): void;
  setTheme(kind: ThemeKind): void;
  getState(): ViewState;
  destroy(): void;
}

export interface WorkflowViewApp extends MLViewApp {
  /**
   * `comparison`: the frame's `previous` or `replaced` (see the `workflow` frame); the
   * viewer checks it again (`sanitizeComparison`).
   */
  setWorkflow(document: WorkflowDocument, preserve?: Partial<ViewState>, comparison?: { previous?: WorkflowDocument; replaced?: string }): void;
}
