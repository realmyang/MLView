"""MLV-P12 (CONTRACTS 11.47): `pipeline:<entrypoint>` and the `pipelines[]` block.

Two training scripts that share one preprocessing module: the shape the ROADMAP
entry is about, small enough to reason about by hand.
"""

from __future__ import annotations

import copy
import json

import pytest

from core_support import validate
from mlview import cli
from mlview.api import (AnalyzeOptions, SCOPE_KINDS, ScopeError, analyze_to_dict,
                        parse_scope, project)
from mlview.core.pipelines import build_index, pipelines_block, resolve_entrypoint
from mlview.core.project import pipeline_catalog, scope_catalog

_SHARED = ("import pandas as pd\n"
           "from sklearn.preprocessing import StandardScaler\n\n\n"
           "def prep(path):\n"
           "    frame = pd.read_csv(path)\n"
           "    scaler = StandardScaler()\n"
           "    return scaler.fit_transform(frame)\n")

_TRAIN = ("import torch\n"
          "import torch.nn as nn\n"
          "import torch.optim as optim\n"
          "from torch.utils.data import DataLoader\n\n"
          "from shared import prep\n\n\n"
          "def train_{name}(path):\n"
          "    features = prep(path)\n"
          "    model = nn.Linear({width}, 2)\n"
          "    criterion = nn.CrossEntropyLoss()\n"
          "    optimizer = optim.Adam(model.parameters())\n"
          "    loader = DataLoader(features, batch_size={batch})\n"
          "    for batch_x, batch_y in loader:\n"
          "        loss = criterion(model(batch_x), batch_y)\n"
          "        loss.backward()\n"
          "        optimizer.step()\n"
          "    return model\n\n\n"
          "if __name__ == '__main__':\n"
          "    train_{name}('{name}.csv')\n")

TWO = {
    "shared.py": _SHARED,
    "alpha.py": _TRAIN.format(name="alpha", width=8, batch=16),
    "beta.py": _TRAIN.format(name="beta", width=4, batch=32),
}

ONE = {
    "shared.py": _SHARED,
    "alpha.py": _TRAIN.format(name="alpha", width=8, batch=16),
}


@pytest.fixture
def two(analyze_ws):
    return analyze_ws(TWO)


# ------------------------------------------------------------ the relation
def test_the_block_is_emitted_only_when_there_is_a_choice(analyze_ws, two):
    """11.47 D. A single-entrypoint workspace emits exactly the bytes it emitted
    before this feature existed."""
    assert len(two["workspace"]["entrypoints"]) >= 2
    assert len(two["pipelines"]) >= 2
    assert {"alpha.py", "beta.py"} <= {r["entrypoint"] for r in two["pipelines"]}
    lone = analyze_ws(ONE)
    assert len(lone["workspace"]["entrypoints"]) == 1
    assert "pipelines" not in lone


def test_the_rows_are_consistent_and_ordered(two):
    entrypoints = two["workspace"]["entrypoints"]
    order = [row["entrypoint"] for row in two["pipelines"]]
    assert order == [e for e in entrypoints if e in order]
    for row in two["pipelines"]:
        assert row["entrypoint"] in entrypoints
        assert row["exclusiveCount"] + row["sharedCount"] == row["nodeCount"]
        assert row["nodeCount"] >= 1
        assert set(row) == {"entrypoint", "label", "nodeCount", "exclusiveCount",
                            "sharedCount", "issueCounts"}
    assert validate(two) == []


def test_the_shared_module_really_is_shared(two):
    """`prep()` is reached from both training scripts, so it is shared for both.

    Each script's own nodes are shared for the *other* pipeline and never for
    its own (11.47 A3.1): the closure includes another entrypoint's nodes
    without expanding through them, so a pipeline can see where it touches its
    neighbour without swallowing it.
    """
    index = build_index(two)
    by_id = {n["id"]: n for n in two["nodes"]}
    mutual = set(index.context_of("alpha.py")) & set(index.context_of("beta.py"))
    assert mutual, "prep() is reached from both training scripts"
    assert {by_id[n]["loc"]["file"] for n in mutual} == {"shared.py"}
    for entrypoint in ("alpha.py", "beta.py"):
        own = {n for n in index.core_of(entrypoint)
               if by_id[n]["loc"]["file"] == entrypoint}
        assert own, entrypoint
        assert not (own & set(index.context_of(entrypoint)))


def test_config_edges_do_not_join_two_pipelines(analyze_ws):
    """11.47 A2. A shared `config.py` is exactly the module that would merge
    every training script into one component, which is why `config` edges are
    cut out of the relation."""
    files = dict(TWO)
    files["conf.py"] = "BATCH = 16\nWORKERS = 4\n"
    files["alpha.py"] = files["alpha.py"].replace(
        "from shared import prep", "from conf import BATCH\nfrom shared import prep")
    doc = analyze_ws(files)
    index = build_index(doc)
    by_id = {n["id"]: n for n in doc["nodes"]}
    for node_id in index.shared:
        assert by_id[node_id]["loc"]["file"] != "conf.py"


