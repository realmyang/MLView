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
 *   `app/documents.ts`  the document and its collapse set
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
import { ThemeController } from './ui/theme.js';
import { SearchController } from './ui/searchcontroller.js';
import { closeComposer, composerOpen, decorateWorkflow, normalizeWorkflow, sanitizeComposer } from './workflow.js';
import { FreshnessState } from './freshness.js';
import { HostNotice } from './ui/hostnotice.js';
import { DoubleClickOpener } from './ui/doubleclick.js';
import { buildAppUi } from './app/build.js';
import { setGraph } from './app/documents.js';
import { renderChrome, renderRail } from './app/surfaces.js';
import { openLocation } from './app/actions.js';
import { onCanvasKey } from './app/keys.js';
import { onHostMessage } from './app/messages.js';
import { applyState, safeLoad, snapshotState } from './app/state.js';
import { sanitizeRailTab } from './ui/commands.js';
import { screenReaderActive } from './motion.js';
import { selectionAnnouncement } from './ui/selection.js';
import type { SearchHit } from './search.js';
import type {
  ActionResult,
  Capabilities,
  ComposerState,
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
 * Campaign 3, issue 6; viewer M2. The rail docks beside the canvas only when the canvas keeps at
 * least this width (with the default 360 px rail: panels 1260 px wide and up). Narrower, the rail
 * is a bottom sheet under the canvas instead of the drawer that covered it: a 32 px tab strip when
 * collapsed, about 47 % of the height when open.
 */
export const RAIL_MIN_CANVAS_W = 900;

/** Viewer M2: where the rail is. `docked` beside the canvas, `sheet` under it. */
export type RailMode = 'docked' | 'sheet';

/** Viewer M2: below this panel width the Selection pane in the sheet is one column, above it two. */
export const SHEET_TWO_COLUMNS_W = 620;

/** The open sheet's share of the body height: the default, and the drag handle's bounds. */
export const SHEET_FRACTION = 0.47;
export const SHEET_FRACTION_MIN = 0.25;
export const SHEET_FRACTION_MAX = 0.75;

/** Where `showAbout` lands the reader. */
export interface ShowAboutOptions {
  /** Open at the coverage limitations (the Selection pane's "limitations apply" link). */
  at?: 'limitations';
  /** Move the keyboard focus into About (a keyboard activation, or the limitations link). */
  focus?: boolean;
}

type RequestFrame = UiToHost & { requestId?: string };

export interface SelectOptions {
  /** Open the selection's cited source beside the panel (Enter, double-click). Focus stays here. */
  open?: boolean;
  /** With `open`: move focus to the editor (Alt+Enter). */
  focusEditor?: boolean;
  /**
   * A gesture on the canvas (viewer M1): the claim is shown. A docked rail the width rule closed
   * opens, unless the reader closed it; a collapsed bottom sheet opens (viewer M2). The target stays
   * in view above the sheet.
   */
  showClaim?: boolean;
  center?: boolean;
  tab?: RailTab;
  /**
   * Viewer M2 review (M2-INT-1): the selection was made from the Findings list or the Outline (a
   * row, Space, Enter, or `n` / `p` walking the findings). That list keeps its place while it is on
   * screen, with the selection marked in it. Every other selection (the canvas, search, a link in
   * the Selection pane, the host) shows the claim in the Selection tab, as in viewer M1.
   */
  fromList?: 'issues' | 'outline';
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
  /** The node `e` / Shift+E are cycling the connections of. */
  edgeAnchor: string | null = null;
  flowOn = true;
  /** Viewer M2: whether the observed claims are faded (the toolbar's "not observed" toggle). */
  exceptionsOn = false;
  caps: Capabilities;
  /* VW-05: `this.themes.kind` is the one answer to "which theme"; the app keeps no copy. */

  filters = new FilterModel();
  viewportState: Viewport = { x: 0, y: 0, zoom: 1 };
  selection: Sel | null = null;
  collapsedState: string[] = [];
  /** Viewer M2: a new revision opens on About; afterwards the reader's tab is kept (and saved). */
  railTab: RailTab = 'about';
  legendOpen = false;

  /** Viewer M1: the displayed revision's stale files, from the host's `stale` frame. */
  freshness = new FreshnessState();
  /** Whether this viewer has said once where an opened source goes. */
  openHintShown = false;
  /** Docked: whether the rail is shown. Sheet (viewer M2): whether the sheet is open, not just its tab strip. */
  railOpen = true;
  /**
   * The reader has shown or hidden the rail themselves, selected a finding
   * (which opens it) or worked inside it, so the width rule in `autoRail` no
   * longer decides.
   */
  railChosen = false;
  /**
   * Viewer M2: the reader hid the DOCKED rail (Ctrl+B or the ... menu). Collapsing the bottom sheet
   * is not hiding the rail: a panel widened back to docking width shows it again unless this is set.
   */
  dockedHidden = false;
  railWidth = 360;
  /** Viewer M2: docked beside the canvas, or a bottom sheet under it (`autoRail`). */
  railMode: RailMode = 'docked';
  /** Viewer M2: the open sheet's share of the body height (the drag handle changes it). */
  sheetFraction = SHEET_FRACTION;
  /** Viewer M2: the columns the Selection pane was last built with (`renderRail`). */
  paneColumns: 1 | 2 = 1;
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
  /** Viewer M2: the rail tab a remount restores, only for the revision it was saved with. */
  private restoredTab: { revision: string; tab: RailTab } | null = null;
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
  legend!: Legend;
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
    const tab = restored && typeof restored.workflowRevision === 'string' ? sanitizeRailTab(restored.railTab) : null;
    if (restored && tab) this.restoredTab = { revision: restored.workflowRevision as string, tab };
    this.disposers.push(bridge.onMessage((msg) => this.onMessage(msg)));
    if (typeof window !== 'undefined') this.disposers.push(on(window, 'resize', () => this.onResize()));
    // Viewer M2: Ctrl/Cmd+F and Ctrl/Cmd+K focus the search from anywhere in the viewer, not only
    // from the canvas (whose keymap answers them first and marks the event handled). Viewer M2
    // review (M2R-9): not from inside a modal surface (the shortcut sheet, the Refine… popover),
    // whose focus trap would otherwise lose the focus to a field behind it while it stays open.
    this.disposers.push(on(root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.defaultPrevented || !(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
      if (ev.key !== 'f' && ev.key !== 'F' && ev.key !== 'k' && ev.key !== 'K') return;
      if (this.modalOpen(ev.target)) return;
      ev.preventDefault();
      this.focusSearch();
    }));
    this.chrome.setWidth(this.rootWidth());
    // No `ready` here: the host bootstrap posts the one `ready` of a page load
    // and mounts this App on the first `workflow` (§1e). A second `ready`
    // would make the host replay the whole handshake and render it again.
  }

  /* ── chrome + rail ─────────────────────────────────────────────────── */

  /** The panel's width, or 0 when it cannot be measured (jsdom, a detached mount). */
  rootWidth(): number {
    const width = this.root.getBoundingClientRect().width;
    return width > 0 ? width : 0;
  }

  /** The panel was resized: the header's shape and the rail's width rule follow it. */
  private onResize(): void {
    const before = this.chrome.headerLayout;
    if (this.chrome.setWidth(this.rootWidth()) !== before) renderChrome(this);
    this.autoRail();
    // The sheet's Selection pane changes between one and two columns at 620 px.
    if (this.paneColumns !== this.selectionColumns()) renderRail(this);
  }

  /** Viewer M2: the Selection pane's columns: two in a sheet at least 620 px wide, else one. */
  selectionColumns(): 1 | 2 {
    return this.railMode === 'sheet' && this.rootWidth() >= SHEET_TWO_COLUMNS_W ? 2 : 1;
  }

  /** Viewer M2: the rail's content is on screen (docked and shown, or the sheet open). */
  railShown(): boolean {
    return this.railOpen;
  }

  /** Repaint the header and the status bar (for modules that change what they show). */
  refreshChrome(): void {
    renderChrome(this);
  }

  /**
   * Viewer M2: focus the search field from a key, the header's search icon or the ... menu. Below
   * 1000 px the field is folded behind the icon, so it is opened first.
   */
  focusSearch(): void {
    this.chrome.setSearchOpen(true);
    this.search.focus();
  }

  /**
   * Viewer M2: the About tab: the request, the model's own summary, coverage with the limitations,
   * scope, run configuration, the cited files and provenance. The provenance chip, the status bar's
   * coverage item, the ... menu and the Selection pane's limitations link open it; it replaces the
   * details panel that opened over the diagram. A docked rail the reader closed opens, and so does
   * a collapsed sheet. `focus` moves the keyboard focus into it.
   */
  showAbout(opts: ShowAboutOptions = {}): void {
    this.railTab = 'about';
    if (!this.railOpen) {
      this.railChosen = true;
      this.setRailOpen(true);
    }
    renderRail(this);
    this.saveSoon();
    const target = opts.at === 'limitations' ? this.rail.revealLimitations() : opts.focus ? this.rail.activePanel() : null;
    if (opts.focus && target) {
      try {
        target.focus();
      } catch (_e) {
        /* a host may have detached the rail already */
      }
    }
    this.announce(opts.at === 'limitations' ? 'About: the coverage limitations.' : 'About this revision shown.');
  }

  /**
   * A modal surface is open, or `target` is inside one: the `?` shortcut sheet or the Refine…
   * popover (both keep Tab inside themselves). Viewer-wide keys leave the focus where it is then.
   */
  modalOpen(target?: EventTarget | null): boolean {
    if (this.sheet && this.sheet.open) return true;
    if (composerOpen(this)) return true;
    const element = target as HTMLElement | null;
    return !!element && typeof element.closest === 'function' && !!element.closest('.mlv-sheet, .mlv-workflow__composer');
  }

  /** Escape's rung for the Refine… popover, the one panel left that opens from the header. */
  closeHeaderPanels(): boolean {
    return closeComposer(this, true);
  }

  headerPanelOpen(): boolean {
    return composerOpen(this);
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
    // Viewer M2: a new revision opens on About. The same revision keeps the reader's tab, and so
    // does a remount of the revision the tab was saved with.
    if (this.workflowRevision !== document.revision.id) {
      const restoredTab = !this.graph && this.restoredTab && this.restoredTab.revision === document.revision.id ? this.restoredTab.tab : null;
      this.railTab = restoredTab || 'about';
    }
    this.restoredTab = null;
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

  /**
   * A tab chosen in the strip. A collapsed bottom sheet opens on it (the tab strip is all of it
   * that shows); the docked rail is always on screen when its strip is.
   */
  setRailTab(tab: RailTab): void {
    this.railTab = tab;
    if (this.railMode === 'sheet' && !this.railOpen) {
      this.railChosen = true;
      this.setRailOpen(true);
    }
    renderRail(this);
    this.saveSoon();
  }

  /**
   * Viewer M2: Ctrl+1 to Ctrl+4. A rail that is not on screen (a collapsed sheet, a hidden docked
   * rail) opens on the tab asked for. In the bottom sheet the focus moves to the tab, so the reader
   * lands in the panel they asked for; the docked rail leaves the focus where it was.
   */
  showRailTab(tab: RailTab): void {
    this.railTab = tab;
    if (!this.railOpen) {
      this.railChosen = true;
      this.setRailOpen(true);
    }
    renderRail(this);
    this.saveSoon();
    if (this.railMode === 'sheet') this.rail.focusTab(tab);
  }

  toggleRail(): void {
    this.railChosen = true;
    if (this.railMode === 'docked') this.dockedHidden = this.railOpen;
    this.setRailOpen(!this.railOpen);
  }

  /**
   * Viewer M2: Escape's rung for the open sheet, and the sheet's own Escape. The sheet collapses to
   * its tab strip; with `restoreFocus` (the sheet's own Escape, pressed inside it) the canvas takes
   * the focus back. False when there was no open sheet.
   */
  collapseSheet(restoreFocus = false): boolean {
    if (this.railMode !== 'sheet' || !this.railOpen) return false;
    this.railChosen = true;
    this.setRailOpen(false);
    this.announce('Bottom panel collapsed.');
    if (restoreFocus) {
      try {
        this.view.canvasEl.focus();
      } catch (_e) {
        /* the canvas may already be torn down */
      }
    }
    return true;
  }

  /**
   * Viewer M2 review (M2R-10): the largest share of the body the open sheet can take. The
   * stylesheet keeps the canvas at least `min(240px, 45%)` tall, so on a short panel the cap is
   * under SHEET_FRACTION_MAX (0.68 at 541x798); an unmeasurable body keeps SHEET_FRACTION_MAX.
   */
  sheetFractionMax(): number {
    const body = this.root.querySelector('.mlv-body');
    const height = body ? body.getBoundingClientRect().height : 0;
    if (!(height > 0)) return SHEET_FRACTION_MAX;
    const floor = Math.min(240, 0.45 * height);
    return Math.max(SHEET_FRACTION_MIN, Math.min(SHEET_FRACTION_MAX, (height - floor) / height));
  }

  /** Viewer M2: the drag handle (or its arrow keys) sets the open sheet's height. */
  setSheetFraction(fraction: number): void {
    const next = Math.max(SHEET_FRACTION_MIN, Math.min(this.sheetFractionMax(), fraction));
    if (Math.abs(next - this.sheetFraction) < 0.001) return;
    this.sheetFraction = next;
    this.rail.setSheetFraction(next);
    if (this.railMode === 'sheet' && this.railOpen && this.graph) this.view.afterSheetToggle();
  }

  /**
   * Campaign 3, issue 6; viewer M2. MEASURED live: the docked rail took 360 of a 1086 or 1382 px
   * panel, and the drawer that replaced it below 900 px covered 86 % of the canvas at the default
   * 541 px. The rail docks only when the canvas beside it keeps RAIL_MIN_CANVAS_W; narrower, it is
   * a bottom sheet under the canvas. Docked, it is shown until the reader hides it. The sheet starts
   * as its tab strip and opens on a selection; a rail the reader was using stays open when the panel
   * narrows into a sheet. An unmeasurable root (jsdom, a detached mount) leaves it docked and shown.
   */
  autoRail(): void {
    const width = this.root.getBoundingClientRect().width;
    if (!(width > 0)) return;
    const mode: RailMode = width - this.railWidth >= RAIL_MIN_CANVAS_W ? 'docked' : 'sheet';
    let open = this.railOpen;
    if (mode !== this.railMode) open = mode === 'sheet' ? this.railOpen && this.railChosen : !this.dockedHidden;
    else if (mode === 'docked' && !this.railChosen) open = true;
    if (mode === this.railMode && open === this.railOpen) return;
    const modeChanged = mode !== this.railMode;
    this.railMode = mode;
    this.rail.setMode(mode, this.sheetFraction);
    this.setRailOpen(open, true);
    if (modeChanged) {
      // Back beside the canvas the rail takes its docked width again; the menu names the mode.
      if (mode === 'docked') this.setRailWidth(this.railWidth);
      renderRail(this);
      renderChrome(this);
    }
    // The canvas changed size; a viewport nobody moved refits now rather than waiting for the
    // host's ResizeObserver (none in jsdom), and a selected target in view stays in view.
    if (this.graph) this.view.handleResize();
  }

  /**
   * Viewer M2: tell the legend which connection kinds this diagram uses, as the author wrote
   * them, since the line style no longer shows the kind. Most used first.
   */
  private legendOtherKinds(): void {
    const kinds = new Map<string, number>();
    let unspecified = 0;
    for (const edge of this.graph?.edges || []) {
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
  private showRailForFinding(): boolean {
    this.railChosen = true;
    if (this.railOpen) return false;
    this.setRailOpen(true);
    return true;
  }

  /**
   * Show or hide the docked rail, or open or collapse the sheet. A sheet toggle changes the canvas
   * height, which must not refit the diagram (the reader is reading a card); the canvas keeps a
   * selected target in view above the sheet instead (`CanvasView.afterSheetToggle`). `quiet` is the
   * width rule's own call, which re-lays the canvas itself.
   */
  setRailOpen(open: boolean, quiet = false): void {
    const changed = this.railOpen !== open;
    this.railOpen = open;
    // A docked rail shown again, by any route, is no longer one the reader hid.
    if (open && this.railMode === 'docked') this.dockedHidden = false;
    this.rail.setOpen(open);
    if (!changed) return;
    // The ... menu's rail item says whether it is shown.
    if (this.chrome) renderChrome(this);
    // Only the visible tab is built: one that opens now is built for the first time.
    if (open && this.rail) renderRail(this);
    if (!quiet && this.railMode === 'sheet' && this.graph) this.view.afterSheetToggle();
  }

  /**
   * The `?` shortcut sheet, a modal dialog (viewer M2: it keeps Tab inside itself). Closing gives
   * the focus back to whatever had it when the sheet opened, or to the canvas.
   */
  toggleShortcuts(next?: boolean): void {
    const show = typeof next === 'boolean' ? next : !this.sheet.open;
    if (show) {
      this.sheet.show();
      return;
    }
    this.sheet.hide(this.view.canvasEl);
  }

  setRailWidth(width: number): void {
    // Viewer M2: docked, the rail never leaves the canvas under RAIL_MIN_CANVAS_W; it would turn
    // into the sheet under the pointer that is dragging it.
    // A panel too narrow to dock the rail at all (the sheet, or before the first width rule) does
    // not clamp the width it will dock at.
    const panel = this.rootWidth();
    const room = this.railMode === 'docked' && panel - RAIL_MIN_CANVAS_W >= 280 ? panel - RAIL_MIN_CANVAS_W : 560;
    this.railWidth = Math.max(280, Math.min(560, room, Math.round(width)));
    // The sheet spans the panel; the width waits for the rail to dock again.
    if (this.railMode === 'docked') this.rail.root.style.width = this.railWidth + 'px';
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
    // Viewer M2: a selection shows its claim in the Selection tab, unless it was made from the
    // Findings list or the Outline on screen (a list the reader is walking keeps its place).
    this.railTab = opts && opts.tab ? opts.tab : this.selectionTab(opts && opts.fromList);
    let openedRail = false;
    if (sel.kind === 'issue') openedRail = this.showRailForFinding();
    if (opts && opts.showClaim) openedRail = this.showRailForClaim() || openedRail;
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
   * Viewer M1: a click shows the claim, which lives in the rail. A docked rail the width rule
   * closed opens (true); one the reader closed stays closed (they have the hover card and Ctrl+B).
   * Viewer M2: a collapsed bottom sheet opens on every such selection; Escape collapses it again.
   */
  private showRailForClaim(): boolean {
    // Viewer M2 review (M2R-5): a claim shown in the open rail means the reader is using it, so the
    // width rule keeps it open when the panel narrows into the bottom sheet (Enter opening the
    // source beside it is what narrows the panel).
    if (this.railOpen) {
      this.railChosen = true;
      return false;
    }
    if (this.railMode === 'docked' && this.railChosen) return false;
    this.railChosen = true;
    this.setRailOpen(true);
    return true;
  }

  /**
   * Viewer M2: the tab a new selection shows. The Selection tab, unless the selection was made from
   * the Findings list or the Outline while that list is the tab on screen: then the list keeps its
   * place and marks the selection (a finding expands in the Findings list).
   */
  private selectionTab(fromList?: 'issues' | 'outline'): RailTab {
    return fromList && this.railTab === fromList && this.railShown() ? fromList : 'inspector';
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
    // Viewer M2: with VS Code's screen-reader optimisation on (the `vscode-using-screen-reader`
    // body class) the announcement leads with the claim: its title, its basis when it is not
    // observed, and the first sentence of what the author wrote.
    if (screenReaderActive()) {
      const text = selectionAnnouncement(this.index, sel);
      if (text) this.announce(text);
      return;
    }
    if (sel.kind === 'node') {
      const label = this.view.labelOf(sel.id);
      if (label) this.announce('Selected ' + label);
    } else if (sel.kind === 'issue') {
      const issue = this.index.issueById.get(sel.id);
      // Viewer M2 review (A11Y-10): the F label the badge and the list print first, the real id after.
      if (issue) this.announce('Finding ' + (issue.short ? issue.short + ' (' + issue.code + ')' : issue.code) + ', ' + issue.severity + ' severity: ' + issue.title);
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

  clearFilters(): void {
    this.search.clear();
    this.applyFilters(() => this.filters.reset());
  }

  /** The Outline's lane rows are a jump target: land on the stage's first node. */
  selectLane(laneId: string): void {
    if (!this.index) return;
    const roots = this.index.roots(laneId);
    if (!roots.length) {
      this.announce('That phase has no steps.');
      return;
    }
    this.select({ kind: 'node', id: roots[0] }, { center: true, pulse: true, fromList: 'outline' });
  }

  zoomToSelection(): void {
    const id = this.selectedNodeId();
    if (id) this.view.zoomToNode(id);
  }

  announce(text: string): void {
    this.liveEl.textContent = text;
  }

  /**
   * A search result was chosen. Viewer M2 review (M2R-3): it shows the claim, as a canvas click
   * does: the Selection tab, and a collapsed bottom sheet opens (a finding opens the rail anyway).
   */
  activateHit(hit: SearchHit): void {
    if (hit.kind === 'node') this.focusNode(hit.id, { center: true, pulse: true, showClaim: true });
    else this.focusIssue(hit.id);
  }

  onKeyDown(ev: KeyboardEvent): void {
    onCanvasKey(this, ev);
  }

  private onMessage(msg: HostToUi): void {
    onHostMessage(this, msg);
  }

  /* ── public API ────────────────────────────────────────────────────── */

  focusNode(id: string, opts?: { center?: boolean; pulse?: boolean; showClaim?: boolean }): void {
    if (!this.index) return;
    if (!this.index.nodeById.has(id)) {
      this.view.toast('Node not found in this graph');
      return;
    }
    this.view.expandAncestors(id);
    this.select(
      { kind: 'node', id },
      { center: opts ? opts.center !== false : true, pulse: opts ? !!opts.pulse : false, showClaim: !!(opts && opts.showClaim) },
    );
  }

  /** Select a finding and frame what it cites. `fromList`: chosen in the Findings list, or walked with `n` / `p`. */
  focusIssue(id: string, opts?: { fromList?: 'issues' }): void {
    if (!this.index) return;
    const issue = this.index.issueById.get(id);
    if (!issue) return;
    for (const nodeId of issue.nodeIds) this.view.expandAncestors(nodeId);
    this.select({ kind: 'issue', id }, { fromList: opts && opts.fromList });
    // Issue 6; viewer M2: the canvas frames EVERY step the finding cites (and the ends of the
    // connections it cites), zooming to READABLE_ZOOM below the detail threshold, so a finding on
    // three steps no longer shows only the first.
    this.view.frameIssue(id);
  }

  /** Viewer M1: Enter (or a double-click) on a finding row selects it and opens its first cited range. */
  openIssue(id: string, focusEditor = false): void {
    this.focusIssue(id, { fromList: 'issues' });
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
    this.view.destroy();
    this.releasePage();
    clear(this.root);
    this.root.classList.remove('mlv-root');
  }
}
