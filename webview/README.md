# MLView authored workflow renderer

This package renders model-authored `WorkflowDocument` artifacts in the VS Code
webview. It provides interactive layout, scope projection, source navigation,
finding inspection, refinement requests, and SVG/PNG export.

## Commands

```sh
npm run build
npm run check
npm test
```

The committed `dist/mlview.js` and `dist/mlview.css` assets are consumed by the
VS Code extension. The JavaScript bundle exposes this browser API:

```ts
window.MLView = {
  version: '0.3.0',
  mountWorkflow(root: HTMLElement, document: WorkflowDocument, bridge: HostBridge): WorkflowViewApp,
  normalizeWorkflow(document: WorkflowDocument): MLGraph,
  bridges: { vscode(): HostBridge }
}
```

`normalizeWorkflow` is exported for contract validation and tests. `MLGraph` is
the renderer's internal layout model; it is not an analyzer input or public
mount format.

The bundle has no network references. The host sends revised workflow documents
through the `workflow` message and receives source-navigation, export, saved
state, and `refineWorkflow` messages through the bridge.

Viewer M1 protocol details:

- `stale` carries `files: [{ path, reason }]`, where `reason` is `changed`,
  `missing`, `unreadable` or `too-large`. The viewer marks the cards,
  connections, findings and quotes that cite those paths, disables their Open
  links and counts them in the status bar. An empty list clears the marks.
- `workflowError` after the mount is drawn as a notice under the header. The
  `checking` code goes to the status bar instead; the `root-hint` code adds
  **Add folder to workspace** and **Open folder**, which post
  `{ type: 'workspaceHint', action: 'add' | 'open' }`. The host picks the folder.
- `openLocation` opens beside the panel with focus kept there; `focus: true`
  (Alt+Enter, Alt+click) asks the host to move focus to the editor.
- A click selects only. Enter, a double-click and the Inspector's Open links
  open the cited range.
