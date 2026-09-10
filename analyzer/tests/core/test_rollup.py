"""PERF-04 (CONTRACTS 11.46): `--max-nodes` is a rollup, not a deletion.

The acceptance battery runs on a **525-file synthetic research repo** built
once per session in a tmp dir - 25 experiments that share one `common/`
package - and every module in it is imported by something, on purpose: dead
code is a lone card at any budget and would measure the corpus rather than the
cap.

The uncapped document is analyzed once; each budget then runs
`apply_node_budget` on a deep copy of the *graph object*, which is exactly what
`core/pipeline.run` does at the same point, so the battery costs one analysis
rather than five.
"""

from __future__ import annotations

import copy
import os

import pytest

from core_support import validate
from mlview.api import AnalyzeOptions, analyze
from mlview.core.rollup import RollupReport, apply_node_budget

CAPS = (2000, 400, 100, 45)

# --------------------------------------------------------------- the corpus
_TRAIN = '''import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

from exp{e}.models.net_0 import Net0
from exp{e}.models.net_1 import Net1
from exp{e}.models.net_2 import Net2
from exp{e}.models.net_3 import Net3
from exp{e}.data.load_0 import load_0
from exp{e}.data.load_1 import load_1
from exp{e}.data.load_2 import load_2
from exp{e}.data.load_3 import load_3
from common.metrics_{c} import score_{c}
from common.metrics_{c2} import score_{c2}
from common.io_{d} import save_{d}
from common.io_{d2} import save_{d2}


def prepare(frame):
    scaler = StandardScaler()
    features = scaler.fit_transform(frame)
    X_train, X_test, y_train, y_test = train_test_split(features, frame)
    return X_train, X_test, y_train, y_test


def build():
    first = Net0()
    second = Net1()
    third = Net2()
    fourth = Net3()
    return nn.Sequential(first, second, third, fourth)


def train(dataset):
    model = build()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=1e-3)
    loader = DataLoader(dataset, batch_size=32, shuffle=True)
    for epoch in range(10):
        for batch_x, batch_y in loader:
            output = model(batch_x)
            loss = criterion(output, batch_y)
            loss.backward()
            optimizer.step()
    return model


def main():
    frame = load_0()
    extra = load_1()
    more = load_2()
    rest = load_3()
    X_train, X_test, y_train, y_test = prepare(frame)
    model = train(X_train)
    preds = model(X_test)
    accuracy = score_{c}(preds, y_test)
    second = score_{c2}(preds, y_test)
    save_{d}(model, accuracy)
    save_{d2}(model, second)
    return accuracy


if __name__ == "__main__":
    main()
'''

_NET = '''import torch.nn as nn

from exp{e}.util.helpers_{j} import make_block_{j}


class Net{j}(nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = nn.Conv2d(3, 16, 3)
        self.bn = nn.BatchNorm2d(16)
        self.act = nn.ReLU()
        self.block = make_block_{j}()
        self.head = nn.Linear(16, 10)

    def forward(self, x):
        x = self.stem(x)
        x = self.bn(x)
        x = self.act(x)
        x = self.block(x)
        return self.head(x)
'''

_UTIL = '''import torch.nn as nn


def make_block_{j}():
    inner = nn.Conv2d(16, 16, 3)
    gate = nn.ReLU()
    return nn.Sequential(inner, gate)
'''

_DATA = '''import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from exp{e}.util.helpers_{j} import make_block_{j}


def load_{j}():
    frame = pd.read_csv("data_{j}.csv")
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(frame)
    return scaled
'''

_METRICS = '''from sklearn.metrics import accuracy_score


def score_{i}(preds, labels):
    return accuracy_score(labels, preds)
'''

_IO = '''import torch


def save_{i}(model, accuracy):
    torch.save(model.state_dict(), "run_{i}.pt")
    return accuracy
'''


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _build_repo(root):
    """25 experiments x 17 files + a 100-file `common/` package = 525 files."""
    files = 0
    os.makedirs(os.path.join(root, "common"), exist_ok=True)
    _write(os.path.join(root, "common", "__init__.py"), "")
    files += 1
    for i in range(50):
        _write(os.path.join(root, "common", "metrics_%d.py" % i),
               _METRICS.format(i=i))
        files += 1
    for i in range(49):
        _write(os.path.join(root, "common", "io_%d.py" % i), _IO.format(i=i))
        files += 1
    for e in range(25):
        base = os.path.join(root, "exp%d" % e)
        for sub in ("", "models", "data", "util"):
            os.makedirs(os.path.join(base, sub), exist_ok=True)
            _write(os.path.join(base, sub, "__init__.py"), "")
            files += 1
        _write(os.path.join(base, "train.py"),
               _TRAIN.format(e=e, c=2 * e, c2=2 * e + 1,
                             d=(2 * e) % 49, d2=(2 * e + 1) % 49))
        files += 1
        for j in range(4):
            _write(os.path.join(base, "models", "net_%d.py" % j),
                   _NET.format(e=e, j=j))
            _write(os.path.join(base, "data", "load_%d.py" % j),
                   _DATA.format(e=e, j=j))
            _write(os.path.join(base, "util", "helpers_%d.py" % j),
                   _UTIL.format(j=j))
            files += 3
    return files


