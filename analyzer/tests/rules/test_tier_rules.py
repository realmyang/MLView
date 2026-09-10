"""The ANA-7 / ANA-8 / ANA-9 rule tiers, rule by rule (CONTRACTS 11.26).

`test_seed_rules.py::test_every_fixture_pair_behaves` already runs every
`<CODE>_bad` / `<CODE>_good` pair on disk, and `test_registry_complete.py`
enforces the authoring checklist. This module asserts the things that are
specific to these sixteen findings and would otherwise only be checked by
reading the code: the variant tags, the named `relatedLocs`, the de-rating that
must **not** become a suppression, the carve-outs that must be exhaustive, and -
the point of the whole tier - that none of them moves the shipped demo or the
precision corpus.
"""

from __future__ import annotations

import os

import pytest

from mlview.rules.registry import rule_for
from rule_harness import (CLEAN_DIR, SAMPLES_DIR, analyze_fixture, analyze_paths,
                          assert_fires, assert_silent, describe, write_workspace)

ANA7 = ("MLV705", "MLV706", "MLV707", "MLV708", "MLV709", "MLV711")
ANA8 = ("MLV207", "MLV208", "MLV209", "MLV502", "MLV803")
ANA9 = ("MLV106", "MLV114", "MLV121", "MLV305", "MLV306")
TIER = ANA7 + ANA8 + ANA9


# --------------------------------------------------------------- declarations
@pytest.mark.parametrize("code", TIER)
def test_every_tier_rule_is_registered_and_enabled(code):
    spec = rule_for(code)
    assert spec is not None, "%s is not registered" % code
    assert spec.enabled, "%s ships disabled" % code
    assert spec.module in ("mlview.rules.r_framework", "mlview.rules.r_mechanics",
                           "mlview.rules.r_holdout"), spec.module


@pytest.mark.parametrize("code", ANA7)
def test_no_framework_rule_is_gated_by_the_framework_it_is_about(code):
    """Iron law 4 silences the *torch loop* rules on a wrapped project. A rule
    whose subject **is** the wrapper must not be de-rated by its presence, or
    ANA-7 reproduces the empty Problems panel it exists to fix."""
    spec = rule_for(code)
    assert not spec.absence, "%s must not declare absence=True" % code


@pytest.mark.parametrize("code", ANA7)
def test_every_framework_finding_is_visible_in_the_problems_panel(code):
    """0.6 is `mlview.minConfidence`; below it a finding is emitted and unseen."""
    issue = assert_fires("%s_bad" % code).of(code)[0]
    assert issue["confidence"] >= 0.6, describe({"issues": [issue]})


# ------------------------------------------------------------ ANA-7 specifics
def test_mlv705_is_a_workspace_claim_and_one_compile_anywhere_silences_it(tmp_path):
    root = write_workspace(str(tmp_path), {
        "model.py": ("from tensorflow import keras\n"
                     "from tensorflow.keras import layers\n\n\n"
                     "def build():\n"
                     "    model = keras.Sequential([layers.Dense(3)])\n"
                     "    return model\n"),
        "train.py": ("from model import build\n\n\n"
                     "def main(x, y):\n"
                     "    model = build()\n"
                     "    model.fit(x, y, epochs=2)\n"
                     "    return model\n"),
    })
    doc = analyze_paths(root)
    assert [i["code"] for i in doc["issues"] if i["code"] == "MLV705"] == ["MLV705"]

    compiled = write_workspace(str(tmp_path / "compiled"), {
        "model.py": ("from tensorflow import keras\n"
                     "from tensorflow.keras import layers\n\n\n"
                     "def build():\n"
                     "    model = keras.Sequential([layers.Dense(3)])\n"
                     "    model.compile(optimizer=\"adam\", loss=\"mse\")\n"
                     "    return model\n"),
        "train.py": ("from model import build\n\n\n"
                     "def main(x, y):\n"
                     "    model = build()\n"
                     "    model.fit(x, y, epochs=2)\n"
                     "    return model\n"),
    })
    assert not [i for i in analyze_paths(compiled)["issues"] if i["code"] == "MLV705"]


