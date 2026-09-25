> Historical record: Codex-era takeover handoff (through 2026-09-24). AGENTS.md, which it cites, was removed on 2026-09-25; its Sol-only subagent rule applied to the Codex period only. Current guidance: [CLAUDE.md](../CLAUDE.md) and [STATUS.md](STATUS.md).

# Current handoff — 2026-09-18 trust and usability campaign

The user authorized execution of the improvement recommendations after the
static analyzer removal and research were pushed. The active product remains
the native LLM skill plus WorkflowDocument viewer. Do not restore the retired
analyzer; historical preservation requirements below no longer apply.

Removed the analyzer source and Python distribution, legacy contracts/goldens,
MCP/vendor/hooks, static extension commands/tools, static rule catalog and static
build/CI paths. Kept the local artifact validator, authored panel and renderer,
skill installers/packages, evaluation records, licenses and prior hardening.
Evaluation source examples moved to `evals/workflow/fixtures/`; recorded native
artifacts were not rewritten. Replay uses a hash-pinned historical path map.

Current operational guidance is in [AGENTS.md](../AGENTS.md),
[CONTRIBUTING.md](../CONTRIBUTING.md) and [STATUS.md](STATUS.md).
Validation of the earlier removal is recorded in [VALIDATION.md](VALIDATION.md):
15 local end-to-end gates passed, with 102 Python tests plus 16 subtests,
21 viewer tests and 30 extension tests. Two unavailable Claude CLI checks were
explicitly skipped. The user then requested commit and push: `5319777` is
published on `llm-workflow`, and both push and PR CI passed all eight jobs.
Live hosts were not rerun after the removal.
Human semantic review and the native held-out pilot remain outstanding.

Research was published in `d40d96e`. The user's subsequent “Execute your
recommendations” authorized the [trust/usability campaign](TRUST_USABILITY_CAMPAIGN.md).
It implements authored semantics, complete evidence inspection and textual
relationships, coalesced validation with race guards, interpretation references,
protected incremental draft edits, full-bundle diagnostics, candidate snapshots
and performance/evaluation preparation. The campaign was committed and pushed
as `84ea3a1` on `llm-workflow`. Follow-up `7182224` fixed the Windows absolute-path
issue caught by CI. Read current validation for later live-check fixes and CI.

