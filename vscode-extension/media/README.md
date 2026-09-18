# MLView webview assets

This directory contains the shared viewer bundle used by the generated-diagram
panel. `tools/sync-assets.py` copies `webview/dist/mlview.js` and
`webview/dist/mlview.css` here after building the webview.

The VS Code extension mounts the WorkflowDocument viewer from these assets; it
does not contain analysis logic.
