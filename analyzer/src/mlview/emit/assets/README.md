# `mlview/emit/assets/`

Placeholder. `tools/sync-assets.py` copies `webview/dist/mlview.js` and
`webview/dist/mlview.css` into this directory; nothing else may write here.

Until that happens:

* `mlview.emit.html_out` emits the **plain-HTML fallback** report — a readable
  table of stages, nodes and issues — with a visible
  *"viewer bundle not synced"* banner.
* `generator.rendererSha` in every emitted graph is 64 zeros
  (CONTRACTS amendment A2).

The bundle SHA-256 is computed from `mlview.js` at runtime by
`mlview.version.renderer_sha()`, so a drifted viewer is detectable from the
graph document alone.
