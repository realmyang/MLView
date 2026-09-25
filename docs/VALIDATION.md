# Validation of the native-only product

The static analyzer and its test/release gates were removed on 2026-09-18.
Current gates target skill publication, WorkflowDocument validation, viewer
interaction, workspace navigation and the distributed packages.

Run `sh scripts/e2e.sh` with Python 3.10+ and Node 20.18.1+ on PATH. On Windows
use `powershell -File scripts/e2e.ps1`. The [script guide](../scripts/README.md)
explains each gate and explicit skip options.

## Campaign 2 final check fixes — 2026-09-25

The fixes for the three regressions the final check of `e7d92c1` found
(REG-1 to REG-3; see "Final check fixes" in the
[changelog](../CHANGELOG.md)) are commit `e6d8b98` on the
`campaign2-pilot-readiness` branch, on top of `cee902b`, checked on the same
macOS machine and virtualenv as below. **These are local automated checks
only**. CI has not run on these commits, so the Python 3.10–3.14 and Node
20.18.1–26 matrix, Windows and the PowerShell drivers are unverified here.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`,
  run on the changes before their commit (the commit only rewraps one
  paragraph of the pilot README after it): **all 15 exercised gates
  passed**.
  - Python helper, distribution and evaluation tests: **842 passed, 537
    subtests passed**, none skipped.
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `python scripts/check_docs.py`: OK, 40 documents.
  `python tools/verify.py --all`: OK.
- Every changed Python file parses with `ast.parse(feature_version=(3, 10))`
  and compiles under a Python 3.10.21 interpreter.
- The 14 new regression test cases (synthetic worlds only) pass; the 4 that
  change a verdict, a reviewer or a baseline review under a summary recorded
  with other tools fail against the `cee902b` tools, as do the two updated
  tests that pin the not-an-ancestor message and the `template --init-all`
  refusal. The reviewers' honest-path rehearsal, kept outside the
  repository, ran 830 steps with no honest-path failure against a scratch
  clone of `e6d8b98`. Their REG-1 probe now holds Stage 2 after a changed
  verdict with other tools, as with the same tools; their REG-2 probe still
  expects `check-frozen` to report the ancestry, which the corrected text no
  longer claims, and a copy that follows the corrected text passes for a
  recovery through the candidate tag and through the original branch.

Every decision, review, verdict and policy value in the new tests, the
rehearsal and the probes is synthetic. No native session, human review,
reference freeze, corpus `--update-sparse` or pilot run occurred.

## Campaign 2 final round fixes — 2026-09-25

The fixes for the 36 verified findings of the campaign's final review (see
the "Final round review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `867cdf2`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on these
commits, so the Python 3.10–3.14 and Node 20.18.1–26 matrix, Windows and
the PowerShell drivers are unverified here.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **828 passed, 533
    subtests passed**, none skipped.
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `python scripts/check_docs.py`: OK, 40 documents.
  `python tools/verify.py --all`: OK.
- Every changed Python file parses with `ast.parse(feature_version=(3, 10))`
  and compiles under a Python 3.10.21 interpreter; the helper's nesting test
  was run under 3.10.21, 3.13.15 and 3.14.7.
- The 18 new regression test cases (synthetic worlds only) fail against the
  `867cdf2` tools and pass against the fixed ones. The reviewers' honest-path
  rehearsal, kept outside the repository, ran 830 steps with no honest-path
  failure against these changes in a scratch clone (a synthetic world: a
  skill fix on main after the capture, a re-saved Stage 1 review, a late
  second review, a cp1252 stdout, rebase and merge pulls). Their git 2.34.1
  reproductions fetch and update a synthetic sparse repository.

Every decision, review, verdict and policy value in the new tests and the
rehearsal is synthetic. No native session, human review, reference freeze,
corpus `--update-sparse` or pilot run occurred.

## Campaign 2 round 5 fixes — 2026-09-25

The fixes for the 15 verified findings of the campaign's fifth review (see
the "Round 5 review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `6fc0dc2`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on this branch.
No Python 3.10 interpreter was available here; the system Python 3.9 parser
read every changed Python file as a stand-in.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **811 passed, 533
    subtests passed**, none skipped.
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `python scripts/check_docs.py`: OK, 40 documents.
  `python tools/verify.py --all`: OK.
- The new regression tests (synthetic worlds only) fail against the round 4
  tools and pass against the fixed ones, except one parser test that pins
  behaviour the review guide now documents. The reviewers' reproductions
  kept outside the repository no longer show the defects: the honest
  summary committed after a tool update, or rebased onto one, unlocks Stage
  2 with a note; a summary hiding a baseline's retry or status is refused;
  a baseline retry after the recorded go is refused; the all-stage summary
  without one corpus repository keeps its Stage 2 runs valid; and an
  attempt that completed before an amendment is no longer shown as unsent.

Every decision, review, verdict and policy value in the new tests is
synthetic. No native session, human review, reference freeze, corpus
`--update-sparse` or pilot run occurred.

## Campaign 2 round 4 fixes — 2026-09-25

The fixes for the 19 verified findings of the campaign's fourth review (see
the "Round 4 review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `b783add`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on this branch.
No Python 3.10 interpreter was available here; the system Python 3.9 parser
read every changed Python file as a stand-in.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **783 passed, 533
    subtests passed**, none skipped.
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `python scripts/check_docs.py`: OK, 40 documents.
  `python tools/verify.py --all`: OK.
- The new regression tests (synthetic worlds only) fail against the round 3
  tools and pass against the fixed ones. Of the reviewers' 18 reproduction
  test cases, kept outside the repository, the 9 that asserted a defect now
  fail; the other 9 check Git's own behaviour or errors that were already
  loud. The Windows line-ending fix (DISTCI4-1) was not run on a Windows
  host: the tests now write the compared Markdown as bytes, and the pilot and
  decision tests passed under the reviewer's shim that makes
  `Path.write_text` write CRLF.

Every decision, review, verdict and policy value in the new tests is
synthetic. No native session, human review, reference freeze, corpus
`--update-sparse` or pilot run occurred.

## Campaign 2 round 3 fixes — 2026-09-25

The fixes for the 25 verified findings of the campaign's third review (see
the "Round 3 review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `1325db8`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on this branch.
No Python 3.10 interpreter was available here; the system Python 3.9 parser
read every changed Python file as a stand-in.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **759 passed, 533
    subtests passed**, none skipped.
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `git diff --name-status d99904f` over the immutable evidence paths printed
  nothing.
- The reviewers' reproduction tests for the merge, erased-campaign, merged
  freeze and retry findings, kept outside the repository, were run against
  the fixed tools: none reproduces any more (each of the 6 fails where the
  defect used to let it pass).

The history tests build synthetic Git repositories with merges, shallow and
partial clones. Every decision, review, verdict and policy value in the new
tests is synthetic. No native session, human review, reference freeze, corpus
`--update-sparse` or pilot run occurred.

## Campaign 2 round 2 fixes — 2026-09-25

The fixes for the 15 verified findings of the campaign's second review (see
the "Round 2 review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `fd75106`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on this branch.
No Python 3.10 interpreter was available here; the system Python 3.9 parser
read every changed Python file as a stand-in.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **721 passed, 533
    subtests passed, 2 skipped** (the same two Claude CLI skips as below).
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `git diff --name-status 25b7a39` over the immutable evidence paths printed
  nothing.
- The integrity reviewer's seven reproduction tests, kept outside the
  repository, were run against the fixed tools: none reproduces any more (each
  fails where the defect used to let it pass).

Every decision, review, verdict and policy value in the new tests is
synthetic. No native session, human review, reference freeze, corpus
`--update-sparse` or pilot run occurred.

## Campaign 2 round 1 fixes — 2026-09-25

The fixes for the 37 verified findings of the campaign's first review (see
the "Round 1 review fixes" paragraph of the [changelog](../CHANGELOG.md))
were checked before their commit on the `campaign2-pilot-readiness` branch,
on top of `484a032`, on the same macOS machine and virtualenv as below.
**These are local automated checks only**. CI has not run on this branch.
No Python 3.10 interpreter was available here. As a stand-in, the system
Python 3.9 parser read every Python file directly in `tools/`,
`evals/workflow/`, `scripts/` and `skills/mlview/scripts/`; it found one
f-string that only Python 3.12+ accepts, which was rewritten.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**.
  - Python helper, distribution and evaluation tests: **696 passed, 533
    subtests passed, 2 skipped** (the same two Claude CLI skips as below).
  - Viewer: **79 passed**. Extension: **250 passed**.
  - The actual VSIX: 11 files, 155,593 bytes. The built viewer's hashes
    are unchanged.
- After a rebuild (viewer build, asset and skill sync, extension compile),
  `git diff --exit-code` was clean over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview`.
