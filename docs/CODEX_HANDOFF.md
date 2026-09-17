# MLView takeover — 2026-09-16

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
