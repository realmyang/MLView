"""RAIL-GROUP, CLI half: `--group-by rule|file|none`.

The measured failure: a 50-file workspace prints **111 flat rows that are 11
codes x 10 identical repeats**, and the reader scrolls forty of them to learn
there are five distinct problems. Grouping is a rendering choice - every
occurrence is still counted, `--json` is untouched, and `none` stays the
default so every existing snapshot holds.
"""

from __future__ import annotations

import json

import pytest

from mlview import cli
from mlview.emit.group_out import group_rows

#: One module with three planted defects (MLV110 + MLV201 + MLV205), written
#: ten times, plus the workspace-wide MLV601 - the 11-codes-x-10-repeats shape
#: the audit measured, in miniature: 31 flat rows saying four things.
REPEATED = ("import torch\n"
            "import torch.nn as nn\n"
            "import torch.optim as optim\n"
            "from torch.utils.data import DataLoader\n\n\n"
            "def train_%d(ds):\n"
            "    model = nn.Linear(4, 2)\n"
            "    crit = nn.CrossEntropyLoss()\n"
            "    opt = optim.Adam(model.parameters())\n"
            "    loader = DataLoader(ds, batch_size=8)\n"
            "    total = 0\n"
            "    for x, y in loader:\n"
            "        loss = crit(model(x), y)\n"
            "        loss.backward()\n"
            "        opt.step()\n"
            "        total += loss\n"
            "    return total\n")

FILES = 10
#: 3 per file, plus one workspace-wide MLV601.
TOTAL_ISSUES = FILES * 3 + 1
CODES = 4


@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out.decode("utf-8", "replace"), captured.err
    return _run


@pytest.fixture
def repeats(make_workspace):
    return make_workspace({"pipeline_%d.py" % n: REPEATED % n for n in range(FILES)})


def _body(text):
    """The table under the `N issue(s) in ...` header, without the rules."""
    return [line for line in text.splitlines()[1:]
            if line.strip() and not line.strip().startswith("---")]


def test_flat_is_the_default_and_prints_one_row_per_finding(run, repeats):
    code, out, _err = run("issues", repeats)
    assert code == 0
    rows = _body(out)[1:]                       # drop the column header
    assert len(rows) == TOTAL_ISSUES


def test_group_by_rule_collapses_to_one_row_per_code(run, repeats):
    code, out, _err = run("issues", repeats, "--group-by", "rule")
    assert code == 0
    rows = _body(out)[1:]
    assert len(rows) == CODES                   # 31 rows become 4
    for code in ("MLV110", "MLV201", "MLV205"):
        assert any(code in r and "10 occurrences in 10 files" in r
                   for r in rows), (code, out)
    assert any("MLV601" in r and "1 occurrence in 1 file" in r for r in rows), out


def test_group_by_file_collapses_to_one_row_per_file(run, repeats):
    code, out, _err = run("issues", repeats, "--group-by", "file")
    assert code == 0
    rows = _body(out)[1:]
    assert len(rows) == FILES
    assert sum("3 occurrences · 3 rules" in r for r in rows) == FILES - 1, out
    assert sum("4 occurrences · 4 rules" in r for r in rows) == 1, out
    assert "MLV110, MLV201, MLV205" in out


def test_grouping_never_changes_the_count_in_the_header(run, repeats):
    _c1, flat, _e1 = run("issues", repeats)
    _c2, grouped, _e2 = run("issues", repeats, "--group-by", "rule")
    assert flat.splitlines()[0] == grouped.splitlines()[0]
    assert flat.splitlines()[0].startswith("%d issue(s)" % TOTAL_ISSUES)


def test_group_by_is_a_rendering_choice_not_a_filter(run, repeats):
    """`--json` is byte-identical with and without the flag."""
    _c1, plain, _e1 = run("issues", repeats, "--json")
    _c2, grouped, _e2 = run("issues", repeats, "--json", "--group-by", "rule")
    assert plain == grouped
    assert len(json.loads(plain)["issues"]) == TOTAL_ISSUES


def test_analyze_summary_takes_the_same_flag(run, repeats):
    code, out, _err = run("analyze", repeats, "--group-by", "rule")
    assert code == 0
    assert "OCCURRENCES" in out and "10 occurrences in 10 files" in out


def test_analyze_summary_default_is_unchanged(run, repeats):
    _c1, plain, _e1 = run("analyze", repeats)
    _c2, explicit, _e2 = run("analyze", repeats, "--group-by", "none")
    assert plain == explicit
    assert "LOCATION" in plain and "OCCURRENCES" not in plain


def test_a_bad_group_by_is_a_usage_error(run, repeats):
    assert run("issues", repeats, "--group-by", "severity")[0] == cli.EXIT_USAGE


# ------------------------------------------------------------------- unit
def test_group_rows_reports_worst_severity_and_bucket():
    issues = [
        {"code": "MLV1", "severity": "low", "confidenceBucket": "possible",
         "title": "t", "loc": {"file": "a.py", "line": 1}},
        {"code": "MLV1", "severity": "high", "confidenceBucket": "certain",
         "title": "t", "loc": {"file": "b.py", "line": 2}},
    ]
    rows = group_rows(issues, "rule")
    assert len(rows) == 1
    assert rows[0]["severity"] == "high"
    assert rows[0]["bucket"] == "certain"
    assert rows[0]["count"] == 2 and rows[0]["files"] == ["a.py", "b.py"]


def test_group_rows_is_empty_for_none():
    assert group_rows([{"code": "MLV1", "loc": {}}], "none") == []
