#!/usr/bin/env python
"""Tests for scripts/doc_figures.py -- checks 13, 14 and 15 of the doc gate.

Same shape as `scripts/test_check_docs.py`, whose `_tree` helper and `REPO` these
reuse: each case builds a throwaway tree and runs the check against it, so
nothing here depends on the state of the real repo. The last three cases *do*
read the real repo and assert the three defects that motivated these checks are
gone from it.

REV5-05: `docs/STATUS.md`'s Components table was refreshed in Sprint 5 wave 1 and
left behind by waves 2 and 3, so every row was contradicted 1900 lines lower by
the same document's own gate paragraph, and its `core/mlview` file count said 88
where `tools/verify.py --all` printed 96.
REV5-08: `README.md` called `contracts/scope.cases.json` "the ten-selector
battery" while the file held 13 projecting cases, 7 error cases and 5 promoted
counterexamples.
REV5-07: `README.md` and `scripts/README.md` named two different runs as "the
last full green push" in the same commit.

`scripts/test_check_docs.py` runs these too, so the drivers and CI keep one
doc-gate self-test entry point. Run either file under pytest for the same set.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs  # noqa: E402
import doc_figures  # noqa: E402
from test_check_docs import REPO, _tree  # noqa: E402

# ------------------------------------------------------------------ check 13
TABLE = """# MLView — Build status

## Components

| Piece | State |
|---|---|
| Analyzer `analyzer/` | Complete. **36 rules**. **%s passed, %s skipped** on 3.11+. |
| Viewer `webview/` | Complete. **%s tests pass**, `tsc --noEmit` clean. |
| VS Code extension | Complete. **%s tests pass**, bundled. |
| Claude Code plugin | Complete. **%s passed, %s skipped**, vendored. |

## Wave 3

Prose about the wave.

**Gates, all re-run on this Mac at the integrated tree.** `sh scripts/e2e.sh`
**20 steps, 0 failed**; analyzer **2024 passed / 4 skipped** (1929 / 4 at wave
2); webview **521 tests** (473); vscode-extension **372 tests**; claude-plugin
**370 passed / 7 skipped** (366 / 7); `python tools/verify.py --all` **10 of 10**.
"""

CURRENT = TABLE % ("2024", "4", "521", "372", "370", "7")
STALE = TABLE % ("1855", "4", "419", "336", "356", "7")


def _figures(root: Path, docs=("README.md", "docs/STATUS.md", "scripts/README.md")):
    """Run all three checks the way `check_docs.run` does, on one throwaway tree."""
    problems: list = []
    paths = [root / rel for rel in docs if (root / rel).is_file()]
    doc_figures.run(root, paths, problems)
    return problems


def test_a_components_table_left_behind_by_the_run_below_it_is_caught():
    """REV5-05: four stale rows, each contradicted by the same file's gates."""
    root = _tree({"docs/STATUS.md": STALE})
    try:
        problems = _figures(root)
        assert len(problems) == 4, problems
        assert all("REV5-05" in p for p in problems), problems
        joined = " ".join(problems)
        for package, said, holds in (("analyzer", "1855", "2024"),
                                     ("webview", "419", "521"),
                                     ("vscode-extension", "336", "372"),
                                     ("claude-plugin", "356", "370")):
            assert "says %s has %s tests" % (package, said) in joined, joined
            assert "says %s" % holds in joined, joined
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_components_table_that_agrees_with_its_gate_paragraph_passes():
    root = _tree({"docs/STATUS.md": CURRENT})
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_stale_skip_count_is_caught_on_its_own():
    """The skips are half the claim: `2024 passed, 3 skipped` is still wrong."""
    root = _tree({"docs/STATUS.md": TABLE % ("2024", "3", "521", "372", "370", "7")})
    try:
        problems = _figures(root)
        assert len(problems) == 1, problems
        assert "says analyzer has 3 skips" in problems[0], problems[0]
        assert "says 4" in problems[0], problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_newest_gate_paragraph_is_the_one_that_binds():
    """A document appends waves, so an older paragraph may not settle the table."""
    older = """
**Gates, all on this Mac.** analyzer **1855 passed / 4 skipped**; webview
**419 tests**; vscode-extension **336 tests**; claude-plugin **356 passed / 7
skipped**.

"""
    root = _tree({"docs/STATUS.md": STALE.replace("## Wave 3", older + "## Wave 3")})
    try:
        problems = _figures(root)
        assert len(problems) == 4, problems
        assert "says 2024" in " ".join(problems), problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


