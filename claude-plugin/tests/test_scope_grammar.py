"""The scope selector grammar at the MCP boundary (CONTRACTS 11.1 / 11.10).

Four obligations, each of which is a way the feature could ship broken while
every other gate stayed green:

1. **`scope="units"` is discovery, not a sixth tool** — the catalogue must carry
   the seven documented columns, in the documented order, and still fit the 4 KB
   budget on a 500-node graph.
2. **A scoped `mlview_analyze` says it is scoped** — the digest carries the
   section 11.6 `scope` block, so "17 nodes" cannot be read as the project's size.
3. **The error names every accepted value.** `mlview_graph`'s docstring promises
   it; a promise the server does not keep is a lie the model acts on.
4. **One projection, two processes.** The CLI (running `analyzer/src`) and the
   MCP server (running the vendored copy, over a real stdio handshake) must agree
   about what three selectors select. This is the plugin-side half of the parity
   gate `tools/verify.py --scopes` runs for the TypeScript port.

The cache obligation is asserted too: a scoped call must not key the analysis on
the scope, and `graphPath` must keep pointing at the FULL document.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import mlview_payloads as payloads
import mlview_scope as scopes
from mlview_budget import payload_size
from plugin_support import REPO_ROOT, child_env, corpus_path, synthetic_graph

LIMIT = 4096
SELECTORS = ("stage:train", "unit:train.train", "concern:evaluation")


def _renderers():
    from mlview.api import render_mermaid, render_text

    return {"mermaid": render_mermaid, "text": render_text}


@pytest.fixture(scope="module")
def sample_graph():
    """The real corpus, analyzed once in-process."""
    from mlview.api import AnalyzeOptions, analyze_to_dict

    return analyze_to_dict(
        AnalyzeOptions(paths=(os.path.join(REPO_ROOT, corpus_path()),))
    )


@pytest.fixture(scope="module")
def big():
    return synthetic_graph(nodes=500, edges=800, issues=300)


def _graph_payload(graph, **kwargs):
    call = {
        "fmt": "mermaid", "scope": None, "depth": None, "renderers": _renderers(),
        "graph_path": "C:/proj/.mlview/graph.json",
    }
    call.update(kwargs)
    return payloads.graph_payload(graph, **call)


# ------------------------------------------------------ 1. the units catalogue
@pytest.mark.parametrize("fmt", ["mermaid", "text", "json"])
def test_the_units_catalogue_fits_the_budget_on_a_five_hundred_node_graph(big, fmt):
    payload = _graph_payload(big, fmt=fmt, scope="units")
    assert payload_size(payload) <= LIMIT
    assert payload["scope"] == "units"
    assert payload["content"], "a catalogue with no rows at all is useless"


def test_the_units_catalogue_has_the_documented_row_shape(sample_graph):
    rows = json.loads(_graph_payload(sample_graph, fmt="json", scope="units")["content"])
    assert rows, "the sample corpus has classes, functions and loops to scope to"
    for row in rows:
        assert list(row) == list(scopes.CATALOG_ROW_KEYS), row
        assert row["nodeId"].startswith("n:")
        assert isinstance(row["nodeCount"], int) and row["nodeCount"] >= 1
        assert row["maxSeverity"] in (None, "low", "medium", "high")
        assert row["file"] and isinstance(row["line"], int)


def test_the_units_catalogue_is_sorted_biggest_first(sample_graph):
    rows = json.loads(_graph_payload(sample_graph, fmt="json", scope="units")["content"])
    keys = [(-r["nodeCount"], r["file"], r["line"], r["qualname"]) for r in rows]
    assert keys == sorted(keys), "CONTRACTS 11.10 sorts (-nodeCount, file, line, qualname)"


def test_every_catalogued_unit_is_a_selector_that_really_resolves(sample_graph):
    """A menu that lists a dish the kitchen cannot cook is worse than no menu."""
    rows = json.loads(_graph_payload(sample_graph, fmt="json", scope="units")["content"])
    for row in rows:
        spec = "unit:%s" % row["qualname"]
        payload = _graph_payload(sample_graph, fmt="text", scope=spec)
        assert payload["scope"] == spec
        assert "matched no nodes" not in payload.get("note", ""), spec


def test_the_catalogue_is_a_project_level_statement_not_a_filtered_view(sample_graph):
    for scope in ("units", "stages"):
        note = _graph_payload(sample_graph, scope=scope).get("note", "")
        assert "filtered view" not in note, scope


# --------------------------------------------- 2. a scoped digest says it is scoped
def test_a_scoped_analyze_digest_carries_the_scope_block(sample_graph):
    from mlview.api import digest

    spec, view, notes, _hops = scopes.apply_scope(sample_graph, "concern:evaluation", 1)
    payload = payloads.analyze_payload(
        digest(view, limit_bytes=3200), "C:/proj/.mlview/graph.json",
        graph=sample_graph, scope=spec, extra_notes=notes,
    )
    assert payload_size(payload) <= LIMIT
    block = payload["scope"]
    assert set(block) == {
        "spec", "kind", "target", "depth", "nodesInScope", "nodesTotal"
    }, block
    assert block["spec"] == "concern:evaluation"
    assert block["kind"] == "concern" and block["target"] == "evaluation"
    assert block["depth"] == 1
    assert 0 < block["nodesInScope"] < block["nodesTotal"] == len(sample_graph["nodes"])
    assert "filtered view" in payload["note"]
    assert payload["graphPath"].endswith("graph.json"), "the FULL document, always"


def test_an_unscoped_digest_is_byte_identical_to_before_the_feature(sample_graph):
    from mlview.api import digest

    plain = payloads.analyze_payload(digest(sample_graph, limit_bytes=3200), "gp", graph=sample_graph)
    for spec in (None, "", "   ", "all", "ALL"):
        _spec, view, notes, _hops = scopes.apply_scope(sample_graph, spec, None)
        scoped = payloads.analyze_payload(
            digest(view, limit_bytes=3200), "gp", graph=sample_graph,
            scope=_spec, extra_notes=notes,
        )
        assert scoped == plain, spec
        assert "scope" not in scoped, spec


def test_a_scoped_issue_list_reports_only_the_retained_findings(sample_graph):
    spec, view, notes, _hops = scopes.apply_scope(sample_graph, "unit:SmallCNN", None)
    scoped = payloads.issues_payload(view, graph_path="gp", scope=spec, extra_notes=notes)
    whole = payloads.issues_payload(sample_graph, graph_path="gp")
    assert scoped["scope"] == "unit:SmallCNN"
    assert "filtered view" in scoped["note"]
    codes = {row["code"] for row in scoped["issues"]}
    assert codes and codes < {row["code"] for row in whole["issues"]}
    assert sum(scoped["countBySeverity"].values()) < sum(whole["countBySeverity"].values())


# ------------------------------------------------- 3. the error names every form
@pytest.mark.parametrize(
    "bad", ["bogus:x", "stage:nope", "concern:nope", "node:n:deadbeefdead",
            "file:nope.py", "everything", "unit"]
)
def test_an_unusable_selector_names_every_accepted_form(sample_graph, bad):
    with pytest.raises(ValueError) as excinfo:
        _graph_payload(sample_graph, scope=bad)
    message = str(excinfo.value)
    for form in ("stages", "units", "'all'", "stage:train", "unit:", "file:",
                 "concern:", "node:", "pipeline:"):
        assert form in message, "%r is missing %r" % (message, form)
    for concern in ("config", "data", "optimization", "evaluation"):
        assert concern in message
    assert bad in message, "the offending value must be quoted back"


def test_the_accepted_values_sentence_is_the_one_the_docstring_promises():
    """CONTRACTS 11.10: the grammar and `mlview_graph`'s docstring move together."""
    import mlview_mcp  # noqa: PLC0415 - imported here so the bootstrap runs first

    doc = mlview_mcp.mlview_graph.__doc__ or ""
    for form in ("stages", "units", "all", "stage:<id>", "unit:<name>",
                 "file:<path.py>", "concern:<name>", "node:<nodeId>",
                 "pipeline:<entry>", "symbol:<name>"):
        assert form in doc, form
    for value in scopes.STAGE_IDS:
        assert value in doc
    assert "depth" in doc and "0, 1 or 2" in doc


