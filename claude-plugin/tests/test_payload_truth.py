"""What the payloads must not misstate, and what they must not omit.

Three regressions live here, all of them about a payload that *fit* the budget and
*validated* but told the model something false:

* **MLV-R2-103** - a scoped ``mlview_graph`` recomputed ``stage.present`` from the
  filtered node set, so ``scope="stage:train"`` printed
  ``%% not detected: config, data, preprocess, model, objective, eval, deliver``
  over a project that has seven of the eight. ``commands/mlview.md`` tells the
  model to report an undetected lane as a finding, so that line invented findings.
* **MLV-R2-107** - the budget was measured on the compact encoding while the SDK
  serializes ``content[0].text`` with ``indent=2``, ~27% larger. ``mlview_issues``
  shipped 4985 model-facing bytes on the demo sample against a 4096-byte cap.
* **MLV-R2-108** - ``issues_payload`` carried no ``filesAnalyzed`` / ``filesFailed``,
  so an empty directory, a directory of syntax errors and genuinely clean code all
  produced the same 0/0/0 payload - which ``commands/mlview-issues.md`` turns into
  a positive clean bill of health.
"""

from __future__ import annotations

import json

import pytest

import mlview_budget
import mlview_payloads as payloads
from plugin_support import synthetic_graph

LIMIT = 4096


def _renderers():
    """The real emitters, so the assertions are about really rendered text."""
    from mlview.api import render_mermaid, render_text

    return {"mermaid": render_mermaid, "text": render_text}


@pytest.fixture(scope="module")
def demo():
    """A document with seven present stages and exactly one absent lane."""
    graph = synthetic_graph(nodes=120, edges=180, issues=40)
    graph["nodes"] = [n for n in graph["nodes"] if n["stage"] != "deliver"]
    keep = {n["id"] for n in graph["nodes"]}
    graph["edges"] = [
        e for e in graph["edges"] if e["source"] in keep and e["target"] in keep
    ]
    for node in graph["nodes"]:
        if node.get("parent") not in keep:
            node["parent"] = None
    graph["stages"] = [
        dict(
            row,
            present=row["id"] != "deliver",
            nodeCount=0 if row["id"] == "deliver" else row["nodeCount"],
        )
        for row in graph["stages"]
    ]
    return graph


# ------------------------------------------------------------------- MLV-R2-103
def test_the_demo_document_really_has_one_absent_lane(demo):
    absent = [s["id"] for s in demo["stages"] if not s["present"]]
    assert absent == ["deliver"], absent


def test_a_scoped_subgraph_keeps_the_project_level_present_flag(demo):
    view = payloads.subgraph(demo, payloads.stage_scope_ids(demo, "train"))
    absent = [s["id"] for s in view["stages"] if not s["present"]]
    assert absent == ["deliver"], (
        "a filtered view reported %s as absent; only 'deliver' is" % absent
    )
    counts = {s["id"]: s["nodeCount"] for s in view["stages"]}
    assert counts["train"] > 0 and counts["model"] == 0, counts


