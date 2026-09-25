#!/usr/bin/env python3
"""Validate and atomically publish MLView WorkflowDocument 1.0 artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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
EDITABLE_COLLECTIONS = {"phases", "nodes", "edges", "findings", "evidence"}
RFC3339_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))", re.ASCII)
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
DRIVE_RE = re.compile(r"^[A-Za-z]:")
DRIVE_MESSAGE = "must be a slash-separated relative path without a drive letter"
ARTIFACT_SUFFIX = ".mlview.json"
# No WorkflowDocument needs more than about 5 levels; deeper JSON is refused at parse time so no
# later walk can recurse too deeply on any Python version (the extension uses the same bound).
MAX_JSON_DEPTH = 64
# verification.files holds at most 2000 keys, so at most 2000 tracked files can be fingerprinted.
MAX_TRACKED = 2000
TRACKED_LIMIT_MESSAGE = f"at most {MAX_TRACKED} distinct tracked files (cited evidence files plus inspected project files) can be fingerprinted; list fewer files"

# MLView's own files (published artifacts, drafts and installed skill copies)
# are never project evidence. The VS Code extension uses the same predicate, so
# both layers agree on what is tracked. It folds A-Z, plus the only two
# non-ASCII code points whose case fold is an ASCII letter: U+017F LATIN SMALL
# LETTER LONG S (s) and U+212A KELVIN SIGN (k). A case-insensitive volume such
# as APFS resolves ".claude/\u017fkills/mlview/SKILL.md" to the installed skill
# file, and Path.resolve() keeps the spelling as written (SECURITY2-1).
OWNED_PREFIXES = (".mlview/", ".agents/skills/mlview/", ".claude/skills/mlview/", ".github/skills/mlview/")
OWNED_SUFFIXES = (ARTIFACT_SUFFIX, ".draft.json")
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_OWNED_FOLD = str.maketrans({**{chr(c): chr(c + 32) for c in range(0x41, 0x5B)}, "\u017f": "s", "\u212a": "k"})
EXCLUDED_EVIDENCE_MESSAGE = "evidence must cite project files, not an MLView artifact, draft or installed MLView skill file"
EXCLUDED_INSPECTED_MESSAGE = "MLView-owned file is listed but not fingerprinted; list only project files"

_UMASK: int | None = None


def is_owned_path(rel: str) -> bool:
    folded = rel.translate(_OWNED_FOLD)
    return folded.startswith(OWNED_PREFIXES) or folded.endswith(OWNED_SUFFIXES)


def _identity(path: Path) -> tuple[int, int] | None:
    """(device, inode) of an existing file; None when unknown (some file systems report inode 0)."""
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _owned_target(resolved: Path, root: Path, owned: set[tuple[int, int]]) -> bool:
    """True when a path that is not owned as written reaches an MLView file: through a symlink to
    an owned location, or as another name (hard link or case alias) of the draft or artifact."""
    try:
        if is_owned_path(resolved.relative_to(root).as_posix()):
            return True
    except ValueError:
        return False
    return bool(owned) and _identity(resolved) in owned


def _tracked(doc: dict[str, Any]) -> set[str]:
    """tracked(doc) as written: cited evidence files plus inspected files that are not MLView-owned."""
    evidence = doc.get("evidence")
    coverage = doc.get("coverage")
    inspected = coverage.get("inspectedFiles") if isinstance(coverage, dict) else None
    cited = {ev["file"] for ev in evidence if isinstance(ev, dict) and isinstance(ev.get("file"), str)} if isinstance(evidence, list) else set()
    listed = {value for value in inspected if isinstance(value, str) and not is_owned_path(value)} if isinstance(inspected, list) else set()
    return cited | listed


def _json_depth(value: Any) -> int:
    """Nesting depth of parsed JSON (a scalar is 0, [] is 1), computed without recursion."""
    deepest = 0
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, (dict, list)):
            deepest = max(deepest, depth + 1)
            children = current.values() if isinstance(current, dict) else current
            pending.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    return deepest


def _rfc3339(value: str) -> bool:
    """Strict RFC 3339 date-time with an offset, identical to the schema layer and the extension on
    every Python version (datetime.fromisoformat accepts only 3 or 6 fraction digits before 3.11)."""
    match = RFC3339_RE.fullmatch(value)
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


class Problems:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, code: str, path: str, message: str, **extra: Any) -> None:
        self.items.append({"code": code, "path": path, "message": message, **extra})


def _warn(warnings: list[dict[str, str]], code: str, path: str, message: str) -> None:
    warnings.append({"code": code, "path": path, "message": message})


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("\ufeff") else text


def _path_syntax(value: Any) -> tuple[str, str] | None:
    """Return the lexical problem of a workspace-relative path, or None."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        return "invalid_path", "must be a non-empty slash-separated relative path"
    if DRIVE_RE.match(value):
        return "invalid_path", DRIVE_MESSAGE
    if PurePosixPath(value).is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        return "path_outside_workspace", "must stay within the workspace"
    return None


