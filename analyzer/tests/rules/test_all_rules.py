"""Every prototype rule against its two fixtures, plus per-rule specifics.

`test_seed_rules.py` covers the four seed codes and the generic
`_bad` fires / `_good` is silent contract for whatever pairs are on disk. This
module names all twenty explicitly - so a rule that silently vanishes from the
registry fails a test rather than quietly stopping - and then asserts the
things that are specific to each finding: the ghost nodes, the named
`relatedLocs` roles, the severity, and the variant tags.
"""

from __future__ import annotations

import pytest

from mlview.rules.registry import all_rules, rule_for
from rule_harness import (analyze_fixture, analyze_paths, assert_fires,
                          assert_silent, describe, write_workspace)

#: Every code the prototype ships (CONTRACTS section 7.3 / ISSUE_RULES section 1).
PROTOTYPE_CODES = (
    "MLV101", "MLV102", "MLV103", "MLV110", "MLV111", "MLV112",
    "MLV201", "MLV202", "MLV203", "MLV204", "MLV205",
    "MLV301", "MLV302", "MLV401", "MLV402", "MLV501",
    "MLV601", "MLV602", "MLV701", "MLV702",
)


def _enabled(code: str) -> bool:
    spec = rule_for(code)
    return spec is not None and spec.enabled


#: The three rule tiers ANA-7 / ANA-8 / ANA-9 added on top of the prototype
#: (CONTRACTS 11.26). `test_tier_rules.py` owns their per-rule assertions; this
#: tuple exists so registry drift in *either* set fails one obvious test.
TIER_CODES = (
    "MLV106", "MLV114", "MLV121",                        # ANA-9 held-out data
    "MLV207", "MLV208", "MLV209",                        # ANA-8 training mechanics
    "MLV305", "MLV306",                                  # ANA-9 held-out metrics
    "MLV502", "MLV803",                                  # ANA-8 device / deliver
    "MLV705", "MLV706", "MLV707", "MLV708", "MLV709", "MLV711",   # ANA-7
)


# ------------------------------------------------------- the registered codes
def test_the_registry_is_the_prototype_plus_the_three_tiers():
    registered = {spec.code for spec in all_rules()}
    expected = set(PROTOTYPE_CODES) | set(TIER_CODES)
    assert registered == expected, (
        "registry drift: missing %s, unexpected %s"
        % (sorted(expected - registered), sorted(registered - expected)))


def test_the_prototype_twenty_are_all_still_there():
    """The tiers are additive: nothing the prototype shipped may vanish."""
    registered = {spec.code for spec in all_rules()}
    assert set(PROTOTYPE_CODES) <= registered
    assert len(PROTOTYPE_CODES) == 20


def test_at_least_fourteen_rules_are_enabled():
    """A8: the prototype passes when >= 14 rules pass their fixtures."""
    enabled = [spec.code for spec in all_rules() if spec.enabled]
    assert len(enabled) >= 14, "only %d enabled: %s" % (len(enabled), enabled)


@pytest.mark.parametrize("code", PROTOTYPE_CODES)
def test_bad_fixture_fires(code):
    if not _enabled(code):
        pytest.skip("%s ships disabled" % code)
    assert_fires("%s_bad" % code)


@pytest.mark.parametrize("code", PROTOTYPE_CODES)
def test_good_fixture_is_silent(code):
    assert_silent("%s_good" % code, code)


# ------------------------------------------------------------ leakage family
def test_mlv102_names_the_split_the_tag_came_from():
    issue = assert_fires("MLV102_bad").of("MLV102")[0]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert "fit_site" in roles and "split_site" in roles
    assert "TEST_SPLIT" in issue["message"]
    assert issue["severity"] == "high"


def test_mlv103_does_not_stack_on_top_of_mlv101():
    """One root cause never yields two findings at the same location."""
    run = assert_fires("MLV103_bad")
    lines_103 = {i["loc"]["line"] for i in run.of("MLV103")}
    lines_101 = {i["loc"]["line"] for i in run.of("MLV101")}
    assert not (lines_103 & lines_101)


def test_mlv103_cites_the_fit_and_the_cross_validation():
    issue = assert_fires("MLV103_bad").of("MLV103")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"fit_site", "call_site"}
    assert roles["fit_site"]["line"] < roles["call_site"]["line"]
    assert "Pipeline" in issue["fixHint"]


# --------------------------------------------------------------- data family
def test_mlv110_explains_which_evidence_made_it_a_training_loader():
    issue = assert_fires("MLV110_bad").of("MLV110")[0]
    kinds = {e["kind"] for e in issue["evidence"]}
    assert "dataflow_direct" in kinds, "TRAIN_SPLIT came from the split, not a regex"
    assert issue["severity"] == "medium"


