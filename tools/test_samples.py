"""The sample diagrams stay grounded in their checked-in sources.

One table, SAMPLES, lists the samples. A sample is a folder `samples/<name>/` and the diagram
`samples/<name>.mlview.json` beside it. Git tracks exactly the diagrams the table names, so a new
diagram fails here until it has a row. Each diagram is valid under the schema and validates in full
against the repository root: no error, and the hashes it records equal the files' hashes. Its
producer equals the table's host and model, and the codes of the helper's warnings equal the
table's. Every file it cites, lists as inspected, names as an entrypoint or fingerprints lies under
`samples/<name>/`, so an edit outside that folder cannot make the diagram stale.
"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow_artifact", ROOT / "skills/mlview/scripts/artifact.py")
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)

# name -> the producer's host and model, and the codes of the warnings the helper prints for the diagram.
# A row leaves out "model" when the diagram records no model.
SAMPLES = {
    "configured_training": {"host": "claude-code", "model": "claude-opus-5-5", "warnings": frozenset()},
    "image_classification": {"host": "claude-code", "model": "claude-opus-5-5", "warnings": frozenset()},
    "keras_tfdata": {"host": "claude-code", "model": "claude-opus-5-5", "warnings": frozenset()},
    "notebook_classifier": {"host": "claude-code", "model": "claude-opus-5-5", "warnings": frozenset()},
}
# Variables that point git at another repository, index, object store or work tree.
GIT_REDIRECTS = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX",
})


def diagram_path(name: str) -> str:
    return f"samples/{name}.mlview.json"


def diagram(name: str) -> dict:
    return json.loads((ROOT / diagram_path(name)).read_text(encoding="utf-8"))


def tracked_diagrams() -> set[str] | None:
    """The `*.mlview.json` files git tracks under samples/, or None when the tree is not the top of a git checkout."""
    environment = {name: value for name, value in os.environ.items() if name not in GIT_REDIRECTS}

    def git(*arguments: str) -> str:
        done = subprocess.run(["git", *arguments], cwd=ROOT, env=environment, capture_output=True, check=True)
        return done.stdout.decode("utf-8")

    try:
        # In a copy inside some other checkout git answers for that checkout and lists nothing here.
        if not os.path.samefile(git("rev-parse", "--show-toplevel").strip(), ROOT):
            return None
        paths = git("ls-files", "-z", "--", "samples").split("\0")
        return {path for path in paths if path.endswith(".mlview.json")}
    except (OSError, subprocess.CalledProcessError):
        return None


def test_git_tracks_exactly_the_diagrams_of_the_table():
    tracked = tracked_diagrams()
    if tracked is None:
        pytest.skip("the tree is not the top of a git checkout")
    assert tracked == {diagram_path(name) for name in SAMPLES}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_sample_has_its_diagram_and_its_folder(name):
    assert (ROOT / diagram_path(name)).is_file()
    assert (ROOT / "samples" / name).is_dir()


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_diagram_is_schema_valid_and_validates_in_full_against_the_repository_root(name):
    doc = diagram(name)
    schema = json.loads((ROOT / "contracts/workflow.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    warnings: list = []
    errors, hashes = artifact.validate(doc, ROOT, warnings=warnings)
    assert errors == []
    assert hashes == doc["verification"]["files"]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_producer_equals_the_table(name):
    row = SAMPLES[name]
    expected = {"kind": "host-llm", "host": row["host"]}
    if "model" in row:
        expected["model"] = row["model"]
    assert diagram(name)["producer"] == expected


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_diagram_gives_the_warning_codes_of_the_table(name):
    warnings: list = []
    artifact.validate(diagram(name), ROOT, warnings=warnings)
    assert {warning["code"] for warning in warnings} == SAMPLES[name]["warnings"]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_each_diagram_cites_and_fingerprints_only_files_of_its_folder(name):
    doc = diagram(name)
    folder = f"samples/{name}/"
    paths = {
        "evidence": {item["file"] for item in doc["evidence"]},
        "coverage.inspectedFiles": set(doc["coverage"]["inspectedFiles"]),
        "request.entrypoints": set(doc["request"].get("entrypoints", [])),
        "verification.files": set(doc["verification"]["files"]),
    }
    outside = {key: sorted(path for path in found if not path.startswith(folder)) for key, found in paths.items()}
    assert {key: found for key, found in outside.items() if found} == {}
