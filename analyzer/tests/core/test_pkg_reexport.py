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


# ------------------------------------------------ REV-02 / REV-03: the blame
def _deep_chain(importers: int) -> dict:
    """One over-long chain rooted in `a/__init__.py`, plus N plain consumers."""
    files = {
        "a/__init__.py": "from .b import Net\n",
        "a/b/__init__.py": "from .c import Net\n",
        "a/b/c/__init__.py": "from .d import Net\n",
        "a/b/c/d/__init__.py": "from .net import Net\n",
        "a/b/c/d/net.py": ("import torch.nn as nn\n\n\n"
                           "class Net(nn.Module):\n"
                           "    def __init__(self):\n"
                           "        super().__init__()\n"
                           "        self.fc = nn.Linear(8, 2)\n"),
    }
    for index in range(importers):
        files["consumer%d.py" % index] = (
            "from a import Net\n\n\ndef use%d():\n    return Net()\n" % index)
    return files


def _cap_notes(doc):
    return [d for d in doc["diagnostics"] if d["kind"] == "dynamic_scope"
            and "stops following the chain" in d["message"]]


@pytest.mark.parametrize("importers", [0, 1, 3, 8])
def test_one_over_long_chain_is_one_note_however_many_modules_import_it(
        make_workspace, importers):
    """REV-02: it was 1 + one per importer, each naming a file that re-exports
    nothing. A package facade imported from 40 modules produced 41 notes, 40 of
    them wrong."""
    root = make_workspace(_deep_chain(importers))
    notes = _cap_notes(analyze_to_dict(AnalyzeOptions(paths=(root,))))
    assert len(notes) == 1, [d["message"] for d in notes]
    assert notes[0]["file"] == "a/__init__.py"
    assert "`a.Net`" in notes[0]["message"]


def test_no_plain_consumer_module_is_ever_blamed(make_workspace):
    root = make_workspace(_deep_chain(3))
    notes = _cap_notes(analyze_to_dict(AnalyzeOptions(paths=(root,))))
    blamed = {d["file"] for d in notes}
    assert not any(name.startswith("consumer") for name in blamed), blamed
    for note in notes:
        assert "consumer" not in note["message"]


def test_a_cycle_says_cycle_and_not_more_than_three_modules(make_workspace):
    """REV-03: the walk stopped for a reason the message did not name."""
    root = make_workspace({
        "p/__init__.py": "from .q import Net\n",
        "p/q/__init__.py": "from .. import Net\n",
        "run.py": "from p import Net\n\n\ndef use():\n    return Net()\n",
    })
    notes = _cap_notes(analyze_to_dict(AnalyzeOptions(paths=(root,))))
    assert len(notes) == 1, [d["message"] for d in notes]
    message = notes[0]["message"]
    assert "re-exports in a cycle" in message
    assert "more than %d modules" % _MAX_REEXPORT_HOPS not in message
    assert "p.Net -> p.q.Net -> p.Net" in message


def test_the_cap_wording_survives_for_a_genuine_cap(make_workspace):
    root = make_workspace(_deep_chain(1))
    message = _cap_notes(analyze_to_dict(AnalyzeOptions(paths=(root,))))[0]["message"]
    assert "re-exported through more than %d modules" % _MAX_REEXPORT_HOPS in message
    assert "cycle" not in message
