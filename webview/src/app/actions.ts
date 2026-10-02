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
    // A file in another folder (the root hint) did not change: the notice says where it is.
    const text = loc.file + ': ' + STALE_TEXT[reason] + '. Not opened' + (reason === 'elsewhere' ? '.' : '; the cited lines may no longer be there.');
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
