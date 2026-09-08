"""ROADMAP RAIL-GROUP, host half — `mlview_issues(groupBy=...)`.

Two audits measured the same failure on two corpora: **113 rows from 12 distinct
codes**, and **111 rows that are 11 codes x 10 identical repeats**. Over MCP the
flat list is worse than in a rail, because the 4 KB budget sheds rows until the
answer is both long and incomplete — the model reads ten copies of MLV702 and
never learns there are only twelve distinct problems.

The property that matters is that grouping **folds** and never **filters**: a
group's `count` still describes every finding that passed minSeverity /
minConfidence / code / scope, so an answer built from groups can never be a
quieter answer than the flat one. That is what most of this file asserts.
"""

from __future__ import annotations

import pytest

import mlview_groups as groups
import mlview_payloads as payloads
from mlview_budget import LIMIT_BYTES, payload_size
from plugin_support import synthetic_graph


@pytest.fixture(scope="module")
def graph():
    """Big enough that the flat answer needs the 4 KB budget's help."""
    return synthetic_graph(nodes=200, edges=300, issues=120)


def _issue(index, code, severity, path):
    return {
        "id": "i:%d" % index,
        "code": code,
        "severity": severity,
        "confidence": 0.9,
        "confidenceBucket": "certain",
        "title": "T%d" % index,
        "message": "m",
        "fixHint": "f",
        "loc": {"file": path, "line": index + 1},
        "relatedLocs": [],
        "suppressed": False,
    }


@pytest.fixture(scope="module")
def small():
    """Terse on purpose: the arithmetic tests must compare group counts against the
    flat rows, and on any graph big enough to need the 4 KB budget's help the flat
    payload has legitimately shed rows while the group counts still cover them."""
    return {
        "issues": [
            _issue(0, "MLV201", "high", "train.py"),
            _issue(1, "MLV201", "high", "model.py"),
            _issue(2, "MLV201", "high", "data.py"),
            _issue(3, "MLV301", "medium", "train.py"),
            _issue(4, "MLV601", "low", "data.py"),
            dict(_issue(5, "MLV101", "high", "data.py"), suppressed=True),
        ],
        "workspace": {"filesAnalyzed": 3, "filesFailed": 0, "notebooksSkipped": 0},
        "diagnostics": [],
    }


def _codes(payload):
    return [row["key"] for row in payload["groups"]]


# --------------------------------------------------------------- the argument itself
def test_the_accepted_modes_are_the_three_the_cli_flag_takes():
    assert groups.GROUP_BY_MODES == ("rule", "file", "severity")


@pytest.mark.parametrize("bad", ["bogus", "rules", "code", "1", " ", "RULE!"])
def test_an_unknown_group_by_is_refused_and_the_error_names_the_real_values(graph, bad):
    with pytest.raises(ValueError) as excinfo:
        payloads.issues_payload(graph, group_by=bad, limit=300)
    message = str(excinfo.value)
    assert "groupBy" in message
    for accepted in groups.GROUP_BY_MODES:
        assert accepted in message


@pytest.mark.parametrize("mode", ["rule", "RULE", " file ", "Severity"])
def test_the_mode_is_case_and_whitespace_tolerant(graph, mode):
    payload = payloads.issues_payload(graph, group_by=mode, limit=300)
    assert payload["groupBy"] == mode.strip().lower()


def test_omitting_group_by_leaves_the_payload_exactly_as_it_was(graph):
    assert payloads.issues_payload(graph, limit=20) == payloads.issues_payload(
        graph, group_by=None, limit=20
    )
    assert "groups" not in payloads.issues_payload(graph, limit=20)
    assert "groupBy" not in payloads.issues_payload(graph, limit=20)


# ------------------------------------------------------------------ folding, not filtering
def test_the_group_counts_add_up_to_every_finding_the_filters_kept(small):
    flat = payloads.issues_payload(small, limit=100000)
    grouped = payloads.issues_payload(small, group_by="rule", limit=100000)
    assert flat["truncated"] is False, "the fixture must not need shedding"
    assert sum(row["count"] for row in grouped["groups"]) == len(flat["issues"])


