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
  mountWorkflow(root: HTMLElement, document: WorkflowDocument, bridge: HostBridge,
                comparison?: { previous?: WorkflowDocument; replaced?: string }): WorkflowViewApp,
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

Viewer M4 protocol, changes since the previous revision (roadmap step 16; no
contract change):

- The `workflow` frame has two optional fields. `previous` is the valid
  document the panel showed just before, sent only when `document.revision.parent`
  is its id; `replaced` is the id of the revision the panel showed before when
  `document` does not follow it. The host keeps them in memory per panel
  (`nextComparison` in `vscode-extension/src/revisionLineage.ts`: a child
  compares with the revision it replaced, any other revision records only what
  it replaced, the same revision again keeps what it had) and sends them with
  every `workflow` frame, including the first one a new page gets after
  `ready`. A new panel (a window reload, an extension restart) has neither.
  Nothing is persisted, by the host or in the webview's saved state.
- The host bootstrap passes them to `mountWorkflow` as its fourth argument;
  later frames go to `App.setWorkflow(document, preserve, comparison)`. The
  viewer checks them again (`sanitizeComparison` in `src/revisiondiff.ts`:
  `previous` must be a 1.0 document whose id is the parent and not the
  document's own id; `replaced` a string that is neither) and recomputes the
  comparison from every frame, so a frame without them shows none.
- `revisionDiff(prev, next)` is pure. It compares steps, connections and
  findings by id: added, removed, or changed when one of these differs: a
  step's label, detail, basis, phase label, parent, kind or evidence; a
  connection's source, target, label, kind, basis or evidence; a finding's
  title, message, severity, basis, suggestion, cited steps and connections (as
  sets), evidence or counter-evidence. Evidence is a sorted multiset of what
  each cited record cites (file, line, endLine, cell, quote), never its ids.
  Its `marks` map (`kind:id`) holds the added and changed items.
- What reads it: About's first section (`Changes since <id>`, or one line for
  `replaced`; a parent the panel never showed is one line under Provenance),
  the card tag (`.mlv-rev-tag`, drawn by `render/nodes.ts` from a
  `revisionMark` option of `renderScene`, outside the scene plan, so the SVG
  export does not draw it and no box moves), the Selection pane's line under
  the title, the Outline's step and relationship rows, the Findings list rows,
  and the walk's `revision` filter ("Changed in this revision", between
  Findings and Changed files, offered only when it holds a claim). The legend
  has a "Changes since the previous revision" section.
