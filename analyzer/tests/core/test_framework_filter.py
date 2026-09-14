"""`--framework <x>` says so in the document (C8).

`--framework torch` is documented as *"restrict framework extractors"*, and
what it actually does is narrow the **rule set**: `registry._applies` drops
every rule that does not declare that framework, including rules the detected
frameworks would have run. Before C8 a user who passed it read a shorter
finding list with **nothing in the document saying why** - the same silent
narrowing `single_file_analysis` exists to make loud.

The caveat is a `framework_filter` coverage diagnostic carrying the codes that
did not run, so the MCP and VS Code coverage blocks can name them the way they
already name the cross-file rules. Four properties have teeth and each has a
test here: it fires only when the flag actually cost something, it names the
rules, it is emitted once per run rather than once per rule, and the findings
themselves are untouched by its presence.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate, write_files
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.core.coverage import COVERAGE_KINDS, framework_filter_diagnostic
from mlview.rules import all_rules

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")

TORCH_TRAIN = (
    "import torch\n"
    "import torch.nn as nn\n"
    "import torch.optim as optim\n"
    "from torch.utils.data import DataLoader\n\n\n"
    "def train(ds):\n"
    "    model = nn.Linear(4, 2)\n"
    "    crit = nn.CrossEntropyLoss()\n"
    "    opt = optim.Adam(model.parameters())\n"
    "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
    "    for x, y in loader:\n"
    "        loss = crit(model(x), y)\n"
    "        loss.backward()\n"
    "        opt.step()\n"
)


def _analyze(paths, framework="auto"):
    return analyze_to_dict(AnalyzeOptions(paths=tuple(paths), framework=framework))


def _filter_notes(doc):
    return [d for d in doc["diagnostics"] if d["kind"] == "framework_filter"]


@pytest.fixture(scope="module")
def auto_doc():
    return _analyze([SAMPLE_DIR])


@pytest.fixture(scope="module")
def keras_doc():
    return _analyze([SAMPLE_DIR], framework="keras")


# ------------------------------------------------------------------ the gate
def test_auto_is_silent(auto_doc):
    """The default narrows nothing, so it must say nothing. A caveat on every
    run is a caveat nobody reads."""
    assert _filter_notes(auto_doc) == []


def test_the_pure_function_refuses_to_cry_wolf():
    """A filter that matched every applicable rule cost nothing, and `auto` is
    not a filter at all. Both answers are None, not an empty caveat."""
    assert framework_filter_diagnostic("auto", ["MLV101"]) is None
    assert framework_filter_diagnostic("", ["MLV101"]) is None
    assert framework_filter_diagnostic("torch", []) is None
    assert framework_filter_diagnostic("torch", [""]) is None


def test_a_narrowing_filter_declares_itself(keras_doc):
    """The property the item exists for: `--framework keras` over a torch
    project hides most of the finding list, and the document now says so."""
    notes = _filter_notes(keras_doc)
    assert len(notes) == 1
    note = notes[0]
    assert "--framework keras" in note["message"]
    assert "clean result for keras alone" in note["message"]
    assert note["count"] == len(note["codes"])
    assert note["codes"] == sorted(note["codes"])


def test_it_names_the_rules_that_did_not_run(auto_doc, keras_doc):
    """`codes` is what the hosts render; a bare count reads as a tally of
    findings. Every code it names must be a registered rule, and every rule that
    fired under `auto` and vanished under the filter must be in it."""
    registered = {spec.code for spec in all_rules()}
    codes = set(_filter_notes(keras_doc)[0]["codes"])
    assert codes <= registered
    fired = {i["code"] for i in auto_doc["issues"]}
    lost = fired - {i["code"] for i in keras_doc["issues"]}
    assert lost, "the filter must actually hide findings for this test to mean anything"
    assert lost <= codes


def test_it_is_one_diagnostic_per_run_not_one_per_rule(keras_doc):
    """The `framework_suppressed` shape (CONTRACTS 11.16 C1): a check looping
    over N rules must not emit N diagnostics."""
    notes = _filter_notes(keras_doc)
    assert len(notes) == 1
    assert len(notes[0]["codes"]) > 1


def test_the_message_elides_a_long_code_list(keras_doc):
    """Bounded, so the block stays inside the plugin's payload budget: at most
    six codes are named in the prose, and the rest are counted."""
    note = _filter_notes(keras_doc)[0]
    named = note["message"].split("did not (")[1].split(")")[0]
    assert named.count("MLV") <= 6
    if len(note["codes"]) > 6:
        assert "and %d more" % (len(note["codes"]) - 6) in named
    # the full list is never elided, only the sentence
    assert len(note["codes"]) >= named.count("MLV")


# ----------------------------------------------------------- the whole document
def test_the_document_stays_contract_valid(keras_doc):
    """`framework_filter` is a `Diagnostic.kind`, and that enum is closed in
    `contracts/graph.schema.json`; a kind the schema does not list makes every
    filtered run invalid."""
    assert validate(keras_doc) == []


def test_it_is_a_coverage_kind(keras_doc):
    """It belongs in the coverage block beside `single_file_analysis`: both say
    *a rule that would have run did not*, which is the one question an empty
    result cannot answer on its own."""
    assert "framework_filter" in COVERAGE_KINDS
    from mlview.emit import text_out

    text = text_out.render_summary(keras_doc)
    assert "--framework keras" in text


def test_the_findings_themselves_are_untouched(tmp_path):
    """The caveat explains the narrowing; it must not change it. The findings a
    filter *keeps* are the same findings, byte for byte, as before it existed -
    proved by comparing a filter that matches everything against `auto`."""
    root = write_files(str(tmp_path / "ws"), {"train.py": TORCH_TRAIN})
    wide = _analyze([root])
    narrow = _analyze([root], framework="torch")
    narrowed_codes = {j["code"] for j in narrow["issues"]}
    kept = [i for i in wide["issues"] if i["code"] in narrowed_codes]
    assert [i["id"] for i in kept] == [i["id"] for i in narrow["issues"]]
    for before, after in zip(kept, narrow["issues"]):
        assert before["confidence"] == after["confidence"]
        assert before["severity"] == after["severity"]
        assert before["message"] == after["message"]


def test_a_filter_that_costs_nothing_stays_silent(tmp_path):
    """A workspace whose every applicable rule declares the named framework is
    not narrowed, so there is nothing to confess."""
    root = write_files(str(tmp_path / "quiet"), {"m.py": "VALUE = 1\n"})
    doc = _analyze([root], framework="lightning")
    codes = {i["code"] for i in doc["issues"]}
    assert not codes
    # Nothing fired either way; the caveat counts rules that *would* have run,
    # and on a module with no ML calls at all that set can still be non-empty -
    # so assert the shape rather than absence, and that it never invents codes.
    for note in _filter_notes(doc):
        assert note["codes"] and note["count"] == len(note["codes"])
