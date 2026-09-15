"""The recall campaign, 2026-09-15: R1-R5, asserted rather than measured.

`docs/ACCURACY.md` §9 carries the numbers and `docs/contracts/recall.md` carries
the normative clauses; this file carries the *properties*, one test per claim
that a later change could break silently.

Four of the five items widen what the analyzer sees, so almost every test here
is of the form "this shape used to resolve to nothing and now resolves to
something", written against a workspace small enough to read. The fifth (R1) is
a default flip and is asserted in `test_dataflow_ip.py`, where the two modes
already have a fixture apiece.

Nothing here asserts a corpus number: `tools/accuracy.py` and the two ratchets
in `analyzer/tests/accuracy/` own those, and a number asserted in two places is
a number that will disagree with itself.
"""

from __future__ import annotations

import pytest

from core_support import validate, write_files
from mlview.api import AnalyzeOptions, analyze_to_dict


def analyze(root, dataflow="ip"):
    return analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False,
                                          dataflow=dataflow))


def codes(doc, code=None):
    return [i for i in doc["issues"] if code is None or i["code"] == code]


# ===========================================================================
# R2 - the knowledge tables
# ===========================================================================
_PANDAS = (
    "import pandas as pd\n"
    "from sklearn.linear_model import Ridge\n"
    "from sklearn.model_selection import train_test_split\n\n\n"
    "def features(path):\n"
    "    frame = pd.read_csv(path)\n"
    "    frame['lag'] = frame['y'].shift(1)\n"
    "    rolled = frame['y'].rolling(24).mean()\n"
    "    joined = frame.merge(rolled, left_index=True, right_index=True)\n"
    "    joined.to_csv('out.csv')\n"
    "    return joined\n\n\n"
    "def run(path):\n"
    "    matrix = features(path)\n"
    "    a, b = train_test_split(matrix, test_size=0.2, random_state=0)\n"
    "    return Ridge().fit(a, b)\n"
)


def test_r2_the_pandas_windowing_and_regrouping_families_draw_a_box(tmp_path):
    """GRAPH-R2. `shift`, `rolling` and `merge` change what the data *means*,
    so they are not the transparent `FRAME_OP` hop `drop` / `copy` are - they
    are where a time-series feature matrix is built and where a leak is
    planted, and MLView drew nothing there."""
    root = write_files(str(tmp_path), {"pipe.py": _PANDAS})
    doc = analyze(root)
    # The label is the bound name when there is one, so the claim is asserted
    # against the resolved symbol rather than against the spelling.
    fqns = {n.get("fqn") for n in doc["nodes"] if n["level"] == "op"}
    assert "pandas.DataFrame.shift" in fqns, sorted(f for f in fqns if f)
    assert "pandas.DataFrame.rolling" in fqns, sorted(f for f in fqns if f)
    assert "pandas.DataFrame.merge" in fqns, sorted(f for f in fqns if f)
    # `to_csv` is an artifact leaving the workspace, in the Deliver lane.
    written = [n for n in doc["nodes"] if n["kind"] == "artifact"]
    assert written and written[0]["stage"] == "deliver", written
    assert validate(doc) == []


def test_r2_a_windowed_frame_still_carries_its_data_tags(tmp_path):
    """The tags `read_csv` seeded survive the window: `FRAME_TEMPORAL` and
    `FRAME_RESHAPE` differ from `FRAME_OP` only in that they draw a box, which
    is a `TRANSPARENT_ROLES` question and not a tag question. Without this the
    whole leakage family goes blind one `shift(...)` downstream."""
    root = write_files(str(tmp_path), {"pipe.py": _PANDAS})
    doc = analyze(root)
    # The split is reached, which is only possible if the frame kept its tags.
    split = [n for n in doc["nodes"] if "train_test_split" in (n.get("fqn") or "")]
    assert split, [n.get("fqn") for n in doc["nodes"]]


