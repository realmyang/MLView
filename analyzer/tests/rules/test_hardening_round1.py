"""Regression tests for the hardening campaign, round 1 (analyzer).

One test per confirmed finding, each asserting the *observed vs expected* pair
the finding recorded. The `_good.py` / `_bad.py` fixtures beside them carry the
shapes; this module pins the behaviour those shapes are about, including the
parts a fixture header cannot express - a `Node.kind`, a diagnostic, a stage's
`present` flag, a knowledge row, an id invariant.

Findings covered here: PUB-01, PUB-02, PUB-03, PUB-04, PUB-05, PUB-06, PUB-07,
PUB-08, PUB-09, PUB-10, PUB-11, PUB-14, PUB-15, NLP-01, NLP-02, NLP-09, NLP-14,
TAB-01, TAB-12, DGRG-01, DGRG-02, DGRG-11, INFRA-01, INFRA-02, INFRA-03,
INFRA-04, INFRA-13, ROB-03, ROB-10, vision-01, vision-03, vision-05, vision-06,
vision-10, vision-11, vision-12, vision-13, vision-14, vision-16.

PUB-14 and PUB-15 were found by the integrator, by the public-corpus gate, on
the code the other findings' fixes produced - which is the only reason the
gate exists.

`analyzer/tests/core/test_hardening_robustness.py` owns ROB-01, ROB-02, ROB-04,
ROB-05, ROB-12 and ROB-13; those were `xfail` there and are plain tests now.
"""

from __future__ import annotations

import collections
import os

import pytest

from mlview import knowledge as K
from rule_harness import analyze_fixture, analyze_paths, write_workspace


def _ws(tmp_path, files):
    """`write_workspace` needs a root; every test here gets pytest's tmp_path."""
    return write_workspace(str(tmp_path), files)

FIXTURES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))
RULES = os.path.join(FIXTURES, "rules")


def _codes(doc, *want):
    return [i["code"] for i in doc["issues"] if not want or i["code"] in want]


def _issues(doc, code):
    return [i for i in doc["issues"] if i["code"] == code]


def _kinds(doc):
    return {d["kind"] for d in doc["diagnostics"]}


def _stage(doc, stage_id):
    return next(s for s in doc["stages"] if s["id"] == stage_id)


# ---------------------------------------------------------------- PUB-01
def test_pub01_a_producer_below_the_use_does_not_reach_it():
    """`loss = bce(pred, true)` then `pred = torch.sigmoid(pred)` is correct."""
    doc = analyze_paths(os.path.join(RULES, "MLV402_blur_good.py"))
    assert _codes(doc, "MLV401", "MLV402") == []


def test_pub01_a_real_double_sigmoid_still_fires():
    """The guard narrows the producer search; it must not disarm the rule."""
    doc = analyze_fixture("MLV402_bad").doc
    assert _issues(doc, "MLV402"), "MLV402 must still fire on its own bad fixture"


# --------------------------------------------------------- PUB-02 / ROB-10
@pytest.mark.parametrize("dataflow", ["local", "ip"])
def test_rob10_an_estimator_fit_is_not_a_preprocessing_fit(dataflow):
    doc = analyze_paths(os.path.join(RULES, "MLV101_estimator_good.py"),
                        dataflow=dataflow)
    assert _codes(doc, "MLV101", "MLV103") == []


def test_pub02_a_transformer_fit_before_the_split_still_fires():
    doc = analyze_fixture("MLV101_bad").doc
    assert _issues(doc, "MLV101"), "the flagship leakage rule must still fire"


# --------------------------------------------------------- PUB-03 / PUB-04
@pytest.mark.parametrize("dataflow", ["local", "ip"])
def test_pub03_two_sections_sharing_a_name_are_not_one_leak(dataflow):
    doc = analyze_paths(os.path.join(RULES, "MLV101_sections_good.py"),
                        dataflow=dataflow)
    assert _codes(doc, "MLV101", "MLV102") == []


