# Changelog

Newest first. Entries before the 2026-09-18 removal of the static analyzer
(everything below "Unreleased — native workflow only") describe the retired
static analyzer; their figures are historical and are not rewritten. Current
truth lives in [docs/STATUS.md](docs/STATUS.md) and
[docs/VALIDATION.md](docs/VALIDATION.md).

## 0.3.0 — pilot readiness (Campaign 2)

Tooling the owner and an operator need to review the reference packet, freeze a
campaign and run, seal, review and summarize the held-out pilot. Nothing here
reviews a reference, runs a model or decides the pilot: every committed
decision file is a pending template, `pilotApproved` is the constant `false`,
and summaries say "computed against the predefined targets; not an approval".
0.3.0 follows 0.2.0, which shipped on 2026-09-25. Finding IDs refer to the
2026-09-25 takeover review; N and J items are the Campaign 2 specification's
own observations.

Evaluation pipeline:
- Owner decisions are plain Markdown files in `evals/workflow/decisions/`:
  eight pending task templates, `run-policy.md` and
  `development-adjudication.md`. `python tools/workflow_eval.py check` prints
  every problem as `path:line: LEVEL section: message` and ends with "ready to
  freeze" or not; `template` (exclusive, `--second`, `--show`, `--init-all`)
  and `context` (a gitignored sheet with each quote verified against the
  pinned bytes) support the review. Unknowns and non-defects get stable IDs,
  and the Flax placeholder argument must be replaced before a freeze (EVAL-2,
  N2, N3).
- `freeze --campaign C [--write]` checks every precondition (ready files,
  resolved second-review disagreements, verified corpus, exact quotes, covered
  paths, no reference leakage or machine paths in prompts) and writes the
  frozen references, reference set, run policy, 16 prompts and `freeze.json`
  exclusively; `referenceRevision` is the reference set's hash. `check-frozen`
  re-derives the current campaign byte for byte and guards the held-out
  manifest fields. The host invocation is frozen per host, outside the hashed
  prompt (EVAL-6, N5).
- Candidate snapshot v2: `python tools/workflow_candidate.py --campaign C
  --build-vsix` builds the VSIX itself on a clean tree, checks its payload,
  media and version and the skill payload against `git ls-files`, and pins the
  schema, manifests, viewer bundle, extension manifest and `freeze.json`
  (no longer the ignored `out/extension.js`). `--output` writes a development
  snapshot, which summaries refuse (CRIT-9).
- Pilot runs: `plan`, `run-prepare` (a fresh workspace per run under
  `$MLVIEW_PILOT_DIR`, outside every Git work tree and instruction file, with
  only the pinned sparse paths and the installed skill), `run-finish` (a
  sealed `record.json` with every evidence hash; `--amend` keeps the previous
  seal), `review-template` and `check` for `session.md` and `review.md`
  (N6, N8, J2, J3).
- `summarize --stage 1|all` reads every frozen input and the helper at the
  candidate commit, refuses integrity failures, counts protocol violations as
  invalid runs, and computes T1-T6 with intention-to-treat denominators, the
  three qualified-claim policies, per-host targets, paired baselines and the
  documented go/stop/incomplete/invalid decision; `--record` writes the stage
  summary exclusively. The unverified legacy `summarize`, `baseline-plan` and
  test-only placeholders are removed (EVAL-1, EVAL-7). `pilotTargets` gains
  `knownUnresolvedQualified` (N1).
- Smoke reviews are bound only to host-less ledgers (EVAL-5); replayed
  citations use the helper's line and notebook semantics and require an
  integer `endLine` (EVAL-15); `development-plan --output` is exclusive and
  `review-packet` needs `--force` to replace its HTML (EVAL-4).
- `tools/evidence_lock.json` pins every byte under the evaluation evidence
  roots, `tools/evidence_lock.py --add` appends new dated records, and
  manifest tests re-hash the recorded native artifacts (EVAL-17). Required
  source paths are computed from entrypoints, anchors and frozen sources, never
  parsed from arguments (J1).

Corpus:
- The mmdetection sparse list adds the five root-anchored config files the
  registry task needs (EVAL-3). `fetch_workflow_repos.py --verify [--json]`
  checks each checkout in place (HEAD, clean state, sparse list, blob-exact
  covered files) without changing it; `--update-sparse` applies a changed list
  to a clean pinned checkout. The analyzer-era `.mlview-pinned-sha` marker is
  tolerated when it holds the pin (EVAL-16), and new checkouts turn off
  `core.autocrlf` (J5).

Distribution and CI:
- One portable-file filter keeps `.DS_Store`, editor and OS files out of the
  skill identity, ZIPs, plugin copy and installs (EVAL-8). The installer
  records `.mlview-install.json`, upgrades unmodified files, refuses local
  edits unless `--force`, and doctor explains symlinked locations (SKILL-15).
- `vsix_check.py` reports a missing working-tree source instead of skipping
  and gains `--payload-only` (EVAL-10). CI adds Python 3.14 and Node 24 and 26,
  runs the native sh and PowerShell drivers, and has a conditional
  `claude plugin validate --strict` job; with `MLVIEW_REQUIRE_CLAUDE_CLI=1` a
  missing Claude CLI fails instead of skipping (EVAL-11). The PowerShell
  drivers choose a Python 3.10+ interpreter like the sh drivers (EVAL-13).
  `requirements-dev.txt` pins `pytest==9.1.1` and `jsonschema==4.26.0`
  (EVAL-12), and `check.py --skip-build` says what still rebuilds (EVAL-14
  remainder).

Helper:
- A cited notebook containing `NaN` or `Infinity` is refused with
  `notebook_cell`, as the viewer cannot read it; the conformance corpus grows
  from 65 to 70 cases (NaN and duplicate keys in notebooks, and three
  `publishedAt` profile pins: lowercase `z`, a leap second, a nine-digit
  fraction).
- Every helper error and warning code (58 and 2) is catalogued in
  `docs/WORKFLOW_CONTRACT.md` and, compactly, in the skill's bundled contract;
  a test fails when a code is added without documentation.

Round 1 review fixes (finding IDs refer to the Campaign 2 round 1 review):
- `check-frozen` counts a final summary only when it is a summary
  `summarize --record` wrote for the campaign's `candidate.json` and
  `freeze.json`; any other file named like a summary is reported and never
  switches the re-derivation off. The hash-only check still binds `freeze.json`
  to the candidate and the ledgers to their frozen bytes, checks the copied
  `supersedes`, `developmentAdjudication` and `tasksManifest.sha256` fields
  (against the commit that added `freeze.json` when the Git history is
  complete), and names each changed decision file (INTEGRITY2, INTEGRITY9,
  OWNERUX1-4). A campaign whose candidate or summary was ever committed needs
  an owner invalidation to be superseded, and the capture refuses a campaign
  that already holds a summary or invalidation (INTEGRITY7).
- `summarize` and `run-prepare` bind every frozen reference and the run policy
  to the decision files and ledgers at the candidate commit (INTEGRITY3); a
  Stage 1 summary unlocks Stage 2 only when it has the recorded format and a
  re-computation from the sealed evidence gives the same `go` and run hashes
  (INTEGRITY4); the development-adjudication gate uses the full checker
  (INTEGRITY6).
- `run-finish` compares the workspace with the pinned bytes recomputed from the
  corpus, records paths where `workspace-before.json` differs, reports Claude
  Code's `.claude/settings.local.json` as a host file instead of invalidating
  the run, counts MLView files in a baseline, and writes `finish-state.json` so
  a deleted `record.json` is never sealed again with other session facts
  (INTEGRITY1, INTEGRITY5, STATS1-4, STATS1-5). `summarize` checks the sealed
  workspace lists and the amendment chain against the hashed evidence
  (STATS1-2). Every `run-prepare` attempt is appended to
  `$MLVIEW_PILOT_DIR/preparations.jsonl`; a failed attempt is retried only with
  `--retry "<reason>"`, which keeps its evidence (INTEGRITY8).
- Baselines are held to the policy's model and reasoning, not the skill
  invocation (STATS1-1); unreviewed baselines show no paired difference and
  block `--record` (STATS1-3); the early-stop bound skips unreviewable runs
  (STATS1-6); split claims refuse leading zeros and repeats (STATS1-7);
  `disputedDenominatorItems` lists disputes on essential and runs-must-state
  flags (STATS1-9); Markdown percentages are floored (STATS1-10). Machine
  paths such as `D:/` are refused in session values, amendment reasons and
  summaries (INTEGRITY11). Summaries and review templates cite README sections
  by heading instead of stale line numbers (SPECDOCS1-1).
- Owner files: second reviews get their own ID space and their additions must
  be resolved, and a second review by the primary reviewer is an error
  (OWNERUX1-1, INTEGRITY10); an unindented wrapped line or a mistyped heading
  gets a message that does not lead to deleting a decision (OWNERUX1-2,
  OWNERUX1-10); owner notes and CRLF line endings keep a pending file valid in
  CI (OWNERUX1-3); the no-skill prompt refuses publishing words (OWNERUX1-5);
  templates cite document sections (OWNERUX1-6, SPECDOCS1-2); messages show the
  typeable ` -- ` separator and explain a single `-` (OWNERUX1-7); a sparse
  mismatch names `--update-sparse --repo <name>` (OWNERUX1-8); a replaced
  `Anchors:` list notes each dropped proposed anchor (OWNERUX1-9). The pending
  decision files were regenerated from the templates.
- `--update-sparse` refuses when the pinned tree could not be listed or
  classified (DISTCI1-2), a relative pilot directory is made absolute before
  packaging (DISTCI1-1), and the protocol, README and guide wording now match
  the tools (SPECDOCS1-3, SPECDOCS1-4, SPECDOCS1-5).

Round 2 review fixes (finding IDs refer to the Campaign 2 round 2 review):
- A retry is allowed only if the prompt was never sent, as the run policy
  defines it. `session.md` gains `Prompt sent: yes | no`; `run-finish` refuses
  `no` for a timeout, a `no-publication` or `repair-budget` failure, a
  completed session or a transcript that contains the prompt. `run-prepare
  --retry` verifies the sealed record and refuses an attempt that timed out,
  failed after the prompt, does not say `Prompt sent: no`, or completed at any
  point of its amendment chain; `summarize` marks a run invalid when an earlier
  attempt sent the prompt. Every earlier attempt is verified like a current
  record and reported: `runs[].attempts`, `failures.earlierAttempts` and
  `inputs.runs[].earlierAttempts`, which a committed Stage 1 summary binds
  (INTEGRITY2-2, INTEGRITY2-3, SPECDOCS2-1).
