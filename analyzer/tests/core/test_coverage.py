"""COVERAGE: "I could not check" must not look like "I checked and it is fine".

Two `Diagnostic.kind` values added by CONTRACTS amendment 11.18 and emitted
here: `untagged_dataflow` (a FIT / SPLIT / LOADER site whose key argument was
never traced) and `single_file_analysis` (a strict subset of a package was
analyzed).

The load-bearing negative is in the middle: neither diagnostic changes a rule's
gate, so `samples/vision_pipeline` still carries exactly its fifteen findings
and both clean corpora stay silent.

The bottom half pins the 2026-09-08 widening. `untagged_dataflow` used to be
reachable only from MLV101 and MLV102, so a blind SPLIT, LOADER or FIT site
outside the leakage pair was silent (TB-10); `single_file_analysis` used to
require exactly one analyzed file, missing the nested-sub-package shape the VS
Code package scope produces (TB-11); and its message mixed two path bases for
the same directory (TB-15).
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate

from mlview.api import AnalyzeOptions, analyze_to_dict

SAMPLES = os.path.join(REPO_ROOT, "samples")
DIRTY = os.path.join(SAMPLES, "vision_pipeline")
CLEAN = os.path.join(SAMPLES, "vision_pipeline_clean")
TESTS_CLEAN = os.path.join(REPO_ROOT, "analyzer", "tests", "clean")

#: The measured MLV101 blind spot: identical leakage, but `X` and `y` arrive as
#: parameters, so no `ValueTag` ever reaches them and the rule stays silent.
LEAK_IN_A_HELPER = {
    "prep.py": ("import numpy as np\n"
                "from sklearn.model_selection import train_test_split\n"
                "from sklearn.preprocessing import StandardScaler\n\n\n"
                "def make_splits(X, y):\n"
                "    scaler = StandardScaler()\n"
                "    scaled = scaler.fit_transform(X)\n"
                "    return train_test_split(scaled, y, test_size=0.2)\n\n\n"
                "def main():\n"
                "    raw = np.load('data.npy')\n"
                "    return make_splits(raw[:, :-1], raw[:, -1])\n"),
}

#: The same leakage, in scope, where MLV101 *does* fire.
LEAK_IN_SCOPE = {
    "prep.py": ("import numpy as np\n"
                "from sklearn.model_selection import train_test_split\n"
                "from sklearn.preprocessing import StandardScaler\n\n\n"
                "def main():\n"
                "    raw = np.load('data.npy')\n"
                "    X = raw[:, :-1]\n"
                "    y = raw[:, -1]\n"
                "    scaler = StandardScaler()\n"
                "    scaled = scaler.fit_transform(X)\n"
                "    return train_test_split(scaled, y, test_size=0.2)\n"),
}


def _of(doc, kind):
    return [d for d in doc.get("diagnostics", []) if d["kind"] == kind]


# ------------------------------------------------------------ untagged_dataflow
def test_a_fit_on_an_untraced_parameter_is_declared(analyze_ws):
    doc = analyze_ws(LEAK_IN_A_HELPER)
    notes = _of(doc, "untagged_dataflow")
    assert len(notes) == 1, doc["diagnostics"]
    note = notes[0]
    assert note["file"] == "prep.py"
    assert note["scope"] == "prep.make_splits"
    assert "`X`" in note["message"]
    assert "arrives as a parameter of prep.make_splits" in note["message"]
    assert "MLV101" in note["codes"]
    assert note["count"] == 1
    # and the rule itself is still silent - the gate is untouched
    assert [i for i in doc["issues"] if i["code"] == "MLV101"] == []
    assert validate(doc) == []


def test_a_traced_fit_produces_a_finding_and_no_coverage_note(analyze_ws):
    doc = analyze_ws(LEAK_IN_SCOPE)
    assert [i["code"] for i in doc["issues"] if i["code"] == "MLV101"] == ["MLV101"]
    assert _of(doc, "untagged_dataflow") == []


def test_sites_in_one_scope_collapse_to_one_note(analyze_ws):
    doc = analyze_ws({
        "prep.py": ("from sklearn.preprocessing import MinMaxScaler, StandardScaler\n"
                    "from sklearn.model_selection import train_test_split\n\n\n"
                    "def two_fits(a, b):\n"
                    "    first = StandardScaler().fit_transform(a)\n"
                    "    second = MinMaxScaler().fit_transform(b)\n"
                    "    return train_test_split(first, second)\n"),
    })
    notes = _of(doc, "untagged_dataflow")
    assert len(notes) == 1
    assert notes[0]["count"] == 2
    assert "`a`" in notes[0]["message"] and "`b`" in notes[0]["message"]


def test_the_summary_gives_coverage_its_own_block(analyze_ws, make_workspace):
    from mlview.api import render_summary
    doc = analyze_ws(LEAK_IN_A_HELPER)
    text = render_summary(doc)
    assert "Coverage (1)" in text
    assert "untagged_dataflow" in text


# --------------------------------------------------------- single_file_analysis
def test_one_file_of_a_package_says_what_it_could_not_see():
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(DIRTY, "train.py"),)))
    notes = _of(doc, "single_file_analysis")
    assert len(notes) == 1
    note = notes[0]
    assert note["file"] == "train.py"
    assert note["count"] == 4                      # the other four sample files
    assert note["codes"] == ["MLV301", "MLV302", "MLV401", "MLV501"]
    for name in ("config.py", "data.py", "model.py", "sklearn_baseline.py"):
        assert name in note["message"]
    assert validate(doc) == []


def test_the_named_codes_are_exactly_what_the_single_file_run_loses():
    """The roadmap's measured 57%: 7 findings in the directory, 3 alone."""
    whole = analyze_to_dict(AnalyzeOptions(paths=(DIRTY,), scope="file:train.py"))
    alone = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(DIRTY, "train.py"),)))
    lost = ({i["code"] for i in whole["issues"]}
            - {i["code"] for i in alone["issues"]})
    note = _of(alone, "single_file_analysis")[0]
    assert lost == set(note["codes"])
    assert len(whole["issues"]) == 7 and len(alone["issues"]) == 3