def test_pub04_a_target_column_fit_is_de_rated_rather_than_high(tmp_path):
    """FP-note (c): `LabelEncoder().fit(df["label"])` is medium x0.6, not high."""
    workspace = _ws(tmp_path, {"m.py": (
        "import pandas as pd\n"
        "from sklearn.model_selection import train_test_split\n"
        "from sklearn.preprocessing import LabelEncoder\n"
        "\n"
        "frame = pd.read_csv('eeg.csv')\n"
        "le = LabelEncoder()\n"
        "le.fit(frame['label'])\n"
        "frame['label'] = le.transform(frame['label'])\n"
        "train, test = train_test_split(frame, test_size=0.2, random_state=0)\n"
    )})
    doc = analyze_paths(workspace, dataflow="ip")
    for issue in _issues(doc, "MLV101"):
        assert issue["severity"] == "medium", issue["message"]
        assert issue["confidence"] < 0.6, issue["confidence"]


# ---------------------------------------------------------------- PUB-05
def test_pub05_a_pytest_case_is_not_an_evaluation_loop():
    doc = analyze_paths(os.path.join(RULES, "MLV301_tests_good"))
    assert _codes(doc, "MLV301", "MLV302") == []


def test_pub05_a_name_alone_cannot_mint_an_eval_region(tmp_path):
    """An eval-shaped name with no no-grad, no metric and no eval() stays quiet."""
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "net = nn.Sequential(nn.Linear(4, 2), nn.Dropout(0.2))\n"
        "\n"
        "def predict_shapes():\n"
        "    out = net(torch.randn(3, 4))\n"
        "    return out.shape\n"
    )})
    doc = analyze_paths(workspace)
    assert _codes(doc, "MLV301", "MLV302") == []


# ---------------------------------------------------------------- PUB-06
def test_pub06_an_order_preserving_splitter_does_not_shuffle():
    doc = analyze_paths(os.path.join(RULES, "MLV106_timeseries_good.py"))
    assert _codes(doc, "MLV106") == []


def test_pub06_a_genuinely_random_split_on_a_series_still_fires():
    doc = analyze_fixture("MLV106_bad").doc
    assert _issues(doc, "MLV106")


# ---------------------------------------------------------------- PUB-07
def test_pub07_manual_optimization_may_return_no_loss():
    doc = analyze_paths(os.path.join(RULES, "MLV707_manual_good.py"))
    assert _codes(doc, "MLV707") == []


def test_pub07_automatic_optimization_still_requires_a_loss():
    doc = analyze_fixture("MLV707_bad").doc
    assert _issues(doc, "MLV707")


# ------------------------------------------------------- PUB-08 / INFRA-01
def test_pub08_a_detached_scalar_accumulator_is_not_a_leak():
    doc = analyze_paths(os.path.join(RULES, "MLV205_scalar_good.py"))
    assert _codes(doc, "MLV205") == []


def test_infra01_an_accumulation_under_no_grad_is_not_a_leak(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "def score(model, loader, criterion):\n"
        "    model.eval()\n"
        "    total = 0.0\n"
        "    with torch.no_grad():\n"
        "        for x, y in loader:\n"
        "            total += criterion(model(x), y)\n"
        "    return total\n"
    )})
    doc = analyze_paths(workspace)
    assert _codes(doc, "MLV205") == []


# ---------------------------------------------------------------- PUB-09
def test_pub09_a_torch_rule_does_not_judge_a_keras_model():
    doc = analyze_paths(os.path.join(RULES, "MLV301_keras_good"))
    assert _codes(doc, "MLV301", "MLV302") == []


