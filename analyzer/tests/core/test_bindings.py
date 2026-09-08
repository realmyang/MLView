"""Binding tracking, value tags and receiver resolution (`ir/bindings.py`)."""

from __future__ import annotations

import pytest

from mlview.ir.bindings import binding_of

SPLIT_SRC = """
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

raw = np.load("d.npz")
X = raw["x"]
y = raw["y"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
"""

TORCH_SRC = """
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(4, 2)

    def forward(self, x):
        return self.fc(x)


def train(ds):
    device = torch.device("cuda")
    model = Net().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters())
    loader = DataLoader(ds, batch_size=8)
    for images, labels in loader:
        out = model(images)
        loss = criterion(out, labels)
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
"""


def scope_of(module, qualname):
    for scope in module.scopes:
        if scope.qualname == qualname:
            return scope
    raise AssertionError("no scope %s" % qualname)


@pytest.fixture
def split_module(analyze_ir):
    result = analyze_ir({"m.py": SPLIT_SRC})
    return result.workspace.modules["m.py"]


@pytest.fixture
def torch_module(analyze_ir):
    result = analyze_ir({"m.py": TORCH_SRC})
    return result.workspace.modules["m.py"]


def test_train_test_split_four_way_convention(split_module):
    scope = scope_of(split_module, "m")
    assert "TRAIN_SPLIT" in binding_of("X_train", scope).tags
    assert "FEATURES" in binding_of("X_train", scope).tags
    assert "TEST_SPLIT" in binding_of("X_test", scope).tags
    assert "TARGET" in binding_of("y_train", scope).tags
    assert "TRAIN_SPLIT" in binding_of("y_train", scope).tags
    assert "TEST_SPLIT" in binding_of("y_test", scope).tags


def test_raw_data_and_feature_tags(split_module):
    scope = scope_of(split_module, "m")
    assert binding_of("raw", scope).has("RAW_DATA")
    assert binding_of("X", scope).has("FEATURES")
    assert binding_of("y", scope).has("TARGET")


def test_fitted_transformer_tag(split_module):
    scope = scope_of(split_module, "m")
    assert binding_of("scaler", scope).has("FITTED_TRANSFORMER")
    assert binding_of("X_train_s", scope).has("TRAIN_SPLIT")


def test_estimator_method_resolves_to_base(split_module):
    fit = [c for c in split_module.calls if c.method == "fit_transform"][0]
    assert "sklearn.base.BaseEstimator.fit_transform" in fit.canonical_fqns
    assert "sklearn.preprocessing.StandardScaler.fit_transform" in fit.canonical_fqns


def test_torch_value_tags(torch_module):
    scope = scope_of(torch_module, "m.train")
    assert binding_of("device", scope).has("DEVICE")
    assert binding_of("model", scope).has("MODEL")
    assert binding_of("criterion", scope).has("LOSS")
    assert binding_of("optimizer", scope).has("OPTIMIZER")
    assert binding_of("loader", scope).has("LOADER")
    assert binding_of("out", scope).has("LOGITS")
    assert binding_of("loss", scope).has("LOSS")
    assert binding_of("images", scope).has("BATCH")


def test_receiver_families(torch_module):
    by_method = {}
    for call in torch_module.calls:
        if call.method:
            by_method.setdefault(call.method, []).append(call)
    assert "torch.optim.Optimizer.step" in by_method["step"][0].canonical_fqns
    assert "torch.optim.Optimizer.zero_grad" in by_method["zero_grad"][0].canonical_fqns
    assert "torch.Tensor.backward" in by_method["backward"][0].canonical_fqns
    assert "torch.nn.Module.parameters" in by_method["parameters"][0].canonical_fqns
    assert "torch.nn.Module.to" in by_method["to"][0].canonical_fqns


def test_workspace_class_is_an_nn_module(torch_module):
    net = torch_module.classes["m.Net"]
    assert net.is_nn_module
    assert "torch.nn.Module" in net.resolved_bases


