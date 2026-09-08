"""CI-ADOPT at the MCP boundary: `changedSince`, `baseline`, and the degradations.

The rule these tests exist to hold is the one the whole feature stands on:
**a failure degrades to "unattributed, showing everything" with a note**, never to
an error and never to an empty list. A tool that reports nothing because git was
missing is worse than one that reports everything, because the empty answer looks
like good news.

They also pin the delegation. `mlview_adopt` implements no attribution of its own —
it calls the analyzer's `mlview.adopt.cli_glue.apply_to_graph`, the same function
`mlview issues --changed-since` calls — so an MCP answer and a CLI answer cannot
diverge on the same repo and the same revision.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import mlview_adopt as adopt
import mlview_payloads as payloads
import mlview_workspace as workspace
from plugin_support import synthetic_graph

LEAKY = """\
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


def build(X, y):
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    return train_test_split(Xs, y, test_size=0.2)
"""

SECOND_LEAK = """\


def build_again(X, y):
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    return train_test_split(Xs, y, test_size=0.3)
"""


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=False)


def _has_git() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True,
                              check=False).returncode == 0
    except OSError:  # pragma: no cover - git is present on every supported runner
        return False


@pytest.fixture()
def repo(tmp_path):
    """A one-file git repo with a committed leak, so HEAD is a real revision."""
    if not _has_git():
        pytest.skip("git is not on PATH")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pipeline.py").write_text(LEAKY, encoding="utf-8")
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)
    _git(["add", "-A"], root)
    commit = _git(["commit", "-q", "-m", "first"], root)
    if commit.returncode != 0:  # pragma: no cover - a misconfigured git
        pytest.skip("git commit failed: %s" % commit.stderr.strip())
    return root


# ------------------------------------------------------------------ delegation
def test_the_vendored_core_supports_attribution():
    assert adopt.supported(), (
        "claude-plugin/vendor/mlview has no mlview.adopt — run tools/sync-core.py"
    )


def test_the_module_delegates_and_implements_nothing_itself():
    source = open(os.path.join(os.path.dirname(adopt.__file__), "mlview_adopt.py"),
                  encoding="utf-8").read()
    assert "cli_glue.apply_to_graph" in source, "attribution must go through the analyzer"
    for invented in ("git diff", "unified=0", "def classify"):
        assert invented not in source, (
            "%r suggests the plugin re-implemented attribution; there is one analyzer"
            % invented
        )


# --------------------------------------------------------------- the happy path
def test_changed_since_lists_only_what_the_change_introduced(repo):
    every = workspace.load_attributed(str(repo))["graph"]
    assert len(every["issues"]) >= 1, "the fixture must have a finding to attribute"

    # Nothing has changed since HEAD, so nothing touches the change.
    unchanged = workspace.load_attributed(str(repo), changed_since="HEAD")
    assert unchanged["graph"]["issues"] == []
    note = " ".join(unchanged["notes"])
    assert "not shown" in note and "Re-run without --changed-only" in note, note

    # Now introduce a second leak and attribute again.
    (repo / "pipeline.py").write_text(LEAKY + SECOND_LEAK, encoding="utf-8")
    changed = workspace.load_attributed(str(repo), changed_since="HEAD")
    issues = changed["graph"]["issues"]
    assert issues, "a finding on an added line must survive --changed-only"
    assert {i["change"] for i in issues} <= {"new", "touched"}
    assert any(i["change"] == "new" for i in issues), (
        "a finding whose own line is inside an added hunk is `new`: %s"
        % [(i["code"], i["change"], i["loc"]["line"]) for i in issues]
    )


def test_the_attributed_document_is_written_beside_the_plain_one_never_over_it(repo):
    plain = workspace.load_graph(str(repo))
    attributed = workspace.load_attributed(str(repo), changed_since="HEAD")
    assert attributed["graphPath"] != plain["graphPath"]
    assert attributed["graphPath"].endswith(".attributed.json")
    # `mlview_analyze`'s graphPath must still hold the FULL document.
    with open(plain["graphPath"], encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert len(on_disk["issues"]) == len(plain["graph"]["issues"]) >= 1


def test_attribution_is_never_cached_because_git_state_is_not_a_file_signature(repo):
    first = workspace.load_attributed(str(repo), changed_since="HEAD")
    assert first["cached"] is False
    # Move HEAD without touching a single byte of any source file.
    (repo / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "second"], repo)
    again = workspace.load_attributed(str(repo), changed_since="HEAD~1")
    assert again["cached"] is False
    assert " ".join(again["notes"]) != "", "a second attribution must be recomputed"


def test_a_baseline_marks_findings_instead_of_deleting_them(repo, tmp_path):
    from mlview.adopt import baseline as baseline_mod
    from mlview.api import AnalyzeOptions, analyze

    graph = analyze(AnalyzeOptions(paths=(str(repo),)))
    target = tmp_path / "baseline.json"
    baseline_mod.write_baseline(graph, str(target))

    loaded = workspace.load_attributed(str(repo), baseline=str(target))
    issues = loaded["graph"]["issues"]
    assert issues, "baselining marks findings; it never deletes them from the document"
    assert all(i.get("baselined") for i in issues)

    payload = payloads.issues_payload(loaded["graph"], extra_notes=loaded["notes"])
    assert payload["issues"] == [], "a baselined finding is not a row"
    assert payload["baselinedCount"] == len(issues)
    assert payload["countBySeverity"] == {"low": 0, "medium": 0, "high": 0}


# --------------------------------------------------------------- degradations
def test_a_directory_that_is_not_a_repo_shows_everything_and_says_why(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "pipeline.py").write_text(LEAKY, encoding="utf-8")
    loaded = workspace.load_attributed(str(root), changed_since="HEAD")
    assert loaded["graph"]["issues"], "never an empty list because git could not answer"
    note = " ".join(loaded["notes"]).lower()
    assert "every finding" in note or "not attributed" in note or "unattributed" in note, (
        "the degradation must be stated, not silent: %r" % loaded["notes"]
    )


def test_a_revision_that_does_not_exist_degrades_the_same_way(repo):
    loaded = workspace.load_attributed(str(repo), changed_since="no-such-rev")
    assert loaded["graph"]["issues"], "a bad revision must not empty the list"
    assert loaded["notes"], "and it must say so"


def test_an_unreadable_baseline_is_ignored_loudly(repo, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    loaded = workspace.load_attributed(str(repo), baseline=str(broken))
    assert loaded["graph"]["issues"], "an unreadable baseline forgives nothing"
    assert any("baseline" in n.lower() for n in loaded["notes"])


def test_the_unsupported_note_names_both_parameters_and_the_consequence():
    note = adopt.unsupported_note("origin/main", "b.json")
    assert "changedSince=origin/main" in note and "baseline=b.json" in note
    assert "EVERY finding" in note
    assert "pip install --upgrade mlview" in note


# ------------------------------------------------------------------- payloads
def test_a_row_carries_its_change_class_only_on_an_attributed_run():
    graph = synthetic_graph(nodes=10, edges=10, issues=4)
    plain = payloads.issues_payload(graph)
    assert all("change" not in row for row in plain["issues"])
    assert "baselinedCount" not in plain

    # Alternate, so both classes reach a VISIBLE row whichever issues the synthetic
    # document happens to mark suppressed.
    for index, issue in enumerate(graph["issues"]):
        issue["change"] = "new" if index % 2 else "touched"
    attributed = payloads.issues_payload(graph)
    assert {row["change"] for row in attributed["issues"]} == {"new", "touched"}


def test_the_tool_signature_carries_both_optional_parameters():
    import inspect

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "server"))
    import mlview_mcp  # noqa: PLC0415 - imports the SDK, so only this test pays for it

    tool = getattr(mlview_mcp.mlview_issues, "__wrapped__", mlview_mcp.mlview_issues)
    while hasattr(tool, "__wrapped__"):
        tool = tool.__wrapped__
    signature = inspect.signature(tool)
    for name in ("changedSince", "baseline"):
        assert name in signature.parameters, "mlview_issues must accept %s" % name
        assert signature.parameters[name].default is None, "%s must be optional" % name
    doc = inspect.getdoc(tool) or ""
    assert "changedSince" in doc and "baseline" in doc, (
        "the model reads the docstring; an undocumented parameter is an unused one"
    )
