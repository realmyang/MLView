"""Round-1 fixer regressions: the false positives, the misses and the lies.

Each test here is a finding that survived the whole suite once. They are kept
together (rather than scattered) so the shape of the failure stays readable:

* MLA-01/05 - a value that comes back from an in-workspace factory used to be
  untyped, so `opt.step()` / `model.to(device)` resolved to nothing and the
  absence rules fired on correct code (and missed the real defect next to it);
* MLA-02 - `X = df.drop(columns=[target])` dropped the RAW_DATA tag on the
  first hop, so MLV101 never saw the pandas path at all;
* MLA-03 - a wrapper anywhere in the workspace *deleted* MLV301/302/501;
* MLA-06 - MLV401 missed a bare `nn.Sequential(..., nn.Softmax(dim=1))`;
* MLA-08/09/10 - a finding that fires but navigates the reader to the wrong
  line, or quotes a count the source plainly contradicts.
"""

from __future__ import annotations

import os

import pytest

from rule_harness import (RULE_FIXTURES, SAMPLES_DIR, analyze_paths, describe,
                          write_workspace)

FACTORY = (
    "import torch\n"
    "import torch.nn as nn\n"
    "import torch.optim as optim\n"
    "from torch.utils.data import DataLoader\n\n\n"
    "def build_optimizer(model, cfg):\n"
    "    if cfg['name'] == 'adam':\n"
    "        return optim.Adam(model.parameters(), lr=cfg['lr'])\n"
    "    return optim.SGD(model.parameters(), lr=cfg['lr'])\n\n\n"
    "def train(ds, cfg):\n"
    "    torch.manual_seed(0)\n"
    "    model = nn.Linear(4, 2)\n"
    "    opt = build_optimizer(model, cfg)\n"
    "    crit = nn.CrossEntropyLoss()\n"
    "    dl = DataLoader(ds, batch_size=8, shuffle=True)\n"
    "    model.train()\n"
    "    for xb, yb in dl:\n"
    "        opt.zero_grad()\n"
    "        loss = crit(model(xb), yb)\n"
    "        loss.backward()\n"
    "        opt.step()\n")

LIT = ("import pytorch_lightning as pl\n"
       "import torch.nn as nn\n\n\n"
       "class Lit(pl.LightningModule):\n"
       "    def __init__(self):\n"
       "        super().__init__()\n"
       "        self.net = nn.Linear(4, 2)\n")

EVAL_LOOP = (
    "import torch\n"
    "import torch.nn as nn\n"
    "import torch.optim as optim\n"
    "from torch.utils.data import DataLoader\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.drop = nn.Dropout(0.2)\n"
    "        self.norm = nn.BatchNorm1d(4)\n"
    "        self.fc = nn.Linear(4, 2)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(self.drop(self.norm(x)))\n\n\n"
    "def evaluate(ds):\n"
    "    torch.manual_seed(0)\n"
    "    device = torch.device('cuda')\n"
    "    model = Net().to(device)\n"
    "    loader = DataLoader(ds, batch_size=8)\n"
    "    correct = 0\n"
    "    for x, y in loader:\n"
    "        preds = model(x).argmax(dim=1)\n"
    "        correct += (preds == y).sum().item()\n"
    "    return correct\n")


def _codes(doc):
    return [i["code"] for i in doc["issues"]]


def _of(doc, code):
    return [i for i in doc["issues"] if i["code"] == code]


# ------------------------------------------------------ MLA-01: the factory
def test_an_optimizer_from_a_factory_is_not_reported_as_missing(tmp_path):
    root = write_workspace(str(tmp_path), {"factory.py": FACTORY})
    doc = analyze_paths(root)
    assert doc["issues"] == [], describe(doc)
    assert not [n for n in doc["nodes"] if n["ghost"]], "no ghost step() either"


@pytest.mark.parametrize("removed,code", [("        opt.zero_grad()\n", "MLV201"),
                                          ("        opt.step()\n", "MLV202")])
def test_the_real_defect_behind_a_factory_is_still_found(tmp_path, removed, code):
    """Silence must come from understanding the factory, not from giving up."""
    source = FACTORY.replace(removed, "")
    assert source != FACTORY
    root = write_workspace(str(tmp_path), {"factory.py": source})
    doc = analyze_paths(root)
    assert code in _codes(doc), describe(doc)


def test_a_tuple_returning_factory_types_both_positions(tmp_path):
    doc = analyze_paths(os.path.join(RULE_FIXTURES, "MLV202_factory_good.py"))
    assert doc["issues"] == [], describe(doc)


# ------------------------------------------------------- MLA-02: the pandas path
PANDAS_LEAK = (
    "import pandas as pd\n"
    "from sklearn.model_selection import train_test_split\n"
    "from sklearn.preprocessing import StandardScaler\n\n"
    "df = pd.read_csv('a.csv')\n"
    "y = df['churn']\n"
    "%s\n"
    "scaler = StandardScaler()\n"
    "Xs = scaler.fit_transform(X)\n"
    "X_tr, X_te, y_tr, y_te = train_test_split(Xs, y, test_size=0.2, random_state=0)\n")


