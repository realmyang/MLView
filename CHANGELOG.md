# Changelog

Newest first. Entries before the 2026-09-18 removal of the static analyzer
(everything below "Unreleased — native workflow only") describe the retired
static analyzer; their figures are historical and are not rewritten. Current
truth lives in [docs/STATUS.md](docs/STATUS.md) and
[docs/VALIDATION.md](docs/VALIDATION.md).

## Unreleased — viewer M3: review walk and the way back

The viewer's third milestone, in progress. So far: the review walk, which goes
through the diagram claim by claim and opens each one's cited lines beside it
(roadmap step 11), the host side of that walk (step 12), a fix for Escape, a
look at the cost of jumping through a large notebook, the phase overview
with the labelled phase index that replaced the minimap (step 13), and
**Reveal in Diagram**, the way back from a cited line in the editor to the
claim in the diagram (step 14). Steps 11, 12 and 14 were checked by local
jsdom and mock `vscode` tests (mutation-checked against the fixes) and in an
isolated VS Code 1.139 Extension Development Host on macOS driven over the
DevTools protocol. Step 13 was checked by local jsdom tests and headless-Chrome
screenshots of a simulated host only, not yet in VS Code. Not tried on Windows
or Linux, with a screen reader or as a usability check. No contract change, no
new setting, no geometry change, and the version is unchanged. Step 14 adds
the extension's second command, with no default keybinding.

The review walk (step 11):
- Press `r` on the diagram, **Review** in the header or **Review the claims**
  in the **⋯** menu to go through the displayed revision claim by claim. The
  order is the diagram's: phase by phase, each step, then its outgoing
  connections, then the findings whose first cited step it is. A finding that
  cites no step (only connections, or the workflow as a whole) has no place
  in that order; the roadmap does not say where it goes, so these come last,
  in document order. Every step, connection and finding is visited exactly
  once: 79 claims (31 + 41 + 7) in the vit-cc shakedown artifact and 176
  (59 + 113 + 4) in yolov5-cc2, counted by the walk's own order on both
  documents and pinned by synthetic test documents of the same shape.
- The walk starts on **Not observed**, the claims marked inferred or
  unresolved: 7 in vit-cc and 16 in yolov5-cc2, the same numbers as the
  header's **N not observed**. The other filters are **Findings**, **All**
  and, only when VS Code reports changed or missing cited files, **Changed
  files**. Each shows its count; a filter with nothing in it is not offered.
- Keys while walking: `j` / `k` or ↓ / ↑ for the next or previous claim, `[`
  / `]` for the claim's quotes, Enter to open the current quote again
  (Alt+Enter also moves the focus to the editor), `n` / `p` for the next or
  previous finding in the walk's order, and `r` or Escape to end it. `u` starts
  the walk on Not observed, and `u` / Shift+U then step through those claims
  whatever the filter. ← and → still move to the nearest card. Outside the
  walk `j`, `k`, `[`, `]` and the arrows do what they did; the walk uses no Ctrl
  or Cmd keys.
- Each step selects the claim and brings it into view (a finding frames the
  steps it cites), shows it in the Selection tab (a hidden side panel or a
  collapsed bottom panel opens), and, once you stop for about 150 ms, opens
  its cited lines in the editor beside the diagram with the range highlighted
  while the keyboard stays on the diagram. A claim with no quotes opens
  nothing and says so, and the previous claim's highlight goes. A quote VS
  Code did not open (its file changed, went missing or has unsaved edits)
  shows the reason in the walk bar and under the quote in the Selection tab;
  nothing is opened and no notification appears. A screen reader hears, for
  example, "Claim 3 of 16, not observed: Step Load batches, inferred."
- The walk bar sits at the foot of the diagram, directly above the bottom
  panel's tabs (with the side panel, along the bottom of the diagram), and is
  shown only while walking: "Claim 3 of 16 · Not observed", the filters, the
  keys, **Exit**, and a line such as "In the editor beside: train.py · lines
  12–14, highlighted. Focus stays here." Below 620 px wide it is one row:
  "3/16", the filters and **Exit**; a quote that was not opened adds a warning
  mark there and the Selection tab says why. It sits under the diagram rather
  than under the header so the diagram stays within four Tab presses of the
  top, and Tab goes from the diagram to the walk's controls to the claim.
- The walk remembers where it was for each revision in the panel's saved view
  state: `r` resumes there, and a panel VS Code rebuilt brings a running walk
  back without opening anything until you move or press Enter. A new revision
  starts fresh. Nothing marks a claim as checked, and nothing is written to
  any file.
- The notice for changed cited files has **Review affected claims**, which
  walks the claims whose quotes cite those files.
- The header's **Review** button is shown from 620 px wide and folds into the
  **⋯** menu with the revision when the row is short; the menu always has it.
- Clicking or searching to another claim the walk holds moves the walk there
  without opening it (Enter opens it), and clears the earlier highlight.
- The walk counts every claim in the document; the severity toggles and the
  **N not observed** fade do not change what it visits.
- Live (vit-cc, VS Code 1.139, macOS, the diagram about 393, 543 and 902 px
  wide beside the notebook): `r` started the walk on 7 claims, each step
  opened the notebook beside it with the cited cell lines highlighted and the
  focus left in the diagram, `]` opened the second quote, Escape ended the
  walk, and no notification appeared. Found in that run: after `]` the
  second quote stayed below the Selection tab's fold. The tab now scrolls the
  walk's quote into view; that fix is checked in jsdom only, not live.

The host side, for the walk (added with step 11):
- A new `walk` message state, `clear`, sent when the walk moves to a claim it
  opens nothing for (no quotes, or a claim you only selected): the host clears
  the highlight and drops a walk open still on its way, as for the walk's
  end.
- A blocked walk open also clears the previous claim's highlight, so the
  editor never shows an earlier claim's lines while the walk says this one was
  not opened. A blocked Enter, double-click or Open link keeps it, as before.

