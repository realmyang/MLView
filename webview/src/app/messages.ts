/**
 * The host protocol, inbound: every `HostToUi` frame the viewer answers.
 *
 * `protocol.ts` owns the shape of a frame and the dispatch; this file owns what
 * each one MEANS to the application. Two invariants run through it: an unknown
 * message is logged and ignored, never an error (invariant 1.1/6), and nothing
 * here re-analyses anything — the host is the only thing that may hand us a new
 * document.
 */

import { dispatchHostMessage } from '../protocol.js';
import { indexOverlay } from '../diff/overlay.js';
import { regionFromHostWord } from '../export/actions.js';
import { setDiff, setGraph } from './documents.js';
import { renderChrome, renderRail } from './surfaces.js';
import { runExport } from './exporting.js';
import { applyState } from './state.js';
import type { App } from '../app.js';
import type { HostToUi } from '../types.js';

export function onHostMessage(app: App, msg: HostToUi): void {
  dispatchHostMessage(msg, {
    init: (theme, capabilities) => {
      app.caps = capabilities || app.caps;
      app.setTheme(theme);
      renderChrome(app);
      renderRail(app);
    },
    graph: (graph, preserve) => setGraph(app, graph, preserve, true),
    analysisStarted: () => {
      app.error = null;
      app.showLoading(true);
      renderChrome(app);
    },
    analysisProgress: (done, total, file) => app.loading.progress(done, total, file),
    analysisFailed: (message, detail, actions) => {
      app.showLoading(false);
      app.error = { message, detail, actions };
      renderChrome(app);
      app.announce('Analysis failed: ' + message);
    },
    theme: (kind) => app.setTheme(kind),
    revealNode: (nodeId, center) => app.focusNode(nodeId, { center, pulse: true }),
    revealIssue: (issueId) => app.focusIssue(issueId),
    setFilter: (severities, codes, query) => {
      if (codes) app.filters.setCodes(codes);
      app.setFilters({ severities: severities ? severities.slice() : undefined });
      if (typeof query === 'string') app.search.setQuery(query);
    },
    stale: (changedFiles) => {
      app.stale = changedFiles.slice();
      app.view.setStale(app.stale);
      app.dismissed.delete('stale');
      renderChrome(app);
      app.view.render();
      app.view.applySelection(app.selection);
    },
    restoreState: (state) => applyState(app, state, true),
    setScope: (spec, depth) => app.setScope(spec, depth === undefined ? undefined : { depth }),
    // VIEW-07: the host's two export commands have no geometry of their own.
    // The region it names becomes the menu's checked region, so the next
    // gesture from the toolbar continues where the command left off.
    requestExport: (kind, scope) => {
      app.exportMenu.setRegion(regionFromHostWord(scope));
      runExport(app, kind === 'png' ? 'png' : 'svg');
    },
    // VIEW-08: an optional sibling document. A malformed one is not an error
    // and not a crash — `indexOverlay` hands back null and the diagram stays
    // exactly as it was (invariant 1.1/6 over a second document).
    diffOverlay: (raw, baseLabel) => {
      const next = raw === null || raw === undefined ? null : indexOverlay(raw);
      if (raw !== null && raw !== undefined && !next) {
        app.bridge.post({ v: 1, type: 'log', level: 'warn', message: 'ignored an unreadable diff overlay' });
        return;
      }
      app.diffBaseLabel = next ? baseLabel || '' : '';
      setDiff(app, next);
    },
    onUnknown: (type) =>
      app.bridge.post({ v: 1, type: 'log', level: 'debug', message: 'ignored unknown message type: ' + type }),
  });
}
