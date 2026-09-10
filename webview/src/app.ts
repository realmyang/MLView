/**
 * The MLView application: view state, chrome, side rail, search, the keyboard
 * model and the host protocol.
 *
 * Everything inside the diagram surface — layout, the scene DOM, the viewport,
 * hover and focus — lives in CanvasView; this class drives it. Layout depends
 * only on (graph, collapsed), so filters, selection and hover never relayout.
 */

import { clear, debounce, on } from './dom.js';
import { emptyCounts, normalizeSeverity } from './markers.js';
import { GraphIndex } from './layout/model.js';
import { CanvasView, CanvasHost } from './canvasview.js';
import { FilterModel } from './filters.js';
import { Chrome } from './ui/chrome.js';
import { Rail } from './ui/rail.js';
import { Legend } from './ui/legend.js';
import { AnswersCard } from './ui/answers.js';
import { ignoreComment } from './ui/suppress.js';
import { sanitizeGroupBy } from './ui/railgroup.js';
import { LoadingState } from './ui/states.js';
import { buildShell, claimPage } from './ui/shell.js';
import { handleCanvasKey } from './ui/keymap.js';
import { canvasCommands, CommandPort } from './ui/commands.js';
import { commandPortFor } from './ui/appkeys.js';
import { ShortcutSheet } from './ui/shortcuts.js';
import { ExportMenu, ExportActionId } from './ui/exportmenu.js';
import { resolvePalette } from './export/palette.js';
import {
  ExportRequest,
  copyPngImage,
  copySvgText,
  exportFileName,
  printDiagram,
  regionFromHostWord,
  renderExport,
  savePng,
  saveSvg,
} from './export/actions.js';
import { ThemeController } from './ui/theme.js';
import { SearchController } from './ui/searchcontroller.js';
import { dispatchHostMessage, sanitizeScope } from './protocol.js';
import { ScopeSession, mergeCollapsed, railScopeCounts, sameScope } from './scope/session.js';
import { ScopeBar } from './ui/scopebar.js';
import { PipelineChooser } from './ui/pipelinechooser.js';
import { pipelineRows } from './scope/catalog.js';
import { DiffBar } from './ui/diffbar.js';
import { adoptDiff, drawnRemoved } from './diff/adopt.js';
import { indexOverlay, readOverlay } from './diff/overlay.js';
import type { DiffIndex } from './diff/overlay.js';
import { CHANGED_SPEC } from './diff/changed.js';
import { runFixAction } from './ui/fixes.js';
import { adoptCellMap } from './notebook.js';
import { isSetAside } from './types.js';
import type { SearchHit } from './search.js';
import type {
  Capabilities,
  ScopeSummary,
  Filters,
  HostBridge,
  HostToUi,
  Issue,
  IssueCounts,
  AnswerLoc,
  Loc,
  MLGraph,
  MLViewApp,
  RailGroupBy,
  RailTab,
  RelatedLoc,
  Sel,
  Severity,
  ThemeKind,
  ViewState,
  Viewport,
} from './types.js';

interface SelectOptions {
  open?: boolean;
  center?: boolean;
  tab?: RailTab;
  pulse?: boolean;
}

export class App implements MLViewApp {
  private root: HTMLElement;
  private bridge: HostBridge;
  private graph: MLGraph | null = null;
  private index: GraphIndex | null = null;
  /** The whole-workspace document. `graph` is its projection while scoped. */
  private scopes = new ScopeSession();
  private fullIndex: GraphIndex | null = null;
  /** Restored by the breadcrumb's [x], so clearing feels like a back button. */
  private preScope: { viewport: Viewport; selection: Sel | null } | null = null;
  /** The node `e` / Shift+E are cycling the connections of. */
  private edgeAnchor: string | null = null;
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
  private pendingScope: { spec: string; depth?: number } | null = null;
  private flowOn = true;
  /**
   * VIEW-08. The host's document, EXACTLY as it arrived. `adoptDiff` stamps the
   * overlay onto a copy and resurrects the removed nodes as ghosts, so the
   * original has to survive somewhere: an overlay can arrive after the graph,
   * be replaced, or be dismissed, and each of those has to be re-derivable
   * without asking the analyzer for anything.
   */
  private rawGraph: MLGraph | null = null;
  /** VIEW-08: the HOST's name for what the comparison is against (11.43 D). */
  private diffBaseLabel = '';
  private caps: Capabilities;
  /**
   * VW-05. `ThemeController` is the ONE place a theme is decided: the standalone
   * report's own Auto / Light / Dark / High contrast switch calls it directly,
   * so a copy of the value on the app went stale the moment a reader touched
   * that switch — and the export stamped the stale one on every picture. There
   * is no copy any more; `this.themes.kind` is the answer, always.
   */

  private filters = new FilterModel();
  private viewportState: Viewport = { x: 0, y: 0, zoom: 1 };
  private selection: Sel | null = null;
  private collapsedState: string[] = [];
  private railTab: RailTab = 'issues';
  private railGroupBy: RailGroupBy = 'none';
  private legendOpen = false;
  /** MLV-P12: the pipeline chooser is asked once per viewer, then remembered. */
  private pipelineChosen = false;
  /** MLV-P1: the answer card starts open, so the four answers are the first read. */
  private answersOpen = true;

  private stale: string[] = [];
  private dismissed = new Set<string>();
  private error: { message: string; detail?: string; actions?: { id: string; label: string }[] } | null = null;
  private railOpen = true;
  private railWidth = 360;
  private disposers: (() => void)[] = [];
  private destroyed = false;

  private view!: CanvasView;
  private chrome!: Chrome;
  private rail!: Rail;
  private sheet!: ShortcutSheet;
  private exportMenu!: ExportMenu;
  private legend!: Legend;
  private answers!: AnswersCard;
  private scopeBar!: ScopeBar;
  private diffBar!: DiffBar;
  private chooser!: PipelineChooser;
  private scrim!: HTMLElement;
  private releasePage: () => void = () => undefined;
  private themes!: ThemeController;
  private search!: SearchController;
  private loading!: LoadingState;
  private liveEl!: HTMLElement;

  private saveSoon = debounce(() => this.bridge.saveState(this.getState()), 250);