def test_self_attribute_binding(torch_module):
    cls_scope = scope_of(torch_module, "m.Net")
    ref = binding_of("self.fc", cls_scope)
    assert ref is not None and ref.producer is not None
    assert ref.producer.fqn == "torch.nn.Linear"


def test_tuple_unpacking_of_random_split(analyze_ir):
    src = ("import torch\n"
           "from torch.utils.data import random_split\n"
           "train_ds, val_ds = random_split(ds, [45000, 5000])\n")
    module = analyze_ir({"m.py": src}).workspace.modules["m.py"]
    scope = scope_of(module, "m")
    assert binding_of("train_ds", scope).has("TRAIN_SPLIT")
    assert binding_of("val_ds", scope).has("VAL_SPLIT")


def test_augmented_assignment_keeps_tags(analyze_ir):
    src = ("import torch\n"
           "import torch.nn as nn\n"
           "criterion = nn.MSELoss()\n"
           "total = 0.0\n"
           "loss = criterion(a, b)\n"
           "total += loss\n")
    module = analyze_ir({"m.py": src}).workspace.modules["m.py"]
    scope = scope_of(module, "m")
    assert binding_of("total", scope).has("LOSS")


def test_walrus_and_with_bindings(analyze_ir):
    src = ("import torch\n"
           "with torch.no_grad() as ctx:\n"
           "    pass\n"
           "if (n := torch.device('cpu')) is not None:\n"
           "    pass\n")
    module = analyze_ir({"m.py": src}).workspace.modules["m.py"]
    scope = scope_of(module, "m")
    assert binding_of("ctx", scope) is not None
    assert binding_of("n", scope).has("DEVICE")


def test_cross_file_class_instantiation(analyze_ir):
    files = {
        "models/net.py": ("import torch.nn as nn\n\n\n"
                          "class Net(nn.Module):\n"
                          "    def forward(self, x):\n"
                          "        return x\n"),
        "train.py": ("from models.net import Net\n"
                     "model = Net()\n"
                     "model.eval()\n"),
    }
    result = analyze_ir(files)
    module = result.workspace.modules["train.py"]
    scope = scope_of(module, "train")
    ref = binding_of("model", scope)
    assert ref.has("MODEL")
    assert ref.class_ir is not None and ref.class_ir.name == "Net"
    call = [c for c in module.calls if c.method == "eval"][0]
    assert "torch.nn.Module.eval" in call.canonical_fqns


# ------------------------------------------------- REV-01: rebound names
#: `x = layer(x)` three times in one `forward` - the universal PyTorch idiom.
#: The flat `name -> one ValueRef` map kept only the LAST store, so the
#: consumer at line 13 was wired to the producer at line 15 and the emitted
#: graph drew the last layer feeding the first two.
REBOUND_SRC = """
import torch.nn as nn
import torch.nn.functional as F


class Seq(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.a = nn.Linear(8, 16)
        self.b = nn.Linear(16, 32)
        self.c = nn.Linear(32, 2)

    def forward(self, x):
        x = F.relu(self.a(x))
        x = F.relu(self.b(x))
        x = self.c(x)
        return x
"""


def _edges(doc):
    """`(source label@line, target label@line)` for every data edge."""
    nodes = {n["id"]: n for n in doc["nodes"]}

    def name(node_id):
        node = nodes[node_id]
        return "%s@%d" % (node["label"], node["loc"]["line"])

    return sorted((name(e["source"]), name(e["target"]))
                  for e in doc["edges"] if e["kind"] == "data")


