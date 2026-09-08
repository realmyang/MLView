"""MLV-R2-106 — a model-supplied `out` path may never escape the permitted roots.

`mlview_open_diagram` writes ~270 KB of HTML to `out` and, outside the tests,
hands the result straight to `os.startfile`. The caller is a language model that
has been reading untrusted third-party source, so the same containment obligation
CONTRACTS section 4 puts on the webview's `openLocation` ("a webview must never be
able to talk the extension into opening ~/.ssh/id_rsa") applies here.

The permitted roots are the project directory and `MLVIEW_DATA_DIR`; everything
else is a `ValueError`, which `visible_errors` turns into a `ToolError` whose text
reaches the model so it can retry with a real path.
"""

from __future__ import annotations

import os
import sys

import pytest

from plugin_support import SERVER_DIR

sys.path.insert(0, SERVER_DIR)

import mlview_mcp  # noqa: E402


@pytest.fixture
def roots(tmp_path, monkeypatch):
    project = tmp_path / "project"
    data = tmp_path / "plugin-data"
    project.mkdir()
    data.mkdir()
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(project))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(data))
    return project, data


def test_the_default_target_is_inside_the_data_directory(roots):
    _, data = roots
    target = mlview_mcp.resolve_out(None)
    assert target.startswith(str(data).replace("\\", "/"))
    assert target.endswith("/report.html")


def test_a_relative_path_resolves_inside_the_project(roots):
    project, _ = roots
    target = mlview_mcp.resolve_out(".mlview/report.html")
    assert target == (str(project).replace("\\", "/") + "/.mlview/report.html")


def test_an_absolute_path_inside_the_data_directory_is_allowed(roots):
    _, data = roots
    wanted = os.path.join(str(data), "explicit.html")
    assert mlview_mcp.resolve_out(wanted) == wanted.replace("\\", "/")


@pytest.mark.parametrize(
    "escape",
    [
        "../../../../Users/realm/AppData/Local/Temp/mlview_escape.html",
        r"..\..\..\evil.html",
        "sub/../../outside.html",
    ],
)
def test_dot_dot_traversal_is_refused(roots, escape):
    with pytest.raises(ValueError) as excinfo:
        mlview_mcp.resolve_out(escape)
    message = str(excinfo.value)
    assert "out must stay inside" in message, message
    assert "MLVIEW_DATA_DIR" in message, message


def test_an_unrelated_absolute_path_is_refused(roots):
    with pytest.raises(ValueError):
        mlview_mcp.resolve_out("C:/Windows/Temp/mlview_escape.html")
    with pytest.raises(ValueError):
        mlview_mcp.resolve_out("/etc/mlview_escape.html")


def test_a_unc_path_is_refused(roots):
    with pytest.raises(ValueError):
        mlview_mcp.resolve_out(r"\server\share\mlview_escape.html")


def test_a_sibling_directory_sharing_a_prefix_is_not_inside(tmp_path, monkeypatch):
    """`/proj` must not accept `/proj-evil` — a prefix match is not containment."""
    project = tmp_path / "proj"
    sibling = tmp_path / "proj-evil"
    project.mkdir()
    sibling.mkdir()
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(project))
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(project / ".mlview"))
    with pytest.raises(ValueError):
        mlview_mcp.resolve_out(str(sibling / "report.html"))


def test_the_project_root_itself_is_a_permitted_parent(roots):
    project, _ = roots
    target = mlview_mcp.resolve_out(str(project / "report.html"))
    assert target == (str(project).replace("\\", "/") + "/report.html")
