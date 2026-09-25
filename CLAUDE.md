## Model routing in workflows and subagents
When writing workflow scripts or spawning subagents, default to opus.
Assign sonnet only to stages that are simple and low-risk:
- searching or listing files, gathering context
- running tests, type checks, or linters and reporting results
- mechanical edits that follow an explicit pattern (renames, formatting,
  applying a fix already specified)
- per-file fan-outs where each item is small and well-defined
Keep opus for planning, debugging, design decisions, ambiguous or
cross-cutting changes, verification, and final synthesis.
If unsure whether a task is simple, use opus.
## Project: MLView (native LLM skill + VS Code viewer)
The user's assistant (Copilot, Codex or Claude Code) invokes the `mlview`
skill, reads the target ML code and authors a `*.mlview.json`
WorkflowDocument 1.0. `skills/mlview/scripts/artifact.py` (stdlib-only,
Python 3.10+) validates structure, workspace paths, hashes and exact quotes
and publishes revisions; it never interprets, imports or runs target code.
`vscode-extension/` opens the artifact in the `webview/` renderer, rechecks
evidence freshness, navigates to source and copies refinement prompts.
Opening, filtering or navigating never calls a model.

Read first: README.md, docs/STATUS.md, docs/WORKFLOW_CONTRACT.md,
docs/LLM_WORKFLOW.md, CONTRIBUTING.md, scripts/README.md.

Ownership and boundaries:
- `skills/mlview/` is the canonical skill. Its helper validates and publishes
  model-authored documents; it does not interpret target programs.
- `contracts/workflow.schema.json` is the normative artifact schema. Keep
  docs/WORKFLOW_CONTRACT.md and the skill's references consistent with it.
- `webview/src/` owns the renderer. Its internal graph projection is a display
  representation, not a source analyzer.
- `vscode-extension/src/` owns workspace validation, panels, navigation and
  refinement prompts.
- Only evaluation replay resolves old citation paths through
  `evals/workflow/fixtures/historical-paths.json`; the product validates real
  workspace paths.

Hard rules:
- The static analyzer (analyzer/, MCP server, rule engine, CLI,
  graph.schema.json, hooks, chat participant/LM tools) was removed on
  2026-09-18 at the maintainer's request. Never reintroduce it or add a static
  semantic fallback (tools/verify.py enforces the retired paths).
- Immutable evidence: evals/workflow/** records, ledgers, reference
  candidates, fixtures and historical-paths.json; docs/archive/**;
  docs/demo-logs/**; docs starting with "> Historical record" or
  "> Dated evaluation record"; samples/configured_training* (pinned by
  evals/workflow/test_example.py). Never edit hashes or quotes to pass a
  test; add new dated records instead. `.gitattributes` is `* -text`:
  keep exact bytes and line endings.
- Never report tests, CI or UI checks as semantic accuracy, human review or
  live-host validation. Human reference review and the held-out pilot are
  the owner's decisions; never fabricate approvals.

Contract changes touch five places: contracts/workflow.schema.json,
artifact.py, vscode-extension/src/workflowDocument.ts (+ authoredPanel.ts
revision rules), webview/src/workflow.ts, and the contract docs (docs/ and
skills/mlview/references/). Contract changes are checked by
`contracts/conformance` (schema, helper and extension runners:
tools/test_workflow_conformance.py and vscode-extension/test/
conformance.test.js); add or update a case there with every rule change.

Generated copies (CI runs `git diff --exit-code` on them; commit rebuilt
outputs): edit skills/mlview/ then `python tools/sync-skill.py` (never hand-
edit claude-plugin/skills/); edit webview/src/ then `npm run build` in
webview/ and `python tools/sync-assets.py`; extension compile rewrites
vscode-extension/THIRD_PARTY_NOTICES.md from the root file.

Much of webview/src is legacy analyzer UI running on a projection of the
authored document (workflow.ts). Comments citing "gated by <test>" often
refer to deleted tests; find the test before trusting the claim.

Checks: use Node 20.18.1+ and a Python 3.10+ virtualenv first on PATH (some
systems ship an older python3), with `PYTHONDONTWRITEBYTECODE=1`. Install the
test dependencies with `python -m pip install -r requirements-dev.txt`. Full
gate: `sh scripts/e2e.sh --skip-npm-install` (15 exercised gates; 17 without
the flag); on Windows `powershell -File scripts/e2e.ps1`. Focused:
`python -m pytest skills/mlview/tests tools evals scripts claude-plugin/tests -q`;
`npm run check && npm test` in webview/ or vscode-extension/;
`python tools/verify.py --all` (generated copies, versions, retired paths);
`python scripts/check_docs.py` (links in current docs). CI runs Node 20.18.1
and 22, so avoid APIs newer than Node 20 (for example
`String.prototype.isWellFormed`, `Array.prototype.toSorted`,
`Promise.withResolvers`).

Report only commands actually run, with their results. Local tests do not
prove live-host use or semantic correctness, and an older CI run does not
validate newer edits.

Git: work on a feature branch. The native workflow is on `llm-workflow`
(draft PR #9 to main); until it merges, the default branch still ships the
retired analyzer, so a fresh clone or worktree may start from the wrong base.
Check `git merge-base --is-ancestor <intended commit> HEAD` before starting.
Commit and push only when asked; never force-push or rewrite shared history.
Preserve unrelated working changes. Keep raw transcripts, credentials and
machine-specific paths out of committed files. Frozen decision records stay
historical; do not rewrite them to claim today's behaviour. Update
docs/STATUS.md when what ships changes. Gitignored local state lives in
.mlview/.
