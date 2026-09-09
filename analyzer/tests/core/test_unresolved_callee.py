"""ANA-5a (CONTRACTS 11.23): never silently drop a call the analyzer cannot
resolve.

`core/build.py` only minted an `unknown` node when `call.scope.is_dynamic and
not call.canonical_fqns`, and `is_dynamic` is **not** set for lambda
indirection, `match`-based dispatch or a `dataclass` `default_factory`. The
odd-syntax file therefore lost its entire training step - the model, the
criterion, the optimizer - and reported `dynamic: 0` on every node it kept, so
a file MLView could not read looked exactly like a file MLView had read and
found clean.

The signal is **per call** (`CallSite.unresolved_callee`), never the scope-wide
dynamic flag: `rules/confidence.DYNAMIC_FACTOR` is 0.7 and applies per scope, so
widening the flag would move the confidence of every finding in the same
function. `test_the_demo_findings_keep_their_confidence` is that promise,
asserted against the checked-in golden.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import (AnalyzeOptions, analyze_full, analyze_to_dict,
                        render_mermaid, render_summary)

FIXTURE = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "oddsyntax",
                       "unresolved_callee.py")
SAMPLE = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
EXPECTED = os.path.join(SAMPLE, "expected_issues.json")
CLEAN_DIR = os.path.join(REPO_ROOT, "analyzer", "tests", "clean")

#: Every construct the fixture exercises, in the words the diagnostic uses.
CONSTRUCTS = ("a subscript", "the result of another call", "a lambda",
              "a value assigned in a match case", "a dataclass default_factory")


@pytest.fixture(scope="module")
def odd():
    return analyze_to_dict(AnalyzeOptions(paths=(FIXTURE,)))


def _unknowns(doc):
    return [n for n in doc["nodes"] if n["kind"] == "unknown"]


def _diagnostics(doc, kind="unresolved_callee"):
    return [d for d in doc.get("diagnostics", []) if d["kind"] == kind]


# ------------------------------------------------------------- the unknown ops
def test_every_unresolved_call_becomes_an_unknown_op(odd):
    unknowns = _unknowns(odd)
    assert len(unknowns) == 5, [(n["label"], n["loc"]["line"]) for n in unknowns]
    assert {n["level"] for n in unknowns} == {"op"}
    assert {n["label"] for n in unknowns} == {"model", "criterion", "head",
                                              "optimizer", "extra"}


def test_each_unknown_op_names_the_construct_that_defeated_it(odd):
    sublabels = sorted(n["sublabel"] for n in _unknowns(odd))
    for construct in CONSTRUCTS:
        assert any(construct in text for text in sublabels), (construct, sublabels)


def test_the_unknown_ops_are_anchored_where_the_call_is(odd):
    lines = sorted(n["loc"]["line"] for n in _unknowns(odd))
    assert lines == [37, 38, 41, 48, 51], lines


def test_the_document_is_contract_valid(odd):
    assert validate(odd) == []


# ------------------------------------------------------------- the diagnostic
def test_one_diagnostic_per_scope_naming_every_construct(odd):
    notes = _diagnostics(odd)
    assert len(notes) == 1, [d["message"] for d in notes]
    note = notes[0]
    assert note["count"] == 5
    assert note["file"] == "unresolved_callee.py"
    assert note["scope"] == "unresolved_callee.build"
    assert note["line"] == 37
    for construct in CONSTRUCTS:
        assert construct in note["message"], (construct, note["message"])


def test_the_scope_wide_dynamic_flag_is_not_widened(odd):
    """ANA-5a is per call. `dynamic` on a static scope would be a lie."""
    assert _diagnostics(odd, "dynamic_scope") == []
    assert [n["label"] for n in odd["nodes"] if n.get("dynamic")] == []
    result = analyze_full(AnalyzeOptions(paths=(FIXTURE,)))
    assert result.workspace.dynamic_scopes == []


def test_the_summary_does_not_claim_a_stage_is_absent_without_qualifying_it(odd):
    text = render_summary(odd)
    line = [row for row in text.splitlines() if "not detected:" in row]
    assert line, text
    assert "5 calls could not be resolved" in line[0], line[0]
    assert "unresolved_callee" in text


def test_the_mermaid_emitter_carries_the_same_qualifier(odd):
    text = render_mermaid(odd)
    absent = [row for row in text.splitlines() if "not detected:" in row]
    assert absent and "could not be resolved" in absent[0], absent


def test_the_verdict_is_not_a_clean_bill_of_health(odd):
    verdict = odd["answers"]["verdict"]["sentence"]
    assert "not a clean bill of health" in verdict, verdict


# ---------------------------------------------------------- the match walk
def test_calls_inside_a_match_case_are_recorded_at_all(odd):
    """`ast.Match`'s cases are neither `stmt` nor `expr` children, so the
    generic walk stepped straight past every case body."""
    result = analyze_full(AnalyzeOptions(paths=(FIXTURE,)))
    module = result.workspace.modules["unresolved_callee.py"]
    scope = module.functions["unresolved_callee.build"].scope
    assert "optimizer_cls" in scope.bindings
    assert scope.bindings["optimizer_cls"].opaque == "a value assigned in a match case"


# ------------------------------------------------------------- the negatives
def test_ordinary_code_mints_no_unknown_node_and_no_diagnostic():
    """A builtin has no binding, so `print()` / `len()` are never flagged."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(CLEAN_DIR,)))
    assert _unknowns(doc) == [], [n["label"] for n in _unknowns(doc)]
    assert _diagnostics(doc) == []
    assert doc["issues"] == []


