# MLView authored workflow renderer

This package renders model-authored `WorkflowDocument` artifacts in the VS Code
webview. It provides interactive layout, source navigation, finding
inspection, refinement requests, and SVG/PNG export.

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
  `missing`, `unreadable`, `too-large` or `elsewhere`. The viewer marks the
  cards, connections, findings and quotes that cite those paths, disables
  their Open links and counts them in the status bar. An empty list clears
  the marks. `elsewhere` is the root-hint case: the file is not under the
  workspace root but is unchanged in another folder, so every surface says
  "in another folder" and points to the notice, never "changed" or "missing".
- `workflowError` after the mount is drawn as a notice under the header. The
  `checking` code goes to the status bar instead; the `root-hint` code adds
  **Add folder to workspace** and **Open folder**, which post
  `{ type: 'workspaceHint', action: 'add' | 'open' }`. The host picks the folder.
- `openLocation` opens beside the panel with focus kept there; `focus: true`
  (Alt+Enter, Alt+click) asks the host to move focus to the editor. The host
  picks an existing editor group other than the panel's own (since the M2
  live-check fixes, `navigationColumn` in `vscode-extension/src/authoredPanel.ts`).
- A click selects only. Enter, a double-click and the Selection pane's Open
  links open the cited range of a step, connection, finding or Outline step; a
  double-click on a group collapses it. The first click of a double-click
  arms an opener (`src/ui/doubleclick.ts`), and the second click, wherever it
  lands, opens what the first one selected: the first click can rebuild the
  rows, collapse a finding above, or open the bottom sheet under the pointer.

Viewer M1 Inspector content, the Selection pane since viewer M2 (no protocol change):

- `normalizeWorkflow` adds `MLNode.detail` (the authored detail, verbatim)
  and `MLNode.phaseLabel`. The Selection pane and the card's accessible name
  read them.
- Viewer M2 re-recorded the geometry golden once: the projection no longer
  gives cards an `attrs={basis}` chip row (`MLNode.attrs` is gone) and edge
  labels no longer end in ` · basis` (`MLEdge.label` is the authored label;
  `MLEdge.authoredLabel` is gone). A card's second line (`sublabel`) is the
  authored detail, else the kind.
