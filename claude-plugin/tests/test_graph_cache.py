"""The on-disk analysis cache must name its producer (CONTRACTS 11.10, 11.15).

`load_graph` memoises an analysis to `<data>/graph*.json` plus a `.sig` sidecar so
a second server process does not re-walk the tree. The sidecar originally recorded
only what was analyzed — path, framework, maxNodes and a mtime/size signature of
the sources — and nothing about *which analyzer* did the analyzing. That is one
half of a cache key pretending to be the whole of one, and it shipped a real
defect: a `.mlview/graph-*.json` written by an earlier build kept being served for
untouched sources while the current analyzer produced six more cross-file edges
for them. §11.10 deliberately applies `project()` to the cached dict, so every one
of those six edges is one a `depth>=1` scope walks — every scoped MCP answer
disagreed with the CLI on the same selector, which is exactly what §11.15's
CLI-vs-MCP parity requirement forbids.

So the tests below are about a sidecar that is *plausible but foreign*: keys that
match, a signature that matches, and an analyzer identity that does not (or is
missing, which is the shape the pre-fix code wrote). The cache must be refused,
and the cheap case — same analyzer, same sources — must still hit, because a cache
that never hits is not a fix.
"""

from __future__ import annotations

import json
import os

import pytest

import mlview_scope as scopes
import mlview_workspace as workspace
from plugin_support import REPO_ROOT, corpus_path


@pytest.fixture()
def workspace_env(tmp_path, monkeypatch):
    """Point the server at the repo with a private, empty data directory."""
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", REPO_ROOT)
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path))
    workspace._CACHE.clear()
    yield tmp_path
    workspace._CACHE.clear()


def _poison(graph_path: str, *, analyzer):
    """Rewrite the cached document as a wrong one and re-stamp its sidecar.

    ``analyzer=None`` drops the field entirely — a sidecar exactly as the pre-fix
    server wrote it; a string forges a different build's identity.
    """
    with open(graph_path, "r", encoding="utf-8") as fh:
        graph = json.load(fh)
    graph["edges"] = (graph.get("edges") or [])[:1]
    graph["nodes"] = (graph.get("nodes") or [])[:1]
    with open(graph_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(graph, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    sidecar = graph_path + ".sig"
    with open(sidecar, "r", encoding="utf-8") as fh:
        stored = json.load(fh)
    if analyzer is None:
        stored.pop("analyzer", None)
    else:
        stored["analyzer"] = analyzer
    with open(sidecar, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(stored, fh)
    return graph


def test_analyzer_identity_is_stable_and_names_the_version():
    first = workspace.analyzer_identity()
    assert first == workspace.analyzer_identity()  # memoised, not re-walked
    from mlview.version import __version__

    assert first.startswith(__version__ + "+")
    assert len(first.split("+", 1)[1]) == 16


def test_sidecar_records_the_analyzer_that_produced_the_document(workspace_env):
    loaded = workspace.load_graph(corpus_path())
    assert loaded["cached"] is False
    with open(loaded["graphPath"] + ".sig", "r", encoding="utf-8") as fh:
        stored = json.load(fh)
    assert stored["analyzer"] == workspace.analyzer_identity()
    assert stored["key"] == [
        workspace.resolve_path(corpus_path()), "auto", 400,
    ]


def test_matching_sidecar_still_hits_the_cache_in_a_fresh_process(workspace_env):
    """The fix must not turn the disk cache off; only make it honest."""
    first = workspace.load_graph(corpus_path())
    workspace._CACHE.clear()  # stand in for a second server process
    second = workspace.load_graph(corpus_path())
    assert second["cached"] is True
    assert second["graph"] == first["graph"]


@pytest.mark.parametrize("forged", [None, "0.0.9+deadbeefdeadbeef"])
def test_cache_from_another_analyzer_is_refused(workspace_env, forged):
    fresh = workspace.load_graph(corpus_path())["graph"]
    graph_path = workspace.graph_file_for(workspace.resolve_path(corpus_path()))
    wrong = _poison(graph_path, analyzer=forged)
    assert len(wrong["edges"]) == 1  # the poison really is on disk

    workspace._CACHE.clear()
    again = workspace.load_graph(corpus_path())
    assert again["cached"] is False, "a foreign sidecar must not satisfy the cache"
    assert again["graph"]["nodes"] == fresh["nodes"]
    assert again["graph"]["edges"] == fresh["edges"]

    # and the stale file is replaced, so the next reader is not poisoned either
    with open(graph_path, "r", encoding="utf-8") as fh:
        assert len(json.load(fh)["edges"]) == len(fresh["edges"])


def test_scoped_projection_survives_a_stale_cache(workspace_env):
    """The defect's own symptom: a scoped answer computed from an old document.

    §11.10 projects the *cached* dict, so a cache miss on the analyzer identity is
    the only thing standing between a stale graph and a wrong scope. Compared
    against a projection of a document analyzed here and now — the same
    comparison `tools/verify.py --parity` makes between the CLI and the server.
    """
    from mlview.api import AnalyzeOptions, analyze_to_dict

    reference = analyze_to_dict(
        AnalyzeOptions(paths=(os.path.join(REPO_ROOT, corpus_path()),))
    )
    workspace.load_graph(corpus_path())
    _poison(
        workspace.graph_file_for(workspace.resolve_path(corpus_path())), analyzer=None
    )
    workspace._CACHE.clear()

    served = workspace.load_graph(corpus_path())["graph"]
    for spec in ("unit:batch_loop", "stage:train", "concern:evaluation"):
        want = scopes.apply_scope(reference, spec, 1)[1]
        got = scopes.apply_scope(served, spec, 1)[1]
        assert [n["id"] for n in got["nodes"]] == [n["id"] for n in want["nodes"]], spec
        assert [e["id"] for e in got["edges"]] == [e["id"] for e in want["edges"]], spec
        assert got["view"] == want["view"], spec
