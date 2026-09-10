"""DATAFLOW-IP (CONTRACTS 11.36) - the interprocedural dataflow mode.

The bet the roadmap ranks highest and calls the most dangerous: recall stops at
the object boundary, and lifting it is the change most likely to cost the 100%
precision that is the product's whole credibility. So this module asserts the
guardrails at least as hard as it asserts the recall:

* **`local` is unchanged** - the default, and byte-identical to the analysis
  that shipped before the flag existed, on every corpus we have;
* **the two named leaks fire** - the Lightning `DataModule` and the research
  script that scales a whole series before a chronological cut, each with
  related locations at the construction site and the split site;
* **the negative probes stay silent** - a parameter merely named `X`, a helper
  that legitimately receives already-split training rows, and a helper called
  from two sites with different tag sets (where a *union* summary would fire
  MLV102 at severity high on correct code);
* **no cross-object finding is `certain`** - every hop is one factor in the
  confidence product, and the arithmetic is asserted, not promised;
* **the clean corpora stay clean** - 0 high and at most 2 medium in `ip` too;
* **the cap speaks** - a chain that outruns three hops is reported as a
  `truncated` diagnostic rather than going quiet, because "I could not check"
  must never look like "I checked and it is fine".
"""

from __future__ import annotations

import glob
import json
import os
import sys

import pytest

from core_support import REPO_ROOT, validate
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict
from mlview.ir.provenance import DEFAULT_MAX_HOPS, IP_HOP_WEIGHT, Hop, extend
from mlview.rules.confidence import compute_confidence, interprocedural_evidence

TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATAFLOW_FIXTURES = os.path.join(TESTS_DIR, "fixtures", "dataflow")
CLEAN_DIR = os.path.join(TESTS_DIR, "clean")
CORPUS = os.path.join(TESTS_DIR, "accuracy", "corpus")
SAMPLES = os.path.join(REPO_ROOT, "samples")
MAX_MEDIUM = 2


def analyze(path: str, dataflow: str = "ip", **kwargs):
    return analyze_to_dict(AnalyzeOptions(paths=(path,), dataflow=dataflow, **kwargs))


def fixture(name: str) -> str:
    return os.path.join(DATAFLOW_FIXTURES, name)


def codes(doc, code: str):
    return [i for i in doc["issues"] if i["code"] == code and not i.get("suppressed")]


def describe(doc) -> str:
    if not doc.get("issues"):
        return "(no issues)"
    return "; ".join("%s@%s:%d %s conf=%.2f"
                     % (i["code"], i["loc"]["file"], i["loc"]["line"], i["severity"],
                        i["confidence"]) for i in doc["issues"])


def roles(issue):
    return [r["role"] for r in issue["relatedLocs"]]


@pytest.fixture(scope="module")
def ctor_ip():
    return analyze(fixture("ctor_features"), "ip")


@pytest.fixture(scope="module")
def series_ip():
    return analyze(fixture("series_cut"), "ip")


@pytest.fixture(scope="module")
def lightning_ip():
    return analyze(os.path.join(CORPUS, "lightning_tabular"), "ip")


# --------------------------------------------------------------- the mode
def test_local_is_the_default_and_the_flag_is_the_identity():
    """A caller that does not name the mode gets `local`, and naming `local`
    changes nothing: the option is additive in the CONTRACTS 11.6 sense."""
    root = os.path.join(CORPUS, "lightning_tabular")
    unset = analyze_to_dict(AnalyzeOptions(paths=(root,)))
    named = analyze(root, "local")
    assert _stable(unset) == _stable(named)


def _stable(doc):
    """The document minus the two fields that move with the clock."""
    copy = json.loads(json.dumps(doc))
    copy.pop("generatedAt", None)
    copy.get("stats", {}).pop("durationMs", None)
    copy.pop("durationMs", None)
    return json.dumps(copy, sort_keys=True)


@pytest.mark.parametrize("name", sorted(os.path.basename(p) for p in
                                        glob.glob(os.path.join(DATAFLOW_FIXTURES, "*"))))
def test_every_dataflow_fixture_is_a_valid_document_in_both_modes(name):
    for mode in ("local", "ip"):
        doc = analyze(fixture(name), mode)
        assert validate(doc) == [], "%s / %s" % (name, mode)
        assert doc["workspace"]["filesFailed"] == 0


