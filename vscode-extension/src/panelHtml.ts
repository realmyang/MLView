/**
 * The frozen webview document (CONTRACTS.md section 4, amendment A13).
 *
 * Split out of panel.ts so the panel class stays inside the repo's ~600-line file budget. It is
 * pure string work with no `vscode` object at all, which is exactly what `test/panelhtml.test.js`
 * and `test/panel.test.js` assert; `panel.ts` re-exports both symbols so every importer, and the
 * test entry point, is unchanged.
 */

import { randomBytes } from 'node:crypto';
import { PANEL_TITLE } from './panelScope';

export interface PanelHtmlOptions {
  cspSource: string;
  nonce: string;
  scriptUri: string;
  styleUri: string;
  /** False before `tools/sync-assets.py` has run — A13 requires a message, not a throw. */
  bundlePresent: boolean;
}

export function createNonce(): string {
  return randomBytes(24).toString('base64');
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * The frozen webview document. `'unsafe-inline'` is granted for STYLES ONLY (nodes carry
 * positional styles); scripts are nonce-locked and `default-src 'none'` is the CSP-level
 * enforcement of the offline requirement.
 */
export function buildPanelHtml(opts: PanelHtmlOptions): string {
  const csp =
    `default-src 'none'; ` +
    `img-src ${opts.cspSource} data:; ` +
    `style-src ${opts.cspSource} 'unsafe-inline'; ` +
    `font-src ${opts.cspSource}; ` +
    `script-src 'nonce-${opts.nonce}';`;

  const head =
    `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1.0">` +
    `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
    `<title>${PANEL_TITLE}</title>` +
    `<link rel="stylesheet" href="${escapeHtml(opts.styleUri)}">`;

  if (!opts.bundlePresent) {
    // A13: tolerate a missing bundle with a designed message instead of a blank, broken panel.
    return (
      head +
      `<style nonce="${opts.nonce}">
        body { font-family: var(--vscode-font-family, sans-serif); padding: 2.5rem; line-height: 1.55; }
        code { background: rgba(127,127,127,0.16); padding: 0.1rem 0.35rem; border-radius: 3px; }
        .hint { opacity: 0.8; max-width: 46rem; }
      </style></head><body><div id="mlview-root">
        <h2>MLView viewer bundle not built</h2>
        <p class="hint">The diagram renderer has not been synced into this extension yet, so there is
        nothing to draw. Build the viewer and sync the assets:</p>
        <p><code>powershell -ExecutionPolicy Bypass -File scripts/build.ps1</code></p>
        <p class="hint">That writes <code>webview/dist/mlview.js</code> and <code>mlview.css</code> into
        <code>vscode-extension/media/</code>. Analysis, the Problems panel and
        <em>Reveal in Diagram</em> keep working without it.</p>
      </div>
      <!-- referenced so the resource roots and the sync target stay visible: ${escapeHtml(
        opts.scriptUri
      )} -->
      </body></html>`
    );
  }

  return (
    head +
    `</head><body><div id="mlview-root"></div>` +
    `<script nonce="${opts.nonce}" src="${escapeHtml(opts.scriptUri)}"></script>` +
    `<script nonce="${opts.nonce}">
(function () {
  var root = document.getElementById('mlview-root');
  if (!window.MLView || typeof window.MLView.mount !== 'function') {
    var box = document.createElement('p');
    box.textContent = 'MLView viewer bundle failed to load. Run scripts/build.ps1 and reopen the panel.';
    root.appendChild(box);
    return;
  }
  var bridge = window.MLView.bridges.vscode();
  // The viewer posts 'ready' from its own constructor; wrap post so we never send it twice.
  var readyPosted = false;
  var post = bridge.post.bind(bridge);
  bridge.post = function (msg) {
    if (msg && msg.type === 'ready') { readyPosted = true; }
    post(msg);
  };
  var app = null;
  try {
    // Mount immediately with no graph: the viewer owns the loading, empty and hard-error states,
    // so an interpreter failure shows a designed banner instead of a blank panel.
    app = window.MLView.mount(root, null, bridge);
  } catch (e) {
    // A viewer that requires a graph at mount time: mount on the first 'graph' message instead,
    // and keep the subscription so every later graph updates in place.
    bridge.onMessage(function (msg) {
      if (!msg || msg.type !== 'graph') { return; }
      if (app) { app.update(msg.graph, msg.preserve); return; }
      app = window.MLView.mount(root, msg.graph, bridge);
    });
  }
  if (!readyPosted) { bridge.post({ v: 1, type: 'ready' }); }
}());
</script></body></html>`
  );
}
