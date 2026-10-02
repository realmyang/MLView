/**
 * VIEW-07, the App's half: gather what the picture needs at the moment the
 * reader asked for it, then hand it to `export/actions.ts`.
 *
 * Nothing here draws. The plan is the one the DOM was built from, so the export
 * cannot diverge from the diagram by construction, and the theme, which could
 * go stale, is read LIVE rather than remembered. The ... menu exports the whole
 * diagram (viewer M2).
 */

import { resolvePalette } from '../export/palette.js';
import { ExportRequest, copySvgText, exportFileName, renderExport, savePng, saveSvg } from '../export/actions.js';
import type { ExportActionId } from '../ui/moremenu.js';
import type { App } from '../app.js';

/**
 * Everything the export needs, gathered at the moment the reader asked.
 *
 * The plan is the one the DOM was built from, the palette is read off the
 * MOUNTED root — so a VS Code user exports their own theme's colours, not our
 * defaults.
 */
function exportRequest(app: App): ExportRequest | null {
  const plan = app.view.scenePlan();
  if (!plan || !app.graph) return null;
  return {
    plan,
    // VW-05: the LIVE theme (the host's `theme` frame may have changed it),
    // not the one the host handed us at construction.
    palette: resolvePalette(app.root, app.themes.kind),
    theme: app.themes.kind,
    graph: app.graph,
    generatedAt: new Date().toISOString().slice(0, 10),
  };
}

export function runExport(app: App, action: ExportActionId): void {
  const host = {
    post: (msg: any) => app.bridge.post(msg),
    request: (msg: any, onResult: (result: any) => void) => {
      app.postRequest(msg, onResult);
    },
    toast: (text: string) => app.view.toast(text),
    announce: (text: string) => app.announce(text),
  };
  const request = exportRequest(app);
  if (!request) {
    app.view.toast('Nothing is drawn yet — there is nothing to export.');
    return;
  }
  const result = renderExport(request);
  if (action === 'svg') saveSvg(host, result, exportFileName(request, 'svg'));
  else if (action === 'png') void savePng(host, result, exportFileName(request, 'png'));
  else if (action === 'copy-svg') void copySvgText(host, result);
}
