"""`mlview.api` is FROZEN (CONTRACTS section 3) - both hosts import it.

The MCP server and the VS Code helper come through here rather than shelling
out, so a signature change here silently breaks two components that this
repository cannot compile-check together.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os

import pytest

from mlview import api

FIXTURE_BAD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "rules", "MLV201_bad.py"))


@pytest.fixture(scope="module")
def doc():
    return api.analyze_to_dict(api.AnalyzeOptions(paths=(FIXTURE_BAD,)))


# ------------------------------------------------------------- the surface
def test_the_frozen_names_are_exported():
    for name in ("AnalyzeOptions", "MLGraph", "analyze", "analyze_to_dict",
                 "render_html", "render_mermaid", "render_text", "digest"):
        assert hasattr(api, name), "api.%s is part of the frozen surface" % name


def test_analyze_options_defaults_match_the_contract():
    assert dataclasses.is_dataclass(api.AnalyzeOptions)
    fields = {f.name: f for f in dataclasses.fields(api.AnalyzeOptions)}
    # CONTRACTS 11.6: `scope` and `depth` are APPENDED LAST, both defaulted, so
    # positional construction, `frozen=True` and hashability are unchanged.
    # H3 appends `progress` under the same rule: a defaulted `None` sink, so
    # `analyze()` still performs no I/O of its own unless a caller asks.
    # CONTRACTS 11.28: `relevance`, `relevance_hops` and `cache` append under
    # the same rule again - all defaulted, all at the end, and all three
    # defaulting to today's behaviour (`all` is the identity prefilter mode and
    # `cache=None` means "ask the environment").
    # CONTRACTS 11.29 (NB) appends `include_notebooks` under the same rule: a
    # defaulted False, so a run that does not name it discovers, parses and
    # emits exactly what it always did - `.ipynb` counted and skipped.
    # CONTRACTS 11.36 (DATAFLOW-IP) appends `dataflow` under the same rule, and
    # R1 flips which side it defaults to: `ip`, read from
    # `ir.build_ir.DEFAULT_DATAFLOW` rather than spelled here, so the constant
    # stays the one authority. `local` remains a supported, gated mode - the
    # opt-out, not a deprecation - and the shipped sample is byte-identical
    # under both, so `analyze --demo` is untouched.
    assert list(fields) == ["paths", "include", "exclude", "max_files", "max_nodes",
                            "framework", "min_severity", "min_confidence",
                            "config_path", "strict", "scope", "depth", "progress",
                            "relevance", "relevance_hops", "cache",
                            "include_notebooks", "dataflow"]
    from mlview.api import DEFAULT_DATAFLOW

    assert fields["dataflow"].default == DEFAULT_DATAFLOW == "ip"
    assert fields["paths"].default is dataclasses.MISSING, "paths is required"
    assert fields["include"].default == ()
    assert fields["exclude"].default == ()
    assert fields["max_files"].default == 500
    assert fields["max_nodes"].default == 400
    assert fields["framework"].default == "auto"
    assert fields["min_severity"].default == "low"
    assert fields["min_confidence"].default == 0.0
    assert fields["config_path"].default is None
    assert fields["strict"].default is False
    assert fields["scope"].default is None
    assert fields["depth"].default is None
    assert fields["progress"].default is None
    # CONTRACTS 11.39: the relevance default flipped to `ml` in Sprint 5. It is
    # the one default on this list that has ever moved, and it moved as a
    # re-baseline - byte-identical on all three perf corpora and on the whole
    # accuracy corpus - not as an optimisation.
    assert fields["relevance"].default == "ml"
    assert fields["relevance_hops"].default == 2
    assert fields["cache"].default is None
    assert fields["include_notebooks"].default is False


def test_analyze_options_is_frozen_and_hashable():
    options = api.AnalyzeOptions(paths=(".",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.max_nodes = 1          # type: ignore[misc]
    assert hash(options) == hash(api.AnalyzeOptions(paths=(".",)))


def test_render_signatures():
    # CONTRACTS 11.6: two defaulted parameters, appended last.
    assert list(inspect.signature(api.render_html).parameters) == [
        "graph", "out_path", "scope", "depth"]
    assert inspect.signature(api.render_html).parameters["scope"].default is None
    assert inspect.signature(api.render_html).parameters["depth"].default is None
    assert list(inspect.signature(api.render_mermaid).parameters) == ["graph"]
    assert list(inspect.signature(api.render_text).parameters) == ["graph"]
    # CONTRACTS 11.28 appends `cached`, defaulted to None: the frozen
    # two-argument call returns exactly what it always returned.
    assert list(inspect.signature(api.digest).parameters) == ["graph", "limit_bytes",
                                                              "cached"]
    assert inspect.signature(api.digest).parameters["limit_bytes"].default == 4096
    assert inspect.signature(api.digest).parameters["cached"].default is None


# ----------------------------------------------------------------- analyze
def test_analyze_returns_a_graph_object_and_a_dict(doc):
    graph = api.analyze(api.AnalyzeOptions(paths=(FIXTURE_BAD,)))
    assert graph.to_dict()["nodes"] == doc["nodes"]
    assert doc["schemaVersion"] == "1.0"
    assert doc["generator"]["name"] == "mlview"
    assert doc["generator"]["version"] == api.__version__


def test_render_html_returns_the_absolute_path_written(doc, tmp_path):
    written = api.render_html(doc, str(tmp_path / "sub" / "r.html"))
    assert os.path.isabs(written)
    assert "/" in written and "\\" not in written, "forward slashes, per section 0"
    assert os.path.isfile(written)


def test_render_text_and_mermaid_are_strings(doc):
    assert api.render_mermaid(doc).startswith("flowchart LR")
    assert "MLView" in api.render_text(doc)
    assert "MLView" in api.render_summary(doc)


# ------------------------------------------------------------------ digest
def test_digest_shape_matches_the_mcp_contract(doc):
    small = api.digest(doc)
    assert set(small) >= {"schemaVersion", "root", "filesAnalyzed", "filesFailed",
                          "notebooksSkipped", "frameworks", "stats", "lanes",
                          "topIssues", "truncated"}
    assert set(small["stats"]) == {"nodes", "edges", "issues"}
    assert set(small["stats"]["issues"]) == {"low", "medium", "high"}
    assert all(set(lane) == {"stage", "label", "nodeCount", "maxSeverity"}
               for lane in small["lanes"])
    assert all(set(issue) == {"code", "severity", "confidenceBucket", "title",
                              "file", "line"} for issue in small["topIssues"])
    assert small["topIssues"][0]["code"] == "MLV201"


def test_digest_is_at_most_4kb(doc):
    assert len(json.dumps(api.digest(doc), ensure_ascii=False).encode("utf-8")) <= 4096


def test_digest_sheds_detail_rather_than_overflowing(doc):
    """The budget is a hard cap: a huge graph drops rows, it does not bust it."""
    fat = json.loads(json.dumps(doc))
    fat["issues"] = []
    for index in range(200):
        issue = json.loads(json.dumps(doc["issues"][0]))
        issue["title"] = "a very long synthetic finding title #%03d %s" % (index, "x" * 40)
        fat["issues"].append(issue)
    small = api.digest(fat)
    assert len(json.dumps(small, ensure_ascii=False).encode("utf-8")) <= 4096
    assert len(small["topIssues"]) <= 10
    for budget in (2048, 1024, 512):
        tight = api.digest(fat, limit_bytes=budget)
        assert len(json.dumps(tight, ensure_ascii=False).encode("utf-8")) <= budget


def test_digest_never_reports_suppressed_findings(make_workspace):
    root = make_workspace({"t.py": (
        "import torch\nimport torch.nn as nn\nimport torch.optim as optim\n"
        "from torch.utils.data import DataLoader\n\n\n"
        "def train(ds):\n"
        "    model = nn.Linear(4, 2)\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = optim.Adam(model.parameters())\n"
        "    loader = DataLoader(ds, batch_size=8)\n"
        "    for x, y in loader:  # mlview: ignore[MLV201]\n"
        "        loss = crit(model(x), y)\n"
        "        loss.backward()\n"
        "        opt.step()\n")})
    document = api.analyze_to_dict(api.AnalyzeOptions(paths=(root,)))
    assert any(i["suppressed"] for i in document["issues"])
    assert all(i["code"] != "MLV201" for i in api.digest(document)["topIssues"])


# ------------------------------------------------------------- schema/demo
def test_schema_and_sample_are_readable_from_the_package():
    assert api.schema_path().endswith("mlview/schema/graph.schema.json")
    assert api.sample_path().endswith("mlview/schema/graph.sample.json")
    assert json.loads(api.schema_text())["title"] == "MLGraph"
    assert api.demo_dict()["schemaVersion"] == "1.0"
    assert api.demo_bytes().startswith(b"{")


def test_analyze_full_exposes_the_ir_for_rules_and_explain():
    result = api.analyze_full(api.AnalyzeOptions(paths=(FIXTURE_BAD,)))
    assert result.workspace is not None
    assert result.builder is not None
    assert result.context is not None
    assert result.empty is False
    assert "MLV201_bad.py" in result.workspace.modules


# -------------------------------------------------- scoped views (CONTRACTS 11.6)
def test_the_scope_surface_is_exported():
    for name in ("CONCERNS", "CONCERN_ALIASES", "SCOPE_KINDS", "Scope", "ScopeError",
                 "ScopeResolution", "parse_scope", "resolve_scope", "project",
                 "scope_catalog"):
        assert hasattr(api, name), "api.%s is part of the scoped-view surface" % name
        assert name in api.__all__


def test_analyze_returns_the_full_graph_even_with_a_scope():
    """A scope is a document-level projection, never a smaller analysis."""
    options = api.AnalyzeOptions(paths=(FIXTURE_BAD,), scope="stage:train")
    full = api.analyze(options).to_dict()
    assert "view" not in full
    projected = api.analyze_to_dict(options)
    assert projected["view"]["scope"] == "stage:train"
    assert len(projected["nodes"]) <= len(full["nodes"])
    assert projected["workspace"] == full["workspace"]


def test_analyze_to_dict_is_unchanged_without_a_scope(doc):
    assert "view" not in doc


def test_scope_catalog_rows_carry_what_list_scopes_and_mcp_need():
    graph = api.analyze_to_dict(api.AnalyzeOptions(paths=(FIXTURE_BAD,)))
    rows = api.scope_catalog(graph)
    assert rows, "the fixture has at least one scopable unit"
    for row in rows:
        assert set(row) == {"spec", "kind", "nodeId", "label", "qualname", "file",
                            "line", "nodeCount", "issueCounts", "maxSeverity"}
        assert row["spec"].startswith("unit:")
    keys = [(-r["nodeCount"], r["file"], r["line"], r["qualname"]) for r in rows]
    assert keys == sorted(keys)
    assert len(api.scope_catalog(graph, limit=1)) == 1


def test_digest_gains_a_scope_block_only_when_the_graph_is_projected():
    graph = api.analyze_to_dict(api.AnalyzeOptions(paths=(FIXTURE_BAD,)))
    assert "scope" not in api.digest(graph)
    scoped = api.project(graph, api.parse_scope("stage:train", 1))
    block = api.digest(scoped)["scope"]
    assert block == {"spec": "stage:train", "kind": "stage", "target": "train",
                     "depth": 1, "nodesInScope": scoped["stats"]["nodes"],
                     "nodesTotal": len(graph["nodes"])}
    assert len(json.dumps(api.digest(scoped)).encode("utf-8")) <= 4096
