#!/usr/bin/env python3
"""Validate and atomically publish MLView WorkflowDocument 1.0 artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MAX_DOCUMENT = 2 * 1024 * 1024
MAX_SOURCE = 8 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HOSTS = {"copilot", "codex", "claude-code", "unknown"}
BASES = {"observed", "inferred", "unresolved"}
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class Problems:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, code: str, path: str, message: str) -> None:
        self.items.append({"code": code, "path": path, "message": message})


def _relative(value: Any, root: Path, problems: Problems, path: str) -> tuple[str, Path] | None:
    if not isinstance(value, str) or not value or "\\" in value:
        problems.add("invalid_path", path, "must be a non-empty slash-separated relative path")
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        problems.add("path_outside_workspace", path, "must stay within the workspace")
        return None
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        problems.add("path_outside_workspace", path, "file is missing or resolves outside the workspace")
        return None
    if not resolved.is_file():
        problems.add("invalid_path", path, "must identify a regular file")
        return None
    return pure.as_posix(), resolved


def _read_source(path: Path, problems: Problems, at: str) -> tuple[bytes, str] | None:
    try:
        if path.stat().st_size > MAX_SOURCE:
            problems.add("source_too_large", at, f"cited source exceeds {MAX_SOURCE} bytes")
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_SOURCE + 1)
    except OSError:
        problems.add("source_read", at, "could not read cited source")
        return None
    if len(raw) > MAX_SOURCE:
        problems.add("source_too_large", at, f"cited source exceeds {MAX_SOURCE} bytes")
        return None
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.add("source_encoding", at, "cited source must be UTF-8")
        return None


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _validate_evidence(doc: dict[str, Any], root: Path, problems: Problems) -> dict[str, str]:
    hashes: dict[str, str] = {}
    cache: dict[str, tuple[bytes, str]] = {}
    for index, ev in enumerate(doc.get("evidence", [])):
        at = f"evidence[{index}]"
        if not isinstance(ev, dict):
            continue
        located = _relative(ev.get("file"), root, problems, f"{at}.file")
        if not located:
            continue
        rel, source_path = located
        content = cache.get(rel)
        if content is None:
            content = _read_source(source_path, problems, f"{at}.file")
            if content is None:
                continue
            cache[rel] = content
        raw, text = content
        hashes[rel] = hashlib.sha256(raw).hexdigest()
        if source_path.suffix.lower() == ".ipynb":
            cell = ev.get("cell")
            if not isinstance(cell, int) or isinstance(cell, bool) or cell < 0:
                problems.add("notebook_cell", f"{at}.cell", "notebook evidence requires a zero-based cell index")
                continue
            try:
                notebook = json.loads(text)
                cells = notebook["cells"]
                source = cells[cell]["source"]
                text = "".join(source) if isinstance(source, list) else source
                if not isinstance(text, str):
                    raise TypeError
            except (ValueError, KeyError, IndexError, TypeError):
                problems.add("notebook_cell", f"{at}.cell", "cell does not identify valid notebook source")
                continue
        elif "cell" in ev:
            problems.add("unexpected_cell", f"{at}.cell", "cell is only valid for .ipynb evidence")
            continue
        line, end = ev.get("line"), ev.get("endLine")
        lines = _lines(text)
        if not isinstance(line, int) or isinstance(line, bool) or not isinstance(end, int) or isinstance(end, bool) or line < 1 or end < line or end > len(lines):
            problems.add("range", at, "line range is invalid for the cited source")
            continue
        expected = "\n".join(lines[line - 1:end])
        if ev.get("quote") != expected:
            problems.add("quote_mismatch", f"{at}.quote", "quote does not exactly match the cited lines")
    return dict(sorted(hashes.items()))


def _validate_inspected(doc: dict[str, Any], root: Path, hashes: dict[str, str], problems: Problems) -> dict[str, str]:
    files = doc.get("coverage", {}).get("inspectedFiles", []) if isinstance(doc.get("coverage"), dict) else []
    for index, value in enumerate(files if isinstance(files, list) else []):
        located = _relative(value, root, problems, f"coverage.inspectedFiles[{index}]")
        if not located:
            continue
        rel, path = located
        if rel in hashes:
            continue
        content = _read_source(path, problems, f"coverage.inspectedFiles[{index}]")
        if content is not None:
            hashes[rel] = hashlib.sha256(content[0]).hexdigest()
    return dict(sorted(hashes.items()))


def _object(value: Any, at: str, required: set[str], allowed: set[str], p: Problems) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        p.add("type", at, "must be an object")
        return None
    for key in sorted(required - value.keys()): p.add("required", f"{at}.{key}", "field is required")
    for key in sorted(value.keys() - allowed): p.add("additional_property", f"{at}.{key}", "field is not allowed")
    return value


def _strings(value: Any, at: str, p: Problems) -> bool:
    if not isinstance(value, list): p.add("type", at, "must be an array"); return False
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item: p.add("type", f"{at}[{i}]", "must be a non-empty string")
    return True


def _optional_text(item: dict[str, Any], key: str, at: str, maximum: int, p: Problems, allow_empty: bool = False) -> None:
    if key in item and (not isinstance(item[key], str) or (not allow_empty and not item[key]) or len(item[key]) > maximum):
        qualifier = "a string" if allow_empty else "a non-empty string"
        p.add("type", f"{at}.{key}", f"must be {qualifier} of at most {maximum} characters")


def _max_text(item: dict[str, Any], key: str, at: str, maximum: int, p: Problems) -> None:
    if isinstance(item.get(key), str) and len(item[key]) > maximum: p.add("limit", f"{at}.{key}", f"must contain at most {maximum} characters")


def _basic_shape(doc: Any, p: Problems) -> None:
    if not isinstance(doc, dict):
        p.add("type", "$", "document must be an object")
        return
    required = {"workflowVersion", "title", "producer", "revision", "request", "phases", "nodes", "edges", "findings", "evidence", "coverage"}
    allowed = required | {"verification"}
    for key in sorted(required - doc.keys()): p.add("required", key, "field is required")
    for key in sorted(doc.keys() - allowed): p.add("additional_property", key, "field is not allowed")
    if doc.get("workflowVersion") != "1.0": p.add("version", "workflowVersion", "must equal '1.0'")
    if not isinstance(doc.get("title"), str) or not doc.get("title"): p.add("type", "title", "must be a non-empty string")
    elif len(doc["title"]) > 200: p.add("limit", "title", "must contain at most 200 characters")
    producer = doc.get("producer")
    producer = _object(producer, "producer", {"kind", "host"}, {"kind", "host", "model"}, p)
    if producer is None or producer.get("kind") != "host-llm" or not isinstance(producer.get("host"), str) or producer.get("host") not in HOSTS:
        p.add("producer", "producer", "must identify a supported host-llm producer")
    elif "model" in producer: _optional_text(producer, "model", "producer", 200, p)
    revision = doc.get("revision")
    revision = _object(revision, "revision", {"id"}, {"id", "parent"}, p)
    if revision is None or not _id(revision.get("id")):
        p.add("revision", "revision.id", "must be a valid ID")
    elif "parent" in revision and not _id(revision["parent"]): p.add("revision", "revision.parent", "must be a valid ID")
    elif revision.get("parent") == revision["id"]: p.add("revision", "revision.parent", "must differ from revision.id")
    request = doc.get("request")
    request = _object(request, "request", {"question", "scope"}, {"question", "scope", "entrypoints", "configuration"}, p)
    if request is None or not all(isinstance(request.get(k), str) and request[k] for k in ("question", "scope")):
        p.add("request", "request", "question and scope must be non-empty strings")
    elif request is not None:
        _max_text(request, "question", "request", 4000, p); _max_text(request, "scope", "request", 2000, p)
        if "entrypoints" in request:
            _strings(request["entrypoints"], "request.entrypoints", p)
            if isinstance(request["entrypoints"], list):
                if len(request["entrypoints"]) > 100: p.add("limit", "request.entrypoints", "must contain at most 100 items")
                for i, value in enumerate(request["entrypoints"]):
                    if isinstance(value, str) and len(value) > 500: p.add("limit", f"request.entrypoints[{i}]", "must contain at most 500 characters")
    if request is not None and "configuration" in request and (not isinstance(request["configuration"], str) or not request["configuration"]): p.add("type", "request.configuration", "must be a non-empty string")
    elif request is not None: _max_text(request, "configuration", "request", 2000, p)
    coverage = doc.get("coverage")
    coverage = _object(coverage, "coverage", {"status", "summary", "inspectedFiles", "limitations"}, {"status", "summary", "inspectedFiles", "limitations"}, p)
    if not isinstance(coverage, dict) or not isinstance(coverage.get("status"), str) or coverage.get("status") not in {"scoped", "partial"} or not isinstance(coverage.get("summary"), str) or not coverage.get("summary"):
        p.add("coverage", "coverage", "must include status and a non-empty summary")
    elif not isinstance(coverage.get("inspectedFiles"), list) or not isinstance(coverage.get("limitations"), list):
        p.add("coverage", "coverage", "inspectedFiles and limitations must be arrays")
    else:
        _strings(coverage["inspectedFiles"], "coverage.inspectedFiles", p)
        _strings(coverage["limitations"], "coverage.limitations", p)
        if len(coverage["inspectedFiles"]) > 2000: p.add("limit", "coverage.inspectedFiles", "must contain at most 2000 items")
        if len(coverage["limitations"]) > 500: p.add("limit", "coverage.limitations", "must contain at most 500 items")
        _max_text(coverage, "summary", "coverage", 4000, p)
        for key, maximum in (("inspectedFiles", 500), ("limitations", 2000)):
            for i, value in enumerate(coverage[key]):
                if isinstance(value, str) and len(value) > maximum: p.add("limit", f"coverage.{key}[{i}]", f"must contain at most {maximum} characters")
    verification = doc.get("verification")
    if verification is not None:
        verification = _object(verification, "verification", {"files", "publishedAt"}, {"files", "publishedAt"}, p)
        if verification is not None:
            published = verification.get("publishedAt")
            if not isinstance(published, str): p.add("type", "verification.publishedAt", "must be a string")
            else:
                try:
                    if not RFC3339_RE.fullmatch(published): raise ValueError
                    if not published.endswith("Z"):
                        offset_hour, offset_minute = published[-5:-3], published[-2:]
                        if int(offset_hour) > 23 or int(offset_minute) > 59: raise ValueError
                    parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if parsed.tzinfo is None: raise ValueError
                except ValueError: p.add("format", "verification.publishedAt", "must be an RFC 3339 date-time with timezone")
            files = verification.get("files")
            if not isinstance(files, dict): p.add("type", "verification.files", "must be an object")
            else:
                if len(files) > 2000: p.add("limit", "verification.files", "must contain at most 2000 entries")
                for key, digest in files.items():
                    if not isinstance(key, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest): p.add("fingerprint", "verification.files", "must map relative paths to lowercase SHA-256")
                    elif len(key) > 500: p.add("limit", "verification.files", "path keys must contain at most 500 characters")
    limits = {"phases": 100, "nodes": 2000, "edges": 4000, "findings": 1000, "evidence": 5000}
    for name, limit in limits.items():
        value = doc.get(name)
        if not isinstance(value, list): p.add("type", name, "must be an array")
        elif len(value) > limit: p.add("limit", name, f"must contain at most {limit} items")
    if isinstance(doc.get("phases"), list) and not doc["phases"]: p.add("required", "phases", "must not be empty")
    if isinstance(doc.get("nodes"), list) and not doc["nodes"]: p.add("required", "nodes", "must not be empty")
    for path, value in _walk_strings(doc):
        if len(value) > 16000: p.add("text_too_large", path, "string exceeds 16000 characters")
    path_lists = []
    if isinstance(request, dict): path_lists.append(("request.entrypoints", request.get("entrypoints", [])))
    for at, values in path_lists:
        if isinstance(values, list):
            for i, value in enumerate(values):
                if not isinstance(value, str) or PurePosixPath(value).is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")) or "\\" in value:
                    p.add("invalid_path", f"{at}[{i}]", "must be a slash-separated relative path")


def _walk_strings(value: Any, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items(): yield from _walk_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): yield from _walk_strings(child, f"{path}[{index}]")


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_RE.fullmatch(value))


def _references(doc: dict[str, Any], p: Problems) -> None:
    collections = {name: doc.get(name, []) for name in ("phases", "nodes", "edges", "findings", "evidence")}
    ids: dict[str, set[str]] = {}
    for name, items in collections.items():
        seen: set[str] = set()
        for i, item in enumerate(items if isinstance(items, list) else []):
            value = item.get("id") if isinstance(item, dict) else None
            if not _id(value): p.add("id", f"{name}[{i}].id", "must be a valid ID")
            elif value in seen: p.add("duplicate_id", f"{name}[{i}].id", "ID is duplicated in this collection")
            else: seen.add(value)
        ids[name] = seen
    for i, phase in enumerate(collections["phases"] if isinstance(collections["phases"], list) else []):
        phase = _object(phase, f"phases[{i}]", {"id", "label"}, {"id", "label"}, p)
        if phase is None or not isinstance(phase.get("label"), str) or not phase.get("label"):
            p.add("phase", f"phases[{i}]", "must have a non-empty label")
        elif len(phase["label"]) > 200: p.add("limit", f"phases[{i}].label", "must contain at most 200 characters")
    for i, ev in enumerate(collections["evidence"] if isinstance(collections["evidence"], list) else []):
        ev = _object(ev, f"evidence[{i}]", {"id", "file", "line", "endLine", "quote"}, {"id", "file", "line", "endLine", "quote", "cell"}, p)
        if ev is None: continue
        if not isinstance(ev.get("quote"), str): p.add("type", f"evidence[{i}].quote", "must be a string")
        elif len(ev["quote"]) > 16000: p.add("limit", f"evidence[{i}].quote", "must contain at most 16000 characters")
        if isinstance(ev.get("file"), str) and len(ev["file"]) > 500: p.add("limit", f"evidence[{i}].file", "must contain at most 500 characters")
    children: set[str] = set()
    parent_of: dict[str, str] = {}
    for i, node in enumerate(collections["nodes"] if isinstance(collections["nodes"], list) else []):
        node = _object(node, f"nodes[{i}]", {"id", "label", "phase", "basis", "evidence"}, {"id", "label", "phase", "parent", "kind", "detail", "basis", "evidence"}, p)
        if node is None: continue
        if not isinstance(node.get("label"), str) or not node.get("label"): p.add("type", f"nodes[{i}].label", "must be a non-empty string")
        elif len(node["label"]) > 300: p.add("limit", f"nodes[{i}].label", "must contain at most 300 characters")
        if not isinstance(node.get("phase"), str) or node.get("phase") not in ids["phases"]: p.add("reference", f"nodes[{i}].phase", "unknown phase ID")
        _optional_text(node, "kind", f"nodes[{i}]", 100, p)
        _optional_text(node, "detail", f"nodes[{i}]", 8000, p, allow_empty=True)
        parent = node.get("parent")
        if parent is not None:
            if not isinstance(parent, str) or parent not in ids["nodes"] or parent == node.get("id"): p.add("parent", f"nodes[{i}].parent", "must reference a different node")
            elif _id(node.get("id")): children.add(parent); parent_of[node["id"]] = parent
        _claim(node, f"nodes[{i}]", ids["evidence"], p)
    checked: set[str] = set()
    for node_id in parent_of:
        if node_id in checked: continue
        seen: set[str] = set(); current = node_id
        while current in parent_of:
            if current in seen: p.add("parent_cycle", "nodes", "node parent relationships must form a forest"); break
            if current in checked: break
            seen.add(current); current = parent_of[current]
        checked.update(seen)
    for i, node in enumerate(collections["nodes"] if isinstance(collections["nodes"], list) else []):
        node_id = node.get("id") if isinstance(node, dict) else None
        if isinstance(node, dict) and not node.get("evidence") and node.get("basis") != "unresolved" and (not _id(node_id) or node_id not in children):
            p.add("evidence_required", f"nodes[{i}].evidence", "empty evidence requires unresolved basis or a conceptual parent with children")
    for i, edge in enumerate(collections["edges"] if isinstance(collections["edges"], list) else []):
        edge = _object(edge, f"edges[{i}]", {"id", "source", "target", "label", "basis", "evidence"}, {"id", "source", "target", "label", "kind", "basis", "evidence"}, p)
        if edge is None: continue
        if not isinstance(edge.get("label"), str) or not edge.get("label"): p.add("type", f"edges[{i}].label", "must be a non-empty string")
        elif len(edge["label"]) > 300: p.add("limit", f"edges[{i}].label", "must contain at most 300 characters")
        _optional_text(edge, "kind", f"edges[{i}]", 100, p)
        for key in ("source", "target"):
            if not isinstance(edge.get(key), str) or edge.get(key) not in ids["nodes"]: p.add("reference", f"edges[{i}].{key}", "unknown node ID")
        _claim(edge, f"edges[{i}]", ids["evidence"], p)
        if not edge.get("evidence") and edge.get("basis") != "unresolved": p.add("evidence_required", f"edges[{i}].evidence", "empty evidence requires unresolved basis")
    for i, finding in enumerate(collections["findings"] if isinstance(collections["findings"], list) else []):
        finding = _object(finding, f"findings[{i}]", {"id", "title", "message", "severity", "nodeIds", "basis", "evidence"}, {"id", "title", "message", "severity", "nodeIds", "edgeIds", "basis", "evidence", "counterEvidence", "suggestion"}, p)
        if finding is None: continue
        for key in ("title", "message"):
            if not isinstance(finding.get(key), str) or not finding.get(key): p.add("type", f"findings[{i}].{key}", "must be a non-empty string")
        _max_text(finding, "title", f"findings[{i}]", 300, p); _max_text(finding, "message", f"findings[{i}]", 8000, p)
        _claim(finding, f"findings[{i}]", ids["evidence"], p)
        if not isinstance(finding.get("severity"), str) or finding.get("severity") not in {"low", "medium", "high"}: p.add("severity", f"findings[{i}].severity", "must be low, medium, or high")
        for key, valid in (("nodeIds", ids["nodes"]), ("edgeIds", ids["edges"]), ("counterEvidence", ids["evidence"])):
            refs = finding.get(key, [])
            if not isinstance(refs, list): p.add("type", f"findings[{i}].{key}", "must be an array"); continue
            if len(refs) > 100: p.add("limit", f"findings[{i}].{key}", "must contain at most 100 references")
            if len(refs) != len({ref for ref in refs if isinstance(ref, str)}): p.add("duplicate_reference", f"findings[{i}].{key}", "references must be unique strings")
            for ref in refs:
                if not isinstance(ref, str) or ref not in valid: p.add("reference", f"findings[{i}].{key}", f"unknown {key} reference")
        _optional_text(finding, "suggestion", f"findings[{i}]", 4000, p, allow_empty=True)
        if not finding.get("evidence") and finding.get("basis") != "unresolved": p.add("evidence_required", f"findings[{i}].evidence", "empty evidence requires unresolved basis")


def _claim(item: dict[str, Any], at: str, evidence_ids: set[str], p: Problems) -> None:
    if not isinstance(item.get("basis"), str) or item.get("basis") not in BASES: p.add("basis", f"{at}.basis", "must be observed, inferred, or unresolved")
    refs = item.get("evidence")
    if not isinstance(refs, list): p.add("type", f"{at}.evidence", "must be an array"); return
    for ref in refs:
        if not isinstance(ref, str) or ref not in evidence_ids: p.add("reference", f"{at}.evidence", "unknown evidence ID")
    if isinstance(refs, list) and len(refs) != len({ref for ref in refs if isinstance(ref, str)}): p.add("duplicate_reference", f"{at}.evidence", "references must be unique strings")
    if isinstance(refs, list) and len(refs) > 100: p.add("limit", f"{at}.evidence", "must contain at most 100 references")


def validate(doc: Any, workspace: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    workspace = workspace.resolve()
    p = Problems(); _basic_shape(doc, p)
    if not isinstance(doc, dict): return p.items, {}
    _references(doc, p)
    hashes = _validate_evidence(doc, workspace, p) if isinstance(doc.get("evidence"), list) else {}
    hashes = _validate_inspected(doc, workspace, hashes, p)
    verification = doc.get("verification")
    if verification is not None:
        supplied = verification.get("files") if isinstance(verification, dict) else None
        if not isinstance(supplied, dict): p.add("verification", "verification.files", "must be an object")
        else:
            for rel, digest in supplied.items():
                if rel not in hashes: p.add("fingerprint_scope", "verification.files", "fingerprint must belong to a cited file")
                elif digest != hashes[rel]: p.add("stale_source", "verification.files", "source changed since the draft fingerprint")
    return p.items, hashes


def _load(path: Path) -> Any:
    if path.stat().st_size > MAX_DOCUMENT: raise ValueError(f"document exceeds {MAX_DOCUMENT} bytes")
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_bytes(doc: dict[str, Any]) -> bytes:
    comparable = dict(doc)
    comparable.pop("verification", None)
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _publish_locked(doc: dict[str, Any], hashes: dict[str, str], root: Path, output: Path, output_name: str) -> int:
    current_id = None; current_doc = None; current_snapshot = None
    if output.exists():
        try:
            current_snapshot = output.read_bytes()
            current_doc = json.loads(current_snapshot.decode("utf-8"))
            current_id = current_doc["revision"]["id"]
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            print(json.dumps({"ok": False, "errors": [{"code": "published_invalid", "path": output_name, "message": "existing artifact is invalid"}]})); return 1
    if doc["revision"].get("parent") != current_id:
        print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": "does not match the published revision"}]})); return 1
    if current_doc is not None and doc["revision"]["id"] == current_id and _semantic_bytes(doc) != _semantic_bytes(current_doc):
        print(json.dumps({"ok": False, "errors": [{"code": "revision_id_reused", "path": "revision.id", "message": "same revision ID cannot identify changed content"}]})); return 1
    doc["verification"] = {"files": hashes, "publishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    fd, temp_name = tempfile.mkstemp(prefix=".mlview-", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(doc, stream, ensure_ascii=False, indent=2, sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        final_errors, final_hashes = validate(doc, root)
        if final_errors or final_hashes != hashes:
            print(json.dumps({"ok": False, "errors": [{"code": "source_changed", "path": "verification.files", "message": "source or configuration changed during publication"}]})); return 1
        if current_snapshot is not None:
            try: unchanged = output.read_bytes() == current_snapshot
            except OSError: unchanged = False
            if not unchanged:
                print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": "published revision changed during publication"}]})); return 1
        elif output.exists():
            print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": "published revision appeared during publication"}]})); return 1
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    print(json.dumps({"ok": True, "errors": [], "output": output_name, "revision": doc["revision"]["id"]}, sort_keys=True)); return 0


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 10):
        print(json.dumps({"ok": False, "errors": [{"code": "python_version", "path": "$", "message": "Python 3.10 or newer is required"}]})); return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "publish")); parser.add_argument("draft")
    parser.add_argument("--workspace", default="."); parser.add_argument("--output", default="workflow.mlview.json")
    parser.add_argument("--include-document", action="store_true", help="include the draft in successful validate output")
    args = parser.parse_args(argv)
    root = Path(args.workspace).resolve()
    try: doc = _load(Path(args.draft))
    except (OSError, UnicodeError, ValueError, RecursionError, json.JSONDecodeError):
        print(json.dumps({"ok": False, "errors": [{"code": "invalid_json", "path": "$", "message": "draft is missing, too large, non-UTF-8, or invalid JSON"}]})); return 1
    errors, hashes = validate(doc, root)
    if errors: print(json.dumps({"ok": False, "errors": errors}, sort_keys=True)); return 1
    if args.command == "validate":
        result: dict[str, Any] = {"ok": True, "errors": [], "revision": doc["revision"]["id"], "files": hashes}
        if args.include_document: result["document"] = doc
        print(json.dumps(result, sort_keys=True)); return 0
    output_arg = PurePosixPath(args.output)
    if not args.output or "\\" in args.output or output_arg.is_absolute() or any(part in {"", ".", ".."} for part in args.output.split("/")):
        print(json.dumps({"ok": False, "errors": [{"code": "output_path", "path": "--output", "message": "must stay within the workspace"}]})); return 1
    output = root.joinpath(*output_arg.parts)
    try: output.resolve(strict=False).parent.relative_to(root)
    except ValueError:
        print(json.dumps({"ok": False, "errors": [{"code": "output_path", "path": "--output", "message": "must stay within the workspace"}]})); return 1
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        print(json.dumps({"ok": False, "errors": [{"code": "publication_io", "path": "--output", "message": "could not prepare the artifact output directory"}]})); return 1
    lock = output.with_name(output.name + ".lock")
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        print(json.dumps({"ok": False, "errors": [{"code": "publish_locked", "path": output_arg.as_posix() + ".lock", "message": "another publisher is active or a stale lock must be removed manually"}]})); return 1
    except OSError:
        print(json.dumps({"ok": False, "errors": [{"code": "publication_io", "path": "--output", "message": "could not create the publication lock"}]})); return 1
    try:
        try:
            os.close(lock_fd)
            return _publish_locked(doc, hashes, root, output, output_arg.as_posix())
        except OSError:
            print(json.dumps({"ok": False, "errors": [{"code": "publication_io", "path": "--output", "message": "could not write the published artifact"}]})); return 1
    finally:
        try: lock.unlink()
        except FileNotFoundError: pass


if __name__ == "__main__": raise SystemExit(main())
