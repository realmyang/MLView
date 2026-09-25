# Trust and usability campaign — 2026-09-18

The maintainer authorized execution of the [improvement recommendations](IMPROVEMENT_RESEARCH_2026-09-18.md).
This campaign implements the first trust/usability work and the interpretation
and measurement foundations that can proceed before human reference review.
Work starts from `d40d96e` on `llm-workflow`. WorkflowDocument remains 1.0.

## Implemented

- **Authored semantics:** unresolved nodes no longer become missing-step ghosts.
  The legend describes claim basis, source fingerprints and severity as impact,
  independently of certainty. Search help and finding grouping use authored
  terminology.
- **Evidence review:** node and edge inspectors show all quoted evidence;
  findings keep support and counter-evidence distinct, including findings with
  no associated node. Coverage limitations stay visible. Adjacent-evidence
  controls, source-less explanations and Challenge actions aid review.
- **Textual relationships:** the Outline enumerates directed relationships and
  basis, with All/Incoming/Outgoing/Unresolved views. Selected-node context and
  view survive an edge inspection. These views are direct topology within the
  current scope, not transitive semantic change-impact analysis.
- **Validation scheduling:** 120 ms event coalescing, one active validation and
  a queued latest rerun, immediate pending-freshness feedback, generation and
  disposal guards, serialized navigation validation and notebook-save handling.
  Awaited source opens cannot navigate after the panel or revision changes.
- **Interpretation support:** targeted rereading, on-demand training-state and
  notebook/configuration guides, explicit coverage obligations, and a complete
  minimal finding reference. Three independent development fixtures exercise
  optimizer/logging distinctions, configuration/lifecycle and notebook order.
- **Optional incremental editing:** `artifact.py upsert` updates one record in
  a validated draft. Bounded reads, duplicate-key rejection, pre/post validation,
  exclusive locks, atomic replacement and conflict checks preserve failed
  checkpoints. Published `*.mlview.json` files cannot be edited this way; copy
  one to a draft first and use ordinary revision-aware publication afterward.
- **Distribution diagnostics:** the doctor compares all distributed file bytes,
  reports missing/edited/unexpected files and duplicate installations, and
  provides remediation without overwriting edits.
- **Measurement:** [synthetic performance harness](PERFORMANCE.md), exact
  all-file candidate snapshots and a separate 24-session no-skill Stage 1 plan.
  See the [candidate protocol](../evals/workflow/CANDIDATE_PROTOCOL.md).

The shared viewer and generated Claude skill are rebuilt from their canonical
sources. Package gates retain the explicit native-only payload boundary.
Historical artifacts, review ledgers, source pins and held-out tasks are unchanged.
The initial eight-file portable skill bundle SHA-256 was
`8ec6c8158db3002aa3fee4069bcfbd91f0030af87c6000d8eab5d7b37a4b91b9`.
Its captured candidate snapshot passed a drift check. The Windows path fix
changed the current identity to
`b251ac3774a453473ccf501643f56eb2ca826640d713903666add9c9e93c5b7f`.
Neither identity denotes a frozen or approved pilot condition.

## Verification and observations

The commands and final integration results are recorded in
[VALIDATION.md](VALIDATION.md). Tests cover publication integrity, evidence
selection and navigation, relationship views, source-less findings, concurrent
validation/disposal races and package consistency.

An auxiliary Codex agent (gpt-5.6-sol) independently exercised the skill in an
isolated temporary workspace using only a fresh development source fixture and
the installed skill. It published after one schema repair, exercised one
incremental node replacement, and revalidated its result. Its interpretation
separated unscaled logger values from the accumulated return value, found no print call, and left concrete
optimizer parameter ownership and actual runtime mutations unresolved. No
target code was imported or executed. The missing finding example caused the
repair and was subsequently corrected in the quick reference. Later helper
hardening was verified with deterministic tests, not another model-quality run.
This auxiliary exercise is neither a native VS Code host test nor human
adjudication, and it does not demonstrate a measured accuracy improvement.
Its artifact had eight nodes, six edges, one finding and nine evidence anchors;
SHA-256 `50ca51cf442e2fe1f5a6a0b7f6a1c551b05cd46d513d40b0a6e1315228e69bb7`.
The exercised skill bundle was
`b7d1b761749ae884b4a16f15493c42657a71258628bee3512d84920ebe7f10cc`;
it predates the subsequent reference and helper fixes. The final helper also
validated the temporary published artifact before cleanup.

The full-size jsdom baseline demonstrates successful representation/export at
2,000 nodes but slow full-view updates. It is not a VS Code responsiveness pass;
the [performance report](PERFORMANCE.md) gives exact hashes, sizes and limits.
The first attempt to automate the live VS Code exercise stalled. The authorized
follow-up completed focused browser measurements and actual VS Code UI and
scale checks. It fixed keyboard tab navigation, authored search/Outline
wording, source-column reuse, Windows draft paths, a timing-sensitive CI test, benchmark fixture integrity,
and native/helper evidence-validation parity. See [VALIDATION.md](VALIDATION.md)
and [PERFORMANCE.md](PERFORMANCE.md). Accessibility-tree checks do not establish
a spoken screen-reader result.

## Remaining gates and later work

The [human reference packet](../evals/workflow/reference-candidates/README.md)
still needs named, source-based decisions. The scored 24/48 held-out pilot and
matched baseline sessions have not run. Candidate settings/prompts and capture
privacy policy must be frozen with those decisions. The tooling deliberately
does not manufacture human approval.

The profile now identifies routing as the first optimization target. Spoken
screen-reader checks, remote platform exercises and native-host matched
interpretation experiments remain outstanding. VSIX-contributed Copilot skills, transitive ML question
views, scenario comparison, redacted sharing and richer schemas remain later
work under the research report's decision gates. No unsupported compatibility
or semantic-coverage claim has been added.
