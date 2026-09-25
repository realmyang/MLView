/**
 * The MLView application: view state, chrome, side rail, search, the keyboard
 * model and the host protocol.
 *
 * Everything inside the diagram surface — layout, the scene DOM, the viewport,
 * hover and focus — lives in CanvasView; this class drives it. Layout depends
 * only on (graph, collapsed), so filters, selection and hover never relayout.
 *
 * WHAT IS WHERE. The App is the state and the lifecycle; the work it drives is
 * in `app/`, as free functions over this object:
 *
 *   `app/build.ts`      the shell, every panel, and what the canvas may ask
 *   `app/documents.ts`  the document, the scope, the diff and the chooser
 *   `app/surfaces.ts`   repaint the chrome, the diff band and the rail
 *   `app/actions.ts`    the one-shot requests posted to the host
 *   `app/exporting.ts`  VIEW-07's picture, gathered at the moment it is asked for
 *   `app/keys.ts`       the keyboard binding
 *   `app/messages.ts`   the host protocol, inbound
 *   `app/state.ts`      `ViewState`, both directions
 *
 * Those modules are this class's own halves, not an API: every field and method
 * below is public only because they reach it, and nothing outside `app/` may
 * depend on anything that `MLViewApp` (types.ts) does not name.
 */

import { clear, debounce } from './dom.js';
import { GraphIndex } from './layout/model.js';
import { CanvasView } from './canvasview.js';
import { FilterModel } from './filters.js';
import { Chrome } from './ui/chrome.js';
import { Rail } from './ui/rail.js';
import { Legend } from './ui/legend.js';
import { AnswersCard } from './ui/answers.js';
import { sanitizeGroupBy } from './ui/railgroup.js';
import { LoadingState } from './ui/states.js';
import { ShortcutSheet } from './ui/shortcuts.js';
import { ExportMenu } from './ui/exportmenu.js';
import { ThemeController } from './ui/theme.js';
import { SearchController } from './ui/searchcontroller.js';
import { ScopeSession } from './scope/session.js';
import { ScopeBar } from './ui/scopebar.js';
import { PipelineChooser } from './ui/pipelinechooser.js';
import { DiffBar } from './ui/diffbar.js';
import { decorateWorkflow, normalizeWorkflow, sanitizeComposer } from './workflow.js';
import { buildAppUi } from './app/build.js';
import { scopeToNode, setGraph, setScope } from './app/documents.js';
import { renderChrome, renderRail } from './app/surfaces.js';
import { applyFix, askAssistant, copyIgnore, disableRule, onAction, openLocation } from './app/actions.js';
import { onCanvasKey } from './app/keys.js';
import { onHostMessage } from './app/messages.js';
import { applyState, safeLoad, snapshotState } from './app/state.js';
import type { SearchHit } from './search.js';
import type {
  ActionResult,
  Capabilities,
  ComposerState,
  ScopeSummary,
  Filters,
  HostBridge,
  HostToUi,
  Loc,
  MLGraph,
  MLViewApp,
  RailGroupBy,
  RailTab,
  RelatedLoc,
  Sel,
  ThemeKind,
  UiToHost,
  ViewState,
  Viewport,
  WorkflowDocument,
} from './types.js';

/** At most this many requests wait for an `actionResult`; the oldest is dropped. */
const MAX_PENDING_REQUESTS = 32;

type RequestFrame = UiToHost & { requestId?: string };

export interface SelectOptions {
  open?: boolean;
  center?: boolean;
  tab?: RailTab;
  pulse?: boolean;
}

