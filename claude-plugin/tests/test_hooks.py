"""H8 — the PostToolUse / Stop hooks.

`claude-plugin/hooks/` did not exist: the plugin was entirely pull-based, so when
Claude edited a training file during a session nothing said the edit introduced
MLV101 and the user found out on the next manual `/mlview-issues`.

Everything below is a test of the DISCIPLINE, because that is the feature. A hook
that speaks on every edit gets turned off within a day, so the assertions are
mostly about staying quiet: silent on a non-Python edit, silent on a path outside
the project, silent when the finding set did not grow, silent when the wall-clock
budget expires, silent when `MLVIEW_HOOK=off`, and never - under any of those -
anything but exit 0, because exit 2 is what blocks a tool call.

Two layers:

* **In process** - the pure decisions (which paths matter, which hook speaks,
  what the diff prints) against `hook_core`.
* **Through the script** - the real `post_edit.py` and `stop_summary.py` driven as
  Claude Code drives them: a JSON payload on stdin, the hook's own environment,
  and the JSON object on stdout parsed back.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from plugin_support import PLUGIN_ROOT, REPO_ROOT, child_env

HOOKS_DIR = os.path.join(PLUGIN_ROOT, "hooks")
HOOKS_JSON = os.path.join(HOOKS_DIR, "hooks.json")
POST_EDIT = os.path.join(HOOKS_DIR, "post_edit.py")
STOP_SUMMARY = os.path.join(HOOKS_DIR, "stop_summary.py")

sys.path.insert(0, HOOKS_DIR)
import hook_core  # noqa: E402  (needs the sys.path line above)

#: The bad half of the pair. `StandardScaler` is fitted on the WHOLE feature matrix
#: before `train_test_split`, so the test set has seen the training statistics:
#: MLV101, high, confidence 0.95.
LEAK = """\
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

X = np.load("features.npy")
y = np.load("labels.npy")
scaler = StandardScaler()
X_all = scaler.fit_transform(X)
X_train, X_test, y_train, y_test = train_test_split(X_all, y, test_size=0.2, random_state=0)
model = LogisticRegression(random_state=0).fit(X_train, y_train)
print(model.score(X_test, y_test))
"""

#: The good half: the same program with the fit moved after the split. Measured at
#: **0 findings**, so the difference between the two files is exactly one finding -
#: which is what makes "the set grew" the thing under test rather than a count.
CLEAN = """\
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

