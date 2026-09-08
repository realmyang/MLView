"""Regressions for the graph the builder draws (round-1 fixer).

Four separate ways the picture used to lie about the code:

* a method called on the result of a plain *function* fabricated the FQN
  `<function>.<method>`, which the knowledge table's prefix rules then happily
  classified - `scores.mean()` was drawn as a `split` node in the Data lane;
* a nested loop's `enter` edge came from the enclosing *function*, so epoch and
  batch were drawn as two parallel branches instead of one inside the other,
  and a loop whose body is only another loop got no iteration arrow at all;
* a `data` / `config` edge could point from a node to the unit that already
  contains it, which CONTRACTS section 1 says is expressed by `Node.parent`;
* the truncation diagnostic quoted a node count the document does not have.
"""

from __future__ import annotations

import os

import pytest

from core_support import validate
from mlview import knowledge as K
from mlview.api import AnalyzeOptions, analyze_to_dict

FIXTURES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures",
                                        "rules"))

NESTED = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "def train(ds, epochs=2):\n"
                 "    torch.manual_seed(0)\n"
                 "    model = nn.Linear(4, 2)\n"
                 "    crit = nn.CrossEntropyLoss()\n"
                 "    opt = optim.Adam(model.parameters(), lr=0.01)\n"
                 "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
                 "    model.train()\n"
                 "    for epoch in range(epochs):\n"
                 "        for x, y in loader:\n"
                 "            opt.zero_grad()\n"
                 "            loss = crit(model(x), y)\n"
                 "            loss.backward()\n"
                 "            opt.step()\n"),
}

CHAINED = {
    "cv.py": ("import numpy as np\n"
              "from sklearn.model_selection import cross_val_score, KFold\n"
              "from sklearn.linear_model import Ridge\n\n"
              "X = np.load('x.npy')\n"
              "y = np.load('y.npy')\n"
              "folds = KFold(n_splits=5, shuffle=True, random_state=0)\n"
              "scores = cross_val_score(Ridge(), X, y, cv=folds)\n"
              "mean = scores.mean()\n"
              "spread = scores.std()\n"
              "best = scores.argmax()\n"
              "shaped = scores.reshape(-1, 1)\n"),
}


def _fabricated(fqn: str):
    """A dotted prefix of `fqn` that is itself a known *non-class* symbol."""
    parts = fqn.split(".")
    for cut in range(1, len(parts)):
        prefix = ".".join(parts[:cut])
        entry = K.lookup_exact(prefix)
        if entry is not None and not entry.get("family"):
            return prefix
    return None


# ------------------------------------------------------- fabricated FQNs
def test_a_method_on_a_function_result_does_not_invent_a_symbol(analyze_ws):
    doc = analyze_ws(CHAINED)
    for node in doc["nodes"]:
        fqn = node.get("fqn")
        if not fqn:
            continue
        assert _fabricated(fqn) is None, (
            "%s is not a real symbol (%s is a plain function)" % (fqn, _fabricated(fqn)))


def test_numpy_reductions_do_not_land_in_the_data_lane(analyze_ws):
    doc = analyze_ws(CHAINED)
    labels = {n["label"] for n in doc["nodes"] if n["stage"] == "data"}
    assert not ({"mean", "spread", "best", "shaped"} & labels), (
        "an ndarray reduction on a CV score array is not a data split")
    assert any(n.get("fqn") == "sklearn.model_selection.cross_val_score"
               for n in doc["nodes"]), "the real call is still drawn"


@pytest.mark.parametrize("name", ["MLV101_bad.py", "MLV201_bad.py", "MLV301_bad.py",
                                  "MLV501_bad.py", "MLV702_bad.py"])
def test_no_shipped_fixture_carries_a_fabricated_fqn(name):
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(FIXTURES, name),)))
    bad = [n["fqn"] for n in doc["nodes"] if n.get("fqn") and _fabricated(n["fqn"])]
    assert bad == [], bad


# ---------------------------------------------------------- loop nesting
def _control(doc):
    nodes = {n["id"]: n for n in doc["nodes"]}
    return [(e.get("subkind"), nodes[e["source"]]["label"], nodes[e["target"]]["label"])
            for e in doc["edges"] if e["kind"] == "control"]


def test_a_nested_loop_is_entered_from_the_loop_that_encloses_it(analyze_ws):
    doc = analyze_ws(NESTED)
    enters = [(src, dst) for kind, src, dst in _control(doc) if kind == "enter"]
    assert ("for epoch in range(epochs)", "for x, y in loader") in enters, enters
    assert ("train()", "for x, y in loader") not in enters, (
        "the batch loop runs inside the epoch loop, not beside it")
    assert ("train()", "for epoch in range(epochs)") in enters


def test_every_drawn_loop_keeps_an_iteration_arrow(analyze_ws):
    doc = analyze_ws(NESTED)
    backs = {dst for kind, _src, dst in _control(doc) if kind == "back"}
    loops = {n["label"] for n in doc["nodes"] if n["kind"] in ("train_loop", "eval_loop")
             and n.get("attrs", {}).get("loopKind")}
    assert loops <= backs, "loops with no back edge: %s" % sorted(loops - backs)


def test_the_nested_graph_is_still_contract_valid(analyze_ws):
    assert validate(analyze_ws(NESTED)) == []


# ------------------------------------------------------ containment edges
@pytest.mark.parametrize("files", [NESTED, CHAINED], ids=["nested", "chained"])
def test_containment_is_never_also_drawn_as_an_edge(analyze_ws, files):
    doc = analyze_ws(files)
    nodes = {n["id"]: n for n in doc["nodes"]}
    offenders = [
        (e["kind"], nodes[e["source"]]["label"], nodes[e["target"]]["label"])
        for e in doc["edges"]
        if e["kind"] != "control"
        and (nodes[e["source"]].get("parent") == e["target"]
             or nodes[e["target"]].get("parent") == e["source"])
    ]
    assert offenders == [], (
        "CONTRACTS section 1: containment is Node.parent, not an edge: %s" % offenders)


# ------------------------------------------------------ truncation wording
def test_the_truncation_diagnostic_describes_the_document_it_produced(analyze_ws):
    doc = analyze_ws(NESTED, max_nodes=3)
    note = next(d for d in doc["diagnostics"] if d["kind"] == "truncated")
    assert doc["stats"]["truncated"] is True
    assert "budget" in note["message"], note["message"]
    assert "%d node(s) kept" % len(doc["nodes"]) in note["message"], (
        "the message must not quote a node count the document does not have")
    assert note["count"] >= 1
