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
**Findings**, **All** and, after a cited file changed, **Changed files** as the
other filters. `j` / `k` or ↓ / ↑ move, `[` / `]` change quote, Enter opens
again, `u` / Shift+U and `n` / `p` go through the claims not observed and the
findings, and Escape or `r` ends it. About 150 ms after each step the claim's
cited lines open beside the diagram, highlighted, with the keyboard kept on
the diagram; a quote whose file changed or is missing is not opened, and the
walk bar (under the diagram) and the Selection tab say why, with no
notification. The walk remembers its place per revision in the panel's view
state and records nothing else; the changed-files notice offers **Review
affected claims**.
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
into the **⋯** menu, which always has **Review the claims** and also holds the legend, the flow animation, the overview map,
the side or bottom panel, **Fit the whole diagram**, the exports and the shortcut sheet.
The overview map item is disabled, with the reason, when the map is not drawn
(at 900 px wide or narrower, under 350 px tall, or below 30 cards). The
viewer's other keys are single keys, so VS Code's Ctrl and Cmd shortcuts are
left alone; the shortcut sheet prints the keys for your platform.
Escape in the diagram closes the topmost thing (the menu, the shortcut sheet,
the Refine popover, the legend, the review walk, the open bottom panel, focus
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