@pytest.mark.parametrize("builder", [
    "X = df.drop(columns=['churn'])",
    "X = df.drop(columns=['churn']).fillna(0.0)",
    "X = df[['age', 'income']].to_numpy()",
    "X = df.select_dtypes('number').copy()",
], ids=["drop", "drop-fillna", "subscript-to_numpy", "select_dtypes-copy"])
def test_the_pandas_feature_matrix_keeps_its_data_tags(tmp_path, builder):
    root = write_workspace(str(tmp_path), {"leak.py": PANDAS_LEAK % builder})
    doc = analyze_paths(root)
    assert "MLV101" in _codes(doc), "%s -> %s" % (builder, describe(doc))


def test_the_pandas_leak_fixture_fires_high(tmp_path):
    doc = analyze_paths(os.path.join(RULE_FIXTURES, "MLV101_pandas_bad.py"))
    issue = _of(doc, "MLV101")[0]
    assert issue["severity"] == "high"
    assert issue["loc"]["line"] == 19
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"fit_site", "split_site"} <= roles


# ----------------------------------------------- MLA-03: the wrapper gate
def test_an_unrelated_wrapper_file_does_not_delete_findings(tmp_path):
    root = write_workspace(str(tmp_path), {"lit.py": LIT, "eval.py": EVAL_LOOP})
    doc = analyze_paths(root)
    codes = set(_codes(doc))
    assert {"MLV301", "MLV302", "MLV501"} <= codes, describe(doc)
    for issue in doc["issues"]:
        assert issue["confidence"] >= 0.5, "nothing is de-rated by a file it never sees"


def test_a_wrapper_in_the_same_module_de_rates_instead_of_deleting(tmp_path):
    root = write_workspace(str(tmp_path), {"eval.py": LIT + "\n\n" + EVAL_LOOP})
    doc = analyze_paths(root)
    gated = {i["code"]: i for i in doc["issues"]
             if i["code"] in ("MLV301", "MLV302", "MLV501")}
    assert set(gated) == {"MLV301", "MLV302", "MLV501"}, (
        "iron law 4 de-rates to speculative, it does not delete: %s" % describe(doc))
    for issue in gated.values():
        assert issue["confidenceBucket"] == "speculative", issue["code"]
    chip = [d for d in doc["diagnostics"] if d["kind"] == "framework_suppressed"]
    assert len(chip) == 1
    assert set(gated) <= set(chip[0]["codes"]), "the chip names every gated rule"
    assert "%d rule(s)" % len(chip[0]["codes"]) in chip[0]["message"], chip[0]["message"]
    assert chip[0]["count"] == len(chip[0]["codes"]), "the count matches the codes"


# ------------------------------------------------ MLA-05: the model factory
def test_a_model_from_a_factory_is_not_reported_as_left_behind(tmp_path):
    doc = analyze_paths(os.path.join(RULE_FIXTURES, "MLV501_factory_good.py"))
    assert doc["issues"] == [], describe(doc)


def test_the_inverse_variant_names_the_model_not_the_loss(tmp_path):
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
    root = write_workspace(str(tmp_path), {"t.py": source})
    doc = analyze_paths(root)
    issue = _of(doc, "MLV501")[0]
    assert "model_not_moved" in issue["tags"]
    assert "the model net" in issue["message"], issue["message"]
    assert "crit" not in issue["message"], "crit is the loss, not the model"
    construction = next(r for r in issue["relatedLocs"] if r["role"] == "construction")
    assert 13 <= construction["line"] <= 18, "the cited move is inside train()"


# --------------------------------------------- MLA-06: the bare Sequential
def test_a_bare_sequential_ending_in_softmax_is_found():
    doc = analyze_paths(os.path.join(RULE_FIXTURES, "MLV401_sequential_bad.py"))
    issue = _of(doc, "MLV401")[0]
    assert issue["severity"] == "high"
    final = next(r for r in issue["relatedLocs"] if r["role"] == "final_layer")
    assert final["line"] == 14, "nn.Softmax(dim=1) is the last Sequential element"


def test_a_sequential_without_a_softmax_stays_silent(tmp_path):
    source = open(os.path.join(RULE_FIXTURES, "MLV401_sequential_bad.py"),
                  encoding="utf-8").read().replace(",\n                        "
                                                   "nn.Softmax(dim=1))", ")")
    root = write_workspace(str(tmp_path), {"t.py": source})
    assert not _of(analyze_paths(root), "MLV401")


# ---------------------------------------- MLA-08: the optimizer_site marker
def test_mlv202_points_at_the_optimizer_not_at_the_loss():
    doc = analyze_paths(os.path.join(RULE_FIXTURES, "MLV202_bad.py"))
    issue = _of(doc, "MLV202")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"backward_site", "optimizer_site"}
    snippet = roles["optimizer_site"].get("snippet", "")
    assert "optim" in snippet or "Optimizer" in snippet, (
        "'optimizer created here' pointed at %r" % snippet)
    assert "loss" not in snippet


# ---------------------------------------------- MLA-09: the MLV601 anchor
def test_mlv601_anchors_on_the_ranked_primary_entrypoint():
    doc = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline"))
    issue = _of(doc, "MLV601")[0]
    primary = doc["workspace"]["entrypoints"][0]
    assert primary == "train.py"
    assert issue["loc"]["file"] == primary, (
        "the seed finding must not land on whatever file sorts first")


# --------------------------------------------- MLA-10: the MLV702 message
def test_mlv702_does_not_claim_a_comprehension_holds_one_submodule():
    doc = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline"))
    message = _of(doc, "MLV702")[0]["message"]
    assert "list comprehension" in message
    assert "1 submodule(s)" not in message, message
    assert "ConvBlock" in message
