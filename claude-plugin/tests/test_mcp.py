"""A real stdio handshake with the MLView MCP server.

Nothing here is mocked: the server is spawned as a subprocess exactly the way
`.mcp.json` spawns it — `PYTHONPATH` pointing only at `claude-plugin/vendor`, so
the test also proves the vendored core is complete and no `pip install` is
needed — and driven through the `mcp` SDK client over stdio. (That claim only
became true once the bootstrap stopped ALSO prepending `<repo>/analyzer/src`;
`test_server_bootstrap.py` is the regression that keeps it true.)

This is the acceptance gate from CONTRACTS A7: initialize, tools/list asserting
exactly the five tool names with usable input schemas, then tools/call on the
sample project (or the rule fixtures when `samples/` has not been written yet).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

anyio = pytest.importorskip("anyio", reason="the mcp SDK's async runtime is required")
pytest.importorskip("mcp", reason="the mcp SDK is required for the stdio handshake")

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from plugin_support import (  # noqa: E402
    REPO_ROOT,
    SERVER_SCRIPT,
    VENDOR_DIR,
    child_env,
    corpus_path,
)

EXPECTED_TOOLS = {
    "mlview_analyze", "mlview_issues", "mlview_graph", "mlview_explain",
    "mlview_open_diagram",
}
LIMIT = 4096


def _size(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _text_size(result) -> int:
    """Bytes of the concatenated `content` text — what a model without structured
    output support actually reads, and what the 4 KB cap is really about.

    The SDK renders it with `indent=2`, ~27% larger than `structuredContent`; a
    budget measured only on the latter let `mlview_issues` ship 4985 bytes here.
    """
    return len(
        "".join(getattr(part, "text", "") or "" for part in result.content).encode("utf-8")
    )


def _run(coro_factory, data_dir):
    """Spawn the server, run one coroutine against a live session, tear it down."""

    async def main():
        env = child_env(MLVIEW_DATA_DIR=str(data_dir))
        # Exactly what .mcp.json does: vendor only, so an incomplete vendor fails here.
        env["PYTHONPATH"] = VENDOR_DIR
        params = StdioServerParameters(
            command=sys.executable,
            args=["-X", "utf8", SERVER_SCRIPT],
            env=env,
            cwd=REPO_ROOT,
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                return await coro_factory(session)

    return anyio.run(main)


@pytest.fixture(scope="module")
def session_data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("mlview-mcp-data")


@pytest.fixture(scope="module")
def listed(session_data_dir):
    async def go(session):
        result = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "schema": tool.input_schema,
            }
            for tool in result.tools
        ]

    return _run(go, session_data_dir)


# ------------------------------------------------------------------------ handshake
def test_the_vendored_core_is_what_the_server_imports():
    assert os.path.isdir(os.path.join(VENDOR_DIR, "mlview")), (
        "claude-plugin/vendor/mlview is missing — run `python tools/sync-core.py`. "
        "Without it the plugin would need a pip install, which the contract forbids."
    )


def test_tools_list_offers_exactly_the_five_contract_tools(listed):
    assert {tool["name"] for tool in listed} == EXPECTED_TOOLS


def test_every_tool_has_a_usable_input_schema(listed):
    for tool in listed:
        schema = tool["schema"]
        assert isinstance(schema, dict), tool["name"]
        assert schema.get("type") == "object", tool["name"]
        assert isinstance(schema.get("properties"), dict), tool["name"]


def test_every_tool_description_tells_the_model_when_to_call_it(listed):
    for tool in listed:
        assert len(tool["description"]) > 200, (
            "%s has a thin description; the docstring IS what Claude reads when "
            "deciding whether to call it" % tool["name"]
        )


def test_tool_inputs_match_the_contract(listed):
    by_name = {tool["name"]: set(tool["schema"].get("properties", {})) for tool in listed}
    assert {"path", "framework", "maxNodes", "includeHtml"} <= by_name["mlview_analyze"]
    # CHANGED by ROADMAP RAIL-GROUP (2026-09-08): `groupBy` joined the contract set.
    assert {
        "path", "minSeverity", "minConfidence", "code", "limit", "groupBy"
    } <= by_name["mlview_issues"]
    assert {"path", "format", "scope", "depth"} <= by_name["mlview_graph"]
    assert {"nodeId", "code", "graphPath"} <= by_name["mlview_explain"]
    assert {"path", "graphPath", "out"} <= by_name["mlview_open_diagram"]


# ----------------------------------------------------------------------- the calls
@pytest.fixture(scope="module")
def analyzed(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool("mlview_analyze", {"path": corpus})

    return _run(go, session_data_dir)


def test_analyze_succeeds_on_the_corpus(analyzed):
    assert analyzed.is_error is False, analyzed.content


def test_analyze_returns_structured_content_under_four_kilobytes(analyzed):
    payload = analyzed.structured_content
    assert payload is not None, "the SDK must serialize the dict as structuredContent"
    assert _size(payload) <= LIMIT
    assert payload["schemaVersion"] == "1.0"
    assert payload["filesAnalyzed"] >= 1
    assert payload["stats"]["nodes"] > 0
    assert isinstance(payload["lanes"], list)
    assert len(payload.get("topIssues", [])) <= 10


def test_analyze_also_returns_the_payload_as_text_content(analyzed):
    texts = [part.text for part in analyzed.content if getattr(part, "text", None)]
    assert texts, "every result carries the JSON as content text too"
    assert json.loads(texts[0])["schemaVersion"] == "1.0"


def test_analyze_writes_a_readable_graph_document(analyzed):
    graph_path = analyzed.structured_content["graphPath"]
    assert os.path.isfile(graph_path), graph_path
    with open(graph_path, "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    assert graph["schemaVersion"] == "1.0"
    assert len(graph["nodes"]) == analyzed.structured_content["stats"]["nodes"]


def test_issues_succeeds_and_fits_the_budget(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_issues", {"path": corpus, "minSeverity": "low", "limit": 50}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert _size(payload) <= LIMIT
    assert set(payload["countBySeverity"]) == {"low", "medium", "high"}
    for row in payload["issues"]:
        assert row["code"].startswith("MLV")
        assert row["file"] and row["line"] >= 1


def test_graph_renders_mermaid_by_default(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool("mlview_graph", {"path": corpus})

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert _size(payload) <= LIMIT
    assert payload["format"] == "mermaid"
    assert payload["content"].lstrip().startswith("flowchart")


def test_graph_stage_scope_summarizes_the_lanes(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stages", "format": "text"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert payload["scope"] == "stages"
    assert "train" in payload["content"]


def test_explain_returns_a_rule_record(session_data_dir):
    async def go(session):
        return await session.call_tool("mlview_explain", {"code": "MLV201"})

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert _size(payload) <= LIMIT
    assert payload["code"] == "MLV201"
    assert payload.get("severity") or payload.get("doc")


def test_open_diagram_writes_the_report_without_launching_a_browser(session_data_dir):
    corpus = corpus_path()
    out = os.path.join(str(session_data_dir), "explicit-report.html")

    async def go(session):
        return await session.call_tool(
            "mlview_open_diagram", {"path": corpus, "out": out}
        )

    result = _run(go, session_data_dir)  # child_env sets MLVIEW_NO_OPEN=1
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert payload["opened"] is False, "MLVIEW_NO_OPEN=1 must suppress the launch"
    assert os.path.isfile(payload["reportPath"])
    with open(payload["reportPath"], "r", encoding="utf-8") as fh:
        html = fh.read()
    assert "http://" not in html and "https://" not in html, "the report must be offline"


# ------------------------------------- the CONTENT text is what the cap is about
def test_every_tool_result_text_block_fits_four_kilobytes(session_data_dir):
    """The frozen 4 KB cap, asserted on the text block of all five tools."""
    corpus = corpus_path()

    async def go(session):
        calls = [
            ("mlview_analyze", {"path": corpus}),
            ("mlview_issues", {"path": corpus, "limit": 50}),
            ("mlview_issues", {"path": corpus, "minSeverity": "low"}),
            ("mlview_graph", {"path": corpus}),
            ("mlview_graph", {"path": corpus, "format": "text"}),
            ("mlview_graph", {"path": corpus, "format": "json"}),
            ("mlview_explain", {"code": "MLV201"}),
            ("mlview_open_diagram", {"path": corpus}),
        ]
        return [(name, await session.call_tool(name, args)) for name, args in calls]

    for name, result in _run(go, session_data_dir):
        assert result.is_error is False, (name, result.content)
        assert _text_size(result) <= LIMIT, "%s: %d bytes of model-facing text" % (
            name, _text_size(result),
        )
        assert _size(result.structured_content) <= LIMIT, name


def test_issues_says_how_much_was_actually_analyzed(session_data_dir):
    """Zero issues must be distinguishable from zero files (MLV-R2-108)."""
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool("mlview_issues", {"path": corpus})

    payload = _run(go, session_data_dir).structured_content
    assert payload["filesAnalyzed"] >= 1, payload
    assert "filesFailed" in payload and "notebooksSkipped" in payload
    assert "note" not in payload, "a real corpus needs no not-a-clean-result note"


def test_an_unanalyzable_directory_is_not_a_clean_bill_of_health(session_data_dir, tmp_path):
    empty = tmp_path / "no_python_here"
    empty.mkdir()
    (empty / "readme.txt").write_text("hello", encoding="utf-8")

    async def go(session):
        return await session.call_tool("mlview_issues", {"path": str(empty)})

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert payload["countBySeverity"] == {"low": 0, "medium": 0, "high": 0}
    assert payload["filesAnalyzed"] == 0
    assert "clean bill of health" in payload.get("note", ""), payload


def test_a_scoped_diagram_does_not_claim_the_other_lanes_are_missing(session_data_dir):
    """MLV-R2-103, over the wire: `stage:train` must not report seven absences."""
    corpus = corpus_path()

    async def lanes(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stages", "format": "json"}
        )

    rows = json.loads(_run(lanes, session_data_dir).structured_content["content"])
    absent = sorted(row["stage"] for row in rows if not row["present"])
    present = [row["stage"] for row in rows if row["present"]]
    if not present:
        pytest.skip("this corpus detected no stages at all")

    async def go(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stage:%s" % present[0]}
        )

    payload = _run(go, session_data_dir).structured_content
    lines = [l for l in payload["content"].splitlines() if "not detected" in l]
    named = sorted(
        s.strip() for line in lines for s in line.split(":", 1)[1].split(",")
    ) if lines else []
    assert named == absent, (
        "a scoped diagram named %s as not detected; the project actually lacks %s"
        % (named, absent)
    )


def test_out_may_not_escape_the_permitted_roots(session_data_dir):
    """MLV-R2-106, over the wire: the write AND the launch target are contained."""
    corpus = corpus_path()
    escape = "../../../../mlview_escape_%d.html" % os.getpid()

    async def go(session):
        return await session.call_tool(
            "mlview_open_diagram", {"path": corpus, "out": escape}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True, result.structured_content
    text = " ".join(getattr(part, "text", "") for part in result.content)
    assert "out must stay inside" in text, text
    assert "MLVIEW_DATA_DIR" in text, text
    assert not os.path.exists(
        os.path.abspath(os.path.join(REPO_ROOT, escape))
    ), "the refused path must not have been written"


# --------------------------------------------------------------------- error paths
def test_a_missing_path_is_reported_as_an_actionable_error(session_data_dir):
    async def go(session):
        return await session.call_tool(
            "mlview_analyze", {"path": "no/such/directory/anywhere"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True
    text = " ".join(getattr(part, "text", "") for part in result.content)
    assert "path not found" in text, text
    assert "no/such/directory/anywhere" in text, text


def test_explain_without_an_argument_says_what_is_needed(session_data_dir):
    async def go(session):
        return await session.call_tool("mlview_explain", {})

    result = _run(go, session_data_dir)
    assert result.is_error is True
    text = " ".join(getattr(part, "text", "") for part in result.content)
    assert "nodeId" in text and "code" in text


# --------------------------------------------------------- explain a real node
def test_explain_walks_a_node_from_the_graph_the_server_just_wrote(
    analyzed, session_data_dir
):
    with open(analyzed.structured_content["graphPath"], "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    # An op node with a real source location and at least one edge is the case a
    # model actually asks about.
    targets = {e["target"] for e in graph["edges"]}
    node = next(n for n in graph["nodes"] if n["id"] in targets and n["loc"].get("absFile"))

    async def go(session):
        return await session.call_tool(
            "mlview_explain",
            {"nodeId": node["id"], "graphPath": analyzed.structured_content["graphPath"]},
        )

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert _size(payload) <= LIMIT
    assert payload["nodeId"] == node["id"]
    assert payload["stage"] == node["stage"]
    assert payload["incoming"], "the node was chosen because it has an incoming edge"
    assert payload["source"], "explain must return the real source segment"
    assert payload["stageEvidence"], "the 'why is it in this lane' evidence must survive"


def test_a_second_analyze_reuses_the_cached_graph(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        first = await session.call_tool("mlview_analyze", {"path": corpus})
        second = await session.call_tool("mlview_analyze", {"path": corpus})
        return first, second

    first, second = _run(go, session_data_dir)
    assert first.is_error is False and second.is_error is False
    assert first.structured_content["graphPath"] == second.structured_content["graphPath"]
    assert first.structured_content["stats"] == second.structured_content["stats"]


# ------------------------------------- out-of-range enums reach the model as errors
def _tool_error_text(result) -> str:
    return " ".join(getattr(part, "text", "") for part in result.content)


def test_an_unknown_graph_format_is_an_error_not_a_silent_fall_back(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "format": "bogus"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True, (
        "a coerced format comes back labelled 'mermaid', so the model cannot "
        "even detect the substitution: %r" % (result.structured_content,)
    )
    text = _tool_error_text(result)
    assert "format" in text and "mermaid" in text and "json" in text, text


def test_an_unknown_stage_scope_is_an_error_not_an_empty_diagram(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stage:nosuch"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True, result.structured_content
    text = _tool_error_text(result)
    assert "stage:nosuch" in text and "stage:train" in text, text


def test_an_unknown_min_severity_is_an_error_not_the_loosest_filter(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_issues", {"path": corpus, "minSeverity": "bogus"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True, result.structured_content
    text = _tool_error_text(result)
    assert "minSeverity" in text and "high" in text, text


def test_a_stage_the_project_lacks_is_answered_with_a_note(session_data_dir):
    corpus = corpus_path()

    async def lanes(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stages", "format": "json"}
        )

    rows = json.loads(_run(lanes, session_data_dir).structured_content["content"])
    absent = next((row["stage"] for row in rows if not row["present"]), None)
    if absent is None:
        pytest.skip("this corpus exercises all eight stages")

    async def go(session):
        return await session.call_tool(
            "mlview_graph", {"path": corpus, "scope": "stage:%s" % absent}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert payload["scope"] == "stage:%s" % absent
    assert absent in payload.get("note", ""), (
        "an undetected lane must say so, not look like a mistyped stage id"
    )


def test_issues_can_fold_a_workspace_into_one_row_per_rule(session_data_dir):
    """RAIL-GROUP over the wire: the real server, the real corpus, one row per code.

    The flat list on an inherited repo is eleven codes repeated ten times; the whole
    value of the flag is that the model reads twelve rows and still learns the true
    occurrence counts, so this asserts the counts and the folding note as well as
    the shape."""
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_issues", {"path": corpus, "groupBy": "rule", "limit": 200}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is False, result.content
    payload = result.structured_content
    assert _size(payload) <= LIMIT
    assert payload["groupBy"] == "rule"
    assert "issues" not in payload, "groups replace the rows; both would blow the budget"
    codes = [row["key"] for row in payload["groups"]]
    assert codes and all(code.startswith("MLV") for code in codes)
    assert len(codes) == len(set(codes)), "one row per code"
    assert all(row["count"] >= 1 and row["sites"] for row in payload["groups"])
    assert "folded" in payload["note"] and "not filtered" in payload["note"]


def test_an_unknown_group_by_is_an_error_not_an_ungrouped_list(session_data_dir):
    corpus = corpus_path()

    async def go(session):
        return await session.call_tool(
            "mlview_issues", {"path": corpus, "groupBy": "rules"}
        )

    result = _run(go, session_data_dir)
    assert result.is_error is True
    text = " ".join(getattr(block, "text", "") for block in result.content)
    assert "groupBy" in text
    for accepted in ("rule", "file", "severity"):
        assert accepted in text


def test_the_analyze_tool_warns_the_model_off_a_single_file(listed):
    """COVERAGE: the docstring IS the instruction Claude reads before choosing a
    path. MLV301/302/401/501 cannot fire on a lone file, so a single-file call is
    the quiet way to get a shorter, wrong answer."""
    description = next(t["description"] for t in listed if t["name"] == "mlview_analyze")
    assert "single_file_analysis" in description
    assert "untagged_dataflow" in description
    for code in ("MLV301", "MLV302", "MLV401", "MLV501"):
        assert code in description
    assert "DIRECTORY" in description
