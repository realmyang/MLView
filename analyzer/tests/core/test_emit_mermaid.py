"""`--format mermaid`: one subgraph per present stage, one declaration per node.

A node declared inside two subgraphs is placed unpredictably by mermaid, so
the emitter nests a node under its parent only while the stage lane is
unbroken and otherwise starts it as a root of its own lane.
"""

from __future__ import annotations

import collections
import os
import re

import pytest

from mlview.api import AnalyzeOptions, analyze_to_dict, demo_dict, render_mermaid

FIXTURE_BAD = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "rules", "MLV201_bad.py"))

DECL_RE = re.compile(r'^\s*(n_[0-9a-f]+)(?:\("|\["|>")', re.M)
SUBGRAPH_RE = re.compile(r'^\s*subgraph (\S+)\[', re.M)

SRC = {
    "train.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader\n\n\n"
                 "def train(ds):\n"
                 "    torch.manual_seed(0)\n"
                 "    model = nn.Linear(4, 2)\n"
                 "    crit = nn.CrossEntropyLoss()\n"
                 "    opt = optim.Adam(model.parameters(), lr=0.01)\n"
                 "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
                 "    for epoch in range(3):\n"
                 "        for x, y in loader:\n"
                 "            loss = crit(model(x), y)\n"
                 "            loss.backward()\n"
                 "            opt.step()\n"),
}


@pytest.fixture
def diagram(analyze_ws):
    doc = analyze_ws(SRC)
    return doc, render_mermaid(doc)


def test_header_and_stage_subgraphs(diagram):
    doc, text = diagram
    assert text.startswith("flowchart LR\n")
    names = SUBGRAPH_RE.findall(text)
    present = [s["id"] for s in doc["stages"] if s["present"]]
    absent = [s["id"] for s in doc["stages"] if not s["present"]]
    for stage in present:
        assert "stage_%s" % stage in names
    for stage in absent:
        assert "stage_%s" % stage not in names
        assert stage in text.rsplit("%%", 1)[-1], "absent stages are listed in the comment"


def test_every_node_is_declared_exactly_once(diagram):
    doc, text = diagram
    declared = DECL_RE.findall(text)
    duplicates = [name for name, count in collections.Counter(declared).items() if count > 1]
    assert duplicates == [], "mermaid places a repeated declaration unpredictably"
    assert len(declared) == len(doc["nodes"])


def test_ids_are_sanitized_and_edges_resolve(diagram):
    doc, text = diagram
    declared = set(DECL_RE.findall(text))
    for node in doc["nodes"]:
        expected = "n_" + node["id"].split(":", 1)[1]
        assert expected in declared
        assert re.fullmatch(r"n_[A-Za-z0-9_]+", expected)
    for edge in doc["edges"]:
        source = "n_" + edge["source"].split(":", 1)[1]
        target = "n_" + edge["target"].split(":", 1)[1]
        assert source in declared and target in declared


def test_each_edge_kind_gets_its_own_arrow(diagram):
    doc, text = diagram
    arrows = {"data": "-->", "call": "-.->", "control": "==>", "config": "--o"}
    for edge in doc["edges"]:
        source = "n_" + edge["source"].split(":", 1)[1]
        target = "n_" + edge["target"].split(":", 1)[1]
        arrow = arrows[edge["kind"]]
        # the label is quoted so `(` in `callee()` does not break the lexer
        label = '|"%s"| ' % edge["label"] if edge.get("label") else ""
        assert "%s %s%s%s" % (source, arrow, label, target) in text
    assert len({arrows[e["kind"]] for e in doc["edges"]}) >= 2, "several kinds are exercised"


def test_severity_prefixes_and_ghosts_are_marked():
    doc = analyze_to_dict(AnalyzeOptions(paths=(FIXTURE_BAD,)))
    text = render_mermaid(doc)
    ghost = next(n for n in doc["nodes"] if n["ghost"])
    ghost_id = "n_" + ghost["id"].split(":", 1)[1]
    assert '%s>"[!!] zero_grad()' % ghost_id in text, "ghosts get the asymmetric shape"
    assert "· missing" in text
    assert "[!!]" in text
    assert "[!]" not in text.replace("[!!]", "")


def test_labels_cannot_break_the_diagram(analyze_ws):
    doc = analyze_ws({"x.py": 'import torch\nd = torch.device("cpu")\n'})
    doc["nodes"][0]["label"] = 'a["b"]|c{d}<e>'
    text = render_mermaid(doc)
    body = text.split("\n", 1)[1]
    assert '"b"' not in body and "|c" not in body and "<e>" not in body
    assert "‹e›" in body


def test_the_absent_stage_line_is_a_real_mermaid_comment(diagram):
    """`%%` is mermaid's comment token; a bare `%` line is stray graph syntax.

    Built with the %-format operator, `"  %% not detected: %s" % ...` collapses
    to a single `%` - so every diagram with an absent stage (which is almost
    every real project) ended in a line the renderer cannot parse.
    """
    doc, text = diagram
    absent = [s["id"] for s in doc["stages"] if not s["present"]]
    assert absent, "the fixture must exercise the absent-stage line"
    assert text.rstrip("\n").endswith("  %% not detected: " + ", ".join(absent))
    stray = [line for line in text.splitlines()
             if line.lstrip().startswith("%") and not line.lstrip().startswith("%%")]
    assert stray == [], stray


def test_the_golden_sample_renders():
    text = render_mermaid(demo_dict())
    assert text.startswith("flowchart LR\n")
    declared = DECL_RE.findall(text)
    assert len(declared) == len(set(declared))