def _relative(value: Any, root: Path, problems: Problems, path: str) -> tuple[str, Path] | None:
    syntax = _path_syntax(value)
    if syntax is not None:
        problems.add(syntax[0], path, syntax[1])
        return None
    pure = PurePosixPath(value)
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError, RuntimeError):
        problems.add("path_outside_workspace", path, "file is missing or resolves outside the workspace")
        return None
    if not resolved.is_file():
        problems.add("invalid_path", path, "must identify a regular file")
        return None
    return pure.as_posix(), resolved


def _read_source(path: Path, problems: Problems, at: str) -> tuple[bytes, str] | None:
    """Read a cited source: raw bytes for the fingerprint, decoded text without a leading BOM."""
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
        return raw, _strip_bom(raw.decode("utf-8"))
    except UnicodeDecodeError:
        problems.add("source_encoding", at, "cited source must be UTF-8")
        return None


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _parse_notebook(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _validate_evidence(doc: dict[str, Any], root: Path, problems: Problems, owned: set[tuple[int, int]] = frozenset()) -> dict[str, str]:
    hashes: dict[str, str] = {}
    cache: dict[str, tuple[bytes, str]] = {}
    notebooks: dict[str, Any] = {}
    for index, ev in enumerate(doc.get("evidence", [])):
        at = f"evidence[{index}]"
        if not isinstance(ev, dict):
            continue
        cited = ev.get("file")
        if isinstance(cited, str) and is_owned_path(cited):
            problems.add("excluded_evidence", f"{at}.file", EXCLUDED_EVIDENCE_MESSAGE)
            continue
        located = _relative(cited, root, problems, f"{at}.file")
        if not located:
            continue
        rel, source_path = located
        if _owned_target(source_path, root, owned):
            problems.add("excluded_evidence", f"{at}.file", EXCLUDED_EVIDENCE_MESSAGE)
            continue
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
            if rel not in notebooks:
                notebooks[rel] = _parse_notebook(text)
            try:
                notebook = notebooks[rel]
                if notebook is None:
                    raise ValueError
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
        quote = ev.get("quote")
        # A leading byte-order mark is not part of line 1: accept a line-1
        # quote with or without it, and compare every other quote exactly.
        matches = _strip_bom(quote) == _strip_bom(expected) if line == 1 and isinstance(quote, str) else quote == expected
        if not matches:
            shown = json.dumps(expected[:200], ensure_ascii=False)
            problems.add("quote_mismatch", f"{at}.quote", f"quote does not exactly match the cited lines; the cited lines are: {shown}")
    return dict(sorted(hashes.items()))


def _validate_inspected(doc: dict[str, Any], root: Path, hashes: dict[str, str], problems: Problems, warnings: list[dict[str, str]], owned: set[tuple[int, int]] = frozenset()) -> dict[str, str]:
    coverage = doc.get("coverage")
    files = coverage.get("inspectedFiles", []) if isinstance(coverage, dict) else []
    evidence = doc.get("evidence")
    cited = {ev["file"] for ev in evidence if isinstance(ev, dict) and isinstance(ev.get("file"), str)} if isinstance(evidence, list) else set()
    seen: set[str] = set()
    for index, value in enumerate(files if isinstance(files, list) else []):
        at = f"coverage.inspectedFiles[{index}]"
        if isinstance(value, str) and is_owned_path(value):
            # Listed for honesty only: never existence-checked, read or fingerprinted.
            syntax = _path_syntax(value)
            if syntax is not None: problems.add(syntax[0], at, syntax[1])
            else: _warn(warnings, "excluded_inspected", at, EXCLUDED_INSPECTED_MESSAGE)
            continue
        located = _relative(value, root, problems, at)
        if not located:
            continue
        rel, path = located
        if rel in cited or rel in seen:
            continue
        seen.add(rel)
        if _owned_target(path, root, owned):
            _warn(warnings, "excluded_inspected", at, EXCLUDED_INSPECTED_MESSAGE)
            continue
        # Inspected-only context may be binary or non-UTF-8: fingerprint raw bytes.
        try:
            if path.stat().st_size > MAX_SOURCE:
                raw = None
            else:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_SOURCE + 1)
        except OSError:
            problems.add("source_read", at, "could not read inspected file")
            continue
        if raw is None or len(raw) > MAX_SOURCE:
            _warn(warnings, "not_fingerprinted", at, f"file is larger than {MAX_SOURCE} bytes; listed without a freshness fingerprint")
            continue
        hashes[rel] = hashlib.sha256(raw).hexdigest()
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
        p.add("producer", "producer", 'must identify a supported host-llm producer: kind "host-llm" and host one of copilot, codex, claude-code, unknown')
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
    if "verification" in doc:
        verification = _object(doc["verification"], "verification", {"files", "publishedAt"}, {"files", "publishedAt"}, p)
        if verification is not None:
            published = verification.get("publishedAt")
            if not isinstance(published, str): p.add("type", "verification.publishedAt", "must be a string")
            else:
                if not _rfc3339(published): p.add("format", "verification.publishedAt", "must be an RFC 3339 date-time with timezone")
            files = verification.get("files")
            if not isinstance(files, dict): p.add("type", "verification.files", "must be an object")
            else:
                if len(files) > 2000: p.add("limit", "verification.files", "must contain at most 2000 entries")
                for key, digest in files.items():
                    if not isinstance(key, str) or not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest): p.add("fingerprint", "verification.files", "must map relative paths to lowercase SHA-256")
                    elif len(key) > 500: p.add("limit", "verification.files", "path keys must contain at most 500 characters")
                    elif _path_syntax(key) is not None: p.add("invalid_path", "verification.files", "path keys must be slash-separated workspace-relative paths without a drive letter")
    limits = {"phases": 100, "nodes": 2000, "edges": 4000, "findings": 1000, "evidence": 5000}
    for name, limit in limits.items():
        value = doc.get(name)
        if not isinstance(value, list): p.add("type", name, "must be an array")
        elif len(value) > limit: p.add("limit", name, f"must contain at most {limit} items")
    if isinstance(doc.get("phases"), list) and not doc["phases"]: p.add("required", "phases", "must not be empty")
    if isinstance(doc.get("nodes"), list) and not doc["nodes"]: p.add("required", "nodes", "must not be empty")
    for path, value in _walk_strings(doc):
        if len(value) > 16000: p.add("text_too_large", path, "string exceeds 16000 characters")
        if not _encodable(value): p.add("text_encoding", path, "contains an unpaired surrogate; use valid Unicode text")
    for path, key in _walk_keys(doc):
        if not _encodable(key): p.add("text_encoding", path, "contains an unpaired surrogate; use valid Unicode text")
    path_lists = []
    if isinstance(request, dict): path_lists.append(("request.entrypoints", request.get("entrypoints", [])))
    for at, values in path_lists:
        if isinstance(values, list):
            for i, value in enumerate(values):
                if _path_syntax(value) is not None:
                    drive = isinstance(value, str) and bool(DRIVE_RE.match(value))
                    p.add("invalid_path", f"{at}[{i}]", DRIVE_MESSAGE if drive else "must be a slash-separated relative path")


