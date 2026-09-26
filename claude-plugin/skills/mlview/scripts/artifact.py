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
# JSON.parse reads a cited notebook at any nesting depth, but json.loads raises RecursionError near the
# interpreter's recursion limit on Python 3.10-3.13 and parses far deeper on 3.14. Refusing deeper
# notebooks on every version keeps the verdict independent of the interpreter; real notebooks,
# widget and plot outputs included, stay far below this.
MAX_NOTEBOOK_DEPTH = 500
NOTEBOOK_JSON_MESSAGE = "cited notebook is not valid JSON (NaN, Infinity or a syntax error); the viewer cannot read it"
NOTEBOOK_DEPTH_MESSAGE = f"cited notebook nests JSON more than {MAX_NOTEBOOK_DEPTH} levels deep; the helper does not read it"
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
MAX_QUOTE = 16000
MAX_EVIDENCE_PATH = 500
# Non-blocking hygiene warnings list at most WARNING_CAP entries per code, then one entry that
# counts the rest, so a large draft cannot flood the output. Evidence wider than WIDE_EVIDENCE_LINES
# lines is reported as wide_evidence.
WARNING_CAP = 10
WIDE_EVIDENCE_LINES = 60
# quote_mismatch shows at most QUOTE_WINDOW characters of each side of the first differing line,
# starting QUOTE_CONTEXT characters before the difference, so every message stays bounded.
QUOTE_WINDOW = 80
QUOTE_CONTEXT = 30
# At most this many repeated JSON members are listed individually.
MAX_DUPLICATE_MEMBERS = 20
# foundAt compares at most FIND_BUDGET source lines per quote, and FIND_TOTAL_BUDGET per validation,
# before giving up, so mismatched quotes of repeated lines (blank lines, say) cannot make validate
# quadratic in the file size.
FIND_BUDGET = 200_000
FIND_TOTAL_BUDGET = 5_000_000
LINES_RE = re.compile(r"(\d+)(?:-(\d+))?", re.ASCII)

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


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_type(value: Any) -> str:
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, (int, float)): return "number"
    return "null" if value is None else "string"


def _shown(value: str, limit: int = 200) -> str:
    """A string as a JSON literal (so tabs, CR, a BOM and trailing spaces are visible), bounded."""
    return json.dumps(value[:limit])


def _unknown(noun: str, value: Any) -> str:
    if isinstance(value, str): return f"unknown {noun} {_shown(value)}"
    if value is None: return f"unknown {noun}"
    return f"unknown {noun}: expected an ID string, found a {_json_type(value)}"


def _value(value: Any) -> dict[str, str]:
    """The structured ``value`` field of a reference error (strings only, bounded)."""
    return {"value": value[:200]} if isinstance(value, str) else {}


def _path_syntax(value: Any) -> tuple[str, str] | None:
    """Return the lexical problem of a workspace-relative path, or None."""
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        return "invalid_path", "must be a non-empty slash-separated relative path"
    if DRIVE_RE.match(value):
        return "invalid_path", DRIVE_MESSAGE
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or ".." in parts:
        return "path_outside_workspace", "must stay within the workspace"
    if any(part in {"", "."} for part in parts):
        return "path_outside_workspace", 'must be a normalised relative path such as src/train.py, without "./", empty or trailing segments'
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


def _read_notebook(text: str) -> tuple[Any, str | None]:
    """(notebook, None), or (None, message) when the notebook cannot be cited: it is not JSON as the
    viewer's JSON.parse reads it (a syntax error, or NaN, Infinity or -Infinity, which json.loads
    accepts by default), or it nests deeper than MAX_NOTEBOOK_DEPTH. A duplicate member keeps the
    last value, as in JSON.parse."""
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except RecursionError:
        return None, NOTEBOOK_DEPTH_MESSAGE
    except ValueError:
        return None, NOTEBOOK_JSON_MESSAGE
    if _json_depth(value) > MAX_NOTEBOOK_DEPTH:
        return None, NOTEBOOK_DEPTH_MESSAGE
    return value, None


def _parse_notebook(text: str) -> Any:
    """The parsed notebook, or None when _read_notebook refuses it."""
    return _read_notebook(text)[0]


