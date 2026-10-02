/**
 * The viewer's shell, built once: every panel the App owns, in the order the
 * document has to carry them.
 *
 * It is one function because the ORDER is the contract — the canvas has to stay
 * within four Tab presses of the top of the document (VIEW-12), the legend is anchored
 * inside the canvas over the phase index's corner (VIEW-10), and the overlays go on the app
 * root so they are never inside the world layer that pans and zooms. Reading
 * those decisions together is the point of keeping them in one place.
 *
 * `canvasHost()` lives here too: it is the other half of the same wiring — what
 * the canvas is allowed to ask of the application (`canvas/host.ts`).
 */

import { on } from '../dom.js';
import { CanvasView } from '../canvasview.js';
import { Chrome } from '../ui/chrome.js';
import { Rail } from '../ui/rail.js';
import { Legend } from '../ui/legend.js';
import { buildShell, claimPage } from '../ui/shell.js';
import { ShortcutSheet } from '../ui/shortcuts.js';
import { SearchController } from '../ui/searchcontroller.js';
import { HostNotice } from '../ui/hostnotice.js';
import { WalkBar } from '../ui/walkbar.js';
import { runExport } from './exporting.js';
import { renderChrome, renderRail } from './surfaces.js';
import { syncCollapsed } from './documents.js';
import type { CanvasHost } from '../canvas/host.js';
import type { App } from '../app.js';

