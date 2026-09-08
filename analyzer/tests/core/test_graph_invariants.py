"""Graph invariants (CONTRACTS section 1.1) over several workspaces.

Every document is run through `contracts/validate_sample.py`, which checks the
schema, the id/hierarchy/edge/issue invariants, the ordering rules, the stage
aggregates, the stats, the confidence buckets and location hygiene.
"""

from __future__ import annotations

import glob
import os

import pytest

from core_support import FIXTURES, validate
from mlview.api import AnalyzeOptions, analyze_to_dict, parse_scope, project
from scope_support import cases, golden

MULTIFILE = {
    "config.py": ("from dataclasses import dataclass\n\n\n"
                  "@dataclass\nclass Cfg:\n    batch_size: int = 64\n    lr: float = 0.01\n\n\n"
                  "CFG = Cfg()\n"),
    "data.py": ("import torch\n"
                "from torch.utils.data import DataLoader, TensorDataset, random_split\n\n\n"
                "def build_loaders(cfg):\n"
                "    ds = TensorDataset(torch.zeros(8, 4), torch.zeros(8, dtype=torch.long))\n"
                "    train_ds, val_ds = random_split(ds, [6, 2])\n"
                "    train_loader = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)\n"
                "    val_loader = DataLoader(val_ds, batch_size=cfg.batch_size)\n"
                "    return train_loader, val_loader\n"),
    "models/net.py": ("import torch.nn as nn\n\n\n"
                      "class Net(nn.Module):\n"
                      "    def __init__(self):\n"
                      "        super().__init__()\n"
                      "        self.fc = nn.Linear(4, 2)\n"
                      "        self.drop = nn.Dropout(0.5)\n\n"
                      "    def forward(self, x):\n"
                      "        return self.fc(self.drop(x))\n"),
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from config import CFG\n"
                 "from data import build_loaders\n"
                 "from models.net import Net\n\n\n"
                 "def train(cfg):\n"
                 "    torch.manual_seed(0)\n"
                 "    train_loader, val_loader = build_loaders(cfg)\n"
                 "    model = Net()\n"
                 "    criterion = nn.CrossEntropyLoss()\n"
                 "    optimizer = optim.SGD(model.parameters(), lr=cfg.lr)\n"
                 "    for epoch in range(3):\n"
                 "        for x, y in train_loader:\n"
                 "            optimizer.zero_grad()\n"
                 "            loss = criterion(model(x), y)\n"
                 "            loss.backward()\n"
                 "            optimizer.step()\n"
                 "    validate(model, val_loader)\n"
                 "    torch.save(model.state_dict(), 'net.pt')\n\n\n"
                 "def validate(model, loader):\n"
                 "    model.eval()\n"
                 "    with torch.no_grad():\n"
                 "        for x, y in loader:\n"
                 "            model(x)\n\n\n"
                 "if __name__ == '__main__':\n"
                 "    train(CFG)\n"),
}


@pytest.fixture
def multifile(analyze_ws):
    return analyze_ws(MULTIFILE)


def test_document_satisfies_every_contract_check(multifile):
    errors = validate(multifile)
    assert errors == [], "\n".join(errors)


def test_fixture_documents_satisfy_every_contract_check():
    for path in sorted(glob.glob(os.path.join(FIXTURES, "rules", "*.py"))):
        doc = analyze_to_dict(AnalyzeOptions(paths=(path,)))
        errors = validate(doc)
        assert errors == [], "%s:\n%s" % (os.path.basename(path), "\n".join(errors))


def test_parent_forest_has_no_cycles_and_decreasing_levels(multifile):
    rank = {"stage": 0, "unit": 1, "op": 2}
    by_id = {n["id"]: n for n in multifile["nodes"]}
    for node in multifile["nodes"]:
        seen = set()
        current = node
        while current["parent"]:
            assert current["parent"] in by_id
            assert current["parent"] not in seen
            seen.add(current["parent"])
            parent = by_id[current["parent"]]
            assert rank[parent["level"]] < rank[current["level"]]
            current = parent


