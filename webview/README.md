# MLView renderer bundle

The diagram renderer. One build, consumed **unchanged** by the VS Code webview
(`vscode-extension/media/`) and by the standalone HTML report
(`analyzer/src/mlview/emit/assets/`). `tools/sync-assets.py` is the only thing
that copies it.

## Build

```
npm install          # offline; @dagrejs/dagre is the only runtime dependency
npm run build        # -> dist/mlview.js (IIFE, global MLView) + dist/mlview.css
npm run check        # tsc --noEmit
npm test             # node --test over test/*.test.mjs (jsdom against dist/)
npm run render-sample    # plain-text render of contracts/graph.sample.json
npm run refresh-sample   # re-inline the sample into dev/index.html
```

`dist/` is a build product that is **committed**, because both hosts load it and
the analyzer hashes it into `generator.rendererSha`.

## Public API (CONTRACTS section 8, amendment A3)

```ts
window.MLView = {
  version: '0.1.0',
  mount(root: HTMLElement, graph: MLGraph | null, bridge: HostBridge): MLViewApp,
  bridges: {
    vscode(): HostBridge,                                                  // acquireVsCodeApi() once
    standalone(opts?: { theme?: 'auto'|'light'|'dark'|'hc',
                        onPost?: (msg: UiToHost) => void }): HostBridge
  }
}
```

`MLViewApp` = `{ update, focusNode, focusIssue, setFilters, setTheme, getState, destroy }`.

- `mount` accepts `null` for the graph and shows the loading skeleton until the
  first `graph` message arrives — the shape amendment A5 needs.
- `ready` is posted on mount. Every `HostToUi` type in CONTRACTS section 4 is
  handled; unknown types are posted back as a `log` message and ignored.
- `ViewState` = `{ viewport, selection, collapsed, filters, railTab }`, saved
  through `bridge.saveState` debounced at 250 ms and restored from
  `bridge.loadState()` on mount.
- Capabilities drive the chrome: `canReanalyze` shows the refresh button,
  `canExport` the export button, `canAskAssistant` the inspector's assistant
  action, `canOpenSource` gates every `openLocation` post.

`window.MLView.__internal` (`layout`, `buildDemoCard`, `severityGlyph`,
`severityShapes`, `nodeKinds`, `GraphIndex`) is a debug surface for this
package's tests and `dev/states.html`. **Hosts must not depend on it.**

## Host notes

- Load `dist/mlview.css` first, then `dist/mlview.js`, then mount. The bundle has
  no external references at all: no font, image, stylesheet, script or fetch, so
  it satisfies `default-src 'none'` with a nonce'd script tag.
- The renderer stamps `data-theme="light|dark|hc"` on the element it mounts into
  and every token is `var(--vscode-*, <literal>)`, so the same CSS works in a
  webview and in a plain browser.
- Positional styles are inline, which is why the webview CSP grants
  `'unsafe-inline'` for **styles only**.
- The DOM is built exclusively with `createElement` / `createElementNS` /
  `textContent`; `test/bundle.test.mjs` fails the build if a markup-string
  assignment, `eval`, dynamic `import()` or an absolute URL ever appears in
  `dist/mlview.js`.
- Requires `structuredClone` (dagre uses it): Chromium 98+, so every VS Code
  1.100+ webview and every current browser. The test harness shims it because
  jsdom 26 lacks it.

## Source map

| Module | Responsibility |
|---|---|
| `src/main.ts` | the single global: `version`, `mount`, `bridges`, `__internal` |
| `src/app.ts` | the controller: view state, chrome, rail, search, keys, host protocol |
| `src/canvasview.ts` | the diagram surface: layout frame, scene DOM, viewport, hover, focus, collapse |
| `src/filters.ts` | the filter model (severities, stages, suppressed, query, rule codes) and its predicates |
| `src/layout/` | `model` (index), `layout` (swimlanes + dagre), `routing` (elbows, loops), `navigate` (arrow keys) |
| `src/render/` | `scene`, `nodes`, `edges`, `canvas` (viewport + minimap), `trace`, `tooltip`, `connectors` |
| `src/ui/` | `shell`, `chrome`, `rail`, `states`, `keymap`, `searchbox`, `searchcontroller` |
| `src/markers.ts` | the three severity shapes, badges, clusters and edge markers |
| `src/icons.ts` | one inline SVG symbol per `NodeKind`, plus the chrome glyphs |
| `src/bridges.ts` | `vscode()` and `standalone()` host bridges, plus `deepLinkPlan` — the standalone report never navigates itself (CONTRACTS 11.17) |
| `src/protocol.ts` | `HostToUi` dispatch and filter coercion |
| `src/demo.ts` | the `__internal` debug surface used by the tests and `dev/states.html` |

## Layout

Amendment A11: the eight `StageId`s as horizontal bands stacked in `order`,
each laid out independently with `@dagrejs/dagre` `rankdir: LR`
(`data 4 / call 2 / control 2 / config 1` edge weights). Absent stages are named
in the "not detected" chip row, never drawn as empty bands. Groups are laid out
children-first and inserted as sized meta-nodes — dagre `compound` / `setParent`
is never used. `control/back` edges are removed before the dagre pass and drawn
afterwards as loops routed below the construct they return to; cross-lane edges
are orthogonal elbows through the gutters, with a left channel for hops that
skip a band. Given the same document and the same collapsed set, the layout is
byte-identical run to run.

## Development pages

- `dev/index.html` — the sample, inlined (no fetch, works from `file://`), with a
  theme switch. `npm run refresh-sample` regenerates the inlined copy from
  `contracts/graph.sample.json`. Its **deep link** button posts `openLocation`
  through the standalone bridge, and `?embed=1` re-serves the same page inside a
  sandboxed iframe — the two halves of the decision table in CONTRACTS 11.17.
  Hover any connection to see the travelling charge (CONTRACTS 11.13.1).
- `dev/states.html` — every node kind in every state, plus the three severity
  markers at every size. Built from the product's own card builder, so it cannot
  drift.

Both pages are asserted to load and mount by `test/devpages.test.mjs`.
