"""Every recorded development evidence manifest still describes the committed bytes (EVAL-17).

The manifests are immutable evidence; these tests only read them. They re-hash each recorded
artifact, refinement and preserved draft, check revisions and hosts against the artifact files,
resolve the comparison and interpretation-case paths, and require every human-review and
accuracy field to stay null. They prove bytes and bookkeeping, not semantic accuracy, and they
record no review or approval.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT = ROOT / "evals/workflow/development"
NATIVE = DEVELOPMENT / "native-artifacts"
FOLLOWUPS = DEVELOPMENT / "quality-followups"
INTERPRETATION = DEVELOPMENT / "interpretation-cases"
HOSTS = {"codex", "claude-code", "copilot"}
UNREVIEWED = ("humanReview", "accuracyScore")

_spec = importlib.util.spec_from_file_location("workflow_eval_for_manifests", ROOT / "tools/workflow_eval.py")
workflow_eval = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(workflow_eval)


def load(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def confined(base: Path, rel: str) -> Path:
    """A recorded relative path, resolved inside the development evidence tree."""
    assert isinstance(rel, str) and rel and not Path(rel).is_absolute() and "\\" not in rel, rel
    path = (base / rel).resolve()
    assert path.is_relative_to(DEVELOPMENT.resolve()), f"{rel} leaves evals/workflow/development"
    assert path.is_file() and not (base / rel).is_symlink(), f"{rel} is not a regular file"
    return path


def assert_bytes(path: Path, entry: dict, sha_key: str = "sha256") -> bytes:
    data = path.read_bytes()
    assert len(data) == entry["bytes"], f"{path.name}: {len(data)} bytes, recorded {entry['bytes']}"
    assert hashlib.sha256(data).hexdigest() == entry[sha_key], f"{path.name}: SHA-256 differs from the manifest"
    return data


def unreviewed_fields(value, where: str = "$"):
    """Every humanReview/accuracyScore member, anywhere in a manifest, with its location."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in UNREVIEWED:
                yield f"{where}.{key}", child
            yield from unreviewed_fields(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from unreviewed_fields(child, f"{where}[{index}]")


NATIVE_MANIFEST = load(NATIVE / "manifest.json")
FOLLOWUP_MANIFEST = load(FOLLOWUPS / "manifest.json")
COMPARISON = load(FOLLOWUPS / "comparison.json")
EXPECTED_REVIEW = load(INTERPRETATION / "expected-review.json")


@pytest.mark.parametrize("entry", NATIVE_MANIFEST["artifacts"], ids=lambda entry: f"{entry['host']}/{entry['task']}")
def test_native_artifact_bytes_revision_and_host(entry):
    path = confined(NATIVE, entry["path"])
    document = json.loads(assert_bytes(path, entry))
    assert entry["host"] in HOSTS
    assert entry["path"] == f"{entry['host']}/{entry['task']}.mlview.json"
    assert document["revision"]["id"] == entry["revision"]
    assert document["producer"]["host"] == entry["host"]


def test_native_manifest_covers_every_host_and_task_once_and_records_no_review():
    pairs = [(entry["host"], entry["task"]) for entry in NATIVE_MANIFEST["artifacts"]]
    assert len(pairs) == len(set(pairs)) == 12
    assert {host for host, _ in pairs} == HOSTS
    assert NATIVE_MANIFEST["humanSemanticReview"] == "pending"
    assert NATIVE_MANIFEST["fullNativeUiProof"] is False
    for refinement in NATIVE_MANIFEST["refinements"]:
        assert refinement["humanSemanticReview"] == "pending"


@pytest.mark.parametrize("entry", NATIVE_MANIFEST["refinements"], ids=lambda entry: entry["path"])
def test_native_refinement_bytes_and_parent(entry):
    path = confined(NATIVE, entry["path"])
    document = json.loads(assert_bytes(path, entry))
    assert document["revision"]["id"] == entry["revision"]
    assert document["revision"]["parent"] == entry["parentRevision"]
    assert document["producer"]["host"] == entry["host"]
    parents = [artifact for artifact in NATIVE_MANIFEST["artifacts"]
               if (artifact["host"], artifact["task"]) == (entry["host"], entry["task"])]
    assert len(parents) == 1
    parent = parents[0]
    assert parent["revision"] == entry["parentRevision"]
    assert parent["sha256"] == entry["parentSha256"]
    assert hashlib.sha256(confined(NATIVE, parent["path"]).read_bytes()).hexdigest() == entry["parentSha256"]


@pytest.mark.parametrize("entry", FOLLOWUP_MANIFEST["artifacts"], ids=lambda entry: f"{entry['host']}/{entry['task']}")
def test_quality_followup_artifact_bytes_revision_and_host(entry):
    path = confined(FOLLOWUPS, entry["path"])
    document = json.loads(assert_bytes(path, entry))
    assert entry["path"] == f"{entry['host']}/{entry['task']}.mlview.json"
    assert document["revision"]["id"] == entry["revision"]
    assert document["producer"]["host"] == entry["host"]


@pytest.mark.parametrize("entry", FOLLOWUP_MANIFEST["failedRuns"], ids=lambda entry: f"{entry['host']}/{entry['task']}")
def test_preserved_failed_drafts_keep_their_bytes(entry):
    assert entry["publishedArtifact"] is None
    path = confined(FOLLOWUPS, entry["preservedDraft"])
    assert path.suffix == ".txt", "a failed draft is kept as text so it cannot pass for a WorkflowDocument"
    assert_bytes(path, entry)
    matches = [run for run in COMPARISON["failedRuns"] if (run["host"], run["task"]) == (entry["host"], entry["task"])]
    assert len(matches) == 1
    assert matches[0]["preservedDraft"] == entry["preservedDraft"]
    assert matches[0]["preservedDraftSha256"] == entry["sha256"]


def test_followup_source_hashes_match_the_relocated_fixtures():
    """sourceSha256 names the frozen source of each task; comparison.json cites it by its old path."""
    cited: dict[str, set[str]] = {}
    for question in COMPARISON["questions"]:
        cited.setdefault(question["task"], set()).update(source["file"] for source in question["sourceEvidence"])
    assert set(FOLLOWUP_MANIFEST["sourceSha256"]) == set(cited)
    for task, digest in FOLLOWUP_MANIFEST["sourceSha256"].items():
        assert len(cited[task]) == 1, f"{task} cites more than one source file"
        source = workflow_eval.historical_source(next(iter(cited[task])), ROOT)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, task


def test_comparison_paths_and_revisions_resolve():
    native = {entry["path"]: entry for entry in NATIVE_MANIFEST["artifacts"]}
    followups = {entry["path"]: entry for entry in FOLLOWUP_MANIFEST["artifacts"]}
    assert COMPARISON["sourceCommit"] == FOLLOWUP_MANIFEST["sourceCommit"]
    assert COMPARISON["candidateSkillBundleSha256"] == FOLLOWUP_MANIFEST["candidateSkillBundleSha256"]
    seen = set()
    for comparison in COMPARISON["comparisons"]:
        key = (comparison["host"], comparison["task"])
        assert key not in seen
        seen.add(key)
        before, after = comparison["before"], comparison["after"]
        assert before["path"].startswith("../native-artifacts/")
        before_entry = native[before["path"].removeprefix("../native-artifacts/")]
        after_entry = followups[after["path"]]
        for side, entry in ((before, before_entry), (after, after_entry)):
            document = load(confined(FOLLOWUPS, side["path"]))
            assert document["revision"]["id"] == side["revision"] == entry["revision"]
            assert (entry["host"], entry["task"]) == key
    assert seen == {(entry["host"], entry["task"]) for entry in FOLLOWUP_MANIFEST["artifacts"]}


def test_interpretation_case_files_exist():
    assert EXPECTED_REVIEW["humanReview"] is None
    files = [rel for case in EXPECTED_REVIEW["cases"] for rel in case["files"]]
    assert files
    for rel in files:
        assert rel.startswith("evals/workflow/development/interpretation-cases/")
        confined(ROOT, rel)


@pytest.mark.parametrize("name, manifest", [
    ("native-artifacts/manifest.json", NATIVE_MANIFEST),
    ("quality-followups/manifest.json", FOLLOWUP_MANIFEST),
    ("quality-followups/comparison.json", COMPARISON),
    ("interpretation-cases/expected-review.json", EXPECTED_REVIEW),
])
def test_no_manifest_records_a_human_review_or_an_accuracy_score(name, manifest):
    assert [(where, value) for where, value in unreviewed_fields(manifest) if value is not None] == []
