"""Core regression tests for the round-2 review findings.

Covers ML-05 (loop lanes), ML-07 / MLV-R2-111 (`--max-nodes` is a real cap),
ML-08 (no fabricated `torch.nn.Module.<method>` FQNs), ML-09 (PEP-263) and
MLV-R2-102 / ML-10 (mermaid output).
"""

from __future__ import annotations

import os
import re

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_to_dict, render_mermaid

_CHECKPOINT_EPOCH_LOOP = {
    "t.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "import torch.optim as optim\n"
        "from torch.utils.data import DataLoader\n\n\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n\n"
        "    def forward(self, x):\n"
        "        return self.fc(x)\n\n\n"
        "def train_one_epoch(model, loader, crit, opt):\n"
        "    for xb, yb in loader:\n"
        "        opt.zero_grad()\n"
        "        loss = crit(model(xb), yb)\n"
        "        loss.backward()\n"
        "        opt.step()\n\n\n"
        "def main(ds):\n"
        "    torch.manual_seed(0)\n"
        "    model = Net()\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = optim.SGD(model.parameters(), lr=0.1)\n"
        "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
        "    for epoch in range(10):\n"
        "        train_one_epoch(model, loader, crit, opt)\n"
        "        torch.save(model.state_dict(), 'ck.pt')\n"
        "        torch.save(opt.state_dict(), 'opt.pt')\n"),
}


# --------------------------------------------------------------------- ML-05
def test_an_epoch_loop_that_checkpoints_stays_in_the_train_lane(analyze_ws):
    doc = analyze_ws(_CHECKPOINT_EPOCH_LOOP)
    epoch = next(n for n in doc["nodes"] if n["label"].startswith("for epoch in range"))
    assert epoch["stage"] == "train", (
        "the checkpoint ops describe what happens each iteration, not what the "
        "loop is: %s" % epoch)
    assert epoch["kind"] == "train_loop"


def test_no_loop_node_contradicts_its_own_kind(analyze_ws):
    """A `train_loop` drawn in Save / Deploy shows evidence for one lane while
    sitting in another."""
    for files in (_CHECKPOINT_EPOCH_LOOP,):
        doc = analyze_ws(files)
        for node in doc["nodes"]:
            if node["kind"] == "train_loop":
                assert node["stage"] == "train", node
            if node["kind"] == "eval_loop":
                assert node["stage"] == "eval", node


# ----------------------------------------------------- ML-07 / MLV-R2-111
_TESTS_TREE = os.path.join(REPO_ROOT, "analyzer", "tests")


@pytest.mark.parametrize("max_nodes", [20, 50, 400])
def test_max_nodes_is_a_real_cap_on_a_large_workspace(max_nodes):
    doc = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=max_nodes))
    assert len(doc["nodes"]) <= max_nodes, (
        "--max-nodes is documented as the graph cap, not an op-node budget")
    assert doc["stats"]["nodes"] == len(doc["nodes"])
    assert doc["stats"]["truncated"] is True
    note = next(d for d in doc["diagnostics"] if d["kind"] == "truncated")
    assert "%d node(s) kept" % len(doc["nodes"]) in note["message"], note["message"]
    assert validate(doc) == []


def test_the_cap_keeps_the_findings_it_would_otherwise_hide():
    """The cap runs after the rules, so lowering it must not silence issues.

    The budget is derived from the findings rather than pinned at 50: the
    invariant is *every issue keeps its first anchor*, so it can only hold when
    the cap has at least one node per finding. This tree carried fewer than 50
    findings until the ANA-7/8/9 tiers landed 32 more rule fixtures in it; a
    literal 50 would have turned corpus growth into a red gate that says
    nothing about the cap. It is still a >90% cut, which is asserted.
    """
    wide = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=100000))
    budget = len(wide["issues"])
    tight = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=budget))
    assert len(tight["nodes"]) <= budget < len(wide["nodes"]) / 10
    assert {i["code"] for i in tight["issues"]} == {i["code"] for i in wide["issues"]}


def test_the_cap_holds_even_when_the_anchors_outnumber_the_budget():
    """The invariant above used to hold only *by luck*: the cap spent its
    budget on second and third anchors of one finding while another lost every
    anchor it had and was dropped. Measured on this tree the day MLV401 gained
    a third anchor: 56 anchors, a 50-node budget, MLV203 and MLV204 silenced.
    Each issue's first anchor now outranks every issue's later ones."""
    wide = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=100000))
    anchors = {node_id for issue in wide["issues"] for node_id in issue["nodeIds"]}
    budget = len(wide["issues"])
    assert len(anchors) > budget, "the interesting case is anchors > budget"
    tight = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=budget))
    assert {i["id"] for i in tight["issues"]} == {i["id"] for i in wide["issues"]}
    for issue in tight["issues"]:
        assert issue["nodeIds"], issue["code"]
    assert validate(tight) == []


def test_every_surviving_node_still_has_a_real_parent():
    doc = analyze_to_dict(AnalyzeOptions(paths=(_TESTS_TREE,), max_nodes=60))
    ids = {n["id"] for n in doc["nodes"]}
    rank = {"stage": 0, "unit": 1, "op": 2}
    by_id = {n["id"]: n for n in doc["nodes"]}
    for node in doc["nodes"]:
        parent = node.get("parent")
        if parent:
            assert parent in ids, "the cap left a dangling parent"
            assert rank[by_id[parent]["level"]] < rank[node["level"]]


