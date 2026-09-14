"""Round-2 hardening: one regression test per fixed finding.

Every test below names the finding it pins, states what was observed before the
fix in the terms the reporter measured it in, and asserts the property rather
than the implementation - so a future refactor that keeps the behaviour keeps
the test green, and one that loses it does not.

The fixtures are written inline into `tmp_path` wherever the defect is about a
*shape* rather than about a shipped program, because a shape is what a reader
has to be able to reproduce from the test alone.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_to_dict

CORPUS = os.path.join(REPO_ROOT, "analyzer", "tests", "accuracy", "corpus")
MODES = ["local", "ip"]


def write(tmp_path, name: str, files) -> str:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for filename, text in files.items():
        with open(str(root / filename), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return str(root)


def analyze(path: str, **kwargs):
    doc = analyze_to_dict(AnalyzeOptions(paths=(path,), cache=False, **kwargs))
    assert validate(doc) == [], doc.get("schemaVersion")
    return doc


def codes(doc):
    return {i["code"] for i in doc["issues"] if not i.get("suppressed")}


def loops(doc):
    return [(n["stage"], n["kind"], n["label"]) for n in doc["nodes"]
            if n["kind"].endswith("_loop")]


def sentence(doc, field: str) -> str:
    return doc["answers"][field]["sentence"]


# ---------------------------------------------------------------- PUB2-01
TF_SUBSAMPLE = '''import tensorflow as tf
from tensorflow.keras.datasets import mnist

BATCH, N_TRAIN, N_VALID = 128, 3000, 1000


def get_mnist():
    (x_train, y_train), (x_valid, y_valid) = mnist.load_data()
    train_ds = tf.data.Dataset.from_tensor_slices((x_train, y_train))
    train_ds = train_ds.shuffle(60000).batch(BATCH).take(N_TRAIN)
    valid_ds = tf.data.Dataset.from_tensor_slices((x_valid, y_valid))
    valid_ds = valid_ds.shuffle(10000).batch(BATCH).take(N_VALID)
    return train_ds, valid_ds
'''

TF_HOLDOUT = '''import tensorflow as tf


def build(paths, labels):
    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    shuffled = ds.shuffle(1024)
    val_ds = shuffled.take(200).batch(32)
    train_ds = shuffled.skip(200).batch(32)
    return train_ds, val_ds
'''


@pytest.mark.parametrize("mode", MODES)
def test_pub2_01_a_lone_take_is_a_subsample_not_a_holdout(tmp_path, mode):
    """A name may not assert a holdout into existence (iron law 2).

    Observed on `optuna-examples/tensorflow/tensorflow_eager_simple.py:112` -
    the ONLY high-severity false positive in 260 runs over 37 repositories.
    `mnist.load_data()` hands back two already-disjoint arrays, each becomes a
    Dataset, and each chain ends in `take()` to cap how many batches a trial
    consumes. There is no `skip()` anywhere in the file. MLV121 reported
    **high / 0.95 / certain** on the second chain only - because the variable
    is called `valid_ds` - and said the take "carves out the holdout" and that
    "every validation row has been trained on by epoch two". The identical
    chain one line above, with a different variable name, was silent.
    """
    root = write(tmp_path, "sub", {"sub.py": TF_SUBSAMPLE})
    assert "MLV121" not in codes(analyze(root, dataflow=mode))


@pytest.mark.parametrize("mode", MODES)
def test_pub2_01_the_real_take_skip_pair_still_fires(tmp_path, mode):
    """The control: an explicit `take` **and** `skip` off one shuffled receiver
    is a holdout, and all three round-1 true positives (keras-io pointnet,
    siamese_network, xray_classification_with_tpus) have exactly this shape."""
    root = write(tmp_path, "pair", {"pair.py": TF_HOLDOUT})
    assert "MLV121" in codes(analyze(root, dataflow=mode))


# ---------------------------------------------------------------- PUB2-02
XFILE_EVAL = '''import torch
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

test_dataset = datasets.CIFAR10("data", train=False, transform=transforms.ToTensor())
test_loader = DataLoader(test_dataset, batch_size=128, shuffle=False)


def accuracy(model):
    model.eval()
    correct = 0
    with torch.no_grad():
        for inputs, labels in test_loader:
            correct += int((model(inputs).argmax(-1) == labels).sum())
    return correct
'''

XFILE_ATTACK = '''# An adversarial-attack tutorial that binds the same bare name.
# The leading comment lines exist so the line numbers differ.
#
#
#
#
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

test_loader = DataLoader(
    datasets.MNIST("data", train=False, transform=transforms.ToTensor()),
    batch_size=1, shuffle=False)


def fgsm_attack(model, epsilon):
    for data, target in test_loader:
        data.requires_grad = True
        loss = F.nll_loss(model(data), target)
        model.zero_grad()
        loss.backward()
        yield data.grad.data
'''


def test_pub2_02_a_bare_name_does_not_match_a_loop_in_another_module(tmp_path):
    """MLV110 matched loops by bare name ACROSS MODULES.

    `iterating_loops` read `if tail in names and (loop.module is call.module or
    tail in names)` - and `A and (B or A)` is `A`, so the module check never
    applied. On pytorch/tutorials a correctly built evaluation loader in
    `knowledge_distillation_tutorial.py:93` was reported as "the **training**
    DataLoader ... consumed in dataset order every epoch" with the decisive
    evidence "the loop at line 272 over this loader calls backward()". Line 272
    of that file is prose inside a comment block; the loop is in
    `fgsm_tutorial.py`, a different module with a different `test_loader` over
    a different dataset.
    """
    root = write(tmp_path, "xfile",
                 {"a_eval.py": XFILE_EVAL, "b_attack.py": XFILE_ATTACK})
    doc = analyze(root)
    hits = [i for i in doc["issues"]
            if i["code"] == "MLV110" and i["loc"]["file"] == "a_eval.py"]
    assert not hits, [i["message"] for i in hits]


# ---------------------------------------------------------------- PUB2-03
PYTEST_MODEL = '''import torch.nn as nn


class Block(nn.Module):
    def __init__(self, dim, out):
        super().__init__()
        self.fc = nn.Linear(dim, out)
        self.drop = nn.Dropout(0.1)

    def forward(self, x, use_cache=False):
        return self.fc(self.drop(x))
'''

PYTEST_CASE = '''import copy

import pytest
import torch

from model import Block


def test_cached_prefill_matches_uncached():
    torch.manual_seed(123)
    att = Block(8, 8)
    att.eval()
    ref = copy.deepcopy(att)
    x = torch.randn(1, 6, 8)
    expected = ref(x, use_cache=False)
    actual = att(x, use_cache=True)
    assert torch.allclose(actual, expected, atol=1e-6)
'''


@pytest.mark.parametrize("filename", ["tests.py", "test_model.py", "model_tests.py",
                                      "conftest.py", "checks.py"])
def test_pub2_03_every_pytest_module_spelling_is_excluded(tmp_path, filename):
    """Round 1's pytest exclusion tested ONE filename pattern.

    `_TEST_FILE_RE` wanted `test_` as a prefix or `_test` as a suffix, and the
    directory arm dropped the filename before looking - so a module literally
    called `tests.py` matched neither. Measured on rasbt/LLMs-from-scratch:
    four MLV302 findings across two `ch*/.../tests.py` files, at 0.85 and 0.68,
    both above the Problems-panel floor, telling the reader to wrap a pytest
    case in `torch.no_grad()`. `checks.py` is the un-spoofable half: it is
    covered by the `import pytest` signal and by nothing else.
    """
    root = write(tmp_path, filename.replace(".", "_"),
                 {"model.py": PYTEST_MODEL, filename: PYTEST_CASE})
    found = {c for c in codes(analyze(root)) if c.startswith("MLV30")}
    assert not found, found


# ---------------------------------------------------------------- PUB2-04
EPOCH_FLOAT = '''import torch.nn as nn
from torch import optim


def train_epoch(dataloader, model, optimizer, criterion):
    total_loss = 0
    for x, y in dataloader:
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(dataloader)


def train(dataloader, model, n_epochs=10, lr=1e-3, print_every=100):
    optimizer = optim.Adam(model.parameters(), lr=lr)
    criterion = nn.NLLLoss()
    print_loss_total = 0
    for epoch in range(1, n_epochs + 1):
        loss = train_epoch(dataloader, model, optimizer, criterion)
        print_loss_total += loss
        if epoch % print_every == 0:
            print(print_loss_total / print_every)
            print_loss_total = 0
'''


@pytest.mark.parametrize("mode", MODES)
def test_pub2_04_a_float_returned_by_an_epoch_helper_is_not_a_tensor(tmp_path, mode):
    """MLV205 called a Python float "the tensor", three times, on the canonical
    PyTorch seq2seq tutorial (`intermediate_source/seq2seq_translation_tutorial.py`
    lines 685, 686 and 696).

    `train_epoch` accumulates `loss.item()` and returns `total_loss /
    len(dataloader)`, so the value the caller adds up is a number and there is
    no autograd graph to keep alive. Round 1 taught the return inference to
    carry the LOSS tag across an arithmetic return (so MLV201/202 stop going
    blind on `loss = bpr_loss(...)`); the same inference then handed MLV205 a
    float wearing a LOSS tag.
    """
    root = write(tmp_path, "epochfloat", {"train.py": EPOCH_FLOAT})
    assert "MLV205" not in codes(analyze(root, dataflow=mode))


# ---------------------------------------------------------------- PUB2-06
WHILE_TRAIN = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

model = nn.Linear(10, 2)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
loader = DataLoader(TensorDataset(torch.randn(64, 10), torch.zeros(64).long()),
                    batch_size=8, shuffle=True)
data_iter = iter(loader)
step = 0
while step < 100:
    x, y = next(data_iter)
    loss = criterion(model(x), y)
    loss.backward()
    optimizer.step()
    step += 1
'''


def test_pub2_06_a_while_training_loop_is_a_loop(tmp_path):
    """`core/build.py` created a loop node only for `epoch`/`batch`/`fold`, and
    `_loop_kind` assigned those only to `ast.For` - so a `while`-based trainer
    drew nothing and MLV201/202/203 could not fire inside one.

    Measured on the two most-read PyTorch repositories: minGPT's
    `Trainer.run` (`while True:` with `zero_grad` / `backward` / `step`) gave a
    98-node graph with **zero** train_loop nodes, and on nanoGPT every op of
    the real step was drawn at its true line with no loop containing them, so
    README requirement 1's "the training loop drawn **as a loop**" did not
    happen on the flagship repo.
    """
    root = write(tmp_path, "whilev", {"t.py": WHILE_TRAIN})
    doc = analyze(root)
    assert [k for _s, k, _l in loops(doc) if k == "train_loop"], loops(doc)
    assert "MLV201" in codes(doc), sorted(codes(doc))


# ---------------------------------------------------------------- PUB2-07
CONFIG_RANGE = '''import tensorflow as tf


def get_default_config():
    config = tf.compat.v1.ConfigProto()
    config.iou_thresholds.append(0.5)
    for i in range(100):
        config.score_cutoffs.append(i * 0.01)
    config.score_cutoffs.append(1.0)
    return config
'''


def test_pub2_07_a_literal_range_with_no_ml_content_is_not_a_training_loop(tmp_path):
    """`for i in range(<literal>)` was classified an epoch loop on that shape
    alone - no backward, no forward, no metric, no nested batch loop.

    Measured over the 252 graph documents of the 37-repo public corpus: 739 of
    4898 train/eval loop nodes (15.1%) were matplotlib subplot loops, `%timeit`
    benchmarks and autoaugment lookup tables, and on tensorflow/models
    `official/vision` the ONLY node in the whole train lane of a 398-node
    diagram was this exact shape - a loop appending 100 float thresholds to a
    protobuf config - with the `train` stage declared present on that evidence
    and MLV601 armed off it.
    """
    root = write(tmp_path, "cfgloop", {"cfg.py": CONFIG_RANGE})
    doc = analyze(root)
    assert not loops(doc), loops(doc)
    assert "train" not in {s["id"] for s in doc["stages"] if s["present"]}
    assert "MLV601" not in codes(doc), sorted(codes(doc))


# ---------------------------------------------------------------- PUB2-08
XGB_NATIVE = '''import numpy as np
import xgboost as xgb

data = np.loadtxt("./dermatology.data", delimiter=",")
sz = data.shape
train = data[: int(sz[0] * 0.7), :]
test = data[int(sz[0] * 0.7):, :]
train_X, train_Y = train[:, :33], train[:, 34]
test_X, test_Y = test[:, :33], test[:, 34]
xg_train = xgb.DMatrix(train_X, label=train_Y)
xg_test = xgb.DMatrix(test_X, label=test_Y)
param = {"objective": "multi:softmax", "eta": 0.1, "max_depth": 6, "num_class": 6}
bst = xgb.train(param, xg_train, 5)
pred = bst.predict(xg_test)
error_rate = np.sum(pred != test_Y) / test_Y.shape[0]
bst.save_model("model.json")
'''


def test_pub2_08_the_native_booster_protocol_is_reachable(tmp_path):
    """`GBM_METHODS["xgboost.Booster.predict"]` and `.save_model` were
    **unreachable code**: there was no `xgboost.Booster` constructor row and
    `xgboost.train` declared no return type, so `bst` never acquired the
    family and `_canonical_for_receiver` proposed `xgboost.train.predict`.

    Observed on the canonical `xgboost/demo/multiclass_classification/train.py`
    - 22 lines, `DMatrix` -> `train` -> `predict` -> an error rate ->
    `save_model`: 5 nodes, 2 edges, stages present `data, train`, `not
    detected: model, objective, eval, deliver`, `diagnostics: []`, and an
    answer card reading "No evaluation stage was detected" plus "No findings:
    no rule fired on this workspace". Three stages claimed absent, three calls
    dropped, and a clean bill of health.
    """
    root = write(tmp_path, "xgbnative", {"train.py": XGB_NATIVE})
    doc = analyze(root)
    present = {s["id"] for s in doc["stages"] if s["present"]}
    assert {"eval", "deliver"} <= present, sorted(present)
    drawn = {n["loc"]["line"] for n in doc["nodes"]}
    assert {14, 16} <= drawn, sorted(drawn)          # predict, save_model
    assert "No evaluation stage was detected" not in sentence(doc, "evaluation")


# ---------------------------------------------------------------- VIS2-12
ENABLE_GRAD = '''import torch
import torch.nn as nn
import torch.nn.functional as F


def step(model, optimizer, x, y):
    with torch.enable_grad():
        probe = F.cross_entropy(model(x), y)
    optimizer.zero_grad()
    loss = F.cross_entropy(model(x), y)
    loss.backward()
    optimizer.step()
'''

#: The inverse control: a `backward()` written INSIDE a real `no_grad` block
#: is the defect MLV204 exists for, and it must still fire.
NO_GRAD_CONTROL = '''import torch
import torch.nn as nn
import torch.nn.functional as F


def step(model, optimizer, x, y):
    optimizer.zero_grad()
    with torch.no_grad():
        loss = F.cross_entropy(model(x), y)
        loss.backward()
    optimizer.step()
'''


def test_vis2_12_enable_grad_does_not_leak_past_its_block(tmp_path):
    """`with torch.enable_grad():` marked LATER statements as inside no_grad.

    `ir/scopes.visit_with` subtracted `min(self.no_grad, enable_grad)` on the
    way in and added back the full `enable_grad` on the way out, so a bare
    `enable_grad` block at depth 0 left `self.no_grad == 1` behind it and every
    statement after it - including sibling function definitions later in the
    module - was marked `insideNoGrad`. MLV204 then reported high / 0.97 /
    `certain` "backward() inside torch.no_grad()" on the canonical
    temperature-scaling LBFGS closure, with no `no_grad` anywhere near it, and
    docs/ISSUE_RULES.md MLV204 documents `enable_grad` as the **negating**
    context.
    """
    root = write(tmp_path, "r204n", {"m.py": ENABLE_GRAD})
    assert "MLV204" not in codes(analyze(root))
    # The inverse control: the same statement under a real no_grad still fires.
    control = write(tmp_path, "r204m", {"m.py": NO_GRAD_CONTROL})
    assert "MLV204" in codes(analyze(control))


# ---------------------------------------------------------------- VIS2-13
def test_vis2_13_an_eval_in_the_caller_or_the_callee_counts(tmp_path):
    """MLV301's dominance search read ONE module - the one the forward pass is
    written in - and asked only whether the call sat in `region.func`.

    When the region is a loop in one function and the forward happens in a
    callee in another file (`tta_accuracy` -> `tta_logits`, `robust_accuracy`
    -> `fgsm`: the shape of every TTA and adversarial evaluation) those two are
    never the same module, so a `model.eval()` written immediately above the
    loop was invisible and the finding's own evidence row asserted "no
    torch.nn.Module.eval() dominates this region" about a workspace with nine
    of them.
    """
    doc = analyze(os.path.join(CORPUS, "vision_explain"))
    assert "MLV301" not in codes(doc), sorted(codes(doc))
    assert "MLV204" not in codes(doc), sorted(codes(doc))


# ---------------------------------------------------------------- VIS2-04
LAMBDA_WARMUP = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def warmup_cosine(optimizer, total_steps, warmup_steps):
    def factor(step):
        if step < warmup_steps:
            return step / max(1, warmup_steps)
        return 0.5 * (1.0 + (1.0 - step / total_steps))
    return torch.optim.lr_scheduler.LambdaLR(optimizer, factor)


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randint(0, 2, (64,)))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = nn.Linear(4, 2)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scheduler = warmup_cosine(optimizer, 10 * len(loader), 20)
    for epoch in range(10):
        for x, y in loader:
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            scheduler.step()
'''


def test_vis2_04_lambdalr_has_no_intrinsic_cadence(tmp_path):
    """`LambdaLR` and `PolynomialLR` were in the implementation's epoch-cadence
    set and NOT in the set docs/ISSUE_RULES.md section 4 documents.

    `LambdaLR` has no intrinsic cadence: the lambda receives whatever counter
    its owner steps, and `transformers.get_linear_schedule_with_warmup` -
    which the same rule lists in `_BATCH_CADENCE` - literally returns one.
    timm, DETR, MoCo, SimCLR and the FixMatch reference all build a LambdaLR
    over `epochs * len(loader)` steps and step it per batch, and MLV207 called
    that a defect at medium / 0.80 / likely with the evidence row "LambdaLR is
    in the epoch-cadence set of torch.optim.lr_scheduler".
    """
    root = write(tmp_path, "r207c", {"m.py": LAMBDA_WARMUP})
    assert "MLV207" not in codes(analyze(root))


# ---------------------------------------------------------------- VIS2-03
ONECYCLE_HELPER = '''import torch
import torch.nn as nn
from torch.optim.lr_scheduler import OneCycleLR
from torch.utils.data import DataLoader, TensorDataset


def train_one_epoch(model, loader, criterion, optimizer):
    for x, y in loader:
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randint(0, 2, (64,)))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = nn.Linear(4, 2)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    scheduler = OneCycleLR(optimizer, max_lr=0.1, total_steps=3 * len(loader))
    for epoch in range(3):
        train_one_epoch(model, loader, criterion, optimizer)
        scheduler.step()
'''


def test_vis2_03_the_batch_loop_may_live_in_the_epoch_helper(tmp_path):
    """`_encloses_batch_loop` was lexical only, so the standard decomposition -
    `for epoch in range(N): train_one_epoch(...); scheduler.step()` - had its
    batch loop in the callee and a `OneCycleLR` that finishes its whole cycle
    in the first few epochs was never reported. That decomposition is what
    torchvision's own references, timm, detectron2 and essentially every
    repository above one file uses."""
    root = write(tmp_path, "r207a", {"m.py": ONECYCLE_HELPER})
    assert "MLV207" in codes(analyze(root))


# ---------------------------------------------------------------- NLP2-03
DICT_MOVE = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader


def train(model, loader, optimizer, device):
    model = model.to(device)
    for batch in loader:
        batch = {key: value.to(device) for key, value in batch.items()}
        optimizer.zero_grad()
        out = model(input_ids=batch["input_ids"], labels=batch["labels"])
        out.loss.backward()
        optimizer.step()
'''


@pytest.mark.parametrize("mode", MODES)
def test_nlp2_03_a_dict_batch_moved_element_wise_counts_as_moved(tmp_path, mode):
    """MLV501 fired at 0.900 / `certain` on the canonical HuggingFace batch
    move, and both of its evidence sentences were false about the file.

    `_moved_names` recognised a move only when the `.to` attribute's own
    receiver was the batch NAME, so
    `batch = {key: value.to(device) for key, value in batch.items()}` - what
    every tokenizer/collator batch requires, and what the HF course,
    `run_glue.py`-style loops and the accelerate examples all write - read as
    "the batch was never moved", one line after a `.to(device)`.
    """
    root = write(tmp_path, "mlv501_dict", {"train.py": DICT_MOVE})
    assert "MLV501" not in codes(analyze(root, dataflow=mode))


# ---------------------------------------------------------------- INFRA-R2-10
def test_infra_r2_10_a_dynamic_factory_is_not_an_absence(tmp_path):
    """MLV501 stated a workspace-wide negative from a search it could not
    complete.

    `_any_model_move` accepted a `.to(...)` only when the receiver resolved
    under `torch.nn.Module` or carried MODEL. With the model produced by a
    factory MLView has ITSELF declared dynamic - `importlib.import_module(...)`
    plus `getattr(module, name)`, which raises a `dynamic_scope` diagnostic in
    the same document - the `.to(device)` chained onto the factory result had
    neither, so the search returned False and the rule reported, twice, at
    0.900 / `certain`, "the model model is never moved" with the evidence "no
    .to(device) / .cuda() on any nn.Module in the workspace" about a file whose
    line 161 is `model = build_model(...).to(device)`.
    """
    doc = analyze(os.path.join(CORPUS, "infra_conditional_imports"))
    assert "MLV501" not in codes(doc), sorted(codes(doc))
    assert any(d["kind"] == "dynamic_scope" for d in doc["diagnostics"]), (
        "the dynamic factory must still be declared")


# ------------------------------------------------- INFRA-R2-01 / INFRA-R2-05
DEEPSPEED_LOOP = '''import torch
import torch.nn as nn
import deepspeed
from torch.utils.data import DataLoader, TensorDataset


def main():
    ds = TensorDataset(torch.randn(64, 8), torch.randint(0, 3, (64,)))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = nn.Sequential(nn.Linear(8, 16), nn.ReLU(), nn.Linear(16, 3))
    criterion = nn.CrossEntropyLoss()
    engine, optimizer, _, _ = deepspeed.initialize(model=model, config="ds.json")
    for epoch in range(3):
        engine.train()
        for x, y in loader:
            loss = criterion(engine(x), y)
            engine.backward(loss)
            engine.step()
'''

TF_TAPE_LOOP = '''import tensorflow as tf
from tensorflow import keras


def main():
    tf.random.set_seed(0)
    model = keras.Sequential([keras.layers.Dense(8), keras.layers.Dense(3)])
    optimizer = keras.optimizers.Adam(1e-3)
    loss_fn = keras.losses.SparseCategoricalCrossentropy(from_logits=True)
    ds = tf.data.Dataset.from_tensor_slices((tf.random.normal((64, 4)),
                                             tf.zeros((64,), dtype=tf.int32)))
    ds = ds.batch(8)
    for batch in ds:
        features, labels = batch
        with tf.GradientTape() as tape:
            logits = model(features, training=True)
            loss = loss_fn(labels, logits)
        grads = tape.gradient(loss, model.trainable_variables)
        optimizer.apply_gradients(zip(grads, model.trainable_variables))
'''


@pytest.mark.parametrize("name,source", [("dsmin", DEEPSPEED_LOOP),
                                         ("tf1", TF_TAPE_LOOP)])
def test_infra_r2_01_a_framework_training_loop_is_not_evaluation(tmp_path, name, source):
    """A framework-owned training loop was drawn in the Evaluate lane and the
    answer card said "Evaluation runs in ..." at 0.95 about it.

    `_runs_without_training` disqualified a loop only on a **resolved** role,
    so `accelerator.backward(loss)`, DeepSpeed's `engine.backward(loss)` /
    `engine.step()`, `fabric.backward(loss)` and TensorFlow's
    `optimizer.apply_gradients(...)` all walked past it - and `.fit()` plus the
    `GradientTape` loop are the only two ways to train in TF2, so that is half
    the TensorFlow surface. The sibling `_runs_an_unresolved_model` already
    carried the correct syntactic guard, with a docstring promising exactly
    this, on a path that was never consulted as a disqualifier.
    """
    root = write(tmp_path, name, {"t.py": source})
    doc = analyze(root)
    kinds = {k for _s, k, _l in loops(doc)}
    assert "eval_loop" not in kinds, loops(doc)
    assert "train_loop" in kinds, loops(doc)
    assert "Evaluation runs in" not in sentence(doc, "evaluation")


def test_infra_r2_01_the_shipped_deepspeed_program_is_a_trainer():
    """`infra_deepspeed`'s own labels.json calls it a DeepSpeed trainer, and
    its batch loop was node `eval / eval_loop` with the card naming it as a
    place evaluation runs."""
    doc = analyze(os.path.join(CORPUS, "infra_deepspeed"))
    # The training loop - `engine(features)` / `engine.backward(loss)` /
    # `engine.step()` - was node `eval / eval_loop` at train_deepspeed.py:93,
    # and the card named it as a place evaluation runs at confidence 0.95. The
    # program's real `evaluate()` (under `@torch.no_grad()`) is an eval loop
    # and stays one.
    mislabelled = [n for n in doc["nodes"]
                   if n["kind"] == "eval_loop"
                   and "train_loader" in (n.get("label") or "")]
    assert not mislabelled, [(n["label"], n["loc"]["line"]) for n in mislabelled]
    train_loops = [n["loc"]["line"] for n in doc["nodes"]
                   if n["kind"] == "train_loop"]
    assert train_loops, [(n["kind"], n["label"]) for n in doc["nodes"]
                         if n["kind"].endswith("_loop")]


# ---------------------------------------------------------------- ROB-15/16
def test_rob15_parallel_assignment_binds_each_slot_from_its_own_expression(tmp_path):
    """`opt, crit = torch.optim.Adam(...), nn.CrossEntropyLoss()` bound BOTH
    names with no tags and no producer, because `_bind_record` asked
    `record.call` for per-slot tags and a tuple literal has no call."""
    source = ("import torch\nimport torch.nn as nn\n"
              "from torch.utils.data import DataLoader\n\n\n"
              "def train(ds):\n"
              "    model = nn.Linear(16, 3)\n"
              "    opt, crit = torch.optim.Adam(model.parameters()), nn.CrossEntropyLoss()\n"
              "    loader = DataLoader(ds, batch_size=8, shuffle=True)\n"
              "    for xb, yb in loader:\n"
              "        loss = crit(model(xb), yb)\n"
              "        loss.backward()\n"
              "        opt.step()\n"
              "    return model\n")
    root = write(tmp_path, "tuple_pair", {"m.py": source})
    doc = analyze(root)
    assert "MLV201" in codes(doc), sorted(codes(doc))
    assert "train_loop" in {k for _s, k, _l in loops(doc)}, loops(doc)


# ---------------------------------------------------------------- VIS2-06
DICT_CRITERIA = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


class Discriminator(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(8, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x):
        return self.net(x)


def train_one_epoch(model, loader, criteria, optimizer):
    criterion = criteria["adversarial"]
    for x, y in loader:
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 8), torch.rand(64, 1))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = Discriminator()
    criteria = {"adversarial": nn.BCELoss(), "pixel": nn.L1Loss()}
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    train_one_epoch(model, loader, criteria, optimizer)
'''


@pytest.mark.parametrize("mode", MODES)
def test_vis2_06_a_dict_literal_read_by_a_constant_key_keeps_its_type(tmp_path, mode):
    """`criterion = criteria["adversarial"]` made the loss binding an opaque
    subscript, so a `BCELoss` fed raw logits - MLV402's `missing_sigmoid`
    variant, high / 0.95 / certain when the same criterion is a plain name -
    became silence, and the MLV2xx family went with it. Multi-loss and
    multi-optimizer dicts are the normal layout for GANs, detectors and
    multi-task models (BasicSR, mmdet's loss registry, CycleGAN)."""
    root = write(tmp_path, "r402e", {"m.py": DICT_CRITERIA})
    assert "MLV402" in codes(analyze(root, dataflow=mode))


# ---------------------------------------------------------------- VIS2-09
CUSTOM_LOSS = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


class DiceLoss(nn.Module):
    def __init__(self, eps=1e-6):
        super().__init__()
        self.eps = eps

    def forward(self, logits, target):
        probs = torch.sigmoid(logits)
        inter = (probs * target).sum()
        union = probs.sum() + target.sum()
        return 1.0 - (2.0 * inter + self.eps) / (union + self.eps)


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.rand(64, 4))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = nn.Linear(4, 4)
    criterion = DiceLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    running = 0.0
    for x, y in loader:
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
        running += loss
    return running
