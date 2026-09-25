import importlib.util
import hashlib
import io
import json
import re
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
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
    pinned = {r["name"]: r for r in json.loads((ROOT / "evals/workflow/repositories.json").read_text())["repos"]}
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


def test_stage_one_baselines_match_tasks_but_cannot_enter_skill_scores():
    baselines = module.baseline_plan(MANIFEST)
    first = [record for record in module.plan(MANIFEST) if record["repeat"] == 1]
    assert len(baselines) == 24
    assert {(r["task"], r["host"], r["repositoryCommit"], r["prompt"]) for r in baselines} == {
        (r["task"], r["host"], r["repositoryCommit"], r["prompt"]) for r in first}
    assert not {r["id"] for r in baselines} & {r["id"] for r in module.plan(MANIFEST)}
    assert all(r["condition"] == "baseline" and r["humanReview"] is None
               and r["status"] == "pending" and "artifact" not in r for r in baselines)
    with pytest.raises(ValueError, match="unknown"):
        module.summarize(baselines, MANIFEST)


def test_duplicate_or_mismatched_run_rejected():
    record = module.plan(MANIFEST)[0]
    with pytest.raises(ValueError, match="duplicate"):
        module.summarize([record, record], MANIFEST)
    record["host"] = "wrong"
    with pytest.raises(ValueError, match="identity"):
        module.summarize([record], MANIFEST)


def test_changed_pilot_prompt_cannot_count_as_a_pinned_run():
    record = module.plan(MANIFEST)[0]
    record["prompt"] += " Skip the difficult parts."
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


def _write_historical_map(root, old_path, new_path, digest):
    mapping = root / "evals/workflow/fixtures/historical-paths.json"
    mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_text(json.dumps({
        "sourceCommit": "0" * 40,
        "paths": {old_path: {"path": new_path, "sha256": digest}},
    }))


