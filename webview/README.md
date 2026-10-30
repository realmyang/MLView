# MLView viewer

This package draws a WorkflowDocument in the page that the VS Code extension
opens. It lays out the diagram and provides the side panel, search, the
review walk, refinement requests and export as SVG or PNG.
[docs/architecture.md](../docs/architecture.md) maps its source.

## Commands

```sh
npm run build
npm run check
npm test
```

## What is built

`npm run build` writes two files, `dist/mlview.js` and `dist/mlview.css`, and
both are committed. `python tools/sync-assets.py`, run from the root, copies
them to `vscode-extension/media/`, where the extension's page loads them.
The script is one file that defines the global `MLView`.

## Interface

```ts
window.MLView = {
  version: string,
  mountWorkflow(root: HTMLElement, document: WorkflowDocument, bridge: HostBridge,
                comparison?: { previous?: WorkflowDocument; replaced?: string }): WorkflowViewApp,
  normalizeWorkflow(document: WorkflowDocument),
  bridges: { vscode(): HostBridge }
}
```

- `version` is the version of the package.
- `mountWorkflow` draws `document` into `root` and returns the application.
  `comparison` carries the revision that the panel showed before, or its id.
- `normalizeWorkflow` returns the viewer's own model of a document. The tests
  call it. It is not a second format, and `mountWorkflow` does not take it.
- `bridges.vscode()` returns the channel to the extension.

## Messages

The viewer reads no file and makes no network request. It receives a document
from the extension in a message, and it asks the extension in messages to
open cited lines, to save an exported picture and to copy a refinement
prompt.
[docs/architecture.md](../docs/architecture.md#messages-between-the-extension-and-the-viewer)
lists the messages.

## Tests

`npm test` runs every `test/*.test.mjs` file with `node --test`. Most tests
load the built `dist/mlview.js` into jsdom, with a stand-in for the extension
that records what the viewer posts. The command does not build: after a
change in `src/`, run `npm run build` first. `npm run check` runs
`tsc --noEmit`. The tests need no browser and no VS Code.

## Tools

`tools/` holds the runner of `npm test` and four developer tools: screenshots
of the viewer in headless Chrome, geometric numbers of the layout, a benchmark
and the key table of the user guide.
[docs/development.md](../docs/development.md) describes them. No file under
`src/` imports them, so they are not in the bundle.