def test_mlv706_names_the_training_step_and_the_manual_update():
    issue = assert_fires("MLV706_bad").of("MLV706")[0]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"definition", "backward_site"} <= roles
    assert "automatic_optimization" in issue["fixHint"]


def test_mlv707_accepts_a_dict_return_and_rejects_a_silent_one():
    assert assert_fires("MLV707_bad").of("MLV707")
    assert_silent("MLV707_good", "MLV707")


def test_mlv708_stays_quiet_when_the_arguments_cannot_be_resolved(tmp_path):
    """Unresolvable is not absent: a Trainer whose `args=` came from a helper is
    not judged, because the evaluation strategy might well be set in there."""
    root = write_workspace(str(tmp_path), {
        "train.py": ("from transformers import Trainer, set_seed\n\n"
                     "from cfg import make_args\n\n\n"
                     "def run(model, data):\n"
                     "    set_seed(0)\n"
                     "    trainer = Trainer(model=model, args=make_args(),\n"
                     "                      train_dataset=data)\n"
                     "    trainer.train()\n"
                     "    return trainer\n"),
        "cfg.py": ("from transformers import TrainingArguments\n\n\n"
                   "def make_args():\n"
                   "    return TrainingArguments(output_dir=\"out\")\n"),
    })
    assert not [i for i in analyze_paths(root)["issues"] if i["code"] == "MLV708"]


def test_mlv709_pairs_by_activation_family_not_by_proximity():
    """The good fixture holds a softmax head and a from_logits=True loss in one
    module; they belong to different families and must not be paired."""
    run = assert_silent("MLV709_good", "MLV709")
    source = open(run.path, encoding="utf-8").read()
    assert "from_logits=True" in source and "activation=\"softmax\"" in source


def test_mlv709_does_not_pair_two_models_that_live_in_one_module():
    """A `models.py` holding a probs head and a logits head of the same
    categorical problem is an ordinary shape. Family-only pairing accused the
    correct softmax head of contradicting the *other* model's loss, at severity
    high and confidence 0.95 - published in every host."""
    run = assert_silent("MLV709_two_heads_good", "MLV709")
    source = open(run.path, encoding="utf-8").read()
    assert source.count("CategoricalCrossentropy") == 2
    assert "from_logits=True" in source and "activation=\"softmax\"" in source


def test_mlv709_only_judges_the_layer_the_model_outputs():
    """A squeeze-and-excite `Dense(ch, activation="sigmoid")` is a channel gate
    multiplied back into the feature map, not an output activation - and the
    head under it is linear, which is what from_logits=True wants."""
    run = assert_silent("MLV709_se_gate_good", "MLV709")
    source = open(run.path, encoding="utf-8").read()
    assert "activation=\"sigmoid\"" in source and "from_logits=True" in source


def test_mlv709_names_the_model_the_layer_and_the_loss_meet_on():
    issue = assert_fires("MLV709_bad").of("MLV709")[0]
    roles = [r["role"] for r in issue["relatedLocs"]]
    assert roles.count("definition") == 1, roles
    assert "output" in issue["message"]


def test_mlv709_cites_the_layer_and_the_loss():
    issue = assert_fires("MLV709_bad").of("MLV709")[0]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"final_layer", "construction"} <= roles
    assert issue["severity"] == "high"


def test_mlv121_does_not_call_a_lone_take_a_holdout():
    """`for images, labels in train_ds.take(1)` is a peek at one batch, and a
    debug subset with no complementary skip is a debug subset. Neither has two
    halves to re-draw, so the message the rule would print - "take(1) carves out
    the holdout ... so the two halves are re-drawn every epoch" - would be a
    false statement about the source."""
    for fixture in ("MLV121_peek_good", "MLV121_debug_subset_good"):
        run = assert_silent(fixture, "MLV121")
        source = open(run.path, encoding="utf-8").read()
        assert ".shuffle(" in source and ".take(" in source and ".skip(" not in source


