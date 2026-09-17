"""NB - the plugin half: `includeNotebooks` on the tools, and `/mlview`'s wording.

Three things are asserted here, and each of them is a way the feature could ship
looking finished and still be useless:

1. **The flag reaches the analyzer, and its absence is byte-identical.** A tool
   argument that is accepted and then dropped is worse than no argument: the
   caller gets a confident answer about code that was never read.
2. **`mlview_issues` takes it too.** `mlview_analyze` alone would report
   `notebooksSkipped: 0` and a full lane summary while the very next call listed
   no finding inside any notebook - the "clean bill of health from a blind run"
   the roadmap's framing names as the product's core failure mode.
3. **The command file says what a notebook run cannot know.** Locations name the
   generated module rather than the `.ipynb`, and cell execution order is not
   recoverable from the file at all. A model that quotes `.mlview/notebooks/x.py:17`
   at a user who has a notebook open has technically answered and actually failed.
"""

from __future__ import annotations

import json
import os

import pytest

import mlview_workspace as workspace
from plugin_support import PLUGIN_ROOT

NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Leaky notebook\n"]},
        {
            "cell_type": "code",
            "execution_count": 1,
            "metadata": {},
            "outputs": [],
            "source": [
                "import pandas as pd\n",
                "from sklearn.preprocessing import StandardScaler\n",
                "from sklearn.model_selection import train_test_split\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": 2,
            "metadata": {},
            "outputs": [],
            "source": [
                "df = pd.read_csv('data.csv')\n",
                "X = df.drop(columns=['y'])\n",
                "y = df['y']\n",
            ],
        },
        {
            "cell_type": "code",
            "execution_count": 3,
            "metadata": {},
            "outputs": [],
            "source": [
                "scaler = StandardScaler()\n",
                "Xs = scaler.fit_transform(X)\n",
                "X_train, X_test, y_train, y_test = train_test_split(Xs, y)\n",
            ],
        },
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}


@pytest.fixture()
def notebook_project(tmp_path, monkeypatch):
    """A project whose only ML code is a notebook - the case NB exists for."""
    project = tmp_path / "project"
    project.mkdir()
    with open(project / "leak.ipynb", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(NOTEBOOK, fh)
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(project))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "data"))
    workspace._CACHE.clear()
    yield str(project)
    workspace._CACHE.clear()


def _kinds(graph):
    return [d.get("kind") for d in graph.get("diagnostics", [])]


def test_without_the_flag_a_notebook_project_is_honestly_empty(notebook_project):
    graph = workspace.load_graph(notebook_project)["graph"]
    assert graph["workspace"]["filesAnalyzed"] == 0
    assert graph["workspace"]["notebooksSkipped"] == 1
    assert "notebook_skipped" in _kinds(graph)
    assert "notebook_analyzed" not in _kinds(graph)
    assert graph["issues"] == []


def test_with_the_flag_the_notebook_is_read_and_says_what_it_did(notebook_project):
    graph = workspace.load_graph(notebook_project, include_notebooks=True)["graph"]
    assert graph["workspace"]["filesAnalyzed"] == 1
    assert graph["workspace"]["notebooksSkipped"] == 0
    assert "notebook_analyzed" in _kinds(graph)

    analyzed = [d for d in graph["diagnostics"] if d["kind"] == "notebook_analyzed"]
    assert len(analyzed) == 1, "one row per notebook - the host counts these"
    assert analyzed[0]["file"] == "leak.ipynb", "the row names the NOTEBOOK, not the module"
    assert "execution_count" in analyzed[0]["message"]

    codes = {issue["code"] for issue in graph["issues"]}
    assert "MLV101" in codes, "fit-before-split is the flagship notebook defect"


def test_every_notebook_finding_carries_its_cell(notebook_project):
    """The host re-anchors a squiggle onto a cell from exactly this evidence row."""
    graph = workspace.load_graph(notebook_project, include_notebooks=True)["graph"]
    leak = next(i for i in graph["issues"] if i["code"] == "MLV101")
    # `Loc` is frozen, so the location names the generated module...
    assert leak["loc"]["file"].startswith(".mlview/notebooks/")
    assert leak["loc"]["file"].endswith("leak.py")
    # ...and the cell mapping rides in the evidence, in the format the VS Code
    # host parses (vscode-extension/src/notebooks.ts CELL_EVIDENCE_RE).
    details = [e["detail"] for e in leak["evidence"]]
    assert any("leak.ipynb cell " in d and ", line " in d for d in details), details


def test_the_flag_is_part_of_the_answer_not_a_filter_on_it(notebook_project):
    """Same sources, same signature, two different documents - and neither is cached as the other."""
    plain = workspace.load_graph(notebook_project)
    with_nb = workspace.load_graph(notebook_project, include_notebooks=True)
    assert plain["cached"] is False and with_nb["cached"] is False
    assert plain["graph"]["workspace"]["filesAnalyzed"] == 0
    assert with_nb["graph"]["workspace"]["filesAnalyzed"] == 1
    assert workspace.load_graph(notebook_project)["cached"] is True
    assert workspace.load_graph(notebook_project, include_notebooks=True)["cached"] is True


def test_both_reporting_tools_accept_the_flag_and_pass_it_down():
    """A signature check, so neither tool can quietly stop forwarding it."""
    import inspect

    import mlview_mcp

    for name in ("mlview_analyze", "mlview_issues"):
        fn = getattr(mlview_mcp, name)
        target = getattr(fn, "fn", fn)
        params = inspect.signature(target).parameters
        assert "includeNotebooks" in params, name
        assert params["includeNotebooks"].default is False, name
        source = inspect.getsource(target)
        assert "include_notebooks=bool(includeNotebooks)" in source, (
            "%s accepts includeNotebooks but never forwards it" % name
        )


# ------------------------------------------------------------------ the command file
def _command(name):
    with open(os.path.join(PLUGIN_ROOT, "commands", name), encoding="utf-8") as fh:
        return fh.read()


def test_authored_mlview_inspects_notebooks_directly():
    body = _command("mlview.md")
    assert "notebooks" in body and "active Claude model" in body
    assert "legacy static\nanalyzer first" in body


def test_mlview_does_not_use_legacy_notebook_skip_counts():
    body = _command("mlview.md")
    assert "notebooksSkipped" not in body


def test_canonical_skill_records_notebook_cell_evidence():
    with open(os.path.join(PLUGIN_ROOT, "skills", "mlview", "references", "WORKFLOW_CONTRACT.md"), encoding="utf-8") as fh:
        body = fh.read()
    assert "zero-based" in body and "cell" in body