export class App implements MLViewApp {
  root: HTMLElement;
  bridge: HostBridge;
  graph: MLGraph | null = null;
  index: GraphIndex | null = null;
  /** The whole-workspace document. `graph` is its projection while scoped. */
  scopes = new ScopeSession();
  fullIndex: GraphIndex | null = null;
  /** Restored by the breadcrumb's [x], so clearing feels like a back button. */
  preScope: { viewport: Viewport; selection: Sel | null } | null = null;
  /** The node `e` / Shift+E are cycling the connections of. */
  edgeAnchor: string | null = null;
  /**
   * A restored or attribute-borne scope that arrived BEFORE any graph did.
   *
   * In the VS Code host the viewer is mounted with no graph at all
   * (`panel.ts`: "Mount immediately with no graph") and the host posts
   * `init` -> `restoreState` -> `graph`, so both restore routes ran while
   * `scopes.full` was still null and `ViewState.scope` — alone among every
   * field of the state — was silently thrown away (R2H-03). It is stashed here
   * and drained by `setGraph`, through the same `setScope` call, so the
   * re-resolve and the `scopeChanged` post still happen exactly once.
   */
  pendingScope: { spec: string; depth?: number } | null = null;
  flowOn = true;
  /**
   * VIEW-08. The host's document, EXACTLY as it arrived. `adoptDiff` stamps the
   * overlay onto a copy and resurrects the removed nodes as ghosts, so the
   * original has to survive somewhere: an overlay can arrive after the graph,
   * be replaced, or be dismissed, and each of those has to be re-derivable
   * without asking the analyzer for anything.
   */
  rawGraph: MLGraph | null = null;
  /** VIEW-08: the HOST's name for what the comparison is against (11.43 D). */
  diffBaseLabel = '';
  caps: Capabilities;
  /**
   * VW-05. `ThemeController` is the ONE place a theme is decided: the standalone
   * report's own Auto / Light / Dark / High contrast switch calls it directly,
   * so a copy of the value on the app went stale the moment a reader touched
   * that switch — and the export stamped the stale one on every picture. There
   * is no copy any more; `this.themes.kind` is the answer, always.
   */

  filters = new FilterModel();
  viewportState: Viewport = { x: 0, y: 0, zoom: 1 };
  selection: Sel | null = null;
  collapsedState: string[] = [];
  railTab: RailTab = 'issues';
  railGroupBy: RailGroupBy = 'none';
  legendOpen = false;
  /** MLV-P12: the pipeline chooser is asked once per viewer, then remembered. */
  pipelineChosen = false;
  /**
   * MLV-P1: the answer card starts open, so the four answers are the first
   * read — except on a document whose chrome already fills the top of the
   * window (HOSTS-UX-R2-06), where it yields its 165 px to the diagram.
   */
  answersOpen = true;
  /**
   * R2-06. The reader has pressed the disclosure (or the host restored a
   * stored `answersOpen`), so the per-document default no longer applies: their
   * choice follows them to the next report, which is what `ViewState` is for.
   */
  answersChosen = false;
  /** The document the default was last decided for; identity, not a copy. */
  answersDoc: MLGraph | null = null;
  /** Whether THIS document's default is "closed", for the header's tooltip. */
  answersYielded = false;

  stale: string[] = [];
  dismissed = new Set<string>();
  error: { message: string; detail?: string; actions?: { id: string; label: string }[] } | null = null;
  railOpen = true;
  railWidth = 360;
  /** The authored document last applied, as the very object that arrived. */
  workflowDocument: WorkflowDocument | null = null;
  /** Its revision id, which decides whether a new frame may keep the viewport. */
  workflowRevision: string | null = null;
  /**
   * A restored viewport and the revision it was saved for (VIEWUI-3). Used by
   * the first `setWorkflow` only, and only when the revisions match.
   */
  private restoredView: { revision: string; viewport: Viewport } | null = null;
  /** The composer a remount restores, under the same rule as `restoredView` (VIEWUI-4). */
  private restoredComposer: { revision: string; composer: ComposerState } | null = null;
  /**
   * Requests waiting for the host's `actionResult`, oldest first (§1e). No
   * timeout: a save dialog may stay open for as long as the user likes.
   */
  private pending = new Map<string, (result: ActionResult) => void>();
  private requestSerial = 0;
  private disposers: (() => void)[] = [];
  private destroyed = false;

  view!: CanvasView;
  chrome!: Chrome;
  rail!: Rail;
  sheet!: ShortcutSheet;
  exportMenu!: ExportMenu;
  legend!: Legend;
  answers!: AnswersCard;
  scopeBar!: ScopeBar;
  diffBar!: DiffBar;
  chooser!: PipelineChooser;
  scrim!: HTMLElement;
  releasePage: () => void = () => undefined;
  themes!: ThemeController;
  search!: SearchController;
  loading!: LoadingState;
  liveEl!: HTMLElement;

  saveSoon = debounce(() => this.bridge.saveState(this.getState()), 250);