See [current validation](VALIDATION.md) for tests actually run. The independent
Sol skill exercise is auxiliary, not a native-host or human-reviewed score.
The initial desktop-control attempt stalled. The user subsequently authorized
live VS Code usability tests and browser/native renderer profiling. Those checks
use synthetic fixtures and do not run a native assistant or target ML code.
They found tab navigation, source-column selection, benchmark-fixture and
validator-parity defects; the follow-up fixes and measurements are recorded in
current validation. They do not establish a spoken screen-reader pass.
A named human must still
review the [reference packet](../evals/workflow/reference-candidates/README.md)
before the 24/48 scored pilot. The separate no-skill plan adds 24 Stage 1
sessions; none has run. The [candidate protocol](../evals/workflow/CANDIDATE_PROTOCOL.md)
replaces reliance on historical four-file hashes for future evaluations.
The [human review guide](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
explains what the user or a nominated reviewer supplies and what the agent can
prepare. No review decisions have been fabricated or recorded as approved.

---

The following material records earlier campaigns. Its static analyzer commands
and preservation instructions no longer apply to the current product.

# MLView takeover — 2026-09-16

> **Current update (2026-09-18):** the user requested a thorough review, fixes,
> appropriate optimization and public open-source readiness. The resulting
> [review record](PUBLIC_READINESS_REVIEW.md) describes validation hardening,
> graph/source-read optimizations, licensed skill distribution, packaging gates
> and contributor documentation. Work remains on `llm-workflow`; the review
> started from a clean tree at `12747c4`. That published commit passed all 13
> remote CI jobs in push run `35287750580` and PR run `35287753581`; these runs
> do not validate the later review fixes. Read the review record for their
> local checks and remaining owner-controlled repository settings.
>
> The [semantic-quality batch](QUALITY_SPRINT.md) retains its frozen four-file
> bundle hash `837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
> Twelve original skill reviews and three baseline comparisons remain
> model-provisional. Five of six fresh follow-ups have valid artifacts and final
> native response evidence; Copilot GAN failed within its two-repair budget.
> Copilot notebook's final response was recovered during cleanup and repeats
> the incorrect claim that execution counts are absent. Its fresh live diagram
> remains unverified. Preserve the frozen artifacts and manifests. Current
> helper and license changes alter the distributable bundle, so freeze a new
> bundle before another native campaign.
>
> The 24 held-out first runs and 48 repeats have not started. Human review and
> reference approval remain prerequisites; structural, UI and CI success must
> not be reported as semantic accuracy. The review does not launch new native
> model sessions, merge the PR or claim marketplace publication.

> **Later user correction (2026-09-16):** the intended product is an LLM skill
> using the native Copilot, Codex, or Claude Code model as the analysis backend.
> The active proposal is [LLM_DIRECTION_PLAN.md](LLM_DIRECTION_PLAN.md), with
> skill invocation followed by an interactive VS Code diagram. Implementation
> was explicitly authorized by “Execute your recommended plan.” Work is on
> `llm-workflow`; see [LLM_IMPLEMENTATION.md](LLM_IMPLEMENTATION.md) for the
> implementation, built distributions, native-host checks and fresh verification.
> The [September 17 retry](demo-logs/2026-09-17-host-retry.md) completed the
> interrupted Copilot/Claude round trips. Basic native publication, source
> navigation and refinement now pass in all three hosts; the
> [pilot references](../evals/workflow/reference-candidates/README.md) still
> require human review before scored runs.
> The user then authorized the next quality sprint: selection-aware refinement,
> explicit scenarios, reproducible distribution, a small native development
> comparison, and a staged held-out pilot after human review. The previous
> implementation is checkpointed at `bb56cdc`; distribution checks are in
> `2b999f1`. Read the implementation page for the latest validation state.
> The follow-up implementation passed all 20 local end-to-end gates and 41
> helper/distribution/evaluation tests plus four subtests. The
> [development retry](demo-logs/2026-09-17-development-retry.md) increased the fresh
> native batch to seven initial artifacts and one challenged child revision.
> Selected-node/finding prompts, VSIX installation and interrupted refinement
> were exercised. A discovered remount bug is fixed in `884c5f8` with a regression
> test; live acceptance of the rebuilt VSIX remains pending.
> The next publication retry succeeded: `llm-workflow` is pushed and
> [draft PR #9](https://github.com/realmyang/MLView/pull/9) is open. The credential
> now includes `workflow` scope. The
> [next desktop retry](demo-logs/2026-09-17-publication-desktop-retry.md) found and
> fixed a second selection race: state must be saved before posting navigation,
> because the webview may disappear before its debounced save. An immediate
> destruction regression fails without that fix and passes with it. Remote CI
> also exposed four Windows path-expectation mismatches, now corrected in tests.
> A late Claude GAN publication brings the initial artifact count to eight;
> its final native UI response was not observed. Desktop control recovered and
> then failed again, leaving four skill cases, three no-skill baselines and remaining
> live checks pending. See the implementation page for revision-specific CI and
> exact acceptance boundaries. No held-out pilot or human semantic scoring has
> started.
> The final `d1461b4` remote matrix passed all 13 active jobs, including Windows
> PowerShell end-to-end. After the user confirmed that VS Code was visible on
> an unlocked desktop, connection recovered. The final `9de5a9d9…` VSIX passed
> live installation, immediate edge-to-source navigation, selected-edge restore
> after remount and copied refinement-prompt verification in the completed
> macOS Codex GAN workspace. Remaining native runs are recorded separately;
> this check does not establish all-host or all-platform acceptance.
> Copilot's grouped-CV task subsequently published the ninth initial artifact,
> and the completed Codex no-skill baseline response was captured. The final
> responses for Codex's notebook and Claude's GAN were also recovered. Three
> skill cases and two baselines remain pending workspace-trust approval.
> A separate partial notebook overview also passed helper validation with
> explicit unfinished work and unchanged original inputs. It is outside the
> initial-case matrix; its final response and live diagram remain unobserved
> after another `cgWindowNotFound` failure. No native session was stopped.
> The user then explicitly approved trust for all five prepared folders; each
> trust change succeeded. Claude's notebook case and both remaining baselines
> completed, bringing the matrix to ten skill cases and all three baselines.
> Copilot GAN and notebook sessions were last seen running after tool approvals;
> their publication remains unobserved after another desktop attachment failure. The partial overview's final response was
> recovered and its live diagram exposed a false legacy truncation banner.
> The adapter fix passed targeted suites and the rebuilt VSIX passed live
> partial-display acceptance. All 13 CI jobs at `6509e4f` passed before this
> latest display fix; see the implementation page for exact acceptance boundaries.
> The September 18 local-time retry recovered the two interrupted Copilot chats
> in their already trusted workspaces and completed both: the development batch
> now has all twelve initial skill artifacts and all three baseline responses.
> GAN reported one validator repair; the notebook reported zero. Both diagrams
> opened and navigated to the expected source line/cell with selection retained.
> Frozen inputs stayed unchanged; semantic limitations are preserved for review
> rather than edited out of the original model outputs. All thirteen CI jobs
> passed at `0103178`, including the partial-display fix. Human adjudication,
> the held-out pilot and broader live-host/platform checks remain pending.
> The static-only direction and “next Sprint A” below
> are the historical takeover snapshot, not the current roadmap.

Codex recovered the repository's Claude Code working context and reviewed the
current implementation. The user's current ground rule is **Sol-only
subagents**, recorded in [AGENTS.md](../AGENTS.md); the former Opus preference
in Claude memory is superseded.

This is a dated handoff, not a new product specification. Source and freshly
run gates take precedence over its snapshot. Repository instructions use the
standard [AGENTS.md discovery mechanism](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Checkout at takeover

- Branch: `research-review`, HEAD `317930d` — research review of rule coverage
  and accuracy. The working tree was clean before these handoff files.
- Its parent is `3c2babf`, the public-readiness squash merge for PR #7 and the
  locally cached `origin/main`. HEAD adds research documentation only.
- The local `main` branch is older. Check ancestry and refresh remote refs
  before basing new work on it.
- Claude's last delivery records research PR #8 from `research-review` to
  `main`. Its present remote/CI status was **not verified** during takeover:
  the public-page fetch failed and `gh` has no configured authentication.
  No commits, pushes, merges, or branch deletions were made during takeover.

## Recovered sessions

The original Windows project conversation was transferred to this Mac on
September 9 local time and continued here through September 16. Recovery read
the main conversation, the transfer conversation, Claude's project memories,
and the latest compacted summary, then reconciled them against git and source.
The early prototype, flow/scoping work, roadmap sprints, hardening, consolidation,
public readiness, and research delivery are represented in that history.

The local index at `.workflows/claude-history/README.md` records source locations
and session IDs. Its manifest and text exports make 718 transcript files
(main sessions and worker histories; 105,251 valid records) searchable from
this checkout. Text exports omit tool calls/results, thinking, and attachments;
the original Claude files remain
the source for tool results and attachments. This is recovery of context into
files; the conversations were not inserted into Codex's native session database.
The archive is gitignored and is not part of a fresh clone.

Historical context that matters:

- The user values deliberate design before feature implementation, realistic
  ML/DL coverage, public-repository testing, and measured review/fix cycles.
- The old `instructions.md` IDE tab referred to an unrelated equity-research
  prompt. Claude left it untracked; it is absent now and is not MLView guidance.
- Two campaigns started from an incomplete branch base and had to be rebuilt.
  Verify ancestry rather than assuming a branch named `main` contains the work.
- The latest Claude exchange answered the user's report from another machine:
  “MLView answers from local static analysis only.” This supports a limited
  observation that the chat participant ran there, not a completed validation
  runbook. No filled demo log is present.
- That answer matches [vscode-extension/src/chat.ts](../vscode-extension/src/chat.ts):
  the participant formats deterministic analysis results without a model call.
  Copilot's agent tools and Claude's MCP tools expose analysis to their host
  models. Optional LLM triage in research section 6.8 is only a proposal.

## System map

| Component | Role and source of truth |
|---|---|
| [analyzer](../analyzer/README.md) | Dependency-free Python core: discovery → AST → bindings/dataflow IR → graph/rules → diagnostics and output. Default dataflow is `ip`; `local` remains supported. |
| [webview](../webview/README.md) | Shared TypeScript viewer: stage lanes, source navigation, flow animation, scoping, issues, comparison, and export. |
| [VS Code](../vscode-extension/README.md) | Python process adapter, shared webview, Problems/CodeLens, chat participant, and three Copilot tools. |
| [Claude plugin](../claude-plugin/README.md) | Five MCP tools, slash commands, and edit hooks over the same analyzer; tracked vendor copy supports installation without a build. |
| [contracts](CONTRACTS.md) | Normative v1.1 interfaces and invariants; graph schema stays 1.0, demo golden stays unchanged. |
| [verification](../scripts/README.md) | Parity, accuracy, public-corpus, packaging, docs, component, and end-to-end gates. |

All surfaces derive from the same analyzer graph. Standalone HTML and VS Code
use the shared viewer bundle, and Claude opens the self-contained HTML produced
from it. Analysis is static and offline; it never runs the source it reads.
Scopes project the complete graph produced for the chosen analysis input;
scope itself never narrows that input. Generated copies must stay synchronized.

## Where work stopped at takeover (historical)

The user subsequently paused this static-expansion direction. The next proposed
campaign is M1 of [LLM_DIRECTION_PLAN.md](LLM_DIRECTION_PLAN.md); the sequence
below records what Claude had proposed before that correction.

Implementation through public readiness is present. The latest research round
was delivered as the documentation in
[RESEARCH_COVERAGE_ACCURACY.md](RESEARCH_COVERAGE_ACCURACY.md) and its
[bibliography](research/sources.md). Its ranked plan is advisory; takeover did
not begin implementing it.

Section 8, **Sprint A**, is the proposed next sequence:

1. Repair three reproduced defects: Keras `predict` result typing (MLV305/306),
   swapped splitter shuffle semantics (MLV106), and `torch.load` handling and
   wording (MLV803). The report contains reproductions and acceptance criteria;
   these are still pending in the inspected source.
2. Improve value identity through indexing/shape-preserving operations and
   HuggingFace outputs, widen evaluation regions, and improve interprocedural
   identity and model recognition with the report's false-positive safeguards.
3. Restrict wrapper confidence reductions to the regions they govern, then
   update rule-authoring and corpus adjudication before adding new rules.

The original [ROADMAP.md](ROADMAP.md) is largely a landing history. Use the newer
research plan for candidate work, while preserving the contract and the
precision/recall gates. The research's independent ranking agent failed on
output length; its writer synthesized the final tiers from seven research
reports. Keep that provenance in mind when choosing priorities.

## Verification performed during takeover

Environment: existing venv Python **3.13.15**, Node **26.4.0**. The shell's
default `python3` was 3.9, so commands ran with the venv on PATH and
`PYTHONDONTWRITEBYTECODE=1`.

| Fresh check | Result |
|---|---|
| `python tools/verify.py --all` | **10/10 PASS**, no skipped parity row. Includes CLI/MCP byte parity, core copies, Python/TS scopes, version and renderer hashes. |
| `python tools/accuracy.py --dataflow ip` | **PASS** against the committed IP baseline: 158 programs, 546 labels; 80.4% recall, 72.5% visible recall, 79.2% unseen recall, 100% measured precision; graph fidelity 1072/1166 = 91.9%. |
| `python scripts/check_docs.py` | **PASS**, including the updated documentation index. |

These measurements are limited to their corpora and checks. The complete
component suites, full end-to-end workflow, public-corpus sweep, packaging,
Windows/Linux, and current remote CI were not rerun for this documentation
handoff. Their earlier results remain dated evidence in [STATUS.md](STATUS.md).

Live host validation and publishing remain unfinished. The user has reported
the Copilot footer above, but the detailed
[VALIDATION.md](VALIDATION.md) checklist and [DEMO_LOG.md](DEMO_LOG.md) still
need a completed run. The documented Windows Claude-hook dependency on Git
Bash and other standing gaps are in `STATUS.md`; do not mark them fixed based
on this takeover.
