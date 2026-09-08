"""The two sample projects (CONTRACTS sections 7.1, 7.2 and amendment A12).

`samples/vision_pipeline/` carries **exactly** the fifteen planted defects that
the acceptance walkthrough depends on, and
`samples/vision_pipeline/expected_issues.json` is the machine-checked contract
for them. `samples/vision_pipeline_clean/` is the same five files with every
defect corrected and must be completely silent.

Both documents are validated against `contracts/graph.schema.json` through
`contracts/validate_sample.py`, the same checker the core suite uses.
"""

from __future__ import annotations

import io
import json
import os

import pytest

from rule_harness import SAMPLES_DIR, analyze_paths, describe, validate

DIRTY = os.path.join(SAMPLES_DIR, "vision_pipeline")
CLEAN = os.path.join(SAMPLES_DIR, "vision_pipeline_clean")
EXPECTED = os.path.join(DIRTY, "expected_issues.json")

SAMPLE_FILES = ("config.py", "data.py", "model.py", "sklearn_baseline.py", "train.py")
#: CONTRACTS section 7.1: 5 high, 6 medium, 4 low across 14 codes (MLV602 twice).
EXPECTED_COUNTS = {"high": 5, "medium": 6, "low": 4}
EXPECTED_CODES = {
    "MLV101", "MLV103", "MLV110", "MLV111", "MLV112", "MLV201", "MLV205",
    "MLV301", "MLV302", "MLV401", "MLV501", "MLV601", "MLV602", "MLV702",
}
#: The six prototype codes the sample deliberately does NOT exercise.
NOT_IN_SAMPLE = {"MLV102", "MLV202", "MLV203", "MLV204", "MLV402", "MLV701"}


@pytest.fixture(scope="module")
def dirty():
    return analyze_paths(DIRTY)


@pytest.fixture(scope="module")
def clean():
    return analyze_paths(CLEAN)


def _rows(doc):
    return sorted(({"code": i["code"], "severity": i["severity"],
                    "file": i["loc"]["file"], "line": i["loc"]["line"]}
                   for i in doc["issues"]),
                  key=lambda r: (r["file"], r["line"], r["code"]))


# ------------------------------------------------------------- both projects
@pytest.mark.parametrize("root", [DIRTY, CLEAN], ids=["dirty", "clean"])
def test_the_five_files_are_there(root):
    present = tuple(sorted(n for n in os.listdir(root) if n.endswith(".py")))
    assert present == SAMPLE_FILES


# -------------------------------------------------------------- dirty sample
def test_the_dirty_sample_matches_expected_issues_json_exactly(dirty):
    expected = json.loads(io.open(EXPECTED, encoding="utf-8").read())
    got = _rows(dirty)
    assert got == expected, (
        "the sample and expected_issues.json disagree - regenerate it with "
        "`python analyzer/tools/gen_expected_issues.py` in the same commit.\n"
        "got: %s" % describe(dirty))


def test_expected_issues_json_is_canonically_sorted():
    expected = json.loads(io.open(EXPECTED, encoding="utf-8").read())
    assert expected == sorted(expected, key=lambda r: (r["file"], r["line"], r["code"]))
    for row in expected:
        assert set(row) == {"code", "severity", "file", "line"}


def test_the_planted_counts_are_five_six_four(dirty):
    counts = {"low": 0, "medium": 0, "high": 0}
    for issue in dirty["issues"]:
        counts[issue["severity"]] += 1
    assert counts == EXPECTED_COUNTS, describe(dirty)
    assert len(dirty["issues"]) == 15


def test_fourteen_distinct_codes_with_mlv602_twice(dirty):
    codes = [i["code"] for i in dirty["issues"]]
    assert set(codes) == EXPECTED_CODES
    assert len(set(codes)) == 14
    assert codes.count("MLV602") == 2


def test_the_six_unplanted_codes_stay_out_of_the_sample(dirty):
    """A slip in one of those six cannot break the acceptance walkthrough."""
    fired = {i["code"] for i in dirty["issues"]}
    assert not (fired & NOT_IN_SAMPLE), sorted(fired & NOT_IN_SAMPLE)


def test_nothing_in_the_sample_is_suppressed(dirty):
    assert [i for i in dirty["issues"] if i["suppressed"]] == []
    assert dirty["stats"].get("suppressed", 0) == 0