- `python tools/evidence_lock.py`: 95 files match the lock.
  `git diff --name-status 25b7a39` over `evals/workflow/development`,
  `evals/workflow/fixtures`, the candidate ledgers and their licenses,
  `samples/configured_training*`, `docs/archive` and `docs/demo-logs`
  printed nothing.
- The reviewers' reproduction scripts, kept outside the repository, were
  run against the fixed tools: 12 of the 16 no longer reproduce. The other 4
  pass as expected:
  - two assert behaviour that was already correct (a consistent rewrite is
    caught, and a deleted record cannot flip a status);
  - one supersedes after deleting `candidate.json` in a world without Git
    (a new test covers the Git case);
  - one uses a hand-written candidate over a correctly bound freeze, which
    the specification leaves to commit authorship.

Every decision, review and verdict in the new tests is synthetic. No native
session, human review, reference freeze, corpus `--update-sparse` or pilot
run occurred.

## Campaign 2 local checks — 2026-09-25

Campaign 2 ("pilot readiness", version 0.3.0; see the
[changelog](../CHANGELOG.md)) was checked on commit `72e0ab3` of the
`campaign2-pilot-readiness` branch. The branch was built on `llm-workflow` at
`25b7a39` while PR #9 was open, then re-parented onto `main` at `d99904f`, the
squash merge of PR #9, which has the same tree as `25b7a39`. Every re-parented
commit keeps its tree, so the checks below apply unchanged (the checked tree
is `9a33c6af`, unchanged by the move).
**These are local automated checks on one macOS machine** (Darwin 25.6.0,
Node 26.4.0, npm 11.17.0, git 2.54.0, Python 3.13.15 in a virtualenv). The
venv's `pip freeze` has `pytest==9.1.1` and `jsonschema==4.26.0`, the exact
pins of `requirements-dev.txt`, with their dependencies (`iniconfig==2.3.0`,
`packaging==26.3`, `pluggy==1.6.0`, `Pygments==2.21.0`, `attrs==26.1.0`,
`jsonschema-specifications==2025.9.1`, `referencing==0.37.0`,
`rpds-py==2026.6.3`) plus packages the gates do not use. CI has not run on
this branch, so the new matrix (Python 3.10–3.14; Node 20.18.1, 22, 24 and 26;
the native sh and PowerShell drivers; 12 jobs) is unverified, as are the
PowerShell drivers, which could not run here. Nothing here is a native
assistant session, a human review, a reference freeze, a pilot run, live-host
validation or semantic accuracy.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**; the same command without
  `--skip-npm-install` ran `npm ci` in both packages and **passed all 17**.
  The tree was clean after each run.
