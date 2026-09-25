#!/usr/bin/env python3
"""Python side of the MLView conformance corpus (contracts/conformance/README.md).

Every case in ``cases/`` is self-contained. This module materialises a case
into a temporary workspace and reports what two layers say about it:

* the helper: ``artifact.validate(doc, root, warnings=w)`` from
  skills/mlview/scripts/artifact.py, reduced to ``{ok, codes, warnings,
  fingerprints, stale}`` exactly as the case format defines them. A ``raw``
  case is parsed with ``artifact._parse``, which applies the CLI's rules
  (unique members, no NaN or Infinity, at most 64 levels of nesting);
* the strict schema layer: contracts/workflow.schema.json under Draft 2020-12
  with full-match ``pattern`` semantics (ECMA-262 for the schema's anchored
  patterns) and a stdlib RFC 3339 ``date-time`` check that mirrors the helper.

tools/test_workflow_conformance.py imports it. The extension runner
(vscode-extension/test/conformance.test.js) runs it as a subprocess:

    python contracts/conformance/helper_bridge.py [CASE.json ...]

which prints one JSON object ``{"schemaLayer": bool, "cases": {"<id>":
{"helper": {...}, "schema": "valid" | "invalid" | null}}}``. Without
arguments every case in ``cases/`` is reported. ``schema`` is null when
jsonschema (requirements-dev.txt) is not installed. The helper layer is
stdlib-only. The bridge never publishes and never runs target code.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASES_DIR = HERE / "cases"
HELPER = ROOT / "skills" / "mlview" / "scripts" / "artifact.py"
SCHEMA = ROOT / "contracts" / "workflow.schema.json"

AREAS = ("shape", "path", "evidence", "notebook", "fingerprint", "freshness", "encoding", "revision", "size")
CASE_ID = re.compile(r"([a-z]+)-(\d{3})-([a-z0-9]+(?:-[a-z0-9]+)*)", re.ASCII)
CASE_KEYS = {"id", "findings", "description", "files", "artifact", "document", "raw", "expect", "divergence"}
HELPER_KEYS = {"ok", "codes", "warnings", "fingerprints", "stale"}
EXTENSION_KEYS = {"ok", "stale", "issuePaths"}
MAX_CASE_BYTES = 100 * 1024
# RFC 3339 date-time with a mandatory offset, the shape artifact.py accepts.
RFC3339 = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))", re.ASCII)


def load_helper() -> Any:
    spec = importlib.util.spec_from_file_location("mlview_artifact_conformance", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def case_paths() -> list[Path]:
    return sorted(CASES_DIR.glob("*.json"))


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def content(spec: Any) -> bytes:
    """Bytes of a file specification: {"text"} (UTF-8, no newline translation), {"base64"} or {"generate"}."""
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError("a file specification has exactly one of text, base64 or generate")
    if "text" in spec and isinstance(spec["text"], str):
        return spec["text"].encode("utf-8")
    if "base64" in spec and isinstance(spec["base64"], str):
        return base64.b64decode(spec["base64"], validate=True)
    if "generate" in spec and isinstance(spec["generate"], dict) and set(spec["generate"]) == {"bytes", "fill"}:
        fill, size = spec["generate"]["fill"], spec["generate"]["bytes"]
        if isinstance(fill, str) and len(fill) == 1 and fill.isascii() and isinstance(size, int) and not isinstance(size, bool) and size >= 0:
            return fill.encode("ascii") * size
    raise ValueError(f"unsupported file specification: {sorted(spec)}")


def substitute(value: Any) -> Any:
    """Replace every {"$sha256": <file specification>} placeholder with its lowercase hex digest."""
    if isinstance(value, dict):
        if set(value) == {"$sha256"}:
            return hashlib.sha256(content(value["$sha256"])).hexdigest()
        return {key: substitute(child) for key, child in value.items()}
    if isinstance(value, list):
        return [substitute(child) for child in value]
    return value


def artifact_bytes(case: dict[str, Any]) -> bytes:
    """The artifact file as both runners write it: `raw` verbatim, else the document as indented JSON."""
    if "raw" in case:
        return case["raw"].encode("utf-8")
    # ensure_ascii keeps unpaired surrogates encodable (as escapes), as JSON.stringify does.
    return (json.dumps(substitute(case["document"]), indent=2) + "\n").encode("utf-8")


def materialise(case: dict[str, Any], root: Path) -> None:
    for rel, spec in case["files"].items():
        target = root.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content(spec))
    target = root.joinpath(*PurePosixPath(case["artifact"]).parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(artifact_bytes(case))


def helper_result(case: dict[str, Any], root: Path, helper: Any) -> dict[str, Any]:
    """The helper layer of a materialised case, in the case format's terms."""
    if "raw" in case:
        try:
            doc = helper._parse(case["raw"].encode("utf-8"))
        except (UnicodeError, ValueError, RecursionError):
            return {"ok": False, "codes": ["invalid_json"], "warnings": [], "fingerprints": None, "stale": []}
    else:
        doc = substitute(case["document"])
    warnings: list[dict[str, str]] = []
    errors, hashes = helper.validate(doc, root, warnings=warnings)
    return {
        "ok": not errors,
        "codes": sorted({error["code"] for error in errors}),
        "warnings": sorted({warning["code"] for warning in warnings}),
        "fingerprints": hashes,
        "stale": sorted({error["file"] for error in errors if error["code"] == "stale_source"}),
    }


