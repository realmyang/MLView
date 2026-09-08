"""ANA-12 - the labelled accuracy corpus, wired into the analyzer suite.

`tools/accuracy.py` is the tool a human runs; this module is the same thing
asserted, so a recall regression or a forbidden finding fails `pytest
analyzer/tests` and not only the dedicated CI job.

The three gates, in the order they matter:

1. **zero `forbidden` findings, ever** - the tolerance is not a baseline and
   never ratchets. A high-severity marker on correct code is the one failure
   the project says costs it its credibility.
2. **recall may only ratchet up** against `baseline.json`, overall, on the
   unseen programs alone, and per rule.
3. **graph fidelity may only ratchet up** - the share of hand-labelled
   human-diagram ops that a node is actually anchored on.

The baseline is a floor, never a pin: a rule that starts finding a defect it
used to miss makes this suite pass and the numbers stale, which is what
`python tools/accuracy.py --update-baseline` is for.
"""

from __future__ import annotations

import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TOOL_PATH = os.path.join(REPO_ROOT, "tools", "accuracy.py")
MIN_PROGRAMS = 8


def _load_tool():
    spec = importlib.util.spec_from_file_location("mlview_accuracy_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


accuracy = _load_tool()


@pytest.fixture(scope="module")
def run():
    """The whole corpus, analyzed once."""
    results, report = accuracy.run_corpus()
    return results, report


@pytest.fixture(scope="module")
def baseline():
    data = accuracy.load_baseline()
    assert data is not None, (
        "analyzer/tests/accuracy/baseline.json is missing - record it with "
        "`python tools/accuracy.py --update-baseline`")
    return data


# ------------------------------------------------------------- the corpus
def test_the_corpus_is_at_least_the_size_the_roadmap_asks_for():
    programs = accuracy.load_programs()
    assert len(programs) >= MIN_PROGRAMS, (
        "ANA-12 asks for at least %d labelled programs, found %d"
        % (MIN_PROGRAMS, len(programs)))
    assert any(not p.tuned for p in programs)
    assert any(p.tuned for p in programs), (
        "the two shipped samples are in the corpus as the tuned ceiling")


def test_every_forbidden_label_cites_a_reason():
    for program in accuracy.load_programs():
        for row in program.forbidden:
            assert row.get("why"), "%s: %s forbids %s without saying why" % (
                program.name, program.labels_path, row.get("code"))


def test_every_labelled_line_exists_in_the_file_it_names():
    """A label pinned to a line that has been edited away is a silent lie."""
    for program in accuracy.load_programs():
        rows = list(program.expected) + list(program.forbidden)
        rows += list(program.graph.get("ops") or [])
        for row in rows:
            line = row.get("line")
            if line is None:
                continue
            path = os.path.join(program.root, row["file"].replace("/", os.sep))
            assert os.path.isfile(path), "%s: no such file %s" % (program.name, path)
            with open(path, "r", encoding="utf-8") as handle:
                count = sum(1 for _ in handle)
            assert 1 <= line <= count, "%s: %s:%s is past end of file (%d lines)" % (
                program.name, row["file"], line, count)


def test_every_labelled_code_is_a_real_rule():
    from mlview.rules.registry import all_rules, discover_rules
    discover_rules()
    known = {rule.code for rule in all_rules()}
    assert known, "the rule registry is empty"
    for program in accuracy.load_programs():
        for row in list(program.expected) + list(program.forbidden):
            assert row["code"] in known, "%s labels unknown rule %s" % (
                program.name, row["code"])


def test_every_expected_label_carries_a_verdict_the_scorer_understands():
    for program in accuracy.load_programs():
        for row in program.expected:
            assert row.get("verdict", "expected") in ("expected", "acceptable")
            assert row.get("severity") in ("low", "medium", "high")
            assert row.get("defect"), "%s: %s has no defect description" % (
                program.name, row["code"])


# ---------------------------------------------------------------- gate one
def test_no_forbidden_finding_fires_anywhere(run):
    results, report = run
    detail = ["%s: %s at %s:%s - the label says %s" % (
        result["name"], hit["issue"]["code"], hit["issue"]["loc"]["file"],
        hit["issue"]["loc"]["line"], hit["label"]["why"])
        for result in results for hit in result["forbidden"]]
    assert report["forbiddenFindings"] == 0, "\n".join(detail)


def test_precision_is_still_total(run):
    """Every unsuppressed finding satisfies a label.

    A new finding that is legitimate but unplanted is not a failure of the
    analyzer - it is a missing label. Add it to that program's `expected` list,
    or to `acceptable` when the tool may reasonably go either way.
    """
    results, report = run
    detail = ["%s: %s at %s:%s (confidence %.2f)" % (
        result["name"], issue["code"], issue["loc"]["file"], issue["loc"]["line"],
        issue.get("confidence", 0.0))
        for result in results for issue in result["unlabelled"]]
    assert report["unlabelledFindings"] == 0, "\n".join(detail)
    assert report["overall"]["precision"] == 1.0


# ---------------------------------------------------------------- gate two
@pytest.mark.parametrize("scope", ["overall", "unseen"])
@pytest.mark.parametrize("key", ["recall", "visibleRecall", "highValueRecall"])
def test_recall_only_ratchets_up(run, baseline, scope, key):
    _, report = run
    was = float(baseline[scope][key])
    now = float(report[scope][key])
    assert now + accuracy.EPSILON >= was, (
        "%s %s fell from %.4f to %.4f; if a rule change earned this, say so and "
        "re-record with `python tools/accuracy.py --update-baseline`"
        % (scope, key, was, now))


def test_per_rule_recall_only_ratchets_up(run, baseline):
    _, report = run
    regressions = []
    for code, data in baseline["perRule"].items():
        was = float(data.get("recall", 0.0))
        now = float(report["perRule"].get(code, {}).get("recall", 0.0))
        if now + accuracy.EPSILON < was:
            regressions.append("%s %.4f -> %.4f" % (code, was, now))
    assert not regressions, "; ".join(regressions)


# -------------------------------------------------------------- gate three
def test_graph_fidelity_only_ratchets_up(run, baseline):
    _, report = run
    was = float(baseline["graphFidelity"]["score"])
    now = float(report["graphFidelity"]["score"])
    assert now + accuracy.EPSILON >= was, (
        "graph fidelity fell from %.4f to %.4f" % (was, now))


def test_the_committed_gate_agrees_with_the_tool(run, baseline):
    _, report = run
    assert accuracy.check(report, baseline) == []


# ---------------------------------------------------------------- the report
def test_the_report_renders_all_four_tables(run):
    results, report = run
    text = accuracy.render(results, report, verbose=True)
    for heading in ("per-rule precision / recall", "graph fidelity",
                    "confidence calibration", "MISSED LABELS"):
        assert heading in text
    assert "%" in text


def test_the_calibration_table_bins_every_matched_finding(run):
    results, report = run
    binned = sum(entry["n"] for entry in report["calibration"].values())
    findings = sum(len(r["rows"]) - sum(1 for row in r["rows"] if row["issue"] is None)
                   for r in results)
    findings += report["forbiddenFindings"] + report["unlabelledFindings"]
    assert binned == findings


def test_the_baseline_on_disk_is_the_shape_the_gate_reads(baseline):
    assert baseline["recordedOn"]
    for scope in ("overall", "unseen"):
        for key in ("recall", "visibleRecall", "highValueRecall", "precision"):
            assert isinstance(baseline[scope][key], (int, float))
    assert baseline["perRule"]
    assert 0.0 <= baseline["graphFidelity"]["score"] <= 1.0


# --------------------------------------------------------- matcher semantics
def _issue(code="MLV101", file="a.py", line=10, end=10, related=()):
    return {"code": code, "loc": {"file": file, "line": line, "endLine": end},
            "relatedLocs": [dict(r) for r in related]}


def test_a_line_label_matches_a_finding_whose_range_spans_it():
    label = {"code": "MLV201", "file": "train.py", "line": 52}
    assert accuracy.matches(_issue("MLV201", "train.py", 47, 56), label)
    assert not accuracy.matches(_issue("MLV201", "train.py", 60, 66), label)


def test_a_line_label_matches_through_a_related_location():
    label = {"code": "MLV101", "file": "data.py", "line": 29}
    issue = _issue("MLV101", "data.py", 40, 40,
                   related=[{"file": "data.py", "line": 29, "endLine": 29}])
    assert accuracy.matches(issue, label)


def test_a_file_label_ignores_the_line_and_a_project_label_ignores_the_file():
    assert accuracy.matches(_issue("MLV601", "train.py", 3, 3),
                            {"code": "MLV601", "file": "train.py"})
    assert accuracy.matches(_issue("MLV601", "anywhere.py", 3, 3),
                            {"code": "MLV601", "file": "train.py", "anchor": "project"})
    assert not accuracy.matches(_issue("MLV601", "other.py", 3, 3),
                                {"code": "MLV601", "file": "train.py"})


def test_the_code_must_always_agree():
    assert not accuracy.matches(_issue("MLV101"), {"code": "MLV102", "file": "a.py"})


def test_windows_and_posix_separators_are_the_same_file():
    assert accuracy.matches(_issue("MLV101", "src\\data.py", 5, 5),
                            {"code": "MLV101", "file": "src/data.py", "line": 5})


def test_one_finding_satisfies_at_most_one_label():
    """Two identical labels on one line must not both be scored by one finding."""
    program = accuracy.Program("probe", os.path.join(HERE, "labels.json"), {
        "expected": [
            {"code": "MLV101", "file": "a.py", "line": 5, "severity": "high",
             "defect": "first"},
            {"code": "MLV101", "file": "a.py", "line": 5, "severity": "high",
             "defect": "second"},
        ],
    })
    doc = {"issues": [_issue("MLV101", "a.py", 5, 5)], "nodes": [], "stats": {},
           "workspace": {}}
    scored = accuracy.score_program(program, doc)
    assert [row["issue"] is not None for row in scored["rows"]] == [True, False]
    assert scored["unlabelled"] == []


def test_a_suppressed_finding_is_neither_a_hit_nor_a_false_positive():
    program = accuracy.Program("probe", os.path.join(HERE, "labels.json"), {
        "expected": [{"code": "MLV101", "file": "a.py", "line": 5,
                      "severity": "high", "defect": "planted"}],
    })
    suppressed = dict(_issue("MLV101", "a.py", 5, 5), suppressed=True)
    doc = {"issues": [suppressed], "nodes": [], "stats": {}, "workspace": {}}
    scored = accuracy.score_program(program, doc)
    assert scored["rows"][0]["issue"] is None
    assert scored["unlabelled"] == []


def test_graph_fidelity_needs_a_node_anchored_on_the_op_not_merely_containing_it():
    program = accuracy.Program("probe", os.path.join(HERE, "labels.json"), {
        "graph": {"edges": 1, "ops": [{"file": "m.py", "line": 20, "symbol": "Conv2d"}]},
    })
    enclosing = {"loc": {"file": "m.py", "line": 10, "endLine": 40}}
    assert accuracy.score_graph(program, {"nodes": [enclosing], "stats": {}})["score"] == 0.0
    anchored = {"loc": {"file": "m.py", "line": 20, "endLine": 20}}
    assert accuracy.score_graph(program, {"nodes": [anchored], "stats": {}})["score"] == 1.0