- A recorded summary is final: `summarize --record` refuses a summary file
  that was ever committed, `run-prepare` and `summarize --stage all` refuse a
  Stage 1 summary that differs from its first commit or was committed more
  than once, and `check-frozen` fails when a committed stage summary is
  missing, changed or re-added (INTEGRITY2-1). `run-prepare` re-computes
  Stage 1 even in a pilot directory without its evidence (SPECDOCS2-4).
- `check-frozen` binds `freeze.json` to `candidate.json` for every captured
  campaign, with or without a summary (SPECDOCS2-2), prints a `not verified`
  line naming the history checks it cannot run in a shallow clone or without
  Git, and the Python CI jobs fetch the full history (the integration jobs'
  shallow checkouts only print those notes) (INTEGRITY2-4, SPECDOCS2-3). It
  names a decision file added after the freeze, which `check` notes
  (OWNERUX2-5).
- Owner files: a `#` line is a comment in the wrong form, reported under its
  section without dropping the lines around it, unless it looks like a heading
  (OWNERUX2-1); a second-review addition is adopted with
  `<their id>: adopted as <your id> -- <why>`, recorded as `adoptedAs`, so
  summaries count it inside the denominators (OWNERUX2-2); the high-severity
  defect note stays until a second-review addition is adopted as that defect
  (OWNERUX2-3); a wrapped line after a blank or note line, or a wrapped
  resolution containing `: `, is told to indent (OWNERUX2-6); the CI guard for
  pending files ignores what the grammar ignores (OWNERUX2-4).
- The Sensitivity section's macro and leave-one-task-out percentages are
  floored like the other Markdown percentages (SPECDOCS2-5).

Round 3 review fixes (finding IDs refer to the Campaign 2 round 3 review):
- The history checks read every version a file ever had in the history
  reachable from HEAD, merges included, and count distinct contents rather
  than adding commits. A recorded summary replaced through a merge, a freeze
  recorded inside a merge and then edited, and a removal hidden behind a merge
  are found; an ordinary pull-request merge is not a finding
  (INTEGRITY3-1). `candidate.json` is final once committed like a summary, and
  capture refuses a shallow or partial clone and a campaign whose candidate
  was ever committed (DISTCI3-2). A partial clone, or a history Git cannot
  read, is reported as not verified instead of "never committed", and a
  supersede refuses there (INTEGRITY3-5).
- A committed campaign is never erased: check-frozen fails when a campaign
  that was ever committed is missing, also with a pre-freeze `tasks.json`, and
  requires every earlier campaign to be reached through `supersedes`; the
  freeze refuses while the history holds a campaign `tasks.json` does not name
  (INTEGRITY3-2). Two merged recordings of one summary are settled by the
  owner's `invalidation.md` and a new campaign, after which the finding is a
  note.
- `Prompt sent: no` is refused against sealed evidence: repair rounds above
  zero, a published `pilot.mlview.json` or a skill draft in the workspace at
  `run-finish`, a captured artifact or a sealed transcript with the prompt at
  `--amend` (which also never drops or replaces a sealed transcript), and any
  of these in `run-prepare --retry` and in `summarize`'s check of earlier
  attempts, which report why an attempt counts as sent (`sentBecause`)
  (INTEGRITY3-3, STATS3-1). `run-prepare --retry` refuses a retry beyond the
  policy's infrastructure retries (STATS3-2).
- With the same tools, a committed Stage 1 summary must equal the
  re-computation in every field and its Markdown the rendering of its JSON
  before Stage 2 is prepared; check-frozen checks the rendering while the
  summary names the running `tools/workflow_pilot.py` and otherwise notes it
  (INTEGRITY3-4).
- Summaries: baseline entries keep their failure, invalid reasons, warnings
  and earlier attempts (`baselines.earlierAttempts`), rendered in the
  Baseline comparison (STATS3-3, SPECDOCS3-1); a per-host miss names the host
  and each host gets its own early-stop bound (STATS3-4); a pending run shows
  no paired difference (STATS3-5).
- Owner files: only a section kind with at most one ID after a single `#`
  looks like a heading, and the error says the lines after it were not read
  (OWNERUX3-1, SPECDOCS3-2); a resolution that names the primary's own
  addition or starts like `adopted` must use the adoption form (OWNERUX3-2);
  a case-only duplicate resolution is an error (OWNERUX3-3); `check` keeps a
  primary with a late second review `frozen in` its campaign and lists that
  review's disagreements as notes for a new campaign, and check-frozen says
  to remove the late file to keep the campaign (OWNERUX3-4); a byte change
  after the freeze names the restore command and is labelled `changed after
  the freeze` (OWNERUX3-5); the pending-file CI guard ignores edited or
  removed tool notes (OWNERUX3-6); adopting a candidate item explains the
  non-adoption form (OWNERUX3-7); the high-severity note suggests an unused
  second-review defect ID (OWNERUX3-8); a mistyped resolution ID lists the
  items still open (OWNERUX3-9).
- Docs: campaign commits reach main by a merge commit or fast-forward, never
  a squash or rebase merge (DISTCI3-1); the root README no longer calls main
  unmerged (SPECDOCS3-4); the CI history wording is exact (SPECDOCS3-5).

