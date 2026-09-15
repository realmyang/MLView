"""The Consolidate review's confirmed analyzer findings, one test each.

REC-02  MLV205's widening to "any accumulating loop" accused correct code:
        a no-grad validation loop, an accumulator one arithmetic step from the
        tensor the program back-propagates, and a loss module's own `forward`.
REC-03  R13 / R15 read a `return` only when it bound a name first, so
        `return scaler.fit_transform(frame)` - the idiomatic spelling - missed
        while `out = ...; return out` hit.
REC-04  GRAPH-R3's dict / dataclass carriage stopped at the scope that wrote
        the literal, so the GradScaler-in-a-parameter-dict the campaign named
        was invisible however far the summaries travelled.
REC-07  a per-batch list joined by `np.concatenate` dropped the LOGITS / PROBS
        tag, which is the dominant real-world spelling of MLV305's defect.
REC-09  `_EVAL_NAME_RE` read every pytest function as an evaluation entrypoint,
        so a test suite drew high-severity MLV301s.

Every one of them is measured on the 37-clone public corpus as well; the
numbers are in `docs/ACCURACY.md` section 8.
"""

from __future__ import annotations

import os

import pytest

from rule_harness import RULE_FIXTURES, analyze_paths, describe, write_workspace


def _codes(doc, code):
    return [i for i in doc["issues"] if i["code"] == code]


def _fixture(name):
    return analyze_paths(os.path.join(RULE_FIXTURES, name))


# ----------------------------------------------------------------- REC-02
_NO_GRAD = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def validate(model, criterion, dataset: TensorDataset):
    loader = DataLoader(dataset, batch_size=8, shuffle=False)
    model.eval()
    running_vloss = 0.0
    with torch.no_grad():
        for features, labels in loader:
            running_vloss += criterion(model(features), labels)
    return running_vloss
'''


def test_mlv205_is_silent_under_no_grad(tmp_path):
    """REC-02(1): a no-grad loop has no autograd graph to keep alive."""
    root = write_workspace(str(tmp_path), {"a.py": _NO_GRAD})
    doc = analyze_paths(root)
    assert _codes(doc, "MLV205") == [], describe(doc)


def test_mlv205_is_silent_when_the_total_is_backwarded_one_step_later():
    """REC-02(2): `total = content + style; total.backward()`."""
    doc = _fixture("MLV205_backwarded_good.py")
    assert _codes(doc, "MLV205") == [], describe(doc)


def test_mlv205_is_silent_when_the_collected_loss_is_returned():
    """REC-02(3): a loss module's `forward` must keep every graph it collects."""
    doc = _fixture("MLV205_returned_good.py")
    assert _codes(doc, "MLV205") == [], describe(doc)


def test_mlv205_still_fires_when_the_collected_loss_is_already_backwarded():
    """The discriminator: `losses.append(loss)` *after* `loss.backward()` is a
    record of the epoch, not the objective, and returning it is the defect."""
    doc = _fixture("MLV205_bad.py")
    assert _codes(doc, "MLV205"), describe(doc)


# ----------------------------------------------------------------- REC-03
def test_mlv101_reads_a_bare_returned_call():
    """REC-03: `return scaler.fit_transform(frame)` is the same leak as the
    two-line spelling `matrix = scaler.fit_transform(frame); return matrix`."""
    doc = _fixture("MLV101_return_call_bad.py")
    found = _codes(doc, "MLV101")
    assert len(found) == 1, describe(doc)
    assert found[0]["severity"] == "high"


def test_mlv103_reads_a_bare_returned_call():
    """REC-03, the R15 half: `return pca.fit_transform(X)`."""
    doc = _fixture("MLV103_return_call_bad.py")
    assert len(_codes(doc, "MLV103")) == 1, describe(doc)


def test_both_spellings_of_the_same_helper_agree():
    """The two fixtures differ by one refactoring and must not diverge again."""
    bound = _fixture("MLV101_bad.py")
    inline = _fixture("MLV101_return_call_bad.py")
    assert len(_codes(bound, "MLV101")) == len(_codes(inline, "MLV101")) == 1


# ----------------------------------------------------------------- REC-04
_FACTORY_DICT = '''import torch
import torch.nn as nn
import torch.optim as optim
from torch.amp import GradScaler, autocast
from torch.utils.data import DataLoader, TensorDataset


