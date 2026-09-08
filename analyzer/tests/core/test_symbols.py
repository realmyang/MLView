"""Import-alias resolution to canonical FQNs (`ir/symbols.py`)."""

from __future__ import annotations

import ast

import pytest

from mlview.ir.symbols import build_symbol_table, dotted_name, dotted_text

CASES = [
    ("import torch", "torch", "torch"),
    ("import torch.nn as nn", "nn.Linear", "torch.nn.Linear"),
    ("import torch.nn.functional as F", "F.softmax", "torch.nn.functional.softmax"),
    ("import torch.nn", "torch.nn.Conv2d", "torch.nn.Conv2d"),
    ("import numpy as np", "np.random.seed", "numpy.random.seed"),
    ("from torch import nn", "nn.Module", "torch.nn.Module"),
    ("from torch import nn as tnn", "tnn.Module", "torch.nn.Module"),
    ("from sklearn.model_selection import train_test_split", "train_test_split",
     "sklearn.model_selection.train_test_split"),
    ("from sklearn.preprocessing import StandardScaler as SS", "SS",
     "sklearn.preprocessing.StandardScaler"),
    ("from torch.utils.data import DataLoader", "DataLoader",
     "torch.utils.data.DataLoader"),
    ("import torch.optim as optim", "optim.Adam", "torch.optim.Adam"),
    ("from torch.optim import lr_scheduler", "lr_scheduler.StepLR",
     "torch.optim.lr_scheduler.StepLR"),
    ("import pytorch_lightning as pl", "pl.Trainer", "pytorch_lightning.Trainer"),
    ("from transformers import Trainer", "Trainer", "transformers.Trainer"),
    ("import torchvision.transforms as T", "T.ToTensor", "torchvision.transforms.ToTensor"),
]


def _resolve(source: str, expression: str, dotted: str = "pkg.mod",
             workspace=("pkg.mod", "pkg.models", "pkg", "models", "data")):
    tree = ast.parse(source)
    table = build_symbol_table(tree, dotted, workspace)
    node = ast.parse(expression, mode="eval").body
    return table.resolve(node)


@pytest.mark.parametrize("source,expression,expected", CASES)
def test_alias_resolution(source, expression, expected):
    assert _resolve(source, expression) == expected


def test_unknown_name_never_resolves():
    """No rule may match a bare attribute name."""
    assert _resolve("import torch", "model.eval") is None
    assert _resolve("import torch", "scaler.fit_transform") is None


def test_relative_import_of_workspace_module():
    assert _resolve("from .models import Net", "Net", dotted="pkg.train") == "pkg.models.Net"
    assert _resolve("from . import data", "data.load", dotted="pkg.train") == "pkg.data.load"


def test_absolute_workspace_import():
    fqn = _resolve("from models import Net", "Net", dotted="train")
    assert fqn == "models.Net"


def test_two_level_relative_import():
    fqn = _resolve("from ..shared import util", "util.f", dotted="pkg.sub.mod")
    assert fqn == "pkg.shared.util.f"


def test_star_import_is_recorded():
    tree = ast.parse("from torch.nn import *")
    table = build_symbol_table(tree, "m", ())
    assert table.star_imports == ["torch.nn"]


def test_frameworks_from_imports():
    tree = ast.parse("import torch\nimport sklearn.metrics\nimport json\n")
    table = build_symbol_table(tree, "m", ())
    assert set(table.frameworks) == {"torch", "sklearn"}


def test_dotted_helpers():
    node = ast.parse("a.b.c(1)", mode="eval").body
    assert dotted_text(node) == "a.b.c"
    assert dotted_name(node.func) == "a.b.c"
    assert dotted_name(ast.parse("f()[0]", mode="eval").body) is None


def test_star_import_marks_scope_dynamic(analyze_ir):
    result = analyze_ir({"m.py": "from torch.nn import *\nx = Linear(2, 2)\n"})
    module = result.workspace.modules["m.py"]
    assert module.module_scope.is_dynamic
    kinds = {d.kind for d in result.graph.diagnostics}
    assert "dynamic_scope" in kinds