- Python helper, distribution and evaluation tests: **654 passed, 533
  subtests passed, 2 skipped**. Both skips need the unavailable Claude CLI; they
  are not plugin validation passes. The corpus-gated tests ran against the local
  `.public-corpus` (all 106 candidate quotes and anchor blobs, the covered-set
  equality for the 8 repositories, the specification's verbatim `check`
  output). `evals/workflow/test_pilot_end_to_end.py` (10 tests) drives
  template, synthetic decisions, check, freeze, check-frozen, a clone, the
  candidate capture with a stub packager, plan, run-prepare, publication by the
  real helper, run-finish, review-template, a synthetic review and summarize
  `go` on one synthetic task with three hosts, with the real `verify_repo`,
  candidate check and frozen formats, then mutations that give `stop`,
  `incomplete`, `invalid` and integrity errors. Every decision and verdict in
  it is labelled synthetic.
- Viewer: **79 passed**. Extension: **250 passed**, including the conformance
  runner over all **70 corpus cases** (65 plus the NaN and duplicate-key
  notebook cases and three `publishedAt` pins), the parity invariant and the
  helper-publish, viewer-load round trip.
- The actual VSIX had **11 files, 155,593 bytes**, with only
  `mlview.openGeneratedDiagram` contributed.
- Portable skill bundle identity (eight files):
  `fd0f9cf06c8b922b854ea71e1755a68e7e7035344b2266503b55f4691da15578` (it was
  `5ef9e6ca…` for 0.2.0; the helper and the bundled contract changed). Built
  viewer: `mlview.js` SHA-256
  `f4eb582052434a649c377eb48c3cf9026b04db445ae2f50522013cdfa5b04443`,
  `mlview.css` unchanged at
  `e43c14dec5968faf86c28993dbbe8c39c35b334e9f6589c817d1ed286daa6185`.
