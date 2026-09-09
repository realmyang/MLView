"""FW-RECOG (CONTRACTS 11.23): tf.data, HuggingFace `datasets`, Keras, GBM
and the Lightning hook table.

R1.9 promises Keras / HuggingFace / Lightning are *"recognised at node level"*.
The Sprint-3 audit measured what that was worth: a five-call tf.data chain was
**1 node and 0 edges**, `datasets` was a single row so `train_test_split` on the
HuggingFace path produced **no SPLIT at all**, `xgboost` was a detected
framework with **no entries**, and the project's own clean `lightning_module.py`
reported *"not detected: preprocess, objective, eval, deliver"* on correct code.

One positive fixture per family, each asserting the two things a knowledge row
exists to decide - `kind` and `stage` - plus the connectivity and the hook
wiring that make the recognition worth having.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict

FIXTURE_DIR = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "frameworks")
CLEAN_DIR = os.path.join(REPO_ROOT, "analyzer", "tests", "clean")


def _doc(name: str):
    return analyze_to_dict(AnalyzeOptions(paths=(os.path.join(FIXTURE_DIR, name),)))


def _ops(doc, **match):
    out = []
    for node in doc["nodes"]:
        if node["level"] != "op":
            continue
        if all(node.get(key) == value for key, value in match.items()):
            out.append(node)
    return out


def _by_label(doc):
    index = {}
    for node in doc["nodes"]:
        index.setdefault(node["label"], []).append(node)
    return index


def _connected(doc, nodes):
    """The subgraph over `nodes` reachable from any one of them, ignoring direction."""
    ids = {n["id"] for n in nodes}
    adjacency = {i: set() for i in ids}
    for edge in doc["edges"]:
        source, target = edge["source"], edge["target"]
        if source in ids and target in ids:
            adjacency[source].add(target)
            adjacency[target].add(source)
    seen, stack = set(), [next(iter(ids))]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency[current] - seen)
    return seen


# --------------------------------------------------------------------- tf.data
@pytest.fixture(scope="module")
def tfdata():
    return _doc("tfdata_pipeline.py")


def test_the_tfdata_chain_is_seven_connected_nodes(tfdata):
    """The audit's probe: 1 node / 0 edges before, a connected chain now."""
    chain = [n for n in _ops(tfdata)
             if n["loc"]["line"] in range(25, 32) and n["fqn"]]
    assert len(chain) >= 7, [(n["label"], n["loc"]["line"]) for n in chain]
    assert len(_connected(tfdata, chain)) == len(chain), (
        "the chain must be connected, not seven islands: %s"
        % [(n["label"], n["loc"]["line"]) for n in chain])
    assert {n["stage"] for n in chain} <= {"data", "preprocess"}


def test_every_tfdata_link_has_the_kind_its_family_implies(tfdata):
    by_label = _by_label(tfdata)
    expected = {"from_tensor_slices()": ("dataset", "data"),
                "map()": ("transform", "preprocess"),
                "shuffle()": ("augment", "preprocess"),
                "cache()": ("transform", "data"),
                "repeat()": ("transform", "data"),
                "batch()": ("dataloader", "data"),
                "prefetch()": ("dataloader", "data")}
    for label, (kind, stage) in expected.items():
        found = by_label.get(label)
        assert found, "no node for %s: %s" % (label, sorted(by_label))
        assert (found[0]["kind"], found[0]["stage"]) == (kind, stage), label
        assert found[0]["framework"] == "tf"


def test_take_and_skip_are_not_split_nodes(tfdata):
    """ROADMAP FW-RECOG hard sequencing: MLV121 (ANA-9) owns that judgement."""
    for label in ("take()", "skip()"):
        node = _by_label(tfdata)[label][0]
        assert node["kind"] != "split", label
        assert node["fqn"].endswith(label[:-2])
    assert [i for i in tfdata.get("issues", []) if i["code"] == "MLV602"] == []


def test_image_dataset_from_directory_is_a_tf_data_source(tfdata):
    node = _by_label(tfdata)["image_dataset_from_directory()"][0]
    assert (node["kind"], node["stage"]) == ("dataset", "data")


def test_the_tfdata_fixture_is_contract_valid(tfdata):
    assert validate(tfdata) == []


# ------------------------------------------------------ HuggingFace `datasets`
@pytest.fixture(scope="module")
def hf():
    return _doc("hf_datasets.py")


