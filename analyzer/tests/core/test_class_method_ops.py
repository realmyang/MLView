"""ANA-1: ops written inside a class method become nodes under the class unit.

`CallSite.class_ir` used to carry two different facts. `ir/scopes.py` set it to
the class a call is *written in*; `ir/resolve.py` overwrote it with the class a
call *resolves to*. `core/build.py:_create_op` reads the second meaning and
returned early on the first, so every `nn.Conv2d(...)` in a `__init__`, every
`StandardScaler().fit_transform(...)` in a `setup()` and every loader built in
a `DataModule` was silently dropped: the flagship demo's Model lane contained
no layers at all.

The two facts are now two fields - `class_ir` (resolution, written only by
`ir/resolve.py`) and `enclosing_class` (lexical, written only by
`ir/scopes.py`) - and `_owning_unit` parents the op onto the class unit, or
onto a method-level loop unit when one exists.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict

SAMPLE = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
CLEAN_TWIN = os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean")
CLEAN_CORPUS = os.path.join(REPO_ROOT, "analyzer", "tests", "clean")


@pytest.fixture(scope="module")
def demo():
    return analyze_to_dict(AnalyzeOptions(paths=(SAMPLE,)))


def _by_id(doc):
    return {n["id"]: n for n in doc["nodes"]}


def _in_file(doc, relpath):
    return [n for n in doc["nodes"] if n["loc"]["file"] == relpath]


# ------------------------------------------------------- the demo's model lane
def test_the_model_file_contributes_more_than_its_two_class_nodes(demo):
    """Before ANA-1 `model.py` produced exactly two nodes: the two classes."""
    nodes = _in_file(demo, "model.py")
    units = [n for n in nodes if n["level"] == "unit"]
    ops = [n for n in nodes if n["level"] == "op"]
    assert len(units) == 2, [n["label"] for n in units]
    assert len(ops) >= 9, [n["label"] for n in ops]


def test_every_layer_built_in___init___is_an_op_under_its_class(demo):
    """`self.conv = nn.Conv2d(...)` is an op node parented to `ConvBlock`."""
    by_id = _by_id(demo)
    owners = {}
    for node in _in_file(demo, "model.py"):
        if node["level"] != "op":
            continue
        parent = by_id.get(node["parent"] or "")
        assert parent is not None, "%s has no parent unit" % node["label"]
        owners.setdefault(parent["label"], set()).add(node["fqn"])
    assert {"torch.nn.Conv2d", "torch.nn.BatchNorm2d", "torch.nn.Dropout"} <= \
        owners.get("ConvBlock", set()), owners
    assert {"torch.nn.Conv2d", "torch.nn.AdaptiveAvgPool2d", "torch.nn.Linear"} <= \
        owners.get("SmallCNN", set()), owners


def test_the_model_lane_is_no_longer_three_nodes(demo):
    lane = [n for n in demo["nodes"] if n["stage"] == "model"]
    assert len(lane) >= 10, [n["label"] for n in lane]


def test_the_class_unit_still_sits_above_its_ops(demo):
    """Invariant 1.1: a parent is at a strictly lower level than its child."""
    order = {"stage": 0, "unit": 1, "op": 2}
    by_id = _by_id(demo)
    for node in demo["nodes"]:
        parent = by_id.get(node["parent"] or "")
        if parent is None:
            continue
        assert order[parent["level"]] < order[node["level"]], \
            "%s (%s) under %s (%s)" % (node["label"], node["level"],
                                       parent["label"], parent["level"])


def test_the_demo_document_is_still_contract_valid(demo):
    assert validate(demo) == []


# ------------------------------------------------------------- the two meanings
def test_class_ir_is_the_resolution_and_enclosing_class_is_the_lexical_one(make_workspace):
    root = make_workspace({"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "class Block(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.conv = nn.Conv2d(3, 8, 3)\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.block = Block()\n"
    )})
    module = analyze_full(AnalyzeOptions(paths=(root,))).workspace.modules["m.py"]
    conv = next(c for c in module.calls if c.short_name == "Conv2d")
    assert conv.class_ir is None, "Conv2d resolves to no workspace class"
    assert conv.enclosing_class is not None and conv.enclosing_class.name == "Block"

    block = next(c for c in module.calls if c.short_name == "Block")
    assert block.class_ir is not None and block.class_ir.name == "Block", \
        "a call that constructs a workspace class keeps the resolution meaning"
    assert block.enclosing_class is not None and block.enclosing_class.name == "Net"


def test_a_call_that_constructs_a_workspace_class_maps_onto_its_unit(make_workspace):
    """The early return survives - for its *real* meaning only."""
    root = make_workspace({"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "class Block(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.conv = nn.Conv2d(3, 8, 3)\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.block = Block()\n"
    )})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    labels = [n["label"] for n in doc["nodes"]]
    assert labels.count("Block") == 1, "no second node for the Block() call site"
    assert any(e["kind"] == "call" for e in doc["edges"]), \
        "Net's __init__ still draws a call edge into Block"


def test_an_op_inside_a_method_loop_hangs_off_the_loop_unit(make_workspace):
    """`_owning_unit` prefers the innermost loop unit over the class unit."""
    root = make_workspace({"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "import torch.optim as optim\n"
        "\n"
        "class Runner:\n"
        "    def __init__(self, model: nn.Module, loader):\n"
        "        self.model = model\n"
        "        self.loader = loader\n"
        "        self.optimizer = optim.SGD(model.parameters(), lr=0.1)\n"
        "\n"
        "    def run(self, epochs: int = 3):\n"
        "        for epoch in range(epochs):\n"
        "            for batch, target in self.loader:\n"
        "                self.optimizer.zero_grad()\n"
        "                self.optimizer.step()\n"
    )})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    by_id = _by_id(doc)
    zero_grad = next(n for n in doc["nodes"] if n["label"] == "zero_grad()")
    parent = by_id[zero_grad["parent"]]
    assert parent["kind"] in ("train_loop", "eval_loop"), parent
    assert parent["attrs"]["loopKind"] == "batch"
    grandparent = by_id[parent["parent"]]
    assert grandparent["kind"] in ("train_loop", "eval_loop", "class"), grandparent


def test_a_module_level_unit_still_excludes_calls_written_in_a_class(make_workspace):
    """`_unit_flags` reads the *lexical* class, so the entrypoint's own vote is
    not polluted by a method body."""
    root = make_workspace({"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n"
        "\n"
        "net = Net()\n"
    )})
    result = analyze_full(AnalyzeOptions(paths=(root,)))
    module = result.workspace.modules["m.py"]
    module_level = [c for c in module.calls
                    if c.function is None and c.enclosing_class is None]
    assert [c.short_name for c in module_level] == ["Net"]


# ------------------------------------------------------------------ determinism
def test_the_new_class_owned_ops_have_stable_content_addressed_ids():
    first = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE,)))
    second = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE,)))
    assert [n["id"] for n in first["nodes"]] == [n["id"] for n in second["nodes"]]
    ids = [n["id"] for n in first["nodes"] if n["loc"]["file"] == "model.py"]
    assert len(ids) == len(set(ids)), "no duplicate ids among the class-owned ops"


# --------------------------------------------------------- the clean corpora
@pytest.mark.parametrize("root", [CLEAN_TWIN, CLEAN_CORPUS],
                         ids=["vision_pipeline_clean", "tests/clean"])
def test_seeing_inside_classes_adds_no_finding_to_correct_code(root):
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    high = [i for i in doc["issues"] if i["severity"] == "high"]
    assert high == [], [(i["code"], i["loc"]["file"], i["loc"]["line"]) for i in high]
