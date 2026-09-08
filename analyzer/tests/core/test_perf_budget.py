"""PERF-01/02: the analyzer stays fast enough to be run on every save.

The audit measured the pre-optimisation analyzer at roughly O(n^1.6) - 4x the
files cost 5.7x the time - and named three causes: an unmemoised
`knowledge.lookup` (2.3M calls, 31% of the profile), `rules.context`'s
`calls_with_role` re-walking every module for each of the 14 rule call sites
that ask for one (38% cumulative), and `ir.build_ir`'s literal `range(4)` over
five whole-workspace passes.

**Measured on this machine** (Windows 11, Python 3.13, `tools/perf_equiv.py
--baseline <main> --bench --repeats 3`, best of 3, the same synthetic corpus
this test builds):

    files   before      after   change
        4    21.0 ms   22.9 ms   0.92x   - the fixed point costs 6 rounds
       50   485.0 ms  387.0 ms   1.25x     where the old literal `range(4)`
      200  4211.0 ms 1850.7 ms   2.28x     always ran exactly 4

The four-file row is the honest cost of PERF-02: a corpus small enough that the
IR rounds are the whole run pays for the two extra rounds it takes to *prove*
the fixed point. Everything past that is dominated by the memoised
`knowledge.lookup` and the role index, and the gap widens with size.

The ceiling below is deliberately ~10x the measured local number: this is a
regression trip-wire for an accidental O(n^2), not a benchmark, and a shared CI
runner is far slower and far noisier than a developer laptop.
"""

from __future__ import annotations

import importlib.util
import os
import time

import pytest

from core_support import REPO_ROOT

from mlview.api import AnalyzeOptions, analyze_to_dict

#: 200 modules of realistic framework-touching code.
CORPUS_FILES = 200
#: Wall-clock ceiling for the whole analysis, in seconds.
CEILING_S = 20.0


def _load_perf_equiv():
    """`tools/perf_equiv.py`, which owns the synthetic-corpus generator."""
    path = os.path.join(REPO_ROOT, "tools", "perf_equiv.py")
    spec = importlib.util.spec_from_file_location("mlview_perf_equiv", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def synthetic_corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("perf_budget")
    _load_perf_equiv().synth_corpus(str(root), CORPUS_FILES)
    return str(root)


def test_two_hundred_files_analyze_under_the_ceiling(synthetic_corpus):
    started = time.perf_counter()
    doc = analyze_to_dict(AnalyzeOptions(paths=(synthetic_corpus,), max_files=4000,
                                         max_nodes=100000))
    elapsed = time.perf_counter() - started
    assert doc["workspace"]["filesAnalyzed"] == CORPUS_FILES
    # a real workspace, not 200 files the analyzer shrugged at
    assert doc["stats"]["nodes"] > CORPUS_FILES * 5
    assert elapsed < CEILING_S, (
        "200 files took %.1fs, over the %.0fs budget - suspect an O(n^2) scan "
        "or a lost memoisation (PERF-01/02)" % (elapsed, CEILING_S))


def test_scaling_is_not_quadratic(synthetic_corpus, tmp_path):
    """4x the files must not cost 16x the time.

    The pre-PERF analyzer was ~O(n^1.6); the bar here is the far weaker
    "not quadratic", which is what a lost index or a reintroduced `x in list`
    would break, and which no amount of CI noise can fake.
    """
    small = str(tmp_path / "small")
    _load_perf_equiv().synth_corpus(small, CORPUS_FILES // 4)

    def timed(path):
        best = None
        for _ in range(2):
            started = time.perf_counter()
            analyze_to_dict(AnalyzeOptions(paths=(path,), max_files=4000,
                                           max_nodes=100000))
            elapsed = time.perf_counter() - started
            best = elapsed if best is None else min(best, elapsed)
        return best

    quarter = timed(small)
    full = timed(synthetic_corpus)
    assert full < quarter * 16.0, (
        "4x the files cost %.1fx the time (%.2fs -> %.2fs); quadratic scaling "
        "is back" % (full / quarter, quarter, full))
