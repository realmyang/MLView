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

import hashlib
import importlib.util
import json
import os
import random
import time

import pytest

from core_support import REPO_ROOT

from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict

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


# --------------------------------------------------------------------- PERF-03
#: The mixed acceptance corpus: 50 framework modules, 450 ordinary ones.
MIXED_ML, MIXED_APP = 50, 450
#: `--relevance ml` must be at least this much faster than `--relevance all` on
#: it. Measured on this Mac at **2.6x-3.2x** (2228 ms -> 693 ms, best of 3) on
#: an idle machine. The bar is a ratio rather than a wall-clock number because a
#: ratio survives a CI runner that is three times slower at everything - but it
#: is set well under the measurement because it does **not** survive a runner
#: that is three times slower at everything *except* the disk: under `-n 4` the
#: fixed per-file read is a larger share of both sides and the ratio compresses
#: to ~1.6x. What this number has to catch is a prefilter that stopped
#: filtering, which reads as 1.0x, and the assertions above it - `filesAnalyzed`
#: and the finding set - are exact and carry the real weight.
NARROWING_SPEEDUP = 1.25
#: The warm-cache delta path is **not** gated on a wall-clock ratio, because a
#: ratio is a property of the runner and not of the cache (CI-MACOS-01). What
#: the cache can save is one thing only - parsing a file whose bytes it has
#: already seen - and the run reports that saving exactly, as a hit count. The
#: same code measured **1.45x - 2.50x across five runs on this Mac** and
#: **1.15x then 1.38x** on two runs of the GitHub `macos-latest` runner - the
#: first of which is the one that reddened `smoke (macos)` against a 1.25 bar.
#: The hit count was 501 of 501 on every one of them.
#:
#: The ratio is dominated by the term the cache does **not** touch. What it
#: elides is the parse of the 450 modules the prefilter was going to discard
#: anyway; reading all 501 files, the IR fixed point and every rule over the 51
#: kept modules are paid in full by the warm run too, and that common term is
#: two to four times the elided one - so the ratio is `1 + saved/common`, it
#: drifts towards 1.0 with every rule the analyzer gains, and it moves with
#: whatever else the host is doing. Measured, on one `macos-latest` job: two
#: runs of the *identical* configuration (`relevance="ml"`, cache off) in the
#: same process took **1.19 s and 0.76 s**, 57% apart. A bar at 1.25 against a
#: quantity that reads 1.15x-1.38x on a host whose inputs swing by half was
#: going to redden whatever the cache did. (Reading the bytes is not the
#: difference: 0.01 s for all 501 files on that runner.) The assertion below is
#: therefore the count, and wall clock is held to an absolute ceiling.
#:
#: The ceiling is the CACHE item's own acceptance number - *"editing one file in
#: a 500-file repo and re-analysing costs under 2 s"* - with the same room for a
#: loaded shared runner that `CEILING_S` above carries.
DELTA_CEILING_S = 8.0


@pytest.fixture(scope="module")
def mixed_corpus(tmp_path_factory):
    """500 files, of which 50 touch a framework and 450 do not, in one package
    whose two halves never import each other."""
    root = tmp_path_factory.mktemp("perf_mixed")
    _load_perf_equiv().mixed_corpus(str(root), MIXED_ML, MIXED_APP)
    return str(root)


def _timed(path, repeats=2, **kwargs):
    """Best-of-`repeats` wall clock, the document, and what the cache did.

    `analyze_full` rather than `analyze_to_dict` so the `CacheReport` of the run
    that was just timed comes back with it: the hit count is the one measure of
    what the cache saved that reads the same on every machine, and the timing
    below it is the one that does not. `to_dict()` stays inside the clock, so a
    figure here is comparable with every figure recorded before it.
    """
    best, doc, cache = None, None, None
    for _ in range(repeats):
        started = time.perf_counter()
        result = analyze_full(AnalyzeOptions(paths=(path,), max_files=4000,
                                             max_nodes=100000, **kwargs))
        doc = result.graph.to_dict()
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
        cache = result.cache
    return best, doc, cache


def _codes(doc):
    return sorted(issue["code"] for issue in doc["issues"])


def _read_all_s(path):
    """How long the bytes alone cost - the floor under every run of `path`.

    Not asserted on. It is printed beside the cold and warm figures because it
    is the term that decides whether a cache which skips *parsing* shows up as a
    ratio at all, and it is the term that differs most between a laptop and a
    shared runner.
    """
    started = time.perf_counter()
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), "rb") as handle:
                    handle.read()
    return time.perf_counter() - started


def test_the_prefilter_narrows_a_mixed_repo_and_pays_for_itself(mixed_corpus):
    """PERF-03's acceptance: the mixed repo analyses materially faster under
    `--relevance ml`, and every finding survives."""
    wide_s, wide, _ = _timed(mixed_corpus, relevance="all", cache=False)
    narrow_s, narrow, _ = _timed(mixed_corpus, relevance="ml", cache=False)
    assert wide["workspace"]["filesAnalyzed"] == MIXED_ML + MIXED_APP + 1
    # the ML half plus the package `__init__` - nothing else is reachable
    assert narrow["workspace"]["filesAnalyzed"] == MIXED_ML + 1
    assert _codes(wide) == _codes(narrow), "the prefilter must not lose a finding"
    print("PREFILTER: %d files wide %.2fs -> %d files narrow %.2fs, %.2fx "
          "(the bytes alone cost %.2fs)"
          % (wide["workspace"]["filesAnalyzed"], wide_s,
             narrow["workspace"]["filesAnalyzed"], narrow_s,
             wide_s / narrow_s, _read_all_s(mixed_corpus)))
    assert wide_s / narrow_s >= NARROWING_SPEEDUP, (
        "--relevance ml was only %.2fx faster than --relevance all (%.2fs -> %.2fs); "
        "the prefilter is not paying for its own import graph"
        % (wide_s / narrow_s, wide_s, narrow_s))


