# MLView webview assets

This directory is the extension's `localResourceRoots` for the diagram webview.

It is **written only by `tools/sync-assets.py`**, which copies the built viewer bundle
(`webview/dist/mlview.js` and `webview/dist/mlview.css`) here. Nothing else may write
to this directory, and nothing here is authored by hand.

Until that sync has run, this README is the only file present. The extension detects the
missing bundle and renders a "viewer bundle not built" panel with a **Build viewer** hint
(`scripts/build.ps1`) instead of failing to load (CONTRACTS.md amendment A13).
