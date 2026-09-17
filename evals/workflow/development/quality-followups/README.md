# Native quality follow-ups

This directory preserves fresh native-assistant outputs for two focused
development cases: the DCGAN alternating-update loop and the out-of-order
notebook. Each `*.mlview.json` file is a byte-identical copy of the assistant's
final published artifact. [`manifest.json`](manifest.json) records public
provenance and independent replay validation against the frozen source and the
installed helper.

[`comparison.json`](comparison.json) is a provisional, source-linked review of
six questions applied consistently across hosts. It compares these follow-ups
with the immutable snapshots in `../native-artifacts/`. The review identifies
semantic gains, regressions, and remaining risks; it is not a benchmark score,
semantic ground truth, or human approval. `humanReview` and `accuracyScore`
remain `null` throughout.

The source bytes are pinned to commit
`36dbbe5597de496b9807b0e52ef232ceca1df89e`. The candidate skill bundle hash is
`837358d2689890ec663dfebac57092c369db02d6e75a9229953776b1b5f2e29b`.
Bundle hashes cover the installed skill's non-test files as sorted relative
paths plus file bytes; an individual `SKILL.md` hash is therefore different.
The manifest deliberately excludes native workspace paths, prompts, and
session identifiers.

Copilot's GAN run did not publish an artifact: both permitted validator repair
rounds ended in invalid JSON. Its current draft is retained under
`failed-drafts/` with a `.txt` extension so it cannot be mistaken for a valid
WorkflowDocument. A third repair was started by the host after the allowed
budget and was cancelled; the preserved bytes are that unvalidated current
draft, not a successful second-round result. It is excluded from semantic
before/after conclusions.