Not in this version: the owner's reference review and freeze, the development
adjudication, any native session and the pilot itself (the owner's
decisions); second-review tooling for run reviews and the development
adjudication; SKILL-16 (identity framing; `files` is documented as part of the
identity); N9 (notebook nesting beyond Python's recursion limit); DOCS-7/10/17;
a CI job that fetches the corpus; blinded or randomised review order;
hash-pinned development dependencies; automatic transcript capture.
`development/native-reviews/README.md` is a frozen record and still shows
`review-packet --output` without `--force`, which a regeneration now needs.

## 0.2.0 — reliability and trust (Campaign 1)

Every manifest now says 0.2.0, the first version number distinct from the
analyzer-era 0.1.0 that `main` shipped before it. It was released on
2026-09-25, when the owner squash-merged PR #9 into `main` (`d99904f`), and
also carries the two "Unreleased" native entries
below, which never shipped under a version number. Finding IDs refer to the
2026-09-25 takeover review.

Open panel and freshness:
- An open panel follows the artifact file: it shows the newest valid revision
  on disk and no longer refuses every later revision after rejecting one;
  Refine continues from the revision actually in the file (CONTRACT-2 = EXT-1 =
  CRIT-2, EXT-11, EXT-12, NEW-1).
- A revision whose sources changed is shown as a historical diagram with a
  banner naming the changed files; only jumps into those files are blocked. A
  revision the panel saw superseded (for example restored from git) is refused
  until **MLView: Open Generated Diagram** is re-run. Banners name each case and
  carry no absolute paths (EXT-18, CRIT-7).
- Freshness uses the saved bytes on disk, as the helper does, so UTF-8 BOM and
  CRLF files no longer look stale while open. Unsaved editor changes are
  reported separately and block only a jump whose cited lines moved. Open files
  are matched by real path, so symlinked roots are handled (an automated test
  on macOS); Windows drive-letter case matching is implemented and unit-tested
  but has not run on Windows (EXT-7 = CONTRACT-5, EXT-2, SKILL-9, EXT-9, EXT-13
  functional part).
- Both high-contrast themes use the high-contrast palette (EXT-4, RENDER-5), and
  a restored panel opens only a `*.mlview.json` inside the workspace (EXT-16).

Refinement:
- The copied prompt has a host-written header and puts all artifact text in one
  escaped JSON data block, so artifact text cannot forge prompt lines. It names
  the artifact path portably and states VS Code Restricted Mode in an untrusted
  workspace (EXT-6, EXT-17, CRIT-8).
- Five explicit intents (Explain, Expand, Challenge, Trace, Custom), with the
  same meanings in the skill; Explain never publishes (EXT-6, CRIT-8).
- The Refine composer keeps its intent, text and selection across refreshes and
  closes only after the prompt was copied (VIEWUI-4).

Viewer:
- A panel renders once on open and once per new revision; refreshes keep the
  viewport, and a reopened panel restores it (VIEWUI-2 = EXT-3, VIEWUI-3).
- Export and Copy scope report success only after VS Code saved or copied. A
  PNG too large for the canvas is scaled down to fit; if it still cannot be
  drawn, the viewer asks you to save the SVG instead (copying a PNG falls back
  to copying the SVG) (CRIT-5, RENDER-3, VIEWUI-10 = EXT-5).
- A document without findings says the assistant recorded none instead of a
  clean result; workflow-level findings survive stage filters and scopes
  (VIEWUI-1, CRIT-3).
- Analyzer-era surfaces (pipeline chooser, Concerns, "Issues" wording, rule
  grouping, limitation chips) are gone from authored diagrams. Scope-to-node
  and search work by node ID, cited file and quote; notebook evidence names its
  cell (VIEWUI-5 to VIEWUI-8, VIEWUI-11 to VIEWUI-15).
- A rebuild during hover no longer leaves the diagram dimmed; reduced motion
  keeps hover-intent delays (RENDER-1, RENDER-19). Finding connectors go only to
  nodes the author named; distinct IDs get distinct element ids; exports use
  the full title and escape invalid characters (RENDER-4, RENDER-6, RENDER-7,
  RENDER-8 = CONTRACT-14, RENDER-11).
- Edge routing runs its cheap geometric test first: identical layout, faster
  large diagrams in the jsdom benchmark (RENDER-2).

Skill and helper:
- MLView's own artifacts, drafts and installed skill are never fingerprinted,
  so a refinement is no longer stale the moment it is published; citing them is
  an error, and `--output` must end in `.mlview.json` (SKILL-2, CRIT-1).
- Drafts omit `verification`; a stale fingerprint names the file and the fix
  (SKILL-3). Binary and non-UTF-8 inspected files can be listed, and files over
  8 MiB are listed without a fingerprint (CONTRACT-6).
- The helper refuses what the viewer cannot open: a `null` node parent or
  verification block, unpaired surrogates, drive-letter paths, NUL in
  entrypoints and artifacts over 2 MiB (CONTRACT-1, CONTRACT-3, CONTRACT-4,
  CONTRACT-10, SKILL-21).
- Errors say what to fix: relative drafts resolve against `--workspace`,
  distinct draft errors with JSON line and column, the published revision in
  `revision_conflict`, the cited lines in `quote_mismatch`, reachable
  `revision_id_reused`, and a JSON `internal_error` instead of a traceback
  (CONTRACT-15 = SKILL-14, SKILL-4, CONTRACT-7, SKILL-11). Published files keep
  their permissions; notebooks are parsed once (SKILL-12, SKILL-18).
- SKILL.md treats repository and artifact text as data, documents the intents,
  what `--workspace` must be, recovery from helper errors and what to report;
  the bundled contract lists every field (CRIT-8, EXT-6, SKILL-5, SKILL-6,
  SKILL-20, CRIT-6).

Contract, checks and distribution:
- `contracts/conformance` holds 65 self-contained cases run through the
  schema, the helper and the extension, plus a helper-publish, viewer-load
  round trip; the extension now matches the helper on notebook cells, exact
  quotes, code-point lengths and empty parents (CONTRACT-8 = SKILL-17,
  CONTRACT-9, CONTRACT-10, CONTRACT-11, CONTRACT-4).
- New regression suites cover revision lineage, the refine wedge with the real
  helper (required by the e2e gate), the host protocol and bootstrap, export
  payloads, recorded artifacts, bundle hygiene and a routed-geometry golden
  (EXT-8, VIEWUI-17, RENDER-12).
- `tools/verify.py` also checks the marketplace and viewer version literals
  (CRIT-4). The Claude plugin's GitHub install command names the real
  marketplace (DOCS-1 = SKILL-8). Dead export and `showOutput` code is gone
  and the development launch configurations open the repository root
  (EXT-14, EXT-15, DOCS-15).
- CLAUDE.md is the tracked agent guide and AGENTS.md is removed; current docs
  describe the new panel, freshness and refinement behaviour, and more of them
  are link-checked (DOCS-3 to DOCS-6, DOCS-9, DOCS-11, DOCS-13 to DOCS-16,
  DOCS-18, DOCS-19).

Fixes from the first review of this campaign (finding IDs from the round-1
review): re-running Open no longer turns an edited draft's historical banner
into a rejection (LINEAGE1-1); a deeply nested artifact is a parse error
instead of a stuck "checking" status (LINEAGE1-2); a direct child of the shown
revision is always adopted (LINEAGE1-3); each disk event gets fresh read
retries (LINEAGE1-4); banner and prompt text from the artifact is single-line,
bounded, and escapes C0 and C1 controls, bidirectional controls, line and
paragraph separators and Unicode default-ignorable characters (SECURITY1-1,
SECURITY1-2); restored and opened paths are normalised before the workspace
check, and refine selections must have a string kind (SECURITY1-3,
SECURITY1-4); links and aliases of MLView files are never fingerprinted
(SECURITY1-5); the helper refuses to edit a published artifact in any case
spelling, reports a missing `--workspace`, more than 2000 tracked files, deep
nesting, an oversize artifact and a missing revision ID with actionable codes,
and checks dates the same way on every Python (HELPER1-1 to HELPER1-6,
SECURITY1-6, SPECDOCS1-5); a scoped viewport and an open composer survive a
webview recreation, a refusal does not outlive its revision, the scope picker
names notebook cells and searches phases, focus mode survives re-renders, and
cards say "step" and "finding" (WEBVIEW1-1 to WEBVIEW1-7, LINEAGE1-5); new
corpus cases pin changed inspected files, entrypoint drive letters, BOM
notebooks and Latin-1 sources (SPECDOCS1-1 to SPECDOCS1-3).

Fixes from the second review of this campaign (finding IDs from the round-2
review): a Refine refusal about a missing or unreadable artifact file is
cleared once the file is read again, even when the revision is unchanged
(LINEAGE2-1); a hand-edited value the viewer's checks used to crash on (an
object with a `toString` member) is reported as an issue, so Refine continues
from that revision instead of calling the file unreadable (LINEAGE2-2); an
artifact opened through a differently cased path on macOS opens in the
workspace folder's spelling (LINEAGE2-3); both layers treat the long s
(U+017F) and the Kelvin sign (U+212A) as `s` and `k` when deciding what is an
MLView file, as case-insensitive volumes do (SECURITY2-1); the escape set now
covers every Unicode default-ignorable character, including variation
selectors and Hangul fillers (SECURITY2-2, SPECDOCS2-1); the helper rejects
`NaN` and `Infinity`, which are not JSON, in drafts and in an existing
artifact (SPECDOCS2-3); the corpus pins the 64-level nesting bound, and both
runners read JSON the way the product does (SPECDOCS2-4); docs no longer say
evidence quotes are copied into the prompt (SPECDOCS2-2).

Not in this version: the manual live VS Code checks (HC Light, BOM files open
while publishing, symlinked roots, Windows drive letters), human semantic
review and the held-out pilot. Deferred: EXT-13's per-click revalidation cost,
EXT-10, the routing grid index, edge connectors and edge search hits,
RENDER-9/16/20, and DOCS-7/10/17 (need owner approval).

## Unreleased — trust and usability

- Clarify authored uncertainty and severity, show every evidence quote, and add
  direct claim challenges plus accessible textual relationship views.
- Coalesce edit-driven validation; guard stale results, navigation and disposal
  across overlapping source and artifact changes.
- Add targeted interpretation guides and protected incremental draft edits.
- Identify full skill bundles, diagnose installation drift, prepare separate
  matched baselines and measure synthetic renderer scale through 2,000 nodes.
- Fix native Windows draft paths and CI timing, keep source links beside the
  diagram, and support arrow/Home/End navigation across the side tabs.
- Align evidence requirements across the Python and VS Code validators;
  correct synthetic benchmark references and authored search/Outline wording.
- Preserve WorkflowDocument 1.0 and historical evaluation records. Human
  semantic review and broader native-host/platform validation remain outstanding.

## Unreleased — native workflow only

- Remove the Python static analyzer, CLI, rules, caches, static reports, MCP
  services, pre-commit hook, GitHub action, and static extension commands.
- Ship the active-assistant MLView skill and WorkflowDocument viewer only.
- Move retained ML example sources into evaluation fixtures without changing
  recorded native outputs, evidence quotes or their hashes.
- Replace analyzer release gates with native helper/viewer/distribution checks.


The older dated entries below were moved here from `docs/STATUS.md`, each
condensed to what changed and the numbers that were measured at the time. The
long-form reasoning behind them is in the historical `docs/CONTRACTS.md` and
`docs/ROADMAP.md`.

**Most entries below were written before CI could confirm them.** GitHub Actions
billing was blocked at the account level for the hardening rounds, the
consolidation and the recall campaign, so every job came back unstarted and each
of those entries is a measurement from one machine. The block went with the
repository going public on 2026-09-15: the matrix has since run green over the
legacy tree the consolidation entry describes — thirteen jobs, run 34986234828 and run
34986239243, and thirteen again over its review fixes, run 35001150997 and run
35001153856. Where an older entry quotes a CI run id, that run predates the
block.

---

## Unreleased — review and public readiness (2026-09-18)

- Hardened artifact paths, timestamps, malformed-input handling and publication
  errors, with matching Python and TypeScript checks.
- Reduced repeated parent traversal, source reads, hashing and graph counting.
- Added symlink-safe skill distribution and a shared MIT license payload;
  pinned the VSIX packager and adopted SPDX wheel metadata.
- Fixed evaluation prompt/pointer validation and Windows review paths, and
  made failed wheel builds fail their gate.
- Updated contribution forms and documentation, preserved upstream evaluation
  license notices, and enabled GitHub secret scanning and push protection.

See the [review and validation record](docs/PUBLIC_READINESS_REVIEW.md).
Human semantic review and the held-out pilot remain pending.

---

## Unreleased — native LLM workflow (2026-09-16–17)

MLView now supplies a portable skill that asks the active assistant to interpret
source and configuration, then publishes a cited semantic artifact for the
interactive VS Code viewer. The default workflow follows the user's corrected
intent; the existing static analyzer remains available as a legacy path.

- Added WorkflowDocument 1.0, exact evidence and inspected-file fingerprints,
  bounded validation/repair, guarded atomic publication, and revision lineage.
- Added **Open Generated Diagram**, custom phases, groups/cycles, notebook
  evidence, source freshness, refinement prompts, and SVG/PNG exports.
- Added shared and Claude skill distributions; Claude's old automatic static
  hooks are now opt-in, and static VS Code entrypoints are visibly labeled.
- Added node/edge/finding refinement intents, visible scenario context and
  stable-ID preservation guidance in prompts copied to the native assistant.
- Fixed authored diagram selection being lost when VS Code recreated the
  webview after source navigation. State is saved before navigation and retained
  during bootstrap; regression coverage includes immediate webview destruction.
- Added a read-only installation doctor, deterministic skill ZIPs, extracted
  helper checks, and CI distribution artifacts for both host layouts.
- Added eight development scenarios and the protocol for a 72-run held-out
  pilot. The pilot and human semantic adjudication are outstanding.

See [implementation and local verification](docs/LLM_IMPLEMENTATION.md) and the
[native-host integration log](docs/demo-logs/2026-09-16-llm-workflow.md). Local
verification and revision-specific remote CI are separate evidence; historical
static accuracy numbers do not measure LLM understanding.

---

## Unreleased — research review of coverage and accuracy (2026-09-16)

Documentation only; no analyzer, viewer or host code changed. Seven research
passes over the shipped rules, the 158-program corpus and the 37 pinned public
repositories, written up as [`docs/RESEARCH_COVERAGE_ACCURACY.md`](docs/RESEARCH_COVERAGE_ACCURACY.md)
with a 120-entry bibliography in `docs/research/sources.md`.

- **Baseline reproduced** before anything was proposed: 80.4 % recall (72.5 %
  visible above the 0.60 confidence floor), 100 % precision, graph fidelity
  91.9 %, 706 public-corpus findings with 0 adjudicated false positives.
- **Every one of the 107 missed labels classified** into seven causes, with the
  two smallest IR changes (identity through a subscript or a shape-preserving
  method, and HuggingFace output objects) worth 22 of them.