  constructor(root: HTMLElement, graph: MLGraph | null, bridge: HostBridge) {
    this.root = root;
    this.bridge = bridge;
    this.caps = bridge.capabilities;
    this.themes = new ThemeController(root, bridge.theme || 'light', bridge.themePreference);
    this.build();
    // VIEW-08. The standalone report's overlay travels the way the rule-doc
    // sidecar does — a second `<script type="application/json">` beside
    // `#mlview-graph` — so it is read BEFORE the first document is adopted and
    // the first paint already carries the ledges. A page without one is
    // unaffected: `readOverlay` returns null and nothing else changes.
    this.scopes.setDiff(readOverlay());
    const restored = safeLoad(bridge);
    if (restored) this.applyState(restored, false);
    this.disposers.push(bridge.onMessage((msg) => this.onMessage(msg)));
    // The initial scope travels as an attribute on the root element the report
    // already emits, so `mount(root, graph, bridge)` keeps its exact frozen
    // three-argument signature (CONTRACTS 11.8). It outranks a restored scope,
    // so it is stashed LAST — either way `setGraph` drains exactly one.
    const attrSpec = root.getAttribute('data-mlview-scope');
    const attrDepth = root.getAttribute('data-mlview-depth');
    if (attrSpec) this.pendingScope = { spec: attrSpec, depth: attrDepth ? Number(attrDepth) : undefined };
    if (graph) this.setGraph(graph, restored ? { viewport: restored.viewport } : undefined);
    else this.showLoading(true);
    bridge.post({ v: 1, type: 'ready' });
  }

  /* ── shell ─────────────────────────────────────────────────────────── */

  private build(): void {
    const shell = buildShell(this.root, this.themes.kind);
    this.releasePage = claimPage(this.root);
    this.liveEl = shell.live;
    this.scrim = shell.scrim;
    on(this.scrim, 'click', () => this.toggleRail());
    this.view = new CanvasView(shell, this.canvasHost());

    this.chrome = new Chrome({
      onQuery: (q) => this.search.run(q),
      onSearchKey: (ev) => this.search.handleKey(ev),
      onRefresh: () => this.requestRefresh(),
      onExport: () => this.bridge.post({ v: 1, type: 'exportHtml' }),
      onToggleRail: () => this.toggleRail(),
      onSeverity: (sev) => this.applyFilters(() => this.filters.toggleSeverity(sev)),
      onShowSuppressed: (next) => this.setFilters({ showSuppressed: next }),
      onFit: () => this.view.fit(),
      onZoom: (dir) => this.view.zoomStep(dir),
      onStage: (stageId) => this.applyFilters(() => this.filters.toggleStage(stageId, this.laneIds())),
      onClearFilters: () => this.clearFilters(),
      onZoomToSelection: () => this.zoomToSelection(),
      onAction: (id) => this.onAction(id),
      onDismiss: (key) => {
        this.dismissed.add(key);
        this.renderChrome();
      },
      onScope: () => this.toggleScopePicker(),
      onToggleFlow: (next) => this.setFlow(next),
      onToggleLegend: (next) => this.setLegend(next),
      onToggleMinimap: (next) => this.setMinimapCollapsed(next),
      onChangedOnly: (next) => this.setFilters({ changedOnly: next }),
    });

    this.scopeBar = new ScopeBar({
      onPick: (spec, depth) => {
        this.setScope(spec, depth === undefined ? undefined : { depth });
        this.scopeBar.closePicker();
      },
      onClear: () => this.setScope(null),
      onDepth: (delta) => this.stepDepth(delta),
      onCopy: (spec) => {
        this.bridge.post({ v: 1, type: 'copy', text: spec });
        this.view.toast('Scope copied: ' + spec);
      },
    });
    this.chrome.scopeSlot.appendChild(this.scopeBar.breadcrumb.root);

    // VIEW-08. Its own band under the chip row: the headline is the first thing
    // a reviewer reads, and it must not compete with the toolbar for width.
    this.diffBar = new DiffBar({
      onChangedOnly: (next) => this.setChangedOnly(next),
      onDismiss: () => this.setDiff(null),
    });

    // VIEW-07. The trigger goes in the toolbar beside Fit; the popup goes on the
    // app root, so the roving toolbar (VIEW-12) keeps its single tab stop.
    this.exportMenu = new ExportMenu({
      onRegion: () => undefined,
      onAction: (action) => this.runExport(action),
    });
    this.chrome.exportSlot.appendChild(this.exportMenu.button);

    // One roving `role="toolbar"` over the toolbar row and the stage-filter row
    // (VIEW-12), so the whole control strip is a single tab stop.
    this.root.appendChild(this.chrome.bar);
    this.root.appendChild(this.chrome.chipRow);
    this.root.appendChild(this.diffBar.root);
    this.root.appendChild(this.chrome.banners);
    this.root.appendChild(shell.body);
    shell.body.appendChild(shell.main);

    // MLV-P1. Appended AFTER the canvas and lifted above it by `order: -1`
    // (styles/chrome.css): the canvas has to stay within four Tab presses of the
    // top of the document (VIEW-12), and a card with five controls in front of
    // it would put it at nine.
    this.answers = new AnswersCard({
      onToggle: (open) => this.setAnswersOpen(open),
      onOpen: (loc) => this.openLocation(completeLoc(loc, this.graph)),
    });
    shell.main.appendChild(this.answers.root);

    this.search = new SearchController(this.chrome.searchInput, this.chrome.results, {
      index: () => this.index,
      activate: (hit) => this.activateHit(hit),
      onQueryChanged: (query) => {
        this.filters.patch({ query });
        this.saveSoon();
      },
      blurToCanvas: () => this.view.canvasEl.focus(),
    });

    this.loading = new LoadingState(() => this.onAction('mlview.cancelAnalysis'));
    this.loading.root.hidden = true;
    shell.stateHost.appendChild(this.loading.root);

    this.rail = new Rail({
      onTab: (tab) => this.setRailTab(tab),
      onClearFilters: () => this.clearFilters(),
      onSelectIssue: (id) => this.focusIssue(id),
      onSelectNode: (id) => this.select({ kind: 'node', id }, { center: true }),
      onOpen: (loc) => this.openLocation(loc),
      onResize: (w) => this.setRailWidth(w),
      onToggleRail: () => this.toggleRail(),
      onAsk: (id) => this.askAssistant(id),
      onSelectLane: (laneId) => this.selectLane(laneId),
      onToggleCollapse: (id) => {
        if (this.index && this.index.isGroup(id)) this.view.toggleCollapse(id);
      },
      // "Show all" means ALL: a reader who clicks it while both a scope and the
      // diff projection are narrowing the list expects one gesture, not two.
      onClearScope: () => {
        if (this.scopes.changedOnly) this.setChangedOnly(false);
        this.setScope(null);
      },
      onScopeToNode: (id) => this.scopeToNode(id),
      onGroupBy: (mode) => this.setRailGroupBy(mode),
      onCopyIgnore: (code) => this.copyIgnore(code),
      onDisableRule: (code) => this.disableRule(code),
      onApplyFix: (id) => this.applyFix(id),
    });
    shell.body.appendChild(this.rail.root);

    // Anchored inside the canvas, beside the minimap, so the key sits with the
    // picture it explains rather than in a modal over it (VIEW-10).
    this.legend = new Legend((open) => this.setLegend(open));
    shell.canvas.appendChild(this.legend.root);

    // MLV-P12. Appended on the app root beside the shortcut sheet and the scope
    // picker, so it overlays the diagram without being inside the canvas — a
    // chooser drawn in the world layer would pan and zoom with it.
    this.chooser = new PipelineChooser({ onPick: (spec) => this.answerPipelineChooser(spec) });
    this.root.appendChild(this.chooser.root);

    this.sheet = new ShortcutSheet(() => this.toggleShortcuts(false));
    this.root.appendChild(this.sheet.root);
    this.root.appendChild(this.exportMenu.panel);
    this.root.appendChild(this.scopeBar.picker.root);

    this.root.appendChild(this.chrome.status);
    this.root.appendChild(this.liveEl);
    this.setRailWidth(this.railWidth);
    this.setRailOpen(this.railOpen);
    // Only the standalone report owns its own theme; in a webview the host does.
    if (this.bridge.host === 'standalone') this.themes.mountSwitch(this.chrome.toolbar);
  }