  constructor(root: HTMLElement, bridge: HostBridge) {
    this.root = root;
    this.bridge = bridge;
    this.caps = bridge.capabilities;
    this.themes = new ThemeController(root, bridge.theme || 'light', bridge.themePreference);
    buildAppUi(this);
    const restored = safeLoad(bridge);
    if (restored) applyState(this, restored, false);
    if (restored && typeof restored.workflowRevision === 'string' && restored.viewport) {
      this.restoredView = { revision: restored.workflowRevision, viewport: { ...restored.viewport } };
    }
    const composer = restored && typeof restored.workflowRevision === 'string' ? sanitizeComposer(restored.composer) : null;
    if (restored && composer) this.restoredComposer = { revision: restored.workflowRevision as string, composer };
    this.disposers.push(bridge.onMessage((msg) => this.onMessage(msg)));
    // The initial scope travels as an attribute on the root element the report
    // already emits, so `mount(root, graph, bridge)` keeps its exact frozen
    // three-argument signature (CONTRACTS 11.8). It outranks a restored scope,
    // so it is stashed LAST — either way `setGraph` drains exactly one.
    const attrSpec = root.getAttribute('data-mlview-scope');
    const attrDepth = root.getAttribute('data-mlview-depth');
    if (attrSpec) this.pendingScope = { spec: attrSpec, depth: attrDepth ? Number(attrDepth) : undefined };
    this.showLoading(true);
    // No `ready` here: the host bootstrap posts the one `ready` of a page load
    // and mounts this App on the first `workflow` (§1e). A second `ready`
    // would make the host replay the whole handshake and render it again.
  }

  /* ── chrome + rail ─────────────────────────────────────────────────── */

  laneIds(): string[] {
    return this.index ? this.index.lanes.map((l) => l.id) : [];
  }

  /**
   * Replace the current model-authored revision without remounting the UI.
   *
   * The same revision id keeps the reader's viewport (a refresh or a re-post
   * is not a new picture); a new revision id fits, unless the caller passes a
   * viewport. On the first document of a remounted viewer, a viewport saved
   * for this same revision is restored instead of fitting (VIEWUI-3).
   */
  setWorkflow(document: WorkflowDocument, preserve?: Partial<ViewState>): void {
    let next = preserve;
    if (!preserve || !preserve.viewport) {
      let viewport: Viewport | null = null;
      if (this.graph && this.workflowRevision === document.revision.id) viewport = { ...this.viewportState };
      else if (!this.graph && this.restoredView && this.restoredView.revision === document.revision.id) {
        viewport = { ...this.restoredView.viewport };
      }
      if (viewport) next = { ...(preserve || {}), viewport };
    }
    this.restoredView = null;
    const composer = this.restoredComposer && this.restoredComposer.revision === document.revision.id ? this.restoredComposer.composer : null;
    this.restoredComposer = null;
    this.workflowDocument = document;
    this.workflowRevision = document.revision.id;
    setGraph(this, normalizeWorkflow(document), next, true);
    decorateWorkflow(this, document, composer);
  }

  /**
   * Post a request that the host answers with one `actionResult` (§1e). The
   * id is a counter plus four random base36 characters; at most
   * `MAX_PENDING_REQUESTS` wait, and the oldest is forgotten first.
   */
  postRequest(message: RequestFrame, onResult: (result: ActionResult) => void): string {
    this.requestSerial += 1;
    let tail = '';
    for (let i = 0; i < 4; i++) tail += Math.floor(Math.random() * 36).toString(36);
    const requestId = 'r' + this.requestSerial.toString(36) + '-' + tail;
    this.pending.set(requestId, onResult);
    while (this.pending.size > MAX_PENDING_REQUESTS) {
      const oldest = this.pending.keys().next().value;
      if (oldest === undefined) break;
      this.pending.delete(oldest);
    }
    this.bridge.post({ ...message, requestId } as UiToHost);
    return requestId;
  }

  /** The host's answer to a request. An unknown or forgotten id is ignored. */
  onActionResult(result: ActionResult): void {
    if (!result || typeof result.requestId !== 'string') return;
    const handler = this.pending.get(result.requestId);
    if (!handler) return;
    this.pending.delete(result.requestId);
    handler(result);
  }

  /** True only where the HOST can actually make an edit behind a preview. */
  canApplyFix(): boolean {
    return this.bridge.host === 'vscode' && this.caps.canOpenSource;
  }

  applyFix(issueId: string): void {
    applyFix(this, issueId);
  }

  copyIgnore(code: string): void {
    copyIgnore(this, code);
  }

  disableRule(code: string): void {
    disableRule(this, code);
  }

  askAssistant(nodeId: string): void {
    askAssistant(this, nodeId);
  }

  openLocation(loc: Loc | RelatedLoc): void {
    openLocation(this, loc);
  }

  onAction(id: string): void {
    onAction(this, id);
  }

  scopeToNode(nodeId: string): void {
    scopeToNode(this, nodeId);
  }

  /** VIEW-12: the toolbar's copy of the minimap chevron. */
  setMinimapCollapsed(next: boolean): void {
    this.view.setMinimapCollapsed(next);
    renderChrome(this);
    this.saveSoon();
    this.announce('Overview minimap ' + (next ? 'hidden' : 'shown') + '.');
  }

