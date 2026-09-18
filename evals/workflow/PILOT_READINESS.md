# Held-out pilot readiness

**2026-09-18: reference drafts and an implemented candidate are ready; scored
runs await human review and reference approval.**

The [review packet](reference-candidates/README.md) provides concrete scenario
proposals, 93 candidate facts, 106 exact source anchors and a proposed common
prompt/budget policy. All eight ledgers are explicitly AI-authored drafts with
human review pending. No target code was imported or executed, and no
held-out native-host output was generated or inspected to prepare them.

The semantic-quality candidate was published as `12747c4`. All 13 remote CI
jobs passed in push run `35287750580` and pull-request run `35287753581` at that
commit. The later [public-readiness review](../../docs/PUBLIC_READINESS_REVIEW.md)
changes the helper and distribution; its local checks and any later remote CI
must be tracked separately. The frozen four-file candidate bundle has SHA-256
`837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
CI success and fresh development follow-ups do not approve reference facts or
count as held-out runs. The public draft ledgers are review inputs, not a
complete candidate fact set or evidence that the candidate improved quality.

Of the six fresh native development follow-ups, five have final native response
evidence and Copilot GAN failed within its two-repair budget. Copilot notebook's
response was recovered during cleanup after publishing a validator-clean
artifact with two repairs; its fresh diagram was not inspected. These outcomes
remain development evidence and do not change
the 24/48 held-out counts below.

## Pinned source availability

All eight repositories are present under the ignored `.public-corpus`
directory. Checkout HEADs match [tasks.json](tasks.json), entrypoints exist,
and cited file bytes independently match their pinned Git blobs.

| Task | Pinned commit |
|---|---|
| `pilot-nanogpt` | `3adf61e154c3fe3fca428ad6bc3818b27a3b8291` |
| `pilot-transformers` | `a2c15b30764b7c6cb0632ac6aed6eac227edc674` |
| `pilot-sklearn` | `dd3ca57300e14d45b7a34fccd0165d143c7a364c` |
| `pilot-flax` | `01854da11286b4109c59d7fd9205f3822fe807d6` |
| `pilot-diffusers` | `c419dac0152186060246c93a095bc1bfaea342b3` |
| `pilot-registry` | `cfd5d3a985b0249de009b67d04f37263e11cdf3d` |
| `pilot-rl` | `fe8d8a03c41a7ef5b523e2e354bd01c363e786bb` |
| `pilot-notebook` | `e707c2d659abafb9b1f9fd927907619a128db8d7` |

MMDetection's selected config and four inherited bases were initially absent
from the local partial checkout. Narrow retrieval from the pinned revision
closed that source gap; all five blob hashes match the Git tree. The selected
configuration is a proposal, not a default supplied by `tools/train.py`.
External framework/runtime/data behavior remains qualified in the drafts.

## Remaining gates

1. A named human reviewer checks and freezes each scenario, source-linked
   reference facts, essential-fact denominator, unresolved cases, and
   defect/non-defect decisions before inspecting outputs.
2. The pilot owner freezes expanded prompts, budget/stop policy, native model
   settings and repair rules. The packet gives a concrete proposal; these
   choices have not silently been treated as approved.
3. Capture skill/reference/source/extension/host/model identities before runs.
   The implementation commit and skill bytes are frozen above; reference and
   expanded-prompt identities still await human review and freezing.
4. Execute Stage 1: the 24 `repeat: 1` records covering all eight tasks in all
   three hosts. Retain failed and blocked attempts, then complete human claim
   ledgers for every record before making the stop/go decision.
5. Continue to Stage 2, the 48 `repeat: 2` and `repeat: 3` records, only if the
   frozen Stage 1 implementation meets all predefined targets: 100% valid
   structure, 100% exact anchors, at least 95% supported claims, at least 85%
   essential-fact recall, qualification of every known unresolved scenario,
   and zero high-severity false accusations. A target miss stops the campaign;
   it must not be hidden by proceeding to repeats.
6. Human-review all Stage 2 records and report complete 72-run per-host/task
   numerators and denominators. Stage 1 success is permission to collect more
   evidence, not a completed or passed pilot.

The local `.mlview/pilot-runs.json` was generated only because it did not already
exist. The summarizer confirms **72 pending, zero completed, zero human-reviewed,
`pilotComplete: false`**. Its prompts remain drafts until expanded/frozen.
Consequently Stage 1 has **24 pending and zero passed**, Stage 2 has **48 pending
and zero passed**, and none of the stop/go targets has a measured result.

For the current native development follow-ups, Claude Code uses Fable 5.1 with
Extra High reasoning and Codex uses Sol with Ultra reasoning. Copilot Auto was
already selected and both current sessions routed to GPT-5.6 Luna; Upgrade
appeared only as an unavailable choice and was never selected, and no account
change occurred. These are development
settings to preserve, not approved held-out settings until the pilot owner
freezes them with the references and run policy.

Citation integrity and native UI mechanics can be checked independently of
human semantic review. [The host retry log](../../docs/demo-logs/2026-09-17-host-retry.md)
records successful basic round trips in Copilot and Claude, completing the
earlier Codex coverage. These configured-training compatibility exercises do
not count toward the held-out matrix or establish semantic accuracy.