- After the 0.3.0 bump (`458ae3a`) a second rebuild (viewer build, asset and
  skill sync, extension compile) left `git diff --exit-code` over
  `webview/dist`, `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview` clean.
- Immutable evidence: `git diff --name-status 25b7a39..HEAD` over
  `evals/workflow/development`, `evals/workflow/fixtures`, the candidate
  ledgers, their licenses, `samples/configured_training*`, `docs/archive` and
  `docs/demo-logs` printed nothing; the only change to
  `evals/workflow/reference-candidates/README.md` is one added, dated note
  (5 lines). `python tools/evidence_lock.py`: 95 files match the lock.
- `python tools/fetch_workflow_repos.py --verify` on the local corpus
  (read-only): **7 of 8 pass**. mmdetection fails only its sparse-list
  comparison (the five new config patterns are missing from the checkout's
  list; HEAD at the pin, clean apart from the tolerated marker, 174 covered
  files, 0 missing, 0 extra, 0 blob mismatches). `--update-sparse` was **not**
  run on the real corpus; running it once, then `--verify`, is the owner's or
  an agent's next step before a freeze.
- `claude plugin validate --strict` did not run: there is no Claude CLI on this
  machine. The conditional CI job is configured but has not run; if it needs
  credentials it will be withdrawn with the reason recorded here.
- Tooling exercise on scratch copies only (a clone at `458ae3a` and a copy of
  the 8 pinned checkouts outside the repository): synthetic decisions (reviewer
  "Test Reviewer (synthetic)", all accepted, the Flax scenario replaced) for the
  8 tasks and a synthetic run policy passed `check`; after `--update-sparse` on
  the scratch copy of mmdetection all 8 checkouts verified; the freeze dry run
  and `--write` produced 93 facts, 74 essential and 16 prompts with 0 leak
  findings, and `check-frozen` re-derived them byte for byte. The capture
  with the real `npm run package` built `mlview-0.3.0.vsix` and a candidate
  that `--check --vsix` accepted. `run-prepare pilot-nanogpt:codex:1` against
  the real nanoGPT checkout (read-only; 26 pinned files) and a synthetic
  artifact published by the installed helper were sealed by `run-finish`,
  reviewed synthetically and summarized as `incomplete` (23 of 24 planned runs
  pending). The remaining documented commands (context, `--supersede-reason`,
  `--stage all`, `plan --output`, `--record` refusals, `--amend`,
  `development-plan --output`, `review-packet --force`, the development
  snapshot, `vsix_check.py --payload-only`, the fetcher modes on the scratch
  copy, `evidence_lock.py --add`, and the installer's upgrade, local-edit
  refusal, `--force` and symlink doctor) behaved as documented. The real corpus
  and this checkout were unchanged afterwards. **This was a tooling exercise;
  not a pilot run, native session or human review.**

No native session, human review, reference freeze or pilot run occurred in
Campaign 2. The commit that adds this record changes only CHANGELOG.md,
STATUS.md and this file. Still outstanding: CI on this branch, the owner's
reference review, the corpus `--update-sparse`, the freeze, the pilot
candidate capture, Stage 1 and the manual live-host checklist.

## Campaign 1 CI and live check — 2026-09-25

