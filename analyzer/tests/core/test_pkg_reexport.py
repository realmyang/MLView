"""ANA-3: relative imports and re-exports inside a package `__init__.py`.

`ir/build_ir.dotted_for` already maps `pkg/__init__.py` to `"pkg"`, but
`_relative_base` unconditionally dropped the module's last dotted component, so
`from .windows import WindowDataset` inside `src/data/__init__.py` resolved to
`src.windows` - one package too high. The importer got a `dynamic_scope` note,
the re-exported symbols became orphan nodes, and package re-export is the most
common research-repo layout there is.

The second half is the hop: `from pkg import Net` names `pkg.Net`, which no
`ClassIR` carries, so the alias is followed to the definition (`pkg.net.Net`),
capped at `_MAX_REEXPORT_HOPS` and cycle-safe, with the cap *reported* rather
than silently binding.
"""

from __future__ import annotations

import os

import pytest

from core_support import FIXTURES, validate
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict
from mlview.ir.build_ir import _MAX_REEXPORT_HOPS, dotted_for, is_package
from mlview.ir.symbols import _relative_base

PKG = os.path.join(FIXTURES, "pkgreexport")


@pytest.fixture(scope="module")
def pkg():
    return analyze_to_dict(AnalyzeOptions(paths=(PKG,)))


def _degrees(doc):
    deg = {n["id"]: 0 for n in doc["nodes"]}
    for edge in doc["edges"]:
        deg[edge["source"]] = deg.get(edge["source"], 0) + 1
        deg[edge["target"]] = deg.get(edge["target"], 0) + 1
    return deg


def _labelled(doc, label):
    return next(n for n in doc["nodes"] if n["label"] == label)


# ------------------------------------------------------------- the base itself
def test_a_package_init_does_not_trim_its_own_name():
    assert dotted_for("src/data/__init__.py") == "src.data"
    assert is_package("src/data/__init__.py") and not is_package("src/data/windows.py")
    assert _relative_base("src.data", 1, is_package=True) == "src.data"
    assert _relative_base("src.data", 2, is_package=True) == "src"
    # a plain module is unchanged: its own package is everything but its name
    assert _relative_base("src.data.windows", 1) == "src.data"
    assert _relative_base("src.data.windows", 2) == "src"


# --------------------------------------------------------------- the fixture
def test_the_re_exported_imports_no_longer_resolve_to_nothing(pkg):
    notes = [d for d in pkg["diagnostics"] if d["kind"] == "dynamic_scope"]
    assert notes == [], [d["message"] for d in notes]


def test_the_entrypoint_reaches_the_class_behind_the_re_export(pkg):
    net = _labelled(pkg, "Net")
    assert net["loc"]["file"] == "src/models/net.py"
    calls = [e for e in pkg["edges"] if e["kind"] == "call" and e["target"] == net["id"]]
    assert calls, "train.py's `Net(width=16)` must draw a call edge into the class"
    source = next(n for n in pkg["nodes"] if n["id"] == calls[0]["source"])
    assert source["loc"]["file"] == "train.py"


def test_every_re_exported_symbol_carries_an_incident_edge(pkg):
    deg = _degrees(pkg)
    for label in ("Net", "WindowDataset", "build_optimizer()"):
        node = _labelled(pkg, label)
        assert deg[node["id"]] > 0, "%s is still an orphan" % label


def test_the_graph_is_one_connected_pipeline(pkg):
    assert len(pkg["edges"]) >= 16, len(pkg["edges"])
    assert pkg["workspace"]["filesAnalyzed"] == 6
    assert validate(pkg) == []


def test_the_fixture_stays_silent(pkg):
    """A correct program: the fix must not buy edges with a false positive."""
    assert pkg["issues"] == [], [(i["code"], i["loc"]["line"]) for i in pkg["issues"]]


# ------------------------------------------------------------------- the hops
def test_a_two_hop_re_export_still_lands_on_the_definition(make_workspace):
    root = make_workspace({
        "src/__init__.py": "from .models import Net\n",
        "src/models/__init__.py": "from .net import Net\n",
        "src/models/net.py": (
            "import torch.nn as nn\n"
            "\n"
            "class Net(nn.Module):\n"
            "    def __init__(self):\n"
            "        super().__init__()\n"
            "        self.fc = nn.Linear(4, 2)\n"
        ),
        "train.py": (
            "from src import Net\n"
            "\n"
            "def main():\n"
            "    return Net()\n"
        ),
    })
    workspace = analyze_full(AnalyzeOptions(paths=(root,))).workspace
    assert workspace.reexports["src.Net"] == "src.models.net.Net"
    call = next(c for c in workspace.modules["train.py"].calls if c.short_name == "Net")
    assert call.class_ir is not None and call.class_ir.qualname == "src.models.net.Net"


def test_a_chain_longer_than_the_cap_is_reported_not_dropped(make_workspace):
    # a straight chain: deep/__init__ -> a0 -> a1 -> ... -> the definition,
    # one module longer than the analyzer is willing to follow
    hops = _MAX_REEXPORT_HOPS + 1
    files = {"deep/__init__.py": "from .a0 import Net\n"}
    for index in range(hops):
        files["deep/a%d.py" % index] = "from .a%d import Net\n" % (index + 1)
    files["deep/a%d.py" % hops] = (
        "import torch.nn as nn\n"
        "\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n"
    )
    files["train.py"] = "from deep import Net\n\n\ndef main():\n    return Net()\n"
    root = make_workspace(files)
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    notes = [d for d in doc["diagnostics"] if d["kind"] == "dynamic_scope"
             and "re-exported through more than" in d["message"]]
    assert notes, [d["message"] for d in doc["diagnostics"]]
    assert str(_MAX_REEXPORT_HOPS) in notes[0]["message"]


def test_a_re_export_cycle_terminates(make_workspace):
    root = make_workspace({
        "a/__init__.py": "from b import Thing\n",
        "b/__init__.py": "from a import Thing\n",
        "train.py": "from a import Thing\n",
    })
    workspace = analyze_full(AnalyzeOptions(paths=(root,))).workspace
    assert "a.Thing" not in workspace.reexports or \
        workspace.reexports["a.Thing"] != "a.Thing"


def test_a_third_party_import_is_never_treated_as_a_re_export(make_workspace):
    root = make_workspace({
        "pkg/__init__.py": "from torch.nn import Linear\n",
        "train.py": "from pkg import Linear\n\n\ndef main():\n    return Linear(4, 2)\n",
    })
    workspace = analyze_full(AnalyzeOptions(paths=(root,))).workspace
    assert "pkg.Linear" not in workspace.reexports