  /** What the canvas is allowed to ask of the application. */
  private canvasHost(): CanvasHost {
    return {
      keep: this.filters.keep,
      isFilteredOut: (node) => this.filters.hidesNode(node),
      activateNode: (id) => this.select({ kind: 'node', id }, { open: true, tab: 'inspector' }),
      activateEdge: (id) => this.select({ kind: 'edge', id }, { open: true }),
      clearFilters: () => this.clearFilters(),
      canReanalyze: () => this.caps.canReanalyze,
      requestRefresh: () => this.requestRefresh(),
      announce: (text) => this.announce(text),
      afterCollapse: () => {
        this.syncCollapsed();
        this.view.applySelection(this.selection);
        this.renderRail();
        this.saveSoon();
      },
      onViewportChange: (vp) => {
        this.viewportState = { x: vp.x, y: vp.y, zoom: vp.zoom };
        this.saveSoon();
      },
      onMinimapCollapsed: () => {
        // The toolbar carries the accessible copy of this toggle (VIEW-12), so
        // the pointer affordance inside the panel has to keep it in step.
        this.renderChrome();
        this.saveSoon();
      },
      onKeyDown: (ev) => this.onKeyDown(ev),
      onBackgroundClick: () => this.clearSelection(),
      widenScope: () => this.stepDepth(1),
      clearScope: () => this.setScope(null),
      scopeSpec: () => this.scopes.spec,
    };
  }

  /* ── graph + layout ────────────────────────────────────────────────── */

  /**
   * A NEW whole-workspace document. `setGraph` owns the full graph and the
   * collapse set; `applyProjection` draws whatever the scope currently selects,
   * so chrome, rail, outline, minimap and layout are scoped with no further
   * edits — they all read only the index (FEATURES 5.1).
   */
  private setGraph(graph: MLGraph, preserve?: Partial<ViewState>, reresolve = false): void {
    // What the HOST currently believes the scope is. A new document can move it
    // without any user gesture — the scope is re-resolved, and dropped when it
    // now matches nothing — and `scopeChanged` is the host's only writer of the
    // panel title and description (CONTRACTS 11.7, 11.11). Without this the tab
    // kept reading `MLView — validate()` over a whole-workspace diagram
    // (R2H-01 / R2-REG-02).
    const before = this.scopes.full ? this.scopes.summary() : null;
    // NB / 11.29 N6. The notebook cell mapping arrives in `Node.attrs` as
    // strings, because `Loc` is frozen (§2). Lift it onto each node's own `Loc`
    // once, here, so every label surface keeps reading a plain `Loc` and none of
    // them has to know where the analyzer keeps its provenance. A `.py`
    // document, and a notebook node the ingest could not map, are untouched.
    adoptCellMap(graph.nodes);
    this.rawGraph = graph;
    // VIEW-08. The overlay is lifted onto a COPY: `diffStatus` lands on the
    // nodes it describes and the removed ones come back as ghosts in place, so
    // every drawing surface below keeps reading a plain document (11.38, and the
    // same shape as `adoptCellMap` above).
    const diff = this.scopes.diff;
    if (diff) graph = adoptDiff(graph, diff);
    this.scopes.setGraph(graph);
    this.fullIndex = new GraphIndex(graph);
    // The collapse set is held against the FULL id space and filtered at
    // projection time, so collapsing inside a scope and then clearing it does
    // not lose the collapse (FEATURES 3.5).
    if (preserve && preserve.collapsed) this.collapsedState = preserve.collapsed.slice();
    else if (!this.collapsedState.length && this.view.collapsed.size === 0) {
      this.collapsedState = this.fullIndex.defaultCollapsed();
    }
    if (reresolve && this.scopes.reresolve()) this.view.toast('Scope no longer matches — cleared');
    this.applyProjection(preserve, true);
    const pending = this.pendingScope;
    this.pendingScope = null;
    // A drained scope announces, posts and persists through `afterScopeChange`,
    // so it needs no second post; anything else that moved the host's view of
    // the scope does.
    if (pending && this.drainScope(pending)) return;
    if (before && !sameScope(before, this.scopes.summary())) this.postScopeChanged();
    // MLV-P12: after the document is drawn and any pending scope has drained,
    // so a reader who already has a scope is never asked which pipeline to open.
    this.maybeOpenPipelineChooser();
  }

  /**
   * Apply a scope that arrived BEFORE the document did — a restored
   * `ViewState.scope`, or the report's `data-mlview-scope` attribute.
   *
   * CONTRACTS 11.9's re-resolve applies here too: a spec that matches nothing in
   * the document that finally arrived is dropped with the same toast rather than
   * left standing as an empty diagram the user never asked for. Returns true when
   * it applied the scope and therefore already posted `scopeChanged`.
   */
  private drainScope(pending: { spec: string; depth?: number }): boolean {
    const result = this.scopes.set(pending.spec, pending.depth);
    if (!result.ok) {
      const error = result.error;
      this.view.toast(error ? error.code + ': ' + error.term : 'That scope could not be applied');
      return false;
    }
    if (result.empty) {
      this.scopes.set(null);
      this.view.toast('Scope no longer matches — cleared');
      return false;
    }
    this.afterScopeChange();
    return true;
  }