def test_the_relation_reads_only_the_document(two):
    """Purity: a doctored `pipelines[]` block cannot move a projection, because
    `project()` recomputes the relation and never reads the block."""
    doctored = copy.deepcopy(two)
    doctored["pipelines"] = [{"entrypoint": "alpha.py", "label": "lies",
                              "nodeCount": 9999, "exclusiveCount": 9999,
                              "sharedCount": 0,
                              "issueCounts": {"low": 0, "medium": 0, "high": 0}}]
    honest = project(two, parse_scope("pipeline:alpha.py"))
    lied_to = project(doctored, parse_scope("pipeline:alpha.py"))
    assert ([n["id"] for n in honest["nodes"]]
            == [n["id"] for n in lied_to["nodes"]])


# ------------------------------------------------------------- the grammar
def test_pipeline_joins_the_kind_tuple_and_the_candidates():
    assert "pipeline" in SCOPE_KINDS
    with pytest.raises(ScopeError) as caught:
        parse_scope("bogus:x")
    assert "pipeline" in caught.value.candidates


def test_an_unknown_entrypoint_names_the_real_ones(two):
    with pytest.raises(ScopeError) as caught:
        project(two, parse_scope("pipeline:nope.py"))
    assert caught.value.code == "unknown_pipeline"
    assert caught.value.term == "nope.py"
    assert set(caught.value.candidates) <= set(two["workspace"]["entrypoints"])
    assert caught.value.candidates


def test_an_empty_target_falls_through_to_the_resolver(two):
    """11.47 B1: only the resolver knows this workspace's entrypoints, so
    `pipeline:` is not a `bad_selector` - it is an `unknown_pipeline` that names
    them."""
    scope = parse_scope("pipeline:")
    assert scope.kind == "pipeline" and scope.target == ""
    with pytest.raises(ScopeError) as caught:
        project(two, scope)
    assert caught.value.code == "unknown_pipeline" and caught.value.term == ""
    assert caught.value.candidates


def test_a_bare_basename_and_a_case_fold_resolve(analyze_ws):
    files = {"pkg/__init__.py": "", "pkg/shared.py": _SHARED,
             "pkg/alpha.py": _TRAIN.format(name="alpha", width=8, batch=16),
             "pkg/beta.py": _TRAIN.format(name="beta", width=4, batch=32)}
    doc = analyze_ws(files)
    entry = next(e for e in doc["workspace"]["entrypoints"]
                 if e.endswith("alpha.py"))
    assert resolve_entrypoint(doc, "alpha.py")[0] == entry
    canonical, warnings = resolve_entrypoint(doc, "ALPHA.PY")
    assert canonical == entry and warnings and "canonical" in warnings[0]
    assert resolve_entrypoint(doc, "pkg\\alpha.py".replace("\\", "/"))[0] == entry


def test_the_default_depth_is_zero(two):
    assert parse_scope("pipeline:alpha.py").depth == 0
    assert project(two, parse_scope("pipeline:alpha.py"))["view"]["depth"] == 0


# ---------------------------------------------------------- the projection
def test_a_shared_node_is_context_in_both_pipelines(two):
    """The ROADMAP clause, asserted from both sides."""
    alpha = project(two, parse_scope("pipeline:alpha.py"))
    beta = project(two, parse_scope("pipeline:beta.py"))
    roles_a = {n["id"]: n["viewRole"] for n in alpha["nodes"]}
    roles_b = {n["id"]: n["viewRole"] for n in beta["nodes"]}
    index = build_index(two)
    mutual = set(index.context_of("alpha.py")) & set(index.context_of("beta.py"))
    assert mutual
    for node_id in mutual:
        assert roles_a.get(node_id) == "context"
        assert roles_b.get(node_id) == "context"
    core_a = {n for n, r in roles_a.items() if r == "core"}
    core_b = {n for n, r in roles_b.items() if r == "core"}
    assert core_a and core_b
    assert not (core_a & core_b), "two pipelines never claim the same node"


def test_a_pipeline_projection_is_a_valid_document(two):
    for entrypoint in (row["entrypoint"] for row in two["pipelines"]):
        doc = project(two, parse_scope("pipeline:%s" % entrypoint))
        assert validate(doc) == []
        assert doc["view"]["scope"] == "pipeline:%s" % entrypoint
        assert doc["view"]["label"] == entrypoint
        counts = doc["view"]["counts"]
        assert counts["core"] + counts["boundary"] + counts["context"] == \
            doc["stats"]["nodes"]


def test_the_block_is_carried_through_a_projection_verbatim(two):
    """11.2 step 10: a projection never restates project-level truth."""
    doc = project(two, parse_scope("pipeline:alpha.py"))
    assert doc["pipelines"] == two["pipelines"]
    other = project(two, parse_scope("stage:train"))
    assert other["pipelines"] == two["pipelines"]


def test_the_projection_says_what_it_is_not_showing(two):
    """11.47 C1: the honesty note - drawn, shared, and how many nodes of the
    whole graph belong to no pipeline at all."""
    doc = project(two, parse_scope("pipeline:alpha.py"))
    notes = [d["message"] for d in doc["diagnostics"]
             if d["kind"] == "config_warning" and "pipeline:alpha.py" in d["message"]]
    assert notes, [d["message"] for d in doc["diagnostics"]]
    assert "shared" in notes[0] and "no pipeline" in notes[0]