# ---------------------------------------------------------------- PUB-10
@pytest.mark.parametrize("fqn,role", [
    ("transformers.AutoModelForImageClassification.from_pretrained", "HF_MODEL"),
    ("transformers.AutoModelForSeq2SeqLM.from_pretrained", "HF_MODEL"),
    ("transformers.AutoModelForCTC.from_pretrained", "HF_MODEL"),
    ("transformers.AutoImageProcessor.from_pretrained", "HF_TOKENIZER"),
    ("transformers.PreTrainedModel.save_pretrained", "SAVE"),
])
def test_pub10_the_hf_table_covers_the_task_heads(fqn, role):
    assert K.role_of(fqn) == role


def test_pub10_a_hf_image_finetune_has_a_model_and_a_preprocess_stage(tmp_path):
    workspace = _ws(tmp_path, {"run.py": (
        "from transformers import (AutoConfig, AutoImageProcessor,\n"
        "                          AutoModelForImageClassification, Trainer,\n"
        "                          TrainingArguments)\n"
        "from datasets import load_dataset\n"
        "\n"
        "def main():\n"
        "    dataset = load_dataset('beans')\n"
        "    config = AutoConfig.from_pretrained('google/vit-base')\n"
        "    model = AutoModelForImageClassification.from_pretrained('google/vit-base',\n"
        "                                                            config=config)\n"
        "    processor = AutoImageProcessor.from_pretrained('google/vit-base')\n"
        "    trainer = Trainer(model=model,\n"
        "                      args=TrainingArguments(output_dir='out'),\n"
        "                      train_dataset=dataset['train'],\n"
        "                      eval_dataset=dataset['validation'],\n"
        "                      processing_class=processor)\n"
        "    trainer.train()\n"
        "    trainer.evaluate()\n"
    )})
    doc = analyze_paths(workspace)
    assert _stage(doc, "model")["present"], "the model stage was declared absent"
    assert _stage(doc, "preprocess")["present"], "the preprocess stage was declared absent"


# ---------------------------------------------------------------- PUB-11
def test_pub11_the_evaluation_answer_cites_each_node_once():
    doc = analyze_fixture("MLV301_bad").doc
    answer = (doc.get("answers") or {}).get("evaluation") or {}
    ids = answer.get("nodeIds") or []
    assert len(ids) == len(set(ids)), ids


# ---------------------------------------------------------------- NLP-01
def test_nlp01_an_eval_loop_over_a_parameter_is_not_a_training_loop(tmp_path):
    """The loop runs the model, measures, and never back-propagates."""
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "def train(model, train_loader):\n"
        "    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)\n"
        "    for batch in train_loader:\n"
        "        opt.zero_grad()\n"
        "        loss = model(batch['x'], labels=batch['y']).loss\n"
        "        loss.backward()\n"
        "        opt.step()\n"
        "\n"
        "def token_accuracy(model, eval_loader):\n"
        "    hits = 0\n"
        "    for batch in eval_loader:\n"
        "        logits = model(batch['x']).logits\n"
        "        hits += (logits.argmax(dim=-1) == batch['y']).sum().item()\n"
        "    return hits\n"
    )})
    doc = analyze_paths(workspace)
    assert _stage(doc, "eval")["present"], "the eval stage was declared absent"
    loops = [n for n in doc["nodes"] if n["kind"] == "eval_loop"]
    assert loops, "the scoring loop was drawn as a training loop"


# ---------------------------------------------------------------- NLP-02
def test_nlp02_a_captured_subscript_keeps_the_dataset_chain(tmp_path):
    """`raw = load_dataset(...)["train"]` must not delete everything downstream."""
    workspace = _ws(tmp_path, {"m.py": (
        "from datasets import load_dataset\n"
        "\n"
        "raw = load_dataset('imdb')['train']\n"
        "encoded = raw.map(lambda b: b, batched=True)\n"
        "split = encoded.train_test_split(test_size=0.1)\n"
    )})
    doc = analyze_paths(workspace)
    kinds = {n["kind"] for n in doc["nodes"]}
    assert "transform" in kinds and "split" in kinds, sorted(kinds)
    assert "MLV602" in _codes(doc), "the unseeded split went unreported"