- **Three defects in shipped rules found by measurement**, each with a
  reproduced fixture: `keras.Model.predict` tagged as hard labels (an `MLV306`
  false positive and an `MLV305` false negative at once), `GroupShuffleSplit`
  and `StratifiedGroupKFold` swapped in `MLV106`'s shuffle table, and
  `MLV803`'s `torch.load` arm accusing a default that torch 2.6+ no longer has.
  None is fixed in this entry; they are Sprint A of the document's §8.
- **37 candidate rules in three tiers**, each with its naive false-positive
  count measured by an AST sweep over the 4,467 public-corpus files before the
  rule was designed; four measure zero, and one (`MLV117`) is recommended
  against on that evidence.
- **The gate cannot yet accept a new rule**: the corpus labels exactly the 36
  shipped codes, so the first run of any new rule fails the ratchet on every
  program it fires on. The document's §7.1 proposes the adjudication step that
  fixes that.

---

## Unreleased — consolidation and recall (2026-09-15)

One campaign, three strands: make the tree say one true thing about itself
(**C1–C9**), close the largest known recall families (**R1–R5**), and fix what
the campaign's own review confirmed. It is built on the hardening base — the
158-program labelled corpus, the pinned public corpus and PR #4's 92 fixes are
underneath everything here, which is why several figures below are *lower* than
the ones the same items measured against a smaller corpus.

### Consolidation

- **C1 · Contracts v1.1.** `docs/CONTRACTS.md` is rewritten as one coherent
  document rather than a v1.0 body with a hundred-odd amendments bolted to the
  end of it: every amendment is folded into the section that owns its clause,
  including the hardening rounds' §11.50–§11.61, and an amendment index says
  where each numbered item went. The amended v1.0 is archived verbatim under
  `docs/archive/` so no decision record is erased.
- **C2 · The VSIX analyzer copy is a build artifact.** `vscode-extension/core`
  is gitignored and written by `vscode-extension/tools/sync-core.mjs`, which
  `compile`, `pretest` and `vscode:prepublish` all run. `claude-plugin/vendor`
  stays **tracked**, and for a reason rather than by omission: a marketplace
  install copies the plugin directory verbatim off a git ref, so for that host
  what git holds is what the user runs, while a VSIX is built from a working
  tree. `tools/sync-core.py` gained a `generated` flag, `tools/verify.py`'s
  `vsix` row is strict, and a test asserts the directory is untracked.
- **C3 · No source file over 750 lines.** Every one that was is split into
  cohesive modules under 600, with re-exports so no importer changed and
  **byte-identical outputs**: `tools/perf_equiv.py --expect-same` against a
  reference tree of `origin/sprint5` after each of the thirteen analyzer splits,
  an AST comparison finding all 451 definitions byte-for-byte the reference's,
  and — for the viewer's five CSS layers — the minified concatenation identical
  at 73 127 B before and after. That proof was taken **at the split**, against a
  tree recall had not yet touched; recall then re-based the graph deliberately,
  so `--expect-same` is no longer the right question to ask of this commit and
  `--demo` byte parity, the two accuracy ratchets and the public-corpus gate are.
- **C4 · The docs say one thing each.** `docs/STATUS.md` is a short
  current-state page; this file is the history it used to carry; `README.md` is
  trimmed to what a reader needs before they trust an answer.
- **C5 · `.workflows/` leaves the index** and is gitignored: a scratch directory
  for this project's own agent runs is not part of the product.
- **C6 · CI in two tiers**, because the repository is private and minutes are
  metered. A branch push runs the analyzer on Python 3.10 and 3.13, the viewer on
  Node 20, both host suites, the accuracy corpus and the Linux e2e table; a pull
  request and a push to `main` add Python 3.11 and 3.12, Node 22, the Windows
  e2e table, a macOS smoke job and packaging. A push that touches only Markdown
  and `docs/` runs nothing. The public-corpus nightly is unchanged.
- **C7 · `LICENSE`** — MIT, Copyright (c) 2026 realmyang. The VS Code
  Marketplace pre-flight requires one and this repository had none.
- **C8 · Four honesty fixes.** The `--framework` caveat reaches **both** hosts'
  coverage blocks, so a narrowed rule set can never be read as a cleaner project;
  `Escape` closes the legend, which needed a rung on the dismissal cascade
  §11.13 freezes rather than a line of code; the parse cache defaults to the
  **user's** cache directory rather than `.mlview/cache` inside the folder being
  analyzed (`MLVIEW_CACHE_DIR` overrides it, `MLVIEW_NO_CACHE=1` disables it);
  and SARIF output carries `fixes[]`.
- **C9 · Two runbooks.** `docs/VALIDATION.md` is the step-by-step for validating
  MLView by hand on a second machine and then publishing it — every command in
  both a POSIX and a PowerShell form — and `docs/DEMO_LOG.md` is the template the
  validator fills in as they go.

### Recall

- **R1 · `--dataflow ip` is the default.** `local` stays as the narrower
  opt-out; `--demo` output is byte-identical either way, so the frozen golden did
  not move.
- **R2 · Five more knowledge tables** — pandas, `evaluate`, Keras,
  statsmodels/Prophet and torchmetrics — so the graph stops losing the ops those
  libraries name.
- **R3 · Calls through workspace objects**, which has been the largest single
  recall family since ANA-1: construction nodes, `__call__` → `forward`,
  workspace loss classes, factory returns, carriage through dicts, tuples and
  dataclasses, `self.<attr>` across methods, and identity through
  `accelerator.prepare` / `fabric.setup` / `torch.compile`. The first two of
  those three keep their types through `ir/bindings_values._self_wrapped` rather
  than through a knowledge row asserting *position i out is argument i in* — the
  narrower claim, and the reason `WRAP_PREPARE` is deliberately absent
  (`docs/CONTRACTS.md` §19 A2).
- **R4 · Value typing.** `LOGITS` / `PROBS` / `PREDS` flow into MLV305, MLV306,
  MLV401 and MLV402, with confidence de-rated per hop.
- **R5 · The rule shapes that were missing.** Three interprocedural leakage
  walks — MLV101 through a `return`, MLV102 through a fold index, MLV103 through
  a callee, all `ip`-only — plus MLV208 learning to find its `GradScaler` by
  identity as well as by proximity. **MLV114 needed nothing**: this base's rule
  was already a strict superset of what the campaign had written for it, and the
  honest entry says so rather than claiming a fix that was not made.

### Review fixes

Confirmed by the campaign's own review, one fix each:

- **A marketplace entry that installed a directory with no plugin in it.** The
  `github` source form takes `repo` / `ref` / `sha` and **no `path`**: the
  fetched tree's root becomes the plugin root, and this repository's root holds a
  marketplace manifest and no `plugin.json`. The hosted entry is `git-subdir` at
  `path: "claude-plugin"`, and `claude-plugin/tests/test_plugin_manifest.py` now
  asserts that **every** entry's resolved directory really contains
  `.claude-plugin/plugin.json` — the class, not the instance.
- **R13 / R15 read a `return` only when it bound a name first**, so
  `return scaler.fit_transform(frame)` missed while `out = …; return out` hit.
- **R3's carriage did not compose with a parameter boundary**, which is the
  GradScaler-in-a-parameter-dict the campaign named.
- **A `file://` report click killed the keyboard.** Handing a URL to the OS
  protocol handler costs the *launching* browsing context its keyboard,
  permanently, so a hand validation of the viewer read as broken from its second
  step. The launch now goes through one named transient context, and a refused
  launch is answered at once rather than after a silence that read as success.
- **R18's MLV205 widening produced three public-corpus false positives.** The
  guard is kept; the widening is not. A high-severity claim about correct code is
  the worst outcome this product has, and the public corpus is the only gate that
  can see one nobody thought to label.
- **The `--framework` caveat did not reach the hosts' coverage blocks** —
  C8's first clause, listed here too because it was found by review rather than
  planned.

### Review round 2 — the rebuild's own review, process and docs

The rebuild was reviewed again on its real base. Five findings were confirmed
against the process-and-docs surfaces; each is fixed at its cause and, where a
check could have seen it, a check now does. The doc gate is **twenty-three
checks**, up from twenty-one.

- **The doc gate's check 22 was cited by the contract and absent from the
  tree.** `scripts/doc_claims.py` — the gate that forbids a green claim and the
  CI matrix in one breath without saying whether the matrix ran — was written
  during the first campaign and never carried onto this base, while
  `docs/CONTRACTS.md` §16.4 and §17 E28 both asserted it was running (**no CI
  job has started on this line of work at all**, which is the whole reason the
  check exists). It is back
  as **check 22** (it collided with `doc_surfaces`' check 16 before), wired into
  `check_docs.run`, and `scripts/test_doc_claims.py` now pins two things the
  first round could not: that the module is *wired in* rather than merely
  present, and that `docs/CONTRACTS.md` names no `scripts/*.py` missing from the
  tree — CONTRACTS is in `check_docs.SKIP` by design, which is exactly how a
  contract came to name a file that did not exist.
- **§7's `mlview diff` figures were three mutually inconsistent sets.** The
  prose said 25 / 15 / 8 / 31 and named `python -m mlview diff` as the authority;
  the authority says **26 / 15 / 8 / 36**, edges **27 / 22 / 1 / 28**, headline
  `+26 nodes · −15 nodes · 0 new findings · 15 fixed`, and both pinning tests had
  already been updated to say so. The section's own JSONC sketch carried a third
  set again. All three are corrected, §17 E36 stops restating a live figure, and
  new **check 23** holds §7 to `analyzer/tests/core/test_diff.py` — the one place
  the doc gate reads CONTRACTS, anchored on the `## 7.` heading so §17's errata
  keep quoting the superseded figures they exist to record.
- **`docs/VALIDATION.md` C5 named a coverage row that never appears.** A
  `--framework` run emits one coverage row and its kind is `framework_filter`;
  `framework_suppressed` appears only in the bare `diagnostics` tally, the same
  cost stated twice (§11.4 C3). A validator checking the kind would have recorded
  a fail against correct behaviour on the one row that exercises C8 end to end.
- **§4.0 prescribed `python tools/wheel_check.py --sdist`, a flag that does not
  exist.** The tool takes `--no-build` and nothing else. The line is gone and the
  gap it papered over is stated instead: **the sdist is published untested** —
  nothing in the repo or in CI builds or smoke-tests one — with the by-hand
  equivalent written out, because a version can never be re-uploaded.
- **B2 told the validator the standalone report "cannot open your editor".** It
  can, and for exactly the report Session B produces: `deepLinkPlan` returns
  `launch` for a top-level `file:` document and hands the `vscode://` URL to the
  OS through a transient window it closes after ~700 ms. Only an embedded or
  `http(s)` report copies. The row now describes both outcomes and says which one
  is the fail (silence).

Four minors went with them: §18's amendment index is total again (§7.1–§7.5 and
§10 had no rows), §2.6 C9's gate citations name the three tests that exist — two of
which read the analyzer's own declaration, while the extension's is a hardcoded
transcription and is recorded as a stated gap — §14.2 R19 says where its negative fixtures actually live, and the five
clauses §19.1 corrects now say so where a reader meets them. The stale counts
that no check reads — "24 third-party repositories with 26 shell scripts", the
VSIX row's 162 files / 110 core files — are replaced by the constant or the
command that settles them rather than by newer numbers.

