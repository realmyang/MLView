#!/usr/bin/env python3
"""Development-run records and review packets, plus the dispatcher for the Campaign 2 evaluation
commands (tools/workflow_decisions.py, tools/workflow_pilot.py). Never runs a model."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import eval_records  # noqa: E402  (the shared Campaign 2 primitives; stdlib only)

MANIFEST = ROOT / "evals/workflow/tasks.json"
# Commands owned by other tools. main() imports the tool lazily and calls its main(argv) with the
# full argument list, command name first; a build without the tool says so (exit status 2).
ROUTED_COMMANDS = {
    "template": ("workflow_decisions", "write a pending decisions template (exclusive create)"),
    "check": ("workflow_decisions", "check owner decision, run-policy, adjudication, session and run-review files; never writes"),
    "context": ("workflow_decisions", "write a local, gitignored source-context sheet for reviewing one task"),
    "freeze": ("workflow_decisions", "freeze a campaign from completed human decisions (dry run unless --write)"),
    "check-frozen": ("workflow_decisions", "re-derive the committed frozen campaign files and require byte equality"),
    "plan": ("workflow_pilot", "print the planned pilot runs and conditions"),
    "run-prepare": ("workflow_pilot", "prepare one pilot run's fresh workspace and evidence directory"),
    "run-finish": ("workflow_pilot", "seal one pilot run's evidence into record.json"),
    "review-template": ("workflow_pilot", "create the pending human review file of one pilot run"),
    "summarize": ("workflow_pilot", "verify sealed pilot runs and compute a stage summary against the predefined targets"),
}
UNAVAILABLE = "not available in this build"
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


def development_plan(manifest: dict) -> list[dict]:
    """Prepare pending native-host development runs and a small matched baseline."""
    tasks = {task["id"]: task for task in manifest["tasks"]}
    records = []
    cases = [(task_id, "skill") for task_id in DEVELOPMENT_TASKS] + [("dev-config", "baseline")]
    for task_id, condition in cases:
        task = tasks[task_id]
        for host in manifest["hosts"]:
            records.append({
                "id": f"{task_id}:{host}:{condition}", "task": task_id, "host": host,
                "condition": condition, "status": "pending-native-run",
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


def historical_source(value: object, root: Path = ROOT) -> Path:
    """Resolve a recorded source citation after the fixture-only relocation.

    This mapping is confined to evaluation replay. Published artifacts and the
    product validator still require their actual workspace-relative paths.
    Exact hashes ensure moved fixtures cannot silently alter historical evidence.
    """
    direct = _confined_path(value, root, require_file=False)
    mapping_file = root / "evals/workflow/fixtures/historical-paths.json"
    if mapping_file.is_file():
        mapping = json.loads(mapping_file.read_text(encoding="utf-8"))["paths"]
        if value in mapping:
            entry = mapping[value]
            return _verify_file(entry["path"], entry["sha256"], root)
    if direct.is_file():
        return direct
    raise ValueError(f"historical source does not exist: {value}")


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
    """The lines the product helper compares quotes against (EVAL-15): UTF-8 with the BOM stripped,
    split only on CRLF, CR and LF, keeping a trailing empty element; a notebook cell's joined source.
    Delegates to eval_records.source_lines, which uses the helper's own functions."""
    return eval_records.source_lines(path.read_bytes(), cell)


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
    """Replay one recorded excerpt with the helper's rules: an integer endLine is required (it is
    no longer defaulted to line), and the quote must equal the cited lines exactly, except that a
    line-1 quote may include or omit a byte-order mark (EVAL-15)."""
    lines = _source_lines(historical_source(source.get("file"), root), source.get("cell"))
    start, end = source.get("line"), source.get("endLine")
    if (type(start) is not int or type(end) is not int or start < 1
            or end < start or end > len(lines)):
        raise ValueError(f"invalid {label} source range")
    quote = source.get("quote")
    if not isinstance(quote, str) or not quote:
        raise ValueError(f"{label} requires a nonempty source quote")
    if not eval_records.quote_matches(quote, lines, start, end):
        raise ValueError(f"{label} source quote mismatch: {source.get('id')}")


