#!/usr/bin/env python
"""Tests for scripts/doc_numbers.py -- checks 9, 10 and 11 of the doc gate.

Same shape as `scripts/test_check_docs.py`, whose `_tree` helper and `REPO` these
reuse: each case builds a throwaway tree and runs the whole gate against it with
--root, so nothing here depends on the state of the real repo. The last case does
read the real repo, and asserts ANA-12's acceptance clause directly.

`scripts/test_check_docs.py` runs these too, so the drivers and CI keep one
doc-gate self-test entry point. Run either file under pytest for the same set.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402
import doc_numbers  # noqa: E402
from test_check_docs import REPO, _tree  # noqa: E402

# ------------------------------------------------- checks 9-11 (doc_numbers)
# TB-08 / DOC-ACCURACY-02: docs/ACCURACY.md published `92 of 139, 66.2%` graph
# fidelity while analyzer/tests/accuracy/baseline.json -- the ratchet the gate
# actually enforces -- had been re-recorded to 120 of 139, and the doc went on to
# explain the stale figure with the defect the same branch had repaired.
# CI-ARTIFACTS-01: both e2e jobs uploaded `.mlview/*.html`, upload-artifact skips
# dot-paths, and four green runs archived nothing at all.
# ANA12-E2E-05: ANA-12's accuracy row was left out of both drivers because four
# documents quoted "17 steps".

BASELINE = {
    "graphFidelity": {"opsLabelled": 139, "opsRecovered": 120, "score": 0.8633},
    "overall": {"expectedLabels": 62, "precision": 1.0, "recall": 0.629,
                "visibleRecall": 0.5323, "highValueRecall": 0.4884},
    "unseen": {"expectedLabels": 47, "precision": 1.0, "recall": 0.5106,
               "recovered": 24, "visibleRecall": 0.383, "visibleRecovered": 18,
               "highValueLabels": 32, "highValueRecall": 0.3125,
               "highValueRecovered": 10},
}

ACCURACY_DOC = """# ACCURACY

## 3 - the numbers

```
overall   labels  62   recall  62.9%   visible  53.2%   high+medium  48.8%   precision 100.0%
unseen    labels  47   recall  51.1%   visible  38.3%   high+medium  31.2%   precision 100.0%
```

| Reading | Number | What it means |
|---|---|---|
| raw recall | **51.1%** | 24 of 47 planted defects produced a finding |
| visible recall | **38.3%** | ...of which only 18 clear 0.6 |
| high+medium recall | **31.2%** | 10 of 32 defects that are not hygiene |