def test_two_ip_runs_are_byte_identical():
    """The summary pass iterates to a fixed point; a fixed point that depends on
    dict order is not one."""
    root = fixture("ctor_features")
    assert _stable(analyze(root, "ip")) == _stable(analyze(root, "ip"))


# ------------------------------------------------- acceptance: the two leaks
def test_the_lightning_datamodule_leak_fires_only_in_ip_mode(lightning_ip):
    root = os.path.join(CORPUS, "lightning_tabular")
    assert codes(analyze(root, "local"), "MLV101") == [], "local mode must not change"
    found = codes(lightning_ip, "MLV101")
    assert len(found) == 1, describe(lightning_ip)
    issue = found[0]
    assert issue["loc"]["file"] == "datamodule.py" and issue["loc"]["line"] == 27
    assert issue["severity"] == "high"
    assert "split_site" in roles(issue), roles(issue)
    assert "construction" in roles(issue), roles(issue)


def test_the_research_series_leak_fires_only_in_ip_mode(series_ip):
    root = fixture("series_cut")
    assert codes(analyze(root, "local"), "MLV101") == []
    found = codes(series_ip, "MLV101")
    assert len(found) == 1, describe(series_ip)
    issue = found[0]
    assert issue["loc"]["file"] == "experiment.py"
    assert "MinMaxScaler" in open(
        os.path.join(root, "experiment.py"), encoding="utf-8").read()
    assert "split_site" in roles(issue), roles(issue)
    # the construction site the whole series entered the object through
    assert "construction" in roles(issue), roles(issue)
    ctor = [r for r in issue["relatedLocs"] if r["role"] == "construction"]
    assert any(r["file"] == "run.py" for r in ctor), ctor


def test_the_ctor_param_probe_fires(ctor_ip):
    """`ctor param -> self.features -> read in a sibling method` - the exact
    probe two audits pinned as the boundary of the analyzer's recall."""
    assert codes(analyze(fixture("ctor_features"), "local"), "MLV101") == []
    found = codes(ctor_ip, "MLV101")
    assert len(found) == 1, describe(ctor_ip)
    ctor = [r for r in found[0]["relatedLocs"] if r["role"] == "construction"]
    assert any(r["file"] == "run.py" for r in ctor), ctor


def test_the_parameter_merely_named_X_probe_does_not_fire():
    """Nothing calls `fit_scaler`, so the summary over its call sites is empty.
    A name is not evidence, in either mode."""
    for mode in ("local", "ip"):
        doc = analyze(fixture("param_named_x"), mode)
        assert doc["issues"] == [], describe(doc)


# ------------------------------------------------------- negative fixtures
@pytest.mark.parametrize("name", ["already_split", "two_call_sites", "return_chain"])
@pytest.mark.parametrize("mode", ["local", "ip"])
def test_the_negative_fixtures_are_silent(name, mode):
    doc = analyze(fixture(name), mode)
    for code in ("MLV101", "MLV102", "MLV103"):
        assert codes(doc, code) == [], "%s / %s: %s" % (name, mode, describe(doc))


def test_a_helper_that_receives_training_rows_knows_that_it_did():
    """The silence is *earned*: the parameter really carries TRAIN_SPLIT, so
    MLV101's guard is reached with information rather than with none."""
    result = analyze_full(AnalyzeOptions(paths=(fixture("already_split"),),
                                         dataflow="ip"))
    param = _binding(result.workspace, "pipeline.fit_on_training_rows", "train_x")
    assert param is not None and "TRAIN_SPLIT" in param.tags, param


def test_two_call_sites_intersect_rather_than_union():
    """`summarize(train_x)` and `summarize(test_x)`. Union would give the
    parameter TRAIN_SPLIT *and* TEST_SPLIT and fire MLV102 at severity high on
    correct code; the intersection is FEATURES and nothing else."""
    result = analyze_full(AnalyzeOptions(paths=(fixture("two_call_sites"),),
                                         dataflow="ip"))
    param = _binding(result.workspace, "report.summarize", "values")
    assert param is not None
    assert tuple(param.tags) == ("FEATURES",), param.tags
    assert "TRAIN_SPLIT" not in param.tags and "TEST_SPLIT" not in param.tags
    assert param.provenance, "the intersected fact still records its hop"