'''


def test_vis2_09_a_workspace_loss_module_earns_the_loss_tag(tmp_path):
    """A workspace `nn.Module` loss class - `DiceLoss`, `FocalLoss`,
    `JointsMSELoss`, YOLO's `ComputeLoss`, the dominant shape in detection,
    segmentation and pose - silenced MLV205 with **no** coverage diagnostic:
    the backward node was drawn, the objective lane was non-empty, and the
    document said nothing about the rule not having judged the step.

    The evidence is structural and carries no name regex: the class registers
    no submodules (nothing it constructs carries the MODEL tag) and its body
    reduces a tensor.
    """
    root = write(tmp_path, "rcust1", {"m.py": CUSTOM_LOSS})
    assert "MLV205" in codes(analyze(root))


# ---------------------------------------------------------------- NLP2-01
IDENTITY_RETURN = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(4, 2)
        self.drop = nn.Dropout(0.2)

    def forward(self, x):
        return self.fc(self.drop(x))


def train(model, loader):
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
    criterion = nn.CrossEntropyLoss()
    for x, y in loader:
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
    return model


def evaluate(model, loader):
    correct = 0
    for x, y in loader:
        correct += int((model(x).argmax(-1) == y).sum())
    return correct


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randint(0, 2, (64,)))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = train(Net(), loader)
    print(evaluate(model, loader))
'''


