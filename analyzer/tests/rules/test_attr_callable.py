"""ANA-2: a call through an attribute that *holds* a callable.

`ir/resolve._canonical_for_receiver` treated `self.loss_fn(logits, labels)` as
*a method named `loss_fn` on `self`*, and because `self` is an `nn.Module` it
proposed `torch.nn.Module.loss_fn` - a symbol nobody declared, which
prefix-matches to role LAYER. Two programs differing only in whether the
criterion lives in a local or on `self` therefore produced opposite answers:
`certain` MLV401 for the local, silence for the attribute.

The correct answer was already in the IR: `binding_of("self.loss_fn", scope)`
is a `ValueRef` whose producer is `torch.nn.CrossEntropyLoss`. The resolver now
consults it, and iron law 1 still holds - the candidate comes from a real
binding, never from a name.
"""

from __future__ import annotations

import pytest

from mlview.api import AnalyzeOptions, analyze_full
from rule_harness import analyze_fixture, analyze_paths, assert_fires, describe, write_workspace

FIXTURE = "MLV401_self_attr_bad"


def calls_of(root: str, relpath: str = "m.py"):
    workspace = analyze_full(AnalyzeOptions(paths=(root,))).workspace
    return workspace.modules[relpath].calls


def call_named(root: str, short_name: str, relpath: str = "m.py"):
    return next(c for c in calls_of(root, relpath) if c.short_name == short_name)


# --------------------------------------------------------------- the fixture
def test_the_self_held_criterion_fires_mlv401():
    run = assert_fires(FIXTURE)
    issue = run.of("MLV401")[0]
    assert issue["confidence"] >= 0.7, describe(run.doc)
    assert issue["severity"] == "high"


def test_the_call_resolves_to_cross_entropy_not_to_a_fabricated_module_attribute():
    run = analyze_fixture(FIXTURE)
    calls = analyze_full(AnalyzeOptions(paths=(run.path,))).workspace
    module = calls.modules["MLV401_self_attr_bad.py"]
    loss_call = next(c for c in module.calls if c.loc.line == 33 and c.method == "__call__"
                     and c.receiver_name == "self.loss_fn")
    assert "torch.nn.CrossEntropyLoss.__call__" in loss_call.canonical_fqns
    assert not any(f == "torch.nn.Module.loss_fn" for f in loss_call.canonical_fqns), \
        "the fabricated symbol must be gone"


def test_a_self_held_layer_is_a_forward_pass_not_a_new_layer():
    """`self.encoder(x)` is a call on the Linear built in `__init__`, so it
    resolves to `__call__` and never mints `torch.nn.Module.encoder`."""
    run = analyze_fixture(FIXTURE)
    module = analyze_full(AnalyzeOptions(paths=(run.path,))).workspace.modules[
        "MLV401_self_attr_bad.py"]
    forward = next(c for c in module.calls if c.receiver_name == "self.encoder")
    assert forward.canonical_fqns[0] == "torch.nn.Linear.__call__"
    assert "torch.nn.Module.encoder" not in forward.canonical_fqns


# ------------------------------------------------------- local / self parity
_LOCAL = (
    "import torch\n"
    "import torch.nn as nn\n"
    "\n"
    "def step(model: nn.Module, features, labels):\n"
    "    criterion = nn.CrossEntropyLoss()\n"
    "    probs = torch.softmax(model(features), dim=1)\n"
    "    return criterion(probs, labels)\n"
)

_SELF = (
    "import torch\n"
    "import torch.nn as nn\n"
    "\n"
    "class Step:\n"
    "    def __init__(self):\n"
    "        self.criterion = nn.CrossEntropyLoss()\n"
    "\n"
    "    def __call__(self, model: nn.Module, features, labels):\n"
    "        probs = torch.softmax(model(features), dim=1)\n"
    "        return self.criterion(probs, labels)\n"
)


@pytest.mark.parametrize("source", [_LOCAL, _SELF], ids=["local", "self_attr"])
def test_the_same_program_answers_the_same_way_either_spelling(tmp_path, source):
    root = write_workspace(str(tmp_path), {"m.py": source})
    doc = analyze_paths(root)
    codes = [i["code"] for i in doc["issues"]]
    assert "MLV401" in codes, describe(doc)


# ------------------------------------------------------------- iron law 1
def test_an_attribute_with_nothing_behind_it_invents_no_fqn(tmp_path):
    """`self.threshold = 0.5` is not a callable; refusing it is the whole
    difference between reading a binding and guessing from a name."""
    root = write_workspace(str(tmp_path), {"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "class Head(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.threshold = 0.5\n"
        "\n"
        "    def forward(self, x):\n"
        "        return self.threshold(x)\n"
    )})
    call = call_named(root, "threshold")
    assert "torch.nn.Module.threshold" not in call.canonical_fqns[:1], call.canonical_fqns
    for fqn in call.canonical_fqns:
        assert not fqn.endswith("CrossEntropyLoss.__call__")


def test_a_real_method_still_beats_the_attribute_lookup(tmp_path):
    """`self.encode(x)` where `encode` is a *method* keeps resolving to the
    method - there is no binding named `self.encode` to read."""
    root = write_workspace(str(tmp_path), {"m.py": (
        "import torch.nn as nn\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n"
        "\n"
        "    def encode(self, x):\n"
        "        return self.fc(x)\n"
        "\n"
        "    def forward(self, x):\n"
        "        return self.encode(x)\n"
    )})
    call = call_named(root, "encode")
    assert call.target_function is not None
    assert call.target_function.qualname.endswith("Net.encode")


def test_a_self_held_estimator_keeps_its_sklearn_family(tmp_path):
    """The class of change ANA-2 was asked to watch: a self-held estimator now
    has a real receiver, so `.fit()` on it must stay an sklearn fit."""
    root = write_workspace(str(tmp_path), {"m.py": (
        "from sklearn.preprocessing import StandardScaler\n"
        "\n"
        "class Prep:\n"
        "    def __init__(self):\n"
        "        self.scaler = StandardScaler()\n"
        "\n"
        "    def run(self, X):\n"
        "        return self.scaler.fit_transform(X)\n"
    )})
    call = call_named(root, "fit_transform")
    assert call.fqn == "sklearn.base.BaseEstimator.fit_transform", call.canonical_fqns