The first CI runs of the campaign (`8aa3e62`) failed in test code only: a
helper test built its deep-nesting input with `json.loads`, which raises
`RecursionError` before Python 3.12, and an extension test compared against
`JSON.stringify` of a 5,001-level object, which overflowed the default stack on
Linux Node 20 and 22. Both now write the input as raw text (`10dd273`). The next
run exposed a Windows-only difference in the vscode mock, whose open documents
had `/`-separated paths where real VS Code gives native ones (`deab60a`). At
`deab60a` all eight CI jobs passed (Python 3.10–3.13; Node 20.18.1 and 22 on
Linux, Node 22 on macOS and Windows) in both the [push run](https://github.com/realmyang/MLView/actions/runs/36093596906) and the
[PR run](https://github.com/realmyang/MLView/actions/runs/36093599706). The local gate results above are unchanged by these test-only
commits.

A partial live check followed, on macOS only: VS Code 1.139.0 Extension
Development Host with an isolated profile, the Campaign 1 extension and viewer,
and a scratch workspace. High Contrast Light mapped to the viewer's
high-contrast palette; a UTF-8 BOM source published by the 0.2.0 helper showed
no banner while open in an editor; typing produced the unsaved-edit banner and
reverting cleared it; a change on disk produced the historical-diagram banner
and restoring the bytes cleared it; a zero-finding document read "No findings
recorded in this revision"; and the copied Challenge prompt matched the new
format. See the [dated log](demo-logs/2026-09-25-campaign1-live-check.md) for
exact observations and what was not covered (HC Dark, the other intents,
notebooks, a symlinked root, Restricted Mode, Windows, Linux, remote
workspaces, a native assistant).

## Campaign 1 local checks — 2026-09-25

Campaign 1 ("reliability and trust", version 0.2.0; see the
[changelog](../CHANGELOG.md)), including the fixes from the campaign's first
and second reviews, was checked on commit `106f172` of the `c1-integration`
branch.
**These are local automated checks on one macOS machine** (Darwin 25.6.0,
Node 26.4.0, npm 11.17.0, Python 3.13.15). CI has not run on this commit, so
its result is pending. Node 20.18.1 and 22, Windows, Linux and Python 3.10–3.12
were not exercised. Nothing here is live-host (Extension Development Host)
validation, a native assistant run, human review or semantic accuracy.

- `MLVIEW_PYTHON="$PWD/.venv/bin/python" PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **all 15 exercised gates passed**. The gate sets `MLVIEW_REQUIRE_PYTHON=1`,
  so the refine-wedge regression ran the real helper instead of skipping.
- Python helper, distribution and evaluation tests: **188 passed, 430 subtests
  passed, 2 skipped**. Both skips need the unavailable Claude CLI; they are not
  plugin validation passes. The conformance runner
  (`tools/test_workflow_conformance.py`, 12 tests, 316 subtests over 65 corpus
  cases) and the recorded-artifact guard (1 test, 23 subtests) are included.
- Viewer: **79 passed**, including the rewritten host, bootstrap and bundle
  handshake, bundle hygiene and the routed-geometry golden.
- Extension: **245 passed**, including revision lineage (37), panel lineage
  (21), host-shown text (10), the refine wedge with the real helper (6), host
  protocol (8), bootstrap (2), export payloads (4), recorded artifacts (3) and
  the conformance runner (70: every corpus case, the parity checks, the
  helper-publish, viewer-load round trip and a long-s alias round trip that
  runs only on a case-insensitive volume, as here). The case-variant open test
  also ran, for the same reason.
- Both eight-file skill ZIPs were packaged. The actual VSIX had **11 files,
  155,592 bytes**, with no analyzer or Python runtime payload and only
  `mlview.openGeneratedDiagram` contributed.
- Portable skill bundle identity (`sha256-sorted-path-nul-bytes-nul` over the
  eight files): `5ef9e6cae829de79ae3400f3ea5d461303d9c07f7752c4fb1595e5097161b475`.
  Built viewer: `mlview.js` SHA-256
  `9618e3be1d56dd296212d62f2095e69a2cb281789b78a575b52ca68221f8a53b`,
  `mlview.css` SHA-256
  `e43c14dec5968faf86c28993dbbe8c39c35b334e9f6589c817d1ed286daa6185`.
- After a separate rebuild (viewer build, asset and skill sync, extension
  compile), `git diff --exit-code` over `webview/dist`,
  `vscode-extension/media`, the extension's notices and
  `claude-plugin/skills/mlview` was clean.
- Earlier, on commit `f4932c7` (before the first-review fixes), the
  2026-09-25 review's critic reproductions were re-run on scratch copies. A
  changed installed-skill file no longer made a diagram stale: no banner, and
  navigation opened `train.py`. A `"parent": null` node was rejected by both
  the helper and the extension. A workflow-level finding stayed listed under
  both phase filters and under `stage:train`. These reproductions were not
  repeated on later commits.
- The second review's lineage reproductions were re-run on scratch copies
  against the extension and viewer built from the `106f172` sources: a
  restored or repaired artifact now clears the composer's refusal; a revision
  holding `{"toString": 1}` is rejected as invalid and Refine continues from
  it; and an artifact opened through a differently cased path opens one
  panel with no error.

The commit that adds this record changes only this file and STATUS.md. Still
outstanding: CI on this commit, the manual live-host checklist (Refine with
each intent, HC Dark and HC Light, a BOM source open while publishing, a
symlinked root, a mixed-case Windows drive letter), Windows/Linux live
interaction, the human reference review and the held-out pilot.

## Live usability and CI follow-up — 2026-09-18

The maintainer authorized committing/pushing the campaign and completing live
viewer checks. `84ea3a1` published the campaign. Remote CI exposed a Windows
absolute path rejection, fixed in `7182224`; its push run passed. Its PR run
exposed a fixed-delay test race, now replaced with a bounded wait for the
settled state.
These earlier run outcomes do not validate the later changes described below.

The final local command was
`PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
**all 15 exercised gates passed**. Python: **122 passed, 24 subtests passed,
2 skipped** (unavailable Claude CLI). Viewer: **32 passed**. Extension:
**43 passed**. Both skill archives passed; the actual VSIX had **11 files,
141,149 bytes**, with no retired analyzer/runtime payload. Documentation checks
and `git diff --check` passed. At that point the eight-file portable skill SHA-256 was
`b251ac3774a453473ccf501643f56eb2ca826640d713903666add9c9e93c5b7f`.

Live checks used an isolated VS Code 1.138.0 Extension Development Host on
macOS, with the actual extension, built viewer and synthetic source/artifacts.
The workspace stayed in Restricted Mode. Native VS Code API commands opened
the diagram; Chromium debugging controlled its real rendered UI and keyboard
events. The fixture was synthetic; no native assistant or target ML code was
executed.

- The Outline enumerated all three nodes and both directed relationships;
  authored basis labels and search wording were checked in the rendered UI.
- Arrow-key/End navigation selected and focused the correct side tabs; Tab
  moved into the panel. This fixed the missing tablist keyboard behavior.
- The edge inspector displayed both quotes. Source navigation reached line 2;
  Previous evidence returned to line 1 with the expected boundary states.
  The source-column fix kept the diagram visible instead of opening a duplicate
  source tab over it. Notebook column selection has regression coverage, but
  this live exercise used Python source.
- Challenge opened a composer for the selected `output` edge. Support and
  counter-evidence remained distinguishable. A finding without associated nodes
  was inspectable with its coverage limitation.
- A structurally invalid revision retained the valid diagram. The native
  validator now matches the helper's evidence requirement, including the
  conceptual-parent exception. Unsaved source changes blocked a stale update
  and evidence navigation; restoring the source cleared the warning and adopted
  the child revision.
- Dark/high-contrast screenshots were inspected. Light theme switching was
  confirmed. Closing the narrow-screen side drawer and fitting the view put all
  three node rectangles inside the canvas. Accessible names were inspected in
  Chromium's accessibility tree; this is **not a spoken screen-reader pass**.

Focused Chrome cold/warm profiling and native VS Code scale measurements
completed through **2,000 represented nodes** with corrected, canonically
validated synthetic fixtures. The earlier generator had invalid host/evidence
values; it is now corrected and guarded by all-size reference/basis tests.
See [PERFORMANCE.md](PERFORMANCE.md) for source hashes, timing definitions,
the routing bottleneck and measurement limits. No performance optimization or
semantic accuracy gain is claimed from these observations.

Windows/Linux/remote live interaction, spoken assistive-technology testing,
and matched native-model experiments remain separate work. The
[human reference review](../evals/workflow/reference-candidates/REVIEW_GUIDE.md)
and held-out pilot remain pending; neither green tests nor these UI checks
provide semantic adjudication.

## Trust/usability campaign results — 2026-09-18

The initial [campaign](TRUST_USABILITY_CAMPAIGN.md), later committed as `84ea3a1`,
was based on `d40d96e`. On macOS with Python 3.13.15 and Node 26.4.0:

- `PATH="$PWD/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 sh scripts/e2e.sh --skip-npm-install`:
  **15 exercised gates passed**, with a fresh build and generated-copy checks.
- Python: **122 passed, 24 subtests passed, 2 skipped**. The two skips require
  the unavailable Claude CLI; they are not live plugin validation passes.
- Viewer: **30 passed**. Extension: **40 passed**. These include evidence and
  relationship navigation, current-selection challenge prompts, coalescing,
  concurrent-change/disposal guards and notebook freshness behavior.
  The extension suite also passed after adding automatic temporary-workspace
  cleanup to the panel and workflow-validator tests. The latter rerun left
  zero new matching temporary directories.
- Both eight-file skill ZIPs and the actual VSIX passed packaging checks.
  VSIX: **11 files, 140,584 bytes**, no analyzer or Python runtime payload.
- Skill Creator `quick_validate.py`, candidate snapshot creation/drift check,
  and `git diff --check` passed. The snapshot covers all eight portable skill
  files; it explicitly does not approve a pilot.
- Four separate-process jsdom benchmarks completed at 100/500/1,000/2,000 nodes
  with node representation, scope/reset, SVG export and disposal assertions.
  See [exact bundle identity, timings and limits](PERFORMANCE.md).
- An independent skill exercise by an auxiliary Codex agent (gpt-5.6-sol)
  published and revalidated an artifact after one schema repair. Its scope and
  limitations are recorded in the [campaign report](TRUST_USABILITY_CAMPAIGN.md).
- Historical native artifacts, provisional ledgers, held-out source/reference
  pins, task manifest, public schema and shipped sample are unchanged.

The first attempt to automate the live VS Code exercise stalled during setup.
No native VS Code interaction, browser paint timing, screen-reader pass or
human semantic score is claimed for these changes. The isolated VS Code process
and loopback server started for that attempt were stopped. The existing pilot
summary still reports **72 pending, zero completed, zero human-reviewed**.
These initial results are superseded by the follow-up above where explicitly
stated.

## Static-removal baseline — 2026-09-18

On macOS with Python 3.13.15, Node 26.4.0 and npm 11.17.0:

- `sh scripts/e2e.sh --skip-npm-install`: **15 exercised gates passed**.
  Existing locked npm dependencies were reused; the viewer and extension were
  freshly rebuilt, type-checked, tested and packaged.
- Python helper, installer/distribution, evaluation and script tests:
  **102 passed, 16 subtests passed, 2 skipped**. Both skips require the absent
  Claude CLI; they are not plugin CLI validation passes.
- Viewer: **21 passed**, including authored layout, cycles, grouping, search,
  scope, source navigation, refinement, revision updates and SVG export.
- Extension: **30 passed**, including activation, workspace evidence validation,
  authored panels and packaging.
- Both standalone skill ZIPs built successfully. The actual VSIX passed payload
  checks: **11 files, approximately 135 KiB**, required licenses and current
  bundles present, no Python analyzer/runtime or static analysis commands.
- `python tools/verify.py --all`, `python scripts/check_docs.py`, YAML parsing
  and `git diff --check` passed. All retired runtime roots are absent.
- Recorded development/native/follow-up artifacts and the shipped sample are
  unchanged. Relocated example files retain their original SHA-256 values.

The rewritten CI matrix passed all eight jobs for `5319777`: Python 3.10–3.13,
Node 20.18.1/22 and Linux/Windows/macOS package checks, in both the
[push run](https://github.com/realmyang/MLView/actions/runs/35329824132) and
[pull-request run](https://github.com/realmyang/MLView/actions/runs/35329828241).
Earlier analyzer suite counts and CI runs refer to older revisions.

No automatic test claims live assistant discovery, native model execution or
semantic correctness. Dated host logs are in [docs/demo-logs/](demo-logs/),
and semantic human review remains pending.
