"""Regression gates for the consolidate2 campaign review's analyzer findings.

One test per confirmed finding, each written so that it fails on the code as it
was rather than on an incidental detail of the fix. Every program here is the
smallest pair that isolates the defect: two files that differ in one way MLView
should not care about, where it did.

* **REV-05 / REV-PREC-02** MLV103 read a returned **call** by its callee text -
  `pca.fit_transform`, which names no value - so `return pca.fit_transform(X)`
  looked like a two-value return to §19.1 A5's ambiguity guard. The guard then
  demanded that the caller's binding share a name with one of them, and MLV103
  fired or stayed silent on whether the caller happened to reuse the callee's
  *parameter* name. §14.2 R13/R15 promise the bare-call spelling explicitly.
* **REV-PREC-01** `y_true, y_pred = evaluate(...)` is how a batched evaluation
  is written, and the value-typing walk read the callee's `return a, b` as a
  whole - a tuple carries no tags - so MLV305/306 went silent on the canonical
  spelling of their own defect. The tuple position the caller unpacked is on
  the `ValueRef`; it now reaches the walk. The same finding's second half: a
  collector and a tensor tail were each charged an interprocedural hop they do
  not make, so a three-hop budget was spent by `np.concatenate` and
  `.detach().cpu().numpy()` before the walk had crossed two objects.
* **REV-PREC-03** §5.3 A12' says the inferred half of `unresolved_callee` is
  recomputed every IR round. It was written once and kept, and a dict returned
  from a factory is carried into the caller at the END of a round - so
  `parts["model"]` was an opaque subscript for exactly one round and
  `parts["model"](x)` reported itself unresolved for the life of the document.
  MLV208 went silent on a GradScaler held in a parameter dict while the same
  scaler in a tuple fired.
* **REV-PREC-04** §5.3 A11 (c) / (d): a criterion reached through a holder
  field never earned the LOSS role, so `loss.backward()` back-propagated a
  value MLView could not type and the whole high-severity MLV2xx family skipped
  the training step. The MODEL half of the same holder always worked.
* **REV-PREC-05** MLV111's loader lookup read `call.var`, which a factory-built
  loader does not have, so the evaluation half of a two-factory program was
  invisible while the training half (MLV110) fired.
* **REV-PREC-07** the unresolved-callee message printed the *call's* line beside
  a phrase describing the *binding's* construct, telling the reader that a line
  holding two plain names "is a subscript".

`H1` - the Answer Card verdict's blindness to `framework_filter` - is gated in
`test_framework_filter.py`, beside the diagnostic it was missing.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, write_files
from mlview.api import AnalyzeOptions, analyze_to_dict

CORPUS = os.path.join(REPO_ROOT, "analyzer", "tests", "accuracy", "corpus")


def analyze(root, dataflow="ip"):
    return analyze_to_dict(AnalyzeOptions(paths=(root,), dataflow=dataflow))


def codes(doc, code=None):
    return [i for i in doc["issues"]
            if (code is None or i["code"] == code) and not i.get("suppressed")]


def lines(doc, code):
    return sorted(i["loc"]["line"] for i in codes(doc, code))


def notes(doc, kind):
    return [d for d in doc["diagnostics"] if d.get("kind") == kind]


def one_file(tmp_path, name, source, dataflow="ip"):
    root = write_files(str(tmp_path / name), {"m.py": source})
    return analyze(root, dataflow)


# ---------------------------------------------------------------------------
# REV-05 / REV-PREC-02 - MLV103 through a helper
# ---------------------------------------------------------------------------
_PREPARE = (
    "from sklearn.ensemble import RandomForestClassifier\n"
    "from sklearn.feature_selection import SelectKBest\n"
    "from sklearn.model_selection import cross_val_score\n\n\n"
    "def prepare(X):\n"
    "    selector = SelectKBest(k=5)\n"
    "%s"
    "\n\n"
    "def main(%s, y):\n"
    "    %s = prepare(%s)\n"
    "    clf = RandomForestClassifier(random_state=0)\n"
    "    print(cross_val_score(clf, %s, y, cv=5).mean())\n"
)


def _prepare_program(body, caller_in, caller_out):
    return _PREPARE % (body, caller_in, caller_out, caller_in, caller_out)


BARE_CALL = "    return selector.fit_transform(X)\n"
BOUND_NAME = "    out = selector.fit_transform(X)\n    return out\n"


def test_a_bare_returned_call_fires_mlv103(tmp_path):
    """§14.2 R15's own promise: the three forms are equivalent."""
    doc = one_file(tmp_path, "bare", _prepare_program(BARE_CALL, "X0", "X_ready"))
    assert lines(doc, "MLV103") == [14], codes(doc)