def test_the_whole_directory_carries_no_single_file_note():
    assert _of(analyze_to_dict(AnalyzeOptions(paths=(DIRTY,))),
               "single_file_analysis") == []


def test_a_standalone_script_with_no_siblings_is_not_warned_about(make_workspace):
    root = make_workspace({"solo.py": "import torch\nprint(torch.__version__)\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(root, "solo.py"),)))
    assert _of(doc, "single_file_analysis") == []


def test_a_file_that_imports_nothing_local_is_not_warned_about(make_workspace):
    """Siblings alone are not enough - crying wolf costs more than it buys."""
    root = make_workspace({
        "solo.py": "import torch\n\n\ndef main():\n    return torch.zeros(2)\n",
        "other.py": "VALUE = 1\n",
    })
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(root, "solo.py"),)))
    assert _of(doc, "single_file_analysis") == []


# ------------------------------------------------------------- the negative
@pytest.mark.parametrize("root", [DIRTY, CLEAN, TESTS_CLEAN],
                         ids=["dirty", "clean", "tests_clean"])
def test_the_shipped_corpora_gain_no_coverage_diagnostics(root):
    """COVERAGE never changes a rule's gate (roadmap acceptance)."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), max_nodes=4000))
    assert _of(doc, "untagged_dataflow") == []
    assert _of(doc, "single_file_analysis") == []


def test_the_dirty_sample_still_carries_exactly_fifteen_findings():
    doc = analyze_to_dict(AnalyzeOptions(paths=(DIRTY,)))
    assert len(doc["issues"]) == 15


def test_the_schema_accepts_every_new_kind():
    """All five values of amendment 11.18 are in both schema mirrors."""
    import json
    kinds = set()
    for path in (os.path.join(REPO_ROOT, "contracts", "graph.schema.json"),
                 os.path.join(REPO_ROOT, "analyzer", "src", "mlview", "schema",
                              "graph.schema.json")):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        enum = schema["$defs"]["Diagnostic"]["properties"]["kind"]["enum"]
        kinds.add(tuple(enum))
    assert len(kinds) == 1, "the two schema mirrors disagree"
    enum = set(kinds.pop())
    assert {"untagged_dataflow", "single_file_analysis", "unresolved_callee",
            "config_unresolved", "notebook_analyzed"} <= enum


# ------------------------------------- TB-10: coverage is not one rule pair wide
#: An untraced SPLIT, LOADER and FIT site, none of which MLV101/MLV102 gate on.
#: Before the post-rule sweep this workspace emitted `diagnostics: []` - a
#: clean-looking result from a run that could not check anything.
BLIND_SITES = {
    "t.py": ("import torch\n"
             "from torch.utils.data import DataLoader\n"
             "from sklearn.model_selection import train_test_split\n\n\n"
             "def make_loader(ds):\n"
             "    return DataLoader(ds, batch_size=32)\n\n\n"
             "def split_it(X, y):\n"
             "    return train_test_split(X, y, test_size=0.2)\n\n\n"
             "def fit_model(model, X, y):\n"
             "    model.fit(X, y)\n"
             "    return model\n"),
}


def test_an_untraced_split_loader_and_fit_are_each_declared(analyze_ws):
    doc = analyze_ws(BLIND_SITES)
    notes = _of(doc, "untagged_dataflow")
    assert sorted(n["scope"] for n in notes) == ["t.fit_model", "t.make_loader",
                                                 "t.split_it"]
    assert [n["kind"] for n in notes] == ["untagged_dataflow"] * 3
    by_scope = {n["scope"]: n for n in notes}
    assert "`ds`" in by_scope["t.make_loader"]["message"]
    assert "`X`" in by_scope["t.split_it"]["message"]
    # `model.fit` resolves to no FQN at all, so the role index never sees it -
    # the blindest site in the file was the one the role sweep could not reach.
    assert "`X`" in by_scope["t.fit_model"]["message"]
    # the sweep is a diagnostic, never a finding: no leakage rule fired here
    assert [i["code"] for i in doc["issues"] if i["code"].startswith("MLV1")] == []
    assert validate(doc) == []


def test_the_sweep_leaves_a_rules_own_note_carrying_its_codes(analyze_ws):
    """The post-pass folds into the rule's note; it does not shadow or double it."""
    doc = analyze_ws(LEAK_IN_A_HELPER)
    notes = _of(doc, "untagged_dataflow")
    assert len(notes) == 1
    assert notes[0]["codes"] == ["MLV101", "MLV102"]
    assert notes[0]["count"] == 1