# ---------------------------------------------------------- NLP-09 / ROB-03
@pytest.mark.parametrize("program", ["vision_unet_seg_bad", "vision_video3d_bad",
                                     "vision_detector_bad"])
@pytest.mark.parametrize("dataflow", ["local", "ip"])
def test_rob03_issue_ids_stay_unique_on_the_shipped_corpus(program, dataflow):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                        "accuracy", "corpus", program))
    if not os.path.isdir(root):
        pytest.skip("%s is not in this corpus" % program)
    doc = analyze_paths(root, dataflow=dataflow)
    counts = collections.Counter(i["id"] for i in doc["issues"])
    assert [k for k, v in counts.items() if v > 1] == []


def test_nlp09_two_call_sites_of_one_criterion_are_two_findings(tmp_path):
    """Ids must separate a train-path finding from an eval-path one."""
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "criterion = nn.CrossEntropyLoss()\n"
        "net = nn.Sequential(nn.Linear(4, 3), nn.Softmax(dim=1))\n"
        "\n"
        "def train_step(x, y):\n"
        "    return criterion(net(x), y)\n"
        "\n"
        "def eval_step(x, y):\n"
        "    return criterion(net(x), y)\n"
    )})
    doc = analyze_paths(workspace)
    found = _issues(doc, "MLV401")
    assert len({i["id"] for i in found}) == len(found)


# ---------------------------------------------------------------- NLP-14
def test_nlp14_a_literal_split_key_reinforces_the_eval_loader(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "from torch.utils.data import DataLoader\n"
        "\n"
        "def score(split):\n"
        "    loader = DataLoader(split['test'], batch_size=32, shuffle=True)\n"
        "    return loader\n"
    )})
    doc = analyze_paths(workspace)
    assert "MLV111" in _codes(doc)


# --------------------------------------------------------- TAB-01 / TAB-12
@pytest.mark.parametrize("fqn", [
    "prophet.Prophet", "statsmodels.tsa.statespace.sarimax.SARIMAX",
    "scipy.stats.boxcox", "sklearn.manifold.TSNE",
    "sklearn.calibration.CalibratedClassifierCV", "sklearn.mixture.GaussianMixture",
    "sklearn.compose.TransformedTargetRegressor",
    "mlflow.log_metrics", "mlflow.start_run", "mlflow.sklearn.log_model",
])
def test_tab01_the_classical_surface_has_a_knowledge_row(fqn):
    assert K.role_of(fqn) is not None, "%s still resolves to role=None" % fqn


def test_tab01_a_statsmodels_forecaster_is_not_reported_as_modelless(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import pandas as pd\n"
        "import statsmodels.api as sm\n"
        "\n"
        "def forecast(path):\n"
        "    frame = pd.read_csv(path, parse_dates=['ds'])\n"
        "    model = sm.tsa.statespace.SARIMAX(frame['y'], order=(1, 1, 1))\n"
        "    fitted = model.fit(disp=False)\n"
        "    return fitted.forecast(steps=12)\n"
    )})
    doc = analyze_paths(workspace)
    assert _stage(doc, "model")["present"], "the model stage was declared absent"


# ---------------------------------------------------------------- DGRG-01
def test_dgrg01_an_unrecognised_framework_is_declared(tmp_path):
    """A clean bill of health on a file MLView understood nothing of."""
    workspace = _ws(tmp_path, {"t.py": (
        "from stable_baselines3 import PPO\n"
        "\n"
        "model = PPO('MlpPolicy', 'CartPole-v1')\n"
        "model.learn(total_timesteps=10000)\n"
        "model.save('out')\n"
    )})
    doc = analyze_paths(workspace)
    notes = [d for d in doc["diagnostics"]
             if d["kind"] == "unresolved_callee" and "stable_baselines3" in d["message"]]
    assert notes, "no diagnostic named the unrecognised framework"


