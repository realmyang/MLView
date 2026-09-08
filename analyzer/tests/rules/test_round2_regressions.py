"""Regression tests for the round-2 review findings (ML-01 .. ML-06).

Each test names the finding it pins down and reproduces the exact shape that
was reported, so a re-regression fails here rather than in a sample golden.
"""

from __future__ import annotations

import json
import os

from rule_harness import (SAMPLES_DIR, analyze_paths, assert_fires, assert_silent,
                          describe, write_workspace)


def _of(doc, code):
    return [i for i in doc["issues"] if i["code"] == code]


# --------------------------------------------------------------------- ML-01
def test_an_unknown_model_zoo_does_not_make_the_loss_the_model():
    """MLV501 named `criterion` as "the model" whenever the real network came
    from a factory the knowledge tables do not carry."""
    run = assert_silent("MLV501_zoo_good", "MLV501")
    assert run.issues == [], describe(run.doc)


def test_model_not_moved_still_fires_when_the_model_does_resolve(tmp_path):
    """The ML-01 guard must not silence the genuine inverse variant."""
    source = (
        "import torch\n"
        "import torch.nn as nn\n"
        "import torch.optim as optim\n"
        "from torch.utils.data import DataLoader\n\n\n"
        "def train(ds):\n"
        "    torch.manual_seed(0)\n"
        "    device = torch.device('cuda')\n"
        "    net = nn.Sequential(nn.Linear(4, 2))\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = optim.SGD(net.parameters(), lr=0.01)\n"
        "    loader = DataLoader(ds, batch_size=8)\n"
        "    for x, y in loader:\n"
        "        x, y = x.to(device), y.to(device)\n"
        "        opt.zero_grad()\n"
        "        loss = crit(net(x), y)\n"
        "        loss.backward()\n"
        "        opt.step()\n")
    doc = analyze_paths(write_workspace(str(tmp_path), {"t.py": source}))
    issue = _of(doc, "MLV501")[0]
    assert "model_not_moved" in issue["tags"]
    assert "the model net" in issue["message"], issue["message"]
    assert "crit" not in issue["message"]


# --------------------------------------------------------------------- ML-02
_SIBLING = {
    "pkg/net.py": (
        "import torch.nn as nn\n\n\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.drop = nn.Dropout(0.3)\n"
        "        self.fc = nn.Linear(4, 2)\n\n"
        "    def forward(self, x):\n"
        "        return self.fc(self.drop(x))\n"),
    "pkg/run.py": (
        "import torch\n"
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "from net import Net\n\n\n"
        "def main():\n"
        "    torch.manual_seed(0)\n"
        "    ds = TensorDataset(torch.randn(8, 4), torch.randint(0, 2, (8,)))\n"
        "    val_loader = DataLoader(ds, batch_size=2)\n"
        "    model = Net()\n"
        "    for xb, yb in val_loader:\n"
        "        model(xb).argmax(1)\n"),
}


def test_sibling_imports_resolve_from_any_ancestor_root(tmp_path):
    """ML-02: analysing one directory above the scripts lost every sibling
    import, so five planted findings vanished and a false one appeared."""
    root = write_workspace(str(tmp_path), _SIBLING)
    inner = analyze_paths(os.path.join(root, "pkg"))
    outer = analyze_paths(root)
    inner_codes = sorted(i["code"] for i in inner["issues"])
    outer_codes = sorted(i["code"] for i in outer["issues"])
    assert inner_codes == outer_codes, (
        "the root passed must not change the findings: %s vs %s"
        % (describe(inner), describe(outer)))
    assert "MLV301" in inner_codes, "the class behind `from net import Net` resolved"


