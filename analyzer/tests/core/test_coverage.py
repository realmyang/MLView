"""COVERAGE: "I could not check" must not look like "I checked and it is fine".

Two `Diagnostic.kind` values added by CONTRACTS amendment 11.18 and emitted
here: `untagged_dataflow` (a leakage rule reached a value it never traced) and
`single_file_analysis` (one file of a package was analyzed).

The load-bearing negative is at the bottom: neither diagnostic changes a rule's
gate, so `samples/vision_pipeline` still carries exactly its fifteen findings
and both clean corpora stay silent.
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