def test_the_dirty_sample_draws_two_ghost_nodes(dirty):
    """The demo shows the holes: a missing zero_grad and a missing eval()."""
    ghosts = {n["label"]: n for n in dirty["nodes"] if n["ghost"]}
    assert set(ghosts) == {"zero_grad()", "model.eval()"}
    for ghost in ghosts.values():
        assert ghost["sublabel"] == "missing"
        assert ghost["issueIds"], "invariant 1.1.8"
        assert ghost["level"] == "op"
    assert ghosts["zero_grad()"]["fqn"] == "torch.optim.Optimizer.zero_grad"
    assert ghosts["model.eval()"]["fqn"] == "torch.nn.Module.eval"


def test_the_dirty_sample_has_one_edge_borne_marker(dirty):
    """MLV401 marks the model -> loss connection, not just a node."""
    edge_borne = [i for i in dirty["issues"] if i["edgeIds"]]
    assert [i["code"] for i in edge_borne] == ["MLV401"]
    edges = {e["id"]: e for e in dirty["edges"]}
    for edge_id in edge_borne[0]["edgeIds"]:
        assert edge_id in edges
        assert edges[edge_id]["kind"] == "data"
        assert edge_borne[0]["id"] in edges[edge_id]["issueIds"]


def test_the_dirty_sample_has_the_leakage_connector(dirty):
    """MLV101 is the multi-location finding: fit site -> split site."""
    issue = next(i for i in dirty["issues"] if i["code"] == "MLV101")
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"fit_site", "split_site"}
    assert roles["fit_site"]["file"] == "sklearn_baseline.py"
    assert roles["fit_site"]["line"] < roles["split_site"]["line"]


def test_the_absence_rules_are_allowed_to_reach_high(dirty):
    """No wrapper, no dynamic scope: exactly the precondition for the cap."""
    assert dirty["workspace"]["frameworks"]
    assert not [d for d in dirty["diagnostics"] if d["kind"] == "framework_suppressed"]
    assert not [d for d in dirty["diagnostics"] if d["kind"] == "dynamic_scope"]
    for code in ("MLV201", "MLV301"):
        issue = next(i for i in dirty["issues"] if i["code"] == code)
        assert issue["severity"] == "high", code


def test_the_dirty_sample_is_a_legible_graph(dirty):
    assert dirty["workspace"]["filesAnalyzed"] == 5
    assert dirty["workspace"]["filesFailed"] == 0
    assert dirty["workspace"]["entrypoints"][0] == "train.py"
    assert len(dirty["nodes"]) >= 20
    present = [s["id"] for s in dirty["stages"] if s["present"]]
    assert len(present) >= 6, present
    assert {"config", "data", "preprocess", "model", "objective", "train",
            "eval"} <= set(present)


def test_the_dirty_sample_document_is_contract_valid(dirty):
    assert validate(dirty) == []


def test_no_rule_raised_on_the_sample(dirty):
    assert [d for d in dirty["diagnostics"] if d["kind"] == "rule_error"] == []


# --------------------------------------------------------------- clean twin
def test_the_clean_twin_is_completely_silent(clean):
    assert clean["issues"] == [], describe(clean)
    assert clean["stats"]["issues"] == {"low": 0, "medium": 0, "high": 0}


def test_the_clean_twin_is_still_a_full_pipeline(clean):
    """0/0/0 must mean 'correct', never 'nothing was understood'."""
    assert clean["workspace"]["filesAnalyzed"] == 5
    assert clean["workspace"]["filesFailed"] == 0
    assert len(clean["nodes"]) >= 20
    present = [s["id"] for s in clean["stages"] if s["present"]]
    assert len(present) >= 6, present
    assert not [n for n in clean["nodes"] if n["ghost"]]


def test_the_clean_twin_keeps_the_shape_of_the_dirty_one(dirty, clean):
    """Side by side in the demo: same stages, comparable size."""
    dirty_stages = {s["id"] for s in dirty["stages"] if s["present"]}
    clean_stages = {s["id"] for s in clean["stages"] if s["present"]}
    assert dirty_stages == clean_stages
    assert abs(len(clean["nodes"]) - len(dirty["nodes"])) <= len(dirty["nodes"]) // 2
    assert set(clean["workspace"]["frameworks"]) == set(dirty["workspace"]["frameworks"])


def test_the_clean_twin_document_is_contract_valid(clean):
    assert validate(clean) == []


# ------------------------------------------------------------- the generator
def test_the_expected_issues_generator_reproduces_the_file():
    import sys
    tools = os.path.join(os.path.dirname(SAMPLES_DIR), "analyzer", "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from gen_expected_issues import expected_rows, render  # noqa: E402
    assert render(expected_rows()) == io.open(EXPECTED, encoding="utf-8").read()
