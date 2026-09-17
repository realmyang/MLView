#!/usr/bin/env python3
"""Prepare and summarize human-reviewed native-host pilot records; never run a model."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
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
NATIVE_ARTIFACT_MANIFEST = ROOT / "evals/workflow/development/native-artifacts/manifest.json"


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
    cells = notebook.get("cells")
    if (type(cell) is not int or cell < 0 or not isinstance(cells, list)
            or cell >= len(cells) or not isinstance(cells[cell], dict)):
        raise ValueError("invalid notebook cell index")
    source = cells[cell].get("source")
    if isinstance(source, str):
        text = source
    elif isinstance(source, list) and all(isinstance(line, str) for line in source):
        text = "".join(source)
    else:
        raise ValueError("invalid notebook cell source")
    return text.splitlines()


def _evidence_location(source: dict) -> str:
    location = str(source["file"])
    if "jsonPointer" in source:
        return f"{location} — JSON Pointer {source['jsonPointer']}"
    if "cell" in source:
        location += f" — cell {source['cell']}"
    if "line" in source:
        location += f" — lines {source['line']}-{source.get('endLine', source['line'])}"
    return location


def _validate_source_excerpt(source: dict, root: Path, label: str) -> None:
    lines = _source_lines(_confined_path(source.get("file"), root), source.get("cell"))
    start, end = source.get("line"), source.get("endLine", source.get("line"))
    if (type(start) is not int or type(end) is not int or start < 1
            or end < start or end > len(lines)):
        raise ValueError(f"invalid {label} source range")
    quote = source.get("quote")
    if not isinstance(quote, str) or not quote:
        raise ValueError(f"{label} requires a nonempty source quote")
    if "\n".join(lines[start - 1:end]) != quote:
        raise ValueError(f"{label} source quote mismatch: {source.get('id')}")


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
    if task not in DEVELOPMENT_ARTIFACTS:
        raise ValueError("development review task and artifact do not match")
    smoke_artifact = artifact_path == DEVELOPMENT_ARTIFACTS[task]
    native_registration = None
    if not smoke_artifact:
        host = review.get("host")
        if host is None:
            raise ValueError("development review task and artifact do not match")
        manifest_path = root / NATIVE_ARTIFACT_MANIFEST.relative_to(ROOT)
        if not manifest_path.is_file():
            raise ValueError("native artifact manifest is unavailable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        matches = [entry for entry in manifest.get("artifacts", [])
                   if entry.get("task") == task and entry.get("host") == host]
        if len(matches) != 1:
            raise ValueError("native review task and host are not uniquely registered")
        native_registration = matches[0]
        registered_path = str(
            NATIVE_ARTIFACT_MANIFEST.parent.relative_to(ROOT) / native_registration["path"]
        )
        if artifact_path != registered_path:
            raise ValueError("native review artifact path is not the registered task/host artifact")
        for field, registered_field in (("artifactSha256", "sha256"),
                                        ("artifactRevision", "revision")):
            if review.get(field) != native_registration.get(registered_field):
                raise ValueError(f"native review {field} differs from the artifact manifest")
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
    claim_ids = [claim.get("id") for claim in claims]
    if (any(not isinstance(claim_id, str) or not claim_id.strip() for claim_id in claim_ids)
            or len(set(claim_ids)) != len(claim_ids)):
        raise ValueError("development review requires nonempty unique claim IDs")
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
            _validate_source_excerpt(item, root, "review evidence")
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


def validate_baselines(value: dict, manifest: dict, root: Path = ROOT) -> list[dict]:
    """Validate public, provisional baseline notes without requiring private captures."""
    if (value.get("version") != 1 or value.get("reviewerType") != "model-provisional"
            or value.get("reviewStatus") != "pending-human-review"
            or value.get("humanReview") is not None):
        raise ValueError("baseline notes must remain model-provisional and pending human review")
    baselines = value.get("baselines")
    if not isinstance(baselines, list) or len(baselines) != len(manifest["hosts"]):
        raise ValueError("baseline notes must contain exactly one entry per host")
    expected_hosts = set(manifest["hosts"])
    if {item.get("host") for item in baselines} != expected_hosts:
        raise ValueError("baseline notes hosts do not match the native matrix")
    for item in baselines:
        if item.get("id") != f"dev-config:{item.get('host')}:baseline" or item.get("task") != "dev-config":
            raise ValueError("baseline note identity differs from the planned matrix")
        digest = item.get("responseSha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("baseline note requires a lowercase response SHA-256")
        if not all(isinstance(item.get(field), str) and item[field].strip()
                   for field in ("captureKind", "summary")):
            raise ValueError("baseline note requires captureKind and summary")
        evidence = item.get("reviewEvidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("baseline note requires exact source evidence")
        indexed = {}
        for source in evidence:
            source_id = source.get("id")
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("baseline evidence requires a nonempty ID")
            if source_id in indexed:
                raise ValueError("duplicate baseline evidence ID")
            indexed[source_id] = source
            _validate_source_excerpt(source, root, "baseline evidence")
        for group in ("strengths", "gaps"):
            entries = item.get(group)
            if not isinstance(entries, list):
                raise ValueError(f"baseline note requires {group}")
            for entry in entries:
                refs = entry.get("sourceReferences")
                if not isinstance(entry.get("summary"), str) or not isinstance(refs, list) or not refs:
                    raise ValueError(f"baseline {group} require summaries and source references")
                if any(ref not in indexed for ref in refs):
                    raise ValueError(f"baseline {group} references unknown evidence")
        if item.get("humanReview") is not None:
            raise ValueError("baseline entry cannot supply human review")
    return baselines


def _artifact_evidence(review: dict, root: Path) -> dict[str, dict]:
    artifact = json.loads(_confined_path(review["artifact"], root).read_text(encoding="utf-8"))
    return {item["id"]: item for item in artifact.get("evidence", [])} | {
        item["id"]: item for item in review.get("reviewEvidence", [])
    }


def _load_baseline_captures(path: Path, baselines: list[dict], root: Path) -> dict[str, str]:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    expected = {item["host"] for item in baselines}
    if not isinstance(mapping, dict) or set(mapping) != expected:
        raise ValueError("baseline capture mapping must contain exactly one path per host")
    captures = {}
    by_host = {item["host"]: item for item in baselines}
    for host, capture_path in mapping.items():
        capture_file = _verify_file(capture_path, by_host[host]["responseSha256"], root)
        captures[host] = capture_file.read_text(encoding="utf-8")
    return captures


def generate_review_packet(review_dir: Path, baselines_path: Path, output: Path,
                           manifest: dict, root: Path = ROOT,
                           baseline_captures_path: Path | None = None) -> None:
    """Render reviewer-authored ledgers; this function makes no semantic judgments."""
    baseline_resolved = baselines_path.resolve()
    review_paths = sorted(path for path in review_dir.glob("**/*.json")
                          if path.resolve() != baseline_resolved)
    reviews = [json.loads(path.read_text(encoding="utf-8")) for path in review_paths]
    expected = {(task, host) for task in DEVELOPMENT_TASKS for host in manifest["hosts"]}
    identities = [(review.get("task"), review.get("host")) for review in reviews]
    if len(reviews) != 12 or set(identities) != expected or len(set(identities)) != len(identities):
        raise ValueError("review packet requires exactly the complete 4-task by 3-host native matrix")
    for review in reviews:
        validate_development_review(review, root)
    baseline_value = json.loads(baselines_path.read_text(encoding="utf-8"))
    baselines = validate_baselines(baseline_value, manifest, root)
    captures = (_load_baseline_captures(baseline_captures_path, baselines, root)
                if baseline_captures_path is not None else None)

    esc = lambda value: html.escape(str(value), quote=True)
    parts = ["<!doctype html><html><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>MLView provisional native review packet</title><style>",
             "body{font:15px/1.45 system-ui,sans-serif;max-width:1100px;margin:auto;padding:2rem;color:#18202a}",
             "h1,h2{border-bottom:1px solid #ccd4dd;padding-bottom:.3rem}article{border:1px solid #ccd4dd;border-radius:8px;padding:1rem;margin:1rem 0}",
             ".pending{background:#fff3cd;padding:.8rem;border:2px solid #9b7300}.meta{color:#465365}pre{white-space:pre-wrap;background:#f4f6f8;padding:.7rem;overflow-wrap:anywhere}",
             "details{margin:.6rem 0}.verdict{font-weight:700}.decision{border:1px dashed #687789;padding:.6rem;margin:.6rem 0}",
             "@media print{body{max-width:none;padding:0}article{break-inside:avoid}details{display:block}details>*{display:block}}",
             "</style></head><body><h1>MLView provisional native review packet</h1>",
             "<p class='pending'><strong>Human adjudication pending.</strong> Every claim and usability answer below was authored provisionally by a model. This packet validates artifact identity and exact source excerpts; it does not validate semantic correctness.</p>",
             "<p class='filters'>Filter: <label>task <select id='task-filter'><option value=''>all</option>" +
             "".join(f"<option>{esc(task)}</option>" for task in DEVELOPMENT_TASKS) +
             "</select></label> <label>host <select id='host-filter'><option value=''>all</option>" +
             "".join(f"<option>{esc(host)}</option>" for host in manifest["hosts"]) +
             "</select></label></p>",
             "<p>Return decisions by artifact identity and claim ID, for example: <code>dev-gan / codex / optimizer-ownership: supported — rationale…</code>. For usability, use <code>dev-gan / codex / usability.losses: clear — rationale…</code>. Include your name and review date separately; do not edit provisional fields into human decisions.</p>"]
    by_identity = {(review["task"], review["host"]): review for review in reviews}
    for task in DEVELOPMENT_TASKS:
        parts.append(f"<section><h2>{esc(task)}</h2>")
        for host in manifest["hosts"]:
            review = by_identity[(task, host)]
            evidence = _artifact_evidence(review, root)
            output_parent = output.parent.resolve()
            artifact_label = esc(review["artifact"])
            if output_parent == root.resolve() or root.resolve() in output_parent.parents:
                href = Path(os.path.relpath(root / review["artifact"], output_parent)).as_posix()
                artifact_label = f"<a href='{esc(href)}'>{artifact_label}</a>"
            parts.extend([f"<article data-task='{esc(task)}' data-host='{esc(host)}'><h3>{esc(host)}</h3>",
                          f"<p class='meta'>Artifact: {artifact_label}<br>Revision: <code>{esc(review['artifactRevision'])}</code><br>SHA-256: <code>{esc(review['artifactSha256'])}</code></p>",
                          "<p class='pending'>Pending human review; provisional claim labels are not adjudication.</p><h4>Claims</h4>"])
            for claim in review["claims"]:
                parts.append(f"<details open><summary><span class='verdict'>{esc(claim['id'])}: {esc(claim['verdict'])}</span> — {esc(claim['summary'])}</summary>")
                parts.append(f"<p>Artifact pointers: {esc(', '.join(claim['artifactPointers']) or 'none')}</p>")
                for ref in claim["sourceReferences"]:
                    source = evidence[ref]
                    location = _evidence_location(source)
                    quote = source.get("quote", json.dumps(source.get("value"), ensure_ascii=False, indent=2))
                    parts.append(f"<p><strong>{esc(ref)}</strong> — {esc(location)}</p><pre>{esc(quote)}</pre>")
                parts.append("<div class='decision'>Human decision: ______ &nbsp; Rationale: ____________________</div></details>")
            parts.append("<h4>Six usability questions</h4><dl>")
            for key in sorted(USABILITY_QUESTIONS):
                answer = review["usability"][key]
                parts.append(f"<dt><strong>{esc(key)}</strong> — provisional {esc(answer['status'])}</dt><dd>{esc(answer['answer'])}<br>Artifact pointers: {esc(', '.join(answer['artifactPointers']) or 'none')}<div class='decision'>Human decision: ______ &nbsp; Rationale: ____________________</div></dd>")
            parts.append("</dl></article>")
        parts.append("</section>")
    capture_note = ("Native capture hashes are recorded; raw responses are not bundled."
                    if captures is None else
                    "Native capture hashes were verified; raw responses are included in this private local packet.")
    parts.append(f"<section><h2>Matched no-skill baseline comparisons (dev-config)</h2><p class='pending'>These are provisional summaries. {capture_note}</p>")
    if captures is not None:
        parts.append("<p class='pending'><strong>Private raw captures included.</strong> This local packet contains native-assistant response text supplied explicitly with <code>--baseline-captures</code>. Do not publish or commit it without a separate privacy review.</p>")
    for item in sorted(baselines, key=lambda entry: entry["host"]):
        parts.append(f"<article><h3>{esc(item['host'])}</h3><p>{esc(item['summary'])}</p><p class='meta'>Capture: {esc(item['captureKind'])}<br>Response SHA-256: <code>{esc(item['responseSha256'])}</code></p>")
        for label in ("strengths", "gaps"):
            parts.append(f"<h4>{esc(label.title())}</h4><ul>")
            for note in item[label]:
                parts.append(f"<li>{esc(note['summary'])} <small>Sources: {esc(', '.join(note['sourceReferences']))}</small></li>")
            parts.append("</ul>")
        for source in item["reviewEvidence"]:
            parts.append(f"<details><summary>{esc(source['id'])} — {esc(_evidence_location(source))}</summary><pre>{esc(source['quote'])}</pre></details>")
        if captures is not None:
            parts.append(f"<details><summary>Private raw response — hash verified</summary><pre>{esc(captures[item['host']])}</pre></details>")
        parts.append("<div class='decision'>Human baseline comparison: ______ &nbsp; Rationale: ____________________</div></article>")
    parts.append("</section><script>for(const id of ['task-filter','host-filter'])document.getElementById(id).addEventListener('change',()=>{const t=document.getElementById('task-filter').value,h=document.getElementById('host-filter').value;for(const a of document.querySelectorAll('article[data-task]'))a.hidden=!!((t&&a.dataset.task!==t)||(h&&a.dataset.host!==h))})</script></body></html>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(parts), encoding="utf-8")


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
    packet = sub.add_parser("review-packet")
    packet.add_argument("--reviews", required=True, type=Path)
    packet.add_argument("--baselines", required=True, type=Path)
    packet.add_argument("--baseline-captures", type=Path)
    packet.add_argument("--output", required=True, type=Path)
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
        elif args.command == "review-packet":
            generate_review_packet(args.reviews, args.baselines, args.output, manifest,
                                   baseline_captures_path=args.baseline_captures)
            value = {"ok": True, "output": str(args.output), "reviews": 12,
                     "baselines": len(manifest["hosts"]),
                     "note": "Packet contains validated provisional material; human adjudication remains pending."}
        else:
            value = summarize(json.loads(args.records.read_text(encoding="utf-8")), manifest)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