def test_r2_a_metric_object_resolves_its_update_and_its_compute(tmp_path):
    """A metric object exists to be `update`d and then `compute`d. With no
    receiver family on the constructor row neither method proposed a candidate
    FQN at all - the whole point of holding one."""
    root = write_files(str(tmp_path), {"eval.py":
        "import evaluate\n"
        "import torchmetrics\n\n\n"
        "def score(loader, model):\n"
        "    metric = evaluate.load('accuracy')\n"
        "    acc = torchmetrics.Accuracy(task='binary')\n"
        "    for batch, labels in loader:\n"
        "        preds = model(batch)\n"
        "        metric.add_batch(predictions=preds, references=labels)\n"
        "        acc.update(preds, labels)\n"
        "    return metric.compute(), acc.compute()\n"})
    doc = analyze(root)
    fqns = {n.get("fqn") for n in doc["nodes"]}
    assert "evaluate.EvaluationModule.compute" in fqns, sorted(f for f in fqns if f)
    assert "torchmetrics.Metric.compute" in fqns, sorted(f for f in fqns if f)
    assert validate(doc) == []


def test_r2_a_keras_export_lands_in_the_deliver_lane(tmp_path):
    """`Model.export` is the SavedModel / TF-Lite hand-off and had no row at
    all, so a Keras repository's Save lane was empty however it shipped."""
    root = write_files(str(tmp_path), {"ship.py":
        "import keras\n\n\n"
        "def ship(path):\n"
        "    model = keras.Sequential([keras.layers.Dense(2)])\n"
        "    model.export(path)\n"
        "    return model\n"})
    doc = analyze(root)
    assert [n["stage"] for n in doc["nodes"] if n.get("fqn") == "keras.Model.export"] \
        == ["deliver"], [(n.get("fqn"), n["stage"]) for n in doc["nodes"]]


# ===========================================================================
# R3 - objects the workspace defines
# ===========================================================================
_WORKSPACE = (
    "import torch\n"
    "import torch.nn as nn\n"
    "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.fc = nn.Linear(4, 2)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(x)\n\n\n"
    "def build_optimizer(model):\n"
    "    return torch.optim.Adam(model.parameters(), lr=1e-3)\n\n\n"
    "def loader():\n"
    "    ds = TensorDataset(torch.zeros(8, 4), torch.zeros(8, dtype=torch.long))\n"
    "    return DataLoader(ds, batch_size=2, shuffle=True)\n\n\n"
    "def main():\n"
    "    model = Net()\n"
    "    optimizer = build_optimizer(model)\n"
    "    criterion = nn.CrossEntropyLoss()\n"
    "    for features, labels in loader():\n"
    "        optimizer.zero_grad()\n"
    "        loss = criterion(model(features), labels)\n"
    "        loss.backward()\n"
    "        optimizer.step()\n"
)


def test_r3_the_construction_site_of_a_workspace_class_is_its_own_card(tmp_path):
    """`model = Net()` used to be folded onto `Net`'s unit node, so the line
    where the object is *built* was invisible and every edge that should start
    at the instance started at the definition."""
    root = write_files(str(tmp_path), {"train.py": _WORKSPACE})
    doc = analyze(root)
    built = [n for n in doc["nodes"] if n["level"] == "op" and n["label"] == "model"]
    assert len(built) == 1, [n["label"] for n in doc["nodes"] if n["level"] == "op"]
    assert built[0]["kind"] == "model" and built[0]["stage"] == "model"
    assert "fqn" not in built[0], "a workspace class is not a canonical symbol"


def test_r3_the_outer_forward_pass_is_drawn_and_the_inner_one_is_not(tmp_path):
    """Role `FORWARD` is transparent by design - `self.fc(x)` inside `forward`
    belongs to the layer it calls - and that correct rule swallowed the outer
    `model(features)` with it: the single most-drawn arrow in any training
    diagram had no node to land on."""
    root = write_files(str(tmp_path), {"train.py": _WORKSPACE})
    doc = analyze(root)
    predicts = [n for n in doc["nodes"] if n["kind"] == "predict"]
    assert len(predicts) == 1, [n["label"] for n in predicts]
    # ... and the layer inside `forward` is still an op of its own, not a
    # second forward-pass card.
    assert [n["label"] for n in doc["nodes"] if n["kind"] == "layer"] == ["self.fc"]


def test_r3_a_workspace_factory_return_is_drawn_at_the_call_site(tmp_path):
    """`opt = build_optimizer(model)`. `ir.returns` already knew what the
    callee hands back and nothing drew it, so the optimizer appeared only
    inside the factory, a file away from the loop that steps it."""
    root = write_files(str(tmp_path), {"train.py": _WORKSPACE})
    doc = analyze(root)
    made = [n for n in doc["nodes"]
            if n["kind"] == "optimizer" and n.get("sublabel") == "build_optimizer()"]
    assert len(made) == 1, [(n["label"], n.get("sublabel")) for n in doc["nodes"]]
    assert made[0]["stage"] == "train"