def test_the_two_spellings_of_one_program_agree(tmp_path):
    """`return f(X)` and `out = f(X); return out` are one program."""
    bare = one_file(tmp_path, "a", _prepare_program(BARE_CALL, "X0", "X_ready"))
    bound = one_file(tmp_path, "b", _prepare_program(BOUND_NAME, "X0", "X_ready"))
    assert codes(bare, "MLV103") and codes(bound, "MLV103")


def test_mlv103_does_not_depend_on_the_callers_variable_name(tmp_path):
    """The measured REV-PREC-02 case. `_returned_names` recorded the callee's
    *argument* as a returned name, and the ambiguity guard then accepted the
    finding only when the caller's binding happened to share that name - so
    renaming a local in the caller decided whether a leak was reported."""
    unrelated = one_file(tmp_path, "u", _prepare_program(BARE_CALL, "X0", "X_ready"))
    shadowing = one_file(tmp_path, "s", _prepare_program(BARE_CALL, "X0", "X"))
    assert bool(codes(unrelated, "MLV103")) == bool(codes(shadowing, "MLV103"))
    assert codes(unrelated, "MLV103"), "the leak is real in both spellings"


def test_a_multi_argument_fit_transform_still_fires(tmp_path):
    """`return scaler.fit_transform(X, y)` names two operands and one value."""
    doc = one_file(tmp_path, "two",
                   _prepare_program("    return selector.fit_transform(X, y)\n",
                                    "X0", "X_ready"))
    assert codes(doc, "MLV103"), codes(doc)


def test_the_precision_guard_the_widening_must_not_undo():
    """§19.1 A5 exists because the walk blamed the **test-set** vectoriser at
    line 34 for the training matrix built at line 29. `build_features` really
    does hand back a five-tuple, so the guard still applies there and MLV103
    stays silent - the widening above narrows the guard to that shape, it does
    not remove it."""
    doc = analyze(os.path.join(CORPUS, "nlp_sklearn_text_leaky"))
    assert not codes(doc, "MLV103"), codes(doc, "MLV103")
    assert lines(doc, "MLV101") == [29] and lines(doc, "MLV102") == [34]


# ---------------------------------------------------------------------------
# REV-PREC-01 - value tags through a tuple-position return
# ---------------------------------------------------------------------------
_EVAL = (
    "import numpy as np\n"
    "import torch\n"
    "import torch.nn as nn\n"
    "from sklearn.metrics import accuracy_score\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.fc = nn.Linear(4, 3)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(x)\n\n\n"
    "def collect(model, loader):\n"
    "    preds = []\n"
    "    for xb, yb in loader:\n"
    "        preds.append(model(xb).detach().cpu().numpy())\n"
    "%s"
    "\n\n"
    "def main(loader, y_true):\n"
    "    model = Net()\n"
    "    %s = collect(model, loader)\n"
    "    accuracy_score(y_true, y_pred)\n"
)

SCALAR_RETURN = "    return np.concatenate(preds)\n"
TUPLE_RETURN = "    return np.concatenate(preds), 0\n"


def test_logits_survive_a_scalar_return(tmp_path):
    """The shape that already worked; the control for the pair below."""
    doc = one_file(tmp_path, "scalar", _EVAL % (SCALAR_RETURN, "y_pred"))
    assert codes(doc, "MLV305"), codes(doc)