def _cited_text(cited: Any, cell: Any, has_cell: bool, root: Path, problems: Problems, file_at: str, cell_at: str,
                owned: set[tuple[int, int]] | frozenset, cache: dict[str, tuple[bytes, str]], notebooks: dict[str, Any],
                hashes: dict[str, str] | None = None) -> tuple[str, str, bool] | None:
    """The text a citation addresses, as (rel, text, is_notebook), or None after reporting why not.

    validate and excerpt share it, so both apply the same workspace confinement, the same refusal
    of MLView's own files, the same size and UTF-8 rules and the same notebook-cell addressing.
    A ``cell`` on a file that is not a notebook is reported (unexpected_cell) and the file's own
    text is still returned, so the quote is checked in the same round."""
    if isinstance(cited, str) and is_owned_path(cited):
        problems.add("excluded_evidence", file_at, EXCLUDED_EVIDENCE_MESSAGE)
        return None
    located = _relative(cited, root, problems, file_at)
    if not located:
        return None
    rel, source_path = located
    if _owned_target(source_path, root, owned):
        problems.add("excluded_evidence", file_at, EXCLUDED_EVIDENCE_MESSAGE)
        return None
    content = cache.get(rel)
    if content is None:
        content = _read_source(source_path, problems, file_at)
        if content is None:
            return None
        cache[rel] = content
    raw, text = content
    if hashes is not None:
        hashes[rel] = hashlib.sha256(raw).hexdigest()
    if source_path.suffix.lower() == ".ipynb":
        if not _is_int(cell) or cell < 0:
            problems.add("notebook_cell", cell_at, "notebook evidence requires a zero-based cell index")
            return None
        if rel not in notebooks:
            notebooks[rel] = _read_notebook(text)
        notebook, unreadable = notebooks[rel]
        if notebook is None:
            problems.add("notebook_cell", cell_at, unreadable)
            return None
        try:
            cells = notebook["cells"]
            source = cells[cell]["source"]
            text = "".join(source) if isinstance(source, list) else source
            if not isinstance(text, str):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            problems.add("notebook_cell", cell_at, "cell does not identify valid notebook source")
            return None
        return rel, text, True
    if has_cell:
        problems.add("unexpected_cell", cell_at, "cell is only valid for .ipynb evidence")
    return rel, text, False


def _span(first: int, last: int) -> str:
    return f"line {first}" if first == last else f"lines {first}-{last}"


def _range_message(maximum: int) -> str:
    return f"line range is invalid for the cited source: line and endLine must be integers with 1 <= line <= endLine <= {maximum}"


def _find_quote(lines: list[str], quote_lines: list[str], positions: dict[str, list[int]], spent: list[int]) -> tuple[int, int] | None:
    """(line, endLine) of the one place where the quote's lines occur exactly, or None when they occur
    nowhere, more than once, or only past the comparison budget. A diagnostic only: the helper never
    rewrites a range.

    The search anchors on the quote line that occurs least often in the source and compares line by
    line with an early exit, spending at most FIND_BUDGET comparisons (and what is left of the
    validation's FIND_TOTAL_BUDGET, counted in ``spent``), so its cost stays bounded whatever the
    quote and the file hold."""
    budget = min(FIND_BUDGET, FIND_TOTAL_BUDGET - spent[0])
    if budget <= 0:
        return None
    wanted = [_strip_bom(quote_lines[0])] + quote_lines[1:]
    count = len(wanted)
    anchor = min(range(count), key=lambda i: len(positions.get(wanted[i], ())))
    found = None
    for position in positions.get(wanted[anchor], ()):
        start = position - anchor
        if start < 0:
            continue
        if start + count > len(lines):
            break
        k = 0
        while k < count and lines[start + k] == wanted[k]:
            k += 1
        budget -= k + 1
        spent[0] += k + 1
        if k == count:
            if found is not None:
                return None
            found = start
        if budget < 0:
            return None
    return None if found is None else (found + 1, found + count)