def rfc3339_date_time(value: object) -> bool:
    """Strict RFC 3339 date-time with an offset: calendar date, hour <= 23, minute and second <= 59."""
    if not isinstance(value, str):
        return True  # `format` constrains strings only; `type` handles the rest.
    match = RFC3339.fullmatch(value)
    if not match:
        return False
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    offset_hour, offset_minute = (int(part) if part is not None else 0 for part in match.groups()[6:])
    if offset_hour > 23 or offset_minute > 59:
        return False
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError:
        return False
    return True


def strict_validator() -> Any:
    """The schema layer, or None when jsonschema is not installed."""
    try:
        from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
    except ImportError:
        return None

    def full_match_pattern(validator: Any, pattern: str, instance: Any, schema: Any):
        # Python's re.search lets `$` match before a trailing newline; ECMA-262 does not.
        # Every schema pattern is anchored (^...$), so a full match is the ECMA-262 result.
        if validator.is_type(instance, "string") and re.fullmatch(pattern, instance) is None:
            yield ValidationError(f"{instance!r} does not match {pattern!r}")

    checker = FormatChecker(formats=())
    checker.checks("date-time")(rfc3339_date_time)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    strict = validators.extend(Draft202012Validator, {"pattern": full_match_pattern})
    return strict(schema, format_checker=checker)


def schema_patterns(value: Any) -> list[str]:
    if isinstance(value, dict):
        found = [value["pattern"]] if isinstance(value.get("pattern"), str) else []
        for child in value.values():
            found.extend(schema_patterns(child))
        return found
    if isinstance(value, list):
        return [pattern for child in value for pattern in schema_patterns(child)]
    return []


def schema_document(case: dict[str, Any]) -> tuple[bool, Any]:
    """What a plain JSON consumer sees: (parsed, value). A `raw` BOM, syntax error, NaN or Infinity
    does not parse (JSON.parse rejects all of them; Python's json module accepts the constants)."""
    if "raw" not in case:
        return True, substitute(case["document"])
    try:
        return True, json.loads(case["raw"], parse_constant=_not_json)
    except ValueError:
        return False, None


