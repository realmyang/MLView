"""Shared helpers for the scope tests (CONTRACTS 11.15).

Two documents are used throughout, and the difference matters:

* `golden()` - the **frozen** `contracts/graph.sample.json`. The parity battery
  is computed over it so a rule change can never redden the scope gate.
* `sample()` - a live analysis of `samples/vision_pipeline`. The measured demo
  figures (F2-A5, F2-A6) live here because they legitimately move when a rule
  changes.

Both are cached and shared; a test must treat them as read-only (`project()`
never mutates its input, which `test_project.py` asserts).
"""

from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from typing import Any, Dict, List

from core_support import REPO_ROOT, SAMPLE_PATH
from mlview.api import AnalyzeOptions, analyze_to_dict

SAMPLE_DIR = os.path.join(REPO_ROOT, "samples", "vision_pipeline")
CASES_PATH = os.path.join(REPO_ROOT, "contracts", "scope.cases.json")
EXPECTED_PATH = os.path.join(REPO_ROOT, "contracts", "scope.expected.json")

__all__ = ["SAMPLE_DIR", "CASES_PATH", "EXPECTED_PATH", "golden", "sample",
           "cases", "expected", "codes_of", "ids_of", "roles_of"]


def _read_json(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    with io.open(path, encoding=encoding) as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def golden() -> Dict[str, Any]:
    """The frozen golden document."""
    return _read_json(SAMPLE_PATH, "utf-8-sig")


@lru_cache(maxsize=1)
def sample() -> Dict[str, Any]:
    """A live, unscoped analysis of `samples/vision_pipeline`."""
    return analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,)))


@lru_cache(maxsize=1)
def cases() -> List[Dict[str, Any]]:
    return _read_json(CASES_PATH)["cases"]


@lru_cache(maxsize=1)
def expected() -> Dict[str, Dict[str, Any]]:
    return {c["name"]: c for c in _read_json(EXPECTED_PATH)["cases"]}


def codes_of(doc: Dict[str, Any]) -> set:
    """The distinct rule codes a document retains (suppressed excluded)."""
    return {i["code"] for i in doc["issues"] if not i.get("suppressed")}


def ids_of(items) -> List[str]:
    return [item["id"] for item in items]


def roles_of(doc: Dict[str, Any]) -> Dict[str, str]:
    return {n["id"]: n.get("viewRole") for n in doc["nodes"]}
