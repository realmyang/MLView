"""Adversarial-but-valid Python: no rule may raise, and none may guess wildly.

A rule that throws becomes a `rule_error` diagnostic rather than a crash, which
means a broken rule is *invisible* in normal use. These tests run every rule
over deliberately awkward code with `strict=True` in spirit - by asserting the
diagnostic channel is empty - so a regression surfaces here instead of as
silence in the field.
"""

from __future__ import annotations

import pytest

from mlview.api import AnalyzeOptions, analyze_full
from rule_harness import analyze_paths, describe, write_workspace

AWKWARD = {
    "empty.py": "",
    "docstring_only.py": '"""Nothing but a docstring."""\n',
    "imports_only.py": "import torch\nimport torch.nn as nn\n",
    "weird_class.py": (
        "import torch.nn as nn\n\n\n"
        "class Empty(nn.Module):\n"
        "    pass\n\n\n"
        "class NoInit(nn.Module):\n"
        "    def forward(self, x):\n"
        "        return x\n\n\n"
        "class Nested(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.inner = {'a': [nn.Linear(1, 1)]}\n"
    ),
    "lambdas.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "make = lambda n: nn.Linear(n, n)\n"
        "chain = [(lambda x: x)(i) for i in range(3)]\n"
        "nested = {k: [make(k) for _ in range(2)] for k in (1, 2)}\n"
    ),
    "walrus.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "if (model := nn.Linear(4, 4)) is not None:\n"
        "    total = sum(p.numel() for p in model.parameters())\n"
    ),
    "star_import.py": (
        "from torch.nn import *\n"
        "layer = Linear(4, 4)\n"
    ),
    "dynamic.py": (
        "import torch.nn as nn\n\n\n"
        "def build(name, **kwargs):\n"
        "    factory = getattr(nn, name)\n"
        "    return factory(**kwargs)\n"
    ),
    "async_loop.py": (
        "import torch\n"
        "import torch.nn as nn\n\n\n"
        "async def train(loader, model: nn.Module, optimizer):\n"
        "    async for images, labels in loader:\n"
        "        optimizer.zero_grad()\n"
        "        loss = model(images).sum()\n"
        "        loss.backward()\n"
        "        optimizer.step()\n"
    ),
    "deep_chain.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "x = nn.Sequential(nn.Linear(2, 2)).to('cpu').eval().train().cpu()\n"
    ),
    "recursive.py": (
        "import torch.nn as nn\n\n\n"
        "class Rec(nn.Module):\n"
        "    def __init__(self, depth=0):\n"
        "        super().__init__()\n"
        "        self.child = Rec(depth - 1) if depth else None\n"
    ),
    "shadowed.py": (
        "import torch\n"
        "torch = 5\n"
        "nn = torch\n"
    ),
    "unicode_names.py": (
        "import torch.nn as nn\n"
        "modèle = nn.Linear(3, 3)\n"
        "レイヤ = [nn.Linear(1, 1)]\n"
    ),
    "no_args.py": (
        "import torch\n"
        "from torch.utils.data import DataLoader\n"
        "loader = DataLoader()\n"
        "split = torch.utils.data.random_split()\n"
    ),
}


@pytest.fixture(scope="module")
def awkward(tmp_path_factory):
    root = write_workspace(str(tmp_path_factory.mktemp("awkward")), AWKWARD)
    return analyze_paths(root)


def test_every_file_was_analyzed(awkward):
    assert awkward["workspace"]["filesAnalyzed"] == len(AWKWARD)
    assert awkward["workspace"]["filesFailed"] == 0


def test_no_rule_raised(awkward):
    errors = [d for d in awkward["diagnostics"] if d["kind"] == "rule_error"]
    assert errors == [], errors


def test_strict_mode_does_not_re_raise_anything(tmp_path):
    """`--strict` turns a swallowed rule exception into a hard failure."""
    root = write_workspace(str(tmp_path), AWKWARD)
    result = analyze_full(AnalyzeOptions(paths=(root,), strict=True))
    assert result.graph is not None
    assert [d for d in result.graph.diagnostics if d.kind == "rule_error"] == []


def test_awkward_code_produces_no_high_severity_guesses(awkward):
    """None of this is a defect - it is just hard to read."""
    high = [i for i in awkward["issues"] if i["severity"] == "high"]
    assert high == [], describe(awkward)


def test_a_dynamic_scope_is_reported_not_hidden(awkward):
    kinds = {d["kind"] for d in awkward["diagnostics"]}
    assert "dynamic_scope" in kinds, awkward["diagnostics"]


@pytest.mark.parametrize("name", sorted(AWKWARD))
def test_each_file_alone_is_survivable(name, tmp_path):
    root = write_workspace(str(tmp_path), {name: AWKWARD[name]})
    result = analyze_full(AnalyzeOptions(paths=(root,), strict=True))
    assert [d for d in result.graph.diagnostics if d.kind == "rule_error"] == []


def test_a_syntax_error_next_door_does_not_stop_the_rules(tmp_path):
    root = write_workspace(str(tmp_path), {
        "broken.py": "def f(:\n    pass\n",
        "train.py": (
            "import torch\n"
            "import torch.nn as nn\n"
            "import torch.optim as optim\n"
            "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
            "def train(dataset: TensorDataset) -> None:\n"
            "    torch.manual_seed(0)\n"
            "    model = nn.Sequential(nn.Linear(10, 3))\n"
            "    criterion = nn.CrossEntropyLoss()\n"
            "    optimizer = optim.Adam(model.parameters(), lr=0.001)\n"
            "    loader = DataLoader(dataset, batch_size=8, shuffle=True)\n"
            "    for features, labels in loader:\n"
            "        loss = criterion(model(features), labels)\n"
            "        loss.backward()\n"
            "        optimizer.step()\n"),
    })
    doc = analyze_paths(root)
    assert doc["workspace"]["filesFailed"] == 1
    assert any(d["kind"] == "parse_error" for d in doc["diagnostics"])
    assert any(i["code"] == "MLV201" for i in doc["issues"]), describe(doc)


def test_analysis_is_repeatable(awkward, tmp_path):
    root = write_workspace(str(tmp_path), AWKWARD)
    first = analyze_paths(root)
    second = analyze_paths(root)
    for doc in (first, second):
        doc["generator"].pop("generatedAt")
        doc["stats"].pop("durationMs")
    assert first == second