def test_dgrg01_a_modelled_framework_raises_no_such_note():
    """`torch.flatten` has no exact row; that is not a reason to say anything."""
    doc = analyze_fixture("MLV201_good").doc
    assert not [d for d in doc["diagnostics"]
                if d["kind"] == "unresolved_callee"
                and "no knowledge table" in d["message"]]


# ---------------------------------------------------------------- DGRG-02
def test_dgrg02_a_composed_loss_still_reaches_the_mlv2xx_family(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "\n"
        "def distill(soft, hard):\n"
        "    return 0.7 * soft + 0.3 * hard\n"
        "\n"
        "def main():\n"
        "    torch.manual_seed(0)\n"
        "    ds = TensorDataset(torch.randn(8, 4), torch.randint(0, 2, (8,)))\n"
        "    loader = DataLoader(ds, batch_size=2, shuffle=True)\n"
        "    model = nn.Linear(4, 2)\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = torch.optim.SGD(model.parameters(), lr=0.1)\n"
        "    for x, y in loader:\n"
        "        loss = distill(crit(model(x), y), crit(model(x), y))\n"
        "        loss.backward()\n"
        "        opt.step()\n"
    )})
    doc = analyze_paths(workspace)
    assert "MLV201" in _codes(doc), "the missing zero_grad went unreported"


def test_dgrg02_an_untyped_backward_is_declared(tmp_path):
    """A rule may stay silent; the silence may not be silent."""
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "def bpr_loss(pos, neg):\n"
        "    return -torch.log(torch.sigmoid(pos - neg)).mean()\n"
        "\n"
        "def train(model, loader, opt):\n"
        "    for users, pos, neg in loader:\n"
        "        loss = bpr_loss(model(users, pos), model(users, neg))\n"
        "        loss.backward()\n"
        "        opt.step()\n"
    )})
    doc = analyze_paths(workspace)
    assert "untagged_dataflow" in _kinds(doc)


# ---------------------------------------------------------------- DGRG-11
def test_dgrg11_a_second_offending_loop_is_named(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "def run(model, train_loader, val_loader, device):\n"
        "    torch.manual_seed(0)\n"
        "    model = model.to(device)\n"
        "    for x, y in val_loader:\n"
        "        model(x)\n"
        "    for x, y in train_loader:\n"
        "        model(x)\n"
    )})
    doc = analyze_paths(workspace)
    found = _issues(doc, "MLV501")
    if not found:
        pytest.skip("MLV501 did not resolve a model here")
    roles = {r["line"] for i in found for r in i["relatedLocs"]}
    assert len(roles) >= 3, roles


# ---------------------------------------------------------------- INFRA-02
def test_infra02_a_model_moved_in_another_module_is_not_missing(tmp_path):
    workspace = _ws(tmp_path, {
        "trainer.py": (
            "import torch\n"
            "import torch.nn as nn\n"
            "\n"
            "from evaluator import evaluate\n"
            "\n"
            "def train(model: nn.Module, loader, device):\n"
            "    torch.manual_seed(0)\n"
            "    model = model.to(device)\n"
            "    return evaluate(model, loader, device)\n"
        ),
        "evaluator.py": (
            "import torch\n"
            "import torch.nn as nn\n"
            "\n"
            "def evaluate(model: nn.Module, loader, device):\n"
            "    model.eval()\n"
            "    with torch.no_grad():\n"
            "        for features, labels in loader:\n"
            "            features = features.to(device)\n"
            "            model(features)\n"
        ),
    })
    doc = analyze_paths(workspace)
    assert _codes(doc, "MLV501") == []


# ------------------------------------------------------- INFRA-03 / INFRA-04
@pytest.mark.parametrize("fqn,role", [
    ("pytorch_lightning.callbacks.ModelCheckpoint", "SAVE"),
    ("ignite.handlers.Checkpoint", "SAVE"),
    ("ignite.engine.create_supervised_evaluator", "IGNITE_EVAL"),
    ("deepspeed.DeepSpeedEngine.save_checkpoint", "SAVE"),
    ("fastai.learner.Learner.export", "SAVE"),
    ("fastai.learner.Learner.fine_tune", "FASTAI_FIT"),
    ("accelerate.utils.set_seed", "SEED"),
])
def test_infra04_the_framework_native_apis_have_rows(fqn, role):
    assert K.role_of(fqn) == role