def test_mlv121_cites_both_halves_of_the_holdout_it_found():
    issue = assert_fires("MLV121_bad").of("MLV121")[0]
    split_sites = [r for r in issue["relatedLocs"] if r["role"] == "split_site"]
    assert len(split_sites) == 2, issue["relatedLocs"]
    assert "take() and skip()" in " ".join(e["detail"] for e in issue["evidence"])


def test_mlv711_only_fires_for_a_batch_cadence_scheduler(tmp_path):
    root = write_workspace(str(tmp_path), {
        "lit.py": ("import pytorch_lightning as pl\n"
                   "import torch\n"
                   "import torch.nn as nn\n\n\n"
                   "class Lit(pl.LightningModule):\n"
                   "    def __init__(self):\n"
                   "        super().__init__()\n"
                   "        self.head = nn.Linear(4, 2)\n\n"
                   "    def training_step(self, batch, idx):\n"
                   "        return self.head(batch[0]).sum()\n\n"
                   "    def configure_optimizers(self):\n"
                   "        opt = torch.optim.SGD(self.parameters(), lr=0.1)\n"
                   "        sched = torch.optim.lr_scheduler.StepLR(opt, step_size=1)\n"
                   "        return [opt], [sched]\n"),
    })
    assert not [i for i in analyze_paths(root)["issues"] if i["code"] == "MLV711"]


# ------------------------------------------------------------ ANA-8 specifics
def test_mlv208_derates_a_non_literal_enabled_flag_and_never_suppresses_it(tmp_path):
    """ROADMAP ANA-8: `GradScaler(enabled=cfg.train.amp)` is the corpus's real
    shape and must **de-rate, not suppress**; `enabled=False` does suppress."""
    body = ("import torch\n"
            "import torch.nn as nn\n"
            "import torch.optim as optim\n"
            "from torch.amp import GradScaler\n"
            "from torch.utils.data import DataLoader\n\n\n"
            "def train(dataset, cfg):\n"
            "    torch.manual_seed(0)\n"
            "    model = nn.Sequential(nn.Linear(4, 2))\n"
            "    criterion = nn.CrossEntropyLoss()\n"
            "    optimizer = optim.SGD(model.parameters(), lr=0.1)\n"
            "    scaler = GradScaler(%s)\n"
            "    loader = DataLoader(dataset, batch_size=8, shuffle=True)\n"
            "    for x, y in loader:\n"
            "        optimizer.zero_grad(set_to_none=True)\n"
            "        loss = criterion(model(x), y)\n"
            "        loss.backward()\n"
            "        scaler.step(optimizer)\n"
            "        scaler.update()\n"
            "    return model\n")
    plain = write_workspace(str(tmp_path / "plain"), {"t.py": body % "\"cpu\""})
    derated = write_workspace(str(tmp_path / "derated"),
                              {"t.py": body % "enabled=cfg.amp"})
    off = write_workspace(str(tmp_path / "off"), {"t.py": body % "enabled=False"})

    full = [i for i in analyze_paths(plain)["issues"] if i["code"] == "MLV208"]
    soft = [i for i in analyze_paths(derated)["issues"] if i["code"] == "MLV208"]
    none = [i for i in analyze_paths(off)["issues"] if i["code"] == "MLV208"]
    assert len(full) == 1 and len(soft) == 1 and none == []
    assert soft[0]["confidence"] < full[0]["confidence"], "the flag must de-rate"
    assert soft[0]["confidence"] > 0.0, "the flag must not suppress"


def test_mlv209_never_reads_across_two_blocks():
    """The clip in the good fixture sits between backward and step in one block;
    the accumulation fixture spreads them over two and must stay silent."""
    assert_silent("MLV209_good", "MLV209")
    assert_silent("MLV208_good", "MLV209", "MLV208")