def _quote_mismatch(ev: dict[str, Any], rel: str, cell: Any, lines: list[str], line: int, end: int, expected: str,
                    positions: Any, spent: list[int]) -> tuple[str, dict[str, Any]]:
    """The message and structured fields of a quote_mismatch: which record and range, the first
    differing line and column with both sides shown, the line counts, and where the quoted text
    occurs when it occurs exactly once elsewhere in the same file or cell."""
    quote = ev.get("quote")
    details: dict[str, Any] = {"file": rel, "line": line, "endLine": end, "citedLines": end - line + 1}
    if isinstance(ev.get("id"), str):
        details["id"] = ev["id"][:200]
    if cell is not None:
        details["cell"] = cell
    record = f"evidence {_shown(ev['id'])}" if isinstance(ev.get("id"), str) else "this evidence"
    place = f"{rel}{f' cell {cell}' if cell is not None else ''}, {_span(line, end)}"
    head = f"quote does not exactly match the cited lines of {record} ({place})."
    if not isinstance(quote, str):
        return f"{head} The quote must be a string.", details
    # Line 1 accepts a quote with or without a leading byte-order mark, so neither side keeps one here.
    q, e = (_strip_bom(quote), _strip_bom(expected)) if line == 1 else (quote, expected)
    quote_lines, cited_lines = q.split("\n"), e.split("\n")
    details["quoteLines"] = len(quote_lines)
    shared = min(len(quote_lines), len(cited_lines))
    k = next((i for i in range(shared) if quote_lines[i] != cited_lines[i]), shared)
    ours = quote_lines[k] if k < len(quote_lines) else None
    theirs = cited_lines[k] if k < len(cited_lines) else None
    column = 0
    if ours is not None and theirs is not None:
        column = next((i for i, (a, b) in enumerate(zip(ours, theirs)) if a != b), min(len(ours), len(theirs)))
    start = max(0, column - QUOTE_CONTEXT)
    difference: dict[str, Any] = {"rangeLine": k + 1, "line": line + k, "column": column + 1, "startColumn": start + 1,
                                  "quote": None if ours is None else ours[start:start + QUOTE_WINDOW],
                                  "cited": None if theirs is None else theirs[start:start + QUOTE_WINDOW]}
    details["difference"] = difference
    # Every position where the two sides differ, counting lines only one side has.
    differing = sum(1 for i in range(max(len(quote_lines), len(cited_lines)))
                    if i >= shared or quote_lines[i] != cited_lines[i])
    details["differingLines"] = differing
    parts = [head]
    found = _find_quote(lines, quote.split("\n"), positions(), spent) if quote else None
    if found is not None and found != (line, end):
        details["foundAt"] = {"line": found[0], "endLine": found[1]}
        parts.append(f"The quoted text occurs exactly once, at {_span(*found)}{' of this cell' if cell is not None else ''}: "
                     "if that is the code you meant, set line and endLine to that range.")
    ours_shown = "nothing (the quote has ended)" if ours is None else json.dumps(difference["quote"])
    theirs_shown = "nothing (the cited range has ended)" if theirs is None else json.dumps(difference["cited"])
    window = f" (both shown from column {start + 1})" if start else ""
    parts.append(f"First difference at line {k + 1} of the quote (source line {line + k}), column {column + 1}: "
                 f"the quote has {ours_shown} where the cited lines have {theirs_shown}{window}.")
    if q == e + "\n":
        parts.append("The quote ends with a line break: cited lines are joined with LF and have none after the last line.")
    elif e == q + "\n":
        parts.append("The cited range ends on an empty line that the quote leaves out; end the range one line earlier.")
    elif "\r" in q:
        parts.append("The quote contains a carriage return; the source is compared with CRLF and CR read as LF, so quote with LF only.")
    elif q.split() == e.split():
        parts.append("Only whitespace differs (indentation, tabs, or spaces at the end of a line).")
    elif q and q in e:
        parts.append("The quote is only part of the cited lines; quote complete lines exactly, or narrow the range to the lines you quote.")
    if len(quote_lines) != len(cited_lines):
        parts.append(f"The quote has {len(quote_lines)} lines; the cited range has {len(cited_lines)}.")
    # With foundAt the whole fix is the range; otherwise say that patching the first line is not enough.
    if differing > 1 and "foundAt" not in details:
        parts.append(f"In all, {differing} lines of the quote differ from the cited lines, not only this one: "
                     "rerun excerpt for the range and replace the whole record rather than editing a line.")
    return " ".join(parts), details