def test_an_unknown_node_is_told_how_to_find_a_real_one(sample_graph):
    with pytest.raises(ValueError) as excinfo:
        _graph_payload(sample_graph, scope="node:n:deadbeefdead")
    assert "mlview_analyze" in str(excinfo.value)


@pytest.mark.parametrize("depth,expected", [(3, 2), (-1, 0), (99, 2)])
def test_a_depth_outside_the_bounds_is_reported_not_applied(sample_graph, depth, expected):
    payload = _graph_payload(sample_graph, scope="unit:train.train", depth=depth)
    assert "depth=%d" % depth in payload["note"], payload["note"]
    assert scopes.clamp_depth(depth)[0] == expected


def test_the_per_kind_default_depth_is_what_omitting_depth_means(sample_graph):
    """`node:<id>` keeps its historical one-hop neighbourhood when depth is omitted."""
    omitted = _graph_payload(sample_graph, fmt="json", scope="node:%s" % sample_graph["nodes"][3]["id"])
    explicit = _graph_payload(
        sample_graph, fmt="json", scope="node:%s" % sample_graph["nodes"][3]["id"], depth=1
    )
    assert omitted == explicit


# --------------------------------------------------- 4. CLI vs MCP, three selectors
def _cli_scoped(corpus: str, spec: str) -> dict:
    """`python -m mlview analyze <corpus> --scope <spec> --json -`, real analyzer."""
    env = child_env()
    env["PYTHONPATH"] = os.path.join(REPO_ROOT, "analyzer", "src")
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "mlview", "analyze", corpus,
         "--scope", spec, "--json", "-"],
        cwd=REPO_ROOT, env=env, capture_output=True, shell=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    return json.loads(proc.stdout.decode("utf-8"))