@pytest.mark.parametrize("mode", MODES)
def test_nlp2_01_an_inline_constructor_argument_types_the_parameter(tmp_path, mode):
    """`propagate_parameters` looked the argument up by NAME, so an argument
    written **inline** - `train(Net(), loader)`,
    `to_device(build_model(), device)` - left the parameter untyped and
    everything downstream of it evaporated.

    Observed on `hydra_research` and `amp_accumulation`: `model = train(Net(),
    loader)` meant `model(features)` inside `validate()` resolved to nothing,
    no eval region was built, and MLV301 (high) and MLV302 both vanished with
    `diagnostics: []`.
    """
    root = write(tmp_path, "torch_ret3", {"m.py": IDENTITY_RETURN})
    doc = analyze(root, dataflow=mode)
    assert {"MLV301", "MLV302"} <= codes(doc), sorted(codes(doc))
    assert [s["present"] for s in doc["stages"] if s["id"] == "eval"] == [True]


# ---------------------------------------------------------------- NLP2-04
DS_CHAIN_SPLIT = '''from datasets import load_dataset
from transformers import AutoTokenizer


def read_shards(data_files):
    raw = load_dataset("text", data_files=data_files)
    return raw["train"]


def split_documents(documents):
    return documents.train_test_split(test_size=0.02)


def encode(tokenizer, split):
    return split.map(lambda b: tokenizer(b["text"]), batched=True)


def main():
    tokenizer = AutoTokenizer.from_pretrained("roberta-base")
    documents = read_shards("shards/*.txt")
    split = split_documents(documents)
    return encode(tokenizer, split)
'''