  /** MLV-P1: the card's disclosure, persisted as ViewState.answersOpen. */
  setAnswersOpen(open: boolean): void {
    this.answersOpen = open;
    // R2-06: an explicit press outranks this document's default from now on.
    this.answersChosen = true;
    this.answers.update(this.graph ? this.graph.answers : undefined, open, this.answersYielded);
    this.saveSoon();
  }

  /** The rail's "Group by" control (RAIL-GROUP). Persisted like `railTab`. */
  setRailGroupBy(mode: RailGroupBy): void {
    this.railGroupBy = sanitizeGroupBy(mode);
    renderRail(this);
    this.saveSoon();
    this.announce('Findings grouped by ' + this.railGroupBy + '.');
  }

  setLegend(next: boolean): void {
    this.legendOpen = next;
    this.legend.setOpen(next);
    renderChrome(this);
    this.saveSoon();
  }

  setRailTab(tab: RailTab): void {
    this.railTab = tab;
    renderRail(this);
    this.saveSoon();
  }

  toggleRail(): void {
    this.setRailOpen(!this.railOpen);
  }

  setRailOpen(open: boolean): void {
    this.railOpen = open;
    this.rail.root.hidden = !open;
    // The scrim only paints below the 900 px breakpoint (see chrome.css), but its
    // hidden state must track the drawer at every width.
    this.scrim.hidden = !open;
  }

  toggleShortcuts(next?: boolean): void {
    const show = typeof next === 'boolean' ? next : !this.sheet.open;
    if (show) {
      this.sheet.show();
      return;
    }
    this.sheet.hide();
    try {
      this.view.canvasEl.focus();
    } catch (_e) {
      /* the canvas may already be torn down */
    }
  }

  setRailWidth(width: number): void {
    this.railWidth = Math.max(280, Math.min(560, Math.round(width)));
    this.rail.root.style.width = this.railWidth + 'px';
  }

  setFlow(next: boolean): void {
    this.flowOn = next;
    this.view.flow.setEnabled(next);
    this.view.flow.syncCanvas();
    renderChrome(this);
    this.saveSoon();
  }

  /* ── selection ─────────────────────────────────────────────────────── */

  select(sel: Sel, opts?: SelectOptions): void {
    if (sel.kind !== 'edge') this.edgeAnchor = null;
    this.selection = sel;
    if (opts && opts.tab) this.railTab = opts.tab;
    this.view.applySelection(sel);
    renderRail(this);
    if (sel.kind === 'node') this.bridge.post({ v: 1, type: 'selectNode', nodeId: sel.id });
    if (opts && opts.center) this.view.centerOnNode(sel.id, !!opts.pulse);
    if (opts && opts.open) {
      const loc = this.locOf(sel);
      if (loc) this.openLocation(loc);
    }
    this.announceSelection();
    this.saveSoon();
  }

  clearSelection(): void {
    if (!this.selection) return;
    this.selection = null;
    this.view.applySelection(null);
    renderRail(this);
    this.bridge.post({ v: 1, type: 'selectNode', nodeId: null });
    this.saveSoon();
  }

  locOf(sel: Sel): Loc | null {
    if (!this.index) return null;
    if (sel.kind === 'node') {
      const node = this.index.nodeById.get(sel.id);
      return node && node.loc.file ? node.loc : null;
    }
    if (sel.kind === 'edge') {
      const edge = this.index.edgeById.get(sel.id);
      return edge && edge.loc.file ? edge.loc : null;
    }
    const issue = this.index.issueById.get(sel.id);
    return issue && issue.loc.file ? issue.loc : null;
  }

  /** The node a non-node selection points at — an issue's primary node. */
  selectedNodeId(): string | null {
    const sel = this.selection;
    if (!sel || !this.index) return null;
    if (sel.kind === 'node') return sel.id;
    if (sel.kind !== 'issue') return null;
    const issue = this.index.issueById.get(sel.id);
    return issue && issue.nodeIds.length ? issue.nodeIds[0] : null;
  }

  private announceSelection(): void {
    const sel = this.selection;
    if (!sel || !this.index) return;
    if (sel.kind === 'node') {
      const label = this.view.labelOf(sel.id);
      if (label) this.announce('Selected ' + label);
    } else if (sel.kind === 'issue') {
      const issue = this.index.issueById.get(sel.id);
      if (issue) this.announce('Finding ' + issue.code + ', ' + issue.severity + ' severity: ' + issue.title);
    }
  }

  /* ── commands ──────────────────────────────────────────────────────── */