def test_logits_survive_a_tuple_position_return(tmp_path):
    """REV-PREC-01. Byte-identical but for the tuple, and it used to go silent
    with a coverage note in place of the finding."""
    doc = one_file(tmp_path, "tuple", _EVAL % (TUPLE_RETURN, "y_pred, _"))
    assert codes(doc, "MLV305"), codes(doc)


def test_the_tag_is_read_at_the_position_the_caller_unpacked(tmp_path):
    """Not "some position": the second element is the scored one here, and the
    first is an integer that carries no tag at all."""
    source = _EVAL % ("    return 0, np.concatenate(preds)\n", "_, y_pred")
    doc = one_file(tmp_path, "pos", source)
    assert codes(doc, "MLV305"), codes(doc)


def test_both_dataflow_modes_agree_on_the_tuple_return(tmp_path):
    """§5.3 A13 is a rule about cross-object claims, not about a flag."""
    root = write_files(str(tmp_path / "modes"),
                       {"m.py": _EVAL % (TUPLE_RETURN, "y_pred, _")})
    assert codes(analyze(root, "ip"), "MLV305")
    assert codes(analyze(root, "local"), "MLV305")


def test_a_collector_and_a_tensor_tail_cost_no_object_hop(tmp_path):
    """The second half of REV-PREC-01. Two objects are crossed here - the
    per-batch helper and the evaluation helper - and the budget is three; the
    walk still gave up, because `np.concatenate` and `.detach().cpu().numpy()`
    had each been charged a hop the module's own doctrine says they do not
    make."""
    source = (
        "import numpy as np\n"
        "import torch\n"
        "import torch.nn as nn\n"
        "from sklearn.metrics import accuracy_score\n\n\n"
        "class Net(nn.Module):\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.fc = nn.Linear(4, 3)\n\n"
        "    def forward(self, x):\n"
        "        return self.fc(x)\n\n\n"
        "def batch_scores(model, batch):\n"
        "    logits = model(batch)\n"
        "    return logits.detach().cpu().numpy()\n\n\n"
        "def collect(model, loader):\n"
        "    predicted = []\n"
        "    truth = []\n"
        "    for xb, yb in loader:\n"
        "        predicted.append(batch_scores(model, xb))\n"
        "        truth.append(yb.detach().cpu().numpy())\n"
        "    return np.concatenate(truth), np.concatenate(predicted)\n\n\n"
        "def main(loader):\n"
        "    model = Net()\n"
        "    y_true, y_pred = collect(model, loader)\n"
        "    accuracy_score(y_true, y_pred)\n"
    )
    doc = one_file(tmp_path, "twohop", source)
    assert codes(doc, "MLV305"), codes(doc)


# ---------------------------------------------------------------------------
# REV-PREC-03 - a dict literal carried out of a factory
# ---------------------------------------------------------------------------
_AMP_BODY = (
    "def main(loader):\n"
    "    torch.manual_seed(0)\n"
    "%s"
    "    m = parts[\"model\"]\n"
    "    opt = parts[\"optimizer\"]\n"
    "    scaler = parts[\"scaler\"]\n"
    "    crit = parts[\"criterion\"]\n"
    "    for xb, yb in loader:\n"
    "        opt.zero_grad()\n"
    "        loss = crit(m(xb), yb)\n"
    "        scaler.scale(loss).backward()\n"
    "        opt.step()\n"
)
_DICT_LITERAL = (
    "    parts = {\"model\": nn.Linear(4, 3),\n"
    "             \"optimizer\": torch.optim.SGD(nn.Linear(4, 3).parameters(), lr=0.1),\n"
    "             \"scaler\": torch.cuda.amp.GradScaler(),\n"
    "             \"criterion\": nn.CrossEntropyLoss()}\n"
)
_FACTORY = (
    "def build():\n"
    "    return {\"model\": nn.Linear(4, 3),\n"
    "            \"optimizer\": torch.optim.SGD(nn.Linear(4, 3).parameters(), lr=0.1),\n"
    "            \"scaler\": torch.cuda.amp.GradScaler(),\n"
    "            \"criterion\": nn.CrossEntropyLoss()}\n\n\n"
)
HEAD = "import torch\nimport torch.nn as nn\n\n\n"