@pytest.mark.parametrize("mode", MODES)
def test_nlp2_04_the_datasets_chain_survives_a_helper_boundary(tmp_path, mode):
    """Round 1 fixed the same-scope form (`raw = load_dataset(...)["train"]`).
    The cross-function form - a `read_shards()` whose `return` is a subscript -
    fell straight through `ir/returns._slot` to `None`, so `train_test_split`
    and every `.map` drew no node, MLV601 and MLV602 both went silent, and
    `diagnostics` was empty. It is how every non-notebook project writes it."""
    root = write(tmp_path, "ds_split_ns", {"data.py": DS_CHAIN_SPLIT})
    assert "MLV602" in codes(analyze(root, dataflow=mode))


# ---------------------------------------------------------------- DGRG2-01
RESTORE_BELOW = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(4, 2)
        self.drop = nn.Dropout(0.5)

    def forward(self, x):
        return self.fc(self.drop(x))


def evaluate(model, loader):
    correct = 0
    for x, y in loader:
        logits = model(x)
        correct += int((logits.argmax(dim=-1) == y).sum())
    return correct


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randint(0, 2, (64,)))
    test_loader = DataLoader(ds, batch_size=8, shuffle=False)
    model = Net()
    print(evaluate(model, test_loader))
    torch.save(model, "best.pt")
    model = torch.load("best.pt", weights_only=False)
    print(evaluate(model, test_loader))
