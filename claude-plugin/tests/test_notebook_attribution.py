"""HOST-5 — `includeNotebooks` survives `changedSince` and `baseline`.

`mlview_issues` used to branch like this::

    if changedSince or baseline:
        loaded = load_attributed(path, changedSince, baseline)   # no notebooks
    else:
        loaded = load_graph(path, include_notebooks=bool(includeNotebooks))

`load_attributed` had no `include_notebooks` parameter at all, so an agent that
asked for *"what did this PR introduce, notebooks included"* got an answer from a
run that had not opened one notebook — byte-identical to the answer it would have
got without the flag, with nothing in the payload saying so. That is the failure
mode the tool's own docstring warns the model about ("a short list from a run that
read none of the notebooks is not a clean project"), enforced on the caller and
then committed by the server.

Two things are asserted here, and the second is the one that keeps the fix honest:

1. **The flag reaches the analysis.** With attribution on, the notebooks are read
   (`notebooksSkipped` 0, the `notebook_analyzed` diagnostic present), and under
   `baseline` — which does not filter by hunk — the notebook's findings are listed.
   This is CLI parity: `mlview issues --include-notebooks --changed-since` has
   always analyzed both.

2. **Where attribution genuinely cannot carry a notebook finding, it says so.** A
   notebook finding is anchored in the generated module `.mlview/notebooks/<n>.py`,
   which git does not track, so `--changed-only` (always on at this boundary) drops
   it however new the `.ipynb` is — measured: 3 findings with `--changed-since HEAD`
   and 0 with `--changed-only`, in the CLI as much as here. Threading the flag and
   stopping there would have swapped a silent drop for a quieter one, so the drop is
   counted and stated in the `note` the model reads.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess

import pytest

import mlview_adopt as adopt
import mlview_payloads as payloads
import mlview_workspace as workspace

NOTEBOOK = {
    "cells": [
        {
            "cell_type": "code", "execution_count": 1, "metadata": {}, "outputs": [],
            "source": [
                "import pandas as pd\n",
                "from sklearn.preprocessing import StandardScaler\n",
                "from sklearn.model_selection import train_test_split\n",
            ],
        },
        {
            "cell_type": "code", "execution_count": 2, "metadata": {}, "outputs": [],
            "source": [
                "df = pd.read_csv('data.csv')\n",
                "X = df.drop(columns=['y'])\n",
                "y = df['y']\n",
            ],
        },
        {
            "cell_type": "code", "execution_count": 3, "metadata": {}, "outputs": [],
            "source": [
                "scaler = StandardScaler()\n",
                "Xs = scaler.fit_transform(X)\n",
                "X_train, X_test, y_train, y_test = train_test_split(Xs, y)\n",
            ],
        },
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 5,
}


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
def nb_repo(tmp_path, monkeypatch):
    """A git repo whose only ML code is a notebook, committed so HEAD is real."""
    if not _has_git():
        pytest.skip("git is not on PATH")
    root = tmp_path / "proj"
    root.mkdir()
    with open(root / "leak.ipynb", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(NOTEBOOK, fh)
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "t"], root)
    _git(["add", "-A"], root)
    if _git(["commit", "-q", "-m", "first"], root).returncode != 0:  # pragma: no cover
        pytest.skip("git commit failed")
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(root))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "data"))
    workspace._CACHE.clear()
    yield root
    workspace._CACHE.clear()


def _kinds(graph):
    return [d.get("kind") for d in graph.get("diagnostics", [])]


# ------------------------------------------------------------------ the wiring
def test_load_attributed_takes_the_flag_and_forwards_it():
    """A signature check, so the parameter cannot be dropped again silently."""
    params = inspect.signature(workspace.load_attributed).parameters
    assert "include_notebooks" in params
    assert params["include_notebooks"].default is False
    assert "include_notebooks" in inspect.signature(adopt.analyze_attributed).parameters
    assert "include_notebooks=bool(include_notebooks)" in inspect.getsource(
        adopt.analyze_attributed
    ), "analyze_attributed accepts the flag but never reaches AnalyzeOptions with it"


def test_mlview_issues_forwards_the_flag_on_the_attributed_branch():
    import mlview_mcp

    fn = getattr(mlview_mcp.mlview_issues, "fn", mlview_mcp.mlview_issues)
    source = inspect.getsource(fn)
    attributed = source.split("if changedSince or baseline:", 1)[1].split("else:", 1)[0]
    assert "include_notebooks=bool(includeNotebooks)" in attributed, (
        "the changedSince/baseline branch drops includeNotebooks again"
    )
    assert "Ignored with\n            changedSince" not in source, (
        "the docstring still tells the model the flag is ignored"
    )


# ------------------------------------------------------------- the flag is real
def test_attribution_reads_the_notebooks_when_asked(nb_repo):
    loaded = workspace.load_attributed(str(nb_repo), changed_since="HEAD",
                                       include_notebooks=True)
    graph = loaded["graph"]
    assert graph["workspace"]["notebooksSkipped"] == 0
    assert graph["workspace"]["filesAnalyzed"] == 1
    assert "notebook_analyzed" in _kinds(graph)


def test_without_the_flag_attribution_still_skips_them(nb_repo):
    graph = workspace.load_attributed(str(nb_repo), changed_since="HEAD")["graph"]
    assert graph["workspace"]["notebooksSkipped"] == 1
    assert "notebook_analyzed" not in _kinds(graph)


def test_the_two_runs_are_no_longer_the_same_answer(nb_repo):
    """The measured shape of the defect: identical bytes with and without the flag."""
    without = workspace.load_attributed(str(nb_repo), changed_since="HEAD")
    with_nb = workspace.load_attributed(str(nb_repo), changed_since="HEAD",
                                        include_notebooks=True)
    assert json.dumps(without["graph"]["workspace"], sort_keys=True) != json.dumps(
        with_nb["graph"]["workspace"], sort_keys=True
    )
    assert without["notes"] != with_nb["notes"]


def test_under_a_baseline_the_notebook_findings_are_actually_listed(nb_repo, tmp_path):
    """`baseline` does not filter by hunk, so the flag pays off in findings."""
    from mlview.adopt import baseline as baseline_mod

    empty = tmp_path / "baseline.json"
    baseline_mod.write_baseline(_empty_graph(tmp_path), str(empty))
    loaded = workspace.load_attributed(str(nb_repo), baseline=str(empty),
                                       include_notebooks=True)
    codes = {issue["code"] for issue in loaded["graph"]["issues"]}
    assert "MLV101" in codes, (
        "a notebook leak must survive baseline attribution: %s" % sorted(codes)
    )


def _empty_graph(tmp_path):
    """An analysis of an empty directory — a baseline that forgives nothing."""
    from mlview.api import AnalyzeOptions, analyze

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir(exist_ok=True)
    return analyze(AnalyzeOptions(paths=(str(empty_dir),)))


# --------------------------------------------------- and what it cannot do, said
def test_the_dropped_notebook_findings_are_reported_not_swallowed(nb_repo):
    loaded = workspace.load_attributed(str(nb_repo), changed_since="HEAD",
                                       include_notebooks=True)
    assert loaded["graph"]["issues"] == [], (
        "nothing in the diff touches the generated module, so the filter drops them"
    )
    note = " ".join(loaded["notes"])
    assert "includeNotebooks was honoured" in note, note
    assert "leak.ipynb" in note, "the note must name the notebook that was dropped"
    assert adopt.NOTEBOOK_MODULE_DIR in note, "and where the finding was anchored"
    assert "not a statement that the notebooks are clean" in note.lower()


def test_the_note_reaches_the_model_facing_payload(nb_repo):
    loaded = workspace.load_attributed(str(nb_repo), changed_since="HEAD",
                                       include_notebooks=True)
    payload = payloads.issues_payload(
        loaded["graph"], graph_path=loaded["graphPath"],
        extra_notes=list(loaded["notes"]),
    )
    assert payload["issues"] == []
    assert "includeNotebooks was honoured" in payload.get("note", ""), payload.get("note")


def test_no_note_when_nothing_was_dropped(nb_repo):
    """The note is a measurement, not a disclaimer printed on every run."""
    loaded = workspace.load_attributed(str(nb_repo), include_notebooks=True)
    assert loaded["graph"]["issues"], "an unattributed run lists the notebook findings"
    assert not any("includeNotebooks was honoured" in n for n in loaded["notes"])


def test_the_note_is_absent_when_notebooks_were_never_read(nb_repo):
    loaded = workspace.load_attributed(str(nb_repo), changed_since="HEAD")
    assert not any("includeNotebooks" in n for n in loaded["notes"]), loaded["notes"]


def test_a_notebook_free_project_never_grows_the_note(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "pipeline.py").write_text(
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.model_selection import train_test_split\n"
        "\n"
        "\n"
        "def build(X, y):\n"
        "    Xs = StandardScaler().fit_transform(X)\n"
        "    return train_test_split(Xs, y, test_size=0.2)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(root))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "data"))
    loaded = workspace.load_attributed(str(root), include_notebooks=True)
    assert not any("includeNotebooks was honoured" in n for n in loaded["notes"])
    assert os.path.isdir(str(root))
