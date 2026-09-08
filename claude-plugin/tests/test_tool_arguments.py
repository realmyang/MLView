"""Out-of-range tool arguments are reported, never silently coerced.

A model that typos `format="mermiad"` or `minSeverity="hgih"` must get an error
it can retry, not a confident answer of the wrong shape. Silent coercion is the
worst failure mode here because the payload echoes the *coerced* value back:
`mlview_graph(format="bogus")` used to return `{"format": "mermaid", ...}`, so
the substitution was invisible from the result, and `minSeverity="bogus"` used
to mean `low` — the loosest filter, for a caller asking for a stricter one.

The pure builders raise `ValueError`; the server's `visible_errors` wrapper
turns that into a `ToolError` whose text reaches the model verbatim (the same
treatment `resolve_path` already gave a bad `path`).
"""

from __future__ import annotations

import pytest

import mlview_payloads as payloads
from plugin_support import STAGES, synthetic_graph


@pytest.fixture(scope="module")
def graph():
    return synthetic_graph(nodes=40, edges=60, issues=20)


def _renderers():
    return {
        "mermaid": lambda view: "flowchart LR\n  a --> b\n",
        "text": lambda view: "config -> data\n",
    }


def _graph(graph, **kwargs):
    call = {"fmt": "mermaid", "scope": None, "depth": 1, "renderers": _renderers()}
    call.update(kwargs)
    return payloads.graph_payload(graph, **call)


# ------------------------------------------------------------------ mlview_issues
@pytest.mark.parametrize("bad", ["bogus", "HIGH!", "critical", "1", " "])
def test_issues_rejects_a_severity_outside_the_enum(graph, bad):
    with pytest.raises(ValueError) as excinfo:
        payloads.issues_payload(graph, min_severity=bad)
    message = str(excinfo.value)
    assert "minSeverity" in message
    for accepted in ("low", "medium", "high"):
        assert accepted in message, "the error must name the accepted values"


@pytest.mark.parametrize("good", ["low", "medium", "high"])
def test_issues_still_accepts_every_contract_severity(graph, good):
    payload = payloads.issues_payload(graph, min_severity=good)
    assert set(payload["countBySeverity"]) == {"low", "medium", "high"}


def test_issues_treats_a_missing_severity_as_low(graph):
    assert payloads.issues_payload(graph, min_severity=None) == payloads.issues_payload(
        graph, min_severity="low"
    )


def test_a_stricter_severity_never_returns_more_rows_than_a_looser_one(graph):
    low = payloads.issues_payload(graph, min_severity="low", limit=300)
    high = payloads.issues_payload(graph, min_severity="high", limit=300)
    assert len(high["issues"]) <= len(low["issues"])


# ------------------------------------------------------------------- mlview_graph
@pytest.mark.parametrize("bad", ["bogus", "mermiad", "svg", "yaml"])
def test_graph_rejects_a_format_outside_the_enum(graph, bad):
    with pytest.raises(ValueError) as excinfo:
        _graph(graph, fmt=bad)
    message = str(excinfo.value)
    assert "format" in message
    for accepted in payloads.GRAPH_FORMATS:
        assert accepted in message


@pytest.mark.parametrize("good", ["mermaid", "text", "json", "MERMAID", " text "])
def test_graph_still_accepts_every_contract_format(graph, good):
    payload = _graph(graph, fmt=good)
    assert payload["format"] == good.strip().lower()


def test_graph_defaults_to_mermaid_when_the_format_is_omitted(graph):
    assert _graph(graph, fmt=None)["format"] == "mermaid"
    assert _graph(graph, fmt="")["format"] == "mermaid"


def test_graph_rejects_an_unknown_stage_id(graph):
    with pytest.raises(ValueError) as excinfo:
        _graph(graph, scope="stage:nosuch")
    message = str(excinfo.value)
    assert "stage:nosuch" in message
    assert "stage:train" in message, "the error must list the real stage ids"


@pytest.mark.parametrize("stage_id", [row[0] for row in STAGES])
def test_graph_accepts_every_canonical_stage_id(graph, stage_id):
    assert _graph(graph, scope="stage:%s" % stage_id)["scope"] == "stage:%s" % stage_id


@pytest.mark.parametrize("bad", ["everything", "lane:train", "stage", "node"])
def test_graph_rejects_a_scope_that_is_not_a_form_of_the_grammar(graph, bad):
    """CHANGED for CONTRACTS 11.10: `"all"` left this list because it is now a
    legal selector (section 11.1, `SPEC := "all" | KIND ":" TARGET`) meaning the
    whole graph — the case below asserts it. Everything else here still has no
    kind the grammar knows, so it is still a refusal rather than a guess."""
    with pytest.raises(ValueError) as excinfo:
        _graph(graph, scope=bad)
    message = str(excinfo.value)
    assert "scope" in message
    assert "stages" in message and "node:" in message


def test_graph_accepts_all_as_the_whole_graph(graph):
    """`scope="all"` is the grammar's identity: same content as omitting it."""
    assert _graph(graph, scope="all")["scope"] == "all"
    assert _graph(graph, scope="all")["content"] == _graph(graph, scope=None)["content"]


def test_graph_rejects_an_empty_stage_id(graph):
    with pytest.raises(ValueError):
        _graph(graph, scope="stage:")


def test_the_stage_id_list_is_the_eight_canonical_stages():
    assert payloads.STAGE_IDS == tuple(row[0] for row in STAGES)


# --------------------------------------------- an absent stage is answered, not refused
def test_an_absent_stage_comes_back_with_a_note_rather_than_an_empty_diagram(graph):
    absent = dict(graph)
    absent["stages"] = [
        dict(row, present=False, nodeCount=0) if row.get("id") == "deliver" else row
        for row in graph["stages"]
    ]
    absent["nodes"] = [n for n in graph["nodes"] if n.get("stage") != "deliver"]

    payload = _graph(absent, scope="stage:deliver")
    assert payload["scope"] == "stage:deliver"
    assert "note" in payload, (
        "an empty lane must be distinguishable from a lane the caller mistyped"
    )
    assert "deliver" in payload["note"]


def test_a_present_stage_is_never_described_as_absent(graph):
    """The note on a scoped view says it is filtered — never that the lane is missing.

    A scoped call gets a note because its per-stage counts describe the scope, not
    the project; what it must NOT say is that the stage was not detected, which is
    what `commands/mlview.md` tells the model to report as a finding.
    """
    note = _graph(graph, scope="stage:train").get("note", "")
    assert "not detected" not in note and "was not detected" not in note, note
    assert "filtered view" in note, note
