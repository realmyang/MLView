"""CLEANUP: the analyzer-owned half of the hygiene PR.

Four independently verified defects, each one to three lines, none of which
deserved a ticket of its own:

1. `issues --text` was declared with `dest="text_out"` and read by nobody - a
   `diff` of the two invocations was **byte-identical**, so the obvious command
   for "show me the issues" was the one that hid the fix hints.
2. `suppress.py` interpolated the raw `path`, so the config warning printed a
   mixed-separator path on Windows.
3. A typo'd rule code (`MVL601 = "off"`, `MLV999 = "off"`) was accepted in
   **total silence**: `diagnostics: []`.
6. `rules --list` truncated the framework column mid-word (`sklearn,p`,
   `torch,lig`).

(4, 5 and 7 belong to the VS Code extension and the plugin.)
"""

from __future__ import annotations

import sys

import pytest

from mlview import cli
from mlview.rules.suppress import load_config, unknown_code_warning

LEAKY = ("import torch\n"
         "import torch.nn as nn\n"
         "import torch.optim as optim\n"
         "from torch.utils.data import DataLoader\n\n\n"
         "def train(ds):\n"
         "    model = nn.Linear(4, 2)\n"
         "    crit = nn.CrossEntropyLoss()\n"
         "    opt = optim.Adam(model.parameters())\n"
         "    loader = DataLoader(ds, batch_size=8)\n"
         "    for x, y in loader:\n"
         "        loss = crit(model(x), y)\n"
         "        loss.backward()\n"
         "        opt.step()\n")


@pytest.fixture
def run(capsysbinary):
    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return (code, captured.out.decode("utf-8", "replace"),
                captured.err.decode("utf-8", "replace"))
    return _run


@pytest.fixture
def workspace(make_workspace):
    return make_workspace({"train.py": LEAKY})


# --------------------------------------------------------------- CLEANUP 1
def test_issues_text_is_no_longer_a_no_op(run, workspace):
    _c1, table, _e1 = run("issues", workspace)
    _c2, rich, _e2 = run("issues", workspace, "--text")
    assert table != rich, "--text is still byte-identical to the default"
    assert "why: " in rich and "fix: " in rich
    assert "CONFIDENCE" not in rich          # not the table
    assert "why: " not in table


def test_issues_text_reaches_the_same_renderer_as_analyze_format_text(run, workspace):
    _c1, rich, _e1 = run("issues", workspace, "--text")
    _c2, long_form, _e2 = run("analyze", workspace, "--format", "text")
    for line in rich.splitlines()[1:]:
        if line.strip():
            assert line in long_form, line


def test_issues_text_still_honours_the_filters(run, workspace):
    _code, rich, _err = run("issues", workspace, "--code", "MLV201", "--text")
    assert "MLV201" in rich
    assert "MLV601" not in rich


def test_issues_text_on_a_clean_workspace_says_none_found(run, make_workspace):
    root = make_workspace({"quiet.py": "VALUE = 1\n"})
    _code, out, _err = run("issues", root, "--text")
    assert "none found" in out


# `.mlview.toml` needs a TOML parser, and tomllib is stdlib only from 3.11.
# `rules/suppress.py` degrades on 3.10 by appending a `config_warning` and
# ignoring the file, so below 3.11 the two tests under this mark would be
# asserting the behaviour of a parser that is not there — CLEANUP 2's warning
# and CLEANUP 3's near-miss list are both computed after the parse. The
# degradation itself is asserted by
# `analyzer/tests/rules/test_suppression.py::test_a_missing_tomllib_says_so_instead_of_pretending`.
# Same mark, same reason, as `tests/rules/test_suppression.py` and
# `tests/core/test_robustness.py`. CI-01 put 3.10 in the matrix; this is what it
# found on the first push of Sprint 3's Track B.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; .mlview.toml is ignored with a config_warning below that",
)


# --------------------------------------------------------------- CLEANUP 2
@NEEDS_TOMLLIB
def test_the_config_warning_prints_one_separator(tmp_path):
    config = tmp_path / "sub" / ".mlview.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[rules]\nMLV201 = "high"\n', encoding="utf-8")
    resolved = load_config(str(config))
    assert len(resolved.warnings) == 1
    warning = resolved.warnings[0]
    assert "\\" not in warning, warning
    assert resolved.path in warning


# --------------------------------------------------------------- CLEANUP 3
@NEEDS_TOMLLIB
def test_a_typod_code_in_the_config_is_no_longer_silent(tmp_path):
    config = tmp_path / ".mlview.toml"
    config.write_text('[rules]\nMVL601 = "off"\nMLV999 = "off"\n', encoding="utf-8")
    warnings = load_config(str(config)).warnings
    assert len(warnings) == 2
    joined = " ".join(warnings)
    assert "MVL601" in joined and "MLV999" in joined
    assert "Did you mean MLV601" in joined, joined


def test_a_typod_code_in_an_ignore_comment_is_no_longer_silent(analyze_ws):
    doc = analyze_ws({"train.py": LEAKY.replace(
        "def train(ds):", "def train(ds):  # mlview: ignore[MLV20]")})
    warnings = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"]
    assert len(warnings) == 1
    assert "MLV20" in warnings[0]["message"]
    assert "MLV205" in warnings[0]["message"]      # a near miss is offered


def test_a_correct_code_stays_silent(analyze_ws):
    doc = analyze_ws({"train.py": LEAKY.replace(
        "        opt.step()", "        opt.step()  # mlview: ignore[MLV201]")})
    assert [d for d in doc["diagnostics"] if d["kind"] == "config_warning"] == []


def test_unknown_code_warning_returns_none_for_a_real_code():
    assert unknown_code_warning("MLV201", "x") is None


# --------------------------------------------------------------- CLEANUP 6
def test_rules_list_never_cuts_a_framework_name(run):
    """`sklearn,p` and `torch,lig` used to be what a 9-character slice left."""
    from mlview.rules import all_rules

    _code, out, _err = run("rules", "--list")
    rows = [line for line in out.splitlines()[1:] if line.strip()]
    specs = all_rules()
    assert len(rows) == len(specs)
    names = {name for spec in specs for name in spec.frameworks} | {"any"}
    for row, spec in zip(rows, specs):
        column = row[:row.index(spec.title)][16:].strip()
        assert column == (", ".join(spec.frameworks) or "any"), row
        for name in column.split(", "):
            assert name in names, (name, row)


def test_rules_list_columns_line_up(run):
    """The framework column is as wide as its widest value, not a fixed 9."""
    from mlview.rules import all_rules

    _code, out, _err = run("rules", "--list")
    rows = [line for line in out.splitlines()[1:] if line.strip()]
    specs = all_rules()
    assert len(rows) == len(specs)
    offsets = {row.index(spec.title) for row, spec in zip(rows, specs)}
    assert len(offsets) == 1, sorted(offsets)
    # and the widest framework value fits without being cut
    widest = max((", ".join(s.frameworks) or "any" for s in specs), key=len)
    assert widest in out, widest