#: The demo's fifteen findings with their **confidence values**, which
#: `expected_issues.json` deliberately does not carry (it pins code / file /
#: line / severity). ANA-5a's whole design constraint is that these do not
#: move, so they are pinned here where the constraint lives.
DEMO_FINDINGS = (
    ("MLV101", "sklearn_baseline.py", 24, 0.95, "high"),
    ("MLV103", "sklearn_baseline.py", 34, 0.85, "medium"),
    ("MLV110", "data.py", 33, 0.85, "medium"),
    ("MLV111", "data.py", 35, 0.9, "low"),
    ("MLV112", "data.py", 33, 0.98, "medium"),
    ("MLV201", "train.py", 29, 0.9, "high"),
    ("MLV205", "train.py", 34, 0.85, "medium"),
    ("MLV301", "train.py", 44, 0.85, "high"),
    ("MLV302", "train.py", 44, 0.85, "medium"),
    ("MLV401", "train.py", 31, 0.855, "high"),
    ("MLV501", "train.py", 29, 0.9, "medium"),
    ("MLV601", "train.py", 28, 0.9, "low"),
    ("MLV602", "data.py", 31, 0.95, "low"),
    ("MLV602", "sklearn_baseline.py", 26, 0.95, "low"),
    ("MLV702", "model.py", 34, 0.95, "high"),
)


def test_the_demo_findings_keep_their_confidence():
    """The demo's fifteen findings, at the same lines and the same confidence."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE,)))
    actual = sorted((i["code"], i["loc"]["file"], i["loc"]["line"], i["confidence"],
                     i["severity"]) for i in doc["issues"])
    assert actual == sorted(DEMO_FINDINGS)
    assert _unknowns(doc) == []
    assert _diagnostics(doc) == []


def test_the_pinned_confidences_agree_with_the_checked_in_golden():
    """The two pins must describe the same fifteen rows, or one of them is stale."""
    with open(EXPECTED, encoding="utf-8") as handle:
        rows = json.load(handle)
    golden = sorted((r["code"], r["file"], r["line"], r["severity"]) for r in rows)
    mine = sorted((c, f, l, s) for c, f, l, _conf, s in DEMO_FINDINGS)
    assert mine == golden