def _binding(workspace, scope_qualname: str, name: str):
    for relpath in sorted(workspace.modules):
        for scope in workspace.modules[relpath].scopes:
            if scope.qualname == scope_qualname:
                return scope.bindings.get(name)
    return None


# --------------------------------------------------------------- the summaries
def test_the_constructor_summary_reaches_the_class_scope():
    result = analyze_full(AnalyzeOptions(paths=(fixture("ctor_features"),),
                                         dataflow="ip"))
    attr = _binding(result.workspace, "datamodule.ProbeDataModule", "self.features")
    assert attr is not None, "self.features must exist in the class scope"
    assert "FEATURES" in attr.tags, attr.tags
    assert [h.kind for h in attr.provenance] == ["constructor"], attr.provenance
    assert attr.provenance[0].file == "run.py"


def test_the_constructor_summary_is_local_modes_blind_spot():
    result = analyze_full(AnalyzeOptions(paths=(fixture("ctor_features"),),
                                         dataflow="local"))
    attr = _binding(result.workspace, "datamodule.ProbeDataModule", "self.features")
    assert attr is None or not attr.tags, "local mode must not cross __init__"


def test_the_return_summary_runs_to_its_fixed_point():
    """Four `def`s between the caller and the `AdamW`: local stops short, ip
    does not - and the cap is what stops ip."""
    root = fixture("return_chain")
    local = analyze_full(AnalyzeOptions(paths=(root,), dataflow="local")).workspace
    ip = analyze_full(AnalyzeOptions(paths=(root,), dataflow="ip")).workspace
    assert _return_tags(local, "factory.build") == ()
    assert _return_tags(ip, "factory.build") == ("OPTIMIZER",)
    assert _return_tags(ip, "factory.make") == ("OPTIMIZER",)


def _return_tags(workspace, qualname):
    func = workspace.functions.get(qualname)
    summary = getattr(func, "return_summary", None) if func is not None else None
    scalar = summary.scalar if summary is not None else None
    return tuple(scalar.tags) if scalar is not None else ()


def test_the_method_arg_summary_applies_to_bound_method_call_sites():
    """ANA-2 resolves `obj.method(x)`; DATAFLOW-IP is what carries `x`'s tags
    into the method's parameter."""
    result = analyze_full(AnalyzeOptions(paths=(fixture("series_cut"),),
                                         dataflow="ip"))
    attr = _binding(result.workspace, "experiment.SeriesExperiment", "self.series")
    assert attr is not None and "FEATURES" in attr.tags, attr


# ---------------------------------------------------------------- the doubt
def test_no_cross_object_finding_is_ever_certain(ctor_ip, series_ip, lightning_ip):
    for doc in (ctor_ip, series_ip, lightning_ip):
        for issue in doc["issues"]:
            hop = [e for e in issue["evidence"] if e["kind"] == "cross_file"
                   and "interprocedurally" in e["detail"]]
            if not hop:
                continue
            assert issue["confidenceBucket"] in ("likely", "possible", "speculative"), \
                "%s landed at %s" % (issue["code"], issue["confidenceBucket"])
            assert issue["confidence"] < 0.9


def test_every_cross_object_finding_names_its_hop_chain(ctor_ip, series_ip):
    for doc in (ctor_ip, series_ip):
        for issue in codes(doc, "MLV101"):
            hop = [e for e in issue["evidence"] if e["kind"] == "cross_file"]
            assert len(hop) == 1, issue["evidence"]
            assert "hop(s)" in hop[0]["detail"]
            assert "at " in hop[0]["detail"], hop[0]["detail"]
            assert 0.0 < hop[0]["weight"] <= IP_HOP_WEIGHT


