"""C8 — the plugin never writes into the project it was asked to read.

C8 has two halves and they land separately. The core half moves
``mlview.core.cache.cache_dir_for`` off ``<root>/.mlview/cache`` and onto the user's
own cache directory, keyed by the workspace path, so a bare ``python -m mlview
analyze .`` leaves the analyzed tree untouched. The host half is this file's subject:
the MCP server used to undo that for itself — ``cache_dir()`` was ``<data_dir>/cache``
and ``data_dir()`` was ``<project>/.mlview``, created eagerly by ``os.makedirs`` — so
merely *resolving* a path inside the server created ``.mlview/`` inside somebody's
repository, and ``shared_cache_dir()`` then exported that directory as
``MLVIEW_CACHE_DIR`` for the analysis that followed. A marketplace install masked it
(``.mcp.json`` names ``${CLAUDE_PLUGIN_DATA}``), but ``claude --plugin-dir`` — the
route ``docs/VALIDATION.md`` Session C tells a validator to take — did not.

What is asserted here:

* with no environment at all, this host **defers to the core** rather than deciding
  for itself, and creates nothing under the project (unconditional: it is the host's
  own obligation and it holds whatever the core's default is today);
* and that the directory the core hands back is outside the project — the C8 clause
  itself, which is skipped with a reason naming the unlanded half while the core
  still answers ``<root>/.mlview/cache``;
* ``CLAUDE_PLUGIN_DATA`` alone is honoured, like ``hooks/hook_core.hook_data_dir``;
* a named data directory still gives the hooks and the tools ONE shared parse cache
  (CONTRACTS 11.41 C3), which is the reason this host computes the path at all;
* ``MLVIEW_CACHE_DIR`` still wins over both.
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


def test_with_no_host_directory_the_parse_cache_is_the_cores_own_answer(project):
    """The host stops deciding. Whatever the core's default is, this is it.

    This is the assertion that keeps the defect from coming back by a different
    route: the old code computed ``<data_dir>/cache`` here, which is a SECOND
    opinion about where a cache belongs, and it disagreed with the core the moment
    C8 moved it.
    """
    from mlview.core.cache import cache_dir_for

    assert workspace.cache_dir() == cache_dir_for(workspace.project_dir()).replace(
        "\\", "/"
    )
    assert _listing(project) == ["train.py"], "resolving a path created something"


def test_the_parse_cache_is_never_inside_the_analyzed_project(project):
    """C8's clause. Skipped, with the reason, while the core half is unlanded."""
    from mlview.core.cache import cache_dir_for

    if cache_dir_for(str(project)).replace("\\", "/").startswith(
        workspace.project_dir() + "/"
    ):
        pytest.skip(
            "C8's core half is not in this tree yet: mlview.core.cache.cache_dir_for "
            "still defaults to <root>/.mlview/cache. This host already defers to it "
            "(see the test above), so this gate turns green with no change here."
        )
    cache = workspace.cache_dir()
    assert not cache.startswith(workspace.project_dir() + "/"), cache
    assert _listing(project) == ["train.py"]


def test_shared_cache_dir_exports_whatever_cache_dir_answered(project):
    with workspace.shared_cache_dir():
        exported = os.environ["MLVIEW_CACHE_DIR"]
    assert exported == workspace.cache_dir()
    assert "MLVIEW_CACHE_DIR" not in os.environ, "the variable is scoped to the call"


def test_resolving_an_out_path_does_not_create_a_directory_in_the_project(project):
    """``resolve_out`` answers a containment QUESTION; it must not have a side effect."""
    with pytest.raises(ValueError):
        workspace.resolve_out("../../../../etc/passwd.html")
    assert _listing(project) == ["train.py"]
    # The default target is still inside the data directory, and WRITING there is
    # what creates it — so the create=True call below is the first thing that may.
    assert workspace.resolve_out(None).endswith("/.mlview/report.html")
    assert os.path.isdir(os.path.join(str(project), ".mlview"))


def test_claude_plugin_data_alone_is_honoured(project, tmp_path, monkeypatch):
    """A ``--plugin-dir`` session exports CLAUDE_PLUGIN_DATA without MLVIEW_DATA_DIR."""
    store = tmp_path / "plugin-data"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(store))
    assert workspace.named_data_dir() == workspace.data_dir()
    assert workspace.data_dir().endswith("/plugin-data")
    assert workspace.cache_dir() == workspace.data_dir() + "/cache"
    assert _listing(project) == ["train.py"]


def test_a_named_data_directory_keeps_one_shared_parse_cache(
    project, tmp_path, monkeypatch
):
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


def test_the_storage_module_is_importable_without_the_analyzer_core():
    """The seam the split is along: ``mlview_storage`` takes no core import at module
    scope, so a host that has not run the bootstrap can still resolve a path."""
    import mlview_storage

    assert mlview_storage.__doc__
    source = open(mlview_storage.__file__, encoding="utf-8").read()
    head = source.split("def project_dir", 1)[0]
    assert "from mlview" not in head and "import mlview" not in head, (
        "a module-scope analyzer import would make this module unimportable before "
        "mlview_mcp's bootstrap has run"
    )
