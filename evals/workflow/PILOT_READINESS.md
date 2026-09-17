# Held-out pilot readiness

**2026-09-17: reference drafts ready; scored runs await human review.**

The [review packet](reference-candidates/README.md) provides concrete scenario
proposals, 93 candidate facts, 106 exact source anchors and a proposed common
prompt/budget policy. All eight ledgers are explicitly AI-authored drafts with
human review pending. No target code was imported or executed, and no
held-out native-host output was generated or inspected to prepare them.

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
   The packet records current skill and VSIX hashes because the implementation
   is not yet identified by its own Git commit.
4. Execute and retain the 72 native-host sessions, then collect human claim
   ledgers and report per-host/task numerators and denominators.

The local `.mlview/pilot-runs.json` was generated only because it did not already
exist. The summarizer confirms **72 pending, zero completed, zero human-reviewed,
`pilotComplete: false`**. Its prompts remain drafts until expanded/frozen.

Citation integrity and native UI mechanics can be checked independently of
human semantic review. [The host retry log](../../docs/demo-logs/2026-09-17-host-retry.md)
records successful basic round trips in Copilot and Claude, completing the
earlier Codex coverage. These configured-training compatibility exercises do
not count toward the held-out matrix or establish semantic accuracy.