def _validate_evidence(doc: dict[str, Any], root: Path, problems: Problems, owned: set[tuple[int, int]] = frozenset()) -> dict[str, str]:
    hashes: dict[str, str] = {}
    cache: dict[str, tuple[bytes, str]] = {}
    notebooks: dict[str, Any] = {}
    sources: dict[tuple[str, Any], list[str]] = {}
    indexes: dict[tuple[str, Any], dict[str, list[int]]] = {}
    spent = [0]  # foundAt comparisons so far in this validation

    def positions(key: tuple[str, Any]):
        def build() -> dict[str, list[int]]:
            if key not in indexes:
                index: dict[str, list[int]] = {}
                for number, text in enumerate(sources[key]):
                    index.setdefault(text, []).append(number)
                indexes[key] = index
            return indexes[key]
        return build

    for index, ev in enumerate(doc.get("evidence", [])):
        at = f"evidence[{index}]"
        if not isinstance(ev, dict):
            continue
        located = _cited_text(ev.get("file"), ev.get("cell"), "cell" in ev, root, problems, f"{at}.file", f"{at}.cell", owned, cache, notebooks, hashes)
        if located is None:
            continue
        rel, text, notebook = located
        key = (rel, ev.get("cell") if notebook else None)
        if key not in sources:
            sources[key] = _lines(text)
        lines = sources[key]
        line, end = ev.get("line"), ev.get("endLine")
        if not _is_int(line) or not _is_int(end) or line < 1 or end < line or end > len(lines):
            problems.add("range", at, _range_message(len(lines)), maxLine=len(lines))
            continue
        expected = "\n".join(lines[line - 1:end])
        quote = ev.get("quote")
        # A leading byte-order mark is not part of line 1: accept a line-1
        # quote with or without it, and compare every other quote exactly.
        matches = _strip_bom(quote) == _strip_bom(expected) if line == 1 and isinstance(quote, str) else quote == expected
        if not matches:
            message, details = _quote_mismatch(ev, rel, key[1], lines, line, end, expected, positions(key), spent)
            problems.add("quote_mismatch", f"{at}.quote", message, **details)
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
        first: dict[str, int] = {}
        for i, item in enumerate(items if isinstance(items, list) else []):
            value = item.get("id") if isinstance(item, dict) else None
            if not _id(value): p.add("id", f"{name}[{i}].id", "must be a valid ID")
            elif value in first:
                p.add("duplicate_id", f"{name}[{i}].id", f"ID {_shown(value)} is already used by {name}[{first[value]}]; IDs are unique within a collection", value=value, firstIndex=first[value])
            else: first[value] = i
        ids[name] = set(first)
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
        if isinstance(ev.get("file"), str) and len(ev["file"]) > MAX_EVIDENCE_PATH: p.add("limit", f"evidence[{i}].file", f"must contain at most {MAX_EVIDENCE_PATH} characters")
    children: set[str] = set()
    parent_of: dict[str, str] = {}
    for i, node in enumerate(collections["nodes"] if isinstance(collections["nodes"], list) else []):
        node = _object(node, f"nodes[{i}]", {"id", "label", "phase", "basis", "evidence"}, {"id", "label", "phase", "parent", "kind", "detail", "basis", "evidence"}, p)
        if node is None: continue
        if not isinstance(node.get("label"), str) or not node.get("label"): p.add("type", f"nodes[{i}].label", "must be a non-empty string")
        elif len(node["label"]) > 300: p.add("limit", f"nodes[{i}].label", "must contain at most 300 characters")
        if not isinstance(node.get("phase"), str) or node.get("phase") not in ids["phases"]: p.add("reference", f"nodes[{i}].phase", _unknown("phase ID", node.get("phase")), **_value(node.get("phase")))
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
            if not isinstance(edge.get(key), str) or edge.get(key) not in ids["nodes"]: p.add("reference", f"edges[{i}].{key}", _unknown("node ID", edge.get(key)), **_value(edge.get(key)))
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
        for key, valid, noun in (("nodeIds", ids["nodes"], "node ID"), ("edgeIds", ids["edges"], "edge ID"), ("counterEvidence", ids["evidence"], "evidence ID")):
            refs = finding.get(key, [])
            if not isinstance(refs, list): p.add("type", f"findings[{i}].{key}", "must be an array"); continue
            if len(refs) > 100: p.add("limit", f"findings[{i}].{key}", "must contain at most 100 references")
            _reference_list(refs, f"findings[{i}].{key}", valid, noun, p)
        _optional_text(finding, "suggestion", f"findings[{i}]", 4000, p, allow_empty=True)
        if not finding.get("evidence") and finding.get("basis") != "unresolved": p.add("evidence_required", f"findings[{i}].evidence", "empty evidence requires unresolved basis")


def _claim(item: dict[str, Any], at: str, evidence_ids: set[str], p: Problems) -> None:
    if not isinstance(item.get("basis"), str) or item.get("basis") not in BASES: p.add("basis", f"{at}.basis", "must be observed, inferred, or unresolved")
    refs = item.get("evidence")
    if not isinstance(refs, list): p.add("type", f"{at}.evidence", "must be an array"); return
    _reference_list(refs, f"{at}.evidence", evidence_ids, "evidence ID", p)
    if len(refs) > 100: p.add("limit", f"{at}.evidence", "must contain at most 100 references")