'''


@pytest.mark.parametrize("mode", MODES)
def test_dgrg2_01_a_checkpoint_restored_into_a_model_is_still_a_model(tmp_path, mode):
    """`torch.load` carries `tags: ()`, so one `model = torch.load(path)` -
    written two statements BELOW the evaluation call - replaced a MODEL-tagged
    binding with an untyped checkpoint for the whole scope, bindings being flat.

    Observed on a 30-line file: without the restore line, 11 nodes, MLV301
    high/0.850 + MLV302 medium/0.850, a `model.eval() · missing` ghost and a
    `metric argmax()` node; with it, **10 nodes, 0 issues, 0 diagnostics** and
    a verdict reading "No findings: no rule fired on this workspace" next to a
    claim that nothing here measures quality - about a file that computes
    `(logits.argmax(dim=-1) == y).sum()`. On `adv_gnn_sage_bad` the same line
    also erased the MLV803 on `torch.save(model, ...)`, because the rule could
    no longer tell a module from a state_dict.
    """
    root = write(tmp_path, "restore", {"m.py": RESTORE_BELOW})
    doc = analyze(root, dataflow=mode)
    assert {"MLV301", "MLV302", "MLV803"} <= codes(doc), sorted(codes(doc))


# ---------------------------------------------------------------- TAB2-02
SAVE_THEN_LOAD = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

CHECKPOINT = "model.pt"


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = nn.Linear(4, 1)
        self.drop = nn.Dropout(0.3)

    def forward(self, x):
        return self.fc(self.drop(x))


def evaluate(model, loader, criterion):
    total = 0.0
    for history, future in loader:
        prediction = model(history)
        total += criterion(prediction, future).item()
    return total


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randn(64, 1))
    test_loader = DataLoader(ds, batch_size=8, shuffle=False)
    criterion = nn.MSELoss()
    model = Net()
    torch.save(model, CHECKPOINT)
    restored = torch.load(CHECKPOINT)
    return evaluate(restored, test_loader, criterion)
'''


