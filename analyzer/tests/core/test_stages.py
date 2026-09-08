"""The eight-stage classifier: knowledge rows, unit voting, evidence."""

from __future__ import annotations

import pytest

from mlview.core.stages import name_stage, unit_stage, vote_stage
from mlview.knowledge import lookup, stage_of

FQN_STAGE = [
    ("torch.utils.data.DataLoader", "data"),
    ("torch.utils.data.random_split", "data"),
    ("torchvision.datasets.CIFAR10", "data"),
    ("torchvision.transforms.Normalize", "preprocess"),
    ("torchvision.transforms.RandomCrop", "preprocess"),
    ("sklearn.preprocessing.StandardScaler", "preprocess"),
    ("sklearn.decomposition.PCA", "preprocess"),
    ("sklearn.model_selection.train_test_split", "data"),
    ("torch.nn.Linear", "model"),
    ("torch.nn.Module", "model"),
    ("torch.nn.CrossEntropyLoss", "objective"),
    ("torch.nn.functional.cross_entropy", "objective"),
    ("torch.optim.Adam", "train"),
    ("torch.optim.lr_scheduler.StepLR", "train"),
    ("torch.optim.Optimizer.step", "train"),
    ("torch.optim.Optimizer.zero_grad", "train"),
    ("torch.Tensor.backward", "train"),
    ("torch.nn.Module.eval", "eval"),
    ("torch.no_grad", "eval"),
    ("sklearn.metrics.accuracy_score", "eval"),
    ("sklearn.metrics.roc_auc_score", "eval"),
    ("sklearn.base.BaseEstimator.predict", "eval"),
    ("sklearn.base.BaseEstimator.fit", "train"),
    ("sklearn.base.BaseEstimator.fit_transform", "preprocess"),
    ("torch.save", "deliver"),
    ("torch.load", "deliver"),
    ("joblib.dump", "deliver"),
    ("torch.device", "config"),
    ("torch.manual_seed", "config"),
    ("argparse.ArgumentParser", "config"),
    ("yaml.safe_load", "config"),
    ("pandas.read_csv", "data"),
    ("transformers.Trainer", "train"),
    ("pytorch_lightning.Trainer", "train"),
    ("keras.Model.fit", "train"),
    ("sklearn.linear_model.LogisticRegression", "model"),
]


@pytest.mark.parametrize("fqn,stage", FQN_STAGE)
def test_knowledge_stage_table(fqn, stage):
    assert lookup(fqn) is not None, "%s is not in the knowledge tables" % fqn
    assert stage_of(fqn) == stage


def test_vote_ties_break_towards_the_earlier_stage():
    assert vote_stage({"train": 2.0, "data": 2.0}) == "data"
    assert vote_stage({"eval": 3.0, "model": 1.0}) == "eval"
    assert vote_stage({}) is None


def test_name_stage_is_a_tiebreak_only():
    assert name_stage("validate") == "eval"
    assert name_stage("train_one_epoch") == "train"
    assert name_stage("build_loaders") == "data"
    assert name_stage("zzz") is None


def test_class_base_beats_votes():
    stage, evidence = unit_stage("class", {"data": 5.0}, {"is_nn_module": True}, "Net")
    assert stage == "model"
    assert evidence[0].kind == "class_base"


def test_backward_and_step_make_a_train_unit():
    stage, evidence = unit_stage("function", {"data": 3.0},
                                 {"has_backward": True, "has_step": True}, "run")
    assert stage == "train"
    assert any(e.kind == "context_confirmed" for e in evidence)


def test_eval_region_votes_eval():
    stage, _ = unit_stage("function", {}, {"is_eval_region": True}, "validate")
    assert stage == "eval"


def test_entrypoint_defaults_to_config_unless_dominated():
    stage, _ = unit_stage("entrypoint", {}, {}, "__main__")
    assert stage == "config"
    stage, _ = unit_stage("entrypoint", {"train": 4.0}, {}, "__main__")
    assert stage == "train"


PIPELINE = """
import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import accuracy_score


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(4, 2)

    def forward(self, x):
        return self.fc(x)


def build_loader(ds):
    return DataLoader(ds, batch_size=8, shuffle=True)


def train(model, loader):
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters())
    for images, labels in loader:
        optimizer.zero_grad()
        loss = criterion(model(images), labels)
        loss.backward()
        optimizer.step()


def validate(model, loader):
    model.eval()
    with torch.no_grad():
        for images, labels in loader:
            preds = model(images).argmax(dim=1)
            accuracy_score(labels, preds)


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    ds = TensorDataset(torch.zeros(2, 4), torch.zeros(2, dtype=torch.long))
    loader = build_loader(ds)
    model = Net()
    train(model, loader)
    validate(model, loader)
    torch.save(model.state_dict(), "out.pt")


if __name__ == "__main__":
    main()
"""


@pytest.fixture
def pipeline(analyze_ws):
    return analyze_ws({"train.py": PIPELINE})


def node_by_label(doc, label):
    for node in doc["nodes"]:
        if node["label"] == label:
            return node
    raise AssertionError("no node labelled %r (have %s)"
                         % (label, [n["label"] for n in doc["nodes"]]))


def test_unit_stages_on_a_real_pipeline(pipeline):
    assert node_by_label(pipeline, "Net")["stage"] == "model"
    assert node_by_label(pipeline, "build_loader()")["stage"] == "data"
    assert node_by_label(pipeline, "train()")["stage"] == "train"
    assert node_by_label(pipeline, "validate()")["stage"] == "eval"


def test_every_node_carries_stage_evidence(pipeline):
    for node in pipeline["nodes"]:
        if node["level"] != "op" or node["kind"] != "unknown":
            assert node["stageEvidence"], node["label"]


def test_all_eight_stages_present_and_ordered(pipeline):
    ids = [s["id"] for s in pipeline["stages"]]
    assert ids == ["config", "data", "preprocess", "model", "objective", "train",
                   "eval", "deliver"]
    assert [s["order"] for s in pipeline["stages"]] == list(range(8))
    present = {s["id"] for s in pipeline["stages"] if s["present"]}
    assert {"data", "model", "train", "eval", "deliver"} <= present
