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

Version 0.3.0 adds Campaign 2, "pilot readiness" (see the
[changelog](../CHANGELOG.md)): owner decision files with a `check` command,
the campaign freeze and `check-frozen`, the v2 pilot candidate that builds its
own VSIX, sealed run records, and a `summarize` that verifies every sealed run
against the frozen campaign and computes the Stage 1 stop/go decision. The
owner's reference review has not happened and **no reference is frozen**: every
file in `evals/workflow/decisions/` is a pending template. The pilot has **not
run**: Stage 1 has 24 skill runs pending and 0 passed, and Stage 2 has 48
pending. The fixes for the campaign's first five reviews (37, 15, 25, 19 and
15 findings) are in: among them, a run is retried only if its prompt was never
sent (`Prompt sent: no` in `session.md`, refused against sealed evidence that
it was sent, including the skill's drafts under `.mlview/`), every earlier
attempt stays in the summary, a recorded summary or candidate can never be
removed, replaced or recorded again, merges included, Stage 1 runs are final
once the Stage 1 summary is recorded, a summary's own `tooling` field never
switches a check off (other tools must be versions committed in the
summary's history), and a committed campaign is never erased. Campaign commits reach
`main` by a merge commit or fast-forward, never a squash. With them, the local
gate passed on one macOS machine ([details](VALIDATION.md)).
CI has not yet run on the Campaign 2 branch. 0.2.0 shipped to `main` on
2026-09-25, when PR #9 was squash-merged as `d99904f`; the Campaign 2 branch
is based on that commit.

Version 0.2.0 adds Campaign 1, "reliability and trust" (see the
[changelog](../CHANGELOG.md)). An open panel follows the artifact file on disk
and shows a revision whose sources changed as a historical diagram instead of
refusing it. Freshness uses the saved file bytes, as the helper does. Refinement
prompts carry artifact text only inside a JSON data block and name one of five
intents; Explain never publishes. The helper no longer fingerprints MLView's own
artifacts, drafts or installed skill. A shared corpus in
`contracts/conformance` checks the schema, helper and extension together. With
the fixes from the campaign's first and second reviews, on commit `106f172`, the
full local gate passed on one macOS machine ([details](VALIDATION.md)).
CI then passed all eight jobs (Python 3.10–3.13; Node 20.18.1 and 22 on Linux, macOS and Windows) at `deab60a`, in the [push](https://github.com/realmyang/MLView/actions/runs/36093596906) and [PR](https://github.com/realmyang/MLView/actions/runs/36093599706) runs, after two test-only fixes for older Python and Windows. A partial
[live check](demo-logs/2026-09-25-campaign1-live-check.md) in a macOS VS Code
Extension Development Host confirmed High Contrast Light, a BOM source open in
an editor, unsaved-edit and changed-on-disk banners, and the Challenge prompt.
HC Dark, the other intents, a symlinked root, Restricted Mode and Windows were
not exercised live, and none of this is semantic validation.

The [trust and usability campaign](TRUST_USABILITY_CAMPAIGN.md) implements the
first campaign from the [improvement research](IMPROVEMENT_RESEARCH_2026-09-18.md):
authored wording, evidence inspection, textual relationships, coalesced
validation, source-reading aids, incremental draft edits, bundle diagnostics
and reproducible performance/candidate checks. See its measured results and
remaining gates. No human semantic review or held-out pilot pass is implied.

The follow-up completed macOS VS Code viewer/keyboard checks and focused browser
and native performance profiling through 2,000 nodes. Source links now retain
the visible diagram, side tabs support keyboard navigation, and both validators
enforce the same evidence requirements. The [profile](PERFORMANCE.md) identified
repeated routing obstacle checks as the bottleneck; Campaign 1 now runs the
cheap geometric test first, with identical routes, and the jsdom benchmark's
2,000-node update fell from about 10 s to about 1.5 s on the same machine. These synthetic viewer exercises do not run or
score a native assistant. The [human review guide](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
explains the pending owner/reviewer decisions.