def test_mlv111_is_low_and_says_why_it_is_only_low():
    issue = assert_fires("MLV111_bad").of("MLV111")[0]
    assert issue["severity"] == "low"
    assert "order" in issue["why"].lower()


def test_mlv112_resolves_num_workers_through_a_module_constant():
    issue = assert_fires("MLV112_bad").of("MLV112")[0]
    assert "num_workers=4" in issue["message"], (
        "NUM_WORKERS = 4 has to be resolved to its literal")
    assert "__main__" in issue["fixHint"]


# ---------------------------------------------------------- train-loop family
def test_mlv202_declares_an_optimizer_step_ghost():
    run = assert_fires("MLV202_bad")
    issue = run.of("MLV202")[0]
    ghosts = [n for n in run.ghost_nodes() if issue["id"] in n["issueIds"]]
    assert len(ghosts) == 1
    ghost = ghosts[0]
    assert ghost["label"] == "optimizer.step()"
    assert ghost["sublabel"] == "missing"
    assert ghost["fqn"] == "torch.optim.Optimizer.step"
    assert issue["nodeIds"][0] == ghost["id"], "the badge is drawn on the ghost"
    parent = next(n for n in run.doc["nodes"] if n["id"] == ghost["parent"])
    assert parent["attrs"]["loopKind"] == "batch"


def test_mlv203_cites_both_sites_in_order():
    issue = assert_fires("MLV203_bad").of("MLV203")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert set(roles) == {"step_site", "backward_site"}
    assert roles["step_site"]["line"] < roles["backward_site"]["line"]


def test_mlv204_points_at_the_no_grad_block_that_opened_it():
    issue = assert_fires("MLV204_bad").of("MLV204")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert "construction" in roles
    assert roles["construction"]["line"] < issue["loc"]["line"]
    assert issue["confidence"] >= 0.9


def test_mlv205_names_the_accumulator_and_where_it_was_created():
    issue = assert_fires("MLV205_bad").of("MLV205")[0]
    assert "running_loss" in issue["message"]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert "construction" in roles
    assert roles["construction"]["line"] < issue["loc"]["line"]


# --------------------------------------------------------------- eval family
def test_mlv301_declares_a_model_eval_ghost_on_the_eval_loop():
    run = assert_fires("MLV301_bad")
    issue = run.of("MLV301")[0]
    ghosts = [n for n in run.ghost_nodes() if issue["id"] in n["issueIds"]]
    assert len(ghosts) == 1
    ghost = ghosts[0]
    assert ghost["label"] == "model.eval()"
    assert ghost["sublabel"] == "missing"
    assert ghost["fqn"] == "torch.nn.Module.eval"
    assert ghost["qualname"].endswith(".__ghost_model_eval")
    assert issue["nodeIds"][0] == ghost["id"]
    assert issue["stage"] == "eval"


def test_mlv301_is_high_only_because_the_model_has_dropout_and_batchnorm():
    issue = assert_fires("MLV301_bad").of("MLV301")[0]
    assert issue["severity"] == "high", "static scope, no wrapper, sensitive layers"
    detail = " ".join(e["detail"] for e in issue["evidence"] if e["kind"] == "class_base")
    assert "Dropout" in detail and "BatchNorm" in detail


def test_mlv302_is_medium_and_names_the_decorator_fix():
    issue = assert_fires("MLV302_bad").of("MLV302")[0]
    assert issue["severity"] == "medium"
    assert "no_grad" in issue["fixHint"]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"eval_loop", "call_site"} <= roles


# --------------------------------------------------------------- loss family
def test_mlv402_reports_the_variant_as_a_tag():
    issue = assert_fires("MLV402_bad").of("MLV402")[0]
    assert "double_sigmoid" in issue["tags"]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert "final_layer" in roles and "definition" in roles


def test_mlv402_finds_the_sigmoid_at_the_tail_of_an_nn_sequential():
    issue = assert_fires("MLV402_bad").of("MLV402")[0]
    final = next(r for r in issue["relatedLocs"] if r["role"] == "final_layer")
    assert final["line"] == 15, "nn.Sequential(nn.Linear(16, 1), nn.Sigmoid())"


# ------------------------------------------------------------- device family
def test_mlv501_names_the_batch_values_that_were_left_behind():
    issue = assert_fires("MLV501_bad").of("MLV501")[0]
    assert "features" in issue["message"]
    assert "batch_not_moved" in issue["tags"]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"construction", "call_site"} <= roles


def test_mlv501_fires_once_per_placement_not_once_per_loop():
    run = assert_fires("MLV501_bad")
    assert len(run.of("MLV501")) == 1