@pytest.fixture(scope="module")
def mcp_scoped(tmp_path_factory):
    """One stdio session, three scoped `mlview_analyze` calls, vendored core only."""
    anyio = pytest.importorskip("anyio", reason="the mcp SDK's async runtime is required")
    pytest.importorskip("mcp", reason="the mcp SDK is required for the stdio handshake")
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    from plugin_support import SERVER_SCRIPT, VENDOR_DIR

    data_dir = tmp_path_factory.mktemp("mlview-scope-data")
    corpus = corpus_path()

    async def main():
        env = child_env(MLVIEW_DATA_DIR=str(data_dir))
        env["PYTHONPATH"] = VENDOR_DIR  # exactly what .mcp.json does
        params = StdioServerParameters(
            command=sys.executable, args=["-X", "utf8", SERVER_SCRIPT],
            env=env, cwd=REPO_ROOT,
        )
        out = {}
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                for spec in SELECTORS:
                    result = await session.call_tool(
                        "mlview_analyze", {"path": corpus, "scope": spec}
                    )
                    assert result.is_error is False, result.content
                    out[spec] = result.structured_content
                units = await session.call_tool(
                    "mlview_graph", {"path": corpus, "scope": "units", "format": "json"}
                )
                assert units.is_error is False, units.content
                out["__units__"] = units.structured_content
                # The SDK renders `content[0].text` with indent=2 — ~27% larger
                # than structuredContent, and it is what a model without
                # structured output actually reads. That is the 4 KB budget.
                out["__units_text_bytes__"] = len(
                    "".join(getattr(part, "text", "") or "" for part in units.content)
                    .encode("utf-8")
                )
                bad = await session.call_tool(
                    "mlview_graph", {"path": corpus, "scope": "concern:nope"}
                )
                out["__bad__"] = (
                    bad.is_error,
                    "".join(getattr(p, "text", "") or "" for p in bad.content),
                )
        return out

    return anyio.run(main)


@pytest.mark.parametrize("spec", SELECTORS)
def test_the_cli_and_the_mcp_server_project_identically(mcp_scoped, spec):
    doc = _cli_scoped(corpus_path(), spec)
    digest = mcp_scoped[spec]
    view = doc["view"]
    assert digest["scope"]["spec"] == view["scope"] == spec
    assert digest["scope"]["depth"] == view["depth"]
    assert digest["scope"]["nodesInScope"] == doc["stats"]["nodes"] == len(doc["nodes"])
    assert digest["scope"]["nodesTotal"] == view["of"]["nodes"]
    assert digest["stats"]["nodes"] == doc["stats"]["nodes"]
    assert digest["stats"]["edges"] == doc["stats"]["edges"]
    assert digest["stats"]["issues"] == doc["stats"]["issues"]


def test_a_scoped_call_leaves_the_full_document_on_disk(mcp_scoped):
    """The cache is keyed on (path, framework, maxNodes, signature) — never scope."""
    digests = [mcp_scoped[spec] for spec in SELECTORS]
    paths = {digest["graphPath"] for digest in digests}
    assert len(paths) == 1, "three scopes wrote three graph documents: %s" % paths
    with open(next(iter(paths)), "r", encoding="utf-8") as fh:
        stored = json.load(fh)
    assert "view" not in stored, "graphPath must hold the FULL, unprojected document"
    for digest in digests:
        assert digest["scope"]["nodesTotal"] == len(stored["nodes"])