### Review round 3 — the analyzer and the viewer, read against the contract

The same review read the build against `docs/CONTRACTS.md` rather than against
its own diff, and confirmed ten more. **Eight of the ten are the contract being
right and the code being wrong**: the clause was written, folded and shipped as
prose, and nothing in the tree ever asserted it — which is §16.4's stated gap
(no gate compares the contract to the build) arriving as ten defects at once.
Every one is now gated by a test that reads the analyzer's **own declaration**
rather than a transcription of it, and the clauses are folded as
`docs/CONTRACTS.md` **§19.4 A9–A19**.

- **A `--framework`-narrowed run still returned a flat clean bill of health.**
  C8 put `framework_filter` in the core and in two hosts' coverage blocks and
  never in `emit/answers_text`, the tuple the Answer Card, the MCP `answers`
  payload and the CLI `verdict:` row are all built from. On
  `samples/vision_pipeline_clean` the verdict under `--framework torch` was
  byte-identical to the verdict under `--framework auto` — *"No findings: no
  rule fired on this workspace."* — with a coverage block one screen below it
  naming five rules that did not run. The verdict now carries both admissions in
  one sentence and counts a filter in **rules**, never folded into a blind-spot
  total.
- **The viewer read two of the core's three coverage kinds**, and its own extra
  as the third. On the same project the rail said *"nothing to flag"*, drew zero
  banners, and put the whole caveat into one **287-character** generic chip. It
  now draws a 38-character chip, a clause in the coverage banner and the rail's
  clean-state caveat, and `webview/test/hardening_coverage_kinds.test.mjs`
  **parses** `core/coverage.py` so the next kind the core adds cannot drift out
  of the viewer silently.
- **Both slash-command prompts told the model to read a coverage row this host
  never renders** — `framework_suppressed` where a `--framework` run emits
  `framework_filter`.
- **A criterion reached through a dataclass field or a constructor parameter
  never earned the LOSS role**, so MLV201 / MLV202 / MLV203 / MLV205 — two of
  them high — all skipped the training step behind a coverage note. §5.3 A11 (c)
  and (d) were contractual and unimplemented; what travels is now the field's
  **identity**, not only its tag. Deliberately **not** extended to a plain
  parameter: doing so made `x.size()` resolve to `torch.nn.LayerNorm.size` and
  cost `nlp_gpt_pretrain` two dataflow edges `local` draws, and `ip` must never
  report less than `local`.
- **A dict returned from a factory did not carry its entries**, though the same
  dict written in the caller's own scope did, because the inferred half of
  `unresolved_callee` was written once instead of recomputed each IR round —
  which A12′ already said in as many words. MLV208 was the finding lost.
- **R4's value tags died at a tuple-position `return`, and its three hops were
  being spent on things that cross no object.** A per-batch helper, a collector
  and a `.detach().cpu().numpy()` tail spend four between them, so MLV305 went
  silent two *object* hops from a value that reaches `accuracy_score` with no
  argmax. A hop is now **crossing an object**; the free links have their own
  bound.
- **MLV103 fired or stayed silent on whether the caller happened to reuse the
  callee's argument name**, and a bare `return pca.fit_transform(X)` was silent
  where the two-line spelling fired — R13's third form, which R15 claims to read
  as well. A returned call contributes its operands and not its callee text, and
  §19.1 A5's ambiguity guard is narrowed to the tuple-or-list returns it was
  measured on. The precision case it exists for is pinned by name.
- **MLV111 still read `call.var`** where MLV110 had been given the one-hop name
  lookup, so a program that inverts both shuffle flags behind two factories
  reported only its MLV110 half. MLV111 requires **every** name the construction
  is bound to to read as an evaluation loader; a name may reinforce and never
  create.
- **C3's split of `analyzer/tools/gen_rule_docs.py` was lost** — 850 lines,
  while two documents claimed the 750-line inequality. Split along the line the
  rule codes already draw (253 / 333 / 323) with byte-identical output.
- **`analyzer/LICENSE` was the third copy C7 never landed**, and
  `analyzer/pyproject.toml` named no `license-files`, so the wheel a validator is
  walked into publishing carried **no licence file at all**.

**What moved on the corpus**, both readings up and both ratcheted: visible recall
72.3% → **72.5%** (`ip`) and 70.5% → **70.7%** (`local`), with MLV110's `visible`
column 21 → 22 — all of it earned by §5.3 A11 (d), measured by disabling that one
fallback and watching both numbers go back. The other fixes move no corpus number,
because the 158 programs do not spell those shapes; each is gated instead by
`analyzer/tests/core/test_campaign_review_fixes.py` — 23 tests, one per confirmed
finding, each a **pair** of programs differing only in the thing MLView should not
have cared about.

### What it measured

Over the 158-program labelled corpus, **precision stayed at 100.0% with zero
forbidden and zero unlabelled findings in both dataflow modes** — which is the
number that had to hold, because every point of recall below was bought without
one false positive.

| | before | after |
|---|---|---|
| Recall, `ip` (546 labels) | 79.1% | **80.4%** |
| Recall, `local` (546 labels) | 77.8% | **78.2%** |
| Recall, `ip`, the 515 unseen labels | 77.8% | **79.2%** |
| Graph fidelity (1166 hand-labelled ops) | 84.5% | **91.9%** |

Per rule, `ip`: MLV103 22.2% → **44.4%**, MLV208 14.3% → **28.6%**, MLV305
14.3% → **20.0%**, MLV402 27.3% → **36.4%**, MLV101 71.0% → **77.4%**, MLV102
60.0% → **70.0%**. The shipped sample pair moved together — `vision_pipeline`
54 → 59 nodes and `vision_pipeline_clean` 64 → 70 — with **no finding moved**:
all 15 keep their code, line, severity and confidence.

The cost is stated rather than hidden: the interprocedural summary pass now runs
on every unflagged run, and `tools/perf_equiv.py --bench` measures 0.76–0.84×
against an `origin/sprint5` reference on 4-, 50- and 200-file corpora. Roughly a
fifth of that is the `ip` default and the rest is R3's extra graph pass.

### Public readiness

The repository went public on 2026-09-15, and this is what that took. **No
machine is named in the tree any more**: the golden document's workspace root
moved from a real Windows home directory to the neutral `/home/mlview/MLView`,
and every artifact derived from it was regenerated with the repository's own
generators, so the golden, its two mirrors, `contracts/scope.expected.json`, the
plugin vendor copy and the webview dev page still agree and `analyze --demo` is
still byte-identical — at **45 588** bytes now rather than 46 078, because the
shorter root shortens every absolute path the document carries. Notes dated
before this round, here and in `docs/CONTRACTS.md`, quote the larger figure and
were true when written. Two path-traversal test payloads that carried the author's
username now use the `Users/someone` convention. The frozen v1.0 spec keeps its
historical path on purpose; `docs/archive/README.md` says why. A scan of every
commit on every ref found no secret and no email but git author metadata.

`THIRD_PARTY_NOTICES.md` is new and records the whole redistribution surface —
`@dagrejs/dagre` 3.1.1 and `@dagrejs/graphlib` 4.0.5, MIT, verbatim, and which of
the four artifacts carries them. The wheel is not exempt: it declares no Python
dependency but ships `emit/assets/mlview.js` with dagre inlined. `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SECURITY.md`, four issue forms, a pull-request template,
`.editorconfig`, `docs/README.md` and `docs/CONTRIBUTING-RULES.md` landed with
it, each written from the tools rather than from a template. `README.md` became a
landing page — badges, three screenshots of the shipped sample under
`docs/media/`, a quick start per host, the rule families, the measured accuracy
table and the known gaps.

`.gitattributes` gained a `diff` attribute for source extensions, which fixes a
real defect rather than a preference: `webview/src/diff/adopt.ts` embeds literal
NUL bytes as string-join separators inside git's 8000-byte binary-detection
window, so `git diff` printed *"Binary files … differ"* for a TypeScript module.
`.gitignore` gained `/.mlview.toml`, which MLView writes into its own checkout on
every e2e pass.

Six documents were corrected because the matrix finally ran: `README.md`,
`docs/STATUS.md`, `CONTRIBUTING.md`, `docs/VALIDATION.md`, the pull-request
template and this file all said, in their own words, that the CI matrix had never
run on this line of work. That was true when written and false once thirteen jobs
came back green, and the doc gate could not catch it because *"the matrix has not
run"* was the one escape check 22 implemented — so the check now also accepts a
cited `run <id>`, and the documents cite one. `docs/ACCURACY.md` §1 still opened
on the 92-program corpus; it holds 158.

