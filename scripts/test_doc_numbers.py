#!/usr/bin/env python
"""Tests for scripts/doc_numbers.py -- checks 9, 10, 11, 19 and 20 of the gate.

Same shape as `scripts/test_check_docs.py`, whose `_tree` helper and `REPO` these
reuse: each case builds a throwaway tree and runs the whole gate against it with
--root, so nothing here depends on the state of the real repo. Five cases do read
the real repo: ANA-12's acceptance clause, the real workflows' command lines
against the real tools' parsers (PUB2-10), and the real docs against the hop
mechanism (VIS2-17).

`scripts/test_check_docs.py` runs these too, so the drivers and CI keep one
doc-gate self-test entry point. Run either file under pytest for the same set.
"""
from __future__ import annotations

import io
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


# ---------------------------------------------------------------- check 19
# PUB2-10: `.github/workflows/public-corpus.yml` built
# `public_corpus.py fetch --repo <names>` out of its `workflow_dispatch` input,
# and `--repo` lived on the top-level parser alone, so argparse answered
# `unrecognized arguments` and exited 2. Every dispatch that used the documented
# input died at the job's first step, and nothing in the tree could see it: a
# workflow is text that is not run until the schedule runs it.

#: The tool as it was before the fix -- the selector on the top level only.
PRE_FIX_TOOL = '''\
"""The pre-PUB2-10 shape, kept here so the defect can be reproduced."""
import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="public_corpus")
    parser.add_argument("--repo", action="append", default=[])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("run")
    return parser
'''

#: A tool that offers no parser is not checked: the gate may not become a reason
#: to import something with side effects.
OPAQUE_TOOL = "import argparse  # no build_parser(), so nothing to ask\n"

CORPUS_WORKFLOW = """name: Public corpus

on:
  workflow_dispatch:
    inputs:
      repos:
        description: 'Comma-separated repo names from repos.json (empty = all)'
        required: false
        default: ''

jobs:
  corpus:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: fetch the pinned corpus
        run: |
          python tools/%s
          du -sh .public-corpus
"""

#: The three spellings that matter: the one that failed, and the two that work.
AFTER_THE_SUBCOMMAND = ("public_corpus.py fetch "
                        "${{ github.event.inputs.repos && "
                        "format('--repo {0}', github.event.inputs.repos) || '' }}")
BEFORE_THE_SUBCOMMAND = ("public_corpus.py "
                         "${{ github.event.inputs.repos && "
                         "format('--repo {0}', github.event.inputs.repos) || '' }} "
                         "fetch")
THROUGH_THE_ENVIRONMENT = 'public_corpus.py ${REPOS:+--repo "$REPOS"} fetch'


def _workflow_tree(command, tool=PRE_FIX_TOOL):
    return _tree({"README.md": "# mlview\n",
                  "tools/public_corpus.py": tool,
                  ".github/workflows/public-corpus.yml": CORPUS_WORKFLOW % command})


