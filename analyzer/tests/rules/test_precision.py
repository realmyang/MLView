"""The precision gate: six idiomatic, correct programs (CONTRACTS section 7.4).

`tests/clean/` is hand-written, correct ML code - the textbook loop, AMP with
gradient accumulation, a LightningModule, a HuggingFace `Trainer` run, a
scikit-learn `Pipeline` + `GridSearchCV`, and a `TimeSeriesSplit` walk-forward
forecast. The bar A7 sets is **0 high and at most 2 medium** across all of
them, analyzed together *and* one at a time.

The sixth file landed on 2026-09-08 (ANA-12's precision-corpus clause): R3.7
asks for ">= 6 idiomatic correct programs ... including a `TimeSeriesSplit`
script", and the corpus had stood at five with no time-series program at all,
so the requirement was open while the item read as done.

A high-severity marker on this corpus is the failure that costs the tool its
credibility, so it is asserted twice over.
"""

from __future__ import annotations

import os

import pytest

from rule_harness import CLEAN_DIR, analyze_paths, clean_corpus, counts, describe, validate

MAX_MEDIUM = 2
EXPECTED_FILES = ("amp_accumulation.py", "hf_trainer.py", "lightning_module.py",
                  "sklearn_pipeline.py", "timeseries_split.py", "vanilla_torch.py")


@pytest.fixture(scope="module")
def corpus():
    return analyze_paths(CLEAN_DIR)


def test_the_corpus_is_the_six_files_the_contract_names():
    assert tuple(sorted(os.path.basename(p) for p in clean_corpus())) == EXPECTED_FILES


def test_no_high_severity_finding_anywhere(corpus):
    high = [i for i in corpus["issues"] if i["severity"] == "high"]
    assert high == [], (
        "a high-severity marker on correct code destroys the tool's credibility: %s"
        % describe(corpus))


def test_at_most_two_medium_findings(corpus):
    got = counts(corpus)
    assert got["medium"] <= MAX_MEDIUM, describe(corpus)


@pytest.mark.parametrize("path", clean_corpus(), ids=lambda p: os.path.basename(p))
def test_each_file_alone_is_clean(path):
    """Analyzed on its own, with no neighbour to supply a seed or a wrapper."""
    doc = analyze_paths(path)
    got = counts(doc)
    assert got["high"] == 0, describe(doc)
    assert got["medium"] <= MAX_MEDIUM, describe(doc)


def test_the_corpus_really_was_analyzed(corpus):
    assert corpus["workspace"]["filesAnalyzed"] == len(EXPECTED_FILES)
    assert corpus["workspace"]["filesFailed"] == 0
    assert len(corpus["nodes"]) > 80
    frameworks = set(corpus["workspace"]["frameworks"])
    assert {"torch", "sklearn", "lightning", "hf", "pandas"} <= frameworks


def test_the_wrapper_files_are_actually_detected_as_wrappers():
    """The `negation_absent` gate is only exercised if the wrapper is found."""
    lightning = analyze_paths(os.path.join(CLEAN_DIR, "lightning_module.py"))
    assert "lightning" in lightning["workspace"]["frameworks"]
    hf = analyze_paths(os.path.join(CLEAN_DIR, "hf_trainer.py"))
    assert "hf" in hf["workspace"]["frameworks"]


def test_the_corpus_document_is_contract_valid(corpus):
    assert validate(corpus) == []


def test_no_rule_raised_on_the_corpus(corpus):
    errors = [d for d in corpus["diagnostics"] if d["kind"] == "rule_error"]
    assert errors == [], errors


def test_a_deliberate_defect_in_the_same_shape_still_fires(tmp_path):
    """The corpus is silent because it is correct, not because nothing runs."""
    source = open(os.path.join(CLEAN_DIR, "vanilla_torch.py"), encoding="utf-8").read()
    broken = source.replace("        optimizer.zero_grad(set_to_none=True)\n", "")
    assert broken != source
    target = tmp_path / "vanilla_torch.py"
    target.write_text(broken, encoding="utf-8")
    doc = analyze_paths(str(target))
    assert any(i["code"] == "MLV201" for i in doc["issues"]), describe(doc)


def test_a_time_series_program_is_actually_in_the_corpus():
    """R3.7 names one shape outright, and only a real file satisfies it: the
    corpus stood at five with no `TimeSeriesSplit` anywhere until 2026-09-08."""
    path = os.path.join(CLEAN_DIR, "timeseries_split.py")
    source = open(path, encoding="utf-8").read()
    assert "TimeSeriesSplit" in source
    body = source.split('"""', 2)[-1]
    assert "train_test_split" not in body, "a walk-forward program never shuffles"
    doc = analyze_paths(path)
    got = counts(doc)
    assert got["high"] == 0 and got["medium"] <= MAX_MEDIUM, describe(doc)
    assert len(EXPECTED_FILES) >= 6