**Gates, local first and then on CI.** Every figure here was measured on this
Mac (macOS 26.6, Python 3.13, Node 26) while Actions billing was blocked at the
account level; the matrix confirmed the tree afterwards, on the `public` → `main`
pull request — thirteen green jobs over Ubuntu, Windows and macOS, Python 3.10
through 3.13 and Node 20/22 (run 34986234828 and run 34986239243), both green on
their first attempt; the one fix iteration belongs to the branch's first
pull-request run, 34974162339, whose four failures were all one test-side
assumption about Windows drive letters. `sh scripts/e2e.sh` 20 steps, all green;
`python tools/verify.py --all` 10 rows; `python tools/verify.py --scopes --fuzz
200` 5 rows; `python tools/accuracy.py` and `--dataflow local` over the
158-program corpus, both PASS; `python tools/public_corpus.py run` then
`check --strict` over the 37 pinned repositories — 260 runs, 260 clean,
49 high / 276 medium / 381 low, **no new high-severity finding**; `mlview analyze --demo` byte-identical to
`contracts/graph.sample.json` at 45 588 bytes; `python scripts/check_docs.py`
**DOC CHECK OK**. Suites: analyzer 2654 passed / 9 skipped / 24 xfail, webview
599 (598 pass, 1 todo), vscode-extension 415, claude-plugin 479 passed / 7
skipped, scripts 146. Every row was run once at the rebuild and again after
the review fixes below; the figures are the second run.

### Public review round — the documented setup, the gate table, the CI claims

The first review of the tree as a stranger meets it: a clone built by following
`CONTRIBUTING.md` line by line, and every CI and accuracy claim re-measured.

**The documented setup did not run the gates it promised.** `analyzer` declares
`dependencies = []` and puts pytest and jsonschema behind a `dev` extra, so a
venv built exactly as §1 said — `pip install -e analyzer` — had no pytest, no
jsonschema, no `mcp` SDK and no `build`, and `sh scripts/e2e.sh`, the next
command on the page, answered `20 steps · 3 failed` on a correct tree. CI never
hit it because the e2e jobs install those packages by name. Every setup block in
`README.md`, `CONTRIBUTING.md`, `docs/STATUS.md` and `docs/VALIDATION.md` now
reads `pip install -e "analyzer[dev]" mcp build`, with the reason next to it, and
each names `python3 --version` first because macOS's `/usr/bin/python3` is 3.9
and the package refuses it.

**Two gate rows lied in opposite directions.** `tools/verify.py --all` turned a
missing optional SDK into `FAIL parity: CLI vs MCP — No module named 'anyio'`
and exit 1 — the one red row a newcomer saw was the one that meant nothing — so
a gate that cannot run now reports **SKIP** with the one-line fix and does not
set the exit status. `vendor: synced core` was built only on that gate's success
path, so any parity failure served **nine** rows where four documents promise
ten, with the row `CONTRIBUTING.md` sends plugin contributors to read simply
absent; it is computed first now and printed on every path. In the other
direction, `tools/wheel_check.py` exited 0 when there was no wheel to test and
both e2e drivers recorded `PASS wheel installs and runs` over a check that had
done nothing — in every e2e job this project has ever run, including the green
ones the README cites, because neither e2e job installed `build`. The tool exits
**3** for that case, both drivers record `SKIP` with the reason, both e2e CI jobs
install `build`, and `scripts/build.{sh,ps1}` says `BUILD OK — 5 of 6 steps
(wheel skipped)` rather than claiming six.

**The docs contradicted each other about CI and about accuracy.**
`docs/STATUS.md` still said, in the present tense, that Actions was
billing-blocked and that *"no claim of a green CI run is made anywhere in this
repository"* — eighty lines above its own paragraph naming thirteen green jobs,
and while four other documents named the runs. `docs/README.md`, the index every
document link goes through, ended its description of the doc gate with *"which,
on this line of work, it has not run at all"*. `docs/VALIDATION.md` told the next
validator both scheduled workflows had never run and that billing was blocked;
both are on `main` and each has been proved by dispatch (nightly run
34984606964, public corpus run 34982508080 at 260 runs, 260 clean). §16.4 of the
contract still carried *"not yet by measurement"* as live normative text. And
`docs/STATUS.md` said the public corpus had caught **four** false positives where
`adjudication.json` holds eleven and `README.md` says eleven — a factor of nearly
three on the number that is the whole argument for that gate.

**Both halves are now gated, because prose that drifts once drifts again.** The
doc gate is **twenty-five checks**. Check 22 gained its mirror: once a living
document names a run that was green, no living document may assert the matrix has
not run. Check **24** holds any prose count of the public corpus's false
positives to `analyzer/tests/public_corpus/adjudication.json`, reading
spelled-out numbers and the shape that states the figure without repeating the
noun. Check **25** holds the versions in `THIRD_PARTY_NOTICES.md` — until now the
one public-facing file no check read at all — to the packages under
`webview/node_modules`, abstaining where they are not installed. Both new checks
carry the meta-escape check 22 needed: a paragraph that documents the rule is not
a claim about the tree.

Smaller: the Python badge said 3.11+ against a `requires-python = ">=3.10"` that
CI exercises on 3.10; the hero screenshot's alt text described eight stage bands
where seven are drawn and the eighth is the one the sample does not have (which
is a feature of the viewer, so it says so now); the README credited a fix
iteration to two runs that were green first time; `docs/ROADMAP.md`, linked as
the backlog a contributor picks work from, sized that work in agent-days;
`project.md` was indexed nowhere and is now in `docs/README.md` as what it is;
`SECURITY.md`'s preferred route was GitHub private vulnerability reporting, which
is **disabled on the repository**, so step 1 is conditional on the button being
there until the setting is turned on; and `docs/STATUS.md` records, as a standing
gap, that the git history still carries the old orchestration scripts with their
absolute paths — a decision taken rather than an oversight, since rewriting
history on a public repository breaks every clone.