# --------------------------------------------------------------------- ML-08
_SKLEARN_ONLY = {
    "m.py": (
        "from sklearn.ensemble import RandomForestClassifier\n"
        "from sklearn.model_selection import GridSearchCV\n\n\n"
        "def run(X_train, y_train, X_test):\n"
        "    search = GridSearchCV(RandomForestClassifier(), {'max_depth': [2, 4]}, cv=3)\n"
        "    search.fit(X_train, y_train)\n"
        "    best = search.best_estimator_\n"
        "    return best.predict(X_test)\n"),
}


def test_an_estimator_reached_through_an_attribute_stays_sklearn(analyze_ws):
    doc = analyze_ws(_SKLEARN_ONLY)
    assert doc["workspace"]["frameworks"] == ["sklearn"], (
        "a file that never imports torch must not report it")
    predict = next(n for n in doc["nodes"] if n["label"] == "predict()")
    assert predict["fqn"] == "sklearn.base.BaseEstimator.predict"
    assert predict["framework"] == "sklearn"
    assert predict["stage"] == "eval" and predict["kind"] == "predict"


def test_no_node_carries_a_fabricated_nn_module_symbol(analyze_ws):
    doc = analyze_ws(_SKLEARN_ONLY)
    bad = [n["fqn"] for n in doc["nodes"]
           if (n.get("fqn") or "").startswith("torch.nn.Module.")]
    assert bad == [], "invented symbols: %s" % bad


# --------------------------------------------------------------------- ML-09
def test_a_pep263_latin1_file_is_analyzed(make_workspace, tmp_path):
    root = make_workspace({"keep.py": "import torch\n"})
    target = os.path.join(root, "d.py")
    with open(target, "wb") as fh:
        fh.write(b"# -*- coding: latin-1 -*-\n# caf\xe9\nimport torch\n"
                 b"torch.manual_seed(0)\n")
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert doc["workspace"]["filesFailed"] == 0, doc["diagnostics"]
    assert doc["workspace"]["filesAnalyzed"] == 2


def test_a_genuinely_undecodable_file_still_reports_a_parse_error(make_workspace):
    root = make_workspace({"keep.py": "import torch\n"})
    with open(os.path.join(root, "broken.py"), "wb") as fh:
        fh.write(b"import torch\nx = '\xff\xfe\xfd'\n")
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert doc["workspace"]["filesFailed"] == 1
    assert any(d["kind"] == "parse_error" for d in doc["diagnostics"])


# ------------------------------------------------------ MLV-R2-102 / ML-10
_SAMPLE = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
_EDGE_LABEL_RE = re.compile(r"(?:-->|-\.->|==>|--o)\|([^|]*)\|")


def _mermaid(path):
    return render_mermaid(analyze_to_dict(AnalyzeOptions(paths=(path,))))


@pytest.mark.parametrize("path", [
    _SAMPLE,
    os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean"),
    os.path.join(REPO_ROOT, "analyzer", "tests", "clean", "vanilla_torch.py"),
])
def test_every_mermaid_edge_label_is_quoted(path):
    """mermaid's flowchart lexer rejects `(` in a bare pipe slot, and every
    `call` edge is labelled `<callee>()`."""
    text = _mermaid(path)
    labels = _EDGE_LABEL_RE.findall(text)
    assert labels, "the fixture must exercise labelled edges"
    unquoted = [l for l in labels if not (l.startswith('"') and l.endswith('"'))]
    assert unquoted == [], "unquoted mermaid edge labels: %s" % unquoted[:5]
    assert any("()" in l for l in labels), "a call edge label carries parentheses"


def test_a_ghost_node_says_missing_once():
    text = _mermaid(_SAMPLE)
    doubled = [line for line in text.splitlines() if line.count("missing") > 1]
    assert doubled == [], doubled
    assert any("· missing" in line for line in text.splitlines())


# --------------------------------------------------------------------- ML-02
_UNRESOLVED = {
    "libs/common/utils.py": "VALUE = 1\n",
    "exp/t.py": "import torch\nfrom common.utils import VALUE\n\ntorch.manual_seed(0)\n",
}
_SIBLING_OK = {
    "pkg/helper.py": "VALUE = 1\n",
    "pkg/t.py": "import torch\nfrom helper import VALUE\n\ntorch.manual_seed(0)\n",
}


def test_an_import_that_resolves_to_nothing_is_reported(analyze_ws):
    """Cross-file resolution must never degrade silently: the graph coming
    back smaller with an empty `diagnostics[]` is the failure ML-02 describes."""
    doc = analyze_ws(_UNRESOLVED)
    notes = [d for d in doc["diagnostics"] if d["kind"] == "dynamic_scope"
             and "resolved to nothing" in d["message"]]
    assert notes, doc["diagnostics"]
    assert notes[0]["file"] == "exp/t.py" and notes[0]["line"] == 2


def test_a_resolvable_sibling_import_is_not_reported(analyze_ws):
    doc = analyze_ws(_SIBLING_OK)
    notes = [d for d in doc["diagnostics"] if "resolved to nothing" in d["message"]]
    assert notes == [], notes
