#!/usr/bin/env python
"""Vendor everything the Claude Code plugin must SHIP: the core, and the rule docs.

`claude-plugin/vendor` is what `.mcp.json` puts on PYTHONPATH, so a vendored core
is what lets the plugin work with **no pip install at all** (CONTRACTS A1, 6.2).

    analyzer/src/mlview/**   ->  claude-plugin/vendor/mlview/**
    docs/rules/MLV*.md       ->  claude-plugin/docs/rules/MLV*.md

The second copy is the plugin's equivalent of `vscode-extension/tools/sync-rule-docs.mjs`.
`mlview_explain(code=...)` resolves `docs/rules/<CODE>.md` under the PLUGIN root and
then the repo root; only the first of those exists in a real
`claude plugin install`, so without this step every installed plugin returns an empty
`doc` — and `skills/mlview-triage/SKILL.md` builds its whole method on that page being
there ("it carries the known false-positive traps, which is what stops you from
confidently reporting a non-bug").

    python tools/sync-core.py            # copy both
    python tools/sync-core.py --check    # exit 1 if either copy has drifted
    python tools/sync-core.py --quiet    # only report problems

The copy is idempotent and byte-exact: `__pycache__`, `*.pyc` and any `tests`
directory are skipped, files that already match are left alone, and files that
exist in the target but no longer exist in the source are deleted so a removed
module or a withdrawn rule page cannot linger.  Any `__pycache__` tree already
under `claude-plugin/vendor/` is pruned on every run: `claude plugin install` copies
the directory verbatim, and bytecode compiled from a different revision must never
ship beside the sources.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import os
import re
import shutil
import sys
from typing import Dict, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO_ROOT, "analyzer", "src", "mlview")
TARGET = os.path.join(REPO_ROOT, "claude-plugin", "vendor", "mlview")
VENDOR_ROOT = os.path.join(REPO_ROOT, "claude-plugin", "vendor")

DOCS_SOURCE = os.path.join(REPO_ROOT, "docs", "rules")
DOCS_TARGET = os.path.join(REPO_ROOT, "claude-plugin", "docs", "rules")
DOC_PAGE = re.compile(r"^MLV[0-9]{3}\.md$")

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", "tests"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".pyd")


def _rel_files(root: str) -> Dict[str, str]:
    """Every syncable file under ``root``, keyed by forward-slashed relative path."""
    found: Dict[str, str] = {}
    if not os.path.isdir(root):
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            found[rel] = full
    return found


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _doc_pages(root: str) -> Dict[str, str]:
    """`{MLV201.md: <abs path>}` for every rule page directly under ``root``."""
    found: Dict[str, str] = {}
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        if DOC_PAGE.match(name) and os.path.isfile(os.path.join(root, name)):
            found[name] = os.path.join(root, name)
    return found


def docs_plan() -> Tuple[List[str], List[str], List[str]]:
    """Return (to_copy, to_delete, unchanged) rule pages, as bare file names."""
    src = _doc_pages(DOCS_SOURCE)
    dst = _doc_pages(DOCS_TARGET)
    to_copy, unchanged = [], []
    for name, full in src.items():
        target = dst.get(name)
        if target is None or not filecmp.cmp(full, target, shallow=False):
            to_copy.append(name)
        else:
            unchanged.append(name)
    to_delete = sorted(name for name in dst if name not in src)
    return sorted(to_copy), to_delete, sorted(unchanged)


def prune_bytecode(root: str = VENDOR_ROOT) -> int:
    """Delete every `__pycache__` tree under ``root``; return how many were removed.

    `tools/sync-core.py` owns `claude-plugin/vendor/` exclusively, and running the
    MCP server out of it used to leave ~48 .pyc files behind that
    `claude plugin install` then copied into the distributed plugin.
    """
    removed = 0
    if not os.path.isdir(root):
        return 0
    for dirpath, dirnames, _ in os.walk(root, topdown=False):
        for name in list(dirnames):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, name), ignore_errors=True)
                removed += 1
    return removed


def plan() -> Tuple[List[str], List[str], List[str]]:
    """Return (to_copy, to_delete, unchanged) as relative paths."""
    src = _rel_files(SOURCE)
    dst = _rel_files(TARGET)
    to_copy, unchanged = [], []
    for rel, full in src.items():
        target = dst.get(rel)
        if target is None:
            to_copy.append(rel)
        elif filecmp.cmp(full, target, shallow=False):
            unchanged.append(rel)
        else:
            to_copy.append(rel)
    to_delete = sorted(rel for rel in dst if rel not in src)
    return sorted(to_copy), to_delete, sorted(unchanged)


def sync(quiet: bool = False) -> int:
    if not os.path.isdir(SOURCE):
        print("sync-core: source not found: %s" % SOURCE, file=sys.stderr)
        return 1
    to_copy, to_delete, unchanged = plan()
    for rel in to_copy:
        src_file = os.path.join(SOURCE, rel.replace("/", os.sep))
        dst_file = os.path.join(TARGET, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
        shutil.copyfile(src_file, dst_file)
    for rel in to_delete:
        try:
            os.remove(os.path.join(TARGET, rel.replace("/", os.sep)))
        except OSError as exc:
            print("sync-core: could not remove %s: %s" % (rel, exc), file=sys.stderr)
    # Prune directories that the deletions emptied.
    for dirpath, dirnames, filenames in os.walk(TARGET, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    pruned = prune_bytecode()

    doc_copy, doc_delete, doc_same = docs_plan()
    if _doc_pages(DOCS_SOURCE):
        os.makedirs(DOCS_TARGET, exist_ok=True)
        for name in doc_copy:
            shutil.copyfile(os.path.join(DOCS_SOURCE, name), os.path.join(DOCS_TARGET, name))
        for name in doc_delete:
            try:
                os.remove(os.path.join(DOCS_TARGET, name))
            except OSError as exc:
                print("sync-core: could not remove doc %s: %s" % (name, exc), file=sys.stderr)
    elif not quiet:
        # A source tarball without docs/ must not fail a build.
        print("sync-core: no rule pages under %s - nothing to ship" % DOCS_SOURCE.replace("\\", "/"))

    if not quiet:
        print(
            "sync-core: %d copied, %d deleted, %d already current -> %s"
            % (len(to_copy), len(to_delete), len(unchanged), TARGET.replace("\\", "/"))
        )
        print(
            "sync-core: %d rule pages copied, %d deleted, %d already current -> %s"
            % (len(doc_copy), len(doc_delete), len(doc_same), DOCS_TARGET.replace("\\", "/"))
        )
        if pruned:
            print("sync-core: pruned %d __pycache__ directories under vendor/" % pruned)
    return 0


def check(quiet: bool = False) -> int:
    if not os.path.isdir(TARGET):
        print("sync-core: FAIL vendor/mlview does not exist — run tools/sync-core.py", file=sys.stderr)
        return 1
    to_copy, to_delete, unchanged = plan()
    if to_copy or to_delete:
        print("sync-core: FAIL vendored core has drifted from analyzer/src/mlview", file=sys.stderr)
        for rel in to_copy[:20]:
            print("  stale or missing: %s" % rel, file=sys.stderr)
        for rel in to_delete[:20]:
            print("  extra in vendor:  %s" % rel, file=sys.stderr)
        extra = len(to_copy) + len(to_delete) - 40
        if extra > 0:
            print("  ... and %d more" % extra, file=sys.stderr)
        print("  fix: python tools/sync-core.py", file=sys.stderr)
        return 1
    doc_copy, doc_delete, doc_same = docs_plan()
    if doc_copy or doc_delete:
        print(
            "sync-core: FAIL claude-plugin/docs/rules has drifted from docs/rules",
            file=sys.stderr,
        )
        for name in doc_copy[:20]:
            print("  stale or missing: docs/rules/%s" % name, file=sys.stderr)
        for name in doc_delete[:20]:
            print("  extra in plugin:  docs/rules/%s" % name, file=sys.stderr)
        print("  fix: python tools/sync-core.py", file=sys.stderr)
        return 1

    # Bytecode residue is not drift. Importing the vendored core in-process (a test,
    # the MCP server, `claude plugin validate`) writes `__pycache__` trees whenever
    # PYTHONDONTWRITEBYTECODE is unset; deleting them is always safe, so --check
    # prunes them and says so instead of turning the gate red (ROADMAP HEALTH-01).
    pruned = prune_bytecode(VENDOR_ROOT)
    if pruned and not quiet:
        print(
            "sync-core: pruned %d __pycache__ directories under claude-plugin/vendor "
            "(bytecode residue, not source drift)" % pruned
        )

    if not quiet:
        print(
            "sync-core: OK %d files match analyzer/src/mlview, %d rule pages match docs/rules"
            % (len(unchanged), len(doc_same))
        )
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-core",
        description=(
            "Vendor analyzer/src/mlview into claude-plugin/vendor/mlview and "
            "docs/rules/MLV*.md into claude-plugin/docs/rules."
        ),
    )
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 on drift")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args(argv)
    return check(args.quiet) if args.check else sync(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
