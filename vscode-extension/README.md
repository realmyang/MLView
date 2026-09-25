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
changed files; only jumps into those files are blocked. Unsaved editor changes
never change validation. They are reported separately, and a jump is blocked
only when the unsaved text no longer contains the cited lines.

Evidence links open the cited source range or notebook cell. The Refine action
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
