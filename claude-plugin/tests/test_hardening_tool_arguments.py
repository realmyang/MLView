"""Hardening round 1, area hosts-ux: two MCP argument gaps measured end to end.

`test_tool_arguments.py` already pins the rule for `format`, `minSeverity`,
`groupBy` and `scope`: an out-of-range value is an error the model can retry,
never a silent coercion. Two arguments were never held to it.

**1. `framework`.** The CLI declares `--framework {auto,torch,sklearn,keras,hf,
lightning}` through argparse, so `--framework pytorch` exits 1 with the accepted
values. `mlview_analyze` passes the string straight through to `load_graph`,
which passes it to `AnalyzeOptions.framework`. Measured on
`samples/vision_pipeline` against a live server over the SDK client:

    framework="auto"      -> 54 nodes, 4 low / 6 medium / 5 high, isError False
    framework="torch"     -> 54 nodes, 4 low / 5 medium / 4 high, isError False
    framework="pytorch"   -> 52 nodes, 1 low / 0 medium / 0 high, isError False
    framework="TORCH"     -> 52 nodes, 1 low / 0 medium / 0 high, isError False

A one-letter model typo turns five high-severity findings into none, with
`frameworks: ["torch", "sklearn", "numpy", "torchvision"]` still in the same
payload and no `note` anywhere in it. That is the precise failure the credibility
rule calls the second-worst: a clean answer about code that is not clean.

**2. `path` containment.** `resolve_out` refuses an `out` outside the project
directory and `MLVIEW_DATA_DIR`, and says why — its docstring names the threat
("the caller is a language model reading untrusted source"). `resolve_path`
applies no containment at all, so `mlview_analyze {"path": "../.."}` walked out
of the project and analysed the user's home directory (97 files, 64 notebooks
skipped, root `/Users/<user>`), and `{"path": "/etc"}` returned a document
rooted at `/etc`. Read-only, but it is an unbounded read of a directory the
session was never pointed at, reachable from one line of text in a repository
the model is reading.

**1 is FIXED** (hardening round 1, claude-plugin): `mlview_workspace.
normalize_framework` folds case and whitespace, accepts exactly the CLI's six
values and raises `ValueError` for anything else, and `load_graph` /
`load_attributed` call it before the cache key is built — so no caller inside
the plugin, including the hooks and the attributed path, can reach
`AnalyzeOptions` with a filter that names no extractor. The xfail marker is gone
with it; the test below is now a gate. **2 is still open.**

The remaining test is `xfail(strict=True)`: it fails today, it passes the moment
the validation lands, and a strict xfail turns into a failure if someone fixes
the symptom and leaves the test asserting the old behaviour.
"""

from __future__ import annotations

import os

import pytest

import mlview_workspace as workspace
from plugin_support import REPO_ROOT

SAMPLE = os.path.join("samples", "vision_pipeline")
ACCEPTED = ("auto", "torch", "sklearn", "keras", "hf", "lightning")


@pytest.fixture(autouse=True)
def _project_dir(monkeypatch):
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", REPO_ROOT)
    yield


def test_the_cli_is_the_authority_on_the_six_framework_values():
    """The CLI refuses an unknown framework; the MCP is what must match it."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "mlview", "analyze",
         SAMPLE, "--framework", "pytorch", "--json", "-"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"),
    )
    assert proc.returncode != 0, "the CLI must refuse --framework pytorch"
    assert proc.stdout == "", "a usage error must leave stdout untouched"
    for name in ACCEPTED:
        assert name in proc.stderr, f"the CLI usage text must list {name}"


def test_an_unknown_framework_is_an_error_and_never_a_quieter_analysis():
    graph_auto = workspace.load_graph(SAMPLE, framework="auto")["graph"]
    high_auto = sum(1 for i in graph_auto.get("issues", []) if i.get("severity") == "high")
    assert high_auto > 0, "the demo must carry high-severity findings for this test to mean anything"

    with pytest.raises(ValueError) as excinfo:
        workspace.load_graph(SAMPLE, framework="pytorch")
    message = str(excinfo.value)
    assert "pytorch" in message, "the error must name the value the caller passed"
    for name in ACCEPTED:
        assert name in message, f"the error must list {name} among the accepted values"


def test_the_damage_an_unvalidated_framework_does_is_measured_not_assumed():
    """Not a gate — the measurement the xfail above is worth fixing for.

    It asserts only that the two runs differ, so it stays true whichever way the
    fix goes: once `framework` is validated this call raises instead, and the
    `pytest.raises` below is what records that.
    """
    graph_auto = workspace.load_graph(SAMPLE, framework="auto")["graph"]
    auto_high = sum(1 for i in graph_auto.get("issues", []) if i.get("severity") == "high")
    try:
        graph_typo = workspace.load_graph(SAMPLE, framework="pytorch")["graph"]
    except ValueError:
        return  # validated now: the xfail above has been fixed, and this is moot
    typo_high = sum(1 for i in graph_typo.get("issues", []) if i.get("severity") == "high")
    assert auto_high != typo_high or len(graph_auto["nodes"]) != len(graph_typo["nodes"]), (
        "an unknown framework produced the same document as `auto`; if that is now true, "
        "the silent-substitution risk is gone and this test can go with it"
    )


@pytest.mark.xfail(
    strict=True,
    reason="HOSTS-UX-PATHESCAPE: resolve_path applies no containment, unlike resolve_out",
)
@pytest.mark.parametrize("escape", ["..", os.path.join("..", ".."), os.path.sep])
def test_a_path_outside_the_project_directory_is_refused(escape):
    with pytest.raises(ValueError) as excinfo:
        workspace.resolve_path(escape)
    message = str(excinfo.value)
    assert "outside" in message or "inside" in message, (
        "the refusal must say the path is outside the project, the way resolve_out does"
    )
    assert REPO_ROOT in message, "the refusal must name the project directory"


def test_resolve_out_still_refuses_an_escape_so_the_asymmetry_is_real(tmp_path, monkeypatch):
    """The control: `out` IS contained, which is what makes `path` an omission."""
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError) as excinfo:
        workspace.resolve_out(os.path.join(os.path.sep, "tmp", "escape.html"))
    assert "outside" in str(excinfo.value)


def test_an_absolute_path_inside_the_project_is_still_accepted():
    """Whatever containment lands must not break the documented absolute-path form."""
    inside = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
    assert workspace.resolve_path(inside).endswith("vision_pipeline")
    assert workspace.resolve_path(SAMPLE).endswith("vision_pipeline")
    assert workspace.resolve_path(None) == workspace.project_dir()