def _reference_list(refs: list[Any], at: str, valid: set[str], noun: str, p: Problems) -> None:
    """Report every unresolved reference and every repeat at its own index, naming the value."""
    first: dict[str, int] = {}
    repeated = False
    for j, ref in enumerate(refs):
        if not isinstance(ref, str) or ref not in valid:
            p.add("reference", f"{at}[{j}]", _unknown(noun, ref), index=j, **_value(ref))
        if isinstance(ref, str):
            if ref in first:
                repeated = True
                p.add("duplicate_reference", f"{at}[{j}]", f"{noun} {_shown(ref)} is already listed at {at}[{first[ref]}]; list each ID once", index=j, firstIndex=first[ref], value=ref[:200])
            else:
                first[ref] = j
    if not repeated and any(not isinstance(ref, str) for ref in refs):
        p.add("duplicate_reference", at, "references must be unique strings")


def _capped(items: list[tuple[str, str]], collection: str, noun: str) -> list[tuple[str, str]]:
    """At most WARNING_CAP (path, message) pairs, then one pair at the collection counting the rest."""
    if len(items) <= WARNING_CAP:
        return items
    return items[:WARNING_CAP] + [(collection, f"{len(items) - WARNING_CAP} more {noun} are not listed ({len(items)} in all)")]


