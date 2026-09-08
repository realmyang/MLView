"""Shared helpers for the core tests: paths, the tmp-workspace writer and
the contract validator from `contracts/validate_sample.py`.

Imported as `core_support` - a unique name, because two `conftest.py` files
on `sys.path` (this one and `tests/rules/conftest.py`) shadow each other
depending on collection order. `conftest.py` re-exports everything here, so
either import spelling works.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Dict, Mapping, Optional, Sequence


from mlview.api import AnalyzeOptions, analyze_full, analyze_to_dict  # noqa: F401

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONTRACTS_DIR = os.path.join(REPO_ROOT, "contracts")
SCHEMA_PATH = os.path.join(CONTRACTS_DIR, "graph.schema.json")
SAMPLE_PATH = os.path.join(CONTRACTS_DIR, "graph.sample.json")
FIXTURES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "fixtures"))


def _load_validator():
    path = os.path.join(CONTRACTS_DIR, "validate_sample.py")
    spec = importlib.util.spec_from_file_location("mlview_contract_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def validate(doc) -> Sequence[str]:
    """Every contract error in a document (empty means valid)."""
    return VALIDATOR.validate_graph(doc, schema_path=SCHEMA_PATH)


def write_files(root: str, files: Mapping[str, str]) -> str:
    for relpath, text in files.items():
        target = os.path.join(root, relpath.replace("/", os.sep))
        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return root.replace("\\", "/")

__all__ = ["REPO_ROOT", "CONTRACTS_DIR", "SCHEMA_PATH", "SAMPLE_PATH",
           "FIXTURES", "VALIDATOR", "validate", "write_files"]