  /** Mutate the filter model, then repaint everything that depends on it. */
  applyFilters(mutate: () => void): void {
    mutate();
    renderChrome(this);
    if (this.index) {
      this.view.render();
      this.view.applySelection(this.selection);
    }
    renderRail(this);
    this.saveSoon();
  }

  /**
   * A stage chip (HOSTS-UX-STAGERESET).
   *
   * The chips dim rather than hide, and with six of seven off the demo shows 45
   * of 53 cards dimmed, 0 issues in the rail and its "No issues match these
   * filters" empty state — all correct. Pressing the SEVENTH used to turn every
   * filter back on with nothing said: the gesture was "hide this one too" and
   * what happened was "show everything again". The model still resets (an empty
   * selection is the only resting state it has), and now the viewer says so.
   */
  toggleStage(stageId: string): void {
    let reset = false;
    this.applyFilters(() => {
      reset = this.filters.toggleStage(stageId, this.laneIds());
    });
    if (!reset) return;
    this.view.toast('All stages hidden — showing everything again');
    this.announce('All stages were hidden, so every stage is shown again.');
  }

  clearFilters(): void {
    this.search.clear();
    this.applyFilters(() => this.filters.reset());
  }

  /** The Outline's lane rows are a jump target: land on the stage's first node. */
  selectLane(laneId: string): void {
    if (!this.index) return;
    const roots = this.index.roots(laneId);
    if (!roots.length) {
      this.announce('That stage has no nodes.');
      return;
    }
    this.select({ kind: 'node', id: roots[0] }, { center: true, pulse: true });
  }

  zoomToSelection(): void {
    const id = this.selectedNodeId();
    if (id) this.view.zoomToNode(id);
  }

  announce(text: string): void {
    this.liveEl.textContent = text;
  }

  showLoading(on: boolean): void {
    this.loading.root.hidden = !on;
  }

  activateHit(hit: SearchHit): void {
    if (hit.kind === 'node') this.focusNode(hit.id, { center: true, pulse: true });
    else this.focusIssue(hit.id);
  }

  onKeyDown(ev: KeyboardEvent): void {
    onCanvasKey(this, ev);
  }

  private onMessage(msg: HostToUi): void {
    onHostMessage(this, msg);
  }

  /* ── public API ────────────────────────────────────────────────────── */

  /**
   * Re-project and relayout LOCALLY. Never posts `requestRefresh`, never touches
   * the analyzer, and never throws: an unresolvable spec is a no-op plus a toast
   * (CONTRACTS 11.8).
   */
  setScope(spec: string | null, opts?: { depth?: number }): void {
    setScope(this, spec, opts);
  }

  getScope(): ScopeSummary {
    return this.scopes.summary();
  }

  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean }): void {
    if (!this.index) return;
    if (!this.index.nodeById.has(id)) {
      // An EXPLICIT navigation beats a scope set two minutes ago: clear it and
      // land on the node. Saying "not found" here would be a false statement
      // about a node the project certainly has (FEATURES 3.5).
      if (this.fullIndex && this.fullIndex.nodeById.has(id) && this.scopes.spec) {
        this.setScope(null);
        this.view.toast('Scope cleared to reveal this node');
        this.focusNode(id, opts);
        return;
      }
      this.view.toast('Node not found in this graph');
      return;
    }
    this.view.expandAncestors(id);
    this.select(
      { kind: 'node', id },
      { center: opts ? opts.center !== false : true, tab: 'inspector', pulse: opts ? !!opts.pulse : false },
    );
  }

  focusIssue(id: string): void {
    if (!this.index) return;
    const issue = this.index.issueById.get(id);
    if (!issue) return;
    const primary = issue.nodeIds[0];
    if (primary) this.view.expandAncestors(primary);
    this.railTab = 'issues';
    this.select({ kind: 'issue', id }, { tab: 'issues' });
    if (primary) this.view.centerOnNode(primary, true);
  }

  setFilters(f: Partial<Filters>): void {
    this.applyFilters(() => this.filters.patch(f));
  }

  setTheme(kind: ThemeKind): void {
    this.themes.apply(kind);
  }

  getState(): ViewState {
    return snapshotState(this);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.saveSoon.cancel();
    this.pending.clear();
    for (const dispose of this.disposers) {
      try {
        dispose();
      } catch (_e) {
        /* a host may already have torn the listener down */
      }
    }
    this.disposers = [];
    this.themes.destroy();
    this.chrome.destroy();
    this.exportMenu.destroy();
    this.view.destroy();
    this.releasePage();
    clear(this.root);
    this.root.classList.remove('mlv-root');
  }
}
