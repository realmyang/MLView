"""Determinism: same input bytes -> same output bytes (R0.4)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from core_support import write_files
from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.emit.json_out import dumps

SRC = {
    "a.py": ("import torch\nimport torch.nn as nn\nimport torch.optim as optim\n"
             "from torch.utils.data import DataLoader\n\n\n"
             "def train(ds):\n"
             "    torch.manual_seed(1)\n"
             "    model = nn.Linear(4, 2)\n"
             "    crit = nn.CrossEntropyLoss()\n"
             "    opt = optim.Adam(model.parameters())\n"
             "    loader = DataLoader(ds, batch_size=4, shuffle=True)\n"
             "    for x, y in loader:\n"
             "        opt.zero_grad()\n"
             "        loss = crit(model(x), y)\n"
             "        loss.backward()\n"
             "        opt.step()\n"),
    "b.py": ("from sklearn.preprocessing import StandardScaler\n"
             "from sklearn.model_selection import train_test_split\n"
             "import numpy as np\n\n\n"
             "def run(X, y):\n"
             "    np.random.seed(0)\n"
             "    scaler = StandardScaler()\n"
             "    Xs = scaler.fit_transform(X)\n"
             "    return train_test_split(Xs, y, random_state=0)\n"),
}

VOLATILE = ("generatedAt", "durationMs")


def strip_volatile(doc):
    doc = json.loads(json.dumps(doc))
    doc["generator"].pop("generatedAt", None)
    doc["stats"].pop("durationMs", None)
    return doc


def test_two_in_process_runs_are_byte_identical(make_workspace):
    root = make_workspace(SRC)
    first = dumps(strip_volatile(analyze_to_dict(AnalyzeOptions(paths=(root,)))))
    second = dumps(strip_volatile(analyze_to_dict(AnalyzeOptions(paths=(root,)))))
    assert first == second


def test_subprocess_with_a_different_hash_seed_matches(make_workspace):
    root = make_workspace(SRC)
    in_process = strip_volatile(analyze_to_dict(AnalyzeOptions(paths=(root,))))

    env = dict(os.environ)
    env.update({"PYTHONHASHSEED": "12345", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "mlview", "analyze", root, "--json", "-"],
        capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    from_subprocess = strip_volatile(json.loads(proc.stdout.decode("utf-8")))
    assert dumps(from_subprocess) == dumps(in_process)


def test_node_and_edge_order_is_canonical(make_workspace):
    root = make_workspace(SRC)
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    stage_order = {s["id"]: s["order"] for s in doc["stages"]}
    keys = [(stage_order[n["stage"]], n["loc"]["file"], n["loc"]["line"], n["loc"]["col"])
            for n in doc["nodes"]]
    assert keys == sorted(keys)
    edge_keys = [(e["source"], e["kind"], e["target"]) for e in doc["edges"]]
    assert edge_keys == sorted(edge_keys)
    sev = {"high": 0, "medium": 1, "low": 2}
    issue_keys = [(sev[i["severity"]], i["loc"]["file"], i["loc"]["line"], i["code"])
                  for i in doc["issues"]]
    assert issue_keys == sorted(issue_keys)


def test_only_two_fields_are_volatile(make_workspace):
    root = make_workspace(SRC)
    first = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    second = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert strip_volatile(first) == strip_volatile(second)
    assert set(VOLATILE) == {"generatedAt", "durationMs"}


# ------------------------------------------------ scoped runs (CONTRACTS 11.2)
SCOPE = "concern:optimization"


def test_two_scoped_projections_are_byte_identical(make_workspace):
    """F2-A9. `project()` is pure: no clock, no randomness, no set-iteration
    order reaching the output."""
    root = make_workspace(SRC)
    options = AnalyzeOptions(paths=(root,), scope=SCOPE, depth=1)
    first = dumps(strip_volatile(analyze_to_dict(options)))
    second = dumps(strip_volatile(analyze_to_dict(options)))
    assert first == second
    assert '"view"' in first


def test_a_scoped_subprocess_with_a_different_hash_seed_matches(make_workspace):
    root = make_workspace(SRC)
    in_process = strip_volatile(analyze_to_dict(
        AnalyzeOptions(paths=(root,), scope=SCOPE, depth=1)))

    env = dict(os.environ)
    env.update({"PYTHONHASHSEED": "424242", "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8"})
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "mlview", "analyze", root,
         "--scope", SCOPE, "--depth", "1", "--json", "-"],
        capture_output=True, env=env)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    from_subprocess = strip_volatile(json.loads(proc.stdout.decode("utf-8")))
    assert dumps(from_subprocess) == dumps(in_process)
    assert from_subprocess["view"]["scope"] == SCOPE


def test_an_unscoped_run_is_unchanged_by_the_feature(make_workspace):
    """F2-A13: no `--scope` -> no `view` key, and the same bytes as before."""
    root = make_workspace(SRC)
    plain = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    with_all = analyze_to_dict(AnalyzeOptions(paths=(root,), scope="all"))
    assert "view" not in plain
    assert dumps(strip_volatile(plain)) == dumps(strip_volatile(with_all))