def test_edges_resolve_and_ids_are_unique(multifile):
    ids = [n["id"] for n in multifile["nodes"]]
    assert len(ids) == len(set(ids))
    node_ids = set(ids)
    for edge in multifile["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
    edge_ids = [e["id"] for e in multifile["edges"]]
    assert len(edge_ids) == len(set(edge_ids))


def test_cross_file_call_edges(multifile):
    labels = {n["id"]: n["label"] for n in multifile["nodes"]}
    files = {n["id"]: n["loc"]["file"] for n in multifile["nodes"]}
    call_edges = [(files[e["source"]], files[e["target"]]) for e in multifile["edges"]
                  if e["kind"] == "call"]
    assert ("train.py", "models/net.py") in call_edges
    assert ("train.py", "data.py") in call_edges
    assert "Net" in labels.values()


def test_loop_units_and_back_edges(multifile):
    loops = [n for n in multifile["nodes"] if n["kind"] in ("train_loop", "eval_loop")
             and n["level"] in ("unit", "stage") and "loopKind" in n.get("attrs", {})]
    kinds = {n["attrs"]["loopKind"] for n in loops}
    assert {"epoch", "batch"} <= kinds
    subkinds = {e.get("subkind") for e in multifile["edges"] if e["kind"] == "control"}
    assert {"enter", "back"} <= subkinds
    back_labels = {e.get("label") for e in multifile["edges"] if e.get("subkind") == "back"}
    assert back_labels & {"next batch", "next epoch"}


def test_data_edges_carry_the_call_site(multifile):
    for edge in multifile["edges"]:
        assert edge["loc"]["line"] >= 1
        assert edge["loc"]["file"].endswith(".py")


def test_ports_and_tags(multifile):
    loader = [n for n in multifile["nodes"] if n.get("var") == "train_loader"]
    assert loader, [n["label"] for n in multifile["nodes"]]
    produces = loader[0]["produces"]
    assert produces and "LOADER" in produces[0]["tags"]


def assert_stage_summaries(doc, unprojected=None):
    """`nodeCount` always describes the document; `present` describes the
    ANALYSIS (CONTRACTS 11.4 F2).

    In an unprojected document the two coincide, and the old equality still
    holds. A projection carries `present` through verbatim - project-level
    truth - so `present: true` at `nodeCount: 0` is correct there, and the
    weaker, correct pair is asserted instead.
    """
    counts = {}
    for node in doc["nodes"]:
        counts[node["stage"]] = counts.get(node["stage"], 0) + 1
    before = {s["id"]: s for s in (unprojected or doc)["stages"]}
    for stage in doc["stages"]:
        assert stage["nodeCount"] == counts.get(stage["id"], 0)
        if "view" not in doc:
            assert stage["present"] == bool(stage["nodeCount"]
                                            or any(stage["issueCounts"].values()))
        else:
            assert stage["present"] == before[stage["id"]]["present"]


def test_stage_summaries_match_nodes(multifile):
    assert_stage_summaries(multifile)


def test_max_nodes_truncates_ops_and_keeps_units(analyze_ws):
    doc = analyze_ws(MULTIFILE, max_nodes=12)
    assert doc["stats"]["truncated"] is True
    assert len(doc["nodes"]) <= 12
    assert any(d["kind"] == "truncated" for d in doc["diagnostics"])
    assert validate(doc) == []


def test_ghost_nodes_carry_issues(analyze_ws):
    doc = analyze_ws({"t.py": ("import torch\n"
                               "import torch.nn as nn\n"
                               "import torch.optim as optim\n"
                               "from torch.utils.data import DataLoader\n\n\n"
                               "def train(ds):\n"
                               "    torch.manual_seed(0)\n"
                               "    model = nn.Linear(2, 2)\n"
                               "    crit = nn.MSELoss()\n"
                               "    opt = optim.SGD(model.parameters(), lr=0.1)\n"
                               "    loader = DataLoader(ds, batch_size=2)\n"
                               "    for x, y in loader:\n"
                               "        loss = crit(model(x), y)\n"
                               "        loss.backward()\n"
                               "        opt.step()\n")})
    ghosts = [n for n in doc["nodes"] if n["ghost"]]
    assert ghosts, "MLV201 should have declared a ghost zero_grad slot"
    for ghost in ghosts:
        assert ghost["issueIds"]
        assert ghost["sublabel"] == "missing"
        assert "__ghost_" in ghost["qualname"]
    assert validate(doc) == []


CONFIG_SOURCES = {
    "m.py": ("import argparse\n"
             "import json\n"
             "import torch.nn as nn\n"
             "import torch.optim as optim\n"
             "from torch.utils.data import DataLoader\n\n"
             "with open('cfg.json') as fh:\n"
             "    config = json.load(fh)\n\n"
             "parser = argparse.ArgumentParser()\n"
             "args = parser.parse_args()\n"
             "hparams = {'lr': 0.01, 'bs': 32}\n\n\n"
             "def build(ds):\n"
             "    model = nn.Linear(config['dim'], 2)\n"
             "    opt = optim.Adam(model.parameters(), lr=hparams['lr'])\n"
             "    loader = DataLoader(ds, batch_size=args.bs)\n"
             "    return model, opt, loader\n"),
}


def test_config_edges_run_from_every_config_source(analyze_ws):
    """argparse / a loaded file / a `cfg`-shaped dict literal all reach consumers."""
    doc = analyze_ws(CONFIG_SOURCES)
    by_id = {n["id"]: n for n in doc["nodes"]}
    config_edges = [e for e in doc["edges"] if e["kind"] == "config"]
    assert {e["label"] for e in config_edges} == {"config", "args", "hparams"}
    for edge in config_edges:
        assert by_id[edge["target"]]["label"] == "build()"
        assert by_id[edge["source"]]["stage"] == "config"
        assert edge["loc"]["line"] >= 15, "a config edge is located at the use site"
    assert validate(doc) == []


def test_a_config_dict_literal_becomes_a_node(analyze_ws):
    """A literal has no call behind it, so the builder mints its node."""
    doc = analyze_ws(CONFIG_SOURCES)
    literal = next(n for n in doc["nodes"] if n["label"] == "hparams")
    assert literal["kind"] == "config"
    assert literal["level"] == "op"
    assert literal["stage"] == "config"
    assert literal["var"] == "hparams"
    assert "lr" in literal["sublabel"]
    assert "fqn" not in literal, "there is no third-party symbol behind a literal"
    assert literal["stageEvidence"][0]["kind"] == "name_regex"
    assert literal["loc"]["line"] == 12


def test_a_plain_dict_is_not_a_config_source(analyze_ws):
    """Only the `cfg|config|args|hparams|...` names qualify - not every dict."""
    doc = analyze_ws({"m.py": ("import torch.nn as nn\n"
                               "sizes = {'a': 1}\n"
                               "layer = nn.Linear(sizes['a'], 2)\n")})
    assert [n for n in doc["nodes"] if n["kind"] == "config"] == []
    assert [e for e in doc["edges"] if e["kind"] == "config"] == []


# ----------------------------------------------- projections (CONTRACTS 11.4)
_BATTERY = [(c["spec"], c["depth"]) for c in cases() if c["kind"] == "project"]


@pytest.mark.parametrize("spec,depth", _BATTERY, ids=[s for s, _d in _BATTERY])
def test_every_projection_satisfies_every_contract_check(spec, depth):
    """Invariant 9: a document carrying `view` is still a valid document, and
    invariants 1-8 still hold on it."""
    doc = project(golden(), parse_scope(spec, depth))
    errors = validate(doc)
    assert errors == [], "\n".join(errors)
    assert_stage_summaries(doc, unprojected=golden())
    if "view" in doc:
        assert all("viewRole" in n for n in doc["nodes"])
        counts = doc["view"]["counts"]
        assert counts["core"] + counts["boundary"] + counts["context"] == \
            doc["stats"]["nodes"]
        assert doc["workspace"] == golden()["workspace"]
        assert doc["generator"] == golden()["generator"]


@pytest.mark.parametrize("spec,depth", _BATTERY, ids=[s for s, _d in _BATTERY])
def test_a_projection_keeps_the_parent_forest_and_the_edge_endpoints(spec, depth):
    doc = project(golden(), parse_scope(spec, depth))
    ids = {n["id"] for n in doc["nodes"]}
    rank = {"stage": 0, "unit": 1, "op": 2}
    by_id = {n["id"]: n for n in doc["nodes"]}
    for node in doc["nodes"]:
        if node["parent"]:
            assert node["parent"] in ids
            assert rank[by_id[node["parent"]]["level"]] < rank[node["level"]]
    for edge in doc["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
    for issue in doc["issues"]:
        assert issue["nodeIds"] and issue["nodeIds"][0] in ids
    for node in doc["nodes"]:
        if node["ghost"]:
            assert node["issueIds"], "invariant 1.1.8 survives the projection"
