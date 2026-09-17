import importlib.util
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workflow_eval", ROOT / "tools/workflow_eval.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
MANIFEST = json.loads((Path(__file__).parent / "tasks.json").read_text())


def test_locked_matrix_and_pinned_sources():
    tasks = MANIFEST["tasks"]
    assert len({t["id"] for t in tasks}) == 16
    assert sum(t["split"] == "development" for t in tasks) == 8
    pinned = {r["name"]: r for r in json.loads((ROOT / "analyzer/tests/public_corpus/repos.json").read_text())["repos"]}
    for task in tasks:
        if task["split"] == "heldout":
            assert task["commit"] == pinned[task["repository"]]["sha"]
        else:
            assert all((ROOT / path).is_file() for path in task["entrypoints"])
    assert len(module.plan(MANIFEST)) == 72


def test_missing_and_blocked_runs_never_pass():
    record = module.plan(MANIFEST)[0]
    record["status"] = "blocked"
    summary = module.summarize([record], MANIFEST)
    assert summary["statuses"] == {"blocked": 1, "pending": 71}
    assert summary["humanReviewedRuns"] == 0
    assert summary["highSeverityFalseAccusations"] is None
    assert not summary["pilotComplete"]


def test_duplicate_or_mismatched_run_rejected():
    record = module.plan(MANIFEST)[0]
    with pytest.raises(ValueError, match="duplicate"):
        module.summarize([record, record], MANIFEST)
    record["host"] = "wrong"
    with pytest.raises(ValueError, match="identity"):
        module.summarize([record], MANIFEST)


def test_completed_requires_live_evidence_and_review_counts():
    record = module.plan(MANIFEST)[0]
    record["status"] = "completed"
    with pytest.raises(ValueError, match="hostVersion"):
        module.summarize([record], MANIFEST)
    for field in ("hostVersion", "skillRevision", "artifact", "artifactSha256", "liveUiLog"):
        record[field] = "test-only"
    assert module.summarize([record], MANIFEST)["humanReviewedRuns"] == 0
    record["humanReview"] = {"reviewer": "Test reviewer", "referenceRevision": "test", "claimLedger": "test",
                             **{key: {"supported": 1, "total": 2} for key in module.PAIRS},
                             "highSeverityFalseAccusations": 1}
    summary = module.summarize([record], MANIFEST)
    assert summary["counts"]["observedClaims"] == {"supported": 1, "total": 2}
    assert summary["highSeverityFalseAccusations"] == 1
    record["humanReview"]["anchors"]["supported"] = 3
    with pytest.raises(ValueError, match="review counts"):
        module.summarize([record], MANIFEST)


def test_development_plan_keeps_native_runs_and_baselines_separate():
    records = module.development_plan(MANIFEST)
    skill = [record for record in records if record["condition"] == "skill"]
    baseline = [record for record in records if record["condition"] == "baseline"]
    assert len(skill) == 12
    assert len(baseline) == 3
    assert {record["task"] for record in skill} == set(module.DEVELOPMENT_TASKS)
    assert {record["host"] for record in skill} == set(MANIFEST["hosts"])
    assert {record["task"] for record in baseline} == {"dev-config"}
    assert all(record["status"] == "pending-native-run" for record in records)
    assert all(record["humanReview"] is None for record in records)
    assert len(module.plan(MANIFEST)) == 72


def test_provisional_development_reviews_have_exact_sources_and_no_human_scores():
    review_dir = Path(__file__).parent / "development"
    for task_id in module.DEVELOPMENT_TASKS:
        review = json.loads((review_dir / f"{task_id}.json").read_text())
        module.validate_development_review(review)
        assert review["task"] == task_id
        assert review["humanReview"] is None
        assert {claim["verdict"] for claim in review["claims"]} <= module.REVIEW_VERDICTS