def test_mlv502_reads_the_literal_at_the_call_site_only(tmp_path):
    """`torch.device(DEVICE)` with `DEVICE = "cuda"` in a config module is a
    configuration decision, not a hard-coded device - and it is exactly what
    samples/vision_pipeline writes, so the demo must not move."""
    root = write_workspace(str(tmp_path), {
        "config.py": "DEVICE = \"cuda\"\n",
        "train.py": ("import torch\n\n"
                     "from config import DEVICE\n\n\n"
                     "def setup(model):\n"
                     "    torch.manual_seed(0)\n"
                     "    device = torch.device(DEVICE)\n"
                     "    return model.to(device)\n"),
    })
    assert not [i for i in analyze_paths(root)["issues"] if i["code"] == "MLV502"]


def test_mlv502_reports_one_finding_per_module_not_one_per_move():
    run = assert_fires("MLV502_bad")
    hits = run.of("MLV502")
    assert len(hits) == 1, "one root cause, one finding: %s" % run.summary()
    assert any(r["role"] == "call_site" for r in hits[0]["relatedLocs"])


def test_mlv803_reports_both_variants_at_distinct_locations():
    hits = assert_fires("MLV803_bad").of("MLV803")
    assert len(hits) == 2
    tags = {t for hit in hits for t in hit["tags"]}
    assert {"whole_model", "unsafe_load"} <= tags
    assert len({hit["loc"]["line"] for hit in hits}) == 2


# ------------------------------------------------------------ ANA-9 specifics
def test_mlv106_needs_two_independent_temporal_signals(tmp_path):
    one = write_workspace(str(tmp_path / "one"), {
        "t.py": ("import pandas as pd\n"
                 "from sklearn.model_selection import train_test_split\n\n\n"
                 "def split(path):\n"
                 "    frame = pd.read_csv(path)\n"
                 "    frame[\"ts\"] = pd.to_datetime(frame[\"ts\"])\n"
                 "    return train_test_split(frame, test_size=0.2, random_state=0)\n"),
    })
    assert not [i for i in analyze_paths(one)["issues"] if i["code"] == "MLV106"]
    assert assert_fires("MLV106_bad").of("MLV106")


def test_mlv305_never_fires_on_a_score_metric():
    """The carve-out is exhaustive by construction: it is a frozen set checked
    before the class-metric list, and roc_auc_score is not on that list."""
    from mlview.rules.r_holdout import _CLASS_METRICS, _SCORE_METRICS
    assert not (_CLASS_METRICS & _SCORE_METRICS)
    for name in ("roc_auc_score", "average_precision_score", "log_loss"):
        assert "sklearn.metrics.%s" % name in _SCORE_METRICS
    assert_silent("MLV305_good", "MLV305")


def test_mlv305_derates_an_unproduced_prediction(tmp_path):
    """A prediction that arrives as a parameter carries its tag but no producer;
    DATAFLOW-IP is what would resolve it, so until then the finding is weaker,
    never absent."""
    run = assert_fires("MLV305_bad")
    inline = run.of("MLV305")[0]
    assert inline["confidence"] >= 0.6
    assert any("de-rated" not in e["detail"] for e in inline["evidence"])


def test_mlv306_reads_the_producer_not_the_metric_name():
    assert assert_fires("MLV306_bad").of("MLV306")
    assert_silent("MLV306_good", "MLV306", "MLV305")


def test_mlv114_does_not_judge_a_dataset_that_is_split_afterwards():
    """samples/vision_pipeline augments `full_train` and then random_splits it
    into a training and a validation half. Which half inherits what is not
    knowable here, so MLV114 says nothing - and the demo keeps its 15 findings."""
    doc = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline"))
    assert not [i for i in doc["issues"] if i["code"] == "MLV114"]
    assert len(doc["issues"]) == 15, describe(doc)


def test_mlv121_fires_once_per_shuffle_however_many_holdouts_follow():
    hits = assert_fires("MLV121_bad").of("MLV121")
    assert len(hits) == 1, "take() and skip() share one root cause"
    roles = {r["role"] for r in hits[0]["relatedLocs"]}
    assert "split_site" in roles