def test_a_stricter_severity_narrows_the_groups_the_same_way_it_narrows_the_rows(small):
    high_flat = payloads.issues_payload(small, min_severity="high", limit=100000)
    high_grouped = payloads.issues_payload(
        small, min_severity="high", group_by="rule", limit=100000
    )
    assert sum(r["count"] for r in high_grouped["groups"]) == len(high_flat["issues"])
    assert all(row["maxSeverity"] == "high" for row in high_grouped["groups"])


def test_grouping_by_rule_collapses_the_repeats_to_one_row_per_code(small):
    flat = payloads.issues_payload(small, limit=100000)
    grouped = payloads.issues_payload(small, group_by="rule", limit=100000)
    assert set(_codes(grouped)) == {row["code"] for row in flat["issues"]}


def test_a_hundred_findings_become_a_readable_number_of_rows(graph):
    grouped = payloads.issues_payload(graph, group_by="rule", limit=100000)
    flat = payloads.issues_payload(graph, limit=100000)
    assert sum(r["count"] for r in grouped["groups"]) > len(flat["issues"]), (
        "the flat answer had to shed rows; the grouped one still covers them all"
    )
    assert len(grouped["groups"]) <= 20, "one row per rule code, not per finding"


def test_a_group_row_carries_the_count_the_files_and_citable_sites(graph):
    grouped = payloads.issues_payload(graph, group_by="rule", limit=100000)
    row = grouped["groups"][0]
    assert row["count"] >= 1
    assert row["files"] >= 1
    assert row["title"]
    assert 1 <= len(row["sites"]) <= groups.MAX_SITES
    assert all(":" in site for site in row["sites"]), "a site must be citable as file:line"


def test_the_rows_are_worst_first_then_biggest_first(graph):
    rows = payloads.issues_payload(graph, group_by="rule", limit=100000)["groups"]
    ranked = [(groups.SEVERITY_RANK[r["maxSeverity"]], r["count"]) for r in rows]
    assert ranked == sorted(ranked, key=lambda pair: (-pair[0], -pair[1]))


def test_grouping_by_file_keys_on_the_file_and_lists_its_codes(graph):
    rows = payloads.issues_payload(graph, group_by="file", limit=100000)["groups"]
    assert all(row["key"].endswith(".py") for row in rows)
    assert all(row["codes"] for row in rows)


def test_grouping_by_severity_yields_at_most_the_three_severities(graph):
    rows = payloads.issues_payload(graph, group_by="severity", limit=100000)["groups"]
    assert set(row["key"] for row in rows) <= {"low", "medium", "high"}
    assert len(rows) <= 3


# ------------------------------------------------------------------------- honesty + budget
def test_a_grouped_payload_says_the_rows_were_folded_and_not_filtered(graph):
    payload = payloads.issues_payload(graph, group_by="rule", limit=100000)
    note = payload["note"]
    assert "grouped by rule" in note
    assert "folded" in note and "not filtered" in note
    assert "omit groupBy" in note, "the model must be told how to get the rows back"


def test_grouping_keeps_a_large_workspace_inside_the_four_kilobyte_budget(graph):
    payload = payloads.issues_payload(graph, group_by="rule", limit=100000)
    assert payload_size(payload) <= LIMIT_BYTES
    assert payload["groups"], "the budget must not shed every row"
    assert payload["countBySeverity"], "the counts are protected and always survive"


def test_a_scoped_grouped_answer_still_carries_the_filtered_view_note(graph):
    payload = payloads.issues_payload(
        graph, group_by="rule", scope="stage:train", limit=100000
    )
    assert payload["scope"] == "stage:train"
    assert "grouped by rule" in payload["note"]
    assert "filtered view" in payload["note"]


def test_an_empty_result_groups_to_nothing_rather_than_to_a_clean_bill_of_health():
    empty = {"issues": [], "workspace": {"filesAnalyzed": 0}, "diagnostics": []}
    payload = payloads.issues_payload(empty, group_by="rule")
    assert payload["groups"] == []
    assert "NOT a clean bill of health" in payload["note"]
