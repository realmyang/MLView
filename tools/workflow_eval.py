#!/usr/bin/env python3
"""Prepare and summarize human-reviewed native-host pilot records; never run a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals/workflow/tasks.json"
PAIRS = ("observedClaims", "inferredClaims", "essentialFacts", "anchors")
DEVELOPMENT_TASKS = ("dev-config", "dev-sklearn", "dev-gan", "dev-notebook")
REVIEW_VERDICTS = {"supported", "qualified", "unsupported", "omitted"}
USABILITY_QUESTIONS = {
    "dataOrigin", "updatedParametersAndFitState", "losses", "evaluationBoundaries",
    "outputs", "uncertainty",
}
DEVELOPMENT_ARTIFACTS = {
    "dev-config": "evals/workflow/development/artifacts/configured-training.mlview.json",
    "dev-sklearn": "evals/workflow/development/artifacts/dev-sklearn.mlview.json",
    "dev-gan": "evals/workflow/development/artifacts/dev-gan.mlview.json",
    "dev-notebook": "evals/workflow/development/artifacts/notebook.mlview.json",
}


def plan(manifest: dict) -> list[dict]:
    return [
        {"id": f"{task['id']}:{host}:{repeat}", "task": task["id"],
         "host": host, "repeat": repeat, "status": "pending",
         "condition": "skill", "prompt": task["prompt"],
         "repositoryCommit": task["commit"], "hostVersion": None,
         "model": None, "skillRevision": None, "artifact": None,
         "artifactSha256": None, "elapsedSeconds": None, "repairRounds": None,
         "usage": None, "liveUiLog": None, "humanReview": None}
        for task in manifest["tasks"] if task["split"] == "heldout"
        for host in manifest["hosts"]
        for repeat in range(1, manifest["repetitions"] + 1)
    ]


def development_plan(manifest: dict) -> list[dict]:
    """Prepare pending native-host development runs and a small matched baseline."""
    tasks = {task["id"]: task for task in manifest["tasks"]}
    records = []
    for task_id in DEVELOPMENT_TASKS:
        task = tasks[task_id]
        for host in manifest["hosts"]:
            records.append({
                "id": f"{task_id}:{host}:skill", "task": task_id, "host": host,
                "condition": "skill", "status": "pending-native-run",
                "prompt": task["prompt"], "workspace": None, "hostVersion": None,
                "model": None, "skillRevision": None, "artifact": None,
                "artifactSha256": None, "responseLog": None, "responseLogSha256": None,
                "liveUiLog": None, "liveUiLogSha256": None, "elapsedSeconds": None,
                "repairRounds": None, "failureReason": None,
                "provisionalReview": None, "humanReview": None,
            })
    task = tasks["dev-config"]
    for host in manifest["hosts"]:
        records.append({
            "id": f"dev-config:{host}:baseline", "task": "dev-config", "host": host,
            "condition": "baseline", "status": "pending-native-run",
            "prompt": task["prompt"], "workspace": None, "hostVersion": None,
            "model": None, "skillRevision": None, "artifact": None,
            "artifactSha256": None, "responseLog": None, "responseLogSha256": None,
            "liveUiLog": None, "liveUiLogSha256": None, "elapsedSeconds": None,
            "repairRounds": None, "failureReason": None,
            "provisionalReview": None, "humanReview": None,
        })
    return records


def _confined_path(value: object, root: Path = ROOT, require_file: bool = True) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a nonempty workspace-relative string")
    supplied = Path(value)
    if supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError("path must be workspace-relative without traversal")
    path = (root / supplied).resolve()
    resolved_root = root.resolve()
    if path != resolved_root and resolved_root not in path.parents:
        raise ValueError("path resolves outside workspace")
    if require_file and not path.is_file():
        raise ValueError(f"file does not exist: {value}")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_file(path_value: object, digest: object, root: Path = ROOT) -> Path:
    path = _confined_path(path_value, root)
    if not isinstance(digest, str) or _sha256(path) != digest:
        raise ValueError(f"SHA-256 mismatch: {path_value}")
    return path


def _verify_directory(path_value: object, root: Path = ROOT) -> Path:
    path = _confined_path(path_value, root, require_file=False)
    if not path.is_dir():
        raise ValueError(f"directory does not exist: {path_value}")
    return path


def validate_development_records(records: list[dict], manifest: dict, root: Path = ROOT) -> None:
    expected = {record["id"]: record for record in development_plan(manifest)}
    seen = set()
    for record in records:
        key = record.get("id")
        if key not in expected or key in seen:
            raise ValueError("unknown or duplicate development run ID")
        seen.add(key)
        wanted = expected[key]
        for field in ("task", "host", "condition", "prompt"):
            if record.get(field) != wanted[field]:
                raise ValueError("development run identity differs from the planned matrix")
        if record.get("humanReview") is not None:
            raise ValueError("development records cannot claim human review")
        status = record.get("status")
        if status not in {"pending-native-run", "completed", "failed", "blocked"}:
            raise ValueError("invalid development run status")
        if status == "pending-native-run":
            continue
        for field in ("workspace", "hostVersion", "model", "responseLog",
                      "responseLogSha256", "liveUiLog", "liveUiLogSha256"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"non-pending development run requires {field}")
        _verify_directory(record["workspace"], root)
        _verify_file(record["responseLog"], record["responseLogSha256"], root)
        _verify_file(record["liveUiLog"], record["liveUiLogSha256"], root)
        if status in {"failed", "blocked"}:
            if not isinstance(record.get("failureReason"), str) or not record["failureReason"].strip():
                raise ValueError("failed or blocked development run requires failureReason")
            if record.get("provisionalReview") is not None:
                raise ValueError("failed or blocked development run cannot claim provisional review")
            continue
        if record["condition"] == "skill":
            for field in ("skillRevision", "artifact", "artifactSha256"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValueError(f"completed skill run requires {field}")
            artifact_path = _verify_file(record["artifact"], record["artifactSha256"], root)
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            if artifact.get("workflowVersion") != "1.0" or not artifact.get("revision", {}).get("id"):
                raise ValueError("completed skill run artifact is not a WorkflowDocument 1.0 revision")
        elif record.get("artifact") is not None or record.get("artifactSha256") is not None:
            raise ValueError("baseline run cannot claim an MLView artifact")
        if record.get("provisionalReview") is not None:
            _confined_path(record["provisionalReview"], root)


def summarize_development(records: list[dict], manifest: dict, root: Path = ROOT) -> dict:
    validate_development_records(records, manifest, root)
    expected = development_plan(manifest)
    supplied = {record["id"]: record for record in records}
    statuses: Counter = Counter()
    by_condition = {condition: Counter() for condition in ("skill", "baseline")}
    by_host = {host: Counter() for host in manifest["hosts"]}
    for wanted in expected:
        status = supplied.get(wanted["id"], wanted)["status"]
        statuses[status] += 1
        by_condition[wanted["condition"]][status] += 1
        by_host[wanted["host"]][status] += 1
    return {
        "expectedRuns": len(expected), "statuses": dict(statuses),
        "byCondition": {key: dict(value) for key, value in by_condition.items()},
        "byHost": {key: dict(value) for key, value in by_host.items()},
        "nativeCompletedRuns": statuses["completed"], "humanReviewedRuns": 0,
        "note": "Evidence-backed run status only; this summary makes no semantic or human-review judgment.",
    }


def _source_lines(path: Path, cell: int | None = None) -> list[str]:
    if cell is None:
        return path.read_text(encoding="utf-8").splitlines()
    notebook = json.loads(path.read_text(encoding="utf-8"))
    source = notebook["cells"][cell]["source"]
    return "".join(source).splitlines()


def _json_pointer(value: object, pointer: str) -> object:
    current = value
    for raw in pointer.lstrip("/").split("/") if pointer else []:
        key = raw.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


def validate_development_review(review: dict, root: Path = ROOT) -> None:
    """Validate review provenance and exact anchors without judging semantics."""
    if review.get("reviewStatus") != "pending-human-review":
        raise ValueError("development review must remain pending-human-review")
    if review.get("reviewerType") != "model-provisional":
        raise ValueError("development review must identify model-provisional authorship")
    if review.get("humanReview") is not None:
        raise ValueError("development review cannot supply human review")
    task = review.get("task")
    artifact_path = review.get("artifact")
    if task not in DEVELOPMENT_ARTIFACTS or artifact_path != DEVELOPMENT_ARTIFACTS[task]:
        raise ValueError("development review task and artifact do not match")
    artifact_file = _verify_file(artifact_path, review.get("artifactSha256"), root)
    artifact = json.loads(artifact_file.read_text(encoding="utf-8"))
    if review.get("artifactRevision") != artifact.get("revision", {}).get("id"):
        raise ValueError("development review artifact revision mismatch")
    if review.get("artifactRequest") != artifact.get("request"):
        raise ValueError("development review artifact request mismatch")
    evidence = {item["id"]: item for item in artifact.get("evidence", [])}
    for item in review.get("reviewEvidence", []):
        if item["id"] in evidence:
            raise ValueError(f"duplicate evidence ID: {item['id']}")
        evidence[item["id"]] = item
    claims = review.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("development review requires claims")
    for claim in claims:
        if claim.get("verdict") not in REVIEW_VERDICTS:
            raise ValueError("invalid provisional claim verdict")
        if not isinstance(claim.get("humanDecision"), type(None)):
            raise ValueError("provisional claims cannot contain a human decision")
        refs = claim.get("sourceReferences")
        if not isinstance(refs, list) or not refs:
            raise ValueError("each provisional claim requires source references")
        for ref in refs:
            item = evidence.get(ref)
            if item is None:
                raise ValueError(f"unknown evidence ID: {ref}")
            if "jsonPointer" in item:
                source_path = _confined_path(item["file"], root)
                actual = _json_pointer(json.loads(source_path.read_text(encoding="utf-8")),
                                       item["jsonPointer"])
                if actual != item.get("value"):
                    raise ValueError(f"JSON evidence mismatch: {ref}")
                continue
            lines = _source_lines(_confined_path(item["file"], root), item.get("cell"))
            start, end = item["line"], item.get("endLine", item["line"])
            if "\n".join(lines[start - 1:end]) != item["quote"]:
                raise ValueError(f"source quote mismatch: {ref}")
        _validate_pointers(claim.get("artifactPointers"), artifact)
    usability = review.get("usability")
    if not isinstance(usability, dict) or set(usability) != USABILITY_QUESTIONS:
        raise ValueError("development review must answer all six usability questions")
    for answer in usability.values():
        if answer.get("status") not in {"clear", "partial", "missing"}:
            raise ValueError("invalid provisional usability status")
        if answer.get("humanDecision") is not None:
            raise ValueError("provisional usability cannot contain a human decision")
        _validate_pointers(answer.get("artifactPointers"), artifact)


def _validate_pointers(pointers: object, artifact: dict) -> None:
    if not isinstance(pointers, list):
        raise ValueError("artifactPointers must be a list")
    collections = {
        "node": {item["id"] for item in artifact.get("nodes", [])},
        "edge": {item["id"] for item in artifact.get("edges", [])},
        "finding": {item["id"] for item in artifact.get("findings", [])},
        "evidence": {item["id"] for item in artifact.get("evidence", [])},
        "phase": {item["id"] for item in artifact.get("phases", [])},
    }
    for pointer in pointers:
        if pointer == "coverage":
            if "coverage" not in artifact:
                raise ValueError("artifact pointer does not resolve: coverage")
            continue
        if not isinstance(pointer, str) or ":" not in pointer:
            raise ValueError(f"invalid artifact pointer: {pointer}")
        kind, identifier = pointer.split(":", 1)
        if identifier not in collections.get(kind, set()):
            raise ValueError(f"artifact pointer does not resolve: {pointer}")


def summarize(records: list[dict], manifest: dict) -> dict:
    expected = {record["id"]: record for record in plan(manifest)}
    seen = set()
    statuses: Counter = Counter()
    totals = {key: {"supported": 0, "total": 0} for key in PAIRS}
    per_host = {host: {"completed": 0, "reviewed": 0} for host in manifest["hosts"]}
    reviewed = false_high = 0
    for record in records:
        key = record.get("id")
        if key not in expected or key in seen:
            raise ValueError("unknown or duplicate run ID")
        seen.add(key)
        wanted = expected[key]
        if any(record.get(k) != wanted[k] for k in ("host", "task", "repeat", "repositoryCommit", "condition")):
            raise ValueError("run identity differs from the pinned matrix")
        status = record.get("status")
        if status not in {"pending", "completed", "failed", "blocked"}:
            raise ValueError("invalid run status")
        statuses[status] += 1
        review = record.get("humanReview")
        if status != "completed":
            if review is not None:
                raise ValueError("only completed runs may have a semantic review")
            continue
        for field in ("hostVersion", "skillRevision", "artifact", "artifactSha256", "liveUiLog"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError(f"completed run requires {field}")
        per_host[record["host"]]["completed"] += 1
        if review is None:
            continue
        if not isinstance(review, dict) or not all(isinstance(review.get(k), str) and review[k].strip()
                                                   for k in ("reviewer", "referenceRevision", "claimLedger")):
            raise ValueError("review requires named human reviewer, frozen reference revision and claim ledger")
        for metric in PAIRS:
            pair = review.get(metric)
            if not isinstance(pair, dict):
                raise ValueError(f"missing review counts: {metric}")
            numerator, denominator = pair.get("supported"), pair.get("total")
            if type(numerator) is not int or type(denominator) is not int or not 0 <= numerator <= denominator:
                raise ValueError("review counts must be integers with 0 <= supported <= total")
            totals[metric]["supported"] += numerator
            totals[metric]["total"] += denominator
        count = review.get("highSeverityFalseAccusations")
        if type(count) is not int or count < 0:
            raise ValueError("high-severity false accusations require an explicit nonnegative count")
        false_high += count
        reviewed += 1
        per_host[record["host"]]["reviewed"] += 1
    statuses["pending"] += len(expected) - len(seen)
    return {"expectedRuns": len(expected), "statuses": dict(statuses),
            "humanReviewedRuns": reviewed, "perHost": per_host,
            "counts": totals, "highSeverityFalseAccusations": false_high if reviewed else None,
            "pilotComplete": reviewed == len(expected),
            "note": "Counts are human-entered, not semantic judgments by this tool. Missing runs never count as passes."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("development-plan")
    development_summary = sub.add_parser("summarize-development")
    development_summary.add_argument("records", type=Path)
    validate = sub.add_parser("validate-development")
    validate.add_argument("reviews", nargs="+", type=Path)
    summary = sub.add_parser("summarize")
    summary.add_argument("records", type=Path)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        if args.command == "plan":
            value = plan(manifest)
        elif args.command == "development-plan":
            value = development_plan(manifest)
        elif args.command == "validate-development":
            for path in args.reviews:
                validate_development_review(json.loads(path.read_text(encoding="utf-8")))
            value = {"ok": True, "validated": len(args.reviews),
                     "note": "Exact anchors and pending status validated; semantics remain unscored."}
        elif args.command == "summarize-development":
            value = summarize_development(json.loads(args.records.read_text(encoding="utf-8")), manifest)
        else:
            value = summarize(json.loads(args.records.read_text(encoding="utf-8")), manifest)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
