import importlib.util
import json
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
