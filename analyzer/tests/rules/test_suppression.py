"""Suppression: the inline comment, the file header, and `.mlview.toml`.

A suppressed issue is **still emitted**, with `suppressed: true`, so the viewer
can offer "show suppressed" and `stats.suppressed` can count it - hosts filter
it out of the Problems panel. That distinction is what these tests pin down.
"""

from __future__ import annotations

import os
import sys

import pytest

from rule_harness import analyze_paths, write_workspace

BAD_TRAIN = '''"""A batch loop with no zero_grad and an unshuffled training loader."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 2) -> None:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    train_loader = DataLoader(dataset, batch_size=32)
    model.train()
    for epoch in range(epochs):
        for features, labels in train_loader:
            loss = criterion(model(features), labels)
            loss.backward()
            optimizer.step()
'''


def _codes(doc, suppressed=None):
    return sorted(i["code"] for i in doc["issues"]
                  if suppressed is None or bool(i["suppressed"]) is suppressed)


def _issue(doc, code):
    found = [i for i in doc["issues"] if i["code"] == code]
    assert found, "%s did not fire at all: %s" % (
        code, [i["code"] for i in doc["issues"]])
    return found[0]


@pytest.fixture
def workspace(tmp_path):
    def build(source, config=None, name="train.py"):
        files = {name: source}
        if config is not None:
            files[".mlview.toml"] = config
        root = write_workspace(str(tmp_path), files)
        return analyze_paths(root)
    return build


# --------------------------------------------------------------- the baseline
def test_the_unsuppressed_baseline_fires(workspace):
    doc = workspace(BAD_TRAIN)
    assert "MLV201" in _codes(doc)
    assert "MLV110" in _codes(doc)
    assert _codes(doc, suppressed=True) == []
    assert doc["stats"].get("suppressed", 0) == 0


# ------------------------------------------------------------- inline comment
def test_inline_ignore_on_the_reported_line(workspace):
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        for features, labels in train_loader:  # mlview: ignore[MLV201]")
    doc = workspace(source)
    assert _issue(doc, "MLV201")["suppressed"] is True
    assert _issue(doc, "MLV110")["suppressed"] is False, "only the named code"


def test_inline_ignore_on_the_line_above(workspace):
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        # mlview: ignore[MLV201]\n"
        "        for features, labels in train_loader:")
    doc = workspace(source)
    assert _issue(doc, "MLV201")["suppressed"] is True


def test_a_bare_ignore_covers_every_code_on_that_line(workspace):
    source = BAD_TRAIN.replace(
        "    train_loader = DataLoader(dataset, batch_size=32)",
        "    train_loader = DataLoader(dataset, batch_size=32)  # mlview: ignore")
    doc = workspace(source)
    assert _issue(doc, "MLV110")["suppressed"] is True
    assert _issue(doc, "MLV201")["suppressed"] is False, "a different line"


def test_an_ignore_for_another_code_does_not_suppress_this_one(workspace):
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        for features, labels in train_loader:  # mlview: ignore[MLV999]")
    doc = workspace(source)
    assert _issue(doc, "MLV201")["suppressed"] is False


def test_a_comma_separated_list_suppresses_each_code(workspace):
    source = BAD_TRAIN.replace(
        "    train_loader = DataLoader(dataset, batch_size=32)",
        "    train_loader = DataLoader(dataset, batch_size=32)"
        "  # mlview: ignore[MLV110, MLV112]")
    doc = workspace(source)
    assert _issue(doc, "MLV110")["suppressed"] is True


# ------------------------------------------------------------------ file-wide
def test_ignore_file_in_the_header_suppresses_everything(workspace):
    doc = workspace("# mlview: ignore-file\n" + BAD_TRAIN)
    assert _codes(doc, suppressed=False) == []
    assert _codes(doc, suppressed=True), "the issues are still emitted"
    assert doc["stats"]["suppressed"] == len(doc["issues"])


def test_ignore_file_below_the_header_does_nothing(workspace):
    source = BAD_TRAIN.replace(
        "def train(", "# mlview: ignore-file\ndef train(")
    doc = workspace(source)
    assert _issue(doc, "MLV201")["suppressed"] is False


# --------------------------------------------------------------- .mlview.toml
# `.mlview.toml` needs a TOML parser, and tomllib is stdlib only from 3.11.
# `rules/suppress.py:53-55` degrades on 3.10 by appending a `config_warning` and
# ignoring the file, so on 3.10 these tests would be asserting the behaviour of a
# parser that is not there. The degradation itself is asserted by
# `test_a_missing_tomllib_says_so_instead_of_pretending`
# (analyzer/tests/rules/test_suppression.py). CI-01 put 3.10 in the matrix and
# this is what it found.
NEEDS_TOMLLIB = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; .mlview.toml is ignored with a config_warning below that",
)