/** Build the shell, every panel, and the canvas; then mount them on the root. */
export function buildAppUi(app: App): void {
  const shell = buildShell(app.root, app.themes.kind);
  app.releasePage = claimPage(app.root);
  app.liveEl = shell.live;
  app.view = new CanvasView(shell, canvasHost(app));

  // Viewer M2: ONE header row (title, provenance, search, severity, not observed, ..., Refine…)
  // and a status bar. Every control the old toolbar carried is in the header or its ... menu.
  app.chrome = new Chrome({
    onQuery: (q) => app.search.run(q),
    onSearchKey: (ev) => app.search.handleKey(ev),
    onSearchOpen: () => app.focusSearch(),
    onSeverity: (sev) => app.applyFilters(() => app.filters.toggleSeverity(sev)),
    onToggleExceptions: (next) => app.setExceptions(next),
    // Viewer M2: the provenance chip, the status bar's coverage item and the ... menu open About. A
    // keyboard activation (a click with no pointer detail) also moves the focus into it.
    onAbout: (byKeyboard) => app.showAbout({ focus: byKeyboard }),
    onZoom: (dir) => app.view.zoomStep(dir),
    onToggleLegend: (next) => app.setLegend(next),
    onToggleFlow: (next) => app.setFlow(next),
    onTogglePhaseIndex: (shown) => app.setPhaseIndexShown(shown),
    // Viewer M3: the ... menu's Phase overview, as Shift+0 (it closes an open one).
    onOverview: () => app.toggleOverview(true),
    onToggleRail: () => app.toggleRail(),
    onFitWhole: () => app.view.fitWhole(),
    onZoomToSelection: () => app.zoomToSelection(),
    onExport: (action) => runExport(app, action),
    onShortcuts: () => app.toggleShortcuts(true),
    // The menu reads the state as it opens (the selection changes without a chrome repaint).
    onMenuOpen: () => renderChrome(app),
    // Viewer M3: the header's Review button and the ... menu's item start or end the walk. A walk
    // they start gives the keyboard to the diagram, as "Review affected claims" does, so j and k
    // step at once instead of reaching a header button (M3 review, A11Y-M3-1). The menu has
    // already closed (and handed the focus back to its trigger) when this runs.
    onReview: () => {
      const wasActive = app.walk.active;
      app.walk.toggle();
      if (!wasActive && app.walk.active) focusCanvas(app);
    },
  }, shell.zoomBar);

  // The header is the first thing after the skip link; the ... menu's panel goes on the app root,
  // so the header's roving toolbar (VIEW-12) keeps its single tab stop.
  app.root.appendChild(app.chrome.header);
  // Viewer M3: the review walk's bar, shown only while the walk runs. It goes at the foot of the
  // diagram column, after the canvas in the document: directly above the bottom sheet's tabs (or,
  // with the side panel, along the bottom of the diagram). So the canvas keeps its place within
  // four Tab presses of the top, and Tab from the canvas reaches the walk's controls, then the
  // claim in the sheet.
  app.walkBar = new WalkBar({
    onFilter: (filter) => app.walk.setFilter(filter),
    // Previous and Next: as k and j. The focus stays on the button, so it can be pressed again.
    onStep: (delta) => {
      app.walk.step(delta);
    },
    onExit: () => {
      app.walk.stop();
      focusCanvas(app);
    },
    onKey: (ev) => {
      const key = ev.key;
      if (key === 'j' || key === 'J') return app.walk.step(1);
      if (key === 'k' || key === 'K') return app.walk.step(-1);
      if (key === ']') return app.walk.stepQuote(1);
      if (key === '[') return app.walk.stepQuote(-1);
      if (key === 'u' || key === 'U') return app.walk.jump('notObserved', ev.shiftKey);
      if (key === 'n' || key === 'N' || key === 'p' || key === 'P') return app.walk.jump('findings', key === 'p' || key === 'P');
      return false;
    },
  });
  // Viewer M1: the host's banner after the mount (stale files, the root hint, a refused update).
  // It moves under the header when it is first shown (App.showHostNotice).
  app.notice = new HostNotice({
    onWorkspaceHint: (action) => app.bridge.post({ v: 1, type: 'workspaceHint', action }),
    // Viewer M3: the stale notice's "Review affected claims" walks the claims that cite those files.
    onReviewAffected: () => {
      if (app.walk.start('changed')) focusCanvas(app);
    },
  });
  app.root.appendChild(app.notice.root);
  app.root.appendChild(shell.body);
  shell.body.appendChild(shell.main);
  shell.main.appendChild(app.walkBar.root);

  app.search = new SearchController(app.chrome.searchInput, app.chrome.results, {
    index: () => app.index,
    activate: (hit) => app.activateHit(hit),
    onQueryChanged: (query) => {
      app.filters.patch({ query });
      app.saveSoon();
    },
    blurToCanvas: () => app.view.canvasEl.focus(),
  });

  app.rail = new Rail({
    onTab: (tab) => app.setRailTab(tab),
    onClearFilters: () => app.clearFilters(),
    // Viewer M1 review (M1-R1): a row click arms the double-click opener. The click rebuilds the
    // rows (and can collapse an expanded finding above), so the second click may land on a
    // detached or different row; the opener opens the row the first click selected.
    onSelectIssue: (id, ev) => {
      app.focusIssue(id, { fromList: 'issues' });
      app.doubleClick.arm(ev, () => app.openIssue(id, false));
    },
    onOpenIssue: (id, focusEditor) => app.openIssue(id, focusEditor),
    // The Outline's rows keep the Outline on screen (viewer M2 review, M2-INT-1).
    onSelectNode: (id, ev) => {
      app.select({ kind: 'node', id }, { center: true, reveal: true, fromList: 'outline' });
      app.doubleClick.arm(ev, () => app.select({ kind: 'node', id }, { center: true, reveal: true, open: true, fromList: 'outline' }));
    },
    onOpenNode: (id, focusEditor) => app.select({ kind: 'node', id }, { center: true, reveal: true, open: true, focusEditor, fromList: 'outline' }),
    onSelectEdge: (id) => app.select({ kind: 'edge', id }, { reveal: true, fromList: 'outline' }),
    // Viewer M2: the Selection pane's links to a cited step, a connection's ends, a finding.
    onShowNode: (id) => app.focusNode(id, { center: true, pulse: true }),
    onShowEdge: (id) => app.select({ kind: 'edge', id }, { reveal: true }),
    onShowIssue: (id) => app.focusIssue(id),
    onChallenge: () => openComposer(app, 'challenge'),
    onRefine: () => openComposer(app, null),
    // Viewer M3: an Open link of the claim the walk is on opens it as the walk's quote.
    onOpen: (loc, focusEditor) => {
      if (!app.walk.openQuote(loc, !!focusEditor)) app.openLocation(loc, focusEditor);
    },
    onResize: (w) => app.setRailWidth(w),
    onSelectLane: (laneId) => app.selectLane(laneId),
    onToggleCollapse: (id) => {
      if (app.index && app.index.isGroup(id)) app.view.toggleCollapse(id);
    },
    onShowLimitations: () => app.showAbout({ at: 'limitations', focus: true }),
    onSheetToggle: () => app.toggleRail(),
    // Viewer M3: Escape inside the open sheet ends a running walk first (one Escape always ends it)
    // and gives the focus back to the diagram; otherwise it collapses the sheet, as in M2.
    onSheetCollapse: () => {
      if (app.walk.stop()) focusCanvas(app);
      else app.collapseSheet(true);
    },
    onSheetResize: (fraction) => app.setSheetFraction(fraction),
    sheetFraction: () => app.sheetFraction,
    sheetFractionMax: () => app.sheetFractionMax(),
    bodyHeight: () => shell.body.getBoundingClientRect().height,
  });
  // Viewer M2: after the canvas in the document, so the canvas stays within the header's tab
  // stops and the sheet comes after it.
  shell.body.appendChild(app.rail.root);
  // Campaign 3, issue 6: a reader working IN the rail has chosen it. Following
  // an evidence link opens the source in a split that narrows this panel, and
  // the width rule (`App.autoRail`) must not then close the finding being read.
  on(app.rail.root, 'pointerdown', () => { app.railChosen = true; });
  on(app.rail.root, 'keydown', () => { app.railChosen = true; });

  // Anchored inside the canvas, over the phase index's corner, so the key sits with the
  // picture it explains rather than in a modal over it (VIEW-10).
  app.legend = new Legend((open) => app.setLegend(open));
  shell.canvas.appendChild(app.legend.root);

  app.sheet = new ShortcutSheet(() => app.toggleShortcuts(false));
  app.root.appendChild(app.sheet.root);
  app.root.appendChild(app.chrome.more.panel);

  app.root.appendChild(app.chrome.status);
  app.root.appendChild(app.liveEl);
  app.setRailWidth(app.railWidth);
  app.setRailOpen(app.railOpen);
}

