"""GRAPH-R3: calls through workspace-defined objects (`core/workspace_ops.py`).

`core/build_ops.py` draws a card for every call a knowledge row recognises.
Three shapes of call carry as much meaning as any of those and used to draw
nothing at all, because the thing they name is defined in the analyzed project:

* the **construction** of a workspace class (`model = SmallCNN()`), which was
  folded onto the class's definition card;
* the **invocation** of a workspace object (`logits = model(images)`,
  `loss = criterion(out, y)`), which role `FORWARD`'s transparency swallowed
  along with the layer chain it exists to keep quiet;
* the object a workspace **factory** returns (`opt = build_optimizer(...)`),
  which `ir.returns` already knew and nothing drew.

And five ways a real script hands such an object to the line that uses it -
`self.<attr>` across sibling methods, a dict, a dataclass field, a tuple, and a
rebinding wrapper (`accelerator.prepare`) - each of which lost the object
entirely.

Every assertion here is a **line number**, because the whole claim is which
line the card lands on: `tools/accuracy.py`'s graph-fidelity score anchors a
hand-drawn op on `(file, line)` exactly, and a card on the right file and the
wrong line is a miss.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_to_dict

FIXTURE = os.path.join(REPO_ROOT, "analyzer", "tests", "fixtures", "graph",
                       "workspace_objects")
SAMPLE = os.path.join(REPO_ROOT, "samples", "vision_pipeline")


@pytest.fixture(scope="module", params=["local", "ip"])
def doc(request):
    """Both dataflow modes: none of this is an interprocedural claim."""
    return analyze_to_dict(AnalyzeOptions(paths=(FIXTURE,), cache=False,
                                          dataflow=request.param))


@pytest.fixture(scope="module")
def sample():
    return analyze_to_dict(AnalyzeOptions(paths=(SAMPLE,), cache=False,
                                          dataflow="ip"))


def ops(doc, relpath, line):
    return [n for n in doc["nodes"]
            if n["level"] == "op" and n["loc"]["file"] == relpath
            and n["loc"]["line"] == line]


def one(doc, relpath, line, kind):
    found = [n for n in ops(doc, relpath, line) if n["kind"] == kind]
    assert len(found) == 1, [
        (n["kind"], n["label"], n["sublabel"]) for n in ops(doc, relpath, line)]
    return found[0]


# --------------------------------------------------------------- the sample
def test_the_sample_draws_its_model_where_it_is_built(sample):
    """`model = SmallCNN()` at train.py:20 - the hand-drawn diagram's `model`
    box, which used to be folded onto the class card in model.py."""
    node = one(sample, "train.py", 20, "model")
    assert node["stage"] == "model" and node["label"] == "model"
    assert node["sublabel"].startswith("SmallCNN")


def test_the_sample_draws_both_forward_passes(sample):
    """`logits = model(images)` in the train loop AND in `validate()`."""
    train_pass = one(sample, "train.py", 30, "predict")
    eval_pass = one(sample, "train.py", 45, "predict")
    # the lane is the lane of the unit each one runs in, not a property of the
    # call: the same expression is training in one place and evaluation in the
    # other, which is why these nodes inherit their stage rather than vote one.
    assert train_pass["stage"] == "train"
    assert eval_pass["stage"] == "eval"
    assert train_pass["produces"][0]["name"] == "logits"


def test_the_sample_draws_the_submodule_where_it_is_built(sample):
    """`self.blocks = [ConvBlock(w, w) ...]` is a `layer`, like every other
    submodule in the same `__init__` - not a `model` and not nothing."""
    node = one(sample, "model.py", 34, "layer")
    assert node["stage"] == "model"


def test_the_sample_keeps_its_fifteen_findings_and_its_edge_count(sample):
    """The cards are new; the judgements are not. The shipped sample is 59
    nodes / 51 edges / 15 findings (54 / 51 / 15 before GRAPH-R3)."""
    issues = [i for i in sample["issues"] if not i.get("suppressed")]
    assert (len(sample["nodes"]), len(sample["edges"]), len(issues)) == (59, 51, 15)
    assert validate(sample) == []


# -------------------------------------------------------- the fixture: R3
def test_a_workspace_model_is_built_and_applied(doc):
    assert one(doc, "lib.py", 56, "model")["label"] == "TinyNet()"
    assert one(doc, "run.py", 87, "model")["label"] == "net"


def test_a_loss_class_is_a_loss_because_its_forward_returns_one(doc):
    """`FocalLoss` is an `nn.Module`; what makes its card a `loss` is that its
    `forward` returns a LOSS-tagged value, never its name."""
    built = one(doc, "run.py", 63, "loss")
    assert built["stage"] == "objective" and built["label"] == "criterion"
    applied = one(doc, "run.py", 67, "loss")
    assert applied["produces"][0]["name"] == "loss"


def test_a_workspace_dataset_is_a_dataset(doc):
    assert one(doc, "lib.py", 68, "dataset")["label"] == "train_ds"
    assert one(doc, "lib.py", 69, "dataset")["label"] == "val_ds"


@pytest.mark.parametrize("line,kind", [(56, "model"), (57, "optimizer"),
                                       (58, "scheduler")])
def test_a_factory_return_keeps_its_kind_at_the_call_site(doc, line, kind):
    """`opt = build_optimizer(model)` is an `optimizer` card where it is called,
    not only inside the factory - `ir.returns` knew this and nothing drew it."""
    node = one(doc, "run.py", line, kind)
    assert node["sublabel"].endswith("()")


def test_a_sibling_method_applies_the_object_init_built(doc):
    """`self.model` / `self.criterion` are set in `__init__` and used in
    `step()`, two methods apart."""
    assert one(doc, "run.py", 46, "predict")["label"] == "logits"
    assert one(doc, "run.py", 47, "loss")["sublabel"] == "self.criterion(...)"


def test_an_object_carried_in_a_dict_keeps_its_identity(doc):
    """`ctx = {"scaler": GradScaler(...)}` then `scaler = ctx["scaler"]`: the
    GradScaler case. `scale`, `step` and `update` all resolve after the hop."""
    assert one(doc, "run.py", 68, "scaler")["label"] == "scale()"
    assert one(doc, "run.py", 69, "scaler")["label"] == "step()"
    assert one(doc, "run.py", 70, "scaler")["label"] == "update()"


def test_an_object_carried_in_a_dataclass_field_keeps_its_identity(doc):
    """`bundle = Bundle(model=model, ...)` then `bundle.model(features)`."""
    node = one(doc, "run.py", 66, "predict")
    assert node["sublabel"] == "bundle.model(...)"


def test_an_object_carried_in_a_tuple_keeps_its_identity(doc):
    """`optimizers = (build_optimizer(...), build_optimizer(...))` then
    `opt_a, opt_b = optimizers`: both names step a real optimizer."""
    assert len(ops(doc, "run.py", 78)) == 1 and ops(doc, "run.py", 78)[0]["kind"] == "optimizer"
    assert len(ops(doc, "run.py", 79)) == 1 and ops(doc, "run.py", 79)[0]["kind"] == "optimizer"


def test_a_rebinding_wrapper_hands_back_what_it_was_given(doc):
    """`net, optimizer, train_loader = accelerator.prepare(net, optimizer,
    train_loader)`: position *i* out is argument *i* in, so the forward pass
    two lines later still resolves and the loop still reads a loader."""
    assert one(doc, "run.py", 94, "predict")["sublabel"] == "net(...)"
    assert one(doc, "run.py", 96, "optimizer")["label"] == "step()"
    loops = [n for n in doc["nodes"]
             if n["kind"] in ("train_loop", "eval_loop") and n["level"] == "unit"
             and n["loc"]["file"] == "run.py" and n["loc"]["line"] == 92]
    assert len(loops) == 1, "the prepared loader is still a loader"


def test_the_fixture_is_clean_and_contract_valid(doc):
    """Nothing here is a defect: the fixture measures the diagram, not the
    rules, so a finding other than the project-level MLV601 would mean the
    cards this pass adds have started inventing judgements."""
    codes = sorted({i["code"] for i in doc["issues"] if not i.get("suppressed")})
    assert codes == ["MLV601"], codes
    assert validate(doc) == []


def test_no_card_this_pass_adds_invents_an_fqn(doc):
    """Iron law 1. A workspace class is not a canonical third-party symbol, so
    a construction / invocation / factory card carries no `fqn` at all."""
    for node in doc["nodes"]:
        if not node.get("fqn"):
            continue
        assert not node["fqn"].startswith(("lib.", "run.")), node
