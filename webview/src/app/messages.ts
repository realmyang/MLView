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
import { regionFromHostWord } from '../export/actions.js';
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
    // One owner per frame (§1e): the host bootstrap mounts on the first
    // `workflow` and ignores the rest; this listener applies every later one.
    // A frame carrying the very document object already applied is dropped, so
    // no path can render the same frame twice.
    workflow: (document) => {
      if (document === app.workflowDocument) return;
      app.setWorkflow(document);
    },
    actionResult: (result) => app.onActionResult(result),
    theme: (kind) => app.setTheme(kind),
    revealNode: (nodeId, center) => app.focusNode(nodeId, { center, pulse: true }),
    revealIssue: (issueId) => app.focusIssue(issueId),
    setFilter: (severities, codes, query) => {
      if (codes) app.filters.setCodes(codes);
      app.setFilters({ severities: severities ? severities.slice() : undefined });
      if (typeof query === 'string') app.search.setQuery(query);
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
    onUnknown: (type) =>
      app.bridge.post({ v: 1, type: 'log', level: 'debug', message: 'ignored unknown message type: ' + type }),
  });
}
