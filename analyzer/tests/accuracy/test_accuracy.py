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


def test_a_program_with_no_graph_block_scores_nothing_rather_than_everything(run):
    """The referee's own report must be truthful about what it measured. Four
    corpus programs carry no hand-drawn diagram (11.26 A13), and the table used
    to print `100.0%` for each of them - four perfect scores where the truth is
    that nobody drew a diagram."""
    results, report = run
    unlabelled = [r for r in results if r["graph"]["opsLabelled"] == 0]
    assert unlabelled, "the interesting case is a program with no graph block"
    for result in unlabelled:
        assert result["graph"]["score"] is None, result["name"]
        assert result["graph"]["edgeRatio"] is None, result["name"]
        assert report["graphFidelity"]["perProgram"][result["name"]] is None
    text = accuracy.render(results, report)
    assert "not labelled" in text
    labelled = [r for r in results if r["graph"]["opsLabelled"]]
    assert all(r["graph"]["score"] is not None for r in labelled)
    # the gated aggregate is untouched: 0/0 contributed nothing before, either
    assert report["graphFidelity"]["opsLabelled"] == sum(
        r["graph"]["opsLabelled"] for r in results)


def test_a_rule_labelled_only_in_tuned_programs_is_marked_as_such(run):
    """`recall 100.0%` off a single label in a program written alongside the
    rule is a ceiling, not a measurement, and the table has to say so.

    Hardening round 1 grew the corpus from 15 programs to 92 and **every** rule
    now carries at least one unseen label, so the corpus no longer contains the
    case. That is the outcome this project wanted and it is asserted as such
    below; the marking itself is still exercised, on a copy of the real report
    with one rule's unseen labels taken away, so the `*` cannot rot while no
    program happens to need it.
    """
    results, report = run
    tuned_only = [code for code, data in report["perRule"].items()
                  if data["expected"] and not data["unseenExpected"]]
    assert tuned_only == [], (
        "every rule is expected to have an unseen label on this corpus; %s "
        "lost theirs" % tuned_only)
    for code in tuned_only:  # pragma: no cover - empty while the corpus is whole
        assert report["perRule"][code]["unseenRecall"] is None

    text = accuracy.render(results, report)
    assert "*" not in "".join(line for line in text.splitlines()
                              if line.startswith("MLV")), text

    # The marking, on a report that does contain the case.
    import copy
    ceiling = copy.deepcopy(report)
    victim = next(code for code, data in ceiling["perRule"].items()
                  if data["expected"])
    ceiling["perRule"][victim].update(unseenExpected=0, unseenRecovered=0,
                                      unseenRecall=None)
    marked = accuracy.render(results, ceiling)
    assert "%s*" % victim in marked, victim

    unseen_scored = [code for code, data in report["perRule"].items()
                     if data["unseenExpected"]]
    assert unseen_scored, "the interesting case is a rule with an unseen label"
    for code in unseen_scored:
        data = report["perRule"][code]
        assert data["unseenRecall"] == round(
            data["unseenRecovered"] / data["unseenExpected"], 4), code
    assert "unseen recall" in text


def test_the_calibration_table_bins_every_matched_finding(run):
    """Every finding the scorer counted as a true or a false positive is in a
    bucket.

    An `acceptable` label is deliberately neither: the tool *may* say this, so a
    finding that matches one is not scored in either direction and is not binned
    (`tools/accuracy_corpus.py` skips the row before `bucket_of`). It is
    therefore excluded here too, rather than making the calibration table count
    findings its own precision column does not.
    """
    results, report = run
    binned = sum(entry["n"] for entry in report["calibration"].values())
    findings = sum(1 for r in results for row in r["rows"]
                   if row["issue"] is not None and row["verdict"] != "acceptable")
    findings += report["forbiddenFindings"] + report["unlabelledFindings"]
    assert binned == findings
    # and the exclusion is real on this corpus, not a hypothetical
    assert any(row["issue"] is not None and row["verdict"] == "acceptable"
               for r in results for row in r["rows"])


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


# --------------------------------------------------------- the gates' own flags
# TB-02: both stated tolerances used to have a one-flag escape. `--no-gate`
# returned 0 on a forbidden finding, and `--update-baseline` rewrote the file
# from the current run without ever loading the one it replaced - so a recall
# regression was erased by one command, under a note that still claimed
# "recall may only ratchet up". These pin that neither is true any more.
def _fake_report(recall=0.60, forbidden=0, unlabelled=0, per_rule=None,
                 graph=0.5):
    scope = {"expectedLabels": 10, "recall": recall, "visibleRecall": recall,
             "highValueRecall": recall, "precision": 1.0}
    return {
        "programs": 3,
        "forbiddenFindings": forbidden,
        "unlabelledFindings": unlabelled,
        "overall": dict(scope),
        "unseen": dict(scope),
        "perRule": per_rule if per_rule is not None else {"MLV101": {"recall": 0.5}},
        "graphFidelity": {"score": graph, "opsLabelled": 4, "opsRecovered": 2,
                          "perProgram": {}},
        "calibration": {},
    }


