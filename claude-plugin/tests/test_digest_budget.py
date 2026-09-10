"""Every MCP payload stays under 4 KB, even on a 500-node graph.

CONTRACTS section 5: "every model-facing payload is capped at 4 KB with full
detail behind `graphPath`". A payload that overflows does not merely waste
context — it is what makes an agent stop calling the tool at all. The synthetic
document here is 500 nodes / 800 edges / 300 issues with deliberately verbose
labels and messages, so every builder is measured against a payload that would
be far over budget if it were emitted honestly.
"""

from __future__ import annotations

import json

import pytest

import mlview_payloads as payloads
from plugin_support import synthetic_graph

LIMIT = 4096


@pytest.fixture(scope="module")
def big():
    return synthetic_graph(nodes=500, edges=800, issues=300)


def size(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def test_the_synthetic_graph_is_actually_large(big):
    assert len(big["nodes"]) == 500
    assert len(big["edges"]) == 800
    assert len(big["issues"]) == 300
    assert size(big) > 400_000, "the fixture must dwarf the budget or it proves nothing"


# ------------------------------------------------------------------ mlview_analyze
def test_analyze_payload_fits(big):
    from mlview.api import digest

    payload = payloads.analyze_payload(
        digest(big, limit_bytes=3200), "C:/proj/.mlview/graph.json"
    )
    assert size(payload) <= LIMIT
    assert payload["graphPath"] == "C:/proj/.mlview/graph.json"
    assert payload["stats"]["nodes"] == 500


def test_analyze_payload_keeps_the_graph_path_when_it_has_to_shed(big):
    from mlview.api import digest

    payload = payloads.analyze_payload(
        digest(big, limit_bytes=3200), "C:/proj/.mlview/graph.json", limit=900
    )
    assert size(payload) <= 900
    assert payload["graphPath"] == "C:/proj/.mlview/graph.json"
    assert payload["truncated"] is True


# ------------------------------------------------------------------- mlview_issues
@pytest.mark.parametrize("limit_rows", [5, 20, 100, 300])
def test_issues_payload_fits_at_any_row_limit(big, limit_rows):
    payload = payloads.issues_payload(
        big, min_severity="low", limit=limit_rows, graph_path="C:/proj/.mlview/graph.json"
    )
    assert size(payload) <= LIMIT
    assert payload["countBySeverity"]["high"] > 0
    assert payload["graphPath"] == "C:/proj/.mlview/graph.json"


def test_issues_payload_never_lists_a_suppressed_issue(big):
    payload = payloads.issues_payload(big, limit=300)
    assert payload["suppressedCount"] == 12
    suppressed_ids = {i["id"] for i in big["issues"] if i["suppressed"]}
    assert not suppressed_ids & {row["id"] for row in payload["issues"]}


def test_issues_payload_filters_by_severity_and_code(big):
    high_only = payloads.issues_payload(big, min_severity="high", limit=300)
    assert {row["severity"] for row in high_only["issues"]} == {"high"}

    one_code = payloads.issues_payload(big, codes=["MLV101"], limit=300)
    assert {row["code"] for row in one_code["issues"]} == {"MLV101"}


# -------------------------------------------------------------------- mlview_graph
def _huge_renderers():
    blob = "\n".join("  node_%04d --> node_%04d  %% a long synthetic edge line" % (i, i + 1)
                     for i in range(4000))
    return {"mermaid": lambda g: "flowchart LR\n" + blob, "text": lambda g: blob}


@pytest.mark.parametrize("fmt", ["mermaid", "text", "json"])
@pytest.mark.parametrize("scope", [None, "stages", "stage:train"])
def test_graph_payload_fits(big, fmt, scope):
    payload = payloads.graph_payload(
        big, fmt=fmt, scope=scope, depth=1, renderers=_huge_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    assert size(payload) <= LIMIT
    assert payload["graphPath"] == "C:/proj/.mlview/graph.json"
    assert payload["content"]


def test_graph_payload_node_scope_fits_and_marks_truncation(big):
    node_id = big["nodes"][17]["id"]
    payload = payloads.graph_payload(
        big, fmt="mermaid", scope="node:%s" % node_id, depth=3,
        renderers=_huge_renderers(), graph_path="C:/proj/.mlview/graph.json",
    )
    assert size(payload) <= LIMIT
    assert payload["truncated"] is True
    assert "graph.json" in payload["content"], "the clip note must point at the full document"


def test_graph_payload_rejects_an_unknown_node_scope(big):
    with pytest.raises(ValueError) as excinfo:
        payloads.graph_payload(
            big, fmt="mermaid", scope="node:n:ffffffffffff", depth=1,
            renderers=_huge_renderers(),
        )
    assert "mlview_analyze" in str(excinfo.value)


# ------------------------------------------------------------------ mlview_explain
def test_explain_node_payload_fits_with_sixty_lines_of_source(big):
    node = dict(big["nodes"][4])
    node["loc"] = dict(node["loc"], line=1, endLine=400)
    graph = dict(big, nodes=[node] + big["nodes"][1:])
    source = ["x = some_function_call(%d)  # a long synthetic source line\n" % i for i in range(500)]
    payload = payloads.explain_node_payload(
        graph, node["id"], source_lines=source, graph_path="C:/proj/.mlview/graph.json"
    )
    assert size(payload) <= LIMIT
    assert payload["nodeId"] == node["id"]
    assert payload["source"].count("\n") < 60


def test_explain_node_payload_rejects_an_unknown_id(big):
    with pytest.raises(ValueError) as excinfo:
        payloads.explain_node_payload(big, "n:ffffffffffff")
    assert "mlview_analyze" in str(excinfo.value)


def test_explain_rule_payload_fits_with_a_long_doc():
    doc = "\n".join("Line %d of a very long offline rule document." % i for i in range(400))
    payload = payloads.explain_rule_payload(
        "MLV201", doc,
        {"severity": "high", "frameworks": ["torch"], "tags": ["correctness"],
         "absence": True, "enabled": True, "title": "Gradients are never zeroed",
         "why": "why", "fix_hint": "call zero_grad"},
        "docs/rules/MLV201.md",
    )
    assert size(payload) <= LIMIT
    assert payload["code"] == "MLV201"
    assert payload["severity"] == "high"


def test_explain_rule_payload_without_a_doc_or_a_spec_is_an_error():
    with pytest.raises(ValueError):
        payloads.explain_rule_payload("MLV999", None, None)


# ------------------------------------------------------------- mlview_open_diagram
def test_open_diagram_payload_fits():
    payload = payloads.open_diagram_payload(
        "C:/proj/.mlview/report.html", "file:///C:/proj/.mlview/report.html", True
    )
    assert size(payload) <= LIMIT
    assert payload["opened"] is True


def test_open_diagram_says_where_a_picture_comes_from():
    """VIEW-07: the MCP host cannot render an SVG, so it must say so, every time.

    Asking for "an image of the pipeline" is the single most likely follow-up to
    this tool, and the only honest answer a terminal host has is the HTML path
    plus the viewer surface that exports one. The hint is unconditional so that
    answer cannot depend on whether a browser happened to launch.
    """
    for opened in (True, False):
        payload = payloads.open_diagram_payload(
            "C:/proj/.mlview/report.html",
            "file:///C:/proj/.mlview/report.html",
            opened,
            scope="unit:train.train",
        )
        assert payload["exportHint"] == payloads.EXPORT_HINT
        assert "viewer feature" in payload["exportHint"]
        assert "reportPath" in payload["exportHint"]
        assert size(payload) <= LIMIT


# ------------------------------------------------------------------------ the fitter
def test_fit_never_drops_a_protected_key():
    payload = {
        "graphPath": "C:/proj/.mlview/graph.json",
        "reportPath": "C:/proj/.mlview/report.html",
        "format": "mermaid",
        "rows": ["a padded synthetic row %d" % i for i in range(2000)],
    }
    fitted = payloads.fit(payload, 512)
    assert size(fitted) <= 512
    assert fitted["graphPath"] == payload["graphPath"]
    assert fitted["reportPath"] == payload["reportPath"]
    assert fitted["format"] == "mermaid"
    assert fitted["truncated"] is True


def test_fit_is_a_no_op_when_the_payload_already_fits():
    payload = {"a": 1, "b": [1, 2, 3]}
    assert payloads.fit(payload, 4096) == payload
    assert "truncated" not in payloads.fit(payload, 4096)


def test_clip_text_lines_keeps_whole_lines():
    text = "\n".join("line %d" % i for i in range(500))
    clipped, was_clipped = payloads.clip_text_lines(text, 200, "... more")
    assert was_clipped is True
    assert len(clipped.encode("utf-8")) <= 200
    assert clipped.endswith("... more")
    assert not clipped.splitlines()[-2].endswith("lin"), "lines must not be cut mid-way"


# --------------------------------------- the json format must stay parseable
@pytest.mark.parametrize("scope", [None, "stages", "stage:train"])
def test_graph_payload_json_content_is_still_valid_json_after_truncation(big, scope):
    # A one-line JSON blob cannot be clipped by line without becoming garbage, so
    # the json format sheds whole rows instead. Nesting it inside a JSON string
    # also doubles every quote, which is why the budget is walked down rather
    # than computed once.
    payload = payloads.graph_payload(
        big, fmt="json", scope=scope, depth=1, renderers=_huge_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    assert size(payload) <= LIMIT
    decoded = json.loads(payload["content"])
    assert decoded, "the clipped content must still parse"
    if scope != "stages":
        assert decoded["nodes"], "an index with no nodes at all is useless"
        view = big
        if scope and scope.startswith("stage:"):
            view = payloads.subgraph(big, payloads.stage_scope_ids(big, scope.split(":", 1)[1]))
        if view["edges"]:
            assert decoded["edges"], "the connections are half the answer; do not shed them all"


def test_graph_payload_json_reports_how_much_it_kept(big):
    payload = payloads.graph_payload(
        big, fmt="json", scope=None, depth=1, renderers=_huge_renderers(),
        graph_path="C:/proj/.mlview/graph.json",
    )
    decoded = json.loads(payload["content"])
    assert payload["truncated"] is True
    assert "of 500" in decoded["truncated"]["nodes"]
    assert "of 800" in decoded["truncated"]["edges"]