**Gates after this round**, on this Mac: `python scripts/check_docs.py`
**DOC CHECK OK (21 files)**; `python -m pytest scripts -q` **146 passed**;
`python tools/verify.py --all` **10 of 10**; `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; `python tools/accuracy.py` PASS in both dataflow modes;
`python tools/public_corpus.py check --strict` gate OK over the 37 pinned
repositories. **And on CI**: the thirteen jobs took this round's commit green on
the first attempt too — run 35001150997 for the seven cheap-tier jobs, run
35001153856 for the six the cheap tier excludes. Those two are the first runs in
this project's history where `wheel installs and runs` was a real check on both
drivers (`wheel-check: OK mlview-0.1.0-py3-none-any.whl -> mlview 0.1.0, 4
node(s), 2 issue(s) in a clean venv`, Ubuntu and Windows alike) rather than a
PASS printed over a step that did nothing.

---

## Hardening rounds 1 and 2 (2026-09-14)

Not a sprint. The brief both times was *"test the current implementation
extensively and carefully; besides fixing bugs, focus on coverage over all
possible ML/DL code — test against public repos, construct code that mimics real
ML/DL applications"*, and the product's standing rule decided what counted as a
failure: **a high-severity false positive on correct code is the worst outcome,
and silently misrepresenting code — a stage claimed absent, a call dropped, a
crash swallowed — is the second worst.** Both happened, repeatedly.
**104 findings fixed** across the two rounds, and fourteen contract amendments,
§11.50–§11.61.

**What the two rounds built, and left behind as gates:**

| Surface | Round 1 | Round 2 |
|---|---|---|
| Public repositories | **24 pinned repos** at exact SHAs, 90 targets × 2 dataflow modes = 180 runs; `tools/public_corpus.py` (`fetch` / `run` / `check`) and `analyzer/tests/public_corpus/` | **37 pinned repos** — the round-1 set plus thirteen, none removed — 112 targets × 3 modes (`local`, `ip`, `--include-notebooks`) = **260 runs** |
| Written ML/DL code | **77 new labelled programs, 188 source files**; the corpus goes 15 → **92** programs, 78 → **312** expected labels, 125 → **1229** forbidden labels | **66 more**; 92 → **158** programs, 312 → **545** expected, 1229 → **2327** forbidden, 614 → **1166** hand-drawn graph ops |
| Robustness | a deep-but-legal AST, a FIFO named `*.py`, a symlink to `/dev/zero`, an unreadable directory, `from x import *`, duplicate `Issue.id`s | binding shapes (tuple parameters, dict literals, `functools.partial`, factory returns), notebook magics, package walking, report escaping — `test_round2_analyzer.py` + `test_round2_core.py`, 64 cases |
| Hosts and the renderer | 16 real repositories rendered in all three hosts; every MCP argument driven out of range | the **built** viewer mounted in jsdom over 260 public-corpus documents and 158 corpus documents; every accepted `framework=` value against the rule registry (26 cases) |
| The tree itself | which selectors are advertised, which directories a tool writes into, which test files `npm test` runs — doc-gate checks 16–18 | the command lines CI generates, the exclusive rule lists a document asserts, a known gap that names its own retirement condition — checks 19–21 |

**The worst class was the largest, both times.** Round 1 opened with **five
forbidden findings** — high-severity claims about correct code that the labelled
corpus explicitly forbids — and precision **97.6%**; round 2 opened with
**eight** and **97.9%**. It closes at zero forbidden, zero unlabelled and
**100% precision in both dataflow modes**.

**Two findings were made by the integration itself, and they are why the
public-corpus gate exists.** With every round-1 fix in the tree,
`public_corpus.py check` refused the build on two NEW high findings, neither
reachable from 312 labels: **PUB-15**, MLV101 reporting a `certain` leak in a
scikit-learn example because the rebinding guard read assignment targets through
`dotted_text`, which is empty for an `ast.Tuple` — so `X, y = load_iris(...)`,
the way scikit-learn binds data, was invisible to it; and **PUB-14**, MLV102
calling a `KNeighborsClassifier` "the transformer" on a notebook cell that is
*teaching* two-fold cross-validation. Both cost nothing: every accuracy figure
identical to four decimal places in both modes.

**Round 2's own integration arrived with a red test file**, which is an honest
hand-off and a blocking one. The four it named: a `pointerdown` on the legend
started a canvas pan and took pointer capture, so the panel's close button worked
from the keyboard and not from the mouse; an unwrapped workspace-relative path
painted one answer over the answer beside it on 7 of 90 real reports; the scope
picker's unit and group rows promised the match set while the click delivered the
projection (`unit:train.train` offered 4 nodes and drew 9), fixed by running the
same `project()` the click runs — 819 ms → 101 ms on a 222-row picker over a
400-node repository; and the Issues rail saying *"No issues found — nothing to
flag"* over a run whose own banners said it had been blind. Measured over the 260
pinned documents: **122 draw the clean state, and 118 of them were drawing it
over a blind run.**

**Recall fell, then rose, and both readings are the honest ones.** Round 1 had to
report a fall — 73.1% → **72.4%** raw — because 77 of its 92 programs were new,
unseen and harder than the fifteen the rules were developed against; scored over
those original fifteen alone the same build reads **75.6%** and the whole
previous gate passes. Round 2's 66 new programs are just as unseen and every
aggregate rose anyway: `local` **72.4% → 77.8%**, visible 66.7% → 70.1%,
high+medium 64.5% → 70.7%, unseen 69.4% → **76.5%**; `ip` 76.3% → **79.1%** with
unseen 73.7% → 77.8%. Both baselines were re-recorded with `--allow-regression`
and the reason written into each file's own `note`, never by deleting a label.
No rule carries a tuned `*` any more: all 36 have at least one label in a program
nobody wrote for them.

**Round 2's closing gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0
failed, 0 skipped**; analyzer **2574 passed / 9 skipped** (2405 / 7 at round 1's
close, 2087 / 4 at the Sprint-5 close); webview **585 tests** (561, 534);
vscode-extension **404** (401, 377); claude-plugin **460 passed / 7 skipped**
(434, 373); `pytest scripts` **119 passed** (99, 74); `npx tsc --noEmit` clean in
both TypeScript packages; `tools/verify.py --all` **10 of 10**;
`tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py` **PASS** —
precision **100.0%** on 36 rules over **158 programs and 545 labels**, recall
**77.8%**, unseen **76.5%**, graph fidelity **84.5%** (985 of 1166), zero
forbidden and zero unlabelled; `--dataflow ip` **PASS** at **79.1%** / unseen
**77.8%**; `public_corpus.py fetch && run && check --strict` **gate OK** — **260
runs, 260 clean**, 36 s of wall at `--jobs 8`, slowest single run 17.9 s against
a 60 s budget, 50 high / 276 medium / 376 low, zero tracebacks, zero schema
errors. CI run 34815166539 (round 2's last push before the billing block): all 12
branch jobs green, 15m39s wall, ~87 billable minutes.

**What the two rounds did not close**, named rather than averaged away: a model,
criterion and optimizer arriving as parameters still cost a training step its
forward, loss and backward nodes; `--dataflow ip` still reports a strict subset
of `local` on one mlflow example, so `local ⊆ ip` is not yet true; Escape still
did not close the legend, because `dismissTopmost` runs the cascade §11.13
freezes; and twenty-two points of recall were still missing, largest first —
MLV208's `GradScaler` through a parameter dict, MLV305 needing a prediction to
carry `LOGITS` or `PROBS`, and a model built by a registry
(`build_from_cfg("model", cfg)`) still being untyped. The campaign above is the
answer to that list.

---

## Sprint 5 — the LATER tier of the roadmap (2026-09-10)

Interprocedural dataflow, structured fixes, one configuration surface, analysis
comparison, node-budget rollup, pipelines, cross-lane bundling, and the process
work around them. `docs/CONTRACTS.md` §11.35–§11.47 are the amendments.
`schemaVersion` stayed `"1.0"`, `contracts/graph.sample.json` never moved, and
`python -m mlview analyze --demo --json -` stayed byte-identical to it at
46 078 bytes through every wave.

**Analyzer and viewer**

- **DATAFLOW-IP** (§11.36) — `analyzer/src/mlview/ir/summaries.py` adds a
  fixed-point interprocedural pass (constructor, return, method-argument
  intersection and subscript projection summaries) behind `--dataflow {local,ip}`
  with `local` the shipped default. `local` is byte-identical *by construction*:
  every new path is reached only from `workspace.dataflow == "ip"` or from a
  non-empty `ValueRef.provenance`. Confidence is arithmetic, not a promise —
  `rules/confidence.py` weights one `cross_file` evidence `0.8 ** hops`, so
  MLV101's 0.95 prior reads 0.760 at one hop and 0.486 at three. Measured:
  recall 71.8% → **78.2%** overall and 53.2% → **63.8%** unseen, precision 100%
  in both modes, zero forbidden findings.
- **PERF-03 / CACHE become the default** (§11.39) — `DEFAULT_RELEVANCE` is
  `"ml"`, which turns the fact cache on with it. `tools/perf_equiv.py
  --expect-same` re-proved byte-identity on all three corpora. On a 501-file
  mixed corpus: 2 920 ms (`--relevance all`) → 1 237 ms cold → **547 ms warm**,
  same 148 findings. The honest cost: a default run now writes
  `<root>/.mlview/cache/`.
- **CFG-ONE** (§11.37, §11.45) — `core/config.py` is the only parser:
  `--config FILE`, else `<root>/.mlview.toml`, else `[tool.mlview]` in
  `pyproject.toml`; first match wins outright and is named in
  `workspace.configPath`. TOML wins for `disable`/`exclude`, flags win for
  `[analysis]` and `min_confidence`, every mistake is one `config_warning`.
  `mlview init` writes a commented file listing all 36 rules from the registry.
- **ANA-10** — in-Python config resolution: module-level dict literals,
  dataclass field defaults, `argparse` defaults and the chains rooted at them
  resolve to literals. Measured A/B: overall recall **71.8% → 73.1%**, unseen
  **53.2% → 55.3%**, graph fidelity 126 → **127 of 139**; in `ip`,
  78.2% → **79.5%** and unseen 63.8% → **66.0%**.
- **H5, structured fixes** (§11.42) — `analyzer/src/mlview/rules/fixes.py` is the
  only module that constructs a `TextEdit`; 31 of 36 rules are byte-identical.
  Rules opt in, every position comes from an `ast` node, nothing below the
  `likely` bucket is offered an edit, and nothing in the analyzer writes to a
  file. Finding-neutral by construction: `tools/accuracy.py` identical to the
  character with and without the field.
- **VIEW-08, `mlview diff`** (§11.38) — a separate `mlview-diff` overlay keyed on
  the §0 stable ids: per-node/edge `added|removed|changed|unchanged`, per-issue
  `new|fixed|persisting`, and a `notes[]` block naming every reason a `removed`
  might not mean "deleted". A move is not a change. Over the sample pair:
  **+26 / −16 nodes, 11 changed, 27 unchanged, 0 new findings, 15 fixed**.
- **PERF-04, rollup** (§11.46) — `core/rollup.py` makes `--max-nodes` a zoom
  level instead of a guillotine: a unit absorbs its ops, a file folds, then a
  directory, and only then the old deletion order. `samples/vision_pipeline` at
  `--max-nodes` 400 / 40 / 20 / 8 gives **54/51, 38/40, 12/18 and 7/4**
  nodes/edges with **15 issues (5 high / 6 medium / 4 low) in all four**.
- **MLV-P12, pipelines** (§11.47) — the root `pipelines[]` block plus a
  `pipeline:<entrypoint>` selector. A single-entrypoint workspace is
  byte-identical to before.
- **VIEW-04, cross-lane bundling** — `layout/channel.ts` plans one trunk per lane
  pair and nests rather than braids; `layout/bundles.ts` draws the common run
  once with a member count. Crossings per edge **3.82 → 1.96** on the 54-node
  demo and **44.55 → 30.47** on a 300-node synthetic. A bundled cable's severity
  marker is never faded.
- **HEALTH-02 grows** — `analyzer/tools/scope_gen_projections.py` generates
  rolled-up and multi-pipeline documents. It found two real divergences within an
  hour, including `exclusiveCount` disagreeing on 17 of 40 graphs; §11.47 D is
  the normative reading, and two counterexamples were promoted into
  `contracts/scope.cases.json` (three → five).

**Hosts**

- H10 multi-root: one graph per open folder (`vscode-extension/src/folders.ts`),
  the Problems panel publishing the union, `MLView: Select Active Folder`.
- The three language-model tools take the whole selector grammar, described in
  the MCP docstring's own words and asserted against it.
- H5's fix preview, VIEW-08's three comparison commands
  (`vscode-extension/src/compare.ts`), and `mlview_graph {scope: "diff"}` — a
  sixth *value*, not a sixth tool. Still exactly five MCP tools.
- H8: `PostToolUse` / `Stop` hooks under `claude-plugin/hooks/` that speak only
  when the issue set grew, at most 5 rows, under a 3-second budget.

**Process**

- CI-MACOS-01: `smoke (macos)` was red on a wall-clock *ratio* assertion that
  read 1.15x–2.50x across runs of the same commit. The delta test now asserts
  what the cache controls, as counts — `("none", 0, 501)`, `("partial", 500, 1)`,
  `("full", 501, 0)` — with wall clock held to a ceiling.
- PROC-12: `webview/test/export_svg.mjs` became the e2e table's 20th step;
  `scripts/doc_numbers.py` check 11 holds every "N steps" claim to what the two
  drivers print.
- §11.35 is an erratum, not an edit: §11.19's "54 nodes and 52 edges" predates
  REV-06 dropping the one backwards data edge. §11 is append-only.
- Review round: three new doc-gate checks in `scripts/doc_figures.py` — the
  `docs/STATUS.md` Components table against that file's own newest `**Gates`
  paragraph, any scope-battery size claim against `contracts/scope.cases.json`,
  and two documents naming different runs as "the last full green push".

**Review fixes (19 findings).** Five were high-severity false positives — MLV101
matching a split by *name* across two functions, MLV121 taking the *absent*
branch for a `reshuffle_each_iteration` it could not read, and three more — each
fixed at its source with no assertion weakened. Three defects were reachable only
from CI: a stray `.mlview` sidecar copied into both vendored cores (now skipped
by `tools/sync-core.py`), two `analyzer (py3.10)` tests asserting behaviour the
CFG-ONE fix removed, and a plugin test that was a race rather than a test.

**Sprint 5 final gates, on this Mac.** `sh scripts/e2e.sh` **20 steps, 0 failed,
0 skipped**; analyzer **2087 passed / 4 skipped** (1722 / 3 at the sprint
baseline); webview **534**; vscode-extension **377**; claude-plugin **373 passed
/ 7 skipped**; `pytest scripts` **74 passed**; `tools/verify.py --all` **10 of
10**; `tools/verify.py --scopes --fuzz 200` **5 of 5**; `tools/accuracy.py`
**PASS** — precision **100.0%** on 36 rules, recall **73.1%**, unseen **55.3%**,
graph fidelity **91.4%** (127 of 139), zero forbidden findings — and
`--dataflow ip` **PASS** at **79.5%** / unseen **66.0%**;
`contracts/validate_sample.py` green at four budgets;
`analyzer/tools/gen_gallery.py` renders **90 reports plus an index**;
`scripts/check_docs.py` **DOC CHECK OK**. CI run 34454599867: **all 12 branch
jobs green**, 7m57s wall, ~44 billable minutes.

---

## Sprint 4 — the NEXT tier of the roadmap (2026-09-09)

Adoption, the answer card, framework recognition, three rule tiers, export,
packaging and notebooks. `docs/CONTRACTS.md` §11.21–§11.34 are the amendments.

- **Sixteen new rules** (ANA-7 / ANA-8 / ANA-9, §11.26) take the registry from
  **20 to 36**: framework misconfiguration (MLV705–MLV711), training mechanics
  (MLV207, MLV208, MLV209, MLV502, MLV803) and held-out integrity (MLV106,
  MLV114, MLV121, MLV305, MLV306). The labelled corpus grew 10 → 14 programs and
  77 labels; precision stayed **100% on all 36 rules**, overall recall
  62.9% → **71.4%**, unseen 51.1% → **53.2%**. `samples/vision_pipeline` kept
  exactly its fifteen findings, so no golden was regenerated.
- **FW-RECOG** (§11.23) — four framework knowledge tables (`knowledge/tf_tbl.py`,
  `hf_tbl.py`, `gbm_tbl.py`, `hooks_tbl.py`) and Lightning hook units in
  `core/hooks.py`. Graph fidelity **86.3% → 90.6%** (120 → 126 of 139).
- **ANA-5a** (§11.23) — a call the analyzer cannot resolve is never silently
  dropped: `CallSite.unresolved_callee` mints an `unknown` op and one diagnostic
  per scope, and no emitter may claim a stage is absent without the qualification
  *"(unverified: N calls could not be resolved…)"*.
- **CI-ADOPT** — the `mlview.adopt` package stamps each finding `new` /
  `touched` / `existing` from `git diff`, `mlview baseline write` plus
  `--baseline FILE`, `--sarif FILE` (SARIF 2.1.0 against the OASIS schema),
  `tools/action/action.yml` and `.pre-commit-hooks.yaml`. Every attribution
  failure degrades to "showing everything" with a diagnostic.
- **MLV-P1** — the deterministic Pipeline Answer Card (`emit/answers.py`), first
  block of `--format summary`, four sentences in `api.digest`, a card in every
  host.
- **VIEW-07** (§11.24, §11.33) — SVG/PNG export. The mitigation landed first:
  `webview/src/render/plan.ts` returns one scene plan that both
  `render/scene.ts` and `export/svg.ts` consume, so the gate can assert one
  `<path data-edge-id>` per routed edge with byte-identical `d`. The SVG
  references nothing outside itself.
- **NB** (§11.29) — `.ipynb` ingest behind `--include-notebooks`. One notebook
  becomes one generated module under `.mlview/notebooks/`, 1:1 line counts inside
  every cell, the cell map on `Node.attrs`, and a non-monotonic `execution_count`
  de-rates MLV101 / MLV203 / MLV209 by 0.75 and says so. The VS Code host
  re-anchors squiggles onto `vscode-notebook-cell:` URIs.
- **PACKAGING** — `tools/sync-core.py` vendors the analyzer into the VSIX as well
  as the plugin, `tools/verify.py` grew a tenth row, `scripts/vsix_check.py`
  re-derives the ceiling and the bundled-core count from the tree, and
  `tools/wheel_check.py` builds the wheel and runs it from a throwaway venv.
- **PERF-03 + CACHE** (§11.28) — the relevance prefilter and the content-keyed
  fact cache, both opt-in at this point. On a 500-file synthetic
  `build_workspace` dropped **1 087 ms → 76 ms** and the whole analysis
  **2 228 ms → 693 ms**, reporting the same 51 findings; a warm run 319 ms.
  Pickling the AST or the IR was measured and **rejected** — both slower than
  recomputing.
- **HEALTH-02** — the differential fuzzer over the two `project()` ports found a
  real divergence on its first 200 cases; §11.30 made the Python behaviour
  normative and three counterexamples were frozen into the battery.
- **Process** — PROC-01 put a `**Landed` measurement note on every shipped
  roadmap item and `scripts/check_docs.py` check 12 keeps it that way; HOST-8
  moved the VSIX figures out of two documents and into `scripts/vsix_check.py`;
  PROC-10 replaced an estimated CI bill with a measured one and stated the
  rounding rule; PROC-12 wrote down that pushes go over SSH because the stored
  PAT has no `workflow` scope.
- **Review fixes (23 findings).** Two rules were judging the wrong thing (MLV709
  paired a loss with any same-file activation; MLV121 fired on
  `train_ds.take(1)`), and a whole binding style was unanalyzed —
  `ds = ds.map(...)` resolved its right-hand side against the store the same
  statement was about to write, so three semantically identical `tf.data`
  pipelines measured 7/5, 7/5 and **2 nodes / 0 edges with `diagnostics: []`**.
  All three now measure 7/5, gated per style.

**Sprint 4 final gates.** `sh scripts/e2e.sh` **19 steps, 0 failed**; analyzer
**1748 passed / 3 skipped**; webview **404**; vscode-extension **308**;
claude-plugin **324 passed / 7 skipped**; `tools/verify.py --all` **10/10**;
`tools/accuracy.py` precision **100.0%**, recall **71.8%**, unseen 53.2%, graph
fidelity **90.6%**, zero forbidden findings; VSIX **128 files, 604.57 KB**.
CI run 34320075813: 12 jobs green, 6m30s wall, ~38 billable minutes.

---

## Sprint 3 — the NOW tier of the roadmap (2026-09-08)

**The re-baseline (§11.19).** Four items landed as one graph change, because one
golden regeneration has to cover all of them.

- **ANA-1** — ops written inside a class method were dropped: `CallSite.class_ir`
  carried two different facts and `core/build.py` read the wrong one. They are
  now `class_ir` (what the call resolves to) and `enclosing_class` (what class it
  is written in).
- **ANA-2** — `self.<attr>(...)` resolved to a symbol nobody declared; it now
  resolves through the binding.
- **ANA-3** — a package `__init__` re-export resolved to nothing.
- **VIEW-01** — lane boxes are no longer normalised to the widest lane. On the
  demo the world went 2636×2484 → 1576×2630 and `fit()` **0.322 → 0.532**; worst
  lane emptiness **91% → 32%**.

`samples/vision_pipeline` grew from 45 nodes / 45 edges to 54 nodes (52 edges at
the time; 51 since REV-01 dropped one backwards data edge) carrying **exactly the
same fifteen findings** at the same lines, so `expected_issues.json` was
unchanged. Precision stayed **100%** and every recall reading was unchanged to
four decimals; graph fidelity ratcheted **66.2% → 86.3%** (92 → 120 of 139).

Also in Sprint 3: PERF-01/PERF-02 (memoised knowledge lookup, a role index and a
convergence loop, byte-identical on three corpora), **ANA-12** — the labelled
accuracy corpus, `tools/accuracy.py` and `docs/ACCURACY.md` — BUILD-01 (−38% on
the report CSS), CI-01 (`.github/workflows/ci.yml`), COVERAGE (the
`single_file_analysis` / `untagged_dataflow` diagnostics and
`mlview.currentFileAnalysisScope`), RAIL-GROUP (`mlview_issues` `groupBy`) and
CLEANUP (`mlview.showSpeculative` and `mlview.followCursor` deleted).

**The pre-sprint audit, for the record.** Five auditors measured the shipped
prototype on 2026-09-08: **0 false positives on unseen code but roughly 26%
recall**, because class-method ops were dropped; the first screen opened a real
repo at 20% zoom; and the tool could not say "I could not check this". Those
three headlines are what Sprint 3 moved, and `docs/ROADMAP.md` (42 ranked items,
11 declined) is what came out of it.

---

## Feature pass and review rounds (2026-09-07)

**Two features on top of the first prototype**, both additive —
`schemaVersion` stayed `"1.0"` and an unscoped run emitted the bytes it emitted
before (§11.13 and the `docs/FEATURES_FLOW_AND_SCOPE.md` design).

- **Flow visibility.** Hovering a connection runs a charge along it from outlet
  to inlet; hovering a node streams its lineage, staggered 90 ms per hop.
  Direction is never decided — every router emits `points` source → target.
  `prefers-reduced-motion`, or more than `FLOW_MAX_EDGES = 120` lit edges, flips
  the canvas to a static chevron plus outlet and inlet dots.
- **Scoped views.** One selector string — `unit:` / `stage:` / `file:` /
  `concern:` / `node:` / `all`, with `depth` 0–2 — projects the whole-workspace
  document in every surface: `--scope` on the CLI, `data-mlview-scope` on the
  report, `Alt+Shift+M` in VS Code, `scope`/`depth` on the MCP tools. A scope is
  a **view, not a filter**: `stage.present`, `workspace` and `diagnostics` still
  describe the full analysis and the VS Code Problems panel is byte-identical
  while scoped. One algorithm, two languages
  (`analyzer/src/mlview/core/project.py` and `webview/src/scope/project.ts`),
  gated against each other by `contracts/scope.cases.json`.

**Integration and review fixes.** Three components that hid themselves never
actually hid (an author `display` outranks `[hidden]`); the drawn hierarchy and
the lexical hierarchy had diverged in `webview/src/layout/model.ts`, so
collapsing one group erased six nodes from another lane and the demo drew 19 of
its 46 cards; `scripts/e2e.sh` had been rewritten LF → CRLF, which is unrunnable
under dash (MLV-R2-H02); and two documents disagreed about the size of the demo
graph (MLV-R2-H05). The doc gate `scripts/check_docs.py` was created in this
pass and grew to eight checks by the end of it, each one the regression gate for
a specific incident.

---

## First build (2026-09-07)

The multi-agent build of the prototype: analyzer, viewer, VS Code extension and
Claude Code plugin, finished with two review → verify → fix rounds (48 confirmed
findings fixed) and a final verification pass. Twenty rules, the frozen
`contracts/graph.schema.json` and `contracts/graph.sample.json`, the
self-contained HTML report, the five MCP tools, and `scripts/build` +
`scripts/e2e` as the two drivers.
