"""Shared fixtures for the Claude Code plugin tests.

The helpers live in `plugin_support.py`, imported by name — NOT from `conftest`.
The analyzer's own suites put two different `conftest.py` files on `sys.path`, and
only the first imported wins that module name, so importing helpers from
`conftest` breaks as soon as the suites are collected together.
"""

from __future__ import annotations

import os
import sys

# Never leave bytecode behind in claude-plugin/vendor: these tests import the
# vendored core in-process, and a `__pycache__` tree there would ship with the
# plugin. The spawned servers get the same flag from plugin_support.child_env().
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO_ROOT, "claude-plugin")
SERVER_DIR = os.path.join(PLUGIN_ROOT, "server")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

for _path in (SERVER_DIR, TESTS_DIR, os.path.join(REPO_ROOT, "analyzer", "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from plugin_support import (  # noqa: E402,F401  re-exported for convenience
    PLUGIN_ROOT as _PLUGIN_ROOT,
    REPO_ROOT as _REPO_ROOT,
    corpus_path,
    synthetic_graph,
)
