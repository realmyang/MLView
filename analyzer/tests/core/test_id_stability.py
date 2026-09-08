"""Content-addressed ids survive edits above a node (CONTRACTS section 0)."""

from __future__ import annotations

from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.core.ids import edge_id, issue_id, node_id

SRC = ("import torch\n"
       "import torch.nn as nn\n"
       "import torch.optim as optim\n"
       "from torch.utils.data import DataLoader\n\n\n"
       "def train(ds):\n"
       "    torch.manual_seed(0)\n"
       "    model = nn.Linear(4, 2)\n"
       "    criterion = nn.CrossEntropyLoss()\n"
       "    optimizer = optim.Adam(model.parameters())\n"
       "    loader = DataLoader(ds, batch_size=8)\n"
       "    for x, y in loader:\n"
       "        loss = criterion(model(x), y)\n"
       "        loss.backward()\n"
       "        optimizer.step()\n")


def test_ids_are_content_addressed():
    assert node_id("train.py", "train.batch_loop", "train_loop").startswith("n:")
    assert len(node_id("a", "b", "c")) == 14
    assert node_id("a", "b", "c") != node_id("a", "b", "d")
    assert edge_id("n:1", "data", "n:2", "x") != edge_id("n:1", "data", "n:2", "y")
    assert issue_id("MLV201", "train.py", "train.loop", "for") .startswith("i:")


def test_inserting_blank_lines_keeps_ids_and_shifts_lines(make_workspace):
    root = make_workspace({"train.py": SRC}, name="before")
    before = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    shifted_root = make_workspace({"train.py": "\n" * 20 + SRC}, name="after")
    after = analyze_to_dict(AnalyzeOptions(paths=(shifted_root,)))

    before_nodes = {n["id"]: n for n in before["nodes"]}
    after_nodes = {n["id"]: n for n in after["nodes"]}
    assert set(before_nodes) == set(after_nodes)
    for node_key, node in before_nodes.items():
        assert after_nodes[node_key]["loc"]["line"] == node["loc"]["line"] + 20

    assert {e["id"] for e in before["edges"]} == {e["id"] for e in after["edges"]}
    assert {i["id"] for i in before["issues"]} == {i["id"] for i in after["issues"]}


def test_ids_are_globally_unique(analyze_ws):
    doc = analyze_ws({"train.py": SRC})
    everything = ([n["id"] for n in doc["nodes"]] + [e["id"] for e in doc["edges"]]
                  + [i["id"] for i in doc["issues"]])
    assert len(everything) == len(set(everything))


def test_duplicate_call_sites_get_distinct_ids(analyze_ws):
    doc = analyze_ws({"m.py": ("from torch.utils.data import DataLoader\n"
                               "def build(a, b):\n"
                               "    DataLoader(a)\n"
                               "    DataLoader(b)\n")})
    loaders = [n for n in doc["nodes"] if n["kind"] == "dataloader"]
    assert len(loaders) == 2
    assert loaders[0]["id"] != loaders[1]["id"]
    assert loaders[0]["qualname"] != loaders[1]["qualname"]
