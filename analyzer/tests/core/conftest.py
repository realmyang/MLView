"""Fixtures for the core tests; the helpers live in `core_support`.

**Import the helpers as `core_support`, not as `conftest`:**

    from core_support import FIXTURES, validate

`tests/core/` and `tests/rules/` both put a `conftest.py` on `sys.path`, and
only the first one imported wins the name `conftest`. The names are
re-exported below, but `core_support` is unambiguous in every collection
order.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from core_support import (  # noqa: F401 - re-exported for `from conftest import ...`
    CONTRACTS_DIR,
    FIXTURES,
    REPO_ROOT,
    SAMPLE_PATH,
    SCHEMA_PATH,
    VALIDATOR,
    validate,
    write_files,
)
from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict


@pytest.fixture
def make_workspace(tmp_path):
    """Write `{relpath: source}` into a tmp dir and return its path."""
    counter = {"n": 0}

    def _make(files: Mapping[str, str], name: Optional[str] = None) -> str:
        counter["n"] += 1
        root = tmp_path / (name or "ws%d" % counter["n"])
        root.mkdir(parents=True, exist_ok=True)
        return write_files(str(root), files)

    return _make


@pytest.fixture
def analyze_ws(make_workspace):
    """Write a workspace, analyze it, and return the emitted document."""

    def _analyze(files: Mapping[str, str], **kwargs) -> Dict:
        root = make_workspace(files)
        return analyze_to_dict(AnalyzeOptions(paths=(root,), **kwargs))

    return _analyze


@pytest.fixture
def analyze_ir(make_workspace):
    """Write a workspace and return the full AnalysisResult (graph + IR)."""

    def _analyze(files: Mapping[str, str], **kwargs):
        root = make_workspace(files)
        return analyze_full(AnalyzeOptions(paths=(root,), **kwargs))

    return _analyze