VSIX_ROW = ("| VS Code extension | Complete. **372 tests pass**, `npm run package`"
            " produced a **744.45 KB VSIX (148 files)**, with `core/mlview` at "
            "**%d** files. |\n")


def _vsix_tree(claimed: int, extra: str = "") -> Path:
    root = _tree({"docs/STATUS.md": "# S\n\n## Components\n\n" + VSIX_ROW % claimed + extra,
                  "analyzer/src/mlview/__init__.py": "",
                  "analyzer/src/mlview/core/project.py": "",
                  "analyzer/src/mlview/core/__pycache__/project.cpython-313.pyc": "",
                  "analyzer/src/mlview/tests/test_x.py": ""})
    (root / "tools").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "tools" / "sync-core.py", root / "tools" / "sync-core.py")
    return root


def test_the_bundled_core_file_count_is_checked_against_the_tree():
    """REV5-05's machine-checkable half: two source files, not three."""
    root = _vsix_tree(3)
    try:
        problems = _figures(root)
        assert len(problems) == 1, problems
        assert "at 3 files" in problems[0] and "copies 2" in problems[0], problems[0]
        assert "vsix: synced core" in problems[0], problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_bundled_core_count_skips_bytecode_and_tests_like_sync_core_does():
    root = _vsix_tree(2)
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_past_rounds_vsix_figure_in_prose_is_a_record_not_a_claim():
    """HOST-8's incident paragraph quotes 79 on purpose; it is history."""
    prose = ("\nThe VSIX figures are measured by a gate now: this file said "
             "`core/mlview` at **79** files while `tools/verify.py --all` printed "
             "**80** for the same directory on the same commit.\n")
    root = _vsix_tree(2, extra=prose)
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ check 14
BATTERY = {"cases": [{"kind": "project", "name": "p%d" % i} for i in range(2)]
                    + [{"kind": "error", "name": "e0"}],
           "fuzzCases": [{"name": "f%d" % i} for i in range(3)]}


def _battery_tree(readme: str) -> Path:
    return _tree({"README.md": readme,
                  "contracts/scope.cases.json": json.dumps(BATTERY, indent=2)})


