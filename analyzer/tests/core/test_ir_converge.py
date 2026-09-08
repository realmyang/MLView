"""PERF-02: the IR rounds run to a fixed point, not to a literal `range(4)`.

`build_ir` used to run exactly four rounds with a comment conceding *"four
rounds reach the fixed point on every fixture"*. It was a guess in both
directions, and both halves are measurable on this tree:

* `samples/vision_pipeline` reaches its fixed point after **3** rounds, so the
  fourth was pure waste - and on 200 files that waste is seconds;
* `analyzer/tests/clean` needs **5**, so the shipped clean corpus was analyzed
  one round short. The visible symptom is one `ValueTag` (`PREDS` on
  `vanilla_torch.evaluate.preds`) that four rounds never assigned. Nodes,
  edges, issues and diagnostics are unchanged - 108 / 106 / 0 / 0 either way.
"""

from __future__ import annotations

import os

import pytest

from core_support import REPO_ROOT

from mlview.api import AnalyzeOptions, analyze_full
from mlview.ir import converge

SAMPLES = os.path.join(REPO_ROOT, "samples")
CLEAN = os.path.join(REPO_ROOT, "analyzer", "tests", "clean")


def _workspace(path, **kwargs):
    return analyze_full(AnalyzeOptions(paths=(path,), max_files=4000,
                                       max_nodes=4000, **kwargs))


def test_vision_pipeline_stops_early():
    """The demo corpus converges before the old fixed count."""
    result = _workspace(os.path.join(SAMPLES, "vision_pipeline"))
    assert result.workspace.ir_converged is True
    # 3 rounds of change plus the round that proves nothing moved
    assert result.workspace.ir_rounds == 4


def test_clean_corpus_needs_a_fifth_round():
    """The chain four rounds could not close now closes."""
    result = _workspace(CLEAN)
    assert result.workspace.ir_converged is True
    assert result.workspace.ir_rounds == 6, (
        "analyzer/tests/clean took %d rounds; the shipped corpus needs 5 rounds "
        "of change plus one to confirm" % result.workspace.ir_rounds)
    doc = result.graph.to_dict()
    preds = [n for n in doc["nodes"] if n["qualname"] == "vanilla_torch.evaluate.preds"]
    assert preds, "the fixture node this round resolves is gone"
    assert "PREDS" in preds[0]["produces"][0]["tags"]
    # the extra round buys information, never a finding
    assert doc["issues"] == []


#: A 5-hop re-export chain. `_bind_imported_values` carries a module-level
#: value exactly one hop per round, and the modules are bound in sorted order,
#: so `a_train` sees `train_loader` only on the fifth round - one more than the
#: old `range(4)` ever ran. Verified against the pre-PERF analyzer: it leaves
#: `a_train`'s module scope completely unbound.
_HOP_CHAIN = {
    "e_source.py": "import torch\n"
                   "from torch.utils.data import DataLoader, TensorDataset\n\n"
                   "train_loader = DataLoader(TensorDataset(torch.zeros(4, 2)), "
                   "batch_size=8, shuffle=True)\n",
    "d_hop.py": "from e_source import train_loader\n",
    "c_hop.py": "from d_hop import train_loader\n",
    "b_hop.py": "from c_hop import train_loader\n",
    "a_train.py": "import torch.nn as nn\nfrom b_hop import train_loader\n\n\n"
                  "def main():\n"
                  "    model = nn.Linear(2, 2)\n"
                  "    for batch in train_loader:\n"
                  "        out = model(batch)\n"
                  "    return out\n",
}


def test_five_hop_chain_four_rounds_could_not_close(make_workspace):
    """The chain that needs a fifth round now resolves, and says so."""
    root = make_workspace(_HOP_CHAIN)
    result = _workspace(root)
    assert result.workspace.ir_converged is True
    assert result.workspace.ir_rounds == 6, (
        "the 5-hop chain closed in %d rounds; the fixture is no longer testing "
        "what it claims" % result.workspace.ir_rounds)
    scope = result.workspace.modules["a_train.py"].module_scope
    ref = scope.bindings.get("train_loader")
    assert ref is not None, "five hops of re-export still lose the value"
    assert "LOADER" in ref.tags and "TRAIN_SPLIT" in ref.tags
    assert ref.producer is not None
    assert ref.producer.fqn == "torch.utils.data.DataLoader"
    # and the loop is classified from the tag, not from the variable's name
    loops = result.workspace.modules["a_train.py"].loops
    assert loops and loops[0].kind == "batch"
    assert "iterates a LOADER-tagged value" in loops[0].evidence


def test_round_cap_is_reported_not_hidden(monkeypatch, analyze_ws):
    """Stopping on the cap is a diagnostic, never a quietly smaller graph."""
    monkeypatch.setattr(converge, "MAX_ROUNDS", 1)
    import mlview.ir.build_ir as build_ir
    monkeypatch.setattr(build_ir, "MAX_ROUNDS", 1)
    doc = analyze_ws({
        "train.py": "import torch\nimport torch.nn as nn\n\n\n"
                    "def main():\n"
                    "    model = nn.Linear(4, 2)\n"
                    "    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)\n"
                    "    optimizer.step()\n",
    })
    capped = [d for d in doc["diagnostics"]
              if d["kind"] == "truncated" and "fixed point" in d["message"]]
    assert capped, "the round cap was hit and nothing said so: %s" % doc["diagnostics"]
    assert capped[0]["count"] == 1


def test_state_digest_is_content_addressed():
    """Two runs over the same corpus must agree, or the loop never converges.

    `bind_module` clears and rebuilds every `ValueRef` each round, so a digest
    built from `id()` would change on every round forever.
    """
    first = _workspace(os.path.join(SAMPLES, "vision_pipeline_clean"))
    second = _workspace(os.path.join(SAMPLES, "vision_pipeline_clean"))
    assert converge.state_digest(first.workspace) == \
        converge.state_digest(second.workspace)