X = np.load("features.npy")
y = np.load("labels.npy")
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=0)
scaler = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)
model = LogisticRegression(random_state=0).fit(X_train, y_train)
print(model.score(X_test, y_test))
"""


# ------------------------------------------------------------------- the manifest
def _manifest():
    with open(HOOKS_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_hooks_json_lives_in_the_conventional_directory():
    # `plugin.json` must NOT name it: CONTRACTS section 5 says a component path
    # field REPLACES the default scan, and `hooks/hooks.json` is that default.
    assert os.path.isfile(HOOKS_JSON)
    with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), "r",
              encoding="utf-8") as fh:
        assert "hooks" not in json.load(fh)


def test_the_manifest_has_the_shape_the_hooks_documentation_specifies():
    manifest = _manifest()
    assert set(manifest) == {"hooks"}, "the file is wrapped in a top-level 'hooks' key"
    events = manifest["hooks"]
    assert set(events) == {"PostToolUse", "Stop"}
    for event, groups in events.items():
        assert isinstance(groups, list) and groups, event
        for group in groups:
            handlers = group["hooks"]
            assert isinstance(handlers, list) and handlers
            for handler in handlers:
                assert handler["type"] == "command"
                assert isinstance(handler["command"], str) and handler["command"]
                # An outer bound on top of the script's own 3 s budget.
                assert isinstance(handler["timeout"], int) and 0 < handler["timeout"] <= 60


def test_the_post_tool_use_matcher_is_exactly_the_three_editing_tools():
    group = _manifest()["hooks"]["PostToolUse"][0]
    assert group["matcher"] == "Edit|Write|NotebookEdit"
    # A Stop hook fires on the event itself, so a matcher there would be noise.
    assert "matcher" not in _manifest()["hooks"]["Stop"][0]


def test_every_command_names_a_script_that_exists_under_the_plugin_root():
    for event, script in (("PostToolUse", "post_edit.py"), ("Stop", "stop_summary.py")):
        command = _manifest()["hooks"][event][0]["hooks"][0]["command"]
        assert "${CLAUDE_PLUGIN_ROOT}" in command, (
            "the plugin's own path is the only one that survives an install"
        )
        assert "/hooks/%s" % script in command
        assert os.path.isfile(os.path.join(HOOKS_DIR, script))
        # The same interpreter override `.mcp.json` uses, defaulting to the one
        # spelling Windows has out of the box (see test_plugin_manifest.py).
        assert "${MLVIEW_PYTHON:-python}" in command


def test_the_hooks_are_documented_where_a_reader_will_look():
    with open(os.path.join(PLUGIN_ROOT, "README.md"), "r", encoding="utf-8") as fh:
        readme = fh.read()
    assert "MLVIEW_HOOK" in readme, "the off switch has to be documented to be usable"
    assert "PostToolUse" in readme and "hooks/hooks.json" in readme


# --------------------------------------------------------------- which hook speaks
@pytest.mark.parametrize(
    "value,post,stop",
    [
        (None, True, False),      # the default: one line per edit, no turn summary
        ("", True, False),
        ("on", True, False),
        ("off", False, False),
        ("0", False, False),
        ("false", False, False),
        ("stop", False, True),
        ("both", True, True),
        ("all", True, True),
        ("nonsense", True, False),  # an unknown value is the default, never an error
    ],
)
def test_mlview_hook_selects_which_of_the_two_speaks(value, post, stop):
    env = {} if value is None else {"MLVIEW_HOOK": value}
    assert hook_core.hook_enabled("PostToolUse", env) is post
    assert hook_core.hook_enabled("Stop", env) is stop


# ------------------------------------------------------------- which paths matter
def test_only_python_under_the_project_directory_is_worth_re_analyzing(tmp_path):
    root = str(tmp_path)
    payload = lambda p: {"tool_input": {"file_path": p}}  # noqa: E731
    assert hook_core.relevant_paths(payload("train.py"), root) == [
        os.path.join(root, "train.py")
    ]
    # Everything the analyzer cannot read is an immediate exit 0.
    for name in ("README.md", "package.json", "train.pyc", "notes.txt"):
        assert hook_core.relevant_paths(payload(name), root) == []
    # And a path outside CLAUDE_PROJECT_DIR is refused whatever its suffix.
    outside = os.path.join(os.path.dirname(root), "elsewhere", "train.py")
    assert hook_core.relevant_paths(payload(outside), root) == []


def test_a_notebook_counts_only_when_notebooks_are_switched_on(tmp_path, monkeypatch):
    root = str(tmp_path)
    payload = {"tool_input": {"notebook_path": "explore.ipynb"}}
    monkeypatch.delenv("MLVIEW_INCLUDE_NOTEBOOKS", raising=False)
    assert hook_core.relevant_paths(payload, root) == []

    monkeypatch.setenv("MLVIEW_INCLUDE_NOTEBOOKS", "1")
    assert hook_core.relevant_paths(payload, root) == [os.path.join(root, "explore.ipynb")]

    # The checked-in half: `[paths] notebooks = true`, which is what a team sets.
    monkeypatch.delenv("MLVIEW_INCLUDE_NOTEBOOKS", raising=False)
    (tmp_path / ".mlview.toml").write_text("[paths]\nnotebooks = true\n", encoding="utf-8")
    assert hook_core.relevant_paths(payload, root) == [os.path.join(root, "explore.ipynb")]


def test_the_data_directory_is_never_inside_the_project(tmp_path, monkeypatch):
    root = str(tmp_path)
    for var in ("MLVIEW_DATA_DIR", "CLAUDE_PLUGIN_DATA"):
        monkeypatch.delenv(var, raising=False)
    resolved = hook_core.hook_data_dir(root)
    assert not hook_core.inside(root, resolved), (
        "with nothing naming a data directory the core would default to "
        "<project>/.mlview - a tool that writes into the repository on every edit"
    )
    # And when one IS named it is honoured, which is what shares the cache with
    # the MCP tools (.mcp.json maps MLVIEW_DATA_DIR to ${CLAUDE_PLUGIN_DATA}).
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "shared"))
    assert hook_core.hook_data_dir(root).endswith("/shared")
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "explicit"))
    assert hook_core.hook_data_dir(root).endswith("/explicit")


# ------------------------------------------------------------------------ the diff
def _issue(issue_id, code="MLV101", file="train.py", severity="high", confidence=0.9):
    return {
        "id": issue_id, "code": code, "severity": severity, "confidence": confidence,
        "title": "A finding about %s" % file, "suppressed": False,
        "loc": {"file": file, "line": 7},
    }


def test_nothing_is_said_when_the_issue_set_did_not_grow():
    current = [_issue("i:1"), _issue("i:2", code="MLV203", file="model.py")]
    ids = [i["id"] for i in current]
    keys = [hook_core.issue_key(i) for i in current]
    rows, reanchored, resolved = hook_core.diff_issues(current, ids, keys)
    assert rows == [] and reanchored == 0 and resolved == 0
    assert hook_core.build_context("PostToolUse", rows, reanchored, resolved, 2, {}) is None


def test_a_finding_whose_line_moved_is_counted_and_not_printed():
    # Issue ids are content-addressed, so an unchanged finding whose line shifted
    # comes back with a NEW id. Printing it would be a false alarm on every edit.
    before = [_issue("i:1")]
    after = [_issue("i:9")]  # same code, same file, new id
    rows, reanchored, resolved = hook_core.diff_issues(
        after, [i["id"] for i in before], [hook_core.issue_key(i) for i in before]
    )
    assert rows == []
    assert reanchored == 1
    assert resolved == 1
    assert hook_core.build_context("PostToolUse", rows, reanchored, resolved, 1, {}) is None


def test_a_genuinely_new_finding_is_reported_worst_first_and_capped_at_five():
    before = [_issue("i:0", code="MLV601", severity="low")]
    after = [before[0]] + [
        _issue("i:%d" % n, code="MLV1%02d" % n, file="f%d.py" % n,
               severity=("high" if n % 2 else "medium"))
        for n in range(1, 9)
    ]
    rows, reanchored, resolved = hook_core.diff_issues(
        after, [i["id"] for i in before], [hook_core.issue_key(i) for i in before]
    )
    assert len(rows) == 8
    context = hook_core.build_context("PostToolUse", rows, reanchored, resolved, 9, {})
    body = [line for line in context.splitlines() if line.startswith("  [")]
    assert len(body) == hook_core.MAX_ROWS, "at most five rows, whatever happened"
    assert all("[HIGH]" in line for line in body[:4]), "worst first"
    assert "and 3 more" in context
    assert "9 finding(s) in the project in total" in context


def test_the_summary_says_what_the_run_could_not_look_at():
    # The standing acceptance criterion: a hook that says "no new findings" about a
    # run which skipped three notebooks has reported a clean bill of health for
    # code it never read.
    graph = {
        "workspace": {"notebooksSkipped": 3, "filesFailed": 1},
        "stats": {"truncated": True},
    }
    context = hook_core.build_context("PostToolUse", [_issue("i:1")], 0, 0, 1, graph)
    assert "could not see everything here" in context
    assert "3 notebook(s) not analyzed" in context
    assert "1 file(s) failed to parse" in context
    assert "truncated" in context
    assert hook_core.coverage_line({"workspace": {"notebooksSkipped": 0}}) is None


def test_a_run_that_overshoots_the_budget_says_nothing_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "data"))
    # A zero budget is the abandoned-run case; the contract is silence, not a stall.
    assert hook_core.analyze_within_budget(str(tmp_path), False, budget=0.0) is None


# ------------------------------------------------------------- through the script
def _drive(script, payload, tmp_path, extra_env=None):
    """Run one hook exactly as Claude Code runs it: JSON on stdin, JSON on stdout."""
    env = child_env()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path / "project")
    env["MLVIEW_DATA_DIR"] = str(tmp_path / "data")
    env.pop("MLVIEW_HOOK", None)
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        shell=False,
        timeout=120,
    )
    return proc


def _post_payload(tmp_path, name="train.py"):
    return {
        "session_id": "test",
        "cwd": str(tmp_path / "project"),
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "project" / name)},
        "tool_response": {"type": "text", "text": "ok"},
    }


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "train.py").write_text(CLEAN, encoding="utf-8")
    return root


def test_the_first_run_warms_the_cache_in_silence(project, tmp_path):
    # There is nothing to diff against, so every finding would look new. The value
    # of that run is the warm cache the MCP tools then read for free.
    proc = _drive(POST_EDIT, _post_payload(tmp_path), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_an_edit_that_introduces_a_leak_is_reported_once(project, tmp_path):
    assert _drive(POST_EDIT, _post_payload(tmp_path), tmp_path).returncode == 0
    (project / "train.py").write_text(LEAK, encoding="utf-8")

    proc = _drive(POST_EDIT, _post_payload(tmp_path), tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    context = output["additionalContext"]
    assert "that edit added" in context
    assert "MLV101" in context
    assert "train.py" in context
    assert len([l for l in context.splitlines() if l.startswith("  [")]) <= hook_core.MAX_ROWS

    # And the SAME edit re-run says nothing: the set did not grow a second time.
    again = _drive(POST_EDIT, _post_payload(tmp_path), tmp_path)
    assert again.returncode == 0
    assert again.stdout.strip() == ""


def test_the_hook_never_writes_into_the_project(project, tmp_path):
    (project / "train.py").write_text(LEAK, encoding="utf-8")
    _drive(POST_EDIT, _post_payload(tmp_path), tmp_path)
    assert sorted(p.name for p in project.iterdir()) == ["train.py"], (
        "a tool that drops .mlview/ into somebody's repository on every edit is a "
        "tool people turn off"
    )


def test_a_non_python_edit_costs_nothing_and_says_nothing(project, tmp_path):
    proc = _drive(POST_EDIT, _post_payload(tmp_path, name="README.md"), tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
    # The immediate exit happens before any analysis, so no state file is written.
    assert not (tmp_path / "data" / "hook-state.json").exists()


def test_mlview_hook_off_disables_both_scripts(project, tmp_path):
    (project / "train.py").write_text(LEAK, encoding="utf-8")
    for script, payload in (
        (POST_EDIT, _post_payload(tmp_path)),
        (STOP_SUMMARY, {"hook_event_name": "Stop", "cwd": str(project)}),
    ):
        proc = _drive(script, payload, tmp_path, {"MLVIEW_HOOK": "off"})
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""


def test_a_malformed_payload_is_exit_0_and_silence(project, tmp_path):
    env = child_env()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["MLVIEW_DATA_DIR"] = str(tmp_path / "data")
    proc = subprocess.run(
        [sys.executable, POST_EDIT], input="not json at all", capture_output=True,
        text=True, cwd=REPO_ROOT, env=env, shell=False, timeout=60,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_the_stop_variant_summarises_a_turn_and_keeps_its_own_diff(project, tmp_path):
    stop = {"hook_event_name": "Stop", "cwd": str(project), "stop_reason": "end_turn"}
    both = {"MLVIEW_HOOK": "both"}
    assert _drive(STOP_SUMMARY, stop, tmp_path, both).stdout.strip() == ""  # first run

    (project / "train.py").write_text(LEAK, encoding="utf-8")
    # The PostToolUse hook speaks first; the Stop hook must still have its own news,
    # or turning the pair on would make each suppress the other.
    edit = _drive(POST_EDIT, _post_payload(tmp_path), tmp_path, both)
    assert edit.returncode == 0

    proc = _drive(STOP_SUMMARY, stop, tmp_path, both)
    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "Stop"
    assert "since the last summary" in output["additionalContext"]
    assert "MLV101" in output["additionalContext"]


def test_a_stop_hook_already_in_a_continuation_never_speaks_again(project, tmp_path):
    (project / "train.py").write_text(LEAK, encoding="utf-8")
    payload = {"hook_event_name": "Stop", "cwd": str(project), "stop_hook_active": True}
    proc = _drive(STOP_SUMMARY, payload, tmp_path, {"MLVIEW_HOOK": "stop"})
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_the_hook_leaves_no_bytecode_in_the_vendored_core(project, tmp_path):
    # Gate 9 (`tools/sync-core.py --check`) fails on a single __pycache__ under
    # claude-plugin/vendor, and these scripts import the core out of it.
    (project / "train.py").write_text(LEAK, encoding="utf-8")
    _drive(POST_EDIT, _post_payload(tmp_path), tmp_path)
    vendor = os.path.join(PLUGIN_ROOT, "vendor")
    if not os.path.isdir(vendor):
        pytest.skip("no vendored core in this checkout")
    residue = [
        os.path.join(base, name)
        for base, dirs, _files in os.walk(vendor)
        for name in dirs
        if name == "__pycache__"
    ]
    assert residue == [], residue