def test_historical_source_rejects_fixture_hash_mismatch(tmp_path):
    fixture = tmp_path / "evals/workflow/fixtures/example.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("print('changed')\n")
    old_path = "analyzer/tests/accuracy/corpus/example.py"
    _write_historical_map(
        tmp_path, old_path, "evals/workflow/fixtures/example.py", "0" * 64
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module.historical_source(old_path, tmp_path)


def test_recreated_legacy_path_cannot_bypass_mapped_fixture_hash(tmp_path):
    old_path = "analyzer/tests/accuracy/corpus/example.py"
    recreated = tmp_path / old_path
    recreated.parent.mkdir(parents=True)
    recreated.write_text("print('recreated legacy path')\n")
    fixture = tmp_path / "evals/workflow/fixtures/example.py"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("print('changed mapped fixture')\n")
    _write_historical_map(
        tmp_path, old_path, "evals/workflow/fixtures/example.py", "0" * 64
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module.historical_source(old_path, tmp_path)


def test_historical_source_rejects_unknown_old_path(tmp_path):
    mapping = tmp_path / "evals/workflow/fixtures/historical-paths.json"
    mapping.parent.mkdir(parents=True)
    mapping.write_text(json.dumps({"sourceCommit": "0" * 40, "paths": {}}))

    with pytest.raises(ValueError, match="historical source does not exist"):
        module.historical_source("analyzer/tests/accuracy/corpus/unknown.py", tmp_path)


def test_historical_source_rejects_mapped_symlink_escape(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text("print('outside')\n")
    link = tmp_path / "evals/workflow/fixtures/escape.py"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    old_path = "analyzer/tests/accuracy/corpus/escape.py"
    _write_historical_map(
        tmp_path, old_path, "evals/workflow/fixtures/escape.py", _digest(outside)
    )

    with pytest.raises(ValueError, match="outside workspace"):
        module.historical_source(old_path, tmp_path)


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


def _native_review(task="dev-config", host="codex"):
    manifest = json.loads((Path(__file__).parent / "development/native-artifacts/manifest.json").read_text())
    entry = next(item for item in manifest["artifacts"]
                 if item["task"] == task and item["host"] == host)
    artifact_path = f"evals/workflow/development/native-artifacts/{entry['path']}"
    artifact = json.loads((ROOT / artifact_path).read_text())
    smoke = json.loads((Path(__file__).parent / f"development/{task}.json").read_text())
    smoke.update({
        "host": host,
        "artifact": artifact_path,
        "artifactSha256": entry["sha256"],
        "artifactRevision": entry["revision"],
        "artifactRequest": artifact["request"],
        # Keep this fixture about identity binding; native pointer IDs differ.
        "reviewEvidence": [],
        "claims": [{**smoke["claims"][0], "artifactPointers": [],
                    "sourceReferences": [artifact["evidence"][0]["id"]]}],
        "usability": {key: {**answer, "artifactPointers": []}
                      for key, answer in smoke["usability"].items()},
    })
    return smoke


def test_native_review_is_bound_to_registered_host_path_hash_and_revision():
    review = _native_review()
    module.validate_development_review(review)
    mutations = [
        ("host", "copilot", "registered task/host artifact"),
        ("artifact", "evals/workflow/development/native-artifacts/codex/dev-gan.mlview.json",
         "registered task/host artifact"),
        ("artifactSha256", "0" * 64, "artifact manifest"),
        ("artifactRevision", "wrong", "artifact manifest"),
        ("artifactRequest", {"question": "wrong"}, "request mismatch"),
        # EVAL-5: the smoke artifact with a native host label must match the native registration.
        ("artifact", module.DEVELOPMENT_ARTIFACTS["dev-config"], "registered task/host artifact"),
    ]
    for field, value, message in mutations:
        changed = _native_review()
        changed[field] = value
        with pytest.raises(ValueError, match=message):
            module.validate_development_review(changed)


def test_all_committed_native_reviews_validate_on_this_platform():
    reviews = sorted((Path(__file__).parent / "development/native-reviews").glob("*/*.json"))
    assert len(reviews) == 12
    for path in reviews:
        module.validate_development_review(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("pointer", ["cells/0", "/cells/-1", "/cells/01", "/cells/+0",
                                     "/cells/1", "/missing", "/cells/0/x", "/bad~2"])
def test_json_evidence_rejects_invalid_or_unresolved_pointers(pointer):
    with pytest.raises(ValueError, match="JSON Pointer"):
        module._json_pointer({"cells": [4]}, pointer)


def test_json_evidence_preserves_empty_keys_and_decodes_escaped_tokens():
    value = {"": {"cells": [4]}, "a/b": {"~key": True}}
    assert module._json_pointer(value, "") is value
    assert module._json_pointer(value, "//cells/0") == 4
    assert module._json_pointer(value, "/a~1b/~0key") is True


def test_native_review_rejects_bad_pointer_and_human_review_injection():
    review = _native_review()
    review["claims"][0]["artifactPointers"] = ["node:not-registered"]
    with pytest.raises(ValueError, match="does not resolve"):
        module.validate_development_review(review)


def test_development_review_requires_unique_claim_ids_and_bounded_nonempty_anchors():
    review = _native_review()
    review["claims"].append(dict(review["claims"][0]))
    with pytest.raises(ValueError, match="unique claim IDs"):
        module.validate_development_review(review)

    review = _native_review()
    review["reviewEvidence"] = [{"id": "empty", "file": "samples/configured_training/train.py",
                                 "line": 9999, "quote": ""}]
    review["claims"][0]["sourceReferences"] = ["empty"]
    with pytest.raises(ValueError, match="source range"):
        module.validate_development_review(review)


def test_baseline_notes_require_complete_hosts_exact_sources_and_no_human_review(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("first\nsecond\n", encoding="utf-8")
    baselines = []
    for host in MANIFEST["hosts"]:
        baselines.append({
            "id": f"dev-config:{host}:baseline", "task": "dev-config", "host": host,
            "responseSha256": "a" * 64, "captureKind": "native response",
            "summary": "Provisional comparison.",
            "strengths": [{"summary": "Names the first fact.", "sourceReferences": ["src"]}],
            "gaps": [{"summary": "Omits the second fact.", "sourceReferences": ["src"]}],
            "reviewEvidence": [{"id": "src", "file": "source.py", "line": 1,
                                "endLine": 2, "quote": "first\nsecond"}],
            "humanReview": None,
        })
    value = {"version": 1, "reviewerType": "model-provisional",
             "reviewStatus": "pending-human-review", "humanReview": None,
             "baselines": baselines}
    assert len(module.validate_baselines(value, MANIFEST, tmp_path)) == 3
    value["baselines"][0]["reviewEvidence"][0]["quote"] = "invented"
    with pytest.raises(ValueError, match="source quote mismatch"):
        module.validate_baselines(value, MANIFEST, tmp_path)
    value["baselines"][0]["reviewEvidence"][0]["quote"] = "first\nsecond"
    value["baselines"][0]["humanReview"] = {"reviewer": "invented"}
    with pytest.raises(ValueError, match="cannot supply human review"):
        module.validate_baselines(value, MANIFEST, tmp_path)
    review = _native_review()
    review["humanReview"] = {"reviewer": "invented"}
    with pytest.raises(ValueError, match="cannot supply human review"):
        module.validate_development_review(review)


def test_baseline_capture_hashes_are_optional_and_verified_before_rendering(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("source line\n", encoding="utf-8")
    captures = {}
    baselines = []
    for host in MANIFEST["hosts"]:
        capture = tmp_path / f"{host}.txt"
        capture.write_text(f"private <response> for {host}", encoding="utf-8")
        captures[host] = capture.name
        baselines.append({
            "id": f"dev-config:{host}:baseline", "task": "dev-config", "host": host,
            "responseSha256": _digest(capture), "captureKind": "native response",
            "summary": "Summary.", "strengths": [], "gaps": [],
            "reviewEvidence": [{"id": "src", "file": "source.py", "line": 1, "endLine": 1,
                                "quote": "source line"}], "humanReview": None,
        })
    mapping = tmp_path / "captures.json"
    mapping.write_text(json.dumps(captures), encoding="utf-8")
    loaded = module._load_baseline_captures(mapping, baselines, tmp_path)
    assert loaded["codex"] == "private <response> for codex"

    reviews = tmp_path / "reviews"
    reviews.mkdir()
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"evidence": []}', encoding="utf-8")
    usability = {key: {"status": "clear", "answer": "answer", "artifactPointers": []}
                 for key in module.USABILITY_QUESTIONS}
    for task in module.DEVELOPMENT_TASKS:
        for host in MANIFEST["hosts"]:
            review = {
                "task": task, "host": host, "artifact": "artifact.json",
                "artifactRevision": "r1", "artifactSha256": "a" * 64,
                "claims": [{"id": "claim", "verdict": "supported", "summary": "summary",
                            "artifactPointers": [], "sourceReferences": []}],
                "usability": usability,
            }
            (reviews / f"{task}-{host}.json").write_text(json.dumps(review), encoding="utf-8")
    baseline_path = tmp_path / "baselines.json"
    baseline_path.write_text(json.dumps({
        "version": 1, "reviewerType": "model-provisional",
        "reviewStatus": "pending-human-review", "humanReview": None,
        "baselines": baselines,
    }), encoding="utf-8")
    monkeypatch.setattr(module, "validate_development_review", lambda review, root: None)
    public_output = tmp_path / "public.html"
    module.generate_review_packet(reviews, baseline_path, public_output, MANIFEST, tmp_path)
    public_html = public_output.read_text(encoding="utf-8")
    assert "private &lt;response&gt;" not in public_html
    # The instruction paragraph points to the decisions file (Campaign 2 specification, section 2).
    assert "evals/workflow/decisions/development-adjudication.md" in public_html
    assert "python tools/workflow_eval.py check development-adjudication" in public_html
    # EVAL-4: the packet is created exclusively; --force replaces the derived file.
    with pytest.raises(ValueError, match="already exists; the packet is derived, so pass --force"):
        module.generate_review_packet(reviews, baseline_path, public_output, MANIFEST, tmp_path)
    public_output.write_text("stale", encoding="utf-8")
    module.generate_review_packet(reviews, baseline_path, public_output, MANIFEST, tmp_path, force=True)
    assert public_output.read_text(encoding="utf-8") == public_html
    private_output = tmp_path / "private.html"
    module.generate_review_packet(reviews, baseline_path, private_output, MANIFEST, tmp_path,
                                  baseline_captures_path=mapping)
    private_html = private_output.read_text(encoding="utf-8")
    assert "Private raw captures included" in private_html
    assert "private &lt;response&gt; for codex" in private_html
    assert "private <response>" not in private_html

    captures["codex"] = "copilot.txt"
    mapping.write_text(json.dumps(captures), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        module._load_baseline_captures(mapping, baselines, tmp_path)


def test_baseline_rejects_empty_out_of_bounds_anchor(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("one\n", encoding="utf-8")
    entries = [{
        "id": f"dev-config:{host}:baseline", "task": "dev-config", "host": host,
        "responseSha256": "a" * 64, "captureKind": "native response", "summary": "Summary.",
        "strengths": [], "gaps": [], "reviewEvidence": [
            {"id": "src", "file": "source.py", "line": 99, "quote": ""}],
        "humanReview": None,
    } for host in MANIFEST["hosts"]]
    value = {"version": 1, "reviewerType": "model-provisional",
             "reviewStatus": "pending-human-review", "humanReview": None,
             "baselines": entries}
    with pytest.raises(ValueError, match="source range"):
        module.validate_baselines(value, MANIFEST, tmp_path)


@pytest.mark.parametrize("cell,message", [(-1, "zero-based integer index"), (True, "zero-based integer index"),
                                          (1, "cell 1 does not identify valid notebook source")])
def test_notebook_source_rejects_invalid_cell_indices(tmp_path, cell, message):
    notebook = tmp_path / "notebook.ipynb"
    notebook.write_text(json.dumps({"cells": [{"source": ["first\n", "second\n"]}]}),
                        encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        module._source_lines(notebook, cell)


def test_notebook_source_rejects_invalid_cell_source_and_locations_show_metadata(tmp_path):
    notebook = tmp_path / "notebook.ipynb"
    notebook.write_text(json.dumps({"cells": [{"source": ["valid\n", 3]}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="cell 0 does not identify valid notebook source"):
        module._source_lines(notebook, 0)
    assert module._evidence_location({
        "file": "flow.ipynb", "cell": 3, "line": 6, "endLine": 10,
    }) == "flow.ipynb — cell 3 — lines 6-10"
    assert module._evidence_location({
        "file": "config.json", "jsonPointer": "/model/name",
    }) == "config.json — JSON Pointer /model/name"


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
            shutil.copyfile(module.historical_source(source_path), target)
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


def _excerpt_source(tmp_path, text: bytes, **fields) -> dict:
    (tmp_path / "source.py").write_bytes(text)
    return {"id": "src", "file": "source.py", **fields}


def test_replay_uses_the_helper_line_semantics(tmp_path):
    """EVAL-15: replay splits only on CRLF, CR and LF, keeps a trailing empty element and strips a
    BOM, exactly like the product helper; str.splitlines() would split on the form feed."""
    source = _excerpt_source(tmp_path, b"\xef\xbb\xbfa = 1\x0cb = 2\r\nc = 3\rd = 4\n",
                             line=1, endLine=2, quote="a = 1\x0cb = 2\nc = 3")
    module._validate_source_excerpt(source, tmp_path, "replay evidence")
    assert module._source_lines(tmp_path / "source.py") == ["a = 1\x0cb = 2", "c = 3", "d = 4", ""]
    helper = module.eval_records.load_helper()
    assert module._source_lines(tmp_path / "source.py") == helper._lines(helper._strip_bom(
        (tmp_path / "source.py").read_bytes().decode("utf-8")))
    source.update(line=4, endLine=4, quote="")
    with pytest.raises(ValueError, match="nonempty source quote"):
        module._validate_source_excerpt(source, tmp_path, "replay evidence")
    source.update(line=1, endLine=1, quote="\ufeffa = 1\x0cb = 2")  # a line-1 quote may keep the BOM
    module._validate_source_excerpt(source, tmp_path, "replay evidence")


def test_replay_requires_an_integer_end_line(tmp_path):
    source = _excerpt_source(tmp_path, b"one\ntwo\n", line=1, quote="one")
    with pytest.raises(ValueError, match="invalid replay evidence source range"):
        module._validate_source_excerpt(source, tmp_path, "replay evidence")
    source["endLine"] = 1
    module._validate_source_excerpt(source, tmp_path, "replay evidence")
    source["endLine"] = "1"
    with pytest.raises(ValueError, match="source range"):
        module._validate_source_excerpt(source, tmp_path, "replay evidence")


def test_smoke_branch_only_without_a_host_key():
    """EVAL-5: a developer-subagent smoke ledger has no host key; adding one requires registration."""
    smoke = json.loads((Path(__file__).parent / "development/dev-config.json").read_text())
    assert "host" not in smoke
    module.validate_development_review(smoke)
    for host in ("codex", None):
        labelled = dict(smoke, host=host)
        with pytest.raises(ValueError, match="registered task/host artifact|not uniquely registered"):
            module.validate_development_review(labelled)


def test_configuration_pointer_resolves_request_configuration():
    artifact = {"request": {"question": "q", "scope": "s", "configuration": "defaults"}, "nodes": [], "coverage": {}}
    module._validate_pointers(["configuration", "coverage"], artifact)
    with pytest.raises(ValueError, match="does not resolve: configuration"):
        module._validate_pointers(["configuration"], {"request": {"question": "q", "scope": "s"}})


def test_development_plan_output_is_exclusive(tmp_path):
    output = tmp_path / "plans" / "development.json"
    out = io.StringIO()
    with redirect_stdout(out):
        assert module.main(["development-plan", "--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == module.development_plan(MANIFEST)
    assert json.loads(out.getvalue())["records"] == 15
    err = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(err), pytest.raises(SystemExit):
        module.main(["development-plan", "--output", str(output)])
    assert "already exists; it may hold recorded run data, so it is never overwritten" in err.getvalue()
