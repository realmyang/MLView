> Historical record: the static analyzer was removed on 2026-09-18.
> Commands, paths, and compatibility promises below describe earlier revisions.
> See [current status](STATUS.md) for the supported product.

# Public-readiness review — 2026-09-18

This review starts from `12747c4` on `llm-workflow`. The working tree was clean
and the branch contains the merged research and public-readiness work at
`2331081`. It covers the native LLM workflow, evaluation tooling, distribution,
contributor entrypoints, and regression checks for the retained static product.
It is an engineering review, not human adjudication of model interpretations.

## Issues resolved

- Artifact validation rejects ambiguous relative paths and invalid timestamps
  consistently in Python and TypeScript. Malformed IDs and publication I/O
  failures produce validation errors rather than leaking filesystem tracebacks.
- Parent-cycle checks use iterative linear traversal. Source validation reuses
  source reads, and the viewer reuses hashes, source lines and notebook parsing.
  Finding-to-edge and per-phase counts use indexes rather than repeated scans.
- Unexpected host validation failures retain the last valid diagram and show
  an error. A regression exercises a maximum-depth 2,000-node chain and cycle.
- Skill install, inspection, synchronization and packaging reject unsafe
  symlinks. The canonical skill carries the MIT license so direct installs,
  Claude copies and reproducible ZIPs distribute the same licensed payload.
- Pilot records must retain the planned prompt. Review evidence uses strict
  JSON Pointers, and registered artifact paths stay portable on Windows.
  All twelve committed native review ledgers are now exercised by tests.
- A failed wheel build fails the packaging gate instead of being counted as a
  skipped check. Windows CI now also runs the authored helper and evaluation
  suite; all supported-version Python matrix jobs include the new wheel tests.
- Python distributions use SPDX license metadata, and the wheel gate verifies
  license bytes. VSIX builds use a locked local VSCE 3.9.2 instead of resolving
  an unpinned tool through `npx`. Build tooling requires Node 20.18.1+; explicit
  development-dependency overrides retain compatibility with that floor.
- The reference ledgers now travel with the exact licenses and applicable
  copyright notices from all eight pinned upstream repositories. Their source
  excerpts retain upstream terms and are excluded from product distributions.
- Contributor instructions, issue forms and PR templates describe the native
  LLM workflow separately from the legacy static analyzer. Security and conduct
  guidance avoids public disclosure of private reports or contact information.
  Local `.env` files are ignored; example files remain eligible for tracking.

## Validation

Local environment: macOS, Python 3.13.15 from the checkout's virtual environment,
Node 26.4.0 and npm 11.17.0. Child processes used the venv on `PATH` and
`PYTHONDONTWRITEBYTECODE=1`.

| Check actually run | Result |
|---|---|
| Viewer build; `tools/sync-assets.py`, `tools/sync-core.py`, `tools/sync-skill.py`; extension compile; both `npm run check` commands | Passed; generated copies synchronized |
| `python -m pytest skills/mlview/tests tools/test_install_skill.py tools/test_package_skill.py tools/test_sync_skill.py tools/test_wheel_check.py evals scripts -q -p no:cacheprovider` | 228 passed, 16 subtests passed |
| `sh scripts/e2e.sh --skip-build` | 19 passed, zero failed; the build step was explicitly skipped because the build was run separately |
| Analyzer suite within e2e | 2,654 passed, nine skipped, 24 expected failures |
| Viewer suite within e2e | 607 passed, one TODO, zero failures |
| Extension suite within e2e | 439 passed, zero failures |
| Claude plugin suite within e2e | 475 passed, six skipped, three expected failures |
| `python tools/verify.py --all` within e2e | All ten gates passed |
| `python tools/verify.py --scopes --fuzz 200` | All five scope gates passed, including 200 generated cases; seed 91064 |
| `python -m build --wheel --no-isolation analyzer`, then the e2e wheel install/run check | Passed with SPDX metadata and exact license text; clean-venv CLI found the planted leak |
| `npm --prefix vscode-extension run package -- --out <temporary-vsix>` and `python scripts/vsix_check.py <temporary-vsix>` | Passed: 182 files, 915.54 KB, below the 1 MiB limit; no bytecode |
| `python tools/package_skill.py --host shared` and `--host claude-code`, with temporary outputs | Both five-file distributions built; reproducibility, extraction and publication checks passed in the suite above |
| Installed skill-creator validator | Portable skill passed frontmatter/resource checks |
| `python scripts/check_docs.py`, workflow/issue YAML parsing, dotenv ignore checks, `git diff --check` | Passed |

The first e2e run exposed a stale generated extension fixture after the viewer
hash changed. Regeneration changed only its renderer hash, generation timestamp
and measured duration; graph content remained identical. The extension suite
and the final complete e2e run above then passed.

A separate helper replay validated all 23 preserved development/sample
WorkflowDocuments. Four historical artifacts also fingerprinted their installed
skill files, so the replay restored those bytes from pinned commit `36dbbe5`
in temporary workspaces and checked every recorded source digest. No artifact
was rewritten and no target program or native LLM session was executed.
The twelve native review ledgers and all eight upstream-license copies are
covered by the evaluation tests. An independent Sol review found no code or
packaging blockers; its documentation wording correction was incorporated.

The published starting commit passed all 13 remote CI jobs:
[push run `35287750580`](https://github.com/realmyang/MLView/actions/runs/35287750580)
and [PR run `35287753581`](https://github.com/realmyang/MLView/actions/runs/35287753581).
Those runs validate `12747c4`, not the later review fixes in this working tree.

Full `npm audit` checks, including build and test dependencies, reported zero
advisories for both `webview` and `vscode-extension` on the review date, including
the final lockfile with the VSIX packager. Source and distribution payload scans
found no private-key or common credential-token pattern matches. Product
archives contained no test suites, corpus checkouts, raw histories, virtual
environments or dependency trees. This is a bounded scan, not a claim
that an exhaustive security audit has occurred. Raw assistant histories,
credentials, local evaluation captures and corpus checkouts remain untracked.

## Public project status and remaining evidence

The repository is public, has an MIT license, accepts issues and contributions,
and has GitHub private vulnerability reporting enabled. This review enabled
GitHub secret scanning and push protection, then verified both settings through
the repository API. This confirms configuration, not completion of the service's
asynchronous scans. Dependabot's automatic security-update PRs, non-provider
pattern scanning and validity checks remain disabled. No dedicated private
conduct-reporting contact is configured, and the conduct policy states that
limitation.

The appropriate public status remains **experimental**. A Marketplace, Open
VSX or PyPI release is not claimed. Native diagram publication and interaction
have prior development evidence, but no fresh native-assistant or desktop
acceptance is claimed for these review fixes. Live Windows and remote-workspace
coverage remain incomplete.

The twelve original native artifacts and their provisional reviews remain
unchanged. Five of the six later GAN/notebook follow-ups produced valid
artifacts; the Copilot GAN attempt failed within its repair budget. Copilot's
notebook final response was recovered during cleanup and still incorrectly
denies recorded execution counts; its fresh diagram was not inspected. The
frozen manifests retain their original observation snapshots.

Human semantic adjudication and reference approval remain pending. The 24
held-out first runs and 48 repeats have not started. The helper and packaging
changes alter the current skill bundle; the earlier four-file bundle hash in
[QUALITY_SPRINT.md](QUALITY_SPRINT.md) identifies that historical batch, not
the revised distribution. Freeze a new bundle before another native campaign.
