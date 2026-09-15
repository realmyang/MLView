"""Session-wide test hygiene for the analyzer suite.

One fixture, and it exists because of C8. The fact cache's default directory is
now the **user's** cache directory keyed by the workspace path, which is right
for a person analysing a project and wrong for a test suite: every `tmp_path`
workspace is a new key, so one run of this suite left **848** sidecar
directories under `~/Library/Caches/mlview` on the machine C8 was written on.
They are small and harmless and they are still somebody's home directory.

`XDG_CACHE_HOME` rather than `MLVIEW_CACHE_DIR`, deliberately: the former is
read by `core.cache.user_cache_root`, so the **default** path is still the one
under test - `cache_dir_for` walks exactly the branch it walks in production,
only rooted somewhere the operating system will clean up. Naming
`MLVIEW_CACHE_DIR` would take the override branch instead and leave the default
untested by every test that does not think about the cache at all.

A test that needs a different answer overrides it with `monkeypatch`, which wins
over anything set here; `tests/core/test_cache.py` does exactly that in both
directions.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _cache_home_outside_the_users_home(tmp_path_factory):
    """Root the default fact-cache directory in the session's tmp dir."""
    previous = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(tmp_path_factory.mktemp("xdg-cache"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = previous
