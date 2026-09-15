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

`dist/mlview.css` is **minified** (BUILD-01): one `esbuild.transform` call takes
the nine concatenated layers from 85 KB to 53 KB, -38 %, in every emitted report
and in all three checked-in copies. The readable concatenation, its
`/* ---- file ---- */` markers and all, is written beside it as
`dist/mlview.dev.css`. That file is **never shipped** -- `tools/sync-assets.py`
copies only `mlview.js` and `mlview.css` -- and exists for two consumers: the
`dev/*.html` harness pages, and the CSS gates that assert authored structure.
`test/bundle.test.mjs` proves `mlview.css` is byte-for-byte the minification of
`mlview.dev.css`, so an assertion about the readable file is an assertion about
what ships, and holds both to a size ratchet (JS 278 KB, CSS 62 KB) whose recorded figures are
themselves gated, so a rebuild that moves the bundle has to re-measure the
block rather than quietly outlive it.

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
- `ViewState` = `{ viewport, selection, collapsed, filters, railTab }` plus the
  optional `minimapCollapsed`, `scope`, `flow`, `railGroupBy` and `legendOpen`
  -- each absent at its default, so a host predating one round-trips it
  untouched (CONTRACTS 11.9's pattern). Saved
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
| `src/app.ts` | the controller: view state and lifecycle; the work it drives is in `src/app/` |
| `src/app/` | `build` (the shell and every panel), `documents` (document, scope, diff, chooser), `surfaces` (repaint chrome / diff band / rail), `actions` (the requests posted to the host), `exporting` (VIEW-07), `keys` (the keyboard binding), `messages` (the host protocol, inbound), `state` (`ViewState`, both directions) |
| `src/canvasview.ts` | the diagram surface: layout frame, scene DOM, viewport, hover, focus, collapse |
| `src/canvas/` | `host` (what the canvas may ask of the App, and the surface's timings), `wiring` (the gestures a rendered card or cable answers), `emphasis` (selection, hover, the lineage trace, focus mode) |
| `src/filters.ts` | the filter model (severities, stages, suppressed, query, rule codes) and its predicates |
| `src/layout/` | `model` (index), `layout` (swimlanes + dagre), `wrap` (rank re-flow), `routing` (elbows, loops), `channel` (the cross-lane trunk plan), `bundles` (trunk + spur geometry), `navigate` (arrow keys) |
| `src/render/` | `scene`, `nodes`, `edges`, `bundles` (the trunk layer and its expand/collapse binding), `canvas` (viewport + minimap), `trace`, `tooltip`, `connectors` |
| `src/ui/` | `shell`, `chrome`, `chromebanners` (the banner stack, in its contracted order), `chromechips` (what the chip row says about a run, before any of it is a DOM node: collect, fold, cap), `rail`, `issuelist`, `railgroup`, `evidence`, `ruledocs`, `legend`, `gestures`, `states`, `keymap`, `searchbox`, `searchcontroller` |
| `src/ui/issuelist.ts` | the Issues panel: the "Group by" control, the severity sections, the rows and the four empty states |
| `src/ui/railgroup.ts` | grouping findings by rule or by file, with occurrence counts (RAIL-GROUP) |
| `src/ui/evidence.ts` | the confidence chip on every row, the `issue.evidence[]` checklist and the rule card (MLV-P6) |
| `src/ui/ruledocs.ts` | **the rule-doc sidecar hook**: reads `<script id="mlview-rule-docs">` or `window.MLViewRuleDocs`, and composes the same sections from the finding until the analyzer emits one |
| `src/diff/` | **VIEW-08**: `overlay` (reads and validates the `mlview-diff` document from the `diffOverlay` message, `window.MLViewDiff` or `<script id="mlview-diff">`), `adopt` (stamps `diffStatus` on the nodes and resurrects the removed ones as ghosts in place), `changed` (the "changed only" projection, which REUSES `scope/project.ts`) |
| `src/ui/diffbar.ts` | the diff banner: the headline, the two documents, the counts, the "changed only" chip, and `notes[]` drawn in full beside the viewer's own blind spots (CONTRACTS 11.38 C) |
| `src/ui/fixes.ts` | **H5**: the "Fix available" marker, the safety word, the edit as a verbatim snippet and the one action — `applyFix` in VS Code, the clipboard in a report |
| `src/config/resolved.ts` | **ANA-10**: the resolved config value read off `Node.attrs`, the one-of-N alternatives list, and "not resolved" as an explicit statement rather than an absence |
| `src/ui/legend.ts` | the legend, generated from `markers.ts`, the edge-kind table and the real card classes (VIEW-10) |
| `src/ui/gestures.ts` | wheel `deltaMode` normalization, the ctrl/pinch branch, two-axis pan and two-pointer pinch (VIEW-06) |
| `src/searchloc.ts` | a pasted `path:line` resolved to the narrowest node containing that line (VIEW-09a) |
| `src/markers.ts` | the three severity shapes, badges, clusters and edge markers |
| `src/icons.ts` | one inline SVG symbol per `NodeKind`, plus the chrome glyphs |
| `src/bridges.ts` | `vscode()` and `standalone()` host bridges, plus `deepLinkPlan` — the standalone report never navigates itself (CONTRACTS 11.17) |
| `src/protocol.ts` | `HostToUi` dispatch and filter coercion |
| `src/demo.ts` | the `__internal` debug surface used by the tests and `dev/states.html` |
| `src/styles/` | the cascade layers, concatenated by `build.mjs` **in a fixed order**. The chrome is four of them — `chrome` (toolbar, chip row, banners, status bar, search box, minimap), `chromestates` (toasts, the loading / empty states, the filter row), `chromepanels` (scrim, `?` sheet, theme switch, flow and legend toggles, the legend, the `role="toolbar"` wrapper), `chromeanswers` (MLV-P1's card) — and the rail is three: `rail`, `railevidence` (MLV-P6), `railgroups` (RAIL-GROUP + CI-ADOPT). Each is a contiguous slice of the file it came out of, so no rule moved and the minified stylesheet is byte-for-byte what it was. |

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

dagre optimises neither axis against a canvas, so `layout/wrap.ts` re-flows its
output twice before a container is measured. `MAX_RANK_H` splits an over-tall
rank into sub-columns (a lane of edge-less siblings otherwise becomes one very
long column). `MAX_RANK_W` (2000 px) wraps an over-wide rank *sequence* into
stacked rows — nine sibling groups in a 300-node project used to lay one
10 232 px row, which made the world 10 408 x 3 234 and put `fit()` on the 0.15
zoom floor (VIEW-01). Ranks are never split, both budgets are constants rather
than functions of the viewport (the layout must be identical in every host), and
both are above every lane in the shipped samples, so those documents are laid
out exactly as dagre produced them.

A lane box ends where its own content ends. It used to be stretched to the
widest lane, which left the emptiest band 87 % padding and made the world as
wide as the one lane that needed the room; `LANE_MIN_W` is now only a floor for
the lane header. The world is still as wide as its widest lane, which is what
`frame.width`, the edge SVG and the minimap letterbox measure against.

**Cross-lane edges are bundled (VIEW-04).** 70 % of a real document's
connections leave their lane and every hop that skips a band funnels through the
left channel, which used to be a flat 56 px fanned out one edge at a time at
`n * 7` — unbounded, so the seventh member of a lane pair was drawn through the
first column of lane boxes, and a large graph put roughly twenty near-parallel
runs in there. `layout/channel.ts` now plans the corridor per **(source lane,
target lane) pair**: one trunk x per pair, the pairs ordered so the longest hop
takes the outermost slot (they nest instead of braiding), a pair's members
ordered by the y of their target, and every member splayed at most
`BUNDLE_MEMBER_SPREAD` off the shoulder so a run can never leave its corridor.
The channel is reserved by the number of lane PAIRS, not edges, capped at
`CHANNEL_MAX_W` (112 px) — past that the step shrinks before the world grows.

`layout/bundles.ts` then turns the routed edges into one drawable trunk per pair
with a splayed spur per member at each end and a member-count badge, and
`render/bundles.ts` draws them under the cables. It is a SECOND drawing: every
edge keeps its own `points`, its own `d` and its own motion-path id, and a
collapsed member is transparent rather than absent — the flow charge and the SVG
export read those strings. Hover, focus, selection or a lineage highlight
expands the trunk back into individual strokes; a group of one is never drawn as
a trunk. The severity marker on a bundled cable is deliberately NOT hidden, so a
bundle can never make the diagram look cleaner than the analysis was. On the
54-node demo this takes the crossings a reader actually sees from 3.82 to 1.96
per edge; `export/svg.ts` keeps every stroke, because a static picture cannot be
hovered.

`fit()` (`render/canvas.ts`) fits the width of a document taller than it is wide
and anchors it at the top — a swimlane diagram is read by panning down — but
bounds that to `TALL_SCREENS` (1.75) canvas-heights and never goes below
`MIN_FIT_ZOOM` (0.5). The unbounded version opened the demo at 0.756 with three
lanes below the fold and was a measured no-op on both shipped samples; the
re-baselined 54-node demo opens at 0.548 in Chromium at 1600x1000 and at the
0.5 floor at 1280x800. `fitPlan()` is the same decision as a pure function, which is what the
gates assert. A projection always fits WHOLE (MLV-R3-001).

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

  It also carries a **diff overlay** (VIEW-08) as a second
  `<script type="application/json" id="mlview-diff">` block beside the graph —
  real `mlview diff` output over a base built from the same sample — so the
  ledges, the ghost outlines, the banner and the "changed only" chip are on the
  first paint. The `diff` button in the dev bar exercises the OTHER route, the
  `diffOverlay` host message, by posting it at the window the standalone bridge
  listens on. The same bootstrap writes one `Issue.fix` (H5) and two ANA-10
  resolutions onto the sample before mounting, because both features are driven
  by optional fields and the inlined sample is regenerated verbatim from
  `contracts/graph.sample.json`.

Both pages are asserted to load and mount by `test/devpages.test.mjs`.
