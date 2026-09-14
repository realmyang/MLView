/**
 * VIEW-07, the App's half: gather what the picture needs at the moment the
 * reader asked for it, then hand it to `export/actions.ts`.
 *
 * Nothing here draws. The plan is the one the DOM was built from, so the export
 * cannot diverge from the diagram by construction, and every decision that could
 * go stale — the theme, the region, the scope label — is read LIVE rather than
 * remembered.
 */

import { resolvePalette } from '../export/palette.js';
import {
  ExportRequest,
  copyPngImage,
  copySvgText,
  exportFileName,
  printDiagram,
  renderExport,
  savePng,
  saveSvg,
} from '../export/actions.js';
import type { ExportActionId } from '../ui/exportmenu.js';
import type { App } from '../app.js';

/**
 * Everything the export needs, gathered at the moment the reader asked.
 *
 * The plan is the one the DOM was built from, the palette is read off the
 * MOUNTED root — so a VS Code user exports their own theme's colours, not our
 * defaults — and the region is whatever the menu currently has checked.
 */
function exportRequest(app: App): ExportRequest | null {
  const plan = app.view.scenePlan();
  if (!plan || !app.graph) return null;
  const summary = app.scopes.summary();
  return {
    plan,
    // VW-05: the LIVE theme, not the one the host handed us at construction.
    // The standalone report's Auto / Light / Dark / High contrast chips go
    // through `ThemeController.choose`, which never called back into the app,
    // so every export stamped `data-mlview-theme="light"` and the
    // high-contrast branch in `buildExportSvg` (outlined severity glyphs)
    // could not be reached from the standalone report at all.
    palette: resolvePalette(app.root, app.themes.kind),
    theme: app.themes.kind,
    graph: app.graph,
    regionKind: app.exportMenu.currentRegion,
    viewRect: app.view.viewportRect(),
    scopeLabel: summary.spec ? summary.label : null,
    generatedAt: new Date().toISOString().slice(0, 10),
  };
}

export function runExport(app: App, action: ExportActionId): void {
  const host = {
    post: (msg: any) => app.bridge.post(msg),
    toast: (text: string) => app.view.toast(text),
    announce: (text: string) => app.announce(text),
    print: () => {
      try {
        if (typeof window !== 'undefined' && typeof window.print === 'function') window.print();
      } catch (_e) {
        app.view.toast('This host does not offer a print dialog.');
      }
    },
  };
  if (action === 'print') {
    printDiagram(host);
    return;
  }
  const request = exportRequest(app);
  if (!request) {
    app.view.toast('Nothing is drawn yet — there is nothing to export.');
    return;
  }
  const result = renderExport(request);
  if (action === 'svg') saveSvg(host, result, exportFileName(request, 'svg'));
  else if (action === 'png') void savePng(host, result, exportFileName(request, 'png'));
  else if (action === 'copy-svg') void copySvgText(host, result);
  else if (action === 'copy-png') void copyPngImage(host, result);
}