@pytest.mark.parametrize("mode", MODES)
def test_tab2_02_a_restored_checkpoint_can_be_evaluated(tmp_path, mode):
    """"Load a checkpoint, then evaluate it" is the shape of every `eval.py`
    and `predict.py` in the world, and `restored = torch.load(CKPT)` silenced
    MLV301 **and** MLV302 completely, with an empty `diagnostics` array - and
    the Answers card did not negate its guardedness clause, it dropped it, so
    the sentence a reader sees is indistinguishable from a clean report.

    The evidence used is dataflow, not a name: a SAVE call writes a
    MODEL-tagged value to the same path expression this load reads.
    `torch.save(model.state_dict(), ...)` does not match, because a state_dict
    carries no MODEL tag.
    """
    root = write(tmp_path, "seq", {"t.py": SAVE_THEN_LOAD})
    doc = analyze(root, dataflow=mode)
    assert {"MLV301", "MLV302"} <= codes(doc), sorted(codes(doc))
    assert "could not be judged" not in sentence(doc, "evaluation")


# ---------------------------------------------------------------- DGRG2-02
STEP_IN_HELPER = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


def train_step(model, crit, opt, x, y):
    loss = crit(model(x), y)
    opt.zero_grad()
    opt.step()
    loss.backward()
    return loss.item()


