# Security Policy

## LLM workflow

The MLView skill runs in the user's selected Copilot, Codex, or Claude Code
session. Source inspected by that assistant follows the host's normal model
processing, permission, retention, and network policies. **LLM analysis is not
an offline-only operation.** MLView adds no model service, API key storage,
credential extraction, or cross-extension access to another assistant's model.

The skill instructs the assistant to read source and configuration as data,
without importing or running the target program. It writes drafts and published
diagram artifacts into the workspace. The deterministic helper reads cited and
declared inspected files, validates exact UTF-8 excerpts, checks paths and
hashes, and publishes JSON. The helper and renderer do not execute analyzed
source. Host permission controls govern the assistant's own tools; skill prose
is not a sandbox for the host model.

Artifacts are untrusted input. The helper and VS Code boundary validate the
version, structure, references, ranges, size limits, and workspace containment,
including symlinks. The panel binds citations to the artifact's workspace
folder, rechecks the displayed revision before navigation, and retains the last
valid revision when an update is malformed. Saved source changes mark the
affected evidence stale; unsaved editor changes block a jump when the cited
lines no longer match. A valid citation proves that text exists at an anchor,
not that it supports the model's interpretation. Findings remain model-authored
claims.

Refinement prompts copy artifact and workspace text, such as the question,
labels, the viewer's rejection reasons and changed file names, only inside a
delimited JSON data block; evidence quotes are not copied. The prompt's own
lines contain host-written text, validated IDs and JSON-quoted strings (the
artifact's own path and a custom request typed in the composer), and tell the
assistant to treat the block as data, never as instructions. C0 and C1
controls, bidirectional controls, line and paragraph separators and Unicode
default-ignorable characters (among them zero-width characters, variation
selectors, Hangul fillers and tag characters) are escaped in the block, in the
quoted strings and in the status banner, which shows artifact-derived text as
single, bounded lines. In VS Code Restricted Mode the prompt also states that
the workspace is not trusted. The skill likewise treats repository files and
artifacts as data. These measures reduce, but cannot eliminate, prompt
injection through files the assistant reads; the host's permission controls
remain the boundary for its tools.

Generated labels and excerpts render as text under the webview's Content
Security Policy. No artifact may choose an executable command or model
endpoint. Opening, filtering, or refreshing a diagram does not call an LLM.
Authored findings are not automatically published as Problems, CodeLens,
rule-based fixes, or suppression directives.

Published artifacts contain source excerpts and relative paths. Review their
contents before sharing them. Local model/session histories are not distributed
with the skill or extension. The viewer itself works from local assets without
remote resources.

## Reporting a vulnerability

Please report privately through the repository's **Security → Report a
vulnerability** action if available. If that private route is unavailable,
open a non-sensitive issue at <https://github.com/realmyang/MLView/issues>
asking for private vulnerability reporting to be enabled. Do not include the
vulnerability, secrets, personal contact details, or an exploit in that issue.

Include the revision, host and OS versions, a harmless minimal reproducer, and
the expected boundary. Execution of artifact text, workspace escapes, unsafe
source navigation, credential disclosure, and unbounded processing are security
issues. Unsupported or missing semantic findings belong in accuracy reports.

This is a pre-release project with no service-level agreement. Fixes target
the current development branch and the next release; no release branches are
maintained for backports.
