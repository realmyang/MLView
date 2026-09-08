"""Location hygiene: 1-based lines, 0-based cols, symbols that really occur.

This is the test that catches the classic off-by-one across nodes, edges and
issues at once: every emitted `loc` is re-opened against the source.
"""

from __future__ import annotations

import glob
import os

import pytest

from core_support import FIXTURES
from mlview.api import AnalyzeOptions, analyze_to_dict

SOURCE = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "class Net(nn.Module):\n"
                 "    def __init__(self):\n"
                 "        super().__init__()\n"
                 "        self.fc = nn.Linear(4, 2)\n\n"
                 "    def forward(self, x):\n"
                 "        return self.fc(x)\n\n\n"
                 "def train(ds):\n"
                 "    torch.manual_seed(0)\n"
                 "    model = Net()\n"
                 "    criterion = nn.CrossEntropyLoss()\n"
                 "    optimizer = optim.Adam(model.parameters(), lr=0.001)\n"
                 "    train_loader = DataLoader(ds, batch_size=128, num_workers=4)\n"
                 "    for images, labels in train_loader:\n"
                 "        optimizer.zero_grad()\n"
                 "        loss = criterion(model(images), labels)\n"
                 "        loss.backward()\n"
                 "        optimizer.step()\n"),
}


def iter_locs(doc):
    for node in doc["nodes"]:
        yield "node %s" % node["id"], node["loc"]
        if node.get("defLoc"):
            yield "defLoc %s" % node["id"], node["defLoc"]
    for edge in doc["edges"]:
        yield "edge %s" % edge["id"], edge["loc"]
    for issue in doc["issues"]:
        yield "issue %s" % issue["id"], issue["loc"]
        for related in issue.get("relatedLocs", []):
            yield "related %s" % issue["id"], related


def check_document(doc, read_source):
    for label, loc in iter_locs(doc):
        assert loc["line"] >= 1, label
        assert loc["col"] >= 0, label
        assert loc["endLine"] >= loc["line"], label
        lines = read_source(loc["file"]).splitlines()
        assert loc["line"] <= len(lines), "%s: line past EOF" % label
        segment = "\n".join(lines[loc["line"] - 1:loc["endLine"]])
        symbol = loc.get("symbol")
        if symbol:
            assert symbol in segment, "%s: %r not in %r" % (label, symbol, segment[:120])
            primary = lines[loc["line"] - 1]
            if primary.count(symbol) == 1 and loc["endLine"] == loc["line"]:
                assert primary.find(symbol) == loc["col"], \
                    "%s: col %d does not point at %r" % (label, loc["col"], symbol)
        snippet = loc.get("snippet")
        if snippet:
            assert snippet == lines[loc["line"] - 1].rstrip(), label


def test_every_location_resolves(make_workspace):
    root = make_workspace(SOURCE)
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))

    def read(relpath):
        with open(os.path.join(root, relpath), encoding="utf-8") as fh:
            return fh.read()

    check_document(doc, read)


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(FIXTURES, "rules", "*.py"))))
def test_fixture_locations_resolve(path):
    doc = analyze_to_dict(AnalyzeOptions(paths=(path,)))
    root = os.path.dirname(path)

    def read(relpath):
        with open(os.path.join(root, relpath), encoding="utf-8") as fh:
            return fh.read()

    check_document(doc, read)


def test_paths_are_workspace_relative_with_forward_slashes(analyze_ws):
    doc = analyze_ws({"pkg/sub/mod.py": "import torch\nx = torch.device('cpu')\n"})
    root = doc["workspace"]["root"]
    assert "\\" not in root
    for _label, loc in iter_locs(doc):
        assert "\\" not in loc["file"]
        assert "\\" not in loc["absFile"]
        assert not loc["file"].startswith("/")
        assert loc["absFile"] == "%s/%s" % (root, loc["file"])


def test_defloc_is_the_definition_header(analyze_ws):
    doc = analyze_ws(SOURCE)
    net = [n for n in doc["nodes"] if n["label"] == "Net"][0]
    assert net["defLoc"]["line"] == 7
    assert net["defLoc"]["symbol"] == "class Net"
    train = [n for n in doc["nodes"] if n["label"] == "train()"][0]
    assert train["defLoc"]["symbol"] == "def train"
