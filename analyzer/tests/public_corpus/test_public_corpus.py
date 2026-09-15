"""PUB-01 - the public-repository corpus, asserted.

Four groups of tests, and only the last needs the ~1.9 GB of clones:

* the **manifest and the adjudication record** are checked on every run, with
  no network and no corpus. They are data that gates a build, so a typo in
  them has to fail here rather than at 3 a.m. in the nightly.
* the **gate logic** is checked against synthetic reports, so the thing that
  decides whether a crash is a failure is itself covered.
* the **command line** is checked, because `.github/workflows/public-corpus.yml`
  is generated text: its `workflow_dispatch` `repos` input produced
  `public_corpus.py fetch --repo <names>`, argparse rejected the option after
  the subcommand, and the job's first step exited 2 every time anybody used the
  documented input (PUB2-10). A workflow line nobody can run is not a feature.
* the **corpus run** is skipped unless ``MLVIEW_PUBLIC_CORPUS_DIR`` points at a
  populated directory (``python tools/public_corpus.py fetch``). Set
  ``MLVIEW_PUBLIC_CORPUS_REPOS=nanoGPT,minGPT`` to run a subset, and
  ``MLVIEW_PUBLIC_CORPUS_MODES=local`` to skip the interprocedural pass.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL_PATH = os.path.join(REPO_ROOT, "tools", "public_corpus.py")

#: The thirteen repositories hardening round 2 added, and the shape each one
#: was added for. A corpus that grows by accident grows into a monoculture;
#: naming the reason here is what stops a later edit from dropping the only
#: gradient-boosting or classical-statistics entry without noticing.
ROUND_TWO = {
    "xgboost": "gradient boosting, native Booster API",
    "LightGBM": "gradient boosting, Dataset/train API",
    "statsmodels": "classical statistics and time series, no torch and no sklearn",
    "accelerate": "the negation_absent framework gate itself",
    "peft": "parameter-efficient fine-tuning over a frozen base model",
    "trl": "RLHF/SFT trainers as a Trainer subclass hierarchy",
    "optuna-examples": "a per-trial objective function, across frameworks",
    "cleanrl": "single-file reinforcement learning",
    "pytorch-tutorials": "the official literate .py tutorials",
    "mmdetection": "a registry + config framework built by string",
    "LLMs-from-scratch": "a hand-written GPT, .py beside .ipynb",
    "torchtune": "YAML-config LLM recipes",
    "handson-ml3": "a second notebook book: sklearn and Keras together",
}


def _load_tool():
    spec = importlib.util.spec_from_file_location("mlview_public_corpus", TOOL_PATH)
    assert spec is not None and spec.loader is not None, TOOL_PATH
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("mlview_public_corpus", module)
    spec.loader.exec_module(module)
    return module


pc = _load_tool()


def _corpus_dir():
    root = os.environ.get("MLVIEW_PUBLIC_CORPUS_DIR")
    if not root or not os.path.isdir(root):
        return None
    manifest = pc.load_manifest()
    have = [r for r in manifest["repos"]
            if os.path.isfile(os.path.join(root, r["name"], ".mlview-pinned-sha"))]
    return root if have else None


needs_corpus = pytest.mark.skipif(
    _corpus_dir() is None,
    reason="no public corpus: set MLVIEW_PUBLIC_CORPUS_DIR and run "
           "`python tools/public_corpus.py fetch`")


# ------------------------------------------------------------------ manifest
def test_manifest_loads_and_is_well_formed():
    manifest = pc.load_manifest()
    # The brief asked round 1 for 18-25 repositories; round 2 added thirteen
    # for the framework and domain shapes round 1 never reached. The ceiling is
    # the clone budget (~3 GB) rather than a taste, so it is generous and the
    # floor is what still makes the corpus mean anything.
    assert 18 <= len(manifest["repos"]) <= 45
    for repo in manifest["repos"]:
        assert repo["url"].startswith("https://github.com/"), repo["name"]
        assert repo["targets"], repo["name"]
        assert repo.get("license"), repo["name"]
        assert repo.get("domain"), repo["name"]
        for target in repo["targets"]:
            assert not target.startswith("/"), (repo["name"], target)
            assert ".." not in target.split("/"), (repo["name"], target)


def test_manifest_spans_the_framework_families():
    """A corpus that is all PyTorch measures one third of the product."""
    manifest = pc.load_manifest()
    families = {f for repo in manifest["repos"] for f in repo.get("frameworks", [])}
    for expected in ("torch", "sklearn", "keras", "tf", "hf", "lightning", "jax",
                     "xgboost", "lightgbm", "statsmodels"):
        assert expected in families, "no %s repo in the corpus" % expected


def test_manifest_keeps_every_round_two_shape():
    names = {repo["name"] for repo in pc.load_manifest()["repos"]}
    missing = sorted(set(ROUND_TWO) - names)
    assert not missing, "round-2 shapes dropped from the corpus: %s" % missing


def test_manifest_never_claims_a_vendored_repo():
    """Nothing in this corpus may be copied into the tree or a build artefact."""
    manifest = pc.load_manifest()
    for repo in manifest["repos"]:
        assert repo.get("redistribute") is False, repo["name"]
        assert not os.path.isdir(os.path.join(HERE, repo["name"])), \
            "%s must not be vendored under analyzer/tests/public_corpus" % repo["name"]


def test_adjudication_loads_and_every_verdict_cites_why():
    data = pc.load_adjudication()          # raises if a verdict is malformed
    verdicts = data["verdicts"]
    assert verdicts, "the adjudication record is empty"
    for key, row in verdicts.items():
        assert key.count("|") == 3, "key must be repo|CODE|file|symbol: %r" % key
        assert row["why"].strip(), key
        assert row.get("state") in ("open", "fixed"), key
        if row["verdict"] == "false-positive":
            assert row.get("guard", "").strip(), \
                "a false positive must name the guard that should have caught it: %s" % key


def test_adjudication_keys_match_the_manifest():
    manifest = pc.load_manifest()
    names = {repo["name"] for repo in manifest["repos"]}
    for key in pc.load_adjudication()["verdicts"]:
        assert key.split("|", 1)[0] in names, key


def test_medium_sample_rows_are_readable_and_addressed():
    """Medium is not gated, but a medium false positive still needs an address."""
    data = pc.load_adjudication()
    rows = data["mediumSample"]["rows"]
    names = {repo["name"] for repo in pc.load_manifest()["repos"]}
    assert rows
    for row in rows:
        assert row["key"].count("|") == 3, row["key"]
        assert row["key"].split("|", 1)[0] in names, row["key"]
        assert row["verdict"] in ("true-positive", "false-positive", "unsure")
        assert row["why"].strip(), row["key"]
        assert row["where"].strip(), row["key"]
        if row["verdict"] == "false-positive":
            assert row.get("guard", "").strip(), row["key"]
            assert row.get("repro", "").strip(), row["key"]


def test_graph_fidelity_section_judges_real_repos():
    """Requirement 1 is a picture, and a picture needs a human verdict."""
    data = pc.load_adjudication()
    names = {repo["name"] for repo in pc.load_manifest()["repos"]}
    repos = data["graphFidelity"]["repos"]
    assert len(repos) >= 5, "the brief asks for five repositories, judged"
    for row in repos:
        assert row["repo"] in names, row["repo"]
        assert row["verdict"].strip(), row["repo"]
        assert len(row["detail"]) > 120, row["repo"]


# ----------------------------------------------------------------- the gate
def _report(**run):
    base = {"repo": "r", "target": ".", "mode": "local", "exit": 0,
            "wallMs": 10, "traceback": False, "schemaErrors": [], "findings": []}
    base.update(run)
    return {"budgetSeconds": 60.0, "runs": [base]}


def test_gate_passes_a_clean_report():
    assert pc.check_report(_report(), {"verdicts": {}}).ok


@pytest.mark.parametrize("run,needle", [
    ({"traceback": True, "stderrNoise": ["boom"]}, "traceback"),
    ({"exit": 1}, "exit 1"),
    ({"exit": 3}, "exit 3"),
    ({"schemaErrors": ["nodes[3].parent does not resolve"]}, "schema/invariant"),
    ({"wallMs": 61_000}, "budget"),
    ({"error": "timed out after 240s"}, "timed out"),
])
def test_gate_blocks_on(run, needle):
    result = pc.check_report(_report(**run), {"verdicts": {}})
    assert not result.ok
    assert any(needle in line for line in result.blocking), result.blocking


_HIGH = {"code": "MLV101", "severity": "high", "file": "a.py",
         "repoFile": "a.py", "line": 3, "symbol": "s.fit"}


def test_gate_blocks_an_unadjudicated_high_finding():
    result = pc.check_report(_report(findings=[_HIGH]), {"verdicts": {}})
    assert not result.ok
    assert "NEW high finding" in result.blocking[0]


def test_gate_allows_an_adjudicated_true_positive():
    key = pc.finding_key("r", "MLV101", "a.py", "s.fit")
    adj = {"verdicts": {key: {"verdict": "true-positive", "why": "real leak",
                              "state": "open"}}}
    assert pc.check_report(_report(findings=[_HIGH]), adj).ok


def test_gate_lists_but_does_not_block_a_known_open_false_positive():
    key = pc.finding_key("r", "MLV101", "a.py", "s.fit")
    adj = {"verdicts": {key: {"verdict": "false-positive", "why": "correct code",
                              "guard": "value identity", "state": "open"}}}
    result = pc.check_report(_report(findings=[_HIGH]), adj)
    assert result.ok
    assert len(result.known) == 1
    assert not pc.check_report(_report(findings=[_HIGH]), adj, strict=True).ok


def test_gate_blocks_a_fixed_false_positive_that_came_back():
    key = pc.finding_key("r", "MLV101", "a.py", "s.fit")
    adj = {"verdicts": {key: {"verdict": "false-positive", "why": "correct code",
                              "guard": "value identity", "state": "fixed"}}}
    result = pc.check_report(_report(findings=[_HIGH]), adj)
    assert not result.ok
    assert "REGRESSION" in result.blocking[0]


def test_gate_notices_a_false_positive_that_has_gone_away():
    key = pc.finding_key("r", "MLV101", "a.py", "s.fit")
    adj = {"verdicts": {key: {"verdict": "false-positive", "why": "correct code",
                              "guard": "value identity", "state": "open"}}}
    result = pc.check_report(_report(), adj)
    assert result.ok
    assert result.stale and "GONE" in result.stale[0]
    assert not pc.check_report(_report(), adj, strict=True).ok


def test_gate_ignores_medium_findings():
    medium = dict(_HIGH, severity="medium")
    assert pc.check_report(_report(findings=[medium]), {"verdicts": {}}).ok


def test_gate_reports_a_finding_ip_dropped():
    """11.36 sells `ip` as a widening; a finding that simply vanishes is news."""
    report = {"budgetSeconds": 60.0, "runs": [
        dict(_report()["runs"][0], mode="local",
             findings=[dict(_HIGH, severity="medium")]),
        dict(_report()["runs"][0], mode="ip", findings=[]),
    ]}
    result = pc.check_report(report, {"verdicts": {}})
    assert result.ok                      # listed, not fatal
    assert any("DROPPED" in line for line in result.known), result.known
    assert not pc.check_report(report, {"verdicts": {}}, strict=True).ok


# ------------------------------------------------------------ the command line
@pytest.mark.parametrize("argv", [
    ["--repo", "nanoGPT", "check", "--report", "<missing>"],
    ["check", "--repo", "nanoGPT", "--report", "<missing>"],
])
def test_repo_selector_is_accepted_either_side_of_the_subcommand(argv, tmp_path,
                                                                 capsys):
    """PUB2-10. The workflow generates the second spelling; it used to exit 2.

    Both spellings must reach the same place: a clean "no report here" with
    exit 2, rather than argparse's `unrecognized arguments`.
    """
    missing = str(tmp_path / "nope.json")
    assert pc._main([a.replace("<missing>", missing) for a in argv]) == 2
    err = capsys.readouterr().err
    assert "no report at" in err
    assert "unrecognized arguments" not in err
    assert "Traceback" not in err


def test_check_on_a_malformed_report_is_a_message_not_a_traceback(tmp_path,
                                                                  capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pc._main(["check", "--report", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "not a valid report" in err
    assert "Traceback" not in err


def test_run_honours_a_repo_selector_after_the_subcommand(tmp_path):
    """The `run` step of the workflow needs the selector too.

    With it missing, a dispatch that fetched one repository then planned all
    thirty-seven, and every unfetched target came back as a blocking
    `target directory missing` - so the subset run could not pass either.
    """
    out = tmp_path / "report.json"
    empty = tmp_path / "corpus"
    empty.mkdir()
    assert pc._main(["run", "--repo", "nanoGPT", "--corpus-dir", str(empty),
                     "--out", str(out), "--modes", "local", "--no-notebooks"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["runs"], "a plan of nothing would pass this test vacuously"
    assert {row["repo"] for row in report["runs"]} == {"nanoGPT"}


def test_a_selector_given_on_both_sides_is_merged_not_overwritten():
    """CONTRACTS 11.58 A2 - the trap this shape has.

    A subparser parses into a namespace of its own which argparse then copies
    over the main one, so a subparser copy that shares a `dest` erases the
    top-level value, and an `append` action there starts from an empty list
    rather than from what the top level collected: `--repo a fetch --repo b`
    would have analyzed `b` alone and said nothing about `a`.
    """
    args = pc.build_parser().parse_args(["--repo", "a", "fetch", "--repo", "b,c"])
    names, _, _ = pc._selectors(args)
    assert names == ["a", "b", "c"]


def test_a_single_valued_selector_takes_the_value_nearest_the_subcommand():
    """Which side wins, not how the winner is spelled.

    `_selectors` absolutises the corpus directory (that is the fix run
    19dc4d4 shipped, so a relative `--corpus-dir` still reaches the analyzer
    children), and a drive-less path is not absolute on Windows: `/before`
    comes back as `D:\\before` there. Comparing against the literal asserted
    POSIX, not precedence, so the expectation goes through `os.path.abspath`
    too - on Linux and macOS it is the identity, on Windows it is the host's
    own spelling.
    """
    parse = pc.build_parser().parse_args
    before = pc._selectors(parse(["--corpus-dir", "/before", "fetch"]))[1]
    both = pc._selectors(parse(["--corpus-dir", "/before", "fetch",
                                "--corpus-dir", "/after"]))[1]
    assert (before, both) == (os.path.abspath("/before"),
                              os.path.abspath("/after"))


def test_the_workflow_and_the_cli_are_checked_against_each_other():
    """PUB2-10's regression gate lives in the doc gate, not here: this asserts
    the seam it needs - `build_parser()` is public and `_main` is written in
    terms of it, so `scripts/doc_numbers.py` check 19 can parse the command
    lines `.github/workflows/public-corpus.yml` generates."""
    parser = pc.build_parser()
    assert parser.prog == "public_corpus"
    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--repos", "nanoGPT"])   # a typo still fails


# -------------------------------------------------------------- the corpus
@needs_corpus
def test_public_corpus_is_clean_and_matches_the_adjudication(tmp_path):
    root = _corpus_dir()
    manifest = pc.load_manifest()
    only = [n for n in (os.environ.get("MLVIEW_PUBLIC_CORPUS_REPOS") or "").split(",")
            if n]
    modes = tuple(m for m in (os.environ.get("MLVIEW_PUBLIC_CORPUS_MODES")
                              or "local,ip").split(",") if m)
    report = pc.run_corpus(manifest, root, str(tmp_path / "graphs"), only, modes,
                           with_notebooks=True, jobs=4)
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    result = pc.check_report(report, pc.load_adjudication())
    assert result.ok, "\n".join(result.blocking)
