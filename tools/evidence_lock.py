#!/usr/bin/env python3
"""Check, or append to, the lock of MLView's immutable evaluation evidence.

tools/evidence_lock.json pins the SHA-256 and size of every file under the evidence roots:
evals/workflow/development/, evals/workflow/fixtures/, evals/workflow/reference-candidates/*.json,
evals/workflow/reference-candidates/licenses/, samples/configured_training.mlview.json and
samples/configured_training/. Without options the tree is compared with the lock in both
directions. ``--add PATH...`` only appends: it locks new files (a directory adds every file
beneath it that is not locked yet) and refuses to change a locked entry or to lock a path
outside the roots. Editor and OS files (dot-files, __pycache__, *.pyc, *~, *.swp, *.swo,
Thumbs.db, desktop.ini) are never evidence and are ignored.

The lock proves bytes, not meaning: it is not a review, an approval or a semantic check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

try:
    from tools.eval_records import canonical_json, write_atomic
except ModuleNotFoundError:  # Run as a script: tools/ is on sys.path.
    from eval_records import canonical_json, write_atomic

ROOT = Path(__file__).resolve().parents[1]
LOCK = "tools/evidence_lock.json"
FORMAT = 1
DIRECTORY_ROOTS = (
    "evals/workflow/development",
    "evals/workflow/fixtures",
    "evals/workflow/reference-candidates/licenses",
    "samples/configured_training",
)
FILE_ROOTS = ("samples/configured_training.mlview.json",)
# Direct children with this suffix: the candidate ledgers, not the living README or guide.
CHILD_ROOTS = (("evals/workflow/reference-candidates", ".json"),)
JUNK_NAMES = {"__pycache__", "thumbs.db", "desktop.ini"}
JUNK_SUFFIXES = ("~", ".swp", ".swo", ".pyc")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")


def in_roots(rel: str) -> bool:
    """True when a repository-relative POSIX path lies under an evidence root."""
    if rel in FILE_ROOTS or any(rel.startswith(root + "/") for root in DIRECTORY_ROOTS):
        return True
    parent, _, name = rel.rpartition("/")
    return any(parent == directory and name.endswith(suffix) and name != suffix for directory, suffix in CHILD_ROOTS)


def is_junk(rel: str) -> bool:
    return any(part.startswith(".") or part.lower() in JUNK_NAMES or part.lower().endswith(JUNK_SUFFIXES)
               for part in rel.split("/"))


def entry(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def tree(root: Path = ROOT) -> tuple[dict[str, Path], list[str]]:
    """({rel: path} of every evidence file, [rel of every symbolic link]) under the roots."""
    files: dict[str, Path] = {}
    links: list[str] = []
    candidates = [root / rel for rel in FILE_ROOTS]
    for directory in DIRECTORY_ROOTS:
        base = root / directory
        if base.is_symlink():
            links.append(directory)
        elif base.is_dir():
            candidates.extend(base.rglob("*"))
    for directory, suffix in CHILD_ROOTS:
        base = root / directory
        if base.is_dir() and not base.is_symlink():
            candidates.extend(child for child in base.iterdir() if child.name.endswith(suffix))
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if is_junk(rel) or not in_roots(rel):
            continue
        if path.is_symlink():
            links.append(rel)
        elif path.is_file():
            files[rel] = path
    return dict(sorted(files.items())), sorted(links)


def load(root: Path = ROOT) -> dict[str, dict[str, object]]:
    """The locked {rel: {sha256, bytes}}; an absent lock is empty, a malformed one raises ValueError."""
    path = root / LOCK
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{LOCK} is not JSON: {exc}") from None
    if not isinstance(value, dict) or set(value) != {"format", "files"} or value["format"] != FORMAT or not isinstance(value["files"], dict):
        raise ValueError(f'{LOCK} must be {{"format": {FORMAT}, "files": {{path: {{"sha256", "bytes"}}}}}}')
    for rel, pinned in value["files"].items():
        if (not in_roots(rel) or is_junk(rel) or not isinstance(pinned, dict) or set(pinned) != {"sha256", "bytes"}
                or not isinstance(pinned["sha256"], str) or not DIGEST_RE.fullmatch(pinned["sha256"])
                or not isinstance(pinned["bytes"], int) or isinstance(pinned["bytes"], bool) or pinned["bytes"] < 0):
            raise ValueError(f"{LOCK} has a malformed entry: {rel}")
    return value["files"]


def check(root: Path = ROOT) -> list[str]:
    """Every difference between the evidence tree and the lock, one line each, naming the path."""
    locked = load(root)
    files, links = tree(root)
    problems = [f"symbolic link in the evidence roots: {rel}" for rel in links]
    for rel in sorted(locked.keys() - files.keys()):
        problems.append(f"locked evidence is missing: {rel}")
    for rel in sorted(files.keys() - locked.keys()):
        problems.append(f"not locked: {rel} (lock new evidence with: python tools/evidence_lock.py --add {rel})")
    for rel in sorted(files.keys() & locked.keys()):
        current = entry(files[rel])
        if current != locked[rel]:
            problems.append(f"changed: {rel} (locked sha256 {str(locked[rel]['sha256'])[:12]}, {locked[rel]['bytes']} bytes; "
                            f"now {str(current['sha256'])[:12]}, {current['bytes']} bytes). Evidence is immutable: restore it and add a new dated record instead.")
    return problems


def _relative(value: str, root: Path) -> str | None:
    """A repository-relative POSIX path: PATH is relative to the repository root, or absolute."""
    path = Path(value)
    if not path.is_absolute():
        rel = path.as_posix()
        return None if rel == ".." or rel.startswith("../") or "/../" in f"/{rel}/" else rel.rstrip("/")
    absolute = Path(os.path.abspath(path))
    for base in (Path(os.path.abspath(root)), root.resolve()):
        try:
            return absolute.relative_to(base).as_posix()
        except ValueError:
            continue
    return None


def _holds_evidence(rel_dir: str) -> bool:
    """True when a directory lies under an evidence root or contains one."""
    roots = DIRECTORY_ROOTS + FILE_ROOTS + tuple(directory for directory, _ in CHILD_ROOTS)
    return rel_dir in ("", ".") or any(root == rel_dir or root.startswith(rel_dir + "/") or rel_dir.startswith(root + "/") for root in roots)


def add(paths: list[str], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Append new evidence files to the lock; returns (added, already locked unchanged).

    Refuses, writing nothing, when any path is outside the roots, is not a regular file, or
    would change a locked entry."""
    locked = load(root)
    files, links = tree(root)
    selected: list[str] = []
    problems: list[str] = []
    for value in paths:
        rel = _relative(value, root)
        if rel is None:
            problems.append(f"{value}: outside the repository")
            continue
        path = root / rel
        if path.is_dir() and not path.is_symlink():
            if not _holds_evidence(rel):
                problems.append(f"{rel}: outside the evidence roots")
                continue
            prefix = "" if rel in ("", ".") else rel + "/"
            problems.extend(f"symbolic link in the evidence roots: {link}" for link in links if link.startswith(prefix))
            selected.extend(name for name in files if name.startswith(prefix))
            continue
        if not in_roots(rel):
            problems.append(f"{rel}: outside the evidence roots")
        elif is_junk(rel):
            problems.append(f"{rel}: editor or OS file, not evidence")
        elif path.is_symlink() or not path.is_file():
            problems.append(f"{rel}: not a regular file")
        else:
            selected.append(rel)
    added: dict[str, dict[str, object]] = {}
    unchanged: list[str] = []
    for rel in sorted(set(selected)):
        current = entry(root / rel)
        if rel not in locked:
            added[rel] = current
        elif locked[rel] == current:
            unchanged.append(rel)
        else:
            problems.append(f"{rel}: refusing to change a locked entry; evidence is immutable, so add a new dated record instead")
    if problems:
        raise ValueError("; ".join(problems))
    if added:
        write_atomic(root / LOCK, canonical_json({"format": FORMAT, "files": {**locked, **added}}))
    return sorted(added), unchanged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--add", nargs="+", metavar="PATH",
                        help="lock new evidence files; PATH is relative to the repository root (or absolute), "
                             "and a directory adds every evidence file beneath it that is not locked yet")
    args = parser.parse_args(argv)
    try:
        if args.add:
            added, unchanged = add(args.add)
            for rel in added:
                print(f"evidence-lock: locked {rel}")
            for rel in unchanged:
                print(f"evidence-lock: already locked, unchanged: {rel}")
            return 0
        problems = check()
    except (OSError, ValueError) as exc:
        print(f"evidence-lock: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"evidence-lock: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"evidence-lock: OK {len(load())} files match {LOCK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
