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
 *   `app/documents.ts`  the document and the scope
 *   `app/surfaces.ts`   repaint the chrome and the rail
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

import { clear, debounce, on } from './dom.js';
import { GraphIndex } from './layout/model.js';
import { CanvasView } from './canvasview.js';
import { FilterModel } from './filters.js';
import { Chrome } from './ui/chrome.js';
import { Rail } from './ui/rail.js';
import { Legend } from './ui/legend.js';
import { ShortcutSheet } from './ui/shortcuts.js';
import { ExportMenu } from './ui/exportmenu.js';
import { ThemeController } from './ui/theme.js';
import { SearchController } from './ui/searchcontroller.js';
import { ScopeSession } from './scope/session.js';
import { ScopeBar } from './ui/scopebar.js';
import { decorateWorkflow, normalizeWorkflow, sanitizeComposer } from './workflow.js';
import { FreshnessState } from './freshness.js';
import { HostNotice } from './ui/hostnotice.js';
import { DoubleClickOpener } from './ui/doubleclick.js';
import { buildAppUi } from './app/build.js';
import { scopeToNode, setGraph, setScope } from './app/documents.js';
import { renderChrome, renderRail } from './app/surfaces.js';
import { openLocation } from './app/actions.js';
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
  RailTab,
  RelatedLoc,
  Sel,
  StaleFile,
  ThemeKind,
  UiToHost,
  ViewState,
  Viewport,
  WorkflowDocument,
} from './types.js';

/** At most this many requests wait for an `actionResult`; the oldest is dropped. */
const MAX_PENDING_REQUESTS = 32;

/**
 * Campaign 3, issue 6. The rail docks only when the canvas beside it keeps at
 * least this width; below the 900 px breakpoint it is an overlay over 86 % of
 * the canvas. Until the reader toggles it, it starts closed when either would
 * leave a diagram narrower than this.
 */
export const RAIL_MIN_CANVAS_W = 900;

type RequestFrame = UiToHost & { requestId?: string };

export interface SelectOptions {
  /** Open the selection's cited source beside the panel (Enter, double-click). Focus stays here. */
  open?: boolean;
  /** With `open`: move focus to the editor (Alt+Enter). */
  focusEditor?: boolean;
  /**
   * A gesture on the canvas (viewer M1): the claim is shown, so a rail that the width rule closed
   * opens on the Inspector, unless the reader closed it; the target stays in view.
   */
  showClaim?: boolean;
  center?: boolean;
  tab?: RailTab;
  pulse?: boolean;
  /**
   * A selection made from the rail (issue 6): below the detail threshold the
   * canvas zooms to the target instead of only centring a shape nobody can read.
   */
  reveal?: boolean;
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
   * A restored scope that arrived BEFORE any graph did: the constructor reads
   * the saved state before the first document is applied, so `ViewState.scope`
   * is stashed here and drained by `setGraph`, through the same `setScope`
   * call (R2H-03).
   */
  pendingScope: { spec: string; depth?: number } | null = null;
  flowOn = true;
  /** Viewer M2: whether the observed claims are faded (the toolbar's "not observed" toggle). */
  exceptionsOn = false;
  caps: Capabilities;
  /* VW-05: `this.themes.kind` is the one answer to "which theme"; the app keeps no copy. */

  filters = new FilterModel();
  viewportState: Viewport = { x: 0, y: 0, zoom: 1 };
  selection: Sel | null = null;
  collapsedState: string[] = [];
  railTab: RailTab = 'issues';
  legendOpen = false;

  /** Viewer M1: the displayed revision's stale files, from the host's `stale` frame. */
  freshness = new FreshnessState();
  /** Whether this viewer has said once where an opened source goes. */
  openHintShown = false;
  railOpen = true;
  /**
   * The reader has shown or hidden the rail themselves, selected a finding
   * (which opens it) or worked inside it, so the width rule in `autoRail` no
   * longer decides.
   */
  railChosen = false;
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
  scopeBar!: ScopeBar;
  scrim!: HTMLElement;
  releasePage: () => void = () => undefined;
  themes!: ThemeController;
  search!: SearchController;
  liveEl!: HTMLElement;
  notice!: HostNotice;
  /** Viewer M1 review: the second click of a double-click opens what the first one selected. */
  doubleClick: DoubleClickOpener;