def test_a_traced_split_and_loader_stay_silent(analyze_ws):
    """Coverage notes are a gap report, not a shape report."""
    doc = analyze_ws({
        "t.py": ("import numpy as np\n"
                 "from sklearn.model_selection import train_test_split\n\n\n"
                 "def main():\n"
                 "    raw = np.load('data.npy')\n"
                 "    X = raw[:, :-1]\n"
                 "    y = raw[:, -1]\n"
                 "    return train_test_split(X, y, test_size=0.2)\n"),
    })
    assert _of(doc, "untagged_dataflow") == []


# ------------------------- TB-11 / TB-15: a strict subset, on one path base
def _package(make_workspace):
    return make_workspace({
        "pkg/__init__.py": "",
        "pkg/data.py": ("import torch\n"
                        "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
                        "def build_loader():\n"
                        "    ds = TensorDataset(torch.zeros(8, 3), torch.zeros(8).long())\n"
                        "    return DataLoader(ds, batch_size=4, shuffle=True)\n"),
        "pkg/sub/__init__.py": "",
        "pkg/sub/model.py": ("import torch.nn as nn\n\n\n"
                             "class Net(nn.Module):\n"
                             "    def __init__(self):\n"
                             "        super().__init__()\n"
                             "        self.fc = nn.Linear(3, 2)\n\n"
                             "    def forward(self, x):\n"
                             "        return self.fc(x)\n"),
        "pkg/sub/train.py": ("import torch\n"
                             "from model import Net\n"
                             "from pkg.data import build_loader\n\n\n"
                             "def train():\n"
                             "    loader = build_loader()\n"
                             "    model = Net()\n"
                             "    opt = torch.optim.SGD(model.parameters(), lr=0.1)\n"
                             "    for features, labels in loader:\n"
                             "        opt.zero_grad()\n"
                             "        loss = torch.nn.functional.cross_entropy(\n"
                             "            model(features), labels)\n"
                             "        loss.backward()\n"
                             "        opt.step()\n"
                             "    return model\n"),
    })


def test_a_nested_sub_package_is_a_strict_subset_and_says_so(make_workspace):
    """The shape `mlview.currentFileAnalysisScope: "package"` produces."""
    root = _package(make_workspace)
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(root, "pkg", "sub"),)))
    notes = _of(doc, "single_file_analysis")
    assert len(notes) == 1, doc["diagnostics"]
    assert notes[0]["count"] == 2                    # pkg/__init__.py, pkg/data.py
    assert notes[0]["message"].startswith(
        "Only 3 of 5 modules in this package were analyzed")
    assert "pkg/data.py" in notes[0]["message"]
    assert validate(doc) == []


def test_the_message_names_the_analyzed_file_on_the_siblings_path_base(make_workspace):
    """TB-15: `train.py` and `pkg/sub/model.py` were two names for one directory."""
    root = _package(make_workspace)
    doc = analyze_to_dict(
        AnalyzeOptions(paths=(os.path.join(root, "pkg", "sub", "train.py"),)))
    message = _of(doc, "single_file_analysis")[0]["message"]
    assert message.startswith("Only pkg/sub/train.py was analyzed")
    assert "pkg/sub/model.py" in message
    assert "(train.py" not in message and " train.py " not in message


def test_the_whole_package_root_carries_no_subset_note(make_workspace):
    root = _package(make_workspace)
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(root, "pkg"),)))
    assert _of(doc, "single_file_analysis") == []