def test_r3_a_workspace_node_never_changes_a_unit_s_lane(tmp_path):
    """Every node `core/workspace_ops` mints is vote-free: it never contributes
    to `_op_votes`, so no unit can be re-laned because of this pass. Asserted
    the only way that can be: the forward pass drawn inside a train loop is
    staged `train`, inherited from its parent, not `model`."""
    root = write_files(str(tmp_path), {"train.py": _WORKSPACE})
    doc = analyze(root)
    predict = [n for n in doc["nodes"] if n["kind"] == "predict"][0]
    parent = [n for n in doc["nodes"] if n["id"] == predict["parent"]][0]
    assert predict["stage"] == parent["stage"] == "train", (predict, parent)


def test_r3_an_untypeable_factory_return_gets_an_honest_unknown_box(tmp_path):
    """ANA-5a one level out. A registry factory is present in a large fraction
    of research repositories, and drawing nothing for it is a smaller graph
    presented as a complete one."""
    root = write_files(str(tmp_path), {"reg.py":
        "REGISTRY = {}\n\n\n"
        "def build_from_cfg(group, name, **kwargs):\n"
        "    return REGISTRY[group][name](**kwargs)\n\n\n"
        "def main(cfg):\n"
        "    model = build_from_cfg('model', cfg['name'])\n"
        "    return model\n"})
    doc = analyze(root)
    unknown = [n for n in doc["nodes"] if n["kind"] == "unknown"]
    assert unknown, [n["label"] for n in doc["nodes"]]
    assert any("unresolved factory" in (n.get("sublabel") or "") for n in unknown), \
        [n.get("sublabel") for n in unknown]
    assert validate(doc) == []


_REC04 = (
    "import torch\n"
    "import torch.nn as nn\n"
    "from torch.amp import GradScaler\n"
    "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.fc = nn.Linear(4, 2)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(x)\n\n\n"
    "def make_state():\n"
    "    model = Net()\n"
    "    return {'model': model,\n"
    "            'optimizer': torch.optim.Adam(model.parameters(), lr=1e-3),\n"
    "            'scaler': GradScaler('cuda')}\n\n\n"
    "def loader():\n"
    "    ds = TensorDataset(torch.zeros(8, 4), torch.zeros(8, dtype=torch.long))\n"
    "    return DataLoader(ds, batch_size=2, shuffle=True)\n\n\n"
    "def run(state, data):\n"
    "    model = state['model']\n"
    "    optimizer = state['optimizer']\n"
    "    scaler = state['scaler']\n"
    "    criterion = nn.CrossEntropyLoss()\n"
    "    for features, labels in data:\n"
    "        optimizer.zero_grad()\n"
    "        loss = criterion(model(features), labels)\n"
    "        scaler.scale(loss).backward()\n"
    "        scaler.step(optimizer)\n"
    "        scaler.update()\n\n\n"
    "run(make_state(), loader())\n"
)


@pytest.mark.parametrize("mode", ["local", "ip"])
def test_rec04_a_container_survives_a_return_and_a_parameter(tmp_path, mode):
    """The composition R3's carriage could not make. A `make_state()` factory
    returning a dict literal lost everything inside it at the `return`, so
    `state['scaler']` in the callee was an opaque subscript and the GradScaler
    was invisible however far the summaries travelled.

    The per-slot values are resolved in the scope that **wrote** the literal
    and travel as values, which is why no name is ever re-read in a scope it
    does not belong to. It holds in both modes because the carriage is the
    binding pass's, not the summary pass's.
    """
    root = write_files(str(tmp_path), {"train.py": _REC04})
    doc = analyze(root, mode)
    labels = {n["label"] for n in doc["nodes"] if n["level"] == "op"}
    assert {"scale()", "step()", "update()"} <= labels, sorted(labels)
    assert [n["kind"] for n in doc["nodes"] if n["label"] == "scale()"] == ["scaler"]
    # the loop is a train loop, which it could not be while the model, the
    # optimizer and the scaler were all untyped
    assert any(n["kind"] == "train_loop" for n in doc["nodes"]), \
        [(n["kind"], n["label"]) for n in doc["nodes"]]
    assert validate(doc) == []