def test_the_ten_selector_battery_is_caught_years_after_it_stopped_being_ten():
    """REV5-08, in the exact words that survived three sprints."""
    root = _battery_tree("# MLView\n\nAll four parity gates: the ten-selector "
                         "battery in\n`contracts/scope.cases.json` projects "
                         "identically through both ports.\n")
    try:
        problems = _figures(root)
        assert len(problems) == 1, problems
        assert "REV5-08" in problems[0] and "holds ten selector(s)" in problems[0], problems[0]
        assert "holds 2" in problems[0], problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_error_cases_and_promoted_counterexamples_are_counted_too():
    root = _battery_tree("# MLView\n\n`contracts/scope.cases.json`: 2 projections "
                         "+ 6 error cases, plus the 5 promoted counterexamples.\n")
    try:
        problems = _figures(root)
        assert len(problems) == 2, problems
        joined = " ".join(problems)
        assert "holds 6 error case(s)" in joined and "holds 1" in joined, joined
        assert "holds 5 promoted counterexample(s)" in joined, joined
        assert "holds 3" in joined, joined
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_right_battery_figures_pass_and_a_bare_case_count_is_not_a_claim():
    """`200 fuzz cases` and `40 generated graphs` are about the fuzzer, not the
    file: only the six counted nouns are claims about its size."""
    root = _battery_tree("# MLView\n\n`contracts/scope.cases.json`: 2 projections "
                         "+ 1 error case + 3 promoted counterexamples, and "
                         "`--fuzz 200` runs 200 cases over 40 generated graphs.\n")
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_block_that_says_it_is_history_escapes_check_14():
    """Check 8's `at the time` escape, reused: `fuzzCases` grew from three to
    five, and the sentence recording that may not be rewritten."""
    root = _battery_tree("# MLView\n\nTwo counterexamples were promoted into "
                         "`contracts/scope.cases.json`, which held 3 promoted "
                         "counterexamples at the time.\n")
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_only_the_living_docs_are_held_to_the_battery():
    """A frozen design record quoting the old size is a record, not a claim."""
    root = _tree({"docs/FEATURES_FLOW_AND_SCOPE.md":
                  "The ten-selector battery in `contracts/scope.cases.json`.\n",
                  "contracts/scope.cases.json": json.dumps(BATTERY)})
    try:
        problems: list = []
        doc_figures.run(root, [root / "docs/FEATURES_FLOW_AND_SCOPE.md"], problems)
        assert problems == [], problems
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ check 15
def test_two_documents_naming_two_last_green_pushes_is_caught():
    """REV5-07: README said run 34422156964, the gate table said 34441571480."""
    root = _tree({
        "README.md": "# MLView\n\n**Measured** — the last full green push\n"
                     "(run 34422156964, Sprint 5's process wave) took 6m25s.\n",
        "scripts/README.md": "# scripts\n\n| 25 | CI | On the last full green "
                             "push (run 34441571480): 12 jobs green. |\n"})
    try:
        problems = _figures(root)
        assert len(problems) == 1, problems
        assert "REV5-07" in problems[0], problems[0]
        assert "34422156964" in problems[0] and "34441571480" in problems[0], problems[0]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_paragraph_that_narrates_the_incident_may_quote_both_runs():
    """Check 8's `at the time` escape again: `scripts/README.md` explains REV5-07
    by naming both runs, and that sentence is a record."""
    root = _tree({"scripts/README.md": "# scripts\n\n`README.md` named run "
                                       "34422156964 as the last full green push "
                                       "at the time while row 25 named the later "
                                       "run 34441571480 (REV5-07).\n",
                  "README.md": "# MLView\n\nthe last full green push "
                               "(run 34441571480) took 8m09s.\n"})
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_one_run_id_everywhere_passes():
    root = _tree({
        "README.md": "# MLView\n\nthe last full green push (run 34441571480,\n"
                     "Sprint 5's wave 3) took 8m09s across 12 green jobs.\n",
        "scripts/README.md": "# scripts\n\n| 25 | CI | On the last full green "
                             "push (run 34441571480): 12 jobs green. |\n"})
    try:
        assert _figures(root) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------- the real repo
def test_the_real_components_table_agrees_with_the_real_gate_paragraph():
    """And is not vacuously clean, in both directions: the table must quote four
    counts, and so must the newest gate paragraph -- a wave that records its
    figures without naming the packages would silently switch this check off."""
    problems: list = []
    doc_figures.check_summary_table(REPO, problems)
    assert problems == [], "\n".join(problems)
    lines = doc_figures._lines(REPO / "docs/STATUS.md")
    rows = [line for _, row_re in doc_figures.PACKAGE_ROWS for line in lines
            if row_re.match(line) and doc_figures.COUNT_RE.search(line)]
    assert len(rows) == 4, rows
    assert any(doc_figures.CORE_FILES_RE.search(line) for line in rows), rows

    gate_at = [n for n, line in enumerate(lines)
               if doc_figures.GATE_PARA_RE.match(line)]
    assert gate_at, "docs/STATUS.md has no `**Gates` paragraph to check against"
    paragraph = doc_figures._paragraph_from(lines, gate_at[-1])
    missing = [package for package, _ in doc_figures.PACKAGE_ROWS
               if not re.search(r"\b%s\s+%s" % (re.escape(package), doc_figures.COUNT),
                                paragraph)]
    assert not missing, ("the newest gate paragraph (line %d) records no test "
                         "count for %s" % (gate_at[-1] + 1, ", ".join(missing)))


def test_the_real_docs_quote_the_real_battery():
    counts = doc_figures._battery(REPO)
    assert counts == {"project": 13, "error": 7, "fuzz": 5}, counts
    current, _ = check_docs.docs(REPO)
    problems: list = []
    doc_figures.check_scope_battery(REPO, current, problems)
    assert problems == [], "\n".join(problems)


def test_the_real_docs_name_one_last_green_push():
    current, _ = check_docs.docs(REPO)
    problems: list = []
    doc_figures.check_one_green_push(REPO, current, problems)
    assert problems == [], "\n".join(problems)
    text = io.open(REPO / "README.md", encoding="utf-8").read()
    assert "last full green push" in text, "README no longer makes the claim"


def main() -> int:
    from test_check_docs import run_module

    failed = run_module(sys.modules[__name__])
    print(("%d test(s) failed" % failed) if failed else "doc_figures self-test OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
