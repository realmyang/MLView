"""ANA-10 (Python half) - config resolution, and every guard on it.

The roadmap measured the failure exactly: `num_workers=4` fires MLV112, a
module-level `WORKERS = 4` fires, and `CFG["workers"]` / `cfg.data.workers` are
**silent**, so every literal-dependent rule degrades the moment a project keeps
its hyperparameters where projects actually keep them.

What this module asserts, in the order the risk runs:

* **the probe ladder** - all four rungs fire MLV112, and the two that came out
  of a container are `likely`, never `certain`;
* **the de-rating is arithmetic, not a promise** - the weight is one visible
  evidence factor, it compounds once per hop, and the resulting confidence is
  exactly the product it always was;
* **the shapes** - a nested dict, a dataclass (nested through
  `field(default_factory=...)`, with constructor keywords overriding defaults)
  and argparse defaults keyed by `dest`;
* **intersection, never union** - a function called with two different
  containers resolves to neither, because a union would report a number the
  program never uses;
* **it never opens a file** - a YAML path is named in a `config_unresolved`
  diagnostic and nothing is read;
* **the `getattr` registry** - resolved to one symbol when the string is a
  literal, bounded to one-of-N when it is not, and never invented;
* **nothing else moved** - the clean corpora stay at zero and the shipped
  demo's fifteen findings keep their exact confidences.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import REPO_ROOT, validate, write_files
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict
from mlview.ir import config_shapes as CS
from mlview.ir import config_values as CV

TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(TESTS_DIR, "fixtures", "config_values")
CLEAN_DIR = os.path.join(TESTS_DIR, "clean")
CORPUS = os.path.join(TESTS_DIR, "accuracy", "corpus")
SAMPLES = os.path.join(REPO_ROOT, "samples")

MLV112_PRIOR = 0.98


def doc_for(*parts):
    path = os.path.join(FIXTURES, *parts)
    return analyze_to_dict(AnalyzeOptions(paths=(path,)))


def issues(doc, code=None):
    rows = [i for i in doc["issues"] if code is None or i["code"] == code]
    rows.sort(key=lambda i: (i["loc"]["file"], i["loc"]["line"]))
    return rows


def kinds(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


# ---------------------------------------------------------------------------
# the probe ladder
# ---------------------------------------------------------------------------
def test_the_probe_ladder_fires_on_every_rung():
    """All four rungs, and the two container reads never reach `certain`."""
    rows = issues(doc_for("ladder"), "MLV112")
    assert [r["loc"]["line"] for r in rows] == [34, 35, 36, 37]
    assert [r["confidenceBucket"] for r in rows] == [
        "certain", "certain", "likely", "likely"]
    # the numbers the rule read, not merely that it fired
    assert "num_workers=4" in rows[0]["message"]
    assert "num_workers=4" in rows[1]["message"]      # the module constant
    assert "num_workers=3" in rows[2]["message"]      # CFG["workers"]
    assert "num_workers=2" in rows[3]["message"]      # cfg.data.workers


def test_a_config_read_never_mints_a_certain_finding():
    """The de-rating is one visible factor and exactly the product it claims."""
    rows = issues(doc_for("ladder"), "MLV112")
    literal, config_read = rows[0], rows[2]
    assert not [e for e in literal["evidence"]
                if e["weight"] == CS.CONFIG_EVIDENCE_WEIGHT]
    factor = [e for e in config_read["evidence"]
              if e["weight"] == CS.CONFIG_EVIDENCE_WEIGHT]
    assert len(factor) == 1, "exactly one config factor per finding"
    assert factor[0]["kind"] == "context_confirmed"
    assert "de-rated" in factor[0]["detail"]
    assert "`CFG.workers` was read as `3`" in factor[0]["detail"]
    assert config_read["confidence"] == pytest.approx(
        round(MLV112_PRIOR * CS.CONFIG_EVIDENCE_WEIGHT, 2), abs=5e-3)
    assert config_read["confidence"] < 0.9


def test_every_hop_costs_one_more_factor():
    """`CFG -> make(cfg=CFG)` is one hop, and one hop is one more de-rating."""
    rows = issues(doc_for("hop"), "MLV112")
    assert len(rows) == 1
    expected = MLV112_PRIOR * CS.CONFIG_EVIDENCE_WEIGHT ** 2
    assert rows[0]["confidence"] == pytest.approx(round(expected, 3), abs=5e-3)
    assert rows[0]["confidenceBucket"] == "possible"
    assert "num_workers=5" in rows[0]["message"]


def test_the_hop_cap_is_a_number_not_a_hope():
    assert CS.MAX_CONFIG_HOPS == 2
    assert CS.CONFIG_EVIDENCE_WEIGHT < 1.0
    # the deepest chain the cap allows still cannot reach `likely` from a 0.98
    # prior, which is what "never certain" means arithmetically
    deepest = MLV112_PRIOR * CS.CONFIG_EVIDENCE_WEIGHT ** (CS.MAX_CONFIG_HOPS + 1)
    assert deepest < 0.7


# ---------------------------------------------------------------------------
# the shapes
# ---------------------------------------------------------------------------
def test_argparse_defaults_are_keyed_by_dest(tmp_path):
    rows = issues(doc_for("argparse_cfg"), "MLV112")
    assert len(rows) == 1 and "num_workers=6" in rows[0]["message"]
    assert rows[0]["confidenceBucket"] == "likely"


def test_argparse_dest_and_store_true(tmp_path):
    """`dest=` wins over the option string, and `store_true` implies False."""
    root = write_files(str(tmp_path), {"run.py": (
        "import argparse\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--seed', dest='random_seed', default=7)\n"
        "parser.add_argument('--amp', action='store_true')\n"
        "parser.add_argument('--no-cache', action='store_false')\n"
        "args = parser.parse_args()\n")})
    scope = _module_scope(root, "run.py")
    assert scope.bindings["args.random_seed"].literal == "7"
    assert scope.bindings["args.amp"].literal == "False"
    assert scope.bindings["args.no_cache"].literal == "True"


def test_two_parsers_in_one_module_are_refused(tmp_path):
    """Two namespaces would be indistinguishable here, so neither is read."""
    root = write_files(str(tmp_path), {"run.py": (
        "import argparse\n"
        "first = argparse.ArgumentParser()\n"
        "second = argparse.ArgumentParser()\n"
        "first.add_argument('--workers', default=4)\n"
        "args = first.parse_args()\n")})
    scope = _module_scope(root, "run.py")
    assert "args.workers" not in scope.bindings


def test_a_dataclass_ctor_keyword_replaces_the_field_default(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "from dataclasses import dataclass, field\n"
        "@dataclass\n"
        "class DataCfg:\n"
        "    workers: int = 2\n"
        "    root: str = 'data'\n"
        "@dataclass\n"
        "class Cfg:\n"
        "    data: DataCfg = field(default_factory=DataCfg)\n"
        "    epochs: int = 10\n"
        "cfg = Cfg(data=DataCfg(workers=8), epochs=3)\n")})
    scope = _module_scope(root, "run.py")
    assert scope.bindings["cfg.data.workers"].literal == "8"
    assert scope.bindings["cfg.epochs"].literal == "3"
    # the *nested* constructor did not mention `root`, so `DataCfg`'s own
    # default still applies to it - overriding a field is not discarding its
    # siblings, and claiming otherwise would report a value the program has not
    # got
    assert scope.bindings["cfg.data.root"].literal == "data"


def test_a_default_factory_that_is_not_a_dataclass_resolves_to_nothing(tmp_path):
    """ANA-5a calls a `default_factory` unresolvable; this must not disagree."""
    root = write_files(str(tmp_path), {"run.py": (
        "from dataclasses import dataclass, field\n"
        "@dataclass\n"
        "class Cfg:\n"
        "    make: object = field(default_factory=lambda: 3)\n"
        "    items: list = field(default_factory=list)\n"
        "    workers: int = 4\n"
        "cfg = Cfg()\n")})
    scope = _module_scope(root, "run.py")
    assert scope.bindings["cfg.workers"].literal == "4"
    assert "cfg.make" not in scope.bindings
    assert "cfg.items" not in scope.bindings


def test_a_subscript_and_an_attribute_are_the_same_path(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "CFG = {'data': {'workers': 4}, 'lr': 0.001}\n")})
    scope = _module_scope(root, "run.py")
    assert scope.bindings["CFG.data.workers"].literal == "4"
    assert CV.path_name(_expr("CFG['data']['workers']")) == "CFG.data.workers"
    assert CV.path_name(_expr("cfg.data['workers']")) == "cfg.data.workers"
    assert CV.path_name(_expr("cfg.data.workers")) == "cfg.data.workers"
    # a key nobody can read statically is not a path
    assert CV.path_name(_expr("CFG[key]")) is None
    assert CV.path_name(_expr("CFG")) is None


def test_a_real_assignment_always_wins_over_a_resolved_leaf(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "CFG = {'workers': 4}\n"
        "CFG.workers = 99\n")})
    scope = _module_scope(root, "run.py")
    assert scope.bindings["CFG.workers"].literal == "99"
    assert CV.config_read_of(scope.bindings["CFG.workers"]) is None


def test_a_name_that_is_not_config_shaped_is_not_a_container(tmp_path):
    """The blast radius is `CONFIG_NAME_RE` and nothing else."""
    root = write_files(str(tmp_path), {"run.py": (
        "WEIGHTS = {'workers': 4}\n")})
    scope = _module_scope(root, "run.py")
    assert "WEIGHTS.workers" not in scope.bindings


# ---------------------------------------------------------------------------
# the keywords a container supplies
# ---------------------------------------------------------------------------
def test_a_container_shuffle_stops_mlv110_making_a_false_statement():
    """The measured false positive, gone - and the true finding still there."""
    doc = doc_for("kwargs")
    assert issues(doc, "MLV110") == [], "shuffle=True came out of the container"
    fired = issues(doc, "MLV111")
    assert len(fired) == 1 and fired[0]["loc"]["line"] == 18


def test_a_finding_that_a_container_keyword_fed_is_never_certain():
    fired = issues(doc_for("kwargs"), "MLV111")[0]
    factor = [e for e in fired["evidence"]
              if e["weight"] == CS.CONFIG_EVIDENCE_WEIGHT]
    assert len(factor) == 1
    assert "`CFG.shuffle` was read as `True`" in factor[0]["detail"]
    assert fired["confidence"] < 0.9


def test_a_keyword_written_at_the_call_site_always_wins(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "CFG = {'shuffle': True}\n"
        "train_loader = DataLoader(TensorDataset(), shuffle=False)\n"
        "for epoch in range(2):\n"
        "    for x, y in train_loader:\n"
        "        pass\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert [i["code"] for i in doc["issues"] if i["code"] == "MLV110"] == ["MLV110"]


def test_a_container_value_reaches_mlv602_and_mlv208(tmp_path):
    """The other two rules the roadmap names, on the same container."""
    root = write_files(str(tmp_path), {"folds.py": (
        "from sklearn.model_selection import KFold\n"
        "CFG = {'shuffle': True, 'folds': 5}\n"
        "splitter = KFold(n_splits=CFG['folds'], shuffle=CFG['shuffle'])\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    rows = [i for i in doc["issues"] if i["code"] == "MLV602"]
    assert len(rows) == 1 and rows[0]["confidenceBucket"] != "certain"

    root = write_files(str(tmp_path / "amp"), {"amp.py": (
        "import torch\n"
        "from torch.cuda.amp import GradScaler, autocast\n"
        "CFG = {'amp': True}\n"
        "model = torch.nn.Linear(4, 2)\n"
        "opt = torch.optim.SGD(model.parameters(), lr=0.1)\n"
        "scaler = GradScaler(enabled=CFG['amp'])\n"
        "loader = [(torch.zeros(2, 4), torch.zeros(2).long())]\n"
        "for epoch in range(2):\n"
        "    for x, y in loader:\n"
        "        opt.zero_grad()\n"
        "        with autocast():\n"
        "            loss = torch.nn.functional.cross_entropy(model(x), y)\n"
        "        loss.backward()\n"
        "        opt.step()\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    rows = [i for i in doc["issues"] if i["code"] == "MLV208"]
    assert len(rows) == 1 and rows[0]["confidenceBucket"] != "certain"
    assert any("config container" in e["detail"] for e in rows[0]["evidence"])


def test_a_container_keyword_is_taken_back_when_the_container_is_refused():
    """`disagree` resolves to nothing, so no keyword survives from round one."""
    doc = doc_for("disagree")
    for node in doc["nodes"]:
        assert "workers" not in (node.get("attrs") or {})


# ---------------------------------------------------------------------------
# intersection, never union
# ---------------------------------------------------------------------------
def test_two_call_sites_that_disagree_resolve_to_neither():
    doc = doc_for("disagree")
    assert issues(doc, "MLV112") == []


def test_one_unfollowable_call_site_silences_the_others(tmp_path):
    """A caller this pass cannot follow refuses the parameter for everybody."""
    root = write_files(str(tmp_path), {"run.py": (
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "CONFIG = {'workers': 7}\n"
        "def make(cfg):\n"
        "    return DataLoader(TensorDataset(), num_workers=cfg['workers'])\n"
        "def outer(other):\n"
        "    return make(other)\n"
        "first = make(CONFIG)\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert [i for i in doc["issues"] if i["code"] == "MLV112"] == []


def test_two_call_sites_that_agree_do_resolve(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "from torch.utils.data import DataLoader, TensorDataset\n"
        "CONFIG = {'workers': 7}\n"
        "OPTIONS = {'workers': 7}\n"
        "def make(cfg):\n"
        "    return DataLoader(TensorDataset(), num_workers=cfg['workers'])\n"
        "first = make(CONFIG)\n"
        "second = make(OPTIONS)\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    rows = [i for i in doc["issues"] if i["code"] == "MLV112"]
    assert rows and all("num_workers=7" in r["message"] for r in rows)


# ---------------------------------------------------------------------------
# it never opens a file
# ---------------------------------------------------------------------------
def test_a_yaml_config_is_named_and_never_read():
    doc = doc_for("yaml_cfg")
    notes = [d for d in doc["diagnostics"] if d["kind"] == "config_unresolved"]
    assert notes, "the deferred half must say so"
    assert any("conf/config.yaml" in d["message"] for d in notes)
    assert all("deferred" in d["message"] for d in notes)
    assert all(d.get("file") == "run.py" for d in notes)


def test_a_hydra_decorator_says_the_composition_was_not_done(tmp_path):
    root = write_files(str(tmp_path), {"run.py": (
        "import hydra\n"
        "@hydra.main(config_path='conf', config_name='config')\n"
        "def main(cfg):\n"
        "    return cfg\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    notes = [d for d in doc["diagnostics"] if d["kind"] == "config_unresolved"]
    assert any("Hydra config for `main()`" in d["message"] for d in notes)


def test_the_pass_reads_no_file_of_its_own():
    """`ir/config_*.py` may not open, import, exec or compile anything.

    *"Never imports, never execs"* is load-bearing, and ANA-10's deferred half
    is deferred precisely because opening a config file widens the trust
    boundary. Asserted against the AST rather than the text, so a `yaml.load`
    that is a **string constant this pass recognises** does not read as a
    `yaml.load` this pass *calls*.
    """
    import ast as _ast
    banned = {"open", "exec", "eval", "compile", "__import__", "execfile"}
    for name in ("config_shapes.py", "config_values.py", "config_calls.py"):
        path = os.path.join(REPO_ROOT, "analyzer", "src", "mlview", "ir", name)
        with open(path, encoding="utf-8") as handle:
            tree = _ast.parse(handle.read())
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
                # a bare builtin: `re.compile` is an attribute of a module the
                # import guard below has already had to allow, and compiling a
                # regex reads nothing
                assert node.func.id not in banned, \
                    "%s calls %s()" % (name, node.func.id)
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                for candidate in [mod] + names:
                    head = (candidate or "").split(".")[0]
                    assert head not in ("yaml", "json", "importlib", "subprocess",
                                        "io", "os", "pathlib"), \
                        "%s imports %s" % (name, candidate)


# ---------------------------------------------------------------------------
# the getattr registry
# ---------------------------------------------------------------------------
def test_a_resolved_getattr_names_the_symbol_and_the_call_constructs_it():
    doc = doc_for("getattr_resolved")
    selection = [n for n in doc["nodes"]
                 if n.get("sublabel") == "selects torch.optim.AdamW"]
    assert len(selection) == 1
    assert selection[0]["kind"] == "config"
    assert selection[0]["fqn"] == "torch.optim.AdamW"
    built = [n for n in doc["nodes"]
             if n["kind"] == "optimizer" and n.get("fqn") == "torch.optim.AdamW"]
    assert built, "the construction a line later resolves through the selection"
    assert not [n for n in doc["nodes"]
                if n["kind"] == "unknown" and n["label"] == "factory"]


def test_an_unresolved_getattr_on_a_workspace_module_names_its_alternatives():
    doc = doc_for("registry")
    node = [n for n in doc["nodes"] if n["label"] == "cls"]
    assert len(node) == 1
    node = node[0]
    assert node["kind"] == "config"
    assert node["sublabel"] == "one of 2 in factories · Alpha, Beta"
    assert node["confidence"] < 0.6, "one of two is not a confident claim"
    assert validate(doc) == []


def test_a_getattr_on_something_that_is_not_a_workspace_module_stays_unknown(tmp_path):
    """No FQN is invented for a module this workspace does not contain."""
    root = write_files(str(tmp_path), {"run.py": (
        "import torch\n"
        "def build(name):\n"
        "    return getattr(torch.optim, name)()\n")})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    assert not [n for n in doc["nodes"]
                if (n.get("sublabel") or "").startswith("one of")]
    assert not [n for n in doc["nodes"] if n.get("fqn", "").endswith(".name")]


# ---------------------------------------------------------------------------
# config nodes and config edges
# ---------------------------------------------------------------------------
def test_the_hydra_program_gains_config_edges_and_loses_its_registry_boxes():
    """The ANA-12 program the roadmap measured: `ZERO config-kind edges`."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(CORPUS, "hydra_research"),)))
    config_edges = [e for e in doc["edges"] if e["kind"] == "config"]
    assert len(config_edges) >= 3
    assert all(e.get("label") == "cfg" for e in config_edges)
    # one container, one node - the alias in every scope it reached points at it
    sources = {e["source"] for e in config_edges}
    assert len(sources) == 1
    origin = [n for n in doc["nodes"] if n["id"] in sources][0]
    assert origin["label"] == "CFG" and origin["loc"]["file"] == "src/train.py"
    # and the edge crosses files, which is what makes it worth drawing
    targets = {e["target"] for e in config_edges}
    files = {n["loc"]["file"] for n in doc["nodes"] if n["id"] in targets}
    assert "src/models.py" in files
    unknown = sorted((n["loc"]["file"], n["loc"]["line"])
                     for n in doc["nodes"] if n["kind"] == "unknown")
    assert unknown == [("src/models.py", 39), ("src/registry.py", 21),
                       ("src/train.py", 29)], (
        "the two getattr registry boxes are gone; the subscript callee and the "
        "unresolvable receiver honestly remain - and GRAPH-R3 adds the third: "
        "`model = build_from_cfg(...)` calls a workspace factory whose return "
        "bottoms out in that same subscript, so the *call site* now says so "
        "too instead of folding onto `build_from_cfg()`'s own card two files "
        "away. The hand-drawn diagram has a box there "
        "(`corpus/hydra_research/labels.json`, src/train.py:29)")
    assert validate(doc) == []


