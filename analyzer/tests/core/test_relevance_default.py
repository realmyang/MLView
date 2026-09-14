"""PERF-03 / CACHE default flip (CONTRACTS 11.39).

`--relevance ml` and the fact cache are the shipped defaults from this release.
11.28 A11 held them back deliberately and wrote down what flipping them would
cost; this file is the other half of that entry — the evidence that the cost is
exactly what A11 said and nothing more.

Four claims, in the order they matter:

1. **The documents do not move.** `samples/vision_pipeline`, its clean twin and
   `analyzer/tests/clean` are byte-identical under `ml` and under `all`. This is
   the same assertion `tools/perf_equiv.py --expect-same` makes from outside;
   it is repeated in-process so a regression fails a unit test rather than only
   a script somebody has to remember to run.
2. **A workspace it *does* narrow says so.** `fixtures/config/mixed_repo`
   exists for this: one framework file, one ordinary application module, and a
   `config_warning` naming the file that was set aside and the flag that brings
   it back.
3. **Nothing is lost, only not analyzed.** Every file is still read, a parse
   error in a set-aside file is still reported, and the finding set is
   unchanged.
4. **The old paths are still there.** `--relevance all` and `MLVIEW_NO_CACHE=1`
   reproduce the pre-flip behaviour exactly.
"""

from __future__ import annotations

import json
import os

import pytest

from core_support import FIXTURES, REPO_ROOT, write_files
from mlview import cli
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict
from mlview.cli_parser import build_parser
from mlview.core.pipeline import DEFAULT_RELEVANCE

MIXED = os.path.join(FIXTURES, "config", "mixed_repo")
CORPORA = (
    os.path.join(REPO_ROOT, "samples", "vision_pipeline"),
    os.path.join(REPO_ROOT, "samples", "vision_pipeline_clean"),
    os.path.join(REPO_ROOT, "analyzer", "tests", "clean"),
)

VOLATILE = ("generatedAt", "durationMs")


def _stable(doc):
    """The document minus the two fields CONTRACTS section 2 lets vary."""
    copy = json.loads(json.dumps(doc))
    copy.get("generator", {}).pop("generatedAt", None)
    for key in VOLATILE:
        copy.pop(key, None)
        copy.get("stats", {}).pop(key, None)
        copy.get("generator", {}).pop(key, None)
    copy.get("workspace", {}).pop("durationMs", None)
    return json.dumps(copy, indent=2, ensure_ascii=False, sort_keys=True)


def _aside(doc):
    return [d for d in doc["diagnostics"]
            if d["kind"] == "config_warning" and "Relevance prefilter" in d["message"]]


# ------------------------------------------------------------ the default
def test_the_shipped_default_is_ml_everywhere_it_is_written_down():
    assert DEFAULT_RELEVANCE == "ml"
    assert AnalyzeOptions(paths=(".",)).relevance == "ml"
    args = build_parser().parse_args(["analyze", "."])
    assert args.relevance == "ml" and args.relevance_hops == 2
    assert args.no_cache is False


@pytest.mark.parametrize("command", ["analyze", "issues", "render", "baseline"])
def test_every_command_that_analyzes_carries_the_same_default(command):
    argv = [command, "write", "."] if command == "baseline" else [command, "."]
    assert build_parser().parse_args(argv).relevance == "ml"


# --------------------------------------------------- the documents hold
@pytest.mark.parametrize("corpus", CORPORA, ids=lambda p: os.path.basename(p))
def test_the_shipped_corpora_are_byte_identical_in_both_modes(corpus):
    narrow = analyze_to_dict(AnalyzeOptions(paths=(corpus,), cache=False))
    wide = analyze_to_dict(AnalyzeOptions(paths=(corpus,), relevance="all",
                                          cache=False))
    assert _stable(narrow) == _stable(wide)
    assert _aside(narrow) == [], "these corpora are entirely machine learning"


def test_the_demo_document_is_untouched_by_the_flip():
    from mlview import api

    with open(os.path.join(REPO_ROOT, "contracts", "graph.sample.json"), "rb") as handle:
        assert api.demo_bytes() == handle.read()