def test_the_units_catalogue_survives_the_wire_within_budget(mcp_scoped):
    """Over stdio, in the encoding the model reads — not just in-process."""
    assert mcp_scoped["__units_text_bytes__"] <= LIMIT, mcp_scoped["__units_text_bytes__"]
    payload = mcp_scoped["__units__"]
    assert payload["scope"] == "units"
    rows = json.loads(payload["content"])
    assert rows, "the corpus has scopable units"
    for row in rows:
        assert list(row) == list(scopes.CATALOG_ROW_KEYS), row
    assert "filtered view" not in payload.get("note", "")


def test_an_unusable_selector_reaches_the_model_as_a_visible_error(mcp_scoped):
    """`visible_errors` must carry the grammar's text, not "tool failed"."""
    is_error, text = mcp_scoped["__bad__"]
    assert is_error is True, text
    for form in ("concern:nope", "stages", "units", "stage:train", "evaluation"):
        assert form in text, text


# ------------------------------------------ 5. ONE grammar, in every host (11.16)
#
# MLV-P12 adds `pipeline:` to the §11.1 KIND enum, and §11.16 says the two
# `project()` implementations, the parity fixtures, `mlview.api.SCOPE_KINDS` and
# the MCP docstring move TOGETHER. Two of those have gates already. These are the
# two that did not: the prose a model reads, and the sentence an unusable
# selector gets back. A host describing a smaller product than the CLI ships is
# how `concern:` was unreachable from Copilot agent mode for a whole release.


def test_the_prose_names_every_kind_the_core_actually_accepts():
    """The drift direction that matters: a kind the core gained and the prose
    never mentioned is a feature no model will ever ask for."""
    import mlview_mcp  # noqa: PLC0415 - imported here so the bootstrap runs first
    from mlview.api import SCOPE_KINDS

    accepted = scopes.accepted_values()
    doc = mlview_mcp.mlview_graph.__doc__ or ""
    for kind in SCOPE_KINDS:
        assert "%s:" % kind in accepted, "%r is not in the accepted values" % kind
        assert '"%s:' % kind in doc, "%r is not in the mlview_graph docstring" % kind


def test_pipeline_is_in_the_grammar_prose_of_this_host():
    """The MCP half of "all hosts describe one grammar". The VS Code half is
    `ScopedToolInput.scope` in `vscode-extension/src/lmTools.ts`."""
    import mlview_mcp  # noqa: PLC0415

    accepted = scopes.accepted_values()
    assert "pipeline:<entrypoint.py>" in accepted
    doc = mlview_mcp.mlview_graph.__doc__ or ""
    assert '"pipeline:<entry>"' in doc
    # The one thing a model must not get wrong about this kind: a node reached
    # from two entrypoints is context, not this pipeline's own.
    assert "shared" in doc.lower() and "context" in doc


def _core_has_pipeline() -> bool:
    from mlview.api import SCOPE_KINDS

    return "pipeline" in SCOPE_KINDS


PIPELINE_REASON = (
    "the core this server runs (claude-plugin/vendor/mlview) has no `pipeline` "
    "scope kind yet — run tools/sync-core.py"
)


@pytest.mark.skipif(not _core_has_pipeline(), reason=PIPELINE_REASON)
def test_a_pipeline_selector_projects_through_the_server(sample_graph):
    entry = (sample_graph["workspace"].get("entrypoints") or [None])[0]
    assert entry, "the corpus has an entrypoint"
    payload = _graph_payload(sample_graph, fmt="json", scope="pipeline:%s" % entry)
    assert payload["scope"] == "pipeline:%s" % entry
    assert "filtered view" in payload.get("note", "")
    doc = json.loads(payload["content"])
    assert doc, "a pipeline projection that renders nothing is not an answer"


@pytest.mark.skipif(not _core_has_pipeline(), reason=PIPELINE_REASON)
def test_an_unknown_pipeline_names_the_real_entrypoints(sample_graph):
    with pytest.raises(ValueError) as excinfo:
        _graph_payload(sample_graph, scope="pipeline:not-an-entrypoint.py")
    message = str(excinfo.value)
    assert "unknown_pipeline" in message
    assert "not-an-entrypoint.py" in message
    for entry in sample_graph["workspace"].get("entrypoints") or []:
        assert entry in message, "the candidates are the workspace entrypoints"
