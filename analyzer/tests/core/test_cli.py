"""The CLI contract (CONTRACTS section 3): exit codes, flags, `--json -`.

Both hosts call exactly this, so every promise here is load-bearing:
`0` graph produced · `1` usage/IO · `2` `--fail-on` exceeded · `3` internal ·
`4` nothing analyzable.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import SAMPLE_PATH, write_files
from mlview import cli

FIXTURE_BAD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "rules", "MLV201_bad.py"))
FIXTURE_GOOD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "rules", "MLV201_good.py"))

TINY = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "def train(ds):\n"
                 "    model = nn.Linear(4, 2)\n"
                 "    crit = nn.CrossEntropyLoss()\n"
                 "    opt = optim.Adam(model.parameters())\n"
                 "    loader = DataLoader(ds, batch_size=8)\n"
                 "    for x, y in loader:\n"
                 "        opt.zero_grad()\n"
                 "        loss = crit(model(x), y)\n"
                 "        loss.backward()\n"
                 "        opt.step()\n"),
}


@pytest.fixture
def run(capsysbinary):
    """Invoke `cli.main(argv)` and return `(code, stdout_bytes, stderr_text)`."""

    def _run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out, captured.err.decode("utf-8", "replace")

    return _run


@pytest.fixture
def workspace(make_workspace):
    return make_workspace(TINY)


# ------------------------------------------------------------------ exit codes
def test_exit_0_when_a_graph_is_produced(run, workspace):
    code, out, _err = run("analyze", workspace)
    assert code == 0
    assert b"MLView" in out


def test_exit_1_on_an_unknown_flag(run, workspace):
    code, out, _err = run("analyze", workspace, "--nonsense")
    assert code == 1, "argparse's own status 2 is reserved for --fail-on"
    assert out == b""


def test_exit_1_with_no_subcommand(run):
    assert run()[0] == 1


def test_exit_0_on_help(run):
    assert run("--help")[0] == 0


def test_exit_1_when_a_graph_file_cannot_be_read(run, tmp_path):
    code, out, err = run("render", "--graph", str(tmp_path / "missing.json"))
    assert code == 1
    assert out == b""
    assert "cannot read" in err


def test_exit_1_on_a_graph_file_that_is_not_json(run, tmp_path):
    junk = tmp_path / "junk.json"
    junk.write_text("not json at all", encoding="utf-8")
    code, _out, err = run("render", "--graph", str(junk))
    assert code == 1
    assert "not valid JSON" in err


def test_exit_2_when_fail_on_is_exceeded(run):
    assert run("analyze", FIXTURE_BAD, "--fail-on", "high")[0] == 2
    assert run("analyze", FIXTURE_BAD, "--fail-on", "low")[0] == 2
    assert run("analyze", FIXTURE_GOOD, "--fail-on", "high")[0] == 0
    assert run("analyze", FIXTURE_BAD, "--fail-on", "none")[0] == 0


def test_exit_3_on_an_internal_error_and_the_error_object_goes_to_stdout(run, monkeypatch):
    def boom(_args):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli._COMMANDS, "analyze", boom)
    code, out, err = run("analyze", ".")
    assert code == 3
    payload = json.loads(out.decode("utf-8"))
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "kaboom"
    assert "Traceback" in err, "the traceback belongs on stderr"


def test_exit_4_when_nothing_is_analyzable(run, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    code, out, err = run("analyze", str(empty))
    assert code == 4
    assert b"MLView" in out, "a valid (empty) document is still produced"
    assert "no analyzable Python files" in err


def test_exit_4_for_a_directory_of_non_python_files(run, tmp_path):
    root = tmp_path / "docsonly"
    root.mkdir()
    write_files(str(root), {"README.md": "# hi\n", "data.csv": "a,b\n1,2\n"})
    assert run("analyze", str(root))[0] == 4


def test_exit_1_and_silent_stdout_for_a_path_that_does_not_exist(run, tmp_path):
    """HOSTS-UX-MISSINGPATH (CONTRACTS 11.51).

    Section 3 reserves exit 1 for "usage or I/O error" and exit 4 for "nothing
    analyzable found (no `.py` files after filtering)". A path that is not
    there is the first, not the second - and the old shared branch printed a
    full, clean-looking summary on stdout about a directory that does not
    exist.
    """
    code, out, err = run("analyze", str(tmp_path / "nowhere"))
    assert code == 1
    assert out == b""
    assert "no such path" in err


def test_exit_4_for_a_directory_that_holds_no_python(run, tmp_path):
    """A path that exists and holds nothing analyzable really is a result."""
    empty = tmp_path / "empty"
    empty.mkdir()
    code, _out, err = run("analyze", str(empty))
    assert code == 4
    assert "no analyzable Python files found" in err


# ----------------------------------------------------------------- --json -
def test_json_dash_writes_only_the_document(run, workspace):
    code, out, err = run("analyze", workspace, "--json", "-")
    assert code == 0
    doc = json.loads(out.decode("utf-8"))
    assert doc["schemaVersion"] == "1.0"
    assert out.endswith(b"\n")
    assert "wrote" not in err


def test_json_to_a_file_leaves_stdout_for_the_summary(run, workspace, tmp_path):
    target = tmp_path / "out" / "graph.json"
    code, out, err = run("analyze", workspace, "--json", str(target))
    assert code == 0
    assert target.is_file(), "the parent directory is created"
    assert json.loads(target.read_text(encoding="utf-8"))["nodes"]
    assert b"MLView" in out, "the summary still goes to stdout"
    assert "wrote" in err


def test_demo_writes_the_golden_sample_byte_for_byte(run):
    code, out, _err = run("analyze", "--demo", "--json", "-")
    assert code == 0
    with open(SAMPLE_PATH, "rb") as fh:
        assert out == fh.read()


def test_schema_subcommand_is_the_shipped_schema(run):
    code, out, _err = run("schema")
    assert code == 0
    assert json.loads(out.decode("utf-8"))["$id"].endswith("mlgraph-1.0.json")


def test_version_plain_and_json(run):
    code, out, _err = run("--version")
    assert code == 0 and out.startswith(b"mlview 0.1.0")
    code, out, _err = run("--version", "--json")
    assert json.loads(out.decode("utf-8"))["version"] == "0.1.0"


# -------------------------------------------------------------------- formats
@pytest.mark.parametrize("fmt,needle", [
    ("summary", b"Stages"),
    ("json", b'"schemaVersion"'),
    ("mermaid", b"flowchart LR"),
    ("text", b"Nodes"),
])
def test_every_format_reaches_stdout(run, workspace, fmt, needle):
    code, out, _err = run("analyze", workspace, "--format", fmt)
    assert code == 0
    assert needle in out


def test_html_report_is_written_and_announced_on_stderr(run, workspace, tmp_path):
    target = tmp_path / "nested" / "report.html"
    code, out, err = run("analyze", workspace, "--html", str(target))
    assert code == 0
    assert target.is_file()
    assert str(target).replace("\\", "/") in err
    assert b"<!DOCTYPE html>" not in out, "the report never lands on stdout"


# -------------------------------------------------------------------- filters
def test_min_severity_and_min_confidence_filter_the_document(run):
    code, out, _err = run("analyze", FIXTURE_BAD, "--json", "-", "--min-severity", "high")
    assert [i["code"] for i in json.loads(out)["issues"]] == ["MLV201"]
    code, out, _err = run("analyze", FIXTURE_BAD, "--json", "-", "--min-confidence", "0.99")
    assert json.loads(out)["issues"] == []
    assert json.loads(out)["stats"]["issues"] == {"low": 0, "medium": 0, "high": 0}


def test_filtering_out_an_issue_removes_its_ghost_node(run):
    """Invariant 1.1.8 survives `--min-confidence` (a ghost always carries an issue)."""
    code, out, _err = run("analyze", FIXTURE_BAD, "--json", "-", "--min-confidence", "0.99")
    doc = json.loads(out)
    assert [n for n in doc["nodes"] if n["ghost"]] == []
    ids = {n["id"] for n in doc["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in doc["edges"])


def test_max_nodes_sets_truncated_and_a_diagnostic(run, make_workspace):
    root = make_workspace({"big.py": "import torch.nn as nn\n" + "".join(
        "layer%d = nn.Linear(%d, 4)\n" % (i, i + 1) for i in range(40))})
    code, out, _err = run("analyze", root, "--json", "-")
    assert len(json.loads(out)["nodes"]) > 10, "the uncapped graph is bigger than the cap"
    code, out, _err = run("analyze", root, "--json", "-", "--max-nodes", "10")
    doc = json.loads(out)
    assert doc["stats"]["truncated"] is True
    assert len(doc["nodes"]) <= 10
    assert any(n["level"] == "unit" for n in doc["nodes"]), "units survive the cap"
    assert any(d["kind"] == "truncated" for d in doc["diagnostics"])


def test_max_files_caps_discovery(run, make_workspace):
    root = make_workspace({"m%d.py" % i: "import torch\n" for i in range(9)})
    code, out, _err = run("analyze", root, "--json", "-", "--max-files", "3")
    doc = json.loads(out)
    assert doc["workspace"]["filesAnalyzed"] == 3
    assert any(d["kind"] == "truncated" for d in doc["diagnostics"])


def test_include_and_exclude_globs(run, make_workspace):
    root = make_workspace({"keep/a.py": "import torch\n", "drop/b.py": "import torch\n"})
    code, out, _err = run("analyze", root, "--json", "-", "--include", "keep/**")
    assert json.loads(out)["workspace"]["filesAnalyzed"] == 1
    code, out, _err = run("analyze", root, "--json", "-", "--exclude", "drop/**")
    assert json.loads(out)["workspace"]["filesAnalyzed"] == 1
    code, out, _err = run("analyze", root, "--json", "-")
    assert json.loads(out)["workspace"]["filesAnalyzed"] == 2


# -------------------------------------------------------------- issues/explain
def test_issues_json_shape(run):
    code, out, _err = run("issues", FIXTURE_BAD, "--json")
    payload = json.loads(out.decode("utf-8"))
    # HOST-4: `diagnostics` is the same list `analyze --format json` carries.
    assert set(payload) == {"countBySeverity", "suppressedCount", "issues",
                            "diagnostics"}
    assert payload["countBySeverity"]["high"] == 1
    assert payload["issues"][0]["code"] == "MLV201"


def test_issues_code_filter_and_limit(run):
    code, out, _err = run("issues", FIXTURE_BAD, "--json", "--code", "MLV999")
    assert json.loads(out)["issues"] == []
    code, out, _err = run("issues", FIXTURE_BAD, "--json", "--code", "mlv201")
    assert len(json.loads(out)["issues"]) == 1
    code, out, _err = run("issues", FIXTURE_BAD, "--json", "--limit", "0")
    assert len(json.loads(out)["issues"]) == 1


def test_explain_a_rule_code_without_a_graph(run):
    code, out, _err = run("explain", "MLV201", "--json")
    payload = json.loads(out.decode("utf-8"))
    assert payload["code"] == "MLV201"
    assert payload["docs"] == "docs/rules/MLV201.md"
    assert payload["absence"] is True


def test_explain_an_unknown_rule_is_a_usage_error(run):
    assert run("explain", "MLV999")[0] == 1


def test_explain_a_node_needs_a_graph(run, tmp_path, workspace):
    assert run("explain", "n:000000000000")[0] == 1
    graph = tmp_path / "g.json"
    run("analyze", workspace, "--json", str(graph))
    doc = json.loads(graph.read_text(encoding="utf-8"))
    node = doc["nodes"][0]
    code, out, _err = run("explain", node["id"], "--graph", str(graph), "--json")
    assert code == 0
    assert json.loads(out.decode("utf-8"))["node"]["id"] == node["id"]
    assert run("explain", "n:ffffffffffff", "--graph", str(graph))[0] == 1


def test_rules_listing(run):
    code, out, _err = run("rules", "--json")
    specs = json.loads(out.decode("utf-8"))
    codes = [s["code"] for s in specs]
    assert codes == sorted(codes), "rules are ordered by code"
    assert {"MLV101", "MLV201", "MLV401", "MLV601"} <= set(codes)
    code, out, _err = run("rules", "--list")
    assert b"rule(s) registered" in out


def test_render_subcommand_from_a_saved_graph(run, tmp_path, workspace):
    graph = tmp_path / "g.json"
    run("analyze", workspace, "--json", str(graph))
    code, out, _err = run("render", "--graph", str(graph), "--format", "mermaid")
    assert code == 0 and out.startswith(b"flowchart LR")
    out_file = tmp_path / "r.html"
    code, _out, err = run("render", "--graph", str(graph), "--out", str(out_file))
    assert code == 0 and out_file.is_file()
    assert str(out_file).replace("\\", "/") in err


# ----------------------------------------------- scoped views (CONTRACTS 11.5)
SAMPLE_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "samples", "vision_pipeline"))


def test_a_valid_non_empty_scope_exits_0_and_prints_one_extra_line(run, workspace):
    code, out, _err = run("analyze", workspace, "--scope", "stage:train")
    plain = run("analyze", workspace)[1]
    assert code == 0
    text = out.decode("utf-8")
    scope_lines = [l for l in text.splitlines() if l.startswith("scope: ")]
    assert len(scope_lines) == 1, "exactly one line, and only when scoped"
    assert "depth 0" in scope_lines[0] and " of " in scope_lines[0]
    assert not any(l.startswith("scope: ") for l in plain.decode("utf-8").splitlines())


def test_the_json_payload_is_the_projection(run, workspace):
    code, out, _err = run("analyze", workspace, "--scope", "unit:train", "--json", "-")
    assert code == 0
    doc = json.loads(out.decode("utf-8"))
    assert doc["view"]["scope"] == "unit:train"
    assert doc["view"]["depth"] == 1, "the per-kind default"
    assert list(doc.keys())[-1] == "view"


def test_depth_overrides_the_per_kind_default(run, workspace):
    _code, out, _err = run("analyze", workspace, "--scope", "unit:train",
                           "--depth", "0", "--json", "-")
    assert json.loads(out.decode("utf-8"))["view"]["depth"] == 0


def test_an_empty_scope_exits_0_with_a_valid_document_and_a_stderr_note(run, workspace):
    code, out, err = run("analyze", workspace, "--scope", "unit:Nope", "--json", "-")
    assert code == 0
    doc = json.loads(out.decode("utf-8"))
    assert doc["view"]["empty"] is True and doc["nodes"] == []
    assert len(doc["stages"]) == 8
    assert any(d["kind"] == "config_warning" for d in doc["diagnostics"])
    assert "matched no nodes" in err and "unit:Nope" in err


@pytest.mark.parametrize("argv,code,term", [
    (("--scope", "bogus:x"), "bad_selector", "bogus"),
    (("--scope", "train"), "bad_selector", "train"),
    (("--scope", "stage:nope"), "unknown_stage", "nope"),
    (("--scope", "concern:nope"), "unknown_concern", "nope"),
    (("--scope", "node:n:deadbeefdead"), "unknown_node", "n:deadbeefdead"),
    (("--scope", "file:nope.py"), "unknown_file", "nope.py"),
    (("--scope", "stage:train", "--depth", "3"), "bad_depth", "3"),
    (("--scope", "stage:train", "--depth", "-1"), "bad_depth", "-1"),
])
def test_an_invalid_selector_exits_1_with_a_clean_stdout(run, workspace, argv, code, term):
    """CONTRACTS 11.5: the code, the offending term and <=10 sorted candidates
    on stderr; stdout untouched."""
    status, out, err = run("analyze", workspace, "--json", "-", *argv)
    assert status == 1
    assert out == b"", "stdout carries only the requested payload"
    assert code in err and term in err


def test_an_invalid_selector_is_rejected_on_issues_and_render_too(run, workspace, tmp_path):
    assert run("issues", workspace, "--scope", "stage:nope")[0] == 1
    assert run("render", workspace, "--scope", "stage:nope",
               "--out", str(tmp_path / "r.html"))[0] == 1


def test_scope_with_demo_is_rejected(run):
    code, out, err = run("analyze", "--demo", "--scope", "stage:train", "--json", "-")
    assert code == 1
    assert out == b""
    assert "bad_selector" in err


def test_fail_on_names_the_active_scope(run):
    code, _out, err = run("analyze", FIXTURE_BAD, "--scope", "stage:train",
                          "--fail-on", "high")
    assert code == 2
    assert "--fail-on high threshold exceeded" in err
    assert "scope: stage:train" in err
    plain = run("analyze", FIXTURE_BAD, "--fail-on", "high")[2]
    assert "mlview: --fail-on high threshold exceeded\n" in plain, "unscoped is unchanged"


def test_a_scope_that_excludes_every_finding_clears_the_fail_on_gate(run):
    code, _out, _err = run("analyze", FIXTURE_BAD, "--scope", "concern:data",
                           "--fail-on", "high")
    assert code == 0


def test_list_scopes_prints_the_catalogue_and_exits_0(run, workspace):
    code, out, _err = run("analyze", workspace, "--list-scopes")
    assert code == 0
    text = out.decode("utf-8")
    assert "scopable unit(s)" in text and "unit:" in text


def test_list_scopes_as_json(run, workspace):
    code, out, _err = run("analyze", workspace, "--list-scopes", "--format", "json")
    assert code == 0
    rows = json.loads(out.decode("utf-8"))
    assert rows and all(r["spec"].startswith("unit:") for r in rows)


@pytest.mark.parametrize("extra", [("--json", "-"), ("--scope", "stage:train")])
def test_list_scopes_is_mutually_exclusive(run, workspace, extra):
    code, out, err = run("analyze", workspace, "--list-scopes", *extra)
    assert code == 1 and out == b"" and "list-scopes" in err


def test_mermaid_gains_exactly_one_leading_comment(run, workspace):
    _code, out, _err = run("analyze", workspace, "--scope", "stage:train",
                           "--format", "mermaid")
    lines = out.decode("utf-8").splitlines()
    assert lines[0].startswith("%% scope: stage:train")
    assert lines[1] == "flowchart LR"
    assert len([l for l in lines if l.startswith("%% scope:")]) == 1
    plain = run("analyze", workspace, "--format", "mermaid")[1].decode("utf-8")
    assert not plain.startswith("%% scope:")


def test_the_html_report_embeds_the_full_graph_and_the_two_attributes(run, workspace, tmp_path):
    target = tmp_path / "report.html"
    code, _out, _err = run("analyze", workspace, "--scope", "unit:train",
                           "--depth", "2", "--html", str(target))
    assert code == 0
    text = target.read_text(encoding="utf-8")
    assert 'data-mlview-scope="unit:train"' in text
    assert 'data-mlview-depth="2"' in text
    embedded = text.split('type="application/json">')[1].split("</script")[0]
    doc = json.loads(embedded.replace("<\\/", "</"))
    assert "view" not in doc, "the report embeds the FULL graph; the viewer projects"
    plain_target = tmp_path / "plain.html"
    run("analyze", workspace, "--html", str(plain_target))
    plain_text = plain_target.read_text(encoding="utf-8")
    # The synced viewer bundle names both attributes (it READS them off the root),
    # so the absence is asserted on the root element itself, not on the whole file.
    root_tag = plain_text.split('<div id="mlview-root"')[1].split(">")[0]
    assert "data-mlview-scope" not in root_tag
    assert "data-mlview-depth" not in root_tag


def test_render_projects_an_already_written_document(run, workspace, tmp_path):
    graph = tmp_path / "graph.json"
    run("analyze", workspace, "--json", str(graph))
    code, out, _err = run("render", "--graph", str(graph), "--scope", "stage:train",
                          "--format", "text")
    assert code == 0
    assert "scope: stage:train" in out.decode("utf-8")


def test_issues_lists_only_the_retained_findings(run):
    _code, scoped, _err = run("issues", SAMPLE_DIR, "--scope", "unit:SmallCNN",
                              "--json")
    _code, plain, _err = run("issues", SAMPLE_DIR, "--json")
    scoped_payload = json.loads(scoped.decode("utf-8"))
    plain_payload = json.loads(plain.decode("utf-8"))
    assert scoped_payload["scope"] == "unit:SmallCNN"
    assert "scope" not in plain_payload
    codes = {i["code"] for i in scoped_payload["issues"]}
    assert codes == {"MLV401", "MLV702"}
    assert len(scoped_payload["issues"]) < len(plain_payload["issues"])


def test_an_unscoped_run_is_byte_identical_to_the_pre_change_snapshot(run, workspace):
    """F2-A13. `--scope all` performs no projection, so it must produce the
    same bytes as no flag at all."""
    first = run("analyze", workspace, "--json", "-")[1]
    second = run("analyze", workspace, "--scope", "all", "--json", "-")[1]
    strip = lambda raw: _without_volatile(json.loads(raw.decode("utf-8")))
    assert strip(first) == strip(second)
    assert "view" not in json.loads(second.decode("utf-8"))


def _without_volatile(doc):
    doc["generator"].pop("generatedAt", None)
    doc["stats"].pop("durationMs", None)
    return doc


def test_text_format_carries_the_same_single_scope_line(run, workspace):
    _code, out, _err = run("analyze", workspace, "--scope", "stage:train",
                           "--format", "text")
    lines = out.decode("utf-8").splitlines()
    assert len([l for l in lines if l.startswith("scope: ")]) == 1


def test_the_fallback_report_still_declares_the_scope(monkeypatch, tmp_path):
    """With no viewer bundle there is nothing to project with, but the scope
    must still be readable from the file (CONTRACTS 11.8)."""
    from mlview.emit import html_out

    monkeypatch.setattr(html_out, "_JS", str(tmp_path / "missing.js"))
    with open(SAMPLE_PATH, encoding="utf-8-sig") as fh:
        doc = json.load(fh)
    plain = html_out.render_html(doc)
    scoped = html_out.render_html(doc, scope="concern:evaluation", depth=1)
    assert "data-mlview-scope" not in plain
    assert 'data-mlview-scope="concern:evaluation"' in scoped
    assert 'data-mlview-depth="1"' in scoped
    assert "viewer bundle not synced" in scoped.lower()


# ------------------------------------------------- re-projecting a projection
# Regression: MLV-R1-F2-02 / MLV-R3-006. `render --graph FILE --scope B` used to
# project whatever it was handed, so scoping an already-projected file rebuilt
# `view.of` from the projection: the payload claimed the project had 10 nodes
# when the analysis found 45, which is precisely what the `View` contract
# forbids ("no surface can claim the project is smaller than it is",
# CONTRACTS 11.3). It is now refused, like `--scope` with `--demo`.
def test_rescoping_an_already_projected_document_is_refused(run, workspace, tmp_path):
    graph = tmp_path / "scoped.json"
    run("analyze", workspace, "--scope", "stage:train", "--json", str(graph))
    saved = json.loads(graph.read_text(encoding="utf-8"))
    assert "view" in saved, "the fixture for this test must be a projection"

    code, out, err = run("render", "--graph", str(graph), "--scope", "stage:train",
                         "--format", "text")
    assert code == 1
    assert out == b"", "stdout carries only the requested payload"
    assert "bad_selector" in err and "already a projection" in err


def test_rescoping_a_projection_is_refused_for_every_format(run, workspace, tmp_path):
    graph = tmp_path / "scoped.json"
    run("analyze", workspace, "--scope", "stage:train", "--json", str(graph))
    for extra in (("--format", "mermaid"), ("--format", "text"),
                  ("--out", str(tmp_path / "r.html"))):
        code, out, _err = run("render", "--graph", str(graph),
                              "--scope", "concern:evaluation", *extra)
        assert code == 1 and out == b""
    assert not (tmp_path / "r.html").exists(), "no payload is written either"


def test_rendering_a_projection_without_a_scope_still_works(run, workspace, tmp_path):
    """The refusal is about *re*-projecting, not about projections: the
    documented two-step flow (analyze --scope --json, then render it) stays
    legal, and so does the identity scope `all`."""
    graph = tmp_path / "scoped.json"
    run("analyze", workspace, "--scope", "stage:train", "--json", str(graph))
    code, out, _err = run("render", "--graph", str(graph), "--format", "text")
    assert code == 0 and b"scope: stage:train" in out
    code, out, _err = run("render", "--graph", str(graph), "--scope", "all",
                          "--format", "text")
    assert code == 0 and b"scope: stage:train" in out, "`all` projects nothing"


def test_an_unprojected_saved_document_reports_project_level_totals(run, workspace,
                                                                    tmp_path):
    """The surviving `render --graph --scope` path keeps `view.of` honest: it
    is the size of the document on disk, which is the whole workspace."""
    graph = tmp_path / "full.json"
    run("analyze", workspace, "--json", str(graph))
    full = json.loads(graph.read_text(encoding="utf-8"))
    code, out, _err = run("render", "--graph", str(graph), "--scope", "stage:train",
                          "--format", "text")
    assert code == 0
    assert ("of %d nodes" % len(full["nodes"])) in out.decode("utf-8")


def test_the_catalogue_count_column_is_named_for_what_it_counts(run, workspace):
    """Regression: MLV-R1-F2-05. The count beside a row is the unit's subtree
    at depth 0, but a `unit:` scope is activated at depth 1, so a `NODES`
    header read as "cards you will get" was wrong by up to 12x on a leaf unit.
    The column is `SUBTREE` and the footer says what it means."""
    code, out, _err = run("analyze", workspace, "--list-scopes")
    text = out.decode("utf-8")
    assert code == 0
    assert "SUBTREE" in text and "NODES" not in text
    assert "--depth 0" in text and "--depth 1" in text


def test_the_catalogue_count_still_matches_a_depth_0_projection(run, workspace,
                                                                tmp_path):
    """...and the number itself is unchanged: it is exactly what
    `--scope <spec> --depth 0` draws, on both ports (CONTRACTS 11.16)."""
    code, out, _err = run("analyze", workspace, "--list-scopes", "--format", "json")
    rows = json.loads(out.decode("utf-8"))
    assert code == 0 and rows
    row = rows[0]
    graph = tmp_path / "scoped.json"
    run("analyze", workspace, "--scope", row["spec"], "--depth", "0",
        "--json", str(graph))
    doc = json.loads(graph.read_text(encoding="utf-8"))
    assert doc["view"]["counts"]["core"] == row["nodeCount"]


def test_the_catalogue_says_a_call_site_resolves_but_is_never_listed(run, workspace):
    """R2-F2-05. `scope_catalog` keeps only units and their parents, so an
    op-level call site - `unit:train_test_split`, the scope README.md and the
    demo scripts lead with - resolves but is never a row. The MCP docstring and
    the plugin README disclose that; the human-facing catalogue must too, or
    its ten rows read as the whole vocabulary."""
    code, out, _err = run("analyze", workspace, "--list-scopes")
    text = out.decode("utf-8")
    assert code == 0
    assert "unit:train_test_split" in text and "never listed" in text
    assert "SUBTREE" in text and "NODES" not in text
    for kind in ("stage:", "file:", "concern:", "node:"):
        assert kind in text, "the footer also names the kinds that take no row"


def test_a_call_site_named_only_in_the_footer_really_does_resolve(run):
    """...and the footer is measured against the analyzer, not trusted: the
    example it names must project on the sample the demo scripts use."""
    code, out, _err = run("analyze", SAMPLE_DIR, "--scope", "unit:train_test_split",
                          "--json", "-")
    assert code == 0
    doc = json.loads(out.decode("utf-8"))
    assert doc["view"]["resolvedTo"], "the footer names a selector that resolves"
    rows = json.loads(run("analyze", SAMPLE_DIR, "--list-scopes",
                          "--format", "json")[1].decode("utf-8"))
    assert "unit:train_test_split" not in {r["spec"] for r in rows}


def test_scoped_issues_names_the_findings_it_is_hiding(run):
    """R2-F2-08. `issues` is the CI-facing command; every other narrowing
    surface prints a denominator, so its header says how many findings the
    scope left out instead of letting 3 read as the project total."""
    head = run("issues", SAMPLE_DIR, "--scope",
               "concern:evaluation")[1].decode("utf-8").splitlines()[0]
    plain = run("issues", SAMPLE_DIR)[1].decode("utf-8").splitlines()[0]
    total = int(plain.split(" ", 1)[0])
    scoped_count = int(head.split(" ", 1)[0])
    assert "(scope: concern:evaluation" in head
    assert ("%d of %d" % (scoped_count, total)) in head
    assert ("%d outside this scope" % (total - scoped_count)) in head
    assert "outside this scope" not in plain, "an unscoped run is unchanged"


def test_a_scoped_summary_separates_out_of_scope_stages_from_absent_ones(run):
    """R2-F2-09. CONTRACTS 11.4 F3 split "not in this scope" from "not
    detected" for the viewer precisely so a scope cannot be read as a statement
    about which stages the project has; the text emitters make the same split,
    because that is the surface the demo scripts and CI logs show."""
    code, out, _err = run("analyze", SAMPLE_DIR, "--scope", "stage:train",
                          "--format", "summary")
    text = out.decode("utf-8")
    lines = [l.strip() for l in text.splitlines()]
    assert code == 0
    scoped_row = [l for l in lines if l.startswith("not in this scope:")]
    absent_row = [l for l in lines if l.startswith("not detected:")]
    assert len(scoped_row) == 1 and len(absent_row) == 1
    assert "deliver" in absent_row[0] and "deliver" not in scoped_row[0]
    assert "config" in scoped_row[0] and "eval" in scoped_row[0]
    assert " 0 nodes" not in text, "a present-but-empty stage is not a table row"
    plain = run("analyze", SAMPLE_DIR, "--format", "summary")[1].decode("utf-8")
    assert "not in this scope" not in plain, "an unscoped run is unchanged"
    assert "not detected: deliver" in plain


def test_a_scoped_text_run_makes_the_same_split(run):
    """`--format text` is `--format summary` plus lanes, so it inherits it."""
    text = run("analyze", SAMPLE_DIR, "--scope", "concern:evaluation",
               "--format", "text")[1].decode("utf-8")
    assert len([l for l in text.splitlines()
                if l.strip().startswith("not in this scope:")]) == 1
