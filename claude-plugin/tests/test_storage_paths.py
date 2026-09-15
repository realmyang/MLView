"""C8 — the plugin never writes into the project it was asked to read.

The core half of C8 landed first: `mlview.core.cache.cache_dir_for` defaults to the
user's own cache directory keyed by the workspace path, so `python -m mlview analyze .`
leaves the analyzed tree untouched. The MCP host then undid it for itself — `cache_dir()`
was `<data_dir>/cache` and `data_dir()` was `<project>/.mlview`, created eagerly by
`os.makedirs` — so merely resolving a path inside the server created `.mlview/` inside
somebody's repository, and `shared_cache_dir()` exported that directory as
`MLVIEW_CACHE_DIR` for the analysis that followed. A marketplace install masked it
(`.mcp.json` names `${CLAUDE_PLUGIN_DATA}`), but `claude --plugin-dir` — the route
`docs/VALIDATION.md` Session C tells a validator to take — did not.

What is asserted here:

* no environment at all: the parse cache is the core's user-level directory, and
  nothing under the project is created;
* `CLAUDE_PLUGIN_DATA` alone is honoured, like `hooks/hook_core.hook_data_dir`;
* a named data directory still gives the hooks and the tools ONE shared parse cache
  (CONTRACTS 11.41 C3), which is the reason this host computes the path at all;
* `MLVIEW_CACHE_DIR` still wins over both.
"""

from __future__ import annotations

import os
import sys

import pytest

from plugin_support import SERVER_DIR

sys.path.insert(0, SERVER_DIR)

import mlview_workspace as workspace  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """An analyzed project with no MLView environment of any kind."""
    root = tmp_path / "project"
    root.mkdir()
    (root / "train.py").write_text("import torch\n", encoding="utf-8")
    monkeypatch.setenv("MLVIEW_PROJECT_DIR", str(root))
    for var in ("MLVIEW_DATA_DIR", "CLAUDE_PLUGIN_DATA", "MLVIEW_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    return root


def _listing(root):
    return sorted(os.listdir(str(root)))


def test_the_parse_cache_is_never_inside_the_analyzed_project(project):
    from mlview.core.cache import cache_dir_for

    cache = workspace.cache_dir()
    assert cache == cache_dir_for(workspace.project_dir()).replace("\\", "/")
    assert not cache.startswith(workspace.project_dir() + "/"), cache
    assert _listing(project) == ["train.py"], "resolving a path created something"


def test_shared_cache_dir_exports_that_same_outside_directory(project):
    with workspace.shared_cache_dir():
        exported = os.environ["MLVIEW_CACHE_DIR"]
    assert exported == workspace.cache_dir()
    assert not exported.startswith(workspace.project_dir() + "/")
    assert "MLVIEW_CACHE_DIR" not in os.environ, "the variable is scoped to the call"
    assert _listing(project) == ["train.py"]


def test_resolving_an_out_path_does_not_create_a_directory_in_the_project(project):
    """`resolve_out` answers a containment QUESTION; it must not have a side effect."""
    with pytest.raises(ValueError):
        workspace.resolve_out("../../../../etc/passwd.html")
    assert _listing(project) == ["train.py"]
    # the default target is still inside the data directory, and writing there is
    # what creates it
    assert workspace.resolve_out(None).endswith("/.mlview/report.html")
    assert os.path.isdir(os.path.join(str(project), ".mlview"))


def test_claude_plugin_data_alone_is_honoured(project, tmp_path, monkeypatch):
    """A `--plugin-dir` session exports CLAUDE_PLUGIN_DATA without MLVIEW_DATA_DIR."""
    store = tmp_path / "plugin-data"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(store))
    assert workspace.named_data_dir() == workspace.data_dir()
    assert workspace.data_dir().endswith("/plugin-data")
    assert workspace.cache_dir() == workspace.data_dir() + "/cache"
    assert _listing(project) == ["train.py"]


def test_a_named_data_directory_keeps_one_shared_parse_cache(project, tmp_path,
                                                             monkeypatch):
    """CONTRACTS 11.41 C3: the hook warms the cache the MCP tools then read."""
    store = tmp_path / "shared"
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(store))
    assert workspace.cache_dir() == workspace.data_dir() + "/cache"

    sys.path.insert(0, os.path.join(os.path.dirname(SERVER_DIR), "hooks"))
    import hook_core

    assert hook_core.hook_data_dir(str(project)) == workspace.data_dir()


def test_an_explicit_cache_directory_still_wins(project, tmp_path, monkeypatch):
    monkeypatch.setenv("MLVIEW_DATA_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("MLVIEW_CACHE_DIR", str(tmp_path / "explicit"))
    assert workspace.cache_dir().endswith("/explicit")