# ------------------------------------------------------------- the two gates
def test_the_precision_corpus_is_untouched_by_the_new_tiers():
    doc = analyze_paths(CLEAN_DIR)
    new = [i for i in doc["issues"] if i["code"] in TIER]
    assert new == [], describe(doc)


@pytest.mark.parametrize("name", ["lightning_module.py", "hf_trainer.py"])
def test_the_two_framework_files_stay_at_zero_findings_alone(name):
    """ANA-7's shared acceptance names these two files explicitly."""
    doc = analyze_paths(os.path.join(CLEAN_DIR, name))
    assert doc["issues"] == [], describe(doc)


def test_the_shipped_demo_is_byte_for_byte_the_same_fifteen():
    doc = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline"))
    assert len(doc["issues"]) == 15, describe(doc)
    assert not [i for i in doc["issues"] if i["code"] in TIER], describe(doc)
    clean = analyze_paths(os.path.join(SAMPLES_DIR, "vision_pipeline_clean"))
    assert clean["issues"] == [], describe(clean)


# ------------------------------------------- ANA8-201: the full-batch shape
def test_a_full_batch_training_loop_is_not_judged_but_is_never_silent(tmp_path):
    """MLV201 needs a DataLoader-driven batch loop. A tabular / full-batch loop
    written `for epoch in range(20)` with backward + step and no zero_grad is a
    genuine high-severity defect that the rule cannot confirm - and it used to
    produce zero findings AND zero diagnostics, which is the one outcome the
    standing acceptance criterion forbids."""
    full_batch = write_workspace(str(tmp_path / "full"), {
        "m.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n\n"
                 "torch.manual_seed(0)\n"
                 "model = nn.Sequential(nn.Linear(10, 3))\n"
                 "criterion = nn.CrossEntropyLoss()\n"
                 "optimizer = optim.Adam(model.parameters(), lr=1e-3)\n"
                 "xb = torch.randn(64, 10)\n"
                 "yb = torch.randint(0, 3, (64,))\n"
                 "for epoch in range(20):\n"
                 "    loss = criterion(model(xb), yb)\n"
                 "    loss.backward()\n"
                 "    optimizer.step()\n")})
    doc = analyze_paths(full_batch)
    assert not [i for i in doc["issues"] if i["code"] == "MLV201"]
    notes = [d for d in doc["diagnostics"]
             if "could not confirm it as a training loop" in d["message"]]
    assert len(notes) == 1, doc["diagnostics"]
    assert notes[0]["kind"] == "untagged_dataflow"
    assert notes[0]["codes"] == ["MLV201", "MLV202", "MLV203"]

    # ...and a confirmed batch loop is judged, with no such note.
    batched = write_workspace(str(tmp_path / "batched"), {
        "m.py": ("import torch\n"
                 "import torch.nn as nn\n"
                 "import torch.optim as optim\n"
                 "from torch.utils.data import DataLoader, TensorDataset\n\n"
                 "torch.manual_seed(0)\n"
                 "model = nn.Sequential(nn.Linear(10, 3))\n"
                 "criterion = nn.CrossEntropyLoss()\n"
                 "optimizer = optim.Adam(model.parameters(), lr=1e-3)\n"
                 "ds = TensorDataset(torch.randn(64, 10), torch.randint(0, 3, (64,)))\n"
                 "dl = DataLoader(ds, batch_size=8, shuffle=True)\n"
                 "for xb, yb in dl:\n"
                 "    loss = criterion(model(xb), yb)\n"
                 "    loss.backward()\n"
                 "    optimizer.step()\n")})
    other = analyze_paths(batched)
    assert [i["code"] for i in other["issues"] if i["code"] == "MLV201"] == ["MLV201"]
    assert not [d for d in other["diagnostics"]
                if "could not confirm it as a training loop" in d["message"]]