def test_a_rebound_name_resolves_to_the_store_in_effect_at_the_consumer(analyze_ir):
    module = analyze_ir({"m.py": REBOUND_SRC}).workspace.modules["m.py"]
    scope = scope_of(module, "m.Seq.forward")
    history = scope.binding_history["x"]
    assert len(history) == 3, [r.loc.line for r in history]
    lines = [r.loc.line for r in history]
    # the consumer on line 14 must see the store on line 13, not the one on 15
    assert binding_of("x", scope, at=lines[1]) is history[0]
    assert binding_of("x", scope, at=lines[2]) is history[1]
    # nothing precedes the first consumer: `x` is the parameter, not layer c
    assert binding_of("x", scope, at=lines[0]) is None
    # and the un-ordered call is byte-for-byte what it always was
    assert binding_of("x", scope) is history[-1]


def test_the_forward_chain_is_drawn_forwards(analyze_ws):
    """No edge may point from a later layer back to an earlier one."""
    doc = analyze_ws({"m.py": REBOUND_SRC})
    edges = _edges(doc)
    # the two edges the flat map lost entirely
    assert ("x@14", "self.b@10") in edges
    assert ("x@15", "self.c@11") in edges
    # the two it drew backwards: the last layer feeding the first two
    assert ("self.c@11", "self.a@9") not in edges
    assert ("self.c@11", "self.b@10") not in edges
    # and the whole forward chain, in order
    assert edges == [("self.a@9", "x@14"), ("self.b@10", "x@15"),
                     ("x@14", "self.b@10"), ("x@15", "self.c@11")]


def test_a_name_rebound_at_module_scope_has_the_same_ordering(analyze_ir):
    module = analyze_ir({"m.py": (
        "import numpy as np\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "\n"
        "raw = np.load('d.npy')\n"
        "X = raw[:, :-1]\n"
        "X = StandardScaler().fit_transform(X)\n"
    )}).workspace.modules["m.py"]
    scope = scope_of(module, "m")
    history = scope.binding_history["X"]
    assert len(history) == 2
    # `StandardScaler().fit_transform(X)` on line 6 reads the line-5 store
    assert binding_of("X", scope, at=6) is history[0]
    assert binding_of("X", scope, at=99) is history[1]


def test_a_loop_carried_rebinding_still_resolves_to_the_previous_iteration(analyze_ir):
    """`h = cell(h)` inside a loop has no store above it; the last one is right."""
    module = analyze_ir({"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "def run(cell, h, steps):\n"
        "    for _ in range(steps):\n"
        "        h = cell(h)\n"
        "    return h\n"
    )}).workspace.modules["m.py"]
    scope = scope_of(module, "m.run")
    history = scope.binding_history["h"]
    assert len(history) == 1                     # one store, so ordering is moot
    assert binding_of("h", scope, at=5) is history[0]


def test_the_self_attribute_map_is_not_reordered(analyze_ir):
    """A `self.x` store lives in the class scope and is read from methods that
    run in any order, so statement order says nothing about it."""
    module = analyze_ir({"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def forward(self, x):\n"
        "        return self.fc(x)\n"
        "\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n"
    )}).workspace.modules["m.py"]
    scope = scope_of(module, "m.Net.forward")
    # `self.fc` is stored at line 10 and read at line 6, above it
    assert binding_of("self.fc", scope, at=6) is not None


def test_the_shipped_demo_no_longer_draws_pool_into_stem():
    """The measured REV-01 instance: `samples/vision_pipeline/model.py` shipped
    `data self.pool -> self.stem`, an arrow pointing three lines backwards
    through the model, in the one lane the Model view exists to get right."""
    import os

    from core_support import REPO_ROOT
    from mlview.api import AnalyzeOptions, analyze_to_dict

    doc = analyze_to_dict(AnalyzeOptions(
        paths=(os.path.join(REPO_ROOT, "samples", "vision_pipeline"),)))
    nodes = {n["id"]: n for n in doc["nodes"]}
    pairs = {(nodes[e["source"]]["label"], nodes[e["target"]]["label"])
             for e in doc["edges"] if e["kind"] == "data"}
    assert ("self.pool", "self.stem") not in pairs
    assert ("self.stem", "x") in pairs           # stem still feeds the relu
    assert ("self.pool", "self.head") in pairs   # and pool still feeds the head
