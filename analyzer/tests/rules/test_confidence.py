"""The confidence model, factor by factor (ISSUE_RULES iron laws 2, 3, 4, 6).

    confidence = clamp(base_prior x PI(evidence weights)
                       x 0.7  when the enclosing scope is dynamic
                       x 0.4  when an absence rule sees a framework wrapper,
                       0.05, 0.99)

Buckets: `certain >= 0.9`, `likely >= 0.7`, `possible >= 0.5`, else
`speculative`. The absence-rule severity cap turns `high` into `medium` unless
the scope resolved statically **and** no wrapper was detected.

Each factor is exercised in isolation here, then together on real code.
"""

from __future__ import annotations

import pytest

from mlview.core.graph import bucket_for, clamp_confidence
from mlview.rules.confidence import (DYNAMIC_FACTOR, WRAPPER_FACTOR, cap_severity,
                                     compute_confidence, normalize_evidence)
from rule_harness import analyze_paths, write_workspace

BASE = 0.9


# ------------------------------------------------------------ factors alone
def test_no_evidence_leaves_the_prior_alone():
    assert compute_confidence(BASE, []) == pytest.approx(0.9)


def test_evidence_weights_multiply():
    assert compute_confidence(1.0, [("name_regex", "", 0.8)]) == pytest.approx(0.8)
    assert compute_confidence(1.0, [("name_regex", "", 0.8),
                                    ("name_regex", "", 0.5)]) == pytest.approx(0.4)


def test_a_weight_above_one_cannot_promote_a_finding():
    """Evidence reinforces; it never invents confidence the prior did not have."""
    assert compute_confidence(0.5, [("fqn_resolved", "", 5.0)]) == pytest.approx(0.5)


def test_a_zero_weight_is_floored_rather_than_annihilating():
    assert compute_confidence(1.0, [("name_regex", "", 0.0)]) == pytest.approx(0.05)


def test_the_dynamic_scope_factor():
    plain = compute_confidence(BASE, [])
    dynamic = compute_confidence(BASE, [], dynamic=True)
    assert dynamic == pytest.approx(plain * DYNAMIC_FACTOR)


def test_the_wrapper_gate_factor():
    plain = compute_confidence(BASE, [])
    gated = compute_confidence(BASE, [], wrapper_gate=True)
    assert gated == pytest.approx(plain * WRAPPER_FACTOR)
    assert bucket_for(gated) == "speculative", "off the Problems panel"


def test_the_factors_compose():
    got = compute_confidence(BASE, [("name_regex", "", 0.8)], dynamic=True,
                             wrapper_gate=True)
    assert got == pytest.approx(clamp_confidence(BASE * 0.8 * 0.7 * 0.4))


def test_confidence_is_clamped_and_rounded():
    assert compute_confidence(1.0, []) == 0.99
    assert compute_confidence(0.0001, []) == 0.05
    assert compute_confidence(0.123456, []) == 0.123


def test_evidence_accepts_tuples_objects_and_dicts():
    tuples = normalize_evidence([("fqn_resolved", "a", 1.0)])
    dicts = normalize_evidence([{"kind": "fqn_resolved", "detail": "a", "weight": 1.0}])
    assert tuples == dicts
    assert normalize_evidence(tuples) == tuples


# ------------------------------------------------------------ bucket edges
@pytest.mark.parametrize("value,bucket", [
    (0.99, "certain"), (0.9, "certain"),
    (0.8999, "likely"), (0.7, "likely"),
    (0.6999, "possible"), (0.5, "possible"),
    (0.4999, "speculative"), (0.05, "speculative"),
])
def test_bucket_boundaries_are_inclusive_from_below(value, bucket):
    assert bucket_for(value) == bucket


def test_the_problems_panel_threshold_sits_inside_possible():
    """Only >= 0.6 reaches the editor; the rest stay behind showSpeculative."""
    assert bucket_for(0.6) == "possible"
    assert bucket_for(0.59) == "possible"


# --------------------------------------------------------- the severity cap
@pytest.mark.parametrize("static,wrapper,expected", [
    (True, False, "high"),
    (False, False, "medium"),
    (True, True, "medium"),
    (False, True, "medium"),
])
def test_absence_rules_only_reach_high_when_fully_resolved(static, wrapper, expected):
    assert cap_severity("high", True, static, wrapper) == expected


def test_the_cap_never_touches_a_non_absence_rule():
    for static in (True, False):
        for wrapper in (True, False):
            assert cap_severity("high", False, static, wrapper) == "high"