  /** Draw the current projection. The old `setGraph` body, verbatim. */
  private applyProjection(preserve?: Partial<ViewState>, announce = false): void {
    const doc = this.scopes.document;
    if (!doc) return;
    const graph = doc;
    this.graph = graph;
    // Reuse the full index only when the document really IS the full one. The
    // test used to be `spec === null`, which VIEW-08 made wrong: a diff
    // projection narrows the document without any selector being set, and
    // indexing the whole graph for it drew every node the projection had just
    // removed.
    const index = graph === this.scopes.full && this.fullIndex ? this.fullIndex : new GraphIndex(graph);
    this.index = index;
    this.error = null;
    this.showLoading(false);

    const known = new Set(graph.nodes.map((n) => n.id));
    const collapsed = preserve && preserve.collapsed ? preserve.collapsed : this.collapsedState;
    this.view.setIndex(index);
    // Every flow element and every --mlv-flow-* property goes before the scene
    // is rebuilt, and the remembered endpoint ids reset (CONTRACTS 11.14 C1).
    this.view.flow.clear();
    this.view.setCollapsed(collapsed.filter((id) => known.has(id) && index.isGroup(id)));

    if (preserve && preserve.selection !== undefined) this.selection = preserve.selection;
    if (this.selection && this.selection.kind === 'node' && !known.has(this.selection.id)) this.selection = null;
    if (this.selection && this.selection.kind === 'edge' && !index.edgeById.has(this.selection.id)) this.selection = null;

    this.view.relayout();
    const vp = preserve && preserve.viewport ? preserve.viewport : null;
    if (vp) this.view.viewport.set(vp);
    else this.view.fit();
    this.renderChrome();
    this.renderRail();
    this.view.applySelection(this.selection);
    if (announce) {
      this.announce(
        'Analysis loaded: ' +
          graph.nodes.length +
          ' nodes, ' +
          graph.issues.length +
          ' issues, ' +
          graph.stats.issues.high +
          ' high severity.',
      );
    }
    this.saveSoon();
  }

  /* ── scope ─────────────────────────────────────────────────────────── */

  /** Merge the drawn collapse set back into the full-id-space one. */
  private syncCollapsed(): void {
    this.collapsedState = mergeCollapsed(
      this.collapsedState,
      this.graph ? this.graph.nodes.map((n) => n.id) : [],
      this.view.collapsed,
    );
  }

  private toggleScopePicker(): void {
    this.scopeBar.togglePicker(this.scopes.full, this.scopes.spec, this.scopes.depth);
  }

  /* ── the pipeline chooser (MLV-P12) ────────────────────────────────── */

  /**
   * Open the chooser on a workspace with two or more pipelines — once.
   *
   * A reader who arrived with a scope already applied (a restored `ViewState`,
   * the report's `data-mlview-scope`, a host `setScope`) has ALREADY answered
   * the question, so they are not asked; nor is anyone who answered it before,
   * which `ViewState.pipelineChosen` remembers. The relation is computed here,
   * never read off the emitted `pipelines[]` block (CONTRACTS 11.47 A).
   */
  private maybeOpenPipelineChooser(): void {
    if (this.pipelineChosen || this.chooser.open) return;
    const graph = this.scopes.full;
    if (!graph || this.scopes.spec || this.pendingScope) return;
    const rows = pipelineRows(graph);
    if (rows.length < 2) return;
    this.chooser.show(graph, rows);
    this.announce(
      'This workspace has ' + rows.length + ' pipelines. Choose one, or show everything.',
    );
  }

  /**
   * The chooser's one exit. Every answer — a pipeline, "everything", Escape —
   * is recorded, so the question is asked once per viewer and never again.
   */
  private answerPipelineChooser(spec: string | null): void {
    this.chooser.hide();
    this.pipelineChosen = true;
    if (spec) this.setScope(spec);
    else this.announce('Showing the whole workspace, every pipeline at once.');
    this.saveSoon();
  }

  private stepDepth(delta: number): void {
    const result = this.scopes.stepDepth(delta);
    if (!result.ok) return;
    this.afterScopeChange();
  }

  /** The Inspector's "Scope to this unit / step". */
  private scopeToNode(nodeId: string): void {
    const node = this.fullIndex ? this.fullIndex.nodeById.get(nodeId) : null;
    if (!node) return;
    this.setScope('unit:' + node.qualname);
  }

  /**
   * Applied, announced, posted and persisted. A scope change is LOCAL: it never
   * posts `requestRefresh` and never reaches the analyzer (CONTRACTS 11.8).
   */
  private afterScopeChange(): void {
    this.syncCollapsed();
    this.applyProjection();
    const summary = this.postScopeChanged();
    this.announce(
      summary.spec
        ? 'Scoped to ' + summary.label + ', ' + summary.nodes + ' of ' + summary.of + ' nodes.'
        : 'Scope cleared, showing all ' + summary.of + ' nodes.',
    );
    this.saveSoon();
  }

  /**
   * The ONE place `scopeChanged` is posted. Every scope change goes through it,
   * including a clear (`spec: null`, `label: "Everything"`, `nodes === of`) and
   * including the one nobody asked for: a re-analysis whose new document no
   * longer contains the scoped unit (CONTRACTS 11.7).
   */
  private postScopeChanged(): ScopeSummary {
    const summary = this.scopes.summary();
    this.bridge.post({
      v: 1,
      type: 'scopeChanged',
      spec: summary.spec,
      label: summary.label,
      nodes: summary.nodes,
      of: summary.of,
    });
    return summary;
  }

  private laneIds(): string[] {
    return this.index ? this.index.lanes.map((l) => l.id) : [];
  }

  private requestRefresh(): void {
    this.bridge.post({ v: 1, type: 'requestRefresh', scope: 'workspace' });
  }

  /* ── chrome + rail ─────────────────────────────────────────────────── */

  /**
   * Counts for the toolbar chips: severity filters do not hide their own count.
   *
   * VW-04. "Visible" here means exactly what `Filters.keep` means everywhere
   * else — `isSetAside`, i.e. suppressed OR BASELINED. It used to test
   * `issue.suppressed` alone, so the moment a repo adopted `--baseline` the
   * most prominent number on the page (5 / 6 / 3) disagreed with the rail
   * ('high · 4', 'medium · 4'), with the MLV-P1 answer card ('8 finding(s)')
   * and with `mlview issues` ('8 issue(s) ... 6 baselined'), and the chip
   * labelled 5 hid four rows when clicked. The netting is now also SAID:
   * `chrome.update` draws the set-aside button as '1 suppressed · 6 baselined'.
   */
  private visibleCounts(): IssueCounts {
    const counts = emptyCounts();
    if (!this.graph) return counts;
    for (const issue of this.graph.issues) {
      if (!this.filters.value.showSuppressed && isSetAside(issue)) continue;
      counts[normalizeSeverity(issue.severity) as Severity]++;
    }
    return counts;
  }