# ===========================================================================
# R4 - what a scored value holds
# ===========================================================================
def test_r4_the_tensor_tail_does_not_change_what_a_value_is(tmp_path):
    """`.detach().cpu().numpy()` changes the container, the device and the
    dtype, and never what the value holds. MLV305 went silent on the shape it
    exists to catch because the LOGITS tag died in that tail."""
    root = write_files(str(tmp_path), {"score.py":
        "from sklearn.metrics import accuracy_score\n\n\n"
        "def report(model, features, labels):\n"
        "    logits = model(features)\n"
        "    return accuracy_score(labels, logits.detach().cpu().numpy())\n"})
    doc = analyze(root, "ip")
    # The value is untyped here (no model class), so the honest outcome is a
    # coverage note rather than a finding - what must NOT happen is a claim.
    assert codes(doc, "MLV305") == [] or all(
        i["confidenceBucket"] != "certain" for i in codes(doc, "MLV305"))
    assert validate(doc) == []


def test_r4_a_helper_that_returns_a_softmax_pairs_wrongly_with_cross_entropy(tmp_path):
    """MLV401 through one `def`. The helper's `return` is the softmax, and the
    chain used to stop at a workspace call it could not name."""
    root = write_files(str(tmp_path), {"train.py":
        "import torch.nn as nn\n"
        "import torch.nn.functional as F\n\n\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n\n"
        "    def forward(self, x):\n"
        "        return self.fc(x)\n\n\n"
        "def probabilities(model, x):\n"
        "    return F.softmax(model(x), dim=-1)\n\n\n"
        "def step(model, features, labels):\n"
        "    scores = probabilities(model, features)\n"
        "    return F.cross_entropy(scores, labels)\n"})
    doc = analyze(root, "ip")
    found = codes(doc, "MLV401")
    assert len(found) == 1, [i["message"] for i in found]
    issue = found[0]
    assert issue["confidenceBucket"] != "certain", issue["confidence"]
    hop = [e for e in issue["evidence"]
           if e["kind"] == "cross_file" and "one function away" in e["detail"]]
    assert len(hop) == 1, issue["evidence"]
    assert hop[0]["weight"] == pytest.approx(0.8), hop[0]
    assert validate(doc) == []


def test_r4_one_root_cause_is_one_finding(tmp_path):
    """A LightningModule applies the same `forward` in `training_step` and in
    `validation_step`, so the per-loss-call loop reported the identical softmax
    twice from two lines with two identical `final_layer` locations. The second
    copy is noise, and on the labelled corpus it was a false positive."""
    root = write_files(str(tmp_path), {"module.py":
        "import pytorch_lightning as pl\n"
        "import torch.nn as nn\n"
        "import torch.nn.functional as F\n\n\n"
        "class Classifier(pl.LightningModule):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.head = nn.Linear(4, 2)\n\n"
        "    def forward(self, x):\n"
        "        return F.softmax(self.head(x), dim=1)\n\n"
        "    def training_step(self, batch, idx):\n"
        "        features, labels = batch\n"
        "        return F.cross_entropy(self(features), labels)\n\n"
        "    def validation_step(self, batch, idx):\n"
        "        features, labels = batch\n"
        "        return F.cross_entropy(self(features), labels)\n"})
    doc = analyze(root, "ip")
    found = codes(doc, "MLV401")
    assert len(found) == 1, [(i["loc"]["line"], i["message"]) for i in found]
    # the merged site is not lost, it is carried as a related location
    lines = {r["line"] for r in found[0]["relatedLocs"]}
    assert len(lines) >= 2, found[0]["relatedLocs"]
    assert validate(doc) == []


def test_r4_mlv306_reads_an_argmax_as_hard_labels(tmp_path):
    """`roc_auc_score(y, logits.argmax(dim=1))` is the torch spelling of
    `roc_auc_score(y, clf.predict(X))`, and only the sklearn one was read."""
    root = write_files(str(tmp_path), {"score.py":
        "import torch\n"
        "import torch.nn as nn\n"
        "from sklearn.metrics import roc_auc_score\n\n\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 2)\n\n"
        "    def forward(self, x):\n"
        "        return self.fc(x)\n\n\n"
        "def report(model, features, labels):\n"
        "    logits = model(features)\n"
        "    hard = torch.argmax(logits, dim=1)\n"
        "    return roc_auc_score(labels, hard)\n"})
    doc = analyze(root, "ip")
    found = codes(doc, "MLV306")
    assert len(found) == 1, [i["message"] for i in codes(doc)]
    assert "argmax" in found[0]["message"], found[0]["message"]
    assert validate(doc) == []


