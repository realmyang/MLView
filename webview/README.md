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

Viewer M1 Inspector content (no protocol change):

- `normalizeWorkflow` adds `MLNode.detail` (the authored detail, verbatim),
  `MLNode.phaseLabel` and `MLEdge.authoredLabel`. The Inspector and the card's
  accessible name read them; the card itself still draws `sublabel`, the
  `attrs={basis}` chip row and the edge label with its ` · basis` suffix, so
  the layout and the geometry golden are unchanged until the M2 re-record.
- The Inspector shows the title, the phase label and kind, one basis chip, a
  sentence for an inferred or unresolved basis, the full detail, the findings
  on the item with **What to change** (the finding's `suggestion`), the source
  quotes under a caption saying that a matching quote does not show support,
  and one line linking to the document-wide limitations in the header Details.
- Authored notebook cells print as recorded, counted from 0
  (`nb.ipynb › cell 7, line 3`).
- `test/inspector-content.test.mjs` injects the shipped stylesheet into jsdom,
  so the detail, the suggestion, the caption and the limitations line are
  checked by computed visibility, not by `textContent`.

Viewer M1 cleanup (no contract change):

- The bundle contains only the authored path. Inbound, the viewer handles
  `init`, `theme`, `workflow`, `workflowError`, `stale` and `actionResult`,
  plus `revealNode` and `revealIssue` (kept for the planned "Reveal in
  Diagram") and `restoreState` (the tests drive collapse with it); any other
  type is answered with a `log` frame and ignored. Outbound it posts
  `openLocation`, `workspaceHint`, `refineWorkflow`, `copy`, `exportFile` and
  `log`; the host bootstrap posts `ready`.
- A saved `ViewState` with keys the viewer no longer writes (for example
  `showSuppressed` or `railGroupBy`) still loads; those keys are ignored.
- `MLGraph` carries only what an authored document fills in. Fields of the
  retired analyzer graph (ghost, confidence, suppression, ports, diff and
  rollup data) and the `concern:` scope presets are gone.
- The stylesheet is 14 files concatenated in the order `build.mjs` lists.
