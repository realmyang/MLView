"""VIEW-08 in the plugin: ``mlview_graph(scope="diff", base=...)``.

The comparison itself is the analyzer's and is pinned by
``analyzer/tests/core/test_diff.py``.  What is asserted here is the tool boundary:

  1. It is a SCOPE, not a sixth tool -- the server still exposes exactly five.
  2. A base that is not a graph is an ERROR naming the file, never an empty diff.
     "0 changes" is the most dangerous wrong answer this projection can give.
  3. ``notes[]`` reaches the model: section 11.38 C's caveats ride the PROTECTED
     ``note`` key, so the 4 KB budget can shed diff rows and never the sentence that
     says a ``removed`` node may not mean "deleted".
  4. The payload fits the 4 KB budget on the shipped sample pair.
"""

from __future__ import annotations

import inspect
import json
import os

import pytest

from plugin_support import REPO_ROOT

import mlview_diff as diffs
import mlview_mcp
from mlview_budget import LIMIT_BYTES, payload_size
from mlview.core.diff import diff_documents
from mlview.emit.diff_out import render_summary

DIRTY = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
CLEAN = os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean")


def _analyze(path: str):
    from mlview.api import AnalyzeOptions, analyze_to_dict

    return analyze_to_dict(AnalyzeOptions(paths=[path]))


def _payload(head, base, graph_path="/tmp/head.json"):
    return diffs.diff_payload(
        head,
        base,
        diff_documents=diff_documents,
        render_summary=render_summary,
        graph_path=graph_path,
    )


def _identity(path):
    return path


# ------------------------------------------------------------------ 1. not a sixth tool


def test_the_diff_is_a_scope_and_the_server_still_exposes_five_tools():
    source = inspect.getsource(mlview_mcp)
    assert source.count("@server.tool(") == 5, (
        "VIEW-08 must not add a sixth tool: mlview_graph already means 'render this "
        "workflow in a way I can read', and a diff is another projection of it"
    )
    assert "base" in inspect.signature(mlview_mcp.mlview_graph).parameters


def test_the_docstring_documents_the_selector_and_its_base_argument():
    doc = mlview_mcp.mlview_graph.__doc__ or ""
    assert '"diff"' in doc, "the selector must be listed with the rest of the grammar"
    assert "base:" in doc, "an argument a model cannot read about is an argument it will not use"
    assert "REQUIRES `base`" in doc
    # The honesty half: the docstring must tell the model to read `note` before
    # quoting the counts, because a `removed` node has five innocent explanations.
    assert "read the returned `note`" in doc
    assert "not-analyzed" in doc
    assert "rename" in doc


# ------------------------------------------------------------------ 2. a bad base is an error


def test_a_missing_base_is_a_caller_error_that_says_what_to_pass():
    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document(None, _identity)
    assert "base=" in str(excinfo.value)
    with pytest.raises(ValueError):
        diffs.load_base_document("   ", _identity)


