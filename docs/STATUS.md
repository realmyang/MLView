# Current status

MLView ships one workflow: invoke the native `mlview` skill in Copilot, Codex or
Claude Code, then open its `*.mlview.json` artifact in the VS Code extension.
The active model interprets source and authors the diagram. Python helpers
validate structure, workspace paths, hashes and exact citations; they do not
perform semantic analysis.

The old static analyzer and all of its runtime integrations were removed on
2026-09-18 at the maintainer's request. There is no analyzer CLI, Python package,
static rule engine, MCP analysis server, static Copilot tool, pre-commit hook,
or analyzer GitHub action in the current tree.

The native path includes installed skill ZIPs, a Claude skill plugin, a
WorkflowDocument contract, source/notebook navigation, evidence and
counter-evidence, scope filters, refinement prompts and revision watching.
Malformed revisions retain the last valid diagram. No model runs on open,
refresh, filtering or source navigation.

This remains experimental. Recorded native development artifacts and review
ledgers are preserved, including their known shortcomings; human semantic review
and the held-out native-host pilot are still pending. Structural test results do
not establish model accuracy. See [the evaluation protocol](../evals/workflow/README.md)
and [current validation](VALIDATION.md).

Historical live host exercises predate this removal. Windows and remote VS Code
interaction need live validation before compatibility is claimed. Latest CI
results: see [VALIDATION.md](VALIDATION.md) and the repository's
[Actions page](https://github.com/realmyang/MLView/actions).

Version 0.2.0 adds Campaign 1, "reliability and trust" (see the
[changelog](../CHANGELOG.md)). An open panel follows the artifact file on disk
and shows a revision whose sources changed as a historical diagram instead of
refusing it. Freshness uses the saved file bytes, as the helper does. Refinement
prompts carry artifact text only inside a JSON data block and name one of five
intents; Explain never publishes. The helper no longer fingerprints MLView's own
artifacts, drafts or installed skill. A shared corpus in
`contracts/conformance` checks the schema, helper and extension together. With
the fixes from the campaign's first review, on commit `85c6c63`, the full local
gate passed on one macOS machine ([details](VALIDATION.md)). CI has not yet run
on it. The manual live VS Code
checks (high-contrast light, a BOM file open while publishing, a symlinked
root, Windows drive letters) have not been run, and none of this is semantic
validation.

The [trust and usability campaign](TRUST_USABILITY_CAMPAIGN.md) implements the
first campaign from the [improvement research](IMPROVEMENT_RESEARCH_2026-09-18.md):
authored wording, evidence inspection, textual relationships, coalesced
validation, source-reading aids, incremental draft edits, bundle diagnostics
and reproducible performance/candidate checks. See its measured results and
remaining gates. No human semantic review or held-out pilot pass is implied.

The follow-up completed macOS VS Code viewer/keyboard checks and focused browser
and native performance profiling through 2,000 nodes. Source links now retain
the visible diagram, side tabs support keyboard navigation, and both validators
enforce the same evidence requirements. Large full-view updates remain slow;
the [profile](PERFORMANCE.md) identifies repeated routing obstacle checks as
the next optimization target. These synthetic viewer exercises do not run or
score a native assistant. The [human review guide](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
explains the pending owner/reviewer decisions.
