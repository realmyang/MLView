"""Schema currency and the golden `--demo` document."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from core_support import SAMPLE_PATH, SCHEMA_PATH, validate
from scope_support import SAMPLE_DIR
from mlview import api
from mlview.api import AnalyzeOptions, analyze_to_dict


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def test_shipped_schema_is_byte_identical_to_contracts():
    assert read_bytes(api.schema_path()) == read_bytes(SCHEMA_PATH)


def test_shipped_sample_is_byte_identical_to_contracts():
    assert read_bytes(api.sample_path()) == read_bytes(SAMPLE_PATH)


def test_schema_subcommand_prints_the_contract_schema():
    proc = _run(["schema"])
    assert proc.returncode == 0
    assert proc.stdout == read_bytes(SCHEMA_PATH)


def test_demo_emits_the_golden_sample_byte_identically():
    proc = _run(["analyze", "--demo", "--json", "-"])
    assert proc.returncode == 0
    assert proc.stdout == read_bytes(SAMPLE_PATH)


def test_golden_sample_still_validates():
    with open(SAMPLE_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert validate(doc) == []


def test_emitted_document_validates_against_the_schema(analyze_ws):
    doc = analyze_ws({"m.py": ("import torch\n"
                               "import torch.nn as nn\n"
                               "model = nn.Linear(2, 2)\n"
                               "torch.save(model.state_dict(), 'm.pt')\n")})
    assert validate(doc) == []
    assert doc["schemaVersion"] == "1.0"
    assert doc["generator"]["name"] == "mlview"
    assert len(doc["generator"]["rendererSha"]) == 64


def test_stages_are_always_all_eight(analyze_ws):
    doc = analyze_ws({"m.py": "x = 1\n"})
    assert len(doc["stages"]) == 8


def _run(args):
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "mlview"] + args,
                          capture_output=True, env=env)


# ------------------------------------------------ scoped views (CONTRACTS 11.3)
def test_view_is_absent_from_an_unscoped_document():
    """The key that keeps `--demo` byte-identical to the golden."""
    doc = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,)))
    assert "view" not in doc
    assert all("viewRole" not in n for n in doc["nodes"])


def test_a_scoped_document_carries_view_and_still_validates():
    doc = analyze_to_dict(AnalyzeOptions(paths=(SAMPLE_DIR,), scope="stage:train"))
    assert validate(doc) == []
    assert doc["view"]["scope"] == "stage:train"
    assert doc["schemaVersion"] == "1.0", "the schema version does not move"


def test_neither_new_property_is_required_in_either_schema_copy():
    for path in (SCHEMA_PATH, api.schema_path()):
        with open(path, encoding="utf-8") as fh:
            schema = json.load(fh)
        assert "view" in schema["properties"]
        assert "view" not in schema["required"]
        assert "viewRole" in schema["$defs"]["Node"]["properties"]
        assert "viewRole" not in schema["$defs"]["Node"]["required"]
        assert schema["properties"]["schemaVersion"]["const"] == "1.0"
        for name, definition in schema["$defs"].items():
            assert "view" not in definition.get("required", []), name
            assert "viewRole" not in definition.get("required", []), name


def test_the_view_definition_matches_the_contract():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        view = json.load(fh)["$defs"]["View"]
    assert view["required"] == ["scope", "label", "depth", "counts", "of", "hidden",
                                "resolvedTo"]
    assert view["additionalProperties"] is False
    assert set(view["properties"]) == {"scope", "label", "depth", "counts", "of",
                                       "hidden", "resolvedTo", "ambiguous", "empty"}