def _hygiene(doc: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Non-blocking checks of a document that has no errors, in document order. They never change
    validity, exit codes or publication."""
    nodes, edges, findings, evidence = doc["nodes"], doc["edges"], doc["findings"], doc["evidence"]
    cited: set[str] = set()
    for item in nodes + edges + findings:
        cited.update(item["evidence"])
    for finding in findings:
        cited.update(finding.get("counterEvidence", []))
    unreferenced = [(f"evidence[{i}]", f"evidence {_shown(ev['id'])} is not cited by any node, edge or finding; cite it where it supports a claim, or remove it")
                    for i, ev in enumerate(evidence) if ev["id"] not in cited]
    for path, message in _capped(unreferenced, "evidence", "uncited evidence records"):
        _warn(warnings, "unreferenced_evidence", path, message)
    connected = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
    connected |= {node["parent"] for node in nodes if "parent" in node} | {node["id"] for node in nodes if "parent" in node}
    # A one-node diagram has nothing to connect to.
    isolated = [(f"nodes[{i}]", f"node {_shown(node['id'])} has no edge, parent or child; connect it to the step it affects or nest it under a group node "
                 "(a node that only records an absence or an external unknown can become a coverage limitation instead)")
                for i, node in enumerate(nodes) if len(nodes) > 1 and node["id"] not in connected]
    for path, message in _capped(isolated, "nodes", "isolated nodes"):
        _warn(warnings, "isolated_node", path, message)
    looped = [(f"edges[{i}]", f"edge {_shown(edge['id'])} connects node {_shown(edge['source'])} to itself; for an iteration, draw the loop edge from the last "
               "step of the repeated work back to its first step (or give a one-step repetition kind \"loop\"), otherwise connect two different nodes")
              for i, edge in enumerate(edges) if edge["source"] == edge["target"] and not (isinstance(edge.get("kind"), str) and edge["kind"].strip().lower() == "loop")]
    for path, message in _capped(looped, "edges", "self-edges"):
        _warn(warnings, "self_edge", path, message)
    wide = [(f"evidence[{i}]", f"evidence {_shown(ev['id'])} spans {ev['endLine'] - ev['line'] + 1} lines (more than {WIDE_EVIDENCE_LINES}); cite the narrowest range that contains the claim, or split it into several records")
            for i, ev in enumerate(evidence) if ev["endLine"] - ev["line"] + 1 > WIDE_EVIDENCE_LINES]
    for path, message in _capped(wide, "evidence", "wide evidence records"):
        _warn(warnings, "wide_evidence", path, message)
    overlap = [(f"findings[{i}].counterEvidence[{j}]", f"finding {_shown(finding['id'])} lists evidence {_shown(ref)} in both evidence and counterEvidence; keep it on the side it supports")
               for i, finding in enumerate(findings) for j, ref in enumerate(finding.get("counterEvidence", [])) if ref in finding["evidence"]]
    for path, message in _capped(overlap, "findings", "overlapping evidence references"):
        _warn(warnings, "evidence_overlap", path, message)
    first: dict[str, int] = {}
    repeated: list[tuple[str, str]] = []
    for i, value in enumerate(doc["coverage"]["inspectedFiles"]):
        if value in first:
            repeated.append((f"coverage.inspectedFiles[{i}]", f"{_shown(value, 500)} is already listed at coverage.inspectedFiles[{first[value]}]; list each file once"))
        else:
            first[value] = i
    for path, message in _capped(repeated, "coverage.inspectedFiles", "repeated inspected files"):
        _warn(warnings, "duplicate_inspected", path, message)


def basis_summary(doc: dict[str, Any]) -> dict[str, dict[str, int]]:
    """How many nodes, edges and findings are observed, inferred and unresolved (a valid document)."""
    return {name: {basis: sum(1 for item in doc[name] if item["basis"] == basis) for basis in ("observed", "inferred", "unresolved")}
            for name in ("nodes", "edges", "findings")}


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
    if not p.items:
        _hygiene(doc, notes)
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


class _TooDeep(ValueError):
    def __init__(self) -> None:
        super().__init__("nesting is too deep")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateMember(key)
        result[key] = value
    return result


class _MemberRecorder:
    """An object_pairs_hook that keeps the last value of a repeated member, as JSON.parse does, and
    records each repeat (at most MAX_DUPLICATE_MEMBERS) with the object that holds it."""

    def __init__(self) -> None:
        self.count = 0
        self.repeats: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                self.count += 1
                if len(self.repeats) < MAX_DUPLICATE_MEMBERS:
                    self.repeats.append((key, result))
            result[key] = value
        return result


def _load_json(text: str, recorder: _MemberRecorder | None = None) -> Any:
    """json.loads with the helper's rules: no NaN or Infinity and at most MAX_JSON_DEPTH levels.
    Members must be unique unless ``recorder`` is given, which keeps the last value and records the
    repeats. Raises ValueError (or RecursionError on very deep input)."""
    value = json.loads(text, object_pairs_hook=recorder if recorder is not None else _unique_object, parse_constant=_reject_constant)
    if _json_depth(value) > MAX_JSON_DEPTH:
        raise _TooDeep()
    return value


def _parse(raw: bytes) -> Any:
    """Parse a document with the CLI's rules (strict UTF-8, unique members, no NaN or Infinity, at
    most MAX_JSON_DEPTH levels), raising ValueError. Tests and the conformance bridge use it."""
    return _load_json(raw.decode("utf-8"))


def _member_paths(value: Any, repeats: list[tuple[str, dict[str, Any]]]) -> list[str | None]:
    """The document path of each repeated member (None when its object was itself overwritten)."""
    wanted = {id(holder) for _, holder in repeats}
    found: dict[int, str] = {}
    pending: list[tuple[Any, str]] = [(value, "")]
    while pending:
        current, at = pending.pop()
        if isinstance(current, dict):
            if id(current) in wanted:
                found.setdefault(id(current), at)
            pending.extend((child, f"{at}.{key}" if at else key) for key, child in current.items() if isinstance(child, (dict, list)))
        elif isinstance(current, list):
            pending.extend((child, f"{at}[{index}]") for index, child in enumerate(current) if isinstance(child, (dict, list)))
    paths: list[str | None] = []
    for key, holder in repeats:
        at = found.get(id(holder))
        paths.append(None if at is None else (f"{at}.{key}" if at else key)[:500])
    return paths


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


def _parse_input(raw: bytes, problems: Problems, label: str, at: str, *, last_wins: bool = False) -> Any:
    """Parse a draft or record, reporting each problem. A repeated member is always an error
    (invalid_json naming its location); with ``last_wins`` the value that keeps each member's last
    occurrence, which is how JSON.parse reads it, is still returned so the caller can report every
    other problem in the same round. Otherwise the result is _INVALID after any problem."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.add("draft_encoding", label, f"{label} file must be UTF-8 JSON")
        return _INVALID
    recorder = _MemberRecorder()
    try:
        value = _load_json(text, recorder)
    except json.JSONDecodeError as exc:
        problems.add("invalid_json", at, f"{exc.msg} at line {exc.lineno}, column {exc.colno}", line=exc.lineno, column=exc.colno)
        return _INVALID
    except (_TooDeep, RecursionError):
        problems.add("invalid_json", at, "nesting is too deep")
        return _INVALID
    except _NotJsonConstant as exc:
        problems.add("invalid_json", at, str(exc))
        return _INVALID
    except ValueError:
        problems.add("invalid_json", at, "the document is not valid JSON")
        return _INVALID
    if not recorder.count:
        return value
    continued = f"; the rest of the {label} was validated with its last value, as JSON.parse reads it" if last_wins else ""
    for (key, _holder), member in zip(recorder.repeats, _member_paths(value, recorder.repeats)):
        located = f" (at {member})" if member is not None and member != key else ""
        extra = {"member": member} if member is not None else {}
        problems.add("invalid_json", at, f"duplicate JSON member: {key[:200]}{located}{continued}", **extra)
    if recorder.count > len(recorder.repeats):
        problems.add("invalid_json", at, f"{recorder.count - len(recorder.repeats)} more duplicate JSON members are not listed")
    return value if last_wins else _INVALID


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
    # --record holds one record, or an array of records for the same collection that are applied in
    # order and validated once as a whole: all of them are written, or none.
    batch = record if isinstance(record, list) else [record]
    if not batch:
        print(json.dumps({"ok": False, "errors": [{"code": "record", "path": "record", "message": "record file must hold one record object or a non-empty array of records"}]})); return 1
    invalid = [{"code": "record", "path": f"record[{index}].id" if isinstance(record, list) else "record.id", "message": "record must be an object with a valid ID"}
               for index, item in enumerate(batch) if not isinstance(item, dict) or not _id(item.get("id"))]
    # One array lists each ID once: a repeat would silently replace a record the same batch added.
    seen_ids: dict[str, int] = {}
    for index, item in enumerate(batch):
        if isinstance(item, dict) and _id(item.get("id")):
            if item["id"] in seen_ids:
                invalid.append({"code": "record", "path": f"record[{index}].id",
                                "message": f"record ID {_shown(item['id'])} is already used by record[{seen_ids[item['id']]}]; list each ID once per record file"})
            else:
                seen_ids[item["id"]] = index
    if invalid:
        print(json.dumps({"ok": False, "errors": invalid}, sort_keys=True)); return 1
    edited = dict(doc)
    records = list(doc[collection])
    applied: list[dict[str, str]] = []
    for item in batch:
        matches = [index for index, existing in enumerate(records) if isinstance(existing, dict) and existing.get("id") == item["id"]]
        if len(matches) > 1:
            print(json.dumps({"ok": False, "errors": [{"code": "checkpoint_invalid", "path": collection, "message": "existing draft contains duplicate record IDs"}]})); return 1
        if matches: records[matches[0]] = item
        else: records.append(item)
        applied.append({"id": item["id"], "action": "replaced" if matches else "inserted"})
    edited[collection] = records
    edited.pop("verification", None)
    warnings: list[dict[str, str]] = []
    after_errors, _ = validate(edited, root, warnings=warnings, owned_files=(draft,))
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
    result: dict[str, Any] = {"ok": True, "errors": [], "draft": draft.relative_to(root).as_posix(), "collection": collection, "records": applied}
    if not isinstance(record, list):
        result.update(applied[0])
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, sort_keys=True)); return 0


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
    parts = value.split("/")
    if not value or "\\" in value or "\0" in value or pure.is_absolute() or ".." in parts:
        return "must stay within the workspace"
    if any(part in {"", "."} for part in parts):
        return 'must be a normalised workspace-relative path such as workflow.mlview.json, without "./", empty or trailing segments'
    if DRIVE_RE.match(value):
        return DRIVE_MESSAGE
    if not value.translate(_ASCII_LOWER).endswith(ARTIFACT_SUFFIX):
        return "must be a workspace-relative path ending in .mlview.json"
    return None