def test_the_hop_weight_is_one_explicit_factor_per_hop():
    """The de-rating is arithmetic, not a promise: MLV101's 0.95 prior lands at
    0.76 after one hop and 0.608 after two, so `certain` (>= 0.9) is out of
    reach the moment a tag crosses an object boundary."""
    class _Ref:
        tags = ("FEATURES",)
        name = "self.features"

        def __init__(self, hops):
            self.provenance = tuple(Hop("constructor", "DM(...)", None)
                                    for _ in range(hops))

    assert compute_confidence(0.95, interprocedural_evidence(_Ref(0))) == 0.95
    assert compute_confidence(0.95, interprocedural_evidence(_Ref(1))) == 0.76
    assert compute_confidence(0.95, interprocedural_evidence(_Ref(2))) == 0.608
    for hops in (1, 2, 3):
        assert compute_confidence(0.99, interprocedural_evidence(_Ref(hops))) < 0.9


def test_the_hop_cap_refuses_the_fourth_hop():
    chain = tuple(Hop("constructor", "S(...)", None) for _ in range(DEFAULT_MAX_HOPS))
    assert extend(chain[:-1], chain[-1]) is not None
    assert extend(chain, chain[-1]) is None


def test_a_capped_chain_is_reported_rather_than_dropped():
    """Four objects deep is one past the cap. The finding does not fire - and
    the document says why, because silence that looks like a clean read is the
    failure mode the whole product is trying not to have."""
    doc = analyze(fixture("deep_chain"), "ip")
    assert codes(doc, "MLV101") == [], describe(doc)
    notes = [d for d in doc["diagnostics"] if d["kind"] == "truncated"
             and "interprocedural cap" in d["message"]]
    assert notes, [d["message"] for d in doc["diagnostics"]]
    assert str(DEFAULT_MAX_HOPS) in notes[0]["message"]
    assert analyze(fixture("deep_chain"), "local")["issues"] == []


# ------------------------------------------------------------ the clean bar
@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(CLEAN_DIR, "*.py")))
                         + [os.path.join(SAMPLES, "vision_pipeline_clean")],
                         ids=lambda p: os.path.basename(p))
def test_the_clean_corpora_stay_clean_in_ip_mode(path):
    doc = analyze(path, "ip")
    counts = {"low": 0, "medium": 0, "high": 0}
    for issue in doc["issues"]:
        if not issue.get("suppressed"):
            counts[issue["severity"]] += 1
    assert counts["high"] == 0, (
        "a high-severity marker on correct code destroys the tool's "
        "credibility: %s" % describe(doc))
    assert counts["medium"] <= MAX_MEDIUM, describe(doc)


def test_the_whole_clean_corpus_together_is_clean_in_ip_mode():
    doc = analyze(CLEAN_DIR, "ip")
    high = [i for i in doc["issues"] if i["severity"] == "high"]
    assert high == [], describe(doc)


# --------------------------------------------------------------- the referee
@pytest.fixture(scope="module")
def ip_report():
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    import accuracy  # noqa: E402 - after the sys.path fix

    _results, report = accuracy.run_corpus(dataflow="ip")
    report["dataflow"] = "ip"
    return accuracy, report


def test_ip_mode_fires_no_forbidden_finding(ip_report):
    _accuracy, report = ip_report
    assert report["forbiddenFindings"] == 0, report.get("forbidden")


def test_ip_mode_precision_is_still_total(ip_report):
    _accuracy, report = ip_report
    assert report["overall"]["precision"] == pytest.approx(1.0)
    assert report["unlabelledFindings"] == 0


def test_ip_mode_recall_beats_local_and_only_ratchets_up(ip_report):
    accuracy, report = ip_report
    local = accuracy.load_baseline(accuracy.BASELINE_PATH)
    ip = accuracy.load_baseline(accuracy.IP_BASELINE_PATH)
    assert ip is not None, ("record it with `python tools/accuracy.py "
                            "--dataflow ip --update-baseline`")
    assert ip["dataflow"] == "ip"
    assert report["overall"]["recall"] > local["overall"]["recall"], (
        "the whole point of the mode is more recall")
    assert accuracy.check(report, ip) == []


def test_the_two_baselines_are_separate_ratchets():
    """`local` and `ip` are two different analyses; one number cannot gate both."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
    import accuracy  # noqa: E402

    assert accuracy.BASELINE_PATH != accuracy.IP_BASELINE_PATH
    assert os.path.isfile(accuracy.IP_BASELINE_PATH)
    local = accuracy.load_baseline(accuracy.BASELINE_PATH)
    assert local.get("dataflow", "local") == "local"