def _not_json(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def schema_result(case: dict[str, Any], validator: Any) -> str:
    parsed, doc = schema_document(case)
    return "valid" if parsed and validator.is_valid(doc) else "invalid"


def case_problems(path: Path, case: Any) -> list[str]:
    """Format violations of one committed case file (empty when well formed)."""
    problems: list[str] = []
    if path.stat().st_size > MAX_CASE_BYTES:
        problems.append(f"larger than {MAX_CASE_BYTES} bytes")
    if not isinstance(case, dict):
        return problems + ["a case must be a JSON object"]
    if set(case) - CASE_KEYS:
        problems.append(f"unknown keys {sorted(set(case) - CASE_KEYS)}")
    match = CASE_ID.fullmatch(case.get("id", "")) if isinstance(case.get("id"), str) else None
    if case.get("id") != path.stem:
        problems.append("id must equal the file stem")
    if match is None or match.group(1) not in AREAS:
        problems.append("id must be <area>-<nnn>-<kebab-slug> with a known area")
    findings = case.get("findings")
    if not isinstance(findings, list) or not findings or not all(isinstance(item, str) and item for item in findings):
        problems.append("findings must be a non-empty list of finding IDs")
    if not isinstance(case.get("description"), str) or not case.get("description"):
        problems.append("description must be a non-empty string")
    if ("document" in case) == ("raw" in case):
        problems.append("exactly one of document or raw is required")
    elif "document" in case and not isinstance(case["document"], dict):
        problems.append("document must be an object")
    elif "raw" in case and not isinstance(case["raw"], str):
        problems.append("raw must be a string")
    artifact = case.get("artifact")
    if not isinstance(artifact, str) or not artifact.lower().endswith(".mlview.json") or artifact.startswith("/") or "\\" in artifact:
        problems.append("artifact must be a relative POSIX path ending in .mlview.json")
    files = case.get("files")
    if not isinstance(files, dict):
        problems.append("files must be an object")
        files = {}
    folded: set[str] = set()
    for rel, spec in files.items():
        if "\\" in rel or rel.startswith("/") or any(part in {"", ".", ".."} for part in rel.split("/")):
            problems.append(f"file path {rel!r} must be relative POSIX")
        if rel.lower() in folded:
            problems.append(f"file path {rel!r} has a case-only sibling")
        folded.add(rel.lower())
        if rel == artifact:
            problems.append("the artifact is written by the runners; do not list it in files")
        try:
            content(spec)
        except (ValueError, TypeError) as exc:
            problems.append(f"file {rel!r}: {exc}")
    expect = case.get("expect")
    if not isinstance(expect, dict) or set(expect) != {"schema", "helper", "extension"}:
        return problems + ["expect must have exactly schema, helper and extension"]
    if expect["schema"] not in ("valid", "invalid", "skip"):
        problems.append("expect.schema must be valid, invalid or skip")
    for layer, keys in (("helper", HELPER_KEYS), ("extension", EXTENSION_KEYS)):
        if expect[layer] == "unverified":
            problems.append(f"expect.{layer} is still unverified")
        elif not isinstance(expect[layer], dict) or set(expect[layer]) != keys:
            problems.append(f"expect.{layer} must have exactly {sorted(keys)}")
    divergence = case.get("divergence")
    if divergence is not None:
        if not isinstance(divergence, dict) or set(divergence) != {"layers", "findings", "note", "status"}:
            problems.append("divergence must be null or {layers, findings, note, status}")
        elif divergence["status"] != "accepted":
            problems.append(f"divergence status {divergence['status']!r}: no open divergence may remain")
        elif not divergence["layers"] or not divergence["findings"] or not divergence["note"]:
            problems.append("an accepted divergence names its layers, findings and a note")
    return problems


def report(paths: list[Path]) -> dict[str, Any]:
    helper = load_helper()
    validator = strict_validator()
    cases: dict[str, Any] = {}
    for path in paths:
        case = load_case(path)
        with tempfile.TemporaryDirectory(prefix="mlview-conformance-") as temp:
            root = Path(temp).resolve()
            materialise(case, root)
            cases[case["id"]] = {
                "helper": helper_result(case, root, helper),
                "schema": schema_result(case, validator) if validator is not None else None,
            }
    return {"schemaLayer": validator is not None, "cases": cases}


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv] if argv else case_paths()
    sys.stdout.write(json.dumps(report(paths), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