def test_the_sample_pair_survives_being_analyzed_from_the_parent():
    """The dirty sample keeps its planted findings and the clean twin keeps
    its 0/0/0 when `samples/` (both twins) is analyzed as one workspace."""
    doc = analyze_paths(SAMPLES_DIR)
    with open(os.path.join(SAMPLES_DIR, "vision_pipeline", "expected_issues.json"),
              encoding="utf-8") as fh:
        expected = json.load(fh)
    fired = {(i["code"], i["loc"]["file"], i["loc"]["line"]) for i in doc["issues"]}
    # MLV601 ("no seed anywhere") is workspace-scoped by definition: the clean
    # twin seeds, so the union legitimately does not carry it.
    missing = [e for e in expected if e["code"] != "MLV601"
               and (e["code"], "vision_pipeline/" + e["file"], e["line"]) not in fired]
    assert not missing, "planted findings lost from the parent root: %s" % missing
    clean = [i for i in doc["issues"]
             if i["loc"]["file"].startswith("vision_pipeline_clean/")]
    assert clean == [], "the clean twin must stay silent: %s" % clean


# --------------------------------------------------------------------- ML-03
def test_a_chained_device_move_keeps_the_model_class():
    """`model = Net().to(device)` must not cost MLV301 its severity."""
    run = assert_fires("MLV301_chained_bad")
    issue = run.of("MLV301")[0]
    assert issue["severity"] == "high"
    assert issue["confidence"] >= 0.6, "below 0.6 it never reaches the Problems panel"
    detail = " ".join(e["detail"] for e in issue["evidence"] if e["kind"] == "class_base")
    assert "Dropout" in detail, detail


def test_a_bare_sequential_model_is_classified_not_declared_unresolvable(tmp_path):
    source = (
        "import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader\n\n\n"
        "def evaluate(ds):\n"
        "    torch.manual_seed(0)\n"
        "    model = nn.Sequential(nn.Linear(4, 8), nn.Dropout(0.3), nn.Linear(8, 2))\n"
        "    loader = DataLoader(ds, batch_size=4)\n"
        "    for xb, yb in loader:\n"
        "        model(xb).argmax(1)\n")
    doc = analyze_paths(write_workspace(str(tmp_path), {"t.py": source}))
    issue = _of(doc, "MLV301")[0]
    assert issue["severity"] == "high", describe(doc)
    detail = " ".join(e["detail"] for e in issue["evidence"] if e["kind"] == "class_base")
    assert "Sequential" in detail and "Dropout" in detail, detail


# --------------------------------------------------------------------- ML-04
def test_an_inline_forward_pass_is_still_an_eval_region():
    """`hits += (model(x).argmax(1) == y).sum().item()` - the forward hides
    inside a compound expression, and the whole Evaluate lane went missing."""
    run = assert_fires("MLV301_inline_bad")
    doc = run.doc
    assert _of(doc, "MLV302"), describe(doc)
    stages = {s["id"]: s for s in doc["stages"]}
    assert stages["eval"]["present"], "the Evaluate lane must not report 'not detected'"
    loops = [n for n in doc["nodes"] if n["kind"] in ("train_loop", "eval_loop")]
    assert any(n["kind"] == "eval_loop" and n["stage"] == "eval" for n in loops), loops


# --------------------------------------------------------------------- ML-06
def test_the_training_loader_is_wired_to_the_training_loop_across_modules():
    """ML-06: `from data import train_loader` bound nothing, so the Data lane
    was a dead end in the shipped demo."""
    doc = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline"))
    by_id = {n["id"]: n for n in doc["nodes"]}
    cross = [e for e in doc["edges"]
             if e["kind"] == "data"
             and by_id[e["source"]]["loc"]["file"] == "data.py"
             and by_id[e["target"]]["loc"]["file"] == "train.py"]
    assert cross, "no data edge from data.py into train.py"
    loop = next(n for n in doc["nodes"]
                if n["kind"] in ("train_loop", "eval_loop")
                and n["label"].startswith("for images, labels in train_loader"))
    ports = {p["name"]: p["tags"] for p in loop.get("consumes", [])}
    assert "train_loader" in ports, loop.get("consumes")
    assert "LOADER" in ports["train_loader"] and "TRAIN_SPLIT" in ports["train_loader"]