**Graph fidelity: 120 of 139 hand-labelled ops, 86.3%.** The distribution is the
story, not the average.
"""


def _accuracy_tree(doc):
    return _tree({"README.md": "# mlview\n",
                  "docs/ACCURACY.md": doc,
                  "analyzer/tests/accuracy/baseline.json":
                      json.dumps(BASELINE, indent=2) + "\n"})


def test_a_matching_accuracy_headline_is_clean():
    root = _accuracy_tree(ACCURACY_DOC)
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stale_graph_fidelity_headline_is_caught():
    """The exact drift TB-08 found: the pre-ANA-1 figure beside the new baseline."""
    stale = ACCURACY_DOC.replace(
        "**Graph fidelity: 120 of 139 hand-labelled ops, 86.3%.**",
        "**Graph fidelity: 92 of 139 hand-labelled ops, 66.2%.**")
    root = _accuracy_tree(stale)
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "TB-08" in problems[0]
        assert "92 of 139" in problems[0] and "120 of 139" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stale_recall_headline_is_caught():
    root = _accuracy_tree(ACCURACY_DOC.replace("recall  51.1%", "recall  26.0%"))
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "TB-08" in problems[0] and "51.1%" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stale_reading_row_is_caught():
    """The prose counts under a percentage rot the same way the percentage does."""
    root = _accuracy_tree(ACCURACY_DOC.replace("24 of 47 planted", "12 of 47 planted"))
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "TB-08" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_accuracy_doc_without_a_baseline_is_not_checked():
    """The check compares two files; with one of them absent it says nothing."""
    root = _tree({"README.md": "# mlview\n", "docs/ACCURACY.md": ACCURACY_DOC})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


UPLOAD_WORKFLOW = """name: CI
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: upload the emitted reports
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: mlview-reports
%s          path: .mlview/*.html
          if-no-files-found: warn
"""


def test_a_hidden_artifact_path_without_the_flag_is_caught():
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/ci.yml": UPLOAD_WORKFLOW % ""})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "CI-ARTIFACTS-01" in problems[0]
        assert ".mlview/*.html" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_hidden_artifact_path_with_the_flag_is_clean():
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/ci.yml":
                      UPLOAD_WORKFLOW % "          include-hidden-files: true\n"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


ENV_UPLOAD_WORKFLOW = """name: Public corpus

on:
  schedule:
    - cron: '20 4 * * 1'
  workflow_dispatch:

env:
  PYTHONUTF8: '1'
  MLVIEW_PUBLIC_CORPUS_DIR: ${{ github.workspace }}/%s

jobs:
  corpus:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: upload the report
        if: always()
        uses: actions/upload-artifact@v5
        with:
          name: public-corpus-report
%s          path: ${{ env.MLVIEW_PUBLIC_CORPUS_DIR }}/_reports/report.json
          if-no-files-found: warn
"""


def test_a_hidden_artifact_path_behind_an_env_reference_is_caught():
    """PUB-01 wrote the same defect a second time, spelled through the workflow's
    own `env:` block, and the check that exists for it saw a path with no dot in
    it. Resolving the reference is the difference between a gate and a spelling
    convention."""
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/public-corpus.yml":
                      ENV_UPLOAD_WORKFLOW % (".public-corpus", "")})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "CI-ARTIFACTS-01" in problems[0]
        assert ".public-corpus/_reports/report.json" in problems[0]
        # The report names the line to go and fix, and what it resolved to.
        assert "public-corpus.yml:17" in problems[0], problems
        assert "written `${{ env.MLVIEW_PUBLIC_CORPUS_DIR }}" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_env_reference_to_a_visible_directory_needs_no_flag():
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/public-corpus.yml":
                      ENV_UPLOAD_WORKFLOW % ("public-corpus", "")})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_env_reference_to_a_hidden_directory_with_the_flag_is_clean():
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/public-corpus.yml":
                      ENV_UPLOAD_WORKFLOW
                      % (".public-corpus",
                         "          include-hidden-files: true\n")})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_schedule_entry_does_not_swallow_the_job_below_it():
    """`- cron:` sits at indent 4 and every step at indent 6, so the old block
    rule found no boundary and reported the one upload step twice -- once under
    its own name and once under the cron line."""
    lines = (ENV_UPLOAD_WORKFLOW % (".public-corpus", "")).splitlines()
    blocks = dict(doc_numbers._yaml_steps(lines))
    cron = next(start for start, block in blocks.items()
                if block[0].lstrip().startswith("- cron"))
    assert not any("upload-artifact" in line for line in blocks[cron]), blocks[cron]


def test_the_real_workflows_upload_what_they_claim_to():
    """The repo's own `.github/workflows`, including the PUB-01 job whose report
    is the only evidence behind its verdict."""
    problems: list = []
    doc_numbers.check_artifact_uploads(REPO, problems)
    assert problems == [], "\n".join(problems)


def test_a_visible_artifact_path_needs_no_flag():
    root = _tree({"README.md": "# mlview\n",
                  ".github/workflows/ci.yml":
                      UPLOAD_WORKFLOW.replace(".mlview/", "ci-reports/") % ""})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


E2E_SH_FIXTURE = """#!/usr/bin/env sh
step "build" "$REPO_ROOT" sh scripts/build.sh
record SKIP "build" "--skip-build"
step "analyzer tests" "$REPO_ROOT" pytest
step "accuracy corpus" "$REPO_ROOT" python tools/accuracy.py
"""
E2E_PS1_FIXTURE = """Invoke-Step 'build' $RepoRoot { }
Add-Result 'build' 'SKIP' '-SkipBuild'
Invoke-Step 'analyzer tests' $RepoRoot { }
Invoke-Step 'accuracy corpus' $RepoRoot { }
"""


def _driver_tree(readme):
    return _tree({"README.md": readme,
                  "scripts/e2e.sh": E2E_SH_FIXTURE,
                  "scripts/e2e.ps1": E2E_PS1_FIXTURE})


def test_a_stale_step_count_is_caught():
    """Three rows, however many branches print them, and a doc that says four."""
    root = _driver_tree("# mlview\n\nsh scripts/e2e.sh runs all 4 steps.\n")
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "ANA12-E2E-05" in problems[0]
        assert "print 3 rows" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_current_step_count_is_clean():
    root = _driver_tree("# mlview\n\nsh scripts/e2e.sh runs all 3 steps.\n")
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_step_count_away_from_an_e2e_line_is_not_a_claim():
    """`BUILD OK - 5/5 steps` is about scripts/build, not about the e2e table."""
    root = _driver_tree("# mlview\n\nscripts/build.sh prints 5 steps.\n")
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_drivers_that_print_different_tables_are_caught():
    """ANA-12's row belongs in both drivers or in neither."""
    root = _tree({"README.md": "# mlview\n",
                  "scripts/e2e.sh": E2E_SH_FIXTURE,
                  "scripts/e2e.ps1": E2E_PS1_FIXTURE.replace(
                      "Invoke-Step 'accuracy corpus' $RepoRoot { }\n", "")})
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "ANA12-E2E-05" in problems[0]
        assert "only in e2e.sh: `accuracy corpus`" in problems[0], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_drivers_agree_and_carry_the_accuracy_row():
    """ANA-12's acceptance clause, asserted rather than asserted about."""
    rows_sh = doc_numbers._rows(REPO / "scripts" / "e2e.sh", doc_numbers.SH_ROW_RE)
    rows_ps1 = doc_numbers._rows(REPO / "scripts" / "e2e.ps1", doc_numbers.PS_ROW_RE)
    assert rows_sh == rows_ps1, sorted(rows_sh ^ rows_ps1)
    assert "accuracy corpus" in rows_sh, sorted(rows_sh)


def main() -> int:
    """Standalone entry point; scripts/test_check_docs.py runs these as well."""
    from test_check_docs import run_module

    failed = run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_numbers self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
