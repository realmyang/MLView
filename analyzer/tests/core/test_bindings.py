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