def _walk_strings(value: Any, path: str = "$"):
    """Every string value with its path, in document order (iterative: nesting cannot overflow)."""
    pending: list[tuple[Any, str]] = [(value, path)]
    while pending:
        current, at = pending.pop()
        if isinstance(current, str):
            yield at, current
        elif isinstance(current, dict):
            pending.extend(reversed([(child, f"{at}.{key}") for key, child in current.items()]))
        elif isinstance(current, list):
            pending.extend(reversed([(child, f"{at}[{index}]") for index, child in enumerate(current)]))


def _walk_keys(value: Any, path: str = "$"):
    """Every object key with its path, in document order (iterative: nesting cannot overflow)."""
    pending: list[tuple[bool, Any, str]] = [(False, value, path)]
    while pending:
        is_key, current, at = pending.pop()
        if is_key:
            yield at, current
        elif isinstance(current, dict):
            entries: list[tuple[bool, Any, str]] = []
            for key, child in current.items():
                entries.append((True, key, f"{at}.{key}"))
                entries.append((False, child, f"{at}.{key}"))
            pending.extend(reversed(entries))
        elif isinstance(current, list):
            pending.extend(reversed([(False, child, f"{at}[{index}]") for index, child in enumerate(current)]))


def _encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


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
        if "parent" in node:
            parent = node["parent"]
            if not _id(parent) or parent not in ids["nodes"] or parent == node.get("id"): p.add("parent", f"nodes[{i}].parent", "must be the ID of a different node; omit parent for root nodes")
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