# ---------------------------------------------------------------------------
# nothing else moved
# ---------------------------------------------------------------------------
def test_the_clean_corpora_stay_clean():
    for path in (CLEAN_DIR, os.path.join(SAMPLES, "vision_pipeline_clean")):
        doc = analyze_to_dict(AnalyzeOptions(paths=(path,)))
        assert doc["issues"] == [], path


def test_the_demo_keeps_its_fifteen_findings_and_their_confidences():
    """Stated causally, so it stays true when another rule changes.

    A confidence moves under ANA-10 only when a finding read a config value,
    and the shipped demo keeps its constants in `config.py` as plain module
    constants - which `literal_of` has always resolved and which this pass does
    not touch. So: the fifteen findings are still fifteen, they are still the
    fifteen `expected_issues.json` names, and **not one of them carries a
    config factor** - which is what "their confidences are unchanged" means.
    """
    with open(os.path.join(SAMPLES, "vision_pipeline", "expected_issues.json"),
              encoding="utf-8") as handle:
        expected = json.load(handle)
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(SAMPLES, "vision_pipeline"),)))
    assert len(expected) == 15
    got = sorted((i["code"], i["loc"]["file"], i["loc"]["line"]) for i in doc["issues"])
    want = sorted((row["code"], row["file"], row["line"]) for row in expected)
    assert got == want
    for issue in doc["issues"]:
        for evidence in issue["evidence"]:
            assert "config container" not in evidence["detail"], issue["code"]


def test_no_config_diagnostic_on_a_workspace_without_one():
    doc = analyze_to_dict(AnalyzeOptions(paths=(os.path.join(SAMPLES, "vision_pipeline"),)))
    assert [d for d in doc["diagnostics"] if d["kind"] == "config_unresolved"] == []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _module_scope(root, relpath):
    result = analyze_full(AnalyzeOptions(paths=(root,)))
    module = result.workspace.modules[relpath]
    return module.module_scope


def _expr(text):
    import ast
    return ast.parse(text, mode="eval").body