def test_development_review_rejects_human_decision_and_bad_anchor():
    path = Path(__file__).parent / "development/dev-config.json"
    review = json.loads(path.read_text())
    review["claims"][0]["humanDecision"] = "approved"
    with pytest.raises(ValueError, match="human decision"):
        module.validate_development_review(review)
    review = json.loads(path.read_text())
    review["humanReview"] = {"reviewer": "not allowed here"}
    with pytest.raises(ValueError, match="cannot supply human review"):
        module.validate_development_review(review)
    review = json.loads(path.read_text())
    review["claims"][0]["sourceReferences"] = ["missing"]
    with pytest.raises(ValueError, match="unknown evidence"):
        module.validate_development_review(review)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_completed_development_record_requires_real_confined_evidence(tmp_path):
    workspace = tmp_path / "run"
    workspace.mkdir()
    response = workspace / "response.txt"
    response.write_text("native response")
    ui_log = workspace / "ui.json"
    ui_log.write_text('{"opened": true}')
    artifact = workspace / "workflow.json"
    artifact.write_text('{"workflowVersion":"1.0","revision":{"id":"r1"}}')
    record = module.development_plan(MANIFEST)[0]
    record.update({
        "status": "completed", "workspace": "run", "hostVersion": "test-host",
        "model": "test-model", "skillRevision": "test-skill", "artifact": "run/workflow.json",
        "artifactSha256": _digest(artifact), "responseLog": "run/response.txt",
        "responseLogSha256": _digest(response), "liveUiLog": "run/ui.json",
        "liveUiLogSha256": _digest(ui_log), "elapsedSeconds": 1.0, "repairRounds": 0,
    })
    summary = module.summarize_development([record], MANIFEST, tmp_path)
    assert summary["statuses"] == {"completed": 1, "pending-native-run": 14}
    assert summary["humanReviewedRuns"] == 0
    record["artifactSha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module.summarize_development([record], MANIFEST, tmp_path)


def test_development_records_reject_false_review_and_path_escape(tmp_path):
    record = module.development_plan(MANIFEST)[0]
    record["humanReview"] = {"reviewer": "claimed"}
    with pytest.raises(ValueError, match="cannot claim human review"):
        module.validate_development_records([record], MANIFEST, tmp_path)
    with pytest.raises(ValueError, match="without traversal"):
        module._confined_path("../outside", tmp_path, require_file=False)
    outside = tmp_path.with_name(tmp_path.name + "-outside")
    outside.write_text("outside")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        if sys.platform == "win32":
            pytest.skip("Windows symlink creation is unavailable")
        raise
    with pytest.raises(ValueError, match="outside workspace"):
        module._confined_path("link", tmp_path)


@pytest.mark.parametrize("field,value,match", [
    ("artifactSha256", "0" * 64, "SHA-256 mismatch"),
    ("artifactRevision", "wrong", "revision mismatch"),
    ("artifactRequest", {"question": "wrong"}, "request mismatch"),
    ("task", "dev-gan", "task and artifact do not match"),
])
def test_provisional_review_is_bound_to_artifact_identity(field, value, match):
    path = Path(__file__).parent / "development/dev-config.json"
    review = json.loads(path.read_text())
    review[field] = value
    with pytest.raises(ValueError, match=match):
        module.validate_development_review(review)


def test_provisional_review_rejects_stale_artifact_pointer():
    path = Path(__file__).parent / "development/dev-config.json"
    review = json.loads(path.read_text())
    review["claims"][0]["artifactPointers"] = ["node:missing"]
    with pytest.raises(ValueError, match="does not resolve"):
        module.validate_development_review(review)


def test_provisional_reviews_validate_in_fresh_root_without_dot_mlview(tmp_path):
    review_dir = Path(__file__).parent / "development"
    assert not (tmp_path / ".mlview").exists()
    for task_id in module.DEVELOPMENT_TASKS:
        review = json.loads((review_dir / f"{task_id}.json").read_text())
        artifact_source = ROOT / review["artifact"]
        artifact_target = tmp_path / review["artifact"]
        artifact_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact_source, artifact_target)
        artifact = json.loads(artifact_source.read_text())
        source_paths = {item["file"] for item in artifact["evidence"]}
        source_paths.update(item["file"] for item in review.get("reviewEvidence", []))
        for source_path in source_paths:
            target = tmp_path / source_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source_path, target)
        module.validate_development_review(review, tmp_path)


def test_checked_in_development_artifacts_are_sanitized_snapshots():
    artifact_dir = Path(__file__).parent / "development/artifacts"
    forbidden = re.compile(
        r"/Users/|/home/|/private/tmp/|[A-Za-z]:\\\\|"
        r"BEGIN [A-Z ]*PRIVATE KEY|(?:api[_-]?key|password|credential|bearer)[=: ]",
        re.IGNORECASE,
    )
    for artifact_path in artifact_dir.glob("*.json"):
        text = artifact_path.read_text()
        assert forbidden.search(text) is None
        document = json.loads(text)
        assert document["workflowVersion"] == "1.0"