def test_the_prefilter_says_how_much_it_set_aside(mixed_corpus):
    """A filter that quietly shrinks the answer is the failure mode this
    project refuses, so the count and the flag are in the document."""
    _elapsed, doc, _ = _timed(mixed_corpus, repeats=1, relevance="ml", cache=False)
    notes = [d for d in doc["diagnostics"]
             if d["kind"] == "config_warning" and "Relevance prefilter" in d["message"]]
    assert len(notes) == 1
    assert notes[0]["count"] == MIXED_APP
    assert "--relevance all" in notes[0]["message"]


# ----------------------------------------------------------------------- CACHE
def test_editing_one_file_re_analyses_fast_and_byte_identically(mixed_corpus,
                                                                tmp_path, monkeypatch):
    """CACHE's acceptance: after one file changes, only that module's facts are
    recomputed - and the document is byte-identical to a cold run of the same
    tree, which is the only property that makes a cache safe to ship.

    *Only that module* is asserted as a **count**, not as a stopwatch reading:
    after the edit the run must report 500 hits and exactly 1 miss, and the
    fully warm run 501 hits and none. That is the whole of what this cache does
    - it keeps the analyzer from parsing a file whose bytes it has already seen
    - and 500 is 500 on every machine.

    **What this cannot assert** (CI-MACOS-01): that a warm run is any given
    factor faster than a cold one. The identical code measured 1.45x - 2.50x
    here and 1.15x then 1.38x on `macos-latest`, with the same 501 hits every
    time, because most of a run is work the cache cannot remove and that work
    is not steady - see `DELTA_CEILING_S` above for the numbers. Wall clock is
    therefore held to that ceiling, which catches a cache that has started
    costing more than it saves, and the measured figures are printed and put in
    the assertion messages so a run that trips it says what it saw.
    """
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MLVIEW_CACHE_KEY_FILE", str(tmp_path / "keys" / "cache.key"))
    monkeypatch.delenv("MLVIEW_NO_CACHE", raising=False)
    files = MIXED_ML + MIXED_APP + 1                 # the package `__init__` too
    cold_first, _doc, first = _timed(mixed_corpus, repeats=1, relevance="ml")
    assert (first.status, first.hits, first.misses) == ("none", 0, files), first.line()

    victim = os.path.join(mixed_corpus, "pkg",
                          "ml_%03d.py" % random.Random(4).randrange(MIXED_ML))
    with open(victim, "a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\ndef mutated_marker():\n    return 42\n")

    delta_s, _doc, delta = _timed(mixed_corpus, repeats=1, relevance="ml")
    assert (delta.status, delta.hits, delta.misses) == ("partial", files - 1, 1), (
        "one file changed, so exactly one module's facts may be recomputed; the "
        "run reported %s" % delta.line())

    warm_s, warm, report = _timed(mixed_corpus, relevance="ml")
    cold_s, cold, off = _timed(mixed_corpus, relevance="ml", cache=False)
    assert (report.status, report.hits, report.misses) == ("full", files, 0), report.line()
    assert off is None, "--no-cache must consult nothing at all"
    assert _digest(warm) == _digest(cold), (
        "a cached re-analysis must be byte-identical to a cold one")
    # The record, for whoever reads a CI log next. `-rP` prints it for a run
    # that passed; a failure below carries the same numbers in its message.
    print("CACHE delta: %d files, cold %.2fs (first %.2fs), warm %.2fs after a "
          "%.2fs 1-miss run, %.2fx, %s; the bytes alone cost %.2fs"
          % (files, cold_s, cold_first, warm_s, delta_s, cold_s / warm_s,
             report.line(), _read_all_s(mixed_corpus)))
    assert warm_s < DELTA_CEILING_S, (
        "a warm re-analysis of %d files took %.2fs, over the %.0fs ceiling "
        "(cold %.2fs, %s) - the cache is costing more than it saves"
        % (files, warm_s, DELTA_CEILING_S, cold_s, report.line()))


def test_the_cache_never_moves_a_byte_on_the_shipped_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MLVIEW_CACHE_KEY_FILE", str(tmp_path / "keys" / "cache.key"))
    monkeypatch.delenv("MLVIEW_NO_CACHE", raising=False)
    sample = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
    off = analyze_to_dict(AnalyzeOptions(paths=(sample,), cache=False))
    cold = analyze_to_dict(AnalyzeOptions(paths=(sample,), relevance="ml"))
    warm = analyze_to_dict(AnalyzeOptions(paths=(sample,), relevance="ml"))
    assert _digest(off) == _digest(cold) == _digest(warm)


def _digest(doc):
    doc = json.loads(json.dumps(doc))
    doc.get("generator", {}).pop("generatedAt", None)
    doc.get("stats", {}).pop("durationMs", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
