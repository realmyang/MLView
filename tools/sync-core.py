#!/usr/bin/env python
"""Vendor everything the two installable hosts must SHIP: the core, and the rule docs.

Two hosts ship a copy of the analyzer, for the same reason and under the same rule:

    analyzer/src/mlview/**   ->  claude-plugin/vendor/mlview/**      (PYTHONPATH for .mcp.json)
    analyzer/src/mlview/**   ->  vscode-extension/core/mlview/**     (PYTHONPATH for the VSIX)
    docs/rules/MLV*.md       ->  claude-plugin/docs/rules/MLV*.md

ONE of those two copies is tracked and one is BUILT (C2).
`claude-plugin/vendor/mlview` stays in git because `claude plugin install` copies
the plugin directory verbatim off a marketplace ref: whatever git holds is what
the user runs, so an untracked vendor directory is a plugin with no analyzer. It
goes away the day the `mlview` wheel is on PyPI and `.mcp.json` can depend on it.
`vscode-extension/core/mlview` is the opposite case: the VSIX is a build artifact
that `vsce package` produces from a working tree, so the copy only has to exist
at package time. It is gitignored, and `npm run compile`, `npm run package` and
`scripts/build.*` all run this script first so it is always there when it counts.

`claude-plugin/vendor` is what `.mcp.json` puts on PYTHONPATH, so a vendored core
is what lets the plugin work with **no pip install at all** (CONTRACTS A1, 6.2).
`vscode-extension/core` is the same idea for a marketplace install: PACKAGING's
precedence chain prefers an installed core and falls back to this one, so a user
with a bare Python 3.10+ and no MLView checkout still gets a diagram
(`docs/CONTRACTS.md §11.25`). Three copies of one analyzer only stay one
analyzer because `--check` is a gate: `tools/verify.py --all` runs it as the
`vendor: synced core` and `vsix: synced core` rows, and CI runs it directly.
`--check` holds a TRACKED copy to the source unconditionally; a BUILT copy that
nobody has built yet is reported as "not built" rather than as drift, because a
fresh clone legitimately has none (`tools/verify.py --vsix`, which runs after a
build, is the row that insists it exists).

The rule-doc copy is the plugin's equivalent of
`vscode-extension/tools/sync-rule-docs.mjs`. `mlview_explain(code=...)` resolves
`docs/rules/<CODE>.md` under the PLUGIN root and then the repo root; only the
first of those exists in a real `claude plugin install`, so without this step
every installed plugin returns an empty `doc` — and `skills/mlview-triage/SKILL.md`
builds its whole method on that page being there ("it carries the known
false-positive traps, which is what stops you from confidently reporting a
non-bug").

    python tools/sync-core.py            # copy all three
    python tools/sync-core.py --check    # exit 1 if any copy has drifted
    python tools/sync-core.py --quiet    # only report problems

The copy is idempotent and byte-exact: `__pycache__`, `*.pyc` and any `tests`
directory are skipped, files that already match are left alone, and files that
exist in the target but no longer exist in the source are deleted so a removed
module or a withdrawn rule page cannot linger.  Any `__pycache__` tree already
under a vendored root is pruned on every run: `claude plugin install` and
`vsce package` both copy the directory verbatim, and bytecode compiled from a
different revision must never ship beside the sources.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import os
import re
import shutil
import sys
from typing import Dict, List, NamedTuple, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO_ROOT, "analyzer", "src", "mlview")
TARGET = os.path.join(REPO_ROOT, "claude-plugin", "vendor", "mlview")
VENDOR_ROOT = os.path.join(REPO_ROOT, "claude-plugin", "vendor")
#: PACKAGING: the VSIX's bundled core. `pythonEnv.ts` puts this directory (not
#: `core/mlview`) on PYTHONPATH, exactly as `.mcp.json` does with `vendor`.
VSIX_TARGET = os.path.join(REPO_ROOT, "vscode-extension", "core", "mlview")
VSIX_ROOT = os.path.join(REPO_ROOT, "vscode-extension", "core")

DOCS_SOURCE = os.path.join(REPO_ROOT, "docs", "rules")
DOCS_TARGET = os.path.join(REPO_ROOT, "claude-plugin", "docs", "rules")
DOC_PAGE = re.compile(r"^MLV[0-9]{3}\.md$")

# `.mlview` is here for the same reason `__pycache__` is (HEALTH-01). Until C8
# the fact cache wrote `<root>/.mlview/cache` into whatever directory was
# analyzed, so anybody who once ran the analyzer over `analyzer/src/mlview` left
# a sidecar that this script would otherwise vendor into the plugin AND the
# shipped VSIX - and that inflated the file count `tools/verify.py --all` prints
# on one machine and not another (REV5-05 caught it as a 97-vs-96 disagreement
# between this Mac and CI). C8 moved the default to the user's cache directory,
# so no new sidecar appears here; the skip stays, because a checkout that
# predates C8 still has 277 of them and a rule that stops an artifact from being
# shipped is not one to delete the week the source of the artifact is fixed.
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".mlview", "tests"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".pyd")


class Copy(NamedTuple):
    """One vendored tree: where it goes, and what to call it in a message."""

    #: `vendor` / `vsix` — the word `tools/verify.py` names its gate row after.
    key: str
    #: `analyzer/src/mlview` -> this directory.
    target: str
    #: The directory that goes on PYTHONPATH (the target's parent), pruned of bytecode.
    root: str
    #: Repo-relative spelling, for the human-readable messages.
    label: str
    #: True when the copy is gitignored and produced at build time (C2). Absence is
    #: then a build that has not run, not drift, so `--check` says so and moves on.
    generated: bool


#: Every copy of `analyzer/src/mlview` this script owns, in table order.
COPIES: Tuple[Copy, ...] = (
    Copy("vendor", TARGET, VENDOR_ROOT, "claude-plugin/vendor/mlview", False),
    Copy("vsix", VSIX_TARGET, VSIX_ROOT, "vscode-extension/core/mlview", True),
)


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

    `tools/sync-core.py` owns `claude-plugin/vendor/` and `vscode-extension/core/`
    exclusively, and running the MCP server out of the first used to leave ~48 .pyc
    files behind that `claude plugin install` then copied into the distributed
    plugin.
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


def plan(target: str = TARGET) -> Tuple[List[str], List[str], List[str]]:
    """Return (to_copy, to_delete, unchanged) as relative paths."""
    src = _rel_files(SOURCE)
    dst = _rel_files(target)
    to_copy, unchanged = [], []
    for rel, full in src.items():
        existing = dst.get(rel)
        if existing is None:
            to_copy.append(rel)
        elif filecmp.cmp(full, existing, shallow=False):
            unchanged.append(rel)
        else:
            to_copy.append(rel)
    to_delete = sorted(rel for rel in dst if rel not in src)
    return sorted(to_copy), to_delete, sorted(unchanged)


def _sync_tree(copy: Copy) -> Tuple[int, int, int, int]:
    """Copy the core into one target. Returns (copied, deleted, unchanged, pruned)."""
    to_copy, to_delete, unchanged = plan(copy.target)
    for rel in to_copy:
        src_file = os.path.join(SOURCE, rel.replace("/", os.sep))
        dst_file = os.path.join(copy.target, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
        shutil.copyfile(src_file, dst_file)
    for rel in to_delete:
        try:
            os.remove(os.path.join(copy.target, rel.replace("/", os.sep)))
        except OSError as exc:
            print("sync-core: could not remove %s: %s" % (rel, exc), file=sys.stderr)
    # Prune directories that the deletions emptied.
    for dirpath, dirnames, filenames in os.walk(copy.target, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass
    return len(to_copy), len(to_delete), len(unchanged), prune_bytecode(copy.root)


def sync(quiet: bool = False) -> int:
    if not os.path.isdir(SOURCE):
        print("sync-core: source not found: %s" % SOURCE, file=sys.stderr)
        return 1
    for copy in COPIES:
        copied, deleted, unchanged, pruned = _sync_tree(copy)
        if not quiet:
            print(
                "sync-core: %d copied, %d deleted, %d already current -> %s"
                % (copied, deleted, unchanged, copy.label)
            )
            if pruned:
                print(
                    "sync-core: pruned %d __pycache__ directories under %s"
                    % (pruned, os.path.dirname(copy.label))
                )

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
            "sync-core: %d rule pages copied, %d deleted, %d already current -> %s"
            % (len(doc_copy), len(doc_delete), len(doc_same), DOCS_TARGET.replace("\\", "/"))
        )
    return 0


def _report_tree_drift(copy: Copy, to_copy: List[str], to_delete: List[str]) -> None:
    print(
        "sync-core: FAIL %s has drifted from analyzer/src/mlview" % copy.label,
        file=sys.stderr,
    )
    for rel in to_copy[:20]:
        print("  stale or missing: %s" % rel, file=sys.stderr)
    for rel in to_delete[:20]:
        print("  extra in copy:    %s" % rel, file=sys.stderr)
    extra = len(to_copy) + len(to_delete) - 40
    if extra > 0:
        print("  ... and %d more" % extra, file=sys.stderr)
    print("  fix: python tools/sync-core.py", file=sys.stderr)


def check_tree(copy: Copy) -> Tuple[bool, str]:
    """`(ok, detail)` for ONE vendored copy. Used by `tools/verify.py`'s gate rows.

    Strict on purpose, unlike `check()`: this is the gate row that runs after a
    build, so a generated copy that is missing is a build that did not happen and
    therefore a VSIX that would ship without an analyzer.
    """
    if not os.path.isdir(copy.target):
        if copy.generated:
            return False, (
                "%s does not exist — it is a gitignored build artifact; run "
                "`python tools/sync-core.py` (or `npm run compile` in "
                "vscode-extension, which does)" % copy.label
            )
        return False, "%s does not exist — run tools/sync-core.py" % copy.label
    to_copy, to_delete, unchanged = plan(copy.target)
    if to_copy or to_delete:
        return (
            False,
            "%s has drifted (%d stale/missing, %d extra) — run tools/sync-core.py"
            % (copy.label, len(to_copy), len(to_delete)),
        )
    return True, "%d files match analyzer/src/mlview" % len(unchanged)


def check(quiet: bool = False) -> int:
    unbuilt: List[str] = []
    for copy in COPIES:
        if not os.path.isdir(copy.target):
            if copy.generated:
                # C2: a build artifact nobody has built. `npm run compile`, `npm run
                # package` and `scripts/build.*` all produce it; a fresh clone that
                # has run none of them is not a drifted tree.
                unbuilt.append(copy.label)
                continue
            print(
                "sync-core: FAIL %s does not exist — run tools/sync-core.py" % copy.label,
                file=sys.stderr,
            )
            return 1
        to_copy, to_delete, _unchanged = plan(copy.target)
        if to_copy or to_delete:
            _report_tree_drift(copy, to_copy, to_delete)
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

    # Bytecode residue is not drift. Importing a vendored core in-process (a test,
    # the MCP server, `claude plugin validate`) writes `__pycache__` trees whenever
    # PYTHONDONTWRITEBYTECODE is unset; deleting them is always safe, so --check
    # prunes them and says so instead of turning the gate red (ROADMAP HEALTH-01).
    pruned = sum(prune_bytecode(copy.root) for copy in COPIES)
    if pruned and not quiet:
        print(
            "sync-core: pruned %d __pycache__ directories under the vendored cores "
            "(bytecode residue, not source drift)" % pruned
        )

    if not quiet:
        matched = len(plan(TARGET)[2])
        checked = [copy.label for copy in COPIES if copy.label not in unbuilt]
        where = ("each of %d copies (%s)" % (len(checked), ", ".join(checked))
                 if len(checked) > 1 else checked[0])
        print(
            "sync-core: OK %d files match analyzer/src/mlview in %s, "
            "%d rule pages match docs/rules" % (matched, where, len(doc_same))
        )
        for label in unbuilt:
            print(
                "sync-core: %s is not built (gitignored build artifact) — "
                "`npm run compile` in vscode-extension writes it" % label
            )
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-core",
        description=(
            "Vendor analyzer/src/mlview into claude-plugin/vendor/mlview and "
            "vscode-extension/core/mlview, and docs/rules/MLV*.md into "
            "claude-plugin/docs/rules."
        ),
    )
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 on drift")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args(argv)
    return check(args.quiet) if args.check else sync(args.quiet)


if __name__ == "__main__":
    sys.exit(main())