# ------------------------------------------------- a workspace it narrows
def test_the_mixed_fixture_names_the_file_it_set_aside():
    doc = analyze_to_dict(AnalyzeOptions(paths=(MIXED,), cache=False))
    assert doc["workspace"]["filesAnalyzed"] == 1
    notes = _aside(doc)
    assert len(notes) == 1 and notes[0]["count"] == 1
    assert "report_utils.py" in notes[0]["message"]
    assert "--relevance all" in notes[0]["message"]
    assert "--relevance-hops" in notes[0]["message"]


def test_the_wide_mode_analyzes_both_files_and_says_nothing():
    doc = analyze_to_dict(AnalyzeOptions(paths=(MIXED,), relevance="all",
                                         cache=False))
    assert doc["workspace"]["filesAnalyzed"] == 2
    assert _aside(doc) == []


def test_the_narrowed_run_reports_the_same_findings():
    narrow = analyze_to_dict(AnalyzeOptions(paths=(MIXED,), cache=False))
    wide = analyze_to_dict(AnalyzeOptions(paths=(MIXED,), relevance="all",
                                          cache=False))
    assert ([i["id"] for i in narrow["issues"]]
            == [i["id"] for i in wide["issues"]])


def test_a_file_named_explicitly_is_never_set_aside():
    """11.28 A7, now that it is the default path: asking about one file must
    not be answered with a filter's opinion of that file."""
    doc = analyze_to_dict(AnalyzeOptions(
        paths=(os.path.join(MIXED, "report_utils.py"),), cache=False))
    assert doc["workspace"]["filesAnalyzed"] == 1
    assert _aside(doc) == []


def test_a_parse_error_in_a_set_aside_file_is_still_reported(tmp_path):
    root = write_files(str(tmp_path), {
        "train.py": "import torch\nMODEL = torch.nn.Linear(2, 2)\n",
        "broken.py": "def oops(:\n"})
    doc = analyze_to_dict(AnalyzeOptions(paths=(root,), cache=False))
    errors = [d for d in doc["diagnostics"] if d["kind"] == "parse_error"]
    assert [d["file"] for d in errors] == ["broken.py"]
    assert doc["workspace"]["filesFailed"] == 1


# ---------------------------------------------------- the cache is on now
def test_a_warm_default_run_is_byte_identical_to_a_cold_one(tmp_path, monkeypatch):
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cache"))
    root = write_files(str(tmp_path / "ws"), {
        "train.py": "import torch\nMODEL = torch.nn.Linear(2, 2)\n",
        "notes.py": "VALUE = 1\n"})
    cold = analyze_full(AnalyzeOptions(paths=(root,)))
    warm = analyze_full(AnalyzeOptions(paths=(root,)))
    assert _stable(cold.graph.to_dict()) == _stable(warm.graph.to_dict())
    assert cold.cache is not None and warm.cache is not None
    assert getattr(warm.cache, "hits", 0) >= 1, "the second run read the sidecar"


def test_no_cache_still_turns_it_off(tmp_path, monkeypatch):
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MLVIEW_NO_CACHE", "1")
    root = write_files(str(tmp_path / "ws"), {
        "train.py": "import torch\nMODEL = torch.nn.Linear(2, 2)\n"})
    result = analyze_full(AnalyzeOptions(paths=(root,)))
    assert result.cache is None
    assert not os.path.isdir(str(tmp_path / "cache"))


def test_the_wide_mode_never_consults_the_cache(tmp_path, monkeypatch):
    """11.28 B7 survives the flip: in `all` there is nothing for it to decide."""
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cache"))
    root = write_files(str(tmp_path / "ws"), {
        "train.py": "import torch\nMODEL = torch.nn.Linear(2, 2)\n"})
    result = analyze_full(AnalyzeOptions(paths=(root,), relevance="all"))
    assert result.cache is None
    assert not os.path.isdir(str(tmp_path / "cache"))


# ------------------------------------------------------------------- CLI
def test_the_cli_default_narrows_and_the_flag_restores(capsysbinary, tmp_path):
    def run(*argv):
        code = cli.main(list(argv))
        captured = capsysbinary.readouterr()
        return code, captured.out.decode("utf-8"), captured.err.decode("utf-8")

    code, out, _err = run("analyze", MIXED, "--format", "json", "--no-cache")
    assert code == 0
    narrow = json.loads(out)
    assert narrow["workspace"]["filesAnalyzed"] == 1

    code, out, _err = run("analyze", MIXED, "--format", "json", "--no-cache",
                          "--relevance", "all")
    assert code == 0
    assert json.loads(out)["workspace"]["filesAnalyzed"] == 2