# ---------------------------------------------------------------- INFRA-13
def test_infra13_an_absence_rule_does_not_pay_for_an_unrelated_config_read(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import argparse\n"
        "import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "\n"
        "def parse():\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--lr', type=float, default=0.0003)\n"
        "    return p.parse_args()\n"
        "\n"
        "def main():\n"
        "    torch.manual_seed(0)\n"
        "    args = parse()\n"
        "    ds = TensorDataset(torch.randn(8, 4), torch.randint(0, 2, (8,)))\n"
        "    loader = DataLoader(ds, batch_size=2, shuffle=True)\n"
        "    model = nn.Linear(4, 2)\n"
        "    crit = nn.CrossEntropyLoss()\n"
        "    opt = torch.optim.SGD(model.parameters(), lr=args.lr)\n"
        "    for x, y in loader:\n"
        "        loss = crit(model(x), y)\n"
        "        loss.backward()\n"
        "        opt.step()\n"
    )})
    doc = analyze_paths(workspace)
    for issue in _issues(doc, "MLV201"):
        reads = [e for e in issue["evidence"]
                 if e["kind"] == "context_confirmed" and "argparse defaults" in e["detail"]]
        assert reads == [], "an absence finding was charged for a config read"


# ------------------------------------------------------- vision-01 / -13
def test_vision01_an_unresolved_compile_receiver_is_not_an_absence():
    doc = analyze_paths(os.path.join(RULES, "MLV705_helper_good.py"))
    assert _codes(doc, "MLV705") == []


def test_vision01_a_workspace_with_no_compile_at_all_still_fires():
    doc = analyze_fixture("MLV705_bad").doc
    assert _issues(doc, "MLV705")


def test_vision13_a_datamodule_missing_super_init_is_reported():
    doc = analyze_paths(os.path.join(RULES, "MLV701_datamodule_bad.py"))
    assert "MLV701" in _codes(doc)


# ---------------------------------------------------------------- vision-03
def test_vision03_a_reduction_keeps_the_tensor_identity(tmp_path):
    """`critic(x).mean()` is a loss; `.backward()` on it is a backward."""
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "\n"
        "def main():\n"
        "    torch.manual_seed(0)\n"
        "    ds = TensorDataset(torch.randn(8, 4), torch.randn(8, 1))\n"
        "    loader = DataLoader(ds, batch_size=2, shuffle=True)\n"
        "    critic = nn.Linear(4, 1)\n"
        "    opt = torch.optim.SGD(critic.parameters(), lr=0.1)\n"
        "    for x, y in loader:\n"
        "        loss = critic(x).mean()\n"
        "        loss.backward()\n"
        "        opt.step()\n"
    )})
    doc = analyze_paths(workspace)
    assert "MLV201" in _codes(doc), "the missing zero_grad went unreported"
    assert any(n["kind"] == "loss" for n in doc["nodes"]), "no loss node was drawn"


# ---------------------------------------------------------------- vision-06
def test_vision06_the_epoch_reset_accumulator_is_found():
    doc = analyze_paths(os.path.join(RULES, "MLV205_nested_bad.py"))
    assert "MLV205" in _codes(doc)


# ---------------------------------------------------------------- vision-05
def test_vision05_a_returned_accumulator_is_the_callers_problem():
    doc = analyze_paths(os.path.join(RULES, "MLV205_returned_good.py"))
    assert _codes(doc, "MLV205") == []