def _write_baseline(tmp_path, report):
    path = str(tmp_path / "baseline.json")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(accuracy.build_baseline(report), handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _run(monkeypatch, report, argv):
    monkeypatch.setattr(accuracy, "run_corpus", lambda *a, **k: ([], report))
    return accuracy.main(argv)


def test_baseline_moves_names_every_number_that_moved_in_both_directions():
    was = accuracy.build_baseline(_fake_report(recall=0.60, graph=0.5))
    now = _fake_report(recall=0.55, graph=0.9,
                       per_rule={"MLV101": {"recall": 0.8}})
    down, up = accuracy.baseline_moves(now, was)
    assert [label for label, _w, _n in down] == [
        "overall highValueRecall", "overall recall", "overall visibleRecall",
        "unseen highValueRecall", "unseen recall", "unseen visibleRecall"]
    assert [label for label, _w, _n in up] == ["MLV101 recall", "graph fidelity"]


def test_a_rule_the_report_stopped_scoring_counts_as_a_downward_move():
    """A rule that vanishes from the report is a silent recall loss, not a wash."""
    was = accuracy.build_baseline(_fake_report(per_rule={"MLV101": {"recall": 0.5}}))
    down, _up = accuracy.baseline_moves(_fake_report(per_rule={}), was)
    assert ("MLV101 recall", 0.5, 0.0) in down


def test_update_baseline_refuses_to_ratchet_a_number_down(tmp_path, monkeypatch,
                                                          capsys):
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    before = open(path, encoding="utf-8").read()
    code = _run(monkeypatch, _fake_report(recall=0.55),
                ["--baseline", path, "--update-baseline", "--quiet"])
    assert code == accuracy.EXIT_REGRESSION
    assert open(path, encoding="utf-8").read() == before, "the file was rewritten"
    out = capsys.readouterr()
    assert "baseline DOWN  overall recall               0.6000 -> 0.5500" in out.out
    assert "--allow-regression" in out.err


def test_a_downward_move_needs_an_explicit_reason_and_records_it(tmp_path,
                                                                 monkeypatch):
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    code = _run(monkeypatch, _fake_report(recall=0.55),
                ["--baseline", path, "--update-baseline", "--quiet",
                 "--allow-regression", "MLV101 was retired by the lead"])
    assert code == accuracy.EXIT_OK
    written = json.load(open(path, encoding="utf-8"))
    assert written["overall"]["recall"] == 0.55
    assert "SANCTIONED REGRESSION" in written["note"]
    assert "MLV101 was retired by the lead" in written["note"]


def test_update_baseline_still_ratchets_up_without_a_flag(tmp_path, monkeypatch):
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    code = _run(monkeypatch, _fake_report(recall=0.70),
                ["--baseline", path, "--update-baseline", "--quiet"])
    assert code == accuracy.EXIT_OK
    assert json.load(open(path, encoding="utf-8"))["overall"]["recall"] == 0.70


def test_update_baseline_refuses_while_a_forbidden_finding_fires(tmp_path,
                                                                 monkeypatch):
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    before = open(path, encoding="utf-8").read()
    code = _run(monkeypatch, _fake_report(recall=0.90, forbidden=1),
                ["--baseline", path, "--update-baseline", "--quiet",
                 "--allow-regression", "irrelevant"])
    assert code == accuracy.EXIT_FORBIDDEN
    assert open(path, encoding="utf-8").read() == before


def test_no_gate_does_not_swallow_a_forbidden_finding(tmp_path, monkeypatch):
    """Gate 1 is not a ratchet, so the flag that relaxes the ratchet misses it."""
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    code = _run(monkeypatch, _fake_report(recall=0.60, forbidden=1),
                ["--baseline", path, "--no-gate", "--quiet"])
    assert code == accuracy.EXIT_FORBIDDEN


def test_no_gate_still_swallows_a_plain_ratchet_regression(tmp_path, monkeypatch):
    path = _write_baseline(tmp_path, _fake_report(recall=0.60))
    assert _run(monkeypatch, _fake_report(recall=0.55),
                ["--baseline", path, "--quiet"]) == accuracy.EXIT_REGRESSION
    assert _run(monkeypatch, _fake_report(recall=0.55),
                ["--baseline", path, "--no-gate", "--quiet"]) == accuracy.EXIT_OK
