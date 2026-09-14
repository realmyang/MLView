"""PUB-01 - the public-repository corpus, asserted.

Three groups of tests, and only the third needs the ~1.8 GB of clones:

* the **manifest and the adjudication record** are checked on every run, with
  no network and no corpus. They are data that gates a build, so a typo in
  them has to fail here rather than at 3 a.m. in the nightly.
* the **gate logic** is checked against synthetic reports, so the thing that
  decides whether a crash is a failure is itself covered.
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
    assert 18 <= len(manifest["repos"]) <= 30, "the brief asks for 18-25 repos"
    for repo in manifest["repos"]:
        assert repo["url"].startswith("https://github.com/"), repo["name"]
        assert repo["targets"], repo["name"]
        assert repo.get("license"), repo["name"]
        for target in repo["targets"]:
            assert not target.startswith("/"), (repo["name"], target)
            assert ".." not in target.split("/"), (repo["name"], target)


def test_manifest_spans_the_framework_families():
    """A corpus that is all PyTorch measures one third of the product."""
    manifest = pc.load_manifest()
    families = {f for repo in manifest["repos"] for f in repo.get("frameworks", [])}
    for expected in ("torch", "sklearn", "keras", "tf", "hf", "lightning", "jax"):
        assert expected in families, "no %s repo in the corpus" % expected


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