- `test/revision-changes.test.mjs` covers the diff, the check, every surface
  and the unchanged routed geometry; `authoredChangesHandshake` in
  `test/authored-handshake.mjs` drives the real host.

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
    groups, connections, trunks and (since viewer M3) the phase index's rows and
    the phase overview's blocks, and node.css
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
    at 1.2) gives `READABLE_MIN_ZOOM` (0.75) or more; otherwise phase 1 (the
    first lane, widened left by `frame.channelW`) at `READABLE_ZOOM` (0.9),
    anchored top-left. Until viewer M4 the whole document opened down to
    `LOD_FULL_ZOOM` (0.62) and phase 1 was fitted between 0.75 and 0.9
    (`PHASE_FIT_MIN_ZOOM`, now only `phasePlan`'s); see "Viewer M4 first
    view" below. A document narrower or shorter than the canvas
    at that zoom is centred on that axis. `ViewportController.fit()` runs it
    (first paint, key 0, a refit on resize); `fitWhole()` is the ⋯ menu's
    **Fit the whole diagram** (Shift+0 was Overview, fold every group and fit
    the whole, until viewer M3 made it the phase overview).
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
- Viewer M4 first view (A11Y-7; no geometry change, the golden is
  byte-identical):
  - The first view never paints a card title under 9.75 px (13 px x
    `READABLE_MIN_ZOOM`, 0.75, the size M2 judged still readable), and a wider
    or taller canvas never paints the same document with smaller titles, except
    where it shows the whole document instead of phase 1, still at 0.75 or
    more. Phase 1 always opens at 0.9; the whole fit only grows with the
    canvas. `LOD_FULL_ZOOM` (0.62) is unchanged and only picks the card face.
  - Under the M2 plan, the screenshot harness measured dino-copilot at 90%
    (11.7 px titles) up to 900 px wide and whole at 69-72% (9.0-9.4 px) from
    1100 px; vit-cc at 81% (10.5 px) at 786 px between 90% at 700 and 900 px;
    yolov5-cc2 at 80-86% (10.3-11.2 px) from 1100 px. With M4 all three open
    at 90% (11.7 px) at every width from 320 to 1920 px, 600 and 900 px tall.
    The cost: a wide panel shows fewer whole titles at first (dino-copilot at
    1440x900: 14 instead of 17); **Fit the whole diagram** and the phase index
    are unchanged.
  - Across the width where the rail docks (a panel of 1260 px), the canvas
    loses 360 px to the rail, so a document that opens whole on both sides can
    open smaller with the rail docked (a 1000x500 document: 1.2 to 0.85),
    never under 0.75.
  - `test/readable-view.test.mjs` sweeps canvas widths 200-2600 px and heights
    200-1600 px over synthetic frames with the sizes of those three documents,
    a small and a medium document, and the viewer's own layout of the
    `VIT_SHAPE`, `YOLO_SHAPE` and regression fixtures, and the panel widths
    320-1920 px through the measured panel-to-canvas sizes.
- Viewer M4 muted text (`--mlv-text-3`): in a light theme it is
  `color-mix(in srgb, var(--mlv-surface) 38%, #000000)`, the card surface
  darkened, instead of `descriptionForeground`. Light Modern sets
  `descriptionForeground` to its text colour (#3B3B3B), so muted text was not
  muted; Light+'s (#717171) is 4.40:1 on its widget background and 3.94:1 on
  a lane header. Now Light Modern #5E5E5E, Light+ #5C5C5C, Light 2026 #5F5F60.
  Dark themes keep `descriptionForeground`, high contrast its text colour;
  `--mlv-text-2` is unchanged. `export/palette.ts` derives the same colour
  (`TEXT3_LIGHT_MIX`). `test/muted-text.test.mjs` checks 4.5:1 or more on the
  canvas, cards, rail and header, hovered rows and quotes, and lane headers in
  Dark Modern, Dark+, Light Modern, Light+ and both High Contrast themes, and
  that muted text has at most 70% of the text colour's contrast outside high
  contrast. Dark 2026 keeps its `descriptionForeground` (#8C8C8C): 4.80:1 on
  cards, but 3.80:1 on a hovered row and 4.34:1 on a lane header (not
  changed: not in the owner's list for this fix).
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
  folded them, marked `data-folded`; then `review`, `overview`, `legend`,
  `flow`, `phaseindex`, `rail`, `fit`, `zoomsel`, `svg`, `png`, `copy-svg`,
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
- Chrome icons are 21 inline SVG paths in `src/icons.ts` (`uiIcon`; viewer M3
  added `review`, and step 13 replaced `minimap` with `phases` and
  `phaseindex`), drawn in
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
- The overview map's width rule was `CanvasView.setPanelWidth(width)`, with
  `CanvasView.minimapUnavailable()` giving the ⋯ menu's disabled item its
  reason. Viewer M3 step 13 replaced the map with the phase index; the
  panel width now picks the index's form, and `phaseIndexUnavailable()` gives
  the reason (below).
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
  starts the numbering again. The walk sends a jump only after the reader has
  stopped moving for `WALK_OPEN_DEBOUNCE_MS` (150 ms, `src/app/walk.ts`).
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
  still waiting. Closing the panel clears it too. `state: 'clear'` (added with
  step 11) does the same while the walk goes on: the walk moved to a claim it
  opens nothing for (no quotes, or a claim the reader only selected). A
  blocked walk open also clears the previous claim's highlight; a blocked
  ordinary open keeps it.
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

Viewer M3 review walk, the viewer (roadmap step 11; no contract change, no new
setting; the golden is byte-identical):

- `src/walk.ts` is pure: `claimOrder(index)` walks the drawn order (lanes, then
  `roots` and `laneChildren` depth first, as the Outline lists them): each
  step, its `outEdges`, then the findings whose first cited step in that order
  it is; then any connection whose source no lane reached (none can today),
  then findings citing no step, in document order (the roadmap is silent on
  those). It also holds the
  filters (`notObserved` uses `isNotObserved`, the same test as the header's
  count; `changed` is offered unless every stale file is only in another
  folder, the root hint's case),
  `positionFor` (keep the claim, else the next one in drawn order), and the
  bar, pane and live-region wording.
- `src/app/walk.ts` (`ReviewWalk`) runs it: start, stop, step, quotes, the
  `u` and `n` / `p` jumps, filters, the debounced numbered open
  (`openLocation` with `walk: true`, `seq`, `requestId` via
  `App.postRequest`), only the latest answer shown, `walk: 'clear'` for a
  claim with nothing to open, and the place per revision. A reader's own
  selection of a claim in the list moves the walk without opening it.
  M3 review fixes: `start(filter)` resumes the remembered claim only for the
  same filter (another starts at position 0); any move resets `latestSeq`, so
  a late answer for a claim or quote the walk has left is dropped; a claim the
  walk is on but has not asked for gets `unansweredStatus('idle')` (the
  viewer's own stale reason, never "Enter shows" for a stale file), and a
  filter that keeps the claim keeps the status; `onStale()` shows (selects, announces, clears
  the old highlight, does not open) the claim that takes the place of one that
  left Changed files; a `done` after Alt+Enter carries `focusEditor`, and the
  bar says the focus moved; `walkResultAnnouncement` says "not opened" once.
- `src/ui/walkbar.ts` is the bar: a labelled region at the end of `.mlv-main`
  (after the canvas, before the rail), one `role="toolbar"` tab stop for
  Previous and Next (`[data-walk-step]`, as k and j), the filters and Exit,
  `data-layout="narrow"` below 620 px, where the visible place is "3/16"
  (`aria-hidden`) and `.mlv-walkbar__posspoken` holds the whole sentence for a
  screen reader. Escape inside it ends the walk; j, k, [, ], u, n and p
  pressed there go to the walk. The header's Review and the ⋯ menu's item
  focus the canvas when they start the walk (`buildAppUi`).
- `ViewState.walk` (`WalkViewState`: `filter`, `claim`, `quote` when not the
  first, `active` while running) is written only once a walk ran for the
  displayed revision, restored only for the same `workflowRevision`
  (`sanitizeWalk`), and a remount resumes a running walk without posting an
  open. No other walk state is kept; nothing is a verdict.
- Keys (`KEYMAP`, `handleCanvasKey`): `r` toggles, `u` / Shift+U, and only
  while walking `j` / `k`, ↓ / ↑ and `[` / `]`; `n` / `p` follow the walk's
  order while it runs (`CommandPort.walkFindings`). The Escape cascade ends
  the walk after the legend and before the bottom sheet (`appkeys.ts`), and an
  Escape inside the open sheet ends a running walk first.
- The header's `.mlv-header__review` goes with the revision chip (below
  620 px or at fit level 1); the ⋯ menu always has `review`. `HostNotice`
  offers `[data-notice-action="review"]` for `stale` while claims cite a
  changed file. The Selection pane marks the walk's quote (`applyWalkMark`:
  `.mlv-quote.is-walk`, `.mlv-quote__walk`) in place and scrolls it into view
  on `[` / `]`.
- `test/walk.test.mjs` covers the order on synthetic documents with the
  vit-cc and yolov5-cc2 shapes (79 and 176 claims), filter counts against the
  header, keys, debounce and `seq`, blocked answers, announcements, the place
  per revision, Changed files, Tab order and 541 / 900 px.
  `authoredWalkHandshake` in `test/authored-handshake.mjs` drives the real
  host with the built viewer.

Viewer M3 phase overview and phase index (roadmap step 13; no contract
change, no new setting; the golden is byte-identical):

- `src/render/phaseoverview.ts` is pure. `overviewInput(index, keep)` lists
  each lane's steps in the walk's and the Outline's order (`roots`, then
  `laneChildren` depth first) with basis, depth and the F labels the severity
  toggles keep, the findings per phase from `laneCounts` (the PR #14 rule), and
  the connections as a partition: inside a phase, one `OverviewLink` per
  ordered pair of phases, and any with a missing end. `phaseOverviewLayout(input,
  w, h)` turns that into blocks, arrows (links to the next phase) and brackets
  (all other links, an adjacent backward one included, packed into as few
  slots as do not overlap). There are two title columns when a block is 600 px
  wide or more, and one below 620 px of canvas. Blocks are trimmed from the one
  with the most rows until the whole fits, never below `MIN_SLOTS` (two titles
  and "… N more steps"); below that the overview scrolls. Per block
  `listed + more` is its step count.
- `src/ui/overview.ts` (`PhaseOverview`) draws it as a `section.mlv-overview`
  inside `.mlv-canvas`, beside (never inside) `.mlv-world`, so the routed
  picture does not move. Blocks are `role="button"` with a roving tab stop,
  named by `blockName()` and described by their list of titles. ↑ ↓ ← →, Home
  and End move, Enter or Space go, and `)` or Shift+0 go back. The overview
  stops only those keys. Escape goes on to the canvas's cascade, which closes
  a legend (or phase list) opened over the overview before it leaves the
  overview. Any other key reaches the canvas, where
  `closingOverview` (`src/app/keys.ts`) closes it and then acts, except the
  `KEEP_OPEN` commands (the shortcut sheet, search, legend, rail). The ◌ mark is
  a drawn `.mlv-ovmark` ring, because macOS system fonts show nothing for the
  character. The header's key is `OVERVIEW_KEY` (one line at 900 px) or, below
  620 px, the shorter `OVERVIEW_KEY_NARROW`; both say what a bracket's number
  counts. A row's F tags are `aria-hidden` (the screen-reader text names them
  once) and each row ends with a screen-reader separator.
- `src/render/phaseindex.ts` (`PhaseIndex`) replaced the minimap: a
  `nav.mlv-phaseindex` inside the canvas, as a list of row buttons when the
  panel is 1000 px wide or more and the canvas 350 px tall or more
  (`PHASE_INDEX_LIST_MIN_W` / `_H` in `src/canvas/host.ts`) and the reader
  has not folded it; otherwise as a pill, "k/N label", that opens the rows as
  a popover (an Escape rung before the legend). The panel grows from
  `INDEX_W` (288 px) to fit its longest name, up to `INDEX_MAX_W` (360 px);
  jsdom's `coveredRect` takes the widest. A row's tooltip is the action; the
  full name is on its label. `phasesInView` marks the lanes
  on the canvas and picks the current one by visible share of the canvas plus
  visible share of the lane. `ViewState.phaseIndex` is `'folded'` or
  `'hidden'` when not the default; a state saved with `minimapCollapsed: true`
  opens folded and is not written back.
- `ViewportController` (`src/render/canvas.ts`): `setCovered(fn)` takes the
  index's `coveredRect` (measured, or its stylesheet sizes in jsdom).
  `isVisible` counts a target under it as out of view, and `centerOn`,
  `revealRect` and `frameRect` (for its anchor) pan the least distance off
  it (`clearOf`). `animateTo(target, VIEW_ANIMATION_MS)` (240 ms, instant
  under `motionMode() === 'reduced'`) moves the canvas-centre point in a
  straight line with the zoom on a log scale; any other move cancels it.
  `phasePlan(frame, k, w, h)` is the view of phase k at reading size: the
  phase fitted between `PHASE_FIT_MIN_ZOOM` (0.75) and 0.9, else 0.9 anchored
  (M2's first-view rule for phase 1; since viewer M4 the first view opens
  phase 1 at 0.9 only).
- `test/phase-overview.test.mjs` covers the geometry at the three sizes on the
  vit-cc and yolov5-cc2 shapes (counts, partition, blocks inside the canvas,
  columns, scrolling), link classification and slot sharing, reading order
  and F labels, the keys, Escape giving the focus back, the animation and
  reduced motion, names, the routed geometry unchanged by the overlay, the
  index's rows, pill and position, and the focused card never under the
  index (arrows, Outline, search, host reveal, findings, the walk) at
  1440x900, 900x800 and 541x798.

Viewer M3 Reveal in Diagram (roadmap step 14; no contract change, no new
setting; the golden is byte-identical). The host side lives in
`vscode-extension/` (`src/revealCommand.ts`, `src/citationIndex.ts`); the
viewer's part is one inbound frame:

- `reveal {v: 1, kind: 'node' | 'edge' | 'issue', id}` (`src/types.ts`).
  `src/protocol.ts` checks that `id` is a non-empty string and dispatches to
  `revealNode(id, true)`, `revealEdge(id)` or `revealIssue(id)`. The older
  `revealNode {nodeId}` and `revealIssue {issueId}` frames now check their id
  the same way and take the same path. A frame with a missing or empty id is
  dropped.
- `App.revealClaim(sel, {center})` (`src/app.ts`): an id the displayed
  revision lacks gets a toast and the announcement "That claim is not in the
  revision shown here." Otherwise it closes the shortcut sheet, the Refine
  popover (keeping its text) and the phase overview; expands the claim's
  ancestors (both ends of a connection; the cited steps and connection ends
  of a finding); opens a hidden docked rail or a collapsed sheet as the walk
  does (`openRailForWalk`); selects with `showClaim` on the Selection tab; and
  frames the claim: a step centred with one pulse, a finding through
  `frameIssue`, a connection through `CanvasView.frameEdge`. A running walk
  follows the selection (`followSelection`) without opening anything.
- `CanvasView.frameEdge(id)` frames the union of the connection's route and
  its two ends at reading size with the source as anchor, so the anchor is
  panned clear of the phase index. If the target end is then out of view, it
  zooms out to the larger of the fits above and beside the index, when that
  zoom is at least `FRAME_MIN_ZOOM` (0.45); otherwise the reading-size frame
  stays.
- Focus: `CanvasView.focusTarget(target)` focuses the step's card (a group's
  header), the connection's `.mlv-edge__hit`, or the canvas for a finding or a
  bundled connection with no element of its own. The host moves the panel's
  focus right after posting the frame, and VS Code 1.139 hands it over in two
  steps that leave the page's `activeElement` on `<body>` (measured live), so
  `holdRevealFocus` refocuses the claim on a window `focus` that finds nothing
  focused, for `REVEAL_FOCUS_HOLD_MS` (1500 ms). A focus elsewhere is left
  alone.
- The host posts the frame again after the page's next `ready` (within
  `REVEAL_REPLAY_MS`, 5 s, while the revision is still shown), because VS Code
  discards a hidden panel's page and the panel does not retain its context.
- The shortcut sheet's note ends with the command
  (`src/ui/shortcuts.ts`).
- `test/reveal.test.mjs` covers the three kinds and the focus each leaves,
  the focus hold, folded groups, connections and findings, the older frames,
  malformed frames and unknown ids, the overlays closing, the walk following,
  a hidden rail opening, and every step card and every connection (all 41 and
  113 since the M3 review, not the first 40) on the canvas, above the sheet
  and clear of the index at 1440x900, 900x800 and 541x798 on the vit-cc and
  yolov5-cc2 shapes; a group, whose box can be larger than the canvas, is
  checked as selected only. `authoredRevealHandshake` in
  `test/authored-handshake.mjs` drives the real host with the built viewer.

Viewer M1 cleanup (no contract change):

- The bundle contains only the authored path. Inbound, the viewer handles
  `init`, `theme`, `workflow`, `workflowError`, `stale` and `actionResult`,
  plus `reveal`, `revealNode` and `revealIssue` (Reveal in Diagram, since
  viewer M3) and `restoreState` (the tests drive collapse with it); any other
  type is answered with a `log` frame and ignored. Outbound it posts
  `openLocation`, `workspaceHint`, `refineWorkflow`, `copy`, `exportFile` and
  `log`, and since viewer M3 `walk` (sent by the review walk); the host
  bootstrap posts `ready`.
- A saved `ViewState` with keys the viewer no longer writes (for example
  `showSuppressed` or `railGroupBy`) still loads; those keys are ignored.
- `MLGraph` carries only what an authored document fills in. Fields of the
  retired analyzer graph (ghost, confidence, suppression, ports, diff and
  rollup data) and the `concern:` scope presets are gone.
- The stylesheet is 14 files concatenated in the order `build.mjs` lists
  (viewer M2 removed `scope.css`; viewer M3 added `overview.css` after
  `rail.css`).

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
  `finding-pane` (that finding, then the Selection tab), `stale`, `stale-selected`, `narrow-selected` (900x800),
  and since viewer M3 `overview` (Shift+0), `overview-go` (Shift+0, Home, ↓ ↓,
  Enter: the move to phase 3) and `phase-list` (the phase index's list, opened
  from its pill below 1000 px). Pick some with
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
  Modern, Dark High Contrast; since viewer M4 also Dark+, Light+, Light High
  Contrast, Dark 2026 and Light 2026: `--theme dark-plus`, `light-plus`,
  `hc-light`, `dark-2026`, `light-2026`), a stub `acquireVsCodeApi`, and the panel's own
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