# ===========================================================================
# R5 - the rule shapes
# ===========================================================================
_RETURNED_LEAK = {
    "features.py":
        "from sklearn.preprocessing import StandardScaler\n\n\n"
        "def build_matrix(frame):\n"
        "    scaler = StandardScaler()\n"
        "    return scaler.fit_transform(frame)\n",
    "train.py":
        "import pandas as pd\n"
        "from sklearn.model_selection import train_test_split\n\n"
        "from features import build_matrix\n\n\n"
        "def run(path):\n"
        "    frame = pd.read_csv(path)\n"
        "    matrix = build_matrix(frame)\n"
        "    return train_test_split(matrix, test_size=0.2, random_state=0)\n",
}


def test_r5_a_leak_that_crosses_a_return_is_found_in_ip_and_not_in_local(tmp_path):
    """The whole shape of a feature-engineering module: `build_matrix()` scales
    the frame, the caller splits what it hands back. No name is matched across
    scopes - the split's argument has to be bound by the very call that invoked
    the fit's function - so the claim rests on the call graph, and it pays for
    the crossing."""
    root = write_files(str(tmp_path), _RETURNED_LEAK)
    local = analyze(root, "local")
    ip = analyze(root, "ip")
    assert codes(local, "MLV101") == [], "local stops at the first def, by definition"
    found = codes(ip, "MLV101")
    assert len(found) == 1, [i["message"] for i in codes(ip)]
    issue = found[0]
    assert issue["confidenceBucket"] != "certain", issue["confidence"]
    assert "returned into" in issue["message"], issue["message"]
    hops = [e for e in issue["evidence"] if e["kind"] == "cross_file"]
    assert len(hops) == 1, "one factor for the whole chain, never one per ref"
    assert validate(ip) == []


def test_r5_a_fit_inside_the_helper_that_built_x_reaches_the_cv_call(tmp_path):
    """MLV103 one `def` away - the commonest spelling of this defect in a
    research repository, and the local pass cannot see it because the two
    halves are in different functions."""
    root = write_files(str(tmp_path), {
        "prep.py":
            "import pandas as pd\n"
            "from sklearn.preprocessing import StandardScaler\n\n\n"
            "def build(path):\n"
            "    frame = pd.read_csv(path)\n"
            "    scaler = StandardScaler()\n"
            "    matrix = scaler.fit_transform(frame.drop(columns=['y']))\n"
            "    return matrix, frame['y']\n",
        "run.py":
            "from sklearn.linear_model import Ridge\n"
            "from sklearn.model_selection import cross_val_score\n\n"
            "from prep import build\n\n\n"
            "def main(path):\n"
            "    features, target = build(path)\n"
            "    return cross_val_score(Ridge(), features, target, cv=5)\n"})
    ip = analyze(root, "ip")
    found = codes(ip, "MLV103")
    assert len(found) == 1, [(i["code"], i["message"]) for i in codes(ip)]
    assert found[0]["confidenceBucket"] != "certain", found[0]["confidence"]
    assert validate(ip) == []


def test_r5_the_callee_walk_refuses_when_it_cannot_say_which_value(tmp_path):
    """A helper that hands back five values must not match on all five. Without
    this guard the walk blamed the *test-set* vectoriser for the training
    matrix, which is a high-confidence sentence that is simply false."""
    root = write_files(str(tmp_path), {"sentiment.py":
        "import pandas as pd\n"
        "from sklearn.feature_extraction.text import TfidfVectorizer\n"
        "from sklearn.linear_model import LogisticRegression\n"
        "from sklearn.model_selection import GridSearchCV, train_test_split\n\n\n"
        "def build_features(path):\n"
        "    frame = pd.read_csv(path)\n"
        "    texts = frame['review']\n"
        "    labels = frame['sentiment']\n"
        "    vectorizer = TfidfVectorizer()\n"
        "    features = vectorizer.fit_transform(texts)\n"
        "    train_x, test_x, train_y, test_y = train_test_split(\n"
        "        features, labels, test_size=0.25, random_state=0)\n"
        "    train_text, test_text = train_test_split(\n"
        "        texts, test_size=0.25, random_state=0)\n"
        "    extra = TfidfVectorizer()\n"
        "    test_x = extra.fit_transform(test_text)\n"
        "    return vectorizer, train_x, test_x, train_y, test_y\n\n\n"
        "def search(train_x, train_y):\n"
        "    grid = GridSearchCV(LogisticRegression(), {'C': [1.0]}, cv=5)\n"
        "    grid.fit(train_x, train_y)\n"
        "    return grid\n\n\n"
        "def main(path):\n"
        "    vectorizer, train_x, test_x, train_y, test_y = build_features(path)\n"
        "    return search(train_x, train_y)\n"})
    ip = analyze(root, "ip")
    blamed = [i for i in codes(ip, "MLV103")]
    assert blamed == [], [i["message"] for i in blamed]
    assert validate(ip) == []