# ---------------------------------------------------------------- vision-11
def test_vision11_a_function_with_no_loop_is_not_drawn_as_one(tmp_path):
    workspace = _ws(tmp_path, {"m.py": (
        "import torch\n"
        "import torch.nn as nn\n"
        "\n"
        "def train_transform():\n"
        "    return nn.Identity()\n"
        "\n"
        "def evaluate_nothing(model, x):\n"
        "    return model(x)\n"
    )})
    doc = analyze_paths(workspace)
    loopish = [n for n in doc["nodes"]
               if n["kind"] in ("train_loop", "eval_loop") and n["level"] == "unit"]
    assert loopish == [], [n["label"] for n in loopish]


# ---------------------------------------------------------------- vision-16
def test_vision16_the_message_names_the_call_not_the_criterion_module():
    doc = analyze_paths(os.path.join(RULES, "MLV205_nested_bad.py"))
    for issue in _issues(doc, "MLV205"):
        assert "the tensor loss" in issue["message"] or "the result of" in issue["message"], \
            issue["message"]


# ---------------------------------------------------------------- PUB-14
@pytest.mark.parametrize("dataflow", ["local", "ip"])
def test_pub14_hand_rolled_two_fold_cv_is_not_a_leak(dataflow):
    """`model.fit(X2, y2).predict(X1)` is cross-validation, not MLV102.

    `MLV101_sections_good.py`'s sibling for the *other* leakage rule: an
    estimator refitted on the held-out half, then scored on the half it never
    saw. `sklearn.base.BaseEstimator.fit` carries the role FIT, so MLV102 had
    every estimator fit as a candidate; the guard MLV101 has used since ROB-10
    now answers for both.
    """
    doc = analyze_paths(os.path.join(RULES, "MLV102_two_fold_good.py"),
                        dataflow=dataflow)
    assert _codes(doc, "MLV101", "MLV102") == []


def test_pub14_a_transformer_fitted_on_the_held_out_half_still_fires():
    """The guard narrows MLV102 to transformers; it must not disarm it."""
    doc = analyze_fixture("MLV102_bad").doc
    assert _issues(doc, "MLV102"), "MLV102 must still fire on its own bad fixture"


# ---------------------------------------------------------------- PUB-15
@pytest.mark.parametrize("dataflow", ["local", "ip"])
def test_pub15_a_tuple_rebinding_breaks_the_chain_like_a_plain_one(dataflow):
    """`X, y = load_iris(...)` is a rebinding; `_rebound_between` must see it.

    `MLV101_sections_good.py` cannot catch this: its fit is an estimator fit, so
    PUB-02's guard silences it before the rebinding guard runs. Here the fit is a
    real transformer, so this fixture is the only thing that holds the tuple
    half of PUB-03.
    """
    doc = analyze_paths(os.path.join(RULES, "MLV101_sections_tuple_good.py"),
                        dataflow=dataflow)
    assert _codes(doc, "MLV101", "MLV102") == []


def test_pub15_the_silence_is_declared_rather_than_quiet(tmp_path):
    """A guard that removes a finding says why, in the coverage diagnostics."""
    workspace = _ws(tmp_path, {"m.py": (
        "from sklearn.datasets import fetch_covtype, load_iris\n"
        "from sklearn.feature_selection import SequentialFeatureSelector\n"
        "from sklearn.model_selection import train_test_split\n"
        "from sklearn.neighbors import KNeighborsClassifier\n"
        "\n"
        "X, y = load_iris(return_X_y=True)\n"
        "sfs = SequentialFeatureSelector(KNeighborsClassifier(3), n_features_to_select=2)\n"
        "sfs.fit(X, y)\n"
        "\n"
        "X, y = fetch_covtype(return_X_y=True)\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=0)\n"
    )})
    doc = analyze_paths(workspace)
    assert _codes(doc, "MLV101") == []
    said = [d["message"] for d in doc["diagnostics"]
            if d["kind"] == "untagged_dataflow" and "re-assigned" in d["message"]]
    assert said, [d["message"] for d in doc["diagnostics"]]