def _json_pointer(value: object, pointer: str) -> object:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("JSON Pointer must be empty or start with /")
    current = value
    for raw in pointer[1:].split("/") if pointer else []:
        if re.search(r"~(?![01])", raw):
            raise ValueError("invalid JSON Pointer escape")
        key = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", key):
                    raise ValueError("invalid JSON Pointer array index")
                current = current[int(key)]
            elif isinstance(current, dict):
                current = current[key]
            else:
                raise ValueError("JSON Pointer does not resolve")
        except (KeyError, IndexError) as exc:
            raise ValueError("JSON Pointer does not resolve") from exc
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
    # EVAL-5: only a ledger without a "host" key is a developer-subagent smoke review. A ledger that
    # names a host (even the smoke artifact's path) must match the native artifact registration.
    native_registration = None
    if "host" not in review:
        if artifact_path != DEVELOPMENT_ARTIFACTS[task]:
            raise ValueError("development review task and artifact do not match")
    else:
        host = review.get("host")
        manifest_path = root / NATIVE_ARTIFACT_MANIFEST.relative_to(ROOT)
        if not manifest_path.is_file():
            raise ValueError("native artifact manifest is unavailable")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        matches = [entry for entry in manifest.get("artifacts", [])
                   if entry.get("task") == task and entry.get("host") == host]
        if len(matches) != 1:
            raise ValueError("native review task and host are not uniquely registered")
        native_registration = matches[0]
        registered_path = (
            NATIVE_ARTIFACT_MANIFEST.parent.relative_to(ROOT) / native_registration["path"]
        ).as_posix()
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
                source_path = historical_source(item["file"], root)
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
        if pointer == "configuration":  # request.configuration (Campaign 2 specification, section 4.4)
            request = artifact.get("request")
            if not isinstance(request, dict) or "configuration" not in request:
                raise ValueError("artifact pointer does not resolve: configuration")
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
                           baseline_captures_path: Path | None = None, *, force: bool = False) -> None:
    """Render reviewer-authored ledgers; this function makes no semantic judgments.

    The output is created exclusively (EVAL-4); ``force`` replaces an existing file atomically,
    which is safe because the packet is derived from committed ledgers."""
    if not force and os.path.lexists(output):
        raise ValueError(f"{output} already exists; the packet is derived, so pass --force to replace it")
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
             "<p>Record your decisions in <code>evals/workflow/decisions/development-adjudication.md</code>: under <code>## dev-gan / codex</code> replace <code>optimizer-ownership: pending</code> with, for example, <code>optimizer-ownership: supported</code>, and <code>usability.losses: pending</code> with <code>usability.losses: clear</code>. Add <code> — reason</code> whenever you differ from the provisional label. Fill Reviewer and Date there, then run <code>python tools/workflow_eval.py check development-adjudication</code>. Do not edit the provisional ledgers; they stay immutable.</p>"]
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
    data = "".join(parts).encode("utf-8")
    if force:
        eval_records.write_atomic(output, data)
    else:
        eval_records.write_exclusive(output, data)


def load_tool(name: str) -> ModuleType | None:
    """Import tools/<name>.py on first use; None when this build does not ship it."""
    path = TOOLS / f"{name}.py"
    if not path.is_file():
        return None
    loaded = sys.modules.get(name)
    loaded_file = getattr(loaded, "__file__", None)
    if loaded is not None and loaded_file and Path(loaded_file).resolve() == path.resolve():
        return loaded
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))  # the tool imports its sibling eval_records
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def build_parser() -> argparse.ArgumentParser:
    """The command list for --help. Routed commands are parsed by their own tool."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for command, (tool, text) in ROUTED_COMMANDS.items():
        if (TOOLS / f"{tool}.py").is_file():
            sub.add_parser(command, help=f"{text} (tools/{tool}.py)", add_help=False)
        else:
            sub.add_parser(command, help=f"{text} [{UNAVAILABLE}: tools/{tool}.py is missing]", add_help=False)
    development = sub.add_parser("development-plan", help="print the pending native development-run records")
    development.add_argument("--output", type=Path,
                             help="also create this file (exclusive: an existing file is never overwritten)")
    development_summary = sub.add_parser("summarize-development",
                                         help="summarize native development-run records; makes no human-review judgement")
    development_summary.add_argument("records", type=Path)
    validate = sub.add_parser("validate-development",
                              help="validate provisional native development reviews (exact anchors, pending status)")
    validate.add_argument("reviews", nargs="+", type=Path)
    packet = sub.add_parser("review-packet", help="write the development review packet for human adjudication")
    packet.add_argument("--reviews", required=True, type=Path)
    packet.add_argument("--baselines", required=True, type=Path)
    packet.add_argument("--baseline-captures", type=Path)
    packet.add_argument("--output", required=True, type=Path,
                        help="the HTML file to create; an existing file is refused unless --force")
    packet.add_argument("--force", action="store_true",
                        help="replace an existing packet (it is derived from the committed ledgers)")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    eval_records.safe_streams()
    if arguments and arguments[0] in ROUTED_COMMANDS:
        command = arguments[0]
        tool = ROUTED_COMMANDS[command][0]
        module = load_tool(tool)
        if module is not None:
            return int(module.main(arguments) or 0)
        print(f"workflow_eval.py {command}: {UNAVAILABLE} (tools/{tool}.py is missing)", file=sys.stderr)
        return 2
    parser = build_parser()
    args = parser.parse_args(arguments)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        if args.command == "development-plan":
            value = development_plan(manifest)
            if args.output is not None:
                data = (json.dumps(value, indent=2) + "\n").encode("utf-8")
                try:
                    eval_records.write_exclusive(args.output, data)
                except FileExistsError:
                    raise ValueError(f"{args.output} already exists; it may hold recorded run data, so it is never "
                                     "overwritten. Choose a new file name.") from None
                value = {"ok": True, "output": str(args.output), "records": len(value),
                         "note": "Pending development-run records written; nothing was run."}
        elif args.command == "validate-development":
            for path in args.reviews:
                validate_development_review(json.loads(path.read_text(encoding="utf-8")))
            value = {"ok": True, "validated": len(args.reviews),
                     "note": "Exact anchors and pending status validated; semantics remain unscored."}
        elif args.command == "summarize-development":
            value = summarize_development(json.loads(args.records.read_text(encoding="utf-8")), manifest)
        elif args.command == "review-packet":
            generate_review_packet(args.reviews, args.baselines, args.output, manifest,
                                   baseline_captures_path=args.baseline_captures, force=args.force)
            value = {"ok": True, "output": str(args.output), "reviews": 12,
                     "baselines": len(manifest["hosts"]),
                     "note": "Packet contains validated provisional material; human adjudication remains pending."}
        else:
            parser.error(f"{args.command}: {UNAVAILABLE}")
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
