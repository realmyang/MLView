"""Loop classification, gradient contexts and dynamic-scope marking."""

from __future__ import annotations

import pytest

LOOPS_SRC = """
import torch
import torch.nn as nn
from sklearn.model_selection import KFold
from torch.utils.data import DataLoader


def run(ds, X, y, epochs=10):
    train_loader = DataLoader(ds, batch_size=8)
    for epoch in range(epochs):
        for images, labels in train_loader:
            pass
    kf = KFold(n_splits=5)
    for train_idx, test_idx in kf.split(X):
        pass
    for item in [1, 2, 3]:
        pass
    for batch in train_loader:
        pass
"""

NOGRAD_SRC = """
import torch


@torch.no_grad()
def decorated(model, batch):
    return model(batch)


def with_block(model, batch):
    with torch.no_grad():
        a = model(batch)
    b = model(batch)
    with torch.no_grad():
        with torch.enable_grad():
            c = model(batch)
    return a, b, c


def amp(model, batch):
    with torch.autocast(device_type="cuda"):
        return model(batch)
"""


def loops_by_line(module):
    return {loop.loc.line: loop for loop in module.loops}


@pytest.fixture
def loops_module(analyze_ir):
    return analyze_ir({"m.py": LOOPS_SRC}).workspace.modules["m.py"]


def test_epoch_loop(loops_module):
    loops = loops_by_line(loops_module)
    epoch = loops[10]
    assert epoch.kind == "epoch"
    assert epoch.depth == 1


def test_batch_loop_is_nested(loops_module):
    loops = loops_by_line(loops_module)
    batch = loops[11]
    assert batch.kind == "batch"
    assert batch.depth == 2
    assert batch.parent_loop is loops[10]
    assert batch.iterates is not None and batch.iterates.has("LOADER")


def test_fold_loop(loops_module):
    assert loops_by_line(loops_module)[14].kind == "fold"


def test_plain_loop_is_other(loops_module):
    assert loops_by_line(loops_module)[16].kind == "other"


def test_loader_loop_without_epoch(loops_module):
    batch = loops_by_line(loops_module)[18]
    assert batch.kind == "batch"
    assert batch.depth == 1


def test_loop_qualnames_are_unique(loops_module):
    names = [loop.qualname for loop in loops_module.loops]
    assert len(names) == len(set(names))
    assert "m.run.batch_loop" in names


@pytest.fixture
def nograd_module(analyze_ir):
    return analyze_ir({"m.py": NOGRAD_SRC}).workspace.modules["m.py"]


def calls_by_line(module):
    return {call.loc.line: call for call in module.calls}


def test_no_grad_decorator(nograd_module):
    call = calls_by_line(nograd_module)[7]
    assert call.inside_no_grad


def test_no_grad_with_block(nograd_module):
    calls = calls_by_line(nograd_module)
    assert calls[12].inside_no_grad          # inside `with torch.no_grad()`
    assert not calls[13].inside_no_grad      # after the block


def test_enable_grad_negates_no_grad(nograd_module):
    assert not calls_by_line(nograd_module)[16].inside_no_grad


def test_autocast_context(nograd_module):
    assert calls_by_line(nograd_module)[22].inside_autocast


def test_dynamic_scope_getattr(analyze_ir):
    src = ("import torch.nn as nn\n"
           "def build(cfg, registry):\n"
           "    cls = getattr(registry, cfg.name)\n"
           "    return cls()\n")
    result = analyze_ir({"m.py": src})
    scope = [s for s in result.workspace.modules["m.py"].scopes if s.qualname == "m.build"][0]
    assert scope.dynamic
    assert any("getattr" in reason for reason in scope.reasons)
    doc = result.graph.to_dict()
    assert any(d["kind"] == "dynamic_scope" for d in doc["diagnostics"])
    assert any(n["dynamic"] for n in doc["nodes"])


def test_dynamic_scope_exec(analyze_ir):
    src = "def run(code):\n    exec(code)\n"
    scope = [s for s in analyze_ir({"m.py": src}).workspace.modules["m.py"].scopes
             if s.qualname == "m.run"][0]
    assert scope.dynamic


def test_kwargs_forwarding_marks_dynamic(analyze_ir):
    src = ("from torch.utils.data import DataLoader\n"
           "def build(ds, **kwargs):\n"
           "    return DataLoader(ds, **kwargs)\n")
    scope = [s for s in analyze_ir({"m.py": src}).workspace.modules["m.py"].scopes
             if s.qualname == "m.build"][0]
    assert scope.dynamic


def test_main_guard_and_entrypoint(analyze_ir):
    src = ("import torch\n"
           "def main():\n"
           "    torch.manual_seed(0)\n"
           "if __name__ == '__main__':\n"
           "    main()\n")
    result = analyze_ir({"train.py": src})
    module = result.workspace.modules["train.py"]
    assert module.main_guard is not None
    doc = result.graph.to_dict()
    assert "train.py" in doc["workspace"]["entrypoints"]
    assert any(n["kind"] == "entrypoint" for n in doc["nodes"])


RANGE_SRC = """
import torch


def run(parts, head, n, model, optimizer, criterion, x, y):
    for i in range(10):
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
    for j in range(0, 100, 5):
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
    for k in range(1, len(parts)):
        pass
    for m in range(len(head), 0, -1):
        pass
    for n_epochs in range(n):
        pass
    for epoch in range(n):
        pass
    for t in range(100):
        parts.append(t * 0.01)
"""


@pytest.fixture
def range_module(analyze_ir):
    return analyze_ir({"m.py": RANGE_SRC}).workspace.modules["m.py"]


def test_a_fully_literal_range_is_an_epoch_loop(range_module):
    """A literal count plus ML content in the body (PUB2-07).

    "The count is a literal" used to be the whole test, and it admitted every
    plotting, timing and lookup-table loop in Python: measured over the 37-repo
    public corpus, 739 of 4898 train/eval loop nodes (15.1%) were `for i in
    range(1000)` around a `%timeit`, `for i in range(1, 7)` building matplotlib
    axes, or `for i in range(256)` filling an autoaugment table - and on
    tensorflow/models the ONLY node in the whole train lane of a 398-node
    diagram was a loop appending 100 float thresholds to a protobuf config.
    """
    loops = loops_by_line(range_module)
    assert loops[6].kind == "epoch"      # range(10), with a training step
    assert loops[10].kind == "epoch"     # range(0, 100, 5), with a training step


def test_a_literal_range_with_no_ml_content_is_not_an_epoch_loop(range_module):
    """PUB2-07: the config / plotting / lookup-table loop. `range(100)` around
    `parts.append(t * 0.01)` is not a training loop, and drawing it as one
    declared the `train` stage present and armed MLV601 off it."""
    loops = loops_by_line(range_module)
    assert loops[22].kind == "other"     # range(100) appending floats


def test_a_partly_literal_range_is_index_arithmetic_not_an_epoch(range_module):
    """`range(1, len(parts))` has a literal bound but counts nothing epoch-ish."""
    loops = loops_by_line(range_module)
    assert loops[14].kind == "other"     # range(1, len(parts))
    assert loops[16].kind == "other"     # range(len(head), 0, -1)


def test_an_epoch_named_argument_or_target_still_wins(range_module):
    """The two real epoch signals are unconditional: they are evidence about
    the loop, not about the shape of its bound."""
    loops = loops_by_line(range_module)
    assert loops[18].kind == "epoch"     # target n_epochs
    assert loops[20].kind == "epoch"     # target epoch
