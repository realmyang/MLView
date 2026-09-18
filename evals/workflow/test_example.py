"""Published native-Codex example stays grounded in its checked-in source."""
import importlib.util
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workflow_artifact", ROOT / "skills/mlview/scripts/artifact.py")
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


def test_native_example_structure_and_exact_source_snapshot():
    doc = json.loads((ROOT / "samples/configured_training.mlview.json").read_text())
    schema = json.loads((ROOT / "contracts/workflow.schema.json").read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    issues, hashes = artifact.validate(doc, ROOT)
    assert issues == []
    assert hashes == doc["verification"]["files"]
    assert doc["producer"] == {"kind": "host-llm", "host": "codex", "model": "gpt-5.6-sol"}