def test_a_dict_written_in_the_callers_scope_fires_mlv208(tmp_path):
    """The control: this always worked."""
    doc = one_file(tmp_path, "inline", HEAD + _AMP_BODY % _DICT_LITERAL)
    assert codes(doc, "MLV208"), codes(doc)


def test_the_same_dict_returned_from_a_factory_fires_mlv208(tmp_path):
    """REV-PREC-03. The same twelve lines with the literal moved into a
    factory; MLV208 used to go silent and leave an unresolved-callee note."""
    doc = one_file(tmp_path, "factory",
                   HEAD + _FACTORY + _AMP_BODY % "    parts = build()\n")
    assert codes(doc, "MLV208"), codes(doc)


def test_a_resolved_subscript_does_not_report_itself_as_a_gap(tmp_path):
    """§5.3 A12': the inferred half of `unresolved_callee` is recomputed on
    every IR round, so a binding round 1 could not follow and round 2 could is
    not still reported as unresolved."""
    doc = one_file(tmp_path, "note",
                   HEAD + _FACTORY + _AMP_BODY % "    parts = build()\n")
    assert not notes(doc, "unresolved_callee"), notes(doc, "unresolved_callee")


def test_the_syntactic_half_of_the_note_is_preserved(tmp_path):
    """The other direction, and the reason the two halves are distinguished at
    all: a subscript written **at the call site** resolves to nothing and must
    still be confessed."""
    source = (
        "def main(registry, xb):\n"
        "    return registry[\"model\"](xb)\n"
    )
    doc = one_file(tmp_path, "syntactic", source)
    rows = notes(doc, "unresolved_callee")
    assert rows and "a subscript" in rows[0]["message"], rows


# ---------------------------------------------------------------------------
# REV-PREC-04 - the LOSS role through a holder field
# ---------------------------------------------------------------------------
_STEP = (
    "\n\n"
    "def main(loader):\n"
    "    torch.manual_seed(0)\n"
    "%s"
    "    opt = torch.optim.SGD(%s.parameters(), lr=0.1)\n"
    "    for xb, yb in loader:\n"
    "        opt.zero_grad()\n"
    "        loss = %s(%s(xb), yb)\n"
    "        loss.backward()\n"
)

DATACLASS = (
    "from dataclasses import dataclass\n"
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "@dataclass\n"
    "class State:\n"
    "    model: nn.Module\n"
    "    criterion: nn.Module"
    + _STEP % ("    state = State(model=nn.Linear(4, 3),\n"
               "                  criterion=nn.CrossEntropyLoss())\n",
               "state.model", "state.criterion", "state.model")
)

EXPLICIT_INIT = (
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "class State:\n"
    "    def __init__(self, model, criterion):\n"
    "        self.model = model\n"
    "        self.criterion = criterion"
    + _STEP % ("    state = State(model=nn.Linear(4, 3),\n"
               "                  criterion=nn.CrossEntropyLoss())\n",
               "state.model", "state.criterion", "state.model")
)

CONSTRUCTOR_PARAM = (
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "class State:\n"
    "    def __init__(self, model, criterion):\n"
    "        self.model = model\n"
    "        self.criterion = criterion"
    + _STEP % ("    crit = nn.CrossEntropyLoss()\n"
               "    state = State(model=nn.Linear(4, 3), criterion=crit)\n",
               "state.model", "state.criterion", "state.model")
)

PLAIN_LOCALS = (
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "def _unused():\n"
    "    return None"
    + _STEP % ("    model = nn.Linear(4, 3)\n"
               "    criterion = nn.CrossEntropyLoss()\n",
               "model", "criterion", "model")
)


@pytest.mark.parametrize("name,source", [
    ("plain_locals", PLAIN_LOCALS),
    ("dataclass", DATACLASS),
    ("explicit_init", EXPLICIT_INIT),
    ("constructor_param", CONSTRUCTOR_PARAM),
])
def test_a_missing_optimizer_step_is_found_however_the_criterion_is_held(
        tmp_path, name, source):
    """One defect, four spellings of where the criterion lives. Only the first
    was found; the other three reported a coverage note saying `loss.backward()`
    back-propagated a value MLView could not type."""
    doc = one_file(tmp_path, name, source)
    assert codes(doc, "MLV202"), (name, codes(doc), doc["diagnostics"])


