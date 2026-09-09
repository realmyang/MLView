"""The Pipeline Answer Card (MLV-P1).

The acceptance from `docs/ROADMAP.md`: four sentences on `samples/vision_pipeline`
citing `data.py:26`, `data.py:31`, `train.py:23` and `train.py:44`; the clean
twin's evaluation answer saying the eval path is guarded; a workspace with no
eval stage naming the absence; and the four sentences in the MCP digest with
the digest still inside 4096 bytes.

The honesty rules are asserted as hard properties, because they are what make
the card worth more than a paragraph of prose: an absence is stated, nothing
under 0.6 node confidence is asserted as fact, and a ghost node - the marker
for something the analyzer did **not** find - is never cited as evidence.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import REPO_ROOT, validate
from mlview import api
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.emit import answers as answers_mod

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
CLEAN_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean")

NO_EVAL = {"train.py": (
    "import torch\nimport torch.nn as nn\nimport torch.optim as optim\n"
    "from torch.utils.data import DataLoader\n\n\n"
    "def train(ds):\n"
    "    model = nn.Linear(4, 2)\n"
    "    crit = nn.CrossEntropyLoss()\n"
    "    opt = optim.Adam(model.parameters())\n"
    "    loader = DataLoader(ds, batch_size=8)\n"
    "    for x, y in loader:\n"
    "        opt.zero_grad()\n"
    "        loss = crit(model(x), y)\n"
    "        loss.backward()\n"
    "        opt.step()\n"
    "    return model\n")}


@pytest.fixture(scope="module")
def sample():
    return analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,)))


@pytest.fixture(scope="module")
def clean():
    return analyze_to_dict(AnalyzeOptions(paths=(CLEAN_DIR,)))


def _locs(answer):
    return {"%s:%d" % (loc["file"], loc["line"]) for loc in answer["locs"]}


def _all_locs(answers):
    out = set()
    for field in answers_mod.FIELDS:
        out |= _locs(answers[field])
    return out


# ------------------------------------------------------------------- shape
def test_every_document_carries_four_answers(sample):
    answers = sample["answers"]
    assert list(answers) == ["dataEntry", "objective", "evaluation", "verdict"]
    for field, answer in answers.items():
        assert set(answer) == {"sentence", "nodeIds", "locs", "confidence"}, field
        assert answer["sentence"].endswith("."), field
        assert len(answer["nodeIds"]) == len(answer["locs"]), field
        assert 0.0 <= answer["confidence"] <= 1.0, field


def test_the_document_still_validates_with_answers(sample):
    assert validate(sample) == []


def test_the_four_sentences_cite_the_acceptance_lines(sample):
    """ROADMAP MLV-P1: data.py:26, data.py:31, train.py:23 and train.py:44."""
    cited = _all_locs(sample["answers"])
    for required in ("data.py:26", "data.py:31", "train.py:23", "train.py:44"):
        assert required in cited, (required, sorted(cited))


def test_data_entry_names_the_dataset_and_the_split(sample):
    answer = sample["answers"]["dataEntry"]
    assert "full_train at data.py:26" in answer["sentence"]
    assert "random_split() at data.py:31" in answer["sentence"]
    assert "data.py:26" in _locs(answer) and "data.py:31" in _locs(answer)


def test_the_objective_names_the_loss_and_the_optimizer_with_their_fqns(sample):
    answer = sample["answers"]["objective"]
    assert "criterion (torch.nn.CrossEntropyLoss) at train.py:22" in answer["sentence"]
    assert "optimizer (torch.optim.Adam) at train.py:23" in answer["sentence"]


def test_the_dirty_sample_says_the_eval_path_is_not_guarded(sample):
    answer = sample["answers"]["evaluation"]
    assert "train.py:44" in _locs(answer)
    assert "NOT guarded" in answer["sentence"]
    assert "model.eval()" in answer["sentence"]


def test_the_clean_twin_says_the_eval_path_is_guarded(clean):
    answer = clean["answers"]["evaluation"]
    assert "the eval path is guarded by" in answer["sentence"]
    assert "NOT guarded" not in answer["sentence"]


def test_the_verdict_ranks_by_severity_times_confidence(sample):
    answer = sample["answers"]["verdict"]
    assert answer["sentence"].startswith("15 finding(s): 5 high / 6 medium / 4 low.")
    assert "Fix first: MLV702 (high) at model.py:34" in answer["sentence"]
    assert len(answer["locs"]) == 3


def test_the_clean_twin_states_no_findings_without_claiming_more(clean):
    assert clean["answers"]["verdict"]["sentence"].startswith("No findings:")
    assert clean["answers"]["verdict"]["confidence"] == 0.0


# ----------------------------------------------------------------- honesty
def test_an_absent_stage_is_stated_as_an_absence(analyze_ws):
    doc = analyze_ws(NO_EVAL)
    answer = doc["answers"]["evaluation"]
    assert answer["sentence"].startswith("No evaluation stage was detected:")
    assert answer["nodeIds"] == [] and answer["locs"] == []
    assert answer["confidence"] == 0.0
    assert [s for s in doc["stages"] if s["id"] == "eval"][0]["present"] is False


def test_a_workspace_with_nothing_in_it_answers_all_four_as_absences(analyze_ws):
    doc = analyze_ws({"notes.py": "VALUE = 1\n"})
    for field in answers_mod.FIELDS:
        answer = doc["answers"][field]
        assert answer["confidence"] == 0.0
        assert answer["sentence"].startswith("No "), (field, answer["sentence"])


def test_a_ghost_node_is_never_cited_as_evidence(sample):
    ghosts = {n["id"] for n in sample["nodes"] if n["ghost"]}
    assert ghosts, "the dirty sample must carry ghosts for this to mean anything"
    for field in answers_mod.FIELDS:
        assert not (set(sample["answers"][field]["nodeIds"]) & ghosts), field


def test_nothing_under_the_confidence_floor_is_asserted():
    doc = {"nodes": [
        {"id": "n:a", "kind": "dataset", "label": "shaky", "stage": "data",
         "confidence": 0.4, "ghost": False, "loc": {"file": "a.py", "line": 3}},
    ], "issues": [], "diagnostics": []}
    answer = answers_mod.compose(doc)["dataEntry"]
    assert answer["nodeIds"] == []
    assert "No data entry was detected" in answer["sentence"]
    assert "below the 0.6 confidence floor" in answer["sentence"], \
        "silence about a dropped candidate is the failure this card exists to end"


def test_a_coverage_gap_stops_the_verdict_reading_as_a_clean_bill(make_workspace):
    """A single file of a package answers a smaller question; the verdict says so."""
    root = make_workspace({
        "pkg/__init__.py": "",
        "pkg/model.py": "import torch.nn as nn\n\n\nclass Net(nn.Module):\n    pass\n",
        "pkg/train.py": "from .model import Net\n\nNET = Net()\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(root, "pkg", "train.py"),)))
    coverage = [d for d in doc["diagnostics"]
                if d["kind"] in ("single_file_analysis", "untagged_dataflow")]
    if not coverage:                       # the fixture stopped being narrow
        pytest.skip("no coverage diagnostic on this fixture")
    assert "not a clean bill of health" in doc["answers"]["verdict"]["sentence"]


def test_composition_is_deterministic(sample):
    assert answers_mod.compose(sample) == answers_mod.compose(sample)
    assert json.dumps(answers_mod.compose(sample), sort_keys=True) == \
        json.dumps(sample["answers"], sort_keys=True)


# ------------------------------------------------------------- the surfaces
def test_the_summary_leads_with_the_answers(sample):
    text = api.render_summary(sample)
    body = text.split("\n")
    assert "Answers" in body
    assert body.index("Answers") < body.index("Stages")
    assert body.index("Answers") < body.index("Issues (15)")
    for field in ("data:", "objective:", "evaluation:", "verdict:"):
        assert any(line.strip().startswith(field) for line in body), field


def test_the_text_format_carries_the_same_block(sample):
    assert "Answers" in api.render_text(sample)


def test_a_document_without_answers_prints_no_block():
    """The hand-authored golden carries no `answers` key, and the renderer must
    not invent one - `--demo` byte parity is a gate."""
    doc = api.demo_dict()
    assert "answers" not in doc
    assert "Answers" not in api.render_summary(doc)


def test_the_digest_carries_the_four_sentences_inside_the_budget(sample):
    digest = api.digest(sample)
    assert set(digest["answers"]) == set(answers_mod.FIELDS)
    assert digest["answers"]["verdict"] == sample["answers"]["verdict"]["sentence"]
    size = len(json.dumps(digest, ensure_ascii=False).encode("utf-8"))
    assert size <= 4096, size


def test_the_digest_sheds_answers_last_and_never_busts_the_budget(sample):
    for budget in (2048, 1024, 512):
        small = api.digest(sample, limit_bytes=budget)
        assert len(json.dumps(small, ensure_ascii=False).encode("utf-8")) <= budget
    # The stated order: dataEntry and objective are the two an agent can most
    # cheaply re-derive from `lanes` and `topIssues`, so they go first.
    tight = api.digest(sample, limit_bytes=1300)
    if "answers" in tight and len(tight["answers"]) < 4:
        assert "verdict" in tight["answers"]
        assert "dataEntry" not in tight["answers"]


def test_a_projection_carries_the_answers_through_verbatim(sample):
    projected = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,),
                                               scope="stage:train"))
    assert projected["answers"] == sample["answers"], \
        "answers are project-level truth, like stages[].present"
    assert list(projected)[-1] == "view"


# --------------------------------------- 11.23 A8 on the answer surface
RESEARCH = {
    "registry.py": (
        "from dataclasses import dataclass, field\n"
        "from typing import Callable, Dict\n"
        "import torch\n"
        "from torch import nn\n\n"
        "BUILDERS: Dict[str, Callable] = {\"mlp\": lambda: nn.Linear(64, 2)}\n\n\n"
        "def make_model(name):\n"
        "    return BUILDERS[name]()\n\n\n"
        "def make_criterion(name):\n"
        "    match name:\n"
        "        case \"ce\":\n"
        "            fn = nn.CrossEntropyLoss\n"
        "        case _:\n"
        "            fn = nn.MSELoss\n"
        "    return fn()\n\n\n"
        "@dataclass\n"
        "class OptCfg:\n"
        "    lr: float = 1e-3\n"
        "    factory: Callable = field(default_factory=lambda: torch.optim.SGD)\n\n"
        "    def build(self, params):\n"
        "        return self.factory(params, lr=self.lr)\n"),
    "train.py": (
        "import torch\n"
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "from registry import OptCfg, make_criterion, make_model\n\n\n"
        "def loop(name=\"mlp\", epochs=3):\n"
        "    x, y = torch.randn(512, 64), torch.randint(0, 2, (512,))\n"
        "    dl = DataLoader(TensorDataset(x, y), batch_size=32, shuffle=True)\n"
        "    model = make_model(name)\n"
        "    criterion = make_criterion(\"ce\")\n"
        "    optimizer = OptCfg().build(model.parameters())\n"
        "    for _ in range(epochs):\n"
        "        for xb, yb in dl:\n"
        "            loss = criterion(model(xb), yb)\n"
        "            loss.backward()\n"
        "            optimizer.step()\n"),
}


def test_an_absence_is_never_claimed_flatly_while_a_call_went_unread(analyze_ws):
    """§11.23 A8 is normative for **every** emitter. The card used to say
    "nothing in the objective stage and no backward() call" about a file whose
    training loop calls `loss.backward()` on line 14 - not a hedged absence but
    a false statement about the source, shipped in the report card,
    `--format summary`, `--format text` and `api.digest`."""
    doc = analyze_ws(RESEARCH)
    kinds = {d["kind"] for d in doc["diagnostics"]}
    assert "unresolved_callee" in kinds, sorted(kinds)
    objective = doc["answers"]["objective"]["sentence"]
    assert "no backward() call" not in objective, objective
    assert "could not be read" in objective, objective
    evaluation = doc["answers"]["evaluation"]["sentence"]
    assert "is not measured anywhere MLView can see" not in evaluation, evaluation
    assert "could not be read" in evaluation, evaluation
    assert doc["answers"]["objective"]["sentence"] == \
        api.digest(doc)["answers"]["objective"]


def test_the_flat_absence_still_stands_when_everything_resolved(analyze_ws):
    """The qualifier is earned, not automatic: with nothing unread the card
    keeps saying so plainly, and the default path is byte-identical."""
    doc = analyze_ws({"m.py": "import pandas as pd\n\n\n"
                              "def load(path):\n"
                              "    return pd.read_csv(path)\n"})
    assert not [d for d in doc["diagnostics"] if d["kind"] == "unresolved_callee"]
    assert "no backward() call" in doc["answers"]["objective"]["sentence"]
