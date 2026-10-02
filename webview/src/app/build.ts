/**
 * The viewer's shell, built once: every panel the App owns, in the order the
 * document has to carry them.
 *
 * It is one function because the ORDER is the contract — the canvas has to stay
 * within four Tab presses of the top of the document (VIEW-12), the legend is anchored
 * inside the canvas beside the minimap (VIEW-10), and the overlays go on the app
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
import { detailsOpen, revealWorkflowLimitations, setDetailsOpen } from '../workflow.js';
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
  app.scrim = shell.scrim;
  on(app.scrim, 'click', () => app.toggleRail());
  app.view = new CanvasView(shell, canvasHost(app));

  // Viewer M2: ONE header row (title, provenance, search, severity, not observed, ..., Refine…)
  // and a status bar. Every control the old toolbar carried is in the header or its ... menu.
  app.chrome = new Chrome({
    onQuery: (q) => app.search.run(q),
    onSearchKey: (ev) => app.search.handleKey(ev),
    onSearchOpen: () => app.focusSearch(),
    onSeverity: (sev) => app.applyFilters(() => app.filters.toggleSeverity(sev)),
    onToggleExceptions: (next) => app.setExceptions(next),
    onDetails: () => app.toggleDetails(),
    onZoom: (dir) => app.view.zoomStep(dir),
    onToggleLegend: (next) => app.setLegend(next),
    onToggleFlow: (next) => app.setFlow(next),
    onToggleMinimap: (collapsed) => app.setMinimapCollapsed(collapsed),
    onToggleRail: () => app.toggleRail(),
    onFitWhole: () => app.view.fitWhole(),
    onZoomToSelection: () => app.zoomToSelection(),
    onExport: (action) => runExport(app, action),
    onShortcuts: () => app.toggleShortcuts(true),
    // The menu reads the state as it opens (the selection changes without a chrome repaint).
    onMenuOpen: () => renderChrome(app),
  }, shell.zoomBar);

  // The header is the first thing after the skip link; the ... menu's panel goes on the app root,
  // so the header's roving toolbar (VIEW-12) keeps its single tab stop.
  app.root.appendChild(app.chrome.header);
  // Viewer M1: the host's banner after the mount (stale files, the root hint, a refused update).
  // It moves under the header when it is first shown (App.showHostNotice).
  app.notice = new HostNotice({ onWorkspaceHint: (action) => app.bridge.post({ v: 1, type: 'workspaceHint', action }) });
  app.root.appendChild(app.notice.root);
  app.root.appendChild(shell.body);
  shell.body.appendChild(shell.main);

  // The request and coverage details open over the diagram; a press anywhere else closes them,
  // except on the controls that open them (they toggle).
  if (typeof document !== 'undefined') {
    const openers = '.mlv-workflow__details, .mlv-header__prov, .mlv-status__coverage, .mlv-moremenu, .mlv-insp__limits-show';
    const off = on(document, 'pointerdown', (ev: PointerEvent) => {
      if (!detailsOpen(app)) return;
      const target = ev.target as HTMLElement | null;
      if (target && typeof target.closest === 'function' && target.closest(openers)) return;
      setDetailsOpen(app, false);
    });
    app.releasePage = chain(app.releasePage, off);
  }

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
      app.focusIssue(id);
      app.doubleClick.arm(ev, () => app.openIssue(id, false));
    },
    onOpenIssue: (id, focusEditor) => app.openIssue(id, focusEditor),
    onSelectNode: (id, ev) => {
      app.select({ kind: 'node', id }, { center: true, reveal: true });
      app.doubleClick.arm(ev, () => app.select({ kind: 'node', id }, { center: true, reveal: true, open: true }));
    },
    onOpenNode: (id, focusEditor) => app.select({ kind: 'node', id }, { center: true, reveal: true, open: true, focusEditor }),
    onSelectEdge: (id) => app.select({ kind: 'edge', id }, { tab: 'inspector', reveal: true }),
    onChallenge: () => {
      const refine = app.root.querySelector<HTMLButtonElement>('.mlv-workflow__refine');
      const composer = app.root.querySelector<HTMLFormElement>('.mlv-workflow__composer');
      const intent = app.root.querySelector<HTMLSelectElement>('.mlv-workflow__intent');
      if (!refine || !composer || !intent) return;
      // Reopen to capture this selection even if an older composer is visible.
      if (!composer.hidden) refine.click();
      refine.click();
      intent.value = 'challenge';
      intent.dispatchEvent(new Event('change', { bubbles: true }));
    },
    onOpen: (loc, focusEditor) => app.openLocation(loc, focusEditor),
    onResize: (w) => app.setRailWidth(w),
    onToggleRail: () => app.toggleRail(),
    onSelectLane: (laneId) => app.selectLane(laneId),
    onToggleCollapse: (id) => {
      if (app.index && app.index.isGroup(id)) app.view.toggleCollapse(id);
    },
    onShowLimitations: () => { revealWorkflowLimitations(app); },
  });
  shell.body.appendChild(app.rail.root);
  // Campaign 3, issue 6: a reader working IN the rail has chosen it. Following
  // an evidence link opens the source in a split that narrows this panel, and
  // the width rule (`App.autoRail`) must not then close the finding being read.
  on(app.rail.root, 'pointerdown', () => { app.railChosen = true; });
  on(app.rail.root, 'keydown', () => { app.railChosen = true; });

  // Anchored inside the canvas, beside the minimap, so the key sits with the
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

/** What the canvas is allowed to ask of the application. */
export function canvasHost(app: App): CanvasHost {
  const openNode = (id: string, focusEditor: boolean) =>
    app.select({ kind: 'node', id }, { tab: 'inspector', showClaim: true, open: true, focusEditor });
  const openEdge = (id: string, focusEditor: boolean) =>
    app.select({ kind: 'edge', id }, { tab: 'inspector', showClaim: true, open: true, focusEditor });
  return {
    keep: app.filters.keep,
    isFilteredOut: (node) => app.filters.hidesNode(node),
    // Viewer M1: a click selects and shows the claim; Enter and a double-click open the cited
    // source beside the panel with focus kept here; Alt+Enter moves focus to the editor. The
    // click arms the double-click opener, so the second click opens even when the first one
    // moved the card (a rail opening, a refit) or put the drawer under the pointer.
    activateNode: (id, ev) => {
      app.select({ kind: 'node', id }, { tab: 'inspector', showClaim: true });
      app.doubleClick.arm(ev, () => openNode(id, false));
    },
    activateEdge: (id, ev) => {
      app.select({ kind: 'edge', id }, { tab: 'inspector', showClaim: true });
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
    onMinimapCollapsed: () => {
      // The toolbar carries the accessible copy of this toggle (VIEW-12), so
      // the pointer affordance inside the panel has to keep it in step.
      renderChrome(app);
      app.saveSoon();
    },
    onKeyDown: (ev) => app.onKeyDown(ev),
    onBackgroundClick: () => app.clearSelection(),
    coveredRight: () => railOverlap(app),
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
 * How many pixels of the canvas's right side the open rail covers (Campaign 3 review, VL-1).
 * Measured rather than inferred from the 900 px breakpoint: docked, the rail's left edge is the
 * canvas's right edge; as the narrow-window drawer it lies over the canvas.
 */
function railOverlap(app: App): number {
  if (!app.railOpen || !app.view || !app.rail || app.rail.root.hidden) return 0;
  const canvas = app.view.canvasEl.getBoundingClientRect();
  const rail = app.rail.root.getBoundingClientRect();
  if (!(rail.width > 0) || !(canvas.width > 0)) return 0;
  if (rail.left >= canvas.right - 1 || rail.right <= canvas.left || rail.bottom <= canvas.top || rail.top >= canvas.bottom) return 0;
  return Math.max(0, canvas.right - Math.max(canvas.left, rail.left));
}

/** Two disposers as one. */
function chain(first: () => void, second: () => void): () => void {
  return () => {
    first();
    second();
  };
}