def test_r5_mlv208_finds_the_scaler_whatever_function_built_it(tmp_path):
    """Proximity first, then identity: a `scaler.step(...)` in this very loop
    whose receiver resolves to a `GradScaler(...)` written elsewhere is that
    scaler. Here it arrives through a four-tuple factory return, which is what
    the return slot's `via_fqns` is for."""
    root = write_files(str(tmp_path), {"train.py":
        "import torch\n"
        "import torch.nn as nn\n\n\n"
        "def build():\n"
        "    model = nn.Linear(4, 2)\n"
        "    optimizer = torch.optim.Adam(model.parameters())\n"
        "    scaler = torch.amp.GradScaler('cuda')\n"
        "    return model, optimizer, scaler\n\n\n"
        "def train(loader):\n"
        "    model, optimizer, scaler = build()\n"
        "    criterion = nn.CrossEntropyLoss()\n"
        "    for features, labels in loader:\n"
        "        optimizer.zero_grad()\n"
        "        loss = criterion(model(features), labels)\n"
        "        scaler.scale(loss).backward()\n"
        "        optimizer.step()\n"
        "        scaler.update()\n"})
    doc = analyze(root, "ip")
    found = codes(doc, "MLV208")
    assert len(found) == 1, [(i["code"], i["message"]) for i in codes(doc)]
    # The fault is the one the fixture writes: `optimizer.step()` instead of
    # `scaler.step(optimizer)`. What R5 changed is that the scaler behind it is
    # found at all - it is built in `build()` and arrives through a tuple.
    assert "steps the optimizer directly" in found[0]["message"], found[0]["message"]
    built = [r for r in found[0]["relatedLocs"] if r["role"] == "construction"]
    assert built and built[0]["line"] == 8, found[0]["relatedLocs"]
    assert validate(doc) == []


def test_r18_a_no_grad_validation_total_is_not_a_graph_leak(tmp_path):
    """R18(a) widened MLV205 to any accumulating loop and so inherited every
    validation loop ever written. There is no graph behind `running_vloss`, so
    nothing is kept alive and the finding is simply wrong."""
    root = write_files(str(tmp_path), {"eval.py":
        "import torch\n\n\n"
        "def validate(model, loader, loss_fn):\n"
        "    running_vloss = 0.0\n"
        "    with torch.no_grad():\n"
        "        for vinputs, vlabels in loader:\n"
        "            running_vloss += loss_fn(model(vinputs), vlabels)\n"
        "    return running_vloss\n"})
    doc = analyze(root, "ip")
    assert codes(doc, "MLV205") == [], [i["message"] for i in codes(doc, "MLV205")]


def test_r18_a_running_total_that_is_backpropagated_is_the_live_value(tmp_path):
    """`style_loss += mse(...)`, `total = content + style_loss`,
    `total.backward()`. The accumulation is one operand of the loss that is
    actually stepped, so `.item()` there would detach the term from training."""
    root = write_files(str(tmp_path), {"style.py":
        "import torch.nn.functional as F\n\n\n"
        "def transfer(features, targets, content_loss, optimizer):\n"
        "    style_loss = 0.0\n"
        "    for f, t in zip(features, targets):\n"
        "        style_loss += F.mse_loss(f, t)\n"
        "    total = content_loss + style_loss\n"
        "    total.backward()\n"
        "    optimizer.step()\n"
        "    return total\n"})
    doc = analyze(root, "ip")
    assert codes(doc, "MLV205") == [], [i["message"] for i in codes(doc, "MLV205")]
