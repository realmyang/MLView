# Native artifact review ledgers

This directory holds provisional, model-authored review ledgers for the twelve
development artifacts: four tasks in each of Codex, Claude Code, and Copilot.
They are review inputs, not semantic scores. Every ledger must keep
`reviewStatus` as `pending-human-review`, `reviewerType` as
`model-provisional`, and all human decision fields as `null`.

`tools/workflow_eval.py` accepts a native ledger only when its task, host,
artifact path, SHA-256, revision, and request match the registration in
`../native-artifacts/manifest.json`. It also checks artifact pointers and exact
source excerpts. The older task-level smoke ledgers in `../dev-*.json` remain
restricted to their original checked-in artifacts.

Generate the local, ignored review packet after all twelve ledgers and the
three baseline notes exist:

```sh
python tools/workflow_eval.py review-packet \
  --reviews evals/workflow/development/native-reviews \
  --baselines evals/workflow/development/native-reviews/baselines.json \
  --output .mlview/quality-20260918/review.html
```

The command refuses an incomplete or duplicate task/host matrix. It validates
registered artifact hashes, revisions, requests, pointers, and exact source
quotes before writing HTML. The output has no external assets and escapes all
ledger strings. It includes source excerpts because those sources belong to
this repository; it does not include raw native-assistant transcripts or local
machine paths.

The three baseline entries are public provisional comparisons bound to a
recorded response SHA-256 and exact repository source anchors. Raw baseline
captures stay ignored and are not required to validate the public notes. A
clean checkout can therefore regenerate the packet while accurately stating
that the capture hash was recorded, rather than claiming the private capture
was independently verified.

For local review, `--baseline-captures <mapping.json>` accepts a JSON object
mapping each host to its workspace-relative capture path. It verifies each
capture's SHA-256 before embedding the escaped response text. That optional
packet is explicitly marked private and must remain ignored; the default
public packet includes only the comparison notes and recorded hashes.

Human reviewers can return decisions without editing generated HTML. Identify
each decision by task, host, and claim ID, for example
`dev-gan / codex / optimizer-ownership`, followed by a verdict and rationale.
Use `usability.<question>` for the six usability answers and identify baseline
decisions as `dev-config / <host> / baseline`. Include the reviewer name and
review date in the returned adjudication record. No reviewer identity or human
decision is inferred by this tooling.