def main():
    torch.manual_seed(0)
    ds = TensorDataset(torch.randn(64, 4), torch.randint(0, 2, (64,)))
    loader = DataLoader(ds, batch_size=8, shuffle=True)
    model = nn.Linear(4, 2)
    crit = nn.CrossEntropyLoss()
    opt = torch.optim.SGD(model.parameters(), lr=0.1)
    for x, y in loader:
        train_step(model, crit, opt, x, y)
'''


def test_dgrg2_02_mlv203_follows_the_same_hop_mlv201_follows(tmp_path):
    """MLV203 read the loop body lexically while MLV201 and MLV202 read
    `calls_in_loop`, which the module docstring says follows "one level of
    module-local helper calls". Moving the identical three statements into the
    canonical `def train_step(...)` helper therefore made a high-severity
    finding vanish - with **no** diagnostic, because `note_untagged_loop` skips
    a loop whose chain already contains a confirmed batch loop."""
    root = write(tmp_path, "helper", {"m.py": STEP_IN_HELPER})
    assert "MLV203" in codes(analyze(root))


# ---------------------------------------------------------------- DGRG2-04
PYG_SCRIPT = '''import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.datasets import Planetoid
from torch_geometric.loader import NeighborLoader
from torch_geometric.nn import SAGEConv


class SAGE(nn.Module):
    def __init__(self, in_dim, hidden, out_dim):
        super().__init__()
        self.conv1 = SAGEConv(in_dim, hidden)
        self.conv2 = SAGEConv(hidden, out_dim)

    def forward(self, x, edge_index):
        return self.conv2(F.relu(self.conv1(x, edge_index)), edge_index)