def validate(doc: Any, workspace: Path, *, warnings: list[dict[str, str]] | None = None, owned_files: Any = ()) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return (errors, fingerprints); non-blocking warnings are appended to ``warnings`` when given.

    ``owned_files`` are MLView files (the draft being validated, the artifact being published):
    another name for one of them (a hard link or case alias) is never cited or fingerprinted.
    """
    workspace = workspace.resolve()
    notes: list[dict[str, str]] = warnings if warnings is not None else []
    owned = {identity for identity in (_identity(Path(item)) for item in owned_files) if identity is not None}
    p = Problems(); _basic_shape(doc, p)
    if not isinstance(doc, dict): return p.items, {}
    _references(doc, p)
    if len(_tracked(doc)) > MAX_TRACKED: p.add("limit", "coverage.inspectedFiles", TRACKED_LIMIT_MESSAGE)
    hashes = _validate_evidence(doc, workspace, p, owned) if isinstance(doc.get("evidence"), list) else {}
    hashes = _validate_inspected(doc, workspace, hashes, p, notes, owned)
    verification = doc.get("verification")
    if isinstance(verification, dict):
        supplied = verification.get("files")
        if not isinstance(supplied, dict): p.add("verification", "verification.files", "must be an object")
        else:
            # `verification` is publication output. A supplied block is checked
            # only for tracked files that were fingerprinted; keys for MLView's
            # own files, untracked paths and unfingerprinted files are ignored.
            for rel, digest in supplied.items():
                current = hashes.get(rel)
                if current is not None and isinstance(digest, str) and DIGEST_RE.fullmatch(digest) and digest != current:
                    p.add("stale_source", "verification.files", f"{rel} changed after this fingerprint was taken; re-read it, update claims that depend on it, then delete the draft's verification block", file=rel)
    return p.items, hashes


class _TooLarge(ValueError):
    pass


class _DuplicateMember(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"duplicate JSON member: {key[:200]}")


class _NotJsonConstant(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not valid JSON")


def _reject_constant(name: str) -> Any:
    """json.loads accepts NaN, Infinity and -Infinity by default; JSON, and the viewer's
    JSON.parse, do not (SPECDOCS2-3)."""
    raise _NotJsonConstant(name)


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT + 1)
    if len(raw) > MAX_DOCUMENT:
        raise _TooLarge(f"document exceeds {MAX_DOCUMENT} bytes")
    return raw


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateMember(key)
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    """Parse a document with the CLI's rules (strict UTF-8, unique members, no NaN or Infinity, at
    most MAX_JSON_DEPTH levels), raising ValueError. Tests and the conformance bridge use it."""
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if _json_depth(value) > MAX_JSON_DEPTH:
        raise ValueError("nesting is too deep")
    return value


_INVALID = object()


RELATIVE_HINT = " (relative paths are resolved against --workspace)"


def _read_input(path: Path, problems: Problems, label: str, relative: bool = False) -> bytes | None:
    """Read a draft or record file, reporting a distinct error code per failure."""
    try:
        return _read_bounded(path)
    except _TooLarge:
        problems.add("draft_too_large", label, f"{label} file exceeds {MAX_DOCUMENT} bytes")
    except (FileNotFoundError, NotADirectoryError):
        problems.add("draft_not_found", label, f"{label} file does not exist" + (RELATIVE_HINT if relative else ""))
    except IsADirectoryError:
        problems.add("draft_path", label, f"{label} must identify a regular file")
    except OSError:
        problems.add("draft_io", label, f"could not read the {label} file")
    return None


def _parse_input(raw: bytes, problems: Problems, label: str, at: str) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.add("draft_encoding", label, f"{label} file must be UTF-8 JSON")
        return _INVALID
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if _json_depth(value) > MAX_JSON_DEPTH:
            problems.add("invalid_json", at, "nesting is too deep")
            return _INVALID
        return value
    except json.JSONDecodeError as exc:
        problems.add("invalid_json", at, f"{exc.msg} at line {exc.lineno}, column {exc.colno}", line=exc.lineno, column=exc.colno)
    except (_DuplicateMember, _NotJsonConstant) as exc:
        problems.add("invalid_json", at, str(exc))
    except RecursionError:
        problems.add("invalid_json", at, "nesting is too deep")
    except ValueError:
        problems.add("invalid_json", at, "the document is not valid JSON")
    return _INVALID


def _input_path(value: str, root: Path, problems: Problems) -> Path | None:
    """Locate a validate/publish draft: absolute as given, relative to --workspace otherwise."""
    path = Path(value) if value else None
    if path is not None and path.is_absolute():
        return path
    if not value or "\\" in value or DRIVE_RE.match(value):
        problems.add("draft_path", "draft", "must be an absolute path or a slash-separated path relative to --workspace")
        return None
    return root.joinpath(*PurePosixPath(value).parts)


def _draft_path(value: str, root: Path, problems: Problems, label: str = "draft") -> Path | None:
    """Resolve an existing draft that is safe to replace inside the workspace."""
    if not value:
        problems.add("draft_path", label, "must be a slash-separated path inside the workspace")
        return None
    path = Path(value)
    if not path.is_absolute():
        if "\\" in value or DRIVE_RE.match(value):
            problems.add("draft_path", label, "must be a slash-separated path inside the workspace")
            return None
        path = root.joinpath(*PurePosixPath(value).parts)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        problems.add("draft_not_found", label, f"{label} file does not exist" + ("" if Path(value).is_absolute() else RELATIVE_HINT))
        return None
    except (OSError, ValueError, RuntimeError):
        problems.add("draft_path", label, "must identify an existing file inside the workspace")
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        problems.add("draft_path", label, "must identify an existing file inside the workspace")
        return None
    if not resolved.is_file() or path.is_symlink():
        problems.add("draft_path", label, "must identify a regular non-symlink file inside the workspace")
        return None
    return resolved


def _umask() -> int:
    global _UMASK
    if _UMASK is None:
        _UMASK = os.umask(0)
        os.umask(_UMASK)
    return _UMASK


def _match_mode(temp_name: str, target: Path) -> None:
    """Give a replacement file the target's mode (or the umask default) instead of mkstemp's 0600."""
    if os.name == "nt":
        return
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError:
        mode = 0o666 & ~_umask()
    os.chmod(temp_name, mode)


def _upsert_draft(draft: Path, collection: str, record: Any, root: Path) -> int:
    p = Problems()
    snapshot = _read_input(draft, p, "draft")
    doc = _parse_input(snapshot, p, "draft", "$") if snapshot is not None else _INVALID
    if p.items:
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    if not isinstance(doc, dict):
        print(json.dumps({"ok": False, "errors": [{"code": "checkpoint_invalid", "path": "$", "message": "existing draft must be a WorkflowDocument object"}]})); return 1
    # Publication metadata describes the old semantic bytes. It is intentionally
    # discarded by an edit, so a stale fingerprint must not make the editable
    # checkpoint unusable. Source quotes and every structural/reference rule
    # still validate against the current workspace before and after the edit.
    checkpoint = dict(doc)
    checkpoint.pop("verification", None)
    before_errors, _ = validate(checkpoint, root, owned_files=(draft,))
    if before_errors:
        print(json.dumps({"ok": False, "errors": [{"code": "checkpoint_invalid", "path": "$", "message": "existing draft must validate before an incremental edit"}] + before_errors}, sort_keys=True)); return 1
    if not isinstance(record, dict) or not _id(record.get("id")):
        print(json.dumps({"ok": False, "errors": [{"code": "record", "path": "record.id", "message": "record must be an object with a valid ID"}]})); return 1
    edited = dict(doc)
    records = list(doc[collection])
    matches = [index for index, item in enumerate(records) if isinstance(item, dict) and item.get("id") == record["id"]]
    if len(matches) > 1:
        print(json.dumps({"ok": False, "errors": [{"code": "checkpoint_invalid", "path": collection, "message": "existing draft contains duplicate record IDs"}]})); return 1
    action = "replaced" if matches else "inserted"
    if matches: records[matches[0]] = record
    else: records.append(record)
    edited[collection] = records
    edited.pop("verification", None)
    after_errors, _ = validate(edited, root, owned_files=(draft,))
    if after_errors:
        print(json.dumps({"ok": False, "errors": after_errors}, sort_keys=True)); return 1
    serialized = (json.dumps(edited, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(serialized) > MAX_DOCUMENT:
        print(json.dumps({"ok": False, "errors": [{"code": "document_too_large", "path": "$", "message": f"edited draft exceeds {MAX_DOCUMENT} bytes"}]})); return 1
    fd, temp_name = tempfile.mkstemp(prefix=".mlview-draft-", suffix=".tmp", dir=draft.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialized); stream.flush(); os.fsync(stream.fileno())
        try: unchanged = _read_bounded(draft) == snapshot
        except (OSError, ValueError): unchanged = False
        if not unchanged:
            print(json.dumps({"ok": False, "errors": [{"code": "draft_conflict", "path": "draft", "message": "draft changed during the edit"}]})); return 1
        _match_mode(temp_name, draft)
        os.replace(temp_name, draft)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    print(json.dumps({"ok": True, "errors": [], "draft": draft.relative_to(root).as_posix(), "collection": collection, "id": record["id"], "action": action}, sort_keys=True)); return 0


def _published_invalid(output_name: str, message: str) -> int:
    print(json.dumps({"ok": False, "errors": [{"code": "published_invalid", "path": output_name, "message": message}]})); return 1


def _publish_locked(doc: dict[str, Any], hashes: dict[str, str], root: Path, output: Path, output_name: str, *, warnings: list[dict[str, str]] | None = None, owned_files: Any = ()) -> int:
    current_id = None; current_doc = None; current_snapshot = None
    if output.exists():
        # Read the existing artifact exactly as the viewer does: at most 2 MiB, strict UTF-8 JSON
        # (a BOM, NaN or Infinity fails, as in JSON.parse; duplicate members pass, as they do
        # there), bounded nesting, and a valid revision.id. The viewer refuses Refine for anything
        # else, telling the user this helper will not publish over it.
        try:
            current_snapshot = _read_bounded(output)
        except _TooLarge:
            return _published_invalid(output_name, f"existing artifact exceeds {MAX_DOCUMENT} bytes")
        except OSError:
            return _published_invalid(output_name, "existing artifact could not be read")
        try:
            current_doc = json.loads(current_snapshot.decode("utf-8"), parse_constant=_reject_constant)
            if _json_depth(current_doc) > MAX_JSON_DEPTH: raise ValueError
        except (ValueError, RecursionError):
            return _published_invalid(output_name, "existing artifact is invalid")
        revision = current_doc.get("revision") if isinstance(current_doc, dict) else None
        if not isinstance(revision, dict) or not _id(revision.get("id")):
            return _published_invalid(output_name, "existing artifact has no valid revision.id")
        current_id = revision["id"]
    if doc["revision"].get("parent") != current_id:
        if current_doc is None: message = f"no artifact is published at {output_name}; omit revision.parent"
        else: message = f"does not match the published revision {current_id}"
        print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": message}]})); return 1
    # The artifact keeps no longer history, but its current revision names its
    # own parent: that ID was already published and must not be reused.
    current_parent = current_doc["revision"].get("parent") if current_doc is not None else None
    if _id(current_parent) and doc["revision"]["id"] == current_parent:
        revision_id = doc["revision"]["id"]
        print(json.dumps({"ok": False, "errors": [{"code": "revision_id_reused", "path": "revision.id", "message": f"revision ID {revision_id} was already used by this artifact (the published revision's parent); choose a new ID"}]})); return 1
    doc["verification"] = {"files": hashes, "publishedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    serialized = (json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(serialized) > MAX_DOCUMENT:
        print(json.dumps({"ok": False, "errors": [{"code": "document_too_large", "path": "$", "message": f"published artifact would be {len(serialized)} bytes; the limit is {MAX_DOCUMENT}"}]})); return 1
    fd, temp_name = tempfile.mkstemp(prefix=".mlview-", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(serialized); stream.flush(); os.fsync(stream.fileno())
        final_errors, final_hashes = validate(doc, root, owned_files=owned_files)
        # Only a fingerprint change (or a source that became stale or unreadable) means the
        # sources moved; any other final problem is reported as it is.
        if final_hashes != hashes or any(error["code"] in {"stale_source", "source_read", "path_outside_workspace", "quote_mismatch"} for error in final_errors):
            print(json.dumps({"ok": False, "errors": [{"code": "source_changed", "path": "verification.files", "message": "source or configuration changed during publication"}]})); return 1
        if final_errors:
            print(json.dumps({"ok": False, "errors": final_errors}, sort_keys=True)); return 1
        if current_snapshot is not None:
            try: unchanged = _read_bounded(output) == current_snapshot
            except (OSError, ValueError): unchanged = False
            if not unchanged:
                print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": "published revision changed during publication"}]})); return 1
        elif output.exists():
            print(json.dumps({"ok": False, "errors": [{"code": "revision_conflict", "path": "revision.parent", "message": "published revision appeared during publication"}]})); return 1
        _match_mode(temp_name, output)
        os.replace(temp_name, output)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)
    result: dict[str, Any] = {"ok": True, "errors": [], "output": output_name, "revision": doc["revision"]["id"]}
    if warnings: result["warnings"] = warnings
    print(json.dumps(result, sort_keys=True)); return 0


def _output_problem(value: str) -> str | None:
    pure = PurePosixPath(value)
    if not value or "\\" in value or "\0" in value or pure.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        return "must stay within the workspace"
    if DRIVE_RE.match(value):
        return DRIVE_MESSAGE
    if not value.translate(_ASCII_LOWER).endswith(ARTIFACT_SUFFIX):
        return "must be a workspace-relative path ending in .mlview.json"
    return None


def _main(argv: list[str] | None) -> int:
    global _UMASK
    if sys.version_info < (3, 10):
        print(json.dumps({"ok": False, "errors": [{"code": "python_version", "path": "$", "message": "Python 3.10 or newer is required"}]})); return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "publish", "upsert")); parser.add_argument("draft")
    parser.add_argument("--workspace", default="."); parser.add_argument("--output", default="workflow.mlview.json")
    parser.add_argument("--include-document", action="store_true", help="include the draft in successful validate output")
    parser.add_argument("--collection", choices=sorted(EDITABLE_COLLECTIONS))
    parser.add_argument("--record", help="JSON file containing one ID-bearing record for upsert")
    args = parser.parse_args(argv)
    # Read the process umask once; replacement files are given the mode a
    # plain write would have produced.
    _UMASK = os.umask(0); os.umask(_UMASK)
    root = Path(args.workspace).resolve()
    if not root.is_dir():
        print(json.dumps({"ok": False, "errors": [{"code": "workspace_path", "path": "--workspace", "message": "must be an existing directory (the VS Code workspace folder that will contain the artifact)"}]})); return 1
    if args.command == "upsert":
        p = Problems(); draft_path = _draft_path(args.draft, root, p)
        if draft_path is None or args.collection is None or args.record is None:
            if draft_path is not None:
                p.add("arguments", "$", "upsert requires --collection and --record")
            print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
        # Case folding like the owned-path rule: casefold also catches the long s and Kelvin
        # sign spellings a case-insensitive volume maps onto the artifact.
        if draft_path.name.casefold().endswith(ARTIFACT_SUFFIX):
            print(json.dumps({"ok": False, "errors": [{"code": "published_target", "path": "draft", "message": "refusing to edit a published *.mlview.json artifact; copy it to a *.draft.json checkpoint first"}]})); return 1
        record_path = _draft_path(args.record, root, p, label="record")
        raw_record = _read_input(record_path, p, "record") if record_path is not None else None
        record = _parse_input(raw_record, p, "record", "record") if raw_record is not None else _INVALID
        if p.items:
            print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
        lock = draft_path.with_name(draft_path.name + ".lock")
        try: lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            print(json.dumps({"ok": False, "errors": [{"code": "draft_locked", "path": "draft", "message": "another editor is active or a stale lock must be removed manually"}]})); return 1
        except OSError:
            print(json.dumps({"ok": False, "errors": [{"code": "draft_io", "path": "draft", "message": "could not create the draft lock"}]})); return 1
        try:
            try:
                os.close(lock_fd)
                return _upsert_draft(draft_path, args.collection, record, root)
            except OSError:
                print(json.dumps({"ok": False, "errors": [{"code": "draft_io", "path": "draft", "message": "could not preserve the edited draft"}]})); return 1
        finally:
            try: lock.unlink()
            except FileNotFoundError: pass
    p = Problems()
    draft = _input_path(args.draft, root, p)
    raw_draft = _read_input(draft, p, "draft", relative=not Path(args.draft).is_absolute()) if draft is not None else None
    doc = _parse_input(raw_draft, p, "draft", "$") if raw_draft is not None else _INVALID
    if p.items:
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    # The draft and the artifact are MLView files under any name.
    owned_files: list[Path] = [draft]
    if args.command == "publish" and _output_problem(args.output) is None:
        owned_files.append(root.joinpath(*PurePosixPath(args.output).parts))
    warnings: list[dict[str, str]] = []
    errors, hashes = validate(doc, root, warnings=warnings, owned_files=owned_files)
    if errors: print(json.dumps({"ok": False, "errors": errors}, sort_keys=True)); return 1
    if args.command == "validate":
        result: dict[str, Any] = {"ok": True, "errors": [], "revision": doc["revision"]["id"], "files": hashes}
        if warnings: result["warnings"] = warnings
        if args.include_document: result["document"] = doc
        print(json.dumps(result, sort_keys=True)); return 0
    problem = _output_problem(args.output)
    if problem is not None:
        print(json.dumps({"ok": False, "errors": [{"code": "output_path", "path": "--output", "message": problem}]})); return 1
    output_arg = PurePosixPath(args.output)
    output = root.joinpath(*output_arg.parts)
    try: output.resolve(strict=False).parent.relative_to(root)
    except (OSError, ValueError, RuntimeError):
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
            return _publish_locked(doc, hashes, root, output, output_arg.as_posix(), warnings=warnings, owned_files=owned_files)
        except OSError:
            print(json.dumps({"ok": False, "errors": [{"code": "publication_io", "path": "--output", "message": "could not write the published artifact"}]})); return 1
    finally:
        try: lock.unlink()
        except FileNotFoundError: pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:  # last resort: keep the one-JSON-object, no-absolute-path contract
        print(json.dumps({"ok": False, "errors": [{"code": "internal_error", "path": "$", "message": f"the helper failed unexpectedly ({type(exc).__name__})"}]}))
        return 1


if __name__ == "__main__": raise SystemExit(main())