@NEEDS_TOMLLIB
def test_mlview_toml_disable_marks_the_issue_suppressed(workspace):
    doc = workspace(BAD_TRAIN, config='[rules]\ndisable = ["MLV201"]\n')
    assert doc["workspace"]["configPath"].endswith(".mlview.toml")
    assert _issue(doc, "MLV201")["suppressed"] is True
    assert _issue(doc, "MLV110")["suppressed"] is False


@NEEDS_TOMLLIB
def test_mlview_toml_disable_is_case_insensitive(workspace):
    doc = workspace(BAD_TRAIN, config='[rules]\ndisable = ["mlv201"]\n')
    assert _issue(doc, "MLV201")["suppressed"] is True


@NEEDS_TOMLLIB
def test_mlview_toml_key_off_form(workspace):
    doc = workspace(BAD_TRAIN, config='[rules]\nMLV201 = "off"\n')
    assert _issue(doc, "MLV201")["suppressed"] is True


@NEEDS_TOMLLIB
def test_mlview_toml_cannot_regrade_a_severity(workspace):
    """Severities are fixed; an override is a `config_warning`, not a change."""
    doc = workspace(BAD_TRAIN, config='[rules]\nMLV201 = "low"\n')
    assert _issue(doc, "MLV201")["severity"] == "high"
    warnings = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"]
    assert warnings, doc["diagnostics"]
    assert "severit" in warnings[0]["message"].lower()


@NEEDS_TOMLLIB
def test_mlview_toml_path_exclude_removes_the_file(workspace, tmp_path):
    root = write_workspace(str(tmp_path), {
        "experiments/scratch.py": BAD_TRAIN,
        "keep.py": "import torch\ndevice = torch.device('cpu')\n",
        ".mlview.toml": '[paths]\nexclude = ["experiments/**"]\n',
    })
    doc = analyze_paths(root)
    files = {n["loc"]["file"] for n in doc["nodes"]}
    assert not any(f.startswith("experiments/") for f in files), files


@pytest.mark.skipif(
    sys.version_info >= (3, 11),
    reason="tomllib is present from 3.11, so there is no degradation to observe",
)
def test_a_missing_tomllib_says_so_instead_of_pretending(workspace):
    """On 3.10 the config is ignored -- loudly, and the analysis still stands.

    `rules/suppress.py:53-55` carries a `pragma: no cover` for this branch
    because the only interpreter it runs on was not in any test matrix until
    CI-01. It matters: a user on 3.10 whose `.mlview.toml` does nothing must be
    told so, not left to conclude the rule is broken.
    """
    doc = workspace(BAD_TRAIN, config='[rules]\ndisable = ["MLV201"]\n')
    warnings = [d for d in doc["diagnostics"] if d["kind"] == "config_warning"]
    assert warnings, doc["diagnostics"]
    assert "tomllib is unavailable" in warnings[0]["message"], warnings[0]
    assert _issue(doc, "MLV201")["suppressed"] is False, "the rule is not silently disabled"


# ---------------------------------------------------------------- the contract
def test_a_suppressed_issue_keeps_every_other_field(workspace):
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        for features, labels in train_loader:  # mlview: ignore[MLV201]")
    doc = workspace(source)
    issue = _issue(doc, "MLV201")
    assert issue["suppressed"] is True
    assert issue["severity"] == "high", "suppression is not a downgrade"
    assert issue["confidence"] > 0.5
    assert issue["nodeIds"] and issue["docs"] == "docs/rules/MLV201.md"


def test_stats_suppressed_counts_them(workspace):
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        for features, labels in train_loader:  # mlview: ignore[MLV201]")
    doc = workspace(source)
    assert doc["stats"]["suppressed"] == 1


def test_a_suppressed_absence_rule_still_drops_its_ghost_node(workspace):
    """Invariant 1.1.8 only demands the ghost carry an issue - which it does."""
    source = BAD_TRAIN.replace(
        "        for features, labels in train_loader:",
        "        for features, labels in train_loader:  # mlview: ignore[MLV201]")
    doc = workspace(source)
    ghosts = [n for n in doc["nodes"] if n["ghost"]]
    for ghost in ghosts:
        assert ghost["issueIds"], ghost