def test_a_ci_line_the_tool_would_refuse_is_caught():
    """The defect itself: the selector after the subcommand, pre-fix parser."""
    root = _workflow_tree(AFTER_THE_SUBCOMMAND)
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "PUB2-10" in problems[0]
        assert "unrecognized arguments" in problems[0], problems[0]
        assert "tools/public_corpus.py" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_same_line_before_the_subcommand_is_clean():
    root = _workflow_tree(BEFORE_THE_SUBCOMMAND)
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_an_input_passed_through_the_environment_is_clean():
    """`${REPOS:+--repo "$REPOS"}` is the injection-safe spelling, and it has to
    stay checkable: either it contributes its text or it contributes nothing."""
    root = _workflow_tree(THROUGH_THE_ENVIRONMENT)
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_tool_accepts_both_orders():
    """The fix, asserted against the real parser rather than a fixture of it."""
    root = _workflow_tree(AFTER_THE_SUBCOMMAND, tool="# replaced below\n")
    try:
        shutil.copy(REPO / "tools" / "public_corpus.py",
                    root / "tools" / "public_corpus.py")
        # The real tool brings check 17 with it: it names a download directory.
        io.open(root / ".gitignore", "w", encoding="utf-8",
                newline="\n").write(".public-corpus/\n")
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
        io.open(root / ".github/workflows/public-corpus.yml", "w",
                encoding="utf-8", newline="\n").write(
                    CORPUS_WORKFLOW % BEFORE_THE_SUBCOMMAND)
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_tool_without_a_parser_is_not_checked():
    root = _tree({"README.md": "# mlview\n",
                  "tools/opaque.py": OPAQUE_TOOL,
                  ".github/workflows/ci.yml":
                      CORPUS_WORKFLOW % "opaque.py --a-flag-nobody-declared"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


NUMERIC_DEFAULT_TOOL = '''\
import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="verify")
    parser.add_argument("--scopes", action="store_true")
    parser.add_argument("--fuzz", type=int, default=0)
    return parser
'''

NIGHTLY_WORKFLOW = """name: Nightly

on:
  workflow_dispatch:
    inputs:
      cases:
        required: false

jobs:
  fuzz:
    runs-on: ubuntu-latest
    steps:
      - name: differential fuzz
        run: python tools/verify.py --scopes --fuzz %s
"""


def test_a_numeric_default_inside_an_expression_is_read_as_a_number():
    """`${{ inputs.cases || 2000 }}`: the literal in the expression is the value
    the line really carries, and `--fuzz` takes an int. Collapsing every
    expression to one opaque token would invent a failure here."""
    root = _tree({"README.md": "# mlview\n",
                  "tools/verify.py": NUMERIC_DEFAULT_TOOL,
                  ".github/workflows/nightly.yml":
                      NIGHTLY_WORKFLOW % "${{ github.event.inputs.cases || 2000 }}"})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_comparison_inside_an_expression_contributes_no_argument():
    """`${{ inputs.strict == 'true' && '--strict' || '' }}` puts `--strict` or
    nothing on the line -- never the word `true`, which the tool would refuse."""
    root = _tree({"README.md": "# mlview\n",
                  "tools/verify.py": NUMERIC_DEFAULT_TOOL,
                  ".github/workflows/nightly.yml": NIGHTLY_WORKFLOW.replace(
                      "--fuzz %s",
                      "--fuzz 200 "
                      "${{ github.event.inputs.strict == 'true' && '--scopes' || '' }}")
                      % ()})
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_workflows_only_run_command_lines_the_tools_accept():
    """The gate on the real tree, and proof that it is not passing vacuously:
    both tools really do answer with a parser."""
    problems: list = []
    doc_numbers.check_ci_command_lines(REPO, problems)
    assert problems == [], problems
    cache: dict = {}
    for tool in ("tools/public_corpus.py", "tools/verify.py"):
        assert doc_numbers.tool_parser(REPO, tool, cache) is not None, tool


def test_the_real_corpus_workflow_passes_the_selector_in_both_steps():
    """PUB2-10's second half: a dispatch that fetched one repository and then
    analyzed all thirty-seven could not pass either. The two steps are generated
    from one input, so the gate reads them as one claim."""
    lines = doc_numbers._lines(
        REPO / ".github" / "workflows" / "public-corpus.yml")
    selectors = [(n, c) for n, c in doc_numbers._command_lines(lines)
                 if "public_corpus.py" in c and "--repo " in c]
    assert len(selectors) == 2, selectors
    assert any(c.endswith(" fetch") for _, c in selectors), selectors
    assert any(" run " in c for _, c in selectors), selectors
    # ...and it reaches the CLI as one option, not as text pasted into the shell.
    assert all("${REPOS:+" in c for _, c in selectors), selectors


# ---------------------------------------------------------------- check 20
# VIS2-17: docs/ACCURACY.md said "Only MLV101 and MLV102 consume the hop chain"
# long after IP-01 made the payment rule-agnostic. Measured in `ip` on the
# labelled corpus, the rules that paid were MLV101, MLV401 and MLV803 -- the
# sentence named a rule that does not pay and missed two that do.
RULES_CONTEXT = '''\
class RuleContext:
    def note_hops(self, ref, scope=None):
        self._hop_reads.append((self.current_rule.code, scope, ref))
'''

HOP_DOC = """# ACCURACY

## 6 - ip

* **%s** The rest of the paragraph is ordinary prose about `--dataflow ip`.
"""

EXCLUSIVE = "Only MLV101 and MLV102 consume the hop chain.**"
REVERSED = "MLV101 and MLV102 are the only rules that pay for a hop.**"
MEASURED = ("Which rules consume the hop chain is a measurement: MLV101, MLV401 "
            "and MLV803 paid on this corpus.**")


def _hop_tree(sentence, constant=""):
    files = {"README.md": "# mlview\n",
             "docs/ACCURACY.md": HOP_DOC % sentence,
             "analyzer/src/mlview/rules/context.py": RULES_CONTEXT}
    if constant:
        files["analyzer/src/mlview/rules/confidence.py"] = constant
    return _tree(files)


def test_an_exclusive_list_of_hop_paying_rules_is_caught():
    root = _hop_tree(EXCLUSIVE)
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "VIS2-17" in problems[0]
        assert "MLV101, MLV102" in problems[0], problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_same_claim_written_the_other_way_round_is_caught():
    root = _hop_tree(REVERSED)
    try:
        problems = check_docs.run(root)[0]
        assert len(problems) == 1, problems
        assert "VIS2-17" in problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_list_is_allowed_when_the_code_holds_one():
    """The gate is against a list nobody can check, not against lists."""
    root = _hop_tree(EXCLUSIVE,
                     constant='HOP_CHAIN_CODES = ("MLV101", "MLV102")\n')
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_measurement_is_not_a_claim_of_exclusivity():
    root = _hop_tree(MEASURED)
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_only_and_a_rule_code_in_two_different_bullets_are_two_claims():
    """The first run of this check read a whole Markdown list as one block and
    reported three sentences that had nothing to do with each other."""
    root = _hop_tree("Fine.**\n\n* The absence rules (`MLV301`, `MLV302`) reach "
                     "one import hop, no further.\n* A gate de-rates a finding "
                     "only when a wrapper is in the module.")
    try:
        assert check_docs.run(root)[0] == [], check_docs.run(root)[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_real_docs_make_no_unheld_claim_about_who_pays_for_a_hop():
    problems: list = []
    current, _ = check_docs.docs(REPO)
    doc_numbers.check_hop_claims(REPO, current, problems)
    assert problems == [], problems
    assert doc_numbers.hop_code_constants(REPO) == [], (
        "a constant now enumerates hop-paying rule codes; check 20 will start "
        "allowing a list in the prose, so say which constant it is here")


def main() -> int:
    """Standalone entry point; scripts/test_check_docs.py runs these as well."""
    from test_check_docs import run_module

    failed = run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_numbers self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