@pytest.fixture(scope="session")
def synthetic(tmp_path_factory):
    """The 525-file repo, and the uncapped graph OBJECT, built once."""
    root = str(tmp_path_factory.mktemp("perf04"))
    written = _build_repo(root)
    assert written == 525, written
    graph = analyze(AnalyzeOptions(paths=(root,), max_nodes=10 ** 7,
                                   max_files=2000))
    assert len(graph.nodes) > 1500, len(graph.nodes)
    return graph


def _capped(graph, budget):
    """What `core/pipeline.run` does at this point, on a copy."""
    rolled = copy.deepcopy(graph)
    report = apply_node_budget(rolled, budget) or RollupReport(budget=budget)
    rolled.finalize()
    return rolled.to_dict(), report


def _degrees(doc):
    touched = set()
    for edge in doc["edges"]:
        touched.add(edge["source"])
        touched.add(edge["target"])
    return touched


def _floating(doc):
    """A card connected to nothing at all: no edge, no parent, no children.

    This - not "degree 0" - is what the ROADMAP's "one-third-disconnected dot
    cloud" describes. A ghost has no edges **by construction** (it draws a call
    that was never made) and is drawn inside its parent, so counting it as an
    orphan would measure the finding rather than the cap.
    """
    touched = _degrees(doc)
    parents = {n["parent"] for n in doc["nodes"] if n.get("parent")}
    return [n for n in doc["nodes"]
            if n["id"] not in touched and not n.get("parent")
            and n["id"] not in parents]


# ------------------------------------------------------------- acceptance
@pytest.mark.parametrize("budget", CAPS)
def test_the_document_is_valid_at_every_budget(synthetic, budget):
    doc, _report = _capped(synthetic, budget)
    assert len(doc["nodes"]) <= budget
    assert validate(doc) == []


@pytest.mark.parametrize("budget", CAPS)
def test_the_rollup_leaves_no_floating_card(synthetic, budget):
    """Acceptance: isolated survivors under 5%. It is **zero** at every budget,
    and the only edgeless survivors are the ghosts, which are drawn inside a
    parent."""
    doc, _report = _capped(synthetic, budget)
    floating = _floating(doc)
    assert floating == [], [n["qualname"] for n in floating[:5]]
    touched = _degrees(doc)
    edgeless = [n for n in doc["nodes"] if n["id"] not in touched]
    assert all(n["ghost"] for n in edgeless), [
        n["qualname"] for n in edgeless if not n["ghost"]][:5]


@pytest.mark.parametrize("budget", CAPS)
def test_no_edge_is_ever_lost(synthetic, budget):
    """Every uncapped edge is drawn, merged into a drawn edge, or absorbed into
    a rolled-up node. None simply disappears - which is what the deletion cap
    did to 96.9% of them."""
    base = synthetic.to_dict()
    doc, report = _capped(synthetic, budget)
    assert report.edges_lost == 0
    assert (len(doc["edges"]) + report.edges_merged + report.edges_absorbed
            == len(base["edges"]))


def test_edge_retention_at_the_roadmap_budget(synthetic):
    """Acceptance: over 40% of the uncapped edges retained at `--max-nodes 400`
    once parallels are merged."""
    base = synthetic.to_dict()
    doc, report = _capped(synthetic, 400)
    retained = len(doc["edges"]) + report.edges_merged
    assert retained > 0.40 * len(base["edges"]), (
        "%d of %d" % (retained, len(base["edges"])))


@pytest.mark.parametrize("budget", CAPS)
def test_every_finding_survives_and_resolves_to_a_node(synthetic, budget):
    """The deletion cap silenced 75 of 126 findings at `--max-nodes 45` on this
    corpus. A fold never drops one."""
    base = synthetic.to_dict()
    doc, report = _capped(synthetic, budget)
    assert report.lost_issues == 0
    assert {i["id"] for i in doc["issues"]} == {i["id"] for i in base["issues"]}
    ids = {n["id"] for n in doc["nodes"]}
    for issue in doc["issues"]:
        assert issue["nodeIds"], issue["code"]
        assert issue["nodeIds"][0] in ids


@pytest.mark.parametrize("budget", CAPS)
def test_the_parent_forest_and_the_level_rule_hold(synthetic, budget):
    doc, _report = _capped(synthetic, budget)
    rank = {"stage": 0, "unit": 1, "op": 2}
    by_id = {n["id"]: n for n in doc["nodes"]}
    for node in doc["nodes"]:
        parent = node.get("parent")
        if not parent:
            continue
        assert parent in by_id, "the rollup left a dangling parent"
        assert rank[by_id[parent]["level"]] < rank[node["level"]]