def test_an_entrypoint_that_contributed_no_node_is_an_empty_scope(two):
    """11.47 B1: an empty pipeline is a finding, not an error - the `unit:`
    rule, for the same reason."""
    stripped = copy.deepcopy(two)
    stripped["nodes"] = [n for n in stripped["nodes"]
                         if n["loc"]["file"] != "alpha.py"]
    keep = {n["id"] for n in stripped["nodes"]}
    stripped["edges"] = [e for e in stripped["edges"]
                         if e["source"] in keep and e["target"] in keep]
    doc = project(stripped, parse_scope("pipeline:alpha.py"))
    assert doc["view"]["empty"] is True
    assert doc["nodes"] == [] and len(doc["stages"]) == 8


# ---------------------------------------------------------- the catalogue
def test_the_catalogue_offers_a_pipeline_row_per_pipeline(two):
    rows = pipeline_catalog(two)
    assert [r["spec"] for r in rows] == \
        ["pipeline:%s" % r["entrypoint"] for r in two["pipelines"]]
    unit_rows = scope_catalog(two, limit=0)
    for row in rows:
        assert set(row) == set(unit_rows[0])
        assert row["kind"] == "pipeline" and row["line"] == 1
    assert all(r["spec"].startswith("unit:") for r in unit_rows), (
        "pipeline rows are deliberately NOT merged into scope_catalog: the MCP "
        "catalogue prefixes every row with unit: from its qualname")


def test_the_three_numbers_a_user_sees_are_one_number(two):
    """11.47 D. `pipelines[].exclusiveCount`, `view.counts.core` at depth 0 and
    the `SUBTREE` column of the `--list-scopes` row are the same quantity - the
    A3.1 sense of "shared", with the owner exception. The differential gate
    caught the two ports disagreeing on exactly this."""
    rows = {r["qualname"]: r for r in pipeline_catalog(two)}
    for block in two["pipelines"]:
        entrypoint = block["entrypoint"]
        doc = project(two, parse_scope("pipeline:%s" % entrypoint, 0))
        assert block["exclusiveCount"] == doc["view"]["counts"]["core"]
        assert block["exclusiveCount"] == rows[entrypoint]["nodeCount"]
        assert block["sharedCount"] == len(build_index(two).context_of(entrypoint))


def test_the_catalogue_count_is_what_depth_0_draws(two):
    for row in pipeline_catalog(two):
        doc = project(two, parse_scope(row["spec"], 0))
        assert doc["view"]["counts"]["core"] == row["nodeCount"]


def test_a_single_pipeline_workspace_offers_no_row(analyze_ws):
    assert pipeline_catalog(analyze_ws(ONE)) == []


def test_list_scopes_prints_the_pipeline_rows(make_workspace, capsysbinary):
    root = make_workspace(TWO)
    assert cli.main(["analyze", root, "--list-scopes"]) == 0
    text = capsysbinary.readouterr().out.decode("utf-8")
    assert "pipeline:alpha.py" in text and "pipeline(s)" in text
    assert "pipeline:<entrypoint>" in text, "the footer names the whole grammar"

    assert cli.main(["analyze", root, "--list-scopes", "--format", "json"]) == 0
    rows = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    specs = [r["spec"] for r in rows]
    assert specs[0].startswith("pipeline:"), "the coarsest scopes lead the menu"
    assert any(s.startswith("unit:") for s in specs)


def test_the_selector_round_trips_through_the_cli(make_workspace, capsysbinary):
    root = make_workspace(TWO)
    assert cli.main(["analyze", root, "--scope", "pipeline:alpha.py",
                     "--json", "-"]) == 0
    doc = json.loads(capsysbinary.readouterr().out.decode("utf-8"))
    assert doc["view"]["scope"] == "pipeline:alpha.py"
    assert validate(doc) == []
    assert cli.main(["analyze", root, "--scope", "pipeline:nope.py"]) == 1
    assert "unknown_pipeline" in capsysbinary.readouterr().err.decode("utf-8")


# ------------------------------------------------- rollup x pipelines
def test_the_block_describes_the_document_it_was_emitted_with(make_workspace):
    """11.47 F: on a capped document the counts describe the SUMMARISED graph,
    and `stats.truncated` is the only thing that says so."""
    root = make_workspace(TWO)
    capped = analyze_to_dict(AnalyzeOptions(paths=(root,), max_nodes=12))
    assert capped["stats"]["truncated"] is True
    assert validate(capped) == []
    if "pipelines" in capped:
        for row in capped["pipelines"]:
            assert row["nodeCount"] <= capped["stats"]["nodes"]


def test_pipelines_are_absent_from_a_graph_with_no_entrypoint(analyze_ws):
    doc = analyze_ws({"lib.py": "def helper(x):\n    return x + 1\n"})
    assert pipelines_block(doc) == []
    assert "pipelines" not in doc