  private renderChrome(): void {
    const summary = this.scopes.summary();
    const view = this.graph ? this.graph.view || null : null;
    // VIEW-08. The breadcrumb is the SCOPE's chip. A diff projection with no
    // scope under it puts a `view` on the document without the user ever having
    // picked a selector, and drawing "Scoped to Changed in this diff · Copy
    // scope" over it would offer a selector that does not parse and an [x] that
    // clears nothing. The diff band owns that state instead.
    const diffOnlyView = !!view && view.scope === CHANGED_SPEC;
    this.scopeBar.update(
      diffOnlyView ? null : view,
      this.scopes.full,
      this.scopes.spec,
      this.scopes.depth,
      !!(this.graph && this.graph.stats.truncated),
    );
    this.renderDiffBar();
    this.chrome.update({
      graph: this.graph,
      scopeLabel: summary.label,
      scopeActive: summary.spec !== null,
      flowOn: this.flowOn,
      legendOpen: this.legendOpen,
      laneIds: this.laneIds(),
      outOfScopeStages: this.index ? this.index.outOfScopeStages : [],
      hasSelection: !!this.selection,
      filters: this.filters.value,
      capabilities: this.caps,
      stale: this.stale,
      error: this.error,
      dismissed: this.dismissed,
      visibleCounts: this.visibleCounts(),
      dynamicNodes: this.graph ? this.graph.nodes.filter((n) => n.dynamic).length : 0,
      minimapCollapsed: this.view.minimapCollapsed,
    });
    // MLV-P1: hidden outright when the document carries no `answers` block.
    this.answers.update(this.graph ? this.graph.answers : undefined, this.answersOpen);
    // VIEW-07: "Current scope" is offered only while there IS a projection.
    this.exportMenu.setScopeAvailable(!!view);
  }

  /* ── the diff overlay (VIEW-08) ────────────────────────────────────── */

  private renderDiffBar(): void {
    const diff = this.scopes.diff;
    this.diffBar.update({
      diff,
      changedOnly: this.scopes.changedOnly,
      ghostsDrawn: diff && this.graph ? drawnRemoved(this.graph, diff) : 0,
      shown: this.graph ? this.graph.nodes.length : 0,
      of: this.scopes.full ? this.scopes.full.nodes.length : 0,
      changedEmpty: this.scopes.changedOnly && !this.scopes.changedActive,
      baseLabel: this.diffBaseLabel,
    });
  }

  /**
   * Install, replace or clear the overlay. It is a SIBLING document: nothing is
   * re-analysed, nothing is posted, and the graph the host gave us is re-adopted
   * from the pristine copy so dismissing a diff really does put the diagram back
   * exactly as it was.
   */
  private setDiff(diff: DiffIndex | null): void {
    if (!diff) this.diffBaseLabel = '';
    this.scopes.setDiff(diff);
    const graph = this.rawGraph;
    if (graph) {
      this.setGraph(graph, { viewport: { ...this.viewportState }, selection: this.selection, collapsed: this.collapsedState.slice() });
    } else {
      this.renderChrome();
    }
    this.announce(
      diff
        ? 'Comparison loaded: ' + diff.headline() + '.'
        : 'Comparison cleared; showing this analysis on its own.',
    );
    this.saveSoon();
  }

  /**
   * "Changed only" — the diff as a PROJECTION (ROADMAP VIEW-08). Local, like
   * every scope change: it never posts `requestRefresh` and never re-analyses.
   */
  private setChangedOnly(next: boolean): void {
    const ok = this.scopes.setChangedOnly(next);
    this.syncCollapsed();
    this.applyProjection();
    if (!ok) {
      this.view.toast('Nothing that changed is in this view');
      this.announce('Changed only: nothing that changed is in this view.');
      this.saveSoon();
      return;
    }
    const shown = this.graph ? this.graph.nodes.length : 0;
    const of = this.scopes.full ? this.scopes.full.nodes.length : 0;
    this.announce(
      next
        ? 'Showing what changed: ' + shown + ' of ' + of + ' nodes, plus one hop.'
        : 'Changed-only view off, showing all ' + of + ' nodes.',
    );
    this.saveSoon();
  }

  /* ── structured fixes (H5) ─────────────────────────────────────────── */

  /** True only where the HOST can actually make an edit behind a preview. */
  private canApplyFix(): boolean {
    return this.bridge.host === 'vscode' && this.caps.canOpenSource;
  }

  /** H5. A REQUEST, never an edit — the decision itself lives in `ui/fixes.ts`. */
  private applyFix(issueId: string): void {
    const issue = this.index ? this.index.issueById.get(issueId) : null;
    if (!issue) return;
    runFixAction(issue, {
      canApply: this.canApplyFix(),
      post: (msg) => this.bridge.post(msg),
      toast: (text) => this.view.toast(text),
      announce: (text) => this.announce(text),
    });
  }

  /* ── export (VIEW-07) ──────────────────────────────────────────────── */

  /**
   * Everything the export needs, gathered at the moment the reader asked.
   *
   * The plan is the one the DOM was built from, the palette is read off the
   * MOUNTED root — so a VS Code user exports their own theme's colours, not our
   * defaults — and the region is whatever the menu currently has checked.
   */
  private exportRequest(): ExportRequest | null {
    const plan = this.view.scenePlan();
    if (!plan || !this.graph) return null;
    const summary = this.scopes.summary();
    return {
      plan,
      // VW-05: the LIVE theme, not the one the host handed us at construction.
      // The standalone report's Auto / Light / Dark / High contrast chips go
      // through `ThemeController.choose`, which never called back into the app,
      // so every export stamped `data-mlview-theme="light"` and the
      // high-contrast branch in `buildExportSvg` (outlined severity glyphs)
      // could not be reached from the standalone report at all.
      palette: resolvePalette(this.root, this.themes.kind),
      theme: this.themes.kind,
      graph: this.graph,
      regionKind: this.exportMenu.currentRegion,
      viewRect: this.view.viewportRect(),
      scopeLabel: summary.spec ? summary.label : null,
      generatedAt: new Date().toISOString().slice(0, 10),
    };
  }

  private runExport(action: ExportActionId): void {
    const host = {
      post: (msg: any) => this.bridge.post(msg),
      toast: (text: string) => this.view.toast(text),
      announce: (text: string) => this.announce(text),
      print: () => {
        try {
          if (typeof window !== 'undefined' && typeof window.print === 'function') window.print();
        } catch (_e) {
          this.view.toast('This host does not offer a print dialog.');
        }
      },
    };
    if (action === 'print') {
      printDiagram(host);
      return;
    }
    const request = this.exportRequest();
    if (!request) {
      this.view.toast('Nothing is drawn yet — there is nothing to export.');
      return;
    }
    const result = renderExport(request);
    if (action === 'svg') saveSvg(host, result, exportFileName(request, 'svg'));
    else if (action === 'png') void savePng(host, result, exportFileName(request, 'png'));
    else if (action === 'copy-svg') void copySvgText(host, result);
    else if (action === 'copy-png') void copyPngImage(host, result);
  }

  private renderRail(): void {
    const sel = this.selection;
    // An issue selection resolves to its primary node, so the Inspector is never
    // empty just because the user clicked the issue row instead of the card
    // (MLV-R1-006).
    const nodeId = this.selectedNodeId();
    const selectedNode = nodeId && this.index ? this.index.nodeById.get(nodeId) || null : null;
    this.rail.update({
      index: this.index,
      canAskAssistant: this.caps.canAskAssistant,
      tab: this.railTab,
      issues: this.graph ? this.graph.issues : [],
      selectedNode,
      selectedIssueId: sel && sel.kind === 'issue' ? sel.id : null,
      collapsed: this.view.collapsed,
      keep: this.filters.keep,
      keepBase: this.filters.keepBase,
      scope: railScopeCounts(this.graph),
      groupBy: this.railGroupBy,
      diff: this.scopes.diff,
      canApplyFix: this.canApplyFix(),
    });
  }

