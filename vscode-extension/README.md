# MLView for VS Code

MLView opens interactive, source-linked workflow diagrams created by the MLView
skill in Copilot, Codex, or Claude Code.

Invoke the skill in your assistant to analyze the repository and publish a
`*.mlview.json` WorkflowDocument. Then run **MLView: Open Generated Diagram** or
open the command from the artifact editor title.

The viewer validates the document and its source evidence before displaying it.
Evidence links open the cited source range or notebook cell. The Refine action
copies a revision-aware follow-up prompt for the assistant that authored the
diagram. SVG and PNG exports are saved through VS Code's file picker.

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
bundle, shared viewer assets, icon, license, and this README.
