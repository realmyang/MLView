"""PERF-03: the relevance prefilter (CONTRACTS 11.28).

Two obligations are asserted here and they pull in opposite directions.

* **`--relevance all` is the identity.** Every document the analyzer emitted
  before this feature existed, it still emits, byte for byte. That is what
  `test_the_two_modes_agree_*` proves on the shipped samples, on every
  single-file rule fixture and on a package with a re-export chain.
* **`--relevance ml` says what it set aside.** A filter that quietly shrinks
  the answer is the exact failure mode this project refuses, so the set-aside
  count, the flag that includes them and four of the files by name are all in a
  `config_warning`, and the tests read that message rather than trusting a
  count.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from core_support import FIXTURES, REPO_ROOT

from mlview.api import AnalyzeOptions, analyze_to_dict
from mlview.core import relevance as R
from mlview.ingest.discover import discover
from mlview.ingest.parse import parse_all
from mlview.ir.build_ir import dotted_for, is_package
from mlview.ir.symbols import build_symbol_table

SAMPLES = os.path.join(REPO_ROOT, "samples")
DIRTY = os.path.join(SAMPLES, "vision_pipeline")

TORCH_MODULE = (
    "import torch\n"
    "import torch.nn as nn\n\n\n"
    "class Net(nn.Module):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "        self.fc = nn.Linear(4, 2)\n\n"
    "    def forward(self, x):\n"
    "        return self.fc(x)\n"
)
PLAIN_MODULE = (
    '"""No framework anywhere in this file."""\n'
    "import json\n"
    "import os\n\n\n"
    "def load(path):\n"
    "    with open(os.path.join(path, 'a.json'), encoding='utf-8') as fh:\n"
    "        return json.load(fh)\n"
)


def _facts(files):
    """`{relpath: FileFacts}` for a dict of `{relpath: source}`, parsed in memory."""
    from mlview.ingest.parse import parse_source

    out = {}
    for relpath, source in files.items():
        parsed, failure = parse_source(source, relpath, "/tmp/" + relpath)
        assert failure is None, failure
        out[relpath] = R.facts_of_parsed(parsed)
    return out


def _sha(doc):
    """The document minus the two fields CONTRACTS section 2 lets vary."""
    doc = json.loads(json.dumps(doc))
    doc.get("generator", {}).pop("generatedAt", None)
    doc.get("stats", {}).pop("durationMs", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------- tokens
def test_the_seed_tokens_are_derived_from_the_knowledge_tables():
    """A framework added to `knowledge/` becomes a seed token for free."""
    import mlview.knowledge as K

    tokens = set(R.framework_tokens())
    for root in K._MODULE_FRAMEWORK:
        if root not in R.GENERIC_ROOTS:
            assert root in tokens, "%s is a framework root and must seed" % root
    for wrapper in K.WRAPPER_FQNS:
        assert wrapper.split(".")[0] in tokens


def test_the_generic_roots_are_excluded_or_the_filter_is_a_no_op():
    """`os`, `json` and friends are in the tables and in every Python file."""
    tokens = set(R.framework_tokens())
    assert not (tokens & R.GENERIC_ROOTS)
    assert not R.is_seed(PLAIN_MODULE)
    assert R.is_seed(TORCH_MODULE)


def test_a_token_matches_only_on_a_whole_word():
    assert not R.is_seed("torchlight = 1\n")
    assert not R.is_seed("my_torch = 1\n")
    assert R.is_seed("x = torch.zeros(3)\n")


# -------------------------------------------------------------------- modes
def test_all_mode_keeps_everything_and_says_nothing():
    facts = _facts({"a.py": TORCH_MODULE, "b.py": PLAIN_MODULE})
    decision = R.select(facts, mode="all")
    assert decision.kept == ("a.py", "b.py")
    assert decision.set_aside == ()
    assert decision.reason == "mode"
    assert R.relevance_diagnostic(decision) is None


def test_a_workspace_with_no_seed_at_all_is_never_narrowed():
    """The refusal: no framework token anywhere is not a licence to analyze
    nothing. It is a reason to have no opinion."""
    facts = _facts({"a.py": PLAIN_MODULE, "b.py": PLAIN_MODULE})
    decision = R.select(facts, mode="ml")
    assert decision.kept == ("a.py", "b.py")
    assert decision.reason == "no-seeds"
    assert R.relevance_diagnostic(decision) is None


def test_an_unreachable_module_is_set_aside_and_named():
    facts = _facts({"train.py": TORCH_MODULE, "island.py": PLAIN_MODULE})
    decision = R.select(facts, mode="ml")
    assert decision.kept == ("train.py",)
    assert decision.set_aside == ("island.py",)
    note = R.relevance_diagnostic(decision)
    assert note.kind == "config_warning"
    assert note.count == 1
    assert "island.py" in note.message
    assert "--relevance all" in note.message
    assert "--relevance-hops" in note.message


def test_a_helper_one_hop_from_a_seed_survives():
    """`utils.py` wraps a splitter without importing sklearn itself - the case
    the roadmap names as the reason hops are followed in both directions."""
    facts = _facts({
        "train.py": "import torch\nfrom utils import split\n\n\nsplit([1], [2])\n",
        "utils.py": "def split(a, b):\n    return a, b\n",
        "island.py": PLAIN_MODULE,
    })
    decision = R.select(facts, mode="ml", hops=1)
    assert decision.kept == ("train.py", "utils.py")
    assert decision.set_aside == ("island.py",)


def test_hops_are_followed_in_both_directions():
    """A module that imports a seed is as relevant as one a seed imports."""
    facts = _facts({
        "model.py": TORCH_MODULE,
        "caller.py": "from model import Net\n\n\ndef build():\n    return Net()\n",
        "island.py": PLAIN_MODULE,
    })
    decision = R.select(facts, mode="ml", hops=1)
    assert "caller.py" in decision.kept
    assert decision.set_aside == ("island.py",)


@pytest.mark.parametrize("hops,expected", [
    (0, ("seed.py",)),
    (1, ("one.py", "seed.py")),
    (2, ("one.py", "seed.py", "two.py")),
    (3, ("one.py", "seed.py", "three.py", "two.py")),
])
def test_the_hop_count_is_exactly_what_it_says(hops, expected):
    facts = _facts({
        "seed.py": TORCH_MODULE,
        "one.py": "from seed import Net\n\n\nA = Net\n",
        "two.py": "from one import A\n\n\nB = A\n",
        "three.py": "from two import B\n\n\nC = B\n",
    })
    decision = R.select(facts, mode="ml", hops=hops)
    assert decision.kept == expected


def test_an_explicitly_named_file_is_always_a_seed():
    """`mlview issues helper.py` asks about that file. A prefilter that decides
    it is uninteresting has answered a different question."""
    facts = _facts({"helper.py": PLAIN_MODULE, "other.py": PLAIN_MODULE})
    decision = R.select(facts, mode="ml", hops=0, pinned=("helper.py",))
    assert decision.kept == ("helper.py",)
    assert decision.set_aside == ("other.py",)


def test_a_package_init_on_a_kept_module_path_is_kept():
    """Importing `pkg.mod` executes `pkg/__init__.py`, so it belongs to the
    package whether or not any import statement names it."""
    facts = _facts({
        "pkg/__init__.py": '"""Package."""\n',
        "pkg/model.py": TORCH_MODULE,
        "island.py": PLAIN_MODULE,
    })
    decision = R.select(facts, mode="ml", hops=0)
    assert decision.kept == ("pkg/__init__.py", "pkg/model.py")


def test_an_ana3_reexport_chain_is_followed_before_the_cut():
    """ROADMAP's hard sequencing: the k-hop reachability is computed after
    ANA-3's re-export resolution, or the prefilter cuts the chains ANA-3 just
    repaired. `pkg/__init__.py` publishes `Net`; `train.py` imports it from the
    package, and `pkg/net.py` must survive at **one** hop, not two."""
    facts = _facts({
        "pkg/__init__.py": "from .net import Net\n",
        "pkg/net.py": TORCH_MODULE,
        "train.py": "from pkg import Net\n\n\nMODEL = Net\n",
        "island.py": PLAIN_MODULE,
    })
    graph = R.import_graph(facts)
    assert "pkg/net.py" in graph["train.py"], graph
    decision = R.select(facts, mode="ml", hops=1)
    assert decision.set_aside == ("island.py",)


def test_import_resolution_agrees_with_the_symbol_table():
    """`resolve_imports` and `build_symbol_table` must never disagree about
    what a module is called - the prefilter would then cut a real edge."""
    found = discover([DIRTY], max_files=100)
    parsed, failures, _sink = parse_all(found)
    assert not failures
    names = {dotted_for(p.relpath) for p in parsed}
    names.discard("")
    for p in parsed:
        dotted = dotted_for(p.relpath)
        table = build_symbol_table(p.tree, dotted, names,
                                   is_package=is_package(p.relpath))
        targets, aliases = R.resolve_imports(R.facts_of_parsed(p), dotted,
                                             is_package(p.relpath), names)
        assert targets >= {t for t, _line in table.import_sites}, p.relpath
        assert aliases == table.aliases, p.relpath


def test_the_raw_import_rows_round_trip_through_the_cache_payload():
    facts = R.facts_of_parsed(
        _parse("pkg/a.py", "import torch\nfrom . import b\nfrom .c import D as E\n"))
    payload = json.loads(json.dumps(facts.payload()))
    back = R.facts_from_payload("pkg/a.py", payload)
    assert back == facts


def test_a_malformed_payload_is_a_miss_not_a_crash():
    assert R.facts_from_payload("a.py", {"s": 1}) is None
    assert R.facts_from_payload("a.py", {"i": "not a list", "s": 0}) is None


def _parse(relpath, source):
    from mlview.ingest.parse import parse_source

    parsed, failure = parse_source(source, relpath, "/tmp/" + relpath)
    assert failure is None
    return parsed


# ------------------------------------------------------- end-to-end equality
@pytest.mark.parametrize("corpus", [
    "samples/vision_pipeline",
    "samples/vision_pipeline_clean",
    "analyzer/tests/clean",
])
def test_the_two_modes_agree_on_the_shipped_corpora(corpus):
    path = os.path.join(REPO_ROOT, corpus)
    common = dict(max_files=4000, max_nodes=4000, cache=False)
    everything = analyze_to_dict(AnalyzeOptions(paths=(path,), **common))
    filtered = analyze_to_dict(AnalyzeOptions(paths=(path,), relevance="ml", **common))
    assert _sha(everything) == _sha(filtered)


def test_the_two_modes_agree_on_every_rule_fixture():
    """Every `fixtures/rules/*.py` case is a single file, so the prefilter
    either pins it or finds no seed - both of which keep it."""
    directory = os.path.join(FIXTURES, "rules")
    names = sorted(n for n in os.listdir(directory) if n.endswith(".py"))
    assert len(names) > 10
    for name in names:
        path = os.path.join(directory, name)
        everything = analyze_to_dict(AnalyzeOptions(paths=(path,), cache=False))
        filtered = analyze_to_dict(AnalyzeOptions(paths=(path,), relevance="ml",
                                                  cache=False))
        assert _sha(everything) == _sha(filtered), name


def test_a_narrowed_run_reports_the_same_findings_as_the_wide_one(make_workspace):
    """The acceptance criterion, in miniature: the set-aside files carry no
    findings, so the finding set is unchanged and only `filesAnalyzed` moves."""
    files = {"train.py": TORCH_MODULE + "\nimport torch\nMODEL = Net()\n"}
    for index in range(6):
        files["app_%d.py" % index] = PLAIN_MODULE
    root = make_workspace(files)
    everything = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    filtered = analyze_to_dict(AnalyzeOptions(paths=(root,), relevance="ml",
                                              cache=False))
    assert ([i["code"] for i in everything["issues"]]
            == [i["code"] for i in filtered["issues"]])
    assert everything["workspace"]["filesAnalyzed"] == 7
    assert filtered["workspace"]["filesAnalyzed"] == 1
    notes = [d for d in filtered["diagnostics"]
             if d["kind"] == "config_warning" and "Relevance prefilter" in d["message"]]
    assert len(notes) == 1 and notes[0]["count"] == 6


def test_a_parse_error_in_a_set_aside_file_is_still_reported(make_workspace):
    """Every file is read in both modes, so a broken one is named in both.
    Silence about a file MLView could not even parse is not an optimisation."""
    root = make_workspace({"train.py": TORCH_MODULE, "broken.py": "def (:\n"})
    filtered = analyze_to_dict(AnalyzeOptions(paths=(root,), relevance="ml",
                                              cache=False))
    errors = [d for d in filtered["diagnostics"] if d["kind"] == "parse_error"]
    assert [e["file"] for e in errors] == ["broken.py"]
    assert filtered["workspace"]["filesFailed"] == 1