def test_the_hf_path_produces_a_split_node(hf):
    splits = _ops(hf, kind="split")
    assert len(splits) == 1, [n["label"] for n in _ops(hf)]
    assert splits[0]["fqn"] == "datasets.Dataset.train_test_split"
    assert splits[0]["stage"] == "data"


def test_mlv602_fires_on_the_unseeded_hf_split(hf):
    """MLV101 / MLV106 / MLV602 were structurally impossible on this path."""
    codes = [i["code"] for i in hf["issues"]]
    assert "MLV602" in codes, codes
    issue = [i for i in hf["issues"] if i["code"] == "MLV602"][0]
    assert issue["loc"]["file"] == "hf_datasets.py"
    assert "seed" in issue["message"]


def test_dataset_map_and_the_collator_are_preprocess(hf):
    labels = _by_label(hf)
    assert labels["encoded"][0]["fqn"] == "datasets.Dataset.map"
    assert labels["encoded"][0]["stage"] == "preprocess"
    assert labels["collator"][0]["kind"] == "transform"
    assert labels["collator"][0]["framework"] == "hf"


def test_load_from_disk_is_a_dataset_source(hf):
    node = _by_label(hf)["load_from_disk()"][0]
    assert (node["kind"], node["stage"]) == ("dataset", "data")


# ----------------------------------------------------------------------- Keras
@pytest.fixture(scope="module")
def keras():
    return _doc("keras_transfer.py")


def test_the_missing_keras_families_are_recognised(keras):
    labels = _by_label(keras)
    expected = {"base": ("model", "model"),
                "inputs": ("layer", "model"),
                "Rescaling()": ("transform", "preprocess"),
                "RandomFlip()": ("augment", "preprocess"),
                "GlobalAveragePooling2D()": ("layer", "model"),
                "EarlyStopping()": ("config", "train"),
                "ReduceLROnPlateau()": ("scheduler", "train"),
                "ModelCheckpoint()": ("checkpoint", "deliver"),
                "CSVLogger()": ("tracker", "deliver"),
                "SparseCategoricalAccuracy()": ("metric", "eval")}
    for label, (kind, stage) in expected.items():
        found = labels.get(label)
        assert found, "no node for %s: %s" % (label, sorted(labels))
        assert (found[0]["kind"], found[0]["stage"]) == (kind, stage), label


def test_the_functional_api_does_not_mint_unknown_nodes(keras):
    """`layers.Dense(64)(x)` is a call of a call - resolved, not guessed at."""
    assert _ops(keras, kind="unknown") == []
    assert [d for d in keras.get("diagnostics", [])
            if d["kind"] == "unresolved_callee"] == []


def test_a_pure_keras_file_names_no_torch_framework(keras):
    detected = keras["workspace"]["frameworks"]
    assert "torch" not in detected, detected
    frameworks = {n.get("framework") for n in keras["nodes"] if n.get("framework")}
    assert "torch" not in frameworks, sorted(frameworks)


def test_model_fit_through_an_annotated_parameter_is_a_train_loop(keras):
    fits = [n for n in _ops(keras) if n.get("fqn") == "keras.Model.fit"]
    assert len(fits) == 1, [n.get("fqn") for n in _ops(keras)]
    assert (fits[0]["kind"], fits[0]["stage"]) == ("train_loop", "train")


# ------------------------------------------------------------------------- GBM
@pytest.fixture(scope="module")
def gbm():
    return _doc("gbm_boosting.py")


def test_the_boosting_estimators_are_model_nodes(gbm):
    labels = _by_label(gbm)
    assert labels["classifier"][0]["fqn"] == "xgboost.XGBClassifier"
    assert (labels["classifier"][0]["kind"], labels["classifier"][0]["stage"]) == (
        "model", "model")
    assert labels["classifier"][0]["framework"] == "xgboost"
    assert labels["regressor"][0]["framework"] == "lightgbm"


def test_fit_predict_and_predict_proba_are_attributed_to_the_library(gbm):
    by_fqn = {n.get("fqn"): n for n in _ops(gbm)}
    assert by_fqn["xgboost.XGBClassifier.fit"]["stage"] == "train"
    assert by_fqn["xgboost.XGBClassifier.predict_proba"]["kind"] == "predict"
    assert by_fqn["lightgbm.LGBMRegressor.predict"]["framework"] == "lightgbm"
    assert by_fqn["xgboost.DMatrix"]["kind"] == "dataset"