Opening a cited range for the walk (`openLocation`, no change for Enter,
double-click or an Open link):
- An open can carry a sequence number (`seq`), a request id, `walk: true` and
  `highlight: false`. The host drops an open whose number is not above the
  last one it saw, and one a later open overtook while it waited (for example
  for a notebook cell's editor). A new page starts the numbering again. The
  walk waits about 150 ms after the reader stops moving before it asks for a
  jump.
- Each open with a request id gets one answer: done, blocked, cancelled or
  failed. A blocked answer names the reason and says nothing was
  opened, for example "vit_pytorch/efficient.py changed after revision
  cats-dogs-r1 was published; not opened." A changed, missing, unreadable or
  oversized file, a file in another folder, unsaved text that lost the cited
  lines, or a notebook cell that no longer exists is never opened.
- A blocked walk open raises no VS Code notification, since the walk shows the
  reason itself. A blocked open from Enter, a double-click or an Open link
  still shows its notification, as before.
- A new message tells the host the walk ended: it clears the cited-range
  highlight, including its mark in the editor's overview ruler, and drops a
  walk open still on its way. Closing the panel also clears the highlight.
- The check behind each jump is cached for the displayed revision and
  freshness. On a synthetic 200-cell, 3.8 MB notebook, 60 cell jumps hashed
  the notebook once instead of 60 times, and the extension host was busy for
  310 ms instead of 466 ms over the 12 s run. A file that changes on disk is
  checked again on the next jump, even before VS Code reports the change.

Escape:
- An Escape the viewer used (closing the menu, the shortcut sheet, the Refine
  popover or the legend, ending the review walk, collapsing the bottom panel, leaving focus mode,
  clearing the selection or the search) no longer also reaches VS Code. VS
  Code's webview forwards every key to the workbench, even one the page has
  handled, so a viewer Escape also hid a visible notification, which was
  measured live. The panel now stops such an Escape inside the page.
- When nothing is left to close and the focus is already off the diagram,
  Escape is left to VS Code, for example to hide a notification.
- The M2 report of the diagram losing focus when Escape followed an Enter that
  opened a notebook (vit-cc, the diagram alone at about 1430 px) was not
  reproduced in 14 live attempts, with waits from 150 ms to 7 s and a
  notification on screen. The fix above removes the one way found for a
  viewer Escape to act in VS Code as well; whether it was the cause of that
  report is not confirmed. After the fix, the same steps keep the focus in
  the diagram, nothing is forwarded, and the notification stays. Live, with
  a warning notification on screen, Escape in the search box cleared it and
  returned to the diagram, the next two cleared the selection and left the
  diagram, all with the notification still up, and only the fourth reached VS
  Code and hid it.

Notebook load (measured, see [docs/PERFORMANCE.md](docs/PERFORMANCE.md)):
- Over 60 paced cell jumps MLView's own code used about 40 ms of extension
  host CPU before and after the cache; the cache removed the 93 ms spent
  hashing the notebook again on every jump.
- Creating 2,000 files in the workspace called MLView's file watcher 1,157
  times for about 6 ms in total. The watcher adds no operating-system watcher
  and must see every cited file, so it was not narrowed.
- With Pylance running, the extra time was outside MLView's code. These runs
  cannot attribute it more finely, and no freeze was reproduced.

The phase overview (step 13):
- Press Shift+0 on the diagram, or choose **Phase overview** in the **⋯** menu,
  to see every phase at once. Each phase is a block: its number and name, its
  step count (with how many steps are inferred or unresolved), the findings
  that touch it, then its step titles in the Outline's order, a group before
  its steps. Inferred steps are marked ◌ and unresolved ones ?; observed steps
  carry no mark. Each title is followed by the F labels of its findings, for
  the severities the header's toggles show.
- An arrow between two neighbouring blocks says how many connections go from
  one phase to the next ("3 connections"). A connection that skips a phase or
  goes back to an earlier one is a bracket on the right with its count,
  dashed when it goes back. The header gives the connections as a sum, for
  vit-cc "6 phases · 31 steps · 41 connections: 19 inside a phase, 8 to the
  next phase, 14 skip ahead or go back."
- A block with more titles than fit lists its first ones and ends with "… N
  more steps", so every step is either listed or counted, and the counts add
  up to the document's steps. The longest blocks give up rows first, and no
  block drops below two titles and its count; past that the overview scrolls.
  The layout on the two shakedown artifacts: at 1440x900 vit-cc lists all 31
  titles and yolov5-cc2 52 of 59. At 900x800 they list 19 and 38. Beside the
  code at 541x798 the titles are one column: yolov5-cc2's four phases list 13
  titles and fit, while vit-cc's six phases list 13 titles and scroll a little.
- ↑ / ↓ (or ← / →), Home and End move between blocks. Enter, Space or a click
  goes to that phase at reading size, the same zoom rule as the first view
  uses for phase 1. The move takes about 240 ms, or happens at once with VS
  Code's Reduce Motion, the OS's reduced-motion setting or a screen reader.
  The selection does not change, and the next arrow key starts at that
  phase's first step. Escape, Shift+0 again or **Back** returns to the diagram
  exactly as it was, with the keyboard where it was. Any other key the
  diagram uses (for example `r`) closes the overview and then acts. The
  shortcut sheet, search and the legend open over it.
- A screen reader reads each block as a button, for example "Phase 2 of 6:
  Data preparation. 9 steps (1 inferred). 2 findings touch this phase. 3
  connections to phase 3; 1 connection ahead to phase 5. Enter goes to this
  phase.", described by its titles. Opening the overview announces the
  number of phases and steps and the keys.
- Shift+0 no longer folds every group and fits the diagram. **Fit the whole
  diagram** stays in the **⋯** menu, and each group keeps its own chevron.
- The overview is drawn over the diagram, not in it: nothing in the diagram's
  layout moves, and the geometry golden is unchanged.

The phase index (step 13):
- The labelled phase index replaces the minimap (the unlabelled overview map
  in the corner). It lists every phase in the diagram's lower right corner:
  the number in the phase's colour, the name, the findings that touch it by
  severity (a finding on two phases counts in each, as on the lane headings)
  and the step count. The phases in view are marked, and a row goes to that
  phase, as a block of the overview does.
- In a panel under 1000 px wide, or on a diagram under 350 px tall, it is one
  line naming the phase most in view, such as "4/6 Objective, optimizer &
  scheduler", which opens the list above itself; Escape closes it. Wide, the
  list's chevron folds it to that line. It sits inside the diagram, so in the
  bottom panel's layout it stays above the panel.
- It never covers the card you are on. Moving with the arrow keys, choosing a
  step in the Outline or in search, stepping through the review walk and VS
  Code's reveal all pan the least distance that keeps the card out from under
  it. A finding keeps its first cited step clear; a finding whose cited steps
  span more than the room beside the index can still have a later one under
  it.
- **Phase index** in the **⋯** menu (in place of **Overview map**) shows or
  hides it. It is disabled, with the reason, for a diagram with fewer than
  two phases. The choice is kept in the panel's view state, and a minimap you
  had collapsed opens as the folded index.

Checked for step 13: `webview/test/phase-overview.test.mjs` runs on synthetic
documents of the vit-cc and yolov5-cc2 shapes and small hand-made ones. It
covers the overview's layout at the canvases of 1440x900, 900x800 and 541x798
(every step listed or counted, the connection counts summing, blocks inside
the canvas, one or two columns), the keys, Escape giving the focus back, the
animation and reduced motion, the blocks' names, and the diagram's geometry
unchanged by the overlay. It also covers the index's rows and pill, and the
selected card never under the index along each path above, at all three
sizes. Removing the index's cover rule makes that last check fail. Headless
Chrome screenshots of vit-cc and yolov5-cc2 at the three sizes were looked at.
Not tried in VS Code, with a screen reader, on Windows or Linux, or as a
usability check.

Reveal in Diagram (step 14):
- Right-click a line in the editor and choose **Reveal in Diagram** to see
  which claims of the open diagram cite it. The Command Palette has it too, as
  **MLView: Reveal in Diagram**. There is no default keybinding; you can add
  one in VS Code's Keyboard Shortcuts. It is the extension's second command,
  next to **MLView: Open Generated Diagram**.
- The menu item appears only while an open diagram cites the file and the file
  still matches it: VS Code has not reported it changed or missing since the
  revision was published, and the editor's text still has the quoted lines
  where the diagram cites them. An unsaved edit that moves every quote hides
  the item until you undo it (checked at most every 150 ms while you type); an
  edit elsewhere keeps it, and a quote that moved no longer counts. The
  item's `when` clause is the context key `mlview.citedFile`, which is cleared
  when the last diagram closes.
- The cursor's line, or the selected lines, decide the claim. One claim cites
  them: it is shown at once. Several do: a list asks which, steps first, then
  connections, then findings, each in document order. Each row gives the kind
  and title (a finding's F label first, a connection as its two ends), then
  the connection's label, the finding's severity, the phase and the basis when
  it is not observed, and where it is cited; a finding's counter-evidence says
  so. A row from the tests' small document: "F1 Finding: Unverified output",
  "medium · Train · inferred", "Counter-evidence at lines 2–3".
- A line no claim cites offers the nearest claims in the file instead (at most
  30), each with how far it is, such as "Cited at lines 2–3, 1 line above".
  Choosing one shows it; Escape cancels. A notebook cell's nearest claims come
  from that cell first, then the nearest cells.
- The diagram selects the claim, opens a folded group that hides it, brings it
  into view and shows it in the Selection tab. A connection is framed with
  both ends where they fit, a finding with the steps it cites. A hidden side
  panel or a collapsed bottom panel opens, so the claim shows at 541 px as
  well as at 900 px. The shortcut sheet, the phase overview and the refine
  box close (the refine box keeps your text). The keyboard moves to the
  diagram, on the card or connection: the one place the viewer moves the focus
  by itself, because you asked for the diagram. Nothing is opened in the
  editor. During the review walk, the walk moves to the claim when its filter
  holds it.
- A diagram hidden behind another editor comes to the front. VS Code reloads
  a hidden panel's page, so the claim is shown again once the page is ready
  (within 5 seconds). If the diagram moved to another revision while you were
  choosing, it says so and asks you to run the command again.
- With several diagrams open, the one that cites the file is used; when more
  than one does, a list asks which, with the number of claims each has there.
- Notebooks: it works in a notebook's cell editors, by the cell index the
  diagram records. A notebook the diagram cites by cell, opened as plain JSON
  text, gets a message saying to open it in the notebook editor (and the other
  way round for a notebook cited as text).
- The menu and the palette hide the command where it does not apply. Run
  there anyway, from a keybinding of your own or because the file changed
  after the menu opened, it says why in one line: no diagram is open, the
  editor is not a cited file or cell, the file changed after the revision was
  published (ask the assistant for a fresh revision), its unsaved text no
  longer has the quotes, or the diagram cites the file from a parent folder
  that is not in the workspace. A changed file is checked again before the
  answer.
- How it finds the claims: each open diagram keeps an index of its validated
  revision's evidence, file by file, with the steps, connections and findings
  that cite each range. It is rebuilt when a new revision is shown and
  dropped with the panel. It reads no code and infers nothing: a line counts
  as cited when it lies inside a quoted range that still matches. No hover,
  CodeLens or Problems-panel entries are added to your editors.
- The webview takes one new host frame, `reveal {kind, id}`, for a step, a
  connection or a finding; the older `revealNode` and `revealIssue` frames go
  the same way. An id the shown revision lacks gets "That claim is not in the
  revision shown here." The shortcut sheet's note mentions the command.
- `scripts/vsix_check.py` now allows the second command in a packaged VSIX.

Checked for step 14: `vscode-extension/test/reveal-host.test.js` (19 tests,
mock `vscode`) covers the index, the nearest claims and the list's rows, the
context key for cited, uncited, changed, edited and closed files, the index
rebuilt on a new revision, one claim shown at once, the list for several and
for the nearest, the plain messages, the parent-folder case, two diagrams
citing one file, the reveal sent again after the page's `ready`, a revision
changing while you choose, notebook cells, and everything disposed with the
last panel. `packaging.test.js` and `activation.test.js` were changed on
purpose to name the second command and to check it has no keybinding.
`webview/test/reveal.test.mjs` (17 tests, jsdom) covers the frames for the
three kinds and the focus they leave, folded groups, connections and
findings, the older frames, malformed frames and unknown ids, the overlays
closing, the walk following, a hidden side panel opening, and, at 1440x900,
900x800 and 541x798 on the vit-cc and yolov5-cc2 shapes, every step and
connection revealed on the canvas and clear of the phase index. An
integration test drives the real host with the built page. Removing the
stale check, the quote check, the focus move, the replay, the index refresh,
the diagram list, the connection case or the side panel opening each makes a
test fail.

It was also tried live in an isolated VS Code 1.139 Extension Development
Host on macOS, on the vit-cc artifact, driven over the DevTools protocol with
the window at 1440x900. The menu item showed on the cited `efficient.py` and
not on `README.md`. A line cited by a step, a connection and a finding gave a
list of three; choosing the connection selected it and opened the bottom
sheet with the diagram 541 px wide. A line with one claim showed it at once,
and Enter on it then opened the code beside with the focus kept. An uncited
line offered the nearest claims. At 866 px (the narrowest the editor beside
allowed, not 900) a finding was framed clear of the phase index. In a
notebook cell the list showed six claims and the step was revealed. A diagram
hidden behind the code came to the front and showed the claim after its page
reloaded. An unsaved edit at the top of the file hid the item and undo
brought it back. After the diagram closed, the item was gone. The live run
showed that VS Code's hand-over of the focus left it on the page's body, so
for 1.5 seconds after a reveal the claim takes the focus back if nothing else
has it; checked live afterwards. A changed file was checked only by the unit
tests, not live. Not tried with a screen reader, on Windows or Linux, or as a
usability check.

## Unreleased — viewer M2: readable at your width

The viewer's second milestone: a diagram you can read in the panel beside your
code. Up to the review fixes these changes were checked by local tests and
headless-Chrome screenshots of a simulated host only. A live check in an
isolated VS Code 1.139 Extension Development Host on macOS, with keys and
clicks sent over the DevTools protocol, then found the problems the live-check
fixes below correct, and those fixes were checked the same way. None of it has
been tried with a screen reader, on Windows or Linux, or as a usability check.
No contract change, no new setting, and the version is unchanged.

Calmer cards (the one deliberate geometry change):
- Cards no longer carry a `basis=observed` chip row, and connection labels no
  longer end in " · observed". The basis is drawn only where a claim is not
  observed (see below). A card without an authored detail shows its kind on
  the second line, never the basis.
- Each expanded card is 26 px shorter. Most documents get shorter, but not
  all: shorter cards change how ranks wrap, so some grow taller. On public
  shakedown artifacts the canvas went from 2088x2620 to 2132x2480 px (vit,
  Claude Code) and from 2140x5503 to 2184x5016 px (yolov5); the repository
  sample went from 956x1735 to 712x1592 px; the synthetic 120-step document
  went from 2086x3018 to 1354x3514 px and the expanded renderer fixture from
  954x3112 to 710x3464 px. Collapsed groups keep their count chip, so they are
  unchanged.
- The geometry golden (`webview/test/geometry-golden.test.mjs`) was
  re-recorded once for this, in its own commit; nothing else in M2 moves it.
- `MLEdge.authoredLabel` is gone: `MLEdge.label` is the authored label. The
  connection's accessible name says "inferred, not observed" or "unresolved"
  for the exceptions instead of repeating the basis through the label.

A calm canvas (layout unchanged; the geometry golden is byte-identical):
- Only the exceptions are marked. An observed step or connection carries no
  basis mark. An inferred one has a dashed border or line and an `inferred`
  tag; an unresolved one has a dotted border or line, faint hatching and a
  `? unresolved` tag. The tags and dashes stay the same size on screen as you
  zoom, so they are still visible when the diagram is zoomed out. The Outline
  marks the exceptions the same way.
- Line style now means certainty, not connection kind: solid is observed,
  dashed is inferred, dotted is unresolved. Every connection has the same
  arrowhead. The kind is written in the hover card and the Inspector, and the
  legend lists the kinds the diagram uses with how many connections have each.
- Each phase gets a colour by its place in the document, shown as a thin rule
  on the lane's left edge and on each card's left edge. Every phase is
  coloured now; before, only the eight analyzer-era phase ids had a colour, so
  most authored phases were grey. Colour is otherwise used only for problems.
  (Tones 2 and 3 changed in the live-check fixes below, to keep clear of the
  warning and error hues.)
- Connections and card borders are easier to see: at least 3:1 against the
  canvas in Dark Modern, Light Modern and Dark High Contrast (WCAG 1.4.11),
  computed from VS Code 1.139's theme colours. Connections went from 1.86-3.59:1
  (by kind) to 3.97:1 on Dark Modern and from 1.94-4.59:1 to 3.87:1 on Light
  Modern; card borders from 1.27:1 to 3.26:1 and from 1.26:1 to 3.31:1.
- A header toggle, "7 not observed (3 steps, 4 connections)", fades the
  observed claims so the inferred and unresolved ones stand out. It fades
  fills and lines only, so every title stays readable (4.5:1 or better). It is
  hidden when every claim is observed. Below 1200 px wide it reads "7 claims
  not observed" and the breakdown is in its tooltip; when the header row is
  too full it moves into the ⋯ menu with its count and breakdown (see the
  header below). This step first added it to the toolbar, which step 10
  replaced with the header row.
- Finding badges name findings `F1`, `F2`… in document order (`F2 F5 +1` when a
  step has several). A new revision can renumber them; the hover card, the
  Findings list and the Inspector show the real id with the number (under
  the title for a finding listed on a step, since the live-check fixes), and
  Refine and Challenge prompts use the real id.
- Every count names its unit: "31 steps · 41 connections", "7 findings",
  "6 coverage limitations", "medium · 2 findings", "5 steps" on a lane or a
  group. Phase counts read "2 findings touch this phase": a finding that cites
  two phases still counts once in each, so the phase counts can add up to more
  than the total.
- Motion settles. A hover or focus-mode (F) flow runs two passes and then
  stays still, showing direction with static marks; Shift+A plays it again.
  VS Code's own Reduce Motion setting (the `vscode-reduce-motion` class on the
  webview) now stops the animation and transitions, as the operating-system
  setting already did.
- The SVG export draws the same tags, dashes and phase colours.
- The screenshot harness gained `focus-settled`, `exceptions` and `legend`
  states, and finds the severity chips by `data-severity`.

A readable first view, and readable titles zoomed out (layout unchanged; the
geometry golden is byte-identical):
- The diagram opens at a zoom where you can read the cards. If the whole
  document fits at 62% or more, it opens whole, as before. Otherwise it opens
  on the first phase at 90% (card titles about 11.7 px on screen), with the
  phase's top-left corner and the routing channel on its left in view; if the
  whole first phase fits at 75% or more, it is fitted instead. A view saved
  for the same revision still comes back as you left it.
- First-paint zoom, measured with the screenshot harness on public shakedown
  artifacts at 1440x900, 900x800 and 541x798 (the measured beside-the-code
  width): vit (Claude Code) 48%, 40%, 17% -> 90%, 90%, 90%; yolov5 (Claude
  Code) 47%, 39%, 23% -> 84%, 90%, 90%; dino (Copilot) 59%, 50%, 35% -> 86%,
  90%, 90%. Card titles on screen went from 5.8, 4.8 and 2.1 px (vit) and
  5.7, 4.7 and 2.7 px (yolov5) to 11.0-11.7 px at every width. The repository
  sample opens at 90% at all three widths (was 71%, 56%, 50%). The trade-off:
  the first view shows the first phase, not the whole document. At 541 px the
  canvas is only about 480 px tall under today's header, so 1 to 6 whole
  cards are in view.
- Press `0` to come back to that view from any zoom. Before, `0` fitted the
  whole document once you had zoomed out below 50%. The old toolbar's "Fit to
  view" button is now **Fit the whole diagram**, an item of the header's ⋯
  menu (step 10), and always shows the whole document with its groups as they
  are; Shift+0 (Overview) still folds every group first.
- Zoomed out (below 62%), a card shows only its title, sized to be read:
  about 11 px on screen, on two lines (three for a long title), never spilling
  out of its card or cut through a line; the full title is in the hover card.
  Titles stay at 10 px or more down to about 35% zoom (43% for a step with no
  evidence, whose card is shorter); further out they shrink with the card.
  On the public artifacts they measured 10.1-12.2 px from 52% down to 36%,
  8.6-8.9 px at 30% and 5.0-5.2 px at 17%; before, they were 6.3 px at 52%,
  4.3 px at 36% and 2.1 px at 17%. Zooming never lays the diagram out again:
  titles change size only when the zoom crosses one of the steps the canvas
  already uses for its constant-size marks.
- First tried as specified, titles held at 11 px at every zoom with the lines
  they need. On the real layout that failed: from 43% down every title
  overflowed its card and was cut through a line, and at 25% a card showed
  about a tenth of its title. Capping the size to what fits the card's own box
  is what makes it work.
- At that level the `inferred` and `? unresolved` tags hang from the card's
  bottom edge instead of sitting across it, where they covered the title's
  last line.
- Between 62% and 77% zoom (full detail) card titles are still 8-10 px; full
  detail is unchanged in this step.
- Cost, measured in headless Chrome at 900x800 from Chrome's main-thread
  counters (script, style and layout), descriptive and not a CI budget: a
  wheel-zoom event costs 0.2 ms (median); crossing a zoom step costs 2.8-6.4 ms
  on vit and yolov5 (2.7-4.9 ms without the compact-title change), 6.1-8.7 ms
  on the synthetic 120-step document, and 40-60 ms on a synthetic 1,000-step
  document, with one 73 ms outlier in four runs (38-49 ms without it).
  Hovering a card costs 3-4 ms on the public artifacts, 5-7 ms on the 120-step
  document and 26-32 ms at 1,000 steps, with or without it.
- The screenshot harness gained `compact` (zoom out below 62%) and `whole`
  (Fit the whole diagram) states and a `titles` fact: on-screen title size,
  lines shown and how many titles end clamped.

One header row and a quiet status bar (layout unchanged; the geometry golden
is byte-identical):
- The brand row, the toolbar of 21 controls, the phase chip row and the
  authored header are now one row about 36 px tall. In order: the title (cut
  with an ellipsis, the whole title on hover); a chip with the assistant and
  the revision, whose dot turns amber only when a cited file changed or went
  missing; search; the severity toggles, each with its count (a severity with
  no findings has no toggle, and the counts are no longer repeated in the
  status bar); "N not observed", which fades the observed claims; a ⋯ menu;
  and **Refine…**, which names what it will refine by its label, for example
  "Step: Compute loss" (the prompt still carries the stable id).
- What the row keeps depends on the panel's width. At 1200 px and wider:
  everything, with the "not observed" breakdown in brackets. Below 1200 px
  the breakdown moves to the tooltip ("7 claims not observed"). Below 1000 px
  search folds behind an icon and the chip shows only the revision. Below
  620 px (541 px is the measured beside-the-code panel) only the title, the
  severity toggles, "not observed", ⋯ and **Refine…** stay; search and the
  revision move into the ⋯ menu. (The review fixes below add a measured fit
  for rows that are still too full.)
- The ⋯ menu holds the legend, the connection flow animation, the overview
  map, the side rail, **Fit the whole diagram**, zoom to the selection,
  **Export SVG…**, **Export PNG…**, **Copy SVG** and the shortcut sheet. The
  exports are always the whole diagram: Copy PNG, Print and the choice of
  region went with the old export menu.
- The request and coverage details (the question, scope, entrypoints,
  configuration, coverage summary, limitations and provenance) no longer sit
  above the canvas and push it down. This step first opened them over the
  diagram; steps 5 and 9 replaced that with the rail's About tab, which the
  revision chip and the status bar's coverage item open (below).
- The scope picker is gone: its depth and unit lists, **Scope to this unit**
  and **Scope … this codebase**, the breadcrumb and its copy button, and the
  `s`, Shift+S, `[` and `]` keys. So are the phase chips that hid phases. The
  whole document is always drawn; collapse groups or use focus mode (F) to
  narrow what you look at. A view saved by an older viewer still opens: its
  scope and phase filter are ignored and not saved again.
- The status bar is about 22 px: "31 steps · 41 connections", then
  "Coverage: scoped · 6 limitations" (which opens the details), then the
  source freshness, then the zoom with − and + (beside the code only the
  readout; the keys and the wheel still zoom). Freshness is muted text when
  nothing is stale ("2 cited files unchanged", or "Freshness not checked" for
  a revision published without hashes) and a warning icon with words only for
  changed or missing files. "Unchanged" means the quoted lines still exist as
  published, not that they support the claims. The old chip row's folded
  "notes about this run" are gone; the limitations are counted here, once.
- Ctrl+F (Cmd+F on macOS) focuses search from anywhere in the viewer, and `/`
  from the diagram, and opens a folded field (Ctrl/Cmd+K did too until the
  live-check fixes below). Results show the title first and the
  location under it (cut from the start, so the file name and line stay),
  headed by a count with its units ("2 matches: 1 step, 1 finding"). A
  finding's Inspector shows its title once. The shortcut sheet and the legend
  say all this.
- The chrome's 19 icons are inline SVGs drawn for MLView in the style of VS
  Code's codicons. There is no icon font, so the webview's
  `default-src 'none'` policy is unchanged.
- Measured with the screenshot harness (headless Chrome, a simulated host,
  the five harness documents, initial state): the chrome above and below the
  canvas went from 203 px to 58 px at 1440x900, from 201-244 px to 58 px at
  900x800 and from 299-348 px to 58 px at 541x798, so the canvas went from
  77% to 94%, from 69-75% to 93% and from 56-63% to 93% of the panel height.
  This is layout, not a usability result.
- Removed from the API: `setScope`, `getScope`, `scopeToNode` and
  `Filters.stages`. The screenshot harness records the header's layout,
  height and controls, the chrome above and below the canvas, and the search
  match count; its `whole` and `search` states use the ⋯ menu when needed.

About, a claim-first Selection pane and a bottom sheet (layout unchanged; the
geometry golden is byte-identical):
- The rail's tabs are now **About · Findings (n) · Selection · Outline**.
  Selection is the old Inspector. A new revision opens on About; after that
  the viewer keeps the tab you chose, saves it with the view and restores it
  when the panel is reopened on the same revision. Selecting a card, a
  connection or a finding switches to Selection; only a selection made from
  the Findings list or the Outline on screen (a row, or `n`/`p` for findings)
  keeps that list in place, with the selection marked in it (as corrected by
  the review fixes below). The live region announces the selection (not
  tried with a screen reader).
- About replaces the request and coverage details that opened over the
  diagram. It holds only what the assistant wrote: **Asked** (the question,
  cut after four lines with **Show all**); **What the model traced** (the
  coverage summary, split into paragraphs at its own run-in heads such as
  "Data:" and "Model:" when it has at least three, otherwise shown as
  written); **Coverage** in plain words with the limitations listed once;
  **Scope** and the entrypoints; **Run configuration**, with `key=value`
  tokens in monospace; **Cited files**, each with its freshness; and
  **Provenance** (host, model, revision, publication time) with the line
  "Model-authored; MLView checks citations, not the interpretation." The
  revision chip, the status bar's coverage item and the ⋯ menu (below 620 px)
  open it; from the keyboard they also move the focus into it.
- The Selection pane reads in this order for a step: phase number and name,
  kind and parent group; the title; a one-sentence basis note only for an
  inferred or unresolved claim; the full detail; **Findings on this step**,
  each with **What to change** (its title opens the finding); the quotes,
  numbered, with their line numbers, a freshness word each ("unchanged" and
  "not checked" in muted text, a warning icon and words only for a changed or
  missing file) and **Open**; "Comes from …" and "Feeds …" as sentences whose
  steps and labels are links; **Challenge this claim** and **Refine…**; and
  one line that says how many document-wide limitations apply, linking to
  them in About. A connection's pane shows its kind in words, its label, from
  → to, its basis, its findings and its quotes. A finding's pane shows its
  severity, its F-number and real id, the title, the description, **What to
  change**, the steps it cites and its quotes (supporting and
  counter-evidence). Every section count names its unit ("2 quotes",
  "3 steps"). The basis is said once.
- Selecting a finding now frames every step it cites, not just the first,
  zooming between 45% and 100% as needed (a finding that cites no step frames
  its connections). If the steps are too far apart even at 45%, the view
  centres on the first one.
- Below the width where a docked rail would leave the canvas under 900 px
  (1260 px with the default 360 px rail), the rail is a bottom sheet under the
  canvas instead of a drawer over it. Collapsed it is a 32 px tab strip; a
  selection opens it to about 47% of the height (drag the handle, or use its
  arrow keys, for 25-75%), and the selected card stays in view above it
  without a refit. The chevron, Escape, or a press on the handle collapses it;
  Escape returns the focus to the diagram, and from the diagram Escape
  collapses an open sheet before it clears the selection. The canvas always
  keeps at least min(240 px, 45%) of the height. In a sheet 620 px or wider
  the Selection pane has two columns: the claim, its findings and its
  connections on the left, the quotes and the actions on the right; narrower,
  one column. The sheet is a labelled region, not a dialog; the diagram stays
  within four Tab stops of the top. `t` moves the focus to the panel's current
  tab, opening the panel first, and the tab strip's arrow keys pick About,
  Findings, Selection or Outline (this step shipped Ctrl+1 to Ctrl+4, which the
  live-check fixes below replaced). The ⋯ menu's rail item reads "Side panel"
  or "Bottom panel".
- Measured with the screenshot harness (headless Chrome, a simulated host,
  vit from Claude Code and dino from Copilot): at 900x800 and 541x798, a click
  on a step used to slide a 360 px drawer over the right of the canvas (two
  thirds of it at 541 px), half covering the card just clicked. Now the sheet
  opens below: the canvas is 900x393 or 541x392 px above a 349 px sheet, and
  the selected card or connection was wholly inside the canvas in all 16
  narrow selection shots. Collapsed, the tab strip costs 32 px of canvas
  height (900x710 instead of 900x742). At 1440x900 the canvas is 1080x842 px,
  as before. This is layout, not a usability result.
- The `?` shortcut sheet and the Refine… popover keep Tab and Shift+Tab inside
  themselves and give the focus back to what opened them (the Challenge
  button, Refine…, or the diagram) when they close.
- With VS Code's screen-reader optimisation on (the
  `vscode-using-screen-reader` class on the webview), a selection is
  announced by its claim (the title, the basis when it is not observed, and
  the first sentence of the detail or the finding's description), and the
  flow animation and transitions stop, as under Reduce Motion.
- The empty Findings list now says the limitations are "listed in About".
  The screenshot harness gained `select-connection` and `finding-pane`
  states and records the rail's mode, box and columns and whether the
  selection is inside the canvas.

Review fixes (an independent review of the branch; each fix has a regression
test in `webview/test/m2-review.test.mjs` or an updated existing test, checked
to fail on the build before the fix; the header and status-bar numbers come
from headless-Chrome probes of a simulated host, not a live VS Code window or
a screen reader; the geometry golden is byte-identical):
- Tab reaches the header again at every width. Its single tab stop could sit
  on a control the stylesheet hides (the revision chip beside the code, the
  search icon at 1000 px and wider), so Tab skipped the whole header at
  541 px and ArrowRight stopped dead at 1440 px. The roving group now skips
  controls that are not rendered, and re-derives the stop whenever the row
  changes shape; search results are reached with the field's arrow keys,
  never by Tab. Probed at 541, 900 and 1440 px: one shown control holds the
  stop and the arrows visit only shown controls.
- The header row always fits, Refine… included. After every change it
  measures itself and, while it overflows, folds the revision chip (About
  stays in the ⋯ menu), then "not observed" (into the ⋯ menu as a checkbox
  item with its count and breakdown), then the title (still read by screen
  readers); only while the search field is open beside the code are the
  severity toggles folded too, and they come back when it closes. Probed with
  four documents from 1440 down to 320 px, search open and closed.
- Every count on the header names its unit on screen: the severity toggles
  are followed by "findings", and "not observed" reads "7 claims not
  observed" below 1200 px and "7 not observed (3 steps, 4 connections)" at
  1200 px and wider.
- A severity toggle that is off is struck through with a dashed border, not
  faded to half opacity, so its count keeps the text colour.
- **Refine…** draws the theme's button foreground (a reset rule had
  outranked it, so the label took the header's text colour), and in High
  Contrast it keeps its border (`button.border`, else `contrastBorder`).
- Beside the code the status bar keeps a stale-files warning whole ("1 of 18
  cited files changed"); the coverage item gives way first and drops its
  "Coverage:" prefix (the full text stays in its name).
- Ctrl/Cmd+F (and Ctrl/Cmd+K, until the live-check fixes removed it) no
  longer pulls the focus out of the shortcut sheet or the Refine… popover.
- Selecting from the canvas shows the claim again, as in M1: a click on a
  card or connection, a search hit for a step, a link in the Selection pane
  and the host's reveal all switch the rail to Selection; a click and a
  search hit also open a collapsed bottom sheet. Only a selection made from
  the Findings list or the Outline while that list is on screen keeps the
  list in place; `n` and `p` count as the Findings list.
- A claim being read in the docked rail stays open when the panel narrows
  into the bottom sheet.
- A group's Selection pane lists the findings inside the group ("Findings in
  this group", as its badge counts them), its steps as links ("Steps in this
  group", with their count), and the connections that cross its edge ("Comes
  from … into …", "Feeds … from …"); it says "group", not "step".
- An observed finding carries no basis mark in the Findings list or the
  Selection pane; an inferred or unresolved one carries the canvas tag, as
  visible text.
- Selecting a finding that cites a step and a connection elsewhere frames
  the step and both ends of the connection when they fit at 45% zoom;
  otherwise it frames the steps, as before.
- The bottom sheet's handle never reports more height than the canvas floor
  (min(240 px, 45%)) leaves, and a drag that collapses the sheet keeps the
  height it had for the next time it opens.
- Announcements and accessible names say steps and connections, never nodes
  and edges ("Workflow loaded: 31 steps, 41 connections, 7 findings (2 high
  severity)." with no "0 high severity"); `n` and `p` announce the F label
  first, then the real id ("Finding F1 (loss-risk), medium severity: …").
- A lane's per-severity numbers are followed by their total ("· 5 findings
  touch this phase"); the phrase used to follow the last number, so "1 1
  findings touch this phase" read as one finding. The SVG export says the
  same.
- A card with an authored detail shows two lines of it where the file:line
  row was; the place stays in the card's accessible name, the hover card and
  the Selection pane. A card without a detail keeps its file:line row. Card
  heights are unchanged, and the SVG export draws the same face.
- A hover no longer dims the other cards: the directly connected cards get a
  ring and their connections light, and nothing fades. Focus mode (F) still
  fades the rest and makes it inert, as before, High Contrast included.
- A lane heading is numbered ("2 Data preparation"), in the text colour at
  the card title's size, on a tinted plate, and no longer upper case. The
  Outline numbers its phases the same way ("2 · Data preparation") and puts
  the phase's finding count on its own line, so the name is not cut.
- Not changed (deferred): a document whose whole fit is between 62% and
  about 85% still opens whole at that zoom, where card titles are 8-10 px on
  screen (dino at 1440x900 opens at 72%). Raising the threshold or applying
  the compact titles in that band is a first-view design change left for the
  next step.
- Cleanup: `STATUS.md` no longer lists scope filters. The benchmark tools
  (`webview/tools/benchmark-workflow.mjs`, `benchmark-browser.mjs`) ran into
  the removed scope API and the retired export request; they now time mount,
  select, SVG export (from the ⋯ menu), update and dispose, and
  `docs/PERFORMANCE.md` says the dated scope columns are historical. Dead
  remnants of the scope picker, the phase chips and the export regions are
  gone: the `.mlv-chip--stage` rules, the `--mlv-fg-boundary` token and its
  palette field, the always-false node filter and its `.is-filtered` styles,
  the flow's projection hook, two unused raster exports, and the "current
  view" export region (`exportFile.scope` is always `all`).
- Earlier bullets in this section that the later steps superseded now
  describe what ships, and the compactness claim names the documents that
  grew taller.

Live-check fixes (a live check of the branch in an isolated VS Code 1.139
Extension Development Host on macOS, at about 1430, 900 and 541 px, driven
over the DevTools protocol; each fix has a regression test, checked to fail on
the build before the fix: `webview/test/m2-live.test.mjs`, the hue test in
`webview/test/calm-canvas.test.mjs` and the "live fix 2" tests in
`vscode-extension/test/verification-loop.test.js`; "checked again live" below
means the same kind of host and driver, not a screen reader or a usability
check; the geometry golden is byte-identical):
- A selection the layout hid is shown again. With the diagram alone at about
  1430 px and the first view untouched, a card selected beside the docked rail
  ended under the open sheet when Enter opened the source beside the panel and
  halved it: the first view was refitted for the new size, anchored on phase 1.
  Now, when the panel resizes or the rail changes shape (docked to the sheet,
  the sheet opening, collapsing or being dragged) and a selection that was
  wholly in view no longer is, the diagram pans the least distance that brings
  it back, 16 px inside the edge it comes in from, at the same zoom, and is
  not refitted. A selection the reader had already moved out of view stays
  where it is, and nothing moves except on such a change. Checked again live:
  from 1382 to 691 px the selected card ended wholly above the open sheet.
- A jump reuses an editor group. At 541 px beside a notebook, Enter on a .py
  citation opened a third editor group and the diagram dropped to 271 px,
  which clipped **Refine…**: a notebook's cell editors report no column, so
  M1's rule fell through to "beside". The source now opens in an existing
  group other than the panel's own: the group already showing the cited file,
  else the group of the previous jump while it exists, else the group last
  used outside the panel, else the open group nearest the panel. Only a
  diagram alone in the window opens a group beside it. Text files and
  notebooks go to the same group, focus stays in the diagram, and the cited
  range is still selected and highlighted. Checked again live: the .py file
  opened as a tab in the notebook's group, and the diagram kept its 541 px
  and **Refine…**.
- Phase colours keep clear of the warnings. Tone 2 (#C9A56B dark, #8D6E2F
  light), the third phase's, was 2-14 degrees of hue (HSL and OKLCH) from
  `editorWarning.foreground`, the amber the stale mark is mixed from, so a
  stale card in that phase read as one colour. Tone 2 is now a
  green (#4CA871 dark, #0A693C light), and tone 3, which sat 30 degrees of hue
  from the error red in Dark Modern, a magenta (#D684C5, #A0388F). A test
  computes from the screenshot harness's theme table (Dark Modern, Light
  Modern, Dark High Contrast) that no tone is within 30 degrees of HSL or
  OKLCH hue of `editorWarning.foreground`, the stale mark or
  `editorError.foreground`, and that no two tones are closer than 0.06 in
  OKLab (the closest pairs, among the unchanged teal, cyan, slate and blue
  tones, are 0.067-0.069 apart, as before); the 3:1
  contrast test still passes. The SVG export uses the same tones. Tones 5 and
  7 stay near the low-severity blue, which was not part of this fix.
- The ⋯ menu's **Overview map** tells the truth. At 900 px wide or narrower
  the map is not drawn, yet the item showed it checked. The item is now
  disabled and unchecked whenever the map is not drawn, with the reason on a
  second line: no room at that width, a canvas under 350 px tall, or fewer
  than 30 cards. The width rule moved from a media query into the viewer (the
  `is-narrow` class), so the map and the menu cannot disagree. Checked again
  live at 541 px.
- Keys that VS Code leaves alone, labelled for the platform. A focused
  webview hands every key to the workbench as well. Measured live on macOS:
  Cmd+B toggled the side bar as well as the viewer's panel; Cmd+K focused the
  search and started a workbench chord, so the next key went to the chord;
  Ctrl+2 brought the diagram's group to its second tab, hiding the diagram
  (VS Code's Open Editor at Index; Cmd+1 to Cmd+8 focus editor groups). By
  VS Code 1.139's own keybinding table, Ctrl+B, Ctrl+K and Ctrl+1 to Ctrl+8 do
  the same on Windows and Linux, and Alt+1 to Alt+9 open an editor by index.
  The viewer now answers no Ctrl or Cmd chord but the find key: Ctrl+F
  (Cmd+F on macOS) and `/` focus search; `b` shows or hides the side panel or
  opens or collapses the bottom one (it was Ctrl+B); `t` moves the focus to
  the panel's current tab, opening the panel, and the tab strip's arrow keys
  pick a tab (it replaced Ctrl+1 to Ctrl+4). Ctrl/Cmd+K is gone. The
  shortcut sheet, the ⋯ menu and the search button print the keys for the
  platform (⌘F, ⇧0, ⌥Enter on macOS). Checked again live on macOS: Cmd+B
  toggled only the side bar, `b` only the panel, Cmd+K only started the
  chord, `t` focused the tab and Cmd+F the search. Windows and Linux were not
  tried.
- A finding's id under "Findings on this step" is one line. It sat in a
  narrow column right of the title and broke letter by letter
  ("f-plot-/not-/random"); it is now a muted monospace line under the title.
  The F-label stays beside the title, and the finding's own pane keeps the id
  beside its F-label.
- Reopening a hidden panel keeps the selection and an open bottom sheet.
  VS Code rebuilds a hidden panel's page when it is shown again; the tab came
  back, but the selection and the open sheet did not. The saved view now
  records an open sheet (`sheetOpen`, absent when the sheet is collapsed or
  the rail docked), and a remount of the same revision restores the selection
  and the sheet with the tab. A selection saved for another revision, of a
  kind the viewer does not have, or for an id the revision lacks is dropped.
  Checked again live at 541 px: hidden behind another tab (the page was
  destroyed) and shown again, the panel came back with the step selected, the
  sheet open and the Selection tab. In jsdom the build before the fix already
  kept the selection across a remount, so why the earlier live run lost it
  was not established; the restore is now explicit and pinned by a test.
- Not changed: the first-view thresholds; the deferral above (A11Y-7) stands.

An independent live re-check of these fixes passed all eight items. It also found two
faults older than M2. Space on a focused, selected group toggled it twice, so
nothing happened: the card's handler and the canvas's both answered the key.
The card now stops the event, as it already did for Enter, and a test pins it.
Not fixed yet: after Enter opens a notebook that was not open, the next Escape
can take keyboard focus away from the diagram (the workbench gets it). It
happens on the build before M2 too, and is carried to M3, whose review walk
depends on focus staying put after a jump.

## Unreleased — viewer M1: verification loop and cleanup

Step 1 of the viewer's first milestone: check a claim against its source
without losing your place in the diagram, and see where a cited file changed
on the diagram itself. These changes are checked by local tests only (jsdom
and the mock `vscode` module in `vscode-extension/test/verification-loop.test.js`
and `webview/test/verification-loop.test.mjs`); none of it has been tried in a
live VS Code window. No contract change, no new setting, and the version is
unchanged. The diagram's layout is unchanged (the geometry golden is
byte-identical).

Opening source (`vscode-extension/`):
- A jump opens the cited file beside the diagram and leaves focus in the
  diagram, so the arrow keys and Enter keep working. The whole cited range is
  selected and highlighted in the theme's range-highlight colour; the
  highlight moves to the next jump and is removed when the panel closes.
- Alt+Enter (or Alt+click on an Open link) opens the same range and moves
  focus to the editor. VS Code binds Alt+Enter only in editors, notebooks,
  chat, search, testing and the terminal, not in a focused webview.
- A notebook citation opens the notebook beside the diagram with the cited
  cell selected and revealed. Its lines are highlighted when VS Code has the
  cell's editor ready within about half a second; otherwise only the cell is
  selected.
- A jump into a file whose saved bytes match the last check no longer
  revalidates the whole revision first. A file that changed is still checked
  before the jump, and the jump is refused if it went stale.

Clicking (`webview/`):
- A click on a card, connection, finding or Outline row selects it and shows
  its claim in the Inspector; it no longer opens source. Enter, a
  double-click and the Inspector's Open links open the cited range. Space
  selects a finding row without opening it. The shortcut sheet, the legend
  and the docs say so.

Freshness on the diagram:
- The extension's `stale` message now lists each stale file with its reason
  (changed, missing, unreadable, too large). Cards, connections and findings
  that cite such a file get a warning mark whose tooltip and screen-reader
  label say how many quotes are affected. In the Inspector each stale quote
  says why and its Open link is disabled. The status bar shows a short count,
  for example "1 of 4 cited files changed". Unchanged files get no mark and no
  colour.
- Once the diagram is shown, the extension's banner is drawn under the header
  with an icon instead of as plain text above the diagram. "Checking source
  freshness" goes to the status bar, so the layout does not jump on each save.
  The plain-text banner remains only for errors before anything can be shown.

Wrong workspace root (`vscode-extension/`):
- When most tracked files are missing from the workspace root but exist, with
  the published hashes, under the artifact's folder or a folder between it and
  the root, the banner names that folder and says the files there are
  unchanged, instead of saying the files no longer match (its wording changed
  again in the review fixes below). It
  offers **Add folder to workspace** and **Open folder** (a new window). The
  extension never resolves a citation against another folder by itself; the
  panel rechecks whenever the workspace folders change.

Step 2: the Inspector shows the claim (`webview/`, rebuilt into
`vscode-extension/media/`). Checked by local jsdom tests only
(`webview/test/inspector-content.test.mjs`, which loads the shipped
stylesheet and checks visibility, plus updated cases in `authored-ui` and
`workflow`); not tried in live VS Code. The cards, the chip row and the edge
labels are unchanged, so the geometry golden is byte-identical.

- The Inspector shows a step's full authored detail as a paragraph under the
  title, the phase label (never the phase id) and the kind. Before, the detail
  was only in the hover card.
- The monospace line that repeated the title is gone. The basis appears once,
  as a chip: the Attributes table no longer repeats it, and a connection's
  title is its authored label without the " · basis" suffix. An inferred or
  unresolved claim gets one sentence saying what that means; observed gets
  none.
- A finding's suggestion is shown, labelled "What to change", in the Inspector
  and in the expanded Findings row. A rule left from the static analyzer had
  hidden every suggestion while the "Suggested check" heading stayed visible;
  a finding without a suggestion now shows no label. In a step's Inspector
  its findings come before its quotes.
- Document-wide limitations are listed once, in the header's Details. Every
  Inspector used to repeat all of them; it now shows one line, for example
  "6 document-wide limitations apply. Show", and Show opens Details at the
  list.
- Under the evidence heading a caption says: "A matching quote shows these
  lines exist unchanged since publishing. Whether they support the claim is
  for you to judge."
- A card's accessible name, and the announcement when you select it, end with
  the first sentence of its claim (cut at 160 characters) and name the phase
  by its label.
- Notebook cells print as the artifact records them, counted from 0
  (`train.ipynb › cell 34, line 2`). The viewer used to add one, so a step the
  model labelled "(cell 34)" showed "cell 35"; the skill, the helper's
  `--cell` and the extension already count from 0. Authored labels are not
  changed.
- The phase chip's tooltip says what a click does ("Hide the Data preparation
  phase" or "Show …"); it used to say "Show only the … stage".
- A connection's hover card is titled with its authored label, so the basis
  appears once there too.

Steps 3 and 4: the code left from the static analyzer's viewer is removed
(`webview/`, rebuilt into `vscode-extension/media/`). The viewer only ever
shows a model-authored document, so this code could not be reached. Checked
by local tests only; not tried in live VS Code.

- Removed: the diff overlay, the pipeline chooser, the answer card, the
  config, fix, suppression and rule-doc panels, the banners, the Findings
  tab's hidden "Group by" control, the loading skeleton, the standalone
  report's bridge and theme switch, the `concern:` scope presets, and the
  fields, messages and styles only that viewer used. The viewer no longer
  posts `selectNode`, `scopeChanged`, `askAssistant` or `action`, which the
  extension never handled, and no longer accepts `setFilter`, `setScope`,
  `requestExport` or `cursorHint`, which the extension never sends.
- Kept: everything steps 1 and 2 added, the scope picker and phase chips
  (to be reworked in M2), and `revealNode` / `revealIssue` for the planned
  "Reveal in Diagram". A saved view state with old keys still loads; the
  old keys are ignored.
- Two small visible changes: a merged connection's tooltip now reads
  "3 connections merged into this edge." (it described the retired rollup),
  and its screen-reader name states the count once.
- Size: TypeScript in `webview/src` went from 26,061 to 18,499 lines and the
  stylesheets from 5,428 to 3,986 lines; `mlview.js` from 364,619 to 286,353
  bytes and `mlview.css` from 82,027 to 61,726 bytes.
- Checks: the geometry golden is byte-identical. A jsdom tour of 39 authored
  documents (6,454 steps) gave the same page, saved state, posted messages
  and SVG export before and after each code batch, apart from the retired
  messages, the ignored old keys and the tooltip changes above. Computed styles at 195 points of a shorter tour are unchanged after
  the stylesheet cleanup. Webview tests at that step: 142 (one removed, "file
  groups report the weakest authored basis", which tested the removed
  grouping); extension tests: 281.

Screenshot harness (`webview/tools/screenshots/`): an opt-in script that opens
documents in the built viewer in headless Chrome and saves one PNG per state
plus an `index.json` of what was clicked, what the page posted and what it
showed. The capture is opt-in: `npm test`, CI and the e2e gates do not run
it, and it needs a local Chrome or Chromium (`CHROME` overrides the lookup).
Its plumbing test, `webview/test/screenshot-pipe.test.mjs`, does run in
`npm test`, so in CI and both e2e drivers (see the review fixes below).

- The host is simulated: VS Code theme colours for Dark Modern, Light Modern
  and Dark High Contrast, a stub `acquireVsCodeApi`, the panel's own inline
  bootstrap, and the frames the extension posts (`init`, `workflow`, and for
  the stale states `stale` and the stale banner). No validation, no editor.
- States: initial, step selected, hover on a step and on a connection, focus
  mode, a severity filter, search, a finding with its suggestion, a stale
  file (with and without a step selected) and a 900x800 panel.
- Inputs: the repository's sample and a synthetic 120-step document by
  default, or your own artifact and workspace. `--viewer` loads another
  checkout's build for before/after pictures.
- It runs on Node 20: Chrome is driven over `--remote-debugging-pipe`, not a
  WebSocket. `webview/test/screenshot-pipe.test.mjs` checks the pipe framing
  and the Chrome lookup without Chrome.
- The pictures are a rendering check only. They are not live VS Code
  validation, usability evidence or a semantic review.

Review fixes (findings from independent model reviews of this branch). Each
code fix has a local regression test that fails without it (jsdom, the mock
`vscode` module, or a child Node process); none of it was tried in live VS
Code. The geometry golden is byte-identical. Webview tests: 155; extension
tests: 282.

- Double-click on a finding or an Outline step opened nothing in a real
  browser: the first click rebuilt the rows, so the second click's
  `dblclick` went to a detached row. A double-click also failed, once per
  viewer, when its first click opened the rail (docked, the canvas refit and
  moved the card; in a narrow panel the drawer and its scrim covered it), and
  the second click could press an Inspector control such as **Challenge this
  claim**. Now the first click arms an opener, and the second click of the
  same double-click (the browser's own count) opens what the first one
  selected, wherever it lands; the rest of that gesture is swallowed. A
  finding expanded above the clicked one no longer makes the double-click
  select another row. The tests send click, click and `dblclick` in Chrome's
  order instead of a bare `dblclick`.
- A notebook jump that waited for its cell editor cleared the highlight of a
  jump made after it (always for a markdown cell in preview). Each jump now
  has a sequence number, and an overtaken jump stops before it touches the
  editor or the highlight.
- The cited-range highlight was invisible in High Contrast themes, which
  define no `editor.rangeHighlightBackground`. It now also draws
  `editor.rangeHighlightBorder`, which only High Contrast themes define.
- Wrong workspace root: the host sends the hinted files with the reason
  `elsewhere`. Cards, connections, findings, quotes, the status bar ("1 of 1
  cited files in another folder") and a blocked jump now say the file is in
  another folder and point to the notice; they used to call it changed or
  missing while the notice said it was unchanged. The notice leads with the
  files: "source.py is not in the workspace root (MLView/). It is in ./copy/,
  unchanged (it matches its published hash). Add ./copy/ to the workspace, or
  open it in its own window."
- The Inspector's stale note no longer ends "the claim was not re-checked"
  (nothing in MLView checks claims). It reads "… cite a file that changed or
  went missing since publishing; those jumps are blocked. To compare the claim
  with the code as it is now, ask the assistant for a fresh revision."
- The stale marks and dashed border use the warning colour mixed 30 % toward
  the text colour. In Light Modern and 2026 Light they were 2.2 to 3.0:1
  against the card; now at least 4.2:1 (WCAG 1.4.11 asks 3:1).
  `webview/test/stale-contrast.test.mjs` checks six default themes.
- A card's spoken claim stopped at "i.e." or "e.g.". A period after a dotted
  abbreviation or after etc., vs., cf., approx. and a few others no longer
  ends the sentence.
- The shortcut sheet and the docs promised a double-click opens every row a
  click selects. A double-click on a group collapses it, and the Outline's
  connection and phase rows only select; the sheet now says which targets
  open.
- `findChrome` built the macOS and Linux candidates with the host's `path`,
  so on Windows it looked for `\Applications\Google Chrome.app\…` and its test
  would fail the Windows CI job. Those candidates now use `path.posix`; a
  test runs the lookup in a child Node process whose `node:path` is
  `path.win32`. The docs no longer say the harness is outside every gate.

Live check fix (`vscode-extension/`): **Add folder to workspace** in a
single-folder window left a dead diagram tab. VS Code turns the window into an
untitled multi-root workspace and restarts every extension host. The panel
stayed open, still showing the hint, and its buttons did nothing: VS Code
1.139 calls a panel serializer only for tabs it restores when a window loads,
not after an extension host restart. Re-running **MLView: Open Generated
Diagram** gave a second panel beside the dead one.

- Before it asks VS Code to add the folder in a single-folder window, the
  extension saves a short note in its global state: the window's session, the
  folder, and each open diagram's artifact and tab title. The note goes in
  the global state because VS Code 1.139 starts the new workspace with an
  empty workspace state. After the restart, the new extension host closes the
  dead diagram tab (one per noted diagram, matched by title) and opens the
  diagram again in the same editor group. There it validates against the
  added folder. The note is used once. It is ignored if it is more than a
  minute old, belongs to another window, or names a folder the workspace does
  not contain. Other tabs, including a restored diagram tab never shown, are
  left alone.
- A multi-root window keeps its extension host, so the panel still validates
  again in place and no note is saved. **Developer: Reload Window** already
  revived the panel through the serializer, with the artifact and view state
  the webview saves. One change there: a revived tab whose diagram is already
  shown in another panel is now closed, so each artifact has one panel. Before,
  the revived panel replaced the other in the extension's list, and the other
  stopped receiving file changes. Two existing restore tests now close the
  first panel before restoring the same artifact.
- Tests: `vscode-extension/test/folder-add-restart.test.js` (11 cases with the
  mock `vscode` module, which gains `window.tabGroups`, `TabInputWebview`,
  `workspace.workspaceFile` and `env.sessionId`). Extension tests: 293.
- Checked in an isolated VS Code 1.139 Extension Development Host (throwaway
  profile, driven over the DevTools protocol). In a single-folder window on
  the parent folder, **Add folder to workspace** now ends with one diagram
  tab, revalidated with no notice, and Enter on a selected card opens the
  cited range. With two diagrams in two editor groups, both were replaced in
  their groups (checked with a build from before the one-panel-per-artifact
  change, which that path does not use). Reload Window revives the panel, both
  when it is in front and when it is a background tab that is then shown. In
  a multi-root window the panel revalidates in place. This was a check of
  these paths only, not a usability study or a review.

Live check follow-up (`vscode-extension/`): an independent check found that
only the root hint's own button saved the reopen note above, so every other
extension restart in a window still left a dead diagram tab: VS Code's
**Workspaces: Add Folder to Workspace...**, **Save Workspace As...**,
**Developer: Restart Extension Host**, and an extension install or update that
restarts extensions. The root hint's notification also outlived the restart,
with its old text and buttons that did nothing.

- The one-minute note is gone. Each extension host keeps a registry of its
  open panels in the global state (`mlview.openPanels`): per window session
  (`vscode.env.sessionId`), each panel's artifact, tab title and editor group.
  It is written when a panel opens, changes title or group, or closes, and not
  when the host shuts down, so it outlives the host. After a restart in the
  same window the new host replaces each dead tab with a new panel for its
  artifact in the same group, checked against the workspace as it is then.
  The root hint's **Add folder** now only makes sure the registry is stored
  before VS Code adds the folder.
- The tabs API shows a dead tab and a tab VS Code restored at startup but has
  not shown yet the same way (same title, view type and flags; checked live).
  A restored tab comes to life through the serializer as soon as it comes to
  the front of its group, so only front tabs are judged, half a second after
  activation or after a tab change: a diagram tab in front that no panel of
  the new host shows by then is dead. VS Code revives a restored panel with
  column 0 and reports its group about 20 ms later (live), so until then a
  visible panel with the tab's title counts as showing it. A dead tab behind
  other tabs is therefore replaced only when it is brought to the front,
  after showing a blank page for about half a second. A dead tab takes the
  registry entry with its title, in its own group first, so two diagrams with
  the same title in one group can come back in each other's places. A front
  tab with no entry is left as it is (Reload Window still revives it). If its
  diagram was opened again since the restart, the dead tab is only closed.
  Entries whose title is on no tab are dropped. Other windows' and earlier
  sessions' entries (each reload leaves one) are pruned after 14 days, and at
  most 20 are kept. The recovery shows no UI beyond a log line.
- The root hint no longer shows a VS Code notification. The panel's notice,
  drawn by the live host, carries both actions. Showing the notification only
  while the panel is hidden was the other option; it would still leave dead
  buttons after a restart and needs visibility tracking.
- Tests: `vscode-extension/test/host-restart.test.js` (17 cases) replaces
  `folder-add-restart.test.js`. Its two-diagram decoy test passed for the
  wrong reason: both decoys were behind the front tab, so the "front tabs
  first" ordering never reached them. The new cases bring a restored tab with
  the same title and group as a pending entry to the front and revive it, and
  cover the dedupe against an open panel, a column VS Code has not reported,
  shutdown, pruning, malformed values, the hint's write before the folder is
  added, and title, group and close updates. The mock gains `Disposable`, tab
  change events, `TabGroup.activeTab`, tabs linked to panels and view state
  changes. A mutation check (19 mutations of the new logic, each rebuilt and
  run against the restart and verification-loop tests) was caught 19 times
  out of 19. Extension tests: 299.
- Checked in an isolated VS Code 1.139 Extension Development Host (throwaway
  profiles, driven over the DevTools protocol): the root hint's **Add folder**
  and VS Code's **Add Folder to Workspace...** in a single-folder window,
  **Save Workspace As...**, **Developer: Restart Extension Host** with the
  diagram in front, behind a text tab (left alone, then replaced when brought
  to the front) and with two diagrams of the same title in two groups (each
  came back in its group with its own artifact), **Reload Window** with the
  diagram in front and behind, a restart while a restored tab was still
  unshown (left alone, then revived when shown), a dead duplicate of a revived
  diagram (closed, no second panel), and a multi-root window (revalidated in
  place). Each ended with one panel per artifact whose card opened the cited
  source on Enter, and no dead tab. A restored tab brought to the front while
  an entry with its title was pending (revived, not closed) and the dead
  duplicate were checked with the build before the column 0 rule, which only
  adds a case where a tab counts as shown; the other paths ran on the final
  code. An extension install or update was not tried. This was a check of
  these paths only, not a usability study or a review.
- A second independent check passed these paths again live and found three
  guards the tests did not pin: the settle delay restarting at every tab
  change, matching a front tab by title even when an entry has its group, and
  a column-0 panel covering only a tab with its own title. Three tests now pin
  them; removing each guard fails its test. The docs now say that a diagram
  put back after a restart starts with a fresh view (its selection and zoom
  reset), while Reload Window keeps them. Known limits: two windows writing
  the registry within about 40 ms can lose one write, which heals on that
  window's next panel change; a dead tab closed from behind while its diagram
  is open again leaves its entry until no tab has that title. Extension
  tests: 302.

## Unreleased — viewer fixes from the Stage 1 review

Two viewer defects the owner reported while reading pilot diagrams in VS Code,
the related gaps that model reviews of the fix found, and a narrower node
hover the owner asked for in the same review. The changes are checked by local
tests only (`webview/test/finding-counts.test.mjs` and new cases in
`webview/test/hover.test.mjs`); the version is unchanged.

Viewer (`webview/`, rebuilt into `vscode-extension/media/`):
- Phase and group badges count each finding once. A phase header and its
  Outline row added up the findings of every step and every connection in the
  phase, so one finding that named three steps and two connections showed 5
  there while the toolbar and status bar said 1. A group's badge did the same
  for a finding naming the group and its children. A finding that touches two
  phases still counts once in each of them. A collapsed group also counts the
  findings of the connections it hides (both ends inside it), which used to
  vanish from the canvas when the reader folded the group.
- Hovering a connection, or the severity marker on it, lists the connection's
  findings in the hover card (severity, id and title, as a step's card does).
  A merged connection lists each finding once, in document order, and findings
  hidden by the severity or phase filters are left out. The card sits above
  the marker instead of over it. The whole marker now opens the card: when
  zoomed in past about 120%, pointing at the edge of the marker used to open
  nothing. A connection's Inspector lists its findings too, so they are not
  reachable only by pointer.
- Hovering a group lists the same findings its badge counts; a collapsed
  group's card listed only the group's own findings, usually none.
- Hovering a step or group lights only its direct connections (the
  connections that start or end at it, and the cards at their other ends) and
  runs the flow animation along those connections only. It used to light the
  whole upstream and downstream lineage, which on a loop or a long chain lit
  most of the diagram. A collapsed group counts as the steps it hides. Focus
  mode (select a step, press F) still lights and animates the full lineage,
  and the shortcut sheet now says so. A bundled trunk that a hover or focus
  mode opened folds again when it ends; it used to stay open. Cards a hover
  dims can still be hovered and clicked (only focus mode makes dimmed cards
  inert), so the cards two hops away stay reachable. Turning focus mode off
  with the pointer on a card brings back that card's hover. When a hovered
  card has more connections than the animation can carry, the message now
  suggests hovering a single connection, since scoping to the card keeps all
  of them.

## Unreleased — Campaign 3: public shakedown fixes

A shakedown ran the `mlview` skill from 0.3.0 (`00e5d45`) once per host
(Claude Code, Codex and Copilot) on 12 public ML repositories that are not in
the held-out pilot; 32 of the 36 runs published an artifact. A provisional
model review, not a human review, ranked 22 product issues; the issue numbers
below refer to that ranking. The fixes are local changes checked by local
tests only: nothing here was exercised on a live host, measured against the
pilot or reviewed by a person, and the version stays 0.3.0.

Helper (`skills/mlview/scripts/artifact.py`, still stdlib-only; no schema
change and no change to what the extension accepts):
- New read-only `excerpt <file> --lines <start>[-<end>] [--cell <n>] [--id
  <evidence-id>] --workspace <ws>` prints one evidence record exactly as
  `validate` accepts it, sharing validation's path confinement, refusal of
  MLView's own files, size and encoding limits, notebook cells and line
  joining. A bad path or range exits 1 with a JSON error (issue 3).
- `quote_mismatch` locates the problem: `id`, `file`, `cell`, the cited range,
  line counts and `difference` (first differing line and column with bounded
  windows of both sides), `foundAt` when the quoted text occurs exactly once
  elsewhere in the same file or cell (a hint; nothing is rewritten), and a
  message naming the usual cause (a trailing line break, a range ending on an
  empty line, a carriage return, whitespace, part of a line). `reference`,
  `duplicate_reference` and `duplicate_id` name the value and index the entry
  (for example `nodes[16].evidence[3]`); `range` adds `maxLine`; a repeated
  JSON member adds `member` (issue 2).
- Errors no longer hide one another: after `unexpected_cell` the quote is
  still checked, and a repeated member in a `validate` or `publish` draft is
  reported while the rest is validated with the last value, as `JSON.parse`
  reads it (the draft still fails; `upsert` still refuses it) (issue 2).
- Six non-blocking warnings for error-free documents, at most 10 per code plus
  a count: `unreferenced_evidence`, `isolated_node`, `self_edge` (not for kind
  `loop`), `wide_evidence` (over 60 lines), `evidence_overlap` and
  `duplicate_inspected`. `validate` adds a `basis` summary counting observed,
  inferred and unresolved nodes, edges and findings. Warnings never change
  validity, the exit status or publication (issues 3, 7, 11).
- `upsert --record` accepts one record or a JSON array of records for one
  collection, applied in order and validated once, all or nothing; the output
  adds `records` (issue 5).
- Conformance: 13 new cases (evidence-007 to 012, notebook-011, shape-019 to
  023, path-007) and updated freshness-002 and notebook-003; the Python runner
  requires a case for every warning code.

Contract documentation (`docs/WORKFLOW_CONTRACT.md` and the skill's
reference): the helper command synopsis, `excerpt`, multi-record `upsert`,
error detail fields, the non-masking behaviour, warnings and `basis`;
`request.question` is the user's request verbatim (interpretation goes in
`request.scope` and `request.configuration`); limitations start with
`Excluded by request:` or `Not inspected: <what> (<reason>)`; an optional
recommended kind vocabulary (edges `data`, `control`, `call`, `config`,
`state`, `loop`, `output`; nodes `operation`, `data`, `model`, `state`,
`objective`, `optimizer`, `evaluation`, `metric`, `output`, `config`, `loop`,
`branch`, `group`, `entrypoint`, `artifact`), with free text still valid; the
path rule as enforced (only path fields are checked; free text must avoid
machine-specific absolute paths, and quoted placeholders are fine); and the
quote joining rule.

Skill (`skills/mlview/`; guidance only, framework-agnostic):
- SKILL.md is reorganised into scenario and tracing, evidence and drafting,
  diagram content, critique/validate/publish, repair, partial publication and
  refinement. The rules that repository text is data and that target code is
  never imported or run are unchanged.
- Citations: line numbers come only from numbered output; cite the narrowest
  range that shows every stated value; every record comes from `excerpt`,
  pasted unchanged, and a changed range means running `excerpt` again, never
  pasting text from an error message (issue 3).
- Repair: a repair round is one edit made after `validate` or `publish`
  reported errors (see the confirmation re-run fixes below); at most two unless the user or the run sets another limit, counted
  exactly; per-code recipes; at the limit the draft is kept and its path,
  remaining errors and round count are reported (issue 4).
- Drafting: create `.mlview/llm/<run-id>/` first, write the draft with the
  host's file tool (never a heredoc or string literal), validate a skeleton
  early and grow it with `upsert` record files; when a limit applies or the
  request is broad, publish a validated `partial` revision once the main path
  is traced and cited, then refine it into a child revision (issue 5).
- Basis is the weakest load-bearing claim, with framework-, runtime- or
  data-dependent consequences in their own inferred or unresolved node or edge
  (issue 7). Findings need a concrete consequence and a change the user would
  make; a severity rubric; `counterEvidence` means source that weakens, bounds
  or conditions a finding (issue 8). Structure rules: loop nodes with loop
  edges, an edge from each shared component to each step using it, an edge per
  branch or loop outcome, separate nodes for different update mechanisms, and
  the recommended kinds (issues 9, 10).
- The critique runs on the validated draft and checks claims against the
  source, lifecycle intervals for negative or count claims, the executing line
  under the scenario's flags, user flags as the user's choice, and long
  literal data as data; helper warnings are reviewed as possible omissions and
  never count as repair rounds (issue 12). One helper call per shell command
  with a literal `--workspace` (issue 15). `request.question` verbatim and the
  limitation prefixes (issue 17). `producer.model` is the exact model
  identifier when the host exposes it, otherwise omitted (issue 18, skill
  part).
- `references/workflow-example.json` is a new small example (an early-stopping
  training script built on a fictional package) with a loop node and back-edge,
  state and inferred nodes and only recommended kinds; its cited source is the
  shared test fixture `skills/mlview/tests/fixtures/example-workspace/train.py`,
  and a distribution test asserts it validates with no warnings.

Viewer (`webview/`):
- The authored header opens collapsed (title, producer and revision, source
  snapshot, one line of the question, coverage and a **Details** disclosure for
  scope, entrypoints, configuration, coverage summary, publication time and
  limitations), is capped at 42% of the height with its own scroller, and the
  canvas keeps at least `min(320px, 50vh)`. In a headless Chrome measurement
  of the 32 shakedown artifacts plus one contract-maximum document, panels
  whose canvas had zero height went from 13/33 (541 px wide), 32/33 (393 px)
  and 1/33 (1382 px) to none at any size (issue 1).
- Authored titles are truncated once and wrap to up to three lines (also in
  the SVG export). Recommended kinds and common synonyms map to existing
  glyphs, with a neutral glyph otherwise; authored nodes never show the `?`
  glyph, and the dashed outline marks only `unresolved` basis (issue 14).
- Edge kinds `state`, `loop` and `output` are styled, synonyms are normalised
  for display only, the inspector and tooltip show the authored spelling, and
  the legend lists an "other" entry; unfilled arrowheads are now stroked
  (a pre-existing styling bug) (issue 9).
- Large diagrams: the rail docks open only while the canvas keeps at least
  900 px until the reader uses it or selects a finding, selecting a finding
  opens the rail and zooms to a readable target, the minimap hides below
  350 px of canvas height, the view refits on large resizes only while still
  fitted, and default collapse never folds a group holding a finding target
  (issue 6, without the optional phase overview).

Extension (`vscode-extension/`): the stale banner, toast and blocked-jump
message are worded from each file's reason, so a deleted cited file is
reported as missing rather than changed (issue 21).

Integration: SKILL.md's `quote_mismatch` recipe now quotes the helper's
actual `foundAt` wording, a request over 4000 characters is noted in
`request.scope` as the contract says, the skill's code list and the contract
table point `quote_mismatch` repairs at `excerpt`, and the README, the
extension README and `docs/LLM_WORKFLOW.md` describe the collapsed header,
the missing-file wording, `excerpt` and the warnings.

Integration review fixes (four provisional model reviews of the integrated
branch, covering the helper, the skill, the live viewer and a replay of the
shakedown drafts; not a human review):
- Helper: default `excerpt` IDs add 8 hex digits of the path's SHA-256 (for
  example `ev-src-train.py-a454ee59-10-24`), so paths that slug alike
  (`utils/io.py` and `utils-io.py`, or names in a non-Latin script) no
  longer share an ID and silently replace each other through `upsert`; an
  `upsert` array that repeats an ID is refused (`record`). `excerpt` refuses
  a path over 500 characters (`limit`) and notebook text holding an unpaired
  surrogate (`text_encoding`) instead of printing a record `validate`
  rejects. The `foundAt` search anchors on the quote's rarest line and stops
  at a comparison budget per record and per validation: three mismatched
  2,001-line quotes against a 1,000,000-line blank file took 11.9 s before
  and 0.07 s after on the development machine, and `foundAt` was unchanged
  on all 137 replayed shakedown mismatches. `quote_mismatch` adds
  `differingLines` and, without `foundAt`, says when more lines than the
  first differ. A `./`, empty or trailing path segment is reported as an
  unnormalised path instead of "must stay within the workspace". The
  `isolated_node` and `self_edge` messages no longer suggest deleting
  content: connect a node to the step it affects (or move an absence to
  `coverage.limitations`), and draw an iteration from the last repeated step
  back to the first.
- Viewer: an authored self-edge on a drawn node is a small loop on its card
  instead of being silently skipped (edges folded into a collapsed group stay
  hidden). Below the 900 px breakpoint a reveal centres its target in the
  strip the rail drawer leaves, when that strip is at least 160 px: in a
  headless Chrome check at 541 px the finding targets went from 4% visible
  behind the drawer to fully visible at 75% zoom; at 393 px the drawer
  leaves 55 px, so the target is still centred behind it and shows when the
  drawer closes. A selected target that was in view is re-centred, at the
  same zoom, when a resize (a split opened by following evidence) turns the
  docked rail into a drawer over it. The collapsed header no longer shrinks
  behind its own scroller: at 541x502 its Details toggle went from 0 of 28 px
  visible to 28 of 28; while it is collapsed the canvas floor is
  `min(320px, 25vh)`, and expanded it stays `min(320px, 50vh)`.
- Skill guidance: a loop edge runs from the last step of the repeated work
  back to its first; independent `excerpt` calls may run in parallel, and a
  scratch script may collect `excerpt` output into an `upsert` array;
  warnings on a growing draft are expected and are acted on in the critique;
  `request.question` leaves out the skill invocation and run instructions,
  replaces machine-specific paths with placeholders and is kept on
  refinement; a certain failure that shows itself (an exception or crash) is
  `medium`; the shared-component examples use neutral wording, and the
  update-mechanism rule is no longer repeated in the training-state
  reference; the bundled example no longer labels its loader as observed
  shuffling, and the minimal finding shape states a search boundary.

Confirmation re-run fixes. A confirmation run of the fixed skill on ten of
the shakedown cases (run once each; provisional model review) found two
problems, both fixed in the skill text:
- Claude Code had a valid yolov5 draft at 28 minutes, then turned the
  critique of the validated draft into new tracing and was stopped at 40
  minutes without publishing (the 0.3.0 skill published in 27). The critique
  now corrects, qualifies and connects what the draft already covers and is
  followed by publication; further work it suggests is named as a
  `Not inspected:` limitation and continued in a child revision.
- Codex built its whisper draft with `upsert`; two refused upserts used up
  both repair rounds, and the rule that a still-valid draft is published as
  `partial` at the limit then published a 3-node skeleton. A repair round is
  now an edit after a `validate` or `publish` error only. A refused upsert
  changes nothing and is not a round: the host fixes that record file and
  applies it again, drops it after a third refusal (naming the dropped work
  as a limitation), and reports how many upserts were refused. The
  publish-as-partial-at-the-limit rule is removed; partial publication
  follows only the partial-publication rule (main steps traced and cited).

Deferred on purpose:
- Issue 13, guidance for values resolved through registries, default tables
  or override chains: the review rated its overfitting risk high because it
  overlaps held-out pilot tasks; the existing generic obligation to resolve
  factories and registries is unchanged. For the owner to decide after the
  first pilot stage.
- Issue 16, a notebook cell-listing command: weak evidence of need (no
  notebook citation failed in the shakedown) and direct relevance to a
  held-out task; `excerpt --cell` covers exact notebook citations.
- Issue 19, checking `request.entrypoints` against workspace files, and
  issue 20, column ranges for long single-line literals: both are contract
  changes across the schema, helper, extension, viewer and docs, and are kept
  out of the pre-freeze contract.
- Also not done: the optional phase overview (issue 6), the harness side of
  issue 18, an `ancestor_edge` warning and a missing-kind warning (kinds stay
  free text). Issue 22 is a review-process note with no product change.

Measurement caveat: once quotes come from the `excerpt` command, the pilot's
`exactAnchors` target (T2) shows only that cited ranges exist and are fresh.
Whether a range supports its claim rests on supported-claim scoring
(`supportedClaimPrecision`, T3). The owner should also note, before a freeze,
that the skill's repair-round limit ("at most two unless the user or the run
sets another limit") must agree with the proposed run policy, including how
rounds are counted (the skill counts edits after `validate` or `publish`
errors, not refused upserts or `excerpt` errors), that one `excerpt` call per
evidence record has not been timed on a live host against the proposed
20-minute budget, that the `medium` severity for a certain visible failure is
a proposal the owner may change, that a published
partial revision may lower essential-fact recall (`essentialFactRecall`, T4)
when a run stops before refining it, and that a verbatim `request.question`
lengthens the header's one-line question.

## Unreleased — Stage 1 normalized review hashes

Evaluation tooling only: `tools/` is not part of the shipped skill, plugin or
VSIX, so no version changes. This simplifies the Stage 1 finality rule of
0.3.0, as its RC2-1 note proposed. No pilot has run, and nothing here reviews
a run or decides the pilot.

- A Stage 1 summary records, beside each review's SHA-256, a normalized hash
  (`inputs.runs[].reviewNormalized`, `{"version": 1, "sha256": ...}`, null
  where no review was read; the Markdown lists it). Review normalization v1 is
  fixed and independent of the review parser (`tools/eval_records.py`): UTF-8,
  one leading BOM stripped, CRLF, CR and LF alike, trailing whitespace
  stripped, blank lines and `>` notes dropped, leading indentation kept, then
  the SHA-256 of the remaining lines, each ended by LF. A test pins its bytes
  and hash, and another checks that its whitespace set is what the parser
  strips.
- The Stage 2 gate (`run-prepare` of a repeat, and `summarize --stage all`)
  compares the normalized hash of every Stage 1 review the recorded summary
  lists, whichever tools recorded it. A changed or deleted review is named
  with its run and file, the message says that only `>` notes, line endings,
  trailing spaces and blank lines may change and everything else must be
  restored exactly, and Stage 2 is held (the all-stage summary is
  `incomplete`; no Stage 2 run becomes invalid). With the same tools the full
  re-computation stays (decision, sealed inputs, every field and the
  Markdown), without comparing review bytes; with other (Git-bound) tools the
  decision, the sealed inputs and the disclosure of retries and failures are
  compared as before.
- Removed: the re-derivation of review verdicts with other tools (0.3.0's
  REG-1 and NEW-1 to NEW-3 fixes, which compared the verdict-derived fields
  and the baselines' false accusations total of each review whose bytes
  changed, and the message that gave the recorded sha256). What the tools read
  or count from a review is no longer compared across tool versions. This
  closes 0.3.0's known limit RC2-1: a tool change in how one baseline's false
  accusations count, plus a re-save of another baseline review, no longer
  holds Stage 2, and neither does a re-save after any later change in how the
  tools judge a review, as long as the re-computed decision stays `go`. The
  rule is stricter where 0.3.0 was lenient: a wording change that kept every
  verdict (a reworded reason, a corrected date) now holds Stage 2 until it is
  restored.
- The end-to-end pilot test also records and checks the normalized hashes
  through the command line.
- A Stage 1 summary without normalized review hashes (one recorded by the
  0.3.0 tools) is refused; there is no fallback path. It holds Stage 2
  (`run-prepare` refuses, and `summarize --stage all` is `incomplete`
  without making Stage 2 runs invalid), and the message says to record Stage
  1 again with the current tools only while no Stage 2 run has been prepared
  and the summary commit is unpushed, and otherwise to supersede the
  campaign, since a summary recorded again after Stage 2 runs were prepared
  makes them invalid. No pilot has run, so no such summary exists.
- The review template's Stage 1 note, the `--record` message and the docs
  (the evaluation README, the pilot README and its known limits, the pilot
  readiness checklist) state the new rule.
- Review fixes on the branch, each with a regression test on synthetic data:
  - A summary without normalized review hashes, or with another
    normalization version, is a hold rather than a missing go, so Stage 2
    runs collected under it are no longer counted invalid in a recordable
    all-stage summary (STATS-1).
  - A later tool version that rejects an unchanged, recorded Stage 1 skill
    review (a new review rule) gets its own message: it names each review,
    says it is final and must not be edited, and that Stage 2 needs the tool
    change reverted; the all-stage note gives that remedy instead of "fetch
    or verify the corpus". The docs no longer say that whether a review is
    complete is not compared across tool versions, and the pilot README's
    known limits say that a tools change must not reject a recorded Stage 1
    review (HONEST-1).
  - A `review.md` that reappears after the record in a Stage 1 run that did
    not complete is named with the remedy (remove it) and holds Stage 2,
    whichever tools recorded the summary, instead of a message that pointed
    at a forged summary and Stage 2 runs counted invalid with the same tools
    (STATS-2, HONEST-2; the latter predates this branch).
  - With the same tools, the normalized review hashes are part of the full
    comparison, so a summary that nulls the hashes of a review the tools read
    no longer unlocks Stage 2 (INTEGRITY-1).
  - The normalization v1 constants and test vectors are spelled with
    escapes instead of invisible raw characters (INTEGRITY-2); the pinned
    bytes and hash are unchanged.
  - With other tools, a later change in how the tools count Stage 1 that
    turns the recorded `go` into `stop` over unchanged evidence is a hold
    with the remedy to revert that change, instead of a missing go that
    counted every Stage 2 run invalid in a recordable all-stage summary
    (found by the final check; 0.3.0 behaved the same). The note for a
    `review.md` in a Stage 1 run that did not complete now ends with its own
    remedy (remove it) rather than "restore the Stage 1 evidence".

## 0.3.0 — pilot readiness (Campaign 2)

Tooling the owner and an operator need to review the reference packet, freeze a
campaign and run, seal, review and summarize the held-out pilot. Nothing here
reviews a reference, runs a model or decides the pilot: every committed
decision file is a pending template, `pilotApproved` is the constant `false`,
and summaries say "computed against the predefined targets; not an approval".
0.3.0 follows 0.2.0, which shipped on 2026-09-25. Finding IDs refer to the
2026-09-25 takeover review; N and J items are the Campaign 2 specification's
own observations.

Evaluation pipeline:
- Owner decisions are plain Markdown files in `evals/workflow/decisions/`:
  eight pending task templates, `run-policy.md` and
  `development-adjudication.md`. `python tools/workflow_eval.py check` prints
  every problem as `path:line: LEVEL section: message` and ends with "ready to
  freeze" or not; `template` (exclusive, `--second`, `--show`, `--init-all`)
  and `context` (a gitignored sheet with each quote verified against the
  pinned bytes) support the review. Unknowns and non-defects get stable IDs,
  and the Flax placeholder argument must be replaced before a freeze (EVAL-2,
  N2, N3).
- `freeze --campaign C [--write]` checks every precondition (ready files,
  resolved second-review disagreements, verified corpus, exact quotes, covered
  paths, no reference leakage or machine paths in prompts) and writes the
  frozen references, reference set, run policy, 16 prompts and `freeze.json`
  exclusively; `referenceRevision` is the reference set's hash. `check-frozen`
  re-derives the current campaign byte for byte and guards the held-out
  manifest fields. The host invocation is frozen per host, outside the hashed
  prompt (EVAL-6, N5).
- Candidate snapshot v2: `python tools/workflow_candidate.py --campaign C
  --build-vsix` builds the VSIX itself on a clean tree, checks its payload,
  media and version and the skill payload against `git ls-files`, and pins the
  schema, manifests, viewer bundle, extension manifest and `freeze.json`
  (no longer the ignored `out/extension.js`). `--output` writes a development
  snapshot, which summaries refuse (CRIT-9).
- Pilot runs: `plan`, `run-prepare` (a fresh workspace per run under
  `$MLVIEW_PILOT_DIR`, outside every Git work tree and instruction file, with
  only the pinned sparse paths and the installed skill), `run-finish` (a
  sealed `record.json` with every evidence hash; `--amend` keeps the previous
  seal), `review-template` and `check` for `session.md` and `review.md`
  (N6, N8, J2, J3).
- `summarize --stage 1|all` reads every frozen input and the helper at the
  candidate commit, refuses integrity failures, counts protocol violations as
  invalid runs, and computes T1-T6 with intention-to-treat denominators, the
  three qualified-claim policies, per-host targets, paired baselines and the
  documented go/stop/incomplete/invalid decision; `--record` writes the stage
  summary exclusively. The unverified legacy `summarize`, `baseline-plan` and
  test-only placeholders are removed (EVAL-1, EVAL-7). `pilotTargets` gains
  `knownUnresolvedQualified` (N1).
- Smoke reviews are bound only to host-less ledgers (EVAL-5); replayed
  citations use the helper's line and notebook semantics and require an
  integer `endLine` (EVAL-15); `development-plan --output` is exclusive and
  `review-packet` needs `--force` to replace its HTML (EVAL-4).
- `tools/evidence_lock.json` pins every byte under the evaluation evidence
  roots, `tools/evidence_lock.py --add` appends new dated records, and
  manifest tests re-hash the recorded native artifacts (EVAL-17). Required
  source paths are computed from entrypoints, anchors and frozen sources, never
  parsed from arguments (J1).

Corpus:
- The mmdetection sparse list adds the five root-anchored config files the
  registry task needs (EVAL-3). `fetch_workflow_repos.py --verify [--json]`
  checks each checkout in place (HEAD, clean state, sparse list, blob-exact
  covered files) without changing it; `--update-sparse` applies a changed list
  to a clean pinned checkout. The analyzer-era `.mlview-pinned-sha` marker is
  tolerated when it holds the pin (EVAL-16), and new checkouts turn off
  `core.autocrlf` (J5).

Distribution and CI:
- One portable-file filter keeps `.DS_Store`, editor and OS files out of the
  skill identity, ZIPs, plugin copy and installs (EVAL-8). The installer
  records `.mlview-install.json`, upgrades unmodified files, refuses local
  edits unless `--force`, and doctor explains symlinked locations (SKILL-15).
- `vsix_check.py` reports a missing working-tree source instead of skipping
  and gains `--payload-only` (EVAL-10). CI adds Python 3.14 and Node 24 and 26,
  runs the native sh and PowerShell drivers, and has a conditional
  `claude plugin validate --strict` job; with `MLVIEW_REQUIRE_CLAUDE_CLI=1` a
  missing Claude CLI fails instead of skipping (EVAL-11). The PowerShell
  drivers choose a Python 3.10+ interpreter like the sh drivers (EVAL-13).
  `requirements-dev.txt` pins `pytest==9.1.1` and `jsonschema==4.26.0`
  (EVAL-12), and `check.py --skip-build` says what still rebuilds (EVAL-14
  remainder).

Helper:
- A cited notebook containing `NaN` or `Infinity` is refused with
  `notebook_cell`, as the viewer cannot read it; the conformance corpus grows
  from 65 to 70 cases (NaN and duplicate keys in notebooks, and three
  `publishedAt` profile pins: lowercase `z`, a leap second, a nine-digit
  fraction).
- Every helper error and warning code (58 and 2) is catalogued in
  `docs/WORKFLOW_CONTRACT.md` and, compactly, in the skill's bundled contract;
  a test fails when a code is added without documentation.

Round 1 review fixes (finding IDs refer to the Campaign 2 round 1 review):
- `check-frozen` counts a final summary only when it is a summary
  `summarize --record` wrote for the campaign's `candidate.json` and
  `freeze.json`; any other file named like a summary is reported and never
  switches the re-derivation off. The hash-only check still binds `freeze.json`
  to the candidate and the ledgers to their frozen bytes, checks the copied
  `supersedes`, `developmentAdjudication` and `tasksManifest.sha256` fields
  (against the commit that added `freeze.json` when the Git history is
  complete), and names each changed decision file (INTEGRITY2, INTEGRITY9,
  OWNERUX1-4). A campaign whose candidate or summary was ever committed needs
  an owner invalidation to be superseded, and the capture refuses a campaign
  that already holds a summary or invalidation (INTEGRITY7).
- `summarize` and `run-prepare` bind every frozen reference and the run policy
  to the decision files and ledgers at the candidate commit (INTEGRITY3); a
  Stage 1 summary unlocks Stage 2 only when it has the recorded format and a
  re-computation from the sealed evidence gives the same `go` and run hashes
  (INTEGRITY4); the development-adjudication gate uses the full checker
  (INTEGRITY6).
- `run-finish` compares the workspace with the pinned bytes recomputed from the
  corpus, records paths where `workspace-before.json` differs, reports Claude
  Code's `.claude/settings.local.json` as a host file instead of invalidating
  the run, counts MLView files in a baseline, and writes `finish-state.json` so
  a deleted `record.json` is never sealed again with other session facts
  (INTEGRITY1, INTEGRITY5, STATS1-4, STATS1-5). `summarize` checks the sealed
  workspace lists and the amendment chain against the hashed evidence
  (STATS1-2). Every `run-prepare` attempt is appended to
  `$MLVIEW_PILOT_DIR/preparations.jsonl`; a failed attempt is retried only with
  `--retry "<reason>"`, which keeps its evidence (INTEGRITY8).
- Baselines are held to the policy's model and reasoning, not the skill
  invocation (STATS1-1); unreviewed baselines show no paired difference and
  block `--record` (STATS1-3); the early-stop bound skips unreviewable runs
  (STATS1-6); split claims refuse leading zeros and repeats (STATS1-7);
  `disputedDenominatorItems` lists disputes on essential and runs-must-state
  flags (STATS1-9); Markdown percentages are floored (STATS1-10). Machine
  paths such as `D:/` are refused in session values, amendment reasons and
  summaries (INTEGRITY11). Summaries and review templates cite README sections
  by heading instead of stale line numbers (SPECDOCS1-1).
- Owner files: second reviews get their own ID space and their additions must
  be resolved, and a second review by the primary reviewer is an error
  (OWNERUX1-1, INTEGRITY10); an unindented wrapped line or a mistyped heading
  gets a message that does not lead to deleting a decision (OWNERUX1-2,
  OWNERUX1-10); owner notes and CRLF line endings keep a pending file valid in
  CI (OWNERUX1-3); the no-skill prompt refuses publishing words (OWNERUX1-5);
  templates cite document sections (OWNERUX1-6, SPECDOCS1-2); messages show the
  typeable ` -- ` separator and explain a single `-` (OWNERUX1-7); a sparse
  mismatch names `--update-sparse --repo <name>` (OWNERUX1-8); a replaced
  `Anchors:` list notes each dropped proposed anchor (OWNERUX1-9). The pending
  decision files were regenerated from the templates.
- `--update-sparse` refuses when the pinned tree could not be listed or
  classified (DISTCI1-2), a relative pilot directory is made absolute before
  packaging (DISTCI1-1), and the protocol, README and guide wording now match
  the tools (SPECDOCS1-3, SPECDOCS1-4, SPECDOCS1-5).

Round 2 review fixes (finding IDs refer to the Campaign 2 round 2 review):
- A retry is allowed only if the prompt was never sent, as the run policy
  defines it. `session.md` gains `Prompt sent: yes | no`; `run-finish` refuses
  `no` for a timeout, a `no-publication` or `repair-budget` failure, a
  completed session or a transcript that contains the prompt. `run-prepare
  --retry` verifies the sealed record and refuses an attempt that timed out,
  failed after the prompt, does not say `Prompt sent: no`, or completed at any
  point of its amendment chain; `summarize` marks a run invalid when an earlier
  attempt sent the prompt. Every earlier attempt is verified like a current
  record and reported: `runs[].attempts`, `failures.earlierAttempts` and
  `inputs.runs[].earlierAttempts`, which a committed Stage 1 summary binds
  (INTEGRITY2-2, INTEGRITY2-3, SPECDOCS2-1).
- A recorded summary is final: `summarize --record` refuses a summary file
  that was ever committed, `run-prepare` and `summarize --stage all` refuse a
  Stage 1 summary that differs from its first commit or was committed more
  than once, and `check-frozen` fails when a committed stage summary is
  missing, changed or re-added (INTEGRITY2-1). `run-prepare` re-computes
  Stage 1 even in a pilot directory without its evidence (SPECDOCS2-4).
- `check-frozen` binds `freeze.json` to `candidate.json` for every captured
  campaign, with or without a summary (SPECDOCS2-2), prints a `not verified`
  line naming the history checks it cannot run in a shallow clone or without
  Git, and the Python CI jobs fetch the full history (the integration jobs'
  shallow checkouts only print those notes) (INTEGRITY2-4, SPECDOCS2-3). It
  names a decision file added after the freeze, which `check` notes
  (OWNERUX2-5).
- Owner files: a `#` line is a comment in the wrong form, reported under its
  section without dropping the lines around it, unless it looks like a heading
  (OWNERUX2-1); a second-review addition is adopted with
  `<their id>: adopted as <your id> -- <why>`, recorded as `adoptedAs`, so
  summaries count it inside the denominators (OWNERUX2-2); the high-severity
  defect note stays until a second-review addition is adopted as that defect
  (OWNERUX2-3); a wrapped line after a blank or note line, or a wrapped
  resolution containing `: `, is told to indent (OWNERUX2-6); the CI guard for
  pending files ignores what the grammar ignores (OWNERUX2-4).
- The Sensitivity section's macro and leave-one-task-out percentages are
  floored like the other Markdown percentages (SPECDOCS2-5).

Round 3 review fixes (finding IDs refer to the Campaign 2 round 3 review):
- The history checks read every version a file ever had in the history
  reachable from HEAD, merges included, and count distinct contents rather
  than adding commits. A recorded summary replaced through a merge, a freeze
  recorded inside a merge and then edited, and a removal hidden behind a merge
  are found; an ordinary pull-request merge is not a finding
  (INTEGRITY3-1). `candidate.json` is final once committed like a summary, and
  capture refuses a shallow or partial clone and a campaign whose candidate
  was ever committed (DISTCI3-2). A partial clone, or a history Git cannot
  read, is reported as not verified instead of "never committed", and a
  supersede refuses there (INTEGRITY3-5).
- Deleting a committed campaign does not clear the way for a new one:
  check-frozen fails when a campaign in the history reachable from `HEAD`
  that was ever committed is missing, also with a pre-freeze `tasks.json`, and
  requires every earlier campaign to be reached through `supersedes`; the
  freeze refuses while the history holds a campaign `tasks.json` does not name
  (INTEGRITY3-2). Two merged recordings of one summary are settled by the
  owner's `invalidation.md` and a new campaign, after which the finding is a
  note.
- `Prompt sent: no` is refused against sealed evidence: repair rounds above
  zero, a published `pilot.mlview.json` or a skill draft in the workspace at
  `run-finish`, a captured artifact or a sealed transcript with the prompt at
  `--amend` (which also never drops or replaces a sealed transcript), and any
  of these in `run-prepare --retry` and in `summarize`'s check of earlier
  attempts, which report why an attempt counts as sent (`sentBecause`)
  (INTEGRITY3-3, STATS3-1). `run-prepare --retry` refuses a retry beyond the
  policy's infrastructure retries (STATS3-2).
- With the same tools, a committed Stage 1 summary must equal the
  re-computation in every field and its Markdown the rendering of its JSON
  before Stage 2 is prepared; check-frozen checks the rendering while the
  summary names the running `tools/workflow_pilot.py` and otherwise notes it
  (INTEGRITY3-4).
- Summaries: baseline entries keep their failure, invalid reasons, warnings
  and earlier attempts (`baselines.earlierAttempts`), rendered in the
  Baseline comparison (STATS3-3, SPECDOCS3-1); a per-host miss names the host
  and each host gets its own early-stop bound (STATS3-4); a pending run shows
  no paired difference (STATS3-5).
- Owner files: only a section kind with at most one ID after a single `#`
  looks like a heading, and the error says the lines after it were not read
  (OWNERUX3-1, SPECDOCS3-2); a resolution that names the primary's own
  addition or starts like `adopted` must use the adoption form (OWNERUX3-2);
  a case-only duplicate resolution is an error (OWNERUX3-3); `check` keeps a
  primary with a late second review `frozen in` its campaign and lists that
  review's disagreements as notes for a new campaign, and check-frozen says
  to remove the late file to keep the campaign (OWNERUX3-4); a byte change
  after the freeze names the restore command and is labelled `changed after
  the freeze` (OWNERUX3-5); the pending-file CI guard ignores edited or
  removed tool notes (OWNERUX3-6); adopting a candidate item explains the
  non-adoption form (OWNERUX3-7); the high-severity note suggests an unused
  second-review defect ID (OWNERUX3-8); a mistyped resolution ID lists the
  items still open (OWNERUX3-9).
- Docs: campaign commits reach main by a merge commit or fast-forward, never
  a squash or rebase merge (DISTCI3-1); the root README no longer calls main
  unmerged (SPECDOCS3-4); the CI history wording is exact (SPECDOCS3-5).

Round 4 review fixes (finding IDs refer to the Campaign 2 round 4 review):
- A final file (`candidate.json`, a stage summary) is judged from Git object
  IDs: a version whose contents Git cannot read, such as a gitlink, no longer
  turns a replaced file into a "not verified" note, and a version committed as
  a gitlink or symbolic link is a problem (INTEGRITY4-1). The history queries
  pin `log.follow`, `log.diffMerges` and `log.showRoot` and fail loudly on an
  unexpected output form, so a user's Git configuration cannot hide a version
  or fail a superseding campaign (DISTCI4-2).
- The skill's drafts under `.mlview/` (SKILL.md's
  `.mlview/llm/<run-id>/draft.json`) count as evidence that the prompt was
  sent, in run-finish, `--amend`, `run-prepare --retry` and summarize
  (INTEGRITY4-2, STATS4-1, SPECDOCS4-1).
- A Stage 1 summary's `tooling` field no longer switches checks off on its
  own word: the helper hash must be the candidate's, any other tool hash must
  be the file committed with the summary, and the run statuses, failures and
  earlier attempts are compared whatever the tools; `summarize --record`
  refuses tools that differ from `HEAD` in the checkout, and check-frozen
  reports a renderer hash that is neither running nor committed with the
  summary (INTEGRITY4-3, STATS4-2).
- Owner messages: the restore advice for a changed or missing frozen file
  names where Git holds exactly the frozen bytes (the index or a commit) and
  offers no git command when it does not, so it never restores the pending
  template; the freeze says to commit before editing again (OWNERUX4-1,
  SPECDOCS4-4). `check` notes a missing or edited `>` proposal line with the
  ledger's text (INTEGRITY4-4). The high-severity note always names an unused
  second-review ID (OWNERUX4-2, SPECDOCS4-3). The named-item rule ignores a
  sentence-final `.` (OWNERUX4-3) and applies only to added items of the same
  kind, and the first-word rule says which word to change (OWNERUX4-7). An
  edited or removed frozen second review is handled like a late one
  (OWNERUX4-4). `# Fact checked` is a comment, not a phantom section
  (OWNERUX4-5), and an unknown `## ` heading says the lines after it were not
  read (OWNERUX4-6).
- The supersede path of the freeze refuses while a committed campaign is
  missing or off the `supersedes` chain (SPECDOCS4-2).
- The tests write summary Markdown as bytes, so the Windows job does not see
  CRLF (DISTCI4-1).

Round 5 review fixes (finding IDs refer to the Campaign 2 round 5 review):
- A summary's other-tool hashes are bound to Git history instead of one
  commit: each must be a version of that tool committed in the history of
  the commit that recorded the summary, so a pull, merge or tool commit
  between `summarize --record` and the summary's commit no longer wedges an
  honest summary (a rebase that rewrites the unpushed commit holding those
  tools still can: drop the summary commit and record again, corrected in
  the final round); a hash of tools never committed there is still
  refused. For a superseded campaign the owner invalidated, check-frozen
  keeps an unbound renderer hash as a note. `--record` says to commit both
  files at once, before any other commit, pull, merge or rebase
  (INTEGRITY5-1, DISTCI5-1, SPECDOCS5-1).
- With other tools, the baselines' statuses, failures, review states and
  earlier attempts are compared with the re-computation too (INTEGRITY5-2,
  STATS5-3; narrowed to sealed facts in the final round).
- Once the Stage 1 summary is recorded (in the working tree or the history),
  `run-prepare --retry` and `run-finish --amend` refuse Stage 1 runs, which
  would otherwise stop the recorded go from unlocking Stage 2 (STATS5-1).
- `summarize --stage all` no longer marks Stage 2 runs invalid, or lists
  false early-stop indicators, when the Stage 1 re-computation is incomplete
  only because the corpus is absent or unverified; the summary is
  incomplete with a note (STATS5-2).
- An earlier attempt that completed before an amendment says "counted as
  sent: it completed ..." instead of "prompt never sent" (STATS5-4).
- Owner messages: after the freeze, the proposal-line and high-severity notes
  of a frozen file never ask for an edit (OWNERUX5-1); a frozen second review
  that no longer parses is handled like an edited one (OWNERUX5-2); an
  unreadable primary is a freeze precondition and a check-frozen restore
  step instead of a traceback (OWNERUX5-3); a deleted frozen file gets its
  restore in `check <task>` and `check` (OWNERUX5-4); `# Scenario checked`,
  `# Task done` and `# Defects none` are comments, and `### Fact checked` says
  its lines were not read (OWNERUX5-6); the review guide states the adoption
  rules and the `#` line rules as the check applies them (OWNERUX5-5,
  SPECDOCS5-2).
- Differs from the Campaign 2 specification: the binding of a summary's
  `tooling` field to Git history (section 4.7 names only the hashes), the
  finality of Stage 1 evidence once its summary is recorded, the
  environment-incomplete Stage 1 re-computation in the all-stage summary,
  and the wider `#` comment rule (section 1.3).

Final round review fixes (finding IDs refer to the Campaign 2 final review,
calibrated to the threat model in the specification's section 1.10):
- `run-prepare` installs the candidate's skill from its `source.commit`
  (read through Git), never from the working tree, so a skill change on main
  during the pilot no longer blocks runs with a dead-end "check out the
  candidate commit" remedy; a note says when the checkout's skill differs,
  and `run-finish`'s doctor compares with the candidate's skill too. Without
  `candidate.json`, the tools say to work on a branch that contains it
  (HONESTF-1).
- The Stage 1 gate compares the sealed inputs (records, amendments, earlier
  attempts) and the decision, no longer the review files' bytes, so a
  re-save or note that keeps every verdict does no harm. A changed sealed
  input or a changed verdict names each run and what to restore, and leaves
  `summarize --stage all` incomplete instead of making Stage 2 runs invalid
  (HONESTF-2, SPECDOCSF-1, STATSF-2, STATSF-5). With other tools, a
  baseline's disclosure is its sealed facts (failure and earlier attempts),
  not its tool-judged status or review state (INTEGRITYF-1). An integrity
  problem is named with its first example and the summarize command
  (STATSF-4).
- The retry rule is shared: `summarize` lists each failure the run policy
  still lets the operator retry, with its command, the early-stop indicators
  count it as open, and `--record` refuses until it is retried (INTEGRITYF-3,
  STATSF-1). After the Stage 1 summary is recorded, `run-prepare` refuses a
  Stage 1 run before any retry hint, and a refused amendment says to undo an
  edit to the sealed `session.md` (INTEGRITYF-2). `--record` prints its
  finality warning after it writes, and the review template says Stage 1
  reviews are final.
- An amendment away from `completed` tells the operator to remove
  `review.md`; `check` of such a review says the same, and summarize names
  each run's first review problem (STATSF-3). The `--record` baseline rule
  applies to Stage 1 `go` and `stop` only.
- Decision files: a second review added after `Review: complete` is a to-do,
  not an error (HONESTF-3); an unreadable second review is named as such,
  never as "no second review ... delete this line" (OWNERUXF-1); a frozen file
  that no longer parses gets its frozen state and restore (OWNERUXF-2); the
  dropped-anchor note on a frozen file asks for no edit (OWNERUXF-3);
  `template` refuses to replace a deleted frozen file (OWNERUXF-6); the
  unbound-renderer error names a next step (OWNERUXF-7); a second review
  added after the freeze is moved out, never removed (OWNERUXF-8); the freeze
  `Next:` line names the merge rule (SPECDOCSF-3).
- Portability: every tool's stdout and stderr fall back to `\` escapes for
  characters the console encoding lacks, and the Markdown writes `>=`
  (HONESTF-4, DISTCIF-3); sparse checkouts use `init --no-cone` then
  `set --`, which git before 2.35 accepts (DISTCIF-2); the helper refuses a
  cited notebook nested more than 500 levels deep with its own message, so
  the result no longer depends on the Python version (3.14 parses what
  3.10-3.13 cannot; DISTCIF-1, N9); the Windows integration job gets 45
  minutes (DISTCIF-4); a missing Git is
  named as such (DISTCIF-5); a pilot directory given with `..` is judged by
  its real parents (HONESTF-5).
- Docs: squash-merge recovery (SPECDOCSF-2), the corrected rebase caveat
  (INTEGRITYF-4, SPECDOCSF-4), the review guide's adoption example and `#`
  rules (OWNERUXF-4, OWNERUXF-5, SPECDOCSF-6), the exact label and
  `--record` rules (SPECDOCSF-8), VALIDATION's tree ID instead of an
  unpushed commit (SPECDOCSF-7), and a "Known limits" section in the pilot
  README: the history checks catch accidents and make tampering visible,
  and do not stop someone with push access (SPECDOCSF-5).
- Differs from the Campaign 2 specification: the skill comes from the
  candidate's source commit rather than the checkout; `--record` refuses
  while a permitted retry is open; the Stage 1 gate compares review verdicts
  rather than review bytes; a changed Stage 1 input leaves the all-stage
  summary incomplete rather than invalid; the Markdown writes `>=`.

Final check fixes (REG IDs refer to the final check of the final round):
- With a Stage 1 summary recorded by other (Git-bound) tools, a changed
  Stage 1 verdict or reviewer that keeps the decision at `go` now holds
  Stage 2 and leaves `summarize --stage all` incomplete, as with the same
  tools: for each `review.md` whose bytes changed since the record (or that
  was deleted), the verdict-derived fields (reviewed, reviewer and the review
  counts of a skill run; the paired row of a baseline) are compared and each
  run is named. Tool-judged fields are still not compared across tool
  versions, and a re-save or note that keeps every verdict still does no harm
  (REG-1).
- The squash-merge recovery names the commands that report a candidate
  commit outside `HEAD`'s history (`run-prepare`, `summarize` and
  `workflow_candidate.py --check`; `check-frozen` does not check it) and
  confirms the recovery with `workflow_candidate.py --check` (REG-2).
- `template --init-all` prints each missing frozen file on its own line
  (REG-3).

Follow-up check fixes (NEW IDs refer to the check of the final check fixes),
all for a Stage 1 summary recorded by other (Git-bound) tools:
- A baseline the recording tools judged invalid has no recorded review, so
  the summary reports none of its verdicts; when later tools judge it valid
  and read its untouched review, Stage 2 is no longer held with a message
  that its `review.md` changed (NEW-1).
- A changed review is compared by what the running tools read from it, so
  after a tool change that judges or counts it differently even a re-save can
  hold Stage 2. The message now says so, says when these tools find problems
  in the review or find it incomplete, and gives the sha256 the summary
  recorded for each named `review.md`; restoring those exact bytes clears the
  hold (NEW-2).
- A changed false accusation in a baseline review now holds Stage 2 too: the
  summary carries only the baselines' total, which is compared whenever a
  baseline review changed and is named with each changed baseline (NEW-3).
- Known limit (RC2-1, left open): because that total covers every baseline,
  a later tool change in how one baseline's accusations count (including a
  baseline the recording tools judged invalid, the NEW-1 case), together with
  a re-save of a different baseline review, holds Stage 2 and names the
  re-saved review. Restoring that review's exact bytes clears it. Comparing a
  normalized hash of each Stage 1 review instead of re-derived verdicts would
  remove this class of case; that is left for a later change.

Not in this version: the owner's reference review and freeze, the development
adjudication, any native session and the pilot itself (the owner's
decisions); second-review tooling for run reviews and the development
adjudication; SKILL-16 (identity framing; `files` is documented as part of the
identity); DOCS-7/10/17;
a CI job that fetches the corpus; blinded or randomised review order;
hash-pinned development dependencies; automatic transcript capture.
`development/native-reviews/README.md` is a frozen record and still shows
`review-packet --output` without `--force`, which a regeneration now needs.

## 0.2.0 — reliability and trust (Campaign 1)

Every manifest now says 0.2.0, the first version number distinct from the
analyzer-era 0.1.0 that `main` shipped before it. It was released on
2026-09-25, when the owner squash-merged PR #9 into `main` (`d99904f`), and
also carries the two "Unreleased" native entries
below, which never shipped under a version number. Finding IDs refer to the
2026-09-25 takeover review.

Open panel and freshness:
- An open panel follows the artifact file: it shows the newest valid revision
  on disk and no longer refuses every later revision after rejecting one;
  Refine continues from the revision actually in the file (CONTRACT-2 = EXT-1 =
  CRIT-2, EXT-11, EXT-12, NEW-1).
- A revision whose sources changed is shown as a historical diagram with a
  banner naming the changed files; only jumps into those files are blocked. A
  revision the panel saw superseded (for example restored from git) is refused
  until **MLView: Open Generated Diagram** is re-run. Banners name each case and
  carry no absolute paths (EXT-18, CRIT-7).
- Freshness uses the saved bytes on disk, as the helper does, so UTF-8 BOM and
  CRLF files no longer look stale while open. Unsaved editor changes are
  reported separately and block only a jump whose cited lines moved. Open files
  are matched by real path, so symlinked roots are handled (an automated test
  on macOS); Windows drive-letter case matching is implemented and unit-tested
  but has not run on Windows (EXT-7 = CONTRACT-5, EXT-2, SKILL-9, EXT-9, EXT-13
  functional part).
- Both high-contrast themes use the high-contrast palette (EXT-4, RENDER-5), and
  a restored panel opens only a `*.mlview.json` inside the workspace (EXT-16).

Refinement:
- The copied prompt has a host-written header and puts all artifact text in one
  escaped JSON data block, so artifact text cannot forge prompt lines. It names
  the artifact path portably and states VS Code Restricted Mode in an untrusted
  workspace (EXT-6, EXT-17, CRIT-8).
- Five explicit intents (Explain, Expand, Challenge, Trace, Custom), with the
  same meanings in the skill; Explain never publishes (EXT-6, CRIT-8).
- The Refine composer keeps its intent, text and selection across refreshes and
  closes only after the prompt was copied (VIEWUI-4).

Viewer:
- A panel renders once on open and once per new revision; refreshes keep the
  viewport, and a reopened panel restores it (VIEWUI-2 = EXT-3, VIEWUI-3).
- Export and Copy scope report success only after VS Code saved or copied. A
  PNG too large for the canvas is scaled down to fit; if it still cannot be
  drawn, the viewer asks you to save the SVG instead (copying a PNG falls back
  to copying the SVG) (CRIT-5, RENDER-3, VIEWUI-10 = EXT-5).
- A document without findings says the assistant recorded none instead of a
  clean result; workflow-level findings survive stage filters and scopes
  (VIEWUI-1, CRIT-3).
- Analyzer-era surfaces (pipeline chooser, Concerns, "Issues" wording, rule
  grouping, limitation chips) are gone from authored diagrams. Scope-to-node
  and search work by node ID, cited file and quote; notebook evidence names its
  cell (VIEWUI-5 to VIEWUI-8, VIEWUI-11 to VIEWUI-15).
- A rebuild during hover no longer leaves the diagram dimmed; reduced motion
  keeps hover-intent delays (RENDER-1, RENDER-19). Finding connectors go only to
  nodes the author named; distinct IDs get distinct element ids; exports use
  the full title and escape invalid characters (RENDER-4, RENDER-6, RENDER-7,
  RENDER-8 = CONTRACT-14, RENDER-11).
- Edge routing runs its cheap geometric test first: identical layout, faster
  large diagrams in the jsdom benchmark (RENDER-2).

Skill and helper:
- MLView's own artifacts, drafts and installed skill are never fingerprinted,
  so a refinement is no longer stale the moment it is published; citing them is
  an error, and `--output` must end in `.mlview.json` (SKILL-2, CRIT-1).
- Drafts omit `verification`; a stale fingerprint names the file and the fix
  (SKILL-3). Binary and non-UTF-8 inspected files can be listed, and files over
  8 MiB are listed without a fingerprint (CONTRACT-6).
- The helper refuses what the viewer cannot open: a `null` node parent or
  verification block, unpaired surrogates, drive-letter paths, NUL in
  entrypoints and artifacts over 2 MiB (CONTRACT-1, CONTRACT-3, CONTRACT-4,
  CONTRACT-10, SKILL-21).
- Errors say what to fix: relative drafts resolve against `--workspace`,
  distinct draft errors with JSON line and column, the published revision in
  `revision_conflict`, the cited lines in `quote_mismatch`, reachable
  `revision_id_reused`, and a JSON `internal_error` instead of a traceback
  (CONTRACT-15 = SKILL-14, SKILL-4, CONTRACT-7, SKILL-11). Published files keep
  their permissions; notebooks are parsed once (SKILL-12, SKILL-18).
- SKILL.md treats repository and artifact text as data, documents the intents,
  what `--workspace` must be, recovery from helper errors and what to report;
  the bundled contract lists every field (CRIT-8, EXT-6, SKILL-5, SKILL-6,
  SKILL-20, CRIT-6).

Contract, checks and distribution:
- `contracts/conformance` holds 65 self-contained cases run through the
  schema, the helper and the extension, plus a helper-publish, viewer-load
  round trip; the extension now matches the helper on notebook cells, exact
  quotes, code-point lengths and empty parents (CONTRACT-8 = SKILL-17,
  CONTRACT-9, CONTRACT-10, CONTRACT-11, CONTRACT-4).
- New regression suites cover revision lineage, the refine wedge with the real
  helper (required by the e2e gate), the host protocol and bootstrap, export
  payloads, recorded artifacts, bundle hygiene and a routed-geometry golden
  (EXT-8, VIEWUI-17, RENDER-12).
- `tools/verify.py` also checks the marketplace and viewer version literals
  (CRIT-4). The Claude plugin's GitHub install command names the real
  marketplace (DOCS-1 = SKILL-8). Dead export and `showOutput` code is gone
  and the development launch configurations open the repository root
  (EXT-14, EXT-15, DOCS-15).
- CLAUDE.md is the tracked agent guide and AGENTS.md is removed; current docs
  describe the new panel, freshness and refinement behaviour, and more of them
  are link-checked (DOCS-3 to DOCS-6, DOCS-9, DOCS-11, DOCS-13 to DOCS-16,
  DOCS-18, DOCS-19).

Fixes from the first review of this campaign (finding IDs from the round-1
review): re-running Open no longer turns an edited draft's historical banner
into a rejection (LINEAGE1-1); a deeply nested artifact is a parse error
instead of a stuck "checking" status (LINEAGE1-2); a direct child of the shown
revision is always adopted (LINEAGE1-3); each disk event gets fresh read
retries (LINEAGE1-4); banner and prompt text from the artifact is single-line,
bounded, and escapes C0 and C1 controls, bidirectional controls, line and
paragraph separators and Unicode default-ignorable characters (SECURITY1-1,
SECURITY1-2); restored and opened paths are normalised before the workspace
check, and refine selections must have a string kind (SECURITY1-3,
SECURITY1-4); links and aliases of MLView files are never fingerprinted
(SECURITY1-5); the helper refuses to edit a published artifact in any case
spelling, reports a missing `--workspace`, more than 2000 tracked files, deep
nesting, an oversize artifact and a missing revision ID with actionable codes,
and checks dates the same way on every Python (HELPER1-1 to HELPER1-6,
SECURITY1-6, SPECDOCS1-5); a scoped viewport and an open composer survive a
webview recreation, a refusal does not outlive its revision, the scope picker
names notebook cells and searches phases, focus mode survives re-renders, and
cards say "step" and "finding" (WEBVIEW1-1 to WEBVIEW1-7, LINEAGE1-5); new
corpus cases pin changed inspected files, entrypoint drive letters, BOM
notebooks and Latin-1 sources (SPECDOCS1-1 to SPECDOCS1-3).

Fixes from the second review of this campaign (finding IDs from the round-2
review): a Refine refusal about a missing or unreadable artifact file is
cleared once the file is read again, even when the revision is unchanged
(LINEAGE2-1); a hand-edited value the viewer's checks used to crash on (an
object with a `toString` member) is reported as an issue, so Refine continues
from that revision instead of calling the file unreadable (LINEAGE2-2); an
artifact opened through a differently cased path on macOS opens in the
workspace folder's spelling (LINEAGE2-3); both layers treat the long s
(U+017F) and the Kelvin sign (U+212A) as `s` and `k` when deciding what is an
MLView file, as case-insensitive volumes do (SECURITY2-1); the escape set now
covers every Unicode default-ignorable character, including variation
selectors and Hangul fillers (SECURITY2-2, SPECDOCS2-1); the helper rejects
`NaN` and `Infinity`, which are not JSON, in drafts and in an existing
artifact (SPECDOCS2-3); the corpus pins the 64-level nesting bound, and both
runners read JSON the way the product does (SPECDOCS2-4); docs no longer say
evidence quotes are copied into the prompt (SPECDOCS2-2).

Not in this version: the manual live VS Code checks (HC Light, BOM files open
while publishing, symlinked roots, Windows drive letters), human semantic
review and the held-out pilot. Deferred: EXT-13's per-click revalidation cost,
EXT-10, the routing grid index, edge connectors and edge search hits,
RENDER-9/16/20, and DOCS-7/10/17 (need owner approval).

## Unreleased — trust and usability

- Clarify authored uncertainty and severity, show every evidence quote, and add
  direct claim challenges plus accessible textual relationship views.
- Coalesce edit-driven validation; guard stale results, navigation and disposal
  across overlapping source and artifact changes.
- Add targeted interpretation guides and protected incremental draft edits.
- Identify full skill bundles, diagnose installation drift, prepare separate
  matched baselines and measure synthetic renderer scale through 2,000 nodes.
- Fix native Windows draft paths and CI timing, keep source links beside the
  diagram, and support arrow/Home/End navigation across the side tabs.
- Align evidence requirements across the Python and VS Code validators;
  correct synthetic benchmark references and authored search/Outline wording.
- Preserve WorkflowDocument 1.0 and historical evaluation records. Human
  semantic review and broader native-host/platform validation remain outstanding.

## Unreleased — native workflow only

- Remove the Python static analyzer, CLI, rules, caches, static reports, MCP
  services, pre-commit hook, GitHub action, and static extension commands.
- Ship the active-assistant MLView skill and WorkflowDocument viewer only.
- Move retained ML example sources into evaluation fixtures without changing
  recorded native outputs, evidence quotes or their hashes.
- Replace analyzer release gates with native helper/viewer/distribution checks.


The older dated entries below were moved here from `docs/STATUS.md`, each
condensed to what changed and the numbers that were measured at the time. The
long-form reasoning behind them is in the historical `docs/CONTRACTS.md` and
`docs/ROADMAP.md`.

**Most entries below were written before CI could confirm them.** GitHub Actions
billing was blocked at the account level for the hardening rounds, the
consolidation and the recall campaign, so every job came back unstarted and each
of those entries is a measurement from one machine. The block went with the
repository going public on 2026-09-15: the matrix has since run green over the
legacy tree the consolidation entry describes — thirteen jobs, run 34986234828 and run
34986239243, and thirteen again over its review fixes, run 35001150997 and run
35001153856. Where an older entry quotes a CI run id, that run predates the
block.

---

## Unreleased — review and public readiness (2026-09-18)

- Hardened artifact paths, timestamps, malformed-input handling and publication
  errors, with matching Python and TypeScript checks.
- Reduced repeated parent traversal, source reads, hashing and graph counting.
- Added symlink-safe skill distribution and a shared MIT license payload;
  pinned the VSIX packager and adopted SPDX wheel metadata.
- Fixed evaluation prompt/pointer validation and Windows review paths, and
  made failed wheel builds fail their gate.
- Updated contribution forms and documentation, preserved upstream evaluation
  license notices, and enabled GitHub secret scanning and push protection.

See the [review and validation record](docs/PUBLIC_READINESS_REVIEW.md).
Human semantic review and the held-out pilot remain pending.

---

## Unreleased — native LLM workflow (2026-09-16–17)

MLView now supplies a portable skill that asks the active assistant to interpret
source and configuration, then publishes a cited semantic artifact for the
interactive VS Code viewer. The default workflow follows the user's corrected
intent; the existing static analyzer remains available as a legacy path.

- Added WorkflowDocument 1.0, exact evidence and inspected-file fingerprints,
  bounded validation/repair, guarded atomic publication, and revision lineage.
- Added **Open Generated Diagram**, custom phases, groups/cycles, notebook
  evidence, source freshness, refinement prompts, and SVG/PNG exports.
- Added shared and Claude skill distributions; Claude's old automatic static
  hooks are now opt-in, and static VS Code entrypoints are visibly labeled.
- Added node/edge/finding refinement intents, visible scenario context and
  stable-ID preservation guidance in prompts copied to the native assistant.
- Fixed authored diagram selection being lost when VS Code recreated the
  webview after source navigation. State is saved before navigation and retained
  during bootstrap; regression coverage includes immediate webview destruction.
- Added a read-only installation doctor, deterministic skill ZIPs, extracted
  helper checks, and CI distribution artifacts for both host layouts.
- Added eight development scenarios and the protocol for a 72-run held-out
  pilot. The pilot and human semantic adjudication are outstanding.

See [implementation and local verification](docs/LLM_IMPLEMENTATION.md) and the
[native-host integration log](docs/demo-logs/2026-09-16-llm-workflow.md). Local
verification and revision-specific remote CI are separate evidence; historical
static accuracy numbers do not measure LLM understanding.

---

## Unreleased — research review of coverage and accuracy (2026-09-16)

Documentation only; no analyzer, viewer or host code changed. Seven research
passes over the shipped rules, the 158-program corpus and the 37 pinned public
repositories, written up as [`docs/RESEARCH_COVERAGE_ACCURACY.md`](docs/RESEARCH_COVERAGE_ACCURACY.md)
with a 120-entry bibliography in `docs/research/sources.md`.

- **Baseline reproduced** before anything was proposed: 80.4 % recall (72.5 %
  visible above the 0.60 confidence floor), 100 % precision, graph fidelity
  91.9 %, 706 public-corpus findings with 0 adjudicated false positives.
- **Every one of the 107 missed labels classified** into seven causes, with the
  two smallest IR changes (identity through a subscript or a shape-preserving
  method, and HuggingFace output objects) worth 22 of them.
- **Three defects in shipped rules found by measurement**, each with a
  reproduced fixture: `keras.Model.predict` tagged as hard labels (an `MLV306`
  false positive and an `MLV305` false negative at once), `GroupShuffleSplit`
  and `StratifiedGroupKFold` swapped in `MLV106`'s shuffle table, and
  `MLV803`'s `torch.load` arm accusing a default that torch 2.6+ no longer has.
  None is fixed in this entry; they are Sprint A of the document's §8.
- **37 candidate rules in three tiers**, each with its naive false-positive
  count measured by an AST sweep over the 4,467 public-corpus files before the
  rule was designed; four measure zero, and one (`MLV117`) is recommended
  against on that evidence.
- **The gate cannot yet accept a new rule**: the corpus labels exactly the 36
  shipped codes, so the first run of any new rule fails the ratchet on every
  program it fires on. The document's §7.1 proposes the adjudication step that
  fixes that.

---

## Unreleased — consolidation and recall (2026-09-15)

One campaign, three strands: make the tree say one true thing about itself
(**C1–C9**), close the largest known recall families (**R1–R5**), and fix what
the campaign's own review confirmed. It is built on the hardening base — the
158-program labelled corpus, the pinned public corpus and PR #4's 92 fixes are
underneath everything here, which is why several figures below are *lower* than
the ones the same items measured against a smaller corpus.

### Consolidation

- **C1 · Contracts v1.1.** `docs/CONTRACTS.md` is rewritten as one coherent
  document rather than a v1.0 body with a hundred-odd amendments bolted to the
  end of it: every amendment is folded into the section that owns its clause,
  including the hardening rounds' §11.50–§11.61, and an amendment index says
  where each numbered item went. The amended v1.0 is archived verbatim under
  `docs/archive/` so no decision record is erased.
- **C2 · The VSIX analyzer copy is a build artifact.** `vscode-extension/core`
  is gitignored and written by `vscode-extension/tools/sync-core.mjs`, which
  `compile`, `pretest` and `vscode:prepublish` all run. `claude-plugin/vendor`
  stays **tracked**, and for a reason rather than by omission: a marketplace
  install copies the plugin directory verbatim off a git ref, so for that host
  what git holds is what the user runs, while a VSIX is built from a working
  tree. `tools/sync-core.py` gained a `generated` flag, `tools/verify.py`'s
  `vsix` row is strict, and a test asserts the directory is untracked.
- **C3 · No source file over 750 lines.** Every one that was is split into
  cohesive modules under 600, with re-exports so no importer changed and
  **byte-identical outputs**: `tools/perf_equiv.py --expect-same` against a
  reference tree of `origin/sprint5` after each of the thirteen analyzer splits,
  an AST comparison finding all 451 definitions byte-for-byte the reference's,
  and — for the viewer's five CSS layers — the minified concatenation identical
  at 73 127 B before and after. That proof was taken **at the split**, against a
  tree recall had not yet touched; recall then re-based the graph deliberately,
  so `--expect-same` is no longer the right question to ask of this commit and
  `--demo` byte parity, the two accuracy ratchets and the public-corpus gate are.
- **C4 · The docs say one thing each.** `docs/STATUS.md` is a short
  current-state page; this file is the history it used to carry; `README.md` is
  trimmed to what a reader needs before they trust an answer.
- **C5 · `.workflows/` leaves the index** and is gitignored: a scratch directory
  for this project's own agent runs is not part of the product.
- **C6 · CI in two tiers**, because the repository is private and minutes are
  metered. A branch push runs the analyzer on Python 3.10 and 3.13, the viewer on
  Node 20, both host suites, the accuracy corpus and the Linux e2e table; a pull
  request and a push to `main` add Python 3.11 and 3.12, Node 22, the Windows
  e2e table, a macOS smoke job and packaging. A push that touches only Markdown
  and `docs/` runs nothing. The public-corpus nightly is unchanged.
- **C7 · `LICENSE`** — MIT, Copyright (c) 2026 realmyang. The VS Code
  Marketplace pre-flight requires one and this repository had none.
- **C8 · Four honesty fixes.** The `--framework` caveat reaches **both** hosts'
  coverage blocks, so a narrowed rule set can never be read as a cleaner project;
  `Escape` closes the legend, which needed a rung on the dismissal cascade
  §11.13 freezes rather than a line of code; the parse cache defaults to the
  **user's** cache directory rather than `.mlview/cache` inside the folder being
  analyzed (`MLVIEW_CACHE_DIR` overrides it, `MLVIEW_NO_CACHE=1` disables it);
  and SARIF output carries `fixes[]`.
- **C9 · Two runbooks.** `docs/VALIDATION.md` is the step-by-step for validating
  MLView by hand on a second machine and then publishing it — every command in
  both a POSIX and a PowerShell form — and `docs/DEMO_LOG.md` is the template the
  validator fills in as they go.

### Recall

- **R1 · `--dataflow ip` is the default.** `local` stays as the narrower
  opt-out; `--demo` output is byte-identical either way, so the frozen golden did
  not move.
- **R2 · Five more knowledge tables** — pandas, `evaluate`, Keras,
  statsmodels/Prophet and torchmetrics — so the graph stops losing the ops those
  libraries name.
- **R3 · Calls through workspace objects**, which has been the largest single
  recall family since ANA-1: construction nodes, `__call__` → `forward`,
  workspace loss classes, factory returns, carriage through dicts, tuples and
  dataclasses, `self.<attr>` across methods, and identity through
  `accelerator.prepare` / `fabric.setup` / `torch.compile`. The first two of
  those three keep their types through `ir/bindings_values._self_wrapped` rather
  than through a knowledge row asserting *position i out is argument i in* — the
  narrower claim, and the reason `WRAP_PREPARE` is deliberately absent
  (`docs/CONTRACTS.md` §19 A2).
- **R4 · Value typing.** `LOGITS` / `PROBS` / `PREDS` flow into MLV305, MLV306,
  MLV401 and MLV402, with confidence de-rated per hop.
- **R5 · The rule shapes that were missing.** Three interprocedural leakage
  walks — MLV101 through a `return`, MLV102 through a fold index, MLV103 through
  a callee, all `ip`-only — plus MLV208 learning to find its `GradScaler` by
  identity as well as by proximity. **MLV114 needed nothing**: this base's rule
  was already a strict superset of what the campaign had written for it, and the
  honest entry says so rather than claiming a fix that was not made.

### Review fixes

Confirmed by the campaign's own review, one fix each:

- **A marketplace entry that installed a directory with no plugin in it.** The
  `github` source form takes `repo` / `ref` / `sha` and **no `path`**: the
  fetched tree's root becomes the plugin root, and this repository's root holds a
  marketplace manifest and no `plugin.json`. The hosted entry is `git-subdir` at
  `path: "claude-plugin"`, and `claude-plugin/tests/test_plugin_manifest.py` now
  asserts that **every** entry's resolved directory really contains
  `.claude-plugin/plugin.json` — the class, not the instance.
- **R13 / R15 read a `return` only when it bound a name first**, so
  `return scaler.fit_transform(frame)` missed while `out = …; return out` hit.
- **R3's carriage did not compose with a parameter boundary**, which is the
  GradScaler-in-a-parameter-dict the campaign named.
- **A `file://` report click killed the keyboard.** Handing a URL to the OS
  protocol handler costs the *launching* browsing context its keyboard,
  permanently, so a hand validation of the viewer read as broken from its second
  step. The launch now goes through one named transient context, and a refused
  launch is answered at once rather than after a silence that read as success.
- **R18's MLV205 widening produced three public-corpus false positives.** The
  guard is kept; the widening is not. A high-severity claim about correct code is
  the worst outcome this product has, and the public corpus is the only gate that
  can see one nobody thought to label.
- **The `--framework` caveat did not reach the hosts' coverage blocks** —
  C8's first clause, listed here too because it was found by review rather than
  planned.

### Review round 2 — the rebuild's own review, process and docs

The rebuild was reviewed again on its real base. Five findings were confirmed
against the process-and-docs surfaces; each is fixed at its cause and, where a
check could have seen it, a check now does. The doc gate is **twenty-three
checks**, up from twenty-one.

- **The doc gate's check 22 was cited by the contract and absent from the
  tree.** `scripts/doc_claims.py` — the gate that forbids a green claim and the
  CI matrix in one breath without saying whether the matrix ran — was written
  during the first campaign and never carried onto this base, while
  `docs/CONTRACTS.md` §16.4 and §17 E28 both asserted it was running (**no CI
  job has started on this line of work at all**, which is the whole reason the
  check exists). It is back
  as **check 22** (it collided with `doc_surfaces`' check 16 before), wired into
  `check_docs.run`, and `scripts/test_doc_claims.py` now pins two things the
  first round could not: that the module is *wired in* rather than merely
  present, and that `docs/CONTRACTS.md` names no `scripts/*.py` missing from the
  tree — CONTRACTS is in `check_docs.SKIP` by design, which is exactly how a
  contract came to name a file that did not exist.
- **§7's `mlview diff` figures were three mutually inconsistent sets.** The
  prose said 25 / 15 / 8 / 31 and named `python -m mlview diff` as the authority;
  the authority says **26 / 15 / 8 / 36**, edges **27 / 22 / 1 / 28**, headline
  `+26 nodes · −15 nodes · 0 new findings · 15 fixed`, and both pinning tests had
  already been updated to say so. The section's own JSONC sketch carried a third
  set again. All three are corrected, §17 E36 stops restating a live figure, and
  new **check 23** holds §7 to `analyzer/tests/core/test_diff.py` — the one place
  the doc gate reads CONTRACTS, anchored on the `## 7.` heading so §17's errata
  keep quoting the superseded figures they exist to record.
- **`docs/VALIDATION.md` C5 named a coverage row that never appears.** A
  `--framework` run emits one coverage row and its kind is `framework_filter`;
  `framework_suppressed` appears only in the bare `diagnostics` tally, the same
  cost stated twice (§11.4 C3). A validator checking the kind would have recorded
  a fail against correct behaviour on the one row that exercises C8 end to end.
- **§4.0 prescribed `python tools/wheel_check.py --sdist`, a flag that does not
  exist.** The tool takes `--no-build` and nothing else. The line is gone and the
  gap it papered over is stated instead: **the sdist is published untested** —
  nothing in the repo or in CI builds or smoke-tests one — with the by-hand
  equivalent written out, because a version can never be re-uploaded.
- **B2 told the validator the standalone report "cannot open your editor".** It
  can, and for exactly the report Session B produces: `deepLinkPlan` returns
  `launch` for a top-level `file:` document and hands the `vscode://` URL to the
  OS through a transient window it closes after ~700 ms. Only an embedded or
  `http(s)` report copies. The row now describes both outcomes and says which one
  is the fail (silence).

Four minors went with them: §18's amendment index is total again (§7.1–§7.5 and
§10 had no rows), §2.6 C9's gate citations name the three tests that exist — two of
which read the analyzer's own declaration, while the extension's is a hardcoded
transcription and is recorded as a stated gap — §14.2 R19 says where its negative fixtures actually live, and the five
clauses §19.1 corrects now say so where a reader meets them. The stale counts
that no check reads — "24 third-party repositories with 26 shell scripts", the
VSIX row's 162 files / 110 core files — are replaced by the constant or the
command that settles them rather than by newer numbers.

### Review round 3 — the analyzer and the viewer, read against the contract

The same review read the build against `docs/CONTRACTS.md` rather than against
its own diff, and confirmed ten more. **Eight of the ten are the contract being
right and the code being wrong**: the clause was written, folded and shipped as
prose, and nothing in the tree ever asserted it — which is §16.4's stated gap
(no gate compares the contract to the build) arriving as ten defects at once.
Every one is now gated by a test that reads the analyzer's **own declaration**
rather than a transcription of it, and the clauses are folded as
`docs/CONTRACTS.md` **§19.4 A9–A19**.

- **A `--framework`-narrowed run still returned a flat clean bill of health.**
  C8 put `framework_filter` in the core and in two hosts' coverage blocks and
  never in `emit/answers_text`, the tuple the Answer Card, the MCP `answers`
  payload and the CLI `verdict:` row are all built from. On
  `samples/vision_pipeline_clean` the verdict under `--framework torch` was
  byte-identical to the verdict under `--framework auto` — *"No findings: no
  rule fired on this workspace."* — with a coverage block one screen below it
  naming five rules that did not run. The verdict now carries both admissions in
  one sentence and counts a filter in **rules**, never folded into a blind-spot
  total.
- **The viewer read two of the core's three coverage kinds**, and its own extra
  as the third. On the same project the rail said *"nothing to flag"*, drew zero
  banners, and put the whole caveat into one **287-character** generic chip. It
  now draws a 38-character chip, a clause in the coverage banner and the rail's
  clean-state caveat, and `webview/test/hardening_coverage_kinds.test.mjs`
  **parses** `core/coverage.py` so the next kind the core adds cannot drift out
  of the viewer silently.
- **Both slash-command prompts told the model to read a coverage row this host
  never renders** — `framework_suppressed` where a `--framework` run emits
  `framework_filter`.
- **A criterion reached through a dataclass field or a constructor parameter
  never earned the LOSS role**, so MLV201 / MLV202 / MLV203 / MLV205 — two of
  them high — all skipped the training step behind a coverage note. §5.3 A11 (c)
  and (d) were contractual and unimplemented; what travels is now the field's
  **identity**, not only its tag. Deliberately **not** extended to a plain
  parameter: doing so made `x.size()` resolve to `torch.nn.LayerNorm.size` and
  cost `nlp_gpt_pretrain` two dataflow edges `local` draws, and `ip` must never
  report less than `local`.
- **A dict returned from a factory did not carry its entries**, though the same
  dict written in the caller's own scope did, because the inferred half of
  `unresolved_callee` was written once instead of recomputed each IR round —
  which A12′ already said in as many words. MLV208 was the finding lost.
- **R4's value tags died at a tuple-position `return`, and its three hops were
  being spent on things that cross no object.** A per-batch helper, a collector
  and a `.detach().cpu().numpy()` tail spend four between them, so MLV305 went
  silent two *object* hops from a value that reaches `accuracy_score` with no
  argmax. A hop is now **crossing an object**; the free links have their own
  bound.
- **MLV103 fired or stayed silent on whether the caller happened to reuse the
  callee's argument name**, and a bare `return pca.fit_transform(X)` was silent
  where the two-line spelling fired — R13's third form, which R15 claims to read
  as well. A returned call contributes its operands and not its callee text, and
  §19.1 A5's ambiguity guard is narrowed to the tuple-or-list returns it was
  measured on. The precision case it exists for is pinned by name.
- **MLV111 still read `call.var`** where MLV110 had been given the one-hop name
  lookup, so a program that inverts both shuffle flags behind two factories
  reported only its MLV110 half. MLV111 requires **every** name the construction
  is bound to to read as an evaluation loader; a name may reinforce and never
  create.
- **C3's split of `analyzer/tools/gen_rule_docs.py` was lost** — 850 lines,
  while two documents claimed the 750-line inequality. Split along the line the
  rule codes already draw (253 / 333 / 323) with byte-identical output.
- **`analyzer/LICENSE` was the third copy C7 never landed**, and
  `analyzer/pyproject.toml` named no `license-files`, so the wheel a validator is
  walked into publishing carried **no licence file at all**.

**What moved on the corpus**, both readings up and both ratcheted: visible recall
72.3% → **72.5%** (`ip`) and 70.5% → **70.7%** (`local`), with MLV110's `visible`
column 21 → 22 — all of it earned by §5.3 A11 (d), measured by disabling that one
fallback and watching both numbers go back. The other fixes move no corpus number,
because the 158 programs do not spell those shapes; each is gated instead by
`analyzer/tests/core/test_campaign_review_fixes.py` — 23 tests, one per confirmed
finding, each a **pair** of programs differing only in the thing MLView should not
have cared about.

### What it measured

Over the 158-program labelled corpus, **precision stayed at 100.0% with zero
forbidden and zero unlabelled findings in both dataflow modes** — which is the
number that had to hold, because every point of recall below was bought without
one false positive.

| | before | after |
|---|---|---|
| Recall, `ip` (546 labels) | 79.1% | **80.4%** |
| Recall, `local` (546 labels) | 77.8% | **78.2%** |
| Recall, `ip`, the 515 unseen labels | 77.8% | **79.2%** |
| Graph fidelity (1166 hand-labelled ops) | 84.5% | **91.9%** |

Per rule, `ip`: MLV103 22.2% → **44.4%**, MLV208 14.3% → **28.6%**, MLV305
14.3% → **20.0%**, MLV402 27.3% → **36.4%**, MLV101 71.0% → **77.4%**, MLV102
60.0% → **70.0%**. The shipped sample pair moved together — `vision_pipeline`
54 → 59 nodes and `vision_pipeline_clean` 64 → 70 — with **no finding moved**:
all 15 keep their code, line, severity and confidence.

The cost is stated rather than hidden: the interprocedural summary pass now runs
on every unflagged run, and `tools/perf_equiv.py --bench` measures 0.76–0.84×
against an `origin/sprint5` reference on 4-, 50- and 200-file corpora. Roughly a
fifth of that is the `ip` default and the rest is R3's extra graph pass.

### Public readiness

The repository went public on 2026-09-15, and this is what that took. **No
machine is named in the tree any more**: the golden document's workspace root
moved from a real Windows home directory to the neutral `/home/mlview/MLView`,
and every artifact derived from it was regenerated with the repository's own
generators, so the golden, its two mirrors, `contracts/scope.expected.json`, the
plugin vendor copy and the webview dev page still agree and `analyze --demo` is
still byte-identical — at **45 588** bytes now rather than 46 078, because the
shorter root shortens every absolute path the document carries. Notes dated
before this round, here and in `docs/CONTRACTS.md`, quote the larger figure and
were true when written. Two path-traversal test payloads that carried the author's
username now use the `Users/someone` convention. The frozen v1.0 spec keeps its
historical path on purpose; `docs/archive/README.md` says why. A scan of every
commit on every ref found no secret and no email but git author metadata.

`THIRD_PARTY_NOTICES.md` is new and records the whole redistribution surface —
`@dagrejs/dagre` 3.1.1 and `@dagrejs/graphlib` 4.0.5, MIT, verbatim, and which of
the four artifacts carries them. The wheel is not exempt: it declares no Python
dependency but ships `emit/assets/mlview.js` with dagre inlined. `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SECURITY.md`, four issue forms, a pull-request template,
`.editorconfig`, `docs/README.md` and `docs/CONTRIBUTING-RULES.md` landed with
it, each written from the tools rather than from a template. `README.md` became a
landing page — badges, three screenshots of the shipped sample under
`docs/media/`, a quick start per host, the rule families, the measured accuracy
table and the known gaps.

`.gitattributes` gained a `diff` attribute for source extensions, which fixes a
real defect rather than a preference: `webview/src/diff/adopt.ts` embeds literal
NUL bytes as string-join separators inside git's 8000-byte binary-detection
window, so `git diff` printed *"Binary files … differ"* for a TypeScript module.
`.gitignore` gained `/.mlview.toml`, which MLView writes into its own checkout on
every e2e pass.

Six documents were corrected because the matrix finally ran: `README.md`,
`docs/STATUS.md`, `CONTRIBUTING.md`, `docs/VALIDATION.md`, the pull-request
template and this file all said, in their own words, that the CI matrix had never
run on this line of work. That was true when written and false once thirteen jobs
came back green, and the doc gate could not catch it because *"the matrix has not
run"* was the one escape check 22 implemented — so the check now also accepts a
cited `run <id>`, and the documents cite one. `docs/ACCURACY.md` §1 still opened
on the 92-program corpus; it holds 158.

**Gates, local first and then on CI.** Every figure here was measured on this
Mac (macOS 26.6, Python 3.13, Node 26) while Actions billing was blocked at the
account level; the matrix confirmed the tree afterwards, on the `public` → `main`
pull request — thirteen green jobs over Ubuntu, Windows and macOS, Python 3.10
through 3.13 and Node 20/22 (run 34986234828 and run 34986239243), both green on
their first attempt; the one fix iteration belongs to the branch's first
pull-request run, 34974162339, whose four failures were all one test-side
assumption about Windows drive letters. `sh scripts/e2e.sh` 20 steps, all green;
`python tools/verify.py --all` 10 rows; `python tools/verify.py --scopes --fuzz
200` 5 rows; `python tools/accuracy.py` and `--dataflow local` over the
158-program corpus, both PASS; `python tools/public_corpus.py run` then
`check --strict` over the 37 pinned repositories — 260 runs, 260 clean,
49 high / 276 medium / 381 low, **no new high-severity finding**; `mlview analyze --demo` byte-identical to
`contracts/graph.sample.json` at 45 588 bytes; `python scripts/check_docs.py`
**DOC CHECK OK**. Suites: analyzer 2654 passed / 9 skipped / 24 xfail, webview
599 (598 pass, 1 todo), vscode-extension 415, claude-plugin 479 passed / 7
skipped, scripts 146. Every row was run once at the rebuild and again after
the review fixes below; the figures are the second run.

### Public review round — the documented setup, the gate table, the CI claims

The first review of the tree as a stranger meets it: a clone built by following
`CONTRIBUTING.md` line by line, and every CI and accuracy claim re-measured.

**The documented setup did not run the gates it promised.** `analyzer` declares
`dependencies = []` and puts pytest and jsonschema behind a `dev` extra, so a
venv built exactly as §1 said — `pip install -e analyzer` — had no pytest, no
jsonschema, no `mcp` SDK and no `build`, and `sh scripts/e2e.sh`, the next
command on the page, answered `20 steps · 3 failed` on a correct tree. CI never
hit it because the e2e jobs install those packages by name. Every setup block in
`README.md`, `CONTRIBUTING.md`, `docs/STATUS.md` and `docs/VALIDATION.md` now
reads `pip install -e "analyzer[dev]" mcp build`, with the reason next to it, and
each names `python3 --version` first because macOS's `/usr/bin/python3` is 3.9
and the package refuses it.

**Two gate rows lied in opposite directions.** `tools/verify.py --all` turned a
missing optional SDK into `FAIL parity: CLI vs MCP — No module named 'anyio'`
and exit 1 — the one red row a newcomer saw was the one that meant nothing — so
a gate that cannot run now reports **SKIP** with the one-line fix and does not
set the exit status. `vendor: synced core` was built only on that gate's success
path, so any parity failure served **nine** rows where four documents promise
ten, with the row `CONTRIBUTING.md` sends plugin contributors to read simply
absent; it is computed first now and printed on every path. In the other
direction, `tools/wheel_check.py` exited 0 when there was no wheel to test and
both e2e drivers recorded `PASS wheel installs and runs` over a check that had
done nothing — in every e2e job this project has ever run, including the green
ones the README cites, because neither e2e job installed `build`. The tool exits
**3** for that case, both drivers record `SKIP` with the reason, both e2e CI jobs
install `build`, and `scripts/build.{sh,ps1}` says `BUILD OK — 5 of 6 steps
(wheel skipped)` rather than claiming six.

**The docs contradicted each other about CI and about accuracy.**
`docs/STATUS.md` still said, in the present tense, that Actions was
billing-blocked and that *"no claim of a green CI run is made anywhere in this
repository"* — eighty lines above its own paragraph naming thirteen green jobs,
and while four other documents named the runs. `docs/README.md`, the index every
document link goes through, ended its description of the doc gate with *"which,
on this line of work, it has not run at all"*. `docs/VALIDATION.md` told the next
validator both scheduled workflows had never run and that billing was blocked;
both are on `main` and each has been proved by dispatch (nightly run
34984606964, public corpus run 34982508080 at 260 runs, 260 clean). §16.4 of the
contract still carried *"not yet by measurement"* as live normative text. And
`docs/STATUS.md` said the public corpus had caught **four** false positives where
`adjudication.json` holds eleven and `README.md` says eleven — a factor of nearly
three on the number that is the whole argument for that gate.

**Both halves are now gated, because prose that drifts once drifts again.** The
doc gate is **twenty-five checks**. Check 22 gained its mirror: once a living
document names a run that was green, no living document may assert the matrix has
not run. Check **24** holds any prose count of the public corpus's false
positives to `analyzer/tests/public_corpus/adjudication.json`, reading
spelled-out numbers and the shape that states the figure without repeating the
noun. Check **25** holds the versions in `THIRD_PARTY_NOTICES.md` — until now the
one public-facing file no check read at all — to the packages under
`webview/node_modules`, abstaining where they are not installed. Both new checks
carry the meta-escape check 22 needed: a paragraph that documents the rule is not
a claim about the tree.

Smaller: the Python badge said 3.11+ against a `requires-python = ">=3.10"` that
CI exercises on 3.10; the hero screenshot's alt text described eight stage bands
where seven are drawn and the eighth is the one the sample does not have (which
is a feature of the viewer, so it says so now); the README credited a fix
iteration to two runs that were green first time; `docs/ROADMAP.md`, linked as
the backlog a contributor picks work from, sized that work in agent-days;
`project.md` was indexed nowhere and is now in `docs/README.md` as what it is;
`SECURITY.md`'s preferred route was GitHub private vulnerability reporting, which
is **disabled on the repository**, so step 1 is conditional on the button being
there until the setting is turned on; and `docs/STATUS.md` records, as a standing
gap, that the git history still carries the old orchestration scripts with their
absolute paths — a decision taken rather than an oversight, since rewriting
history on a public repository breaks every clone.

**Gates after this round**, on this Mac: `python scripts/check_docs.py`
**DOC CHECK OK (21 files)**; `python -m pytest scripts -q` **146 passed**;
`python tools/verify.py --all` **10 of 10**; `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; `python tools/accuracy.py` PASS in both dataflow modes;
`python tools/public_corpus.py check --strict` gate OK over the 37 pinned
repositories. **And on CI**: the thirteen jobs took this round's commit green on
the first attempt too — run 35001150997 for the seven cheap-tier jobs, run
35001153856 for the six the cheap tier excludes. Those two are the first runs in
this project's history where `wheel installs and runs` was a real check on both
drivers (`wheel-check: OK mlview-0.1.0-py3-none-any.whl -> mlview 0.1.0, 4
node(s), 2 issue(s) in a clean venv`, Ubuntu and Windows alike) rather than a
PASS printed over a step that did nothing.

---

## Hardening rounds 1 and 2 (2026-09-14)

Not a sprint. The brief both times was *"test the current implementation
extensively and carefully; besides fixing bugs, focus on coverage over all
possible ML/DL code — test against public repos, construct code that mimics real
ML/DL applications"*, and the product's standing rule decided what counted as a
failure: **a high-severity false positive on correct code is the worst outcome,
and silently misrepresenting code — a stage claimed absent, a call dropped, a
crash swallowed — is the second worst.** Both happened, repeatedly.
**104 findings fixed** across the two rounds, and fourteen contract amendments,
§11.50–§11.61.

**What the two rounds built, and left behind as gates:**

| Surface | Round 1 | Round 2 |
|---|---|---|
| Public repositories | **24 pinned repos** at exact SHAs, 90 targets × 2 dataflow modes = 180 runs; `tools/public_corpus.py` (`fetch` / `run` / `check`) and `analyzer/tests/public_corpus/` | **37 pinned repos** — the round-1 set plus thirteen, none removed — 112 targets × 3 modes (`local`, `ip`, `--include-notebooks`) = **260 runs** |
| Written ML/DL code | **77 new labelled programs, 188 source files**; the corpus goes 15 → **92** programs, 78 → **312** expected labels, 125 → **1229** forbidden labels | **66 more**; 92 → **158** programs, 312 → **545** expected, 1229 → **2327** forbidden, 614 → **1166** hand-drawn graph ops |
| Robustness | a deep-but-legal AST, a FIFO named `*.py`, a symlink to `/dev/zero`, an unreadable directory, `from x import *`, duplicate `Issue.id`s | binding shapes (tuple parameters, dict literals, `functools.partial`, factory returns), notebook magics, package walking, report escaping — `test_round2_analyzer.py` + `test_round2_core.py`, 64 cases |
| Hosts and the renderer | 16 real repositories rendered in all three hosts; every MCP argument driven out of range | the **built** viewer mounted in jsdom over 260 public-corpus documents and 158 corpus documents; every accepted `framework=` value against the rule registry (26 cases) |
| The tree itself | which selectors are advertised, which directories a tool writes into, which test files `npm test` runs — doc-gate checks 16–18 | the command lines CI generates, the exclusive rule lists a document asserts, a known gap that names its own retirement condition — checks 19–21 |

**The worst class was the largest, both times.** Round 1 opened with **five
forbidden findings** — high-severity claims about correct code that the labelled
corpus explicitly forbids — and precision **97.6%**; round 2 opened with
**eight** and **97.9%**. It closes at zero forbidden, zero unlabelled and
**100% precision in both dataflow modes**.

**Two findings were made by the integration itself, and they are why the
public-corpus gate exists.** With every round-1 fix in the tree,
`public_corpus.py check` refused the build on two NEW high findings, neither
reachable from 312 labels: **PUB-15**, MLV101 reporting a `certain` leak in a
scikit-learn example because the rebinding guard read assignment targets through
`dotted_text`, which is empty for an `ast.Tuple` — so `X, y = load_iris(...)`,
the way scikit-learn binds data, was invisible to it; and **PUB-14**, MLV102
calling a `KNeighborsClassifier` "the transformer" on a notebook cell that is
*teaching* two-fold cross-validation. Both cost nothing: every accuracy figure
identical to four decimal places in both modes.

**Round 2's own integration arrived with a red test file**, which is an honest
hand-off and a blocking one. The four it named: a `pointerdown` on the legend
started a canvas pan and took pointer capture, so the panel's close button worked
from the keyboard and not from the mouse; an unwrapped workspace-relative path
painted one answer over the answer beside it on 7 of 90 real reports; the scope
picker's unit and group rows promised the match set while the click delivered the
projection (`unit:train.train` offered 4 nodes and drew 9), fixed by running the
same `project()` the click runs — 819 ms → 101 ms on a 222-row picker over a
400-node repository; and the Issues rail saying *"No issues found — nothing to
flag"* over a run whose own banners said it had been blind. Measured over the 260
pinned documents: **122 draw the clean state, and 118 of them were drawing it
over a blind run.**

**Recall fell, then rose, and both readings are the honest ones.** Round 1 had to
report a fall — 73.1% → **72.4%** raw — because 77 of its 92 programs were new,
unseen and harder than the fifteen the rules were developed against; scored over
those original fifteen alone the same build reads **75.6%** and the whole
previous gate passes. Round 2's 66 new programs are just as unseen and every
aggregate rose anyway: `local` **72.4% → 77.8%**, visible 66.7% → 70.1%,
high+medium 64.5% → 70.7%, unseen 69.4% → **76.5%**; `ip` 76.3% → **79.1%** with
unseen 73.7% → 77.8%. Both baselines were re-recorded with `--allow-regression`
and the reason written into each file's own `note`, never by deleting a label.
No rule carries a tuned `*` any more: all 36 have at least one label in a program
nobody wrote for them.

**Round 2's closing gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; analyzer **2574 passed / 9 skipped** (2405 / 7 at round 1's
close, 2087 / 4 at the Sprint-5 close); webview **585 tests** (561, 534);
vscode-extension **404** (401, 377); claude-plugin **460 passed / 7 skipped**
(434, 373); `pytest scripts` **119 passed** (99, 74); `npx tsc --noEmit` clean in
both TypeScript packages; `tools/verify.py --all` **10 of 10**;
`tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py` **PASS** —
precision **100.0%** on 36 rules over **158 programs and 545 labels**, recall
**77.8%**, unseen **76.5%**, graph fidelity **84.5%** (985 of 1166), zero
forbidden and zero unlabelled; `--dataflow ip` **PASS** at **79.1%** / unseen
**77.8%**; `public_corpus.py fetch && run && check --strict` **gate OK** — **260
runs, 260 clean**, 36 s of wall at `--jobs 8`, slowest single run 17.9 s against
a 60 s budget, 50 high / 276 medium / 376 low, zero tracebacks, zero schema
errors. CI run 34815166539 (round 2's last push before the billing block): all 12
branch jobs green, 15m39s wall, ~87 billable minutes.

**What the two rounds did not close**, named rather than averaged away: a model,
criterion and optimizer arriving as parameters still cost a training step its
forward, loss and backward nodes; `--dataflow ip` still reports a strict subset
of `local` on one mlflow example, so `local ⊆ ip` is not yet true; Escape still
did not close the legend, because `dismissTopmost` runs the cascade §11.13
freezes; and twenty-two points of recall were still missing, largest first —
MLV208's `GradScaler` through a parameter dict, MLV305 needing a prediction to
carry `LOGITS` or `PROBS`, and a model built by a registry
(`build_from_cfg("model", cfg)`) still being untyped. The campaign above is the
answer to that list.

---

## Sprint 5 — the LATER tier of the roadmap (2026-09-10)

Interprocedural dataflow, structured fixes, one configuration surface, analysis
comparison, node-budget rollup, pipelines, cross-lane bundling, and the process
work around them. `docs/CONTRACTS.md` §11.35–§11.47 are the amendments.
`schemaVersion` stayed `"1.0"`, `contracts/graph.sample.json` never moved, and
`python -m mlview analyze --demo --json -` stayed byte-identical to it at
46 078 bytes through every wave.

**Analyzer and viewer**

- **DATAFLOW-IP** (§11.36) — `analyzer/src/mlview/ir/summaries.py` adds a
  fixed-point interprocedural pass (constructor, return, method-argument
  intersection and subscript projection summaries) behind `--dataflow {local,ip}`
  with `local` the shipped default. `local` is byte-identical *by construction*:
  every new path is reached only from `workspace.dataflow == "ip"` or from a
  non-empty `ValueRef.provenance`. Confidence is arithmetic, not a promise —
  `rules/confidence.py` weights one `cross_file` evidence `0.8 ** hops`, so
  MLV101's 0.95 prior reads 0.760 at one hop and 0.486 at three. Measured:
  recall 71.8% → **78.2%** overall and 53.2% → **63.8%** unseen, precision 100%
  in both modes, zero forbidden findings.
- **PERF-03 / CACHE become the default** (§11.39) — `DEFAULT_RELEVANCE` is
  `"ml"`, which turns the fact cache on with it. `tools/perf_equiv.py
  --expect-same` re-proved byte-identity on all three corpora. On a 501-file
  mixed corpus: 2 920 ms (`--relevance all`) → 1 237 ms cold → **547 ms warm**,
  same 148 findings. The honest cost: a default run now writes
  `<root>/.mlview/cache/`.
- **CFG-ONE** (§11.37, §11.45) — `core/config.py` is the only parser:
  `--config FILE`, else `<root>/.mlview.toml`, else `[tool.mlview]` in
  `pyproject.toml`; first match wins outright and is named in
  `workspace.configPath`. TOML wins for `disable`/`exclude`, flags win for
  `[analysis]` and `min_confidence`, every mistake is one `config_warning`.
  `mlview init` writes a commented file listing all 36 rules from the registry.
- **ANA-10** — in-Python config resolution: module-level dict literals,
  dataclass field defaults, `argparse` defaults and the chains rooted at them
  resolve to literals. Measured A/B: overall recall **71.8% → 73.1%**, unseen
  **53.2% → 55.3%**, graph fidelity 126 → **127 of 139**; in `ip`,
  78.2% → **79.5%** and unseen 63.8% → **66.0%**.
- **H5, structured fixes** (§11.42) — `analyzer/src/mlview/rules/fixes.py` is the
  only module that constructs a `TextEdit`; 31 of 36 rules are byte-identical.
  Rules opt in, every position comes from an `ast` node, nothing below the
  `likely` bucket is offered an edit, and nothing in the analyzer writes to a
  file. Finding-neutral by construction: `tools/accuracy.py` identical to the
  character with and without the field.
- **VIEW-08, `mlview diff`** (§11.38) — a separate `mlview-diff` overlay keyed on
  the §0 stable ids: per-node/edge `added|removed|changed|unchanged`, per-issue
  `new|fixed|persisting`, and a `notes[]` block naming every reason a `removed`
  might not mean "deleted". A move is not a change. Over the sample pair:
  **+26 / −16 nodes, 11 changed, 27 unchanged, 0 new findings, 15 fixed**.
- **PERF-04, rollup** (§11.46) — `core/rollup.py` makes `--max-nodes` a zoom
  level instead of a guillotine: a unit absorbs its ops, a file folds, then a
  directory, and only then the old deletion order. `samples/vision_pipeline` at
  `--max-nodes` 400 / 40 / 20 / 8 gives **54/51, 38/40, 12/18 and 7/4**
  nodes/edges with **15 issues (5 high / 6 medium / 4 low) in all four**.
- **MLV-P12, pipelines** (§11.47) — the root `pipelines[]` block plus a
  `pipeline:<entrypoint>` selector. A single-entrypoint workspace is
  byte-identical to before.
- **VIEW-04, cross-lane bundling** — `layout/channel.ts` plans one trunk per lane
  pair and nests rather than braids; `layout/bundles.ts` draws the common run
  once with a member count. Crossings per edge **3.82 → 1.96** on the 54-node
  demo and **44.55 → 30.47** on a 300-node synthetic. A bundled cable's severity
  marker is never faded.
- **HEALTH-02 grows** — `analyzer/tools/scope_gen_projections.py` generates
  rolled-up and multi-pipeline documents. It found two real divergences within an
  hour, including `exclusiveCount` disagreeing on 17 of 40 graphs; §11.47 D is
  the normative reading, and two counterexamples were promoted into
  `contracts/scope.cases.json` (three → five).

**Hosts**

- H10 multi-root: one graph per open folder (`vscode-extension/src/folders.ts`),
  the Problems panel publishing the union, `MLView: Select Active Folder`.
- The three language-model tools take the whole selector grammar, described in
  the MCP docstring's own words and asserted against it.
- H5's fix preview, VIEW-08's three comparison commands
  (`vscode-extension/src/compare.ts`), and `mlview_graph {scope: "diff"}` — a
  sixth *value*, not a sixth tool. Still exactly five MCP tools.
- H8: `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/` that speak only
  when the issue set grew, at most 5 rows, under a 3-second budget.

**Process**

- CI-MACOS-01: `smoke (macos)` was red on a wall-clock *ratio* assertion that
  read 1.15x–2.50x across runs of the same commit. The delta test now asserts
  what the cache controls, as counts — `("none", 0, 501)`, `("partial", 500, 1)`,
  `("full", 501, 0)` — with wall clock held to a ceiling.
- PROC-12: `webview/test/export_svg.mjs` became the e2e table's 20th step;
  `scripts/doc_numbers.py` check 11 holds every "N steps" claim to what the two
  drivers print.
- §11.35 is an erratum, not an edit: §11.19's "54 nodes and 52 edges" predates
  REV-06 dropping the one backwards data edge. §11 is append-only.
- Review round: three new doc-gate checks in `scripts/doc_figures.py` — the
  `docs/STATUS.md` Components table against that file's own newest `**Gates`
  paragraph, any scope-battery size claim against `contracts/scope.cases.json`,
  and two documents naming different runs as "the last full green push".

**Review fixes (19 findings).** Five were high-severity false positives — MLV101
matching a split by *name* across two functions, MLV121 taking the *absent*
branch for a `reshuffle_each_iteration` it could not read, and three more — each
fixed at its source with no assertion weakened. Three defects were reachable only
from CI: a stray `.mlview` sidecar copied into both vendored cores (now skipped
by `tools/sync-core.py`), two `analyzer (py3.10)` tests asserting behaviour the
CFG-ONE fix removed, and a plugin test that was a race rather than a test.

**Sprint 5 final gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **2087 passed / 4 skipped** (1722 / 3 at the sprint
baseline); webview **534**; vscode-extension **377**; claude-plugin **373 passed
/ 7 skipped**; `pytest scripts` **74 passed**; `tools/verify.py --all` **10 of
10**; `tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py`
**PASS** — precision **100.0%** on 36 rules, recall **73.1%**, unseen **55.3%**,
graph fidelity **91.4%** (127 of 139), zero forbidden findings — and
`--dataflow ip` **PASS** at **79.5%** / unseen **66.0%**;
`contracts/validate_sample.py` green at four budgets;
`analyzer/tools/gen_gallery.py` renders **90 reports plus an index**;
`scripts/check_docs.py` **DOC CHECK OK**. CI run 34454599867: **all 12 branch
jobs green**, 7m57s wall, ~44 billable minutes.

---

## Sprint 4 — the NEXT tier of the roadmap (2026-09-09)

Adoption, the answer card, framework recognition, three rule tiers, export,
packaging and notebooks. `docs/CONTRACTS.md` §11.21–§11.34 are the amendments.

- **Sixteen new rules** (ANA-7 / ANA-8 / ANA-9, §11.26) take the registry from
  **20 to 36**: framework misconfiguration (MLV705–MLV711), training mechanics
  (MLV207, MLV208, MLV209, MLV502, MLV803) and held-out integrity (MLV106,
  MLV114, MLV121, MLV305, MLV306). The labelled corpus grew 10 → 14 programs and
  77 labels; precision stayed **100% on all 36 rules**, overall recall
  62.9% → **71.4%**, unseen 51.1% → **53.2%**. `samples/vision_pipeline` kept
  exactly its fifteen findings, so no golden was regenerated.
- **FW-RECOG** (§11.23) — four framework knowledge tables (`knowledge/tf_tbl.py`,
  `hf_tbl.py`, `gbm_tbl.py`, `hooks_tbl.py`) and Lightning hook units in
  `core/hooks.py`. Graph fidelity **86.3% → 90.6%** (120 → 126 of 139).
- **ANA-5a** (§11.23) — a call the analyzer cannot resolve is never silently
  dropped: `CallSite.unresolved_callee` mints an `unknown` op and one diagnostic
  per scope, and no emitter may claim a stage is absent without the qualification
  *"(unverified: N calls could not be resolved…)"*.
- **CI-ADOPT** — the `mlview.adopt` package stamps each finding `new` /
  `touched` / `existing` from `git diff`, `mlview baseline write` plus
  `--baseline FILE`, `--sarif FILE` (SARIF 2.1.0 against the OASIS schema),
  `tools/action/action.yml` and `.pre-commit-hooks.yaml`. Every attribution
  failure degrades to "showing everything" with a diagnostic.
- **MLV-P1** — the deterministic Pipeline Answer Card (`emit/answers.py`), first
  block of `--format summary`, four sentences in `api.digest`, a card in every
  host.
- **VIEW-07** (§11.24, §11.33) — SVG/PNG export. The mitigation landed first:
  `webview/src/render/plan.ts` returns one scene plan that both
  `render/scene.ts` and `export/svg.ts` consume, so the gate can assert one
  `<path data-edge-id>` per routed edge with byte-identical `d`. The SVG
  references nothing outside itself.
- **NB** (§11.29) — `.ipynb` ingest behind `--include-notebooks`. One notebook
  becomes one generated module under `.mlview/notebooks/`, 1:1 line counts inside
  every cell, the cell map on `Node.attrs`, and a non-monotonic `execution_count`
  de-rates MLV101 / MLV203 / MLV209 by 0.75 and says so. The VS Code host
  re-anchors squiggles onto `vscode-notebook-cell:` URIs.
- **PACKAGING** — `tools/sync-core.py` vendors the analyzer into the VSIX as well
  as the plugin, `tools/verify.py` grew a tenth row, `scripts/vsix_check.py`
  re-derives the ceiling and the bundled-core count from the tree, and
  `tools/wheel_check.py` builds the wheel and runs it from a throwaway venv.
- **PERF-03 + CACHE** (§11.28) — the relevance prefilter and the content-keyed
  fact cache, both opt-in at this point. On a 500-file synthetic
  `build_workspace` dropped **1 087 ms → 76 ms** and the whole analysis
  **2 228 ms → 693 ms**, reporting the same 51 findings; a warm run 319 ms.
  Pickling the AST or the IR was measured and **rejected** — both slower than
  recomputing.
- **HEALTH-02** — the differential fuzzer over the two `project()` ports found a
  real divergence on its first 200 cases; §11.30 made the Python behaviour
  normative and three counterexamples were frozen into the battery.
- **Process** — PROC-01 put a `**Landed` measurement note on every shipped
  roadmap item and `scripts/check_docs.py` check 12 keeps it that way; HOST-8
  moved the VSIX figures out of two documents and into `scripts/vsix_check.py`;
  PROC-10 replaced an estimated CI bill with a measured one and stated the
  rounding rule; PROC-12 wrote down that pushes go over SSH because the stored
  PAT has no `workflow` scope.
- **Review fixes (23 findings).** Two rules were judging the wrong thing (MLV709
  paired a loss with any same-file activation; MLV121 fired on
  `train_ds.take(1)`), and a whole binding style was unanalyzed —
  `ds = ds.map(...)` resolved its right-hand side against the store the same
  statement was about to write, so three semantically identical `tf.data`
  pipelines measured 7/5, 7/5 and **2 nodes / 0 edges with `diagnostics: []`**.
  All three now measure 7/5, gated per style.

**Sprint 4 final gates.** `sh scripts/e2e.sh` **19 steps, 0 failed**; analyzer
**1748 passed / 3 skipped**; webview **404**; vscode-extension **308**;
claude-plugin **324 passed / 7 skipped**; `tools/verify.py --all` **10/10**;
`tools/accuracy.py` precision **100.0%**, recall **71.8%**, unseen 53.2%, graph
fidelity **90.6%**, zero forbidden findings; VSIX **128 files, 604.57 KB**.
CI run 34320075813: 12 jobs green, 6m30s wall, ~38 billable minutes.

---

## Sprint 3 — the NOW tier of the roadmap (2026-09-08)

**The re-baseline (§11.19).** Four items landed as one graph change, because one
golden regeneration has to cover all of them.

- **ANA-1** — ops written inside a class method were dropped: `CallSite.class_ir`
  carried two different facts and `core/build.py` read the wrong one. They are
  now `class_ir` (what the call resolves to) and `enclosing_class` (what class it
  is written in).
- **ANA-2** — `self.<attr>(...)` resolved to a symbol nobody declared; it now
  resolves through the binding.
- **ANA-3** — a package `__init__` re-export resolved to nothing.
- **VIEW-01** — lane boxes are no longer normalised to the widest lane. On the
  demo the world went 2636×2484 → 1576×2630 and `fit()` **0.322 → 0.532**; worst
  lane emptiness **91% → 32%**.

`samples/vision_pipeline` grew from 45 nodes / 45 edges to 54 nodes (52 edges at
the time; 51 since REV-01 dropped one backwards data edge) carrying **exactly the
same fifteen findings** at the same lines, so `expected_issues.json` was
unchanged. Precision stayed **100%** and every recall reading was unchanged to
four decimals; graph fidelity ratcheted **66.2% → 86.3%** (92 → 120 of 139).

Also in Sprint 3: PERF-01/PERF-02 (memoised knowledge lookup, a role index and a
convergence loop, byte-identical on three corpora), **ANA-12** — the labelled
accuracy corpus, `tools/accuracy.py` and `docs/ACCURACY.md` — BUILD-01 (−38% on
the report CSS), CI-01 (`.github/workflows/ci.yml`), COVERAGE (the
`single_file_analysis` / `untagged_dataflow` diagnostics and
`mlview.currentFileAnalysisScope`), RAIL-GROUP (`mlview_issues` `groupBy`) and
CLEANUP (`mlview.showSpeculative` and `mlview.followCursor` deleted).

**The pre-sprint audit, for the record.** Five auditors measured the shipped
prototype on 2026-09-08: **0 false positives on unseen code but roughly 26%
recall**, because class-method ops were dropped; the first screen opened a real
repo at 20% zoom; and the tool could not say "I could not check this". Those
three headlines are what Sprint 3 moved, and `docs/ROADMAP.md` (42 ranked items,
11 declined) is what came out of it.

---

## Feature pass and review rounds (2026-09-07)

**Two features on top of the first prototype**, both additive —
`schemaVersion` stayed `"1.0"` and an unscoped run emitted the bytes it emitted
before (§11.13 and the `docs/FEATURES_FLOW_AND_SCOPE.md` design).

- **Flow visibility.** Hovering a connection runs a charge along it from outlet
  to inlet; hovering a node streams its lineage, staggered 90 ms per hop.
  Direction is never decided — every router emits `points` source → target.
  `prefers-reduced-motion`, or more than `FLOW_MAX_EDGES = 120` lit edges, flips
  the canvas to a static chevron plus outlet and inlet dots.
- **Scoped views.** One selector string — `unit:` / `stage:` / `file:` /
  `concern:` / `node:` / `all`, with `depth` 0–2 — projects the whole-workspace
  document in every surface: `--scope` on the CLI, `data-mlview-scope` on the
  report, `Alt+Shift+M` in VS Code, `scope`/`depth` on the MCP tools. A scope is
  a **view, not a filter**: `stage.present`, `workspace` and `diagnostics` still
  describe the full analysis and the VS Code Problems panel is byte-identical
  while scoped. One algorithm, two languages
  (`analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`),
  gated against each other by `contracts/scope.cases.json`.

**Integration and review fixes.** Three components that hid themselves never
actually hid (an author `display` outranks `[hidden]`); the drawn hierarchy and
the lexical hierarchy had diverged in `webview/src/layout/model.ts`, so
collapsing one group erased six nodes from another lane and the demo drew 19 of
its 46 cards; `scripts/e2e.sh` had been rewritten LF → CRLF, which is unrunnable
under dash (MLV-R2-H02); and two documents disagreed about the size of the demo
graph (MLV-R2-H05). The doc gate `scripts/check_docs.py` was created in this
pass and grew to eight checks by the end of it, each one the regression gate for
a specific incident.

---

## First build (2026-09-07)

The multi-agent build of the prototype: analyzer, viewer, VS Code extension and
Claude Code plugin, finished with two review → verify → fix rounds (48 confirmed
findings fixed) and a final verification pass. Twenty rules, the frozen
`contracts/graph.schema.json` and `contracts/graph.sample.json`, the
self-contained HTML report, the five MCP tools, and `scripts/build` +
`scripts/e2e` as the two drivers.
