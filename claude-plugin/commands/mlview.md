---
description: Use the active Claude model to map an ML workflow and publish an interactive source-linked MLView diagram
argument-hint: "[question or focus]"
allowed-tools: [Bash, Read, Glob, Grep, Write, Edit]
---

# /mlview — understand and visualize an ML workflow

Use the bundled `mlview` skill. Treat `$ARGUMENTS` as the user's requested
question or analysis focus; when empty, map the repository's principal ML
workflow. Inspect source, configuration, notebooks, launch scripts, tests, and
documentation with native tools. Claude is the semantic analysis backend.

Author and validate a WorkflowDocument draft, publish
`workflow.mlview.json` with the skill's Python 3.10+ helper, and tell the user to
run **MLView: Open Generated Diagram** in VS Code. Do not call the legacy static
analyzer first or present a legacy MLGraph as this model-authored result.

The explicit `/mlview-issues` command, `mlview-triage` skill, and `mlview_*` MCP
tools remain available for legacy deterministic static analysis. Their legacy
selectors are `all`, `concern:`, `file:`, `node:`, `pipeline:`, `stage:`,
`symbol:`, and `unit:`; these selectors filter static output and do not replace
the authored workflow request above.
