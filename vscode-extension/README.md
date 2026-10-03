# MLView for VS Code

MLView opens interactive, source-linked workflow diagrams created by the MLView
skill in Copilot, Codex, or Claude Code.

Invoke the skill in your assistant to analyze the repository and publish a
`*.mlview.json` WorkflowDocument. Then run **MLView: Open Generated Diagram** or
open the command from the artifact editor title.

The viewer validates the document and its source evidence against the saved
files on disk before displaying it. An open panel follows the artifact file: it
shows each newer valid revision the assistant publishes, keeps the last valid
revision on screen when the file is invalid, unreadable, or missing, and
explains why in a status line. A revision the panel has already seen replaced
(for example one restored from version control) is not shown again until you
re-run **MLView: Open Generated Diagram**, which always shows the file as it is.

When cited or inspected files change after a revision was published, the
diagram stays visible as a historical revision and the status line names the
changed or missing files. The steps, connections, findings and quotes that
cite them carry a warning mark, the status bar counts them, and only jumps
into those files are blocked. Unsaved editor changes never change validation.
They are reported separately, and a jump is blocked only when the unsaved text
no longer contains the cited lines.

If the workspace root is a parent of the folder the diagram cites from (most
tracked files are missing from the root but exist, with the published hashes,
under the artifact's folder or a folder above it), the notice names the files
and the folder that holds them, unchanged, and offers **Add folder to
workspace** or **Open folder**. The marks, the status bar, the Selection tab and a
blocked jump say "in another folder" instead of calling the files changed or
missing. The panel checks again whenever workspace folders change. The two
actions are only in the panel's notice; there is no separate notification.

When VS Code restarts its extensions inside the same window, MLView puts each
open diagram back in its tab's place, checked against the workspace as it is
then. That covers **Developer: Restart Extension Host**, an extension install
or update that restarts extensions, **Save Workspace As...**, and adding a
folder to a single-folder window (the notice's **Add folder to workspace** or
VS Code's **Add Folder to Workspace...**), which turns the window into an
untitled multi-root workspace. A diagram in front of its editor group comes
back at once. A diagram tab behind other tabs comes back when you bring it to
the front, after a blank half second: until then MLView cannot tell it from a
tab VS Code restored at startup and has not shown yet, which must be left
alone. A diagram put back this way starts with a fresh view: the selection
and zoom start over. **Developer: Reload Window** restores diagrams as before,
with their selection and zoom.

The rail beside the diagram has four tabs: **About**, **Findings (n)**,
**Selection** and **Outline**. A new revision opens on About (the question,
what the model traced, coverage with its limitations listed once, scope, run
configuration, the cited files with their freshness, and provenance); after
that the tab you choose is kept for that revision. A click on a step or
connection, or a search result, selects it and shows its claim in Selection
(a row chosen in Findings or the Outline keeps that list in place): the phase, title and full detail, a
note only for an inferred or unresolved claim, the findings on it with **What
to change**, its numbered quotes with line numbers, freshness and **Open**,
and what it comes from and feeds. Selecting a finding frames every step it
cites. Below about 1260 px wide the rail is a bottom sheet under the diagram:
a 32 px tab strip until a selection opens it to about half the height, with
the selected card kept in view; drag its handle to resize it, and use the
chevron or Escape to collapse it. `t` moves the focus to the rail's tabs and
the arrow keys choose one; `b` shows or hides the rail. A resize or a rail
change that hides the selected card pans just enough to show it again, and a
panel shown again after being hidden keeps its selection and an open sheet.
Notebook cells are numbered from 0, as the artifact records them.
`r` (or **Review** in the header, or **Review the claims** in the **⋯** menu)
starts the review walk: claim by claim in the diagram's order (each step, its
outgoing connections, then the findings whose first cited step it is;
findings citing no step last), starting on the claims not observed, with
**Findings**, **All claims** and, after a cited file changed, **Changed
files** as the other filters. `j` / `k` or ↓ / ↑ (or the walk bar's up and
down buttons) move, `[` / `]` change quote, Enter opens
again, `u` / Shift+U and `n` / `p` go through the claims not observed and the
findings, and Escape or `r` ends it. About 150 ms after each step the claim's
cited lines open beside the diagram, highlighted, with the keyboard kept on
the diagram (also when the walk was started from **Review** or the **⋯**
menu); a quote whose file changed or is missing, or whose unsaved edits no
longer contain the cited lines, is not opened, and the walk bar (under the
diagram) and the Selection tab say why, with no notification; once VS Code
reports the file unchanged again, they say Enter shows it. When the walk
ends, moves to a claim it opens nothing for, or does not open a quote, the
highlight goes and the lines it selected are no longer selected (unless you
changed the selection). Each claim
starts at the top of the Selection tab, and the walk brings its quote's file
line and what the editor shows into view, with the title when both fit. A
walk step or a keyboard move hides the hover card until the pointer moves. The walk
remembers its place per revision in the panel's view state and records
nothing else; the changed-files notice offers **Review affected claims**,
which starts at the first affected claim.
Shift+0 (or **Phase overview** in the **⋯** menu) shows every phase as a block
of its step titles, with ◌ for inferred, ? for unresolved and the F labels of
findings. Arrows count the connections to the next phase, and brackets count
those that skip ahead or go back. A block that does not fit ends with "… N
more steps". The arrow keys move between blocks, Enter or a click goes to that
phase at reading size, and Escape returns to where you were (a legend opened
over it closes first). A key under the overview's header explains ◌, ? and
the brackets at every width; the header, with **Back**, stays at the top
while the overview scrolls. The phase index
in the diagram's lower right corner lists each phase with its findings and
step count and marks the phases in view; a row goes to its phase. Below 1000
px wide it is one line such as "4/6 Objective, optimizer & scheduler" that
opens the list. It never covers the card you are on.
**Reveal in Diagram** goes from the code back to the diagram. Right-click a
line in the editor and choose it, or run **MLView: Reveal in Diagram** from
the Command Palette; there is no default keybinding, so bind one in Keyboard
Shortcuts if you want one. It is offered on a file an open diagram cites that
has not changed or gone missing since the revision was published, on the first
right-click, even straight after you pressed Enter in the diagram. The `when`
clause is `resourcePath in mlview.citedFiles`: the extension keeps that list
of the open diagrams' cited, unchanged files, so VS Code decides for the
editor under the pointer without waiting for the extension. If unsaved edits
moved the quoted lines, or a notebook cited by cell is open as text, the
command says so in one line. A file opened through another path (a symlinked
folder) is matched when the command runs, but the menu matches the path only. The
cursor's line or the selected lines decide the claim: one claim is shown at
once; several are listed as steps, then connections, then findings (with the
F label, severity, phase, a basis other than observed, and where each is
cited, counter-evidence marked); a line no claim cites lists the nearest
claims in the file, with how far each is. The diagram selects the claim,
unfolds its group, brings it into view (a connection with its ends, a finding
with its steps), shows it in the Selection tab, opening a hidden side panel or
a collapsed bottom panel, and moves the keyboard to the diagram. That is the
one time the viewer moves the focus by itself. A diagram hidden behind the
code comes to the front and shows the claim once VS Code has reloaded its
page. With several diagrams open, the one citing the file is used, or a list
asks which. In a notebook it works in the cell editors, by the cell numbers
the artifact records; a notebook cited by cell and opened as text gets a
message saying to use the notebook editor. Run where it does not apply (from
a keybinding of your own, or after the file changed), it says why in one
line. Each panel keeps an index of its revision's evidence
(files, lines, and the claims citing them), rebuilt on a new revision and
dropped with the panel; it reads no code, and adds no hover, CodeLens or
Problems entries.
Enter, a double-click (on a step, connection, finding or Outline step) or a
quote's **Open** link opens the cited range beside the diagram: the whole range is selected and highlighted, and focus
stays in the diagram. The source goes to an editor group you already have
(the one showing the file, else the last jump's, else the one you last used),
never the diagram's own; a new group opens beside only a diagram alone in the
window. Alt+Enter (or Alt+click on an Open link) also moves
focus to the editor. For a notebook citation the cell is selected and
revealed; its lines are highlighted when VS Code has the cell's editor ready.
In High Contrast themes the highlighted lines are outlined with the theme's
range-highlight border, since those themes define no highlight background.
The highlight also marks the editor's overview ruler. MLView checks a cited
file once per revision and freshness check: later jumps into it read it again
only after it changes on disk, so stepping through the cells of a large
notebook does not re-read the whole notebook each time.
Only inferred (dashed, `inferred` tag) and unresolved (dotted, `? unresolved`
tag) steps and connections are marked; observed ones carry no mark, and the
header's **N not observed** toggle fades them. Line style shows certainty,
not connection kind; the hover card and the Selection tab name the kind. Each phase
is coloured by its place in the document. Finding badges read F1, F2… in
document order, with the real id in the Selection tab and in Refine prompts. Flow
animations stop after two passes (Shift+A replays them) and follow VS Code's
Reduce Motion setting. The diagram opens at a readable zoom (the whole
document if it fits at 62% or more, otherwise the first phase at 90%); `0`
returns there, and **Fit the whole diagram** shows everything. Zoomed out,
cards show only their titles, at about 11 px.
The header is one row of about 36 px: the title, the assistant and revision,
search (Ctrl+F, or Cmd+F on macOS), the severity toggles, **N not observed**,
**Review**, a **⋯** menu and **Refine…**, which names the step, connection or
finding it will refine.
Below 620 px wide only the title, the severity toggles, **N not observed**,
**⋯** and **Refine…** stay in the row; search, the revision and **Review** move
into the **⋯** menu, which always has **Review the claims** and also holds the phase overview, the legend, the flow animation,
the phase index, the side or bottom panel, **Fit the whole diagram**, the exports and the shortcut sheet.
The phase index item is disabled, with the reason, for a diagram with fewer
than two phases. The
viewer's other keys are single keys, so VS Code's Ctrl and Cmd shortcuts are
left alone; the shortcut sheet prints the keys for your platform.
Escape in the diagram closes the topmost thing (the menu, the shortcut sheet,
the Refine popover, the phase list, the legend, the phase overview, the review walk, the open bottom panel, focus
mode, the selection) or clears the search, and VS Code does not also act on that key
press. Once nothing is left to close and the focus is off the diagram, Escape
goes to VS Code, for example to hide a notification.
The status bar reads, for example, "31 steps · 41 connections",
"Coverage: scoped · 6 limitations" (which opens About), the source
freshness, and the zoom.
The Refine action
copies a follow-up prompt for the assistant that authored the diagram, with one
of five intents (Explain, Expand, Challenge, Trace, or a custom request).
Explain never asks for a new revision. The prompt names the revision currently
in the artifact file as the parent and carries all artifact text inside a
fenced JSON data block. SVG and PNG exports are saved through VS Code's file
picker.

The extension does not bundle or run an analyzer and needs no Python runtime or
model API key. Interpretation stays in the user's active assistant session.

## Development

```sh
npm ci
npm run check
npm test
npm run compile
npm run package
```

Node 20.18.1 or newer is required. The packaged extension contains the host
bundle, shared viewer assets, icon, license, third-party notices, and this
README.