def _default_evidence_id(rel: str, cell: int | None, start: int, end: int) -> str:
    """A valid evidence ID derived from the path and range, for example ev-src-train.py-7e5d2a91-10-24.
    The slug keeps it readable; the first 8 hex digits of the path's SHA-256 keep apart paths whose
    slugs coincide (src/io.py and src-io.py, names in a non-Latin script, a truncated long path)."""
    digest = hashlib.sha256(rel.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    suffix = f"-{digest}" + (f"-c{cell}" if cell is not None else "") + f"-{start}" + (f"-{end}" if end != start else "")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", rel).strip("-.") or "file"
    return "ev-" + slug[-(128 - len("ev-") - len(suffix)):] + suffix


def _excerpt(value: str, lines_arg: str | None, cell: int | None, evidence_id: str | None, root: Path) -> int:
    """Print the evidence record validate would accept for a cited range. Read-only: it reads the
    cited file with validate's own rules and never writes, imports or runs anything."""
    p = Problems()
    match = LINES_RE.fullmatch(lines_arg) if lines_arg is not None else None
    if match is None:
        p.add("arguments", "--lines", "excerpt requires --lines START or START-END (one-based, inclusive)")
    if evidence_id is not None and not _id(evidence_id):
        p.add("id", "--id", "must match ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    located = _cited_text(value, cell, cell is not None, root, p, "file", "--cell", frozenset(), {}, {}) if not p.items else None
    if Path(value).is_absolute() or DRIVE_RE.match(value):
        for problem in p.items:
            if problem["path"] == "file":
                problem["message"] += "; pass the path relative to --workspace, as evidence[].file records it"
    if located is None or p.items or match is None:
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    rel, text, notebook = located
    lines = _lines(text)
    start = int(match.group(1)); end = int(match.group(2)) if match.group(2) is not None else start
    if start < 1 or end < start or end > len(lines):
        p.add("range", "--lines", f"line range is invalid for the cited source: need 1 <= START <= END <= {len(lines)}", maxLine=len(lines))
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    quote = "\n".join(lines[start - 1:end])
    # The record-level checks validate applies to evidence, so the printed record is accepted as printed.
    if len(rel) > MAX_EVIDENCE_PATH:
        p.add("limit", "file", f"must contain at most {MAX_EVIDENCE_PATH} characters, the longest evidence path a document may record")
    elif not _encodable(rel):
        p.add("text_encoding", "file", "the path contains an unpaired surrogate (bytes that are not UTF-8), which a document cannot record")
    if len(quote) > MAX_QUOTE:
        p.add("limit", "--lines", f"the excerpt has {len(quote)} characters; a quote holds at most {MAX_QUOTE}, so cite a narrower range")
    elif not _encodable(quote):
        p.add("text_encoding", "--lines", "the cited lines contain an unpaired surrogate, which validate refuses in a quote; cite lines without it")
    if p.items:
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    record: dict[str, Any] = {"id": evidence_id or _default_evidence_id(rel, cell if notebook else None, start, end), "file": rel}
    if notebook:
        record["cell"] = cell
    record.update({"line": start, "endLine": end, "quote": quote})
    print(json.dumps(record)); return 0


def _main(argv: list[str] | None) -> int:
    global _UMASK
    if sys.version_info < (3, 10):
        print(json.dumps({"ok": False, "errors": [{"code": "python_version", "path": "$", "message": "Python 3.10 or newer is required"}]})); return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "publish", "upsert", "excerpt"))
    parser.add_argument("draft", metavar="path", help="the draft (validate, publish, upsert) or the cited project file (excerpt)")
    parser.add_argument("--workspace", default="."); parser.add_argument("--output", default="workflow.mlview.json")
    parser.add_argument("--include-document", action="store_true", help="include the draft in successful validate output")
    parser.add_argument("--collection", choices=sorted(EDITABLE_COLLECTIONS))
    parser.add_argument("--record", help="JSON file holding one ID-bearing record, or an array of records for the same collection, for upsert")
    parser.add_argument("--lines", help="excerpt: one-based inclusive line range, START or START-END")
    parser.add_argument("--cell", type=int, help="excerpt: zero-based notebook cell index (.ipynb only)")
    parser.add_argument("--id", dest="evidence_id", help="excerpt: evidence ID for the printed record (default: derived from the path and range)")
    args = parser.parse_args(argv)
    # Read the process umask once; replacement files are given the mode a
    # plain write would have produced.
    _UMASK = os.umask(0); os.umask(_UMASK)
    root = Path(args.workspace).resolve()
    if not root.is_dir():
        print(json.dumps({"ok": False, "errors": [{"code": "workspace_path", "path": "--workspace", "message": "must be an existing directory (the VS Code workspace folder that will contain the artifact)"}]})); return 1
    if args.command == "excerpt":
        return _excerpt(args.draft, args.lines, args.cell, args.evidence_id, root)
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
    # A repeated member is an error, but the draft is still validated with each member's last value
    # (as JSON.parse reads it), so every other problem is reported in the same round.
    doc = _parse_input(raw_draft, p, "draft", "$", last_wins=True) if raw_draft is not None else _INVALID
    if doc is _INVALID:
        print(json.dumps({"ok": False, "errors": p.items}, sort_keys=True)); return 1
    # The draft and the artifact are MLView files under any name.
    owned_files: list[Path] = [draft]
    if args.command == "publish" and _output_problem(args.output) is None:
        owned_files.append(root.joinpath(*PurePosixPath(args.output).parts))
    warnings: list[dict[str, str]] = []
    errors, hashes = validate(doc, root, warnings=warnings, owned_files=owned_files)
    errors = p.items + errors
    if errors: print(json.dumps({"ok": False, "errors": errors}, sort_keys=True)); return 1
    if args.command == "validate":
        result: dict[str, Any] = {"ok": True, "errors": [], "revision": doc["revision"]["id"], "files": hashes, "basis": basis_summary(doc)}
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
