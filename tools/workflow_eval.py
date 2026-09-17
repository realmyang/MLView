#!/usr/bin/env python3
"""Prepare and summarize human-reviewed native-host pilot records; never run a model."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals/workflow/tasks.json"
PAIRS = ("observedClaims", "inferredClaims", "essentialFacts", "anchors")


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
    summary = sub.add_parser("summarize")
    summary.add_argument("records", type=Path)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        value = plan(manifest) if args.command == "plan" else summarize(
            json.loads(args.records.read_text(encoding="utf-8")), manifest)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