@pytest.mark.parametrize("stage", ["train", "model", "data"])
def test_a_scoped_mermaid_diagram_names_only_the_genuinely_absent_stage(demo, stage):
    """MLV-R2-103, in both places the answer can live.

    CHANGED for CONTRACTS 11.2: a `stage:` scope now keeps the `parent` ancestor
    closure, which roughly doubles the projected node count (verified on
    `samples/vision_pipeline`: `stage:train` 9 -> 10 nodes) and pushes this
    120-node synthetic diagram past the 4 KB budget. The mermaid emitter prints
    its absence comment LAST, so a clipped body can now legitimately end before
    it — which is why the project-level absence is also carried in the payload's
    `note`, a PROTECTED key that neither clipping nor `fit` can shed. The
    assertion is therefore stronger than before, not weaker: whichever of the two
    places states an absence must name `deliver` and nothing else.
    """
    payload = payloads.graph_payload(
        demo,
        fmt="mermaid",
        scope="stage:%s" % stage,
        depth=1,
        renderers=_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    lines = [line for line in payload["content"].splitlines() if "not detected" in line]
    assert lines in ([], ["  %% not detected: deliver"]), lines
    absence = [
        part for part in payload["note"].split("; ") if part.startswith("absent from")
    ]
    assert len(absence) == 1, payload["note"]
    assert absence[0].endswith(": deliver"), absence
    for present_stage in ("train", "model", "data", "config"):
        assert present_stage not in absence[0], absence


def test_a_scoped_text_diagram_names_only_the_genuinely_absent_stage(demo):
    payload = payloads.graph_payload(
        demo,
        fmt="text",
        scope="stage:model",
        depth=1,
        renderers=_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    lines = [
        line.strip() for line in payload["content"].splitlines() if "not detected" in line
    ]
    assert lines == ["not detected: deliver"], lines


def test_the_absent_stage_note_and_the_diagram_body_agree(demo):
    payload = payloads.graph_payload(
        demo,
        fmt="mermaid",
        scope="stage:deliver",
        depth=1,
        renderers=_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    assert "deliver" in payload["note"]
    body = [line for line in payload["content"].splitlines() if "not detected" in line]
    assert body == ["  %% not detected: deliver"], (
        "the note said only 'deliver' was absent while the body said %s" % body
    )


def test_a_scoped_view_says_its_counts_are_scope_local(demo):
    payload = payloads.graph_payload(
        demo, fmt="mermaid", scope="stage:train", depth=1, renderers=_renderers()
    )
    assert "filtered view" in payload["note"], payload.get("note")


def test_the_unscoped_and_stages_views_carry_no_filtering_note(demo):
    for scope in (None, "stages"):
        payload = payloads.graph_payload(
            demo, fmt="mermaid", scope=scope, depth=1, renderers=_renderers()
        )
        assert "filtered view" not in payload.get("note", ""), scope


# ------------------------------------------------------------------- MLV-R2-107
def test_the_budget_is_measured_on_the_encoding_the_sdk_emits():
    payload = {"a": ["x" * 40 for _ in range(20)]}
    assert mlview_budget.payload_size(payload) > mlview_budget.compact_size(payload), (
        "the SDK renders content[0].text with indent=2; measuring the compact "
        "encoding is what let mlview_issues ship 4985 model-facing bytes"
    )
    assert mlview_budget.serialize(payload) == json.dumps(
        payload, ensure_ascii=False, indent=2
    )


@pytest.mark.parametrize("limit_rows", [5, 20, 50, 300])
def test_the_issues_text_block_fits_the_cap(demo, limit_rows):
    payload = payloads.issues_payload(
        demo,
        min_severity="low",
        limit=limit_rows,
        graph_path="C:/proj/.mlview/graph.json",
    )
    indented = len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    compact = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    assert indented <= LIMIT, "%d bytes of model-facing text" % indented
    assert compact <= LIMIT


@pytest.mark.parametrize("fmt", ["mermaid", "text", "json"])
@pytest.mark.parametrize("scope", [None, "stages", "stage:train"])
def test_every_graph_payload_text_block_fits_the_cap(fmt, scope):
    big = synthetic_graph(nodes=500, edges=800, issues=300)
    blob = "\n".join(
        "  n_%04d --> n_%04d  long synthetic edge" % (i, i + 1) for i in range(4000)
    )
    payload = payloads.graph_payload(
        big,
        fmt=fmt,
        scope=scope,
        depth=1,
        renderers={"mermaid": lambda g: "flowchart LR\n" + blob, "text": lambda g: blob},
        graph_path="C:/proj/.mlview/graph.json",
    )
    indented = len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    assert indented <= LIMIT, "%s/%s -> %d bytes" % (fmt, scope, indented)


def test_explain_payloads_fit_the_cap_in_the_sdk_encoding():
    big = synthetic_graph(nodes=200, edges=300, issues=80)
    node = dict(big["nodes"][4], loc=dict(big["nodes"][4]["loc"], line=1, endLine=400))
    graph = dict(big, nodes=[node] + big["nodes"][1:])
    source = [
        "value = call_%d(argument)  # a long synthetic source line\n" % i
        for i in range(500)
    ]
    node_payload = payloads.explain_node_payload(graph, node["id"], source_lines=source)
    rule_payload = payloads.explain_rule_payload(
        "MLV201",
        "\n".join("Line %d of a very long offline rule document." % i for i in range(400)),
        {
            "severity": "high",
            "frameworks": ["torch"],
            "tags": ["correctness"],
            "absence": True,
            "enabled": True,
            "title": "t",
            "why": "w",
            "fix_hint": "f",
        },
        "docs/rules/MLV201.md",
    )
    for payload in (node_payload, rule_payload):
        size = len(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        assert size <= LIMIT, size


# ------------------------------------------------------------------- MLV-R2-108
def _corpus(files_analyzed, files_failed, diagnostics=()):
    graph = synthetic_graph(nodes=4, edges=2, issues=3)
    graph["issues"] = []
    graph["nodes"] = []
    graph["edges"] = []
    graph["workspace"] = dict(
        graph["workspace"],
        filesAnalyzed=files_analyzed,
        filesFailed=files_failed,
        notebooksSkipped=0,
    )
    graph["diagnostics"] = list(diagnostics)
    return graph


def test_an_empty_directory_is_not_reported_as_clean():
    payload = payloads.issues_payload(_corpus(0, 0))
    assert payload["filesAnalyzed"] == 0
    assert payload["filesFailed"] == 0
    assert "NOT a clean bill of health" in payload["note"], payload.get("note")


def test_a_directory_of_parse_failures_is_distinguishable_from_clean_code():
    broken = payloads.issues_payload(
        _corpus(
            0,
            2,
            [
                {"kind": "parse_error", "message": "boom", "count": 1},
                {"kind": "parse_error", "message": "boom", "count": 1},
            ],
        )
    )
    clean = payloads.issues_payload(_corpus(5, 0))
    assert broken != clean, "clean code and total parse failure must not agree"
    assert broken["filesFailed"] == 2
    assert "failed to parse" in broken["note"]
    assert broken["diagnostics"] == [{"kind": "parse_error", "count": 2}]
    assert "note" not in clean, clean.get("note")
    assert clean["filesAnalyzed"] == 5


def test_clean_code_carries_the_counts_but_no_alarming_note():
    payload = payloads.issues_payload(_corpus(7, 0))
    assert payload["countBySeverity"] == {"low": 0, "medium": 0, "high": 0}
    assert payload["filesAnalyzed"] == 7 and payload["filesFailed"] == 0
    assert "note" not in payload


def test_the_analyze_payload_surfaces_diagnostics_the_digest_drops():
    from mlview.api import digest

    graph = _corpus(0, 3, [{"kind": "parse_error", "message": "x", "count": 3}])
    payload = payloads.analyze_payload(
        digest(graph, limit_bytes=3200), "C:/proj/.mlview/graph.json", graph=graph
    )
    assert payload["diagnostics"] == [{"kind": "parse_error", "count": 3}]
    assert "failed to parse" in payload["note"]


def test_the_counts_survive_a_payload_that_has_to_shed_rows():
    """The budget fitter must never drop the 'this is not clean' signal."""
    graph = _corpus(0, 4, [{"kind": "parse_error", "message": "x", "count": 4}])
    graph["issues"] = synthetic_graph(nodes=8, edges=4, issues=60)["issues"]
    payload = payloads.issues_payload(graph, limit=60, limit_bytes=900)
    assert payload["truncated"] is True
    assert payload["filesAnalyzed"] == 0 and payload["filesFailed"] == 4
    assert "NOT a clean bill of health" in payload["note"]


# --------------------------------------------------------------- TB-06 (COVERAGE)
# `commands/mlview.md` tells the model: "The payload carries a `single_file_analysis`
# diagnostic **naming the rules that could not run**" and "name the rules that could
# not run before you report the count". The payload used to carry `{kind, count}` and
# nothing else, so that instruction could only be met by INVENTING rule codes - and
# `count: 4` is sibling modules, not rules, so the tally read as a rule tally was
# wrong too. The rules the analyzer named have to be in the payload.
SINGLE_FILE_MESSAGE = (
    "Only train.py was analyzed: 4 sibling module(s) in the same package were not "
    "(config.py, data.py, model.py, sklearn_baseline.py), and train.py imports 3 of "
    "them. Rules that need cross-file evidence (MLV301, MLV302, MLV401, MLV501) "
    "cannot see those definitions, so a clean result here is not a clean result for "
    "the package - analyze the directory to widen."
)
UNTAGGED_MESSAGE = (
    "MLV101 stayed silent in prep.make_splits: `X` (line 5) carries no dataflow tag "
    "(it arrives as a parameter of prep.make_splits), so leakage through it is "
    "neither confirmed nor ruled out - a gap in coverage, not a clean result."
)
SINGLE_FILE_DIAGNOSTIC = {
    "kind": "single_file_analysis",
    "message": SINGLE_FILE_MESSAGE,
    "file": "train.py",
    "codes": ["MLV301", "MLV302", "MLV401", "MLV501"],
    "count": 4,
}
UNTAGGED_DIAGNOSTIC = {
    "kind": "untagged_dataflow",
    "message": UNTAGGED_MESSAGE,
    "file": "prep.py",
    "line": 5,
    "scope": "prep.make_splits",
    "codes": ["MLV101"],
    "count": 1,
}


def test_the_issues_payload_names_the_rules_that_could_not_run():
    payload = payloads.issues_payload(_corpus(1, 0, [SINGLE_FILE_DIAGNOSTIC]))
    coverage = payload["coverage"]
    assert [c["kind"] for c in coverage] == ["single_file_analysis"]
    assert coverage[0]["codes"] == ["MLV301", "MLV302", "MLV401", "MLV501"]
    assert coverage[0]["message"] == SINGLE_FILE_MESSAGE, "the analyzer's own wording"
    # and the note says what to do with them, in the order the command body asks
    for code in ("MLV301", "MLV302", "MLV401", "MLV501"):
        assert code in payload["note"], payload["note"]
    assert "floor" in payload["note"] and "clean bill of health" in payload["note"]


def test_the_analyze_payload_names_the_rules_that_could_not_run():
    from mlview.api import digest

    graph = _corpus(1, 0, [SINGLE_FILE_DIAGNOSTIC])
    payload = payloads.analyze_payload(
        digest(graph, limit_bytes=3200), "C:/proj/.mlview/graph.json", graph=graph
    )
    assert payload["coverage"][0]["codes"] == ["MLV301", "MLV302", "MLV401", "MLV501"]
    assert "MLV501" in payload["note"]
    # the tally stays too: it is the only thing that carries the OTHER kinds
    assert payload["diagnostics"] == [{"kind": "single_file_analysis", "count": 4}]


def test_a_coverage_count_is_never_presented_as_a_count_of_rules():
    """`count: 4` is four sibling MODULES; four rules is a coincidence of this
    fixture. The message that explains what the number counts must travel with it."""
    payload = payloads.issues_payload(_corpus(1, 0, [SINGLE_FILE_DIAGNOSTIC]))
    note = payload["coverage"][0]
    assert note["count"] == 4
    assert "sibling module(s)" in note["message"]
    assert "could not run" in payload["note"]


def test_both_coverage_kinds_are_carried_in_a_stable_order():
    graph = _corpus(3, 0, [UNTAGGED_DIAGNOSTIC, SINGLE_FILE_DIAGNOSTIC])
    payload = payloads.issues_payload(graph)
    assert [c["kind"] for c in payload["coverage"]] == [
        "single_file_analysis",
        "untagged_dataflow",
    ]
    assert payload["coverage"][1]["codes"] == ["MLV101"]
    assert "MLV101" in payload["note"]
    assert mlview_budget.payload_size(payload) <= LIMIT


def test_untagged_sites_in_many_scopes_collapse_to_one_row_with_the_union_of_codes():
    graph = _corpus(
        3,
        0,
        [
            dict(UNTAGGED_DIAGNOSTIC, codes=["MLV101"], count=2),
            dict(UNTAGGED_DIAGNOSTIC, codes=["MLV102", "MLV101"], count=3, file="b.py"),
        ],
    )
    note = payloads.issues_payload(graph)["coverage"][0]
    assert note["kind"] == "untagged_dataflow"
    assert note["count"] == 5, "five untraced sites, not two rows"
    assert note["codes"] == ["MLV101", "MLV102"]


def test_a_clean_document_carries_no_coverage_block_at_all():
    payload = payloads.issues_payload(_corpus(7, 0))
    assert "coverage" not in payload
    assert "note" not in payload


def test_a_parse_error_is_not_mistaken_for_a_coverage_caveat():
    payload = payloads.issues_payload(
        _corpus(0, 1, [{"kind": "parse_error", "message": "boom", "count": 1}])
    )
    assert "coverage" not in payload
    assert "could not run" not in payload["note"]


def test_the_coverage_block_survives_a_payload_that_has_to_shed_rows():
    """The budget walk sheds issue ROWS; it must never shed the reason the row
    count is a floor. `coverage` is in PROTECTED_KEYS for exactly this."""
    graph = _corpus(1, 0, [SINGLE_FILE_DIAGNOSTIC, UNTAGGED_DIAGNOSTIC])
    graph["issues"] = synthetic_graph(nodes=8, edges=4, issues=60)["issues"]
    payload = payloads.issues_payload(graph, limit=60, limit_bytes=1800)
    assert payload["truncated"] is True
    assert len(payload["issues"]) < 60
    assert [c["kind"] for c in payload["coverage"]] == [
        "single_file_analysis",
        "untagged_dataflow",
    ]
    assert "MLV301" in payload["note"] and "MLV101" in payload["note"]


def test_the_coverage_block_is_bounded_so_protecting_it_cannot_starve_a_payload():
    """A hostile document - forty codes, a kilobyte of message - must still leave
    room for the rest of the payload, or `fit` would give up above the cap."""
    huge = dict(
        SINGLE_FILE_DIAGNOSTIC,
        message="x" * 4000,
        codes=["MLV%03d" % n for n in range(101, 141)],
    )
    graph = _corpus(1, 0, [huge, dict(UNTAGGED_DIAGNOSTIC, message="y" * 4000)])
    payload = payloads.issues_payload(graph)
    assert mlview_budget.payload_size(payload) <= LIMIT
    for note in payload["coverage"]:
        assert len(note["codes"]) <= 6
        assert len(note["message"]) <= 400
    assert payload["coverage"][0]["message"].endswith("...")


def test_a_diagnostic_with_no_message_or_codes_still_says_the_run_was_blind():
    graph = _corpus(1, 0, [{"kind": "untagged_dataflow", "count": 1}])
    note = payloads.issues_payload(graph)["coverage"][0]
    assert "leakage rules could not check it" in note["message"]
    assert note["codes"] == []
    assert "some rules could not run" in payloads.issues_payload(graph)["note"]