  /**
   * MLV-P10, "Copy ignore comment". It goes through the SAME `copy` message the
   * scope breadcrumb uses, so the standalone report answers with the clipboard
   * plus its copy toast (CONTRACTS 11.17.1) and VS Code with its own clipboard.
   * Nothing is written to any file by the viewer, ever.
   */
  private copyIgnore(code: string): void {
    const text = ignoreComment(code);
    this.bridge.post({ v: 1, type: 'copy', text });
    this.view.toast('Copied ' + text);
    this.announce('Copied the ignore comment for ' + code + '.');
  }

  /**
   * MLV-P10, "Disable this rule". A REQUEST, not an edit: the host decides
   * whether and how to write `.mlview.toml`. A host predating the message drops
   * it, which leaves the viewer exactly as it was.
   */
  private disableRule(code: string): void {
    this.bridge.post({ v: 1, type: 'suppressRule', code, scope: 'workspace', action: 'disable' });
    // VW-10. What the announcement may claim is bounded by what the HOST does
    // with the frame. VS Code writes `.mlview.toml`; the standalone report
    // answers it in the same page by copying the snippet to the clipboard
    // (`bridges.ts`), so "Asked the host to disable X" announced an edit that
    // nobody made, and did it before the toast that told the truth. This says
    // the request and names the answer, in both hosts.
    this.announce(
      'Requested that ' + code + ' be disabled for this workspace — ' +
        (this.bridge.host === 'standalone'
          ? 'this host answers by copying the .mlview.toml snippet.'
          : 'the host decides whether to write .mlview.toml.'),
    );
  }

  /** VIEW-12: the toolbar's copy of the minimap chevron. */
  private setMinimapCollapsed(next: boolean): void {
    this.view.setMinimapCollapsed(next);
    this.renderChrome();
    this.saveSoon();
    this.announce('Overview minimap ' + (next ? 'hidden' : 'shown') + '.');
  }

  /** MLV-P1: the card's disclosure, persisted as ViewState.answersOpen. */
  private setAnswersOpen(open: boolean): void {
    this.answersOpen = open;
    this.answers.update(this.graph ? this.graph.answers : undefined, open);
    this.saveSoon();
  }


  /** The rail's "Group by" control (RAIL-GROUP). Persisted like `railTab`. */
  private setRailGroupBy(mode: RailGroupBy): void {
    this.railGroupBy = sanitizeGroupBy(mode);
    this.renderRail();
    this.saveSoon();
    this.announce('Findings grouped by ' + this.railGroupBy + '.');
  }

  private setLegend(next: boolean): void {
    this.legendOpen = next;
    this.legend.setOpen(next);
    this.renderChrome();
    this.saveSoon();
  }

  private setRailTab(tab: RailTab): void {
    this.railTab = tab;
    this.renderRail();
    this.saveSoon();
  }

  private toggleRail(): void {
    this.setRailOpen(!this.railOpen);
  }

  private setRailOpen(open: boolean): void {
    this.railOpen = open;
    this.rail.root.hidden = !open;
    // The scrim only paints below the 900 px breakpoint (see chrome.css), but its
    // hidden state must track the drawer at every width.
    this.scrim.hidden = !open;
  }

