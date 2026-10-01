/**
 * The one-shot things a reader ASKS FOR, and what the viewer is allowed to do
 * about them.
 *
 * Every one of these is a REQUEST posted to the host. The viewer opens no file,
 * writes no file and edits nothing: what `openLocation` and `copy` actually do
 * is the host's decision, and the announcements here are careful to claim only
 * what the host will have done (VW-10).
 */

import { STALE_TEXT } from '../freshness.js';
import { fileLine } from '../dom.js';
import type { App } from '../app.js';
import type { Loc, RelatedLoc } from '../types.js';

/** Composes the prompt described in UX_DESIGN section 7; hidden unless the host offers it. */
export function askAssistant(app: App, nodeId: string): void {
  if (!app.caps.canAskAssistant || !app.index) return;
  const node = app.index.nodeById.get(nodeId);
  if (!node) return;
  const codes = app.index.issuesOf(nodeId, app.filters.keep).map((i) => i.code);
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
  app.bridge.post({ v: 1, type: 'askAssistant', nodeId, prompt });
}

/**
 * Ask the host to open a cited range beside the panel (viewer M1). The host selects and
 * highlights the whole range and keeps focus here; `focusEditor` (Alt+Enter, Alt+click) asks it
 * to move focus to the editor. A quote whose file the host reported stale is not sent: the reason
 * is said here instead, and the host would refuse the jump anyway.
 */
export function openLocation(app: App, loc: Loc | RelatedLoc, focusEditor = false): void {
  if (!app.caps.canOpenSource) return;
  const reason = loc.evidenceId ? app.freshness.reasonOf(loc.file) : undefined;
  if (reason) {
    const text = loc.file + ': ' + STALE_TEXT[reason] + '. Not opened; the cited lines may no longer be there.';
    app.view.toast(text);
    app.announce(text);
    return;
  }
  // VS Code may tear down a hidden webview as soon as opening source changes
  // the active editor. Persist synchronously before handing control to the
  // host; the ordinary debounced save can be lost with the document.
  app.bridge.saveState(app.getState());
  const message: any = {
    v: 1,
    type: 'openLocation',
    file: loc.file,
    absFile: loc.absFile,
    line: loc.line,
    col: loc.col,
    endLine: loc.endLine,
    endCol: loc.endCol,
    preview: true,
  };
  // Preserve the frozen legacy frame byte-for-byte. Authored evidence adds
  // identifiers only when it actually has them.
  if (loc.evidenceId) message.evidenceId = loc.evidenceId;
  if (loc.evidenceId && loc.cell !== undefined) message.cell = loc.cell;
  if (focusEditor) message.focus = true;
  app.bridge.post(message);
  // What the host is asked to do, not a claim that it did it (VW-10).
  const where = fileLine(loc);
  app.announce(focusEditor
    ? 'Opening ' + where + ' in the editor.'
    : 'Opening ' + where + ' beside the diagram. Focus stays here; Alt+Enter moves it to the editor.');
  if (!focusEditor && !app.openHintShown) {
    app.openHintShown = true;
    app.view.toast('Opening the cited lines beside the diagram. Focus stays here; Alt+Enter moves it to the editor.');
  }
}

export function onAction(app: App, id: string): void {
  if (id === 'mlview.copyErrorDetails' && app.error) {
    app.bridge.post({
      v: 1,
      type: 'copy',
      text: app.error.message + (app.error.detail ? '\n' + app.error.detail : ''),
    });
    app.view.toast('Error details copied');
    return;
  }
  app.bridge.post({ v: 1, type: 'action', id });
}
