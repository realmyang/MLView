/**
 * The viewer's shell, built once: every panel the App owns, in the order the
 * document has to carry them.
 *
 * It is one function because the ORDER is the contract — the canvas has to stay
 * within four Tab presses of the top of the document (VIEW-12), the answer card
 * is appended after the canvas and lifted by `order: -1`, the legend is anchored
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
import { AnswersCard } from '../ui/answers.js';
import { LoadingState } from '../ui/states.js';
import { buildShell, claimPage } from '../ui/shell.js';
import { ShortcutSheet } from '../ui/shortcuts.js';
import { ExportMenu } from '../ui/exportmenu.js';
import { SearchController } from '../ui/searchcontroller.js';
import { ScopeBar } from '../ui/scopebar.js';
import { PipelineChooser } from '../ui/pipelinechooser.js';
import { DiffBar } from '../ui/diffbar.js';
import { runExport } from './exporting.js';
import { renderChrome, renderRail } from './surfaces.js';
import {
  answerPipelineChooser,
  setChangedOnly,
  setDiff,
  stepDepth,
  syncCollapsed,
  toggleScopePicker,
} from './documents.js';
import type { CanvasHost } from '../canvas/host.js';
import type { App } from '../app.js';
import type { AnswerLoc, Loc, MLGraph } from '../types.js';

/** Build the shell, every panel, and the canvas; then mount them on the root. */
export function buildAppUi(app: App): void {
  const shell = buildShell(app.root, app.themes.kind);
  app.releasePage = claimPage(app.root);
  app.liveEl = shell.live;
  app.scrim = shell.scrim;
  on(app.scrim, 'click', () => app.toggleRail());
  app.view = new CanvasView(shell, canvasHost(app));

  app.chrome = new Chrome({
    onRefresh: () => undefined,
    onQuery: (q) => app.search.run(q),
    onSearchKey: (ev) => app.search.handleKey(ev),
    onToggleRail: () => app.toggleRail(),
    onSeverity: (sev) => app.applyFilters(() => app.filters.toggleSeverity(sev)),
    onShowSuppressed: (next) => app.setFilters({ showSuppressed: next }),
    onFit: () => app.view.fit(),
    onZoom: (dir) => app.view.zoomStep(dir),
    onStage: (stageId) => app.toggleStage(stageId),
    onClearFilters: () => app.clearFilters(),
    onZoomToSelection: () => app.zoomToSelection(),
    onAction: (id) => app.onAction(id),
    onDismiss: (key) => {
      app.dismissed.add(key);
      renderChrome(app);
    },
    onScope: () => toggleScopePicker(app),
    onToggleFlow: (next) => app.setFlow(next),
    onToggleLegend: (next) => app.setLegend(next),
    onToggleMinimap: (next) => app.setMinimapCollapsed(next),
    onChangedOnly: (next) => app.setFilters({ changedOnly: next }),
  });

  app.scopeBar = new ScopeBar({
    onPick: (spec, depth) => {
      app.setScope(spec, depth === undefined ? undefined : { depth });
      app.scopeBar.closePicker();
    },
    onClear: () => app.setScope(null),
    onDepth: (delta) => stepDepth(app, delta),
    onCopy: (spec) => {
      app.bridge.post({ v: 1, type: 'copy', text: spec });
      app.view.toast('Scope copied: ' + spec);
    },
  });
  app.chrome.scopeSlot.appendChild(app.scopeBar.breadcrumb.root);

  // VIEW-08. Its own band under the chip row: the headline is the first thing
  // a reviewer reads, and it must not compete with the toolbar for width.
  app.diffBar = new DiffBar({
    onChangedOnly: (next) => setChangedOnly(app, next),
    onDismiss: () => setDiff(app, null),
  });

  // VIEW-07. The trigger goes in the toolbar beside Fit; the popup goes on the
  // app root, so the roving toolbar (VIEW-12) keeps its single tab stop.
  app.exportMenu = new ExportMenu({
    onRegion: () => undefined,
    onAction: (action) => runExport(app, action),
  });
  app.chrome.exportSlot.appendChild(app.exportMenu.button);

  // One roving `role="toolbar"` over the toolbar row and the stage-filter row
  // (VIEW-12), so the whole control strip is a single tab stop.
  app.root.appendChild(app.chrome.bar);
  // HOSTS-UX-CHIPWALL: the chip row is the third row INSIDE `chrome.bar` now,
  // so its one disclosure control lives in the roving toolbar and costs the
  // path to the canvas nothing (VIEW-12). Same pixels, same order.
  app.root.appendChild(app.diffBar.root);
  app.root.appendChild(app.chrome.banners);
  app.root.appendChild(shell.body);
  shell.body.appendChild(shell.main);

  // MLV-P1. Appended AFTER the canvas and lifted above it by `order: -1`
  // (styles/chrome.css): the canvas has to stay within four Tab presses of the
  // top of the document (VIEW-12), and a card with five controls in front of
  // it would put it at nine.
  app.answers = new AnswersCard({
    onToggle: (open) => app.setAnswersOpen(open),
    onOpen: (loc) => app.openLocation(completeLoc(loc, app.graph)),
  });
  shell.main.appendChild(app.answers.root);

  app.search = new SearchController(app.chrome.searchInput, app.chrome.results, {
    index: () => app.index,
    activate: (hit) => app.activateHit(hit),
    onQueryChanged: (query) => {
      app.filters.patch({ query });
      app.saveSoon();
    },
    blurToCanvas: () => app.view.canvasEl.focus(),
  });

  app.loading = new LoadingState(() => app.onAction('mlview.cancelAnalysis'));
  app.loading.root.hidden = true;
  shell.stateHost.appendChild(app.loading.root);

  app.rail = new Rail({
    onTab: (tab) => app.setRailTab(tab),
    onClearFilters: () => app.clearFilters(),
    onSelectIssue: (id) => app.focusIssue(id),
    onSelectNode: (id) => app.select({ kind: 'node', id }, { center: true }),
    onOpen: (loc) => app.openLocation(loc),
    onResize: (w) => app.setRailWidth(w),
    onToggleRail: () => app.toggleRail(),
    onAsk: (id) => app.askAssistant(id),
    onSelectLane: (laneId) => app.selectLane(laneId),
    onToggleCollapse: (id) => {
      if (app.index && app.index.isGroup(id)) app.view.toggleCollapse(id);
    },
    // "Show all" means ALL: a reader who clicks it while both a scope and the
    // diff projection are narrowing the list expects one gesture, not two.
    onClearScope: () => {
      if (app.scopes.changedOnly) setChangedOnly(app, false);
      app.setScope(null);
    },
    onScopeToNode: (id) => app.scopeToNode(id),
    onGroupBy: (mode) => app.setRailGroupBy(mode),
    onCopyIgnore: (code) => app.copyIgnore(code),
    onDisableRule: (code) => app.disableRule(code),
    onApplyFix: (id) => app.applyFix(id),
  });
  shell.body.appendChild(app.rail.root);

  // Anchored inside the canvas, beside the minimap, so the key sits with the
  // picture it explains rather than in a modal over it (VIEW-10).
  app.legend = new Legend((open) => app.setLegend(open));
  shell.canvas.appendChild(app.legend.root);

  // MLV-P12. Appended on the app root beside the shortcut sheet and the scope
  // picker, so it overlays the diagram without being inside the canvas — a
  // chooser drawn in the world layer would pan and zoom with it.
  app.chooser = new PipelineChooser({ onPick: (spec) => answerPipelineChooser(app, spec) });
  app.root.appendChild(app.chooser.root);

  app.sheet = new ShortcutSheet(() => app.toggleShortcuts(false));
  app.root.appendChild(app.sheet.root);
  app.root.appendChild(app.exportMenu.panel);
  app.root.appendChild(app.scopeBar.picker.root);

  app.root.appendChild(app.chrome.status);
  app.root.appendChild(app.liveEl);
  app.setRailWidth(app.railWidth);
  app.setRailOpen(app.railOpen);
  // Only the standalone report owns its own theme; in a webview the host does.
  if (app.bridge.host === 'standalone') app.themes.mountSwitch(app.chrome.toolbar);
}

/** What the canvas is allowed to ask of the application. */
export function canvasHost(app: App): CanvasHost {
  return {
    keep: app.filters.keep,
    isFilteredOut: (node) => app.filters.hidesNode(node),
    activateNode: (id) => app.select({ kind: 'node', id }, { open: true, tab: 'inspector' }),
    activateEdge: (id) => app.select({ kind: 'edge', id }, { open: true, tab: 'inspector' }),
    clearFilters: () => app.clearFilters(),
    canReanalyze: () => false,
    requestRefresh: () => undefined,
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
    widenScope: () => stepDepth(app, 1),
    clearScope: () => app.setScope(null),
    scopeSpec: () => app.scopes.spec,
  };
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
export function completeLoc(loc: AnswerLoc, graph: MLGraph | null): Loc {
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
