# Security policy

## Reporting a vulnerability

Private vulnerability reporting is switched on for this repository. To report
a vulnerability, open the repository's **Security and quality** tab on GitHub
and choose **Report a vulnerability**. Do not put a vulnerability, a secret,
personal contact details or an exploit into a public issue.

Include MLView's version or commit, the versions of the assistant, of VS Code
and of the operating system, a harmless minimal reproducer, and the boundary
that you expected to hold. Execution of text from a diagram, an escape from the
workspace, unsafe source navigation, disclosure of credentials and unbounded
processing are security issues. A wrong or missing claim in a diagram is not a
security issue:
[Report a wrong diagram](docs/validation.md#report-a-wrong-diagram) says how
to report one.

## Supported versions

MLView is a preview. The format and the viewer can still change between
releases, and fixes go into the next release. No release branch is kept for
backports.

## How MLView handles your code

### The assistant's session

The MLView skill runs in the session of the assistant that you chose: GitHub
Copilot, Codex or Claude Code. MLView does not control how that assistant
processes, keeps or sends the source it inspects: the assistant's own policies
and permission settings apply. **An analysis by an assistant is not an
offline-only operation.** MLView adds no model service, stores no API key,
reads no credentials and does not use another extension's access to a model.
See
[What leaves your machine](docs/user-guide.md#what-leaves-your-machine-and-what-a-diagram-file-holds)
in the user guide.

### The skill and the helper

The skill instructs the assistant to read source and configuration as data,
without importing or running the target program. The assistant writes drafts
into the workspace, and the helper writes published diagrams there. The helper
reads the cited files and the files listed as inspected, checks exact UTF-8
excerpts, paths and hashes, and publishes JSON. The helper and the viewer do
not execute the source they read. The assistant's own permission controls
govern its tools; the skill's text is not a sandbox for the model.

### Diagrams are untrusted input

A diagram file is untrusted input. The helper and the extension each check the
version, the structure, the references, the ranges, the size limits and that
every path stays inside the workspace, symbolic links included. The panel
resolves citations inside the workspace folder that holds the diagram, checks
the cited file again before it opens a cited line, and keeps the last valid
revision on screen when an update is malformed. A saved change to a source
file marks the evidence that cites it as stale; an unsaved change in an editor
blocks a jump when the cited lines no longer match. A valid citation shows
that the text is at the cited lines, not that it supports the assistant's
claim. Findings remain claims by the assistant.

### Refinement prompts

A refinement prompt copies text from the diagram and the workspace, such as
the question, labels, the viewer's rejection reasons and the names of changed
files, only inside a delimited JSON data block; evidence quotes are not
copied. The prompt's own lines contain text that the extension wrote, checked
IDs and JSON-quoted strings (the diagram's own path and a custom request typed
in the composer), and tell the assistant to treat the block as data, never as
instructions.

C0 and C1 controls, bidirectional controls, line and paragraph separators and
Unicode default-ignorable characters (among them zero-width characters,
variation selectors, Hangul fillers and tag characters) are escaped in the
block, in the quoted strings and in the status banner, which shows text from a
diagram as single, bounded lines. In VS Code Restricted Mode the prompt also
states that the workspace is not trusted. The skill likewise treats repository
files and diagrams as data. These measures reduce, but cannot eliminate,
prompt injection through files that the assistant reads; the assistant's
permission controls remain the boundary for its tools.

### The viewer page

Labels and excerpts from a diagram are drawn as text, under the page's Content
Security Policy. A diagram cannot name a command to run or a model address.
Opening, filtering or refreshing a diagram calls no model. Findings appear
only in the diagram: the extension creates no diagnostics, code lenses or code
actions.

### What a diagram file contains

A published diagram contains excerpts of source and relative paths. Read it
before you share it. The viewer works from the extension's own files and loads
nothing from a network.