- Viewer M2 calm canvas (no geometry change; the golden is byte-identical):
  - Phase colour by document order. `GraphIndex.phaseIndexOf(id)` is the
    phase's position among the declared phases; `render/phase.ts` stamps
    `data-phase-index` and `data-phase-tone` (index mod 8) on lanes, cards,
    groups, connections, trunks and minimap dots, and node.css
    binds `--mlv-stage` from the tone (`--mlv-phase-0` … `--mlv-phase-7` in
    tokens.css, eight literals per theme kind, the contrast border in high
    contrast). `data-stage` stays, because the golden hashes it.
  - Exceptions only. Cards, groups and connections carry `data-basis`; the
    stylesheet dashes `inferred` and dots `unresolved` (cards through a
    `::after` overlay, so the border takes no layout space) and leaves
    `observed` unmarked. `render/nodes.ts` adds a `.mlv-basis-tag` to
    inferred and unresolved cards and group headers only. The edge dash
    channel is the basis, not the kind (`edge.css`); `mlv-edge--<kind>` stays
    for the flow layer. One arrowhead marker, `#mlv-arrow`.
  - `--mlv-z` is written on the canvas: the zoom rounded to the nearest of
    13 buckets. Tags, exception dashes and a 1 px stroke floor divide by it
    to keep their size on screen.
  - `--mlv-edge` and `--mlv-node-edge` are the theme's text colour mixed into
    its background (54% / 46% on dark, 64% / 58% on light); export/palette.ts
    recomputes the same mix.
  - `Issue.short` is `F1`…`Fn` in document order. Badges, edge markers and the
    Findings list print it; tooltips, the Selection pane and the refine
    selection keep `Issue.id`.
  - `.mlv-canvas[data-exceptions="on"]` (the header's not-observed toggle)
    fades observed cards and connections through fill and stroke only.
  - `motion.ts` reads `body.vscode-reduce-motion` as well as the media query
    and watches the body class. A flow runs `FLOW.SETTLE_PASSES` (2) passes:
    the stream's dash train gets a per-cable `--mlv-flow-iter`, the pulse's
    SMIL dot `repeatCount="2"`, and `animationend` calls
    `FlowController.settle()`, which leaves the static marks and sets
    `data-flow-settled` on the canvas. Shift+A calls `replay()`.
  - `test/calm-canvas.test.mjs` computes the contrast of connections, card
    borders, phase tones, basis borders and faded text from the harness's
    theme table (`tools/screenshots/themes.js`) and tokens.css, and covers
    the marks, the F labels, the units, the toggle and the motion rules.
- Viewer M2 readable first view (no geometry change; the golden is
  byte-identical, and the viewport is not part of it):
  - `readablePlan(frame, w, h)` in `render/canvas.ts` is pure: the whole
    document, centred, when `fitPlan` (now only the whole-document fit, capped
    at 1.2) gives `LOD_FULL_ZOOM` (0.62) or more; otherwise phase 1 (the first
    lane, widened left by `frame.channelW`) fitted when that zoom is
    `PHASE_FIT_MIN_ZOOM` (0.75) or more, capped at `READABLE_ZOOM` (0.9), else
    anchored top-left at 0.9. A document narrower or shorter than the canvas
    at that zoom is centred on that axis. `ViewportController.fit()` runs it
    (first paint, key 0, a refit on resize); `fitWhole()` is the ⋯ menu's
    **Fit the whole diagram** and Overview.
    The old top-anchored tall branch (`TALL_SCREENS`, `MIN_FIT_ZOOM`) is gone.
    `App.setWorkflow` still restores a viewport saved for the same revision.
  - Compact level (`data-lod="compact"`, below 0.62): node.css hides the icon
    tile, detail, file:line and chips, makes `.mlv-node__main` a size
    container, and sets the title to
    `min(var(--mlv-compact-title) / var(--mlv-z), 100cqh / (lines x 1.15))`
    with `--mlv-compact-title: 11.2px`, clamped to 2 lines (3 when
    `data-lines="3"`). The `--mlv-z` bucket rounding keeps the counter-scaled
    size between 10 and 12.5 px; the `cqh` cap keeps the lines inside the box
    `layout/cardmetrics.ts` reserved, so nothing is laid out again and no
    per-card style is written. The basis tag hangs below the card at this
    level. `export.css` restores the full card for print.
  - `test/readable-view.test.mjs` compiles `render/canvas.ts` with esbuild for
    the pure plan cases, checks first paint, key 0, Fit the whole diagram and
    a restored viewport on the bundle, and recomputes the compact title size
    over every compact zoom from the shipped stylesheet's numbers and the card
    heights `cardHeight` reserves (10 px or more down to 0.35 for a one-line
    title with a file:line row; never more lines than the box holds).
- The Selection pane (viewer M2 below) shows the claim first; its quotes sit
  under a caption saying that a matching quote does not show support, and one
  line links to the document-wide limitations in About.
- Authored notebook cells print as recorded, counted from 0
  (`nb.ipynb › cell 7, line 3`).
- `test/inspector-content.test.mjs` injects the shipped stylesheet into jsdom,
  so the detail, the suggestion, the caption and the limitations line are
  checked by computed visibility, not by `textContent`.

Viewer M2 header and status bar (no contract change, no geometry change; the
golden is byte-identical):

- `Chrome` (`src/ui/chrome.ts`) builds one `.mlv-header` row (the `h1` title,
  the `.mlv-header__prov` host · revision chip, search, the severity toggles,
  `.mlv-chip--exceptions`, the ⋯ button and the Refine… slot, one
  `role="toolbar"` tab stop) and the `.mlv-status` bar. The App sets
  `data-layout` on both from the root's width on mount and on resize:
  `headerLayout(width)` returns `full` (1200 px and up), `wide` (1000),
  `mid` (620) or `narrow`; an unmeasurable width (jsdom) is `full`.
  `data-search="open|closed"` folds the field at `mid` and `narrow`. The CSS
  keys on these attributes, so the row never wraps.
- `MoreMenu` (`src/ui/moremenu.ts`) is a menu button. Items carry
  `data-more-item` (`search`, `about` and `exceptions` only while the row has
  folded them, marked `data-folded`; then `legend`, `flow`,
  `minimap`, `rail`, `fit`, `zoomsel`, `svg`, `png`, `copy-svg`,
  `shortcuts`); the exports also carry `data-export-action`. The panel is
  mounted on the app root and repaints its checkboxes as it opens. The
  exports are always the whole diagram; Copy PNG, Print and the region
  choice are gone (`@media print` styles remain for the browser's own print).
- The zero-height `.mlv-workflow` section after the header anchors the
  Refine… popover. (The request and coverage details that also opened there
  are the About tab since steps 5 and 9, below.)
- The Refine… composer names its target by label in
  `.mlv-workflow__selection` ("Step: …", "Connection: …", "Finding: F2 · …",
  "Whole diagram"); `data-selection-kind` and `data-selection-id` on the
  composer keep the stable id the request posts.
- The status bar shows `.mlv-status__counts` ("31 steps · 41 connections"),
  `.mlv-status__coverage` ("Coverage: scoped · 6 limitations"), a
  `[data-freshness]` item (`stale` with an icon, `checking`, or muted
  `unchanged` / `unverified` from `freshnessStatus()` in `src/freshness.ts`)
  and the zoom readout with its buttons (`.mlv-zoom__btn`, hidden when
  narrow).
- Removed: the scope projection (`src/scope/`, `setScope`, `getScope`,
  `scopeToNode`), the scope picker, breadcrumb and the Inspector's scope button, the
  `s`, Shift+S, `[` and `]` keys, the phase chips and `Filters.stages`. A
  saved `ViewState` with `scope` or `filters.stages` still loads; both are
  ignored and not written back.
- Ctrl/Cmd+F focuses search from anywhere in the root, and `/` from the
  canvas (the extension sets no `enableFindWidget`, so the webview has no find
  bar of its own; Ctrl/Cmd+K did the same until the live-check fixes). Search rows print the title first and the location under
  it, cut from the start; `.mlv-result__count` heads the list.
- Chrome icons are 19 inline SVG paths in `src/icons.ts` (`uiIcon`), drawn in
  the codicon style; there is no icon font, so the CSP is unchanged.
- `test/header-m2.test.mjs` injects the shipped stylesheet and stubs the root
  width to check the header at 1440, 900 and 541 px, the ⋯ menu, the removed
  controls, an older saved state, the keys and the status bar wording.

Viewer M2 About, Selection pane and bottom sheet (steps 5 and 9; no contract
change, no geometry change, the golden is byte-identical):

- `Rail` (`src/ui/rail.ts`) has four tabs, `RailTab` `about`, `issues`,
  `inspector` (labelled Selection; the id is kept for saved states and panel
  ids) and `outline`, and builds only the visible tab. `App.setWorkflow` sets
  `railTab = 'about'` for a new revision id; `ViewState.railTab` is saved with
  `workflowRevision`, and a remount restores it only for that revision
  (`sanitizeRailTab` in `src/ui/commands.ts` drops unknown values).
  `App.select` shows `inspector` unless the selection came from the list on
  screen: `SelectOptions.fromList` (`issues` from a Findings row or `n`/`p`,
  `outline` from an Outline row) keeps that tab when it is the current tab
  and the rail is shown (viewer M2 review, M2-INT-1).
- `src/ui/about.ts` renders About from the document only: `splitSummary`
  (paragraphs at the summary's own run-in heads, only when there are at least
  `MIN_RUN_IN_HEADS` = 3), `configurationRuns` (`k=v` tokens as `code`), the
  limitations in one `details`, the cited files with a `[data-fresh]` badge
  (`unchanged` and `unchecked` muted, `stale` with an icon), and provenance.
- `src/ui/selection.ts` renders the Selection pane for a step, a connection
  or a finding (`.mlv-sel[data-kind][data-columns]`), in reading order; the
  quotes are `ol > li.mlv-quote` with `.mlv-quote__ln` line numbers and a
  `.mlv-quote__open` button whose accessible name names the place.
  `selectionAnnouncement` is the live-region text while VS Code's
  `vscode-using-screen-reader` body class is set (`motion.ts` also treats
  that class as reduced motion). `CanvasView.frameIssue` frames the union of
  a finding's cited cards and the ends of its cited connections when that
  fits at `FRAME_MIN_ZOOM` (0.45; `ViewportController.fitsAt`), else the
  cited cards (`ViewportController.frameRect`, zoom 0.45 to 1).
- The bottom sheet: `App.autoRail` docks the rail only when
  `width - railWidth >= RAIL_MIN_CANVAS_W` (900); otherwise `Rail.setMode`
  sets `data-mode="sheet"` on the rail and `data-rail="sheet"` on
  `.mlv-body`, which stacks the canvas over it (rail.css). The open sheet is
  `--mlv-sheet-fraction` of the body (0.47; the handle keeps it within 0.25
  and `App.sheetFractionMax()`, at most 0.75, the share that leaves the canvas
  `min(240px, 45%)`, which is also its `aria-valuemax`); collapsed it is
  32 px. A drag that collapses the sheet keeps the fraction it started with. `CanvasView.afterSheetToggle` takes the new canvas size as fitted
  (`ViewportController.acceptResize`) and keeps a visible selection in view.
  The Selection pane has two columns when `App.selectionColumns()` says so
  (sheet and at least 620 px). The drawer, its scrim and
  `CanvasHost.coveredRight` are gone.
- `src/ui/focustrap.ts` keeps Tab inside the shortcut sheet and the Refine…
  popover (`role="dialog"`, `aria-modal`) and restores the focus on close.
- `test/panes-m2.test.mjs` covers the tabs and their memory, the tab rule,
  About, the three panes, finding framing, the sheet at 1440, 900 and 541 px,
  keyboard focus, the Tab budget, the focus traps and the screen-reader
  announcement; `test/viewer-layout.test.mjs` keeps the canvas floor rule and
  checks the sheet CSS.

Viewer M2 review fixes (no contract change, no geometry change; the golden is
byte-identical):

- `RovingGroup` (`src/ui/roving.ts`) skips controls with no client rects
  (a stylesheet's `display: none`) while its container is rendered, puts every
  non-item out of the Tab order, and keeps the stop on the control the user
  left it on; until the user moves it, the stop is the first item. Search
  result rows (`role="option"`) are not items and carry `tabindex="-1"`; the
  field's arrow keys reach them.
- `Chrome.fitRow()` measures the header after every change of width, search
  state or content: while `scrollWidth > clientWidth` it raises `data-fit`
  (0 to `HEADER_FIT_MAX` = 4): 1 hides the revision chip, 2 hides
  `.mlv-chip--exceptions` (the ⋯ menu's `exceptions` item takes it), 3 makes
  the title visually hidden and tightens the gaps, 4 (only while the search
  field is open at `mid` or `narrow`) hides the severity toggles. Hidden
  controls get the `hidden` attribute, so the roving group drops them. jsdom
  measures nothing, so `data-fit` stays 0 there.
- `.mlv-header__unit` prints "findings" after the severity toggles (visual
  only; each toggle's name has its unit). The exceptions chip reads "N not
  observed" plus its `.mlv-chip__detail` breakdown at `full`, otherwise
  `notObservedLead()` ("N claims not observed"). An off toggle
  (`aria-pressed="false"`) is struck through with a dashed border, never
  faded. `.mlv-root .mlv-btn--primary` takes `--mlv-on-accent` over the
  button reset; high contrast gives it `button.border` or `contrastBorder`.
- `App.modalOpen()` keeps Ctrl/Cmd+F inside the shortcut sheet and the
  Refine… popover. `App.activateHit` selects a step with
  `showClaim`; `showRailForClaim` marks an already-open rail as chosen, so
  `autoRail` keeps it open into the sheet.
- The Selection pane has a `group` kind: `subtreeIssues` for "Findings in
  this group", a `members` section with links to its steps, and "Comes
  from … into …" / "Feeds … from …" for the connections across its edge.
  `basisChip()` (`src/ui/evidence.ts`) returns the canvas tag for inferred
  and unresolved findings and `null` for observed ones.
- Canvas: a hover (`.is-tracing`) dims nothing and rings the lit cards; only
  focus mode (`.is-focusing`) fades and disables the rest. A card with an
  authored detail and a file:line row (`cardDetailLines()` in
  `render/nodes.ts`) draws `.mlv-node__sub[data-lines="2"]`, two clamped
  lines, and no `.mlv-node__loc`; the reserved heights are unchanged. A lane
  header is a plate with the phase swatch, `.mlv-lane__num`, the label in
  `--mlv-text` at 13 px, the step count, the severity cluster and
  `.mlv-lane__unit` ("N findings touch this phase", `phaseFindingsText`).
  The Outline numbers its lanes and puts `.mlv-outline__phasecount` on its
  own line. `export/svg.ts` draws the same lane plate, unit and card face.
- Removed as dead: `FilterModel.hidesNode`, `CanvasHost.isFilteredOut` and the
  `.is-filtered` styles, `FlowHost.streamEligible`, `--mlv-fg-boundary` and
  `Palette.fgBoundary`, `base64ToBytes` and `MIME` in `export/raster.ts`,
  `CanvasView.viewportRect` and the `view` export region
  (`exportFile.scope` is always `all`).
- `test/helpers.mjs` adds `cascadeWinner(css, element, property)`, which
  resolves a declaration by specificity and order from the stylesheet text
  (jsdom's `getComputedStyle` lets the later rule win whatever its
  specificity). `test/m2-review.test.mjs` holds one regression test per
  review finding; it models the header's widths and which elements have
  boxes where jsdom lays nothing out.

Viewer M2 live-check fixes (no contract change, no new setting; the golden is
byte-identical):

- `ViewportController.revealRect(rect, margin = 16)` (`src/render/canvas.ts`)
  pans the least distance that brings a world rectangle wholly into the
  visible area, at the same zoom. `CanvasView.handleResize` uses it when the
  selection was wholly visible before a size change and is not after: it
  accepts the new size (no refit of the first view) and reveals the
  selection. A selection already out of view, or no selection, keeps the old
  behaviour (`onResize`).
- The overview map's width rule is `CanvasView.setPanelWidth(width)`, which
  sets `.mlv-minimap.is-narrow` at `MINIMAP_NARROW_W` (900 px,
  `src/canvas/host.ts`) or less, in place of a media query.
  `CanvasView.minimapUnavailable()` returns the reason the map is not drawn
  (fewer than 30 cards, `is-narrow`, `is-short`) or `null`; the ⋯ menu's
  `minimap` item is disabled and unchecked while it is not null and prints
  the reason in `.mlv-moremenu__note`.
- Keys: the only Ctrl/Cmd chord the viewer answers is `Mod+F`
  (`handleCanvasKey` in `src/ui/keymap.ts` returns false for the others, so
  they reach the workbench). `b` toggles the rail (was Ctrl+B) and `t` calls
  `App.focusRailTabs()` (replaces Ctrl+1 to Ctrl+4 and
  `KeyCommands.selectRailTab`). `keyLabel()` in `src/ui/platform.ts` prints a
  keymap string for the platform (`Mod+` as Ctrl+ or ⌘, and ⌃ ⌥ ⇧ on macOS);
  the shortcut sheet, the ⋯ menu and the search button use it.
- A finding listed on a step (`appendFindings` in `src/ui/selection.ts`)
  prints its real id as `.mlv-insp__issue-id.mlv-mono` under the title,
  not beside it.
- `ViewState.sheetOpen` is written (with `workflowRevision`) only while the
  rail is an open bottom sheet. A remount keeps the saved selection
  (`sanitizeSelection` in `src/ui/commands.ts`) and an open sheet in
  `restoredSelection` / `restoredSheet` and applies them in the first
  `setWorkflow` for the same revision, as for `railTab`; a selection whose id
  the revision lacks is dropped there.
- Phase tones 2 and 3 changed in `src/styles/tokens.css` and
  `src/export/palette.ts` (light #0A693C, #A0388F; dark #4CA871, #D684C5).
- `test/m2-live.test.mjs` holds the regression tests for fixes 1, 4, 5, 6
  and 7; the hue test for fix 3 is in `test/calm-canvas.test.mjs`.

Viewer M3 review walk, host side, and Escape (no contract change, no new
setting; the golden is byte-identical):

- `openLocation` takes four optional fields (`UiToHost` in `src/types.ts`):
  `seq`, a positive integer that increases with every numbered open of a
  page; `requestId`, which asks for one `actionResult`; `walk: true`, an open
  from the review walk; and `highlight: false`, which selects the range
  without the whole-range highlight. Opens without them behave as in M2.
- The host drops a numbered open whose `seq` is not above the last one it saw
  on this page (answered `cancelled`), and an open a later open overtook while
  it waited (a notebook's cell editor, for example). A new page (`ready`)
  starts the numbering again. The walk itself (step 11) should send a jump
  only after the reader has stopped moving for about 150 ms; that debounce is
  not in the viewer yet.
- `actionResult` answers `openLocation` too: `done`, `blocked` (not opened,
  with `reason` and a short `message` such as "train.py changed after
  revision r3 was published; not opened."), `cancelled` or `failed`. It
  repeats the request's `seq`. `reason` is one of `changed`, `missing`,
  `unreadable`, `too-large`, `elsewhere`, `unsaved`, `cell-missing`,
  `unchecked` or `unknown` (`OpenBlockReason`). The message never holds an
  absolute path.
- A blocked walk open raises no VS Code notification; the reason is only in
  the result. A blocked open from Enter, a double-click or an Open link still
  shows the M2 warning notification, and is answered as well when it carried
  a `requestId`.
- `{ type: 'walk', state: 'end' }` is new: the walk ended, so the host clears
  the cited-range highlight (and its overview-ruler mark) and drops a walk open
  still waiting. Closing the panel clears it too.
- The checks behind a jump are cached per revision and freshness version, keyed
  by each cited file's device, inode, size, and modification and change times
  (`checkCitedFile` in `vscode-extension/src/authoredPanel.ts`). The first jump
  into a file hashes that file once; later jumps into it read no file content
  while those stay the same. A file whose stat changed without a watcher event
  is checked again.
- Escape: `KeyCommands.escape()` returns whether the cascade did anything.
  When the focus is already off the canvas and nothing is open or selected,
  `handleCanvasKey` leaves Escape unconsumed so VS Code can use it (for
  example to hide a notification). VS Code's webview host forwards every
  keydown to the workbench, even one the page called `preventDefault()` on,
  and its window listener runs before any page script. So after the mount
  the panel's bootstrap (`render()` in `vscode-extension/src/authoredPanel.ts`)
  adds a document-level keydown listener that stops an Escape the viewer
  already handled (`defaultPrevented`) before it reaches that window
  listener. The search box's Escape (`SearchController.handleKey`) is marked
  handled too. `authoredEscapeHandshake` in `test/authored-handshake.mjs` pins
  both with a stand-in forwarder attached before the scripts.

Viewer M1 cleanup (no contract change):

- The bundle contains only the authored path. Inbound, the viewer handles
  `init`, `theme`, `workflow`, `workflowError`, `stale` and `actionResult`,
  plus `revealNode` and `revealIssue` (kept for the planned "Reveal in
  Diagram") and `restoreState` (the tests drive collapse with it); any other
  type is answered with a `log` frame and ignored. Outbound it posts
  `openLocation`, `workspaceHint`, `refineWorkflow`, `copy`, `exportFile` and
  `log` (viewer M3 adds `walk` to the protocol for the review walk; the viewer
  does not send it yet); the host bootstrap posts `ready`.
- A saved `ViewState` with keys the viewer no longer writes (for example
  `showSuppressed` or `railGroupBy`) still loads; those keys are ignored.
- `MLGraph` carries only what an authored document fills in. Fields of the
  retired analyzer graph (ghost, confidence, suppression, ports, diff and
  rollup data) and the `concern:` scope presets are gone.
- The stylesheet is 13 files concatenated in the order `build.mjs` lists
  (viewer M2 removed `scope.css`).

## Screenshots (opt-in)

`node tools/screenshots/capture.mjs` (from `webview/`) opens documents in the
built viewer in headless Chrome and saves one PNG per state plus `index.json`.
The capture itself is opt-in: it is not run by `npm test`, CI or the e2e
gates, and it needs a local Chrome or Chromium (set `CHROME` if it is not in
the usual place). Its plumbing is tested, though: `test/screenshot-pipe.test.mjs`
(pipe framing and the Chrome lookup, no Chrome needed) runs in `npm test`, so
in CI and in both e2e drivers, Windows included, and a change to
`tools/screenshots/cdp.mjs` can fail those gates. Node 20 is enough: it talks
to Chrome over `--remote-debugging-pipe`, not a WebSocket.

```sh
node tools/screenshots/capture.mjs                    # sample + synthetic, dark theme
node tools/screenshots/capture.mjs --theme all --scale 2
node tools/screenshots/capture.mjs --artifact ~/repo/run.mlview.json --workspace ~/repo
node tools/screenshots/capture.mjs --viewer /path/to/main-worktree --out /tmp/shots-before
```

- States: `initial` (About, since viewer M2), `select-node`,
  `select-connection`, `hover-node`, `hover-connection`,
  `focus-mode`, `focus-settled` (focus mode, then 7 s for the flow to
  settle), `exceptions` (the "not observed" toggle on), `legend`, `compact`
  (`-` pressed until the zoom is under 62%), `whole` (**Fit the whole
  diagram**, from the ⋯ menu), `filter` (the lowest severity with findings
  turned off), `search` (through the search icon or the ⋯ menu when the
  field is folded), `finding` (a finding with its suggestion),
  `finding-pane` (that finding, then the Selection tab), `stale`, `stale-selected` and `narrow-selected` (900x800). Pick some with
  `--states`. `index.json` records, per shot, how many connections are lit
  and moving, whether the flow has settled, the canvas box, the header and
  status bar heights (`bars`), the chrome above and below the canvas
  (`chrome`), the header's layout, height and the controls it shows
  (`header`), the search match count (`searchCount`), the rail's mode,
  box and Selection columns (`rail`), whether the selected card or
  connection is wholly inside the canvas (`selectedInCanvas`), the zoom, and `titles`: for the step titles wholly in
  the canvas, their size on screen (computed font size times the canvas
  scale, measured from the box), the lines shown, how many end clamped and
  the share of characters the shown lines hold. Use `--size 541x798` for the
  measured beside-the-code width.
- Inputs: by default `samples/configured_training.mlview.json` (read only)
  and a synthetic 120-step document built from `tools/benchmark-model.mjs`.
  `--artifact` and `--workspace` open your own; with a workspace, cited files
  are hashed against the published hashes and real stale files are posted.
  When no file is really stale, the stale states mark one file cited by the
  clicked step as changed, and `index.json` says it was simulated.
- The page plays the VS Code side: VS Code theme colours (Dark Modern, Light
  Modern, Dark High Contrast), a stub `acquireVsCodeApi`, and the panel's own
  inline bootstrap read from `vscode-extension/src/authoredPanel.ts`. It
  posts what the extension posts: `init`, `workflow`, and for the stale states
  `stale` and the stale banner. Nothing answers the viewer's requests;
  `index.json` records what it posted (for example `openLocation`).
- `--viewer <checkout>` loads another checkout's `webview/dist` and
  bootstrap, for before/after pictures of the same documents.
- Output goes to `.mlview/screenshots/<time>/` (gitignored) unless you pass
  `--out`. Do not commit screenshots of third-party code.

It lives here, next to the benchmark tools, because it serves `dist/` and
reuses `tools/benchmark-model.mjs`, and nothing under `webview/tools/` is
packaged into the VSIX. `test/screenshot-pipe.test.mjs` checks its pipe
framing and Chrome lookup without Chrome. The host is simulated, so the
pictures are a rendering check: they are not live VS Code validation,
usability evidence or a semantic review.
