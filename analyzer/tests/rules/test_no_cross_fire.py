"""The union of every `_good.py` fixture, analyzed as one workspace, is silent.

This is the cheapest possible precision gate and the one that catches the most
regressions: every good fixture is deliberately *near* the boundary of its own
rule, so twenty of them in one workspace is twenty adversarial inputs for every
other rule at once - including the cross-file failure modes (a `model` in one
file being confused with a `model` in another, a wrapper in one file gating an
absence rule in another, a seed in one file satisfying MLV601 for all of them).
"""

from __future__ import annotations

import os
import shutil

import pytest

from rule_harness import analyze_paths, describe, good_fixtures, validate


@pytest.fixture(scope="module")
def union(tmp_path_factory):
    """Every `_good.py` copied into one directory and analyzed together."""
    root = tmp_path_factory.mktemp("all_good")
    for path in good_fixtures():
        shutil.copyfile(path, os.path.join(str(root), os.path.basename(path)))
    return analyze_paths(str(root))


def test_the_union_of_every_good_fixture_yields_zero_issues(union):
    assert union["issues"] == [], (
        "a rule fired on correct code: %s" % describe(union))


def test_the_union_still_produces_a_real_graph(union):
    """Silence has to mean 'nothing wrong', not 'nothing analyzed'."""
    assert union["workspace"]["filesAnalyzed"] == len(good_fixtures())
    assert union["workspace"]["filesFailed"] == 0
    assert len(union["nodes"]) > 60
    assert len(union["edges"]) > 30
    present = [s["id"] for s in union["stages"] if s["present"]]
    assert {"data", "model", "objective", "train"} <= set(present)


def test_the_union_document_is_contract_valid(union):
    assert validate(union) == []


def test_every_good_fixture_is_silent_on_its_own_too():
    """A rule must not need its neighbours' code to stay quiet."""
    noisy = []
    for path in good_fixtures():
        doc = analyze_paths(path)
        if doc["issues"]:
            noisy.append("%s -> %s" % (os.path.basename(path), describe(doc)))
    assert not noisy, "\n".join(noisy)


def test_no_rule_errors_were_swallowed(union):
    """A rule that raised would show up as a diagnostic, not as silence."""
    errors = [d for d in union["diagnostics"] if d["kind"] == "rule_error"]
    assert errors == [], errors