def test_the_holder_field_carries_the_symbol_not_only_the_tag(tmp_path):
    """The root cause. A tag says what a value is *for*; the FQN says what it
    **is**, and `criterion(...)` only resolves to `CrossEntropyLoss.__call__` -
    and only then yields a LOSS-tagged value - with the FQN."""
    from mlview.api import analyze_full
    root = write_files(str(tmp_path / "symbol"), {"m.py": EXPLICIT_INIT})
    workspace = analyze_full(AnalyzeOptions(paths=(root,), dataflow="ip")).workspace
    module = workspace.modules["m.py"]
    call = next(c for c in module.calls if c.receiver_name == "state.criterion")
    assert "torch.nn.CrossEntropyLoss.__call__" in call.canonical_fqns, \
        call.canonical_fqns


# ---------------------------------------------------------------------------
# REV-PREC-05 - MLV111 through a factory
# ---------------------------------------------------------------------------
LOADER_HEAD = (
    "import torch\n"
    "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
    "def _data():\n"
    "    return TensorDataset(torch.randn(8, 2), torch.randint(0, 2, (8,)))\n\n\n"
)


def test_an_eval_loader_written_in_place_fires_mlv111(tmp_path):
    """The control."""
    source = LOADER_HEAD + (
        "def main():\n"
        "    eval_loader = DataLoader(_data(), batch_size=4, shuffle=True)\n"
        "    for xb, yb in eval_loader:\n"
        "        print(xb, yb)\n"
    )
    assert codes(one_file(tmp_path, "inline_loader", source), "MLV111")


def test_an_eval_loader_returned_from_a_factory_fires_mlv111(tmp_path):
    """REV-PREC-05. `call.var` is None for a factory-built loader, and the name
    that says it is an evaluation loader is one hop away at the caller - the
    hop MLV110 already makes for its own evidence."""
    source = LOADER_HEAD + (
        "def make_eval_loader(bs):\n"
        "    return DataLoader(_data(), batch_size=bs, shuffle=True)\n\n\n"
        "def main():\n"
        "    eval_loader = make_eval_loader(4)\n"
        "    for xb, yb in eval_loader:\n"
        "        print(xb, yb)\n"
    )
    assert codes(one_file(tmp_path, "factory_loader", source), "MLV111")


def test_a_factory_that_also_builds_the_training_loader_stays_silent(tmp_path):
    """All the names, not any of them. A loader that is also the training
    loader is *correct* to shuffle, so one caller naming it `test_loader` must
    not turn a shared factory into a finding."""
    source = LOADER_HEAD + (
        "def make_loader(bs):\n"
        "    return DataLoader(_data(), batch_size=bs, shuffle=True)\n\n\n"
        "def main():\n"
        "    train_loader = make_loader(4)\n"
        "    test_loader = make_loader(4)\n"
        "    for xb, yb in train_loader:\n"
        "        print(xb, yb)\n"
        "    for xb, yb in test_loader:\n"
        "        print(xb, yb)\n"
    )
    assert not codes(one_file(tmp_path, "shared_loader", source), "MLV111")


# ---------------------------------------------------------------------------
# REV-PREC-07 - the unresolved-callee message cites the right line
# ---------------------------------------------------------------------------
def test_the_note_cites_the_binding_not_the_call(tmp_path):
    """The construct describes the callee's binding; the message used to print
    the call's line beside it, telling the reader that a line holding two plain
    names "is a subscript"."""
    source = (
        "import json\n\n\n"
        "def main(path, xb):\n"
        "    with open(path) as fh:\n"
        "        registry = json.load(fh)\n"
        "    model = registry[\"model\"]\n"
        "    return model(xb)\n"
    )
    doc = one_file(tmp_path, "cite", source)
    rows = notes(doc, "unresolved_callee")
    assert rows, doc["diagnostics"]
    message = rows[0]["message"]
    assert "was bound from a subscript at line 7" in message, message
    assert "at line 8 is a subscript" not in message, message