def make_state():
    model = nn.Linear(10, 3)
    return {"scaler": GradScaler("cpu"), "model": model,
            "criterion": nn.CrossEntropyLoss(),
            "optimizer": optim.SGD(model.parameters(), lr=0.01)}


def train(state, dataset: TensorDataset):
    loader = DataLoader(dataset, batch_size=8, shuffle=True)
    scaler = state["scaler"]
    model = state["model"]
    criterion = state["criterion"]
    optimizer = state["optimizer"]
    for features, labels in loader:
        optimizer.zero_grad()
        with autocast("cpu"):
            loss = criterion(model(features), labels)
        loss.backward()
        scaler.step(optimizer)
        scaler.update()
    return model


def main(x, y):
    torch.manual_seed(0)
    train(make_state(), TensorDataset(x, y))
'''

_TWO_DICTS = _FACTORY_DICT + '''

def other(x, y):
    train({"scaler": None, "model": None, "criterion": None, "optimizer": None},
          TensorDataset(x, y))
'''


def test_a_container_travels_through_a_return_and_a_parameter(tmp_path):
    """REC-04: the GradScaler carried in a parameter dict, the named case."""
    root = write_workspace(str(tmp_path), {"a.py": _FACTORY_DICT})
    doc = analyze_paths(root)
    assert _codes(doc, "MLV208"), describe(doc)
    gaps = [d for d in doc["diagnostics"] if d["kind"] == "unresolved_callee"]
    assert gaps == [], "the objects in the dict resolved, so nothing is a gap"


def test_two_call_sites_with_two_different_dicts_carry_nothing(tmp_path):
    """The negative twin: intersection over call sites, never union. A second
    site passing a different literal means the parameter inherits none."""
    root = write_workspace(str(tmp_path), {"a.py": _TWO_DICTS})
    doc = analyze_paths(root)
    assert _codes(doc, "MLV208") == [], describe(doc)


def test_local_mode_still_reads_a_container_in_its_own_scope(tmp_path):
    """Carriage inside one scope is what GRAPH-R3 shipped and is unchanged."""
    root = write_workspace(str(tmp_path), {"a.py": _FACTORY_DICT.replace(
        "def train(state, dataset: TensorDataset):",
        "def train(dataset: TensorDataset):\n    state = make_state()").replace(
        "train(make_state(), TensorDataset(x, y))", "train(TensorDataset(x, y))")})
    for mode in ("local", "ip"):
        doc = analyze_paths(root, dataflow=mode)
        assert _codes(doc, "MLV208"), "%s: %s" % (mode, describe(doc))


# ----------------------------------------------------------------- REC-07
def test_mlv305_follows_a_per_batch_list_through_np_concatenate():
    doc = _fixture("MLV305_batched_bad.py")
    assert len(_codes(doc, "MLV305")) == 1, describe(doc)


def test_the_collector_hop_intersects_rather_than_unions():
    doc = _fixture("MLV305_batched_good.py")
    assert _codes(doc, "MLV305") == [], describe(doc)


# ----------------------------------------------------------------- REC-09
@pytest.mark.parametrize("code", ["MLV301", "MLV302"])
def test_a_pytest_module_is_not_an_evaluation_region(code):
    doc = _fixture("MLV301_pytest_good.py")
    assert _codes(doc, code) == [], describe(doc)


def test_a_test_named_file_that_trains_is_still_judged(tmp_path):
    """The guard needs *both* halves: a test-shaped module and a test-shaped
    region. A training loop written in a file called `test_pipeline.py` is
    still a training loop, and MLV301 has nothing to say about it either way -
    what must survive is the rest of the analysis."""
    source = ('import torch\n'
              'import torch.nn as nn\n'
              'import torch.optim as optim\n'
              'from torch.utils.data import DataLoader, TensorDataset\n\n\n'
              'def build_and_train(dataset: TensorDataset):\n'
              '    model = nn.Linear(4, 2)\n'
              '    crit = nn.CrossEntropyLoss()\n'
              '    opt = optim.Adam(model.parameters())\n'
              '    loader = DataLoader(dataset, batch_size=8)\n'
              '    for x, y in loader:\n'
              '        loss = crit(model(x), y)\n'
              '        loss.backward()\n'
              '        opt.step()\n'
              '    return model\n')
    root = write_workspace(str(tmp_path), {"test_pipeline.py": source})
    doc = analyze_paths(root)
    assert _codes(doc, "MLV201"), describe(doc)      # zero_grad is still missing