def test_a_base_that_is_not_a_graph_is_refused_by_name(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document(str(missing), _identity)
    assert "not a file" in str(excinfo.value)
    assert str(missing) in str(excinfo.value)

    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document(str(garbage), _identity)
    assert "not readable JSON" in str(excinfo.value)

    a_list = tmp_path / "list.json"
    a_list.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        diffs.load_base_document(str(a_list), _identity)

    not_a_graph = tmp_path / "half.json"
    not_a_graph.write_text(json.dumps({"schemaVersion": "1.0"}), encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document(str(not_a_graph), _identity)
    assert "not an MLView graph" in str(excinfo.value)


def test_an_overlay_passed_as_the_base_names_the_mistake(tmp_path):
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps({"kind": "mlview-diff", "diffVersion": "1.0", "schemaVersion": "1.0"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document(str(overlay), _identity)
    message = str(excinfo.value)
    assert "diff overlay, not a graph" in message
    assert "the analyze document" in message


def test_the_base_path_goes_through_the_project_containment_resolver(tmp_path):
    """`resolve` is `mlview_workspace.resolve_path`, so a refusal there is a refusal here."""
    seen = []

    def refusing(path):
        seen.append(path)
        raise ValueError("path is outside the project: %s" % path)

    with pytest.raises(ValueError) as excinfo:
        diffs.load_base_document("../../etc/passwd", refusing)
    assert seen == ["../../etc/passwd"]
    assert "outside the project" in str(excinfo.value)


# ------------------------------------------------------------------ 3 & 4. the payload


@pytest.mark.skipif(
    not (os.path.isdir(DIRTY) and os.path.isdir(CLEAN)),
    reason="the shipped sample pair is not in this tree",
)
def test_the_sample_pair_reports_the_11_38_E_table_and_fits_the_budget(tmp_path):
    base_file = tmp_path / "base.json"
    base_file.write_text(json.dumps(_analyze(DIRTY)), encoding="utf-8")
    head = _analyze(CLEAN)

    out = _payload(head, diffs.load_base_document(str(base_file), _identity))

    assert out["scope"] == "diff"
    assert out["format"] == "text"
    # Section 7 E, exactly: the dirty sample as the base, the clean twin as the
    # head, in whatever mode `AnalyzeOptions` defaults to - which is what the
    # plugin itself does, so this test has to move when the default moves.
    # It did: GRAPH-R3 draws a card for each workspace object at the line it is
    # built or applied, which adds one node to the dirty sample's side of the
    # pair and five to the clean twin's (CONTRACTS 17 E25), and the findings
    # did not move at all - still 15 fixed, 0 new.
    assert out["summary"]["nodes"] == {
        "added": 27, "removed": 16, "changed": 11, "unchanged": 32
    }
    assert out["summary"]["edges"] == {
        "added": 27, "removed": 22, "changed": 1, "unchanged": 28
    }
    assert out["summary"]["issues"] == {"new": 0, "fixed": 15, "persisting": 0}
    assert out["summary"]["headline"] == "+27 nodes · −16 nodes · 0 new findings · 15 fixed"
    assert out["basePath"] == str(base_file)
    assert out["graphPath"] == "/tmp/head.json"
    assert payload_size(out) <= LIMIT_BYTES
    # The prose the model reads is the analyzer's own summary, not a second rendering.
    assert "mlview diff" in out["content"]


@pytest.mark.skipif(
    not (os.path.isdir(DIRTY) and os.path.isdir(CLEAN)),
    reason="the shipped sample pair is not in this tree",
)
def test_the_caveats_reach_the_model_even_when_the_rows_do_not(tmp_path):
    base_file = tmp_path / "base.json"
    base_file.write_text(json.dumps(_analyze(DIRTY)), encoding="utf-8")
    out = _payload(_analyze(CLEAN), diffs.load_base_document(str(base_file), _identity))

    note = out["note"]
    # The pair's real caveat: two sibling directories are not two commits of one tree.
    assert "different-roots" in note
    # ...and the standing one, which no pair can escape.
    assert "rename" in note
    assert "no rename detection" in note
    assert payload_size(out) <= LIMIT_BYTES


def test_a_pair_with_nothing_to_declare_says_so_rather_than_going_silent():
    graph = {
        "schemaVersion": "1.0",
        "generator": {"name": "mlview", "version": "0.1.0"},
        "workspace": {"root": "/repo", "filesAnalyzed": 1},
        "stages": [],
        "nodes": [],
        "edges": [],
        "issues": [],
        "diagnostics": [],
        "stats": {"nodes": 0, "edges": 0, "issues": {}, "truncated": False},
    }
    out = _payload(dict(graph), dict(graph))
    assert "both analyses read their whole workspace" in out["note"]
    assert out["summary"]["issues"] == {"new": 0, "fixed": 0, "persisting": 0}


def test_a_huge_comparison_sheds_rows_and_keeps_the_note(tmp_path):
    """The budget may clip the prose; it may never clip the caveat."""
    from plugin_support import synthetic_graph

    base = synthetic_graph(nodes=300, edges=400, issues=200)
    head = synthetic_graph(nodes=300, edges=400, issues=200)
    head["nodes"] = head["nodes"][:150]
    out = _payload(head, base)
    assert payload_size(out) <= LIMIT_BYTES
    assert "rename" in out["note"], "note is a PROTECTED key and must survive the clip"
    assert out["summary"]["nodes"]["removed"] > 0