def test_the_cap_never_promotes():
    assert cap_severity("medium", True, True, False) == "medium"
    assert cap_severity("low", True, True, False) == "low"


# ------------------------------------------------- the factors on real code
BAD = '''"""No zero_grad in the batch loop."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset) -> None:
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(10, 3))
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)
    for features, labels in train_loader:
        loss = criterion(model(features), labels)
        loss.backward()
        optimizer.step()
'''

DYNAMIC = BAD.replace("    torch.manual_seed(0)\n",
                      "    torch.manual_seed(0)\n"
                      "    build = getattr(nn, layer_name)\n")
WRAPPED = BAD.replace("import torch\n",
                      "import pytorch_lightning as pl\nimport torch\n").replace(
    "def train(dataset: TensorDataset) -> None:\n",
    "def train(dataset: TensorDataset) -> None:\n"
    "    trainer = pl.Trainer(max_epochs=1)\n")


def _issue(tmp_path, source, code="MLV201", name="train.py"):
    root = write_workspace(str(tmp_path), {name: source})
    doc = analyze_paths(root)
    found = [i for i in doc["issues"] if i["code"] == code]
    assert found, "%s did not fire: %s" % (code, [i["code"] for i in doc["issues"]])
    return found[0], doc


def test_the_baseline_is_certain_and_high(tmp_path):
    issue, _doc = _issue(tmp_path, BAD)
    assert issue["severity"] == "high"
    assert issue["confidenceBucket"] == "certain"
    assert issue["confidence"] >= 0.9


def test_a_dynamic_scope_derates_once_and_caps_the_severity(tmp_path):
    baseline, _ = _issue(tmp_path / "a", BAD)
    dynamic, doc = _issue(tmp_path / "b", DYNAMIC)
    assert dynamic["confidence"] < baseline["confidence"]
    assert dynamic["confidence"] == pytest.approx(
        clamp_confidence(baseline["confidence"] * DYNAMIC_FACTOR), abs=0.02), (
        "the dynamic factor must be applied exactly once")
    assert dynamic["severity"] == "medium", "the absence cap bites on a dynamic scope"
    assert any(d["kind"] == "dynamic_scope" for d in doc["diagnostics"])


def test_a_framework_wrapper_gates_the_absence_rule(tmp_path):
    baseline, _ = _issue(tmp_path / "a", BAD)
    gated, doc = _issue(tmp_path / "b", WRAPPED)
    assert gated["confidence"] == pytest.approx(
        clamp_confidence(baseline["confidence"] * WRAPPER_FACTOR), abs=0.02)
    assert gated["confidenceBucket"] == "speculative"
    assert gated["severity"] == "medium"
    chips = [d for d in doc["diagnostics"] if d["kind"] == "framework_suppressed"]
    assert chips, doc["diagnostics"]
    assert "MLV201" in chips[0]["codes"]
    assert "Lightning" in chips[0]["message"]


def test_a_regex_only_match_is_derated(tmp_path):
    """Iron law 2: a name regex reinforces, it never creates - weight 0.8."""
    source = '''"""A loader that is only a training loader by name."""
import torch
from torch.utils.data import DataLoader, TensorDataset


def build(dataset: TensorDataset):
    torch.manual_seed(0)
    train_loader = DataLoader(dataset, batch_size=32)
    return train_loader
'''
    issue, _doc = _issue(tmp_path, source, code="MLV110")
    weights = {e["kind"]: e["weight"] for e in issue["evidence"]}
    assert weights.get("name_regex") == 0.8
    assert issue["confidence"] < 0.85


def test_every_emitted_confidence_matches_its_bucket(tmp_path):
    _issue_, doc = _issue(tmp_path, BAD)
    for issue in doc["issues"]:
        assert issue["confidenceBucket"] == bucket_for(issue["confidence"])
    for node in doc["nodes"]:
        assert node["confidenceBucket"] == bucket_for(node["confidence"])


def test_min_confidence_filters_without_leaving_orphan_ghosts(tmp_path):
    root = write_workspace(str(tmp_path), {"train.py": WRAPPED})
    doc = analyze_paths(root, min_confidence=0.6)
    assert not [i for i in doc["issues"] if i["code"] == "MLV201"]
    assert not [n for n in doc["nodes"] if n["ghost"]], (
        "invariant 1.1.8: a ghost whose issue was filtered out is dropped")