  saveSoon = debounce(() => this.bridge.saveState(this.getState()), 250);

  constructor(root: HTMLElement, bridge: HostBridge) {
    this.root = root;
    this.bridge = bridge;
    this.caps = bridge.capabilities;
    this.themes = new ThemeController(root, bridge.theme || 'light');
    this.doubleClick = new DoubleClickOpener(root);
    this.disposers.push(() => this.doubleClick.dispose());
    buildAppUi(this);
    const restored = safeLoad(bridge);
    if (restored) applyState(this, restored, false);
    if (restored && typeof restored.workflowRevision === 'string' && restored.viewport) {
      this.restoredView = { revision: restored.workflowRevision, viewport: { ...restored.viewport } };
    }
    const composer = restored && typeof restored.workflowRevision === 'string' ? sanitizeComposer(restored.composer) : null;
    if (restored && composer) this.restoredComposer = { revision: restored.workflowRevision as string, composer };
    this.disposers.push(bridge.onMessage((msg) => this.onMessage(msg)));
    if (typeof window !== 'undefined') this.disposers.push(on(window, 'resize', () => this.autoRail()));
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
    // Before the first fit, so the fit sees the canvas the rail leaves (issue 6).
    this.autoRail();
    setGraph(this, normalizeWorkflow(document), next, true);
    decorateWorkflow(this, document, composer);
    this.legendOtherKinds();
    // The header is built after the fit ran; refit a viewport nobody moved to
    // the canvas that is actually left (issue 1).
    this.view.afterChromeChange();
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

  /** Ask the host to open `loc` beside the panel; `focusEditor` (Alt+Enter) moves focus there. */
  openLocation(loc: Loc | RelatedLoc, focusEditor = false): void {
    openLocation(this, loc, focusEditor);
  }

  /**
   * Viewer M1: the host's stale files. Cards, connections, findings and quotes that cite them are
   * marked, their Open links are disabled with the reason, and the status bar counts them.
   */
  setStale(files: StaleFile[]): void {
    if (!this.freshness.set(files)) return;
    this.view.setStale(this.freshness.list());
    if (this.index) this.view.refresh(this.selection);
    renderChrome(this);
    renderRail(this);
  }

  /**
   * Viewer M1: the host's banner, drawn under the header once the viewer is mounted. A banner that
   * only says a change is being checked goes to the status bar instead and leaves the notice as
   * it was, so the layout does not jump on every save of a cited file.
   */
  showHostNotice(message: string, codes: string[] | undefined): void {
    const checking = !!codes && codes.length === 1 && codes[0] === 'checking';
    if (this.freshness.checking !== checking) {
      this.freshness.checking = checking;
      renderChrome(this);
    }
    if (checking) return;
    const before = this.notice.root.hidden;
    this.notice.update(message, codes);
    const body = this.root.querySelector('.mlv-body');
    if (body && this.notice.root.nextSibling !== body) this.root.insertBefore(this.notice.root, body);
    if (this.graph && before !== this.notice.root.hidden) this.view.afterChromeChange();
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
    this.railChosen = true;
    this.setRailOpen(!this.railOpen);
  }

  /**
   * Campaign 3, issue 6. MEASURED live: the docked rail took 360 of a 1086 or
   * 1382 px panel, and below the 900 px breakpoint the open overlay covered
   * 86 % of the canvas at the default 541 px. Until the reader chooses, the
   * rail is open only when the canvas beside it keeps RAIL_MIN_CANVAS_W, and
   * follows the panel width as it changes. An unmeasurable root (jsdom, a
   * detached mount) leaves it as it is.
   */
  autoRail(): void {
    if (this.railChosen) return;
    const width = this.root.getBoundingClientRect().width;
    if (!(width > 0)) return;
    const open = width - this.railWidth >= RAIL_MIN_CANVAS_W;
    if (open === this.railOpen) return;
    this.setRailOpen(open);
    // A docked rail changes the canvas width; refit a viewport nobody moved
    // now rather than waiting for the host's ResizeObserver (none in jsdom).
    if (this.graph) this.view.handleResize();
  }

  /**
   * Viewer M2: tell the legend which connection kinds this diagram uses, as the author wrote
   * them, since the line style no longer shows the kind. Most used first.
   */
  private legendOtherKinds(): void {
    const kinds = new Map<string, number>();
    let unspecified = 0;
    for (const edge of (this.scopes.full || this.graph)?.edges || []) {
      if (edge.kind === 'unknown') unspecified++;
      else {
        const word = edge.authoredKind || edge.kind;
        kinds.set(word, (kinds.get(word) || 0) + 1);
      }
    }
    const list = Array.from(kinds, ([kind, count]) => ({ kind, count })).sort((a, b) => b.count - a.count || (a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : 0));
    this.legend.setKinds(list, unspecified);
  }

  /**
   * A finding was selected: its detail lives in the rail, so the rail opens and
   * stays open — the reader is now reading it, and a later resize (the split a
   * followed evidence link opens) must not take it away.
   */
  private showRailForFinding(): void {
    this.railChosen = true;
    if (!this.railOpen) this.setRailOpen(true);
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

  /**
   * Viewer M2: fade the observed claims, or stop fading them. Fill and stroke only (node.css,
   * edge.css), so the faded text keeps its contrast. Per view; not saved.
   */
  setExceptions(next: boolean): void {
    this.exceptionsOn = next;
    if (next) this.view.canvasEl.setAttribute('data-exceptions', 'on');
    else this.view.canvasEl.removeAttribute('data-exceptions');
    renderChrome(this);
    this.announce(next ? 'Observed claims faded; inferred and unresolved claims stand out.' : 'Observed claims shown normally.');
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
    if (sel.kind === 'issue') this.showRailForFinding();
    const openedRail = !!(opts && opts.showClaim) && this.showRailForClaim();
    this.view.applySelection(sel);
    renderRail(this);
    if (opts && opts.reveal && sel.kind === 'edge') this.view.revealEdge(sel.id);
    else if (opts && opts.center && opts.reveal) this.view.revealNode(sel.id, !!opts.pulse);
    else if (opts && opts.center) this.view.centerOnNode(sel.id, !!opts.pulse);
    else if (openedRail && sel.kind !== 'issue') this.view.keepInView({ kind: sel.kind, id: sel.id });
    this.announceSelection();
    if (opts && opts.open) {
      const loc = this.locOf(sel);
      if (loc) this.openLocation(loc, !!opts.focusEditor);
    }
    this.saveSoon();
  }

  /**
   * Viewer M1: a click shows the claim, which lives in the rail. A rail the width rule closed
   * opens (true); one the reader closed stays closed (they have the hover card and Ctrl+B).
   */
  private showRailForClaim(): boolean {
    if (this.railOpen || this.railChosen) return false;
    this.railChosen = true;
    this.setRailOpen(true);
    return true;
  }

  clearSelection(): void {
    if (!this.selection) return;
    this.selection = null;
    this.view.applySelection(null);
    renderRail(this);
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
   * Re-project and relayout LOCALLY. Never posts to the host and never throws:
   * an unresolvable spec is a no-op plus a toast (CONTRACTS 11.8).
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
    // Issue 6: at 15-45 % a centred card is an unreadable shape, so below the
    // detail threshold the canvas zooms to the finding's target. A finding on
    // connections only reveals its first connection.
    if (primary) this.view.revealNode(primary, true);
    else if (issue.edgeIds.length) this.view.revealEdge(issue.edgeIds[0]);
  }

  /** Viewer M1: Enter (or a double-click) on a finding row selects it and opens its first cited range. */
  openIssue(id: string, focusEditor = false): void {
    this.focusIssue(id);
    if (!this.selection || this.selection.kind !== 'issue' || this.selection.id !== id) return;
    const loc = this.locOf({ kind: 'issue', id });
    if (loc) this.openLocation(loc, focusEditor);
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