  private toggleShortcuts(next?: boolean): void {
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

  private setRailWidth(width: number): void {
    this.railWidth = Math.max(280, Math.min(560, Math.round(width)));
    this.rail.root.style.width = this.railWidth + 'px';
  }

  /* ── selection ─────────────────────────────────────────────────────── */

  private select(sel: Sel, opts?: SelectOptions): void {
    if (sel.kind !== 'edge') this.edgeAnchor = null;
    this.selection = sel;
    if (opts && opts.tab) this.railTab = opts.tab;
    this.view.applySelection(sel);
    this.renderRail();
    if (sel.kind === 'node') this.bridge.post({ v: 1, type: 'selectNode', nodeId: sel.id });
    if (opts && opts.center) this.view.centerOnNode(sel.id, !!opts.pulse);
    if (opts && opts.open) {
      const loc = this.locOf(sel);
      if (loc) this.openLocation(loc);
    }
    this.announceSelection();
    this.saveSoon();
  }

  private clearSelection(): void {
    if (!this.selection) return;
    this.selection = null;
    this.view.applySelection(null);
    this.renderRail();
    this.bridge.post({ v: 1, type: 'selectNode', nodeId: null });
    this.saveSoon();
  }

  private locOf(sel: Sel): Loc | null {
    if (!this.index) return null;
    if (sel.kind === 'node') {
      const node = this.index.nodeById.get(sel.id);
      return node ? node.loc : null;
    }
    if (sel.kind === 'edge') {
      const edge = this.index.edgeById.get(sel.id);
      return edge ? edge.loc : null;
    }
    const issue = this.index.issueById.get(sel.id);
    return issue ? issue.loc : null;
  }

  /** The node a non-node selection points at — an issue's primary node. */
  private selectedNodeId(): string | null {
    const sel = this.selection;
    if (!sel || !this.index) return null;
    if (sel.kind === 'node') return sel.id;
    if (sel.kind !== 'issue') return null;
    const issue = this.index.issueById.get(sel.id);
    return issue && issue.nodeIds.length ? issue.nodeIds[0] : null;
  }

  /* ── commands ──────────────────────────────────────────────────────── */

  /** Mutate the filter model, then repaint everything that depends on it. */
  private applyFilters(mutate: () => void): void {
    mutate();
    this.renderChrome();
    if (this.index) {
      this.view.render();
      this.view.applySelection(this.selection);
    }
    this.renderRail();
    this.saveSoon();
  }

  private clearFilters(): void {
    this.search.clear();
    this.applyFilters(() => this.filters.reset());
  }

  /** The Outline's lane rows are a jump target: land on the stage's first node. */
  private selectLane(laneId: string): void {
    if (!this.index) return;
    const roots = this.index.roots(laneId);
    if (!roots.length) {
      this.announce('That stage has no nodes.');
      return;
    }
    this.select({ kind: 'node', id: roots[0] }, { center: true, pulse: true });
  }

  private zoomToSelection(): void {
    const id = this.selectedNodeId();
    if (id) this.view.zoomToNode(id);
  }

  /** Composes the prompt described in UX_DESIGN section 7; hidden unless the host offers it. */
  private askAssistant(nodeId: string): void {
    if (!this.caps.canAskAssistant || !this.index) return;
    const node = this.index.nodeById.get(nodeId);
    if (!node) return;
    const codes = this.index.issuesOf(nodeId, this.filters.keep).map((i) => i.code);
    const prompt =
      'Explain the MLView node ' +
      (node.fqn || node.qualname) +
      ' at ' +
      node.loc.file +
      ':' +
      node.loc.line +
      ' in the ' +
      node.stage +
      ' stage' +
      (codes.length ? ', and the findings ' + codes.join(', ') : '') +
      '.';
    this.bridge.post({ v: 1, type: 'askAssistant', nodeId, prompt });
  }

  private openLocation(loc: Loc | RelatedLoc): void {
    if (!this.caps.canOpenSource) return;
    this.bridge.post({
      v: 1,
      type: 'openLocation',
      file: loc.file,
      absFile: loc.absFile,
      line: loc.line,
      col: loc.col,
      endLine: loc.endLine,
      endCol: loc.endCol,
      preview: true,
    });
  }

  private onAction(id: string): void {
    if (id === 'mlview.copyErrorDetails' && this.error) {
      this.bridge.post({
        v: 1,
        type: 'copy',
        text: this.error.message + (this.error.detail ? '\n' + this.error.detail : ''),
      });
      this.view.toast('Error details copied');
      return;
    }
    this.bridge.post({ v: 1, type: 'action', id });
  }

  private announce(text: string): void {
    this.liveEl.textContent = text;
  }

  private announceSelection(): void {
    const sel = this.selection;
    if (!sel || !this.index) return;
    if (sel.kind === 'node') {
      const label = this.view.labelOf(sel.id);
      if (label) this.announce('Selected ' + label);
    } else if (sel.kind === 'issue') {
      const issue = this.index.issueById.get(sel.id);
      if (issue) this.announce('Issue ' + issue.code + ', ' + issue.severity + ' severity: ' + issue.title);
    }
  }

  private showLoading(on: boolean): void {
    this.loading.root.hidden = !on;
  }

  private activateHit(hit: SearchHit): void {
    if (hit.kind === 'node') this.focusNode(hit.id, { center: true, pulse: true });
    else this.focusIssue(hit.id);
  }

  /* ── keyboard ──────────────────────────────────────────────────────── */

  private onKeyDown(ev: KeyboardEvent): void {
    handleCanvasKey(ev, canvasCommands(this.commandPort()));
  }

  /** Everything the keyboard model is allowed to reach (see ui/commands.ts). */
  private commandPort(): CommandPort {
    return commandPortFor({
      view: () => this.view,
      index: () => this.index,
      selection: () => this.selection,
      edgeAnchor: () => this.edgeAnchor,
      setEdgeAnchor: (id) => {
        this.edgeAnchor = id;
      },
      select: (sel) => this.select(sel),
      clearSelection: () => this.clearSelection(),
      focusSearch: () => this.search.focus(),
      visibleIssues: () => this.filteredIssues(),
      focusIssue: (id) => this.focusIssue(id),
      openSelection: () => {
        const sel = this.selection;
        if (!sel) return false;
        const loc = this.locOf(sel);
        if (loc) this.openLocation(loc);
        return true;
      },
      zoomToSelection: () => this.zoomToSelection(),
      move: (key) => this.moveSelection(key),
      toggleSeverity: (sev) => this.applyFilters(() => this.filters.toggleSeverity(sev)),
      toggleRail: () => this.toggleRail(),
      setRailTab: (tab) => this.setRailTab(tab),
      toggleShortcuts: (next) => this.toggleShortcuts(next),
      sheetOpen: () => this.sheet.open,
      closeScopePicker: () => this.scopeBar.closePicker(),
      scopeSpec: () => this.scopes.spec,
      setScope: (spec) => this.setScope(spec),
      stepDepth: (delta) => this.stepDepth(delta),
      scopeToNode: (id) => this.scopeToNode(id),
      openScopePicker: () => this.toggleScopePicker(),
      selectedNodeId: () => this.selectedNodeId(),
      announce: (text) => this.announce(text),
      toggleLegend: () => this.setLegend(!this.legendOpen),
      toggleFlow: () => this.setFlow(!this.flowOn),
    });
  }

  private setFlow(next: boolean): void {
    this.flowOn = next;
    this.view.flow.setEnabled(next);
    this.view.flow.syncCanvas();
    this.renderChrome();
    this.saveSoon();
  }

  private filteredIssues(): Issue[] {
    if (!this.graph) return [];
    return this.graph.issues.filter(this.filters.keep);
  }

  /** Arrows move the selection among visible siblings, in spatial order. */
  private moveSelection(key: string): void {
    const sel = this.selection;
    const next = this.view.nextSelection(sel && sel.kind === 'node' ? sel.id : null, key);
    if (!next) return;
    this.select({ kind: 'node', id: next.id }, { center: !next.visible });
    const element = this.view.nodeElement(next.id);
    if (element) element.focus();
  }

  /* ── host protocol ─────────────────────────────────────────────────── */

  private onMessage(msg: HostToUi): void {
    dispatchHostMessage(msg, {
      init: (theme, capabilities) => {
        this.caps = capabilities || this.caps;
        this.setTheme(theme);
        this.renderChrome();
        this.renderRail();
      },
      graph: (graph, preserve) => this.setGraph(graph, preserve, true),
      analysisStarted: () => {
        this.error = null;
        this.showLoading(true);
        this.renderChrome();
      },
      analysisProgress: (done, total, file) => this.loading.progress(done, total, file),
      analysisFailed: (message, detail, actions) => {
        this.showLoading(false);
        this.error = { message, detail, actions };
        this.renderChrome();
        this.announce('Analysis failed: ' + message);
      },
      theme: (kind) => this.setTheme(kind),
      revealNode: (nodeId, center) => this.focusNode(nodeId, { center, pulse: true }),
      revealIssue: (issueId) => this.focusIssue(issueId),
      setFilter: (severities, codes, query) => {
        if (codes) this.filters.setCodes(codes);
        this.setFilters({ severities: severities ? severities.slice() : undefined });
        if (typeof query === 'string') this.search.setQuery(query);
      },
      stale: (changedFiles) => {
        this.stale = changedFiles.slice();
        this.view.setStale(this.stale);
        this.dismissed.delete('stale');
        this.renderChrome();
        this.view.render();
        this.view.applySelection(this.selection);
      },
      restoreState: (state) => this.applyState(state, true),
      setScope: (spec, depth) => this.setScope(spec, depth === undefined ? undefined : { depth }),
      // VIEW-07: the host's two export commands have no geometry of their own.
      // The region it names becomes the menu's checked region, so the next
      // gesture from the toolbar continues where the command left off.
      requestExport: (kind, scope) => {
        this.exportMenu.setRegion(regionFromHostWord(scope));
        this.runExport(kind === 'png' ? 'png' : 'svg');
      },
      // VIEW-08: an optional sibling document. A malformed one is not an error
      // and not a crash — `indexOverlay` hands back null and the diagram stays
      // exactly as it was (invariant 1.1/6 over a second document).
      diffOverlay: (raw, baseLabel) => {
        const next = raw === null || raw === undefined ? null : indexOverlay(raw);
        if (raw !== null && raw !== undefined && !next) {
          this.bridge.post({ v: 1, type: 'log', level: 'warn', message: 'ignored an unreadable diff overlay' });
          return;
        }
        this.diffBaseLabel = next ? baseLabel || '' : '';
        this.setDiff(next);
      },
      onUnknown: (type) =>
        this.bridge.post({ v: 1, type: 'log', level: 'debug', message: 'ignored unknown message type: ' + type }),
    });
  }

  private applyState(state: ViewState, rerender: boolean): void {
    if (!state || typeof state !== 'object') return;
    if (state.filters) this.filters.restore(state.filters);
    if (state.railTab) this.railTab = state.railTab;
    if (Array.isArray(state.collapsed)) {
      this.collapsedState = state.collapsed.slice();
      if (this.index) this.view.setCollapsed(state.collapsed.filter((id) => this.index!.isGroup(id)));
    }
    if (state.selection) this.selection = state.selection;
    if (typeof state.minimapCollapsed === 'boolean') this.view.setMinimapCollapsed(state.minimapCollapsed);
    if (typeof state.flow === 'boolean') this.setFlow(state.flow);
    if (state.railGroupBy) this.railGroupBy = sanitizeGroupBy(state.railGroupBy);
    if (typeof state.legendOpen === 'boolean') this.setLegend(state.legendOpen);
    if (typeof state.answersOpen === 'boolean') this.answersOpen = state.answersOpen;
    // MLV-P12: the question has been answered before, so it is not asked again.
    if (state.pipelineChosen === true) this.pipelineChosen = true;
    // VIEW-08: restoring "changed only" with no overlay loaded is a NO-OP, never
    // an empty diagram — `ScopeSession.setChangedOnly` refuses without a diff,
    // and the flag is dropped rather than left standing for an overlay that may
    // never arrive.
    if (state.diffOnly === true && this.scopes.diff) this.scopes.setChangedOnly(true);
    const scope = sanitizeScope(state.scope);
    // No graph yet? The host mounts the viewer empty and restores state before
    // it posts one, so applying here would drop the scope on the floor (R2H-03).
    if (scope && this.scopes.full) this.setScope(scope.spec, { depth: scope.depth });
    else if (scope) this.pendingScope = { spec: scope.spec, depth: scope.depth };
    if (rerender && this.index) {
      this.view.relayout();
      this.renderChrome();
      this.renderRail();
      this.view.applySelection(this.selection);
    }
    if (state.viewport) this.view.viewport.set(state.viewport);
  }

  /* ── public API ────────────────────────────────────────────────────── */

  update(graph: MLGraph, preserve?: Partial<ViewState>): void {
    this.setGraph(graph, preserve);
  }

  /**
   * Re-project and relayout LOCALLY. Never posts `requestRefresh`, never touches
   * the analyzer, and never throws: an unresolvable spec is a no-op plus a toast
   * (CONTRACTS 11.8).
   */
  setScope(spec: string | null, opts?: { depth?: number }): void {
    if (!this.scopes.full) return;
    const wasScoped = this.scopes.spec !== null;
    if (!wasScoped && spec) {
      // Clearing restores the viewport and the selection from before the scope
      // was set, so [x] feels like a back button rather than a reset.
      this.preScope = { viewport: { ...this.viewportState }, selection: this.selection ? { ...this.selection } : null };
    }
    const result = this.scopes.set(spec, opts ? opts.depth : undefined);
    if (!result.ok) {
      const error = result.error;
      this.view.toast(error ? error.code + ': ' + error.term : 'That scope could not be applied');
      return;
    }
    this.afterScopeChange();
    if (!this.scopes.spec && this.preScope) {
      const back = this.preScope;
      this.preScope = null;
      // The viewport always comes back, so [x] feels like a back button. The
      // SELECTION only comes back when the user has not made a new one inside
      // the scope — clearing a scope must never throw away what they just
      // picked, and the Escape cascade's next rung is that selection.
      if (!this.selection) this.selection = back.selection;
      this.view.viewport.set(back.viewport);
      this.view.applySelection(this.selection);
      this.renderRail();
    }
    if (result.empty) this.view.toast('Nothing in this scope — ' + (spec || ''));
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
    this.syncCollapsed();
    const state: ViewState = {
      viewport: { ...this.viewportState },
      selection: this.selection ? { ...this.selection } : null,
      collapsed: this.collapsedState.slice(),
      filters: this.filters.snapshot(),
      railTab: this.railTab,
      minimapCollapsed: this.view.minimapCollapsed,
    };
    const spec = this.scopes.spec;
    if (spec) state.scope = { spec, depth: this.scopes.depth };
    if (!this.flowOn) state.flow = false;
    // Both absent at their defaults, like `scope` and `flow`: an older host
    // round-trips a state it has never seen, and a newer one restores to the
    // documented default rather than to whatever `undefined` renders as.
    if (this.railGroupBy !== 'none') state.railGroupBy = this.railGroupBy;
    if (this.legendOpen) state.legendOpen = true;
    // Absent at its default (open), exactly as `flow` is absent while on: an
    // older host round-trips a state it has never seen (CONTRACTS 11.9).
    if (!this.answersOpen) state.answersOpen = false;
    // Absent at its default (off), exactly as `flow`, `scope` and `legendOpen`
    // are: an older host round-trips a state it has never seen (11.9).
    if (this.scopes.changedOnly) state.diffOnly = true;
    // MLV-P12, and the same rule again: absent means "not asked yet".
    if (this.pipelineChosen) state.pipelineChosen = true;
    return state;
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.saveSoon.cancel();
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

/**
 * Complete an answer citation into a real `Loc` (MLV-P1).
 *
 * `emit/answers.py` writes `{file, line}` — an answer cites a place to look, not
 * a range to select — while `openLocation` is contracted to carry six fields
 * (CONTRACTS §4). The absolute path is rebuilt from `workspace.root`, which is
 * the only place the viewer can learn it, so a citation still reaches VS Code
 * instead of posting `absFile: undefined`.
 */
function completeLoc(loc: AnswerLoc, graph: MLGraph | null): Loc {
  const line = typeof loc.line === 'number' ? loc.line : 1;
  const col = typeof loc.col === 'number' ? loc.col : 0;
  const root = graph && graph.workspace ? String(graph.workspace.root || '') : '';
  const absFile = loc.absFile || (root ? root.replace(/[\\/]+$/, '') + '/' + loc.file : '');
  return {
    file: loc.file,
    absFile,
    line,
    col,
    endLine: typeof loc.endLine === 'number' ? loc.endLine : line,
    endCol: typeof loc.endCol === 'number' ? loc.endCol : col,
  };
}

function safeLoad(bridge: HostBridge): ViewState | null {
  try {
    return bridge.loadState();
  } catch (_e) {
    return null;
  }
}
