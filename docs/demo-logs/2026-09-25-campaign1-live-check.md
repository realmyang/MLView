# Campaign 1 live viewer check — 2026-09-25

A partial run of the manual live-host checklist for 0.2.0, on macOS only. It
exercised the real extension and viewer in VS Code. It did not run a native
assistant, analyse ML code with a model, or score any interpretation.

## Setup

- VS Code 1.139.0 on macOS 26.6.2 (arm64), started as an Extension Development
  Host from `vscode-extension/` with an isolated, temporary user-data
  directory, `--disable-extensions` and no other extensions installed.
- Extension and viewer built from the Campaign 1 sources on `llm-workflow`
  (`8aa3e62`; the gate run on that tree is recorded in
  [VALIDATION.md](../VALIDATION.md)).
- Settings: color theme **Default High Contrast Light**; workspace trust
  disabled, so Restricted Mode was **not** exercised.
- A scratch workspace held a byte-exact copy of `samples/configured_training*`
  and a new file `bom_train.py` that starts with a UTF-8 byte order mark. A
  two-node document citing `bom_train.py` was written by hand and published by
  the 0.2.0 helper (`artifact.py publish … --output bom.mlview.json`). The
  helper accepted the line-1 quote written without the BOM and fingerprinted
  the raw bytes.
- The window was driven through the Chrome DevTools protocol
  (`--remote-debugging-port`): command-palette keystrokes, editor typing and
  DOM inspection of the webview frame. Screenshots were taken but not
  committed.

## Results

| Check | Observed |
|---|---|
| **MLView: Open Generated Diagram** with the artifact active | Panel opened; 2 nodes and the edge rendered; no banner |
| High Contrast Light | Viewer root `data-theme="hc"`; body classes `vscode-high-contrast-light vscode-high-contrast` (EXT-4) |
| Document with no findings | "No findings recorded in this revision · The assistant recorded no findings. Coverage: scoped. This is not a check result." (VIEWUI-1) |
| BOM source open in an editor, unmodified, then the artifact touched on disk | No banner: freshness uses disk bytes, not the editor text (EXT-7) |
| Unsaved edit typed into the BOM source | Banner: "Unsaved editor changes in bom_train.py are not checked; freshness uses the saved files. …" |
| **File: Revert File** | Banner cleared |
| `bom_train.py` changed on disk | Banner: "This historical diagram is visible, but 1 source file(s) changed after revision r1 was published: bom_train.py. Jumps into those files are blocked; other evidence still opens. …" |
| Original bytes restored | Banner cleared; the file hash again equals the published fingerprint |
| Node `load` selected → Refine → **Challenge** → Copy prompt | The clipboard held the §1f prompt: host-written header, `Intent: challenge`, `Published revision on disk: r1. If you publish, set revision.parent to r1.`, `Selected item: node load`, and all artifact text inside one fenced JSON block (EXT-6, CRIT-8) |

## Not covered

HC Dark; Refine with the other four intents; notebook evidence; the shipped
`configured_training` sample (copied but not opened); a symlinked workspace
root; Restricted Mode; Windows and Linux; remote workspaces; a native assistant
publishing a refinement into an open panel. The refine-wedge sequences remain
covered by the automated `refine-wedge.test.js` with the real helper, not by
this live run.

## Observation for later work

At the default window size the panel's side rail took most of the panel width,
leaving the diagram canvas as a narrow strip. This is a layout issue in the
legacy viewer shell, not a Campaign 1 regression.