/** Give the keyboard back to the diagram. */
function focusCanvas(app: App): void {
  try {
    app.view.canvasEl.focus();
  } catch (_e) {
    /* the canvas may already be torn down */
  }
}

/** What the canvas is allowed to ask of the application. */
export function canvasHost(app: App): CanvasHost {
  const openNode = (id: string, focusEditor: boolean) =>
    app.select({ kind: 'node', id }, { showClaim: true, open: true, focusEditor });
  const openEdge = (id: string, focusEditor: boolean) =>
    app.select({ kind: 'edge', id }, { showClaim: true, open: true, focusEditor });
  return {
    keep: app.filters.keep,
    // Viewer M1: a click selects and shows the claim (viewer M2 review, M2-INT-1: in the Selection
    // tab, whichever tab was on show); Enter and a double-click open the cited
    // source beside the panel with focus kept here; Alt+Enter moves focus to the editor. The
    // click arms the double-click opener, so the second click opens even when the first one
    // moved the card (a rail opening, a refit) or put the bottom sheet under the pointer.
    activateNode: (id, ev) => {
      app.select({ kind: 'node', id }, { showClaim: true });
      app.doubleClick.arm(ev, () => openNode(id, false));
    },
    activateEdge: (id, ev) => {
      app.select({ kind: 'edge', id }, { showClaim: true });
      app.doubleClick.arm(ev, () => openEdge(id, false));
    },
    openNode,
    openEdge,
    clearFilters: () => app.clearFilters(),
    announce: (text) => app.announce(text),
    afterCollapse: () => {
      syncCollapsed(app);
      app.view.applySelection(app.selection);
      renderRail(app);
      app.saveSoon();
    },
    onViewportChange: (vp) => {
      app.viewportState = { x: vp.x, y: vp.y, zoom: vp.zoom };
      app.saveSoon();
    },
    onPhaseIndexChanged: () => {
      // Viewer M3: the phase index's fold chevron; the ... menu and the saved state follow it.
      renderChrome(app);
      app.saveSoon();
    },
    onKeyDown: (ev) => app.onKeyDown(ev),
    onBackgroundClick: () => app.clearSelection(),
    keptTarget: () => {
      const sel = app.selection;
      if (!sel) return null;
      if (sel.kind !== 'issue') return { kind: sel.kind, id: sel.id };
      const issue = app.index ? app.index.issueById.get(sel.id) : undefined;
      if (!issue) return null;
      if (issue.nodeIds[0]) return { kind: 'node', id: issue.nodeIds[0] };
      return issue.edgeIds.length ? { kind: 'edge', id: issue.edgeIds[0] } : null;
    },
  };
}

/**
 * Open the Refine… popover for the current selection: Challenge (the Selection pane's "Challenge
 * this claim") or the intent it last had (its Refine… button). An open popover is closed and
 * opened again, so it captures this selection rather than an older one.
 */
function openComposer(app: App, intent: 'challenge' | null): void {
  const refine = app.root.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
  const composer = app.root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
  const select = app.root.querySelector<HTMLSelectElement>('.mlv-workflow__intent');
  if (!refine || !composer || !select) return;
  if (!composer.hidden) refine.click();
  refine.click();
  if (!intent) return;
  select.value = intent;
  select.dispatchEvent(new Event('change', { bubbles: true }));
}