@pytest.mark.parametrize("budget", CAPS)
def test_a_ghost_is_never_folded_away(synthetic, budget):
    """11.46 A5. A ghost draws a call the code should have made; folding it
    would delete the most legible thing MLView renders."""
    base = synthetic.to_dict()
    doc, _report = _capped(synthetic, budget)
    ghosts = {n["id"] for n in base["nodes"] if n["ghost"]}
    assert ghosts, "the corpus must carry ghosts for this to mean anything"
    assert ghosts <= {n["id"] for n in doc["nodes"]}
    for node in doc["nodes"]:
        if node["ghost"]:
            assert node["issueIds"], node["id"]
            assert "rolledUp" not in node


# ------------------------------------------------------------- the fields
def test_an_uncapped_document_is_untouched(synthetic):
    """11.46 A: the cap path is only entered above budget, so a document within
    it cannot change - asserted by identity of the bytes AND by the fact that
    `apply_node_budget` reports nothing."""
    base = synthetic.to_dict()
    copy_of = copy.deepcopy(synthetic)
    assert apply_node_budget(copy_of, 10 ** 7) is None
    copy_of.finalize()
    assert copy_of.to_dict() == base
    assert not any("rolledUp" in n for n in base["nodes"])
    assert not any("weight" in e for e in base["edges"])
    assert base["stats"]["truncated"] is False


@pytest.mark.parametrize("budget", (400, 100, 45))
def test_rolled_up_and_weight_only_appear_on_a_capped_document(synthetic, budget):
    doc, _report = _capped(synthetic, budget)
    assert doc["stats"]["truncated"] is True
    assert any(n.get("rolledUp") for n in doc["nodes"])
    for node in doc["nodes"]:
        if "rolledUp" in node:
            assert isinstance(node["rolledUp"], int) and node["rolledUp"] >= 1
    for edge in doc["edges"]:
        if "weight" in edge:
            assert isinstance(edge["weight"], int) and edge["weight"] >= 2


@pytest.mark.parametrize("budget", (400, 100, 45))
def test_edges_are_merged_not_duplicated(synthetic, budget):
    """11.46 B2/B3: no self-loop, no parallel pair, and a merged edge that keeps
    a label only when its members agreed."""
    doc, _report = _capped(synthetic, budget)
    seen = set()
    for edge in doc["edges"]:
        assert edge["source"] != edge["target"]
        key = (edge["source"], edge["kind"], edge["target"])
        assert key not in seen, key
        seen.add(key)


@pytest.mark.parametrize("budget", (400, 45))
def test_the_summary_node_is_a_real_node(synthetic, budget):
    """11.46 A3: a summary carries a location an editor can open, a count, and
    the collapsed-group visual the viewer already has."""
    doc, _report = _capped(synthetic, budget)
    summaries = [n for n in doc["nodes"] if n.get("attrs", {}).get("rollup")]
    assert summaries, "this budget must have summarised something"
    root = doc["workspace"]["root"]
    for node in summaries:
        assert node["level"] == "stage" and node["parent"] is None
        assert node["collapsedByDefault"] is True
        assert node["ghost"] is False
        assert node["rolledUp"] >= 2
        assert node["sublabel"] == "%d nodes rolled up" % node["rolledUp"]
        assert node["loc"]["file"].endswith(".py"), (
            "click-to-code must land on a file, never on a directory")
        assert node["loc"]["absFile"] == root + "/" + node["loc"]["file"]


# ------------------------------------------------------------ the wording
@pytest.mark.parametrize("budget", (400, 45))
def test_the_diagnostic_says_rolled_up_and_counts_what_it_did(synthetic, budget):
    """11.46 D. `stats.truncated` is a boolean; the words are the diagnostic's
    job, and it must describe the document it actually produced."""
    doc, _report = _capped(synthetic, budget)
    note = next(d for d in doc["diagnostics"] if d["kind"] == "truncated")
    assert "budget" in note["message"]
    assert "rolled up" in note["message"]
    assert "%d node(s) kept" % len(doc["nodes"]) in note["message"]
    assert "dropped" in note["message"] and "absorbed" in note["message"]
    assert note["count"] >= 1


@pytest.mark.parametrize("budget", CAPS)
def test_truncated_always_carries_a_truncated_diagnostic(synthetic, budget):
    """The emitter obligation `contracts/validate_sample.py` deliberately does
    not assert (11.46 C): `analyzer/tools/scope_gen.py` sets `truncated` at
    random on synthetic graphs that carry no diagnostics at all."""
    doc, _report = _capped(synthetic, budget)
    if doc["stats"]["truncated"]:
        assert any(d["kind"] == "truncated" for d in doc["diagnostics"])


def test_the_rollup_is_deterministic(synthetic):
    first, _ = _capped(synthetic, 400)
    second, _ = _capped(synthetic, 400)
    first["generator"] = second["generator"] = {}
    first["stats"]["durationMs"] = second["stats"]["durationMs"] = 0
    assert first == second


def test_a_tighter_budget_is_a_zoom_level_not_a_different_answer(synthetic):
    """Every finding is present at every budget, and the node count is
    monotonic in the budget."""
    counts = []
    for budget in (2000, 400, 100, 45):
        doc, _report = _capped(synthetic, budget)
        counts.append(len(doc["nodes"]))
        assert len(doc["issues"]) == len(synthetic.issues)
    assert counts == sorted(counts, reverse=True), counts