def main():
    torch.manual_seed(0)
    data = Planetoid("/tmp/pl", "Cora")[0]
    train_loader = NeighborLoader(data, num_neighbors=[10, 10], batch_size=64)
    val_loader = NeighborLoader(data, num_neighbors=[10, 10], batch_size=64)
    model = SAGE(data.num_features, 64, 7)
    opt = torch.optim.Adam(model.parameters(), lr=0.01)
    for batch in train_loader:
        loss = F.cross_entropy(model(batch.x, batch.edge_index), batch.y)
        loss.backward()
        opt.step()
    for batch in val_loader:
        model(batch.x, batch.edge_index)
'''


def test_dgrg2_04_the_data_answer_carries_the_coverage_clause(tmp_path):
    """`_objective` and `_evaluation` both hedge their absence sentence with
    the coverage clause; `_data_entry` did not take the parameter at all.

    The FIRST line a reader or an agent sees therefore said "nothing in this
    workspace builds a dataset or a loader" about a file containing
    `Planetoid(...)` and two `NeighborLoader(...)` calls, while the stage list
    two lines below carried the `unverified` qualifier and the verdict said it
    was not a clean bill of health - one payload contradicting itself.
    """
    root = write(tmp_path, "pyg", {"m.py": PYG_SCRIPT})
    doc = analyze(root)
    text = sentence(doc, "dataEntry")
    if "No data entry was detected" in text:
        assert "resolved" in text and "could not" in text, text
    # DGRG2-13: with the torch_geometric rows, the loaders are simply drawn.
    assert "data" in {s["id"] for s in doc["stages"] if s["present"]}


# ---------------------------------------------------------------- INFRA-R2-11
BROKEN = '''import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

def main(:
    ds = TensorDataset(torch.randn(8, 2), torch.zeros(8, dtype=torch.long))
    loader = DataLoader(ds, batch_size=2)
    model = nn.Linear(2, 2)
'''


def test_infra_r2_11_an_unparsed_file_reaches_the_verdict(tmp_path):
    """`_COVERAGE_KINDS` held three kinds, and three strictly LARGER gaps were
    outside it: a file that failed to parse, a notebook that was never opened,
    and the unreadable-directory note round 1 added (emitted as `parse_error`).

    With `filesFailed: 1` the card said "No data entry was detected: nothing in
    this workspace builds a dataset or a loader", "nothing in the objective
    stage and no backward() call", and the verdict was a bare "No findings: no
    rule fired on this workspace." - about a workspace whose only ML file is
    the unparsed one. §11.23 A8 is normative and the answers layer is the layer
    an agent quotes.
    """
    root = write(tmp_path, "pe1", {"train.py": BROKEN,
                                   "util.py": "def describe(x):\n    return repr(x)\n"})
    doc = analyze(root)
    assert doc["workspace"]["filesFailed"] == 1
    verdict = sentence(doc, "verdict")
    assert "clean bill of health" in verdict, verdict


def test_infra_r2_11_a_notebooks_only_workspace_says_it_read_nothing():
    """`filesAnalyzed: 0, notebooksSkipped: 3`, all eight stages absent, and
    four confident absence claims about code MLView never opened."""
    doc = analyze(os.path.join(CORPUS, "infra_notebooks_only"))
    assert doc["workspace"]["filesAnalyzed"] == 0
    for field in ("dataEntry", "objective", "evaluation"):
        assert "analyzed 0 files" in sentence(doc, field), sentence(doc, field)


# ---------------------------------------------------------------- NLP2-02
def test_nlp2_02_the_guard_clause_names_only_guards_that_cover_the_region():
    """The clause was appended whenever **any** EVAL_MODE call had been
    collected anywhere in the eval stage, without asking whose model it
    switched.

    On `nlp_distil_bert_bad` the card read "the eval path is guarded by eval()
    at distill.py:75" - which is `teacher.eval()`, the frozen teacher - about
    an evaluation that runs `student`, a BERT with dropout in every block, in
    train mode. The teacher/student, policy/reference, generator/discriminator
    and online/target shapes all pair one frozen `.eval()` model with one
    trained one.
    """
    doc = analyze(os.path.join(CORPUS, "nlp_distil_bert_bad"))
    text = sentence(doc, "evaluation")
    assert "the eval path is guarded by" not in text, text


# ---------------------------------------------------------------- VIS2-15
def test_vis2_15_a_method_name_alone_does_not_name_a_framework(tmp_path):
    """`tolist` was registered for pandas only, so `np.array(...).tolist()`
    resolved to `pandas.Series.tolist` and put **pandas** into
    `workspace.frameworks` - which the README, the VS Code status-bar tooltip
    and every chat digest present as a statement about the project - on a pure
    numpy + torch workspace with no `import pandas` anywhere."""
    source = ("import numpy as np\nimport torch\n\n\n"
              "def to_lists(record):\n"
              "    boxes = np.array(record[\"boxes\"], dtype=np.float32).reshape(-1, 4)\n"
              "    return boxes.tolist()\n")
    root = write(tmp_path, "fwb", {"m.py": source})
    assert "pandas" not in analyze(root)["workspace"]["frameworks"]


# ---------------------------------------------------------------- VIS2-14
def test_vis2_14_the_two_truncations_are_distinguishable():
    """Four different losses shared `kind: "truncated"` - files never read,
    nodes rolled up into an ancestor, IR rounds capped, an interprocedural
    chain stopped - and they need different fixes and mean different things for
    trust. `scope` names which one."""
    tree = os.path.join(REPO_ROOT, "analyzer", "tests")
    doc = analyze_to_dict(AnalyzeOptions(paths=(tree,), max_nodes=20, max_files=500,
                                         cache=False))
    rows = {d.get("scope") for d in doc["diagnostics"] if d["kind"] == "truncated"}
    assert {"files", "nodes"} <= rows, rows