def test_mlv501_also_catches_the_inverse_variant(tmp_path):
    """`model_not_moved`: the batches move, the network stays on the CPU."""
    source = (
        "import torch\n"
        "import torch.nn as nn\n"
        "import torch.optim as optim\n"
        "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
        "def train(dataset: TensorDataset) -> None:\n"
        "    torch.manual_seed(0)\n"
        "    device = torch.device('cuda')\n"
        "    model = nn.Sequential(nn.Linear(10, 3))\n"
        "    criterion = nn.CrossEntropyLoss()\n"
        "    optimizer = optim.SGD(model.parameters(), lr=0.01)\n"
        "    loader = DataLoader(dataset, batch_size=8, shuffle=True)\n"
        "    for features, labels in loader:\n"
        "        features = features.to(device)\n"
        "        labels = labels.to(device)\n"
        "        optimizer.zero_grad()\n"
        "        loss = criterion(model(features), labels)\n"
        "        loss.backward()\n"
        "        optimizer.step()\n")
    root = write_workspace(str(tmp_path), {"train.py": source})
    doc = analyze_paths(root)
    fired = [i for i in doc["issues"] if i["code"] == "MLV501"]
    assert len(fired) == 1, describe(doc)
    assert "model_not_moved" in fired[0]["tags"]
    assert "never moved" in fired[0]["message"]


def test_mlv205_also_catches_a_list_of_undetached_losses(tmp_path):
    source = (
        "import torch\n"
        "import torch.nn as nn\n"
        "import torch.optim as optim\n"
        "from torch.utils.data import DataLoader, TensorDataset\n\n\n"
        "def train(dataset: TensorDataset):\n"
        "    torch.manual_seed(0)\n"
        "    model = nn.Sequential(nn.Linear(10, 3))\n"
        "    criterion = nn.CrossEntropyLoss()\n"
        "    optimizer = optim.SGD(model.parameters(), lr=0.01)\n"
        "    loader = DataLoader(dataset, batch_size=8, shuffle=True)\n"
        "    losses = []\n"
        "    for features, labels in loader:\n"
        "        optimizer.zero_grad()\n"
        "        loss = criterion(model(features), labels)\n"
        "        loss.backward()\n"
        "        optimizer.step()\n"
        "        losses.append(loss)\n"
        "    return losses\n")
    root = write_workspace(str(tmp_path), {"train.py": source})
    doc = analyze_paths(root)
    fired = [i for i in doc["issues"] if i["code"] == "MLV205"]
    assert len(fired) == 1, describe(doc)
    assert "losses" in fired[0]["message"]
    assert "collects" in fired[0]["message"]


# --------------------------------------------------------- repro / model family
def test_mlv602_fires_once_per_split_site():
    run = assert_fires("MLV602_bad")
    fired = run.of("MLV602")
    assert len(fired) == 2, "one sklearn split and one torch split"
    assert {i["loc"]["file"] for i in fired} == {"MLV602_bad.py"}
    keywords = " ".join(i["message"] for i in fired)
    assert "random_state" in keywords and "generator" in keywords


def test_mlv602_drops_to_possible_when_the_workspace_is_seeded():
    """A global seed does make the split reproducible - just not locally."""
    issue = assert_fires("MLV602_bad").of("MLV602")[0]
    assert issue["confidenceBucket"] == "possible"
    assert "prefer an explicit" in issue["message"]


def test_mlv701_points_at_the_init_and_the_class_header():
    issue = assert_fires("MLV701_bad").of("MLV701")[0]
    roles = {r["role"]: r for r in issue["relatedLocs"]}
    assert "definition" in roles
    assert roles["definition"]["line"] < issue["loc"]["line"], "class line, then def"
    assert "super().__init__()" in issue["fixHint"]


def test_mlv702_counts_the_submodules_it_found():
    issue = assert_fires("MLV702_bad").of("MLV702")[0]
    assert "self.blocks" in issue["message"]
    assert "list comprehension" in issue["message"]
    roles = {r["role"] for r in issue["relatedLocs"]}
    assert {"construction", "definition"} <= roles


# ------------------------------------------------------------------ hygiene
@pytest.mark.parametrize("code", PROTOTYPE_CODES)
def test_every_issue_carries_its_docs_path(code):
    if not _enabled(code):
        pytest.skip("%s ships disabled" % code)
    for issue in analyze_fixture("%s_bad" % code).of(code):
        assert issue["docs"] == "docs/rules/%s.md" % code


@pytest.mark.parametrize("code", PROTOTYPE_CODES)
def test_every_finding_cites_concrete_evidence(code):
    """ISSUE_RULES section 5 box 7: the message names variables and lines."""
    if not _enabled(code):
        pytest.skip("%s ships disabled" % code)
    for issue in analyze_fixture("%s_bad" % code).of(code):
        assert issue["message"] != issue["title"], "the message is not a restatement"
        assert any(ch.isdigit() for ch in issue["message"]), "no line number cited"
        assert issue["evidence"], "confidence must be backed by evidence"
