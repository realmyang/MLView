"""The generated test documents of contracts/conformance/documents are exactly the listed set.

The validator tests read these documents by name. This module pins the set itself: the
committed files equal a fresh run of the generator, the folder holds nothing else, and each
document has the size it is listed with. `generate.py --check` is also run on changed copies,
to show that it reports a changed, a missing and an extra file.

It also pins which `*.mlview.json` files the tree holds: git tracks these eight, and every other
one is a sample diagram `samples/<name>.mlview.json` beside its folder `samples/<name>/`
(tools/test_samples.py pins the samples). The source text of each suite that reads whole documents
names the eight. A test document that is added to the tree fails here until it is listed here and
named in each suite.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ROOT / "contracts" / "conformance" / "documents"
WORKSPACE = DOCUMENTS / "workspace"
GENERATOR = DOCUMENTS / "generate.py"

# name -> (steps, connections, phases, findings)
SIZES = {
    "d01-minimal": (4, 3, 3, 0),
    "d02-notebook": (7, 6, 4, 3),
    "d03-two-files": (10, 9, 3, 1),
    "d04-loop": (12, 15, 5, 2),
    "d05-groups": (16, 21, 4, 4),
    "d06-refinement": (20, 23, 5, 2),
    "d07-multi-file": (28, 41, 6, 2),
    "d08-dense": (38, 72, 9, 2),
}
SOURCES = {
    "notebooks/explore.ipynb", "pipeline/config.json", "pipeline/data.py", "pipeline/evaluate.py",
    "pipeline/export.py", "pipeline/features.py", "pipeline/model.py", "pipeline/train.py",
}
FILES = SOURCES | {name + ".mlview.json" for name in SIZES}
TEST_WORKSPACE = "contracts/conformance/documents/workspace/"
# The eight test documents, as git paths.
LISTED = {f"{TEST_WORKSPACE}{name}.mlview.json" for name in SIZES}
# A sample diagram, as a git path: `samples/<name>.mlview.json`, with no folder in <name>.
SAMPLE_DIAGRAM = re.compile(r"samples/([^/]+)\.mlview\.json")
# The suites that read whole documents. Each lists the test documents by name.
SUITES = (
    "skills/mlview/tests/test_documents.py",
    "tools/test_workflow_conformance.py",
    "vscode-extension/test/documents.test.js",
)
# Variables that point git at another repository, index, object store or work tree.
GIT_REDIRECTS = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX",
})


def files_of(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def document(name: str) -> dict:
    return json.loads((WORKSPACE / (name + ".mlview.json")).read_text(encoding="utf-8"))


def check(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GENERATOR), "--check", *arguments], capture_output=True, text=True)


def tracked_documents() -> set[str] | None:
    """The `*.mlview.json` files git tracks, or None when the tree is not the top of a git checkout."""
    environment = {name: value for name, value in os.environ.items() if name not in GIT_REDIRECTS}

    def git(*arguments: str) -> str:
        done = subprocess.run(["git", *arguments], cwd=ROOT, env=environment, capture_output=True, check=True)
        return done.stdout.decode("utf-8")

    try:
        # In a copy inside some other checkout git answers for that checkout and lists nothing here.
        if not os.path.samefile(git("rev-parse", "--show-toplevel").strip(), ROOT):
            return None
        return {path for path in git("ls-files", "-z", "--", "*.mlview.json").split("\0") if path}
    except (OSError, subprocess.CalledProcessError):
        return None


def test_committed_files_equal_a_fresh_run():
    result = check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "OK: workspace/ equals a fresh run"


def test_workspace_holds_exactly_the_listed_files():
    assert len(FILES) == 16
    assert files_of(WORKSPACE) == FILES


def test_every_tracked_document_is_a_test_document_or_a_sample_diagram():
    tracked = tracked_documents()
    if tracked is None:
        pytest.skip("the tree is not the top of a git checkout")
    assert LISTED <= tracked
    others = tracked - LISTED
    not_samples = sorted(path for path in others if not SAMPLE_DIAGRAM.fullmatch(path))
    assert not_samples == []
    without_folder = sorted(path for path in others if not (ROOT / "samples" / SAMPLE_DIAGRAM.fullmatch(path).group(1)).is_dir())
    assert without_folder == []


def test_each_document_suite_names_every_listed_document():
    # A suite writes a test document by its bare name.
    names = set(SIZES)
    assert len(names) == 8
    for suite in SUITES:
        # The quoted strings in the suite's source text.
        quoted = set(re.findall(r"""["']([^"'\s]+)["']""", (ROOT / suite).read_text(encoding="utf-8")))
        assert names <= quoted, f"{suite} does not name {sorted(names - quoted)}"


def test_each_document_has_its_listed_size():
    for name, size in SIZES.items():
        doc = document(name)
        assert (len(doc["nodes"]), len(doc["edges"]), len(doc["phases"]), len(doc["findings"])) == size, name


def test_the_set_spans_4_to_38_steps_and_3_to_72_connections():
    steps = [len(document(name)["nodes"]) for name in SIZES]
    connections = [len(document(name)["edges"]) for name in SIZES]
    assert (min(steps), max(steps)) == (4, 38)
    assert (min(connections), max(connections)) == (3, 72)


def test_no_document_names_a_host_or_a_model():
    for name in SIZES:
        assert document(name)["producer"] == {"kind": "host-llm", "host": "unknown"}, name


def test_check_reports_a_changed_a_missing_and_an_extra_file(tmp_path):
    shutil.copytree(WORKSPACE, tmp_path / "workspace")
    assert check("--out", str(tmp_path)).returncode == 0
    source = tmp_path / "workspace" / "pipeline" / "data.py"
    source.write_bytes(source.read_bytes().replace(b"read_rows", b"load_rows", 1))
    (tmp_path / "workspace" / "d03-two-files.mlview.json").unlink()
    (tmp_path / "workspace" / "d09-extra.mlview.json").write_text("{}\n", encoding="utf-8")
    result = check("--out", str(tmp_path))
    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL: missing: workspace/d03-two-files.mlview.json",
        "FAIL: not written by the generator: workspace/d09-extra.mlview.json",
        "FAIL: differs from a fresh run: workspace/pipeline/data.py",
    ]