def test_the_boosting_fixture_reports_nothing(gbm):
    assert [i for i in gbm.get("issues", []) if not i.get("suppressed")] == []


# ------------------------------------------------------------------- Lightning
@pytest.fixture(scope="module")
def lightning():
    return _doc("lightning_hooks.py")


def _unit(doc, label):
    found = [n for n in doc["nodes"] if n["label"] == label and n["level"] != "op"]
    assert found, "no unit %s: %s" % (label, sorted(n["label"] for n in doc["nodes"]))
    return found[0]


def test_a_lightning_module_is_a_model_class(lightning):
    node = _unit(lightning, "TabularClassifier")
    assert node["kind"] == "model"
    assert node["stage"] == "model"


def test_every_hook_is_a_unit_in_the_lane_the_framework_runs_it_in(lightning):
    expected = {"training_step()": "train", "validation_step()": "eval",
                "test_step()": "eval", "configure_optimizers()": "objective",
                "train_dataloader()": "data", "val_dataloader()": "data",
                "setup()": "data", "forward()": "model",
                "on_validation_epoch_end()": "eval"}
    for label, stage in expected.items():
        node = _unit(lightning, label)
        assert node["stage"] == stage, (label, node["stage"])
        assert node["sublabel"].startswith("framework hook"), label


def test_trainer_fit_enters_the_hooks_it_actually_runs(lightning):
    by_id = {n["id"]: n for n in lightning["nodes"]}
    entered = {}
    for edge in lightning["edges"]:
        if edge["kind"] != "control" or edge.get("subkind") != "enter":
            continue
        source = by_id[edge["source"]]
        if source["level"] != "op":
            continue
        entered.setdefault(source["label"], set()).add(by_id[edge["target"]]["label"])
    assert "training_step()" in entered["fit()"]
    assert "configure_optimizers()" in entered["fit()"]
    assert "validation_step()" in entered["fit()"]
    # `trainer.fit` does not run `test_step`, and drawing that arrow would be a
    # false statement about control flow.
    assert "test_step()" not in entered["fit()"]
    assert entered["test()"] == {"setup()", "test_step()", "forward()"}


def test_configure_optimizers_returns_an_optimizer(lightning):
    result = analyze_full(AnalyzeOptions(
        paths=(os.path.join(FIXTURE_DIR, "lightning_hooks.py"),)))
    module = result.workspace.modules["lightning_hooks.py"]
    cls = module.classes["lightning_hooks.TabularClassifier"]
    summary = cls.methods["configure_optimizers"].return_summary
    assert summary is not None and summary.scalar is not None
    assert "OPTIMIZER" in summary.scalar.tags


def test_the_lightning_fixture_reports_nothing(lightning):
    assert [i for i in lightning.get("issues", []) if not i.get("suppressed")] == []
    assert validate(lightning) == []


# ----------------------------------------------------- the acceptance corpora
def test_the_clean_lightning_program_is_twenty_nodes_with_an_objective():
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(os.path.join(CLEAN_DIR, "lightning_module.py"),)))
    assert doc["stats"]["nodes"] >= 20, doc["stats"]
    classes = [n for n in doc["nodes"] if n["label"] == "LitClassifier"]
    assert classes and classes[0]["kind"] == "model"
    objective = [n for n in doc["nodes"]
                 if n["stage"] == "objective" and n["level"] == "op"]
    assert any((n.get("fqn") or "").endswith("cross_entropy") for n in objective), (
        [(n["label"], n.get("fqn")) for n in objective])
    stages = {s["id"]: s for s in doc["stages"]}
    assert stages["eval"]["present"] and stages["eval"]["nodeCount"] > 0
    assert doc["issues"] == []


def test_the_clean_hf_program_still_reports_nothing():
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(os.path.join(CLEAN_DIR, "hf_trainer.py"),)))
    assert doc["issues"] == []


def test_the_whole_clean_corpus_still_reports_nothing():
    doc = analyze_to_dict(AnalyzeOptions(paths=(CLEAN_DIR,)))
    assert doc["issues"] == [], [(i["code"], i["loc"]["file"]) for i in doc["issues"]]
